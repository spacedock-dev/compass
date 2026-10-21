import { nextNumber } from '../api/bootstrap';
import {
  clock,
  durationSince,
  endedAt,
  exactAskOwner,
  gapNames,
  isRecord,
  isScanOnly,
  payloadAskRows,
  records,
  sessionKey,
  type ObservedSession,
  type Row,
} from '../observed';
import { revisionSuperseded } from './rows';

/* The pure half of the session page: every sentence, count and ordering it prints, derived from the
   payload row and the model read from it. `next-session.js` is the oracle; the rendered text of both
   pages is compared over generated payloads. Nothing here reads the DOM or the clock: a figure ages only
   when a new payload arrives, because it is measured from the payload's own `generated`. */

export const ANSWER_FAILURE = 'no confirmation came back — it may already have been answered';
export const LONG_TURN_NOTE =
  'This request is running long (or estimated to). Double-check what the agent is doing matches your expectations.';

/* The exact requests that belong to one session, in payload order, only while the board says it
   publishes requests. A request whose owner is not exactly this session is none of its business. */
export function sessionAsks(payload: Row, session: Row): Row[] {
  if (payload['ask'] !== true || !Array.isArray(payload['asks'])) return [];
  const key = sessionKey(session);
  return payloadAskRows(payload).filter((ask) => {
    const owner = exactAskOwner(payload, ask);
    return owner !== null && sessionKey(owner) === key;
  });
}

export function registryLabel(labels: ReadonlyMap<string, string>, session: Row): string {
  return labels.get(String(session['harness'] || '')) ?? '';
}

export function askingTitle(labels: ReadonlyMap<string, string>, session: Row): string {
  return `${registryLabel(labels, session) || 'An agent'} is asking you`;
}

const DETAIL_STATES = {
  needs_input: { label: 'needs input', token: 'needs_input' },
  working: { label: 'working', token: 'working' },
  idle: { label: 'idle', token: 'idle' },
} as const;

export function detailState(
  state: unknown,
): { readonly label: string; readonly token: string } | null {
  return typeof state === 'string' && Object.hasOwn(DETAIL_STATES, state)
    ? DETAIL_STATES[state as keyof typeof DETAIL_STATES]
    : null;
}

/* The measured line under the title. An observed end supersedes the present-tense activity and duration
   phrases, since an ended session must not describe itself as awaiting input. The last two clauses are
   unconditional: every clause above is a reading, and these say what the readings cannot cover, so they
   qualify the whole line rather than any one of them. `entries` is the activity list's own count, and
   nothing where the record was not read. */
export function sessionMeta(
  session: Row,
  labels: ReadonlyMap<string, string>,
  generated: number | null,
  entries: number | null,
  /** The entries since the intent's window opened, where entries before it are also held. */
  since: number | null = null,
): string {
  const parts: string[] = [];
  const harness = registryLabel(labels, session);
  if (harness) parts.push(harness);
  const ended = durationSince(generated, endedAt(session));
  if (ended !== null) {
    parts.push(`ended ${ended} ago`);
  } else {
    if (session['state_detail']) parts.push(String(session['state_detail']));
    const state = session['state'];
    if (state === 'needs_input') {
      const blocked = durationSince(generated, session['blocked_since']);
      if (blocked !== null) parts.push(`blocked ${blocked}`);
      if (session['wait_unconfirmed']) parts.push('unconfirmed: no positive observation in 5m');
    } else if (state === 'working') {
      const turn = session['turn'];
      const elapsed =
        isRecord(turn) && typeof turn['elapsed_h'] === 'string' ? turn['elapsed_h'].trim() : '';
      if (elapsed) parts.push(`turn started ${elapsed} ago`);
    } else if (state === 'idle') {
      const started = durationSince(generated, session['started_at']);
      if (started !== null) parts.push(`session started ${started} ago`);
    }
  }
  if (entries !== null)
    parts.push(
      `${String(entries)} ${entries === 1 ? 'entry' : 'entries'}${since === null ? '' : `, ${String(since)} since your intent’s start`}`,
    );
  if (isScanOnly(session)) parts.push('read by scanning: no turn end can be observed here');
  const gaps = gapNames(session);
  if (gaps.length) parts.push(`source not fully read: ${gaps.join(', ')}`);
  return parts.join(' · ');
}

export interface Fact {
  readonly key: 'next' | 'turn' | 'block' | 'outcome' | 'git' | 'project';
  readonly label: string;
  readonly text: string;
  readonly known: boolean;
  readonly note: string;
  /** The next step, known, with no exact request open: the one fact the command surface scopes to. */
  readonly commandFact: boolean;
}

export interface Facts {
  readonly shown: readonly Fact[];
  readonly behind: readonly Fact[];
  readonly summary: string;
}

/* What the reader acts on stays in view: the next step and whether it is blocked. Turn, outcome, git
   state and project sit behind "Session facts", with the outcome and git state in the summary, because
   HOW IT LANDED says both again. A known outcome already carries the git clause ("Session ended; git
   state not measured"), so the summary says it once. */
export function sessionFacts(observed: ObservedSession, asks: readonly Row[]): Facts {
  const rows: Fact[] = [
    {
      key: 'next',
      label: 'NEXT STEP',
      text: observed.nextText,
      known: observed.nextKnown,
      note: '',
      commandFact: observed.nextKnown && asks.length === 0,
    },
    {
      key: 'turn',
      label: 'TURN',
      text: observed.turnText,
      known: observed.turnKnown,
      note: '',
      commandFact: false,
    },
    {
      key: 'block',
      label: 'BLOCKED',
      text: observed.blockText,
      known: observed.blockKnown,
      note: observed.blockNote,
      commandFact: false,
    },
    {
      key: 'outcome',
      label: 'OUTCOME',
      text: observed.outcomeText,
      known: observed.outcomeKnown,
      note: '',
      commandFact: false,
    },
    {
      key: 'git',
      label: 'GIT STATE',
      text: observed.gitText,
      known: observed.gitKnown,
      note: '',
      commandFact: false,
    },
    {
      key: 'project',
      label: 'PROJECT',
      text: observed.project,
      known: true,
      note: '',
      commandFact: false,
    },
  ];
  return {
    shown: rows.filter((row) => row.key === 'next' || row.key === 'block'),
    behind: rows.filter((row) => row.key !== 'next' && row.key !== 'block'),
    summary: observed.outcomeKnown
      ? `Session facts: ${observed.outcomeText}`
      : `Session facts: ${observed.outcomeText} · ${observed.gitText}`,
  };
}

const MCP_TOOL = /\bmcp__([A-Za-z0-9-]+(?:_[A-Za-z0-9-]+)*?)__([A-Za-z0-9_-]+)/g;
const MCP_HOST_PREFIX = /^(?:claude_ai_|claude_code_|plugin_)/;

/* A tool name as a person reads it: the service, then what it does. Kept beside the page that prints it
   rather than in a shared helper, because no other page names a tool. */
export function humanTool(text: string): string {
  return text.replace(MCP_TOOL, (whole, server: string, tool: string) => {
    const service = server.replace(MCP_HOST_PREFIX, '').replace(/_+/g, ' ').trim();
    const action = tool.replace(/_+/g, ' ').trim();
    if (!action) return whole;
    return (service ? `${service} · ` : '') + action;
  });
}

/* Three readings of one turn, and each sentence says which one fired. Saying "in a row" about a total
   would be false the moment a success split it, which is the whole reason the total exists. */
export function loopNote(loop: unknown): string {
  if (!isRecord(loop)) return '';
  const errors = nextNumber(loop['errors']);
  if (errors === null || !Number.isInteger(errors) || errors <= 0) return '';
  const rawTool = typeof loop['tool'] === 'string' ? loop['tool'].trim() : '';
  const tool = rawTool ? ` (most recently ${humanTool(rawTool)})` : '';
  const failures = nextNumber(loop['failures']);
  const total =
    failures !== null && Number.isInteger(failures) && failures > errors ? failures : errors;
  const calls = total === 1 ? 'tool call' : 'tool calls';
  const advice = 'Check the agent is working the problem rather than repeating the failure.';
  if (loop['barren'] === true)
    return `${String(total)} ${calls} failed this turn and none succeeded${tool}. ${advice}`;
  if (total > errors)
    return `${String(total)} ${calls} failed this turn, ${String(errors)} of them consecutive${tool}. ${advice}`;
  return `${String(errors)} ${calls} in a row came back as errors${tool}. ${advice}`;
}

export interface Health {
  readonly kind: 'long-turn' | 'failed-tool-loop';
  readonly label: 'LONG TURN' | 'FAILED TOOL LOOP';
  readonly why: string;
}

export function sessionHealth(session: Row): Health | null {
  const turn = session['turn'];
  const long = isRecord(turn) && turn['long'] === true;
  const note = loopNote(session['loop']);
  if (!long && !note) return null;
  return {
    kind: long ? 'long-turn' : 'failed-tool-loop',
    label: long ? 'LONG TURN' : 'FAILED TOOL LOOP',
    why: note || LONG_TURN_NOTE,
  };
}

export type TaskGlyph = 'completed' | 'in progress' | 'pending';

export interface TaskRow {
  readonly id: string;
  readonly subject: string;
  readonly pending: boolean;
  readonly glyph: TaskGlyph;
}

export interface Tasks {
  readonly heading: string;
  readonly rows: readonly TaskRow[];
}

function field(value: unknown, key: string): unknown {
  return isRecord(value) ? value[key] : undefined;
}

const published = (value: unknown): string => String(value == null ? '' : value);

/* Gated on the payload, not on the harness name: it was `harness !== "claude"` while Claude was the only
   collector filling the field, and that spelling hid a Codex plan the moment one arrived. An empty list
   still draws nothing, which is the check that was wanted. */
export function sessionTasks(tasks: readonly unknown[]): Tasks | null {
  if (!tasks.length) return null;
  const completed = tasks.filter((task) => field(task, 'status') === 'completed').length;
  return {
    heading: `TASKS · ${String(completed)} OF ${String(tasks.length)} DONE`,
    rows: tasks.map((task) => {
      const status = String(field(task, 'status') || 'pending');
      return {
        id: published(field(task, 'id')),
        subject: published(field(task, 'subject')),
        pending: status === 'pending',
        glyph:
          status === 'completed'
            ? 'completed'
            : status === 'in_progress'
              ? 'in progress'
              : 'pending',
      };
    }),
  };
}

/* Only `active === false` withholds the live pulse and the running count. Unset means the collector does
   not measure per-entry liveness, so a harness nobody has taught to measure it renders as it always did. */
export function subagentIsLive(subagent: unknown): boolean {
  return !(isRecord(subagent) && subagent['active'] === false);
}

export interface SubagentRow {
  readonly index: number;
  readonly live: boolean;
  readonly name: string;
  readonly parent: string;
  readonly elapsed: string | null;
}

export interface Subagents {
  readonly label: string;
  readonly rows: readonly SubagentRow[];
  readonly omitted: number;
}

/* Every number in the heading counts DIRECT children, so the leading clause agrees with the row's state
   line above it: a grandchild is deliberately not in that population. A worker beneath a teammate is a
   third population and gets its own clause rather than being folded into either count. The heading has to
   survive a finished board still inside the display window, every element inactive: hiding the list there
   would be the vanishing act, so the heading tells the truth and the rows stay. */
export function sessionSubagents(
  subagents: readonly unknown[],
  omitted: number,
  generated: number | null,
): Subagents | null {
  if (!subagents.length) return null;
  const parentOf = (subagent: unknown): string => {
    const parent = field(subagent, 'parent');
    return parent ? String(parent) : '';
  };
  const direct = subagents.filter((subagent) => !parentOf(subagent));
  const running = direct.filter(subagentIsLive).length;
  const beneath = subagents.filter(
    (subagent) => parentOf(subagent) && subagentIsLive(subagent),
  ).length;
  const label =
    (running === 0
      ? `${String(direct.length)} SUBAGENT${direct.length === 1 ? '' : 'S'} · NONE RUNNING`
      : running === 1
        ? '1 RUNNING SUBAGENT'
        : `${String(running)} RUNNING SUBAGENTS`) +
    (beneath === 0
      ? ''
      : ` · ${String(beneath)} WORKER${beneath === 1 ? '' : 'S'} RUNNING BENEATH`);
  return {
    label,
    omitted: omitted || 0,
    rows: subagents.map((subagent, index) => ({
      index,
      live: subagentIsLive(subagent),
      name: String(field(subagent, 'name') || 'subagent'),
      parent: parentOf(subagent),
      elapsed: durationSince(generated, field(subagent, 'started_at')),
    })),
  };
}

export function compactTokens(value: number): string {
  if (value < 1000) return Math.round(value).toLocaleString('en-US');
  return `${String(Math.round(value / 100) / 10)}k`;
}

export interface Footer {
  readonly source: 'turn' | 'session';
  readonly text: string;
}

/* The turn's tokens while it runs, the session's otherwise, and the other where the preferred one was not
   published. Nothing where neither was: a zero would be a default and not a count. */
export function sessionFooter(session: Row): Footer | null {
  const sessionTotal = nextNumber(session['session_output_tokens']);
  const turnTotal = nextNumber(session['turn_output_tokens']);
  let source: 'turn' | 'session' = session['state'] === 'working' ? 'turn' : 'session';
  let value = source === 'turn' ? turnTotal : sessionTotal;
  if (value === null) {
    source = source === 'turn' ? 'session' : 'turn';
    value = source === 'turn' ? turnTotal : sessionTotal;
  }
  return value === null
    ? null
    : { source, text: `${compactTokens(value)} output tokens this ${source}` };
}

export interface Delivery {
  readonly outcome: string;
  readonly mixed: boolean;
  readonly count: string;
  readonly why: string;
  readonly mixedWhy: string;
  readonly bindingWhy: string;
  readonly laneWhy: string;
}

/* The four published sentences and the count that scopes them, in one wording for every surface. Every
   sentence is composed by the server and printed verbatim: the wording is the product, and three
   surfaces wording it three ways is how the least true reading becomes the most reassuring one. This
   chooses WHETHER to print, never WHAT. Nothing is drawn for a session with no raise: an absence of raises
   is not an absence of evidence about a raise, and a panel saying "no record" under a session nobody was
   alerted about invents a question the reader did not have. */
export function sessionDelivery(session: Row): Delivery | null {
  const raises = Number(session['delivery_raises']);
  if (!Number.isFinite(raises) || raises < 1) return null;
  /* The sentence describes the LATEST raise and no other, so the count and the sentence must not read as
     one claim: "3 notifications were raised" above one outcome reads as three of that outcome. */
  const count =
    raises === 1
      ? 'One notification was raised about this session'
      : `${String(raises)} notifications were raised about this session. The most recent:`;
  return {
    outcome: published(session['delivery_outcome']),
    mixed: session['delivery_mixed'] === true,
    count,
    why: published(session['delivery_why']),
    mixedWhy: session['delivery_mixed'] === true ? published(session['delivery_mixed_why']) : '',
    bindingWhy: published(session['delivery_binding_why']),
    // `browser_lane_why` and never `browser_lane`: the flag is board-wide and says nothing about one
    // session, while the sentence is relative to this raise.
    laneWhy: published(session['browser_lane_why']),
  };
}

/* The delivery figures for the lane that raises a departure, never the board's: the flat keys carry the
   latest raise of ANY lane, and a session with no departure at all printed another lane's outcome under a
   heading about raises. */
function departureDelivery(session: Row): Row | null {
  const scoped = session['delivery_departure'];
  return scoped && typeof scoped === 'object' ? (scoped as Row) : null;
}

/* The sentence for a departure no raise was ever recorded against. Printed only beside a departure and
   only when the DEPARTURE LANE holds no raise for this session. */
export function deliveryAbsence(session: Row, hasDeparture: boolean): string {
  if (!hasDeparture) return '';
  const scoped = departureDelivery(session);
  if (!scoped) return '';
  const raises = Number(scoped['delivery_raises']);
  if (Number.isFinite(raises) && raises > 0) return '';
  return published(scoped['delivery_none_why']);
}

export interface DepartureRow {
  readonly constraint: string;
  readonly at: string;
  readonly clause: string;
  readonly reading: string;
  readonly base: string;
  readonly stale: string;
  readonly followUp: string;
}

/* One raised departure, with the baseline it rested on. The baseline and the cutoff are printed rather
   than implied: by the time this is read the intent may have changed and the evidence window has moved, so
   a row that does not say which words it read and where its evidence stopped cannot be checked by the
   person it was raised to. A raise whose baseline did not survive says so rather than borrowing today's.
   The stale line names times; the revision number only decides whether it shows. */
export function departureRow(
  row: Row,
  current: number | null,
  changedAt: number | null = null,
): DepartureRow {
  const text = (key: string): string => published(row[key]);
  const revision = Number(row['revision']);
  const read = Number.isFinite(revision) && revision > 0 ? revision : null;
  const baseline =
    read !== null
      ? 'read against the intent as it stood then'
      : 'the intent it read is not on record';
  const cutoff = Number(row['cutoff']);
  const window =
    Number.isFinite(cutoff) && cutoff > 0
      ? ` · evidence to ${clock(cutoff)}`
      : ' · the evidence window is not on record';
  const at = Number(row['at']);
  return {
    constraint: text('constraint'),
    at: Number.isFinite(at) && at > 0 ? clock(at) : '',
    clause: text('clause'),
    reading: text('reading'),
    base:
      baseline +
      window +
      (text('cutoff_text') ? ` · ${text('cutoff_text')}` : '') +
      (text('evidence') ? ` · ${text('evidence')}` : ''),
    stale: revisionSuperseded('This raise', read, current, nextNumber(row['at']), changedAt),
    followUp: text('follow_up'),
  };
}

export interface Departures {
  readonly heading: string;
  readonly rows: readonly DepartureRow[];
  readonly why: string;
  readonly absence: string;
}

/* The rows and the absence sentence, in one wording for every surface that shows them: the drift block's
   departures section. The heading counts, and each row says when ("while you were away" was a claim about
   the reader, and nothing here observes where they were). */
/* What the page says about the checks run while the reader was away when that lane is off. Two sentences and two
   subjects, in two paragraphs so neither qualifies the other: the first is about the present, the second about the
   record, which is read whichever way the switch is set. The wording is the legacy page's. */
export const LANE_OFF_RECORD =
  'The checks that run while you were away are off for this run, so nothing new is being checked. What was already raised is still on record.';
export function laneOffWhy(reason: unknown): string {
  return reason === 'run-disabled'
    ? 'The model off switch refuses unasked checks. Restart with --unasked-readings and without either --no-harness-usage or --no-observer-model to enable them.'
    : 'Nothing watches for a departure on its own. Start with --unasked-readings to have Compass check a session against what you asked for while you are away.';
}

export function unaskedDepartures(session: Row): Departures | null {
  const raised = Array.isArray(session['departures']) ? (session['departures'] as unknown[]) : [];
  const why = published(session['departure_why']);
  if (!raised.length && !why) return null;
  const current = nextNumber(session['annotation_revision']);
  return {
    heading:
      raised.length === 1
        ? 'One departure was raised'
        : `${String(raised.length)} departures were raised`,
    rows: raised.map((row) =>
      departureRow(isRecord(row) ? row : {}, current, nextNumber(session['annotation_at'])),
    ),
    why,
    absence: deliveryAbsence(session, raised.length > 0),
  };
}

export const FOCUS_OFF_LINE = 'Terminal raise: off for this run.';
const NO_TERMINAL_LINE =
  'No terminal was reported for this session, so it cannot be raised. That is the ordinary answer outside tmux, for a session older than this server run, and on Linux and Windows.';
const RAISE_LIMIT =
  'A raise switches what the terminal displays; its window may still be behind others.';

export function raiseLimit(canRaise: boolean, focusCapability: boolean): string {
  return canRaise ? RAISE_LIMIT : !focusCapability ? FOCUS_OFF_LINE : NO_TERMINAL_LINE;
}

export interface CommandReports {
  readonly state: 'off' | 'unsupported' | 'on';
  readonly absent: string;
  readonly rows: readonly { readonly text: string; readonly source: string }[];
}

export function commandReports(payload: Row, session: Row): CommandReports {
  const disabled = payload['irreversible_enabled'] !== true;
  const unsupported = !['claude', 'codex'].includes(String(session['harness']));
  const reports = disabled || unsupported ? [] : records(session['command_reports']).slice(0, 20);
  const absent = disabled
    ? 'Command-shape reports are disabled for this run.'
    : unsupported
      ? 'Command-shape reporting is unsupported for this harness.'
      : 'No matching reports received; missing hooks and unmatched commands can look the same.';
  return {
    state: disabled ? 'off' : unsupported ? 'unsupported' : 'on',
    absent,
    rows: reports.map((report) => {
      const stamp = nextNumber(report['timestamp']);
      const date = stamp === null ? null : new Date(stamp * 1000);
      // A timestamp that is no date prints nothing: the page this ports throws on one, which would blank
      // the whole session for a malformed report.
      const when = date && !Number.isNaN(date.getTime()) ? ` · ${date.toISOString()}` : '';
      return {
        text: `Command shape reported: ${String(report['label'])}`,
        source: `${String(report['tool_name'])}${when}`,
      };
    }),
  };
}
