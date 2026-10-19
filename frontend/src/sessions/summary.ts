import type {
  FocusedSummary,
  LargestRead,
  StoredSummary,
  SummaryBlock,
  SummaryGrant,
  SummaryJob,
} from '../api/summary';
import { clock } from '../observed';

/* What the What the session has done card says about a summary. Every reason token the server can publish is
   worded once, in `SUMMARY_REASONS`, as `drift/route.ts` words a reading's: a refusal, a stop and a stored
   state read the same wherever they reach the card. No sentence here says the requested work was delivered,
   and none presents a citation as proof of the sentence beside it
   ([the known limit](../../../docs/design-session-summary.md#the-known-limit-relevance-is-not-checked)). */

export const SUMMARY_ADDS =
  'A summary tells this session as a short story in phases, each line citing the entries it rests on. It is written by a model; the outline below is Compass’s own grouping.';
export const SUMMARY_WORKING_KEEP = 'You can keep working. The summary will appear here.';
export const SUMMARY_STARTING = 'Starting a summary of this finished session…';
export const SUMMARY_OFF =
  'Summaries are turned off. Nothing from this session is sent for a summary until you turn them on.';
export const SUMMARY_NOT_CLAUDE = (harness: string) =>
  `${harness} sessions cannot be summarized yet: Compass summarizes Claude Code sessions only. The outline below is Compass’s own grouping.`;
export const SUMMARY_RELEVANCE =
  'Each line cites the entries it rests on. Compass checks that a cited entry exists and what kind it is, not that it supports the line.';
export const SUMMARY_FAILED_SEND =
  'Compass could not confirm the request. Nothing changed; try again.';
export const SUMMARY_CANCEL_FAILED = 'Compass could not confirm the cancel. Try again.';
export const SUMMARY_HOLDS = 'Holds evidence for a departure';
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
  'readings-off': () =>
    'Readings are turned off, and that stops summaries too. Turn readings back on in the Drift card to summarize.',
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
export const WITHHELD_TITLE = 'A phase title was withheld here.';
export const LEDE_LAST = 'The opening summary is written once every part has been read.';

/* A `said` bullet reads as the agent's words: it opens with "Said", and keeps the model's own opening when the
   model already wrote it so. */
export function saidText(words: string): string {
  const flat = words.trim();
  if (/^said\b/i.test(flat)) return words;
  /* The producer's attribution rule asks the model to name the speaker ("The agent said ..."), and the card's
     own "Said" already names it, so the two are folded rather than stacked. */
  const named = /^the agent\s+said\b\s*/i.exec(flat);
  return named ? `Said ${flat.slice(named[0].length)}` : `Said: ${words}`;
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

/* How large the read is, before a summary runs. The server plans its parts when a summary starts, so before
   then the card says what the outline counted. */
export function readSize(entries: number | null, more: boolean): string {
  if (entries === null) return '';
  return `${more ? 'More than' : 'About'} ${plural(entries, 'entry', 'entries')} to read. Compass plans the parts when the summary starts, and shows them here.`;
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
  for (const q of points) {
    if (start && before(q, start)) return { where: 'before', phases };
    if (end && before(end, q)) return { where: 'after', phases };
  }
  return { where: points.length && start && end ? 'between' : 'unplaced', phases };
}

export const phaseId = (key: string, place: string) =>
  `summary-phase:${key}:${place.replace(':', '-')}`;
