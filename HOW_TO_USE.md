# How to use Compass

What a person configures by hand, one task per section.

Installing the plugin gets you the dashboard. It cannot get you the things that live in your own
configuration: the ask-lane MCP server, the lifecycle hooks that make the board live, a relocated
store. A plugin has no business writing those files, so you write them, and this page is where the
procedures live.

Every command and every snippet here was run before it was written down. Where something could not be
run, it says so rather than guessing.

This page owns none of the following, and links to it instead:

| For | Read |
|---|---|
| Installing the plugin, per harness | [README.md](README.md#1-how-to-set-up) |
| Reading the board: session states, display modes, the queue of things waiting on you, starting and stopping | [compass/skills/compass/SKILL.md](compass/skills/compass/SKILL.md) |
| What works on which harness and which platform, and what was measured | [COMPATIBILITY.md](COMPATIBILITY.md) |
| What is read, what is sent, and what granting a permission means | [SECURITY.md](SECURITY.md) |
| Working on Compass itself | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Find the copy your commands will run

Every command below starts with a path to `server.py`, and there are usually two on the machine: the
one your harness installed and the one in a checkout. They are different builds and they answer
differently.

```bash
# The installed copy. The directory carries the plugin version, so it moves on every update.
find ~/.claude/plugins/cache -name server.py -path '*compass*'
```

On the machine this was written on that printed a 0.10.0 path while the checkout was 0.12.0. Pin
whichever you meant, and use it for everything in the session including `--status` and `--stop`:

```bash
SKILL="$(dirname "$(find ~/.claude/plugins/cache -name server.py -path '*compass*' | head -1)")"
python3 "$SKILL/server.py" --diagnose
```

Use the same interpreter every time. The one that started the server is recorded in its state file,
and a second Python on the PATH is the usual reason a hook works from one shell and not another. On
native Windows `python3` is not a reliable spelling; use `python` or `py -3`.

## Let a session ask you a question

Compass ships one MCP tool, `ask_operator`. A session that hits a decision it cannot make calls it,
the question appears as a card on your dashboard, the tool call blocks until you click an option, and
the option you clicked is what the session gets back. Nothing else Compass does reaches into a
running session, and this only happens because the session asked.

Two harnesses can reach it: Claude Code, where the plugin registers the server for you, and Codex,
where you register it yourself. Antigravity and Gemini CLI cannot, for reasons below.

It pays off on unattended runs. An attended session usually does not call the tool at all, because
ending its turn already reaches you. That was measured both ways and
[docs/design-ask-lane.md](docs/design-ask-lane.md) records the two trials, so do not install this
expecting your next attended session to start asking questions.

### Before either harness

A dashboard has to be running, or the tool has nowhere to put the question and answers the session
with a decline saying so. [SKILL.md](compass/skills/compass/SKILL.md#start) owns starting it.

Your installed copy has to contain `mcp_server.py`, beside `server.py` in the skill directory. If it
is missing, your release predates the ask lane and no amount of configuration will help:

```bash
ls ~/.claude/plugins/cache/*/compass/*/skills/compass/mcp_server.py     # Claude Code
ls ~/.codex/plugins/cache/*/compass/*/skills/compass/mcp_server.py      # Codex
```

The examples below use port 4601, because that is where they were run. The default is 4553.

### Claude Code: nothing to register, one permission to grant

The plugin declares the server itself, so there is nothing to add anywhere. Confirm the harness sees
it:

```bash
claude mcp list
```

```
plugin:compass:compass: python3 /.../compass/skills/compass/mcp_server.py - Connected
```

The tool arrives under a name qualified by both the plugin and the server key:

```
mcp__plugin_compass_compass__ask_operator
```

Guessing that name is the one setup step that fails silently, so read it from the harness rather than
writing it out.

The first call is gated in your terminal before it reaches Compass. At default permissions the call
is refused and nothing reaches the dashboard, so there is no card and no question. The session is
told:

```
Claude requested permissions to use mcp__plugin_compass_compass__ask_operator, but you haven't granted it yet.
```

Interactively that arrives as a prompt you can answer. In an unattended run there is nobody to answer
it, which defeats the point, so grant it in advance. The grant is per project directory, in that
project's `.claude/settings.local.json`:

```json
{
  "permissions": {
    "allow": [
      "mcp__plugin_compass_compass__ask_operator"
    ]
  }
}
```

With that in place the same session called the tool, the card appeared, and the clicked option came
back with no permission denial recorded. [SECURITY.md](SECURITY.md#the-ask-lane-ask_operator) owns
what granting it means and what it does not.

If your dashboard is not on the default port or not under `~/.compass`, export `COMPASS_HOME` in
the shell you launch the harness from. The manifest passes no environment of its own and the server
inherits the harness's, which is how the runs above reached a dashboard on 4601 with its state under
a scratch directory. No port needs configuring.

### Register the MCP server in Codex

The plugin does not register it. Point Codex at the `mcp_server.py` inside the installed plugin. The
CLI writes the table for you:

```bash
codex mcp add compass --env COMPASS_HOME="$HOME/.compass" \
  -- python3 ~/.codex/plugins/cache/<marketplace>/compass/<version>/skills/compass/mcp_server.py
```

That is the whole configuration, and writing it by hand into `~/.codex/config.toml` is equivalent:

```toml
[mcp_servers.compass]
command = "python3"
args = ["/Users/you/.codex/plugins/cache/compass-marketplace/compass/0.12.0/skills/compass/mcp_server.py"]

[mcp_servers.compass.env]
COMPASS_HOME = "/Users/you/.compass"
```

Three things about that path and that block:

- The version is in the path. Upgrading installs beside the old copy and leaves the table pointing at
  the version you registered, so re-run `codex mcp add` after an upgrade.
- The `env` block is only needed for a relocated `COMPASS_HOME`. Leave it out and the server looks
  in `~/.compass`, where a default dashboard publishes its state file.
- A port can be given directly instead: `args = [".../mcp_server.py", "4601"]` makes the server try
  4601 first. Verified with no state file at all to read.

Check it:

```bash
codex mcp list
```

`Auth: Unsupported` is normal, since the server has no authentication to support. The env value is
masked in that listing rather than dropped. Codex names the tool `mcp__compass__ask_operator`,
qualified by the server key alone, which is not the same shape as Claude's.

Codex gates the call too, and its own approval policy decides. Under a plain `codex exec`, whose
policy is `never`, the call never reaches Compass and the session is told `MCP tool call requires
approval, but approval policy is never`. With approvals available, `codex exec --approve-for-me`,
the same call went through end to end and Codex held the tool call for a 75 second wait before
delivering the answer. An interactive session raises an approval prompt on the first call instead.

Codex also has a per-server key for a standing grant:

```toml
[mcp_servers.compass]
default_tools_approval_mode = "auto"   # accepted values: auto, prompt, writes, approve
```

Codex validates those four values, but setting `auto` did not override `codex exec`'s `never` policy
and under `--approve-for-me` the call was approved either way, so nothing here proves what it does in
an interactive session. Treat it as the thing to try, not as verified.

One difference on the board: a Codex question arrives with no session id, so its card is answerable
but does not attach to a session row. [COMPATIBILITY.md](COMPATIBILITY.md) owns that contract.

### Antigravity and Gemini CLI cannot register it

Antigravity's MCP surface takes a non-empty `serverUrl` per entry, which is a URL. `ask_operator` is a
stdio server, a command and its arguments, and there is no field to put it in. Gemini CLI's extension
root carries hooks only and has no manifest surface to declare a server in. Neither is a gap waiting
on a small fix, and neither has a hand configuration you could add today.

### Checking it worked

| Check | Command | Good looks like |
|---|---|---|
| The dashboard is up | `python3 "$SKILL/server.py" --port 4601 --status` | `Compass: running on port 4601 (pid ..., since 12:16)` |
| The lane is on | `curl -s http://127.0.0.1:4601/api/data \| python3 -c 'import json,sys; print(json.load(sys.stdin).get("ask"))'` | `True`. Anything else means the lane is off. Do not grep for `"ask":true`: the payload is serialised with spaces after the colon, so that never matches |
| The harness has the server | `claude mcp list` or `codex mcp list` | connected, or `enabled` |
| The tool is reachable | ask the session to name its ask tool | the qualified name above, not a guess |

`--diagnose` will not help here. It reports where session stores are searched and says nothing about
the ask lane, and its `--json` output carries no ask-related key. It is the right tool for a missing
harness, not a missing question.

Claude Code's own MCP log, on macOS at
`~/Library/Caches/claude-cli-nodejs/<encoded-cwd>/mcp-logs-plugin-compass-compass/`, records the
connection lifecycle only. It did not contain the server's own diagnostics on either the working or
the refused path, so do not go looking there for the reason a question was declined. The reason is in
the text the tool returned to the session, which is written to be quotable.

### The off switch

Start the dashboard with `--no-ask` and the lane is closed in both directions: the routes refuse, and
the page offers no control because the payload carries no `ask` flag.

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"question":"probe","options":["a","b"]}' http://127.0.0.1:4602/api/ask
```

```
{"ok":false,"reason":"disabled"}
```

That machine-readable reason matters. A session asking a lane-off dashboard is told the truth rather
than that nothing is running, and the server stops there instead of shopping the question to another
dashboard that has the lane on. There is no per-project or per-session setting: the flag belongs to
the dashboard process, so turning the lane back on means restarting without it.

### What the session experiences

One tool call, blocked, returning one string: the label on the card you clicked, character for
character, never text from anywhere else. [SECURITY.md](SECURITY.md#the-ask-lane-ask_operator) owns
why the answer travels as an index rather than a string.

Everything else resolves to a decline the session can act on rather than an error it has to
interpret. Observed: nothing listening, the lane switched off, and the dashboard stopped while a
question was outstanding, which released the waiting session in 12 seconds. Each one ends by telling
the session to use its own judgement and say what it chose. A question nobody answers is retired
after five minutes and the session is told the same thing.

A second click on the same card is a no-op. Four answers racing one question produced one accepted
and three no-ops, and the session saw the first.

Compass will not answer your harness's own permission prompts, type into a terminal, or reach a
session that never called the tool.

## Make the board live rather than polled

Without hooks, state comes from reading session stores on a cadence. With them, a harness pushes
lifecycle events to the dashboard and the board reacts as things happen.
[SKILL.md](compass/skills/compass/SKILL.md#notifications) owns the hook JSON, the event names, and
which ones matter. What it cannot own is the absolute path those snippets need, because the shipped
skill body is installed without the repository and is forbidden to name one. Resolve it with `$SKILL`
from the first section, then paste the resolved path into the snippet.

Claude Code's hooks go in `~/.claude/settings.json`. Antigravity's status line goes in its own
settings file. Both are yours to edit; the plugin does not write either.

Analyze drift reads a Claude Code session's last turn once Claude Code records it finishing, which
it does when Stop hooks are registered (the plugin registers them), whichever board you view. Any
other harness can be read after its session ends only when its hooks reach this board.

## Install or migrate Droid hooks

Droid loads plugin hooks from `<root>/hooks/hooks.json` and supports Factory plugins via `.factory-plugin/plugin.json`.
Install Droid hooks from `compass-droid/`:

```bash
droid plugin install /path/to/compass-droid
```

Restart Droid after installation.

If you previously installed the Claude root (`compass/`) into Droid, migrate by uninstalling that copy first:

```bash
droid plugin uninstall compass
droid plugin install /path/to/compass-droid
```

This ensures Droid's `SessionStart` and `SessionEnd` hooks run with the `droid` harness argument and route to `/api/events/droid` rather than `/api/events/claude`, so Droid session lifecycle events join the existing Droid collector row. Droid Notification and permission events are not mapped.

## Report Pi extension prompts

This procedure was exercised with `@earendil-works/pi-coding-agent@0.85.1` on macOS.
Use the dashboard copy selected above and start Pi with its bundled extension:

```bash
pi -e "$SKILL/pi_extension.js"
```

For automatic loading, copy that file to `extensions/compass.js` under the Pi agent
configuration directory, then restart Pi or run `/reload`. Repeat the copy when updating
Compass. The default configuration directory is `~/.pi/agent`; a relocated
`PI_CODING_AGENT_DIR` changes it.

Pi and the dashboard must use the same Compass state directory and port. The extension
reads `COMPASS_HOME` (default `~/.compass`) and `COMPASS_PORT` (default 4553).
It reads the run's capability from the state file and sends only to 127.0.0.1.

After a normal model turn has persisted the session, an extension's select, confirm, input,
editor or custom prompt appears in Attention. Answering or canceling it clears the wait.
The adapter never answers a prompt. Stock project trust and prompts before persistence are
outside this coverage; other Pi versions need their own evidence. Without an effective event
reading, the session reports block state as unavailable. A dashboard restart loses a standing
wait; it is not restored until another prompt event arrives. `--no-events` disables reporting.

Measured shapes and the contained replay procedure are in
[the Pi capture](docs/captures/pi/README.md).

## Report OpenCode permission waits

OpenCode needs a copy in each project. From that project, with `SKILL` set to the
installed skill directory [found above](#find-the-copy-your-commands-will-run):

```bash
mkdir -p .opencode/plugin
cp "$SKILL/opencode_plugin.js" .opencode/plugin/compass.js
```

Start Compass, then start a fresh OpenCode session. The adapter observes the passive
`permission.asked` / `permission.replied` pair; answer in OpenCode. A standing parent-session
permission appears in Attention and clears after its last outstanding request is answered.
The default dashboard port is 4553. For a different local port, start OpenCode with
`COMPASS_PORT=48679 opencode`; set `COMPASS_HOME` in both processes if using a different state
home. No URL or remote destination can be configured.

To uninstall, remove `.opencode/plugin/compass.js` and start a fresh OpenCode session.
An already running session keeps its loaded plugin. Repeat the copy after a Compass update.
No global configuration is changed by this procedure.

Measured on the official OpenCode 1.18.30 macOS binary. Parent permissions only: child routing,
question events and terminal control are not covered. Missing state, disabled events, delivery
failure or a dashboard restart can lose an observation; a standing wait is not reconstructed.
Without a current event observation, the row says block state is unknown. The capability condition
names the installation requirement; it does not verify that a project has installed the file.
The adapter keeps at most 128 active/queued sessions and 64 outstanding requests per session;
request overflow retains that session's wait until the plugin restarts. It remembers the most recent
8,192 answered request identities to suppress duplicate delivery.

## See why a harness is missing

A collector skips a store it cannot read rather than taking the dashboard down, so a wrong path and an
idle machine look identical on the board. `--diagnose` is the only thing that tells them apart. It
reads local paths, writes nothing, transmits nothing, and starts no server:

```bash
python3 "$SKILL/server.py" --diagnose
```

Two traps in reading its output, both reproduced:

- **Read the store lines, not the harness lines.** `[ok  ]` beside a harness means the collector ran,
  not that it read anything. A directory at mode `000` and a file that is not a SQLite database both
  still printed `[ok  ] <Harness> 0 session(s)`, with the real problem further down under the stores.
- **The `overrides` line is narrower than it reads.** It lists only the per-harness store variables,
  so `COMPASS_HOME` can move everything Compass writes while that line still says `none`.

## Move it: ports, a second dashboard, and where state lives

`--port` moves the listener. `COMPASS_HOME` moves everything Compass writes, which is its state
file, the dismissal store, the history store, the annotation store and the daemon log. Two
dashboards on different ports coexist, and each
publishes its own state file.

The per-harness store variables `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME`, `COPILOT_HOME`,
`PI_CODING_AGENT_DIR` and `PI_CODING_AGENT_SESSION_DIR` point Compass at a store somewhere other
than its default. Set one and confirm with `--diagnose` that the store line moved, rather than
assuming it did.

`--host` moves the bind address, and it is the one flag here that changes who can read the board
rather than where you read it from. It takes two values: `127.0.0.1`, the default, and `0.0.0.0`,
every interface. Nothing narrower is accepted. `--host 10.0.0.2` is a usage error, not a bind, because
`--status`, `--stop`, the hook forwarders and the MCP server all reach the dashboard over loopback
and a single-interface bind does not answer there. Binding one interface is a reasonable thing to
want; it is refused rather than half-supported. IPv4 only, too: the server has never spoken IPv6, so
`--host ::1` is a usage error rather than a bind failure.

Nothing authenticates the reader that arrives. Whatever can reach the port reads the whole board:
every session's titles, prompts and project paths. It can also POST to the board, including stopping
the dashboard and answering a question a session is waiting on. The Host and Origin checks still
refuse a hostname, so a web page cannot rebind its way in, but they cannot tell one remote address
from another. [SECURITY.md](SECURITY.md#known-and-accepted) states the scope.

So the first thing to try is not this flag:

```bash
# On the machine you are reading from. Nothing on the dashboard host changes.
ssh -L 4553:127.0.0.1:4553 you@the-agent-machine
python3 -m webbrowser -t http://127.0.0.1:4553/
```

That gets a remote board over a channel that already authenticates you, with the dashboard still
bound to loopback. Reach for `--host` when there is no ssh to be had, such as a container publishing
a port or a VM whose host browser cannot see its loopback:

```bash
python3 "<skill-dir>/server.py" --port 4553 --host 0.0.0.0 --daemon
```

Then open `http://<the machine's address>:4553/`. Not its hostname: a name is refused whichever
address it resolves to, and that is the rebinding defense rather than a bug. `--daemon` re-spawns
itself on Windows and carries the address across, so a detached remote-bound dashboard stays remote
bound.

Both `--status` and `--stop` find a live instance by probing the port, so neither needs the home the
dashboard was started with. Tested: a dashboard started under a scratch `COMPASS_HOME` was stopped
by a `--stop` issued with no `COMPASS_HOME` at all, and its state file was cleaned up anyway, because
the process removes its own on the way out.

To analyze drift, press **Analyze drift** on the session page. It runs on your press and tells
you once what is sent and where. With no saved goal, the check adopts the goal drafted from your first
permitted Claude Code or Codex prompt, or from your latest prompt where no first prompt with a time
is published. **Use your prompt** beside the goal lists up to five of your own prompts from the
session; choosing one fills the goal box without saving it, and **Save intent** saves it. You
can also type your own goal. Adopted words say "from your prompt", and editing them makes a typed
goal. An unavailable prompt time means you must type a goal instead. The notice is remembered
across tabs and restarts and shown again if the destination or content tier changes. Where Compass
cannot name the destination (always on Windows and for a Codex base URL), a move between unnamed
destinations cannot be detected.
Use **Turn off readings** on a session page to revoke it. A Claude Code session is read by Claude
Code when `claude` is on the dashboard's PATH, and by Codex when it is not; every other session is
read by Codex, or by Claude Code on a machine without Codex. Checks spend the capacity of whichever
reads. **What is sent**, under the button, opens a short list naming it, and with neither installed that reason takes
the button's place and says no analysis can run. Turn off readings stops readings and goal
summaries; an off saved before an upgrade stays off. Analyze allows 100 attempts in a rolling
twenty-four hours and says when capacity becomes available again. Codex goal summaries are on by
default on a focused refresh, with their own one-time notice.

A Claude Code reading includes its checks by default where Compass can name the destination: the
command, result, last 180 characters of output and written paths. The notice names tool output too.
`--observer-model`, `--allow-tool-output` and `COMPASS_ALLOW_TOOL_OUTPUT=1` are accepted and do
nothing in this release; they will be removed in a later release. Turn off readings or
`--no-observer-model` stops these calls.

`--forget` also clears reading permission without resetting its rolling spend budget. It deletes the local history store and the session-end store, removes the records of any
session you discarded everything for, and exits. It belongs with `--status` and `--stop` rather
than in the table below, because what it does is not undone by running the next command without it:

```bash
python3 "<skill-dir>/server.py" --forget
```

It removes the history file whether or not the store was enabled, so turning the feature off and then
asking for the file to go does what it says. The discard-record sweep follows the same rule for the
same reason: `--no-annotations` is a switch for one run, not a statement about the file. The
session-end store goes with it, because both are the machine's memory of what it observed, and a
session whose end was recorded then reads as quiet again. Nothing over the loopback port can delete
history; this is the only way. It deletes nothing you typed: the goal and the expected outcome lines you wrote against a
session, and any reading made against them, go when you discard that session's words on its
session page. The one thing it takes out of that store is the record of a discard, which holds when the act
happened and no text, and is the machine's memory of something it did rather than anything you
wrote. It also deletes `compass-copied-corrections.json`, the digests of corrections you copied
from Compass, which hold no text either.

Stop the dashboard first if one is running. `--forget` refuses while an instance answers on the port
it names, because a running server keeps its own copy of the history in memory and writes the
deleted records back on its next observation, so the delete would report success and be undone a
few seconds later. The refusal is for the whole command rather than for that one store, so the
discard records are still there afterwards too, and the message names all three files. It finds the
instance with the same probe `--status` and `--stop` use, so `--stop` and then `--forget` is the
whole procedure.

## Alert once on a workflow stage

Open a project's Course tab, find Workflow stage conditions, choose a declared stage and press
Save. The first observation establishes a baseline. A later observed entry into the selected stage
trips the condition once. Already being at that stage does not trigger it, and an observation gap
does not imply a crossing.

Rearm permits another entry alert. Saving the same stage preserves its latch; changing the stage
starts a fresh baseline. Projects keeps saved conditions visible and removable after their source
session disappears. The card distinguishes a suspended source, a failed save and the notification
service's response. A service accepting an attempt does not prove a banner appeared.

## Turn a feature off

Each flag belongs to the dashboard process, so changing one means restarting.

| Flag | What stops |
|---|---|
| `--no-ask` | The ask lane, in both directions. See the off switch above |
| `--no-usage` | Credential-backed quota fetching. Disk-read quota evidence remains |
| `--no-dismiss` | Marking a session handled, and the store that remembers it |
| `--no-events` | The event coordinator. State comes from scanning stores rather than from pushed events, and the session-end store is neither read nor written |
| `--no-spacedock` | Reading Spacedock workflow state out of a project; saved stage conditions remain readable but suspended |
| `--no-tripwires` | Workflow stage conditions and every read or write of their saved store |
| `--no-git` | The end-of-session git probe. No git command runs inside any repository |
| `--no-history` | The local history of what the server observed. Nothing is written, and an existing store is not read back |
| `--no-annotations` | The goal and expected outcome lines you typed against a session. Nothing is shown or saved, and the page offers no field |
| `--no-focus` | Raising a session's terminal. No focus command runs, no terminal identity is recorded, and the page is offered no raise control. `--no-events` turns it off as well |
| `--no-observer-model` | Every model call, including goal summaries, reader-requested analyses and unasked checks. It overrides `--observer-model` and `--unasked-readings` for both Claude Code and Codex |
| `--no-reach` | Off-machine reach nudges. Outbound webhook nudges are disabled for this run |

[SKILL.md](compass/skills/compass/SKILL.md#options) owns the full option reference.

### Select the Claude reading model

Start the dashboard with `--claude-reading-model claude-sonnet-5` to select the Sonnet 5 baseline.
The default requests `claude-sonnet-5-5`. Use an explicit Sonnet or Opus generation 5 or later ID;
floating aliases such as `sonnet` are refused. An account that cannot use the chosen model gets a
failed reading, without a retry on another model. A daemon respawn keeps your selection.
The disclosure beside **Analyze drift** names the selected Claude model.
[SECURITY.md](SECURITY.md#amended-2026-10-05-claude-reading-model-baseline) owns the admission policy.

### Move the history's two bounds

The history keeps 14 days of observations inside a 1 MiB file, and both figures are flags rather
than constants:

```bash
python3 "<skill-dir>/server.py" --history-days 3 --history-max-bytes 262144
```

Either one alone still applies: narrowing the window drops what falls outside it, and the cap drops
the oldest first once the file would exceed it. Neither accepts zero or a negative number: a window
of zero days is a store that evicts everything it records, and `--no-history` is the switch for
turning the store off. A `--daemon` respawn carries whichever of the two you moved, so a restart
cannot widen a bound you tightened. What leaves the file is gone from it, so raising a figure back
afterwards brings nothing with it.

## Usage and quota

Usage quota reads and operator-configured reach nudges are the outbound requests Compass can make,
and neither sends anything until you configure it. The first time the dashboard opens on a machine
where a harness could be asked, a banner on Session operations, below the session groups, explains that answering yes lets
Compass read the credential that harness already stored and send it to that vendor for your usage
numbers. Until you answer, nothing is read and nothing is sent. The request carries the vendor's own
token and nothing else, behind a five minute floor.

Changing your mind takes one click: the capacity strip carries a switch that turns the fetch on or
off without a restart. `--no-usage` refuses it for a whole run whatever is stored in the page.
[SECURITY.md](SECURITY.md#usage-quota-reads-the-quota-fetcher) owns the contract, including what is
sent, what comes back, and what is never touched.

## Reach nudges away from the desk

When configured, Compass can post a scalar count to a webhook URL you provide when sessions
need input or finish unread while you are away:

```bash
python3 "<skill-dir>/server.py" --reach-url "https://ntfy.sh/my-topic"
```

The URL can also be set via the `COMPASS_REACH_URL` environment variable or saved in
`~/.compass/reach_url`. The payload contains only two count integers (`needs_input` and
`finished_unread`) and never includes session IDs, paths, titles, or prompt text. Outbound
nudges are disabled by default and can be suppressed for any run with `--no-reach`. See
[SECURITY.md](SECURITY.md#off-machine-nudges-reaching-the-operator-away-from-the-desk) for the
full security contract.

## Quiet hours

When configured, Compass suppresses non-urgent notifications (native popups, unasked checks,
tripwire alerts, and reach nudges) during a specified local time window:

```bash
python3 "<skill-dir>/server.py" --quiet-hours "22:00-08:00"
```

The window can also be set via the `COMPASS_QUIET_HOURS` environment variable or saved in
`~/.compass/quiet_hours`. The window format is `HH:MM-HH:MM` in 24-hour local time and can cross
midnight (e.g. `22:00-08:00`). Direct operator questions asking for input are not suppressed.
Quiet hours can be disabled for any run with `--no-quiet-hours`.

## Stop a dashboard, and unstick a port

```bash
COMPASS_HOME="$HOME/.compass" python3 "$SKILL/server.py" --port 4553 --stop
```

[SKILL.md](compass/skills/compass/SKILL.md#stop) owns the last-resort per-platform commands for a
port that stays held.

State files accumulate, but only from runs that never exited cleanly. A dashboard removes its own on
the way out, so a kill, a crash or a sleeping machine is what leaves one behind. They are inert, since
a stale record is told from a live instance by probing the port, but each one holds that dead run's
capability tokens and nothing sweeps them, so they are worth deleting by hand if you have collected a
pile.

## Troubleshooting

| Symptom | Likely cause | What to run |
|---|---|---|
| A harness's sessions are missing | Its store is elsewhere, or unreadable | `--diagnose`, and read the store lines rather than the harness lines |
| The board is empty and the harness is installed | You are running a different copy than you think | Re-pin `$SKILL` from the first section |
| A question never appears | The lane is off, or the first call was gated in the terminal | Check `"ask":true` in the payload, then check the grant |
| The session says no dashboard is running | It is looking at a different `COMPASS_HOME` or port | Export `COMPASS_HOME` in the shell that launches the harness |
| The session says the lane is switched off | The dashboard was started with `--no-ask` | Restart without the flag |
| A hook works in one shell and not another | Two Pythons on the PATH | Use one interpreter for everything |

Anything that looks like a defect rather than a configuration problem belongs in an issue. The
security contact is in [SECURITY.md](SECURITY.md).
