"""The tool report's cached listing against a full re-listing, step by step (DRC-5062).

The live estimate asks `_ToolReportTally.entries` after every call of its window, so the tally
keeps what it can between two asks: the entry built for each check, which run of each history is
latest, and when another call last changed files. Every one of those is a cache whose miss is slow
and whose stale hit is a wrong page. The test here holds the cached tally to an oracle that keeps
nothing between asks and reads every write afresh, over seeded random sessions, at every step.
"""

from __future__ import annotations

import random
import unittest
from typing import Any
from unittest import mock

from compass_runtime import ci_read, live_estimate
from compass_runtime import project_context as pc

SESSION_DIR = "/work/proj"
SID = "s1"

# Check lines. The `-m` ones name closed selectors (`_check_coverage`), so a later pass of a wider
# one takes in an earlier failure of a narrower one and the failure's history joins the pass's.
_CHECKS = (
    "python -m pytest tests/test_a.py::test_x0",
    "python -m pytest tests/test_a.py::test_x1",
    "python -m pytest tests/test_a.py",
    "python -m pytest tests/test_a.py tests/test_b.py",
    "python3 -m unittest tests.test_c.T.test_y",
    "python3 -m unittest tests.test_c",
    "pytest tests/test_a.py::test_x2",
    "pytest tests/test_b.py -k foo",
    "pytest tests",
    "pytest",
    "ruff check .",
    "mypy",
    "cd sub && pytest tests",
    # One check twice in a call: two runs at one time, which only call order separates, and the
    # call's status speaks for the last of them alone.
    "pytest tests; pytest tests",
    "mypy && mypy",
)
_COMMANDS = (
    "npm run build",
    "make lint",
    "git status",
    "ls src",
    "gh pr checks 12",
    "gh pr checks",
)
_FIXERS = (
    "black .",
    "ruff format .",
    "pytest tests && black .",
    "pytest tests/test_a.py > out.txt",
)
_REDIRECTS = ("echo x > src/gen.py", "echo x > /tmp/gen.py")
_PASSED = "3 passed in 0.1s"
_FAILED = "Exit code 1\n1 failed, 2 passed"


class _Binding:
    """A CI binding that binds a poll to a pull request this session created, and nothing else."""

    @staticmethod
    def bound(poll: ci_read.Poll, _cwd: str, _session_dir: str, created: Any) -> bool:
        return any(number == poll.number for _repository, number in created)


class FullListing(pc._ToolReportTally):
    """The oracle: every listing built from nothing, as the tally listed before it cached.

    No entry outlives the ranking that built it, the latest run of a history is the plain `max`
    over every run, and whether a write followed a run is the scan over every write.
    """

    def _ranked(self, histories: Any) -> list[dict[str, Any]]:
        self._entry_cache.clear()
        return super()._ranked(histories)

    def _latest_index(self, _key: str, history: list[dict[str, Any]]) -> int:
        return self._latest(history)

    def _check_entry(
        self, history: list[dict[str, Any]], own: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        return self._with_scanned_writes(super()._check_entry(history, own), history)

    def _command_entry(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        return self._with_scanned_writes(super()._command_entry(history), history)

    def _forget_check(self, identity: str) -> None:
        # The drop as it was before the listing kept anything, so the oracle shares no code with
        # the cache it checks.
        del self.runs[identity]
        self._entry_cache.pop(identity, None)

    def _with_scanned_writes(
        self, entry: dict[str, Any], history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        latest = history[self._latest(history)]
        entry["before_last_change"] = bool(latest["fixes"]) or any(
            at >= latest["at"] and call_id != latest["record_id"]
            for at, call_id in self.write_calls
        )
        return entry


class _Session:
    """One seeded random session, added to a cached tally and an oracle in step."""

    def __init__(self, seed: int, edges: pc._Edges) -> None:
        self.rnd = random.Random(seed)
        self.edges = edges
        self.results: dict[str, pc._Result] = {}
        self.ends: dict[str, float] = {}
        self.cached = self._tally(pc._ToolReportTally)
        self.oracle = self._tally(FullListing)
        self.effects: list[tuple[str, int] | None] = []
        self.at = 1000.0
        self.n = 0
        self.assertion = True
        self.seen: dict[str, int] = dict.fromkeys(
            ("merged", "bound", "unbound", "launch", "checkpoint", "dropped", "late"), 0
        )

    def _tally(self, kind: type[pc._ToolReportTally]) -> pc._ToolReportTally:
        tally = kind(self.results, SESSION_DIR, None, _Binding(), self.edges)  # type: ignore[arg-type]
        tally.change_ends = self.ends
        return tally

    def _result(self, call_id: str, text: str, *, error: bool = False, **extra: Any) -> None:
        # A result can arrive well after later calls began: it then decides which run is latest.
        # A delay of 0 or a whole second can tie a result with a later call's time.
        delay = self.rnd.choice((0.0, 0.2, 1.0, 5.0, 30.0))
        self.seen["late"] += delay > 2
        block = {"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": error}
        self.results[call_id] = pc._Result(block, self.at + delay, **extra)
        if self.edges is pc._CODEX_EDGES:
            self.ends[call_id] = self.at + delay

    def _shell(self, call_id: str, command: str) -> tuple[str, dict[str, Any]]:
        roll = self.rnd.random()
        if roll < 0.12:
            pass  # no result recorded yet
        elif roll < 0.17:
            self._result(call_id, "The user doesn't want to proceed", error=True)  # never ran
        elif roll < 0.47:
            self._result(call_id, _FAILED, error=True)
        elif roll < 0.52:
            self._result(call_id, "0 passed in 0.01s")
        else:
            self._result(call_id, _PASSED)
        return "Bash", {"command": command}

    def _write(self, call_id: str) -> tuple[str, dict[str, Any]]:
        codex = self.edges is pc._CODEX_EDGES
        where = self.rnd.choice(
            (f"{SESSION_DIR}/src/f{self.rnd.randrange(5)}.py", "/elsewhere/y.py")
        )
        tool_input: dict[str, Any] = {"file_path": where}
        if codex and self.rnd.random() < 0.2:
            tool_input["removed"] = "deleted"
        if self.rnd.random() < 0.9:
            self._result(call_id, "ok")
        return (pc.CODEX_PATCH_TOOL if codex else "Write"), tool_input

    def _pull_request(self, call_id: str) -> tuple[str, dict[str, Any]]:
        number = self.rnd.choice((12, 13))
        url = f"https://github.com/acme/app/pull/{number}"
        meta = {"gitOperation": {"pr": {"url": url, "action": "created", "number": number}}}
        self._result(call_id, url, meta=meta)
        return "Bash", {"command": f"gh pr create --title t{number}"}

    def _launch(self, call_id: str) -> tuple[str, dict[str, Any]]:
        self.seen["launch"] += 1
        if self.rnd.random() < 0.6:
            self._result(call_id, "")
            return "Bash", {"command": self.rnd.choice(_CHECKS[:6]) + " &"}
        self._result(call_id, "launched")
        return "Agent", {"prompt": "look", "run_in_background": True}

    def call(self) -> tuple[float, str, str, str, dict[str, Any], str]:
        rnd = self.rnd
        self.at += rnd.choice((0.0, 1.0, 1.0, 2.0))  # two calls can share a time
        self.n += 1
        call_id = f"c{self.n}"
        worker = "agent-1" if rnd.random() < 0.1 else ""
        roll = rnd.random()
        if roll < 0.14:
            name, tool_input = self._write(call_id)
        elif roll < 0.17 and self.edges is pc._CODEX_EDGES:
            name, tool_input = pc.CODEX_UNREAD_TOOL, {}
            self.ends[call_id] = self.at + rnd.choice((0.0, 3.0))
        elif roll < 0.21:
            name, tool_input = self._shell(call_id, rnd.choice(_FIXERS))
        elif roll < 0.25:
            name, tool_input = self._shell(call_id, rnd.choice(_REDIRECTS))
        elif roll < 0.35:
            name, tool_input = self._shell(call_id, rnd.choice(_COMMANDS))
        elif roll < 0.40:
            name, tool_input = self._launch(call_id)
        elif roll < 0.43:
            name, tool_input = self._pull_request(call_id)
        elif roll < 0.55:
            # A check that runs once: the only kind of head a shifted window may drop.
            name, tool_input = self._shell(call_id, f"pytest tests/test_u.py::test_{self.n}")
        else:
            name, tool_input = self._shell(call_id, rnd.choice(_CHECKS))
        return (self.at, SESSION_DIR, call_id, name, tool_input, worker)

    def add(self, call: tuple[float, str, str, str, dict[str, Any], str]) -> None:
        before = live_estimate._head_state(self.cached)
        self.cached.add(*call)
        self.oracle.add(*call)
        self.effects.append(live_estimate._safe_head_effect(self.cached, before, call[3]))

    def checkpoint(self) -> None:
        """Both tallies replaced by checkpoint copies, as the live estimate carries one between two
        reads, and sometimes a head of safe passes dropped from both and the horizon moved."""
        self.seen["checkpoint"] += 1
        self.cached = live_estimate._checkpoint(self.cached)
        oracle = live_estimate._checkpoint(self.oracle)
        oracle.__class__ = FullListing
        self.oracle = oracle
        for tally in (self.cached, self.oracle):
            tally.results = self.results
            tally.change_ends = self.ends
            tally.edges = self.edges
            tally.ci_binding = _Binding()  # type: ignore[assignment]
        if self.effects and self.rnd.random() < 0.6:
            head = self.effects[: self.rnd.choice((1, 1, 2, len(self.effects)))]
            dropped = live_estimate._drop_safe_head(self.cached, head)
            self.assertion = dropped == live_estimate._drop_safe_head(self.oracle, head)
            self.seen["dropped"] += dropped
            self.effects = self.effects[len(head) :] if dropped else []
        if self.rnd.random() < 0.3:
            # A moved horizon empties the entry cache (`_shifted_checkpoint`).
            horizon = self.at - self.rnd.choice((1.0, 10.0))
            self.cached._entry_cache.clear()
            for tally in (self.cached, self.oracle):
                tally.reads_from = horizon

    def note(self) -> None:
        runs = self.cached.runs
        foreground = sum(not all(run["background"] for run in history) for history in runs.values())
        self.seen["merged"] += len(self.cached._histories()) < foreground
        for row in self.cached.entries(SID):
            if row["subject"] == pc.CI_SUBJECT:
                self.seen["bound"] += 1
            elif row.get("result_reason") == pc.CI_POLL_UNBOUND:
                self.seen["unbound"] += 1


class CachedListingMatchesAFullRelistingTest(unittest.TestCase):
    """At every step of a seeded random session, the cached `entries` and the scan counters equal
    the oracle's, and so do a capped listing's positions and the press's passes and writes."""

    # 24 seeds a harness, split by harness so the runner schedules the two halves apart: 40 cost
    # 14.7 s on a hosted runner as one method, and a review fuzz of 300 more seeds found nothing
    # these miss. Every state below is reached on both harnesses except a bound CI poll on Codex,
    # which this generator gives no pull request to bind to.
    SEEDS = range(24)
    CALLS = 90

    def replay(self, seed: int, edges: pc._Edges) -> dict[str, int]:
        session = _Session(seed, edges)
        for step in range(self.CALLS):
            session.add(session.call())
            if session.rnd.random() < 0.06:
                session.checkpoint()
                self.assertTrue(session.assertion, (seed, step, "drop"))
            where = (edges.harness, seed, step)
            self.assertEqual(session.oracle.entries(SID), session.cached.entries(SID), where)
            self.assertEqual(session.oracle.scan, session.cached.scan, where)
            if step % 7 == 0:
                cap = session.rnd.choice((2, 5))
                self.assertEqual(session.oracle.listing(cap), session.cached.listing(cap), where)
                self.assertEqual(
                    session.oracle.passes_and_writes(), session.cached.passes_and_writes(), where
                )
                session.note()
                session.oracle.entries(SID)  # keeps the two scans counting in step
        return session.seen

    def assert_every_step_matches(
        self, edges: pc._Edges, unreachable: tuple[str, ...] = ()
    ) -> None:
        seen: dict[str, int] = {}
        for seed in self.SEEDS:
            for key, count in self.replay(seed, edges).items():
                seen[key] = seen.get(key, 0) + count
        # The generator reaches the states a stale cache would get wrong, or the comparison above
        # proves nothing about them.
        for key, count in seen.items():
            if key in unreachable:
                continue
            with self.subTest(state=key):
                self.assertGreater(count, 0, seen)

    def test_every_claude_code_step_lists_what_a_full_relisting_lists(self) -> None:
        self.assert_every_step_matches(pc._CLAUDE_EDGES)

    def test_every_codex_step_lists_what_a_full_relisting_lists(self) -> None:
        self.assert_every_step_matches(pc._CODEX_EDGES, unreachable=("bound",))


class TheListingRebuildsOnlyWhatChangedTest(unittest.TestCase):
    """The work a listing does after one call is the work that call made, not the session's."""

    def tally(self, checks: int) -> pc._ToolReportTally:
        results: dict[str, pc._Result] = {}
        tally = pc._ToolReportTally(results, SESSION_DIR)
        for i in range(checks):
            call_id = f"c{i}"
            block = {"type": "tool_result", "tool_use_id": call_id, "content": _PASSED}
            results[call_id] = pc._Result(block, 1000.0 + i)
            tally.add(1000.0 + i, SESSION_DIR, call_id, "Bash", {"command": f"pytest t.py::t{i}"})
        tally.entries(SID)
        return tally

    def test_one_added_check_builds_one_entry(self) -> None:
        tally = self.tally(40)
        block = {"type": "tool_result", "tool_use_id": "new", "content": _PASSED}
        tally.results["new"] = pc._Result(block, 2000.0)
        tally.add(2000.0, SESSION_DIR, "new", "Bash", {"command": "pytest t.py::new"})
        with mock.patch.object(tally, "_check_entry", wraps=tally._check_entry) as built:
            tally.entries(SID)
        self.assertEqual(1, built.call_count)

    def test_an_unchanged_tally_finds_no_latest_run_again(self) -> None:
        tally = self.tally(40)
        with mock.patch.object(pc, "_evidence_at", wraps=pc._evidence_at) as read:
            tally.entries(SID)
        self.assertEqual(0, read.call_count)

    def test_a_checkpoint_keeps_the_entries_and_latest_runs_it_copied(self) -> None:
        saved = live_estimate._checkpoint(self.tally(40))
        with (
            mock.patch.object(saved, "_check_entry", wraps=saved._check_entry) as built,
            mock.patch.object(pc, "_evidence_at", wraps=pc._evidence_at) as read,
        ):
            saved.entries(SID)
        self.assertEqual((0, 0), (built.call_count, read.call_count))


if __name__ == "__main__":
    unittest.main()
