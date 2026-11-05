import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { chromium } from 'playwright';
import { openPage } from '../e2e/support/browser.mjs';

async function fixture() {
  const traffic = { requests: 0, upgrades: 0 };
  const sockets = new Set();
  const server = createServer((request, response) => {
    traffic.requests++;
    response.setHeader('Content-Type', 'text/html');
    response.end(request.url === '/' ? '<iframe src="/frame"></iframe>' : '<p>Frame</p>');
  });
  server.on('upgrade', (request, socket) => {
    traffic.upgrades++;
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    const accept = createHash('sha1')
      .update(request.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
      .digest('base64');
    socket.write(
      `HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`,
    );
    socket.write(Buffer.from([0x81, 2, 111, 107]));
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
    const opened = await openPage(browser, allowed.origin, { nativeWebSockets: true });
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
