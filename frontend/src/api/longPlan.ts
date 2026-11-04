/** Closed advisory metadata. It is neither source proof nor permission to launch. */
export interface LongPlanDescriptor {
  readonly version: 1;
  readonly mode: 'long';
  readonly supported: boolean;
  readonly can_start: boolean;
  readonly reason: string;
  readonly binding: string | null;
  readonly route: {
    readonly harness: 'claude';
    readonly provider: 'claude' | 'codex';
    readonly model: string;
    readonly words_destination: string;
    readonly destination: string;
    readonly reason: string;
    readonly fallback: boolean;
    readonly ci_read: string;
  } | null;
  readonly intent: { readonly revision: number | null; readonly start_at: number | null };
  readonly source: {
    readonly capability: 'native-claude' | 'unsupported' | 'unknown';
    readonly kinds: readonly string[];
    readonly parent_bytes: number | null;
    readonly observed_at: number | null;
    readonly stream_count: null;
    readonly record_count: null;
    readonly frozen: false;
  };
  readonly allowance: {
    readonly limit: number;
    readonly window_seconds: number;
    readonly used: number | null;
    readonly remaining: number | null;
    readonly state: string;
    readonly reserved: false;
  };
  readonly plan: {
    readonly version: 1;
    readonly mode: 'long';
    readonly max_evidence_passes: number;
    readonly max_reconciliation_passes: 1;
    readonly max_calls: number;
    readonly limits: Readonly<
      Record<
        | 'prompt_bytes'
        | 'input_bytes'
        | 'reply_bytes'
        | 'output_bytes'
        | 'source_bytes'
        | 'prepare_ms'
        | 'retained_bytes'
        | 'retained_units'
        | 'source_pages'
        | 'job_ms',
        number
      >
    >;
  } | null;
  readonly prompt: {
    readonly saved_ceiling_bytes: number | null;
    readonly route_ceiling_bytes: number | null;
    readonly fit_verified: false;
  };
  readonly measurements: Readonly<Record<string, string>>;
}
export interface ReadingLongPlanBody {
  readonly ok: true;
  readonly long_plan: unknown;
}
const MEASUREMENTS = {
  prompt_bytes: 'assembled-input',
  input_bytes: 'aggregate-assembled-input',
  reply_bytes: 'captured-reply-allocation',
  source_bytes: 'native-actual-io',
  retained_bytes: 'retained-object-graph',
  prepare_ms: 'source-collection-and-revalidation',
  job_ms: 'whole-job-elapsed',
};
const LIMITS = [
  'prompt_bytes',
  'input_bytes',
  'reply_bytes',
  'output_bytes',
  'source_bytes',
  'prepare_ms',
  'retained_bytes',
  'retained_units',
  'source_pages',
  'job_ms',
];
const keys = (value: unknown, names: readonly string[]): value is Record<string, unknown> =>
  typeof value === 'object' &&
  value !== null &&
  !Array.isArray(value) &&
  Object.keys(value).length === names.length &&
  names.every((key) => Object.hasOwn(value, key));
const count = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const positive = (value: unknown): value is number => count(value) && value > 0;
const moment = (value: unknown): boolean =>
  value === null ||
  (typeof value === 'number' && Number.isFinite(value) && value > 0 && value < 2 ** 53);
const optionalCount = (value: unknown): boolean => value === null || count(value);
const oneOf = (value: unknown, allowed: readonly string[]): boolean =>
  typeof value === 'string' && allowed.includes(value);

export function longPlan(value: unknown): LongPlanDescriptor | null {
  if (
    !keys(value, [
      'version',
      'mode',
      'supported',
      'can_start',
      'reason',
      'binding',
      'route',
      'intent',
      'source',
      'allowance',
      'plan',
      'prompt',
      'measurements',
    ]) ||
    value['version'] !== 1 ||
    value['mode'] !== 'long' ||
    typeof value['supported'] !== 'boolean' ||
    typeof value['can_start'] !== 'boolean' ||
    !oneOf(value['reason'], [
      '',
      'unsupported-source',
      'source-unavailable',
      'route-unavailable',
      'capacity-unavailable',
      'intent-unavailable',
      'intent-ineligible',
      'allowance-unavailable',
    ]) ||
    !(
      value['binding'] === null ||
      (typeof value['binding'] === 'string' && /^[0-9a-f]{64}$/.test(value['binding']))
    )
  )
    return null;
  const route = value['route'];
  if (
    route !== null &&
    (!keys(route, [
      'harness',
      'provider',
      'model',
      'words_destination',
      'destination',
      'reason',
      'fallback',
      'ci_read',
    ]) ||
      route['harness'] !== 'claude' ||
      !oneOf(route['provider'], ['claude', 'codex']) ||
      !['model', 'words_destination', 'destination'].every(
        (key) => typeof route[key] === 'string' && route[key].length <= 1024,
      ) ||
      !route['model'] ||
      typeof route['fallback'] !== 'boolean' ||
      !oneOf(route['reason'], [
        'own-harness',
        'no-own-producer',
        'fallback-not-installed',
        'fallback-not-qualified',
      ]) ||
      !oneOf(route['ci_read'], ['on', 'off', 'flag-off']))
  )
    return null;
  const intent = value['intent'];
  if (
    !keys(intent, ['revision', 'start_at']) ||
    !(intent['revision'] === null || positive(intent['revision'])) ||
    !moment(intent['start_at']) ||
    (intent['revision'] === null) !== (intent['start_at'] === null)
  )
    return null;
  const source = value['source'];
  if (
    !keys(source, [
      'capability',
      'kinds',
      'parent_bytes',
      'observed_at',
      'stream_count',
      'record_count',
      'frozen',
    ]) ||
    !oneOf(source['capability'], ['native-claude', 'unsupported', 'unknown']) ||
    value['supported'] !== (source['capability'] === 'native-claude') ||
    JSON.stringify(source['kinds']) !==
      JSON.stringify(value['supported'] ? ['parent', 'admitted-subagent'] : []) ||
    !optionalCount(source['parent_bytes']) ||
    !moment(source['observed_at']) ||
    source['stream_count'] !== null ||
    source['record_count'] !== null ||
    source['frozen'] !== false ||
    (!value['supported'] && (source['parent_bytes'] !== null || source['observed_at'] !== null))
  )
    return null;
  const allowance = value['allowance'];
  if (
    !keys(allowance, ['limit', 'window_seconds', 'used', 'remaining', 'state', 'reserved']) ||
    !positive(allowance['limit']) ||
    !positive(allowance['window_seconds']) ||
    !optionalCount(allowance['used']) ||
    !optionalCount(allowance['remaining']) ||
    !oneOf(allowance['state'], [
      'unknown',
      'unavailable',
      'run-disabled',
      'paused',
      'daily-cap',
      'available',
    ]) ||
    allowance['reserved'] !== false ||
    (allowance['used'] === null) !== (allowance['remaining'] === null) ||
    (typeof allowance['used'] === 'number' &&
      allowance['remaining'] !== Math.max(0, allowance['limit'] - allowance['used']))
  )
    return null;
  const plan = value['plan'];
  if (
    plan !== null &&
    (!keys(plan, [
      'version',
      'mode',
      'max_evidence_passes',
      'max_reconciliation_passes',
      'max_calls',
      'limits',
    ]) ||
      plan['version'] !== 1 ||
      plan['mode'] !== 'long' ||
      !positive(plan['max_evidence_passes']) ||
      plan['max_evidence_passes'] > 16 ||
      plan['max_reconciliation_passes'] !== 1 ||
      plan['max_calls'] !== plan['max_evidence_passes'] + 1 ||
      !keys(plan['limits'], LIMITS) ||
      !Object.values(plan['limits']).every(positive))
  )
    return null;
  const prompt = value['prompt'];
  if (
    !keys(prompt, ['saved_ceiling_bytes', 'route_ceiling_bytes', 'fit_verified']) ||
    !(prompt['saved_ceiling_bytes'] === null || positive(prompt['saved_ceiling_bytes'])) ||
    !(prompt['route_ceiling_bytes'] === null || positive(prompt['route_ceiling_bytes'])) ||
    prompt['fit_verified'] !== false
  )
    return null;
  const measurements = value['measurements'];
  if (
    !keys(measurements, Object.keys(MEASUREMENTS)) ||
    !Object.entries(MEASUREMENTS).every(([key, expected]) => measurements[key] === expected)
  )
    return null;
  if (
    value['can_start'] !== (value['reason'] === '') ||
    (value['can_start'] &&
      (!value['supported'] ||
        route === null ||
        plan === null ||
        value['binding'] === null ||
        intent['revision'] === null ||
        allowance['state'] !== 'available' ||
        !positive(allowance['remaining'])))
  )
    return null;
  if (
    keys(plan, [
      'version',
      'mode',
      'max_evidence_passes',
      'max_reconciliation_passes',
      'max_calls',
      'limits',
    ])
  ) {
    const limits = plan['limits'] as Record<string, number>;
    if (
      !positive(prompt['saved_ceiling_bytes']) ||
      !positive(prompt['route_ceiling_bytes']) ||
      limits['prompt_bytes'] !==
        Math.min(prompt['saved_ceiling_bytes'], prompt['route_ceiling_bytes'])
    )
      return null;
  }
  return JSON.parse(JSON.stringify(value)) as LongPlanDescriptor;
}

export function readingLongPlan(value: unknown): LongPlanDescriptor | null {
  return keys(value, ['ok', 'long_plan']) && value['ok'] === true
    ? longPlan(value['long_plan'])
    : null;
}
