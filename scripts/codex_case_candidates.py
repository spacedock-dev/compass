#!/usr/bin/env python3
"""Private, metadata-only Codex candidate inventory. No provider or dashboard calls.

An explicit source root is required; nothing reads the account's stores by default.
Only hashes, dates, counts and closed labels can leave the inventory function.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 10000
REPOSITORY = Path(__file__).resolve().parents[1]


def outside_repository(path: Path) -> bool:
    """Reject the checkout, linked worktrees, symlink escapes and Git internals."""
    resolved = path.resolve()
    return not any(
        (parent / ".git").exists() for parent in (resolved, *resolved.parents)
    ) and not resolved.is_relative_to(REPOSITORY)


def summarize_shape(path: Path) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - closed metadata vocabulary, one arm per native shape
    """No untrusted text field is copied, even when it looks like a short enum."""
    row: dict[str, Any] = dict(  # noqa: C408 - readable counter field inventory
        alias=hashlib.sha256(path.name.encode()).hexdigest(),
        date="",
        bytes=0,
        source="other",
        child=False,
        human=0,
        injected=0,
        untagged=0,
        turns=0,
        completed=0,
        aborted=0,
        cmds=0,
        failed=0,
        fail_then_pass=False,
        edits=0,
        bad_lines=0,
        bounded=True,
        head_bytes=0,
        head_is_session_meta=False,
    )
    date = re.search(r"rollout-(\d{4}-\d{2}-\d{2})", path.name)
    if date:
        row["date"] = date[1]
    seen_failure = False
    if path.is_symlink():
        row["bad_lines"] = -1
        row["bounded"] = False
        return row
    try:
        row["bytes"] = path.stat().st_size
        used = 0
        with path.open("rb") as handle:
            while raw := handle.readline(MAX_BYTES - used + 1):
                first = used == 0
                if first:
                    row["head_bytes"] = len(raw)
                used += len(raw)
                if used > MAX_BYTES:
                    row["bounded"] = False
                    break
                try:
                    record = json.loads(raw)
                except (ValueError, RecursionError):
                    row["bad_lines"] += 1
                    continue
                if not isinstance(record, dict):
                    row["bad_lines"] += 1
                    continue
                if first:
                    row["head_is_session_meta"] = record.get("type") == "session_meta"
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                kind = payload.get("type")
                if record.get("type") == "session_meta":
                    source = payload.get("source")
                    row["child"] = isinstance(source, dict) or bool(payload.get("parent_thread_id"))
                    row["source"] = (
                        source
                        if isinstance(source, str) and source in {"cli", "exec", "vscode"}
                        else ("subagent" if row["child"] else "other")
                    )
                elif (
                    record.get("type") == "response_item"
                    and kind == "message"
                    and payload.get("role") == "user"
                ):
                    metadata = payload.get("internal_chat_message_metadata_passthrough")
                    items = (
                        metadata.get("content_item_metadata")
                        if isinstance(metadata, dict)
                        else None
                    )
                    if (
                        isinstance(items, list)
                        and items
                        and all(
                            isinstance(item, dict)
                            and isinstance(item.get("provenance"), dict)
                            and item["provenance"].get("type") == "user"
                            for item in items
                        )
                    ):
                        row["human"] += 1
                    elif items is None:
                        row["untagged"] += 1
                    else:
                        row["injected"] += 1
                elif record.get("type") == "event_msg":
                    counter = {
                        "task_started": "turns",
                        "task_complete": "completed",
                        "turn_aborted": "aborted",
                    }.get(str(kind))
                    if counter:
                        row[counter] += 1
                    item = (
                        payload.get("item")
                        if kind == "item_completed"
                        else payload
                        if kind == "exec_command_end"
                        else None
                    )
                    if isinstance(item, dict):
                        if item.get("type") == "CommandExecution" or kind == "exec_command_end":
                            row["cmds"] += 1
                            code = item.get("exit_code")
                            if type(code) is int and code != 0:
                                row["failed"] += 1
                                seen_failure = True
                            elif type(code) is int and code == 0 and seen_failure:
                                row["fail_then_pass"] = True
                        elif item.get("type") in {"FileChange", "PatchApply"}:
                            row["edits"] += 1
    except (OSError, ValueError):
        row["bad_lines"] = -1
        row["bounded"] = False
    return row


def inventory(root: Path, *, output: Path | None = None) -> list[dict[str, Any]]:
    """Explicit metadata permission does not admit any rollout as a recorded case."""
    if output is not None and not outside_repository(output):
        raise ValueError("output-must-be-outside-repository")
    paths = sorted(root.rglob("rollout-*.jsonl"))
    if len(paths) > MAX_FILES:
        raise ValueError("inventory-file-limit")
    rows = [summarize_shape(path) for path in paths]
    if output is not None:
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rows = inventory(args.root, output=args.output)
    except (OSError, ValueError, TypeError):
        print("inventory-source-unconfirmed: check the private source and output selection.")
        return 1
    print(
        f"Inventoried {len(rows)} rollouts; "
        f"{sum(bool(row['child']) for row in rows)} children. Private metadata only."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
