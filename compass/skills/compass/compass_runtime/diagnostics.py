"""Why a harness is not showing up: store paths, what is on disk, and errors."""

from __future__ import annotations

import os
import stat as stat_module
import sys
from typing import TYPE_CHECKING, Any

from compass_runtime import config as runtime_config
from compass_runtime import io as runtime_io
from compass_runtime import project_context, project_scripts, reader_checks, tripwires

if TYPE_CHECKING:
    from compass_runtime.aggregate import Application
    from compass_runtime.config import RuntimeConfig


# Report order only. The paths come from the resolved configuration, never from
# a second table, so a relocated store cannot be reported at a path nothing
# searches. Pinned here so reordering the resolver cannot reshuffle output that
# gets diffed between machines.
_REPORT_KEY_ORDER = (
    "claude.projects",
    "claude.tasks",
    "claude.teams",
    "codex.sessions",
    "pi.sessions",
    "gemini.tmp",
    "antigravity.root",
    "copilot.root",
    "opencode.data",
    "cursor.chats",
    "goose.db",
    "droid.projects",
)


def store_primaries(config: RuntimeConfig) -> dict[str, str]:
    """Primary root per store, in the order the report renders them.

    A store the resolver knows about but this module does not is still reported,
    at the end, rather than silently dropped from the one place a user looks to
    find out where Compass searched.
    """
    resolved = {key: roots[0] for key, roots in config.store_roots.items() if roots}
    ordered = {key: resolved[key] for key in _REPORT_KEY_ORDER if key in resolved}
    ordered.update({key: value for key, value in resolved.items() if key not in ordered})
    return ordered


def candidate_report(path: str) -> dict[str, Any]:
    """What a single candidate store path actually is on disk."""
    entry: dict[str, Any] = {"path": path, "kind": "missing", "readable": False, "entries": None}
    # stat(), not isdir()/isfile(): those swallow OSError and return False, so
    # a candidate under an unreadable parent reported "missing" — the exact
    # confusion between "absent" and "inaccessible" this exists to remove.
    try:
        stat_result = os.stat(path)
    except FileNotFoundError:
        # stat() follows symlinks, so a dangling one lands here. Say so rather
        # than calling it absent — the target is what the user needs to fix.
        if os.path.islink(path):
            entry["kind"] = "broken symlink"
        return entry
    except OSError as exc:
        entry["kind"] = "inaccessible"
        entry["error"] = f"{type(exc).__name__}: {exc}"
        return entry
    if stat_module.S_ISDIR(stat_result.st_mode):
        entry["kind"] = "directory"
        try:
            with os.scandir(path) as scan:
                # Streamed, not materialised: this is an arbitrary user store
                # root, so len(list(...)) would hold every entry in memory.
                entry["entries"] = sum(1 for _ in scan)
            entry["readable"] = True
        except OSError as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
    elif stat_module.S_ISREG(stat_result.st_mode):
        entry["kind"] = "file"
        entry["readable"] = os.access(path, os.R_OK)
    else:
        # A FIFO or socket at a store path is never a usable store; reporting
        # it as a readable file would send someone looking in the wrong place.
        entry["kind"] = "special file"
    return entry


def diagnose(application: Application) -> dict[str, Any]:
    """Everything needed to explain a harness that is not showing up.

    Collectors swallow their errors so one broken store cannot take down the
    dashboard, which means a wrong path looks exactly like an idle machine.
    This is the counterweight: it names every location searched and what was
    found there. Local only — nothing is transmitted anywhere.

    It runs the application's own collection and registry rather than building
    a second one, so the report describes the process it was asked about.
    """
    config, state = application.config, application.state
    with state.cache_lock:
        state.store_errors.clear()  # this run's failures only
    data = application.collect(show_all=True, notify=False)
    with state.cache_lock:
        store_errors = dict(state.store_errors)
    sessions_by_harness: dict[str, int] = {}
    for session in data["sessions"]:
        key = str(session["harness"])
        sessions_by_harness[key] = sessions_by_harness.get(key, 0) + 1
    overrides_vars = (
        *runtime_config.STORE_ENV_VARS,
        runtime_config.COMPASS_HOME_ENV,
        "XDG_DATA_HOME",
    )
    return {
        "tripwires": {
            "enabled": config.tripwires_enabled,
            "path": tripwires.store_path(config) if config.tripwires_enabled else None,
            "error": data["tripwires"]["error"],
        },
        # The unasked lane is the one model caller an operator can switch on
        # at startup without the observer flag, so whether the off switch
        # refused it is reported here rather than left to the page (DRC-4649).
        "unasked": {"enabled": config.unasked_enabled},
        "platform": config.platform_name,
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "home": config.home,
        "compass_home": config.state_home,
        "sqlite": {
            "available": runtime_io.sqlite_available(),
            "error": runtime_io.SQLITE_IMPORT_ERROR,
            "version": (
                runtime_io.sqlite_module.sqlite_version if runtime_io.sqlite_available() else None
            ),
        },
        "env": {name: os.environ[name] for name in overrides_vars if os.environ.get(name)},
        # Failures the collectors swallowed. Without these a corrupt database
        # reads as a healthy store with no sessions.
        "store_errors": store_errors,
        # Declaring files (package.json, a Makefile, a justfile) the collection above found and
        # did not trust, with why. Names and a closed reason only, never a file's content.
        "project_scripts": project_scripts.problems(config.home),
        # The reader's own list of check commands: where it is, whether it could be read, and each
        # entry that was ignored with its program and why. Never an argument or a path.
        "reader_checks": reader_checks.report(config, project_context.listed_entry_refusal),
        "stores": {
            key: {
                "primary": primary,
                "candidates": [
                    candidate_report(root) for root in runtime_config.store_roots(config, key)
                ],
            }
            for key, primary in store_primaries(config).items()
        },
        "harnesses": [
            {**harness, "sessions": sessions_by_harness.get(str(harness["key"]), 0)}
            for harness in data["harnesses"]
        ],
    }


def _project_script_lines(problems: list[dict[str, str]]) -> list[str]:
    if not problems:
        return []
    lines = ["", "Project scripts not read as checks"]
    for problem in problems:
        lines.extend([f"  [  --] {problem['file']}", f"           {problem['reason']}"])
    return lines


def _reader_check_lines(report: dict[str, Any] | None) -> list[str]:
    return render_reader_checks(report).split("\n") if report else []


def render_reader_checks(report: dict[str, Any]) -> str:
    lines = ["", "Reader-listed checks", f"  file       {report['path']}"]
    if report["error"]:
        lines.append(f"  [  --] not read: {report['error']}")
    elif not report["projects"]:
        lines.append("  none listed")
    else:
        lines.append(
            f"  {report['listed']} command(s) for {report['projects']} project(s) count as checks"
        )
    if report.get("projects_dropped"):
        lines.append(f"  [  --] {report['projects_dropped']} project(s) past the cap were not read")
    for item in report["ignored"]:
        program = item["program"] or "an entry"
        lines.extend([f"  [  --] {program}", f"           ignored: {item['reason']}"])
    if report.get("ignored_more"):
        lines.append(f"  [  --] and {report['ignored_more']} more ignored")
    return "\n".join(lines)


def render_diagnosis(report: dict[str, Any]) -> str:
    """ASCII-only rendering — this output gets pasted into bug reports from
    consoles whose encoding we do not control."""
    sqlite_info = report["sqlite"]
    lines = [
        "Compass diagnostics",
        f"  platform   {report['platform']} (python {report['python']})",
        f"  python at  {report['executable']}",
        f"  home       {report['home']}",
        f"  compass   {report.get('compass_home') or report['home']}",
        f"  sqlite3    {sqlite_info['version'] or 'UNAVAILABLE: ' + str(sqlite_info['error'])}",
    ]
    stage = report["tripwires"]
    lines.append(
        f"  tripwires  {stage['path'] or 'disabled'}"
        + (": " + stage["error"] if stage["error"] else "")
    )
    lines.append(f"  unasked    {'on' if report['unasked']['enabled'] else 'off'}")
    env = report["env"]
    lines.append(
        "  overrides  " + (", ".join(f"{k}={v}" for k, v in env.items()) if env else "none")
    )

    lines.append("")
    lines.append("Harnesses")
    for harness in report["harnesses"]:
        mark = "ok  " if harness["discovered"] else "  --"
        detail = f"{harness['sessions']} session(s)" if harness["discovered"] else "not discovered"
        lines.append(f"  [{mark}] {harness['label']!s:<10} {detail}")
        if harness["error"]:
            lines.append(f"           error: {harness['error']}")

    if report["store_errors"]:
        lines.append("")
        lines.append("Stores that failed to open or query")
        for path, message in report["store_errors"].items():
            lines.append(f"  [  --] {path}")
            lines.append(f"           {message}")

    lines.extend(_project_script_lines(report.get("project_scripts") or []))
    lines.extend(_reader_check_lines(report.get("reader_checks")))

    lines.append("")
    lines.append("Stores searched (in order)")
    for key, store in report["stores"].items():
        lines.append(f"  {key}")
        for candidate in store["candidates"]:
            mark = "ok  " if candidate["kind"] != "missing" else "  --"
            detail = candidate["kind"]
            if candidate["entries"] is not None:
                detail += f", {candidate['entries']} entries"
            if not candidate["readable"] and candidate["kind"] != "missing":
                detail += ", NOT READABLE"
            if candidate.get("error"):
                detail += f", {candidate['error']}"
            lines.append(f"    [{mark}] {candidate['path']}  ({detail})")
    return "\n".join(lines)
