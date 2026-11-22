/*
 * The Projects list and a project's page in a real browser, against the real backend (DRC-4826).
 *
 * Two kinds of proof. The DIFFERENTIAL half drives the React page over a board and compares what a reader can read
 * with what the previous interface showed for it: the Projects list group by group and row by row, then each
 * project's header, scope tree, recovery strip, tab strip and its Now and Course panels, for the proof board
 * (several projects, a plan, the same sid under two harnesses, a session that ended without an end stamp, a
 * source gap, a project with no plan or context, a unicode label, a label that differs by a space), for the
 * states that need a different board (no sessions, no plans, a session the board no longer holds, a context that
 * failed) and for a run of generated boards. The BEHAVIOUR half holds the React page to what a text comparison
 * cannot see: nothing posts, copies or notifies on mount, StrictMode, a poll or navigation; the workstream
 * collapse survives a reload and a refusing store; a human-context note keeps its node, caret and native undo
 * through the board's own revisions and through tab changes; a scope survives leaving the project and coming
 * back; an open plan survives a poll; and 320, 375 and 640 CSS px layouts do not scroll sideways.
 *
 * What the previous interface said is a RECORDING (`support/golden.mjs`, `frontend/test/golden/e2e/project-parity.json`)
 * that cannot be remade because that interface is gone. A recorded reading is keyed by the step, the fragment and
 * a digest of the board and contexts served, so a changed generator or fixture fails as "no golden" instead of
 * comparing nothing. Every browser here runs in UTC, because the pages print clock times in the local zone and a
 * recording must read the same on any machine. Dropped with the interface, because nothing asserted against them:
 * its screenshots.
 *
 * Models, usage, notifications and the terminal are off or replaced: the page's clipboard is a recorder, the
 * backend serving the page answers only the document and its health, and every board and project-context read
 * is the one this script serves. The Decisions and Console tabs and the steering bar belong to the steering step
 * and are outside the comparison. Run with `pnpm test:project:browser`; `COMPASS_E2E_STEPS=<regex>` runs only
 * the steps whose name matches, `PROJECT_E2E_SEEDS` sets how many generated boards the differential compares.
 *
 * Timing: every fixed wait here means "give the page time to react", and a hosted runner has a few shared cores,
 * so each is tripled under CI and every comparison reads until two reads agree (`settled`) rather than once.
 */
import {
  projectWordDeviation,
  projectGlossEnabled,
  projectInstructionHeading,
} from '../test/projectWordDeviation.ts';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { createHash } from 'node:crypto';
import { openPage } from './support/browser.mjs';
import { goldenFor, jsonSafe, normalise } from './support/golden.mjs';
import { recordedLocationNotes } from './support/location-deviations.mjs';
import { recordedName } from '../test/recorded-name.ts';
import {
  instrumentResources,
  recordClipboard,
  resources,
  startSessionsBoard,
} from './sessions-board.mjs';

const patience = (ms) => (process.env.CI ? ms * 3 : ms);
const golden = goldenFor('project-parity');
/* The React reading in the stable form a recorded observation has, so the two compare as plain data. */
const norm = (value) => jsonSafe(normalise(value));
// The key that undoes in a text box: Command on macOS, Control elsewhere.
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';

// The generators are TypeScript the unit tests also use; Node 26 strips the types as it imports them.
process.removeAllListeners('warning');
const base = await import('../src/observed/generate.test.helper.ts');
const { makeBoards } = await import('../test/project_boards.ts');
const { genBoard, genContext, parityBoard } = makeBoards(base);

// A proof belongs to its worktree; sibling captures must not overwrite one another.
const checkout = fileURLToPath(new URL('../../', import.meta.url));
const SHOTS = (process.env.COMPASS_SCREENSHOTS || `${checkout}docs/screenshots`).replace(
  /\/?$/,
  '/',
);
const SEEDS = Number(process.env.PROJECT_E2E_SEEDS || 12);
const E = encodeURIComponent;
const receipts = {};
const failures = [];
const shots = [];
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
  const norm = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : '');
  const { document } = globalThis;
  const root = document.querySelector('[data-next-view-body="projects"]')?.cloneNode(true);
  if (!root) return { missing: true, text: norm(document.body).slice(0, 200) };
  root.querySelectorAll('.next-project-session-limit').forEach((node) => node.remove());
  for (const activity of root.querySelectorAll('.next-project-session-now')) {
    if (activity.textContent === 'No recent activity') activity.textContent = 'quiet';
  }
  return {
    note: norm(root.querySelector('.next-projects-note')),
    groups: [...root.querySelectorAll('[data-next-project-group]')].map((group) => ({
      kind: group.getAttribute('data-next-project-group'),
      header: norm(group.querySelector(':scope > header')),
      empty: group.querySelector('.next-projects-empty')
        ? norm(group.querySelector('.next-projects-empty'))
        : null,
      rows: [...group.querySelectorAll('article.next-project-row')].map((row) => ({
        project: row.getAttribute('data-next-project'),
        route: row.getAttribute('data-next-route'),
        tone: [...row.classList].find((name) => name.startsWith('next-project-tone--')) || '',
        history: row.getAttribute('data-next-project-history') === 'true',
        role: row.getAttribute('role'),
        tabindex: row.getAttribute('tabindex'),
        text: norm(row),
        members: [...row.querySelectorAll('button.next-project-session')].map((member) => [
          member.getAttribute('data-next-route'),
          member.getAttribute('data-next-harness'),
          member.getAttribute('data-next-session'),
          norm(member),
        ]),
        more: row.querySelector('.next-project-more')
          ? norm(row.querySelector('.next-project-more'))
          : null,
      })),
    })),
  };
};

const summarizeProject = ({ tab, recordedStates }) => {
  const norm = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : '');
  const { document } = globalThis;
  const body = document.querySelector('[data-next-view-body="project"]');
  const article = document.querySelector('article.next-project-detail')?.cloneNode(true);
  if (!article)
    return {
      empty: body
        ? {
            state: body.getAttribute('data-next-project-state') || body.className,
            text: norm(body),
            links: [...body.querySelectorAll('a')].map((a) => a.getAttribute('href')),
          }
        : { missing: true },
    };
  const header = article.querySelector('.next-project-detail-header');
  // The recorded scope metadata used raw state tokens and contained no status limit or
  // plan status word. The Storybook plays assert the changed presentation directly.
  article
    .querySelectorAll(
      '.next-project-session-limit,[data-next-plan-status],[data-next-project-focus-status]',
    )
    .forEach((node) => node.remove());
  for (const link of article.querySelectorAll('[data-next-cockpit-scope]')) {
    const state = recordedStates[link.getAttribute('data-next-cockpit-scope')];
    const meta = link.querySelector('.next-cockpit-scope-meta');
    if (!state || !meta) continue;
    const hoisted = link
      .closest('nav')
      ?.querySelector('.next-cockpit-scope-heading')
      ?.textContent.includes(' · ');
    const parts = [...meta.children]
      .filter((part) => !part.matches('.next-cockpit-scope-state'))
      .map(norm);
    parts.splice(hoisted ? 0 : 1, 0, state);
    meta.textContent = parts.join(' · ');
  }
  const viewing = article.querySelector('[data-next-cockpit-viewing-session]');
  const focusedState = recordedStates[viewing?.getAttribute('data-next-cockpit-viewing-session')];
  if (focusedState) {
    viewing.append(` · ${focusedState}`);
    article
      .querySelector('.next-cockpit-scope-switcher [data-slot="accordion-trigger"] > span')
      ?.append(` · ${focusedState}`);
  }
  const tree = article.querySelector('nav.next-cockpit-scope-tree');
  const strip = article.querySelector('.next-cockpit-recovery');
  const panel =
    article.querySelector(`[data-next-cockpit-panel="${tab}"]`) ||
    article.querySelector('.next-cockpit-panel');
  return {
    header: norm(header),
    viewing: norm(article.querySelector('.next-cockpit-viewing-session')),
    scopeTree: norm(tree),
    scopeLinks: [...(tree ? tree.querySelectorAll('a') : [])].map((link) => [
      link.getAttribute('href'),
      link.getAttribute('data-scope-kind'),
      link.hasAttribute('aria-current'),
    ]),
    switcher: norm(
      article.querySelector(
        '[data-slot=accordion].next-cockpit-scope-switcher [data-slot=accordion-trigger]',
      ),
    ),
    strip: norm(strip),
    stripLinks: [...(strip ? strip.querySelectorAll('a') : [])].map((link) =>
      link.getAttribute('href'),
    ),
    tabs: [...article.querySelectorAll('nav.next-cockpit-tabs [role="tab"]')].map(
      (button) => `${norm(button)}|${button.getAttribute('aria-selected')}`,
    ),
    panel: norm(panel),
    panelLinks: [...(panel ? panel.querySelectorAll('a') : [])].map((link) =>
      link.getAttribute('href'),
    ),
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

/* A read taken the instant after a navigation can still show the previous view, and a project's context read
   arrives a beat after the page. The page counts as read once two reads 120 ms apart agree. */
async function settled(page, read, ...args) {
  let previous = await page.evaluate(read, ...args);
  for (let waited = 0; waited < patience(5000); waited += 120) {
    await new Promise((resolve) => setTimeout(resolve, 120));
    const next = await page.evaluate(read, ...args);
    if (JSON.stringify(next) === JSON.stringify(previous)) return next;
    previous = next;
  }
  throw new Error('The page kept changing.');
}

/* One board for the page, so it has one clock: every read of /api/data answers it, every project-context
   read answers `holder.contexts` by `project\nsession` (the project's own where the session has none), and the
   stream is refused so nothing else moves. A context of `null` is a read that fails. */
async function freeze(opened, holder) {
  await opened.page.route('**/api/data*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'X-Compass-Revision': '7.1' },
      body: JSON.stringify(holder.body),
    }),
  );
  await opened.page.route('**/api/project-context*', (route) => {
    const url = new URL(route.request().url());
    const project = url.searchParams.get('project') ?? '';
    const session = url.searchParams.get('session') ?? '';
    const body = holder.contexts[`${project}\n${session}`] ?? holder.contexts[`${project}\n`];
    if (!body) return route.fulfill({ status: 500, contentType: 'text/plain', body: 'no context' });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
  await opened.page.route('**/api/stream', (route) => route.abort('failed'));
}

/* The command-opener departure uses the same snapshot projection as recordedCommandOpener.ts.
   Keep it local: that Vitest helper imports extensionless application modules Node cannot resolve.
   docs/design-frontend-migration.md#held-to-recorded-answers owns the wording departure. */
function restateLiveOpenerValue(value) {
  if (typeof value === 'string')
    return value.replaceAll('No name: the session opened with a command', 'Title not published');
  if (Array.isArray(value)) return value.map(restateLiveOpenerValue);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, restateLiveOpenerValue(item)]),
    );
  return value;
}

/* The first place two readings differ, each taken in its stored form, so a live reading and a recorded one meet
   as the same kind of data. */
function firstDifference(left, right) {
  return firstDifferenceIn(norm(left), norm(right), '$');
}
function firstDifferenceIn(left, right, path) {
  if (JSON.stringify(left) === JSON.stringify(right)) return null;
  if (left && right && typeof left === 'object' && typeof right === 'object') {
    for (const key of new Set([...Object.keys(left), ...Object.keys(right)])) {
      const found = firstDifferenceIn(left[key], right[key], `${path}.${key}`);
      if (found) return found;
    }
    // A recording stores its keys sorted, so two readings of one shape can differ only in key order.
    return null;
  }
  return `${path}: ${JSON.stringify(left)?.slice(0, 260)} != ${JSON.stringify(right)?.slice(0, 260)}`;
}

/* What was served, as a short digest: part of a recorded key, so a board that changed is a key that is absent. */
const digestOf = (value) =>
  createHash('sha256')
    .update(JSON.stringify(recordedName(value, true)))
    .digest('hex')
    .slice(0, 10);

/* A difference found by the comparison is a failure unless it is named here with its reason. */
const DEVIATIONS = [
  {
    scope: 'status and navigation marks',
    reason: '2026-11-22: the project rows, activity and workstream use Phosphor SVGs.',
  },
  {
    scope: 'recovery strip',
    reason:
      'Plain project labels distinguish instructions from a session goal; workflow gloss is conditional.',
  },
  {
    scope: 'member row',
    reason: 'Opening requests Intent focus under the same rule as a Sessions goal link.',
  },
];

function maskRecordedProjectGlyphs(record, evidence) {
  if (Array.isArray(record.groups)) {
    return {
      ...record,
      groups: record.groups.map((group) => ({
        ...group,
        rows: group.rows.map((row) => ({ ...row, text: row.text.replace(/›$/, '') })),
      })),
    };
  }
  if (typeof record.panel !== 'string') return record;
  const authored = new Set();
  const collect = (value) => {
    if (typeof value === 'string' && /[●○△◦✓▸▾]/.test(value))
      authored.add(value.replace(/\s+/g, ' ').trim());
    else if (value && typeof value === 'object') Object.values(value).forEach(collect);
  };
  collect(evidence);
  const held = [];
  const pattern = [...authored]
    .sort((a, b) => b.length - a.length)
    .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|');
  let panel = record.panel;
  if (pattern)
    panel = panel.replace(new RegExp(pattern, 'g'), (word) => `\uE000${held.push(word) - 1}\uE001`);
  return {
    ...record,
    panel: panel
      .replace(/[●○△◦✓]/g, '')
      .replace(/[▸▾]\s*(?=OBSERVED STATE CHANGES)/g, '')
      .replace(/\uE000(\d+)\uE001/g, (_match, index) => held[Number(index)]),
  };
}

const proof = parityBoard();
const contextsFor = (contexts) => {
  const out = {};
  for (const [project, body] of Object.entries(contexts)) if (body) out[`${project}\n`] = body;
  return out;
};
const stableKeyOf = (board, label) => {
  const row = (board.sessions || []).find((candidate) => candidate.project === label);
  return (row && row.project_key) || label;
};
const labelsOf = (board) => [
  ...new Set((board.sessions || []).map((row) => (row.project == null ? '' : String(row.project)))),
];
const fragmentFor = (label, { focus, tab } = {}) =>
  `#n=project:${E(label)}${focus ? `:${E(focus)}` : ''}${tab && tab !== 'now' ? `:${tab}` : ''}`;

const browser = await chromium.launch({ env: { ...process.env, TZ: 'UTC' } });
const board = await startSessionsBoard();
const reactOrigins = [board.react.origin, board.react.viteOrigin];
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
  const holder = { body: proof.board, contexts: contextsFor(proof.contexts) };
  await freeze(react, holder);

  /* `name` says what is being compared, and the key adds the fragment and what the board and contexts held at the
     moment, so two reads of one fragment over different boards are different keys. */
  async function both(name, fragment, read, ...args) {
    await load(react, board.react.origin, fragment);
    const mine =
      read === summarizeProject
        ? await settled(react.page, read, {
            tab: args[0],
            recordedStates: Object.fromEntries(
              (holder.body.sessions ?? []).map((row) => [
                `${row.harness}:${row.sid}`,
                String(row.state || 'unknown'),
              ]),
            ),
          })
        : await settled(react.page, read, ...args);
    const key = `${name} | ${fragment} | ${digestOf([holder.body, holder.contexts, args])}`;
    const project = decodeURIComponent(fragment.split(':')[1] || '');
    return {
      mine: restateLiveOpenerValue(mine),
      old: projectWordDeviation(
        maskRecordedProjectGlyphs(
          recordedLocationNotes(golden.observe(key), holder.body, project),
          [holder.body, holder.contexts],
        ),
        projectGlossEnabled(holder.body, project),
        [holder.body, holder.contexts],
        projectInstructionHeading(
          holder.body,
          project,
          holder.body.sessions?.find(
            (row) =>
              `${row.harness}:${row.sid}` === decodeURIComponent(fragment.split(':')[2] || ''),
          ) ?? null,
        ),
      ),
    };
  }

  await step(
    'plain projects: no workflow labels and one click from each member into Intent',
    async () => {
      const o = await newPage();
      const rows = [
        {
          harness: 'claude',
          sid: 'waiting',
          project: 'plain/app',
          state: 'needs_input',
          title: 'Waiting task',
          first_prompt: 'Ship the queue',
          first_prompt_at: 100,
        },
        {
          harness: 'claude',
          sid: 'working',
          project: 'plain/app',
          state: 'working',
          title: 'Working task',
          annotation_goal: 'Land the result',
          annotation_revision: 1,
        },
      ];
      await freeze(o, {
        body: { ...proof.board, annotate: true, tripwires: { enabled: false }, sessions: rows },
        contexts: {},
      });
      try {
        await load(o, board.react.origin, '#n=project:plain%2Fapp');
        const text = await o.page.locator('[data-next-view-body="project"]').innerText();
        for (const old of [
          'PROJECT RECOVERY BRIEFING',
          'ASSIGNMENT',
          'EXECUTION',
          'COMMAND',
          'LATEST EVIDENCE',
          'STATED GOAL',
          'STEER · LOCAL ONLY',
          'FO is the first officer, the agent driving this workflow; Captain is you.',
          'Workflow stage conditions',
          'FO INSPECTING',
          'FO CONTINUES',
          'CAPTAIN NEEDED',
          'Captain state unknown',
        ])
          assert.ok(!text.includes(old), old);
        assert.equal(
          await o.page
            .locator('[data-next-cockpit-waiting]')
            .getByText('Waiting task', { exact: true })
            .count(),
          1,
        );
        assert.ok(
          await o.page
            .locator('[data-next-cockpit-waiting]')
            .evaluate((node) =>
              Boolean(
                node.compareDocumentPosition(document.querySelector('[role=tablist]')) &
                  Node.DOCUMENT_POSITION_FOLLOWING,
              ),
            ),
        );
        const clicks = [];
        for (const row of rows) {
          await load(o, board.react.origin, '#n=projects');
          await o.page.evaluate(() => {
            globalThis.__memberClicks = 0;
            document.addEventListener(
              'click',
              (event) => {
                if (event.target.closest('[data-next-project-session]'))
                  globalThis.__memberClicks += 1;
              },
              true,
            );
          });
          await o.page
            .locator(`[data-next-project-session][data-next-session="${row.sid}"]`)
            .click();
          await o.page.waitForFunction(
            ({ typed, sid }) =>
              typed
                ? document.activeElement?.getAttribute('data-next-focus') ===
                  `held:claude:${sid}:goal`
                : document.activeElement?.id === 'next-session-intent-heading',
            { typed: Boolean(row.annotation_goal), sid: row.sid },
          );
          assert.equal(await o.page.evaluate(() => globalThis.__memberClicks), 1);
          clicks.push({ sid: row.sid, clicks: 1 });
        }
        return clicks;
      } finally {
        await o.close();
      }
    },
  );

  /* ===================== DIFFERENTIAL: the proof board ===================== */
  await step(
    'differential: the Projects list reads as recorded, group by group and row by row',
    async () => {
      const { mine, old } = await both('the list', '#n=projects', summarizeList);
      assert.ok(mine.groups?.length === 2, 'the React list draws both groups');
      const rows = mine.groups.reduce((sum, group) => sum + group.rows.length, 0);
      assert.ok(rows >= 6, `the proof board carries its projects (${rows})`);
      if (old) assert.equal(firstDifference(old, mine), null);
      return { rows, active: mine.groups[0].rows.map((row) => row.project) };
    },
  );

  await step('differential: every project of the proof board, on Now and on Course', async () => {
    const compared = [];
    for (const label of labelsOf(proof.board).filter(Boolean)) {
      for (const tab of ['now', 'course']) {
        const { mine, old } = await both(
          'a project',
          fragmentFor(label, { tab }),
          summarizeProject,
          tab,
        );
        assert.ok(mine.header, `${label} ${tab}: the page drew its project`);
        if (old) assert.equal(firstDifference(old, mine), null, `${label} ${tab}`);
        compared.push(`${label}:${tab}`);
      }
    }
    return { compared: compared.length };
  });

  await step(
    'differential: a project’s exact sessions as scopes, on Now and on Course',
    async () => {
      const compared = [];
      const rows = proof.board.sessions.filter((row) => row.project === 'alpha/app');
      for (const row of rows) {
        const focus = `${row.harness}:${row.sid}`;
        for (const tab of ['now', 'course']) {
          const { mine, old } = await both(
            'an exact session',
            fragmentFor('alpha/app', { focus, tab }),
            summarizeProject,
            tab,
          );
          assert.ok(mine.viewing, `${focus} ${tab}: the page says which session it is viewing`);
          if (old) assert.equal(firstDifference(old, mine), null, `${focus} ${tab}`);
          compared.push(`${focus}:${tab}`);
        }
      }
      return { compared: compared.length };
    },
  );

  /* ===================== DIFFERENTIAL: states that need another board ===================== */
  await step(
    'differential: no sessions, a project the board lacks, a stale focus and a failed read',
    async () => {
      const results = {};
      holder.body = {
        generated: proof.board.generated,
        harnesses: proof.board.harnesses,
        sessions: [],
      };
      {
        const { mine, old } = await both('no sessions: the list', '#n=projects', summarizeList);
        if (old) assert.equal(firstDifference(old, mine), null, 'no sessions: the list');
        assert.ok(mine.groups.every((group) => group.rows.length === 0 && group.empty));
        results.noSessions = mine.groups.map((group) => group.empty);
        const gone = await both(
          'no sessions: a project',
          fragmentFor('alpha/app'),
          summarizeProject,
          'now',
        );
        if (gone.old)
          assert.equal(firstDifference(gone.old.empty.text, gone.mine.empty.text), null);
        assert.match(gone.mine.empty.text, /not present in the current payload/i);
      }
      holder.body = proof.board;
      {
        const stale = await both(
          'a stale focus',
          fragmentFor('alpha/app', { focus: 'claude:gone' }),
          () =>
            globalThis.document
              .querySelector('[data-next-view-body="project"]')
              ?.textContent.replace(/\s+/g, ' ')
              .trim(),
        );
        if (stale.old) assert.equal(stale.old, norm(stale.mine), 'the stale focus');
        assert.match(stale.mine, /Session filter is outside this payload window/);
        results.staleFocus = stale.mine;
      }
      holder.contexts = {};
      {
        const failed = await both(
          'a failed read',
          fragmentFor('alpha/app', { tab: 'course' }),
          summarizeProject,
          'course',
        );
        if (failed.old)
          assert.equal(firstDifference(failed.old, failed.mine), null, 'a failed read');
        assert.match(failed.mine.panel, /Course evidence unavailable/);
        assert.match(failed.mine.strip, /Captain attention unavailable/);
        results.failedRead = 'unavailable, never "no changes"';
      }
      holder.contexts = contextsFor(proof.contexts);
      return results;
    },
  );

  await step(
    'differential: a project with no plan, and one that ended without an end stamp',
    async () => {
      const beta = await both('no plan', fragmentFor('beta/api'), summarizeProject, 'now');
      if (beta.old) assert.equal(firstDifference(beta.old, beta.mine), null, 'beta/api');
      assert.ok(!/PLAN\b/.test(beta.mine.panel) || /No live session plan/.test(beta.mine.panel));
      const alpha = await both(
        'ended without a stamp',
        fragmentFor('alpha/app'),
        summarizeProject,
        'now',
      );
      assert.match(alpha.mine.panel, /HOW THINGS ENDED/);
      assert.match(alpha.mine.panel, /Ended with uncommitted work/);
      return { noPlan: 'stated', ended: 'in HOW THINGS ENDED' };
    },
  );

  /* ===================== DIFFERENTIAL: generated boards ===================== */
  await step(
    `differential: ${SEEDS} generated boards read as recorded, list and project pages`,
    async () => {
      let lists = 0;
      let pages = 0;
      for (let seed = 1; seed <= SEEDS; seed += 1) {
        const generated = genBoard(seed);
        holder.body = generated;
        holder.contexts = {};
        const labels = labelsOf(generated).filter(Boolean);
        for (const label of labels) {
          const context = genContext(seed, generated);
          if (context) holder.contexts[`${stableKeyOf(generated, label)}\n`] = context;
        }
        const list = await both(`seed ${seed} list`, '#n=projects', summarizeList);
        if (list.old) {
          const found = firstDifference(list.old, list.mine);
          if (found && !DEVIATIONS.some((d) => d.seed === seed && d.scope === 'list'))
            assert.fail(`seed ${seed} list: ${found}`);
        }
        lists += 1;
        for (const label of labels.slice(0, 2)) {
          const tab = seed % 2 ? 'now' : 'course';
          const page = await both(
            `seed ${seed} project`,
            fragmentFor(label, { tab }),
            summarizeProject,
            tab,
          );
          if (page.old) {
            const found = firstDifference(page.old, page.mine);
            if (found && !DEVIATIONS.some((d) => d.seed === seed && d.scope === label))
              assert.fail(`seed ${seed} ${JSON.stringify(label)} ${tab}: ${found}`);
          }
          pages += 1;
        }
      }
      holder.body = proof.board;
      holder.contexts = contextsFor(proof.contexts);
      return { lists, pages };
    },
  );

  await step(
    'differential: hostile text is text, as recorded, and draws no element, selector or script',
    async () => {
      const hostile = [
        '"]\'><img src=x onerror=globalThis.__hit=1>',
        '<script>globalThis.__hit=1</script>',
        '\u202eRTL',
      ];
      holder.body = {
        generated: proof.board.generated,
        sessions: hostile.map((text, index) => ({
          harness: 'claude',
          sid: `s${index}:${text}`,
          project: text,
          title: text,
          state: 'working',
          active: true,
          state_detail: text,
          last_activity: proof.board.generated - 3,
        })),
      };
      holder.contexts = {};
      const list = await both('hostile: the list', '#n=projects', summarizeList);
      if (list.old) assert.equal(firstDifference(list.old, list.mine), null);
      assert.equal(await react.page.evaluate(() => globalThis.__hit), undefined, 'no handler ran');
      assert.equal(
        await react.page.locator('main img, main script').count(),
        0,
        'no element was injected',
      );
      const label = hostile[0];
      const page = await both('hostile: the project', fragmentFor(label), summarizeProject, 'now');
      assert.ok(page.mine.header.includes('img src'), 'the label is drawn as text');
      if (page.old) assert.equal(firstDifference(page.old, page.mine), null);
      holder.body = proof.board;
      holder.contexts = contextsFor(proof.contexts);
    },
  );

  /* ===================== BEHAVIOUR: resources, and nothing the reader did not press for ===================== */
  async function clocked(fragment, { storage, initScripts = [] } = {}) {
    const o = await newPage();
    const state = { body: proof.board, contexts: contextsFor(proof.contexts), polls: 0 };
    await o.page.clock.install({ time: Date.now() });
    if (storage)
      await o.context.addInitScript((seed) => {
        for (const [key, value] of Object.entries(seed)) {
          try {
            globalThis.localStorage.setItem(key, value);
          } catch {
            /* a refusing store */
          }
        }
      }, storage);
    for (const script of initScripts) await o.context.addInitScript(script);
    await o.page.route('**/api/data*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'X-Compass-Revision': '7.1' },
        body: JSON.stringify(state.body),
      }),
    );
    await o.page.route('**/api/project-context*', (route) => {
      const url = new URL(route.request().url());
      const project = url.searchParams.get('project') ?? '';
      const session = url.searchParams.get('session') ?? '';
      const body = state.contexts[`${project}\n${session}`] ?? state.contexts[`${project}\n`];
      if (!body)
        return route.fulfill({ status: 500, contentType: 'text/plain', body: 'no context' });
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    });
    await o.page.route('**/api/stream', (route) => route.abort('failed'));
    await o.page.goto(board.react.origin + '/' + fragment);
    await reactReady(o.page);
    await o.page.waitForTimeout(patience(300));
    o.state = state;
    /* One board revision, as the page's own fallback poll brings it: the clock moves past the interval and the
       board's own clock moves with it. */
    o.poll = async (change = {}) => {
      state.body = { ...state.body, ...change, generated: state.body.generated + 25 };
      state.polls += 1;
      const before = o.counts().data;
      await o.page.clock.fastForward(20_000);
      for (let waited = 0; waited < patience(4000) && o.counts().data <= before; waited += 100)
        await new Promise((resolve) => setTimeout(resolve, 100));
      await o.page.waitForTimeout(patience(250));
    };
    return o;
  }

  await step(
    'resources: a project page opens one stream and reads once, under StrictMode, and navigation adds nothing',
    async () => {
      const live = await newPage();
      try {
        await live.context.addInitScript(() => {
          const causes = { revisions: new Set(), polls: 0 };
          globalThis.__readCauses = causes;
          const Source = globalThis.EventSource;
          globalThis.EventSource = class extends Source {
            constructor(...args) {
              super(...args);
              this.addEventListener('revision', (event) => causes.revisions.add(event.data));
            }
          };
          const setInterval = globalThis.setInterval;
          globalThis.setInterval = (callback, ms, ...args) =>
            setInterval(
              (...values) => {
                if (ms === 20_000) causes.polls += 1;
                callback(...values);
              },
              ms,
              ...args,
            );
        });
        const readCauses = () =>
          live.page.evaluate(() => ({
            revisions: [...globalThis.__readCauses.revisions],
            polls: globalThis.__readCauses.polls,
          }));
        const assertReads = (sample, phase) => {
          // The live producer advances the revision while a slow runner waits or navigates. Count
          // those wakes and fallback polls, rather than giving every run a fixed spare-read budget.
          const allowed = 1 + sample.causes.revisions.length + sample.causes.polls;
          assert.ok(
            sample.counts.data >= 1 && sample.counts.data <= allowed,
            `${phase} read, saw ${sample.counts.data}; boot, revisions and polls allow ${allowed}`,
          );
          assert.ok(
            sample.context >= 1 && sample.context <= sample.counts.data,
            `${phase}: the project context was read ${sample.context} times for ${sample.counts.data} board reads`,
          );
        };
        await live.page.goto(board.react.origin + '/' + fragmentFor('alpha/app'));
        await reactReady(live.page);
        await live.page.waitForTimeout(patience(600));
        const contextReads = () =>
          live.log.requests.filter((entry) => entry.path.startsWith('/api/project-context')).length;
        const first = {
          counts: live.counts(),
          res: await resources(live.page),
          context: contextReads(),
          causes: await readCauses(),
        };
        assertReads(first, 'boot');
        assert.equal(first.counts.stream, 1, 'one stream');
        assert.equal(first.counts.nonGet, 0, 'nothing but reads');
        assert.deepEqual([first.res.opened, first.res.closed, first.res.sources], [1, 0, 1]);
        for (let round = 0; round < 5; round += 1) {
          await live.page.locator('nav[aria-label="Primary"] a', { hasText: 'Projects' }).click();
          await live.page.waitForSelector('[data-next-view-body="projects"]');
          // The row's name, not its middle: a member line there is a link of its own to one session.
          await live.page
            .locator('article.next-project-row[data-next-project="alpha/app"] .next-project-name')
            .click();
          await live.page.waitForSelector('article.next-project-detail');
          for (const tab of ['Course', 'Now']) {
            await live.page.getByRole('tab', { name: new RegExp(`^${tab}`) }).click();
            await live.page.waitForTimeout(patience(60));
          }
        }
        await live.page.waitForTimeout(patience(500));
        const after = {
          counts: live.counts(),
          res: await resources(live.page),
          context: contextReads(),
          causes: await readCauses(),
        };
        assert.equal(after.counts.stream, 1, 'navigation opened no second stream');
        assertReads(after, 'navigation');
        assert.equal(after.counts.nonGet, 0);
        assert.deepEqual([after.res.opened, after.res.closed, after.res.sources], [1, 0, 1]);
        assert.ok(
          after.res.intervals <= first.res.intervals,
          `intervals settled (${first.res.intervals} -> ${after.res.intervals})`,
        );
        assert.deepEqual(
          await live.page.evaluate(() => globalThis.__copied),
          [],
          'nothing was copied',
        );
        assert.deepEqual(live.log.consoleErrors, []);
        assert.deepEqual(live.log.pageErrors, []);
        assert.deepEqual(live.log.externalRequests, []);
        return {
          first: { ...first.counts, ...first.res, context: first.context, causes: first.causes },
          after: { ...after.counts, ...after.res, context: after.context, causes: after.causes },
        };
      } finally {
        await live.close();
      }
    },
  );

  await step(
    'actions: Copy briefing copies once per press, from the rows the strip draws, and never on its own',
    async () => {
      const o = await clocked(fragmentFor('alpha/app'));
      try {
        await o.poll();
        await o.page.getByRole('tab', { name: /^Course/ }).click();
        await o.poll();
        assert.deepEqual(
          await o.page.evaluate(() => globalThis.__copied),
          [],
          'nothing copied before a press',
        );
        assert.deepEqual(o.log.nonGet, [], 'nothing posted before a press');
        await o.page.locator('summary[aria-label="More"]').click();
        await o.page.getByRole('button', { name: 'Copy briefing' }).click();
        await o.page.waitForTimeout(patience(150));
        const copied = await o.page.evaluate(() => globalThis.__copied);
        assert.equal(copied.length, 1, 'one press, one copy');
        assert.ok(
          copied[0].startsWith('Compass recovery briefing\nProject: app\n'),
          copied[0].slice(0, 80),
        );
        assert.match(copied[0], /Captain attention: Authorize the dispatch\?/);
        assert.match(copied[0], /Assignment: Ship feature · Build · Exact workflow state/);
        assert.equal(
          await o.page.getByRole('button', { name: 'Copied' }).count(),
          1,
          'the control says it copied',
        );
        await o.poll();
        assert.equal(
          await o.page.getByRole('button', { name: 'Copied' }).count(),
          1,
          'the cue outlived a poll',
        );
        await o.page.getByRole('button', { name: 'Copied' }).click();
        assert.equal(
          (await o.page.evaluate(() => globalThis.__copied)).length,
          2,
          'a second press is a second copy',
        );
        assert.deepEqual(o.log.nonGet, [], 'copying posts nothing');
        return { copied: copied[0].split('\n').length + ' lines' };
      } finally {
        await o.close();
      }
    },
  );

  /* ===================== BEHAVIOUR: the workstream's collapse ===================== */
  const WORKSTREAM_KEY = 'compass.next.workstream.collapsed';
  await step(
    'workstream: the collapse survives a reload as 1 or 0, and a refusing store keeps the tab’s toggle',
    async () => {
      const o = await clocked(fragmentFor('alpha/app', { tab: 'course' }));
      try {
        const toggle = o.page.locator('[data-next-workstream-toggle]');
        assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
        await toggle.click();
        assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
        assert.equal(
          await o.page.evaluate((key) => globalThis.localStorage.getItem(key), WORKSTREAM_KEY),
          '1',
        );
        await o.page.reload();
        await reactReady(o.page);
        await o.page.waitForTimeout(patience(300));
        assert.equal(
          await o.page.locator('[data-next-workstream-toggle]').getAttribute('aria-expanded'),
          'false',
          'collapsed after a reload',
        );
        await o.page.locator('[data-next-workstream-toggle]').click();
        assert.equal(
          await o.page.evaluate((key) => globalThis.localStorage.getItem(key), WORKSTREAM_KEY),
          '0',
        );
      } finally {
        await o.close();
      }
      // A store that refuses every write: the toggle still works in the tab.
      const blocked = await clocked(fragmentFor('alpha/app', { tab: 'course' }), {
        initScripts: [
          () => {
            const refuse = () => {
              throw new DOMException('blocked', 'QuotaExceededError');
            };
            globalThis.Storage.prototype.setItem = refuse;
          },
        ],
      });
      try {
        const toggle = blocked.page.locator('[data-next-workstream-toggle]');
        await toggle.click();
        assert.equal(
          await toggle.getAttribute('aria-expanded'),
          'false',
          'the tab keeps the toggle',
        );
        await blocked.page.getByRole('tab', { name: /^Now/ }).click();
        await blocked.page.getByRole('tab', { name: /^Course/ }).click();
        assert.equal(
          await blocked.page.locator('[data-next-workstream-toggle]').getAttribute('aria-expanded'),
          'false',
          'and it survives a tab change',
        );
      } finally {
        await blocked.close();
      }
      // The previous interface's unnamespaced key is not adopted.
      const stray = await clocked(fragmentFor('alpha/app', { tab: 'course' }), {
        storage: { 'compass.workstream.collapsed': '1' },
      });
      try {
        assert.equal(
          await stray.page.locator('[data-next-workstream-toggle]').getAttribute('aria-expanded'),
          'true',
          'an unnamespaced key is not read',
        );
      } finally {
        await stray.close();
      }
      return {
        key: WORKSTREAM_KEY,
        readBack: '1 then 0',
        refusingStore: 'tab toggle kept',
        unnamespaced: 'not adopted',
      };
    },
  );

  await step(
    'workstream: a change this tab saw is listed, and the previous interface listed the same change from the same boards',
    async () => {
      const changed = (state, generated) => ({
        generated,
        sessions: proof.board.sessions.map((row) =>
          row.sid === 'a-lead' && row.harness === 'claude' ? { ...row, state } : row,
        ),
      });
      const results = {};
      /* The changes a page listed after two further boards reached it. Each row begins with the clock time the page
         saw it, which is the moment of the run, so a reading is the last two rows without it. */
      const listed = async (o, origin) => {
        holder.body = proof.board;
        await load(o, origin, fragmentFor('alpha/app', { tab: 'course' }));
        // Two further boards reach the page the way a poll would.
        for (const [index, state] of ['idle', 'working'].entries()) {
          holder.body = {
            ...proof.board,
            ...changed(state, proof.board.generated + 60 * (index + 1)),
          };
          await o.page.evaluate(() =>
            globalThis.dispatchEvent(
              new globalThis.StorageEvent('storage', {
                key: 'compass.next.revision',
                newValue: `9.${Date.now() % 100000}`,
              }),
            ),
          );
          await o.page.waitForTimeout(patience(400));
        }
        return settled(o.page, () => ({
          rows: [...globalThis.document.querySelectorAll('.next-project-change')].map((row) =>
            row.textContent.replace(/\s+/g, ' ').trim(),
          ),
          note: globalThis.document.querySelector('[data-next-workstream-toggle] small')
            ?.textContent,
        }));
      };
      const lastTwo = (reading) =>
        reading.rows.slice(-2).map((row) => row.replace(/^\d\d:\d\d/, ''));
      results.react = await listed(react, board.react.origin);
      const recordedRows = golden.observe('workstream: the changes the legacy page listed');
      holder.body = proof.board;
      assert.ok(results.react.rows.length >= 1, 'this tab observed a change');
      // The reload above read the board once, so the page saw the same two changes the recording did.
      assert.deepEqual(lastTwo(results.react), recordedRows);
      return results.react;
    },
  );

  /* ===================== BEHAVIOUR: human context ===================== */
  await step(
    'memo: a note keeps its node, text, caret, focus and native undo through the board’s own revisions and tab changes',
    async () => {
      const o = await clocked(fragmentFor('beta/api'));
      try {
        await o.page.getByText('+ Add human context · this browser').click();
        const box = o.page.locator(
          'textarea[placeholder="What result should this scope achieve?"]',
        );
        await box.waitFor();
        assert.equal(
          await box.evaluate((node) => node === globalThis.document.activeElement),
          true,
          'the editor took focus when opened',
        );
        await o.page.evaluate(() => {
          globalThis.document.querySelector(
            'textarea[placeholder="What result should this scope achieve?"]',
          ).__mark = 'kept';
        });
        await o.page.keyboard.type('hello brave world');
        for (let i = 0; i < 5; i += 1) await o.page.keyboard.press('ArrowLeft');
        await o.page.keyboard.type('X');
        await o.page.keyboard.press('ArrowLeft');
        await o.page.keyboard.press('Shift+ArrowLeft');
        await o.page.keyboard.press('Shift+ArrowLeft');
        const before = await box.evaluate((node) => [
          node.selectionStart,
          node.selectionEnd,
          node.value,
        ]);
        await o.poll();
        await o.poll({
          sessions: o.state.body.sessions.map((row) =>
            row.sid === 'b-1' ? { ...row, state: 'working' } : row,
          ),
        });
        const through = await box.evaluate((node) => [
          node.selectionStart,
          node.selectionEnd,
          node.value,
          globalThis.document.activeElement === node,
          node.__mark,
        ]);
        assert.deepEqual(through.slice(0, 3), before, 'text and caret survived the revisions');
        assert.equal(through[3], true, 'focus stayed in the note');
        assert.equal(through[4], 'kept', 'the note’s node was kept, not replaced');
        // The strip sits above the tabs, so a tab change leaves the note where it is.
        await o.page.getByRole('tab', { name: /^Course/ }).click();
        await o.page.waitForTimeout(patience(100));
        await o.page.getByRole('tab', { name: /^Now/ }).click();
        await o.page.waitForTimeout(patience(100));
        await o.poll();
        const after = await box.evaluate((node) => [
          node.selectionStart,
          node.selectionEnd,
          node.value,
          node.__mark,
        ]);
        assert.deepEqual(
          [after[0], after[1], after[2]],
          before,
          'a tab change left the note alone',
        );
        assert.equal(after[3], 'kept');
        await box.focus();
        await o.page.keyboard.press(`${MOD}+z`);
        assert.equal(
          await box.inputValue(),
          'hello brave world',
          'native undo still steps back over the typed character',
        );
        await o.page.keyboard.press(`${MOD}+Shift+z`);
        assert.equal(await box.inputValue(), 'hello brave Xworld', 'and forward again');
        assert.equal(
          await o.page.evaluate(
            (key) => globalThis.localStorage.getItem(key),
            'compass.cockpit.memo.v2:beta%2Fapi:project:outcome',
          ),
          'hello brave Xworld',
          'saved on input to the released key',
        );
        assert.deepEqual(o.log.nonGet, [], 'typing and revisions sent nothing');
        return { caret: before.slice(0, 2), value: before[2] };
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'memo: a note belongs to its project and its scope, and Escape puts back the words held when editing began',
    async () => {
      const o = await clocked(fragmentFor('beta/api'), {
        storage: { 'compass.cockpit.memo.v2:beta%2Fapi:project:outcome': 'Land the queue' },
      });
      try {
        assert.match(
          await o.page.locator('.next-cockpit-recovery-memos').innerText(),
          /Land the queue/,
        );
        await o.page.locator('button[aria-label="Edit OUTCOME"]').click();
        const box = o.page.locator(
          'textarea[placeholder="What result should this scope achieve?"]',
        );
        await box.waitFor();
        assert.equal(
          await box.inputValue(),
          'Land the queue',
          'the editor opens with the saved words',
        );
        await box.pressSequentially(' and more', { delay: 10 });
        await o.page.keyboard.press('Escape');
        await o.page.waitForTimeout(patience(100));
        assert.match(
          await o.page.locator('.next-cockpit-recovery-memos').innerText(),
          /Land the queue/,
        );
        assert.equal(
          await o.page.evaluate(() =>
            globalThis.localStorage.getItem('compass.cockpit.memo.v2:beta%2Fapi:project:outcome'),
          ),
          'Land the queue',
          'Escape restored the saved words',
        );
        // Another project does not show it.
        await o.page.evaluate(() => {
          globalThis.location.hash = '#n=project:calm%2Fapp';
        });
        await o.page.waitForSelector(
          'article.next-project-detail[data-next-project-detail="calm/app"]',
        );
        assert.equal(
          await o.page.getByText('Land the queue').count(),
          0,
          'the note stayed with its project',
        );
        // A session scope of the first project draws no note, and the root draws it again on return.
        await o.page.evaluate(() => {
          globalThis.location.hash = '#n=project:beta%2Fapi';
        });
        await o.page.waitForSelector(
          'article.next-project-detail[data-next-project-detail="beta/api"]',
        );
        assert.match(
          await o.page.locator('.next-cockpit-recovery-memos').innerText(),
          /Land the queue/,
        );
      } finally {
        await o.close();
      }
    },
  );

  /* ===================== BEHAVIOUR: scope, disclosures, focus ===================== */
  await step(
    'scope: the root and an exact session are different scopes, and the scope survives leaving and coming back',
    async () => {
      const results = {};
      const o = await clocked(fragmentFor('alpha/app', { tab: 'course' }));
      try {
        const links = o.page.locator('nav.next-cockpit-scope-tree a');
        assert.equal(
          await links.first().getAttribute('aria-current'),
          'page',
          'the root is the current scope',
        );
        assert.equal(await links.first().getAttribute('data-scope-kind'), 'project');
        const target = o.page.locator(
          'nav.next-cockpit-scope-tree a[data-next-cockpit-scope="claude:a-wait"]',
        );
        assert.equal(await target.getAttribute('data-scope-kind'), 'session');
        await target.click();
        await o.page.waitForFunction(() => globalThis.location.hash.includes('claude%3Aa-wait'));
        results.focused = await o.page.evaluate(() => globalThis.location.hash);
        assert.equal(
          await o.page
            .locator('nav.next-cockpit-scope-tree a[data-next-cockpit-scope="claude:a-wait"]')
            .getAttribute('aria-current'),
          'page',
        );
        assert.match(
          await o.page.locator('.next-cockpit-viewing-session').innerText(),
          /Viewing session · Claude Code · needs_input/,
        );
        assert.match(results.focused, /:course$/, 'the tab was kept');
        // Away to Sessions and back with the browser's own history.
        await o.page.locator('nav[aria-label="Primary"] a', { hasText: 'Sessions' }).click();
        await o.page.waitForSelector('[data-next-view-body="sessions"]');
        await o.page.goBack();
        await o.page.waitForSelector('article.next-project-detail');
        assert.equal(
          await o.page.evaluate(() => globalThis.location.hash),
          results.focused,
          'back restored the scope',
        );
        assert.equal(
          await o.page
            .locator('nav.next-cockpit-scope-tree a[data-next-cockpit-scope="claude:a-wait"]')
            .getAttribute('aria-current'),
          'page',
        );
        await o.page.reload();
        await reactReady(o.page);
        await o.page.waitForSelector('article.next-project-detail');
        assert.equal(
          await o.page.evaluate(() => globalThis.location.hash),
          results.focused,
          'a reload kept it',
        );
        // Another harness's session with the same sid is a different scope.
        const same = await o.page
          .locator('nav.next-cockpit-scope-tree a[data-next-cockpit-scope$=":a-lead"]')
          .evaluateAll((nodes) =>
            nodes.map((node) => node.getAttribute('data-next-cockpit-scope')),
          );
        assert.deepEqual(same.sort(), ['claude:a-lead', 'codex:a-lead']);
        return results;
      } finally {
        await o.close();
      }
    },
  );

  await step(
    'continuity: an open plan, a focused link and the page’s nodes survive a poll that changes the rows',
    async () => {
      const o = await clocked(fragmentFor('alpha/app'));
      try {
        await o.page.getByText('Show project plan').click();
        await o.page.evaluate(() => {
          const card = globalThis.document.querySelector('[data-next-going-on="a-lead"]');
          card.__mark = 'kept';
          const link = globalThis.document.querySelector(
            'nav.next-cockpit-scope-tree a[data-next-cockpit-scope="claude:a-lead"]',
          );
          link.focus();
        });
        await o.poll({
          sessions: o.state.body.sessions.map((row) =>
            row.sid === 'a-lead' && row.harness === 'claude' ? { ...row, rate_per_min: 1500 } : row,
          ),
        });
        const kept = await o.page.evaluate(() => ({
          mark: globalThis.document.querySelector('[data-next-going-on="a-lead"]')?.__mark,
          text: globalThis.document
            .querySelector('[data-next-going-on="a-lead"]')
            ?.textContent.includes('1,500'),
          focus: globalThis.document.activeElement?.getAttribute('data-next-cockpit-scope'),
          open: [
            ...globalThis.document.querySelectorAll(
              'details[open] > summary,[data-slot=accordion][data-open] [data-slot=accordion-trigger]',
            ),
          ].map((summary) => summary.textContent),
        }));
        assert.equal(kept.text, true, 'the change reached the card');
        assert.equal(kept.mark, 'kept', 'the card was updated, not replaced');
        assert.equal(kept.focus, 'claude:a-lead', 'focus stayed on the scope link');
        assert.ok(kept.open.includes('Show project plan'), 'the plan stayed open');
        await o.page.getByRole('tab', { name: /^Course/ }).click();
        await o.page.getByRole('tab', { name: /^Now/ }).click();
        assert.ok(
          (
            await o.page.evaluate(() =>
              [
                ...globalThis.document.querySelectorAll(
                  'details[open] > summary,[data-slot=accordion][data-open] [data-slot=accordion-trigger]',
                ),
              ].map((summary) => summary.textContent),
            )
          ).includes('Show project plan'),
          'and a tab change',
        );
        return kept;
      } finally {
        await o.close();
      }
    },
  );

  /* ===================== BEHAVIOUR: keyboard ===================== */
  await step(
    'keyboard: a project row opens with Enter, the tab strip wraps with the arrows, and a scope is reached by Tab',
    async () => {
      const results = {};
      const openRow = async (name, opened_, origin) => {
        await load(opened_, origin, '#n=projects');
        await opened_.page.evaluate(() => globalThis.document.activeElement?.blur());
        let stops = 0;
        for (; stops < 60; stops += 1) {
          await opened_.page.keyboard.press('Tab');
          const onRow = await opened_.page.evaluate(
            () => globalThis.document.activeElement?.matches('article.next-project-row') === true,
          );
          if (onRow) break;
        }
        assert.ok(stops < 60, `${name}: a project row is reachable by Tab`);
        await opened_.page.keyboard.press('Enter');
        await opened_.page.waitForFunction(() => globalThis.location.hash.includes('project:'));
        return { opens: await opened_.page.evaluate(() => globalThis.location.hash) };
      };
      results.recorded = golden.observe('keyboard: a project row opens with Enter');
      results.react = await openRow('react', react, board.react.origin);
      assert.deepEqual(results.react, results.recorded);
      const o = react;
      await o.page.waitForSelector('article.next-project-detail');
      const tab = (name) => o.page.getByRole('tab', { name: new RegExp(`^${name}`) });
      await tab('Now').focus();
      await o.page.keyboard.press('ArrowLeft');
      assert.equal(
        await o.page.evaluate(() => globalThis.document.activeElement?.textContent.slice(0, 7)),
        'Console',
        'ArrowLeft wraps to the last tab and focuses it',
      );
      await o.page.keyboard.press('ArrowRight');
      assert.equal(
        await o.page.evaluate(() => globalThis.document.activeElement?.textContent.slice(0, 3)),
        'Now',
      );
      let reached = false;
      for (let stop = 0; stop < 80 && !reached; stop += 1) {
        await o.page.keyboard.press('Tab');
        reached = await o.page.evaluate(
          () => globalThis.document.activeElement?.hasAttribute('data-next-cockpit-scope') === true,
        );
      }
      assert.ok(reached, 'a scope link is reachable by Tab');
      return { ...results, tabStrip: 'wraps' };
    },
  );

  /* ===================== BEHAVIOUR: layout ===================== */
  await step(
    'layout: 320, 375 and 640 CSS px (and 1280) never scroll sideways, on the list and every tab',
    async () => {
      const widths = [320, 375, 640, 1280];
      const overflow = [];
      for (const width of widths) {
        const o = await newPage({ viewport: { width, height: 900 } });
        try {
          await o.page.route('**/api/data*', (route) =>
            route.fulfill({
              status: 200,
              contentType: 'application/json',
              headers: { 'X-Compass-Revision': '7.1' },
              body: JSON.stringify(proof.board),
            }),
          );
          await o.page.route('**/api/project-context*', (route) => {
            const url = new URL(route.request().url());
            const body = contextsFor(proof.contexts)[`${url.searchParams.get('project')}\n`];
            return body
              ? route.fulfill({
                  status: 200,
                  contentType: 'application/json',
                  body: JSON.stringify(body),
                })
              : route.fulfill({ status: 500, body: 'no' });
          });
          await o.page.route('**/api/stream', (route) => route.abort('failed'));
          for (const fragment of [
            '#n=projects',
            fragmentFor('alpha/app'),
            fragmentFor('alpha/app', { tab: 'course' }),
            fragmentFor('alpha/app', { focus: 'claude:a-wait' }),
            fragmentFor('ünï/çødé'),
            fragmentFor('beta/api'),
          ]) {
            await o.page.goto('about:blank');
            await o.page.goto(board.react.origin + '/' + fragment);
            await reactReady(o.page);
            await o.page.waitForTimeout(patience(250));
            if (fragment.includes('alpha')) {
              const switcher = o.page.locator(
                '[data-slot=accordion].next-cockpit-scope-switcher [data-slot=accordion-trigger]',
              );
              // The switcher is the compact page's, so the wide page hides it and there is nothing to open.
              if (await switcher.isVisible()) await switcher.click();
            }
            const wide = await o.page.evaluate(() => ({
              scroll: globalThis.document.documentElement.scrollWidth,
              client: globalThis.document.documentElement.clientWidth,
            }));
            if (wide.scroll > wide.client)
              overflow.push(`${width}px ${fragment}: ${wide.scroll} > ${wide.client}`);
          }
        } finally {
          await o.close();
        }
      }
      assert.deepEqual(overflow, [], 'nothing scrolls sideways');
      return { widths };
    },
  );

  /* ===================== computed style against the recording ===================== */
  /* A rule that stopped reaching its target shows as a different computed value, not as different text, so the
     parity of three layout facts is read from the browser: the side inset of a tab's panel (and where its
     content starts), the tab strip's own margin, and how the workstream toggle is drawn. Each is compared to
     the recorded value at a phone width and a desktop width. */
  const computedLayout = () => {
    const { document, getComputedStyle } = globalThis;
    const pick = (node, names) => {
      if (!node) return null;
      const style = getComputedStyle(node);
      return Object.fromEntries(names.map((name) => [name, style.getPropertyValue(name)]));
    };
    const content = document.querySelector('.next-cockpit-content');
    const panel = document.querySelector('.next-cockpit-panel');
    const left = (node) =>
      node && content
        ? Math.round(node.getBoundingClientRect().left - content.getBoundingClientRect().left)
        : null;
    return {
      panel: pick(panel, ['padding-left', 'padding-right']),
      panelWidth: panel ? Math.round(panel.getBoundingClientRect().width) : null,
      panelContentLeft: left(panel?.querySelector('.next-workstream, .next-project-activity')),
      tabs: pick(document.querySelector('nav.next-cockpit-tabs'), [
        'margin-top',
        'margin-bottom',
        'padding-left',
        'padding-right',
        'border-bottom-width',
      ]),
      toggle: pick(document.querySelector('[data-next-workstream-toggle]'), [
        'padding-top',
        'padding-right',
        'padding-bottom',
        'padding-left',
        'border-top-width',
        'border-bottom-width',
        'border-left-width',
        'border-right-width',
        'background-color',
        'font-family',
        'font-size',
        'font-weight',
        'letter-spacing',
        'width',
      ]),
    };
  };
  await step(
    'computed style: a tab panel’s inset, the tab strip’s margin and the workstream toggle match the recording at 375 and 1280',
    async () => {
      const results = {};
      for (const width of [375, 1280]) {
        await react.page.setViewportSize({ width, height: 900 });
        for (const tab of ['now', 'course']) {
          const { mine, old } = await both(
            `computed style at ${width}`,
            fragmentFor('alpha/app', { tab }),
            computedLayout,
          );
          // Held to fixed values as well as to the recording's, so a recording cannot excuse a regression.
          assert.equal(
            mine.panel['padding-left'],
            '12px',
            `${width}px ${tab}: the panel keeps its 12px side inset`,
          );
          assert.equal(mine.panel['padding-right'], '12px');
          assert.equal(
            mine.tabs['margin-top'],
            '0px',
            `${width}px ${tab}: the tab strip has no top margin`,
          );
          if (tab === 'course') {
            assert.equal(
              mine.toggle['border-top-width'],
              '0px',
              `${width}px: the workstream toggle is a caption, not a bordered button`,
            );
            assert.equal(mine.toggle['padding-left'], '0px');
            assert.match(mine.toggle['font-family'], /mono/i);
          }
          // The shell lost its two 1px side borders in 715033e2; the recorded panel was narrower.
          // docs/design-frontend-migration.md#held-to-recorded-answers keeps the other style facts exact.
          const expected = {
            ...old,
            panelWidth: old.panelWidth + 2,
            ...(old.toggle && {
              toggle: {
                ...old.toggle,
                'font-family':
                  old.toggle['font-family'] === '"IBM Plex Mono", ui-monospace, monospace'
                    ? 'ui-monospace, monospace'
                    : old.toggle['font-family'],
                width: `${Number.parseFloat(old.toggle.width) + 2}px`,
              },
            }),
          };
          assert.equal(firstDifference(expected, mine), null, `${width}px ${tab}`);
          results[`${width}:${tab}`] = {
            inset: mine.panel['padding-left'],
            tabsMargin: mine.tabs['margin-top'],
            toggleBorder: mine.toggle?.['border-top-width'],
          };
        }
      }
      await react.page.setViewportSize({ width: 1280, height: 720 });
      return results;
    },
  );

  /* ===================== screenshots ===================== */
  await step('screenshots: the list and a project page, wide and narrow', async () => {
    for (const [label, fragment] of [
      ['projects-list', '#n=projects'],
      ['project-alpha-now', fragmentFor('alpha/app')],
      ['project-alpha-course', fragmentFor('alpha/app', { tab: 'course' })],
    ]) {
      for (const width of [1280, 375]) {
        await react.page.setViewportSize({ width, height: 1100 });
        await load(react, board.react.origin, fragment);
        await react.page.waitForTimeout(patience(300));
        const file = `${SHOTS}project-views-${label}-react-${width}.png`;
        await react.page.screenshot({ path: file, fullPage: true });
        shots.push(file);
      }
    }
    return { shots: shots.length };
  });

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

try {
  golden.finish({ complete: !only && failures.length === 0 });
} catch (error) {
  failures.push({ name: 'golden', message: String(error.message) });
}

console.log(
  JSON.stringify(
    {
      project: receipts,
      deviations: DEVIATIONS,
      screenshots: shots,
    },
    null,
    2,
  ),
);
if (failures.length) {
  console.error(JSON.stringify({ failures }, null, 2));
  process.exitCode = 1;
}
