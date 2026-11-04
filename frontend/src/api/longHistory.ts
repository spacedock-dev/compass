/** Display-only recovery inspection. These records confer no discard or process authority. */
export interface HistoryTotals {
  readonly calls: number;
  readonly prompt_bytes: number;
  readonly reply_bytes: number;
}
export interface HistoryItem {
  readonly job_id: string;
  readonly state: 'active' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
  readonly started_at: number;
  readonly updated_at: number;
  readonly terminal_at: number | null;
  readonly unsettled: boolean | null;
  readonly accounting: 'exact' | 'minimum' | 'unknown';
  readonly exact: HistoryTotals | null;
  readonly minimum: HistoryTotals | null;
  readonly reason: string;
}
export interface LongHistory {
  readonly version: 1;
  readonly items: readonly HistoryItem[];
  readonly incomplete: boolean;
  readonly reason: string;
}
export interface ReadingLongHistoryBody {
  readonly ok: boolean;
  readonly long_history?: unknown;
}
export interface ReadingLongDiscardBody {
  readonly ok: boolean;
  readonly discarded: boolean;
  readonly reason: string;
}

const HISTORY_REASONS = [
  '',
  'invalid-session',
  'inspection-clock-invalid',
  'inventory-unavailable',
  'inventory-bounded',
  'marker-unavailable',
  'marker-changed',
  'marker-unattributed',
  'accounting-unavailable',
];
const ITEM_REASONS = [
  '',
  'inspection-clock-invalid',
  'ledger-identity-unknown',
  'registration-inconsistent',
  'ledger-incomplete',
  'ledger-unavailable',
  'accounting-unavailable',
];
const DISCARD_REASONS = [
  '',
  'clock-invalid',
  'marker-unavailable',
  'marker-changed',
  'owner-current',
  'owner-unresolved',
  'accounting-unknown',
  'publication-unattributed',
  'discard-unproved',
  'retirement-unresolved',
  'discard-unavailable',
  'receipt-unresolved',
  'invalid-request',
  'session-mismatch',
];
const record = (x: unknown): x is Record<string, unknown> =>
  typeof x === 'object' && x !== null && !Array.isArray(x);
const keys = (x: Record<string, unknown>, expected: string) => {
  const names = expected.split(' ');
  return Object.keys(x).length === names.length && names.every((name) => Object.hasOwn(x, name));
};
const number = (x: unknown): x is number =>
  typeof x === 'number' && Number.isFinite(x) && x >= 0 && x <= Number.MAX_SAFE_INTEGER;
const integer = (x: unknown): x is number => number(x) && Number.isSafeInteger(x);
const reason = (x: unknown, allowed: readonly string[]): x is string =>
  typeof x === 'string' && allowed.includes(x);
function totals(x: unknown): HistoryTotals | null {
  if (
    !record(x) ||
    !keys(x, 'calls prompt_bytes reply_bytes') ||
    !integer(x.calls) ||
    !integer(x.prompt_bytes) ||
    !integer(x.reply_bytes)
  )
    return null;
  return { calls: x.calls, prompt_bytes: x.prompt_bytes, reply_bytes: x.reply_bytes };
}
function item(x: unknown): HistoryItem | null {
  if (
    !record(x) ||
    !keys(
      x,
      'job_id state started_at updated_at terminal_at unsettled accounting exact minimum reason',
    ) ||
    typeof x.job_id !== 'string' ||
    !/^[a-f0-9]{32}$/.test(x.job_id) ||
    !reason(x.state, ['active', 'completed', 'failed', 'cancelled', 'interrupted']) ||
    !number(x.started_at) ||
    x.started_at <= 0 ||
    !number(x.updated_at) ||
    !(x.terminal_at === null || number(x.terminal_at)) ||
    (x.state === 'active' ? x.terminal_at !== null : x.terminal_at === null) ||
    !(x.unsettled === null || typeof x.unsettled === 'boolean') ||
    !reason(x.accounting, ['exact', 'minimum', 'unknown']) ||
    !reason(x.reason, ITEM_REASONS)
  )
    return null;
  const exact = totals(x.exact),
    minimum = totals(x.minimum);
  if (
    x.accounting === 'exact'
      ? !exact ||
        !minimum ||
        exact.calls !== minimum.calls ||
        exact.prompt_bytes !== minimum.prompt_bytes ||
        exact.reply_bytes !== minimum.reply_bytes
      : x.accounting === 'minimum'
        ? x.exact !== null || !minimum
        : x.exact !== null || x.minimum !== null
  )
    return null;
  return {
    job_id: x.job_id,
    state: x.state as HistoryItem['state'],
    started_at: x.started_at,
    updated_at: x.updated_at,
    terminal_at: x.terminal_at,
    unsettled: x.unsettled,
    accounting: x.accounting as HistoryItem['accounting'],
    exact,
    minimum,
    reason: x.reason,
  };
}
export function readingLongHistory(value: unknown): LongHistory | null {
  if (!record(value) || !keys(value, 'ok long_history') || value.ok !== true) return null;
  const x = value.long_history;
  if (
    !record(x) ||
    !keys(x, 'version items incomplete reason') ||
    x.version !== 1 ||
    !Array.isArray(x.items) ||
    x.items.length > 128 ||
    typeof x.incomplete !== 'boolean' ||
    !reason(x.reason, HISTORY_REASONS)
  )
    return null;
  const items: HistoryItem[] = [],
    seen = new Set<string>();
  for (const raw of x.items) {
    const parsed = item(raw);
    if (!parsed || seen.has(parsed.job_id)) return null;
    seen.add(parsed.job_id);
    items.push(parsed);
  }
  if (!x.incomplete && (x.reason !== '' || items.some((row) => row.accounting !== 'exact')))
    return null;
  return { version: 1, items, incomplete: x.incomplete, reason: x.reason };
}
export function readingLongDiscard(value: unknown): ReadingLongDiscardBody | null {
  if (
    !record(value) ||
    !keys(value, 'ok discarded reason') ||
    typeof value.ok !== 'boolean' ||
    typeof value.discarded !== 'boolean' ||
    value.ok !== value.discarded ||
    !reason(value.reason, DISCARD_REASONS)
  )
    return null;
  if (value.discarded && value.reason !== '' && value.reason !== 'receipt-unresolved') return null;
  return { ok: value.ok, discarded: value.discarded, reason: value.reason };
}
