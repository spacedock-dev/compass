"""Synthetic values in the committed Codex capture shapes; no live store reads."""

from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import mark_abstention as marker  # noqa: E402

marker._reading()

from compass_runtime import config as runtime_config  # noqa: E402

SID = "00000000-0000-4000-8000-000000000001"
CHILD = "00000000-0000-4000-8000-000000000002"
AT = 1794000000.0


def stamp(delta: float) -> str:
    return datetime.fromtimestamp(AT + delta, UTC).isoformat()


def config(home: Path) -> Any:
    return runtime_config.build_runtime_config(
        environ={
            "HOME": str(home),
            "COMPASS_HOME": str(home / "packet"),
            "CODEX_HOME": str(home / "codex"),
        },
        platform_name=sys.platform,
        os_name="posix",
        launcher_path=ROOT / "compass/skills/compass/server.py",
    )


def message(
    text: str = "Please repair the example and verify it.", *, tagged: bool = True, delta: float = 1
) -> dict[str, Any]:
    capture = ROOT / "docs/captures/codex/skill-action-shapes-0.167.0-macos.jsonl"
    shape = next(
        json.loads(line)["record"]
        for line in capture.read_text().splitlines()
        if '"provenance": {"type": "user"}' in line
    )
    row = copy.deepcopy(shape)
    row["timestamp"] = stamp(delta)
    row["ordinal"] = 1
    row["payload"].update(id=f"person-{delta}", content=[{"type": "input_text", "text": text}])
    row.pop("metadata", None)
    if not tagged:
        row["payload"].pop("internal_chat_message_metadata_passthrough", None)
    return cast("dict[str, Any]", row)


def event(kind: str, delta: float, **fields: Any) -> dict[str, Any]:
    return {
        "timestamp": stamp(delta),
        "type": "event_msg",
        "payload": {"type": kind, "turn_id": "turn-a", **fields},
    }


def command(delta: float, code: int = 0, command_text: str = "python3 -m pytest") -> dict[str, Any]:
    capture = ROOT / "docs/captures/codex/tool-calls-0.149-0.164-macos.jsonl"
    shape = next(
        json.loads(line)
        for line in capture.read_text().splitlines()
        if '"shape": "CommandExecution"' in line
    )
    item: dict[str, Any] = dict.fromkeys(shape["item"], "")
    item.update(
        type="CommandExecution",
        id=f"check-{delta}",
        command=["/bin/bash", "-lc", command_text],
        cwd="file:///synthetic/project",
        exit_code=code,
        status="completed" if code == 0 else "failed",
        aggregated_output="one synthetic check",
        duration={"secs": 0, "nanos": 0},
    )
    return event(
        "item_completed",
        delta,
        item=item,
        thread_id=SID,
        started_at_ms=int((AT + delta - 0.1) * 1000),
        completed_at_ms=int((AT + delta) * 1000),
    )


def rollout(
    folder: Path,
    *,
    sid: str = SID,
    parent: str = "",
    tagged: bool = True,
    session: str | None = None,
) -> Path:
    """A synthetic rollout. A child records its chain root as `session_id`, as every one of the
    owner's 697 subagent rollouts did when measured (metadata only, 2026-11-09); a root records its
    own id."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-2026-11-07T00-00-00-{sid}.jsonl"
    rows = [
        {
            "timestamp": stamp(0),
            "type": "session_meta",
            "payload": {
                "id": sid,
                "session_id": (session or SID) if parent else sid,
                "cli_version": "0.167.0",
                "cwd": "/synthetic/project",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent}}}
                if parent
                else "cli",
            },
        },
        event("task_started", 0.5),
        message(tagged=tagged),
        command(3, 1),
        command(4),
        {
            "timestamp": stamp(5),
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "answer-a",
                "role": "assistant",
                "phase": "final_answer",
                "content": [
                    {"type": "output_text", "text": "The example is repaired; the check passed."}
                ],
            },
        },
        event("task_complete", 6),
    ]
    write(path, rows)
    return path


def write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def entry(root: Path, path: Path) -> dict[str, Any]:
    return {
        "harness": "codex",
        "sid": SID,
        "sessions_root": str(root),
        "transcript": str(path),
        "children": [],
        "captured_at": AT + 20,
        "intent": {
            "n": 3,
            "at": AT + 1,
            "goal": "Repair the example",
            "lines": ["The example passes its check."],
        },
        "row": {"state": "idle", "turn_end_at": AT + 6},
    }
