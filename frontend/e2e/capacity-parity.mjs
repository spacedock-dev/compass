/*
 * The capacity strip, the quota line and the observer-model consent in a real browser, against the real
 * backend (DRC-4827, capacity half; the quota line restated 2026-10-27).
 *
 * The React page runs in Chromium over a synthetic board (`frontend/test/capacity_backend.py`) whose backend
 * counts what matters to a person who was promised a disclosure: the requests that carried `usage=1` to the
 * application and the project-context requests that carried the observer-model consent. A differential then
 * compares what a reader can observe (the strip's rows, the consent controls) with what the previous interface
 * said of the same board, from `frontend/test/golden/e2e/capacity-parity.json` (`support/golden.mjs`), a
 * recording that cannot be remade because that interface is gone. The React page is held to every assertion.
 *
 * Where a loop once ran the same absolute assertions on both pages (a consent that sends no parameter, a selected
 * window that survives a reorder, a layout that fits), the React page now carries each such assertion whole: they
 * state what must hold rather than compare two pages. What is compared with the recording stays: the disclosure
 * sentence, the strip's keys, ticks, sub-limits and wording. Dropped with the previous interface: its overflow
 * measures and keyboard traces, which were only recorded as notes, its screenshots, and, in the development run,
 * its origin standing in as the second origin of "the answer is per origin" (the production run opens the React
 * page at a second origin instead).
 *
 * The quota fetch is on until the reader turns it off (SECURITY.md, Usage quota reads, amended 2026-10-27), so the
 * recorded question is read only to hold the page to its absence. What a unit test cannot see is proved here:
 * that every board read carries the usage parameter through a mount, a route change, a reload and a reconnect;
 * that Turn off stops it at the next request and is kept across a reload, and Turn on brings it back at the next
 * one; that the choice is per origin;
 * that the selected window survives a redraw that reorders it and a route change; that allowing the observer
 * model sends nothing and that one press of Summarize sends one request for the exact session; that nothing
 * posts, raises a terminal or notifies; and that the layout holds at 320 and 375 CSS px.
 *
 * No model is called, no credential is read and no vendor is contacted: the backend answers from fixed numbers
 * and records the request instead of acting on it. `Notification` is a script that records and shows nothing.
 * Run with `pnpm test:capacity:browser`; `COMPASS_E2E_STEPS=<regex>` runs only the steps whose name matches,
 * `COMPASS_SCREENSHOTS=1` writes captures to docs/screenshots/, and `COMPASS_MUTATION=<name>` applies one
 * deliberate break (see MUTATIONS), which must make the run FAIL.
 */
import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import { goldenFor } from './support/golden.mjs';
import { PRODUCTION, startReactWorld } from './support/world.mjs';
import { focusedLabel, freePorts, openPage, REPOSITORY, tabTo } from './support/browser.mjs';

/* Every fixed wait here means "give the page time to react". A hosted runner has a few shared cores and delivers
   events later than a desktop, so each wait is tripled there; only a pass gets slower. */
const golden = goldenFor('capacity-parity');
const patience = (ms) => (process.env.CI ? ms * 3 : ms);
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, patience(ms)));

const SHOTS = join(REPOSITORY, 'docs/screenshots');
const shots = process.env.COMPASS_SCREENSHOTS === '1';
const only = process.env.COMPASS_E2E_STEPS ? new RegExp(process.env.COMPASS_E2E_STEPS) : null;

/* One break each, applied to the scratch copy only. A missing needle fails the run loudly rather than silently
   testing nothing. */
const MUTATIONS = {
  'figure-becomes-verdict': [
    ['src/capacity/CapacityStrip.tsx', '{`${String(row.pct)}%`}', "{'safe'}"],
  ],
  // The strip's rows keep their wide desktop columns on a narrow window: the page scrolls sideways.
  'strip-wide-columns': [
    [
      'src/capacity/capacity.css',
      '.next-capacity-row{position:relative;',
      '.next-capacity-row{position:relative;min-width:560px;',
    ],
  ],
  // A window row and the consent answers answer a pointer press and nothing else.
  'window-pointer-only': [
    [
      'src/capacity/CapacityStrip.tsx',
      'onClick={() => onPick(key)}',
      'onMouseDown={() => onPick(key)}',
    ],
  ],
  'answer-pointer-only': [
    [
      'src/capacity/UsageConsent.tsx',
      "onClick={() => answer(on ? 'declined' : 'granted')}",
      "onMouseDown={() => answer(on ? 'declined' : 'granted')}",
    ],
  ],
  // The fetch waits for a yes again: an unanswered origin sends no usage parameter. Since 2026-10-27 the fetch
  // is on until turned off, so this is the break.
  'unanswered-is-no': [
    [
      'src/transport/runtime.ts',
      "usage: storage.usageConsent() !== 'declined',",
      "usage: storage.usageConsent() === 'granted',",
    ],
  ],
  // Turned off, the line vanishes, so the reader has no way to turn it back on.
  'off-hides-the-line': [
    [
      'src/capacity/UsageConsent.tsx',
      'if (!offered) return null;',
      "if (!offered || consent === 'declined') return null;",
    ],
  ],
  // Turning summaries back on also asks the model for one.
  'turn-on-sends': [
    [
      'src/capacity/ObserverControls.tsx',
      "    heldFor(runtime).observer.answer('granted');\n  };",
      "    heldFor(runtime).observer.answer('granted');\n    summarize();\n  };",
    ],
  ],
  // The observer model is asked for a summary as soon as the controls are drawn, without a press.
  'observer-on-mount': [
    [
      'src/capacity/ObserverControls.tsx',
      'const model = selectObserverModel(entry);',
      "useEffect(() => {\n    if (identity && heldFor(runtime).observer.read() !== 'declined')\n      void runtime.requestObserverSummary({ projectKey, focus: identity });\n  }, [entry]);\n  const model = selectObserverModel(entry);",
    ],
  ],
  // The selection is not kept: the first window is always the selected one.
  'selection-forgotten': [
    [
      'src/capacity/model.ts',
      'const selected = rows.find((row) => rowKey(row) === key) ?? first;',
      'const selected = first;',
    ],
  ],
  // A fallback is not held: the stored selection is never written back.
  'fallback-not-held': [
    ['src/capacity/CapacityStrip.tsx', 'if (read) lane.set(selectedKey);', 'void read;'],
  ],
  // A row with no clock is given a tick at the middle of its bar.
  'invented-tick': [
    [
      'src/capacity/CapacityStrip.tsx',
      'if (row.elapsed === null) {\n    return (',
      'if (row.elapsed === null && row.pct < 0) {\n    return (',
    ],
  ],
};

const results = {};
const failures = [];
async function step(name, run) {
  if (only && !only.test(name)) return;
  const started = Date.now();
  try {
    const detail = await run();
    results[name] = {
      ok: true,
      ms: Date.now() - started,
      ...(detail === undefined ? {} : { detail }),
    };
  } catch (error) {
    results[name] = { ok: false, ms: Date.now() - started };
    failures.push({
      name,
      message: String(error.message || error)
        .split('\n')
        .slice(0, 6)
        .join(' | ')
        .slice(0, 1800),
    });
  }
}

/* Waits for a condition read from the page or the server, and says what it was waiting for. */
async function until(read, what, timeout = patience(12000)) {
  const deadline = Date.now() + timeout;
  let last;
  for (;;) {
    try {
      last = await read();
      if (last) return last;
    } catch (error) {
      last = error.message;
    }
    if (Date.now() > deadline)
      throw new Error(
        `Never saw ${what}${last === undefined ? '' : ` (last: ${JSON.stringify(last)})`}`,
      );
    await new Promise((resolve) => setTimeout(resolve, 80));
  }
}

/* ---- the world: one backend serving the page, over a scratch copy of the tree ---- */
async function startWorld({ mutation = process.env.COMPASS_MUTATION || '' } = {}) {
  /* Development mounts the capacity harness (`capacity-harness.tsx`) in a scratch copy, so the strip, the usage consent
     and the observer controls are driven apart from the page that hosts them. The production run serves the page
     readers get instead, and drives each surface through its real mount point: the strip in the Sessions view, the
     consent and observer controls in the Console tab. Without a mutation that page is the tracked `react.html`
     itself; a mutation needs a scratch copy, which is packaged with the same build. */
  const shipped = PRODUCTION;
  const ownsRepository = shipped && !mutation;
  const copy = ownsRepository
    ? REPOSITORY
    : await mkdtemp(join(tmpdir(), 'compass-capacity-browser-'));
  let dev = null;
  const world = { copy, mutation, close };
  async function close() {
    if (dev) await dev.close();
    if (!ownsRepository) await rm(copy, { recursive: true, force: true });
  }
  try {
    if (!ownsRepository) {
      await cp(join(REPOSITORY, 'frontend'), join(copy, 'frontend'), {
        recursive: true,
        filter: (path) =>
          !path.includes('/fixtures') &&
          !path.includes('/test-results') &&
          !path.includes('__pycache__'),
      });
      await cp(join(REPOSITORY, 'compass'), join(copy, 'compass'), {
        recursive: true,
        filter: (path) =>
          !path.includes('/tests/') && !path.endsWith('/tests') && !path.includes('__pycache__'),
      });
      await symlink(
        join(REPOSITORY, 'node_modules'),
        join(copy, 'node_modules'),
        process.platform === 'win32' ? 'junction' : 'dir',
      );
      if (!shipped)
        await writeFile(join(copy, 'frontend/src/main.tsx'), "import '../e2e/capacity-harness';\n");
    }
    assert.ok(!mutation || MUTATIONS[mutation], `unknown mutation ${mutation}`);
    for (const [file, needle, replacement] of MUTATIONS[mutation] ?? []) {
      const path = join(copy, 'frontend', file);
      const text = await readFile(path, 'utf8');
      assert.ok(text.includes(needle), `mutation ${mutation}: needle not found in ${file}`);
      await writeFile(path, text.replace(needle, replacement));
    }

    const helper = join(copy, 'frontend/test/capacity_backend.py');
    /* A sibling run can bind a port between the check that it is free and the bind itself; startup then fails
       loudly rather than adopting someone else's listener. Try again on other ports, a few times. */
    const refused = [];
    let ports;
    for (let attempt = 0; ; attempt += 1) {
      ports = await freePorts(2, refused);
      try {
        dev = await startReactWorld({
          root: copy,
          port: ports[0],
          vitePort: ports[1],
          backendHelper: helper,
        });
        break;
      } catch (error) {
        refused.push(...ports);
        if (
          attempt >= 3 ||
          !/in use|EADDRINUSE|belongs to another|backend exited|readiness/i.test(
            String(error.message),
          )
        )
          throw error;
      }
    }
    world.react = {
      name: 'react',
      origin: dev.origin,
      viteOrigin: dev.viteOrigin,
      state: join(dev.scratch, 'state'),
    };

    return world;
  } catch (error) {
    await close();
    throw error;
  }
}

/* What a backend counted since it started, and the board a test asks it to publish next. */
async function eventsOf(side, kind) {
  try {
    const text = await readFile(join(side.state, 'capacity-fixture/events.ndjson'), 'utf8');
    return text
      .split('\n')
      .filter(Boolean)
      .map((line) => JSON.parse(line))
      .filter((event) => event.event === kind);
  } catch {
    return [];
  }
}
/* The board is published at most every 2.5 s and announced to a page only when it changes, so a steer that changes
   the windows waits that long and reads the board once itself: waiting for the page's own fallback poll took
   several seconds a step. A steer that changes only what the project context says is read on the next request. */
async function steer(side, control, { board = true } = {}) {
  await mkdir(join(side.state, 'capacity-fixture'), { recursive: true });
  await writeFile(join(side.state, 'capacity-fixture/control.json'), JSON.stringify(control));
  if (!board) return;
  await new Promise((resolve) => setTimeout(resolve, 2700));
  await fetch(`${side.origin}/api/data`, { signal: AbortSignal.timeout(5000) }).then((r) =>
    r.arrayBuffer(),
  );
}

/* A script in place of the browser's Notification: it records what a page asks of it and shows nothing, so the
   test can state that no surface here asked for permission or made one. */
const SCRIPTED_NOTIFICATION = `
  globalThis.__notified = [];
  globalThis.Notification = class {
    static permission = 'default';
    static requestPermission() { globalThis.__notified.push('requestPermission'); return Promise.resolve('default'); }
    constructor(title) { globalThis.__notified.push('construct:' + title); }
    close() {}
  };
`;

const E = encodeURIComponent;
const SESSIONS = '#n=sessions';
const CONSOLE = `#n=project:${E('alpha/app')}:${E('claude:live-work')}:console`;
const ELSEWHERE = '#n=projects';

async function open(browser, side, extra = []) {
  const opened = await openPage(browser, [side.origin, side.viteOrigin ?? side.origin, ...extra], {
    viewport: { width: 1100, height: 900 },
    reducedMotion: 'reduce',
  });
  await opened.context.addInitScript(SCRIPTED_NOTIFICATION);
  // `reset()` clears the shared log between steps; this one never is, so the closing checks see every request.
  const everything = [];
  opened.page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.protocol !== 'data:')
      everything.push({ method: request.method(), path: url.pathname + url.search });
  });
  return { ...opened, side, everything };
}

async function go(view, fragment) {
  const { page, side } = view;
  await page.goto('about:blank');
  await page.goto(`${side.origin}/${fragment}`);
  try {
    await page.waitForSelector('nav[aria-label="Primary"]', { timeout: patience(15000) });
  } catch (error) {
    const body = await page.evaluate(() => globalThis.document.body.innerText.slice(0, 300));
    throw new Error(
      `${side.name} never drew its navigation (${page.url()}): ${body} ${JSON.stringify([...view.log.pageErrors, ...view.log.consoleErrors]).slice(0, 600)}`,
      {
        cause: error,
      },
    );
  }
}

/* The route change a link makes, which is a hash change and a real unmount. */
async function navigate(view, fragment) {
  await view.page.evaluate((hash) => {
    globalThis.location.hash = hash;
  }, fragment);
}

/* ---- what a reader can observe ---- */
const stripOf = (page) =>
  page.evaluate(() => {
    const text = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : null);
    const section = globalThis.document.querySelector('[data-next-capacity]');
    if (!section) return null;
    return {
      rows: [...section.querySelectorAll('[data-next-capacity-row]')].map((row) => ({
        key: row.dataset.nextCapacityRow,
        pressed: row.querySelector('button')?.getAttribute('aria-pressed') === 'true',
        text: text(row),
        tick: Boolean(row.querySelector('.next-capacity-tick')),
        noclock: Boolean(row.querySelector('.next-capacity-noclock')),
      })),
      more: text(section.querySelector('.next-capacity-more')),
      prospect: text(section.querySelector('.next-capacity-prospect')),
      models: [...section.querySelectorAll('[data-next-capacity-models]')].map(text),
    };
  });
/* The quota line (`data-next-usage-switch`, `on` or `off`) and the retired question, which must stay gone. */
const consentOf = (page) =>
  page.evaluate(() => {
    const text = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : null);
    const { document } = globalThis;
    const line = document.querySelector('[data-next-usage-switch]');
    return {
      disclosure: text(document.querySelector('[data-next-usage-consent]')),
      line: text(line),
      state: line?.getAttribute('data-next-usage-switch') ?? null,
    };
  });
// The sentence and the button label, which `textContent` joins with no space between them.
const ON_LINE =
  /^Quota is read with the Claude Code and Cursor logins on this machine\. No session content is sent\.\s*Turn off$/;
const OFF_LINE =
  /^Quota reading is off\. (?:Windows above are the last cached read and will lapse|No window has been read)\.\s*Turn on$/;
const withoutUsage = (view) => dataRequests(view).filter((r) => !/[?&]usage=1(&|$)/.test(r.path));
const dataRequests = (view) => view.log.requests.filter((r) => r.path.startsWith('/api/data'));
const usageRequests = (view) => dataRequests(view).filter((r) => /[?&]usage=/.test(r.path));
const modelRequests = (view) =>
  view.log.requests.filter(
    (r) => r.path.startsWith('/api/project-context') && /observer_model=1/.test(r.path),
  );
const pressUsage = (view, answer) =>
  view.page.locator(`[data-next-usage-answer="${answer}"]`).first().click();
const pressedKey = async (view) => (await stripOf(view.page))?.rows.find((r) => r.pressed)?.key;
const pressWindow = (view, key) =>
  view.page.locator(`[data-next-capacity-row="${key}"] button`).first().click();
const observerText = (page) =>
  page.evaluate(() => {
    const section = globalThis.document.querySelector('[data-next-observer-controls]');
    if (section) return section.textContent.replace(/\s+/g, ' ').trim();
    const empty = [...globalThis.document.querySelectorAll('.next-cockpit-empty')]
      .map((node) => node.textContent.replace(/\s+/g, ' ').trim())
      .filter((text) => /^(Observer|Select one exact session to request)/.test(text));
    return empty.join(' | ') || null;
  });
const observerButtons = (page) =>
  page.evaluate(() =>
    [...globalThis.document.querySelectorAll('[data-next-observer-action]')].map((button) => ({
      action: button.dataset.nextObserverAction,
      label: button.textContent.trim(),
      disabled: button.disabled,
    })),
  );

let world;
let browser;
try {
  world = await startWorld();
  browser = await chromium.launch();
  const side = world.react;

  /* One tracked page for the strip and the usage consent, and one fresh profile per consent path, so
     an answer given in one step cannot stand in for the question in the next. */
  const view = await open(browser, side);
  await go(view, SESSIONS);

  /* The production run is only worth its name if the surfaces it drives are the ones the shipped page mounts. This
     reads each one inside the view that hosts it: the strip in the Sessions view and the consent in the project
     page's Console tab, on a page that carries no test hook. The development run mounts the harness instead. */
  if (PRODUCTION)
    await step(
      'shipped page: the strip is mounted by the Sessions view and the quota line by the Console tab',
      async () => {
        await until(
          () => view.page.locator('[data-next-view-body="sessions"] [data-next-capacity]').count(),
          'the strip inside the Sessions view',
        );
        const console_ = await open(browser, world.react);
        try {
          await go(console_, CONSOLE);
          await until(
            () =>
              console_.page
                .locator('[data-next-view-body="project"] [data-next-usage-switch]')
                .count(),
            'the quota line inside the Console tab',
          );
        } finally {
          await console_.close();
        }
      },
    );

  /* Since 2026-10-27 the quota fetch is on until the reader turns it off (SECURITY.md, Usage quota reads): one
     line says what is read and that no session content is sent, beside Turn off. The recording holds the retired
     page's question, which the page must no longer ask; it is read so the recording stays accounted for, and the
     React page is held to the opposite of it. */
  await step(
    'the quota line is drawn and every board read carries usage=1 from the first',
    async () => {
      await until(async () => (await consentOf(view.page)).line, 'the quota line');
      await until(async () => (await stripOf(view.page))?.rows.length, 'the strip');
      await until(() => dataRequests(view).length > 0, `${side.name} the first read`);
      assert.deepEqual(withoutUsage(view), [], `${side.name}: a board read without usage=1`);
      await until(
        async () => (await eventsOf(side, 'usage_fetch')).length > 0,
        `${side.name} the server counting it`,
      );
      const state = await consentOf(view.page);
      assert.equal(state.state, 'on');
      assert.match(state.line, ON_LINE);
      assert.equal(state.disclosure, null, `${side.name}: the retired question is drawn`);
      const recorded = golden.observe('the unanswered disclosure: the legacy sentence');
      assert.match(String(recorded), /Read your quota from the vendor\?/);
    },
  );

  await step('a route change, a reload and a reconnect keep reading it', async () => {
    await navigate(view, ELSEWHERE);
    await pause(300);
    await navigate(view, SESSIONS);
    await until(async () => (await stripOf(view.page))?.rows.length, 'the strip after a return');
    await view.page.reload();
    await until(async () => (await consentOf(view.page)).line, 'the quota line after a reload');
    // A reconnect: the page loses the network, then regains it, and reads the board again.
    const before = dataRequests(view).length;
    await view.context.setOffline(true);
    await pause(1200);
    await view.context.setOffline(false);
    view.page.evaluate(() => globalThis.dispatchEvent(new Event('online'))).catch(() => undefined);
    await until(
      () => dataRequests(view).length > before,
      `${side.name} reading the board again after reconnecting`,
      patience(20000),
    );
    assert.deepEqual(withoutUsage(view), [], `${side.name}: a board read without usage=1`);
  });

  await step(
    'Turn off sends no parameter, says the windows will lapse, and is kept across a reload',
    async () => {
      // Pressed while quota is on, so a poll can land between a reset and the press; the count starts once
      // the line says off, with the read the reload asks for.
      await pressUsage(view, 'declined');
      await until(
        async () => (await consentOf(view.page)).state === 'off',
        `${side.name} the line turned off`,
      );
      view.reset();
      await view.page.reload();
      await until(
        () => dataRequests(view).length > 0,
        `${side.name} reading the board after the press`,
      );
      assert.match((await consentOf(view.page)).line, OFF_LINE);
      const frozen = (await eventsOf(side, 'usage_fetch')).length;
      await pause(2000);
      assert.deepEqual(usageRequests(view), [], `${side.name}: turned off and still sent usage=1`);
      await view.page.reload();
      await until(
        async () => (await consentOf(view.page)).state === 'off',
        'the line still off after a reload',
      );
      assert.deepEqual(usageRequests(view), []);
      assert.equal(
        (await eventsOf(side, 'usage_fetch')).length,
        frozen,
        `${side.name}: still fetching`,
      );
    },
  );

  await step('the choice is per origin: turning it off on one leaves another on', async () => {
    /* The second origin. The shipped page serves everything from one origin, so the same React server under
       another loopback name (`localhost`, which this server admits) is a second origin to the browser. The
       development page loads its modules from a Vite server that answers only the first origin, so there the
       React page cannot be opened at another one: the production run holds this half of the proof. */
    const elsewhere = PRODUCTION ? `http://localhost:${new URL(world.react.origin).port}` : null;
    const wide = await open(browser, world.react, [elsewhere].filter(Boolean));
    try {
      await go(wide, SESSIONS);
      await until(async () => (await consentOf(wide.page)).state === 'on', 'the line on');
      await pressUsage(wide, 'declined');
      await until(async () => (await consentOf(wide.page)).state === 'off', 'off on this origin');
      // Same profile, different origin: nothing was turned off there, so it reads quota.
      if (elsewhere) {
        await wide.page.goto(`${elsewhere}/${SESSIONS}`);
        await until(
          async () => (await consentOf(wide.page)).state === 'on',
          'the line on at the other origin',
        );
      }
    } finally {
      await wide.close();
    }
  });

  await step(
    'Turn on carries usage=1 on the very next request, the server sees it, and Turn off stops it',
    async () => {
      view.reset();
      const before = (await eventsOf(side, 'usage_fetch')).length;
      await pressUsage(view, 'granted');
      await until(
        () => usageRequests(view).length > 0,
        `${side.name} a request with the parameter`,
      );
      assert.match(usageRequests(view)[0].path, /usage=1/);
      await until(
        async () => (await eventsOf(side, 'usage_fetch')).length > before,
        `${side.name} the server counting it`,
      );
      assert.match((await consentOf(view.page)).line, ON_LINE);
      // Turned back on, the choice rides the very first read of a fresh page load.
      view.reset();
      await view.page.reload();
      await until(() => dataRequests(view).length > 0, `${side.name} the first read`);
      assert.match(dataRequests(view)[0].path, /usage=1/, `${side.name}: on rides the first read`);
      // Off again: the read the press asks for carries none, and the server's count stops.
      view.reset();
      await until(async () => (await consentOf(view.page)).line, 'the line');
      await pressUsage(view, 'declined');
      await until(
        () => dataRequests(view).length > 0,
        `${side.name} the read after turning it off`,
      );
      assert.deepEqual(usageRequests(view), [], `${side.name}: still sending the parameter`);
      const frozen = (await eventsOf(side, 'usage_fetch')).length;
      await pause(2500);
      assert.equal(
        (await eventsOf(side, 'usage_fetch')).length,
        frozen,
        `${side.name}: still fetching`,
      );
      assert.deepEqual(usageRequests(view), [], `${side.name}: still sending the parameter`);
    },
  );

  await step(
    'a fresh profile reads quota from its very first request, and a press keeps focus on the switch',
    async () => {
      const fresh = await open(browser, world.react);
      try {
        await go(fresh, SESSIONS);
        await until(() => dataRequests(fresh).length > 0, 'the first read');
        assert.match(dataRequests(fresh)[0].path, /usage=1/, 'the first read asks for quota');
        await until(async () => (await consentOf(fresh.page)).state === 'on', 'the line on');
        await pressUsage(fresh, 'declined');
        await until(async () => (await consentOf(fresh.page)).state === 'off', 'the line off');
        // The button stays where it was, renamed, so a keyboard reader is not left on nothing.
        const focused = await fresh.page.evaluate(
          () => globalThis.document.activeElement?.closest('.next-usage-switch') !== null,
        );
        assert.ok(focused, 'focus stays on the switch');
      } finally {
        await fresh.close();
      }
    },
  );

  /* The selected window. The board is steered to publish six windows, the third of which the reader chooses; a
     later board ranks it fourth, and it must stay on screen and selected. */
  await step(
    'the selected window keeps its identity across a redraw that reorders it and a route change',
    async () => {
      await steer(side, { windows: 'full' });
      await go(view, SESSIONS);
      const first = await until(
        async () => {
          const state = await stripOf(view.page);
          return state && state.rows.length === 3 && state.rows.some((r) => r.key === 'codex:fiveH')
            ? state
            : null;
        },
        `${side.name} the full board`,
        patience(15000),
      );
      assert.equal(first.rows[0].key, 'cursor:fiveH');
      assert.match(first.more, /^3 more windows/);
      assert.equal(first.rows.filter((r) => r.pressed).length, 1);
      assert.equal(
        await pressedKey(view),
        'cursor:fiveH',
        'the first window is selected until the reader chooses',
      );
      await pressWindow(view, 'codex:fiveH');
      assert.equal(await pressedKey(view), 'codex:fiveH');
      await steer(side, { windows: 'reordered' });
      const after = await until(
        async () => {
          const state = await stripOf(view.page);
          const claude = state?.rows.find((r) => r.key === 'claude:fiveH');
          return claude && /95%/.test(claude.text) ? state : null;
        },
        `${side.name} the reordered board`,
        patience(20000),
      );
      // The chosen window is now ranked below the first three, and still drawn, selected.
      assert.equal(after.rows.length, 3);
      assert.ok(
        after.rows.some((r) => r.key === 'codex:fiveH'),
        `${side.name}: the chosen window left the strip`,
      );
      assert.equal(
        await pressedKey(view),
        'codex:fiveH',
        `${side.name}: the selection moved with the rank`,
      );
      assert.match(after.prospect, /Codex · 5-hour/);
      await navigate(view, ELSEWHERE);
      await pause(300);
      await navigate(view, SESSIONS);
      await until(async () => (await stripOf(view.page))?.rows.length, 'the strip after a return');
      assert.equal(
        await pressedKey(view),
        'codex:fiveH',
        `${side.name}: lost across a route change`,
      );
      // A page is a tab's life: a reload starts again at the first window.
      await view.page.reload();
      await until(async () => (await stripOf(view.page))?.rows.length, 'the strip after a reload');
      assert.notEqual(await pressedKey(view), 'codex:fiveH');
    },
  );

  await step(
    'the selection falls back only when its window is gone, holds the fallback, and clears with the last window',
    async () => {
      await steer(side, { windows: 'full' });
      await go(view, SESSIONS);
      await until(
        async () => (await stripOf(view.page))?.rows.some((r) => r.key === 'codex:fiveH'),
        'the board',
      );
      await pressWindow(view, 'codex:fiveH');
      await steer(side, { windows: 'fewer' });
      await until(
        async () => {
          const state = await stripOf(view.page);
          return state && state.rows.every((r) => r.key.startsWith('claude:')) ? state : null;
        },
        `${side.name} the smaller board`,
        patience(20000),
      );
      const fell = await pressedKey(view);
      assert.ok(fell?.startsWith('claude:'), `${side.name}: no fallback to an existing window`);
      await steer(side, { windows: 'full' });
      await until(
        async () => (await stripOf(view.page))?.rows.some((r) => r.key === 'codex:fiveH'),
        'the board back',
      );
      assert.equal(await pressedKey(view), fell, `${side.name}: the fallback was not held`);
      await steer(side, { windows: 'none' });
      await until(
        async () => (await stripOf(view.page)) === null,
        `${side.name} no strip`,
        patience(20000),
      );
      assert.equal(await view.page.locator('[data-next-capacity]').count(), 0);
      await steer(side, { windows: 'full' });
      await until(async () => (await stripOf(view.page))?.rows.length, 'the strip returning');
      assert.equal(
        await pressedKey(view),
        'cursor:fiveH',
        `${side.name}: not cleared when none remained`,
      );
    },
  );

  await step('the strip draws the recorded facts and invents no tick', async () => {
    const facts = (state) => ({
      keys: state.rows.map((r) => r.key),
      ticks: state.rows.map((r) => r.tick),
      noclock: state.rows.map((r) => r.noclock),
      more: state.more,
      models: state.models,
    });
    const read = (count) =>
      until(
        async () => {
          const state = await stripOf(view.page);
          return state && state.rows.length === count ? state : null;
        },
        `${side.name} ${count} windows`,
        patience(20000),
      );
    for (const [windows, count] of [
      ['full', 3],
      ['fewer', 3],
    ]) {
      await steer(side, { windows });
      await go(view, SESSIONS);
      const mine = await read(count);
      const factsKey = `the strip's windows, ticks and sub-limits with the ${windows} board`;
      golden.observe(factsKey);
      golden.verify(factsKey, facts(mine));
      if (windows === 'full') {
        // A spent budget says so, and the window with no clock is ranked last, behind the fold, untimed.
        assert.match(mine.rows[0].text, /already spent/);
        assert.match(mine.more, /^3 more windows, 1 of them not timed$/);
        continue;
      }
      // The window that publishes no clock draws a hatched gap and no tick: nothing is invented to fill it.
      const month = mine.rows.find((r) => r.key === 'claude:month');
      assert.ok(
        month?.noclock && !month.tick,
        'react: a window with no clock drew a bar or a tick',
      );
      assert.match(month.text, /Window length not published/);
      assert.match(month.text, /Pace not measured/);
      assert.match(month.text, /not projected/);
      await pressWindow(view, 'claude:week');
      const week = await stripOf(view.page);
      assert.ok(week.rows.find((r) => r.key === 'claude:week')?.pressed);
      // The sub-limits hang under the weekly row only, and keep a measured zero.
      assert.deepEqual(
        week.models.map((m) => /Opus 71%.*Sonnet 0%/.test(m)),
        [true],
      );
      /* The page samples the pace on its own clock, so the span and the number of readings it quotes ("across 8s and
         3 readings") and the wall-clock minute a budget ends at differ from the recording's: a recording keeps the
         sentences with the figures masked, because a clock minute and the weekday or date a budget ends on (the
         browser's time zone, and today's date: the column draws "21:04", "Sat 21:04" or "Oct 12" by how far off the
         end is) are not facts about the previous interface's code. Everything else is the same sentence and a
         difference in it fails, and React's own text is asserted below, strictly. */
      const unclocked = (text) =>
        text
          .replace(/across \S+ and \d+ readings/g, 'across <span> and <n> readings')
          .replace(/\d{1,2}:\d{2}/g, '<time>')
          .replace(/(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?= <time>)/g, '<day>')
          .replace(
            /BUDGET ENDS(?:<day> <time>|<time>|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{2})/g,
            'BUDGET ENDS<instant>',
          );
      const weekKey = "the weekly window's prospect and rows, clocks aside";
      const said = golden.observe(weekKey);
      golden.verify(weekKey, {
        prospect: unclocked(week.prospect),
        rows: week.rows.map((r) => unclocked(r.text)),
      });
      assert.ok(said.rows.length > 0, 'the recording holds the weekly rows');
      // The weekly row's recent pace is a measured zero, which is evidence and is not "not measured".
      assert.match(
        week.prospect,
        /Recent pace measured at zero: nothing spent across .+ and \d+ readings/,
      );
    }
  });

  /* The observer-model controls, in the Console tab of the exact session, with a fresh profile per path. */
  const observer = async (side, body) => {
    const view = await open(browser, side);
    try {
      await go(view, CONSOLE);
      await body(view);
      assert.deepEqual(
        view.everything.filter((r) => r.method !== 'GET'),
        [],
        `${side.name}: a request that was not a GET`,
      );
      assert.deepEqual(
        view.everything.filter((r) => r.path.startsWith('/api/focus')),
        [],
        `${side.name}: a focus request`,
      );
      assert.deepEqual(await view.page.evaluate(() => globalThis.__notified), []);
    } finally {
      await view.close();
    }
  };
  await step(
    'an offer nothing read, one that is off, and one withheld are three different sentences',
    async () => {
      const said = {};
      for (const [mode, expected] of [
        ['absent', /Observer model availability has not been read\./],
        ['disabled', /Observer model is disabled for this run\./],
        ['no-disclosure', /Observer disclosure is unavailable; model requests are withheld\./],
      ]) {
        await steer(side, { windows: 'full', observer: mode }, { board: false });
        await observer(side, async (view) => {
          await until(
            async () => expected.test((await observerText(view.page)) ?? ''),
            `${side.name} ${mode}`,
          );
          said[mode] = await observerText(view.page);
          assert.deepEqual(
            await observerButtons(view.page),
            [],
            `${side.name} ${mode}: controls offered`,
          );
          assert.equal(modelRequests(view).length, 0);
        });
      }
      assert.equal(new Set(Object.values(said)).size, 3);
      assert.equal((await eventsOf(side, 'model_call')).length, 0);
    },
  );

  /* Restated 2026-10-27: since the summary widening (docs/design-session-summary.md, "The widening") the controls
     ask no question. Summarize this session is the press, Pause model calls sits beside it, and a reader who turned
     summaries off is offered Turn on summaries. Pause is a POST, which this proof's observer pages forbid, so it is
     held by the unit tests and the story instead. */
  await step(
    'nothing is sent before a press; one press of Summarize is one request for the exact session',
    async () => {
      await steer(side, { windows: 'full', observer: 'enabled' }, { board: false });
      const before = (await eventsOf(side, 'model_call')).length;
      await observer(side, async (view) => {
        const first = await until(async () => {
          const buttons = await observerButtons(view.page);
          return buttons.some((b) => b.action === 'request') ? buttons : null;
        }, `${side.name} the Summarize button`);
        assert.deepEqual(
          first.map((b) => b.label),
          ['Summarize this session', 'Pause model calls'],
        );
        // Mounting, StrictMode, a poll, a route change and a reload asked nothing.
        await pause(2000);
        await navigate(view, ELSEWHERE);
        await pause(300);
        await navigate(view, CONSOLE);
        await until(
          async () => (await observerButtons(view.page)).length,
          'the controls after a return',
        );
        await view.page.reload();
        await until(
          async () => (await observerButtons(view.page)).some((b) => b.action === 'request'),
          'the controls after a reload',
        );
        await pause(1500);
        assert.equal(modelRequests(view).length, 0, `${side.name}: a request before a press`);
        assert.equal(
          (await eventsOf(side, 'model_call')).length,
          before,
          `${side.name}: the server saw one`,
        );
        // The press: a double click is one request for exactly this session. This world starts the server with
        // `--no-observer-model`, which development fixtures must keep, and since the summary widening the server
        // asks the reading policy before it passes a press on, so the request arrives and no model runs: the page
        // says the refresh returned and published no summary, and the server records no model call.
        await view.page.locator('[data-next-observer-action="request"]').dblclick();
        await until(
          async () => {
            const drawn = (await observerText(view.page)) ?? '';
            if (/No goal summary was published by this refresh\./.test(drawn)) return drawn;
            throw new Error(`the page drew: ${drawn.slice(0, 400)}`);
          },
          `${side.name} the refresh`,
          patience(30000),
        );
        assert.match(await observerText(view.page), /The refresh returned\./);
        assert.equal(modelRequests(view).length, 1, `${side.name}: not one request`);
        assert.match(modelRequests(view)[0].path, /session=claude%3Alive-work/);
        assert.equal(
          (await eventsOf(side, 'model_call')).length,
          before,
          `${side.name}: a model call with model calls off for the run`,
        );
      });
    },
  );

  await step(
    'reading quota sends no summary, and Turn on summaries sends nothing by itself',
    async () => {
      await steer(side, { windows: 'full', observer: 'enabled' }, { board: false });
      const view = await open(browser, side);
      try {
        await view.page.goto(`${side.origin}/${SESSIONS}`);
        await view.page.evaluate(() =>
          globalThis.localStorage.setItem('compass.observer-model-consent.v1', 'declined'),
        );
        const before = (await eventsOf(side, 'model_call')).length;
        await go(view, CONSOLE);
        await until(
          async () => (await observerButtons(view.page)).some((b) => b.action === 'on'),
          `${side.name} the way back`,
        );
        assert.deepEqual(
          (await observerButtons(view.page)).map((b) => b.action),
          ['on', 'off'],
        );
        assert.match(
          (await observerText(view.page)) ?? '',
          /Goal summaries are off in this browser\. Nothing is sent for a summary until you turn them back on\./,
        );
        // The quota line is on, and its board reads carry usage=1, without a summary being asked for.
        assert.equal((await consentOf(view.page)).state, 'on');
        assert.ok(usageRequests(view).length > 0, `${side.name}: no board read carried usage=1`);
        assert.deepEqual(withoutUsage(view), [], `${side.name}: a board read without usage=1`);
        await pause(1500);
        assert.equal(modelRequests(view).length, 0);
        assert.equal((await eventsOf(side, 'model_call')).length, before);
        await view.page.locator('[data-next-observer-action="on"]').click();
        await until(
          async () => (await observerButtons(view.page)).some((b) => b.action === 'request'),
          `${side.name} Summarize after turning summaries on`,
        );
        await pause(1500);
        assert.equal(modelRequests(view).length, 0, `${side.name}: turning summaries on sent one`);
        assert.equal((await eventsOf(side, 'model_call')).length, before);
      } finally {
        await view.close();
      }
    },
  );

  await step('nothing posted, raised a terminal or notified on either page', async () => {
    assert.deepEqual(
      view.everything.filter((r) => r.method !== 'GET'),
      [],
      `${side.name}: a request that was not a GET`,
    );
    assert.deepEqual(
      view.everything.filter((r) => r.path.startsWith('/api/focus')),
      [],
      `${side.name}: a focus request`,
    );
    assert.deepEqual(
      await view.page.evaluate(() => globalThis.__notified),
      [],
      `${side.name}: a notification call`,
    );
  });

  await step('the layout holds at 320 and 375 px and every control is a touch target', async () => {
    const report = {};
    await steer(side, { windows: 'full', observer: 'enabled' });
    for (const width of [375, 320]) {
      await view.page.setViewportSize({ width, height: 900 });
      await go(view, SESSIONS);
      await until(async () => (await stripOf(view.page))?.rows.length, 'the strip');
      const measured = await view.page.evaluate(() => {
        const { document } = globalThis;
        const root = document.scrollingElement;
        const boxes = (selector) =>
          [...document.querySelectorAll(selector)].map((node) => {
            const box = node.getBoundingClientRect();
            return { width: box.width, height: box.height, right: box.right };
          });
        return {
          overflow: root.scrollWidth - root.clientWidth,
          client: root.clientWidth,
          rows: boxes('.next-capacity-row'),
          actions: boxes('.next-usage-consent-actions button, .next-usage-switch button'),
        };
      });
      assert.ok(
        measured.overflow <= 0,
        `react: horizontal page scroll at ${width}px: ${measured.overflow}`,
      );
      for (const row of measured.rows)
        assert.ok(
          row.right <= measured.client + 1,
          `react: a window row leaves the page at ${width}px`,
        );
      const small = measured.rows.filter((r) => r.height < 44).length;
      assert.equal(small, 0, `react: a window row under 44 px at ${width}px`);
      for (const action of measured.actions)
        assert.ok(
          action.height >= 44 && action.width >= 44,
          `react: a consent control under 44 px at ${width}px`,
        );
      report[`${side.name}@${width}`] = { overflow: measured.overflow };
      if (shots) {
        await mkdir(SHOTS, { recursive: true });
        await view.page.screenshot({
          path: join(SHOTS, `drc-4827-capacity-${side.name}-${width}px.png`),
          fullPage: true,
        });
      }
    }
    await view.page.setViewportSize({ width: 1100, height: 900 });
    if (shots) {
      await go(view, SESSIONS);
      await until(async () => (await stripOf(view.page))?.rows.length, 'the strip');
      await view.page.screenshot({
        path: join(SHOTS, 'drc-4827-capacity-react-1100px.png'),
        fullPage: true,
      });
      await steer(world.react, { windows: 'full', observer: 'enabled' });
      const consoleView = await open(browser, world.react);
      try {
        await go(consoleView, CONSOLE);
        await until(
          async () => (await observerButtons(consoleView.page)).length,
          'the observer controls',
        );
        await consoleView.page.screenshot({
          path: join(SHOTS, 'drc-4827-observer-react-1100px.png'),
          fullPage: true,
        });
      } finally {
        await consoleView.close();
      }
    }
    return report;
  });

  /* The strip and the consent at the widths and zoom a reader meets: 320 and 375 CSS px, 640 (200% zoom of a 1280
     window) and the reader's text at twice the size, on the Sessions view (the strip and the usage question) and the
     Console tab (the usage switch and the observer controls). A fresh profile draws the unanswered question; the
     answered switch is drawn by the tracked strip page, which answered earlier in this run. React is held to every
     measure. */
  /* The harness draws the strip with no page padding, so a disclosure chevron (a rotated pseudo-element, which counts
     toward scrollable overflow) pokes 3 px past the window at 320 px and 200% text. The shipped page's view padding
     holds it, so the production run allows nothing; the harness run allows the chevron's width and no more. */
  const CHEVRON_PX = PRODUCTION ? 0 : 4;
  await step(
    'zoom: the strip, the consent and the observer controls fit at 320, 375 and 640 px and at 200% text, on the Sessions view and the Console tab',
    async () => {
      const report = {};
      await steer(side, { windows: 'full', observer: 'enabled' });
      const measure = (page) =>
        page.evaluate(() => {
          const { document } = globalThis;
          const root = document.scrollingElement;
          const boxes = (selector) =>
            [...document.querySelectorAll(selector)].map((node) => {
              const box = node.getBoundingClientRect();
              return { width: box.width, height: box.height, right: box.right };
            });
          return {
            overflow: root.scrollWidth - root.clientWidth,
            client: root.clientWidth,
            rows: boxes('.next-capacity-row'),
            actions: boxes(
              '.next-usage-consent-actions button, .next-usage-switch button, [data-next-observer-action]',
            ),
          };
        });
      for (const [label, route, wait] of [
        ['sessions', SESSIONS, async (view) => (await stripOf(view.page))?.rows.length],
        [
          'console',
          CONSOLE,
          async (view) =>
            (await observerButtons(view.page)).length || (await consentOf(view.page)).line,
        ],
      ]) {
        for (const width of [320, 375, 640]) {
          const view = await open(browser, side);
          try {
            await view.page.setViewportSize({ width, height: 900 });
            await go(view, route);
            await until(() => wait(view), `${side.name} the ${label} view at ${width}`);
            for (const scale of ['100%', '200%']) {
              await view.page.evaluate((fontSize) => {
                globalThis.document.documentElement.style.fontSize = fontSize;
              }, scale);
              await pause(150);
              const measured = await measure(view.page);
              const where = `${side.name} ${label} at ${width}px, text ${scale}`;
              report[where] = { overflow: measured.overflow };
              assert.ok(
                measured.overflow <= CHEVRON_PX,
                `${where}: horizontal page scroll ${measured.overflow}`,
              );
              for (const row of measured.rows)
                assert.ok(
                  row.right <= measured.client + 1,
                  `${where}: a window row leaves the page`,
                );
              for (const action of measured.actions) {
                assert.ok(
                  action.right <= measured.client + 1,
                  `${where}: a control leaves the page`,
                );
                assert.ok(
                  action.height >= 44 && action.width >= 44,
                  `${where}: a control under 44 px (${Math.round(action.width)}x${Math.round(action.height)})`,
                );
              }
            }
          } finally {
            await view.close();
          }
        }
      }

      // The line turned off, which is the longer of its two sentences, at the narrowest width and the largest text.
      const answered = await open(browser, world.react);
      try {
        await answered.page.setViewportSize({ width: 320, height: 900 });
        await go(answered, SESSIONS);
        await until(async () => (await consentOf(answered.page)).state === 'on', 'the line on');
        await pressUsage(answered, 'declined');
        await until(
          async () => (await consentOf(answered.page)).state === 'off',
          'the line turned off',
        );
        await answered.page.evaluate(() => {
          globalThis.document.documentElement.style.fontSize = '200%';
        });
        await pause(150);
        const switched = await measure(answered.page);
        assert.ok(
          switched.overflow <= CHEVRON_PX,
          `react: the quota line scrolls the page by ${switched.overflow} at 320px, text 200%`,
        );
        report['react quota line off at 320px, text 200%'] = { overflow: switched.overflow };
      } finally {
        await answered.close();
      }
      return report;
    },
  );

  /* A reader who never touches the mouse: the window rows and the quota switch are reached by Tab and operated by
     Enter and Space, and each press does what the same press with a pointer does. */
  await step(
    'keyboard: the window rows and the quota switch are reached by Tab, operated by Enter and Space, and keep their focus',
    async () => {
      const trace = { react: {} };
      const nameOf = (page, selector) =>
        page.evaluate((query) => {
          const node = globalThis.document.querySelector(query);
          return node
            ? (node.getAttribute('aria-label') || node.textContent || '')
                .replace(/\s+/g, ' ')
                .trim()
            : null;
        }, selector);
      const holdsFocus = (page, selector) =>
        page.evaluate(
          (query) => globalThis.document.querySelector(query) === globalThis.document.activeElement,
          selector,
        );

      await steer(side, { windows: 'full' });
      const seen = trace.react;

      // The window rows: Space selects the third, Shift+Tab and Enter select the one before it.
      const rows = await open(browser, side);
      try {
        await go(rows, SESSIONS);
        await until(
          async () => (await stripOf(rows.page))?.rows.some((r) => r.key === 'codex:fiveH'),
          `${side.name} the full board`,
          patience(15000),
        );
        {
          const keys = (await stripOf(rows.page)).rows.map((r) => r.key);
          const target = keys.at(-1);
          const before = keys.at(-2);
          const buttonOf = (key) => `[data-next-capacity-row="${key}"] button`;
          const name = await nameOf(rows.page, buttonOf(target));
          assert.ok(name, 'the last window row has no button');
          seen.rowTabs = await tabTo(rows.page, name);
          await rows.page.keyboard.press('Space');
          assert.equal(await pressedKey(rows), target, 'Space did not select the window');
          assert.equal(await holdsFocus(rows.page, buttonOf(target)), true, 'focus left the row');
          await rows.page.keyboard.press('Shift+Tab');
          assert.equal(
            await holdsFocus(rows.page, buttonOf(before)),
            true,
            'Shift+Tab did not reach the row before',
          );
          await rows.page.keyboard.press('Enter');
          assert.equal(await pressedKey(rows), before, 'Enter did not select the window');
          assert.equal(await holdsFocus(rows.page, buttonOf(before)), true, 'focus left the row');
          seen.rows = [target, before];
        }
      } finally {
        await rows.close();
      }

      // The quota line: Turn off and Turn on are each a button a keyboard reader reaches and presses.
      for (const [answer, key, startOff] of [
        ['declined', 'Enter', false],
        ['granted', 'Space', true],
      ]) {
        const view = await open(browser, side);
        try {
          await go(view, SESSIONS);
          if (startOff) {
            await view.page.evaluate(() =>
              globalThis.localStorage.setItem('compass.next.usage.consent', 'declined'),
            );
            await view.page.reload();
          }
          const from = startOff ? 'off' : 'on';
          await until(
            async () => (await consentOf(view.page)).state === from,
            `${side.name} the line ${from}`,
          );
          {
            const selector = `[data-next-usage-answer="${answer}"]`;
            const name = await nameOf(view.page, selector);
            assert.ok(name, `no ${answer} button`);
            seen[`${answer}Tabs`] = await tabTo(view.page, name);
            const seenBefore = (await eventsOf(side, 'usage_fetch')).length;
            // Turning off from on: a poll can still carry usage=1 until the press lands, so the count starts
            // after the line says off. Turning on from off: nothing carries it before, so it starts at once.
            if (startOff) view.reset();
            await view.page.keyboard.press(key);
            const to = startOff ? 'on' : 'off';
            await until(
              async () => (await consentOf(view.page)).state === to,
              `${side.name} the line ${to} after ${key}`,
            );
            if (!startOff) view.reset();
            await until(
              () => dataRequests(view).length > 0,
              `${side.name} the read after the press`,
            );
            if (answer === 'granted') {
              await until(() => usageRequests(view).length > 0, `${side.name} the parameter`);
              assert.match(usageRequests(view)[0].path, /usage=1/);
              await until(
                async () => (await eventsOf(side, 'usage_fetch')).length > seenBefore,
                `${side.name} the server counting the press`,
              );
            } else {
              await pause(1500);
              assert.deepEqual(usageRequests(view), [], `${side.name}: Turn off sent a parameter`);
            }
            // The button stays and is renamed, so focus stays with it.
            seen[`${answer}Focus`] = await focusedLabel(view.page);
            assert.equal(
              await view.page.evaluate(
                () => globalThis.document.activeElement?.closest('.next-usage-switch') !== null,
              ),
              true,
              `focus left the switch after ${key} on ${answer}`,
            );
          }
        } finally {
          await view.close();
        }
      }

      return trace;
    },
  );

  await step('no external request, page error or console error', async () => {
    assert.deepEqual(view.log.externalRequests, [], `${side.name}: an external request`);
    assert.deepEqual(view.log.pageErrors, [], `${side.name}: a page error`);
    assert.deepEqual(
      view.log.consoleErrors.filter(
        (text) =>
          !/net::ERR_FAILED|ERR_INTERNET_DISCONNECTED|Failed to load resource: the server responded with a status of (404|500)/.test(
            text,
          ),
      ),
      [],
      `${side.name}: a console error`,
    );
  });

  console.log(
    JSON.stringify(
      {
        capacityBrowser: {
          mutation: world.mutation || null,
          strictMode: true,
          realBackend: true,
          failures: failures.length,
          steps: results,
        },
      },
      null,
      2,
    ),
  );
  // A mutation run is expected to fail and a filtered run skips steps, so neither records nor checks the golden.
  golden.finish({ complete: failures.length === 0 && !only && !world.mutation });
  if (failures.length) {
    console.error(JSON.stringify({ mutation: world.mutation || null, failures }, null, 2));
    process.exitCode = 1;
  }
} catch (error) {
  console.error(
    JSON.stringify(
      {
        steps: results,
        failures,
        fatal: String(error.message || error)
          .split('\n')
          .slice(0, 6)
          .join(' | '),
      },
      null,
      2,
    ),
  );
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  if (world) await world.close();
}
