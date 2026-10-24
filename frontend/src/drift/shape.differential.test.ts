import { describe, expect, it } from 'vitest';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import { outcomeLineSource } from '../intent/annotation';
import type { WorkEntry } from '../intent/work';
import { genAnnotation, genAssessment, genEntries, mulberry32, pick } from './generate.test.helper';
import { loadLegacyDrift, retiredWording, withoutKey } from './legacy.test.helper';
import { lineRequestFloors, readingShape } from './shape';
import { seedSample } from '../../test/legacy_goldens';

/* The reading's shape contract, run next to the legacy producer over generated stored readings and evidence.
   A difference is a bug here: the seven rules are the reason a reading can be shown at all. */
const legacy = loadLegacyDrift();
legacy.lift([
  'NEXT_READING_DEPARTURE',
  'NEXT_READING_CONSISTENT',
  'NEXT_READING_UNVERIFIABLE',
  'NEXT_READING_UNSUPPORTED',
  'NEXT_READING_NOT_REACHED',
  'NEXT_READING_RESULTS',
  'NEXT_READING_CRITERION_KEYS',
  'NEXT_READING_ASSISTANT_ONLY',
  'NEXT_READING_UNCITED',
  'NEXT_READING_BASELINE_OPEN',
  'NEXT_READING_CLAUSE_UNRETAINED',
  'NEXT_READING_MALFORMED',
  'NEXT_READING_NOT_ASKED',
  'NEXT_READING_VERDICT_STATED',
  'NEXT_READING_CHECK_DOES_NOT_SHOW_IT',
  'NEXT_READING_CHANGED_AFTER_CHECK',
  'NEXT_READING_CHECK_READ_INCOMPLETE',
  'NEXT_READING_CHECKS_NOT_READ',
  'NEXT_READING_TELLS_THE_PERSON',
  'NEXT_READING_FAILED_CHECK_ON_RECORD',
  'NEXT_READING_FAILED_CHECK_UNREAD',
  'NEXT_READING_CLAIM_RECORD_UNREAD',
  'NEXT_READING_CLAIM_UNCITED',
  'NEXT_READING_DERIVED_ONLY',
  'NEXT_READING_OWN_WORDS_ONLY',
  'NEXT_READING_STORED_WHY',
  'NEXT_READING_PI_CHECK_SOURCE',
  'NEXT_READING_COVERAGE_KEYS',
  'NEXT_READING_COVERAGE_GOALS',
  'nextReadingConstraints',
  'nextReadingCopied',
  'nextReadingAgentMessage',
  'nextReadingDemonstratesWork',
  'nextReadingEvidenceAt',
  'nextReadingBeforeWindow',
  'nextCockpitLineRequests',
  'nextReadingCheckSupports',
  'nextReadingSubjectlessPiCheck',
  'nextReadingAuthor',
  'nextReadingCitations',
  'nextCockpitReadingCriterion',
  'nextCockpitLineLabel',
  'nextCockpitReadingClause',
  'nextReadingCoverage',
  'nextReadingWindowPartial',
  'nextCockpitReadingShape',
]);

const CASES = 60;
// The first seed that reaches each of the result kinds the first seeds miss.
const WITNESSES = [144, 165, 257];
const SAMPLE = seedSample(CASES, WITNESSES);
const SEEDS = SAMPLE.length;

describe('the reading shape contract holds as the legacy producer holds it', () => {
  it(`agrees on ${String(SEEDS)} generated stored readings`, () => {
    const failures: string[] = [];
    const seen: Record<string, number> = {};
    const note = (name: string) => {
      seen[name] = (seen[name] ?? 0) + 1;
    };
    for (const seed of SAMPLE) {
      if (failures.length >= 3) break;
      const rnd = mulberry32(seed);
      const harness = pick(rnd, ['claude', 'pi', 'codex']);
      const entries = genEntries(rnd, harness);
      const annotation = genAnnotation(rnd);
      const raw = rnd() < 0.05 ? pick(rnd, [null, 'x', 4]) : genAssessment(rnd, entries);
      const limit = pick(rnd, ['', '', 'A route limit.']);
      const unsettled = rnd() < 0.2;
      const lineRequests: Record<string, number> =
        rnd() < 0.3 ? { line_1: pick(rnd, [100, 300]) } : {};
      const theirs = legacy.call<{ criteria: { result: string }[]; malformed: string }>(
        'nextCockpitReadingShape',
        raw,
        annotation,
        entries,
        limit,
        unsettled,
        // The same naming both sides, since the line label is the panel's to supply.
        (line: { k: number; source: string }) => `from ${String(line.k)}`,
        lineRequests,
      );
      const mine = readingShape(
        raw,
        annotation,
        entries as unknown as WorkEntry[],
        limit,
        unsettled,
        (line) => `from ${String(line.k)}`,
        lineRequests,
      );
      for (const row of mine.criteria) note(`result:${row.result}`);
      if (mine.malformed) note('malformed');
      /* A refused reading carries the six fields the legacy page sets and no others; this shape names the
         rest as empty so a caller never reads a missing key. Compared on the legacy page's own keys. */
      const own = theirs.malformed
        ? Object.fromEntries(Object.keys(theirs).map((key) => [key, (mine as never)[key]]))
        : mine;
      /* `unloaded` is this page's own count of cited ids it holds no entry for, and `goalVerdict` carries
         Compass's test of the harness's goal verdict; the retired page had neither field
         (docs/design-frontend-migration.md#held-to-recorded-answers). */
      const found = firstDifference(
        canonical(theirs),
        canonical(retiredWording(withoutKey(withoutKey(own, 'unloaded'), 'goalVerdict'))),
      );
      if (found) failures.push(`seed ${String(seed)}: ${found}`);
    }
    expect(failures).toEqual([]);
    // The generator reaches every result and the two refusal paths, or this proves nothing.
    for (const name of [
      'result:departure',
      'result:consistent with the evidence read',
      'result:not verifiable from available evidence',
      'result:not shown by the record',
      'result:not reached at this stop',
      'malformed',
    ]) {
      expect(seen[name] ?? 0, name).toBeGreaterThan(0);
    }
  });

  it('joins a line request to its unique, non-copied parent entry as the legacy page does', () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= CASES && failures.length < 3; seed += 1) {
      const rnd = mulberry32(seed + 9000);
      const session = { harness: 'claude', sid: 's1' };
      const entries = genEntries(rnd, 'claude');
      const annotation = {
        revision: 3,
        line_1: 'a',
        line_1_source: 'entry',
        line_1_source_id: pick(rnd, ['e1', 'e0']),
        line_2: 'b',
        line_2_source: 'typed',
      } as Record<string, unknown>;
      const parent = entries.find((entry) => entry.id === annotation['line_1_source_id']);
      const source = {
        all: entries,
        entries,
        lineRequests: {
          harness: 'claude',
          sid: pick(rnd, ['s1', 'other']),
          revision: pick(rnd, [3, 2]),
          lines: {
            line_1: {
              at: parent ? pick(rnd, [parent.at, 5]) : 5,
              source_id: annotation['line_1_source_id'],
            },
            line_2: { at: 5, source_id: 'x' },
          },
        },
      };
      const theirs = legacy.call('nextCockpitLineRequests', session, annotation, source);
      const mine = lineRequestFloors(session, annotation, source as never);
      const found = firstDifference(canonical(theirs), canonical(mine));
      if (found) failures.push(`seed ${String(seed)}: ${found}`);
    }
    expect(failures).toEqual([]);
    expect(outcomeLineSource({ source: 'entry' })).toBeTypeOf('string');
  });
});
