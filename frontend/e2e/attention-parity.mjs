/*
 * The Attention screen and the notification lanes in a real browser, against the real backend (DRC-4827).
 *
 * The React page runs over one synthetic board and is held to what the previous interface said of it, from the
 * recording in `frontend/test/golden/e2e/attention-parity.json` (`support/golden.mjs`), which cannot be remade
 * because that interface is gone. The DIFFERENTIAL half compares what a reader can read of Attention (each queue,
 * each row in order, the rows a section hides until it is expanded) and the permission flow's visible outcome. The
 * BEHAVIOUR half holds the React page to what a text comparison cannot see: an expanded section keeps its button
 * node, its focus and its state through revisions that reorder and remove rows; focus falls to the section heading
 * when the row a reader was on leaves; the polite status region says "Attention updated" only when a queue changed
 * length; and the page does nothing on its own about notifications. Nothing is raised, asked or posted on mount,
 * StrictMode, a poll, a reconnect or a route change; the browser's permission prompt opens only on a press; the one
 * POST the lane sends names two scalars and no session; a granted tab reports again after a reload, and raises
 * nothing for the gates the board already held.
 *
 * The Notification API is a SCRIPTED one, installed before the page loads: it records what the page asked it to
 * raise and what permission it asked for, and nothing here can create a native notification. Models, usage,
 * focus and the clipboard are not exercised: every board read is the one this script serves, usage is never
 * consented to, and a request for it fails the run. Run with `pnpm test:attention:browser`;
 * `COMPASS_E2E_STEPS=<regex>` runs only the steps whose name matches, `COMPASS_SCREENSHOTS=1` writes captures
 * to docs/screenshots/, and `COMPASS_MUTATION=<name>` applies one deliberate break in a scratch copy of the
 * tree (see MUTATIONS), which must make the run FAIL.
 *
 * Timing: every fixed wait here means "give the page time to react", and a hosted runner has a few shared
 * cores, so each is tripled under CI and every comparison reads until two reads agree (`settled`).
 *
 * Dropped with the previous interface, because no React reading was compared with them: its keyboard legs (Show
 * more, Copy, Raise and Enable notifications) and its screenshots.
 */
import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import { recordClipboard, startSessionsBoard } from './sessions-board.mjs';
import { goldenFor } from './support/golden.mjs';
import { unchangedAttentionLocations } from './support/location-deviations.mjs';
import { focusedLabel, openPage, REPOSITORY, tabTo } from './support/browser.mjs';
import { PRODUCTION } from './support/world.mjs';
import { omitAttentionQuietSubtotals } from '../test/recordedSessionStatus.ts';

const golden = goldenFor('attention-parity');
const patience = (ms) => (process.env.CI ? ms * 3 : ms);
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, patience(ms)));

// The board builder is TypeScript the unit tests also use; Node 26 strips the types as it imports it.
process.removeAllListeners('warning');
const { attentionBoard } = await import('../test/attention_boards.ts');

const SHOTS = join(REPOSITORY, 'docs/screenshots');
const shotsOn = process.env.COMPASS_SCREENSHOTS === '1';
const only = process.env.COMPASS_E2E_STEPS ? new RegExp(process.env.COMPASS_E2E_STEPS) : null;

/* One break each, applied to the scratch copy only. A missing needle fails the run loudly rather than
   silently testing nothing. */
const MUTATIONS = {
  // Show more answers a pointer press and nothing else: Enter and Space do nothing.
  'toggle-pointer-only': [
    [
      'src/attention/AttentionView.tsx',
      'onClick={() => expansion.toggle(section)}',
      'onMouseDown={() => expansion.toggle(section)}',
    ],
  ],
  // The screen says something other than the previous interface did: the recording must catch a wording drift.
  'screen-wording': [
    [
      'src/attention/AttentionView.tsx',
      'Show ${String(remainder)} more',
      'Show ${String(remainder)} others',
    ],
  ],
  // A section remounts on every revision: the button the reader pressed and focused is a different node.
  'section-remounts': [
    [
      'src/attention/AttentionView.tsx',
      '<section className="next-attention-section" data-next-attention-section={section}>',
      '<section key={String(model.generated)} className="next-attention-section" data-next-attention-section={section}>',
    ],
  ],
  // The expanded flag is dropped whenever a board arrives.
  'expansion-forgets': [
    [
      'src/attention/AttentionView.tsx',
      'const expanded = expansion.has(section);',
      'const expanded = expansion.has(section) && model.counts[section] === subjects.length;',
    ],
  ],
  // Focus has nowhere to go when its row leaves.
  'no-focus-fallback': [
    [
      'src/attention/AttentionLink.tsx',
      'useFocusKey<HTMLAnchorElement>(controls.focusLane, focusKey, { fallback })',
      'useFocusKey<HTMLAnchorElement>(controls.focusLane, focusKey)',
    ],
  ],
  // The announcer speaks on every board, changed or not.
  'announce-always': [
    [
      'src/attention/model.ts',
      "if (keys.every((key) => previous.counts[key] === current.counts[key])) return '';",
      '',
    ],
  ],
  // The prompt opens as the control mounts.
  'prompt-on-mount': [
    [
      'src/notify/NotificationControl.tsx',
      'startNotifications(runtime);\n  }, [runtime]);',
      'startNotifications(runtime);\n    owner.request();\n  }, [runtime, owner]);',
    ],
  ],
  // The first board raises for the gates it already held.
  'first-board-raises': [['src/notify/owner.ts', 'let primed = false;', 'let primed = true;']],
  // The server's native lane no longer takes the banner.
  'native-also': [
    [
      'src/notify/owner.ts',
      "return !(payload && payload['native_notify']) && host.supported();",
      'return host.supported();',
    ],
  ],
  // The lane is reported on every payload, not on a disagreement.
  'lane-every-payload': [
    [
      'src/notify/owner.ts',
      'return !Number.isFinite(generated) || generated > laneReportedThrough;',
      'return true;',
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
      message: String(error.stack || error.message || error)
        .split('\n')
        .slice(0, 8)
        .join(' | ')
        .slice(0, 2200),
    });
  }
}

/* ---- the world: a scratch copy of the tree, so a mutation never touches a tracked file ---- */
const mutation = process.env.COMPASS_MUTATION || '';
assert.ok(!mutation || MUTATIONS[mutation], `unknown mutation ${mutation}`);
/* Without a mutation, the production run serves the tracked `react.html` itself rather than a scratch copy's build. */
const ownsRepository = PRODUCTION && !mutation;
const copy = ownsRepository
  ? REPOSITORY
  : await mkdtemp(join(tmpdir(), 'compass-attention-browser-'));
let board = null;
let browser = null;
const opened = [];

async function prepareCopy() {
  if (ownsRepository) return;
  await cp(join(REPOSITORY, 'frontend'), join(copy, 'frontend'), {
    recursive: true,
    filter: (path) =>
      !path.includes('/test-results') &&
      !path.includes('__pycache__') &&
      !path.includes('/.frontend-build'),
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
  for (const [file, needle, replacement] of MUTATIONS[mutation] ?? []) {
    const path = join(copy, 'frontend', file);
    const text = await readFile(path, 'utf8');
    assert.ok(text.includes(needle), `mutation ${mutation}: needle not found in ${file}`);
    await writeFile(path, text.replace(needle, replacement));
  }
}

/* ---- the scripted Notification, installed before the page loads ---- */
const scriptNotification = (context, config) =>
  context.addInitScript((cfg) => {
    const read = (key, fallback) => {
      try {
        const raw = globalThis.sessionStorage.getItem(key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch {
        return fallback;
      }
    };
    const write = (key, value) => {
      try {
        globalThis.sessionStorage.setItem(key, JSON.stringify(value));
      } catch {
        /* a blocked store */
      }
    };
    const state = {
      permission: read('__notify_permission', cfg.permission),
      made: read('__notify_made', []),
      asked: read('__notify_asked', 0),
    };
    globalThis.__notify = state;
    if (cfg.absent) {
      delete globalThis.Notification;
      return;
    }
    class Scripted {
      static get permission() {
        return state.permission;
      }
      static requestPermission(done) {
        state.asked += 1;
        state.permission = cfg.answer;
        write('__notify_permission', cfg.answer);
        write('__notify_asked', state.asked);
        if (done) done();
        return Promise.resolve(cfg.answer);
      }
      constructor(title, options = {}) {
        state.made.push({ title, body: options.body, tag: options.tag });
        write('__notify_made', state.made);
      }
    }
    Object.defineProperty(globalThis, 'Notification', {
      configurable: true,
      writable: true,
      value: Scripted,
    });
  }, config);

/* A wall-clock time ("Latest launch 21:03") is drawn in the browser's own time zone, so a recording made in one
   zone differs from a run in another while saying the same thing about the board. Both are compared with
   the hour and minute masked; the sentence around them still has to match. */
const clockless = (value) =>
  JSON.parse(JSON.stringify(value).replace(/(?<!\d)\d{1,2}:\d\d(?!\d)/g, '<clock>'));

const notifyState = (page) => page.evaluate(() => globalThis.__notify);

/* ---- what a reader can read of Attention, reduced to data. Runs IN the page, so it is self-contained. ---- */
const readAttention = () => {
  const { document } = globalThis;
  const norm = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : '');
  const root = document.querySelector('[data-next-view-body="attention"]');
  if (!root) return { missing: true, text: norm(document.body).slice(0, 200) };
  return {
    brief: norm(root.querySelector('.next-attention-brief > p')),
    sections: [...root.querySelectorAll('section[data-next-attention-section]')]
      .filter((section) => section.dataset.nextAttentionSection !== 'open')
      .map((section) => {
        const toggle = section.querySelector(':scope > [data-next-attention-toggle]');
        return {
          name: section.dataset.nextAttentionSection,
          heading: norm(
            section.querySelector(':scope > h2, :scope > .next-attention-section-heading h2'),
          ),
          toggle: toggle ? [norm(toggle), toggle.getAttribute('aria-expanded')] : null,
          items: [...section.querySelectorAll(':scope > ol > li')].map((li) => ({
            hidden: li.hasAttribute('hidden'),
            subject: li.querySelector('article')?.dataset.nextAttentionSubject ?? '',
            text: norm(li),
          })),
        };
      }),
    reports: norm(root.querySelector('[data-next-command-reports]')),
    open: [...root.querySelectorAll('[data-next-open]')].map(norm),
  };
};
const statusText = (page) =>
  page.evaluate(
    () => globalThis.document.getElementById('next-attention-status')?.textContent ?? '',
  );
const readControl = () => {
  const { document } = globalThis;
  const button = document.querySelector('[data-next-action="enable-notifications"]');
  const note = document.querySelector('.next-notify-note');
  return {
    button: button ? button.textContent.trim() : null,
    note: note ? note.textContent.trim() : null,
  };
};
const controlText = (page) => page.evaluate(readControl);

async function needsYouFocus(page) {
  const focused = await settled(page, () => {
    const active = globalThis.document.activeElement;
    return {
      primary: active?.matches('nav[aria-label="Primary"] a[aria-current="page"]'),
      href: active?.getAttribute('href') ?? null,
      text: active?.textContent ?? '',
    };
  });
  assert.deepEqual(
    focused,
    { primary: true, href: '#n=attention', text: 'Needs you 4' },
    'focus was dropped with the button',
  );
  return focused.text;
}

/* ---- pages ---- */
const holder = { body: null, revision: 10 };
const lanePosts = [];
let sides = 0;
/* Every page that holds permission polls on its own clock and reports a lane the board does not know, so a slow
   run sees posts from pages an earlier step left open. A step counts the posts of the page it is about. */
const postsOf = (side) => lanePosts.filter((post) => post.id === side.id);

async function serve(side) {
  await side.page.route('**/api/data*', (route) => {
    const url = new URL(route.request().url());
    side.dataUrls.push(url.pathname + url.search);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'X-Compass-Revision': `9.${holder.revision}` },
      body: JSON.stringify(holder.body),
    });
  });
  await side.page.route('**/api/lane', (route) => {
    lanePosts.push({ id: side.id, side: side.name, body: route.request().postData() });
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  await side.page.route('**/api/stream', (route) => route.abort('failed'));
}

async function newSide({ notify = { permission: 'default', answer: 'granted' }, viewport } = {}) {
  const origin = board.react.origin;
  const allowed = [board.react.origin, board.react.viteOrigin];
  const side = await openPage(browser, allowed, {
    viewport: viewport ?? { width: 1100, height: 900 },
  });
  side.name = 'react';
  sides += 1;
  side.id = sides;
  side.origin = origin;
  side.dataUrls = [];
  await scriptNotification(side.context, notify);
  await serve(side);
  opened.push(side);
  return side;
}

const reactReady = (page) =>
  page.waitForFunction(
    () =>
      globalThis.document.querySelector('nav[aria-label="Primary"]') &&
      !/Waiting for the first board|first payload has not arrived/.test(
        globalThis.document.body.innerText,
      ),
  );

async function load(side, fragment = '#n=attention') {
  await side.page.goto('about:blank');
  await side.page.goto(`${side.origin}/${fragment}`);
  await reactReady(side.page);
  await side.page.waitForTimeout(patience(150));
}

/* A read taken the instant after an event can still show the previous screen, and a render follows its event by
   a frame or more. A page counts as read once two reads 100 ms apart agree. */
async function settled(page, read, ...args) {
  let previous = await page.evaluate(read, ...args);
  for (let waited = 0; waited < patience(6000); waited += 100) {
    await new Promise((resolve) => setTimeout(resolve, 100));
    const next = await page.evaluate(read, ...args);
    if (JSON.stringify(next) === JSON.stringify(previous)) return next;
    previous = next;
  }
  throw new Error('The page kept changing.');
}

/* One board revision, as another tab's announcement brings it: the board changes, and a storage event carries
   the new revision, which the page treats as a wake. Waits until the page has read it. */
async function revise(change, ...sides) {
  holder.body = attentionBoard(change);
  holder.revision += 1;
  const before = sides.map((side) => side.counts().data);
  for (const side of sides)
    await side.page.evaluate(
      (revision) =>
        globalThis.dispatchEvent(
          new globalThis.StorageEvent('storage', {
            key: 'compass.next.revision',
            newValue: revision,
          }),
        ),
      `9.${holder.revision}`,
    );
  for (const [index, side] of sides.entries()) {
    for (
      let waited = 0;
      waited < patience(5000) && side.counts().data <= before[index];
      waited += 100
    )
      await new Promise((resolve) => setTimeout(resolve, 100));
    assert.ok(
      side.counts().data > before[index],
      `${side.name}: the page never read the revised board`,
    );
  }
  await sides[0].page.waitForTimeout(patience(250));
}

/* Reads until the condition holds, so a runner that delivers a render late is waited for instead of measured
   mid-flight. A condition that never holds throws with what it last saw. */
async function until(read, holds, what) {
  let last;
  for (let waited = 0; waited < patience(6000); waited += 100) {
    last = await read();
    if (holds(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`${what}; last read ${JSON.stringify(last)}`);
}

const sectionToggle = (page, name) => page.locator(`[data-next-attention-toggle="${name}"]`);
const subjectSelector = (sid) =>
  `[data-next-attention-subject="${`session:["claude","${sid}"]`.replaceAll('"', '\\"')}"]`;

// The screen fixture gives each of its five exact requests a native permission wait too.
function withRecordedFixtureWaits(summary) {
  return {
    ...summary,
    sections: summary.sections.map((section) =>
      section.name === 'needs'
        ? {
            ...section,
            items: section.items.map((item) => ({
              ...item,
              text: item.text.replace(
                /^Question waitingIDENTITY(.+?)(NOWApprove step [1-5]\?2 published options)SOURCE/,
                'Question waiting · 1 additional source signalIDENTITY$1$2$1 · Input signal observed: waiting on a permission promptSOURCE',
              ),
            })),
          }
        : section,
    ),
  };
}

try {
  await prepareCopy();
  browser = await chromium.launch();
  board = await startSessionsBoard({ root: copy });
  holder.body = attentionBoard();

  /* ===================== the screen ===================== */
  await step(
    'parity: the React screen reads as the recording does, collapsed and with every section expanded',
    async () => {
      const react = await newSide();
      await load(react);
      const arms = {};
      const mine = await settled(react.page, readAttention);
      assert.ok(!mine.missing, `the React screen did not draw: ${JSON.stringify(mine)}`);
      const counters = await react.page.locator('[data-next-fleet-fact]').allTextContents();
      assert.equal(counters.length, 2);
      assert.ok(counters[0].includes('EXACT REQUESTS'));
      assert.ok(counters[1].includes('REPORTED BLOCKS'));
      const recorded = withRecordedFixtureWaits(golden.observe('the screen, collapsed'));
      const unchangedAttention = (summary) =>
        unchangedAttentionLocations({
          ...summary,
          brief: omitAttentionQuietSubtotals(summary.brief),
        });
      assert.deepEqual(unchangedAttention(clockless(mine)), unchangedAttention(recorded));
      arms.collapsed = mine.sections.map((section) => [section.name, section.items.length]);
      assert.ok(
        mine.sections.some((section) => section.items.some((item) => item.hidden)),
        'a queue longer than three hides its rest',
      );
      for (const name of ['needs', 'next']) await sectionToggle(react.page, name).click();
      const mineOpen = await settled(react.page, readAttention);
      const recordedOpen = withRecordedFixtureWaits(
        golden.observe('the screen, every section expanded'),
      );
      assert.deepEqual(unchangedAttention(clockless(mineOpen)), unchangedAttention(recordedOpen));
      assert.ok(
        mineOpen.sections
          .find((section) => section.name === 'needs')
          .items.every((item) => !item.hidden),
        'every needs row shows once expanded',
      );
      assert.deepEqual(react.log.nonGet, [], 'reading the screen sent nothing');
      assert.deepEqual(react.log.pageErrors, []);
      return arms;
    },
  );

  await step(
    'an expanded section keeps its button, its focus and its state through revisions that reorder and remove rows',
    async () => {
      const react = opened.find((side) => side.name === 'react');
      await load(react);
      const toggle = sectionToggle(react.page, 'needs');
      await toggle.click();
      await react.page.evaluate(() => {
        const button = globalThis.document.querySelector('[data-next-attention-toggle="needs"]');
        button.__mark = 'kept';
        button.focus();
      });
      const kept = await react.page.evaluate((selector) => {
        const node = globalThis.document.querySelector(selector);
        node.__mark = 'kept';
        return Boolean(node);
      }, subjectSelector('gate-2'));
      assert.ok(kept, 'gate-2 is on the board');
      for (const change of [
        { generated: 1_000_025, reversed: true, gone: ['gate-3'] },
        { generated: 1_000_050, reversed: false, gone: ['gate-5'] },
        { generated: 1_000_075, reversed: true },
      ]) {
        await revise(change, react);
        const state = await settled(
          react.page,
          (selector) => {
            const { document } = globalThis;
            const button = document.querySelector('[data-next-attention-toggle="needs"]');
            const section = document.querySelector('[data-next-attention-section="needs"]');
            const rows = [...section.querySelectorAll(':scope > ol > li')];
            return {
              mark: button?.__mark ?? null,
              focused: document.activeElement === button,
              expanded: button?.getAttribute('aria-expanded') ?? null,
              rows: rows.length,
              hidden: rows.filter((row) => row.hasAttribute('hidden')).length,
              subjectMark: document.querySelector(selector)?.__mark ?? null,
            };
          },
          subjectSelector('gate-2'),
        );
        assert.equal(state.mark, 'kept', `the button was replaced by ${JSON.stringify(change)}`);
        assert.equal(state.focused, true, 'focus left the button');
        assert.equal(state.expanded, 'true', 'the section collapsed');
        assert.equal(state.hidden, 0, 'a row is hidden in an expanded section');
        assert.equal(state.subjectMark, 'kept', 'a row still on the board was replaced');
      }
      // A queue that shrinks to three rows has nothing to expand, and the reader's choice waits for it to grow.
      await revise({ generated: 1_000_090, gone: ['gate-3', 'gate-4', 'gate-5'] }, react);
      assert.equal(
        await sectionToggle(react.page, 'needs').count(),
        0,
        'a three-row queue still offers more',
      );
      await revise({ generated: 1_000_110 }, react);
      assert.equal(
        await sectionToggle(react.page, 'needs').getAttribute('aria-expanded'),
        'true',
        'the choice was lost while the queue was short',
      );
      // Leaving the screen and coming back keeps the choice for the tab; closing it is the reader's too.
      await react.page.evaluate(() => {
        globalThis.location.hash = '#n=sessions';
      });
      await react.page.waitForSelector('[data-next-view-body="sessions"]');
      await react.page.evaluate(() => {
        globalThis.location.hash = '#n=attention';
      });
      await react.page.waitForSelector('[data-next-view-body="attention"]');
      assert.equal(
        await sectionToggle(react.page, 'needs').getAttribute('aria-expanded'),
        'true',
        'a route change forgot the expanded section',
      );
      await sectionToggle(react.page, 'needs').click();
      assert.equal(await sectionToggle(react.page, 'needs').getAttribute('aria-expanded'), 'false');
      assert.deepEqual(react.log.nonGet, []);
      holder.body = attentionBoard();
    },
  );

  await step(
    'focus falls to the section heading when the row the reader was on leaves the board',
    async () => {
      const react = opened.find((side) => side.name === 'react');
      holder.body = attentionBoard();
      await load(react);
      await react.page.evaluate(
        (selector) => globalThis.document.querySelector(`${selector} h3 a`).focus(),
        subjectSelector('gate-1'),
      );
      await revise({ generated: 1_000_025, gone: ['gate-1'] }, react);
      const focus = await settled(react.page, () => {
        const active = globalThis.document.activeElement;
        return {
          tag: active?.tagName ?? null,
          text: active?.textContent ?? '',
          inSection: Boolean(active?.closest?.('[data-next-attention-section="needs"]')),
        };
      });
      assert.equal(focus.tag, 'H2', `focus went to ${JSON.stringify(focus)}`);
      assert.ok(focus.inSection && /^Needs you now/.test(focus.text), `focus text ${focus.text}`);
      holder.body = attentionBoard();
    },
  );

  await step(
    'the polite region says "Attention updated" only when a queue changed length, and never for the first board',
    async () => {
      const react = opened.find((side) => side.name === 'react');
      holder.body = attentionBoard();
      await load(react);
      const region = await react.page.evaluate(() => {
        const node = globalThis.document.getElementById('next-attention-status');
        node.__mark = 'kept';
        return {
          role: node.getAttribute('role'),
          live: node.getAttribute('aria-live'),
          text: node.textContent,
        };
      });
      assert.deepEqual(
        region,
        { role: 'status', live: 'polite', text: '' },
        'the first board announced something',
      );
      await revise({ generated: 1_000_025 }, react);
      assert.equal(
        await statusText(react.page),
        '',
        'a board that moved nothing announced something',
      );
      await react.page.evaluate(() => {
        globalThis.location.hash = '#n=sessions';
      });
      await react.page.waitForSelector('[data-next-view-body="sessions"]');
      await revise({ generated: 1_000_050, gone: ['gate-1'] }, react);
      const said = await settled(react.page, () => {
        const node = globalThis.document.getElementById('next-attention-status');
        return { text: node.textContent, mark: node.__mark ?? null };
      });
      assert.equal(
        said.text,
        'Attention updated: 5 need you, 5 at risk, 4 close the loop, 4 coming next',
      );
      assert.equal(said.mark, 'kept', 'the region was rebuilt, so its message arrived with it');
      holder.body = attentionBoard();
    },
  );

  /* ===================== notifications ===================== */
  await step(
    'nothing is asked, raised or posted on mount, StrictMode, a poll, a reconnect or a route change',
    async () => {
      const react = await newSide({
        notify: { permission: 'default', answer: 'granted' },
      });
      holder.body = attentionBoard({ asking: [], unowned: false });
      await load(react);
      await react.page.getByRole('button', { name: 'Enable notifications' }).waitFor();
      for (const change of [
        { generated: 1_000_025 },
        { generated: 1_000_050, blocked: ['gate-1'] },
      ]) {
        await revise({ asking: [], unowned: false, ...change }, react);
      }
      for (const hash of ['#n=sessions', '#n=projects', '#n=attention'])
        await react.page.evaluate((next) => {
          globalThis.location.hash = next;
        }, hash);
      await react.page.waitForSelector('[data-next-view-body="attention"]');
      await pause(400);
      const state = await notifyState(react.page);
      assert.equal(state.asked, 0, 'the browser prompt opened without a press');
      assert.deepEqual(state.made, [], 'a banner was raised without permission');
      assert.deepEqual(react.log.nonGet, [], 'something was posted');
      assert.deepEqual(lanePosts, [], 'the lane was reported by a tab with no permission');
      assert.equal(
        (await controlText(react.page)).button,
        'Enable notifications',
        'the control stands while the reader can still be asked',
      );
      // The StrictMode double mount found one control, not two.
      assert.equal(
        await react.page.locator('[data-next-action="enable-notifications"]').count(),
        1,
      );
    },
  );

  let flowReact = null;
  await step(
    'pressing Enable asks once, reports the lane as two scalars, hands focus back, and the recording says the same',
    async () => {
      holder.body = attentionBoard({ asking: [], unowned: false });
      lanePosts.length = 0;
      flowReact = await newSide({ notify: { permission: 'default', answer: 'granted' } });
      {
        await load(flowReact);
        const button = flowReact.page.getByRole('button', { name: 'Enable notifications' });
        await button.waitFor();
        await button.focus();
        await button.click();
      }
      await until(
        () => flowReact.page.getByRole('button', { name: 'Enable notifications' }).count(),
        (count) => count === 0,
        'the control stayed after the grant',
      );
      await until(
        () => postsOf(flowReact).length,
        (count) => count >= 1,
        'the grant was never reported',
      );
      await pause(400);
      const mine = await notifyState(flowReact.page);
      assert.equal(mine.asked, 1, 'the prompt opens once, on the press');
      assert.equal(mine.permission, 'granted');
      assert.equal(
        await flowReact.page.getByRole('button', { name: 'Enable notifications' }).count(),
        0,
      );
      await needsYouFocus(flowReact.page);
      const posts = postsOf(flowReact);
      assert.equal(posts.length, 1, `React reported the lane ${posts.length} times`);
      assert.deepEqual(JSON.parse(posts[0].body), { supported: true, permission: 'granted' });
      // The bodies the previous interface reported, in order.
      const recordedPosts = golden.observe('the lane the legacy page reported');
      assert.deepEqual(
        recordedPosts,
        posts.map((post) => JSON.parse(post.body)),
        'the lane reports differ from the recording',
      );
      return { reactPosts: posts.length };
    },
  );

  await step(
    'a gate that arrives after the first board raises one banner, once, and the recording raised the same',
    async () => {
      holder.body = attentionBoard({ asking: [], unowned: false, browserLane: true });
      await load(flowReact);
      // The page holds the board without the gate, and did not raise for what it already held.
      assert.deepEqual((await notifyState(flowReact.page)).made, []);
      const change = { asking: [], unowned: false, blocked: ['gate-1'], browserLane: true };
      for (const generated of [1_000_100, 1_000_125, 1_000_150])
        await revise({ ...change, generated }, flowReact);
      const made = (await notifyState(flowReact.page)).made;
      assert.deepEqual(made, [
        {
          title: 'Claude Code is waiting on you',
          body: '[alpha/app] a prompt appeared',
          tag: 'claude:gate-1',
        },
      ]);
      const recordedMade = golden.observe('the banners the legacy page raised');
      assert.deepEqual(recordedMade, made, 'the banners differ from the recording');
    },
  );

  await step(
    'after a reload a granted tab raises nothing for the gate the board already holds, and reports its lane again',
    async () => {
      lanePosts.length = 0;
      holder.body = attentionBoard({ asking: [], unowned: false, blocked: ['gate-1'] });
      const before = (await notifyState(flowReact.page)).made.length;
      await load(flowReact);
      await until(
        () => postsOf(flowReact).length,
        (count) => count >= 1,
        'the reload was not reported to the server that forgot the lane',
      );
      await pause(500);
      const state = await notifyState(flowReact.page);
      assert.equal(state.permission, 'granted', 'the browser keeps its answer across a reload');
      assert.equal(
        state.made.length,
        before,
        'the first board after a reload raised for a gate it already held',
      );
      assert.equal(
        postsOf(flowReact).length,
        1,
        'the reload was not reported to the server that forgot the lane',
      );
      assert.equal(
        await flowReact.page.getByRole('button', { name: 'Enable notifications' }).count(),
        0,
      );
      // A server that already holds the lane is not told again.
      lanePosts.length = 0;
      holder.body = attentionBoard({
        asking: [],
        unowned: false,
        blocked: ['gate-1'],
        browserLane: true,
      });
      holder.revision += 1;
      await load(flowReact);
      await pause(500);
      assert.deepEqual(postsOf(flowReact), [], 'a lane the server holds was reported again');
    },
  );

  await step(
    'questions raise one banner when they arrive and none again for the same ones',
    async () => {
      holder.body = attentionBoard({ browserLane: true });
      const side = await newSide({ notify: { permission: 'granted', answer: 'granted' } });
      await load(side);
      await pause(300);
      const first = (await notifyState(side.page)).made;
      assert.equal(first.length, 1);
      assert.equal(first[0].title, '6 questions are waiting for your answer');
      await revise({ browserLane: true, generated: 1_000_050 }, side);
      assert.equal(
        (await notifyState(side.page)).made.length,
        1,
        'the same questions raised again',
      );
      await revise(
        {
          browserLane: true,
          generated: 1_000_075,
          asking: ['gate-1', 'gate-2', 'gate-3', 'gate-4', 'gate-5', 'task-1'],
        },
        side,
      );
      const made = (await notifyState(side.page)).made;
      assert.equal(made.length, 2, 'a new question raised nothing');
      assert.equal(made[1].tag, 'compass-ask:ask-task-1');
    },
  );

  await step(
    'a refused prompt says so and offers nothing; no Notification API draws nothing; the server’s lane owns its banners',
    async () => {
      holder.body = attentionBoard({ asking: [], unowned: false, browserLane: true });
      const denied = await newSide({ notify: { permission: 'denied', answer: 'denied' } });
      await load(denied);
      const note = await settled(denied.page, readControl);
      assert.deepEqual(note, { button: null, note: 'notifications blocked' });

      const absent = await newSide({
        notify: { permission: 'default', answer: 'granted', absent: true },
      });
      await load(absent);
      assert.deepEqual(await settled(absent.page, readControl), { button: null, note: null });
      assert.deepEqual(absent.log.pageErrors, [], 'a page without the API threw');
      // The refused stream is this script's own, so its failed load is the one console line that is expected.
      assert.deepEqual(
        absent.log.consoleErrors.filter((line) => !/ERR_FAILED/.test(line)),
        [],
      );

      holder.body = attentionBoard({
        asking: [],
        unowned: false,
        nativeNotify: 'osascript',
        browserLane: true,
      });
      const native = await newSide({
        notify: { permission: 'granted', answer: 'granted' },
      });
      await load(native);
      await revise(
        {
          asking: [],
          unowned: false,
          nativeNotify: 'osascript',
          browserLane: true,
          blocked: ['gate-1'],
          generated: 1_000_050,
        },
        native,
      );
      assert.deepEqual(await controlText(native.page), { button: null, note: null });
      assert.deepEqual(
        (await notifyState(native.page)).made,
        [],
        'the browser raised what the native lane owns',
      );
    },
  );

  await step(
    'a command-shape report whose stamp is no date is printed without a time, and the screen still draws',
    async () => {
      holder.body = attentionBoard({ malformedReport: true });
      const side = await newSide();
      await load(side);
      const text = await settled(
        side.page,
        () => globalThis.document.querySelector('[data-next-command-reports]')?.textContent ?? '',
      );
      assert.match(text, /Command shape reported: git push --force/);
      assert.match(text, /claude · nobody · Bash(?! ·)/);
      assert.deepEqual(side.log.pageErrors, []);
    },
  );

  await step(
    'a granted tab reports its lane once for a collection, however often the page reads it, and again for a newer one',
    async () => {
      holder.body = attentionBoard({
        asking: [],
        unowned: false,
        browserLane: false,
        generated: 1_000_000,
      });
      const side = await newSide({ notify: { permission: 'granted', answer: 'granted' } });
      await load(side);
      await until(
        () => postsOf(side).length,
        (count) => count >= 1,
        'the first board was not reported',
      );
      for (let wake = 0; wake < 3; wake += 1) {
        await revise(
          { asking: [], unowned: false, browserLane: false, generated: 1_000_000 },
          side,
        );
      }
      await pause(400);
      assert.equal(
        postsOf(side).length,
        1,
        `the same collection was reported ${postsOf(side).length} times`,
      );
      await revise({ asking: [], unowned: false, browserLane: false, generated: 1_000_025 }, side);
      await until(
        () => postsOf(side).length,
        (count) => count >= 2,
        'a newer collection was not reported',
      );
      await pause(400);
      assert.equal(postsOf(side).length, 2);
    },
  );

  /* ===================== keyboard ===================== */
  await step(
    'keyboard: Show more, Copy, Raise and Enable notifications are reached by Tab and operated by Enter and Space, and keep their focus',
    async () => {
      const trace = { react: {} };
      const nameOf = (side, pattern) =>
        side.page.evaluate((source) => {
          const re = new RegExp(source, 'i');
          const text = (node) =>
            (node.getAttribute('aria-label') || node.textContent || '').replace(/\s+/g, ' ').trim();
          const found = [
            ...globalThis.document.querySelectorAll('[data-next-attention-section="needs"] button'),
          ].find((node) => re.test(text(node)));
          return found ? text(found) : null;
        }, pattern.source);
      const nonGetTo = (side, path) =>
        side.log.nonGet.filter((entry) => entry.path === path).length;

      holder.body = attentionBoard({ terminals: true });
      {
        const side = await newSide();
        await recordClipboard(side.context);
        await load(side);
        const seen = trace.react;

        // Show more: Tab reaches the section's toggle, Enter opens it and Space closes it, and focus stays on it.
        {
          const toggle = sectionToggle(side.page, 'needs');
          const name = await toggle.evaluate((node) =>
            (node.getAttribute('aria-label') || node.textContent).replace(/\s+/g, ' ').trim(),
          );
          assert.match(name, /more/i, `the toggle reads "${name}"`);
          seen.showMoreTabs = await tabTo(side.page, name);
          await side.page.keyboard.press('Shift+Tab');
          assert.notEqual(await focusedLabel(side.page), name, 'Shift+Tab did not leave');
          await side.page.keyboard.press('Tab');
          assert.equal(await focusedLabel(side.page), name, 'Tab did not come back');
          await side.page.keyboard.press('Enter');
          assert.equal(await toggle.getAttribute('aria-expanded'), 'true', 'Enter did not expand');
          const open = await settled(side.page, readAttention);
          assert.ok(
            open.sections
              .find((section) => section.name === 'needs')
              .items.every((item) => !item.hidden),
            'every needs row shows once expanded by keyboard',
          );
          assert.equal(
            await toggle.evaluate((node) => node === globalThis.document.activeElement),
            true,
            'focus left the toggle on Enter',
          );
          await side.page.keyboard.press('Space');
          assert.equal(
            await toggle.getAttribute('aria-expanded'),
            'false',
            'Space did not collapse',
          );
          assert.equal(
            await toggle.evaluate((node) => node === globalThis.document.activeElement),
            true,
            'focus left the toggle on Space',
          );
          seen.showMore = 'enter opens, space closes, focus kept';
        }

        // Copy: Enter writes the resume command once, and the button keeps focus.
        {
          const name = await nameOf(side, /copy/);
          assert.ok(name, 'the gate row offers no Copy');
          seen.copyTabs = await tabTo(side.page, name);
          const before = await side.page.evaluate(() => globalThis.__copied.length);
          await side.page.keyboard.press('Enter');
          await until(
            () => side.page.evaluate(() => globalThis.__copied.length),
            (count) => count === before + 1,
            'Enter on Copy did not write exactly once',
          );
          assert.equal(await focusedLabel(side.page), name, 'focus left Copy after the press');
          seen.copied = await side.page.evaluate(() => globalThis.__copied.at(-1));
        }

        // Raise: Space sends one request, and the button keeps focus. The inert raise answers; nothing is raised.
        {
          const name = await nameOf(side, /raise the terminal/);
          assert.ok(name, 'the gate row offers no Raise');
          seen.raiseTabs = await tabTo(side.page, name);
          side.pressedRaise = true;
          const before = nonGetTo(side, '/api/focus');
          await side.page.keyboard.press('Space');
          await until(
            () => nonGetTo(side, '/api/focus'),
            (count) => count === before + 1,
            'Space on Raise did not send exactly one request',
          );
          await pause(400);
          assert.equal(
            nonGetTo(side, '/api/focus'),
            before + 1,
            'a press sent more than one request',
          );
          assert.equal(await focusedLabel(side.page), name, 'focus left Raise after the press');
        }
        await side.close();
      }

      // Enable notifications: Tab reaches it on a tab that can still be asked, Enter asks once, and focus is handed back.
      holder.body = attentionBoard({ asking: [], unowned: false });
      lanePosts.length = 0;
      {
        const side = await newSide({ notify: { permission: 'default', answer: 'granted' } });
        await load(side);
        const seen = trace.react;
        {
          seen.enableTabs = await tabTo(side.page, 'Enable notifications');
          await side.page.keyboard.press('Enter');
          await until(
            () => notifyState(side.page).then((state) => state.asked),
            (asked) => asked === 1,
            'Enter on Enable notifications did not ask exactly once',
          );
          await until(
            () => side.page.getByRole('button', { name: 'Enable notifications' }).count(),
            (count) => count === 0,
            'the control stayed after the grant',
          );
          await pause(300);
          assert.equal((await notifyState(side.page)).asked, 1);
          seen.afterEnable = await needsYouFocus(side.page);
        }
        await side.close();
      }
      holder.body = attentionBoard();
      return trace;
    },
  );

  /* ===================== layout and captures ===================== */
  await step('the screen does not scroll sideways at 320, 375 and 640 CSS px', async () => {
    holder.body = attentionBoard({ terminals: false });
    const widths = {};
    for (const width of [320, 375, 640]) {
      const side = await newSide({ viewport: { width, height: 900 } });
      await load(side);
      widths[width] = await settled(side.page, () => ({
        scroll: globalThis.document.documentElement.scrollWidth,
        client: globalThis.document.documentElement.clientWidth,
      }));
      assert.ok(
        widths[width].scroll <= widths[width].client,
        `scrolls sideways at ${width}: ${JSON.stringify(widths[width])}`,
      );
      await side.close();
    }
    return widths;
  });

  if (shotsOn)
    await step('screenshots: Attention wide and narrow, collapsed and expanded', async () => {
      await mkdir(SHOTS, { recursive: true });
      holder.body = attentionBoard();
      const taken = [];
      for (const width of [1280, 375]) {
        const side = await newSide({ viewport: { width, height: 1100 } });
        await load(side);
        for (const expanded of [false, true]) {
          if (expanded)
            for (const name of ['needs', 'next']) await sectionToggle(side.page, name).click();
          await side.page.waitForTimeout(patience(300));
          const file = join(SHOTS, `attention-react-${width}${expanded ? '-expanded' : ''}.png`);
          await side.page.screenshot({ path: file, fullPage: true });
          taken.push(file);
        }
      }
      return { taken: taken.length };
    });

  await step(
    'no board read carried the usage parameter, and nothing asked to raise a terminal',
    async () => {
      const reads = opened.flatMap((side) => side.dataUrls);
      assert.ok(reads.length > 10, 'the pages read the board');
      assert.deepEqual(
        reads.filter((url) => /usage/.test(url)),
        [],
        'a board read carried the usage parameter',
      );
      // A page where the keyboard step pressed Raise sent the one request that press is for; every other page, and
      // every page for a notification, asked for nothing.
      assert.deepEqual(
        opened.flatMap((side) =>
          side.log.requests.filter(
            (entry) =>
              /^\/api\/notify/.test(entry.path) ||
              (!side.pressedRaise && /^\/api\/focus/.test(entry.path)),
          ),
        ),
        [],
      );
      return { reads: reads.length };
    },
  );

  for (const side of opened) {
    if (side.log.externalRequests.length)
      failures.push({ name: 'externals', message: JSON.stringify(side.log.externalRequests) });
    if (side.name === 'react' && side.log.pageErrors.length)
      failures.push({ name: 'page errors', message: JSON.stringify(side.log.pageErrors) });
  }
} finally {
  for (const side of opened) await side.close().catch(() => undefined);
  if (browser) await browser.close();
  if (board) await board.close();
  if (!ownsRepository) await rm(copy, { recursive: true, force: true });
}

console.log(JSON.stringify({ attention: results, mutation: mutation || null }, null, 2));
// A mutation run is expected to fail and a filtered run skips steps, so neither records nor checks the golden.
golden.finish({ complete: failures.length === 0 && !only && !mutation });
if (failures.length) {
  console.error(JSON.stringify({ failures }, null, 2));
  process.exitCode = 1;
}
