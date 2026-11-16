// Bidirectional storage conformance for the twelve persisted families.
//
// The codec under test is the real frontend/src/storage module, bundled with Vite and executed
// inside a real Chromium page, so it reads and writes the same `localStorage` the removed page
// did. What that page did is a recording (`support/golden.mjs`): every interaction with it (a click,
// a function call, a wait, a page load) is one recorded step in
// `frontend/test/golden/e2e/storage-conformance.json`, holding what it returned and the localStorage it
// changed. The recording cannot be remade, because the page that produced it is gone. Each check records HOW
// the previous side was reached, because a function run in a page is weaker evidence than the page's own UI:
//   recorded-ui        the reader's controls on the previous page wrote or read the value
//   recorded-passive   the previous page wrote or read it on its own while loading and running
//   recorded-function  a function of the previous page was executed in the real page; no control exists
//                      that can reach it without a model, native or credentialed action
//   codec-level        the codec alone, in the browser, against raw storage
//
// The proof hands the codec a blank same-origin page in place of the previous one and applies each recorded
// change to it, so the codec reads exactly what that page wrote, and every codec write is then checked against
// what that page did with it: a page load is keyed by the digest of the storage the codec left for it, so a
// codec that writes something else misses its recording instead of being compared with another input's.
// Values a run invents (the tab id, the revision stamp, a lease's timestamp) are recorded as tokens and given
// fixed stand-ins, so the same relations hold. Dropped with the previous page, with the reason: its requests to
// its own backend (the revision header and the stream), which were that server's behaviour; what the page did
// with them is recorded.
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { build } from 'vite';
import { BROWSER_CONTEXT, digest, goldenFor } from './support/golden.mjs';
import { recordedName } from '../test/recorded-name.ts';

const golden = goldenFor('storage-conformance');
const root = fileURLToPath(new URL('../../', import.meta.url));
const PROJECT = 'storage-conformance';
const CLAUDE = { harness: 'claude', sid: 'claude-sid:one' };
const KEYS = {
  memo: 'compass.cockpit.memo.v2:',
  graphMode: 'compass.next.graph.mode',
  guardrails: 'compass.next.guardrails.',
  leader: 'compass.next.leader',
  liveEstimate: 'compass.next.live-estimate:',
  revision: 'compass.next.revision',
  usageConsent: 'compass.next.usage.consent',
  workstream: 'compass.next.workstream.collapsed',
  observerConsent: 'compass.observer-model-consent.v1',
  cockpitProject: 'compass.projectCockpitProject',
  goal: 'compass.projectGoal.v1:',
  usage: 'compass.projectUsage.v1',
};

const receipt = new Map(
  Object.entries(KEYS).map(([name, key]) => [
    name,
    { key, recordedToCodec: new Map(), codecToRecorded: new Map(), codecLevel: [] },
  ]),
);
function proved(family, direction, how, what) {
  const entry = receipt.get(family);
  if (direction === 'codec') {
    entry.codecLevel.push(what);
    return;
  }
  const side = direction === 'recorded->codec' ? entry.recordedToCodec : entry.codecToRecorded;
  if (!side.has(how)) side.set(how, []);
  side.get(how).push(what);
}

/* The React side here is the codec, not a served page. In production mode (`COMPASS_E2E_BUNDLE=production`) it is
   bundled minified, as the shipped page's copy of it is, so a rename or dead-code removal the minifier performs
   shows up as a failed conformance check; the development run keeps it readable. */
const minify = process.env.COMPASS_E2E_BUNDLE === 'production';

async function buildBundle(entry, name) {
  const output = await build({
    root,
    configFile: false,
    logLevel: 'silent',
    build: { write: false, minify, lib: { entry, name, formats: ['iife'], fileName: name } },
  });
  const bundle = Array.isArray(output) ? output[0] : output;
  // Playwright wraps init scripts, so the IIFE's `var` would not reach the page's global scope.
  return bundle.output[0].code + `\nglobalThis.${name} = ${name};\n`;
}

// The identity helpers are the API layer's own, so the memo and live-estimate keys are derived the way the client derives them.
const bundle =
  (await buildBundle(
    process.env.COMPASS_STORAGE_ENTRY || 'frontend/src/storage/index.ts',
    'CompassStorage',
  )) + (await buildBundle('frontend/src/api/identity.ts', 'CompassIdentity'));
// Only blank documents are served from routes, so the origin names a host that nothing listens on.
const origin = 'http://storage-conformance.invalid';
const browser = await chromium.launch();
const problems = { external: [], pageErrors: [], unexpectedPosts: [] };
const observations = [];

async function newContext({ blocked = false } = {}) {
  const context = await browser.newContext({
    ...BROWSER_CONTEXT,
    viewport: { width: 1700, height: 1100 },
  });
  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (url.startsWith(origin + '/') || url.startsWith('data:')) return route.continue();
    problems.external.push(url);
    return route.abort();
  });
  // A blank same-origin document: stands in for the previous page, and shares the storage the codec reads.
  await context.route(origin + '/__storage-seed', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>seed</title>' }),
  );
  await context.addInitScript({ content: bundle });
  if (blocked) {
    await context.addInitScript(() => {
      for (const method of ['getItem', 'setItem', 'removeItem']) {
        Storage.prototype[method] = function blocked() {
          throw new DOMException('blocked for conformance', 'SecurityError');
        };
      }
    });
  }
  return context;
}

async function track(page, label) {
  const requests = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    requests.push({ method: request.method(), path: url.pathname });
    if (request.method() !== 'GET')
      problems.unexpectedPosts.push(`${label}: ${request.method()} ${url.pathname}`);
  });
  page.on('pageerror', (error) => problems.pageErrors.push(`${label}: ${error.message}`));
  return requests;
}

async function seedPage(context, label = 'seed') {
  const page = await context.newPage();
  await track(page, label);
  await page.goto(origin + '/__storage-seed');
  return page;
}

/* ---- the previous page as a recording ----
   Each interaction is one `golden.observe`d step: its result, and the localStorage keys it set or removed.
   The keys are applied to a blank page of the same origin, which is where the codec then reads them. */
const REPLAY_TAB = 'replay-tab-0000000000000';
const REPLAY_STARTED = '1700000000';
const TAB_ID = /^[a-z0-9]+-\d{13}$/;
const REVISION = /^\d{9,}\.\d+$/;
const LEASE = /^\{"id":"([^"]*)","ts":(\d+)\}$/;
let place = { scenario: '', step: 0 };

async function snapshot(page) {
  return page.evaluate(() => {
    try {
      return Object.fromEntries(
        Object.keys(globalThis.localStorage)
          .sort()
          .map((key) => [key, globalThis.localStorage.getItem(key)]),
      );
    } catch {
      return {}; // blocked storage: there is nothing to read
    }
  });
}

/* A stored value with what a run invents replaced by a token. `age` keeps how old a lease's timestamp is, in
   whole seconds, for a page's inputs; what the previous page itself wrote was always fresh. */
function tokenised(key, value, { age = false } = {}) {
  if (typeof value !== 'string') return value;
  if (key === KEYS.revision) return tokenisedRevision(value);
  const lease = key === KEYS.leader ? LEASE.exec(value) : null;
  if (!lease) return value;
  const id = TAB_ID.test(lease[1]) ? '@tab' : lease[1];
  const stamp = age ? `@now-${Math.floor((Date.now() - Number(lease[2])) / 1000)}` : '@now';
  return `{"id":${json(id)},"ts":${json(stamp)}}`;
}
const tokenisedRevision = (value) =>
  REVISION.test(value) ? `@started.${value.split('.')[1]}` : value;
function restored(value) {
  return value
    .replace('"@now"', String(Date.now()))
    .replace(/"@now-(\d+)"/, (_, seconds) => String(Date.now() - Number(seconds) * 1000))
    .replace('@tab', REPLAY_TAB)
    .replace('@started', REPLAY_STARTED);
}
function restoredResult(value) {
  if (typeof value === 'string')
    return value === '@tab' ? REPLAY_TAB : value.replace(/^@started\./, `${REPLAY_STARTED}.`);
  if (Array.isArray(value)) return value.map(restoredResult);
  if (value && typeof value === 'object')
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, restoredResult(v)]));
  return value;
}
async function apply(page, delta) {
  if (!Object.keys(delta.set).length && !delta.removed.length) return;
  await page.evaluate(
    ([set, removed]) => {
      for (const [key, value] of Object.entries(set)) globalThis.localStorage.setItem(key, value);
      for (const key of removed) globalThis.localStorage.removeItem(key);
    },
    [
      Object.fromEntries(Object.entries(delta.set).map(([k, v]) => [k, restored(v)])),
      delta.removed,
    ],
  );
}

/** One interaction with the previous page, answered from the recording: its recorded changes are applied to the
 *  blank page `page`, and its recorded answer comes back. */
async function recorded(page, label) {
  label = recordedName(label, true);
  place.step += 1;
  const key = `${place.scenario} | #${place.step} ${label.length > 160 ? `${label.slice(0, 120)}~${digest(label)}` : label}`;
  const answer = golden.observe(key);
  await apply(page, answer.delta);
  return restoredResult(answer.value);
}
/** Whether the previous page asked its server for the stream: the page's behaviour, recorded rather than re-asked. */
const streamed = (page) => recorded(page, 'the page requested /api/stream');

/* The blank page that stands in for the previous page. A load is keyed by the digest of the storage the codec
   left for it, and its recording holds what the page wrote while booting. */
async function recordedPage(context, fragment = '') {
  const page = await seedPage(context, 'inputs');
  const stored = await snapshot(page);
  const inputs = Object.fromEntries(
    Object.entries(stored).map(([k, v]) => [k, tokenised(k, v, { age: true })]),
  );
  place.step += 1;
  const key = `${place.scenario} | #${place.step} load ${fragment || '/'} inputs:${digest(inputs)}`;
  await apply(page, golden.observe(key));
  return { page };
}

/** Run one method of a fresh or persistent codec instance in the page. Maps come back as objects. */
async function codec(page, path, args = [], { fresh = false } = {}) {
  return page.evaluate(
    ([where, values, reset]) => {
      const g = globalThis;
      if (reset || !g.__storage) g.__storage = g.CompassStorage.createLegacyStorage();
      const parts = where.split('.');
      const name = parts.pop();
      let target = g.__storage;
      for (const part of parts) target = target[part];
      const result = target[name](...values);
      return result instanceof Map ? Object.fromEntries(result) : result;
    },
    [path, args, fresh],
  );
}

async function pure(page, name, args = []) {
  return page.evaluate(
    ([fn, values]) => {
      const result = globalThis.CompassStorage[fn](...values);
      return result instanceof Map ? Object.fromEntries(result) : result;
    },
    [name, args],
  );
}

async function identity(page, name, args = []) {
  return page.evaluate(([fn, values]) => globalThis.CompassIdentity[fn](...values), [name, args]);
}

const raw = (page, key) => page.evaluate((storageKey) => localStorage.getItem(storageKey), key);
const setRaw = (page, key, value) =>
  page.evaluate(([storageKey, text]) => localStorage.setItem(storageKey, text), [key, value]);
const json = (value) => JSON.stringify(value);
/** A long text in a step's label: its length and digest say which text without spelling it. */
const sized = (text) => `${text.length} units ${digest(text)}`;

async function scenario(name, body) {
  place = { scenario: name, step: 0 };
  const started = Date.now();
  try {
    await body();
  } catch (error) {
    error.message = `[${name}] ${error.message}`;
    throw error;
  }
  console.error(`ok ${name} (${Date.now() - started} ms)`);
}

try {
  // ── memo ──────────────────────────────────────────────────────────────
  await scenario('memo: legacy UI writes, codec reads', async () => {
    const context = await newContext();
    const { page } = await recordedPage(context, `#n=project:${PROJECT}`);
    const key = await pure(page, 'memoKey', [PROJECT, null, 'outcome']);
    await recorded(page, 'click memo-edit');
    await recorded(page, 'fill memo: Ship the storage layer');
    assert.equal(await raw(page, key), 'Ship the storage layer');
    assert.equal(await codec(page, 'memo.read', [key], { fresh: true }), 'Ship the storage layer');
    proved(
      'memo',
      'recorded->codec',
      'recorded-ui',
      'typing in the project memo writes the key the codec builds; codec reads the raw string back',
    );

    await recorded(page, `fill memo ${sized('x'.repeat(600))}`);
    assert.equal(
      (await raw(page, key)).length,
      500,
      'the textarea maxlength caps typed text at 500',
    );
    assert.equal((await codec(page, 'memo.read', [key], { fresh: true })).length, 500);
    // Typed text: Chrome's maxlength never splits a surrogate pair, so the cut lands one unit early.
    await recorded(page, 'fill memo 499 a and an emoji');
    const typed = await raw(page, key);
    assert.equal(typed.length, 499);
    assert.equal(await codec(page, 'memo.read', [key], { fresh: true }), typed);
    // Script-set text skips maxlength, so the page's own slice runs and keeps the lone high surrogate.
    await recorded(page, 'script-set memo 499 a and an emoji');
    const stored = await raw(page, key);
    assert.equal(stored.length, 500);
    assert.equal(stored.charCodeAt(499), 0xd83d, 'legacy keeps the lone high surrogate at the cut');
    assert.equal(await codec(page, 'memo.read', [key], { fresh: true }), stored);
    proved(
      'memo',
      'recorded->codec',
      'recorded-ui',
      'UTF-16 boundary: typed text stops at 499 units before a surrogate pair (browser maxlength); script-set text is cut at 500 by the page, splitting the pair; the codec reads both unchanged',
    );

    for (const [group, focus, kind] of [
      [{ label: 'p/é', sessions: [{ project_key: 'pk 1' }] }, null, 'outcome'],
      [{ label: 'only-label', sessions: [{}, { project_key: 'a' }] }, CLAUDE, 'focus'],
      [{ label: 'only-label', sessions: [] }, { harness: 'codex', sid: 'x:y z' }, 'outcome'],
      [{ label: 'only-label', sessions: [] }, { harness: 'claude', session: 'abcd1234' }, 'focus'],
    ]) {
      const projectKey = await identity(page, 'stableProjectKey', [group]);
      const expected = await recorded(
        page,
        `nextCockpitMemoKey(${json(group)}, ${json(focus)}, ${json(kind)})`,
      );
      assert.equal(await pure(page, 'memoKey', [projectKey, focus, kind]), expected);
    }
    proved(
      'memo',
      'recorded->codec',
      'recorded-function',
      'key spelling for project and exact harness:sid scopes, encoded, matches nextCockpitMemoKey, with the project key derived by api/identity.stableProjectKey',
    );
    await context.close();
  });

  await scenario('memo: codec writes, legacy UI reads', async () => {
    const context = await newContext();
    const seed = await seedPage(context);
    const outcome = await pure(seed, 'memoKey', [PROJECT, null, 'outcome']);
    const focus = await pure(seed, 'memoKey', [PROJECT, null, 'focus']);
    await codec(seed, 'memo.write', [outcome, 'Codec outcome']);
    await codec(seed, 'memo.write', [focus, 'Codec focus']);
    await seed.close();
    const { page } = await recordedPage(context, `#n=project:${PROJECT}`);
    await recorded(page, 'wait for the outcome field');
    assert.equal(await recorded(page, 'read the outcome field'), 'Codec outcome');
    assert.equal(await recorded(page, 'read the focus field'), 'Codec focus');
    proved(
      'memo',
      'codec->recorded',
      'recorded-ui',
      'legacy project page shows the outcome and focus a codec wrote',
    );
    await setRaw(page, outcome, 'y'.repeat(700));
    assert.equal(await recorded(page, `nextCockpitReadMemo(${json(outcome)}).length`), 500);
    assert.equal((await codec(page, 'memo.read', [outcome], { fresh: true })).length, 500);
    proved(
      'memo',
      'codec->recorded',
      'recorded-function',
      'a longer raw value reads back bounded to 500 units in both',
    );
    await context.close();
  });

  // ── graph mode ────────────────────────────────────────────────────────
  await scenario('graph mode: legacy UI writes, codec reads', async () => {
    const context = await newContext();
    const { page } = await recordedPage(context, `#n=project:${PROJECT}:decisions`);
    await recorded(page, 'click graph mode All');
    const scope = await pure(page, 'graphModeScope', [PROJECT, null]);
    assert.equal(await raw(page, KEYS.graphMode), json({ [scope]: 'all' }));
    assert.deepEqual(await pure(page, 'decodeGraphModes', [await raw(page, KEYS.graphMode)]), {
      [scope]: 'all',
    });
    assert.equal(await codec(page, 'graphMode.resolve', [{ scope }], { fresh: true }), 'all');
    proved(
      'graphMode',
      'recorded->codec',
      'recorded-ui',
      'pressing All events writes {"<project>\\u0000": "all"} that the codec resolves',
    );
    assert.equal(await recorded(page, 'projectGraphModeScope()'), scope);
    await context.close();
  });

  await scenario('graph mode: codec writes, legacy UI reads', async () => {
    const context = await newContext();
    const seed = await seedPage(context);
    const scope = await pure(seed, 'graphModeScope', [PROJECT, null]);
    await codec(seed, 'graphMode.set', [scope, 'all']);
    await seed.close();
    const { page } = await recordedPage(context, `#n=project:${PROJECT}:decisions`);
    await recorded(page, 'wait for All pressed');
    assert.equal(await recorded(page, 'count pressed modes'), 1);
    proved(
      'graphMode',
      'codec->recorded',
      'recorded-ui',
      'legacy Decisions tab presses the mode the codec wrote',
    );
    // The retired build wrote every project under one empty key; both sides must drop it.
    await setRaw(
      page,
      KEYS.graphMode,
      json({ '': 'all', 'p\u0000s': 'decisions', 'a\u0000b\u0000c': 'all', 'q\u0000': 'sideways' }),
    );
    const decoded = await pure(page, 'decodeGraphModes', [await raw(page, KEYS.graphMode)]);
    await recorded(page, 'projectGraphModeBySession.clear(); projectLoadGraphModes();');
    assert.deepEqual(
      await recorded(page, 'Object.fromEntries(projectGraphModeBySession)'),
      decoded,
    );
    assert.deepEqual(decoded, { 'p\u0000s': 'decisions' });
    proved(
      'graphMode',
      'codec->recorded',
      'recorded-function',
      'legacy projectLoadGraphModes and the codec decode the same raw map, dropping empty-key, three-part and invalid-mode entries',
    );
    for (const corrupt of ['{', '5', '[]', '"x"']) {
      await setRaw(page, KEYS.graphMode, corrupt);
      await recorded(page, 'projectGraphModeBySession.clear(); projectLoadGraphModes();');
      assert.equal(await recorded(page, 'projectGraphModeBySession.size'), 0);
      assert.deepEqual(await pure(page, 'decodeGraphModes', [corrupt]), {});
    }
    proved(
      'graphMode',
      'codec',
      undefined,
      'corrupt JSON, scalars and arrays read as no choices in both',
    );
    await context.close();
  });

  // ── guardrails ────────────────────────────────────────────────────────
  await scenario('guardrails: legacy UI writes, codec reads', async () => {
    const context = await newContext();
    const { page } = await recordedPage(context, `#n=project:${PROJECT}:console`);
    const key = await pure(page, 'guardrailKey', [PROJECT]);
    const add = (text, options = {}) =>
      recorded(page, `add guardrail${options.script ? ' (script-set)' : ''} ${sized(text)}`);
    await add('  watch the tests  ');
    await add('second rule');
    await recorded(page, 'toggle guardrail 0');
    assert.equal(
      await raw(page, key),
      json([
        { enabled: false, text: 'watch the tests' },
        { enabled: true, text: 'second rule' },
      ]),
    );
    assert.deepEqual(await codec(page, 'guardrails.rules', [PROJECT], { fresh: true }), [
      { enabled: false, text: 'watch the tests' },
      { enabled: true, text: 'second rule' },
    ]);
    proved(
      'guardrails',
      'recorded->codec',
      'recorded-ui',
      'adding two tripwires and toggling one writes the rule array the codec reads, trimmed and with enabled flags',
    );

    await add('a'.repeat(499) + '😀😀 tail');
    assert.equal(
      JSON.parse(await raw(page, key))[2].text.length,
      499,
      'typed text stops before the surrogate pair',
    );
    await add('b'.repeat(499) + '😀😀 tail', { script: true });
    const rules = JSON.parse(await raw(page, key)).slice(-1);
    assert.equal(rules[0].text.length, 500);
    assert.equal(rules[0].text.charCodeAt(499), 0xd83d);
    assert.deepEqual(
      (await codec(page, 'guardrails.rules', [PROJECT], { fresh: true })).at(-1),
      rules[0],
    );
    proved(
      'guardrails',
      'recorded->codec',
      'recorded-ui',
      'UTF-16 boundary: typed text stops at 499 before a surrogate pair; script-set text is trimmed and cut at 500 by the page, splitting the pair; the codec reads it unchanged',
    );
    await recorded(page, 'add fifty-five rules');
    const stored = JSON.parse(await raw(page, key));
    assert.equal(stored.length, 50);
    assert.equal(stored[49].text, 'rule 54');
    assert.deepEqual(await codec(page, 'guardrails.rules', [PROJECT], { fresh: true }), stored);
    proved(
      'guardrails',
      'recorded->codec',
      'recorded-ui',
      'legacy keeps the last 50 on add; codec loads all 50',
    );
    await context.close();
  });

  await scenario('guardrails: codec writes, legacy reads', async () => {
    const context = await newContext();
    const seed = await seedPage(context);
    const key = await pure(seed, 'guardrailKey', [PROJECT]);
    await codec(seed, 'guardrails.add', [PROJECT, 'first']);
    await codec(seed, 'guardrails.add', [PROJECT, 'second']);
    await codec(seed, 'guardrails.add', [PROJECT, 'third']);
    await codec(seed, 'guardrails.toggle', [PROJECT, 1]);
    await seed.close();
    const { page } = await recordedPage(context, `#n=project:${PROJECT}:console`);
    await recorded(page, 'wait for a guardrail');
    assert.deepEqual(await recorded(page, 'read the guardrail rows'), [
      ['true', 'first'],
      ['false', 'second'],
      ['true', 'third'],
    ]);
    assert.equal(
      await raw(page, key),
      json([
        { enabled: true, text: 'first' },
        { enabled: false, text: 'second' },
        { enabled: true, text: 'third' },
      ]),
      'the codec writes the rule array in the legacy key order',
    );
    proved(
      'guardrails',
      'codec->recorded',
      'recorded-ui',
      'legacy console rail lists the rules and enabled states the codec wrote, and the raw array has the legacy key order',
    );

    const plain = [
      null,
      ...Array.from({ length: 60 }, (_, index) =>
        index === 0
          ? 'old plain string'
          : index === 1
            ? { text: 'off', enabled: false }
            : `rule ${index}`,
      ),
      { text: '   ' },
      { text: 7 },
      'z'.repeat(520),
      'a'.repeat(499) + '😀😀',
    ];
    const corpus = json(plain);
    await setRaw(page, key, corpus);
    const legacyRules = await recorded(page, `nextControlsReadRules(${json(PROJECT)})`);
    const codecRules = await pure(page, 'decodeGuardrails', [corpus]);
    assert.deepEqual(codecRules, legacyRules);
    assert.equal(codecRules.length, 50);
    assert.deepEqual(codecRules[0], { enabled: true, text: 'old plain string' });
    assert.deepEqual(codecRules[1], { enabled: false, text: 'off' });
    proved(
      'guardrails',
      'codec->recorded',
      'recorded-function',
      'nextControlsReadRules and the codec agree on old plain strings as enabled, invalid rules dropped, the 50-rule cap and the 500-unit text cap',
    );
    const short = json([
      'a'.repeat(520),
      'a'.repeat(499) + '😀😀',
      { text: ' pad ', enabled: 0 },
      { text: 'n', enabled: null },
    ]);
    assert.deepEqual(
      await pure(page, 'decodeGuardrails', [short]),
      await recorded(
        page,
        `(() => { localStorage.setItem(${json(key)}, ${json(short)}); return nextControlsReadRules(${json(PROJECT)}); })()`,
      ),
    );
    for (const corrupt of ['{', '{"text":"a"}', '5', 'null']) {
      await setRaw(page, key, corrupt);
      assert.deepEqual(await recorded(page, `nextControlsReadRules(${json(PROJECT)})`), []);
      assert.deepEqual(await pure(page, 'decodeGuardrails', [corrupt]), []);
    }
    proved(
      'guardrails',
      'codec',
      undefined,
      'corrupt, non-array and null values read as no rules; enabled only false disables',
    );
    await context.close();
  });

  // ── workstream collapse ───────────────────────────────────────────────
  await scenario('workstream collapse: both directions through the legacy toggle', async () => {
    const context = await newContext();
    const { page } = await recordedPage(context, `#n=project:${PROJECT}:course`);
    assert.equal(await recorded(page, 'read expanded'), 'true');
    await recorded(page, 'click the toggle');
    assert.equal(await raw(page, KEYS.workstream), '1');
    assert.equal(await codec(page, 'workstream.collapsed', [], { fresh: true }), true);
    await recorded(page, 'click the toggle again');
    assert.equal(await raw(page, KEYS.workstream), '0');
    assert.equal(await codec(page, 'workstream.collapsed', [], { fresh: true }), false);
    proved(
      'workstream',
      'recorded->codec',
      'recorded-ui',
      'toggling OBSERVED STATE CHANGES writes 1 then 0 that the codec reads',
    );
    await context.close();

    for (const collapsed of [true, false]) {
      const next = await newContext();
      const seed = await seedPage(next);
      assert.equal(await codec(seed, 'workstream.setCollapsed', [collapsed]), true);
      assert.equal(await raw(seed, KEYS.workstream), collapsed ? '1' : '0');
      await seed.close();
      const { page: reader } = await recordedPage(next, `#n=project:${PROJECT}:course`);
      assert.equal(
        await recorded(reader, `read expanded after a codec ${collapsed ? 1 : 0}`),
        String(!collapsed),
      );
      await next.close();
    }
    proved(
      'workstream',
      'codec->recorded',
      'recorded-ui',
      'the legacy toggle loads expanded or collapsed from the codec-written 0 or 1',
    );
    const other = await newContext();
    const seed = await seedPage(other);
    await setRaw(seed, KEYS.workstream, 'true');
    await seed.close();
    const { page: reader } = await recordedPage(other, `#n=project:${PROJECT}:course`);
    assert.equal(await recorded(reader, 'read expanded after a codec true'), 'true');
    assert.equal(await codec(reader, 'workstream.collapsed', [], { fresh: true }), false);
    proved(
      'workstream',
      'codec',
      undefined,
      'only the word 1 means collapsed; true, empty and missing read expanded in both',
    );
    await other.close();
  });

  // ── leader lease ──────────────────────────────────────────────────────
  await scenario(
    'leader lease: legacy writes, codec reads, codec foreign owner steers legacy',
    async () => {
      const context = await newContext();
      const { page } = await recordedPage(context, '');
      const tabId = await recorded(page, 'NEXT_TAB_ID');
      const lease = await codec(page, 'lease.read', [], { fresh: true });
      assert.equal(lease.id, tabId);
      assert.equal(typeof lease.ts, 'number');
      assert.equal(await raw(page, KEYS.leader), json({ id: tabId, ts: lease.ts }));
      assert.equal(await pure(page, 'leaseIsLive', [lease, Date.now()]), true);
      await recorded(page, 'wait 2600 ms for a renewal');
      assert.ok(
        (await codec(page, 'lease.read')).ts > lease.ts,
        'the legacy leader renews on its 2000 ms timer',
      );
      proved(
        'leader',
        'recorded->codec',
        'recorded-passive',
        'the page writes {id, ts} under its own tab id and renews it; codec parses and judges it live',
      );
      assert.ok(await streamed(page));

      // A foreign lease, stale but written after this tab led: the throttled leader must still yield.
      const foreign = { id: 'foreign-conformance-tab', ts: Date.now() - 7000 };
      assert.equal(
        await pure(page, 'electionDecision', [
          { lease: foreign, tabId, isLeader: true, now: Date.now() },
        ]),
        'yield',
      );
      await setRaw(page, KEYS.leader, json(foreign));
      await recorded(page, 'wait for the tab to yield');
      assert.equal(
        await raw(page, KEYS.leader),
        json(foreign),
        'the yielding tab does not overwrite the foreign record',
      );
      proved(
        'leader',
        'codec->recorded',
        'recorded-passive',
        'a foreign owner written after the legacy tab led, even stale, makes it close its stream and yield, as electionDecision says',
      );

      await context.close();

      // pagehide releases a lease the tab still owns.
      const owner = await newContext();
      const { page: leader } = await recordedPage(owner, '');
      const observer = await seedPage(owner, 'lease-observer');
      // The leader writes its lease on its first election, which a loaded runner can delay past page load.
      await recorded(observer, 'the lease is written');
      assert.notEqual(await codec(observer, 'lease.read', [], { fresh: true }), null);
      // The page is still alive after a synthetic pagehide, so its next election tick (within 2 s) writes the lease
      // again, and the handler only releases while the page leads (a stream error under load drops that until the next
      // tick). Read the key and the codec's view in the same task as the event, and only accept an attempt that led.
      // The page keeps running after the event and writes its lease on the next tick, so the storage it leaves is
      // not recorded: the answer below is what the page did in that one task.
      const released = await recorded(leader, 'pagehide releases a lease the tab owns');
      assert.equal(released.leading, true);
      assert.equal(released.raw, null);
      assert.equal(released.lease, null);
      proved(
        'leader',
        'recorded->codec',
        'recorded-function',
        'the pagehide handler removes the key a leading tab owns; the codec then reads no lease',
      );
      await owner.close();

      // Measured, not assumed: a real navigation does not run that release in Chromium, because the
      // aborted EventSource reports CLOSED first and the legacy error handler clears nextIsLeader
      // before pagehide fires. The lease is left to go stale, so the codec must read it as live.
      const away = await newContext();
      const { page: leaving } = await recordedPage(away, '');
      const watcher = await seedPage(away, 'lease-watcher');
      await recorded(leaving, 'navigate away');
      const left = await raw(watcher, KEYS.leader);
      const decoded = await codec(watcher, 'lease.read', [], { fresh: true });
      assert.equal(decoded === null, left === null);
      observations.push({
        navigationLeavesLease: left !== null,
        lease: left === null ? null : 'a record with the departed tab id, live for up to 6 s',
      });
      if (left !== null)
        assert.equal(await pure(watcher, 'leaseIsLive', [decoded, Date.now()]), true);
      await away.close();
    },
  );

  await scenario('leader lease: codec-written foreign owners live and stale', async () => {
    const live = await newContext();
    const seed = await seedPage(live);
    await codec(seed, 'lease.write', ['foreign-live-tab', Date.now()]);
    await seed.close();
    const { page } = await recordedPage(live);
    await recorded(page, 'wait 2600 ms');
    assert.equal(await recorded(page, 'nextIsLeader'), false);
    assert.equal(
      await streamed(page),
      false,
      'a tab yielding to a live foreign lease opens no stream',
    );
    assert.match(
      await raw(page, KEYS.leader),
      /^\{"id":"foreign-live-tab","ts":\d+\}$/,
      'the codec writes id then a numeric ts',
    );
    assert.equal(
      await pure(page, 'electionDecision', [
        {
          lease: await codec(page, 'lease.read', [], { fresh: true }),
          tabId: await recorded(page, 'NEXT_TAB_ID'),
          isLeader: false,
          now: Date.now(),
        },
      ]),
      'yield',
    );
    proved(
      'leader',
      'codec->recorded',
      'recorded-passive',
      'a codec-written live foreign lease keeps the legacy tab from opening /api/stream',
    );
    await live.close();

    // Near the 6000 ms edge: 5.2 s old is still live to legacy, and the codec must agree.
    const edge = await newContext();
    const edgeSeed = await seedPage(edge);
    await codec(edgeSeed, 'lease.write', ['foreign-edge-tab', Date.now() - 5200]);
    assert.equal(
      await pure(edgeSeed, 'leaseIsLive', [await codec(edgeSeed, 'lease.read'), Date.now()]),
      true,
    );
    await edgeSeed.close();
    const { page: edgePage } = await recordedPage(edge);
    await recorded(edgePage, 'wait 500 ms');
    assert.equal(await recorded(edgePage, 'nextIsLeader'), false);
    assert.equal(await streamed(edgePage), false);
    proved(
      'leader',
      'codec->recorded',
      'recorded-passive',
      'a codec-written lease 5.2 s old is still live to legacy (6000 ms edge), and leaseIsLive agrees',
    );
    await edge.close();

    const stale = await newContext();
    const staleSeed = await seedPage(stale);
    await codec(staleSeed, 'lease.write', ['foreign-stale-tab', Date.now() - 7000]);
    await staleSeed.close();
    const { page: taker } = await recordedPage(stale);
    await recorded(taker, 'wait for the takeover');
    assert.equal(
      JSON.parse(await raw(taker, KEYS.leader)).id,
      await recorded(taker, 'NEXT_TAB_ID'),
    );
    assert.ok(await streamed(taker));
    proved(
      'leader',
      'codec->recorded',
      'recorded-passive',
      'a codec-written stale foreign lease (7 s old) is taken over by the legacy tab, which opens its stream',
    );
    await stale.close();

    const corrupt = await newContext();
    const corruptSeed = await seedPage(corrupt);
    await setRaw(corruptSeed, KEYS.leader, '{oops');
    assert.equal(await codec(corruptSeed, 'lease.read', [], { fresh: true }), null);
    await corruptSeed.close();
    const { page: tolerant } = await recordedPage(corrupt);
    await recorded(tolerant, 'wait for the takeover');
    assert.equal(
      await recorded(tolerant, 'nextReadLease() && nextReadLease().id'),
      await recorded(tolerant, 'NEXT_TAB_ID'),
    );
    proved(
      'leader',
      'codec',
      undefined,
      'a corrupt lease reads as none in the codec and the legacy tab leads, overwriting it',
    );
    await corrupt.close();

    const blocked = await newContext({ blocked: true });
    const { page: self } = await recordedPage(blocked);
    await recorded(self, 'wait for the tab to lead');
    assert.ok(await streamed(self));
    assert.equal(await codec(self, 'lease.read', [], { fresh: true }), null);
    assert.equal(await codec(self, 'lease.write', ['t', 1]), false);
    proved(
      'leader',
      'codec',
      undefined,
      'blocked storage: the legacy tab leads itself and streams; the codec reads no lease and reports the refused write',
    );
    await blocked.close();
  });

  // ── revision ──────────────────────────────────────────────────────────
  await scenario('revision: legacy broadcast, comparator and cross-tab wake', async () => {
    const context = await newContext();
    const { page } = await recordedPage(context, '');
    const revision = await recorded(page, 'nextLastRevision');
    assert.equal(await raw(page, KEYS.revision), revision);
    assert.equal(await codec(page, 'revision.read', [], { fresh: true }), revision);
    assert.equal(
      await recorded(page, "the stored revision carries this server's start stamp"),
      true,
      "the stored revision carries this server's start stamp",
    );
    proved(
      'revision',
      'recorded->codec',
      'recorded-passive',
      'the SSE revision the page accepted is stored raw, <started>.<counter>, and the codec reads it',
    );

    const pairs = [
      ['', 'a.1'],
      ['a.1', null],
      ['a.2', 'a.1'],
      ['a.1', 'a.1'],
      ['a.1', 'a.2'],
      ['a.10', 'a.9'],
      ['b.1', 'a.99'],
      ['a.1.5', 'a.1.4'],
      ['a.1.5', 'a.2.4'],
      ['a.x', 'a.1'],
      ['a.x', 'a.x'],
      ['abc', 'abd'],
      ['abc', 'abc'],
      ['a.', 'a.1'],
      ['.5', '.4'],
      ['1.5', '1.5e0'],
    ];
    for (const [a, b] of pairs) {
      assert.equal(
        await pure(page, 'revisionNewer', [a, b]),
        await recorded(page, `nextRevisionNewer(${json(a)}, ${json(b)})`),
        `comparator ${json([a, b])}`,
      );
    }
    proved(
      'revision',
      'codec->recorded',
      'recorded-function',
      `revisionNewer agrees with nextRevisionNewer on ${pairs.length} pairs, including restarts, non-finite counters and a missing dot`,
    );

    const [started, counter] = [
      revision.slice(0, revision.lastIndexOf('.')),
      Number(revision.slice(revision.lastIndexOf('.') + 1)),
    ];
    const writer = await seedPage(context, 'revision-writer');
    const newer = `${started}.${counter + 5}`;
    assert.equal(await codec(writer, 'revision.write', [newer]), true);
    const woke = await recorded(page, 'a newer revision written by another tab wakes a refetch');
    assert.ok(woke, 'a newer revision written by another tab wakes a refetch');
    assert.equal(await codec(writer, 'revision.write', [`${started}.${counter + 4}`]), true);
    const idle = await recorded(page, 'an older revision moves nothing and wakes no refetch');
    assert.equal(idle.revision, newer, 'an older revision does not move the tab');
    assert.equal(idle.refetched, false, 'an older revision wakes no refetch');
    proved(
      'revision',
      'codec->recorded',
      'recorded-passive',
      'a newer revision the codec writes from another tab wakes the legacy tab to refetch /api/data; an older one does nothing',
    );
    const event = await pure(writer, 'revisionFromStorageEvent', [
      { key: KEYS.revision, newValue: newer },
    ]);
    assert.equal(event, newer);
    await context.close();

    const blocked = await newContext({ blocked: true });
    const seed = await seedPage(blocked);
    assert.equal(await codec(seed, 'revision.write', ['1.1']), false);
    assert.equal(await codec(seed, 'revision.read'), null);
    proved(
      'revision',
      'codec',
      undefined,
      'blocked storage: write reports false and read is null; the page never hydrates from this key',
    );
    await blocked.close();
  });

  // ── live estimate ─────────────────────────────────────────────────────
  await scenario('live estimate: both directions through the legacy functions', async () => {
    const context = await newContext();
    const { page } = await recordedPage(context);
    const key = await pure(page, 'liveEstimateKey', [CLAUDE]);
    await recorded(page, `nextLiveMonitorSet(${json(CLAUDE)}, true)`);
    assert.equal(await raw(page, key), '1');
    assert.equal(await recorded(page, `NEXT_LIVE_ESTIMATE_KEY + sessKey(${json(CLAUDE)})`), key);
    assert.equal(await codec(page, 'liveEstimate.on', [CLAUDE], { fresh: true }), true);
    assert.equal(
      await codec(page, 'liveEstimate.on', [{ harness: 'codex', sid: CLAUDE.sid }], {
        fresh: true,
      }),
      false,
    );
    await recorded(page, `nextLiveMonitorSet(${json(CLAUDE)}, false)`);
    assert.equal(await raw(page, key), null);
    assert.equal(await codec(page, 'liveEstimate.on', [CLAUDE], { fresh: true }), false);
    proved(
      'liveEstimate',
      'recorded->codec',
      'recorded-function',
      'nextLiveMonitorSet writes the unencoded harness:sid key as 1 and removes it for off; the codec reads both. The UI switch needs annotations on, which this run disables',
    );

    // A local toggle wins over storage on both sides; storage that someone else wrote is not consulted afterwards.
    await recorded(page, `nextLiveMonitorSet(${json(CLAUDE)}, false)`);
    await codec(page, 'liveEstimate.set', [CLAUDE, false], { fresh: true });
    await setRaw(page, key, '1');
    assert.equal(await recorded(page, `nextLiveMonitorOn(${json(CLAUDE)})`), false);
    assert.equal(await codec(page, 'liveEstimate.on', [CLAUDE]), false);
    assert.equal(
      await codec(page, 'liveEstimate.on', [CLAUDE], { fresh: true }),
      true,
      'a fresh reader sees the raw value',
    );
    await context.close();

    const reader = await newContext();
    const seed = await seedPage(reader);
    assert.equal(await codec(seed, 'liveEstimate.set', [CLAUDE, true], { fresh: true }), true);
    assert.equal(await raw(seed, key), '1');
    await seed.close();
    const { page: loaded } = await recordedPage(reader);
    assert.equal(await recorded(loaded, `nextLiveMonitorOn(${json(CLAUDE)})`), true);
    assert.equal(
      await recorded(loaded, `nextLiveMonitorOn(${json({ harness: 'codex', sid: CLAUDE.sid })})`),
      false,
    );
    assert.equal(
      await recorded(loaded, `nextLiveMonitorOn(${json({ harness: 'claude', sid: 'other' })})`),
      false,
    );
    await codec(loaded, 'liveEstimate.set', [CLAUDE, false], { fresh: true });
    assert.equal(await raw(loaded, key), null);
    for (const value of ['0', 'true', '']) {
      await setRaw(loaded, key, value);
      await recorded(loaded, 'nextLiveMonitorMemory.clear()');
      assert.equal(
        await recorded(loaded, `nextLiveMonitorOn(${json(CLAUDE)})`),
        await codec(loaded, 'liveEstimate.on', [CLAUDE], { fresh: true }),
      );
    }
    proved(
      'liveEstimate',
      'codec->recorded',
      'recorded-function',
      'a codec-written 1 reads as on in nextLiveMonitorOn for that exact harness and sid only, removal as off, and 0, true and empty read off in both; a local toggle wins over storage on both sides',
    );
    await reader.close();
  });

  // ── consents ──────────────────────────────────────────────────────────
  for (const [family, key, setLegacy, getLegacy] of [
    ['usageConsent', KEYS.usageConsent, 'nextSetUsageConsent', 'nextUsageConsent'],
    ['observerConsent', KEYS.observerConsent, 'nextSetObserverConsent', 'nextObserverConsent'],
  ]) {
    await scenario(`${family}: both directions, other-tab winner, blocked storage`, async () => {
      const context = await newContext();
      const { page } = await recordedPage(context);
      const store = family;
      assert.equal(await recorded(page, `${getLegacy}()`), null);
      assert.equal(await codec(page, `${store}.get`, [], { fresh: true }), null);
      await recorded(page, `${setLegacy}("granted")`);
      assert.equal(await raw(page, key), 'granted');
      assert.equal(await codec(page, `${store}.get`, [], { fresh: true }), 'granted');
      await recorded(page, `${setLegacy}("declined")`);
      assert.equal(await codec(page, `${store}.get`, [], { fresh: true }), 'declined');
      proved(
        family,
        'recorded->codec',
        'recorded-function',
        `${setLegacy} writes the raw word the codec reads. The disclosure UI needs a credentialed usage fetch or an enabled observer model, which this run disables`,
      );

      assert.equal(await codec(page, `${store}.set`, ['granted'], { fresh: true }), true);
      assert.equal(await raw(page, key), 'granted');
      assert.equal(await recorded(page, `${getLegacy}()`), 'granted');
      await setRaw(page, key, 'garbled');
      // Each side falls back to its own memo: legacy last answered declined, the codec granted.
      assert.equal(
        await recorded(page, `${getLegacy}()`),
        'declined',
        'legacy falls back to its memo for an unrecognised value',
      );
      assert.equal(
        await codec(page, `${store}.get`),
        'granted',
        'codec falls back to its memo for an unrecognised value',
      );
      await context.close();

      // Another tab's answer wins over this tab's memo, in both directions.
      const tabs = await newContext();
      const { page: first } = await recordedPage(tabs);
      const second = await seedPage(tabs, 'other-tab');
      await recorded(first, `${setLegacy}("granted")`);
      await codec(second, `${store}.set`, ['declined'], { fresh: true });
      assert.equal(
        await recorded(first, `${getLegacy}()`),
        'declined',
        'legacy: the other tab answer wins over the memo',
      );
      await codec(first, `${store}.set`, ['granted'], { fresh: true });
      await recorded(first, `${setLegacy}("declined")`);
      assert.equal(
        await codec(first, `${store}.get`),
        'declined',
        'codec: an answer legacy stored wins over the codec memo',
      );
      proved(
        family,
        'codec->recorded',
        'recorded-function',
        'a codec answer written from another document overrides the legacy memo, and an answer legacy stores overrides the codec memo',
      );
      await tabs.close();

      const blocked = await newContext({ blocked: true });
      const { page: shut } = await recordedPage(blocked);
      await recorded(shut, `${setLegacy}("granted")`);
      assert.equal(await recorded(shut, `${getLegacy}()`), 'granted');
      assert.equal(await codec(shut, `${store}.set`, ['granted'], { fresh: true }), false);
      assert.equal(await codec(shut, `${store}.get`), 'granted');
      proved(
        family,
        'codec',
        undefined,
        'blocked storage: both hold the answer in memory for the tab; the codec reports the refused write',
      );
      await blocked.close();
    });
  }

  // ── cockpit project, usage and goal (project.js) ──────────────────────
  await scenario(
    'cockpit project and usage: legacy setProjectCockpit writes, codec reads',
    async () => {
      const context = await newContext();
      const { page } = await recordedPage(context);
      await recorded(page, `setProjectCockpit(${json(PROJECT)})`);
      await recorded(page, `setProjectCockpit("other project")`);
      await recorded(page, `setProjectCockpit(${json(PROJECT)})`);
      assert.equal(await raw(page, KEYS.cockpitProject), PROJECT);
      assert.equal(await codec(page, 'cockpitProject.read', [], { fresh: true }), PROJECT);
      assert.equal(await raw(page, KEYS.usage), json({ [PROJECT]: 2, 'other project': 1 }));
      assert.deepEqual(await codec(page, 'usage.counts', [], { fresh: true }), {
        [PROJECT]: 2,
        'other project': 1,
      });
      await recorded(page, 'setProjectCockpit("")');
      assert.equal(await raw(page, KEYS.cockpitProject), '');
      assert.equal(await codec(page, 'cockpitProject.read', [], { fresh: true }), null);
      proved(
        'cockpitProject',
        'recorded->codec',
        'recorded-function',
        'setProjectCockpit writes the raw label; an empty one reads as null in the codec',
      );
      proved(
        'usage',
        'recorded->codec',
        'recorded-function',
        'each setProjectCockpit increments projectUsage; the codec reads the label=>count object. The routes driven here render no control that calls it',
      );
      await context.close();
    },
  );

  await scenario('cockpit project and usage: codec writes, legacy reads at load', async () => {
    const context = await newContext();
    const seed = await seedPage(context);
    await codec(seed, 'cockpitProject.write', ['seeded label']);
    await codec(seed, 'usage.record', ['seeded label']);
    await codec(seed, 'usage.record', ['seeded label']);
    await codec(seed, 'usage.record', ['second']);
    await seed.close();
    const { page } = await recordedPage(context);
    assert.equal(
      await recorded(page, 'projectCockpitLabel'),
      'seeded label',
      'the legacy boot reads the key the codec wrote',
    );
    assert.deepEqual(await recorded(page, 'Object.assign({}, projectUsage())'), {
      'seeded label': 2,
      second: 1,
    });
    proved(
      'cockpitProject',
      'codec->recorded',
      'recorded-passive',
      'the legacy page boot reads the label the codec wrote into projectCockpitLabel',
    );
    proved(
      'usage',
      'codec->recorded',
      'recorded-function',
      'projectUsage loads the label=>count object the codec wrote',
    );
    await context.close();

    // The load rules, run on the same raw text by both loaders.
    const entries = Object.fromEntries(
      Array.from({ length: 250 }, (_, index) => [`k${index}`, index + 1]),
    );
    const corpora = [
      json({ a: 5.9, b: '7', c: 0, d: -3, e: 'abc', f: 1e9, g: true, h: null, '': 4, i: [3] }),
      json(entries),
      json({
        '': 1,
        ...Object.fromEntries(Array.from({ length: 200 }, (_, index) => [`k${index}`, 1])),
      }),
      '{',
      '5',
      '[1,2]',
      'null',
      '"x"',
      '',
    ];
    for (const text of corpora) {
      const next = await newContext();
      const loader = await seedPage(next);
      if (text !== '') await setRaw(loader, KEYS.usage, text);
      await loader.close();
      const { page: reader } = await recordedPage(next);
      const expected = await recorded(reader, 'Object.assign({}, projectUsage())');
      assert.deepEqual(
        await pure(reader, 'decodeUsage', [text === '' ? null : text]),
        expected,
        `usage corpus ${text.slice(0, 40)}`,
      );
      if (text === corpora[1]) assert.equal(Object.keys(expected).length, 200);
      await next.close();
    }
    const writes = await newContext();
    const { page: writer } = await recordedPage(writes);
    await setRaw(
      writer,
      KEYS.usage,
      json(Object.fromEntries(Array.from({ length: 200 }, (_, index) => [`k${index}`, 1]))),
    );
    await recorded(writer, 'projectUsageCounts = null;');
    await recorded(writer, 'projectRecordUse("fresh")');
    assert.equal(
      Object.keys(JSON.parse(await raw(writer, KEYS.usage))).length,
      201,
      'legacy writes do not bound the key count',
    );
    assert.equal(
      Object.keys(await codec(writer, 'usage.counts', [], { fresh: true })).length,
      200,
      'a reload takes the first 200 of the 201',
    );
    await codec(writer, 'usage.record', ['fresh2'], { fresh: true });
    assert.equal(
      Object.keys(JSON.parse(await raw(writer, KEYS.usage))).length,
      201,
      'a codec write keeps the 200 it loaded and adds one, without bounding',
    );
    proved(
      'usage',
      'codec',
      undefined,
      'writes never bound the key count, in legacy or codec, while loads stop at 200',
    );
    await writes.close();
  });

  await scenario(
    'goal: legacy editor writes, codec reads, codec writes, legacy reads',
    async () => {
      const context = await newContext();
      const { page } = await recordedPage(context);
      const label = 'goal project/é';
      const key = await pure(page, 'goalKey', [label]);
      await recorded(
        page,
        // Browser proof only: label is a fixed test value serialized with JSON.stringify into the recorded fixture script.
        // nosemgrep: javascript.lang.security.html-in-template-string
        `projectGoalEditingLabel = ${json(label)};
      document.body.insertAdjacentHTML('beforeend', '<div id="conformance-goal-host">' + projectGoalBlock({label: ${json(label)}}, projectGoal(${json(label)}), '') + '</div>');`,
      );
      assert.equal(await recorded(page, 'read the goal field maxlength'), '500');
      await recorded(page, 'fill the goal: ship the migration');
      await recorded(page, `projectGoalAction("project-goal-save", ${json(label)})`);
      assert.equal(await raw(page, key), 'ship the migration');
      assert.equal(await codec(page, 'goal.read', [label], { fresh: true }), 'ship the migration');
      const long = 'g'.repeat(900);
      await recorded(page, `script-set the goal ${sized(long)}`);
      await recorded(page, `projectGoalAction("project-goal-save", ${json(label)})`);
      assert.equal((await raw(page, key)).length, 900, 'the legacy store does not bound a goal');
      assert.equal((await codec(page, 'goal.read', [label], { fresh: true })).length, 900);
      await recorded(page, 'fill the goal with spaces');
      await recorded(page, `projectGoalAction("project-goal-save", ${json(label)})`);
      assert.equal((await raw(page, key)).length, 900, 'an empty goal writes nothing');
      assert.equal(await codec(page, 'goal.save', [label, '   '], { fresh: true }), 'empty');
      await recorded(page, `projectGoalAction("project-goal-clear", ${json(label)})`);
      assert.equal(await raw(page, key), null);
      assert.equal(await codec(page, 'goal.read', [label], { fresh: true }), '');
      proved(
        'goal',
        'recorded->codec',
        'recorded-function',
        'the legacy-rendered goal editor, saved through projectGoalAction, writes the trimmed raw text under the encoded-label key; clear removes it. No goal-editor control is rendered on the routes driven here, so the legacy editor markup is built by projectGoalBlock and inserted',
      );

      assert.equal(
        await codec(page, 'goal.save', [label, '  padded goal  '], { fresh: true }),
        'saved',
      );
      assert.equal(await raw(page, key), 'padded goal');
      await recorded(page, `delete projectDraftByLabel[${json(label)}]`);
      assert.equal(await recorded(page, `projectGoal(${json(label)})`), 'padded goal');
      await codec(page, 'goal.save', [label, long]);
      await recorded(page, `delete projectDraftByLabel[${json(label)}]`);
      assert.equal((await recorded(page, `projectGoal(${json(label)})`)).length, 900);
      assert.equal(await codec(page, 'goal.clear', [label]), 'cleared');
      await recorded(page, `delete projectDraftByLabel[${json(label)}]`);
      assert.equal(await recorded(page, `projectGoal(${json(label)})`), '');
      proved(
        'goal',
        'codec->recorded',
        'recorded-function',
        'projectGoal reads the trimmed text, the unbounded 900-unit text and the cleared state the codec wrote',
      );
      const blocked = await newContext({ blocked: true });
      const { page: shut } = await recordedPage(blocked);
      assert.equal(await codec(shut, 'goal.read', [label], { fresh: true }), '');
      assert.equal(await codec(shut, 'goal.save', [label, 'x']), 'unavailable');
      assert.equal(await recorded(shut, `projectGoal(${json(label)})`), '');
      proved(
        'goal',
        'codec',
        undefined,
        'blocked storage reads as empty and a save reports unavailable in the codec, matching the legacy read',
      );
      await blocked.close();
      await context.close();
    },
  );

  // ── codec writes that the real legacy page has to accept ──────────────
  await scenario('codec writes are accepted by the real legacy page', async () => {
    // Graph mode: a codec write merges with the scopes already there instead of replacing the map.
    const graph = await newContext();
    const { page } = await recordedPage(graph, `#n=project:${PROJECT}:decisions`);
    await recorded(page, 'click graph mode All');
    const here = await pure(page, 'graphModeScope', [PROJECT, null]);
    const there = await pure(page, 'graphModeScope', ['another project', 'sid:2']);
    assert.equal(await codec(page, 'graphMode.set', [there, 'decisions'], { fresh: true }), true);
    assert.deepEqual(JSON.parse(await raw(page, KEYS.graphMode)), {
      [here]: 'all',
      [there]: 'decisions',
    });
    await recorded(page, 'reload and wait for All pressed');
    assert.deepEqual(await recorded(page, 'Object.fromEntries(projectGraphModeBySession)'), {
      [here]: 'all',
      [there]: 'decisions',
    });
    proved(
      'graphMode',
      'codec->recorded',
      'recorded-ui',
      'a codec set beside a legacy-written scope keeps both; the reloaded legacy page presses the legacy choice and loads the codec one',
    );
    await graph.close();

    // Guardrails: the codec's 50-rule cap on add leaves the page showing exactly the last fifty.
    const cap = await newContext();
    const capSeed = await seedPage(cap);
    for (let index = 0; index < 55; index += 1)
      await codec(capSeed, 'guardrails.add', [PROJECT, `rule ${index}`], { fresh: index === 0 });
    assert.equal(
      JSON.parse(await raw(capSeed, await pure(capSeed, 'guardrailKey', [PROJECT]))).length,
      50,
    );
    await capSeed.close();
    const { page: rails } = await recordedPage(cap, `#n=project:${PROJECT}:console`);
    await recorded(rails, 'wait for a guardrail');
    const texts = await recorded(rails, 'read every guardrail text');
    assert.equal(texts.length, 50);
    assert.equal(texts[0], 'rule 5');
    assert.equal(texts[49], 'rule 54');
    proved(
      'guardrails',
      'codec->recorded',
      'recorded-ui',
      'fifty-five codec adds leave 50 rules, the last fifty, and the legacy console lists exactly those',
    );
    await cap.close();

    // Lease: a codec release is what legacy treats as released, so a waiting legacy tab takes over.
    const lease = await newContext();
    const leaseSeed = await seedPage(lease);
    await codec(leaseSeed, 'lease.write', ['foreign-release-tab', Date.now()], { fresh: true });
    await leaseSeed.close();
    const { page: waiting } = await recordedPage(lease);
    await recorded(waiting, 'wait 500 ms');
    assert.equal(await recorded(waiting, 'nextIsLeader'), false);
    assert.equal(await streamed(waiting), false);
    assert.equal(await codec(waiting, 'lease.release', [], { fresh: true }), true);
    assert.equal(
      await raw(waiting, KEYS.leader),
      null,
      'release removes the key rather than writing a value',
    );
    await recorded(waiting, 'wait for the takeover and its stream');
    assert.ok(await streamed(waiting));
    assert.equal(
      JSON.parse(await raw(waiting, KEYS.leader)).id,
      await recorded(waiting, 'NEXT_TAB_ID'),
    );
    proved(
      'leader',
      'codec->recorded',
      'recorded-passive',
      'after a codec release the key is absent and the waiting legacy tab takes over and opens its stream on its next election',
    );
    await lease.close();

    // Memo: the codec bounds what it writes the way the page does, so raw storage holds 500 units.
    const memo = await newContext();
    const memoSeed = await seedPage(memo);
    const outcome = await pure(memoSeed, 'memoKey', [PROJECT, null, 'outcome']);
    const focus = await pure(memoSeed, 'memoKey', [PROJECT, null, 'focus']);
    await codec(memoSeed, 'memo.write', [outcome, 'y'.repeat(700)], { fresh: true });
    await codec(memoSeed, 'memo.write', [focus, 'a'.repeat(499) + '😀']);
    const rawOutcome = await raw(memoSeed, outcome);
    const rawFocus = await raw(memoSeed, focus);
    assert.equal(rawOutcome.length, 500);
    assert.equal(rawFocus.length, 500);
    assert.equal(rawFocus.charCodeAt(499), 0xd83d);
    await memoSeed.close();
    const { page: shown } = await recordedPage(memo, `#n=project:${PROJECT}`);
    assert.equal(
      await recorded(shown, `nextCockpitBoundMemo(${json(rawFocus)}) === ${json(rawFocus)}`),
      true,
      'legacy would have stored exactly the codec-written text',
    );
    await recorded(shown, 'wait for the outcome field');
    assert.equal(await recorded(shown, 'the outcome field is 500 units long'), 500);
    proved(
      'memo',
      'codec->recorded',
      'recorded-ui',
      'the codec writes 500 units for over-long and surrogate-cut text, equal to what nextCockpitBoundMemo yields, and the legacy page shows all 500',
    );
    await memo.close();
  });

  // ── reading must not write ────────────────────────────────────────────
  await scenario('reads write nothing, in the codec and in legacy', async () => {
    const context = await newContext();
    const seed = await seedPage(context);
    const memoKey = await pure(seed, 'memoKey', [PROJECT, null, 'outcome']);
    const goalKey = await pure(seed, 'goalKey', [PROJECT]);
    const guardKey = await pure(seed, 'guardrailKey', [PROJECT]);
    const liveKey = await pure(seed, 'liveEstimateKey', [CLAUDE]);
    const scope = await pure(seed, 'graphModeScope', [PROJECT, null]);
    // Values that legacy accepts but a tidy-up on load would change; rollback needs them back exactly.
    const stored = {
      [KEYS.usage]: json(
        Object.fromEntries(Array.from({ length: 201 }, (_, index) => [`k${index}`, index + 1])),
      ),
      [guardKey]: json([
        null,
        'plain',
        { text: '  padded  ', enabled: 0 },
        ...Array.from({ length: 60 }, (_, index) => `r${index}`),
      ]),
      [KEYS.graphMode]: json({ '': 'all', [scope]: 'decisions', 'x\u0000y\u0000z': 'all' }),
      [memoKey]: 'm'.repeat(700),
      [goalKey]: '  untrimmed ' + 'g'.repeat(800),
      [KEYS.leader]: '{"id":"someone","ts":"1"}',
      [KEYS.revision]: 'start.7',
      [KEYS.usageConsent]: 'garbled',
      [KEYS.observerConsent]: 'granted',
      [KEYS.workstream]: 'true',
      [KEYS.cockpitProject]: 'a project',
      [liveKey]: '1',
    };
    for (const [key, value] of Object.entries(stored)) await setRaw(seed, key, value);
    const codecReads = await seed.evaluate(
      ([project, identityRow, focusKey]) => {
        const writes = [];
        const originals = {};
        for (const method of ['setItem', 'removeItem', 'clear']) {
          originals[method] = Storage.prototype[method];
          Storage.prototype[method] = function recorder(...args) {
            writes.push([method, args[0]]);
            return originals[method].apply(this, args);
          };
        }
        const before = Object.fromEntries(
          Object.keys(localStorage).map((key) => [key, localStorage.getItem(key)]),
        );
        try {
          const s = globalThis.CompassStorage.createLegacyStorage();
          const scopeKey = globalThis.CompassStorage.graphModeScope(project, null);
          for (let pass = 0; pass < 2; pass += 1) {
            s.usage.counts();
            s.guardrails.rules(project);
            s.graphMode.resolve({ scope: scopeKey });
            s.memo.read(focusKey);
            s.goal.read(project);
            s.lease.read();
            s.revision.read();
            s.usageConsent.get();
            s.observerConsent.get();
            s.workstream.collapsed();
            s.cockpitProject.read();
            s.liveEstimate.on(identityRow);
          }
        } finally {
          for (const method of Object.keys(originals))
            Storage.prototype[method] = originals[method];
        }
        const after = Object.fromEntries(
          Object.keys(localStorage).map((key) => [key, localStorage.getItem(key)]),
        );
        return {
          writes,
          unchanged: JSON.stringify(before) === JSON.stringify(after),
          keys: Object.keys(after).length,
        };
      },
      [PROJECT, CLAUDE, memoKey],
    );
    assert.deepEqual(codecReads.writes, []);
    assert.equal(codecReads.unchanged, true);
    assert.equal(codecReads.keys, Object.keys(stored).length);
    for (const family of receipt.keys())
      proved(
        family,
        'codec',
        undefined,
        'reading, twice, writes nothing and leaves legacy-valid raw values exactly as stored',
      );
    await seed.close();

    // The legacy loaders are the standard: run in one synchronous call so no legacy timer can write between.
    const { page } = await recordedPage(context);
    const legacyWrites = await recorded(
      page,
      `(() => {
      const writes = [];
      const original = {};
      for (const method of ['setItem', 'removeItem', 'clear']) {
        original[method] = Storage.prototype[method];
        Storage.prototype[method] = function(...args){ writes.push([method, args[0]]); return original[method].apply(this, args); };
      }
      try {
        projectUsageCounts = null; projectUsage();
        nextControlsReadRules(${json(PROJECT)});
        projectGraphModeBySession.clear(); projectLoadGraphModes();
        nextCockpitReadMemo(${json(memoKey)}); projectGoal(${json(PROJECT)});
        nextReadLease(); nextUsageConsent(); nextObserverConsent(); nextWorkstreamStoredCollapsed();
        nextLiveMonitorMemory.clear(); nextLiveMonitorOn(${json(CLAUDE)});
      } finally { for (const method of Object.keys(original)) Storage.prototype[method] = original[method]; }
      return writes;
    })()`,
    );
    assert.deepEqual(legacyWrites, [], 'legacy loaders write nothing either, so the codec matches');
    await context.close();
  });

  golden.finish();

  const unproved = [];
  for (const [family, entry] of receipt) {
    if (!entry.recordedToCodec.size) unproved.push(`${family}: recorded->codec`);
    if (!entry.codecToRecorded.size) unproved.push(`${family}: codec->recorded`);
  }
  assert.deepEqual(unproved, [], 'every family proves both directions');
  assert.deepEqual(problems.external, [], 'no external request');
  assert.deepEqual(problems.pageErrors, [], 'no page error');
  assert.deepEqual(problems.unexpectedPosts, [], 'no action request: every request was a GET');

  // Strongest evidence per family and direction; a headline that lumped them would overclaim.
  const rank = ['recorded-ui', 'recorded-passive', 'recorded-function'];
  const evidence = { directions: 24, ui: 0, passive: 0, recordedFunction: 0, codecLevelChecks: 0 };
  for (const entry of receipt.values()) {
    for (const side of [entry.recordedToCodec, entry.codecToRecorded]) {
      const strongest = rank.find((how) => side.has(how));
      if (strongest === rank[0]) evidence.ui += 1;
      else if (strongest === rank[1]) evidence.passive += 1;
      else evidence.recordedFunction += 1;
    }
    evidence.codecLevelChecks += entry.codecLevel.length;
  }
  assert.equal(evidence.ui + evidence.passive + evidence.recordedFunction, receipt.size * 2);

  const families = [...receipt].map(([name, entry]) => ({
    family: name,
    key: entry.key,
    recordedToCodec: Object.fromEntries(
      [...entry.recordedToCodec].map(([how, checks]) => [how, checks]),
    ),
    codecToRecorded: Object.fromEntries(
      [...entry.codecToRecorded].map(([how, checks]) => [how, checks]),
    ),
    codecLevel: entry.codecLevel,
  }));
  console.log(
    JSON.stringify(
      {
        storageConformance: {
          browser: browser.version(),
          previousPage:
            'recorded from the real Python runtime over a synthetic fixture, models/usage/notifications/focus disabled; the page no longer exists',
          codec: 'frontend/src/storage bundled with Vite and executed in the page',
          evidence,
          externalRequests: 0,
          actionRequests: 0,
          observations,
          families,
        },
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
