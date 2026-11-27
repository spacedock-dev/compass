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
python3 compass/skills/compass/server.py --monitor [--off] [--session claude:SESSION_ID] [--no-update-check]
python3 compass/skills/compass/server.py --footer [--session HARNESS:SESSION_ID]
python3 compass/skills/compass/server.py --forward-usage
python3 compass/skills/compass/server.py --plan-slice [--lane NAME]
python3 compass/skills/compass/server.py --sessions [waiting] [--port PORT]
python3 compass/skills/compass/server.py --project [--session HARNESS:SESSION_ID] [--port PORT]
python3 compass/skills/compass/server.py --goal [TEXT | --clear | --adopt] [--session claude:SESSION_ID] [--port PORT] [--no-update-check]
python3 compass/skills/compass/server.py --set-group LABEL --session HARNESS:SESSION_ID [--port PORT] [--no-update-check]
python3 compass/skills/compass/server.py --pause-model-calls [--port PORT]
python3 compass/skills/compass/server.py --summary [--update | --again] [--session claude:SESSION_ID] [--port PORT] [--no-update-check]
python3 compass/skills/compass/server.py --summaries off [--port PORT]
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

Quiet unanswered tool calls can keep a session Working past the usual 90-second activity window.
Claude Code, Codex and Pi each have a 900-second ceiling, held in the internal
`claude_tool_in_flight_max_sec`, `codex_tool_in_flight_max_sec` and `pi_tool_in_flight_max_sec`
settings. These are runtime defaults, not command-line options or environment variables.
The [session state reference](compass/skills/compass/reference/dashboard.md#session-states)
owns which records qualify and which boundaries retire them.

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
`--daemon` with any of those four operations is a usage error. Terminal operations run before those
four. `--summary`, `--summaries`, `--goal`, `--set-group` and `--pause-model-calls` reject unrelated options before
the `--version` check. Otherwise `--version` ignores the other flags, though their values must still parse. `--sessions` is checked
next and uses only `--port`. A lone `--version` or `--sessions` is answered before the dashboard's
modules load; beside any other option it goes through the full parser, which is what checks those
values. `--footer` is a client operation too: alone, or with its own `--session`, it is answered
before the dashboard's modules load, and beside any other option it is a usage error.
`--forward-usage` is the same, and takes no option at all. `--drift` is
checked after `--sessions`: alone, or with `again` and its own `--session`, it is answered before
the dashboard's modules load. It also accepts `--no-update-check` on that path; beside other options
it uses `--session`, `--port`, `--no-update-check` and the proxy startup options below.

`--summary` accepts `--update` or `--again`, plus `--session`, explicit `--port` and
`--no-update-check`, plus the proxy startup options below.
A plain stored read returns immediately even while a job runs. A new job waits up to 20 seconds
inside a session or 630 seconds at a terminal with an explicit session; a timeout leaves it running
and says how to read it later. Ctrl+C cancels only the job this command started, by its id.
A lost response never retries a spend. A tool timeout or SIGTERM inside a session leaves any
admitted job running and says how to read it later. Summaries retain their existing 200-call rolling-day cap
and per-summary limits of 37 calls, 768 KiB and ten minutes. The first start prints the current
summary notice when it is due; changed content or destination renews it.

`--goal` accepts one mode, its own `--session` and `--no-update-check` before the dashboard modules load.
With `--port` it uses the full parser, which refuses unrelated options.

`--set-group LABEL` requires an explicit `--session` and accepts `--port` and
`--no-update-check`. It works in a shell script with piped stdout. It uses the same annotation
availability and HTTP admission guards as goal saves. A label is at most 40 characters;
`--set-group ""` clears the session's own label so it can inherit a linked parent's group.
Send `group` alone or beside plain goal/outcome fields; combining it with adoption, discard or
reading actions is refused. Saving a group changes no intent revision and starts no model call. With `--no-annotations`, writes are unavailable and saved groups are
not read. Parent declarations and group inheritance are described in the
[session state reference](compass/skills/compass/reference/dashboard.md#launcher-declarations).

`--project` is checked after `--sessions` and before `--drift`. Alone or with its own
`--session`, it answers before the dashboard modules load; beside other options it uses only
`--session` and an explicit `--port`. The project reads share a 40-second budget. The session list has a
30-second deadline, including any older-dashboard fallback; session lookup and project context
each have a 5-second deadline. Session lookup is capped at 1 MiB; the lean list and context
are capped at 16 MiB each. A refused or oversized reply produces no partial brief.

`--monitor` accepts `--off`, `--session` and `--no-update-check` beside it. Without proxy startup options, it answers before loading the
dashboard modules. Each dashboard probe and request has one wall-clock deadline across connection,
headers and body, including a listener that keeps sending a little at a time.

`--allow-host`, `--login-proxy` and `--allow-user` can accompany `--drift`, `--summary`, `--goal`
and `--monitor`, with an optional explicit `--host`. These validated proxy startup options pass
through the full parser and are retained if the operation starts a dashboard. Names alone keep the
loopback bind, which is what a proxy on the same machine needs; only an explicit `--host 0.0.0.0`
opens remote access. An already running dashboard keeps its own
configuration, and a read still starts nothing.

When no dashboard answers, a read exits `1` and prints the start command for this copy: its
Python launcher and server paths, or its packaged executable. Paths with spaces are quoted.
On Windows, the printed command is written for cmd and Bash; in PowerShell prefix it with `&`.
If a sandbox or permissions blocks the loopback connection, the command says so and starts
nothing; a blocked connection does not establish whether the dashboard is running. When a state
file exists but no dashboard answers, the command names the ports checked and state folder,
explains that a dashboard may run beyond its reach, and preserves the record. Automatic starts
are refused in that case. Terminal health probes and `--status` both allow one second per port. Reads
continue to work across installation folders and releases.

Without a resolvable caller, `--drift`, `--monitor`, `--project`, `--goal` and `--summary` name
what they could not do and send no request. They do not ask an agent to supply a Claude Code
session id. `--sessions waiting` still reads the list and says it may include the caller.

If the dashboard cannot build a session's drift view or cannot uniquely identify the session for
it, `--drift` reports that failure and exits `1`, including when the failure appears after a
reading finishes. It prints no reading banner, outcome lines or model attribution. An older
dashboard that supplies no drift-view field gets a separate compatibility refusal.

### Starting and inspecting an instance

| Option | Behavior and default |
|---|---|
| `-h`, `--help` | Print the launcher's current option list and exit. |
| `--version` | Print the Compass version alone on one line and exit. The standalone binary prints the release it was built for. `server.py` prints the version of the plugin it sits in. Exits `1` with a message when an installation records no version. Alone, it answers without loading the dashboard. |
| `--summary` | Print the named Claude Code session's stored summary, stale or partial included: model, local write time, lede, every phase and cited line, freshness, coverage limits and encoded page URL. Start only if absent. Reads never refresh or call a model. Uses `--session`, else the Claude Code environment id; honors explicit `--port`. Starting or updating a summary runs from a real terminal, or from the person's exact typed command inside a session, once. Redirecting or piping output still needs that typed command, even with `--session`. |
| `--update` | Only with `--summary`: continue an appendable or resumable summary. An unchanged fully covered summary spends nothing. A source requiring a fresh read is refused; never silently reruns. |
| `--again` | Only with `--summary`: explicitly summarize from the start. Cannot be combined with `--update`. |
| `--summaries off` | Turn summaries off machine-wide on the running dashboard; no session needed and no launch or model call. Refused while model calls are paused, preserving the stored answer. There is no terminal on operation. |
| `--goal [TEXT]` | With no text, read the goal a fresh Goal card offers, its exact source sentence, saved revision, outcome lines, binding caveat and page URL. Reads the running dashboard only; starts no monitor and calls no model. Text saves a new typed goal revision while keeping outcome lines. An identical save says already saved. Writes require an explicit `--session` and terminal stdout; inferred-session and piped writes are refused before any POST. Writes may start the matching dashboard release. Every write checks the revision; a lost response is not retried. Saving supplies intent; a later monitor check must produce a level. Honors an explicit `--port`; rejects unrelated options and combined goal modes. |
| `--set-group LABEL` | Set the explicitly selected session's local display group through `/api/annotate`. At most 40 characters; an empty string clears it. Requires `--session HARNESS:SESSION_ID`; accepts `--port` and `--no-update-check`. Does not require a terminal, change intent or call a model. |
| `--clear` | Only with `--goal`: save an empty goal, keeping outcome lines and earlier revisions within the existing history limit. This does not discard intent history. An unsaved draft may be offered again; the command says when one is. |
| `--adopt` | Only with `--goal`: adopt the current harness `/goal`, otherwise the offered prompt draft, through the page's own adoption path. Checks its source, exact words, time and expected revision again before saving. Refuses a changed or missing candidate and preserves intent discarded on the board meanwhile. Keeps outcome lines. |
| `--pause-model-calls` | Send the page's durable Pause all AI use to a running dashboard, from any shell. Needs no session or typed command. Stops that dashboard's ordinary readings, long analyses, unasked checks, session summaries and Live monitor holders; preserves charged attempts. Starts nothing. Honors an explicit `--port`; rejects other options. Exits `0` only after a confirmed stored pause, otherwise `1`. The success line names the dashboard address and port that received the pause. A lost reply is not retried automatically. Resume AI use stays on the board and does not restart old jobs. |
| `--footer` | Print one status line segment and exit `0`: `AI use paused` while the shared permission store confirms pause, the session row's stored departure level while its evidence still matches, `Live monitor on` while this session's monitor is on, the number of other needs on the Needs you queue (sessions waiting on you and pending asks), the harnesses that cannot report a wait, and the tighter of the five-hour and seven-day quota windows with its reset. A monitor end may show a short reason for five minutes. Turning it off yourself is silent. It reads the JSON a Claude Code status line passes on standard input and the line file the running dashboard keeps for that session, makes no request and starts nothing, and prints nothing when it cannot tell. Alone, or with `--session`, it answers without loading the dashboard. Claude Code's `statusLine.refreshInterval` redraws it while idle: use 5 seconds alone or 10 seconds with the Barista wrapper. [Set it up](HOW_TO_USE.md#show-waiting-sessions-and-quota-in-the-claude-code-status-line). |
| `--plan-slice` | Print the plan summary a session would receive with the current settings. Reads the selected lane's brief and the event log through the board's guarded readers, and the lane states a dashboard last saved (state and progress read `not measured` when none was saved in the last 24 hours). Works with the dashboard down and calls no model. It prints nothing when the summary is off, the plan settings are refused, the plan cannot be read or no single lane matches. Also silent with `--no-plan`. Writes the summary as UTF-8 whatever the terminal's encoding. Any other option except `--lane`, `--no-plan` and `--no-update-check` is a usage error. See [preview the plan summary](HOW_TO_USE_TERMINAL.md#preview-the-plan-summary). |
| `--lane NAME` | Select a published lane by its brief slug for `--plan-slice`. If omitted, use `COMPASS_LANE` when set. Otherwise use the single declared lane folder containing the current working directory. An invalid or unknown explicit value leaves the preview empty. |
| `--forward-usage` | Send Claude's quota from a Claude Code status line to the running dashboard and exit `0`. It reads the status line's JSON on standard input, with the same byte and time bounds as `--footer`, and posts only `rate_limits.five_hour` and `rate_limits.seven_day`, each as `used_percentage` and `resets_at`, to `POST /api/usage/claude` on `127.0.0.1`. Nothing else from the JSON is sent. A window whose percentage is not a number from 0 to 100, or whose reset is missing or past, is left out; with neither window it sends nothing. It finds the dashboard as the other client operations do, with discovery and the post sharing a one-second budget after the standard input is read, never starts one, and prints nothing whatever happens. Claude Code supplies these windows after the session's first reply for eligible subscriptions. The board shows them while quota reading is on and a window is current. The command takes no other option. [Set it up](HOW_TO_USE.md#show-claudes-allowance-on-the-board-from-your-status-line). |
| `--project` | Read a Claude Code or Codex session's project label, counts and members, marking the selected session, then Current task, Latest instruction (Published instruction when undated), Running now and Needs you. Needs you names who acts (AGENT or YOU). A complete scan with no human question or waiting session says You are not needed, even when the agent has follow-ups. A final technical line explains workflow roles. Quiet requires an observed turn stop. Prose is folded to one line and clipped to 160 characters per field; members are never dropped. Accepts `--session claude:SESSION_ID` or `--session codex:SESSION_ID`. Uses `CLAUDE_CODE_SESSION_ID` as the default for Claude Code when `CODEX_THREAD_ID` is unset. Codex requires its full id in `--session`. If both markers are set, pass `--session` to select which session to read. Standard input and the working directory do not select a project session. Reads session lookup, the session list (the full board on an older dashboard) and project context; starts nothing and asks no model. Exits `1` when Compass is not running, a read fails or the caller is outside the current board or changed project. A session without a project label says so and lists nothing, with exit `0`. |
| `--session HARNESS:SESSION_ID` | The session `--footer`, `--goal`, `--project`, `--summary` or `--drift` reports for, `--monitor` holds, or `--set-group` labels, such as `claude:SESSION_ID`. Default for `--footer`: the `session_id` on standard input, then `CLAUDE_CODE_SESSION_ID`; for `--goal`, `--project`, `--summary`, `--drift` and `--monitor`, `CLAUDE_CODE_SESSION_ID` alone, since its standard input is not a status line; `--drift` also reads `CODEX_THREAD_ID` as `codex:` and that id when `CLAUDE_CODE_SESSION_ID` is not set. A malformed value leaves `--footer` silent. For `--project`, the message lists both accepted forms. `--drift` and `--monitor` also print a one-sentence refusal. Valid only with `--footer`, `--goal`, `--project`, `--summary`, `--drift`, `--monitor` or `--set-group`. Goal and group writes always require it. |
| `--port PORT` | TCP port, an integer from 1 through 65535. Default: `4553`. Also selects the instance addressed by status, stop and forget. |
| `--frontend-dev-manifest PATH` | Contributor-only startup ticket for an owned Vite child. Requires foreground operation and `127.0.0.1`; refuses diagnose/forget and disables model calls, quota fetching and native actions. Validates fixture locations and a fresh child handshake before serving. Status/stop do not read the ticket or probe Vite. Use the [frontend development command](CONTRIBUTING.md#frontend-development) to create and own it. |
| `--host ADDRESS` | Accepts only `127.0.0.1` (default) or `0.0.0.0`. The latter exposes the dashboard on every IPv4 interface without authentication. Other addresses and IPv6 are rejected. Read [remote-access risks](SECURITY.md#known-and-accepted) before changing it; prefer an SSH tunnel. Its local port must match the server's `--port`: a different local port can load the board but every action is refused with 403 and a same-port instruction. See [the tunnel procedure](HOW_TO_USE.md#move-it-ports-a-second-dashboard-and-where-state-lives). |
| `--allow-host NAME` | Trust one exact DNS hostname for Host and Origin behind a login proxy; repeat for additional names. It works on any bind: a proxy on the same machine, such as exe.dev's, reaches the default loopback bind, so keep `127.0.0.1` there and use `--host 0.0.0.0` only for a proxy on another machine. Names are case-insensitive with one optional trailing dot, at most 253 ASCII characters, with labels of 1-63 letters, digits or hyphens (no leading/trailing hyphen and no numeric final label). Supply an ASCII punycode name for an internationalized domain. Schemes, paths, ports, wildcards and IP literals are refused at startup. Subdomains and suffix matches remain blocked. For allowed names only, Host may omit its port or use the listening port, 80 or 443. State-changing requests require Origin; GET and HEAD may omit it. Any supplied Origin must match Host's exact name and use HTTPS on port 443 (omitted or explicit), or HTTP with the explicit listening port, excluding 80 even when Compass listens there. An explicit Host port must match Origin's effective port; an omitted Host port accepts either permitted origin. The proxy must forward the allowed name as the request's only Host header; a repeated Host is refused. IP and loopback rules are unchanged. Actions that spend a model call or open a message's whole text (Summarize, Check progress, corrections, Find goal, the Live monitor, saving Settings) stay refused through the proxy, unless `--login-proxy` and `--allow-user` name the signed-in reader, and the board says to use the Compass computer or an ssh -L tunnel. This does not authenticate anyone; use a login proxy and block direct access to the port. See [the trust boundary](SECURITY.md#known-and-accepted). Daemon and terminal automatic starts retain every name and any explicit bind; an existing dashboard keeps its own configuration. |
| `--login-proxy PROXY` | Name the login proxy in front of an `--allow-host` name, so its signed-in user header can admit a reader listed with `--allow-user`. The one accepted value is `exe.dev`, whose `X-ExeDev-Email` header was measured to replace any copy a client sends and to be absent from requests the proxy refuses. That holds for a private VM only: on one shared with `share set-public`, unsigned requests reach Compass and their header handling was not measured, so do not use this flag there. Requires `--allow-user` and at least one `--allow-host`; any one without the others is a usage error. |
| `--allow-user EMAIL` | One signed-in reader the `--login-proxy` may name; repeat for more. That reader may run the board's own actions through the proxy: Summarize, Check progress, opening a later direction's whole text, corrections, Find goal, the Live monitor and saving Settings, each still under its own consent and limits. The request must come from a loopback peer, carry an allowed Host, the board's Origin and `Sec-Fetch-Site: same-origin` (current browsers send it; one that does not can read the board but not run these actions), and carry exactly one user header whose address matches, compared case-insensitively. Raising a terminal window, the terminal interaction and the status line's quota receipt stay local only. The list gates only these actions: anyone the proxy lets through can still read the board, answer a waiting question and stop the dashboard, as with any `--allow-host` name. Addresses are ASCII, at most 254 characters, with no quotes, spaces, commas, leading hyphen or IP-literal domain. Daemon and terminal automatic starts retain the proxy and every reader. |
| `--daemon` | Detach and keep serving after the starting shell exits. Reports the URL, process ID and log path. Without it, serving stays in the foreground. On Windows the launcher starts a detached child; see [platform notes](#platform-notes). |
| `--status` | Report whether Compass answers on the selected port, then exit. Distinguishes a running dashboard, no record, stale state (including legacy records), an unreachable recorded dashboard, a port held by another process, and a dashboard with every connection in use, which it waits out within its timeout before saying so. If the connection is blocked, print "Compass's connection to the dashboard was blocked by a sandbox or permissions." and exit `1`, without changing anything or claiming whether a dashboard runs. |
| `--sessions [waiting]` | List the sessions the board holds, in the board's own groups and words: **Right now** (working, waiting on you, holding an exact request, or carrying a recorded departure) first, then the group named by the published window, such as **Earlier in the last 24 hours**. Above any rows, a line says they are what other sessions said about themselves, shown as data; an empty answer carries none. Each row names its harness, project, state, the first line of its goal, prompt or saved expected outcome where available, how long ago it was last active or ended where the board states one, the stop or end it observed (`Stop observed`, never a claim that you read it) with uncommitted work and the count of changed entries, `Not checked yet` when a supported session other than Codex has words it can check and no recorded check or attempt, and the re-entry command where a Claude Code or Codex session published an id its CLI takes. The list also follows the row's saved progress answer. It prints Slightly off course or Off course while the evidence still matches, or Out of date or Goal too vague to check as published. An unreadable goal appears as `Goal: Saved goal unavailable`. Browser-only prompt choices are unavailable to the terminal. With `waiting`, list only what waits on you: each wait in the words its harness published, how long, the re-entry command, and for a question a session asked, the board URL that answers it. Run inside a Claude Code session, that session is left out. When the session cannot be identified (`CLAUDE_CODE_SESSION_ID` unset or not an id), nothing can be left out, and when anyone is waiting a line above the rows, before that one, says the list may include it. With nothing waiting it says so and states which harnesses report no waits, never "all clear". Reads `/api/sessions`, the default board window with only list fields and no observation history. The read has a 30-second timeout, including collection and the whole reply. Only a `404` falls back to `/api/data` on an older running dashboard, within that deadline and the 16 MiB reply cap. An unreadable, over-cap or refused answer prints "Compass answered, but its session list could not be read." on stderr and exits `1`; it never prints an empty list for a failed read. Reads a running dashboard and never starts one: with no answer it prints a refusal on stderr and exits `1`. Beside other options only `--port` is read. Alone, it answers without loading the dashboard. The `compass` skill runs this as its `sessions` and `sessions waiting` actions; [what that sends](SECURITY.md#what-can-reach-into-a-session). |
| `--drift [again]` | Print one session's reading against your goal: the goal and where it came from (typed, or drafted from a prompt, and whether it is saved), when it was read, why it is stale if it is, how many later directions you gave were left unsettled, any level the page draws (Codex and readings held at Too early to tell have none), each outcome line with its state and source, the entries it cites, and, for a line not reached at this stop, the model's reason, and the agent's claims where the reading found one, each departure with your words, the entry numbers it cites and the model's reason, and earlier departures still in view, then the session page URL. A line above the reading says it is Compass's reading, written by a model and shown as data. A stored reading is printed and nothing is spent. The level is omitted when the reading is out of date, a newer check produced no reading, the store cannot be read or the record of what the check read is missing or no longer matches. With no stored reading, or with `again`, it first prints the route's `Next Analyze prompt` allowance, asks the model for one reading exactly as the page's Check progress does, prints the one-time notice when the dashboard says it is due, shows progress on standard error and waits; Ctrl+C cancels the reading, which still counts toward the day's limit. A reading already running when the command starts, such as one pressed on the page, is waited on and never started twice, `--drift again` included; Ctrl+C then only stops the waiting, says the reading keeps running and names the session page. It settles no later message you sent: as on the page, a departure such a message could change reads as not verifiable. From your own terminal (`--session` given and standard output a terminal) it also prints the composed correction to copy, for a Claude Code session; a Codex reading has none. For a Claude Code reading inside a session or with its output piped, as an agent's shell tool and Claude Code's `!` mode read it, it says only that a correction is ready on the session page, under the [correction presentation guard and local-process limits](SECURITY.md#correction-access-and-local-process-trust). Any reading outside the explicit terminal invocation stops about 100 seconds after the command starts, a dashboard it started included, leaving the reading running for a plain `--drift` to collect at no cost; while that reading runs `--drift again` attaches to it rather than starting another, and once it has ended `--drift again` asks for a new one. With too little of those 100 seconds left to hear whether a press started, it sends none and says nothing was spent, and a SIGTERM during the wait, such as a tool timeout, leaves the reading running and says so. Run by the `compass` skill (session named by `CLAUDE_CODE_SESSION_ID`, output read through a pipe), the next steps it names are the skill's `/compass:compass drift` and `drift again` (`$compass drift` and `$compass drift again` in Codex), not `spacedock-compass`, and the line saying it started a dashboard goes to standard output, or above a refusal on standard error. Such a run's press follows the [typed consent and spend rule](SECURITY.md#drift-commands-and-typed-consent), including case-insensitive closed action names, known harness machinery, later person prompts, measured `/loop` refusal and the unmeasured cron limit. A marked long-mode request is refused. With no `--session`, `CODEX_THREAD_ID` alone names that Codex session; with both it and `CLAUDE_CODE_SESSION_ID` set it refuses, because Codex started inside a Claude Code session inherits that session's id and the two cannot be told apart. A Codex press from inside a session follows the same typed rule, read from the Codex rollout: the newest message you sent must be your whole typed `$compass drift` or `$compass drift again`. Every refusal the page can show (annotations or model calls off, paused, the daily limit, no route, a session that cannot be read yet, nothing typed, and the rest) is one line on standard error, exit `1`, with nothing spent. Goal refusals lead with the checked session id and page URL. If a local command opened the session, the missing-draft reason names that command. Inside a session, these refusals explain that drift reads only the session it was typed in and that another session's reading is on that session's page. A reading the dashboard withholds after the press, such as on a route whose managed policy can change at launch, prints the dashboard's own sentence, which says whether anything was sent or counted, below the goal as it now stands: a press over a drafted goal saves it even when nothing is read, unless adoption is refused. A discard saved meanwhile survives adoption by Check progress; the refusal starts no reading and saves no goal. A Claude Code or Codex session starts a dashboard when none answers and lifecycle permits the default or explicit target port, recovering dead target state and refusing unknown target state with its exact filename, and refuses one of another release; any other harness gets one line naming its session page, where the page reads it. A Codex reading prints the line states and departures the page shows, with no level and no correction. The `compass` skill runs this as its `drift` and `drift again` actions inside a Claude Code or Codex session; [what that sends](SECURITY.md#what-can-reach-into-a-session). |
| `--monitor` | Start one detached terminal holder for this live Claude Code session, without a browser tab. Resolve the session from `--session` or `CLAUDE_CODE_SESSION_ID`; with none, start nothing and send nothing. A full id must match the published `resume_id`. Start or reuse a dashboard as `--daemon` does, refusing another release, and say when this command started it. Successful in-session starts print this announcement on stdout; failures report it on stderr. Repeated starts share the holder. Inside a session, require the latest prompt to be the person's typed `/compass:compass monitor on`, once per accepted run. Refused admission releases that command. This can spend on model checks under the [Live monitor limits](SECURITY.md#the-live-monitor). Before checking, it saves the page's drafted goal only when no goal or outcome lines are saved. It prints the saved words with their source and the session page URL, or says it makes no check until a goal is saved. It prints what is sent when disclosure is due and always prints a stop command with the full session id. From another terminal, `--monitor --session claude:ID` needs no typed command and adds no turn to the watched session. Repeats read only this session's [lease metadata](SECURITY.md#the-live-monitor), without a model reading or renewal. A valid off or browser-only reply stops the stale helper and attempts normal admission again, including the typed-command check inside a session; browser holders remain. Missing or malformed terminal-holder identity, a timeout, a busy dashboard or an unreadable reply leaves the helper running. A helper that keeps its lifetime lock is never replaced. HTTP start refusals remain refusals even with an empty or HTML body; malformed successful replies are unreadable. Session lookup, lease reads, start requests and check-ins each allow up to 30 seconds and 16 MiB; helper readiness allows 35 seconds. A concurrent command for the same session waits up to 204 seconds for the command lock: up to 54 seconds to find or start the dashboard, two 30-second reads, two 35-second readiness waits, up to 18 seconds of worker cleanup and a two-second handoff margin. If the lock is still held, it exits `1` with "Another monitor command is still running."; polling can add up to 0.05 seconds, apart from OS scheduling delays. This holds a lease; it does not claim a check ran. There is no browser consent deadline. The holder ends on a lease end, an absent or ended session, dashboard restart, 30 seconds of failed dashboard exchanges or two hours without new published activity. On POSIX, when monitoring the caller's own session, it also ends when the recorded Claude ancestor exits or changes start time. |
| `--off` | Only with `--monitor`: cooperatively stop this terminal holder and wait for it to exit. Start and stop no dashboard. Browser holders keep their lease. Off/on keeps the current period's charged check count and one-minute spacing within the running server; server restart resets both, while the rolling daily charge survives. With no terminal holder, say it is not running. |
| `--stop` | Ask Compass on the selected port to shut down and wait for the port to be free. A foreign process is left alone, and so is a dashboard that stays at its connection cap. Origin-aware records need matching machine, boot and measured namespaces plus a positively absent process, or the same machine on a different boot with a recorded start before this boot. Unknown provenance preserves state and exits `1`. Legacy records retain the old stop behavior: an unanswered parsed record can be removed after the port is free, even with a locally live PID. Read the [legacy and cloned-machine limits](SECURITY.md#process-lifecycle-written-paths-and-apishutdown). Failed removal exits `1` without claiming success. If the connection is blocked, print "Compass's connection to the dashboard was blocked by a sandbox or permissions." and exit `1`, without stopping anything, removing state or claiming whether a dashboard runs. |
| `--diagnose` | Report the local store paths searched, whether they are readable and what was found, any project script file it skipped and why, and where your list of check commands is, whether it could be read and which entries were ignored; exit without serving, writing history or making model calls. Use it first when a harness is missing. |
| `--json` | Format `--diagnose` as JSON. Does not change status output or make the dashboard's normal output JSON. |
| `--window-hours HOURS` | Hide sessions with no activity within this many hours. Default: `24`. Accepts a floating-point number. This display window is separate from history retention. |

### Model use and quota

Check progress (Analyze drift) runs on your press in the session header. For a Codex goal summary,
open Show technical details on the project page and press Summarize this session for the selected
session. A Claude Code session summary runs when you open a finished session, press Summarize or
Update summary, or request one with `--summary`, `--summary --update` or `--summary --again`.
Each tells you once what is sent and where, again if the destination or content tier changes. Pause all AI use stops every model call until Resume AI use.
`--no-observer-model` refuses them at startup. Turn off summaries affects session summaries only,
is disabled while paused, and keeps its saved answer through pause and resume. Unattended checks remain a separate opt-in. A model ID selects a
reader, not proof of accuracy.

Long analysis is a separate page action for native Claude Code sessions, with no new startup
flag. Check progress makes one call; an explicit long press allows at most 16 evidence calls
and one final reconciliation call, each sharing the same rolling limit as Check progress. The saved
prompt ceiling still applies within the route's allowance. Individual calls keep the 180-second
timeout; the whole long job is bounded at 30 minutes. Pause all AI use, Cancel and `--no-observer-model`
still stop calls. See [the workflow](HOW_TO_USE.md#analyze-a-session) and
[the long-analysis contract](SECURITY.md#long-analysis) for source, preparation and storage limits.

| Option | Behavior and default |
|---|---|
| `--observer-model` | Accepted and does nothing in this release; will be removed in a later release. Goal summaries need no flag and run on Summarize this session under Show technical details on the project page. |
| `--claude-reading-model MODEL` | Explicit Claude model ID for Claude readings. Default: `claude-sonnet-5-5` (Sonnet 5.5). The admission floor is Sonnet 5: explicit Sonnet or Opus generation 5 or later IDs are accepted, such as `claude-sonnet-5`. Floating aliases, Haiku and older generations are rejected. An admitted ID must still be available through your Claude Code installation. |
| `--claude-monitor-model MODEL` | Explicit Claude Haiku model ID for the Live monitor's once-a-minute check. Default: `claude-haiku-5-5` (Haiku 5.5). Only an explicit Haiku generation 4 or later ID is accepted; floating aliases such as `haiku`, and every Sonnet or Opus ID, are rejected, and this does not change `--claude-reading-model`. An accepted ID must still be available through your Claude Code installation. The setting takes effect once Live monitor runs the check. |
| `--unasked-readings` | Enable bounded checks of sessions with a typed goal without a fresh press; only departures are raised. Off by default. Claude Code reads Claude Code sessions; Codex reads Codex sessions. On Pi and Antigravity an unasked check prefers Claude Code, where Check progress prefers Codex; if the preferred provider is unavailable or unqualified on this machine, the other serves. Codex needs the Is it on track? card's "Allow Codex to run unasked checks" toggle for the current destination; Needs you points to it when sessions with a typed goal are waiting. Claude Code needs no separate grant; the Is it on track? card names it and lists what each check sends, which on a Claude Code session includes the checks and commands that failed, never one that passed. Check progress and Resume AI use never grant it. Revoking it, Pause all AI use and `--no-observer-model` stop checks. Pausing and then resuming AI use clears the grant. Quiet hours hold the notification, not the check. The caps remain three per session, twelve per rolling day, with a fifteen-minute floor. A call that starts and fails counts toward both caps. Harnesses without a session record reader show an explanation instead of a grant offer and do not enter the Needs you permission queue; every stored Codex grant, including one saved for an earlier destination, stays revocable from any session's Is it on track? card while these controls are on. A saved grant that no longer applies shows a checked switch and explains why; Needs you does not ask for permission while a grant is stored. No effect under `--no-annotations`. |
| `--allow-tool-output` | Accepted and does nothing in this release; will be removed in a later release. Claude Code readings include tool output by default where the destination is named, and disclose it in the notice. |
| `--no-observer-model`, `--no-harness-usage` | Equivalent names for refusing every model call for this run, including goal summaries, reader-requested analyses and unasked checks. Includes session summaries. Overrides the unasked opt-in. |
| `--no-update-check` | Refuse the daily release lookup for this run, independently of the saved **Look for new versions once a day** switch in Settings. Also accepted with `--drift`, `--monitor`, `--summary` (including `--update` and `--again`) and `--goal` (including text, `--clear` and `--adopt`); any dashboard they start inherits the refusal. An already running dashboard keeps its own settings. `--footer` only reads local files and accepts no startup switches. The check is on by default. Turning off the switch or using the flag stops it and suppresses the cached startup hint. After successful dashboard startup, the launcher prints a cached newer stable version to stdout once, never into the daemon log, without a request or wait. The terminal reads the saved answer once per successful start; the dashboard shows later answers on its next refresh. Short operations print no update hint. It requests the plain release URL with no query string and sends only a `compass/<version> (<os>; <arch>[; ci][; internal])` User-Agent beyond urllib's standard headers to spacedock.md, with no identifier or session content. The route counts the lookup itself from its headers. The site counts checks in PostHog without an IP and in Plausible with the caller's IP and user agent; CI-marked checks are not counted. Plausible stores neither and derives approximate location from the address. See [Daily update checks](SECURITY.md#daily-update-checks) for the exact request and limits. |
| `--internal` [on/off] | Show the effective internal-use marker with no value, or persist `on` or `off` in the Compass home, print the effective state, and exit. `SPACEDOCK_INTERNAL=1` overrides a saved `off`; a development build alone is not internal. Refused with `--daemon`. |
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
| `--no-annotations` | Do not read or write saved goals, expected outcome lines, readings or group labels for this run. The page offers no editable goal fields. Check progress remains visible but disabled with a reason. Existing annotations are left on disk. Does not govern the separate session-summary store. |
| `--no-dismiss` | Do not read or write the handled-session store. Previously handled sessions return to the board and its dismiss control is unavailable for this run. |
| `--forget` | A one-shot cleanup: delete observation history, recorded session ends, launcher parent declarations, stored session summaries, copied-correction digests and the lane states saved for the session summary; sweep annotation discard records; store model calls as paused, which stops readings, goal summaries and session summaries until you use Resume AI use on the page, and store session summaries as off, which stays after you resume until you turn summaries on again. Preserve the words and group labels you typed, unexpired model-spend timestamps and `compass-typed-presses.json`, which like those timestamps guards what a press may spend: deleting it would let a typed command that already paid for a reading pay for another. Refused while a dashboard answers on the selected port or any dashboard state file in the Compass home lacks proof that its writer is gone. A refusal for a recorded writer names its state file; stop that dashboard in the environment where it runs first. The deletions are irreversible. |

`--forget` checks the selected port and every dashboard state file in that Compass home. A recorded
writer is proven gone only with matching machine, boot, network and process namespace evidence and
a definitely absent process. Unproven writers, legacy, corrupt or unreadable records block the whole
cleanup, leaving every store unchanged. Run `--stop --port PORT` where the recorded dashboard runs,
or press Ctrl+C in its foreground terminal. If it has already stopped, verify that there before
removing only its state file and matching `.origin` file, then retry. With no state files, cleanup
behaves as usual. Cleanup repeats these checks under the folder's `compass-lifecycle.lock` OS lock,
held through every store change. Dashboard state publication takes the same lock and precedes
interaction discovery, which can write history. A competing
cleanup or startup refuses clearly; retry after the holder finishes. Killing a holder releases the
lock, even though the lock file remains. Unavailable or unsupported locking refuses cleanup and
state publication. Both commands must use a build with this lock; stop dashboards using older
builds first. The command does not erase harness transcripts or every Compass setting and store.

### Workflow and event controls

These features are enabled by default. An off switch suppresses the named feature for this run.

| Option | Behavior and default |
|---|---|
| `--no-spacedock` | Do not read workflow definitions or show their stage strips. Claude role metadata remains; saved stage conditions remain readable but suspended. |
| `--no-tripwires` | Do not read or write saved workflow stage conditions. |
| `--no-events` | Disable the event coordinator, event overlays and coarse store probe. Fixed-interval collection continues. Also disables terminal focus, command-shape reporting and reading/writing recorded session ends. Observation history is independent. |
| `--no-irreversible` | Disable hook command-shape matching, report ingress and publication. Ordinary lifecycle hints remain available unless `--no-events` is also set. |
| `--no-git` | Skip end-of-session Git probes, project check-script reads and plan reads from Git. No remote is read, so no `gh pr checks` or `gh run view` poll counts as CI evidence. Empty dirty and changed fields mean no reading is available. |
| `--no-plan` | Skip the plan settings, sources and working-folder capture. `GET /api/plan` answers 404 to an admitted loopback fetch. With `--diagnose`, the plan settings entry reports that the plan is off. [Set up the plan board](HOW_TO_USE.md#set-up-the-plan-board). |
| `--no-ci-read` | Do not read a pull request's or merge request's CI checks from GitHub or GitLab when you press Check progress. No `gh` or `glab` command runs, and a reading goes without those checks. Turning off Read pull request status in Settings also stops the read. |
| `--no-focus` | Do not record terminal identities, publish a focus capability or raise session terminals. `--no-events` also turns this off. |
| `--no-ask` | Disable session-to-reader questions: register, poll and answer routes refuse, and the page offers no ask control. |

### Notifications away from the desk

Reach nudges are off until a URL is configured. Quiet hours have no effect until a window is
configured. Both settings can come from a command-line value, environment variable or file;
see [Environment](#environment).

| Option | Behavior and default |
|---|---|
| `--reach-url URL` | HTTPS webhook endpoint for counts-only nudges when sessions need input or finish unread while you are away. HTTP is refused to protect the credential in the URL. Overrides the environment and file settings. No URL is configured by default. |
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
| `COMPASS_PARENT_SESSION` | Launcher declaration on a child: `HARNESS:SESSION_ID`. Only `event_hook.py` reads it, on SessionStart. Known hook harness tokens are `claude`, `codex`, `gemini` and `droid`; Claude accepts its eight-character published key or a full UUID, the others a full UUID. Malformed values are dropped. It links only to a row on this board; no process or transcript is discovered from it. A resume without the variable preserves this run's earlier declaration. Received declarations survive restarts in bounded private storage; absent claims expire after the activity window without an event. Unavailable storage is diagnosed and new claims may last only in memory. `--no-events` neither loads nor saves them; `--forget` removes them. Events never received cannot be recovered. |
| `COMPASS_LANE` | The lane brief slug for the opt-in SessionStart plan summary and its terminal preview. Set it in the environment of the session you start. If unset, Compass matches the working folder to a single declared lane. |
| `COMPASS_HOME` | Move Compass's own state, logs and persistent stores. Default: `.compass` under your home directory. Does not relocate harness transcripts. Use the same value for start, stop, status and forget. |
| `COMPASS_ALLOW_TOOL_OUTPUT` | `1` is accepted and does nothing in this release; will be removed in a later release. |
| `SPACEDOCK_INTERNAL` | Exactly `1` marks release lookups as internal, overriding the saved internal flag. No other value does. |
| `CI` | After ASCII whitespace trimming and ASCII case-folding, `1`, `true`, `yes` or `on` adds `; ci` to the release lookup's User-Agent; any other value adds nothing. It does not turn the check off. |
| `COMPASS_REACH_URL` | HTTPS Reach endpoint when `--reach-url` is absent; takes precedence over the `reach_url` file in the Compass home. `--no-reach` overrides all sources. |
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
| `footer/HARNESS-HASH.json` | One small file per Claude Code session for `--footer`: a count, harness names, monitor state, the published stored departure token, the last end reason and time, and a freshness time. Written by a running dashboard, removed when it stops. [What it holds](SECURITY.md#the-status-line-files). |
| `compass-settings.json` | Reading limits and the saved daily update-check preference, shared by dashboards using this Compass home. In Settings, open Customize under How much a progress check reads. The stepped sliders show sizes in KB and save on release. Reset restores one default, and Reset all to recommended restores every limit to its default. |
| `compass-internal.json` | Saved internal-use flag; changed by `--internal on` or `--internal off`. |
| `compass-update-check.json` | Last attempted UTC day, plus the last successful release answer and its time. Its persistent `.lock` file serializes servers sharing one Compass home; no request is made if the lock or atomic save fails. |
| `compass-history.json` | Bounded observation history. |
| `compass-ends.json` | Recorded session ends from the event coordinator. |
| `compass-lifecycle.lock` | Stable OS lock shared by cleanup and dashboard state publication in this folder. It remains after cleanup; killing a holder releases the lock. |
| `declared-parents/claims.json` and `claims.lock` beside it | Bounded launcher parent claims and their stable writer lock. `--forget` removes claims and leaves the lock file. See the [security contract](SECURITY.md#launcher-parent-declarations-and-group-labels) for retention and failure behavior. |
| `compass-annotations.json` | Saved reader goals, outcome lines, readings, local group labels and discard records. |
| `compass-summaries.json` | Stored session summaries and word-free source comparison metadata. Independent of annotations; Delete summary removes one session and `--forget` deletes the store. |
| `compass-dismissals.json` | Sessions marked handled. |
| `compass-project-checks.json` | Commands you list as checks for a project. You write it; Compass only reads it. [How to list one](HOW_TO_USE.md#list-a-projects-checks). |
| `compass-plan.json` | Optional settings you write for the Plan board. It declares the sources, their formats and the privacy rules. [Plan settings and source admission](SECURITY.md#plan-settings-and-source-admission). |
| `compass-plan-states.json` | Each lane's published state and which lanes serve each goal, with no plan text, saved by a dashboard each time it reads the plan while the session summary is on. The SessionStart summary and `--plan-slice` read it and ignore it after 24 hours. `--forget` deletes it. [Saved lane states](SECURITY.md#saved-lane-states-for-the-session-summary). |
| `ci-read-off` | One-line marker the Read pull request status switch in Settings leaves while it is off. It is removed when the switch goes back on. |
| `compass-tripwires.json` | Saved workflow stage conditions. |
| `compass-copied-corrections.json` | Digests recording copied corrections, without their text. |
| `compass-reading-permission.sqlite3` | Reading permissions, the model-call pause, the session-summary switch, the one-time notices shown, and the spend admission timestamps for readings and for session summaries, kept apart. Long analysis adds word-free job and per-pass bindings and reservation receipts; these do not authorize resume. |
| `compass-typed-presses.json` | The ids of the typed `/compass:compass drift` and `drift again` commands (and Codex's `$compass drift` and `drift again`) that a press from inside a session started a reading on, `summary`, `summary update` and `summary again` commands that started a summary, and `monitor on` commands that admitted a terminal lease, with their consumption times, no command words; the newest 512 and every consumption in the last 24 hours, as [typed consent](SECURITY.md#drift-commands-and-typed-consent) explains; owner-only (mode `0600`). A press refused before it starts leaves its command out. `--forget` keeps it. |
| `reading-long-jobs/` | Word-free long-analysis owner, plan, pass and accounting markers under the state directory. Recovery preserves uncertain accounting and never resumes model calls. |
| `reach_url`, `quiet_hours` | Optional plain-text defaults for reach and quiet hours. |

See [local-store security](SECURITY.md#scope) for retention, permissions and other persistent data.
Keep logs and state private when reporting a problem; they can contain local paths and capabilities.

The terminal holder keeps owner-only control and status records, plus persistent command and
lifetime lock paths, under `monitor/` in the Compass home. They contain identities, exit reasons and a bounded start receipt with the adopted goal and disclosure,
never a transcript. The receipt stays until a later start replaces it. An obtainable lifetime lock means stale metadata is no running
holder. Lock paths are never removed while another process could hold them.

The holder exits on a recorded lease end, a missing or ended session row, 30 seconds of continuously
failed dashboard exchanges, or two hours without new published session activity. On POSIX it also
exits when the nearest ancestor named `claude` dies or its PID's start time changes. Without that
ancestor (for example an explicit session from an ordinary shell), or on Windows, this process
check does not apply. A dashboard restart ends the holder with a reason in its status file; it
never replays start. A new typed command is needed to resume. A hard-killed holder lapses after
50 seconds without beats. These bounds apply independently of browser holders.

## Platform notes

The same launcher supports macOS, Linux and Windows. Native notifications and terminal focus
depend on the platform and harness; see [Compatibility](COMPATIBILITY.md).

On Windows, `--daemon` respawns the server and deliberately omits the unattended-check opt-in
`--unasked-readings`. The compatibility flags `--observer-model` and `--allow-tool-output`
do nothing and need no forwarding. The experimental interaction-origin pair is also not
forwarded. Use foreground mode on Windows when you need those options. Feature-off switches,
port, host, every allowed hostname, the login proxy and its readers, display/history bounds, Claude model choice, reach URL and quiet
hours are forwarded.

## Exit status

| Code | Meaning |
|---|---|
| `0` | Help, the version, a session listing, a drift reading or diagnosis completed; `--footer`, `--forward-usage` and `--plan-slice` always, including when they printed or sent nothing; status found a running Compass; serving ended normally; daemon startup or stop succeeded; or forget stored model calls as paused and finished its summary-store cleanup. `--stop` can succeed when no instance is running. |
| `1` | Status found no running Compass, found it with every connection in use, or could not check because the connection was blocked, or startup/stop/forget failed or was refused. A foreign process is not stopped. `--sessions` found no running Compass, or its answer could not be read. `--drift` refused, or no new reading was produced. |
| `130` | `--drift` was interrupted with Ctrl+C. It cancels only a job positively identified as started by this invocation. After an interrupted POST it reads the board once and reports running, absent or unknown without cancelling a job it found there. After a completed job it says the reading ended. |
| `2` | Invalid command-line syntax or rejected values/combinations, reported by the argument parser. |

Startup exits `1` if the initial dashboard state file cannot be written. It names the state
folder and error class and refuses before binding or accessing shared Compass stores; `--daemon` reports the
same refusal to its launching command. A failure writing only the later `.origin` sidecar is
reported but permits serving, since the published state file still blocks `--forget`.

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
- [Use Compass from a terminal](HOW_TO_USE_TERMINAL.md): the everyday commands, what they print, and what only the board does.
- [Installed skill](compass/skills/compass/SKILL.md): dashboard controls, supported stores and session interpretation.
- [Security](SECURITY.md): data exposure, outbound activity and retention limits.
- [Compatibility](COMPATIBILITY.md): harness and platform support.

The [launcher](compass/skills/compass/server.py) delegates to
[`compass_runtime.entry`](compass/skills/compass/compass_runtime/entry.py), which answers a lone
`--version`, `--sessions`, `--footer`, `--forward-usage` and `--drift` itself and otherwise hands over to
[`compass_runtime.cli`](compass/skills/compass/compass_runtime/cli.py), which owns the parser.
`--help` reflects the copy you actually run; this manual follows the repository's current code.
