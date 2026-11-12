# Design: when a prompt outranks a busy session

Owner for the question "the agent is waiting on you, so why does the row say Working?". The module
map, including which file owns the collector and which owns hook classification, belongs to
[design-runtime-architecture.md](design-runtime-architecture.md); this document owns the precedence
call between a standing prompt and a session that looks busy, and it exists mainly to record the
attempts that did not work, because two of them were made and reverted before the third landed.

<a id="n-1"></a>

## N-1: there is more than one needs-input path, and only one of them was broken

Worth establishing first, because the defect was originally filed as though there were one path and
it was dead. Four independent mechanisms can put a Claude row into Needs input. Three of them
existed when this was written; the roster row arrived with DRC-4263 and is the only one that raises
a wait about somebody other than the reader:

| Path | Source | Covers |
|---|---|---|
| Transcript | a pending question found by reading the session's records | `AskUserQuestion`, `ExitPlanMode`, and only when the record has reached disk. See N-4 |
| Event overlay | the plugin-bundled `PermissionRequest` hook | `ExitPlanMode` observed directly (N-4). `AskUserQuestion` seen once in the wild, on the DRC-4097 incident row, which carried `acquisition: event`. Any other tool gate, and a subagent's, is **inferred** from the hook being tool-scoped and has not been seen |
| Notification | the user-installed `Notification` hook, posted to the loopback API | MCP elicitation dialogs, worker permission and network requests |
| Teams roster | a member registered in `teams/session-<sid>/config.json` that has written no transcript | A dispatched subagent that never started. The wait is the subagent's, not the lead's, and the store carries no more than that: once a member has written its first record, nothing on disk distinguishes one blocked at a gate from one that is busy |

Codex has since become the second harness that can report a gate, and it has exactly one path: the
event overlay, from its own bundled `PermissionRequest` hook. It is not a fourth row in that table
because the table sorts Claude's three against each other, and a second harness with one source has
nothing to be sorted against. What the two share is the overlay mechanism, so N-5's ledger and N-9's stop handling apply to a
Codex row unchanged. N-6 is the exception and says so in its own section: its dispute ring only
watches a *collector* wait, so it cannot see a Codex gate in either direction. What they do not share is the other two
paths: Codex has no transcript detection and no Notification hook, which is why a Codex row can say a
gate is open and cannot say which. See N-7 for why that limit is a security decision rather than an
omission.

Copilot is the third, and it is neither of those mechanisms. Its own store records the prompt:
`permission.requested` is written when the dialog opens and `permission.completed` only when the
human answers, joined on `data.requestId`, so its **collector** raises the wait from an unanswered
pair in the tail. It needs no hook and nothing installed. The consequence for the rest of this
document is that a Copilot row behaves like the transcript row of N-1's table rather than like a
Codex row: the overlay sections do not apply to it at all, because no event adapter maps Copilot and
`events.parse` refuses its envelopes outright, and the wait ends when the collector next reads the
file rather than when an overlay is superseded. The measurement is
`docs/captures/copilot/permission-events-1.0.78-macos.jsonl`.

Cursor is the fourth, by Copilot's route on a different store, and it brings one thing neither of the
others needed. A standing tool-call gate leaves `pendingToolExecutionContracts` non-empty on the
newest blob of the chat's SQLite store, and answering it (approving or refusing alike) appends a
blob carrying the same key with the map emptied. Three properties of that store shaped the reader,
and each was measured rather than reasoned:

- The carrier is a length-prefixed binary frame, not a JSON object, so the collector's existing
  brace-first parse finds nothing in it. The match is on bytes.
- The store is append-only and its ids are content-addressed, so the blob that stood at the gate is
  still in the table long after the answer. The reading has to be newest-by-`rowid`, which is the
  only order handle the schema leaves; "any blob carries a non-empty map" is a wait that never ends.
- The carrier is not reachable from `meta.latestRootBlobId` in the general case. One readable store
  had a root id that was not in the table at all, so widening the existing meta-root-children walk
  would have missed it. It is a separate read on the connection the metadata pass already opens,
  memoised on the same mtime.

The thing neither of the others needed is [N-10](#n-10-a-cursor-gate-needs-a-liveness-gate-and-a-time-limit-cannot-be-it),
below. The measurement is `docs/captures/cursor/pending-tool-call-2026.08.11-macos.jsonl`, and B2 in
the tracker carries the remaining harness-specific work.

OpenCode and Pi now use the same event overlay with host-native JavaScript callbacks. OpenCode
maps parent permission asks and their matching final replies; Pi maps extension UI prompt spans
in persisted sessions on 0.85.1, excluding startup trust. Neither forwards prompt contents or
interprets a close as approval. Both need a separately installed adapter and events enabled.
Missing current-run observations remain unknown; a restart does not reconstruct a standing wait.
Their admission and executed-route checks belong to [adapter packaging](design-adapter-packaging.md).

The hook route for Cursor is a decided negative and is not revisited: `beforeShellExecution` runs
before the permission decision and feeds into it, so returning `permission: "ask"` **creates** the
prompt rather than observing one, and a wait posted from there would paint every Cursor row on its
first command.

The first two rows overlap, which is easy to miss and was missed here. `AskUserQuestion` and
`ExitPlanMode` are gated tools, so `PermissionRequest` fires for them like any other tool call, and
the event overlay carries them independently of whether the transcript ever shows them. An earlier
draft of this table listed those two under the transcript row alone, which read as though the event
path did not cover them. It does, and N-4 is the measurement.

The event overlay is the one that carries ordinary permission prompts, and its patch is written over
whatever the collector decided, so the collector's own ordering cannot suppress it. That is why the
symptom was narrower than it first read: the prompts that went missing were the ones with no
`PermissionRequest` behind them. `PermissionRequest` is tool-scoped, so an MCP elicitation, which is
a server asking the user rather than a tool being gated, raises only a notification. A worker's
request for network access is in the same position: it is a sandbox grant off a queue, not a tool
call.

<a id="n-2"></a>

## N-2: a live subagent used to mean Working, and it could not lapse

The collector resolved state in a fixed order: a pending question in the transcript, then a busy
test, then a standing hook. The busy test was two conditions joined by `or`, and they behave nothing
alike.

Fresh activity in the session's own transcript lapses on its own. An open prompt leaves that
transcript quiet, so a genuinely blocked session falls out of the window within
`working_threshold_sec` and its hook surfaces. Late, but not lost.

An earlier draft of this paragraph gave a mechanism for the quiet: that the `tool_use` record is
written before the prompt is raised and the `tool_result` only after it is answered. N-4 measured
that and it is not reliably true, since the record is sometimes not written at all while the gate
stands. The conclusion survives the correction because it only needs the transcript to be quiet, and
a record that was never written leaves it quieter still. The mechanism was wrong, the window still
lapses.

A live subagent never lapses. One running subagent held the row for as long as the workflow ran, so
a fan-out, the shape most likely to be holding a prompt in the first place, could not show one at
all. The two conditions had been written as if they were the same kind of evidence.

So they are now separated. Fresh own-transcript activity still outranks a hook. A live subagent
outranks only a hook this build does not recognise.

Claude's capped outstanding-tool and background-launch extension also yields to a standing hook,
including the legacy path without a recognised type. It does not extend the 90-second window that
fresh own-transcript activity gets above, and it never advances the activity stamp that clears an
explicit permission overlay. The [overlay contract](design-event-driven-observation.md#event-overlays-versus-store-truth)
owns the 900-second cap and the headless measurement.

## N-3: recognised, not merely actionable

The ingress already classifies a notification before storing it, and an unknown structured type
fails visible: stored, popped, treated as needing input. That is the right default there, because a
notification type added upstream must not vanish.

It is the wrong test for precedence, and there is a measured reason. Claude Code advertises eight
`notification_type` values and its callers pass at least four more. One of the four is
`computer_use_enter`, whose message is "Claude is using your computer, press Esc to stop": a status
line, not a question. Under fail-visible alone an unknown type would have been allowed to override a
working row, which means the next status line Anthropic ships would paint a red band on a session
that is fine.

The predicate that gates precedence therefore asks whether the type is one this build names
actionable, not whether the ingress let it through. An unrecognised type keeps the old behaviour and
waits for the session to go quiet. Storing an unknown prompt costs nothing; letting it win a
precedence fight costs the credibility of the band, and a band that cries wolf is worse than no band,
because it teaches the reader to ignore the one signal the product exists to give.

A hook stored before the type was carried through has no type recorded at all, which reads as
unrecognised. That is the safe direction on an upgrade.

### Rejected

- **Reordering the whole chain so any hook beats the busy test.** Attempted and reverted. It breaks
  the background-task lifecycle test, which posts a permission-shaped message while background
  events flow and asserts the row holds at Working, poll after poll. That test is right: its hook
  carries no type, so it exercises the legacy text-matching path, and fresh own-transcript activity
  should still win there.
- **Gating on the type, but against both halves of the busy test.** Fixed the subagent case and
  still failed the same test, because it also overrode fresh activity. The freshness half was never
  the defect; it self-clears.
- **Clearing a wait whenever the row shows activity.** Rejected earlier for the event path and
  rejected again here. A row's activity is the maximum over its transcript, its task files and every
  child transcript, deliberately, so that a parent parked on a long workflow does not age out. Using
  it to clear a wait would clear a genuine block the moment a subagent wrote. A false clear is worse
  than a false block: it hides the thing the dashboard is for.
- **Treating an unknown type as non-actionable at the ingress instead.** This would fix the false
  band by dropping the notification entirely, and it trades a wrong colour for a missing prompt. The
  ingress and the precedence test want opposite defaults, which is why they are two decisions and not
  one.

<a id="n-4"></a>

## N-4: every path is probabilistic, so the docs rank them instead of trusting one

N-1 sorted the three paths by what they cover. This section sorts them by how often they actually
fire, which is a different question and was answered later, by holding real sessions at real gates
and reading both the transcript and `/api/data` while the question was still on screen.

| Path | Live gates seen on it | Breakdown |
|---|---|---|
| Transcript (`pending_input_tool`) | 3 of 6 | `ExitPlanMode` 2/4, `AskUserQuestion` 1/2 |
| Event overlay (`PermissionRequest`) | 4 of 5 | all `ExitPlanMode`; one miss read `working` with `acquisition: event` |

Both rows are Claude's, and there is no Codex equivalent. Its one path had not shipped when these
were taken, and a hit rate for it would need the same interactive method applied to a Codex session,
which nobody has run. So the ranking below is a Claude ranking; a Codex row's reliability is
unmeasured rather than assumed to match.

**These are observations, not a capture, and they are not auditable.** Claude Code 2.1.226 on macOS,
2026-08-12, driven interactively under `tmux` against a scratch workspace, reading the transcript and
`/api/data` while the pane still showed the gate. Nothing was recorded to `captures/`, so a reader
cannot re-derive these counts from this repository, and the directory's own rule is that a claim
marked measured should be able to show its measurement. This one cannot. Treat the table as a field
note. Turning it into evidence is DRC-4135.

The samples are also far too small to rank anything. Five and six trials, unevenly composed, with
some drawn from the same session, support exactly one conclusion: **both paths missed at least once,
so neither is a guarantee.** That both counts point the same way is a hint about which to prefer, not
a measured ordering, and the ranking `SKILL.md` gives readers is a judgement built on that hint plus
the mechanism, not a statistic.

The transcript case is the strange one. Claude Code does not write the `tool_use` record for an
input tool on a fixed schedule. Two consecutive questions in a single session, same version, same
prompt shape, behaved differently: the first had its record on disk with no matching `tool_result`
while the gate stood, and the second had no record at all after five minutes of waiting. That is not
a slow flush, it is a flush that had not been triggered. So the branch is neither dead nor live, it
is opportunistic, and it is documented that way rather than removed. Removing it would cost the one
population that has nothing else: a user running without the bundled hooks, for whom this is the only
needs-input source there is.

The event path's single miss is recorded as DRC-4134 and its cause is **not established**. All the
observation shows is `state: working` with `acquisition: event`, which proves some overlay patched
the row and nothing more. A `PermissionRequest` that never fired, never forwarded, or never
associated would look identical from outside, and so would a later working overlay retiring a wait
that did arrive.

Only the last of those resembles DRC-4095, and even there the resemblance is not a defect claim:
DRC-4095's fix makes a later working overlay retire an earlier wait **on purpose**, and its tests
pin that. So this is a miss in need of a mechanism, not a known bug of a known family. Attributing
it to one before tracing the overlay sequence is the same error this section is about.

### A heartbeat source cannot use this lane, and that is what rules Antigravity out

That deliberate retirement is the reason a fourth path was measured and then not built. Antigravity's
status line does carry a confirmation-pending flag: driven to a real permission prompt it pushes the
flag beside a `tool_use` state, with an id that names the session in the one arm whose recorder
checked, recorded in
[`captures/antigravity/statusline-confirmation-1.1.19-macos.jsonl`](captures/antigravity/statusline-confirmation-1.1.19-macos.jsonl).
The obstacle is the shape of the source rather than the signal. The status line is a repeating render
of live state, not an event stream, so the ordinary `working` and `idle` pushes that surround a gate
would arrive after the wait and retire it by exactly the rule above. Gates that stood 65 s, 94 s and
145 s each pushed the flag twice as the dialog opened and then went silent until something redrew the
pane, so the retirement would land while the human was still being asked.

The general form is worth stating, because it applies to any source of the same shape and not only to
this one. A path whose pushes assert what the session is doing **now** cannot post an overlay whose
whole value is surviving until it is answered, unless the reducer learns that a wait outranks a later
working push from the same source. That is a precedence rule, not a mapping, and it does not exist
yet. Until it does, `statusline_hook.py` maps `working` and `idle` and nothing else, which is why
`tool_use` is absent from its table on purpose rather than by oversight.

### The methodology this cost us

A single live read is one coin toss, not a measurement. The first `ExitPlanMode` observation showed
the record present and detected, and stopping there would have produced a confident write-up saying
the transcript branch works. Three more trials made it 2 of 4. The same trap ran the other way on the
event path: one trial showed `working` at a live gate, which looked exactly like a released-version
regression worth an emergency release, and the next two showed `needs_input` and killed that reading.

The original report on this behavior measured it once and concluded the branch was dead. This
investigation measured it once and nearly concluded it was live. Both readings came from honest live
reads. Anything in this area needs n greater than one before it goes in writing, and the desk read
and the timestamp replay that the original report warned about are not the only ways to get it wrong.

<a id="n-5"></a>

## N-5: two different faults produce the same row, so the ledger is now readable

The event path's one miss (N-4, tracked as DRC-4134) could not be diagnosed from outside the
process, and the reason is worth stating in general terms because it will happen again. A row
reading `state: working` with `acquisition: event` at a live gate has at least two causes, and
`/api/data` shows the same three fields for both:

- a needs-input overlay exists but the reducer suppressed it, leaving the turn's working overlay as
  the last applicable writer;
- no needs-input overlay ever existed, because the hook did not fire, did not reach the server, or
  did not match a session key.

The fixes have nothing in common. The first is a reducer change; the second is a delivery problem
where changing the reducer would do nothing at all. Guessing between them was the mistake DRC-4134
was opened to stop, and the issue's own first draft guessed wrong: it proposed a `PostToolUse`
landing after the request and retiring the wait through `ENDS_A_WAIT`. `PostToolUse` maps to
`store_changed`, which produces no overlay, so it can never enter that set. Only `UserPromptSubmit`
and `Stop` end a wait by outranking it, and in an ordinary turn both arrive before the gate.
`SessionEnd` ends one too, by retiring the whole ledger for that session rather than by outranking
anything, and Claude fires it on `/clear`.

`GET /api/overlays` publishes the ledger the reducer reads: one row per live overlay, with its kind,
`arrival_seq`, timestamps, and `time_gate_open`, which is the overlay's own effective and expiry
window and nothing more.

### Reading it

Two causes is the short version, and the short version is the one that sends an investigator to the
wrong file. There are four readings, and the report carries what separates all of them:

| The ledger shows | The reading | Where the fault is |
|---|---|---|
| a needs-input overlay, `arrival_seq` above every working and idle row | the activity grace suppressed it (`events.py:525`) | the reducer's grace |
| a needs-input overlay, `arrival_seq` below a working or idle row | it was outranked and permanently superseded (`events.py:523`) | ordering, the DRC-4095 family |
| no needs-input overlay, and a counter moved | the envelope arrived and was dropped | ingress, not the reducer |
| no needs-input overlay, and no counter moved | nothing was ever posted | the hook, or the wire |

The bottom two rows are not decidable from a single read, because the counters are cumulative since
the process started: a lone `reject.rate: 3` says nothing about whether any of the three belong to
the gate in front of you. Read the report before reproducing and again after, and diff. The top two
are decidable from one read, with one caveat: a row only reflects an overlay once a collection has
run, so compare the report's `now` against `/api/data`'s `generated` before concluding anything
inside the collection floor.

The second row is why `arrival_seq` is published rather than implied by list order. Delivery is
at-least-once and may reorder, so a `turn_started` can land after the `input_requested` it precedes
in real time, and the result is a needs-input overlay that is present, inside its window, and skipped
anyway. Attributing that to the grace and going to change the grace is exactly the wrong-guess
failure DRC-4134 exists to stop.

The third row is why `counters` rides along. An envelope can arrive and still leave no overlay:
rate-limited (`reject.rate`), rejected at validation (`reject.unmappable-id` is the one that means
the id matched no session, and the other `reject.*` reasons cover a malformed, incompatible or
unknown event), refused at the session cap (`overlay.refused`), expired while waiting for a
collection to produce its row (`pending.expired`), or retired by a `session_ended`, which Claude
fires on `/clear` (`retired`). `pending_rows` names the sessions currently in that waiting state.
None of this is visible in `overlays`, because in every case there is nothing there to see.

A fifth thing the ledger cannot tell you: whether an overlay it shows actually won. `time_gate_open`
is the overlay's own gate only. The reducer's ordering and its activity guards both run afterwards,
and their inputs (`own_activity`, `last_activity`) live on the collected row, which is `/api/data`'s
to publish. Read the two together.

Three notes on its shape, each of which was a choice:

- **It publishes the inputs, not a verdict.** The reducer's activity guards read `own_activity` and
  `last_activity` off the collected row, which `/api/data` already carries. Recomputing the patch
  here would mean sampling a second collection and reporting a decision the server never actually
  made.
- **It is same-origin only**, unlike `/api/data`. `do_GET` relaxes its cross-site check so that a
  link to the dashboard opens. Nothing renders this route, so the relaxation has no reason to reach
  it.
- **No coordinator answers 503, not 404.** Under `--no-events` the route exists and the ledger does
  not. A 404 would read as a build too old to have the route, which is a bad thing to conclude while
  chasing a missing overlay.

### Rejected

- **A `debug=1` parameter on `/api/data`.** That response is a published snapshot, revision-
  qualified and shared between clients, and a per-request variant of it either doubles the snapshot
  keyspace or serves one caller's debug view to another. The ledger is a different object with a
  different lifetime, so it is a different route.
- **Logging the ledger on every collection.** It would answer the question after the fact, and only
  for whoever had the log level raised before the fault. Nothing rotates the log either, so a
  standing gate would write the same rows every few seconds for as long as it stood.

<a id="n-6"></a>

## N-6: the server records its own contradictions, because nobody else will

N-5 gave a person a way to read the ledger. It assumed the person knows to look, and that
assumption does not survive contact with the product: the dashboard exists so that nobody opens
every session, so a row wrongly reading Working is a row nobody visits. The one instance behind
DRC-4134 was found because somebody was deliberately holding a gate open under `tmux` while reading
the API. That is not a detector, it is a person, and it stops the moment they stop.

Nor is it recoverable afterwards. Overlays expire, the ledger is memory, and an hour later there is
nothing to read.

So the server records the disagreement itself. `Application._apply_overlays` already holds both
halves at the moment they conflict: the row a collector produced, and the patch the ledger reduced
to. When the collector says `needs_input` and the patch says `working` or `idle`, that is one source
of truth overruling another about the single fact the product exists to report, and it is written to
a bounded ring on `RuntimeState` with the ledger attached. `/api/overlays` serves it alongside the
live ledger, in the same response, because a dispute is read against the ledger and two requests
would be two instants.

The ring is a ring, unlike the ledger and pending caps, which refuse rather than evict. Those hold
live alerts, where dropping the oldest could drop a standing prompt. A dispute is evidence: losing
the oldest costs a sample, and refusing new ones would stop recording exactly when the fault got
worse. The running total is separate and never resets, so a machine can still report that this
happened sixty times after the ring has turned over four times.

### Reading what it collected

`GET /api/overlays` carries `dispute_total`, a count of episodes since the process started, and
`disputes`, the last `dispute_log_max` of them. For each record:

1. Walk its own `overlays` against the four-reading table above. The record carries `own_activity`,
   `last_activity` and the `activity_grace_sec` it was read against, so the first two readings are
   decidable from the record alone, without the live process and without `/api/data`.
2. For the second two, diff its `drop_counters` against the record before it. The live counters
   cannot do this job hours later, because they are cumulative and a single read cannot be
   bracketed; two consecutive records can, because each carries its own copy. Two things to know
   before reading that diff: the first record in the ring has no neighbour, so its counters are the
   totals since the process started rather than a delta, and the counters are process-wide, so the
   window between two records covers every session rather than the one the records are about.
3. `repeats` and `last_seen_at` say how long the episode stood, and what that means depends on which
   state overruled the wait. On an `idle` record it is the whole answer, since an idle overlay has no
   deadline and a long one is a stale overlay pinning a live wait. On a `working` record it can never
   exceed the working TTL, because a refreshed working overlay carries a new arrival sequence and
   therefore opens a new record. The signature to look for there is not one long record but a chain
   of consecutive records for the same session, each a fresh working overlay over the same standing
   wait.

### It is one direction, and it only ever watched the collector

Two scope limits, both easy to read past.

Zero disputes is not evidence of zero faults. This catches a contradiction the collector can see,
which means the collector has to have found the wait. Where a fault starves both paths at once, a
hook that never fired leaves the event path empty and the collector's own notification state unset,
so both halves say Working, they agree, and nothing is recorded. That case is real and is the fourth
reading in N-5.

A dispute needs a collector wait and an overlay that overrules it, and no harness but Claude has
both. That sentence used to read "only the Claude collector ever produces a `needs_input` row", and
it was true when it was written; it is not now, and it failed in the two opposite directions at once.

Codex reports a gate as an **overlay** and has no collector detection, so there is no collector wait
for an overlay to contradict. Copilot is the mirror image: its collector raises the wait off the
permission pair in its own store, and no overlay can ever reach the row, because Copilot has no entry
in `events.IDENTITY_NORMALIZERS` and `events.parse` refuses its envelopes. Cursor sits exactly where Copilot
does, for the same two reasons. So the ledger is structurally blind to a gate on any of the three,
and a zero on a Codex, Copilot or Cursor machine is not a measurement.

A Copilot row is not left unwatched by that, only unwatched *here*. This ledger exists because an
overlay can pin a live wait behind a stale Working row and nothing else would notice. A collector
that re-derives the state from the file on every refresh has no such failure mode: the same
`permission.completed` that answers the gate is the record that clears it.

It has a different one, and it is the mirror of the Claude case N-2 answers. The answering record is
written by the CLI when the human replies, so a CLI that dies at its own dialog never writes it, and
the request stands, ahead of the busy test, for as long as the row stays inside the activity window.
A resumed session then reads Needs input while it is visibly working. What retires it is the session
writing a `user.message` past the request: the dialog owns the input while it is up, so a typed
prompt is proof it is gone. That is deliberately narrower than the evidence would allow. The capture
has the file quiescent for the whole 36, 44 and 48 seconds a gate stood, so *any* record written
after a standing request would do. But no arm ran a subagent, and a child writing into the parent's
file while the parent's dialog stands would silence a real gate under exactly the fan-out where one
is most likely. A killed session that never comes back is not covered by any of this and cannot be:
the store records the question and never records the process going away, and there is no lock file
beside it to ask. It ages out with the window, and `SKILL.md` says so on the Copilot row.

Worse, the direction a Codex row can fail in is the one deliberately not recorded here. "It records,
it does not decide" below explains why the reverse case, an overlay wait wrongly standing over a
session that is generating, is left out: on Claude it is the ordinary event-ahead-of-scan path at
every permission prompt, and counting it would bury the case this ledger exists to find. For a
harness whose *only* path is the overlay, that ordinary case and the fault are the same shape, so
nothing separates them. A Codex gate that should have been retired and was not has no detector, and
adding one means the separate detector that paragraph already says this would need.

### Only one direction counts

A collector Idle row that an overlay promotes to Working is the ordinary path, and counting it would
bury the case worth finding under every ordinary one. So would a collector `needs_input` that an
overlay agrees with.

Both `working` and `idle` count as overruling a wait. Idle is as wrong as Working for a session
holding a question, and the idle dwell makes it the likelier of the two to arrive late.

### It records, it does not decide

The patch is applied either way, and the row still reads whatever the reducer said.

The tempting change is to let the collector's `needs_input` win, on the fail-visible principle N-3
applies to unrecognised notification types. It is not made here, and the reason is that DRC-4095 and
DRC-4097 are this same disagreement resolved the other way: a wait that should have been retired and
was not. Their fix is exactly that a later working overlay retires an earlier wait, and their tests
pin it. The two directions cannot both be loosened.

Which way to move is a question about how often each side is right, and nobody has that number. This
produces half of it: how often an overlay overrules a collected wait. The other half, how often an
overlay wait wrongly stands over a session that is generating, is deliberately not recorded here,
because that shape is the ordinary event-ahead-of-scan path at every permission prompt and counting
it would bury this one. It is DRC-4095 and DRC-4097 territory and would need its own detector.

Half a number is still the half that was missing, and it is the half this milestone is about.
Deciding first and measuring afterwards is how DRC-4134 got a mechanism that turned out to be
impossible.

## N-7: saying what it is waiting for, and why that is two changes rather than one

Knowing a session is blocked is worth less than knowing what it is blocked on. "Force push to main?"
is a decision a person can make from the board; "open question (AskUserQuestion)" is a reason to go
and look, which is the trip the row exists to save (DRC-4015).

The board note that opened that issue said this was pure rendering, over data already parsed. Half of
that was right and the half that was wrong is where the work is.

**The parse threw the text away.** A pending input tool was kept as `{name, ts}`, and the question
lives in the `tool_use` block's `input`, which was dropped on the floor. Summarising it at parse time
rather than keeping it raw is deliberate: `ExitPlanMode` carries a whole plan, sometimes thousands of
words, and a plan has no business in a session row or in the caches a row is built from. A plan is
reduced to its first line, which is its own title in practice. A question is the first question, with
a count of the rest.

**An agreeing overlay then blanked it anyway.** No overlay constructor sets `detail`, so every
needs-input patch carried None and `apply_patch` wrote that over whatever the collector had found.
The fix is narrow on purpose: the collector's detail survives only when the row was already Needs
input and stays Needs input, which is the case where the overlay agrees about the state and
contradicts nothing.

How often that erasure fired is **not measured**, and an earlier draft of this paragraph said it
happened on every default install, which the repository cannot support. It needs an `input_requested`
overlay, which only `PermissionRequest` mints. `captures/` now holds one Claude `PermissionRequest`
record, in `claude/notification-2.1.241-macos.jsonl`, and it is a single tool-permission prompt for
`NotebookEdit`. So the hook is observed firing for a tool gate. Whether it also fires for
`AskUserQuestion` and `ExitPlanMode` is still unobserved, and is an adapter claim of exactly the kind
this repository requires a capture for. Until there is one,
the honest statement is that the erasure is reachable and its frequency is unknown. The fix is
correct and costs nothing either way.

Working and Idle still clear the field, and that is not an oversight. A working detail such as
`running Bash` is true of a session that is running and false of one stopped at a gate, so it must
not follow the row into a wait. And a question that has been answered must not outlive the overlay
that retired the wait, which is exactly DRC-4095 and DRC-4097.

### What it deliberately does not do

The text still comes from the transcript alone, so it appears when the record has reached disk and
does not when it has not (N-4). The row says a question is open either way; it can only sometimes say
which. That is stated in `SKILL.md` rather than smoothed over, because a field that is usually there
teaches a reader to trust it and then fails silently on the sessions that matter.

There is a second window, and it is the ordinary one rather than the exotic one. For up to
`overlay_working_ttl_sec` after a turn starts, a live working overlay overrules the collector
outright: the row reads Working, the detail is cleared, and the question is invisible even when the
record is on disk and the parse has it. `_keep_wait_detail` cannot help there, because it only holds
when the patch agrees the row is waiting, and this patch says Working. That window is bounded, it is
the disagreement N-6's recorder exists to count, and it is the reason the sentence above applies to a
default install and not only to an unlucky flush.

Sourcing the text from the event path instead would make it reliable and is not a rendering change:
the envelope drops the tool name and the tool input at the hook, deliberately, and `SECURITY.md`
states that as a property. Reopening it is a security decision, not this one.

`notification_type` is present on every Notification payload. Its value list was read from the emit
sites in an installed 2.1.226 bundle, and three of the values the classification branches on are now
observed on the wire instead: `captures/claude/notification-2.1.241-macos.jsonl` holds
`permission_prompt`, `elicitation_dialog` and `idle_prompt`, each classified the way this build
already assumed. A plain main-session permission prompt carries **`permission_prompt`**, raised twice
from different tools, which closes the first of the two inferences below.

One inference is still open, and it is the one that matters to `worker_permission_prompt`: that a
worker's **network** request has no `PermissionRequest` behind it. The capture run could not produce a
`worker_permission_prompt` at all. A subagent driven to a tool outside the allow list surfaced a plain
`permission_prompt` on the leader's own session prefix, alongside a `PermissionRequest` carrying the
tool name, so the tool half demonstrably has both signals. That is consistent with the reasoning (the
emit site is tool-scoped) without testing the network half, which needs a worker network request that
is not allow-listed.

Two method notes, because both of them silently produced a run that looked like it worked and measured
nothing. A headless run auto-denies and never raises a prompt, so this needs an interactive session.
And a session that loads a user's own settings may be unable to raise a prompt either: a bare `allow`
list grants the common tools outright, and `--permission-mode default` overrides the *mode* and not
the *list*. Drive a tool the list does not name.

## N-8: the queue clears itself out of measurements, and holds no state of its own

The gates were on screen before they were a queue (DRC-4018). What B7 added was an order that means
something, a position, a handle, and a cursor. What it deliberately did not add is any record of
which gates you have dealt with.

That is the obvious feature and it was rejected. A "handled" mark would be the page asserting
something no collector measured: Compass never writes to a session and cannot observe an answer, so
the mark could only record that a person clicked something. Two failure modes follow, and the second
is the serious one. A mark that is right is redundant: the session leaves `needs_input` within a
poll and the row goes on its own. A mark that is wrong **hides a gate that is still open**, which is
the exact failure the needs-input band exists to prevent, now caused by the surface built to prevent
it. The asymmetry decides it: the redundant case costs nothing and the wrong case costs everything.
One case escapes that argument rather than weakening it, and it is carved out at the end of this
section.

So the pass is driven entirely by the payload. You answer in the session's own terminal; the
collector stops calling that session blocked; the row leaves the queue on the next refresh. The
cursor is held as an entry key rather than an index precisely so this works. `focusKeyIn()`
resolves a key that has left the queue to the current head instead of writing the fallback back, so
answering the row you are standing on advances the pass, and answering a row above the one you are
standing on does not slide the cursor onto a different session. A cursor held as an index would do
the second thing silently. DRC-4178 extended the same rule to the questions rather than adding a
second one: a pending ask is keyed on its registration id, so the key a question holds behaves the
way a session's does and the one cursor walks both.

The same reasoning is why the queue's order is published by the server rather than derived in the
page. `row_order()` in `aggregate.py` ranks blocked rows by `blocked_since`; both views render that
order rather than each re-deriving it, so the band and the ledger cannot name a different gate at the
head. `waitingQueue()` merges the pending questions into that order without re-sorting either list,
which is what let the page hold one order over both kinds without the page inventing a ranking of its
own. [design-ask-lane.md A-5](design-ask-lane.md#a-5-the-merged-order-is-a-reader-over-two-arrays-not-one-array-with-a-synthetic-row)
owns that merge and what it costs calm. Calm's `attention` ordering ranks on the raw timestamp for the same reason, not on the elapsed
`waitSec` it displays: that value floors at zero, so two implausibly future stamps would tie in the
ledger while the server still separated them.

### What it deliberately does not do

It does not tell you how long answering will take, which gate is cheapest to clear, or which is most
urgent beyond how long it has waited. Waiting time is the only ranking signal the payload actually
carries; anything richer would be a guess dressed as an ordering.

### The carve-out: a question the session asked is answerable, because it is measured

The rejection above rests on one fact and not on a preference. A native gate is unanswerable here
because Compass cannot observe the answer: it never writes to a session, so a mark could only record
that a person clicked something, which is the page asserting a state no collector measured. Every word
of that still holds for every gate on the needs-input band, and nothing about it is softened by what
follows.

The `ask_operator` lane (see [design-ask-lane.md](design-ask-lane.md)) is a different situation on
exactly the fact the argument turns on. There, the answer *is* measured. The session called the tool
and is holding the call open until an answer arrives, so the runtime is the thing the session is
waiting on rather than a bystander guessing at a terminal it cannot see. A click is not an assertion
about someone else's state; it is the state. The wrong-mark failure mode cannot occur either, because
there is no gate left open behind the click: the option the reader chose is what the tool returns.

The two therefore stay two kinds, and the distinction is the load-bearing part. They share a queue
and a cursor now, but not their rules: a question comes from `d.asks` and never from `sessions`, it
carries buttons where a gate carries an id to copy, `x` marks a gate handled and does nothing to a
question, and the band still keeps no handled state of its own. A future change that wants to mark a
native gate has to overturn the paragraph above on its own merits, and cannot borrow this carve-out to
do it: an answer the runtime delivered and a click about a terminal nobody read are not the same
evidence.

<a id="n-9"></a>

## N-9: Idle was two situations, and only an event can separate them

Idle covered a turn that ended and nobody read the result, and a session still waiting on a reply
that never came. Nothing on a collected row separates them, because both are a transcript that
stopped changing. Only an observed `turn_stopped` does, so a row now carries `finished_at`, the stamp
of the last stop seen for it, and both views read the two apart instead of printing the one word.

The stamp is held outside the overlay ledger, and that is the one place this design departs from
N-5's rule that `session_ended` retires everything a session's events wrote. The coordinator keeps it
in a map of its own: `session_ended` pops the ledger whole, and for `claude -p` the stop and the exit
arrive back to back, so a mark kept in the ledger would be destroyed for exactly the sessions the
mark answers for. It is still reduced through `events.reduce_overlays` rather than written straight
onto the row, so it passes the same `session_activity` guard the idle overlay does and a session
resumed by a background task loses it. A working or waiting overlay clears it, and a collection that
stops producing the row is its only other bound, since no event ends it.

**The end-of-session git reading joined that lifecycle, after shipping without it.** DRC-4037 keeps
one `git status` reading per session in a second map beside the marks, for the reason above: the
event that produces a reading is the event that pops the ledger. What the first build did not do was
retire the reading where the mark is retired, and the reducer's own clears cannot cover that gap.
Those clears sit inside the working, waiting and idle overlay branches, so each lapses with the
overlay carrying it while a reading does not, and the side channel's staleness guard read
`bool(finished_at) and ...`, which is vacuously false the moment a working overlay has popped the
mark. A session that ended, resumed, and then worked for longer than `overlay_working_ttl_sec`
republished its last clean reading as `dirty: false` permanently, which is DRC-4101's confident green
over absent evidence one field over. The reading now rides the mark's presence as well as its
freshness, and `_mark_finished` discards it on the same two overlay kinds that discard the mark. The
general lesson is that a guard which only runs at render time cannot protect state that outlives the
thing carrying the guard.

**The display threshold is measured, not inherited.** Across 10,119 returns to a stopped turn in
1,355 local Claude transcripts, half were answered inside 106 seconds and nine in ten inside 966, so
past 1,200 the odds are better than ten to one that nobody is coming back to that one soon. That is
the gate both views apply. `SKILL.md` states it in minutes, and a documentation test reads the
constant and requires the prose to agree, because otherwise the two can only match by accident.

### Rejected

- **Marking on the stop itself.** It puts the word on nearly every idle row within seconds, which is
  Idle restated in a second vocabulary: the fault the retired `stale` chip was dropped for. That
  chip's 7,200 seconds is twice the 97th percentile of these returns and was never re-argued, so it
  stayed silent through the whole window in which collecting the finished work is still worth
  something.
- **Narrowing what `session_ended` retires**, which would have let the mark live in the ledger after
  all. Claude fires that event on `/clear` as well as on exit (N-5), so a cleared session would read
  finished forever, which is DRC-4101's failure class by another door. *Amended 2026-09-06: the
  premise is wrong. `/clear` mints a NEW session id, so the cleared id is not the one that carries
  on (see N-12). The rejection stands anyway, on the second reason rather than the first: retiring
  the ledger whole is what keeps a retirement coherent under arrival order, and a mark that lives in
  the ledger cannot outlive the exit it describes, which is the whole of what N-9 needed.*
- **A third flag.** The two-flag cap is a shipped decision, and finished work is worth collecting
  rather than worth alarming about, so the word sits in the `idle / wait` cell and in the regular
  view's idle row. A chip would also pull the count into the flagged total, the `f` filter and the
  attention ordering, none of which should move because a turn ended tidily.
- **Clearing the git reading on every `session_ended`** rather than on the resume. It looks like the
  tighter rule and buys nothing measurable: the resume discards the reading before any second end can
  reach it, so no test could tell the two apart. *Amended 2026-09-06: this bullet carried a second
  reason, that "two ends with no turn between them, which is how `/clear` followed by an exit
  arrives, would discard a reading that is still accurate", and that scenario cannot happen.
  `self._git` is keyed on `SessionKey`, and N-12's measurement is that the prompt after a `/clear`
  goes to a NEW session id, so the clear's end lands on one key and the exit's on another. The
  rejection stands on the first reason alone.*
- **An arrival-order guard on the reading**, mirroring either the `max` that keeps the completion
  mark from being pulled backwards by a redelivered stop or the `arrival_seq` comparison that makes
  the overlay ledger idempotent. Reproduced first, with the probe and the thread spawner injected:
  two overlapping session ends for one key, a slow probe answering 111 entries and a fast one
  answering 222, published 222 and then 111 as each returned. The guard is still the wrong fix.
  Those two neighbours hold values the event itself carried, so the event's order is what decides
  which is newer; a reading is an observation whose freshness is the moment the probe finished, so
  last completion wins is correct and an arrival-order guard would let the LATER-arriving event pin
  an older reading of the tree. The direction is worth stating, because the guard sounds protective
  read the other way round: the mirror is last-writer-wins sorted by `arrival_seq`
  (`events.py:630`), so a max-seq guard keeps the seq-2 event's answer, and in the reproduction
  above that is the fast probe, which finished first and so observed the tree earlier. What the
  overlap earned instead is a gate on the dispatch: the second probe no longer runs. The accepted
  cost of that is stated where the gate lives, and it is the same refuse-rather-than-evict trade the
  maps beside it already make.
- **Retrying a saturated git probe once when a slot is released (DRC-4467).** Retain refusal under
  the [canonical concurrency contract](../SECURITY.md#repository-git-reads-the-end-of-session-probe).
  With a ceiling of two and four distinct ends, draining both probes and running collection left
  two readings and two nulls, with only two dispatches. There is no automatic recovery without
  another eligible end event: redelivering `session_ended` for a refused key in the same process
  dispatched a third probe and supplied its reading. Retry-on-release is deferred work even when
  limited to one attempt. A bounded queue is possible, but no measured legitimate saturation
  workload earns it here. Revisit only with that evidence and specified capacity and overflow,
  deduplication, freshness and resume handling, row retirement, shutdown, and attribution of a
  later tree reading to an earlier end. Both the per-session guard and the process ceiling remain.
- **Letting a collector infer completion** for the six harnesses with no turn-end adapter. A guessed
  completion renders identically to a measured one, so those rows disclose `scan-only` through
  `acquisition`, which was defined for this. A test holds the collectors to it. *Amended
  2026-09-08: this bullet said the field "rendered nowhere until now", written when the stamping
  site landed, and it stayed false for two and a half weeks. Nothing under
  `compass_runtime/web/` read the name at all, so the disclosure the rejection rests on was
  published and never shown. DRC-4473 put it on the row; where and in what words is
  [design-scan-only-rows.md](design-scan-only-rows.md).*

## N-10: a Cursor gate needs a liveness gate, and a time limit cannot be it

The other three harnesses close a wait with a record. Claude's overlay is superseded, Codex's
expires, Copilot's is answered or written past. Cursor's store closes nothing on its own: it is
append-only, and a session that was abandoned at a gate leaves its non-empty contract map in the
newest blob it will ever write. There is no lock file, no pid, nothing beside the store that records
the process going away.

That is not a hypothetical. The capture ran a control arm over ten readable stores no arm of the
probe had driven, and **2 of them read as waiting 29.4 hours after their process exited**. Neither
had a tool result matching its pending call id, so both were genuinely still at a gate and both were
genuinely dead. Publishing them means permanent red rows for sessions nobody is in, and since
DRC-4192 pointed the desktop notifier at every harness, a popup with each.

So the wait is gated on `active`, the freshness test the row already runs on. Three things recommend
it over the alternatives:

- It is the same reading the title is already gated on, so a row cannot be current enough to name and
  too stale to trust in the same refresh.
- It holds under `--all`. That mode shows a row whose `active` is False, which is the door the
  measured 29.4-hour case would otherwise have walked through.
- It costs nothing: it is a comparison against a number the collector has already computed.

Liveness alone still trusts whatever the bytes said. A second rule bounds the reading itself: the
stamp has to be plausibly this store's own newest write. The write that raises the gate is what puts
`pendingToolCallStartedAtMs` on disk, so on a real gate the stamp and the file's mtime are the same
moment, give or take the hook that ran first (20 seconds in the probe's slowest arm). A stamp from
long before that write is not the conversation's current state, and there are two ways to get one: a
neighbouring object inside the 8 KB window the reader pulls, and bytes that merely spell the field,
which a message quoting a store record is enough to produce. Either publishes a red row and a popup
carrying a wait nobody believes, and nothing retires it, because the blob that produced it stays the
newest carrier for as long as the store exists. So a stamp outside the activity window of the
store's own mtime drops the whole reading rather than the wait's start time. The window is the
activity window and not something tighter: nothing measured how far a genuine gate's stamp may trail
a later write to the same store, and a missed gate is a row that reads Working where an invented one
is a desktop notification.

Two smaller rules follow the same grain. Inside the chosen blob the last carrier wins, for the reason
the blob itself is chosen by highest `rowid`: a blob is bytes appended in order, and first-match
disagrees in both directions, reading an answered-then-reopened gate as no wait and a gate-then-answer
as a wait that never ends. And a gate read that raised is never memoised. The memo is keyed on the
store's mtime, and a standing gate freezes that mtime by construction, so caching the `None` an
exception leaves behind hides that gate for the whole life of the wait. The one failure that is a
reading rather than an accident, a schema with no `blobs` table, is told apart by asking
`sqlite_master` rather than by matching SQLite's error text, which is text SQLite is free to change.

### Rejected

- **`working_threshold_sec` as the liveness test.** It is 90 seconds, and a gate the probe
  deliberately left standing ran 243.7 seconds without expiring. A real permission wait can last
  hours; a 90-second liveness would drop it after the first minute and a half.
- **Capping the age a wait may reach.** `config.py` already rules that a needs-input overlay has no
  deadline, for that same reason, and nothing in the capture found an upper bound to lean on.
- **A minimum stand before a gate counts**, which is what Copilot's collector does. Copilot needed
  it for a measured race: `copilot -p` without `--allow-all-tools` auto-denies every gated call, and
  the capture times that request/answer pair 1 ms apart, so a tick landing inside it could catch a
  half-written pair and raise a popup for a run nobody is watching. Cursor has no such pair to catch.
  The two states are two different blobs rather than one record being amended, and a read-only
  connection sees only committed ones, so there is no half-written state to sample. The shortest gate
  the probe recorded stood 15.3 seconds. A floor here would be guarding against something nothing has
  observed.
- **Retiring the gate when the session writes past it**, Copilot's other fix. Cursor needs no rule
  for it, because the reading is already newest-by-`rowid`: answering the prompt appends a blob with
  the map emptied, and that blob is the one the reader takes. The retirement is structural rather
  than a heuristic about which record counts as proof.

### What it still cannot do

A session abandoned at a gate an hour ago is inside the window and reads as a standing wait, exactly
as a Copilot one does. The liveness gate moves the boundary to the edge of the activity window; it
does not find the process. Nothing in the store can, and the capture says so rather than implying it.

A subagent's gate is invisible. A Cursor child keeps its own store and folds onto its parent's card
as a pill, so its rows are never published and its pending contract is never read. The capture's
`other-prompt-kinds` arm records `subagent_store_tested` as false, so this is an untested shape as
well as an unhandled one, and widening the read to children without a measurement would be inventing
the parent's state from a file nobody has looked at at a gate.

How many times one blob can carry the key is unmeasured. The capture counted contract entries and
never occurrences, so the last-carrier rule above is reasoning from the store's append-only shape
rather than from a count. The reader sees 4096 bytes either side of the first occurrence; a second
carrier further out than that is not reachable without materialising the whole blob, which is the
read the window exists to avoid. One read-only query over real stores would settle it, and it has
not been run.

Only a shell gate was driven. MCP prompts, plan decisions, question tools and sudo requests are all
recorded unmeasured in the same arm; whether they write the same key is not known here.

A store whose blobs are encrypted reports no wait. Every store measured was plaintext, but every
`meta` payload carries a `blobEncryptionKey`, so some build almost certainly encrypts them. There the
bytes simply do not match and the session reads as nobody waiting, which is the honest reading of
bytes we cannot read. The key is never used, for the reason the model read gives: opening a user's
conversation to label a card is not a trade this dashboard makes.

## N-11: Pi raises no approval prompt, and the wait it does publish is not passive

DRC-4190 asked what fires while Pi's own approval prompt stands. The premise is wrong: Pi raises no
approval prompt of its own. The built-in trust prompt is `project_trust`, asked once per
directory rather than once per tool call. The vendor is explicit about how little it covers: it "is only an input-loading guard. It prevents a repository from silently changing pi's
settings or extensions before you approve it. It does not make untrusted code, untrusted prompts, or
untrusted model output safe."
([pi.dev/docs/latest/security](https://pi.dev/docs/latest/security).) A gate on a tool call is
something an extension builds, from the `tool_call` event returning `{ block: true }`, so a stock Pi
has no gate for a collector or an adapter to find.

That excluded tool approvals from the original probe. Pi does publish a different wait.
`ui_prompt_start` and `ui_prompt_end`
fire around `ctx.ui.select()`, `ctx.ui.confirm()`, `ctx.ui.input()`, `ctx.ui.editor()` and
`ctx.ui.custom()`, and the documented purpose is this board's own: "so host/status integrations can
report 'waiting for user' instead of just 'running'". `ctx.sessionManager.getSessionId()` supplies
the key an overlay would be filed under. Nested prompts coalesce into one outer span, and handlers
are best-effort rather than awaited, so what arrives is a notification about a wait and never a hold
on it. ([pi.dev/docs/latest/extensions](https://pi.dev/docs/latest/extensions).)

DRC-4380 now ships that adapter, measured on 0.85.1 with persisted session IDs. Coverage excludes
startup trust and unnamed future prompt kinds. No store-only wait path or turn-end mapping is
claimed by this adapter; each would need its own evidence.

Antigravity still has an unbuilt gate path, for a harder reason: its confirmation-pending flag
already reaches `statusline_hook.py`, which reads `agent_state`
and drops the rest, and using it needs the reducer precedence rule N-4 describes rather than an
adapter nobody has written. Nothing is wanted from either vendor.

## N-12: a session that ended and one waiting for you both said Idle

N-9 separated a turn that stopped from a session still waiting on a reply. It did not separate either
of those from a session that is **over**. `finished_at` cannot: it marks a turn stopping, and a
session whose turn stopped is usually still open, still typeable, and still worth going back to. So a
`claude -p` run that exited and a session sitting at its prompt rendered identically.

The row now carries `ended_at`, a nullable stamp set when the session id itself is observed to end,
and `CLOSE THE LOOP`, the operations row and the session detail all read it (DRC-4036).

**`/clear` was the objection, and it dissolves.** Claude fires `SessionEnd` on `/clear` as well as on
exit, and the capture that recorded it
([`claude/session-end-2.1.261-macos.jsonl`](captures/claude/session-end-2.1.261-macos.jsonl), arm
a7) reports the process surviving and accepting another prompt 0.277 s later. Read from that file
alone the only thing separating a continuation from an ending is the event's `reason`. A separate
probe on 2026-09-06, on the same Claude Code 2.1.261, answered the question the capture could not:
**the prompt after a `/clear` goes to a new session id.** Two prompts either side of one `/clear`
wrote two different transcripts. So a `session_ended` means "this session id is finished" whatever
its reason, `reason` never has to cross `events.ALLOWED_FIELDS`, and no adapter has to special-case
a clear.

**A nullable stamp, not a fourth `state` value.** A new state member was investigated and rejected
because three page sites read `state` against a closed set and fail toward the *wrong* answer on an
unknown member rather than degrading: `nextAttentionStopSignal` drops the session out of Safe to
close, which is the lane this exists to strengthen; the project activity pill blanks; and the
coverage note reports it as "unknown state", the opposite of what was observed. `None` follows
`finished_at`'s contract exactly: it means NOT OBSERVED, never "did not end". Only a SIGKILL ends a
Claude session silently, but an adapter-less harness, a session predating the server run and
`--no-events` are all absences too, so the page never reads silence as life.

**What lifts the mark, and what deliberately does not.** A `session_started` lifts it, because
`claude --resume <id>` reuses the id; so does a working or needs-input overlay, because a session
doing something has not ended. An idle overlay does not: every tidy ending has a `turn_stopped` in
front of it, and lifting on idle would erase the mark for exactly the endings this exists to show.
`session_started` needed an explicit path, since `overlay_for` returns None for it and it reaches
neither `_remember` nor `_mark_finished`. The comparison is on event stamps rather than arrival
order, because a reordered delivery is precisely one whose arrival order lies about causality, and
the a1 arm's 5.581 s gap between the last stop and the end is longer than a short headless run.

**Its retirement rule differs from N-9's, and has to.** `session_ended` pops the session's overlays,
so straight after an end the key is in neither the collected row set nor the ledger, which is
exactly `_finished`'s prune condition. `_finished` tolerates that because the next `turn_stopped`
re-supplies it; a session fires `session_ended` once, so a mark pruned early can never be earned
again. It is therefore retired on two conditions rather than one: the row must have left the
collected set **and** the end must be a display window old. The clock is there for the reason
`focus_target_ttl_sec` uses (a row is produced only while its activity is inside that window, and
an end is the last thing that happens to an id), and the row-set half is there so a session still
being collected keeps its mark however long ago it ended. Neither alone would do: the clock alone
would strip a live row's mark at the window, and the row set alone is `_finished`'s condition above,
which an end satisfies immediately.

### Rejected

- **Carrying the event's `reason` and special-casing `clear`.** An earlier draft of this issue called
  for it, on the capture's own reading. The new-session-id measurement makes it unnecessary, and it
  would have cost a member of `events.ALLOWED_FIELDS`, a public compatibility surface with an
  indefinite tail, to encode a harness-specific vocabulary the server would then have to keep
  interpreting.
- **A boolean `ended`.** Null's job done by false: every harness with no adapter would publish a
  confident "did not end" over no evidence at all, which is the DRC-4101 shape one field over.
- **Applying `finished_at`'s activity guard to the end.** A stop is a reading of a moment that later
  writing invalidates. An end is a fact about an id, and the id cannot write again without a
  `session_started`. An end also lands *after* the last write rather than before it, 5.581 s after
  the final stop in the a1 arm, so the guard would have read a perfectly ordinary ending as a
  contradiction.
- **Reading an absent end as "still running".** The most tempting inference on the page and the one
  the capture forbids: only a SIGKILL is silent, but that is one of four causes of an absence, and
  the coverage note says so rather than counting them as live.

<a id="n-13"></a>

## N-13: the browser has no idle hook, so its nudge fires on the polled edge

A reader with the tab open on Linux or Windows got no notification when a session fell quiet. The
two lanes are exclusive by design (`notifications.native_notifier` returns `osascript` on darwin
and `""` everywhere else, and `next-notify.js` fires only when `/api/data` publishes the empty
string), so on those platforms nothing raised anything for a working-to-idle transition. The macOS
lane did: `notification_disposition` returns `(needs_input=False, popup=True)` for
`IDLE_NOTIFICATION_TYPES`, and `handle_payload`'s five gates never ask whether the transition is
idle.

**The issue asked for a new `/api/data` field and did not need one.** Measured against the
assembled bundle at the time: the payload already carries `native_notify` and per-session `state`
and `active`, and `nextNotifyState` already holds each session's previous state. Driving a
working-to-idle transition with `native_notify:""` and permission granted, the page observed working,
then idle, and raised nothing, while the same fixture's working-to-needs-input raised one
`Notification`. The single test stopping it was a `state !== "needs_input"` comparison. So this is a
web-only change and the field is not part of it.

**The trigger is not the same event, and the page says so rather than pretending.** The native lane
fires off Claude's own `idle_prompt` hook. The browser has no hook of its own, so the edge it can
see is `state` moving from `working` to `idle` on the published row, and a row reaches `idle` two
ways, which is why the wording has to cover both. Where a harness's lifecycle hooks are installed,
its `Stop` becomes a `turn_stopped` event and `events.overlay_for` returns an idle overlay
`overlay_idle_dwell_sec` (3 s) later, so the row turns over within one poll of the real turn end.
Everywhere else the row turns over on the collector's own reading, once writes have paused for
`working_threshold_sec` (90 s). The two coincide often and not always: a turn whose writes pause for
ninety seconds crosses the threshold without the harness declaring anything.

**The `active` gate is ordered below the quiet branch, and that ordering is load-bearing.** The idle
overlay patches `active: False` alongside `state: "idle"`, and `active` is in `events.PATCHABLE`, so
`_apply_overlays` writes it onto the collected row. A `nextNotifyEdge` that tested
`session.active !== true` first therefore refused precisely the transition the nudge exists to
report, and refused it on the **default** install, since `compass/hooks/hooks.json` and
`compass/hooks/codex-hooks.json` both declare `Stop`. Worse, the edge was then spent for good:
the suppressed render still recorded `idle` in `nextNotifyState`, so a later idle row with
`active: true` raised nothing either. Measured: the instrumented arm went 0 to 1 once the quiet
branch moved above the gate, with no double-fire when the overlay later retires.

`previous === "working"` is the liveness check the gate would otherwise have supplied, and it is
sufficient rather than merely cheaper: the working overlay and every collector's working state both
carry `active: true`, so a row cannot be seen `working` at one render without having been live at
it. A dead or ended row cannot nudge without having just been observed working. The gate still
guards the needs-input branch, whose overlay sets `active: True`.

The near-parity reading is shipped deliberately, and the disclosure is in the sentence:

- The quiet nudge's title is `<harness> has gone quiet`, which is what was observed. It does **not**
  reuse the gate lane's `waiting_title` (`<harness> is waiting on you`), because that is a claim
  about intent, and nothing on this path measured intent. The two share the session's tag, so a row
  that goes quiet and then asks a question replaces its own banner instead of stacking a second.
- The edge is `working` to `idle` and nothing else. `needs_input` to `idle` also lands on idle and
  raises nothing, because the reader answered the question and was standing there when it cleared.
  A row seen idle for the first time raises nothing either, because there is no previous state
  to have moved from.

**Quiet repeats have a ten-minute floor per tab and per `(harness, sid)` (DRC-4475).** Only a
successful `Notification` construction starts the floor. Denied permission, native ownership and
a constructor that throws do not. Every observed state is still recorded, including a suppressed
edge: a later nudge needs a new working sighting followed by idle, and becomes eligible at 600
seconds. A session disappearing from one payload does not clear its unexpired floor. Expired
timestamps are discarded on the next sync. Needs-input and exact questions keep their own delivery
rules and do not wait for this floor.

The value follows the native `popup_repeat_suppress_sec` precedent, without claiming parity with
its other gates. One uninterrupted silent tool call can yield one false quiet sighting; repeated
crossings require renewed working evidence. The floor limits interruptions, not turns: a later real
turn inside it can be suppressed, and a long turn with renewed activity can nudge again after it.
Constructor counts are what the tests measure, not operating-system banner alerts. Dismissed rows
are already removed in `aggregate._subtract_dismissed` before assembly; the browser reads no
dismissal store.

### Rejected

- **Exact parity through the notification `kind`.** `handle_payload` computes `kind` and drops it
  for the idle types, so recovering it means publishing a new field and threading it to the page:
  the field this issue was refuted for asking for, bought back for a distinction the reader cannot
  act on differently.
- **Reusing `waiting_title` for both edges.** One sentence for two facts, and the stronger of the
  two is the wrong one: a turn that stopped is not a request. The gate lane's wording exists because
  the native notifier and the browser both render it and they drifted once; that argument is about
  one fact rendered twice, not about collapsing two.
- **Gating both edges on `active`, for symmetry.** It reads tidier and it is the bug above: the one
  edge whose own overlay clears `active` is the one edge that must not be gated on it. Anyone
  reordering those two branches to match the needs-input branch reintroduces it, which is why
  `next-notify.js` carries a comment at the site rather than leaving the order to look arbitrary.

<a id="n-14"></a>

## N-14: repeating-source evidence needs a lease and visible uncertainty, not an inferred answer

Discrete lifecycle hooks and repeating status-line renders have fundamentally different contracts.
A discrete hook fires once per edge (`UserPromptSubmit`, `Stop`, `PermissionRequest`). A repeating
status source (such as Antigravity's status line) renders periodic state snapshots. When an agent
pauses at a gate, the status line may repeat a confirmation flag or fall silent between renders,
followed by ordinary status updates that do not reflect human interaction with the gate.

Treating ordinary Working or Idle heartbeats from a repeating source as proof of resolution clears
a standing wait while the user is still blocked. Conversely, treating a repeating wait as permanent
leaves the board stuck forever if the session drops or the prompt is dismissed without an edge.
The DRC-4573 ruling resolves this with a source-specific evidence lease and visible uncertainty:

- **Source classification.** Events from status lines carry `source_instance_id` and are classified
  as repeating sources (`SOURCE_CLASS_REPEATING`). Hook-driven lifecycle events remain discrete
  sources (`SOURCE_CLASS_DISCRETE`).
- **Heartbeats neither clear nor renew.** An active repeating wait outranks subsequent Working and
  Idle renders from that same source. Heartbeats do not clear the wait, nor do they renew its lease.
- **The 300-second product threshold.** A positive pending observation starts or renews a 300-second
  evidence lease. The 300-second duration is an approved product threshold rather than a measured
  safe maximum, because human confirmation prompts can remain open for hours.
- **Visible uncertainty, never an inferred answer.** After 300 seconds without a fresh positive
  observation, the wait transitions to an unconfirmed state (`wait_unconfirmed: True`). The board
  continues to show the session in the needs-input section and adds an explicit disclosure:
  `Unconfirmed: no positive observation in 5m; prompt may still be standing`. Elapsed time never
  proves an answer or safety.
- **Age preservation.** When a fresh positive observation renews the lease, it preserves the original
  `blocked_since` timestamp from the start of the wait rather than restarting the wait age.
- **Explicit resolution retirement.** Only a matching explicit resolution (`input_resolved` from that
  same harness and source instance) or session end permanently retires the wait.
- **Other harnesses untouched.** OpenCode and Pi explicit-resolution adapters gain no timeout. Claude
  and Codex lifecycle rules remain intact.
- **Antigravity admission boundary.** Antigravity's `tool_confirmation_pending` flag remains
  deliberately unmapped in `statusline_hook.py`, and `reports_needs_input` remains false for
  Antigravity in the harness registry. Reducer and display prerequisites are delivered without
  claiming native Antigravity wait detection.
