import { describe, expect, it } from 'vitest';
import { LONG_DIAGNOSTIC } from '../../test/longDiagnostic';
import { longDiagnostic } from './longDiagnostic';

describe('the optional long outcome display projection', () => {
  it('copies only outcome, accounting and association fields without promoting opaque producer detail', () => {
    const input = structuredClone(LONG_DIAGNOSTIC);
    const result = longDiagnostic(input);
    expect(result).toEqual({
      outcome: input.outcome,
      complete: false,
      accounting: input.accounting,
      binding: input.binding,
    });
    input.accounting.totals.calls = 8;
    expect(result?.accounting.totals?.calls).toBe(4);
    const opaque = longDiagnostic({
      ...LONG_DIAGNOSTIC,
      source: { source_verified: true, words: 'PRIVATE' },
    });
    expect(opaque?.complete).toBe(false);
    expect(JSON.stringify(opaque)).not.toContain('PRIVATE');
    expect(opaque).not.toHaveProperty('source');
  });

  it('refuses malformed displayed fields and never accepts complete coverage', () => {
    for (const changes of [
      { version: 2 },
      { kind: 'ordinary' },
      { outcome: ['completed'] },
      { complete: true },
      { private: 'words' },
      { binding: { ...LONG_DIAGNOSTIC.binding, revision: 0 } },
      { binding: { ...LONG_DIAGNOSTIC.binding, window_end: 99 } },
      { binding: { ...LONG_DIAGNOSTIC.binding, open_call_at: 1000 } },
      {
        accounting: {
          state: 'unknown',
          totals: LONG_DIAGNOSTIC.accounting.totals,
          attempted_job: 1,
        },
      },
      { accounting: { ...LONG_DIAGNOSTIC.accounting, attempted_job: 0 } },
      {
        accounting: {
          state: 'exact',
          totals: { calls: 18, prompt_bytes: 1, reply_bytes: 18 * 8192 },
          attempted_job: 1,
        },
      },
      {
        accounting: {
          state: 'exact',
          totals: { calls: 1, prompt_bytes: 1, reply_bytes: 1 },
          attempted_job: 1,
        },
      },
    ])
      expect(longDiagnostic({ ...LONG_DIAGNOSTIC, ...changes })).toBeNull();
  });

  it('preserves null unknowns, exact zero, unbound stops and qualified completed outcomes', () => {
    expect(
      longDiagnostic({
        ...LONG_DIAGNOSTIC,
        binding: null,
        accounting: { state: 'unknown', totals: null, attempted_job: null },
      })?.accounting.totals,
    ).toBeNull();
    expect(
      longDiagnostic({
        ...LONG_DIAGNOSTIC,
        accounting: {
          state: 'exact',
          totals: { calls: 0, prompt_bytes: 0, reply_bytes: 0 },
          attempted_job: 0,
        },
      })?.accounting.totals?.calls,
    ).toBe(0);
    expect(
      longDiagnostic({ ...LONG_DIAGNOSTIC, outcome: 'completed', complete: null })?.complete,
    ).toBeNull();
    expect(
      longDiagnostic({ ...LONG_DIAGNOSTIC, outcome: 'completed', binding: null, complete: null }),
    ).toBeNull();
  });
});
