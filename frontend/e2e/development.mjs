import assert from 'node:assert/strict';
import { mkdtemp, cp, symlink, readFile, writeFile, mkdir, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { startDevelopment } from '../dev/supervisor.mjs';

const repository = fileURLToPath(new URL('../../', import.meta.url));
const copy = await mkdtemp(join(tmpdir(), 'compass-development-browser-'));
let dev, browser, context;
const external = [],
  errors = [],
  restartResets = [];
let restarting = false;
const failures = [];
try {
  await cp(join(repository, 'frontend'), join(copy, 'frontend'), { recursive: true });
  await cp(join(repository, 'compass'), join(copy, 'compass'), {
    recursive: true,
    filter: (path) =>
      !path.includes('/tests/') && !path.endsWith('/tests') && !path.includes('__pycache__'),
  });
  await symlink(
    join(repository, 'node_modules'),
    join(copy, 'node_modules'),
    process.platform === 'win32' ? 'junction' : 'dir',
  );
  // The shell's page component carries the fixture: it exports only a component, so React refresh can keep its state.
  const component = join(copy, 'frontend/src/shell/Page.tsx');
  const original = await readFile(component, 'utf8');
  const fixture = original
    .replace("import { useEffect } from 'react';", "import { useEffect, useState } from 'react';")
    .replace(
      'export function Page() {',
      'export function Page() {\n  const [count, setCount] = useState(0);',
    )
    .replace(
      '<main id="app">',
      '<main id="app"><button onClick={() => setCount(count + 1)}>Fixture count {count}</button><p>Compass fixture marker</p>',
    );
  assert.notEqual(fixture, original);
  await writeFile(component, fixture);
  dev = await startDevelopment({ root: copy, port: 4587, vitePort: 4588 });
  browser = await chromium.launch();
  context = await browser.newContext();
  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (
      [dev.origin, dev.viteOrigin].some((origin) => url.startsWith(origin + '/')) ||
      url.startsWith('data:')
    )
      return route.continue();
    external.push(url);
    return route.abort();
  });
  await context.routeWebSocket('**/*', (socket) => {
    if (socket.url().startsWith(dev.viteOrigin.replace('http:', 'ws:') + '/__compass_hmr'))
      socket.connectToServer();
    else {
      external.push(socket.url());
      socket.close({ code: 1008 });
    }
  });
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('response', async (response) => {
    if (response.status() < 400) return;
    // The body names the refusing layer: the worker's own guard answers "Development origin refused.", Vite's filesystem guard answers "403 Restricted".
    failures.push({
      url: response.url(),
      status: response.status(),
      body: (await response.text().catch(() => '')).slice(0, 600),
    });
  });
  // Stopping the owned backend resets the open event stream, and the page's own polls are refused until the new
  // backend answers. Chromium reports both as console errors, under different names by platform and timing
  // (a reset, a refusal, a closed or never-connected socket, an empty response, a body cut short of its
  // declared length). Only such an error on a Python API
  // read is set aside, only while the restart is in flight, and only up to a bound. A failure of any other resource
  // still fails the proof.
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const url = message.location().url;
    const apiRead = !url || url.endsWith('/api/stream') || url.endsWith('/api/data');
    if (
      restarting &&
      /net::ERR_(CONNECTION_(RESET|REFUSED|CLOSED|ABORTED)|SOCKET_NOT_CONNECTED|EMPTY_RESPONSE|CONTENT_LENGTH_MISMATCH)/.test(
        message.text(),
      ) &&
      apiRead &&
      restartResets.length < 40
    ) {
      restartResets.push(message.text());
    } else errors.push(message.text());
  });
  await page.goto(dev.origin);
  await page.getByText('Compass fixture marker').waitFor();
  const fonts = await page.evaluate(() => globalThis.document.fonts.size);
  assert.equal(fonts, 3);
  await page.getByRole('button', { name: 'Fixture count 0' }).click();
  await page.evaluate(() => {
    globalThis.__devDocumentSentinel = 'same document';
  });
  await writeFile(component, fixture.replace('Compass fixture marker', 'Hot refresh verified'));
  await page.getByText('Hot refresh verified').waitFor();
  await page.getByRole('button', { name: 'Fixture count 1' }).waitFor();
  assert.equal(await page.evaluate(() => globalThis.__devDocumentSentinel), 'same document');
  const first = await page.evaluate(async () => (await fetch('/api/data')).json());
  assert.match(first.build, /^react-dev-/);
  await page.evaluate(() => {
    globalThis.__devRevisions = [];
    globalThis.__devOpenCount = 0;
    globalThis.__devStream = new globalThis.EventSource('/api/stream');
    globalThis.__devStream.addEventListener('open', () => {
      globalThis.__devOpenCount++;
    });
    globalThis.__devStream.addEventListener('revision', (event) =>
      globalThis.__devRevisions.push(event.data),
    );
  });
  await page.waitForFunction(() => globalThis.__devRevisions.length > 0);
  const before = await page.evaluate(() => globalThis.__devRevisions.at(-1));
  const sessions = join(dev.scratch, 'codex/sessions/2026/10/07');
  await mkdir(sessions, { recursive: true });
  const sid = '11111111-1111-4111-8111-111111111111';
  const records = [
    { type: 'session_meta', payload: { id: sid, cwd: copy } },
    {
      timestamp: new Date().toISOString(),
      type: 'response_item',
      payload: {
        type: 'message',
        role: 'user',
        content: [{ type: 'input_text', text: 'Synthetic isolated developer fixture.' }],
      },
    },
  ];
  await writeFile(
    join(sessions, 'rollout-fixture.jsonl'),
    records.map((row) => JSON.stringify(row)).join('\n') + '\n',
  );
  await page.waitForFunction(async (target) => {
    const data = await (await fetch('/api/data')).json();
    return data.sessions.some((row) => row.sid === target);
  }, sid);
  await page.waitForFunction((previous) => globalThis.__devRevisions.at(-1) !== previous, before);
  const oldGeneration = dev.ready.generation;
  const oldOpenCount = await page.evaluate(() => globalThis.__devOpenCount);
  restarting = true;
  await dev.restart();
  assert.notEqual(dev.ready.generation, oldGeneration);
  await page.waitForFunction(
    async (oldBuild) => (await (await fetch('/api/data')).json()).build !== oldBuild,
    first.build,
  );
  await page.waitForFunction(
    (previous) =>
      globalThis.__devOpenCount > previous &&
      globalThis.__devStream.readyState === globalThis.EventSource.OPEN,
    oldOpenCount,
  );
  restarting = false;
  assert.equal(
    (
      await context.request.get(dev.origin + '/api/data', { headers: { Origin: dev.viteOrigin } })
    ).status(),
    403,
  );
  assert.equal((await context.request.get(dev.origin + '/@vite/client')).status(), 404);
  assert.equal(
    (
      await context.request.post(dev.origin + '/api/focus', {
        headers: { Origin: dev.viteOrigin },
        data: {},
      })
    ).status(),
    403,
  );
  await page.evaluate(() => globalThis.__devStream.close());
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
  await context.close();
  context = null;
  await dev.close();
  dev = null;

  // Separate fixture uses the real application's capability, HTTP guard and
  // lifecycle. Only its native raise callback is inert; normal pnpm dev keeps
  // focus/events disabled and has no injected focus capability.
  dev = await startDevelopment({
    root: copy,
    port: 4587,
    vitePort: 4588,
    backendHelper: join(copy, 'frontend/test/dev_capability_backend.py'),
  });
  context = await browser.newContext();
  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (
      [dev.origin, dev.viteOrigin].some((origin) => url.startsWith(origin + '/')) ||
      url.startsWith('data:')
    )
      return route.continue();
    external.push(url);
    return route.abort();
  });
  await context.routeWebSocket('**/*', (socket) => {
    if (socket.url().startsWith(dev.viteOrigin.replace('http:', 'ws:') + '/__compass_hmr'))
      socket.connectToServer();
    else {
      external.push(socket.url());
      socket.close({ code: 1008 });
    }
  });
  const capPage = await context.newPage();
  capPage.on('pageerror', (error) => errors.push(error.message));
  await capPage.goto(dev.origin);
  await capPage.getByText('Hot refresh verified').waitFor();
  const token = await capPage.locator('head meta[name="compass-focus"]').getAttribute('content');
  assert.match(token, /^[0-9a-f]{64}$/);
  const focus = async (capability) =>
    capPage.evaluate(async (value) => {
      const response = await fetch('/api/focus', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(value ? { 'X-Compass-Capability': value } : {}),
        },
        body: JSON.stringify({ harness: 'codex', sid: 'synthetic-missing-session' }),
      });
      return {
        status: response.status,
        body: response.status === 200 ? await response.json() : null,
      };
    }, capability);
  assert.equal((await focus(null)).status, 403);
  assert.equal((await focus('00'.repeat(32))).status, 403);
  assert.deepEqual(await focus(token), { status: 200, body: { focused: false } });
  assert.equal(
    (
      await context.request.post(dev.origin + '/api/focus', {
        headers: {
          Origin: dev.viteOrigin,
          'X-Compass-Capability': token,
        },
        data: { harness: 'codex', sid: 'synthetic-missing-session' },
      })
    ).status(),
    403,
  );
  await dev.restart();
  await capPage.reload();
  await capPage.getByText('Hot refresh verified').waitFor();
  const renewedToken = await capPage
    .locator('head meta[name="compass-focus"]')
    .getAttribute('content');
  assert.notEqual(renewedToken, token);
  assert.equal((await focus(token)).status, 403);
  assert.deepEqual(await focus(renewedToken), { status: 200, body: { focused: false } });
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify(
      {
        development: {
          realPython: true,
          hotRefreshPreservedState: true,
          fonts,
          collectorFixtureObserved: true,
          realSseRevision: true,
          backendRestart: true,
          sseReconnected: true,
          externalRequests: 0,
          modelsAndUsageDisabled: true,
          nativeActionsDisabled: true,
          restartConsoleResetsSetAside: restartResets.length,
        },
        inertCapabilityFixture: {
          actualInjection: true,
          missingAndWrongRefused: true,
          crossOriginRefused: true,
          renewedAfterRestart: true,
          staleRefused: true,
          authorizedResponseFocused: false,
          nativeRaiseInert: true,
        },
      },
      null,
      2,
    ),
  );
} catch (error) {
  console.error(JSON.stringify({ errors, failures, external }));
  throw error;
} finally {
  if (context) await context.close();
  if (browser) await browser.close();
  if (dev) await dev.close();
  await rm(copy, { recursive: true, force: true });
}
