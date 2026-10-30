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
/* `reading.RESULT_GOAL_UNCLEAR`: the model read the goal, and the outcome lines if any, before the session
   and found no end state to read the work against. The goal row's alone, and it stands in place of a level:
   `levels.REASON_GOAL_UNCLEAR` is the reason the level carries. */
export const GOAL_UNCLEAR_RESULT = 'goal too vague to analyze against';
export const RESULTS: readonly string[] = [
  DEPARTURE,
  CONSISTENT,
  UNVERIFIABLE,
  UNSUPPORTED,
  NOT_REACHED,
  GOAL_UNCLEAR_RESULT,
];
/* The warning under the Goal field, in Compass's voice (owner, 2026-10-22). Its one home: the level's
   blocker line below says it too, so the sentence cannot drift between the two. */
export const GOAL_UNCLEAR =
  'This goal is too vague to analyze against. Rewrite it with what should be true when the work is done, then try again.';
/* The Drift card's own answer over a refused goal, where a level would stand. */
export const GOAL_UNCLEAR_VERDICT = 'No level: the goal is too vague to analyze against.';
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

/* The harness's own "goal met" verdict, and Compass's test of it (`reading.GOAL_VERDICT_*`). The verdict is
   always the harness's claim and the sentences here are Compass's: the producer's `check` and `why` are
   closed tokens, and its prose never reaches the page through them. A claim never moves a level and is never
   a passing check, and the sentences say so where a reader might take it for either
   ([DEC-26](../../../docs/design-reading-a-session.md#amended-2026-10-22-a-goal-met-verdict-is-a-claim)). */
export const GOAL_VERDICT_KEYS: readonly string[] = ['at', 'check', 'why', 'cites'];
/* A dispute that rests on a file taken away names the file and the moment, both or neither. */
export const GOAL_VERDICT_REMOVAL_KEYS: readonly string[] = ['path', 'changed_at'];
export const GOAL_VERDICT_REMOVAL_WHYS: readonly string[] = ['deleted-after', 'moved-after'];
/* The text the reason quotes was found in a recorded check's output: the count of distinct quoted spans
   found comes alone, with its own token (never in a payload as the text, only as how many). */
export const GOAL_VERDICT_QUOTED_KEYS: readonly string[] = ['quoted'];
export const GOAL_VERDICT_QUOTED_WHY = 'quoted-in-check';
export const GOAL_VERDICT_QUOTED_MAX = 8;
export const GOAL_VERDICT_CHECKS: readonly string[] = ['agrees', 'disputed', 'unconfirmed'];
export const GOAL_VERDICT_WHY: Readonly<Record<string, string>> = {
  'written-before': 'the file its reason names is recorded as written before the verdict',
  'passed-before': 'a check of the kind its reason names is recorded as passing before the verdict',
  'pr-created-before':
    'the pull request its reason names is recorded as created before the verdict',
  'ci-passed':
    'the pull request its reason names had every check that counts pass on this session’s commit',
  'ci-passed-config-changed': 'CI passed, and the session changed its CI configuration',
  'written-after': 'the file its reason names was written again after the verdict',
  'deleted-after': 'a file its reason or the goal names was deleted after the verdict',
  'moved-after': 'a file its reason or the goal names was moved away after the verdict',
  'check-failed': 'a check of the kind its reason names has a failing latest run',
  'quoted-in-check': 'the quoted text is in the output of a check Compass recorded',
  'not-found': 'the record Compass read does not show what its reason names',
  'nothing-checkable': 'its reason names no file or check Compass can look for',
};
/* The same answers for a claim that gives no reason (every Codex verdict), which the reading tests against what
   the goal names instead; "its reason" would describe words the harness never wrote. */
export const GOAL_VERDICT_WHY_GOAL: Readonly<Record<string, string>> = {
  'written-before': 'the file the goal names is recorded as written before the verdict',
  'passed-before': 'a check of the kind the goal names is recorded as passing before the verdict',
  'pr-created-before': 'the pull request the goal names is recorded as created before the verdict',
  'ci-passed':
    'the pull request the goal names had every check that counts pass on this session’s commit',
  'ci-passed-config-changed': 'CI passed, and the session changed its CI configuration',
  'written-after': 'the file the goal names was written again after the verdict',
  'deleted-after': 'a file the goal names was deleted after the verdict',
  'moved-after': 'a file the goal names was moved away after the verdict',
  'check-failed': 'a check of the kind the goal names has a failing latest run',
  'quoted-in-check': 'the quoted text is in the output of a check Compass recorded',
  'not-found': 'the record Compass read does not show what the goal names',
  'nothing-checkable':
    'the claim gives no reason, and the goal names no file or check Compass can look for',
};
/* The pull request's CI checks a press read from GitHub (`ci_read`), as the stored record holds them. The
   tokens are the producer's closed sets, and the sentences are Compass's: nothing the CLI said reaches the
   page through them
   ([DEC-30](../../../docs/design-reading-a-session.md#dec-30-compass-may-read-a-pull-requests-ci-state-when-the-reader-presses-analyze)). */
export const CI_BUCKETS: readonly string[] = ['pass', 'fail', 'pending', 'skipping', 'cancel'];
export const CI_SOURCES: readonly string[] = ['goal', 'record'];
export const CI_READ_ERRORS: Readonly<Record<string, string>> = {
  'gh-missing': 'the gh command was not found on this machine',
  'gh-signed-out': 'gh is not signed in, so run gh auth login to let Compass read them',
  'pull-request-not-found': 'GitHub does not show that pull request to your gh login',
  'rate-limited': 'GitHub is rate limiting your gh login',
  timeout: 'GitHub did not answer in time',
  'unreadable-output': 'gh answered in a shape Compass does not read',
  'gh-failed': 'gh failed',
  'glab-missing': 'the glab command was not found on this machine',
  'glab-signed-out': 'glab is not signed in, so run glab auth login to let Compass read them',
  'glab-failed': 'glab failed',
  'host-not-configured': 'glab’s own configuration does not name that GitLab host',
  'no-session-folder':
    'no folder is known for this session, so the pull request’s commit could not be matched to it',
  'no-session-commit':
    'the commit this session is on could not be read (git is off or the folder is not a repository), so the pull request’s commit could not be matched to it',
};
/* The three tokens both providers share, worded for GitLab. */
const CI_READ_ERRORS_GITLAB: Readonly<Record<string, string>> = {
  'pull-request-not-found': 'GitLab does not show that merge request to your glab login',
  'rate-limited': 'GitLab is rate limiting your glab login',
  timeout: 'GitLab did not answer in time',
  'unreadable-output': 'glab answered in a shape Compass does not read',
  'no-session-folder':
    'no folder is known for this session, so the merge request’s pipeline commit could not be matched to it',
  'no-session-commit':
    'the commit this session is on could not be read (git is off or the folder is not a repository), so the merge request’s pipeline commit could not be matched to it',
};
export type CiProvider = 'GitHub' | 'GitLab';
/* Which provider a stored repository names. A GitLab one is stored as `host/group/project`, and no GitHub
   owner holds a dot (`ci_read.host_of`). */
export const ciProvider = (repository: string): CiProvider =>
  repository.split('/')[0]?.includes('.') ? 'GitLab' : 'GitHub';
/* The provider the verdict's own words name when no CI read is stored: a GitLab merge request URL, or an
   `MR`/merge request wording with no `PR`/pull request beside it. Anything else says GitHub's word. */
export const requestProviderOf = (text: string): CiProvider => {
  if (/\/-\/merge_requests\/\d/.test(text)) return 'GitLab';
  const merge = /\b(?:MRs?|merge\s+requests?)\b/i.test(text);
  const pull = /\b(?:PRs?|pull\s+requests?)\b|\/pull\/\d/i.test(text);
  return merge && !pull ? 'GitLab' : 'GitHub';
};
export const ciReadReason = (token: string, provider: CiProvider): string =>
  (provider === 'GitLab' ? CI_READ_ERRORS_GITLAB[token] : undefined) ??
  CI_READ_ERRORS[token] ??
  token;
/* The merge request GitLab numbers with a bang, and a pull request GitHub numbers with a hash. */
export const ciRequestName = (repository: string, number: number): string =>
  `${repository}${ciProvider(repository) === 'GitLab' ? '!' : '#'}${String(number)}`;
export const ciReadLabel = (provider: CiProvider): string =>
  provider === 'GitLab' ? 'Merge request checks' : 'Pull request checks';
/* The entry a stored CI check is, as the producer's fact words it (`ci_read.facts`), so a citation of one
   resolves on this page as it did when the reading was made. */
export const CI_ENTRY_SOURCE = 'GitHub pull request check, read by Compass · recorded';
export const CI_ENTRY_SOURCE_GITLAB =
  'GitLab merge request pipeline job, read by Compass · recorded';
export const CI_ENTRY_WORDS: Readonly<Record<string, string>> = {
  pass: 'passed on the pull request',
  fail: 'failed on the pull request',
  pending: 'still running on the pull request',
  skipping: 'skipped on the pull request',
  cancel: 'cancelled on the pull request',
};
export const CI_ENTRY_WORDS_GITLAB: Readonly<Record<string, string>> = {
  pass: 'passed on the merge request',
  fail: 'failed on the merge request',
  pending: 'still running on the merge request',
  skipping: 'skipped on the merge request',
  cancel: 'cancelled on the merge request',
};
export const CI_ENTRY_RESULT: Readonly<Record<string, string>> = {
  pass: 'passed',
  fail: 'failed',
  pending: 'pending',
  skipping: 'skipped',
  cancel: 'cancelled',
};
export const CI_ENTRY_KIND = 'GitHub check';
export const ciEntryKind = (by: string): string => (by === 'gitlab' ? 'GitLab job' : CI_ENTRY_KIND);
export const CI_BUCKET_WORDS: Readonly<Record<string, string>> = {
  pass: 'passed',
  fail: 'failed',
  pending: 'still running',
  skipping: 'skipped',
  cancel: 'cancelled',
};
export const ciReadFailed = (reason: string, provider: CiProvider = 'GitHub'): string =>
  `${provider === 'GitLab' ? 'Merge request' : 'Pull request'} checks were not read from ${provider}: ${reason}.`;
export const ciReadFrom = (
  at: string,
  pr: string,
  counts: string,
  provider: CiProvider = 'GitHub',
): string => `Read from ${provider} at ${at}: ${pr}, ${counts}.`;
export const CI_NO_CHECKS = 'no checks reported';
export const CI_SETTLES = 'Every check that counts passed on this session’s commit.';
export const CI_FAILING = 'A failing check on this session’s commit counts against the work.';
/* A pull request merged by a commit the session folder's history holds (`ci_read`'s `merged_in`): its head is
   not the folder's commit, but what it ran is in the session's branch. */
export const CI_MERGED_IN =
  'The pull request was merged into this session’s branch, so its checks count.';
export const CI_SETTLES_MERGED = 'Every check that counts passed on the merged pull request.';
export const CI_FAILING_MERGED =
  'A failing check on the merged pull request counts against the work.';
export const CI_RUNNING = 'Checks are still running, so they settle nothing.';
export const CI_NONE_DONE = 'No check has completed, so they settle nothing.';
export const CI_CANCELLED = 'A cancelled check keeps them from settling anything.';
export const CI_HEAD_MOVED =
  'The pull request head is not this session’s commit, so they settle nothing.';
export const CI_HEAD_MOVED_GITLAB =
  'The merge request head is not this session’s commit, so they settle nothing.';
export const CI_HEAD_UNKNOWN =
  'Compass could not read this session’s commit, so they settle nothing.';
export const CI_CAUTION = 'This session changed the CI configuration.';
export const CI_REQUIRED_ONLY = 'Only the checks GitHub requires are counted.';
/* How many checks that rule left out, so a failing one that is not required is not silently hidden. */
export const ciNotCounted = (count: number): string =>
  `${String(count)} non-required ${count === 1 ? 'check' : 'checks'} not counted.`;
/* The switch beside the notice. `flag-off` is the run's own `--no-ci-read`, which the page cannot lift. */
export const CI_SWITCH_ON =
  'Pull request checks are read from GitHub or GitLab with your gh or glab login when you press Analyze.';
export const CI_SWITCH_OFF = 'Pull request checks are not read from GitHub or GitLab.';
export const CI_SWITCH_FLAG =
  'Pull request checks are not read from GitHub or GitLab for this run (--no-ci-read).';
export const CI_SWITCH_FAILED = 'Could not save that. Try again.';

/* "the pull request its reason names, example-org/example-repo#7, is recorded as created before the verdict":
   the pull request fact the test confirmed, named from the entry it cites. */
export const goalVerdictPullRequest = (
  name: string,
  byGoal = false,
  provider: CiProvider = 'GitHub',
): string =>
  `the ${provider === 'GitLab' ? 'merge' : 'pull'} request ${byGoal ? 'the goal' : 'its reason'} names, ${name}, is recorded as created before the verdict`;
/* "the quoted text is in the output of check #12": where the text its reason quotes was found, named by the
   numbers the card gives the checks. It says where the text is and nothing about whether the check passed. */
export const goalVerdictQuoted = (numbers: readonly string[]): string =>
  `the quoted text is in the output of ${numbers.length === 1 ? 'check' : 'checks'} ${numbers
    .map((n) => `#${n}`)
    .join(numbers.length === 2 ? ' and ' : ', ')}`;
/* "docs/e2e/notes.md was deleted at 22:59, after the verdict": the file and the moment the record shows. */
export const goalVerdictRemoval = (why: string, path: string, at: string): string =>
  `${path} was ${why === 'moved-after' ? 'moved away' : 'deleted'} at ${at}, after the verdict`;
/* The two verdict reasons that name the request, worded for a reader on GitLab, where it is a merge request.
   Read where the stored CI read is from GitLab (`ciProvider`); a reading with no CI read takes it from the verdict's own URL or wording (`requestProviderOf`). */
const GOAL_VERDICT_WHY_GITLAB: Readonly<Record<string, string>> = {
  'pr-created-before':
    'the merge request its reason names is recorded as created before the verdict',
  'ci-passed':
    'the merge request its reason names had every check that counts pass on this session’s commit',
};
const GOAL_VERDICT_WHY_GOAL_GITLAB: Readonly<Record<string, string>> = {
  'pr-created-before': 'the merge request the goal names is recorded as created before the verdict',
  'ci-passed':
    'the merge request the goal names had every check that counts pass on this session’s commit',
};
export const goalVerdictWhy = (why: string, byGoal: boolean, provider: CiProvider): string =>
  (provider === 'GitLab'
    ? (byGoal ? GOAL_VERDICT_WHY_GOAL_GITLAB : GOAL_VERDICT_WHY_GITLAB)[why]
    : undefined) ??
  (byGoal ? GOAL_VERDICT_WHY_GOAL : GOAL_VERDICT_WHY)[why] ??
  '';
export const GOAL_VERDICT_LABEL = 'The harness’s claim:';
/* Both claims name the product, not the payload's harness label ("Claude"). Claude Code and Codex report a
   goal met; only Claude Code gives one up this way, and the Intent card's note says "Claude Code" too. */
const VERDICT_PRODUCT: Readonly<Record<string, string>> = { claude: 'Claude Code', codex: 'Codex' };
export const goalVerdictClaim = (at: string, harness = 'claude'): string =>
  `${VERDICT_PRODUCT[harness] ?? 'The harness'} marked this goal met at ${at}.`;
export const goalGaveUpClaim = (at: string): string => `Claude Code gave up on this goal at ${at}.`;
/* A give-up is the harness's say-so about a goal it ended: Compass does not check it and it moves no level. */
export const GOAL_GAVE_UP_LINE = 'Compass has not checked it, and it does not change the level.';
export const GOAL_VERDICT_LINES: Readonly<Record<string, (why: string) => string>> = {
  'claim-only': () =>
    'Compass has not analyzed this session, so nothing has checked it and no level is implied.',
  unchecked: () =>
    'Compass’s reading does not cover this verdict, so nothing has checked it. Analyze again to check it.',
  agrees: (why) =>
    `Compass agrees: ${why}. This does not change the level and is not a passing check.`,
  disputed: (why) => `Compass disputes it: ${why}. Compass’s own reading stands.`,
  unconfirmed: (why) => `Compass could not confirm it: ${why}. This does not change the level.`,
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
/* An earlier departure the next reading answered with the agent's own message, and nothing that shows the work,
   is not said to be gone: the card lists it, and the verdict says so in place of `clearedLine`. With no single
   time to name, the readings are named together. */
export const priorListedLine = (count: number, at: string): string => {
  const subject = count === 1 ? 'The departure' : `The ${String(count)} departures`;
  const verb = count === 1 ? 'is' : 'are';
  const from = at ? `the ${at} reading` : 'earlier readings';
  const after = at ? 'it' : 'them';
  return `${subject} from ${from} ${verb} still listed below: the reading after ${after} rests on what the agent said.`;
};
export const PRIOR_DEPARTURE_LABEL = 'Earlier departure';
export const priorDepartureLine = (earlier: string, later: string, where: string): string =>
  `From the ${earlier} reading. The ${later} reading rests this line on what the agent said at ${where}, which is not a check.`;
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
/* The scope arrives in the stored reading, so a name the table does not list (or one inherited from
   Object.prototype, such as "constructor") falls back to the producer's own words rather than reading the
   prototype. */
export function readScopeLine(scope: string, fallback: string): string {
  return Object.hasOwn(READ_SCOPE, scope) ? (READ_SCOPE[scope] as string) : fallback;
}
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

export const WORK_HARNESSES: readonly string[] = ['claude', 'codex', 'pi'];
export const WORK_READ_FROM = 'Compass reads work results from Claude Code, Codex and Pi only.';
/* The sentence Codex's record earns: the checks its own rollout lists, from codex-cli 0.149, and not its
   subagents'
   ([the amendment](../../../docs/design-reading-a-session.md#amended-2026-10-30-owner-dec-23-applied-to-codex)). */
export const CODEX_RECORD =
  'records the checks a session ran and the files it patched, from codex-cli 0.149 on, and they are listed here. A result is the command’s exit code; Compass inspects no file, test or deliverable, and reads no subagent’s commands.';
export const CODEX_COMMANDS_UNREAD =
  'This Codex version records no exit status, so its commands are not read and no check is counted.';
export const WORK_AS_REPORTED = 'Results are as the tool reported; not inspected.';

/* The copy route's cap (`copied_corrections.CORRECTION_CAP_CHARS`): the lines' own 2,760 and room for eight
   explanations of 277 each, since the owner's ruling of 2026-10-20 that a departure carries its explanation
   ([the amendment](../../../docs/design-reading-a-session.md#amended-2026-10-20-owner-the-correction-carries-the-explanation)),
   and room for seven quotes of the agent's own words of 132 each since the owner's second ruling that day
   ([local time and quoted words](../../../docs/design-reading-a-session.md#amended-2026-10-20-owner-local-time-and-quoted-words)):
   2,760 + 8 × 277 + 7 × 132. The lines had 2,000 until the goal's cap rose to 1,000 (owner, 2026-10-27). */
export const CORRECTION_CAP = 5900;
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
  'This composition would exceed 5,900 characters and was not kept.';
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
/* What the switch does, in the monitor notice's words: a model call, how often, to whom, and what it falls back
   to. The server's own "What is sent" sentence, naming the destination, stands beside it while the monitor
   is on. */
export const LIVE_HINT =
  'Asks Haiku, through your Claude Code, where the latest turns are heading, about once a minute while this session is on screen. Until a check returns, the level comes from checks and file paths. The level shows here and in the header.';
/* The monitor level's source line: what a Haiku check read, and what it does not say. The estimate's own line
   above stays the line for the level computed from checks and paths. */
export const LIVE_MONITOR_LINE =
  'A Haiku check of the latest turns, about once a minute while you view the session. It reads your goal and the turns it was sent, and says where they are heading, not whether the work met the goal.';
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
/* The same blocker for a reading of the goal alone, where no outcome line was saved. */
export const GOAL_NOT_SHOWN = 'Your goal is not shown by any check.';
/* The verdict's own sentence over a goal-only reading that found nothing: what the reading did find, why
   there is no level, and what would let one be drawn (owner decision, 2026-10-23: the evidence floor stands,
   a level still needs a passing check or, since 2026-10-24, a recorded pull request or skill the line cites). */
export const GOAL_ONLY_NO_LEVEL =
  'Nothing departs from your goal, but no check shows it done, so no level is drawn. Run a check that shows the goal is done (a test, lint or build), then analyze again.';
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
  /* Retired as a reason a new reading carries, kept for the payloads a reading stored before it still
     publishes: they keep the sentence they were stored with. */
  'no-outcome-line': 'No expected outcome line was saved.',
  'goal-unclear': GOAL_UNCLEAR,
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
