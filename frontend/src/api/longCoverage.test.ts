import { describe, expect, it } from 'vitest';
import { LONG_DIAGNOSTIC } from '../../test/longDiagnostic';
import { FAILED_EVIDENCE_DIAGNOSTIC, SOURCE_GAP_DIAGNOSTIC } from '../../test/longCoverage';
import { longCoverage } from './longCoverage';
import { longDiagnostic } from './longDiagnostic';

describe('selected long coverage measurements', () => {
  it('projects measured counts and actual frozen ceilings without retaining opaque detail', () => {
    const result = longCoverage(FAILED_EVIDENCE_DIAGNOSTIC);
    expect(result?.maps).toEqual({
      planned_passes: 3,
      planned_primary_ranges: 6,
      usable_primary_ranges: 4,
      failed_primary_ranges: 2,
      unassigned_primary_ranges: 1,
    });
    expect(result?.source?.gap_records).toBe(0);
    expect(result?.source?.usage?.io_bytes).toBe(24576);
    expect(result?.limits.prepare_ms).toBe(LONG_DIAGNOSTIC.plan.limits.prepare_ms);
    expect(JSON.stringify(result)).not.toContain('streams":[');
    expect(result).not.toHaveProperty('observations');
    expect(longDiagnostic(FAILED_EVIDENCE_DIAGNOSTIC)?.stop_reason).toBe('evidence-pass-failed');
  });

  it('preserves missing sections and absent stop reasons as unknown, not measured zeros', () => {
    const result = longCoverage(LONG_DIAGNOSTIC);
    expect(result?.source).toBeNull();
    expect(result?.maps).toBeNull();
    expect(result?.stop_reason).toBeNull();
    expect(
      longCoverage({
        ...SOURCE_GAP_DIAGNOSTIC,
        source: { ...SOURCE_GAP_DIAGNOSTIC.source, usage: null },
      })?.source?.usage,
    ).toBeNull();
  });

  it('withholds malformed selected sections and rejects foreign stop labels without inferring from usage', () => {
    expect(
      longCoverage({
        ...FAILED_EVIDENCE_DIAGNOSTIC,
        maps: { ...FAILED_EVIDENCE_DIAGNOSTIC.maps, usable_primary_ranges: 7 },
      })?.maps,
    ).toBeNull();
    expect(
      longCoverage({
        ...SOURCE_GAP_DIAGNOSTIC,
        source: { ...SOURCE_GAP_DIAGNOSTIC.source, verified_streams: 3 },
      })?.source,
    ).toBeNull();
    expect(
      longCoverage({
        ...SOURCE_GAP_DIAGNOSTIC,
        source: { ...SOURCE_GAP_DIAGNOSTIC.source, gaps: new Array(513).fill({}) },
      })?.source,
    ).toBeNull();
    for (const stop_reason of [null, false, 'raw exception text']) {
      expect(longDiagnostic({ ...LONG_DIAGNOSTIC, stop_reason })).toBeNull();
    }
    const atCap = {
      ...SOURCE_GAP_DIAGNOSTIC,
      source: {
        ...SOURCE_GAP_DIAGNOSTIC.source,
        usage: {
          ...SOURCE_GAP_DIAGNOSTIC.source.usage,
          prepare_ms: LONG_DIAGNOSTIC.plan.limits.prepare_ms,
        },
      },
    };
    expect(longCoverage(atCap)?.stop_reason).toBe('source-gap');
    const noReason: Record<string, unknown> = { ...atCap };
    delete noReason['stop_reason'];
    expect(longCoverage(noReason)?.stop_reason).toBeNull();
  });
});
