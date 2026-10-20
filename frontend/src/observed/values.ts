import { nextNumber } from '../api/bootstrap';
import { formatDuration } from '../shell/format';

/* The small readers the observed model is built from. Each is the legacy page's own, spelled the same
   way, because the payload is untrusted and the legacy truthiness rules (`harness || ""`, `== null`) are
   part of what the two pages must agree on: a harness of `0` and a harness of `""` are the same
   absent harness there, and a sid of `0` is a published one. */

export type Row = Readonly<Record<string, unknown>>;

export function isRecord(value: unknown): value is Row {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The payload as a record, or an empty one: the page holds `{}` before a board arrives. */
export function asPayload(value: unknown): Row {
  return isRecord(value) ? value : {};
}

/** `nextObservedString`: a trimmed string, and nothing for any other type. */
export function trimmed(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

/** `String(value == null ? "" : value)`: the published text with only null and undefined absent. */
export function textOf(value: unknown): string {
  return String(value == null ? '' : value);
}

/** `String(value || "")`: the identity spelling, where every falsy value is the empty string. */
export function identityPart(value: unknown): string {
  return String(value || '');
}

export function records(value: unknown): Row[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

export function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

/* The pair every fact travels as: the sentence to show and whether it is a measurement. An unmeasured
   fact carries the reason in its text, so a reader never meets a blank that could be a zero. */
export type Pair<N extends string> = { readonly [K in `${N}Text`]: string } & {
  readonly [K in `${N}Known`]: boolean;
};

export function pair<N extends string>(name: N, value: unknown, reason: string): Pair<N> {
  const text = trimmed(value);
  return { [`${name}Text`]: text || reason, [`${name}Known`]: Boolean(text) } as Pair<N>;
}

/* When a session id was observed to end, or null. Null is the whole of what the page may say: absence
   covers a SIGKILL, a harness with no event adapter, a session that predates this server run and
   --no-events, so a row without a stamp is not known to be running and is never drawn as though it were. */
export function endedAt(session: Row | null | undefined): number | null {
  const at = nextNumber(session?.['ended_at']);
  return at !== null && at > 0 ? at : null;
}

/* The pair, as a key. `JSON.stringify` of the two parts, so a sid or harness containing any separator
   cannot forge another session's key. */
export function sessionKey(session: Row | null | undefined): string {
  return `session:${JSON.stringify([identityPart(session?.['harness']), identityPart(session?.['sid'])])}`;
}

export function payloadSessionRows(payload: Row): Row[] {
  return Array.isArray(payload['sessions']) ? payload['sessions'].filter(isRecord) : [];
}

export function payloadAskRows(payload: Row): Row[] {
  return Array.isArray(payload['asks']) ? payload['asks'].filter(isRecord) : [];
}

/* The one session an ask belongs to: its sid, and its harness when it names one, matching exactly one
   row. An ask that matches none or several is attributed to no session. */
export function exactAskOwner(payload: Row, ask: Row | null | undefined): Row | null {
  const sid = identityPart(ask?.['session_id']);
  if (!sid) return null;
  const harness = identityPart(ask?.['harness']);
  const matches = payloadSessionRows(payload).filter(
    (row) =>
      identityPart(row['sid']) === sid && (!harness || identityPart(row['harness']) === harness),
  );
  return matches.length === 1 ? (matches[0] ?? null) : null;
}

/* Seconds between the payload's own clock and a stamp, never below zero, or null where either is not a
   usable number. The payload's clock and not the browser's, so a stamp ages only when a new board
   arrives. */
export function ageSeconds(generated: number | null, stamp: unknown): number | null {
  const at = nextNumber(stamp);
  if (generated === null || at === null || at <= 0) return null;
  return Math.max(0, generated - at);
}

export function durationSince(generated: number | null, stamp: unknown): string | null {
  const age = ageSeconds(generated, stamp);
  return age === null ? null : formatDuration(age);
}

/* Wall-clock hours and minutes, in the reader's own zone. */
export function clock(stamp: number): string {
  const date = new Date(stamp * 1000);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

/* `clock`, with the date in front where the moment is not the reader's today: the rule the copied correction's
   `correction.zone_clock` draws by, so a label beside Steer back and the text it copies name the same moment, and
   an old reading never reads as today's (review, 2026-10-20). */
export function datedClock(stamp: number, now: number = Date.now() / 1000): string {
  const date = new Date(stamp * 1000);
  if (date.toDateString() === new Date(now * 1000).toDateString()) return clock(stamp);
  const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  return `${day} ${clock(stamp)}`;
}

/* Whether the row's `field` quotes a correction the reader copied from Compass, which is never
   presented as their words. The server places each field on the message it quotes (the quoted_as
   list), so this reads its answer. */
export function promptCopied(session: Row | null | undefined, field: string): boolean {
  const entries = Array.isArray(session?.['copied_prompts'])
    ? (session['copied_prompts'] as unknown[])
    : [];
  return entries.some(
    (entry) =>
      isRecord(entry) && Array.isArray(entry['quoted_as']) && entry['quoted_as'].includes(field),
  );
}

/* The readings a row's collector could not take from a store it opened, as names. `source_gaps` is an
   untrusted published array, so a non-array and a non-string member are both nothing. */
export function gapNames(session: Row | null | undefined): string[] {
  const gaps = session?.['source_gaps'];
  if (!Array.isArray(gaps)) return [];
  return gaps
    .filter((name): name is string => typeof name === 'string' && Boolean(name.trim()))
    .map((name) => name.trim());
}

/* Whether no event can ever reach this row, so an absent stop says nothing about whether the turn
   ended. `acquisition` is published, so it is compared to one exact string: a truthy check would print
   the sentence for "event", the value that means the opposite. A published stop takes precedence,
   because the sentence says a stop could not be observed and a stamp beside it would make that false. */
export function isScanOnly(session: Row | null | undefined): boolean {
  if (!session || session['acquisition'] !== 'scan-only') return false;
  const finished = Number(session['finished_at']);
  return !(Number.isFinite(finished) && finished > 0);
}

/* The working lane's order: a long turn first, then by sid. */
export function workingOrder(rows: readonly Row[]): Row[] {
  const bySid = (left: Row, right: Row) =>
    compare(identityPart(left['sid']), identityPart(right['sid']));
  const rank = (row: Row) => (isRecord(row['turn']) && row['turn']['long'] ? 1 : 2);
  return [...rows].sort((left, right) => {
    const byRank = rank(left) - rank(right);
    return byRank !== 0 ? byRank : bySid(left, right);
  });
}
