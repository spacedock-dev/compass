import { describe, expect, it } from 'vitest';
import {
  EARLIER_READING,
  LONG_INTERRUPTED_SENTENCE,
  PARTIAL_READING,
  PARTIAL_WHY,
} from '../../test/longReading';
import { check, fact, mountDrift, POLICY, readingPosts, textOf } from './testing';

const facts = [check('c1', 500, 'failed', { result_source: 'failed flag' })];
const session = { annotation_assessment: PARTIAL_READING, annotation_reading_count: 1 };

describe('qualified long outcomes', () => {
  it('keeps the local departure and says why other clauses cannot be judged', async () => {
    const page = mountDrift({ session, facts });
    await page.settle();
    const result = textOf('[data-next-result]');
    expect(result).toContain('The retry check failed.');
    expect(result).toContain("Can't tell");
    expect(result).toContain(PARTIAL_WHY);
    expect(result).not.toMatch(/Nothing departs|On track|All.*consistent/);
    expect(readingPosts(page)).toEqual([]);
  });

  for (const pending of [false, true]) {
    it(`keeps interrupted outcome and labels the older reading${pending ? ' with a pending direction and Pause' : ''}`, async () => {
      const page = mountDrift({
        session: {
          ...session,
          annotation_reading_withheld: LONG_INTERRUPTED_SENTENCE,
          annotation_reading_withheld_at: 1001,
        },
        facts: pending
          ? [...facts, fact('u2', 1050, { summary: 'Use the new queue instead' })]
          : facts,
        ...(pending ? { payload: { reading: { ...POLICY, off: true, consent: false } } } : {}),
      });
      await page.settle();
      expect(textOf('[data-next-drift-body]')).toContain(LONG_INTERRUPTED_SENTENCE);
      expect(textOf('[data-next-result]')).toContain(EARLIER_READING);
      expect(textOf('[data-next-result]')).toContain('The retry check failed.');
      expect(document.querySelectorAll('[data-next-long-interrupted]')).toHaveLength(1);
      expect(readingPosts(page)).toEqual([]);
    });
  }

  it('does not label a newer saved result as preceding an older interruption', async () => {
    const page = mountDrift({
      session: {
        ...session,
        annotation_reading_withheld: LONG_INTERRUPTED_SENTENCE,
        annotation_reading_withheld_at: 999,
      },
      facts,
    });
    await page.settle();
    expect(textOf('[data-next-result]')).not.toContain(EARLIER_READING);
  });
});
