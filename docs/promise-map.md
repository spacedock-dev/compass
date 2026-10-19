# What Compass promises

Run as many coding agents as you like. Compass tells you which ones need you, which ones are
fine, and when it is safe to walk away. One local screen, every harness you use, and nothing
leaves your machine that you cannot switch off.

This file says what Compass answers today, what backs each answer, and where each answer stops.
The five promises below follow the questions a reader asks during a day of coding-agent work.

It is written for someone who runs several coding agents at once and cannot see most of them.
Nine or ten terminal tabs, three of them waiting on a question nobody noticed, one burning the
week's quota on the wrong branch.

## How a new user gets there

Four steps, and only the first two are required.

1. Install the plugin. For Claude Code that is `claude plugin marketplace add spacedock-dev/marketplace`
   followed by `claude plugin install compass@spacedock`. Codex, Antigravity and Gemini CLI each
   have a one-line equivalent in the [README](../README.md). There is nothing to install alongside
   it: the server is Python 3.11 or newer and stdlib only, and it runs standalone with no harness
   plugin at all.
2. Say "open compass". A local dashboard opens at `http://127.0.0.1:4553`, and it maps every
   harness it finds on the machine regardless of which one launched it. No account, no cloud
   service, no repository token. The server binds IPv4 loopback and nothing else.
3. Use Intent and drift to compare a session's recorded work with your goal. Open a session, set a
   goal and press `Analyze drift`. The `How Intent and drift works` button explains the steps, the
   reading's limits and why an expected outcome line is needed for a drift level.

   Sessions separates active work from recent history and gives each active
   session its goal beside what it is doing now, plus where it is, what it does next, and whether
   it is blocked. A recorded departure brings a session forward without counting it as active.
   The orientation and how-to stay visible after a session has been checked. Projects, one click
   away, groups the sessions by the label their harness publishes, with active projects first.
4. Optionally connect two things, both one-time and both documented in
   [HOW_TO_USE.md](../HOW_TO_USE.md): the lifecycle hooks that let a blocked session raise a
   desktop notification, and the status-line hook that gives Antigravity its working state and
   forwards its quota.

The moment worth waiting for is step 3, and it is not the layout. It is the first time the board
shows you a second agent that has been blocked on you for eleven minutes while you were watching
the first one. No single harness can tell you that, because no single harness can see the others.

## The five questions of a day

The columns below are the narrative spine of the user journey, in the order a day actually hits
them. Each one gets one promise, the shipped capability that backs it, and the limit that keeps
the promise honest.

### P1. Which of my agents are running?

**We promise:** every session on this machine, across ten harnesses, on one screen, with what is
active now kept apart from what is only recent history.

Backed by the ten-harness collector set (Claude Code, Codex, Pi, Gemini CLI, Antigravity CLI,
GitHub Copilot CLI, OpenCode, Cursor CLI, Goose, Factory Droid), a one-line description of what
each session is, the Projects view that groups sessions by the label their harness publishes, and
the active-versus-recent split that shipped with the session operations board in 0.19.

Where it stops: a row counts as active only when its harness published evidence that it is. A
recorded departure may bring an idle session into the first group without adding to the active
figure. A recent observation cannot prove that a harness is still open, so history keeps identity and scope
and makes no claim about live state. A harness with no local session data shows as discovered but
disabled rather than silently missing.

### P2. What is it doing, and when should I come back?

**We promise:** for each live session, what it is doing now, what it plans next, how far into the
current turn it is, and an estimate of when that turn ends. It tells you when that changes instead
of making you poll. The first screen sets your goal or a permitted prompt beside current activity
and brings recorded departures forward. The session page tells you once what a reading sends and
where, and you can turn it off, without steering it for you. Open a session, set a goal and
press Analyze drift. The How Intent and drift works button beside Intent explains the steps and
the limits; Not enough recorded yet is normal until you add an expected outcome line.
On Claude Code sessions, you can turn on a live drift estimate in the panel and header after every
turn, based on recorded checks and file paths rather than the meaning of your intent. An analysis
shows its level, each outcome line against the recorded work and what the agent said with its
source, where files were written, and why a result is stale. Recorded checks and file paths include subagent work, labelled
as such.
Reader-requested readings are capped at 100 attempts per rolling twenty-four hours. With no saved
goal, a check adopts the goal drafted from your first Claude Code or Codex prompt (your latest
where no first one with a time is published); the goal field also offers your latest prompt.
Adopted words are marked, and missing source times refuse adoption.
Claude Code and Codex hooks also report matched destructive command shapes; a match does not
prove success. Compass saves a stage you choose for a Spacedock workflow and alerts once when
it observes an entity enter that stage; gaps and unavailable sources are stated, and a
notification request does not prove a banner appeared.

Backed by the current-turn elapsed and ETA estimate with its progress bar, the warning that fires
when a request runs or is projected to run past fifteen minutes, a pill per subagent carrying its
measured elapsed, its own model and its own liveness, with a teammate that has finished or gone
quiet still listed rather than dropped, session detail that leads with a drift block setting your goal beside the agent's current activity, the recent token output rate, the model each
session is running on, desktop notifications on a state change, and a goal and an expected outcome checklist
you can type against one session and read back beside the goal its harness published, each on its
own row with its own source, alongside every observed entry naming that session. Course also saves
one stage-entry condition per observed Spacedock workflow, with rule management in Projects after
the source disappears. The first qualifying entity trips it once until Rearm; first sight and gaps
establish a baseline, skipped stages imply nothing, and notification service acceptance does not
prove a banner appeared. See [workflow stage conditions](design-tripwires.md).

The Claude Code live monitor is off by default and remembered for the session in your browser.
It calls no model and raises no notification. An analysis result keeps the source beside each
outcome line, groups written paths by folder, and states whether your words changed or new work
arrived after it. Both levels are recomputed from the evidence and are never stored.
A current result offers no rerun button; new work or changed intent gives one `Analyze again`
control with that reason. A finding's `Show cited entries in Full activity` button opens that
section and jumps to its entries, loading older record pages for one not yet listed, marked with
the finding's words and their current numbers. Departure
citations keep the neutral `Cited` tag.

The Intent log brings every board session and retained annotation/discard record into one list,
with typed goals/output, cached deterministic goals and published workflow titles labeled
separately. Sessions with no goal or project still appear. An unavailable annotation store does
not hide the board or its other sources. Saved derivations carry their observation time, or an
explicit unknown, and say their currentness has not been checked. The list performs no analysis
and reads no model goal as deterministic evidence. Workflow titles come from the existing
attachment; a missing title or a disabled source supplies no goal. Withdrawal still removes typed
words and readings, while separately labeled independent sources can remain.

Claude Code and Codex after-tool hooks add fixed command-shape reports to session detail and
Attention. They show what a hook matched while you were away; they do not establish success.
Reports are incomplete, may repeat, and last only for the current dashboard run. Missing hooks
and unmatched commands can look the same. The exact forms and limits belong to the security
section linked below.

Where it stops: Compass reads a tool call's name and whether it failed, and reads what it
contained only at the few places
[SECURITY.md](../SECURITY.md#irreversible-actions-hook-side-destructive-shape-matching) names, each
reduced to a short summary as it is read. A plan and a question are the two that reach the board: a
plan title from Claude, and up to 64 plan steps with their statuses from Codex. DEC-5 lifted that
boundary in part on 2026-09-02 rather than confirming it, and SECURITY.md is where the current line
is drawn.
An ETA is an estimate, and it says so.

Your words are yours. You can ask for a model reading against them after you allow it on the
session page, unless model calls are off for this run. Claude Code reads a Claude Code session when
it is installed, and Codex reads it when not; both are enabled by an acceptance, not by a passed
check: the captain's of Codex on 2026-09-14 and the owner's of Claude Code on 2026-10-02. The reading
states the evidence it read and its limits;
the evidence remains readable beside your words without asking for one.
Demonstrated work results are read on Pi, which the work evidence states under itself rather
than leaving an empty list to read as no work done.
On Claude Code, the observed record lists the checks a session ran and the files it wrote, with what
the harness recorded as each check's result
([DEC-23](design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work)).
That includes subagent checks and writes, labelled by their source. A pass older than the part of
the work record read cannot reassure, and incompleteness alone establishes no departure. The live
estimate reads checks and file paths, not the meaning of your intent; too little evidence reads
"Not enough recorded yet"
([DEC-26](design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)).
A reading includes them by default and names them, with their destination, in the notice its
first press shows; Turn off readings or `--no-observer-model` stops them. Where Compass cannot name
that destination it sends none and says so. A recorded pass is what the
tool reported, never an inspection of the work, and a reading labels it that way; a result the
record does not carry reads as not recorded rather than as a pass.

### P3. Is anything waiting on me?

**We promise:** one queue of everything blocked on you, with what it is waiting for and how long it
has waited. A session can also ask you a question directly and wait for your answer.

Backed by the merged gate queue with a keyboard pass over it, the wait reason surfaced without
opening the session, the standing wait duration, a control on the row that copies the command which
puts you back in the waiting session, a second one that raises that session's terminal where
Compass can reach it, and the ask lane: a session calls one tool, the question lands
on the dashboard, the answer goes back, and the session continues. An arriving
question raises a notification rather than sitting there unseen.

Where it stops: six of the ten harnesses can report a wait: Claude Code, Codex, Copilot, Cursor,
OpenCode and Pi. OpenCode requires its project adapter and covers parent permissions only. Pi
requires its adapter on 0.85.1 and covers extension UI prompts in persisted sessions, excluding
startup trust. Both need events enabled and lose standing observations on restart.
The other four have no gate detection, so the board names that coverage
gap rather than letting a quiet row read as an all clear. What each can say also
differs: Claude names the gate, Codex says one is open without naming it, Copilot says whether a
command or a URL is being asked about, Cursor says only that a permission request is standing and
for how long. OpenCode and Pi report a wait without its contents; resolving one proves neither
approval nor tool success. The re-entry command is narrower again: two of the ten, Claude Code and Codex,
publish a session id their own CLI takes, so a row from the other eight offers no command rather
than a guessed one. Raising the terminal is narrower still, and on most rows it is not offered at
all: the session has to be running under tmux, to have started while this server has been up, and
to have exactly one terminal attached, or Compass declines rather than guessing which window you
meant. A raise moves what that terminal displays and does not bring its window to the front of your
desk. Where no raise is offered the queue says how far the feature reached rather than repeating
the absence on every row, and the copy control is what remains. Compass does not answer a prompt
for you. The one shape it is allowed is the session asking and Compass
answering, as the [ask lane design](design-ask-lane.md) describes.

Compass can now check a session against your words while you are away and raise a departure
without being asked, which is off by default and the only thing here that spends your model capacity
with nobody watching. Where it stops is the part worth reading: it raises a departure and never a
reassurance, because an unasked "this looks fine" is the output the evidence-floor ruling called
most damaging and it is worth nothing to someone who is not at the desk. It sends a check only
under your Codex "Allow and analyze" for where the words go now, so it never sends where a press
would ask you first. It stops at a per-session
and a per-day limit, and a spent limit is stated rather than passed over, because a session nobody
checked and a session checked and found clean are the two things you cannot tell apart from an empty
board. The sentence is about your words rather than about the machine's history, so a check whose
words you have since taken out of the boxes reads as not checked against what you are asking for
now. And turning the switch off stops new checks without retracting the old ones: what was already
raised still shows on the session, in the review and in the Intent log, under a line saying nothing
new is being checked.

What was raised is reviewable rather than only raised. The session page's drift block collects, in
one place, the departures a reading you asked for produced, the departures the checks run while you
were away produced, what became of the raise, and the figures, with a tmux raise beside each
departure where it exists; the Intent log carries a line per session
saying what was raised against the words on it, and keeps that after the row leaves the board.
Where it stops is the follow-up. What came after a raise is derived from later checks in the same
store, so the common answer is that no later check has read the session, and the board says that
rather than leaving a blank that would read as nothing having gone wrong. Where a later check did
run, the sentence says what that check found and never that the raise caused it, and it says a
later check ran rather than that it read newer evidence, because the store records when each check
ran and holds no evidence bound to support the stronger claim. A raise goes on quoting the words it
read, and where those words have since moved to a later revision the row says so, in the same
wording the reading block uses, so the number on the row has a second source beside it. A raise
whose revision was never recorded keeps saying that and is never given today's. The figures are five
labelled lines with no arithmetic between them: the departures each of the two collections raised,
counted from the rows it renders, and the board's raises, attempts and hand-overs. A figure nobody measured says
so rather than reading zero, which covers the switch being off with nothing on record and the away
checks never having read this particular session. An empty list is the same value in either case.
With the switch off and raises on record the figure is the rows the review actually drew. A count identifies a
session
worth reading and settles nothing about whether the brief, the agent or Compass's own judgement
was poor.

A notification the board raised now carries what became of it, so a signal that never left the
machine is not read as one you ignored. What it can say stops at the hand-over: on macOS the
scripting bridge exits zero under Do Not Disturb and with the hosting application's notifications
switched off, so the record says the notification service accepted the request and never that a
banner was drawn or that you saw it. On Linux and Windows there is no server-side backend at all,
and the page may report that it has a notification lane of its own. That is a statement about a tab
being open, not about a raise reaching you.

### P4. Will I hit the wall before the work finishes?

**We promise:** your quota in one place across vendors, with each window's budget shown against its
own clock, so you can see whether there is room before you start rather than partway through.

Backed by the capacity strip, which reads five harnesses by three different routes. Claude and
Cursor are fetched from the vendor with the harness credential once you have answered the
disclosure, Codex and Copilot are read from files they already write to disk, and Antigravity
forwards its own figures through a status-line receipt. Each window shows how much of its allowance
is spent against how much of its time is gone, the pace that comparison implies, when the budget
runs out at that pace, and when the window resets. Beneath it, what the remaining budget buys in
minutes at both paces Compass has measured, and how long sessions have actually worked in the
project that consumed the most measured working time on this machine. On top of that sit
per-model sub-limits.

Where it stops: what a vendor exposes is what you get. Claude, Codex and Antigravity publish
five-hour and weekly windows, Cursor publishes its monthly billing cycle, and Copilot contributes
per-session AI Units with no percentage because its entitlement is not stored locally. Cursor
fetching is macOS only, and Cursor's cycle has no published start, so its row shows a level and no
clock. There is no per-session cost figure anywhere on the board, and no ranking of which session is
burning fastest right now: every rate the board publishes is a mean over one ten-minute window, and
it names that window rather than claiming an immediacy the arithmetic does not have.
Credential-backed fetching happens only once the disclosure is answered, `--no-usage` refuses it for
a run, and the token is never written, logged, or served. Quota that is expired, rejected, missing,
or stale is withheld rather than rendered as zero.

**Compass never tells you that you are going to overrun.** It puts the budget's end time beside
the window's reset time and leaves the comparison to you, including on the day they are ninety
seconds apart. There is deliberately no single safe-to-start light and no likelihood: every quota
producer signals failure as an empty list, so a composed verdict reads green exactly when Compass
can see nothing.

### P5. Did anything die quietly?

**We promise:** nothing finishes invisibly. Work that finished and was never read is flagged, and a
session that ends leaving uncommitted changes says so.

Backed by the finished-and-unread flag, the mark that separates a turn that stopped from a session
still waiting on a reply that never came, the mark that a session is over so it stops reading as one
waiting at its prompt, kept on disk so what Compass saw end stays ended across a restart of the
board, the note on a row read off disk saying that no turn end can be observed
there, a way to mark a session handled so it leaves the board, and the
end-of-session git probe that shipped in 0.19. And, since the annotation store landed, by what you
typed the session should achieve and produce: the words are kept beside the two end axes, so a
session that ended can be read against what was asked of it rather than only against whether it
stopped. The Intent log keeps them after the row leaves the board. Taking them back is one act
and it is on the board: `discard everything` deletes every revision, deletes any reading of them,
and withdraws the quotations from anything raised against them. What it leaves is the fact that a
check ran and a record of the act itself, carrying no text: the moment you discarded, and the last
revision number that went. That record is why the Intent log still lists the session afterwards,
and why the board can tell a session you discarded from one nobody ever typed against.

Where it stops: nothing reads your words for you at the end. The two axes say what ended and who
claims it finished, drawn separately because neither implies the other, and the comparison against
what you asked for is yours to make. You can allow a model reading from the session page unless
model calls are off for this run;
an acceptance of each provider's checks enables that control (the captain's of Codex, the owner's of
Claude Code). A reading is an account of the evidence, never
verification that the work was done. The words are kept under a
session count rather than a date, so an old enough annotation is evicted rather than expired. The
goal's Clear in the Intent card empties that box; outcome lines have Remove after use. Neither is Discard
everything: the save after a clear or removal keeps every earlier revision, so anything raised
against those words goes on quoting them. The board says which is which where the two controls
sit. And both of those
marks reach only the harnesses whose adapter maps the event that
carries them. An absent mark means no end was observed, never that a session is alive, so it covers
the harnesses with no adapter, a session that predates this server process, and a run under
`--no-events` alike. Of those three, only the first is named on the row: the note is a fact about
the harness, so a Claude row under `--no-events` carries no mark and no note either. The
session-end mark also lapses one row window after the row it belongs to.
A quiet session is published as idle with nothing elapsed behind it: there is no duration threshold,
so going quiet is a state here and not a reading. The row says how long ago the session was last
active, which is a timestamp and never a verdict that it is still open or has closed. The git probe runs one bounded command as a
session ends and publishes two numbers, whether the tree is dirty and how many porcelain entries
changed. Compass runs no program of its own there, though a repository can carry a committed
attribute that makes git invoke a filter driver you already have installed, git-lfs being the common
one, and that driver may then write inside the repository. It is a residual
[SECURITY.md](../SECURITY.md#the-residual-a-filter-driver-can-still-run-and-can-still-write) states
in full. It never publishes a pathname, and `--no-git` turns it off entirely.
Telling a session that died from one that finished is not shipped yet.

## What we do not promise yet

Three of these are the interesting ones, because each is one decision or one release away rather
than a research project.

Walking away from the desk is the promise this map most wants to make and cannot yet. It needs a
session that is genuinely wedged to be told apart from one that is merely quiet, and it needs
Compass to reach you somewhere other than a browser tab you are not looking at. The first half
reaches Claude only: the turn's failure total and the turn where nothing succeeded are published,
and the other nine harnesses record tool failure in no shape this can read. The second half is a
build rather than a call now. DEC-4 ruled on 2026-09-02 that Compass may post a count to an
endpoint you supply, and [SECURITY.md](../SECURITY.md) writes that boundary down before the code
lands.

Gate coverage on the remaining six harnesses is a per-harness measurement job, not a design
question. Today the board is honest about the gap, which is the right behaviour and not the same as
covering it.

Telling a session that died from one that finished is scoped and unstarted.

The [design records](design-next-ui.md) explain the alternatives behind the current interface.
They do not turn a proposed capability into a shipped promise.

## Keeping this file honest

Four rules, and the first one is the whole point.

A promise enters this file only when a shipped capability backs it, and that capability is named in
the same section. Nothing on the roadmap is written here in the future tense.

A cancelled item never becomes a promise. Two were cancelled for exactly the reason a promise would
have been wrong: a composed safe-to-start light that reads green when the data is missing, and a
come-back-later time whose measured lead over simply looking was one minute sixteen seconds.

The limits are part of the promise, not a disclaimer under it. The reason a reader believes the
first four paragraphs of a section is that the fifth one tells them where it ends.

Before and after screenshots are the design record, not the promise. They explain how the interface
got here to people who followed the process, and they belong in
[the session operations board walkthrough](future-ui-exploration/presentations/future-ui-session-operations-board/README.md)
and [the Next UI design record](design-next-ui.md).
