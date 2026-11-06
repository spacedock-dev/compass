// @vitest-environment node
/* The terminal's port of the Drift card's shape against the page. Each case is the published JSON a freshly
   loaded page receives: the session row, the payload bits the page reads and the focused context's body, with
   no unsaved typing, no Show-more pages and the live monitor off. The expected view is what THIS page derives
   from it, written by `COMPASS_WRITE_DRIFT_PARITY=1 pnpm exec vitest run frontend/src/drift/terminalParity` and
   reviewed by hand. `tests/test_drift_view.py` reads the same two files, so the page and the terminal are held
   to one answer.

   The expected values must never be regenerated from the Python port: a file the port wrote would agree with
   the port by construction and prove nothing. A change to the page's rules rewrites them from the page, and the
   port follows. */
import { readFileSync, writeFileSync } from 'node:fs';
import { gunzipSync, gzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { contextKey } from '../api/identity';
import { createHeld } from '../intent/held';
import type { Row } from '../observed';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import { buildModel } from './model';
import { resultState } from './result';
import {
  ASSISTANT_ONLY,
  BASELINE_OPEN,
  CHECK_DOES_NOT_SHOW_IT,
  CHECK_READ_INCOMPLETE,
  CLAIM_UNCITED,
  DERIVED_ONLY,
  FAILED_CHECK_ON_RECORD,
  FAILED_CHECK_UNREAD,
  MALFORMED,
  OWN_WORDS_ONLY,
  STORED_WHY,
  UNCITED,
} from './sentences';
import {
  generatedCases,
  GENERATED_FIRST_SEED,
  GENERATED_SEEDS,
  namedCases,
  RULES,
  type DriftCase,
} from './terminalParity.corpus.test.helper';

const NAMED_FILE = new URL('../../test/fixtures/drift-parity.json', import.meta.url);
const GENERATED_FILE = new URL(
  '../../test/fixtures/drift-parity-generated.json.gz',
  import.meta.url,
);

/* The page words a row's reason in sentences; the port says it as the closed token the producer stores, so a
   sentence is mapped to its token here and an unfamiliar one fails the write rather than leaking through. */
const WHY = new Map<string, string>([
  [BASELINE_OPEN, 'baseline-open'],
  [MALFORMED, 'malformed'],
  [UNCITED, 'uncited'],
  [CHECK_DOES_NOT_SHOW_IT, 'check-does-not-show-it'],
  [CHECK_READ_INCOMPLETE, 'check-read-incomplete'],
  [CLAIM_UNCITED, 'claim-uncited'],
  [DERIVED_ONLY, 'board-quoting-itself'],
  [ASSISTANT_ONLY, 'no-work-shown'],
  [OWN_WORDS_ONLY, 'uncorroborated'],
  [FAILED_CHECK_ON_RECORD, 'failed-check-on-record'],
  [FAILED_CHECK_UNREAD, 'failed-check-unread'],
]);
for (const [token, sentence] of Object.entries(STORED_WHY)) {
  if (!WHY.has(sentence)) WHY.set(sentence, token);
}

function whyToken(sentence: string): string {
  if (!sentence) return '';
  const token = WHY.get(sentence);
  if (token === undefined) throw new Error(`no token for the reason: ${sentence}`);
  return token;
}

function limitToken(sentence: string): string {
  if (!sentence) return '';
  return sentence === STORED_WHY['not-asked'] ? 'not-asked' : 'route';
}

/* What the Drift card would hold for the case's session on a fresh load, projected onto closed tokens, numbers
   and the reader's own words. Nothing here is a sentence of the page's. */
export function pageView(item: DriftCase): unknown {
  const session = item.session as Row;
  const payload = item.payload as Row;
  const contexts = new Map([
    [contextKey('p', session as never), { data: item.context as never, revision: 1, error: null }],
  ]);
  const model = buildModel({
    session,
    payload,
    base: payload,
    project: 'p',
    projectKey: 'p',
    contexts,
    held: createHeld({ clock: createFakeClock(), announcer: createAnnouncer() }),
    liveOn: false,
  });
  const numbers = (ids: readonly string[]): string[] => ids.map((id) => model.labels.get(id) ?? '');
  const shape = model.shape;
  const view = {
    harness: model.harness,
    sid: String(session['sid']),
    annotate: model.annotate,
    reading: shape !== null,
    malformed: shape?.malformed ?? '',
    unsettled: model.unsettled,
    drafted: model.drafted,
    limited: model.limit !== '',
    entry_count: model.entryCount,
    window_count: model.windowCount,
    lines: (shape?.criteria ?? []).map((row) => ({
      key: row.key,
      state: resultState(row),
      result: row.result,
      why: whyToken(row.why),
      rests_on: row.restsOn,
      limit: limitToken(row.limit),
      clause: row.clauseKnown ? row.clause : '',
      detail: row.detail,
      cites: [...row.citedIds],
      numbers: numbers(row.citedIds),
      unloaded: row.unloaded,
      partial: Boolean(row.coverage),
    })),
    departures: (shape?.departures ?? []).map((row) => row.key),
    cited: [...model.cited].sort(),
    priors: model.priors.map((prior) => ({
      key: prior.key,
      read_at: prior.readAt,
      answer: prior.answer,
      cites: [...prior.cites],
      numbers: numbers(prior.cites),
      clause: prior.row.clause,
      detail: prior.row.detail,
    })),
  };
  return JSON.parse(JSON.stringify(view)) as unknown;
}

interface Recorded extends DriftCase {
  readonly expected: unknown;
}
interface Fixture {
  readonly rules?: readonly string[];
  readonly cases: readonly Recorded[];
}

function record(items: readonly DriftCase[]): { kept: Recorded[]; dropped: number } {
  const kept: Recorded[] = [];
  let dropped = 0;
  for (const item of items) {
    try {
      kept.push({ ...item, expected: pageView(item) });
    } catch {
      dropped += 1;
    }
  }
  return { kept, dropped };
}

/* One case to a line, so a changed answer reads as a changed line in review. */
function write(file: URL, fixture: Fixture): void {
  const head = fixture.rules ? `"rules": ${JSON.stringify(fixture.rules)},\n` : '';
  const body = fixture.cases.map((item) => `  ${JSON.stringify(item)}`).join(',\n');
  const text = `{\n${head}"cases": [\n${body}\n]\n}\n`;
  /* The generated set is about 700 KB of JSON, so it is stored compressed. */
  writeFileSync(file, file.pathname.endsWith('.gz') ? gzipSync(text, { level: 9 }) : text);
}

const read = (file: URL): Fixture => {
  const bytes = readFileSync(file);
  const text = file.pathname.endsWith('.gz')
    ? gunzipSync(bytes).toString('utf8')
    : bytes.toString('utf8');
  return JSON.parse(text) as Fixture;
};

/* At collection, before the files are read below. */
if (process.env['COMPASS_WRITE_DRIFT_PARITY'] === '1') {
  write(NAMED_FILE, { rules: RULES, cases: record(namedCases()).kept });
  write(GENERATED_FILE, { cases: record(generatedCases()).kept });
}

describe('the shape the terminal is held to', () => {
  describe('the named cases', () => {
    const { cases } = read(NAMED_FILE);

    it('lists every rule at least once', () => {
      const covered = new Set(cases.flatMap((item) => item.rules));
      expect(RULES.filter((rule) => !covered.has(rule))).toEqual([]);
    });

    it('records the corpus the code builds, so a case cannot go stale in the file', () => {
      const built = namedCases().map(({ name, rules, session, payload, context }) => ({
        name,
        rules,
        session,
        payload,
        context,
      }));
      const held = cases.map(({ name, rules, session, payload, context }) => ({
        name,
        rules,
        session,
        payload,
        context,
      }));
      expect(JSON.parse(JSON.stringify(built))).toEqual(held);
    });

    it.each(cases.map((item) => [item.name, item] as const))('%s', (_name, item) => {
      expect(pageView(item)).toEqual(item.expected);
    });
  });

  describe('the generated cases', () => {
    const { cases } = read(GENERATED_FILE);

    it('holds the seeded set, with a share on each harness', () => {
      expect(cases.length).toBeGreaterThan(GENERATED_SEEDS * 0.9);
      expect(String(cases[0]?.name)).toBe(`generated-${String(GENERATED_FIRST_SEED)}`);
      const harnesses = new Set(cases.map((item) => String(item.session['harness'])));
      expect([...harnesses].sort()).toEqual(['claude', 'codex', 'pi']);
    });

    it('agrees with the page on every case', () => {
      const wrong = cases.filter(
        (item) => JSON.stringify(pageView(item)) !== JSON.stringify(item.expected),
      );
      expect(wrong.map((item) => item.name)).toEqual([]);
    });
  });
});
