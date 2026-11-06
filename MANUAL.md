# Compass command manual

[Synopsis](#synopsis) | [Options](#options) | [Environment](#environment) |
[Files](#files) | [Exit status](#exit-status) | [Examples](#examples)

## Name

`server.py` starts, inspects and stops the Compass coding-agent dashboard.

## Synopsis

```text
python3 compass/skills/compass/server.py [OPTIONS]
python3 compass/skills/compass/server.py --diagnose [--json] [OPTIONS]
python3 compass/skills/compass/server.py --status [--port PORT]
python3 compass/skills/compass/server.py --stop [--port PORT]
python3 compass/skills/compass/server.py --forget [--port PORT]
python3 compass/skills/compass/server.py --footer [--session HARNESS:SESSION_ID]
python3 compass/skills/compass/server.py --sessions [waiting] [--port PORT]
python3 compass/skills/compass/server.py --drift [again] [--session HARNESS:SESSION_ID] [--port PORT]
```

On a `python3` older than 3.12, start it through the `launch.py` beside it
(`python3 compass/skills/compass/launch.py compass/skills/compass/server.py ...`) for a one-line
explanation instead of a traceback.

Paths above are relative to the repository root. For a plugin installation, use the
`server.py` beside the installed `SKILL.md`; [find that copy](HOW_TO_USE.md#find-the-copy-your-commands-will-run)
and use the same launcher and port for start, status and stop. On Windows, use your Python 3.12+
command, such as `py -3`, in place of `python3`. The [standalone binary](README.md#standalone-binary)
takes the same options: run `compass/compass` from the unpacked archive in place of the whole
`python3 …/server.py` command.

## Description

Compass is a Python 3.12+ standard-library server that reads local coding-agent stores and displays
sessions across harnesses. With no operation flag it runs in the foreground until stopped. Open
`http://127.0.0.1:4553/` in a browser, or use the port you selected. `/api/data` serves the session
snapshot as JSON. The launcher does not open a browser for you.

The default bind is IPv4 loopback. Harness stores are read-only; Compass keeps its own observations,
annotations and settings separately. Optional vendor quota requests, model analyses and webhook
nudges have different controls. See [Security](SECURITY.md#scope) for their disclosures and limits.

This file is the command reference. [How to use Compass](HOW_TO_USE.md) owns harness configuration
and setup procedures. The [installed skill](compass/skills/compass/SKILL.md) remains self-contained
for agents that do not have the repository.

## Options

[Instance control](#starting-and-inspecting-an-instance) | [Models and quota](#model-use-and-quota) |
[History](#history-and-annotations) | [Workflow and events](#workflow-and-event-controls) |
[Notifications](#notifications-away-from-the-desk) | [Experimental interaction](#experimental-session-interaction)

Spell every long option in full: an abbreviation such as `--no-hist` is refused rather than matched
to the nearest option. Arguments written in capitals are values you supply. Boolean switches affect this invocation;
leaving an off switch out on a later start enables that feature again without deleting its store.
Pass one operation flag at a time. If combined, the current implementation chooses `--diagnose`,
then `--forget`, then `--stop`, then `--status`; it does not execute a sequence of operations.
`--daemon` with any of those four operations is a usage error. `--version` is checked before all of
them and ignores the other flags, though their values must still parse. `--sessions` is checked
next and uses only `--port`. A lone `--version` or `--sessions` is answered before the dashboard's
modules load; beside any other option it goes through the full parser, which is what checks those
values. `--footer` is a client operation too: alone, or with its own `--session`, it is answered
before the dashboard's modules load, and beside any other option it is a usage error. `--drift` is
checked after `--sessions`: alone, or with `again` and its own `--session`, it is answered before
the dashboard's modules load, and beside any other option it uses only `--session` and `--port`.

### Starting and inspecting an instance

| Option | Behavior and default |
|---|---|
| `-h`, `--help` | Print the launcher's current option list and exit. |
| `--version` | Print the Compass version alone on one line and exit. The standalone binary prints the release it was built for. `server.py` prints the version of the plugin it sits in. Exits `1` with a message when an installation records no version. Alone, it answers without loading the dashboard. |
| `--footer` | Print one status line segment and exit `0`: the number of other needs on the Attention queue (sessions waiting on you and pending asks), the harnesses that cannot report a wait, and the tighter of the five-hour and seven-day quota windows with its reset. It reads the JSON a Claude Code status line passes on standard input and the line file the running dashboard keeps for that session, makes no request and starts nothing, and prints nothing when it cannot tell. Alone, or with `--session`, it answers without loading the dashboard. [Set it up](HOW_TO_USE.md#show-waiting-sessions-and-quota-in-the-claude-code-status-line). |
| `--session HARNESS:SESSION_ID` | The session `--footer` or `--drift` reports for, such as `claude:SESSION_ID`. Default for `--footer`: the `session_id` on standard input, then `CLAUDE_CODE_SESSION_ID`; for `--drift`, `CLAUDE_CODE_SESSION_ID` alone, since its standard input is not a status line. A value that does not parse prints nothing for `--footer` and one sentence for `--drift`. Valid only with `--footer` or `--drift`. |
| `--port PORT` | TCP port, an integer from 1 through 65535. Default: `4553`. Also selects the instance addressed by status, stop and forget. |
| `--frontend-dev-manifest PATH` | Contributor-only startup ticket for an owned Vite child. Requires foreground operation and `127.0.0.1`; refuses diagnose/forget and disables model calls, quota fetching and native actions. Validates fixture locations and a fresh child handshake before serving. Status/stop do not read the ticket or probe Vite. Use the [frontend development command](CONTRIBUTING.md#frontend-development) to create and own it. |
| `--host ADDRESS` | Accepts only `127.0.0.1` (default) or `0.0.0.0`. The latter exposes the dashboard on every IPv4 interface without authentication. Other addresses and IPv6 are rejected. Read [remote-access risks](SECURITY.md#known-and-accepted) before changing it; prefer an SSH tunnel. |
| `--daemon` | Detach and keep serving after the starting shell exits. Reports the URL, process ID and log path. Without it, serving stays in the foreground. On Windows the launcher starts a detached child; see [platform notes](#platform-notes). |
| `--status` | Report whether Compass answers on the selected port, then exit. Distinguishes a running dashboard, no dashboard, stale state and a port held by another process. |
| `--sessions [waiting]` | List the sessions the board holds, in the board's own groups and words: **Active now** (working, waiting on you, holding an exact request, or carrying a recorded departure) first, then **Recent history**. Above any rows, a line says they are what other sessions said about themselves, shown as data; an empty answer carries none. Each row names its harness, project, state, the first line of its goal, how long ago it was last active or ended where the board states one, the stop or end it observed (`Stop observed`, never a claim that you read it) with uncommitted work and the count of changed entries, a departure mark with its age, and the re-entry command where a Claude Code or Codex session published an id its CLI takes. No row names a drift level. With `waiting`, list only what waits on you: each wait in the words its harness published, how long, the re-entry command, and for a question a session asked, the board URL that answers it. Run inside a Claude Code session, that session is left out. When the session cannot be identified (`CLAUDE_CODE_SESSION_ID` unset or not an id), nothing can be left out, and when anyone is waiting a line above the rows, before that one, says the list may include it. With nothing waiting it says so and states which harnesses report no waits, never "all clear". Reads a running dashboard and never starts one: with none running it prints the shared sentence on stderr and exits `1`. Beside other options only `--port` is read. Alone, it answers without loading the dashboard. The `compass` skill runs this as its `sessions` and `sessions waiting` actions; [what that sends](SECURITY.md#what-can-reach-into-a-session). |
| `--drift [again]` | Print one session's drift reading against your goal: the goal and where it came from (typed, or drafted from a prompt, and whether it is saved), when it was read, why it is stale if it is, how many later messages you sent were left unsettled, the level where the page draws one (it draws none over a reading held at Not enough recorded yet), each outcome line with its state and source, and the agent's claims where the reading found one, each departure with your words, the entry numbers it cites and the model's reason, and earlier departures still in view, then the session page URL. A line above the reading says it is Compass's reading, written by a model and shown as data. A stored reading is printed and nothing is spent. With no stored reading, or with `again`, it first prints the route's `Next Analyze prompt` allowance, asks the model for one reading exactly as the page's Analyze does, prints the one-time notice when the dashboard says it is due, shows progress on standard error and waits; Ctrl+C cancels the reading, which still counts toward the day's limit. A reading already running when the command starts, such as one pressed on the page, is waited on and never started twice, `--drift again` included; Ctrl+C then only stops the waiting, says the reading keeps running and names the session page. It settles no later message you sent: as on the page, a departure such a message could change reads as not verifiable. From your own terminal (`--session` given and standard output a terminal) it also prints the composed correction to copy. Anywhere else, inside a session or with its output piped, as an agent's shell tool and Claude Code's `!` mode read it, it says only that one is ready on the session page, so the agent the correction is addressed to never reads it; it also stops about 100 seconds after the command starts, a dashboard it started included, leaving the reading running for a plain `--drift` to collect at no cost; while that reading runs `--drift again` attaches to it rather than starting another, and once it has ended `--drift again` asks for a new one. With too little of those 100 seconds left to hear whether a press started, it sends none and says nothing was spent, and a SIGTERM during the wait, such as a tool timeout, leaves the reading running and says so. Run by the `compass` skill (session named by `CLAUDE_CODE_SESSION_ID`, output read through a pipe), the next steps it names are the skill's `/compass:compass drift` and `drift again`, not `spacedock-compass`, and the line saying it started a dashboard goes to standard output, or above a refusal on standard error. Such a run's press carries the action it was typed as, and the dashboard sends it only when the latest prompt in the session's transcript is that typed `/compass:compass` command, once per typed command; otherwise it refuses with nothing spent. With no `--session`, `CODEX_THREAD_ID` set refuses, because Codex started inside a Claude Code session inherits that session's id. Every refusal the page can show (annotations or model calls off, paused, the daily limit, no route, a session that cannot be read yet, nothing typed, and the rest) is one sentence on standard error, exit `1`, with nothing spent. A reading the dashboard withholds after the press, such as on a route whose managed policy can change at launch, prints the dashboard's own sentence, which says whether anything was sent or counted, below the goal as it now stands: a press over a drafted goal saves it even when nothing is read. A Claude Code session starts a dashboard when none runs and refuses one of another release; any other harness gets one line naming its session page, where the page reads it. The `compass` skill runs this as its `drift` and `drift again` actions inside a Claude Code session; [what that sends](SECURITY.md#what-can-reach-into-a-session). |
| `--stop` | Ask Compass on the selected port to shut down and wait for the port to be free. A foreign process is left alone. If nothing is running, remove stale instance state if present. |
| `--diagnose` | Report the local store paths searched, whether they are readable and what was found, any project script file it skipped and why, and where your list of check commands is, whether it could be read and which entries were ignored; exit without serving, writing history or making model calls. Use it first when a harness is missing. |
| `--json` | Format `--diagnose` as JSON. Does not change status output or make the dashboard's normal output JSON. |
| `--window-hours HOURS` | Hide sessions with no activity within this many hours. Default: `24`. Accepts a floating-point number. This display window is separate from history retention. |

### Model use and quota

Analyze drift runs on your press, Codex goal summaries on Summarize this session in Console, and a
Claude Code session summary when you open a finished session or press Summarize or Update summary.
Each tells you once what is sent and where, again if the destination or content tier changes. Pause model calls stops every model call until Resume model calls;
`--no-observer-model` refuses them at startup. Turn off summaries affects session summaries only,
is disabled while paused, and keeps its saved answer through pause and resume. Unattended checks remain a separate opt-in. A model ID selects a
reader, not proof of accuracy.

Long analysis is a separate page action for native Claude Code sessions, with no new startup
flag. Ordinary Analyze makes one call; an explicit long press allows at most 16 evidence calls
and one final reconciliation call, each sharing the same Analyze rolling allowance. The saved
prompt ceiling still applies within the route's allowance. Individual calls keep the 180-second
timeout; the whole long job is bounded at 30 minutes. Pause, Cancel and `--no-observer-model`
still stop calls. See [the workflow](HOW_TO_USE.md#analyze-a-session) and
[the long-analysis contract](SECURITY.md#long-analysis) for source, preparation and storage limits.

| Option | Behavior and default |
|---|---|
| `--observer-model` | Accepted and does nothing in this release; will be removed in a later release. Goal summaries need no flag and run on Summarize this session in Console. |
| `--claude-reading-model MODEL` | Explicit Claude model ID for Claude readings. Default: `claude-sonnet-5-5` (Sonnet 5.5). The admission floor is Sonnet 5: explicit Sonnet or Opus generation 5 or later IDs are accepted, such as `claude-sonnet-5`. Floating aliases, Haiku and older generations are rejected. An admitted ID must still be available through your Claude Code installation. |
| `--claude-monitor-model MODEL` | Explicit Claude Haiku model ID for the Live monitor's once-a-minute check. Default: `claude-haiku-5-5` (Haiku 5.5). Only an explicit Haiku generation 4 or later ID is accepted; floating aliases such as `haiku`, and every Sonnet or Opus ID, are rejected, and this does not change `--claude-reading-model`. An accepted ID must still be available through your Claude Code installation. The setting takes effect once Live monitor runs the check. |
| `--unasked-readings` | Enable bounded checks of sessions with a typed goal without a fresh press; only departures are raised. Off by default. Claude Code reads Claude Code sessions; Codex reads Codex sessions. On other harnesses an unasked check prefers Claude Code, where Analyze drift prefers Codex; if the preferred provider is unavailable or unqualified on this machine, the other serves. Codex needs the Drift card's "Allow Codex to run unasked checks" toggle for the current destination; Attention points to it when sessions with a typed goal are waiting. Claude Code needs no separate grant; the Drift card names it and lists what each check sends, which on a Claude Code session includes the checks and commands that failed, never one that passed. Analyze and Resume never grant it. Revoking it, Pause model calls and `--no-observer-model` stop checks; Pause followed by Resume clears the grant. Quiet hours hold the notification, not the check. The caps remain three per session, twelve per rolling day, with a fifteen-minute floor. A call that starts and fails counts toward both caps. No effect under `--no-annotations`. |
| `--allow-tool-output` | Accepted and does nothing in this release; will be removed in a later release. Claude Code readings include tool output by default where the destination is named, and disclose it in the notice. |
| `--no-observer-model`, `--no-harness-usage` | Equivalent names for refusing every model call for this run, including goal summaries, reader-requested analyses and unasked checks. Includes session summaries. Overrides the unasked opt-in. |
| `--no-usage` | Refuse vendor quota network fetches and quota pushed into Compass for this run, regardless of the stored dashboard setting. Quota recorded in harness-owned stores, such as Codex or Copilot, still appears. Does not disable model calls or reach nudges. |

### History and annotations

History records what Compass observed. Annotations contain the goal and expected outcome you typed.
Switches below address those stores separately; a port selects an instance, not a separate history.
Dashboards using the same Compass home share persistent stores.

| Option | Behavior and default |
|---|---|
| `--history-days DAYS` | Retain observations for this many days. Default: `14`. Must be finite and greater than zero; fractions are accepted. Narrowing the window evicts older records; widening it cannot recover them. |
| `--history-max-bytes BYTES` | History size and read cap. Default: `1048576` (1 MiB). Must be a positive integer. A history file larger than this cap is discarded unread rather than parsed. |
| `--no-history` | Do not read or write observation history for this run. Existing history is left on disk. Does not disable the separate annotations or session-end store. |
| `--no-annotations` | Do not read or write saved goals, expected outcome lines or readings for this run. The page offers no editable intent fields; `Analyze drift` remains visible but disabled with a reason. Existing annotations are left on disk. Does not govern the separate session-summary store. |
| `--no-dismiss` | Do not read or write the handled-session store. Previously handled sessions return to the board and its dismiss control is unavailable for this run. |
| `--forget` | A one-shot cleanup: delete observation history, recorded session ends, stored session summaries and copied-correction digests; sweep annotation discard records; store model calls as paused, which stops readings, goal summaries and session summaries until you use Resume model calls in the page, and store session summaries as off, which stays after you resume until you turn summaries on again. Preserve the words you typed and unexpired model-spend timestamps. Refused while a dashboard answers on the selected port: stop it first. The deletions are irreversible. |

`--forget` checks only the named port. Stop every dashboard sharing that Compass home before
cleanup; an instance on another port can otherwise retain or recreate observations. It does not
erase harness transcripts or every Compass setting and store.

### Workflow and event controls

These features are enabled by default. An off switch suppresses the named feature for this run.

| Option | Behavior and default |
|---|---|
| `--no-spacedock` | Do not read workflow definitions or show their stage strips. Claude role metadata remains; saved stage conditions remain readable but suspended. |
| `--no-tripwires` | Do not read or write saved workflow stage conditions. |
| `--no-events` | Disable the event coordinator, event overlays and coarse store probe. Fixed-interval collection continues. Also disables terminal focus, command-shape reporting and reading/writing recorded session ends. Observation history is independent. |
| `--no-irreversible` | Disable hook command-shape matching, report ingress and publication. Ordinary lifecycle hints remain available unless `--no-events` is also set. |
| `--no-git` | Do not run end-of-session Git probes in session repositories, and do not read a project's `package.json`, Makefile or justfile from git to count its test and lint scripts as checks. No remote is read either, so no `gh pr checks` or `gh run view` poll counts as CI evidence. Dirty/changed fields stay empty; empty is not a finding that the tree is clean. |
| `--no-ci-read` | Do not read a pull request's or merge request's CI checks from GitHub or GitLab when Analyze drift is pressed. No `gh` or `glab` command runs, and a reading goes without those checks. The page also has a setting of its own; either one off stops the read. |
| `--no-focus` | Do not record terminal identities, publish a focus capability or raise session terminals. `--no-events` also turns this off. |
| `--no-ask` | Disable session-to-reader questions: register, poll and answer routes refuse, and the page offers no ask control. |

### Notifications away from the desk

Reach nudges are off until a URL is configured. Quiet hours have no effect until a window is
configured. Both settings can come from a command-line value, environment variable or file;
see [Environment](#environment).

| Option | Behavior and default |
|---|---|
| `--reach-url URL` | HTTP or HTTPS webhook endpoint for counts-only nudges when sessions need input or finish unread while you are away. Overrides the environment and file settings. No URL is configured by default. |
| `--no-reach` | Refuse off-machine reach nudges regardless of any configured URL. Does not disable other notifications, quota fetches or model calls. |
| `--quiet-hours WINDOW` | Local 24-hour window, such as `22:00-08:00` or `13:00-14:00`. Suppresses non-ask notifications, unasked checks, workflow-condition notifications and reach nudges during the window. Conditions are still evaluated. Direct questions are exempt. Overrides environment and file settings. |
| `--no-quiet-hours` | Disable quiet-hours suppression for this run regardless of the configured window. |

A quiet-hours window includes its start and excludes its end; a window crossing midnight is valid.
Invalid windows or identical start/end times produce no suppression. An invalid selected webhook
URL produces no reach nudges. These are not command-line usage errors, and an invalid nonempty
higher-priority setting does not fall back to a lower-priority one.

### Experimental session interaction

These options configure a prototype. They do not open a session page or attach an arbitrary
terminal. Leave both unset for normal dashboard use. See the
[interaction limits](SECURITY.md#operator-cockpit-prototype) before configuring them.

| Option | Behavior and default |
|---|---|
| `--interaction-origin-session HARNESS:SID` | Select one exact, already-collected session identity for registered read-only terminal output. No session is selected by default. Must be paired with the registration-file option. |
| `--interaction-origin-registration-file PATH` | Write the one-use session-side tmux registration capability to this file. No path is selected by default. Must be paired with the origin-session option; session-side registration is still required. |

## Environment

Use absolute paths for directory overrides. A nonblank harness override is authoritative: Compass
does not also search that harness's default directory. Diagnose the effective paths after relocation.
These are dashboard configuration variables; provider authentication and destination settings are
owned by the installed harness, as explained in [Security](SECURITY.md#observer-model-calls).

| Variable | Effect |
|---|---|
| `COMPASS_HOME` | Move Compass's own state, logs and persistent stores. Default: `.compass` under your home directory. Does not relocate harness transcripts. Use the same value for start, stop, status and forget. |
| `COMPASS_ALLOW_TOOL_OUTPUT` | `1` is accepted and does nothing in this release; will be removed in a later release. |
| `COMPASS_REACH_URL` | Reach endpoint when `--reach-url` is absent; takes precedence over the `reach_url` file in the Compass home. `--no-reach` overrides all sources. |
| `COMPASS_QUIET_HOURS` | Quiet-hours window when `--quiet-hours` is absent; takes precedence over the `quiet_hours` file in the Compass home. `--no-quiet-hours` overrides all sources. |
| `CLAUDE_CONFIG_DIR` | Claude configuration root; Compass searches `projects`, `tasks` and `teams` below it. |
| `CODEX_HOME` | Codex root; Compass searches `sessions` below it. |
| `GEMINI_CLI_HOME` | Parent of `.gemini`, not `.gemini` itself. Relocates Gemini data and Antigravity data below `.gemini/antigravity-cli`. |
| `COPILOT_HOME` | Copilot store root. |
| `PI_CODING_AGENT_DIR` | Pi configuration root; its `settings.json` and default `sessions` directory are resolved here. |
| `PI_CODING_AGENT_SESSION_DIR` | Pi session directory; overrides Pi's `sessionDir` setting and its default sessions directory. |
| `XDG_DATA_HOME` | Base for OpenCode and Goose data discovery. Defaults to `.local/share` under your home directory. |
| `LOCALAPPDATA`, `APPDATA` | Additional native Windows candidates for OpenCode and Goose; see the [platform contract](COMPATIBILITY.md). |

`COMPASS_PORT`, used by hook and MCP clients, does not set the dashboard listener's port.
Pass `--port` to `server.py`; configure its clients to reach that same port using the
[setup procedures](HOW_TO_USE.md#move-it-ports-a-second-dashboard-and-where-state-lives).

## Files

The following files live in `COMPASS_HOME`, or `.compass` under your home directory. The list
covers instance control and the stores addressed above; it is not a complete inventory of caches.

| File | Purpose |
|---|---|
| `compass-PORT.json` | Per-port instance state, including process identity and capabilities. |
| `compass-PORT.log` | Detached instance output and diagnostics. |
| `footer/HARNESS-HASH.json` | One small file per Claude Code session for `--footer`: a count, harness names and a time. Written by a running dashboard, removed when it stops. [What it holds](SECURITY.md#the-status-line-files). |
| `compass-history.json` | Bounded observation history. |
| `compass-ends.json` | Recorded session ends from the event coordinator. |
| `compass-annotations.json` | Saved reader goals, outcome lines, readings and discard records. |
| `compass-summaries.json` | Stored session summaries and word-free source comparison metadata. Independent of annotations; Delete summary removes one session and `--forget` deletes the store. |
| `compass-dismissals.json` | Sessions marked handled. |
| `compass-project-checks.json` | Commands you list as checks for a project. You write it; Compass only reads it. [How to list one](HOW_TO_USE.md#list-a-projects-checks). |
| `ci-read-off` | One-line marker the page's pull request CI read switch leaves while it is off. It is removed when the switch goes back on. |
| `compass-tripwires.json` | Saved workflow stage conditions. |
| `compass-copied-corrections.json` | Digests recording copied corrections, without their text. |
| `compass-reading-permission.sqlite3` | Reading permissions, the model-call pause, the session-summary switch, the one-time notices shown, and the spend admission timestamps for readings and for session summaries, kept apart. Long analysis adds word-free job and per-pass bindings and reservation receipts; these do not authorize resume. |
| `reading-long-jobs/` | Word-free long-analysis owner, plan, pass and accounting markers under the state directory. Recovery preserves uncertain accounting and never resumes model calls. |
| `reach_url`, `quiet_hours` | Optional plain-text defaults for reach and quiet hours. |

See [local-store security](SECURITY.md#scope) for retention, permissions and other persistent data.
Keep logs and state private when reporting a problem; they can contain local paths and capabilities.

## Platform notes

The same launcher supports macOS, Linux and Windows. Native notifications and terminal focus
depend on the platform and harness; see [Compatibility](COMPATIBILITY.md).

On Windows, `--daemon` respawns the server and deliberately omits the unattended-check opt-in
`--unasked-readings`. The compatibility flags `--observer-model` and `--allow-tool-output`
do nothing and need no forwarding. The experimental interaction-origin pair is also not
forwarded. Use foreground mode on Windows when you need those options. Feature-off switches,
port, host, display/history bounds, Claude model choice, reach URL and quiet
hours are forwarded.

## Exit status

| Code | Meaning |
|---|---|
| `0` | Help, the version, a session listing, a drift reading or diagnosis completed; `--footer` always, including when it printed nothing; status found a running Compass; serving ended normally; daemon startup or stop succeeded; or forget stored model calls as paused and finished its summary-store cleanup. `--stop` can succeed when no instance is running. |
| `1` | Status found no running Compass, or startup/stop/forget failed or was refused. A foreign process is not stopped. `--sessions` found no running Compass, or its answer could not be read. `--drift` refused, or no new reading was produced. |
| `130` | `--drift` was interrupted with Ctrl+C: it asked the dashboard to cancel a reading it started, or stopped waiting on one it found running and left it running. |
| `2` | Invalid command-line syntax or rejected values/combinations, reported by the argument parser. |

Diagnosis can exit `0` while reporting missing or unreadable stores; inspect its report.
Forget prints separate outcomes for its stores: exit `0` alone does not prove every file was removed.

## Examples

Run these from the repository root. Replace `4581` with your chosen port. Options for a running
instance are fixed at launch; stop and restart it to change them. The examples refuse model calls
so browsing a session cannot start an analysis; omit `--no-observer-model` when you want disclosed,
reader-requested model analyses.

Show help or inspect discovery without starting a listener:

```bash
python3 compass/skills/compass/server.py --help
python3 compass/skills/compass/server.py --diagnose --json
```

Run in the foreground with a shorter display window:

```bash
python3 compass/skills/compass/server.py --port 4581 --window-hours 6 --no-observer-model
```

List what is running and what waits on you, from any shell:

```bash
python3 compass/skills/compass/server.py --sessions
python3 compass/skills/compass/server.py --sessions waiting
```

Read a session against your goal, then ask for a fresh reading:

```bash
python3 compass/skills/compass/server.py --drift --session claude:SESSION_ID
python3 compass/skills/compass/server.py --drift again --session claude:SESSION_ID
```

Start a detached instance, check it and stop it:

```bash
python3 compass/skills/compass/server.py --port 4581 --daemon --no-observer-model
python3 compass/skills/compass/server.py --port 4581 --status
python3 compass/skills/compass/server.py --port 4581 --stop
```

Keep three days of history with a 256 KiB cap and overnight quiet hours:

```bash
python3 compass/skills/compass/server.py --port 4581 --history-days 3 --history-max-bytes 262144 --quiet-hours 22:00-08:00 --no-observer-model
```

Refuse quota network fetches, model calls and reach nudges for the run:

```bash
python3 compass/skills/compass/server.py --port 4581 --no-usage --no-harness-usage --no-reach
```

After stopping every instance sharing the selected Compass home, clear observed history and
reading permission while preserving typed annotations:

```bash
python3 compass/skills/compass/server.py --port 4581 --forget
```

## See also

- [README](README.md): installation and a product overview.
- [How to use Compass](HOW_TO_USE.md): installed launcher discovery, hooks, MCP, relocation and troubleshooting.
- [Installed skill](compass/skills/compass/SKILL.md): dashboard controls, supported stores and session interpretation.
- [Security](SECURITY.md): data exposure, outbound activity and retention limits.
- [Compatibility](COMPATIBILITY.md): harness and platform support.

The [launcher](compass/skills/compass/server.py) delegates to
[`compass_runtime.entry`](compass/skills/compass/compass_runtime/entry.py), which answers a lone
`--version`, `--sessions`, `--footer` and `--drift` itself and otherwise hands over to
[`compass_runtime.cli`](compass/skills/compass/compass_runtime/cli.py), which owns the parser.
`--help` reflects the copy you actually run; this manual follows the repository's current code.
