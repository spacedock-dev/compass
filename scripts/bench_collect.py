#!/usr/bin/env python3
"""Measure Compass collection cost, per harness and in total.

Phase 0 of the event-driven observation plan gates on these numbers, so they
have to be reproducible on a reviewer's machine rather than quoted from one
laptop. Timing uses perf_counter and reports a median, because a cold page
cache makes a single sample useless.
"""

from __future__ import annotations

import argparse
import cProfile
import dataclasses
import json
import os
import pstats
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# The bar the event-driven plan sets for building per-harness dirty invalidation.
# Owned by docs/design-event-driven-observation.md; change it there first.
SELECTIVE_REUSE_BAR = 0.25

# The dashboard runtime is not an installed package. server.py imports it with
# the skill directory as sys.path[0], and this script has to arrange the same.
SKILL_DIR = Path(__file__).resolve().parents[1] / "compass" / "skills" / "compass"

# One synthetic in-window session's shape. Both defaults are measured, not
# chosen: on the machine that produced Phase 0's numbers the in-window Claude
# transcripts have a median of 53 records and 164 KiB, which is about 3.2 KiB a
# record. A synthetic session that matches both is the only kind whose cost
# means anything, because a collect spends most of its time reading in-window
# sessions rather than walking the store — see SIM_NOTE.
SIM_RECORDS = 53
SIM_RECORD_BYTES = 3200

# How many working directories a harness's sessions are spread across. Measured
# the same way: 75 project directories hold this machine's Claude store.
SIM_PROJECTS = 75

# Named profiles, in ACTIVE (in-window) sessions per harness. The modelled table
# in DRC-4087 states its profiles in store files, which a cProfile run shows is
# the wrong unit: walking 22,332 Claude files costs ~0.07 s of stat and glob,
# while turn-scanning the 38 of them inside the window costs ~0.28 s. Files set
# the walk term, in-window sessions set the read term, and the read term is the
# larger one. --simulate-cold adds the walk term back.
SIMULATIONS: dict[str, dict[str, int]] = {
    "single-harness": {"claude": 40},
    "claude-heavy": {"claude": 40, "codex": 4, "pi": 4, "copilot": 4, "droid": 4},
    "two-harness": {"claude": 20, "codex": 20},
    "balanced-five": {"claude": 12, "codex": 12, "pi": 12, "copilot": 12, "droid": 12},
    # The Sessions board a reader polls with two dozen Claude Code sessions, each of which can
    # carry a stored reading (--stored-readings): the poll the stored-reading record is held to.
    "board-24": {"claude": 24},
}

SIM_NOTE = """
A synthetic store measures what a machine with this session mix would cost, not
what any real machine costs. It is faithful about the number of in-window
sessions, their record count and their byte size, and about which collector code
runs. It is silent about four things: the four SQLite-backed harnesses
(antigravity, opencode, cursor, goose) have no generator here, because their
cost is row-bound rather than byte-bound and a representative row corpus is a
separate exercise; every synthetic session is the same size, where a real store
is long-tailed; a fresh temp tree is warm in the page cache; and subagent
transcripts, task files and Spacedock state are not generated at all.
""".strip()


def _iso(when: float) -> str:
    return datetime.fromtimestamp(when, tz=UTC).isoformat()


def _write_jsonl(path: Path, records: list[dict[str, Any]], when: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    os.utime(path, (when, when))


def _pad(record_bytes: int) -> str:
    """Filler wide enough that a synthetic record weighs what a real one does.

    Subtracting the envelope is deliberate: the caller asks for a record size and
    gets one, rather than that size plus however many bytes the surrounding JSON
    happens to take.
    """
    return "x" * max(0, record_bytes - 120)


def _claude_session(
    root: Path, index: int, when: float, records: int, size: int, project: int
) -> None:
    body = _pad(size)
    lines: list[dict[str, Any]] = [
        {"type": "user", "uuid": "u1", "timestamp": _iso(when), "message": {"content": body}}
    ]
    lines.extend(
        {
            "type": "assistant",
            "uuid": f"a{n}",
            "timestamp": _iso(when),
            "message": {"usage": {"output_tokens": 10}, "content": [{"text": body}]},
        }
        for n in range(records)
    )
    _write_jsonl(root / f"-w-proj-{project}" / f"{_sid(index)}.jsonl", lines, when)


def _codex_session(
    root: Path, index: int, when: float, records: int, size: int, project: int
) -> None:
    body = _pad(size)
    lines: list[dict[str, Any]] = [
        {
            "type": "session_meta",
            "timestamp": _iso(when),
            "payload": {"id": _sid(index), "cwd": f"/w/proj-{project}"},
        }
    ]
    lines.extend(
        {
            "type": "event_msg",
            "timestamp": _iso(when),
            "payload": {"type": "agent_message", "message": body},
        }
        for _ in range(records)
    )
    _write_jsonl(root / "2026" / "08" / "06" / f"rollout-{_sid(index)}.jsonl", lines, when)


def _pi_session(root: Path, index: int, when: float, records: int, size: int, project: int) -> None:
    body = _pad(size)
    sid = _sid(index)
    lines: list[dict[str, Any]] = [
        {"type": "session", "version": 3, "id": sid, "timestamp": _iso(when), "cwd": "/w/proj"}
    ]
    parent: str | None = None
    for n in range(records):
        # Chained rather than flat: Pi walks the last leaf's ancestors, so a fan
        # of orphans would leave all but one record off the active branch and
        # measure a scan the real collector never does.
        mid = f"m{n:08d}"
        lines.append(
            {
                "type": "message",
                "id": mid,
                "parentId": parent,
                "timestamp": _iso(when),
                "message": {
                    "role": "assistant" if n % 2 else "user",
                    "content": body,
                    "timestamp": int(when * 1000),
                },
            }
        )
        parent = mid
    _write_jsonl(root / f"--w-proj-{project}--" / f"2026-08-06_{sid}.jsonl", lines, when)


def _gemini_session(
    root: Path, index: int, when: float, records: int, size: int, project: int
) -> None:
    body = _pad(size)
    lines: list[dict[str, Any]] = [
        {"sessionId": _sid(index), "kind": "main", "directories": [f"/w/proj-{project}"]}
    ]
    lines.extend(
        {
            "type": "gemini" if n % 2 else "user",
            "timestamp": _iso(when),
            "content": body,
            "tokens": {"output": 10},
        }
        for n in range(records)
    )
    _write_jsonl(root / f"proj-{project}" / "chats" / f"session-{_sid(index)}.jsonl", lines, when)


def _copilot_session(
    root: Path, index: int, when: float, records: int, size: int, project: int
) -> None:
    body = _pad(size)
    lines: list[dict[str, Any]] = [
        {
            "type": "session.start",
            "timestamp": _iso(when),
            "data": {"context": {"cwd": f"/w/proj-{project}"}},
        }
    ]
    lines.extend(
        {"type": "user.message", "timestamp": _iso(when), "data": {"text": body}}
        for _ in range(records)
    )
    _write_jsonl(root / "session-state" / _sid(index) / "events.jsonl", lines, when)


def _droid_session(
    root: Path, index: int, when: float, records: int, size: int, project: int
) -> None:
    body = _pad(size)
    lines: list[dict[str, Any]] = [
        {
            "type": "session_start",
            "id": _sid(index),
            "sessionTitle": f"synthetic {index}",
            "cwd": f"/w/proj-{project}",
            "timestamp": _iso(when),
        }
    ]
    lines.extend(
        {
            "type": "message",
            "timestamp": _iso(when),
            "message": {"role": "assistant" if n % 2 else "user", "content": body},
        }
        for n in range(records)
    )
    _write_jsonl(root / f"proj-{project}" / f"{_sid(index)}.jsonl", lines, when)


def _sid(index: int) -> str:
    """A UUID-shaped id, because more than one collector keys on the shape."""
    return f"{index:08x}-1111-2222-3333-444444444444"


# harness -> (one-session writer, store key -> the key's root inside the harness
# directory). Claude is the only harness with two roots, and its tasks store is
# named here so a profile run cannot fall back to reading the real one.
GENERATORS: dict[str, tuple[Callable[..., None], dict[str, str]]] = {
    "claude": (_claude_session, {"claude.projects": "sessions", "claude.tasks": "tasks"}),
    "codex": (_codex_session, {"codex.sessions": "sessions"}),
    "pi": (_pi_session, {"pi.sessions": "sessions"}),
    "gemini": (_gemini_session, {"gemini.tmp": "sessions"}),
    "copilot": (_copilot_session, {"copilot.root": "sessions"}),
    "droid": (_droid_session, {"droid.projects": "sessions"}),
}

# Every store the runtime resolves. A profile that overrode only the harnesses it
# generates would leave the rest reading the caller's real stores, and the share
# it reported would be of a machine nobody has.
ALL_STORE_KEYS = (
    "claude.projects",
    "claude.tasks",
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


def parse_simulation(spec: str) -> dict[str, int]:
    """A profile name, or ``harness=N,harness=N`` in active sessions per harness.

    Unknown names are an error rather than a skip. A typo that silently
    generated nothing would report a share for a profile the caller never ran,
    which is the failure this whole ticket exists to stop repeating.
    """
    if spec in SIMULATIONS:
        return dict(SIMULATIONS[spec])
    counts: dict[str, int] = {}
    for part in spec.split(","):
        harness, separator, raw = part.strip().partition("=")
        harness = harness.strip()
        if not separator or harness not in GENERATORS:
            raise ValueError(
                f"unknown simulation {spec!r}: expected one of {', '.join(sorted(SIMULATIONS))}, "
                f"or harness=N pairs from {', '.join(sorted(GENERATORS))}"
            )
        try:
            count = int(raw)
        except ValueError:
            raise ValueError(f"session count for {harness!r} is not an integer: {raw!r}") from None
        if count < 0:
            raise ValueError(f"session count for {harness!r} is negative: {count}")
        counts[harness] = count
    return counts


def build_simulated_store(
    root: Path,
    counts: dict[str, int],
    *,
    now: float,
    records: int = SIM_RECORDS,
    record_bytes: int = SIM_RECORD_BYTES,
    cold: int = 0,
    projects: int = SIM_PROJECTS,
) -> dict[str, str]:
    """Write a synthetic store and return the store-root overrides that reach it.

    ``counts`` is in-window sessions, which is the term collection cost is
    actually made of. ``cold`` adds that many out-of-window sessions per harness
    on top: they are walked and never read, which is the other term.

    ``projects`` is how many working directories those sessions are spread
    across, and it is not a cosmetic detail. The first version of this generator
    gave every session its own project directory, and a store shaped like this
    machine's came out 4.8x more expensive than the machine itself, because the
    walk was scanning 22,000 directories instead of 75.
    """
    empty = root / "empty"
    empty.mkdir(parents=True, exist_ok=True)
    # goose.db names a file, not a directory, so its empty stand-in has to be a
    # path that does not exist rather than the empty directory the others get.
    overrides = {key: str(empty) for key in ALL_STORE_KEYS}
    overrides["goose.db"] = str(empty / "absent.db")
    for harness, count in counts.items():
        write, keys = GENERATORS[harness]
        for key, leaf in keys.items():
            (root / harness / leaf).mkdir(parents=True, exist_ok=True)
            overrides[key] = str(root / harness / leaf)
        store = root / harness / "sessions"
        spread = max(1, projects)
        for index in range(count):
            write(store, index, now - 60.0 - index, records, record_bytes, index % spread)
        for index in range(cold):
            # Two weeks back, well outside any --window-hours a benchmark uses,
            # and one small record each: an out-of-window session is stat'd and
            # skipped, never read, so its size buys nothing and 20,000 of them at
            # the in-window size would write gigabytes to measure a stat.
            write(store, count + index, now - 1_209_600.0, 1, 200, index % spread)
    return overrides


def timed(inner: Callable[..., Any], samples: list[float]) -> Callable[..., Any]:
    """Wrap a registry callable so each call appends its duration to ``samples``.

    The duration is recorded in a finally and the exception is re-raised
    untouched: the per-harness failure boundary belongs to Application.collect,
    and swallowing here would change which harnesses the benchmark reports as
    broken.
    """

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return inner(*args, **kwargs)
        finally:
            samples.append((time.perf_counter() - started) * 1000.0)

    return wrapped


def measure(app: Any, *, repeat: int) -> dict[str, Any]:
    """Median wall-clock cost of a full collect, and of each harness inside it.

    Every sample is a real collect against the caller's stores. The per-harness
    figures come from wrapping each registry entry's collector, so they sum to
    the total minus serialization rather than being estimated.

    HarnessSpec is frozen, so a wrapper cannot be assigned over spec.collect.
    The registry is rebuilt with dataclasses.replace for the duration of the
    measurement and the original tuple is restored in a finally, which keeps a
    benchmark run from leaving instrumentation behind on a live application.
    """
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    totals: list[float] = []
    per_harness: dict[str, list[float]] = {}
    discovery: list[float] = []
    discover_calls: list[float] = []
    specs = tuple(getattr(app, "harnesses", ()) or ())
    for spec in specs:
        per_harness.setdefault(spec.key, [])
    if specs:
        app.harnesses = tuple(
            dataclasses.replace(
                spec,
                collect=timed(spec.collect, per_harness[spec.key]),
                discover=timed(spec.discover, discover_calls),
            )
            for spec in specs
        )
    sessions: dict[str, int] = {}
    try:
        for _ in range(repeat):
            mark = len(discover_calls)
            started = time.perf_counter()
            collection = app.collect(show_all=False)
            totals.append((time.perf_counter() - started) * 1000.0)
            # Every harness is probed on every collect, so one sample is the
            # whole discovery cost of one collect rather than of one probe.
            discovery.append(sum(discover_calls[mark:]))
            # Rows per harness, from the last sample. A collector handed a store
            # whose shape it does not recognise costs almost nothing and reports
            # nothing, and the share would come out confidently wrong; the report
            # prints this so a run that measured an empty store is visible.
            sessions = {}
            for session in collection.get("sessions", ()):
                # A stand-in application in the script's own tests yields rows
                # that are not session mappings, and counting is a diagnostic
                # rather than the measurement, so it steps over them.
                if not isinstance(session, dict):
                    continue
                key = str(session.get("harness", "?"))
                sessions[key] = sessions.get(key, 0) + 1
    finally:
        if specs:
            app.harnesses = specs
    return {
        "total_ms": statistics.median(totals),
        # An undiscovered harness never has its collector called, so it has no
        # samples and is left out rather than reported as zero.
        "per_harness_ms": {name: statistics.median(v) for name, v in per_harness.items() if v},
        "discovery_ms": statistics.median(discovery) if discovery else 0.0,
        "sessions": sessions,
        "repeat": repeat,
    }


def selective_reuse(result: dict[str, Any]) -> dict[str, Any]:
    """What per-harness dirty invalidation could save on this machine.

    The dirty harness is the one whose cost cannot be skipped, so the saving
    available to reuse is the total minus the largest single harness. That makes
    the whole question one number: reuse clears a 25% bar whenever the largest
    harness is at most 75% of collection time.

    Absolute milliseconds are not comparable across machines, and one machine's
    absolute figures are what made this question look settled when it was not.
    The share is comparable, which is why the report leads with it.
    """
    per = {k: float(v) for k, v in result["per_harness_ms"].items()}
    total = float(result["total_ms"])
    if not per or total <= 0:
        return {"largest": None, "share": None, "saving": None}
    largest = max(per, key=lambda k: per[k])
    share = per[largest] / total
    return {"largest": largest, "share": share, "saving": 1.0 - share}


def format_report(result: dict[str, Any], simulation: dict[str, Any] | None = None) -> str:
    lines: list[str] = []
    if simulation is not None:
        asked = simulation["counts"]
        lines += [
            f"simulated store: {simulation['spec']}",
            "  active sessions asked for: "
            + ", ".join(f"{k}={v}" for k, v in sorted(asked.items())),
            "  collected:                 "
            + (
                ", ".join(f"{k}={v}" for k, v in sorted(result["sessions"].items()))
                or "NOTHING — the generated store was not recognised, the run below is meaningless"
            ),
            (
                f"  per session: {simulation['records']} records of "
                f"~{simulation['record_bytes']} B "
                f"(~{simulation['records'] * simulation['record_bytes'] // 1024} KiB)"
            ),
            f"  out-of-window sessions per harness: {simulation['cold']}",
            f"  project directories per harness: {simulation['projects']}",
            "",
        ]
    lines += [
        f"repeat: {result['repeat']}",
        f"total_ms: {result['total_ms']}",
        f"discovery_ms: {result['discovery_ms']}",
    ]
    for name, value in sorted(result["per_harness_ms"].items(), key=lambda kv: -float(kv[1])):
        lines.append(f"  {name}: {value} ms")
    reuse = selective_reuse(result)
    if reuse["share"] is not None:
        verdict = "clears" if reuse["saving"] >= SELECTIVE_REUSE_BAR else "below"
        lines += [
            "",
            f"largest harness: {reuse['largest']} at {reuse['share']:.1%} of collection time",
            (
                f"selective-reuse saving: {reuse['saving']:.1%} "
                f"({verdict} the {SELECTIVE_REUSE_BAR:.0%} bar)"
            ),
            "",
        ]
        lines += (
            SIM_NOTE.splitlines()
            if simulation is not None
            else [
                "One machine cannot settle this: the figure is a property of how your",
                "history is distributed across harnesses, not of the product. A store",
                "dominated by one harness reports a low saving; a balanced multi-harness",
                "store reports a high one. If you run several harnesses, the share above is",
                "worth reporting on DRC-4080. To ask the same question of a session mix you",
                "do not have, run --simulate.",
            ]
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--window-hours", type=float, default=24.0)
    parser.add_argument("--profile", action="store_true", help="cProfile one collect by function")
    parser.add_argument(
        "--simulate",
        metavar="SPEC",
        help=(
            "measure a synthetic store instead of your own: a named profile "
            f"({', '.join(sorted(SIMULATIONS))}) or harness=N pairs in active sessions"
        ),
    )
    parser.add_argument("--simulate-records", type=int, default=SIM_RECORDS)
    parser.add_argument("--simulate-record-bytes", type=int, default=SIM_RECORD_BYTES)
    parser.add_argument("--simulate-projects", type=int, default=SIM_PROJECTS)
    parser.add_argument(
        "--simulate-cold",
        type=int,
        default=0,
        help="out-of-window sessions per harness: walked on every collect, never read",
    )
    parser.add_argument(
        "--stored-readings",
        action="store_true",
        help=(
            "with --simulate, give every simulated Claude Code session a saved goal and a stored "
            "reading, with the record of what it read where this build keeps one"
        ),
    )
    parser.add_argument("--list-simulations", action="store_true")
    args = parser.parse_args(argv[1:])

    if args.list_simulations:
        for name, counts in sorted(SIMULATIONS.items()):
            print(f"{name}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        return 0

    if str(SKILL_DIR) not in sys.path:
        sys.path.insert(0, str(SKILL_DIR))
    # Deferred on purpose: sys.path has to carry SKILL_DIR before the runtime
    # resolves, and keeping it out of module scope also lets measure() and
    # format_report() be imported without the runtime tree present.
    from compass_runtime import cli  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="compass-bench-") as scratch:
        simulation: dict[str, Any] | None = None
        overrides: dict[str, str] | None = None
        if args.simulate:
            try:
                counts = parse_simulation(args.simulate)
            except ValueError as error:
                print(f"bench_collect: {error}", file=sys.stderr)
                return 2
            overrides = build_simulated_store(
                Path(scratch),
                counts,
                now=time.time(),
                records=args.simulate_records,
                record_bytes=args.simulate_record_bytes,
                cold=args.simulate_cold,
                projects=args.simulate_projects,
            )
            simulation = {
                "spec": args.simulate,
                "counts": counts,
                "records": args.simulate_records,
                "record_bytes": args.simulate_record_bytes,
                "cold": args.simulate_cold,
                "projects": args.simulate_projects,
            }
        config, state = build_runtime(
            cli, args, store_root_overrides=overrides, state_home=Path(scratch) / "compass"
        )
        # build_application, not Application(...): the constructor also requires
        # the harness registry and three injected sinks, and the CLI is what
        # assembles them. The no-op sink keeps store diagnostics out of the report.
        app = cli.build_application(
            config,
            state,
            clock=time.time,
            diagnostic_sink=lambda _message: None,
        )
        if args.stored_readings and simulation is not None:
            seed_stored_readings(config, state, int(simulation["counts"].get("claude", 0)))
        if args.profile:
            profiler = cProfile.Profile()
            profiler.enable()
            app.collect(show_all=False)
            profiler.disable()
            pstats.Stats(profiler).sort_stats("cumulative").print_stats(25)
            return 0
        print(format_report(measure(app, repeat=args.repeat), simulation))
    return 0


def seed_stored_readings(config: Any, state: Any, count: int) -> None:
    """A saved goal and a stored reading on each simulated Claude Code session.

    The reading is stored with a `reading_evidence` record where the runtime has that seam, so the
    same script measures a build without one and a build with one: the poll reads the annotation
    store on every collection, and the record is what grows it.
    """
    import inspect  # noqa: PLC0415

    from compass_runtime import annotations as annotation_store  # noqa: PLC0415

    keeps_record = "evidence" in inspect.signature(annotation_store.record_reading).parameters
    now = time.time()
    for index in range(count):
        sid = _sid(index)
        annotation_store.annotate(
            config, state, "claude", sid, goal="Add retry with backoff", now=now - 600
        )
        read_at = now - 300.0
        # `Any`: an `Assessment` TypedDict to the runtime, built here as plain JSON.
        assessment: Any = {
            "revision_read": 1,
            "stamp": "bench",
            "cutoff": "",
            "scope": "last-turn",
            "scope_text": "Read to its last turn.",
            "ended_at_read": None,
            "read_at": read_at,
            "evidence_through": read_at - 1,
            "revision_read_at": now - 600,
            "window_start": now - 600,
            "criteria": {"goal": {"result": "unverifiable", "cites": [], "why": ""}},
        }
        extra: dict[str, Any] = {}
        if keeps_record:
            extra["evidence"] = {
                "v": 1,
                "read_at": read_at,
                "project": "a" * 32,
                "history": {"lineage": "b" * 32, "generation": 7},
                "transcript_bytes": 123_456,
                "direction_at": None,
            }
        stored = annotation_store.record_reading(
            config, state, "claude", sid, assessment=assessment, **extra
        )
        if stored != annotation_store.OUTCOME_STORED:
            raise RuntimeError(f"bench_collect: could not seed a reading ({stored})")


def build_runtime(
    cli: Any,
    args: argparse.Namespace,
    *,
    store_root_overrides: dict[str, str] | None,
    state_home: Path,
) -> tuple[Any, Any]:
    """Config and state, with the stores redirected when a simulation asked.

    ``cli.build_runtime`` takes no store overrides, because nothing in the
    product needs them; a simulation does, so it goes one level down to
    ``build_runtime_config`` and reproduces what the CLI passes. usage_fetch is
    off in both branches on purpose: a benchmark must never make an outbound
    vendor quota request, and a fetch would pollute the timing besides.

    A simulation also moves Compass's own state into ``state_home``. Redirecting
    the harness stores alone left ``COMPASS_HOME`` resolving to the owner's real
    ``~/.compass``, so every simulated collect recorded its fixture sessions into
    their real history store, where at the size cap each one evicts a real row.
    The state is redirected rather than history switched off so the timing still
    includes the history write a real collect pays for.
    """
    if store_root_overrides is None:
        # Parse standard CLI defaults so newly added runtime flags populate
        # automatically without manual Namespace syncing.
        ns = cli.build_parser().parse_args([])
        ns.window_hours = args.window_hours
        ns.no_usage = True
        built: tuple[Any, Any] = cli.build_runtime(
            ns,
            started=time.time(),
        )
        return built
    from compass_runtime import config as runtime_config  # noqa: PLC0415
    from compass_runtime import state as runtime_state  # noqa: PLC0415

    config = runtime_config.build_runtime_config(
        environ={**os.environ, runtime_config.COMPASS_HOME_ENV: str(state_home)},
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=SKILL_DIR / "server.py",
        store_root_overrides=store_root_overrides,
        window_hours=args.window_hours,
        usage_fetch_enabled=False,
    )
    return config, runtime_state.build_runtime_state(config, started=time.time())


if __name__ == "__main__":
    sys.exit(main(sys.argv))
