import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import { isRecord, records, type Row } from '../observed';
import { SESSION_GOAL } from '../sessions/intent';
import { formatTimestamp } from '../shell/format';
import { annotationDiscarded, annotationLines } from './annotation';

export const READING_NOT_A_VERIFICATION =
  'A reading is never a verification that the work was done.';

export const GOAL_HISTORY_SESSION_LIMIT = 256;
export const GOAL_HISTORY_REVISION_LIMIT = 16;
export const GOAL_HISTORY_COPY_DAYS = 14;

export const GOAL_HISTORY_LIMITS = [
  `Compass keeps goals for up to ${GOAL_HISTORY_SESSION_LIMIT} sessions, with up to ${GOAL_HISTORY_REVISION_LIMIT} revisions per session. Saved goals have no time limit.`,
  'When space runs out, discard records go first, then the oldest saves.',
  `Session history keeps a copy of goals and expected outcomes for ${GOAL_HISTORY_COPY_DAYS} days. Goal history reads saved goals from their own store.`,
  'Forget everything keeps typed goals and readings. It removes the records of goals you discarded.',
];

export type LogLoad = 'unread' | 'loading' | 'read' | 'error';

export interface LogRow {
  readonly key: string;
  readonly session: Row | null;
  readonly title: string;
  readonly goal: string;
  readonly source: string;
  readonly time: string;
  readonly absence: string;
  readonly canAdd: boolean;
  readonly outcomes: readonly { readonly k: number; readonly text: string }[];
}

export interface Group {
  readonly id: 'current' | 'older';
  readonly title: string;
  readonly rows: readonly LogRow[];
}

function savedSource(kind: unknown): string {
  switch (kind) {
    case SESSION_GOAL:
      return 'You wrote this with /goal';
    case 'first-prompt':
      return 'Taken from your first prompt';
    case 'latest-prompt':
      return 'Taken from your latest prompt';
    case 'chosen-prompt':
      return 'Taken from a prompt you chose';
    default:
      return 'You wrote this';
  }
}

function stamp(label: string, at: unknown, generated: unknown) {
  const time = formatTimestamp(at, generated) ?? formatTimestamp(at, generated, { style: 'clock' });
  return time ? `${label} ${time}` : `${label} time unavailable`;
}

function goalRecord(record: Row | undefined, session: Row | null, payload: Row, load: LogLoad) {
  const generated = payload['generated'];
  if (record && annotationDiscarded(record)) {
    return {
      goal: '',
      source: 'You discarded this goal',
      time: stamp('Discarded', record['discarded_at'], generated),
      absence: '',
      canAdd: false,
    };
  }
  const goal = String(record?.['goal'] ?? '').trim();
  if (goal) {
    return {
      goal,
      source: savedSource(record?.['goal_source']),
      time: stamp('Saved', record?.['goal_saved_at'] ?? record?.['at'], generated),
      absence: '',
      canAdd: false,
    };
  }
  const stated = session?.['session_goal'];
  const cached = session?.['cached_deterministic_goal'];
  const tracked = session?.['spacedock'];
  const workflow =
    payload['spacedock_enabled'] !== false && isRecord(tracked)
      ? records(tracked['workflows']).find((row) => String(row['goal'] ?? '').trim())
      : undefined;
  for (const [entry, key, source] of [
    [stated, 'text', 'You wrote this with /goal'],
    [cached, 'goal', 'Taken from session activity'],
    [workflow, 'goal', 'Reported by the workflow'],
  ] as const) {
    if (!isRecord(entry)) continue;
    const words = String(entry[key] ?? '').trim();
    if (!words) continue;
    return {
      goal: words,
      source,
      time: stamp('Observed', entry['at'] ?? entry['observed_at'], generated),
      absence: '',
      canAdd: false,
    };
  }

  const known = payload['annotate'] === true && load === 'read';
  return {
    goal: '',
    source: '',
    time: '',
    absence: known ? 'No goal yet.' : 'Saved goal unavailable.',
    canAdd: known && session !== null,
  };
}

export interface LogInput {
  readonly payload: Row;
  readonly board: readonly Row[];
  readonly rows: readonly Row[] | null;
  readonly load: LogLoad;
}

export function intentLogView({ payload, board, rows, load }: LogInput) {
  const annotating = payload['annotate'] === true;
  const readable = annotating && load === 'read';
  const retained = new Map((readable ? (rows ?? []) : []).map((row) => [compatSessKey(row), row]));
  const live = new Map(board.map((row) => [compatSessKey(row), row]));
  /* The annotation store is authoritative for saved and withdrawn words. The history copy is
     deliberately excluded so a newer board cannot bring a discarded goal back. */
  function row(key: string, session: Row | null): LogRow {
    const record = retained.get(key);
    return {
      key,
      session,
      title: String(session?.['title'] ?? record?.['title'] ?? '').trim(),
      ...goalRecord(record, session, payload, load),
      outcomes: record && !annotationDiscarded(record) ? annotationLines(record) : [],
    };
  }
  const older = [...retained]
    .filter(([key]) => !live.has(key))
    .sort(
      ([, a], [, b]) =>
        Number(annotationDiscarded(a)) - Number(annotationDiscarded(b)) ||
        (nextNumber(b['at'] ?? b['discarded_at']) ?? 0) -
          (nextNumber(a['at'] ?? a['discarded_at']) ?? 0),
    );
  const groups: readonly Group[] = [
    {
      id: 'current',
      title: 'On the board now',
      rows: [...live].map(([key, session]) => row(key, session)),
    },
    { id: 'older', title: 'Older sessions', rows: older.map(([key]) => row(key, null)) },
  ];
  const notice = !annotating
    ? 'Saving goals is off for this run.'
    : load === 'error'
      ? 'Compass could not read your saved goals.'
      : !readable
        ? 'Loading saved goals.'
        : '';
  return { groups, notice };
}
