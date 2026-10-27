import { sessionDeviations } from './support/session-deviations.mjs';
/*
 * The Sessions screen and the session page in a real browser, against the real backend (DRC-4824).
 *
 * Two kinds of proof. The DIFFERENTIAL half drives the React page over a payload and compares what a reader can
 * read with what the previous interface showed for it: each group, each row in order, its text and its one-step
 * link, then each session's page. The payload is the real board's (frozen once so the page sees one clock) and then
 * a run of generated payloads that reach the states the real board does not. The BEHAVIOUR half holds the React
 * page to what a unit test cannot see: StrictMode resource counts over repeated navigation, answering a held
 * request through the real route (and a refusal, and a stale card), a disclosure and a focused link surviving a
 * poll, keyboard operation, hostile text, and 320/375/640/1280 CSS px layouts with no horizontal page scroll.
 *
 * Models, usage, notifications, the clipboard and the terminal are off or replaced: the page's clipboard is a
 * recorder, the terminal raise is inert, and the Intent panel the previous interface drew beside the activity
 * column is outside the comparison (it is a stated slot in the React page). Run with
 * `pnpm test:sessions:browser`; `COMPASS_E2E_STEPS=<regex>` runs only the steps whose name matches,
 * `SESSIONS_E2E_SEEDS` sets how many generated payloads the differential compares.
 *
 * What the previous interface said is read through `support/golden.mjs` from
 * `frontend/test/golden/e2e/sessions-parity.json`, a recording that cannot be remade because that interface is
 * gone. A generated payload is keyed by seed and by the digest of the payload, so a generator that changes misses
 * its golden. Dropped with the interface, with the reason: its own overflow numbers and screenshots in the layout
 * step (nothing there was asserted of it), and its external-request check.
 */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { openPage } from './support/browser.mjs';
import { digest } from './support/golden.mjs';
import {
  instrumentResources,
  recordClipboard,
  resources,
  startSessionsBoard,
} from './sessions-board.mjs';

/* Every fixed wait here means "give the page time to react". A hosted runner has a few shared cores and delivers
   events and frames later than a desktop, so each wait is tripled there; only a pass gets slower. */
const patience = (ms) => (process.env.CI ? ms * 3 : ms);

// The generator is TypeScript the unit tests also use; Node 26 strips the types as it imports it.
process.removeAllListeners('warning');
const { genPayload } = await import('../src/observed/generate.test.helper.ts');

// A proof belongs to its worktree; sibling captures must not overwrite one another.
const checkout = fileURLToPath(new URL('../../', import.meta.url));
const SHOTS = (process.env.COMPASS_SCREENSHOTS || `${checkout}docs/screenshots`).replace(
  /\/?$/,
  '/',
);
const SEEDS = Number(process.env.SESSIONS_E2E_SEEDS || 10);
const E = encodeURIComponent;
const receipts = {};
const failures = [];
const only = process.env.COMPASS_E2E_STEPS ? new RegExp(process.env.COMPASS_E2E_STEPS) : null;

async function step(name, run) {
  if (only && !only.test(name)) return;
  try {
    const detail = await run();
    receipts[name] = detail === undefined ? 'ok' : detail;
  } catch (error) {
    failures.push({ name, message: String(error.stack || error.message || error).slice(0, 2500) });
    receipts[name] = 'FAILED';
  }
}

/* ---- what a reader can read, reduced to data. These run IN the page, so they are self-contained. ---- */
const summarizeList = () => {
  const norm = (node) => {
    if (!node) return '';
    const clone = node.cloneNode(true);
    // Recorded snapshots included closed native bodies. Rejoin the retained
    // portal content by its labelled trigger without rewriting the live tree.
    for (const trigger of clone.querySelectorAll('[data-slot=popover-trigger]')) {
      const popup = [...document.querySelectorAll('[data-slot=popover-content]')].find(
        (popup) => popup.getAttribute('aria-labelledby') === trigger.id,
      );
      if (popup) trigger.parentElement.append(popup.cloneNode(true));
    }
    return clone.textContent.replace(/\s+/g, ' ').trim();
  };
  const { document } = globalThis;
  const root = document.querySelector('[data-next-view-body="sessions"]');
  if (!root) return { missing: true, text: norm(document.body).slice(0, 200) };
  return {
    header: (() => {
      const header = root.querySelector('.next-operations-header').cloneNode(true);
      const trigger = header.querySelector('[data-slot=popover-trigger]');
      const popup = [...document.querySelectorAll('[data-slot=popover-content]')].find(
        (popup) => popup.getAttribute('aria-labelledby') === trigger?.id,
      );
      trigger?.parentElement.remove();
      for (const body of popup?.querySelectorAll('.next-why-body') || [])
        header.append(body.cloneNode(true));
      return norm(header);
    })(),
    fleet: [...root.querySelectorAll('[data-next-fleet-fact]')].map((node) => [
      node.dataset.nextFleetFact,
      norm(node),
    ]),
    groups: [...root.querySelectorAll('[data-next-operation-group]')].map((group) => ({
      kind: group.dataset.nextOperationGroup,
      header: norm(group.querySelector(':scope > header')),
      empty: group.querySelector('.next-sessions-empty')
        ? norm(group.querySelector('.next-sessions-empty'))
        : null,
      rows: [
        ...group.querySelectorAll('article[data-slot="card"][data-variant="session-row"]'),
      ].map((row) => {
        const route = row.querySelector('a.next-operation-route');
        return {
          harness: row.dataset.nextHarness,
          sid: row.dataset.nextSession,
          history: row.dataset.nextOperationHistory === 'true',
          tone: [...row.classList].find((name) => name.startsWith('next-operation-row--')) || '',
          href: route ? route.getAttribute('href') : null,
          aria: route ? route.getAttribute('aria-label') : null,
          text: norm(row),
          buttons: [...row.querySelectorAll('button')].map((button) =>
            button.getAttribute('aria-label'),
          ),
        };
      }),
    })),
  };
};

const summarizeDetail = () => {
  const norm = (node) => {
    if (!node) return '';
    const clone = node.cloneNode(true);
    // Recorded snapshots included closed native bodies. Rejoin the retained
    // portal content by its labelled trigger without rewriting the live tree.
    for (const trigger of clone.querySelectorAll('[data-slot=popover-trigger]')) {
      const popup = [...document.querySelectorAll('[data-slot=popover-content]')].find(
        (popup) => popup.getAttribute('aria-labelledby') === trigger.id,
      );
      if (popup) trigger.parentElement.append(popup.cloneNode(true));
    }
    return clone.textContent.replace(/\s+/g, ' ').trim();
  };
  const { document } = globalThis;
  const empty = document.querySelector('.next-session-detail-empty');
  const article = document.querySelector('article.next-session-detail');
  if (!article) {
    return {
      empty: empty
        ? {
            state: empty.getAttribute('data-next-session-state'),
            text: norm(empty),
            links: [...empty.querySelectorAll('a')].map((a) => a.getAttribute('href')),
          }
        : { missing: true },
    };
  }
  const clone = article.cloneNode(true);
  // The Intent panel and its pill are the Intent step's, and a stated slot on the React page.
  clone.querySelector('.next-session-panel')?.remove();
  clone.querySelectorAll('[data-next-drift-pill]').forEach((node) => node.remove());
  /* Predates the one-column page (2026-10-19): the two-column next-session-columns and next-session-activity
     layout is gone, so this fails when the proof is run on demand until it is brought forward to Intent,
     What the session has done, Drift and the collapsed Full activity. */
  // The activity column, child by child, for the parts this step owns. The activity list the panel feeds is not one.
  const own = [
    '.next-session-activity-heading',
    '.next-session-command-surface',
    '[data-next-session-subagents]',
    'dl.next-session-facts',
    '[data-slot=accordion].next-session-facts-more',
    '.next-session-evidence',
    '[data-slot=alert][data-variant=session-health]',
    '[data-next-session-section="tasks"]',
    '[data-next-command-reports]',
    '.next-session-delivery',
    '.next-cockpit-landed',
    '.next-cockpit-departures-kept',
  ];
  const parts = [...clone.querySelector('.next-session-activity').children]
    .map((child) => {
      const hit = own.find((selector) => child.matches(selector));
      return hit
        ? [
            hit
              .replace('[data-slot=accordion]', 'details')
              .replace('[data-slot=alert][data-variant=session-health]', '.next-session-health'),
            norm(child),
          ]
        : null;
    })
    .filter(Boolean);
  const header = clone.querySelector('.next-session-detail-header');
  // The previous measured line ended in the activity list's own count, which the list that is not drawn here carries.
  const meta = clone.querySelector('.next-session-detail-meta');
  if (meta && !header.contains(meta))
    header.querySelector('.next-session-detail-bar').prepend(meta);
  if (meta) meta.textContent = meta.textContent.replace(/ · \d+ entr(?:y|ies)\b/, '');
  const ask = clone.querySelector('[data-next-session-section="ask"]');
  return {
    attrs: [
      article.getAttribute('data-next-session-detail'),
      article.getAttribute('data-next-session-state'),
      article.getAttribute('data-tone'),
      article.classList.contains('next-session-detail--blocked'),
    ],
    header: norm(header),
    headerLinks: [...header.querySelectorAll('a')].map((a) => a.getAttribute('href')),
    headerButtons: [...header.querySelectorAll('button:not([data-slot=popover-trigger])')].map(
      (button) => button.getAttribute('aria-label'),
    ),
    // The age after "ASKED YOU" is the wait between the board and the draw, a second more or less from run to run.
    ask: ask ? norm(ask).replace(/(ASKED YOU · )\d+[smhd]/, '$1Ns') : null,
    answers: [...clone.querySelectorAll('[data-next-answer]')].map(
      (button) =>
        // The ask id is minted per run, so it is not part of what is recorded; the answer step holds the id to the board's.
        `ask#${button.getAttribute('data-next-answer-index')}:${norm(button)}`,
    ),
    parts,
    footer: norm(clone.querySelector('.next-session-footer')),
  };
};

/* ---- pages ---- */
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
  await opened.page.waitForTimeout(patience(120));
}

/* One payload for the page, so it has one clock: every read of /api/data answers it, and the stream is
   refused so nothing else moves. */
async function freeze(opened, holder) {
  await opened.page.route('**/api/data*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'X-Compass-Revision': '7.1' },
      body: JSON.stringify(holder.body),
    }),
  );
  await opened.page.route('**/api/stream', (route) => route.abort('failed'));
}

const sessionFragment = (row) =>
  `#n=session:${E(row.project ?? '')}:${E(row.harness)}:${E(row.sid)}`;
const routable = (row) =>
  row &&
  typeof row === 'object' &&
  typeof row.harness === 'string' &&
  row.harness &&
  typeof row.sid === 'string' &&
  row.sid;

/* A recorded page says how long ago a session was active, counted from when the board was recorded; this run counts
   from its own start, so a sub-minute age is two seconds either way on a loaded runner (10s against 12s failed the
   Windows leg). Only that seconds count is set aside: a minute or hour age, the words around it and everything
   else still compare exactly. */
const seconds = (value) => JSON.stringify(value)?.replace(/\d+s ago/g, 'Ns ago');

function firstDifference(left, right, path = '$') {
  if (seconds(left) === seconds(right)) return null;
  if (left && right && typeof left === 'object' && typeof right === 'object') {
    for (const key of new Set([...Object.keys(left), ...Object.keys(right)])) {
      const found = firstDifference(left[key], right[key], `${path}.${key}`);
      if (found) return found;
    }
  }
  return `${path}: ${JSON.stringify(left)?.slice(0, 220)} != ${JSON.stringify(right)?.slice(0, 220)}`;
}

/* A difference found by the comparison is a failure unless it is named here with its reason. */
const DEVIATIONS = [
  {
    scope: 'Sessions header',
    reason:
      'DEC-27 moves the two explanations into the shared how-to and request/block counters to Attention; goal links include saved words.',
  },
  {
    scope: 'assignment',
    reason: 'Current task names the instruction without borrowing the session goal label.',
  },
];

const browser = await chromium.launch();
let holder;
const golden = sessionDeviations('sessions-parity', () => holder?.body || {});
const board = await startSessionsBoard();
const reactOrigins = [board.react.origin, board.react.viteOrigin];
const shots = [];
const opened = [];
async function newPage(options = {}) {
  const page = await openPage(browser, reactOrigins, options);
  await recordClipboard(page.context);
  await instrumentResources(page.context);
  opened.push(page);
  return page;
}

try {
  await mkdir(SHOTS, { recursive: true });
  const react = await newPage();
  const real = await (await fetch(board.react.origin + '/api/data')).json();
  holder = { body: real };
  await freeze(react, holder);

  await step('orientation: annotations off, unreadable store and providerless board', async () => {
    const o = await newPage();
    const states = [
      { annotate: false, reading_routes: { claude: { provider: 'claude' } } },
      {
        annotate: true,
        annotate_unreadable: 'Store unreadable',
        reading_routes: { claude: { provider: 'claude' } },
      },
      { annotate: true, reading_routes: { claude: { provider: '' } } },
    ];
    const fixture = { body: {} };
    await freeze(o, fixture);
    try {
      for (const state of states) {
        fixture.body = { ...real, ...state };
        await load(o, board.react.origin, '#n=sessions');
        assert.equal(
          await o.page.locator('[data-next-sessions-orientation]').textContent(),
          'Open a session to see what it is doing and where it stands.',
        );
        assert.equal(await o.page.locator('.next-operations-header > p').count(), 1);
        assert.equal(
          await o.page.getByRole('button', { name: 'How Intent and drift works' }).count(),
          1,
        );
      }
    } finally {
      await o.close();
    }
  });

  await step('first step: four goal links need one click and land focus on Intent', async () => {
    const fixtures = [
      {
        harness: 'claude',
        sid: 'active-draft',
        state: 'working',
        first_prompt: 'Draft active task',
        first_prompt_at: 100,
      },
      {
        harness: 'claude',
        sid: 'recent-draft',
        state: 'idle',
        first_prompt: 'Draft recent task',
        first_prompt_at: 100,
      },
      {
        harness: 'claude',
        sid: 'active-typed',
        state: 'working',
        annotation_goal: 'Saved active task',
        annotation_revision: 1,
      },
      {
        harness: 'claude',
        sid: 'recent-typed',
        state: 'idle',
        annotation_goal: 'Saved recent task',
        annotation_revision: 1,
      },
    ].map((row) => ({ ...row, project: 'first/step' }));
    const o = await newPage();
    const state = {
      body: {
        ...real,
        annotate: true,
        annotate_unreadable: '',
        reading_routes: { claude: { provider: 'claude' } },
        sessions: fixtures,
      },
    };
    await freeze(o, state);
    const clicks = [];
    try {
      for (const [index, row] of fixtures.entries()) {
        state.body = {
          ...state.body,
          sessions: fixtures.map((item) => ({ ...item, departure_checked: index % 2 === 1 })),
        };
        await load(o, board.react.origin, '#n=sessions');
        assert.equal(
          await o.page.locator('[data-next-sessions-orientation]').textContent(),
          'Open a session, set its goal and press Analyze drift to see how far it moved from it.' +
            (index % 2 === 0
              ? ' No session has been checked for drift yet; open one to check it.'
              : ''),
        );
        assert.equal(
          await o.page.getByRole('button', { name: 'How Intent and drift works' }).count(),
          1,
        );
        assert.equal(
          await o.page.locator('.next-operations-header [data-slot=accordion-trigger]').count(),
          0,
        );
        assert.equal(await o.page.locator('[data-next-fleet-fact]').count(), 2);
        await o.page.evaluate(() => {
          globalThis.__goalClicks = 0;
          document.addEventListener('click', (event) => {
            if (event.target.closest('[data-next-goal-focus]')) globalThis.__goalClicks += 1;
          });
        });
        await o.page
          .locator(`article[data-next-session="${row.sid}"] [data-next-goal-focus]`)
          .click();
        await o.page.waitForFunction(
          ({ typed, sid }) =>
            typed
              ? document.activeElement?.getAttribute('data-next-focus') ===
                `held:claude:${sid}:goal`
              : document.activeElement?.id === 'next-session-intent-heading',
          { typed: Boolean(row.annotation_goal), sid: row.sid },
        );
        assert.equal(await o.page.evaluate(() => globalThis.__goalClicks), 1);
        clicks.push({ sid: row.sid, clicks: 1 });
      }
      return clicks;
    } finally {
      await o.close();
    }
  });

  /* ===================== DIFFERENTIAL: the real board ===================== */
  await step(
    'differential: the real board reads as the recording does, group by group and row by row',
    async () => {
      const old = golden.observe('real board: list');
      await load(react, board.react.origin, '#n=sessions');
      const mine = await react.page.evaluate(summarizeList);
      assert.ok(
        old.groups?.length === 2 && mine.groups?.length === 2,
        'the page and the recording draw both groups',
      );
      const rowCount = mine.groups.reduce((sum, group) => sum + group.rows.length, 0);
      assert.ok(rowCount >= 12, `the real board carries its sessions (${rowCount})`);
      assert.equal(firstDifference(old, mine), null);
      return {
        rows: rowCount,
        active: mine.groups[0].rows.map((row) => `${row.harness}/${row.sid}`),
        history: mine.groups[1].rows.length,
      };
    },
  );

  await step(
    'differential: every session of the real board has the recorded page, reached by its one-step link',
    async () => {
      const rows = real.sessions.filter(routable);
      const compared = [];
      for (const row of rows) {
        const fragment = sessionFragment(row);
        const old = golden.observe(`real board: page ${row.harness}/${row.sid}`);
        await load(react, board.react.origin, fragment);
        const mine = await react.page.evaluate(summarizeDetail);
        const found = firstDifference(old, mine);
        assert.equal(found, null, `${row.harness}/${row.sid}: ${found}`);
        compared.push(`${row.harness}/${row.sid}`);
      }
      return { compared: compared.length };
    },
  );

  await step(
    'differential: a row’s link opens its exact session, with the origin stamped, as recorded',
    async () => {
      const open = async (origin, opened_) => {
        await load(opened_, origin, '#n=sessions');
        const link = opened_.page.locator(
          'article[data-slot="card"][data-variant="session-row"][data-next-harness="codex"][data-next-session="colon:sid"] a.next-operation-route',
        );
        await link.click();
        await opened_.page.waitForFunction(() => globalThis.location.hash.includes('session:'));
        return opened_.page.evaluate(() => globalThis.location.hash);
      };
      const hashes = {
        recorded: golden.observe('row link hash'),
        react: await open(board.react.origin, react),
      };
      assert.equal(hashes.react, hashes.recorded);
      assert.equal(
        hashes.react,
        `#n=session:${E('beta/api')}:codex:${E('colon:sid')}&from=sessions`,
      );
      return hashes.react;
    },
  );

  /* ===================== DIFFERENTIAL: generated payloads ===================== */
  await step(
    `differential: ${SEEDS} generated payloads read as recorded, lists and pages`,
    async () => {
      let lists = 0;
      let pages = 0;
      for (let seed = 1; seed <= SEEDS; seed += 1) {
        holder.body = genPayload(seed, { wellFormed: true });
        const input = digest(holder.body);
        const old = golden.observe(`generated seed ${seed} ${input}: list`);
        await load(react, board.react.origin, '#n=sessions');
        const mine = await react.page.evaluate(summarizeList);
        const found = firstDifference(old, mine);
        if (found && !DEVIATIONS.some((d) => d.seed === seed && d.scope === 'list'))
          assert.fail(`seed ${seed} list: ${found}`);
        lists += 1;
        const rows = (Array.isArray(holder.body.sessions) ? holder.body.sessions : [])
          .filter(routable)
          .slice(0, 2);
        for (const [index, row] of rows.entries()) {
          const fragment = sessionFragment(row);
          const oldPage = golden.observe(
            `generated seed ${seed} ${input}: page ${index} ${row.harness}/${row.sid}`,
          );
          await load(react, board.react.origin, fragment);
          const minePage = await react.page.evaluate(summarizeDetail);
          const detail = firstDifference(oldPage, minePage);
          if (detail && !DEVIATIONS.some((d) => d.seed === seed && d.scope === 'detail'))
            assert.fail(`seed ${seed} ${row.harness}/${row.sid}: ${detail}`);
          pages += 1;
        }
      }
      holder.body = real;
      return { lists, pages };
    },
  );

  await step(
    'differential: hostile text is text, as recorded, and draws no element, selector or script',
    async () => {
      // A NUL is left out of the comparison on purpose: the previous interface built HTML text, whose parser turns it into
      // U+FFFD, where this page sets the attribute and keeps the exact identity. Checked on its own below.
      const hostile = [
        '"]\'><img src=x onerror=globalThis.__hit=1>',
        '<script>globalThis.__hit=1</script>',
        '`${1+1}`',
        '\u202eRTL',
      ];
      const body = {
        generated: real.generated,
        sessions: hostile.map((text, index) => ({
          harness: 'claude',
          sid: `s${index}:${text}`,
          project: text,
          title: text,
          state: 'working',
          active: true,
          last_prompt: text,
          state_detail: text,
        })),
      };
      holder.body = body;
      const old = golden.observe('hostile text: list');
      await load(react, board.react.origin, '#n=sessions');
      const mine = await react.page.evaluate(summarizeList);
      assert.equal(firstDifference(old, mine), null);
      assert.equal(await react.page.evaluate(() => globalThis.__hit), undefined, 'no handler ran');
      assert.equal(
        await react.page.locator('main img, main script').count(),
        0,
        'no element was injected',
      );
      const first = body.sessions[0];
      await load(react, board.react.origin, sessionFragment(first));
      assert.ok(
        await react.page.locator('article.next-session-detail').count(),
        'a session with hostile characters in its id still opens',
      );
      holder.body = {
        generated: real.generated,
        sessions: [
          { harness: 'claude', sid: 'a\u0000b', project: 'p', title: 'NUL', state: 'idle' },
        ],
      };
      await load(react, board.react.origin, '#n=sessions');
      assert.equal(
        await react.page
          .locator('article[data-slot="card"][data-variant="session-row"]')
          .first()
          .getAttribute('data-next-session'),
        'a\u0000b',
        'the identity is kept exactly',
      );
      holder.body = real;
    },
  );

  /* ===================== BEHAVIOUR: resources and StrictMode ===================== */
  await step(
    'resources: a page load opens one stream and reads once, under StrictMode, and navigation adds nothing',
    async () => {
      const live = await newPage();
      try {
        await live.page.goto(board.react.origin + '/#n=sessions');
        await reactReady(live.page);
        await live.page.waitForTimeout(patience(500));
        const first = { counts: live.counts(), res: await resources(live.page) };
        // The boot read, plus the stream's first announcement when it lands inside the wait: both are the page's own.
        assert.ok(
          first.counts.data >= 1 && first.counts.data <= 2,
          `boot read, saw ${first.counts.data}`,
        );
        assert.equal(first.counts.stream, 1, 'one stream');
        assert.equal(first.counts.nonGet, 0, 'nothing but reads');
        assert.deepEqual(
          [first.res.opened, first.res.closed, first.res.sources],
          [1, 0, 1],
          'one EventSource opened, none closed',
        );
        for (let round = 0; round < 6; round += 1) {
          await live.page
            .locator('article[data-slot="card"][data-variant="session-row"] a.next-operation-route')
            .first()
            .click();
          await live.page.waitForSelector('article.next-session-detail');
          await live.page.goBack();
          await live.page.waitForSelector('[data-next-view-body="sessions"]');
        }
        await live.page.waitForTimeout(patience(400));
        const after = { counts: live.counts(), res: await resources(live.page) };
        assert.equal(after.counts.stream, 1, 'navigation opened no second stream');
        // Twelve view changes that each read would add twelve; the board's wall-clock revision can add a follow-up
        // read per tick on a slow runner, so the bound sits below twelve with room for that.
        assert.ok(
          after.counts.data <= first.counts.data + 7,
          `navigation read ${after.counts.data - first.counts.data} more times`,
        );
        assert.equal(after.counts.nonGet, 0);
        assert.deepEqual([after.res.opened, after.res.closed, after.res.sources], [1, 0, 1]);
        assert.ok(
          after.res.intervals <= first.res.intervals,
          `intervals settled (${first.res.intervals} -> ${after.res.intervals})`,
        );
        assert.deepEqual(live.log.consoleErrors, []);
        assert.deepEqual(live.log.pageErrors, []);
        assert.deepEqual(live.log.externalRequests, []);
        return {
          first: { ...first.counts, ...first.res },
          after: { ...after.counts, ...after.res },
        };
      } finally {
        await live.close();
      }
    },
  );

  await step(
    'pending answer: click, Enter and Space send one request and keep focus and width',
    async () => {
      const live = await newPage();
      let release;
      try {
        const gate = real.sessions.find((row) => row.sid === 'gate-open');
        await live.page.goto(board.react.origin + '/' + sessionFragment(gate));
        await reactReady(live.page);
        const answer = live.page.locator('[data-next-answer-index="0"]');
        const before = await answer.boundingBox();
        const held = new Promise((resolve) => {
          release = resolve;
        });
        await live.page.route('**/api/answer', async (route) => {
          await held;
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ answered: false }),
          });
        });
        await answer.click();
        await live.page.locator('[data-next-answer][aria-busy="true"]').waitFor();
        // dispatchEvent reaches the control even though automation regards aria-disabled as unclickable.
        await answer.dispatchEvent('click');
        await live.page.keyboard.press('Enter');
        await live.page.keyboard.press('Space');
        assert.equal(await answer.getAttribute('aria-disabled'), 'true');
        assert.equal(await answer.getAttribute('disabled'), null);
        assert.equal(await answer.evaluate((el) => document.activeElement === el), true);
        const after = await answer.boundingBox();
        assert.equal(after.width, before.width);
        assert.equal(after.height, before.height);
        assert.equal(live.log.nonGet.filter((request) => request.path === '/api/answer').length, 1);
        release();
        await live.page
          .locator('[data-next-answer][aria-busy="true"]')
          .waitFor({ state: 'detached' });
        return { requests: 1, width: after.width, height: after.height };
      } finally {
        release?.();
        await live.close();
      }
    },
  );

  /* ===================== BEHAVIOUR: answering a held request ===================== */
  await step(
    'answer: one numeric index goes to the real route by keyboard, the request leaves the board, and no model is called',
    async () => {
      const live = await newPage();
      try {
        const gate = real.sessions.find((row) => row.sid === 'gate-open');
        await live.page.goto(board.react.origin + '/' + sessionFragment(gate));
        await reactReady(live.page);
        await live.page.waitForSelector('[data-next-answer]');
        const options = await live.page.locator('[data-next-answer]').allInnerTexts();
        assert.deepEqual(
          options,
          ['Yes, run it', 'No, stop', 'Ask me later'],
          'every option, in order',
        );
        assert.equal(live.counts().nonGet, 0, 'nothing posted before a press');
        await live.page.locator('[data-next-answer-index="1"]').focus();
        const posted = live.page.waitForRequest((request) => request.url().endsWith('/api/answer'));
        await live.page.keyboard.press('Enter');
        const request = await posted;
        const body = JSON.parse(request.postData());
        assert.deepEqual(Object.keys(body).sort(), ['id', 'index']);
        assert.equal(body.index, 1);
        assert.equal(typeof body.index, 'number');
        assert.equal(body.id, real.asks.find((ask) => ask.session_id === 'gate-open').id);
        await live.page.waitForSelector('[data-next-session-ask]', {
          state: 'detached',
          timeout: 8000,
        });
        const after = await live.page.locator('article.next-session-detail').innerText();
        assert.ok(!after.includes('ASKED YOU'), 'the question left with the next board');
        assert.deepEqual(
          live.log.nonGet,
          [{ method: 'POST', path: '/api/answer' }],
          'one answer and nothing else',
        );
        return { index: body.index, sent: Object.keys(body) };
      } finally {
        await live.close();
      }
    },
  );

  await step(
    'answer: a card another tab already answered says no confirmation came back, and keeps the question',
    async () => {
      const live = await newPage();
      try {
        const asked = real.sessions.find((row) => row.sid === 'spacedock-asked');
        const ask = real.asks.find((item) => item.session_id === 'spacedock-asked');
        await live.page.goto(board.react.origin + '/' + sessionFragment(asked));
        await reactReady(live.page);
        await live.page.waitForSelector('[data-next-answer]');
        // The answer another tab gave, straight to the route.
        const other = await fetch(board.react.origin + '/api/answer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: ask.id, index: 0 }),
        });
        assert.equal((await other.json()).answered, true);
        // This tab still holds the card: the stream is refused for it so it cannot learn otherwise before the press.
        await live.page.route('**/api/data*', (route) => route.abort('failed'));
        await live.page.locator('[data-next-answer-index="1"]').click();
        await live.page.waitForSelector('[data-slot=alert][data-variant=answer-failure]');
        assert.equal(
          await live.page
            .locator('[data-slot=alert][data-variant=answer-failure]')
            .getAttribute('role'),
          'status',
          'the failure stays polite',
        );
        assert.equal(
          await live.page.locator('[data-slot=alert][data-variant=answer-failure]').innerText(),
          'no confirmation came back — it may already have been answered',
        );
        assert.ok(
          await live.page.locator('[data-next-session-ask]').count(),
          'the question stays until the board says otherwise',
        );
        assert.equal(
          await live.page.locator('[data-next-pending]').count(),
          0,
          'the control is no longer busy',
        );
      } finally {
        await live.close();
      }
    },
  );

  /* ===================== BEHAVIOUR: a redraw leaves the reader's place alone ===================== */
  async function clocked(fragment) {
    const o = await newPage();
    const state = { body: real };
    await o.page.clock.install({ time: Date.now() });
    await o.page.route('**/api/data*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'X-Compass-Revision': '7.1' },
        body: JSON.stringify(state.body),
      }),
    );
    await o.page.route('**/api/stream', (route) => route.abort('failed'));
    await o.page.goto(board.react.origin + '/' + fragment);
    await reactReady(o.page);
    await o.page.waitForTimeout(patience(300));
    o.state = state;
    o.poll = async () => {
      await o.page.clock.fastForward(20_000);
      await o.page.waitForTimeout(patience(300));
    };
    return o;
  }

  await step(
    'continuity: nodes, an open caveat, focus and scroll survive a poll that changes the rows',
    async () => {
      const o = await clocked('#n=sessions');
      try {
        await o.page.addStyleTag({ content: '#app{min-height:3200px}' });
        await o.page.getByRole('button', { name: 'How Intent and drift works' }).click();
        await o.page.evaluate(() => {
          const row = globalThis.document.querySelector('article[data-next-session="live-work"]');
          row.__mark = 'kept';
          const link = globalThis.document.querySelector(
            'article[data-next-session="live-work"] a.next-operation-route',
          );
          link.focus();
          globalThis.scrollTo(0, 420);
          globalThis.__linkTop = Math.round(link.getBoundingClientRect().top);
        });
        o.state.body = {
          ...real,
          generated: real.generated + 25,
          sessions: real.sessions.map((row) =>
            row.sid === 'live-work'
              ? { ...row, tasks: [{ id: '2', subject: 'A different step', status: 'in_progress' }] }
              : row,
          ),
        };
        await o.poll();
        const kept = await o.page.evaluate(() => ({
          mark: globalThis.document.querySelector('article[data-next-session="live-work"]').__mark,
          focus: globalThis.document.activeElement?.closest('article')?.dataset.nextSession,
          linkTop: Math.round(
            globalThis.document
              .querySelector('article[data-next-session="live-work"] a.next-operation-route')
              .getBoundingClientRect().top,
          ),
          before: globalThis.__linkTop,
          open: [
            ...globalThis.document.querySelectorAll(
              '[data-slot=popover-trigger][aria-expanded=true],details[open] > summary,[data-slot=accordion][data-open] [data-slot=accordion-trigger]',
            ),
          ].map((summary) => summary.textContent),
          text: globalThis.document
            .querySelector('article[data-next-session="live-work"]')
            .textContent.includes('A different step'),
        }));
        assert.equal(kept.text, true, 'the change reached the row');
        assert.equal(kept.mark, 'kept', 'the row node was updated, not replaced');
        assert.equal(kept.focus, 'live-work', 'focus stayed on the link');
        // The browser's own scroll anchoring may move the scroll offset to keep what the reader is looking at where it
        // was when a row above it changes height; what must hold is that the focused link did not move on screen.
        // Rounded from fractional positions, so scroll anchoring can leave the link one pixel off (a hosted runner
        // measured 712 against 711); a reader who scrolled to follow it would be several rows away.
        assert.ok(
          Math.abs(kept.linkTop - kept.before) <= 1,
          `the focused link stayed where it was on screen: ${kept.linkTop} against ${kept.before}`,
        );
        assert.deepEqual(kept.open, [], 'the how-to closes when focus leaves for the row link');
        return kept;
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'continuity: an open popover caveat stays open across a poll, and closes on Escape and on focus leaving',
    async () => {
      const o = await clocked('#n=sessions');
      try {
        await o.page.getByText('What recent means').click();
        const open = () =>
          o.page.evaluate(() =>
            [
              ...globalThis.document.querySelectorAll(
                '[data-slot=popover-trigger][aria-expanded=true],details[open] > summary,[data-slot=accordion][data-open] [data-slot=accordion-trigger]',
              ),
            ].map((summary) => summary.textContent),
          );
        assert.deepEqual(await open(), ['What recent means']);
        o.state.body = { ...real, generated: real.generated + 25 };
        await o.poll();
        assert.deepEqual(await open(), ['What recent means'], 'a poll did not close it');
        await o.page.keyboard.press('Escape');
        assert.deepEqual(await open(), [], 'Escape closed it');
        await o.page.getByText('What recent means').click();
        await o.page
          .locator('article[data-slot="card"][data-variant="session-row"] a.next-operation-route')
          .first()
          .focus();
        assert.deepEqual(await open(), [], 'focus leaving closed it');
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'continuity: a selection inside a row, and a session page’s open facts disclosure, survive a poll',
    async () => {
      const o = await clocked(`#n=session:${E('alpha/app')}:claude:live-work`);
      try {
        await o.page
          .locator('[data-slot=accordion].next-session-facts-more [data-slot=accordion-trigger]')
          .click();
        await o.page.evaluate(() => {
          const range = globalThis.document.createRange();
          const target = globalThis.document.querySelector(
            '[data-slot=card][data-variant=session-current] > strong',
          );
          range.selectNodeContents(target);
          const selection = globalThis.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          globalThis.__selected = selection.toString();
        });
        o.state.body = { ...real, generated: real.generated + 25 };
        await o.poll();
        const after = await o.page.evaluate(() => ({
          selected: globalThis.getSelection().toString(),
          open: globalThis.document
            .querySelector('[data-slot=accordion].next-session-facts-more')
            .hasAttribute('data-open'),
          before: globalThis.__selected,
        }));
        assert.equal(after.open, true, 'the facts disclosure stayed open');
        // An unrelated update keeps the node whose text did not change, so the selection holds. Where the text
        // itself changed the selection is the reader's to lose, and the receipt says which it was.
        return { selectionHeld: after.selected === after.before };
      } finally {
        await o.close();
      }
    },
  );

  /* ===================== BEHAVIOUR: keyboard ===================== */
  await step(
    'keyboard: Tab reaches a row’s link, Enter opens the session, Escape returns, as recorded',
    async () => {
      const walk = async (name, origin, opened_) => {
        await load(opened_, origin, '#n=sessions');
        await opened_.page.evaluate(() => {
          globalThis.document.activeElement?.blur();
        });
        let stops = 0;
        for (; stops < 40; stops += 1) {
          await opened_.page.keyboard.press('Tab');
          const onRoute = await opened_.page.evaluate(
            () => globalThis.document.activeElement?.matches('a.next-operation-route') === true,
          );
          if (onRoute) break;
        }
        assert.ok(stops < 40, `${name}: a row link is reachable by Tab`);
        await opened_.page.keyboard.press('Enter');
        await opened_.page.waitForFunction(() => globalThis.location.hash.includes('session:'));
        const opens = await opened_.page.evaluate(() => globalThis.location.hash);
        await opened_.page.keyboard.press('Escape');
        await opened_.page.waitForFunction(() => !globalThis.location.hash.includes('session:'));
        return {
          opens,
          returns: await opened_.page.evaluate(() => globalThis.location.hash),
        };
      };
      const results = {
        recorded: golden.observe('keyboard: open and return'),
        react: await walk('react', board.react.origin, react),
      };
      assert.deepEqual(results.react, results.recorded);
      return results.react;
    },
  );

  await step(
    'keyboard: a caveat opens and closes with Enter and Space, and the page reports its state',
    async () => {
      await load(react, board.react.origin, '#n=sessions');
      const summary = react.page.getByRole('button', { name: 'How Intent and drift works' });
      await summary.focus();
      await react.page.keyboard.press('Enter');
      assert.equal(
        await react.page.evaluate(
          () => globalThis.document.activeElement.getAttribute('aria-expanded') === 'true',
        ),
        true,
      );
      await react.page.keyboard.press('Space');
      assert.equal(
        await react.page.evaluate(
          () => globalThis.document.activeElement.getAttribute('aria-expanded') === 'true',
        ),
        false,
      );
    },
  );

  /* ===================== BEHAVIOUR: layout ===================== */
  const SHAPES = [
    { width: 320, height: 800, name: '320' },
    { width: 375, height: 800, name: '375' },
    { width: 640, height: 800, name: '640', zoom: true },
    { width: 1280, height: 900, name: '1280' },
  ];
  const overflow = (page) =>
    page.evaluate(() => ({
      scroll: globalThis.document.documentElement.scrollWidth,
      client: globalThis.document.documentElement.clientWidth,
      wide: [...globalThis.document.querySelectorAll('main *')]
        .filter(
          (node) =>
            node.getBoundingClientRect().right >
              globalThis.document.documentElement.clientWidth + 1 &&
            globalThis.getComputedStyle(node).position !== 'absolute',
        )
        .slice(0, 4)
        .map((node) => `${node.tagName}.${node.className}`),
    }));

  await step(
    'layout: the screen and four session pages wrap at 320, 375, 200% zoom and 1280 with no horizontal page scroll',
    async () => {
      const report = {};
      const fragments = {
        list: '#n=sessions',
        'live work': sessionFragment(real.sessions.find((row) => row.sid === 'live-work')),
        'held request': sessionFragment(real.sessions.find((row) => row.sid === 'gate-open')),
        'long turn': sessionFragment(real.sessions.find((row) => row.sid === 'long-turn')),
        delegated: sessionFragment(real.sessions.find((row) => row.sid === 'delegated')),
      };
      const wide = [];
      for (const shape of SHAPES) {
        const context = { viewport: { width: shape.width, height: shape.height } };
        const o = await newPage(context);
        await freeze(o, holder);
        try {
          for (const [label, fragment] of Object.entries(fragments)) {
            await load(o, board.react.origin, fragment);
            const measured = await overflow(o.page);
            const height = await o.page.evaluate(
              () => globalThis.document.documentElement.scrollHeight,
            );
            report[`${shape.name} ${label} react`] = { ...measured, height };
            if (measured.scroll > measured.client)
              wide.push(`${shape.name} ${label}: ${JSON.stringify(measured)}`);
          }
          await load(o, board.react.origin, '#n=sessions');
          const name = `sessions-react-${shape.name}.png`;
          await o.page.screenshot({ path: SHOTS + name, fullPage: false });
          shots.push(name);
          if (shape.name === '375' || shape.name === '1280') {
            await load(o, board.react.origin, fragments['held request']);
            const detail = `session-detail-react-${shape.name}.png`;
            await o.page.screenshot({
              path: SHOTS + detail,
              fullPage: shape.name === '375',
            });
            shots.push(detail);
          }
        } finally {
          await o.close();
        }
      }
      assert.deepEqual(wide, [], 'horizontal page overflow on the React page: ' + wide.join(' | '));
      return report;
    },
  );

  await step(
    'layout: the React screen is not taller than the recorded one by more than a wrapped line per row',
    async () => {
      const height = async (opened_, origin) => {
        await load(opened_, origin, '#n=sessions');
        return opened_.page.evaluate(() => globalThis.document.documentElement.scrollHeight);
      };
      const heights = {
        recorded: golden.observe('layout: list height'),
        react: await height(react, board.react.origin),
      };
      // The recorded height is from macOS; the page is as tall as its wrapped text, so the typeface moves it.
      // Measured: recorded 3227 against React 3262 on macOS (+1.1%) and 3297 on Linux with Liberation fonts (+2.2%), so the
      // operating system moves the ratio by about one point of the twelve allowed.
      assert.ok(
        Math.abs(heights.react - heights.recorded) <= 0.12 * heights.recorded,
        JSON.stringify(heights),
      );
      return heights;
    },
  );

  await step('motion: a running worker’s dot pulses, and stops under reduced motion', async () => {
    const animation = async (reducedMotion) => {
      const o = await newPage({ reducedMotion });
      try {
        await o.page.goto(
          board.react.origin +
            '/' +
            sessionFragment(real.sessions.find((row) => row.sid === 'live-work')),
        );
        await reactReady(o.page);
        await o.page.waitForSelector('.next-session-subagent.next-live');
        return await o.page.evaluate(
          () =>
            globalThis.globalThis.getComputedStyle(
              globalThis.document.querySelector(
                '.next-session-subagent.next-live .next-status-dot',
              ),
            ).animationName,
        );
      } finally {
        await o.close();
      }
    };
    const [on, off] = [await animation('no-preference'), await animation('reduce')];
    assert.notEqual(on, 'none');
    assert.equal(off, 'none');
  });

  await step(
    'session copy controls are absent on rows and detail, including departures',
    async () => {
      const o = await clocked('#n=sessions');
      try {
        assert.equal(await o.page.locator('.next-operation-row [data-copy-kind]').count(), 0);
        for (const row of real.sessions.filter(routable)) {
          await load(o, board.react.origin, sessionFragment(row));
          assert.equal(await o.page.locator('.next-session-detail [data-copy-kind]').count(), 0);
        }
        await load(o, board.react.origin, '#n=attention');
        assert.ok(
          (await o.page.locator('.next-attention [data-copy-kind=command]').count()) > 0,
          'Attention lost resume commands',
        );
        await load(o, board.react.origin, '#n=project:alpha%2Fapp');
        assert.ok(
          (await o.page.locator('.next-cockpit-waiting [data-copy-kind=command]').count()) > 0,
          'project rail lost resume commands',
        );
        await o.page.getByRole('tab', { name: /^Console/ }).click();
        await o.page.waitForSelector('.next-rail-wait [data-copy-kind=command]');
        assert.ok(
          (await o.page.locator('.next-rail-wait [data-copy-kind=command]').count()) > 0,
          'waiting panel lost resume commands',
        );
        assert.deepEqual(await o.page.evaluate(() => globalThis.__copied), []);
      } finally {
        await o.close();
      }
    },
  );

  for (const page of opened) {
    // Every page this run opened stayed inside the board's own origins.
    if (page.log.externalRequests.length)
      failures.push({ name: 'externals', message: JSON.stringify(page.log.externalRequests) });
  }
} finally {
  for (const page of opened) await page.close().catch(() => undefined);
  await browser.close();
  await board.close();
}

golden.finish({ complete: !only && failures.length === 0 });

console.log(
  JSON.stringify({ sessions: receipts, deviations: DEVIATIONS, screenshots: shots }, null, 2),
);
if (failures.length) {
  console.error(JSON.stringify({ failures }, null, 2));
  process.exitCode = 1;
}
