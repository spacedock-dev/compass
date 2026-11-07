"""A detached terminal holder for one session's dashboard lease; never a model caller."""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from compass_runtime import monitor_store, terminal_sessions
from compass_runtime import terminal_client as client

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

BEAT_SEC = 20.0
PROCESS_CHECK_SEC = 5.0
FAILURE_SEC = 30.0
IDLE_SEC = 7200.0
READY_SEC = 12.0
SIDECAR_FLAG = "--monitor-sidecar"


def process_identity(pid: int) -> tuple[int, str, str] | None:
    if os.name == "nt":
        return None
    try:
        result = subprocess.run(  # noqa: S603
            ["/bin/ps", "-ww", "-o", "ppid=,lstart=,comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
        parts = result.stdout.strip().split()
        if result.returncode or len(parts) < 7:
            return None
        # On macOS comm is truncated when followed by another column, even with -ww.
        # Keep it last so an installed executable's full path survives.
        return int(parts[0]), " ".join(parts[6:]), " ".join(parts[1:6])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def ancestor() -> dict[str, Any]:
    pid = os.getppid()
    seen: set[int] = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        identity = process_identity(pid)
        if identity is None:
            break
        parent, executable, started = identity
        if Path(executable).name == "claude":
            return {"pid": pid, "started": started}
        pid = parent
    return {}


def ancestor_alive(record: Mapping[str, Any]) -> bool:
    if not record:
        return True
    identity = process_identity(int(record["pid"]))
    return identity is not None and identity[2] == record.get("started")


def spawn(sid: str, generation: str) -> subprocess.Popen[bytes]:
    root = Path(__file__).resolve().parents[1]
    argv = (
        [sys.executable]
        if getattr(sys, "frozen", False)
        else [sys.executable, str(root / "launch.py"), str(root / "server.py")]
    )
    argv += [SIDECAR_FLAG, sid, generation]
    flags: dict[str, Any]
    if sys.platform == "win32":
        flags = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        flags = {"start_new_session": True}
    return subprocess.Popen(  # noqa: S603 — this installation's entry point, no shell
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **flags,
    )


def _say(reason: str, *, failed: bool = False) -> int:
    print(client.sentence("monitor_" + reason), file=sys.stderr if failed else sys.stdout)
    return int(failed)


def _report_start(answer: Mapping[str, Any], *, repeat: bool = False) -> int:
    if answer.get("ok") is not True:
        reason = answer.get("reason")
        return _say(
            str(reason) if reason in {"paused", "no-observer-model", "ended"} else "refused",
            failed=True,
        )
    receipt = answer.get("terminal") or {}
    if receipt.get("notice_due") and receipt.get("disclosure"):
        print(terminal_sessions.printable(receipt["disclosure"]))
    _say(
        "missing"
        if receipt.get("goal_status") == "missing"
        else "already_running"
        if repeat
        else "started"
    )
    goal = receipt.get("goal")
    if receipt.get("goal_status") == "adopted" and isinstance(goal, dict):
        source = {
            "first-prompt": "your first prompt",
            "latest-prompt": "your latest prompt",
            "session-goal": "your /goal",
        }.get(str(goal.get("source")), "your prompt")
        at = goal.get("at")
        if goal.get("source") == "session-goal" and isinstance(at, int | float) and at > 0:
            source += " at " + time.strftime("%H:%M", time.localtime(at))
        print(f"From {source} · saved")
        print(terminal_sessions.printable(goal.get("text", "")))
    if receipt.get("goal_status") in {"missing", "adopted"}:
        print(
            "Change the goal on the session page: "
            + terminal_sessions.printable(receipt.get("page_url", ""))
        )
    return 0


def _start_receipt(reply: client.Reply) -> dict[str, Any]:
    """Keep readiness readable within Store's 8 KiB bound, even for escaped Unicode goals."""
    data = reply.data if isinstance(reply.data, dict) else {}
    answer = {name: data[name] for name in ("ok", "reason", "terminal") if name in data}
    answer = json.loads(json.dumps(answer))
    terminal = answer.get("terminal")
    if isinstance(terminal, dict):
        goal = terminal.get("goal")
        if isinstance(goal, dict):
            while len(json.dumps(answer)) > 7400 and goal.get("text"):
                goal["text"] = goal["text"][: max(0, len(goal["text"]) - 100)]
            if goal.get("text") != data.get("terminal", {}).get("goal", {}).get("text"):
                goal["text"] += "…"
    return answer if len(json.dumps(answer)) <= 7500 else {"ok": False, "reason": "unreadable"}


def command(named: client.Session, *, off: bool, home: str, in_session: bool) -> int:
    try:
        store = monitor_store.Store(home, named.sid)
        with store.lock("command") as held:
            if not held:
                # A competing command owns admission until readiness, rather than merely until
                # Popen returns. Waiting here costs no dashboard request and no second worker.
                until = time.monotonic() + READY_SEC + 2
                while time.monotonic() < until:
                    time.sleep(0.05)
                    with store.lock("command") as retry:
                        if retry:
                            return _command(store, named, off=off, in_session=in_session)
                return _say("busy", failed=True)
            return _command(store, named, off=off, in_session=in_session)
    except (OSError, ValueError):
        return _say("failed", failed=True)


def _command(
    store: monitor_store.Store, named: client.Session, *, off: bool, in_session: bool
) -> int:
    if store.running():
        record = store.read("run")
        if not terminal_sessions.names(record, named.sid):
            return _say("unavailable", failed=True)
        if not off:
            try:
                query = urlencode(
                    {"project": record.get("project", ""), "session": "claude:" + record["sid"]}
                )
                reply = client.get(record["dashboard"][0], "/api/project-context?" + query)
                board = reply.data["sources"]["work"]["live_monitor"]
                receipt = {"notice_due": board["notice_due"], "disclosure": board["disclosure"]}
                return _report_start({"ok": True, "terminal": receipt}, repeat=True)
            except (client.DashboardUnreachable, KeyError, TypeError):
                return _say("unreadable", failed=True)
        generation = record.get("generation")
        store.write("stop", {"generation": generation})
        until = time.monotonic() + READY_SEC
        while store.running() and time.monotonic() < until:
            time.sleep(0.05)
        return _say("failed", failed=True) if store.running() else _say("stopped")
    if off:
        record = store.read("run")
        if terminal_sessions.names(record, named.sid):
            store.write("stop", {"generation": record.get("generation")})
        return _say("not_running")
    return _start(store, named, in_session=in_session)


def _start(store: monitor_store.Store, named: client.Session, *, in_session: bool) -> int:
    found = client.ensure_dashboard(
        str(store.root.parent),
        port=None,
        spend=True,
        own_version=client.release_version(),
        in_session=in_session,
        say=lambda _message: None,
    )
    if isinstance(found, client.Refusal):
        print(found.message, file=sys.stderr)
        return found.code
    try:
        query = urlencode({"harness": named.harness, "sid": named.sid})
        reply = client.get(found.port, "/api/session?" + query)
    except client.DashboardUnreachable:
        return _say("unreadable", failed=True)
    payload = reply.data
    if (reply.status, payload) in (
        (404, {"reason": "not-found"}),
        (409, {"reason": "ambiguous"}),
    ):
        return _say("unavailable", failed=True)
    row = payload.get("session") if isinstance(payload, dict) else None
    if (
        reply.status != 200
        or not isinstance(row, dict)
        or row.get("harness") != named.harness
        or not isinstance(row.get("sid"), str)
        or not terminal_sessions.names(row, named.sid)
    ):
        return _say("unreadable", failed=True)
    if row.get("ended_at"):
        return _say("ended", failed=True)
    generation = uuid.uuid4().hex
    store.write(
        "run",
        {
            "generation": generation,
            "sid": row["sid"],
            "resume_id": row.get("resume_id"),
            "project": row.get("project", ""),
            "dashboard": list(found),
            "typed": in_session,
            "ancestor": (
                ancestor()
                if terminal_sessions.names(row, os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
                else {}
            ),
        },
    )
    return _await_start(store, named.sid, generation)


def _await_start(  # noqa: C901 — readiness and cleanup share ownership of the Popen child
    store: monitor_store.Store, sid: str, generation: str
) -> int:
    worker = spawn(sid, generation)
    until = time.monotonic() + READY_SEC
    ready = False
    try:
        while time.monotonic() < until:
            status = store.read("status")
            if status.get("generation") == generation:
                if isinstance(status.get("answer"), dict) and status["answer"]:
                    ready = status["answer"].get("ok") is True
                    if ready:
                        threading.Thread(target=worker.wait, daemon=True).start()
                    return _report_start(status["answer"])
                if status.get("reason") == "started":
                    ready = True
                    # Keep Popen owned until exit so it is reaped without a ResourceWarning.
                    threading.Thread(target=worker.wait, daemon=True).start()
                    return _say("started")
                if status.get("reason"):
                    reason = "failed" if status["reason"] == "unreachable" else "refused"
                    return _say(reason, failed=True)
            if worker.poll() is not None:
                break
            time.sleep(0.05)
        return _say("failed", failed=True)
    finally:
        if not ready:
            store.write("stop", {"generation": generation})
            # This is our Popen child, never a PID read from a stale file.
            with contextlib.suppress(subprocess.TimeoutExpired):
                worker.wait(timeout=6)
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=6)


def hold(  # noqa: C901, PLR0911, PLR0912, PLR0913 — one bounded holder state machine
    dashboard: client.Dashboard,
    sid: str,
    generation: str,
    *,
    clock: Callable[[], float] = time.monotonic,
    wait: Callable[[float], bool],
    stopped: Callable[[], bool],
    alive: Callable[[], bool],
    post: Callable[..., client.Reply] = client.post,
    probe: Callable[..., client.Dashboard | None] = client.probe,
) -> str:
    failed_at: float | None = None
    activity_at = clock()
    activity: object = None
    due = clock()
    process_due = due
    while True:
        if stopped():
            return "stopped"
        now = clock()
        if now >= process_due:
            if not alive():
                return "session-gone"
            process_due = now + PROCESS_CHECK_SEC
        if now - activity_at >= IDLE_SEC:
            return "idle"
        if now >= due:
            if failed_at is None:
                failed_at = now
            remaining = FAILURE_SEC - (now - failed_at)
            if remaining <= 0:
                return "unreachable"
            found = probe(dashboard.port, timeout=min(0.3, remaining))
            if found is not None and found[1:3] != dashboard[1:3]:
                return "restarted"
            try:
                reply = (
                    post(
                        dashboard.port,
                        "/api/live-monitor",
                        {
                            "action": "beat",
                            "harness": "claude",
                            "sid": sid,
                            "tab_id": generation,
                            "visible": True,
                        },
                        timeout=min(5.0, max(0.001, FAILURE_SEC - (clock() - failed_at))),
                    )
                    if found is not None
                    else None
                )
            except client.DashboardUnreachable:
                reply = None
            if reply is not None:
                data = reply.data
                if not isinstance(data, dict) or not isinstance(data.get("state"), dict):
                    return "refused"
                if data.get("ok") is not True or data["state"].get("on") is not True:
                    end = data["state"].get("last_end")
                    return str(end.get("reason", "ended")) if isinstance(end, dict) else "ended"
                last_ok = clock()
                failed_at = None
                if data.get("activity") != activity:
                    activity, activity_at = data.get("activity"), last_ok
                due = last_ok + BEAT_SEC
            else:
                due = clock() + 1
        if wait(min(0.5, max(0.0, due - clock()))):
            return "stopped"


def _accepted(reply: client.Reply) -> bool:
    return reply.status == 200 and isinstance(reply.data, dict) and reply.data.get("ok") is True


def sidecar(sid: str, generation: str) -> int:
    if re.fullmatch(r"[0-9a-f]{32}", generation) is None:
        return 2
    store = monitor_store.Store(client.state_home(os.environ), sid)
    stopping = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stopping.set())
    if os.name != "nt":
        signal.signal(signal.SIGHUP, lambda *_args: stopping.set())
    with store.lock("life") as held:
        record = store.read("run")
        if not held or record.get("generation") != generation:
            return 1
        dashboard = client.Dashboard(*record["dashboard"])
        payload = {
            "action": "start",
            "harness": "claude",
            "sid": record["sid"],
            "tab_id": generation,
            "holder_kind": "terminal",
            "observer_model": 1,
        }
        if record.get("typed"):
            payload["typed_action"] = "monitor on"
        reason = "refused"
        started = False
        receipt: dict[str, Any] = {}
        try:
            if stopping.is_set() or store.read("stop").get("generation") == generation:
                return 0
            answer = client.post(dashboard.port, "/api/live-monitor", payload)
            receipt = _start_receipt(answer)
            if not _accepted(answer):
                return 1
            started = True
            store.write(
                "status", {"generation": generation, "reason": "started", "answer": receipt}
            )
            reason = hold(
                dashboard,
                record["sid"],
                generation,
                wait=stopping.wait,
                stopped=lambda: (
                    stopping.is_set() or store.read("stop").get("generation") == generation
                ),
                alive=lambda: ancestor_alive(record.get("ancestor", {})),
            )
        except (OSError, ValueError, KeyError):
            reason = "unreachable"
            return 1
        else:
            return 0
        finally:
            _stop_holder(dashboard, record["sid"], generation)
            store.write(
                "status",
                {
                    "generation": generation,
                    "reason": reason,
                    "at": time.time(),
                    "started": started,
                    "answer": receipt,
                },
            )


def _stop_holder(dashboard: client.Dashboard, sid: str, generation: str) -> None:
    # An unanswered start may have been accepted. Stop that holder too. A restarted
    # dashboard must receive no stop aimed at a different generation of the server.
    current = client.probe(dashboard.port)
    if current is not None and current[1:3] == dashboard[1:3]:
        with contextlib.suppress(client.DashboardUnreachable):
            client.post(
                dashboard.port,
                "/api/live-monitor",
                {
                    "action": "stop",
                    "harness": "claude",
                    "sid": sid,
                    "tab_id": generation,
                },
                timeout=2,
            )
