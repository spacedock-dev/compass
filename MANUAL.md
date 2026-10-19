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
```

Paths above are relative to the repository root. For a plugin installation, use the
`server.py` beside the installed `SKILL.md`; [find that copy](HOW_TO_USE.md#find-the-copy-your-commands-will-run)
and use the same launcher and port for start, status and stop. On Windows, use your Python 3.11+
command, such as `py -3`, in place of `python3`. The [standalone binary](README.md#standalone-binary)
takes the same options: run `compass/compass` from the unpacked archive in place of the whole
`python3 …/server.py` command.

## Description

Compass is a Python 3.11+ standard-library server that reads local coding-agent stores and displays
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
`--daemon` with any of those four operations is a usage error.

### Starting and inspecting an instance

| Option | Behavior and default |
|---|---|
| `-h`, `--help` | Print the launcher's current option list and exit. |
| `--port PORT` | TCP port, an integer from 1 through 65535. Default: `4553`. Also selects the instance addressed by status, stop and forget. |
| `--frontend-dev-manifest PATH` | Contributor-only startup ticket for an owned Vite child. Requires foreground operation and `127.0.0.1`; refuses diagnose/forget and disables model calls, quota fetching and native actions. Validates fixture locations and a fresh child handshake before serving. Status/stop do not read the ticket or probe Vite. Use the [frontend development command](CONTRIBUTING.md#frontend-development) to create and own it. |
| `--host ADDRESS` | Accepts only `127.0.0.1` (default) or `0.0.0.0`. The latter exposes the dashboard on every IPv4 interface without authentication. Other addresses and IPv6 are rejected. Read [remote-access risks](SECURITY.md#known-and-accepted) before changing it; prefer an SSH tunnel. |
| `--daemon` | Detach and keep serving after the starting shell exits. Reports the URL, process ID and log path. Without it, serving stays in the foreground. On Windows the launcher starts a detached child; see [platform notes](#platform-notes). |
| `--status` | Report whether Compass answers on the selected port, then exit. Distinguishes a running dashboard, no dashboard, stale state and a port held by another process. |
| `--stop` | Ask Compass on the selected port to shut down and wait for the port to be free. A foreign process is left alone. If nothing is running, remove stale instance state if present. |
| `--diagnose` | Report the local store paths searched, whether they are readable and what was found; exit without serving, writing history or making model calls. Use it first when a harness is missing. |
| `--json` | Format `--diagnose` as JSON. Does not change status output or make the dashboard's normal output JSON. |
| `--window-hours HOURS` | Hide sessions with no activity within this many hours. Default: `24`. Accepts a floating-point number. This display window is separate from history retention. |

### Model use and quota

Analyze drift runs on your press and Codex goal summaries run on a focused refresh. Each tells you
once what is sent and where, again if the destination or content tier changes. Pause model calls stops every model call until Resume model calls;
`--no-observer-model` refuses them at startup. Turn off summaries affects session summaries only,
is disabled while paused, and keeps its saved answer through pause and resume. Unattended checks remain a separate opt-in. A model ID selects a
reader, not proof of accuracy.

| Option | Behavior and default |
|---|---|
| `--observer-model` | Accepted and does nothing in this release; will be removed in a later release. Goal summaries are on by default on a focused refresh. |
| `--claude-reading-model MODEL` | Explicit Claude model ID for Claude readings. Default: `claude-sonnet-5-5` (Sonnet 5.5). The admission floor is Sonnet 5: explicit Sonnet or Opus generation 5 or later IDs are accepted, such as `claude-sonnet-5`. Floating aliases, Haiku and older generations are rejected. An admitted ID must still be available through your Claude Code installation. |
| `--unasked-readings` | Enable bounded Codex checks of annotated sessions without a fresh press; only departures are raised. Off by default. Spends model capacity and requires remembered Codex permission covering the current destination. Quiet hours can suppress checks. |
| `--allow-tool-output` | Accepted and does nothing in this release; will be removed in a later release. Claude Code readings include tool output by default where the destination is named, and disclose it in the notice. |
| `--no-observer-model`, `--no-harness-usage` | Equivalent names for refusing every model call for this run, including goal summaries, reader-requested analyses and unasked checks. Overrides default-on goal summaries and the unasked opt-in. |
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
| `--no-git` | Do not run end-of-session Git probes in session repositories. Dirty/changed fields stay empty; empty is not a finding that the tree is clean. |
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
| `compass-history.json` | Bounded observation history. |
| `compass-ends.json` | Recorded session ends from the event coordinator. |
| `compass-annotations.json` | Saved reader goals, outcome lines, readings and discard records. |
| `compass-summaries.json` | Stored session summaries and word-free source comparison metadata. Independent of annotations; Delete summary removes one session and `--forget` deletes the store. |
| `compass-dismissals.json` | Sessions marked handled. |
| `compass-tripwires.json` | Saved workflow stage conditions. |
| `compass-copied-corrections.json` | Digests recording copied corrections, without their text. |
| `compass-reading-permission.sqlite3` | Reading permissions and model-spend admission timestamps. |
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
| `0` | Help or diagnosis completed; status found a running Compass; serving ended normally; daemon startup or stop succeeded; or forget completed its reading-permission cleanup. `--stop` can succeed when no instance is running. |
| `1` | Status found no running Compass, or startup/stop/forget failed or was refused. A foreign process is not stopped. |
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
[`compass_runtime.cli`](compass/skills/compass/compass_runtime/cli.py), which owns the parser.
`--help` reflects the copy you actually run; this manual follows the repository's current code.
