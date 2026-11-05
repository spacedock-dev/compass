import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { chromium } from 'playwright';
import { openPage } from '../e2e/support/browser.mjs';
import { openDevelopmentStorybookPage } from './browser.mjs';

async function fixture() {
  const traffic = { requests: 0, upgrades: 0 };
  const sockets = new Set();
  let releaseHandshake;
  const handshake = new Promise((resolve) => {
    releaseHandshake = resolve;
  });
  const server = createServer((request, response) => {
    traffic.requests++;
    if (request.url === '/wait-for-socket') {
      const timeout = setTimeout(() => {
        response.setHeader('X-Socket-Upgrades', String(traffic.upgrades));
        response.writeHead(504).end('Socket handshake waited for the page main thread');
      }, 3000);
      response.on('close', () => clearTimeout(timeout));
      handshake.then(() => {
        clearTimeout(timeout);
        if (!response.writableEnded) {
          response.setHeader('X-Socket-Upgrades', String(traffic.upgrades));
          response.end('Socket handshake reached the server');
        }
      });
      return;
    }
    response.setHeader('Content-Type', 'text/html');
    response.end(request.url === '/' ? '<iframe src="/frame"></iframe>' : '<p>Frame</p>');
  });
  server.on('upgrade', (request, socket) => {
    traffic.upgrades++;
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    // Closing the owned context can reset a socket that the delayed bridge just opened.
    socket.on('error', (error) => {
      if (error.code !== 'ECONNRESET') throw error;
    });
    const accept = createHash('sha1')
      .update(request.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
      .digest('base64');
    socket.write(
      `HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`,
    );
    socket.write(Buffer.from([0x81, 2, 111, 107]));
    releaseHandshake();
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return {
    origin: `http://127.0.0.1:${server.address().port}`,
    traffic,
    async close() {
      for (const socket of sockets) socket.destroy();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

test('native Storybook sockets stay local in the manager and preview', {
  timeout: 15_000,
}, async () => {
  const allowed = await fixture();
  const denied = await fixture();
  let browser;
  try {
    browser = await chromium.launch();
    const opened = await openDevelopmentStorybookPage(browser, allowed.origin);
    try {
      await opened.page.goto(allowed.origin);
      for (const frame of opened.page.frames()) {
        const result = await frame.evaluate(
          async ({ allowed, denied }) => {
            const violations = [];
            document.addEventListener('securitypolicyviolation', (event) => {
              violations.push({ directive: event.effectiveDirective, uri: event.blockedURI });
            });
            const connect = (origin) =>
              new Promise((resolve) => {
                const socket = new WebSocket(origin.replace('http:', 'ws:') + '/socket');
                socket.onmessage = (event) => {
                  socket.close();
                  resolve(event.data);
                };
                socket.onerror = () => resolve('refused');
                socket.onclose = () => resolve('refused');
              });
            return { allowed: await connect(allowed), denied: await connect(denied), violations };
          },
          { allowed: allowed.origin, denied: denied.origin },
        );
        assert.equal(result.allowed, 'ok', JSON.stringify(opened.log.consoleErrors));
        assert.equal(result.denied, 'refused');
        assert.deepEqual(result.violations, [
          {
            directive: 'connect-src',
            uri: denied.origin.replace('http:', 'ws:') + '/socket',
          },
        ]);
      }
      const image = denied.origin + '/image';
      await opened.page.evaluate(
        (url) =>
          new Promise((resolve) => {
            const image = new Image();
            image.onerror = resolve;
            image.src = url;
          }),
        image,
      );
      assert.equal(allowed.traffic.upgrades, 2);
      assert.deepEqual(denied.traffic, { requests: 0, upgrades: 0 });
      assert.ok(opened.log.externalRequests.includes(image), 'HTTP requests remain blocked');
      assert.ok(
        opened.log.externalRequests.includes(denied.origin.replace('http:', 'ws:') + '/socket'),
      );
      assert.ok(
        opened.log.consoleErrors.some((error) => error.includes('Content Security Policy')),
      );
    } finally {
      await opened.close();
    }
  } finally {
    await browser?.close();
    await allowed.close();
    await denied.close();
  }
});

async function handshakeWhileMainThreadOccupied(open) {
  const allowed = await fixture();
  let browser;
  try {
    browser = await chromium.launch();
    const opened = await open(browser, allowed.origin);
    try {
      await opened.page.goto(allowed.origin);
      const result = await opened.page.evaluate((origin) => {
        const socket = new WebSocket(origin.replace('http:', 'ws:') + '/socket');
        // The server releases this synchronous request only after receiving the socket handshake.
        // A Playwright socket proxy needs the blocked renderer to run before it can connect.
        const barrier = new XMLHttpRequest();
        barrier.open('GET', origin + '/wait-for-socket', false);
        barrier.send();
        socket.close();
        return {
          status: barrier.status,
          upgrades: Number(barrier.getResponseHeader('X-Socket-Upgrades')),
        };
      }, allowed.origin);
      assert.deepEqual(opened.log.externalRequests, []);
      assert.deepEqual(opened.log.pageErrors, []);
      return {
        ...result,
        consoleErrors: opened.log.consoleErrors,
      };
    } finally {
      await opened.close();
    }
  } finally {
    await browser?.close();
    await allowed.close();
  }
}

test('the socket bridge waits for the occupied page main thread', { timeout: 15_000 }, async () => {
  const result = await handshakeWhileMainThreadOccupied(openPage);
  assert.equal(result.status, 504);
  assert.equal(result.upgrades, 0);
  assert.equal(result.consoleErrors.length, 1);
  assert.match(result.consoleErrors[0], /504/);
});

test('development sockets connect while the page main thread is occupied', {
  timeout: 15_000,
}, async () => {
  const result = await handshakeWhileMainThreadOccupied(openDevelopmentStorybookPage);
  assert.equal(result.status, 200, 'The socket handshake must not wait for the page main thread');
  assert.equal(result.upgrades, 1);
  assert.deepEqual(result.consoleErrors, []);
});
