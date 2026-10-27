import { clock } from '../observed';
/* The sentences the Intent panel prints more than once, spelt once. Each is the legacy page's own wording,
   because the same fact worded two ways is two promises, and a refusal always names the step that
   resolves it. */

/* The seventh line's refusal, said where the reader meets it: beside the add control, which stays on the
   page and inert at six, and in the polite region when it is pressed anyway. The owner's ruling for a full
   list is to replace or merge a line, so the sentence names both. */
export const LINES_FULL =
  'An expected outcome holds six lines. Replace or merge a line to add another.';

export function directionTooLong(cap: number): string {
  return `A line holds ${String(cap)} characters. Shorten this one to add it.`;
}

export const DIRECTION_CLIPPED =
  'Only the start of this direction is shown; it is longer than Compass opens.';
export const DIRECTION_UNOPENED =
  'Could not open that direction, so nothing was added. Press again to retry.';

export function directionFailure(action: 'goal' | 'add' | 'keep', reason?: string): string {
  const source =
    reason === 'out_of_reach'
      ? 'That direction is beyond the part of the record Compass could search.'
      : reason === 'changed'
        ? 'The session wrote to its record while Compass was reading it. Press again.'
        : reason === 'not_found'
          ? 'That direction could not be verified as later than your intent in the current record.'
          : 'Compass could not open that direction.';
  const outcome =
    action === 'goal'
      ? 'Your goal has not changed.'
      : action === 'add'
        ? 'No outcome line was added.'
        : 'Nothing was settled and no analysis was started.';
  return `${source} ${outcome}`;
}

/* Analyze or Keep over an unsaved edit would read words that are not on screen, so the press is refused. Add's
   save has its own sentence, beside its line. */
export const INTENT_EDITED = 'Save your intent, or undo your edit, to analyze drift.';
export const INTENT_SAVING = 'Saving your intent…';
export const INTENT_EDITED_ADD = 'Save your intent, or undo your edit, to add this direction.';
export const INTENT_CHOSEN_SAID = 'Goal filled from your prompt. Not saved.';
export const INTENT_MEASURED = 'Drift is measured against these. Edit anything that is off.';
export const INTENT_DETECTED_SAID = 'Goal filled from your /goal. Not saved.';
/* A goal found in the reader's prompts is a draft like a /goal, and says where it came from in its own words. */
export const INTENT_FOUND_SAID = 'Goal found in your prompts. Not saved.';
export const FIND_GOAL_NOTHING = 'No clear goal in your prompts. Type one or use a prompt.';
export const FIND_GOAL_NO_PROMPTS =
  'Compass found no prompts of yours in this session to read. Type a goal.';
export const FIND_GOAL_LEFT =
  'A goal was found, but you had started typing one, so the box was left as it is.';
export const FIND_GOAL_OUTRANKED =
  'A goal was found, but this session already has one, so it was not used.';
export const FIND_GOAL_LOST =
  'Could not confirm the search for a goal. It has not been retried and nothing was changed.';
export const FIND_GOAL_REFUSED = 'Compass could not look for a goal just now. Nothing was changed.';
export const FIND_GOAL_RUNNING = 'A search for a goal is already running for this session.';
export const FIND_GOAL_FAILED = (label: string): string =>
  `${label} did not answer, so no goal was found. Nothing was changed. Press Find goal to try again.`;
export const FIND_GOAL_UNAVAILABLE = (label: string): string =>
  `${label} is not available here, so nothing was sent.`;
export const FIND_GOAL_TITLE = (label: string): string =>
  `Sends the prompts you typed in this session to ${label} to look for a goal. Nothing is sent until you press.`;
/* Appended to a source line whose words were cut; `cap` is the box's own limit, never a literal. */
export const goalCut = (cap: number): string =>
  ` · Shortened to fit ${cap.toLocaleString('en-US')} characters; Analyze reads this shortened goal`;
export const EXCERPT_READ_WHOLE = ' · Shortened here; Analyze reads the whole prompt';
/* `reading.LEDGER_WORDS_CAP_CHARS`, copied rather than fetched; `test_reader_words.py` holds the two equal.
   The ruled wording (docs/design-frontend-migration.md, 2026-10-13 departures): "up to" read as a limit that
   had bitten, so the sentence says it is how every prompt is read. */
export const ANALYZE_PROMPT_CAP_CHARS = 1_000;
export const ANALYZE_READS_PROMPT = `Analyze reads at most the first ${ANALYZE_PROMPT_CAP_CHARS.toLocaleString('en-US')} characters of any prompt.`;
export const GOAL_HINT =
  "Write what should be true when this session is done. Compass checks the session's work against it and never writes into the session.";

/* The ended-session caveat the goal box already carries, repeated where the save is confirmed: a reader who
   saved late read "Saved." and had no sign that Analyze would still read the drafted goal
   instead. Said only beside a confirmed save on an ended session. The goal box shows the same sentence, so
   the short form, which reads as "nothing can be read", is not used. */
export const ENDED_CAVEAT =
  'This session has ended. What you save now is kept, but Analyze will not check the session against it. Analyze still uses the intent you saved before the session ended, or a goal taken from one of your prompts.';

/* What the last save attempt is still worth saying. `persisted:false` is its own cue and not a success: the
   annotation is then held only in this process, and the next collection reloads the store from disk and
   the words are gone. One sentence per store outcome, chosen from the reply's `outcome` token and not from
   `persisted`, which is one bit for four sentences. */
export const HELD_CUES: Readonly<Record<string, string>> = {
  error: 'Not saved. The server refused the write, and your words are still in the box.',
  unpersisted:
    'Not stored. The store could not be written, so the refresh has already dropped these words, and they are still in the box.',
  saved: 'Saved.',
  /* The request was lost, aborted at the bound, or answered with something unreadable: not a refusal, so
     never "Not saved". */
  unconfirmed:
    'Compass did not answer, so this page cannot tell whether your intent was saved. Your words are still in the box.',
  unchanged: 'Already saved. These words match what is stored, so nothing new was saved.',
  /* The store exists and the server could not read it, so it wrote nothing: writing would keep only what
     it can read and lose every other session's words. The remedy is the file, not a retry. */
  untrusted:
    'Not saved. Compass could not read compass-annotations.json, so nothing was saved and nothing was overwritten, and what you typed is still in the box. Move or repair that file to save again.',
  'settle-untrusted':
    'Not settled. Compass could not read compass-annotations.json, so nothing was saved and nothing was overwritten. Move or repair that file to settle again.',
  /* This session's own entry is one this build cannot read: it is kept as it was, never saved over. */
  unreadable:
    "Not saved. This session's words were saved by a build of Compass that can read more than this one, so nothing was saved over them, and what you typed is still in the box. Save from that build, or remove this session's entry from compass-annotations.json.",
};

/* The cue Read from my latest message earns carries the time it moved the start to, so its kind does too. A static table
   cannot hold a time; the page reads it back from the refreshed row and stamps it here, in the one moment
   the save is drawn. */
export const READS_FROM_KIND = 'reads-from:';
export const readsFromKind = (at: number): string => `${READS_FROM_KIND}${String(at)}`;
export const isReadsFrom = (kind: string): boolean => kind.startsWith(READS_FROM_KIND);
export function readsFromSentence(kind: string): string {
  const at = Number(kind.slice(READS_FROM_KIND.length));
  return Number.isFinite(at) && at > 0
    ? `Saved. Compass now reads from ${clock(at)}. Work before that is not read.`
    : '';
}

/* What Read from my latest message does, said where the reader chooses it. Saving alone keeps the start the first reading
   had, so the work already done toward earlier words stays read. */
export const READ_FROM_NOW_WHY =
  'Saves your intent and reads the session from your latest message on. Work before that message is not read. Save intent alone keeps reading from where it started.';

/* The reply's `outcome` token to the cue it earns. An unknown token, from a server newer than this page,
   falls back on `persisted`, which keeps its meaning across builds. */
export const HELD_OUTCOME_CUES: Readonly<Record<string, string>> = {
  stored: 'saved',
  unchanged: 'unchanged',
  refused: 'error',
  unwritable: 'unpersisted',
  untrusted: 'untrusted',
  unreadable: 'unreadable',
};

/* The page's own, unlike the server's discard sentences: no answer came, so the server has said nothing
   about these words. */
export const DISCARD_UNCONFIRMED =
  'Compass did not answer, so this page cannot tell whether the words were discarded.';

/* How long the armed discard refuses to be confirmed. Above the one second a double-click interval can be
   set to and above a key repeat delay, because both gestures deliver the second press through one listener
   and the replacement button is already under the pointer. A floor and not a disabled interval, because a
   disabled button would move focus and the arm is meant to lapse on its own. */
export const DISCARD_DWELL_MS = 1_200;

export const ADOPT_REFUSED: Readonly<Record<string, string>> = {
  untrusted:
    'Compass could not read compass-annotations.json, so your prompt was not saved as the goal and nothing was overwritten. Move or repair that file to save again.',
  unreadable:
    "This session's words were saved by a build of Compass that can read more than this one, so your prompt was not saved as the goal. Save from that build, or remove this session's entry from compass-annotations.json.",
};

export const ADOPT_CHANGED =
  'The prompt or saved goal changed, or could not be saved. Review the goal before trying again.';

export const KEEP = 'Leave it';
export const ADD_DIRECTION = 'Add as a line';
export const GOAL_DIRECTION = 'Make it the goal';
export const RULE_HINT = 'Write the rule, not the moment.';
export const KEEP_NO_ANALYSIS =
  'Kept your intent and settled the direction. No analysis was started.';
export function keptDirections(count: number): string {
  const sentence = KEEP_NO_ANALYSIS;
  return count === 1
    ? sentence
    : sentence.replace('the direction.', `all ${String(count)} directions.`);
}
export const KEEP_REFUSED =
  'Nothing was settled and no analysis was started: your intent changed since this page was drawn, or the store refused the mark. Review your intent and press again.';
export const KEEP_READ_FIRST =
  'Nothing was settled yet. Each direction Keep settles is now shown whole. Read it, then press again.';
export const KEEP_BATCH_LIMIT =
  'Keep can open up to 64 directions at once. Nothing was settled and no analysis was started.';
export const KEEP_UNOPENED =
  'Nothing was settled and no analysis was started: Compass could not open the whole text of every direction Keep would settle, so it cannot show you what you would keep. Press again to retry.';
export const KEEP_UNCONFIRMED =
  'Could not confirm the press. Refresh to check whether your intent was kept before pressing again.';

/* The short line a press's answer leaves under its button, with the whole sentence behind an info mark. The
   long answers used to print under the button and move every control around it; the words are the same,
   said once, in a hover and focus popover and to a screen reader, and the polite region still announces
   the whole sentence. A message with no entry here keeps its first sentence, cut at a word. */
const FEEDBACK_SHORT: readonly (readonly [RegExp, string])[] = [
  [/^That direction is beyond the part of the record/, 'Direction out of reach'],
  [/^The session wrote to its record while Compass/, 'Record changed, press again'],
  [/^That direction could not be verified/, 'Direction unverified'],
  [/^Compass could not open that direction/, 'Could not open direction'],
  [/^Could not open that direction/, 'Could not open direction'],
  /* Only the bare settlement is "Intent kept". The same sentence with a reason after it (the reader changed,
     the daily limit, a store that could not be reached) says the reading did not start, and the line says so. */
  [
    /^Kept your intent and settled (?:the direction|all \d+ directions)\. No analysis was started\.$/,
    'Intent kept',
  ],
  [/^Kept your intent/, 'Kept, not analyzed'],
  [/^Nothing was settled yet/, 'Read each direction, then press again'],
  [/^Keep can open up to/, 'Too many directions to keep at once'],
  [/^Nothing was settled/, 'Nothing was settled'],
  [/^Could not confirm the press/, 'Press not confirmed'],
];
const FEEDBACK_SHORT_MAX = 44;

export function feedbackSummary(message: string): string {
  for (const [pattern, short] of FEEDBACK_SHORT) if (pattern.test(message)) return short;
  const first = message.split(/(?<=[.!?])\s/)[0] ?? message;
  if (first.length <= FEEDBACK_SHORT_MAX) return first;
  const head = first.slice(0, FEEDBACK_SHORT_MAX);
  const cut = first[FEEDBACK_SHORT_MAX] === ' ' ? head : head.replace(/\s+\S*$/, '');
  return `${cut}…`;
}

export const DRIFT_SUBTITLE = 'How far the session has moved from the goal';
export const LIVE_MONITOR = 'Live monitor';
