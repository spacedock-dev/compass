# Design: marking a session handled

Owner for the question "I have dealt with this one, why is it still on the board?". The module map
belongs to [design-runtime-architecture.md](design-runtime-architecture.md); this document owns four
decisions that three later features will inherit, because this is the first user-authored state
Compass keeps and the cheapest place to settle its shape.

Before it, nothing a reader did survived a run. `lifecycle.write_state` records the instance (pid,
port, log) and is rewritten every time one binds and deleted when it stops. The browser remembers a
display mode and a usage preference, but those move with the profile rather than with the machine,
and neither is something the server could act on.

## D-1: the store is a server file, not `localStorage`

A browser-side filter was the smaller change by a wide margin: no Python at all, no endpoint, no
config field, no new module, no amendment to [SECURITY.md](../SECURITY.md).

It is also wrong, for one reason that decides it. `summary.needs_input`, `summary.active_sessions`
and `summary.open_tasks` are counted inside `Application.collect`, from the rows it is about to
publish. A page-side filter cannot reach them, so the tile would go on saying **2 waiting** with one
row on screen, and the tab title would go on saying `(2!)`. Every consumer that derives a total (the
tile, the title, `gateQueue`, calm's idle clip) would need its own copy of the rule.

Subtracting on the server fixes all of them at once and costs each of them nothing.

The page keeps no mirror. An optimistic hide was on the table and was dropped: a row removed before
the server agreed is a claim the board cannot back, and a POST that fails would leave the reader
believing they had cleared something. The row leaves when the next payload arrives without it.

## D-2: a mark lapses on activity, never on a clock

The rule: a dismissal holds while the row's `last_activity` stays at or below the watermark recorded
when the mark landed.

A wall-clock time-to-live was the obvious alternative and is the wrong shape in both directions at
once. It re-shows sessions that never came back: the mark expires, the row returns, and nothing
about the session has changed. It also goes on hiding sessions that did come back, for as long as
the window lasts. Those are the two failures a reader would call the feature broken for, and a TTL
produces both.

`last_activity` rather than `own_activity`, which is the whole-subtree reading rather than the
session's own writes. Any movement in the tree means the work resumed, and a parked parent with a
running child is exactly the row a dashboard must not hide. (The two fields, and why they differ, are
in [design-needs-input.md](design-needs-input.md).)

The watermark is the **server's clock at the moment of the mark**, not a value the caller sends. That
was a security choice as much as a simplifying one: "hide until activity exceeds T" with a large
enough T is a row hidden forever, and a clock the server owns cannot express it. It is also
sufficient: a session's next write is later than the instant the reader marked it, whether the row
was idle for an hour or generating at the time.

<a id="d-3"></a>

## D-3: an unanswered gate is clearable, and clearing silences its popup

A gate the reader has decided to answer somewhere else is exactly the row they want off the board, so
refusing to clear it would be answering the wrong question.

The trap is the second half. Subtracting in `collect` is not enough, because the popup is raised
*from inside the collection*, before the subtraction runs, so a cleared session would keep raising
desktop notifications for as long as it stayed blocked, which reads as a feature that does not work.
The gate therefore lives in `notifications`, where the popup policy already lives, and it consults
the same set the subtraction does: `collect` refreshes the store before the harness loop rather than
after it, precisely so the two cannot disagree inside one collection.

The popup moved out of Claude's collector and up into `Application` in DRC-4192, and the decision
still runs before the subtraction. That order is a convention rather than a constraint, and it is
worth naming as one: `maybe_popup` returns on the dismissal before its own bookkeeping, so a cleared
row records nothing whichever line runs first, and swapping the two changes no observable behaviour
(measured on the suite, not reasoned about). What the order buys is that the gate stays the thing
that refuses a cleared row, so the design holds if `maybe_popup` ever stops consulting the store
itself.

The hook ingress (`POST /api/notify`) is gated too, and it has no `last_activity` to compare. It uses
the transcript's mtime, which is the conservative half of the collector's figure: it can only be
older, so that gate lapses no earlier than the collector's and never later. The hook itself is still
stored: only the popup is refused, so restoring the row brings its standing question back with it
rather than an empty board.

## D-4: the payload loses the row entirely and carries only a count

`sessions` never contains a cleared row. The payload carries `cleared`, the number this collection
subtracted, and `dismiss`, the capability flag that tells the page whether the control exists at all.

The alternative was a `cleared: true` field on the row, with the page filtering. It breaks the moment
any consumer forgets the flag, and there are four that would have to remember it. That is the bug
class this codebase writes comments about, so the row is simply not there.

Revealing what was cleared is a separate request, `GET /api/cleared`, rather than a `?cleared=1`
variant of `/api/data`. The variant was the first plan and it reintroduces exactly what D-4 avoids:
whatever it put in `sessions` would land in front of the tab title, `gateQueue` and the summary, and
each would need to know which request it was answering. What the reveal actually answers is a
different question (*which sessions have I marked?*), so it gets a different response, holding the
store's own records and nothing derived from a session. `SnapshotKey` is unchanged as a result.

## The file

`~/.compass/compass-dismissals.json`, `{"v": 1, "entries": [{harness, sid, at, seen_activity}]}`.

Not per port, unlike `compass-<port>.json`: a mark is the reader's and has to outlive both a restart
and a different `--port`. `remove_state` must never touch it.

**Bounded by count, at 256, oldest `at` evicted first.** A count and not a time-to-live, for the D-2
reason: a TTL that pruned an entry would re-show a session that never came back, which is the
failure the invalidation rule exists to avoid. 256 is an order of magnitude above the busiest board
measured (31 live sessions), and at roughly 100 bytes an entry a full store is a quarter of the
64 KB read cap.

**Failure degrades to "no dismissals", never to a lost row.** A missing file, a truncated one, a
non-object, `entries` that is not a list, a file past the read cap, and JSON nested deeply enough to
raise `RecursionError` rather than `ValueError` all yield an empty tuple, and every row stays visible.
A single malformed entry is dropped on its own so it cannot discard the reader's other marks. Both
strings go through `records.safe_text` at 64 characters, because they reach the DOM through the
reveal endpoint; both timestamps go through `records.norm_epoch`, where a string or a null becomes 0.
And 0 is the safe direction, since it lapses on the session's next write.

An unwritable store returns `persisted: false`. The next collection rereads the disk store and can
lose the in-memory mark. Needs you reports that Compass could not save the change and offers Undo
only for a saved mark or dismissal.

More than one Compass can bind on one machine, and they share the one file. Each re-reads it at
the top of every collection, so a mark made in one dashboard is picked up by the other within a
poll. A write reads and merges the stored marks under the process lock, then atomically replaces
the file after releasing that lock. Overlapping writes can each produce a complete file and the
last replacement wins. Needs you sends one change at a time and disables the other dismissal
controls while that write is pending. Overlap across dashboards remains possible.
