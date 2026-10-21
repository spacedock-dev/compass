import type {
  FocusedSummary,
  LargestRead,
  StoredSummary,
  SummaryBlock,
  SummaryBullet,
  SummaryGrant,
  SummaryJob,
  SummaryPlan,
} from '../api/summary';
import { clock } from '../observed';

/* What the What the session has done card says about a summary. Every reason token the server can publish is
   worded once, in `SUMMARY_REASONS`, as `drift/route.ts` words a reading's: a refusal, a stop and a stored
   state read the same wherever they reach the card. No sentence here says the requested work was delivered,
   and none presents a citation as proof of the sentence beside it
   ([the known limit](../../../docs/design-session-summary.md#the-known-limit-relevance-is-not-checked)). */

export const SUMMARY_WORKING_KEEP = 'You can keep working. The summary will appear here.';
export const SUMMARY_STARTING = 'Starting a summary of this finished session…';
/* The switch is one for the whole machine, so the sentence says so: it once said "this session", and a reader
   who turned summaries off on one session found them off on the next. */
export const SUMMARY_OFF =
  'Summaries are turned off for every session. Nothing is sent for a summary until you turn them on.';
/* The outline is named only where one is drawn: a Gemini session has none, and the sentence once pointed at an
   outline beside the line saying this session has no outline. */
export const SUMMARY_NOT_CLAUDE = (harness: string, outlined = true) =>
  `${harness} sessions cannot be summarized yet: Compass summarizes Claude Code sessions only.${outlined ? ' The outline above is Compass’s own grouping.' : ''}`;
export const SUMMARY_RELEVANCE =
  'Each line cites the entries it rests on. Compass checks that a cited entry exists and what kind it is, not that it supports the line.';
export const SUMMARY_FAILED_SEND =
  'Compass could not confirm the request. The next board shows whether it started.';
export const SUMMARY_CANCEL_FAILED = 'Compass could not confirm the cancel. Try again.';
export const SUMMARY_HOLDS = 'Holds evidence for a departure';
export const SUMMARY_INCOMPLETE =
  'This summary does not cover every part of the session. Summarize again reads it from the start.';
export const REPLY_CUT =
  'The model’s reply for this part was cut short, so only the phases it finished are shown.';
export const SUMMARY_LABEL = 'Summary: written by a model from this session’s record';

const plural = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`;

export interface ReasonContext {
  readonly grant: SummaryGrant | null;
  readonly harness: string;
  readonly largest: LargestRead | null;
}

/* Every reason the grant block, a refused press or a job can carry, in the reader's words. A token the table
   does not hold is said as an unknown stop rather than dropped. */
export const SUMMARY_REASONS: Readonly<Record<string, (context: ReasonContext) => string>> = {
  'summaries-off': () => SUMMARY_OFF,
  'model-calls-paused': () =>
    'Model calls are paused. Nothing is sent for a session summary until you resume.',
  'daily-cap': ({ grant }) =>
    `Summaries have used their ${String(grant?.limit || 'daily')} model calls for the last 24 hours${grant?.retryAt ? `. They can run again at ${clock(grant.retryAt)}` : ''}.`,
  'run-disabled': () =>
    'Compass was started with model calls turned off (--no-observer-model), so it makes no summary.',
  'store-unavailable': () =>
    'Compass could not read or write its summary store on this machine, so it makes no summary.',
  'session-running': () =>
    'This session is still running, so it is not summarized on open. Summarize reads the session so far.',
  'session-unavailable': () =>
    'Compass could not find this session on the board, so it cannot summarize it.',
  'in-flight': () => 'A summary of this session is already being made.',
  'no-summary': () => 'There is no saved summary to update. Summarize makes a new one.',
  'summary-changed': () =>
    'The saved summary changed while you pressed, so nothing was started. Compass reads it again.',
  'summary-exists': () => 'A summary of this session is already saved. Compass reads it again.',
  'source-unavailable': () =>
    'Compass could not read this session’s record, so it cannot summarize it. Nothing was sent.',
  'job-unrecorded': () => 'Compass could not start the summary. Nothing was sent or charged.',
  'no-thread': () => 'Compass could not start the summary. Nothing was sent or charged.',
  harness_not_supported: ({ harness }) => SUMMARY_NOT_CLAUDE(harness),
  invalid_bounds: () => 'Compass’s summary limits are set so that no summary can run.',
  planned_calls: (context) => tooLarge(context),
  planned_bytes: (context) => tooLarge(context),
  planned_seconds: (context) => tooLarge(context),
  output_bound_full: () =>
    'The saved summary is as large as a summary may be, so it cannot be updated. Summarize again makes a fresh one.',
  truncated: () => 'The session’s record got shorter after this summary was made.',
  replaced: () => 'The session’s record was replaced after this summary was made.',
  changed_earlier: () => 'An earlier entry of the session changed after this summary was made.',
  late_evidence: () =>
    'An entry arrived between parts the summary had already read, so no part read it.',
  span_mismatch: () => 'The entries under a part of the summary no longer match it.',
  unknown_change: () => 'The session’s record changed in a way Compass cannot place.',
  cancelled: () => 'You cancelled the summary.',
  deleted: () => 'The summary was deleted.',
  'grant-changed': () =>
    'Summaries were turned off while a part was being read, so that part was not kept.',
  'destination-changed': () =>
    'Where summaries are sent changed while this one ran, so it stopped.',
  stopping: () => 'The summary is stopping.',
  'model-unavailable': () =>
    'Compass could not reach your Claude Code (the claude command), so the summary stopped.',
  interrupted: () =>
    'Compass restarted while this summary ran, so it stopped. It does not resume on its own.',
  'job-failed': () => 'The summary stopped on an error.',
  'store-refused': () => 'The summary store refused this summary, so its newest part was not kept.',
  'store-unwritable': () =>
    'Compass could not write the summary store, so its newest part was not kept.',
  gaps: () => 'Some parts of the session could not be summarized; each says so in place.',
  bytes: () =>
    'The summary reached the largest size it may be saved at, so its newest parts were left out.',
  source_incomplete: () =>
    'Compass could not read the whole record, so the summary does not cover all of it.',
  no_entries: () => 'The part of the record Compass read holds no entries to summarize.',
  ceiling: () =>
    'The summary reached one of its limits on calls, bytes or time, so the parts after it were not read.',
  refused: () => 'A model call was refused, so the summary stopped.',
  stopped: () => 'The summary stopped before every part was read.',
  output_bound_too_small: () => 'Compass’s summary size limit is too small for any summary.',
};

function tooLarge({ largest }: ReasonContext): string {
  if (!largest || !largest.windows)
    return 'This session is larger than one summary may read. Nothing was sent.';
  const minutes = Math.max(1, Math.round(largest.seconds / 60));
  return `This session is larger than one summary may read: at most ${plural(largest.windows, 'part', 'parts')} of ${String(Math.round(largest.windowBytes / 1024))} KiB, ${plural(largest.calls, 'model call', 'model calls')} and ${plural(minutes, 'minute', 'minutes')}. Nothing was sent.`;
}

export function reasonSentence(reason: string, context: ReasonContext): string {
  const line = SUMMARY_REASONS[reason];
  return line ? line(context) : `The summary stopped (${reason}).`;
}

/* A part the summary could not summarize, said where it sits. Every gap points at the outline. */
export const GAP_LINES: Readonly<Record<string, string>> = {
  before_window:
    'The summary starts after this part: the session is longer than one summary reads. The outline covers it.',
  no_valid_reply: 'This part could not be summarized: the model’s reply could not be read.',
  no_output: 'This part could not be summarized: the model returned nothing, twice.',
  refused: 'This part could not be summarized: the model call was refused.',
  stopped: 'This part was not summarized: the summary stopped before it.',
  ceiling: 'This part was not summarized: the summary reached one of its limits first.',
  bytes: 'This part was left out: the summary reached the largest size it may be saved at.',
};
export const GAP_RUNNING = 'Not summarized yet: this part is still being read.';

export function gapSentence(block: SummaryBlock, running: boolean): string {
  if (running && block.gap === 'stopped') return GAP_RUNNING;
  return GAP_LINES[block.gap ?? ''] ?? 'This part could not be summarized.';
}

/* A string the server withheld, said in its place. */
export const WITHHELD_LINES: Readonly<Record<string, string>> = {
  completion_claim:
    'Withheld: this line said, in the summary’s own voice, that work was done or working.',
  no_citation: 'Withheld: this line cited no entry.',
  shape_fault: 'Withheld: this line was not in the shape a summary line must take.',
  too_long_cut: 'Withheld: this line was too long, and cutting it changed what it said.',
};
export const withheldSentence = (reason: string): string =>
  WITHHELD_LINES[reason] ?? 'Withheld: this line broke a rule a summary line must keep.';

/* A run of withheld lines in a phase is one muted line, as the owner ruled on 2026-10-20: eleven "Withheld: ..."
   lines in twelve made the sample's summary unreadable. Each reason is the table's above, said of one line or of
   several; the rule that withholds them is unchanged, and each line's own reason stays one press away. */
const HIDDEN_WHY: Readonly<Record<string, readonly [string, string]>> = {
  completion_claim: [
    'it said, in the summary’s own voice, that work was done or working',
    'they said, in the summary’s own voice, that work was done or working',
  ],
  no_citation: ['it cited no entry', 'they cited no entry'],
  shape_fault: [
    'it was not in the shape a summary line must take',
    'they were not in the shape a summary line must take',
  ],
  too_long_cut: [
    'it was too long, and cutting it changed what it said',
    'they were too long, and cutting them changed what they said',
  ],
};
/* A run whose lines were withheld for different reasons names each reason with its count, so the one line still
   says why: "each broke a rule a summary line must keep" once stood for a mix and said none of them. */
const HIDDEN_PART: Readonly<Record<string, readonly [string, string]>> = {
  completion_claim: [
    'said, in the summary’s own voice, that work was done or working',
    'said, in the summary’s own voice, that work was done or working',
  ],
  no_citation: ['cited no entry', 'cited no entry'],
  shape_fault: [
    'was not in the shape a summary line must take',
    'were not in the shape a summary line must take',
  ],
  too_long_cut: [
    'was too long, and cutting it changed what it said',
    'were too long, and cutting them changed what they said',
  ],
};
const HIDDEN_OTHER = [
  'broke a rule a summary line must keep',
  'broke a rule a summary line must keep',
] as const;
export function hiddenSentence(reasons: readonly string[], range: string): string {
  const n = reasons.length;
  const counts = new Map<string, number>();
  for (const reason of reasons) {
    const key = reason in HIDDEN_PART ? reason : '';
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const one = counts.size === 1 ? HIDDEN_WHY[[...counts.keys()][0] ?? ''] : undefined;
  const why =
    counts.size === 1
      ? one
        ? one[n === 1 ? 0 : 1]
        : n === 1
          ? 'it broke a rule a summary line must keep'
          : 'they broke a rule a summary line must keep'
      : [...counts]
          .map(([reason, count]) => {
            const part = HIDDEN_PART[reason] ?? HIDDEN_OTHER;
            return `${String(count)} ${part[count === 1 ? 0 : 1]}`;
          })
          .join('; ');
  return `${plural(n, 'line', 'lines')} hidden: ${why}.${range ? ` ${range}.` : ''}`;
}

/* A hidden run's open state is keyed by the entries its lines cite, not its place in the phase: a refreshed summary
   that gains or drops a line shifts every later run, and a positional key opened a different run's reasons. A run
   that cites nothing has nothing else to be known by, so it keeps its place. */
export const hiddenKey = (bullets: readonly SummaryBullet[], at: number): string => {
  const cites = [...new Set(bullets.flatMap((bullet) => bullet.cites))].sort();
  return cites.length ? `cites:${cites.join('+')}` : `at:${String(at)}`;
};

/* "Entries #50.1 to #55" over the entries a run of hidden lines cites, in the activity list's order; "Entry #44"
   for one; nothing where the page numbers none of them. */
export function hiddenRange(cites: readonly string[], labels: ReadonlyMap<string, string>): string {
  const known = [...new Set(cites.map((id) => labels.get(id)).filter((n): n is string => !!n))];
  const sorted = known
    .map((label) => ({ label, at: positionOf(label) }))
    .filter((row): row is { label: string; at: Position } => row.at !== null)
    .sort((a, b) => a.at[0] - b.at[0] || a.at[1] - b.at[1]);
  const first = sorted[0];
  const last = sorted.at(-1);
  if (!first || !last) return '';
  // An entry the page has not numbered is counted, so the range never reads as all the run cites.
  const more = new Set(cites.filter((id) => !labels.has(id))).size;
  const extra = more ? `, and ${String(more)} more` : '';
  return first.label === last.label
    ? `Entry #${first.label}${extra}`
    : `Entries #${first.label} to #${last.label}${extra}`;
}
/* A withheld title says why, as a withheld line does. It once said only that it was withheld, on most phases, and
   a reader could not tell that "Revenue chart tooltip date fix" had been held for the word "fix": a title has no
   speaker, so the backstop holds every completion word in it
   ([DEC-28](../../../docs/design-session-summary.md#amended-2026-10-19-owner-the-summarys-own-voice)). */
export const WITHHELD_TITLES: Readonly<Record<string, string>> = {
  completion_claim:
    'Phase title withheld: it used a word that can say work is done, such as “fix” or “done”, which a title may not.',
  shape_fault: 'Phase title withheld: it was not in the shape a phase title must take.',
  too_long_cut: 'Phase title withheld: it was too long, and cutting it changed what it said.',
};
export const withheldTitle = (reason: string): string =>
  WITHHELD_TITLES[reason] ?? 'Phase title withheld: it broke a rule a phase title must keep.';
export const LEDE_LAST = 'The opening summary is written once every part has been read.';

/* A `said` bullet reads as the agent's words: it opens with the label "Said:", as the card names a speaker. The
   producer's attribution rule asks the model to name the speaker ("The agent said ...", "The agent also said
   that ..."), and the label already names it, so the two are folded rather than stacked. Folded to a bare "Said"
   they read as a sentence with no subject ("Said the tooltip formats ..."), and an adverb the fold did not know
   left "Said: The agent also said ...". */
/* One table of speech verbs for every speaker test, so a line naming the agent or the person with any of them is
   read as that speaker's. Three tables once disagreed: "The agent reported ..." matched only the person's, and an
   `asked` line credited it to the person ("You said: The agent reported ..."). */
const SPEECH_VERB =
  '(?:asked|said|reported|confirmed|requested|wanted|told|noted|explained|mentioned|suggested|proposed|stated|replied|answered|claimed|wrote)';
const ADVERB = '(?:(?:also|then|later|again|first|finally|now)\\s+)?';
const AGENT_NOUN =
  "(?:the\\s+agent['’]s\\s+reply|the\\s+agent|agent|the\\s+assistant|assistant|claude)";
const AGENT_SPEECH = new RegExp(
  `^(?:${AGENT_NOUN}\\s+${ADVERB})?said\\b(?:\\s+that\\b)?[\\s:,]*`,
  'i',
);
export function saidText(words: string): string {
  const flat = words.trim();
  const named = AGENT_SPEECH.exec(flat);
  const rest = named ? flat.slice(named[0].length) : flat;
  return rest ? `Said: ${rest}` : words;
}
/* The agent named as the speaker, as opposed to a bare "Said", which an `asked` line uses for the person too. */
const AGENT_NAMED = new RegExp(`^${AGENT_NOUN}\\s+${ADVERB}${SPEECH_VERB}\\b`, 'i');
/* The person named as the speaker; "You <verb>" already reads in the card's own voice for the person. */
const PERSON_YOU = new RegExp(`^you\\s+${ADVERB}${SPEECH_VERB}\\b`, 'i');
const PERSON_NAMED = new RegExp(
  `^(?:you|the\\s+(?:person|user))\\s+${ADVERB}${SPEECH_VERB}\\b`,
  'i',
);
/* The person in the third person, folded into the card's "You"; a bare leading "Asked" or "Said" is folded too. */
const PERSON_THIRD = new RegExp(`^the\\s+(?:person|user)\\s+(${ADVERB}${SPEECH_VERB})\\b\\s*`, 'i');
const BARE_SPEECH = /^(asked|said)\b\s*/i;

/* An `asked` bullet reads as the person's words, as Full activity names them "You": the server admits it under
   the same speech licence as a `said` bullet, so text that opens with another verb ("Confirmed the parser is
   fixed") would otherwise read in the summary's own voice. */
export function askedText(words: string): string {
  const flat = words.trim();
  if (PERSON_YOU.test(flat)) return words;
  /* The line names the agent as its speaker. An `asked` bullet cites the person and the agent, so it may report
     either, and "You said: The agent said ..." credited the agent's words to the person. */
  if (AGENT_NAMED.test(flat)) return saidText(words);
  const named = PERSON_THIRD.exec(flat) ?? BARE_SPEECH.exec(flat);
  if (named) {
    const rest = flat.slice(named[0].length);
    const verb = (named[1] ?? '').toLowerCase().replace(/\s+/g, ' ').trim();
    return rest.startsWith(':')
      ? `You ${verb}: ${rest.slice(1).trimStart()}`.trimEnd()
      : `You ${verb} ${rest}`.trimEnd();
  }
  return `You said: ${words}`;
}

/* A failed check is told apart from plain work in words, not only in colour, as the outline words it. */
export const FAILED_MARK = 'Failed as the tool reported:';
/* The producer's own tool-report form already says it, so a line in that form takes the short mark: both
   together read "Failed as the tool reported: ... reported failed, as the tool reported." */
export const FAILED_SHORT = 'Failed:';
const TOOL_REPORT = /\breported\s+failed,\s*as\s+the\s+tool\s+reported\b/i;

/* What a bullet draws, and what its chips are named for: the speaker for words, the failure for a check. */
export function bulletWords(kind: string, words: string): string {
  const flat = words.trim();
  /* A `said` line cites only the agent's words, so a line naming the person is the agent's report of them: it
     keeps "Said:" and names the person as the card does, "you". */
  if (kind === 'said' && PERSON_NAMED.test(flat)) {
    const you = askedText(flat);
    return `Said: ${(you[0] ?? '').toLowerCase()}${you.slice(1)}`;
  }
  if (kind === 'said') return saidText(words);
  if (kind === 'asked') return askedText(words);
  /* Work cited with words: a line that names its speaker is said as that speaker's, not in the summary's voice. */
  if (kind === 'did' && AGENT_NAMED.test(flat)) return saidText(words);
  if (kind === 'did' && PERSON_NAMED.test(flat)) return askedText(words);
  if (kind === 'failed') return `${TOOL_REPORT.test(words) ? FAILED_SHORT : FAILED_MARK} ${words}`;
  return words;
}

/* Cited entries a chip cannot open: an earlier check or file has no entry of its own in Full activity. Said as a
   sentence that names why, where it once read "2 cited entries Full activity cannot open from here". */
export function unlinkedSentence(n: number): string {
  return n === 1
    ? '(1 cited entry is an earlier check or file that Full activity does not list, so it cannot be opened from here.)'
    : `(${String(n)} cited entries are earlier checks or files that Full activity does not list, so they cannot be opened from here.)`;
}

/* The card's right-hand header: the model, and when the summary was made. */
export function summaryStamp(summary: StoredSummary, running: boolean, model: string): string {
  const at = summary.madeAt ? clock(summary.madeAt) : '';
  const when = running
    ? [at ? `updated ${at}` : '', 'still running']
    : [at ? `summarized at ${at}` : ''];
  return [model, ...when].filter(Boolean).join(' · ');
}

/* What is out of date, and the one control that brings it up to date. */
export function outOfDateLine(
  summary: StoredSummary,
  context: ReasonContext,
): { readonly sentence: string; readonly action: 'update' | 'rerun' } | null {
  const report = summary.outOfDate;
  if (!report || report.kind === 'unchanged') return null;
  const at = summary.madeAt ? clock(summary.madeAt) : '';
  if (report.action === 'update') {
    const since = at ? ` since ${at}` : '';
    return {
      sentence: report.newEntries
        ? `${plural(report.newEntries, 'new entry', 'new entries')}${since}.`
        : `A check’s result arrived${since}.`,
      action: 'update',
    };
  }
  if (report.action === 'summarize_again') {
    const why = reasonSentence(report.reason ?? report.kind, context);
    const parts = report.affectedBlocks.map((index) => blockName(summary, index));
    const which = parts.length ? ` It affects ${parts.join(', ')}.` : '';
    return { sentence: `${why}${which}`, action: 'rerun' };
  }
  return null;
}

/* A block named for a reader: its first phase's title, or its place among the summary's parts. */
export function blockName(summary: StoredSummary, index: number): string {
  const block = summary.blocks[index];
  const title = block?.phases.find((phase) => 'text' in phase.title)?.title;
  return title && 'text' in title
    ? `the part “${title.text}”`
    : `part ${String(index + 1)} of ${String(summary.blocks.length)}`;
}

/* Why a stored summary's freshness could not be told. */
export const FRESHNESS_UNKNOWN =
  'Compass could not read the whole record now, so it cannot tell whether this summary is current.';

/* What the read behind a stored summary did not cover, said once above the phases. */
export function summaryNotes(summary: StoredSummary, startsAt: string): string[] {
  const notes: string[] = [];
  /* `starts_at` is set for any partial read, a stop at a time or byte limit included, so it is not the
     signal that the read began partway (docs/design-session-summary.md#open-questions). */
  const partway =
    (summary.coverage?.startOffset ?? 0) > 0 ||
    Boolean(summary.coverage?.unread.includes('before_window')) ||
    summary.blocks[0]?.gap === 'before_window';
  if (partway)
    notes.push(
      startsAt
        ? `This summary starts at ${startsAt}, not at the session’s first entry. The outline covers what comes before.`
        : 'This summary starts partway through the session, not at its first entry. The outline covers what comes before.',
    );
  if (summary.coverage?.agentReplies === 'not_read')
    notes.push('The agent’s replies were not read for this harness, so the summary has none.');
  return notes;
}

/* How large the read is, before a summary runs. With the server's plan it adds the parts and an upper bound on the
   minutes; a plan off a partial read gives a floor on the parts, and a plan the preflight would refuse, or one
   with no parts, is not quoted, so the card falls back to what the outline counted. */
export function readSize(
  entries: number | null,
  more: boolean,
  plan: SummaryPlan | null = null,
): string {
  if (entries === null) return '';
  const size = `${more ? 'More than' : 'About'} ${plural(entries, 'entry', 'entries')} to read`;
  if (!plan || plan.reason || plan.parts < 1)
    return `${size}. Compass plans the parts when the summary starts, and shows them here.`;
  const parts = `${plan.complete ? '' : 'at least '}${plural(plan.parts, 'part', 'parts')}`;
  return `${size} in ${parts}, up to ${plural(plan.minutes, 'minute', 'minutes')}.`;
}

export function progressLine(job: SummaryJob): string {
  if (job.state === 'stopping') return 'Stopping the summary…';
  if (!job.parts) return 'Planning the summary…';
  const part = Math.max(1, Math.min(job.part || 1, job.parts));
  return `Summarizing: part ${String(part)} of ${String(job.parts)}`;
}

export function partsKept(job: SummaryJob): string {
  if (!job.parts) return '';
  return job.finishedParts.length
    ? `It kept ${plural(job.finishedParts.length, 'part', 'parts')} of ${String(job.parts)}.`
    : 'It kept no part.';
}

/* Whether the page posts the one summary a finished session gets when it is opened: summaries on and not at
   their cap, a Claude Code session that has ended, no stored summary and no job of any kind
   ([answer 5](../../../docs/design-session-summary.md#the-ruling)). Each session is posted for at most once per
   page load, by the caller. */
export function autoStartDue(input: {
  readonly grant: SummaryGrant | null;
  readonly focused: FocusedSummary | null;
  readonly harness: string;
  readonly ended: boolean;
  readonly sample: boolean;
}): boolean {
  const { grant, focused } = input;
  return (
    !input.sample &&
    input.ended &&
    input.harness === 'claude' &&
    grant !== null &&
    grant.consent &&
    grant.reason === '' &&
    focused !== null &&
    focused.state === 'absent' &&
    focused.job === null
  );
}

/* A `#n` label sorts by its number, then its sub-number: `#2.1` lies between `#2` and `#3`. */
export type Position = readonly [number, number];

export function positionOf(label: string | undefined): Position | null {
  if (!label) return null;
  const match = /^(\d+)(?:\.(\d+))?$/.exec(label);
  return match ? [Number(match[1]), Number(match[2] ?? 0)] : null;
}

const before = (a: Position, b: Position) => a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);
const within = (p: Position, lo: Position, hi: Position) => !before(p, lo) && !before(hi, p);

export type Where = 'phase' | 'before' | 'after' | 'gap' | 'between' | 'unplaced';

export interface Placement {
  readonly where: Where;
  /** `block:phase` of each phase whose own cited span holds one of the departure's entries. */
  readonly phases: readonly string[];
}

export const PLACE_LINES: Readonly<Record<Exclude<Where, 'phase'>, string>> = {
  after: 'Its evidence comes after the last entry the summary covers.',
  before: 'Its evidence sits before where the summary starts, in the part the outline covers.',
  gap: 'Its evidence sits inside a part of the session the summary could not summarize.',
  between: 'Its evidence sits inside the span the summary covers, but in no phase of it.',
  unplaced: 'Compass cannot place its evidence against the summary.',
};

/* Where a departure's cited entries sit against a summary. A phase's span is the span its own bullets cite,
   because a phase publishes no bounds of its own; an entry between two phases is in neither. Positions come
   from the activity list's `#n`, so an entry the page has not numbered cannot be placed. */
export function placeDeparture(
  summary: StoredSummary,
  cited: readonly string[],
  numbers: ReadonlyMap<string, string>,
): Placement {
  const at = (id: string) => positionOf(numbers.get(id));
  const points = cited.map(at).filter((p): p is Position => p !== null);
  const phases: string[] = [];
  const spans = summary.blocks.map((block) => {
    const cites = block.phases.flatMap((phase) => phase.bullets.flatMap((row) => row.cites));
    const known = [block.first, ...cites, block.last]
      .map(at)
      .filter((p): p is Position => p !== null);
    const lo = known.reduce<Position | null>((a, p) => (a && !before(p, a) ? a : p), null);
    const hi = known.reduce<Position | null>((a, p) => (a && !before(a, p) ? a : p), null);
    return { block, lo, hi };
  });
  summary.blocks.forEach((block, b) => {
    block.phases.forEach((phase, p) => {
      const own = phase.bullets
        .flatMap((row) => row.cites)
        .map(at)
        .filter((q): q is Position => q !== null);
      if (!own.length) return;
      const lo = own.reduce((a, q) => (before(q, a) ? q : a));
      const hi = own.reduce((a, q) => (before(a, q) ? q : a));
      if (points.some((q) => within(q, lo, hi))) phases.push(`${String(b)}:${String(p)}`);
    });
  });
  if (phases.length) return { where: 'phase', phases };
  const first = summary.startsAt ? at(summary.startsAt) : null;
  const known = spans.filter((span) => span.lo && span.hi);
  const start = first ?? known.find((span) => span.block.gap !== 'before_window')?.lo ?? null;
  const end = known.length ? (known[known.length - 1]?.hi ?? null) : null;
  for (const q of points) {
    const gap = known.find(
      (span) => span.block.gap && within(q, span.lo as Position, span.hi as Position),
    );
    if (gap) return { where: gap.block.gap === 'before_window' ? 'before' : 'gap', phases };
  }
  /* A summary id the page has not numbered narrows every span read from the ids it has: a check or file id
     here is not the record's (docs/design-session-summary.md#open-questions). A point inside a narrowed span is
     inside the real one, so a phase or a gap still holds; before, after and between are said only when every
     id is numbered, or, for before, when the summary's own start is. */
  const whole = summary.blocks.every((block) =>
    [
      block.first,
      block.last,
      ...block.phases.flatMap((phase) => phase.bullets.flatMap((row) => row.cites)),
    ].every((id) => at(id) !== null),
  );
  for (const q of points) {
    if (start && before(q, start) && (whole || first)) return { where: 'before', phases };
    if (whole && end && before(end, q)) return { where: 'after', phases };
  }
  return { where: whole && points.length && start && end ? 'between' : 'unplaced', phases };
}

export const phaseId = (key: string, place: string) =>
  `summary-phase:${key}:${place.replace(':', '-')}`;

/* What the first press on Delete summary says before anything is deleted, and what the second leaves. Said in
   the page's own words and not the server's: the delete route answers a token, and the sentence claims nothing
   about another store. The wait it names is `CUE_TTL_MS`, the lifetime every armed control here shares. */
export const DELETE_LAPSE_SECONDS = 30;
export function deleteArmed(receiver: string): string {
  return `Press again to delete this summary from this machine. Nothing else is deleted. Summarize writes a new one, which sends the session to ${receiver} again. Nothing has been deleted yet, and this offer lapses in ${String(DELETE_LAPSE_SECONDS)} seconds.`;
}
export function summaryDeleted(time: string): string {
  return `Summary deleted at ${time}. Summarize writes a new one.`;
}
