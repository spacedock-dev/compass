import { nextNumber } from '../api/bootstrap';
import type { Annotation } from '../intent/annotation';
import { personAuthored, type WorkEntry } from '../intent/work';
import { clock, type Row } from '../observed';
import { revisionSuperseded } from '../sessions/rows';
import { fmtDur } from './route';
import {
  CLAIMS,
  CONSISTENT,
  DEPARTURE,
  GOAL_UNCLEAR_RESULT,
  GOAL_NOT_SHOWN,
  GOAL_ONLY_NO_LEVEL,
  GOAL_UNCLEAR_VERDICT,
  NOT_REACHED,
  RESULT_CANT_TELL,
  RESULT_CLAIM_TAIL,
  RESULT_NOTHING_SHOWS,
  RESULT_NOTHING_SHOWS_REASON,
  UNSUPPORTED,
  UNVERIFIABLE,
} from './sentences';
import {
  agentMessage,
  evidenceAt,
  isOutcomeLine,
  windowPartial,
  type Criterion,
  type Shape,
} from './shape';

/* What the result stage says about a reading that survived the shape contract: where each line points, the
   answer over all of them, where the work went and why a result is stale. Each function returns the words
   and the numbers the words are made of, so the component that draws them cannot say a figure the list did
   not give. The legacy cockpit's `nextCockpitResult*` and `nextDriftAnswer` are the oracle. */

export type Numbers = ReadonlyMap<string, string>;
export type EntryIndex = ReadonlyMap<string, WorkEntry>;

export function indexEntries(entries: readonly WorkEntry[]): Map<string, WorkEntry> {
  return new Map(entries.map((entry) => [String(entry.id || ''), entry]));
}

/* Each line's words, verbatim from the ruling, and never "Done" or a check mark. The number is the activity
   list's own, so the "#<n>" is a row on screen; an entry the list does not number keeps its time instead.
   `arrived` is the failed-check answer's: the time it falls back to is when the result arrived, not when the
   check was called. */
export function resultWhere(
  entry: WorkEntry | null | undefined,
  numbers: Numbers,
  arrived = false,
): string {
  if (!entry) return '';
  const n = numbers.get(String(entry.id || ''));
  if (n !== undefined) return `#${String(n)}`;
  const at = arrived ? evidenceAt(entry) : nextNumber(entry.at);
  return at !== null && at > 0 ? clock(at) : '';
}

/* The claims row's four states, each naming the agent's message by the list's number. "Not shown" says the
   record read is the board's recent tail, so it is about what was read, never that the thing did not
   happen. */
export function claimStatus(row: Criterion, numbers: Numbers, short: boolean): string {
  const said = resultWhere(row.claimEntry, numbers);
  const record = resultWhere(row.recordEntry, numbers);
  const what = said ? `What the agent said at ${said}` : 'What the agent said';
  if (row.result === DEPARTURE) {
    return `${what} is contradicted${record ? ` at ${record}` : ''}`;
  }
  if (row.result === UNSUPPORTED) {
    return short
      ? `${what} is not shown by the record`
      : `${what} is not shown by the record. ${RESULT_CLAIM_TAIL}`;
  }
  if (row.result === CONSISTENT && record) {
    const tool =
      row.recordEntry &&
      (String(row.recordEntry.type || '') === 'tool_report' || row.recordEntry.subject === 'check');
    return `${what} is shown at ${record}${tool && !short ? ', as the tool reported; not inspected' : ''}`;
  }
  return row.why || row.limit ? RESULT_CANT_TELL : RESULT_NOTHING_SHOWS;
}

export function resultStatus(
  row: Criterion,
  numbers: Numbers,
  byId: EntryIndex,
  short = false,
): string {
  if (row.key === CLAIMS) return claimStatus(row, numbers, short);
  if (row.result === NOT_REACHED) return 'Not reached at this stop';
  if (row.result === DEPARTURE) {
    const where = resultWhere(byId.get(String(row.citedIds[0] ?? '')), numbers);
    return where ? `Departs; evidence ${where}` : 'Departs';
  }
  if (row.result === CONSISTENT && row.restsOn) {
    const where = resultWhere(row.restsOnEntry, numbers);
    if (where) {
      /* `short` is the checklist's line in view: the source stays named, and the qualifier is said in full in
         the line's Evidence. */
      const who = row.restsOn === 'message' ? 'the agent' : 'the session';
      if (short) {
        return row.restsOn === 'tool'
          ? `Consistent with ${where}`
          : `Consistent with what ${who} said at ${where}`;
      }
      return row.restsOn === 'tool'
        ? `Consistent with ${where}, as the tool reported; not inspected`
        : `Consistent with what ${who} said at ${where}; not a check`;
    }
  }
  /* A consistent the page cannot place is no claim it can word, so it is said as what it is to the reader:
     nothing shown. */
  return row.why || row.limit
    ? RESULT_CANT_TELL
    : row.citedIds.length
      ? "Can't tell: what was read does not settle this"
      : RESULT_NOTHING_SHOWS;
}

/* The words of the claims row's heading, from the design's form: `What the agent claimed · "<claim>" is not
   shown by the record`. The claim is the title of the agent's message the row cites, the way
   `reading.claim_title` quotes it into a correction (the first sentence, its closing stop dropped). The tail is
   `claimStatus`'s own ruled wording by the list's numbers, so the two cannot say different things. Null where
   the row cites no message the page holds: there is nothing to quote, and `claimStatus` says what it can. */
export interface ClaimHeading {
  readonly claim: string;
  readonly tail: string;
}

export function claimHeading(row: Criterion, numbers: Numbers): ClaimHeading | null {
  if (row.key !== CLAIMS) return null;
  const claim = String(row.claimEntry?.summary || '')
    .trim()
    .replace(/\.+$/, '')
    .trim();
  if (!claim) return null;
  const record = resultWhere(row.recordEntry, numbers);
  if (row.result === DEPARTURE) {
    return { claim, tail: `is contradicted${record ? ` at ${record}` : ''}` };
  }
  if (row.result === UNSUPPORTED) return { claim, tail: 'is not shown by the record' };
  if (row.result === CONSISTENT && record) return { claim, tail: `is shown at ${record}` };
  return null;
}

/* Why a line reads "Can't tell", in the one sentence that is about that line. The rule that left it without a
   verdict says it where one did, a limit of the harness where that is the cause; otherwise the entries the
   reading read are named, or their absence is, so no two unsettled lines read the same unless they rest on
   the same thing. Never the generic "what was read does not settle this". */
export function cantTellReason(row: Criterion, numbers: Numbers): string {
  if (row.why) return row.why;
  if (row.limit) return row.limit;
  const cited = row.citedIds
    .map((id) => numbers.get(id))
    .filter((n): n is string => n !== undefined)
    .map((n) => `#${n}`);
  if (cited.length) {
    return `What it read, ${[...new Set(cited)].join(', ')}, neither shows nor contradicts this.`;
  }
  return row.citedIds.length
    ? 'What it read neither shows nor contradicts this.'
    : RESULT_NOTHING_SHOWS_REASON;
}

/* The kinds of check a claim can speak of, and the words of a check's own command that say which kind it is:
   the page's copy of `reading._LINE_KINDS` and `_CHECK_WORDS`, kept small for the same reason. */
type CheckKind = 'test' | 'lint' | 'type' | 'build';
const CHECK_KINDS: readonly CheckKind[] = ['test', 'lint', 'type', 'build'];
const CLAIM_WORDS: Readonly<Record<CheckKind, RegExp>> = {
  test: /\b(?:tests?|suite|specs?|pytest|vitest|jest|unittest)\b/i,
  lint: /\b(?:lint(?:s|ed|er|ing)?|ruff|biome|eslint)\b/i,
  type: /\b(?:type-?check(?:s|ed|ing)?|type\s+checks?|mypy|tsc|pyright)\b/i,
  build: /\bbuild(?:s|ing)?\b/i,
};
const COMMAND_WORDS: Readonly<Record<CheckKind, RegExp>> = {
  test: /^(?:pytest|unittest|vitest|jest|mocha|playwright|tests?|test:\S+|run_tests\.py)$/,
  lint: /^(?:ruff|biome|eslint|flake8|pylint|lint(?::\S+)?)$/,
  type: /^(?:mypy|tsc|pyright|typecheck|type-check)$/,
  build: /^build(?::\S+)?$/,
};

function commandKinds(summary: string): ReadonlySet<CheckKind> {
  const words = summary.split(/\s+/).map((word) => word.slice(word.lastIndexOf('/') + 1));
  return new Set(
    CHECK_KINDS.filter((kind) => words.some((word) => COMMAND_WORDS[kind].test(word))),
  );
}

/* Why a claim the record does not show is not shown, said about that claim: the kinds of check its own words
   name, and what the record read holds of each (none, a run with no recorded result, or a run the analysis
   did not tie to it). A claim that names no kind of check gets where the agent said it, what the record read
   is and how many checks it held, since "not shown" is about that and never about whether the thing happened. */
export function claimReason(
  row: Criterion,
  numbers: Numbers,
  entries: readonly WorkEntry[] = [],
  windowStart: number | null = null,
): string {
  if (row.key !== CLAIMS || row.result !== UNSUPPORTED) return '';
  const claim = String(row.claimEntry?.summary || '');
  const named = CHECK_KINDS.filter((kind) => CLAIM_WORDS[kind].test(claim));
  const checks = entries
    .filter(
      (entry) =>
        entry.type === 'tool_report' &&
        entry.subject === 'check' &&
        (windowStart === null || (nextNumber(entry.at) ?? 0) >= windowStart),
    )
    .map((entry) => ({ kinds: commandKinds(entry.summary), result: entry.result }));
  if (!named.length) {
    const said = resultWhere(row.claimEntry, numbers);
    const beside = checks.length
      ? `${checks.length} ${checks.length === 1 ? 'check was' : 'checks were'} recorded in what was read, and the analysis tied none to this claim.`
      : 'No check was recorded in what was read.';
    return `Nothing in the record read backs this claim${said ? `, which the agent made at ${said}` : ''}. ${RESULT_CLAIM_TAIL} ${beside}`;
  }
  const none: string[] = [];
  const unrecorded: string[] = [];
  const clauses: string[] = [];
  for (const kind of named) {
    const runs = checks.filter((check) => check.kinds.has(kind));
    const result =
      runs.find((run) => run.result === 'failed')?.result ??
      runs.find((run) => run.result === 'passed')?.result;
    if (!runs.length) none.push(kind);
    else if (result)
      clauses.push(
        `A ${kind} check ${result} on record, and the analysis did not tie it to this claim`,
      );
    else unrecorded.push(kind);
  }
  const first: string[] = [];
  if (none.length)
    first.push(
      `No ${none.map((kind) => `${kind} check`).join(' and no ')} was recorded in what was read`,
    );
  if (unrecorded.length)
    first.push(
      `The ${unrecorded.join(' and ')} ${unrecorded.length === 1 ? 'check ran' : 'checks ran'} with no recorded result`,
    );
  const all = [...first, ...clauses];
  return `${all.join('; ')}${first.length ? ', so nothing backs this claim' : ''}.`;
}

export type ResultState = 'departs' | 'unshown' | 'consistent' | 'cant-tell' | 'not-reached';

export function resultState(row: Criterion): ResultState {
  if (row.key === CLAIMS) {
    return row.result === DEPARTURE
      ? 'departs'
      : row.result === UNSUPPORTED
        ? 'unshown'
        : row.result === CONSISTENT && row.recordEntry
          ? 'consistent'
          : 'cant-tell';
  }
  return row.result === DEPARTURE
    ? 'departs'
    : row.result === NOT_REACHED
      ? 'not-reached'
      : row.result === CONSISTENT && row.restsOn
        ? 'consistent'
        : 'cant-tell';
}

/* The claims row as the result draws it: not where the agent made no claim, which the reading says as its
   own `unverifiable` with no reason. */
export function claimsDrawn(shape: Shape): Criterion[] {
  return shape.criteria.filter((row) => row.key === CLAIMS && row.result !== UNVERIFIABLE);
}

/* A failed run a later pass of the same check followed: a red test written first and then fixed, which is the
   work going as planned. The outline's rule (`session_outline._fixed`), held for the Drift card, because the
   page keeps the entries of earlier loads and so can hold both runs of one check. The same check is the
   server's own identity for it, which includes the directory it ran in: the command line alone says the same
   thing for `pytest -q` in two packages, and a pass in one must not hide a failure in the other. An entry
   that carries no identity is never matched, so it stays failed. */
function fixedFailures(entries: readonly WorkEntry[]): ReadonlySet<WorkEntry> {
  const passedAt = new Map<string, number>();
  for (const entry of entries) {
    if (
      entry.type !== 'tool_report' ||
      entry.subject !== 'check' ||
      entry.result !== 'passed' ||
      !entry.checkId
    )
      continue;
    const at = evidenceAt(entry) || 0;
    passedAt.set(entry.checkId, Math.max(passedAt.get(entry.checkId) ?? 0, at));
  }
  return new Set(
    entries.filter(
      (entry) =>
        entry.type === 'tool_report' &&
        entry.subject === 'check' &&
        entry.result === 'failed' &&
        Boolean(entry.checkId) &&
        (passedAt.get(entry.checkId) ?? 0) > (evidenceAt(entry) || 0),
    ),
  );
}

/* The failed checks after the words, by the server's rule (`_failed_checks`): one person-message boundary for
   the answer and the correction, mirroring reading.py, less a red test a later run fixed. The server's list is
   one run per check, so it never holds the fixed one. */
export function failedChecksAfterPerson(
  entries: readonly WorkEntry[],
  anchor: unknown = null,
  floor = 0,
): WorkEntry[] {
  const times = entries
    .filter((entry) => entry && entry.type === 'user_message')
    .map((entry) => nextNumber(entry.at))
    .filter((at): at is number => at !== null && at > 0);
  const last = nextNumber(anchor);
  if (last !== null && last > 0) times.push(last);
  if (!times.length) return [];
  const start = Math.max(floor || 0, ...times);
  const fixed = fixedFailures(entries);
  return entries.filter(
    (entry) =>
      entry &&
      entry.type === 'tool_report' &&
      entry.subject === 'check' &&
      entry.result === 'failed' &&
      !fixed.has(entry) &&
      (evidenceAt(entry) || 0) > start,
  );
}

export type Answer =
  | { readonly kind: 'departs'; readonly count: number; readonly departures: readonly Criterion[] }
  | { readonly kind: 'failed-check'; readonly failed: WorkEntry }
  | { readonly kind: 'not-reached' }
  | { readonly kind: 'cant-tell' }
  | { readonly kind: 'goal-unclear' }
  | { readonly kind: 'nothing-found' };

/* Item 14's answer reducer, over the rows after every page rule. Any valid departure departs, whatever the
   other lines say; otherwise a failed check in the reading's window; otherwise any line without a valid
   verdict cannot tell; otherwise nothing was found. A goal the model refused as too vague answers before all
   of that, and in place of it: no departure, check or level is read over words with no end state. A reading
   with no outcome line is answered by its goal row alone (owner, 2026-10-22: the goal's own end state is
   the outcome). The answer is about the intent alone, so the claims row never counts as departing from it
   and never holds "Nothing found" back. */
export function driftAnswer(
  shape: Shape,
  entries: readonly WorkEntry[],
  scan: Row | null | undefined = null,
): Answer {
  const intent = shape.criteria.filter((row) => row.key !== CLAIMS);
  if (intent.some((row) => row.key === 'goal' && row.result === GOAL_UNCLEAR_RESULT)) {
    return { kind: 'goal-unclear' };
  }
  const departures = intent.filter((row) => row.result === DEPARTURE);
  if (departures.length) return { kind: 'departs', count: departures.length, departures };
  const failed = failedChecksAfterPerson(entries, scan?.['last_user_at'], shape.windowStart || 0);
  const first = failed[0];
  if (first) {
    const latest = failed.reduce(
      (a, b) => ((evidenceAt(b) || 0) >= (evidenceAt(a) || 0) ? b : a),
      first,
    );
    return { kind: 'failed-check', failed: latest };
  }
  const verdict = (row: Criterion) => row.result === CONSISTENT && Boolean(row.restsOn);
  if (
    intent.some((row) => row.result === NOT_REACHED) &&
    intent.every((row) => verdict(row) || row.result === NOT_REACHED)
  ) {
    return { kind: 'not-reached' };
  }
  if (!intent.length || !intent.every(verdict)) return { kind: 'cant-tell' };
  return { kind: 'nothing-found' };
}

/* These are recorded event times, never the reading's time or a claim about when intent changed. A date and
   UTC keep older evidence unambiguous. */
export function recordedTime(at: unknown): string {
  const epoch = nextNumber(at);
  if (epoch === null || epoch <= 0) return 'time not recorded';
  const date = new Date(epoch * 1000);
  return Number.isFinite(date.getTime())
    ? `${date
        .toISOString()
        .replace(/\.\d{3}Z$/, '')
        .replace('T', ' ')} UTC`
    : 'time not recorded';
}

/* The same recorded time as the page draws it: the reader's local zone, as every other time on the page is
   (usability review, 2026-10-20: "01:15:00 UTC" beside a "09:15" the reader had just read). The date stays,
   so older evidence is still unambiguous. */
export function localRecordedTime(at: unknown): string {
  const epoch = nextNumber(at);
  if (epoch === null || epoch <= 0) return 'time not recorded';
  const date = new Date(epoch * 1000);
  if (!Number.isFinite(date.getTime())) return 'time not recorded';
  const two = (n: number) => String(n).padStart(2, '0');
  return `${String(date.getFullYear())}-${two(date.getMonth() + 1)}-${two(date.getDate())} ${two(date.getHours())}:${two(date.getMinutes())}:${two(date.getSeconds())}`;
}

export interface WorkGroup {
  readonly folder: string;
  readonly files: number;
  readonly references: string;
}

export interface ResultWork {
  readonly groups: readonly WorkGroup[];
  /** Written files the scan counted and did not list, or 0. */
  readonly more: number;
  /** The scan's total for this window is unavailable or smaller than what is listed. */
  readonly unavailable: boolean;
}

/* Where the work went: the written paths in this analysis window, grouped by folder without a model. A path
   with no folder is the working directory. The listing cannot count its own omissions; the scan supplies a
   distinct-path count for the same cutoff. A saved result keeps that cutoff even when the current intent
   window moves. */
export function resultWork(
  entries: readonly WorkEntry[],
  numbers: Numbers,
  scan: Row | null | undefined,
  resultWindow: number | null,
): ResultWork | null {
  const writes = entries.filter(
    (entry) =>
      entry &&
      entry.type === 'tool_report' &&
      entry.subject === 'write' &&
      (nextNumber(entry.at) ?? 0) > 0 &&
      (resultWindow === null || (nextNumber(entry.at) ?? 0) >= resultWindow),
  );
  const written = scan?.['window_written_paths'];
  const counted =
    scan !== null &&
    scan !== undefined &&
    nextNumber(scan['window_start']) === resultWindow &&
    Number.isSafeInteger(written) &&
    (written as number) >= 0
      ? (written as number)
      : null;
  if (!writes.length && !counted) return null;
  const groups = new Map<string, WorkEntry[]>();
  for (const entry of writes) {
    const path = String(entry.summary || '');
    const cut = path.lastIndexOf('/');
    const folder = cut > 0 ? path.slice(0, cut) : '';
    const held = groups.get(folder);
    if (held) held.push(entry);
    else groups.set(folder, [entry]);
  }
  const ordered = [...groups].sort(
    (a, b) => b[1].length - a[1].length || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0),
  );
  const listed = ordered.map(([folder, rows]): WorkGroup => {
    const numbered = rows
      .filter((entry) => numbers.has(String(entry.id || '')))
      .map((entry) => `#${String(numbers.get(String(entry.id || '')))}`);
    const unnumbered = rows.length - numbered.length;
    const references = [
      ...numbered,
      ...(unnumbered ? [`${String(unnumbered)} not numbered in the current view`] : []),
    ];
    return { folder, files: rows.length, references: references.join(', ') };
  });
  const more = counted !== null && counted >= writes.length ? counted - writes.length : 0;
  return {
    groups: listed,
    more,
    unavailable: !more && (counted === null || counted < writes.length),
  };
}

export interface Stale {
  readonly kind: 'intent' | 'work';
  readonly head: string;
  /** The revision sentence, only where the words changed. */
  readonly superseded: string;
  /** When the reader's first message after the reading was sent, where one was. */
  readonly before: number | null;
}

/* The two stale states of item 6, from the revision the reading read and the newest entry it saw
   (`evidence_through`). The words changing says why with the revision sentence the raises use; new work is
   any entry after the reading's newest. A reading stored with no such time counts from when it read instead,
   so an older row still owns up to work that landed after it. */
export function resultStale(
  shape: Shape,
  raw: Row | null | undefined,
  annotation: Annotation | null | undefined,
  entries: readonly WorkEntry[],
): Stale | null {
  const current = nextNumber(annotation?.['revision']);
  const superseded = revisionSuperseded(
    'This reading',
    shape.revisionRead,
    current,
    nextNumber(raw?.['read_at']),
    nextNumber(annotation?.['at']),
  );
  const evidence = nextNumber(raw?.['evidence_through']);
  const through = evidence !== null ? evidence : nextNumber(raw?.['read_at']);
  const newer =
    !superseded &&
    through !== null &&
    entries.some((entry) => (nextNumber(entry?.at) || 0) > through);
  if (!superseded && !newer) return null;
  const readAt = nextNumber(raw?.['read_at']);
  const after =
    !superseded && readAt !== null
      ? entries
          .filter((entry) => personAuthored(entry))
          .find((entry) => (nextNumber(entry.at) || 0) > readAt)
      : null;
  const head = superseded
    ? 'Your intent changed after this analysis.'
    : after
      ? `Read before your message at ${clock(Number(after.at))}. New work since this analysis.`
      : 'New work since this analysis.';
  return {
    kind: superseded ? 'intent' : 'work',
    head,
    superseded,
    before: after ? nextNumber(after.at) : null,
  };
}

/* What arrived since a reading read, counted from the entries and never authored. */
export function arrivedLine(
  annotation: Annotation | null | undefined,
  entries: readonly WorkEntry[],
): string {
  const assessment = annotation?.['assessment'];
  const at = nextNumber(
    assessment && typeof assessment === 'object' ? (assessment as Row)['read_at'] : null,
  );
  if (!(at !== null && at > 0)) return '';
  const arrived = entries.filter((entry) => (evidenceAt(entry) || 0) > at);
  const checks = arrived.filter(
    (entry) => entry.type === 'tool_report' && entry.subject === 'check',
  ).length;
  const writes = arrived.filter(
    (entry) => entry.type === 'tool_report' && entry.subject === 'write',
  ).length;
  const messages = arrived.filter((entry) =>
    ['user_message', 'agent_message'].includes(entry.type),
  ).length;
  const parts = (
    [
      [checks, 'check'],
      [writes, 'file write'],
      [messages, 'message'],
    ] as const
  )
    .filter(([count]) => count > 0)
    .map(([count, label]) => `${String(count)} ${label}${count === 1 ? '' : 's'}`);
  return parts.length ? `${parts.join(', ')} arrived since this analysis.` : '';
}

/* How far the message tail reached, said as clauses. Coverage that was not recorded says so rather than
   reading as complete. */
export function coverageLimits(shape: Shape): string {
  const measured = shape.coverage;
  const clauses: string[] = [];
  if (!measured || measured.tail_truncated === null) {
    clauses.push('Coverage was not recorded for this reading.');
  } else if (windowPartial(shape)) {
    const start = measured.tail_start ?? 0;
    clauses.push(
      `Message tail starts ${clock(start)}; about ${String(Math.max(1, Math.ceil((start - (shape.windowStart ?? 0)) / 60)))} min at the start of the window were outside it. The check listing can include older work.`,
    );
  } else if (measured.tail_truncated && measured.tail_start === null) {
    clauses.push('The message tail was truncated; its start time was not recorded.');
  }
  if (measured?.unlisted) {
    clauses.push(
      `${String(measured.unlisted)} ${measured.unlisted === 1 ? 'pass or write in the window was' : 'passes or writes in the window were'} not listed.`,
    );
  }
  if (measured?.unread_checks) {
    clauses.push(
      `${String(measured.unread_checks)} ${measured.unread_checks === 1 ? 'check' : 'checks'} had no room in the reading.`,
    );
  }
  return clauses.join(' ');
}

/* A reading's cutoff already says how many other commands ran beside the entries it read, so this speaks only
   where the count was never recorded: a reading stored before it was measured, or one whose session had no scan.
   Said apart from `coverageLimits`, which the retired page's own sentence is held to. */
export function commandCountNote(shape: Shape): string {
  return shape.coverage && Object.hasOwn(shape.coverage, 'other_commands')
    ? ''
    : 'How many other commands ran beside the entries read was not recorded for this reading.';
}

/* What the analysis did with an adopted prompt. Said under What the analysis read rather than beside the
   answer (usability review, 2026-10-20): it is about the reading's input, and above the departures it stood
   between the reader and the verdict. */
export function goalSourceLine(shape: Shape, statedGoal = false): string {
  const measured = shape.coverage;
  if (measured && ['excerpt', 'unroomed'].includes(measured.goal_source)) {
    return 'The adopted source could not be read whole; this reading used the saved excerpt. Put the instruction you meant in the goal box, then analyze again.';
  }
  /* A /goal has no source prompt to have found, so the "found" sentence does not apply to it; one that was
     cut is still said above, from the producer's coverage. */
  if (statedGoal) return '';
  if (measured && measured.goal_source === 'whole') {
    return 'The adopted source was found. Analyze reads at most the first 1,000 characters of any prompt.';
  }
  return '';
}

/* The retired page's one coverage sentence, which the differential test is held to: the limits, then the
   goal source. The page draws the two halves in different places. */
export function coverageLine(shape: Shape): string {
  return [coverageLimits(shape), goalSourceLine(shape)].filter(Boolean).join(' ');
}

/* A command's kind, in words that never say it passed: it exited, and Compass does not know what it checks. A
   tier 2 CI read says what the tool reported, as a check does. */
function commandKind(entry: WorkEntry): string {
  if (entry.subject === 'ci_command') return `${entry.result || 'Recorded'} CI check`;
  return entry.result === 'passed'
    ? 'Command that exited 0'
    : entry.result === 'failed'
      ? 'Command that exited non-zero'
      : 'Command, status not recorded';
}

/* Whether an entry is one of the agent's own words, for the evidence rows' kind. */
export function entryKind(entry: WorkEntry): string {
  return entry.subject === 'command' || entry.subject === 'ci_command'
    ? commandKind(entry)
    : entry.subject === 'check'
      ? `${entry.result || 'Recorded'} check`
      : entry.subject === 'write'
        ? 'File write'
        : entry.subject === 'pr'
          ? 'Pull request created'
          : entry.subject === 'skill'
            ? 'Skill used'
            : agentMessage(entry)
              ? 'Agent message'
              : String(entry.type || 'Recorded entry');
}

/* What a cited entry is, in Compass's own words, beside its number on a finding: never a model's account of
   it. A raw record type is not a reader's word, so anything unnamed here is a recorded entry. */
export function citedKind(entry: WorkEntry): string {
  if (entry.subject === 'command' || entry.subject === 'ci_command') return commandKind(entry);
  if (entry.subject === 'check') return `${entry.result || 'Recorded'} check`;
  if (entry.subject === 'write') return 'File write';
  if (entry.subject === 'pr') return 'Pull request created';
  if (entry.subject === 'skill') return 'Skill used';
  if (agentMessage(entry)) return 'Agent message';
  if (personAuthored(entry)) return 'Your message';
  return 'Recorded entry';
}

/* A cited entry's own words as What shows them: attributed and quoted, so an agent's "Done" reads as the
   agent's and never as the result's (usability review, 2026-10-20: "#5 Agent message" sent the reader into
   Evidence for the line the departure is about). Plain text, one line, bounded. */
const QUOTE_MAX = 200;

/* A check glyph in the agent's words would draw a check mark inside the result, the one shape kept off every
   result; it is said in words instead. */
const CHECK_GLYPHS = /[\u221a\u2611\u2705\u2713\u2714\u{10102}\u{1f5f8}\u{1f5f9}\u{1fbb1}]/gu;

function bounded(text: string, max: number = QUOTE_MAX): string {
  const flat = text.replace(CHECK_GLYPHS, '[check mark]').replace(/\s+/g, ' ').trim();
  // Counted in code points, so an emoji at the cut is kept whole rather than left as a lone surrogate.
  const points = Array.from(flat);
  if (points.length <= max) return flat;
  const cut = points.slice(0, max).join('');
  /* At the last space, wherever it falls: a cut at the limit left "…and noth" in a departure's What (walk
     record, 2026-10-21). A quote of one unbroken word, a URL, is cut where it stands, since there is no
     whole word shorter than it to end on. */
  const space = cut.lastIndexOf(' ');
  if (space > 0) return `${cut.slice(0, space).trimEnd()}…`;
  /* An unbroken path or URL is cut after its last "/" rather than in the middle of a name, unless that would
     keep less than a third of it. */
  const slash = cut.lastIndexOf('/');
  return `${slash >= max / 3 ? cut.slice(0, slash + 1) : cut}…`;
}

/* A written path longer than the title allows keeps its end, which is the name that tells two files apart, and
   gives up the directories in front of it. */
function pathTail(text: string, max: number): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  if (Array.from(flat).length <= max || flat.includes(' ')) return bounded(flat, max);
  const cut = flat.indexOf('/', flat.length - (max - 2));
  const names = cut >= 0 ? flat.slice(cut) : flat.slice(-(max - 2));
  return `…${names.startsWith('/') ? names : `/${names}`}`;
}

/* A departure's title, from what the cited entry is and the constraint it departs from, never from the
   constraint's own sentence: the goal's whole sentence made every title the same. No model writes it: the stored
   reading keeps a `detail` and no headline, so the title says only what the record itself shows, a write, a
   failed check or the agent's own message, with the entry's time so two departures on two messages or two
   checks read as two. A write or a check outranks a message, which only reports on one. The constraint's name
   follows where it is given, so one entry cited under two constraints still reads as two cards. Empty where no
   cited entry is held, and the card keeps the constraint's own words then. */
const TITLE_WORDS = 60;
export function titledEntry(entries: readonly WorkEntry[]): WorkEntry | null {
  return (
    entries.find((entry) => entry.subject === 'write' || entry.subject === 'check') ??
    entries.find(agentMessage) ??
    entries[0] ??
    null
  );
}

/* A constraint as the card's label names it, in the middle of a sentence. */
function constraintPhrase(name: string): string {
  if (name === 'Goal' || name === 'Expected outcome') return `the ${name.toLowerCase()}`;
  return name.charAt(0).toLowerCase() + name.slice(1);
}

export function departureTitle(entries: readonly WorkEntry[], constraint = ''): string {
  const entry = titledEntry(entries);
  if (!entry) return '';
  const seen = nextNumber(entry.at);
  const at = seen !== null && seen > 0 ? ` at ${clock(seen)}` : '';
  const from = constraint ? constraintPhrase(constraint) : 'this';
  if (entry.subject === 'write') {
    const path = pathTail(String(entry.summary || ''), TITLE_WORDS);
    return `${path ? `It changed ${path}` : 'It changed files'}${constraint ? ` against ${from}` : ''}`;
  }
  if (entry.subject === 'check') {
    return `${entry.result === 'failed' ? 'A check failed' : 'A check ran'}${at}${constraint ? ` against ${from}` : ''}`;
  }
  if (agentMessage(entry)) return `What the agent said${at} departs from ${from}`;
  return personAuthored(entry)
    ? `Your own words${at} depart from ${from}`
    : `Something in the record${at} departs from ${from}`;
}

/* A departure's What, one plain sentence about the same entry the title names: when, who and what, ending in
   one stop. The agent's own words stay quoted and attributed, so a result never says for the agent that it
   did the work. */
export function departureWhat(entries: readonly WorkEntry[]): string {
  const entry = titledEntry(entries);
  if (!entry) return '';
  const at = nextNumber(entry.at);
  const when = at !== null && at > 0 ? `At ${clock(at)} ` : 'At a time not recorded ';
  const words = bounded(String(entry.summary || ''));
  const stop = (text: string): string => (/[.!?…”]$/.test(text) ? text : `${text}.`);
  if (entry.subject === 'write') {
    return `${when}the agent changed ${words ? stop(words) : 'files.'}`;
  }
  if (entry.subject === 'check') {
    const failed = entry.result === 'failed';
    return `${when}a ${failed ? 'check failed' : 'check ran'}${words ? `: ${stop(words)}` : '.'}`;
  }
  if (agentMessage(entry))
    return `${when}the agent said ${words ? `“${words.replace(/\.+$/, '')}”` : 'something'}.`;
  if (personAuthored(entry) && words) return `${when}you said “${words.replace(/\.+$/, '')}”.`;
  return `${when}${citedKind(entry).toLowerCase()} was recorded.`;
}

export function citedLine(entry: WorkEntry): string {
  const words = bounded(String(entry.summary || ''));
  if (!words) return citedKind(entry);
  if (entry.subject === 'command' || entry.subject === 'ci_command') {
    return `${commandKind(entry)}: ${words}`;
  }
  if (entry.subject === 'check') {
    const result = String(entry.result || 'Recorded');
    return `${result.charAt(0).toUpperCase()}${result.slice(1)} check: ${words}`;
  }
  if (entry.subject === 'write') return `File write: ${words}`;
  if (entry.subject === 'pr') return `Pull request created: ${words}`;
  if (entry.subject === 'skill') return `Skill used: ${words}`;
  if (agentMessage(entry)) return `Agent said: “${words}”`;
  if (personAuthored(entry)) return `You said: “${words}”`;
  return citedKind(entry);
}

/* An entry as the verdict sentence names it, with its time. */
function entryPhrase(entry: WorkEntry): string {
  const kind =
    entry.subject === 'command' || entry.subject === 'ci_command'
      ? `a ${commandKind(entry).toLowerCase()}`
      : entry.subject === 'check'
        ? `a ${String(entry.result || 'recorded')} check`
        : entry.subject === 'write'
          ? 'a file write'
          : entry.subject === 'pr'
            ? 'a pull request created'
            : entry.subject === 'skill'
              ? 'a skill used'
              : agentMessage(entry)
                ? "the agent's message"
                : personAuthored(entry)
                  ? 'your message'
                  : 'an entry';
  const at = nextNumber(entry.at);
  return at !== null && at > 0 ? `${kind} at ${clock(at)}` : kind;
}

/* The Drift card's one plain answer, first under its heading: the level word, how many departures, and what
   and when each rests on, from the stored reading and the entries it cites alone. It never reassures where
   the reading could not settle: "Can't tell" and "Not reached" carry no level word. */
/* Whether the verdict sentence says the level word: only over an answer the reading could settle. The level
   view leaves its own word out where the sentence has it, so the card says each verdict once. */
export function verdictNamesLevel(answer: Answer): boolean {
  return (
    answer.kind !== 'cant-tell' && answer.kind !== 'not-reached' && answer.kind !== 'goal-unclear'
  );
}

/* The shape the Drift card's verdict sentence draws from, or null where it is not drawn: not over an unreadable
   reading or one the reader marked inaccurate. `DriftVerdict` and the level view both ask, so a level word is
   left out only where the sentence above it carries it. */
export function verdictShape(input: {
  readonly annotate: boolean;
  readonly shape: Shape | null;
  readonly raw: unknown;
  readonly annotation: Annotation | null | undefined;
}): Shape | null {
  const { annotate, shape, raw, annotation } = input;
  if (!annotate || !shape || shape.malformed || !raw || !annotation) return null;
  if (annotation['not_accurate'] === true) return null;
  if (!shape.criteria.length && !shape.departures.length) return null;
  return shape;
}

export function verdictLine({
  answer,
  level,
  heldBack = [],
  byId,
  midFlight,
}: {
  readonly answer: Answer;
  /** The analysis level's word, or empty where no level stands for this reading. */
  readonly level: string;
  /** Why no level is drawn over a reading that found nothing, one sentence each, from the level's own reasons. */
  readonly heldBack?: readonly string[];
  readonly byId: EntryIndex;
  /** A reading of a running session, which answers for the work so far. */
  readonly midFlight: boolean;
}): string {
  const said = (text: string) => (midFlight ? `So far: ${text}` : text);
  const levelled = (text: string) =>
    level ? `${level}${midFlight ? ' so far' : ''}: ${text}` : said(text);
  if (answer.kind === 'cant-tell') return said("Can't tell from what was read.");
  if (answer.kind === 'goal-unclear') return GOAL_UNCLEAR_VERDICT;
  if (answer.kind === 'not-reached') return said('Not reached at this stop.');
  if (answer.kind === 'nothing-found') {
    /* A level above None or low stands on a departure, so none is drawn here, and when the level is held
       back the same sentence says why: behind a "Why not None or low" disclosure it read as a missing
       answer. A held-back reason is a sentence of the page's own, lowercased into this one. */
    const goalOnly = heldBack.includes(GOAL_NOT_SHOWN);
    const why = heldBack
      .filter((line) => line !== GOAL_NOT_SHOWN)
      .map((line) => `${line.charAt(0).toLowerCase()}${line.slice(1)}`.replace(/\.$/, ''));
    if (goalOnly) {
      return levelled(
        why.length ? `${GOAL_ONLY_NO_LEVEL} Also: ${why.join('; ')}.` : GOAL_ONLY_NO_LEVEL,
      );
    }
    return levelled(
      why.length
        ? `Nothing found against what it read, but no level is drawn: ${why.join('; ')}.`
        : 'Nothing found against what it read.',
    );
  }
  if (answer.kind === 'failed-check') {
    const at = evidenceAt(answer.failed);
    return levelled(at !== null && at > 0 ? `A check failed at ${clock(at)}.` : 'A check failed.');
  }
  const count = `${String(answer.count)} departure${answer.count === 1 ? '' : 's'}`;
  const held = answer.departures.map((row) =>
    row.citedIds
      .map((id) => byId.get(String(id)))
      .filter((entry): entry is WorkEntry => Boolean(entry)),
  );
  const distinct = [
    ...new Map(held.flat().map((entry) => [String(entry.id || ''), entry])).values(),
  ];
  let where = '';
  const [first, second] = distinct;
  if (first && distinct.length === 1) {
    const all = answer.count === 1 ? '' : answer.count === 2 ? 'both ' : 'all ';
    where = held.every((rows) => rows.length)
      ? `, ${all}at ${entryPhrase(first)}`
      : `, at ${entryPhrase(first)}`;
  } else if (first && second && distinct.length === 2) {
    where = `, at ${entryPhrase(first)} and ${entryPhrase(second)}`;
  } else if (distinct.length > 2) {
    const times = distinct
      .map((entry) => nextNumber(entry.at))
      .filter((at): at is number => at !== null && at > 0);
    const span =
      times.length === distinct.length
        ? ` from ${clock(Math.min(...times))} to ${clock(Math.max(...times))}`
        : '';
    where = `, citing ${String(distinct.length)} entries${span}`;
  }
  return levelled(`${count}${where}.`);
}

/* How much of a session a reading may cover and still be called early. A judgement, not a measurement: it is
   the span in which a session has usually not yet run a check, which is what an empty verdict then waits on. */
const EARLY_SECONDS = 600;

export const LIVE_HIDDEN =
  'The live estimate is not drawn while this reading stands: it reads checks and file paths, never your intent.';

/* Said under an empty verdict when the reading covers only the first minutes of a session, so three lines of
   "Can't tell" read as "too soon" and not as a finding. Only where the page can show it is early: the answer
   is the empty one over an outcome line, the session was not finished, the record was read from its start, and
   the span from its first entry to the end of what the reading read is inside the window. Nothing otherwise,
   because a start the page cannot see would make "early" a default. */
export function earlyLine(
  answer: Answer,
  shape: Shape,
  raw: unknown,
  entries: readonly WorkEntry[],
): string {
  if (
    answer.kind !== 'cant-tell' ||
    shape.scope === 'final' ||
    shape.coverage?.tail_truncated !== false ||
    !shape.criteria.some((row) => isOutcomeLine(row.key))
  ) {
    return '';
  }
  const through = nextNumber((raw as Row | null)?.['evidence_through']);
  const times = entries
    .map((entry) => nextNumber(entry.at))
    .filter((at): at is number => at !== null && at > 0 && through !== null && at <= through);
  const first = Math.min(...times);
  if (
    through === null ||
    !times.length ||
    through - first <= 0 ||
    through - first >= EARLY_SECONDS
  ) {
    return '';
  }
  return `Early: this reading covers only the first ${fmtDur(through - first)} of the session. Read again once it has run its checks.`;
}

/* The model a stored reading names, from the stamp the server composes as "<model> · read at HH:MM". Only
   that shape is split; anything else ("unasked check at HH:MM") names no model rather than guessing. */
export function stampModel(stamp: string): string {
  const found = /^(.+?) · read at \d\d:\d\d$/.exec(stamp.trim());
  return found?.[1]?.trim() ?? '';
}

/* The Drift card's header line for a stored reading. "Last run", because "Analysis at 22:27" read as a time
   inside the session (2026-10-15 feedback, item 5); the time is `read_at`'s, never the stamp's text. */
export function lastRunLine(stamp: string, readAt: number | null): string {
  if (readAt === null || readAt <= 0) return '';
  return [stampModel(stamp), `Analysis last run ${clock(readAt)}`].filter(Boolean).join(' · ');
}

/* The constraint a finding is about, as a card's label says it. An outcome line is numbered only where more
   than one was read, as What the analysis read numbers them. */
export function constraintName(key: string, outcomes: number): string {
  if (key === 'goal') return 'Goal';
  if (key === CLAIMS) return 'What the agent claimed';
  const n = key === 'output' ? '1' : key.slice(5);
  return outcomes > 1 ? `Expected outcome ${n}` : 'Expected outcome';
}
