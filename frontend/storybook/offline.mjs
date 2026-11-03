import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { once } from 'node:events';
import { chromium } from 'playwright';
import { openPage } from '../e2e/support/browser.mjs';
import { warmDevServer } from './warm.mjs';
const root = resolve('.storybook-build');
const types = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
};
const server = createServer(async (request, response) => {
  const path = resolve(root, '.' + new URL(request.url, 'http://127.0.0.1').pathname);
  if (path !== root && !path.startsWith(root + '/')) {
    response.writeHead(403).end();
    return;
  }
  try {
    const file = path === root ? resolve(root, 'index.html') : path;
    response.setHeader('Content-Type', types[extname(file)] ?? 'application/octet-stream');
    response.end(await readFile(file));
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await chromium.launch({ headless: true });
  const opened = await openPage(browser, origin);
  try {
    await opened.page.goto(`${origin}/?path=/story/ui-button--pending`);
    await opened.page.locator('iframe').waitFor();
    await opened.page.frameLocator('iframe').getByRole('button', { name: 'Saving…' }).waitFor();
    assert.deepEqual(opened.log.externalRequests, [], 'Storybook runtime must stay offline');
    assert.deepEqual(opened.log.consoleErrors, [], 'Storybook manager and preview console errors');
    assert.deepEqual(opened.log.pageErrors, [], 'Storybook manager and preview page errors');
    console.log('Storybook manager and interactive preview render offline without errors');
  } finally {
    await opened.close();
  }
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}

const dev = spawn(
  process.execPath,
  [
    fileURLToPath(import.meta.resolve('storybook/internal/bin/dispatcher')),
    'dev',
    '--config-dir',
    'frontend/.storybook',
    '--host',
    '127.0.0.1',
    '--port',
    '6006',
    '--exact-port',
    '--ci',
    '--no-open',
    '--no-version-updates',
  ],
  {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, STORYBOOK_DISABLE_TELEMETRY: '1', STORYBOOK_DISABLE_UPDATE_CHECK: '1' },
  },
);
let output = '';
dev.stdout.on('data', (bytes) => {
  output += bytes;
});
dev.stderr.on('data', (bytes) => {
  output += bytes;
});
let devBrowser;
try {
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      clearInterval(poll);
      reject(new Error(`Storybook startup timed out: ${output}`));
    }, 45_000);
    const poll = setInterval(() => {
      if (output.includes('Storybook ready!')) {
        clearInterval(poll);
        clearTimeout(timer);
        resolve();
      } else if (dev.exitCode !== null) {
        clearInterval(poll);
        clearTimeout(timer);
        reject(new Error(output));
      }
    }, 100);
  });
  // The followers' leader wait is 1000 ms and the first page load makes the server transform the preview,
  // so do that before the browser asks (frontend/storybook/warm.mjs says why).
  await warmDevServer('http://127.0.0.1:6006');
  devBrowser = await chromium.launch({ headless: true });
  const opened = await openPage(devBrowser, 'http://127.0.0.1:6006');
  try {
    await opened.page.goto('http://127.0.0.1:6006/?path=/story/ui-button--pending');
    await opened.page.frameLocator('iframe').getByRole('button', { name: 'Saving…' }).waitFor();
    assert.deepEqual(opened.log.externalRequests, [], 'Development Storybook must stay offline');
    assert.deepEqual(
      opened.log.consoleErrors,
      [],
      'Development manager and preview console errors',
    );
    assert.deepEqual(opened.log.pageErrors, [], 'Development manager and preview page errors');
    console.log('Development Storybook renders offline on 127.0.0.1:6006 without errors');
  } finally {
    await opened.close();
  }
} finally {
  await devBrowser?.close();
  if (dev.exitCode === null) {
    const closed = once(dev, 'exit');
    dev.kill('SIGTERM');
    const killTimer = setTimeout(() => dev.kill('SIGKILL'), 5000);
    try {
      await closed;
    } finally {
      clearTimeout(killTimer);
    }
  }
}
