# Dashboard reference

Return to [start, status and stop](../SKILL.md#start).

`<skill-dir>` is the directory holding `SKILL.md`, one level above this file's `reference/` directory; see [Start in SKILL.md](../SKILL.md#start).

## About Compass

Use Intent and drift to compare a session's recorded work with your goal. Open a session, set a
goal and press `Analyze drift`. The Goal card's `How goals work` disclosure explains the steps, the
reading's limits and what a goal with no expected outcome line is read against.
New to it? `See a sample session (view only)`, above the Sessions list, opens an anonymized session
that drifted, with a stored summary of what it did, its stored reading, the correction Compass
composed and numbered (i) marks that explain each part. It is static page data: nothing in it is saved, sent or run.

Compass is an agnostic agent cartography and visualization tool: a local web dashboard mapping live coding-agent activity across **ten harnesses** on this machine — Claude Code, Codex, Pi, Gemini CLI, Antigravity CLI, GitHub Copilot CLI, OpenCode, Cursor CLI, Goose, Factory Droid — each row badged with its harness. A "Discovered harnesses" strip at the top shows all supported harnesses; ones with local session data are green/enabled, others gray/disabled. A harness's sessions only appear if its data is discovered. Transcript-backed sessions appear even if they never called TaskCreate; Claude task files may also surface a task-only session when its transcript is unavailable. Per session: observed state, what it's doing right now, running subagents (named pills), a current-turn elapsed/ETA estimate with progress bar, a ⚠️ warning (with tooltip) when a request runs or is estimated ≥15 min, one row per tracked task, and the recent token output rate. Fires desktop notifications when a session is blocked waiting on the human — Claude, Codex, Copilot, Cursor, OpenCode and Pi can report waits, within their stated coverage — and when any session registers a question through the ask lane. Sessions, Projects and Needs you render the same data three ways — see Dashboard views below.

Store locations are resolved per platform, and the documented relocation variables are honored: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME` (the CLI creates `.gemini` inside it; relocates the Antigravity store with it), `COPILOT_HOME`, `PI_CODING_AGENT_DIR`, and `PI_CODING_AGENT_SESSION_DIR`. When one is set it is authoritative — no fallback to the default location. Run `--diagnose` to see every path searched.

Data sources (read-only; a reader-started model call can send session content through an installed Claude Code or Codex CLI. Analyze drift runs on your press, Codex goal summaries on `Summarize this session` in Console, and a Claude Code session summary when you open a finished session, press `Summarize` or `Update summary`, or invoke a spending `summary` action; each tells you once what is sent and where, again if the destination or content tier changes. Pause all AI use or `--no-observer-model` stops them, and `Turn off summaries` stops session summaries alone. The Live monitor, with its switch on, adds a Claude Code call to Haiku about once a minute while you view a session or a terminal holder keeps it on, tells you once what it sends, and stops under the same two. Unasked drift checks remain a separate opt-in. All parsing is defensive — a broken harness store is skipped, never fatal):
- `~/.claude/projects/*/<session>.jsonl` — Claude transcript tails: session discovery (a file holding only generated-title, agent-name or PR-link records is not a session), titles, token usage, pending AskUserQuestion detection and the text of the question it is asking
- Claude subagents, two generations: modern harnesses write each subagent as a top-level `~/.claude/projects/*/<uuid>.jsonl` whose records carry `agentName` + `teamName: "session-<parent prefix>"` — these fold into the parent session (named pill, its own start and elapsed, freshness, output rate) and never appear as standalone sessions. A teammate dispatched into its own pane stays on that row once it goes quiet, marked as no longer running rather than dropped, and its own subagents are walked and listed beside it, each attributed to the teammate that spawned it; legacy `<session-uuid>/subagents/agent-*.jsonl` + `.meta.json` files are still recognized (fresh mtime = running, and one the lead ran itself stays listed as no longer running once quiet, on the same display window as a teammate), including the `subagents/workflows/<run-id>/` directory a workflow fan-out nests its agents in. A bare `agentName` from a top-level `--agent` launch has no parent relation and remains a standalone session; `agentSetting`, not `agentName`, supplies any Spacedock role. Agent writes count as parent activity in their own right, so a session parked on a long background workflow reads Working
- Spacedock workflows: a Claude session launched by Spacedock carries an `agentSetting` of `spacedock:first-officer` or `spacedock:ensign` in its first transcript records, which is how its role badge appears. Pi and Codex write no such setting, so a supported boot result earns a first-officer badge instead, and never an ensign one. Codex also accepts the captured fulfilled-result wrapper only when its integer exit code is zero and its output is one complete boot JSON object. A first officer also records its `spacedock status --boot` output — counted only when it arrives as command output, never as ordinary conversation text — which names each workflow directory and each entity-state directory absolutely. The ordered stage list comes from the workflow `README.md` frontmatter, and each entity's current stage from the `status` in its own state-file frontmatter; boot's `dispatchable` list is only a snapshot of what was ready to move at boot, so it fills in behind the state directory rather than standing in for it. Those two kinds of frontmatter are the only project files the stage-strip reader reads; the cockpit's separate project-context prototype also reads bounded dispatch and workflow evidence — see the repository's SECURITY.md for the contract, and `--no-spacedock` to disable it
- `~/.claude/teams/session-<id>/config.json` — the Claude teams registry: the roster of members a lead session has dispatched. A member is listed here the moment it is spawned, which is before it has written a transcript byte, so a member on the roster with no transcript anywhere is one that has not started — the shape an agent parked on a startup permission prompt takes on disk — and the session reports Needs input and names it. The roster is a roster and not a heartbeat: one file stamp covers every member and moves only on a join or a leave, so a member is read this way only once it has been registered longer than a healthy agent takes to start and only while the session is still inside the display window; running subagents keep their own transcript freshness. Older harnesses pruned a member as it finished; Claude Code 2.1.259 keeps it and marks it `isActive: false` instead, so what stops finished work from reading as running is transcript freshness, and that flag is only ever allowed to confirm a member has stopped, never to claim one is still going. A session directory with no `config.json` (an older layout) is skipped rather than treated as broken. A gate that opens mid-run is not detected: nothing in the store distinguishes a blocked member from a busy one once it has started
- `~/.claude/tasks/<session-id>/N.json` — tracked task state (subject, status, activeForm); current bare-UUID and older `session-<id>` directories are supported
- `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` — Codex. The newest instruction, the title and the agent's turn-start statement of intent come from a walk backward from the end of the file rather than from its tail, because Codex pads a rollout with large encrypted reasoning blobs and the prompt is usually well outside any bounded tail read. Line 1 (`session_meta`) gives identity + cwd; `thread_source: "subagent"` files are subagent threads (named by `agent_nickname`), grouped through `source.subagent.thread_spawn.parent_thread_id`; resumes dedupe to newest file per session. Codex's own plan is read from the newest `update_plan` record and becomes that session's task rows — the same backward walk and for the same reason, since a session that has done any work since writing its plan has pushed it out of tail range. Two wire shapes are read, because a given Codex build writes one or the other: an older tool call whose arguments are JSON, and the current one that carries the plan as JavaScript source. The walk does not stop at a compaction boundary the way the prompt walk does, since the CLI keeps showing the plan across one. A step carries no timestamps of its own, so a Codex session gets task rows and a progress count but no age per row and no "est. remaining"
- `~/.pi/agent/sessions/--<encoded-cwd>--/<timestamp>_<uuid>.jsonl` — Pi v3. The default store is nested; a custom session store is flat and contains JSONL files directly. The last persisted leaf's ancestor path is active, so sibling branches are excluded from prompts, tools, output usage, and turns. The latest global `session_info` name is the title, including a later clear; `parentSession` means fork or clone, never a subagent. Assistant, tool-result, compaction, and branch-summary output usage feed the rate. Pi has no allowance of its own, so each row also names the authority it is spending, read from the newest entry on the active branch that carries one (an assistant message, or a `model_change` the user has switched to but not spent yet): it renders as `via Codex · gpt-5.6-sol`, and a provider with no harness of its own keeps its own name. A session that names no provider makes no claim rather than guessing from Pi's current default. Pi has no passive needs-input or core-subagent signal. Its Working or Quiet reading comes off the active-branch leaf record's `stopReason` rather than recency alone, and it is the only harness whose store records how a turn ended: an assistant leaf stamped `toolUse` is a tool call whose result has not been written, so it reads Working — `running <tool>` — past the 90s window and up to 15 minutes, because recency cannot tell a long `bash` from a parked session; past that it publishes idle activity, because a transcript can record that a tool started and can never record that the process died, so a Pi hard-killed mid-tool would otherwise hold the top of the board for the whole display window. A finished turn (`stop`, `aborted` or `error`) publishes idle activity the second it lands however fresh it is. A `user` or `toolResult` leaf has handed the turn back to the model and reads `thinking` while fresh. An unrecognised `stopReason` claims nothing and stays on recency. None of this distinguishes a finished turn from an unanswered wait, which still needs a turn-end event reaching the board: Pi documents `turn_end` and `agent_settled`, the second one for status integrations by name, but both are handed to an in-process extension handler and Compass ships no Pi adapter to receive one. It does get a Spacedock first-officer badge and stage strips: with no `agentSetting` to read, a Pi session is taken to be a first officer when its transcript carries a `spacedock status --boot` envelope, written as a `toolResult` message. There is no Pi ensign role, and a Pi strip never bolds an entity, because Pi reports no workers to attribute one to.
- `~/.gemini/tmp/<project>/chats/session-*.jsonl` — Gemini CLI main sessions. Gemini CLI stopped serving consumer accounts in June 2026 and Antigravity CLI succeeds it there, but enterprise Code Assist and API-key use still write this store, so it is historical on a consumer machine — sessions read as idle and need `?all=1` to show — and live on an enterprise or API-key one (line 1: `sessionId`/`kind`/`directories`); `chats/<parentSessionId>/*.jsonl` are subagent recordings (linked by directory name). Flat messages and resumed-session `$set.messages` snapshots support `type: user|gemini` and per-message `tokens.output`. Legacy single-`.json` chat files are not parsed
- `~/.gemini/antigravity-cli/conversations/<session-id>.db` + `cache/last_conversations.json` + `log/cli-*.log` — Antigravity CLI (`agy`) sessions. Per-conversation DB/WAL activity provides discovery and working/idle state; trajectory-metadata protobuf fields fold fresh subagents at every nesting depth into the root card with role/type labels, and descendant activity and output usage feed the root state and token rate; stable step-metadata fields provide prompt boundaries and tool action/summary; the cache supplies the primary workspace, with CLI logs as its fallback and as the latest-prompt source; when a log carries no prompt, the newest typed direction in the conversation's `brain/<session-id>/.system_generated/logs/transcript.jsonl` is the title, and those directions alone, never the agent's work, are what a reading of an Antigravity session reads against. Conversation content is not decoded
- `~/.copilot/session-state/<uuid>/events.jsonl` (+ legacy `history-session-state/`) — Copilot CLI typed events: `user.message`, `session.start` (`data.context.cwd`), `tool.execution_start`, `subagent.started/completed/failed`, `session.task_complete`, `permission.requested/completed`. The permission pair joins on `data.requestId` and is what makes a Copilot row report Needs input; only the kind of prompt is read from it, never the command or the URL. A subagent's model comes off the same `subagent.started` object its name does, so the two are paired without a join, and all three subagent events are keyed on the `agentId` they share. Event `data` field names are de-facto, parsed defensively
- `~/.local/share/opencode/opencode*.db` (SQLite, read-only) — OpenCode: `session` table (`parent_id` links subagent/child sessions, `directory`, `title`, `time_updated` in epoch ms; archived sessions filtered), plus `message` joined to `part` for turns and prompts. `message` has no `type` column — the role is inside `message.data` — and the prompt text is inside `part.data`, on the parts a message typed `text`, so an attached filename never publishes as the prompt someone typed. Measured on 1.18.20: `session_message` exists, is what an earlier reading went to, and no build measured writes a row into it. The model is the `id` inside `session.model`, a JSON object OpenCode writes on the session row; the column is optional there, so a row carrying none falls back to the newest assistant message's own `modelID`, and a child session's model is read from its own row rather than inherited. Busy/idle is not persisted — inferred from `time_updated` freshness
- `~/.cursor/chats/*/<agent-id>/store.db` (SQLite, read-only) + the sibling `meta.json` — Cursor CLI: the `meta` table holds hex-encoded JSON (session name, `latestRootBlobId`, and `subagentInfo` on a child), and the sibling file holds `cwd`. Minimal support: discovery + working/idle via db/WAL mtime + title + project + the model of the newest message + subagents + a standing permission gate; no turn ETA (content is hex blobs). The gate is `pendingToolExecutionContracts` on the newest blob by `rowid` — non-empty means somebody is being asked, and `pendingToolCallStartedAtMs` beside it is when they started waiting. Newest by `rowid` and not simply anywhere, because the store is append-only and content-addressed: the blob that stood at the gate is still there long after the answer, and `rowid` is the only order the schema keeps. The key is matched on bytes, since the carrier is a length-prefixed binary frame rather than JSON, and the wait is published only while the row is fresh — an abandoned session stays pending in the file forever, so without that the board would carry a red row and a notification for a session nobody is in. A reading is also dropped when its stamp is too old to have been written by the store's own last write, since a real gate is what froze that file: that is what keeps a stamp belonging to some neighbouring record, or a message that merely quotes the field, from turning a row red with a wait nobody believes. The model is `providerOptions.cursor.modelName`, found by following the chat's root blob to the message blobs it lists and reading a bounded slice of the newest few. Cursor writes its own codename there and it is published verbatim, since mapping it to a marketing name is a guess that would silently mislabel the next codename. Blobs are plaintext on every store measured, but the store carries an encryption key it is never asked for: where the bytes do not read, the session reports no model. The workspace is `cwd` in the `meta.json` beside the store — no spelling of it appears in the `meta` payload at all — so the key spellings that payload was read for stay on as a fallback beneath it. Either source is accepted, bare path or `file://`, only when it resolves to a directory that exists, since a wrong key would label the row confidently and wrongly; when neither does, the row reads `cursor`, and a store with no `meta.json` (a subagent's has none) is a session without a workspace rather than a broken store. A subagent keeps its own store under the same workspace hash and names its agent in `subagentInfo.rootParentAgentId` — another store's directory name, which is exactly the session id another row carries — so children fold onto that row as pills labelled by `typeName` (their own name is the generic `New Agent`), each with the model read from its own store; a child whose named agent is not among the rows stays a row of its own rather than disappearing
- `~/.local/share/goose/sessions/sessions.db` (SQLite, read-only) — Goose v1.10.0+: `sessions` (`working_dir`, `updated_at` UTC, `session_type='subagent'` + `parent_session_id`; archived + infrastructure types `hidden/terminal/gateway/acp` filtered), `messages` (role, `created_timestamp`) for turns/prompts, `usage_ledger` for the token rate (`messages.tokens` is never written by goose). Per-session activity = `updated_at` column, not file mtime (shared DB) — a long single-message generation can briefly read Quiet since `updated_at` only bumps on message insert. Legacy per-session `.jsonl` and the `GOOSE_PATH_ROOT` override are not supported
- `~/.factory/sessions/<slugified-cwd>/<session-id>.jsonl` — Factory Droid 0.202.0 (the older `~/.factory/projects/<project>/<session-id>.jsonl` root is still searched): line 1 `session_start` (`id`, `sessionTitle`, `cwd`); messages are Anthropic-style blocks (`role`, `content[]`, `timestamp`). The sibling `<session-id>.settings.json` is not read

Pi relocation: `PI_CODING_AGENT_SESSION_DIR` is an authoritative direct session-store override and takes precedence over `PI_CODING_AGENT_DIR`, Pi's global `sessionDir` setting, and the default. `PI_CODING_AGENT_DIR` relocates the configuration root; a relative global `sessionDir` resolves below it. A one-off Pi `--session-dir` and a project-local `.pi/settings.json` are not discoverable from this separate process. Set `PI_CODING_AGENT_SESSION_DIR` to the effective directory in either case.

## Session states

Sessions rows show the observed state in a named icon tile beside the title. The progress
slot is blank. Open the session page to see the progress reading and any live estimate
the session supports.

The Sessions legend pairs Working with a pulse, Waiting on you with a clock, Quiet with a moon
and Ended with a checkmark. The warning triangle means Worth a look. A wait on a child, an
unpublished state or a scan without a turn stop is explained in a secondary text line.

| State | Meaning | Derived from |
|---|---|---|
| **Waiting on you** | An agent is blocked on the human | Best effort, never guaranteed, and six harnesses can report it at all. **Claude** has four sources that cover different things rather than ranking cleanly: the bundled `PermissionRequest` hook is the main one for tool gates, seen directly for `ExitPlanMode` and in the wild for `AskUserQuestion`; an actionable Notification-hook POST is the *only* source for an MCP elicitation or a worker's permission or network request; and a pending input tool seen in the transcript is an opportunistic extra, because Claude Code flushes that record on its own schedule and sometimes not until the gate has been answered; the fourth is about a subagent rather than the session, and is a member on the teams roster that was dispatched and never wrote a transcript, described on the teams-registry bullet above. **Codex** has one, its own bundled `PermissionRequest` hook, measured firing interactively with the prompt still on screen. A Codex row says a gate is open and cannot say which, because the event envelope drops the tool name at the hook; it raises a popup on the same terms a Claude one does. **Copilot** has one too, and it is the only one that needs nothing installed: the CLI writes `permission.requested` to its own `events.jsonl` when the dialog opens and `permission.completed` only once the human answers, so the collector reads a request with no answer behind it as a standing gate. A Copilot row says whether a command or a URL is being asked about, and never which command or which URL. **Cursor** takes the same route on a different store: a standing tool-call gate leaves `pendingToolExecutionContracts` non-empty on the newest blob of the chat's SQLite store, and answering it — either way — appends a blob with the map emptied. Its store closes nothing on its own, so the wait is published only while the row is fresh enough to be trusted; the reason is on the Cursor store bullet above. A Cursor row says a permission request is open and how long it has stood, and nothing about what was asked. **OpenCode** reports parent permission waits through its per-project passive plugin. **Pi** reports extension UI prompts in persisted sessions through its adapter on 0.85.1; startup trust is excluded. Both require events enabled and lose standing observations on restart. The other four harnesses have no gate detection; Needs you reports that coverage gap so a quiet row cannot be read as an all-clear |
| **Working** | Actively generating | transcript/subagent/DB activity within the last 90s; detail = in-progress task's activeForm, else running subagents, else `thinking` where the harness can see the model holding the turn with no tool call open, else last tool, else `generating…`. Claude also keeps an unanswered non-input call in the current step Working as `running <tool>` for at most 900 seconds from that call. A foreground builder still running after 15 minutes falls back to the usual activity window. Only the newest assistant message id qualifies; parallel calls sharing it may remain pending independently. A later assistant message, a human prompt, compaction, a validated Stop or an interruption ends this foreground wait. Injected task notifications, system reminders and hook feedback do not end it. Codex also keeps a shell-capable call (`exec`, `exec_command`, `shell_command` or `write_stdin`) Working as `running <tool>` for up to 900 seconds from the call while its turn is open. The bounded rollout tail must contain the call and no matching output; parallel calls retire independently. The tool name is shown without inferring shell commands from JavaScript. Once its output arrives or the call expires, Codex uses the plan step, running subagents or `generating…` instead of the last tool name. A killed process with no recorded end can read Working until the cap; a still-running process past the cap falls back to the usual activity rules. A new turn, a genuine user message, a recorded finish or an interruption clears pending calls. Injected context and subagent notifications preserve them. Custom `exec` needs nonblank JavaScript input; direct function calls need JSON-object arguments with a nonblank `cmd` or `command`, or an integer `session_id` for `write_stdin`. An observed session end or a remembered Stop that still stands makes the row idle and inactive, even with a pending call. In headless sessions only, outstanding background Agent/Task subagents and explicit Bash calls with `run_in_background: true` acknowledged by a parent-owned tool result in the current turn read `waiting on 1 background task` or `waiting on N background tasks`, for at most 900 seconds from the newest qualifying outstanding launch. These background tasks can make the parent's Stop yield; a later interruption or new user prompt retires their wait. A recorded task completion ends its wait. Ordinary shell `&` jobs and calls automatically moved to the background do not qualify. Interactive sessions and sessions whose entrypoint is unknown keep the usual background activity and Stop rules. Each cap is independent, an input request still wins, and an observed session end ends both waits. A session killed mid-tool without an observed end (SIGKILL) can read Working until the 900-second cap instead of the usual 90-second activity window; this is an accepted limit. Every other measured ending sent SessionEnd. Pi also has exceptions to recency in both directions; see its store bullet above |
| **Quiet** | An observed turn stop | An idle session with a turn stop published by the harness can show Quiet. Without a stop, the board shows State not published. A scan-only row without turn-end evidence says `Read by scanning: no turn end can be observed here`. |
| **Ended** | A reported session end | The session published an end timestamp. A turn stop can leave a resumable session open. |

## Launcher declarations

A launcher can set `COMPASS_PARENT_SESSION=HARNESS:SESSION_ID` on a child before its SessionStart
hook runs. The hook accepts `claude`, `codex`, `gemini` or `droid`, with a full UUID or, for
Claude, the published eight-character key. No parent is inferred. `/api/data` publishes
`declared_parent: {harness, sid}` with the matched parent's published identity and
`declared_parent_state: "linked"`. Without a declaration both are null. An unmatched parent,
self-link or cycle member has a null parent and state `"not_linked"`.

A linked working child can keep an otherwise idle, non-ended parent Working, without overriding
an input wait. `waiting_on_child: {harness, sid}` names the most recently active eligible child;
ascending harness and sid break ties. It is null when no hold applies. Idle, finished or ended
children cannot hold a parent. Each hold lasts at most the child's activity plus the existing
900-second tool-in-flight ceiling; chained links do not renew it. A resume without the variable
preserves the claim. Received declarations persist across restarts in a private, locked store,
up to 512 claims and 256 KiB. Once row visibility is known, absent claims expire after the activity
window without an event; loading preserves their original timestamps and renews no working hold.
A failed write is diagnosed and may leave only an in-memory claim for this run. Unreadable,
corrupt or unsafe storage is refused. `--forget` removes claims but keeps user-authored groups;
`--no-events` neither loads nor saves claims. Events never received cannot be recovered, including
claims lost before upgrading from memory-only storage. Codex noninteractive runs can silently
skip untrusted hooks, so their SessionStart must be trusted before launch.

UUID hex matching ignores case, keeps the matched row's published identity, and refuses ambiguous
matches. A full Claude UUID must match the full resume identity when the row has one. A held
parent also publishes `declared_native_state: {state, active, state_detail}`, its actual pre-hold
values, or null without a hold. Reading, context, Live and drift consumers restore that snapshot
before deriving their inputs; it grants no source access.

`--set-group LABEL --session HARNESS:SESSION_ID` saves a local display label, at most 40
characters, using `/api/annotate` and the goal-save admission guards. Empty LABEL clears it. The row's
`group` is the effective string or null; `group_source` is `"set"`, `"parent"` for inheritance
from a linked labelled ancestor, or null. Own labels win. `--no-annotations` reads no labels and
refuses saves, so there are no labels to inherit. Labels and parent metadata never enter history
or model input. Goals and drift readings remain each session's own.

## Dashboard views

The light dashboard opens on **Sessions** with a greeting and a summary of the board. The
**At a glance** cards count Waiting on you, Working now and Worth a look. Waiting on you and
Worth a look open **Needs you**. Working now selects Working and takes you to the list.
Press it again to clear that selection. The summary says when it covers only sources Compass
could read. Below the cards, Right now comes before the earlier group. The six status tabs count the whole loaded board.
Search reads titles, goals and prompts. Press `/` to jump to it or paste a session id to find it.
Filters opens a panel for Project, Agent, Started and Progress check. The level chips are disabled.
No goal yet uses published goal evidence across agents and includes unsaved prompt drafts.
Filters explains when some sessions have unpublished goal data. More filters for power users holds
the full project list, date ranges,
Group, Headless, State, Progress records and Goal source.
Headless offers Headless and Interactive or unknown. The latter includes
interactive Claude Code and Codex runs, unknown entrypoints and other harnesses. Codex classifies
only rollout source `exec` as headless and `cli` as interactive. A quiet headless Codex row with a
standing recorded turn stop says "run finished" with its age on the list and session page. New work
withdraws that reading; it does not declare a session end. Neither
option is selected by default, so all sessions show. At a glance keeps counting the whole board.
When the filters hide a waiting session, the list can link to it or to Needs you.
Show everything resets a search with no matches. If every discovered source fails, search results
and session counts are unavailable. Show older sessions widens the collection with
a reload, which clears the filters. Choices and the open panel last across refreshes and trips
into a session and back for the life of the tab. **Projects**, one
click away, groups sessions by the label their harness publishes. **Goal history** lists every
current board session and retained annotation/discard record once, including sessions without a
project or a goal. It labels the typed goal and each expected outcome line, cached deterministic goal, and each
published workflow goal separately. A missing workflow title supplies no goal. Saved deterministic
evidence is bounded and scrubbed; every line says its currentness has not been checked and gives
its observation time or says that time is unknown. Opening the log never derives a new goal.

Annotation off/loading/error withholds typed evidence while board sessions and other sources stay
visible. Retained words, revisions and readings remain reachable after the session leaves the
board. Discard removes your saved words, typed or adopted, readings and the session's summary without removing independently labeled sources.
An open log invalidates withdrawn words before loading their replacement, including a discard
made in another tab. The annotation store keeps at most 256 records and sixteen revisions each;
discard records are evicted before retained words, then oldest first. These limits do not apply
to board-only rows. A present session without a project links to its own page, which has no
project to return to.
Each project opens its cockpit:
a left **Scope** rail selects the project or one exact session. Each row leads with the session
title, with its harness, state and age as a caption beneath; a row whose title was never published says
so in place of the title rather than falling back to an id. Where two sessions of one harness would
otherwise render identically, the row carries the session key so you are not picking blind. A
persistent briefing shows
**Where this project stands**, with **Current task**, **Running now**, **Needs you** and
**Latest result**. **Latest instruction** selects by instruction time, with its source and the
reason when no instruction is available. Without instruction times, the card says
**Published instruction**. **Your saved words** labels saved words and expected outcome rows. Needs you keeps a project session
waiting on you visible above the tabs, with raise and copy-resume controls where supported.

**Now** pairs current activity with observed session endings, their outcome glyphs and git readings,
plus workflow evidence. **Course** holds observed state changes, semantic history, and completed
tasks. **Decisions** shows recorded decisions and their application state; it does not approve
them. **Console** leads with the operations rail, Delegation, Waiting on you, Capacity and
Tripwires, and keeps how the server was started in one disclosure beneath it, holding the selected
session's optional read-only terminal, the observer-model controls and the status line. The summary
names the state of both capabilities. A capability that is on renders expanded and outside the
disclosure, so nothing you can act on is behind a click. What you typed for a session, and
everything read against it, lives on that session's own page (below), not on a tab here.
The **Your note (this tab only)** box, browser-local human context and old
tripwire notes do not instruct an agent and remain inert. The first-officer gloss appears with a
first-officer session or enabled stage source; stage alerts require an enabled stage source.

Each tab names its own panel in a line beneath the strip, because two of the four open onto a
heading that does not repeat the label. Course and Decisions also carry a cue on the tab
itself: the number of observed state changes or decisions. A cue reads `…` while
the record is still loading and `·` where nothing published the figure, and those two are never the
same claim as a zero. Every cue is spelled out for a screen reader beside its mark.

The composer for a note to yourself sits in the project header, above the tabs, rather than inside
Tripwires. It is the same control wherever you reach it, and it still writes nothing into a session.

Stage alerts are separate typed controls in Course and Projects. Save one declared
stage per exact workflow; the first current entity observed entering it trips the condition once.
First sight, restart and evidence gaps establish a baseline rather than an entry. The card reports
the current coverage and unavailable sources. Rearm permits another alert; saving the unchanged
stage preserves its latch. Projects retains Remove when no source session remains. Up to 64 rules
are saved without eviction, and `--diagnose` reports their store path and any read failure. No rule
writes into an agent. Notification outcomes report service acceptance or failure, never that a
person saw a banner.

The state-change timeline and delegation figure use the server's local session history, survive a
restart or fresh tab, and caption the window actually observed. The timeline carries its own filter
again: active, all, or decisions. The choice is remembered per session in this browser, so picking
one on a session does not pick it for the next. The cockpit's semantic history is
a separate prototype store; `--forget` does not delete it. The terminal is also a prototype: it
requires both interaction flags and registration from inside the selected session's tmux pane,
and accepts no input. Its xterm assets are vendored and served from loopback.

Exact session detail is reachable from Sessions, cockpit session links and Goal history. The
page is one column at every width. It opens with the session's name (a Claude Code session holding a `/goal` is named by that goal, so a replaced or cleared `/goal` never names it; a generated title still wins; a Codex session started with `/goal` and not prompted since is named by its goal), the state word
and what it is doing, then the question first when the session is waiting on you. A wait on the harness's
own prompt, whose question Compass cannot answer, is said instead under "Waiting on you", with how long it
has stood and where it is answered; while the open session waits, the tab's title starts "● Needs you" and
its icon turns amber. Then come the
**Intent** card with the goal and the expected outcome lines you typed, a **What the session has
done** card, and a **Drift** card with the `Analyze drift` control, what an analysis reads and
sends under it, the reading, and every departure on record, asked for or not. While a direction you
gave after your intent is unsettled, the question about it stands where `Analyze drift` would be
(see [Intent and drift](intent-and-drift.md#recording-what-a-session-should-achieve)). On Claude Code and Codex, What the session has done shows Compass's own outline of
the record, one group per message of yours, opening at your first, in short sentences naming its checks, failures and folders, made with no model
call; other harnesses keep no record it can page through and say so. On Claude Code it also holds a
model-written summary in phases, each line citing the entries it rests on: a finished session is
summarized when you open it, once Compass has observed its end (without one the card offers
`Summarize` instead), a running one on `Summarize` or `Update summary`, and a stored summary
opens without a call. Source collection continues through bounded pages in the background; `Planning the summary…`
keeps `Cancel` available. Collection limits and unread regions remain explicit, separately from
the model's window and call limits; an incomplete update keeps the saved summary.
`Delete summary` removes it after a second press, says what it removes before that press, and reports the deletion; and a line that claims in its own voice that the
work is done is withheld. **Show technical details** at the foot of the page opens the **Activity log**, with the session's numbered entries, agent activity, recorded request, tasks, subagents, token measurements and end evidence. Filters narrow the loaded entries by speaker, kind or citation. On a harness other than Claude Code or Pi the Drift section says "Compass
can't read work from this harness" where a drift level will go; `Analyze drift` stays wherever a
reader is named. With no reader on this machine, the reason stands where the control would be. The
page has at most one primary run control. No answer option is ever emphasised: a session blocked on
you gives the primary to the terminal raise when one is offered, and otherwise nothing is primary
while its question is open.
With no outcome line, Compass reads your goal's end state; a goal too vague to read is refused. The refusal reads "This goal is too vague to analyze against. Rewrite it with what should be true when the work is done, then try again." under the Goal field, shows no level, departures or Steer back for that run, clears when you edit the goal, and counts against the daily cap like any press. A link to a session
the board no longer holds names that session and says it is not in the current payload.

The route lives in the URL fragment: `#n=sessions`, `#n=projects`, `#n=attention` (Needs you),
`#n=intent` (Goal history), `#n=settings`,
`#n=project:<encoded-project>` with the selected session and then the open tab appended when either
is set, or the full project, harness, and session identity for session
detail, where the project part is empty for a session that published no project label. A project link that ends in the retired `held-to` tab opens that session's page. Reload, pasted links, and browser back therefore preserve the selected view. Old fragments
that belonged to the retired dashboard normalize to Sessions, as the bare URL does. Open the dashboard at its bare URL;
the retired `next` query is no longer a dashboard route.

The header shows how many sessions are Working across the board, including on project pages.
The **Needs you** badge counts sessions that are Waiting on you or Worth a look. A reported block
and an exact request for the same session count once. Keyboard shortcuts `n`, `p`, and `s` open
Needs you, Projects, and Sessions unless focus is in a form control or Meta, Control, or Alt is held.
A session opens under the tab it was opened from (Sessions for a pasted link), and its breadcrumb
starts there. `Escape` returns from a session to that breadcrumb's last link and otherwise to
Sessions, under the same focus and modifier rules. Inside a tripwire draft it cancels the draft.

MCP tools appear under the service being called rather than their wire name, for example
`GitHub · list issues`. The full recorded string remains available in the row tooltip.

### Reading declared families on the board

Sessions places a linked child after its visible parent within the same active/history section and
group bucket, with a "Child of" link. A parent outside the filtered set is still named on its child.
An unmatched declaration says "Declared parent is not on the board; not linked." On Sessions
and the session page, the parent's relationship line links to the selected working child as
`Waiting on child "title"`, even when a filter hides that child. Project shows the same wait in text.
An open question keeps its input-wait state on both row and session page. Open a
parent's page to see its linked children and states; open a child to see its parent. An ended child
remains listed while it stays on the board, but no longer holds its parent working.

Group labels appear as text, with "(from parent)" when inherited. In More filters for power users,
Group narrows by label and Group by group arranges rows in label buckets. "No group" marks
unlabeled rows. Named choices, selected chips and bucket headings quote the label, so a label
called `No group` reads `"No group"` and remains distinct from absence. Nesting never unhides a
filtered headless child or changes the board's counts.
Group choices and grouping survive polls and navigation for the life of the tab; reload resets them.
The terminal session and project lists use the same group, parent and waiting words.


## Needs you

The Needs you brief counts **Waiting on you**, **Worth a look** and **Ready to wrap up**.
**Also at risk, off the session count** holds quota pressure, location gaps, concurrent checkout
warnings and requests whose session ownership is not established.
**Not on this board yet** names the capabilities no source supports. Coverage details describe
which harnesses and observations Compass could read.

**Waiting on you** combines native harness gates with questions registered through `ask_operator`.
Both reasons can appear on the same row and session page, and the session counts once. An open exact request keeps the session in this queue
even if it reported an end.
Native permission prompts, plan approvals, and harness questions must still be answered in that
session's terminal; Compass does not mark them answered on the session's behalf. A Claude Code or
Codex row therefore carries a control that copies the command that harness's own CLI takes to
re-enter that session, so reaching the terminal is a paste rather than a hunt. The other eight
harnesses publish no session id their CLI would accept, and their rows show no control rather than a
guessed command. Where Compass can reach the terminal a session is running in, the row carries a
second control that raises it, so the hunt across tabs ends in a click rather than a paste. That
reach is narrow: macOS, tmux, a session that started while this dashboard has been up, and exactly
one terminal attached to it. Rows outside it carry no raise control at all, and the queue's coverage
details say how far the feature reached rather than repeating the absence on every row. A raise
changes what that terminal displays; it does not bring the window in front of other applications,
and nothing is ever typed into the session. The item leaves when the harness publishes evidence that the wait ended. A
question registered through `ask_operator` has answer buttons in the session detail. Choosing
one returns that option to the waiting agent. Free-form replies are not
accepted, unanswered questions expire, and `--no-ask` disables this lane.

**Worth a look** names detected failed-tool loops, long-running turns, quiet launches, uncommitted
work at a reported end, conflicting source evidence and labels shared across measured locations.
Waiting on the reader takes precedence. When a label spans multiple measured locations, each
measured member has its own exact session link. The warning also reports how many locations
Compass could not measure. Sessions in one measured
directory or repository need no label warning. A multi-location sentence counts only measured
sessions, followed by a separate count of unknown locations. A missing Claude worktree layout
keeps its label and worktree name but counts as unknown. Worktree names are display text.
Two non-ended sessions working or waiting with measured evidence of the same checkout get a
concurrent-session warning; a matching name alone cannot establish that evidence.
Each warning links its members by title, worktree, id and start time, without rendering raw checkout
paths or identity keys. Missing titles and start times are stated as not published.
It never absorbs their stops, ends or tasks. A quiet row is never promoted into proof that nothing is waiting. Claude, Codex, Copilot, Cursor, OpenCode and Pi have wait-reporting paths; the coverage detail names
conditions. OpenCode covers parent permissions with its project adapter; Pi covers persisted-session
extension UI prompts on 0.85.1. Neither proves installation or reconstructs a wait after restart.

**Ready to wrap up** lists sessions that reported an end and clean git state after any exact
request has cleared. A stop leaves the session available for another turn. A session end conveys
no readership, remote commit or termination cause. Later lifecycle activity for the same id can
clear an end mark. Stop followed by SessionEnd still reads ended. A late SessionEnd after resumed
activity also reads ended because hooks cannot identify which process sent it. **Coming next**
groups the strongest published next action by project.

## Usage and rate limits

Your AI allowance sits below the session groups. It names the selected plan window and reset
beside the percentage used and a bar. The tick marks how much of the window has elapsed when
the vendor published a clock. Choose another window when several are available. How the AI
allowance works shows the pace, reset time, source, and the projected budget end. It also
shows what the remaining budget buys at the measured paces and observed working time for the
project with the most measured work. Compare the budget's projected end with the reset.

Quota evidence also appears in Needs you, raised either by a level at or above 70 percent or by a
pace whose projected end falls before the reset. Codex reads rate-limit snapshots from its own
session files. Claude and Cursor use the harness credential to poll their vendor endpoint at most once
per five minutes while a page is open, and never refresh, write, log, or serve the token. This is on
until you turn it off: one line beside the windows says the quota is read with the logins on this
machine and that no session content is sent, beside Turn off quota reading. Turning it off stops
credential-backed fetches in this browser and hides their percentages and bars. Fresh Codex disk
readings and Antigravity receipts can still appear in Your AI allowance.
Cursor fetching is macOS-only, and because Cursor publishes a cycle end with no start, its row shows
a level and no clock.
Copilot contributes per-session AI Units from disk but no percentage because its entitlement is not
stored locally. Antigravity can forward quota from its status-line payload:

```json
"statusLine": {"command": "python3 <skill-dir>/launch.py <skill-dir>/notify_hook.py http://127.0.0.1:4553/api/usage", "enabled": true}
```

`--no-usage` disables credential-backed vendor fetching for a run whatever the page has stored; disk-read evidence remains.
Expired, rejected, missing, or stale quota is withheld rather than rendered as zero. Claude, Codex,
and Antigravity may publish five-hour and weekly windows, while Cursor publishes its monthly billing
cycle. Capacity bars use accent below the window's sustainable pace, amber from 1× pace, clay from 1.5×, and neutral ink when no clock supports a pace.
Model-specific Claude weekly limits remain separate because the tightest model allowance can stop
work before the account-wide window does.

