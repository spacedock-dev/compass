#!/usr/bin/env python3
"""Measure how much of a session's work Compass can read, over Claude Code transcripts.

Each transcript goes through the runtime's own parser and tally, so the figures are what the board
would have had to work with, not a second reading of the files. The report holds counts and command
heads only: no argument, no output line and no path ever reaches it. A head is the command word, or
the command word and its subcommand when the tool is on a closed list and the second word is one of
that tool's own subcommands; any other second word is an argument and is dropped.

Two bases differ. Session counts (Bash, check, CI poll) read the whole parent transcript. Check-run
counts are what the board reads inside its scan budget, the newest `turn_scan_max_bytes` shared with
the subagent transcripts beside the parent, so subagent runs are in the tally and not in the session
counts.

Default corpus: `$COMPASS_HOME/drift-replay/` (`~/.compass/drift-replay/` when unset). `--dir`
points elsewhere, for example `~/.claude/projects`; `--days N` keeps transcripts modified in
the last N days; `--json` prints the report as JSON.

Read-only: nothing is written, and subagent transcripts are not counted as sessions (the tally
reads them from beside their parent).
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import pathlib
import re
import sys
import time
from typing import TYPE_CHECKING, Any

import store_paths

if TYPE_CHECKING:
    from collections.abc import Iterable

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SKILL = str(_ROOT / "compass" / "skills" / "compass")

SUBDIR = "drift-replay"
TOP_HEADS = 25
LABEL_WIDTH = 36

_SHELL_WRAPPERS = frozenset({"rtk"})


def _polls_ci(words: list[str]) -> bool:
    """`gh pr checks`, `gh run view|watch|list`, `gh pr view ... statusCheckRollup`, `glab ci`.

    Read from a parsed command's own words, so a commit message or an `echo` argument that names
    one is not a poll.
    """
    while words and words[0] in _SHELL_WRAPPERS:
        words = words[1:]
    if words[:1] == ["glab"]:
        return words[1:2] == ["ci"]
    if words[:1] != ["gh"]:
        return False
    return (
        words[1:3] == ["pr", "checks"]
        or (words[1:2] == ["run"] and words[2:3] in (["view"], ["watch"], ["list"]))
        or (words[1:3] == ["pr", "view"] and "statusCheckRollup" in words)
    )


# Tools whose second word is a subcommand, and the subcommands each one may name. A second word not
# on its tool's list is an argument and never reaches the report: `psql hunter2db` stays `psql`.
# `make` and `just` take targets and the interpreters take scripts, so they report the first word.
SUBCOMMANDS: dict[str, frozenset[str]] = {
    "gh": frozenset(["pr", "run", "api", "issue", "repo", "workflow", "release", "auth"]),
    "git": frozenset(
        [
            "status",
            "diff",
            "log",
            "commit",
            "push",
            "pull",
            "checkout",
            "branch",
            "merge",
            "rebase",
            "fetch",
            "add",
            "stash",
            "worktree",
            "show",
            "reset",
            "tag",
            "remote",
        ]
    ),
    "glab": frozenset(["ci", "mr", "api", "issue"]),
    "npm": frozenset(
        ["install", "run", "test", "build", "lint", "exec", "ci", "add", "publish", "typecheck"]
    ),
    "pnpm": frozenset(
        [
            "install",
            "run",
            "test",
            "build",
            "lint",
            "exec",
            "dlx",
            "ci",
            "add",
            "publish",
            "typecheck",
        ]
    ),
    "yarn": frozenset(
        ["install", "run", "test", "build", "lint", "exec", "dlx", "add", "publish", "typecheck"]
    ),
    "uv": frozenset(["run", "sync", "pip", "add", "lock"]),
    "cargo": frozenset(
        ["build", "test", "run", "check", "clippy", "fmt", "install", "publish", "add"]
    ),
    "go": frozenset(["build", "test", "run", "vet", "mod", "get", "install", "fmt", "generate"]),
    "docker": frozenset(["build", "run", "compose", "push", "pull", "exec", "ps", "logs", "image"]),
    "kubectl": frozenset(
        ["get", "apply", "describe", "logs", "exec", "delete", "rollout", "port-forward", "config"]
    ),
    "terraform": frozenset(
        ["init", "plan", "apply", "destroy", "validate", "fmt", "output", "state", "import"]
    ),
    "aws": frozenset(["s3", "ec2", "ecs", "iam", "sts", "lambda", "logs", "cloudformation", "ssm"]),
    "helm": frozenset(["install", "upgrade", "template", "lint", "list", "repo", "uninstall"]),
    "dbt": frozenset(["run", "test", "build", "compile", "seed", "snapshot", "docs", "deps"]),
}
# Shell words that are never a command a person would name.
SHELL_WORDS = frozenset(
    {
        "cd", "echo", "source", "export", "sleep", "if", "then", "fi", "do", "done", "for", "while",
        "else", "break", "true", "false", "!", "set", "printf",
    }
)  # fmt: skip
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$")
# A withheld-result reason is a closed token; anything else is counted as `other`.
_REASON = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
NO_TOKEN = "no token"  # noqa: S105 - a label for a blank reason, not a credential


def _runtime() -> tuple[Any, Any]:
    """(config, project_context), imported late: `scripts` is a package to tests, a path to mypy."""
    if _SKILL not in sys.path:
        sys.path.insert(0, _SKILL)
    from compass_runtime import config, project_context  # noqa: PLC0415

    return config, project_context


def _config() -> Any:
    config_mod, _project_context = _runtime()
    return config_mod.build_runtime_config(
        environ=os.environ,
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=pathlib.Path(_SKILL, "server.py"),
        model_calls_disabled=True,
    )


def default_dir() -> str:
    return os.path.join(store_paths.store_home(), SUBDIR)


def find_transcripts(
    root: str, days: float | None = None, *, now: float | None = None
) -> list[str]:
    """Parent transcripts under `root`, newest bound by mtime when `days` is given."""
    cut = None if days is None else (time.time() if now is None else now) - days * 86400
    found = []
    for path in sorted(glob.glob(os.path.join(glob.escape(root), "**", "*.jsonl"), recursive=True)):
        parts = pathlib.PurePath(os.path.relpath(path, root)).parts
        if "subagents" in parts:
            continue
        try:
            if cut is not None and os.stat(path).st_mtime < cut:
                continue
        except OSError:
            continue
        found.append(path)
    return found


def _head(words: list[str]) -> str | None:
    """The command word, and the subcommand for a tool that takes one; None when not a name."""
    first = os.path.basename(words[0]) if not words[0].startswith("./") else words[0]
    probe = first.removeprefix("./")
    if not _NAME.match(probe):
        return None
    if len(words) > 1 and words[1] in SUBCOMMANDS.get(first, ()):
        return f"{first} {words[1]}"
    return first


def _unwrapped_head_words(call: Any, index: int, words: list[str], pc: Any) -> list[str]:
    """The words a head is read from.

    The runtime strips `npx`, `uv run`, `rtk` and `pnpm exec` before a rule reads a
    command, so after the strip the first word can be the runner's positional
    argument, which may be a secret. Unless the stripped-to word is a closed known
    tool, the head is read from the words as written, so the runner is the head.
    """
    if words[0] in SUBCOMMANDS:
        return words
    raw = list(getattr(call.parts[index], "raw", ()) or ())
    while raw and pc._ASSIGNMENT_RE.match(raw[0]):  # noqa: SLF001
        raw = raw[1:]
    return raw or words


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            yield str(key)
            yield from _walk_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _walk_keys(inner)


def _bash_commands(record: dict[str, Any]) -> Iterable[str]:
    content = (record.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else ():
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") == "Bash"
        ):
            command = (block.get("input") or {}).get("command")
            if isinstance(command, str):
                yield command


def _is_rewriting_hook(record: dict[str, Any]) -> bool:
    attachment = record.get("attachment")
    return (
        record.get("type") == "attachment"
        and isinstance(attachment, dict)
        and str(attachment.get("hookName", "")).startswith("PreToolUse:Bash")
        and (
            "updatedInput" in set(_walk_keys(attachment))
            # Real attachments carry the hook's JSON as text in `stdout`, not as nested keys.
            or "updatedInput" in str(attachment.get("stdout", ""))
        )
    )


def _scan_file(path: str, project_context: Any, heads: collections.Counter[str]) -> dict[str, int]:
    """Per-session counts from the transcript's own lines: Bash calls, checks, CI polls, hooks."""
    out: collections.Counter[str] = collections.Counter()
    try:
        handle = open(path, encoding="utf-8", errors="replace")  # noqa: SIM115
    except OSError:
        return {}
    with handle:
        for line in handle:
            if '"Bash"' not in line and "updatedInput" not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            out["hook_rewrites"] += _is_rewriting_hook(record)
            for command in _bash_commands(record):
                out["bash_calls"] += 1
                try:
                    call = project_context._ShellCall(0.0, "/", {"command": command})  # noqa: SLF001
                except Exception:  # noqa: BLE001 - a command the parser refuses is not a head
                    out["unparsed"] += 1
                    continue
                out["checks"] += bool(call.checks)
                out["ci_polls"] += _count_heads(call, project_context, heads)
    return dict(out)


def _count_heads(call: Any, project_context: Any, heads: collections.Counter[str]) -> bool:
    """Count the unclassified heads of one command; True when any of its parts polls CI."""
    pc = project_context
    polls = False
    for index in call.meaningful:
        words = call.words[index][0]
        if not words:
            continue
        words = pc._runner_words(words)  # noqa: SLF001
        polls = polls or _polls_ci(words)
        if index in call.checks:
            continue
        if words[0] in pc._READ_ONLY_WORDS or " ".join(words[:2]) in pc._READ_ONLY_PAIRS:  # noqa: SLF001
            continue
        if words[0] in SHELL_WORDS:
            continue
        head = _head(_unwrapped_head_words(call, index, words, pc))
        if head is not None:
            heads[head] += 1
    return polls


def _tally(path: str, cfg: Any, project_context: Any) -> dict[str, Any] | None:
    try:
        tally = project_context._claude_tally(cfg, path)  # noqa: SLF001
    except Exception:  # noqa: BLE001 - one unreadable transcript must not stop the survey
        return None
    runs: collections.Counter[str] = collections.Counter()
    reasons: collections.Counter[str] = collections.Counter()
    for history in tally.runs.values():
        for run in history:
            if run["background"]:
                runs["background"] += 1
                continue
            result = str(run["result"])
            runs[result if result in ("passed", "failed") else "not-recorded"] += 1
            if result not in ("passed", "failed"):
                reason = str(run["result_reason"] or "")
                reasons[
                    reason if _REASON.match(reason) else NO_TOKEN if not reason else "other"
                ] += 1
    return {"runs": runs, "reasons": reasons}


def measure(paths: list[str]) -> dict[str, Any]:
    """The coverage figures over these transcripts. Counts and heads only."""
    _config_mod, project_context = _runtime()
    cfg = _config()
    sessions: collections.Counter[str] = collections.Counter()
    runs: collections.Counter[str] = collections.Counter()
    reasons: collections.Counter[str] = collections.Counter()
    heads: collections.Counter[str] = collections.Counter()
    hook_records = 0
    for path in paths:
        sessions["transcripts"] += 1
        scanned = _scan_file(path, project_context, heads)
        if scanned.get("bash_calls"):
            sessions["with_bash"] += 1
            sessions["with_closed_list_check"] += bool(scanned.get("checks"))
            sessions["polling_ci"] += bool(scanned.get("ci_polls"))
        if scanned.get("hook_rewrites"):
            sessions["with_rewriting_hook"] += 1
            hook_records += scanned["hook_rewrites"]
        tallied = _tally(path, cfg, project_context)
        if tallied is None:
            sessions["unreadable"] += 1
            continue
        runs.update(tallied["runs"])
        reasons.update(tallied["reasons"])
    foreground = runs["passed"] + runs["failed"] + runs["not-recorded"]
    recorded = runs["passed"] + runs["failed"]
    return {
        "transcripts": sessions["transcripts"],
        "unreadable": sessions["unreadable"],
        "sessions_with_bash": sessions["with_bash"],
        "sessions_with_closed_list_check": sessions["with_closed_list_check"],
        "sessions_polling_ci": sessions["polling_ci"],
        "check_runs": {
            "passed": runs["passed"],
            "failed": runs["failed"],
            "not_recorded": runs["not-recorded"],
            "background": runs["background"],
            "foreground": foreground,
            "recorded_share": (recorded / foreground) if foreground else None,
        },
        "withheld_by_reason": dict(sorted(reasons.items(), key=lambda pair: (-pair[1], pair[0]))),
        "top_unclassified_heads": [
            {"head": head, "count": count} for head, count in heads.most_common(TOP_HEADS)
        ],
        "output_rewriting_hook": {
            "present": hook_records > 0,
            "records": hook_records,
            "sessions": sessions["with_rewriting_hook"],
        },
    }


def render(report: dict[str, Any]) -> str:
    runs = report["check_runs"]
    share = runs["recorded_share"]
    hook = report["output_rewriting_hook"]

    def row(label: str, value: str) -> str:
        return f"{label:<{LABEL_WIDTH}}{value}"

    lines = [
        row("transcripts", f"{report['transcripts']} (unreadable {report['unreadable']})"),
        row("sessions with Bash", str(report["sessions_with_bash"])),
        row("sessions with a closed-list check", str(report["sessions_with_closed_list_check"])),
        row("sessions polling CI", str(report["sessions_polling_ci"])),
        row(
            "check runs",
            f"passed {runs['passed']}, failed {runs['failed']}, "
            f"not recorded {runs['not_recorded']}, background {runs['background']}",
        ),
        row(
            "recorded-result share",
            "n/a (no foreground runs)" if share is None else f"{share:.1%} of {runs['foreground']}",
        ),
        "withheld by reason",
    ]
    lines += [
        f"  {count:5d}  {reason}" for reason, count in report["withheld_by_reason"].items()
    ] or ["  none"]
    lines.append("top unclassified command heads")
    lines += [
        f"  {row['count']:5d}  {row['head']}" for row in report["top_unclassified_heads"]
    ] or ["  none"]
    lines.append(
        row(
            "output-rewriting PreToolUse hook",
            (
                f"present ({hook['records']} records in {hook['sessions']} sessions)"
                if hook["present"]
                else "absent"
            ),
        )
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None, say: Any = print) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", help="transcripts to read (default: the drift-replay corpus)")
    parser.add_argument("--days", type=float, help="only transcripts modified in the last N days")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    root = os.path.expanduser(args.dir) if args.dir else default_dir()
    if not os.path.isdir(root):
        say(f"{root} is not a directory.")
        return 2
    report = measure(find_transcripts(root, args.days))
    say(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
