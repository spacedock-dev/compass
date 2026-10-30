#!/usr/bin/env python3
"""Run a unittest discovery across worker processes, with unittest's own result.

The CI quality gate ran the dashboard suite single-process on multi-core
runners, six times per pull request. This runner keeps unittest's discovery,
fixtures and verdict, and spreads the work:

- Every worker repeats the exact ``discover`` call the serial command makes.
  That is load-bearing, not tidiness: 29 test modules never import
  ``tests/support.py`` and get their temporary ``HOME`` and ``COMPASS_HOME``
  only because discovery imports it first. A worker that imported just its
  own modules would run those against the developer's real home.
- The unit of work is a test class that has class fixtures, so ``setUpClass``
  keeps its meaning, and a single test otherwise, so a long fixture-free class
  spreads across workers. Units go into one queue, largest first, and each
  worker pulls until it is empty. Measured 2026-09-23 on the same 3705 tests
  and verdict: 131s serial, 33.8s on four workers with whole classes, 19s once
  fixture-free classes were split. A timings file gained 0.2s at four workers,
  so the queue orders on test count alone and nothing goes stale.
- Workers are started with ``spawn`` everywhere, which is what Windows does
  anyway, so a pass on Linux says something about the other two.
- ``--coverage`` starts coverage inside each worker with a data suffix; run
  ``coverage combine`` afterwards. Coverage is imported only when asked for,
  because the runtime floor installs no coverage.
- Output a test writes to ``sys.stdout`` or ``sys.stderr`` is held, as
  ``unittest -b`` does, and shown only with that test's failure or error. A
  passing run printed 650 lines of argparse refusals and phase timings that
  tests provoke on purpose (2026-10-28), which buried the one line that mattered.
  ``--no-buffer`` prints it as it happens. A subprocess writes to the real
  descriptors and is never held.

Every class is its own top-level run, so ``setUpModule`` runs once per class
rather than once per module. One module defines it, to start and stop a log
patch, which is indifferent to that. And two classes that land in different
workers cannot see each other's leftovers, so an order-dependent failure that
serial ``unittest`` would show every time can pass here; the serial command
still exists for chasing one.

Each worker also reports what its own discovery found, and any difference from
the parent's is an error. Without that, a class a worker failed to import ran
as an empty suite and passed, and a class only a worker found was never run:
three crafted suites went green here and red under ``unittest``.

Usage mirrors ``python -m unittest discover``::

    python scripts/run_tests.py -s compass/skills/compass/tests -t .
    python scripts/run_tests.py -s scripts/tests -t scripts/tests -j 4 --coverage
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import queue
import sys
import tempfile
import time
import traceback
import unittest
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from multiprocessing.queues import Queue

# How long the parent waits on the result queue before checking whether its
# workers are still alive. A worker that dies without a word is reported as an
# error on every class it never finished, never waited on forever.
POLL_SECONDS = 5.0
JOIN_SECONDS = 30.0


# Seconds one module took on a hosted Windows runner, the slowest platform (measured 2026-10-10
# from the `--slowest` report of a passing run), used only to balance `--shard` legs. A module
# not listed costs DEFAULT_COST. The numbers need not stay current: a stale table makes a shard
# slower, never wrong, because every module lands in exactly one shard whatever it costs.
MODULE_COST: dict[str, float] = {
    "test_analyze_campaign": 450.0,
    "test_qualification_conditional_priority": 212.0,
    # Not measured on Windows: 140 s and 172 s on a loaded local macOS run (2026-10-30), scaled.
    "test_qualification_tenth": 300.0,
    "test_qualification_retry": 350.0,
    "test_closure_qualification": 150.0,
    "test_qualification_semantic_measurement": 137.0,
    "test_release_transition": 130.0,
    "test_claude_route_verification": 58.0,
}
DEFAULT_COST = 2.0


def parse_shard(text: str) -> tuple[int, int]:
    """Read ``K/N`` (1-based) and refuse anything else."""
    try:
        first, count = (int(part) for part in text.split("/"))
    except ValueError:
        first = count = 0
    if not 1 <= first <= count:
        message = f"--shard expects K/N with 1 <= K <= N, got {text!r}"
        raise SystemExit(message)
    return first, count


def assign_shards(modules: Iterable[str], count: int) -> dict[str, int]:
    """Give each module one shard, heaviest first onto the lightest shard (zero-based)."""
    load = [0.0] * count
    shard_of: dict[str, int] = {}
    ranked = sorted(set(modules), key=lambda name: (-MODULE_COST.get(name, DEFAULT_COST), name))
    for module in ranked:
        lightest = min(range(count), key=lambda index: (load[index], index))
        shard_of[module] = lightest
        load[lightest] += MODULE_COST.get(module, DEFAULT_COST)
    return shard_of


def module_of(tests: list[unittest.TestCase]) -> str:
    """The test module a unit belongs to, by its last dotted component."""
    first = tests[0]
    name = type(first).__module__
    if name == "unittest.loader":  # an import failure: its id is the module that failed
        name = first.id()
    return name.rsplit(".", 1)[-1]


def iter_tests(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    """Yield every test case in a nested suite, in discovery order."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item


def has_class_fixture(kind: type) -> bool:
    """Whether a class overrides `setUpClass` or `tearDownClass` anywhere above it."""
    return any(
        getattr(kind, name).__func__ is not getattr(unittest.TestCase, name).__func__
        for name in ("setUpClass", "tearDownClass")
    )


def unit_of(test: unittest.TestCase) -> str:
    """Name a test's unit of work: its class if it has class fixtures, else itself.

    A class with `setUpClass` or `tearDownClass` stays on one worker, so the
    fixture runs once around all its tests. A class without one has nothing that
    ties its tests together, so each test is its own unit and a long class
    spreads across workers. Measured on the Windows runner 2026-09-23: one
    fixture-free class of about twenty tests took 54s of an 89s job, every
    other class at most 18s, and a class runs on one worker.

    An import failure is keyed by its own id, which names the module, because
    every one of them shares the class `unittest.loader._FailedTest` and a
    report that says only that cannot say what broke.
    """
    kind = type(test)
    name = f"{kind.__module__}.{kind.__qualname__}"
    if name == "unittest.loader._FailedTest" or not has_class_fixture(kind):
        return test.id()
    return name


def discover(
    start: str, top: str | None, pattern: str, shard: tuple[int, int] | None = None
) -> dict[str, list[unittest.TestCase]]:
    """Discover like ``unittest discover`` and group the cases by class.

    With ``shard`` (K, N) only the units of the modules assigned to leg K of N are kept. Parent and
    every worker discover with the same shard, so the inventory check still compares like with like.
    """
    suite = unittest.TestLoader().discover(start, pattern=pattern, top_level_dir=top)
    units: dict[str, list[unittest.TestCase]] = {}
    for test in iter_tests(suite):
        units.setdefault(unit_of(test), []).append(test)
    if shard is None:
        return units
    index, count = shard
    owner = assign_shards((module_of(tests) for tests in units.values()), count)
    return {unit: tests for unit, tests in units.items() if owner[module_of(tests)] == index - 1}


def summarise(unit: str, result: unittest.TestResult, seconds: float) -> dict[str, Any]:
    """Reduce a result to picklable strings the parent can merge and print."""
    return {
        "unit": unit,
        "seconds": seconds,
        "run": result.testsRun,
        "failures": [(str(test), text) for test, text in result.failures],
        "errors": [(str(test), text) for test, text in result.errors],
        "skipped": [(str(test), text) for test, text in result.skipped],
        "expected": [(str(test), text) for test, text in result.expectedFailures],
        "unexpected": [str(test) for test in result.unexpectedSuccesses],
    }


def worker(
    index: int, config: dict[str, Any], tasks: Queue[str | None], results: Queue[tuple[Any, ...]]
) -> None:
    """Run classes from ``tasks`` until the sentinel, reporting each one."""
    cov = None
    if config["coverage"]:
        import coverage  # noqa: PLC0415 - optional, and absent on the runtime floor

        cov = coverage.Coverage(data_suffix=True)
        cov.start()
    try:
        units = discover(config["start"], config["top"], config["pattern"], config["shard"])
        results.put(("inventory", index, {unit: len(tests) for unit, tests in units.items()}))
        while (unit := tasks.get()) is not None:
            result = unittest.TestResult()
            result.buffer = config["buffer"]
            problems: list[tuple[str, str]] = []
            started = time.perf_counter()
            if unit not in units:
                problems.append((unit, "this worker's discovery did not find the class"))
            else:
                try:
                    # A fresh result makes this a top-level run, so TestSuite opens
                    # and closes the class and module fixtures itself.
                    unittest.TestSuite(units[unit])(result)
                except BaseException:  # noqa: BLE001 - report a unit, never lose it
                    problems.append((unit, traceback.format_exc()))
            summary = summarise(unit, result, time.perf_counter() - started)
            summary["errors"] += problems
            results.put(("unit", index, summary))
    except BaseException:  # noqa: BLE001 - a crashed worker is a reported error
        results.put(("crash", index, traceback.format_exc()))
    finally:
        if cov is not None:
            cov.stop()
            cov.save()
        results.put(("done", index))


def order_units(units: dict[str, list[unittest.TestCase]]) -> list[str]:
    """Largest class first, so the long ones start early and the queue balances."""
    return sorted(units, key=lambda unit: (-len(units[unit]), unit))


def report(total: dict[str, Any], elapsed: float, jobs: int) -> bool:
    """Print unittest's closing report to stderr and return the verdict."""
    out = sys.stderr
    out.write("\n")
    for flavour, key in (("ERROR", "errors"), ("FAIL", "failures")):
        for name, text in total[key]:
            out.write(f"{'=' * 70}\n{flavour}: {name}\n{'-' * 70}\n{text}\n")
    out.write(f"{'-' * 70}\nRan {total['run']} tests in {elapsed:.3f}s ({jobs} workers)\n\n")
    extras = [
        f"{label}={len(total[key])}"
        for label, key in (
            ("failures", "failures"),
            ("errors", "errors"),
            ("skipped", "skipped"),
            ("expected failures", "expected"),
            ("unexpected successes", "unexpected"),
        )
        if total[key]
    ]
    ok = not (total["failures"] or total["errors"] or total["unexpected"]) and total["run"] > 0
    out.write(("OK" if ok else "FAILED") + (f" ({', '.join(extras)})" if extras else "") + "\n")
    return ok


def absorb(
    message: tuple[Any, ...], total: dict[str, Any], expected: dict[str, int], seen: set[str]
) -> bool:
    """Fold one worker message into the totals; True when it says the worker is done."""
    kind = message[0]
    if kind == "unit":
        summary = message[2]
        seen.add(summary["unit"])
        total["durations"].append((summary["seconds"], summary["unit"]))
        for key in ("run", "failures", "errors", "skipped", "expected", "unexpected"):
            total[key] += summary[key]
        sys.stderr.write("F" if summary["failures"] or summary["errors"] else ".")
        sys.stderr.flush()
    elif kind == "inventory":
        found: dict[str, int] = message[2]
        for unit in sorted(set(expected) | set(found)):
            if expected.get(unit) != found.get(unit):
                total["errors"].append(
                    (
                        f"worker {message[1]} discovery",
                        (
                            f"{unit}: the parent found {expected.get(unit, 0)} tests and this "
                            f"worker found {found.get(unit, 0)}"
                        ),
                    )
                )
    elif kind == "crash":
        total["errors"].append((f"worker {message[1]}", message[2]))
    return bool(kind == "done")


def collect(
    results: Queue[tuple[Any, ...]], procs: list[Any], expected: dict[str, int]
) -> tuple[dict[str, Any], set[str]]:
    """Merge worker reports until every worker is done, or every worker is gone."""
    total: dict[str, Any] = {
        "run": 0,
        "failures": [],
        "errors": [],
        "skipped": [],
        "expected": [],
        "unexpected": [],
        "durations": [],
    }
    seen: set[str] = set()
    done = 0
    while done < len(procs):
        try:
            message = results.get(timeout=POLL_SECONDS)
        except queue.Empty:
            if not any(proc.is_alive() for proc in procs):
                break
            continue
        done += absorb(message, total, expected, seen)
    # A worker can finish between the last timeout and the liveness check;
    # whatever it sent is still on the queue, and is read rather than lost.
    while True:
        try:
            absorb(results.get_nowait(), total, expected, seen)
        except queue.Empty:
            break
    return total, seen


def run(
    start: str,
    top: str | None,
    pattern: str,
    jobs: int,
    *,
    coverage: bool,
    slowest: int = 0,
    shard: tuple[int, int] | None = None,
    buffer: bool = True,
) -> bool:
    """Discover, fan out across ``jobs`` workers, merge, report, return the verdict."""
    started = time.perf_counter()
    units = discover(start, top, pattern, shard)
    order = order_units(units)
    jobs = max(1, min(jobs, len(order)))
    context = multiprocessing.get_context("spawn")
    tasks: Queue[str | None] = context.Queue()
    results: Queue[tuple[Any, ...]] = context.Queue()
    for unit in order:
        tasks.put(unit)
    for _ in range(jobs):
        tasks.put(None)
    config = {
        "start": start,
        "top": top,
        "pattern": pattern,
        "coverage": coverage,
        "shard": shard,
        "buffer": buffer,
    }
    procs = [
        context.Process(target=worker, args=(index, config, tasks, results))
        for index in range(jobs)
    ]
    for proc in procs:
        proc.start()

    total, seen = collect(results, procs, {unit: len(tests) for unit, tests in units.items()})
    # Workers that died early leave tasks unread; without this the parent's
    # feeder thread waits at exit to flush them into a pipe nobody reads.
    tasks.cancel_join_thread()
    for proc in procs:
        proc.join(timeout=JOIN_SECONDS)
    total["errors"].extend(
        (unit, "the worker exited before reporting this class")
        for unit in order
        if unit not in seen
    )
    total["errors"].extend(
        (f"worker pid {proc.pid}", f"exit code {proc.exitcode}")
        for proc in procs
        if proc.exitcode not in (0, None)
    )
    if slowest:
        sys.stderr.write(f"\nSlowest {slowest} classes:\n")
        for seconds, unit in sorted(total["durations"], reverse=True)[:slowest]:
            sys.stderr.write(f"  {seconds:7.2f}s  {unit}\n")
    return report(total, time.perf_counter() - started, jobs)


def main(argv: list[str] | None = None) -> int:
    """Parse ``unittest discover``-style arguments and run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-s", "--start-directory", dest="start", default=".")
    parser.add_argument("-t", "--top-level-directory", dest="top", default=None)
    parser.add_argument("-p", "--pattern", default="test*.py")
    parser.add_argument(
        "-j", "--jobs", type=int, default=os.cpu_count() or 2, help="worker processes"
    )
    parser.add_argument("--coverage", action="store_true", help="record coverage in each worker")
    parser.add_argument(
        "--slowest", type=int, default=0, metavar="N", help="list the N slowest classes"
    )
    parser.add_argument(
        "--no-buffer",
        dest="buffer",
        action="store_false",
        help="print what tests write as they run, instead of only with a failure",
    )
    parser.add_argument(
        "--shard",
        type=parse_shard,
        default=None,
        metavar="K/N",
        help="run only leg K of N, balancing whole modules by measured cost",
    )
    args = parser.parse_args(argv)
    # Every worker inherits this, so no test can resolve Compass's state to the
    # developer's real ~/.compass. The dashboard suite already gets one from
    # tests/support.py; scripts/tests has no shared module, and a test there that
    # built a runtime (bench_collect's simulation, 2026-09-27) wrote fixture
    # sessions into the owner's real history store. Assigned rather than
    # defaulted, as support.py does: an exported COMPASS_HOME is the same leak.
    # HOME stays: test_abstention_claude deliberately refuses a HOME that is not
    # the account's own.
    state_home = tempfile.TemporaryDirectory(prefix="compass-runner-home-")
    os.environ["COMPASS_HOME"] = state_home.name
    if args.top:
        sys.path.insert(0, os.path.abspath(args.top))
    ok = run(
        args.start,
        args.top,
        args.pattern,
        args.jobs,
        coverage=args.coverage,
        slowest=args.slowest,
        shard=args.shard,
        buffer=args.buffer,
    )
    state_home.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
