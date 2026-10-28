import { nextNumber } from '../api/bootstrap';
import {
  conflictCandidates,
  entryNumbering,
  labelOrder,
  laterDirections,
  personAuthored,
  workAbsence,
  type WorkEntry,
  type WorkSource,
} from '../intent/work';
import type { Draft } from '../intent/derive';
import type { Annotation } from '../intent/annotation';
import {
  durationSince,
  endedAt,
  READING_TURN_STOP_HARNESSES,
  sessionStop,
  type Row,
} from '../observed';
import { PROMPT_SOURCES } from '../sessions/intent';
import { harnessLabels } from '../sessions/rows';
import { readingRoute } from './route';
import { WORK_AS_REPORTED, WORK_READ_FROM, WORK_HARNESSES } from './sentences';
import { readingAuthor, readingCopied } from './shape';

/* The session's activity, numbered. It sits right after CURRENT ACTIVITY in Full activity, under that
   section's own heading, and the numbers are the ones every "#<n>" on the page names: a
   reading cites an entry by this list's number, so a citation resolves against the same list the reader is
   looking at rather than against a second collection assembled from the same facts. `cited` is the set of
   fact ids the current reading's surviving departures rest on. The legacy cockpit's `nextCockpitWorkEvidence`
   is the oracle (`workList.differential.test.ts`). */

/* A fact's type as a word on the activity list. Closed, and a Map so a type named like an Object property
   cannot resolve to one: a type with no word here reads "Entry" rather than its raw token. */
const ENTRY_KIND = new Map([
  ['prepared_dispatch', 'Dispatch'],
  ['work_birth', 'Task started'],
  ['work_result', 'Task result'],
  ['result', 'Result'],
  ['gate_decision', 'Gate'],
  ['decision', 'Decision'],
  ['assignment', 'Assignment'],
  ['stage_transition', 'Stage'],
  ['agent_message', 'said'],
]);

/* A check's or a written path's own line under its summary: who, what, and what the tool reported. The result
   words say where the result came from, because "passed" from an error flag and "passed" from a summary line
   are different strengths of the same claim. */
const CHECK_RESULTS: Readonly<Record<string, string>> = {
  'failed flag': 'failed, as the tool reported',
  'passed flag': 'passed, as the tool reported',
  'failed summary': 'failed, per its summary line',
  'passed summary': 'passed, per its summary line',
  'failed marker': 'failed, per a failure line in its output',
};

/* A tier 3 command's result words: the exit status, and what Compass does not know. A command is any shell
   command that is neither a closed-list check nor a read, so a pass of one is never a pass of a test
   ([DEC-29](../../../docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)).
   `vocabulary.json` pins these to the producer's. */
export const COMMAND_RESULTS: Readonly<Record<string, string>> = {
  'passed flag': 'exited 0; Compass does not know what it checks',
  'failed flag': 'exited non-zero; Compass does not know what it checks',
};
export const COMMAND_NOT_RECORDED = 'ran, exit status not recorded';
const COMMAND_SHORT: Readonly<Record<'unrecorded' | 'passed' | 'failed', string>> = {
  unrecorded: 'No status',
  passed: 'Exited 0',
  failed: 'Exited non-zero',
};

/* Said beside a check that counted only because the reader listed its command for the project, so a pass
   is never read as a runner Compass knows. `vocabulary.json` pins it to the producer's (`CHECK_LISTED_BY_READER`). */
export const LISTING_WRITTEN =
  'The session wrote the file where you list checks, so none of the commands you listed counted as checks.';
export const CHECK_LISTED_BY_READER = 'counted because you listed it';

/* Why a rule withheld a check's result, in the reader's words, keyed by the closed token the collector publishes
   as `result_reason` (`CHECK_NOT_RECORDED_REASONS` in project_context.py). `vocabulary.json` pins the two together. */
export const CHECK_NOT_RECORDED_REASONS: Readonly<Record<string, string>> = {
  several_checks: 'several checks in one call',
  directory_not_placeable: 'directory not placeable',
  piped_beside_other_commands: 'output is piped beside other commands',
  printed_beside_other_commands: 'output is printed beside other commands',
  ci_poll_unbound: 'a CI poll of a pull request or repository this session is not bound to',
};

/* A check's or a file's own line in parts: who, what it was, and the notes about its result. The row draws the
   notes at the right edge, as a reader's flag is, and `toolReportLine` is the same words in one line. */
export type CheckResult = 'unrecorded' | 'passed' | 'failed';
export interface ActivityMark {
  readonly icon: CheckResult | 'command' | 'stale' | 'earlier-failed' | 'checks';
  readonly short: string;
  readonly words: string;
}
export interface CheckMarks {
  /** True for a tier 2 CI read or a tier 3 command, which a run of checks never folds. */
  readonly command?: true;
  readonly result: CheckResult;
  readonly stale: boolean;
  readonly earlierFailed: boolean;
  readonly marks: readonly ActivityMark[];
}
export const RESULT_MARKS: Readonly<Record<CheckResult, ActivityMark>> = {
  unrecorded: { icon: 'unrecorded', short: 'No result', words: 'Ran, result not recorded' },
  passed: { icon: 'passed', short: 'Passed', words: 'Passed, as the tool reported' },
  failed: { icon: 'failed', short: 'Failed', words: 'Failed, as the tool reported' },
};
export const STALE_MARK: ActivityMark = {
  icon: 'stale',
  short: '',
  words: 'Before the last change',
};
export const EARLIER_FAILED_MARK: ActivityMark = {
  icon: 'earlier-failed',
  short: '',
  words: 'An earlier run failed',
};
export const LISTED_BY_READER_MARK: ActivityMark = {
  icon: 'checks',
  short: 'Listed by you',
  words: 'Counted because you listed it',
};
export const LAST_TURN_MARK = { short: 'Last turn', words: 'from the last turn' };
export const MARK_LEGEND = [
  RESULT_MARKS.unrecorded,
  RESULT_MARKS.passed,
  RESULT_MARKS.failed,
  STALE_MARK,
  EARLIER_FAILED_MARK,
  LISTED_BY_READER_MARK,
];

/* A tier 2 CI read or a tier 3 command, drawn with the words the server composed for it: a CI read says
   what the tool reported, as a check does, and a command says its exit status and what Compass does not
   know. Neither folds into a run of checks, and neither reads as a test pass. */
function commandParts(entry: WorkEntry): {
  readonly actor: string;
  readonly type: string;
  readonly notes: readonly string[];
  readonly check: CheckMarks | null;
} {
  const ci = entry.subject === 'ci_command';
  const table = ci ? CHECK_RESULTS : COMMAND_RESULTS;
  const key = `${entry.result} ${entry.resultSource}`;
  const recorded = Object.hasOwn(table, key);
  const result: CheckResult =
    recorded && key.startsWith('failed')
      ? 'failed'
      : recorded && key.startsWith('passed')
        ? 'passed'
        : 'unrecorded';
  const phrase = recorded
    ? (table[key] as string)
    : ci
      ? 'ran, result not recorded'
      : COMMAND_NOT_RECORDED;
  /* A command whose status says nothing about the work is withdrawn for one of two reasons, and the producer says
     which: a CI poll of a pull request the session is not bound to names itself, and any other is a later `|| true`. */
  const reason = entry.cannotFail
    ? Object.hasOwn(CHECK_NOT_RECORDED_REASONS, entry.resultReason)
      ? (CHECK_NOT_RECORDED_REASONS[entry.resultReason] as string)
      : 'a later command forces the exit status to 0'
    : '';
  const notes = reason ? [phrase, reason] : [phrase];
  const words = notes.join(': ');
  if (entry.earlierFailed) notes.push('an earlier run failed');
  if (entry.beforeLastChange) notes.push('before the last change');
  const short = ci ? RESULT_MARKS[result].short : COMMAND_SHORT[result];
  return {
    actor: 'Agent',
    type: ci ? 'CI check' : 'command',
    notes,
    check: {
      command: true,
      result,
      stale: Boolean(entry.beforeLastChange),
      earlierFailed: Boolean(entry.earlierFailed),
      marks: [
        {
          ...RESULT_MARKS[result],
          /* A command that exited 0 draws its own glyph, never a check's tick: a pass of a command
             Compass does not know proves nothing the tick would say. A failure keeps the failed glyph. */
          icon: !ci && result === 'passed' ? 'command' : RESULT_MARKS[result].icon,
          short: reason ? `${short}: ${reason}` : short,
          words: words[0]?.toUpperCase() + words.slice(1),
        },
        ...(entry.earlierFailed ? [EARLIER_FAILED_MARK] : []),
        ...(entry.beforeLastChange ? [STALE_MARK] : []),
      ],
    },
  };
}

export function toolReportParts(entry: WorkEntry): {
  readonly actor: string;
  readonly type: string;
  readonly notes: readonly string[];
  readonly check: CheckMarks | null;
} {
  if (entry.subject === 'command' || entry.subject === 'ci_command') return commandParts(entry);
  if (entry.subject !== 'check')
    return {
      actor: 'Agent',
      type:
        entry.subject === 'pr'
          ? 'pull request created'
          : entry.subject === 'skill'
            ? 'skill used'
            : 'file written',
      notes: [],
      check: null,
    };
  const key = `${entry.result} ${entry.resultSource}`;
  const recorded = Object.hasOwn(CHECK_RESULTS, key);
  const result: CheckResult =
    recorded && key.startsWith('failed')
      ? 'failed'
      : recorded && key.startsWith('passed')
        ? 'passed'
        : 'unrecorded';
  const phrase = recorded ? (CHECK_RESULTS[key] as string) : 'ran, result not recorded';
  const reason =
    !recorded && Object.hasOwn(CHECK_NOT_RECORDED_REASONS, entry.resultReason)
      ? (CHECK_NOT_RECORDED_REASONS[entry.resultReason] as string)
      : '';
  const notes = reason ? [phrase, reason] : [phrase];
  const words = notes.join(': ');
  if (entry.earlierFailed) notes.push('an earlier run failed');
  if (entry.beforeLastChange) notes.push('before the last change');
  if (entry.listedByReader) notes.push(CHECK_LISTED_BY_READER);
  return {
    actor: 'Agent',
    type: 'check',
    notes,
    check: {
      result,
      stale: Boolean(entry.beforeLastChange),
      earlierFailed: Boolean(entry.earlierFailed),
      marks: [
        /* The reason is part of the row's own mark, so a reader sees why there is no result without opening it. */
        {
          ...RESULT_MARKS[result],
          short: reason ? `${RESULT_MARKS[result].short}: ${reason}` : RESULT_MARKS[result].short,
          words: words[0]?.toUpperCase() + words.slice(1),
        },
        ...(entry.earlierFailed ? [EARLIER_FAILED_MARK] : []),
        ...(entry.beforeLastChange ? [STALE_MARK] : []),
        ...(entry.listedByReader ? [LISTED_BY_READER_MARK] : []),
      ],
    },
  };
}

export function toolReportLine(entry: WorkEntry): string {
  const { actor, type, notes } = toolReportParts(entry);
  return [actor, type, ...notes].join(' · ');
}

function humanLabel(value: string): string {
  const words = String(value || 'work')
    .replace(/[-_]+/g, ' ')
    .trim();
  return words ? (words[0] ?? '').toUpperCase() + words.slice(1) : 'Work';
}

/* What the whole scan found, from the counts `claude_tool_reports` publishes beside the rows. Every figure is
   the full scan, never the listed rows: a dropped entry must not turn into "no check" or into a reassurance. A
   background launch is named, because a background run records no result and a sentence that said no check
   ran would be false. */
export function checkScan(scan: Row | null | undefined): string {
  if (!scan || typeof scan !== 'object') return '';
  const count = (n: number, one: string, many: string): string =>
    `${String(n)} ${n === 1 ? one : many}`;
  const runs = nextNumber(scan['check_runs']) || 0;
  const background = nextNumber(scan['background']) || 0;
  const written = nextNumber(scan['written_paths']) || 0;
  const other = nextNumber(scan['other_commands']) || 0;
  const more = nextNumber(scan['more']) || 0;
  const outside = nextNumber(scan['outside_paths']) || 0;
  const pulls = nextNumber(scan['pull_requests']) || 0;
  const skills = nextNumber(scan['skills_used']) || 0;
  /* The file where the reader lists checks was written by the session, so none of its entries counted. Said
     whatever else was found, because a reader who listed a command is owed the reason it read as a command. */
  const listing = scan['reader_checks_written'] === true ? ` ${LISTING_WRITTEN}` : '';
  if (!runs && !background && !written && !other && !outside && !pulls && !skills) {
    return `No check ran in the part of the transcript read.${listing}`;
  }
  /* The latest results, always, so a failure is never left for the listed rows alone to carry; the files are a
     sentence of their own, so they never read as a latest-run result. */
  const checks = runs
    ? `${count(runs, 'check run', 'check runs')} across ${count(nextNumber(scan['distinct_checks']) || 0, 'distinct check', 'distinct checks')}; latest runs: ${String(nextNumber(scan['failed']) || 0)} failed, ${String(nextNumber(scan['not_recorded']) || 0)} with no recorded result, ${String(nextNumber(scan['passed']) || 0)} passed`
    : 'no check in the foreground';
  const files: string[] = [];
  if (written) files.push(count(written, 'file written', 'files written'));
  if (outside)
    files.push(`${count(outside, 'file', 'files')} written outside the working directory`);
  /* Said apart from the files and the latest runs: neither is a check, and neither has a result to fail. */
  const done: string[] = [];
  if (pulls) done.push(count(pulls, 'pull request created', 'pull requests created'));
  if (skills) done.push(count(skills, 'skill used', 'skills used'));
  const counted: string[] = [];
  if (background) {
    counted.push(
      `${count(background, 'background launch', 'background launches')}, because a background run records no result`,
    );
  }
  if (other) counted.push(count(other, 'other shell command', 'other shell commands'));
  return (
    `From the part of the transcript read: ${checks}.` +
    (files.length ? ` ${files.join(', ').replace(/^./, (c) => c.toUpperCase())}.` : '') +
    (done.length ? ` ${done.join(', ').replace(/^./, (c) => c.toUpperCase())}.` : '') +
    (counted.length ? ` Counted and not listed: ${counted.join('; ')}.` : '') +
    (more
      ? ` Failures are listed first, and ${String(more)} more are counted and not listed.`
      : '') +
    listing
  );
}

/* The observed last turn of a session waiting at its prompt, inside the evidence window: from the reader's
   latest message at or before the stop, or the window start if later, up to the stop. Not from the window
   start to the save: that range is fixed when the words are saved, so the next turn made it name an older one.
   Null on every other session and where no message opens the turn, because a label nothing measured would be
   the board authoring a turn. */
export function lastTurn(
  session: Row,
  entries: readonly WorkEntry[],
): { readonly from: number; readonly to: number } | null {
  if (!READING_TURN_STOP_HARNESSES.includes(String(session['harness'] || ''))) return null;
  if (endedAt(session) !== null) return null;
  const found = sessionStop(session);
  const stop = found ? found.at : null;
  if (!(session['state'] === 'idle' && stop !== null && stop > 0)) return null;
  const opened = nextNumber(session['annotation_window_start']);
  const starts = entries
    .filter(personAuthored)
    .map((entry) => nextNumber(entry.at))
    .filter((at): at is number => at !== null && at > 0 && at <= stop);
  if (opened === null || !starts.length) return null;
  const from = Math.max(opened, ...starts);
  return from <= stop ? { from, to: stop } : null;
}

export function entryActor(entry: WorkEntry): string {
  const author = readingAuthor(entry);
  /* You pasted it, and Compass wrote it: the meta says which. */
  if (author === 'person' || readingCopied(entry)) return 'You';
  /* Compass's own paraphrase is never credited to the agent. */
  return author === 'derived' ? 'Compass’s summary' : 'Agent';
}

/* The clause for entries that are counted and not listed, naming the ones a departure cites, which are listed
   anyway with their time and no number. An untimed entry has no time to list it with. */
function unlistedClause(count: number, what: string, cited: number, timed = true): string {
  const are = count === 1 ? 'is' : 'are';
  const how = timed ? `with ${cited === 1 ? 'its' : 'their'} time and no number` : 'with no number';
  const except = !cited
    ? ''
    : `, except ${cited === 1 ? 'the one' : `the ${String(cited)}`} the analysis cites, listed ${how}`;
  return `${String(count)} ${what} ${are} counted and not listed${except}.`;
}

/* What the rows actually are, counted from the rows themselves. The block was headed WORK EVIDENCE, and on
   Claude and Codex every entry is a `user_message`, so a reader comparing their words against "work evidence"
   was reading their own sentences back on both sides of the comparison. The heading names the record rather
   than the work, and this line says what is in it. One pass and exclusive buckets, so the remainder cannot be
   reached by subtracting overlapping filters. */
export function workMix(entries: readonly WorkEntry[]): string {
  let directions = 0;
  let copied = 0;
  let derived = 0;
  let summaries = 0;
  let said = 0;
  let work = 0;
  for (const entry of entries) {
    if (personAuthored(entry)) directions += 1;
    else if (readingCopied(entry)) copied += 1;
    else if (entry.modelDerived) derived += 1;
    else if (String(entry.type || '') === 'observer_snapshot') summaries += 1;
    /* What the agent said is its account, not an observation of what it did. */ else if (
      String(entry.type || '') === 'agent_message'
    ) {
      said += 1;
    } else work += 1;
  }
  const parts = [`${String(entries.length)} ${entries.length === 1 ? 'entry' : 'entries'}`];
  if (directions)
    parts.push(`${String(directions)} ${directions === 1 ? 'direction' : 'directions'} you gave`);
  if (said) parts.push(`${String(said)} ${said === 1 ? 'message' : 'messages'} the agent wrote`);
  if (copied) parts.push(`${String(copied)} copied from Compass`);
  if (derived) parts.push(`${String(derived)} model-derived`);
  if (summaries) {
    parts.push(
      `${String(summaries)} derived ${summaries === 1 ? 'summary' : 'summaries'} of this session`,
    );
  }
  parts.push(`${String(work)} observed of what it did`);
  return `${parts.join(' · ')}.`;
}

export function evidenceOwn(payload: Row, harness: string, sent = true): string {
  const label = harnessLabels(payload).get(harness) || humanLabel(harness);
  if (harness === 'pi')
    return `${label} publishes demonstrated work results, and they are read here.`;
  if (harness === 'claude') {
    /* The route's own sentence says what a reading sends of them and to whom, or that it sends none, so the
       line under the checks and the disclosure beside the button cannot word it two ways. */
    const route = sent ? readingRoute(payload, { harness }) : null;
    const output = route?.['provider'] ? String(route['tool_output'] || '') : '';
    return (
      `${label} records the checks a session ran and the files it wrote, and they are listed here. A result is what the tool reported; Compass inspects no file, test or deliverable.` +
      (output ? ` ${output}` : '')
    );
  }
  /* "Compass reads those on Pi alone" stood here, and stopped being true when Claude Code's checks were read
     too. The panel's own harness limit is the level's, so this line says only what the record above is. */
  return `${label} publishes no demonstrated work results, so nothing above is an inspected file, test or deliverable.`;
}

export interface WorkRow {
  readonly entry: WorkEntry;
  readonly n: string | null;
  /** A check's or a file's own line, or the actor and the type's word. */
  readonly head:
    | {
        readonly report: string;
        readonly actor: string;
        readonly type: string;
        readonly notes: readonly string[];
        readonly check: CheckMarks | null;
      }
    | { readonly actor: string; readonly type: string };
  readonly flags: readonly ('later' | 'cited')[];
  readonly source: string;
  readonly at: string;
  readonly turn: boolean;
  readonly add: boolean;
}

export interface CheckRunModel {
  readonly kind: 'run';
  readonly rows: readonly WorkRow[];
  readonly counts: Readonly<Record<CheckResult, number>>;
  readonly first: WorkRow;
  readonly last: WorkRow;
  readonly label: string;
  readonly range: string;
  readonly at: string;
}
export type FoldedItem = { readonly kind: 'row'; readonly row: WorkRow } | CheckRunModel;

/* The lowest and highest number in a folded run. A check is labelled where it first ran and drawn where it
   last did, so the ends of the drawn run are not always its lowest and highest. */
function runRange(rows: readonly WorkRow[]): string {
  const labels = rows
    .map((row) => row.n)
    .filter((n): n is string => n !== null)
    .sort(labelOrder);
  return `#${String(labels[0])} to #${String(labels.at(-1))}`;
}

/* Cited and failed evidence stays reachable without a disclosure. Runs are formed in drawn order,
   never time-sorted a second time. docs/design-reader-state.md#the-inventory owns their oldest-id key. */
export function foldRuns(
  rows: readonly WorkRow[],
  revealed: ReadonlySet<string> = new Set(),
): FoldedItem[] {
  const items: FoldedItem[] = [];
  let pending: WorkRow[] = [];
  const flush = () => {
    const first = pending[0];
    const last = pending.at(-1);
    if (pending.length < 3 || !first || !last) {
      items.push(...pending.map((row): FoldedItem => ({ kind: 'row', row })));
    } else {
      const counts = { passed: 0, failed: 0, unrecorded: 0 };
      for (const row of pending) {
        if ('check' in row.head && row.head.check) counts[row.head.check.result] += 1;
      }
      items.push({
        kind: 'run',
        rows: pending,
        counts,
        first,
        last,
        label: `${String(pending.length)} checks`,
        range:
          first.n === null || last.n === null
            ? 'Entries not numbered in this view'
            : runRange(pending),
        at: first.at === last.at ? first.at : `${first.at.replace(/ ago$/, '')} to ${last.at}`,
      });
    }
    pending = [];
  };
  for (const row of rows) {
    const check = 'check' in row.head ? row.head.check : null;
    if (
      row.entry.type === 'tool_report' &&
      check &&
      !check.command &&
      check.result !== 'failed' &&
      !check.earlierFailed &&
      !row.flags.includes('cited') &&
      !revealed.has(row.entry.id)
    ) {
      pending.push(row);
    } else {
      flush();
      items.push({ kind: 'row', row });
    }
  }
  flush();
  return items;
}

export interface WorkList {
  readonly anchor: string;
  readonly unnumbered: string;
  readonly rows: readonly WorkRow[];
  /** Said where no row is drawn and the record is not merely unnumbered. */
  readonly absent: string;
  readonly mix: string;
  readonly unlisted: readonly string[];
  readonly checks: string;
  readonly bound: string;
  readonly reads: boolean;
  readonly limit: string;
  /** Numbers are the server's fixed ones, not a count of the entries loaded. */
  readonly ordinals: boolean;
}

export interface WorkListInput {
  readonly session: Row;
  readonly payload: Row;
  readonly source: WorkSource;
  readonly annotation: Annotation | null;
  readonly draft: Draft | null;
  readonly cited: ReadonlySet<string>;
  readonly revealed?: ReadonlySet<string>;
  readonly generated: number;
}

export function workList(input: WorkListInput): WorkList {
  const { session, payload, source, annotation, cited } = input;
  const numbering = entryNumbering(session, source, payload);
  const { all, numbers, earlier, untimed, unnumbered: noNumber, opened, ordinals } = numbering;
  const annotate = payload['annotate'] === true;
  const ann = annotate ? annotation : null;
  const later = new Set(laterDirections(ann, all, session, input.draft));
  /* Every unsettled later direction is drawn at its own number, as a cited entry is, so the "#<n>" the
     question before the press names is always a row on screen. One from before the window has no number and
     is drawn with its time, as a cited earlier entry is, and is not counted among the earlier entries left
     unlisted. A settled one takes the bound. */
  const open = new Set(conflictCandidates(ann, all, session, input.draft));
  const numbered = all.filter((entry) => numbers.has(entry));
  const isCited = (entry: WorkEntry): boolean => cited.has(entry.id);
  const isRevealed = (entry: WorkEntry): boolean => Boolean(input.revealed?.has(entry.id));
  /* An entry a fixed-number session published no number for (a workflow fact, say) is still in the window, so it
     is drawn, without a number and with its time, as a cited earlier entry is. */
  const unnumberedHere = new Set(noNumber);
  const entries = all.filter(
    (entry) =>
      numbers.has(entry) ||
      unnumberedHere.has(entry) ||
      isCited(entry) ||
      isRevealed(entry) ||
      open.has(entry),
  );
  const turnOf = lastTurn(session, all);
  const rows = entries.map((entry): WorkRow => {
    const stamp = nextNumber(entry.at);
    const n = numbers.get(entry);
    const copied = readingCopied(entry);
    return {
      entry,
      n: n ?? null,
      head:
        entry.type === 'tool_report'
          ? { report: toolReportLine(entry), ...toolReportParts(entry) }
          : {
              actor: entryActor(entry),
              type: copied
                ? 'Copied from Compass'
                : entry.type === 'user_message'
                  ? 'Prompt'
                  : (ENTRY_KIND.get(String(entry.type || '')) ?? 'Entry'),
            },
      /* Neutral tags: neither is a finding. "Cited" says a departure rests on the entry, and a later
         direction is never called drift. */
      flags: [
        ...(later.has(entry) ? (['later'] as const) : []),
        ...(isCited(entry) ? (['cited'] as const) : []),
      ],
      /* Out of view and still read out: the same source on every row was a full-width caption five times
         over. Only where `actor_claim` says something the source line does not. */
      source:
        (entry.source || 'Source not published') +
        (entry.actorClaim && !entry.source.includes(entry.actorClaim)
          ? ` · ${entry.actorClaim}`
          : ''),
      at: ((): string => {
        const age = durationSince(input.generated, entry.at);
        return age === null ? 'time not published' : `${age} ago`;
      })(),
      turn: Boolean(
        turnOf &&
          stamp !== null &&
          stamp >= turnOf.from &&
          stamp <= turnOf.to &&
          !personAuthored(entry),
      ),
      add: later.has(entry),
    };
  });
  /* Where the words' window opens, a message of the reader's should sit: the latest one at or before the save
     for typed words, the prompt itself for adopted ones. A window at the save time is typed words with no
     earlier message, and nothing is expected there. */
  const promptSource = Boolean(
    annotation && PROMPT_SOURCES.includes(String(annotation['goal_source'])),
  );
  const saved = nextNumber(annotation?.['at']);
  const expected = opened !== null && (promptSource || (saved !== null && opened < saved));
  // Fixed numbers do not start at the window, so there is no "#1" for the window's opening to explain.
  const anchor =
    ann &&
    expected &&
    !ordinals &&
    numbers.size &&
    !all.some((entry) => nextNumber(entry.at) === opened)
      ? earlier.length
        ? 'No entry in the record read here sits where your intent’s window opens, so #1 is the first entry after that point.'
        : 'The record read here no longer reaches back to where your intent’s window opens, so #1 is the first entry it holds after that point.'
      : '';
  const unlisted: string[] = [];
  const unasked = earlier.filter((entry) => !open.has(entry));
  if (unasked.length) {
    unlisted.push(
      unlistedClause(
        unasked.length,
        `earlier ${unasked.length === 1 ? 'entry' : 'entries'}, from before your intent’s window opened,`,
        unasked.filter((entry) => isCited(entry) || isRevealed(entry)).length,
      ),
    );
  }
  if (untimed.length) {
    unlisted.push(
      unlistedClause(
        untimed.length,
        `${untimed.length === 1 ? 'entry' : 'entries'} with no published time`,
        untimed.filter((entry) => isCited(entry) || isRevealed(entry)).length,
        false,
      ),
    );
  }
  // Every timed entry in the loaded window is drawn; there is no hidden readability slice.
  const bound = '';
  /* Nothing numbered while the record holds entries is a fact about the window, not an empty record: "No entry
     names this session" beside a count of the entries it holds was false. */
  const unnumbered =
    !numbers.size && (earlier.length || untimed.length)
      ? earlier.length
        ? 'No entry in the record read here is from after your intent’s window opened, so none is numbered.'
        : 'No entry in the record read here has a published time, so none is numbered.'
      : '';
  const harness = String(session['harness'] || '');
  const reads = WORK_HARNESSES.includes(harness);
  const limit = reads
    ? `${WORK_READ_FROM} ${evidenceOwn(payload, harness, false)}`
    : `${WORK_READ_FROM} ${evidenceOwn(payload, harness)}`;
  return {
    anchor,
    unnumbered,
    rows,
    absent: rows.length || unnumbered ? '' : workAbsence(source),
    mix: numbered.length ? workMix(numbered) : '',
    unlisted,
    checks: source.scan ? checkScan(source.scan) : '',
    bound,
    reads,
    limit,
    ordinals,
  };
}

/* What the list draws, apart from what the model says, so the comparison with the recorded answers still reads the
   model's own words and order (docs/design-frontend-migration.md#activity-list-order). */

/* The rows in number order: a check or file sits under the message whose number it carries. It was drawn where it
   last ran, so #59.1 stood between #67 and #66. A row with no number keeps its place. */
export function rowsByNumber(rows: readonly WorkRow[]): WorkRow[] {
  const numbered = rows
    .filter((row) => row.n !== null)
    .sort((a, b) => labelOrder(String(a.n), String(b.n)));
  let next = 0;
  return rows.map((row) => (row.n === null ? row : (numbered[next++] as WorkRow)));
}

/* Newest first by message: a message and the checks and files numbered under it (#59, #59.1) are one group, and
   the groups are reversed, so a message's checks stay under it. Reversing every row drew #59.1 above #59. A row with
   no number is a group of its own. */
export function newestFirst(rows: readonly WorkRow[]): WorkRow[] {
  const groups: WorkRow[][] = [];
  let major: string | null = null;
  for (const row of rows) {
    const next = row.n === null ? null : (String(row.n).split('.')[0] ?? null);
    const last = groups.at(-1);
    if (last && next !== null && next === major) last.push(row);
    else groups.push([row]);
    major = next;
  }
  return groups.reverse().flat();
}

/* The last turn said once, on its newest drawn row, with the numbers it spans: on every row it was the same tag
   down the whole list. Chosen from the rows drawn outside a folded run, because the newest row of a turn is often
   a passing check that folds, and a label inside a closed run is a label nobody sees. When every row of the turn
   folds, the run holding its newest row carries the label on its trigger (`run`). */
export function lastTurnLead(
  rows: readonly WorkRow[],
  folded?: readonly FoldedItem[],
): {
  readonly id: string;
  readonly range: string;
  readonly run: string | null;
} | null {
  const turn = rows.filter((row) => row.turn);
  const newest = turn.at(-1);
  if (!newest) return null;
  const labels = turn
    .map((row) => row.n)
    .filter((n): n is string => n !== null)
    .sort(labelOrder);
  const first = labels[0];
  const last = labels.at(-1);
  const range = first && last && first !== last ? `#${first} to #${last}` : '';
  if (!folded) return { id: newest.entry.id, range, run: null };
  const drawn = new Set(folded.flatMap((item) => (item.kind === 'row' ? [item.row.entry.id] : [])));
  const lead = turn.filter((row) => drawn.has(row.entry.id)).at(-1);
  if (lead) return { id: lead.entry.id, range, run: null };
  const run = folded.find(
    (item) => item.kind === 'run' && item.rows.some((row) => row.entry.id === newest.entry.id),
  );
  return { id: newest.entry.id, range, run: run?.kind === 'run' ? run.last.entry.id : null };
}

/* Markdown emphasis an agent wrote ("**High**") drawn as the words it marks. Only paired asterisks: a lone `*` is
   a glob and an underscore is part of a name. */
export function plainEmphasis(text: string): string {
  return text.replace(/\*\*(?=\S)([^*\n]*?\S)\*\*/g, '$1');
}

/* A row's words as drawn. Emphasis is unwrapped only in an agent's prose or a model's paraphrase of it: a check
   command, a file path and the person's own message are literal source text, where a pair of asterisks is a
   glob, and a recursive glob in a check command once lost both of its pairs. */
const LITERAL_TYPES = new Set(['tool_report', 'user_message']);
export function rowWords(entry: {
  readonly type: string;
  readonly summary: string;
  readonly modelDerived?: boolean;
}): string {
  const prose =
    !LITERAL_TYPES.has(entry.type) && (entry.type === 'agent_message' || entry.modelDerived);
  return prose ? plainEmphasis(entry.summary) : entry.summary;
}

export { WORK_AS_REPORTED };
