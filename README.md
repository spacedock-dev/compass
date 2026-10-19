# Compass

[![Validate](https://github.com/spacedock-dev/compass/actions/workflows/validate.yml/badge.svg)](https://github.com/spacedock-dev/compass/actions/workflows/validate.yml)
[![Quality Gate](https://github.com/spacedock-dev/compass/actions/workflows/quality-gate.yml/badge.svg)](https://github.com/spacedock-dev/compass/actions/workflows/quality-gate.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

Agnostic agent cartography and visualization.

Run as many coding agents as you like. Compass tells you which ones need you, which ones are fine,
and when it is safe to walk away. One local screen, every harness you use, and nothing leaves your
machine that you cannot switch off.

Use Intent and drift to compare a session's recorded work with your goal. Open a session, set a
goal and press `Analyze drift`. The `How Intent and drift works` button explains the steps, the
reading's limits and why an expected outcome line is needed for a drift level. The Claude reader's
accuracy check has not passed, and its latest correction is unmeasured, so read a level as an
account of the evidence, not a measurement.

It answers five questions, in the order a working day hits them. Which of my agents are running.
What is each one doing, and when should I come back. Is anything waiting on me. Will I hit the quota
wall before the work finishes. Did anything die quietly.
[What Compass promises](docs/promise-map.md) states each answer, names the shipped capability
behind it, and says where it stops.

Under that, Compass maps live coding-agent activity on your machine into a single local dashboard.
It shows sessions, subagents, task progress, turn ETAs, quota windows, and token output rate across
ten harnesses: Claude Code, Codex, Pi, Gemini CLI, Antigravity CLI, GitHub Copilot CLI, OpenCode,
Cursor CLI, Goose, and Factory Droid. Gemini CLI stopped serving consumer accounts in June 2026 and
Antigravity CLI succeeds it there, but enterprise and API-key use continues, so that row reads
either historical or live sessions depending on the account.

This repo contains one plugin, `compass`, the agent cartography dashboard skill.

---

## 1. How to set up

### Prerequisites

- Python 3.11+. The server is stdlib-only, so there is nothing to install alongside it. A
  [standalone binary](#standalone-binary) needs no Python at all.
- To install it as a plugin: Codex, Claude Code, Antigravity/AGY, or Gemini CLI.

You do not need all four. The dashboard maps every harness it finds on the machine regardless of
which one launched it, and it runs standalone with no client installed at all:

```bash
python3 compass/skills/compass/server.py --port 4553 --daemon
```

`--daemon` detaches so the dashboard keeps running after this shell exits. Stop it with `--stop`;
drop `--daemon` to run it in the foreground instead.

### Standalone binary

Every [release](https://github.com/spacedock-dev/compass/releases) attaches a build of the
dashboard that carries its own Python, so there is nothing else to install. Pick the archive for your
machine, `compass_<version>_<os>_<arch>.tar.gz` with `os` `darwin` or `linux` and `arch` `arm64` or
`amd64`, check it against `checksums.txt`, and run it:

```bash
grep compass_<version>_<os>_<arch>.tar.gz checksums.txt | shasum -a 256 -c
tar -xzf compass_<version>_<os>_<arch>.tar.gz
./compass/compass --port 4553 --daemon
```

It takes the same options as `server.py`. There is no Windows binary yet, and macOS may ask you to clear a
quarantine flag on a copy downloaded through a browser; [COMPATIBILITY.md](COMPATIBILITY.md#standalone-binary)
has the details and the limits.

See the [command manual](MANUAL.md) for every launcher option, defaults, environment variables
and examples, including controls for model use, history and notifications.

### Claude Code installation

Compass is listed in the shared Spacedock marketplace, so if you already have that marketplace you
only need the second line.

```bash
# Add the Spacedock marketplace (one-time setup, shared with the other Spacedock plugins)
claude plugin marketplace add spacedock-dev/marketplace

# Install the compass plugin
claude plugin install compass@spacedock
```

Restart Claude Code after installation.

### Antigravity / AGY installation

```bash
# From a local checkout, install the native AGY plugin
agy plugin install "$PWD/compass"
```

Restart AGY after installation.

### Gemini CLI installation

```bash
# From a local checkout, install the native Gemini CLI extension
gemini extensions install "$PWD/compass-gemini"
```

Restart Gemini CLI after installation.

Gemini installs from its own directory rather than from `compass/`. Both Claude Code and Gemini CLI
load extension hooks from `<root>/hooks/hooks.json` and neither lets that path be moved, so one shared
root would hand each harness the other's event names. `compass-gemini/` carries the Gemini manifest,
Gemini's hooks, and the two hook scripts they run.

### Droid installation

```bash
# From a local checkout, install the native Droid plugin
droid plugin install "$PWD/compass-droid"
```

Restart Droid after installation.

Droid installs from its own directory rather than from `compass/`. Both Claude Code and Droid
load plugin hooks from `<root>/hooks/hooks.json` and Droid also reads `.claude-plugin/plugin.json`,
so installing the Claude root into Droid would run hooks with Claude's harness argument and send
events to `/api/events/claude`. `compass-droid/` carries the Droid manifest (`.factory-plugin/plugin.json`),
Droid's hooks mapping measured lifecycle events, and the two hook scripts they run. If you previously
installed `compass/` into Droid, remove it with `droid plugin uninstall compass` before installing
from `compass-droid`.

### Codex installation

```bash
# Add the marketplace from a local checkout, then install the plugin
codex plugin marketplace add .
codex plugin add compass@compass-marketplace
```

Restart Codex after installation.

Installing the plugin is most of the setup. What is left is configured by hand, because a plugin
cannot write it for you: the ask-lane MCP server, Claude's lifecycle hooks, Antigravity's status
line. See [HOW_TO_USE.md](HOW_TO_USE.md) for one procedure per task.

---

## 2. Skills

| Skill | What it does | Standalone invocation |
|-------|--------------|------------------------|
| `compass` | Live agent-cartography dashboard: maps sessions, subagents, task progress, ETAs, and token rate across ten coding-agent harnesses, with input-wait notifications (native on macOS, browser notifications elsewhere) | `/compass:compass` |

In Codex, invoke it as `$compass`. In any harness you can also just ask: "open compass" or "monitor my agents".

## 3. How it works

The skill starts a stdlib-only Python server: `compass/skills/compass/server.py` is a small
launcher, and the dashboard itself lives in the importable `compass_runtime` package beside it. The
server reads local harness session stores read-only, meaning transcripts, task files, and SQLite
databases, and assembles the HTML, CSS and JavaScript under `compass_runtime/web/` into a
self-refreshing dashboard at `http://127.0.0.1:4553/`. The server binds to 127.0.0.1 unless you ask
for another address with `--host`, which has no authentication behind it. Session content stays on
the machine by default. The quota poll requires disclosure consent, carries a vendor token and no
session content, and can be disabled with `--no-usage`. Model calls can send session content
through an installed Claude Code or Codex CLI. Analyze drift runs on your press; Codex goal
summaries run on a focused refresh by default. Each tells you once what is sent and where, and
tells you again if the destination or content tier changes. Turn off readings or
`--no-observer-model` stops them. Unasked drift checks remain a separate opt-in.
Dashboard assets, including the optional terminal's vendored xterm files, need no external fetch.
A third outbound pathway sends counts-only nudges to an operator-supplied endpoint. It stays off
until you configure a URL, and `--no-reach` disables it. See [SECURITY.md](SECURITY.md#scope)
for all three, and before you use `--host`; its [model-call policy](SECURITY.md#observer-model-calls)
owns the disclosures and bounds.

The dashboard opens on Sessions. The tabs run Sessions, Projects, Attention and Intent log.
Projects groups sessions by the label their harness publishes, and each project opens a cockpit
with a Scope rail and a persistent Where this project stands briefing,
and Now, Course, Decisions and Console tabs. Each session's own page leads with drift: there you
type the goal you are holding that session to, optionally add an expected outcome, and check it for drift with one
press, and read back what has been raised about that session and what became of the raise.
Sessions keeps an orientation paragraph and how-to visible after a session has been checked.
The paragraph explains analysis when annotations are on, the store is readable and a reading
route names a provider; otherwise it explains how to inspect a session. Every goal
cell, including saved words, opens its session at Intent.
A finding can jump to the entries it cites in Session activity, marked with its words and their
current numbers. Departure citations retain the neutral "Cited" tag. A current result has no rerun
button; new work or changed intent gives one "Analyze again" with that reason.
Console collects delegation, waiting requests,
capacity and browser-local tripwires. The terminal bridge and semantic history remain prototypes;
the [cockpit design contract](docs/design-next-ui.md#cockpit-reconciliation) records their limits.
Sessions puts active work above recent history, counts active now and working, and gives each active session the same four facts: where it
is, what it is doing now, what it does next, and whether it is blocked.
Attention collects what needs a human, and the Intent log lists every board session plus retained
annotations, with typed, cached deterministic and workflow goals labeled by source. Keyboard shortcuts `s`, `p` and `a` reach
Sessions, Projects and Attention; the Intent log is a nav link with no shortcut.
A session opens under the tab you opened it from, and `Escape` returns there; a pasted link opens it
under Sessions. Every other view's `Escape` returns to Sessions. The route lives in the URL fragment
so a reload or a pasted link comes back to the same view.

New to Intent and drift? Open "See a sample session (view only)" above the Sessions list: an
anonymized session that drifted, with its stored reading, the correction Compass composed and numbered
(i) marks that explain each part. Nothing in it is saved, sent or run.
[The design record](docs/design-sample-session.md) says how it works.

See [compass/skills/compass/SKILL.md](compass/skills/compass/SKILL.md) for data sources, session states, options, and troubleshooting.

## 4. Validation

The canonical pre-PR suite lives in [AGENTS.md](AGENTS.md#pre-pr-checks): lint, types,
frontend lint, types and tests, the contract validator, tests under coverage, and the native plugin validators.
Contributors should start from [CONTRIBUTING.md](CONTRIBUTING.md), which walks through setting it up.

See [COMPATIBILITY.md](COMPATIBILITY.md) for the cross-platform contract.

## 5. Contributing

Contributions are welcome, and new harness support is especially useful. Start with
[CONTRIBUTING.md](CONTRIBUTING.md) for setup, validation, and PR conventions. This project follows
the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). Please report security issues
privately, as described in [SECURITY.md](SECURITY.md).

## 6. License

Compass's code and documentation are licensed under the [Apache License 2.0](LICENSE). See
[NOTICE](NOTICE) for attribution. The bundled Space Grotesk and IBM Plex Mono font subsets retain their
SIL Open Font License notices in `compass/skills/compass/compass_runtime/web/fonts/`.
