import { describe, expect, it } from 'vitest';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import { annotationOf } from '../intent/annotation';
import { intentDraft, intentDrafted, type DraftInput } from '../intent/derive';
import { genSession } from '../intent/generate.test.helper';
import { createHeld } from '../intent/held';
import type { WorkEntry, WorkSource } from '../intent/work';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import {
  correctionEdit,
  correctionFailedIds,
  correctionFit,
  correctionIds,
  correctionLength,
  correctionStale,
  correctionStamp,
  correctionText,
  correctionWhole,
  offeredDirection,
  steerOffer,
  steerTrigger,
  CHECK_FAILED_TRIGGER,
} from './correction';
import {
  genAnnotation,
  genAssessment,
  genEntries,
  mulberry32,
  pick,
  type Rng,
} from './generate.test.helper';
import { loadLegacyDrift } from './legacy.test.helper';
import { readingShape } from './shape';

/* The correction's pure half, run next to the legacy page: the edit arithmetic that decides what an
   over-the-cap paste keeps, the text composed from the server's parts and the list's numbers, whether it is
   stale, and whether there is anything to steer from. */
/* The one deliberate departure from what the retired page said (owner, 2026-10-14): every number reads
   "(entry #n in Compass's activity list)" where it read "(#n in Compass)" on the first and "(#n)" after.
   The recorded answer is compared through this projection, which turns the new wording back into the old
   so the rest of the text, the placeholders dropped and the order stay held to the recording. See
   docs/design-frontend-migration.md#held-to-recorded-answers. */
function recordedNumbering(text: string): string {
  let first = true;
  return text.replace(/ \(entry #(\d+) in Compass's activity list\)/g, (_all, n: string) => {
    const said = first ? ` (#${n} in Compass)` : ` (#${n})`;
    first = false;
    return said;
  });
}

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
  'NEXT_COCKPIT_CORRECTION_CAP',
  'NEXT_COCKPIT_STEER_HARNESSES',
  'nextCockpitCorrectionEdit',
  'nextCockpitCorrectionWhole',
  'nextCockpitCorrectionFit',
  'nextCockpitCorrectionLength',
  'nextCockpitCorrectionText',
  'nextCockpitCorrectionStamp',
  'nextCockpitCorrectionIds',
  'nextCockpitCorrectionFailedIds',
  'nextCockpitCorrectionStale',
  'nextFailedChecksAfterPerson',
  'nextCockpitFailedChecks',
  'nextCockpitSteerOffer',
  'nextCockpitOfferedDirection',
  'nextCockpitSteerTrigger',
  'nextCockpitEntryNumbers',
]);
legacy.lift(['fmtDur'], 'next-cockpit-compat.js');

const CASES = 60;
const SEEDS = CASES;
// Edits are cheap to answer and cheap to store: a few hundred cover the emoji, the caret and the cap arms.
const EDITS = 150;
const text = (html: string): string => {
  const node = document.createElement('div');
  node.innerHTML = html;
  return node.textContent ?? '';
};

const RUNS = ['a', 'b', 'é', 'é', '👩‍👩‍👧', '😀', ' ', '\n', 'xyz', '', 'ab'];

function genText(rnd: Rng, length: number): string {
  return Array.from({ length }, () => pick(rnd, RUNS)).join('');
}

describe('the correction edit arithmetic matches the legacy page', () => {
  it("cuts the inserted run and never the reader's text, on generated edits", () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= EDITS && failures.length < 3; seed += 1) {
      const rnd = mulberry32(seed + 400);
      const before = genText(rnd, Math.floor(rnd() * 40));
      const cut = Math.floor(rnd() * (before.length + 1));
      const insert = genText(rnd, Math.floor(rnd() * 50));
      const typed = before.slice(0, cut) + insert + before.slice(cut);
      const caret = pick(rnd, [cut + insert.length, undefined, null, -1, typed.length + 3]);
      for (const compare of [
        ['edit', () => correctionEdit(before, typed, caret as never), 'nextCockpitCorrectionEdit'],
      ] as const) {
        const [name, mine, legacyName] = compare;
        const theirs = legacy.call(legacyName, before, typed, caret);
        const found = firstDifference(canonical(theirs), canonical(mine()));
        if (found) failures.push(`seed ${String(seed)} ${name}: ${found}`);
      }
      const run = [...insert];
      const room = Math.floor(rnd() * 30) - 3;
      if (legacy.call('nextCockpitCorrectionWhole', run, room) !== correctionWhole(run, room)) {
        failures.push(`seed ${String(seed)} whole`);
      }
      // A cap this small makes the fit reachable from short strings; the legacy cap is 2,000.
      const long = genText(rnd, 5) + 'x'.repeat(rnd() < 0.5 ? 1995 : 10);
      const typedLong = long.slice(0, cut) + insert + long.slice(cut);
      const fit = correctionFit(long, typedLong, cut + insert.length);
      const fitA = legacy.call('nextCockpitCorrectionFit', long, typedLong, cut + insert.length);
      const found = firstDifference(canonical(fitA), canonical(fit));
      if (found) failures.push(`seed ${String(seed)} fit: ${found}`);
      if (legacy.call('nextCockpitCorrectionLength', typed) !== correctionLength(typed)) {
        failures.push(`seed ${String(seed)} length`);
      }
    }
    expect(failures).toEqual([]);
  });
});

describe('the correction text, staleness and offer match the legacy page', () => {
  it(`agree on ${String(SEEDS)} generated sessions`, () => {
    const failures: string[] = [];
    const seen: Record<string, number> = {};
    const note = (name: string) => {
      seen[name] = (seen[name] ?? 0) + 1;
    };
    for (let seed = 1; seed <= SEEDS && failures.length < 3; seed += 1) {
      const rnd = mulberry32(seed + 900);
      const harness = pick(rnd, ['claude', 'claude', 'codex']);
      const entries = genEntries(rnd, harness) as unknown as WorkEntry[];
      const annotation = genAnnotation(rnd);
      const session: Record<string, unknown> = {
        ...genSession(rnd, seed),
        harness,
        sid: 's1',
        first_prompt: 'Fix it',
        first_prompt_at: 100,
        annotation_window_start: pick(rnd, [100, null, 0]),
      };
      for (const [name, value] of Object.entries(annotation)) session[`annotation_${name}`] = value;
      const ann = annotationOf(session as never);
      const raw = rnd() < 0.7 ? genAssessment(rnd, entries as never) : null;
      const source: WorkSource = {
        state: pick(rnd, ['read', 'read', 'empty', 'unread']) as WorkSource['state'],
        entries,
        all: entries,
        scan: pick(rnd, [null, { last_user_at: 150 }]),
      };
      const annotate = pick(rnd, [true, true, false]);
      legacy.setData({ annotate, generated: 1000 });
      const payload = { annotate, generated: 1000 };
      const shape = readingShape(raw, ann, entries, '', false, () => 'typed');
      const legacyShape = legacy.call(
        'nextCockpitReadingShape',
        raw,
        ann,
        entries,
        '',
        false,
        () => 'typed',
        {},
      );
      const numbers = new Map<string, number>();
      let n = 0;
      for (const entry of entries) {
        if (rnd() >= 0.7) continue;
        n += 1;
        numbers.set(entry.id, n);
      }
      const parts = Array.from({ length: Math.floor(rnd() * 6) }, () =>
        pick<unknown>(rnd, [
          'Words. ',
          { entry: pick(rnd, ['e1', 'e2', 'zz']) },
          ' more ',
          { entry: 'e0' },
        ]),
      );
      if (
        legacy.call('nextCockpitCorrectionText', parts, numbers) !==
        recordedNumbering(correctionText(parts as never, labels(numbers)))
      ) {
        failures.push(`seed ${String(seed)} text`);
      }
      if (legacy.call('nextCockpitCorrectionStamp', ann) !== correctionStamp(ann)) {
        failures.push(`seed ${String(seed)} stamp`);
      }
      const idsA = legacy.call<Set<string> | null>('nextCockpitCorrectionIds', source);
      const idsB = correctionIds(source);
      if (JSON.stringify(idsA && [...idsA]) !== JSON.stringify(idsB && [...idsB])) {
        failures.push(`seed ${String(seed)} ids`);
      }
      const failedA = legacy.call('nextCockpitCorrectionFailedIds', session, source);
      if (
        JSON.stringify(failedA) !== JSON.stringify(correctionFailedIds(session as never, source))
      ) {
        failures.push(`seed ${String(seed)} failed ids`);
      }
      const held = {
        parts: pick(rnd, [parts, null]),
        stale: pick(rnd, [undefined, true]),
        stamp: pick(rnd, [correctionStamp(ann), '[1,null,null]', null]),
        cited: pick(rnd, [['e0'], ['e1', 'gone'], null]),
        failed: pick(rnd, [[], ['e1'], null]),
      };
      const staleA = legacy.call('nextCockpitCorrectionStale', held, ann, source, session);
      const staleB = correctionStale(held as never, ann, source, session as never);
      if (staleA !== staleB)
        failures.push(`seed ${String(seed)} stale: ${String(staleA)} / ${String(staleB)}`);
      note(`stale:${String(staleB)}`);

      const clock = createFakeClock();
      const input: DraftInput = {
        held: createHeld({ clock, announcer: createAnnouncer() }),
        contexts: new Map(),
        payload: payload as never,
        session: session as never,
        annotation: ann,
      };
      const drafted = intentDrafted(input);
      const offerA = legacy.call<Record<string, boolean> | null>(
        'nextCockpitSteerOffer',
        session,
        ann,
        source,
        legacyShape,
      );
      const offerB = steerOffer({
        session: session as never,
        annotation: ann,
        source,
        shape,
        annotate,
        drafted,
      });
      const found = firstDifference(canonical(offerA), canonical(offerB));
      if (found) failures.push(`seed ${String(seed)} offer: ${found}`);
      note(
        `offer:${
          offerB
            ? Object.entries(offerB)
                .filter(([, v]) => v)
                .map(([k]) => k)
                .join('+')
            : 'none'
        }`,
      );
      const dirA = legacy.call('nextCockpitOfferedDirection', ann, entries, session, legacyShape);
      const dirB = offeredDirection(ann, entries, session as never, shape, intentDraft(input));
      if (dirA !== dirB) failures.push(`seed ${String(seed)} direction: ${String(dirA)} / ${dirB}`);
      if (offerB) {
        /* Two deviations (2026-10-20, docs/design-frontend-migration.md#the-drift-card-analyze-and-steer-back):
           a departure's trigger names its first cited entry, as its result row does, and a failed check says
           whose check it was. The recorded side is given the same shape and wording. */
        const recorded = legacyShape as { departures: { citedIds?: unknown[] }[] } | null;
        const firstCited = recorded && {
          ...recorded,
          departures: recorded.departures.map((row) => ({
            ...row,
            citedIds: (row.citedIds || []).slice(0, 1),
          })),
        };
        const triggerA = text(
          legacy.call<string>(
            'nextCockpitSteerTrigger',
            offerA,
            firstCited,
            session,
            entries,
            numbers,
            source.scan,
          ),
        ).replace(/^Check failed\b/, CHECK_FAILED_TRIGGER);
        const triggerB = steerTrigger({
          offer: offerB,
          shape,
          session: session as never,
          entries,
          numbers: labels(numbers),
          scan: source.scan,
          generated: 1000,
        });
        if (triggerA !== triggerB)
          failures.push(`seed ${String(seed)} trigger: ${triggerA} / ${triggerB}`);
        if (triggerB) note('trigger');
      }
    }
    expect(failures).toEqual([]);
    for (const name of ['stale:true', 'stale:false', 'trigger']) {
      expect(seen[name] ?? 0, name).toBeGreaterThan(0);
    }
  });
});
