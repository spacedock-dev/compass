import { describe, expect, it } from 'vitest';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import type { WorkEntry } from '../intent/work';
import { genAnnotation, genAssessment, genEntries, mulberry32, pick } from './generate.test.helper';
import { loadLegacyDrift, retiredWording, withoutKey } from './legacy.test.helper';
import {
  arrivedLine,
  claimsDrawn,
  coverageLine,
  driftAnswer,
  failedChecksAfterPerson,
  indexEntries,
  recordedTime,
  resultStale,
  resultState,
  resultStatus,
  resultWork,
  resultWhere,
} from './result';
import { readingShape } from './shape';
import { seedSample } from '../../test/legacy_goldens';
import { maskRevisionWords } from '../../test/revisionWordDeviation';

/* The result stage's words, run next to the legacy page's over generated readings: the status line of each
   row, the answer over all of them, where the work went, why a reading is stale. */
const legacy = loadLegacyDrift();

/* The retired page numbered with whole numbers and was recorded that way; the page now reads a label. */
const labels = (numbers: ReadonlyMap<string, number>): ReadonlyMap<string, string> =>
  new Map([...numbers].map(([id, n]) => [id, String(n)]));
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
  'NEXT_RESULT_CANT_TELL',
  'NEXT_RESULT_NOTHING_SHOWS',
  'NEXT_RESULT_CLAIM_TAIL',
  'NEXT_RESULT_DEPARTS',
  'nextCockpitResultWhere',
  'nextCockpitClaimStatus',
  'nextCockpitResultStatus',
  'nextCockpitResultState',
  'nextCockpitClaimsDrawn',
  'nextFailedChecksAfterPerson',
  'nextDriftAnswer',
  'nextDriftRecordedTime',
  'nextReadingArrivedLine',
  'nextCockpitResultStale',
  'nextCockpitResultWork',
  'nextCockpitReadingCoverage',
]);

const CASES = 60;
// The first seed that reaches each of these states: the departs, unshown, consistent and not-reached answers.
const WITNESSES = [149, 175, 278, 594];
const SAMPLE = seedSample(CASES, WITNESSES);
const SEEDS = SAMPLE.length;
/* Text with no whitespace at all: elements the page draws side by side have no space between them in the
   markup string and a gap in the layout, so only the words and their order are compared. */
const text = (html: string): string => {
  const node = document.createElement('div');
  node.innerHTML = html;
  return (node.textContent ?? '').replace(/\s+/g, '');
};
const squash = (value: string): string => value.replace(/\s+/g, '');

describe('the result stage says what the legacy page says', () => {
  it(`agrees on ${String(SEEDS)} generated readings`, () => {
    const failures: string[] = [];
    const seen: Record<string, number> = {};
    const note = (name: string) => {
      seen[name] = (seen[name] ?? 0) + 1;
    };
    for (const seed of SAMPLE) {
      if (failures.length >= 3) break;
      const rnd = mulberry32(seed + 31);
      const harness = pick(rnd, ['claude', 'pi']);
      const entries = genEntries(rnd, harness);
      const annotation = genAnnotation(rnd);
      const raw = genAssessment(rnd, entries);
      const mine = readingShape(
        raw,
        annotation,
        entries as unknown as WorkEntry[],
        pick(rnd, ['', '']),
        rnd() < 0.1,
        (line) => `from ${String(line.k)}`,
      );
      if (mine.malformed) continue;
      // Numbers as the activity list gives them, with some entries left unnumbered.
      const numbers = new Map<string, number>();
      let n = 0;
      for (const entry of entries) {
        if (rnd() >= 0.7) continue;
        n += 1;
        numbers.set(String(entry.id), n);
      }
      const byId = indexEntries(entries as unknown as WorkEntry[]);
      const legacyShape = legacy.call<{ criteria: Record<string, unknown>[] }>(
        'nextCockpitReadingShape',
        raw,
        annotation,
        entries,
        '',
        false,
        (line: { k: number }) => `from ${String(line.k)}`,
        {},
      );
      // The shape differential owns the unsettled and limit arms; this test needs equal inputs to compare.
      const same = readingShape(
        raw,
        annotation,
        entries as unknown as WorkEntry[],
        '',
        false,
        (line) => `from ${String(line.k)}`,
      );
      const scan = pick(rnd, [
        null,
        { last_user_at: 150, window_start: same.windowStart, window_written_paths: 5 },
        { window_start: same.windowStart, window_written_paths: 0 },
        { window_start: 7, window_written_paths: 'x' },
      ]);
      for (const [index, row] of same.criteria.entries()) {
        const theirs = legacyShape.criteria[index];
        for (const short of [false, true]) {
          const a = legacy.call('nextCockpitResultStatus', theirs, numbers, byId, short);
          const b = resultStatus(row, labels(numbers), byId, short);
          const found = firstDifference(canonical(a), canonical(b));
          if (found)
            failures.push(`seed ${String(seed)} status ${row.key}: ${found} (${String(a)} / ${b})`);
        }
        const state = legacy.call('nextCockpitResultState', theirs);
        if (state !== resultState(row)) failures.push(`seed ${String(seed)} state ${row.key}`);
        note(`state:${resultState(row)}`);
        const where = (arrived: boolean) => [
          legacy.call('nextCockpitResultWhere', row.restsOnEntry, numbers, arrived),
          resultWhere(row.restsOnEntry, labels(numbers), arrived),
        ];
        for (const arrived of [false, true]) {
          const [a, b] = where(arrived);
          if (a !== b) failures.push(`seed ${String(seed)} where: ${String(a)} / ${String(b)}`);
        }
      }
      const answerA = legacy.call('nextDriftAnswer', legacyShape, entries, scan);
      const answerB = driftAnswer(same, entries as unknown as WorkEntry[], scan);
      note(`answer:${answerB.kind}`);
      const foundAnswer = firstDifference(
        canonical(answerA),
        canonical(withoutKey(withoutKey(answerB, 'unloaded'), 'goalVerdict')),
      );
      if (foundAnswer) failures.push(`seed ${String(seed)} answer: ${foundAnswer}`);
      const drawn = legacy.call<unknown[]>('nextCockpitClaimsDrawn', legacyShape).length;
      if (drawn !== claimsDrawn(same).length) failures.push(`seed ${String(seed)} claims drawn`);
      const failed = failedChecksAfterPerson(
        entries as unknown as WorkEntry[],
        scan?.last_user_at,
        100,
      );
      const failedA = legacy.call<unknown[]>(
        'nextFailedChecksAfterPerson',
        entries,
        scan?.last_user_at,
        100,
      );
      if (failed.length !== failedA.length) failures.push(`seed ${String(seed)} failed checks`);
      // The reading's windowed work, as a list of folders and files.
      const workHtml = legacy.call<string>(
        'nextCockpitResultWork',
        entries,
        numbers,
        scan,
        same.windowStart,
      );
      const work = resultWork(
        entries as unknown as WorkEntry[],
        labels(numbers),
        scan,
        same.windowStart,
      );
      if (Boolean(workHtml) !== Boolean(work)) failures.push(`seed ${String(seed)} work presence`);
      if (workHtml && work) {
        note('work');
        const node = document.createElement('div');
        node.innerHTML = workHtml;
        const folders = [...node.querySelectorAll('li.next-cockpit-result-folder')].map((li) =>
          [...li.querySelectorAll('span')].map((span) => span.textContent ?? ''),
        );
        const mineFolders = work.groups.map((group) => [
          group.folder || 'The working directory',
          `${String(group.files)} file${group.files === 1 ? '' : 's'}`,
          group.references,
        ]);
        const found = firstDifference(canonical(folders), canonical(mineFolders));
        if (found) failures.push(`seed ${String(seed)} work folders: ${found}`);
        const tail = text(node.querySelector('details,p')?.outerHTML ?? '');
        const expected = work.more
          ? squash(
              `${String(work.more)} more ${String(work.more)} more written ${work.more === 1 ? 'file is' : 'files are'} counted and not listed.`,
            )
          : work.unavailable
            ? squash('The total written in this window is unavailable.')
            : '';
        if (tail !== expected)
          failures.push(`seed ${String(seed)} work tail: ${tail} / ${expected}`);
      }
      const staleRaw = pick(rnd, [raw, { ...raw, read_at: 120, evidence_through: undefined }]);
      const staleHtml = legacy.call<string>(
        'nextCockpitResultStale',
        legacyShape2(same),
        staleRaw,
        annotation,
        entries,
        '',
      );
      const stale = resultStale(same, staleRaw, annotation, entries as unknown as WorkEntry[]);
      if (Boolean(staleHtml) !== Boolean(stale))
        failures.push(`seed ${String(seed)} stale presence`);
      if (stale) {
        note(`stale:${stale.kind}`);
        const expected = squash(maskRevisionWords(`${stale.head} ${stale.superseded}`));
        const recorded = text(maskRevisionWords(staleHtml));
        if (recorded !== expected) {
          failures.push(`seed ${String(seed)} stale text: ${recorded} / ${expected}`);
        }
      }
      const arrivedA = text(legacy.call<string>('nextReadingArrivedLine', annotation, entries));
      if (arrivedA !== squash(arrivedLine(annotation, entries as unknown as WorkEntry[]))) {
        failures.push(`seed ${String(seed)} arrived: ${arrivedA}`);
      }
      const coverageA = text(
        legacy
          .call<string>('nextCockpitReadingCoverage', legacyShape2(same))
          .replace(RETIRED_GOAL_SENTENCE, GOAL_SENTENCE),
      );
      if (coverageA !== squash(coverageLine(same))) {
        failures.push(`seed ${String(seed)} coverage: ${coverageA} / ${coverageLine(same)}`);
      }
      for (const at of [0, null, 'x', 1700000000, 1700000000.9, -5]) {
        if (legacy.call('nextDriftRecordedTime', at) !== recordedTime(at)) {
          failures.push(`recorded time ${String(at)}`);
        }
      }
    }
    expect(failures).toEqual([]);
    for (const name of ['state:departs', 'state:consistent', 'state:cant-tell', 'work']) {
      expect(seen[name] ?? 0, name).toBeGreaterThan(0);
    }
  });
});

/* The legacy functions read plain fields off the shape, and the React shape has the same names. */
/* The shape the retired page's functions are called with. `unloaded` is this page's own count of cited ids
   it holds no entry for; the retired page had no such field and its recorded answers are keyed by their
   arguments, so it is dropped here (docs/design-frontend-migration.md#held-to-recorded-answers). */
function legacyShape2(shape: unknown): unknown {
  return retiredWording(withoutKey(withoutKey(shape, 'unloaded'), 'goalVerdict'));
}

/* A named departure from the retired page. Its goal-source sentence said "Analyze read up to 1,000
   characters" and printed it for a prompt of any length, so it read as a limit that bit. The cap is real
   (a reading takes the head of a prompt's words) and the new sentence says only that. The recorded text is
   compared after this one sentence is swapped. */
const RETIRED_GOAL_SENTENCE = 'The adopted source was found; Analyze read up to 1,000 characters.';
const GOAL_SENTENCE =
  'The adopted source was found. Analyze reads at most the first 1,000 characters of any prompt.';
