import { longResourcePlan } from './longPlan';
import type { LongProgress } from './longProgress';

/** Display projection only. Backend validation owns the unrendered source/maps/observations. */
export interface LongDiagnostic {
  readonly outcome: 'pending' | 'completed' | 'partial' | 'withheld' | 'cancelled' | 'interrupted';
  readonly complete: false | null;
  readonly accounting: LongProgress['accounting'] & { readonly attempted_job: number | null };
  readonly binding: {
    readonly revision: number;
    readonly revision_at: number;
    readonly window_start: number;
    readonly window_end: number | null;
    readonly scope: 'final' | 'last-turn' | 'mid-flight';
    readonly end_kind: 'session-end' | 'turn-stop' | 'running' | 'unobservable' | 'idle-unknown';
    readonly open_call_at: number | null;
    readonly job_started_at: number;
  } | null;
}
const keys = (value: unknown, names: readonly string[]): value is Record<string, unknown> =>
  typeof value === 'object' &&
  value !== null &&
  !Array.isArray(value) &&
  Object.keys(value).length === names.length &&
  names.every((key) => Object.hasOwn(value, key));
const count = (value: unknown, maximum = Number.MAX_SAFE_INTEGER): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= maximum;
const moment = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value < 2 ** 53;
const oneOf = (value: unknown, values: readonly string[]): boolean =>
  typeof value === 'string' && values.includes(value);

function binding(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (
    !keys(value, [
      'revision',
      'revision_at',
      'window_start',
      'window_end',
      'scope',
      'end_kind',
      'open_call_at',
      'job_started_at',
    ])
  )
    return false;
  return (
    count(value['revision']) &&
    value['revision'] > 0 &&
    moment(value['revision_at']) &&
    value['revision_at'] > 0 &&
    moment(value['window_start']) &&
    value['window_start'] <= value['revision_at'] &&
    moment(value['job_started_at']) &&
    value['job_started_at'] > 0 &&
    (value['window_end'] === null ||
      (moment(value['window_end']) && value['window_end'] >= value['window_start'])) &&
    oneOf(value['scope'], ['final', 'last-turn', 'mid-flight']) &&
    oneOf(value['end_kind'], [
      'session-end',
      'turn-stop',
      'running',
      'unobservable',
      'idle-unknown',
    ]) &&
    (value['open_call_at'] === null ||
      (moment(value['open_call_at']) &&
        value['scope'] === 'mid-flight' &&
        value['end_kind'] === 'running'))
  );
}

export function longDiagnostic(value: unknown): LongDiagnostic | null {
  const fields = [
    'version',
    'kind',
    'plan',
    'source',
    'maps',
    'observations',
    'accounting',
    'outcome',
    'complete',
  ];
  if (
    !(keys(value, fields) || keys(value, [...fields, 'binding'])) ||
    value['version'] !== 1 ||
    value['kind'] !== 'long-analysis' ||
    !oneOf(value['outcome'], [
      'pending',
      'completed',
      'partial',
      'withheld',
      'cancelled',
      'interrupted',
    ]) ||
    (value['complete'] !== null && value['complete'] !== false) ||
    (!['pending', 'completed'].includes(String(value['outcome'])) && value['complete'] !== false) ||
    !binding(value['binding']) ||
    (['completed', 'partial'].includes(String(value['outcome'])) && value['binding'] == null)
  )
    return null;
  const plan = longResourcePlan(value['plan']),
    accounting = value['accounting'];
  if (
    plan === null ||
    !keys(accounting, ['state', 'totals', 'attempted_job']) ||
    !oneOf(accounting['state'], ['unknown', 'minimum', 'exact'])
  )
    return null;
  const totals = accounting['totals'];
  if (accounting['state'] === 'unknown') {
    if (totals !== null || accounting['attempted_job'] !== null) return null;
  } else {
    if (
      !keys(totals, ['calls', 'prompt_bytes', 'reply_bytes']) ||
      !count(totals['calls'], plan.max_calls) ||
      !count(totals['prompt_bytes'], plan.limits.input_bytes) ||
      !count(totals['reply_bytes'], plan.limits.output_bytes) ||
      totals['reply_bytes'] !== totals['calls'] * plan.limits.reply_bytes ||
      (totals['calls'] === 0 && totals['prompt_bytes'] !== 0) ||
      accounting['attempted_job'] !==
        (totals['calls'] > 0 ? 1 : accounting['state'] === 'exact' ? 0 : null)
    )
      return null;
  }
  // Only these small, validated scalars leave this reader; opaque sections support no UI claim.
  return JSON.parse(
    JSON.stringify({
      outcome: value['outcome'],
      complete: value['complete'],
      accounting,
      binding: value['binding'] ?? null,
    }),
  ) as LongDiagnostic;
}
