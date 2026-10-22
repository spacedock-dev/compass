import { sessionDeviations } from './support/session-deviations.mjs';
/* global document, getComputedStyle -- used inside page.evaluate, which runs in the browser */
/*
 * The Drift section, Analyze, its result, Steer back and the departures in a real browser.
 *
 * Two kinds of proof. The DIFFERENTIAL half drives the React page over one scripted board (`drift-board.mjs`: the
 * real document and modules, the Drift fields and the routes that could reach a model replaced) and compares what a
 * reader can read, in each state a reader reaches, with what the previous interface showed there: no reading, a
 * refusal, an Allow owed, a running analysis, a cancel, a stored result, a withheld one, a reading this build cannot
 * read, a superseded one, a gap in the record, the lane off and on. The BEHAVIOUR half holds the React page to what a
 * unit test cannot see: the correction box's node, text, caret, selection, native undo and input-method composition
 * surviving the board's own revisions, a route away and back and a pointer on its way to a control; request counts
 * over a mount, a poll, a route change, a hover, a focus and a keypress; keyboard operation; the announcements
 * through the runtime's live regions; and 320/375/640(200% zoom)/1280 CSS px layouts with no horizontal page scroll.
 *
 * What the previous interface said is a RECORDING (`support/golden.mjs`, `frontend/test/golden/e2e/drift-parity.json`)
 * that cannot be remade because that interface is gone. Each state is scripted onto the React page and what it reads
 * is held to the recording. Every assertion that compared the two pages (the consent step's request count, the copies
 * and the copy requests of Steer back) is a recorded observation asserted against the React page's own.
 *
 * No model is ever called: the reading route is a double. Every request leaving the board's own origins is
 * refused. Run with `pnpm test:drift:browser`; `COMPASS_E2E_STEPS=<regex>` runs only the steps whose name
 * matches.
 */
import assert from 'node:assert/strict';
import { isDeepStrictEqual } from 'node:util';
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import {
  ASSESSMENT,
  HARNESS,
  POLICY,
  RECORD,
  ROUTE,
  SAVED,
  SID,
  FIRST_PRESS,
  check,
  fact,
  freshScript,
  installScript,
  postsTo,
} from './drift-board.mjs';
import { call, startIntentBoard } from './intent-board.mjs';
import { instrumentResources, recordClipboard, resources } from './sessions-board.mjs';
import { openPage, REPOSITORY } from './support/browser.mjs';
import { jsonSafe, normalise } from './support/golden.mjs';
import { awaitRecordRead } from './support/record.mjs';
import { copyProofPath } from './support/proof-copy.mjs';

/* Every fixed wait here means "give the page time to react". A hosted runner has a few shared cores and
   delivers events and frames later than a desktop, so each wait is tripled there; only a pass gets slower. A
   state is read once two reads a short while apart agree (`settled`), never after a fixed delay alone. */
const patience = (ms) => (process.env.CI ? ms * 3 : ms);
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';

const checkout = fileURLToPath(new URL('../../', import.meta.url));
const SHOTS = (process.env.COMPASS_SCREENSHOTS || `${checkout}docs/screenshots`).replace(
  /\/?$/,
  '/',
);
const golden = sessionDeviations('drift-parity');
/* The React reading in the stable form a recorded observation has, so the two compare as plain data. */
const norm = (value) => jsonSafe(normalise(value));
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

const E = encodeURIComponent;
const FRAGMENT = `#n=session:${E('w/alpha')}:${HARNESS}:${E(SID)}`;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
/* The card keys commit 4f6512bb and the send disclosure reworked after these recordings: the mark and its undo, the
   "What the analysis read" disclosure and the "What is sent" disclosure. Each step asserts its own React words. */
const REWORKED = ['text', 'buttons'];

/* ---- what a reader can read, reduced to data. These run IN the page, so they are self-contained. ---- */
const summarizeCard = () => {
  const norm = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : '');
  const liveCard = document.querySelector('.next-session-drift');
  if (!liveCard) return { missing: true, body: norm(document.body).slice(0, 200) };
  const card = liveCard.cloneNode(true);
  // The new jumps are proved separately; every retained word still compares with its recording.
  for (const jump of card.querySelectorAll('[data-next-cockpit-action="finding-jump"]'))
    jump.remove();
  // Closed native details retained their evidence and controls. Read each owned
  // keepMounted popup after its trigger in the snapshot, without opening or moving live nodes.
  const joined = new Set();
  for (;;) {
    const trigger = [...card.querySelectorAll('[data-slot="popover-trigger"]')].find(
      (node) => !joined.has(node),
    );
    if (!trigger) break;
    const panels = [...document.querySelectorAll('[data-slot="popover-content"]')].filter(
      (popup) => popup.getAttribute('aria-labelledby') === trigger.id,
    );
    if (!trigger.id || panels.length !== 1)
      throw new Error('A drift popover lost its trigger or uniquely labelled panel.');
    trigger.after(panels[0].cloneNode(true));
    joined.add(trigger);
  }
  /* Predates the one-column page (2026-10-19): the session More is retired and these parts now sit in the
     Drift card's head and the Intent card, so this lookup finds nothing until the proof is brought forward.
     The proof is on demand only; docs/design-reading-a-session.md#where-everything-in-more-went is the map. */
  const more = document.querySelector('[data-next-session-more]');
  const copy = (selector) => more?.querySelector(selector)?.cloneNode(true);
  const header = card.querySelector('.next-session-drift-head');
  const subtitle = copy('.next-session-drift-sub');
  if (subtitle) header.querySelector('.next-session-drift-titles').append(subtitle);
  const monitor = copy('.next-session-drift-monitor');
  if (monitor) header.append(monitor);
  if (
    monitor &&
    monitor.querySelector('[role="switch"]')?.getAttribute('aria-checked') === 'false' &&
    !card.querySelector('.next-cockpit-result,.next-cockpit-reading,.next-cockpit-reading-outcome')
  ) {
    const hint = [...more.querySelectorAll('p')].find((node) =>
      node.textContent.startsWith('Shows a level after every turn'),
    );
    if (hint) header.after(hint.cloneNode(true));
  }
  // Compare every retained word in the recorded order; the live placement has its own viewport proof.
  const primary = card.querySelector('[data-next-result-primary]');
  if (primary) {
    const result = card.querySelector('[data-next-result]');
    let foot = result.querySelector('.next-cockpit-result-press');
    if (!foot) {
      foot = document.createElement('div');
      foot.className = 'next-cockpit-result-press';
      result.querySelector('.next-cockpit-result-foot').before(foot);
    }
    const ask = foot.querySelector('.next-cockpit-reading-ask');
    if (ask) ask.prepend(...primary.children);
    else foot.prepend(primary);
    if (!primary.children.length) primary.remove();
  }
  const liveLevel = card.querySelector('.next-session-drift-live');
  const questionArea = card.querySelector(
    '.next-session-drift-check:has(.next-cockpit-direction-question)',
  );
  if (liveLevel && questionArea) questionArea.before(liveLevel);
  const question = card.querySelector('.next-cockpit-direction-question');
  const off = copy('[data-next-cockpit-action="reading-off"]');
  if (off) {
    const noReader = card.querySelector('.next-cockpit-reading-ask--none');
    const sent = card.querySelector('[data-slot="popover-content"]');
    const job = card.querySelector('.next-cockpit-reading-job');
    const consent = card.querySelector('.next-cockpit-reading-consent');
    if (question) question.querySelector('.next-cockpit-reading-ask').append(off);
    else if (noReader) noReader.append(off);
    else {
      const row = document.createElement('div');
      row.className = 'next-cockpit-reading-ask';
      row.append(off);
      if (sent) sent.append(row);
      else if (job || consent) (job || consent).after(row);
    }
  }
  // The departures section is not always a direct child of the card (the React page wraps it), so the
  // copied node goes before the card's child that holds it, never before a grandchild insertBefore rejects.
  const beforeDepartures = (node) => {
    const departures = card.querySelector('.next-cockpit-departures');
    const anchor = departures
      ? [...card.children].find((child) => child.contains(departures))
      : null;
    card.insertBefore(node, anchor ?? null);
  };
  for (const selector of ['.next-cockpit-conflict', '.next-session-drift-caveats']) {
    const node = copy(selector);
    if (node) beforeDepartures(node);
  }
  const button = (b) => [
    norm(b),
    b.getAttribute('data-next-cockpit-action') || '',
    b.getAttribute('aria-disabled') === 'true',
    b.getAttribute('aria-pressed'),
    b.hidden,
  ];
  return {
    heading: norm(card.querySelector('h2')),
    text: norm(card),
    buttons: [...card.querySelectorAll('button')]
      .filter((b) => !b.closest('.next-cockpit-held'))
      // A disclosure's trigger is a button now; the retired page's summary was not one.
      .filter((b) => !b.matches('[data-slot$="-trigger"]'))
      .map(button),
    resultStates: [...card.querySelectorAll('[data-next-result-state]')].map(
      (node) => node.dataset.nextResultState,
    ),
    steps: [...card.querySelectorAll('.next-cockpit-reading-step')].map((node) => [
      node.dataset.state,
      node.getAttribute('aria-current'),
    ]),
    analyzing: [...card.querySelectorAll('[data-next-analyzing]')].map(
      (node) => node.dataset.nextAnalyzing,
    ),
    absences: [...card.querySelectorAll('[data-absence]')].map((node) => [
      node.dataset.absence,
      norm(node),
    ]),
    stale: [...card.querySelectorAll('[data-next-result-stale]')].map(
      (node) => node.dataset.nextResultStale,
    ),
    delivery: [...card.querySelectorAll('[data-next-delivery]')].map((node) => [
      node.dataset.nextDelivery,
      node.dataset.nextDeliveryMixed || '',
    ]),
    levels: [...card.querySelectorAll('.next-session-drift-seg[data-on]')].length,
    pill: norm(document.querySelector('[data-next-drift-pill]')),
    // The page draws the activity list newest first and the recorded answer oldest first: restate the rows in
    // number order, on a copy, before comparing. The departure is recorded in docs/design-frontend-migration.md.
    work: (() => {
      const panel = document.querySelector('[data-next-cockpit-work]');
      if (!panel) return norm(panel);
      const copy = panel.cloneNode(true);
      // Reader-requested pages and their numbering note are new, asserted by the Record pages stories.
      copy.querySelector('[data-record-pages]')?.remove();
      const rows = copy.querySelector('.next-cockpit-work-rows');
      if (rows) {
        // Mounted members carry their own original words. Flatten folds only in the copy, then restore
        // the retired head and body time placement; new short marks and headers are asserted in stories.
        const entries = [...rows.querySelectorAll('[data-next-entry-id]')];
        for (const row of entries) {
          const head = row.querySelector('.next-cockpit-work-head');
          const body = row.querySelector('.next-cockpit-work-body');
          const time = row.querySelector('.next-cockpit-work-at');
          const lastTurn = row.querySelector('.next-cockpit-work-turn');
          const words = row.getAttribute('data-next-entry-words');
          if (words && head && body) {
            const flags = [...head.querySelectorAll('[data-next-entry-flag]')];
            head.replaceChildren(document.createTextNode(words), ...flags);
            const add = body.querySelector('[data-next-cockpit-action="direction-add"]');
            // The add control sits inside a wrapper on the React page, so the restated order puts each node before
            // the body's child that holds it (insertBefore rejects a grandchild).
            const before = add ? [...body.children].find((child) => child.contains(add)) : null;
            if (time) body.insertBefore(time, before ?? null);
            if (lastTurn) {
              lastTurn.textContent = 'from the last turn';
              body.insertBefore(lastTurn, before ?? null);
            }
          } else {
            // The same narrow recorded-side projection as recorded-activity.ts.
            const type = head?.querySelector('.next-cockpit-work-type');
            if (type?.textContent === 'Agent said') type.textContent = 'said';
          }
        }
        rows.replaceChildren(...entries.reverse());
      }
      copy.querySelector('[data-activity-legend]')?.remove();
      return norm(copy);
    })(),
    entries: [...document.querySelectorAll('[data-next-entry]')]
      .reverse()
      .map((node) => [node.dataset.nextEntry, node.dataset.nextEntryId]),
    meta: norm(document.querySelector('.next-session-detail-meta')),
  };
};

/* A duration, a clock time and a fact id differ between two loads a moment apart, and say the same
   thing about the reader's words either way. */
const comparable = (value) =>
  JSON.stringify(value)
    // Ids first: a hex id can hold a digit followed by d, which the age pattern below would otherwise take.
    .replace(/fact:[0-9a-f]{16}/g, '<fact>')
    // A call's moment is printed whole, with its date and seconds, and a recording must not carry the day it was made.
    .replace(/\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC/g, '<instant>')
    // No word boundary before the digits: a list row prints "exact" and its age with nothing between.
    .replace(/(?<!\d)\d+[smhd]( \d+[smh])?(?![A-Za-z0-9])/g, '<age>')
    .replace(/(?<!\d)\d\d:\d\d(?!\d)/g, '<clock>');

async function settled(read, { deadline = patience(6000), every = 120 } = {}) {
  let previous = comparable(await read());
  const until = Date.now() + deadline;
  for (;;) {
    await sleep(every);
    const next = comparable(await read());
    if (next === previous) return JSON.parse(next);
    previous = next;
    if (Date.now() > until) throw new Error('The page kept changing: ' + next.slice(0, 300));
  }
}

let mutationRoot = null;
if (process.env.DRIFT_MUTATION && process.env.DRIFT_MUTATION !== 'drop-consent')
  throw new Error(`Unknown drift mutation: ${process.env.DRIFT_MUTATION}`);
if (process.env.DRIFT_MUTATION === 'drop-consent') {
  mutationRoot = await mkdtemp(join(tmpdir(), 'compass-drift-consent-'));
  for (const folder of ['frontend', 'compass'])
    await cp(join(REPOSITORY, folder), join(mutationRoot, folder), {
      recursive: true,
      filter: copyProofPath,
    });
  await symlink(
    join(REPOSITORY, 'node_modules'),
    join(mutationRoot, 'node_modules'),
    process.platform === 'win32' ? 'junction' : 'dir',
  );
  const file = join(mutationRoot, 'frontend/src/drift/ReadingControl.tsx');
  const source = await readFile(file, 'utf8');
  assert.ok(source.includes('if (confirming) {'));
  await writeFile(file, source.replace('if (confirming) {', 'if (confirming && false) {'));
}
const board = await startIntentBoard({ root: mutationRoot || REPOSITORY });
const browser = await chromium.launch();
const origins = [board.react.origin, board.react.viteOrigin];
const opened = [];

async function newPage(viewport = { width: 1280, height: 900 }) {
  const o = await openPage(browser, origins, { viewport });
  await o.context.addInitScript(() => {
    globalThis.__announced = [];
  });
  await recordClipboard(o.context);
  await instrumentResources(o.context);
  o.script = freshScript();
  await installScript(o.context, o.script);
  opened.push(o);
  return o;
}

const expectsUnread = (o) =>
  o.script.contextError ||
  o.script.payload.annotate === false ||
  (o.script.work.omitted || []).some((row) => row.harness === HARNESS && row.sid === SID);

async function read(o, { expectUnread = expectsUnread(o) } = {}) {
  await awaitRecordRead(o.page, { expectUnread });
  return settled(() => o.page.evaluate(summarizeCard));
}

async function load(o, fragment = FRAGMENT, { expectUnread = expectsUnread(o) } = {}) {
  await o.page.goto('about:blank');
  await o.page.goto(`${board.react.origin}/${fragment}`);
  await o.page.waitForFunction(
    () =>
      document.querySelector('nav[aria-label="Primary"]') &&
      !/Waiting for the first board|first payload has not arrived/.test(document.body.innerText),
  );
  await o.page.waitForSelector('.next-session-drift');
  await awaitRecordRead(o.page, { expectUnread });
}

/* The real board's own clock, so every time in a state is relative to it. */
async function clockOf() {
  const real = await (await fetch(`${board.react.origin}/api/data`)).json();
  return real.generated;
}

async function setState(o, make) {
  const next = freshScript();
  Object.assign(next, await make(o));
  for (const key of Object.keys(o.script)) delete o.script[key];
  Object.assign(o.script, next);
}

try {
  const react = await newPage();

  /* ===================== DIFFERENTIAL: the card, state by state ===================== */
  async function compare(label, make, { skip = [], ready = null, restate = null } = {}) {
    const raw = golden.observe(`card: ${label}`);
    const recordUnread = /has not been read yet|record is unread rather than empty/.test(raw.work);
    // The recording is what the retired page said. `restate` changes only the words the React page is held to
    // differently, and `skip` names the keys a later change reworked; the step asserts those words itself.
    const old = restate ? restate(raw) : raw;
    const g = await clockOf();
    await setState(react, (o) => make(g, o));
    const draw = async (o) => {
      await load(o, FRAGMENT, { expectUnread: recordUnread });
      // A state the page reaches after a record read, said by what it draws rather than by a delay.
      if (ready) await o.page.waitForSelector(ready, { timeout: patience(15000) });
      return read(o, { expectUnread: recordUnread });
    };
    const mine = norm(await draw(react));
    const differing = [];
    for (const key of Object.keys(old)) {
      if (skip.includes(key)) continue;
      if (typeof old[key] === 'string' && typeof mine[key] === 'string' && old[key] !== mine[key]) {
        let at = 0;
        while (old[key][at] === mine[key][at]) at += 1;
        differing.push(
          `${key} at ${at}: recorded ${JSON.stringify(old[key].slice(Math.max(0, at - 60), at + 120))} / react ${JSON.stringify(mine[key].slice(Math.max(0, at - 60), at + 120))}`,
        );
      } else if (!isDeepStrictEqual(mine[key], old[key])) differing.push(key);
    }
    assert.ok(
      differing.length === 0,
      `the card differs from the recorded card (${label}): ${differing.join('; ')}`,
    );
    // What the React page reads, so a caller's assertion is about the page; equal to the recording wherever compared.
    return mine;
  }

  const claude = (g, extra = {}) => ({
    // The real board's own eligibility is cleared: the backend has no reading model, so it says Analyze is closed.
    session: {
      ...SAVED(g),
      state: 'idle',
      turn_end_at: g - 200,
      reading_eligibility: undefined,
      ...(extra.session || {}),
    },
    payload: {
      reading: POLICY,
      reading_routes: { claude: ROUTE },
      reading_check: 'accepted',
      reading_jobs: {},
      ...(extra.payload || {}),
    },
    facts: extra.facts ?? [],
    work: extra.work ?? {},
    routes: extra.routes ?? {},
    contextError: extra.contextError ?? false,
  });

  await step('no reading: Analyze is offered, with what is sent one click away', async () => {
    const state = await compare('no reading', (g) => claude(g));
    assert.ok(state.buttons.some(([label]) => label === 'Analyze drift'));
    assert.match(state.text, /What is sent/);
    return state.buttons.map(([label]) => label);
  });

  await step(
    'closed popover evidence mutations still fail the recorded card comparison',
    async () => {
      const g = await clockOf();
      await setState(react, () => claude(g));
      await load(react);
      const baseline = norm(await read(react));
      const recorded = golden.recorded('card: no reading');
      assert.equal(baseline.text, recorded.text);
      assert.deepEqual(baseline.buttons, recorded.buttons);
      const panel = await react.page.evaluateHandle(() => {
        const trigger = document.querySelector('.next-session-drift [data-slot="popover-trigger"]');
        if (!trigger?.id || trigger.getAttribute('aria-expanded') !== 'false')
          throw new Error('The mutation proof requires a closed, labelled popover.');
        const panels = [...document.querySelectorAll('[data-slot="popover-content"]')].filter(
          (popup) => popup.getAttribute('aria-labelledby') === trigger.id,
        );
        if (panels.length !== 1) throw new Error('The mutation proof requires one retained popup.');
        return panels[0];
      });
      const children = await panel.evaluateHandle((popup) => [...popup.childNodes]);
      try {
        for (const mutation of ['changed body', 'missing body']) {
          await panel.evaluate((popup, mutation) => {
            if (mutation === 'changed body')
              popup.prepend(document.createTextNode('Changed disclosure evidence.'));
            else popup.replaceChildren();
          }, mutation);
          try {
            const reading = norm(await react.page.evaluate(summarizeCard));
            assert.throws(() => assert.equal(reading.text, recorded.text), {
              code: 'ERR_ASSERTION',
            });
          } finally {
            await panel.evaluate((popup, original) => popup.replaceChildren(...original), children);
          }
        }
        await panel.evaluate((popup) => {
          popup.removeAttribute('aria-labelledby');
        });
        try {
          await assert.rejects(react.page.evaluate(summarizeCard), /uniquely labelled panel/);
        } finally {
          const id = await react.page
            .locator('.next-session-drift [data-slot="popover-trigger"]')
            .first()
            .getAttribute('id');
          await panel.evaluate((popup, id) => popup.setAttribute('aria-labelledby', id), id);
        }
        assert.deepEqual(norm(await read(react)), baseline);
      } finally {
        await children.dispose();
        await panel.dispose();
      }
      return ['changed body', 'missing body', 'missing labelled panel'];
    },
  );

  await step(
    'a refusal is said under the control that was pressed, in the recorded sentence',
    async () => {
      const state = await compare('model off', (g) =>
        claude(g, { payload: { reading: { reason: 'run-disabled', used: 0, limit: 10 } } }),
      );
      assert.match(state.text, /Model calls are off for this run/);
      assert.equal(
        state.absences.some(([kind]) => kind === 'run-config'),
        true,
      );
    },
  );

  await step(
    'an Allow is owed: Analyze offers the receiver one click away and sends nothing',
    async () => {
      const state = await compare('allow owed', (g) =>
        claude(g, { payload: { reading: FIRST_PRESS } }),
      );
      assert.match(state.text, /What is sent to Claude Code/);
    },
  );

  await step('no reader on this machine: the reason stands where the button would be', async () => {
    const state = await compare('no reader', (g) =>
      claude(g, {
        payload: {
          reading_routes: { claude: { provider: '', note: 'No claude binary was found.' } },
        },
      }),
    );
    assert.match(state.text, /No claude binary was found\./);
    assert.ok(!state.buttons.some(([label]) => label === 'Analyze drift'));
  });

  const JOB = (g, extra = {}) => ({
    id: 'job-1',
    phase: 'read',
    steps: [
      { phase: 'collect', text: 'Collecting the record' },
      { phase: 'read', text: 'Reading it' },
      { phase: 'write', text: 'Writing the result' },
    ],
    ...extra,
  });

  await step(
    'a running analysis draws its steps and Cancel; a cancelling one keeps Cancel inert',
    async () => {
      const running = await compare('running', (g) =>
        claude(g, {
          session: { state: 'working' },
          payload: { reading_jobs: { [`${HARNESS}:${SID}`]: JOB(g) } },
        }),
      );
      assert.deepEqual(
        running.steps.map(([s]) => s),
        ['done', 'active', 'todo'],
      );
      assert.deepEqual(running.analyzing, ['job-1']);
      const cancelling = await compare('cancelling', (g) =>
        claude(g, {
          session: { state: 'working' },
          payload: { reading_jobs: { [`${HARNESS}:${SID}`]: JOB(g, { cancelling: true }) } },
        }),
      );
      assert.ok(cancelling.buttons.some(([label, , inert]) => label === 'Cancel' && inert));
    },
  );

  const stored = (g, extra = {}) =>
    claude(g, {
      ...extra,
      session: {
        annotation_assessment: ASSESSMENT(g),
        annotation_reading_count: 1,
        ...(extra.session || {}),
      },
      facts: extra.facts ?? RECORD(g),
    });

  await step(
    'a stored result: the answer, each line by the list’s number, where the work went',
    async () => {
      // The card's text and buttons are not compared: the mark, its undo and the "What the analysis read" disclosure
      // were reworked after this recording (commit 4f6512bb). ReadingResult.test.tsx holds the result's states.
      const state = await compare('stored result', (g) => stored(g), { skip: REWORKED });
      assert.match(state.text, /Departs from your intent1 departure/);
      // Sorted as a copy: a golden observation is the stored value itself, and sorting it would change the recording.
      assert.deepEqual([...state.resultStates].sort(), ['consistent', 'departs']);
      assert.ok(state.entries.length >= 2);
      assert.ok(!state.buttons.some(([label]) => label === 'Analyze again'));
      assert.equal(await react.page.locator('[data-next-cockpit-action="reading-ask"]').count(), 0);
      return state.resultStates;
    },
  );

  await step('a result marked not accurate draws marked, and a withheld one says why', async () => {
    // The text and buttons are not compared: the mark's words were reworked after this recording (commit 4f6512bb).
    // ReadingResult.test.tsx holds these sentences and DriftAnalysisResult.stories.tsx the mark and its undo.
    const marked = await compare(
      'not accurate',
      (g) => stored(g, { session: { annotation_not_accurate: true } }),
      {
        skip: REWORKED,
      },
    );
    assert.match(
      marked.text,
      /Marked inaccurate\. This analysis no longer sets the drift level or Steer back/,
    );
    assert.match(marked.text, /Drift level hidden because you marked this analysis inaccurate\./);
    const withheld = await compare('withheld', (g) =>
      claude(g, {
        session: {
          annotation_reading_withheld: 'The analysis was cancelled.',
          annotation_reading_withheld_at: g - 120,
          annotation_reading_count: 1,
        },
      }),
    );
    assert.match(withheld.text, /Last analysis, .* ago: The analysis was cancelled\./);
  });

  await step(
    'a reading this build cannot read, and one it refused, say so and draw no verdict',
    async () => {
      const odd = await compare('unknown field', (g) =>
        stored(g, { session: { annotation_assessment: ASSESSMENT(g, { surprise: true }) } }),
      );
      assert.match(odd.text, /cannot read the reading it was given/);
      assert.deepEqual(odd.resultStates, []);
      const refused = await compare('refused', (g) =>
        claude(g, { session: { annotation_reading_refused: true, annotation_reading_count: 1 } }),
      );
      assert.match(refused.text, /this build could not read it/);
    },
  );

  await step(
    'a reading of earlier words says so, and offers Analyze again in the callout',
    async () => {
      // The text and buttons are not compared: the card's words were reworked after this recording (`Mark as
      // inaccurate`, `What the analysis read`, commit 4f6512bb). The callout's words and its one Analyze again are
      // asserted here and in ReadingResult.test.tsx ("says a reading of earlier words is of earlier words").
      const state = await compare(
        'superseded',
        (g) => stored(g, { session: { annotation_revision: 4, annotation_revision_count: 4 } }),
        { skip: REWORKED },
      );
      assert.deepEqual(state.stale, ['intent']);
      assert.match(state.text, /Your intent changed after this analysis\./);
      assert.match(state.text, /Revision 4 is current/);
      assert.equal(await react.page.locator('[data-next-cockpit-action="reading-ask"]').count(), 1);
      const work = await compare(
        'new work',
        (g) =>
          stored(g, {
            facts: [
              ...RECORD(g),
              check('c3', g - 100, 'passed'),
              fact('m1', g - 90, { type: 'agent_message', by: 'agent' }),
            ],
          }),
        // The activity panel labels an agent message "said" with the speaker beside it, which WorkListView.test.tsx
        // ("reads Agent said once") holds; the recording says "Agent said". Its count line is asserted below.
        { skip: [...REWORKED, 'work'] },
      );
      assert.match(work.work, /4 entries · 1 message the agent wrote/);
      assert.deepEqual(work.stale, ['work']);
      assert.equal(await react.page.locator('[data-next-cockpit-action="reading-ask"]').count(), 1);
      assert.match(work.text, /New work since this analysis/);
    },
  );

  await step(
    'finding jumps resolve fact ids after renumbering without requests or launches',
    async () => {
      const g = await clockOf();
      await setState(react, () => stored(g));
      await load(react);
      await read(react);
      await react.page.emulateMedia({ reducedMotion: 'reduce' });
      await react.page.evaluate(() => {
        globalThis.__findingScrolls = [];
        const scroll = Element.prototype.scrollIntoView;
        Element.prototype.scrollIntoView = function (options) {
          globalThis.__findingScrolls.push({
            id: this.getAttribute('data-next-entry-id'),
            options,
          });
          return scroll.call(this, options);
        };
      });
      const choose = async (key, id, number, words, activation) => {
        const requests = [...react.log.nonGet];
        const before = await resources(react.page);
        const posts = react.script.posts.length;
        await react.page.locator(`[data-next-finding="${key}"]`).focus();
        await react.page.keyboard.press(activation);
        const row = react.page.locator(`[data-next-entry-id="${id}"]`);
        await row.locator('[data-next-finding-entry]').waitFor();
        assert.match(await row.innerText(), new RegExp(`Cited for “${words}” · #${number}`));
        assert.equal(await row.evaluate((node) => document.activeElement === node), true);
        assert.equal(
          await row.evaluate((node) => {
            const box = node.getBoundingClientRect();
            return box.top >= 0 && box.bottom <= innerHeight;
          }),
          true,
        );
        // A board GET may coincide with a jump; only a mutation or launch would violate the contract.
        await react.page.evaluate(() => fetch('/api/data'));
        assert.deepEqual(await resources(react.page), before);
        assert.equal(react.script.posts.length, posts);
        assert.deepEqual(react.log.nonGet, requests);
        assert.equal(await react.page.locator('[data-next-finding-entry]').count(), 1);
      };
      const names = await react.page
        .locator('[data-next-finding]')
        .evaluateAll((buttons) => buttons.map((button) => button.getAttribute('aria-label')));
      assert.deepEqual(names, [
        'Show #1 in Full activity for Goal: Ship the queue worker',
        'Show #2 in Full activity for Expected outcome line 1: Tests pass',
      ]);
      assert.equal(new Set(names).size, names.length);
      for (const name of names)
        assert.equal(await react.page.getByRole('button', { name, exact: true }).count(), 1);
      await choose('goal', 'c1', 1, 'It stopped running the tests.', 'Enter');
      await choose('line_1', 'c2', 2, 'Tests pass', 'Space');
      assert.equal(
        await react.page.locator('[data-next-entry-id="c1"] [data-next-finding-entry]').count(),
        0,
      );
      assert.deepEqual(
        await react.page.evaluate(() =>
          globalThis.__findingScrolls.map((row) => row.options.behavior),
        ),
        ['instant', 'instant'],
      );
      await setState(react, () =>
        stored(g, {
          facts: [
            check('c2', g - 650, 'passed'),
            check('c1', g - 600, 'failed', { result_source: 'failed flag' }),
          ],
        }),
      );
      await load(react);
      await read(react);
      await choose('goal', 'c1', 2, 'It stopped running the tests.', 'Enter');
      await setState(react, () =>
        stored(g, {
          facts: RECORD(g),
          session: {
            annotation_assessment: ASSESSMENT(g, {
              criteria: {
                goal: {
                  result: 'departure',
                  cites: ['gone'],
                  detail: 'Old account',
                  clause: 'Ship the queue worker',
                },
              },
            }),
          },
        }),
      );
      await load(react);
      await read(react);
      const unresolved = react.page.locator('[data-next-result-goal]');
      await unresolved.getByRole('button', { name: 'Evidence', exact: true }).click();
      await unresolved.getByText(/Nothing resolvable was cited/).waitFor();
      assert.match(await unresolved.innerText(), /Nothing resolvable was cited/);
      assert.equal(await react.page.locator('[data-next-finding]').count(), 0);
      assert.equal(await react.page.locator('[data-next-finding-entry]').count(), 0);
      await react.page.emulateMedia({ reducedMotion: 'no-preference' });
    },
  );

  await step('a gap in the record is said as a gap, never as an empty record', async () => {
    /* The previous interface and this page both say the record is absent, in the words of what happened. It read
       only the focused session's context, so its failure left the record "not read yet"; this page also reads the
       project's (the Intent step does, for its later directions), so the same failure is "could not be read".
       Neither is an empty record. */
    const g0 = await clockOf();
    await setState(react, () => claude(g0, { contextError: true }));
    await load(react);
    const unreadReact = norm(await read(react));
    const unreadRecorded = golden.observe('gap: the record could not be read');
    const unread = [unreadRecorded, unreadReact];
    assert.match(unread[0].work, /has not been read yet/);
    assert.match(unread[1].work, /could not be read/);
    assert.ok(
      unread.every(
        (state) => !/No entry in the observed record names this session/.test(state.work),
      ),
    );
    const partial = await compare('outside the scan', (g) =>
      claude(g, {
        work: {
          omitted: [{ harness: HARNESS, sid: SID }],
        },
      }),
    );
    assert.match(partial.work, /outside the observed-record scan/);
  });

  await step(
    'the departures section: lane on and off, raises on record, delivery and counts',
    async () => {
      const row = (g) => ({
        constraint: 'TYPED GOAL',
        at: g - 400,
        clause: 'Ship the queue worker',
        reading: 'It stopped running the tests.',
        revision: 2,
        cutoff: g - 380,
        evidence: 'pytest failed',
      });
      const raised = await compare('raises', (g) =>
        claude(g, {
          payload: { unasked: true, delivery_counts: { raises: 3, attempted: 3, handed_over: 2 } },
          session: {
            departures: [row(g)],
            departure_checked: true,
            delivery_departure: {
              delivery_raises: 1,
              delivery_outcome: 'handed-over',
              delivery_why: 'A notification service accepted it.',
            },
          },
        }),
      );
      assert.match(raised.text, /Raised while you were away: 1/);
      assert.deepEqual(raised.delivery, [['handed-over', '']]);
      const off = await compare('lane off', (g) =>
        claude(g, {
          payload: { unasked: false, unasked_off_reason: 'run-disabled' },
          session: { departures: [row(g)] },
        }),
      );
      assert.match(off.text, /model off switch refuses unasked checks/);
      const checked = await compare('lane on, nothing raised', (g) =>
        claude(g, {
          payload: { unasked: true },
          session: { departures: [], departure_why: 'Not checked yet.' },
        }),
      );
      assert.match(checked.text, /Not checked yet\./);
    },
  );

  await step(
    'a later direction is asked about before the press, with Analyze behind Keep',
    async () => {
      // The text and buttons are not compared: the recorded card paints the send disclosure as a sentence under the
      // buttons, and the page draws it under "What is sent" (DriftReadability.test.tsx).
      const state = await compare(
        'question',
        (g) =>
          claude(g, {
            facts: [fact('d1', g - 100, { summary: 'Keep the flag off by default.' })],
            session: { annotation_goal_saved_at: g - 600 },
          }),
        { skip: REWORKED },
      );
      assert.ok(state.buttons.some(([label]) => label === 'Keep my intent and analyze'));
      assert.ok(!state.buttons.some(([label]) => label === 'Analyze drift'));
      const owed = await compare(
        'question, an Allow owed',
        (g) =>
          claude(g, {
            payload: { reading: FIRST_PRESS },
            facts: [fact('d1', g - 100, { summary: 'Keep the flag off by default.' })],
          }),
        { skip: REWORKED },
      );
      assert.ok(owed.buttons.some(([label]) => label === 'Keep my intent'));
    },
  );

  await step(
    'with annotations off the check stays on the page, inert, with its one refusal',
    async () => {
      // The retired page gated the observed record behind annotations, so it said "has not been read yet". The
      // server publishes the session's context whether annotations are on or not (only the analysis levels are
      // gated, http_api.py), so this page read the record and its sentence is the one for a read record with no
      // entry naming this session. That is restated here; the rest of the card is held to the recording.
      const state = await compare(
        'annotations off',
        (g) => claude(g, { payload: { annotate: false, reading_check: 'not-run' } }),
        {
          restate: (old) => ({
            ...old,
            // The same read record, counted in the session's meta line: no entry names this session.
            meta: `${old.meta} · 0 entries`,
            work: old.work.replace(
              'The observed record for this session has not been read yet.',
              'No entry in the observed record names this session.',
            ),
          }),
        },
      );
      assert.match(state.text, /Annotations are off for this run/);
      assert.match(state.work, /^No entry in the observed record names this session\./);
    },
  );

  await step(
    'pressing Analyze where an Allow is owed asks for it, naming the receiver, and sends nothing',
    async () => {
      const g = await clockOf();
      await setState(react, () => claude(g, { payload: { reading: FIRST_PRESS } }));
      await load(react);
      await react.page.locator('[data-next-cockpit-action="reading-ask"]').click();
      const old = golden.observe('consent: the step');
      const mine = norm(await read(react));
      assert.deepEqual(mine, old, 'the consent step differs from the recorded step');
      assert.match(old.text, /Send this session to Claude Code for analysis\?/);
      /* Predates the one-column page (2026-10-19): the Allow and analyze step is retired and a press writes
         no Allow, so this fails when the proof is run on demand until it is brought forward to the notice a
         first Analyze drift shows. */
      assert.deepEqual(
        old.buttons.filter(([label]) => ['Allow and analyze', 'Not now'].includes(label)).length,
        2,
      );
      const recordedSent = golden.observe('consent: reading requests the legacy page sent');
      assert.equal(recordedSent + postsTo(react.script, '/api/reading').length, 0);
      await react.page.locator('[data-next-cockpit-action="reading-not-now"]').click();
      const after = golden.observe('consent: after Not now');
      const again = norm(await read(react));
      assert.deepEqual(again, after);
      assert.ok(after.buttons.some(([label]) => label === 'Analyze drift'));
    },
  );

  await step(
    'Steer back opens the correction with its numbers filled in, and Copy records it once',
    async () => {
      const g = await clockOf();
      const PARTS = ['Your last check failed', { entry: 'c1' }, '. Fix it, then say so.'];
      await setState(react, () =>
        stored(g, {
          routes: {
            '/api/correction': () => ({ body: { ok: true, parts: PARTS } }),
            '/api/correction/copied': () => ({ body: { ok: true } }),
          },
        }),
      );
      await load(react);
      await react.page.locator('[data-next-cockpit-action="steer-back"]').click();
      await react.page.waitForSelector('#next-cockpit-correction');
      const recordedBox = golden.observe('steer: the box');
      const retiredText = golden.observe('steer: the correction text');
      // A named departure (owner, 2026-10-14): a number reads "(entry #n in Compass's activity list)", where
      // the recording says "(#n in Compass)". Only that wording is restated; docs/design-frontend-migration.md
      // owns the record of it.
      const recordedText = retiredText.replace(
        '(#1 in Compass)',
        "(entry #1 in Compass's activity list)",
      );
      // Only the box's own keys are compared: the card around it was reworked after this recording (the mark and
      // its undo, commit 4f6512bb), so its text and buttons are not. SteerBack.test.tsx holds the count and the copy.
      const mine = norm(await read(react));
      for (const key of Object.keys(recordedBox))
        if (!REWORKED.includes(key))
          assert.deepEqual(mine[key], recordedBox[key], `the steer box differs in ${key}`);
      assert.match(mine.text, new RegExp(`${recordedText.length}/2000`));
      const text = await react.page.locator('#next-cockpit-correction').inputValue();
      assert.equal(text, recordedText);
      assert.match(
        text,
        /Your last check failed \(entry #1 in Compass's activity list\)\. Fix it, then say so\./,
      );
      await react.page.locator('[data-next-cockpit-action="correction-copy"]').click();
      await sleep(patience(300));
      const copied = await react.page.evaluate(() => globalThis.__copied);
      const recordedCopied = golden
        .observe('steer: what the legacy page copied')
        .map((value) => value.replace('(#1 in Compass)', "(entry #1 in Compass's activity list)"));
      assert.deepEqual(copied, recordedCopied);
      assert.equal(recordedCopied.length, 1);
      const recordedRequests = golden.observe('steer: copy requests the legacy page sent');
      assert.equal(recordedRequests, 1);
      assert.equal(postsTo(react.script, '/api/correction/copied').length, 1);
      assert.equal(postsTo(react.script, '/api/correction').length, 1);
    },
  );

  await step('the live estimate and the header pill read as the recording does', async () => {
    const g = await clockOf();
    const make = (g2) =>
      claude(g2, {
        session: { annotation_revision: 3 },
        work: {
          live_levels: [
            {
              harness: HARNESS,
              sid: SID,
              level: 'high',
              revision: 3,
              computed_at: g2 - 60,
              reasons: ['failed-check', 'no-passing-check'],
              cites: ['c1'],
              rose_from: 'medium',
              rose_at: 'c1',
            },
          ],
        },
        facts: RECORD(g2),
      });
    await setState(react, () => make(g));
    const arm = async (o) => {
      await o.context.addInitScript(
        ([harness, sid]) => {
          globalThis.localStorage.setItem(`compass.next.live-estimate:${harness}:${sid}`, '1');
        },
        [HARNESS, SID],
      );
      await load(o);
      return read(o);
    };
    const mine = norm(await arm(react));
    const recorded = golden.observe('live estimate and pill');
    // A named departure (owner, 2026-10-14): the line also says shell-written files are not seen.
    const old = {
      ...recorded,
      text: recorded.text.replace(
        'Reads checks and file paths, not what your intent says.',
        'Reads checks and file paths, not what your intent says. Files written by shell commands, such as a build, are not seen.',
      ),
    };
    assert.deepEqual(mine, old, 'the live estimate differs from the recording');
    assert.match(old.pill, /Drift: High/);
    assert.match(old.text, /Live estimate/);
  });
  /* ===================== BEHAVIOUR: nothing starts on its own ===================== */
  /* The board's own revision, moved from outside the page: another session's words are saved, the backend's
     revision advances and the stream announces it, so what the page receives it was told, not asked for. */
  let tickNumber = 0;
  async function tick(o) {
    const before = o.counts().data;
    tickNumber += 1;
    const data = (await call(board.react.origin, 'GET', '/api/data')).body;
    const row = data.sessions.find((x) => x.sid === 'intent-3');
    await call(board.react.origin, 'POST', '/api/annotate', {
      harness: 'claude',
      sid: 'intent-3',
      goal: `tick ${tickNumber}`,
      expected_revision: row.annotation_revision || 0,
    });
    await call(board.react.origin, 'GET', '/api/data');
    const until = Date.now() + patience(15000);
    while (o.counts().data <= before && Date.now() < until) await sleep(100);
    assert.ok(o.counts().data > before, 'the page never received the new board revision');
    await sleep(patience(200));
  }
  const apply = async (o, make) => {
    const g = await clockOf();
    const next = freshScript();
    Object.assign(next, await make(g));
    // What the page has already sent is a record of the page, not of the state, so it is kept.
    next.posts = o.script.posts;
    for (const key of Object.keys(o.script)) delete o.script[key];
    Object.assign(o.script, next);
  };
  const ANNOUNCE = '#next-cockpit-cue-status';
  const said = (o) => o.page.locator(ANNOUNCE).textContent();

  await step(
    'no reading, cancel or correction request leaves the page from a mount, a poll, a route change, a hover, a focus or a keypress',
    async () => {
      await apply(react, (g) => claude(g));
      await load(react);
      await read(react);
      react.reset();
      react.script.posts.length = 0;
      const ask = react.page.locator('[data-next-cockpit-action="reading-ask"]');
      for (let i = 0; i < 3; i += 1) await tick(react);
      await ask.hover();
      await ask.focus();
      await react.page.keyboard.press('Shift');
      await react.page.keyboard.press('a');
      await react.page.mouse.move(5, 5);
      for (let round = 0; round < 2; round += 1) {
        await react.page.evaluate(() => {
          location.hash = '#n=intent';
        });
        await react.page.waitForSelector('[data-next-view-body="intent"]');
        await react.page.evaluate((hash) => {
          location.hash = hash;
        }, FRAGMENT);
        await backOnTheSession(react);
      }
      await read(react);
      assert.deepEqual(react.log.nonGet, []);
      assert.deepEqual(react.script.posts, []);
      const r = await resources(react.page);
      assert.ok(r.sources <= 1, `${r.sources} streams are open`);
      return { requests: react.log.requests.length };
    },
  );

  async function backOnTheSession(o) {
    await o.page
      .waitForSelector('.next-session-drift', { timeout: patience(8000) })
      .catch(async (error) => {
        const where = await o.page.evaluate(
          () => `${location.href} | ${document.body.innerText.slice(0, 300)}`,
        );
        throw new Error(`${error.message} at ${where}`);
      });
    await awaitRecordRead(o.page, { expectUnread: expectsUnread(o) });
  }

  const deferred = () => {
    let release;
    const promise = new Promise((resolve) => {
      release = resolve;
    });
    return { promise, release };
  };

  await step(
    'one press sends one request, however it is pressed, and nothing retries it or restarts it under StrictMode',
    async () => {
      const gate = deferred();
      await apply(react, (g) =>
        claude(g, {
          routes: {
            '/api/reading': async () => {
              await gate.promise;
              return { body: { ok: true, job: JOB(g) } };
            },
          },
        }),
      );
      await load(react);
      await read(react);
      react.script.posts.length = 0;
      const ask = react.page.locator('[data-next-cockpit-action="reading-ask"]');
      await ask.focus();
      await react.page.keyboard.press('Enter');
      await react.page.keyboard.press('Enter');
      await react.page.keyboard.press('Space');
      await ask.click({ force: true });
      await ask.dblclick({ force: true });
      await sleep(patience(300));
      assert.equal(
        postsTo(react.script, '/api/reading').length,
        1,
        'more than one reading request left',
      );
      const body = postsTo(react.script, '/api/reading')[0].body;
      assert.equal(body.press, true);
      assert.equal(body.observer_model, 1);
      assert.equal(body.provider, 'claude');
      assert.equal(body.expected_revision, 3);
      assert.ok(!('allow' in body), 'an Allow was sent although none was owed');
      // The button is busy, not gone, and still holds focus.
      assert.equal(await ask.getAttribute('aria-busy'), 'true');
      // A poll while it is open sends nothing more.
      await tick(react);
      await tick(react);
      assert.equal(postsTo(react.script, '/api/reading').length, 1);
      // The server answers: the board now holds the job, and the box is the answer.
      await apply(react, (g) =>
        claude(g, {
          session: { state: 'working' },
          payload: { reading_jobs: { [`${HARNESS}:${SID}`]: JOB(g) } },
          routes: react.script.routes,
        }),
      );
      gate.release();
      await tick(react);
      await react.page.waitForSelector('[data-next-analyzing="job-1"]');
      assert.equal(postsTo(react.script, '/api/reading').length, 1);
      // Said once, when the box was first drawn by a tab that watched it begin.
      assert.equal(await said(react), 'Analyzing drift');
      await tick(react);
      assert.equal(await said(react), 'Analyzing drift');
      return 'one request';
    },
  );

  await step('a keyboard-started analysis keeps focus on its result after completion', async () => {
    const gate = deferred();
    await apply(react, (g) =>
      claude(g, {
        routes: {
          '/api/reading': async () => {
            await gate.promise;
            return { body: { ok: true, job: JOB(g) } };
          },
        },
      }),
    );
    await load(react);
    await read(react);
    const ask = react.page.locator('[data-next-cockpit-action="reading-ask"]');
    await ask.focus();
    await react.page.keyboard.press('Enter');
    await apply(react, (g) =>
      claude(g, {
        payload: { reading_jobs: { [`${HARNESS}:${SID}`]: JOB(g) } },
        routes: react.script.routes,
      }),
    );
    gate.release();
    await tick(react);
    const title = react.page.locator('.next-cockpit-reading-job-title');
    await title.waitFor();
    assert.equal(await title.evaluate((node) => node === document.activeElement), true);
    await apply(react, (g) => stored(g));
    await tick(react);
    const heading = react.page.locator('[data-next-result-heading]');
    await heading.waitFor();
    assert.equal(await heading.evaluate((node) => node === document.activeElement), true);
    assert.equal(await heading.evaluate((node) => node.tagName), 'H3');
    assert.equal(await react.page.locator('[data-next-cockpit-action="reading-ask"]').count(), 0);
  });

  await step(
    'Cancel names the job, sends one request, and the server’s cancelling flag survives a reload',
    async () => {
      const gate = deferred();
      await apply(react, (g) =>
        claude(g, {
          session: { state: 'working' },
          payload: { reading_jobs: { [`${HARNESS}:${SID}`]: JOB(g) } },
          routes: {
            '/api/reading/cancel': async () => {
              await gate.promise;
              return { status: 202, body: { ok: true, cancelling: true } };
            },
          },
        }),
      );
      await load(react);
      await react.page.waitForSelector('[data-next-analyzing]');
      react.script.posts.length = 0;
      const cancel = react.page.locator('[data-next-cockpit-action="reading-cancel"]');
      await cancel.focus();
      await react.page.keyboard.press('Enter');
      await react.page.keyboard.press('Enter');
      await cancel.click({ force: true });
      await sleep(patience(300));
      const posts = postsTo(react.script, '/api/reading/cancel');
      assert.equal(posts.length, 1);
      assert.deepEqual(posts[0].body, {
        harness: HARNESS,
        sid: SID,
        job: 'job-1',
        press: true,
        observer_model: 1,
      });
      await apply(react, (g) =>
        claude(g, {
          session: { state: 'working' },
          payload: { reading_jobs: { [`${HARNESS}:${SID}`]: JOB(g, { cancelling: true }) } },
        }),
      );
      gate.release();
      await tick(react);
      await react.page.reload();
      await react.page.waitForSelector('[data-next-analyzing]');
      assert.equal(
        await react.page
          .locator('[data-next-cockpit-action="reading-cancel"]')
          .getAttribute('aria-disabled'),
        'true',
      );
    },
  );

  await step('the end of a watched analysis is announced once, in the server’s words', async () => {
    await apply(react, (g) => claude(g, { payload: {} }));
    await load(react);
    await read(react);
    await apply(react, (g) =>
      claude(g, {
        session: { state: 'working' },
        payload: { reading_jobs: { [`${HARNESS}:${SID}`]: JOB(g) } },
      }),
    );
    await tick(react);
    await react.page.waitForSelector('[data-next-analyzing]');
    assert.equal(await said(react), 'Analyzing drift');
    await apply(react, (g) => stored(g));
    await tick(react);
    await react.page.waitForSelector('[data-next-result]');
    assert.equal(await said(react), 'The analysis finished. Its result is in the Drift section.');
    await apply(react, (g) =>
      claude(g, {
        session: {
          annotation_reading_withheld: 'The analysis was cancelled.',
          annotation_reading_count: 1,
        },
      }),
    );
    await tick(react);
    await read(react);
    // No job was in play, so there is nothing new to say: the last word stays the last thing said.
    assert.equal(await said(react), 'The analysis finished. Its result is in the Drift section.');
  });

  await step(
    'the consent step is the only place an Allow is sent from, and a changed destination refuses it',
    async () => {
      await apply(react, (g) =>
        claude(g, {
          payload: { reading: FIRST_PRESS },
          routes: {
            '/api/reading': () => ({
              status: 409,
              body: { ok: false, reason: 'destination-changed' },
            }),
          },
        }),
      );
      await load(react);
      await read(react);
      react.script.posts.length = 0;
      await react.page.locator('[data-next-cockpit-action="reading-ask"]').click();
      await react.page.waitForSelector('.next-cockpit-reading-consent');
      await sleep(patience(200));
      assert.equal(
        postsTo(react.script, '/api/reading').length,
        0,
        'the first press sent without an Allow',
      );
      // The heading holds focus, so a second Enter cannot give consent unread.
      assert.equal(
        await react.page.evaluate(() => document.activeElement?.id),
        'next-cockpit-reading-consent-title',
      );
      await react.page.keyboard.press('Enter');
      await sleep(patience(200));
      assert.equal(postsTo(react.script, '/api/reading').length, 0);
      /* Predates the one-column page (2026-10-19): the reading-allow action is retired and a press writes no
         Allow, so this fails when the proof is run on demand until it is brought forward to the notice a
         first Analyze drift shows. */
      await react.page.locator('[data-next-cockpit-action="reading-allow"]').click();
      await sleep(patience(400));
      const sent = postsTo(react.script, '/api/reading');
      assert.equal(sent.length, 1);
      assert.equal(sent[0].body.allow, true);
      assert.equal(sent[0].body.words_destination, 'api');
      assert.equal(sent[0].body.tool_output, 'api');
      assert.match(
        await react.page.locator('.next-session-drift').textContent(),
        /Where this session would be sent changed/,
      );
      await sleep(patience(600));
      assert.equal(postsTo(react.script, '/api/reading').length, 1, 'a refused press was retried');
    },
  );
  /* ===================== BEHAVIOUR: the correction's native editor ===================== */
  const PARTS = ['Your last check failed', { entry: 'c1' }, '. Fix it, then say so.'];
  const steerState = (g, extra = {}) =>
    stored(g, {
      ...extra,
      routes: {
        '/api/correction': () => ({ body: { ok: true, parts: PARTS } }),
        '/api/correction/copied': () => ({ body: { ok: true } }),
        ...(extra.routes || {}),
      },
    });
  const BOX = '#next-cockpit-correction';
  const mark = (o, selector, name) =>
    o.page.locator(selector).evaluate((node, key) => {
      globalThis.__marks ??= {};
      globalThis.__marks[key] = node;
    }, name);
  const same = (o, selector, name) =>
    o.page.locator(selector).evaluate((node, key) => globalThis.__marks[key] === node, name);
  const caretOf = (o) =>
    o.page.locator(BOX).evaluate((node) => ({
      value: node.value,
      start: node.selectionStart,
      end: node.selectionEnd,
      focused: document.activeElement === node,
    }));
  async function openSteer(o, extra = {}) {
    await apply(o, (g) => steerState(g, extra));
    await load(o);
    await read(o);
    o.script.posts.length = 0;
    await o.page.locator('[data-next-cockpit-action="steer-back"]').click();
    await o.page.waitForSelector(BOX);
    await o.page.waitForFunction(
      (selector) => document.activeElement === document.querySelector(selector),
      BOX,
    );
  }

  await step(
    'the correction box keeps its node, text, caret, selection, focus and native undo through the board’s own revisions',
    async () => {
      await openSteer(react);
      await mark(react, BOX, 'box');
      await react.page.keyboard.press(`${MOD}+a`);
      await react.page.keyboard.type('hello brave world');
      for (let i = 0; i < 5; i += 1) await react.page.keyboard.press('ArrowLeft');
      await react.page.keyboard.type('X');
      await react.page.keyboard.press('ArrowLeft');
      await react.page.keyboard.press('Shift+ArrowLeft');
      await react.page.keyboard.press('Shift+ArrowLeft');
      const before = await caretOf(react);
      assert.equal(before.value, 'hello brave Xworld');
      // New work lands, and a running analysis: boards that would redraw the card under the reader.
      await apply(react, (g) =>
        steerState(g, { facts: [...RECORD(g), check('c9', g - 20, 'passed')] }),
      );
      for (let i = 0; i < 3; i += 1) await tick(react);
      assert.equal(await same(react, BOX, 'box'), true, 'the box was replaced');
      assert.deepEqual(await caretOf(react), before);
      // The board that arrived waits, and the box says so.
      assert.equal(await react.page.locator('[data-next-result-stale]').count(), 0);
      assert.match(
        await react.page.locator('[data-next-correction-paint-why]').textContent(),
        /Updates are paused while you edit this correction/,
      );
      // Native undo takes back the last edit, and only that.
      await react.page.keyboard.press(`${MOD}+z`);
      assert.equal((await caretOf(react)).value, 'hello brave world');
      await react.page.keyboard.press(`${MOD}+Shift+z`);
      assert.equal((await caretOf(react)).value, 'hello brave Xworld');
      // Leaving the box shows the newest board.
      await react.page.locator('.next-session-drift-heading').click();
      await react.page.waitForSelector('[data-next-result-stale="work"]');
      // The stale mark moves the box in the layout, which the reader has left; the words are theirs and stay.
      assert.equal(await react.page.locator('[data-next-correction-paint-why]').isHidden(), true);
      assert.equal((await caretOf(react)).value, 'hello brave Xworld');
    },
  );

  await step(
    'a focused, untouched correction box keeps its node, caret and selection when a stale mark would move it',
    async () => {
      await openSteer(react);
      await mark(react, BOX, 'box');
      await react.page.locator(BOX).evaluate((node) => {
        node.focus();
        node.setSelectionRange(2, 7);
      });
      await apply(react, (g) =>
        steerState(g, { facts: [...RECORD(g), check('c9', g - 20, 'passed')] }),
      );
      await tick(react);
      await tick(react);
      assert.equal(await same(react, BOX, 'box'), true, 'the stale mark replaced the box');
      const caret = await caretOf(react);
      assert.deepEqual([caret.start, caret.end, caret.focused], [2, 7, true]);
      assert.equal(await react.page.locator('[data-next-result-stale]').count(), 0);
      // Leaving it shows the board.
      await react.page.locator('.next-session-drift-heading').click();
      await react.page.waitForSelector('[data-next-result-stale="work"]');
    },
  );

  await step('a composition is never cut, copied or lost, and the board waits for it', async () => {
    // Composing into a box nobody has edited yet, so nothing but the composition holds the board back.
    await openSteer(react);
    await mark(react, BOX, 'box');
    const before = (await caretOf(react)).value;
    await react.page.locator(BOX).evaluate((node) => {
      globalThis.__ime = [];
      for (const name of ['compositionstart', 'compositionupdate', 'compositionend']) {
        node.addEventListener(name, () => globalThis.__ime.push(name));
      }
    });
    const cdp = await react.context.newCDPSession(react.page);
    await cdp.send('Input.imeSetComposition', {
      text: 'にほん',
      selectionStart: 3,
      selectionEnd: 3,
    });
    const composing = (await caretOf(react)).value;
    assert.ok(composing.includes('にほん'), `no provisional text in ${composing}`);
    assert.equal(composing.length, before.length + 3);
    assert.ok((await react.page.evaluate(() => globalThis.__ime)).includes('compositionstart'));
    await apply(react, (g) =>
      steerState(g, { facts: [...RECORD(g), check('c9', g - 20, 'passed')] }),
    );
    await tick(react);
    await tick(react);
    assert.equal(await same(react, BOX, 'box'), true, 'a board replaced the box mid-composition');
    assert.equal((await caretOf(react)).value, composing);
    assert.equal(await react.page.locator('[data-next-result-stale]').count(), 0);
    // A press that could copy the provisional words is refused, and nothing reaches the clipboard.
    await react.page
      .locator('[data-next-cockpit-action="correction-copy"]')
      .evaluate((b) => b.click());
    assert.equal(
      (await react.page.locator('[data-next-correction-cue]').textContent()).trim(),
      'Copy unavailable',
    );
    assert.deepEqual(await react.page.evaluate(() => globalThis.__copied), []);
    await cdp.send('Input.insertText', { text: '日本' });
    const committed = (await caretOf(react)).value;
    assert.ok(committed.includes('日本') && !committed.includes('にほん'));
    assert.ok((await react.page.evaluate(() => globalThis.__ime)).includes('compositionend'));
    // Committed, the words are the reader's and the box is edited and focused, so the board still waits.
    assert.equal(await react.page.locator('[data-next-result-stale]').count(), 0);
    await react.page.locator('.next-session-drift-heading').click();
    await react.page.waitForSelector('[data-next-result-stale="work"]');
    await react.page.locator('[data-next-cockpit-action="correction-copy"]').click();
    await sleep(patience(300));
    assert.deepEqual(await react.page.evaluate(() => globalThis.__copied), [committed]);
    assert.equal(postsTo(react.script, '/api/correction/copied').at(-1).body.text, committed);
    await cdp.detach();
  });

  await step(
    'the box survives a route away and back, and its words are what Copy sends',
    async () => {
      await openSteer(react);
      await react.page.keyboard.press(`${MOD}+a`);
      await react.page.keyboard.type('Words I wrote myself.');
      await react.page.evaluate(() => {
        location.hash = '#n=intent';
      });
      await react.page.waitForSelector('[data-next-view-body="intent"]');
      await react.page.evaluate((hash) => {
        location.hash = hash;
      }, FRAGMENT);
      await backOnTheSession(react);
      await react.page.waitForSelector(BOX);
      assert.equal((await caretOf(react)).value, 'Words I wrote myself.');
      await react.page.locator('[data-next-cockpit-action="correction-copy"]').click();
      await sleep(patience(300));
      assert.deepEqual(await react.page.evaluate(() => globalThis.__copied), [
        'Words I wrote myself.',
      ]);
      // Said until an accepted edit.
      assert.equal(
        (await react.page.locator('[data-next-correction-cue]').textContent()).trim(),
        'Copied',
      );
      await tick(react);
      assert.equal(
        (await react.page.locator('[data-next-correction-cue]').textContent()).trim(),
        'Copied',
      );
      await react.page.locator(BOX).click();
      await react.page.keyboard.type('!');
      assert.equal(
        (await react.page.locator('[data-next-correction-cue]').textContent()).trim(),
        'Copy',
      );
    },
  );

  await step(
    'a paste over the cap keeps the reader’s words and cuts what was inserted, in one undo step',
    async () => {
      await openSteer(react);
      await react.page.keyboard.press(`${MOD}+a`);
      await react.page.keyboard.type('Keep these words. ');
      const cdp = await react.context.newCDPSession(react.page);
      await cdp.send('Input.insertText', { text: 'x'.repeat(2100) });
      const after = await caretOf(react);
      assert.ok(after.value.startsWith('Keep these words. '));
      assert.equal([...after.value].length, 2000);
      assert.equal(
        (await react.page.locator('[data-next-correction-count]').textContent()).trim(),
        '2000/2000',
      );
      await react.page.keyboard.press(`${MOD}+z`);
      assert.equal((await caretOf(react)).value, 'Keep these words. ');
      await cdp.detach();
    },
  );

  await step(
    'a pointer on its way to Copy is waited through, and the click that follows is not swallowed',
    async () => {
      await openSteer(react);
      await react.page.keyboard.press(`${MOD}+a`);
      await react.page.keyboard.type('An edit that is mine.');
      const copy = react.page.locator('[data-next-cockpit-action="correction-copy"]');
      const box = await copy.boundingBox();
      await react.page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await react.page.mouse.down();
      // The browser blurred the box between the press and the click; a board arrives meanwhile.
      await apply(react, (g) =>
        steerState(g, { facts: [...RECORD(g), check('c9', g - 20, 'passed')] }),
      );
      await tick(react);
      await tick(react);
      assert.equal(
        await react.page.locator('[data-next-result-stale]').count(),
        0,
        'a board was drawn under the pointer',
      );
      await react.page.mouse.up();
      await sleep(patience(400));
      assert.deepEqual(await react.page.evaluate(() => globalThis.__copied), [
        'An edit that is mine.',
      ]);
      await react.page.waitForSelector('[data-next-result-stale="work"]');
    },
  );

  /* ===================== BEHAVIOUR: keyboard, layout and pictures ===================== */
  await step(
    'Analyze, the consent step and Steer back are operated from the keyboard alone',
    async () => {
      await apply(react, (g) =>
        claude(g, {
          payload: { reading: FIRST_PRESS },
          routes: { '/api/reading': () => ({ body: { ok: true, produced: false } }) },
        }),
      );
      await load(react);
      await read(react);
      react.script.posts.length = 0;
      const reach = async (selector) => {
        for (let i = 0; i < 80; i += 1) {
          const there = await react.page.evaluate(
            (sel) => document.activeElement?.matches(sel) === true,
            selector,
          );
          if (there) return;
          await react.page.keyboard.press('Tab');
        }
        throw new Error(`Tab never reached ${selector}`);
      };
      await react.page.locator('.next-session-drift-heading').focus();
      await reach('[data-next-cockpit-action="reading-ask"]');
      await react.page.keyboard.press('Enter');
      await react.page.waitForSelector('.next-cockpit-reading-consent');
      assert.equal(postsTo(react.script, '/api/reading').length, 0);
      // The question holds focus, and Tab reaches Allow and then Not now, in that order.
      /* Predates the one-column page (2026-10-19): the reading-allow action is retired, so this fails when
         the proof is run on demand until it is brought forward to the Drift card's own focus order. */
      await react.page.keyboard.press('Tab');
      assert.equal(
        await react.page.evaluate(() =>
          document.activeElement?.getAttribute('data-next-cockpit-action'),
        ),
        'reading-allow',
      );
      await react.page.keyboard.press('Tab');
      assert.equal(
        await react.page.evaluate(() =>
          document.activeElement?.getAttribute('data-next-cockpit-action'),
        ),
        'reading-not-now',
      );
      await react.page.keyboard.press('Space');
      await react.page.waitForSelector('[data-next-cockpit-action="reading-ask"]');
      assert.equal(postsTo(react.script, '/api/reading').length, 0);
      // Steer back, from a stored departure, the same way.
      await apply(react, (g) => steerState(g));
      await load(react);
      await read(react);
      await react.page.locator('.next-session-drift-heading').focus();
      await reach('[data-next-cockpit-action="steer-back"]');
      await react.page.keyboard.press('Enter');
      await react.page.waitForSelector(BOX);
      await reach(BOX);
      await react.page.keyboard.type('Typed with no pointer.');
      await react.page.keyboard.press('Tab');
      assert.equal(
        await react.page.evaluate(() =>
          document.activeElement?.getAttribute('data-next-cockpit-action'),
        ),
        'correction-copy',
      );
      await react.page.keyboard.press('Enter');
      await sleep(patience(300));
      const copied = await react.page.evaluate(() => globalThis.__copied);
      assert.equal(copied.length, 1);
      assert.ok(copied[0].startsWith('Typed with no pointer.'));
    },
  );

  await step(
    '320, 375, 640 (200% zoom) and 1280 CSS px: no horizontal scroll, in every state',
    async () => {
      const widths = {};
      for (const width of [320, 375, 640, 1280]) {
        const o = await newPage({ width, height: 900 });
        const states = [
          ['result and an open correction', (g) => steerState(g)],
          [
            'a running analysis',
            (g) =>
              claude(g, {
                session: { state: 'working' },
                payload: { reading_jobs: { [`${HARNESS}:${SID}`]: JOB(g) } },
              }),
          ],
          ['the consent step', (g) => claude(g, { payload: { reading: FIRST_PRESS } })],
          [
            'a stale result and a gap',
            (g) => stored(g, { session: { annotation_revision: 4 }, contextError: true }),
          ],
        ];
        for (const [name, make] of states) {
          await apply(o, make);
          await load(o);
          await read(o);
          if (name.startsWith('result')) {
            await o.page.locator('[data-next-cockpit-action="steer-back"]').click();
            await o.page.waitForSelector(BOX);
            await o.page
              .locator(BOX)
              .fill(`${'A long correction word '.repeat(12)}${'x'.repeat(80)}`);
          }
          if (name === 'the consent step') {
            await o.page.locator('[data-next-cockpit-action="reading-ask"]').click();
            await o.page.waitForSelector('.next-cockpit-reading-consent');
          }
          const overflow = await o.page.evaluate(() => ({
            scroll: document.documentElement.scrollWidth,
            client: document.documentElement.clientWidth,
            card: document.querySelector('.next-session-drift')?.scrollWidth ?? 0,
            cardClient: document.querySelector('.next-session-drift')?.clientWidth ?? 0,
          }));
          assert.ok(
            overflow.scroll <= overflow.client,
            `${name} scrolls sideways at ${width}px: ${JSON.stringify(overflow)}`,
          );
          assert.ok(
            overflow.card <= overflow.cardClient + 1,
            `the card overflows at ${width}px in ${name}`,
          );
          if ([375, 1280].includes(width)) {
            await mkdir(SHOTS, { recursive: true });
            const file = `${SHOTS}drift-${name.replace(/[^a-z]+/g, '-')}-${width}.png`;
            await o.page.screenshot({ path: file, fullPage: true });
            shots.push(file);
          }
        }
        widths[width] = 'ok';
        await o.close();
      }
      return widths;
    },
  );
} finally {
  for (const o of opened) await o.close().catch(() => undefined);
  await browser.close();
  await board.close();
  if (mutationRoot) await rm(mutationRoot, { recursive: true, force: true });
}

try {
  golden.finish({ complete: !only && failures.length === 0 });
} catch (error) {
  failures.push({ name: 'golden', message: String(error.message) });
}

console.log(JSON.stringify({ receipts, shots }, null, 2));
if (failures.length) {
  for (const failure of failures) console.error(`FAILED: ${failure.name}\n${failure.message}\n`);
  process.exit(1);
}
