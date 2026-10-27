import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import { isRecord, records, type Row } from '../observed';
import { datedClock } from '../observed/values';
import { LANE_OFF_RECORD } from '../sessions/detail';
import { PROMPT_SOURCES, SESSION_GOAL } from '../sessions/intent';
import {
  annotationDiscarded,
  annotationLines,
  discardAccount,
  discardStamp,
  revisionLine,
} from './annotation';

/* The Intent log, as sentences. The legacy `next-intent.js` builds markup; this builds the same cells as
   data so a view can draw them and a test can read them, and so no reader's words ever reach an HTML
   parser. Retained typed words come from the annotation store alone: session history keeps a copy of the
   goal for fourteen days, and reading the log out of that would resurrect words a reader withdrew, so the
   bound here is a count and not a date, and the surface says which. */

/* The load-bearing half of what a reading is not: the reading block says it about the reading it is
   offering and this log says it about every row it lists, so a second wording would be a second promise. */
export const READING_NOT_A_VERIFICATION =
  'A reading is never a verification that the work was done.';

export type LogLoad = 'unread' | 'loading' | 'read' | 'error';

export interface Cell {
  readonly kind: 'words' | 'why' | 'revision' | 'gone';
  readonly text: string;
}

export interface LogRow {
  readonly key: string;
  /** The live session this row names, or null where it has left the board. */
  readonly session: Row | null;
  readonly cells: readonly Cell[];
}

export interface Group {
  readonly title: string;
  readonly rows: readonly LogRow[];
}

export interface LogView {
  readonly counts: string;
  readonly notice: string;
  readonly limits: string;
  readonly groups: readonly Group[];
  readonly closing: string;
}

const sessKey = (row: Row | null | undefined): string => compatSessKey(row);

function departureCount(rows: readonly unknown[]): string {
  return `${rows.length === 1 ? 'One departure' : `${String(rows.length)} departures`} raised`;
}

/* What was raised against this session's words, in the space a list row has. Derived from the published
   list the session page renders from, so it counts raises and not store rows; where there is none the
   server's own sentence says which of the four reasons, because a bare zero would read as a session found
   to be on track. Nothing at all while the lane is off, which is the rule the session page applies to the
   same switch. On a discard record the raise count stands and the why-sentence does not: a raise on
   record is a fact about the record, while "has not checked this session against what you asked for" is
   true only because the words are gone, which the record above it has already said. */
function departures(row: Row, unasked: boolean): string {
  const rows = Array.isArray(row['departures']) ? row['departures'] : [];
  if (annotationDiscarded(row) || !unasked) return rows.length ? departureCount(rows) : '';
  if (rows.length) return departureCount(rows);
  return String(row['departure_why'] || '').trim();
}

/* Compact on purpose: the session page's drift block owns the full sentence about a reading made against
   older words, and a list row says the same fact in the space it has. */
function reading(row: Row): string {
  const raw = row['assessment'];
  const read = isRecord(raw) ? nextNumber(raw['revision_read']) : null;
  const current = nextNumber(row['revision']);
  if (read !== null) {
    const readAt = isRecord(raw) ? nextNumber(raw['read_at']) : null;
    const changedAt = nextNumber(row['at']);
    const moved = current !== null && read !== current;
    const made =
      readAt !== null && readAt > 0 ? `read at ${datedClock(readAt)}` : 'read your intent';
    const changed =
      moved && changedAt !== null && changedAt > 0
        ? `; intent changed at ${datedClock(changedAt)}`
        : moved
          ? '; intent changed since'
          : '';
    return `${made}${changed}`;
  }
  const withheld = String(row['reading_withheld'] || '').trim();
  if (withheld) return withheld;
  /* A count with no reading and no reason is a press whose reading the store refused on read-back. It is
     not a session nobody pressed on. */
  const asked = nextNumber(row['reading_count']) || 0;
  if (asked > 0)
    return `${String(asked)} ${asked === 1 ? 'reading' : 'readings'} asked for, none readable`;
  return 'No reading asked for';
}

function sources(row: Row, session: Row | null, retained: boolean, payload: Row, load: LogLoad) {
  const discarded = annotationDiscarded(row);
  const typed = retained && !discarded;
  const cachedGoal = session?.['cached_deterministic_goal'];
  const cached = isRecord(cachedGoal) ? cachedGoal : null;
  const goal = String((cached && cached['goal']) || '').trim();
  const stated = session?.['session_goal'];
  const statedGoal = String((isRecord(stated) && stated['text']) || '').trim();
  const spacedock = session?.['spacedock'];
  const workflows =
    payload['spacedock_enabled'] === false
      ? []
      : records(isRecord(spacedock) ? spacedock['workflows'] : undefined);
  const cells: Cell[] = [];
  const line = (label: string, text: string) =>
    cells.push({ kind: 'words', text: `${label}: ${text}` });
  const why = (text: string) => cells.push({ kind: 'why', text });
  /* "Your words", not "Typed words": a discarded goal may have been adopted from the reader's prompt, so
     the record cannot say they typed it. */
  if (discarded) line('Your words', String(row['discarded_why'] || ''));
  if (typed) {
    line(
      row['goal_source'] === SESSION_GOAL
        ? 'Goal from /goal'
        : PROMPT_SOURCES.includes(row['goal_source'] as string)
          ? 'Goal from your prompt'
          : 'Typed goal',
      String(row['goal'] || row['goal_why'] || 'No goal typed for this session.'),
    );
    const lines = annotationLines(row);
    if (lines.length)
      for (const item of lines) line(`Expected outcome, line ${String(item.k)}`, item.text);
    else line('Expected outcome', String(row['lines_why'] || 'No expected outcome typed.'));
  } else if (!discarded) {
    line(
      'Typed words',
      payload['annotate'] === true && load === 'read'
        ? 'No goal or expected outcome typed.'
        : 'Annotation evidence unavailable.',
    );
  }
  if (goal) {
    const at = cached ? nextNumber(cached['observed_at']) : null;
    const stamp =
      at && Number.isFinite(new Date(at * 1000).getTime())
        ? `Observed ${new Date(at * 1000).toISOString()}.`
        : 'Observation time unknown.';
    line('Cached deterministic goal', goal);
    why(`${stamp} Cached; currentness has not been checked.`);
  } else {
    line('Cached deterministic goal', 'No cached deterministic goal available.');
  }
  /* A /goal is a fourth place a goal can live, so a session that states one never reads as
     goal-less: the sentence below is scoped to the sources listed, and a reader takes it for the session. */
  if (statedGoal) line('Goal stated with /goal', statedGoal);
  if (payload['spacedock_enabled'] === false)
    line('Workflow goal', 'Spacedock is off for this run.');
  else if (!workflows.length) line('Workflow goal', 'No workflow goal published.');
  else
    for (const workflow of workflows)
      line(
        `Workflow ${String(workflow['workflow'] || 'unnamed')}`,
        String(workflow['goal'] || 'No workflow goal published.'),
      );
  if (
    !(typed && String(row['goal'] || '').trim()) &&
    !goal &&
    !statedGoal &&
    !workflows.some((workflow) => String(workflow['goal'] || '').trim())
  ) {
    why('No goal available from these sources.');
  }
  return cells;
}

function logRow(
  row: Row,
  live: ReadonlyMap<string, Row>,
  retained: boolean,
  payload: Row,
  load: LogLoad,
  generated: number | null,
): LogRow {
  const key = sessKey(row);
  const session = live.get(key) ?? null;
  /* The third state, and the reason this row branches rather than filling the same cells with emptier
     values: a discard record has no words, no revision and no reading it could ever carry, so the words
     cell holds the record's own sentence and the revision cell holds when the act happened. */
  const discarded = annotationDiscarded(row);
  const revision = !retained
    ? ''
    : discarded
      ? discardStamp(row, generated)
      : revisionLine(row, generated) || 'No revision saved yet';
  const raised = retained ? departures(row, payload['unasked'] === true) : '';
  const cells: Cell[] = sources(row, session, retained, payload, load).slice();
  if (revision) cells.push({ kind: 'revision', text: revision });
  /* The reading cell is dropped on a record and not softened: every sentence it can produce is about a
     session that could still have one, and a record cannot. */
  if (!(discarded || !retained)) cells.push({ kind: 'revision', text: reading(row) });
  if (raised) cells.push({ kind: 'revision', text: raised });
  /* And the standing-raise sentence, where the withdrawal did not land, so the row never says the words
     are gone beside a count of raises that still quote them. */
  if (discarded) {
    const published = isRecord(payload['annotate_discard']) ? payload['annotate_discard'] : {};
    for (const said of discardAccount(row, row['departures'], published).slice(1))
      cells.push({ kind: 'why', text: said });
  }
  if (!session) {
    cells.push({
      kind: 'why',
      text: `Not on the board now, so there is nowhere to open.${discarded ? '' : ' The words are here.'}`,
    });
  }
  /* The binding caveat: a list of many sessions is where a shared prefix would actually bite, and an
     absent caveat here reads as exact binding. */
  if (row['binding_why']) cells.push({ kind: 'why', text: String(row['binding_why']) });
  return { key, session, cells };
}

/* Derived from the rows this view is holding rather than asserted. Over the rows that still hold words
   and not over every row: a discard record can never carry a reading, so counting one in the denominator
   would report the schema rather than the sessions. The standing-raise clause still reads every row,
   because a raise on record is a fact about the record and not about the words. */
function closing(ordered: readonly Row[], listed: number, payload: Row): string {
  const typedRows = ordered.filter((row) => !annotationDiscarded(row));
  const withReading = typedRows.filter((row) => Boolean(row['assessment'])).length;
  const total = typedRows.length;
  const records_ = ordered.length - total;
  const watching = payload['unasked'] === true;
  const tail = watching ? '. ' : ', and nothing watches for one. ';
  /* The denominator names the set it counted wherever that set is not the list: four rows on screen and
     "1 of these 2" is what a corrected count left behind a stale demonstrative. */
  const counted =
    records_ || listed !== total
      ? `the ${String(total)} that still ${total === 1 ? 'holds' : 'hold'} words`
      : `these ${String(total)}`;
  const lead =
    withReading === 0
      ? listed === ordered.length
        ? `No reading has been made against any of these${tail}`
        : `No retained annotation carries a reading${tail}`
      : `${String(withReading)} of ${counted} ${withReading === 1 ? 'carries' : 'carry'} a reading${tail}`;
  const standing =
    !watching &&
    ordered.some((row) => Array.isArray(row['departures']) && row['departures'].length > 0);
  const record = standing ? `${LANE_OFF_RECORD} ` : '';
  return `${lead}${record}${READING_NOT_A_VERIFICATION}`;
}

export interface LogInput {
  readonly payload: Row;
  readonly board: readonly Row[];
  readonly rows: readonly Row[] | null;
  readonly load: LogLoad;
}

export function intentLogView(input: LogInput): LogView {
  const { payload, board: boardRows, load } = input;
  const generated = nextNumber(payload['generated']);
  const annotating = payload['annotate'] === true;
  const available = annotating && load === 'read';
  const held = input.rows ?? [];
  const notice = !annotating
    ? 'Annotations are off for this run. Start without --no-annotations to type a goal and an expected outcome.'
    : load === 'error'
      ? 'The annotation store could not be read, so its evidence is unread rather than empty.'
      : !available
        ? 'Reading the annotation store.'
        : !held.length
          ? 'No goal or expected outcome has been saved yet.'
          : '';
  const rows = available ? [...new Map(held.map((row) => [sessKey(row), row])).values()] : [];
  const live = new Map(boardRows.map((session) => [sessKey(session), session]));
  /* Newest save first, which is also eviction order read backwards. Records sort below every row that
     still holds words, because that is the store's own eviction rank: a discard may never push out words a
     reader still has, so a record goes first however recent it is. */
  const ordered = [...rows].sort(
    (a, b) =>
      (annotationDiscarded(b) ? 0 : 1) - (annotationDiscarded(a) ? 0 : 1) ||
      (nextNumber(b['at']) || nextNumber(b['discarded_at']) || 0) -
        (nextNumber(a['at']) || nextNumber(a['discarded_at']) || 0),
  );
  /* Two figures over one collection, derived in one pass: a record is a session the reader typed against
     and then discarded, so counting it as typed claims words that are gone and dropping it silently
     claims a smaller history than they lived. */
  const typed = ordered.filter((row) => !annotationDiscarded(row));
  const records_ = ordered.length - typed.length;
  const lead =
    `${String(typed.length)} ${typed.length === 1 ? 'session' : 'sessions'} you have saved words against` +
    (records_ ? `, and ${String(records_)} whose words you discarded` : '') +
    '. ';
  /* The stated rule and not just the order: with no record on the list, group-before-age and oldest-first
     pick the same bottom row, and the longer sentence would put the word "discarded" on a board where
     nothing was. */
  const evicts = records_
    ? 'A row whose words you discarded goes before any row that still holds words, and the oldest of what is left goes next.'
    : 'The oldest save goes first.';
  const retained = new Map(ordered.map((row) => [sessKey(row), row]));
  const onBoard = [...live.values()].map(
    (session): Row =>
      retained.get(sessKey(session)) ?? { harness: session['harness'], sid: session['sid'] },
  );
  const departed = ordered.filter((row) => !live.has(sessKey(row)));
  const total = onBoard.length + departed.length;
  const group = (title: string, members: readonly Row[]): Group | null =>
    members.length
      ? {
          title,
          rows: members.map((row) =>
            logRow(row, live, retained.has(sessKey(row)), payload, load, generated),
          ),
        }
      : null;
  return {
    counts: `${String(total)} sessions listed: ${String(onBoard.length)} on the board, ${String(departed.length)} retained after leaving the board.`,
    notice,
    limits:
      available && rows.length
        ? `${lead}The annotation store keeps the newest 256 and sixteen revisions each. ${evicts} These limits apply only to retained annotation records. Session history keeps a fourteen-day copy of the goal and each outcome line; this list does not recover saved words from that copy. Removal by the annotation store is an eviction and not an expiry.`
        : '',
    groups: [
      group('On the board', onBoard),
      group('Retained after leaving the board', departed),
    ].filter((entry): entry is Group => entry !== null),
    closing: available ? closing(ordered, total, payload) : READING_NOT_A_VERIFICATION,
  };
}
