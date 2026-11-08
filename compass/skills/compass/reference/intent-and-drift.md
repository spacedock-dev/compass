# Intent and drift reference

Return to [start, status and stop](../SKILL.md#start).

### Marking a session handled

The dismissal API remains available for integrations, but the dashboard does not currently expose
handled controls. A mark made through `POST /api/dismiss` removes that session from published
counts until anything in it writes again; a subagent write counts. Marks live in
`compass-dismissals.json`. Delete that file to clear them all, call the endpoint with
`{"clear": false}` to restore one, or run with `--no-dismiss` to leave the store unread for a run.

### Recording what a session should achieve

You can record a goal and an expected outcome against one session, in your own words. The
expected outcome starts with one optional empty line and holds up to six lines, each at most 240
characters. The goal is a three-row box of at most 1,000, so a prompt you choose as the goal fits whole. Both are optional and set independently, and saving one
leaves the other alone. Open the session's page: the fields are the first thing in its drift
block, for a session with or without a project. The how-to beside Intent says what an analysis
reads and that Compass never writes into the session. Each box shows how many of its characters (1,000 for the goal, 240 for a line)
you have used as you type, and a hint under the goal box says what to write there. The Intent card shows the saved reads-from line beside its status word, and keeps `Clear` and `How Intent and drift works` in its `More` menu.
The Expected outcome sits in an accordion under the Goal, labelled "Expected outcome (optional) · up to 6 lines" and closed until it has something to show: it opens by itself over saved lines, a line being edited, a pending later direction, or a departure that cites a line, and a close you make holds until one of those arises again. Inside it each outcome line has `Remove`, and `Add a line` sits under the list; Add adds another until there are six, where it stays
on the page, refuses a seventh and says why (replace or merge a line instead). `Save intent` stays
visible and saves the drafted goal or your edits. `Undo changes` is drawn beside it, inert until there is a goal edit or prompt
choice to undo. The list saves as a whole, and Escape puts the stored words back. Each saved line shows where it came from: typed, or added from an entry. A
reading reads each line on its own and shows one row per line.

`POST /api/annotate` with a harness, a session id and `goal` or `lines` (a list of strings, the
whole checklist) does the same thing without the page; `expected_revision` refuses a goal or a list
saved from a view of an older revision (the page sends it with both and keeps what you typed), and
a seventh line or a line over 240 characters is refused rather than clipped. `"read_from_now": true` beside them, or beside `adopt`, opens a new reading window as a first save does; without it a save over saved words keeps the window it had. It writes a numbered revision; an earlier revision is never edited, so anything citing
revision 1 still means what it meant. Send `{"clear": true}` to forget a session's words entirely
(beside `expected_revision`, a discard naming an older revision than the stored one is refused
and takes nothing; the page's Discard everything sends the revision it had drawn when the discard
was armed, so words another tab or dashboard saved after the warning was shown stay, even once a
refresh has drawn them here),
or `settle_through` with a timestamp to mark the directions given up to that moment as settled
against the current baseline. The reply says what happened: `persisted` is whether the words are
on disk, and `outcome` is which of six things the store did — `stored` (a new revision),
`unchanged` (the same words again, so no revision was minted and `persisted` is still true),
`refused` (the request named nothing the store would take, such as a settle on a session with no
words, or a list saved without the revision it was drafted against, and nothing was written),
`unwritable` (the write failed, so the words are held for this run only; or the entry could not
fit the store even alone, so nothing was written and nothing is held), `untrusted` (the store
file exists and could not be read whole, so nothing was written over it, and the page says so
in place of "nothing typed" until the file is moved or repaired) or `unreadable` (this session's
own entry was saved by a build that can read more than this one, so it is kept as it was and not
saved over). A save may send `origins`, the saved position each line came from, so two lines that
share text each keep their own source. The page draws a different sentence for each, and
re-saving the same words never mints a revision. `add_direction` with a fact id from the session's
record, `text` and `expected_revision` adds a later direction you gave as a line marked as added
from that entry, settling it in the same write; the fact must be your own message, later than
your intent and still in the part of the record Compass reads. At six lines it needs `replace`,
the position of the line it takes the place of. Over an unsaved draft, `adopt` with
`expected_prompt` and `expected_prompt_at` adopts the draft in that same write, and `adopt` beside
`settle_through` and `expected_revision` keeps your intent without analyzing; it never adopts over
a saved goal holding other words.

They are held in `compass-annotations.json`, bounded by how many sessions carry words and how many
revisions each keeps rather than by age, because a session still on the board should not lose what
you asked of it because time passed. Delete that file to clear them all, or run with
`--no-annotations` to leave the store unread and unwritten for a run.

Binding is per session, and the board says when it is not exact. Where a harness publishes only a
short identity prefix, another session sharing that prefix would share these words, and the row says
so rather than leaving you to assume otherwise.

Below the two fields the Drift section holds the run control (or the question about a later
direction), the reading and the departures on record. Notes about your saved words are in the
Intent card under the save. The agent's current activity leads Full activity, and the session's entries follow it,
numbered. The departures section appears only with `--unasked-readings` on, or once a reading or a
departure is on record. How it landed follows the session's own facts further down. With saved
words the list starts at the entry where their evidence window opens; earlier entries are
counted and not listed, and with nothing saved the whole record is listed. A Claude Code session's
numbers are fixed: #1 is its oldest message, a message keeps its number as the session grows, and a
check or file is numbered by the message it follows and its place after it (#41.2). Other harnesses
number what the page holds, from the oldest. The measured line
gives the count, in Full activity when the session is blocked and otherwise in the header,
and leaves it out when the record was not read. It lists the twenty most
recent entries in the window, the ten most recent messages the agent wrote, every check and file in
the window and every later direction still to settle, each at its own number, and says how many it
counted and did not list. An entry a departure cites is flagged "Cited" and always listed, and a direction you
gave after saving is flagged "A later direction you gave", which records no finding. In a Claude Code
session a message you sent while the agent was working, and your answer to its multiple-choice question, are
directions you gave too, at the time you typed or answered. Numbers are
worked out again on every render. Each cited entry's number on a finding opens Full activity,
scrolls to that entry and marks every entry the finding cites with its saved words and their current
numbers, and tints each of those rows so it stands apart from the list, without requesting another
analysis. An entry it cites that is not loaded yet is read from older record pages first; one no
page returns is named as not loaded, and focus goes there instead. Escape or "Back to the finding"
returns focus to the number. A finding that cites nothing resolvable says so and marks nothing.
On a harness without fixed numbers, a check that re-runs or a file written again moves the entries
after it. Each entry shows who wrote it, its own type and the source that published it, and the
list states the limit under it: demonstrated work results are read on Pi, and on
Claude Code, and on Codex from codex-cli 0.149 (its subagents' read from their own rollouts), the
record also lists the checks a session ran and the files it wrote, each result as
the tool reported it and counted from the whole transcript read (a project's own test, lint or build script counts as a check
when its body is a known runner, read from the commit the session began on, so a script the session edited counts for nothing;
a command you list for the project in `compass-project-checks.json` under the Compass home also counts, and the page marks it "counted because you listed it"), every other command that is not a
read with its exit status and the words "Compass does not know what it checks" (an exit of 0 may settle a
line, and one that cannot fail, such as `echo` or an exit a trailing `|| true` forces, never does; a test or lint run told to exit zero or to run nothing, or started under a changed search path or startup variable, or after the session set its package manager's script shell, is one of these commands), and what the agent said, each of
its messages an entry marked "Agent said". A reading you press for sends the agent's messages as
evidence of what it said and claimed, each redacted and up to 1,000 characters, except the newest
reply the transcript records as ending its turn, which goes whole up to 16,384 characters. The
prompt names a measured crop's excerpt length and full reply length, and may use remaining room
after your messages have had their share. Compass never stores or
shows more than the first sentence; an unasked reading sends none of them. The notice names
the content sent. It includes those checks by default, with the last 180 characters each printed,
the paths of the files written, every other command as its masked line and exit status (with its output only when the reading runs on Claude Code itself), the repository and number of a pull request the session created and the names of skills it used, for the destination named beside the button, and sends none where Compass cannot name that destination. On every other harness those
entries are instructions, dispatches and gate decisions and never an inspected file, test or
deliverable. Pressing Analyze drift also reads one pull request's CI checks from GitHub with your own `gh` login, when your goal names the pull request by its URL or a Claude Code session records one for the repository its folder points at. GitHub is sent the repository and the number, or, where a pushed branch is what bound it, the repository and that branch's name, and nothing else of the session, and the notice carries one line about it. Checks still running, no completed check and a pull request head past the session's commit settle nothing, unless the pull request was merged by a commit the session's folder already holds, when its checks count and the card says it was merged into the session's branch; skipped checks count as neither a pass nor a failure; a missing or signed-out `gh` is said beside the reading, as is a session with no recorded folder (a harness that records none, or a transcript that cannot be found), where nothing is launched. Where GitHub names required checks, only those count and the card says how many others it left out. A GitLab merge request your goal names by its URL is read the same way through your own `glab`, only on a host `glab`'s own configuration names, and no session record binds one. Its checks and head are worded as a merge request's, one 60 second deadline covers the whole read, and a login stored by `glab auth login` is what it uses: `GITLAB_TOKEN` is not passed on, and a configuration only under `GLAB_CONFIG_DIR` is not followed. `--no-ci-read` or the page's switch turns it off. Your words also appear beside the goal the harness published,
in the project view's Latest instruction card (Published instruction when undated), each on its own row so the two claims are never merged, and
the derived row says when the directive was observed.

Long caveats keep their claim on the page and put the rest behind a summary you can open, on both
the session page's drift block and Console. Nothing is removed by that: an opened one stays open when the board redraws,
and a closed one still holds every word it was written with.

A goal-less Claude Code or Codex session arrives with its goal drafted from your first prompt, as
Compass publishes it, or from your latest prompt, marked "latest", where no first prompt with a
time is published. A session that opened with a harness control such as `/clear` drafts nothing,
not even the latest prompt, and says there is no first prompt to draft from, so you type a goal.
A line above the box says where the words came from, "Drafted from your first prompt · not saved", and an
excerpt adds "Shortened here; Analyze reads the whole prompt"
(the goal keeps the excerpt, and a reading reads the prompt it came from whole, up to 1,000
characters, or says in what it read that it could not), and the box is tinted: nothing is saved until you press Save intent, edit the box and save, or
press `Analyze drift`, which adopts the draft. `Use your prompt` lists up to five of your own
prompts, and choosing one fills the goal box for you to save. While no goal is saved and no `/goal` was detected, `Find goal` beside it reads the prompts you typed in the session, on your press only, and fills the box when it can quote your own words for a goal: it says "Found in your prompts at" the time and the prompt entries it quotes, each a link to that entry in Full activity, and editing the words replaces it. It sends your prompts to the model Analyze names, counts against the same daily limit, is refused while model calls are paused, and says so beside the button when it finds nothing clear. Analyze drift, Keep and an added line's save are refused
while the goal box or the outcome lines hold an edit you have not saved, because each would stand
on words that are not on screen; your edit stays in the box. No drift level or pill is drawn over
an unsaved draft. Once a goal is saved, "Saved" names the window's opening time and holds when the words were saved. Editing the goal, using a prompt or a later direction as the goal, and adding or editing outcome lines all keep that window, so work already done toward the earlier words stays read. `Read from my latest message`, beside Save intent over saved words, saves and opens a new window at your latest message, and says so with its time. A `/goal` Claude Code gave up on, or the reader cleared, ends that goal: the Drift card says a give-up as the harness's claim with its time, never as met and never as a level or a check, and the Intent card says under the Goal field that an earlier `/goal` was replaced, met, given up or cleared, with the time and never its words.

A direction you gave after your intent (after the saved goal's words, or after the drafted prompt)
is asked about before the press, in the control's place: "Your 11:05 message adds:" quotes the
selected message whole under the time you sent it (the newest is preselected; you can choose another),
and of several the page says how many you sent after your goal and lists them all, each by its time and
opening words, in the Direction picker above the quote, which holds only the one the buttons act on. Compass reads
those words when the question is drawn, so each choice acts on its first press. Nothing there decides
whether it changes what you asked for: that is yours, and Compass does not write into the session
either way. `Leave it` settles them through the newest one shown, adopting a draft in the same write,
says no analysis was started, and starts none; `Analyze drift` stays beside the choices and does not settle
anything. `Add as a line` opens the selected direction's first sentence as a pending line under
Expected outcome, marked "not saved", with the hint "Write the rule, not the moment.", for you to edit;
the one `Save intent` saves it, after any unsaved goal or line words, and settles through that direction
only, so the question comes back for any later one: a line over 240 characters is refused rather than
clipped, and at six lines you choose the line it replaces. `Make it the goal` fills the goal with that
first sentence and the same hint, asks whether to keep standing outcome lines with two buttons, and waits for
Save intent. A saved line names when you said it ("added from your 11:05 message"). Add on an activity entry
opens that listed direction too. The prompt menu resolves choices when opened. An unsettled direction at
or before a stored reading demotes its intent rows; a later message labels the reading as preceding it.

Delegated work has no line on the Drift card. An unpaired launch followed by thirty quiet
minutes in the last turn adds an At-risk item and a question to copy into the session, and that
item names the recorded launches and their clocks. Missing or partial attribution says Compass
cannot see all the work; a missing count is not zero. It records no finding about whether a
process is running or finished.

A reading you asked for states its departures once, in its result. What the checks run while you
were away raised is reviewed under `Raised while you were away: N`, drawn only where they raised
something (with those checks on and nothing raised, their one sentence saying whether the session
was checked stands in its place), and that is the one place on the session page a raise appears.
Each row carries the annotation revision it read against and where its evidence stopped. Where the
words have since moved to a later revision the row says so, in the same wording the reading block
uses, and a raise whose revision was never recorded is not given today's number. Under them sits
what became of that lane's raise, and a raise with no delivery record on file says that rather
than showing nothing. Each raised constraint carries what a later check found, derived from later
checks rather than from a second reading: the usual answer is that no later check has read the
session, and where one has, the sentence says what it found and never that the raise caused it. The
figures beneath are one line per collection — the departures the reading raised and the departures
the away checks raised, each counted from the rows shown beside it — then the board's raises,
attempts and hand-overs, with no arithmetic between any of them. A count identifies a session worth
reading and settles nothing else, and where the away checks have never read the session the figure
says it was not measured rather than reading zero. The goal's `Clear` in the Intent card empties that box, and
the save after it keeps every earlier revision, so the raises quoting those words stay. Discarding
the whole annotation withdraws them and deletes the session's summary, stopping one being written
first: the quotations go from the departure record too, and what
stays is the fact that a check ran and a record of the discard itself, holding when it happened
and no text at all. That record is why a discarded session still has a line in the Intent log,
and why the board never describes it as a session nobody typed against. That act is the `Discard everything` control, in the Intent card, behind the summary of the same name and offered only
where a revision is stored; it takes two presses, and between them the board names what it will
delete (the revisions, any reading and the summary), what it will withdraw and what it keeps (the
record that a check ran, and session history, which `--forget` clears), and when the offer lapses. The result names only what happened to the summary: gone, none stored, still stored, or unreadable. Where it is gone or was never there, it says a finished session opened again writes a new one unless summaries are turned off. That sentence is the control's own description, and it is
written to the page's live region when the first press arms it, so it reaches a reader who is not
looking at the screen. Beside each raised departure sits the raise that selects its tmux pane
where available, whatever state the session is in; it does not bring the window forward or send
anything to the session. Resume commands are available on Attention, the waiting panel and the
project rail. The Intent log carries the same raises a line at a time, and keeps
them after the session leaves the board.

Sessions labels your typed goal beside NOW, or shows the prompt the session page drafts ("GOAL ·
YOUR FIRST PROMPT", or your latest where no first one is published) from Claude Code or Codex;
other harnesses show typed words only, and a session that opened with a harness control shows "Add
a goal". A slot without a typed
goal opens the session page with the cursor in its goal field. Showing a prompt does not save it.
A recorded departure adds a Drift mark with its age and moves the session after blocked sessions
and before working ones, even if it is idle; it does not add to the Active now figure. Earlier
revisions say the words have moved, and legacy readings without a reading time say the age is
unknown. Consistent readings add no mark or rank, and there is no drift total. With annotations
off the slot has no link and there is no Drift mark; the screen explains that once.

One thing here evaluates on a cadence, and only when you turn it on: the `Live monitor`, from the session page's Drift settings or the `monitor on` terminal action. The page switch is off by default and not remembered across reloads. With a visible page or a terminal holder, a Claude Code session is checked by Haiku through your installed Claude Code about once a minute after new work. The Drift card and the page header then show the level that check gives (None or low, Medium, High or Extreme, or Not enough recorded yet), labelled `Live monitor · Haiku` with the time of the check and one sentence on where the latest turns are heading. Each check sends your saved goal and the recent turns, redacted: your messages, the agent's replies, the commands of checks with their result, every other command as its line with its exit status, and the paths of files written, and no tool output. It names what it sends and where when you turn it on, says nothing of whether the work met your goal, and its accuracy check has not been run yet, which is why the label names the model. An Analyze reading outranks it, and the estimate described next shows whenever the monitor has no level: before its first check returns, and when it is paused, capped or has failed. A browser holder stops when you turn it off or leave the session, and pauses checks while the tab is hidden. After 20 minutes it asks "Do you still want to monitor this session?" and drops that browser holder, with a note, if nobody answers within 10 minutes. A terminal holder asks no question and keeps running without a tab; `monitor off` stops that holder alone. Session end, a lost dashboard connection or Pause model calls ends terminal monitoring too; `--no-observer-model` refuses it. It has its own limits, 30 checks per session in a 30-minute window (fixed accounting buckets for a terminal holder) and 240 per rolling 24 hours across the board, apart from Analyze's 100 attempts; it never appears on a Sessions row, raises no notification and never feeds the unasked lane.

The estimate is the level worked out after every turn from the recorded checks and written paths against your saved intent, with no model call, labelled `Live estimate` with the time it was computed. It says where it last rose ("Rose from Medium at #12"), recomputed each time and never stored, adds a nudge to analyze only for a cited High signal after your last message, and shows the level in the page header beside the entry count. An older failure blocks None or low and keeps its name and age; a failure followed
by file writes reads Medium at most until a re-run. Recorded signals show the cited entries and
their event times; its line says it reads checks and file paths, not what your intent says, and that files written by
shell commands, such as a build, are not seen. Limits of this estimate names gaps such as an intent that names no folder.
At Not enough recorded yet, the reasons sit once under Why not None or low, while that folder
limit stays visible. A broader explicit passing run can retire a
covered failure in the same directory and execution context. A folder counts only when it exists
in the session's known working directory or holds a recorded write. Over an unsaved draft it reads "Save your intent to see a live estimate" and there is no
pill. It never appears on a Sessions row, raises no notification, and never feeds the unasked lane.
Drift marks show departures already on record, from a
reader-requested reading or the optional unasked lane. With nothing typed the block says there is nothing to read against; with the observer
model off it gives that reason; otherwise it states what a reading may and may not read and offers
the ordinary one-call control, `Analyze drift`. When it cannot run it stays on the page, refuses the press, and
names one next step, and a press on it opens "Why Analyze is off" with the whole reason, except where no reader is available on this machine: then the reason stands
where the control would be. An acceptance of each provider's checks enables that control (the
captain's of Codex's case review on 2026-09-14; the owner's of Claude Code on 2026-10-02, after its
scored runs failed): a
Claude Code session is read by Claude Code when `claude` is on PATH and by Codex otherwise, and the
evidence stays readable
whether or not you ask for a reading. A press that waits on the server shows a spinner and a busy
label ("Saving…", "Starting…") and takes no second press until it is answered, and when Analyze
opens or closes on its own a line under it says so and why. A press starts an analysis the server runs in the background,
and while it runs the control is replaced by an "Analyzing drift" box listing its real steps
(preparing what is sent, waiting for the named provider, checking the reply), the one under way
marked, with the attempt count and disclosure still beside it. A screen reader hears "Analyzing drift" once
when the box appears and how the analysis ended once when it goes, never again on a redraw or reload. The box comes from the published
board, so a reload or another tab shows the same analysis at the same step, and a second press
starts nothing. The result, or why there is none, replaces the box when it is stored; an analysis
a stop or restart cut short is recorded as an interrupted attempt. On a Claude Code, Codex or Pi session the
result shows the analysis level (worked out again from the stored reading on every view, never
stored, never on a row) with its time. A level above None or low is drawn only beside a departure the
reading shows. With none, the card draws no level or bar, and the answer says what the reading did
find and, where every line is consistent but the level is held back, why. The live estimate is not
drawn beside a reading that stands, and where the switch is on and it has a level to draw, the card
says so. A reading that could tell nothing about a session only minutes old says it is early and to
read again once the session has run its checks. The header pill adds "so far" while the session runs.
A departure that an earlier reading found and the next one does not is named once on that reading,
whether it was the only one or one of several: two departures that become one name the one that went.
The answer follows: "Departs from your intent" with a count and
each departure's own account under a departure, otherwise a failed check after your last message
that a later pass of the same check, in the same directory, did not follow,
"Can't tell", "Not reached at this stop", or "Nothing found against what it read". Coverage beside it names a measured partial
message tail, unlisted passes or writes, checks that did not fit and an adopted-source fallback. The read
sentence also counts the other commands the session ran (session-wide from a scan that read the whole transcript,
or "at least" that many when the scan began late, because it was cut from the tail or an unread subagent
transcript moved where it starts, or a named subagent left no transcript to count),
how many were read-only, and says Compass did not read what they did; an older reading says that count was not recorded.
An older reading says coverage was not recorded. A tail starting inside the intent window tags
every intent row "may be in the part not read"; claims stay independent. On Claude Code an Analyze
press reads the session's messages back to the window start where it can, and says where it stopped
when it cannot. How much a press keeps and sends is set on the page's Settings screen: the largest
prompt (512 KB by default, optionally up to 2,048 KB), how many of the session's messages and checks it keeps (2,000), how
many checks and written files it lists (1,000), and how much of the session's and its subagents'
transcripts it scans for them (512 MB), which is where delegated work runs its tests. Prompt size
limits one Analyze drift prompt, not the outline or Summary's source coverage. Settings shows
each route's estimated allowance separately from the saved limit. The session's Next Analyze
prompt line shows the current route's allowance outside any stored assessment; it describes the
next press, not what an earlier reading covered. Neither estimate confirms model availability
or fit. An assembled prompt above that allowance is refused before a model call,
without automatically shortening it or switching providers. A smaller actual prompt may still
pass when the saved limit is higher. Unknown or unusable estimates say so, and a tiny allowance
does not ask you to save below the 16 KB minimum. The project
page keeps its own 100 events and 12 checks and scans 8 MB. A check that `&&` joins ahead of a later
check whose own summary ends the output counts as passed, since the later one only ran because the
earlier one exited 0. Checks separated by `;`, each cut by `tail`, each take their own summary line
in order, but only when there is exactly one such line per check and the last ends the output; a
bare unittest `OK` counts when the command names the tests it runs. When nothing departs and the
goal line rests on what the agent said, green pull request checks that count (on the session's
commit, or merged into its branch) are enough for a level of None or low. An idle Claude Code or Codex session whose last turn has no recorded finish is read up to
its last recorded entry, and the result says so with that entry's time, never as a final verdict. A Codex session that finished a turn is read through that turn, from the finish its own record shows or from its Stop hook. General scope and the
count-by-kind cutoff remain under What the analysis read, which groups the model, your intent, the
session read and what is never read under their own headings. Coverage holds only counts, time and closed state
tokens and changes no verdict. A departure is a card whose What gives each cited entry as one line in its own words with its number (the
agent said, you said, a failed check, a file write), with no Evidence or Source fold; the claims row and every quiet row do the same, and a number opens Full activity on that entry. Each other line reads "Consistent with
#n, as the tool reported; not inspected", "Consistent with what the agent said at #n; not a
check" where it rests on the agent's messages alone, "Consistent with what the session said at #n;
not a check", "Not reached at this stop" or "Can't tell · <your line>" with its own reason under it; the result's own words never say "Done" (an agent message it cites is quoted and attributed to the agent). A line that rules out a folder, or limits the work to one, departs on a file write the record holds
there, whatever the reading said; a recorded passing check that covers a line is cited ahead of the agent's
message on it, which it does only where the line claims that kind of check's result ("the tests pass"), never for a line that merely names the subject ("the lint config is left alone"). Unfinished work in flight
at a non-final stop has its own result and cited explanation in view, where the record shows that line's work under way: a check or write that bears on it, or a call still running. A line only a message says is coming reads "Can't tell". It raises no
departure, Medium level or Steer back offer, and cannot establish None or low. An unkept promise
to continue or finish, a needless wait on you or a stated remainder of the asked-for set still
counts as departure. While a turn is open, a departure that rests on messages alone is stored as not
reached at this stop when a call is still running (a Claude Code session only: the call is read from
its transcript, and no other harness has one to read), or when a check or write that bears on the line is
recorded after them (a line that names a path or claims a check's result is borne on only by a check
that covers it or a write to that path); a departure on a failed check or a write, or one with nothing
running or recorded after it, is not stored as not reached. An idle session with no recorded finish reads the same way, but
no call counts as running there: an unanswered call is an interruption. A line may read consistent on one of the
agent's messages, never beside a check that failed after your words or a file write the record holds:
there the goal and each line need a check, CI command or CI check that passed, a pull request created
or a skill used, and a command that only ran, or a file write cited, is neither. A passing check covers a line only when every clause that says how a check came out leaves its kind of check unqualified, before or after ("the tests pass", not "the frontend tests pass" or "tests for the parser pass"). A line departs only on recorded work, a failed check or a write the record settles, and on
messages alone reads "Can't tell"; a line that is only a ban on pushing ("Don't push to main", with no condition anywhere in the line) also departs on a `git push` the record shows exited 0 to that branch (any branch, where the line names none), once you wrote it, when the analysis cited that push, and a dry run, a deletion, another branch or a condition anywhere in the line leaves it "Can't tell"; the goal may still depart on what the agent said. A line that only asks for the agent's own account of what it did, found or changed ("Tell me which files changed", not "Tell me when the deploy is green") is the exception: it is judged on the agent's messages, a "consistent" on one sent after the last file write and a departure only where every message was read whole and the newest is cited. The goal reads
consistent only when every line asked beside it does, and the level never reads "None or low" on
the agent's word alone. A goal departure resting on an agent message stops counting once that
message leaves the transcript tail the board reads. A press that carries the agent's
messages also asks whether any of them claims a state of the work (running, merged, passing and
the like) that the record contradicts, or, for a pass, a fix or a file written, that the record
does not show; the reading is asked to keep "not shown" for those, so a claim nothing Compass
records can show (merged, pushed, deployed) is not meant to read "not shown". "What the agent claimed" quotes the claim's first sentence and then reads "is contradicted at #m", "is not shown by the record" (with its own reason: which kind of check the claim names and what the record holds of it, or, for a claim naming none, that the record read is the board's recent tail, and never where some of the session's checks, passes
or file writes went unread, or where a check or command that can fail ran inside the window before the claim with no result recorded, unless a later run of that command in the same folder recorded one before the claim; a recorded run only after the claim does not settle it), "is shown at #m" or "Can't tell", and is not
drawn when there was no claim. A check that failed before the claim does not contradict it once
the agent ran the same tool again before claiming, with no failure in that run or an earlier one of it,
naming nothing after the tool but flags or `.`; the working directory is not recorded. A
contradicted claim is said on its own row and sets no level by itself. An unshown claim blocks None or low without raising Medium.
Neither is counted as a departure from your intent or held back by an unsettled later direction.
A withdrawn claim draws no row. Steer back is offered only with a departure from your intent; the server still composes a correction from a claim or a failed check, as an evidence request:
`Can you show evidence for "<its first sentence>" at 14:02?`, or, contradicted,
`You said "<its first sentence>" at 14:02; the record shows otherwise at 14:05.`
Short titles and bare URLs are not quoted in the correction. Times are your local clock, the
correction names no Compass entry number, and a departure cited at one of the agent's messages
quotes that message's first sentence ("where you said …"). While departures are listed, Steer back
is its own section after them, headed "Steer back", with the correction under it labelled "Built from your saved intent and the reading at HH:MM", including once the session is idle; where
a mark or a reading of earlier words withholds it, a line beside the departures says why. "Where the work went" groups the written files by folder, under What the analysis read. The
card header carries one re-run control once a reading exists: "Check again" when your intent changed
after it or new work arrived since, "Analyze again" when it is current. It is inert, not gone, where a press cannot run. The request count stays beside it.
The shared budget is not shown until it is spent; then a banner holds the top of the session page,
naming the limit and the time the next analysis can run. "Mark as inaccurate" marks the reading with
a token that is stored beside it and never sent or counted, and says so beside the control; that
reading no longer sets the level or Steer back until you press Undo. One message where the level was
says so, with Undo and Analyze again beside it, and the reading's verdicts stay below it dimmed as disowned. A later
direction alone offers no correction. A correction puts departures and failed checks first, dates
a time from an earlier day, and asks for evidence where an outcome is not shown. Under each
departure, and a contradicted claim, it carries the analysis's own explanation on an indented
line starting "Why Compass reads this as drift:", redacted, bounded and cleaned so it cannot paste
as a command or a new instruction block. Its button names
the triggering entry and age, and What the analysis read counts new work since the analysis.
The box offers Cancel, which stops the call and records a cancelled attempt that still counts, or one that spent nothing when it landed before anything was sent. A failed request says its result could
not be confirmed and is never retried automatically. The counter reports recorded model requests, so a refusal before the model runs
does not increase it.

### Long analysis

For native Claude Code session sources, `Long analysis options` offers a separate explicit
`Start long analysis` press. Its preview names the saved intent, route, source metadata, limits
and current shared allowance. Opening it reads no transcript bodies, fetches no CI checks and
reserves no calls. Start refreshes the binding; the preview is neither a source-completeness
claim nor a guarantee that the whole plan can run. The model provider is the disclosed route,
which may be Claude Code or Codex; other harness sources do not support this mode.

If Start first saves a drafted goal, that press runs no analysis. Refresh the long preview,
review the saved intent and reading window, then press `Start long analysis` again.

The plan permits at most 16 sequential evidence calls and one final reconciliation call. Each
prompt uses the smaller of the saved ceiling (512 KiB by default, at most 2 MiB) and the route
allowance. All prompts together are bounded at 16 MiB, including repeated context; each reply
at 8,192 bytes. Every reserved call consumes the same 100-attempt rolling daily Analyze allowance,
including failures and late refusals. A final slot numbered 17 is not 17 spent calls. There is
no automatic retry, resume, shortening or provider fallback.

Source collection and analysis share 256 MiB of actual native I/O including verification rereads,
512 pages, a 256 MiB retained object graph and 1,048,576 graph objects (not process RSS), and
60 seconds of preparation and response processing excluding model waits. The whole job has
30 minutes; each model call retains its 180-second timeout. Progress separates source work,
planned and ended evidence passes, reconciliation and actual charge accounting. Exact totals,
known minimums and unknown counts remain distinct; allocations are not provider usage receipts.

Complete admitted messages are masked before splitting. Candidates from evidence passes are
unstored hypotheses, sent to the final call as untrusted navigation; final citations bind original
evidence. Source or pass gaps withhold a new
reading. A qualified partial reading may retain supported local departures on outcome lines,
with Can't tell elsewhere; it cannot establish global reassurance or absence. Strict whole-final
and adopted-goal proofs remain required, so larger limits do not make every session readable.
Synthetic application tests do not establish the model's accuracy on long sessions.

The server runs the requested job across browser reloads, but never starts long analysis on its
own. Cancel requests a stop for that job; Pause and the model off switch stop further calls. A withheld,
cancelled or failed attempt leaves the older reading visible beside the latest outcome; a
qualified partial reading may replace it. Restart markers hold word-free identity, plan and
accounting metadata, not prompts or permission to resume. Refresh the preview before another
explicit Start. Unknown accounting or unconfirmed cleanup stays unknown.

`Unfinished long analysis records` reads the selected session's recovery metadata only on an
explicit open or `Refresh recovery records`, including while model calls are paused. Recorded
state does not prove owner liveness. `Check and discard superseded record` asks the server to
prove a dead terminal owner, exact accounting and a superseded target; it cannot stop a model or
refund calls. A lost or refused reply stays uncertain and never retries automatically. A marker
may be removed while its receipt cleanup remains unconfirmed. `Analysis cleanup unconfirmed`
keeps the long job blocked and the previous reading visible; it is not completion or permission
to start another job.

