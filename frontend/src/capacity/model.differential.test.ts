// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { mulberry32, pick } from '../observed/generate.test.helper';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import { genCapacity } from './generate.test.helper';
import { loadLegacyCapacity } from './legacy.test.helper';
import { clockWords, modelLimits, projectSpread, stripRows } from './model';

/* The strip's rows, model sub-limits, clock words and project spread are held to `next-capacity.js` by what
   they compute, over generated boards that publish windows with and without a clock, a reset already past,
   a vendor clock ahead of ours, a budget exactly spent, a recent pace measured at zero against an absent
   one, hostile model labels and a history with idle gaps. */
const legacy = loadLegacyCapacity();
const CASES = 80;
const SEEDS = CASES;
const SPREAD_SEEDS = 600;

describe('the capacity model agrees with the legacy page', () => {
  it(`rows, in rank order and in every figure, over ${String(SEEDS)} boards`, () => {
    const failures: string[] = [];
    const seen = { rows: 0, timed: 0, flat: 0, thin: 0, spent: 0, untimed: 0, models: 0 };
    for (let seed = 1; seed <= SEEDS && failures.length < 3; seed += 1) {
      const { payload } = genCapacity(seed);
      const mine = stripRows(payload);
      const found = firstDifference(canonical(legacy.rows(payload)), canonical(mine));
      if (found) failures.push(`seed ${String(seed)}: ${found}`);
      seen.rows += mine.length;
      seen.timed += mine.filter((row) => row.windowMinutesLeft !== null).length;
      seen.flat += mine.filter((row) => row.recentFlat).length;
      seen.thin += mine.filter((row) => row.thinBasis).length;
      seen.spent += mine.filter((row) => row.left === 0).length;
      seen.untimed += mine.filter((row) => row.elapsed === null).length;
      seen.models += mine.reduce((total, row) => total + row.models.length, 0);
    }
    expect(failures).toEqual([]);
    // The comparison is not vacuous: every branch the strip words differently is reached.
    expect(seen.rows).toBeGreaterThan(60);
    expect(seen.timed).toBeGreaterThan(15);
    expect(seen.flat).toBeGreaterThan(0);
    expect(seen.thin).toBeGreaterThan(0);
    expect(seen.spent).toBeGreaterThan(0);
    expect(seen.untimed).toBeGreaterThan(10);
    expect(seen.models).toBeGreaterThan(10);
  });

  it('model sub-limits keep a measured zero, refuse fractions and strings, and bound the rest', () => {
    const rnd = mulberry32(5);
    const labels = ['Opus', '', '  ', 'z'.repeat(80), '<i>', 'ü', 7, null, '  x '];
    const levels = [0, 1, 50, 100, 2.5, '5', null, -3];
    for (let round = 0; round < Math.min(400, SEEDS); round += 1) {
      const raw = Array.from({ length: Math.floor(rnd() * 13) }, () =>
        rnd() < 0.05 ? null : { label: pick(rnd, labels), pct: pick(rnd, levels) },
      );
      expect(canonical(modelLimits(raw))).toEqual(canonical(legacy.models(raw)));
    }
    expect(modelLimits({ not: 'a list' })).toEqual([]);
    expect(modelLimits([{ label: 'Opus', pct: 0 }])).toEqual([{ label: 'Opus', pct: 0 }]);
  });

  it('clock words are day-qualified exactly as the page words them', () => {
    const rnd = mulberry32(9);
    const generated = 1_800_000_000 + Math.floor(rnd() * 86_400);
    const offsets = [0, 60, 3600, 86400, 3 * 86400, 6.9 * 86400, 7 * 86400, 20 * 86400, -3600];
    for (const offset of offsets) {
      const stamp = generated + offset;
      expect(clockWords(stamp, generated)).toBe(legacy.clock(stamp, generated));
    }
    expect(clockWords(null, generated)).toBe(legacy.clock(null, generated));
    expect(clockWords(generated, null)).toBe(legacy.clock(generated, null));
  });

  it(`the project spread is the legacy sentence over ${String(SPREAD_SEEDS)} boards`, () => {
    let sentences = 0;
    let aside = 0;
    for (let seed = 1; seed <= SPREAD_SEEDS; seed += 1) {
      const { payload } = genCapacity(seed);
      for (const harness of ['claude', 'cursor', 'codex']) {
        const old = legacy.spread(payload, harness) as string;
        const mine = projectSpread(payload, harness);
        if (old === '') {
          expect(mine, `seed ${String(seed)} ${harness}`).toBeNull();
          continue;
        }
        expect(mine, `seed ${String(seed)} ${harness}`).not.toBeNull();
        const text = new DOMParser().parseFromString(old, 'text/html').body.textContent ?? '';
        expect(text).toContain(String(mine?.project));
        expect(text).toContain(`from ${String(mine?.count)} observed.`);
        sentences += 1;
        if (mine && mine.unmeasured > 0) {
          aside += 1;
          expect(text).toContain(`${String(mine.unmeasured)} more session`);
        }
      }
    }
    expect(sentences).toBeGreaterThan(20);
    expect(aside).toBeGreaterThan(0);
  });
});
