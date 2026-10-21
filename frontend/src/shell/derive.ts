import { payloadSessions } from '../api/bootstrap';
import type { PayloadData, PayloadSession } from '../api/types';
import { pageTitleOf } from '../observed/session';
import { observedFor } from '../observed/select';
import type { BoardSnapshot } from '../store/board';

/* The few figures the page's chrome reads, taken from the observed model of the rows the views render
   (`observed/`), never counted a second way: the header, the Sessions fleet facts and the session page all
   stand on one model of one payload, so they cannot disagree about what a running or blocked session is.
   The header-count tests pin them against the legacy cases. */

export const TITLE_NOT_PUBLISHED = 'Title not published';

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export type HeaderCounts =
  /** No board has been accepted yet: nothing is known, and nothing may be claimed. */
  | { readonly state: 'unread' }
  /** A board arrived and carried no session collection, which is not the same as an empty one. */
  | { readonly state: 'absent' }
  | {
      readonly state: 'measured';
      readonly gates: number;
      readonly running: number;
      readonly subagents: number;
    };

const countsByBody = new WeakMap<object, HeaderCounts>();
/* One object, because a selector over an unread board is called on every render and must return what it
   returned last time or `useSyncExternalStore` sees a change that never ends. */
const UNREAD: HeaderCounts = Object.freeze({ state: 'unread' });

export function deriveHeaderCounts(data: PayloadData | null): HeaderCounts {
  if (!data) return UNREAD;
  const cached = countsByBody.get(data);
  if (cached) return cached;
  let counts: HeaderCounts;
  if (!payloadSessions(data).present) {
    counts = { state: 'absent' };
  } else {
    const model = observedFor(data);
    counts = {
      state: 'measured',
      gates: model.sessions.filter((session) => session.isNeeds || session.askKnown).length,
      running: model.totals.running,
      subagents: model.totals.subagents,
    };
  }
  countsByBody.set(data, counts);
  return counts;
}

export function selectHeaderCounts(snapshot: BoardSnapshot): HeaderCounts {
  return deriveHeaderCounts(snapshot.data);
}

/* A session as a route names it: project exactly (an empty one included), sid, and the harness
   when the route carries one. More than one match is no match, so the released id-only form can
   never silently open an ambiguous wrong owner. */
export function findSession(
  data: PayloadData | null,
  project: string | null | undefined,
  harness: string | null | undefined,
  sid: string | null | undefined,
): PayloadSession | null {
  if (!data) return null;
  const projectKey = String(project ?? '');
  const harnessKey = String(harness ?? '');
  const sidKey = String(sid ?? '');
  const matches = payloadSessions(data).rows.filter(
    (row) =>
      String(row.project ?? '') === projectKey &&
      String(row.sid ?? '') === sidKey &&
      (!harnessKey || String(row.harness ?? '') === harnessKey),
  );
  return matches.length === 1 ? (matches[0] ?? null) : null;
}

/* The published title, or a sentence saying there is none. Never an invented one. The tab and the crumb take
   the same stand-in for an identifier-only title as the session heading does, so the three agree. */
export function sessionTitle(session: PayloadSession | null): string {
  return (
    (session ? pageTitleOf(session as unknown as Record<string, unknown>) : '') ||
    TITLE_NOT_PUBLISHED
  );
}

/* The two reasons the history store publishes, and nothing else: the field arrives from a file any
   local process could have replaced, so an unrecognised literal draws nothing rather than letting a
   tampered store write header copy. A closed list rather than a property lookup, so `toString` is no reason. */
const RESET_REASONS = ['unreadable', 'version'] as const;
export type HistoryResetReason = (typeof RESET_REASONS)[number];

export function historyResetReason(data: PayloadData | null): HistoryResetReason | null {
  const value = record(data)['history_reset'];
  return (RESET_REASONS as readonly unknown[]).includes(value)
    ? (value as HistoryResetReason)
    : null;
}

/* The span the board holds, in hours, or null when it did not say. */
export function windowHours(data: PayloadData | null): number | null {
  const value = record(data)['window_hours'];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
