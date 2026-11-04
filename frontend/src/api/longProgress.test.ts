import { describe, expect, it } from 'vitest';
import { EVIDENCE_PROGRESS, LONG_JOB } from '../../test/longProgress';
import { longJobProgress } from './longProgress';

describe('a long job progress snapshot', () => {
  it('preserves unknown measurements and actual planned/current positions independently of the reserved final slot', () => {
    expect(longJobProgress(LONG_JOB)).toEqual(LONG_JOB.progress);
    const actual = longJobProgress({ ...LONG_JOB, progress: EVIDENCE_PROGRESS });
    expect(actual?.evidence).toEqual({ planned: 7, ended: 3, current: 4 });
    expect(actual?.reconciliation.ordinal).toBe(17);
    expect(actual?.accounting.totals?.calls).toBe(4);
  });

  it('copies the snapshot so later caller edits do not change it', () => {
    const supplied = structuredClone({ ...LONG_JOB, progress: EVIDENCE_PROGRESS });
    const result = longJobProgress(supplied);
    supplied.progress.evidence.current = 5;
    supplied.progress.accounting.totals.calls = 5;
    expect(result?.evidence.current).toBe(4);
    expect(result?.accounting.totals?.calls).toBe(4);
  });

  it('refuses ordinary jobs and missing, foreign or malformed metadata', () => {
    for (const value of [
      null,
      {},
      { ...LONG_JOB, mode: 'ordinary' },
      { ...LONG_JOB, progress: null },
      { ...LONG_JOB, plan: { ...LONG_JOB.plan, extra: 'private' } },
      { ...LONG_JOB, plan: { ...LONG_JOB.plan, max_calls: 8 } },
      {
        ...LONG_JOB,
        plan: { ...LONG_JOB.plan, limits: { ...LONG_JOB.plan.limits, source_pages: 0 } },
      },
      { ...LONG_JOB, progress: { ...EVIDENCE_PROGRESS, raw: 'private words' } },
      { ...LONG_JOB, progress: { ...EVIDENCE_PROGRESS, version: 2 } },
    ])
      expect(longJobProgress(value)).toBeNull();
  });

  it('refuses counters outside the frozen plan and contradictory evidence positions', () => {
    const cases = [
      { evidence: { planned: null, ended: 1, current: null } },
      { evidence: { planned: 7, ended: 3, current: 5 } },
      { evidence: { planned: 7, ended: 8, current: null } },
      { evidence: { planned: 17, ended: 0, current: 1 } },
      { evidence: { planned: 7, ended: 0, current: 0 } },
      { evidence: { planned: 7, ended: false, current: 1 } },
      { evidence: { planned: 7, ended: 1.5, current: null } },
      { stage: 'publication' },
      {
        source: { ...EVIDENCE_PROGRESS.source, bytes_read: LONG_JOB.plan.limits.source_bytes + 1 },
      },
      {
        source: { ...EVIDENCE_PROGRESS.source, pages_read: LONG_JOB.plan.limits.source_pages + 1 },
      },
      { source: { ...EVIDENCE_PROGRESS.source, streams_verified: 3 } },
      { source: { ...EVIDENCE_PROGRESS.source, streams_total: 513 } },
      { source: { ...EVIDENCE_PROGRESS.source, bytes_read: Number.NaN } },
      { reconciliation: { ordinal: 8, state: 'not-started' } },
      { reconciliation: { ordinal: 17, state: ['not-started'] } },
      { reconciliation: { ordinal: 17, state: 'running' } },
    ];
    for (const changes of cases)
      expect(
        longJobProgress({ ...LONG_JOB, progress: { ...EVIDENCE_PROGRESS, ...changes } }),
      ).toBeNull();
  });

  it('keeps exact, minimum and unknown distinct and validates actual reservation allocations', () => {
    for (const state of ['exact', 'minimum']) {
      const accounting = { ...EVIDENCE_PROGRESS.accounting, state };
      expect(
        longJobProgress({ ...LONG_JOB, progress: { ...EVIDENCE_PROGRESS, accounting } })
          ?.accounting,
      ).toEqual(accounting);
    }
    for (const accounting of [
      { state: 'unknown', totals: EVIDENCE_PROGRESS.accounting.totals },
      { state: 'exact', totals: null },
      { state: 'provider-usage', totals: null },
      { state: ['exact'], totals: EVIDENCE_PROGRESS.accounting.totals },
      { state: 'exact', totals: { calls: 0, prompt_bytes: 1, reply_bytes: 0 } },
      { state: 'exact', totals: { calls: 4, prompt_bytes: 1, reply_bytes: 8192 } },
      { state: 'exact', totals: { calls: 18, prompt_bytes: 1, reply_bytes: 18 * 8192 } },
      {
        state: 'exact',
        totals: {
          calls: 1,
          prompt_bytes: LONG_JOB.plan.limits.prompt_bytes + 1,
          reply_bytes: 8192,
        },
      },
    ])
      expect(
        longJobProgress({ ...LONG_JOB, progress: { ...EVIDENCE_PROGRESS, accounting } }),
      ).toBeNull();
  });
});
