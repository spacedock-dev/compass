"""A goal verdict's reason is read for remote phrasing in work linear in its length.

A remote job name ("server-unittest pass") and a CI run URL are read out of a goal-met reason before
it is searched for a local check. A reason may be 16,000 characters (an Antigravity goal), and the
two patterns that find them restarted inside every token: 16.9 s for one reason. These tests hold
the replacement to the old patterns' exact matches and to work that doubles, not quadruples, when
the reason doubles.
"""

from __future__ import annotations

import random
import re
import sys
import time
import unittest
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import reading

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# Frozen copies of the patterns and the replacement as they were before the linear scan. The new
# scan must yield exactly their matches and their substitution.
_RESULT_WORD = r"(?:pass(?:es|ed|ing)?|green|succe\w*|fail(?:s|ed|ing)?)"
_OLD_REMOTE_JOB = re.compile(
    r"(?<![\w-])[`'\"]?(?!type-?checks?\b)(?P<job>\w[\w.]*(?:[-/]\w[\w.]*)+)[`'\"]?"
    rf"(?:\s+(?:job|check))?(?:\s*[:(]\s*|\s+(?:is\s+)?){_RESULT_WORD}\b\)?",
    re.IGNORECASE,
)
_OLD_CI_RUN_URL = re.compile(
    r"https?://[^\s)]*/(?:actions/runs|pipelines|jobs)/\d+[^\s)]*", re.IGNORECASE
)
_OLD_PATH_AFTER = re.compile(r"\b(?:in|under|of)\s+[`'\"]?$", re.IGNORECASE)


def _old_drop_remote_job(match: re.Match[str]) -> str:
    job = match["job"]
    if reading._NOT_A_JOB.match(job) or reading._is_kind_list(job):
        return match[0]
    if "/" in job and _OLD_PATH_AFTER.search(match.string[: match.start("job")]):
        return match[0]
    return " "


_JOB_PIECES = (
    "a", "b", "Z", "_", "é", "1", ".", "/", "-", "--", "'", '"', "`", " ", "  ", ":", "(", ")",
    "\t", "\n", "type", "check", "checks", "type-check", "typecheck", "TYPE-CHECKS", "job", " job",
    " check", "is", " is ", "pass", "passes", "passed", "FAILED", "green", "success", "succeeded",
    "ci/build", "server-unittest", "14/14", "in ", "under ", " of ", "tests/unit", "lint-test",
    "x.y", "..", "./", "\u017f",
)  # fmt: skip
_URL_PIECES = (
    "http://", "https://", "HTTPS://", "ht", "tp", "s", ":", "/", "//", "x", "a.b", "actions/runs",
    "/actions/runs/", "pipelines", "/pipelines/", "/jobs/", "jobs", "12", "7", "\u0661", " ", ")",
    "(", "-", "?q=1", "#", "\u017f", "\n",
)  # fmt: skip


def _texts(pieces: tuple[str, ...], seed: int, count: int) -> Iterator[str]:
    rng = random.Random(seed)
    for _ in range(count):
        yield "".join(rng.choice(pieces) for _ in range(rng.randint(1, 18)))


def _shaped_job_texts(seed: int, count: int) -> Iterator[str]:
    """Reasons built from a job-shaped token, a quote, a joiner word and a result word, so most of
    them match, and the context before a slash-joined job is often "in", "under" or "of"."""
    rng = random.Random(seed)
    token = ("a", "B", "1", "_", "é", ".", "/", "-", "type", "check", "s", "ci", "unit", "14")
    before = ("", " ", "in ", "under ", "of ", "x", "-", "'", '"', "`", "\n", "in '", "in \n", "(")
    joiner = ("", " job", " check", " Job")
    gap = (":", " (", " ", " is ", ": ", "  ", "\t", "", " :")
    result = ("pass", "passes", "PASSED", "green", "succeeded", "fails", "failing", "passx", "is")
    for _ in range(count):
        yield "".join(
            rng.choice(before)
            + rng.choice(("", "'", "`", '"'))
            + "".join(rng.choices(token, k=rng.randint(1, 8)))
            + rng.choice(("", "'", "`", '"'))
            + rng.choice(joiner)
            + rng.choice(gap)
            + rng.choice(result)
            + rng.choice(("", ")", " ", ".", "/x", "-y"))
            for _ in range(rng.randint(1, 4))
        )


def _shaped_url_texts(seed: int, count: int) -> Iterator[str]:
    rng = random.Random(seed)
    scheme = ("http://", "https://", "HTTPS://", "Http://", "htp://", "")
    part: tuple[str, ...] = (
        "x",
        "a.b",
        "/",
        "actions",
        "/actions/runs/",
        "/pipelines/",
        "/jobs/",
        "runs",
        "12",
    )
    part += ("\u0661", "?q=1", "-", "http://", "(", "\u017f")
    for _ in range(count):
        yield rng.choice(("", " ", ")", "x")).join(
            rng.choice(scheme) + "".join(rng.choices(part, k=rng.randint(1, 8)))
            for _ in range(rng.randint(1, 4))
        )


def _spans(matches: Any) -> list[tuple[tuple[int, int], str, str | None]]:
    return [(match.span(), match.group(0), match.groupdict().get("job")) for match in matches]


class _Charged:
    """A compiled pattern that records the characters each call may read.

    An anchored call reads at most its window. An unanchored scan of these patterns may restart at
    every offset and read to the end, so it is charged the square of its window: that is what the
    old patterns cost (17 s for one 50,000-character token).
    """

    def __init__(self, pattern: re.Pattern[str], spent: list[int]) -> None:
        self._pattern = pattern
        self._spent = spent

    def _window(self, string: str, pos: int, endpos: int) -> int:
        return max(0, min(endpos, len(string)) - pos)

    def match(self, string: str, pos: int = 0, endpos: int = sys.maxsize) -> Any:
        self._spent[0] += self._window(string, pos, endpos)
        return self._pattern.match(string, pos, endpos)

    def search(self, string: str, pos: int = 0, endpos: int = sys.maxsize) -> Any:
        self._spent[0] += self._window(string, pos, endpos) ** 2
        return self._pattern.search(string, pos, endpos)

    def sub(self, repl: Any, string: str, count: int = 0) -> str:
        self._spent[0] += len(string) ** 2
        return self._pattern.sub(repl, string, count)

    def finditer(self, string: str, pos: int = 0, endpos: int = sys.maxsize) -> Any:
        self._spent[0] += self._window(string, pos, endpos) ** 2
        return self._pattern.finditer(string, pos, endpos)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pattern, name)


@contextmanager
def _charged() -> Iterator[list[int]]:
    """The characters the remote-phrase patterns may read inside the block, plus the Python calls
    the reading makes."""
    spent = [0]
    with (
        mock.patch.object(reading, "_REMOTE_JOB", _Charged(reading._REMOTE_JOB, spent)),
        mock.patch.object(reading, "_CI_RUN_URL", _Charged(reading._CI_RUN_URL, spent)),
        mock.patch.object(reading, "_PATH_AFTER", _Charged(reading._PATH_AFTER, spent)),
    ):

        def counting(_frame: Any, event: str, _arg: Any) -> None:
            spent[0] += event == "call"

        sys.setprofile(counting)
        try:
            yield spent
        finally:
            sys.setprofile(None)


# Reasons shaped to make a restarting scan read every token to its end, by length.
_HOSTILE: dict[str, Callable[[int], str]] = {
    "dotted then joined": lambda n: "a." * (n // 2) + "-a",
    "slash-joined": lambda n: "a/" * (n // 2),
    "a URL of segments": lambda n: "https://x/" + "x/" * (n // 2),
    "repeated schemes": lambda n: "http://" * (n // 7),
    "slash jobs that pass": lambda n: "a/b passes " * (n // 11),
    "quoted jobs": lambda n: "'x-y' " * (n // 6),
    "a dotted result": lambda n: "a." * (n // 2) + " passes",
    "run URLs": lambda n: "https://x/actions/runs/1 " * (n // 25),
}


class TheRemotePhraseMatchersAreLinear(unittest.TestCase):
    def work(self, text: str) -> int:
        with _charged() as spent:
            reading._verdict_check_kinds(text)
        return spent[0]

    def test_a_goal_of_sixteen_thousand_characters_is_read_in_linear_work(self) -> None:
        for name, make in _HOSTILE.items():
            for size in (4_000, 16_000):
                with self.subTest(shape=name, size=size):
                    small, large = self.work(make(size)), self.work(make(2 * size))
                    self.assertLess(large, 2.5 * small, (small, large))
                    self.assertLess(small, 40 * size, small)

    def test_a_hundred_thousand_character_reason_is_read_in_well_under_a_second(self) -> None:
        if sys.gettrace() is not None or "coverage" in sys.modules:
            self.skipTest("timed without a tracer only")
        for name, make in _HOSTILE.items():
            with self.subTest(shape=name):
                started = time.process_time()
                reading._verdict_check_kinds(make(100_000))
                self.assertLess(time.process_time() - started, 2.0)

    def test_a_reason_is_split_into_clauses_once(self) -> None:
        with mock.patch.object(reading, "_local_clauses", wraps=reading._local_clauses) as clauses:
            reading._verdict_check_kinds("the server-unittest pass and pytest passed")
        self.assertEqual(1, clauses.call_count)


class EveryReasonTheOldMatchersReadIsReadTheSameWay(unittest.TestCase):
    def test_a_remote_job_is_found_where_the_old_pattern_found_it(self) -> None:
        for text in (*_texts(_JOB_PIECES, 5016, 20_000), *_shaped_job_texts(5016, 20_000)):
            with self.subTest(text=text):
                self.assertEqual(
                    _spans(_OLD_REMOTE_JOB.finditer(text)), _spans(reading._remote_jobs(text))
                )
                self.assertEqual(
                    _OLD_REMOTE_JOB.sub(_old_drop_remote_job, text),
                    reading._drop_remote_jobs(text),
                )

    def test_a_run_url_is_found_where_the_old_pattern_found_it(self) -> None:
        for text in (*_texts(_URL_PIECES, 5070, 20_000), *_shaped_url_texts(5070, 20_000)):
            with self.subTest(text=text):
                self.assertEqual(
                    _spans(_OLD_CI_RUN_URL.finditer(text)), _spans(reading._ci_run_urls(text))
                )

    def test_a_reason_the_old_matchers_read_as_remote_is_read_the_same_way(self) -> None:
        for text in (
            "the server-unittest pass shows it",
            "'server-unittest' passed and `ci/lint` failed",
            "tests in tests/unit pass",
            "type-check/lint-x passes",
            "14/14 pass",
            "the tests passed https://github.com/acme/widgets/actions/runs/123456 today",
            "see http://a http://b/pipelines/9/x and HTTPS://c/jobs/12",
        ):
            with self.subTest(text=text):
                old = _OLD_REMOTE_JOB.sub(
                    _old_drop_remote_job,
                    _OLD_CI_RUN_URL.sub(f" {reading._REMOTE_MARK} ", text),
                )
                self.assertEqual(
                    [
                        clause
                        for clause in reading._CLAIM_CLAUSE_BREAK.split(old)
                        if not reading._REMOTE_CLAUSE.search(clause)
                    ],
                    reading._local_clauses(text),
                )


if __name__ == "__main__":
    unittest.main()
