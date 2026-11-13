# Design: a session asks, the reader answers

Owner for the question "why does the only path from the dashboard into a session look like this?".
The module map belongs to
[design-runtime-architecture.md](design-runtime-architecture.md#r-1-one-responsibility-per-file-and-the-launcher-owns-none);
the shipped security contract belongs to [SECURITY.md](../SECURITY.md). This document owns the four
alternatives weighed on the way there, one of which was rejected and then reversed, because each one
is the shape a later change would reach for first.

Everything before this feature ran one direction. Collectors read harness stores, the page rendered
what they read, and the two things a reader could do (dismiss a row, stop the server) changed only
what the reader saw. `ask_operator` is the first thing a reader does that changes what an agent does
next, and it exists in exactly one shape: the session asks, and the answer is a choice among options
the session itself wrote.

## What was measured, and why the shape follows from it

The hold was re-measured attended on both harnesses before any of this was designed, because the
original measurement was taken on a path no user is on (headless `claude -p` with permissions
pre-granted, and Codex under `approval: never` with `sandbox: danger-full-access`). The captures are
[`captures/claude/mcp-ask-gate-2.1.239-macos.jsonl`](captures/claude/mcp-ask-gate-2.1.239-macos.jsonl)
and [`captures/codex/mcp-ask-gate-0.146.1-macos.jsonl`](captures/codex/mcp-ask-gate-0.146.1-macos.jsonl).

Two findings shaped the feature rather than merely confirming it.

The hold survives on the attended path: both harnesses held a 20 second tool call and delivered its
result, with the interactive TUI behaving as the headless run did. So a tool that blocks until a human
answers is a real mechanism and not an artefact of a sandbox.

The gate is client-side and comes first. On both harnesses the first call raised a permission prompt
in the user's own terminal, and the MCP server saw `tools/list` and then nothing at all until the
human answered there. That is why the standing permission is part of what ships rather than a setup
footnote: without the grant the feature is a no-op, and the reader who walks to the terminal to answer
the gate has already unblocked the agent by arriving.

## Whether anything actually calls it, which was the real risk

DRC-4172 named this as the acceptance question rather than a footnote: a build that works and is never
called has failed. It now has a measured answer, and the answer is conditional rather than yes or no.
The capture is
[`captures/claude/ask-roundtrip-2.1.239-macos.jsonl`](captures/claude/ask-roundtrip-2.1.239-macos.jsonl).

Two trials, the same scenario both times: an ambiguous irreversible delete where nothing on disk
records which file to keep. Neither prompt mentioned the tool, Compass, or asking.

Attended, the agent did not call it. It checked mtimes, git and project memory, then ended its turn
with a report refusing to guess. That is the right behaviour and the tool was redundant to it, because
ending a turn already reaches the human.

Framed as an unattended overnight batch whose final message nobody reads until morning, the same
scenario produced an unprompted `ask_operator` call. The question it wrote named the ambiguity, gave
both readings of the evidence, and offered a third option the prompt had not suggested. The answer was
honoured.

So the tool is reached for when it is the only way to reach a person, and correctly ignored when it is
not. That is a narrower claim than the issue hoped for and a much better one than "unmeasured", and it
locates the feature's value precisely: long autonomous runs, not attended ones. It also means the
adoption lever is the situation rather than the prompt, which is worth knowing before anyone writes
skill-body copy to talk agents into calling it.

## A-1: the wait is a bounded long poll, not one held request

Rejected: the MCP server opens one request to the dashboard and the dashboard answers it whenever a
reader clicks. It is the obvious design, it is one round trip, and it needs no polling interval.

It also needs three things the runtime does not have, and the poll needs none of them.

A bound on concurrent holds. `ThreadingHTTPServer` spawns a thread per request, and the only
concurrency budget anywhere in the runtime is `stream_max_clients`. A held request per outstanding
question is an unbounded thread count decided by whatever is asking.

A release that declines. Handler threads are daemons and nothing joins them, so `shutdown()` never
touches a request in flight. A `--stop` during a held request drops the connection rather than
answering it, and the agent on the other end learns nothing. The poll turns this into a decline that
the next poll collects, which is why `decline_all()` is wired into both `_shutdown` and
`lifecycle.serve`'s finally block.

A read deadline on the accept path. `BaseHTTPRequestHandler.timeout` is `None`. A peer that declares a
small `Content-Length` and then goes silent pins a handler indefinitely, and a design whose normal
case is a pinned handler cannot tell that apart from its normal case.

The server has since gained a 10-second socket timeout and a cap of 64 connections. Neither
reverses the ruling: a held request per question would spend one of those capped slots for as long
as a person takes to answer, and the timeout bounds waits on the socket, not a wait on a reader.

Each poll returns inside `ask_poll_timeout_sec`, so all three become ordinary. The cost is a request
every few seconds per outstanding question, against a loopback server that already publishes a
snapshot on a five second cadence.

## A-2: the answer is an index, never an option string

Rejected: the answer body carries the chosen option's text, and the MCP server returns that text to
the agent. It is simpler, it needs no server-side record of the question, and it survives a restart.

It is also a general purpose channel for putting attacker-chosen text into any local agent's context,
bounded only by a body cap. Anything on the machine that can reach the loopback port could answer a
question with content of its own, and that content becomes a tool result the model reads as the
user's own decision.

So the options are recorded when the question is registered, the answer body carries the question id
and an integer, an out-of-range index is a no-op, and the MCP server returns `options[index]` from its
own copy of the list it was called with rather than anything the dashboard sent back. That copy is
redacted and cut in the MCP server's own process, by `records.cut_text`, the function the dashboard
draws the card with, so the string returned is the label that was clicked. It can therefore read
`…REDACTED` or end in `…` where the agent's option did not, but every character in it comes from the
agent's own text or from that function, never from the dashboard. The dashboard's register reply
echoes the card's text so the MCP server can withdraw a card that differs from its copy; the echo is
compared, never returned. What that buys is
a hard ceiling on a forgery: the worst it can do is select the wrong one of the options the asking
agent itself wrote. It cannot introduce a single character. That ceiling is what makes the loopback
exposure in [SECURITY.md](../SECURITY.md) an accepted one rather than a blocker, and it is the reason
the index rule is not an implementation detail to be relaxed later.

The id is generated with `secrets.token_urlsafe` and is not guessable, but it is deliberately not
treated as an authenticator. The index rule is the protection, and a design that leaned on the id
would be resting on a value that reaches the page.

## A-3: no new wake seam in the coordinator, and why that was wrong

Rejected, then reversed. `observation.py` now carries a seam a registration uses to demand a
collection, because both grounds this section gave for refusing it were false. The argument is kept
rather than deleted: it read well, it was wrong twice, and the two mistakes in it are the ones a
later change would make again.

What was argued. Registration calls `state.snapshot.clear()`, exactly as `_dismiss` already does.
The next collection includes the question, and `Application.collect_json` is the sole caller of
`state.streams.publish`, so every connected client wakes on the new revision. `run_producer` already
collects every `stream_producer_interval_sec` while a tab is open, which was said to put a question
on an open page within about five seconds using machinery that was already there. The seam was
rejected on cost rather than on latency: a registration path reaching into the coordinator would add
an `Observation._lock` to ask-registry edge that nothing else in the runtime needs, in the one module
that starts a thread, and lock cycles are the class of bug this codebase pays most to avoid.

The lock edge does not exist. `Observation._collect` takes and releases `_lock` around the read
rather than across it, and calls `self.application.collect_json`, and therefore `AskRegistry.pending`,
between those blocks. So `Observation._lock` was never held while an ask lock was taken, and a seam
that takes `_lock`, bumps the dirty generation and notifies adds no edge to a graph it was never part
of. What has to keep holding is one direction rather than a separation, and it is recorded as a
comment on both sides: `_lock` is the outer lock wherever the two are ever held at once, so the ask
path never calls into `Observation` while holding a registry lock, which is why `note_ask` is called
after `register` has returned.

The five seconds belonged to a path that was not running. `run_producer` is the fallback loop
`serve` starts only when the server carries no coordinator, which means `--no-events` and a good many
test doubles. On the default build the coordinator runs instead, `Observation._due` collects on a
dirty generation or on a periodic tick while a stream is connected, and a cleared snapshot is
neither, so nothing woke on a registration at all. What eventually noticed was the page's own 20
second fallback poll. Measured register to SSE revision: 3.2 s under `--no-events`, against 18.2,
22.3, 22.3 and 22.2 s on the default build. The figure quoted above was four times off on the only
path a user is on, and it was measured on the other one.

Latency was the smaller half of it. `AskRegistry.pending` is the only caller of `expire`, and the
collection is the only caller of `pending`, so on the default path a dashboard with no tab open never
collected, never expired an overdue question and never released an answered one. The budget filled
with resolved and abandoned asks, every later registration was refused, and `d.asks` reported
nothing the whole time. That is a permanent wedge on exactly the path this document locates the
feature's value on: long autonomous runs, with nobody watching. So `Observation._due` now returns
true while an unresolved ask exists, and `register` sweeps overdue and retained asks before it checks
the budget, which is what makes the lane heal with no reader, no tab and no collection.

The knob is still the cheaper fix for latency alone, and `stream_producer_interval_sec` is still
where it lives. What this section got wrong was not preferring a knob to a seam. It was pricing the
seam against a lock cycle that could not form, and the knob against a clock that was not running.

## A-4: an outstanding question is its own band, not a row in `sessions`

Rejected: the collection injects a synthetic session row so the question rides the gate queue and
inherits its ordering, its cursor and its keyboard handling for free.

[design-dismissals.md D-4](design-dismissals.md#d-4-the-payload-loses-the-row-entirely-and-carries-only-a-count)
already argued this in nearly the same terms, one direction earlier: a row that consumers have to
know is special breaks the moment one of them forgets, and there are several that would have to
remember. `gateQueue()` is a pure filter over `d.sessions` walked by three readers, each of which
would need the exception. The shared-project-label collision marker is the concrete failure: a
pseudo-row carrying the asking session's project label collides with the real row on the same label,
so the reader is told two sessions share a project when one of them is a card about the other.

So `d.asks` is its own array and its own band, and `d.ask` is the capability flag that decides whether
the control exists at all, matching how `d.dismiss` gates the dismiss control. The summary counts are
left alone for the D-4 reason as well: several tests pin that dict's shape, and the page can count an
array it already has.

What this gives up is real. The gate queue's ordering, its cursor and its keys do not extend to the
band, and calm mode gets a plainer rendering than regular mode does. That is a follow-up rather than a
reversal, and it is cheaper to add ordering to a band than to remove a special case from three
readers. A-5 is that follow-up, and it settles whether the estimate held.

## A-5: the merged order is a reader over two arrays, not one array with a synthetic row

The follow-up A-4 deferred had two routes, and they are the same two A-4 and
[design-dismissals.md D-4](design-dismissals.md#d-4-the-payload-loses-the-row-entirely-and-carries-only-a-count)
already weighed, arriving one layer later. The question this time is not where a question is stored.
It is where the single order over waiting sessions and waiting questions is defined.

Rejected, again: a synthetic row in `d.sessions`. Everything the queue has would come free, including
the parts a second array has to be taught one at a time: the band, the tile, the tab title, the
keyboard cursor, the desktop popup, and calm's ledger row, which is the surface a second array can
least easily reach.

The argument against it did not weaken between the two decisions, and one part of it got stronger.
`DECLARED_SESSION_FIELDS`, `row_order`, the summary counts, the dismissal store and the overlay
reducer all read `sessions` and would each need to know which rows are not sessions, which is D-4's
whole objection. The collision marker is still concrete: a pseudo-row carrying the asking session's
project label collides with the real row on that label, and the reader is told two sessions share a
checkout when one of them is a card about the other. What got stronger is the dismissal edge. A
gate is clearable and clearing it silences its popup (D-3), so a synthetic row inherits a `handled`
button that would write a mark against a session id for a question the store cannot express, and the
mark would lapse on that session's next write rather than when the question is answered. The two
concepts have different lifetimes, and the row shape has one.

Taken: `nextAttentionModel()` in the retired page's `next-attention.js` keeps asks as first-class Attention
signals. An ask with an exact owner joins that session's Needs-you subject; an unmatched ask remains
a standalone subject rather than becoming a synthetic session. Native gates without a matched ask
form their own session subjects. The comparator then ranks those subjects by the strongest waiting
evidence while stable identity breaks ties, so multiple asks for one session do not produce
competing session rows.

What it ranks on is primary kind first, then duration within each kind: asks (`primaryKind: "ask"`)
strictly precede native input gates (`primaryKind: "input"`). Within questions,
`nextAttentionCompareSubjects` ranks by longest ask age; within native gates, it ranks by duration
calculated from `blocked_since`. Because kind order separates questions from native gates,
the two kinds never compete directly on timestamp or swap positions under the reader.

That replaces the earlier interface's chronological interleaving, which is worth recording because
its rounding failure was real before the kind-first comparator replaced it. The obsolete `waitingQueue()`
ranked both kinds on a single reconstructed epoch: `blocked_since` for a gate, and `generated - age_sec`
for a question. Because `generated` is a float and `age_sec` was rounded to the nearest second, the
question's reconstructed `since` shifted across consecutive polls. Two waits that began within ~0.3s of
each other traded places every poll as the rounding landed either side of the sample, prompting a
proposed follow-up to publish an absolute `asked_at` epoch in `_ask_cards`. With #245 and #247 promoting
kind-first ordering in Attention, exact questions consistently lead native gates, settling the
churn without expanding the payload contract or adding `asked_at`.

The cursor holds a key rather than an index for the reason it always did, and a question needed a key
that behaves the way `sessKey` does. It is `ask:<id>`, the registration id: generated once from
`secrets.token_urlsafe`, never reused, the same value `/api/answer` addresses, and gone from the
payload at the moment the card leaves the board. The asking session's key was the obvious alternative
and is wrong, because one session may hold more than one question open and the two cards would share
a cursor.

What this route still cannot give, stated rather than smoothed over. In the regular view the band
draws the whole merged order in one container, because that view's other two sections exclude blocked
rows and nothing is drawn twice. Calm cannot: its ledger already carries every blocked row, so the
band there holds the questions and the gates stay in the ledger below. The cursor spans both, keyed
the same way and moved by the same keys, but the questions lead calm's pass because the band is drawn
above the ledger. So calm has one order for `g`, for the band, for the tile and for the title, and a
navigation order that follows the screen. Closing that last gap needs the two kinds in one container,
which is the synthetic row this section refuses, so it is the price of the refusal rather than an
oversight.

## What this deliberately does not do

It does not answer a harness's own permission prompt, and that is a refusal rather than an unfinished
edge. It does not type into a terminal, write a harness store, or reach a session that never called
the tool. And it holds no state across runs: a question outstanding when the server stops is declined
rather than resumed, because a question whose asker may no longer exist is not a question anyone can
answer.

It also does not decide how the question is *announced*. The notification split (which layer alerts,
what it may say, and why the ask lane keeps its own cooldown key) belongs to D-3 in
[`docs/design-cross-platform.md`](design-cross-platform.md#d-3-exactly-one-owner-per-notification-path).
