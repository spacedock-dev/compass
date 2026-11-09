"""The drift-level case tool: what it may keep, what it may commit, and what it refuses.

DRC-4692 measures the two level functions against levels the owner marks before any rule runs. The
cases hold facts drawn from recorded Claude Code sessions and stay under `~/.compass`; only the
marks' digest and the scored expectations reach the repository.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
import unittest.mock
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import levels_cases

START = dt.datetime(2026, 9, 24, 3, 0, tzinfo=dt.UTC)
SID = "74c70a30-fcf5-4dbf-9c59-3e28031a0549"
# Node's summary and failure glyphs, written as escapes so review can read them.
INFO = "\u2139"
CROSS = "\u2716"
GOAL = "Build a tic-tac-toe game in web/ that a phone can play"


def _stamp(seconds: int) -> str:
    return (START + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _epoch(seconds: int) -> float:
    return (START + dt.timedelta(seconds=seconds)).timestamp()


class Transcript:
    """Just enough of Claude Code's recorded shapes for layer 1's scan."""

    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.rows: list[dict[str, Any]] = []
        self.calls = 0
        self._row("user", 0, [{"type": "text", "text": "Build the game"}])

    def _row(self, kind: str, at: int, content: list[dict[str, Any]]) -> None:
        self.rows.append(
            {
                "type": kind,
                "isSidechain": False,
                "cwd": self.cwd,
                "sessionId": SID,
                "timestamp": _stamp(at),
                "message": {"role": kind, "content": content},
            }
        )

    def bash(self, at: int, command: str, output: str, *, failed: bool) -> None:
        self.calls += 1
        call_id = f"toolu_{self.calls:03d}"
        tool = {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}
        self._row("assistant", at, [tool])
        text = f"Exit code 1\n{output}" if failed else output
        result = {
            "type": "tool_result",
            "tool_use_id": call_id,
            "content": text,
            "is_error": failed,
        }
        self._row("user", at + 1, [result])

    def write(self, at: int, path: str) -> None:
        self.calls += 1
        call_id = f"toolu_{self.calls:03d}"
        tool = {
            "type": "tool_use",
            "id": call_id,
            "name": "Write",
            "input": {"file_path": path, "content": "SECRET BODY"},
        }
        self._row("assistant", at, [tool])
        result = {"type": "tool_result", "tool_use_id": call_id, "content": "File created"}
        self._row("user", at + 1, [result])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r) for r in self.rows) + "\n", encoding="utf-8")


class Answers:
    """A marker at the keyboard: each call returns the next reply, and records the prompt."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise EOFError
        return self.replies.pop(0)


def _git(repo: Path, *args: str) -> str:
    """Git in the throwaway repository, isolated from the operator's hooks and signing."""
    done = subprocess.run(
        [  # noqa: S607 - git on PATH, as the tool itself uses it
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


def a_reading(read_at: float, **criteria: dict[str, Any]) -> dict[str, Any]:
    """A stored reading in the store's own shape, as `annotations._assessment` admits it."""
    return {
        "revision_read": 1,
        "revision_read_at": read_at - 600,
        "window_start": None,
        "read_at": read_at,
        "stamp": "03:10",
        "cutoff": "",
        "scope": "mid-flight",
        "scope_text": "",
        "ended_at_read": None,
        "evidence_through": None,
        "criteria": {
            name: {"cites": [], "detail": "", "clause": "", "why": "", **row}
            for name, row in {"goal": {}, **criteria}.items()
        },
    }


class CaseToolTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home" / ".compass"
        self.repo = self.root / "repo"
        (self.repo / "docs" / "drift-levels").mkdir(parents=True)
        _git(self.repo, "init", "-q")
        (self.repo / "README.md").write_text("repo\n", encoding="utf-8")
        _git(self.repo, "add", "README.md")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.digest_path = self.repo / "docs" / "drift-levels" / "marks-digest.json"
        self.results_path = self.repo / "docs" / "drift-levels" / "results.json"
        self.cwd = str(self.root / "work" / "ttt")
        self.transcript_path = self.root / "claude" / "projects" / "-work-ttt" / f"{SID}.jsonl"
        session = Transcript(self.cwd)
        session.write(10, os.path.join(self.cwd, "web", "index.html"))
        session.bash(20, "node --test", f"{CROSS} draws a board\n{INFO} fail 1", failed=True)
        # The second turn DRC-4673 gave it: a later passing run.
        session.bash(600, "node --test", f"{INFO} pass 3\n{INFO} fail 0", failed=False)
        session.save(self.transcript_path)
        self.out: list[str] = []

    def say(self, *args: Any, **_kwargs: Any) -> None:
        self.out.append(" ".join(map(str, args)))

    def spec(self, *cases: dict[str, Any]) -> Path:
        path = self.home / "drift-levels" / "spec.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"v": 1, "cases": list(cases)}), encoding="utf-8")
        return path

    def case(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "kind": "failed-check",
            "transcript": str(self.transcript_path),
            "until": _epoch(300),
            "intent": {"saved": True, "goal": GOAL, "lines": ["node --test passes"]},
            "unsettled_directions": 0,
        }
        body.update(overrides)
        return body

    def build(self, *cases: dict[str, Any]) -> int:
        return levels_cases.build(
            self.spec(*cases), home=str(self.home), repo_root=str(self.repo), say=self.say
        )

    def cases(self) -> list[dict[str, Any]]:
        body = json.loads((self.home / "drift-levels" / "cases.json").read_text(encoding="utf-8"))
        return list(body["cases"])

    def marks(self) -> dict[str, Any]:
        path = self.home / "drift-levels" / "marks.json"
        return dict(json.loads(path.read_text(encoding="utf-8"))["marks"])

    def mark(self, answers: Answers) -> int:
        return levels_cases.mark(
            home=str(self.home),
            digest_path=str(self.digest_path),
            results_path=str(self.results_path),
            repo_root=str(self.repo),
            ask=answers,
            say=self.say,
        )

    def commit_digest(self) -> None:
        _git(self.repo, "add", str(self.digest_path))
        _git(self.repo, "commit", "-q", "-m", "marks digest")

    def attach(self, readings: dict[str, Any]) -> int:
        path = self.home / "drift-levels" / "readings-spec.json"
        path.write_text(json.dumps({"v": 1, "readings": readings}), encoding="utf-8")
        return levels_cases.attach_readings(
            path,
            home=str(self.home),
            repo_root=str(self.repo),
            digest_path=str(self.digest_path),
            now=time.time() + 120,
            say=self.say,
        )

    def score(self) -> int:
        return levels_cases.score(
            home=str(self.home),
            repo_root=str(self.repo),
            digest_path=str(self.digest_path),
            results_path=str(self.results_path),
            now=time.time() + 300,
            say=self.say,
        )

    def marked(self, *replies: str) -> str:
        """Build one failed-check case, mark it, commit the digest; the case id."""
        self.build(self.case())
        self.mark(Answers(*replies))
        self.commit_digest()
        return str(self.cases()[0]["id"])

    def results(self) -> dict[str, Any]:
        return dict(json.loads(self.results_path.read_text(encoding="utf-8")))


class BuildTest(CaseToolTestCase):
    def test_a_case_is_frozen_at_its_cut(self) -> None:
        # 74c70a30 now ends passing; its failed-check case is cut before the second turn.
        self.assertEqual(self.build(self.case()), 0)
        (frozen,) = self.cases()
        checks = [f for f in frozen["facts"] if f.get("subject") == "check"]
        self.assertEqual([f["result"] for f in checks], ["failed"])
        self.assertEqual(frozen["scan"]["failed"], 1)
        self.assertEqual(frozen["captured_at"], _epoch(300))

    def test_without_a_cut_the_later_pass_is_the_latest_run(self) -> None:
        self.assertEqual(self.build(self.case(until=None, kind="other")), 0)
        (frozen,) = self.cases()
        self.assertEqual(frozen["scan"]["passed"], 1)
        self.assertEqual(frozen["scan"]["failed"], 0)

    def test_the_intent_is_kept_as_a_separate_yardstick(self) -> None:
        self.build(self.case())
        (frozen,) = self.cases()
        self.assertEqual(
            frozen["intent"], {"saved": True, "goal": GOAL, "lines": ["node --test passes"]}
        )
        self.assertEqual(frozen["unsettled_directions"], 0)

    def test_the_working_directory_is_frozen_for_the_folder_rule(self) -> None:
        self.build(self.case())
        self.assertEqual(self.cases()[0]["cwd"], self.cwd)

    def test_no_file_content_is_frozen(self) -> None:
        self.build(self.case())
        raw = (self.home / "drift-levels" / "cases.json").read_text(encoding="utf-8")
        self.assertNotIn("SECRET BODY", raw)

    def test_the_cases_never_land_in_the_repository(self) -> None:
        code = levels_cases.build(
            self.spec(self.case()),
            home=str(self.repo / ".compass"),
            repo_root=str(self.repo),
            say=self.say,
        )
        self.assertEqual(code, 2)
        self.assertFalse((self.repo / ".compass" / "drift-levels" / "cases.json").exists())

    def test_a_case_without_its_later_directions_is_refused_not_defaulted(self) -> None:
        body = self.case()
        del body["unsettled_directions"]
        self.assertEqual(self.build(body), 1)
        self.assertFalse((self.home / "drift-levels" / "cases.json").exists())

    def test_a_case_without_an_intent_is_refused(self) -> None:
        body = self.case()
        del body["intent"]
        self.assertEqual(self.build(body), 1)

    def test_a_kind_outside_the_closed_set_is_refused(self) -> None:
        self.assertEqual(self.build(self.case(kind="Failed check")), 1)

    def test_a_reading_in_the_spec_is_refused_because_marks_come_first(self) -> None:
        # T1: a case built with its reading lets the reading shape the key.
        self.assertEqual(self.build(self.case(reading=a_reading(1.0))), 1)
        self.assertFalse((self.home / "drift-levels" / "cases.json").exists())

    def test_the_same_session_under_two_kinds_is_two_cases(self) -> None:
        self.build(self.case(), self.case(kind="intent-names-no-folder"))
        self.assertEqual(len({c["id"] for c in self.cases()}), 2)

    def test_a_rebuild_that_would_orphan_marks_is_refused(self) -> None:
        self.build(self.case())
        self.mark(Answers("h", "h"))
        self.assertEqual(self.build(self.case(kind="other")), 1)


class MarkTest(CaseToolTestCase):
    def test_the_tool_refuses_to_guess_and_has_no_default(self) -> None:
        self.build(self.case())
        answers = Answers("", "maybe", "h", "", "h")
        self.assertEqual(self.mark(answers), 0)
        # Replies that were not a level were asked again, not defaulted.
        self.assertEqual(len(answers.prompts), 5)
        self.assertEqual(list(self.marks().values()), [{"live": "high", "analysis": "high"}])

    def test_stopping_keeps_nothing_it_was_not_told(self) -> None:
        self.build(self.case(), self.case(kind="other", until=None))
        self.mark(Answers("h", "h", "q"))
        self.assertEqual(len(self.marks()), 1)

    def test_both_levels_are_asked_for_every_case_with_an_outcome_line(self) -> None:
        # T1: the analysis mark is asked from the evidence and intent, with no reading in hand.
        self.build(self.case())
        answers = Answers("h", "x")
        self.mark(answers)
        self.assertEqual(list(self.marks().values()), [{"live": "high", "analysis": "not_enough"}])
        self.assertEqual(len(answers.prompts), 2)

    def test_no_outcome_line_means_no_analysis_question(self) -> None:
        intent = {"saved": True, "goal": GOAL, "lines": []}
        self.build(self.case(intent=intent))
        answers = Answers("x")
        self.mark(answers)
        self.assertEqual(list(self.marks().values()), [{"live": "not_enough", "analysis": None}])
        self.assertEqual(len(answers.prompts), 1)

    def test_the_marking_screen_shows_no_reading_or_model_output(self) -> None:
        self.build(self.case())
        self.mark(Answers("h", "h"))
        screen = "\n".join(self.out)
        for word in ("READING", "departure", "consistent", "not verifiable"):
            self.assertNotIn(word, screen)

    def test_the_marks_and_their_sha256_are_written_and_the_digest_is_committable(self) -> None:
        self.build(self.case())
        self.mark(Answers("h", "h"))
        raw = (self.home / "drift-levels" / "marks.json").read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(
            (self.home / "drift-levels" / "marks.sha256").read_text(encoding="utf-8").split()[0],
            digest,
        )
        committed = json.loads(self.digest_path.read_text(encoding="utf-8"))
        self.assertEqual(committed["marks_digest"], digest)
        self.assertNotIn(SID[:8], json.dumps(committed))

    def test_marks_for_a_different_case_set_are_refused(self) -> None:
        self.build(self.case())
        self.mark(Answers("h", "h"))
        cases_path = self.home / "drift-levels" / "cases.json"
        body = json.loads(cases_path.read_text(encoding="utf-8"))
        body["cases"][0]["unsettled_directions"] = 3
        cases_path.write_text(json.dumps(body), encoding="utf-8")
        self.assertEqual(self.mark(Answers("m", "m")), 1)

    def test_marking_is_refused_once_any_result_exists(self) -> None:
        # T2: re-marking after seeing a result is agreement, not a mark.
        self.build(self.case(), self.case(kind="other", until=None))
        self.mark(Answers("h", "h", "q"))
        self.results_path.write_text("{}", encoding="utf-8")
        self.assertEqual(self.mark(Answers("e", "e")), 1)
        self.assertEqual(len(self.marks()), 1)


class RemarkAfterScoreTest(CaseToolTestCase):
    """V2: a result seen is a key closed, however the files that showed it were removed."""

    def scored(self) -> None:
        self.marked("h", "h")
        self.assertEqual(self.score(), 0)

    def forget_locally(self) -> None:
        self.results_path.unlink()
        (self.home / "drift-levels" / "marks.json").unlink()

    def test_deleting_the_result_and_the_marks_does_not_reopen_marking(self) -> None:
        self.scored()
        self.forget_locally()
        self.assertEqual(self.mark(Answers("e", "e")), 1)
        self.assertFalse((self.home / "drift-levels" / "marks.json").exists())

    def test_the_scored_marker_is_local_and_keyed_by_the_case_set(self) -> None:
        self.scored()
        markers = list((self.home / "drift-levels").glob("scored-*.json"))
        self.assertEqual(len(markers), 1)
        body = json.loads((self.home / "drift-levels" / "cases.json").read_text("utf-8"))
        self.assertIn(levels_cases.digest(body), markers[0].name)
        self.assertFalse(list(self.repo.rglob("scored-*.json")))

    def test_deleting_the_marker_too_is_caught_by_the_committed_digest(self) -> None:
        self.scored()
        self.forget_locally()
        for marker in (self.home / "drift-levels").glob("scored-*.json"):
            marker.unlink()
        self.assertEqual(self.mark(Answers("e", "e")), 1)

    def test_a_result_once_committed_and_removed_still_closes_marking(self) -> None:
        self.scored()
        _git(self.repo, "add", str(self.results_path))
        _git(self.repo, "commit", "-q", "-m", "results")
        _git(self.repo, "rm", "-q", str(self.results_path), str(self.digest_path))
        _git(self.repo, "commit", "-q", "-m", "gone")
        (self.home / "drift-levels" / "marks.json").unlink()
        for marker in (self.home / "drift-levels").glob("scored-*.json"):
            marker.unlink()
        self.assertEqual(self.mark(Answers("e", "e")), 1)

    def test_the_local_marker_holds_when_history_was_rewritten(self) -> None:
        self.scored()
        _git(self.repo, "reset", "-q", "--hard", "HEAD~1")
        _git(self.repo, "reflog", "expire", "--expire=now", "--all")
        self.results_path.unlink(missing_ok=True)
        (self.home / "drift-levels" / "marks.json").unlink()
        self.assertEqual(self.mark(Answers("e", "e")), 1)

    def test_a_committed_result_with_no_case_digest_closes_marking(self) -> None:
        self.build(self.case())
        self.results_path.write_text('{"v": 1}\n', encoding="utf-8")
        _git(self.repo, "add", str(self.results_path))
        _git(self.repo, "commit", "-q", "-m", "a result from before the case digest")
        _git(self.repo, "rm", "-q", str(self.results_path))
        _git(self.repo, "commit", "-q", "-m", "gone")
        self.assertEqual(self.mark(Answers("h", "h")), 1)

    def test_an_earlier_committed_digest_for_this_case_set_closes_marking(self) -> None:
        self.build(self.case(), self.case(kind="other", until=None))
        self.mark(Answers("h", "h", "q"))
        self.commit_digest()
        self.assertEqual(self.mark(Answers("m", "m")), 1)

    def test_another_case_set_may_still_be_marked(self) -> None:
        self.scored()
        (self.home / "drift-levels" / "marks.json").unlink()
        self.results_path.unlink()
        self.build(self.case(kind="other", until=None))
        self.assertEqual(self.mark(Answers("m", "m")), 0)


class CommittedDigestTest(CaseToolTestCase):
    def test_git_is_handed_the_digest_path_with_forward_slashes(self) -> None:
        # What `HEAD:<path>` needs on Windows, where relpath answers with backslashes.
        relative = levels_cases._repo_path(str(self.digest_path), str(self.repo))
        self.assertEqual(relative, "docs/drift-levels/marks-digest.json")

    def test_a_digest_committed_with_crlf_is_the_committed_digest(self) -> None:
        # Windows with core.autocrlf off commits the bytes as written; the
        # working copy is read in text mode, so only a line-wise compare agrees.
        self.marked("h", "h")
        self.digest_path.write_bytes(self.digest_path.read_bytes().replace(b"\n", b"\r\n"))
        _git(self.repo, "-c", "core.autocrlf=false", "add", str(self.digest_path))
        _git(self.repo, "commit", "-q", "-m", "marks digest, CRLF")
        blob = _git(self.repo, "cat-file", "-s", "HEAD:docs/drift-levels/marks-digest.json")
        self.assertEqual(int(blob), self.digest_path.stat().st_size)  # the CRLF bytes, kept
        committed = levels_cases.committed_digest(str(self.repo), str(self.digest_path))
        self.assertIsInstance(committed, levels_cases.Committed)


class AttachReadingsTest(CaseToolTestCase):
    def test_v4_a_reading_for_a_case_not_in_the_committed_marks_is_refused(self) -> None:
        self.build(self.case(), self.case(kind="other", until=None))
        self.mark(Answers("h", "h", "q"))
        self.commit_digest()
        unmarked = self.cases()[1]["id"]
        body = a_reading(time.time() + 60, line_1={"result": "departure"})
        self.assertEqual(self.attach({unmarked: body}), 1)
        self.assertFalse((self.home / "drift-levels" / "readings.json").exists())

    def test_a_reading_attaches_after_the_committed_digest(self) -> None:
        case_id = self.marked("h", "h")
        body = a_reading(time.time() + 60, line_1={"result": "departure"})
        self.assertEqual(self.attach({case_id: body}), 0)
        saved = json.loads((self.home / "drift-levels" / "readings.json").read_text("utf-8"))
        committed = json.loads(self.digest_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["marks_digest"], committed["marks_digest"])
        self.assertEqual(saved["digest_commit"], _git(self.repo, "rev-parse", "HEAD").strip())
        self.assertIn(case_id, saved["readings"])

    def test_nothing_attaches_before_the_digest_is_committed(self) -> None:
        self.build(self.case())
        self.mark(Answers("h", "h"))
        case_id = self.cases()[0]["id"]
        body = a_reading(time.time() + 60, line_1={"result": "departure"})
        self.assertEqual(self.attach({case_id: body}), 1)
        self.assertFalse((self.home / "drift-levels" / "readings.json").exists())

    def test_a_reading_made_before_the_digest_was_committed_is_refused(self) -> None:
        case_id = self.marked("h", "h")
        body = a_reading(time.time() - 3600, line_1={"result": "departure"})
        self.assertEqual(self.attach({case_id: body}), 1)

    def test_a_reading_the_store_would_refuse_is_refused(self) -> None:
        case_id = self.marked("h", "h")
        body = a_reading(time.time() + 60, line_1={"result": "departure"})
        body["surprise"] = "field"
        self.assertEqual(self.attach({case_id: body}), 1)

    def test_a_reading_for_an_unknown_case_is_refused(self) -> None:
        self.marked("h", "h")
        body = a_reading(time.time() + 60, line_1={"result": "departure"})
        self.assertEqual(self.attach({"0" * 16: body}), 1)


class JudgeTest(unittest.TestCase):
    """Matches the mark, or is more cautious; None or low never on a case marked higher."""

    def test_a_match_passes(self) -> None:
        self.assertEqual(levels_cases.judge("high", "high"), levels_cases.MATCH)

    def test_a_higher_level_is_more_cautious(self) -> None:
        self.assertEqual(levels_cases.judge("high", "medium"), levels_cases.CAUTIOUS)

    def test_a_lower_level_fails(self) -> None:
        self.assertEqual(levels_cases.judge("medium", "high"), levels_cases.FAILED)

    def test_none_or_low_on_a_case_marked_higher_fails(self) -> None:
        for mark in ("medium", "high", "extreme", "not_enough"):
            self.assertEqual(levels_cases.judge("none_or_low", mark), levels_cases.FAILED, mark)

    def test_too_little_is_more_cautious_only_than_none_or_low(self) -> None:
        self.assertEqual(levels_cases.judge("not_enough", "none_or_low"), levels_cases.CAUTIOUS)
        self.assertEqual(levels_cases.judge("not_enough", "high"), levels_cases.FAILED)

    def test_a_drift_level_on_a_case_marked_too_little_is_more_cautious(self) -> None:
        self.assertEqual(levels_cases.judge("medium", "not_enough"), levels_cases.CAUTIOUS)

    def test_no_live_level_matches_only_itself(self) -> None:
        self.assertEqual(levels_cases.judge("no_live_level", "no_live_level"), levels_cases.MATCH)
        self.assertEqual(levels_cases.judge("no_live_level", "high"), levels_cases.FAILED)
        self.assertEqual(levels_cases.judge("high", "no_live_level"), levels_cases.FAILED)


class ScoreTest(CaseToolTestCase):
    def test_a_case_matching_its_mark_passes_and_names_the_digest_commit(self) -> None:
        case_id = self.marked("h", "h")
        self.attach({case_id: a_reading(time.time() + 60, line_1={"result": "departure"})})
        self.assertEqual(self.score(), 0)
        body = self.results()
        self.assertEqual(body["verdict"], levels_cases.VERDICT_PASSED)
        self.assertEqual(body["digest_commit"], _git(self.repo, "rev-parse", "HEAD").strip())
        row = body["cases"][case_id]
        self.assertEqual(row["live"]["level"], "high")
        self.assertEqual(row["live"]["outcome"], levels_cases.MATCH)
        self.assertEqual(row["analysis"]["level"], "high")
        self.assertIn("failed-check", row["live"]["reasons"])

    def test_a_case_marked_higher_than_it_scores_fails(self) -> None:
        self.build(self.case(until=None, kind="other"))
        self.mark(Answers("e", "e"))
        self.commit_digest()
        self.assertEqual(self.score(), 1)
        self.assertEqual(self.results()["verdict"], levels_cases.VERDICT_FAILED)

    def test_an_analysis_mark_with_no_reading_attached_is_not_scored(self) -> None:
        case_id = self.marked("h", "h")
        self.assertEqual(self.score(), 0)
        self.assertEqual(self.results()["cases"][case_id]["analysis"], None)
        self.assertEqual(self.results()["counts"]["no_reading"], 1)

    def test_marks_that_moved_since_the_committed_digest_write_nothing(self) -> None:
        self.marked("h", "h")
        marks_path = self.home / "drift-levels" / "marks.json"
        body = json.loads(marks_path.read_text(encoding="utf-8"))
        marks_path.write_text(json.dumps(body, indent=4), encoding="utf-8")
        self.assertEqual(self.score(), 1)
        self.assertFalse(self.results_path.exists())

    def test_an_uncommitted_digest_refuses_the_score(self) -> None:
        # T2: the working copy the marker rewrites is not the committed digest.
        self.build(self.case())
        self.mark(Answers("h", "h"))
        self.assertEqual(self.score(), 1)
        self.assertFalse(self.results_path.exists())

    def test_a_working_copy_that_differs_from_the_commit_refuses_the_score(self) -> None:
        self.marked("h", "h")
        self.digest_path.write_text('{"marks_digest": "0"}\n', encoding="utf-8")
        self.assertEqual(self.score(), 1)
        self.assertFalse(self.results_path.exists())

    def test_an_unmarked_case_refuses_the_score_and_writes_nothing(self) -> None:
        # T3: a level written for an unmarked case can be read and then marked.
        self.build(self.case(), self.case(kind="other", until=None))
        self.mark(Answers("h", "h", "q"))
        self.commit_digest()
        self.assertEqual(self.score(), 1)
        self.assertFalse(self.results_path.exists())

    def test_an_analysis_mark_outside_the_closed_set_is_not_a_mark(self) -> None:
        # T4
        self.build(self.case())
        self.mark(Answers("h", "h"))
        marks_path = self.home / "drift-levels" / "marks.json"
        body = json.loads(marks_path.read_text(encoding="utf-8"))
        (key,) = body["marks"]
        body["marks"][key]["analysis"] = "SESSION TEXT"
        marks_path.write_text(json.dumps(body), encoding="utf-8")
        levels_cases._publish_digest(
            levels_cases._paths(str(self.home)),
            str(self.digest_path),
            1,
            1,
            cases_digest=body["cases_digest"],
        )
        self.commit_digest()
        self.assertEqual(self.score(), 1)
        self.assertFalse(self.results_path.exists())

    def test_a_reading_stored_in_the_case_file_is_refused(self) -> None:
        case_id = self.marked("h", "h")
        cases_path = self.home / "drift-levels" / "cases.json"
        body = json.loads(cases_path.read_text(encoding="utf-8"))
        body["cases"][0]["reading"] = a_reading(time.time() + 60, line_1={"result": "departure"})
        cases_path.write_text(json.dumps(body), encoding="utf-8")
        # Editing the case file also unbinds the marks, so this is refused before it is read.
        self.assertEqual(self.score(), 1)
        self.assertFalse(self.results_path.exists())
        committed = levels_cases.committed_digest(str(self.repo), str(self.digest_path))
        assert isinstance(committed, levels_cases.Committed)
        got = levels_cases._reading_for(body["cases"][0], {}, committed, None)
        self.assertEqual(got, (None, "reading-in-cases"))
        del case_id

    def test_a_reading_attached_under_another_digest_is_refused(self) -> None:
        case_id = self.marked("h", "h")
        self.attach({case_id: a_reading(time.time() + 60, line_1={"result": "departure"})})
        path = self.home / "drift-levels" / "readings.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        body["marks_digest"] = "f" * 64
        path.write_text(json.dumps(body), encoding="utf-8")
        self.assertEqual(self.score(), 1)
        row = self.results()["cases"][case_id]
        self.assertEqual(row["analysis"]["outcome"], "refused:other-digest")

    def test_a_reading_stamped_with_another_digest_commit_is_refused(self) -> None:
        case_id = self.marked("h", "h")
        self.attach({case_id: a_reading(time.time() + 60, line_1={"result": "departure"})})
        path = self.home / "drift-levels" / "readings.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        body["digest_commit"] = "0" * 40
        path.write_text(json.dumps(body), encoding="utf-8")
        self.assertEqual(self.score(), 1)
        row = self.results()["cases"][case_id]
        self.assertEqual(row["analysis"]["outcome"], "refused:other-digest")

    def test_the_results_hold_expectations_and_results_only(self) -> None:
        case_id = self.marked("h", "h")
        body = a_reading(time.time() + 60, line_1={"result": "departure", "detail": "MODEL PROSE"})
        self.attach({case_id: body})
        self.score()
        raw = self.results_path.read_text(encoding="utf-8")
        frozen = self.cases()[0]
        for local in (
            SID,
            SID[:8],
            str(self.transcript_path),
            self.cwd,
            GOAL,
            "node --test passes",
            "MODEL PROSE",
            "web/index.html",
            *(f["fact_id"] for f in frozen["facts"]),
        ):
            self.assertNotIn(local, raw, local)
        self.assertIn(case_id, raw)


def _runtime_module(name: str) -> Any:
    """A runtime module, reached the way the tool reaches it."""
    levels_cases._runtime()
    import importlib  # noqa: PLC0415

    return importlib.import_module(f"compass_runtime.{name}")


class FakeModel:
    """A reading model that never leaves the process: counts calls and keeps the prompts."""

    unavailable_reason = "model-unavailable"

    def __init__(self, reply: str = "", status: str = "ok", interrupt_at: int = 0) -> None:
        self.interrupt_at = interrupt_at
        self.reply = reply or json.dumps(
            {
                "goal": {"result": "unverifiable", "cites": [], "detail": ""},
                "line_1": {"result": "departure", "cites": [1], "detail": "MODEL PROSE"},
            }
        )
        self.status = status
        self.prompts: list[str] = []

    def available(self) -> bool:
        return True

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        del output_cap_bytes
        self.prompts.append(prompt)
        if len(self.prompts) == self.interrupt_at:
            raise KeyboardInterrupt
        return self.reply, self.status


class ReadTest(CaseToolTestCase):
    """`--read`: the frozen cases replayed through the board's producer, charged on its ledger."""

    def setUp(self) -> None:
        super().setUp()
        self.reading_home = self.root / "reading-home"
        self.config = levels_cases.reading_config(str(self.reading_home))
        self.policy = _runtime_module("reading_policy")
        self.policy.set_consent(
            self.config,
            True,
            now=time.time(),
            provider="codex",
            tool_output="OpenAI",
            destination="OpenAI",
        )
        self.model = FakeModel()

    def used(self) -> int:
        return int(self.policy.status(self.config, now=time.time(), provider="codex")["used"])

    def read(self, *case_ids: str, dry_run: bool = False) -> int:
        return levels_cases.read_cases(
            home=str(self.home),
            repo_root=str(self.repo),
            digest_path=str(self.digest_path),
            reading_config=self.config,
            case_ids=list(case_ids) or None,
            model=self.model,
            destination="OpenAI",
            dry_run=dry_run,
            clock=lambda: time.time() + 60,
            say=self.say,
        )

    def replayed(self) -> dict[str, Any]:
        path = levels_cases._paths(str(self.home))["replayed"]
        return dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def record(self) -> dict[str, Any]:
        path = levels_cases._paths(str(self.home))["replay"]
        return dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def attach_replayed(self) -> int:
        return levels_cases.attach_readings(
            levels_cases._paths(str(self.home))["replayed"],
            home=str(self.home),
            repo_root=str(self.repo),
            digest_path=str(self.digest_path),
            now=time.time() + 120,
            say=self.say,
        )

    def test_a_read_case_attaches_and_scores_unchanged(self) -> None:
        case_id = self.marked("h", "h")
        self.assertEqual(self.read(case_id), 0, self.out)
        self.assertEqual(len(self.model.prompts), 1)
        self.assertEqual(set(self.replayed()), {"v", "readings"})
        self.assertEqual(set(self.replayed()["readings"]), {case_id})
        self.assertEqual(self.attach_replayed(), 0, self.out)
        self.assertEqual(self.score(), 0, self.out)
        row = self.results()["cases"][case_id]
        self.assertEqual(row["analysis"]["level"], "high")
        self.assertEqual(row["analysis"]["outcome"], levels_cases.MATCH)

    def test_the_frozen_record_and_intent_are_what_is_sent(self) -> None:
        case_id = self.marked("h", "h")
        self.read(case_id)
        (prompt,) = self.model.prompts
        self.assertIn(GOAL, prompt)
        self.assertIn("node --test passes", prompt)
        # The check the case froze at its cut: the failure, never the later pass.
        self.assertIn("failed", prompt)
        self.assertNotIn("pass 3", prompt)

    def test_a_withheld_case_is_recorded_as_refused_not_faked(self) -> None:
        # Cut before any record: nothing to read, so the producer withholds.
        self.build(self.case(until=_epoch(5), kind="other"))
        self.mark(Answers("x", "x"))
        self.commit_digest()
        (case,) = self.cases()
        self.assertEqual(self.read(case["id"]), 0, self.out)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.used(), 0)
        entry = self.record()["cases"][case["id"]]
        self.assertEqual(entry["status"], "refused")
        self.assertEqual(entry["withheld"], "ledger-empty")
        self.assertFalse(entry["charged"])
        self.assertFalse(Path(levels_cases._paths(str(self.home))["replayed"]).exists())

    def test_a_failed_call_is_refused_and_still_charged(self) -> None:
        case_id = self.marked("h", "h")
        self.model = FakeModel(status="failed")
        self.assertEqual(self.read(case_id), 0, self.out)
        entry = self.record()["cases"][case_id]
        self.assertEqual((entry["status"], entry["withheld"]), ("refused", "model-failed"))
        self.assertTrue(entry["charged"])
        self.assertEqual(self.used(), 1)

    def test_an_unmarked_case_refuses_before_any_call(self) -> None:
        self.build(self.case(), self.case(kind="other", until=None))
        self.mark(Answers("h", "h", "q"))
        self.commit_digest()
        marked, unmarked = (c["id"] for c in self.cases())
        self.assertEqual(self.read(marked, unmarked), 1)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.used(), 0)

    def test_an_uncommitted_digest_refuses_before_any_call(self) -> None:
        self.build(self.case())
        self.mark(Answers("h", "h"))
        self.assertEqual(self.read(self.cases()[0]["id"]), 1)
        self.assertEqual(self.model.prompts, [])

    def test_a_case_changed_since_marking_refuses_before_any_call(self) -> None:
        case_id = self.marked("h", "h")
        cases_path = self.home / "drift-levels" / "cases.json"
        body = json.loads(cases_path.read_text(encoding="utf-8"))
        body["cases"][0]["intent"]["lines"] = ["a line nobody marked against"]
        cases_path.write_text(json.dumps(body), encoding="utf-8")
        self.assertEqual(self.read(case_id), 1)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.used(), 0)

    def test_the_budget_is_charged_exactly_once_per_call(self) -> None:
        # One session frozen as two kinds is one producer input: one call, one charge.
        self.build(self.case(), self.case(kind="other"))
        self.mark(Answers("h", "h", "h", "h"))
        self.commit_digest()
        ids = [c["id"] for c in self.cases()]
        self.assertEqual(self.read(*ids), 0, self.out)
        self.assertEqual(len(self.model.prompts), 1)
        self.assertEqual(self.used(), 1)
        self.assertEqual(set(self.replayed()["readings"]), set(ids))

    def test_a_case_already_read_is_not_read_or_charged_again(self) -> None:
        case_id = self.marked("h", "h")
        self.read(case_id)
        self.assertEqual(self.read(case_id), 0, self.out)
        self.assertEqual(len(self.model.prompts), 1)
        self.assertEqual(self.used(), 1)
        self.assertIn(case_id, self.replayed()["readings"])

    def test_a_budget_too_small_for_the_calls_refuses_before_any_call(self) -> None:
        case_id = self.marked("h", "h")
        for _ in range(self.policy.DAILY_CAP):
            self.policy.reserve(
                self.config, now=time.time(), provider="codex", destination="OpenAI"
            )
        self.assertEqual(self.read(case_id), 1)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.used(), self.policy.DAILY_CAP)

    def test_an_allow_given_for_another_destination_refuses_before_any_call(self) -> None:
        """The Allow is bound to where the words go (owner, 2026-10-02): one given
        while Codex reached a gateway does not cover a replay that reaches OpenAI."""
        case_id = self.marked("h", "h")
        self.policy.set_consent(
            self.config, True, now=time.time(), provider="codex", destination="gw.example"
        )
        self.assertEqual(self.read(case_id), 1)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.used(), 0)

    def test_codex_not_allowed_in_the_reading_home_refuses_before_any_call(self) -> None:
        case_id = self.marked("h", "h")
        self.policy.set_consent(self.config, False, now=time.time())
        self.assertEqual(self.read(case_id), 1)
        self.assertEqual(self.model.prompts, [])

    def test_a_route_that_is_not_openai_refuses_before_any_call(self) -> None:
        case_id = self.marked("h", "h")
        got = levels_cases.read_cases(
            home=str(self.home),
            repo_root=str(self.repo),
            digest_path=str(self.digest_path),
            reading_config=self.config,
            case_ids=[case_id],
            model=self.model,
            destination="",
            say=self.say,
        )
        self.assertEqual(got, 1)
        self.assertEqual(self.model.prompts, [])

    def test_a_dry_run_makes_no_call_and_no_charge(self) -> None:
        case_id = self.marked("h", "h")
        self.out.clear()  # the marking screen shows the intent; the dry run must not
        self.assertEqual(self.read(case_id, dry_run=True), 0, self.out)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.used(), 0)
        paths = levels_cases._paths(str(self.home))
        self.assertFalse(Path(paths["replayed"]).exists())
        self.assertFalse(Path(paths["replay"]).exists())
        shown = "\n".join(self.out)
        self.assertIn(case_id, shown)
        self.assertIn("1 call", shown)
        for local in (GOAL, "node --test passes", SID, self.cwd):
            self.assertNotIn(local, shown)

    def test_the_default_is_the_cases_the_prep_named(self) -> None:
        self.assertEqual(
            levels_cases.DEFAULT_READ,
            (
                "e41740a407b84be1",
                "5e607f9f716ab27c",
                "a753d332906e61bd",
                "d68d3f6a32182ba0",
                "0dd3ae7c558bf2cf",
            ),
        )

    def test_the_local_record_holds_no_session_text(self) -> None:
        case_id = self.marked("h", "h")
        self.read(case_id)
        raw = Path(levels_cases._paths(str(self.home))["replay"]).read_text(encoding="utf-8")
        for local in (GOAL, "node --test passes", SID, self.cwd, "MODEL PROSE"):
            self.assertNotIn(local, raw)

    # -- F1: the dry run says which cases a reading could move, before any spend.

    def line_for(self, case_id: str) -> str:
        (line,) = [x for x in self.out if x.strip().startswith(f"{case_id}: analysis")]
        return line

    def test_a_dry_run_flags_cases_whose_analysis_outcome_cannot_move(self) -> None:
        # A failed check inside the window forces High whatever the reply says,
        # so a case marked High can only match and one marked Extreme can only fail.
        passing = Transcript(self.cwd)
        passing.bash(20, "node --test", f"{INFO} pass 3\n{INFO} fail 0", failed=False)
        passing_path = self.root / "claude" / "projects" / "-work-ttt-pass" / f"{SID}.jsonl"
        passing.save(passing_path)
        self.build(
            self.case(),
            self.case(kind="other"),
            self.case(kind="own-account-only", transcript=str(passing_path), until=None),
        )
        self.mark(Answers("h", "h", "h", "e", "x", "x"))
        self.commit_digest()
        fixed, failing, movable = (c["id"] for c in self.cases())
        self.out.clear()
        self.assertEqual(self.read(fixed, failing, movable, dry_run=True), 0, self.out)
        self.assertIn("fixed by the evidence", self.line_for(fixed))
        self.assertNotIn("fails whatever the reply", self.line_for(fixed))
        self.assertIn("reaches high;", self.line_for(fixed))
        self.assertIn("fails whatever the reply", self.line_for(failing))
        self.assertNotIn("fixed by the evidence", self.line_for(movable))
        self.assertNotIn("fails whatever the reply", self.line_for(movable))
        # A departure stands only on a failed check, so a passing-only case
        # reaches None or low (failed against its mark) or Not enough (a match).
        self.assertIn("reaches none_or_low, not_enough;", self.line_for(movable))
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.used(), 0)
        paths = levels_cases._paths(str(self.home))
        self.assertFalse(Path(paths["replayed"]).exists())
        self.assertFalse(Path(paths["replay"]).exists())
        shown = "\n".join(self.out)
        for local in (GOAL, "node --test passes", SID, self.cwd):
            self.assertNotIn(local, shown)

    def test_a_dry_run_with_no_fake_calls_nothing_and_charges_nothing(self) -> None:
        from unittest import mock  # noqa: PLC0415

        case_id = self.marked("h", "h")
        reading = _runtime_module("reading")
        with mock.patch.object(reading, "CodexReadingModel", side_effect=AssertionError("built")):
            got = levels_cases.read_cases(
                home=str(self.home),
                repo_root=str(self.repo),
                digest_path=str(self.digest_path),
                reading_config=self.config,
                case_ids=[case_id],
                destination="OpenAI",
                dry_run=True,
                say=self.say,
            )
        self.assertEqual(got, 0, self.out)
        self.assertEqual(self.used(), 0)
        self.assertIn("fixed by the evidence", self.line_for(case_id))

    # -- F2: every call is written as it lands, and a charge is never paid twice.

    def four_cases(self) -> list[str]:
        self.build(*(self.case(until=_epoch(t)) for t in (300, 400, 500)), self.case(until=None))
        self.mark(Answers(*["h"] * 8))
        self.commit_digest()
        return [str(c["id"]) for c in self.cases()]

    def test_an_interrupted_run_keeps_its_readings_and_never_charges_twice(self) -> None:
        ids = self.four_cases()
        self.model = FakeModel(interrupt_at=3)
        with self.assertRaises(KeyboardInterrupt):
            self.read(*ids)
        self.assertEqual(self.used(), 3)
        self.assertEqual(set(self.replayed()["readings"]), set(ids[:2]))
        statuses = {k: v["status"] for k, v in self.record()["cases"].items()}
        self.assertEqual(statuses, {ids[0]: "read", ids[1]: "read", ids[2]: "charged"})
        self.model = FakeModel()
        self.assertEqual(self.read(*ids), 0, self.out)
        # Exactly the call not yet made: the fourth. The third was charged and is not read again.
        self.assertEqual(len(self.model.prompts), 1)
        self.assertEqual(self.used(), 4)
        self.assertEqual(set(self.replayed()["readings"]), {ids[0], ids[1], ids[3]})
        self.assertEqual(self.record()["cases"][ids[2]]["status"], "charged")
        self.assertTrue(any(ids[2] in x and "not read again" in x for x in self.out))

    def test_a_marker_whose_charge_never_landed_is_read(self) -> None:
        case_id = self.marked("h", "h")
        path = levels_cases._paths(str(self.home))["replay"]
        levels_cases._write(
            path,
            {
                "v": 1,
                "cases": {
                    case_id: {
                        "status": "pending",
                        "job": "levels-replay:never-charged",
                        "started_at": time.time() + 30,
                    }
                },
            },
        )
        self.assertEqual(self.read(case_id), 0, self.out)
        self.assertEqual(len(self.model.prompts), 1)
        self.assertEqual(self.used(), 1)
        self.assertEqual(self.record()["cases"][case_id]["status"], "read")

    # -- F4: no grant, no reading: refused up front.

    def test_no_tool_output_grant_refuses_before_any_call(self) -> None:
        case_id = self.marked("h", "h")
        self.policy.set_consent(self.config, False, now=time.time())
        self.policy.set_consent(
            self.config, True, now=time.time(), provider="codex", destination="OpenAI"
        )
        self.assertEqual(self.read(case_id), 1)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.used(), 0)
        self.assertIn("tool output", "\n".join(self.out))
        self.assertFalse(Path(levels_cases._paths(str(self.home))["replay"]).exists())

    # -- F5 and F6: what a re-run charges.

    def test_a_charged_failure_is_read_and_charged_again_on_rerun(self) -> None:
        case_id = self.marked("h", "h")
        self.model = FakeModel(status="failed")
        self.read(case_id)
        self.model = FakeModel()
        self.assertEqual(self.read(case_id), 0, self.out)
        self.assertEqual(self.used(), 2)
        self.assertEqual(self.record()["cases"][case_id]["status"], "read")

    def test_a_sibling_with_identical_inputs_reuses_the_held_reading(self) -> None:
        self.build(self.case(), self.case(kind="other"))
        self.mark(Answers("h", "h", "h", "h"))
        self.commit_digest()
        first, second = (str(c["id"]) for c in self.cases())
        self.read(first)
        self.assertEqual(self.read(second), 0, self.out)
        self.assertEqual(len(self.model.prompts), 1)
        self.assertEqual(self.used(), 1)
        readings = self.replayed()["readings"]
        self.assertEqual(readings[first], readings[second])
        entry = self.record()["cases"][second]
        self.assertEqual((entry["status"], entry["charged"], entry["call"]), ("read", False, first))


class AScoredCaseReadsEveryLineWholeTest(unittest.TestCase):
    """The drift-level rule for a line about what the agent tells you reads the whole
    line, so the cases tool must pass the line text as the page's route does."""

    def test_the_cases_tool_passes_each_outcome_line_to_the_level(self) -> None:
        seen: dict[str, Any] = {}

        class _Levels:
            Evidence = staticmethod(lambda **kw: kw)
            Intent = staticmethod(lambda **kw: kw)

            @staticmethod
            def live_level(*_a: Any, **_k: Any) -> Any:
                return types.SimpleNamespace(level="x", reasons=())

            @staticmethod
            def analysis_level(*_a: Any, **kwargs: Any) -> Any:
                seen.update(kwargs)
                return types.SimpleNamespace(level="x", reasons=())

        case = {
            "kind": "other",
            "intent": {"saved": True, "goal": "g", "lines": ["first line", "it is reported"]},
        }
        levels_cases._score_case(
            _Levels, case, {"live": "x", "analysis": "x"}, ({"criteria": {}}, "")
        )
        self.assertEqual(("first line", "it is reported"), tuple(seen["lines"]))
        self.assertEqual(2, seen["outcome_lines"])


# ------------------------------------------------------------------ the Codex cohort


class CodexCohortTestCase(unittest.TestCase):
    """A Codex analysis cohort, built from rollouts the committed Codex capture shapes describe.

    Nothing here reaches a model, a real session store or a ledger outside the temporary home.
    """

    def setUp(self) -> None:
        if TYPE_CHECKING:
            from tests import codex_source_support as support  # noqa: PLC0415
        else:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import codex_source_support as support  # noqa: PLC0415

        self.support = support
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = self.root / "codex" / "sessions"
        self.path = support.rollout(self.sessions)
        env = {
            "HOME": str(self.root),
            "COMPASS_HOME": str(self.root / "packet"),
            "CODEX_HOME": str(self.root / "codex"),
        }
        patched = unittest.mock.patch.dict(os.environ, env)
        patched.start()
        self.addCleanup(patched.stop)
        self.home = self.root / "packet"
        self.repo = self.root / "repo"
        (self.repo / "docs" / "drift-levels").mkdir(parents=True)
        _git(self.repo, "init", "-q")
        (self.repo / "README.md").write_text("repo\n", encoding="utf-8")
        _git(self.repo, "add", "README.md")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.digest_path = self.repo / "docs" / "drift-levels" / "codex-marks-digest.json"
        self.results_path = self.repo / "docs" / "drift-levels" / "codex-results.json"
        self.allowance_path = self.root / "cargento" / "codex-levels-replay-spend.json"
        self.out: list[str] = []

    def say(self, *args: Any, **_kwargs: Any) -> None:
        self.out.append(" ".join(map(str, args)))

    def entry(
        self, kind: str = "admissible-support", *, line: str = "", **over: Any
    ) -> dict[str, Any]:
        body = self.support.entry(self.sessions, self.path)
        body["intent"] = {
            **body["intent"],
            "lines": [line or "The example passes its check."],
        }
        body.update(kind=kind, unsettled_directions=0)
        body.update(over)
        return body

    def spec(self, *cases: dict[str, Any], matrix: list[str] | None = None) -> Path:
        path = self.home / "drift-levels-codex" / "spec.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        kinds = matrix if matrix is not None else sorted({str(c["kind"]) for c in cases})
        body = {"v": 1, "cohort": "codex", "matrix": kinds, "cases": list(cases)}
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    def build(self, *cases: dict[str, Any], matrix: list[str] | None = None) -> int:
        return levels_cases.build(
            self.spec(*cases, matrix=matrix),
            home=str(self.home),
            repo_root=str(self.repo),
            say=self.say,
            cohort="codex",
        )

    def files(self) -> dict[str, str]:
        return levels_cases._paths(str(self.home), "codex")

    def cases(self) -> list[dict[str, Any]]:
        return list(json.loads(Path(self.files()["cases"]).read_text(encoding="utf-8"))["cases"])

    def mark(self, answers: Answers) -> int:
        return levels_cases.mark(
            home=str(self.home),
            digest_path=str(self.digest_path),
            results_path=str(self.results_path),
            repo_root=str(self.repo),
            ask=answers,
            say=self.say,
            cohort="codex",
        )

    def commit_digest(self) -> None:
        _git(self.repo, "add", str(self.digest_path))
        _git(self.repo, "commit", "-q", "-m", "codex marks digest")

    def marked(self, *replies: str, **entry: Any) -> list[str]:
        """Build and mark Codex cases (one per reply), commit the digest; their ids."""
        kinds = list(entry.pop("kinds", ["admissible-support"]))
        entries = [
            self.entry(k, line=f"The example passes check {n}.") for n, k in enumerate(kinds)
        ]
        self.assertEqual(self.build(*entries), 0, self.out)
        self.assertEqual(self.mark(Answers(*replies)), 0, self.out)
        self.commit_digest()
        return [str(c["id"]) for c in self.cases()]


class CodexBuildTest(CodexCohortTestCase):
    def test_a_person_never_confuses_a_claude_case_with_a_codex_case_of_one_session(self) -> None:
        claude = levels_cases.case_id("sid", None, "other")
        self.assertEqual(claude, hashlib.sha256(b"claude|sid|None|other").hexdigest()[:16])
        self.assertNotEqual(claude, levels_cases.case_id("sid", None, "other", "codex"))

    def test_a_person_freezes_a_codex_case_with_its_checks_and_sealed_sources(self) -> None:
        self.assertEqual(self.build(self.entry()), 0, self.out)
        (case,) = self.cases()
        self.assertEqual(case["harness"], "codex")
        self.assertEqual(
            case["id"],
            levels_cases.case_id(case["sid"], case["captured_at"], case["kind"], "codex"),
        )
        self.assertEqual([f["subject"] for f in case["facts"]], ["check"])
        self.assertEqual(len(case["sources"]["parent"]["sha256"]), 64)
        self.assertEqual(case["intent"]["lines"], ["The example passes its check."])
        self.assertEqual(case["unsettled_directions"], 0)

    def test_a_person_keeps_no_session_words_outside_the_private_packet(self) -> None:
        self.assertEqual(self.build(self.entry()), 0, self.out)
        self.assertIn("codex", self.files()["dir"])
        self.assertNotEqual(self.files()["dir"], levels_cases._paths(str(self.home))["dir"])
        self.assertTrue(self.files()["cases"].startswith(str(self.home)))

    def test_a_person_must_account_for_every_child_rollout(self) -> None:
        child = self.support.rollout(self.sessions, sid=self.support.CHILD, parent=self.support.SID)
        self.assertEqual(self.build(self.entry()), 1)
        self.assertFalse(Path(self.files()["cases"]).exists())
        self.assertEqual(self.build(self.entry(children=[str(child)])), 0, self.out)
        self.assertEqual(len(self.cases()[0]["sources"]["children"]), 1)

    def test_a_person_cannot_build_a_codex_cohort_from_claude_shaped_entries(self) -> None:
        claude = {
            "kind": "failed-check",
            "transcript": str(self.path),
            "until": None,
            "intent": {"saved": True, "goal": "g", "lines": ["l"]},
            "unsettled_directions": 0,
        }
        self.assertEqual(self.build(claude), 1)
        self.assertFalse(Path(self.files()["cases"]).exists())

    def test_a_person_cannot_build_a_claude_cohort_from_a_codex_entry(self) -> None:
        path = self.home / "drift-levels" / "spec.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"v": 1, "cases": [self.entry()]}), encoding="utf-8")
        self.assertEqual(
            levels_cases.build(path, home=str(self.home), repo_root=str(self.repo), say=self.say), 1
        )

    def test_a_codex_spec_missing_a_hand_written_count_is_refused_not_defaulted(self) -> None:
        entry = self.entry()
        del entry["unsettled_directions"]
        self.assertEqual(self.build(entry), 1)
        self.assertFalse(Path(self.files()["cases"]).exists())

    def test_a_kind_outside_the_codex_matrix_is_refused(self) -> None:
        self.assertEqual(self.build(self.entry("failed-check")), 1)

    def test_a_matrix_with_an_uncovered_kind_is_refused_before_anything_is_written(self) -> None:
        self.assertEqual(self.build(self.entry(), matrix=["admissible-support", "stale-pass"]), 1)
        self.assertFalse(Path(self.files()["cases"]).exists())

    def test_a_cohort_is_at_most_twelve_cases(self) -> None:
        many = [
            self.entry(line=f"The example passes check {n}.", captured_at=self.support.AT + 20 + n)
            for n in range(13)
        ]
        self.assertEqual(self.build(*many, matrix=["admissible-support"]), 1)

    def test_a_reading_in_the_spec_is_refused_because_marks_come_first(self) -> None:
        self.assertEqual(self.build(self.entry(reading={"x": 1})), 1)


class CodexMarkTest(CodexCohortTestCase):
    def test_a_codex_case_is_marked_for_analysis_only_and_the_cohort_is_named(self) -> None:
        answers = Answers("n")
        self.build(self.entry())
        self.assertEqual(self.mark(answers), 0, self.out)
        self.assertEqual(len(answers.prompts), 1)
        self.assertIn("ANALYSIS", answers.prompts[0])
        self.assertNotIn("LIVE", answers.prompts[0])
        marks = json.loads(Path(self.files()["marks"]).read_text(encoding="utf-8"))
        self.assertEqual(marks["cohort"], "codex")
        (value,) = marks["marks"].values()
        self.assertEqual(value, {"live": None, "analysis": "none_or_low"})

    def test_the_codex_digest_binds_the_matrix_and_the_required_cases_before_any_output(
        self,
    ) -> None:
        (case_id,) = self.marked("n")
        digest = json.loads(self.digest_path.read_text(encoding="utf-8"))
        self.assertEqual(digest["cohort"], "codex")
        self.assertEqual(digest["required_analysis"], [case_id])
        self.assertEqual(digest["matrix"], ["admissible-support"])
        self.assertNotIn(self.support.SID, self.digest_path.read_text(encoding="utf-8"))

    def test_the_marking_screen_shows_no_model_words_and_no_live_estimate(self) -> None:
        self.build(self.entry())
        self.mark(Answers("n"))
        shown = "\n".join(self.out)
        self.assertNotIn("LIVE ESTIMATE", shown)
        self.assertNotIn(self.support.SID, shown)

    def test_a_codex_cohort_cannot_be_marked_after_its_result_exists(self) -> None:
        self.marked("n")
        self.results_path.write_text("{}\n", encoding="utf-8")
        self.assertEqual(self.mark(Answers("n")), 1)
        self.assertTrue(any("closed" in line for line in self.out))


class CodexReplayTestCase(CodexCohortTestCase):
    """`--read --cohort codex`: replays charged to the reading home AND a fixed allowance."""

    ALLOWANCE = 2

    def setUp(self) -> None:
        super().setUp()
        self.reading_home = self.root / "reading-home"
        self.config = levels_cases.reading_config(str(self.reading_home))
        self.policy = _runtime_module("reading_policy")
        self.policy.set_consent(
            self.config,
            True,
            now=time.time(),
            provider="codex",
            tool_output="OpenAI",
            destination="OpenAI",
        )
        self.model = FakeModel()
        self.asked: list[dict[str, Any]] = []
        self.answer = True

    def approve(self, call: dict[str, Any]) -> bool:
        self.asked.append(call)
        return self.answer

    def allow(self, total: int | None = None) -> int:
        return levels_cases.approve_replay_allowance(
            self.allowance_path, self.ALLOWANCE if total is None else total, now=1.0, say=self.say
        )

    def used(self) -> int:
        return int(self.policy.status(self.config, now=time.time(), provider="codex")["used"])

    def read(self, *ids: str, approve: Any = "default", dry_run: bool = False) -> int:
        return levels_cases.read_cases(
            home=str(self.home),
            repo_root=str(self.repo),
            digest_path=str(self.digest_path),
            reading_config=self.config,
            case_ids=list(ids) or None,
            model=self.model,
            destination="OpenAI",
            dry_run=dry_run,
            clock=lambda: time.time() + 60,
            say=self.say,
            cohort="codex",
            approve=self.approve if approve == "default" else approve,
            allowance_path=str(self.allowance_path),
        )

    def ledger(self) -> dict[str, Any]:
        return dict(json.loads(self.allowance_path.read_text(encoding="utf-8")))

    def charges(self) -> list[dict[str, Any]]:
        return [e for e in self.ledger()["events"] if e["kind"] == "charge"]

    def replayed(self) -> dict[str, Any]:
        return dict(json.loads(Path(self.files()["replayed"]).read_text(encoding="utf-8")))

    def two_cases(self) -> list[str]:
        return self.marked("n", "n", kinds=["admissible-support", "stale-pass"])

    def attach_replayed(self) -> int:
        return levels_cases.attach_readings(
            self.files()["replayed"],
            home=str(self.home),
            repo_root=str(self.repo),
            digest_path=str(self.digest_path),
            now=time.time() + 120,
            say=self.say,
            cohort="codex",
            allowance_path=str(self.allowance_path),
        )

    def score(self) -> int:
        return levels_cases.score(
            home=str(self.home),
            repo_root=str(self.repo),
            digest_path=str(self.digest_path),
            results_path=str(self.results_path),
            now=time.time() + 300,
            say=self.say,
            cohort="codex",
            allowance_path=str(self.allowance_path),
        )

    def results(self) -> dict[str, Any]:
        return dict(json.loads(self.results_path.read_text(encoding="utf-8")))


class CodexAllowanceTest(CodexReplayTestCase):
    def test_a_person_fixes_the_total_replay_allowance_once(self) -> None:
        self.assertEqual(self.allow(2), 0, self.out)
        self.assertEqual(self.ledger()["allowance"], 2)
        self.assertEqual(self.allow(3), 1)
        self.assertEqual(self.ledger()["allowance"], 2)

    def test_the_allowance_is_between_zero_and_twelve(self) -> None:
        self.assertEqual(self.allow(13), 1)
        self.assertEqual(self.allow(-1), 1)
        self.assertFalse(self.allowance_path.exists())

    def test_the_ledger_itself_refuses_a_charge_past_the_total(self) -> None:
        self.allow(1)
        ledger = levels_cases.ReplayLedger(str(self.allowance_path))
        ledger.charge(case="a", inputs="i1", request="r", approval="p1", now=2.0)
        with self.assertRaisesRegex(levels_cases.ReplayLedgerError, "spent"):
            ledger.charge(case="b", inputs="i2", request="r", approval="p2", now=3.0)

    def test_the_ledger_itself_never_charges_the_same_inputs_or_approval_twice(self) -> None:
        self.allow(3)
        ledger = levels_cases.ReplayLedger(str(self.allowance_path))
        ledger.charge(case="a", inputs="i1", request="r", approval="p1", now=2.0)
        with self.assertRaisesRegex(levels_cases.ReplayLedgerError, "charged already"):
            ledger.charge(case="a", inputs="i1", request="r", approval="p2", now=3.0)
        with self.assertRaisesRegex(levels_cases.ReplayLedgerError, "approval"):
            ledger.charge(case="b", inputs="i2", request="r", approval="p1", now=3.0)
        self.assertEqual(ledger.remaining(), 2)

    def test_a_settlement_never_gives_a_charge_back(self) -> None:
        self.allow(1)
        ledger = levels_cases.ReplayLedger(str(self.allowance_path))
        charge = ledger.charge(case="a", inputs="i1", request="r", approval="p1", now=2.0)
        ledger.settle(charge, "unusable", now=3.0)
        self.assertEqual(ledger.remaining(), 0)

    def test_the_allowance_file_is_private(self) -> None:
        self.allow(1)
        self.assertEqual(self.allowance_path.stat().st_mode & 0o777, 0o600)


class CodexReplayTest(CodexReplayTestCase):
    def test_a_person_approves_each_call_with_its_digest_and_the_allowance_left(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        self.assertEqual(self.read(case_id), 0, self.out)
        (asked,) = self.asked
        self.assertEqual(asked["case"], case_id)
        self.assertEqual(len(asked["request_digest"]), 64)
        self.assertEqual(asked["remaining"], 2)
        self.assertEqual(len(self.model.prompts), 1)
        self.assertEqual(
            hashlib.sha256(self.model.prompts[0].encode()).hexdigest(), asked["request_digest"]
        )

    def test_the_replayed_prompt_is_the_one_the_frozen_production_reader_built(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        self.read(case_id)
        (case,) = self.cases()
        self.assertEqual(
            hashlib.sha256(self.model.prompts[0].encode()).hexdigest(),
            case["production_reading"]["prompt_digest"],
        )

    def test_a_replay_with_no_way_to_approve_a_call_refuses_before_any_call(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        self.assertEqual(self.read(case_id, approve=None), 1)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.used(), 0)

    def test_a_call_the_person_does_not_approve_is_not_made_or_charged(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        self.answer = False
        self.assertEqual(self.read(case_id), 0, self.out)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual((self.used(), self.charges()), (0, []))

    def test_a_replay_before_the_allowance_is_fixed_refuses_before_any_call(self) -> None:
        (case_id,) = self.marked("n")
        self.assertEqual(self.read(case_id), 1)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(self.asked, [])

    def test_a_replay_needing_more_calls_than_the_allowance_holds_refuses_whole(self) -> None:
        ids = self.two_cases()
        self.allow(1)
        self.assertEqual(self.read(*ids), 1)
        self.assertEqual((self.model.prompts, self.asked, self.used()), ([], [], 0))

    def test_the_rolling_reading_budget_still_refuses_before_any_charge(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        for _ in range(self.policy.DAILY_CAP):
            self.policy.reserve(
                self.config, now=time.time(), provider="codex", destination="OpenAI"
            )
        self.assertEqual(self.read(case_id), 1)
        self.assertEqual((self.model.prompts, self.asked), ([], []))
        self.assertEqual(self.ledger()["events"], [])

    def test_reading_consent_is_still_required(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        self.policy.set_consent(self.config, False, now=time.time())
        self.assertEqual(self.read(case_id), 1)
        self.assertEqual(self.model.prompts, [])

    def test_a_charged_interruption_stays_charged_and_is_never_read_again(self) -> None:
        ids = self.two_cases()
        self.allow()
        self.model = FakeModel(interrupt_at=1)
        with self.assertRaises(KeyboardInterrupt):
            self.read(*ids)
        (charge,) = self.charges()
        self.assertFalse([e for e in self.ledger()["events"] if e["kind"] == "settlement"])
        self.model = FakeModel()
        self.assertEqual(self.read(*ids), 0, self.out)
        self.assertEqual(len(self.model.prompts), 1)
        self.assertEqual(len(self.charges()), 2)
        self.assertEqual(self.charges()[0], charge)
        self.assertEqual(len({c["case"] for c in self.charges()}), 2)

    def test_a_failed_case_is_not_silently_recharged_on_a_rerun(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        self.model = FakeModel(status="failed")
        self.assertEqual(self.read(case_id), 0, self.out)
        self.assertEqual(len(self.charges()), 1)
        self.model = FakeModel()
        self.assertEqual(self.read(case_id), 0, self.out)
        self.assertEqual(self.model.prompts, [])
        self.assertEqual(len(self.charges()), 1)
        self.assertEqual(len(self.asked), 1)

    def test_the_allowance_is_spent_once_per_call_and_never_renewed(self) -> None:
        ids = self.two_cases()
        self.allow(1)
        self.assertEqual(self.read(ids[0]), 0, self.out)
        self.assertEqual(self.read(ids[1]), 1)
        self.assertEqual(len(self.charges()), 1)
        self.assertEqual(self.allow(5), 1)

    def test_a_request_other_than_the_approved_one_is_never_sent(self) -> None:
        model = FakeModel()
        approved = levels_cases._Pinned(model, hashlib.sha256(b"approved").hexdigest())
        self.assertEqual(approved("something else", output_cap_bytes=1), ("", "cancelled"))
        self.assertEqual(model.prompts, [])
        self.assertEqual(approved("approved", output_cap_bytes=1)[1], "ok")

    def test_a_dry_run_asks_for_nothing_and_charges_nothing(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        self.assertEqual(self.read(case_id, dry_run=True), 0, self.out)
        self.assertEqual((self.asked, self.charges(), self.used()), ([], [], 0))

    def test_a_replay_for_a_claude_case_cannot_spend_the_codex_allowance(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        body = json.loads(Path(self.files()["cases"]).read_text(encoding="utf-8"))
        body["cases"][0]["harness"] = "claude"
        Path(self.files()["cases"]).write_text(json.dumps(body), encoding="utf-8")
        self.assertEqual(self.read(case_id), 1)
        self.assertEqual(self.model.prompts, [])


class CodexAttachTest(CodexReplayTestCase):
    def replay_one(self) -> str:
        (case_id,) = self.marked("n")
        self.allow()
        self.assertEqual(self.read(case_id), 0, self.out)
        return case_id

    def test_a_replayed_reading_binds_its_producer_request_inputs_and_charge(self) -> None:
        case_id = self.replay_one()
        binding = self.replayed()["bindings"][case_id]
        self.assertEqual(set(binding), {"producer", "request", "inputs", "charge"})
        self.assertEqual(binding["charge"], self.charges()[0]["id"])
        self.assertEqual(self.attach_replayed(), 0, self.out)

    def test_a_reading_from_another_producer_is_refused(self) -> None:
        case_id = self.replay_one()
        spec = self.replayed()
        spec["bindings"][case_id]["producer"] = "someone-else"
        Path(self.files()["replayed"]).write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(self.attach_replayed(), 1)
        self.assertTrue(any("producer" in line for line in self.out))
        self.assertFalse(Path(self.files()["readings"]).exists())

    def test_a_reading_with_no_binding_is_refused_however_late_it_is_stamped(self) -> None:
        case_id = self.replay_one()
        spec = self.replayed()
        del spec["bindings"]
        Path(self.files()["replayed"]).write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(self.attach_replayed(), 1)
        self.assertTrue(any(case_id in line and "binding" in line for line in self.out))

    def test_a_reading_for_inputs_that_changed_since_it_was_read_is_refused(self) -> None:
        case_id = self.replay_one()
        spec = self.replayed()
        spec["bindings"][case_id]["inputs"] = "0" * 64
        Path(self.files()["replayed"]).write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(self.attach_replayed(), 1)
        self.assertTrue(any("inputs" in line for line in self.out))

    def test_a_reading_that_names_a_charge_nobody_approved_is_refused(self) -> None:
        case_id = self.replay_one()
        spec = self.replayed()
        spec["bindings"][case_id]["charge"] = "f" * 32
        Path(self.files()["replayed"]).write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(self.attach_replayed(), 1)
        self.assertTrue(any("charge" in line for line in self.out))

    def test_a_reading_that_names_another_requests_charge_is_refused(self) -> None:
        case_id = self.replay_one()
        spec = self.replayed()
        spec["bindings"][case_id]["request"] = "0" * 64
        Path(self.files()["replayed"]).write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(self.attach_replayed(), 1)

    def test_a_reading_charged_before_the_digest_was_committed_is_refused(self) -> None:
        case_id = self.replay_one()
        ledger = self.ledger()
        for event in ledger["events"]:
            event["at"] = 1.0
        self.allowance_path.write_text(json.dumps(ledger), encoding="utf-8")
        self.assertEqual(self.attach_replayed(), 1)
        self.assertTrue(any(case_id in line for line in self.out))

    def test_a_binding_edited_after_it_attached_is_refused_when_the_cohort_is_scored(self) -> None:
        case_id = self.replay_one()
        self.assertEqual(self.attach_replayed(), 0, self.out)
        readings = json.loads(Path(self.files()["readings"]).read_text(encoding="utf-8"))
        readings["bindings"][case_id]["producer"] = "someone-else"
        Path(self.files()["readings"]).write_text(json.dumps(readings), encoding="utf-8")
        self.assertEqual(self.score(), 1)
        row = self.results()["cases"][case_id]["analysis"]
        self.assertEqual(row["outcome"], "refused:unbound")
        self.assertEqual(self.results()["verdict"], levels_cases.VERDICT_REFUSED)

    def test_siblings_with_identical_inputs_share_one_call_and_its_binding(self) -> None:
        entries = [
            self.entry(k, line="The example passes its check.") for k in ("stale-pass", "goal-only")
        ]
        self.assertEqual(self.build(*entries), 0, self.out)
        self.mark(Answers("n", "n"))
        self.commit_digest()
        ids = [str(c["id"]) for c in self.cases()]
        self.allow()
        self.assertEqual(self.read(*ids), 0, self.out)
        self.assertEqual(len(self.model.prompts), 1)
        bindings = self.replayed()["bindings"]
        self.assertEqual(bindings[ids[0]], bindings[ids[1]])
        self.assertEqual(self.attach_replayed(), 0, self.out)
        self.assertEqual(len(self.charges()), 1)

    def test_nothing_attaches_before_the_codex_digest_is_committed(self) -> None:
        (case_id,) = self.marked("n")
        self.allow()
        self.read(case_id)
        _git(self.repo, "reset", "-q", "--hard", "HEAD~1")
        self.assertEqual(self.attach_replayed(), 1)


class CodexScoreTest(CodexReplayTestCase):
    def reply(self, result: str = "consistent") -> str:
        case = self.cases()[0]
        names = case["production_reading"]["constraints"]
        return json.dumps({n: {"result": result, "cites": [], "detail": ""} for n in names})

    def test_a_person_scores_a_whole_codex_cohort_with_no_model_call(self) -> None:
        ids = self.two_cases()
        self.allow()
        self.model = FakeModel(reply=self.reply())
        self.assertEqual(self.read(*ids), 0, self.out)
        self.assertEqual(self.attach_replayed(), 0, self.out)
        calls = len(self.model.prompts)
        self.assertEqual(self.score(), 0, self.out)
        self.assertEqual(len(self.model.prompts), calls)
        result = self.results()
        self.assertEqual(result["cohort"], "codex")
        self.assertEqual(result["verdict"], levels_cases.VERDICT_PASSED)
        self.assertEqual(result["counts"]["no_reading"], 0)
        self.assertTrue(all(row["live"] is None for row in result["cases"].values()))
        self.assertTrue(all(row["analysis"] is not None for row in result["cases"].values()))

    def test_a_missing_reading_cannot_accompany_a_codex_pass(self) -> None:
        ids = self.two_cases()
        self.allow()
        self.model = FakeModel(reply=self.reply())
        self.read(ids[0])
        self.attach_replayed()
        self.assertEqual(self.score(), 1)
        result = self.results()
        self.assertEqual(result["verdict"], levels_cases.VERDICT_INCOMPLETE)
        self.assertEqual(result["counts"]["no_reading"], 1)
        self.assertNotEqual(result["verdict"], levels_cases.VERDICT_PASSED)

    def test_a_cohort_whose_matrix_lost_a_case_cannot_pass(self) -> None:
        ids = self.two_cases()
        self.allow()
        self.model = FakeModel(reply=self.reply())
        self.read(*ids)
        self.attach_replayed()
        body = json.loads(Path(self.files()["cases"]).read_text(encoding="utf-8"))
        body["matrix"].append("misleading-claim")
        Path(self.files()["cases"]).write_text(json.dumps(body), encoding="utf-8")
        self.assertEqual(self.score(), 1)
        self.assertFalse(self.results_path.exists())

    def test_a_codex_result_names_no_session_path_command_or_words(self) -> None:
        ids = self.two_cases()
        self.allow()
        self.model = FakeModel(reply=self.reply())
        self.read(*ids)
        self.attach_replayed()
        self.score()
        text = self.results_path.read_text(encoding="utf-8")
        for private in (
            self.support.SID,
            str(self.root),
            "pytest",
            "Please repair",
            "passes check",
        ):
            self.assertNotIn(private, text)

    def test_a_codex_score_never_needs_a_live_source(self) -> None:
        ids = self.two_cases()
        self.allow()
        self.model = FakeModel(reply=self.reply())
        self.read(*ids)
        self.attach_replayed()
        self.score()
        for row in self.results()["cases"].values():
            self.assertIsNone(row["live"])
            self.assertIsNone(row["marks"]["live"])

    def test_the_claude_cohort_keeps_its_own_files_and_still_scores_a_live_source(self) -> None:
        self.assertNotEqual(levels_cases.DIGEST_PATH, levels_cases.CODEX_DIGEST_PATH)
        self.assertNotEqual(levels_cases.RESULTS_PATH, levels_cases.CODEX_RESULTS_PATH)
        self.assertTrue(levels_cases.CODEX_DIGEST_PATH.endswith("codex-marks-digest.json"))
        self.assertTrue(levels_cases.CODEX_RESULTS_PATH.endswith("codex-results.json"))


class CommittedTextTest(unittest.TestCase):
    """What this tool commits never names a session (SECURITY.md, the abstention check)."""

    def test_no_session_id_prefix_in_the_readme_or_the_tool(self) -> None:
        import re  # noqa: PLC0415

        root = Path(__file__).resolve().parents[2]
        for relative in ("docs/drift-levels/README.md", "scripts/levels_cases.py"):
            text = (root / relative).read_text(encoding="utf-8")
            tokens = re.findall(r"(?<![0-9a-f])[0-9a-f]{8}(?![0-9a-f])", text)
            self.assertEqual([t for t in tokens if any(ch.isdigit() for ch in t)], [], relative)


if __name__ == "__main__":
    unittest.main()
