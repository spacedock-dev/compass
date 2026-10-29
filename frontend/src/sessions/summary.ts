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
import { CUE_TTL_MS } from '../controls/keyedState';
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
/* A summary written again is a new read of the session, not an edit of the last: the walk found the second one
   grouped the work into other phases, with nothing to say that was expected. */
export const SUMMARY_REWRITTEN =
  'A summary written again can group the work into different phases from the one before.';
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
  session_not_matched: () =>
    'Compass could not match this page to exactly one session on the board, so it cannot show a summary. A session idle longer than the board’s window is not on it.',
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

/* A string the server withheld, said in its place, in the words the hidden-run line uses: what was wrong with it,
   not the name of the rule. `subject` is what was withheld, so an opening summary is not called a line. */
export const WITHHELD_LINES: Readonly<Record<string, string>> = {
  completion_claim:
    'Left out: this line said work was done or working, and the record does not back that.',
  no_citation: 'Left out: this line cited no entry.',
  shape_fault: 'Left out: this line could not be shown in a form Compass accepts.',
  too_long_cut: 'Left out: this line was too long to show whole.',
};
const WITHHELD_OTHER = 'Left out: Compass held this line back.';
export const withheldSentence = (reason: string, subject = 'line'): string =>
  (WITHHELD_LINES[reason] ?? WITHHELD_OTHER).replace('this line', `this ${subject}`);

/* A run of withheld lines in a phase is one muted line, as the owner ruled on 2026-10-20: eleven "Withheld: ..."
   lines in twelve made the sample's summary unreadable. Each reason is the table's above, said of one line or of
   several; the rule that withholds them is unchanged, and each line's own reason stays one press away. */
const HIDDEN_WHY: Readonly<Record<string, readonly [string, string]>> = {
  no_citation: ['it cited no entry', 'they cited no entry'],
  shape_fault: [
    'it could not be shown in a form Compass accepts',
    'they could not be shown in a form Compass accepts',
  ],
  too_long_cut: ['it was too long to show whole', 'they were too long to show whole'],
};
/* A run whose lines were withheld for different reasons names each reason with its count, so the one line still
   says why: "each broke a rule a summary line must keep" once stood for a mix and said none of them. */
const HIDDEN_PART: Readonly<Record<string, readonly [string, string]>> = {
  completion_claim: [
    'was left out because the record does not back it',
    'were left out because the record does not back them',
  ],
  no_citation: ['cited no entry', 'cited no entry'],
  shape_fault: [
    'could not be shown in a form Compass accepts',
    'could not be shown in a form Compass accepts',
  ],
  too_long_cut: ['was too long to show whole', 'were too long to show whole'],
};
const HIDDEN_OTHER = ['was held back', 'were held back'] as const;
export function hiddenSentence(reasons: readonly string[], range: string): string {
  const n = reasons.length;
  const counts = new Map<string, number>();
  for (const reason of reasons) {
    const key = reason in HIDDEN_PART ? reason : '';
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const only = counts.size === 1 ? ([...counts.keys()][0] ?? '') : null;
  /* A line the producer held for saying, in its own voice, that work was done or working: the reader is told the
     record does not back it, as the walk asked, and each line's own reason stays one press away. */
  if (only === 'completion_claim')
    return `${n === 1 ? 'One line was left out because the record does not back it' : `${String(n)} lines were left out because the record does not back them`}.${range ? ` ${range}.` : ''}`;
  const one = only === null ? undefined : HIDDEN_WHY[only];
  const why =
    counts.size === 1
      ? one
        ? one[n === 1 ? 0 : 1]
        : n === 1
          ? 'it was held back'
          : 'they were held back'
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
    'Phase title left out: it used a word that can say work is done, such as “fix” or “done”, which a title may not.',
  shape_fault: 'Phase title left out: it could not be shown in a form Compass accepts.',
  too_long_cut: 'Phase title left out: it was too long to show whole.',
};
export const withheldTitle = (reason: string): string =>
  WITHHELD_TITLES[reason] ?? 'Phase title left out: Compass held it back.';
export const LEDE_LAST = 'The opening summary is written once every part has been read.';

/* A `said` bullet is the agent's words, and its text names the agent as the speaker: the producer's attribution
   rule asks for "The agent said ...", and the check withholds a line that does not. A line that arrives
   without one, from a summary stored before that, is given the speaker here, so it never reads as the summary's
   own claim. There is no "Said:" label: it was a kind marker leaking into the text. */
/* One table of speech verbs for every speaker test, so a line naming the agent or the person with any of them is
   read as that speaker's. Three tables once disagreed: "The agent reported ..." matched only the person's, and an
   `asked` line credited it to the person ("You said: The agent reported ..."). */
const SPEECH_VERB =
  '(?:asked|said|reported|confirmed|requested|wanted|told|noted|explained|mentioned|suggested|proposed|stated|replied|answered|claimed|wrote)';
const ADVERB = '(?:(?:also|then|later|again|first|finally|now)\\s+)?';
const AGENT_NOUN =
  "(?:the\\s+agent['’]s\\s+reply|the\\s+agent|agent|the\\s+assistant|assistant|claude)";
const BARE_SAID = /^said\b(?:\s+that\b)?[\s:,]*/i;
export function saidText(words: string): string {
  const flat = words.trim();
  if (AGENT_NAMED.test(flat) || AGENT_SUBJECT.test(flat)) return words;
  const rest = BARE_SAID.test(flat) ? flat.replace(BARE_SAID, '') : flat;
  return rest ? `The agent said: ${rest}` : words;
}
/* The agent named as the speaker, as opposed to a bare "Said", which an `asked` line uses for the person too. */
const AGENT_NAMED = new RegExp(`^${AGENT_NOUN}\\s+${ADVERB}${SPEECH_VERB}\\b`, 'i');
/* The agent as the subject of any clause, not only a speech one: "The agent read the gate ...". Such a line already
   names who it is about, so "The agent said:" in front of it read "The agent said: The agent read ...". */
const AGENT_SUBJECT = /^the\s+(?:agent|assistant)\b(?!['’]s\b)/i;
/* The person as the subject of any clause, which the card says as "You": "The person chose ..." is "You chose ...",
   in front of which no kind prefix is wanted either. The subject only: a quote or a later mention is left alone. */
const PERSON_SUBJECT = /^the\s+(?:person|user)\b(?!['’]s\b)\s*/i;
const YOU_SUBJECT = /^you\b/i;
/* The verb after "the person" agrees with "you": "wants" is "want", "has" is "have". Past tense is untouched. */
const YOU_VERB: Readonly<Record<string, string>> = {
  has: 'have',
  is: 'are',
  was: 'were',
  does: 'do',
  goes: 'go',
};
function youSubject(rest: string): string {
  const [, verb = '', after = ''] = /^(\S+)([\s\S]*)$/.exec(rest) ?? [];
  const plain = verb.toLowerCase();
  const agreed =
    YOU_VERB[plain] ?? (/[^s]s$/.test(plain) && !plain.endsWith("'s") ? verb.slice(0, -1) : verb);
  return `You ${agreed}${after}`.trimEnd();
}
/* The opening paragraph in the card's own voice: "The person" at the start of a sentence is "You", with its verb
   agreed as a person bullet's is. This is only how the page draws the words. The stored text keeps "the person",
   which is the form the server's completion check recognises, so the check is not weakened to match the page. */
/* A sentence boundary is a stop, a space and a capital, so "e.g. the person" is not one. */
const SENTENCE_PERSON = /(^|[.!?]\s+)The\s+(?:person|user)\b(?!['’]s\b)\s*([^.!?]*)/g;
/* Only a verb follows the subject a fold turns into "You": "The user interface" and "The person who asked" name
   a noun or open a clause, and folding them told the reader something the model did not write. The test is the
   word's shape (past tense, a present "-s", a modal or an irregular past), not a list of every verb. */
const VERB_AFTER_PERSON =
  /^(?:\w+ed|\w+[^s'’]s|has|is|was|were|does|goes|will|would|can|could|should|must|may|might|did|had|chose|said|wrote|ran|took|made|saw|told|gave|got|found|felt|kept|left|began|went|knew|asked|wanted)$/i;
export function ledeWords(words: string): string {
  return words.replace(SENTENCE_PERSON, (whole, before: string, rest: string) => {
    const first = /^[^\s,;:]+/.exec(rest.trim())?.[0] ?? '';
    return rest.trim() && !/^[,;:]/.test(rest.trim()) && VERB_AFTER_PERSON.test(first)
      ? `${before}${youSubject(rest)}`
      : whole;
  });
}
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
  if (PERSON_YOU.test(flat) || YOU_SUBJECT.test(flat)) return words;
  /* The line names the agent as its speaker. An `asked` bullet cites the person and the agent, so it may report
     either, and "You said: The agent said ..." credited the agent's words to the person. */
  if (AGENT_NAMED.test(flat) || AGENT_SUBJECT.test(flat)) return saidText(words);
  const named = PERSON_THIRD.exec(flat) ?? BARE_SPEECH.exec(flat);
  if (named) {
    const rest = flat.slice(named[0].length);
    const verb = (named[1] ?? '').toLowerCase().replace(/\s+/g, ' ').trim();
    return rest.startsWith(':')
      ? `You ${verb}: ${rest.slice(1).trimStart()}`.trimEnd()
      : `You ${verb} ${rest}`.trimEnd();
  }
  /* The person as the subject of a verb that is not speech: "The person chose 54 exceptions" is "You chose ...". */
  const subject = PERSON_SUBJECT.exec(flat);
  if (subject) return youSubject(flat.slice(subject[0].length));
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
     is told as the agent's and names the person as the card does, "you". */
  if (kind === 'said' && (PERSON_NAMED.test(flat) || PERSON_SUBJECT.test(flat))) {
    const you = askedText(flat);
    return `The agent said ${(you[0] ?? '').toLowerCase()}${you.slice(1)}`;
  }
  if (kind === 'said') return saidText(words);
  if (kind === 'asked') return askedText(words);
  /* Work cited with words: a line that names its speaker is said as that speaker's, not in the summary's voice. */
  if (kind === 'did' && AGENT_NAMED.test(flat)) return saidText(words);
  if (kind === 'did' && (PERSON_NAMED.test(flat) || PERSON_SUBJECT.test(flat)))
    return askedText(words);
  if (kind === 'failed') return `${TOOL_REPORT.test(words) ? FAILED_SHORT : FAILED_MARK} ${words}`;
  return words;
}

/* Cited entries a chip cannot open: an earlier check or file has no entry of its own in Full activity. Said once,
   at the foot of the card, for the whole summary: it once followed the opening and most bullets. */
export function unlinkedSentence(n: number): string {
  return n === 1
    ? '1 cited entry is an earlier check or file that Full activity does not list, so it cannot be opened from here.'
    : `${String(n)} cited entries are earlier checks or files that Full activity does not list, so they cannot be opened from here.`;
}

/* Whether a failed bullet is a failed test run. The server marks a bullet failed when a cited check failed, which
   holds a build, a lint and a browser launch the agent's sandbox refused as much as a test. The card badges the
   first only: the walk found a sandboxed Storybook run badged with the weight of a real test failure. The
   producer's text is all the page has of the check, so a run is a test run when it names one and was not put down
   to the environment the agent ran in. A build, a lint or a type check is put down first even when its words
   name a test: `pnpm build:storybook` and `ruff check tests` each carry a test word and are not test runs. */
const TEST_RUN =
  /\b(?:tests?|suite|specs?|py\.test|pytest|vitest|jest|mocha|unittest|rspec|tox|nox|nextest|karma|storybook|stories|playwright|cypress)\b/i;
/* The reasons an agent gives for a run that never ran: its sandbox or environment named outright, or the
   refusals those produce (a denied or blocked call, a read-only disk, a browser that would not launch, a host it
   could not reach). The first walk's phrasing was the word "sandbox" alone; the rest read the same way. */
const ENVIRONMENT =
  /\b(?:sandbox(?:ed)?|environment|not-recorded|permission denied|operation not permitted|EPERM|EACCES|read-only file system|(?:launch|call|command|request|access) (?:was|were) blocked|(?:blocked|denied) by (?:the )?(?:sandbox|policy|environment)|operation not (?:allowed|permitted)|not allowed (?:in|by) (?:the )?sandbox|(?:failed|unable|could not) to launch|could not launch|ECONNREFUSED|ENOTFOUND|network is unreachable|offline|no network)\b/i;
const NOT_A_TEST =
  /\b(?:(?:pnpm|npm|yarn)\s+(?:run\s+)?(?:build|lint|typecheck|format|compile)|ruff|mypy|tsc|biome|eslint|prettier)\b/i;
export const isTestFailure = (words: string): boolean =>
  TEST_RUN.test(words) && !NOT_A_TEST.test(words) && !ENVIRONMENT.test(words);

/* The card's right-hand header: the model, and when the summary was made. */
export function summaryStamp(
  summary: StoredSummary,
  running: boolean,
  model: string,
  summarizing = false,
): string {
  const at = summary.madeAt ? clock(summary.madeAt) : '';
  /* A summary a job is still writing is not "summarized at" any time: it says so until the job is done. */
  if (summarizing) return [model, 'summarizing…'].filter(Boolean).join(' · ');
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

/* How large the read is, before a summary runs. With the server's plan of a whole read it adds the parts and an
   upper bound on the minutes; a plan off a partial read, one the preflight would refuse, or one with no parts is
   not quoted, so the card falls back to what the outline counted. */
export function readSize(
  entries: number | null,
  more: boolean,
  plan: SummaryPlan | null = null,
): string {
  if (entries === null) return '';
  const size = `${more ? 'More than' : 'About'} ${plural(entries, 'entry', 'entries')} to read`;
  /* A plan off a partial read counts a floor, and the job's own count can pass it: "at least 2 parts" once
     became "part 1 of 3" with nothing saying so. Only a whole read's count is quoted. */
  if (!plan || plan.reason || plan.parts < 1 || !plan.complete)
    return `${size}. Compass plans the parts when the summary starts, and shows them here.`;
  return `${size} in ${plural(plan.parts, 'part', 'parts')}, up to ${plural(plan.minutes, 'minute', 'minutes')}.`;
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

/* Each numbered entry's place in the record, for placing a departure. A Claude Code check or file keeps the
   number of its first run or write so no number moves, while its id and time are the newest one's: the
   turn-3 rewrite of a file first written in turn 1 reads #1.1. Placing by that number stretched every phase
   citing a rerun back to its first run, and a departure in one phase marked the later ones as well. So the
   place is the entry's time; at an equal time a message comes first, as the server numbers a check after the
   message at or before it, and then the number breaks the tie. Only an entry the page numbers is placed. */
export function recordPositions(
  entries: readonly { readonly id: string; readonly at: number | null }[],
  numbers: ReadonlyMap<string, string>,
): Map<string, Position> {
  const placed = entries
    .map((entry) => ({ id: entry.id, at: entry.at, n: positionOf(numbers.get(entry.id)) }))
    .filter(
      (row): row is { id: string; at: number; n: Position } => row.at !== null && row.n !== null,
    )
    .sort(
      (a, b) =>
        a.at - b.at ||
        Number(a.n[1] > 0) - Number(b.n[1] > 0) ||
        a.n[0] - b.n[0] ||
        a.n[1] - b.n[1],
    );
  return new Map(placed.map((row, index) => [row.id, [index + 1, 0] as const]));
}

/* Where a departure's cited entries sit against a summary. A phase's span is the span its own bullets cite,
   because a phase publishes no bounds of its own; an entry between two phases is in neither. Positions come
   from `recordPositions`, so an entry the page has not numbered cannot be placed. */
export function placeDeparture(
  summary: StoredSummary,
  cited: readonly string[],
  positions: ReadonlyMap<string, Position>,
): Placement {
  const at = (id: string): Position | null => positions.get(id) ?? null;
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
export const DELETE_LAPSE_SECONDS = CUE_TTL_MS / 1000;
export function deleteArmed(receiver: string): string {
  return `Press again to delete this summary from this machine. Nothing else is deleted. Summarize writes a new one, which sends the session to ${receiver} again. Nothing has been deleted yet, and this offer lapses in ${String(DELETE_LAPSE_SECONDS)} seconds.`;
}
export function summaryDeleted(time: string): string {
  return `Summary deleted at ${time}. Summarize writes a new one.`;
}
