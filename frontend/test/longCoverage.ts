import { LONG_DIAGNOSTIC } from './longDiagnostic';

export const SOURCE_GAP_DIAGNOSTIC = {
  ...LONG_DIAGNOSTIC,
  stop_reason: 'source-gap',
  source: {
    reason: 'source_gap',
    frozen_streams: 2,
    frozen_bytes: 8192,
    unexpanded_extent_unknown: true,
    streams: [
      { ordinal: 0, frozen_bytes: 4096, verified_end: 4096 },
      { ordinal: 1, frozen_bytes: 4096, verified_end: null },
    ],
    streams_omitted: 0,
    gaps: [{ stream: 1, start: 0, end: 32, reason: 'unfinished_line', permanent: true }],
    gaps_omitted: 0,
    inventory_gaps: ['streams'],
    inventory_gaps_omitted: 0,
    usage: {
      io_bytes: 24576,
      pages: 9,
      retained_graph_peak_bytes: 1048576,
      retained_graph_peak_units: 2000,
      prepare_ms: 12000,
    },
    source_verified: false,
    verified_streams: 1,
    canonical_fact_count: null,
    eligible_entries: null,
    retained_whole_message_characters: null,
    eligible_message_characters: null,
  },
};
export const FAILED_EVIDENCE_DIAGNOSTIC = {
  ...SOURCE_GAP_DIAGNOSTIC,
  outcome: 'partial',
  stop_reason: 'evidence-pass-failed',
  source: {
    ...SOURCE_GAP_DIAGNOSTIC.source,
    reason: '',
    source_verified: true,
    verified_streams: 2,
    unexpanded_extent_unknown: false,
    gaps: [],
    inventory_gaps: [],
    streams: [
      { ordinal: 0, frozen_bytes: 4096, verified_end: 4096 },
      { ordinal: 1, frozen_bytes: 4096, verified_end: 4096 },
    ],
  },
  maps: {
    reason: 'passes-ended',
    planned_passes: 3,
    planned_primary_ranges: 6,
    planned_primary_characters: 6000,
    usable_primary_ranges: 4,
    failed_primary_ranges: 2,
    unassigned_primary_ranges: 1,
    planned_prompt_bytes: 30000,
    observed_prompt_bytes: 30000,
    candidate_overflow: false,
  },
};
export const RESOURCE_LIMIT_DIAGNOSTIC = {
  ...SOURCE_GAP_DIAGNOSTIC,
  stop_reason: 'resource-limit',
  source: {
    ...SOURCE_GAP_DIAGNOSTIC.source,
    usage: {
      ...SOURCE_GAP_DIAGNOSTIC.source.usage,
      io_bytes: LONG_DIAGNOSTIC.plan.limits.source_bytes,
      prepare_ms: LONG_DIAGNOSTIC.plan.limits.prepare_ms,
    },
  },
};
