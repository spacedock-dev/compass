/* The sentences the Drift section owns, one home each. The page owns every sentence of a reading's rows:
   the producer's `why` is a closed token and its prose never reaches the page through a field. Ported from
   the legacy cockpit verbatim, and held to it by `shape.differential.test.ts`, which walks the producer's
   token set against this table. */

export const DEPARTURE = 'departure';
export const CONSISTENT = 'consistent with the evidence read';
export const UNVERIFIABLE = 'not verifiable from available evidence';
/* `reading.RESULT_UNSUPPORTED`: the claims question's own fourth result, never a departure, and only ever
   on the claims row. */
export const UNSUPPORTED = 'not shown by the record';
export const NOT_REACHED = 'not reached at this stop';
export const RESULTS: readonly string[] = [
  DEPARTURE,
  CONSISTENT,
  UNVERIFIABLE,
  UNSUPPORTED,
  NOT_REACHED,
];
export const CLAIMS = 'claims';

/* The published shape, spelt once on each side: a producer and a renderer disagreeing about a key name
   without either noticing is the measured failure. */
export const CRITERION_KEYS: readonly string[] = ['result', 'cites', 'detail', 'clause', 'why'];

export const ASSISTANT_ONLY =
  'Nothing cited here demonstrates that the requested output exists; each entry describes or asks for the work rather than showing it.';
export const UNCITED = 'Nothing resolvable was cited, so there is no entry to read this against.';

/* A reading cites what its press read, which can reach past the entries the board holds. A finished press
   reads older pages for it (`resolve`), within a page cap; where that stops short, the row says so and the
   reader's Show more, under the list, is what may resolve it. "May": the entry could also be newer than the
   last poll, or not a message the record pages return. */
export function unloadedCites(count: number): string {
  return count === 1
    ? 'This reading cites an entry that is not listed. Show more, under the list, may load it.'
    : `This reading cites ${String(count)} entries that are not listed. Show more, under the list, may load them.`;
}
/* What a press of a cited number or Load the cited entries found it could not list, once every page it may
   read has been read. Only a read that reached the record's start may say the record does not list it; one
   that stopped short (the page cap, a failed page) says Show more may still load it, as `unloadedCites` does. */
export function missingCites(count: number, reason: 'start' | 'stopped' | 'unshown'): string {
  if (reason === 'unshown')
    return 'The entries this finding cites are loaded, but none is marked in the list: they fall outside what this reading read, or its stated limit sets them aside.';
  if (reason === 'stopped')
    return count === 1
      ? 'An entry this finding cites could not be loaded: the read stopped before the start of the record. Show more, under the list, may load it.'
      : `${String(count)} entries this finding cites could not be loaded: the read stopped before the start of the record. Show more, under the list, may load them.`;
  return count === 1
    ? 'An entry this finding cites could not be loaded: the record read for this session does not list it.'
    : `${String(count)} entries this finding cites could not be loaded: the record read for this session does not list them.`;
}
export const BASELINE_OPEN =
  'You have given a later direction that is still unsettled, so this reads against a baseline that may not be the one you want.';
export const CLAUSE_UNRETAINED = 'the words of the revision this reading read are not retained';
export const UNKNOWN_KEY =
  'This board cannot read the reading it was given: it carries a field this build does not know. Nothing from it is shown, because a reading half-read is not a reading.';
export const SAVE_STEP = 'Save a goal above to analyze drift.';
export const NO_WORDS = `Nothing has been typed for this session, so there is nothing to read it against. ${SAVE_STEP}`;
export const MODEL_UNREAD =
  'Reading availability has not been read, so no reading can be offered. Compass asks again with the next update.';
export const JOB_TITLE = 'Analyzing drift';
/* The title over a run that keeps the last result in view, dimmed, until the new one lands. */
export const JOB_TITLE_AGAIN = 'Reading again';
export const JOB_NOTE = 'You can keep working. The result will appear here.';
export const JOB_NOTE_SO_FAR = 'Reads only the work so far. The result will appear here.';
export const CANCEL_FAILED =
  'Could not confirm the cancel. The analysis may still be running; refresh to check.';
export const MODEL_OFF =
  'Model calls are off for this run. Restart without --no-observer-model or its alias --no-harness-usage to allow a reading.';
export const UNAUTHORIZED =
  'Analyzing drift is not enabled in this build, because the abstention check that gates it has not been recorded. It waits on a later release; nothing on this page lifts it.';
export const ANNOTATIONS_OFF =
  'Annotations are off for this run. Start without --no-annotations to type a goal and an expected output here.';
export const ROUTE_UNREAD =
  'Who would read this session is not published, so no analysis is offered. Compass asks again with the next update.';
export const PROVIDER_CHANGED =
  'The reader for this session changed since this page was drawn, so nothing was sent; read who reads it now and press again.';
export const DESTINATION_CHANGED =
  'Where this session would be sent changed since this page was drawn, so nothing was sent; read where it goes now and press again.';

/* Which kind of absence each refusal is. Never on a paragraph that is not an absence: the class also
   carries rules, offers and results, and tagging them all would make the attribute a structurally present
   default that measures nothing about the session. */
export const REFUSAL_ABSENCE: ReadonlyMap<string, string> = new Map([
  [ROUTE_UNREAD, 'not-observed'],
  [NO_WORDS, 'waiting-on-you'],
  [MODEL_UNREAD, 'not-observed'],
  [MODEL_OFF, 'run-config'],
  [UNAUTHORIZED, 'run-config'],
  [ANNOTATIONS_OFF, 'run-config'],
]);

export const DERIVED_ONLY =
  "Rests only on Compass's own summary of this session, which is not evidence about it.";
export const OWN_WORDS_ONLY =
  'Rests only on what you asked for, which is the request rather than the work.';
export const MALFORMED = 'The reading did not return a usable result for this constraint.';
export const NOT_ASKED =
  'This constraint was not put to the reading when it was made, so no verdict on it was asked for.';
export const VERDICT_STATED =
  "The reading's explanation stated whether the work landed, which is a verdict the evidence read does not license, so its result was withdrawn.";
/* Not "The check it cited": `reading._evidence_rules` empties the published cites whenever it withdraws a
   verdict, so the page cannot tell a check that does not show the line from a write, or nothing, that was
   cited instead. Owner, 2026-10-14. */
export const CHECK_DOES_NOT_SHOW_IT =
  'What it cited does not show this: a departure needs its latest run failing, and a consistent its latest run passing with no change after it, both after the words you saved.';
export const CHANGED_AFTER_CHECK =
  'The check it cited passed, and a later command may have changed files, so it does not show this.';
export const CHECK_READ_INCOMPLETE =
  'The check passed, but part of the work record was not read, so it does not show this.';
export const CHECKS_NOT_READ =
  'No check this session recorded had room in the reading, so your expected output was not put to it.';
export const TELLS_THE_PERSON =
  'This line is about what the agent told you, and the analysis rested it on no message the agent wrote, so it reads as not verifiable.';
export const FAILED_CHECK_ON_RECORD =
  'A check this session ran failed after the words you saved, and this rests on no check that passed, so it reads as not verifiable.';
export const FAILED_CHECK_UNREAD =
  'A check that failed was not read, because the reading had no room for it, so nothing here says the output is consistent.';
export const CLAIM_RECORD_UNREAD =
  "Not all of this session's checks were read, so the analysis cannot say the record does not show what the agent said.";
/* The stored token of an outcome line the producer settled from a recorded write (`reading.WHY_RECORDED_WRITE`).
   Unlike every other token it is on a verdict that stands, so this sentence is only ever the reason a page that
   does not hold the write it cites gives for withdrawing it. */
export const RECORDED_WRITE = 'recorded-write';
export const RECORDED_WRITE_UNHELD =
  'Compass settled this from a file write it recorded, and this page does not hold that entry, so it reads as not verifiable.';
export const CLAIM_UNCITED =
  "The analysis did not cite the agent's message and, for a contradiction or a match, the entry it compared it with, so it reads as not verifiable.";

/* Why a stored row is `not verifiable`, token to sentence (`reading.WHY_TOKENS`). Consulted only where the
   page's own derivation left a `not verifiable` row without a reason: the live rules stay authoritative, and
   a stored reason never overrides a result derived from evidence the page holds. */
export const STORED_WHY: Readonly<Record<string, string>> = {
  'not-asked': NOT_ASKED,
  unreadable: MALFORMED,
  uncited: UNCITED,
  'no-work-shown': ASSISTANT_ONLY,
  'board-quoting-itself': DERIVED_ONLY,
  uncorroborated: OWN_WORDS_ONLY,
  'verdict-stated': VERDICT_STATED,
  'check-does-not-show-it': CHECK_DOES_NOT_SHOW_IT,
  'failed-check-unread': FAILED_CHECK_UNREAD,
  'changed-after-check': CHANGED_AFTER_CHECK,
  'check-read-incomplete': CHECK_READ_INCOMPLETE,
  'checks-not-read': CHECKS_NOT_READ,
  'tells-the-person': TELLS_THE_PERSON,
  'failed-check-on-record': FAILED_CHECK_ON_RECORD,
  'claim-uncited': CLAIM_UNCITED,
  'claim-record-unread': CLAIM_RECORD_UNREAD,
  [RECORDED_WRITE]: RECORDED_WRITE_UNHELD,
};

/* Said once, on the reading that no longer finds a departure the one before it did, with that reading's time:
   a departure that clears names itself, since nothing else on the card says the earlier one ended. When the
   reader pasted corrections between the two readings it says they named it, in the singular for the one. */
export const clearedLine = (count: number, at: string, corrections = 0): string => {
  const subject = count === 1 ? 'The departure' : `The ${String(count)} departures`;
  const verb = count === 1 ? 'no longer holds' : 'no longer hold';
  if (corrections === 0) return `${subject} from the ${at} reading ${verb}.`;
  const who = corrections === 1 ? 'your correction' : 'your corrections';
  return `${subject} ${who} named, from the ${at} reading, ${verb}.`;
};
export const CLAIM_LEAD = 'What the agent claimed';
export const RESULT_CANT_TELL = "Can't tell";
export const RESULT_NOTHING_SHOWS = "Can't tell: nothing recorded shows this yet";
export const RESULT_NOTHING_SHOWS_REASON =
  'Nothing recorded shows this yet: no write, check or message it read speaks to it.';
export const RESULT_CLAIM_TAIL = "The record read is the board's recent tail.";
export const RESULT_DEPARTS = 'Departs from your intent';
export const RESULT_NOTHING_FOUND =
  'Nothing found against what it read. This is not a check that the work was done.';
/* The mark is a local flag on this one analysis. Each state says what the press does and what changed, beside
   the control, because both effects (the level and Steer back) are drawn far above it. */
export const RESULT_NOT_ACCURATE = 'Mark as inaccurate';
export const RESULT_NOT_ACCURATE_HINT =
  'Stops this analysis from setting the drift level or Steer back. Nothing is sent or re-run.';
export const RESULT_MARKED =
  'Marked inaccurate. This analysis no longer sets the drift level or Steer back, and its verdicts below are set aside.';
export const RESULT_UNMARK = 'Undo';
export const RESULT_MARK_UNSAVED = 'Your mark was not saved. Try again.';

/* What it read: the model, the intent it read against, how much of the session it read, and what it never
   reads. Headings and short items rather than one paragraph of caveats. */
export const READ_SUMMARY = 'What the analysis read';
export const READ_MODEL = 'Model';
export const READ_INTENT = 'Your intent';
export const READ_SESSION = 'The session';
export const READ_NOT_READ = 'Not read';
export const READ_NEVER =
  'Files, diffs, test results, git or gh output, connected tools, or your screen. The model only sees what is on this page.';
export const READ_SCOPE: Readonly<Record<string, string>> = {
  final: 'Everything up to the session’s end.',
  'mid-flight': 'The work so far. The session was still running.',
  'last-turn': 'Everything up to the last finished turn.',
  withdrawn: 'The session end this analysis relied on is no longer reported.',
};
/* `reading.SCOPE_TEXT_MID_FLIGHT_IDLE`, the stored sentence of a press on an idle Claude Code session whose
   last turn has no recorded finish (owner, 2026-10-20). Recognised by its words, because its scope token is
   the running session's, and drawn as the reading's own line with the local time of the last entry it read. */
export const SCOPE_TEXT_IDLE =
  'The session was idle and its last turn was not recorded as finished, so this covers the work up to the last recorded entry. It is not a reading of how the turn or the session ended.';
export const readIdle = (at: string): string =>
  at
    ? `Read up to the last recorded entry at ${at}; the last turn was not recorded as finished.`
    : 'Read up to the last recorded entry; the last turn was not recorded as finished.';
export const READING_FINISHED = 'The analysis finished. Its result is in the Drift section.';

export const STEER_BY_HAND = 'Raised to you and nowhere else.';
export const STEER_BY_HAND_WHY =
  'Compass does not write into a session, so steering is by hand; the steer box in Console states the same rule about notes you write there.';
export const DEPARTURE_DEFINITION =
  'A departure is a place the record does not match the words you chose.';
export const READING_DEFINITION =
  'A reading is one model pass over the record, made only when you press for it.';
export const REVISION_DEFINITION = 'Each save is kept on its own.';

export const OFFER =
  'A reading is a model’s account of the evidence on this page: the observed record in this session’s activity and the goal and output you saved, and nothing else. It does not read a diff, a file, a test or a deliverable, replies from git, gh or connected tools, or what you saw on your screen.';
export const SCOPE =
  'What it reads is the evidence on this page: the observed record in this session’s activity and the goal and output you saved, and nothing else. It does not read a diff, a file, a test or a deliverable, replies from git, gh or connected tools, or your screen.';

export const PRESS_LINES: Readonly<Record<string, string>> = {
  'idle-unknown': 'Analyze opens while this session runs.',
  unobservable: 'This harness sends no events, so Analyze opens only while it runs.',
  'turn-stop': 'Analyze opens while a turn runs or once the session ends.',
  settling: 'Ready in a few seconds.',
  'stop-settling': 'Ready in a few seconds.',
  'revision-after-end': 'Your intent was saved after this session ended.',
};
export const PRESS_CODEX = 'Codex sessions can be analyzed only while a turn is running.';
export const PRESS_EVENTS = 'Analyze opens while this session runs or once it ends.';
/* The disclosure under a refused Analyze, which holds the server's whole sentence. Its old name, "Why it can't
   read", answered a question the reader had not asked; the reader wants to know why the button is off. */
export const WHY_OFF = 'Why Analyze is off';

export const FLIP_HOLD_MS = 10_000;
export const FLIP_SAY_EVERY_MS = 60_000;
export const FLIP_OPEN_RUNNING = 'Analyze is open again: the session is running.';
export const FLIP_OPEN_LAST_TURN = "Analyze is open: the session's last turn finished.";
export const FLIP_OPEN_ENDED = 'Analyze is open: the session ended.';
/* "Went quiet", not "stopped": a close also follows a turn left on an open tool call or an interruption,
   which did not stop. */
export const FLIP_CLOSED = 'Analyze closed: the session went quiet.';
export const FLIP_CLOSED_REVISION =
  'Analyze closed: your intent was saved after the session ended.';

export const WORK_HARNESSES: readonly string[] = ['claude', 'pi'];
export const WORK_READ_FROM = 'Compass reads work results from Claude Code and Pi only.';
export const WORK_AS_REPORTED = 'Results are as the tool reported; not inspected.';

/* The copy route's cap (`copied_corrections.CORRECTION_CAP_CHARS`): the lines' own 2,000 and room for eight
   explanations of 277 each, since the owner's ruling of 2026-10-20 that a departure carries its explanation
   ([the amendment](../../../docs/design-reading-a-session.md#amended-2026-10-20-owner-the-correction-carries-the-explanation)),
   and room for seven quotes of the agent's own words of 132 each since the owner's second ruling that day
   ([local time and quoted words](../../../docs/design-reading-a-session.md#amended-2026-10-20-owner-local-time-and-quoted-words)):
   2,000 + 8 × 277 + 7 × 132. */
export const CORRECTION_CAP = 5140;
/* The label the server writes before a departure's explanation (`correction.EXPLANATION_LABEL`). */
export const CORRECTION_WHY_LABEL = 'Why Compass reads this as drift: ';
export const STEER_HARNESSES: readonly string[] = ['claude'];
/* Over the correction, since it steers from the stored reading, which can be older than the session's latest
   work: the time that reading was read, on the reader's clock (owner, 2026-10-20). */
export const steerFrom = (at: string): string =>
  `Built from your saved intent and the reading at ${at}`;
/* Under the Steer back heading, in the design's words. */
export const STEER_PURPOSE =
  'Compass writes a correction for you to paste into the session. It never types into the session itself.';
/* Beside departures Steer back will not carry, so the button is never simply missing (owner, 2026-10-20). The
   rules are unchanged: a reading marked inaccurate, or one of an earlier version of the intent, sets no
   correction. With a failed check still offering one, the line says the departures are left out of it. */
export const STEER_OFF_MARKED = 'Steer back is off because you marked this analysis inaccurate.';
export const STEER_OFF_OLDER =
  'Steer back is off because this analysis read an earlier version of your intent. Analyze again to steer back from it.';
export const STEER_LEAVES_MARKED =
  'Steer back leaves these departures out because you marked this analysis inaccurate.';
export const STEER_LEAVES_OLDER =
  'Steer back leaves these departures out because this analysis read an earlier version of your intent.';
export const CORRECTION_HINT = 'Compass never sends this. Copy it and paste it into the session.';
export const CORRECTION_NOTHING = 'Nothing recorded now gives a correction to steer back from.';
export const CORRECTION_FAILED = 'Could not compose a correction. Press Steer back again to retry.';
export const CORRECTION_OLDER =
  'This was composed from an older record. Recompose replaces your edit with a correction from the record as it stands.';
export const CORRECTION_EDIT_REFUSED = 'This edit is unavailable here. Your text is kept.';
export const CORRECTION_COMPOSITION_REFUSED =
  'This composition would exceed 5,140 characters and was not kept.';
export const CORRECTION_UNDO_UNAVAILABLE =
  'The previous text was restored. Undo is unavailable for this refused edit.';
export const CORRECTION_PAINT_PAUSED =
  'Updates are paused while you edit this correction. Leave the box to show new work.';

/* The owner's 2026-10-14 ruling: the Claude route runs under an acceptance, not a passed qualification. The
   README's limits say it in these words, and `test_documentation` holds the two together. */
export const CLAUDE_READER_LIMIT =
  "The Claude reader's accuracy check has not passed, and its latest correction is unmeasured, so read a level as an account of the evidence, not a measurement.";

export const LIVE_LEVEL_NAMES: Readonly<Record<string, string>> = {
  none_or_low: 'None or low',
  medium: 'Medium',
  high: 'High',
  extreme: 'Extreme',
  not_enough: 'Not enough recorded yet',
};
export const LEVEL_SCALE: readonly string[] = ['none_or_low', 'medium', 'high', 'extreme'];
export const LIVE_LINE =
  'Reads checks and file paths, not what your intent says. Files written by shell commands, such as a build, are not seen.';
export const LIVE_HINT =
  'Shows a level after every turn, from checks and file paths, with no model call. The level shows here and in the header.';
export const LIVE_SAVE = 'Save your intent to see a live estimate.';
export const UNCHECKED = 'Not checked yet';
export const NUDGE = 'This is a quick estimate. Analyze to see what drifted and how to steer back.';
export const HARNESS_LIMIT = "Compass can't read work or the agent's replies from this harness.";

export const REASON_LINES: Readonly<Record<string, (n: string) => string>> = {
  'failed-check': (n) => (n ? `A check failed at ${n}.` : 'A check failed.'),
  departure: (n) =>
    n ? `Departure evidence: ${n}.` : 'The model assessed a departure from your intent.',
  'pass-then-write': () => 'A check passed, then files were written after it.',
  'claim-contradicted': (n) =>
    n
      ? `The record contradicts what the agent said at ${n}.`
      : 'The record contradicts what the agent said.',
  'claim-not-shown': (n) =>
    n
      ? `The record read does not show what the agent said at ${n}.`
      : 'The record read does not show what the agent said.',
  'writes-outside-folders': () => 'Some files were written outside the folders your intent names.',
  'most-writes-outside-folders': () =>
    'Most files were written outside the folders your intent names.',
};
/* The reasons `levels.REASONS` can publish that carry no sentence of their own: the level is drawn without
   one. Every reason has exactly one home, a line, a blocker or this list, and
   `api/vocabulary.test.ts` holds the three to the producer's list. */
export const SILENT_REASONS: readonly string[] = ['draft-unsaved', 'floor-met', 'no-reading'];
export const BLOCKER_LINES: Readonly<Record<string, string>> = {
  'no-passing-check': 'No check has passed yet.',
  'check-not-recorded': 'A check ran and its result was not recorded.',
  'background-run': 'A check ran in the background, so its result is not known.',
  'command-after-pass': 'A command that can change files ran after the last pass.',
  'pass-older-than-read': 'The last pass is older than the work it would show.',
  'later-direction': 'A later direction of yours is unsettled.',
  'entries-not-listed': 'Some written files were counted and not listed.',
  'intent-names-no-folder': 'Your intent names no folder, so where files went is not weighed.',
  'scan-incomplete': 'The record was not read in full.',
  'line-not-shown-by-a-check': 'A line of your intent is not shown by any check.',
  'outcome-not-reached': 'Work against your intent was not reached at this stop.',
  'no-outcome-line': 'No expected outcome line was saved.',
  'reading-malformed': 'Part of the stored analysis could not be read.',
};

/* The attribute that says which kind of absence a refusal is, only for the sentences that are one. */
export const absenceAttr = (text: string): Record<string, string> => {
  const kind = REFUSAL_ABSENCE.get(text);
  return kind ? { 'data-absence': kind } : {};
};

export const MODEL_PAUSE_EXPLANATION =
  'Compass stops sending session text to Claude Code or Codex, so it uses none of your tokens, and stays paused until you resume.';
export const READINGS_OFF = 'Model calls are paused. Nothing is sent until you resume.';
export const PAGE_OUTDATED = 'Reload this page before resuming model calls. Nothing was sent.';
export const NOTICE_SENT = 'This request sends:';
/* The re-run control in the Drift card's header, from the first reading on: Check again over a reading that
   new work or a changed intent left behind, Analyze again over a current one. */
export const RERUN_STALE = 'Check again';
export const RERUN_CURRENT = 'Analyze again';
export const SETTINGS = 'Drift settings';
export const NOTICE_WORDS = "The session's words, without the agent's messages.";
export const NOTICE_WORDS_AND_MESSAGES = "The session's words and the agent's messages.";
export const READINGS_OFF_CONSOLE = 'Model calls are paused. Nothing is sent until you resume.';
export const noticeProvider = (label: string): string => `Provider: ${label}`;
export const noticeDestination = (destination: string): string =>
  `Words go to: ${destination || 'destination not published'}`;
export const noticeToolOutput = (destination: string): string =>
  `Tool output goes to: ${destination}`;
