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
export const EXCERPT_READ_WHOLE = 'Excerpt. Analyze looks up the source when pressed.';
export const INTENT_LEDE =
  'Say what this session should achieve. Type it, or start from a prompt you gave the session. Compass reads the session against these words and never writes into the session.';

/* The ended-session caveat the goal box already carries, repeated where the save is confirmed: a reader who
   saved late read "Saved as a new revision." and had no sign that Analyze would still read the drafted goal
   instead. Said only beside a confirmed save on an ended session. The goal box shows the same sentence, so
   the short form, which reads as "nothing can be read", is not used. */
export const ENDED_CAVEAT =
  'This session has ended. Words you save now cannot be read against it; your saved intent and the goal drafted from your prompt still can.';

/* What the last save attempt is still worth saying. `persisted:false` is its own cue and not a success: the
   annotation is then held only in this process, and the next collection reloads the store from disk and
   the words are gone. One sentence per store outcome, chosen from the reply's `outcome` token and not from
   `persisted`, which is one bit for four sentences. */
export const HELD_CUES: Readonly<Record<string, string>> = {
  error: 'Not saved. The server refused the write, and your words are still in the box.',
  unpersisted:
    'Not stored. The store could not be written, so the refresh has already dropped these words, and they are still in the box.',
  saved: 'Saved as a new revision.',
  /* The request was lost, aborted at the bound, or answered with something unreadable: not a refusal, so
     never "Not saved". */
  unconfirmed:
    'Compass did not answer, so this page cannot tell whether your intent was saved. Your words are still in the box.',
  unchanged: 'Already stored. These words match the saved revision, so no new revision was minted.',
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

export const KEEP_ANALYZE = 'Keep my intent and analyze';
export const KEEP = 'Keep my intent';
export const ADD_DIRECTION = 'Add it to my intent';
export const KEEP_NO_ANALYSIS =
  'Kept your intent and settled the direction. No analysis was started.';
/* Keep never grants consent: where none is given it only settles, and the Allow and analyze beside its
   disclosure does the sending. */
export const KEEP_ALLOW =
  'Kept your intent and settled the direction. Press Allow and analyze to send it for a reading.';

export function keptDirections(count: number, owed = false): string {
  const sentence = owed ? KEEP_ALLOW : KEEP_NO_ANALYSIS;
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
    /^Kept your intent and settled (?:the direction|all \d+ directions)\.(?: No analysis was started\.| Press Allow and analyze to send it for a reading\.)$/,
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
