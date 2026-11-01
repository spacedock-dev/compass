"""No prompt builder carries a stored reading's text, or the departures kept beside it.

A stored reading and its prior departures are shown to the reader and nowhere else. If a builder
sent them to a model, the next verdict would be drawn from the last one rather than from the
record, and nothing in the output would say so. The test seeds a real annotation store with two
marker strings, one in a standing reading and one in an earlier departure, then sends the reading
through each builder that reaches a model and asserts neither marker appears in what was sent.

Builders covered: `reading.produce` (asked and unasked, which share `build_prompt`),
`session_summary` (window and lede), `goal_find.build_prompt`, `live_monitor.build_prompt` and
`observer.CodexGoalModel`. The completeness guard at the end fails when a new module starts a
model call, so the next caller is added here rather than missed.

Deliberately not covered:
- `correction.compose` builds the text the reader copies into the agent's session, and it carries
  the stored `detail` by owner ruling (2026-10-20, quoted in its module docstring). No model is
  sent it.
- The static system prompts and `observer._queued_prompt_text` take no stored input.
- The Update summary prompt carries prior phase titles. Those are a stored summary's prose, kept by
  design, and this test seeds no summary store. The tail lede variant is reached only through
  `session_summary.update`, so it is not covered here.

Every message here is placeholder prose.
"""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import (
    aggregate,
    goal_find,
    live_estimate,
    live_monitor,
    observer,
    reading,
    session_source,
    session_summary,
)
from compass_runtime import annotations as annotation_store
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from . import test_live_monitor as live
from .support import make_config
from .test_prior_departures import (
    DEPARTED,
    GOAL,
    GOAL_DEPARTED,
    LINE_1,
    LINE_2,
    ON_THE_AGENTS_WORD,
    _assessment,
)
from .test_session_summary import Replies
from .test_session_summary import entry as summary_entry

if TYPE_CHECKING:
    from collections.abc import Sequence

MARK_STORED = "ZQMARK-STORED-READING-41c7"
MARK_EARLIER = "ZQMARK-EARLIER-DEPARTURE-9b2e"
MARKERS = (MARK_STORED, MARK_EARLIER)

# The modules whose code starts a model call. Each one has a test above that reaches it.
COVERED_CALLERS = frozenset({"observer.py", "reading.py", "summary_jobs.py", "live_monitor.py"})

FIRST_READ = 100.0
SECOND_READ = 200.0
REVISION_AT = 10.0
LAST_ACTIVITY = 300.0
NOW = 500.0
SID = {"harness": "claude", "sid": "s1"}


def _seed(config: Any) -> tuple[Any, Any, dict[str, Any]]:
    """Two readings through the real store: the first departs on line 2, the second rests it.

    The first reading's departure is the one the second reading no longer finds, so it is kept as
    a prior departure. The second reading's standing goal departure is the stored reading.
    """
    state = build_runtime_state(config, started=1.0)
    annotation_store.annotate(
        config, state, "claude", "s1", goal=GOAL, lines=[LINE_1, LINE_2], now=REVISION_AT
    )
    annotation_store.record_reading(
        config,
        state,
        "claude",
        "s1",
        assessment=_assessment(  # type: ignore[arg-type]
            FIRST_READ,
            revision=1,
            line_2={**DEPARTED, "detail": f"{MARK_EARLIER} A stylesheet was written."},
        ),
    )
    annotation_store.record_reading(
        config,
        state,
        "claude",
        "s1",
        assessment=_assessment(  # type: ignore[arg-type]
            SECOND_READ,
            revision=1,
            line_2=ON_THE_AGENTS_WORD,
            goal={**GOAL_DEPARTED, "detail": f"{MARK_STORED} It built a different page."},
        ),
    )
    entries = annotation_store.active(config, state)
    found = annotation_store.find(entries, "claude", "s1")
    assert found is not None
    row: dict[str, Any] = {
        **SID,
        "state": "working",
        "ended_at": None,
        "last_activity": LAST_ACTIVITY,
    }
    rows: list[Any] = [row]
    aggregate._attach_annotations(rows, entries)
    return state, found, row


def _check_seed(testcase: unittest.TestCase, entry: dict[str, Any], row: dict[str, Any]) -> None:
    """A seed that was silently dropped would make every assertion after it pass for nothing."""
    testcase.assertIn(MARK_STORED, json.dumps(row["annotation_assessment"]))
    testcase.assertIn(MARK_EARLIER, json.dumps(row["annotation_prior_departures"]))
    # The revisions a builder legitimately reads are the typed words only.
    testcase.assertNotIn(MARK_STORED, json.dumps(entry["revisions"]))


def _assert_clean(testcase: unittest.TestCase, prompts: Sequence[str], label: str) -> None:
    """Every prompt sent, not the first alone: a builder may send more than one."""
    testcase.assertTrue(prompts, f"{label}: no prompt was sent, so nothing was checked")
    for prompt in prompts:
        for marker in MARKERS:
            testcase.assertNotIn(marker, prompt, f"{label} sent a stored reading's text")


def _person(fact_id: str, at: float, words: str) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "type": "user_message",
        "summary": f"{fact_id} opens",
        reading.WORDS_FIELD: words,
        "at": at,
        "source_session": SID,
        "evidence": {"source": "timestamped non-meta user-role record", "confidence": "exact"},
    }


def _agent(fact_id: str, at: float, title: str) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "type": reading.AGENT_MESSAGE_TYPE,
        "summary": title,
        reading.AGENT_WORDS_FIELD: f"{title} More words follow the title.",
        "at": at,
        "source_session": SID,
        "evidence": {
            "source": "timestamped top-level assistant text record",
            "confidence": "exact",
        },
    }


def _check(fact_id: str, at: float, result: str) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "type": reading.TOOL_REPORT_TYPE,
        "subject": reading.CHECK_SUBJECT,
        "result": result,
        "result_source": "flag",
        "summary": "python3 -m pytest tests/test_retry.py",
        "at": at,
        "evidence": {"source": "Claude Bash call and paired result", "confidence": "exact"},
        "source_session": SID,
        "branch": {**SID, "record_id": f"call-{fact_id}"},
    }


class _Capture:
    """A model that records each prompt and answers with an empty object."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        del output_cap_bytes
        self.prompts.append(prompt)
        return "{}", "ok"


class _Seeded(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        self.state, self.entry, self.row = _seed(self.config)
        _check_seed(self, self.entry, self.row)

    def facts(self) -> list[dict[str, Any]]:
        return [
            _person("p1", 250.0, f"{GOAL}. Please add a retry to the upload client."),
            _agent("a1", 260.0, "I added the retry."),
            _check("c1", 270.0, "failed"),
        ]


class WhenAReaderHasAStoredReadingAndEarlierDepartures(_Seeded):
    def test_the_next_reading_the_reader_presses_sends_neither_the_stored_reading_nor_the_earlier_departures(
        self,
    ) -> None:
        capture = _Capture()
        reading.produce(
            self.config,
            self.row,
            self.entry["revisions"],
            self.facts(),
            now=NOW,
            stamp_text="read at 10:00",
            model=capture,
            read_lines=True,
            read_agent_words=True,
        )
        self.assertEqual(1, len(capture.prompts))
        self.assertIn(GOAL, capture.prompts[0])
        _assert_clean(self, capture.prompts, "the asked reading")

    def test_the_unasked_check_sends_neither(self) -> None:
        capture = _Capture()
        reading.produce(
            self.config,
            self.row,
            self.entry["revisions"],
            self.facts(),
            now=NOW,
            stamp_text="read at 10:00",
            model=capture,
            failures_only=True,
            read_lines=False,
            read_agent_words=False,
        )
        self.assertEqual(1, len(capture.prompts))
        _assert_clean(self, capture.prompts, "the unasked check")

    # The four builders below never receive the row, the entry or the `annotation_*` fields. They
    # take text, facts or entries only, so these tests pass by construction. They are not coverage
    # of the store; the feeders that would hand them stored text are outside this test.

    def test_find_goal_sends_neither(self) -> None:
        prompts = goal_find.prompts_from_facts(
            [
                {
                    "fact_id": "f1",
                    "type": "user_message",
                    "at": 250.0,
                    "source_session": SID,
                    reading.WORDS_FIELD: f"{GOAL}. Also keep the tests passing.",
                }
            ],
            ordinal={"f1": 1}.get,
        )
        capture = _Capture()
        goal_find.find(prompts, capture, goal_cap=240)
        self.assertEqual(1, len(capture.prompts))
        _assert_clean(self, capture.prompts, "the goal finder")

    def test_the_session_summary_sends_neither(self) -> None:
        model = Replies()
        session_summary.summarize(
            [
                summary_entry(1, words=f"{GOAL}. Keep the stylesheets as they are."),
                summary_entry(2, "agent", words="The queue page now lists pending jobs."),
            ],
            session_source.SourceCoverage(True, None, 0, 100, (), "read", "read"),
            "claude",
            config=build_runtime_config(
                environ={"HOME": "/synthetic"},
                platform_name="linux",
                os_name="posix",
                launcher_path=Path("/synthetic/server.py"),
            ),
            model=model,
            clock=lambda: 0.0,
        )
        self.assertGreaterEqual(len(model.prompts), 2, "a window prompt and a lede prompt")
        _assert_clean(self, model.prompts, "the session summary")

    def test_the_goal_line_summary_sends_neither(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            config = dataclasses.replace(
                make_config(), observer_model_enabled=True, state_dir=Path(state_dir)
            )
            for child in (False, True):
                with self.subTest(child_assignment=child):
                    sent: list[str] = []
                    caller = observer.CodexGoalModel(
                        config,
                        runner=_codex_runner(sent),
                        binary_resolver=mock.Mock(return_value="/usr/bin/codex"),
                        child_assignment=child,
                        consent=True,
                        session_key="codex:one",
                    )
                    caller(f"{GOAL}. The transcript excerpt says the same.", "stage")
                    self.assertEqual(1, len(sent))
                    _assert_clean(self, sent, "the goal-line summary")


def _codex_runner(sent: list[str]) -> Any:
    def runner(command: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        sent.append(kwargs["input"])
        return subprocess.CompletedProcess(command, 0, "", "")

    return runner


class WhenTheLiveMonitorChecksAStoredReading(live.Case):
    def setUp(self) -> None:
        super().setUp()
        # live.Case's config keeps the store under a path that does not exist; point the store at
        # this test's own directory, or the seed writes outside it and is lost.
        self.config = dataclasses.replace(self.config, state_home=str(self.home))
        self.state, self.entry, self.row = _seed(self.config)
        _check_seed(self, self.entry, self.row)

    def test_the_live_monitor_sends_neither(self) -> None:
        # Built the way `http_api._lease_inputs` builds the intent from the published row.
        saved = live_estimate.saved_intent(self.row)
        intent = " ".join(part for part in (saved.goal, *saved.lines) if part.strip())
        self.begin()
        live_monitor.tick(
            self.config,
            live.KEY,
            now=live.NOW,
            transcript_path=str(self.transcript),
            facts=live.facts(sid="one"),
            intent=intent,
            estimate=live.OK_ESTIMATE,
            runner=self.runner,
            binary_resolver=lambda _name: "/synthetic/bin/claude",
            ended=False,
        )
        self.assertEqual(1, len(self.runner.calls))
        sent = [self.runner.calls[0][1]["input"]]
        self.assertIn(GOAL, sent[0])
        _assert_clean(self, sent, "the live monitor")


class WhenANewModelCallerIsAdded(unittest.TestCase):
    def test_every_module_that_starts_a_model_is_one_this_test_covers(self) -> None:
        runtime = Path(reading.__file__).resolve().parent
        callers: set[str] = set()
        for path in sorted(runtime.glob("*.py")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if re.search(r"\b(claude_exec|codex_exec|prepare_claude_exec)\(", line) and not (
                    re.match(r"\s*def ", line)
                ):
                    callers.add(path.name)
                    break
        self.assertEqual(
            COVERED_CALLERS,
            callers,
            "A module now starts a model call. Add a test above that sends its prompt a stored "
            "reading, then add the module to COVERED_CALLERS.",
        )
