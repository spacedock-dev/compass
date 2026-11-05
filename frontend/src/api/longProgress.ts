import { longResourcePlan } from './longPlan';

/** Mirrors reading_long_progress v1. Counters describe measured reads and reservations only. */
export interface LongProgress {
  readonly version: 1;
  readonly stage: 'source' | 'evidence' | 'reconciliation' | 'publication';
  readonly source: {
    readonly streams_total: number | null;
    readonly streams_verified: number | null;
    readonly bytes_read: number | null;
    readonly pages_read: number | null;
  };
  readonly evidence: {
    readonly planned: number | null;
    readonly ended: number;
    readonly current: number | null;
  };
  readonly reconciliation: {
    readonly ordinal: number;
    readonly state: 'not-started' | 'running' | 'ended';
  };
  readonly accounting: {
    readonly state: 'unknown' | 'minimum' | 'exact';
    readonly totals: {
      readonly calls: number;
      readonly prompt_bytes: number;
      readonly reply_bytes: number;
    } | null;
  };
}
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const keys = (value: unknown, names: readonly string[]): value is Record<string, unknown> =>
  object(value) &&
  Object.keys(value).length === names.length &&
  names.every((key) => Object.hasOwn(value, key));
const count = (value: unknown, maximum: number): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= maximum;
const optional = (value: unknown, maximum: number): boolean =>
  value === null || count(value, maximum);
const oneOf = (value: unknown, allowed: readonly string[]): boolean =>
  typeof value === 'string' && allowed.includes(value);
const stages = ['source', 'evidence', 'reconciliation', 'publication'];

/** Ordinary Jobs retain their existing reader and shape. Invalid long metadata is withheld. */
export function longJobProgress(job: unknown): LongProgress | null {
  if (!object(job) || job['mode'] !== 'long') return null;
  const plan = longResourcePlan(job['plan']);
  const value = job['progress'];
  if (
    plan === null ||
    !keys(value, ['version', 'stage', 'source', 'evidence', 'reconciliation', 'accounting']) ||
    value['version'] !== 1 ||
    typeof value['stage'] !== 'string' ||
    !stages.includes(value['stage'])
  )
    return null;
  const source = value['source'],
    evidence = value['evidence'];
  const reconciliation = value['reconciliation'],
    accounting = value['accounting'];
  if (
    !keys(source, ['streams_total', 'streams_verified', 'bytes_read', 'pages_read']) ||
    !keys(evidence, ['planned', 'ended', 'current']) ||
    !keys(reconciliation, ['ordinal', 'state']) ||
    !keys(accounting, ['state', 'totals'])
  )
    return null;
  // 512 is the v1 progress protocol's stream bound; resource ceilings come from the frozen plan.
  if (
    !optional(source['streams_total'], 512) ||
    !optional(source['streams_verified'], 512) ||
    !optional(source['bytes_read'], plan.limits.source_bytes) ||
    !optional(source['pages_read'], plan.limits.source_pages) ||
    (typeof source['streams_total'] === 'number' &&
      typeof source['streams_verified'] === 'number' &&
      source['streams_verified'] > source['streams_total'])
  )
    return null;
  const planned = evidence['planned'],
    ended = evidence['ended'],
    current = evidence['current'];
  if (
    !optional(planned, plan.max_evidence_passes) ||
    !count(ended, plan.max_evidence_passes) ||
    (planned === null && (ended !== 0 || current !== null)) ||
    (typeof planned === 'number' && ended > planned) ||
    (current !== null &&
      (!count(current, typeof planned === 'number' ? planned : 0) ||
        current === 0 ||
        current !== ended + 1 ||
        value['stage'] !== 'evidence')) ||
    (['evidence', 'reconciliation'].includes(value['stage']) && planned === null) ||
    reconciliation['ordinal'] !== plan.max_calls ||
    !oneOf(reconciliation['state'], ['not-started', 'running', 'ended']) ||
    (reconciliation['state'] !== 'not-started' &&
      stages.indexOf(value['stage']) < stages.indexOf('reconciliation'))
  )
    return null;
  const state = accounting['state'],
    totals = accounting['totals'];
  if (state === 'unknown') {
    if (totals !== null) return null;
  } else if (
    !oneOf(state, ['minimum', 'exact']) ||
    !keys(totals, ['calls', 'prompt_bytes', 'reply_bytes']) ||
    !count(totals['calls'], plan.max_calls) ||
    !count(totals['prompt_bytes'], plan.limits.input_bytes) ||
    !count(totals['reply_bytes'], plan.limits.output_bytes) ||
    totals['reply_bytes'] !== totals['calls'] * plan.limits.reply_bytes ||
    totals['prompt_bytes'] > totals['calls'] * plan.limits.prompt_bytes
  )
    return null;
  return JSON.parse(JSON.stringify(value)) as LongProgress;
}

/** Closed optional Job metadata, independent of progress v1 and never an ordinary-job claim. */
export function longCleanupUnresolved(job: unknown): boolean {
  return object(job) && job['mode'] === 'long' && job['blocked_reason'] === 'cleanup-unresolved';
}
