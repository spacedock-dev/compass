# Design: event-driven session observation

Status: Phases 0 through 3 have shipped, and this file began as the plan and is now the design record
of the work. The Phase 0 collector fixes, the two quota opt-out repairs and the benchmark landed with
tests, and its four gates carry verdicts: the coarse probe and the adapter semantics are measured, the
latter for the four harnesses that have adapters; selective reuse is undecided from the one machine
measured rather than failed; operational rollout is unreached. Phase 1's materialized snapshot and SSE,
Phase 2's ingress, coordinator and bundled hooks, and Phase 3's Codex adapter are all in the runtime.
Phase 4, optional managed sessions, is unshipped, was never filed as an issue and is not planned.

Everything below the Phase 0 section that is not marked shipped is a problem statement and an option
survey rather than a commitment. The ACP, filesystem-watcher and OpenTelemetry findings, and the
reasons `PreToolUse` is not a needs-input source, are the rejected alternatives this record exists to
keep.

Which runtime file owns what, and the inward-only dependency rule any new module must respect, is
owned by [`design-runtime-architecture.md`](design-runtime-architecture.md). The per-harness
store formats are owned by the shipped [`SKILL.md`](../compass/skills/compass/SKILL.md). This
file records the August 2026 investigation into replacing request-driven session polling with
lower-latency collection.

## Recommendation

Compass should keep its Python runtime and existing collectors, but stop making a browser refresh
the scheduler for all collection work.

**Phase 0 has run its measurement, collector and quota-repair tasks, and the recommendation below is
subordinate to the verdicts it produced.** One of the four gates was reached and it failed; the other
three were never reached. All of them are recorded under
[Phase 0](#phase-0-measure-repair-prerequisites-and-fix-the-collector).

The figures below come from **one machine only**: darwin/arm64 (macOS 26.5.2, Apple silicon), CPython
3.12.13, 6 of 10 harnesses discovered, 16 sessions in the default 24-hour window, and 3,632 Claude
transcript files under `~/.claude/projects`. Nothing here has been reproduced on Linux or Windows.
Both columns were measured on the same machine and the same day with `scripts/bench_collect.py`: the
after column at the branch tip, the before column at the pre-fix commit checked out in a detached
worktree of the same repository, against the same store.

| Measurement | Before the Phase 0 collector fixes | After |
|---|---|---|
| Warm `Application.collect`, median of 7 | 283 ms | 118 to 120 ms |
| Of which the Claude collector | 263 ms, 93% | 98 to 101 ms, 83% |
| First collect in a fresh process, caches empty | 392 to 399 ms | 275 to 297 ms |
| The five other discovered harnesses combined | 7.3 ms | 7.5 ms |
| All ten discovery predicates combined | 0.34 ms | 0.33 ms |
| `glob_under` calls in one cold collect | 11,850 | 1,646 |
| Coarse `os.stat` probe over 97 store paths | 0.14 ms | not re-measured |
| Forwarder process cost, server absent, macOS | 56 ms median | not re-measured; p95 and p99 never measured |
| Files or bytes consulted | not measured | not measured, no counter exists |

Run-to-run variance is worth about 15% of the total on this machine: an earlier same-commit baseline
recorded 322 ms warm against the 283 ms above, on the same store hours apart. Read the columns as a
ratio, not as absolute constants.

Two conclusions survive the fixes. First, the cost argument for an event architecture is gone: a 120
ms warm collect at the current five-second cadence is a 2.4% duty cycle, and latency plus
needs-input semantics are the only remaining justification for anything below. Second, per-harness
dirty invalidation still saves little. Claude is 83% of the post-fix collection and is also the
harness that generates the most events, so it will be dirty in nearly every coalescing window; the
[selective-reuse gate](#phase-0-measure-repair-prerequisites-and-fix-the-collector) measures that
saving at about 17% on the one machine measured, which is below the bar but does not settle the
gate: that machine's Claude store is 71x Codex's, and the gate section records the verdict as open
pending several multi-harness profiles.

The design that survives those numbers is an event-triggered, materialized dashboard snapshot:

1. Harness-native lifecycle hooks, status-line callbacks, native event streams, a coarse store
   probe, and optional Compass-managed ACP connections report that something changed.
2. An authenticated, bounded loopback ingress normalizes the signal and marks one session or harness
   dirty.
3. The existing defensive collector for that harness reconstructs authoritative state from its
   store when the event does not contain enough trustworthy state on its own.
4. Compass merges the result into a versioned in-memory snapshot.
5. The server pushes a revision notification to dashboard tabs with Server-Sent Events (SSE).
6. A full reconstruction on first demand and periodic reconciliation retain correctness when an
   event is missed or an integration is unavailable.

In short:

> Events tell Compass **when** to look. Collectors determine **what** the authoritative state is.

That invariant is the one thing in this document that should survive any cut. Where it and a
latency goal conflict, it wins, with the narrow per-field exceptions written out under
[Event overlays versus store truth](#event-overlays-versus-store-truth).

ACP is useful for sessions Compass launches, owns, or transparently proxies. It is not a suitable
replacement for passive discovery of arbitrary agent sessions already running under other clients.

## The current collection path

Before Phase 1c the browser called `/api/data` every five seconds from `compass_runtime/web/main.js`;
the section below describes that path, which is the baseline every figure in this document was
measured against. The page now drives itself from `/api/stream` in `web/live.js`, with a twenty-second
safety net and the five-second cadence retained only for browsers without `EventSource`. A cold request
enters `Application.collect` in `compass_runtime/aggregate.py`, iterates the harness registry, runs
discovery for each harness, invokes every discovered collector, and serializes the complete
aggregate response.

`Application.collect_json` memoizes the serialized result for 2.5 seconds and holds its lock through
collection. That prevents concurrent browser tabs from stampeding the stores on the same cold cache
entry, but it does not make collection incremental at the application level. Once the memo expires,
the next request repeats discovery and invokes every discovered harness collector.

Individual collectors use bounded reads, mtime and size checks, metadata caches, incremental turn
scanners and defensive SQLite access, behind a per-harness failure boundary that `Application.collect`
owns rather than the collectors themselves. The costs are architectural rather than a property of the
language:

- Browser demand schedules collection work.
- A change in one harness invalidates nothing specifically, so the next cold request consults all
  discovered harnesses. On the profile above this is worth about 7 ms, so it is the weakest of these
  costs, not the strongest.
- The page learns about a change zero to five seconds after it occurs, and up to about 7.5 seconds in
  the worst case, because the five-second poll composes with up to 2.5 seconds of memo staleness.
- Multiple tabs still generate repeated HTTP requests, even when the memo makes some of them cheap.
- Long-running turns can look idle when a harness only updates its store at message boundaries.
- Exact semantic state such as waiting for approval is often reduced to an mtime freshness guess.

The supported sources remain intentionally heterogeneous. Those stores are valuable because they
provide historical reconstruction and a fallback that does not depend on an agent still running.

### State is partly time-derived

Compass treats activity within `working_threshold_sec` as Working. A session can therefore become
Idle without another file write or lifecycle event. Moving to events does not remove the need for
clocks: the server must schedule state invalidations for deadlines such as:

- `last_activity + working_threshold_sec`;
- history-window expiry;
- expiry of Working and other transient overlays, so a missed stop cannot pin false activity;
- the vendor quota poll floor and allowance reset times.

Needs-input state is deliberately *not* cleared merely because a wall-clock TTL elapsed. A real
permission or input wait can last for hours, so a time-only deadline would replace a possible stale
positive with a more dangerous false negative. An `input_requested` overlay retires on a positive
`input_resolved`, resumed user/agent activity, `session_ended`, collector evidence allowed by that
harness's precedence rule, or removal of the collector-owned row. A liveness lease may mark its event
source stale, but does not silently clear the alert.

Existing hook state follows the same principle. `notifications.current_hook` clears a standing hook
when the newest user record in the transcript changes, and its docstring calls that clock-independent;
the only fallback compares against a newly parsed transcript timestamp, not a timer, and no hook TTL
field exists in `config`. Scheduling an arbitrary expiry would invent behavior the mechanism does not
have. Working overlays and source-health leases do need deadlines; Needs-input overlays need positive
retirement evidence.

An event-driven system is not timer-free. It avoids asking every source the same question at a fixed
cadence when nothing has changed.

### Existing push paths

Compass already has two partial push integrations:

- Claude `Notification` and `SessionEnd` hooks can forward JSON to `POST /api/notify` through
  `notify_hook.py`. The resulting hook state augments Claude session state and can drive native
  notifications even when no dashboard tab is open.
- Antigravity invokes its configured `statusLine` command on agent-state changes. That payload reaches
  `POST /api/usage` and Compass retains the shaped quota receipt in memory.

One script serves both. The shipped skill configures Antigravity's `statusLine` as
`notify_hook.py <url>/api/usage` and states that it is the same forwarder the Claude hooks use with a
different URL. It is payload-agnostic, forwarding raw stdin bytes to whichever URL it is given. That
coupling is easy to miss and constrains anything done to the forwarder later.

Both paths reach Compass only for a user who has edited the harness's own configuration by hand. They
prove that loopback event ingestion fits the product; they are not evidence that the mechanism is
installed anywhere. Today they update side state; they do not maintain the session-board snapshot or
trigger browser delivery.

## Cheaper options that must be tried first

### Make collection cheaper

The cheapest option is not an acquisition strategy at all: fix the dominant collector and keep
request-driven polling. `claude.collect` issues roughly 11,800 `glob` calls per collection across
about 3,000 historical session prefixes to produce 8 rows, because the freshness filter
(`if not (active or show_all)`) runs *after* the per-prefix subagent scan, and because
`agent_transcripts` is called once directly and once again inside `load_subagents` for every prefix.

**This shipped in Phase 0.** Three behavior-preserving fixes landed: an `os.path.isdir` guard before
globbing, calling `agent_transcripts` once per prefix instead of twice, and a bounded `RuntimeState`
cache of subagent listings. Together they took the warm Claude collector from 263 ms to about 100 ms
and one cold collect from 11,850 `glob` calls to 1,646, with the whole test suite unchanged.

The cache did not land the way the prototype described it, because the prototype was not
behavior-preserving. Keying on the session directory's mtime alone misses two writes: appending to an
existing child transcript changes no directory mtime, and creating a child below
`subagents/workflows/<run>/` need not change the session directory. Either one loses the parked-parent
case the code comments exist to preserve. What shipped caches membership only; fingerprints every
directory a glob pattern can reach, including each existing workflow run directory, so a run watched
before it holds anything still notices its first agent; takes that fingerprint **before** the listing,
so a write racing the scan invalidates the entry instead of pinning a listing that missed it; and
restats every cached child transcript on every call, so a running subagent is never frozen at the
mtime it was first seen at. That conservatism is why the result is near 100 ms rather than the 41 ms
the mtime-only prototype reported. The parked-parent and nested-workflow cases have regression tests.

Doing this first was worth it regardless of what follows. A 120 ms collect at the current five-second
cadence is a 2.4% duty cycle, which removes cost from the argument entirely and leaves latency and
needs-input semantics as the only remaining justification for anything below. An event architecture
layered over an O(all-history) collector inherits the same cost on every dirty refresh.

### A coarse store probe

A prototype `os.stat` sweep over store roots, per-project directories, and known in-window
transcripts cost 0.14 ms for 97 paths on one warm macOS profile. At 1 Hz that would be a 0.014% duty
cycle on that profile, roughly 400 times cheaper than today's poll. It is pure stdlib, needs no user
configuration, no envelope, no versioning and no uninstall path. It is not yet proven to cover every
input read by all ten collectors.

The probe needs a reviewed dependency and fingerprint table per harness before it can become a
correctness-relevant trigger. Its target set includes known JSONL, task and subagent files; every
directory used to discover new or removed targets; and SQLite database, WAL and SHM sidecars. A
fingerprint uses only change-bearing fields such as existence, `mtime_ns`, size and, where portable,
inode or file ID, plus the owning directory; atime is excluded. Reconciliation refreshes the target
set. Mutation fixtures must cover append-in-place, same-size rewrite, atomic replacement, create,
delete, nested-file creation, WAL append and checkpoint, coarse timestamp resolution, suspend/resume,
and target-set changes on all three supported operating systems. Bind mounts, WSL/9p, remote and
network stores remain best-effort unless measured separately.

It cannot distinguish "waiting for approval" from "bytes changed". That distinction is the case for
hooks, and it is a narrower case than "hooks are the primary trigger". Until the probe passes its
independent false-negative and performance gate, the current five-second scan remains the fallback;
the 0.14 ms experiment is a hypothesis, not grounds to reduce polling.

## ACP findings

Nothing in this section is measured. It is read from the ACP specification pages; no ACP agent has
been launched here and no ACP traffic captured. The conclusions are about what the standard
requires, not about what any implementation does.

### What ACP is designed to do

The [ACP introduction](https://agentclientprotocol.com/get-started/introduction) describes a standard
interface between an agent and a client such as an editor or IDE. In the standard local topology,
the client launches the agent as a subprocess and exchanges newline-delimited JSON-RPC over stdin
and stdout. A connection may host several sessions, and the protocol makes extensive use of
notifications for real-time UI updates. See the
[architecture](https://agentclientprotocol.com/get-started/architecture) and
[transport specification](https://agentclientprotocol.com/protocol/v1/transports).

For a session carried on that connection, ACP's live data model covers:

- prompt-turn start and completion;
- streamed agent messages;
- tool calls and status changes;
- agent plans;
- permission requests;
- context usage and optional cost;
- cancellation;
- session metadata updates.

The [prompt-turn specification](https://agentclientprotocol.com/protocol/v1/prompt-turn) states turn
boundaries directly, where a transcript mtime only supports a guess.

### What ACP does not standardize

ACP does not define a machine-wide observer connection for all independently running agents.

Its optional [`session/list`](https://agentclientprotocol.com/protocol/v1/session-list) method is a
history-discovery mechanism. Standard `SessionInfo` contains a session identifier, working
directory, and optional `additionalDirectories`, `title`, `updatedAt` and `_meta`. Only `sessionId` and
`cwd` are required, so a collector cannot rely on a title or an update time being present, and `_meta`
is ACP's generic extension slot rather than a defined agent-metadata field. The method is gated on the
`sessionCapabilities.list` capability. All of that is as the v1 schema reads; unverified against any
implementation. `session_info_update` can keep title, update time and `_meta`
current without polling, and it is delivered over `session/update`, so it inherits exactly the scoping
described next.
The standard does not give listed sessions a normalized Working, Idle, waiting-for-approval, tool
progress, or externally-running status.

No ACP page states in so many words that `session/update` is connection-scoped; that is an inference
from the stdio-subprocess topology, in which the stream belongs to the connection on which the client
set up, loaded, resumed, or prompted the session. The direct evidence for the claim that matters is
negative and stronger: the v1 method index contains no `session/subscribe`, `session/observe` or
`session/watch`. A normal terminal session, a session in an editor, and a Compass process are
normally different processes and different connections. An implementation may expose a shared daemon
or custom transport, but ACP does not require it. Remote transports are moving: the introduction calls
ACP suitable for remote scenarios over HTTP or WebSocket with full support still in progress, and
Streamable HTTP is a draft proposal, so a future shared-HTTP topology could soften this conclusion.

Consequently, launching an ACP subprocess merely to call `session/list` would not replace the current
passive collectors. It would still query for history, would not guarantee live state, and could be
more expensive than reading the already-local store.

### Nominal coverage is not passive observability

The [ACP agent directory](https://agentclientprotocol.com/get-started/agents) as read in August 2026
lists nine of Compass's ten harnesses. It is a live page, so re-read it before relying on either the
membership or the maturity annotations:

- Claude Agent, through an adapter;
- Codex CLI, through an adapter;
- Cursor;
- Factory Droid;
- Gemini CLI;
- GitHub Copilot, currently preview;
- Goose;
- OpenCode;
- Pi, through an adapter.

Antigravity is not listed. More importantly, the implementations do not have one maturity level or
one deployment topology. Being able to launch a harness as an ACP agent does not mean a second ACP
client can subscribe to sessions that another terminal or editor already owns.

### Where ACP does fit Compass

ACP fits an optional managed-session lane:

- Compass launches an ACP agent and becomes its client.
- The dashboard gains prompts, permission UI, cancellation, plans, and tool progress for sessions it
  owns.
- An editor is configured to launch a Compass proxy, which forwards ACP traffic bidirectionally
  while copying lifecycle notifications into the dashboard.
- Compass connects to a harness daemon that explicitly supports multiple clients and live
  subscription semantics.

Every form changes the product boundary. A direct ACP client must answer or relay permission
requests, survive as part of the session's critical path, and potentially gain write or control
access. A proxy can preserve the existing editor's permission experience but still becomes a point
of failure. These modes should be explicit and optional rather than prerequisites for passive
cartography.

Codex illustrates the distinction. Its official
[app-server protocol](https://learn.chatgpt.com/docs/app-server) exposes authentication,
conversation history, approvals, streamed `turn/*` and `item/*` events, loaded-thread discovery, and
`thread/status/changed`, whose `status.activeFlags` can carry `waitingOnApproval`. All of that is
read from the page, not observed: no app-server has been started here and `docs/captures/codex/`
covers hooks and rollouts only, so the managed-Codex recommendation is provisional on a capture, one
`codex app-server` process, one loaded thread, and a recorded list of the notification method names
and status values it actually emits. Those explicit loaded-thread states make it the provisional
first managed Codex topology, subject to an adapter fixture comparison rather than an assumed
superiority over ACP. It only provides exact runtime status for threads loaded in that
app-server; ordinary standalone CLI sessions do not silently join a separate Compass server.

## Alternative acquisition strategies

| Approach | Sees independently launched sessions? | Semantic precision | Main cost | Feasibility | Recommendation |
|---|---|---|---|---|---|
| Fix the dominant collector | Yes | Whatever stores persist | One collector's algorithm | Done in Phase 0 | **Done first, unconditionally** |
| Coarse periodic `stat` probe | Intended to, pending mutation tests | Low: says bytes changed, not what the agent is doing | 0.14 ms for one warm 97-path Mac profile; cross-platform cost unmeasured | Medium, gate unreached | Primary latency candidate only after its independent gate |
| Harness-native hooks, extensions, and status lines | Yes, when installed at user or plugin scope | High for lifecycle and input waits | Per-harness adapters, user trust, an indefinite support tail | Medium | Semantic supplement, needs-input first |
| ACP | Not guaranteed; normally only sessions on Compass's connection | Very high for owned sessions | Changes Compass into a client, launcher, or proxy | Technically feasible | Optional managed mode |
| Native harness server or event API | Only sessions connected to that server | Very high | Agent-specific topology and lifecycle | Medium | Use opportunistically; prefer where already running |
| Native filesystem-event watcher | Yes | Low | Three platform backends or a dependency | Poor fit | For precision the product does not need |
| OpenTelemetry | Yes for opted-in processes | Strong telemetry, uneven interactive state | Configuration, decoding, and partial harness coverage | Low | Optional observability lane |
| Fixed polling | Yes | Whatever stores persist | Repeated work and latency | High | Correctness fallback only |

### Filesystem notifications

Watching session stores reduces blind polling without requiring harness configuration, but it is not
sufficient as the source of truth:

- JSONL is often appended in place, so watching only directory mtimes misses changes.
- SQLite may write a database, WAL, shared-memory file, temporary file, or replacement file.
- Watchers coalesce events, can overflow, and differ in rename and delete semantics.
- A filesystem event has no standard meaning for Working, Idle, permission requested, turn ended, or
  subagent started.
- Linux inotify, macOS FSEvents, and Windows directory-change APIs require separate implementations.

The last two objections are objections to a *native* watcher, not to a cheap one. Compass's runtime
has a deliberate stdlib-only, no-dependencies contract; the Python floor is owned by
[`COMPATIBILITY.md`](../COMPATIBILITY.md) and the implementation constraint by
[`CONTRIBUTING.md`](../CONTRIBUTING.md). A watcher library would overturn that contract and three
native backends would be substantial maintenance. The coarse probe described above needs
neither. It captures most of the latency win at a fraction of the surface area. Every notification,
from a probe or a native watcher, remains a hint followed by reconciliation.

### OpenTelemetry

Claude Code, Codex, and Gemini CLI all document OpenTelemetry export:

- [Claude Code monitoring](https://code.claude.com/docs/en/monitoring-usage)
- [Codex observability](https://learn.chatgpt.com/docs/config-file/config-advanced)
- [Gemini CLI telemetry](https://geminicli.com/docs/cli/telemetry/)

OTel can provide session identifiers, prompts, API lifecycle, token usage, tool decisions and results,
metrics, logs, and traces. Prompt logging is configurable but its default is not uniform, which matters
for a security review: Claude redacts prompts unless `OTEL_LOG_USER_PROMPTS` is set, Codex has
`log_user_prompt`, and Gemini's `logPrompts` defaults to true. It is useful for organizational
observability and could eventually become an optional Compass source.

It should not be the core transport because it is disabled by default, does not cover the full
harness set, introduces OTLP receiving and decoding concerns, and is aimed more at telemetry than a
portable interactive state machine. Hooks are simpler for local lifecycle events and can report
permission waits directly.

## Harness-by-harness feasibility

No single hook integration covers all ten harnesses. The coarse probe is intended to cover their
known mutation surfaces, but cannot be called universal until its per-harness mutation corpus passes.
What hooks add is semantics, so the route is one small event adapter per harness where the semantics
justify it, each of which feeds one normalized ingress.

Cost of that route, stated plainly: ten adapters, ten forwarder configurations, an ingress, a
coalescing worker, two schedulers, an SSE endpoint, browser reconnect logic and an acquisition-mode
display, in a stdlib-only runtime with a 3:1 test-to-code ratio, `ruff select = ALL`,
`mypy --strict`, a ratcheting coverage floor and a three-OS matrix. Order-of-magnitude estimate:
1,000 to 1,500 runtime lines and 3,000 to 4,500 test lines. The latency it buys over the coarse probe
is about one second, which is the 1 Hz probe cadence rather than a measurement, down to about 0.3
seconds, which the measured 294 ms ordinary p50 later bore out. No probe-to-render measurement
exists, so the two are not directly comparable. Each phase beyond the first two must carry its own
justification against the probe baseline rather than inherit this recommendation.

Distribution asymmetry compounds it. Compass currently ships artifacts to four harnesses (Claude,
Codex, Antigravity and Gemini) and currently has no distribution artifact for the other six. That is
not the same as those ecosystems lacking manageable lifecycle support: [Pi has packages](https://pi.dev/docs/latest/packages),
[Cursor has plugin-installed hooks](https://cursor.com/docs/hooks.md), and Factory is said to install
hooks through its plugin surface, a claim carried here with no citation behind it. Other harnesses
vary. Assess
install, trust, update and exact removal per harness. Until Compass actually ships such an artifact,
any hand-written setup instructions remain a user-owned support tail.

Harness counts stated in prose drift. `docs/design-harness-registry.md` H-4 owns that problem, and
any count next to a harness list here is part of the list.

| Harness | Best passive live source | ACP or managed source | Recommendation |
|---|---|---|---|
| Claude Code | Plugin-bundled HTTP or command hooks | Claude ACP adapter | First and only initial implementation target |
| Codex | Plugin-bundled command hooks | Native app-server first; ACP adapter second | Second target, after Claude proves the ingress |
| Pi | User extension lifecycle events (documentation read; no event name or payload observed) | Community ACP adapter | Deferred; probe baseline |
| Gemini CLI | Extension-bundled command hooks and OTel; consumer-account access transitioned, while enterprise and API-key use remain | Native ACP mode | Shipped-extension candidate after the first adapters |
| Antigravity | Plugin-bundled model/tool/loop hints, plus opt-in `statusLine` snapshots for agent state and quota (no confirmation or task-count field in the 37 print-mode pushes; both arrive interactively) | No listed ACP implementation | Phase 2 target alongside Claude |
| Copilot CLI | Plugin-bundled, repo (`.github/hooks/*.json`) or user command hooks | ACP server via `--acp`, transport unverified | Deferred; probe baseline |
| OpenCode | A project or user plugin file, measured on 1.18.20: `permission.asked` and `permission.replied` both carry a joinable `sessionID`, and no store table records a standing request. Shared server SSE where safely discoverable and authenticated | Native ACP mode | Plugin is the proven path; an existing-server topology is still untested |
| Cursor CLI | Plugin-installed hooks, with ordinary local-CLI coverage requiring fixtures | Listed in the ACP agent directory; the installed cursor-agent 2026.07.23 help advertises no ACP entry point, so the mode is unverified. Opt-in `--output-format stream-json` in print mode | Deferred; probe baseline |
| Goose | Plugin command hooks, auto-discovered from `~/.agents/plugins/<name>/hooks/hooks.json`. Goose registered all eleven event names offered to it and seven of them were observed firing, both lists in [`../captures/goose/tool-confirmation-1.47.0-macos.jsonl`](captures/goose/tool-confirmation-1.47.0-macos.jsonl). They bound a turn and nothing else: no hook fires while a tool confirmation stands, and the store records nothing either | Goose ACP server/API | Turn boundaries are reachable; a needs-input signal is a measured blank |
| Factory Droid | User or plugin command hooks (documented, summarised by category) | ACP listed in the agent directory, mode unverified | Deferred; probe baseline |

Claude, Codex, Antigravity, Gemini, OpenCode and Goose rows are backed by captures under
`docs/captures/`. The OpenCode capture covers the plugin path only; its ACP and shared-server cells
are still documentation reads. Factory Droid's hook cell is now backed in part: registration, the
event vocabulary and two payload shapes were measured on 0.202.0, while everything a turn would
exercise was not, because a turn needs a Factory account. Pi, Copilot CLI and Cursor CLI now have
captures under `docs/captures/`, but none of them measures the passive-feed cell as this table
states it, and none has been reconciled into these rows: read those files before trusting a Pi,
Copilot or Cursor cell here. The ACP column is unmeasured on every row either way: its per-harness
qualifiers come from the ACP agent directory listing rather than from any observed
connection.

### Claude Code

[Claude's hook reference](https://code.claude.com/docs/en/hooks) exposes session start/end, prompt
submission, pre- and post-tool events, permission requests, notifications, stops, subagent and task
lifecycle, and several other events; eight of those names are measured firing below, and bundled
plugin hooks are measured too. **HTTP hooks are a desk read.** The reference documents an HTTP hook
type, nothing here has ever registered one, and all ten entries in the shipped `hooks/hooks.json` are
command hooks. That gap is worth closing before Phase 2: the command forwarder costs 56 ms per
invocation on macOS, which is the figure that decides whether the event path is cheaper than the
polling it replaces, and an HTTP hook would not pay it.

The minimal event set should be `SessionStart`, `UserPromptSubmit`, `PermissionRequest` and/or
actionable `Notification`, `Stop`, `SubagentStart`, `SubagentStop`, `TaskCompleted` if task progress is
needed, and `SessionEnd`. All nine names are present in a `strings` read of the Claude Code 2.1.221
binary, a static read, which in this project sits above the docs and below a capture (see the
`session_title` miss recorded below), alongside `PreToolUse`, `PostToolUse`, `PreCompact` and
`PostCompact`. That last pair is a reminder that this set
has changed across releases, so confirm each name against the installed version at implementation time
rather than against this document. Observing every tool call is not required merely to know that a turn
is active and would add avoidable process or HTTP traffic.

Cost, measured: the current forwarder takes 56 ms per invocation on macOS against a closed port:
about 13.5 ms of interpreter startup plus about 42 ms importing `urllib.request`. Process
creation on Windows is expected to cost more, but that is unmeasured here and no capture on this
project is from Windows. Against the pre-fix 283 ms poll every five seconds, break-even was roughly
60 hook events per minute. Against the post-fix 120 ms collect it is roughly 26, and against a fixed
60 ms collector roughly 13.
The minimal event set is therefore not a nicety but the thing that decides whether the event path
costs less than the polling it replaces, and a forwarder that imports `urllib.request` on every event
is the wrong shape. Prefer `http.client`, or a persistent local transport.

### Codex

[Codex hooks](https://learn.chatgpt.com/docs/hooks) expose session start/end, prompt submission,
pre- and post-tool events, permission requests, stops, and subagent lifecycle. Enabled Codex plugins
can bundle hooks through `hooks/hooks.json` or a manifest-specific path. Non-managed hooks require
the user to review and trust their current definition, which is an appropriate consent boundary.

Codex command hooks should call a small forwarder that always exits successfully and returns quickly
when Compass is not running. For a future managed mode, native app-server exposes explicit loaded
thread status and is preferable to scraping rollouts; compare it with the ACP adapter using fixtures
before choosing between those managed transports.

#### Claude hook distribution and semantics: both MEASURED

Two separate questions. Both are now answered, the second one late.

**Distribution is verified.** Claude Code loads a plugin's bundled hooks from
`hooks/hooks.json` at the plugin root, by convention, with no manifest key. Confirmed by running
`claude --plugin-dir <copy> -p` against a copy carrying probe hooks and watching them fire, then
end to end with the shipped file: a dashboard on an isolated `COMPASS_HOME` showed the nested
session's row with `acquisition: event`. `${CLAUDE_PLUGIN_ROOT}` is expanded in the hook's
environment, so a command referencing it stays stable across plugin upgrades. So Claude no longer
needs a hand-edited `settings.json` for events, which was the last harness that did.

Two things that misled the verification, worth writing down because both look like bugs:

1. `session_ended` retires a session's overlays, correctly, and a one-shot `claude -p` run ends
   immediately. So the row reads scan-only again within seconds and the events look lost. Removing
   only `SessionEnd` from the bundled file made the same run show `acquisition: event`, which is what
   isolated the cause.
2. The adapter exits 0 on every failure by design, so nothing distinguishes "posted" from "gave up".
   Diagnosing this needed the guards instrumented from inside a real hook invocation.

**Semantics are now measured too, for everything a headless turn reaches.** Evidence:
[`docs/captures/claude/`](captures/claude/), from Claude Code 2.1.222 on macOS. Five sessions, 38
hook invocations, five complete turns.

The route matters, because the one this document originally proposed would have failed. Isolating the
store with `CLAUDE_CONFIG_DIR` **loses the subscription login**: the credential's keychain account
name is suffixed with the first eight hex characters of `sha256(config dir)`, and is unsuffixed only
when the variable is unset. So the capture used `--plugin-dir` against a copy of the plugin whose
`hooks/hooks.json` commands were repointed at `scripts/capture_hook.py`. No settings file was edited,
no isolated config directory was needed, and the login was untouched. That is the recipe to reuse.

**Ordering and cardinality.** `UserPromptSubmit` exactly once, `Stop` exactly once, in that order,
with `SessionStart` before the turn and `SessionEnd` after it. `PreToolUse` and `PostToolUse` pair up,
once per tool call, three pairs in a three-tool turn. So the two guesses that mattered most, that a
prompt hook means Working and `Stop` means Idle once per turn, hold.

**The subagent turn, which is the one that settled the open question:**

```text
UserPromptSubmit -> PreToolUse -> SubagentStart -> PreToolUse -> PostToolUse -> SubagentStop
                 -> PostToolUse -> Stop
```

The subagent's lifecycle nests inside the parent's Agent-tool `PreToolUse` and `PostToolUse` pair, and
the inner pair is the *child's* own tool call. All ten events of that turn carried **one**
`session_id`, equal to the parent's. `agent_id` was a single distinct value, 17 characters and **not
UUID-shaped**, and it appeared on the child's `PreToolUse` and `PostToolUse` as well as on
`SubagentStart` and `SubagentStop`, because it lives in the common hook base rather than only in the
subagent events.

Two consequences worth writing down, because both look like bugs and neither is:

1. A `store_changed` originating inside a subagent arrives carrying `subagent_id`, since
   `event_hook.py` maps `agent_id` unconditionally. Harmless: `overlay_for` reads `subagent_id` only
   for `subagent_started` and `subagent_stopped`, so every other overlay keys on `(kind, None)`.
2. Nothing validates `subagent_id`'s shape, and nothing may start to. Claude's `agent_id` is 17
   characters, so a UUID check of the kind `session_id` gets would drop every Claude subagent overlay.

**Identity, re-verified.** Five sessions, five exact matches: the transcript filename stem *is* the
`session_id`, all 36 characters, so `collectors/claude.py` taking `basename(fp)[:8]` and `_claude_sid`
taking `session_id[:8]` agree by construction rather than by luck.

**Cost.** p50 0.12 ms, p95 0.16 ms, p99 **0.18 ms**, macOS, hook self-cost across 38 invocations.
Linux and Windows remain unmeasured. This is the hook's own work; the interpreter startup that
dominates it is measured separately by `scripts/bench_collect.py`.

**Where the capture disagreed with the published documentation.** The docs are wrong or stale on
several payloads, which is the fourth time desk-read field names have been wrong in this project:
`SessionEnd` sends `reason`, not `end_reason`; `SubagentStop` carries an undocumented
`agent_transcript_path`; `PostToolUse` carries `duration_ms`; `Stop` and `SubagentStop` both carry
`background_tasks` and `session_crons`; and `effort` and `tool_use_id` appear throughout. A static
read of the binary also predicted `session_title` on `UserPromptSubmit`, and the real payload does not
carry it, so the field list already recorded above is correct and the static read was not. None of
this changes the adapter, which builds its envelope from an allowlist, but it is the reason the
allowlist exists.

**Three mapped events still have not fired, and one of them matters.** `PermissionRequest`,
`TaskCompleted` and `PostCompact` never occurred, so their payloads remain unmeasured.
`PermissionRequest` was pursued rather than skipped: a shell command was requested with the tool
absent from `--allowedTools`, and then again under `--permission-mode manual` and
`--permission-mode default`. In all three cases the tool simply ran and no permission event fired, so
a headless print-mode session cannot produce one. `--permission-prompt-tool` exists precisely to serve
prompts non-interactively and is the likely route; an interactive session is the other. Until then the
`input_requested` mapping is the one Claude claim still resting on documentation, and
`overlay_working_ttl_sec` remains what bounds the damage.

`PermissionRequest` is registered in the bundled `hooks/hooks.json` and has never fired, so beyond
its unmeasured payload its output contract is also unconfirmed. Claude carries `permissionDecision`
and `permissionDecisionReason` inside the same `hookSpecificOutput` envelope Codex uses for
`decision.behavior`, both present in the 2.1.223 binary, so the Codex hazard analysis recorded below
does not carry over field-for-field. `event_hook.py` writes nothing and exits 0, which is expected to
read as no opinion; that expectation rests on a static read and the vendor page, not on a firing
event. The confirmation the Codex section demands before registration is owed here retroactively.

#### Permission alert latency: MEASURED, and the floor was never the real problem

`scripts/bench_event_latency.py` measures the gap between an adapter posting an event and a revision
being published, which is the thing a person actually waits through. Three cases, because the trade
depends on all three. macOS, one machine, six samples each:

| Case | p50 | What it is |
|---|---|---|
| ordinary | 294 ms | a `store_changed`, which waits out the coalescing window |
| urgent | 177 ms | an `input_requested`, which is exempt from that window |
| floored | 2864 ms | the same event arriving just after a collection, so the floor is the whole wait |

The measurement found two defects that mattered far more than the floor it was pointed at.

**The documented coalescing exemption did not exist.** `observation.py` has said since Phase 2b that a
matched `input_requested` is exempt from the coalescing delay. Nothing implemented it: `_record` opened
`_coalesce_until` for every dirty event and `_due` gated on it unconditionally. It was invisible
because the window is 0.1 s against a 2.5 s floor, so the thing not happening was 4% of the wait. Now
implemented, and worth the 117 ms between ordinary and urgent above.

**The floor is enforced twice, and an event landing between the two enforcements was dropped.** The
coordinator has its own `_last_collect_at`, and `Application.collect_json` separately refuses to
re-serialize inside `collect_memo_sec`. A coordinator that has never collected has an open floor while
the application's is closed, so `collect_json` returns the revision it published *before* the event
arrived, and the coordinator then marked the dirty generation collected against that read. Nothing
republished. A permission alert arriving in that gap did not render at all until an unrelated event or
a five-second stream tick happened along.

Fixed by comparing the revision `collect_json` returns against the last one this coordinator produced:
an unchanged revision is not progress, so the generation stays dirty. And the retry is scheduled at the
floor, because `_sleep_for` consults only `_coalesce_until` and without that the retry landed at
`stream_producer_interval_sec`. Measured at 5194 ms before both fixes and 2864 ms after.

**Verdict on overlay-only republication: not worth building, and the earlier note pointed at the wrong
obstacle.** Two corrections to what this document and the ticket both said:

- Nothing retains a live collection today. `collect_json` serializes inline and retains only bytes in
  an immutable `(revision, body, published_at)` tuple, so there is no existing mutability hazard to
  remove. The immutability work is the price of *starting* to retain a dict.
- `assign_display_ids` is not the blocker it was named as. It derives `session["session"]` from `sid`
  every time and never from its own previous output, so it is idempotent over a fixed row set. The real
  blocker is `events.apply_patch`, which overwrites five display fields in place with no unpatched base
  kept, so an expiring overlay cannot be undone. A republish would also have to redo the Claude
  collector's clock-derived `elapsed_h` and `updated_ago` writes into embedded task dicts, the
  state-ranked sort, and the summary counted from patched rows.

So the remaining prize is the 2.7 s between `urgent` and `floored`, bought with a retention refactor
whose own risk is the display-id double-render hazard this document warns about under
[Dirty queue and coalescing](#dirty-queue-and-coalescing). A correctness risk traded for
under three seconds on one transition is the wrong trade while the floor still protects the stores.
Revisit it if the floor itself ever moves.

#### Codex adapter semantics: MEASURED, and the gate is cleared

The first adapter gate in this project to be cleared by evidence rather than waived. Captured from a
real `codex exec` session, codex-cli 0.146.0 on macOS, against an isolated `CODEX_HOME` so nothing of
the user's configuration was touched. The records are kept in
[`../captures/`](captures/README.md).

`hooks.json` accepts the same schema as Claude's `settings.json` hooks, PascalCase event names and
all: `{"hooks": {"<Event>": [{"matcher": ..., "hooks": [{"type": "command", "command": ...}]}]}}`.
Codex normalizes those names to snake_case internally, which is the form its `config.toml`
`[hooks.state]` keys use.

Cardinality and order for one turn containing one tool call, all five hooks fired exactly once:

```text
UserPromptSubmit -> PreToolUse -> PostToolUse -> Stop
```

`SessionStart` fires once outside the turn. Payload fields per event, which is what the adapter is
written against:

| Event | Fields |
|---|---|
| `SessionStart` | `cwd`, `hook_event_name`, `model`, `permission_mode`, `session_id`, `source`, `transcript_path` |
| `UserPromptSubmit` | the common set plus `prompt`, `turn_id` |
| `PreToolUse` | the common set plus `tool_input`, `tool_name`, `tool_use_id`, `turn_id` |
| `PostToolUse` | as `PreToolUse` plus `tool_response` |
| `Stop` | the common set plus `last_assistant_message`, `stop_hook_active`, `turn_id` |

The common set is `cwd`, `hook_event_name`, `model`, `permission_mode`, `session_id` and
`transcript_path`. Hook self-cost p99 was 0.47 ms on macOS, excluding interpreter startup as always.
No numeric budget has been agreed for this gate; 0.47 ms is well inside any plausible one. Linux and
Windows remain unmeasured.

**The identity mapping is the identity function, and this is the part worth having measured.** The
payload's `session_id` is Codex's own session id, and it matched the `session_meta` id of the rollout
file the same session wrote, which is exactly what `collectors/codex.py` keys `sid` on. So unlike
Claude, no truncation is involved, and unlike Antigravity there is no second candidate id field to
choose wrongly between.

Two operational findings that change how the adapter ships:

1. **Hooks require per-hook trust.** Codex records a `trusted_hash` in `config.toml` under
   `[hooks.state."<source>:<snake_case_event>:<group>:<index>"]`, and an untrusted hook is silently
   skipped rather than reported. The first capture attempt produced zero events for exactly this
   reason. `codex exec --dangerously-bypass-hook-trust` exists for automation and is what the capture
   used; a shipped adapter must instead expect the user to approve it once, and must tolerate being
   skipped until they do.
2. **The trust hash changes with the command.** So an adapter upgrade that rewrites its command line
   re-prompts. The command should therefore be stable, which argues for a fixed script path with the
   port passed through the environment or a settings file rather than interpolated into the command.

`prompt`, `tool_input`, `tool_response` and `last_assistant_message` all arrive in these payloads.
The adapter drops them in the hook, exactly as the Claude one does, so they never reach a socket.

### Antigravity

Antigravity has two push paths, not one, and the second is the better fit for this design.

The [status-line callback](https://antigravity.google/docs/cli/statusline) fires frequently while the
TUI runs, measured at 13 and 24 pushes across two short turns, mostly repeating the same
`agent_state`, and its payload is much richer than a dirty signal. Measured, from those 37 pushes:
`agent_state`, `context_window`, `conversation_id`, `cwd`, `email`, `exceeds_200k_tokens`, `model`,
`plan_tier`, `product`, `quota`, `sandbox`, `session_id`, `terminal_width`, `transcript_path`, `vcs`,
`version` and `workspace`, not all on every push. The `quota` block is measured only as far as its
bucket identifiers, which the capture records as `quota_keys` (`3p-5h`, `3p-weekly`, `gemini-5h`,
`gemini-weekly`): the recorder does not descend into a nested object, so none of the inner field
names appears in it. `remaining_fraction` and `reset_time` are what the shipped reader consumes
(`quota.py:513,519`), which is evidence they arrive; `reset_in_seconds` is a documentation read and
appears nowhere in the runtime. Google's documentation additionally
describes `tool_confirmation_pending`, `pending_input_count` and `task_count`; none appeared in this
capture, and all three were later found in an interactive one. See
[Antigravity status-line semantics](#antigravity-status-line-semantics-measured-and-the-documented-field-list-was-wrong)
for both halves.

`agent_state` supplies Working and Idle. Antigravity's status line is a genuine live-state source
rather than a dirty signal, but narrower than a documentation read suggests: the id is blank on 14
of 37 pushes, so the adapter often cannot report the return
to Idle. The `/api/usage` receipt path should still feed the general event coordinator before or
alongside quota shaping.

Antigravity also documents [agent hooks](https://antigravity.google/docs/hooks): `PreToolUse`,
`PostToolUse`, `PreInvocation`, `PostInvocation` and `Stop`, configured through a `hooks.json`. They
provide tool, model-invocation and execution-loop hints, not clean user-turn boundaries:
`PreInvocation` may occur before each model call, `PostInvocation` follows tool completion, and one
user turn may contain several invocations. `Stop.fullyIdle` is useful, but no adapter may normalize
these as `turn_started` and `turn_stopped` until real fixtures establish cardinality and ordering.
The decisive detail is trust asymmetry:
[plugins can bundle `hooks.json` at plugin root](https://antigravity.google/docs/cli/plugins), and
Compass already ships an Antigravity plugin manifest, whereas `statusLine` cannot be plugin-bundled
under the documented plugin schema. Status-line forwarding still requires explicit user opt-in via
`/statusline <command>` or settings, but not necessarily hand-editing a file. So this document's own
rule, to prefer plugin-bundled hooks where Compass already ships through the harness's plugin system,
applies here and makes Antigravity a Phase 2 target on the same footing as Claude.

Neither path replaces the other. Antigravity's hooks include no session start or end and no
notification event. The status line supplies live state and quota snapshots while the TUI runs, with
no confirmation or background-task field observed in the 37 print-mode pushes (both arrive
interactively), and does not document a
guaranteed start, end or final callback;
collectors and reconciliation remain authoritative for definitive session lifecycle. The hooks are
what can be installed without separate user configuration.

#### Antigravity hooks: distribution and schema MEASURED, payload documented only

`agy plugin validate` on a copy reports `hooks: 5 processed` for a **root
`hooks.json`**, which settles both the location and the schema. Two schema facts
matter, and neither matches Claude:

1. **There is no `hooks` wrapper.** Each top-level key is a hook name. Compass's
   own validator rejected the file until it learned this, having required the
   wrapper that Claude and Codex use.
2. **Two handler layouts in one file.** `PreToolUse` and `PostToolUse` group their
   handlers under a `matcher`; `PreInvocation`, `PostInvocation` and `Stop` list
   handlers directly. A file using the wrong layout for either half has that half
   silently ignored.

From the guide embedded in the `agy` 1.1.10 binary, which is stronger than a web
page but is still documentation rather than capture: payload keys are camelCase protojson,
so the id is `conversationId`; every payload carries it alongside
`workspacePaths`, `transcriptPath` and `artifactDirectoryPath`; a hook must print
a JSON object on stdout; and **`PreToolUse` output can gate the tool** with a
`decision` of `allow`, `deny`, `ask` or `force_ask`. That last one is why
`agy_hook.py` prints exactly `{}` on every path including every failure path: a
reporting hook has no business being able to block a user's tool call.

The hooks could not be made to fire under `agy --print`, at either the workspace
`.agents/hooks.json` or the CLI customization root, so **cardinality and ordering
are unmeasured**. That is why the adapter maps so little: only `PostToolUse` and
`PostInvocation`, and only to `store_changed`, which claims nothing about what the
agent is doing. Mapping `PreInvocation` to `turn_started` or `Stop` to
`turn_stopped` without knowing how often they fire per turn would risk flapping a
row mid-turn, which is the rule this document already sets for this harness.

So the two Antigravity paths divide cleanly: **hooks give freshness and install
with the plugin; the status line gives state and is opt-in.**

#### `PreToolUse` is not a Needs-input source, and here is why nobody should retry it

The paragraph above is superseded on the firing question by
[`../captures/antigravity/hooks-schema-1.1.19-macos.jsonl`](captures/antigravity/hooks-schema-1.1.19-macos.jsonl):
the hooks do fire once `hooks.json` carries its name wrapper, nine invocations in one interactive
turn. What has not changed is the conclusion for a permission wait, and the reasons are worth
writing down so the route is not walked twice.

`PreToolUse` fires before **every** tool call, not before a gated one, and its payload carries no
permission state at all: `artifactDirectoryPath`, `conversationId`, `modelName`, `stepIdx`,
`toolCall`, `transcriptPath`, `workspacePaths`. A wait posted from it would paint the row for
the length of every tool call, nine times in the turn measured. Nor is the decision channel a way
out: an empty object **denies**, which is the measured finding that inverted this adapter's safety
comment, so the pass-through a reporting hook needs is not `{}`. The binary's own jsonschema tag
reads `enum=allow,enum=deny,enum=ask,enum=force_ask,enum=deny_unless_prior_grant`, a fifth verb the
published guide does not list, with a matching telemetry token `hook_deny_unless_prior_grant`. That
is the defer-to-existing-policy shape and the only candidate for a pass-through here. It is **read
in the binary and never run**, as are `deny`, `ask` and `force_ask`.

Matching on `ask_question` does not help either. The binary carries
`Auto-answering ask_question at step %d with skipped=true` alongside `user cancelled ask_question`,
so agy answers some of its own questions and a hook cannot tell one a human sees from one it does
not. `matcher` is a regex, so an unanchored `ask_question` is not an exact match on the tool name.

#### Codex's permission hook exists and cannot fire in `exec`, and its subagent hooks are mapped

Two negatives, and the first one was recorded wrongly twice before it was measured
properly. Evidence:
[`docs/captures/codex/permission-hook-0.146.0-macos.jsonl`](captures/codex/permission-hook-0.146.0-macos.jsonl).

**No task-completed event. That half holds.** `TaskCompleted` is absent from the
0.146.0 binary's hook-event enum, which reads `PreToolUse`, `PermissionRequest`,
`PostToolUse`, `PreCompact`, `PostCompact`, `SessionStart`, `SessionEnd`,
`UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`.

**A permission event does exist, and the earlier claim that it does not was drawn
from evidence that could not support it.** That claim rested on
`~/.codex/config.toml`, which accumulates a `trusted_hash` under
`[hooks.state."<source>:<snake_case_event>:<group>:<index>"]` for every hook Codex
has actually registered, and on the observation that no permission event appeared
there. What was missed is that nothing had ever *asked* for one. Seven independent
hook sources have registered on the development machine, and the union of every
event name they requested is exactly the nine that were found. Absence from
registration state was absence of attempt. A negative needs the attempt to have
been made.

The vendor documents it, and has for months. OpenAI's Codex documentation (now on
`learn.chatgpt.com`; the `developers.openai.com/codex/*` paths 308-redirect there)
describes `PermissionRequest` as a shipped hook that runs before Codex asks for
approval and may allow or deny. This document previously recorded a third value,
`decline`, from a reading of that page; the binary has only two, and the page as it
stands today agrees with the binary. It landed in `rust-v0.122.0` on 2026-04-20
and was extended in `rust-v0.145.0` on 2026-07-21. Nothing removed it. So the
negative was not merely unsupported by its evidence, it was contradicted by the
vendor's own documentation for the whole time it stood.

Registering it directly settles the name: a hooks file listing `PermissionRequest`
alongside seven proven names installed without complaint and left all seven firing
normally, twice. So the name is accepted, and the recorded gotcha that an unknown
name invalidates a whole file does not apply to it. That gotcha still stands for
genuinely invented names, and it is the observable that separates the two cases:
an unknown name silences the file, a known one does not.

**It cannot fire under `codex exec`, and the reason is not a feature flag.**
`codex exec` pins `approval_policy` to `never`, which by the CLI's own definition
means "never ask for user approval; execution failures are immediately returned to
the model". Measured from the session's own `turn_context` record while
`-c approval_policy=untrusted` was passed explicitly. That override is parsed and
valid, since an invalid value is rejected with `expected one of untrusted,
on-failure, on-request, granular, never`, and it was still overridden to `never`.

Two runs, identical outcomes, differing only in the flags:

| Run | Requested | Effective | `exec_permission_approvals` | `PermissionRequest` fired |
|---|---|---|---|---|
| A | `untrusted` | `never` | false | no |
| B | `untrusted` | `never` | **true** | no |

Both runs asked for a write under a read-only sandbox. The sandbox refused it at
the OS level and the failure went back to the model, which is precisely what
`never` prescribes. No approval was ever requested, so there was nothing for a
permission hook to be asked about. Enabling `exec_permission_approvals` and
`request_permissions_tool`, both marked *under development* and both false by
default, changed nothing.

So `PermissionRequest` stays out of `CODEX_EVENTS` -- but as of 2026-08-23 that is a
product decision rather than a missing measurement. Driven interactively on 0.149.0
the event fires, its payload matches the nine keys predicted below, `behavior: allow`
skips the approval prompt outright, `behavior: deny` refuses the call, and Codex
holds the hook open (honoured at 25 s on allow, 70 s on deny) rather than timing out.
See [`../captures/codex/permission-hook-interactive-0.149.0-macos.jsonl`](captures/codex/permission-hook-interactive-0.149.0-macos.jsonl).
The `exec` finding above stands and is narrower than it reads: `codex exec` pins the
policy, so nothing asks under `exec`. That is a property of the mode, not of the
event. Note also that `approval_policy = "untrusted"`, which the runs above passed,
is a hard error on 0.149.0.

The validator's permitted vocabulary for the Codex hooks file now includes
`PermissionRequest`, because that list records what the harness *accepts* and this
work measured that it does. What the adapter *maps* is the separate question, and
the answer there is still no.

**Its payload is nevertheless fully known, from the binary rather than from a
capture.** 0.146.0 embeds draft-07 schemas for all eleven hook events, and
`permission-request.command.input` is `additionalProperties: false` with nine
required fields: `cwd`, `hook_event_name` (const `PermissionRequest`), `model`,
`permission_mode`, `session_id`, `tool_input`, `tool_name`, `transcript_path` and
`turn_id`, plus optional `agent_id` and `agent_type`. Nothing there is new: the
adapter's allowlist already drops `tool_name` and `tool_input`, and `session_id` is
the same id the collector keys on. So the mapping is writable today. The confirmation
that the event arrives is no longer missing either: the interactive capture named
above observed exactly those nine keys. The rule that a mapping ships on a capture is
satisfied, and what keeps this unmapped now is the decision below rather than the
evidence.

**And a hazard that has to be settled before this event is ever registered, whatever
the mapping.** Alone among Codex's hooks, a permission hook gets to *decide*. A
static read of the binary settles the shape: `PermissionRequestBehaviorWire` carries
exactly `allow` and `deny`, with no third variant, and a denial surfaces as
"PermissionRequest hook denied approval". The vendor page agrees today, but it is the
binary being trusted here, because an earlier reading of that page recorded a third
value, `decline`, that does not exist. That
is strictly more authority than `PreToolUse` has, which rejects both
`decision: approve` and `permissionDecision: allow` as unsupported. Note the shape:
unlike `PreToolUse`, `PermissionRequest` has *no* top-level `decision` field, and its
message rides on `hookSpecificOutput.decision.message` rather than a top-level
`reason`. The documented resolution order makes the authority sharper than it sounds:
a permission hook resolves *before* both the auto-review guardian and the user, so its
answer is not a suggestion that a human then confirms.

Declining is the absence of a decision rather than a third enum value: omit
`hookSpecificOutput.decision` and normal handling proceeds. That is what
`event_hook.py` already does, since it writes nothing to stdout and exits 0 on every
path, so silence is the documented no-opinion path rather than a lucky accident.

What is *not* safe is stray output. Three `decision` fields are documented as reserved
and **fail closed**: `interrupt: true`, or the presence of `updatedInput` or
`updatedPermissions`, each causes the hook to fail closed. So a forwarder that grew a
field by mistake would not approve a tool call, it would block one. That is the safer
direction of the two, and it is still a dashboard interfering with a user's session.

Before `PermissionRequest` appears in any bundled hooks file, the no-output path should
be confirmed against a real firing event rather than against a schema, and the
forwarder's output kept provably empty. A cartography tool must be unable to decide
either way.

The dispatch site may be narrower than the event name suggests, but that is a
read of the Codex Rust source with no file, commit or date recorded here:
`Approvable::permission_request_payload` appears to be implemented for the shell,
apply-patch and unified-exec runtimes only, not for MCP tools, which would mean the
event does not report an MCP permission wait even once it fires. Nothing in the
shipped binary corroborates it. `strings -a` on 0.146.1 finds no
`permission_request_payload` and no `Approvable` symbol, while the source paths it
does retain include `core/src/mcp_tool_approval_templates.rs`,
`core/src/tools/approvals.rs` and `core/src/guardian/approval_request.rs`, so MCP
approval has a module of its own and the bound is a claim about which of several
approval paths reaches the hook. That is the same class of evidence that predicted
`session_title` on Claude's `UserPromptSubmit` and lost, so treat it as a reason to
check rather than a settled bound. Settling it means driving an MCP tool to an
approval with `PermissionRequest` registered, which is the capture the payload gate
already needs.

**A defect found while chasing this, which mattered more than the hook does. Now
fixed.** The argument for wanting a permission signal is that `input_requested` is
the overlay with no dedicated clearing event: `EVENT_NAMES` carries `input_resolved`
and nothing anywhere produces it. That much was already recorded. What was not is
how badly the fallback behaved. A later `turn_started` did not durably clear a
needs-input overlay, it only outranked it for `overlay_working_ttl_sec`, and when
that working overlay expired the needs-input overlay applied again with its
*original* `blocked_since`:

| `now` | before | after |
|---|---|---|
| working overlay live | `state: working` | `state: working` |
| 90 seconds later | `state: needs_input`, original `blocked_since` | no patch: the collector's reading stands |

So a turn still running 90 seconds after its permission was granted reverted to a
false "waiting for you", and claimed to have been waiting the whole time.

The fix is in `reduce_overlays`: a needs-input overlay is superseded permanently once
a later overlay says the session is not waiting, and the check ignores whether that
later overlay is still live. Once a turn has started the earlier wait is over as a
matter of history, and history does not lapse. Two details are load-bearing:

- **Order, not presence.** Superseding is by `arrival_seq`, so a permission asked for
  *during* a turn arrives later and survives. Reversing that would silence every
  mid-turn prompt, which is most of them.
- **What it falls back to.** With the wait superseded and the working overlay expired,
  no overlay patches anything, so the collector's own reading of the store stands.
  Trusting the store again after the deadline is the point of the deadline.

`idle` is in `ENDS_A_WAIT` alongside `working` for completeness rather than necessity:
it carries no deadline today, so it already won forever. It is listed, and pinned by a
test that builds an idle overlay with a deadline it does not currently have, because an
untestable invariant is one a later change drops silently. That is precisely how this
defect arrived through the working overlay.

`subagent_start` and `subagent_stop` are real, and are now **measured** as well.
Evidence: [`docs/captures/codex/subagents-0.146.0-macos.jsonl`](captures/codex/subagents-0.146.0-macos.jsonl).

The claim above this paragraph used to read that `codex exec` exposes no way to
spawn a subagent, and that a prompt asking for one hangs until the timeout. That
was wrong, and the store said so before the capture did: of 175 subagent rollouts
on the development machine, 24 carry originator `codex_exec`. The tool set is
`spawn_agent` and `wait_agent`, `multi_agent` is stable at 0.146.0, and a prompt
naming those tools directly produced one subagent on the first attempt.

One turn, ten hook invocations:

```text
SessionStart -> UserPromptSubmit -> PreToolUse -> PostToolUse -> SubagentStart
             -> PreToolUse -> SubagentStop -> PostToolUse -> Stop -> SessionEnd
```

`SubagentStart` fires after the spawning tool call completes and `SubagentStop`
during the `wait_agent` call, so the pair nests between the two parent tool calls
rather than around them. One subagent produced exactly one start and one stop,
which is what the ledger needs, since it keys subagent overlays by child id and two
children are two facts rather than one superseding the other.

**The question that decided the mapping, answered: `session_id` is the parent's.**
It equalled the `UserPromptSubmit` session id of the same turn. `agent_id` is a
different 36-character UUID, and three things line up around it: it appears in the
child's own rollout filename, the child's `session_meta` records the parent id
rather than its own, and the child's `source.subagent.thread_spawn.parent_thread_id`
equals the hook's `session_id`. So the hook agrees with what `transcripts.codex_meta`
already reconstructs from the store, and the envelope maps straight through: the
existing `agent_id` to `subagent_id` rename is the whole adapter change.

`SubagentStop` also carries `agent_transcript_path`, `last_assistant_message` and
`stop_hook_active`; `SubagentStart` carries only `agent_id`, `agent_type` and
`turn_id` beyond the common base. `agent_type` was `default` here.

**The permission-hook doubt this work raised has since been settled**, and the
heading above is the corrected version. The short form: the event exists, the name
registers, and `codex exec` pins `approval_policy` to `never` so it can never be asked
under `exec`. Superseded in part on 2026-08-23, when an interactive run captured the
payload and showed the decision takes effect and is waited for. It stays unmapped by
decision now, not for want of a payload.

#### Antigravity status-line semantics: MEASURED, and the documented field list was wrong

Captured from two real `agy --print` sessions, 37 status-line pushes, with the recorder wired through
`settings.json` and the file restored afterwards. Records are in
[`../captures/`](captures/README.md). This measurement corrected claims made earlier in this
document from Google's documentation, and bounded what a print-mode capture can say about the rest,
which is why it is written out rather than summarised.

The payload's top-level fields are `agent_state`, `context_window`, `conversation_id`, `cwd`,
`email`, `exceeds_200k_tokens`, `model`, `plan_tier`, `product`, `quota`, `sandbox`, `session_id`,
`terminal_width`, `transcript_path`, `vcs`, `version` and `workspace`. Not all are present on every
push.

**Corrections to this document's earlier field list:**

1. None of `tool_confirmation_pending`, `task_count` or `pending_input_count` appeared on any of the
   37 pushes, and that is not evidence they do not exist. All three are declared `omitempty` in the
   agy 1.1.10 binary, so a zero value is omitted from the wire and a shape-only recorder cannot see
   it. The same is true of `email`, `quota` and `plan_tier`, which appeared on 33, 30 and 25 of the
   37 pushes rather than all of them. Both sessions were `agy --print`, a mode in which no tool
   confirmation can be pending, no input can queue and no background task runs, so the capture never
   asked the question. What this measurement establishes is the always-present field set, not the
   schema.

   **Settled since, positively**, in
   [`../captures/antigravity/statusline-confirmation-1.1.19-macos.jsonl`](captures/antigravity/statusline-confirmation-1.1.19-macos.jsonl):
   all three fields arrive. `tool_confirmation_pending` carries `true` for as long as a tool
   confirmation stands, beside a fourth `agent_state`, `tool_use`. Whether a flagged push is keyable
   was recorded in one of the five gate arms only, the one whose recorder wrote id verdicts: all
   seven of its flagged pushes carried a 36-character id in both `conversation_id` and `session_id`,
   each naming a real `conversations/<id>.db`, while the other 14 flagged pushes have no id verdict
   either way. What that file also settles is why a mapping is not the answer. The push is
   live state on a repeating render, not a transition edge: a gate that stood 65 s produced two
   pushes, both at the moment it opened, then nothing, while forcing a redraw produced a fresh pair
   each time. So an `input_requested` posted from the status line would be **clobbered by the next
   render** rather than left stuck, which is the inverse of the hazard the overlay reducer is built
   for, and any wait built on it needs both a precedence rule and a deadline.

   Two claims this document made alongside that one were wrong and are withdrawn here. The status
   line is not "Compass's only source" of Needs input for this harness by choice:
   `collectors/antigravity.py` carries no `needs_input` path at all and assigns only `idle` or
   `working`, so nothing reports it and the gap is unqualified. And an `ask_question` is not covered
   either: one stood 144 s with `agent_state` at `working` and then `idle`, adding no key, in a
   session whose sibling arms saw the confirmation flag on the same recorder.
2. `agent_state` values observed were `authenticating`, `idle` and `working`, not the five the
   documentation lists. `authenticating` is startup rather than activity and is deliberately
   unmapped, because calling it either Working or Idle invents a claim about the session. The
   interactive probe added three more the print-mode sessions never reached: `initializing`,
   `tool_use` and `error`, the last of which is a settings failure rather than a session state.

**The identity mapping resolves cleanly.** `conversation_id` and `session_id` carried the same
36-character value whenever they carried one, and that value was the stem of a real
`conversations/<id>.db`, which is what `collectors/antigravity.py` keys on. The adapter prefers
`conversation_id` because it is named for what the collector reads, with `session_id` as the
fallback. So the feared ambiguity between two id fields is not real in practice, though preferring
the durable one by name is what keeps a future divergence resolving correctly.

**The id is often empty, and that bounds what the adapter can claim.** Fourteen of the 37 pushes
carried a present-but-blank id: all four `authenticating` pushes and ten of the eleven `idle` ones,
because the field exists before a conversation does. An event with no id cannot be keyed to a row,
so this adapter reliably reports Working and usually cannot report the return to Idle. That is the
concrete reason the Working overlay carries a measured deadline: it expires, and the collector's own
reading of the store decides again. A post-turn `idle` push can still carry an id. One of the two
arms ended on an `idle` render after its working run, carrying a 36-character id that named a real
`conversations/<id>.db`; the other ended while still `working`. One arm out of two is thin enough
that the deadline stays.

**Cardinality is high.** Thirteen and 24 pushes for two short turns, mostly repeating the same
`agent_state`. So the adapter dedupes on the last state in a small memo file rather than spending the
server's per-source rate budget restating it, and forwards quota on its own slower interval because
quota changes on its own schedule.

The `hooks.json` path for Antigravity has since been built and ships: `compass/hooks.json` registers
`agy_hook.py` on `PostToolUse` and `PostInvocation`. What has not changed is why it claims so little.
Its hook vocabulary (`PreInvocation`, `PostInvocation`) is a different one, its payloads are
uncaptured, and the status line already supplies the state those hooks would only hint at, so the
adapter maps them to `store_changed` and nothing more.

### Gemini CLI, Copilot, and Factory Droid

All three document command-based lifecycle hooks. Gemini's is measured below, Factory's is measured
in part, and Copilot's is a documentation read with no capture and no adapter:

- [Gemini CLI hooks](https://geminicli.com/docs/hooks/reference/) include before/after agent and
  model events, tool events, session lifecycle, notifications, and compression.
- [Copilot hooks](https://docs.github.com/en/copilot/concepts/agents/hooks) include session, prompt,
  tool, agent-stop, subagent-stop, and error events. Copilot CLI 1.0.78 accepts them at three
  scopes: bundled in a plugin, repo-level in `.github/hooks/*.json`, and user-level in global
  `config.json`. Event names, cardinality and payloads are unmeasured.
- [Factory hooks](https://docs.factory.ai/reference/hooks-reference) include session lifecycle,
  prompts, notifications, stops, subagent stops, and tool events. Factory documents notification
  cases for permission waits and idle input waits. Partly measured on droid 0.202.0 in
  [`../captures/droid/notification-0.202.0-macos.jsonl`](captures/droid/notification-0.202.0-macos.jsonl):
  hooks register from a project-scope `.factory/hooks.json` and fire before the account gate, so
  `SessionStart` and `SessionEnd` payload shapes and the session identity are settled, and both of
  `collectors/droid.py`'s candidate keys agree on a 36-character id. The notification vocabulary is
  not: every one of the three types this binary can produce is raised from agent-turn code, which
  needs a Factory account, so it is unreachable rather than absent. Two things in that file bear on
  what may ship. Droid loads a `.claude-plugin` root, unwraps the same `hooks` key Claude's format
  uses, and expands `${CLAUDE_PLUGIN_ROOT}`, so a Droid that finds a compass root would run
  Claude's hooks file and post to `/api/events/claude`, where the id is truncated to eight
  characters and matches no row. And `auth_success`, the fourth documented notification type, does
  not appear in the 0.202.0 binary at all.

The [Gemini extension format](https://geminicli.com/docs/extensions/reference/) can bundle
`hooks/hooks.json`, and this repository already ships an extension manifest. Gemini CLI's
[consumer-account transition](https://github.com/google-gemini/gemini-cli/discussions/28017), a
vendor discussion thread rather than a documentation page, is read as leaving enterprise Code Assist
and API-key use in place. Not measured, and the capture below could not measure it: the auth check
runs before any hook fires, so the only route to a real session was a loopback stand-in for the API,
and the capture records no authentication mode. Call out the affected authentication populations as
unverified rather than labeling the whole harness legacy.

These hooks are synchronous in at least some implementations, which puts the forwarder's cost on the
user's own agent latency. The forwarding command must do no collection work itself, must use a short
bounded loopback request, and must not make an unavailable dashboard visible as a harness failure.

#### Gemini CLI adapter semantics: MEASURED, and the harness is not legacy

Evidence: [`docs/captures/gemini/`](captures/gemini/), from Gemini CLI 0.53.1 on macOS.

**The premise was wrong before the payloads were.** This document and the collector both described the
Gemini store as legacy. Gemini CLI 0.53.1 published on 2026-07-31, nightly builds were still landing
two days before this measurement, the package is not deprecated, and a real 0.53.1 session was
observed writing `<tmp>/<project>/chats/session-*.jsonl`, the exact layout `collectors/gemini.py`
globs. Consumer access ended; the CLI did not.

**How a real session was reached without a credential.** The auth check runs before any hook fires, so
an unauthenticated run produces nothing at all: exit 41 and zero hooks. Consumer accounts are no
longer served, so there is no ordinary login to use. The route that worked is
`GOOGLE_GEMINI_BASE_URL` pointed at a loopback stand-in for the API, with an isolated
`GEMINI_CLI_HOME`. Every hook, store write and session id in the capture is genuine; only the model
was substituted. That also made the model's behavior scriptable, which is how a tool call was
exercised deliberately rather than hoped for.

**Vocabulary, cardinality and ordering.** Four turns, 56 hook invocations, identical ordering 4 out of
4:

```text
SessionStart -> BeforeAgent -> PreCompress -> BeforeModel -> BeforeToolSelection -> AfterModel
             -> BeforeTool -> AfterTool
             -> PreCompress -> BeforeModel -> BeforeToolSelection -> AfterModel
             -> AfterAgent -> SessionEnd
```

`BeforeAgent` and `AfterAgent` fired exactly once per turn and bound it. `BeforeTool` and `AfterTool`
fired once per tool call. `PreCompress`, `BeforeModel`, `BeforeToolSelection` and `AfterModel` fired
once per model round trip, twice in a turn with one tool call, which is why none of them is a session
signal. The payload is the same snake_case shape Claude and Codex send, down to `session_id`,
`transcript_path`, `cwd`, `hook_event_name` and `timestamp`. That resemblance is deliberate: Gemini
ships a `gemini hooks migrate` subcommand for porting Claude Code hooks across.

**Identity: the whole id, matched against the store.** Five verdict records, five exact matches
between the hook's `session_id` and the `sessionId` on line 1 of the transcript the same session
wrote, all 36 characters. Records and not sessions: the identity file carries no session marker, so
it cannot say whether five sessions or five writes produced them, and the four above is the count
the hooks capture supports. So `IDENTITY_NORMALIZERS["gemini"]` is the whole-uuid normalizer, not Claude's truncating
one. The trap worth recording: the store *filename* carries only the first eight characters, so a
mapping keyed on the name would key on a prefix the collector never reads.

**Cost.** p50 0.16 ms, p95 0.43 ms, p99 0.61 ms, max 0.61 ms, macOS, hook self-cost across 56
invocations. Linux and Windows remain unmeasured.

**The one thing still unmeasured, and it is the one worth wanting.** `Notification` is documented as
carrying `notification_type: "ToolPermission"`, which would be a first-class permission signal, better
than Claude's ambiguous notification and better than Codex, whose permission hook exists but cannot be
reached in the only mode this project drives non-interactively. It could not be captured either, and
not for want of trying: non-interactive Gemini offers no tool that needs approval. The advertised set
was `glob`, `grep_search`, `list_directory`, `read_file`,
`google_web_search`, `invoke_agent`, `update_topic` and `enter_plan_mode`, with no shell and no write
tool, so no approval prompt can arise. It is therefore absent from `GEMINI_EVENTS`, on the same rule
that keeps unmeasured Codex subagent events out. Capturing it needs an interactive session.

#### Two harnesses cannot share one hooks file, and sharing one root shipped a defect

Distribution turned out to be the hard part, and the collision is not avoidable by naming.

Claude Code reads `<plugin root>/hooks/hooks.json` unconditionally. Declaring another path in
`.claude-plugin/plugin.json`, or inlining the hooks object there, does not release the slot:
`claude plugin validate --strict` still reads that file and rejects any event name it does not know.
Gemini CLI reads `<extension>/hooks/hooks.json` and its reference states plainly that hooks "are not
defined in the `gemini-extension.json` manifest", so it cannot be redirected either. Both were
confirmed by running the two validators against the same directory.

Before this was noticed, `compass/` carried both `gemini-extension.json` and Claude's
`hooks/hooks.json`, and the README told users to install that directory as a Gemini extension. What
that produced, measured on a real session:

- eight `Invalid hook event name ... Skipping.` warnings on stderr, one per Claude-only name;
- the two names that do overlap, `SessionStart` and `SessionEnd`, registered and run, then reported to
  the user as failed hooks, because Gemini does not expand `${CLAUDE_PLUGIN_ROOT}`;
- 258 ms and 259 ms of synchronous cost per session, for nothing.

That is precisely the failure this section warned about two paragraphs earlier: making an unavailable
dashboard visible as a harness failure. The fix is a separate extension root, `compass-gemini/`,
holding the Gemini manifest, a Gemini-vocabulary `hooks/hooks.json` using `${extensionPath}`, and
byte-identical copies of `event_hook.py` and `notify_hook.py`. The copies are the cost of the split:
`gemini extensions install` copies the directory and a git-URL install clones it, so a command
reaching outside the extension root does not resolve once installed.

Two validator rules now hold the shape, because nothing in the build noticed the defect for a whole
release. No bundled hooks file may register an event name its harness does not recognise, or pass
another harness's name to `event_hook.py`; and a script that ships twice must be byte-identical in
both places.

### OpenCode

OpenCode has two native options, and one of them is now measured.

- Its [plugin API](https://dev.opencode.ai/docs/plugins/) is **measured** on opencode 1.18.20, in
  `docs/captures/opencode/plugin-permission-1.18.20-macos.jsonl`. A plugin is one plain file under
  `.opencode/plugin/`, loaded with no install step, so the npm route the earlier read assumed is not
  required. `permission.asked` carries `sessionID`, `id`, `permission`, `patterns`, `metadata`,
  `always` and `tool`; `permission.replied` carries `sessionID`, `requestID` and a `reply` of
  `once`, `always` or `reject`. The `sessionID` on both is exactly the `session.id` the OpenCode
  collector already keys on, so the pair maps onto `input_requested` and `input_resolved` with no
  dwell, no expiry and no inference. `session.idle` fires once per turn end and carries `sessionID`
  alone.
- Its [server](https://dev.opencode.ai/docs/server/) is documented to expose `/global/event` and
  `/event` SSE streams, session listing, and session status. Documented only, since no OpenCode
  server has been started here.

The plugin is the proven path. The shared server would be zero-install where the exact TUI server
can be discovered and authenticated, but the TUI may select a random host and port and an operator
may configure authentication, so that path stays conditional. The server documentation states that
`opencode serve` starts a new server when a TUI is already running, and that the TUI picks its port
and hostname at random. Whether that new server can see the first instance's sessions or events is
not documented and has not been tested here.

The same capture closes the store-only alternative. Measured while an approval dialog stood on
screen for 130 s, 76 s and 36 s: the store's `permission` table holds project-scoped saved approvals
and stayed empty, even after an "Allow always", which OpenCode's own dialog says holds only until
restart. The durable `event` table carries session and message types alone. And no `session.status`
event is delivered between the ask and the reply in any gated arm. The grant and always arms' status
sequences match the ungated control's exactly and the reject arm's differs only by a `retry`, so the
status lane never announces the wait. Nothing but a single `session.updated` reaches a reader
between the ask and the reply, and the store's own counts advance at most once inside the gate
window and then hold.

### Pi, Cursor, and Goose

Pi exposes an extension event model, so a small package suits passive events better than its ACP
adapter. [Cursor documents hooks](https://cursor.com/docs/hooks.md) and plugin installation, but its
official documentation does not establish complete ordinary local-CLI parity; fixture-test each
transition. Its [structured output](https://cursor.com/docs/cli/reference/output-format.md) is
documented as opt-in `--output-format stream-json` in explicit or inferred print mode, with `text`
the default.
Goose's [official documentation](https://block.github.io/goose/) describes CLI, API and managed ACP
server modes. The paragraph that stood here concluded from those topologies that nothing could
attach passively to an already-running ordinary CLI session; that is no longer true, and the way it
stopped being true is worth keeping. Goose auto-discovers a plugin's `hooks/hooks.json` under
`~/.agents/plugins/`, and [`../captures/goose/tool-confirmation-1.47.0-macos.jsonl`](captures/goose/tool-confirmation-1.47.0-macos.jsonl)
records goose 1.47.0 registering all eleven event names a probe plugin offered it, seven of them
observed firing from an ordinary interactive session and carrying the whole ten-character
`sessions.id` the collector already keys on. What that route does not reach is
the tool-confirmation gate: no hook fires in the 83.2 s between the prompt and the answer, the
window that contains the standing dialog, and the store is silent across it too, so the turn
boundaries are reachable and the needs-input signal is a measured blank rather than an unread one.

For all three, the current store collectors remain the safe compatibility baseline. Event support
can be added only for the states proven by contract tests and real CLI fixtures.

## Proposed runtime design

```text
Claude/Codex hooks ───────┐
Antigravity statusLine ───┤
Other hooks/extensions ───┼──► Event ingress ──► Dirty queue ──► Per-harness collector
Native server streams ────┤                          ▲                    │
Managed ACP sessions ─────┘                          │                    ▼
                                                     │          Materialized snapshot
Coarse store stat probe ─────────────────────────────┤                    │
Slow reconciliation scan ────────────────────────────┘                    ▼
                                                                 SSE revision stream
                                                                          │
                                                                          ▼
                                                                   Dashboard tabs
```

### Module ownership

Four responsibilities in this design have no owner in the current module map, and the obvious
placement would invert the enforced dependency rule. Putting a publish protocol, revision counter,
dirty queue and deadline scheduler into `state.py` makes `state` import `aggregate`, which imports
`state`: an import cycle, and a failure of R-2, the inward-only dependency rule, which
`test_runtime_import_graph_matches_the_reviewed_allowlist` enforces. `design-runtime-architecture.md`
says that allowlist changes only in a PR that makes a reviewed ownership decision, never to make the
test pass.

Name the owners before implementation:

- `events.py` owns pure envelope validation, identity normalization and transition reducers;
- `snapshot.py` owns immutable published payloads, the revision pair and subscriber notification;
- `observation.py`, above `aggregate`, `events` and `snapshot`, owns the bounded dirty coordinator,
  the single collection lane, collection floors, the probe, deadlines, reconciliation, worker
  lifecycle and deterministic shutdown;
- `http_api.py` owns the stream and ingress routes through an injected observation interface.

The CLI constructs an inert coordinator. `lifecycle.serve` starts it only after the final POSIX fork
or in the Windows child, then stops ingress, wakes conditions, closes stream clients, joins every
worker to a deadline, closes the server and removes state in that order. Constructors must not start
threads before daemonization. A synchronous GET submits work to the same collection lane and waits;
dirty refresh, reconciliation, `?all=1` and GET freshness may not run collectors concurrently or let
an older slow result replace a newer result. Amend `design-runtime-architecture.md` and the reviewed
import allowlist in the same implementation PR.

### Event ingress

Use a source-specific path, for example `POST /api/events/codex`, so the server assigns the harness
from the route rather than trusting a payload field. A route is not authentication: new event ingress
requires the per-run capability described under [Security and privacy requirements](#security-and-privacy-requirements).
Normalize only an allowlisted envelope:

```json
{
  "v": 1,
  "event": "input_requested",
  "session_id": "opaque-harness-id",
  "timestamp": "2026-08-04T12:34:56Z",
  "source_instance_id": null,
  "source_sequence": null,
  "cwd": null,
  "subagent_id": null,
  "transcript_path": null
}
```

The public normalized event vocabulary can remain small:

- `session_started`
- `session_ended`
- `turn_started`
- `turn_stopped`
- `input_requested`
- `input_resolved`
- `subagent_started`
- `subagent_stopped`
- `tasks_changed`
- `store_changed`
- `reconcile_required`, for a source-specific cache invalidation such as completed compaction

Adapters translate native names. Unknown event names are ignored rather than accepted into state.
The forwarder shapes every native payload to its destination's minimum schema, and the server repeats
validation because every hook input is untrusted. `cwd` is an optional matching hint, never a display
field or authority to create a row, and is never echoed. `transcript_path` is allowed only for the
validated Claude clearing rule described under security and is never echoed.

Ordering uses three deliberately separate concepts:

- `arrival_seq` is assigned by the server under the ingress lock after authentication and validation;
  it is monotonic for one Compass process and defines deterministic reducer order for concurrent
  handler threads.
- `(source_instance_id, source_sequence)` is optional and is used only when the native source supplies
  both trustworthy values. It supports source-local deduplication and ordering.
- `session_generation` is a server lifecycle invalidation generation, like the existing
  `hook_generation`; it is not an external event counter.

A fresh command-hook process cannot mint a shared sequence. Sources without a trustworthy native key
have at-least-once, possibly reordered delivery: reducers must be idempotent, may use a bounded
canonical-payload replay cache where safe, and reconcile ambiguous transitions. A lower source
sequence without a new source-instance identifier cannot distinguish a restart from a delayed packet,
so it triggers conservative reconciliation rather than unconditional rejection. Event timestamps
drive plausibility and displayed timing only; neither wall time nor filesystem time fences concurrency.

Event timestamps are parsed to epoch seconds and passed through the same plausibility filter as every
store timestamp, so an implausible stamp is replaced by server arrival time. A hook inside a
container whose clock runs hours ahead must not be able to pin a row.

### Envelope versioning

Adapters installed in user-owned configuration are not upgraded when Compass is. The envelope is
therefore a versioned compatibility surface with an indefinite support tail, not an internal wire
format. Every event carries `v`; the server accepts a documented range of versions; and an
out-of-range `v` is reported through `--diagnose` and the acquisition-mode strip as
`event-incompatible` rather than silently ignored, which is what the unknown-name rule above would
otherwise do to it. Removing a field or changing a field's meaning is a breaking change to a public
interface.

### Session identity

The envelope's `session_id` is not the key the collectors use. Claude's `sid` is the eight-character
prefix of the transcript filename and `dedupe_sessions` keys on `(harness, sid)`, which is why the
existing notification path truncates the hook payload's full UUID before looking anything up. An
overlay keyed on the raw native id would never match its row.

The ingress therefore owns a per-harness identity normalizer that maps a native event id onto the
exact `sid` its collector produces and rejects ambiguous mappings. A normalized id that matches no
collected session goes into a small bounded, expiring pending map and triggers collection; it never
renders and never creates a row. It attaches only if a later collection produces the matching
`(harness, sid)`, otherwise it expires after bounded time and attempts with a diagnostic counter.
This preserves first-session and early permission events without letting a wrong or forged id invent
a session. The mapping and pending behavior must be established per harness before its adapter ships.
At capacity, reject new pending entries and count the rejection rather than evicting a live alert.

### Dirty queue and coalescing

An event handler must acknowledge quickly. It should not scan a transcript or query SQLite on the
hook's request thread.

Instead it should:

1. Authenticate, validate and normalize the event.
2. Assign its `arrival_seq` and apply only a transition that is unambiguous and safe, if one exists.
3. Mark the session or harness dirty by advancing its dirty generation.
4. Signal the coordinator condition.
5. Return promptly; the reporting shim exits successfully even if Compass rejects or drops it.

The coordinator coalesces an event burst for roughly 50 to 150 milliseconds. The window is fixed,
not sliding: a sliding window never closes under a sustained burst and the board would stop updating
entirely. Every overlay in a burst is reduced in `arrival_seq` order. A matched `input_requested` is
exempt from the delay and publishes an overlay revision immediately; an unmatched request remains
non-rendering in the pending map until a collector supplies its row. No event is assumed to arrive
alone.

Coalescing bounds burst latency but sets no floor between collections, and removing the 2.5-second
memo would remove the only rate limiter on store reads. A ten-agent fan-out emitting lifecycle events
continuously would drive roughly 6.7 full collections per second against today's ceiling of 0.4.
Keep an explicit minimum interval per harness, the role `collect_memo_sec` plays today. The first
dirty event schedules collection at the later of the fixed coalescing deadline and the harness's next
allowed collection time; subsequent events merge into the pending state. Semantic overlays may
publish before that collection. The floor is the store-protection guarantee and must not be a derived
side effect of the coalescing window.

The bounded coordinator exists regardless of whether selective collection proves worthwhile: it
serializes events and scans, enforces floors, and keeps collection off request threads. The existing
`HarnessSpec.collect` boundary makes per-harness refresh feasible. The Phase 0 selective-reuse gate
is undecided from one machine: Claude was 83% of a 118 to 120 ms collect there, about a 17% saving
against a 25% bar, on a store 71x skewed toward Claude. Phase 1 therefore marks the aggregate dirty
and performs one full `Application.collect` per floor, behind an interface that can serve per-harness
merges if a multi-harness profile clears the bar. The paragraph below describes the selective path
for that day.

When selective refresh is enabled, the new application state retains one current result per harness,
merges only the refreshed harness, deduplicates and sorts the aggregate, then serializes a new
version. Retained per-harness results are immutable once
published. `assign_display_ids` is idempotent over a fixed row set, so re-running it is not the
hazard; a merge that changes the row set is, because widening is per `(harness, project)` and a Codex
worker widening the retained Claude list while `/api/data` serializes it can emit one session at two
id widths, the exact confusion display ids exist to prevent. The mutations with no unpatched base to
restore are `events.apply_patch`'s five in-place display fields and the Claude collector's
clock-derived `elapsed_h` and `updated_ago` writes into embedded task dicts. Merging must therefore
build a fresh aggregate list before dedupe, display-id assignment and sorting run over it. The single
coordinator lane serializes collection and merge, rather than merely placing a lock around the final
merge.

`show_all` is decided here rather than deferred, because it is not a presentation filter: it reaches
into the collectors and changes what they return. The snapshot is built for the default window only.
In the first delivery, `?all=1` keeps its existing five-second polling fallback behind its own memo
instead of reacting to default-view revisions; its collection still runs through the coordinator and
the same overlay/fencing pass. A later on-demand historical snapshot may replace that fallback.
Deriving both centrally from one raw snapshot would mean always collecting the unfiltered set, and on
a machine with 3,600
historical Claude transcripts that is the expensive path taken on every lifecycle event, forever, for
a rarely used historical query.

### Event overlays versus store truth

Some native events are semantically stronger than persisted stores:

- prompt or before-agent event → Working;
- explicit permission request → Needs input;
- permission reply or resumed agent activity → Working;
- stop or after-agent event → Idle, after a short dwell;
- subagent start/stop → update child activity.

Other events only mean that the store probably changed. Provenance matters: an explicit native
permission request can patch `state`, `state_detail`, `active`, `blocked_since` and the event-derived
activity marker. A generic or actionable Claude `Notification` remains standing hook state under
today's precedence; it is not promoted to an authoritative permission overlay.

Precedence is per field and per provenance, not per timestamp. A live Working or explicit-permission
overlay may be authoritative for the fields above when its adapter contract proves the transition.
For every other field the collector is authoritative: titles, projects, historical turns, tasks,
token rates, parent relationships, subagent reconstruction and recovery after missed events. That is
what makes a long generation stay Working without letting a hook rewrite collector-owned metadata.

Wall-clock recency cannot fence a concurrent collection. Under the ingress lock, each collection
captures `collection_start_seq` and the harness dirty generation before reading. Under the merge lock
it then:

1. installs the collector result only through the single collection lane;
2. applies **every live overlay**, including overlays that predate collection start, in `arrival_seq`
   order;
3. refuses to retire an overlay whose `arrival_seq` is newer than `collection_start_seq`; and
4. leaves the harness dirty and queues another pass if its dirty generation changed during the read,
   because a non-semantic `store_changed` event cannot be recovered by overlay replay.

The overlay ledger is immutable apart from explicit retirement records. `arrival_seq`, not an epoch
clock, closes the mid-collection race. A collector can retire an older overlay only through a
documented, source-specific evidence rule.

One such rule already exists and must be preserved: the Claude collector lets fresh transcript or
background activity beat a standing `Notification`, because Claude Code can emit an input-waiting
notification for a session that continues running. An explicit `PermissionRequest` is different and
must be cleared by a reply, resumed activity known to follow it, session end, or equivalent positive
collector evidence. Working overlays get a measured deadline so a missed stop cannot pin Working.
Needs-input overlays do not get an arbitrary time-only expiry; event-source liveness can become stale
without silently clearing a real hours-long permission wait.

Claude has a second, bounded source-specific rule, measured on 2026-11-12 with Claude Code
2.1.322 on macOS against Compass 2.11.0. The three headless arms in
[the headless-wait capture](captures/claude/headless-wait-2.1.322-macos.jsonl) show a foreground
Bash call and a shell loop becoming Idle after 90 seconds without a result, and a parent becoming
Idle at Stop while `claude -p` remains alive waiting for its background Agent. A child file going
quiet does not establish completion. The capture also shows the stale Working tail after exit.

`claude_data.analyze_transcript` matches foreground non-input calls only within the newest assistant
message id. Parallel calls sharing that id remain pending independently. A new assistant message id,
a user record other than tool results, a turn stop or a compaction boundary clears the pending set.
Sidechain records and records whose session id differs from the transcript filename never enter or
answer that set. Missing message or session identity earns no extension. The Claude collector keeps
the newest remaining call Working as `running <tool>` until its own tool timestamp plus
`claude_tool_in_flight_max_sec` (900 seconds). A Stop or interruption always ends this foreground wait.

The collector also reuses `project_context.delegated_work_status`'s cached completion pairing, but
only outstanding parent Agent/Task launches with `run_in_background`, a successful launch tool
result, and a launch at or after the current turn's floor qualify. A later interruption or new user
prompt retires a launch even if it was acknowledged. Calls, acknowledgements, completion pairing
and turn boundaries use only records with the parent's native session id (the transcript filename
stem), excluding sidechain records. Missing identity earns no exception. Background Bash launches,
shell `&` jobs, Monitor calls and earlier-turn launches do not qualify. The row reads
`waiting on 1 background task` or `waiting on N background tasks`, counting only qualifying launches,
even after the parent's Stop and with an old child file. TaskOutput and task-notification completion
pairing includes the queued attachment's `attachment.prompt`, measured in
[the mid-turn shape capture](captures/claude/mid-turn-and-answer-shapes-2.1.305-macos.jsonl).
This background lease expires at the newest qualifying unpaired launch plus the same cap,
independently of any foreground call. Neither child
activity nor a newer completed launch renews it. The ceiling matches Pi because neither transcript
can prove a process killed mid-call survived. The accepted cost is that a session killed mid-tool
without an observed end reads Working until the 900-second cap rather than the former 90-second
activity window. SIGKILL was the only measured ending without SessionEnd in
[the ending capture](captures/claude/session-end-2.1.261-macos.jsonl); every other measured ending
sent it. After either expiry the existing freshness and stop rules apply. No process-liveness probe
is added.

The collector publishes nullable `work_in_flight_until` solely as current-turn background-subagent
evidence; `state_detail` carries the wording. It does not advance `own_activity`, `work_activity`
or `last_activity`. `reduce_overlays` lets an Idle overlay and a remembered turn stop yield within
that background cap only; foreground evidence never suppresses either stop. It does not weaken an
explicit input overlay or change its activity guard. Transcript
input tools and standing notification waits retain precedence over this extension. An observed
`ended_at` disables the exception; after reduction, `Application._apply_overlays` settles an ended
Claude row to Idle and clears the lease, also ending the existing fresh-child Working tail. A
remembered Stop that survives reduction also settles a Working Claude row to Idle when its live
overlay is gone; preserving `finished_at` alone would leave the foreground extension running. A new
Working or input overlay can still retire an old end under the existing reopening contract.

Notification delivery reads the final reduced row. The browser's Working-to-Idle quiet edge is
therefore delayed for this outstanding work; a real completed turn still settles immediately under
the existing stop rules. Native quiet nudges still read the harness's `idle_prompt` notification.
Permission waits still set their original `blocked_since`, enter Attention's input queue and notify
once. Task and turn ETA calculations keep their existing inputs; the extension invents no activity
or progress measurements. `ClaudeHeadlessActivityTest` covers the capture shapes, cap, completion,
end and prompt precedence; `ApplicationPopupTest.test_extended_claude_work_yields_to_a_gate_and_notifies_once`
covers the final row, shared Attention queue and notification transition without a server.

`session_ended` is non-destructive. It retires overlays and hook state but never removes a row; only
the collector may do that. Claude is documented as firing it on `/clear` as well as on exit, so a
user who clears and immediately prompts again can produce `session_ended` and `turn_started` for the
same session inside one coalescing window. Not measured: the capture is headless and `/clear` is
interactive, so only the `reason` field name was observed, never its value. A killed harness may
never send it; in that case its source-health lease
expires while the alert remains until positive evidence resolves it or the collector removes the row
from its authoritative window.

Compaction is a conservative invalidation hint, not documented proof that Claude rewrites its JSONL.
If fixtures show a transient mutation window, `PreCompact` marks rewrite-in-progress and suppresses
collection; `PostCompact` emits `reconcile_required`, clears only the scan or metadata caches proven
unsafe, and performs a full session reconciliation. If only one event is supported, use
`PostCompact`. Offset/size discontinuity detection and periodic reconciliation cover compaction with a
missed event. Neither hook counts as activity. Tests must cover both append-only and rewrite fixtures
before the implementation assumes either storage behavior.

Notification ownership has to move with this. Both the native notifier and browser notification text
hardcode Claude today. Before any second harness can report Needs input, titles and bodies must derive
from the matched row's harness label. The server assigns a stable alert generation so overlay- and
collector-derived views of one wait deduplicate against the same identity; native and browser ledgers
consume that identity according to the user's channel policy. Only the elected browser leader may
issue browser notifications; follower tabs render the shared snapshot without each producing another
popup.

### Versioned snapshot

Replace the 2.5-second response memo with a durable in-memory snapshot and monotonically increasing
revision:

- `/api/data` returns the latest already-built bytes, subject to the freshness rule below.
- Collection workers, deadline timers, quota updates, and hook overlays publish revisions.
- A revision increments only after a material state change or a deliberate generated-time update.
- Collection failure for one harness retains the existing per-harness failure boundary.
- The cache remains bounded and process-local; the first demanded snapshot is reconstructed from
  stores before it is served. An idle daemon with no request and no event still does no filesystem
  work.

A revision number alone is not a safe cursor, because it restarts at zero when the process does. Every
revision is the pair `(server_started, revision)`. `server_started` already exists and `/api/health`
already publishes it. The pair distinguishes a restart; it does not "survive" one. Any change in the
first element forces the client to discard its cursor and refetch. `/api/data` returns the revision it
actually served, so the client compares what it got rather than what it was told. Otherwise a tab
frozen at revision 512 across a dashboard restart would treat every subsequent revision as older and
never refetch, showing an hours-old board behind a live indicator.

`/api/data` must also remain self-freshening. Define a direct-GET maximum age no greater than today's
`collect_memo_sec` (2.5 seconds by default), independently of the slower reconciliation interval. A
GET beyond that age submits a collection to the coordinator and waits before answering.
`curl -s http://127.0.0.1:4553/api/data` is printed by the bind-error message when a port is already
in use, and a headless or SSH-forwarded caller has no SSE connection and no tab. A snapshot-only read
would hand them arbitrarily stale data. This keeps the current freshness
contract rather than quietly replacing 2.5 seconds with 30 to 60 seconds.

Time-derived fields need their own contract, but the wire snapshot does not currently retain enough
inputs to recompute them cheaply. Before Phase 1, inventory `rate_per_min`, `turn`, Claude task
`elapsed_h` and `updated_ago`, `active`, history-window membership, overlay dwell/expiry and
`generated`. For each, either retain immutable derivation inputs outside the wire snapshot or admit
that the tick recollects and measure that cost. A scalar `rate_per_min` cannot decay itself; its source
timestamped usage events or database projection must remain available.

Use one documented sampling cadence after that design is proven. Add a `rate_sampled_at` value (or an
equivalent fixed time bucket) so the frontend appends at most one sparkline point per cadence. Event,
quota and notification revisions must not create extra samples merely because `generated` advanced;
otherwise an event burst distorts the rate graph. Without an explicit derivation and sampling design,
keep today's five-second collection behavior for these fields.

### SSE browser delivery

Add a `GET /api/stream` endpoint that is strictly same-origin. It must not inherit the `do_GET`
default: `do_GET` passes `allow_cross_site_navigation=True` so a cross-site *document* navigation can
reach the dashboard, while `do_POST` uses the strict check. A long-lived data stream is not a document
navigation and must use the strict form. SSE is preferable to WebSockets for the dashboard
because updates are server-to-browser; existing HTTP POST endpoints already cover shutdown and any
future controls.

A minimal stream can send revision numbers rather than duplicating the full dashboard payload:

```text
id: 1722765296.125/123
event: revision
data: {"server_started":1722765296.125,"revision":123}

```

The page loads `/api/data` once, opens `EventSource`, and fetches the cached payload whenever it sees
a newer revision. This design preserves the current rendering functions and keeps large JSON out of
the long-lived stream. Every connection receives the current pair immediately. `EventSource`
reconnects automatically and sends the last string as `Last-Event-ID`; the server, not the browser,
owns replay policy. When the server identity differs it sends a `reset` event and forces a data
refetch. When it matches, sending the current revision is sufficient, so a replay buffer is not
required. Leader handoff shares the complete pair, not the numeric revision alone.

Three constraints apply, and none of them is optional.

The first is the browser's connection budget. HTTP/1.x browsers commonly cap persistent connections
near six per browser and domain, so one `EventSource` per tab can starve other requests. Exact limits,
pooling and failure behavior are user-agent-dependent; the risk is not a theorem that the seventh tab
always freezes. Elect one leader tab per origin over `BroadcastChannel` or a `localStorage` lease to
hold the single stream and fan revisions out to the others, with a hard staleness deadline and tested
handoff. Unsupported coordination falls back to bounded polling rather than opening unbounded streams.

The second is the response path. The handler's `protocol_version` is HTTP/1.0 and its send helper
always sets `Content-Length`, so the stream needs its own persistent response path and an explicitly
tested HTTP version rather than an extension of the existing helper. Send and flush an SSE comment
heartbeat about every 15 seconds so intermediaries and clients can detect a dead connection.

The third is connection, thread and lock discipline. A stream cap alone is insufficient because
`ThreadingHTTPServer` creates a handler before the route is known, and partial headers or bodies can
occupy threads. Add a server-wide accepted-connection/handler budget, header and body read deadlines,
exact body-length enforcement and a smaller SSE cap. Give every accepted stream a one-slot
latest-revision queue and a socket write timeout; collapse intermediate revisions rather than growing
a FIFO. Never hold snapshot or client-registry locks across a socket write. The snapshot is published
as one immutable `(revision_pair, bytes)` value under a short lock. Today the collect memo lock is held
across collection, so that is exactly the lock the implementation will be tempted to reuse.

While the default-window stream is healthy, the browser's five-second refresh timer disappears. In
Phase 1, before hooks or the probe exist, one demand-scoped server producer runs the current
five-second collection cadence while at least one stream client is connected and stops at zero
clients. Merely opening a passive connection is not a recurring trigger. Later phases may replace
that producer only when their correctness gates pass. A slow adaptive fallback remains for
unsupported browsers and prolonged disconnection, while `?all=1` retains the explicit fallback above.
The client coalesces revisions behind a minimum render interval. The frontend rebuilds `#app` from
scratch on every render and reapplies reader state afterwards, so a burst arriving several times a
second during a fan-out would
destroy and rebuild the DOM under a user mid-keystroke. Skip re-rendering while an interaction is in
progress.

Shutdown closes stream sockets and must prove long-lived handlers and every observation worker exit
within the shutdown deadline.

### Deadline scheduler and reconciliation

The runtime needs two kinds of background scheduling:

1. Exact deadlines. Working-to-Idle transitions, transient-overlay expiry, source-health leases,
   history-window removal, and similar state derived from time. Needs-input retirement requires the
   positive evidence defined above, not a generic TTL. A condition-driven priority queue or
   recalculated nearest deadline avoids a busy loop. Deadlines must tolerate a machine that suspends
   and resumes, where a batch of them comes due at once.
2. Reconciliation. A full or dirty-aware store scan that repairs state after dropped events, unclean
   harness exits, unsupported versions, or files copied into a store.

A reasonable starting policy is:

- full reconstruction on the first `/api/data` or stream demand, or on an event that requires a row
  for an immediate native notification; no eager scan merely because the daemon started;
- direct-GET maximum age at or below today's 2.5-second memo age;
- the current five-second connected-client producer for Phase 1 and for sources without proven
  invalidation coverage;
- immediate selective collection after events;
- 30 to 60 second reconciliation only for sources whose probe or event topology has passed its
  correctness and liveness gate;
- a longer interval when no tab is connected, while hooks continue to maintain native notification
  state. A read still collects on demand, so no timer-driven scan is not the same as no scan;
- immediate reconciliation on tab focus, stream reconnect after a long gap, or manual refresh.

The exact values should follow measurements rather than become undocumented constants.

Three timings are independent configuration values: direct-GET maximum age, connected-client
producer cadence and slow reconciliation cadence. Conflating them silently weakens the headless API.

Two classes of session get *worse* under a slower reconciliation cadence and must be exempt. A
session in a container or remote shell has its own loopback, so its hook POSTs to a `127.0.0.1` that
is not the host's and the event is lost by design; if its store is bind-mounted, polling sees it today
at five seconds and would see it at 30 to 60 instead. The same applies to any harness with no healthy
event source. Either the reconciliation floor stays at the current poll interval for those harnesses,
or the acquisition display shows those rows as `scan-only` with their true latency. The degradation
must be disclosed, not silent. A command-hook receipt is not a harness heartbeat: an idle session,
disabled hook and broken hook are otherwise indistinguishable. Track `installed`, `compatible` and
`live` separately. Only a verified heartbeat or persistent source subscription establishes continuing
liveness; a one-shot hook establishes at most a short per-session lease and never justifies reducing
harness-wide reconciliation on its own.

### Quota consent and refresh

Today a page adds `usage=1` to `/api/data` only after the user has enabled the feature and answered
the disclosure. That request may schedule a vendor quota fetch behind its existing floor and
in-flight gates. [`SECURITY.md`](../SECURITY.md) publishes the resulting property: with the feature
off, nothing is fetched or retained, and no polling happens while no dashboard page is connected.

Phase 0 repaired the two existing violations of that contract: Windows daemon respawn now carries
`--no-usage`, and `/api/usage` now discards quota fields before storage whenever server-side usage is
disabled, while still answering 200 so a status line never sees an error. Those were security
prerequisites, and Phase 1 may now claim the contract it preserves.

Under SSE, quota consent remains browser-originated but cannot depend on unrelated revisions. The
elected tab is the only quota-triggering client. It broadcasts `localStorage` consent changes to all
tabs, transfers the current value on leader handoff, and sends or renews a short-lived same-origin
server consent lease while enabled. Revocation clears that lease immediately; absence of a page lets
it expire. A consenting leader sends an explicit quota-due request no more often than the existing
vendor/cache floor, so five quiet minutes still refresh without a session revision. A server timer
never initiates an outbound vendor fetch by itself, and background fetch completion publishes a
snapshot revision.

Antigravity status-line forwarding separates always-allowed lifecycle fields from quota fields. The
server drops quota before storage when `--no-usage` is set or no consent lease exists. Quota
acquisition and session acquisition remain separate schedulers even when both publish into the same
dashboard snapshot.

## Installation, upgrade, and removal

Every adapter Compass does not distribute through a harness plugin is user-owned configuration that
outlives Compass's own installation. The hazard is already reachable: the shipped skill tells users
to hand-add a `notify_hook.py` command to their Claude settings, and uninstalling the plugin deletes
that path while leaving the hook in place, so every later session runs a command that cannot be found.

The plan must therefore include:

- plugin- or extension-bundled hooks wherever the harness supports them, using its native trust and
  uninstall lifecycle;
- an `--install-hooks <harness>` / `--uninstall-hooks <harness>` pair only for adapters Compass must
  place in user configuration. It previews a diff and requires explicit confirmation, rejects
  symlinked or wrongly owned targets, uses compare-and-swap plus atomic replacement, preserves a
  recovery backup, marks the exact entry and removes only that entry, and detects concurrent edits;
- a self-contained stable shim outside a versioned plugin/cache path, for example under
  `COMPASS_HOME/bin`, installed atomically and retained as a silent no-op until its matching config
  entry is removed. A deleted script cannot execute code to exit 0, so manually installed hooks must
  never point only at the removable plugin copy;
- `notify_hook.py` retained at its current plugin-relative path and default URL for legacy settings
  while that plugin is installed. It cannot promise graceful behavior after the plugin itself is
  deleted. New behavior arrives behind arguments rather than breaking the legacy invocation;
- a minimum schema per destination. Antigravity forwarding retains only the quota buckets and
  lifecycle fields actually consumed, and drops account email and unrelated state before transport;
- `--diagnose` listing installed adapters with the Compass version that wrote them.

[`SECURITY.md`](../SECURITY.md) now names all three written paths: the server's two, and
`statusline_hook.py`'s deduplication memo, which its invariant 2 had always described while the
lifecycle section still said two. The shipped ingress capability needs no path, being a per-process
HMAC key held in memory, but a stable shim or an edited harness config would add one, so amend
`SECURITY.md` before installing either, rather than hiding the new paths in an installer.

### Port discovery

The forwarder must discover the port rather than assume it. `notify_hook.py` hardcodes port 4553 and
works on another port only because the skill tells the user to pass a URL by hand. A plugin-bundled
hook bakes a fixed command string into a manifest, so a user on `--port 9999` gets a hook pointed at a
port nothing is listening on, silently and forever.

The state directory can hold the answer, but the current health response is not authentication: a
process that acquires a stale recorded port can imitate its JSON and capture forwarded payloads. The
selected design must authenticate discovery before sending event data. The forwarder reads an
owner-private per-run secret, challenges the candidate with a fresh nonce, and accepts only a response
that authenticates the nonce and expected server identity. The subsequent capability is bound to the
source endpoint. An explicit URL or environment override must supply equivalent authentication; it
does not bypass the requirement.

Create state and secret material atomically. On POSIX, reject symlinked, non-owned or permissive state
homes/files. `0600` is not a Windows ACL design, so Phase 0 must choose and prove a Windows user-scoped
mechanism, such as protected secret storage or an explicitly ACLed named pipe/file. If owner privacy
cannot be established, event overlays stay disabled and the instance remains scan-only.

Discovery and delivery share one end-to-end deadline, targeted at roughly 100 to 250 ms and measured
at p95 and p99 on every supported OS. Do not spend a per-probe timeout or the current two-second HTTP
timeout on each candidate: synchronous SessionEnd hooks have tighter budgets. The shim always exits
successfully and silently when the deadline expires.

### Multiple instances and multiple users

`lifecycle` supports many instances by design, one state file and one `--status` per port, but a
synchronous hook must not probe and post sequentially to all of them. An explicit authenticated URL
targets one instance; otherwise discovery chooses one authenticated live instance deterministically.
Every other instance keeps the current scan cadence and reports `scan-only`, rather than claiming a
stale event integration or silently slowing its polling. A future authenticated local dispatcher can
fan out off the hook's critical path, but is not part of this plan.

Loopback is also not a user boundary. The local-request check reads Host, Origin and `Sec-Fetch-Site`,
none of which carry a uid, and separate ports or store roots are discovery hygiene rather than access
control. New event ingress therefore requires the per-run capability above; without it, overlays are
disabled and current polling continues. This protects event integrity only. Other local accounts can
still read `/api/data` and reach existing control surfaces under the accepted exposure in
`SECURITY.md`. Actual shared-host confidentiality would additionally require protecting `/api/data`,
`/api/stream` and `/api/shutdown`. The optional `cwd` hint never creates or renders a row, so it is not
an event-driven path-disclosure field.

## Security and privacy requirements

The refactor must preserve both invariants in [`SECURITY.md`](../SECURITY.md). The requirements
below are how this design satisfies them.

- Reuse the current Host, Origin, and fetch-site checks.
- Require an authenticated per-run, per-source capability for every new event overlay; source-specific
  routing chooses a harness but does not prove the caller.
- Reject non-loopback forwarding URLs and redirects.
- Keep strict body caps, exact lengths, read deadlines, a server-wide handler budget, per-source rate
  limits and bounded pending/replay/overlay caches.
- Assign the harness from the endpoint or installed adapter, not from the body.
- Allowlist fields and event names; discard prompts, tool arguments, tool output, credentials, and
  unrelated native payload fields.
- Deduplicate only when an adapter supplies a trustworthy source instance and key. Otherwise document
  at-least-once/out-of-order delivery, use idempotent reducers and reconcile ambiguous events.
- Always return quickly and never make a missing Compass server disrupt an agent session.
- Keep hook installation visible and consented. Where a harness has plugin hook trust, use it.
- Make ACP control access an explicit separate mode rather than silently weakening the read-only
  product promise.

The trust boundary widens with this work, and that has to be recorded rather than implied. Today a
forged `POST /api/notify` can set one harness's side state, which `SECURITY.md` carries as accepted.
General lifecycle overlays are more powerful: a forged `session_ended` can suppress a permission
alert, and a looped `turn_started` can mask a blocked session. Do not merely generalize the accepted
exposure. Require the new capability, retain the invariant that an overlay may patch only a
collector-produced row and may never create or delete one, and document that same-user malicious
processes remain inside the trust boundary because they can read user-owned secret material.

One allowlist exception is load-bearing. The rule that clears a standing needs-input hook when the
newest user record changes works
only because the payload carried `transcript_path`; without it the code falls back to a timestamp rule
its own docstring describes as compatibility for older versions. Keep `transcript_path` in the
allowlisted envelope for harnesses whose clearing rule depends on it, validated as it is today (inside
the resolved projects root, basename matching the session prefix), since it is a path the server already
resolves rather than new content, and never echo it to `/api/data`. Shape every destination to its
minimum envelope before forwarding. In particular, `/api/usage` does not need account email or the
complete status-line document merely because it needs selected quota and lifecycle fields.

## User experience

The visible benefits:

- Session transitions appear shortly after the native lifecycle event rather than up to five seconds
  later.
- More harnesses can display Needs input, for those whose native hooks expose permission waits and
  whose adapter is authenticated, contract-tested and carrying a live per-session lease.
- Long generations remain Working even when their persistent store updates only at message end, on
  harnesses with a contract-tested turn-start event and live per-session lease.
- Multiple dashboard tabs no longer cause repeated scans, up to the connection budget above.
- Native notifications still work with no browser tab open.
- Store-only and older harness versions retain today's scan cadence until a probe or persistent source
  passes the gate that permits reducing it.

Compass should disclose the quality of each source rather than make all rows look equally live. Do
not collapse configuration, mode and health into one label. Diagnostics and possibly the harness
strip expose:

- acquisition mode: `managed`, `events-plus-reconcile`, or `scan-only`;
- installation state: `not-installed`, `installed`, or `requires-trust`;
- compatibility: `compatible`, `incompatible`, or `unknown`;
- positive liveness: `connected` for a persistent source, a short `session-lease` after a command
  hook, or `unverified`. Ordinary user inactivity is not evidence that a hook is broken.

`--diagnose` should report which integrations are installed, which endpoint last received an event,
the last event timestamp, the last successful collection per harness, any adapter error without
prompt content, and counters for events accepted, events rejected by reason (unknown source, unknown
name, oversized body, failed authentication or allowlist, deduplicated event, incompatible version),
pending overlays expired, coalescing windows opened, and selective or full collections triggered. An
adapter firing ten times a second and one firing never look identical without those counters.

## Delivery sequence

### Phase 0: measure, repair prerequisites, and fix the collector

The baseline measurements must complete before architectural code lands. What was measured, and what
was not:

| Baseline measurement | Status |
|---|---|
| Cold and memo-hit collection duration | Measured. Cold 275 to 297 ms, warm 118 to 120 ms, one machine. |
| Discovery and collection duration per harness | Measured by `scripts/bench_collect.py`, one machine. |
| `cProfile` of the slowest collector by function | Measured. Claude remains the slowest; its residue is subagent globbing (140 ms cumulative under the profiler), JSONL parsing and turn scanning. |
| Files or bytes consulted | **Not measured.** No counter exists without instrumenting `io.py`, and the design asks for this only where cheaply measurable. Blocks nothing on its own, but leave the row empty rather than guessing. |
| Number of collections with one and several tabs | **Not yet measured, blocks the phase it gates.** Only meaningful once Phase 1 owns the render path. |
| Forwarder p50, p95 and p99 per OS, against a closed port, a stale listener and a live server | **Not yet measured, blocks the phase it gates.** One macOS median (56 ms, server absent) exists and is not a distribution. Depends on the authenticated discovery Phase 2 designs. |
| Native hook event count per turn per harness | **Measured for the four harnesses with captures.** Claude 38 invocations over five turns, Codex ten over one subagent turn, Gemini 56 over four turns, Antigravity 13 and 24 status-line pushes for two turns. Unmeasured for the six harnesses with no adapter. |
| Probe dependency table, mutation corpus, warm and cold probe cost and false negatives on three OSes | **Measured, with one part still outstanding.** `compass_runtime/probe.py` shipped after this row was written, and `tests/test_probe.py` runs its mutation corpus on Ubuntu, macOS and Windows through `platform-tests`, asserting cost per path rather than as a total, with one documented false negative. The reviewed per-harness dependency and fingerprint table is still unwritten. See the probe gate verdict below. |
| Event cardinality and ordering from real harness fixtures | **Not yet measured, blocks the phase it gates.** Prerequisite for assigning semantic transitions. |

Event-to-render latency and reconciliation repair counts are post-change measurements, but
missed-event rate is a rollout gate rather than a dashboard-only metric.

The collector fixes from [Make collection cheaper](#make-collection-cheaper) have landed, with the
parked-parent and nested-workflow equivalence tests, and they changed every number above. The two
quota opt-out defects are fixed as well: `--no-usage` now reaches the respawned Windows daemon, and a
pushed status-line receipt has its quota fields dropped before storage when server-side usage is off.
[`SECURITY.md`](../SECURITY.md) documents the resulting behavior, so no exposure remains open
against the published contract.

The gates are independent. Verdicts, one per gate:

- **Selective reuse: NOT DECIDABLE from the profile measured. Do not treat it as failed.** The rule
  is that if per-harness reuse saves less than 25% of post-fix collection time, keep the coordinator
  but run one full aggregate collection per floor. The saving available to reuse is the total minus
  the largest single harness, as a fraction of the total, since the dirty harness is the one whose
  cost cannot be skipped. That makes the criterion a single number:

  > Selective reuse clears the 25% bar whenever the largest harness is at most 75% of collection
  > time. It fails only when one harness dominates.

  The one machine measured is an extreme outlier and cannot answer this on its own. Its Claude store
  held 25,483 files against Codex's 349, a 71x skew, and Claude came out at 92.8% of collection time
  for a saving of 7.2%. That was a fact about one store, and it has not even held still: the same
  machine re-measured on 2026-08-06 reports Claude at 75.9% and a 24.1% saving, 17 points off the
  original, after Phase 0's optimisation and some pruning. A number that moves that far on one
  machine was never going to settle a question about every machine.

  **The extrapolation this section used to carry has been withdrawn, because it measured the wrong
  quantity.** It modelled cost as milliseconds per *store file*. A `cProfile` run over the real store
  shows where a collect's time actually goes: turn-scanning the in-window transcripts costs ~0.28 s
  against ~0.07 s of stat and glob over all 22,332 files. Files set the walk term, in-window sessions
  set the read term, and the read term is roughly four times the larger. Scaling a profile by file
  count therefore scales the smaller half.

  `scripts/bench_collect.py --simulate` replaces the model with a measurement. It generates a store
  with a named number of in-window sessions per harness, at a session shape measured from the real
  one (53 records of ~3.2 KiB, spread across 75 project directories), points the runtime's store roots
  at it, and runs the same collect. Its calibration is the reason to believe it: given this machine's
  own shape, 65 in-window Claude sessions over 11,106 older ones, it reports 257.0 ms where the
  machine itself reports 246.5 ms, 4.3% apart.

  ```
  simulated, active sessions per harness       largest              saving   verdict
  claude 40                                    claude 98.4%           1.6%   below
  claude 40 + 4 each x4   (was modelled 58%)   claude 76.8%          23.2%   below
  claude 20 + codex 20                         claude 54.8%          45.2%   clears
  claude 12 + 4 others at 12                   claude 28.3%          71.7%   clears
  ```

  Two of those rows overturn the withdrawn model. It put the 10:1 profile at a 58% saving, clearing
  the bar comfortably; measured, that profile saves 23.2% and sits below it. And it named Copilot as
  the largest harness in a balanced store; measured, Claude is still the largest even with every
  harness at the same session count. A Claude session simply costs more to read than the others'.

  So the gate is now decidable, as a function of one variable. Sweeping the ratio at 40 Claude
  sessions puts the crossover between 4 and 5 sessions for each of the four other harnesses: Claude
  is 77.6% of collection time at 4 and 72.9% at 5. **Selective reuse clears the bar once harnesses
  other than Claude supply roughly a third of active sessions, and not before.**

  History volume turns out not to enter into it. Adding 2,000 out-of-window sessions per harness to a
  balanced profile moves the largest-harness share by 0.2 points, because those files are stat'd and
  skipped rather than read. The store-file counts that the withdrawn model was built on are close to
  irrelevant to the answer.

  What this gate still needs, and what a simulation cannot supply, is what session mix real users
  actually have. That is a fact about people, not about code. It also needs a second set of hardware:
  every figure above comes from one laptop, and the simulation is silent about the four SQLite-backed
  harnesses, which have no generator. Until then Phase 1 should keep the publish protocol behind an
  interface that can serve either one full aggregate or per-harness merges, and should not hard-code
  the full-aggregate assumption that a single-machine reading would have justified.
- **Coarse probe: MEASURED, and it passes with one documented false negative.** The probe is
  `compass_runtime/probe.py`, and its corpus is `tests/test_probe.py`, which performs real
  filesystem mutations against a real temporary store rather than mocking `stat`.

  Detected: an append to a tracked transcript; an append inside one filesystem tick, which mtime
  alone misses and size catches; a new session file in a known project; a new project directory; a
  deleted tracked transcript; a rename; and a SQLite write that lands only in the write-ahead log.
  An unreadable or absent store root degrades to no signal rather than raising.

  The probe stats store roots, their immediate children, and the paths a caller names as tracked. It
  never globs, reads, or recurses. Cost is asserted per path rather than as a total, so the budget
  means the same thing on a fast laptop and a slow runner, and the test additionally asserts the
  watched set stays bounded: 60 projects holding 40 files each must not become 2,400 stats.
  Ubuntu, macOS and Windows all run it through `platform-tests`.

  **The false negative, which is deliberate.** A session that is not tracked and whose directory does
  not change is invisible: a session older than the activity window becomes active again, its
  transcript's mtime moves, and appending changed no directory. Covering it means statting every
  historical transcript, which on the machine measured in Phase 0 is about 3,600 top-level
  transcripts, or 24,898 files walking the whole store tree. Either count costs more than the
  collection the probe exists to avoid, but the two are not the same number and which one the budget
  was computed against is not written down. A test asserts the gap is still exactly that size, so
  widening the watched set cannot happen silently without re-measuring the budget.

  Reconciliation therefore stays, and this is the concrete reason rather than a general caution. WSL,
  remote, bind and network stores are still unproven and retain the current cadence.
- **Adapter semantics: MEASURED for Claude, Codex, Gemini and the Antigravity status line. NOT
  measured for the Antigravity hooks adapter.** Antigravity has two adapters at two standings. The
  status-line adapter is measured. The hooks adapter (`agy_hook.py`, shipped and registered in
  `compass/hooks.json`) rests on a static read of the guide embedded in the agy 1.1.10 binary: its
  payload keys are unconfirmed by any capture and its cardinality and ordering are unmeasured, which
  is why it maps only to `store_changed`.
  Codex's evidence is under [Codex](#codex): cardinality, ordering, per-event payload fields, a p99
  hook cost of 0.47 ms, and an identity mapping verified against the rollout the same session wrote.
  Antigravity's is under [Antigravity](#antigravity), and it corrected three field names this document
  had taken from vendor documentation. Gemini's is under
  [Gemini CLI](#gemini-cli-copilot-and-factory-droid), and it corrected something larger than a field
  name: the premise that the harness was legacy. Claude's is under
  [Claude hook distribution and semantics](#claude-hook-distribution-and-semantics-both-measured), and
  it was the last gate waived rather than cleared. Three of its ten mapped events have still not
  fired, `PermissionRequest` among them, which is recorded there rather than counted as measured.

- **Claude adapter semantics: WAIVED at the time, CLEARED afterwards by capture.** The history is
  kept because it is the more useful record. The gate asked for contract or real-CLI fixtures proving
  event meaning, cardinality and order, plus a p99 hook budget per OS. `scripts/capture_hook.py`
  existed to collect exactly that from the start. No captures were taken for a whole phase, and not
  for want of tooling: the recording hook writes a merged `settings_with_hooks.json` for review and
  deliberately never edits the real settings file, and nobody swapped it in, so
  `~/.compass/captures` stayed empty. Phase 2 shipped on a decision to accept unproven event
  semantics rather than on measurement.

  The lesson is about the route, not the diligence. The proposed route was itself unusable: isolating
  the store with `CLAUDE_CONFIG_DIR` loses the subscription login, because the credential's keychain
  account name is suffixed with `sha256(config dir)` and unsuffixed only when the variable is unset.
  A gate whose only documented method does not work is a gate that stays waived. The method that does
  work is `--plugin-dir` against a copy of the plugin with the hook commands repointed, which touches
  no settings file at all.

  What it cost while waived, stated plainly so the shape of the risk stays visible: every semantic
  mapping was a reasoned guess, a wrong one shows as a row stuck in the wrong state, and the deadline
  on the Working overlay is what bounded the damage. When the capture finally ran, the two guesses
  that mattered most were right, and the published field names were wrong on five payloads. Both
  halves of that are the argument for measuring.

  See [Claude hook distribution and semantics](#claude-hook-distribution-and-semantics-both-measured)
  for the evidence, including the three mapped events that still have not fired.
- **Operational rollout: not yet measured, blocks the phase it gates.** Retain abort thresholds for
  CPU duty, memory, handler/thread ceilings, p95 render latency and missed-event repair rate. A 25%
  collection threshold alone cannot protect the user experience. There is no render path to measure
  against until Phase 1 delivers one.

Phase 1 may proceed: its inputs from Phase 0 are the post-fix collection time and the selective-reuse
verdict, and both now exist. Phase 2's probe gate is cleared, and its adapter gate is now cleared by
capture for every harness with an adapter, Claude last.

### Phase 1: materialized snapshot and SSE

Split into 1a and 1b. Both are shipped; what each delivered is recorded below.

- **Shipped in 1a.** A versioned snapshot, revision pair, and publish protocol, in a new
  `snapshot.py` that imports no runtime module. It is owned by `RuntimeState` rather than by the
  `Application`, because the memo it replaces lived there and two applications over one state must
  share one scan; putting it per-instance broke that single-flight property outright.
- **Shipped in 1a.** `/api/data` serves the snapshot, initialized lazily on first demand, and names
  the revision it served in an `X-Compass-Revision` header so a client can hold a cursor. The
  freshness floor stays at `collect_memo_sec` rather than being retuned, so worst-case staleness for
  `curl` and the headless path is unchanged and the change is provable as a refactor. The payload was
  verified byte-identical against the pre-snapshot branch.
- **Shipped in 1b.** `GET /api/stream`, strictly same-origin rather than inheriting the
  document-navigation relaxation, with restart-qualified ids, immediate current-state delivery, a
  server-wide client budget answering 503 past the cap, a socket write timeout, one-slot mailboxes
  and heartbeats. `stream.py` imports no runtime module and `state` owns the registry.
- **Shipped in 1b.** Shutdown wakes sleeping streams. `server.shutdown()` stops the accept loop and
  never touches handler threads, so both `/api/shutdown` and `serve()`'s finally close the registry.
- **Shipped in 1b.** A demand-scoped producer that collects on an interval only while a stream is
  connected, started inside `serve()` so the daemon path creates it after the fork. Verified on a
  real daemon: 14 seconds idle with no reader and the first GET still reports revision counter 1.
- **Shipped in 1c.** The page drives itself from the stream: one `EventSource` per browser elected
  through a `localStorage` lease, followers refetching on a storage broadcast, and the fixed
  five-second poll replaced by a twenty-second safety net. A browser with no `EventSource` keeps the
  old cadence rather than freezing. Quota consent needs no lease: the page still carries `usage=1` on
  the fetch it makes per revision, and the producer publishes on every tick, so the cadence a
  consenting page sees is unchanged.
- Move time-derived fields only after the derivation-input inventory proves the tick can recompute
  them; otherwise retain the current cadence. Decouple sparkline sampling from arbitrary revisions.
  Still outstanding: no `rate_sampled_at` or equivalent fixed time bucket exists in the runtime.

This phase separates browser delivery from collection without changing harness semantics. Its success
criterion is delivery-mechanism correctness, not a user-visible latency improvement, which it does not
produce.

### Phase 2: the gated coarse probe, then Claude and Antigravity events

- Add the coarse store probe only for harnesses and filesystems that pass its independent gate;
  unproven sources keep the current scan cadence.
- **Shipped in 2a and 2b** (PRs #89, #91 and #92). Authenticated normalized ingress, envelope
  versioning, identity normalization, the pending overlay map and the bounded coordinator, in
  `events.py` and `observation.py`. The ingress capability is a per-process HMAC key held in memory
  and never written to disk. These were not subject to the selective-reuse gate; an undecided or
  failed reuse gate makes the coordinator run a full collection.
- Ship a minimal plugin-bundled lifecycle hook for Claude first, using its native trust model, and get
  the ingress to one working producer end to end before adding a second.
- Then add Antigravity's plugin-bundled `hooks.json` as model/tool/execution-loop hints, not asserted
  user-turn boundaries. It installs with the plugin Compass already ships, which makes it the
  cheapest second producer.
- Generalize notification ownership off the Claude-specific path.
- Extend `notify_hook.py` with source-aware minimal schemas behind arguments, keeping its legacy path
  and default URL while installed. Add the stable shim and authenticated one-instance discovery with
  a single end-to-end deadline.
- Route Antigravity's existing status-line receipt into dirty invalidation, and read `agent_state`
  from its minimal lifecycle envelope. No confirmation, task-count or pending-input field appeared
  in the 37 print-mode pushes, because all three are `omitempty` and that mode can raise none of the
  states they report. The interactive capture
  [`../captures/antigravity/statusline-confirmation-1.1.19-macos.jsonl`](captures/antigravity/statusline-confirmation-1.1.19-macos.jsonl)
  reached all three. Needs input still is not available from this path, for a different reason: the
  status line is a repeating render whose ordinary `working` and `idle` pushes would retire the wait,
  which needs a precedence rule in the reducer that does not exist yet. It is not available from the
  collector either: `collectors/antigravity.py` has no `needs_input` path at all.
  Keep status-line quota separately; collectors own definitive session lifecycle.
- Add deadline-driven Working-to-Idle transitions with dwell. Needs-input retirement requires
  positive evidence, not a generic dead-man timeout.
- Do **not** reduce reconciliation from a one-shot hook receipt or for a harness without positive
  liveness and proven invalidation coverage.

This is the highest-value validation milestone because the repository already distributes Compass to
Claude and Antigravity and already has push plumbing for both.

### Phase 3: Codex and Gemini, then nothing else by default

Add the Codex adapter once Claude has proven the ingress; its plugin can bundle hooks and its
app-server is a provisional managed target later. Evaluate Gemini next because Compass already ships
a Gemini extension and that extension can bundle `hooks/hooks.json`; consumer-account transition does
not erase enterprise and API-key CLI use.

Further passive adapters (OpenCode, Copilot, Factory Droid, Pi, Cursor and Goose) are deferred
indefinitely. Each needs its own justification against the proven probe baseline and a harness-specific
distribution/lifecycle assessment. OpenCode is the strongest of the six on evidence: its plugin path
is measured, and its `permission.replied` carries the joinable session id inline, so a reader needs
nothing but the event to close the request it opened. It is still not zero-action, because a plugin
file has to reach the user's machine, and the already-running TUI server that would make it
zero-action cannot yet be discovered or authenticated reliably.

Each adapter must be independently optional and independently testable. One broken integration must
never take down the aggregate, as the existing collector failure boundary already ensures.

### Phase 4: optional managed sessions

A managed ACP or native-server mode is a different product from passive cartography, and the analysis
above already establishes that. It is recorded here only so it is not mistaken for sequenced work:
prototype it, if ever, after the passive architecture is stable, with one harness, explicit connection
ownership, faithfully proxied permission requests, managed and passively observed sessions displayed
distinctly, and collectors retained for history and crash recovery. Codex app-server or OpenCode's
native server is the provisional first managed integration because each documents explicit native
state; validate that choice against an ACP adapter fixture before committing to it.

## Verification requirements

The implementation plan should include tests for:

- event capability authentication, source binding, body-size limits, exact lengths, read deadlines,
  invalid JSON, unknown sources, unknown events, per-source rate limits and server-wide handler caps;
- authenticated discovery rejecting a stale-port impersonator before sending a payload, owner and
  symlink checks on POSIX, and the selected Windows user-private mechanism;
- an out-of-range envelope `v`;
- field allowlisting and prompt/tool-output redaction, with `transcript_path` retained and never
  echoed, and Antigravity email/unrelated fields removed before forwarding;
- native ids that must be normalized to a collector `sid`, ambiguous ids, a first-session event before
  store flush, an event during the first collection, pending attachment, expiry, and capacity rejection;
- trustworthy source-instance/sequence deduplication, sources with no sequence, reordered and repeated
  events, a source restart, idempotent reduction and conservative reconciliation;
- an implausible or skewed event timestamp;
- event-burst coalescing, arrival-order overlay application, and the per-harness collection floor;
- an overlay and a non-semantic dirty event arriving mid-collection, fenced by `arrival_seq` and dirty
  generation rather than wall time;
- one collection lane across dirty refresh, reconciliation, direct GET and `?all=1`, proving an older
  slow result cannot overwrite a newer one;
- per-harness selective collection and unchanged-harness reuse, with retained results proven
  immutable, plus the failed-reuse-gate full-collection path;
- one collector failing while other cached harnesses remain available;
- the Claude membership cache appending an existing parked-parent child and creating a nested workflow
  child without touching ancestor directory mtimes;
- every coarse-probe mutation and filesystem case in its Phase 0 corpus;
- Working-to-Idle transitions without a new event, dwell, Working-overlay expiry, and a long-lived
  Needs-input overlay that is not cleared by time alone;
- `session_ended` followed immediately by `turn_started` for one session;
- `PreCompact`/`PostCompact`, append-only and rewrite fixtures, and compaction with a missed event, all
  reconciled without counting as activity;
- provenance-specific precedence: a Claude `Notification` stays subordinate to fresh activity while
  an explicit permission request retains its contracted fields;
- Needs input and its notification on a non-Claude harness;
- lazy first-demand reconstruction, no filesystem work for an idle no-event daemon, a critical event
  before first browser demand, and missed-event reconciliation;
- `/api/data` direct-GET freshness at today's age with no tab or stream, the connected five-second
  producer, and independent slow reconciliation;
- every time-derived field's retained inputs or measured recollection, and fixed-bucket sparkline
  sampling during an event burst;
- the complete revision pair on initial SSE connect, reconnect, leader handoff and server restart,
  including reset behavior and `Last-Event-ID` from the previous process;
- SSE keepalive, multiple tabs, leader failure/handoff, exactly one browser notification, common
  HTTP/1.x connection pressure, a stalled reader, queue collapse and stream/global caps;
- SSE clients and all observation workers disconnecting during shutdown;
- manual `/api/data`, `?all=1` polling and overlay compatibility;
- Windows `--no-usage` respawn, unconsented `/api/usage` discard, multi-tab consent broadcast and
  revocation, leader handoff, five quiet minutes reaching quota due, fetch completion publication,
  and consent expiry with no page;
- hook forwarding with no server, a wrong port, an authenticated discovered port, an impersonator,
  an unresponsive listener, deleted plugin runtime files with a surviving stable shim, one selected
  instance plus a scan-only second instance, the total hook deadline, and every supported OS;
- an event posted by a different OS user;
- hooks never returning an error that disturbs the reporting harness;
- bounded state under a long-running event stream;
- no worker starting in either daemon parent, exactly one service set in the foreground/final child,
  and deterministic shutdown order;
- `--no-events` disabling event ingress only, independent probe/stream gates, and
  `--legacy-polling` restoring today's memoized `/api/data` plus browser-poll path;
- direct launch on the documented Python floor with no third-party package.

## Feasibility assessment

| Outcome | Feasibility | Reason |
|---|---|---|
| Cheaper Claude collector at identical output | Done | All three fixes shipped in Phase 0 at 263 ms to about 100 ms warm; the membership cache passes the parked-parent and nested-workflow fixtures |
| Coarse stat-poll invalidation across all ten harnesses | Gate cleared | The mutation corpus passes on Ubuntu, macOS and Windows with one documented false negative, an untracked session whose directory does not change. WSL, remote, bind and network stores remain unproven and keep the current cadence |
| Materialized snapshot with SSE delivery | Medium to high | Fits the runtime, but needs a real coordinator, demand producer, restart cursor, server-wide resource limits and shutdown lifecycle |
| Event-triggered selective collection | Value depends on the session mix | Below the 25% gate on a Claude-dominated machine and well clear of it once other harnesses supply about a third of active sessions, measured with `bench_collect.py --simulate`. The coordinator runs one full aggregate per floor until real multi-harness mixes are known |
| Near-real-time Claude and Codex | Medium to high | Both plugin formats can bundle hooks; Compass still needs authenticated routing, fixtures and its own lifecycle wiring |
| Near-real-time Antigravity | Medium to high | Hooks are bundleable and the status line adds agent state; the confirmation field does arrive interactively, but it is a repeating render rather than a transition edge, hooks are not clean turn boundaries, and the status line is opt-in |
| Near-real-time Gemini | Medium | The shipped extension can bundle hooks, but supported auth populations and event semantics need fixtures |
| Near-real-time coverage across all ten harnesses | Low to medium | Several adapters and passive topologies remain unproven; Compass lacks artifacts for six even where upstream lifecycle support exists |
| Zero polling for every arbitrary external session | Not presently feasible | No universal observer protocol; events can be missed and time-derived state still needs deadlines |
| ACP-backed sessions launched by Compass | Technically feasible | Standard event model, broad nominal harness support |
| ACP as a transparent universal replacement for collectors | Not feasible | Connection-scoped lifecycle and incomplete passive/global semantics |
| Native filesystem-event watcher | Poor fit | Three platform backends or a dependency, for precision the product does not need |

The likely experience is near-real-time rather than literally instantaneous, and the estimate below is
unmeasured. A matched semantic overlay can publish before the collection floor; a store-only event may
wait for that floor and store flush. A native hook, bounded loopback POST, short coalescing window,
collection, snapshot publication and SSE delivery should normally beat the current five-second
interval, but p95/p99 hook cost, store timing and harness behavior must be measured before setting any
public latency promise.

## Decisions to carry forward

- Do not rewrite the runtime merely to remove Python; the cost is one collector's algorithm, not the
  interpreter.
- Do fix that collector before changing any scheduling, since it changes every number in the argument.
  Done: Phase 0 landed the three fixes, and the numbers in the argument are the post-fix ones.
- Do not remove the existing collectors; they are the cross-harness historical and recovery layer.
- Do not adopt ACP as the core passive observation mechanism, and never require ACP for the ordinary
  dashboard.
- Do add a materialized snapshot, a revision pair that distinguishes restart, and SSE delivery. This is the
  highest-value change here and needs no events, no adapters and no envelope.
- Do use the coarse probe for latency only after per-harness mutation and cross-platform gates prove
  its coverage; keep current scans for every unproven source.
- Do add hooks for the needs-input semantics an mtime genuinely cannot express, starting with a
  harness for which Compass already ships a plugin artifact.
- Do use plugin-bundled hooks where Compass ships through the harness's plugin system, and treat
  every other adapter according to a harness-specific distribution and removal assessment.
- Do version the event envelope; it is a public compatibility surface the moment a third-party harness
  executes a Compass hook.
- Do serialize collections through one coordinator, fence them with `arrival_seq` and dirty
  generations, and set overlay precedence per field and provenance rather than timestamp recency.
- Do normalize native session ids onto collector `sid`s, quarantine unmatched overlays without
  rendering them, and never let an overlay create or delete a row.
- Do treat native filesystem watchers and OTel as optional inputs, not foundations.
- Do retain full first-demand reconstruction and periodic reconciliation, and keep the current cadence
  for any harness without positive liveness and proven invalidation coverage.
- Do schedule time-derived state transitions only after retaining the inputs they need, and keep
  sparkline samples on a fixed cadence independent of event revisions.
- Do keep quota consent browser-originated, synchronized across tabs and separate from session
  refresh; no server timer may initiate a vendor fetch without a consenting request.
- Do make event health, acquisition quality, and ingress rejection counters visible in diagnostics.
- Do define `--no-events` accurately as disabling event ingress, keep independent stream/probe gates,
  and ship `--legacy-polling` for a real operational rollback to today's delivery path.
- Do require authenticated discovery and a per-run event capability; record the remaining shared-host
  read exposure and every new written path in `SECURITY.md`.
- Do install user-configured hooks through a stable shim outside removable plugin paths, with exact
  config ownership and uninstall semantics.
- Do start observation workers only after daemonization and join them deterministically.
- Do keep managed ACP and native-server sessions as a distinct future product mode.
