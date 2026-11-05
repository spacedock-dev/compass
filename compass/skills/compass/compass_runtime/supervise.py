"""Model subprocesses, each in a process group of its own (a Job Object on Windows).

`subprocess.run` kills only the direct child on a timeout. A CLI that has
started a helper, or the `cmd.exe` behind a `.CMD` shim on Windows, leaves that
grandchild running with nobody to reap it. Every model call Compass makes goes
through `run` instead, so a timeout, a shutdown and (DRC-4693) a Cancel kill the
CLI's process group and never the daemon's own: `--daemon` calls `setsid`, and a
foreground run shares the job of the terminal that started it. The limit on
POSIX: a helper that leaves the group, by `setsid` or `setpgid`, is not reached.
A Job Object on Windows has no such exit.

`run` keeps `subprocess.run`'s keyword subset, so a test that injects a runner
with that signature stays valid, plus `on_spawn`: it is handed the `Group` the
moment the child exists, which is the seam a reading job uses to say it is
waiting on the provider and a Cancel reaches the CLI through (`Group.cancel`). Output goes to a file
or nowhere, never to a pipe: every model call writes its reply to a file. `output_limit`
bounds that file (DRC-4667): the wait looks at its size every `_LIMIT_POLL_SEC`,
and once more after the group or Job Object has no live writer (DRC-4729).
Past the limit the call kills the group as a Cancel does and raises
`OversizedError`; the last write already in flight can finish after that kill.

When neither `waitid` nor kqueue can watch the exit, the call polls, and the
poll reaps the leader: helpers still in its group after a normal exit are then
not swept. A timeout, a shutdown or a Cancel still kills the group, because
each kills before the reap. It has been seen only under forced errors, so it is
documented (COMPATIBILITY.md, SECURITY.md) rather than fixed (DRC-4712).

This module imports nothing from the runtime.
"""

from __future__ import annotations

import contextlib
import errno
import os
import select
import signal
import subprocess
import sys
import threading
import time
from typing import IO, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

# Held across the spawn and its registration as well as across the shutdown's
# snapshot, so no child can exist between the two where a shutdown misses it.
_LOCK = threading.Lock()
_LIVE: set[Group] = set()
# Set once, by the shutdown, for the life of the process: a daemon on its way
# out starts nothing more (review F2, measured: a CLI spawned 0.2 s after the
# snapshot outlived the daemon).
_SHUTDOWN = threading.Event()
# How long a killed child may take to exit before the call stops waiting on it.
# SIGKILL is not ignorable, so the only children that outlast this are ones the
# kill never reached, and waiting longer would hang the reading instead.
REAP_TIMEOUT_SEC = 5.0
# How often a running call looks up from its wait to see whether it was
# cancelled. Only a kill that failed needs it: one that worked ends the wait
# at once. It bounds how late the call starts its own bounded reap.
_CANCEL_POLL_SEC = 0.1
# The slice while an output file has a bound (review F1). At 0.1 s an unpaused
# writer on an APFS SSD put 286 to 600 MiB on disk before the first look; the
# slice is what bounds the overshoot, since the kill itself took 88 ms.
_LIMIT_POLL_SEC = 0.01

_RUNNING, _EXITED, _REAPED, _UNKNOWN = "running", "exited", "reaped", "unknown"


class ClosedError(OSError):
    """The runner is shut down: nothing more is spawned in this process."""


class UnstoppedError(subprocess.SubprocessError):
    """A killed child did not exit within `REAP_TIMEOUT_SEC`, so it may still run."""


class OversizedError(subprocess.SubprocessError):
    """The CLI wrote past its `output_limit`, so its group was killed and reaped."""


def kill_group(pgid: int) -> bool:
    """SIGKILL one process group, and never this process's own.

    True when the signal was delivered or the group is already gone, False when
    the kill itself failed. The guard is the property DRC-4693 depends on, so
    it lives at the one call to `killpg` rather than at each caller: 0 and 1
    name the caller's own group and init, and `getpgrp()` is the daemon's.
    """
    if sys.platform == "win32" or pgid <= 1 or pgid == os.getpgrp():
        return False
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        # EPERM, including macOS's answer for a group left holding only a
        # zombie leader. Whether the kill mattered is settled by whether the
        # leader exits, which the caller waits on with a bound.
        return False
    return True


def _state(pid: int, timeout: float) -> str:
    """Whether a child is running, has exited, or is already reaped. Never reaps.

    `waitid` with `WNOWAIT` where `os` has it (Linux, and macOS from Python
    3.13), and a kqueue exit filter where it does not (macOS on 3.12, the
    floor). CI runs a macOS leg on each, since `hasattr` picks the branch. This
    only observes:
    what keeps a group from being signalled after its leader is reaped is
    `Group._reaped`, set under the group's lock in the same step as the reap.

    kqueue reports a registration it cannot make as an event flagged
    `EV_ERROR`, not as an exception. ESRCH there means the process has exited
    (a zombie cannot be registered either, and only `run` reaps, so it has not
    been reaped), and any other error means the exit cannot be watched:
    `_UNKNOWN`, which callers never read as an exit (verify N2).
    """
    return _state_waitid(pid, timeout) if hasattr(os, "waitid") else _state_kqueue(pid, timeout)


def _state_waitid(pid: int, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while True:
        try:
            info = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)  # type: ignore[attr-defined,unused-ignore]
        except ChildProcessError:
            return _REAPED
        if info is not None:
            return _EXITED
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _RUNNING
        time.sleep(min(0.02, remaining))


def _state_kqueue(pid: int, timeout: float) -> str:
    queue = select.kqueue()
    try:
        event = select.kevent(
            pid,
            filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
            fflags=select.KQ_NOTE_EXIT,
        )
        try:
            events = queue.control([event], 1, max(timeout, 0.0))
        except ProcessLookupError:
            return _EXITED
        except OSError:
            return _UNKNOWN
    finally:
        queue.close()
    if not events:
        return _RUNNING
    if events[0].flags & select.KQ_EV_ERROR:
        return _EXITED if events[0].data == errno.ESRCH else _UNKNOWN
    return _EXITED


def _group_state(output: str, pgid: int) -> bool | None:
    running = False
    found = False
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[0].isdigit():
            return None
        if int(parts[0]) == pgid:
            found = True
            if not parts[1][0].isalpha():
                return None
            running |= not parts[1].startswith("Z")
    return running if found else None


def _group_running(pgid: int, timeout: float) -> bool | None:
    """Whether a POSIX group still has a live member, ignoring its unreaped zombies.

    A zero signal cannot distinguish zombies from writers. The native `ps`
    reads only group ids and states, and its spawn is kept off the waiting
    thread: subprocess timeouts do not include process creation. A probe
    that cannot finish inside the remaining reap bound answers unknown.
    """
    deadline = time.monotonic() + timeout
    done, abandoned = threading.Event(), threading.Event()
    result: list[bool | None] = []

    def read() -> None:
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                ["/bin/ps", "-axo", "pgid=,stat="],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                env={"LC_ALL": "C"},
            )
            remaining = deadline - time.monotonic()
            if abandoned.is_set() or remaining <= 0:
                return
            output, _ = process.communicate(timeout=remaining)
            if process.returncode:
                return
            result.append(_group_state(output, pgid))
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            if process is not None and process.poll() is None:
                with contextlib.suppress(OSError):
                    process.kill()
                # This worker owns only the native probe, not a model group.
                # Its reap may outlast the bound; it never holds the caller.
                with contextlib.suppress(OSError):
                    process.communicate()
            if process is not None and process.stdout is not None:
                process.stdout.close()
            done.set()

    try:
        threading.Thread(target=read, daemon=True).start()
    except RuntimeError:
        return None
    if not done.wait(max(0.0, deadline - time.monotonic())):
        abandoned.set()
        return None
    return result[0] if result else None


class Group:
    """One supervised child and everything in its process group."""

    def __init__(self, process: subprocess.Popen[Any], job: int = 0) -> None:
        self._process = process
        # The Windows Job Object handle, 0 on POSIX.
        self._job = job
        # Held across every kill and across the reap, so a shutdown's or a
        # cancel's kill from another thread never lands after the leader is
        # reaped, when its id could name somebody else's group.
        self._lock = threading.Lock()
        self._reaped = False
        # A successful runner cleanup, distinct from the PID-safety marker
        # above, which can also be set on an unconfirmed group shutdown.
        self._cleanup_complete = False
        # Set by a Cancel, from any thread; the call's own wait reads it.
        self._cancelled = threading.Event()
        # The output file and its bound, and whether the bound was passed.
        self._limit: tuple[str, int] | None = None
        self._limits: tuple[tuple[str, int], ...] = ()
        self._oversized = False
        self._reap_by: float | None = None

    @property
    def pid(self) -> int:
        return self._process.pid

    def running(self) -> bool:
        """Whether the CLI still runs. Never reaps a leader it could still signal."""
        if sys.platform == "win32":
            # A handle, not a pid: polling it cannot free an id for reuse.
            return self._process.poll() is None
        with self._lock:
            if self._reaped:
                return False
            state = _state(self._process.pid, 0.0)
            if state != _UNKNOWN:
                return state == _RUNNING
            # Unwatchable: reap if it has exited, marked in the same step, so
            # no kill can follow the reap.
            if self._process.poll() is None:
                return True
            self._reaped = True
            return False

    def cleanup_complete(self) -> bool:
        """Read an owned completion fact without polling, reaping or signalling.

        False includes unknown/failed cleanup. Only run() sets this after its
        normal cleanup path returns; it says nothing about the model's output.
        """
        return self._cleanup_complete is True

    def _await_exit(self, timeout: float) -> bool:
        """For an exit `_state` cannot watch: poll, reaping and marking in one step.

        True once the leader has exited (and is reaped, so its helpers are not
        swept), False on the timeout, with the leader still unreaped for the
        kill that follows.
        """
        deadline = time.monotonic() + timeout
        while True:
            # The size before the poll, because the poll reaps: after it the
            # group can no longer be signalled (Codex P1). A helper still
            # writing after the leader's exit is not reached here at all.
            if self._over_limit() or self._cancelled.is_set():
                return False
            with self._lock:
                if self._process.poll() is not None:
                    self._reaped = True
                    return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_LIMIT_POLL_SEC if self._limit or self._limits else 0.02, remaining))

    def kill(self) -> bool:
        """Kill the group. Safe from any thread and more than once; False if it failed."""
        with self._lock:
            return self._kill() if not self._reaped else True

    def cancel(self) -> None:
        """Ask the call to end its CLI, and kill it now when that costs no wait.

        Never blocks the caller, which is a request thread. The group lock is
        held for up to `REAP_TIMEOUT_SEC` by the call's own reap, and that reap
        kills anyway; any other holder lets go within one poll, after which
        the call sees the flag and kills and reaps with its bound. So a kill
        skipped here is one the call makes itself.
        """
        self._cancelled.set()
        if self._lock.acquire(blocking=False):
            try:
                if not self._reaped:
                    self._kill()
            finally:
                self._lock.release()

    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def _poll_step(self) -> float:
        return _LIMIT_POLL_SEC if self._limit is not None or self._limits else _CANCEL_POLL_SEC

    def _over_limit(self) -> bool:
        """Whether the output file passed its bound, cancelling the call the first time.

        Through `cancel`, so the kill, the bounded reap and an unconfirmed kill
        are exactly a Cancel's; only the answer the call raises differs.
        """
        if self._oversized:
            return self._oversized
        limits = ((self._limit,) if self._limit is not None else ()) + self._limits
        for path, max_bytes in limits:
            try:
                size = os.stat(path).st_size
            except OSError:
                continue
            if size > max_bytes:
                self._oversized = True
                self.cancel()
                return True
        return False

    def _kill(self) -> bool:
        if sys.platform == "win32":
            return _windows.terminate(self._job) if self._job else True
        return kill_group(self._process.pid)

    def _finish(self) -> None:
        """Kill or sweep the group while its leader is unreaped, then reap. POSIX only.

        After a normal exit the leader is a zombie still holding the group id,
        so the sweep reaches the helpers it left behind and nothing else. After
        a timeout it is the kill itself. A killed helper can still finish a
        write, so group quiescence is observed before releasing the leader's
        identity. Observation and reap share one deadline; a failed observation
        cannot authorize a normal reply (DRC-4729).
        """
        with self._lock:
            if self._reaped:
                return
            deadline = time.monotonic() + REAP_TIMEOUT_SEC
            if _state(self._process.pid, 0.0) != _REAPED:
                self._kill()
                # Keep the leader's identity until every group writer is gone.
                # A helper can finish a write after its SIGKILL was sent.
                try:
                    self._wait_group(deadline)
                except BaseException:
                    # No signal after a reap, including on a failed observation.
                    self._reaped = True
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        self._process.wait(timeout=max(0.0, deadline - time.monotonic()))
                    raise
            self._reaped = True
            try:
                self._process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise UnstoppedError(self._process.pid) from exc
            self._cleanup_complete = True

    def _wait_group(self, deadline: float) -> None:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UnstoppedError(self.pid)
            running = _group_running(self.pid, remaining)
            if running is False:
                return
            remaining = deadline - time.monotonic()
            if running is None or remaining <= 0:
                raise UnstoppedError(self.pid)
            time.sleep(min(_LIMIT_POLL_SEC, remaining))

    def close(self) -> None:
        if sys.platform == "win32" and self._job:
            with self._lock:
                self._reaped = True
                # KILL_ON_JOB_CLOSE: closing the last handle ends any straggler.
                _windows.close(self._job)
                self._job = 0

    def _finish_windows(self) -> None:
        """End the job and wait for all its writers before the final size check."""
        if not self._job:
            return
        deadline = (
            self._reap_by if self._reap_by is not None else time.monotonic() + REAP_TIMEOUT_SEC
        )
        with self._lock:
            if not _windows.terminate(self._job):
                raise UnstoppedError(self.pid)
            while True:
                try:
                    active = _windows.active(self._job)
                except OSError as exc:
                    raise UnstoppedError(self.pid) from exc
                if active == 0:
                    self._reaped = True
                    self._cleanup_complete = True
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise UnstoppedError(self.pid)
                time.sleep(min(_LIMIT_POLL_SEC, remaining))


def live() -> frozenset[Group]:
    """The groups running now."""
    with _LOCK:
        return frozenset(_LIVE)


def closed() -> bool:
    """Whether the runner has been shut down in this process."""
    return _SHUTDOWN.is_set()


@contextlib.contextmanager
def admitting() -> Iterator[bool]:
    """Hold the lock `kill_all` takes, and yield whether the runner is still open.

    A reservation commits inside this (DRC-4712), so a shutdown lands wholly
    before the charge, which is then never made, or wholly after it, which
    is then spent: the stop's line is the reservation, as the Cancel's is.
    """
    with _LOCK:
        yield not _SHUTDOWN.is_set()


def kill_all() -> None:
    """Shut the runner and kill every running group. Daemon shutdown calls this.

    With a group of its own, a child no longer receives the Ctrl-C a foreground
    run gets, so without this it would outlive the daemon, orphaned, with
    nobody left to remove its temporary files. The runner is closed under the
    spawn lock, so a spawn in progress registers first and is killed here, and
    any spawn after is refused.
    """
    with _LOCK:
        _SHUTDOWN.set()
        groups = list(_LIVE)
    for group in groups:
        group.kill()


def _spawn(
    command: Sequence[str],
    *,
    stdin: int | None,
    stdout: int | IO[Any] | None,
    stderr: int | IO[Any] | None,
    cwd: str | None,
    env: Mapping[str, str] | None,
    text: bool,
    encoding: str | None,
) -> Group:
    options: dict[str, Any] = {
        "stdin": stdin,
        "stdout": stdout,
        "stderr": stderr,
        "cwd": cwd,
        "env": env,
        "text": text,
        "encoding": encoding,
    }
    if sys.platform == "win32":
        process = subprocess.Popen(  # noqa: S603
            command,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
                | _CREATE_SUSPENDED
            ),
            **options,
        )
        try:
            # Suspended until it is in the job: a child resumed first can start
            # a grandchild the job never contains.
            job = _windows.contain(process)
        except OSError:
            process.kill()
            process.communicate()
            raise
        return Group(process, job)
    return Group(subprocess.Popen(command, start_new_session=True, **options))  # noqa: S603


_CREATE_SUSPENDED = 0x00000004


def _feed(stream: IO[Any], data: str | bytes) -> None:
    """Write a prompt to stdin from its own thread: the pipe is smaller than 16 KiB."""
    if data:
        with contextlib.suppress(OSError, ValueError):
            stream.write(data)
    with contextlib.suppress(OSError, ValueError):
        stream.close()


def run(  # noqa: PLR0913 (subprocess.run's keywords, one each)
    command: Sequence[str],
    *,
    input: str | bytes | None = None,  # noqa: A002 (subprocess.run's name)
    cwd: str | None = None,
    stdout: int | IO[Any] | None = None,
    stderr: int | IO[Any] | None = None,
    env: Mapping[str, str] | None = None,
    text: bool = False,
    encoding: str | None = None,
    timeout: float | None = None,
    check: bool = False,
    on_spawn: Callable[[Group], None] | None = None,
    before_spawn: Callable[[], None] | None = None,
    output_limit: tuple[str, int] | None = None,
    output_limits: tuple[tuple[str, int], ...] = (),
) -> subprocess.CompletedProcess[Any]:
    """`subprocess.run`, with the CLI's whole group killed on a timeout or an error.

    Returns only after the child is reaped, so a caller's `finally` that
    removes a temporary file never races a writer that is still alive. Raises
    `ClosedError` after a shutdown, `UnstoppedError` when a killed child
    would not exit, and `OversizedError` when the file `output_limit` names
    passed its size in bytes. Additional files in `output_limits` are watched
    independently, including stderr; they never replace `output_limit`.
    `before_spawn` runs after blocking launch admission, immediately before spawn.
    It must be cheap and nonblocking: it holds the global spawn lock and must
    not acquire other locks or read external state. Raising prevents launch.
    """
    if subprocess.PIPE in (stdout, stderr):
        raise ValueError("supervise.run writes output to a file or nowhere, never a pipe")
    with _LOCK:
        if _SHUTDOWN.is_set():
            raise ClosedError("Compass is shutting down")
        if before_spawn is not None:
            before_spawn()
        group = _spawn(
            command,
            stdin=subprocess.PIPE if input is not None else None,
            stdout=stdout,
            stderr=stderr,
            cwd=cwd,
            env=env,
            text=text,
            encoding=encoding,
        )
        _LIVE.add(group)
    group._limit = output_limit  # noqa: SLF001 (set before any wait reads it)
    group._limits = output_limits  # noqa: SLF001 (set before any wait reads it)
    try:
        if sys.platform == "win32":
            try:
                returncode = _run_windows(group, input, timeout, on_spawn)
            finally:
                group._finish_windows()  # noqa: SLF001
        else:
            returncode = _run_posix(group, input, timeout, on_spawn)
        # After quiescence: a helper's last write may finish after the kill,
        # so checking between the kill and the group wait once missed it.
        # The documented poll fallback is the exception: it already reaped.
        group._over_limit()  # noqa: SLF001
    finally:
        with _LOCK:
            _LIVE.discard(group)
        group.close()
    group._cleanup_complete = True  # noqa: SLF001 - supervisor-owned post-cleanup fact
    if group._oversized:  # noqa: SLF001
        raise OversizedError(group.pid)
    if check and returncode:
        raise subprocess.CalledProcessError(returncode, command)
    return subprocess.CompletedProcess(command, returncode, None, None)


def _run_posix(
    group: Group,
    data: str | bytes | None,
    timeout: float | None,
    on_spawn: Callable[[Group], None] | None,
) -> int:
    process = group._process  # noqa: SLF001 (the one owner of the handle)
    try:
        if on_spawn is not None:
            on_spawn(group)
        if data is not None and process.stdin is not None:
            threading.Thread(target=_feed, args=(process.stdin, data), daemon=True).start()
        timed_out = _wait_posix(group, 1e9 if timeout is None else timeout)
    except BaseException:
        # The timeout, a failing `on_spawn`, or an interrupt: kill before
        # reaping, reap with a bound, then let it propagate.
        with contextlib.suppress(UnstoppedError):
            group._finish()  # noqa: SLF001
        raise
    # A cancelled call reaps here as a timeout does: kill while the leader is
    # unreaped, then wait with the bound, so a kill that failed is reported
    # unstopped within it rather than after the call's own timeout.
    group._finish()  # noqa: SLF001
    if timed_out and not group.cancelled():
        raise subprocess.TimeoutExpired(process.args, timeout or 0.0)
    return int(process.returncode)


def _wait_posix(group: Group, limit: float) -> bool:
    """Wait for the leader to exit, a Cancel, or the limit. True on the limit.

    In slices, so a Cancel whose kill did not land is seen within one. An exit
    that cannot be watched is waited on by polling, never read as an exit:
    that would kill a running CLI at once.
    """
    pid = group.pid
    deadline = time.monotonic() + limit
    while True:
        remaining = deadline - time.monotonic()
        step = min(group._poll_step(), max(remaining, 0.0))  # noqa: SLF001
        state = _state(pid, step)
        if state == _UNKNOWN:
            return not group._await_exit(max(deadline - time.monotonic(), 0.0))  # noqa: SLF001
        # The size first, so an exit inside the slice cannot hide it (Codex
        # P2): the leader is unreaped here and the group can still be killed.
        if group._over_limit() or state != _RUNNING or group.cancelled():  # noqa: SLF001
            return False
        if remaining <= step:
            return True


def _run_windows(
    group: Group,
    data: str | bytes | None,
    timeout: float | None,
    on_spawn: Callable[[Group], None] | None,
) -> int:
    process = group._process  # noqa: SLF001
    # Fed from a thread, as on POSIX, and never from `communicate`: CPython's
    # Windows `communicate` writes stdin in the calling thread before any timed
    # wait, so a CLI that never read a prompt larger than the pipe held the
    # call past its own deadline (DRC-4713). Output goes to a file or nowhere,
    # so `communicate` bought nothing else. If the kill fails, the feeder stays
    # blocked; it is a daemon thread and ends with the process.
    stdin, process.stdin = process.stdin, None
    try:
        if on_spawn is not None:
            on_spawn(group)
        if data is not None and stdin is not None:
            threading.Thread(target=_feed, args=(stdin, data), daemon=True).start()
        _wait_windows(group, timeout)
    except UnstoppedError:
        raise
    except BaseException:
        group._reap_by = time.monotonic() + REAP_TIMEOUT_SEC  # noqa: SLF001
        group.kill()
        try:
            process.wait(timeout=max(0.0, group._reap_by - time.monotonic()))  # noqa: SLF001
        except subprocess.TimeoutExpired as exc:
            raise UnstoppedError(process.pid) from exc
        raise
    return int(process.returncode)


def _wait_windows(group: Group, timeout: float | None) -> None:
    """`wait` in slices, so a Cancel is seen within one. Raises on the limit.

    Once cancelled, the step stays `_CANCEL_POLL_SEC` whatever the call's
    deadline says: a deadline that ran out inside the reap window made every
    step zero, and the loop spun on a core until the reap bound.
    """
    process = group._process  # noqa: SLF001
    deadline = None if timeout is None else time.monotonic() + timeout
    reap_by: float | None = None
    while True:
        step = group._poll_step()  # noqa: SLF001
        if deadline is not None and not group.cancelled():
            step = min(step, max(deadline - time.monotonic(), 0.0))
        try:
            process.wait(timeout=step)
        except subprocess.TimeoutExpired:
            pass
        else:
            return
        group._over_limit()  # noqa: SLF001 (cancels the call past its bound)
        if group.cancelled():
            if reap_by is None:
                reap_by = time.monotonic() + REAP_TIMEOUT_SEC
                group._reap_by = reap_by  # noqa: SLF001
                group.kill()
            elif time.monotonic() >= reap_by:
                raise UnstoppedError(process.pid)
        elif deadline is not None and time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, timeout or 0.0)


class _Windows:
    """The Job Object calls, by ctypes: the standard library has no API for them."""

    _KILL_ON_JOB_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self) -> None:
        self._kernel32: Any = None
        self._ntdll: Any = None

    def _load(self) -> tuple[Any, Any]:
        if self._kernel32 is None:
            import ctypes  # noqa: PLC0415 (Windows only)
            from ctypes import wintypes  # noqa: PLC0415

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            kernel32.SetInformationJobObject.argtypes = (
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            )
            kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
            kernel32.QueryInformationJobObject.argtypes = (
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.c_void_p,
            )
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]
            ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
            self._kernel32, self._ntdll = kernel32, ntdll
        return self._kernel32, self._ntdll

    def contain(self, process: subprocess.Popen[Any]) -> int:
        """Put a suspended child in a new kill-on-close job, then resume it."""
        import ctypes  # noqa: PLC0415 (Windows only)
        from ctypes import wintypes  # noqa: PLC0415

        kernel32, ntdll = self._load()

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = self._KILL_ON_JOB_CLOSE
        # `Popen._handle` is the process handle; Popen exposes no public one.
        handle = int(process._handle)  # type: ignore[attr-defined]  # noqa: SLF001
        if not (
            kernel32.SetInformationJobObject(
                job, self._EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
            )
            and kernel32.AssignProcessToJobObject(job, handle)
        ):
            error = ctypes.get_last_error()  # type: ignore[attr-defined]
            kernel32.CloseHandle(job)
            raise ctypes.WinError(error)  # type: ignore[attr-defined]
        if ntdll.NtResumeProcess(handle) != 0:
            kernel32.TerminateJobObject(job, 1)
            kernel32.CloseHandle(job)
            raise OSError("the supervised child could not be resumed")
        return int(job)

    def terminate(self, job: int) -> bool:
        kernel32, _ = self._load()
        return bool(kernel32.TerminateJobObject(job, 1))

    def active(self, job: int) -> int:
        """The kernel's count of job processes that have not exited yet."""
        import ctypes  # noqa: PLC0415 (Windows only)
        from ctypes import wintypes  # noqa: PLC0415

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        kernel32, _ = self._load()
        info = Accounting()
        if not kernel32.QueryInformationJobObject(
            job, 1, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
        return int(info.ActiveProcesses)

    def close(self, job: int) -> None:
        kernel32, _ = self._load()
        kernel32.CloseHandle(job)


_windows = _Windows()
