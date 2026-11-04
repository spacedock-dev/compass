import { longDiagnostic, type LongStopReason } from './longDiagnostic';
import { longResourcePlan, type LongResourcePlan } from './longPlan';

export interface SourceUsage {
  readonly io_bytes: number;
  readonly pages: number;
  readonly retained_graph_peak_bytes: number;
  readonly retained_graph_peak_units: number;
  readonly prepare_ms: number;
}
export interface SourceCoverage {
  readonly frozen_streams: number;
  readonly frozen_bytes: number;
  readonly verified_streams: number | null;
  readonly source_verified: boolean | null;
  readonly streams_omitted: number;
  readonly gap_records: number;
  readonly gaps_omitted: number;
  readonly inventory_gap_records: number;
  readonly inventory_gaps_omitted: number;
  readonly unexpanded_extent_unknown: boolean;
  readonly usage: SourceUsage | null;
}
export interface EvidenceCoverage {
  readonly planned_passes: number;
  readonly planned_primary_ranges: number;
  readonly usable_primary_ranges: number;
  readonly failed_primary_ranges: number;
  readonly unassigned_primary_ranges: number;
}
export interface LongCoverage {
  readonly source: SourceCoverage | null;
  readonly maps: EvidenceCoverage | null;
  readonly limits: Pick<
    LongResourcePlan['limits'],
    'source_bytes' | 'source_pages' | 'prepare_ms' | 'retained_bytes' | 'retained_units'
  >;
  readonly stop_reason: LongStopReason | null;
}
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const selected = (value: unknown, names: readonly string[]): value is Record<string, unknown> =>
  object(value) && names.every((name) => Object.hasOwn(value, name));
const count = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const records = (value: unknown): value is unknown[] => Array.isArray(value) && value.length <= 512;

function usage(value: unknown): SourceUsage | null {
  const names = [
    'io_bytes',
    'pages',
    'retained_graph_peak_bytes',
    'retained_graph_peak_units',
    'prepare_ms',
  ];
  if (!selected(value, names) || !names.every((name) => count(value[name]))) return null;
  // Measured high-water usage can exceed a ceiling at refusal; do not clamp or reinterpret it.
  return Object.fromEntries(names.map((name) => [name, value[name]])) as unknown as SourceUsage;
}

function source(value: unknown): SourceCoverage | null {
  if (
    !selected(value, [
      'frozen_streams',
      'frozen_bytes',
      'verified_streams',
      'source_verified',
      'streams_omitted',
      'gaps',
      'gaps_omitted',
      'inventory_gaps',
      'inventory_gaps_omitted',
      'unexpanded_extent_unknown',
      'usage',
    ]) ||
    !count(value['frozen_streams']) ||
    !count(value['frozen_bytes']) ||
    !(
      value['verified_streams'] === null ||
      (count(value['verified_streams']) && value['verified_streams'] <= value['frozen_streams'])
    ) ||
    !(value['source_verified'] === null || typeof value['source_verified'] === 'boolean') ||
    !count(value['streams_omitted']) ||
    value['streams_omitted'] > value['frozen_streams'] ||
    !records(value['gaps']) ||
    !count(value['gaps_omitted']) ||
    !records(value['inventory_gaps']) ||
    !count(value['inventory_gaps_omitted']) ||
    typeof value['unexpanded_extent_unknown'] !== 'boolean' ||
    value['unexpanded_extent_unknown'] !==
      Boolean(value['inventory_gaps'].length || value['inventory_gaps_omitted']) ||
    (value['source_verified'] === true &&
      (value['verified_streams'] !== value['frozen_streams'] ||
        value['frozen_streams'] === 0 ||
        value['gaps'].length > 0 ||
        value['gaps_omitted'] > 0 ||
        value['unexpanded_extent_unknown']))
  )
    return null;
  // Only record counts are displayed; opaque stream/gap details are never copied or read.
  return {
    frozen_streams: value['frozen_streams'],
    frozen_bytes: value['frozen_bytes'],
    verified_streams: value['verified_streams'],
    source_verified: value['source_verified'],
    streams_omitted: value['streams_omitted'],
    gap_records: value['gaps'].length,
    gaps_omitted: value['gaps_omitted'],
    inventory_gap_records: value['inventory_gaps'].length,
    inventory_gaps_omitted: value['inventory_gaps_omitted'],
    unexpanded_extent_unknown: value['unexpanded_extent_unknown'],
    usage: usage(value['usage']),
  };
}
function maps(value: unknown, maximum: number): EvidenceCoverage | null {
  const names = [
    'planned_passes',
    'planned_primary_ranges',
    'usable_primary_ranges',
    'failed_primary_ranges',
    'unassigned_primary_ranges',
  ];
  if (!selected(value, names) || !names.every((name) => count(value[name]))) return null;
  const copied = Object.fromEntries(
    names.map((name) => [name, value[name]]),
  ) as unknown as EvidenceCoverage;
  return copied.planned_passes <= maximum &&
    copied.usable_primary_ranges + copied.failed_primary_ranges <= copied.planned_primary_ranges
    ? copied
    : null;
}

/** Independent small display sections: malformed/missing measurements remain unknown. */
export function longCoverage(value: unknown): LongCoverage | null {
  const diagnostic = longDiagnostic(value);
  if (diagnostic === null || !object(value)) return null;
  const plan = longResourcePlan(value['plan']);
  if (plan === null) return null;
  return {
    source: source(value['source']),
    maps: maps(value['maps'], plan.max_evidence_passes),
    limits: {
      source_bytes: plan.limits.source_bytes,
      source_pages: plan.limits.source_pages,
      prepare_ms: plan.limits.prepare_ms,
      retained_bytes: plan.limits.retained_bytes,
      retained_units: plan.limits.retained_units,
    },
    stop_reason: diagnostic.stop_reason ?? null,
  };
}
