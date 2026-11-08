# Notification reference

Return to [start, status and stop](../SKILL.md#start).

## Notifications

Three paths manage Claude's needs-input state, and a question registered through the ask lane is a
fourth alert rather than needs-input state. On macOS the server can deliver native notifications
through `osascript`, even with no dashboard tab open. Gate alerts have a 60-second per-session
cooldown and a 15-second lane-wide floor; questions have their own 15-second floor. Linux and
Windows have no native backend in this release; with a dashboard tab open, the page can deliver
browser notifications after permission is granted, for a session that starts waiting on the human
and for one that was working and has gone quiet. The dashboard shows every published item in
Attention on all platforms.

Native alerts fire on the transition into needs-input, not on every refresh. Questions notify on
arrival. Idle nudges (`idle_prompt`) can notify without marking the session blocked. The browser's
quiet nudge is close to that but not the same event: it has no hook of its own, so it fires on the
published row ceasing to look busy, and a row reaches that two ways. Where the harness's lifecycle
hooks are installed its own turn-stop reaches the row within a few seconds; everywhere else the row
turns over only once its writes have paused for as long as the working threshold. Its wording says
the session has gone quiet rather than that it is waiting on you, which is the honest reading of
either path.
Notification delivery is best effort; the dashboard's observed state remains the source to inspect.

Compass can also check an annotated session against what you asked for without being asked, and
raise a departure while you are away. Off by default, behind `--unasked-readings`, refused by
`--no-observer-model` whatever else is set, and it is the only thing here that spends your model
capacity with nobody watching. Claude Code reads Claude Code sessions; Codex reads Codex sessions.
On Pi and Antigravity an unasked check prefers Claude Code. If the preferred provider is unavailable or
unqualified on this machine, the other serves. Claude Code needs no separate grant. For Codex, use “Allow Codex to
run unasked checks” in the session’s Drift card; Attention points to that toggle when saved typed
goals are waiting for permission. A harness with no session record reader shows an explanation
instead of the grant switch and stays out of that Attention queue. Every stored Codex grant, including one saved for an earlier destination, keeps a checked revoke
switch on every session's Drift card while the unasked controls are on. The card explains when
saved permission no longer applies; Attention does not ask for it again. Granting covers Codex at
the disclosed destination across sessions.
Revoking it stops Codex checks; Analyze and Resume never grant it. Pause model calls stops either
provider, and Pause followed by Resume clears the Codex grant. With the startup flag off, neither the toggle nor the Attention cue appears.
It checks on an observed state
change rather than every turn, it raises a departure and never a reassurance, and it stops at a
limit of three per session and twelve per rolling day, with a fifteen-minute floor. It reads your typed goal alone, never your expected outcome
lines, and a session with lines and no goal is not checked this way. On a Claude Code session it also reads the checks
and commands that failed, with their output, so a failing test or CI run against your goal can raise a departure while
you are away; a check that passed is never sent, because the lane does not reassure. A shell call that also held a
run that passed, ran more than one thing, or whose output is not one failed check's own is sent without its
output. A spent limit is said out loud: a session nobody checked and a session checked and found clean are
different sentences on the board, because you were not there to know which one you are looking at. Turning it off stops new checks and retracts nothing: what was
already raised still shows on the session, in the review and in the Intent log, under a line saying
nothing new is being checked.

What became of an alert about a session is now recorded, one entry per raise, and that session's
panel prints it. There are five outcomes and they mean different things: handed to this machine's
notification service, the service returned an error, the command could not be started at all, the
call did not return inside its time limit, and this platform has no backend in this build. A raise
whose subject carries no session id records nothing, since the record is keyed by session. None of them is "seen". `osascript` exits zero under Do Not
Disturb and with the hosting application's notifications switched off, so a hand-over says the
service accepted the request and nothing about whether a banner was drawn or anyone was at the desk.
A raise on a platform with no backend spends no cooldown, so the next real transition is still
eligible. Beside the outcome, the panel says whether a dashboard tab has reported a notification lane
of its own and how long before the raise it did so. That is a statement about a tab, not about a
raise: a tab that opens reports and a tab that closes does not, so its absence never means the alert
missed you.

1. **Transcript detection** — an open `AskUserQuestion` or `ExitPlanMode` flips the session to Needs input on the next collection, *when the record has reached disk*. Claude Code buffers it and may not write it until the gate is answered, so treat this as an opportunistic early signal rather than a source to rely on (an open dashboard tab is what drives collections, so keep one open). When the record is there, the row shows the question itself, or a plan's first line, rather than the tool's name; when it is not, the row still says a question is open but cannot say which. Both readings are normal for the same session. There is also a window of up to 90 seconds after a turn starts where a live event overlay reports Working and the question does not show at all, even though it was parsed.
2. **Lifecycle hooks** — `Notification` and `SessionEnd` hooks in user settings (`~/.claude/settings.json`) POSTing their payloads to `http://127.0.0.1:4553/api/notify`. Notifications cover permission prompts and idle waits, even with no browser tab open. The structured `notification_type` decides whether a notification is actionable. Idle nudges (`idle_prompt`, message "Claude is waiting for your input") pop once but never mark the session blocked; authentication, completion and computer-use status notifications do neither; permission prompts, MCP elicitation dialogs and a worker's permission or network request create Needs-input state. A type not on either list is treated as actionable, so a notification kind added upstream surfaces rather than disappearing. `SessionEnd` clears a standing hook when Claude exits cleanly. These hooks are NOT installed by the plugin — if the user wants path 2, offer to add them to their `~/.claude/settings.json`:

Use the bundled `notify_hook.py` (next to `server.py`) rather than a `curl` one-liner. The one-liner is POSIX-only end to end — single-quoting, `/dev/null`, `|| true`, and `--data-binary @-` all fail in `cmd.exe`, and Windows PowerShell 5.1 aliases `curl` to `Invoke-WebRequest` and has no `||`. One interpreter invocation behaves the same in every shell, exits 0 even when the dashboard is not running, and refuses to POST anywhere but loopback.

```json
"hooks": {
  "Notification": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/launch.py\" \"<skill-dir>/notify_hook.py\"", "async": true}]}
  ],
  "SessionEnd": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/launch.py\" \"<skill-dir>/notify_hook.py\""}]}
  ]
}
```

On native Windows use `python` instead of `python3`, and a Windows path. Pass a URL as the first argument for a non-default port: `python3 "<skill-dir>/launch.py" "<skill-dir>/notify_hook.py" http://127.0.0.1:9999/api/notify`.

After adding it (or after any settings change that breaks it), tell the user to open `/hooks` once or restart Claude Code to reload hook config.

Simulate for testing:
```bash
echo '{"session_id":"<id>","message":"test"}' | python3 "<skill-dir>/launch.py" "<skill-dir>/notify_hook.py"
```

3. **Lifecycle events** — the plugin's own bundled hooks at `hooks/hooks.json`, so there is **nothing to add to a settings file**. They forward general lifecycle events to `/api/events/claude`: session started and ended, prompt submitted, turn stopped, permission requested, a tool run finishing, subagent started or stopped, tasks changed, compaction finished. Where path 2 sets one piece of side state, this drives the session's Working, Needs-input and Idle state directly, so the board reacts to a turn starting instead of waiting for the next scan.

   Nothing to install: enabling the plugin is enough. Note that a session's overlays are retired when it ends, which is correct and means a one-shot `claude -p` run shows no event-driven state by the time it exits. Two things survive that retirement, both held outside those overlays on purpose: the mark that its turn ended, so a run that finished and was never read can still say so, and the mark that the session itself ended, so a session that is over reads as over rather than as one sitting at its prompt waiting for you. A session with no end recorded is not known to be running — only a `SIGKILL` ends a Claude session silently, but a harness with no adapter, a session that started before the server did, and `--no-events` all look the same from here.

   Only add the hooks by hand if the user runs `event_hook.py` outside the plugin, for instance against a checkout. In that case:

```json
"hooks": {
  "UserPromptSubmit": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/launch.py\" \"<skill-dir>/event_hook.py\" claude", "async": true}]}
  ],
  "Stop": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/launch.py\" \"<skill-dir>/event_hook.py\" claude", "async": true}]}
  ],
  "PermissionRequest": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/launch.py\" \"<skill-dir>/event_hook.py\" claude", "async": true}]}
  ],
  "SessionEnd": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/launch.py\" \"<skill-dir>/event_hook.py\" claude"}]}
  ]
}
```

The harness name is the first argument and is required. Pass a **port** second for a non-default instance: `python3 "<skill-dir>/launch.py" "<skill-dir>/event_hook.py" claude 9999`. Note that this differs from `notify_hook.py`, which takes a whole URL.

Claude Code and Codex after-tool hooks also report fixed command shapes: force push, hard reset,
DROP TABLE in supported SQL-client forms, and recursive delete outside literal temporary prefixes.
Session detail and Attention show reports, not proof that an action succeeded. Missing hooks and
unmatched commands can look the same. Reports stay in memory for this run: newest 1,000 globally,
20 per session, at most 24 hours. Restarting clears them; duplicates and reordered delivery are possible.
Matching uses a nominal 5 ms best-effort wait, separate from startup and transport. Exact literal forms
and exclusions are in the project's security documentation; arbitrary shell syntax is not interpreted.

This path needs no configured secret. Each run of the dashboard generates its own capability and publishes it in its state file, which the hook reads; nothing is stored between runs. With no dashboard running the hook reads one small file and exits 0. A dashboard started with `--no-events` publishes no capability, so the hook stays silent.

### Codex

Codex sessions report through the **plugin's own bundled hooks** at `hooks/codex-hooks.json`, so there is nothing to add to a settings file. Codex asks the user to trust each hook once, and silently skips any hook it has not been asked about, so after installing the plugin tell the user to approve Compass's hooks when Codex prompts. Until they do, Codex rows keep the same scan-only behaviour they have today.

Eight events are registered: `SessionStart`, `UserPromptSubmit`, `PermissionRequest`, `PostToolUse`, `Stop`, `PostCompact`, `SubagentStart` and `SubagentStop`. Seven have been seen firing in a real session; `PostCompact` is the exception and is mapped on Codex accepting Claude's schema rather than on a capture, which is worth knowing before trusting a compaction row. `PreToolUse` fires too and is deliberately not used, because `PostToolUse` reports the same turn once the store has actually changed.

`PermissionRequest` is the one that makes a Codex row go red, and it is worth knowing what it does and does not do. Codex blocks the tool call on the hook and applies whatever the hook returns, so this is the one event where a reporting adapter could gate the user's own work. It cannot here, and this is measured rather than reasoned: a hook on this event that printed nothing and exited 0 let the approval prompt reach the person, who approved it, and the command ran. Empty output is how Codex is told the hook has no opinion. Compass never answers a Codex gate.

Two honest limits on that. The argument covers what the adapter *writes*, and a failure before it starts — no interpreter, an unreadable file — exits non-zero instead, which is a channel nothing here has measured. And the hook runs *before* the prompt is drawn, so its cost lands while the person is still waiting to be asked rather than after; it is one short-lived process, and the same one seven other Codex hooks already run.

### Pi

Pi reports extension UI prompts in persisted sessions through the bundled
`pi_extension.js` adapter. Validated on Pi 0.85.1: select, confirm, input, editor
and custom prompts enter the waiting queue; answering or canceling clears the wait.
Sessions shows the elapsed wait without publishing the prompt's title or answer.
Stock project trust and prompts before persistence are outside coverage. A missing
adapter, disabled event lane, or expired reading leaves block state unavailable;
restarting the dashboard does not recover a standing prompt.
Follow [Pi setup](https://github.com/spacedock-dev/compass/blob/main/HOW_TO_USE.md#report-pi-extension-prompts)
to install the adapter.

### Copilot

Copilot needs nothing installed at all: its own store records the permission prompt, so the collector reads the gate straight off `events.jsonl` with no hook, no adapter and no settings file in the way. Cursor is the other harness that works this way — see below.

The CLI writes `permission.requested` when the dialog opens and `permission.completed` when the human answers, joined on a request id. A request with no answer behind it is somebody being held up, and that is what turns the row red; the answer clears it on the next refresh, whichever way it went. Measured on 1.0.78: the request was on disk in the first frame the dialog was visible in all four timed arms, and prompts stood 36, 44 and 48 seconds on a shell gate and 23 on a URL one before anyone answered.

A new prompt typed into the session also clears it, and that is the only other thing that does. The answer is never written when the terminal is closed on the dialog or the process is killed at it, so without this a resumed session carries the dead request until it ages out of the activity window — red, and ranked ahead of the work it is visibly doing. A request also has to have stood a couple of seconds before it counts, which no prompt in front of a person ever notices and which keeps a headless run's auto-denial, written and answered a millisecond apart, from being caught half-written and read as a wait.

The row says a command is being asked about, or a URL, and stops there. It never carries the command itself, the URL, or the model's stated reason for wanting either, and a typed refusal does not reach the board.

Four limits worth knowing. A session directory with no `events.jsonl` is not a Copilot row in any state, gate or no gate: 3 of the 7 directories on the machine this was measured on had none, and the collector cannot see what is not written. A headless run (`copilot -p` without `--allow-all-tools`) auto-denies every gated call in about a millisecond and raises no wait, which is correct rather than a gap, since no human was ever going to be asked. Whether an unanswered prompt eventually gives up on its own is not something this has measured; the longest observed gate ran 48.5 seconds and was answered.

The fourth is the one to know before trusting a red Copilot row overnight. A session killed at its dialog looks exactly like a person who has walked away from one — the store records the question, never the process going away, and there is no lock file or pid beside it to ask. So a row can say a prompt has been standing for hours when the terminal it was in is long gone, and the wait ends when the session drops out of the activity window rather than when the prompt does. Answering it or typing to the session is what clears it; nothing else can.

### Cursor

Cursor needs nothing installed either, and for the same reason: its own store records the prompt. While a tool call sits in front of you, the chat's `store.db` carries a non-empty `pendingToolExecutionContracts` on its newest blob, with `pendingToolCallStartedAtMs` beside it saying when the wait began. Answering — approving or refusing, it makes no difference — appends a blob with the map emptied, and the row clears on the next refresh. Measured on 2026.08.11-e8db854 across four interactive `allowlist`-mode sessions, with gates standing 15 to 244 seconds.

The row says a permission request is open and how long it has stood. It never says what was asked. The contract entry beside the map names the tool three different ways, and none of them is read.

The hook route is deliberately not taken. `beforeShellExecution` runs before Cursor decides whether to ask you, and feeds into that decision, so a hook that reported a wait from there would be reporting a prompt it had just caused — on every command, whether or not anybody was ever asked.

Two limits. The first is the one to know before trusting a red Cursor row: the store is append-only, so a session abandoned at a prompt keeps its pending contract forever, and 2 of the 10 stores on the machine this was measured on still read as waiting 29.4 hours after their process had exited. Nothing in the store records a process going away, so Compass publishes the wait only while the session is fresh enough to be worth a row at all — the same freshness its title is gated on. That draws the line at the edge of the activity window rather than at the moment the terminal closed, which is as close as a passive reader can get.

The second is subagents. A Cursor child keeps its own store and appears as a pill on its parent's card, so a gate standing in front of a child is not read and does not turn anything red. Only a shell prompt was measured; MCP prompts, plan decisions and question tools were not, and whether they write the same record is unknown here. And where a store's blobs are encrypted — every one measured was plaintext, but the store carries a key for it — the record does not read and the session reports no wait.

### OpenCode

Copy `{baseDir}/opencode_plugin.js` into each project's `.opencode/plugin/compass.js`, then
start a fresh OpenCode session. Remove that copy and start a fresh session to uninstall.
The passive plugin reports parent `permission.asked` and matching `permission.replied` events;
Compass never answers them. Use `COMPASS_PORT` for a local port other than 4553 and the same
`COMPASS_HOME` as the dashboard when its state lives elsewhere. Missing state, disabled events,
transport failure and restart can lose observations. Child permissions and question events remain
unclaimed; no current event means block state is unknown. Measured on official OpenCode 1.18.30.

### Antigravity

Antigravity has two paths, and they do different jobs.

**Hooks are bundled with the plugin** (`hooks.json` at the plugin root), so nothing needs configuring for them. They fire after a tool step and after a model invocation, and they only tell the dashboard the store probably moved, which keeps an Antigravity row fresh without waiting for the next scan. They deliberately claim nothing about whether the agent is working or idle: Antigravity's hooks can fire several times in one turn, so treating them as turn boundaries would flap the row.

**Working and Idle state comes from the status line**, which cannot be plugin-bundled, so that half is opt-in. Point it at `statusline_hook.py`, which forwards both the quota figures and the lifecycle state:

```json
"statusLine": {"command": "python3 \"<skill-dir>/launch.py\" \"<skill-dir>/statusline_hook.py\"", "enabled": true}
```

Pass a port as the first argument for a non-default instance. This replaces the older `notify_hook.py <url>/api/usage` line, which still works and still feeds the quota band; the new script additionally drives Working state and sends the quota block *alone* rather than the whole status-line document, which carries the account email and the transcript path.

Two honest limits. The conversation id is blank until a conversation exists, which is measured: the return to Idle often cannot be reported, so the Working state carries a deadline and the collector decides again after it lapses. The second one is now settled, and not the way an earlier note here guessed. The status line does report a pending tool confirmation: driven to a real permission prompt, it pushes a confirmation-pending flag beside a `tool_use` state, and in the one arm that recorded it, every flagged push carried an id that names the session. An Antigravity row still does not report Needs input, for a different reason. The status line is a repeating render rather than an event stream, so the flag arrives in a short burst as the dialog opens — two or three pushes — and then not again until something redraws the pane, and the ordinary Working and Idle pushes that follow would clear the wait rather than leave it stuck. Reporting it needs a precedence rule that does not exist yet. An agent question raises no flag at all.

Paths 2 and 3 are complementary and can both be installed. Keep `Notification` on `notify_hook.py`: Claude Code can emit an input-waiting notification for a session that then carries on running, so it stays revocable side state rather than an authoritative state change. `SessionEnd` is useful on both, which is why it appears twice above.

