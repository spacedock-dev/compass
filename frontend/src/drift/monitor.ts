import { nextNumber } from '../api/bootstrap';
import { clock, isRecord, type Row } from '../observed';
import type { DriftLevel } from './level';
import { LIVE_LEVEL_NAMES } from './sentences';

/* What the page reads of the Live monitor's lease, which the server holds: the clock, the words it says
   are sent, the level a Haiku check earned, and why a lease ended. Pure: the page keeps none of this in
   storage, and a reload starts with no lease
   ([DEC-26](../../../docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)). */

export const END_REASONS = [
  'ended',
  'left',
  'paused',
  'unanswered',
  'declined',
  'stopped',
  'cap',
] as const;
export type EndReason = (typeof END_REASONS)[number];

export interface LeaseEnd {
  readonly reason: EndReason;
  readonly at: number;
}

export interface LeaseState {
  readonly on: boolean;
  readonly startedAt: number | null;
  readonly bannerDueAt: number | null;
  readonly deadline: number | null;
  /** While the question stands, when it stops standing; the server's clock, in epoch seconds. */
  readonly confirmBy: number | null;
  readonly visible: boolean;
  readonly lastEnd: LeaseEnd | null;
  /** The level row of the last completed check, or null while none has completed. */
  readonly level: Row | null;
  readonly label: string;
  readonly destination: string | null;
  readonly disclosure: string | null;
  /** The server's own time when this state was made, so two states order without the page's clock. */
  readonly now: number;
}

const isEnd = (value: unknown): value is EndReason =>
  typeof value === 'string' && (END_REASONS as readonly string[]).includes(value);

function text(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

export function idleLease(): LeaseState {
  return {
    on: false,
    startedAt: null,
    bannerDueAt: null,
    deadline: null,
    confirmBy: null,
    visible: false,
    lastEnd: null,
    level: null,
    label: 'Live monitor · Haiku',
    destination: null,
    disclosure: null,
    now: 0,
  };
}

export function parseLease(value: unknown): LeaseState | null {
  if (!isRecord(value) || typeof value['on'] !== 'boolean') return null;
  const end = isRecord(value['last_end']) ? value['last_end'] : null;
  const reason = end?.['reason'];
  const at = nextNumber(end?.['at']);
  return {
    on: value['on'],
    startedAt: nextNumber(value['started_at']),
    bannerDueAt: nextNumber(value['banner_due_at']),
    deadline: nextNumber(value['deadline']),
    confirmBy: nextNumber(value['confirm_by']),
    visible: value['visible'] === true,
    lastEnd: isEnd(reason) && at !== null ? { reason, at } : null,
    level: isRecord(value['level']) ? (value['level'] as Row) : null,
    label: text(value['label']) ?? 'Live monitor · Haiku',
    destination: text(value['destination']),
    disclosure: text(value['disclosure']),
    now: nextNumber(value['now']) ?? 0,
  };
}

/* The level of the last completed check, drawn as the monitor's own. Absent, never "None or low", while no
   check has completed or the lease is off; the page then shows the estimate. The sentence is the model's, held
   by the server to the shape contract and to the floor; it says where the turns are heading and never that
   the work met the goal. */
export function monitorLevel(lease: LeaseState): DriftLevel | null {
  const row = lease.on ? lease.level : null;
  if (!row) return null;
  const level = String(row['level'] || '');
  const label = Object.hasOwn(LIVE_LEVEL_NAMES, level) ? LIVE_LEVEL_NAMES[level] : undefined;
  if (!label) return null;
  const at = nextNumber(row['checked_at']);
  return {
    level,
    label,
    source: at !== null ? `${lease.label} · ${clock(at)}` : lease.label,
    rose: '',
    anchored: false,
    signals: null,
    reasons: { first: '', blockers: [] },
    analysis: false,
    line: '',
    range: '',
    monitor: true,
    note: String(row['reason'] || ''),
  };
}

/* One sentence for each reason a lease ends, each saying that the monitor is off and why. The reader's own
   off (`stopped`) has none: they pressed it. The limit's wording is the monitor's own, apart from the Analyze
   banner's, because the two budgets are kept apart. */
export const END_NOTES: Readonly<Record<Exclude<EndReason, 'stopped'>, string>> = {
  ended: 'Live monitor turned off: the session ended, so there is nothing live to monitor.',
  left: 'Live monitor turned off: you left the session or this tab stopped answering, so no more model calls were made.',
  paused:
    'Live monitor turned off: model calls are paused. Resume model calls, then turn it on again.',
  unanswered:
    'Live monitor turned off: no answer after {minutes}, so no more model calls were made.',
  declined: 'Live monitor turned off at your answer, so no more model calls will be made.',
  cap: 'Live monitor turned off: it reached its own limit of checks. That limit is not your Analyze budget, which it never spends. Turn it on again when the limit clears.',
};

export function endNote(reason: EndReason, options: { readonly answerMinutes?: number }): string {
  if (reason === 'stopped') return '';
  const minutes = options.answerMinutes ?? 10;
  return END_NOTES[reason].replace(
    '{minutes}',
    `${String(minutes)} minute${minutes === 1 ? '' : 's'}`,
  );
}

const REFUSALS: Readonly<Record<string, string>> = {
  ended: 'Live monitor did not start: the session has ended, so there is nothing live to monitor.',
  paused: 'Live monitor did not start: model calls are paused.',
  'no-observer-model': 'Live monitor did not start: model calls are off for this run.',
  'unknown-session': 'Live monitor did not start: this session is not on the board.',
  'unsupported-harness': 'Live monitor did not start: it checks Claude Code sessions only.',
  sample: 'Live monitor did not start: the sample session is view only.',
};

export function refusalNote(reason: string): string {
  return REFUSALS[reason] ?? 'Live monitor did not start.';
}
