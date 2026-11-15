#!/usr/bin/env python3
"""Forward one Antigravity status-line push to a running Compass.

Antigravity is not hook-shaped. Its status line is a command the CLI runs on
every render, handing it a *state snapshot* on stdin and printing whatever it
writes back into the status bar. There is no event name, no turn boundary and no
guaranteed final call, so `event_hook.py` does not fit and this is its own
adapter.

Two destinations, shaped separately, which is the point of doing it here:

- `/api/usage` gets **only** the `quota` block. The raw payload also carries the
  account email, the transcript path and the working directory, and the quota
  tile needs none of them. Sending the whole document and letting the server
  discard it is what SECURITY.md asks not to happen.
- `/api/events/antigravity` gets a lifecycle envelope derived from
  `agent_state`, behind this run's capability.

Usage as the status-line command:

    python3 <skill-dir>/statusline_hook.py            # default port
    python3 <skill-dir>/statusline_hook.py 9999       # non-default port

It always prints a line, because a status-line command that prints nothing
blanks the user's status bar, and always exits 0.

## What the payload actually contains

Measured from real `agy` sessions rather than read off a documentation page,
across two probes recorded under `docs/captures/antigravity/`: 37 pushes from two
`agy --print` sessions, then thirteen interactive sessions driven through `tmux`
on agy 1.1.19. The top-level fields are `agent_state`, `context_window`,
`conversation_id`, `cwd`, `email`, `exceeds_200k_tokens`, `model`, `plan_tier`,
`product`, `quota`, `sandbox`, `session_id`, `terminal_width`,
`transcript_path`, `vcs`, `version` and `workspace`, and not all of them are
present every time.

Three more are `omitempty`, so they arrive only when they have something to say,
which is why the print-mode probe saw none of them and reported that as absence.
The interactive probe reached all three. `tool_confirmation_pending` carries
`true` for as long as a tool confirmation stands, beside an `agent_state` of
`tool_use`. Whether a flagged push is *keyable* was measured in one of the five
gate arms only — the one whose recorder wrote id verdicts — and there all seven
flagged pushes carried a 36-character id in both `conversation_id` and
`session_id`, each naming a real `conversations/<id>.db`. The other four arms
recorded the fields as present and nothing more, which settles nothing on its
own: that same arm carried both fields present and empty on 15 of its unflagged
pushes. `task_count` counts background tasks.
`pending_input_count` counts queued user messages and was visible for 0.6 s in
the one arm that reached it, because the queue drains as fast as it fills.

`agent_state` values observed across both probes: `authenticating`,
`initializing`, `idle`, `tool_use`, `working` and `error`.

An `ask_question` is **not** reported by any of the three. One stood 144 s with
`agent_state` at `working` and then `idle`, adding no key, in a session whose
sibling arms saw the confirmation flag on the same recorder.

`conversation_id` and `session_id` carried the same 36-character value whenever
they carried one at all, and that value was the stem of a real
`conversations/<id>.db`, which is what the Antigravity collector keys on.
`conversation_id` is preferred here because it is named for the thing the
collector keys on, with `session_id` as the fallback.

**The id is often empty, and that limits what this adapter can report.** Of 37
pushes, 14 carried no id: all four `authenticating` pushes and ten of the eleven
`idle` ones. The field is present but blank before a conversation exists. Since an
event with no id cannot be keyed to a row, this adapter reliably reports Working
and usually cannot report the return to Idle. That is not a gap to paper over: it
is exactly why the Working overlay carries a measured deadline, after which the
collector's own reading of the store decides again. A *post-turn* idle push can
still carry an id. One of the two arms ended on an `idle` render after its working
run, carrying a 36-character id that named a real `conversations/<id>.db`; the
other ended while still `working`. One arm out of two is thin enough that the
deadline stays.

## Why it dedupes

The status line fired 13 and 24 times for two short turns, mostly repeating the
same `agent_state`. Posting every push would spend the server's per-source rate
budget on saying the same thing, so the last state is remembered in a small file
under the Compass state directory and an unchanged state posts nothing. Quota is
forwarded on its own slower schedule for the same reason.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
from typing import Any

# Must match the server's accepted envelope range. See event_hook.py.
ENVELOPE_VERSION = 1

DEFAULT_PORT = 4553
MAX_PAYLOAD_BYTES = 1 << 20
HARNESS = "antigravity"

# `agent_state` to the normalized vocabulary. Only the two that assert what the
# agent is doing are mapped. `authenticating` and `initializing` are startup, not
# activity, and `error` is a settings failure rather than a session state;
# treating any of them as Working or Idle would invent a claim about the session.
#
# `tool_use` is unmapped even though its push is the one that carries
# `tool_confirmation_pending: true` and a keyable id. The obstacle is not the
# signal, it is the shape: the status line is a repeating render, so a session
# pushes `working` and `idle` many times a turn and both map to overlays that end
# a wait. An `input_requested` posted from here would be cleared by the next
# render rather than left stuck, which is the inverse of the usual hazard.
# Sending it needs a precedence rule in the overlay reducer, not a row in this
# table. Until that exists nothing reports Needs input for this harness:
# `collectors/antigravity.py` has no `needs_input` path at all and its state is
# two-valued, so this is an open gap and not a division of labour.
# Measured in `docs/captures/antigravity/statusline-confirmation-1.1.19-macos.jsonl`.
AGENT_STATES = {
    "working": "turn_started",
    "idle": "turn_stopped",
}

# How often to re-forward quota when nothing else changed. The server keeps its
# own five-minute floor per vendor; this only stops the adapter from posting the
# same numbers on every render.
QUOTA_INTERVAL_SEC = 60.0


def _shared() -> Any:
    """The transport guards from `notify_hook`, which ships beside this file."""
    with contextlib.suppress(Exception):
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import notify_hook  # noqa: PLC0415 — resolved relative to this file at runtime

        return notify_hook
    return None


def default_home() -> str:
    return os.path.join(os.path.expanduser("~"), ".compass")


def state_home() -> str:
    env = os.environ
    override = env.get("COMPASS_HOME")
    return override if override and override.strip() else default_home()


def capability(port: int) -> str | None:
    """This run's Antigravity token, or None if there is nothing to read."""
    try:
        from notify_hook import open_regular_binary  # noqa: PLC0415 - standalone hook dependency

        path = os.path.join(state_home(), f"compass-{port}.json")
        with open_regular_binary(path) as handle:
            data = json.loads(handle.read(65_536) or b"null")
    except (OSError, ValueError, RecursionError, ImportError):
        return None
    if not isinstance(data, dict):
        return None
    tokens = data.get("capabilities")
    if not isinstance(tokens, dict):
        return None
    token = tokens.get(HARNESS)
    return token if isinstance(token, str) and token else None


def conversation_id(payload: dict[str, Any]) -> str | None:
    """The id the Antigravity collector keys on.

    `conversation_id` first because it is named for the `conversations/<id>.db`
    stem the collector reads, then `session_id`, which held the same value in
    every captured push. Taking the preferred one first rather than merging them
    means a future divergence resolves to the durable id instead of whichever
    happened to be checked first.
    """
    for field in ("conversation_id", "session_id"):
        value = payload.get(field)
        if isinstance(value, str) and re.fullmatch(
            r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", value.strip()
        ):
            return value.strip()
    return None


def envelope(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The lifecycle envelope for this push, or None if it asserts nothing.

    Built field by field, so `email`, `transcript_path`, `model` and the rest stay
    out. `cwd` is carried because it is an allowlisted matching hint the server
    never echoes.
    """
    state = payload.get("agent_state")
    name = AGENT_STATES.get(state) if isinstance(state, str) else None
    if name is None:
        return None
    sid = conversation_id(payload)
    if sid is None:
        return None
    event: dict[str, Any] = {
        "v": ENVELOPE_VERSION,
        "event": name,
        "session_id": sid,
        "source_instance_id": "statusline",
    }
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        event["cwd"] = cwd.strip()
    return event


def usage_envelope(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The minimum `/api/usage` needs: the quota block, and nothing else."""
    quota = payload.get("quota")
    if not isinstance(quota, dict) or not quota:
        return None
    return {"quota": quota}


def _memo_path(sid: str) -> str:
    # One file per conversation, named from the id the server already knows, so
    # nothing new about the user is written anywhere.
    return os.path.join(state_home(), f"statusline-{HARNESS}-{sid}.json")


def read_memo(sid: str) -> dict[str, Any]:
    if conversation_id({"session_id": sid}) != sid:
        return {}
    with contextlib.suppress(OSError, ValueError, RecursionError, ImportError):
        from notify_hook import open_regular_binary  # noqa: PLC0415 - standalone hook dependency

        with open_regular_binary(_memo_path(sid)) as handle:
            memo = json.loads(handle.read(4096) or b"{}")
        if isinstance(memo, dict):
            return memo
    return {}


def write_memo(sid: str, memo: dict[str, Any]) -> None:
    """Best effort. A memo that cannot be written costs a duplicate post."""
    if conversation_id({"session_id": sid}) != sid:
        return
    with contextlib.suppress(OSError, TypeError, ValueError, ImportError):
        from notify_hook import write_owner_json  # noqa: PLC0415 - standalone hook dependency

        write_owner_json(_memo_path(sid), memo)


def decide(
    payload: dict[str, Any], memo: dict[str, Any], *, now: float
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """What is worth posting this time. Returned rather than posted, so the
    deduplication rule is testable without a socket.

    The event goes only when `agent_state` changed; quota goes on its own
    interval, because it changes on its own schedule and not with the state.
    """
    event = envelope(payload)
    if event is not None and memo.get("event") == event["event"]:
        event = None
    usage = usage_envelope(payload)
    if usage is not None and now - float(memo.get("quota_at") or 0) < QUOTA_INTERVAL_SEC:
        usage = None
    return event, usage


def commit(
    memo: dict[str, Any],
    *,
    event: dict[str, Any] | None = None,
    quota_at: float | None = None,
) -> dict[str, Any]:
    """The next memo, recording only what was actually delivered.

    Separate from `decide` because the two are not the same question, and
    conflating them was a real bug. An event that was worth sending but could not
    be sent, because no dashboard had published a capability yet, must not be
    recorded as sent: the next push would dedupe against it and the row would sit
    without its overlay until the state happened to change again.
    """
    keep = dict(memo)
    if event is not None:
        keep["event"] = event["event"]
    if quota_at is not None:
        keep["quota_at"] = quota_at
    return keep


def main(argv: list[str]) -> int:
    port = DEFAULT_PORT
    if len(argv) > 1:
        with contextlib.suppress(ValueError):
            port = int(argv[1])
    payload: Any = {}
    try:
        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES)
        payload = json.loads(raw or b"{}")
    except (OSError, ValueError, AttributeError, RecursionError):
        payload = {}
    if isinstance(payload, dict):
        with contextlib.suppress(Exception):
            _push(payload, port)
    # The status bar renders whatever this prints, so it always prints. A bare
    # newline rather than a status string: Compass's job is the dashboard, and
    # taking over the user's status bar would be presumptuous.
    print()
    return 0


def _push(payload: dict[str, Any], port: int) -> None:
    sid = conversation_id(payload)
    if sid is None:
        return
    memo = read_memo(sid)
    now = time.time()
    event, usage = decide(payload, memo, now=now)
    if event is None and usage is None:
        return
    shared = _shared()
    if shared is None:
        return
    base = f"http://127.0.0.1:{port}"
    delivered_quota_at: float | None = None
    delivered_event: dict[str, Any] | None = None
    if usage is not None:
        # Unauthenticated, exactly as it is today: this endpoint stores a quota
        # figure and nothing else, and its exposure is already documented. Sent
        # before the capability is even looked up, so a dashboard that publishes
        # none, or one run with --no-events, keeps the quota band it already had.
        shared.forward(f"{base}/api/usage", json.dumps(usage, separators=(",", ":")).encode())
        delivered_quota_at = now
    if event is not None:
        token = capability(port)
        if token is not None:
            shared.forward(
                f"{base}/api/events/{HARNESS}",
                json.dumps(event, separators=(",", ":")).encode(),
                headers={"X-Compass-Capability": token},
            )
            delivered_event = event
    write_memo(sid, commit(memo, event=delivered_event, quota_at=delivered_quota_at))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
