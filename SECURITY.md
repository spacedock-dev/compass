# Security policy

## Scope

Compass ships three kinds of component that touch the network. The dashboard server
(`compass/skills/compass/server.py`, whose code is the `compass_runtime` package beside it)
reads local coding-agent session stores (transcripts, task
files, SQLite databases) and serves them over HTTP. When the usage feature is on, the server also
makes the quota poll described in Usage quota reads (the quota fetcher); it carries no session
data. The model lane is the one path that can send session content off this machine. A call a
reader's action starts (a focused refresh for a goal line, a press for a reading, or the open of a
finished session or a press for a session summary) runs without a prior question and shows a
one-time, non-blocking notice naming what is sent and where, with its off switch beside it: Pause
model calls for a reading or a goal line, Turn off summaries for a summary. Turning on the Live monitor
starts a Haiku check about once a minute for as long as the session is viewed, and shows its own notice. Unasked drift checks stay off by default, and `--no-observer-model` refuses
every model call.
[Observer model calls](#observer-model-calls) states its bounds;
[Light harness usage](#light-harness-usage-asking-a-harness-a-bounded-question) states the notice rule.
The opt-in UI's Space fonts are
packaged into its page, so
loading either interface makes no request to a font provider. Four small forwarders ship beside it,
each wired into a harness's own configuration by the user or by the plugin: `notify_hook.py` POSTs
a Claude `Notification` payload to the dashboard, `event_hook.py` posts command-hook lifecycle
events for Claude and Codex, `agy_hook.py` posts Antigravity's hook events, and
`statusline_hook.py` posts Antigravity's status-line state. All four share one transport, so the
loopback check, the proxy suppression and the redirect refusal have a single implementation.

Two JavaScript adapters run inside their hosts: `opencode_plugin.js` observes parent permission
callbacks and `pi_extension.js` observes extension UI prompts. They read at most 65,536 bytes from
this port's ordinary state file, reject non-regular files, and send allowlisted envelopes with the
current harness capability only to IPv4 loopback. They do not follow redirects, use proxy settings,
log native contents, or answer prompts. Each has a bounded serial queue and an HTTP deadline
(OpenCode 250 ms; Pi 500 ms), and returns from the callback without waiting for delivery.
The [OpenCode](HOW_TO_USE.md#report-opencode-permission-waits) and
[Pi](HOW_TO_USE.md#report-pi-extension-prompts) procedures state their coverage and loss boundaries. Their transport is JavaScript inside the host, not the Python forwarders' helper.

One of them could do harm if it were registered in the wrong place. Antigravity's `PreToolUse` hook
may return a `decision` that allows, denies or re-prompts a tool call, and there is no harmless
output at that position: an empty object there reads as a DENY, so a reporting hook would block the
user's work rather than pass it through. The safety property is that `agy_hook.py` is never
registered at `PreToolUse`. Where it is registered, after a tool call and after an invocation, it
prints exactly `{}` and nothing else on every path including every failure path, and a test asserts
that for malformed, empty and valid input alike. Irreversible actions below carries the same rule
for the hook that matches destructive shapes.

The third kind is one stdio MCP server, `mcp_server.py`, described under The ask lane below. It is
not a forwarder and shares none of the four's transport: a harness spawns it, it speaks JSON-RPC on
stdin and stdout, and it reaches the dashboard on loopback under the same three guards.

The posture rests on two invariants:

1. Localhost unless the operator says otherwise. The server binds `127.0.0.1`, and every forwarder
   and the MCP server refuse to reach anywhere but loopback, ignore proxy environment variables, and
   do not follow redirects. `--host` is the one way that first clause moves, it is an explicit
   argument nothing sets for you, and what it costs is under Known and accepted.
   Four kinds of outbound request are implemented, and they are named apart rather than counted
   together because they are not the same
   exposure. The quota poll carries a vendor token out and quota numbers back, and no session
   content whatever. The pull request CI read, described in Pull request CI reads below, starts
   your own `gh` when you press Analyze and sends GitHub a repository and a pull request number (or a pushed branch's name, where that bound
   it), or your own `glab` and sends a GitLab host you have signed in to a project and a merge request number; it carries no session text. A harness invocation, described in Light harness usage below, can carry
   session-derived text: it is the one pathway by which the operator's own words may leave this
   machine. A nudge to an endpoint the operator supplies, described in Off-machine nudges below,
   carries two counts and nothing that names a session. The observer model and reader-requested
   readings implement the harness invocation pathway behind their own enablement and consent. Nudges stay off
   until an endpoint is configured. `--no-usage` stops the quota poll, `--no-harness-usage` refuses
   model calls, `--no-ci-read` stops the pull request read and `--no-reach` disables nudges,
   each for its own path and no other.
   [What launches and what sends](#what-launches-and-what-sends) tables every switch against the
   test that fails when it leaks.
   Nothing else Compass does reaches the network. One further pathway is written down and reaches
   no network on Compass's own account: the hand-off request in Hand-off requests below writes one
   line to a socket on this machine, and what travels afterwards travels on the receiving session's
   own connection, which is why it is named here rather than counted above.
2. Read-only against harness stores. They are opened read-only and never written. Sixteen endpoints
   mutate, and seven of them only in memory: `POST /api/notify` updates needs-input state, and
   `POST /api/usage` stores a quota figure a harness published to its own status-line command.
   `POST /api/events/<harness>` also mutates in memory only, behind the capability described under
   Known and accepted, and so do `POST /api/ask`, `POST /api/answer` and `POST /api/ask/withdraw`,
   which register a question a session asked, record the option the reader chose, and drop a question
   whose asker has stopped waiting for it, all three described under The ask lane. So does
   `POST /api/lane`, which records that a dashboard tab has a working notification lane in it: one
   timestamp for the whole board, never written to disk, and a body that names a session is refused
   rather than stripped. Delivery records below is where that refusal is stated. The long
   poll that delivers an answer, `GET /api/ask/<id>`, drops that question from memory once it has,
   which is the delivery completing rather than a change a caller asked for. Nine write to disk.
   `POST /api/dismiss` writes the sessions you marked handled,
   `POST /api/annotate` writes the goal you typed or explicitly adopted and the expected outcome lines you typed against a session, including a line you added from a later direction you gave and the settlement of those directions, and
   `POST /api/reading` writes a model's reading of that session back into the same annotation
   entry. A press that produces nothing still writes, because the reason and the spend count are
   recorded too. These three routes write Compass's own state under `~/.compass` and never a harness
   store, so the read-only rule above stands unchanged. What the first holds and how to clear it is
   in Dismissals; the other two share one file,
   `compass-annotations.json`, bounded by a session count and a revision count rather than by age,
   and by a 16 MiB read limit that every write trims to, dropping the least recently written
   entries and never the one being written. A store file that exists and cannot be read whole is
   never written over: every save answers `untrusted` until it can be, because a write would keep
   only what this build could read, and the board says the file could not be read rather than
   showing every session as one nobody typed against. A session whose own entry this build cannot
   read is kept as it was, and a save, adoption or discard of it answers `unreadable`. Every write
   holds an OS lock on the selected annotation filename plus `.lock` beside the file across its read, its check
   and its rename (`flock` on POSIX, `msvcrt.locking` on Windows), so two dashboards sharing one
   Compass home cannot write an older copy over a newer save or reuse a revision number: a write
   that named a revision the other dashboard has moved past is refused as stale, and a plain goal
   save appends after it. A write that waits ten seconds for the lock writes nothing and answers
   `unwritable`, and so does one whose lock file exists or can be made but cannot be opened or locked
   by this user, such as a lock file left mode 000 or owned by another account. Only a filesystem
   that reports it cannot lock at all (`ENOLCK` or `EOPNOTSUPP`) falls back to the one dashboard's
   in-process lock: its saves still write, the dashboard logs once that another dashboard sharing
   the home may overwrite them, and on that filesystem the guarantee above holds within one
   dashboard only. It is
   redacted on the way in like every other prompt-derived string, written owner-only through a temp
   file and a rename -- the file synced before the rename and the directory synced after it, so
   that rename is trusted only once both are on disk; where the directory cannot be synced, as on
   Windows, the bytes are durable and only the rename is not, and the save is not reported as
   failed -- and turned off entirely by `--no-annotations`. It is the only store holding
   prose you composed rather than anything a harness published, and since 2026-09-10 it also holds
   a **reading**: a model's account of that session against those words. A reading carries one
   model-authored string, `detail` under a cited departure or unfinished-work result, and it goes through the same
   redact-before-clip scrub the two prose fields do, on the way in and again on the way out,
   because any local process can rewrite the file. Everything else a reading holds is a value the
   code selected from a closed set or composed from counts it measured.

   Delegated owner acceptance, 2026-10-05: a local rewrite of `detail` is scrubbed and
   escaped, but the prose verdict backstop used at production is not reapplied when loading the
   file. A rewritten detail can therefore say the work succeeded beside a valid departure token.
   A blanket success-word check would also reject legitimate quotations of the agent's claims.
   Repeating a prose check cannot authenticate a file the same local process can rewrite in full.
   This remains an accepted local-process limit; redaction, citation checks and escaping still
   apply. No claim of tamper detection or authenticated model output follows from them.

   A line added from an entry can also hold its verified request time and SHA256 fingerprints of
   its parent, source identity and full request-record digest, and reviewed line, under the
   [request-age ruling](docs/design-reading-a-session.md#amended-2026-10-05-verified-request-age-belongs-to-a-line).
   These bindings add no source words. Loading invalid metadata removes its age without deleting
   the line, and current parent facts must verify it before it changes a verdict. The page receives
   only verified times and source handles, bound to the current revision. Typed and legacy lines
   retain unknown request age. The fingerprints check continuity, not authenticity against a local
   process that can change both the store and the source.

   Two consequences of storing it here rather than in session history, both accepted rather than
   discovered. `--forget` deletes the session-history, session-end and summary stores and **deletes nothing
   a reader typed and no reading of it**, so a reader who wants a model-authored reading gone
   clears that session's annotation, which deletes the reading with the words that produced it.
   The one thing that command does take out of this file is the discard records described below,
   which hold no text at all. And there is no
   fourteen-day expiry: a reading is evicted when its annotation is, oldest-save-first at the
   session count above. The fourth disk writer, `POST /api/tripwire`, saves, rearms or removes
   workflow stage conditions in Compass's own store; [Saved workflow stage conditions](#saved-workflow-stage-conditions)
   owns its bounds. The fifth, `POST /api/reading/cancel`, marks the running analysis cancelled,
   rewrites its recovery marker under the state directory, and kills its CLI's process group; the
   cancelled outcome it causes is written by the analysis's own job, into the same annotation entry
   `POST /api/reading` writes. The sixth, `POST /api/correction/copied`, records the digest of a
   correction you copied, never its text, in `compass-copied-corrections.json`; [Analyze drift,
   Cancel and copied corrections](#analyze-drift-cancel-and-copied-corrections) owns its bounds.
   The seventh, `POST /api/summary/delete`, deletes one stored summary, and reading one writes
   too: a focused `GET /api/project-context` records its last access time, named with the other
   writing `GET` below.
   The eighth, `POST /api/summary`, and the ninth, `POST /api/summary/cancel`,
   start or stop a server-owned summary job, and the first also stores Turn off summaries or
   Turn summaries on. The first writes the separate summary store incrementally after each part.
   Both write identifier-only progress markers in `state_dir/summary-jobs/` before any charge;
   startup reports a dead job as interrupted with its finished parts and never resumes it.
   Delete summary stops a running summary before a later reply can publish. Discard everything
   does the same for the discarded session, under the reason `discarded`, and then deletes that
   session's stored summary; it removes no other session's. A publication lock at `state_dir/summary-jobs.lock` serializes
   admission, save, cancel, deletion and grant changes across dashboards. The independent
   `summary_permission` row and `summary_spends` receipt/timestamp rows live in the permission
   SQLite file; neither reads or charges Analyze's `spends` or `spend_jobs` tables. A receipt is
   the random job id and attempt number, never a session id or source text, and is retained for
   30 days for restart accounting; the rolling cap reads only the newest 24 hours.
   All three summary POST routes are loopback-only, enforce Host/Origin and fetch-site checks,
   and refuse document navigation before parsing a body or touching a store.
   The tenth, `POST /api/goal/find`, sends one session's own prompts to the model on a press and
   writes nothing to disk but the rolling-cap ledger row and, the first time, the goal notice in
   the permission file. It is guarded as `POST /api/reading` is: loopback-only, Host/Origin and
   fetch-site checks, a document navigation refused before the body is read, and a body that must
   assert `press` and `observer_model`. [Find goal](#find-goal) owns what it sends and what it keeps. The separate
   **summary store**, `compass-summaries.json` under the same home, holds model-written
   summaries keyed by harness and session, without a saved intent. Discard everything removes the
   discarded session's entry and no other (owner's ruling, 2026-10-21; it reversed the earlier rule
   that the summary store survives). Its versioned closed schema admits the producer's summary (lede, blocks, spans,
   fingerprints, citations, withheld markers, cut counts, gaps, coverage and spend), made-at time,
   model stamp, last access time and word-free source comparison metadata. Unknown schemas,
   torn files and files above the 64 MiB aggregate read cap are unavailable, never partially read
   or overwritten by a save. Every stored string is redacted before bounding on the way in and
   again on the way out. Writers hold a process lock and the store filename plus `.lock` across
   read, eviction and owner-only temp-file rename; unavailable filesystem locks refuse the write.
   The bound allows 64 summaries at 512 KiB each (32 MiB), plus 32 MiB for comparison metadata
   and envelopes. Eviction drops the least recently read or written summaries, never the summary
   being saved, and cannot touch the annotation store. Delete summary removes one session; no
   marker of the deletion is stored, so the next open of that finished session summarizes it again
   and sends its text once more, unless summaries are turned off or model calls are paused.
   `--forget` deletes the whole store, even when unreadable and even when the filesystem lock is
   unsupported or unusable; only a lock another holder keeps past ten seconds refuses it.
   `--no-annotations` does not govern it.
   Deletion is loopback-only, same-origin and refused for document navigation before the body or
   store is read. A local process with no fetch metadata can delete a summary; it cannot use this
   route to remove saved intent. [Session summary calls](#session-summary-calls) owns model-call bounds;
   the [store contract](docs/design-session-summary.md#store-contract) owns its schema and API.
   One forwarder writes too: `statusline_hook.py`'s deduplication memo under
   the same directory, which holds a normalized state name and a timestamp and nothing about the
   session's content.
   Two `POST`s store nothing of their own and are named here for what they return rather than for
   the count above: `POST /api/direction` hands back the whole text of one later direction you
   gave, which the page asks for on its own, with no press, for every open direction (up to 64)
   when it draws the question that quotes them, so you read the words before you choose what to do
   with them, and `POST /api/correction` hands back Steer
   back's correction, which is the goal and outcome lines you saved, each line's state and the
   times of the entries it rests on, and since 2026-10-04 the first sentence of an agent message
   whose claim the record contradicts or does not show, or, since 2026-10-20, at which a departure
   is cited, the title the activity list already publishes. Each runs a collection to read the session, and that
   collection may rewrite `semantic-work-history.json` as any collection does. [Analyze drift, Cancel and copied corrections](#analyze-drift-cancel-and-copied-corrections)
   owns the bounds of both.
   One `GET` reads wider than the rest, and is named here for that reason rather than for the
   count above. `GET /api/annotations` serves the prose you composed, for every session you have
   annotated, including sessions no longer on the board. That is a wider scope than `/api/data`
   ever had, which serves only what is live. It also serves what the unasked lane raised against
   those words, read from the departure store in the same pass, so the Intent log can show a raise
   on a session the board no longer carries. Each raised row adds eleven fields, and they are
   named here rather than summarised as one sentence: the harness and session id, when the check
   ran, the constraint it concerned, the clause QUOTED FROM YOUR WORDS, the model's own sentence
   about it, the evidence labels it cited, the annotation revision and the moment it read, the
   producer's own account of what it read, and one sentence this build derives about what a later
   check found. Two of those are prose about a departed session and one of them is yours.
   It is same-origin only, refuses a cross-site
   navigation, answers 503 under `--no-annotations`, and reads the annotation store and the
   departure store rather than session history. Discarding a session's annotation withdraws from
   both: it deletes every revision and blanks the quotations from the departure rows those
   revisions were read against, keeping only that a check ran, so words discarded that way are
   gone from this response and from both of those stores on disk. Both of those and not every
   store: session history keeps its own fourteen-day copy of the goal and each outcome line, the discard
   path does not touch it, and `--forget` is what removes that copy. The record's own sentence
   names it, so a reader meets that fact where the act happened rather than only here.
   What stays in the annotation store in their place is a
   **discard record**, and it holds four things and no fifth: the harness, the session id, the
   moment of the act, and the number of the last revision that went. No goal, no outcome line,
   no reading, no withheld reason and no press count -- the parser drops every other field of a
   record unread, so a file rewritten by any local process to hang text off one reads back with
   none. It is what lets a surface say a discard happened without restating what was discarded,
   and it is the only thing in this file `--forget` removes. The two stores are written one after the other and the
   second write can fail on its own, in which case the annotation is gone and the quotations are
   not; the reply carries that answer as `withdrew` and the board prints a sentence saying the
   raises still quote those words, rather than the one saying nothing does. That is the `clear`
   field of a `POST /api/annotate`
   body, sent by the `discard everything` control under the two boxes on the session page, and it
   is not the `clear` control beside each box: that one empties the box, and the save after it
   writes a revision with an empty string while every earlier revision, and every raise quoting
   one, stays. Nothing else removes a departure row's words. It is not on the
   refresh loop: the words leave the server when the Intent log is opened, and the route's own
   docstring records that reasoning. The POST-route inventory in the test suite cannot see a `GET`,
   so this paragraph is the accounting for it.

   Two `GET`s write as well, which is why they are named here rather than left to the count above.
   `GET /api/project-context` with a `session` that matches one row reads that session's stored
   summary, and at most once an hour per summary that read records the summary's last access time,
   which eviction orders by. It writes nothing else: the same entry with a later `accessed_at`,
   under the summary store's process lock and `compass-summaries.json.lock`, by rewriting the whole
   file, up to 64 MiB, through the owner-only temporary file and rename every save uses. That
   rewrite applies the same size bound, so it can evict other summaries but never the one read, and
   it never touches the annotation store. Under a non-default `--host` bind, a peer that can reach
   the port can cause that hourly rewrite; it cannot choose what is written.
   `GET /api/observe` is a trigger rather than a poll: it derives one session's goal, stage and open
   block and records the answer as a sidecar under `~/.compass/observer/`, again Compass's own
   state and never a harness store. Its two components are the harness key and the session id, and
   both must match `[A-Za-z0-9._-]{1,128}` before either reaches a path. `records.safe_text`
   bounds a string and strips control characters, and passes a separator straight through, so the
   grammar is what keeps the write inside that directory rather than the join. The file holds
   prompt-derived text, so it is written the way the state file and the dismissal store are: a temp
   file created owner-only and renamed into place, with a failed write reported as a failure rather
   than raised at the request. Published text records what that redaction covers. What the route
   reads is covered by Project reads below: the transcript, and the same two kinds of frontmatter a
   stage strip reads, under the same guards and the same `--no-spacedock` switch.
   The git probe runs inside a repository the user chose rather than a harness store. Git writes
   nothing there on the probe's behalf, and Compass runs no program of its own; a filter driver the
   operator has configured globally, git-lfs being the common one, can still be invoked by a
   committed attribute and may then write where it likes, which the git-reads section below states
   in full. The focus command writes nothing
   anywhere, reads nothing back, and touches no harness store; `POST /api/focus` is the one POST
   route that mutates nothing at all. The server also keeps its own history
   of what it observed under `~/.compass`, written as it observes rather than in answer to a
   request, and never a harness store, so the read-only rule stands unchanged.

Anything that weakens either invariant is a security bug: a bind reaching an address the operator did
not ask for, a request admitted that the bind's own Host gate should have refused, file reads outside
the documented store paths and the project-read contract below (however the path was derived),
writes to harness stores, running any program inside a user's repository other than the probe
described in Repository git reads (the end-of-session probe) and the two press-time identity
commands described in Pull request CI reads, running a program to reach a session's
terminal other than the focus command described in Reaching a session's terminal (the focus
command), or the hook client reaching a non-loopback destination. Those three exceptions are a
whitelist of three scoped clauses and not a general permission to execute: written generally the
sentence would make documented security bugs of three paths Compass already ships, the native
notifier's `osascript`, `--daemon`'s respawn of the server, and the quota fetcher's Keychain read.

## Find goal

`POST /api/goal/find` reads the prompts a reader typed in one Claude Code or Codex session and
answers a goal, or nothing. It runs only on a press of Find goal, one call per press, and a second
press while one runs is refused with 409 rather than charged again.

- It sends the session's own person-authored prompts and nothing else: not an agent message, not
  tool output, not a correction Compass wrote and the reader copied. Each prompt is masked by named
  form and folded as a chosen goal is, then at most 40 of them (the first five and the latest) and
  24,000 characters go in one message, with the rules and a boundary no prompt can close.
- The receiver is the route Analyze names for that harness. A press names the provider and, for
  Claude Code, the model the page drew, and a mismatch answers 409 before any call.
- Every refusal that can be known without the model comes before the prompts are read: the
  startup off switch, the stored pause, a spent day, a lured request. The charge is taken at the
  model seam, the same reservation Analyze pays, so a press that runs counts against the same
  rolling cap whether or not it finds a goal. A press with no prompts, or with the CLI missing,
  sends nothing and is not charged.
- A goal is shown only if it passes three mechanical rules: the model quotes the prompt words it
  comes from, each quote is verbatim (whitespace aside) in the prompt it names as Compass sent it,
  and the model calls the goal clear, asked in end-state wording matching a reading's. A paraphrase, a quote
  under the wrong prompt number, a goal too long for the Goal field and a reply of the wrong shape
  are dropped.
- The answer is held as words in the Goal field and is stored nowhere. Nothing is written into the
  session, and nothing is saved until the reader presses Save intent.
- The accepted limit: the third rule is the model's own judgement, carried in the same call, so a
  goal a later analysis would call too vague can still be shown. The quotes are what the reader
  checks it against.

## What launches and what sends

[Scope](#scope) names the kinds of outbound request. This section is the other direction of the
same ledger: each way Compass reaches off the machine or starts a program, the switch that stops
it, and the test that fails if it runs anyway. A path with no such test says "none" and why,
rather than leaving the cell blank.

The switches are separate, and a run that wants a path closed has to name it. `--no-harness-usage`
is an alias of `--no-observer-model` and stops model calls only. It does not stop the vendor quota
poll, which stops under `--no-usage`, or the reach nudge, which stops under `--no-reach`. A run with
all three still serves its loopback port and still starts the local programs in the second table.
Anything written as "no outbound connection under `--no-harness-usage`" is wrong, and the rows below
are why.

Tests are named `module.Class.method`, under `compass/skills/compass/tests/`.
`test_launch_and_send_pins.TheLaunchAndSendTableNamesRealTestsTest` fails when a name here no
longer resolves, so a renamed pin cannot leave this table citing nothing.

### Outbound requests and program launches

| Path | What it can carry | Stopped by | Fails if it leaks |
|---|---|---|---|
| Vendor quota poll, with the credential read before it | A vendor token out, quota numbers back, no session content. On until the reader turns it off in the page. | `--no-usage` | `test_contracts.ApplicationIsolationTest.test_no_usage_leaves_every_network_row_without_a_provider`; pushed quota: `test_http_api.UsageReceiptOptOutTest.test_pushed_quota_is_discarded_when_usage_is_disabled` |
| Reach nudge | Two counts, to an endpoint you configure. Nothing is sent without one. | `--no-reach` | `test_reach.ReachNudgeTest.test_no_reach_flag_never_attempts_post`, `test_reach.ReachNudgeTest.test_no_reach_switch_disables_url_resolution` |
| A press for a reading, an unasked check | Session content, through the Claude Code or Codex CLI that Compass starts as a supervised child. With a session summary, one of the two paths that can send what you wrote off the machine. | `--no-observer-model` or its alias `--no-harness-usage`, which overrides `--unasked-readings` | `test_launch_and_send_pins.APressUnderTheModelRefusalLaunchesNothingTest` (a press starts no process and opens no connection); `test_http_api.ReadingRouteTest.test_every_closed_gate_refuses_before_the_model_is_reached`; `test_unasked.TheSwitchIsTheWholeGateTest.test_the_off_switch_refuses_the_lane`; every caller goes through the one runner: `test_observer.SupervisedModelCallTest.test_every_model_caller_defaults_to_the_supervised_runner` |
| A press on Find goal | The prompts you typed in one session, masked and bounded, through the Claude Code or Codex CLI that Compass starts as a supervised child. Nothing from the agent, no tool output and no correction Compass wrote. The answer is stored nowhere. | `--no-observer-model`, the stored pause (Pause model calls) and the rolling cap, all checked before the prompts are read | `test_goal_find.FindGoalRouteTest.test_nothing_runs_without_a_press`, `test_goal_find.FindGoalRouteTest.test_nothing_runs_while_model_calls_are_paused`, `test_goal_find.FindGoalRouteTest.test_a_spent_day_refuses_before_the_model_and_a_press_counts_against_it` |
| An optional goal summary | A Codex goal call, on by default for a focused refresh with a notice. | The same refusal | `test_documentation.LightHarnessUsageContractDocumentationTest.test_the_observer_pathway_defaults_on_and_has_both_rollback_spellings` checks that the switch reaches the configuration. None runs a goal summary with a process patched to raise, so that half rests on the shared runner above. |
| A session summary, on open of a finished session or on a press | Session content, through the Claude Code CLI that Compass starts as a supervised child, under its own grant and rolling cap. [Session summary calls](#session-summary-calls) owns what it sends. | The same refusal, Pause model calls, and Turn off summaries | `test_summary_jobs.SummaryJobTest.test_summary_off_makes_no_call_until_on_and_no_model_switch_always_refuses`; `test_summary_jobs.SummaryJobTest.test_readings_off_refuses_summary_start_and_stops_a_running_job`; `test_summary_jobs.SummaryGrantTest.test_run_disabled_refuses_summary_charge` |
| The model-free live estimate, the Live monitor's fallback level | Nothing. It is computed from checks and file paths, with no model, and writes nothing. Its only process is the read-only committed-file `git` read of a project's check scripts. | `--no-git` stops that read | `test_live_estimate.TheLiveEstimateTest.test_no_model_is_launched_and_nothing_is_written` patches every model class and connection, and refuses any process but that git read |
| A Live monitor check, about once a minute while you view a Claude Code session with the switch on | Session text, through the Claude Code CLI that Compass starts as a supervised child, to Haiku: your saved goal, and your recent messages, the agent's replies, the commands of checks with their result, every other command as its masked line with its exit status, and the paths of files written. [The Live monitor](#the-live-monitor) owns what it sends. | `--no-observer-model`, Pause model calls, the switch, leaving the session, hiding the tab, the session ending, and the 20-minute question | `test_live_monitor.RefusalsPrecedeEverything.test_pause_refuses_without_a_call_a_charge_or_a_notice`; `test_live_lease.ALeaseThatIsAbandoned.test_a_killed_tab_ends_the_lease_left_within_the_grace_and_no_check_follows`; `test_live_lease_http.PauseAndShutdown.test_pause_ends_every_lease_paused`; `test_live_monitor.TheMonitorNeverTouchesTheUnaskedLaneOrNotifications.test_the_module_imports_neither_the_lane_nor_notifications` |
| The page and its stylesheet | Nothing. The page names no host, and its fonts and the optional terminal are packaged with it. The response carries only `frame-ancestors 'none'` as a policy, so the page's own bytes are what keep it local. | None to switch off | `test_launch_and_send_pins.ThePageMakesNoAbsoluteRequestTest` |
| The hook forwarders and the MCP server | Loopback only. The Python forwarders and the MCP server refuse a target that is not loopback, ignore proxy settings and refuse redirects. The two JavaScript adapters, `opencode_plugin.js` and `pi_extension.js`, hard-code `127.0.0.1` and have no such check to fail. | Remove the hook, adapter or server from the harness | `test_notifications.NotifyHookTest.test_refuses_to_forward_off_loopback`; `test_events_ingress.AdapterTest.test_the_forwarder_refuses_a_non_loopback_target_without_connecting`; `test_mcp_server.TransportGuardTest.test_a_non_loopback_url_is_refused_before_any_request`. None for the two JavaScript adapters. |
| A press for a reading that reads a pull request's CI checks | Your own `gh`, started as a supervised child on a press only, to read one pull request your goal or the session's own records name. GitHub is sent the repository and the pull request number, or, where a pushed branch bound it, the repository and that branch's name, under your own login. For a merge request your goal names by URL, your own `glab` reads it the same way, and the host is sent the project and the merge request number under the login `glab` stored for that host; the checks that come back go to the reading model with the rest of the entries. [Pull request CI reads](#pull-request-ci-reads) owns the bounds. | `--no-ci-read`, the page's switch beside the notice, and the refusals every press meets first (`--no-observer-model`, Pause model calls, the rolling cap) | `test_ci_read.NoCommandRunsWithoutAPressABindingAndTheSwitchOn.test_no_binding_no_launch`, `test_ci_read.NoCommandRunsWithoutAPressABindingAndTheSwitchOn.test_the_flag_no_launch_and_the_page_cannot_lift_it`, `test_ci_read.NoCommandRunsWithoutAPressABindingAndTheSwitchOn.test_the_page_setting_off_no_launch` and `test_ci_read.NoCommandRunsWithoutAPressABindingAndTheSwitchOn.test_no_observer_model_no_launch` patch the process starters to raise, as do `test_ci_read_gitlab.TheLaunchKeepsEverySafeguard.test_a_host_glab_does_not_name_launches_nothing` and `test_ci_read_gitlab.APressOnAnUnconfiguredHostStartsNothing.test_a_goal_url_on_a_host_not_in_glabs_configuration_launches_nothing` for a goal URL on a host glab does not name |
| The git probe, and the committed-file read of a project's check scripts | One bounded `git` command per session end, and four read-only ones (`rev-parse`, `rev-list`, `ls-tree`, `cat-file`) against the commit a session began on, in a repository you chose; and, only inside an admitted Analyze press that reads a pull request's checks, two more fixed `git` commands (`rev-parse HEAD` and `config --get remote.origin.url`). Nothing leaves the machine from any of them, though GitHub is later sent the repository the last one names. | `--no-git` | `test_observation.GitProbeDispatchTest.test_no_git_stops_the_probe_running_at_all`; `test_project_script_checks.ADeclaredScriptReadsAsACheck.test_no_git_stops_the_read_so_the_script_is_a_command_again` and `test_ci_read.ThePressTimeIdentityReadsTheFolder.test_no_git_launches_nothing` |
| The Spacedock workflow discovery | `spacedock status --discover`, a fixed read-only command with no shell and a two-second timeout, run in a project root Compass verified. Nothing leaves the machine. [Cockpit dispatch and terminal reads](#cockpit-dispatch-and-terminal-reads) states its bounds. | `--no-spacedock` | `test_launch_and_send_pins.TheSpacedockDiscoveryStartsNothingUnderItsSwitchTest` |
| The focus command | Local terminal automation. Nothing leaves the machine. | `--no-focus`, and `--no-events` | `test_focus.RouteTest.test_the_feature_being_off_answers_503_before_any_token_is_read`; `test_focus.OffSwitchTest.test_no_events_turns_focus_off_as_well` |
| A native notification | On macOS, `/usr/bin/osascript` with text Compass composes. Other platforms have no native notifier. Nothing leaves the machine. | `--quiet-hours` holds it back inside a window you name. No switch turns it off outright. | None: the program is meant to launch. `test_notifications.NoNativeNotificationTest` only keeps this repository's own test run from launching one. |
| The optional read-only terminal | Run against the tmux server of the one collected session you name: `tmux display-message` to resolve its pane and a read-only `tmux -CC attach-session -r`. Compass starts no tmux server of its own on this path. Output flows to the page and no keystroke flows back. [Operator-cockpit prototype](#operator-cockpit-prototype) owns the contract. | Off unless both `--interaction-origin-session` and `--interaction-origin-registration-file` are given | Off by default: `test_interaction_prototype.InteractionPrototypeDisabledTest.test_normal_dashboard_has_no_prototype_routes`. A lone flag is refused: `test_interaction_prototype.CollectedSessionCliBoundaryTest.test_interaction_flags_are_an_exact_pair`. None runs an attach with a process patched to raise, so "nothing starts without both flags" rests on those two. |
| The development frontend probe | A loopback HTTP request carrying a challenge to the development server, which only `pnpm dev` starts. The run is forced to refuse model calls and vendor usage, and a non-loopback host or `--daemon` is refused. | Not passing `--frontend-dev-manifest` | `test_frontend_dev.FrontendDevelopmentTest.test_cli_dev_requires_a_foreground_loopback_server_and_freezes_safe_services` |
| The daemon | With `--daemon` the server forks and detaches on POSIX. On Windows, which has no fork, it respawns itself with an argv built from the parsed switches. | Do not pass `--daemon` | `test_lifecycle.EveryOptOutReachesTheWindowsChildTest` (the Windows respawn carries every opt-out) |

### The launch grant for tool output

Tool output is included by default in a reader-pressed Claude Code reading when Compass can name
its destination: a check's command, result, last 180 characters of output, written paths, the
repository and number of a pull request it created, and the names of skills it used, and, for each
other command, its masked line and exit status (and its tail, when the session's own vendor reads it).
[Tool output in a Claude Code reading](#tool-output-in-a-claude-code-reading) owns the content bounds.
`--allow-tool-output` and `COMPASS_ALLOW_TOOL_OUTPUT=1` are accepted and do nothing for one release;
they will be removed in a later release. They write no grant and need no forwarding on respawn.
`test_lifecycle.EveryOptOutReachesTheWindowsChildTest.test_compatibility_flags_and_environment_change_nothing`
binds this compatibility behavior. Pause model calls and `--no-observer-model` stop the calls.

### What can reach into a session

| Path | What it does | Stopped by | Fails if it leaks |
|---|---|---|---|
| A write into a session, its transcript store or its working directory | Nothing does. A correction is composed for you to copy, and the copy is your own action in the browser. Compass keeps a digest of what you copied and none of its words. | No switch: there is no code path to turn off | `test_launch_and_send_pins.TheJourneyWritesNothingIntoAHarnessStoreTest`: over one journey of nine routes (board, observation, goal, press, correction, copy, dismissal, Intent log) it compares the transcript store, the Claude and Codex configuration directories of the fixture's home and the working directory before and after, watches `open`, `os.open` and the `os` and `shutil` calls that change a path, and checks that no Unix-domain socket is connected to. A SQLite write or a child process outside those directories is not covered. |
| Keystrokes into a terminal | None. The optional terminal is read-only, and `control` and `input` always refuse. | The terminal's own two flags, which leave it off | `test_interaction_prototype.InteractionPrototypeHTTPTest.test_stale_unregistered_spoofed_and_keyboard_paths_are_refused` |
| The answer to an ask | The option you chose, returned to the session that asked, which wrote the options. This is the only path by which what you do in Compass reaches a running session. | `--no-ask` | `test_http_api.AskEndpointTest.test_the_rollback_switch_answers_503_on_all_four_routes`; an answer outside the asker's options is refused: `test_asks.AskRegistryTest.test_answer_refuses_an_out_of_range_index` |
| The hand-off request | Not built. [Hand-off requests](#hand-off-requests-one-verb-into-a-session) states the one shape it may take. | Not applicable | None for the verb itself, because no code sends it. `test_launch_and_send_pins.ThePostRoutesAreTheListedOnesTest` pins the exact set of POST routes, so adding one fails a test and sends its author here. The journey test above adds a check for a Unix-domain socket connection, the path a hand-off would take, on the routes it calls only. |

### The sample session

The page ships one example session, an anonymized Claude Code session with a stored reading, so a new
reader can see what the Session page shows. It is static data bundled in the page and drawn over a
second shell with an in-memory server: it opens no connection, reads no session store, runs no model
and writes nothing, and its own fetch refuses every write with a 403. A press that would edit, save,
allow or run is held in the page before it reaches a handler. The transcript behind it is committed
under `sample-session/`, an exception to the policy against committed transcripts that the owner made
for this one session. It was anonymized by a script, checked for every original value, and reviewed
by readers who held only the anonymized file; the mapping that holds the originals is never committed
and `.gitignore` refuses a mapping file kept in `sample-session/`. [The design record](docs/design-sample-session.md) owns the decisions.

### What the tests do not see, and what a live capture would add

Every pin above runs against Compass's own code, with the call that would leave patched or watched.
That is the right tool for "this path is gated", and it cannot see what happens past the gate. It
does not see the Claude Code or Codex CLI once Compass has started one, which opens its own
connections. It does not see a connection made by a dependency below the patched call, and it
attributes nothing to a process.

A live capture would add that: a process and socket trace of one real journey on a running build,
once each for the default run, monitor only, no model, a declined press and a launch-granted run,
with the clipboard read back and the session transcript diffed before and after. It would show
whether the connections a run opens match the tables above. It has not run. It needs an observer
restricted to the dashboard's own process tree that loses no events (one-second sampling missed all
twenty short connections in a control run, and packet capture and DTrace were refused by the
machine), and a funded allowance for real Claude Code turns. It will run when both exist, by hand
and not in CI, and its result replaces this paragraph.

## Project reads (Spacedock stage strips)

One feature reads paths that are not under a store root. When a session declares itself a Spacedock
first officer, or in Pi and Codex has a supported boot result in its transcript,
Compass reads YAML frontmatter, and only frontmatter, from two kinds of file, so it can show where
each entity sits on its workflow's stage spine:

1. one workflow `README.md`, for the ordered stage list and which stages are initial or terminal;
2. the entity files in that workflow's entity-state directory, for each entity's current `status`.

That is the whole of it. No other project file is opened, and the only directory listed is the
entity-state directory itself, through one non-recursive `scandir`. Nothing is ever walked.

Neither path is guessed. The first officer's own `spacedock status --boot` output, already recorded
in its transcript, names the workflow directory and the entity-state directory as absolute paths.
Compass uses those values and nothing else. Before any file is opened, all of the following must
hold, and a path failing any one is skipped silently:

- the directory value is absolute, contains no NUL, and encodes for this filesystem. A lone
  surrogate survives JSON decoding, and the checks below it raise `UnicodeEncodeError` rather
  than `OSError`, so an unencodable path would escape every handler here;
- the path is canonicalised with `realpath`, and the README must still resolve inside the workflow
  directory (`commonpath` containment), so a swapped entry cannot redirect the read;
- every file opened is a regular file and not a symlink. This is checked with `lstat`, opened with
  `O_NOFOLLOW` where the platform has it, and confirmed with an `fstat` `(st_dev, st_ino)` match
  against the `stat` the cache key was built from, so a parent-directory swap between the two cannot
  seed the cache from a different file. Windows has no `O_NOFOLLOW`, so there the guarantee rests on
  the `lstat` classification alone and a racing reparse-point swap could still be followed. That is
  the same unclosable class as the `FILE_SHARE_DELETE` window described in the skill body;
- the README frontmatter declares `commissioned-by: spacedock@`, which is Spacedock's own workflow
  discriminator.

The entity-state directory is deliberately not required to sit inside the workflow directory. A
`split-root` workflow legitimately keeps its state elsewhere, and that path carries the same
authority as the workflow path, having come from the same tool result. A per-file discriminator
stands in for containment instead: an entity file counts only if its name is a well-formed slug
(`^[a-z0-9][a-z0-9-]*[a-z0-9]$`, which also excludes `_archive/` and any report left beside the
state) and its `status` names a stage the README declared.

Hard caps: at most 64 KiB read from a README and 8 KiB from an entity file, 400 frontmatter lines
scanned, 32 stage names taken, 120 characters of the README's `title`, 96 entity files read per
workflow (newest first), 12 entities rendered per workflow, and 8 workflows per session. Display
entity reads are cached on `(realpath, st_mtime_ns, st_size)`; the README cache also checks device,
inode and change time. Neither caches a file modified in the last two seconds, because a same-size
rewrite inside one timestamp tick would leave every part of that key unchanged. Stage conditions read current entity frontmatter within the same caps on
each collection, independently of the display cache. Entity files older than the freshness window
are not opened; future file stamps cannot become stage-condition evidence.

Only derived scalars reach `/api/data`: stage names (each validated against Spacedock's
`^[a-z0-9][a-z0-9-]*[a-z0-9]$` grammar), entity slugs, cycle markers, and the README frontmatter's
`title` scalar, shown as the workflow's goal line in the session view. That title is the one piece of
project-authored *text* on the surface, and it is there because a stage spine says where the work is
without saying what it is for; it is capped at 120 characters and passes through the same
control-character and bidi stripping every untrusted string does. No other file text, no frontmatter
body and no filesystem path is ever published, and the page HTML-escapes every value.
Pass `--no-spacedock` to switch the feature off. The read surface is then exactly the documented
store paths.

## Saved workflow stage conditions

`compass-tripwires.json` under Compass's state directory holds at most 64 stage conditions. A versioned
SHA-256 digest of the canonical definition and state directory pair identifies a workflow; new
condition fields expose no paths or copied file bodies. The bounded store uses atomic replacement
and owner-only temporary files. Corruption refuses mutation and evaluation rather than discarding
intent. `POST /api/tripwire` accepts only a known action, opaque workflow id, declared stage and
expected revision, under the loopback origin gate and a 1 KiB body cap.

A latch reaches disk before a notification attempt. Failed latch writes retain pending evidence
in memory and make no attempt; restarting loses that pending evidence. A saved latch is never
replayed after restart, including when the process stopped before attempting the notification.
Simultaneous dashboard processes retain the existing last-writer-wins limitation; the latch is not
a cross-process exactly-once guarantee. `--no-tripwires` disables all condition-store reads and
writes. `--no-spacedock` leaves saved intent readable but suspended. See the
[stage-condition contract](docs/design-tripwires.md) for baselines and delivery wording.

## Repository git reads (the end-of-session probe)

Two features run a program inside a directory the user chose, both git, both in `git_status.py`.
Compass already records each session's working directory; when a session ends, the server runs one
bounded git command there, so the board can show that a session stopped with work still in the tree.
The second, below the probe's own contract, reads a project's check scripts as a commit held them.

The end-of-session probe is exactly this command, or there is no probe. The press-time identity read
in [Pull request CI reads](#pull-request-ci-reads) runs two other fixed commands and never this
probe:

    git -c core.fsmonitor= -c core.hooksPath=/dev/null -c status.showUntrackedFiles=normal --no-optional-locks status --porcelain

`status.showUntrackedFiles=normal` keeps non-ignored untracked entries visible. Measured
2026-09-08: one untracked file was suppressed by `status.showUntrackedFiles=no` through local
config, `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_COUNT`. This key override closes all three routes;
other operator configuration, including ignore and filter rules, remains in effect. Clean means
no porcelain entries under these rules, not discovery of ignored content.

Two things about how it is spawned are part of the boundary rather than details of it.

**The executable is resolved, not looked up by the child.** `git` above is the name the contract
prints; what runs is an absolute path resolved once against a PATH the probe controls. Measured
2026-09-07: with the bare name, any empty or relative element ahead of the first element holding a
real `git` supplied the binary instead, and it resolved from the session's own directory, which is
the one directory whose contents must not be trusted to supply a program. The rule is order rather
than position: a leading `.`, a leading empty element, an interior empty element and an interior `.`
all hijacked, and trailing forms did not.

Every non-absolute PATH element is dropped, and the resolution refuses a relative answer as well.
Both ends, not either: the first version of this dropped a named pair, the empty element and `.`,
which reads like the whole property and was not. Measured 2026-09-07, a bare `relbin` survived that
filter, and then the two directories parted company: the resolver validated a `git` under the
dashboard's own working directory while the child resolved the same relative string against the
directory being probed, which is session-supplied. It published seven changed entries for a
directory that is not a repository at all. So the filter now drops anything a resolver would
resolve against a working directory, and the resolution returns nothing for an answer that is not
absolute even if it is ever handed a PATH from somewhere other than that filter. A PATH left with no
absolute element publishes no reading at all rather than falling back to the ambient one.

**The child's environment is scrubbed of `GIT_DIR` and `GIT_WORK_TREE`.** Either one points git at a
different repository entirely. Measured the same day: a probe of a clean repository published a
dirty reading belonging to another one, and a directory that is not a repository at all published it
too, so the check that the path is a directory does not help.

The mechanism is subprocess execution rather than a file open. That is what separates this feature from
every other read Compass performs, and the three safety flags are load-bearing. The first two were measured
2026-08-28 at git 2.55.0 across four fresh repositories, one probe each, from an identical racy-clean
state; the third was measured 2026-09-07 at git 2.55.0 with git-lfs 3.8.0:

- Without `--no-optional-locks`, the probe writes `.git/index`. The write is git resolving a racy
  stat, not a per-invocation habit, and a repository a live session is editing is the normal case
  for it rather than a corner case.
- Without `-c core.fsmonitor=`, a `core.fsmonitor` script configured in the repository is executed
  under Compass's identity. A repository can carry that setting in from wherever it was cloned.
- Without `-c core.hooksPath=/dev/null`, a filter driver installs its own hooks inside the
  repository. Hashing a tracked path whose committed attributes name a driver invokes it, and
  git-lfs then asks git where hooks belong and writes there: four files at mode 0755, named
  `post-checkout`, `post-commit`, `post-merge` and `pre-push`. `.git/index` was untouched in that arm,
  so neither other flag sees it, and this one closes it by answering with a path git cannot write.

Each flag disarms a hazard the others do not, so none may be dropped. There is no fallback to a
plain `git status`.

### The residual: a filter driver can still run, and can still write

The third flag suppresses the hook installation and neither the invocation nor what the driver does
once running. Two separate residuals, and the first is reachable by a clone.

**A committed attribute alone reaches the operator's own driver.** Measured 2026-09-07: a fresh
`git clone` of a repository whose only unusual artifact is a committed `.gitattributes` saying
`*.bin filter=lfs`, with `git config --local --get-regexp '^filter\.'` returning nothing at all,
ran `git-lfs filter-process` on one probe and gained
`.git/lfs/objects/d5/3e/d53eda7a…` inside the repository. The flag was present. The driver was
never carried by the clone: it comes from the global config that `git lfs install` writes, which
most machines with git-lfs already have. So this is clone-portable, and the write is driver-caused
rather than git writing on the probe's behalf.

**An arbitrary, attacker-chosen driver command needs `.git/config`.** A repository with
`*.x filter=pwn` committed and `filter.pwn.clean` set in its own `.git/config` had that command
executed by one probe, with the flag present. That half is not clone-portable, and there the
comparison with `core.fsmonitor` holds: both need the inspected repository's own config to name a
program. The comparison does **not** extend to the git-lfs case above, where committed content plus
a ubiquitous global install is the whole precondition. The two are kept apart here because blurring
them is what made the first version of this section wrong.

The trigger is a tracked path matching a filter attribute whose content git must hash, and **it does
not require a modified file.** A tree git itself reports clean invoked the driver on each of three
consecutive probes, because the racy-clean state that makes git hash the path is exactly what
`--no-optional-locks` declines to clear. So this recurs rather than happening once. What genuinely
reaches nothing is a repository with no matching tracked path: the attribute on its own, with
nothing it applies to, installed and ran nothing, measured.

No flag closes it, and this was looked for rather than assumed. `--attr-source` and
`GIT_ATTR_SOURCE` pointed at the empty tree do suppress the driver, and on a real git-lfs
repository they then report a merely-touched pointer file as modified, so the answer stops being
true. Clearing the driver with `-c filter.lfs.clean= -c filter.lfs.process=` makes git fail the
command outright, which publishes nothing. `diff-files`, `diff-index` and `ls-files -m` each invoke
the driver anyway, and the first two also call a touched LFS file modified. `status --porcelain`
has to hash the path to answer at all, and hashing is what runs the driver, so this is stated
rather than fixed.

`/dev/null` as a hooks path is measured on darwin. It names a location git can find no hook under on
any supported platform, and `tests/test_git_status.py` skips rather than passes where the mechanism
cannot be armed, so the Linux and Windows arms are unmeasured rather than verified.

### The residual: the reading is about the repository, not about the directory

`git status` discovers repository metadata by walking upward from the directory it runs in. The
probe passes the session's own working directory as cwd and passes nothing that bounds the walk.
With an ordinary `.git` directory and no working-tree redirection, it answers about the containing
repository. That walk has two outcomes, and only one of them is what a reader wants.

The common outcome is the right one, and it is why the feature is useful at all. A session working
in `repo/src/components` gets `repo`'s reading, which is the answer to whether that session left
work behind. Measured 2026-09-07 against this tree: a probe at a dirty repository's root and a probe
three levels inside it published an identical `dirty=True, changed=3`, while a directory with no
repository above it published `null`.

The wrong outcome is a `$HOME` that is itself a repository. A session working somewhere under such a
`$HOME`, in no project repository of its own, gets `$HOME`'s reading, and its row then reports a
dirty tree that has nothing to do with that session. Anyone who keeps dotfiles as a repository
checked out at `$HOME` can reach this. It is not reachable on the machine these measurements were
taken on, where `git -C "$HOME" rev-parse --show-toplevel` finds no repository at all, and that is a
fact about one machine rather than a property of the design.

Decided 2026-09-07, and recorded rather than fixed. Three measurements settled it, and
the first is the one to read before proposing anything here:

- The confinement this was originally filed with does not work. `GIT_CEILING_DIRECTORIES` set to the
  probed directory changed nothing in either arm: the probe three levels inside the repository still
  published the parent's `dirty=True, changed=3`, identical to the same probe with no ceiling set.
  Only a ceiling at the probed directory's parent changes the outcome, and that publishes `null` for
  any session not sitting exactly at a repository root. So this is not a fix that was weighed and
  declined on cost. It was measured not to do the thing it was proposed to do.
- Confining the walk costs a reading people rely on. Of 48 recorded session directories still
  present on the machine measured, 30 sat at a repository root, 10 inside a repository below its
  root, and 8 in no repository at all. A parent ceiling would blank one in four of the
  repository-backed ones, and `null` means no reading available, so such a row could not even say why.
- The targeted alternative reopens DEC-3. Refusing only when the resolved repository root is `$HOME`
  keeps the subdirectory case and closes the dotfiles case, but learning that root needs a second git
  command, and this section's first bound is that the end-of-session probe is exactly the one command above or
  there is no probe.

So the trade was a common correct reading against a hazard nobody here can currently reach, and the
ruling keeps the reading. What it costs a reader is written down rather than left to be discovered: a
git reading names a session's directory, but the repository git discovers may be an unrelated
ancestor such as `$HOME`.

**Local metadata can also select a different working tree.** Git can read
`core.worktree` from the discovered `.git/config` and compare another directory's contents against
that repository's index. Measured 2026-09-08: a clean source pointing at a directory with nine
untracked entries returned `dirty=True, changed=9`; removing the setting restored clean/zero.
This is accepted local-config trust, distinct from inherited `GIT_WORK_TREE`, which the probe
scrubs. A `.git` file selects metadata elsewhere; it does not by itself establish that the remote
directory's contents were measured. In the gitfile control, changing files beside the target
metadata left the reading clean, while an untracked file beside the gitfile made it dirty. Metadata
selection and working-tree redirection are separate mechanisms. The probe retains its one-command
design and does not confine either one.

What the probe publishes, per session, is two fields and nothing else:

    {dirty: bool | None, changed: int | None}

Both fields are nullable, and `null` means no reading available: never attempted (including refused),
attempted without a usable result, or retired after resumed work. It makes no clean-tree inference.
The probe fires on `session_ended`, and most harnesses do not emit that event today, so most rows
carry `null`. `changed` counts porcelain entries rather than files: git collapses an untracked
directory into a single entry, so a new directory holding three files is one entry, not three.

What is never read:

- File contents, of any file, at any point.
- Diffs and blobs. Nothing asks what changed inside a file, only that something did.
- Branch and upstream state of any kind. The branch name, its tracking branch, and how far ahead or
  behind it sits are all outside this feature.

Porcelain output names paths. Those pathnames are matching hints and are never echoed to
`/api/data`, the same rule and the same wording this document applies to `cwd`.

The cadence is one-shot, on the `session_ended` edge. Never a poll, never on demand, and never on a
turn stop: the completion stamp written when a turn stops is a different edge, and probing there
would put one subprocess in the user's repository per turn for the life of the session.

The cadence is not a bound on how many probes run at once, and that took a second gate. One edge per
session at most once each still allowed 240 live probes per harness and 960 across the four event
sources, because the event budget refills for the whole of a probe's ten seconds, and each one is a
real `git status` in a real repository. So a session already being probed is refused a second probe,
and the process holds at most 32 in flight across every harness.

The two gates cost different things, and only one of them costs a stale reading. A session refused
because its own probe is already running keeps the reading that probe produces, which can be up to
ten seconds old and stays until another session end arrives. A session refused by the ceiling
publishes no reading at all: no first probe ran for it, and releasing a slot re-dispatches nothing.
There is no automatic recovery without another eligible end event. Measured with the ceiling set
to 2 and four distinct ends: after every in-flight probe drained and collection ran, the two probed
sessions read `dirty=True, changed=5`, both refused ones read null, and the dispatch count stayed
at 2. Redelivering `session_ended` for a refused key in the same process dispatched a third probe
and supplied its reading. The decision to retain refusal is recorded in
[N-9's rejected list](docs/design-needs-input.md#n-9-idle-was-two-situations-and-only-an-event-can-separate-them).

The off switch is `--no-git`. The probe is on by default and that flag turns it off. It mirrors
`--no-spacedock` at every one of that flag's sites, including the branch that forwards flags to a
respawned daemon, so a restart cannot re-enable a probe the user disabled. With the probe off no
git command runs at all, and both fields stay `null`.

A violation of any boundary in this section is a security bug: a git command other than the one
above, any of its fixed options dropped, a read of file contents or diffs or branch state, a pathname
reaching a response, a probe on any edge but session end, a probe while the feature is off, an
executable taken from anywhere but the resolved absolute path, a reading published about any
repository but the one git discovers from the directory it names, subject to the metadata and
working-tree selection described above, or any write inside the user's repository
that Compass's own argv could have prevented.

Two of those clauses are narrower than they read, and both narrowings are the residuals above rather
than relaxations. A filter driver the inspected repository configured for itself may write where it
likes, and no argv Compass can pass stops it; what the argv must prevent, and now does, is git
writing on the probe's behalf. And the reading clause says repository rather than directory on
purpose: git's discovery normally selects the containing repository, which is the correct answer
for a session in a subdirectory and the wrong one for a session under a `$HOME` that is a repository.
That selection also trusts local metadata: a gitfile can select external metadata, and
`core.worktree` can redirect the contents compared against the discovered index. The boundary does
not promise that those contents lie beneath the session directory or the discovered metadata.

### The committed-file read (project check scripts)

A Claude Code session that ran `pnpm typecheck` or `make lint` is read as having run a check when the
project's own `package.json`, Makefile or justfile says that script is a known test or lint runner.
The agent can write those files, so Compass reads them from git as a commit held them, not from the
work tree alone. This is a second command family in `git_status.py`, not the probe, and the probe's
own contract above is unchanged.

Four read-only subcommands, each behind `-c core.fsmonitor= -c core.hooksPath=/dev/null
--no-optional-locks`, through the same resolved executable and scrubbed environment as the probe:

- `rev-parse --show-toplevel`, in the session's directory;
- `rev-list -1 --first-parent --before=<ISO date in UTC> HEAD`, in the toplevel;
- `ls-tree -l -z <commit> -- <names>`, naming at most the seven declaring files;
- `cat-file blob <id>`, for each regular file of at most 256 KiB that the listing returned.

Every argument is a constant, an object id the module checked as hex, or a name that matched a closed
pattern, and the environment sets `GIT_NO_REPLACE_OBJECTS=1`, so a replace ref cannot swap a blob
for the bytes the work tree now holds. None reads the index, runs a filter or an fsmonitor, or writes. Measured 2026-10-27:
`--before=<digits>` is not a timestamp (git matched a commit newer than the bound), which is why the
date is written out. One five second deadline covers all four, and a failure means no declarations,
never a guess.

What bounds the content: only the toplevel of the work tree the session began in; a link or special
file in the commit's tree is refused by its mode, and one in the work tree by `lstat` before any open,
which is non-blocking and refuses a link, so a FIFO cannot block the read; the work-tree file must
equal the commit's blob for the declaration in question, one script, target or recipe at a time, so
a session that rewrote a script's body leaves that script a command while an unrelated later edit, a
dependency bump, leaves the others alone (a package.json keeps its scripts through a change to its dependencies, version or other
publishing fields, and loses them all through a change to tool configuration such as `jest` or `eslintConfig`; a Makefile or justfile loses
every declaration through any change outside its recipes, such as an assignment, `export` or `.IGNORE`), and a cached read is checked against the work tree again before it is used; a recorded
write by a write tool withdraws that kind of file even if the session restored it. `make` reads the first of
`GNUmakefile`, `makefile` and `Makefile`, and so does this read. A file over the
cap, with more than 5,000 lines, with a line over 4,096 characters, with more than 500 scripts, that does not parse, or that is a Makefile using `include`,
conditionals, `define`, `.ONESHELL` or a custom `SHELL` adds nothing, and `--diagnose` lists it by
path and a closed reason. The commit is the newest first-parent commit of HEAD no newer than the
transcript's first record, since Compass does not record the commit a session began on. Workflow `run:`
steps are not read.

Nothing read from these files leaves the machine. The script bodies are never published, shown or
sent; what is published is the session's own command line, masked and clipped as any check's is, which
the vendor rule of [the command ruling](docs/design-reading-a-session.md#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor)
already covers. `--no-git` stops the read, and the scripts read as commands again. The residuals are
the probe's: a repository can carry configuration of its own, and an edit made by a shell command and
put back before the session ended is the one change neither the recorded write nor the comparison sees.
One more is accepted. The base commit is the newest one whose commit date is no later than the
session's first record, so a backdated `GIT_COMMITTER_DATE` can make a script the session wrote look
committed. That needs a deliberate act on the reader's machine, and a session that wants a false pass
can already type a runner from the closed list, so no skew check between author and committer dates is
made: a rebase makes the same skew honestly. [The ruling](docs/design-reading-a-session.md#amended-2026-10-28-owner-a-declaration-is-compared-one-script-at-a-time)
and [the one before it](docs/design-reading-a-session.md#amended-2026-10-27-owner-a-projects-own-scripts-are-tier-2-checks)
hold the rest.

### The reader's list of check commands

A reader can list commands that are checks for a project, in one file in the Compass home,
`compass-project-checks.json`. It is a plain file read to a 64 KiB cap, the way the other stores are, and
nothing is run to read it. The agent can write files in a repository, and a listing makes a command count as
evidence, so a `.compass` folder inside a repository is never read. A recorded write by the session to a file of
that name withdraws the listing for that session, and the page says so. So does a shell command that names the
file and is not only a read of it: a redirect, a `cp`, a `tee`, or an interpreter's code, including code sent
to it through a heredoc, a here-string or a pipe. A `cat`, `grep`, `head` or `wc` of it does not, nor does a
pure viewer such as `jq`, and neither does running a listed script. A listed script follows the same rule.
What this does not see is a write that builds the path indirectly, through a script or a variable. A listed
script named by a relative path counts only from the project's root and only when the session did not write
it. An entry that is a shell builtin, cannot fail, only reads, writes files or is not one plain command never
counts, so a listing cannot turn `echo ok` into a pass. Nothing read from the file leaves the machine; the
session's own command line is published as any check's is.
The rulings, [the listing](docs/design-reading-a-session.md#amended-2026-10-27-owner-a-reader-may-list-a-projects-checks)
and [what counts as a write](docs/design-reading-a-session.md#amended-2026-10-28-owner-a-read-of-a-listed-file-is-not-a-write),
hold the rest.

## Reaching a session's terminal (the focus command)

One feature asks the operating system to put a window in front of the operator. Compass already
knows where each session runs; when the reader clicks through to a session that is waiting on them,
the server runs one bounded command that raises that session's terminal, so the hunt across tabs
ends in one move.

### What runs, exactly

The command is a literal argv per named case, or there is no focus. A session matching no named case
is not focused, and the reader is told that rather than shown a control that does nothing.

Each argv is constant except for its target fields, and every one of those is substituted into a
fixed position rather than concatenated. No shell, no interpolation, and nothing from a request body
reaches any position. The tmux case carries three such fields, not one, and the grammars section
below states each one separately. Every command runs with stdin closed and under a timeout. A
failure is reported to the reader as a focus that did not happen, and never retried.

No working directory is set. The command does not run inside the user's repository, which is what
keeps Scope's repository-execution sentence meaningful rather than sidestepped.

### The named cases, and why the list is this short

Two arrangements are candidates today, because identification was measured for exactly two: a
session in a bare macOS Terminal.app tab, and a session in a tmux pane. The identifier differs by
harness even within one arrangement. A Codex hook keeps the controlling terminal and reads it
directly; a Claude hook does not, because its stdin is the payload pipe, so the device has to be
read one level up off the harness process. In a pane neither works and tmux's own client device is
what finds the window.

**One arrangement is now a named case and the other is not, and the difference is what was run.**
The socket-raise capture recorded that `switch-client` on a named socket moved the client it
was told to, with a negative control that held still recorded first. So the tmux socket case is
named, and it is what ships. The Apple Event case is not. The probe ran its arms and the one that
decides it, a daemon whose launching window has been quit, came back inconclusive: it moved a tab
but its two responsible-identity fields were null, so the record cannot say who issued the raise.
Until that is answered no Apple Event case may be named, and the paragraph below is why the bar is
set there.

This is the part most easily read too generously.
**The identification capture measured which identifier finds a terminal. It did not raise one.**
The capture says so in its own words: the lookup counts a tab and never activates one. So a raise command becomes a named
case only once it has been run and recorded, one case per platform, per multiplexer and per harness
where they differ, the way Usage quota reads requires a vendor's endpoint to be named before it
ships. A section listing commands nobody has run would repeat the failure of documenting bounds the
code will not accept.

**A tmux raise is two commands in two mechanisms, and the section admits that rather than hiding it.**
Selecting the pane is socket IPC to the tmux server; bringing the window that hosts the client to
the front is an Apple Event to the emulator. They fail independently, and the first is worth shipping
without the second: a selected pane in a client the operator then switches to by hand is the whole
value on a machine where the terminal is already visible. What the section forbids is reporting the
second as done when only the first ran.

**The two mechanisms carry very different permission costs, and the difference is measured.** The
socket path needs no operating-system permission at all. The Apple Event path is checked against the
Automation privacy permission, which macOS attributes to the *responsible* process rather than the
caller. Measured on the running daemon: after a double fork, a `setsid`, and three days re-parented
to `launchd`, its responsible process is still the Terminal window that launched it. So the sixteen
successful `osascript` calls recorded in the identification capture are that application automating
itself while its launcher is alive, which is an exemption rather than a grant.

The launcher outliving the daemon is not the shipping case; the daemon exists to outlive it. What
happens then is unmeasured, and the failure it risks is silent: an unbundled, ad-hoc-signed
interpreter carries no usage description, so a refused Apple Event returns an error the operator
never sees and cannot grant from the Automation pane. **No Apple Event case may be named until that
arm has been run**, and the socket case is not blocked behind it.

Linux and Windows are unmeasured, and the capture records them that way. Earlier desk research
suggested Wayland may not permit a background process to raise a window at all, and that Windows
Terminal has no documented way to focus a tab. That is research rather than measurement and this
document does not rely on it: both are simply not named cases, and either becomes one the same way
the macOS cases do, by being run and recorded.

**Not a named case means no target is recorded there, and that is enforced where the target is
stored rather than left to the raise to discover.** The device grammar below anchors `/dev/` and
admits no separator after it, so it refuses `/dev/pts/N`, which is the client device of every
terminal emulator, every ssh session and every mux-inside-mux client on Linux and the BSDs. A run
that recorded targets there would publish a focusable control for the ordinary Linux case and spend
two subprocesses answering false every time it was clicked, which is precisely what "A session
matching no named case is not focused, and the reader is told that rather than shown a control that
does nothing" forbids. So recording is gated on the platform the case was measured on, and
`focusable` is false on every other one. iTerm2 is unmeasured for the plainest reason, that it
is not installed on the machine that took the capture.

### The target, and what makes it safe to pass

The target is a **record shaped by its named case, not a single string**, and each field carries its
own grammar. The first draft of this document required every target to match
`^[A-Za-z0-9._-]{1,128}$`, the grammar `GET /api/observe` applies to a harness key and a session id.
That was wrong in a way that mattered: a tmux pane id is `%3`, and `%` is not in that class. The one
case needing no operating-system permission could not have shipped under it, and re-adding the `%`
in the argv builder is exactly the concatenation the previous section forbids.

So the grammars are per field, and each is as narrow as its field allows:

| Field | Grammar | Refused examples |
| -- | -- | -- |
| tmux pane id | `^%[0-9]{1,9}$` | `%3; rm -rf`, `-%3`, `%`, `%3 %4` |
| tmux socket name | `^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$`, passed as `-L`, a name and never a path | `-L`, `../x`, `/tmp/s`, `.hidden`, an empty string |
| controlling terminal device | `^/dev/[A-Za-z0-9][A-Za-z0-9._-]{0,119}$` | `--dangerously-skip-permissions`, `; rm -rf ~`, `../../etc/passwd`, `/dev/..` |
| tmux server pid | `^[0-9]{1,10}$`, compared and never passed as an argument | `-84321`, `84321;x`, `84321,0`, an empty string |

Every field is substituted into a fixed argv position and never concatenated, and a field failing
its grammar is not a raise.

**Each grammar refuses a leading dash in its own first character class rather than in a sentence
beside it, and that wording is the lesson of a reproduced command-injection defect.** An earlier
version shipped
`^[A-Za-z0-9._-]{1,64}$`, whose class contains a dash with nothing anchoring position 0, and review
reproduced a poisoned transcript filename turning a copied command into one that disables a
harness's permission checks. The first draft of this table repeated the same shape twice, and it was
caught only by running the patterns against the values the table claimed they refused. A raise puts
that class of value in an argv position rather than on a clipboard, so a prose promise that the
grammar does not keep is worse here than nowhere.

The device grammar anchors the literal `/dev/` prefix rather than allowing a path and checking it
afterwards, so traversal is refused by the shape rather than by a later resolve: no member of the
class after the prefix is a separator, and a leading dot is refused, which is what excludes
`/dev/..`.

Where a platform path builds a script rather than an argv, the field passes through the same
escaping the native notifier applies, and its grammar still runs first. **That is an escaping
precedent and not a permission one, and the difference decides what may be claimed.**
`notifications.notify_mac` runs `display notification`, a StandardAdditions command with no
`tell application` block, so it is never checked against the Automation privacy permission. A macOS
focus case would be the **first** Automation-checked call in this codebase, not the second, and
nothing about the notifier working says a raise will.

The record is derived from a session Compass observed, and reaches the runtime through an
authenticated event rather than through the focus request. That is the honest statement, and it is
narrower than the first draft's "never taken from a request body": on the only measured path the
identity arrives in a hook POST to `/api/events/<harness>`, which is a request body, from a process
Compass does not control. What bounds it is the capability on that route, which holds a forger to
the same operating-system user. The focus request itself names a session and never a target.

### The lookup is done at raise time, and an ambiguous answer is not a raise

Two measured facts make this a bound rather than an implementation note.

The device is not known to hold still. The identification capture's verdict field is named
`identifier_shape_held_still` and claims exactly that: two devices mask to the same shape, so the capture establishes that the
readings agree and deliberately leaves unmade the claim that the device itself stayed put. The case
where it demonstrably moves is tmux, where detaching and reattaching from another tab moves the
client device inside one session. So a target is resolved at the moment of the raise and never
cached across a session's life.

A device does not identify one window. macOS recycles the device, and the capture caught it: in one
arm three Terminal tabs matched a single device with one of them busy, because finished tabs still
held a device macOS had handed out again. A lookup returning more than one live candidate is
ambiguous, and an ambiguous lookup does not raise. Picking one would be the same failure as the
naive readings below, arrived at from the other direction.

A session with more than one attached client is refused. This is the third decline rule and the one
no lookup prevents: a target can be correctly resolved, unambiguous, and the only live candidate,
and raising it still takes the view away from every other client attached to that session. On a real
machine that is another person, or another agent. The rule is therefore about who else is watching
rather than about whether the target was found, which is why it sits beside the ambiguity bound and
not inside it.

Refusing is the operator's ruling of 2026-09-06, taken over the alternative of raising anyway and
disclosing it on the control. The reasoning recorded with it: a reader often cannot know who else is
attached, and a disclosure they clicked past is not consent from the person whose view moved. The
cost is that the shared-session case is not served at all, and the section says so rather than
leaving a reader to discover it.

**The rule is decided on one command and enforced by the next, and the gap between them is named
rather than narrowed.** `list-clients` answers, the count is decided, and `switch-client` is spawned
about six milliseconds later: measured at a 6.1 ms median and a 7.4 ms maximum over ten runs, that
being server-side client spawn rather than the 0.05 ms of Python between them. A client attaching
inside that window is raised anyway. tmux offers no conditional switch, and closing the gap would
mean a fourth command (a server-side `if-shell -F '#{session_attached}'`), which the "a command
other than one of the named cases" clause forbids outright. So the bound is stated the way the
`core.fsmonitor` hazard and the Apple Event arm each are, and the violation clause below measures
what the lookup reported rather than a state of the world this feature cannot hold still. The worst
outcome in that window is another attached client's view moving; nothing is escalated, disclosed or
written.

### What is never done

Nothing is typed into a terminal. No keystroke, no text, no newline, by any path. The ask lane's
direction invariant is unchanged by this feature, and any implementation reaching for `send-keys`
contradicts it outright.

No harness store is written. No file inside the user's repository is read or written. No native
permission prompt is answered, and no agent session's state is altered: the conversation is
untouched, no turn is started or stopped, and nothing is typed.

**What a socket raise does change is the multiplexer session, and an earlier draft of this document
denied it.** It read "the window moves, the session does not", which is false of the only mechanism
this feature ships. `tmux switch-client` resolves the pane to its window and moves the tmux
session's current window; every client attached to that session displays the change. The socket-raise
capture measured it in both positive arms, and reproduced it outside them by steering one client and
watching the other follow. The sentence is corrected rather than softened, because the bound below
rests on the mechanism being described accurately.

The raise reads nothing back: its standard output is discarded unread, so no pane content, no window
title and no pathname enters Compass.

**The two lookups that precede it do read, and saying so is the point.** The shared-session rule and
the ambiguity rule cannot be enforced without asking tmux which session a pane belongs to and which
clients are attached to it, so a section forbidding all reading would forbid its own bounds. What
those two commands return is bounded, held to the same grammars as any other field before it reaches
an argv position, used only to build the next command, and then dropped: none of it is stored,
published, logged or echoed to the reader. An earlier draft of this section said output was discarded
rather than parsed without qualification, which was false of the mechanism the same document
mandates.

### What the named case runs

The tmux socket case is three commands on the socket the session reported, in this order, or there is
no focus:

    tmux -L <socket> display-message -p -t <pane> '#{pid} #{session_name}'
    tmux -L <socket> list-clients -t <session> -F '#{client_tty}'
    tmux -L <socket> switch-client -c <client tty> -t <pane>

The first names the session and the server, and an earlier draft claimed less carefully that it
"proves the pane still exists". It proves that *a* pane with that id exists in whatever server holds
that socket name now, which is not the same pane. **A pane id is an ordinal on one tmux server, not
a name.** Kill the server, start another on the same socket name, and `%3` is somebody else's pane
in somebody else's session: reproduced on tmux 3.7c, where the second generation re-issued `%0`
upward and a raise on the stale target moved an attached client onto an unrelated window and
reported success. That is the misdirected raise Known and accepted names, arrived at without any
lookup failing. So the pid the server reports is compared against the pid that reported the pane,
and a mismatch is a decline. It costs no extra command, and it is also what makes a socket name that
resolves on a *different* server of the same user (the hook and the daemon need not share a
`TMUX_TMPDIR`) a decline rather than a raise on that server's pane.

The second is what the two decline rules are decided on: no client attached is nobody to raise for,
and more than one is the shared session this document refuses. **It is counted by lines, not by
values.** `list-clients` prints one line per attached client, and a control-mode client (a
`tmux -C attach`, which is what another agent driving the same session looks like) reports an empty
`#{client_tty}`. A reader that dropped empty lines would count two attached clients as one and raise,
which is the shared-session case this document refuses outright. A client the device grammar cannot
name is then a separate decline, decided after the count, so such a client is refused rather than
invisible. Only the third moves anything.

### What the command can still cause

This section does not claim the command executes nothing but itself, and the reason is recorded
rather than assumed. The git probe's contract used to carry the stronger claim, that it "neither
writes there nor executes anything the repository supplies", and DEC-11 retracted it because a
reproduction falsified both halves: hashing a tracked path whose committed attributes named a filter
driver installed four hooks inside the repository and ran the driver, through a path the probe's two
flags were never written against. A third flag now closes the write; the invocation is stated as a
residual, because no flag closes it. The general lesson is the one this feature most needs. A
bounded command can still cause a program to run through a path its bounds never contemplated.

So the honest statement is narrower. A multiplexer and a window manager are programs the operator
configured, and what they do when asked to raise a window is theirs. That is the same trust already
extended by running them, and it is the `core.fsmonitor` hazard in smaller form. Naming it is what
keeps this section from inheriting an optimism that has already been shown to be wrong once.

### Who may trigger it

The operator's own action, and nothing else. The route is a POST carrying a per-run capability, so a
document navigation cannot take this path and a local process without the token cannot either.

**The capability is minted for this feature and delivered to the page, and saying so is the point.**
The first draft said the route carries "the per-run capability `POST /api/events/<harness>` uses",
and that was unsatisfiable by the caller the same sentence names: nothing under
`compass_runtime/web/` knows about tokens, the page makes two `fetch` calls and one `EventSource`
with no header among them, and the per-run tokens live only in the state file at mode `0600`. It was
also the wrong token. The per-harness capabilities are derived per harness, so the token that would
focus a Claude session is byte-identical to the one `POST /api/events/claude` accepts, which is the
power to forge that harness's lifecycle state. Handing the browser that token to raise a window
would be a strictly worse trade than the raise is worth.

So focus gets **its own consumer key**, and it is delivered by injecting it into the served document
where the page bytes are handed to the server rather than by baking it into an asset. That seam
matters: the page's bytes are verified against `react.integrity.json` at load, and a token in an
asset would break that check and make them non-deterministic. Injecting after the load leaves the
verified bytes untouched.

Both halves of that matter and neither is decoration. A GET would repeat a gap this repository has
already been bitten by: an attacker page that gets the browser to open a Compass URL in a tab reads
nothing back, and the "a cross-origin document cannot be read" reasoning does not cover the side
effect. On the quota fetch that side effect was a credential read. Here it would be a window
appearing on the operator's desk.

**What the capability separates, stated exactly, because the first draft claimed more than it
buys.** Loopback is not a per-user boundary, and the token rides in the served document: any other
account on the machine can `GET /` and lift it, so against that account this route stands where
`/api/dismiss` does. What the capability actually separates is a page from a document navigation and
from a local process that never fetched the board. The absence of per-user isolation is a documented
exposure of the whole server rather than something this feature introduces or repairs, and Known and
accepted below says so in the same words.

A rate ceiling and an in-flight gate, so a repeated or looped request cannot repeat the raise. The
route's check order is deliberately **not** the one `POST /api/events/<harness>` uses, and the
difference is the security property rather than an inconsistency. That route answers an unsupported
harness with a 404 before consulting the capability, because a harness name is public. **A session id
is not.** So here the capability is checked first, then the ceiling, and the session is looked up
last: to a caller without the token a live session and one that never existed are byte-identical
403s, and the route is not an oracle for which sessions the board holds. The focus route emits no
404 on any path: an unsupported session is the same 200 `{"focused": false}` as any other
unfocusable one, and the feature being off is a 503 rather than a 404 because it is a run-wide fact
that leaks nothing about any session, where a 404 would read as a build too old to have the route.

The ceiling is claimed after the body is read rather than before it. The body read is blocking and
carries no socket timeout, so claiming a process-wide one-slot gate ahead of it let a peer that sent
a length and then nothing hold focus shut for as long as it kept the socket open. Nothing in the
body distinguishes one session from another, so reading it first adds no oracle, and the gate still
precedes the raise, which is what "cannot repeat the raise" asks for.

### What is published, and what is written to disk

The response is a single boolean saying whether a focus happened: true only when the raise command
itself exited zero, and false alike for a raise that was attempted and failed and for one that was
never attempted at all, so a declined lookup and an unknown session are indistinguishable from a
failed command. No target identifier, no pathname and no window title is echoed. Nothing is written to disk by this feature, and nothing
leaves the machine.

### The off switch

`--no-focus`, and one other flag turns it off as a side effect. The capability comes from the
observation coordinator, which does not exist under `--no-events`, so that flag disables focus too.
A reader of this line would not otherwise have that fact, and a feature with an undocumented second
off switch is one nobody can reason about.

The flag disables the feature for a run, and it mirrors `--no-git` at every one of that flag's sites, including the branch that forwards flags to a respawned daemon, so a restart cannot
re-enable a focus command the operator disabled. With the feature off no command runs at all and the
control does not render.

### Known and accepted

The Claude Code CLI that Compass starts for a reading, a summary or the Live monitor is told not to
persist a session, but it keeps its own local state under `~/.claude`, which Compass neither writes nor
prunes and has not measured. A press passes redacted session text through it once. The Live monitor
passes the recent window through it about once a minute for as long as the switch is on and the session
is viewed, so the same exposure repeats at that cadence. It is accepted rather than solved, because the
CLI's own storage is outside what Compass controls, and the switch, Pause model calls and the
20-minute question are what bound how long it repeats. [The Live monitor](#the-live-monitor) owns the rest.

A row's attribution is unverified, as the ask lane's already is. A forged registration cannot make a
window appear, because the target comes from a collector rather than from a request, but a reader
who clicks is trusting a row Compass measured rather than one a session proved.

Raising a window is the first thing Compass does that it cannot undo and that is visible outside
Compass. A raise that lands on the wrong window puts a keyboard in front of a session the operator
did not mean to reach. The identification capture measured how that happens: for a session with no
controlling terminal at all, both obvious readings report a terminal, and it belongs to somebody else. So a
lookup that cannot identify a terminal must decline rather than fall back, and "the first ancestor
with a tty" and "an emulator variable is set" are both named here as refused readings.

### Violation

A violation of any boundary in this section is a security bug: a command other than one of the named
cases, a field reaching an argv position without passing its own grammar, any field beginning with a
dash, a target field concatenated into an argument rather than substituted into a fixed position,
an Apple Event case named before its arm has been run, a raise reported as done when only the
socket half of it ran, a keystroke sent into any terminal by any path, output read back or published, a working
directory set on the command, a focus triggered by anything but an authorized operator action, a
focus while the feature is off, a respawned daemon that re-enables it, a target resolved once and
reused rather than resolved at the raise, a raise on a lookup that returned no terminal or more than
one live candidate, a raise on a lookup that reported more than one attached client, or any read or write inside the user's repository.

## Usage quota reads (the quota fetcher)

The quota feature sends credentials but no session content. When the usage feature is on, the server polls each
supported vendor's usage endpoint so the dashboard can show quota windows: how much of the 5-hour
and weekly limits is used and when they reset, or for a vendor that meters spend rather than
requests, how much of the monthly billing period's allowance is used and when the cycle ends.

What is sent: the vendor's own OAuth access token, read from where the harness keeps it (the macOS
Keychain, or the harness's credential file on other platforms), carried in the request's
authorization header. Nothing else. No transcript content, no prompts, no paths, no project names,
no machine identifiers. What comes back is quota numbers: window utilization, reset times, and
per-limit entries. Session data never appears in either direction.

The endpoints, named exactly:

1. Anthropic (Claude Code, and any harness signed in with the same Claude subscription):
   `GET https://api.anthropic.com/api/oauth/usage` with the `anthropic-beta: oauth-2025-04-20`
   header.
2. Cursor: `POST https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage` with an
   empty JSON body and two headers, the bearer authorization and `Content-Type: application/json`.
   This is the RPC the Cursor CLI itself calls for its own `/usage` command, against the backend the
   CLI's config records. The credential is the session token in the macOS Keychain under the service
   name `cursor-access-token`. Read this next part before trusting the name: Cursor stores the
   identical value under `cursor-refresh-token`, so unlike Claude's quota-scoped token this one can
   also mint new sessions. Compass sends it as a bearer token and never exchanges it, and the
   never-refreshed rule below is what keeps that true. macOS only, because that is the only platform
   where the token's location has been verified; elsewhere Cursor is absent from the band rather than
   read from a guessed path.
3. Codex: no endpoint. Codex writes rate-limit snapshots into its own session files, and Compass
   reads them from disk like every other store.
4. Copilot: no endpoint. Copilot records its own per-request AI Unit consumption in a local session
   store, and Compass reads that from disk. Its remaining entitlement is not published locally and
   is not fetched.

No other vendor is polled. A new vendor's endpoint must be named here before it ships. These
endpoints are not documented for third-party use: a vendor can change, break, or block them at any
time, and a failed poll means an empty tile, never a retry storm.

Token handling is read-only, one way, and never expands:

- The token is never refreshed. Refreshing from outside the harness can race the harness for its
  own session. A token the harness would refresh by itself, or one a vendor refuses, switches that
  vendor's usage display off and says which of the two happened; the remedy always belongs to the
  harness. This rule is what bounds the Cursor credential noted above: a value that could mint
  sessions is only ever presented as a bearer token, so the extra capability is never exercised.
- The token is never written to disk, never logged, and never served. `/api/data` and every other
  loopback endpoint must not carry it, in any form.
- Reading the token adds no write access anywhere. Harness stores stay read-only.

Consent and the off switch: the feature is on until the reader turns it off, and the line saying so is
on screen whenever it can act. Wherever the quota windows are drawn, on Session operations below the
session groups and in the Console rail, one line says the quota is read with the Claude Code and Cursor
logins on this machine and that no session content is sent, beside a Turn off button. Turned off, the line
says so and offers Turn on. `--no-usage` disables the feature for a run regardless of the stored setting.
With the feature off, Compass's network surface is exactly the three loopback-bound kinds of component
described above, and nothing is fetched.

**Amended 2026-10-27 (owner): on until turned off.** The page now adds `usage=1` to every request unless
the stored answer is `declined`, so an unanswered page, an unrecognisable stored value and storage the
browser will not read all fetch. The four-sentence question that used to stand before the first fetch is
gone; the one line above replaces it. Nothing else in this section moved: what is sent, the endpoints, the
token handling, the five-minute floor, the server's refusal of the parameter on a document navigation, and
`--no-usage` are unchanged. The paragraph below records the rule this replaced.

**Answered, not assumed, a change of 2026-09-04, replaced 2026-10-27 by the amendment above.** The mechanism is the `usage=1`
parameter: the server fires the fetch for no request that omits it, and the page adds it only while
the stored answer is `granted`. So an unanswered disclosure reads no credential and makes no
request, and neither does a declined one, and an unrecognisable stored value counts as unanswered.
The server enforces its own half rather than trusting the page: it ignores the parameter on a
document navigation, so a cross-site link that opens `/api/data?usage=1` in a tab is served the
body and arms nothing. That check is what makes the sentence above a property of the system and
not only of the page's URL builder.
This paragraph previously described the banner as shipped when the page had no banner, no configure
control and no stored setting at all: the next-UI promotion had dropped them, the page consequently
sent the parameter never, and nothing failed because nothing bound this paragraph to the page. The
promise was true only because the feature never acted. Restoring the surface and making the page
ask, in that order, repaired it. `frontend/src/capacity/UsageConsent.test.tsx` and `frontend/src/api/bootstrap.test.ts` bind the builder and the mount, and
`test_quota.NoFetchWithoutConsentTest` binds the server's refusal, so neither half can go missing
again without a red test.

Polling posture: responses are cached, and at most one request per vendor is made every five
minutes. No polling happens while no dashboard page is connected. `--diagnose` never triggers a
fetch; its output stays a report of local paths only.

A violation of any boundary in this section is a security bug: a request carrying anything beyond
the token, a token reaching a log or a loopback response, a refresh attempt, an unlisted endpoint,
or a fetch with the feature off.

Not every harness needs that request. One publishes its own quota to a user-configured command:
Antigravity pipes a state payload, including a `quota` object, to whatever its status-line setting
names, and a user who points that at `POST /api/usage` gets the same display with no credential
read and no outbound request at all. That payload also carries an account email and a transcript
path, so the receipt is never stored or served as it arrived: only the derived window percentages
and reset times are kept, built into a fresh record field by field. `--no-usage` stops this too: the
quota fields are dropped before storage, so nothing is retained and nothing reaches the band, and
the request still succeeds so a status line never sees an error. The dashboard's own switch is
narrower, and deliberately so. It governs the outbound fetch and the display, which is all it can
govern for a harness that publishes its quota locally: with it off, a pushed receipt is still kept
and still served on the loopback port, exactly as a disk-read tile (Codex, Copilot) is. Withdrawing
retention for a run is what `--no-usage` is for.

## Light harness usage (asking a harness a bounded question)

Compass was built to sit outside harness usage: it watched, and it spent nothing. DEC-14 changed
that on 2026-09-04, because several of the answers the dashboard most wants to give cannot be
derived from a transcript by rule (whether a quiet session died or finished, what happened while
the operator was away, what a session's actual goal is rather than its opening instruction), and
each of those shipped withholding its answer instead. Compass may now ask a harness a bounded
question and consume a little of the operator's own capacity doing it.

The observer model is the first implementation of this pathway, deriving a session's goal line, and
the reading lane is the second, reading a session against the words the reader saved against it.
The Claude Code reading producer is the third: built behind its own gate, which the owner's
acceptance opened on 2026-10-02 without a passing check.
Each has its own entry below naming what it sends, what it asks, and what it caps. Future harness
callers need their own entry.

What makes this different from every other boundary in this document: it is the only one that sends
the operator's own words off this machine. The quota poll carries a token and numbers. A harness
invocation carries session-derived text, which is why invariant 1 names it separately rather than
widening the quota exception to cover it. The consent below is not the quota fetch's: a call a
reader's action starts runs only on that action, and an unasked check runs only under
`--unasked-readings` and DEC-18's preconditions. Every kind of call announces itself the first time
it runs. Pause model calls stops readings, goal summaries and session summaries; Turn off
summaries stops session summaries alone. `--no-observer-model` refuses all of them for the run, where `--no-usage` is a startup flag
alone.

The bounds, all of which hold together:

- Opt-out, with a notice, for a call a reader's action starts. Ruled 2026-10-19 by the owner
  ([DEC-28](docs/design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts));
  this replaces the former "Opt-in, and off until answered" bound for reader-started calls.
  - What it covers: every model call a reader's action starts, and nothing else. That is a session
    summary (made when a finished session is opened, or on Update summary), a reader-requested
    Analyze drift (its consent step goes), Claude Code tool output on such a reading (included by
    default), and a Codex goal summary (on by default). Such a call runs without a prior question.
  - What it does not cover: unasked drift checks. No reader action starts them, so they stay off by
    default behind `--unasked-readings` and DEC-18's preconditions. Codex also requires an explicit
    grant for the current destination; Claude Code uses the owner's acceptance without a separate grant.
  - The notice. The first call of each kind on this machine shows a non-blocking notice naming
    what is sent (the words, and tool output where it is included) and to which provider and
    destination, with a one-press off switch beside it. A changed destination or a wider content tier
    shows the notice again, naming the new destination, rather than a blocking Allow. It is disclosed this way, and
    not left silent like the quota fetch, for a stronger reason: this one spends their capacity
    rather than reading a number.
  - The master switch. Pause model calls stops Analyze drift, goal summaries and session summaries
    until Resume model calls. Compass stops sending session text to Claude Code or Codex, so it
    uses none of your tokens, and stays paused until you resume. An answer of off already stored
    is kept across upgrades. A running summary stops at its next part and a spawned call is cancelled.
    Turn off summaries affects session summaries alone. While paused, that control stays visible
    and disabled with "Model calls are paused" beside it. Pause and Resume never change the stored
    summaries answer; resuming restores the switch exactly as the reader left it.
    `--no-observer-model` still refuses every model call. `--allow-tool-output` and
    `--observer-model` are accepted no-ops for one release.
- Goal summaries are on by default. The browser still sends `observer_model=1` on the focused
  refresh that the reader starts; a document navigation never authorizes a call. Quota consent
  does not authorize sending transcripts. This parameter is not per-user authentication: a local
  process can imitate it. The per-session in-flight gate and prompt and time bounds limit that
  exposure. Pause model calls stops goal summaries too. No per-run event capability is implemented
  on this route. Goal calls are not charged to the 100-attempt rolling cap below and have no rolling
  cap of their own: what bounds them is one call in flight per session, the refresh guards, and a
  focused refresh reaching only its session and up to three active child sessions.
- The operator's own harness, never a Compass credential. Compass invokes the harness the
  operator has already installed and signed in, non-interactively. It holds no API key, reads no
  new secret, and adds no endpoint to the list in Usage quota reads. Nothing about token handling
  changes, because there is no new token. A future feature that wanted to call a vendor API
  directly would be a different decision needing its own endpoint entry there.
- Redacted before it leaves, and bounded after. What is sent is prompt-derived text, so it goes
  through `records.redact_secrets` first and the bound second, the same order and for the same
  reason Published text gives. A key pasted into a prompt must not be handed to a subprocess any
  more than it may be published to the page.
- One bounded question. The generated prompt has a byte cap and the subprocess has a timeout.
  Codex is invoked ephemerally with user configuration and rules ignored, in a read-only sandbox.
  Explicit CLI overrides disable shell execution, hooks, plugins, apps, subagents, browser and
  computer tools, image generation, web search, and automatic project/skill instructions.
  These flags are not a proof of an empty tool set across Codex versions. The installed CLI and
  its provider remain a trust boundary; live tool suppression and provider retention are not
  verified by the dashboard's tests. Claude Code has no read-only sandbox to invoke, so its
  reading call is bounded by CLI flags alone; [its own entry](#claude-code-reading-calls) lists
  them.
- Visible spend. Model metadata records whether a call ran or was refused. Provider token usage
  is not measured by this prototype; it must not present a zero cost as if it had measured one.
- Off switch. `--no-observer-model` disables calls for a run regardless of consent and overrides
  the default-on goal summaries and session summaries. `--observer-model` is an accepted no-op for one release.
  `--no-harness-usage` is an alias for that rollback. The explicit off state
  survives daemon respawn.
  The off switch refuses the unasked lane as well: with it set,
  `--unasked-readings` attaches no lane, starts no reading, and the page reports the lane off.

A violation of any of those is a security bug: an invocation with the setting off, an invocation
with the Codex grant unanswered for an unasked check, a reader-started call whose first run of its kind shows no
notice, an invocation carrying unredacted text, a credential read that this section does not name, tool access
beyond the documented CLI boundary, or an unbounded or untimed call.

What is accepted rather than solved: the invoked harness is another program with its own logging and
its own retention, and what it does with a prompt is outside Compass's control. That is the same
trust the operator already extends to that harness by running it, but it is a real transfer and it is
stated here rather than implied.

### Reader-requested permission and rolling budget

The first Analyze drift press runs and shows a non-blocking notice naming the provider,
destination and content sent, including the agent's words and tool output where included. No prior
Allow is needed. A notice is recorded per kind and provider on this machine; a new destination, a
wider content tier or a tool-output destination the last notice did not name shows it again, and a
narrower press to the same destination does not. Goal summaries use the same
notice mechanism and are on by default on a focused refresh carrying `observer_model=1`.

The answer and notices live under `COMPASS_HOME` (by default `~/.compass`) in
`compass-reading-permission.sqlite3`, shared by tabs and respawned daemons. Pause model calls and
`--forget` store an explicit off, block readings, goal summaries and session summaries, and clear their notices, so after
`--forget` they stay paused until Resume model calls. Resuming shows the notice again on the next call. An off
saved by an older build stays off after upgrade; an old Allow reads as on, including an older
build's Allow given after its own off, which left that off's other rows in place. `--no-observer-model` refuses every model call for the run.

The same SQLite store holds the independent summary answer and ledger described under
Session summary calls, that reading answer, notice rows (kind, provider, destination, content
tier, tool-output destination and time), model-attempt timestamps and, for 30 days, the
random id of the job each attempt was charged to, never session ids or content. A transaction reserves
one of 100 reader-requested attempts in a rolling twenty-four hours before the model starts. Eligibility checks and a known missing CLI spend nothing; a failed
or timed-out attempt keeps its reservation because the provider may already have spent capacity.
Concurrent processes share the transaction bound. A denied or corrupt store fails closed. The page
reports the cap, once it is spent, and the earliest time another attempt can be admitted. Turning permission off,
back on, or forgetting it does not erase unexpired spend timestamps or refill the budget.

The store is created owner-only; SQLite is required for this permission path. Every
reader-started model call (Analyze drift, goal summaries and session summaries) records its notice
there, so without `sqlite3` or a writable state directory each is refused as `store-unavailable`. Deleting the file
manually can reset its budget, as can any other modification by the owning local user. The cap
bounds requests through the HTTP route, not a hostile owner editing their own files.

Legacy explicit Allows remain per provider, bound to the disclosed destination and content tier.
An explicit Allow covers every session routed to that provider.
They govern Codex unasked checks, which require a stored words-only Allow covering today's
destination. The Drift card's "Allow Codex to run unasked checks" toggle deliberately writes or
revokes it through a separate `unasked_grant` body on `POST /api/reading`. It requires the startup
flag, a current provider and destination, a loopback non-navigation press, and refuses while paused
(409 with `model-calls-paused`, the pause kept) or under `--no-observer-model` (503). It adds no route. Revocation deletes coverage without pausing requested readings.
Analyze, an older page's `allow: true`, and Resume never write it. Pause followed by Resume clears
it. Claude Code unasked checks use the owner's acceptance and need no separate stored grant.
The board's `providers`, `words`, `rebind` and `tool_output` retain their explicit-coverage meaning;
reader-started calls use the off switch and notices instead.

The destination is resolved again at a reading job's reservation. If it moved after the press,
the job refuses `destination-changed` before spending or sending. The CLI reads its own settings
again at launch, so a change between reservation and launch is not caught. A changed destination
between presses runs with a new notice. An explicit `allow: true` press still binds the destination
it names: a stale destination answers `409 destination-changed`, and an absent `words_destination`
answers `400 page-outdated` without recording an Allow.

An unnamed destination is `""`: two endpoints Compass cannot name are indistinguishable, so their
move cannot trigger a new notice. This includes every Windows destination and every Codex base URL
under `OPENAI_BASE_URL` or `OPENAI_API_BASE`. An unnamed legacy Allow keeps covering every endpoint
it cannot name, including every destination on Windows. Tool output is not sent where its destination is
unnamed. Pause model calls and `--forget` revoke all providers; schema triggers also clear notices,
other provider answers and grants when an older build writes its legacy off. The 100-attempt cap
is shared between providers and reports `daily-cap` when spent.

Which provider a press reaches is decided before the press, by `reading_route.resolve`, from the
session's harness and this machine. The page shows that route's disclosure, naming the receiver,
its vendor and whose capacity is spent. The route resolves the provider again from the payload's
harness. If the provider the page named is no longer the one that would run, it answers 409 and
writes no consent and reserves nothing; if no provider can read the session, it answers 503 with
the reason. One model runs per press. If its CLI is missing at launch, or the call fails, no other
provider is tried.

A press names the revision its page drew. The route checks it against the annotation store read
from disk under the store's lock, not this process's copy, before the route, any Allow write and
the job, and checks the entry it hands the job again the same way. A save another dashboard on
the same home made in between, or one landing between the check and the job, answers 409
`revision-changed`, so the model never reads words the page did not show.

### Observer model calls

Goal summaries are on by default unless model calls are paused or `--no-observer-model` is supplied.
`observer.CodexGoalModel` sends a generated prompt to the installed Codex CLI, which uses its
own authentication to reach OpenAI. `reading.CodexReadingModel` is the second caller and goes
through the same `observer.codex_exec`, so the two share one set of sandbox flags rather than two
that could drift. These are the paths that can send session content off the
machine. A reading of a Claude Code session is made by Claude Code when `claude` is on the
server's PATH, and by Codex when it is not: Codex then spends the operator's Codex capacity and
sends that session's evidence to OpenAI, and the disclosure before the press says which. A reader-requested reading requires the remembered answer and rolling budget above; an
unasked reading requires `--unasked-readings`. `--no-observer-model` always wins over both. The Live
monitor is a third reader-started path, to Claude Code and on to Haiku only; [The Live
monitor](#the-live-monitor) states what it sends and every way it stops.

Two requests can reach the model. A focused `/api/project-context` refresh can summarize the
focused session and up to three active children whose assignment is unavailable.
`POST /api/reading` reads one annotated session against the words typed against it, and it sends
those words as well as the session's evidence, which is why it carries a disclosure of its own
rather than reusing the observer's.
The evidence includes the reader's own messages in the session's record, and since 2026-10-01 each
is sent whole rather than as its first sentence where the prompt has room (the newest first,
within half the prompt; the rest go by their first sentence): collapsed to one line, redacted by
`records.safe_text`, and cut at 1,000 characters (`project_context.READER_WORDS_CAP_CHARS`, held
again by the ledger's `reading.LEDGER_WORDS_CAP_CHARS`), inside the same 16 KiB prompt bound. That
sends more of what the reader typed than the first sentence did, including any private prose in a
later sentence that redaction does not recognize. The owner accepted that, because a first sentence
dropped the point of a measured correction
([the amendment](docs/design-reading-a-session.md#amended-2026-10-01-a-reading-sees-the-readers-whole-message)).
A goal adopted from one of those messages is sent as that message's whole field too, from the same
half, in place of the goal box's 1,000 characters; the goal stored and shown stays the excerpt
([the amendment](docs/design-reading-a-session.md#amended-2026-10-04-owner-an-adopted-goal-is-read-whole)).
The owner, approving the Analyze drift plan, amended the source lookup on 2026-10-04. A reader's
press can find that adopted source outside the recent transcript tail: a forward scan reads at
most the newest 64 MiB plus the opening 32 MiB under one two-second clock, and retains
at most 4,096 user-message facts. Only the adopted source can
replace the Goal; the other facts do not enter the reading's evidence ledger. The runtime caches
the redacted, 1,000-character fields in memory for at most eight transcripts on its default arm,
keyed by path, harness, session, size and modification time. A reader's press uses the uncached
arm that masks raw separators first. Neither arm writes or publishes the words. The adopted-goal
lookup does not run for a typed goal or an unasked reading.
The same owner amendment also lets a Claude Code or Codex press recover words for listed person messages in
the reading window, through its observed stop, from the latest 32 MiB of the parent transcript.
That uncached lookup verifies each fact id and timestamp and refuses conflicting raw-content fingerprints or
a file changed since collection. A missing or unverifiable source keeps its listed title. It adds
no fact id, stores no words and does not run for an unasked reading. The history and listing bounds
still hold; this is not a whole-transcript evidence ledger. Other harnesses keep their existing
in-tail words.
Since 2026-10-21 the reader's own messages include two Claude Code records that carry no user turn: a
message the reader sent while the agent worked, and the reader's answer to the agent's multiple-choice
question ([the amendment](docs/design-reading-a-session.md#amended-2026-10-21-a-message-sent-mid-turn-and-an-answer-to-the-agents-question-are-the-readers-words)).
Both are sent as any other reader message is: whole, redacted by `records.safe_text`, at most 1,000
characters, inside the same 16 KiB prompt bound, and never stored or published. An answer is its
question's one-word `header` (the agent's label), the answer and any note the reader attached. The
question's text and every option's preview, which are the agent's words, are not read as the
reader's. This sends more of what the reader typed than before, and sends the answer a reader
chose from the agent's options, which is why it is said here; the disclosure's "your messages" is
unchanged because the kind of thing sent is. A pasted image in such a message is never read, only
its text. The queue these messages arrive through also holds background-task notifications, and
only a record whose `origin.kind` is `human` is taken.
A Claude Code press also reads the focused session's person and agent messages back to the reading's
window start instead of from the 400,000-byte tail (2026-10-13, `project_context.press_message_events`,
[the amendment](docs/design-reading-a-session.md#amended-2026-10-13-a-press-reads-the-message-record-back-to-the-window-start)).
The read is backward and memory-only, under the same allowance as the adopted-source lookup: the newest
64 MiB under one two-second clock, a stamp check that refuses a file changed since the press began, and
a stop after sixteen timestamped records in a row older than the window. It keeps the newest 100
messages, the project event cap, and the closing agent message of up to twelve earlier turns with the
reader's message after each, a bounded handful held in memory (2026-10-13, [the amendment](docs/design-reading-a-session.md#amended-2026-10-13-a-press-keeps-the-closing-agent-message-of-each-earlier-turn)).
A message whose text is over 256 Ki characters is not read and counts as an unread region. The prompt
reserves an eighth of its 16 KiB (`reading.ANCHOR_SHARE_DIVISOR`) for those closings ahead of the newest
agent messages, and no entry of another kind is displaced. It adds no content class. The messages it finds are the person and agent messages
a reading already sends, redacted and capped the same way, `for_page` still strips both words fields,
and nothing is stored or retained after the press. Ordinary collection and every other harness keep the
tail, and `CONTENT_VERSION` is unchanged.
The field holding the whole message (`reader_words`) is held in memory for the reading and is
neither stored nor published: the history stores' field allowlists do not name it, and
`/api/project-context` drops it (`project_context.for_page`), so the page still shows the first
sentence and `/api/data` never carried it. One bounded copy is the exception, by the owner's ruling
of 2026-10-01: the focused project context's `prompt_choices` offers up to five of the reader's own
messages for adoption as the goal, each the field clipped to the goal's 1,000 characters, and the
rest of the field past that cap is not published (Prompt-derived text, below). The owner raised that
bound from 240 on 2026-10-27, so a prompt chosen as the goal is offered whole
([the amendment](docs/design-reading-a-session.md#amended-2026-10-27-owner-the-goal-holds-1000-characters)). What the model writes back is a different matter. A
reading's `detail` is the model's own sentence under a cited departure or unfinished-work result,
and it is stored with the reading and published
on the page, as it was before; the model can now paraphrase or quote a later sentence of a message
there, which it could not when it saw only the first. The one copy of the field on disk is an
abstention packet's frozen facts, which stay local under `~/.compass` with the rest of that
packet's prompt text (below).

Amended 2026-10-04 by the owner, approving the Analyze drift plan: "Not reached at this stop"
retains a cited unfinished-work explanation at non-final scope. It uses the existing detail field
and its scrub and bound; it adds no transcript carrier, source class or model destination.
Final readings and claims cannot carry it. The correction copies a fixed unfinished-work sentence,
never this model prose. The [shape contract](docs/design-reading-a-session.md#amended-2026-10-04-unfinished-work)
owns what the result may say.

The original whole-message path had one redaction limit the first sentence did not. The message was collapsed to
one line before it is redacted, so a credential the reader's text broke across a line break becomes
two runs. The part before the break is masked only when it is still long enough to match its shape
on its own, and the part after it has no prefix to match and is never masked, the same
shape-matching residual Published text describes for a control character. Measured on the
documented AWS example key and on a GitHub token shape, each split partway through: neither half was
masked. Before this change the part after the break was on a later line and never reached a model;
it reached the provider. Amended 2026-10-04 by the owner: the reader-requested window lookup now
masks raw prose before folding whitespace, including before rendering command arguments. Default
callers retain the original path. A message's words are also shared out of the prompt budget
rather than taking it: every entry is chosen by its first sentence exactly as before, and the
newest messages replace their first sentence with their words only inside half the 16 KiB
(`reading.WORDS_SHARE_DIVISOR`), counted in UTF-8 bytes. A message whose words do not fit is sent
as its first sentence.

Since 2026-10-03 the agent's own messages are a further class of content a reading sends, by the
owner's ruling that what the agent says is evidence
([the amendment](docs/design-reading-a-session.md#amended-2026-10-03-owner-the-agents-own-words-are-evidence)).
On a Claude Code session each top-level assistant text message in the bounded transcript tail is
an entry of its own; sidechain and meta records, thinking and tool call blocks, and the CLI's own
`<synthetic>` records are not. Its first sentence is the entry's title, and the whole message,
masked as raw prose before it is collapsed to one line, then redacted by `records.safe_text` and
cut at 1,000 characters (`project_context.AGENT_WORDS_CAP_CHARS`), replaces the title inside a quarter of the 16 KiB
prompt (`reading.AGENT_WORDS_SHARE_DIVISOR`), newest first, after the reader's own messages have had
their half. Amended 2026-10-04 by the owner: additional selected agent excerpts may use room left
after those passes, without dropping an entry or exceeding the 16 KiB cap. Complete bounded
records measure the full masked, folded length; a cropped prompt row labels its actual excerpt
length and that total. Neither count is inferred for a legacy record. These counts stay in memory
and are stripped from page responses with the words. That change stayed within the existing
content classes, so it left `reading_policy.CONTENT_VERSION` at 2.

Amended 2026-10-05 by the owner through delegated adversarial acceptance
([the amendment](docs/design-reading-a-session.md#amended-2026-10-05-owner-the-newest-recorded-final-reply-is-read-whole)):
the agent's newest message that its own transcript record marks as ending its turn
(`message.stop_reason` equal to `end_turn`; text alone, a quiet session or a later timestamp does
not establish it) goes whole in place of its 1,000-character excerpt, but only when its complete
quoted row fits the 4,096 bytes of the agent's quarter and the room the reader's words left. It is
chosen among the rows the prompt already selected, so no entry, citation number or older or later
record is added, and it is read from the same file version the press read its facts from, by a
memory-only scan of the complete file, only when it is at most 32 MiB. A larger file cannot
prove an earlier conflicting duplicate is absent and keeps its excerpt with a cutoff note.
A reply that does not fit, a source that moved, a
duplicate or same-time record that disagrees, or a record the source cannot prove final keeps the
excerpt, and the reading's cutoff says so. The agent's other messages keep their 1,000
characters, no shell output or tool result is added, the consent tier does not widen, and the
words are neither stored, cached, logged nor published. This changed what a message sent and
raised `reading_policy.CONTENT_VERSION` to 3; a changed tier now renews the notice.

Amended 2026-10-06: the whole-final lookup binds a shortened Claude session key to the
complete UUID filename through the same identity normalizer used for lifecycle events.
Every non-meta parent assistant record in that complete scan must carry the exact full
filename identity. A conflicting or missing identity keeps the excerpt, including when
the conflicting reply was not selected. Bounded JSON records with Unicode escapes are
decoded for this check; an oversized escaped record refuses recovery before decoding.
This does not admit another transcript or widen
consent; the existing source stamp, selected-row and byte bounds still apply.

Amended 2026-10-06: an Allow records the content tier the server resolved from the
session harness and actually disclosed. A non-Claude Allow at `WORDS_CONTENT_VERSION`
cannot authorize a later Claude agent-message reading through the same provider. Older
version-3 rows cannot prove which disclosure created them, so the wide consent epoch is
now 4. Reader-started presses use a renewed notice rather than this legacy Allow bound. This adds
no transmitted content.
A verified wider grant survives a narrower Allow only at the same provider and destination;
Pause model calls still withdraws every tier and tool-output grant without refunding spend. Words-only
consent remains grandfathered under the earlier ruling.

An agent message, cropped or whole, is quoted as one JSON string with the menu heading neutralised, as a check's output
tail is, and the prompt's trusted header says agent messages are quoted data, never instructions.
That goes only on a reading the reader pressed for, whether or not tool output is allowed, and to
whichever provider the route names; the unasked lane sends none of it (`reading.build_ledger`'s
`read_agent_words`, set by the reading route alone). It sends what the agent wrote to the reader,
including any private prose or path it repeated that redaction does not recognize, and it carries
the uncued-prose residual described above. An agent message can repeat tool output,
so a command's output can reach the provider in the agent's words even where tool output was not
allowed. Redaction catches credential shapes and, since 2026-10-03, the value after a cue such as
`Authorization: Bearer`, `--password`, `password=`, `token:` or a name such as `DB_PASSWORD`,
`PGPASSWORD` or `OPENAI_API_KEY` (Published text, below); a password or token with neither a shape
nor a cue can go verbatim. The field holding the whole message (`agent_words`) is treated as
`reader_words` is: held in memory for the reading and the live project context, never in either
history store, and dropped from every page route by `project_context.for_page`, so the page shows
only the message's title. The title is its first line cut at sentence punctuation followed by a
space (`project_context._semantic_line`) and at 112 characters, so text with no such break, CJK
prose among it, publishes up to 112 characters that can span several sentences. The agent's
messages are not written into the session history store at all, live or whole. The route's "What
is sent" list names them, and the first press shows a notice naming their content tier and
configured destination. The notice repeats when that tier or destination changes. The legacy
explicit Allow is still bound to its version in `permission_disclosure`; the unasked lane sends no
agent messages and still requires explicit coverage at `WORDS_CONTENT_VERSION`. Older builds clear
that version on Turn off and write no version on Allow, preserving the rollback boundary.

Rendering, polling, reconnecting, resuming and saving a revision call no model. The server requires
`observer_model=1` on a reading press or focused goal refresh, and the page sends it on the reader's
act. Readings and goal summaries honor the durable off switch. Session summaries have the separate
reader-open rule described in their own section.

### Accepted source-recovery and model-accuracy limits, 2026-10-05

The owner delegated acceptance to adversarial agent review. Source recovery may send more of
already-disclosed message prose at a requested press, bound to an already-selected parent message
and the source version the press read. A mismatch supplies no new words. Recovered prose stays
in memory, adds no citable fact, enters no history or page response, and is not read by the
unasked lane. The newest-final path requires its content tier in the notice.

The [closed-proof ruling](docs/design-reading-a-session.md#amended-2026-10-05-the-original-closed-proof-proposal-is-retired)
retires that proposal as infeasible, with no verified clearances, and removes it as a prerequisite
for newest-final source recovery. The fresh measurement campaign remains unavailable at this
amendment until its exact protocol and aggregate transport guards are built and reviewed.

This acceptance retains source-fidelity behavior while the expanded-input accuracy gate remains
failed and unqualified. Sanitizing, quoting, provenance checks and CI do not establish truth or
improve model accuracy. A local process may rewrite stored assessment prose: sanitization and
escaping do not authenticate it. The instruction-text guard can reject legitimate quoted text
and is a mitigation, not a signature.

Usage is reported in its actual unit. Engineering launch, wall-time and captured-output limits
do not bound tokens or remaining subscription usage. A CLI dollar-budget flag is not a conversion
to weekly quota. Analyze reservations, qualification allowances and engineering calls remain
separate ledgers; calling work a review does not replenish an exhausted or failed study.
Only loopback peers can authorize a model call, and cross-origin Fetch Metadata is refused.
The response publishes the disclosure and byte cap. The backend does not treat `usage=1` as
authorization to send transcript content. Goal summaries honor the notice and durable off switch. Console sends `observer_model=1` on an explicit focused refresh;
no browser consent card is required. The notice names Codex and its configured destination, and
Pause model calls or `--no-observer-model` stops the call. Passive refreshes never carry the request.

Transcript message content is redacted before extraction can clip credential shapes. The complete
generated prompt, including workflow stage, then goes through `records.redact_secrets` again
before UTF-8 clipping to **16,384 bytes (16 KiB)**. This caps the prompt Compass hands to Codex,
not the CLI's added protocol or system instructions. Redaction recognizes credential shapes;
it does not remove arbitrary private prose. One call per session may be in flight, including
concurrent HTTP refreshes, and a reading takes the same one-in-flight gate per session; both slots
are released on failure. A goal summary has a **60-second** timeout and a reading, pressed or
unasked, on either provider, a **180-second** one. Every model call, the goal lane's, the
unasked lane's and a pressed reading's, runs through `supervise.run`: the CLI leads a process
group of its own (a kill-on-close Job Object on Windows, the child held suspended until it is
inside the job), a timeout kills its process group
rather than only the direct child, and the daemon's own group is never signalled. The limit on
POSIX: a helper that leaves the group, by `setsid` or `setpgid`, is not reached; a Job Object has
no such exit. The group is signalled only while its leader is unreaped, so its id cannot have been
reused by another process, and the call returns only after the child is reaped, so its temporary
files are removed after, never under, a live writer. When neither `waitid` nor kqueue can watch the
exit, the call polls, which reaps the leader, so helpers still in its group after a normal exit are
not swept; a timeout, a shutdown or a Cancel still kills the group, because each kills before the
reap. That has been seen only under forced errors, and a test pins it. On that path a
helper still writing after the leader's exit is not reached at all, whether it was already
writing under the bound or starts afterwards: the poll that sees the exit is the reap, the caller then removes the file, and the helper's writes to
the removed file are bounded by nothing but the disk until the helper exits. Seeing the exit
without reaping needs a third watcher, which is the fix the owner ruled documented rather than
built. On the watched POSIX path, the runner keeps the leader unreaped while it kills the group
and waits for every member to stop, then reaps the leader. It observes group ids and process
states through the native `/bin/ps -axo pgid=,stat=`; it reads no command lines, arguments or
environment, and publishes or stores none of the snapshot. Zombies cannot write and count as
stopped. The probe runs with only `LC_ALL=C` in its environment, never a shell or a PATH-selected
executable. An unavailable probe, an unreadable snapshot or a group still running at the deadline
refuses the call as `unstopped`, even if the leader exited. On Windows, the runner terminates the
Job Object and waits until the kernel's `ActiveProcesses` count reaches zero before releasing it.
Observation and leader reap share the existing five-second bound. A stalled POSIX probe spawn
cannot hold the caller beyond it: the probe runs on a daemon thread, and a spawn that finishes
after the bound is killed and reaped by that thread. An OS call that never returns can leave that
thread pending until the daemon exits. The first failed or timed-out probe ends that call's
cleanup, so a call cannot accumulate concurrent probe workers. The native probe was measured on macOS; Linux's native
probe and Windows's job query are checked by their platform tests. A POSIX host without this native
`ps` command's fields refuses the call rather than assuming its helpers stopped.

A call's output file is bounded on disk as well as on read: the runner checks its
size every 0.01 s while the CLI runs, and once more after its group or Job Object has no live
writer. The unwatchable POSIX fallback above still cannot make that guarantee. Past
**1 MiB** it kills the CLI's group or Job Object as a Cancel does. A reading
records a spent `oversized` attempt; the goal lane falls back as on any failed call and records
nothing. The file can exceed 1 MiB by what the CLI writes in one 0.01 s slice, which is bounded by
disk speed rather than by the limit, and a write already in flight can finish after the kill:
an unpaused writer on an APFS SSD was measured at 41 to 89 MiB
before the kill, which landed 11 to 15 ms after the bound was passed (286 to 600 MiB at the earlier
0.1 s slice). The file is removed after the bounded cleanup. A kill whose group has not stopped within five
seconds ends the call anyway and is recorded as its own withheld reason, which says the process
may still be running. Because a child in its own group no longer receives the terminal's signals,
SIGTERM, SIGHUP and SIGQUIT all unwind through the daemon's cleanup, which shuts the runner (a
spawn after that point is refused, and a reading not yet sent is refused before it is charged) and
kills every supervised group. A SIGHUP or SIGQUIT the server was started ignoring, as `nohup`
ignores SIGHUP, stays ignored; SIGTERM always stops it. A goal call returns at most `observer_goal_cap_chars * 4` bytes for a 200-character goal
line; a reading returns at most `annotation_text_cap_chars * 8` bytes, 1,920 at the shipped
value.
A failed call falls back to local analysis. No raw model stdout or stderr is served or logged.

An absent or relative `shutil.which("codex")` result is refused. An absolute installed executable
is still trusted code; replacing it as the owning user is outside this boundary.

### Claude Code reading calls

`reading.ClaudeReadingModel` calls `observer.claude_exec`, one bounded `claude --print` call
through the Claude Code CLI the operator has already signed in to. It reaches Anthropic on the
operator's own authentication and spends their Claude Code capacity. **It is gated, and the
owner's acceptance opened the gate on 2026-10-02.** `annotations.CLAUDE_ABSTENTION_CHECK` is
`accepted`, never `passed`: every scored qualification run failed, from the
[first](docs/abstention/claude-results.json) to the
[third continuation](docs/abstention/claude-results-continuation-3.json), and the
[acceptance record](docs/abstention/claude-acceptance.json) lists each with its verdict
([DEC-21](docs/design-reading-a-session.md#amended-2026-10-02-claude-code-is-accepted)).
`reading_route` selects it for a Claude Code session when an absolute `claude` is on PATH, and for
another harness's session only when `codex` is not. The unasked lane resolves with Claude Code
first on a harness that has no producer of its own (owner, 2026-10-20), and sends through
`reading_policy.GuardedModel`. Goal summaries never invoke it. Outside the runtime, only the qualification scorer and the drift replay check's
owner-authorized Analyze tier build one, both through the scorer's verified, pinned copy of the CLI,
and a test holds that list. Set back to `not-run`, the gate is read before the CLI is looked for, so no route,
fallback or forged request can invoke it.

The argv, every flag checked against `claude --help` on 2.1.280, run without a shell:

- `--print`, with the prompt on stdin and never as an argument.
- `--safe-mode`: no CLAUDE.md, skills, plugins, hooks, MCP servers, custom commands or agents. This
  also keeps Compass's own hooks from posting the call to the board as a session.
- `--restricted`: no code-running built-in tools and no WebFetch, and user, project and local
  settings files are ignored.
- Both leave admin-managed (policy) settings in force, as `claude --help` says, so a managed hook or
  other managed setting still applies. `--strict-mcp-config` below does cover managed MCP servers.
- `--tools ""`: the built-in tool set is empty.
- `--strict-mcp-config --mcp-config '{"mcpServers":{}}'`: no MCP server from anywhere.
- `--disable-slash-commands`, `--no-chrome`, and `--no-session-persistence`, so no session is saved
  to disk.
- `--permission-mode dontAsk --permission-prompts none`: anything that would prompt is denied, and
  nobody is asked. `bypassPermissions` and the `--dangerously-*` flags never appear.
- `--output-format text`, `--model` with the explicitly selected admitted model, and `--effort high`.
  The [model admission amendment](#amended-2026-10-05-claude-reading-model-baseline) owns the selection.
- `--system-prompt` with one fixed sentence, `observer.CLAUDE_READING_SYSTEM_PROMPT`, in place of
  Claude Code's default system prompt (owner ruling, 2026-09-27). Checked on 2.1.283.
  `--append-system-prompt`, which would keep the default, never appears.

`--bare` is not used, because it refuses OAuth sign-in. `--json-schema` is not used either.

#### Amended 2026-10-05: Claude reading model baseline

The owner replaced the single Sonnet 5 pin with a Sonnet 5 admission floor. The default request
is `claude-sonnet-5-5`; `--claude-reading-model` selects another explicit ID. A refused model
never falls back to another model or provider. Selecting `claude-sonnet-5` explicitly requests the
baseline when the account does not admit the default; that selection may also be refused.

The versioned policy admits Sonnet and Opus generation 5 or later, with bounded positive integer
version components and an optional valid eight-digit snapshot date. Its generation/minor/family
rank gives Sonnet tier 1 and Opus tier 2. This is an owner admission policy, not a measured ordering
of accuracy. Haiku has no admitted tier; a larger Haiku version number does not establish that it
meets the Sonnet floor. Floating aliases, unknown families, lower generations and malformed IDs
are refused before launch. A canonical ID whose model is unavailable fails normally; naming it
does not prove that an account has access.

A stored Allow binds the provider, receiver and disclosed content version, not a model ID.
Changing an admitted selection does not renew that Allow; every actual press still names and
binds its selected model before it can send.

The selected ID is named in the before-press disclosure and reaches the same restricted call and
its stamp. Tagged replay plans bind the
selected model, effort, policy and command-envelope digest, and each stored read retains that
binding. Changing it requires a new matching dry plan; a tag containing another or unbound model
cannot be extended. Qualification results bind their selected model too. Historical qualification
or replay results do not qualify another selection. The text-only CLI reply supplies no resolved
model receipt, so the served snapshot is unknown rather than inferred from the requested ID.

The process runs with the daemon's environment minus the markers of any Claude Code session the
daemon was started from (`observer.claude_environment`: `CLAUDECODE`, `CLAUDE_CODE_*SESSION*`,
`CLAUDE_CODE_MESSAGING_*`, `CLAUDE_PID`, `CLAUDE_EFFORT`, `CLAUDE_CODE_ENTRYPOINT` and
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`), the set the CLI drops itself when it starts a fresh
session. Authentication and provider variables are kept, so configuration in the daemon's
environment, such as `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` or `CLAUDE_CODE_USE_BEDROCK` and
`CLAUDE_CODE_USE_VERTEX`, decides which endpoint and which account receive the reading.

What reaches Anthropic besides the reading prompt was measured on 2.1.283, 2026-09-27, by
running the real CLI against a local stub with every outbound connection off this machine blocked
by the OS (`score_abstention.py --probe-argv`, below):

- Not sent: Claude Code's default system prompt, about 13,000 characters of agent
  instructions, and with it anything read from CLAUDE.md, memory or skills. No tool is offered:
  the request's tool list is empty.
- Sent anyway, with no flag that removes it:
  - in the system prompt, a billing header line naming the CLI version and one line saying the
    caller is built on the Claude Agent SDK;
  - a separate system message giving the working directory, whether it is a git repository, the
    platform, the shell, the OS version, the model's name and ID, a sentence stating the model's
    knowledge cutoff, a token-budget line (`<total_tokens>`) and today's date;
  - `metadata.user_id`, which holds a device identifier the CLI keeps per machine (per config
    directory), the account UUID and a session id;
  - the headers `User-Agent: claude-cli/<version>`, `X-Claude-Code-Session-Id`, and
    `X-Stainless-OS`, `-Arch`, `-Runtime` and `-Runtime-Version`, which name the OS, the CPU
    architecture and the Node runtime's version.
- Sent only under OAuth sign-in (a Claude account rather than an API key): a context block in the
  user turn reading "The user's email address is ..." with the signed-in account's email address,
  and the account UUID in `metadata.user_id`, which is empty under an API key. The CLI reads the
  email from its cached account and no flag removes it. The owner accepted this on 2026-09-27 on
  condition that it is said before the press, and the Claude Code disclosure names it
  (`reading_route._base_disclosure`). Amended 2026-10-01 (owner, Q1): the press it is
  said before is the one that sends. Idle, the disclosure is one click away in a popover under
  "What is sent to <receiver>", and a press there sends nothing; the press that would send opens a consent step
  that shows the whole disclosure, as the server's parts, before "Allow and analyze". Amended
  2026-10-02 (owner): the disclosure is a short list, one item a line, and keeps each fact this
  section and [Observer model calls](#observer-model-calls) require: what is sent, where it goes as
  configured (the company off this machine, the endpoint named in its place, or that Compass
  cannot name it), the CLI and sign-in it goes through and whose capacity it spends, these
  account details on a Claude Code route, tool output only after it is allowed, and the caveat
  ([the amendment](docs/design-reading-a-session.md#amended-2026-10-02-owner-the-disclosure-is-a-short-list)).
  Superseded in part by
  [DEC-28](docs/design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts):
  there is no consent step and no "Allow and analyze" before the first press. The disclosure, these
  account details included, stays one click away under "What is sent to <receiver>" before any
  press, the first press of each kind shows the notice naming what was sent and where, and tool
  output is included by default rather than after it is allowed.

`--exclude-dynamic-system-prompt-sections` does not help: the CLI ignores it under
`--system-prompt`.

The prompt itself can still name paths. Under the tool-output ruling a check's command line and its
redacted output tail are sent as the session recorded them, and a reader's own messages and, since
2026-10-03, the agent's own messages are sent whole up to 1,000 characters each where the prompt
has room (Observer model calls), except its newest recorded final reply, which since 2026-10-05
goes in full where it fits 4,096 bytes, redacted, so a home path or user name the session typed or
printed reaches Anthropic that way.

Because the working directory is sent, the process runs in a fresh owner-only (0700) empty
directory made outside the state directory, whose path carries the account's home and so the user
name (`observer.reading_workdir_root`). On macOS and Linux it is made in the system temp directory
unless that path sits under the account's home, or has a path component containing the user name
(names under three characters must be a whole component), as a `TMPDIR` set by direnv, a Nix
shell or a `~/tmp` convention does. Both tests ignore case, and "under home" asks the filesystem
whether any parent is the home, because on a case-insensitive volume `/Users/ALICE` is the home
and the CLI names its canonical spelling (review N1). It then falls back to `/tmp`, and when that fails the same test
the reading is refused before anything runs. A missing password-database entry, a root home of
`/`, or an unwritable directory also refuses. The qualification prepares both the private cwd and
output file before charging a call, so these local refusals consume none of its allowance. On
Windows the system temp directory is inside the user's profile and no fallback is tried, so the
user name is still sent there.

The reading runs with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, forced even when the operator
set it to `0`. Measured under a no-egress sandbox on 2.1.283, the CLI otherwise looked up six other
hosts on each call (telemetry and feature flags, carrying the device and account identifiers), and
with it set it looked up none. Nothing in this repository proves that from a real network, and the
probe below can only say what reached its stub.

Stdout goes to an owner-only temp file under the state directory, never a pipe, and at most `annotation_text_cap_chars * 8` bytes of
it are read. The file's 1 MiB bound allows one 0.01 s slice of writes and a write already in flight at the kill, as
[Observer model calls](#observer-model-calls) describes, with the measured overshoot. Since
2026-10-20 stderr goes to a second owner-only temp file beside it, under its own file-size bound,
so a failed call can name its cause: after a nonzero exit at most the first 8 KiB of each stream is
matched against a fixed list and only the closed label survives (`login-required`, `rate-limited`
and the others `observer._claude_failure_reason` names, or the `timeout` category). The reader sees
Compass's own sentence for that label, such as "Claude Code said it is not logged in"; no word of
the CLI's output is stored, served or logged, and an unmatched failure says only that Claude Code
returned an error. The timeout is the reading's **180 seconds**, as on the Codex lane. The
directory and both files are removed on every path Compass itself runs to the end of, including a
timeout or an OS error, and only once the CLI and anything it started have been killed and reaped.
A hard kill of Compass (SIGKILL, a power loss) runs no cleanup and can leave both files behind,
owner-only; the next start removes any such file in `state_dir` older than a day, which no live
call reaches, so a second instance's call in flight keeps its own. An absent or relative
`shutil.which("claude")` spends nothing and creates nothing. The prompt is the reading prompt Codex
receives: redacted, then clipped to 16 KiB. The same remembered answer, now per provider, and the
same rolling cap apply.

These flags are CLI restrictions, not an OS sandbox. There is no Claude Code equivalent of Codex
`--sandbox read-only`. The installed CLI still owns its authentication, caches and logs, and
`--no-session-persistence` does not govern those. That the flags suppress every tool at run time
is not verified by this repository's tests; the one measurement, the stub probe above on 2.1.283,
saw an empty tool list. The pinned model id answered on the owner's account in every scored
qualification run; whether another account may use it is unmeasured.

### Tool output in a Claude Code reading

Ruled 2026-09-24 by [DEC-23](docs/design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work). The record and its route to a model are both built:
`project_context.claude_tool_reports` reads it into the observed record, and `reading.build_ledger`
admits it by default to a reader-pressed reading for a named destination, disclosed in the notice.
With no named destination it drops it, and the unasked lane keeps only a failed result ([the amendment](docs/design-reading-a-session.md#amended-2026-10-27-owner-the-unasked-lane-reads-failed-results)). The
named read is listed under Irreversible actions.

The delegated launch summary added on 2026-10-04 reads the same bounded parent
and admitted child records. It publishes counts and launch, completion and
activity times, with no command, task description or notification output. Those
fields are held in memory and published on the session row; they do not enter
session history. Launch facts are excluded from every Analyze ledger, including
one carrying tool output. Terminal task notifications pair only within the
originating admitted stream, and their text is never published or stored.

Two more kinds join it by the owner's ruling of 2026-10-23
([the amendment](docs/design-reading-a-session.md#amended-2026-10-23-owner-pr-and-skill-facts)): a pull
request Claude Code recorded as created, and a skill it launched. A pull request is read from the
structured `gitOperation.pr` on a shell call's result alone, and published as its repository, number, a
URL rebuilt from those two and the time, only when the URL is `https://github.com/<owner>/<repo>/pull/<number>`
with a matching number and the action is `created`. A skill is read from a `Skill` call whose result did not
error, and published as its name alone, in a closed character set of at most 80 characters. Neither reads a
command, an output tail or a skill's arguments. Like a check, each reaches a prompt only under the same
grant for a named destination, and the unasked lane never receives them: it takes a failed check or command and nothing else.

Commands join it by the owner's rulings of 2026-10-27
([DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)
and [DEC-31](docs/design-reading-a-session.md#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor)).
A foreground shell command that is neither a closed-list check nor on the read-only list is published as
a command: its line, masked and clipped as a check line is, and its exit status where the call's status
speaks for it. `gh pr checks` and `gh run view --exit-status` are published as CI reads. `gh pr checks`
records a failure only on exit 1 with checks reported, and no result on exit 8 (pending), 2, 4 or a pull
request with no checks. `gh run view --exit-status` exits 0 for a run still in progress, so only its failure
counts. A command that cannot fail (`echo`, `printf`, `true`, `:`, `export`, `unset`, `set`, `eval`, `tee`,
`exit 0`, `return 0`, by any spelling such as a path or `command true`) is never published, and one whose
status a later `|| true` or `; exit 0` forces is published with no result and withdrawn from every verdict
and level. A stage after a `|` that follows other work, such as `tee` or `sed`, records no result, since the
call's status speaks for the filter and not for the program before it. A tier 3 failure blocks the live
estimate's floor only until a later check or command passes. A call whose result carries Claude Code's structured git record publishes that record only, never
its command line. A quoted word the masking cannot read word by word, such as the script of a `bash -c`
call that did not parse, is published as `…`, so half of a value is never shown. The same rules decide the
last 180 characters of output the press reads. The vendor of the session decides what leaves the machine:
a Claude Code session read through Claude Code may be sent every command's masked line and redacted tail,
since that vendor already received them. The Live monitor's Haiku check is the exception: it is sent a
command's line and its result words only, never a tail. Another vendor (Codex
reading a Claude Code session) is sent each command's line and status, and tails for checks and CI reads
only: a tail whose call also holds a command is withheld whole, because it is the whole call's output.
The notice names it in one sentence. The residual: redaction is by named form and shape and is best
effort, so a credential in a form it does not name can reach the provider, and across vendors the command
line is the one place that can. The history store receives no command. The unasked lane receives a failed command only, on Claude Code, and never a pass.

The content class is what a Claude Code transcript recorded about the checks a session ran and the
files it wrote. Since 2026-09-28 that includes the session's subagents, read from their own
transcripts under the session's directory. One check-evidence scan spends at most the configured
8 MiB byte allowance across the parent first and all admitted children, charged by actual binary
content bytes returned, including malformed or discarded lines. Live children follow newest
modification time and stable relative path; a frozen check reads children by stable relative path
after a bounded parent cutoff search. A parent cutoff it cannot establish within that same
allowance refuses the frozen check read. Each subagent entry is labelled `worker_kind: "subagent"`
([the amendment](docs/design-reading-a-session.md#amended-2026-09-28-a-subagents-checks-and-writes-are-the-parents)).
A clipped parent Agent result without its earlier call withholds a passing check when that child
cannot be read completely; it does not count as a verified named child. A check is a shell command segment whose runner is on the ruling's closed list, or a project script (a `package.json` script, make target or just recipe) whose own body is a closed-list runner or a `&&` chain of them and whose name carries a check verb, read as the commit the session began on held it; and
a program file counts only when `test` or `tests` stands alone as a word in its name. This check
allowance does not bound the separate activity, identity or user-message reads made during a full
frozen admission or validation. Its publication bounds:
the check's own segment, never the rest of the shell line, with a substituted command shown as
`$(…)`, a brace expansion and the word after it shown as `…`, no redirection, here-string word or heredoc delimiter
published in it, and a trailing comment dropped, after credential redaction and masking of the forms
redaction cannot recognise, clipped to 120 characters. A heredoc body is never listed or read as
literal commands. Command substitutions in an unquoted body do execute, however, and age a prior
pass unless their own commands meet the closed read-only rules. A quoted delimiter keeps its body
literal. Behind `bash -c`, `sh -c`, `zsh -c` or `bash -lc`, it is the
inner segment alone, never the wrapper. A call with an unterminated quote is a syntax error and is
read as not run, so nothing of its text is published; the last 180 characters of output, with Claude Code's own trailer lines dropped from its end and
redaction run over the whole read window before the clip; and a written path relative to the session's working directory, the folder
it began in. A written path is a file-write tool's path or, since 2026-09-27, a check's own
redirect target, published only when it falls inside that directory and through the same
redaction; a target outside it, one the shell decides at run time (`$VAR`, a substitution, `~`), one under a directory a `cd` left unknown,
and one holding any value the call's masking hides, is counted and never published
([the amendment](docs/design-reading-a-session.md#amended-2026-09-27-a-subshell-a-checks-own-redirect-a-write-at-the-same-time-and-when-a-result-arrived)). No file content is
read as a field, and no Edit or Write result body is read. At most 12 entries are listed and the
rest are counted. The published entry carries the check segment, the result, where the result
came from and, as `result_at`, when it arrived, and never the output itself. The output tail is read again at the press
(`project_context.claude_check_press`), keyed by the call, and carried into that one prompt, and held in memory for the local search of the text a harness verdict quotes
([below](#local-history-the-session-history-store)), which sends, stores and publishes nothing:
Compass never writes it onto the fact, a row, the page or history. A departure's explanation is
model prose, and the model may quote a line of the tail in it; that explanation is stored with the
reading and shown on the page with credential-shape redaction and, since 2026-10-27, the values the
session's commands masked removed from it, so a shapeless source line or assertion diff can still
appear there. Only a masked value that can be a credential is removed from the explanation: an
environment literal (`true`, `false`, `production`, `main`, `test`), an auth scheme word (`Bearer`,
`Basic`), a bare number and a lowercase-letters-only word stay, because `CI=true` and `-u 1000`
would otherwise erase ordinary words from a sentence the reader reads. The accepted loss is a
lowercase-letters-only password quoted in an explanation; the check line and the output tail still
mask it. A press carries up to 4,096 masked values and 131,072 characters of them and, past either,
keeps the newest; when it has dropped any, the stored explanation is replaced by a fixed sentence saying it was withheld, rather than
published unscrubbed. The server holds the masked values of the last two scrubs in a small in-memory
cache for the life of the process, and writes them nowhere. A line that lists a command of the shell
(not a check) shows the script given to `python -c`, `node -e`, `-p`, `--eval` or `--print`, `bun` with the same flags,
`deno eval`, `ruby -e`, `perl -e` or `-E` and `php -r` as one ellipsis, also behind a wrapper such as `docker exec`, `timeout` or `uv run`, since a literal
credential inside code has no form a mask can find; a check line keeps its own rule. A value at the
end of a sentence or inside brackets or quotes is removed, while one inside a
longer word, path or domain is not. The class lives in the observed record only, as
its own fact type, kept out of the semantic history store and out of every session row field, and
it is named in `history.PROMPT_DERIVED_CARRIERS`.

Masking is by named form, word by word, and covers these forms and no others: a `NAME=value`
assignment; the value after `--password`, `--token`, `--api-key`, `--secret`, `--auth`, `-p` or
`-P`, joined by `=` or in the next word, except that a pytest check shows `-p no:<plugin>` (or
`-pno:<plugin>`) for an identifier and masks any other word after `-p` (a word spelled
`no:<identifier>` is shown whatever it is, and credential shapes are still redacted by shape; the
output-tail scrub keeps the plain `-p` mask); an `Authorization:` or `X-Api-Key:` header value
anywhere; and, only where a header is expected (the word after `-H`, `--header` or
`--proxy-header`, a header joined to its flag, or an `extraheader=` key), a `Proxy-Authorization:`,
`Cookie:` or `Set-Cookie:` value or one whose name holds `token`, `key`, `secret`, `password`,
`passwd` or `credential` (`X-Vault-Token:`, `Private-Token:`, `DD-API-KEY:`,
`Ocp-Apim-Subscription-Key:`), including a header name standing alone with its value in the words
after it, so `grep -n 'Authorization:' log` masks nothing; for `curl`, `wget`, `http`, `https` and
`xh` only, the password of `-u`, `--user` or `--proxy-user` (also inside a cluster of short flags
such as `curl -sSu`, and `-a` for the `http` clients; the user name stays, and only a word with a
colon is masked, so `git push -u`, `docker run -u 1000:1000` and `tar -su` read as typed); the
value of `--cookie`; the value of a dotted config key whose last part is `extraheader`, `password`,
`passwd`, `token`, `secret`, `apikey` or `api-key` (`http.extraheader=`, and the key GitHub Actions
writes, `http.https://github.com/.extraheader=`), while a flag such as `--max-tokens=4096` or
`--password-file=/x` is not a key; the word after `-a`, `-a<value>`, `--pass` or `--pass=` for
`redis-cli` only; the token word of `vault login`; the value of `aws configure set` for a name
holding `secret`, `token`, `password`, `passwd` or `key`, read past `--profile` and the other flags
that take a value; the value after `--secret-string`, `--passphrase`, `--pass`, `--pwd` or
`--credentials`, joined by `=` or in the next word; the value of `--from-literal` in kubectl's
`key=value` pair (the key stays); the value after `--value` for `aws ssm put-parameter` only;
npm's `_authToken`, `_auth` and `_password` lines, as `//registry/:_authToken=value` or after
`npm config set`; the value after
`--body` or `-b` for `gh secret` only, so a pull request body stays readable; the value after `-w`
for the `ldap*` tools and after `-N` for `ssh-keygen`; an openssl `pass:` prefix, on an openssl
line or after `-pass`, `-passin` or `-passout` (`-passin pass:value`), while `env:` and `file:`
sources name no value; the token word of `cargo login`;
and the password in `user:password@`, up to the last `@` in the word, so one
holding `/`, `@` or whitespace is masked whole. A program is found behind `rtk`, `sudo`, `env`, `uv
run`, `pnpm exec` and the like, and behind `docker`, `podman` or `kubectl exec`. The words are the
ones the program receives: quotes removed, `$'…'` escapes decoded and backslash-newline
continuations joined before masking and redaction run, so a value is masked whole however it was
quoted, and an escaped key such as `$'\x41KIA…'` reaches redaction as the key it is. Redirections,
a named descriptor such as `{fd}>` included, are set apart first, so a flag and its value are
masked as a pair even with a redirection between them, and a NUL decoded from `$'…'` ends the
argument as it does for the program. A value after any other flag is published as typed unless it
has a credential shape.

The output tail is covered by credential-shape redaction, and by one more step: each named value
masked anywhere in the call, assignments, wrapper arguments and executed substitutions included,
and each piece of it of four characters or more, is removed before redaction and the 180-character
clip. This covers the
literal value and its shell re-quoting, including an apostrophe split by xtrace, since an echoed
command (`set -x`, a runner printing its arguments) repeats it. Matching respects filename and
identifier boundaries: a password `test` does not rewrite `test_a.py`, `contest` or `src/test`.
Credential shapes the tail itself can print are redacted as well, since 2026-10-27: a gcloud
`ya29.` access token, the value of an AWS `"SecretString"`, the password of a netrc entry (behind
`machine` or `default`), a `PASSPHRASE` assignment, and the signature of a pre-signed URL (`X-Amz-Signature=`,
`sig=`, `signature=` and the like, inside a query string only). Ordinary runner output, paths and commit
ids are left as they are. A netrc entry is taken when `login` follows its `machine` or `default`, or
when the value of a loginless one has a digit or a capital, and a signature only when its value has a
digit, a base64 or percent character, or both letter cases, so "password reset", "machine learning
password manager" and `sig=overview` are left alone. A shapeless value no named form masked, a masked piece shorter than four
characters, or an arbitrary encoding of a value can still reach the prompt through the tail.

The destination rule: it goes to the reading producer that reads the session, or the fallback
route `reading_route.resolve` selects and discloses before the press. Tool output is included by
default for a named destination, and the non-blocking reading notice names it. No separate grant
is required; `tool-output-consent-required` is no longer a refusal. Explicit off blocks the press
and the reservation. The unasked lane receives the failed results of a Claude Code session's checks and
commands and no other tool output, and no output tail from a shell call that also held a run that
passed, ran more than one thing, or whose output is not one failed check's own ([the amendment](docs/design-reading-a-session.md#amended-2026-10-27-owner-the-unasked-lane-reads-failed-results),
[the mixed-call rule](docs/design-reading-a-session.md#amended-2026-10-28-owner-the-unasked-lane-withholds-a-mixed-calls-tail-and-says-what-a-later-pass-superseded)).

- The legacy `tool_output_permission` table remains keyed by provider and destination, so an older
  build can still read its explicit grants. Old word-only answers remain distinct from those
  grants. An explicit Allow carrying a stale tool-output destination still answers
  `409 destination-changed` before writing or spending. Pause model calls and `--forget` clear
  all grants and notices. A plain reader press needs no grant lookup.
- `--allow-tool-output` and `COMPASS_ALLOW_TOOL_OUTPUT=1` are accepted no-ops for this release and
  will be removed in a later release. Startup writes no grant, changes no disclosure and prints
  no grant diagnostic. The Windows respawn no longer forwards this no-op flag.
- `reading_route.destination` names the destination as configured, or names nothing. For Claude
  Code: `Anthropic`; `Amazon Bedrock` or `Google Vertex AI` under `CLAUDE_CODE_USE_BEDROCK` or
  `CLAUDE_CODE_USE_VERTEX`; or the host and port of `ANTHROPIC_BASE_URL`, never its path, query or
  user information. It reads the daemon's environment, the managed settings file and its drop-in
  folder (`/Library/Application Support/ClaudeCode/managed-settings.json` and `managed-settings.d/`
  on macOS, `/etc/claude-code/` on Linux) and the cached remote settings
  (`~/.claude/remote-settings.json`, or under `CLAUDE_CONFIG_DIR`). Those paths were measured in
  the live 2.1.281 binary on 2026-09-24. For Codex: `OpenAI`.
- It names nothing, and tool output is not sent, where: two provider switches are on, or one it
  does not know; a switch holds a value that is neither on nor off; a base URL sits beside a cloud
  switch, or any `ANTHROPIC_*_BASE_URL` other than `ANTHROPIC_BASE_URL` is set; two sources set one
  endpoint variable differently; a settings file cannot be read or parsed;
  `CLAUDE_CODE_MANAGED_SETTINGS_PATH` is set; `CLAUDE_CODE_CUSTOM_OAUTH_URL` is set in any source,
  because an approved custom OAuth host replaces the first-party API host; `ANTHROPIC_UNIX_SOCKET`
  is set, because every request then goes to a local socket whose far end forwards under another
  machine's settings; `ANTHROPIC_BASE_URL` holds anything the CLI's WHATWG URL parser could read
  as another host than Python's `urlsplit` does (consent F1, ui5). That is a backslash, any
  whitespace or control character (leading and trailing included), any non-ASCII character, a host
  with a percent-escape or a character outside letters, digits, `.`, `-` and `_`, an empty label,
  a host ending in a number that is not a plain dotted quad, or a host with a credential's shape.
  Measured on Claude Code 2.1.287, `http://127.0.0.1:4597\@127.0.0.1:4598` sent every request to
  4597, where `urlsplit` reads 4598, so naming 4598 would have bound the Allow to a host the words
  never reached, and a key after a backslash would have been published and stored as the host;
  neither `HOME` and `USER` nor the password-file entry gives a home and a user
  to look under; a macOS managed-preferences profile
  (`/Library/Managed Preferences/com.anthropic.claudecode.plist`, or its per-user copy) exists,
  because the build does not read it; or the machine is Windows, whose policy lives in the registry
  and under `C:\Program Files\ClaudeCode`, neither of which is read. On the Codex route, which
  reads a Claude Code session on this build, it names nothing where `OPENAI_BASE_URL` or
  `OPENAI_API_BASE` is set, whether or not Codex honours them under `--ignore-user-config`, which is
  not measured; where `/etc/codex/managed_config.toml` or `/etc/codex/config.toml` exists, or a
  `com.openai.codex` managed-preferences profile, each measured in the live 0.156.1 binary; and on
  Windows.
- A proxy variable does not change the destination named: it carries the call, and the vendor that
  answers it is the same (owner, 2026-09-24). A `CLAUDE_CODE_USE_*` switch that is not a provider
  switch but is on (`CLAUDE_CODE_USE_POWERSHELL_TOOL` is one) also names nothing today. That fails
  closed, costs the reader tool output, and is left as it is.
- A pass that a later command may have changed files after, in the same call or a later one, does
  not let a reading say the output is consistent, and its reason says so.
- A passing check never makes an outcome line consistent when the line is about what the agent
  tells the reader (reports, explains, says, lets you know). A check cannot show that, so the
  resolver withdraws the verdict unless one of the agent's own messages is among what it rests on
  ([the amendment](docs/design-reading-a-session.md#amended-2026-10-01-a-line-about-what-the-agent-tells-you-cannot-be-shown),
  narrowed on 2026-10-03).
- The agent's own messages may quote what a check printed, so tool output can reach the provider in
  the agent's words even where this grant was never given (Observer model calls).
- Where the destination cannot be named, the reading still runs on the reader's words, and its
  cutoff sentence says the checks were not sent and why.
- The disclosure's `To:` item says what `destination` says, on every harness and not only for tool
  output: the vendor off this machine, the cloud, or the base URL's host in its place (a host is
  never said to be off this machine, since it may be a local gateway), and where nothing can be
  named, that Compass cannot name where the CLI's settings send it. It never names the vendor
  then, so an Allow is never given for a receiver the words do not reach (verifier C1,
  2026-10-02), and the Allow is bound to what it named, so it never carries over to a receiver
  named later (owner, 2026-10-02). On Windows this is every route.

It is quoted into the prompt as untrusted data, never into an instruction Compass writes: each
check is one numbered row whose result words are Compass's own, and its output tail is one
JSON-quoted field on that row with line breaks and the menu heading neutralised. A reply that obeys
an instruction in that output is held to the same shape rules as any other. The unasked lane receives
it for a failed result alone. The live drift estimate (DEC-26) reads
the check results and written paths on this machine, never the output tail, and publishes a derived
level on the focused session's project context only: never on a row, in history, in the reading
route's context or in any off-machine payload. It starts no model and writes nothing, and its only process is the read-only committed-file
git read of a project's check scripts, which `--no-git` stops. Whether the reader turned it on is kept in the browser and never sent.

What it cannot remove: a reported success is what the tool said, not an inspection of the work, and
a reading labels it that way. Two settings sources are not read and so cannot be named or refused:
Codex's cloud-delivered managed configuration, and any Claude Code remote setting not yet cached
on this machine. A managed setting that moves the endpoint through either reaches the destination
it names, not the one the disclosure named. The output tail is whatever the runner printed. A traceback, an
assertion diff or a printed setting can carry source lines, file content or a secret that has no
recognisable shape, and output gets credential-shape redaction only, because the command-line masks
do not apply to it. It leaves the machine under the destination rule above. The command field is
the check's own segment. Any other command on the same line is a separate command fact, which
[Tool output in a Claude Code reading](#tool-output-in-a-claude-code-reading) owns.

### Analyze drift, Cancel and copied corrections

Ruled 2026-09-24 by [DEC-24](docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy). The background job, Cancel and the copied-correction route are built; each other part arrives
with the layer named beside it, and the route counts in Scope move in those layers, not here.

The labels. "Check for drift" became "Analyze drift", and "Allow and check" became "Allow and
analyze". When idle the disclosure sits one click away under "Analyze drift", in a
popover whose summary reads "What is sent to <receiver>" until it is allowed (owner, 2026-10-01, Q1), and that
press either opens the consent step first or runs under an Allow already given after this same
disclosure; in the consent step it is shown whole, as the server's parts, before "Allow and
analyze". The permission and rolling budget above are otherwise unchanged, except
that an allow given before the disclosure named tool output does not cover it
([Tool output in a Claude Code reading](#tool-output-in-a-claude-code-reading)). Keep never counts
as the allow (owner, 2026-09-27): where the disclosure has not been allowed, it reads "Keep my
intent", settles through `POST /api/annotate` with no `allow` and no `tool_output`, and leaves
"Allow and analyze", with its disclosure, as the press that sends. Superseded by
[DEC-28](docs/design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts)
for the consent step and the tool-output allow: the first press runs and shows the notice, and a
stored off still refuses every press until Resume model calls.

Keeping your intent and adding a later direction. "Leave it" settles every later direction the
question quoted, as the `settle_through` field of a `POST /api/annotate` body, which reads nothing
and starts no analysis: "Analyze drift" is its own press. Over an unsaved draft it adopts the
draft and records the settlement in one store write, and a refused adoption settles nothing. It
names the intent revision on screen when it is pressed, so words saved since the page was drawn
are refused rather than settled over, and a refusal leaves the quoted words in place.

"Add as a line" reads, then writes. The read, `POST /api/direction`, names a session and one
fact id and returns that message's whole text, which the page already holds from drawing the
question, where the published record holds only
its first sentence, clipped. That is wider than any published field, so it is stated exactly. It
returns the text of one message, masked by named form as a check line is (a `NAME=value`, the
word after `--password`, `--token` or `-p`, an `Authorization:` or `X-Api-Key:` value (the wider
header names, `Cookie:` and `password:` among them, are read only on a command line, where a header
flag says one is expected, so "the Set-Cookie: header" and "Fix the password: handling" keep their words), a
`user:password@host` quoted or not, and a credential shape wrapped by a line break on both sides
of the break, with a zero-width space, soft hyphen and the other invisible characters that can
hide a flag removed first, while the joiners that spell words and emoji are kept), then redacted by
shape like every published string, with line breaks and control characters as spaces, bounded at 2,000 characters with a flag saying whether
it was clipped (a message the record reader already cut at that bound counts as clipped), and a flag saying whether the store would take it as a line (at most 240
characters). It returns nothing for a message that is not a person's message in that session's
own record, one not later than the words it would join, or one beyond the bounded source search.
Every refusal is an HTTP 200 body. `not_found` covers an unverified source or a
request not later than the intent, including unknown sessions; `out_of_reach` says
the search ended before reaching the record's start; `changed` says the session wrote to
its record during each of three whole scans, and the press can be repeated. The budget token describes search coverage, not whether the requested direction
exists. Session identities remain the same loopback data already published by
`/api/data`; unknown sessions have no separate HTTP status. The [long-session lookup](docs/design-reading-a-session.md#long-session-direction-and-prompt-reads)
owns its 64 MiB and two-second limits and the bounded ambiguity guarantee.
Prose shapes outside those named forms come back as typed: a password written into a sentence,
`token: value`, a JSON field and a `?token=` query are not masked, and only a value with a
credential's own shape is redacted there. The text is read again from the bounded native transcript source, found by `observer.resolve_transcript`
from the session's harness and id, and never from a path a client names. It is served to the same
callers as `/api/data`: loopback only, same-origin, and refused to a document navigation and to a
same-site or cross-site fetch, as `POST /api/reading` is, and it answers 503 under
`--no-annotations`. It writes nothing, stores nothing, reaches no model and sends nothing off the
machine, and the text never enters session history: no published field carries it and the
history prompt-text allowlist is unchanged. A local process running as you gains nothing it could
not read from the transcript file itself. Another account on the machine can reach this route as
it can reach `/api/data` (Known and accepted), and for that account it is wider: the whole text of
any verified later direction within a session's bounded source search, each fact id listed by
`GET /api/project-context`, where that route gives only the first sentence. A loop over those ids
reads every one of them, so the ids bound nothing. A Claude Code slash command is the one message
the record names by more than its first sentence: the record and this route both give the command
as typed, its name and arguments on one line rather than the tags they arrived in, under the same
redaction and bounds, and a harness control such as `/clear` is in neither. Its
arguments go nowhere an ordinary message's words do not. Why it is no narrower: the reader edits a long direction down to one line of
their own, so the page must show more than fits, and a summary in its place would be the one thing
DEC-24 item 4 forbids saving.

The second is the `add_direction` field of a `POST /api/annotate` body, with the reader's edited
text. The server checks the fact again exactly as the first request did, so the only claim it
mints is that the line was added from that entry. The text is saved under the typed-line rules: at
most 240 characters and one line, refused rather than clipped. A full list of six is refused
unless the body names the line to replace, so a reader's own line is written away only when they
chose it, and every request names the revision it was drafted against. The line, the settlement
through that direction's time and, over an unsaved draft, the adopted goal go in one store write.
Keep names its revision too, on both routes, and a stale one settles nothing; Keep never adopts
over a saved goal holding other words, and a settlement never moves back over one already given.
The revision check holds across dashboards too: every store write takes the store's lock file, as
the annotation store section above describes, and the check reads the revision from disk
under it.

The background job. An admitted press answers `202` with a job the server
owns, before the model is called, and the reading runs on a thread of its own under the
supervised runner above. The job's id, its phase, the three step names and when it started are
published board-wide under `reading_jobs` in the payload, to any loopback client, as the board
itself is; the process handle never is. A second press answers `409 in-flight` with the running
job and starts nothing. A slot the unasked lane holds answers the same `409` with no job. The
permission and budget are read again at the model seam inside the job, so a budget another tab
filled, or an answer withdrawn, after the press was admitted ends the job with nothing written or
spent. Before the reservation, a marker under `reading-jobs/` in the state directory names the job
(its id, the harness and session id, the pid, the start time, and no content), owner-only; a marker
that cannot be written stops the job with nothing spent. The outcome is stored under the job's id,
and a spent attempt keeps its marker until the store holds it; a store that refused the outcome
leaves the marker saying so, and the next start records the attempt with that sentence, or with
the stop's or the unconfirmed kill's own sentence when that was the refused outcome. A job the
shutdown ends is recorded as a spent `interrupted` attempt, unless its kill could not be confirmed,
which keeps the "may still be running" sentence. The stop's line is the reservation: the
charge commits under the lock the shutdown takes, so a shutdown before the commit charges nothing
and records the unspent "Compass was stopping" sentence. A marker the next dashboard start finds,
whose pid no state file of a running dashboard on this state directory names (its own pid counts
as an earlier run), is recorded from the job ledger: spent when the budget store holds a
charge for that job's id or cannot answer, and unspent ("stopping", or "cancelled-unsent" when the
marker says cancelled) when it holds none.
A recovery pass holds an OS lock on `reading-jobs.lock` beside that directory (`flock` on POSIX,
`msvcrt.locking` on Windows), each marker is claimed by a rename before it is recorded, and an entry
that already holds the job's id counts nothing, so one job is one attempt however many dashboards
recover it. The lock is there because the rename is atomic on POSIX and not exclusive on Windows. A
claimed marker that cannot be read is left in place for the next start, and only a malformed one is
deleted.

The Cancel route. `POST /api/reading/cancel` names the running job's id and
kills that job's process group, or its Job Object on Windows, through the handle the supervised
runner gives the job; nothing on that path can reach the daemon's own group. It releases the
one-in-flight slot after the child is reaped and its temporary files are removed, records a
"cancelled" withheld reason as a spent attempt, and discards a reply that arrives after it. A cancel
that lands before anything is reserved records an unspent attempt instead. One deviation is
accepted: a kill that cannot be confirmed within 5 seconds records the "may still be running"
sentence and frees the slot anyway, as the timeout and shutdown paths do, because a slot held
forever would refuse every later press until a restart.
A forged cancel needs the job id, which the push publishes to any loopback client, and like every
route that can authorize a model call it is refused to a non-loopback peer and cross-site. It
discards a reading the reader started and records it as a cancelled, spent attempt, as though the
reader chose it, and it reaches no process but the reading's own. No job, another job's id and an
unknown session answer one `409 not-running` body, so the route says nothing about which sessions
exist. It writes no consent and reserves nothing.

The copied-correction route. `POST /api/correction/copied` names a session
and the exact text the reader copied, at most 5,900 characters, and the server records its digest:
a SHA-256 of the text after one normalisation, applied to both sides, which is what Claude Code
2.1.283 was measured doing to a paste: CRLF and CR become LF, a tab becomes four spaces, and
whitespace is trimmed at both ends. It also records a second digest of the same text with every run of
whitespace folded to one space, so a paste whose only edit was whitespace still matches; a changed
word, or a space inside a word, does not. The store holds the digests, the moment of the copy and where the
session's transcript ended at that moment (its inode and size), and, once a message is recognised,
that message's fact id and time. It never holds the text. It is `compass-copied-corrections.json`
beside the annotation store, owner-only through a temp file and a rename, under an OS lock on the
`.lock` file beside it. It is bounded at eight digests per session still waiting for their message
and 32 recognised messages per session, the oldest of each dropped. Dropping the oldest waiting
digest drops only a copy whose message never arrived: a message already recognised keeps its mark
until 32 later recognised messages in that session push it out, and then it reads as the reader's
own words again. `--forget` deletes the file, and `--no-annotations` turns it off. A digest still
waiting answers without storing anything, so registering one twice earns no second match. Only
Claude Code sessions are read for a match. A user message written after the point the transcript
had reached when the text was copied, whose digest computed from its raw text before any redaction
or clipping matches exactly (or by the whitespace-folded digest), is Compass-assisted, whatever either
clock says. Claude Code wraps a paste in its own `pasted_content` tags, which are taken off before
either digest is computed; words typed around the paste are not, so they make a different message. The transcript is
read from that point to its end, at most its newest 64 MiB plus its opening 32 MiB, matching the Intent source reads,
under the same unchanged digest and first-paste rules; the semantic history store
reads a source to, so a paste the bounded tail never held is still recognised. Each digest binds the
first such message, and nothing before it, and a recognised message stays recognised after the
tail moves past it. An assisted message is `derived` rather than person-authored evidence, is never
adopted as the goal, does not open the evidence window of typed words, cannot be opened by
`POST /api/direction`, is not an unsettled later direction, and is never shown as the stated goal,
the assignment or an exact direction. Reader edits inside a copied correction are exempt from the
later-direction floor: an edit made in Compass's box before copying is inside the digest, while an
edit after pasting, a backspace that wipes the paste included, makes a different message that is
the reader's own. The route is guarded as `POST /api/direction` is: loopback only, same-origin,
refused to a document navigation and to a same-site or cross-site fetch, and 503 under
`--no-annotations`. Every accepted registration answers the same `{"ok": true}`, whether the session
exists, whether its harness is read and whether that text was copied before, so the route says
nothing about which sessions exist. Two things remain. Each probe of a real Claude Code session
stores a digest and takes one of its eight waiting slots, pushing out the oldest copy still waiting.
And a store that cannot be written answers 503 only when a write was attempted, which happens only
for a real Claude Code session. The Copy button in Steer back's box calls this route with the box's
exact text, after the clipboard took it and never before. The
residual is a local process: any process that can reach the loopback route can record a digest.
Each digest it records can mark one later message whose text matches exactly as Compass-assisted,
once, up to the per-session bound. A marked message is not person-authored evidence and not an
unsettled later direction, so a process that records the exact text of a short direction in
advance can keep that direction from raising the later-direction question and from blocking "None
or low".

Steer back's correction. `POST /api/correction` names a session and nothing
else, and answers a correction the server composes without a model from that session's published
row and observed record: the goal and outcome lines the reader saved, each line's state re-derived
from a stored reading of those exact words, and the time of each entry a line or sentence rests on.
It never reads a fact's summary, a command, a check name, tool output or a message's text, so
none of them can reach the correction, with one exception since 2026-10-04: for
a claim of the agent's that a stored reading found the record contradicts or does not show, it
quotes that one agent message's published title, its first sentence of at most 112 characters,
which the activity list already shows, and never the message's words. The owner amendment of
2026-10-04 omits titles of two words or fewer and bare URLs; the correction uses a generic
evidence request in their place
([the amendment](docs/design-reading-a-session.md#amended-2026-10-04-owner-what-the-agent-claims-is-its-own-constraint)).
A reader who copies such a correction and edits it before sending it pastes the quoted claim back
into the session; edited past recognition, it arrives as the reader's own words, as any edited
correction does. A second exception since the owner's ruling of 2026-10-20: each surviving
departure, a contradicted claim's included, carries the stored reading's own explanation, the one
bounded `detail` sentence a model wrote, on its own line labelled "Why Compass reads this as
drift:", so it reads as Compass's reading and never as the reader's words
([the amendment](docs/design-reading-a-session.md#amended-2026-10-20-owner-the-correction-carries-the-explanation)).
It is passed again through the redaction and bound every stored reading string takes (240
characters and a closing ellipsis where cut), also behind each hyphen or underscore inside a token,
because the shape filter misses a key joined to "x-", and neutralised so that a paste cannot become a
command or a new instruction block: every invisible format character (Unicode category Cf, the
byte-order mark, word joiners, bidi controls and the tag characters among them, but not the
zero-width joiner and non-joiner) and every variation selector is dropped, control characters and
line separators become spaces, a leading structural opener (`/`, `!`, `>`, `|`, a heading `#`, a
list or ordered-list marker, a `~~~` or backtick fence) is removed before anything is swapped, and
then a backtick, an angle bracket and a word-initial `@` are each replaced by one look-alike
character. It remains model prose: a reader who pastes it hands
the agent a sentence a model wrote about its session, and one who edits the correction past
recognition sends that sentence as their own words. A third exception since the owner's second
ruling of 2026-10-20: a departed goal or outcome line cited at one of the agent's messages quotes
that message's published title, the same first sentence of at most 112 characters, passed through
exactly the redaction and neutralising the explanation takes, so the agent can find the moment
([the amendment](docs/design-reading-a-session.md#amended-2026-10-20-owner-local-time-and-quoted-words)).
A command, a check name, a path and tool output are still never quoted. Each entry travels as its
time, drawn in the zone the page sends (`utc_offset_minutes`, refused unless a whole offset within
16 hours of UTC, and the server's own clock when absent), and a placeholder holding its fact id,
which the page draws as nothing. A reply's lines are at most 2,760 characters, each of at most
eight explanations has 277 more and each of at most seven quotes 132 more, so a reply is at most
5,900 characters and is never truncated: lines over their 2,760 drop the consistent ones and then answer a refusal sentence. It stores nothing of
its own: it reads, and the collection it runs to read the session may rewrite the semantic history
store, as `POST /api/direction`'s does. It is guarded as `POST /api/direction` is, reads Claude Code sessions only, and answers one body for an
unknown session, another harness, and a session with nothing to steer from alike. The reader edits
the text in the page and copies it; Compass never sends it into the session.

The Not accurate token. A reader may mark a reading not accurate, through the
`not_accurate` arm of `POST /api/annotate`, which takes a bool and the reading's `read_at` and
stores the literal token `true` beside the reading it names, and nothing else: no reason and no
text. Setting or clearing a mark updates the entry's `written` time, as every write to the store
does, because that time orders eviction at the store cap; so the time of the last mark can be read
back until the entry is next written. A mark naming any other reading is refused, and a new reading clears it. The token is
stored with the annotation entry and removed with it, and, like the words and readings in that
file, it is not reached by `--forget`. It is published on the session row as
`annotation_not_accurate` for the page and derived reading guards: it is never sent to a model, never counted, never in
session history or the unasked lane, and never entered into abstention marks. Any local process
that can reach the loopback route can set or clear it, as it can the words themselves. The owner,
approving the Analyze drift plan on 2026-10-04, amended DEC-24 item 10: a marked reading no longer
contributes to its analysis level or Steer back composition. This changes use of the token, not
its stored shape or exposure; independent recorded facts still count. Clearing the mark restores
the reading.

Reading coverage, owner amendment of 2026-10-04. A pressed reading may store and publish an
optional `coverage` mapping beside its existing assessment: whether the bounded transcript tail
was truncated (boolean or unknown), its earliest time (or unknown), counts of unlisted passes or
writes and checks with no prompt room, the counts of other commands that ran and of those that were read-only (session-wide, both or neither; an older reading, or one whose scan was cut from the tail, has neither and says the count was not recorded), and a closed adopted-source state. The state is `typed`,
`whole`, `excerpt`, `unroomed` or `unknown`; it holds no source words. The file identity used to
bind the measurement to fact collection stays in memory and is not part of that mapping. Missing
legacy coverage stays unknown. The metadata is never sent to a model, copied into session history
or used to alter a verdict. It permits no additional transcript text to be stored or published
([the ruling](docs/design-reading-a-session.md#amended-2026-10-04-owner-disclose-measured-reading-coverage)).
For a Claude Code press that read back (2026-10-13), the two message measurements describe what the
project cap kept rather than the 400,000-byte tail: the boolean is true when the read stopped before the
window start, left an unread region inside it, or the read or the cap dropped an in-window message of the session, and
the time is where the record is whole from. The keys, types and exposure are unchanged.

### Pull request CI reads

[The ruling](docs/design-reading-a-session.md#dec-30-compass-may-read-a-pull-requests-ci-state-when-the-reader-presses-analyze)
is the contract. When you press Analyze on a session whose goal names a pull request by its
`https://github.com/OWNER/REPO/pull/N` URL, or whose Claude Code transcript records a `pr-link` or a
pushed branch for the repository the session folder's own `origin` names, Compass starts your `gh`
to read that pull request's checks. The records are read from the transcript's tail, bounded in
bytes and rows: a `pr-link` row's `prRepository` and `prNumber`, and a result's
`toolUseResult.gitOperation.push` (`branch`); never the command or its output. It sends GitHub the repository and the number, or, where a pushed branch is what bound it, the
repository and that branch's name, and nothing else of the session's text. The repository, the number and the branch are identifiers taken from the session's records, not session text, and they leave the machine with your own login. A
second `gh` call asks which checks the repository requires, and the checks that come back go to the
reading model with the rest of the entries, so the model's own notice covers them.

What runs: `gh pr view` for the head commit before the checks and again after them, so a head that
moved in between matches nothing, and `gh pr checks` twice, with `--repo github.com/OWNER/REPO`
always explicit. A pull request read within 30 seconds of the last is not read again. Nothing runs without a press: not the
Live monitor, the live estimate, a summary, the unasked lane or `--diagnose`.

The launch keeps these bounds, each pinned by `test_ci_read`, and by `test_ci_read_gitlab` for GitLab:

- The binary is an absolute path resolved against a `PATH` with every relative element removed, as
  the git probe does it, and a missing `gh` is said beside the reading.
- It runs in an empty directory Compass made for it and removes afterwards, with stdin closed.
- `GH_*`, `GITLAB_*` and `GL_*` are removed from its environment, so no override redirects the host,
  repository, account or configuration, and `GH_PROMPT_DISABLED` and `GH_NO_UPDATE_NOTIFIER` are set.
  The login it uses is the one stored for your account. A `GITHUB_TOKEN` in the environment is kept.
- The owner, repository and number are checked against a closed pattern before anything starts, and
  a pushed branch against another, so nothing in a transcript can become an option.
- A hard timeout of 20 seconds kills the process group, and output is capped at 256 KiB.
- Its output is read as JSON whatever the exit code, since `gh` exits 8 while a check is pending and
  1 while one has failed, then checked against a closed schema. Anything else is one closed error
  token. Its stderr is read only to choose that token and is then dropped.
- GitLab is read through `glab api`, a fixed GET of the merge request and then of its pipeline's jobs
  (a hundred a page, ten pages at most, anything past that is unreadable and never a pass), and the
  merge request again at the end for the head. The project path is a closed pattern, percent-encoded,
  and the numbers are integers. `GLAB_*`, `OAUTH_TOKEN` and `REMOTE_ALIAS` go with `GITLAB_*` and
  `GL_*`, so `GITLAB_TOKEN`, which applies to any host a command names, never reaches the child: a reader
  who signs in to `glab` by that variable alone reads nothing, and one signed in with `glab auth login`
  reads normally. Before anything is launched Compass reads the host names under `hosts:` in glab's
  own configuration file (`glab-cli/config.yml` in `XDG_CONFIG_HOME`, else `~/.config`, else
  `%APPDATA%` on Windows), keeps no value from it, and reads only a host that matches one exactly, over
  https, as a dotted name that is never an IP literal and carries no port. A host whose block sets
  `api_protocol` to anything but https, `api_host` to another address, or `skip_tls_verify` on is
  not read either (those three values are read from the block, and no token). A pipeline counts only when
  it ran the merge request's head, which is the session's commit; a merged-results pipeline settles
  nothing. A goal URL that names any
  other host starts no process and says so beside the reading. Only a goal URL binds a merge request:
  what Claude Code writes for one is not measured
  ([the capture note](docs/captures/claude/gitlab-merge-request-read-unmeasured.md)).
  GitLab has no required-checks list, so a job allowed to fail counts as neither a pass nor a
  failure, a manual job counts as pending unless it may be skipped, and a pipeline whose own
  status disagrees with its jobs (a trigger job's child failed) is listed as a check named `pipeline`.
- To place the session, Compass runs `git rev-parse HEAD` and `git config --get remote.origin.url`
  in the session folder, with the status probe's flags and the same scrubbed `PATH`. It keeps the
  commit and the host and repository the remote names. Any user or token in the URL, and the URL
  itself, are dropped by the parse and never returned. `--no-git` stops both commands, pinned by
  `test_ci_read.ThePressTimeIdentityReadsTheFolder.test_no_git_launches_nothing`. They run only inside
  an admitted Analyze press, never at the end of a session and never from the Live monitor.
- Compass keeps each check's name, bucket and completion time, the head commit and counts. A name is
  writable by whoever writes the workflows, so it takes a closed character set and a clip, and it
  reaches the model quoted. A description, a link or a log is never read.

The record is stored with the reading (`ci` beside `criteria`), labelled with the time it was read,
and read back only through a closed validator. Pending is never a pass. A skipped check counts as
neither a pass nor a failure. A cancelled check is not a pass. No completed check is no result, and
GitHub's required checks are preferred where it names any. CI counts only when the pull request's
head is the commit the session folder is on, and a session that edited a workflow file or
`.gitlab-ci.yml` carries a caution the model reads while it still settles.

The off switches are `--no-ci-read` and a switch on the page, stored as one marker file in
Compass's state directory. The flag wins over the page. `--no-observer-model`, Pause model calls and
the rolling cap refuse the press before anything starts, because the read runs inside the admitted
job. `--no-git` also leaves the read without a session commit, so it settles nothing. The one line
naming the read is part of the notice a press shows, and a reader who turns the read off sees no such line.

### Session summary calls

Ruled 2026-10-19 by the owner ([DEC-28](docs/design-session-summary.md)). Summary jobs run on a reader's open or press and keep finished parts as they arrive.
Opening a stored summary makes no summary call or charge.

- What it is. A model-written summary of what a session did: a lede and phases with titled bullets,
  each bullet citing at least one entry by fact id, in the
  [closed shape](docs/design-session-summary.md#the-closed-summary-shape). Unlike a reading, which
  stores one bounded model sentence per constraint, a summary stores model prose throughout: the
  lede, phase titles and bullets. Every one is held to the shape's backstop at production, and a
  string that fails it is withheld in place.
- What is sent. Entries from the session's own record, read in order and bounded in bytes and time:
  the person's words, the agent's words where the harness record admits them (Claude Code only
  today), and the checks and files the record shows. Everything goes through
  `records.redact_secrets` first and the byte bound second, as every harness invocation does. No saved intent is needed or sent. The producer sends
  exactly these carriers, each redacted before it is clipped: the person's words and text relayed
  in a person turn, at most 1,200 characters per entry; the agent's words, at most 700; a check's
  masked title, at most 220, with the source's result token (`failed`, `passed` or
  `not-recorded`); a written file's display path, at most 220; earlier phase titles the model
  wrote for this same summary, as context only, within one sixteenth of a window; and, for the
  lede, the menu lines the surviving phases cited, sent again within one window. No tool output is
  sent yet: the source admits none, so an output prefix waits on that source change and the
  tool-output grant. The [producer contract](docs/design-session-summary.md#producer-contract)
  owns the exact shape.
- To whom. The provider and destination the notice names, invoked as the operator's own harness,
  under the bounds above. Summaries have a grant of their own, bound to provider, destination and
  content tier, separate from Analyze's; turning summaries off leaves Analyze as it was. Consent,
  destination and the tool-output grant are checked again before every part of a multi-part
  summary, so a revoke stops the job at the next part.
- When. A finished session is summarized when the reader opens it, unless summaries are turned
  off, and later opens read the store without a call. A running session updates only on Update
  summary, reading only new entries. There is no interval. These are reader-requested calls, not
  unasked ones.
- Ceilings. Each summary has whole-job ceilings on calls, bytes sent and seconds, and summaries have
  a rolling cap of their own, so a summary cannot spend Analyze's 100 attempts in 24 hours. The
  measured ceilings are 37 calls, 768 KiB sent and 600 seconds, with a separate rolling cap of
  200 summary calls per 24 hours. The producer's plan refuses oversized jobs before the first
  charge and reports the allowed windows, bytes, calls and seconds. Each attempted part has an
  idempotent receipt in `summary_spends`; failed and timed-out attempts stay charged. Analyze's
  ledger is untouched. Cancel keeps finished parts; an interrupted job reports them at restart
  without resuming. Jobs outlive the page that started them.
- Timeout. Every call has a 180-second subprocess timeout (`session_summary_call_timeout`). No call
  starts unless its full timeout fits inside the remaining whole-job seconds.
- Off switch. Turn off summaries, one press from the notice and the card, stops every summary call
  until it is turned back on, and an answer of off already stored survives restart and upgrade.
  It changes neither Analyze's grant nor a goal-summary answer, and it cancels a summary call
  already running. A stored Pause model calls also refuses every summary call, with the reason
  `model-calls-paused`. Its summary switch is disabled while paused and says "Model calls are paused";
  its stored answer is preserved through pause and resume. The first summary shows a
  non-blocking notice naming all the carriers above, Claude Code/Anthropic and the configured
  destination, and the off switch. A new destination or wider content tier repeats the notice.
  Each part rechecks grant, destination and content; this source sends no tool output and
  cannot infer a tool-output grant. Turn off summaries, Delete summary, Discard everything and
  Cancel bar late publication: a reply that returns after one of them is not stored. Delete summary
  takes a second press, like Discard everything, and says what it removes before it does.
  `--no-observer-model` refuses every summary call at startup.
- Storage. A store of its own under `COMPASS_HOME` (by default `~/.compass`), keyed by harness and
  session and independent of any saved intent, so a session with no saved words can have one. Discard
  everything deletes the discarded session's summary, stopping one being written first, and only
  after a clear that landed over words that existed; a clear over nothing typed leaves it. If that
  delete fails the reply says so and the page names Delete summary as the way to finish. Each field
  is named and admitted. Strings are redacted on the way in and again on the way out, because any
  local process can rewrite the file. It has an aggregate byte bound and an eviction that can never
  push out a reader's saved words. Delete summary removes one session's summary, which the next
  open of that finished session makes again unless summaries are off or model calls are paused, and
  `--forget` deletes the store. Invariant 2 names its separate file and 64 MiB aggregate bound.
  `--no-annotations` does not govern this store: summaries need no saved intent. The model job
  must honor `--no-observer-model`; this store only reads, writes and deletes local state.

A violation is a security bug on the same terms as the bounds above, and also: a summary call made
after Turn off summaries or under `--no-observer-model`, a part sent after consent or the
destination changed, a job that passes its ceilings or charges Analyze's cap, a stored string that
leaves the store unredacted, or an eviction that removes a reader's saved words.

What is accepted rather than solved: the code checks that a citation names a real entry and sets a
bullet's kind from it, but it cannot check that the cited entry is relevant to the sentence. A local
rewrite of the store faces the limit the 2026-10-05 delegated acceptance records for a reading's
`detail`: redaction and escaping apply, and nothing authenticates model output against a local
process that can rewrite the file.

### The Live monitor

Ruled 2026-10-23 by the owner
([DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)).
With the switch on and the session on screen, a Haiku check of the latest turns runs about once a
minute and produces the live drift level. It is a call the reader starts, under
[DEC-28](docs/design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts),
with a `monitor` notice shown before the first charged call.

- What is sent. The saved goal, and, redacted and clipped first, the person's own messages, the
  agent's replies, the commands of checks with their result, every other command as its masked line
  with its exit status (a command that cannot fail is left out), and the paths of files written, from
  this session's own record only. The recent window is sent again by each later check, and again each
  time the switch is turned off and on. Where Compass cannot name the destination, checks and paths are
  not sent, as for Analyze. No command output, file contents or other tool output is sent.
- How it runs. A supervised `claude --print` child on an explicit Haiku id, set with `--claude-monitor-model`
  (default `claude-haiku-5-5`; only an explicit Haiku id is accepted, and the reading model's Sonnet floor is
  unchanged), with no tools and no session persistence, in a private working directory. It is never resumed into or injected into the watched
  session. Nothing is written into the session.
- What holds it. A lease in memory, one per session, held by any number of tabs. A tab beats about every
  20 seconds, and a visible tab that stops for 50 seconds has left. A hidden tab pauses the checks and
  keeps the lease. The lease ends when the last tab leaves, the session ends, model calls are paused,
  nobody answers the 20-minute question within 10 minutes, or a cap is spent. A restart starts with no
  lease and makes no check until a page starts one.
- What caps it. At least 60 seconds between two checks of a session, 30 checks per session per window,
  and its own rolling 24-hour cap across the board (240 checks at present), kept apart from Analyze's. A check cancelled by an
  Analyze press is not refunded.
- What is not known yet. The page labels its level `Live monitor · Haiku`, and its accuracy check has not
  been run: it ships labelled and is qualified later, so read its level as an account of the latest turns,
  not a measurement.
- What it never does. It never feeds or triggers the unasked lane and never raises a notification.
  The estimate stays as the level when the check is paused, capped, failed or has not run.

### The abstention check

The `Analyze drift` control (formerly named `Ask for a reading` and `Check for drift`) is enabled by
the captain's acceptance of the recorded case review on 2026-09-14, published as `reading_check: "accepted"`. The amended enablement rule is owned by
[DEC-17](docs/design-reading-a-session.md#amended-2026-09-14-the-captain-accepts-the-case-review).
The acceptance record under `docs/abstention/` carries only marks, hashes and decision metadata.

The Claude Code producer has its own gate, opened by the owner's acceptance on 2026-10-02 and
published as `accepted`, never `passed`: every scored Claude Code run failed, and
[claude-acceptance.json](docs/abstention/claude-acceptance.json) lists each one with its own
verdict, digests, counts and spend, which a test reads back from the result files. It carries no
session text. The results, their grants and the spend ledger are unchanged. The amended rule is
owned by
[DEC-21](docs/design-reading-a-session.md#amended-2026-10-02-claude-code-is-accepted).

The evaluator still asks whether the producer says `not verifiable from available evidence` on
every case a person marked, in advance, as one it should not judge. Two scripts run it, both
outside the gate and neither in CI, and the ruling of 2026-09-10 on what they may hold is restated
here so it is not rediscovered.

The cases stay local and uncommitted. `scripts/mark_abstention.py --build` writes
`abstention-cases.json`, and that file stays on this machine, under `~/.compass`: it names the
session ids the cases were drawn from, and for a Claude session it carries the opening user turn,
which is prompt text. Historical replay packets also carry the frozen session row and semantic
facts, a user message's fact with its whole words up to 1,000 characters as a reading reads them;
they have the same local-only boundary. It is never committed. Only the expectations and
the results are committed.
`abstention-marks.json` holds one sixteen-character hash of `(harness, sid)` per case and two tokens,
`judge` or `abstain`. Replay marks also hold a hash binding them to the frozen packet.
`abstention-results.json`, the scorer's local half, may
carry the producer's withheld reason and its cutoff sentence and also stays under `~/.compass`; the
committable summary the scorer writes to `docs/abstention/` carries case ids, marks, outcomes,
counts, coverage, the sha256 of the marks file as scored and a timestamp. Replay summaries also
hold a hash of the cases and rubric, so changing either invalidates the report. No session id, no
project, no title, no prompt text and no model prose reach the repository from either script, and
a test asserts that none of the local half's fields (the session id, the project, the title, the
opening ask, the cutoff sentence, the model's detail) appears anywhere in the summary.

A scoring run names its producer with a required `--producer`, and only `claude` may score:
no Codex spend is authorized for this qualification, so `--producer codex` reports and refuses to
score. A Claude Code run spends the operator's Anthropic capacity through `reading.ClaudeReadingModel`, the
same subprocess and flags as `POST /api/reading` above, pinned to the CLI the run verified. It
spends once per case whose ledger holds anything citable and sends exactly what that route sends
for the same session: a format 5 case's own goal and outcome lines in place of the reader's typed
words, and the bounded, redacted menu of ledger entries. A Claude Code case also carries its checks,
frozen from the transcript as it stood at the capture, with their redacted output tails, as a press
with a tool-output grant would. The owner authorized that sending for this qualification only,
2026-09-24, and bounded it at twenty calls, one of them the browser walk. The owner later
raised the ceiling to 23 scorer calls and 26 Claude CLI invocations overall, and on
2026-10-01 directed the qualification to run to completion within it. When the second
continuation failed and had spent the last of those calls, the owner authorized one more five-case
run past that ceiling the same day: 28 scorer calls and 31 Claude CLI invocations overall.

The scorer refuses to start unless the call reaches Anthropic (`reading_route.destination` names
`Anthropic`) through the native installer's CLI, whose version file and `--version` line agree, and
unless every case is marked with closed tokens. On macOS the CLI must also satisfy a pinned code
requirement, checked with `codesign --verify --strict` before the file is first run: signed
through Apple's Developer ID chain, identifier `com.anthropic.claude-code`, team `Q6L2SF6YDW`
(Anthropic PBC, measured on 2.1.283). An unsigned stub saved in the install layout is refused, and
so is a machine where `codesign` cannot run. No other platform checks a signature. Linux
has none to check, and whether the Windows CLI carries an Authenticode signature was never measured.
There the committed result records the binary's sha256 as `unchecked sha256:<hex>`, which names
the file that ran and not who built it. The scorer copies bytes from one held regular-file handle
into an owner-only (0700) private directory, checks the handle's identity before and after the
copy, and makes the executable read-only to its owner (0500). It refuses a source larger than
512 MiB before allocating the destination and stops if the source grows past that limit during the
copy. Signature verification and
`--version` run against that copy, and every scoring/probe call uses it. Rewriting or replacing
the installation after the copy cannot select the executable for those calls. The context removes
the copy when scoring or probing ends, including refusal paths and interrupted verification.

The committed summary names the producer, model, argv digest, destination, installation path
with the home directory written `~`, version, signature phrase and copied-byte digest
(`binary_sha256`). A resume carries records only when a versioned ledger run digest binds them
to the full current producer binding, including the copied-byte digest. Editing the local summary
cannot supply that match, and legacy records-only run digests refuse resume. A resumed case whose
source no longer passes provenance checks replaces its former result with a withheld record without
another model call. The private file's
device, inode, size, mtime, ctime and sha256 are confirmed
unchanged before and after `--version`, and compared before every call
(`score_abstention.PinnedClaude`). Each identity read samples metadata before and after hashing.
A changed copy refuses that call and every later one. A process running as the reader can still
rewrite or replace files inside its own private directory between a check and spawn; this does
not defend against the account itself. On macOS the authentic CLI's held-handle copy was measured
on 2026-09-29: equal sha256, valid pinned code signature, and successful `--version` and `--help`
under an OS no-egress sandbox, with zero model calls. The same version's authentic Linux ARM64
ELF was measured the same day: its signed release manifest and pinned Anthropic signing-key
fingerprint vouched for the source hash, the held-handle copy had equal sha256, and both commands
succeeded as a nonroot user in a container with no network, no capabilities, and an isolated
HOME/config/cwd. Both platforms returned 22 stdout bytes for `--version`, 22,114 for `--help`,
and no stderr. Linux x64 and Windows copied-CLI behavior remain unmeasured. On Windows Python
3.11.0 through 3.11.9, a shared temporary directory may not honor the requested owner-only ACL; this
platform has not been qualified for real scoring. Synthetic helpers
establish copy/cleanup mechanics, and do not replace those native measurements. The previous
installation-path pin was chosen while copied-CLI behavior was unmeasured; the macOS and Linux
ARM64 prerequisites are now satisfied, and the same-owner limit remains explicit.

Local preparation owns its cwd, output file and descriptor before yielding. An interruption before
charge removes them and is re-raised. Every call is charged after successful local preparation and
before it runs to one JSON ledger at a fixed path under `~/.compass`, under an exclusive lock,
with the digests of the marks and the cases it was made under. It never follows `COMPASS_HOME` or `HOME`: the home is the account's
own, and scoring refuses while `HOME` names another. Without an observable account home,
canonical roots stay unavailable and scoring refuses before runtime configuration, packet reads
or executable verification. The committed result records a hash chain
over the ledger's charges and their digests, and scoring refuses while the ledger does not begin
with it, reading the committed result at its fixed path whatever `--out` says. The scorer also
re-checks each case's provenance against this machine's transcripts, history and ends, and spends
nothing on a case that claims recorded and is not vouched for. One lifecycle may be vouched by the
transcript rather than the history store: a Claude Code turn stop older than the store's oldest
observation, which the transcript's own top-level `stop_hook_summary` for that session marks at
that moment. A stop the store still reaches is never vouched that way, and a stop or end that had
not settled before the capture is refused at score time as it is at freeze. Whoever can edit the
transcript or trim the history store's oldest observations can already forge either record, which
is the local-process exposure this document accepts throughout. For a Claude Code case that includes
its contents, rebuilt from the transcript as it stood at the case's `captured_at`. The
checks and their output tails must be exactly the transcript's. The user messages must be the
newest ones up to the capture, in order, with none missing between them, none repeated, and at
least as many as the board's bounded tail reads of the transcript as it stood at the capture, whose
length the case records (`transcript_bytes`), and no case may name less than that length
(`transcript-bytes-differ`). A case the freeze cut at its capture (`transcript_cut`) must name it
exactly; its user messages come from the transcript as it then stood, never from the board. An
older message may be absent, because the board read a bounded tail. A fresh `--score` never
replaces a written result that charged calls; only `--resume` rewrites one. A transcript now shorter than that length, or a case that
records none, is demoted (`transcript-truncated`). A capture with a user or assistant message
between the recorded stop and itself is refused at freeze and demoted at score time
(`activity-after-stop`); administrative records such as turn duration do not resume work.
If the bounded parent check scan cannot reach the capture cutoff, freezing refuses and the
score-time contents check demotes the case (`check-cutoff-unreachable`). A case frozen under other
parser code is named as such (`frozen-on-another-parser`) rather
than read as tampered. The stamp hashes a versioned AST representation of the derivation files:
the shared byte reader, check producer and reading producer. Comments and formatting do not move
it, while literals, expressions and control flow do. Existing
byte-stamped packets remain incompatible; neither cases nor marks are rewritten to fit the new
stamp. A mismatch still refuses the whole scoring run before consulting or charging its ledger,
and the contents check still requires the facts derived at capture to match. On Windows the home falls back to `USERPROFILE`, so the
`HOME` protection is POSIX only. The ledger stops at 28 calls across every
run and producer, refuses every call when it cannot be read, refuses calls under other digests, and
freezes each packet's marks once it holds one. A failed run may be followed by a fresh packet only
through a reviewed, fixed-path continuation grant: its marking phase binds the old result's exact
ledger prefix and a new case digest, and its sealed phase binds the new marks and cases-and-rubric
digests before scoring. Each later grant may follow a continuation that also failed, bound to that
result the same way, and only while every earlier grant is sealed with a `next` key equal to the
following grant's `previous`. A grant without its predecessor, numbered past the chain's fixed
bound of nine, or under a name the pattern never writes, is refused. Every earlier packet's charges must carry its own key, in ledger order,
and the whole chain is checked under the charge lock against the same 28-call cap. The failed result cannot be overwritten, and a grant is not permission
to send real session evidence or increase spend; both need separate owner authorization. The
ledger holds case ids, times, statuses and digests only. The
scorer does not pass through the reader's rolling budget, so that ledger is the bound.
`--probe-argv` writes and charges nothing, and it cannot reach a real model through anything the
operator configured. It starts its own stub on `127.0.0.1` and runs the verified CLI twice, once
signed in with a placeholder API key and once with a placeholder OAuth token and a placeholder
account (a random `@example.invalid` email and a random UUID) in a config directory of its own, so
the operator's account is never read. Removed from its environment: every `ANTHROPIC_*`,
`CLAUDE_CODE_USE_*` and `CLAUDE_CODE_*OAUTH*` variable, `CLAUDE_CONFIG_DIR`, `http_proxy`,
`https_proxy`, `all_proxy` and `no_proxy` in either case, and the CLI's own
`CLAUDE_CODE_HTTP_PROXY`, `CLAUDE_CODE_HTTPS_PROXY` and `CLAUDE_CODE_PROXY_URL`. It refuses to run
when `reading_route.destination` would name anything but the stub, and counts the call good only
when the reply carries a nonce only the stub knew (recorded probe: refused, not charged). It reports
only yes or no facts about each request, never its text: whether the home path, the user name or
the state directory appear anywhere, and in the OAuth pass whether the placeholder email appears
in the disclosed block and whether the email or UUID appear anywhere else. Any of those found
fails it. It cannot see traffic that went elsewhere; only an OS sandbox can. The failed Claude Code
result is `docs/abstention/claude-results.json`; an authorized continuation has its own file, as
[the abstention documentation](docs/abstention/README.md#the-spend-ledger) specifies. Neither opens
the gate by being written. A case the producer refuses before the model, an empty ledger or a
session the board no longer lists, spends nothing. The yardstick is handed to the producer as an
argument; the run writes nothing to `compass-annotations.json` and increments no reading count.
Historical replay reads the frozen row, facts and clock instead of the live board. Reviewer
excerpts and later context are not model inputs. Its file format and checks are owned by the
[abstention documentation](docs/abstention/README.md#historical-replay-case-format-4).

Synthesised cases are admissible in the rubric expectation file, cross-verified by a different
agent than generated them, and their text is agent-written rather than recorded. It goes through
`records.safe_text` before the producer sees it: redaction before the clip, in that order, the same
as anything derived from a transcript. The rubric file also stays under `~/.compass`; the summary
records for each of its cases the kind, the origin, whether it was admitted and why not, and the
two scored columns, never the case body. Each of those is a closed token or empty: the file is
hand-written, so an entry naming anything else -- a kind, an origin or a harness outside the sets,
or a key that is not a case id -- is refused rather than copied into the summary.

The drift levels check is a second check under the same rules, and `docs/drift-levels/`
is its committed half. `scripts/levels_cases.py --build` freezes cases from recorded Claude Code
transcripts into `~/.compass/drift-levels/cases.json`. Each case holds the session id, the
transcript path, the working directory, the check lines and written paths layer 1 publishes, and the
intent the owner set for the case. The build refuses a `COMPASS_HOME` inside the repository. The
owner's marks stay beside the cases, and only their sha256 is committed, in `marks-digest.json`,
before any reading is attached or any result is written. Readings attached afterwards, which carry
model detail, stay in `~/.compass/drift-levels/readings.json`. `results.json` carries case ids, closed kind and reason
tokens, marks, levels, outcomes, the digests and a timestamp. It carries no session id, path,
command, intent text, fact id or model prose, and a test asserts that none of the local fields
appears in it. Scoring calls no model and writes to neither the annotation store nor the reading
route. `levels_cases.py --read` is the one mode that calls a model, and it runs only when the owner
says to. It sends one case's frozen facts and intent to Codex, the way a press sends a Claude Code
session's record, but with no check output and no user messages, since the cases froze neither.
A press sends the messages you typed; this sends none. It charges the reading home's reading ledger
and never writes the annotation store. What comes back stays in
`~/.compass/drift-levels/replayed-readings.json`. Its record, `replay.json`, holds case ids, closed
tokens, times, and the ledger job id built from a case id and a time. The [drift levels documentation](docs/drift-levels/README.md) owns its format.

The drift replay check is a third check under the same rules, and `docs/drift-replay/` is its
committed half. `scripts/drift_replay.py` reads the pushback fixtures under `tests/raw_sessions/`
(redacted by `scripts/redact_session.py`, gitignored) or, with `--source original`, the logs under
`~/.claude/projects`. Its cases, its owner's blind marks, its outputs, its spend ledger and the salt
behind its case ids stay under `~/.compass/drift-replay/`, and the build refuses a `COMPASS_HOME`
inside the repository. Its claim items and claim marks, each with the marker's one-line reason,
stay there too. Only count and digest summaries are committed: the digests hold digests and counts, the results
closed tokens, counts, and case and claim ids salted with a local secret, so a committed id cannot
be recomputed from a session id and a time. `--live` calls no model. `--read`
sends what a press on that session would send, through the same verified, pinned Claude Code CLI
the qualification uses: the person's messages, the agent's messages once the producer reads them,
each check's line, result, times and redacted output tail, and the intent. The owner authorized that
send and its spend on 2026-10-03, bounded at 240 calls, raised to 440 on 2026-10-04, and then to
870 on 2026-10-04 for the Analyze drift follow-up, on the same ledger
`~/.compass/drift-replay/spend.json`. That path is under the operator's home whatever
`COMPASS_HOME` says, so moving the home does not reset the count. Each call is charged before it is
made, under an exclusive lock on macOS and Linux (Windows has none, so the cap there holds for one
run at a time), and never by a case the producer withholds or by a dry run; a ledger
that will not parse refuses every call, and the charged calls the run's own record holds are a floor
a deleted ledger cannot go under. Two consecutive charged failures or replies with no parsed
answer stop the batch. Failed cut-arms stay charged and are not stored as read, so a tagged retry
can read them again. With `--source original` the words sent are the session's own,
through only the redaction a press applies, not the fixtures' redaction. It never writes the
annotation store and never posts to the reading route. The
[drift replay documentation](docs/drift-replay/README.md) owns its format.

#### Shared closure allowance, 2026-10-05

The authorized follow-up has at most 239 additional Analyze attempts across all three routes:
190 replay, 31 qualification and 18 live. The qualification and live allowances are included in
239. They cannot be added to it or transferred to another route. The existing 631 replay charges
and 28 qualification charges stay intact, along with their failed results and grants.

`scripts/analyze_campaign.py` reads a reviewed repository manifest and a fixed account ledger,
`~/.compass/analyze-closure-spend.json`. Actual final prompt, model, runtime and output-cap
digests bind each reservation; experimental replay also binds its study code and condition.
Reservations precede transport, and failures remain charged. Immutable reservation,
classification and acceptance receipts detect missing or rewritten state. A reviewed zero-charge
genesis digest is required for activation; an activated campaign never creates replacement
state automatically. This guards accidental reset, not an account holder who rewrites both the
repository authority and every private receipt.

Every admission validates the current ledger and each ancestor. Proof assembly may use the
snapshots validated during that admission; it cannot cache them for a later request.

By default, the lanes run in replay, qualification, live order. Each registered batch needs measured,
independently reviewed acceptance before the next batch. Transport usability is insufficient.
A semantic, coverage or protection failure stops every lane, as do two consecutive unusable
charged attempts, except for the finite semantic-measurement amendment below. Pending or
orphaned attempts block another launch. Batches charge at most
25 attempts including retries, and each lane opens with one availability attempt. Only an
explicit same-slot retry under its registered allowance can follow an unusable opening.

Future inputs may be explicitly held without invented request hashes. Held slots cannot spend,
be skipped or pass acceptance, and the authority has no unholding or reset API. A live wrapper
in `scripts/live_analyze_campaign.py` reserves at the unchanged production executor seam after
the native consent route and refuses unmetered Codex execution for that foreground process.
Its instrumentation supplies no complete process or network trace. Native replay
preflight binds its fixed ten-file implementation inventory and actual checkout.
Every registration requires an exact positive integer repeat and a unique
`(phase, case, arm, condition, repeat)` identity; extra metadata cannot shadow a pair.
Every declared critical group requires three static registrations with distinct integer
repeats 1, 2 and 3 before charge. The ten historical protected rows must have distinct
`(case, arm, claim)` identities; missing or unknown independent admission refuses before
the first replay model charge. Unsupported semantic conditions refuse rather than pass unread.
When neither observed arm draws a required protected claim, unresolved comparison adds
a coverage failure and blocks acceptance. Future pairs with no outputs remain pending;
the comparison does not require a favorable legacy result. The production pilot forwards
the supplied stamp-bound final lookup like the shipped reading prompt builder; matched
scope and first-1000 controls remain explicit comparisons.
Historical protocols remain unchanged and need separate, independently reviewed
prospective translation before activation; translation alone grants no source admission.
No campaign is activated by installing this machinery, and no earlier failed qualification
becomes a pass. The [replay documentation](docs/drift-replay/README.md#the-shared-closure-guard)
owns the preparation and measurement boundary.

##### Qualification-first priority, 2026-10-06

The owner may authorize a prospective qualification-first campaign within the same 239-attempt
allowance. Its only alternate order is qualification, replay, live. All 30 qualification slots
must have actual request bindings; the 31-attempt limit includes its one registered retry.
Every replay and live slot must be explicitly deferred. Their fixed planned slot identities
and batch partitions remain, but their request maps are empty and their protocol, binding and
evidence fields are explicitly `null`. Those fields express absent admission, not placeholder
hashes or an exemption from a source requirement. A partially held later lane or held qualification
slot refuses this profile.

Qualification can then reserve without replay acceptance. Its sealed fourth grant, actual native
source and prompt checks, model and packet bindings, independent batch reviews, historical
631/28 prefixes, shared ledger and activation guards still apply. The 190 replay and 18 live
allowances cannot be borrowed. Held lanes cannot reserve or pass either batch or lane acceptance.
A failure still stops the whole campaign. Replay's original protection obligations remain pending
behind its hold; qualification must independently meet its own typed native source and five-kind
floor. This profile does not depend on completing separate observer, ordinary-session, cold-study
or native-window measurements.

This is a new reviewed prospective authority, not a migration of an activated campaign.
Its manifest remains immutable: there is no automatic unholding, replacement genesis or reset.
Releasing the held lanes later requires a separate reviewed design that preserves charged
attempts. Installing the guard or preparing cases does not activate it or supply blind marks.

##### Charge-preserving qualification successor, 2026-10-06

The owner authorized 31 fresh qualification attempts after the stopped run reached 30 native
qualification charges and two shared charges. This replaces the stopped lane's 29 unused
attempts; those cannot be added again. The fifth grant's bound key has a cumulative native
ceiling of 61. Earlier keys retain their 28 or 59 ceilings. With 190 replay and 18 live attempts
still held, the cumulative shared allocation is 241: two spent, 31 fresh and 208 held. No held
allowance can be transferred to qualification.

The fixed successor manifest and independently reviewed handoff bind the original manifest,
activation anchor, complete two-call shared state, thirty-call native prefix, failed fourth
result and actual native/shared attempt joins. The old semantic stop is established by its
settled failure receipt; an explicit stop receipt is bound only if it already exists. The
successor never creates a stop file for the old run or rewrites its failure.

An explicit one-time initialization appends one epoch to the same account ledger under its
existing lock. The original state projection, excluding only the new `epochs` field, and its
receipts remain bound. New transition and reservation receipts live in the separate
`.epochs/1/` tree. The new epoch has its own reviewed zero-charge activation anchor and fresh
batch acceptance; it cannot inherit the old opening batch's acceptance. The original campaign
remains stopped and inspectable. Missing or changed ancestor, transition, handoff, source or
grant bindings refuse further launches.

The fifth grant and handoff require newly frozen case, marks, rubric, model and actual request
bindings. Qualification alone may spend up to 31 attempts, including its opening exposure and
one registered availability retry. Replay and live remain held. The existing failure, orphan,
batch review and source guards apply to the new epoch. Installing this software neither
initializes an account nor supplies a grant, source admission or accuracy result.

##### Login-repaired qualification continuation, 2026-10-07

After the owner reported repairing Claude Code sign-in, they authorized carrying the fifth
run's 29 unused attempts forward and adding two. The sixth grant admits 31 available attempts,
including the first diagnostic exposure and one retry. All 32 native charges and four shared
charges remain spent. The cumulative native ceiling is 63 and shared allocation is 243,
including the unchanged 190 replay and 18 live attempts held. Earlier keys keep their earlier
ceilings. This is one finite continuation, not permission to reopen arbitrary stopped runs.

The fixed login-resume manifest and independent handoff bind the stopped fifth result, all
ancestor manifests, transitions and reservation receipts, the exact native 32-call prefix,
and the new source, scorer, packet, marks, model and request digests. Initialization appends
only epoch two under the existing account lock; both earlier epochs remain unchanged and
inspectable. No earlier batch acceptance carries forward. Missing or changed ancestry refuses
execution. The original three-repeat protocol and batch stops remain required.

Only qualification opts into execution diagnostics. Its raw stdout and stderr stay in private
transient files and are deleted at cleanup; neither is added to a diagnostic receipt. Both
streams retain independent supervised file-size limits. The receipt holds the charged attempt
identity, request/model digests, actual return code when available, monotonic elapsed time,
closed exception category and a closed reason label from at most the first 8 KiB of each error
stream. A text match is a CLI-reported hint, not proof of provider causality. Successful answer
text is never used to classify an authentication problem. Diagnostic receipts stay in the
owner-only packet directory (0700, files 0600), never public results or dashboard data.
Unwritable or non-private diagnostic storage refuses before charging; a later write failure
cannot refund a charged attempt or authorize another call.

##### Per-clause qualification continuation, 2026-10-07

After the sixth run stopped on an accuracy failure, the owner authorized a corrected producer
and a fresh qualification. The seventh grant carries its 29 held attempts forward and adds two,
for 31 available attempts: thirty readings and at most one availability retry. All 34 native
charges and six shared charges remain spent. The cumulative ceilings are 65 native charges and
245 shared attempts, including the unchanged 190 replay and 18 live attempts held. No earlier
key receives the new ceiling, and a semantic stop cannot be retried.

The fixed per-clause manifest and independent handoff bind the failed sixth result, its accepted
opening batch, every earlier stopped epoch and immutable reservation, and the exact native
34-call prefix. New source, scorer, packet, marks, model and request bindings precede execution.
Initialization appends only epoch three under the existing lock. Missing, changed or unfinished
ancestry refuses execution; older epochs are never reset or resumed. Installing the software
does not initialize an account, admit a packet or supply a passing score.

The full pre-execution suite caught a scope omission after the zero-charge preparation was
activated. A fixed, independently reviewed zero-charge reseal record binds both preparations,
their handoffs and the exact original transition bytes. It permits one replacement of epoch
three's strictly empty genesis, before any reservation or charge. An exclusive immutable reseal
receipt is written before the account update; the original transition and every charged ancestor
remain intact. Missing or mismatched records, a partial update, a second reseal, or any attempted
reading refuse execution. This correction adds no allowance and cannot repair a scored failure.

The opening is the first registered exposure, followed by batches of nine, ten and ten with
independent review between them. No old acceptance carries forward. Existing source, diagnostic,
charge, retry and stop guards remain required. This is one finite continuation, not permission
to reopen arbitrary stopped runs or borrow held replay and live allowance.

##### Clause-isolation qualification continuation, 2026-10-07

The seventh run identified both sampled Goal departures but judged an approval-qualified
outcome whose scope was unknown. It stopped after two charged readings. The owner approved
carrying its 29 unused attempts forward and adding two, giving one new 31-attempt allowance
for thirty fresh readings and at most one availability retry. All 36 native charges and eight
shared charges remain spent. The new cumulative ceilings are 67 native charges and 247 shared
attempts, including the unchanged 190 replay and 18 live attempts held. Earlier grants retain
their own ceilings, and the current semantic stop cannot be retried.

The fixed eighth grant, manifest and independently reviewed handoff bind the stopped seventh
result, every charged ancestor and immutable receipt, the seventh run's opening acceptance,
and its original zero-charge transition and reseal. Initialization appends only epoch four;
no earlier state, stop or acceptance is reset or carried forward. Missing or changed ancestry
refuses execution. Admission and the complete local checks precede zero-charge activation;
merged software and passing CI precede every model call.

Source-derived inputs bind the corrected producer, parser, scorer, exact native model request
and binary before output. A changed attribution criterion must declare its scope and receive
fresh independent pre-output marks and rubric adjudication. Unchanged expectations may transfer
only after their material, scope and selection are independently checked. No result is regraded
and no answer from a changed producer counts toward the new run.

The first exposure is the one-call opening, followed by independently reviewed batches of nine,
ten and ten. The existing semantic, coverage, charge and availability guards remain; one retry
cannot cross a semantic stop. This is one finite continuation, not authority to reopen arbitrary
runs, increase an older ceiling or borrow replay and live allowance.

##### Conditional-priority qualification measurement, 2026-10-07

The eighth run stopped after two parsed answers because an approval-qualified outcome was
judged without established approval. The owner approved carrying its 29 unused attempts
forward and adding two, giving 31 available attempts for a fresh thirty-reading measurement
and at most one availability retry. All 38 native and ten shared charges remain spent.
The new cumulative ceilings are 69 native and 249 shared attempts; replay's 190 and live's
18 attempts remain held. Older grants and their stops retain their original limits.

The owner also removed the requirement to stop measurement at its first failing semantic
batch. Only the ninth-generation campaign may continue to the next registered exposure after
a semantic failure. Every wrong answer, grade and charge remains recorded. Such an exposure
is terminal measurement evidence, never a retry slot. Batches of one, nine, ten and ten still
require independent measured review. A measured review records the actual failures and cannot
stand for qualification acceptance. A failed aggregate remains failed and cannot arm another
lane or the qualified browser-verification route.

Coverage, protection, orphan and source-binding failures still block launches. An unstopped
process or oversized response latches a protection stop without retry. The existing limit
on consecutive unusable attempts and the single registered availability retry remain. No
option or arbitrary manifest field can remove these checks or increase the finite allowance.

The fixed ninth grant and reviewed handoff bind the complete paid predecessor, including
its accepted opening, every earlier failed result and immutable receipt, and both original
transition and reseal in epoch three. Ordinary initialization appends only epoch five;
it resets no earlier state and carries no prior batch or lane acceptance. Missing or changed
history refuses execution. Source admission and the complete local checks precede activation;
merged software and current-head passing CI precede spending.

Fresh source-derived inputs bind the corrected producer and scorer before output. Unchanged
expectations may transfer only after their scope, material, selected entries and citation
menus are independently checked. A changed producer cannot reuse earlier answers or regrade
an old packet. This amendment permits completing one finite measurement, not reporting a
failure as a pass or reopening an earlier stopped run.

##### One qualified Claude-only browser reading, 2026-10-07

After the ninth-generation qualification passes, a separately reviewed profile may allocate
one of the existing 18 held live attempts to a foreground browser reading. The other 17 live
and 190 replay attempts remain held; this adds no attempt to the 249 shared ceiling. The
profile binds the actual qualifying result, all thirty usable exposures, full qualification
acceptance, current runtime and scorer, model request and independently reviewed browser
context. Measured batch reviews cannot supply that acceptance. An explicit technical stop
refuses the route even when an earlier qualifying result passed.

The wrapper starts the genuine application and preserves its consent, provider selection,
collector, resolver and native executor. Its private PATH excludes Codex; background reading
is disabled. Before the press, disclose Claude Code and Anthropic and bind the selected
session, saved intent, consent, startup identity and exact prompt. Only this registered
foreground request may launch the model. Construction and mocks establish no browser pass.

The route account and context use a separate fixed conditional-priority namespace. Its
exclusive activation marker remains outside that namespace, at
`~/.compass/claude-route-live00.ACTIVATED.json`, so deleting an account or restoring a prepared
profile cannot mint a second allocation. Every reservation stays charged, and settled
failures are immutable. A late source change cannot hide an already charged native warning
or prevent its durable closed settlement. Missing state, orphaned calls, unknown statuses
and source or admission changes refuse another launch; no retry is allocated to this route.

#### Prospective qualification source cuts, 2026-10-05

The opt-in typed-Claude qualification freezer may make an owned transient copy of the raw
historical source prefix, as the replay already makes a cut transcript. This is a study-input
exception to the runtime's memory-only source recovery rule, not permission to cache recovered
replies. The source-cut helper admits a prefix no larger than 32 MiB and uses bounded lookahead
to prove the capture boundary, refusing records over 1 MiB. The existing freeze and vouch
provenance scans retain their separate limits. The source is opened without following a symlink
where supported; its
descriptor identity and source stamp must agree before and after the read. A 0700 temporary
directory and a 0600 file hold that raw input only while the stamped production reader runs.
Normal completion, refusal and exceptions remove the cut. Abrupt process termination may leave
an owner-only temporary copy, which the operator must remove; the code does not promise secure
erasure or protection from another process under the same account.

The frozen packet retains existing bounded agent excerpts and exact selected identities,
prefix, word and prompt digests. Recovered complete replies remain in memory and enter no new
packet field, marker output, cache or history. Later source appends may be ignored beyond the
bound capture prefix, but a changed prefix or selection refuses before transport. Existing
packets are never upgraded. This first prospective protocol refuses adopted goals and sourced
outcome lines; it establishes neither their qualification nor model accuracy.

The model-free studies use separate tagged cohorts under that same private directory. Their
initial blind marks stay private before later proof is opened. The exact imported cohort,
including the later proof key where used, is bound by committed counts and a digest before
output. Positive-proof marks name only recorded evidence in the private key. The Codex study loader
reads an operator-selected CLI or editor parent log, rejects exec and worker metadata, applies the
runtime's measured injection filter and masks words before private storage. Its committed result
holds one salted case id, counts and a digest. It calls no model, adds no runtime fact and grants
no Analyze eligibility. The historical replay cases and reads are not overwritten.

#### Reviewed native export intake, 2026-10-06

The owner-approved qualification source work also admits explicitly reviewed Claude Code
exports outside the canonical projects directory. The marker's export freezer and the scorer's
reporting and scoring modes require the paired
`--reviewed-exports` manifest path and `--reviewed-exports-sha256` digest. The manifest has a
closed schema, at most 32 distinct full session UUIDs, canonical absolute regular-file paths
whose basenames match those UUIDs, and complete-file SHA256 digests. Its review fields record
the caller's review; they do not authenticate a reviewer or confer trust on a case-supplied
path. The caller must independently choose the manifest and pin its digest. A process able to
rewrite all local inputs remains inside the accepted same-account trust boundary.
Claude case specs under this explicit resolver use eight lowercase hexadecimal identity characters.
Malformed ids and full-UUID aliases refuse before board, history or canonical-source fallback;
the manifest still binds the full UUID. The default path without this opt-in is unchanged.

This initial import admits only idle captures with an exact native Stop timestamp, the configured
settle interval, and no conversation continuation through the capture cut. The Stop must name
the preceding top-level, non-meta, non-sidechain assistant `end_turn`, with a valid earlier
human ancestor in physically prior UUID ancestry. Native metadata clocks may be skewed; parent
wall-clock ordering is not required. The final and human ancestor must yield their native text
events, which excludes thinking-only, synthetic-agent and injected-only records. This does not
require the ancestor to survive prompt selection or guarantee whole final-word allocation.
Missing `hookLabel` means `Stop`; another explicit label refuses. This route
currently supports only `preventedContinuation: false`. A true value is unsupported here, not
proof of continuation; the canonical collector and its existing Stop semantics are unchanged.
The first physically future record ends the prefix even if a later-written record is backdated.

The manifest is limited to 64 KiB, each complete source to 32 MiB, and each native record to
1 MiB, counted on the native newline-only record boundaries. Literal carriage returns inside a
record or between JSON objects on one line refuse; CRLF terminators and escaped JSON carriage
returns remain valid. Nonregular files and symlinks refuse; opened descriptor and path stamps must agree
through the bounded read. The existing 8 MiB check scan and 400,000-byte tail remain unchanged.
An admitted export is rebuilt directly through the native freeze helpers without a live board
read. Source lookup, machine vouch and the scorer use the same explicit resolver. Immediately
before the charging delegate, the scorer rechecks the manifest, complete source, native cut,
case and production selection, plus the current intake scripts and runtime parser stamp.
Changing even source bytes beyond the prefix requires a new reviewed manifest and packet.

The source-cut exception above still governs transient raw input and cleanup. Receipt metadata
is separate from the production-reading seal; it adds no complete reply cache or new evidence
class. Existing cases without a receipt retain their canonical provenance rules and are never
upgraded by a matching UUID. Import establishes source and lifecycle eligibility only. It does
not supply semantic blind marks, a genuine-kind verdict, accuracy, a grant, campaign activation
or permission to bypass a spend guard.

A violation here is a committed file under `docs/abstention/`, `docs/drift-levels/` or
`docs/drift-replay/` carrying a session id, prompt text, a recorded command or path, or model prose,
or a scoring run that reaches the annotation store or the reading route.

### Cockpit dispatch and terminal reads

Dispatch markdown is read from `XDG_RUNTIME_DIR/spacedock-dispatch` when available, with the
legacy `/tmp/spacedock-dispatch` path retained for existing producers. The legacy location is in
a shared temporary namespace where another local user can plant matching filenames; a filename
match alone establishes neither ownership nor safe contents. Both use the same checks:
`O_NOFOLLOW`, an anchored directory descriptor, realpath containment, regular files owned by the
current uid, and refusal of group- or world-writable files. Files larger than **65,536 bytes** are
refused, including growth during the bounded read. The directory must also belong to the current
uid. Platforms without the POSIX no-follow and ownership checks refuse this source. The 32 MiB
semantic backfill limit applies to transcripts, not dispatch artifacts: a dispatch is a short
Markdown file, and a transcript-sized allowance would let a planted artifact force a large read.

`SPACEDOCK_BIN`, when set, must be absolute; otherwise discovery resolves `spacedock` and also
requires an absolute result. Accepting a relative override or resolution could execute a planted
program when the working directory is on `PATH`. The child gets only `PATH` (the OS default),
`HOME` and `LANG`, a fixed argv without a shell, and a two-second timeout. Discovery output over 64 KiB is rejected after
capture; that is a parsing cap, not a streaming bound on subprocess output allocation.

The terminal registration file is created with mode **0600**. Its reader checks that exact mode,
uid, regular-file type and a **16 KiB** limit on the opened descriptor, refusing symlinks.
This capability trust check is POSIX-only; platforms without `O_NOFOLLOW` or `getuid`, including
native Windows, refuse terminal registration and report why. Shutdown uses a separate bounded
regular-file read of `server_generation` solely to decide whether to remove its own file. That
cleanup read does not require ownership or mode checks and never consumes a token, port or lease;
it preserves files with a different generation, nonregular files and files over the byte cap. The tmux
adapter attaches with `-r`; it exposes no pane-input method, HTTP input/control requests refuse,
and any client WebSocket frame closes the connection. Control lines and queued output each have
a **64 KiB** byte cap; overlong frames disconnect instead of growing the buffer. The snapshot
retains at most 12,000 characters. These bounds supplement the 512-frame limit.

The optional xterm JavaScript and CSS are vendored and served at `/assets/xterm.js` and
`/assets/xterm.css`. Only loopback peers with the ordinary origin checks can receive them, and
both return 404 unless the interaction feature is enabled. Serving an asset starts no terminal.

## Antigravity directions (a directions-only transcript read)

The directions reader reads one more file: Antigravity's
`<antigravity.root>/brain/<conversation-id>/.system_generated/logs/transcript.jsonl`, found by
`observer.resolve_directions`. Only records whose `type` is `USER_INPUT` and whose `source` is
`USER_EXPLICIT` are read, and of those only `content`, `created_at`, `step_index` and
`truncated_fields` (`transcripts.antigravity_direction`). The planner's responses and thinking,
tool calls, command records and their exit codes, system messages and conversation history are
never parsed into anything. The file is read by the bounded tail read every transcript gets. It
is refused when it, `brain/<conversation-id>`, `.system_generated` or `logs` is a link: its real
path must be exactly that path under the real `brain/` directory, so a link above `brain/`, such as
a linked `~/.gemini`, is followed and one below it is not. The conversation id is refused when it
could climb out of `brain/`. The reads then open the file without following a link where the
platform has `O_NOFOLLOW`, so a file swapped for a link after the check is not followed. Windows has
no `O_NOFOLLOW`, and a parent directory swapped between the check and the open is not caught on any
platform; both need write access to the owner's `~/.gemini` already.

What is read is the words the person typed, the class every other harness's user messages are
already in. They become steer facts in the observed record, under the same line bound and
redaction as those, and the newest one is the row's title and last prompt when the CLI log does
not carry one, which it does not in 1.2.11. They are also kept in `semantic-work-history.json`,
cut to 112 characters, like every harness's directives, and `--forget` does not clear that store.
After a reader allows a reading, those directions may be sent to the reading model with the rest of
the record, whole up to 1,000 characters where the prompt has room, as every harness's user
messages are, and the opt-in unasked lane, when switched on, may send them without a press, exactly
as it sends a Claude Code, Codex or Pi session's user messages. The file is kept apart from `observer.resolve_transcript` on purpose:
every caller of that one reads work or tool output (the observer, the gate and Spacedock boot
scans, the working-directory read, workflow discovery), and none of them is handed this path, so
"Compass can't read work from this harness" stays true. A direction the harness truncated is
refused by "Add as a line" rather than saved as the whole of what was typed. The shapes behind
this are in
[docs/captures/antigravity/transcript-shapes-1.2.11-macos.jsonl](docs/captures/antigravity/transcript-shapes-1.2.11-macos.jsonl).

## Off-machine nudges (reaching the operator away from the desk)

Every signal Compass sends today needs somebody in front of the machine: the macOS popup, the
browser notification in a tab that is open, the board itself. DEC-4 ruled on 2026-09-02 that
Compass may reach further, in one shape and no other. The operator supplies one endpoint, and
Compass posts a count to it.

This is the section to read before building that, and it grants nothing on its own. The reach endpoint
provides this capability. The outbound surface is the quota poll, the explicitly enabled observer
model, and the operator-configured reach endpoint.

Why this needs its own section rather than an entry under Usage quota reads: that section's
endpoint list is closed, and every entry on it is a vendor Compass chose and verified. Here the
endpoint is one the operator pastes in, so the list cannot be closed and there is no vendor to
vouch for. What bounds the exposure is the payload rather than the destination, which is the
opposite way round from the quota poll and is why the two are not one rule.

The bounds, all of which hold together:

- Off until a URL exists. There is no default endpoint and no provider Compass picked. With no URL
  configured nothing is posted, which is the shipped state today. DEC-4 refused a first-class push
  through a provider Compass chooses, so an endpoint the operator already uses, ntfy, Pushover or
  a Slack webhook being the common ones, is the whole mechanism.
- One destination, and it is the operator's. Compass posts to that URL and nowhere else, follows
  no redirect, and ignores proxy environment variables. Those last two are the rules the four
  forwarders and the MCP server already hold to; the loopback check beside them is the one rule
  that cannot carry over, since the whole point here is a destination that is not this machine. So
  a redirect cannot move the destination after the operator chose it, and that is what replaces the
  loopback guard rather than sitting beside it.
- Counts and states, never a session. The payload carries how many sessions need a human and how
  many finished and were never read. It carries no session name, no project, no title, no path, no
  prompt text and no request text. A person who gets a nudge opens the dashboard to find out which
  session it was, and the count is the whole message.
- Two counts, not three, and the missing one is deliberate. DEC-4's own wording offered a third,
  how many sessions went quiet, and what is missing is not the elapsed reading but the threshold.
  `last_activity` is published on every row and the board renders an idle duration from it, so
  `now - last_activity` is a reading the runtime already takes. What nothing decides is when quiet
  becomes worth a nudge: `config.py` holds no such threshold, and `events.py`'s `stale` is a
  different fact, a finish stamp contradicted by later activity rather than a session that went
  quiet. A third count would therefore have to name its own threshold, and naming one is a product
  decision this section is not the place to make. If DEC-4's third count is wanted, that threshold
  is the work, and it is smaller than it looks.
- Throttled, and a change is what triggers it. At most one post per configured interval, with a
  change in the counts as the trigger rather than a timer, so a board that is not changing sends
  nothing and a flapping one cannot turn into a stream.
- The URL is a credential. A webhook URL is a bearer token wearing a path: whoever holds it can
  post to the operator's own phone. It is never logged, never echoed, never served on the loopback
  port, and never printed by `--diagnose`, which is the handling Usage quota reads gives a vendor
  token. Redaction has to cover the whole URL and not only a query string, because these providers
  put the secret in the path.
- Off switch. The feature ships `--no-reach` with it: a flag that disables the pathway for a run
  regardless of the stored setting, mirroring `--no-usage` and `--no-history` at every one of their
  sites, including the branch that forwards flags to a respawned daemon, so a restart cannot
  re-enable what the operator disabled.

A violation of any of those is a security bug: a post with no URL configured, a post to any
destination but the configured one, a redirect followed, a payload carrying any field beyond the
counts named above, the URL reaching a log line, a `--diagnose` line or a loopback response, or a
post rate above the configured interval.

What is accepted rather than solved: the endpoint is a third party, and what it does with a count
is outside Compass's control. That is the same trust the operator extends to that provider by
using it, and it is a real transfer. A count is a small thing to leak and it is not nothing. How
many sessions on this machine need a human, and when, says that the operator is working and roughly
how hard, to anyone who can read the notification stream. That is stated here rather than implied.

## Process lifecycle: written paths, and `/api/shutdown`

The server writes eleven files, all under `~/.compass` (relocatable with `COMPASS_HOME`,
authoritative when nonblank): `compass-<port>.json`, recording the running instance (`pid`, `port`,
`started`, `log`, `python`); `compass-<port>.log`, where a detached (`--daemon`) instance's
output goes; `compass-dismissals.json`, the sessions the reader marked handled, described in
Dismissals below; `observer/<harness>_<sid>.json`, the sidecar `GET /api/observe` records when a
reader opens that panel for a session, named in invariant 2 above; `compass-history.json`, the
history of what this server observed, described in Local history above;
`compass-annotations.json`, the typed or explicitly adopted goal, typed expected outcome lines and readings taken against
them, named in invariant 2 above and turned off by `--no-annotations`;
`compass-deliveries.json`, what became of each notification this board raised, described in
Delivery records below; `compass-departures.json`, what an unasked reading raised, described in
Unasked readings below and written only with that feature switched on; `compass-ends.json`, the
session ends this board observed, described in Session ends below; `ci-read-off`, the marker the
page's switch for the pull request CI read leaves when it is off, described in Pull request CI reads
above, which holds one line and is removed when the switch goes back on; and
`semantic-work-history.json`, the operator-cockpit prototype's own store, described under the
prototype below and not reached by `--forget`. One forwarder writes a
twelfth, in the same directory and named in invariant 2 above:
`statusline_hook.py` keeps `statusline-<harness>-<session>.json` per conversation, holding a
normalized state name and a timestamp, so a status line that fires many times a turn posts once. The directory is created `0o700` because the log can carry local paths: uncaught
tracebacks land there, not just Python-level prints. Nothing ever removes or rotates the log: a
`--stop` (or a killed process) deletes the state file but leaves the log behind, since it is the
record of a detached run, so `~/.compass` accumulates one log file per port indefinitely.

`POST /api/shutdown` stops the server and is gated by the same `_local_ok()` checks (`Host`,
`Origin`, `Sec-Fetch-Site`) that already protect `/api/notify`. It adds no new exposure of
consequence: any local process that can reach the port could already read every session on the
machine through `/api/data`, and can now also stop the server. That is a smaller capability inside
the same trust boundary described above, not a new one.

`GET /api/overlays` reads the event overlay ledger and is a diagnostic, described in
[`docs/design-needs-input.md`](docs/design-needs-input.md#n-5-two-different-faults-produce-the-same-row-so-the-ledger-is-now-readable).
It carries no session content: an overlay is a harness name, the collector key for the session, a
state kind, three timestamps, and a subagent id the hook supplied, capped at ingress. The collector
key is Claude's eight-character transcript prefix and the whole session UUID for Codex, Antigravity
and Gemini CLI, and `/api/data` already publishes both, along with titles and prompts this route
never sees. It applies the strict same-origin check rather than the relaxed one `/api/data` uses for
navigations, and answers 503 when the process runs without a coordinator.

The same route serves the bounded record of state disputes, where an event overruled a session the
dashboard had read as waiting. A record holds the same fields plus the two activity timestamps the
reducer compared, and no more: the row's title and its state detail are deliberately absent, because
a state detail can carry a permission prompt's own text, an open question's, or a plan's first line.

## Unasked readings

`--unasked-readings` is off by default, and it is the only feature here that sends your words and
your session's record to a model with nobody watching. Everything else that reads a session with a
model happens because somebody pressed a control and saw a disclosure first. This one happens
because the operator passed a flag, so the flag's own help text is where that disclosure lives.

What it sends is less than `POST /api/reading` sends, on the same path: the goal you typed, and the
observed record the reading is allowed to read, through a supervised Claude Code or Codex CLI on
your machine under your capacity. Claude Code reads Claude Code sessions; Codex reads Codex
sessions. On other harnesses the lane prefers Claude Code, where a pressed reading prefers Codex.
If the preferred provider is unavailable or unqualified on this machine, the other serves. A
failed launch never tries a second provider. That record carries your messages in the session whole, up to 1,000
characters each where the prompt has room, as a pressed reading's does. It never sends what the
agent said: a pressed reading of a Claude Code session carries the agent's own messages since
2026-10-03 (Observer model calls), and the lane leaves them out, entry and words alike. Your expected outcome lines are never sent by it, and a session with lines
and no goal is not read by it at all (item 12 of
[DEC-24](docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)).
The lane uses `reading_policy.GuardedModel`, the same guarded model seam as a requested reading.
It sends no outcome lines or agent messages, and no tool output but one kind: on Claude Code, reading a
Claude Code session where Compass can name the destination, a check or command that failed goes with its masked
line, its exit status and the last 180 characters of its output, as for a pressed reading, except from a shell call that ran more than one thing, which sends the line and exit status alone. A check that passed,
a run with no result, a CI pass and a command that cannot fail never go, and neither does anything on the Codex
route, whose stored Allow covers words. The reading's cutoff says only failures were sent. Claude Code runs under
the owner's 2026-10-02 acceptance and needs no separate grant. Codex sends only with a stored Allow for the
current destination, checked again at the seam. With no grant, after Pause model calls, under the
model off switch, or after a destination change, nothing is sent and the skip is logged. The
session's Drift card shows the grant and a toggle to allow or revoke it, with the words and
destination disclosed beside it. Attention points to that toggle when a session with a typed goal
is waiting for permission. The grant covers every session routed to Codex at that destination;
Analyze and Resume cannot grant it. A revoke cancels this daemon's in-flight Codex check and
refuses subsequent sends; Pause does the same for either provider. A call already sent cannot be
unsent. A cancelled call that spent capacity keeps a withdrawn check row for the caps without
publishing a finding or claiming a completed check. The lane does not charge Analyze's budget;
its own caps below bound it.

Start with `--unasked-readings` to enable the lane. Without that flag neither the toggle nor the
Attention cue appears. The flag remains off by default; the delivery and qualification preconditions
for changing that default are unchanged.

It is bounded three ways, and the bounds are the posture rather than a preference. One reading runs
at a time for the whole board, so a board where forty annotated sessions cross a state boundary
together starts one subprocess and not forty. A fifteen-minute per-session floor holds a second reading of the same
session off, because a session can cross a boundary repeatedly inside a minute. And two counts of CHECKS RUN, per session and rolling
per day (three per session, twelve per rolling day), stop the lane entirely once spent. Counting only what was raised was tried and is wrong: a
board whose sessions are all healthy raises nothing, so nothing advances the count and the lane runs
forever. Measured on that version, five sessions ran 480 subprocesses in a simulated day against a
daily cap of 12. A spent count is stated on the board
rather than passed over in silence: the reader is by construction not present, so a limit being
spent and a session found to be on track must never render alike.

`~/.compass/compass-departures.json` holds every check the lane ran, opened `0600` with the mode
in the `open` call and written through a temp file and `os.replace`. Every check and not only the
ones that found something: a check that found nothing still spent a subprocess, and a store of
findings alone bounds nothing, which is what the caps count. It is also the only way the board can
say whether a particular session was looked at, as against whether the feature was switched on.

A record holds a harness key, a session id, the server's clock, and the annotation revision and
evidence window it read against. A check that raised something also holds the constraint and clause
that departed, the model's own sentence about it, and the evidence ids it cited. That sentence is
prose a model wrote about your session, which is the same class of content the annotation store
already holds and is bounded the same way. On a Claude Code session it may quote a line of a failed
check's output; it is scrubbed as a pressed reading's explanation is, of credential shapes and of the
call's masked values, and the same text reaches the local notification. Nothing sends it anywhere.
With the switch off the file is never created.

The switch governs writing, not reading. A file that already exists is read on every collection and
on every `GET /api/annotations` whether or not `--unasked-readings` was passed, and every raise it
holds is published on the row it belongs to, so turning the feature off stops new checks and
retracts no record. The board says as much rather than leaving the reader to infer it from a panel
that has gone quiet.

Discarding what you asked of a session withdraws its raises too. The constraint, the clause, the
model's sentence, the evidence ids and the producer's account of what it read are blanked in place
and the row is marked withdrawn, so nothing quoting the words you took back survives on disk or on
`GET /api/annotations`. The row itself stays, holding only that a check ran and when, because the
row is what the two caps above count and deleting it would refund the subprocess it spent.

Discarding here means the `clear` field of a `POST /api/annotate` body, which deletes every
revision and, after a clear that took at least one revision, the session's stored summary. The
store counts what it took under its own lock (the reply's `removed` field, null on any other arm), so a
save from another tab that the page had not yet seen is taken too and never leaves the summary
standing. The reply's `summary` field says `deleted`, `absent`, `stopped` (nothing stored and a running job stopped), a
refusal token (`unwritable`, `unavailable`), or `untouched`, and the page's sentence claims only that outcome. It is reachable from the board as `discard everything`, a control under the goal and the
expected outcome on the session page's drift block, offered only where a revision is stored and armed by one press before a second
performs it. The board's own `clear` control beside the goal, and `remove` beside an outcome line,
are a different act: each empties one box or drops one line, and the save that follows appends a
revision without those words. The words you typed
are still in the earlier revisions and a raise quoting them is still quoting them, so nothing is
withdrawn. Naming both is the point, because the shorter name is the one printed on the button, and
the board now says so where the reader meets the two controls rather than only here.

## Session ends

A session's end is the one fact a final reading rests on, and until 2026-09-12 the board held it
only in the memory of the process that saw the `SessionEnd` hook fire. Measured 2026-09-11: three
sessions that read as ended came back after a restart as merely quiet, and no final reading could
be taken on any of them again. So the coordinator now writes the end through to
`~/.compass/compass-ends.json`, opened `0600` with the mode in the `open` call and written
through a temp file and `os.replace`, and a collection reads it back onto a row the running
coordinator never saw end.

A record holds a harness key, a session id and the harness's own stamp for the end. Nothing else:
no title, no prompt, no project path, no reason. One record per session id, the later stamp
winning, and at most 512 of them, the same count the coordinator's own memory refuses new ends
at, so the file can never restore more than a running board would have held. Nothing sends it
anywhere. A corrupt, truncated or over-cap file degrades to "no ends", and every row then reads
exactly as it did before this store existed; one malformed entry is dropped on its own without
discarding the rest.

What a stored end may not do is invent one. Absence means the end was not observed by any run of
this board, never that the session is still open, which is the same reading the coordinator's
memory gives. A stored end also loses to later activity: a session resumed while the board was
down produced no `session_started` this process could see, so a file written more than the
activity grace after its end is the only tell that the id is in use again, and the stored end is
then not applied. Activity here is whatever the row counts as activity, which is wider than the
session's own transcript: on Claude it is the newest of the task file, the parent transcript's
newest conversation record, the subagent transcripts, the agent files and the child sessions. The
parent is read by its newest `user` or `assistant` record rather than its mtime,
because Claude Code appends bookkeeping records such as `away_summary` after a turn stops, and
read as mtime one retired the stop it followed. The exposure accepted with that
guard is stated rather than solved. A harness that writes any of those after `SessionEnd` would
have its restored end dropped, and the row reads as it does today, no end observed, which is
honest rather than wrong. A live end, observed by the running coordinator, takes no such guard,
because the coordinator retires it itself the moment the id is seen in use.

A Claude Code turn stop may also be read from the session's own transcript (owner,
2026-10-02): its top-level `stop_hook_summary`, from the bounded tail the collector already
reads. Nothing more is read, stored or sent, and it is never written as an observed stop
(`finished_at`). Whoever can write the transcript can forge one, which is the local-process
exposure accepted throughout. The worst it buys is a reading the reader pressed for, saying it
covers a turn that had not finished. A summary written after a hook's feedback, which keeps the
turn going, is refused by the collector and by the scorer's transcript vouching above alike.

The coordinator is the only writer, so two flags govern the file by construction rather than by a
switch of their own. `--no-events` leaves it unread and unwritten, exactly as it leaves the focus
command with no capability: with no coordinator there is nothing to write an end and the
collection then reads none back. `--diagnose` builds no coordinator either, so it reads the
harness stores and never creates or touches this one. `--forget` deletes it along with the history
store, because the command removes the machine's memory of what it observed and a durable end is
exactly that class. It is refused while a dashboard is running on the port, and the history store's
refusal is what covers it: a live coordinator still holds the ends it observed in memory and keeps
publishing them, so the delete would change the file and not the board.

Two dashboards on one machine share the one file, and two ends landing in the same instant resolve
last-writer-wins on the whole file, the exposure Dismissals below already accepts; the write lock
is intra-process, as it is for the delivery record.

## Delivery records

Raising a notification writes one file: `~/.compass/compass-deliveries.json`, opened `0600` with
the mode in the `open` call and written through a temp file and `os.replace`, exactly as the
dismissal store is.

A record holds a harness key, a session id, the server's clock at the attempt, which producer raised
it, and one of five outcome tokens. Nothing else: no title, no prompt, no project path, no question
text and no notification body. What the operating system did with the banner is not in it either,
because nothing reports that back. Nothing sends it anywhere.

`POST /api/lane` is the one route that writes the browser half, and what it refuses is the point.
The page may report that a notification lane exists in it and may never report a delivery, so the
body carries two scalars about the tab and a body naming a session is refused with a 400 rather than
having its session dropped. The record it writes is one timestamp for the whole board, held in
memory and never on disk. It is gated by `_local_ok()` alone and carries no capability, for the
reason `/api/dismiss` does not. What a forged request buys is worth stating in the right direction,
because an earlier draft of this paragraph had it backwards. A forge stamps the server's clock at
the moment it arrives, so every raise already on record renders the sentence saying the report came
after it, which claims nothing. It is the raises AFTER the forge that render the reassuring sentence,
and the most it can say is that a tab reported a working notification lane some minutes before the
raise. That is a statement about a tab, never about a delivery, and the negative sentence it
displaces already claimed nothing either way. A local account that can post this can already read
every session on the machine through `/api/data`.

## Dismissals

Marking a session handled writes one file:
`~/.compass/compass-dismissals.json`, opened `0600` with the mode in the `open` call so it is never
briefly world-readable, written through a temp file and `os.replace` so a reader mid-write sees the
old file or the new one.

It holds a harness key, a session id, and two timestamps per entry. Nothing else: no title, no
prompt, no project path, no state detail. Nothing sends it anywhere either. The one route that reads
it out is `GET /api/cleared`, on the loopback port, and what that serves back to the page is strictly
less than `/api/data` already does. It applies the strict same-origin check rather than the relaxed
one `/api/data` uses for navigations, and answers 503 under `--no-dismiss`.

Two properties bound what a forged `POST /api/dismiss` can do. The body carries no timestamp: the
watermark that decides how long a mark holds is the server's own clock at the moment it lands, so
there is no value a caller can send that hides a row past that session's next write. And the file is
capped at 256 entries, oldest mark evicted first, so nothing can grow it without limit. A corrupt,
truncated or over-cap file degrades to "no dismissals", with every row visible, rather than
raising, and one malformed entry is dropped on its own without discarding the rest.

To clear it, delete the file, or use the page's `handled` chip to restore individual sessions.
`--no-dismiss` leaves it unread and unwritten for a run.

Two exposures come with the feature and are accepted rather than solved. The first is that clearing a
session suppresses its desktop popup as well as its row, including a session still waiting on an
answer, which is what the control is for when the gate was answered somewhere else. It is also the
most a forged `POST /api/dismiss` can achieve: one session's alert stays silent until that session
writes again, and its standing question is still on the board the moment the row is restored. The
second is that two dashboards on one machine share the one file. Each picks up the other's marks on
its next collection, but two marks landing in the same instant resolve last-writer-wins on the whole
file, and the losing mark is lost.
[`docs/design-dismissals.md`](docs/design-dismissals.md) records why that race is stated rather than
solved.

## Local history (the session history store)

The board is rebuilt from the harness stores on every start, so a restart used to leave it with no
memory of sessions that already ran. Compass keeps its own history of what it observed, on this
machine, so the board can open knowing what happened before it was last closed.

One rule fixes the rest: the store holds nothing the live snapshot does not already serve. What is
kept is session identity, states and the transitions between them, gate open and close, turn
boundaries and their timings, tool names and counts, and the derived two-segment project label the
board groups by: it is published on every row, it is capped at the last two segments rather than
being a path, and both panels that read the history group by it, so the history cannot be seeded
without it. Never a raw working directory.

What is never written to it, under any circumstances and with no exception available:

- Tool input, in whole or in part, including any substring of a command.
- Paths. Neither a session's working directory nor any path a tool touched.
- File contents, of any file.

**Prompt-derived text is avoided by default and allowlisted per field when a feature needs it.**
Until 2026-09-04 this was a fourth outright prohibition, and DEC-13 replaced it with the allowlist
below. What did not change is that the store keeps no prompt-derived text nobody named: a carrier
absent from the allowlist is banned exactly as firmly as tool input is, and the allowlist is a list
of decisions rather than a category.

The reason the ban became an allowlist is that it was stricter than the product around it and the
asymmetry was doing no work. The dashboard already publishes prompt text. Published text below owns
the enumeration, and the carriers that reach the page raw are these ten: `title`, `last_prompt`, `state_detail`,
`project_key`, `project_name`, `worktree`, `tasks[].subject`, `tasks[].activeForm`, `subagents[].name` and
`subagents[].parent`. More reaches the page through `records.safe_text`, including the observer's
derived goal and Codex's `title`, which is a prompt because Codex writes no generated title. And
`GET /api/observe` already writes prompt-derived text to disk as a sidecar under
`~/.compass/observer/`, redacted on the way in and written owner-only. Prompt
text on disk in Compass's own state was therefore already a shipped pattern with a review behind
it, and the history store was the one place holding a harder line than the surface it records.

A field carrying prompt-derived text may be kept only when every one of these holds:

1. it is named in the allowlist below, on its own line, with the feature that needs it;
2. it is already published on the live board, so the one rule above, that the store holds nothing the
   live snapshot does not already serve, still holds unchanged;
3. it has passed `records.redact_secrets`, through `safe_text` or `redact_clip`, **before** it is
   bounded and never after, the order Published text requires and for the reason given there;
4. it is bounded to a cap this section states;
5. it lives inside the retention window, the size cap, `--no-history` and `--forget` described
   below, with no separate lifetime of its own;
6. its admission bumps `history.SCHEMA_VERSION` and appends the old value to
   `history.READABLE_VERSIONS`, so an upgrade reads the records already on disk instead of
   discarding them. Every admission is additive, because each field is re-validated on its own
   and a record written before a field existed is a record with that field absent. The store
   used to compare the version for equality, which meant the bump that came with the first
   admission would have wiped fourteen days of history on upgrade with no signal but a reset
   reason nobody reads. A version outside that tuple is still refused, which is the case the
   header exists to report.

The allowlist, one line per field:

- `annotation_goal`, for the outcome baseline DEC-15b admits. What the reader typed one session
  should achieve, at most 1,000 characters as the annotation store bounds it and at most 256 as this
  store does, which keeps a longer goal's opening. Published on every row, redacted by `records.safe_text` inside
  `annotations.annotate` before either bound is applied, and kept so the words a reading was read
  against reopen after a restart and after the live row leaves the board.
- `annotation_line_1`, the first line of the expected outcome: one thing the reader typed the
  session should produce, at most 240 characters on one line as the annotation store bounds it and
  at most 256 as this store does. Same redaction and same reason as the goal.
- `annotation_line_2`, the second outcome line. Same bound, same redaction, same reason.
- `annotation_line_3`, the third outcome line. Same bound, same redaction, same reason.
- `annotation_line_4`, the fourth outcome line. Same bound, same redaction, same reason.
- `annotation_line_5`, the fifth outcome line. Same bound, same redaction, same reason.
- `annotation_line_6`, the sixth and last outcome line. Same bound, same redaction, same reason.
- `first_prompt`, the first recorded user prompt offered by DEC-22 so a reader can choose the
  original goal without retyping it. Published for Claude Code and Codex, redacted before clipping
  to 140 characters plus the clipping mark, and scrubbed to the same bound on history reload.
  Its existing history retention, size cap, `--no-history` and `--forget` apply unchanged.

[DEC-22](docs/design-reading-a-session.md#dec-22-your-own-prompt-may-become-your-goal) also admits
an explicitly adopted latest or first prompt as `annotation_goal`, and, since the owner's ruling of
2026-10-01 ([amended](docs/design-reading-a-session.md#amended-2026-10-01-up-to-five-of-your-prompts-may-be-chosen)),
one of up to five of the reader's own prompts chosen from the observed record, under the closed
source token `chosen-prompt`. The five are published as `prompt_choices` on the focused project
context only, each redacted by `records.safe_text` before it is bounded to the goal's 1,000 characters,
and they are neither stored nor admitted here: no history field holds the list, and only the one
the reader adopts is kept, as `annotation_goal`. A choice is resolved again on the server by its
fact id, and refused unless its displayed text and time still match an offered source; a copied
correction, a harness control and a local command are never offered. Authorship is inferred from the
harness user-message shape and injected-prompt filter, which fails open; it is not proof a person
wrote the message. The server resolves the published source again, requires its displayed text and
source time to match, and refuses implicit adoption over an existing goal. Adoption uses the same
1,000-character, one-line annotation writer for the goal. Its closed source token and source time survive with
the revision and the reading that used it; an explicit goal save makes typed words instead.

Amended by the owner, approving the Analyze drift plan, 2026-10-04: the menu's five choices are
built only when the reader opens it. A listed later direction may also be explicitly chosen with
"Make it the goal". The server resolves its fact id in the same session's own source record,
requires a person-authored message after the goal's direction floor, and verifies the displayed
words, source time and saved revision again before adoption. Claude and Codex use a stable,
bounded backward 64 MiB search so recent messages in long files and paged entries
can be reached after they leave the live tail or semantic history. Missing,
changing and ambiguous sources are refused. A duplicate outside the consumed
byte or clock allowance is not checked. The draft asks whether to keep or clear
standing outcome lines and saves only on Save intent. No list or whole source text is stored.
Every offered goal choice masks named credential forms before raw line breaks are folded and
before the goal cap is applied. This goal-only scan is uncached; Analyze keeps its own words.
The prompt lookup returns at most 4,096 source facts from the newest 64 MiB and
opening 32 MiB, sharing a two-second clock. It checks conflicting copies of
retained identities throughout those consumed ranges. The menu still publishes
at most five choices and no whole records. `prompt_scan` adds only a state and
byte or clock stop token, so a partial read is disclosed beside the choices. Known source clipping remains an excerpt even after whitespace folds.
Adopted goals never authorize unasked checks, even when the same revision has a typed output.

The history record also keeps `first_prompt_at`, `annotation_goal_source`,
`annotation_goal_source_at` and `annotation_line_1_source` to `annotation_line_6_source`, scalar
provenance for the admitted words: each line's source is the closed token `typed` or `entry`, and
the entry it came from is not kept here. Schema 4 reads versions 1, 2 and 3 without discarding
their observations, and a record's one `annotation_output` comes forward as line 1. Six line
fields make an annotated session's records larger than one did, so the size cap below ages other
sessions out sooner; the owner accepted that on 2026-09-24. Unknown versions still refuse. First prompts come
from a bounded two-MiB transcript-prefix scan, excluding generated titles, compaction summaries
and recognized injected messages. An unread prefix yields no first prompt; it never substitutes
a later record. A first prompt that is a harness control such as `/clear` is still the first
prompt, published with the boolean `first_prompt_control`. No goal is drafted from it, none is
drafted from a later record in its place, and the server refuses to adopt it. Source text is at most 140 characters plus the clipping mark. The page names an
excerpt rather than silently adopting a longer prompt. Missing source times prevent adoption.

A Claude Code session that states a goal with `/goal` has it read from the transcript's own
records, not from the prompt: the `goal_status` attachment that carries the condition, and the
`local_command` record that prints the command's answer. The read is forward and incremental over at
most the last 8 MiB, so a goal set before that and untouched since publishes nothing: a reader who opens
such a session cold sees no detected goal and can type or adopt one as usual. A clear is the same
sentinel with `met: true`, which is the only trace of one in an interactive session. A `failed: true`
verdict, which Claude Code writes for a goal it gave up on, is not a verdict, and a measured run
showed it ends the goal: Compass stops holding the goal, publishes the give-up as its own claim
(`session_goal_gave_up`, `{at, reason}`) and never calls it met. The condition
is published as `session_goal`, `{text, at}`, masked by the same prose masking a later direction
gets and folded to one line, and a condition over 4,000 characters, the limit Claude Code itself enforces, publishes nothing. A condition longer than the Goal field holds (1,000 characters) also carries `offered`, the
bounded excerpt an adoption stores, and `cut: true`, so the page marks it cut and an adoption names
exactly the words the store keeps; a shorter one carries neither key. A subagent's record is never the session's goal. Once the evaluator has decided, the latest `met: true`
verdict joins the goal as `verdict`, `{met, at, reason}`. The reason is the evaluator model's own
sentence, so it gets the same prose masking, is folded to one line and is cut at 500 characters with an
ellipsis. The page draws it quoted, as text, under the label "The harness's claim", and never as Compass's
own words. A not-met verdict is not read: the evaluator repeats it on every iteration while the goal is open, so it
is progress rather than an end state, and the card reports only the end state. Like a first prompt the goal is not in session history, and it is
stored only if the reader adopts it as their goal under the source token `session-goal`.

A clear and a give-up are published beside the goal and never as it: `session_goal_cleared` (`{at}`) and
`session_goal_gave_up` (`{at, reason}`), and a goal that followed another carries `earlier`
(`{how, at}`, with how one of replaced, met or gave-up). None of them holds the earlier goal's words. The
give-up reason is the evaluator model's own sentence and takes the same masking, one line and 500-character
bound as a verdict's reason; its iterations, tokens and duration are not published. Like the goal, none of it
is in session history, and a read that starts mid-file publishes none of it, since a missing value means unknown.

The verdict is a claim and Compass tests it. The test is code over the writes and checks the record already
holds, with no model call and nothing new sent anywhere. It is stored beside a reading's criteria as
`goal_verdict`, three closed values and a list of at most three fact ids, and a stored value outside them,
or a pair the test never gives (a pass with no fact behind it), is dropped on read and the reading renders
without it. The verdict never lowers a drift level and never counts as a passing check. A
reason that names nothing the record can show is "unconfirmed", never "disputed", because a capped listing
cannot prove absence.

The test also looks for text the reason puts in double quotes in the output of a check the record holds: only the
redacted last 180 characters the press already reads for one recorded check whose call ran that check and nothing
else that may print, never a read, an `echo` or another command's output, and never more than the press already
held. The search needs no grant, since it sends nothing, and keeps nothing: the stored answer is the check entries
and a count of one to eight, never a span or any output. A quoted span that holds a credential shape is not
searched, nor is one the check's own command line holds, and a match only says where the text is, so the answer stays "unconfirmed" and never raises a level.

A Codex session that states a goal with `/goal` has it read from the rollout's own records the same way, into
the same `session_goal`, `{text, at}`, with the same masking, the same 4,000-character bound, the same excerpt
keys and the same 8 MiB forward read. The goal is the objective a `thread_goal_updated` event carries, timed by
the goal's own `createdAt`; Codex writes that event for a set, an edit, a pause and a resume, never for a goal
the model creates itself, so a goal the model wrote is never published as the reader's. A clear is the
`User cleared the goal.` line Codex writes in its own `<codex_internal_context>` wrapper, published as
`session_goal_cleared` only when a goal was held, because Codex writes the same line for a clear with no goal
and before every new goal. An objective over 4,000 characters is stored by Codex as a sentence naming a file
it wrote the words to; that sentence publishes nothing, and the file is not read. The `<codex_internal_context>`
messages are Codex's own wording and are never read as a prompt the reader typed.

Codex records a goal met only in `goals_1.sqlite`, beside `sessions/` under `CODEX_HOME` (`~/.codex` by default),
so that file is read too (amended 2026-10-27). It is opened read-only through SQLite's `mode=ro` URI, and the
database is never written, though SQLite's WAL index (`-shm`) records the reader as it does for any reader.
Codex keeps the file in WAL mode, and once its last process exits the `-wal` and `-shm` are gone and a `mode=ro`
open fails; with no pending `-wal` data the file is then read as `immutable`, as the Antigravity stores are.
One query reads the thread id, objective and the two timestamps of rows whose status is `complete` and whose
objective is within the 4,000-character goal bound, at most 10,000 of them, and nothing else in the file: not the token budget, the tokens or time used, or any
other status. A row attaches to a Codex row's `session_goal` as `verdict` (`{met, at, reason}`, with an empty
reason, because Codex records none) only when its thread id is the session's id and its set time and masked
words match the goal the rollout published, so an edited, replaced or cleared goal never inherits another's
completion. The working model marks its own goal complete, so the verdict is weaker than Claude Code's
evaluator, and it is published and tested the same way: as the harness's claim, which a reading checks and
which never moves a level. A missing file, a build without `sqlite3`, or a read that fails publishes no
verdict; a failed read is kept as a store error, once per change to the file rather than once per row. Codex records no give-up, so a Codex goal never carries one.

An Antigravity session that states a goal with `/goal` has it read from the person's own typed input in
`brain/<conversation>/.system_generated/logs/transcript_full.jsonl`, a file beside the `transcript.jsonl`
the directions are already read from that holds the same records with no field cut. Only a `USER_INPUT` from
`USER_EXPLICIT` whose request opens `/goal ` and whose metadata carries agy's fixed `/goal is a [Slash
Command]` paragraph counts, and the condition is the request after the command. It is published as the same
`session_goal`, with the same masking and its own 16,000-character bound (agy accepted 5,000 and refused
nothing, so the 4,000 the other two use would drop real goals; a longer one publishes nothing), the same excerpt keys and the same 8 MiB forward read, and the same symlink
checks guard the path. agy records no end to a goal: a met or cancelled goal is a marker in the model's own
reply, which Compass does not read, so an Antigravity goal carries no verdict, no clear and no `earlier`, and
the latest `/goal` stays the session's goal. The server adopts an Antigravity row's `session-goal` and still
adopts none of its prompts.

The revision number beside them, `annotation_revision`, is in the record and not on this list. It
is an integer the board derives, not text anybody typed.

Reserved and deliberately not admitted, because nothing produces one and this store may not hold
what the live snapshot does not already serve: `assessment_at`, `assessment_cutoff`,
`assessment_revision_read`, `assessment_goal_result` and `assessment_output_result`. The names are
recorded so the admission that adds them does not re-argue the naming, and each still needs its own
line here.

A test binds this list to `history.PROMPT_TEXT_ALLOWLIST` and to the record's own field set: an
entry with no record behind it fails, and none of the carriers named in
`history.PROMPT_DERIVED_CARRIERS` may enter the record without an entry here. That tuple is a
hand-kept list of names, so a carrier it does not yet name is held out by this section and by
review rather than by the test. Adding a prompt-derived field to the record means adding its name
there in the same change.

The store may never widen the set of fields it keeps otherwise: a field that is not already
published on the live board is not a field history may keep. That condition used to run one way
only, because the board published prompt text while the never-list banned it outright; with the
allowlist the exception is gone and the condition runs both ways for an allowlisted field. The
derived two-segment project label is kept by the kept-list above while the never-list still bans
the paths it is derived from.

The store lives under Compass's own directory, next to the dismissals file, and is written the way
that file and the state file are. It is opened owner-only with the mode in the `open` call, so it is
never briefly world-readable, and it is written through a temp file and a rename, so a reader
mid-write sees the old file or the new one. The mode is advisory, exactly as it is for the state
file and the dismissal store: Windows ignores it, and root reads it either way.

Retention is 14 days by default, with a size cap, and both are configurable. Eviction is by age
first, oldest observation dropped first, so a session that fell out of the window cannot be brought
back by raising the cap. The age window and the size cap bound the store together, and raising
either does not stop the other applying.

The store is on by default. A digest of what happened while the user was away exists only if the
history was being kept before they left, and Compass already writes local state on the user's
behalf by default in the dismissals file, and writes the observer sidecar on demand when a reader
opens that panel for a session. The trust cost of that default is retention, and the bounds above
and the delete below are what answer it.

The off switch is `--no-history`. It mirrors `--no-git` at every one of that flag's sites, including
the branch that forwards flags to a respawned daemon, so a restart cannot re-enable a store the user
disabled. With the store off nothing is written and nothing is read back: the board opens with no
memory, exactly as it does today.

`--forget` deletes the store and exits. It is a one-shot command, in the family of `--stop` and
`--status` rather than the family of per-run switches, because what it does is not reversible by
running the next command without it. It removes the file whether or not the store is enabled, and it
adds no endpoint: nothing over the loopback port can delete history. It is refused while a dashboard
answers on the port it names, and says to `--stop` that instance first: a running server holds its
own copy of the history in memory and would write the deleted records back on the next transition,
which is the one way a delete could report success and not have happened. A dashboard on some other
port is out of that probe's reach, so the recording lane also drops its copy when the file it read
has gone.

A store that cannot be read is discarded rather than repaired. Corrupt bytes, an unreadable file, a
version the running build does not understand: in every case the store is dropped, the board starts
empty, and the header reports the reset, so a silent loss of history is never mistaken for a machine
that did nothing.

Nothing in the store ever leaves the machine. It adds no outbound request, no forwarder and no
endpoint; the network posture described in Scope is unchanged by it.

A violation of any boundary in this section is a security bug: a field in the store that the live
board does not publish, prompt-derived text in a field the allowlist above does not name, tool input
or a path or file content reaching it by any route,
a write that is not owner-only or not through a temp file and a rename, an unbounded store or one
evicted by anything but age first, a store still written while the feature is off, a respawned daemon
that re-enables it, a history file reachable over the port, or any part of the store leaving the
machine.

## Irreversible actions (hook-side destructive-shape matching)

Claude Code and Codex after-tool hooks report a fixed set of destructive command shapes.
A report says a hook observed that shape after a tool call. It does not prove the action succeeded.
The command stays in the hook process; session detail and Attention show fixed labels only.
Coverage requires installed hooks. No matching reports received; missing hooks and unmatched
commands can look the same. Unsupported harnesses and disabled runs say so on the page.

### What Compass reads of a tool call today, exactly

The rule here is an allowlist rather than a prohibition, for the reason DEC-13 gave the history
store: a flat "never" the code already breaks is a contract narrower than the system, and a reader
who finds the counter-example stops believing the rest of the document. So the honest form is a list
of named reads. Of an observed session's tool calls, the runtime parses the input at exactly the
places below and nowhere else, and each reduces what it read to a bounded summary at parse time
rather than keeping anything raw. One further read exists and is governed elsewhere: the ask lane's
own `ask_operator` tool parses the arguments of the call a session makes to Compass, which is a
tool Compass owns rather than one it observed, and The ask lane states its bounds:

- `claude_data.input_summary` reads two fields of two Claude tools. `ExitPlanMode` carries `plan`,
  and what is kept is its first usable line, which is the plan's own title in practice.
  `AskUserQuestion` carries `questions`, and what is kept is each item's `question`. Both go through
  `records.safe_text` and are bounded at `config.input_summary_cap_chars`, 160 characters. The pair
  of tool names is `claude_data.INPUT_TOOLS`, and a tool absent from it has its input read by
  nothing.
- `transcripts.codex_plan` reads Codex's `update_plan` payload, in both shapes Codex writes: the
  `arguments` of a `function_call` and the `input` of a `custom_tool_call`. What is kept is the plan
  steps and their statuses, bounded at `transcripts.CODEX_PLAN_MAX_STEPS` steps, 64, with each
  step's text through `records.safe_text` and bounded at `transcripts.CODEX_PLAN_STEP_CAP_CHARS`,
  160 characters. Codex caps its own plan well below both, and the record is untrusted input, so the
  bound is against a malformed one rather than against ordinary use.

The operator-cockpit prototype also reads dispatch evidence:

- `collectors.codex._child_assignment` reads `spawn_agent` and `followup_task` arguments from
  the bounded transcript tail, matching a child task or target before summarizing its message.
- `project_context._tool_call_events` and `project_context._tool_support` read Pi `bash` and
  `subagent` arguments for dispatch events, assignment summaries, and counts. The first reads
  through `project_context._call_arguments`, which the Pi check reader shares, so the check
  results add no expression. That reader is two named reads. `project_context._pi_bash_check_runs`
  parses a `bash` command to find the runner, and keeps the runner and result under DEC-23's rules,
  publishing a title Compass writes ("2 validation checks failed"), never the command or its
  output. It reads the last 180 characters of the result text, redacted first, and the error flag,
  and nothing of that tail reaches a prompt. `project_context._pi_changes` reads the name of every
  Pi tool call and parses every `bash` command, check or not, against DEC-23's read-only list; what
  it keeps is only whether a change followed a check.
- `project_context.codex_dispatch_events` reads `spawn_agent` arguments to join a task name to
  a readable dispatch artifact. Its backward scan is capped at 32 MiB by default; project event
  output is capped at 100 rows and semantic lines at 112 characters.
- `project_context.claude_tool_reports` reads a Claude Code session's `Bash` calls and the path
  of its `Write`, `Edit`, `MultiEdit` and `NotebookEdit` calls (`file_path`, or `notebook_path`),
  for the checks it ran and the files it wrote, its subagents' calls included through the same
  expression. Of a file-write call it reads the path, and of its
  result the error flag alone. Since 2026-10-23 it also reads the `skill` name of a `Skill` call
  (never its arguments), and of a `Bash` call's result only the structured
  `toolUseResult.gitOperation.pr` (`number`, `url`, `action`), never the command or its output. Both
  go through closed shapes and publish nothing that does not match them. [Tool output in a Claude
  Code reading](#tool-output-in-a-claude-code-reading) states its bounds and where the result may go.

These are evidence reads, not command execution. In total, eight expressions in `compass_runtime`
reach an input payload. The counts and module names are checked by `test_documentation`.
DEC-23's named read for the checks a Claude Code session ran is the eighth, and
[its entry](#tool-output-in-a-claude-code-reading) states its bounds.
The prototype has no additional switch that disables just these dispatch reads.

A shape match is a different kind of read from those. It happens in the hook, inside
the operator's own harness process, against a payload that process already has, and what it keeps is
a verdict rather than a summary. It changes nothing about what the server or the collectors read from
a transcript, and it adds no disk store, no path and no subprocess.

### The bounds a shape match has to hold to

The initial literal forms are fixed below. Only Claude Code and Codex `PostToolUse`,
tool `Bash`, `tool_input.command` are admitted by the measured captures. Claude's
nonzero call emitted `PostToolUseFailure`; Codex's emitted `PostToolUse`, so neither
a match nor its absence establishes success.

| Identifier / display label | Supported literal form | Exclusions |
| -- | -- | -- |
| `git_force_push` / force push | `git push` with `--force`, `-f`, or `--force-with-lease`, optionally followed by plain remote/ref arguments | Other options, combined short options, and `--force-with-lease=...` abstain. |
| `git_hard_reset` / hard reset | `git reset --hard` with at most one plain revision | Other flags and option ordering abstain. |
| `sql_drop_table` / DROP TABLE | `psql -c 'DROP TABLE name;'`, `mysql -e 'DROP TABLE name;'`, or `sqlite3 database 'DROP TABLE name;'`; optional `IF EXISTS`, case-insensitive SQL words, optional final semicolon | One unquoted SQL identifier only, optionally dotted; no client flags, multiple statements, comments or quoted identifiers. Double quotes may delimit the whole SQL argument too. |
| `recursive_delete` / recursive delete | `rm` followed by `-r`, `-R`, `-rf`, `-fr`, `-Rf`, or `-fR`, optionally `-f` and `--`, then plain paths | A path beginning `/tmp/`, `/private/tmp/`, or `/var/tmp/` is excluded. No report if every path is excluded. `..` path components abstain everywhere; prefixes say nothing about symlinks or filesystem resolution. |

Each whole command may have one `rtk`, `rtk proxy` or `rtk bypass` prefix. No other wrappers,
executable paths, environment assignments, shell composition, expansion, redirects,
escapes or multiline commands are accepted. Plain tokens contain only ASCII letters,
digits and `_./:@%+=,-`; quotes are reserved for the SQL argument. Commands over
4,096 characters or 64 whitespace-separated tokens abstain. The matcher performs no
shell evaluation, filesystem resolution, regex, worker I/O or subprocess call.

The hook posts an identifier for a shape from the named set, the tool name, and a timestamp,
which is the shape DEC-5 allowed, plus the three routing fields below. No command, argument,
output, copied substring, path, file content or free-text explanation enters this report.
Fixed labels can share characters with an input; nothing is copied from it.

Matching has a nominal 5 ms wait in a daemon thread, bounded input and no worker I/O. Late
results are discarded. This is best effort: startup, scheduling and transport take separate time,
so neither 5 ms nor the tests' 250 ms process containment is a universal real-time guarantee.
Forced sleep and pure-Python spin are tested through the actual hook process. A GIL-held regex
fails that containment and remains a rejected negative control, never a production matcher.
An executor was rejected because it joins its workers at interpreter exit.

Report after, never before. The matcher is reached only at `PostToolUse`, never a permission
or pre-tool gate. Antigravity's `PreToolUse` is why this distinction matters: an empty object there
is a deny rather than an abstention, so the hook is never registered there rather than claiming
its empty output is harmless. The reporting hook writes no stdout and exits zero on handled failures.

`--no-irreversible` disables matching, ingress and publication, and survives daemon respawn.
`--no-events` also disables the feature. Fresh hooks read the explicit `irreversible_enabled`
state-file bit before entering the matcher; an absent bit, missing file or old server means off.
Ordinary lifecycle hints remain available with only `--no-irreversible`. A hook already in flight
can race a restart and attempt a post. An off replacement refuses it; an enabled replacement may
accept it because the six-field report has no run identity. Ingress still requires the current
harness capability and the existing event rate budget.

### The envelope has to widen, and one dropped thing has to come back

Every new report carries exactly six fields: `v`, `event`, `session_id`, `timestamp`,
`pattern_id`, `tool_name`. Its event is `command_shape_reported`, its tool is the fixed `Bash`,
and its pattern must be in the table above. Ingress validates that vocabulary independently and
rejects any missing or extra field. The report cannot become a lifecycle patch or carry a cwd,
transcript path, source sequence or terminal identity. Ordinary lifecycle envelopes still drop
the tool name and retain their existing compatibility and routing-hint rules.

The tool-name exception was deliberate: a failing tool's name reaches the page through the loop
signal already. The prompt, the tool input and the tool output stay dropped.

Three places carry the envelope's width and they move together in one commit. This document's own
sentence spells it as a word, `config.py`'s stated reason for `event_body_cap_bytes` spells it as a
word too because the cap is justified by that width, and `events.ALLOWED_FIELDS` is the set itself.
`test_documentation.EventEnvelopeEnumerationTest` reads both prose copies against
`len(events.ALLOWED_FIELDS)`, so a field added without the words moving is a red test rather than a
document that has quietly drifted.

### Whether a shape identifier may enter the history store

A field the live board does not publish is not a field history may keep. Publication makes a
fixed label eligible for a future history decision; it does not authorize storage by itself.
This feature keeps no command reports in durable history. A separate in-memory ledger retains
the newest 1,000 reports globally, newest 20 per session, for at most 24 hours. Oldest reports
are evicted first. The ledger survives collection coalescing and session end, but not a restart.
It retains duplicates and orders by report time, then arrival order: these are reports, never
an exact action count. Attention shows the newest 20 independently of its session-risk denominator.
The list count comes from the reports displayed. No notifications or dismissal controls are added.

A violation of any boundary in this section is a security bug: a command, an argument or a tool
output reaching a socket, an input read the allowlist above does not name, an operator-configurable
pattern, a hook that returns anything but its harness's no-opinion answer, an envelope field this
document has not named, or a shape identifier in the history store with no published field behind
it.

DEC-23 scopes the command and tool-output clauses above to the hook: they govern what a hook
reports and the socket it posts to. A Claude Code check line, and the output tail read to classify
it, are a separate read from the transcript. The check line reaches the page the way other
transcript text does, bounded and redacted, and neither reaches a model except under the destination
rule in [Tool output in a Claude Code reading](#tool-output-in-a-claude-code-reading).

## The ask lane (`ask_operator`)

Compass ships one MCP tool. A session that wants a human decision calls `ask_operator`, and the
question appears in the dashboard for the reader to answer. This is the only path by which anything
a reader does in Compass reaches a running session, and it exists because the session asked. One
other direction is written down and unbuilt: Hand-off requests (one verb into a session) below is
Compass starting the exchange rather than a reader, it carries one fixed verb and nothing a reader
typed, and no shipped feature uses it.

What it is, precisely. Compass ships a stdio MCP server beside the dashboard. It is not one of the
four forwarders and shares none of their transport. A harness spawns it, it speaks JSON-RPC on stdin
and stdout, and it holds the agent's tool call open while the question is outstanding. It registers
the question with the dashboard over loopback and polls for the answer.

The direction is the invariant for everything shipped. Compass reaches into no session today, and
the one written-down exception is the hand-off request below, which DEC-2 allowed as a single verb
into a session that consents and which nothing ships. It weakens no other sentence in this section.
A session can only ever be
waiting because it asked to be, and a session that never calls the tool is untouched by all of this.
Nothing is typed into a terminal, no harness store is written, and the tool cannot answer a native
permission prompt. That last point is not a limitation to be lifted later: answering a harness's own
gate is refused, and the four probes DEC-2 filed are research rather than a roadmap.

What the reader's click can and cannot say. The question's options are recorded when the question is
registered. An answer names the question and an option by index, and the MCP server returns its own
copy of that option to the agent. An answer cannot introduce text. The strongest thing a forged
answer can do is select the wrong one of the options the asking agent itself wrote, and it cannot put
new content into that agent's context.

What is bounded. The question text and the option list are bounded when they arrive, and rendered as
text and never as markup. The number of questions outstanding at once is capped, and the honest
answer past the cap is a refusal the server turns into a decline rather than an error. A question
that is never answered expires and declines. The question is also delivered as a notification: on macOS by the server,
through the same truncation and AppleScript escaping the needs-input popup uses, and elsewhere by the page, which
passes the text to the browser's own notification API and applies neither (it is not building a
shell command, and the text is already bounded at the ingress); the notification is a pointer rather than a decision surface, and an option can
only ever be chosen back in the page.

Failure is always a decline, never a hang. If the dashboard is not running, if no reader answers, if
the deadline passes, or if the process is stopped while a question is outstanding, the tool returns a
decline and the agent proceeds as it judges best. A stopped dashboard releases every outstanding
question before it exits. A tool call that gives up for any of those reasons also withdraws its own
question on the way out, so a card nobody is waiting on leaves the board instead of staying clickable
until its deadline. A click on a question whose asker has gone is accepted and discarded either way,
which is why the withdrawal matters to the reader rather than to the agent.

The standing permission this needs, and what granting it means. At default settings every harness
gates the first call to this tool in the user's own terminal, before the call reaches Compass. The
feature is therefore useless until the user grants the tool once, which on Claude Code writes
`permissions.allow: ["mcp__plugin_compass_compass__ask_operator"]` into that project's
`.claude/settings.local.json`. Granting it means that project's sessions may pause themselves on a
Compass question without asking again. It is scoped to that directory, it is the user's to revoke by
deleting the line, and Compass never writes it.

Answering is a real decision. Every other click in the dashboard changes what you see. This one
changes what an agent does next, with your credentials, in your repository. The exposure that follows
is recorded under Known and accepted rather than solved here, because loopback is not a per-user
boundary.

## Hand-off requests (one verb into a session)

The ask lane runs one way. A session asks, a reader answers, and Compass starts nothing. DEC-2
ruled on 2026-09-02 that Compass may also start the exchange, in one shape and no other: when a
quota window is about to close on a session that is mid-task, Compass may send that session one
request for a hand-off summary, so the operator gets the state of the work written down instead of
writing it from memory before the cutoff. This is the boundary the hand-off request has
to respect, and it is written before the code exists for the same reason the quota, git-probe,
history and light-harness boundaries were.

This section grants nothing on its own. No shipped feature sends anything into a session, and the
ask lane's direction claim is amended for this section and for nothing else.

### One verb, and what makes it one

What may be sent is a request for a hand-off summary. Not a prompt the reader composed, not a line
off the board, not a retry of the operator's last instruction: one fixed request Compass authored,
in plain text, whose content does not vary with what the reader typed or with what the session
holds. That is what keeps this out of the general write path into terminals that DEC-2 refused as a
standing answer, and it is the same property the ask lane relies on in the other direction, where an
answer can only ever select one of the options the asking agent itself wrote. A reader cannot
introduce text through either.

The verb is also not a permission answer. DEC-2 confirmed the refusal of native-gate answering
rather than lifting it, so nothing here reaches a harness's own prompt, and the ask lane's sentence
on that stands unchanged.

### The session's own consent, and what is documented rather than measured

The receiving side decides whether to accept, and the mechanism is the harness's rather than
Compass's. What follows is read off Claude Code's own documentation and has not been measured on a
machine here, which is stated plainly because this repository's standing lesson is that desk
research got the field, the unit or the rendering wrong five times out of five. Four facts are
documented, not measured:

- that the inbound setting, `crossSessionInbound`, has values that refuse an inbound message or hold
  it for the session to accept;
- that a held message lapses after a `dialogExpiry` of five minutes;
- that a delivered message counts toward usage the way a prompt the operator types does;
- that the socket lives in a per-user directory under the system temporary directory, of the shape
  `/tmp/cc-socks-<uid>`.

The build that lands E7 measures all four first, records the capture under `docs/captures/` the way
every other harness vocabulary here was earned, and replaces this list with the measurement. Until
then no sentence in this section rests on any of them being exactly right. What the section does
assert is the rule Compass sets for itself: a session that refuses inbound messages is not reached,
and a request that lapses unread is a request that was not delivered.

Compass sends no authentication line, on any platform. The socket protocol documents one, and the
reason to leave it unused is not convenience. Verifying that a session is Compass's own child is
one permission class. Presenting a credential that would reach any session on the machine is
another, and sending the line asserts the second. So the verb reaches a session that already accepts
inbound messages, and it reaches nothing else.

### The token, and the path that contains it

The per-session token is never logged, never echoed, never served on the loopback port, and never
printed by `--diagnose`. Neither is any path that contains it. That second half is not a flourish:
the token is documented as part of the socket's filename rather than as a separate field, so a
redaction covering the value while printing a directory listing, an error message or the path itself
leaks the whole thing. Both the value and its containing path get the handling Usage quota reads
gives a vendor token. Published text records what redaction covers today, and a path-shaped secret
is the case it does not yet name, so E7's change adds it there in the same commit.

### The read this adds, and why `config.py` has to name it

Finding a session's socket means reading a path that is no harness store and lies under no root
`config.resolve_store_roots` returns. That function documents three Claude roots today,
`claude.projects`, `claude.tasks` and `claude.teams`, and no fourth. Scope makes a read outside the
documented store paths a security bug "however the path was derived", so this read is a security bug
until its location is documented there. Naming it belongs to E7's change rather than to this
section: the commit that opens the socket adds the directory to the documented roots, and a reviewer
who finds the open without the entry has found the bug this paragraph predicts.

### How this relates to Light harness usage, and to the outbound count

They are two pathways and not one, which is why invariant 1 names them apart. Light harness usage
starts a fresh harness process and hands it text Compass composed out of a session, so the
operator's own words leave the machine on a request Compass made. A hand-off request writes one
line to a socket on this machine, to a session the operator already started and is already paying
for. Compass makes no network request for it, and the fixed verb carries nothing derived from any
session.

What leaves the machine afterwards is what that session sends next, on its own connection and its
own credentials, exactly as everything else that session does leaves. So this pathway adds nothing
to invariant 1's count of outbound requests, and the invariant names it anyway: a reader counting
network exposures who found no mention of a verb that causes a vendor round trip would be right to
distrust the count.

It does spend the operator's capacity, and Light harness usage's rule about that holds here without
being restated. A feature that consumes capacity states what it consumed.

### Failure is a decline, never a hang

An absent socket, a stale token, a session that never answers, an inbound setting that refuses, a
message that lapses: each one ends as the board reporting that the hand-off was not delivered. None
of them holds a request open, blocks a shutdown, or leaves a session parked. This is the ask lane's
rule in the other direction and it is there for the same reason: neither end of this exchange may be
able to wedge the other.

Compass does not retry. A verb that resent itself when a session did not answer would spend the
operator's remaining window on delivery attempts at the exact moment the window is the thing running
out.

### The off switch

The feature ships `--no-handoff` with it: a flag that disables the pathway for a run regardless of
the stored setting, mirroring `--no-ask` and `--no-history` at every one of their sites, including
the branch that forwards flags to a respawned daemon, so a restart cannot re-enable what the
operator disabled. That flag does not exist yet, and this document does not claim it does. No
feature sends the verb, so there is nothing to switch off. A test holds those two statements
together: it asserts this section still says nothing is sent and that the parser still has no such
flag, so whoever adds the flag is failed here until they amend this section too.

### Violation, and what is accepted rather than solved

A violation of any boundary in this section is a security bug: text sent into a session that is not
the one fixed verb, a verb sent to a session that refuses inbound messages, an authentication line
presented, the token or its containing path reaching a log, a `--diagnose` line or a loopback
response, a retry, a socket read from a location the store roots do not document, or a request that
blocks rather than declines.

What is accepted rather than solved: as far as the harness's own documentation goes, the socket
directory is per-user, so other accounts are held out only as well as that documented shape holds,
and E7's capture is what settles it rather than this paragraph. What is certain either way is that
the directory does nothing about other processes of the same account. Anything running as the
operator can send the same verb to the same session without going through Compass at all. That stays inside the
trust boundary for the reason Known and accepted gives for the rest of this document, since such a
process can read the operator's secret material directly, and it is the same limit the ask lane
already accepts on loopback.

## Operator-cockpit prototype

The `proto/operator-cockpit` branch adds project context and an optional read-only terminal.
`GET /api/project-context` reads bounded transcript and workflow evidence, stores semantic history
under the configured state directory, and can invoke the installed Codex CLI for a derived goal.
`GET /api/session-record` uses the same loopback and bounded project/session guards, returns the same redacted message titles as project-context, and exposes no fields or content classes the page could not already read. Each message also carries its fixed number, read from an in-memory index of every message's time and fact id in the transcript (at most 16 transcripts, never written to disk, nothing a person wrote); the index adds no field the page could not derive from the record it already reads, and a read that cannot finish inside its allowance publishes no numbers.
This is separate from quota fetching and from the session-history switch. The prototype retains
its own semantic-history store. `--forget` deletes the session-history, session-end and summary
stores, removes annotation discard records and copied-correction digests, and withdraws model
permission; it does not reach this semantic-history store.

That store carries session text in both directions, and this document did not say so until the
annotation work re-counted which files hold what a person typed. A fact's `summary` is bounded at
240 characters and holds the operator's own directive where the fact is a steer or an observer goal;
a result fact's `detail` holds up to 4096 characters of the assistant's final answer. So the file is
a carrier of typed words as well as generated ones, in the same content class as the observer
sidecar's goal line, and the redaction paragraph below is what stands between it and a credential.

Semantic history redacts recognized credential shapes before publication and persistence.
Loading an older store also redacts nested values and, if any changed, immediately replaces
the file atomically with an owner-only copy under the history lock. A read may be the only
activity after an upgrade, so waiting for a later history update would retain known secrets
unnecessarily. If replacement fails, the read still publishes redacted values, logs a warning
without their contents, and retries the repair on the next load. Original bytes can remain
until the filesystem permits replacement; this does not erase filesystem snapshots or backups.

The terminal is off unless both `--interaction-origin-session` and
`--interaction-origin-registration-file` are supplied. When enabled, ten POST operations under
`/api/interaction/` join the ordinary routes: `register`, `renew`, `probe-unregistered`,
`probe-spoofed`, `control`, `input`, `expire`, `disconnect`, `reconnect`, and `reset`.
Registration requires the session-side registration token; renewal requires the lease token.
The probe and lifecycle controls have the normal loopback/origin checks, with no additional
capability. `control` and `input` always refuse. Normal serving returns 404 for this prefix.

`interaction_prototype.py` joins `focus.py` as a module allowed to invoke tmux. It validates the
registered pane identity before capturing output and attaches a read-only control-mode client.
The WebSocket at `/api/interaction/stream` carries output only; receiving a client frame ends the
connection. Its upgrade response carries the same framing header as ordinary responses. Terminal
output is a separate exposure from the redacted session summaries: a person or local process that
can read the registered terminal can see its captured text.

## Published text (credential redaction)

A harness transcript records what the operator typed, verbatim, so if a key was ever pasted into a
prompt the store holds it. The dashboard reads those stores and publishes prompt text. Named as
fields rather than glossed, because a prose alias is a name no test can check, the carriers that reach the page raw are these ten: `title`, `last_prompt`, `state_detail`,
`project_key`, `project_name`, `worktree`, `tasks[].subject`, `tasks[].activeForm`, `subagents[].name` and
`subagents[].parent`. Those are the two tables in
`aggregate`, and the instruction line's own `text` passes the same sweep beside them. It is a list
of carriers rather than a list of every published string that could hold what the operator typed:
more prompt text reaches the page through `records.safe_text` on the way, including the observer's
derived goal, the ask question and its options, a Codex `title`, which is a prompt because Codex
writes no generated title, the focused project context's `prompt_choices[].text`, up to five of
the reader's prompts at 1,000 characters each (240 before 2026-10-27), and since 2026-10-03 the first sentence of each of the
agent's messages, as the `summary` of an `agent_message` fact on `/api/project-context`, at most
112 characters. Some of what those carriers hold came from a tool call's input rather
than from a prompt directly: a Claude plan's first line, an `AskUserQuestion` question, and a Codex
plan's steps, each under the bounds Irreversible actions states. A sweep of the local Claude store
on the machine this was built on found seven distinct live Anthropic credentials in ordinary prompt
history. Loopback is no help against it: the dashboard is what someone opens to show a colleague
what their agents are doing, so the exposure is the screen and the screenshot.

Credential-shaped runs are replaced before publication, in place, by a visible marker that keeps the
prefix naming the kind: `sk-ant-…REDACTED`, `AKIA…REDACTED`, `ghp_…REDACTED`. The words around it
survive, because those are the instruction and the reason the line is on the card. The marker is
visible deliberately. Someone who sees it learns their prompt history holds a live key, which is the
only route by which it gets rotated.

The list of shapes is measured against the local corpus and lives in one place,
`records.redact_secrets`. It is applied at three. Inside `records.safe_text`, which nearly every
published string already passes through, including the ask question and its options, Codex's title
and the observer's goal. At the slice, through `records.redact_clip`, for the strings the other nine
collectors build out of their own store by hand: `title` and `last_prompt`. And over the assembled rows
in `aggregate`, a backstop under both that also reaches `state_detail`, the instruction line, task
subjects and a subagent name. An ask answer needs no cover, being an index into options the asking
agent wrote rather than text. The measurement, the false-positive rate and the rejected alternatives
are in [`docs/design-credential-redaction.md`](docs/design-credential-redaction.md).

Since 2026-10-27 the list also holds the shapes a command's output prints with no vendor prefix: a
gcloud `ya29.` token, an AWS `"SecretString"` value (escaped JSON inside it included), a netrc
password after `login` or `machine`, and the signature parameter of a pre-signed URL. The cue list
gains `passphrase`. Each keeps its name and loses its value. Each is cued, and each has a limit where
prose can open like it, so some false positives and misses stay: `sig=` outside a query string,
"login page password reset", "machine learning password manager" and `sig=overview` are left alone
because the shape needs the `login` word, a value with a digit or a capital, or a signature-like
value; a loginless `default password Reset` is masked, and an all-lowercase signature with no digit,
`+`, `/` or `%` is not.
A `"SecretString"` value is masked to its closing quote however long it is, and one with no closing
quote is masked to the end of its line.

Since 2026-10-03 one shape is cued rather than shaped, beside the AWS secret. The cue is
`Authorization: Bearer`, a `--password`, `--token`, `--secret` or `--api-key` flag, or a name ending
in `password`, `passwd`, `pwd`, `token`, `secret`, `api_key` or `apikey` in any case (`DB_PASSWORD`,
`PGPASSWORD`, `GITHUB_API_TOKEN`, `db_password`) or an upper-case `*_KEY` (`OPENAI_API_KEY`,
`STRIPE_KEY`), before `=` or `:` with any spacing and an optional closing quote (`"password":`).
The value after it is masked up to whitespace or punctuation, and a quoted value whole, spaces and
all. The cue stays and the value becomes the marker. It was added when the agent's own messages
began reaching a reading model, because an agent repeats what it read. Left alone, because each
names a value rather than holding one or is ordinary prose: `None`, `null`, `true`, a `$VAR` or
`${VAR}`, `self.…`, `os.environ…`, a call such as `next_token()`, `PWD=/a/path`, `sort_key=name`;
after a bare `Bearer`, anything shorter than 16 characters or with no digit or symbol ("bearer
auth"); and after `secret`, `token` or a `:`, a value with neither a digit, a symbol nor 16
characters (`secret=staging`, "the token: next"). It is the withholding direction and was not
measured against the corpus the shapes were, so a harmless value that looks like a credential is
masked too. A title a cue newly masks hashes to a new fact id once (`project_context` records the
precedent).

The order matters as much as the coverage. Redaction runs before the bound, never after, because a
key cut at a 140-character cap is still a hundred usable characters of key and a shape whose tail has
fallen off no longer matches. A slice that ran first is what published a URL credential cut short of
its `@`.

Since 2026-10-05 the shared filter also checks a second view with transparent HTML inline formatting
removed, before the credential hint check. A match masks the corresponding original span; ordinary
spaces, newlines and harmless formatting remain, and the raw scan still masks credentials in tag
attributes. The supported elements are `a`, `abbr`, `b`, `code`, `del`, `em`, `i`, `ins`, `kbd`, `mark`,
`s`, `samp`, `small`, `span`, `strong`, `sub`, `sup`, `time`, `u` and `var`, including closing and
self-closing tags and quoted attributes. Slash-command arguments are masked before their tags turn
into spaces. This extra view is limited to 16,384 characters: longer text containing one of those
element starts is withheld as a redaction marker, including an unfinished attribute. Plain text
does not acquire that bound. Arbitrary envelope tags, encoded markup and unseen text beyond an
existing source extraction bound are outside this correction's claim.

Amended 2026-10-06: native command field boundaries are captured before the observer's
early scrub. Each field is masked before extraction; missing closing tags remain source
cuts, and malformed overlaps use the whole-record scrub. Observer packets, first prompts
and copied-correction matching then use the existing safe renderer and bounds. This
changes no credential pattern or content class. Separating those fields also removes an
accidental mask: a closing tag formerly made a short word after a colon look like a
credential. At the end of native arguments, a short word with no digit or symbol
can now survive after a colon (`password: correcthorse`) or a strict token/secret
assignment (`CLIENT_SECRET=staging`, `API_TOKEN=next`); a bare `bearer` value
shorter than 16 characters can survive too, as can a value shorter than three
characters after another cued assignment (`password=ab`, `API_KEY=xy`). Any may
be a real secret. These are
the cued rule's documented exceptions, not evidence that the values are harmless;
this filter does not identify every secret. The [command-boundary rationale](docs/design-credential-redaction.md#amended-2026-10-06-native-command-boundaries-survive-an-early-scrub)
owns the ordering and the existing fact-identity consequence.

The card, the browser notification body and the native popup are pixels, and a screenshot is what
each of them risks. Two of the things carrying this text are files. The first is the observer
sidecar under `~/.compass/observer/`, one JSON file per session holding the derived goal, which is
the operator's own words. Since goal provenance landed it holds two such lines rather than one: the published
`goal` and the pre-model `deterministic_goal` the model arm would otherwise have overwritten. They
are the same class of text and carry the same risk, so the count changes and nothing else does.
Both are redacted on the way in like everything else, and the file is
written owner-only through a temp file and a rename, so a reader mid-write sees the old file or the
new one and neither is ever briefly world-readable. The mode is advisory and Windows ignores it, the
same caveat the state file and the dismissal store carry.

The second is the prototype's semantic-history store, `~/.compass/semantic-work-history.json`. It
holds the operator's own directive as well as the assistant's answer, it is redacted on the way in
and again on every read, and it is written owner-only through a temp file and a rename like the
sidecar above. The Operator-cockpit prototype section has its fields and its deletion behaviour,
including that `--forget` does not reach it.

This reduces the exposure and does not close it, and both directions of error are real. A shape list
covers the formats it was measured against, so a credential in a format nobody has seen goes through
unmarked. A control character struck through the middle of a key defeats the match on the whole key,
and what follows is worse than nothing being published: the substitution that scrubs the character
turns it into a space, so the head in front of it still matches and redacts while the tail behind it
publishes beside the marker, 75 characters of key on a probe. A run longer than any key its format
issues is cut at the cap, and the characters past the cap publish. And the AWS secret access key is
matched only when one of three spellings of its key name sits in front of the value, because a bare
40-character base64 run cannot be told apart from a hash or a diff.

In the other direction a genuine instruction line can be altered: 20 of 22,120 real prompts in the
local corpus, 18 on Claude and 2 on Codex. That rate was re-measured when the filter was widened to
cover a key with a character in front of it, a URL credential clipped short of its `@`, capped
bodies, `lin_api_` API keys and the cued AWS secret, and it did not move on any of them. Nothing here
changes the rule outside the software, which is not to paste a credential into a prompt, and to rotate one
that was.

## Known and accepted

`--host` hands that same access to a network. `--host 0.0.0.0` is the operator
saying the machine's network may read the board, and there is no second gate behind it: everything
the paragraph below grants another account on the machine, a non-default bind grants anything that
can reach the port. Reading `/api/data` is the whole board: every session's titles, prompts and
project paths. Writing is the twenty-two POST routes enabled without terminal registration, `/api/shutdown` and `/api/answer` among them, so a
reachable dashboard can be killed, and a question a session is waiting on can be answered by
somebody other than you. Three of the twenty-two store nothing durable of their own: `POST /api/direction` returns the whole text
of a direction a session's user gave, which `/api/project-context` names by its first sentence,
`POST /api/correction` returns the goal and outcome lines a reader saved, composed as Steer back's
correction, and, for a claim of the agent's the record contradicts or does not show, that one agent
message's published title of at most 112 characters, and `POST /api/live-monitor` holds the Live
monitor's lease in memory only. All three answer only a loopback peer, so a non-default bind does not widen them;
the first two have their bounds in Analyze drift, Cancel and copied corrections. There is nothing to authenticate with on twenty of them, for the reason the
ask-lane paragraph below gives: the page is served as fixed bytes with no per-run secret in them.
Two carry a capability and they are not worth the same. `POST /api/events/<harness>` takes a per-run
token published only in the state file at mode `0600` and never served to the page, so a client
holding only the board cannot post events at all; that boundary survives a non-default bind intact,
and Event ingress below is where it is stated. `POST /api/focus`'s capability buys less: the token is
injected into the served document, so anything that can load the board under a non-default bind can
also ask for a raise, and `/api/data` names which rows would answer it. What that second gate
actually separates is a page from a document navigation and from a local process that never fetched
the board, which is the exposure the focus section states. `POST /api/live-monitor` holds an in-memory lease for a Claude Code session and writes nothing; it answers only a loopback peer that is not a document navigation, and `start` is the one action that begins to spend.

What the non-default bind does *not* spend is the rebinding defense. The Host and Origin gate widens
to addresses and never to names. Under `0.0.0.0`, that means any address a client could arrive on.
A page on `http://evil.example:4553` whose DNS points at the machine is refused in both modes, and
the `Sec-Fetch-Site` cross-site check runs unchanged. The gate tells a name from an address; it
cannot tell one remote client from another. So the honest scope is: use `--host` on a network you
would hand the transcripts to, and reach a dashboard over `ssh -L` otherwise.

Loopback is not a per-user boundary. Any other account on the same machine can `GET /api/data` and
read every session's titles and prompts, or forge a `POST /api/notify`. The Host, `Sec-Fetch` and
Origin checks defeat browser-based DNS rebinding, but they do not defeat a local process. This
matters more on a shared Linux host than on a personal laptop. Please report a *bypass* of the checks
that do exist. The absence of per-user isolation is documented here rather than treated as a new
finding.

A browser will not frame the board, and the header that stops it is narrower than it looks. Every
response the server composes carries `Content-Security-Policy: frame-ancestors 'none'`, with the
three exceptions named below, because the request gate does not close framing on its own: every port
on this machine is the same site, so a page served from another local port frames the board under a
`same-site` label that never reaches the cross-site check, and a frame navigation carries no `Origin`
for the check below it. That is worth closing because the served document holds the focus capability,
so a framed board is one lured click from raising a terminal, and `/api/data` names which rows would
answer. The attack it stops is blind: the framer cannot read the frame, since a fetch from another
local port carries an `Origin` and is refused, and no `Access-Control-Allow-Origin` is ever sent, so
the framer must guess that a question is outstanding and where its control landed.

What the header does not buy is the local-process exposure above. A local process the attacker
controls can open a socket to the port carrying no `Origin` and no `Sec-Fetch` headers at all, pass
every check, and answer or raise directly. `frame-ancestors` is not a defense against that attacker
and does not narrow what this section already accepts. The one case it does defend is a loopback page
whose process the attacker does not control: a stored cross-site scripting flaw, or an
HTML-rendering endpoint, in some other local development server the operator already runs. It is
delivered as a header rather than in the document because CSP ignores `frame-ancestors` in a
`<meta http-equiv>`, and it is the only directive in that policy because `frame-ancestors` has no
fallback to `default-src`, so it restricts framing and nothing else. Three responses are outside it,
deliberately, and none of them is a page: `/api/stream` writes its own headers and an event stream
has nothing to click; a `send_error` body is the standard library's error template, which carries no
control and no capability; and the `204` a poll of `/api/ask/<id>` returns while no answer has
arrived carries no body at all, so a frame navigated to it renders nothing. The stream and that poll
are both reachable from a frame on the same terms the board is, because each route takes the plain
local check.

A reading spends the reader's own capacity, and any local process that can reach the port can spend
it. `POST /api/reading` carries no capability token. The precedent is the quota fetch rather than the
event ingress: the harm is a side effect on the operator's Codex balance rather than a forged claim
about a session, and what holds it is the same-origin check and the refusal of a document
navigation, neither of which a local process sends headers for. A local process can grant the
remembered answer too, and can start a call without a prior Allow. A Claude Code reading
sends checks only where Compass names the configured destination, with its notice. The rolling cap of 100 attempts across tabs and processes bounds that
exposure. One reading per session may be in flight, and the explicit model off switch refuses all
calls. The
route reads nothing back to the caller beyond the job it started or found running, which the payload
already publishes: an unknown session answers 200 with no job, never a 404, so the route tells a
caller nothing about which sessions exist that `GET /api/data` does not. The same local process can
cancel an analysis through `POST /api/reading/cancel` and spend an attempt; the Cancel paragraph
above states it.

Having nothing to click is not the whole question for those two, because both hold a socket open,
and that half was measured on 2026-09-07 in Chrome. Eight frames pointed at `/api/stream` from a
page on another loopback port took **six** sockets, not eight: a browser caps concurrent HTTP/1.1
connections per origin at six, so the eight-slot stream budget was never drained and a seventh
client still received a 200. `stream_max_clients` sitting above the browser's six is why, and the
reason it was chosen that way is recorded beside it in `config`. What the six frames did drain was
Chrome's own connection pool for that origin, and the board then would not load at all in the same
browser: the navigation sat pending and committed the instant the frames were removed. So the
resource a framed long-lived route can deny is the browser's, not this server's, and the server
cannot arbitrate it.

Both routes therefore refuse a frame navigation outright, on `Sec-Fetch-Dest`, which the same
measurement confirmed a framed request carries: `iframe`, alongside `Sec-Fetch-Site: same-site` and
no `Origin` at all, which is how such a request passed the checks above. That buys one thing, which
is that the request is refused before it can hold a socket rather than holding one for as long as
the framer likes. It is worth exactly what `frame-ancestors` is worth and no more, and for the same
reason stated above: a local process the attacker controls sends no `Sec-Fetch` headers at all. A
`curl` caller sends none either and is unaffected, since the refusal fires only on a header a
browser sets.

Event ingress is the exception, and it is narrow. `POST /api/events/<harness>` requires a per-run
capability, because a general lifecycle overlay is more powerful than the side state `/api/notify`
sets: a forged `session_ended` can suppress a permission alert, and a looped `turn_started` can mask
a blocked session. The server generates one secret per process, derives one token per harness from
it, and publishes only the derived tokens in the state file, opened `0600` with the mode in the
`open` call so the token is never briefly world-readable. A token from one adapter cannot post as
another harness, and a token recovered from an old state file is useless against the next run. The
comparison is constant-time.

What that does **not** buy: the file mode is advisory, exactly as the state directory's `0700` is.
It does not apply to a directory that already exists, Windows ignores it, and root reads it either
way. Any process running as the same user can read the token and post events, and that stays inside
the trust boundary for the same reason the rest of this section does, since such a process can read
the user's secret material directly. An overlay may also only ever patch a row a collector produced;
it can never create or delete one, and it can only write these ten fields: `state`,
`state_detail`, `active`, `blocked_since`, `wait_unconfirmed` (whether a repeating-source wait
exceeded its evidence lease), `acquisition`, `finished_at` (the stamp of the turn's last
observed stop), `ended_at` (the stamp of the session id's own end), and `dirty` with `changed` (the
end-of-session git reading). `--no-events` turns the whole path off for a run.

The event envelope is allowlisted at both ends. Each adapter builds the fourteen permitted fields
one at a time across the ordinary and command-report variants; no variant carries all fourteen.
The prompt, the tool input and the tool output stay dropped in the hook and never reach a socket.
That is the hook: the bounded tool output a Claude Code transcript recorded is a separate read,
governed by [Tool output in a Claude Code reading](#tool-output-in-a-claude-code-reading).
Ordinary lifecycle envelopes still drop the tool name. Command reports carry only the six fields
listed in Irreversible actions above, with an allowlisted tool name and pattern identifier.
The server validates independently because a hook's output is untrusted. Ordinary `cwd` and
`transcript_path` matching hints are never echoed to `/api/data`; command reports carry neither.
`statusline_hook.py` shapes `/api/usage` down to the `quota` block alone.
The count here, `config.py`'s reason for `event_body_cap_bytes`, and `events.ALLOWED_FIELDS`
move together; `test_documentation.EventEnvelopeEnumerationTest` binds both prose counts.

One published field is derived from a transcript filename, and the sentence above is the one it has
to be read against. `resume_id` carries the session id a harness's own CLI takes to re-enter that
session, so the board can hand a reader the command rather than the hunt. It is the transcript's
stem and never its path: no directory, no home, nothing a filesystem could be walked from, and the
first eight characters of that same stem are already published as Claude's `sid`. `cwd` is not read
for it and would not help if it were. Two harnesses fill it, Claude Code and Codex, and the other
eight publish `null`, which is what stops the page offering a command nobody has verified.

The value is checked against `^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$` before it is published and again in
the page before a command is built from it, and that grammar is the guard rather than any quoting:
this is the one string on the board that becomes a shell command in the reader's own terminal, and it
is read off a filename in a store the harness owns. Two shapes are refused, and quoting would have
covered only the first. A token a shell would split, or one carrying a separator, substitution or
newline, is dropped and the row shows no control. So is a token starting with `-`: a shell reads that
as one word, but the CLI reads it as a flag. `claude --resume` takes an optional value and therefore
never consumes a `-`-leading token, and both harnesses ship a valueless flag that turns their
permission checks off, so a transcript named `--dangerously-skip-permissions.jsonl` would otherwise
reach the clipboard as a permission bypass with the session id dropped. Publishing a value that fails
that grammar, or building a command from one, is a security bug.

The ask lane inherits the loopback exposure above, and it is the first place where that exposure
reaches beyond what a reader sees. Any local process that can reach the port can answer a question a
session is waiting on. Two things keep this narrow rather than solved. An answer selects an option by
index from a list the asking agent wrote, so a forgery cannot introduce text into an agent's context,
only choose badly among choices the agent already offered. And a session is only ever waiting because
it asked, so there is no question to answer unless an agent raised one. A per-reader
authentication would be the real fix, and it is not available: the dashboard page is served as fixed
bytes with no per-run secret in it, and a local process could read such a secret anyway.

A question's attribution is unverified, and this is the second half of that exposure. `harness`,
`session_id` and `project` are taken from the registration body and bounded, and nothing checks that
the named session exists or that the caller is it, so any local process that can reach the port can
put a card on the board that reads as coming from a specific session in a specific repository. Two
things bound the damage. The card is its own band and touches no collector-measured session state, so
a forged attribution cannot alter a row, a state, a count or a dismissal
([`docs/design-ask-lane.md`](docs/design-ask-lane.md#a-4-an-outstanding-question-is-its-own-band-not-a-row-in-sessions)
records why the band is separate); and answering the card still
only selects among options its own registrant wrote, so the forger gains nothing from being answered.
What a forgery does buy is plausibility, at the one place in the dashboard where a reader makes a
decision, which is why it is named here rather than left implicit in the loopback paragraph above. That
plausibility now reaches a reader with no tab open, because the question also raises a notification. The
title renders the display label of the harness key the registration claimed, and neither the key nor the
claim is verified. A registration that inherits or forges the harness environment variable titles the
banner with that harness. What the registry lookup does buy is that the title is a name the registry
carries or nothing at all, so a 120-character agent-authored string cannot reach it, and an
unattributable question is announced as "An agent" rather than under a borrowed name.
Verifying it would need a per-session secret that the sessions do not have and that the loopback
boundary could not keep.

`--diagnose` runs the same collection a served page does, so unless `--no-git` is given it may run the
read-only `git` commands of [the committed-file read](#the-committed-file-read-project-check-scripts)
for a Claude Code session's project. It still writes nothing and transmits nothing.

`--diagnose` output is sensitive. It prints the home directory, the interpreter path, the *values* of
the store relocation variables, every candidate store path, and per-path read errors. A recorded
store error may include a store or prompt excerpt, even when SQLite raised it. The shared formatter
keeps the exception type plus at most 1,024 Unicode characters of its message, including
`... [truncated]` when clipped; clipping does not redact sensitive content. Nothing is transmitted,
but redact it before pasting it into a public issue.

## Release workflow (the deploy key)

A release is pushed by a deploy key that bypasses the branch and tag rulesets, so the workflow
keeps that key away from dependency code. The release target is fixed once, before anything is
built. The frontend is then installed, rebuilt and tested in jobs that have a read-only token, a
checkout without persisted credentials and no secrets; the repository validation suite runs in a
second job with the same limits, because it starts `node` whenever `node` is on the path. The one
job that holds the key and the write token installs and runs no Node, pnpm, npm or frontend
dependency, refuses to continue unless its checkout is the exact commit both verifiers saw, and
proves the archive of the release commit before it pushes, moves the tag or advances `stable`.
The Python in that job installs from wheels only, into an environment it calls by path, and runs
no build script.

What it still runs beside the key: first-party Python from the verified tree (the release
scripts, the archived launcher and the validator), as the same operating-system user, with an empty
path and a throwaway home. That keeps Node out of reach and is not credential isolation. A change
that reaches `main` through the normal review and checks is the accepted trust boundary; the
workflow does not defend against a reviewed commit that is hostile. The release publishes the tree
that was verified, never a newer `main`, and a `stable` that has already moved forward is not moved
back. Whether the ruleset bypass, the key handling of `actions/checkout` and the runner image behave
as described can only be shown by a real run.

The standalone `compass` binaries are built the same way: by four jobs with a read-only token, no
secrets and a checkout without persisted credentials, under an exactly pinned PyInstaller toolchain
installed from wheels only. A third-party build dependency runs there, so what those jobs produce is
treated as data. It never reaches the job that holds the key. A separate job that holds only the
repository write token downloads the archives, checksums them and uploads them to the release,
and never unpacks or runs one. That job cannot push to `main` or move a tag. The checksums file
lives beside the archives, so it detects a corrupted download and not a hostile release; the
binaries carry no signature of their own, and on macOS no developer identity or notarization.

## Reporting a vulnerability

Please do not open a public issue for security problems. Instead:

- Use [GitHub private vulnerability reporting](https://github.com/spacedock-dev/compass/security/advisories/new), or
- Email dev@reccehq.com with a description and reproduction steps.

You can expect an acknowledgment within a few days. Please allow time for a fix to land and release before public disclosure.

## Supported versions

Only the latest released version of the plugin receives security fixes.
