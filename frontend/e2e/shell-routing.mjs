/*
 * The React shell in a real browser, against the real backend (DRC-4823).
 *
 * Two kinds of proof. The DIFFERENTIAL half drives the React page against the synthetic board and compares
 * what a reader can observe (canonical fragment, document title, current primary item, breadcrumb sentence,
 * header counts, history depth after Back and Escape and reload) with what the previous interface showed
 * for every route contract in scripts/frontend-migration.json. The BEHAVIOUR half holds
 * the React page to the criteria a unit test cannot see: StrictMode action counts, notices at one and two
 * failures, focus, scroll and a held select across refreshes, tab keys, 320/375 widths, 200% zoom and
 * reduced motion.
 *
 * Models, usage, focus and notifications are off in the fixture backend; nothing here reads a harness
 * store, a clipboard or a terminal. Run with `pnpm test:shell:browser`; `COMPASS_E2E_STEPS=<regex>`
 * runs only the steps whose name matches.
 *
 * What the previous interface said is read through `support/golden.mjs` from
 * `frontend/test/golden/e2e/shell-routing.json`, a recording that cannot be remade because that interface is gone.
 * Every differential step keeps its React side strict and compares it with the recorded reading. Dropped with the
 * interface, with its reason: the assertion that it asked for nothing outside the board, which was a fact about its
 * own requests with no React counterpart (the React page's are asserted by the behaviour steps).
 */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { BOARD, openPage, observeShell, startBoard } from './support/browser.mjs';
import { BROWSER_CONTEXT, goldenFor } from './support/golden.mjs';

/* Every fixed wait here means "give the page time to react". A hosted runner has a few shared cores and draws frames,
   fires timers and delivers stream events later than a desktop does, so each wait is tripled there. A wait that is too
   long only slows a pass: the assertion after it is unchanged. */
const patience = (ms) => (process.env.CI ? ms * 3 : ms);

// Captures land in the gitignored docs/screenshots/ of this checkout unless a run names another directory.
const SHOTS = (
  process.env.COMPASS_SCREENSHOTS ||
  fileURLToPath(new URL('../../docs/screenshots', import.meta.url))
).replace(/\/?$/, '/');
const E = encodeURIComponent;
const receipts = {};
const failures = [];

/* `COMPASS_E2E_STEPS=<regex>` runs only the steps whose name matches, for working on one of them. */
const only = process.env.COMPASS_E2E_STEPS ? new RegExp(process.env.COMPASS_E2E_STEPS) : null;

async function step(name, run) {
  if (only && !only.test(name)) return;
  try {
    const detail = await run();
    receipts[name] = detail === undefined ? 'ok' : detail;
  } catch (error) {
    failures.push({ name, message: String(error.message || error).slice(0, 1500) });
    receipts[name] = 'FAILED';
  }
}

/* ---- readiness: the React page says so on screen ---- */
const reactReady = (page) =>
  page.waitForFunction(
    () =>
      globalThis.document.querySelector('nav[aria-label="Primary"]') &&
      !/Waiting for the first board|first payload has not arrived/.test(
        globalThis.document.body.innerText,
      ),
  );

async function load(opened, origin, fragment = '') {
  await opened.page.goto('about:blank');
  await opened.page.goto(origin + '/' + fragment);
  await reactReady(opened.page);
  await opened.page.waitForTimeout(patience(150));
}

const counts = (page) =>
  page.evaluate(() => {
    const running = globalThis.document.querySelector('.next-running');
    const gate = globalThis.document.querySelector('.next-gate');
    const norm = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : null);
    return { running: norm(running), gate: norm(gate) };
  });

/* ---- the route contracts: every row of `routes` in the ownership map, as fragments ---- */
const A = E('alpha/app');
const B = E('beta/api');
const ROUTES = [
  ['bare-or-invalid-fragment: bare', ''],
  ['bare-or-invalid-fragment: empty token', '#n='],
  ['bare-or-invalid-fragment: unknown view', '#n=bogus'],
  ['top-level-sessions', '#n=sessions'],
  ['top-level-attention', '#n=attention'],
  ['top-level-projects', '#n=projects'],
  ['top-level-intent', '#n=intent'],
  ['project-root', `#n=project:${A}`],
  ['project-root: absent project', `#n=project:${E('nowhere')}`],
  ['project-tabs: course', `#n=project:${A}:course`],
  ['project-tabs: decisions', `#n=project:${A}:decisions`],
  ['project-tabs: console', `#n=project:${A}:console`],
  ['project-tabs: now is the default', `#n=project:${A}:now`],
  ['project-exact-session-focus', `#n=project:${A}:${E('claude:shared-sid')}`],
  ['project-exact-session-focus: with tab', `#n=project:${A}:${E('claude:shared-sid')}:console`],
  ['project-exact-session-focus: stale focus', `#n=project:${A}:${E('claude:gone')}`],
  ['session-exact-harness-and-id: claude', `#n=session:${A}:claude:shared-sid`],
  ['session-exact-harness-and-id: codex', `#n=session:${A}:codex:shared-sid`],
  ['session-exact-harness-and-id: colon sid', `#n=session:${B}:claude:${E('colon:sid')}`],
  ['session-exact-harness-and-id: empty project', '#n=session::codex:bare-project-sid'],
  ['session-exact-harness-and-id: absent session', `#n=session:${A}:claude:gone`],
  ['session-legacy-id-form: unambiguous', `#n=session:${B}:${E('colon:sid')}`],
  ['session-legacy-id-form: ambiguous across harnesses', `#n=session:${A}:shared-sid`],
  ['session-origin-from: sessions', `#n=session:${A}:claude:shared-sid&from=sessions`],
  ['session-origin-from: attention', `#n=session:${A}:claude:shared-sid&from=attention`],
  ['session-origin-from: intent', `#n=session:${A}:claude:shared-sid&from=intent`],
  ['session-origin-from: projects', `#n=session:${A}:claude:shared-sid&from=projects`],
  ['session-origin-from: project', `#n=session:${A}:claude:shared-sid&from=project`],
  ['session-origin-from: unknown is omitted', `#n=session:${A}:claude:shared-sid&from=elsewhere`],
  ['retired-held-to-alias', `#n=project:${A}:${E('claude:shared-sid')}:held-to`],
  ['retired-held-to-alias: no harness', `#n=project:${A}:${E('lonely')}:held-to`],
  ['malformed-encoding: project in a session', '#n=session:%E0%A4%A:claude:one'],
  ['malformed-encoding: sid in a session', `#n=session:${A}:claude:%E0%A4%A`],
  ['malformed-encoding: id-only form', '#n=session:%E0%A4%A:one'],
  ['malformed-encoding: project root', '#n=project:%E0%A4%A'],
];

/* What each contract must canonicalise to, written out so the comparison with the recording is not the
   only oracle. */
const CANONICAL = new Map([
  ['', '#n=sessions'],
  ['#n=', '#n=sessions'],
  ['#n=bogus', '#n=sessions'],
  [`#n=project:${A}:now`, `#n=project:${A}`],
  [`#n=project:${A}:${E('claude:shared-sid')}:held-to`, `#n=session:${A}:claude:shared-sid`],
  [`#n=session:${A}:claude:shared-sid&from=elsewhere`, `#n=session:${A}:claude:shared-sid`],
  ['#n=session:%E0%A4%A:claude:one', '#n=sessions'],
  ['#n=session:%E0%A4%A:one', '#n=sessions'],
  ['#n=project:%E0%A4%A', '#n=sessions'],
  ['#n=session::codex:bare-project-sid', '#n=session::codex:bare-project-sid'],
]);

/* A difference found by the comparison is a failure unless it is named here with its reason, so a
   justified deviation is a recorded fact and never a silent skip. Each entry is `{route, field, reason}`. */
const DEVIATIONS = [
  {
    field: 'primary',
    reason: 'Sessions precedes Projects under DEC-27; all routes and labels still compare.',
  },
  {
    field: 'breadcrumb and header counts',
    reason: '2026-11-22: Phosphor replaces the breadcrumb separator and running mark.',
  },
];

const browser = await chromium.launch();
const golden = goldenFor('shell-routing');
const board = await startBoard();
const reactOrigins = [board.react.origin, board.react.dev.viteOrigin];
const shots = [];
let react;

try {
  await mkdir(SHOTS, { recursive: true });
  react = await openPage(browser, reactOrigins);

  /* ===================== DIFFERENTIAL: the previous interface's recording vs the React page ===================== */
  await step('differential: every route contract reads as the recording does', async () => {
    const mismatches = [];
    for (const [name, fragment] of ROUTES) {
      const recorded = golden.observe(`routes: ${name}`);
      await load(react, board.react.origin, fragment);
      const l = {
        ...recorded.shell,
        primary: ['Sessions', 'Projects', ...recorded.shell.primary.slice(2)],
      };
      const r = await observeShell(react.page);
      for (const field of [
        'hash',
        'title',
        'current',
        'primary',
        'breadcrumb',
        'search',
        'historyLength',
      ]) {
        if (JSON.stringify(l[field]) !== JSON.stringify(r[field]))
          mismatches.push({ route: name, field, recorded: l[field], react: r[field] });
      }
      if (CANONICAL.has(fragment))
        assert.equal(r.hash, CANONICAL.get(fragment), `${name}: canonical fragment`);
      const lc = {
        ...recorded.counts,
        running: recorded.counts.running?.replace(/^●\s*/, '') ?? null,
      };
      const rc = await counts(react.page);
      if (!fragment.startsWith('#n=project:')) {
        if (JSON.stringify(lc) !== JSON.stringify(rc))
          mismatches.push({ route: name, field: 'header counts', recorded: lc, react: rc });
      }
    }
    assert.deepEqual(
      mismatches,
      [],
      'the page and the recording disagree: ' + JSON.stringify(mismatches, null, 1),
    );
    return `${ROUTES.length} routes compared`;
  });

  await step(
    'differential: reload and Escape read as the recording does for every session route that carries an origin',
    async () => {
      const mismatches = [];
      const trace = async (opened, origin, fragment) => {
        await load(opened, origin, fragment);
        const before = await observeShell(opened.page);
        await opened.page.reload();
        await reactReady(opened.page);
        await opened.page.waitForTimeout(patience(100));
        const reloaded = await observeShell(opened.page);
        await opened.page.keyboard.press('Escape');
        await opened.page.waitForTimeout(patience(100));
        const escaped = await observeShell(opened.page);
        return {
          before: [before.hash, before.current, before.breadcrumb],
          reloaded: [reloaded.hash, reloaded.current, reloaded.breadcrumb],
          escaped: [escaped.hash, escaped.current],
        };
      };
      for (const [name, fragment] of ROUTES.filter(([, f]) => f.includes('session:'))) {
        const after = {};
        after.recorded = golden.observe(`reload and Escape: ${name}`);
        after.react = await trace(react, board.react.origin, fragment);
        if (JSON.stringify(after.recorded) !== JSON.stringify(after.react))
          mismatches.push({ route: name, ...after });
        assert.deepEqual(
          after.react.before,
          after.react.reloaded,
          `${name}: reload keeps the session, tab and crumb`,
        );
      }
      assert.deepEqual(
        mismatches,
        [],
        'reload or Escape differs: ' + JSON.stringify(mismatches, null, 1),
      );
    },
  );

  await step(
    'differential: Back and Forward leave the recorded hash and history depth',
    async () => {
      const walk = async (opened, origin) => {
        await load(opened, origin, '#n=sessions');
        const seen = [];
        const note = async (label) => {
          const o = await observeShell(opened.page);
          seen.push([label, o.hash, o.current, o.historyLength]);
        };
        await opened.page.getByRole('link', { name: 'Attention', exact: true }).first().click();
        await note('Attention');
        await opened.page.getByRole('link', { name: 'Projects', exact: true }).first().click();
        await note('Projects');
        await opened.page.goBack();
        await note('Back');
        await opened.page.goBack();
        await note('Back');
        await opened.page.goForward();
        await note('Forward');
        return seen;
      };
      const trace = {
        recorded: golden.observe('back and forward'),
        react: await walk(react, board.react.origin),
      };
      assert.deepEqual(trace.react, trace.recorded);
    },
  );

  /* ---- differential, continued: the notices, with the faults the recording was made under ---- */
  async function faulted(origin, shape) {
    const opened = await openPage(browser, reactOrigins);
    const state = { fail: false, mutate: null };
    await opened.page.clock.install({ time: Date.now() });
    await opened.page.route('**/api/stream', (route) => route.abort('failed'));
    await opened.page.route('**/api/data*', async (route) => {
      if (state.fail) return route.abort('failed');
      const response = await route.fetch();
      if (!state.mutate) return route.fulfill({ response });
      return route.fulfill({ response, json: state.mutate(await response.json()) });
    });
    if (shape.boot === 'fail') state.fail = true;
    await opened.page.goto(origin + '/#n=sessions');
    await opened.page.locator('nav[aria-label="Primary"]').waitFor();
    if (shape.boot !== 'fail') await reactReady(opened.page);
    await opened.page.waitForTimeout(patience(400));
    opened.state = state;
    opened.poll = async () => {
      await opened.page.clock.fastForward(20_000);
      await opened.page.waitForTimeout(patience(250));
    };
    return opened;
  }
  const noticeText = async (page) =>
    (
      await page.evaluate(() =>
        [...globalThis.document.querySelectorAll('[data-next-state]')].map(
          (node) =>
            `${node.getAttribute('data-next-state')}: ${node.textContent.replace(/\s+/g, ' ').trim()}`,
        ),
      )
    ).map((line) => line.replace(/Last updated \d+[smhd]( \d+[smh])? ago/, 'Last updated N ago'));

  await step(
    'differential: a failed refresh, a history reset and a newer build read as the recording does',
    async () => {
      const notices = async (origin) => {
        const o = await faulted(origin, {});
        try {
          const seen = [];
          o.state.fail = true;
          await o.poll();
          seen.push(['one failure', await noticeText(o.page)]);
          await o.poll();
          seen.push(['two failures', await noticeText(o.page)]);
          await o.poll();
          seen.push(['three failures', await noticeText(o.page)]);
          o.state.fail = false;
          await o.page.getByRole('button', { name: 'Retry now' }).click();
          await o.page.waitForTimeout(patience(400));
          seen.push(['after Retry now', await noticeText(o.page)]);
          o.state.mutate = (body) => ({
            ...body,
            history_reset: 'unreadable',
            build: 'a-different-build',
          });
          await o.poll();
          seen.push(['reset and new build', await noticeText(o.page)]);
          o.state.mutate = (body) => ({ ...body, history_reset: '<img src=x>' });
          await o.poll();
          seen.push(['unknown reset', await noticeText(o.page)]);
          return seen;
        } finally {
          await o.close();
        }
      };
      const trace = {
        recorded: golden.observe('notices'),
        react: await notices(board.react.origin),
      };
      assert.deepEqual(trace.react, trace.recorded, JSON.stringify(trace, null, 1));
      assert.deepEqual(trace.react[0][1], [], 'one failure shows nothing');
      assert.match(
        trace.react[1][1][0],
        /^stalled: Live refresh failed twice in a row\.\s*Displayed data may be stale\. Last updated N ago\. Retrying automatically every 20s\.\s*Retry now$/,
      );
    },
  );

  await step(
    'differential: before the first payload the previous interface counted zero and the React page states the absence',
    async () => {
      const before = async (origin) => {
        const o = await faulted(origin, { boot: 'fail' });
        try {
          return (await counts(o.page)).running;
        } finally {
          await o.close();
        }
      };
      const seen = {
        recorded: golden.observe('before the first payload'),
        react: await before(board.react.origin),
      };
      assert.match(
        seen.recorded,
        /0 running · 0 subagents observed/,
        'the previous interface claimed a measured zero before any board',
      );
      assert.equal(seen.react, 'Waiting for the first board.');
      DEVIATIONS.push({
        route: 'any, before the first payload',
        field: 'header counts',
        recorded: seen.recorded,
        react: seen.react,
        reason:
          'a count nobody measured is not zero, and the live dot would claim a board is being watched',
      });
      return 'recorded as a deviation';
    },
  );

  /* ===================== BEHAVIOUR: the React page ===================== */
  await step(
    'routes: every contract prints the canonical fragment the contract states',
    async () => {
      const expected = new Map([
        [
          `#n=session:${A}:claude:shared-sid&from=attention`,
          `#n=session:${A}:claude:shared-sid&from=attention`,
        ],
        [
          `#n=project:${A}:${E('claude:shared-sid')}:console`,
          `#n=project:${A}:${E('claude:shared-sid')}:console`,
        ],
        [`#n=session:${A}:shared-sid`, `#n=session:${A}:shared-sid`],
      ]);
      for (const [fragment, canonical] of expected) {
        await load(react, board.react.origin, fragment);
        assert.equal((await observeShell(react.page)).hash, canonical);
      }
    },
  );

  await step(
    'history: a canonical rewrite replaces the entry, so Back is never stuck on a dead link',
    async () => {
      await load(react, board.react.origin, '');
      const clean = (await observeShell(react.page)).historyLength;
      await load(react, board.react.origin, '#n=bogus');
      assert.equal(
        (await observeShell(react.page)).historyLength,
        clean,
        'a bogus fragment added a history entry',
      );
      await load(react, board.react.origin, `#n=project:${A}:${E('claude:shared-sid')}:held-to`);
      assert.equal(
        (await observeShell(react.page)).historyLength,
        clean,
        'the held-to alias added a history entry',
      );
      await react.page.goBack();
      assert.equal(
        react.page.url(),
        'about:blank',
        'Back from the first board page leaves the board, so no entry was added behind it',
      );
    },
  );

  await step(
    'history: a malformed fragment typed into an open page is rewritten in place, so Back is never stuck on it',
    async () => {
      // A page of its own: Chromium keeps at most 50 history entries, and the page the earlier steps used is full.
      const o = await openPage(browser, reactOrigins);
      try {
        await o.page.goto(board.react.origin + '/#n=attention');
        await reactReady(o.page);
        const before = (await observeShell(o.page)).historyLength;
        await o.page.evaluate(() => {
          globalThis.location.hash = '#n=bogus';
        });
        await o.page.waitForFunction(() => globalThis.location.hash === '#n=sessions');
        await o.page.waitForTimeout(patience(150));
        const typed = await observeShell(o.page);
        assert.equal(
          typed.historyLength,
          before + 1,
          'typing a fragment adds one entry, and its rewrite adds none',
        );
        assert.equal(typed.current, 'Sessions');
        await o.page.goBack();
        await o.page.waitForTimeout(patience(250));
        assert.equal(
          (await observeShell(o.page)).hash,
          '#n=attention',
          'Back returns to the preceding view instead of bouncing forward off the dead link',
        );
        await o.page.evaluate(
          (next) => {
            globalThis.location.hash = next;
          },
          `#n=project:${A}:${E('claude:shared-sid')}:held-to`,
        );
        await o.page.waitForTimeout(patience(250));
        assert.equal((await observeShell(o.page)).hash, `#n=session:${A}:claude:shared-sid`);
        await o.page.goBack();
        await o.page.waitForTimeout(patience(250));
        assert.equal(
          (await observeShell(o.page)).hash,
          '#n=attention',
          'Back from the aliased session returns to where the reader was',
        );
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'history: Escape walks a session back to where it came from, and Back returns across in-page moves',
    async () => {
      await load(react, board.react.origin, `#n=session:${A}:claude:shared-sid&from=attention`);
      await react.page.keyboard.press('Escape');
      await react.page.waitForTimeout(patience(80));
      assert.equal((await observeShell(react.page)).hash, '#n=attention');
      await react.page.goBack();
      assert.equal(
        (await observeShell(react.page)).hash,
        `#n=session:${A}:claude:shared-sid&from=attention`,
      );
      await react.page.keyboard.press('KeyA');
      await react.page.waitForTimeout(patience(60));
      assert.equal((await observeShell(react.page)).hash, '#n=attention');
      await react.page.keyboard.press('KeyP');
      await react.page.waitForTimeout(patience(60));
      assert.equal((await observeShell(react.page)).hash, '#n=projects');
      await react.page.keyboard.press('KeyS');
      await react.page.waitForTimeout(patience(60));
      assert.equal((await observeShell(react.page)).hash, '#n=sessions');
    },
  );

  await step(
    'project tabs: Now is the default and the arrow keys wrap over the strip, keeping focus on the new tab',
    async () => {
      await load(react, board.react.origin, `#n=project:${A}`);
      /* A tab carried its count in its accessible name ("Course No observed state changes observed") in the previous interface, so a tab
         is found by its label as the first word of that name; Now and Console carry no cue and are their label. */
      const tab = (name) => react.page.getByRole('tab', { name: new RegExp(`^${name}( |$)`) });
      assert.equal(await tab('Now').getAttribute('aria-selected'), 'true');
      await tab('Now').focus();
      await react.page.keyboard.press('ArrowLeft');
      assert.equal(
        (await observeShell(react.page)).hash,
        `#n=project:${A}:console`,
        'ArrowLeft from Now wraps to Console',
      );
      assert.equal(
        await react.page.evaluate(() => globalThis.document.activeElement.textContent),
        'Console',
      );
      await react.page.keyboard.press('ArrowRight');
      assert.equal(
        (await observeShell(react.page)).hash,
        `#n=project:${A}`,
        'ArrowRight from Console wraps to Now, which prints no tab',
      );
      await react.page.keyboard.press('End');
      assert.equal((await observeShell(react.page)).hash, `#n=project:${A}:console`);
      await react.page.keyboard.press('Home');
      assert.equal((await observeShell(react.page)).hash, `#n=project:${A}`);
      assert.equal(
        await react.page.evaluate(() => globalThis.document.activeElement.textContent),
        'Now',
      );
      assert.equal(await tab('Now').getAttribute('tabindex'), '0');
      assert.equal(await tab('Course').getAttribute('tabindex'), '-1');
    },
  );

  await step(
    'project focus: a stale session filter says so and links to the project root',
    async () => {
      await load(react, board.react.origin, `#n=project:${A}:${E('claude:gone')}`);
      assert.ok(
        await react.page.getByText('Session filter is outside this payload window').isVisible(),
      );
      await react.page.getByRole('link', { name: 'View project root' }).click();
      assert.equal((await observeShell(react.page)).hash, `#n=project:${A}`);
    },
  );

  await step(
    'absence: an absent project and an absent session are stated, and the legacy id form never picks an owner',
    async () => {
      await load(react, board.react.origin, `#n=project:${E('nowhere')}`);
      assert.ok(await react.page.getByText('Not present in the current payload.').isVisible());
      await load(react, board.react.origin, `#n=session:${A}:claude:gone`);
      assert.ok(
        await react.page.getByText('This session is not in the current payload.').isVisible(),
      );
      await load(react, board.react.origin, `#n=session:${A}:shared-sid`);
      assert.ok(
        await react.page.getByText('This session is not in the current payload.').isVisible(),
        'two harnesses carry the sid, so no owner is chosen',
      );
    },
  );

  await step(
    'actions: nothing is sent, opened or polled by a mount, StrictMode, a route change or a keypress',
    async () => {
      /* A fresh browser context, because the leader lease lives in localStorage: a page loaded moments after
       another in the same profile is a follower, and a follower opens no stream. */
      const o = await openPage(browser, reactOrigins);
      try {
        await o.page.goto(board.react.origin + '/#n=sessions');
        await reactReady(o.page);
        // The boot read and the stream's first announcement land at a pace that depends on the machine's load, so
        // wait for the request count to hold still before counting what the interactions add.
        let last = '';
        for (let still = 0; still < 6; ) {
          await o.page.waitForTimeout(patience(250));
          const now = JSON.stringify(o.counts());
          still = now === last ? still + 1 : 0;
          last = now;
        }
        const boot = o.counts();
        assert.equal(boot.stream, 1, 'one event stream under StrictMode');
        // The boot read, the stream's first announcement and a follow-up read for each time the fixture board's wall-clock
        // revision advanced between them: a loaded hosted runner saw four. A duplicated start under StrictMode would
        // show as a second stream, asserted above, and a poll would keep climbing through the interaction phase below,
        // whose bound is the one that proves nothing is sent; the runtime's own start counts are pinned in its unit tests.
        assert.ok(
          boot.data >= 1 && boot.data <= 6,
          `boot read, the stream's first wake and the board's revision follow-ups, saw ${boot.data}`,
        );
        assert.equal(boot.nonGet, 0);
        o.reset();
        for (const fragment of [
          '#n=attention',
          '#n=projects',
          `#n=project:${A}`,
          `#n=project:${A}:course`,
          `#n=session:${A}:claude:shared-sid`,
          '#n=intent',
          '#n=sessions',
        ]) {
          await o.page.evaluate((next) => {
            globalThis.location.hash = next;
          }, fragment);
          await o.page.waitForTimeout(patience(40));
        }
        for (const key of ['KeyA', 'KeyP', 'KeyS', 'Escape', 'KeyD'])
          await o.page.keyboard.press(key);
        await o.page.waitForTimeout(patience(300));
        // Twelve interactions that each caused a read would show twelve. One read can still be the stream's first
        // announcement arriving after the settle window above on a slow runner, so one is allowed; the runtime's unit
        // tests pin the exact count with a fake clock.
        const after = o.counts();
        assert.ok(after.data <= 1, `interactions caused ${after.data} data reads`);
        assert.deepEqual({ stream: after.stream, nonGet: after.nonGet }, { stream: 0, nonGet: 0 });
        assert.deepEqual(o.log.externalRequests, []);
        assert.deepEqual([...o.log.consoleErrors, ...o.log.pageErrors], []);
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'ownership: React owns the page and the five live regions stand beside it, empty, and never move',
    async () => {
      await load(react, board.react.origin, '#n=sessions');
      const shape = await react.page.evaluate(() => {
        const { document } = globalThis;
        const regions = [...document.querySelectorAll('[aria-live]')];
        globalThis.__regions = regions;
        return {
          bodyChildren: [...document.body.children].map(
            (node) => node.tagName + (node.id ? '#' + node.id : ''),
          ),
          rootChildren: [...document.getElementById('root').children].map(
            (node) => node.tagName + (node.id ? '#' + node.id : ''),
          ),
          regions: regions.map((node) => [
            node.id,
            node.getAttribute('role'),
            node.getAttribute('aria-live'),
            node.textContent,
            document.getElementById('app').contains(node),
          ]),
        };
      });
      assert.ok(
        shape.bodyChildren.every((name) => name === 'DIV#root' || name.startsWith('SCRIPT')),
        'nothing but the root and scripts: ' + shape.bodyChildren,
      );
      assert.deepEqual(shape.rootChildren.slice(0, 1), ['MAIN#app']);
      assert.equal(shape.regions.length, 5);
      for (const [id, , , text, inside] of shape.regions) {
        assert.equal(text, '', `${id} is empty before anything is said`);
        assert.equal(inside, false, `${id} is outside the replaceable page`);
      }
      assert.deepEqual(shape.regions.map(([, role, live]) => [role, live]).sort(), [
        ['alert', 'assertive'],
        ['status', 'polite'],
        ['status', 'polite'],
        ['status', 'polite'],
        ['status', 'polite'],
      ]);
      // Watch the regions across routes, a refresh and keys: nothing may be written into any of them.
      await react.page.evaluate(() => {
        globalThis.__writes = 0;
        const observer = new globalThis.MutationObserver((records) => {
          globalThis.__writes += records.length;
        });
        for (const node of globalThis.__regions)
          observer.observe(node, { childList: true, characterData: true, subtree: true });
      });
      for (const fragment of [
        '#n=attention',
        `#n=project:${A}`,
        `#n=session:${A}:claude:shared-sid`,
        '#n=sessions',
      ]) {
        await react.page.evaluate((next) => {
          globalThis.location.hash = next;
        }, fragment);
        await react.page.waitForTimeout(patience(40));
      }
      const after = await react.page.evaluate(() => ({
        writes: globalThis.__writes,
        same: [...globalThis.document.querySelectorAll('[aria-live]')].every(
          (node, index) => node === globalThis.__regions[index],
        ),
      }));
      assert.deepEqual(
        after,
        { writes: 0, same: true },
        'the regions were replaced or written to by navigation alone',
      );
    },
  );

  await step(
    'query: only ?all=1 widens the data scope; usage and next are never read from the address',
    async () => {
      const status = async (path) =>
        (await react.context.request.get(board.react.origin + path)).status();
      assert.equal(await status('/?all=1'), 200);
      for (const path of ['/?next=true', '/?next=false', '/?next=', '/?all=1&next=true'])
        assert.equal(await status(path), 404, path);
      react.reset();
      await load(react, board.react.origin, '#n=sessions');
      await react.page.waitForTimeout(patience(300));
      assert.ok(
        react.log.requests.some((entry) => entry.path === '/api/data'),
        'the plain board reads /api/data',
      );
      assert.ok(
        !react.log.requests.some((entry) => entry.path.includes('all=1')),
        'no all=1 without the query',
      );
      react.reset();
      await react.page.goto('about:blank');
      await react.page.goto(board.react.origin + '/?all=1&usage=1&nextish=true#n=sessions');
      await reactReady(react.page);
      await react.page.waitForTimeout(patience(300));
      const data = react.log.requests
        .filter((entry) => entry.path.startsWith('/api/data'))
        .map((entry) => entry.path);
      assert.ok(
        data.length >= 1 && data.every((path) => path === '/api/data?all=1'),
        'only all=1 rides the data read, saw ' + JSON.stringify(data),
      );
      react.reset();
    },
  );

  await step(
    'bookmark: an exact session fragment keeps ?all=1 and reopens the same session after a reload',
    async () => {
      const link = `${board.react.origin}/?all=1#n=session:${A}:codex:shared-sid`;
      await react.page.goto('about:blank');
      await react.page.goto(link);
      await reactReady(react.page);
      const first = await observeShell(react.page);
      await react.page.reload();
      await reactReady(react.page);
      const second = await observeShell(react.page);
      assert.deepEqual(
        [second.hash, second.search, second.breadcrumb],
        [first.hash, '?all=1', 'Sessions › Alpha shared codex'],
      );
      assert.equal(second.title, 'Alpha shared codex — alpha/app — Compass');
    },
  );

  await step(
    'keyboard: Tab reaches the four views in order and then the block button, and project tabs roam by tabindex',
    async () => {
      const o = await openPage(browser, reactOrigins);
      try {
        await o.page.goto(board.react.origin + '/#n=sessions');
        await reactReady(o.page);
        await o.page.evaluate(() => globalThis.document.body.focus());
        const seen = [];
        for (let press = 0; press < 5; press += 1) {
          await o.page.keyboard.press('Tab');
          seen.push(await o.page.evaluate(() => globalThis.document.activeElement.textContent));
        }
        assert.deepEqual(seen, [
          'Sessions',
          'Projects',
          'Attention',
          'Intent log',
          '1 reported block',
        ]);
        assert.equal(await o.page.getByRole('navigation', { name: 'Primary' }).count(), 1);
        await o.page.goto('about:blank');
        await o.page.goto(board.react.origin + `/#n=project:${A}`);
        await reactReady(o.page);
        const tabindexes = await o.page.getByRole('tab').evaluateAll((tabs) =>
          tabs.map((tab) => [
            // The label is the button's first text; the cue after it is the page's own.
            tab.firstChild.textContent,
            tab.getAttribute('tabindex'),
            tab.getAttribute('aria-selected'),
          ]),
        );
        assert.deepEqual(tabindexes, [
          ['Now', '0', 'true'],
          ['Course', '-1', 'false'],
          ['Decisions', '-1', 'false'],
          ['Console', '-1', 'false'],
        ]);
        assert.equal(
          await o.page.getByRole('tablist', { name: 'Project cockpit views' }).count(),
          1,
        );
        assert.equal(await o.page.getByRole('tabpanel').count(), 1);
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'keyboard: project arrows activate their route and modified keys keep browser ownership',
    async () => {
      const o = await openPage(browser, reactOrigins);
      try {
        await o.page.goto(board.react.origin + `/#n=project:${A}`);
        await reactReady(o.page);
        const tabs = o.page.getByRole('tab');
        const assertActive = async (index, fragment) => {
          await o.page.waitForFunction(
            ({ index, hash }) =>
              location.hash === hash &&
              document.querySelectorAll('[role=tab]')[index] === document.activeElement &&
              document.activeElement.getAttribute('aria-selected') === 'true',
            { index, hash: `#n=project:${A}${fragment}` },
            { timeout: patience(5000) },
          );
          assert.deepEqual(
            await tabs.evaluateAll((nodes) => nodes.map((node) => node.getAttribute('tabindex'))),
            [0, 1, 2, 3].map((i) => (i === index ? '0' : '-1')),
          );
        };
        await tabs.nth(0).focus();
        for (const [key, index, fragment] of [
          ['ArrowLeft', 3, `:console`],
          ['ArrowRight', 0, ''],
          ['ArrowRight', 1, ':course'],
          ['End', 3, ':console'],
          ['Home', 0, ''],
        ]) {
          await o.page.keyboard.press(key);
          await assertActive(index, fragment);
        }
        for (const [key, start, focused, target, fragment] of [
          ['End', '', 3, 3, ':console'],
          ['Home', ':console', 0, 0, ''],
          ['ArrowRight', '', 3, 0, ''],
          ['ArrowLeft', ':console', 0, 3, ':console'],
        ]) {
          await load(o, board.react.origin, `#n=project:${A}${start}`);
          await tabs.nth(focused).focus();
          await assertActive(focused, focused === 0 ? '' : ':console');
          await o.page.goBack();
          await o.page.waitForFunction(
            ({ index, hash }) =>
              location.hash === hash &&
              document.querySelectorAll('[role=tab]')[index] === document.activeElement &&
              document.activeElement.getAttribute('aria-selected') === 'false',
            { index: focused, hash: `#n=project:${A}${start}` },
            { timeout: patience(5000) },
          );
          await tabs.nth(focused).evaluate((node) => {
            node.addEventListener(
              'keydown',
              (event) => {
                node.proofKeyEvent = event;
              },
              { once: true },
            );
          });
          await o.page.keyboard.press(key);
          await assertActive(target, fragment);
          assert.equal(
            await tabs.nth(focused).evaluate((node) => {
              const cancelled = node.proofKeyEvent.defaultPrevented;
              delete node.proofKeyEvent;
              return cancelled;
            }),
            true,
            key,
          );
        }
        await tabs.nth(0).focus();
        await assertActive(0, '');
        const result = await tabs.nth(0).evaluate(async (node) => {
          const before = location.hash;
          const presses = [];
          for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
            for (const modifier of ['altKey', 'ctrlKey', 'metaKey']) {
              const event = new KeyboardEvent('keydown', {
                key,
                [modifier]: true,
                bubbles: true,
                cancelable: true,
              });
              presses.push({ key, modifier, uncancelled: node.dispatchEvent(event) });
            }
          }
          await Promise.resolve();
          return {
            presses,
            routeHeld: location.hash === before,
            focusHeld: document.activeElement === node,
          };
        });
        assert.ok(
          result.presses.every((press) => press.uncancelled),
          JSON.stringify(result),
        );
        assert.ok(result.routeHeld && result.focusHeld, JSON.stringify(result));
        return 'five route activations, four cancelled activations after Back and twelve uncancelled modified keys';
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'absence: a board that never answers is stated as absent, never as an empty healthy board',
    async () => {
      const o = await openPage(browser, reactOrigins);
      try {
        await o.page.clock.install({ time: Date.now() });
        await o.page.route('**/api/data*', (route) => route.abort('failed'));
        await o.page.goto(board.react.origin + '/#n=sessions');
        await o.page.locator('nav[aria-label="Primary"]').waitFor();
        await o.page.waitForTimeout(patience(300));
        assert.equal(
          (await o.page.locator('.next-running').innerText()).trim(),
          'Waiting for the first board.',
        );
        assert.equal(
          await o.page.locator('.next-status-icon').count(),
          0,
          'no live dot over a board nobody has read',
        );
        for (let poll = 0; poll < 2; poll += 1) {
          await o.page.clock.fastForward(20_000);
          await o.page.waitForTimeout(patience(200));
        }
        const text = (await o.page.locator('[data-next-state="stalled"]').innerText()).replace(
          /\s+/g,
          ' ',
        );
        assert.match(text, /No data has been received in this tab\./);
        assert.doesNotMatch(text, /stale|Last updated/);
        assert.doesNotMatch(await o.page.locator('body').innerText(), /0 running|0 subagents/);
        assert.ok(
          await o.page.getByText('No data has been received in this tab.').first().isVisible(),
          'the view says the board is absent',
        );
      } finally {
        await o.close();
      }
    },
  );

  /* ---- notices, focus, scroll and the held select, under a fake clock so a poll is a step ---- */
  async function clocked(fragment = '#n=sessions', mutate = null) {
    const opened = await openPage(browser, reactOrigins);
    const state = { fail: false, mutate };
    await opened.page.clock.install({ time: Date.now() });
    await opened.page.route('**/api/data*', async (route) => {
      if (state.fail) return route.abort('failed');
      const response = await route.fetch();
      if (!state.mutate) return route.fulfill({ response });
      const body = await response.json();
      return route.fulfill({ response, json: state.mutate(body) });
    });
    /* The event stream is refused, so the only reads are the boot read and the polls a test steps the clock
       to. An announcement that landed between two steps would be one more failure in a count the test is
       making exact, and which one it landed on varies with the machine's load. */
    await opened.page.route('**/api/stream', (route) => route.abort('failed'));
    await opened.page.goto(board.react.origin + '/' + fragment);
    await reactReady(opened.page);
    await opened.page.waitForTimeout(patience(400));
    opened.state = state;
    opened.poll = async () => {
      await opened.page.clock.fastForward(20_000);
      await opened.page.waitForTimeout(patience(250));
    };
    return opened;
  }

  await step(
    'notices: a failed refresh is told at the second failure, quotes the interval, and one success clears it',
    async () => {
      const o = await clocked();
      try {
        o.state.fail = true;
        await o.poll();
        assert.equal(
          await o.page.getByText(/Live refresh failed/).count(),
          0,
          'one failure says nothing',
        );
        await o.poll();
        const notice = o.page.locator('[data-next-state="stalled"]');
        assert.ok(await notice.isVisible(), 'two failures show the notice');
        const text = (await notice.innerText()).replace(/\s+/g, ' ');
        assert.match(text, /Live refresh failed twice in a row\./);
        assert.match(text, /Displayed data may be stale\./);
        assert.match(text, /Retrying automatically every 20s\./);
        assert.match(
          await o.page.locator('.next-running').innerText(),
          /2 running/,
          'the rows stay on screen and are not zeroed',
        );
        // The keyboard path: Retry now, then the removal of the notice must not drop focus on the page, and a
        // reader who scrolled away from the parked control is not dragged back up to the fallback.
        await o.page.addStyleTag({ content: '#app{min-height:3000px}' });
        await o.page.getByRole('button', { name: 'Retry now' }).focus();
        await o.page.evaluate(() => globalThis.scrollTo(0, 900));
        const noticeHeight = await notice.evaluate((node) =>
          Math.ceil(node.getBoundingClientRect().height),
        );
        o.state.fail = false;
        await o.page.keyboard.press('Enter');
        await o.page.waitForFunction(
          () => !globalThis.document.querySelector('[data-next-state="stalled"]'),
        );
        await o.page.waitForTimeout(patience(100));
        const landed = await o.page.evaluate(() => ({
          focus: globalThis.document.activeElement.textContent,
          scrollY: Math.round(globalThis.scrollY),
        }));
        assert.equal(landed.focus, 'Sessions', 'focus falls back to the current primary item');
        // The browser's own scroll anchoring keeps the rows the reader was looking at in place, so the page can move up by
        // the notice that went away and the margins around it, and by nothing more: it is never dragged back to the fallback
        // control, which would put it near 0.
        assert.ok(
          landed.scrollY <= 900 && landed.scrollY >= 900 - noticeHeight - 60,
          `the page was scrolled by more than the notice and its margins: ${JSON.stringify({ ...landed, noticeHeight })}`,
        );
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'notices: a newer build asks for a reload, keeps its Why open across polls, and reloads only on the press',
    async () => {
      const o = await clocked();
      try {
        o.state.mutate = (body) => ({ ...body, build: 'a-different-build' });
        await o.poll();
        const notice = o.page.locator('[data-next-state="build-changed"]');
        assert.ok(await notice.isVisible());
        assert.ok(await notice.getByText('Reload to use the new version.').isVisible());
        await notice.getByText('Why reload').click();
        await o.poll();
        assert.ok(
          await notice.getByText(/restarted with a different version/).isVisible(),
          'the disclosure stayed open across a poll',
        );
        const navigated = o.page.waitForEvent('framenavigated', { timeout: 5000 });
        // The disclosure trigger "Why reload" is a button now, so a substring name matches two.
        await notice.getByRole('button', { name: 'Reload', exact: true }).click();
        await navigated;
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'notices: a history reset names which reset it was and an unknown literal draws nothing',
    async () => {
      const o = await clocked('#n=sessions', (body) => ({ ...body, history_reset: 'unreadable' }));
      try {
        const text = await o.page.locator('[data-next-state="history-reset"]').innerText();
        assert.match(text, /The saved history was reset\./);
        assert.match(text, /The saved file could not be read\./);
        o.state.mutate = (body) => ({ ...body, history_reset: '<img src=x onerror=alert(1)>' });
        await o.poll();
        assert.equal(await o.page.locator('[data-next-state="history-reset"]').count(), 0);
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'refresh: a refresh moves no focus, no scroll offset, no title and no live region',
    async () => {
      const o = await clocked();
      try {
        await o.page.addStyleTag({ content: '#app{min-height:3000px}' });
        await o.page.evaluate(() => {
          const link = [
            ...globalThis.document.querySelectorAll('nav[aria-label="Primary"] a'),
          ].find((a) => a.textContent === 'Attention');
          link.focus();
          globalThis.__focused = link;
          globalThis.scrollTo(0, 900);
          globalThis.__titles = 0;
          new globalThis.MutationObserver(() => {
            globalThis.__titles += 1;
          }).observe(globalThis.document.querySelector('title'), { childList: true });
          globalThis.__writes = 0;
          const observer = new globalThis.MutationObserver((records) => {
            globalThis.__writes += records.length;
          });
          for (const node of globalThis.document.querySelectorAll('[aria-live]'))
            observer.observe(node, { childList: true, characterData: true });
        });
        /* Text selection is not managed: a stable node keeps the browser's own highlight, and nothing here
         restores one. The heading is a stable node, so its selection must survive a refresh untouched. */
        await o.page.evaluate(() => {
          const heading = globalThis.document.querySelector('h1');
          const range = globalThis.document.createRange();
          range.selectNodeContents(heading);
          const selection = globalThis.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          globalThis.__selected = selection.toString();
        });
        for (let poll = 0; poll < 3; poll += 1) {
          o.state.mutate = (body) => ({ ...body, generated: body.generated + poll + 1 });
          await o.poll();
        }
        const after = await o.page.evaluate(() => ({
          sameNode: globalThis.document.activeElement === globalThis.__focused,
          scrollY: Math.round(globalThis.scrollY),
          titles: globalThis.__titles,
          writes: globalThis.__writes,
          selection:
            globalThis.getSelection().toString() === globalThis.__selected &&
            globalThis.__selected.length > 0,
        }));
        assert.deepEqual(after, {
          sameNode: true,
          scrollY: 900,
          titles: 0,
          writes: 0,
          selection: true,
        });
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'refresh: an open Base UI list holds a poll paint, and the board catches up once when it closes',
    async () => {
      const source = (body) => ({
        ...body,
        annotate: true,
        sessions: body.sessions.map((row) => ({
          ...row,
          first_prompt: 'A prompt to choose',
          first_prompt_at: body.generated - 10,
        })),
      });
      const o = await clocked(`#n=session:${A}:claude:shared-sid`, source);
      try {
        const select = o.page.locator('[data-next-cockpit-prompt-select]');
        await select.click();
        await o.page.getByRole('listbox').waitFor();
        assert.match(await o.page.locator('.next-running').innerText(), /2 running/);
        o.state.mutate = (body) => ({
          ...source(body),
          sessions: source(body).sessions.map((row) => ({ ...row, state: 'idle', active: false })),
        });
        await o.poll();
        assert.match(
          await o.page.locator('.next-running').innerText(),
          /2 running/,
          'the held board did not repaint under an open list',
        );
        assert.equal(await select.getAttribute('aria-expanded'), 'true');
        await o.page.keyboard.press('Escape');
        assert.match(o.page.url(), /#n=session:/);
        await o.page.waitForFunction(() =>
          /0 running/.test(globalThis.document.querySelector('.next-running').textContent),
        );
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'more menu: on a project route it stays open across polls and keeps its Copy briefing result, copies the briefing it built, and copies nothing for a project it cannot build one for',
    async () => {
      const o = await clocked(`#n=project:${A}`);
      try {
        await o.page.evaluate(() => {
          globalThis.__clipboardWrites = [];
          Object.defineProperty(globalThis.navigator, 'clipboard', {
            configurable: true,
            value: {
              writeText: async (text) => {
                globalThis.__clipboardWrites.push(String(text));
              },
            },
          });
        });
        assert.equal(
          await o.page.locator('.next-running').count(),
          0,
          'a project page keeps the counts in its More menu',
        );
        await o.page.locator('summary[aria-label="More"]').click();
        const status = o.page.getByText('All projects · 2 running · 3 subagents observed');
        // The menu fades open over 160 ms, and its content is not visible until the fade has begun.
        await status.waitFor({ state: 'visible' });
        o.state.mutate = (body) => ({ ...body, generated: body.generated + 1 });
        await o.poll();
        assert.ok(await status.isVisible(), 'the menu stayed open across a poll');
        assert.deepEqual(
          await o.page.evaluate(() => globalThis.__clipboardWrites),
          [],
          'nothing is copied before a press',
        );
        await o.page.getByRole('button', { name: 'Copy briefing' }).click();
        await o.page.getByRole('button', { name: 'Copied' }).waitFor();
        const written = await o.page.evaluate(() => globalThis.__clipboardWrites);
        assert.equal(written.length, 1, 'one press writes one briefing');
        assert.ok(
          written[0].startsWith('Compass recovery briefing\nProject: app\nScope: Project\n'),
          `the briefing the project page builds was copied: ${written[0].slice(0, 80)}`,
        );
        assert.match(
          await o.page.locator('#next-cockpit-cue-status').innerText(),
          /Copied the project briefing/,
        );
        o.state.mutate = (body) => ({ ...body, generated: body.generated + 2 });
        await o.poll();
        await o.page.evaluate((next) => {
          globalThis.location.hash = next;
        }, `#n=project:${A}:course`);
        await o.page.waitForTimeout(patience(100));
        assert.ok(
          await o.page.getByRole('button', { name: 'Copied' }).isVisible(),
          'the result has no expiry and survives a tab change in the same project',
        );
        assert.equal(
          (await o.page.evaluate(() => globalThis.__clipboardWrites)).length,
          1,
          'a poll and a tab change copy nothing more',
        );
        await o.page.evaluate((next) => {
          globalThis.location.hash = next;
        }, `#n=project:${B}`);
        await o.page.waitForTimeout(patience(100));
        assert.ok(
          await o.page.getByRole('button', { name: 'Copy briefing' }).isVisible(),
          'a different project reads its own, untouched',
        );
        // A project the board does not hold has no briefing to build: the press says so and writes nothing.
        await o.page.evaluate(
          (next) => {
            globalThis.location.hash = next;
          },
          `#n=project:${E('nowhere')}`,
        );
        await o.page.waitForTimeout(patience(100));
        await o.page.getByRole('button', { name: 'Copy briefing' }).click();
        await o.page.getByRole('button', { name: 'Copy unavailable' }).waitFor();
        assert.equal(
          (await o.page.evaluate(() => globalThis.__clipboardWrites)).length,
          1,
          'no briefing exists for it, so no empty one is written',
        );
        assert.match(
          await o.page.locator('#next-cockpit-cue-status').innerText(),
          /There is no briefing to copy: the project is not in the current payload/,
        );
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'layout: no horizontal page scroll at 320 and 375 CSS px, at 200% zoom and at 200% text size, notices included',
    async () => {
      const wide = [];
      const shapes = [
        { width: 320, height: 700, dpr: 1 },
        { width: 375, height: 800, dpr: 1 },
        { width: 320, height: 700, dpr: 2 },
        { width: 375, height: 800, dpr: 2 },
      ];
      const fragments = [
        '#n=sessions',
        '#n=attention',
        `#n=project:${A}:console`,
        `#n=project:${E('a-very-long-project-name-that-has-no-break-opportunity-at-all-'.repeat(3))}`,
        `#n=session:${B}:claude:${E('colon:sid')}&from=project`,
        '#n=session:%E0%A4%A:claude:one',
      ];
      for (const shape of shapes) {
        const context = await browser.newContext({
          ...BROWSER_CONTEXT,
          viewport: { width: shape.width, height: shape.height },
          deviceScaleFactor: shape.dpr,
        });
        const page = await context.newPage();
        await page.route('**/*', (route) => {
          const url = route.request().url();
          return reactOrigins.some((origin) => url.startsWith(origin)) || url.startsWith('data:')
            ? route.continue()
            : route.abort();
        });
        try {
          for (const fragment of fragments) {
            await page.goto('about:blank');
            await page.goto(board.react.origin + '/' + fragment);
            await reactReady(page);
            for (const textScale of ['100%', '200%']) {
              await page.evaluate((scale) => {
                globalThis.document.documentElement.style.fontSize = scale;
              }, textScale);
              const overflow = await page.evaluate(() => {
                const root = globalThis.document.documentElement;
                return {
                  scroll: root.scrollWidth,
                  client: root.clientWidth,
                  bodyScroll: globalThis.document.body.scrollWidth,
                };
              });
              if (overflow.scroll > overflow.client || overflow.bodyScroll > overflow.client)
                wide.push({ ...shape, fragment, textScale, ...overflow });
            }
          }
          await page.evaluate(() => {
            globalThis.document.documentElement.style.fontSize = '';
          });
          if (shape.dpr === 1) {
            await page.goto('about:blank');
            await page.goto(board.react.origin + '/#n=sessions');
            await reactReady(page);
            const name = `shell-react-${shape.width}.png`;
            await page.screenshot({ path: SHOTS + name, fullPage: false });
            shots.push(name);
          }
        } finally {
          await context.close();
        }
      }
      assert.deepEqual(wide, [], 'horizontal overflow: ' + JSON.stringify(wide, null, 1));
    },
  );

  await step(
    'layout: a failure notice and a build notice wrap at 320 without horizontal scroll',
    async () => {
      const o = await clocked('#n=sessions');
      try {
        await o.page.setViewportSize({ width: 320, height: 800 });
        o.state.mutate = (body) => ({ ...body, build: 'another', history_reset: 'version' });
        o.state.fail = false;
        await o.poll();
        const overflow = await o.page.evaluate(() => ({
          scroll: globalThis.document.documentElement.scrollWidth,
          client: globalThis.document.documentElement.clientWidth,
        }));
        assert.ok(overflow.scroll <= overflow.client, JSON.stringify(overflow));
        await o.page.screenshot({ path: SHOTS + 'shell-react-320-notices.png' });
        shots.push('shell-react-320-notices.png');
      } finally {
        await o.close();
      }
    },
  );

  await step('motion: the live dot pulses, and stops under reduced motion', async () => {
    const animation = async (reducedMotion) => {
      const o = await openPage(browser, reactOrigins, { reducedMotion });
      try {
        await o.page.goto(board.react.origin + '/#n=sessions');
        await reactReady(o.page);
        return await o.page.evaluate(
          () =>
            globalThis.getComputedStyle(
              globalThis.document.querySelector('.next-live .next-status-icon'),
            ).animationName,
        );
      } finally {
        await o.close();
      }
    };
    assert.equal(await animation('no-preference'), 'next-live-pulse');
    assert.equal(await animation('reduce'), 'none');
  });

  await step(
    'desktop: screenshots of the shell at desktop width, on a session route and with a notice',
    async () => {
      const o = await clocked(`#n=session:${A}:claude:shared-sid&from=attention`);
      try {
        await o.page.setViewportSize({ width: 1280, height: 720 });
        await o.page.screenshot({ path: SHOTS + 'shell-react-desktop-session.png' });
        shots.push('shell-react-desktop-session.png');
      } finally {
        await o.close();
      }
    },
  );
} finally {
  await react?.close();
  await browser.close();
  await board.close();
}

golden.finish({ complete: !only && failures.length === 0 });

console.log(
  JSON.stringify(
    {
      shell: receipts,
      deviations: DEVIATIONS,
      screenshots: shots,
      board: { sessions: BOARD.sessions.length },
    },
    null,
    2,
  ),
);
if (failures.length) {
  console.error(JSON.stringify({ failures }, null, 2));
  process.exitCode = 1;
}
