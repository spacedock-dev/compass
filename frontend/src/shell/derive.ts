import { payloadSessions } from '../api/bootstrap';
import type { PayloadData, PayloadSession } from '../api/types';
import { SHOWN } from '../language/glossary';
import { noTitleText, pageTitleOf } from '../observed/session';

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
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
  const row = session ? (session as unknown as Record<string, unknown>) : null;
  return row ? pageTitleOf(row) || noTitleText(row) : SHOWN.titleNotPublished;
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
