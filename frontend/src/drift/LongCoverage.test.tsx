import { describe, expect, it } from 'vitest';
import {
  FAILED_EVIDENCE_DIAGNOSTIC,
  RESOURCE_LIMIT_DIAGNOSTIC,
  SOURCE_GAP_DIAGNOSTIC,
} from '../../test/longCoverage';
import { LONG_DIAGNOSTIC } from '../../test/longDiagnostic';
import { LONG_JOB } from '../../test/longProgress';
import { PARTIAL_READING, PARTIAL_WHY } from '../../test/longReading';
import { check, driftBoard, mountDrift, readingPosts, textOf } from './testing';
const facts = [check('c1', 500, 'failed', { result_source: 'failed flag' })];
const session = (diagnostic: unknown) => ({
  annotation_assessment: PARTIAL_READING,
  annotation_long_diagnostic: diagnostic,
});
const text = () => textOf('[data-next-long-coverage]');

describe('a person reading saved long coverage and limits', () => {
  it('sees failed and unassigned evidence ranges without losing the local departure or unknown clauses', async () => {
    const page = mountDrift({ facts, session: session(FAILED_EVIDENCE_DIAGNOSTIC) });
    await page.settle();
    expect(text()).toContain('An evidence pass failed.');
    expect(text()).toContain('Evidence passes planned: 3.');
    expect(text()).toContain('Evidence ranges: 6 planned; 4 usable; 2 failed; 1 unassigned.');
    expect(text()).toContain('Source files verified: 2 of 2.');
    expect(text()).toContain('These counts do not establish that all saved work was assessed.');
    expect(textOf('[data-next-result]')).toContain('The retry check failed.');
    expect(textOf('[data-next-result]')).toContain(PARTIAL_WHY);
    expect(text()).not.toMatch(/100%|all.*covered|complete coverage/i);
    await page.poll({
      ...driftBoard({ session: session(FAILED_EVIDENCE_DIAGNOSTIC) }),
      generated: 1200,
    });
    expect(readingPosts(page)).toEqual([]);
  });

  it('shows known source gaps and unknown unexpanded extent rather than implying an empty remainder', async () => {
    const page = mountDrift({ session: session(SOURCE_GAP_DIAGNOSTIC) });
    await page.settle();
    expect(text()).toContain('Source gaps prevented the analysis from covering its saved work.');
    expect(text()).toContain('Source files verified: 1 of 2.');
    expect(text()).toContain('Frozen source extent: 8,192 bytes.');
    expect(text()).toContain('Source gap records: 1; additional records omitted: 0.');
    expect(text()).toContain('Unexpanded source extent is unknown.');
    expect(text()).toContain('Evidence range measurements are unknown.');
    expect(readingPosts(page)).toEqual([]);
  });

  it('shows an explicit resource stop with measured usage against the actual frozen plan', async () => {
    const page = mountDrift({ session: session(RESOURCE_LIMIT_DIAGNOSTIC) });
    await page.settle();
    expect(text()).toContain('A resource limit stopped the analysis.');
    expect(text()).toContain('Native source reads: 268,435,456 / 268,435,456 bytes');
    expect(text()).toContain('Preparation measured: 60,000 / 60,000 ms');
    expect(text()).toContain('model waits excluded');
    expect(text()).toContain('Retained object graph: 1,048,576 / 268,435,456 bytes');
    expect(text()).toContain('not process RSS');
    expect(readingPosts(page)).toEqual([]);
  });

  it('keeps unknown measurements explicit and labels saved outcome separately during a new job', async () => {
    const page = mountDrift({
      session: session(LONG_DIAGNOSTIC),
      payload: { reading_jobs: { 'claude:s1': { ...LONG_JOB, started_at: 2000 } } },
    });
    await page.settle();
    expect(text()).toContain('Stop or limit reason: unknown.');
    expect(text()).toContain('Source coverage measurements are unknown.');
    expect(text()).toContain('Preparation measured: unknown / 60,000 ms');
    expect(text()).toContain('Evidence range measurements are unknown.');
    expect(text()).not.toMatch(/0 of 0|0 failed|0 bytes/);
    expect(textOf('[data-next-long-outcome]')).toContain('Last saved long outcome:');
    expect(textOf('[data-next-long-outcome]')).toContain(
      'Current long analysis is still running; these are saved measurements.',
    );
    expect(textOf('[data-next-long-progress]')).toContain('Collecting source');
    await page.poll({
      ...driftBoard({
        session: session(LONG_DIAGNOSTIC),
        payload: { reading_jobs: { 'claude:s1': { ...LONG_JOB, started_at: 2000 } } },
      }),
      generated: 2100,
    });
    expect(readingPosts(page)).toEqual([]);
  });
});
