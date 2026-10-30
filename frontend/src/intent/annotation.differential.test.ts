import { describe, expect, it } from 'vitest';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import {
  annotationDiscarded,
  annotationLines,
  annotationOf,
  discardAccount,
  discardStamp,
  HELD_UNSAFE,
  heldCap,
  outcomeLineSource,
  revisionLine,
} from './annotation';
import {
  genAnnotationFields,
  genRetained,
  genSession,
  mulberry32,
  pick,
} from './generate.test.helper';
import { loadLegacyIntent } from './legacy.test.helper';
import { maskRevisionWords } from '../../test/revisionWordDeviation';
import { withoutLaterFields } from '../../test/legacy_goldens';

/* The annotation reader and the sentences built from it, run next to the legacy functions over generated
   rows. The legacy source is the oracle; a difference is a bug here. */
const legacy = loadLegacyIntent();
const CASES = 80;
const SEEDS = CASES;

function agree(label: string, left: unknown, right: unknown): string | null {
  const masked = (value: unknown): unknown =>
    typeof value === 'string' ? maskRevisionWords(value) : value;
  const found = firstDifference(canonical(masked(left)), canonical(masked(right)));
  return found ? `${label}: ${found}` : null;
}

describe('the annotation reader agrees with the legacy page over generated rows', () => {
  it(`reads the same annotation, lines, stamps and revision line on ${String(SEEDS)} seeds`, () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= SEEDS && failures.length < 3; seed += 1) {
      const rnd = mulberry32(seed);
      const session = rnd() < 0.8 ? genSession(rnd, seed) : { harness: 'x', sid: 'y' };
      const retained = genRetained(rnd, null, seed);
      const payload = {
        generated: pick(rnd, [1000, 1000.5, 50]),
        annotate_discard: pick(rnd, [{ record: 'R', record_standing: 'S' }, {}, undefined]),
      };
      legacy.setData(payload);
      const generated = payload.generated;
      const published = (payload.annotate_discard ?? {}) as Record<string, unknown>;
      const mine = annotationOf(session);
      const theirs = legacy.call('nextCockpitAnnotation', session);
      const found = [
        agree('annotationOf', withoutLaterFields(mine), theirs),
        ...[mine, retained, null].map((row, index) =>
          agree(
            `lines#${String(index)}`,
            annotationLines(row),
            legacy.call('nextAnnotationLines', row),
          ),
        ),
        ...[mine, retained, null].map((row, index) =>
          agree(
            `discarded#${String(index)}`,
            annotationDiscarded(row),
            legacy.call('nextAnnotationDiscarded', row),
          ),
        ),
        ...[mine, retained].map((row, index) =>
          agree(
            `stamp#${String(index)}`,
            discardStamp(row, generated),
            legacy.call('nextAnnotationDiscardStamp', row),
          ),
        ),
        ...[mine, retained].map((row, index) =>
          agree(
            `revision#${String(index)}`,
            revisionLine(row, generated),
            legacy.call('nextProjectRevisionLine', row),
          ),
        ),
        ...[mine, retained].flatMap((row, index) =>
          [session['departures'], retained['departures'], undefined, 'x'].map((departures, which) =>
            agree(
              `account#${String(index)}.${String(which)}`,
              discardAccount(row, departures, published),
              legacy.call('nextAnnotationDiscardAccount', row, departures),
            ),
          ),
        ),
        agree(
          'source',
          outcomeLineSource({ source: 'entry' }),
          legacy.call('nextOutcomeLineSource', { source: 'entry' }),
        ),
        agree(
          'source typed',
          outcomeLineSource({ source: 'typed' }),
          legacy.call('nextOutcomeLineSource', { source: 'typed' }),
        ),
        agree('source null', outcomeLineSource(null), legacy.call('nextOutcomeLineSource', null)),
      ].filter((message): message is string => message !== null);
      if (found.length) failures.push(`seed ${String(seed)}: ${found[0] ?? ''}`);
    }
    expect(failures).toEqual([]);
  });

  it('reaches the discard, the entry source, the past-the-bound revision and the empty-label cases', () => {
    const seen = { discarded: 0, entry: 0, past: 0, blank: 0, known: 0 };
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const rnd = mulberry32(seed);
      const session = genSession(rnd, seed);
      const annotation = annotationOf(session);
      if (annotation) seen.known += 1;
      if (annotationDiscarded(annotation)) seen.discarded += 1;
      if (annotationLines(annotation).some((line) => line.source === 'entry')) seen.entry += 1;
      if (/older saves dropped/.test(revisionLine(annotation, 1000))) seen.past += 1;
      if (session['project'] === '') seen.blank += 1;
    }
    for (const [name, count] of Object.entries(seen)) expect(count, name).toBeGreaterThan(0);
  });

  it('collapses the same characters the legacy box does and caps at the same number', () => {
    const rnd = mulberry32(7);
    expect(HELD_UNSAFE.source).toBe(
      legacy
        .run<RegExp>('NEXT_COCKPIT_HELD_UNSAFE')
        .source.replace(/\\x00-\\x1f/, '\\u0000-\\u001f')
        .replace(/\\x7f/, '\\u007f'),
    );
    for (let seed = 0; seed < 50; seed += 1) {
      legacy.setData({ annotate_cap: pick(rnd, [undefined, 0, -3, 12.4, 'x', 240, 500]) });
      const cap = legacy.run<number>('nextCockpitHeldCap()');
      const payload = legacy.run<{ annotate_cap?: unknown }>('nextData');
      expect(heldCap(payload as Record<string, unknown>)).toBe(cap);
    }
    expect(genAnnotationFields(rnd)).toBeTypeOf('object');
  });
});
