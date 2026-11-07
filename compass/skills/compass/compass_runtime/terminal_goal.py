"""The fresh Intent card's goal, and model-free writes through its existing route."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from compass_runtime import terminal_drift
from compass_runtime.terminal_sessions import names, printable

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TextIO

    from compass_runtime.terminal_client import GoalRequest, Session


class Board(Protocol):
    port: int

    def session(self, harness: str, sid: str) -> Any: ...
    def post(self, path: str, body: Mapping[str, Any]) -> tuple[int, Any]: ...


def render(payload: Mapping[str, Any], *, port: int) -> list[str]:
    row = payload["session"]
    lines = ["Goal: " + (terminal_drift.goal_text(row, payload) or "No goal offered.")]
    source = terminal_drift.goal_source_line(row, payload)
    if source:
        lines.append(source)
    revision = row.get("annotation_revision")
    lines.append(f"Saved revision: {revision}" if type(revision) is int else "No saved revision.")
    outcomes = [row.get(f"annotation_line_{n}") for n in range(1, 7)]
    lines.extend(
        f"Outcome {n}: {text}"
        for n, text in enumerate(outcomes, 1)
        if isinstance(text, str) and text.strip()
    )
    if not any(isinstance(text, str) and text.strip() for text in outcomes):
        lines.append("No expected outcome lines saved.")
    lines.extend(
        note
        for note in (payload.get("annotate_unreadable"), row.get("annotation_binding_why"))
        if isinstance(note, str) and note
    )
    if payload.get("annotate") is not True:
        lines.append("Saving intent is unavailable on this dashboard.")
    lines.append(
        terminal_drift.session_url(port, str(row.get("project") or ""), row["harness"], row["sid"])
    )
    return lines


def _snapshot(board: Board, named: Session) -> dict[str, Any] | None:
    payload = board.session(named.harness, named.sid)
    if not isinstance(payload, dict):
        return None
    row = payload.get("session")
    if (
        not isinstance(row, dict)
        or row.get("harness") != named.harness
        or not isinstance(row.get("sid"), str)
    ):
        return None
    return payload if names(row, named.sid) else None


def _body(request: GoalRequest, payload: Mapping[str, Any]) -> dict[str, Any] | str:
    row = payload["session"]
    if payload.get("annotate") is not True or payload.get("annotate_unreadable"):
        return "Goal not saved: saving intent is unavailable or its store is unreadable."
    revision = row.get("annotation_revision")
    if revision is not None and (type(revision) is not int or revision < 0):
        return "Goal not saved: the saved revision could not be read."
    body = {"harness": row["harness"], "sid": row["sid"], "expected_revision": revision or 0}
    if request.adopt:
        candidate = terminal_drift.session_goal_candidate(row) or terminal_drift.draft(row, payload)
        if candidate is None:
            return "No goal candidate is offered to adopt."
        body.update(
            adopt=candidate.source, expected_prompt=candidate.text, expected_prompt_at=candidate.at
        )
        if not revision:
            # Revision zero also names a discard. Keep a board discard that follows
            # this read; the page can still deliberately adopt after discarding.
            body["empty_intent_only"] = True
    else:
        text = "" if request.clear else request.text
        cap = payload.get("annotate_goal_cap")
        if type(cap) is not int or cap <= 0:
            return "Goal not saved: the goal limit could not be read."
        if text is None or len(text) > cap:
            return f"Goal not saved: use at most {cap:,} characters."
        body["goal"] = text
    return body


def run(request: GoalRequest, *, named: Session, board: Board, out: TextIO, err: TextIO) -> int:
    try:
        payload = _snapshot(board, named)
        if payload is None:
            print(
                "This session could not be read unambiguously; open its page and try again.",
                file=err,
            )
            return 1
        notices: list[str] = []
        if request.writes:
            body = _body(request, payload)
            if isinstance(body, str):
                print(body, file=err)
                return 1
            status, answer = board.post("/api/annotate", body)
            if (
                status != 200
                or not isinstance(answer, dict)
                or answer.get("ok") is not True
                or answer.get("persisted") is not True
                or answer.get("outcome") not in ("stored", "unchanged")
                or type(answer.get("saved_revision")) is not int
            ):
                reason = (
                    "Goal not saved: the goal was discarded on the board meanwhile."
                    if request.adopt and isinstance(answer, dict) and answer.get("discarded")
                    else "Goal not saved: the source or revision changed, "
                    "or the store could not save it. Read again before retrying."
                )
                print(reason, file=err)
                return 1
            saved = answer["saved_revision"]
            notices.append(
                f"Goal already saved as revision {saved}."
                if answer["outcome"] == "unchanged"
                else f"Saved goal as revision {saved}."
            )
            payload = _snapshot(board, named)
            if payload is None:
                print(
                    f"Goal saved as revision {saved}, but the current goal could not be read. "
                    "Open its page.",
                    file=err,
                )
                return 1
            if payload["session"].get("annotation_revision") != saved:
                notices.append("Another save followed this one; the current goal is shown below.")
            elif request.clear:
                notices.append(
                    "The saved goal is empty. A draft is now offered."
                    if terminal_drift.draft(payload["session"], payload) is not None
                    else "The saved goal is empty."
                )
        text = "".join(
            f"{printable(line)}\n" for line in [*notices, *render(payload, port=board.port)]
        )
        encoding = getattr(out, "encoding", None) or "utf-8"
        out.write(text.encode(encoding, "replace").decode(encoding, "replace"))
    except terminal_drift.Lost:
        print(
            "Compass did not confirm the goal request. Read again before retrying a save.", file=err
        )
        return 1
    return 0
