import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import { isRecord, records, type Row } from '../observed';
import { SESSION_GOAL } from '../sessions/intent';
import { formatTimestamp } from '../shell/format';
import { annotationDiscarded, annotationLines, discardAccount } from './annotation';

export const READING_NOT_A_VERIFICATION =
  'A reading is never a verification that the work was done.';

export const GOAL_HISTORY_SESSION_LIMIT = 256;
export const GOAL_HISTORY_REVISION_LIMIT = 16;
export const GOAL_HISTORY_COPY_DAYS = 14;

export const GOAL_HISTORY_LIMITS = [
  `Compass keeps goals for up to ${GOAL_HISTORY_SESSION_LIMIT} sessions, with up to ${GOAL_HISTORY_REVISION_LIMIT} revisions per session. Saved goals have no time limit.`,
  'When space runs out, discard records go first, then the oldest saves.',
  `When session history is enabled, it keeps a copy of goals and outcome lines for ${GOAL_HISTORY_COPY_DAYS} days by default. Goal history reads saved goals from their own store.`,
  'Forget everything keeps typed goals and readings. It removes the records of goals you discarded.',
];

export type LogLoad = 'unread' | 'loading' | 'read' | 'error';

interface PublishedGoal {
  readonly goal: string;
  readonly source: string;
  readonly time: string;
}

export interface LogRow extends PublishedGoal {
  readonly key: string;
  readonly session: Row | null;
  readonly title: string;
  readonly absence: string;
  readonly canAdd: boolean;
  readonly outcomes: readonly { readonly k: number; readonly text: string }[];
  readonly additionalGoals: readonly PublishedGoal[];
  readonly caveats: readonly string[];
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

function publishedGoals(
  record: Row | undefined,
  session: Row | null,
  payload: Row,
): PublishedGoal[] {
  const generated = payload['generated'];
  const goals: PublishedGoal[] = [];
  const goal = String(record?.['goal'] ?? '').trim();
  if (goal)
    goals.push({
      goal,
      source: savedSource(record?.['goal_source']),
      time: stamp('Saved', record?.['goal_saved_at'] ?? record?.['at'], generated),
    });
  const stated = session?.['session_goal'];
  const cached = session?.['cached_deterministic_goal'];
  const tracked = session?.['spacedock'];
  const workflows =
    payload['spacedock_enabled'] !== false && isRecord(tracked)
      ? records(tracked['workflows'])
      : [];
  for (const [entry, key, source] of [
    [cached, 'goal', 'Previously observed in this session'],
    [stated, 'text', 'You wrote this with /goal'],
  ] as const) {
    if (!isRecord(entry)) continue;
    const words = String(entry[key] ?? '').trim();
    if (!words) continue;
    goals.push({
      goal: words,
      source,
      time: stamp('Observed', entry['at'] ?? entry['observed_at'], generated),
    });
  }
  for (const workflow of workflows) {
    const words = String(workflow['goal'] ?? '').trim();
    if (words)
      goals.push({
        goal: words,
        source: 'Reported by the workflow',
        time: stamp('Observed', workflow['at'] ?? workflow['observed_at'], generated),
      });
  }
  return goals;
}

export interface LogInput {
  readonly payload: Row;
  readonly board: readonly Row[];
  readonly rows: readonly Row[] | null;
  readonly load: LogLoad;
}

export function intentLogView({ payload, board, rows, load }: LogInput) {
  const annotating = payload['annotate'] === true;
  const storeNotice =
    typeof payload['annotate_unreadable'] === 'string' ? payload['annotate_unreadable'] : '';
  const readable = annotating && !storeNotice && load === 'read';
  const retained = new Map((readable ? (rows ?? []) : []).map((row) => [compatSessKey(row), row]));
  const live = new Map(board.map((row) => [compatSessKey(row), row]));
  /* The annotation store is authoritative for saved and withdrawn words. The history copy is
     deliberately excluded so a newer board cannot bring a discarded goal back. */
  function row(key: string, session: Row | null): LogRow {
    const record = retained.get(key);
    const discarded = record !== undefined && annotationDiscarded(record);
    const outcomes = record && !discarded ? annotationLines(record) : [];
    const [first, ...additionalGoals] = discarded ? [] : publishedGoals(record, session, payload);
    const published = isRecord(payload['annotate_discard']) ? payload['annotate_discard'] : {};
    const caveats = discarded ? discardAccount(record, record['departures'], published, false) : [];
    if (record?.['binding_why']) caveats.push(String(record['binding_why']));
    return {
      key,
      session,
      title: String(session?.['title'] ?? record?.['title'] ?? '').trim(),
      goal: first?.goal ?? '',
      source: discarded ? 'You discarded this goal' : (first?.source ?? ''),
      time: discarded
        ? stamp('Discarded', record['discarded_at'], payload['generated'])
        : (first?.time ??
          (outcomes.length ? stamp('Saved', record?.['at'], payload['generated']) : '')),
      absence: discarded || first ? '' : readable ? 'No goal yet.' : 'Saved goal unavailable.',
      canAdd: !discarded && !first && readable && session !== null,
      outcomes,
      additionalGoals,
      caveats,
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
    : storeNotice ||
      (load === 'error'
        ? 'Compass could not read your saved goals.'
        : !readable
          ? 'Loading saved goals.'
          : '');
  return { groups, notice };
}
