import { nextNumber } from '../api/bootstrap';
import { formatDuration } from '../shell/format';
import { goalOf, landingOf, sessionStop, type Landing } from './landing';
import {
  ageSeconds,
  endedAt,
  isRecord,
  pair,
  promptCopied,
  records,
  textOf,
  trimmed,
  type Pair,
  type Row,
} from './values';

export type ObservedSession = {
  readonly sid: string;
  readonly harness: string;
  /** The published label, exactly: whitespace and the empty label are groups of their own. */
  readonly project: string;
  readonly focusable: unknown;
  readonly resume_id: unknown;
  readonly blockText: string;
  readonly blockKnown: boolean;
  readonly blockNote: string;
  readonly outcomeGlyph: string;
  readonly waitedText: string;
  readonly waitedKnown: boolean;
  readonly state: string;
  readonly isWorking: boolean;
  readonly isNeeds: boolean;
  readonly isEnded: boolean;
  /** Working, waiting on the reader, or holding an exact request. */
  readonly isActive: boolean;
  /** Working AND the collector says it is live: the one claim the running count rests on. */
  readonly isLive: boolean;
  readonly isQuiet: boolean;
  readonly lastActivityAt: number | null;
  readonly tone: 'ok' | 'want' | 'bad' | 'unknown';
  readonly landing: Landing;
  readonly ownGoalSrcText: string;
  readonly ownGoalSrcKnown: boolean;
  readonly ownGoalAt: number | null;
  readonly subagents: readonly unknown[];
  readonly subagentsOmitted: number;
  readonly tasks: readonly unknown[];
} & Pair<'title'> &
  Pair<'prompt'> &
  Pair<'now'> &
  Pair<'next'> &
  Pair<'where'> &
  Pair<'turn'> &
  Pair<'outcome'> &
  Pair<'git'> &
  Pair<'rate'> &
  Pair<'ask'> &
  Pair<'stuck'> &
  Pair<'sharedLabel'> &
  Pair<'ownGoal'>;

/* The exact published label, including whitespace and the empty label: the page groups by it as it
   stands, so two spellings of one directory are two groups and say so. */
export function labelOf(session: Row): string {
  return String(session['project'] == null ? '' : session['project']);
}

/* A title that is only an identifier (an issue key, or the session's own id) says nothing a reader can use, so
   the goal, then the first prompt (never a correction the reader copied, nor a control message), then the
   last prompt where the harness publishes no first one, stands in for it: its first line, cut at a width a heading can hold. Only the
   session page's heading asks: a Sessions row keeps the title as published, since the rows are held to the recorded
   page. */
/* An issue key is upper-case with a number of two or more digits: "gpt-4" and "utf-8" are real titles. */
const ISSUE_KEY = /^[A-Z][A-Z0-9]{1,9}-\d{2,}$/;
const HEX_ID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){0,4}(?:-[0-9a-f]{12})?$/i;
const TITLE_WIDTH = 120;

export function pageTitleOf(source: Row): string {
  const goal = goalOf(source);
  const title = trimmed(source['title']);
  if (!title) return '';
  if (!ISSUE_KEY.test(title) && !HEX_ID.test(title) && title !== trimmed(source['sid']))
    return title;
  const firstPrompt =
    promptCopied(source, 'first_prompt') || source['first_prompt_control'] === true
      ? ''
      : trimmed(source['first_prompt']);
  const words = (goal ? trimmed(goal.text) : '') || firstPrompt || trimmed(source['last_prompt']);
  const line =
    words
      .split('\n')
      .find((part) => part.trim())
      ?.trim() ?? '';
  if (!line) return title;
  return line.length > TITLE_WIDTH ? `${line.slice(0, TITLE_WIDTH - 1).trimEnd()}…` : line;
}

/* One row of the model, from one payload row. `asks` are the exact requests that belong to it,
   `harness` the payload's own row about the harness that published it, and `shared` how many rows carry
   its label. Nothing here reads the DOM, the clock or a store: a figure is derived from the payload it
   arrived in, so the same payload always draws the same page. */
export function observeSession(
  source: Row,
  asks: readonly Row[],
  harness: Row | undefined,
  generated: number | null,
  shared: number,
): ObservedSession {
  const ended = endedAt(source) !== null;
  const state = source['state'];
  const working = !ended && state === 'working';
  const needs = !ended && state === 'needs_input';
  const quiet = !ended && state === 'idle';
  const lastActivityAt = nextNumber(source['last_activity']);
  const quietSeconds = quiet ? formatDuration(ageSeconds(generated, lastActivityAt)) : null;
  const stateKnown = state === 'working' || state === 'needs_input' || state === 'idle';
  const question = asks
    .map((ask) => trimmed(ask['question']))
    .filter(Boolean)
    .join('\n');
  const tasks = records(source['tasks']);
  const taskWith = (status: string) =>
    tasks.find((row) => row['status'] === status && trimmed(row['subject']));
  const doing = taskWith('in_progress');
  const pending = taskWith('pending');
  const gaps = Array.isArray(source['source_gaps']) ? (source['source_gaps'] as unknown[]) : [];
  const reporter = Boolean(
    harness &&
      !harness['error'] &&
      harness['reports_needs_input'] === true &&
      !gaps.includes('block state'),
  );
  const blocked = needs || Boolean(question);
  const blockKnown = Boolean(blocked || reporter);
  const waitAge = asks
    .map((ask) => nextNumber(ask['age_sec']))
    .filter((age): age is number => age !== null && age >= 0);
  const stampAge = ageSeconds(generated, source['blocked_since']);
  const age = waitAge.length ? Math.max(...waitAge) : blocked ? stampAge : null;
  const rate = nextNumber(source['rate_per_min']);
  const rateKnown =
    rate !== null &&
    rate >= 0 &&
    Boolean(
      harness &&
        !harness['error'] &&
        harness['reports_rate'] === true &&
        !gaps.includes('token accounting'),
    );
  const loop = source['loop'];
  const loopErrors = isRecord(loop) ? loop['errors'] : undefined;
  const loopFailures = isRecord(loop) ? loop['failures'] : undefined;
  const errors =
    typeof loopErrors === 'number' && Number.isInteger(loopErrors) && loopErrors > 0
      ? loopErrors
      : 0;
  const failures =
    typeof loopFailures === 'number' && Number.isInteger(loopFailures) && loopFailures > errors
      ? loopFailures
      : 0;
  const stuck = errors
    ? `${String(errors)} tool failures in a row` +
      (failures ? ` · ${String(failures)} failures this turn` : '')
    : '';
  const stopped = state === 'idle' && (nextNumber(source['finished_at']) ?? 0) > 0;
  /* A stop Claude Code's transcript records is named as the transcript's, here as in HOW IT LANDED beside
     it, so "Session facts" never says no stop was observed next to a card naming one. */
  const recordedStop = state === 'idle' ? sessionStop(source) : null;
  const transcriptStop = !stopped && Boolean(recordedStop && recordedStop.kind === 'transcript');
  const outcomeKnown = ended || stopped || transcriptStop;
  const outcomePrefix = ended
    ? 'Session ended'
    : stopped
      ? 'Stop observed'
      : "Turn stop in Claude Code's transcript";
  const landing = landingOf(source, ended, recordedStop);
  const gitKnown = typeof source['dirty'] === 'boolean';
  const outcome = outcomeKnown
    ? outcomePrefix +
      (source['dirty'] === true
        ? ' with uncommitted work'
        : source['dirty'] === false
          ? '; git state clean'
          : '; git state not measured')
    : '';
  let git = '';
  if (gitKnown) {
    git = source['dirty'] ? 'Uncommitted work observed' : 'Git state reported clean';
    const changed = source['changed'];
    if (source['dirty'] && Number.isInteger(changed) && (changed as number) >= 0)
      git = `${String(changed)} changed entries`;
  }
  const sharedText =
    shared > 1
      ? `${String(shared)} sessions share this display label; shared location is not established`
      : '';
  const turn: Row = isRecord(source['turn']) ? source['turn'] : {};
  const turnElapsed = trimmed(turn['elapsed_h']);
  const turnEta = trimmed(turn['eta_h']);
  const turnText = turnElapsed
    ? `${turnElapsed} into turn` + (turnEta ? ` · ${turnEta} estimated remaining` : '')
    : '';
  const turnReporter = Boolean(
    harness &&
      !harness['error'] &&
      (typeof harness['reports_turn_bounds'] === 'boolean'
        ? harness['reports_turn_bounds']
        : harness['key'] !== 'cursor' && source['harness'] !== 'cursor'),
  );
  const turnReason = turnReporter
    ? working
      ? 'Turn bounds not published'
      : 'No turn in progress'
    : 'Harness does not report turn bounds';
  const goal = goalOf(source);
  const stateDetail = trimmed(source['state_detail']);
  /* A quiet row states how long ago it was last active in place of the collector's "awaiting your
     message": a recent observation cannot prove the harness is still open, so a day-old idle row cannot
     claim to be waiting. A session holding an exact request is not quiet, and with no timestamp the old
     reading stands, minus the waiting claim. */
  const nowValue = ended
    ? 'Session reported its own end'
    : stateKnown
      ? doing
        ? doing['subject']
        : quiet && !question
          ? quietSeconds
            ? `last active ${quietSeconds} ago`
            : stateDetail
              ? 'quiet'
              : ''
          : source['state_detail']
      : '';
  const row = {
    sid: textOf(source['sid']),
    harness: textOf(source['harness']),
    project: labelOf(source),
    focusable: source['focusable'] == null ? false : source['focusable'],
    resume_id: source['resume_id'] == null ? null : source['resume_id'],
    ...pair('title', source['title'], 'Title not published'),
    ...pair('prompt', source['last_prompt'], 'Last prompt not published'),
    ...pair('now', nowValue, stateKnown ? 'Activity not published' : 'No state published'),
    ...pair('next', pending?.['subject'], 'No pending step published'),
    ...pair('where', '', 'Exact location not published'),
    ...pair('turn', turnText, turnReason),
    blockText: blocked
      ? 'Waiting on you'
      : reporter
        ? 'No reported block'
        : gaps.includes('block state')
          ? 'Block state could not be read'
          : 'Harness does not report blocks',
    blockKnown,
    blockNote:
      question ||
      (needs
        ? source['wait_unconfirmed']
          ? 'Unconfirmed: no positive observation in 5m; prompt may still be standing'
          : trimmed(source['state_detail']) || 'Block reported'
        : ''),
    // Stops and ends are published; readership and termination cause are not. Their absence belongs in
    // open and coverage, never in an inferred outcome.
    ...pair('outcome', outcome, 'No stop or end observed'),
    outcomeGlyph: outcomeKnown
      ? source['dirty'] === true
        ? '△'
        : source['dirty'] === false
          ? '✓'
          : '◦'
      : '',
    ...pair('git', git, 'Git state was not measured'),
    ...pair(
      'rate',
      rateKnown ? `${Math.round(rate as number).toLocaleString('en-US')} /m` : '',
      'Token rate not reported',
    ),
    ...pair('ask', question, 'No exact request published'),
    waitedText: age === null ? 'Wait duration not published' : (formatDuration(age) ?? ''),
    waitedKnown: age !== null,
    ...pair('stuck', stuck, 'No stuck signal published'),
    ...pair('sharedLabel', sharedText, 'No shared display label observed'),
    state: textOf(source['state']),
    isWorking: working,
    isNeeds: needs,
    isEnded: ended,
    isActive: working || needs || Boolean(question),
    isLive: working && source['active'] === true,
    isQuiet: quiet,
    lastActivityAt,
    tone: (outcomeKnown
      ? gitKnown
        ? source['dirty']
          ? 'bad'
          : 'ok'
        : 'unknown'
      : blocked || errors || (working && turn['long'] === true)
        ? 'want'
        : blockKnown && (state === 'working' || state === 'idle')
          ? 'ok'
          : 'unknown') as ObservedSession['tone'],
    landing,
    /* This session's own derived goal, beside the project's. A session-scope render used to take the
       project's, which is the most recently active session's, so the reader saw their words for one
       session above another session's directive. */
    ...pair('ownGoal', goal && goal.text, 'This session published no goal'),
    ownGoalSrcText: goal ? goal.src : 'Goal source not published',
    ownGoalSrcKnown: Boolean(goal),
    ownGoalAt: goal && goal.at !== null ? goal.at : null,
    subagents: Array.isArray(source['subagents']) ? (source['subagents'] as unknown[]) : [],
    subagentsOmitted: Math.max(0, nextNumber(source['subagents_omitted']) ?? 0),
    tasks: Array.isArray(source['tasks']) ? (source['tasks'] as unknown[]) : [],
  };
  return row as ObservedSession;
}
