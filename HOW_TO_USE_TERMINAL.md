# Use Compass from a terminal

Compass runs a dashboard on your machine that reads the records your coding agents, such as Claude
Code and Codex, write about their sessions. Compass calls each agent tool a harness. Its browser view, the board, is at
http://127.0.0.1:4553/. The commands on this page ask the running dashboard and print the answer as
text. Set up your command in [Choose the command to type](#choose-the-command-to-type), then:

```bash
spacedock-compass --daemon     # start the dashboard
spacedock-compass --sessions   # see what your sessions are doing
```

Inside Claude Code you can type an action instead, such as `/compass:compass sessions`
([how](#ask-from-inside-a-claude-code-or-codex-session)). Every option and exit status is in
[MANUAL.md](MANUAL.md); what is read, sent and spent is in [SECURITY.md](SECURITY.md#scope).

Printed paths, errors and session text have terminal escapes and hidden formatting removed.
Joined emoji and complete subdivision flags stay. This also covers `--forget` and diagnostics
from a dashboard running in the foreground. Newlines and tabs inside diagnostic paths and errors
become spaces; report lines and indentation stay. See [terminal output handling](SECURITY.md#scope).

## Choose the command to type

This page writes every command as `spacedock-compass`. Type the command for your copy in its place,
or set an alias so that name works.

| You have | Your command | Needs |
|---|---|---|
| A Homebrew install (`brew install spacedock-dev/tap/compass`) | `spacedock-compass`, as written | macOS or Linux |
| A [release archive](README.md#standalone-binary) | `./compass/compass`, from the folder you unpacked it in | macOS or Linux ([limits](COMPATIBILITY.md#standalone-binary)) |
| The [plugin](README.md#1-how-to-set-up) | `python3 "$SKILL/launch.py" "$SKILL/server.py"`, with `SKILL` set as in [Find the copy your commands will run](HOW_TO_USE.md#find-the-copy-your-commands-will-run) | Python 3.12 or newer ([if yours is older](HOW_TO_USE.md#when-python3-is-older-than-312)) |

To keep the name in every new shell, put one of these lines in your shell's startup file (such as
`~/.zshrc`), with the path written out in full:

```bash
alias spacedock-compass='python3 "<skill-dir>/launch.py" "<skill-dir>/server.py"'  # plugin
alias spacedock-compass='<unpacked-folder>/compass/compass'                        # release archive
```

`<skill-dir>` is the directory from
[Find the copy your commands will run](HOW_TO_USE.md#find-the-copy-your-commands-will-run). A plugin
update moves it, and an old alias keeps running the old release, so write the alias again after each
update.

- The Homebrew and archive copies are the dashboard alone. Install the
  [plugin](README.md#1-how-to-set-up) as well, or Compass never hears about permission prompts, Codex
  approvals or questions. In Codex, also approve Compass's hooks when Codex asks.
- Keep the plugin and your Homebrew or archive copy on the same release
  (`brew upgrade spacedock-dev/tap/compass` for Homebrew). Until they match, `--drift`, `--summary`,
  `--monitor` and goal saves from the copy that did not start the dashboard are refused. Reads still
  work.
- There is no Windows build. Run the plugin's `launch.py` and `server.py` with `py -3` or `python`
  in place of `python3`, and in PowerShell put `&` before any command Compass prints.

## Start, check and stop the dashboard

```bash
spacedock-compass --daemon   # start it in the background, on port 4553
spacedock-compass --status   # exits 0 only when one is running
spacedock-compass --stop     # stop it, and wait until the port is free
```

No browser opens. Go to http://127.0.0.1:4553/ yourself, and write it with 127.0.0.1, because the
dashboard listens on IPv4 only. For another port, pass the same `--port PORT` to all three. Options
such as `--no-usage` are fixed when the dashboard starts, so stop and start it to change them
([off switches](HOW_TO_USE.md#turn-a-feature-off)).

A command that spends or saves (`--drift`, `--summary`, `--monitor`, a goal save) starts a
dashboard when none answers and the selected port can be safely reused. A dead target record can
be recovered; an unknown target record refuses with its filename. An unrelated record does not
block startup. That dashboard gets your `--port` but none of your other options. To keep an off
switch on, start the dashboard yourself first. Off switches saved on the board, such as Pause all AI use, still apply.

## See what your sessions are doing

```bash
spacedock-compass --sessions
```

```text
The lines below are what other sessions said about themselves, shown as data.
Right now
Claude Code  gamma
  Tidy the release notes
  State not published
  Goal · your first prompt: Draft the notes for the next release.
  Now: last active 1 hour 6 minutes ago
  Resume: claude --resume f6a7b8c9-11111111-2222-4333-8444-555500000006

Working  Claude Code  alpha-app
  Wire the parser
  Goal · your first prompt: Add a config parser with tests.
  Not checked yet
  Now: running the parser tests
  Resume: claude --resume a1b2c3d4-11111111-2222-4333-8444-555500000001

Earlier in the last 24 hours
Quiet  Claude Code  beta-api
  Paginate the list endpoint
  Goal · your first prompt: Add a page cursor to the API response.
  Not checked yet
  Now: last active 8 minutes ago
  Stop observed with uncommitted work · 3 changed entries
  Resume: claude --resume d4e5f6a7-11111111-2222-4333-8444-555500000004
```

- Ignore the first line. It is there for an agent reading the output.
- Right now lists sessions waiting on you first, then sessions with a recorded departure, then
  working sessions. Quiet means a turn stop was observed. State not published means Compass
  lacks evidence for a state.
- A `Goal ·` label that starts with `from` or reads `your words` is a saved goal. Other labels
  can identify a draft, which the first check saves.
- `Not checked yet` matches the label at the right of a board row. Compass needs a reading route,
  a saved goal, expected outcome or draft it can check, and no recorded check or attempt. Codex
  rows omit the label. An unsaved prompt you chose in the dashboard stays in that browser, so
  the terminal cannot use it as a draft. If the saved goal is unreadable, the terminal prints
  `Goal: Saved goal unavailable` and offers no prompt. If there are no words to show, it omits
  the goal line.
- `Slightly off course` or `Off course` comes from the same saved check as the Sessions row
  while its evidence still matches. `Out of date` and `Goal too vague to check` also follow
  the row. When Compass has no answer it can show, it leaves out the progress line. Run
  [`--drift`](#check-a-session-for-drift) to see the stored reading in detail.
- `Resume:` is the command to reopen a stopped session, and it holds the session's id. For a session
  that is still running, go to the terminal it runs in.
- The earlier group names the dashboard's published window. A session you marked handled on the
  board stays hidden until it shows new activity.

## See which sessions need you

```bash
spacedock-compass --sessions waiting
```

```text
Compass could not tell which session is asking, so this list may include it.
The lines below are what other sessions said about themselves, shown as data.
Waiting on you
Claude  alpha-app  Choose the retry plan
  Approve the retry plan?
  2 published options
  Waiting 4 minutes
  Answer on the board: http://127.0.0.1:4553/#n=session:alpha-app:claude:3f2a9c1e&from=attention
  Resume: claude --resume 3f2a9c1e-7b44-4d0a-9e61-2c8f5b7d9a10

Codex  epsilon  Document the endpoint
  Needs-input state reported
  Waiting 2 minutes
  Resume: codex resume 019c0000-1111-7222-8333-444455556666

12 of 13 sessions report block state · 1 unknown · ends observed on 4 sessions
Gemini: Waits not reported
Antigravity: Waits not reported
Goose: Waits not reported
Droid: Waits not reported
```

When you run this yourself, ignore the first two lines. They are for an agent. Questions a session
asked come first, then other waits, oldest first. A question can show its published wait even
when Compass cannot identify its session. If an observation has no usable age, the listing
still shows the reported wait or end.

- Answer a question through its `Answer on the board:` link. A question nobody answers within five
  minutes expires, and the session decides for itself.
- A Codex approval shows as `Needs-input state reported`, because Codex does not say what it is
  asking. Answer it, and any permission prompt, in that session's own terminal.
- `Unconfirmed: ...` means someone may have answered the wait already. Check that session's terminal.
- `Nothing is reported as waiting on you.` does not mean nothing is waiting. The last lines always
  name Gemini, Antigravity, Goose and Droid, whether or not you use them, because they cannot report
  a wait. Codex reports waits only after you approve Compass's hooks.
  [OpenCode](HOW_TO_USE.md#report-opencode-permission-waits) and
  [Pi](HOW_TO_USE.md#report-pi-extension-prompts) report them only after you set them up.

On macOS the dashboard also shows a desktop notification when a session starts waiting on you. On
Linux and Windows, run this command, put the count in the
[status line](#show-waiting-sessions-and-drift-in-the-status-line-claude-code), or send a
[reach nudge](HOW_TO_USE.md#reach-nudges-away-from-the-desk).

## Find a session's id

Commands about one session take `--session claude:ID` or `--session codex:ID`. Copy the id from the
session's `Resume:` line in `--sessions`, as in `--session claude:5d0c8a2e-9b31-4f6e-a2c7-1e4b8d3f6a90`.
Inside a Claude Code session, a command without `--session` uses that session. `--summary` and
`--monitor` work on Claude Code sessions only. For a Codex project brief, pass `--session codex:ID`.

## What costs a model call

| Command | Calls a model |
|---|---|
| `--sessions`, `--project`, `--goal`, `--footer`, `--plan-slice`, `--forward-usage`, `--pause-model-calls`, `--summaries off`, `--monitor --off` | Never |
| `--drift`, `--summary` | Only when nothing is stored yet |
| `--summary --update` | Only when the session changed |
| `--drift again`, `--summary --again` | Every time, unless one is already running |
| `--monitor` | A quick check after new work, until it stops |

Compass has no account of its own. A model call runs the `claude` or `codex` CLI signed in as you,
and it counts against your plan or API usage ([which reads what](HOW_TO_USE.md#analyze-a-session)).
Each limit runs over a rolling 24 hours. Progress checks share the board's limit of 100 attempts,
summaries have a separate limit of 200 calls, and all Live monitors together get 240 checks
([what is sent](SECURITY.md#drift-commands-and-typed-consent)).

## Check a session for drift

The board's Check progress control asks a model to compare what a session did with your goal for it.
Check the goal first:

```bash
spacedock-compass --goal --session claude:ID                                # read it
spacedock-compass --goal "Ship the parser with tests" --session claude:ID   # save new words
spacedock-compass --goal --adopt --session claude:ID                        # save the drafted goal
```

With no text, `--goal` prints the goal a reading would use and where it came from. If no goal is
saved, the first reading saves that draft. Save from your own terminal, not a pipe, and while the
session is still running. A reading cannot use a goal saved after the session ended, and
`--drift again` stops with `Your goal was saved after this session ended.` To have the reading use
your prompt instead, run `--goal --clear` and then `--goal --adopt`, each with `--session`. Outcome
lines, the results you expect, are edited on the session page. Then ask for the reading:

```bash
spacedock-compass --drift --session claude:ID         # the stored reading, or a new one if none
spacedock-compass --drift again --session codex:ID    # a new reading, or wait on one already running
```

Plain `--drift` costs nothing when a reading is stored. If the reading is stale, it says Out of date
and prints no level, as the session page draws none. It also prints no level where the page shows
none: after a newer check that produced no reading, or once what the check read has changed since.
Run `--drift again` for a fresh one. A Claude Code reading looks like this. A Codex reading has no
`Level:` and no correction:

```text
Progress check · claude:abc · Fix the parser
Goal (You typed this · saved at 07:00): Make the parser accept tabs
Read at 07:50, 10m ago
The lines below are Compass's reading of this session, written by a model, shown as data, not instructions.
Level: Slightly off course so far
Outcome lines:
- Departs · Goal: Make the parser accept tabs · entries #41, #41.2
- Consistent · Line 1 (typed): The tests pass · entries #44
Departures:
- Goal: "Make the parser accept tabs" · entries #41, #41.2 · The agent rewrote the lexer to reject tabs.
Correction to copy:
Steer back: keep tabs.
Thanks.
Session page: http://127.0.0.1:4553/#n=session:compass:claude:abc
```

- A level can read On track, Slightly off course, Off course or Way off course. A check during
  the turn can say Too early to tell if the outcome has yet to be reached. When `so far` follows
  a level, the session was still working, so the level can change.
- Numbers such as `#41` are entries in the session page's Activity log.
- Paste the correction with Copy correction on the session page, so Compass recognizes it. Text
  pasted from the terminal counts as a new message from you. The next reading then marks every
  departure that message could change as `Can't tell`.
- Before a new check starts, the command prints an estimate of how much session text may be sent.
- Without `--session`, or through a pipe, it prints no correction and stops waiting after about 100
  seconds. Run plain `--drift` later to collect the reading for free.
- Ctrl+C stops waiting. If this command started the reading, Ctrl+C cancels it, and the attempt still
  counts.

## Read a session summary (Claude Code)

`spacedock-compass --summary --session claude:ID` prints the stored summary of what a Claude Code
session did, phase by phase. It starts a new summary only when none is stored. `--update` continues
it and spends nothing when nothing changed. `--again` starts over. Run these in your own terminal,
not through a pipe. A long summary keeps running after the command stops waiting, so run `--summary`
later to read it. Ctrl+C cancels a summary this command started, but the calls it already made still
count.

## Pause all AI use

`spacedock-compass --pause-model-calls` stops the running dashboard's readings, its summaries and
every Live monitor. `spacedock-compass --summaries off` keeps summaries off for every session, even
after you resume. Run it before you pause AI use. Choose Resume AI use on the board to resume.

## Keep the Live monitor on without a browser (Claude Code)

The Live monitor asks Haiku, through your Claude Code, whether the latest turns are following your
saved goal. It checks only after new work, at most about once a minute, and it writes nothing into
your session. An agent reply without a new prompt also counts as new work. Inside the session,
type `/compass:compass monitor on` or `monitor off`. The start uses one turn there; subsequent
checks run separately. From another terminal, first run `spacedock-compass --sessions` and copy
the full id from the session's `Resume:` line, then run:

```bash
spacedock-compass --monitor --session claude:ID
spacedock-compass --monitor --off --session claude:ID
```

A start from another terminal needs no typed command and adds no turn to the watched session.
The start prints the exact stop command, including the full id. If it starts a dashboard, it says so.
Successful starts inside a session put this announcement on stdout so the skill shows it; failed
starts report it on stderr. A repeat reads only this session's
[lease metadata](SECURITY.md#the-live-monitor). If a valid reply says it is off, or only browser
holders remain, the command stops the stale helper and attempts a new start. Browser holders stay
running. A missing or malformed terminal-holder flag, a timeout, a busy dashboard or an unreadable
reply leaves the helper running. A helper that cannot finish stopping is never replaced.

- A monitor started from a terminal keeps running after you close that terminal. It stops when any
  of these happens, and it does not restart by itself:
  - you run `--off`, which leaves a board tab's monitor running
  - the session ends, or, for a monitor started inside the session on macOS or Linux, Claude Code
    exits
  - you choose Pause all AI use
  - it reaches its check limit
  - your Claude Code settings change so that two checks in a row are refused
    ([what to check](HOW_TO_USE.md#when-claude-code-settings-stop-a-check))
  - the dashboard stops or restarts
  - two hours pass with nothing new
- It raises no notification. The [status line](#show-waiting-sessions-and-drift-in-the-status-line-claude-code)
  can say `Live monitor on`. To check from another terminal, run
  `spacedock-compass --footer --session claude:ID` with the full id from the `Resume:` line.
  After the monitor stops, the line may give a reason for five minutes.
- Save a goal with `--goal` first. If none is saved, the monitor saves the drafted goal
  ([what it sends](SECURITY.md#the-live-monitor)).

## Show waiting sessions and drift in the status line (Claude Code)

`--footer` prints one line for Claude Code's status line, such as
`Live monitor on · 2 waiting · waits not reported for Droid · 5h 82% resets in 2h 9m`.
It can show:

- whether the Live monitor is on or AI use is paused
- the departure level shown on this session's Sessions row while the saved evidence still matches
- how many other sessions are waiting on you
- which harnesses have an active session but cannot report a wait
- your tightest quota window

It gets its session from the status line, from Claude Code, or from `--session`. A steady board
can leave the line empty. Open the session page or use `--drift` for a stored progress check.

[Set it up](HOW_TO_USE.md#show-waiting-sessions-and-quota-in-the-claude-code-status-line).

## Read your project's brief

`spacedock-compass --project --session codex:ID` reads the project brief for a Codex session.
For a Claude Code session, use `--session claude:ID` or omit `--session` inside that session.
If Compass sees both a Claude Code session and a Codex thread in the shell, use `--session`
to choose which one to read.

The brief lists the project's sessions, the current task, your latest instruction and what is
running now. It ends with a `Needs you:` line, which reads one of these:

- `NEEDS YOU`
- `CHECKING`: an agent has something to look at, or Compass did not see every session
- `CONTINUES`

Parent and waiting-child lines follow the same 160-character field limit as session titles;
longer fields end with an ellipsis.

Sessions are grouped by project name. The Quiet count includes only observed turn stops.
For a Spacedock workflow, a technical line explains the workflow roles.

Run the command in your own terminal to keep the output there. If an agent runs it as a tool
call inside a session, other sessions' words can reach that session's model provider.
[What can reach into a session](SECURITY.md#what-can-reach-into-a-session).

## Preview the plan summary

Use `spacedock-compass --plan-slice` from the session's working folder to see the plan text the
hook would provide using the current settings. To inspect a specific lane, pass its brief slug
with `--lane hull`. With no flag, `COMPASS_LANE` takes precedence over the folder match.

The preview works with the dashboard down. Lane state and progress show what a dashboard last
saved, and read "not measured" when no dashboard has read the plan in the last 24 hours or since the
settings changed. Empty
output means the [summary is off](HOW_TO_USE.md#give-a-new-session-its-lane-summary), the plan
could not be read, or Compass could not select a single lane. `--plan-slice` runs on its own:
with any option but `--lane`, `--no-plan` or `--no-update-check`, such as `--stop` or `--port`,
it stops with a usage error. Codex can act on hook context without quoting it.
Use the preview to read the text directly.

## Ask from inside a Claude Code or Codex session

In Claude Code, type an action after `/compass:compass`: `sessions`, `sessions waiting`, `project`,
`goal`, `drift`, `drift again`, `summary`, `summary update`, `summary again`, `summaries off`,
`monitor on`, `monitor off` or `pause`. With no action it starts the dashboard and opens the board.
[What each prints](HOW_TO_USE.md#ask-compass-from-inside-a-session).

- If Claude Code asks permission, do not choose "Yes, and don't ask again". That option offers
  `python3 *`, which approves every `python3` command.
- The actions that spend are `drift`, `drift again`, the `summary` actions and `monitor on`. They
  call a model only when you type them yourself, as your whole message. Do not run them in `/loop`
  or on a schedule ([typed consent](SECURITY.md#drift-commands-and-typed-consent)).
- Each action is a turn of your session's model. Its answer stays in the session's context and goes
  out with every later turn. For `sessions`, that includes other sessions' titles and goals. For
  frequent checks, use a separate terminal or the status line.
- If `drift` or `summary` returns before the result is ready, type the plain action later to collect
  it without spending again. This works even if you first typed `drift again` or `summary again`.
  `drift` never prints the correction here, so copy it from the session page.

In Codex the actions are `$compass sessions`, `sessions waiting`, `drift` and `drift again`. Codex's
sandbox can block them, with `Compass's connection to the dashboard was blocked by a sandbox or permissions.`
If that happens, run the command in your own terminal, and add `--session codex:ID` for `--drift`.

## What only the board does

Each command prints once and exits, and it sees only saved state. The board updates itself. Use the
board to do these things:

- answer a session's question, or mark a session handled
- bring a session's terminal to the front
- show sessions older than 24 hours, and search and filter them
- see token rate, ETAs and every harness's quota
- edit a correction or your outcome lines
- use Check progress for harnesses other than Claude Code and Codex
- summarize a Codex goal: choose `Summarize this session` in the project's technical details. The cited session summary is Claude Code only
- choose Resume AI use, or turn summaries back on
- read the Plan page: goals and their lanes, open asks, product decisions, tracker items and
  diagrams from your plan files. `--diagnose` reports refused plan settings and sources;
  [set up the plan board](HOW_TO_USE.md#set-up-the-plan-board) says how

[How it works](docs/how-it-works.md#finding-your-way-around) tours the board.

## When something goes wrong

| You see | Do this |
|---|---|
| ``Compass is not running; start it with `...`.`` | No dashboard answered and no state file was found in this command's state folder. Run the printed command if none is running. |
| `Compass: no dashboard answered at 127.0.0.1 on port ...; state folder: ...` (or `ports ...`) | A recorded dashboard may run outside this command's network, in a container or sandbox, on another machine, or with another port or state folder. If the page works, run the command from that dashboard's terminal. The named state files are preserved. Reads offer a start command if Compass is no longer running; startup can recover a local crash record. A refused startup instead asks you to verify the dashboard is gone in its original environment before removing only its state and origin files. Automatic startup checks only its target port; legacy cleanup and reboot recovery have the [documented limits](SECURITY.md#process-lifecycle-written-paths-and-apishutdown). |
| `Compass: port 4553 is already in use.` after `--daemon` | A dashboard is probably running already, often one a command started for you. Run `--status` to check, or run `--stop` and then `--daemon` to restart it with your options. |
| `No exact session has active evidence right now.` | Nothing was active in the last 24 hours, or Compass is not finding your harness's sessions. Run `spacedock-compass --diagnose`. |
| `Compass answered, but its session list could not be read.` | The list is not empty. Run the command again. |
| `Compass has no session claude:ID on the board ...`, `This session is outside the current board ...`, `This session could not be read unambiguously ...`, or a session is missing from `--sessions` | The id may be mistyped. The session may be older than 24 hours, marked handled, or on another dashboard. It may also be too new to be on the board yet: wait a few seconds and run it again. |
| `... was given no ... session id ...` or `The session must look like claude:SESSION_ID, with no spaces.` | Add `--session claude:ID` or `--session codex:ID`, with no space after the colon ([find the id](#find-a-sessions-id)). |
| `Saving a goal needs an explicit --session and terminal stdout.` | Run it in your own terminal, with `--session` and no pipe. |
| `Nothing has been typed for this session...` or `This session opened with /clear...` | The refusal leads with the checked session id and its page URL. Save a goal on that page, then retry. A local command such as `/clear` provides no first prompt to draft from, even if work followed it. Goals stay with the session they were saved on; another session's goal is not used. To read another session, open its page or run `--drift --session claude:ID` in your own terminal ([find the id](#find-a-sessions-id)). |
| `Your goal was saved after this session ended.` | Run `--goal --clear` and then `--goal --adopt`, each with `--session`, to read the session against your prompt. |
| `Compass could not confirm that you typed the command, ...` or `Summary request refused (typed-command-required)` | From a shell, run it in your own terminal with `--session` and no pipe. Inside a session, type the action yourself, as your whole message. |
| `Compass refused this Live monitor start.` inside a session | Type `/compass:compass monitor on` yourself, as your whole message, inside that session. |
| `Compass refused this Live monitor start.` from your own terminal with `--session` | Run `--sessions` and check that this session is live and on the board. Check that the dashboard allows annotations (`--no-annotations` refuses a start), and that any drafted goal could be saved. Then retry from that terminal with the full id. Empty or HTML refusal bodies still mean refused; a malformed successful reply means unreadable. |
| `Compass could not read the board to find this live Claude Code session.` | The dashboard replied, but its reply could not be read as the requested session or lease. A repeat leaves the running helper alone. Check that your command uses the same Compass copy as the dashboard, then retry. This is different from a missing session or a timeout. |
| `Another monitor command is still running.` | Another command for the same session has kept its command lock past the 204-second wait. That wait covers finding or starting the dashboard, the monitor reads, replacement and helper readiness, including failed-worker cleanup. Polling can add up to 0.05 seconds, apart from OS scheduling delays. Wait for that command to finish, then retry. |
| `Compass could not start or stop this terminal's Live monitor.` | The helper could not finish starting or stopping. A start waits up to 35 seconds for readiness, then allows up to 18 seconds to reap its own worker. Check the dashboard and retry. `--monitor --off --session claude:ID` stops a leftover helper without a board read. |
| `Compass: the dashboard did not answer in time ...` during a monitor command | Each lookup, lease read, start request or check-in has a 30-second whole-exchange bound, including retries while busy. Wait for the dashboard to finish collecting and retry. A timed-out repeat keeps its helper running. |
| `A Codex project brief requires an explicitly selected session.` | In your terminal, run `--project --session codex:ID` with the full Codex session id from `--sessions`. |
| `Compass summarizes Claude Code sessions only.` | `--summary` and `--monitor` take Claude Code sessions only. For a Codex goal summary, use `Summarize this session` in the project's technical details on the board. Codex sessions get no cited session summary. |
| `Compass's connection to the dashboard was blocked by a sandbox or permissions.` | A sandbox, such as Codex's, blocked the local connection. Run the command in a terminal outside it, and add `--session codex:ID` for `--drift`. |
| `The dashboard has every connection in use, so nothing was sent; try again in a moment.` | The dashboard is running but all of its connections are open at once, often many sessions asking together. Wait a moment and run the command again. |
| `The running dashboard is version X and this is version Y, so nothing was sent.` or `... refused this request as outdated ...` | Y is the copy you typed. Inside a session, that is the plugin. If Y is older, or the message says `outdated`, update that copy (and your alias) and run your command again. Do not run the printed commands, because they would restart the older release. If Y is newer, run the two printed commands to restart the dashboard, then update your other copy. Add `--port` to both if the dashboard is not on 4553. Inside a session, run `spacedock-compass --stop` in your own terminal, then type `/compass:compass`. |
| A hint names `spacedock-compass`, which you do not have | Use your command from [the table above](#choose-the-command-to-type), or set the alias. |

[Troubleshooting](HOW_TO_USE.md#troubleshooting) covers missing harnesses, an empty board and the
ask tool. [Ports and a second dashboard](HOW_TO_USE.md#move-it-ports-a-second-dashboard-and-where-state-lives)
covers a dashboard on another port.
