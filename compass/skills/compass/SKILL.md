---
name: compass
description: Open Compass, a local agent-cartography dashboard for Claude Code, Codex, Pi, Gemini, Antigravity, Copilot, OpenCode, Cursor, Goose, and Droid sessions, with subagents, task progress, token rate, ETAs, and Claude input-wait notifications. Use for “open compass” or “monitor agent progress”.
license: Apache-2.0 AND OFL-1.1
---

# Compass

Use Intent and drift to compare a session's recorded work with your goal. Open a session, set a
goal and press `Analyze drift`. The `How Intent and drift works` entry in the Intent card's `More` menu explains the steps, the
reading's limits and why an expected outcome line is needed for a drift level.
New to it? `See a sample session (view only)`, above the Sessions list, opens an anonymized session
that drifted, with a stored summary of what it did, its stored reading, the correction Compass
composed and numbered (i) marks that explain each part. It is static page data: nothing in it is saved, sent or run.

Compass is an agnostic agent cartography and visualization tool: a local web dashboard mapping live coding-agent activity across **ten harnesses** on this machine — Claude Code, Codex, Pi, Gemini CLI, Antigravity CLI, GitHub Copilot CLI, OpenCode, Cursor CLI, Goose, Factory Droid — each row badged with its harness. A "Discovered harnesses" strip at the top shows all supported harnesses; ones with local session data are green/enabled, others gray/disabled. A harness's sessions only appear if its data is discovered. Transcript-backed sessions appear even if they never called TaskCreate; Claude task files may also surface a task-only session when its transcript is unavailable. Per session: a live state badge, what it's doing right now, running subagents (named pills), a current-turn elapsed/ETA estimate with progress bar, a ⚠️ warning (with tooltip) when a request runs or is estimated ≥15 min, one row per tracked task, and the recent token output rate. Fires desktop notifications when a session is blocked waiting on the human — Claude, Codex, Copilot, Cursor, OpenCode and Pi can report waits, within their stated coverage — and when any session registers a question through the ask lane. Sessions, Projects and Attention render the same data three ways — see Dashboard views below.

Store locations are resolved per platform, and the documented relocation variables are honored: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME` (the CLI creates `.gemini` inside it; relocates the Antigravity store with it), `COPILOT_HOME`, `PI_CODING_AGENT_DIR`, and `PI_CODING_AGENT_SESSION_DIR`. When one is set it is authoritative — no fallback to the default location. Run `--diagnose` to see every path searched.

Data sources (read-only; a reader-started model call can send session content through an installed Claude Code or Codex CLI. Analyze drift runs on your press, Codex goal summaries on `Summarize this session` in Console, and a Claude Code session summary when you open a finished session or press `Summarize` or `Update summary`; each tells you once what is sent and where, again if the destination or content tier changes. Pause model calls or `--no-observer-model` stops them, and `Turn off summaries` stops session summaries alone. Unasked drift checks remain a separate opt-in. All parsing is defensive — a broken harness store is skipped, never fatal):
- `~/.claude/projects/*/<session>.jsonl` — Claude transcript tails: session discovery (a file holding only generated-title, agent-name or PR-link records is not a session), titles, token usage, pending AskUserQuestion detection and the text of the question it is asking
- Claude subagents, two generations: modern harnesses write each subagent as a top-level `~/.claude/projects/*/<uuid>.jsonl` whose records carry `agentName` + `teamName: "session-<parent prefix>"` — these fold into the parent session (named pill, its own start and elapsed, freshness, output rate) and never appear as standalone sessions. A teammate dispatched into its own pane stays on that row once it goes quiet, marked as no longer running rather than dropped, and its own subagents are walked and listed beside it, each attributed to the teammate that spawned it; legacy `<session-uuid>/subagents/agent-*.jsonl` + `.meta.json` files are still recognized (fresh mtime = running, and one the lead ran itself stays listed as no longer running once quiet, on the same display window as a teammate), including the `subagents/workflows/<run-id>/` directory a workflow fan-out nests its agents in. A bare `agentName` from a top-level `--agent` launch has no parent relation and remains a standalone session; `agentSetting`, not `agentName`, supplies any Spacedock role. Agent writes count as parent activity in their own right, so a session parked on a long background workflow reads Working rather than Idle
- Spacedock workflows: a Claude session launched by Spacedock carries an `agentSetting` of `spacedock:first-officer` or `spacedock:ensign` in its first transcript records, which is how its role badge appears. Pi and Codex write no such setting, so a supported boot result earns a first-officer badge instead, and never an ensign one. Codex also accepts the captured fulfilled-result wrapper only when its integer exit code is zero and its output is one complete boot JSON object. A first officer also records its `spacedock status --boot` output — counted only when it arrives as command output, never as ordinary conversation text — which names each workflow directory and each entity-state directory absolutely. The ordered stage list comes from the workflow `README.md` frontmatter, and each entity's current stage from the `status` in its own state-file frontmatter; boot's `dispatchable` list is only a snapshot of what was ready to move at boot, so it fills in behind the state directory rather than standing in for it. Those two kinds of frontmatter are the only project files the stage-strip reader reads; the cockpit's separate project-context prototype also reads bounded dispatch and workflow evidence — see the repository's SECURITY.md for the contract, and `--no-spacedock` to disable it
- `~/.claude/teams/session-<id>/config.json` — the Claude teams registry: the roster of members a lead session has dispatched. A member is listed here the moment it is spawned, which is before it has written a transcript byte, so a member on the roster with no transcript anywhere is one that has not started — the shape an agent parked on a startup permission prompt takes on disk — and the session reports Needs input and names it. The roster is a roster and not a heartbeat: one file stamp covers every member and moves only on a join or a leave, so a member is read this way only once it has been registered longer than a healthy agent takes to start and only while the session is still inside the display window; running subagents keep their own transcript freshness. Older harnesses pruned a member as it finished; Claude Code 2.1.259 keeps it and marks it `isActive: false` instead, so what stops finished work from reading as running is transcript freshness, and that flag is only ever allowed to confirm a member has stopped, never to claim one is still going. A session directory with no `config.json` (an older layout) is skipped rather than treated as broken. A gate that opens mid-run is not detected: nothing in the store distinguishes a blocked member from a busy one once it has started
- `~/.claude/tasks/<session-id>/N.json` — tracked task state (subject, status, activeForm); current bare-UUID and older `session-<id>` directories are supported
- `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` — Codex. The newest instruction, the title and the agent's turn-start statement of intent come from a walk backward from the end of the file rather than from its tail, because Codex pads a rollout with large encrypted reasoning blobs and the prompt is usually well outside any bounded tail read. Line 1 (`session_meta`) gives identity + cwd; `thread_source: "subagent"` files are subagent threads (named by `agent_nickname`), grouped through `source.subagent.thread_spawn.parent_thread_id`; resumes dedupe to newest file per session. Codex's own plan is read from the newest `update_plan` record and becomes that session's task rows — the same backward walk and for the same reason, since a session that has done any work since writing its plan has pushed it out of tail range. Two wire shapes are read, because a given Codex build writes one or the other: an older tool call whose arguments are JSON, and the current one that carries the plan as JavaScript source. The walk does not stop at a compaction boundary the way the prompt walk does, since the CLI keeps showing the plan across one. A step carries no timestamps of its own, so a Codex session gets task rows and a progress count but no age per row and no "est. remaining"
- `~/.pi/agent/sessions/--<encoded-cwd>--/<timestamp>_<uuid>.jsonl` — Pi v3. The default store is nested; a custom session store is flat and contains JSONL files directly. The last persisted leaf's ancestor path is active, so sibling branches are excluded from prompts, tools, output usage, and turns. The latest global `session_info` name is the title, including a later clear; `parentSession` means fork or clone, never a subagent. Assistant, tool-result, compaction, and branch-summary output usage feed the rate. Pi has no allowance of its own, so each row also names the authority it is spending, read from the newest entry on the active branch that carries one (an assistant message, or a `model_change` the user has switched to but not spent yet): it renders as `via Codex · gpt-5.6-sol`, and a provider with no harness of its own keeps its own name. A session that names no provider makes no claim rather than guessing from Pi's current default. Pi has no passive needs-input or core-subagent signal. Its Working/Idle reading comes off the active-branch leaf record's `stopReason` rather than recency alone, and it is the only harness whose store records how a turn ended: an assistant leaf stamped `toolUse` is a tool call whose result has not been written, so it reads Working — `running <tool>` — past the 90s window and up to 15 minutes, because recency cannot tell a long `bash` from a parked session; past that it reads Idle, because a transcript can record that a tool started and can never record that the process died, so a Pi hard-killed mid-tool would otherwise hold the top of the board for the whole display window. A finished turn (`stop`, `aborted` or `error`) reads Idle the second it lands however fresh it is. A `user` or `toolResult` leaf has handed the turn back to the model and reads `thinking` while fresh. An unrecognised `stopReason` claims nothing and stays on recency. None of this distinguishes a finished turn from an unanswered wait, which still needs a turn-end event reaching the board: Pi documents `turn_end` and `agent_settled`, the second one for status integrations by name, but both are handed to an in-process extension handler and Compass ships no Pi adapter to receive one. It does get a Spacedock first-officer badge and stage strips: with no `agentSetting` to read, a Pi session is taken to be a first officer when its transcript carries a `spacedock status --boot` envelope, written as a `toolResult` message. There is no Pi ensign role, and a Pi strip never bolds an entity, because Pi reports no workers to attribute one to.
- `~/.gemini/tmp/<project>/chats/session-*.jsonl` — Gemini CLI main sessions. Gemini CLI stopped serving consumer accounts in June 2026 and Antigravity CLI succeeds it there, but enterprise Code Assist and API-key use still write this store, so it is historical on a consumer machine — sessions read as idle and need `?all=1` to show — and live on an enterprise or API-key one (line 1: `sessionId`/`kind`/`directories`); `chats/<parentSessionId>/*.jsonl` are subagent recordings (linked by directory name). Flat messages and resumed-session `$set.messages` snapshots support `type: user|gemini` and per-message `tokens.output`. Legacy single-`.json` chat files are not parsed
- `~/.gemini/antigravity-cli/conversations/<session-id>.db` + `cache/last_conversations.json` + `log/cli-*.log` — Antigravity CLI (`agy`) sessions. Per-conversation DB/WAL activity provides discovery and working/idle state; trajectory-metadata protobuf fields fold fresh subagents at every nesting depth into the root card with role/type labels, and descendant activity and output usage feed the root state and token rate; stable step-metadata fields provide prompt boundaries and tool action/summary; the cache supplies the primary workspace, with CLI logs as its fallback and as the latest-prompt source; when a log carries no prompt, the newest typed direction in the conversation's `brain/<session-id>/.system_generated/logs/transcript.jsonl` is the title, and those directions alone, never the agent's work, are what a reading of an Antigravity session reads against. Conversation content is not decoded
- `~/.copilot/session-state/<uuid>/events.jsonl` (+ legacy `history-session-state/`) — Copilot CLI typed events: `user.message`, `session.start` (`data.context.cwd`), `tool.execution_start`, `subagent.started/completed/failed`, `session.task_complete`, `permission.requested/completed`. The permission pair joins on `data.requestId` and is what makes a Copilot row report Needs input; only the kind of prompt is read from it, never the command or the URL. A subagent's model comes off the same `subagent.started` object its name does, so the two are paired without a join, and all three subagent events are keyed on the `agentId` they share. Event `data` field names are de-facto, parsed defensively
- `~/.local/share/opencode/opencode*.db` (SQLite, read-only) — OpenCode: `session` table (`parent_id` links subagent/child sessions, `directory`, `title`, `time_updated` in epoch ms; archived sessions filtered), plus `message` joined to `part` for turns and prompts. `message` has no `type` column — the role is inside `message.data` — and the prompt text is inside `part.data`, on the parts a message typed `text`, so an attached filename never publishes as the prompt someone typed. Measured on 1.18.20: `session_message` exists, is what an earlier reading went to, and no build measured writes a row into it. The model is the `id` inside `session.model`, a JSON object OpenCode writes on the session row; the column is optional there, so a row carrying none falls back to the newest assistant message's own `modelID`, and a child session's model is read from its own row rather than inherited. Busy/idle is not persisted — inferred from `time_updated` freshness
- `~/.cursor/chats/*/<agent-id>/store.db` (SQLite, read-only) + the sibling `meta.json` — Cursor CLI: the `meta` table holds hex-encoded JSON (session name, `latestRootBlobId`, and `subagentInfo` on a child), and the sibling file holds `cwd`. Minimal support: discovery + working/idle via db/WAL mtime + title + project + the model of the newest message + subagents + a standing permission gate; no turn ETA (content is hex blobs). The gate is `pendingToolExecutionContracts` on the newest blob by `rowid` — non-empty means somebody is being asked, and `pendingToolCallStartedAtMs` beside it is when they started waiting. Newest by `rowid` and not simply anywhere, because the store is append-only and content-addressed: the blob that stood at the gate is still there long after the answer, and `rowid` is the only order the schema keeps. The key is matched on bytes, since the carrier is a length-prefixed binary frame rather than JSON, and the wait is published only while the row is fresh — an abandoned session stays pending in the file forever, so without that the board would carry a red row and a notification for a session nobody is in. A reading is also dropped when its stamp is too old to have been written by the store's own last write, since a real gate is what froze that file: that is what keeps a stamp belonging to some neighbouring record, or a message that merely quotes the field, from turning a row red with a wait nobody believes. The model is `providerOptions.cursor.modelName`, found by following the chat's root blob to the message blobs it lists and reading a bounded slice of the newest few. Cursor writes its own codename there and it is published verbatim, since mapping it to a marketing name is a guess that would silently mislabel the next codename. Blobs are plaintext on every store measured, but the store carries an encryption key it is never asked for: where the bytes do not read, the session reports no model. The workspace is `cwd` in the `meta.json` beside the store — no spelling of it appears in the `meta` payload at all — so the key spellings that payload was read for stay on as a fallback beneath it. Either source is accepted, bare path or `file://`, only when it resolves to a directory that exists, since a wrong key would label the row confidently and wrongly; when neither does, the row reads `cursor`, and a store with no `meta.json` (a subagent's has none) is a session without a workspace rather than a broken store. A subagent keeps its own store under the same workspace hash and names its agent in `subagentInfo.rootParentAgentId` — another store's directory name, which is exactly the session id another row carries — so children fold onto that row as pills labelled by `typeName` (their own name is the generic `New Agent`), each with the model read from its own store; a child whose named agent is not among the rows stays a row of its own rather than disappearing
- `~/.local/share/goose/sessions/sessions.db` (SQLite, read-only) — Goose v1.10.0+: `sessions` (`working_dir`, `updated_at` UTC, `session_type='subagent'` + `parent_session_id`; archived + infrastructure types `hidden/terminal/gateway/acp` filtered), `messages` (role, `created_timestamp`) for turns/prompts, `usage_ledger` for the token rate (`messages.tokens` is never written by goose). Per-session activity = `updated_at` column, not file mtime (shared DB) — a long single-message generation can briefly read Idle since `updated_at` only bumps on message insert. Legacy per-session `.jsonl` and the `GOOSE_PATH_ROOT` override are not supported
- `~/.factory/sessions/<slugified-cwd>/<session-id>.jsonl` — Factory Droid 0.202.0 (the older `~/.factory/projects/<project>/<session-id>.jsonl` root is still searched): line 1 `session_start` (`id`, `sessionTitle`, `cwd`); messages are Anthropic-style blocks (`role`, `content[]`, `timestamp`). The sibling `<session-id>.settings.json` is not read

Pi relocation: `PI_CODING_AGENT_SESSION_DIR` is an authoritative direct session-store override and takes precedence over `PI_CODING_AGENT_DIR`, Pi's global `sessionDir` setting, and the default. `PI_CODING_AGENT_DIR` relocates the configuration root; a relative global `sessionDir` resolves below it. A one-off Pi `--session-dir` and a project-local `.pi/settings.json` are not discoverable from this separate process. Set `PI_CODING_AGENT_SESSION_DIR` to the effective directory in either case.

## Session states

| State | Meaning | Derived from |
|---|---|---|
| **Needs input** (red, popup) | An agent is blocked on the human | Best effort, never guaranteed, and six harnesses can report it at all. **Claude** has four sources that cover different things rather than ranking cleanly: the bundled `PermissionRequest` hook is the main one for tool gates, seen directly for `ExitPlanMode` and in the wild for `AskUserQuestion`; an actionable Notification-hook POST is the *only* source for an MCP elicitation or a worker's permission or network request; and a pending input tool seen in the transcript is an opportunistic extra, because Claude Code flushes that record on its own schedule and sometimes not until the gate has been answered; the fourth is about a subagent rather than the session, and is a member on the teams roster that was dispatched and never wrote a transcript, described on the teams-registry bullet above. **Codex** has one, its own bundled `PermissionRequest` hook, measured firing interactively with the prompt still on screen. A Codex row says a gate is open and cannot say which, because the event envelope drops the tool name at the hook; it raises a popup on the same terms a Claude one does. **Copilot** has one too, and it is the only one that needs nothing installed: the CLI writes `permission.requested` to its own `events.jsonl` when the dialog opens and `permission.completed` only once the human answers, so the collector reads a request with no answer behind it as a standing gate. A Copilot row says whether a command or a URL is being asked about, and never which command or which URL. **Cursor** takes the same route on a different store: a standing tool-call gate leaves `pendingToolExecutionContracts` non-empty on the newest blob of the chat's SQLite store, and answering it — either way — appends a blob with the map emptied. Its store closes nothing on its own, so the wait is published only while the row is fresh enough to be trusted; the reason is on the Cursor store bullet above. A Cursor row says a permission request is open and how long it has stood, and nothing about what was asked. **OpenCode** reports parent permission waits through its per-project passive plugin. **Pi** reports extension UI prompts in persisted sessions through its adapter on 0.85.1; startup trust is excluded. Both require events enabled and lose standing observations on restart. The other four harnesses have no gate detection; Attention reports that coverage gap so a quiet row cannot be read as an all-clear |
| **Working** (blue) | Actively generating | transcript/subagent/DB activity within the last 90s; detail = in-progress task's activeForm, else running subagents, else `thinking` where the harness can see the model holding the turn with no tool call open, else last tool, else `generating…`. Pi is the one exemption from recency, in both directions — see its store bullet above |
| **Idle** (gray) | Turn ended | anything else — "awaiting your message" from the harness, which the board replaces with how long ago the session was last active. A Claude Code session whose transcript records no finished turn says "last turn not recorded as finished" instead, since it may still be mid-turn. Two situations wear the one word: a turn that ended and nobody read the result, and a session still waiting on a reply that never came. Only a turn-end event tells them apart, so only the four harnesses with turn-end hooks can — Claude Code, Codex, Gemini CLI and Antigravity, and only with their hooks installed. On the other six the row says the answer cannot be known there, rather than guessing at it: it carries `Read by scanning: no turn end can be observed here`, in the session cell and again on the session page, so a quiet row is read as nothing observed recently and not as a turn that finished |

## Dashboard views

The dark-only dashboard opens on **Sessions**, which keeps active work first and recent history
below it. Its two counters show active now and working; exact requests and reported blocks are
counted in Attention. One paragraph and the `How Intent and drift works` entry in the Intent card's `More` menu stay visible
after a session has been checked. The paragraph explains how to open a session. Where annotations
are on, the store is readable and a reading route names a provider, it explains how to set a goal and
analyze drift, adding that no session has been checked while that is true. **Projects**, one
click away, groups sessions by the label their harness publishes. **Intent log** lists every
current board session and retained annotation/discard record once, including sessions without a
project or a goal. It labels the typed goal and each expected outcome line, cached deterministic goal, and each
published workflow goal separately. A missing workflow title supplies no goal. Saved deterministic
evidence is bounded and scrubbed; every line says its currentness has not been checked and gives
its observation time or says that time is unknown. Opening the log never derives a new goal.

Annotation off/loading/error withholds typed evidence while board sessions and other sources stay
visible. Retained words, revisions and readings remain reachable after the session leaves the
board. Discard removes your saved words, typed or adopted, and readings without removing independently labeled sources.
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

Exact session detail is reachable from Sessions, cockpit session links and the Intent log. The
page is one column at every width. It opens with the session's name, its state beside a status dot
and what it is doing, then the question first when the session is waiting on you. Then come the
**Intent** card with the goal and the expected outcome lines you typed, a **What the session has
done** card, and a **Drift** card with the `Analyze drift` control, what an analysis reads and
sends under it, the reading, and every departure on record, asked for or not. While a direction you
gave after your intent is unsettled, the question about it stands where `Analyze drift` would be
(see below). On Claude Code and Codex, What the session has done shows Compass's own outline of
the record, one group per message of yours with its checks, failures and folders, made with no model
call; other harnesses keep no record it can page through and say so. On Claude Code it also holds a
model-written summary in phases, each line citing the entries it rests on: a finished session is
summarized when you open it, once Compass has observed its end (without one the card offers
`Summarize` instead), a running one on `Summarize` or `Update summary`, and a stored summary
opens without a call. `Delete summary` removes it, and a line that claims in its own voice that the
work is done is withheld. **Full activity** closes the page, collapsed until you open it: the agent's current
activity, the session's numbered entries, the recorded request, tasks, subagents, token
measurements and how the session landed. On a harness other than Claude Code or Pi the Drift section says "Compass
can't read work from this harness" where a drift level will go; `Analyze drift` stays wherever a
reader is named. With no reader on this machine, the reason stands where the control would be. The
page has at most one primary run control. No answer option is ever emphasised: a session blocked on
you gives the primary to the terminal raise when one is offered, and otherwise nothing is primary
while its question is open.
`Not enough recorded yet` is normal until you add an expected outcome line. A link to a session
the board no longer holds names that session and says it is not in the current payload.

The route lives in the URL fragment: `#n=sessions`, `#n=projects`, `#n=attention`, `#n=intent`,
`#n=project:<encoded-project>` with the selected session and then the open tab appended when either
is set, or the full project, harness, and session identity for session
detail, where the project part is empty for a session that published no project label. A project link that ends in the retired `held-to` tab opens that session's page. Reload, pasted links, and browser back therefore preserve the selected view. Old fragments
that belonged to the retired dashboard normalize to Sessions, as the bare URL does. Open the dashboard at its bare URL;
the retired `next` query is no longer a dashboard route.

The header reports event-backed running sessions and all observed subagents. When work needs intervention, a button counting
the reported blocks opens **Attention**. Keyboard shortcuts `a`, `p`, and `s` open Attention,
Projects, and Sessions unless focus is in a form control or Meta, Control, or Alt is held.
A session opens under the tab it was opened from (Sessions for a pasted link), and its breadcrumb
starts there. `Escape` returns from a session to that breadcrumb's last link and otherwise to
Sessions, under the same focus and modifier rules. Inside a tripwire draft it cancels the draft.

MCP tools appear under the service being called rather than their wire name, for example
`GitHub · list issues`. The full recorded string remains available in the row tooltip.

## Attention

Attention is a triage view. **At risk** names session evidence alongside **Needs you now**,
**Close the loop**, and **Coming next**. The opening brief counts the sessions these categories
claim and describes the remainder as moving, quiet, ended, or without a counted state.
**Also at risk, off the session count** holds quota pressure, shared display labels and requests
whose session ownership is not established. Those subjects never inflate the session denominator.
**Not on this board yet** names the capabilities no source supports. Coverage details explain
missing observations instead of treating an unmeasured harness as an all-clear.

**Needs you now** combines native harness gates with questions registered through `ask_operator`.
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
question registered through `ask_operator` is different: its offered options are buttons in
Attention and in the exact session detail, and choosing one returns that option to the waiting
agent. Free-form replies are not
accepted, unanswered questions expire, and `--no-ask` disables this lane.

**At risk** names detected failed-tool loops, long-running turns, uncommitted work and conflicting
completion evidence. Waiting on the reader takes precedence over those categories; the session
still carries its observed details. Quota pressure and shared labels appear in the separate board
group. A quiet row is never promoted into proof that nothing is waiting. Claude, Codex, Copilot, Cursor, OpenCode and Pi have wait-reporting paths; the coverage detail names
conditions. OpenCode covers parent permissions with its project adapter; Pi covers persisted-session
extension UI prompts on 0.85.1. Neither proves installation or reconstructs a wait after restart.

**Close the loop** identifies observed stops and session ends after waiting and risk take
precedence. The outcome vocabulary has six readings: stop or end, each with uncommitted work,
clean git state, or unmeasured git state. A stop is not a session end, and neither tells Compass
whether you read the result, whether commits reached a remote, or why the process ended.
**Coming next** groups the strongest available next action by project. Both are advisory views of
observed records, not commands sent to a harness.

## Usage and rate limits

The capacity strip sits on Session operations below the two session groups, so the first screen
carries values rather than its consent and budget sentences. Each readable window shows
how much of its allowance is spent against how much of its own time is gone, so the two can be
compared: a window a third spent with an eighth of its time gone runs out long before one that is
nine-tenths spent with nine-tenths of its time gone. Rows are ordered by when the budget runs out at
the pace measured so far, which is not the same order as by percentage. Beneath them, what the
remaining budget buys in minutes, and how long sessions have actually worked in the project that
consumed the most measured working time, counting the intervals that opened working and were
seen to close.
Compass never states which of the two times arrives first: the budget's end and the window's reset
sit side by side and the comparison is yours.

Quota evidence also appears in Attention, raised either by a level at or above 70 percent or by a
pace whose projected end falls before the reset. Codex reads rate-limit snapshots from its own
session files. Claude and Cursor use the harness credential only after the first-run disclosure in
the page is answered, poll their vendor endpoint at most once per five minutes while a page is open,
and never refresh, write, log, or serve the token. Until that disclosure is answered no credential
is read and no request is made, and the strip carries a switch that changes the answer later.
Cursor fetching is macOS-only, and because Cursor publishes a cycle end with no start, its row shows
a level and no clock.
Copilot contributes per-session AI Units from disk but no percentage because its entitlement is not
stored locally. Antigravity can forward quota from its status-line payload:

```json
"statusLine": {"command": "python3 <skill-dir>/notify_hook.py http://127.0.0.1:4553/api/usage", "enabled": true}
```

`--no-usage` disables credential-backed vendor fetching for a run whatever the page has stored; disk-read evidence remains.
Expired, rejected, missing, or stale quota is withheld rather than rendered as zero. Claude, Codex,
and Antigravity may publish five-hour and weekly windows, while Cursor publishes its monthly billing
cycle. Capacity bars use accent below the window's sustainable pace, amber from 1× pace, clay from 1.5×, and neutral ink when no clock supports a pace.
Model-specific Claude weekly limits remain separate because the tightest model allowance can stop
work before the account-wide window does.

## Start

Stdlib-only, Python 3.11+, no dependencies. Resolve `server.py` relative to this `SKILL.md` in the
installed plugin and start it detached, so it keeps running after this session ends:

```bash
python3 "<skill-dir>/server.py" --port 4553 --daemon
```

One line on every platform and in every shell — `--daemon` does the detaching itself, so no
backgrounding operator is involved. It prints the URL, the pid and the log path, and returns.
On native Windows `python3` is not a reliable spelling; use `python` (or `py -3`). Whichever
interpreter starts the server, reuse it for the commands below.

Drop `--daemon` to run it in the foreground instead, which is the easier shape for debugging: log
output goes to your terminal rather than to the log file.

Then open the UI:

```bash
python3 -m webbrowser -t http://127.0.0.1:4553/
```

Use `127.0.0.1`, not `localhost`: the server listens on IPv4 only, and on some systems `localhost`
resolves to `::1` first.

Tell the user the URL, that the page updates itself as sessions change, that it keeps running until
stopped, and that popups require the server to be running. Completed-task ages/estimates degrade
where the filesystem exposes no birthtime (Linux, and Windows before Python 3.12).

If the port is busy the server explains that instead of dumping a traceback, and exits non-zero —
under `--daemon` too. Check whether a dashboard is already there before killing anything:

```bash
python3 "<skill-dir>/server.py" --port 4553 --status
```

`--status` reports one of three things, and never guesses: running (with pid and start time), not
running, or that the port belongs to some other process — in which case it changes nothing. A start
on a port that already runs a dashboard is refused and points at it.

The server writes ten files, all under `~/.compass` (relocatable with `COMPASS_HOME`):
`compass-<port>.json`, which records the running instance; `compass-<port>.log`, where a
detached server's output goes; `compass-dismissals.json`, the sessions marked handled;
`compass-annotations.json`, the goal and expected outcome lines you typed against a session, plus a
text-free record of any session you discarded everything for;
`compass-deliveries.json`, what became of each notification the board raised;
`compass-departures.json`, what an unasked reading raised, written only with `--unasked-readings`;
`compass-ends.json`, the session ends the board observed, so a session that finished still reads as
ended after a restart;
`semantic-work-history.json`, the project cockpit's own record of what a project's sessions were
observed doing, bounded to a 24-hour window across at most 20 projects;
`observer/<harness>_<sid>.json`, the sidecar an observer panel records when a reader opens one; and
`compass-history.json`, the history of what the server observed, kept for up to 14 days. A store
that cannot be read is discarded rather than repaired, the board starts empty, and the header names
which reset it was. If you
wire up Antigravity's status line, `statusline_hook.py` keeps one small memo per conversation in the
same directory so a status line that fires many times a turn posts once.

### Marking a session handled

The dismissal API remains available for integrations, but the dashboard does not currently expose
handled controls. A mark made through `POST /api/dismiss` removes that session from published
counts until anything in it writes again; a subagent write counts. Marks live in
`compass-dismissals.json`. Delete that file to clear them all, call the endpoint with
`{"clear": false}` to restore one, or run with `--no-dismiss` to leave the store unread for a run.

### Recording what a session should achieve

You can record a goal and an expected outcome against one session, in your own words. The
expected outcome starts with one optional empty line and holds up to six lines, each at most 240
characters. The goal is a three-row box of at most 240. Both are optional and set independently, and saving one
leaves the other alone. Open the session's page: the fields are the first thing in its drift
block, for a session with or without a project. The how-to beside Intent says what an analysis
reads and that Compass never writes into the session. Each box shows how many of its 240 characters
you have used as you type. The Intent card shows the saved reads-from line beside its status word, and keeps `Clear` and `How Intent and drift works` in its `More` menu.
Each outcome line has `Remove`, and `Add a line` sits beside `Save intent`, all drawn from the first view; Add adds another until there are six, where it stays
on the page, refuses a seventh and says why (replace or merge a line instead). `Save intent` stays
visible and saves the drafted goal or your edits. `Undo changes` is drawn beside it, inert until there is a goal edit or prompt
choice to undo. The list saves as a whole, and Escape puts the stored words back. Each saved line shows where it came from: typed, or added from an entry. A
reading reads each line on its own and shows one row per line.

`POST /api/annotate` with a harness, a session id and `goal` or `lines` (a list of strings, the
whole checklist) does the same thing without the page; `expected_revision` refuses a goal or a list
saved from a view of an older revision (the page sends it with both and keeps what you typed), and
a seventh line or a line over 240 characters is refused rather than clipped. It writes a numbered revision; an earlier revision is never edited, so anything citing
revision 1 still means what it meant. Send `{"clear": true}` to forget a session's words entirely,
or `settle_through` with a timestamp to mark the directions given up to that moment as settled
against the current baseline. The reply says what happened: `persisted` is whether the words are
on disk, and `outcome` is which of six things the store did — `stored` (a new revision),
`unchanged` (the same words again, so no revision was minted and `persisted` is still true),
`refused` (the request named nothing the store would take, such as a settle on a session with no
words, or a list saved without the revision it was drafted against, and nothing was written),
`unwritable` (the write failed, so the words are held for this run only; or the entry could not
fit the store even alone, so nothing was written and nothing is held), `untrusted` (the store
file exists and could not be read whole, so nothing was written over it, and the page says so
in place of "nothing typed" until the file is moved or repaired) or `unreadable` (this session's
own entry was saved by a build that can read more than this one, so it is kept as it was and not
saved over). A save may send `origins`, the saved position each line came from, so two lines that
share text each keep their own source. The page draws a different sentence for each, and
re-saving the same words never mints a revision. `add_direction` with a fact id from the session's
record, `text` and `expected_revision` adds a later direction you gave as a line marked as added
from that entry, settling it in the same write; the fact must be your own message, later than
your intent and still in the part of the record Compass reads. At six lines it needs `replace`,
the position of the line it takes the place of. Over an unsaved draft, `adopt` with
`expected_prompt` and `expected_prompt_at` adopts the draft in that same write, and `adopt` beside
`settle_through` and `expected_revision` keeps your intent without analyzing; it never adopts over
a saved goal holding other words.

They are held in `compass-annotations.json`, bounded by how many sessions carry words and how many
revisions each keeps rather than by age, because a session still on the board should not lose what
you asked of it because time passed. Delete that file to clear them all, or run with
`--no-annotations` to leave the store unread and unwritten for a run.

Binding is per session, and the board says when it is not exact. Where a harness publishes only a
short identity prefix, another session sharing that prefix would share these words, and the row says
so rather than leaving you to assume otherwise.

Below the two fields the Drift section holds the run control (or the question about a later
direction), the reading and the departures on record. Notes about your saved words are in the
Intent card under the save. The agent's current activity leads Full activity, and the session's entries follow it,
numbered. The departures section appears only with `--unasked-readings` on, or once a reading or a
departure is on record. How it landed follows the session's own facts further down. With saved
words the list starts at the entry where their evidence window opens; earlier entries are
counted and not listed, and with nothing saved the whole record is listed. A Claude Code session's
numbers are fixed: #1 is its oldest message, a message keeps its number as the session grows, and a
check or file is numbered by the message it follows and its place after it (#41.2). Other harnesses
number what the page holds, from the oldest. The measured line
gives the count, in Full activity when the session is blocked and otherwise in the header,
and leaves it out when the record was not read. It lists the twenty most
recent entries in the window, the ten most recent messages the agent wrote, every check and file in
the window and every later direction still to settle, each at its own number, and says how many it
counted and did not list. An entry a departure cites is flagged "Cited" and always listed, and a direction you
gave after saving is flagged "A later direction you gave", which records no finding. In a Claude Code
session a message you sent while the agent was working, and your answer to its multiple-choice question, are
directions you gave too, at the time you typed or answered. Numbers are
worked out again on every render. Each cited entry's number on a finding opens Full activity,
scrolls to that entry and marks every entry the finding cites with its saved words and their current
numbers, and tints each of those rows so it stands apart from the list, without requesting another
analysis. An entry it cites that is not loaded yet is read from older record pages first; one no
page returns is named as not loaded, and focus goes there instead. Escape or "Back to the finding"
returns focus to the number. A finding that cites nothing resolvable says so and marks nothing.
On a harness without fixed numbers, a check that re-runs or a file written again moves the entries
after it. Each entry shows who wrote it, its own type and the source that published it, and the
list states the limit under it: demonstrated work results are read on Pi, and on
Claude Code the record also lists the checks a session ran and the files it wrote, each result as
the tool reported it and counted from the whole transcript read, and what the agent said, each of
its messages an entry marked "Agent said". A reading you press for sends the agent's messages as
evidence of what it said and claimed, each redacted and up to 1,000 characters, except the newest
reply the transcript records as ending its turn, which goes whole where it fits 4,096 bytes. The
prompt names a measured crop's excerpt length and full reply length, and may use remaining room
after your messages have had their share. Compass never stores or
shows more than the first sentence; an unasked reading sends none of them. The notice names
the content sent. It includes those checks by default, with the last 180 characters each printed
and the paths of the files written, for the destination named beside the button, and sends none where Compass cannot name that destination. On every other harness those
entries are instructions, dispatches and gate decisions and never an inspected file, test or
deliverable. Your words also appear beside the goal the harness published,
in the project view's Latest instruction card (Published instruction when undated), each on its own row so the two claims are never merged, and
the derived row says when the directive was observed.

Long caveats keep their claim on the page and put the rest behind a summary you can open, on both
the session page's drift block and Console. Nothing is removed by that: an opened one stays open when the board redraws,
and a closed one still holds every word it was written with.

A goal-less Claude Code or Codex session arrives with its goal drafted from your first prompt, as
Compass publishes it, or from your latest prompt, marked "latest", where no first prompt with a
time is published. A session that opened with a harness control such as `/clear` drafts nothing,
not even the latest prompt, and says there is no first prompt to draft from, so you type a goal.
The draft is marked "from your prompt", an excerpt says "Excerpt. Analyze reads up to 1,000 characters."
(the goal keeps the excerpt, and a reading reads the prompt it came from whole, up to 1,000
characters, or says in what it read that it could not), and the box is tinted: nothing is saved until you press Save intent, edit the box and save, or
press `Analyze drift`, which adopts the draft. `Use your prompt` lists up to five of your own
prompts, and choosing one fills the goal box for you to save. Analyze drift, Keep and an added line's save are refused
while the goal box or the outcome lines hold an edit you have not saved, because each would stand
on words that are not on screen; your edit stays in the box. No drift level or pill is drawn over
an unsaved draft. Once a goal is saved, "Saved" names the window's opening time and holds the revision line. Adding or editing outcome lines keeps that window; new goal words open another.

A direction you gave after your intent (after the saved goal's words, or after the drafted prompt)
is asked about before the press, in the control's place: "You gave a later direction at #n" names
the selected entry by its number in the list (the newest is preselected; you can choose another), and
every unsettled one is listed at its own number past the twenty-row bound. Nothing there decides whether it changes what you asked for: that is yours, and
Compass does not write into the session either way. `Keep my intent and analyze` settles them
through the newest one shown, adopting a draft in the same write, and starts the analysis. Of two
or more, the first press shows each whole and settles nothing, and the next press settles what was
shown. Keep starts the reading with the same notice and off switch as Analyze drift; where
no analysis can start it reads
`Keep my intent`, settles, and says no analysis was started. `Add it to my intent` opens the
selected direction's whole text as a pending line under Expected outcome, marked "not
saved", for you to edit, and its save settles through that direction only, so the question comes
back for any later one: a line over 240 characters is refused rather than clipped, and at six
lines you choose the line it replaces. "Use this as my goal" fills a draft, asks whether to keep
standing outcome lines, and waits for Save intent. Add on an activity entry opens that listed
direction too. The prompt menu resolves choices when opened. An unsettled direction at or before
a stored reading demotes its intent rows; a later message labels the reading as preceding it.

Delegated work names recorded launches and their clocks when present. Missing or partial
attribution says Compass cannot see all the work; a missing count is not zero. An unpaired
launch followed by thirty quiet minutes in the last turn adds an At-risk item and a question
to copy into the session. It records no finding about whether a process is running or finished.

A reading you asked for states its departures once, in its result. What the checks run while you
were away raised is reviewed under `Raised while you were away: N`, drawn only where they raised
something (with those checks on and nothing raised, their one sentence saying whether the session
was checked stands in its place), and that is the one place on the session page a raise appears.
Each row carries the annotation revision it read against and where its evidence stopped. Where the
words have since moved to a later revision the row says so, in the same wording the reading block
uses, and a raise whose revision was never recorded is not given today's number. Under them sits
what became of that lane's raise, and a raise with no delivery record on file says that rather
than showing nothing. Each raised constraint carries what a later check found, derived from later
checks rather than from a second reading: the usual answer is that no later check has read the
session, and where one has, the sentence says what it found and never that the raise caused it. The
figures beneath are one line per collection — the departures the reading raised and the departures
the away checks raised, each counted from the rows shown beside it — then the board's raises,
attempts and hand-overs, with no arithmetic between any of them. A count identifies a session worth
reading and settles nothing else, and where the away checks have never read the session the figure
says it was not measured rather than reading zero. The goal's `Clear` in the Intent card empties that box, and
the save after it keeps every earlier revision, so the raises quoting those words stay. Discarding
the whole annotation withdraws them: the quotations go from the departure record too, and what
stays is the fact that a check ran and a record of the discard itself, holding when it happened
and no text at all. That record is why a discarded session still has a line in the Intent log,
and why the board never describes it as a session nobody typed against. That act is the `Discard everything` control, in the Intent card, behind the summary of the same name and offered only
where a revision is stored; it takes two presses, and between them the board names what it will
delete and what it will withdraw. That sentence is the control's own description, and it is
written to the page's live region when the first press arms it, so it reaches a reader who is not
looking at the screen. Beside each raised departure sits the raise that selects its tmux pane
where available, whatever state the session is in; it does not bring the window forward or send
anything to the session. Resume commands are available on Attention, the waiting panel and the
project rail. The Intent log carries the same raises a line at a time, and keeps
them after the session leaves the board.

Sessions labels your typed goal beside NOW, or shows the prompt the session page drafts ("GOAL ·
YOUR FIRST PROMPT", or your latest where no first one is published) from Claude Code or Codex;
other harnesses show typed words only, and a session that opened with a harness control shows "Add
a goal". A slot without a typed
goal opens the session page with the cursor in its goal field. Showing a prompt does not save it.
A recorded departure adds a Drift mark with its age and moves the session after blocked sessions
and before working ones, even if it is idle; it does not add to the Active now figure. Earlier
revisions say the words have moved, and legacy readings without a reading time say the age is
unknown. Consistent readings add no mark or rank, and there is no drift total. With annotations
off the slot has no link and there is no Drift mark; the screen explains that once.

One thing here evaluates on a cadence, and only when you turn it on: the session page's `Live
monitor` switch in the Drift card's heading, off by default and remembered per session in this browser only, never sent to the
server. With it on, a Claude Code session's page shows a live estimate (None or low, Medium, High or
Extreme, or Not enough recorded yet), labelled `Live estimate` with the time it was computed and
worked out after every turn from the recorded checks and written paths against your saved intent,
with no model call. It says where it last rose ("Rose from Medium at #12"), recomputed each time and
never stored, adds a nudge to analyze only for a cited High signal after your last message, and shows the level in the page header beside the
entry count. An older failure blocks None or low and keeps its name and age; a failure followed
by file writes reads Medium at most until a re-run. Recorded signals show the cited entries and
their event times; its line says it reads checks and file paths, not what your intent says, and that files written by
shell commands, such as a build, are not seen. Limits of this estimate names gaps such as an intent that names no folder.
At Not enough recorded yet, the reasons sit once under Why not None or low, while that folder
limit stays visible. A broader explicit passing run can retire a
covered failure in the same directory and execution context. A folder counts only when it exists
in the session's known working directory or holds a recorded write. Over an unsaved draft it reads "Save your intent to see a live estimate" and there is no
pill. It never appears on a Sessions row, raises no notification, and never feeds the unasked lane.
Drift marks show departures already on record, from a
reader-requested reading or the optional unasked lane. With nothing typed the block says there is nothing to read against; with the observer
model off it gives that reason; otherwise it states what a reading may and may not read and offers
one control, `Analyze drift`. When it cannot run it stays on the page, refuses the press, and
names one next step, and a press on it opens "Why Analyze is off" with the whole reason, except where no reader is available on this machine: then the reason stands
where the control would be. An acceptance of each provider's checks enables that control (the
captain's of Codex's case review on 2026-09-14; the owner's of Claude Code on 2026-10-02, after its
scored runs failed): a
Claude Code session is read by Claude Code when `claude` is on PATH and by Codex otherwise, and the
evidence stays readable
whether or not you ask for a reading. A press that waits on the server shows a spinner and a busy
label ("Saving…", "Starting…") and takes no second press until it is answered, and when Analyze
opens or closes on its own a line under it says so and why. A press starts an analysis the server runs in the background,
and while it runs the control is replaced by an "Analyzing drift" box listing its real steps
(preparing what is sent, waiting for the named provider, checking the reply), the one under way
marked, with the attempt count and disclosure still beside it. A screen reader hears "Analyzing drift" once
when the box appears and how the analysis ended once when it goes, never again on a redraw or reload. The box comes from the published
board, so a reload or another tab shows the same analysis at the same step, and a second press
starts nothing. The result, or why there is none, replaces the box when it is stored; an analysis
a stop or restart cut short is recorded as an interrupted attempt. On a Claude Code session the
result shows the analysis level (worked out again from the stored reading on every view, never
stored, never on a row) with its time. A level above None or low is drawn only beside a departure the
reading shows. With none, the card draws no level or bar, and the answer says what the reading did
find and, where every line is consistent but the level is held back, why. The live estimate is not
drawn beside a reading that stands. The header pill adds "so far" while the session runs. A
departure that an earlier reading found and the next one does not is named once on that reading.
The answer follows: "Departs from your intent" with a count and
each departure's own account under a departure, otherwise a failed check after your last message,
"Can't tell", "Not reached at this stop", or "Nothing found against what it read". Coverage beside it names a measured partial
message tail, unlisted passes or writes, checks that did not fit and an adopted-source fallback.
An older reading says coverage was not recorded. A tail starting inside the intent window tags
every intent row "may be in the part not read"; claims stay independent. On Claude Code an Analyze
press reads the session's messages back to the window start where it can, and says where it stopped
when it cannot. An idle Claude Code session whose last turn has no recorded finish is read up to
its last recorded entry, and the result says so with that entry's time, never as a final verdict. General scope and the
count-by-kind cutoff remain under What the analysis read, which groups the model, your intent, the
session read and what is never read under their own headings. Coverage holds only counts, time and closed state
tokens and changes no verdict. Each line reads "Departs; evidence #n", "Consistent with
#n, as the tool reported; not inspected", "Consistent with what the agent said at #n; not a
check" where it rests on the agent's messages alone, "Consistent with what the session said at #n;
not a check", "Not reached at this stop" or "Can't tell", never "Done". Unfinished work in flight
at a non-final stop has its own result and cited explanation under Evidence. It raises no
departure, Medium level or Steer back offer, and cannot establish None or low. An unkept promise
to continue or finish, a needless wait on you or a stated remainder of the asked-for set still
counts as departure. While a turn is open, a departure that rests on messages alone, with a recorded
check or write after them, is stored as not reached at this stop; a departure on a failed check or a
write, or one with nothing recorded after it, stands. A line may depart, or read consistent, on one of the
agent's messages, never beside a check that failed after your words, and the level never reads
"None or low" on the agent's word alone. A departure resting on an agent message stops counting
once that message leaves the transcript tail the board reads. A press that carries the agent's
messages also asks whether any of them claims a state of the work (running, merged, passing and
the like) that the record contradicts, or, for a pass, a fix or a file written, that the record
does not show; the reading is asked to keep "not shown" for those, so a claim nothing Compass
records can show (merged, pushed, deployed) is not meant to read "not shown". "What the agent claimed" reads "is contradicted at #m", "is not shown by the record" (the
record read being the board's recent tail, and never where some of the session's checks, passes
or file writes went unread), "is shown at #m" or "Can't tell", and is not
drawn when there was no claim. A check that failed before the claim does not contradict it once
the agent ran the same tool again before claiming, with no failure in that run or an earlier one of it,
naming nothing after the tool but flags or `.`; the working directory is not recorded. A
contradicted claim is said on its own row and sets no level by itself. An unshown claim blocks None or low without raising Medium.
Neither is counted as a departure from your intent or held back by an unsettled later direction.
A withdrawn claim draws no row. A claim alone offers Steer back as a secondary evidence request:
`Can you show evidence for "<its first sentence>" at 14:02?`, or, contradicted,
`You said "<its first sentence>" at 14:02; the record shows otherwise at 14:05.`
Short titles and bare URLs are not quoted in the correction. Times are your local clock, the
correction names no Compass entry number, and a departure cited at one of the agent's messages
quotes that message's first sentence ("where you said …"). While departures are listed, Steer back
stays beside them, labelled "from the check at HH:MM", including once the session is idle; where
a mark or a reading of earlier words withholds it, a line beside the departures says why. "Where the work went" groups the written files by folder. A
current result offers no second run control. When your intent changed after it or new work arrived
since, the result gives that reason with one "Analyze again". The request count stays beside it.
The shared budget is not shown until it is spent; then a banner holds the top of the session page,
naming the limit and the time the next analysis can run. "Mark as inaccurate" marks the reading with
a token that is stored beside it and never sent or counted, and says so beside the control; that
reading no longer sets the level or Steer back until you press Undo, and the level's slot says why
it is empty. A later
direction alone offers no correction. A correction puts departures and failed checks first, dates
a time from an earlier day, and asks for evidence where an outcome is not shown. Under each
departure, and a contradicted claim, it carries the analysis's own explanation on an indented
line starting "Why Compass reads this as drift:", redacted, bounded and cleaned so it cannot paste
as a command or a new instruction block. Its button names
the triggering entry and age, and What the analysis read counts new work since the analysis.
The box offers Cancel, which stops the call and records a cancelled attempt that still counts, or one that spent nothing when it landed before anything was sent. A failed request says its result could
not be confirmed and is never retried automatically. The counter reports recorded model requests, so a refusal before the model runs
does not increase it.

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
On other harnesses an unasked check prefers Claude Code. If the preferred provider is unavailable or
unqualified on this machine, the other serves. Claude Code needs no separate grant. For Codex, use “Allow Codex to
run unasked checks” in the session’s Drift card; Attention points to that toggle when saved typed
goals are waiting for permission. The grant covers Codex at the disclosed destination across sessions.
Revoking it stops Codex checks; Analyze and Resume never grant it. Pause model calls stops either
provider, and Pause followed by Resume clears the Codex grant. With the startup flag off, neither the toggle nor the Attention cue appears.
It checks on an observed state
change rather than every turn, it raises a departure and never a reassurance, and it stops at a
limit of three per session and twelve per rolling day, with a fifteen-minute floor. It reads your typed goal alone, never your expected outcome
lines, and a session with lines and no goal is not checked this way. A spent limit is said out loud: a session nobody checked and a
session checked and found clean are different sentences on the board, because you were not there to
know which one you are looking at. Turning it off stops new checks and retracts nothing: what was
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
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/notify_hook.py\"", "async": true}]}
  ],
  "SessionEnd": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/notify_hook.py\""}]}
  ]
}
```

On native Windows use `python` instead of `python3`, and a Windows path. Pass a URL as the first argument for a non-default port: `python3 "<skill-dir>/notify_hook.py" http://127.0.0.1:9999/api/notify`.

After adding it (or after any settings change that breaks it), tell the user to open `/hooks` once or restart Claude Code to reload hook config.

Simulate for testing:
```bash
echo '{"session_id":"<id>","message":"test"}' | python3 "<skill-dir>/notify_hook.py"
```

3. **Lifecycle events** — the plugin's own bundled hooks at `hooks/hooks.json`, so there is **nothing to add to a settings file**. They forward general lifecycle events to `/api/events/claude`: session started and ended, prompt submitted, turn stopped, permission requested, a tool run finishing, subagent started or stopped, tasks changed, compaction finished. Where path 2 sets one piece of side state, this drives the session's Working, Needs-input and Idle state directly, so the board reacts to a turn starting instead of waiting for the next scan.

   Nothing to install: enabling the plugin is enough. Note that a session's overlays are retired when it ends, which is correct and means a one-shot `claude -p` run shows no event-driven state by the time it exits. Two things survive that retirement, both held outside those overlays on purpose: the mark that its turn ended, so a run that finished and was never read can still say so, and the mark that the session itself ended, so a session that is over reads as over rather than as one sitting at its prompt waiting for you. A session with no end recorded is not known to be running — only a `SIGKILL` ends a Claude session silently, but a harness with no adapter, a session that started before the server did, and `--no-events` all look the same from here.

   Only add the hooks by hand if the user runs `event_hook.py` outside the plugin, for instance against a checkout. In that case:

```json
"hooks": {
  "UserPromptSubmit": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/event_hook.py\" claude", "async": true}]}
  ],
  "Stop": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/event_hook.py\" claude", "async": true}]}
  ],
  "PermissionRequest": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/event_hook.py\" claude", "async": true}]}
  ],
  "SessionEnd": [
    {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"<skill-dir>/event_hook.py\" claude"}]}
  ]
}
```

The harness name is the first argument and is required. Pass a **port** second for a non-default instance: `python3 "<skill-dir>/event_hook.py" claude 9999`. Note that this differs from `notify_hook.py`, which takes a whole URL.

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
"statusLine": {"command": "python3 \"<skill-dir>/statusline_hook.py\"", "enabled": true}
```

Pass a port as the first argument for a non-default instance. This replaces the older `notify_hook.py <url>/api/usage` line, which still works and still feeds the quota band; the new script additionally drives Working state and sends the quota block *alone* rather than the whole status-line document, which carries the account email and the transcript path.

Two honest limits. The conversation id is blank until a conversation exists, which is measured: the return to Idle often cannot be reported, so the Working state carries a deadline and the collector decides again after it lapses. The second one is now settled, and not the way an earlier note here guessed. The status line does report a pending tool confirmation: driven to a real permission prompt, it pushes a confirmation-pending flag beside a `tool_use` state, and in the one arm that recorded it, every flagged push carried an id that names the session. An Antigravity row still does not report Needs input, for a different reason. The status line is a repeating render rather than an event stream, so the flag arrives in a short burst as the dialog opens — two or three pushes — and then not again until something redraws the pane, and the ordinary Working and Idle pushes that follow would clear the wait rather than leave it stuck. Reporting it needs a precedence rule that does not exist yet. An agent question raises no flag at all.

Paths 2 and 3 are complementary and can both be installed. Keep `Notification` on `notify_hook.py`: Claude Code can emit an input-waiting notification for a session that then carries on running, so it stays revocable side state rather than an authoritative state change. `SessionEnd` is useful on both, which is why it appears twice above.

## Options

| Flag / URL | Effect |
|---|---|
| `--frontend-dev-manifest PATH` | Contributor-only ticket for an owned Vite child, requiring a foreground server on `127.0.0.1`. Startup validates isolated fixture roots and a fresh child handshake; models, quota fetching and native actions are disabled. Diagnose/forget refuse this mode. Ordinary installed launches use the packaged page. |
| `--claude-reading-model MODEL` | Select an explicit Claude Sonnet or Opus generation 5 or later ID for reader-requested Claude readings (default `claude-sonnet-5-5`). `claude-sonnet-5` is the baseline. Unavailable models fail without retrying another selection; aliases and lower or unknown families refuse before launch. This selection supplies no accuracy qualification. |
| `--allow-tool-output` | Accepted and does nothing in this release, as does `COMPASS_ALLOW_TOOL_OUTPUT=1`; both will be removed in a later release. Claude Code readings include tool output by default where Compass names the destination, and name it in the notice. |
| `--observer-model` / `--no-observer-model` | `--observer-model` is accepted and does nothing in this release and will be removed in a later release. Goal summaries need no flag and run when you press `Summarize this session` in Console; `--no-observer-model` refuses every model call, including unasked checks. On a goal-less Claude Code or Codex session the goal is drafted from the published first prompt (the latest where no first one with a time is published), and Analyze drift or Save intent adopts it. A session whose first prompt is a harness control such as `/clear` drafts nothing, says so, and never drafts a later prompt in its place. The goal field also offers the latest prompt without checking. Adopted goals say "from your prompt" and never enable unasked readings; editing the goal makes typed words. Reader-requested readings need no startup flag: Analyze drift runs on your press and tells you once what is sent and where. The notice is remembered across tabs and restarts and repeats when its destination or content tier changes. Pause model calls stops Analyze drift, goal summaries and session summaries until Resume model calls. Turn off summaries affects session summaries only; it is disabled while paused with "Model calls are paused" beside it, and its saved answer is unchanged by pause or resume. They spend the capacity of the provider the disclosure names (Claude Code for a Claude Code session when `claude` is on PATH, Codex otherwise) and are capped at 100 reserved or actual attempts per rolling twenty-four hours. Failed attempts are not refunded; off/on and `--forget` do not reset that budget. Each prompt is bounded to 16,384 redacted bytes, with one call in flight per session; a reading has a 180-second timeout and a goal summary a 60-second one. Quota consent authorizes neither path. |
| `--interaction-origin-session <harness:sid>` / `--interaction-origin-registration-file <private-file>` | Enable the prototype terminal for one exact session only when both flags are supplied. The generated private file supplies the registration capability; registration must happen inside that session's tmux pane. Output is read-only and bounded; no terminal input is accepted. |
| `--port N` | Change port (default 4553; valid range 1–65535). If the port is busy, check `--status` first — a running dashboard may already be there; don't kill it blindly. |
| `--host A` | Bind address: `127.0.0.1` (default) or `0.0.0.0`, IPv4 only. Nothing narrower — a single-interface bind is refused rather than half-supported, because `--status`, `--stop` and the hook forwarders all reach the dashboard over loopback and such a bind does not answer there. **Nothing authenticates a remote reader**: anything that reaches the port reads every session's titles, prompts and paths, and can answer a question a session is waiting on. Prefer `ssh -L 4553:127.0.0.1:4553`; use `--host` only on a network the user would hand the transcripts to. |
| `--daemon` | Detach and keep running after the starting session exits. Prints the URL, pid and log path. |
| `--stop` | Stop the instance on `--port` over `/api/shutdown`. Returns once the port is free, so a restart on the same port works. |
| `--status` | Report whether Compass is on `--port`: running, not running, or the port belongs to another process. Exits 0 only when running. |
| `--forget` | Store model calls as paused and session summaries as off, without erasing unexpired spend timestamps; readings and goal summaries wait for `Resume model calls`, and session summaries also wait for `Turn summaries on`. Delete the local history store, the session-end store and the stored session summaries, remove the record of any session you discarded everything for, delete the digests of corrections you copied, and exit. It deletes nothing you typed: a discard record holds when the act happened and no text. A one-shot command like `--stop` and `--status`, not a switch for a run: what it does is not undone by running the next command without it. Refused while a dashboard answers on `--port`, and the refusal names all four stores. Two of them a running instance would undo: it would write the deleted history records back, and it would go on publishing the ends it observed. The annotation store it would not — every write there re-reads the file, so a running board picks the sweep up on its next collection — but the command refuses whole rather than in parts, so the discard records and stored summaries are still there too. Stop it with `--stop` first. |
| `--window-hours H` | Sessions idle longer than H hours are hidden (default 24) |
| `--diagnose` | Print where each harness's data was searched for and what was found there, then exit. Use this first whenever a harness the user expects is missing — collectors skip broken or absent stores silently, so a wrong path looks exactly like an idle machine. Add `--json` for machine-readable output. Reads local paths only; it writes nothing and transmits nothing. |
| `--no-spacedock` | Do not read Spacedock workflow definitions. Claude role metadata remains, but stage strips do not; saved stage conditions remain readable and suspended. |
| `--no-tripwires` | Disable workflow stage conditions and all reads or writes of their saved store. |
| `--no-usage` | For this run, never fetch vendor quota over the network and ignore quota a harness pushes in, regardless of the setting stored in the dashboard. Quota a harness writes into its own store (Codex, Copilot) still shows. |
| `--no-irreversible` | Disable command-shape matching, report ingress and publication for this run. `--no-events` also disables it. Ordinary lifecycle hints remain available with only this flag. |
| `--no-events` | For this run, do not accept lifecycle events: no event overlays, no coarse store probe, no capability published, and the fixed-interval scan keeps the board warm instead. The session-end store is neither read nor written, since the coordinator is its only writer, so a session that ended before this run reads as quiet. The rollback switch if event acquisition misbehaves. |
| `--no-git` | For this run, do not run the end-of-session git probe in any session's working repository. No git command runs at all, and every row's `dirty` and `changed` stay empty. Empty means no reading available: never attempted (including refused), attempted without a usable result, or a reading retired after resumed work. It does not mean a clean tree. |
| `--no-dismiss` | For this run, do not read or write the store of sessions marked handled: every marked session comes back onto the board. The rollback switch for the dismissal store Compass writes on your behalf. |
| `--no-annotations` | For this run, do not read or write the goal and expected outcome lines you typed against a session: nothing is shown, nothing is saved, and the session page's Intent and drift panel offers no field; its `Analyze drift` control stays on the page, inert, and says why. The rollback switch for the one store holding prose you composed. |
| `--no-ask` | For this run, do not let a session ask the reader a question: the register, poll and answer routes refuse and the page offers no control. The rollback switch for the ask lane. |
| `--no-focus` | For this run, do not raise a session's terminal: no focus command runs, no terminal identity is recorded, and the page is handed no capability to ask with, so it offers no raise control. `--no-events` turns it off as well. The rollback switch for the terminal raise. |
| `--no-history` | For this run, keep no local history of what the server observed: nothing is written and an existing store is not read back, so the board opens with no memory of earlier sessions. |
| `--no-reach` | For this run, disable outbound reach nudges: no webhook URL is resolved and no off-machine nudge is posted. |
| `--reach-url URL` | Webhook URL for off-machine reach nudges when sessions need input or finish unread while away from the desk. Overrides `COMPASS_REACH_URL` and `~/.compass/reach_url`. |
| `--no-quiet-hours` | For this run, disable quiet hours notification suppression: notifications fire regardless of local time or configured window. |
| `--quiet-hours WINDOW` | Local time window (`HH:MM-HH:MM`) during which non-urgent notifications (popups, unasked checks, tripwires, reach nudges) are suppressed, except direct questions. Overrides `COMPASS_QUIET_HOURS` and `~/.compass/quiet_hours`. |
| `--history-days N` | How long the local history keeps an observation, in days (default 14). Eviction is age first, so narrowing this drops what falls outside the window and widening it again brings nothing back. Zero or negative is refused. |
| `--history-max-bytes N` | The size cap on the local history store, in bytes (default 1048576). It is the read cap too: a file larger than it is discarded unread rather than parsed. Zero or negative is refused. |
| `http://127.0.0.1:4553/?all=1` | Show all sessions ever, including idle ones |
| `/api/data` | Raw JSON, same data as the UI. Its `build` names the page this process serves, and a tab that sees it change asks to be reloaded. |
| `/api/health` | Liveness and identity (pid, port, start time). Scans nothing, unlike `/api/data`. |
| `/api/overlays` | Diagnostic: the live event overlays behind each session's state, with their arrival order and timings, plus a record of every time an event overruled a session the dashboard had read as waiting. Use this when a row's state disagrees with what the agent is actually doing and you need to know whether an event said so or never arrived. Empty is a real answer. Absent under `--no-events`. |
| `/api/stream` | Server-sent events, one per new revision. This is what keeps an open page current, so it refetches when something changed rather than on a timer; one tab per browser holds the connection. A browser without `EventSource` falls back to polling. |
| `POST /api/shutdown` | Stop the server. Loopback-only, with the same origin checks as `/api/notify`. |
| `POST /api/usage` | Receive a harness's own quota, forwarded by its status-line command (see Usage and rate limits). Loopback-only, same origin checks. Stores in memory only. |
| `POST /api/dismiss` | Mark one session handled, or with `{"clear": false}` put one back. Body is `{"harness", "sid"}` and carries no timestamp — the watermark is the server's clock. Answers `persisted: false` when the store could not be written. 503 under `--no-dismiss`. |
| `POST /api/tripwire` | Save, Remove or Rearm one workflow stage condition. Requires `action`, opaque `id`, declared `stage` and `expected_revision`; stale revisions return 409, failed writes 503. Disabled by `--no-tripwires`. |
| `POST /api/annotate` | Record a goal or the expected outcome checklist against one session, clear both, or settle a later direction; the paragraph on what you asked for above has the body. Answers `persisted` (are the words on disk) and `outcome`, one of `stored`, `unchanged`, `refused`, `unwritable`, `untrusted` or `unreadable`, so a refused request and a failed write are told apart and re-saving the same words is not reported as a new revision. 503 under `--no-annotations`. |
| `POST /api/direction` | Open one later direction you gave for review before adding it as a line. Body is `{"harness", "sid", "fact_id"}`. Answers the message's whole text, redacted, on one line and bounded at 2,000 characters, with `clipped` and `fits` (whether the store would take it as a line), and for Claude Code or Codex a verified `goal_choice` for explicit adoption; every direction it will not open answers one `{"ok": false, "reason": "unavailable"}` body. Stores nothing of its own; the collection it runs to read the session may rewrite the semantic history store, as any collection does. Loopback-only and refused on a document navigation; 503 under `--no-annotations`. |
| `POST /api/correction` | Compose Steer back's correction for a Claude Code session. Body is `{"harness", "sid"}` and optionally `"time_zone"`, your zone's IANA name, which every time is drawn in by that zone's own rules, and `"utc_offset_minutes"`, your zone in whole minutes east of UTC within 16 hours, used where this machine does not know the name (a `time_zone` that is not text, or any other offset, is refused with 400); without either the times use this machine's clock. Answers `{"ok": true, "parts": [...]}`, each part text or an `{"entry": fact_id}` placeholder the page draws as nothing, built only from your saved goal and lines, each line's state and entry times, the first sentence of an agent message whose claim the record contradicts or does not show or at which a departure is cited (quoted as "where you said"), and each departure's stored explanation on its own labelled line; at most 5,140 characters; `{"ok": false, "reason": "too-long", "why": ...}` when its lines, counted without the explanations and quotes, pass 2,000 characters; and one `{"ok": false, "reason": "nothing"}` body otherwise. Stores nothing of its own (its collection may rewrite the semantic history store, as `/api/direction`'s does) and never sends anything to the session. Loopback-only and refused on a document navigation; 503 under `--no-annotations`. |
| `/api/cleared` | The sessions marked handled: a harness key, a session id and when each was marked, and nothing else. 503 under `--no-dismiss`. |
| `/api/annotations` | Every session you have typed a goal or an expected outcome line against, including sessions no longer on the board, with what an unasked check raised against each. Serves the words themselves, so it is read when the Intent log is opened rather than on the refresh loop. 503 under `--no-annotations`. |
| `POST /api/reading` | Ask for one reading against the words typed against a session. Body is `{"harness", "sid", "provider", "press": true, "observer_model": 1}`, where `provider` is the one the page's route for that harness named (`codex` or `claude`); no prior Allow is needed. A press never records an Allow: an older page's `"allow": true` is read as a plain press, so it lifts no pause (it answers 403 with `model-calls-paused` until Resume model calls) and grants no unasked lane. Such an Allow naming a destination that is no longer the route's still answers 409 with `"reason": "destination-changed"`, and one with no `words_destination` at all, which a page older than the binding sends, answers 400 with `"reason": "page-outdated"` and a `route` whose note says to reload. `{"consent":"off","press":true,"observer_model":1}` is Pause model calls. The same request with `consent:"on"` is Resume model calls and starts no call. With `--unasked-readings` on, a separate body carrying `unasked_grant: true` or `false`, the session identity, `provider`, `model`, `words_destination`, `press: true` and `observer_model: 1` grants or revokes unasked checks for that provider and destination, without analysis. A revoke deletes the stored Codex grant whatever provider checks that session today. It is refused with 409 and `model-calls-paused` while paused, and 503 without the flag, under `--no-annotations` (which turns `--unasked-readings` off) or under the model off switch. A grant is also refused with 409 and `no-grant-needed` for a session Claude Code checks, and with 409 for a stale provider, model or destination. Neither changes the saved summary answer. Pause and Resume model calls are accepted without annotations or a reading provider, including under `--no-observer-model`, which still refuses calls. `settle_through` with `expected_revision` settles later directions before anything else in the press, adopting a draft with it when `adopt` is sent, and every reply then carries the store's token as `settled`; a refused one answers 422. Without `settle_through`, an `expected_revision` that is not the stored revision answers 409 with `"reason": "revision-changed"` before anything else in the press, so nothing is allowed, adopted or started; the page sends the revision it drew. Bodies are capped at 12,288 bytes, loopback-only and refused on a document navigation. 503 under `--no-annotations`, the explicit model off switch, a closed reading gate, or unavailable permission storage; 403 with `model-calls-paused` after Pause model calls; 429 at the rolling cap, with its retry time; each of these permission refusals carries the press's current `route`, so a page drawn before the destination moved shows where the words go now. 409 while that session has a reading in flight. 409 with `"reason": "provider-changed"` and the current `route` when `provider` is missing or no longer the one that would run: nothing was saved or spent, so read the route's disclosure and press again. 503 with the `route` and its `reason` when no provider can read that harness on this machine. 200 with `produced: false` when no annotated session by that name exists. |
| `POST /api/summary`, `/api/summary/cancel`, `/api/summary/delete` | Start, cancel or delete one Claude Code session summary. A start is `{"harness", "sid", "action", "origin"}`, where `action` is `start`, `update` or `rerun` and `origin` is `press` or `open` (an open only starts); `{"consent": "off"}` or `"on"` is Turn off summaries or Turn summaries on for every session. A start answers 403 with `model-calls-paused` while model calls are paused, even at the cap; 429 with `daily-cap` at the 200-call rolling cap, even with summaries off; 403 with `summaries-off` while summaries are off; and 503 with `run-disabled` under `--no-observer-model`. Cancel and delete take `{"harness", "sid"}`. Loopback-only, with Host, Origin and fetch-site checks, and a document navigation is refused before the body is read; the summary is kept in its own store, not with your annotations. |

## Interpretation notes (share with the user if asked)

- **A quiet session is not proof nothing is waiting.** Claude, Codex, Copilot, Cursor, OpenCode and Pi can
  report waits within their stated coverage. Attention names missing coverage and collector errors rather than turning them into
  zero. A question registered through `ask_operator` is separate and can belong to any harness.
- **Age** on a task is creation to now, or creation to last update when complete. Claude task files
  expose timestamps; Codex plan steps do not, so Codex task rows show no borrowed age.
- **Output rate** is output tokens over the last ten minutes, not billed input or cache tokens.
  Claude, Codex, Pi, Gemini CLI, Antigravity, and Goose expose usable generation totals. Missing
  harnesses make aggregates a floor, never a measured zero.
- **Model and consumption** come only from records a harness writes. Claude, Codex, Pi,
  Antigravity, Copilot, and Cursor can report a model. Copilot alone provides per-session AI Units;
  those units are not converted to dollars or summed across harnesses.
- **Current-turn estimates** compare elapsed generation time with completed turns from the same
  session. They are withheld when there is no defensible sample. A quiet gap longer than five
  minutes re-anchors elapsed time so a permission wait is not counted as generation.
- **Loop detection** reads one request three ways, and the note says which one fired. Four
  consecutive failed Claude tool calls is the tight run. Six failed calls in the request however
  they were spaced, and more failures than successes, is the total, which no success resets, and it
  catches the request that fails three times, succeeds once, then fails three more, where the run
  alone reads as clean. Three failed calls with none succeeding at all is a request where nothing
  has worked yet. The count alone is not enough for the second of those: six scattered failures
  among two hundred successful calls is ordinary work, so the failures have to outnumber the
  successes as well. The last two readings are withheld entirely when the scan started partway
  through a request, since both describe the whole of it. Other harnesses do not expose a verified
  failure field, so Compass does not infer any of the three there. The pattern is evidence, not proof; iterating on a failing test can look
  the same from outside.
- **Project** is the last two path segments when the working directory is known. This keeps sibling
  repositories distinguishable without printing an entire path. The fallback harness label is not
  treated as proof that two sessions share a directory.
- **Session identity** includes harness, project, and the complete session id. Displayed ids widen
  beyond eight characters when nearby rows would otherwise collide. Detail routes carry the full
  identity so similarly prefixed sessions cannot alias.
- **The line beneath a session title** is the strongest current instruction Compass can attribute:
  newest operator request, current agent statement, or an earlier substantive request when the
  newest prompt is only a continuation such as `proceed`. It carries its source and age and is
  absent when attribution would be a guess.
- **`…REDACTED`** means a credential-shaped value was replaced before it reached the page. The
  original still exists in the harness transcript on disk, so rotate a real credential rather than
  treating the marker as remediation.
- **Spacedock evidence** is bounded and freshness-gated. Stage, entity, and delegation readings are
  omitted when the workflow definition or measured window cannot support them. A missing strip is
  not a claim that no workflow exists.
- **"Source not fully read"** on a row means Compass opened that session's store and could not read
  every part of it, and it names which readings are missing. What the row still shows was read
  normally; the named readings are absent rather than zero, which matters most for a token rate,
  where nothing else separates a missing measurement from a measured zero. The five harnesses whose
  store is a database can report it: Antigravity, Copilot, Cursor, Goose, and OpenCode. A row
  without the line is not a promise that everything read, only that nothing reported otherwise.

## Stop

```bash
python3 "<skill-dir>/server.py" --port 4553 --stop
```

The command uses `POST /api/shutdown` and waits for the port to come free before reporting success,
so you can start a fresh instance on the same port straight afterwards. It also clears a state file
left behind by a server that was killed,
and exits non-zero without touching anything if the port turns out to belong to another process.

**Last resort**, for a server wedged badly enough that it no longer answers HTTP. Match only
*listening* sockets — without that filter these also match connected clients, including the
browser's own network process:

```bash
# macOS, Linux, WSL (lsof is absent on many minimal images — fuser is the fallback)
lsof -ti tcp:4553 -sTCP:LISTEN | xargs kill
fuser -k 4553/tcp
```
```powershell
# Windows PowerShell
Get-NetTCPConnection -LocalPort 4553 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```
```bat
:: Windows cmd, typed at the prompt — inside a .bat file write %%a for %a.
for /f "tokens=5" %a in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":4553"') do taskkill /PID %a /F
```

Substitute the port the server was actually started on. The cmd form matches any port whose digits
contain the string (`:4553` also matches `:45530`), so prefer the PowerShell form on Windows.

## Common mistakes

- Do not widen the bind in code. The default is `127.0.0.1` and `--host 0.0.0.0` is the operator's own opt-in (see the flag table above), never something to set for them: anything that reaches the port reads every session's titles, prompts and paths.
- A harness the user expects is missing: run `--diagnose` before guessing. It distinguishes "no store here", "store present but unreadable", and "store read, no recent sessions" — the collectors cannot, because they skip unreadable stores silently by design.
- Headless Linux (no graphical session): `python3 -m webbrowser` and `notify-send` both need a desktop. Reach the dashboard over SSH with `ssh -L 4553:127.0.0.1:4553 <host>` and open it locally. If running it under systemd, use a **user** unit — a system unit expands `~` to `/root` and `ProtectHome` hides every harness store.
- Flatpak- or Snap-installed harnesses write inside their sandbox, and Snap's `home` interface excludes dotfiles like `.claude`. Compass running outside the sandbox will not see them; `--diagnose` shows where it looked.
- Very long Windows paths: Claude's encoded project directory names are long by construction, and without `LongPathsEnabled` a store can exceed the 260-character limit. Those transcripts are skipped rather than crashing, so the symptom is missing sessions — `--diagnose` reports the root it scanned.
- On Windows, Compass briefly holds a transcript open while reading it, and Python cannot request `FILE_SHARE_DELETE`. If a harness rotates that exact file in that window it may see a sharing violation. Reads are short and bounded, but the window is not zero; there is no way to close it from Python without native calls.
- A session stuck on "Needs input" after you already answered: the state clears on the session's own next transcript write — its own, not a subagent's, since a background agent writing says nothing about whether you have answered. `SessionEnd` clears it on a clean Claude exit, and a server restart also clears hook-reported notifications (they're in-memory). An abrupt kill cannot be distinguished from a terminal left open at a prompt, so it clears only by a later transcript event or restart.
- After two missed refreshes, the live header changes to "stalled" and shows the last successful update — restart the server, no need to reload the page.
