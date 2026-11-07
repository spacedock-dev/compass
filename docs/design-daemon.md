# Design: daemon mode and the retired in-dashboard stop control

The durable rationale behind `--daemon`, `--status`, `--stop`, the two HTTP routes that back them,
and the stop control removed when the replacement dashboard became canonical. It records the
decisions and the alternatives that were tried and rejected. The rejected ones are the expensive
part, because without them they get re-attempted.

Behavioral detail lives in [`COMPATIBILITY.md`](../COMPATIBILITY.md) (the per-OS matrix), the written
paths and the `/api/shutdown` exposure are owned by [`SECURITY.md`](../SECURITY.md), and the
user-facing contract is the skill body. This file explains *why*, not *what*.

The code behind all of it is `compass_runtime/lifecycle.py` (state file, port probes, status, stop,
fork and re-spawn) driven by `compass_runtime/cli.py`, which owns the three serve branches.
`server.py` is a seven-line launcher and holds none of it. Which file owns what, and why the three
branches stay distinct rather than collapsing into one rule, is owned by
[`design-runtime-architecture.md`](design-runtime-architecture.md).

Each decision keeps a stable `D-N` anchor, and code comments cite them by name. Grep the identifier
across `*.py` and `*.md` before renumbering anything.

---

## The problem these decisions answer

Compass is started by an agent, in that agent's session, as a background child of the session's
shell. Two consequences, and they pull against each other.

The dashboard dies with the session that opened it. That is wrong on its own terms (a board
watching ten harnesses is not an artifact of whichever session happened to open it), and it is
worse for the notification path, whose whole point is to fire with no browser tab open. Detaching
fixes it.

But a process nothing supervises and nothing reaps is worse than one that dies too early, unless
there is an obvious way to end it. Before this work, "stop it" meant the three platform-specific
`lsof`/`netstat`/`taskkill` blocks in the skill's Stop section, and the `cmd` form matches any port
whose digits contain the string you asked for. That is not an off-switch a person reaches for. So
detaching and a reliable off-switch shipped together, in one change, because neither is worth
shipping alone.

## D-1: `--daemon` detaches, and the socket is bound before it does

On POSIX: bind the listener, then double-fork (`fork`, `setsid`, `fork`), with both parents leaving
through `os._exit(0)` to avoid flushing inherited buffers twice.

Binding first is the load-bearing part. `bind_error_message()` exists so that a busy port produces an
explanation instead of a traceback, and the skill tells the agent to check for an already-running
dashboard when it sees one. A daemon that forks before it binds sends that message to a log file
nobody has been told about yet, and reports success instead. Binding first is what keeps a busy-port
message on the terminal that asked, instead of in a log nobody reads. That is the whole value of
the ordering, and it is easy to get backwards because forking first *looks* more conventional.

`stdin` comes from `os.devnull`; `stdout` and `stderr` are `os.dup2`'d onto the log file so that
writes from C and uncaught tracebacks land there too, not just Python-level prints.

No `chdir("/")`. It is conventional, it buys nothing for a loopback dashboard that resolves every
store path from `HOME`, and it would silently change how any relative path in the process resolves.

<a id="d-2"></a>

## D-2: Windows re-spawns instead of forking, and waits to be sure

There is no `fork`, so the parent starts a fresh copy of itself with
`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, `stdin` from `DEVNULL`, `stdout`/`stderr` to the log
file, then waits for the child to become reachable, bounded by a named constant,
`DAEMON_READY_TIMEOUT_SEC = 10`, polled against `/api/health`. If the child exits first, or the wait
runs out, the parent prints the tail of its log and exits 1.

That wait is how Windows keeps D-1's promise. The parent cannot observe the child's `bind()`
directly, so it observes the consequence, and a port conflict remains a message on the terminal
rather than a silent failure.

The answer has to be matched against the child's own pid, and the first version of this did not do
that. A dashboard already on the port answers `/api/health` perfectly well, so the parent accepted
that as proof, reported success, and handed back a pid belonging to a process it had not started,
while the child it spawned was dying on the bind. The `platform-tests` job on Windows caught it; the
POSIX path was never affected, because there the bind happens in the parent before any fork. This is
what the pid in the health payload is for, the same reason `--status` needs it (D-4). A foreign
answer now reports that the port is already served by a different Compass and points at `--status`.

The child needs no private flag: it is an ordinary foreground run that happens to own no console. One
fewer argument, and one fewer way for the two paths to diverge.

Every opt-out the parent was given reaches the child, and the set is read from the parser rather than
listed. `spawn_argv` forwards each `no_*` destination the parsed namespace holds as True, which is
every `--no-*` switch `cli.build_parser` defines under its canonical spelling, so
`--no-harness-usage` arrives as `--no-observer-model`. It reads the namespace rather than the parser
because `cli` imports `lifecycle`, and the reverse edge would break the inward-only import rule. A hand-kept list
was tried first and dropped `--no-annotations` and `--no-tripwires` (DRC-4655), so a Windows daemon
turned both stores back on. The test parses the respawn argv back through the CLI and compares the
child's config with the parent's for every switch, and a second test holds the convention the
derivation reads: every `--no-*` option is a store-true switch whose destination starts with `no_`
and spells it. A `--no-*` flag that took a value would be dropped silently, and a `no_*` switch
spelled otherwise would make the child exit 2, so either shape fails that test first. The renderer choice is always forwarded, the default included, so a respawn never falls back to
its own default. No opt-in is forwarded; one that ever is will
travel with `--no-observer-model`, which the derivation always carries.

The Windows branch has to be checked, and the re-spawn dispatched, *before* the POSIX bind-then-fork
path runs. Reversing that order means the parent holds the listening socket it is supposed to be
handing to the child.

## D-3: One state file per port, written by every instance that binds

`~/.compass/compass-<port>.json` holds `pid`, `port`, `started`, `version` (the release, null when an install records none), `log` and `python`;
`~/.compass/compass-<port>.log` is the log. The directory is created `0o700`. `COMPASS_HOME`
relocates it, which is how this project already treats store locations: when the variable is set it
is authoritative.

One layout on every platform. `XDG_RUNTIME_DIR` on Linux, `%LOCALAPPDATA%` on Windows and a
`~/.compass` fallback would be three code paths, three sets of documentation and three ways for
`--status` to look in the wrong place, to place a file more correctly than anyone needs.

Foreground runs write it too. A user who started the server without `--daemon` still benefits from
`--status` and `--stop`, and a state file that exists only sometimes is a state file whose absence
means nothing.

This adds the only paths Compass writes. `CONTRIBUTING.md`'s read-only constraint is about harness
stores and still holds exactly as written, but `SECURITY.md` has to say what is written and where:
including that nothing ever deletes or rotates the log, so `~/.compass` accumulates one log per port
indefinitely.

## D-4: Liveness is an HTTP probe. Never a signal, and never `os.kill`

`os.kill(pid, 0)` is the usual liveness check, and it must not be used here. On Windows, CPython
implements `os.kill` for ordinary signal numbers through `TerminateProcess`, the call that is
supposed to inspect a process kills it instead. This is not a hypothetical: it is the kind of thing
that looks correct in a POSIX-only test run and only shows up once someone runs `--status` on
Windows and kills the very process they asked about. A cross-platform `--status` built on `os.kill`
would terminate the dashboard it was asked to describe.

So `--status` requests `/api/health` and reads the state file, in that order of authority:

| Observation | Report |
|---|---|
| answered `/api/health` as Compass | running, with the pid *it* reported, start time and URL |
| answered, but not as Compass | the port belongs to another process, so touch nothing |
| nothing answered, state file present | stale; `--stop` deletes the file and says so |
| nothing answered, no state file | absent: nothing recorded and nothing listening |

Row two is why the pid is in the health response at all. Without it, "something is listening" reads
as "Compass is running", and the next step is a kill aimed at an innocent process.

The pid the state file records is deliberately *not* compared against the pid health reports, and
`--status` believes health when they differ. A state file is a claim about the past. A killed
instance leaves one behind, and the next instance on that port writes its own, so treating a
mismatch as "foreign" would refuse to stop a live, legitimately restarted dashboard on the strength
of a stale file. The live answer is the evidence; the file only supplies the log path and the
stale-versus-absent distinction. The one place a pid comparison *is* the point is `await_spawned`,
where the parent knows its own child's pid and a dashboard already on the port would otherwise pass
for it.

`--stop` is idempotent by design: it exits 0 whether it stopped a running instance, cleaned up a
stale state file, or found nothing at all, and exits 1 in the foreign-process case, the one case
where it deliberately did nothing. A script can call `--stop` unconditionally before starting a
fresh instance.

Which is exactly why it does not return on the 200 alone. The handler answers before it stops, and
`server.shutdown()` takes up to one poll interval to be noticed, after which the listening socket
closes only once `serve_forever()` has returned. Returning on the 200 asserted a completed stop
while the port was still bound, and the obvious restart (`--stop`, then start again) failed on a busy
port and was told to go look at a dashboard that was in the middle of shutting down. `--stop` now
waits for the port and exits 1, saying so, if it never comes free.

Waiting means asking the right question, and the right question is not "is anything listening". A TCP
connect to a bound socket that nothing is accepting from still completes, so a connect probe cannot
see the window between `serve_forever()` returning and `server_close()` running. Each probe
leaves an unaccepted connection in the backlog, so after `request_queue_size` of them the probe
starts reporting the port gone while it is still bound. `port_released()` therefore *binds*, with the
same options as the real listener down to `SO_EXCLUSIVEADDRUSE`, because what the caller wants to
know is whether a new listener could take the port, and a probe more permissive than that listener
answers a question nobody asked.

Only `EADDRINUSE` counts as "still held". A bind refused for privilege says nothing about whether the
port is in use. A dashboard started as root on port 80 and stopped over HTTP by an ordinary user,
which needs no privilege, made `--stop` sit out its whole timeout and then report an instance still
listening after it had gone. Where a bind cannot answer, `port_released()` answers "not held",
because the caller is deciding whether to keep waiting rather than whether to trust the port.
Windows is the exception written into the code: an in-use port reports `EACCES` there once
`SO_EXCLUSIVEADDRUSE` is in play, the same ambiguity `bind_error_message` already names.

Two things this deliberately accepts. The probe really binds, so for the ~20µs it holds a free port
it can lose a genuinely concurrent restart the coin toss. With one bind per 50ms of waiting, its
measured duty cycle was roughly 0.04%, and the loser gets the ordinary busy-port explanation rather
than anything silent. And exit 0 has to mean the port is takeable, which is why the branches where
nothing answered `/api/health` wait too: `main()` removes the state file *before* it closes the
listener, so a stop already in progress arrives at "nothing running" with the port still bound, and
reporting success there is what made the unconditional stop-then-start unsafe in the first place.

## D-5: Stopping uses one code path over HTTP

`--stop` POSTs `/api/shutdown`, which is also what the retired UI button did. The canonical dashboard
does not expose that control, but the route remains available to the CLI and integrations. There is
still one implementation of stopping and no signal-handling difference between platforms to
reconcile.

A wedged server that has stopped serving cannot be stopped this way. The existing per-platform kill
blocks therefore stay in the skill body, demoted from the documented way to stop Compass to the last
resort for a server that has stopped answering. A `--force` flag that reimplements them in Python is
not worth its own cross-platform surface.

`--daemon` combined with `--diagnose`, `--stop` or `--status` is an argparse error. Each of those
three exits without serving, so `--daemon` cannot mean anything alongside them, and accepting it
silently would teach that it had been honored.

## D-6: The two new routes, and why stopping happens on its own thread

`GET /api/health` returns `{"ok": true, "pid": …, "port": …, "started": …, "version": …}` and touches no
filesystem. The skill previously sent the agent to `/api/data` to ask whether a dashboard is up,
which runs a full scan across every harness store to answer a yes-or-no question.

`POST /api/shutdown` returns `{"ok": true, "stopping": true}` and is gated by the existing
`_local_ok()`: the `Host`, `Origin` and `Sec-Fetch-Site` checks that already protect `/api/notify`.
It responds *before* stopping, and calls `server.shutdown()` on a thread it spawns.
`main()` removes the state file in a `finally` and exits 0.

An earlier revision of this design justified that thread as deadlock avoidance, on the theory that a
handler cannot call `server.shutdown()` from inside itself without the accept loop hanging. That
reasoning does not hold here, and it is worth being precise about why: the listener is a
`ThreadingHTTPServer`, so `ThreadingMixIn.process_request` gives every request its own thread, and
the accept loop is never the thread that dispatched the handler. `BaseServer.shutdown`'s deadlock
warning describes a server whose handler runs on the same thread as `serve_forever`, the case a
threading listener is already clear of. Calling `shutdown()` inline here would not deadlock.

The thread earns its place for two duller reasons instead. First, `shutdown()` blocks until the
accept loop notices the request, which can take up to one poll interval (0.5s by default); running it
inline would hold the client open for that long just to deliver "stopping". Second, it keeps the code
correct if the listener class ever stops being a threading one. At that point the handler *would*
run on the serve loop's own thread, and an inline call really would deadlock exactly as the docstring
warns. The thread costs nothing today and removes a footgun for whoever touches this later.

The exposure is worth stating plainly rather than leaving implicit. Any local process that can reach
the port could already read every session on the machine through `/api/data`. It can now also stop
the server, a smaller capability than the one already granted, gated by the same trust boundary and
the same `_local_ok()` checks. `SECURITY.md` says so rather than leaving a reader to work it out.

<a id="d-7"></a>

## D-7: The retired button armed before it fired, and the stopped page was not the stalled page

This section preserves the interaction reasoning for the dashboard control removed during the UI
promotion. It describes the retired implementation rather than the current interface.

A `stop` button sits beside the display toggle, in both display modes. The first activation arms it
in place, asks for confirmation, and restores focus after the header re-render; the second POSTs.
`Enter` and `Space` on that focused button are activations, not unrelated keystrokes, so their
keydown must reach the native button click without disarming first. Anything else the reader does
first disarms it: `esc`, a click anywhere else, another control, or another key. Arming survives a
render on purpose, so whatever is not made to disarm it, it outlives. Sort the ledger, toggle a
mode, come back later, and a single click would stop the server having never been confirmed at all.
The second activation only means something while it is still answering for the first.

Disarming on a click and not on a keystroke was the same mistake in miniature. The keyboard drives
the same controls the mouse does (`c` is the mode button, `f` the flag, and `Enter` opens a row), so
the scenario above stayed reachable with one hand on the keyboard, and the button kept its armed
label for an interaction that had long since finished. Both input paths disarm now, except
for `Enter` or `Space` while the armed stop button itself still has focus.

The terminal panel takes no keystrokes at all, which is a separate guard from the one in `render()`
and needs to be: `setDisplayMode` writes `localStorage` *before* it paints, so a `c` pressed on the
stopped panel looked inert while durably flipping the saved display mode for the next run. The
keydown listener therefore returns on `serverStopped` before anything else, which also stops it
calling `preventDefault()` and swallowing page scrolling on a page that is no longer live.

`stopArmed` lives in a module variable and is reapplied after each render, which is the rule
`CONTRIBUTING.md` already states for anything a reader set: `#app` is rebuilt from scratch every five
seconds, so state that is not reapplied is state the refresh eats. Here that rule has teeth: a
button that disarmed itself on the next poll would arm and disarm under the reader's cursor.

No keystroke is bound to stopping. Calm mode gives single keys to moving, expanding and filtering,
all of which are free to get wrong.

On success the page enters a terminal stopped panel and stops polling. Falling through to the
existing "stalled · retrying" banner would be actively misleading: nothing is retrying,
nothing is coming back, and the reader is the one who ended it. A failed POST shows the error inline
and disarms, because the server is still running and the page should not pretend otherwise.

Making the panel actually terminal took three attempts, and the two failures are the instructive
part. `serverStopped` is checked in `render()` itself, as its first statement, because `render()` is
the sink: every `innerHTML` and `document.title` write on the page is either inside it or inside
`renderStopped()`.

Guarding the *caller* was tried twice and was wrong twice. First only at the top of `refresh()`,
which skips a poll yet to start but does nothing about one already in flight. `/api/data` is the
slow request here while the shutdown POST is a loopback round trip, so a reply landing after the stop
is the common ordering rather than a narrow race. Then also after each `await` in `refresh()`, which
fixed the poll and missed that `refresh()` is one of fifteen callers: `setDisplayMode`, `toggleIdle`,
`calmAction`, `calmCopyId`, the sort/state/flag/open paths, and the keyboard all end in
`render(lastData)`, and the keydown listener is bound to `document`, so nothing in `#app` gates it.
A single `c` brought the whole dashboard back. Both failures repainted a live-looking board with a
stale needs-input count in the title, for a server that was gone, with the interval already cleared
so not even the stalled banner was left to contradict it.

The rule that generalises, and that `CONTRIBUTING.md` now carries: guard the sink, not the caller you
happened to be looking at. The `refresh()` checks stay anyway, because they also skip `recordRates()`
on stale data and the `latestSettledRefresh` bookkeeping, neither of which runs through `render()`.
The one in the failure arm carries its own point: a stop the reader asked for is not a
refresh failure and must not drive the stalled bookkeeping.

## Verified: the macOS notification path survives detaching

The one thing this design refused to assume rather than reason about: whether `osascript display
notification`, fired from a fully double-forked session leader with no controlling terminal, still
reaches the user's Aqua session. It does. A `--daemon` server, started under a temporary
`COMPASS_HOME`, received a `permission_request` POST and answered `{"ok":true}`; its log file stayed
at 0 bytes, and `notify_mac()` logs any non-zero `osascript` exit through `diag()`, which in a
daemon, goes to that same log file, so a silent log is itself the evidence that `osascript`
reported success. A control `osascript` invocation in the same shell exited 0 for comparison.

The double-fork keeps the daemon in the user's login session rather than moving it to a new one,
which is why this works, and it is the main reason daemon mode is worth having: delivering the popup
with no browser tab open at all.

One caveat worth keeping attached to this result: it proves `osascript` reported success, not that a
banner was visibly displayed. Focus modes and Do Not Disturb can still suppress on-screen display
independently of whether the process is attached to a session. That is a macOS notification-center
setting, not something detaching affects one way or the other.

The equivalent question for Linux and Windows is not this design's to close; it is
[`plans/native-notifications.md`](plans/native-notifications.md), which daemon mode makes more
valuable and does not otherwise touch.

## Rejected

- **Documenting `nohup` and `Start-Process` instead of writing code.** Cheapest, and it leaves the
  agent choosing between per-shell incantations that cannot be tested. The old Start section was
  already three code blocks for one idea.
- **Signals for stopping.** D-4: unusable on Windows, and D-5 gets one code path without them.
- **`psutil` for process liveness.** Stdlib only, permanently.
- **An idle timeout that exits on its own.** The request was a way to turn Compass off, and there is
  now a button and a flag. A dashboard that vanishes because nobody looked at it is a new surprise,
  not a fix for the old one.
- **Platform-correct runtime directories.** D-3.
- **Inheriting `HTTPServer.server_bind`.** It sets `server_name` from `socket.getfqdn()`, a reverse
  DNS lookup on the startup path for a value nothing in this codebase reads. A resolver with no
  answer for `127.0.0.1` does not fail fast, it waits: measured at roughly 17.5 seconds per bind on
  the macOS CI runner, where seven tests that bind, or spawn something that binds, accounted for
  285 seconds of that leg's 316 while the other 1936 finished in 31. Ubuntu answers the same lookup
  from `/etc/hosts` instantly, which is why it read as a macOS problem rather than as a lookup
  nobody needed. `CompassHTTPServer.server_bind` calls `socketserver.TCPServer.server_bind`
  directly and sets `server_name` and `server_port` itself. Restoring the `super()` call reinstates
  the stall, for the dashboard's own startup as much as for the suite.


## Terminal monitor holders

The monitor sidecar uses a detached subprocess of the existing entry point rather than forking the
client: POSIX `start_new_session`, Windows `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, closed
descriptors and all standard streams on `DEVNULL`. Its hidden mode is dispatched before `cli` and
is not a public operation. A short command lock covers spawn through readiness; the worker takes a
lifetime lock before admitting a lease. Both lock paths persist so a waiter never locks an obsolete
inode. Stop is a generation-bound file request, never a signal to a PID read from disk. Failed
readiness cleans up only the parent's own child. Signals converge on bounded stop and cleanup;
a hard kill leaves the lease to lapse after 50 seconds.

On POSIX, the starting command walks its ancestors with bounded `ps` calls and remembers the nearest
executable named `claude`, its PID and start time. The worker checks both so PID reuse does not keep
an orphan. It checks at most once every five seconds; the faster stop-file poll starts no process.
Windows skips this check and never calls `os.kill(pid, 0)`. With no matching ancestor,
row/lease endings, a 30-second continuous exchange failure budget and a two-hour idle bound still
end the worker. A dashboard identity change exits with a status-file reason and no new start:
restarting would replay or bypass a consumed typed command. The monitor store owns that status;
footer files remain the dashboard's alone.
