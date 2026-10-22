# Codex, Claude Code, Antigravity, and Gemini CLI compatibility

The repository keeps one shared skill implementation for all clients. Platform-native wrappers are retained only when the platform owns the behavior.

| Surface | Codex | Claude Code | Antigravity / AGY | Gemini CLI | Repository contract |
|---|---|---|---|---|---|
| Package marker | `.codex-plugin/plugin.json` | `.claude-plugin/plugin.json` | `plugin.json` | `../compass-gemini/gemini-extension.json` | Each runtime receives its native root/manifest shape. Gemini's and Droid's (`../compass-droid/.factory-plugin/plugin.json`) are separate roots: see Hooks below |
| Skills | `/skills` or `$compass` | `/compass:compass` | Bundled plugin skills | **Not bundled** | Shared `skills/compass/SKILL.md`. The Gemini extension root carries hooks only, so Gemini users launch the dashboard directly rather than through a skill |
| Skill UI metadata | `agents/openai.yaml` | Ignored | Ignored | Ignored | Optional Codex presentation data beside the shared skill |
| MCP | Not registered by the plugin; the user registers it themselves, and [`HOW_TO_USE.md`](HOW_TO_USE.md#register-the-mcp-server-in-codex) owns that procedure. Gate and hold measured attended on codex-cli 0.146.1 (`mcp-ask-gate-0.146.1`), and a round trip ran end to end there too, answered at index 1 (`ask-roundtrip-0.146.1`). A Codex ask arrives with no session id, so its card is answerable but does not attach to a session row | Registered: `mcpServers` in `.claude-plugin/plugin.json`. Gate and hold measured attended on 2.1.239 (`mcp-ask-gate-2.1.239`), and the plugin-declared path is measured too: loaded with `--plugin-dir`, it produces the tool `mcp__plugin_compass_compass__ask_operator`, and one round trip ran end to end through it, answered at index 0 (`ask-roundtrip-2.1.239`) | Not registered. Antigravity's MCP path takes a `serverUrl` only and cannot express a stdio server without a validator change | Not registered. The Gemini extension root carries hooks only, so there is no manifest surface for it | One stdio server, `compass/skills/compass/mcp_server.py`, serving one tool, `ask_operator`. Session data still comes from reading local stores; the server exists so a session can ask the reader a question and wait. Two kinds of capture, and they answer different questions: the gate and the hold in `docs/captures/{claude,codex}/mcp-ask-gate-*.jsonl`, the round trip and the decline paths in `docs/captures/{claude,codex}/ask-roundtrip-*.jsonl`. [`SECURITY.md`](SECURITY.md) owns the contract and the standing permission it needs, [`docs/design-ask-lane.md`](docs/design-ask-lane.md) the rejected alternatives |
| Hooks | `hooks/codex-hooks.json` | `hooks/hooks.json` | `hooks.json` | `../compass-gemini/hooks/hooks.json` | Bundled per harness, each in the path that harness reads, each in that harness's own event vocabulary. The vocabularies do not overlap enough to share a file: a foreign event name is skipped with a warning on every session. `scripts/validate_plugins.py` fails the build on a foreign name or a foreign harness argument. Droid also ships in its own dedicated root `../compass-droid/` (`hooks/hooks.json`) |
| Recurring runs | Invoke the skill one pass at a time | Invoke the skill one pass at a time; a scheduler plugin can repeat it | Invoke the skill one pass at a time | Invoke the skill one pass at a time | The skill remains useful as a one-shot workflow |

Command-shape reports cover Claude Code and Codex `PostToolUse`, tool `Bash`, with installed
hooks. Their input field was measured on macOS; the same bounded Python matcher and subprocess
containment tests run on macOS and Linux in CI. Platform-specific shell forms are not admitted.
Claude's nonzero call emitted `PostToolUseFailure`; Codex's still emitted `PostToolUse`.
A report therefore does not establish success. Other harnesses say reporting is unsupported.
`--no-irreversible` and `--no-events` disable the feature, including daemon respawn.
[SECURITY.md](SECURITY.md#irreversible-actions-hook-side-destructive-shape-matching) owns the exact
forms, exclusions, current-run retention and qualified timing contract.

Downgrading can discard checklist lines or saved annotations. Read the
[annotation-store downgrade limits](docs/design-reading-a-session.md#amended-2026-09-24-an-intent-revision-and-a-reading-hold-more)
before using an older build.

## Platform-specific behavior

CI exercises the dashboard unit suite on macOS and Linux, the frontend development checks on macOS,
and production-bundle parity proofs on Linux. Windows is no longer exercised by CI for the dashboard
unit suite or frontend. Local checks remain available; the capability matrix below describes the
implementation, not continuous verification on every platform.

This file owns the Python floor. The dashboard server is stdlib-only Python 3.11+, with
`datetime.UTC` setting the floor, and it runs identically regardless of which harness launched it.
`sqlite3.Connection.blobopen` holds it there too, since the Antigravity collector uses it to read
the last 64 bytes of a generation blob without materialising a row that can run past 700 KB.
The floor is restated in eleven other places across eight files, which must all move together:
`README.md`, `CONTRIBUTING.md` (three times, in the prerequisites, in the `runtime-floor` bullet of
the quality-gate list, and in the dashboard implementation constraints),
`compass/skills/compass/SKILL.md`, `docs/promise-map.md`, `.github/PULL_REQUEST_TEMPLATE.md`,
`AGENTS.md`'s quality-gate paragraph, and `pyproject.toml` (`[tool.ruff] target-version` and
`[tool.mypy] python_version`), plus the Python 3.11 direct-launch smoke in
`.github/workflows/quality-gate.yml`. The documentation-matches-code test guards three of them, the
`SKILL.md` copy and both `pyproject.toml` fields, and the runtime-floor job exercises the shipped
entry point on Python 3.11. The rest are on you.

| Capability | macOS | Linux | Windows | WSL2 |
|---|---|---|---|---|
| Harness discovery, dashboard, `/api/data` | yes | yes | yes | yes (Linux-side stores) |
| Pi nested and flat session stores | yes | yes | yes | yes (Linux-side stores) |
| Turn ETA, token rate | yes | yes | yes | yes |
| Task age from file birthtime | yes | falls back to mtime | Python 3.12+ only | falls back to mtime |
| Needs-input popup, browser (tab open) | no (the server delivers it) | yes | yes | yes (host browser) |
| Needs-input popup, native (no tab) | yes (`osascript`) | not yet | not yet | not yet |
| Ask-lane popup, browser (tab open) | not needed | yes | yes | yes (host browser) |
| Ask-lane popup, native (no tab) | yes (`osascript`) | not yet | not yet | not yet |
| Gone-quiet popup, browser (tab open) | no (the server delivers it) | yes | yes | yes (host browser) |
| Gone-quiet popup, native (no tab) | yes (`osascript`, Claude only) | not yet | not yet | not yet |
| Terminal raise from the gate queue | yes (tmux, one attached client) | not yet | not yet | not yet |
| Claude quota token read (the usage fetch) | Keychain via `security`; the first read can prompt | credential file | credential file | credential file (Linux-side home) |
| Cursor quota token read (the usage fetch) | Keychain via `security`, service `cursor-access-token` | no (see below) | no (see below) | no (see below) |

Exactly one layer delivers a given popup: the server where it has a native backend, the page otherwise. `/api/data` reports which as `native_notify`. The split covers an arriving `ask_operator` question as well as a needs-input transition, which is why the ask rows above read the same way. It covers a session going quiet too, with one asymmetry the rows record and the sentence cannot: the native layer fires off Claude's own idle hook and so reaches only Claude, while the page has no hook and fires on any harness's row when it stops looking busy. Those are near the same moment and not the same event, so the wording differs by layer. Both layers are harness-independent: the server decides once per collected row, whatever harness produced it, so a Codex gate is delivered on macOS exactly as a Claude one is. That is new. The server used to fire only from Claude's collector, which left a gate on any other harness with no popup on macOS at all while the page stood down for it.

The terminal raise is recorded only on the platform the case was measured on, so a target is never stored off macOS and every row elsewhere reports no reachable terminal. Linux needs more than a measurement: the device grammar the contract fixes admits `/dev/ttys004` and refuses `/dev/pts/3`, so widening it is a contract change and not a platform port. tmux is the only arrangement named, one attached client is required (`switch-client` moves the window every client of that session displays, so two clients means somebody else's view moves too), and a session that predates the running dashboard has no recorded target. `--no-focus` turns the whole thing off, and so does `--no-events`.

Notification delivery is best-effort by design, on every platform. The exit criterion is graceful degradation plus a reported delivery status, not a guarantee: browser notifications need the user's permission and an open tab, `notify-send` needs a graphical user D-Bus session, and a Windows toast needs an interactive session (and, from WSL, enabled interop). A backend that cannot deliver must no-op quietly, never raise.

What that status now says, and what it does not. A server-side raise about a session records one of
five outcomes: handed to this machine's notification service, the service returned an error, the
command could not be started at all, the call did not return inside its time limit, or this platform
has no backend in this build. A raise whose subject carries no session id records nothing, because
the record is keyed by session and inventing a key would be worse than the gap. A zero return from
`osascript` is the first of those and is not a delivery: it exits zero under Do Not Disturb and with
the hosting application's notifications switched off, so the call returning says the service accepted
it and nothing about whether a banner was drawn or anyone was at the desk. On a platform with no
server-side backend the page may report that it has a notification lane of its own, which is a
statement about a tab rather than about a raise: see
[DEC-19](docs/design-reading-a-session.md#dec-19-the-page-may-report-a-lane-never-a-delivery).

The unasked reading lane raises through the SERVER side of this same lane and records the same
outcome, so everything above about a server-side raise applies to a departure. The browser half does
not: the page raises on edges it computes from the payload, and a departure is not one of them, so on
Linux and Windows a departure reaches the delivery record and no banner. It also needs a working
`codex` CLI on the machine, which is the dependency a reader-requested reading already has, and it is
off by default on every platform.

The operator-cockpit prototype's terminal registration is unsupported on native Windows. Its
tmux bridge consumes registration capabilities only after POSIX ownership, mode and no-follow
checks; Windows cannot pass those checks. The registration client reports this platform
restriction. Shutdown can still remove its own registration file on every platform: a separate
bounded regular-file read compares the server generation without trusting any capabilities.

Verified by hand: on macOS, a `--daemon` server delivers the native notification with no browser tab
open at all, since the double-fork keeps the daemon in the user's own login session rather than
moving it to a new one, which is the main reason daemon mode is worth having. That confirms `osascript`
reported success, not that a banner was visibly displayed; Focus and Do Not Disturb can still
suppress on-screen display independently of whether the process is detached. See
[`docs/design-daemon.md`](docs/design-daemon.md) for how this was verified.

### `--daemon`, `--status`, `--stop`

`--daemon` detaches so the dashboard outlives the session that started it: a double-fork on POSIX,
a detached re-spawn on Windows (there is no `fork` there). Both bind the listening socket (or, on
Windows, wait for the re-spawned child to prove it bound, over `/api/health`, matching the answering
pid against the child's own so a dashboard already on that port cannot be mistaken for it) before reporting
success, so a busy port still fails loudly on every platform instead of silently in a log nobody was
told about.

The per-port state file and log live under `~/.compass`, one layout on every platform;
`COMPASS_HOME` is authoritative when nonblank, the same rule the harness store relocation variables
follow. Nothing ever removes or rotates the log, so `~/.compass` accumulates one log file per port
indefinitely. See [`SECURITY.md`](SECURITY.md) for the written-paths contract.

Other notes:

- Needs-input detection reaches six harnesses of the ten. Claude Code has four sources of its own, and the fourth is about a subagent rather than the session: a member listed in the teams registry that has written no transcript was dispatched and never started, which is the shape an agent parked on a startup permission prompt takes on disk. That one is bounded at both ends, since the registry stamps a join and never ages it: a member is read this way only once it has been registered longer than a healthy agent takes to start, and only while its session is still inside the activity window. Nothing detects a gate that opens after a member has started. The registry does now carry one per-member flag, `isActive`, which Claude Code 2.1.259 sets false on a member it has finished with rather than pruning it, and that separates finished from live; it says nothing about whether a live member is blocked or busy, and an inbox never carries a reply. The flag is read only to demote a member transcript freshness already reads as running, never to promote one, because whether a hard-killed pane clears it is unmeasured. Codex has one, its bundled `PermissionRequest` hook, which was measured firing in an interactive session with the approval prompt still on screen. That hook is the whole of its gate reporting, so the capability reaches only an operator who runs Codex with approvals enabled: with approvals off no prompt opens, the hook never fires, and a quiet Codex row says only that nothing asked. The payload declares that condition beside the capability and the coverage line prints it, because nothing can read it off a config file: `approval_policy` is overridable per invocation and per project, so a global reading cannot say whether a given session will ask. Copilot needs no hook at all: its CLI writes `permission.requested` to `events.jsonl` when the dialog opens and `permission.completed` only when the human answers, joined on `data.requestId`, so the collector reads an unanswered request as a standing gate. That was measured on 1.0.78 across six interactive sessions, with the request on disk in the first frame the dialog was visible and gates standing 23 to 48 seconds. Cursor takes Copilot's route on a different store, and also needs no hook: a standing tool-call gate leaves `pendingToolExecutionContracts` non-empty on the newest blob of the chat's SQLite store, and answering it appends a blob with the map emptied. That was measured on 2026.08.11-e8db854 across four interactive `allowlist`-mode sessions, with gates standing 15 to 244 seconds and the record readable through the collector's existing read-only connection. OpenCode adds a per-project passive permission plugin; Pi adds extension UI prompt callbacks on 0.85.1 for persisted sessions, excluding startup trust. Both require events enabled, disclose their installation condition and lose standing observations on restart. The other four have no shipped gate path, so the payload declares the capability per harness and the page marks those rows rather than letting their silence read as an all-clear. Three per-harness limits ride with that: a Codex row can say a gate is open without saying which, because the event envelope drops the tool name at the hook; a Copilot row reports only whether a command or a URL is being asked about, because the command text and the model's stated reason are the class of value Compass does not read; and a Cursor row says only that a permission request is open, since the three fields that would name the tool sit in the same contract entry the reader deliberately stops short of. A Copilot session directory that holds no `events.jsonl` is not a row in any state, so it cannot report a gate either; 3 of 7 directories on the probe machine were in that position. And a Copilot gate has no liveness signal behind it: the store records the question and never records the process going away, so a session killed at its dialog reads the same as a person who walked away from one. A prompt typed into the session retires the request, which covers a session that was resumed and is working again; a session that never comes back keeps its red row until it ages out of the activity window. Cursor has the same hole and a sharper version of it: its store is append-only, so a session abandoned at a gate stays pending in the file forever, and 2 of 10 untouched stores on the probe machine still read as waiting 29.4 hours after their process exited. Its wait is therefore published only while the row is inside the activity window, which is the same freshness its title is already gated on. A Cursor subagent's gate is not read at all: a child folds onto its parent's card as a pill and its own store is never published. Delivery is not a limit: a Codex, Copilot or Cursor gate raises a popup on every platform Claude's does, on the same terms. The ask lane is a different mechanism and is not detection at all, so it does not follow that line: an `ask_operator` question is raised by the session itself over MCP, which means any harness that can register the stdio server can put a question on the board no matter what its store records. Which harnesses those are is the MCP row above.
- Re-entry commands reach two harnesses of the ten, and only where the verb was read off the installed CLI's own help rather than off its documentation: `claude --resume <session-id>` on Claude Code 2.1.261, and `codex resume <SESSION_ID>` on Codex 0.153.4. A gate-queue row for either one carries a control that copies that command; the other eight publish no session id their CLI would accept, so their rows carry no control, because a guessed verb costs the reader a failed command on top of the hunt it was meant to replace. The id is not always the one the row displays. Claude's is the whole transcript stem, since the CLI refuses the eight-character prefix a Claude row shows, and Codex's is the rollout id it already publishes. Neither CLI lets a second process onto a live conversation, and both refuse in a way that names what to do next, so the control ships with no warning attached; [`docs/design-next-ui.md`](docs/design-next-ui.md) records what each refusal looks like and [`SECURITY.md`](SECURITY.md) owns the grammar the copied token has to satisfy.
- Turn-end events reach only the four harnesses with turn-end hooks, Claude Code, Codex, Antigravity and Gemini CLI, each through the hooks bundled for it, so only their rows can tell a session that finished and went unread from one still waiting on a reply that never came. The other six (Pi, Copilot, OpenCode, Cursor, Goose and Droid) are read by scanning their stores, and their rows say the answer cannot be known there rather than guessing at it. No collector may infer a completion.
- A reader-requested reading has two reaches and neither is the whole board. A final reading rests on an observed session end, and `ended_at` is patched only by the event overlay reducer, so only the four turn-end-hook harnesses above can ever carry one. A scan-only row still reads mid-flight while it is running and claims no finality; idle, it says no end can be observed there rather than that nothing finished. The expected-output constraint is narrower again: only Pi publishes a demonstrated work result on its own, a validation run read under DEC-23's rules. Claude Code shows its checks only under a tool-output grant, and since 2026-10-03 a reading you press for also puts the constraint to the model whenever the agent's own messages are among what it reads, with or without that grant; an unasked reading never sends them. On the other eight harnesses that constraint is never put to the model at all rather than answered weakly. What a reading reads against is narrower still on some harnesses: Antigravity's record is the person's typed directions alone, and Copilot, Cursor, OpenCode, Goose, Droid and Gemini CLI have no observed-record reader (Compass reads only their prompts and titles), so a press there withholds in its own sentence and spends nothing. A Codex reading is the second caller of the one bounded `codex exec` subprocess the observer model uses, and a Claude Code reading runs one bounded `claude --print`, so on every platform a press needs an absolute `codex` or `claude` on the server's PATH and reports the model unavailable without one, having spent nothing. The accepted Codex case review enables the control, and the first press asks for consent, remembered for that provider across tabs and restarts. Reader-requested readings need no `--observer-model` startup flag; `--no-harness-usage` and its alias `--no-observer-model` refuse every model call. Every Claude Code qualification run failed, and the owner accepted its producer anyway on 2026-10-02, so a Claude Code session is read by Claude Code when an absolute `claude` is on the server's PATH and by Codex otherwise. Every model call runs in a process group of its own, and a timeout, a shutdown or a reader's Cancel kills that group: a POSIX session on macOS and Linux, where a helper that leaves the group (by `setsid` or `setpgid`) is not reached, and on Windows a kill-on-close Job Object the child is placed in while suspended, which requires a local native Windows test run and is no longer exercised by CI. The exit is watched without reaping, by `waitid` on Linux and a kqueue exit filter on macOS, so the group can be swept while its leader still holds the id; the reap and the end of signalling are one step under the group's lock, and an exit neither can watch is polled rather than guessed. The poll reaps the leader, so on that path helpers still in its group after a normal exit are not swept; a timeout, a shutdown or a Cancel still kills the group, because each kills before the reap. It has been seen only under forced errors, and a test pins it; on that path a helper still writing after the leader's exit is not reached, so its writes are not bounded either ([SECURITY.md](SECURITY.md) states the cost). On Windows the prompt is written from a thread of its own and the call waits with `process.wait`, so a CLI that never reads its stdin still meets the call's timeout. A call whose output file passes 1 MiB is killed the way a Cancel kills it, on every platform: the size is checked every 0.01 s while the CLI runs and once more after its group or Job Object has no live writer. Watched POSIX cleanup holds the leader unreaped while observing the killed group's process states; Windows waits for the Job Object's active-process count to reach zero. An uncertain or timed-out observation refuses the reply. The documented POSIX poll fallback cannot make that final-writer guarantee. [SECURITY.md](SECURITY.md) owns what the call may send, and [docs/design-reading-a-session.md](docs/design-reading-a-session.md) the shape contract the answer has to satisfy.
- Spacedock workflow detection covers Claude Code, Pi and Codex. Claude rests on an `agentSetting` in the first transcript records plus the first officer's boot output. Pi writes no `agentSetting`, so a session is taken to be a first officer when its transcript carries the boot envelope itself; that costs a transcript scan per Pi session, where Claude pays one cached lookup and skips the scan entirely. Pi gets no ensign role and no bolded entity, because it reports no workers. Codex also attaches a workflow from a supported command-output boot result, including its captured fulfilled wrapper with integer exit code zero and one complete boot object. Its badge follows that evidence; no Codex ensign role is inferred. Pi forks and clones remain independent rows, not subagents.
- Pi is the only store-scanned harness that records *how* a turn ended, and Compass reads it: an assistant record carries a `stopReason`, so a Pi row can say a tool is in flight or that the turn is over without waiting on an event adapter it does not have. That is narrower than the turn-end line above rather than an exception to it. Knowing a turn ended is not knowing whether its result was read, so a finished Pi session and one waiting on a reply that never came still read alike. `compass/skills/compass/SKILL.md` owns what each spelling means and the ceiling the in-flight reading carries.
- Loop detection, the failed tool calls behind a long turn's explanation, is also Claude Code only. That covers all three of its readings: the consecutive run, the request total, and a request in which nothing succeeded. Claude is the only harness that records whether a tool call failed, so every other row reads as not measured rather than as nothing failed, and none of them ever carries the signal. `compass/skills/compass/SKILL.md` owns what the signal means and which record each of the other harnesses is missing.
- Pi scans the nested default store under `~/.pi/agent/sessions` and a flat custom store. `PI_CODING_AGENT_SESSION_DIR` is the authoritative direct-store override and wins over `PI_CODING_AGENT_DIR`, the global `sessionDir` setting, and the default. `PI_CODING_AGENT_DIR` relocates the configuration root, including its global `settings.json`; a relative global `sessionDir` resolves there. A separate process cannot infer a one-off Pi `--session-dir` or a project-local `.pi/settings.json`, so expose the effective store with `PI_CODING_AGENT_SESSION_DIR` when either is in use.
- Store locations resolve per platform, and `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME`, `COPILOT_HOME`, `PI_CODING_AGENT_DIR`, and `PI_CODING_AGENT_SESSION_DIR` are honored. Run `server.py --diagnose` to see every path searched and what was found there.
- WSL2's `localhostForwarding` defaults on but can be switched off, and mirrored/NAT networking modes or corporate policy can also break host-browser access to `127.0.0.1:4553`. Probe before assuming; the fallback is `ssh -L` or a browser inside WSL.
- Supported WSL topology is server and agents on the same side of the boundary. Reading a Windows-side store from inside WSL works over `/mnt/c`, but 9p latency and mtime granularity make state detection unreliable, so it is not supported.
- `sqlite3` is an optional stdlib module. On a build without it (some musl/Alpine images) OpenCode, Cursor and Goose report undiscovered. Antigravity still appears, since its discovery and state come from store mtime and CLI logs, but without a token rate or turn ETA. Copilot also still appears, because it is discovered and read from JSONL events, but its `used` figure in the usage section is absent, since that figure comes from a SQLite store.
- Quota follows discovery, for every harness. A harness that is not discovered publishes no usage entry and, if it is one of the fetched ones, is never fetched for either. Two consequences are worth knowing because neither is obvious from the quota path itself: on a build with no `sqlite3` Cursor's quota is absent even though the fetch needs no SQLite, and a freshly installed Cursor CLI with no conversation yet is undiscovered, so its quota waits on the first chat. This is deliberate. The alternative is a quota tile for a harness the machine shows no other sign of using.
- Gemini CLI stopped serving consumer accounts (Google AI Pro, Google AI Ultra and the free individual tier) on 2026-06-18, and Antigravity CLI is the successor for those users. Enterprise Gemini Code Assist licences and API-key authentication were explicitly unaffected, so on a machine using either of those the CLI still runs and still writes `~/.gemini/tmp`. This file owns that distinction; it is restated in `README.md`, `compass/skills/compass/SKILL.md` and `docs/design-harness-registry.md` (H-2), which must move together. Gemini and Antigravity are two harness rows. Antigravity is the current consumer one, and the Gemini row reads `~/.gemini/tmp`: historical on a consumer machine, where its sessions read as idle and need `?all=1` to appear, and live on an enterprise or API-key one, where they appear like any other harness. `GEMINI_CLI_HOME` relocates both, since Antigravity's store sits inside the Gemini home.
- Cursor's quota tile is macOS-only. The Cursor CLI keeps its session token in the macOS Keychain, and where it persists that token on Linux and Windows has not been verified, so those platforms read no credential rather than a guessed path: Cursor's sessions still appear, only its usage entry is absent. Verifying the location on either platform is what lifts this, and it needs the CLI installed there. Every other harness's usage figure is platform-independent.

Pi extension gate reporting was measured on `@earendil-works/pi-coding-agent@0.85.1`
on macOS. This is an exact tested version, not a minimum-version claim. The deprecated
0.73.1 package has no prompt-event surface. Coverage requires the adapter, enabled events,
and a persisted session; stock startup trust is excluded. See
[setup](HOW_TO_USE.md#report-pi-extension-prompts) and [measured evidence](docs/captures/pi/README.md).

### Standalone binary

Each release attaches `compass_<version>_<os>_<arch>.tar.gz` for `darwin` and `linux` on `arm64`
and `amd64`, with a `checksums.txt` of their SHA-256 sums. One archive unpacks to a `compass/`
directory whose `compass` program carries its own Python interpreter and the dashboard, built with
[PyInstaller](https://pyinstaller.org/en/stable/), so nothing needs installing beside it. It takes
the same options as `server.py`, daemon mode included. `compass --version` prints the release the archive was built for.

The release workflow builds under Python 3.12, so that is the interpreter in every binary. The 3.11
floor above governs running `server.py` from source or a plugin; it does not constrain the binary,
which never runs on an interpreter the user picked.

PyInstaller embeds the interpreter it runs under and cannot cross-compile, so each archive is built
on a host of its own OS and architecture. The Linux hosts are Ubuntu 22.04, the oldest image the
workflow can use, because a PyInstaller binary needs at least the glibc of the machine that built
it. A distribution with an older glibc may not run it, and musl-based distributions are not built
for.

On macOS the Apple silicon program is signed ad hoc, as that platform requires, but neither build
is signed with a developer identity or notarized. Fetching it with `curl` runs. A copy downloaded
through a browser carries the quarantine flag, and Gatekeeper may refuse it until you run
`xattr -dr com.apple.quarantine compass`.

There is no Windows binary yet. It waits on Spacedock's install contract covering Windows, which
is what the release archives are shaped for. Until then, run `server.py` with Python 3.11 or newer
there. The binary is the
dashboard server only. Hooks, skills and the MCP server still come from the plugin or are set up by
hand; see [HOW_TO_USE.md](HOW_TO_USE.md).

## Validation

The canonical pre-PR suite is in [AGENTS.md](AGENTS.md#pre-pr-checks). This file owns only the
native per-runtime validators. They run locally, because the CLIs are not available on stock CI
runners:

```bash
claude plugin validate ./compass --strict
agy plugin validate ./compass
```

<!-- docs-synced-through: 8ea4d2a (2026-10-06) -->
<!-- Reconciled 5988426c..8ea4d2a: standalone commands, reading source and consent bounds,
     ordinary-driver preparation, conditional study guards and live-estimate disclosures.
     Source-only study machinery grants no activation, source admission or qualification;
     independent source review, cold participants and complete outbound attribution remain open. -->
