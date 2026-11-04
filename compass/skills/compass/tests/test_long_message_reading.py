"""Later source words reach a bounded producer without becoming new evidence identities."""

from __future__ import annotations

import dataclasses
import json
import re
import unittest
from pathlib import Path

from compass_runtime import session_source, session_summary
from compass_runtime.config import build_runtime_config

from .test_session_summary import Replies, entry


class SummaryMessageTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = build_runtime_config(
            environ={"HOME": "/synthetic"},
            platform_name="linux",
            os_name="posix",
            launcher_path=Path("/synthetic/server.py"),
        )
        self.coverage = session_source.SourceCoverage(True, None, 0, 100, (), "read", "read")

    def test_later_user_and_agent_words_reach_the_summary(self) -> None:
        rows = [
            entry(1, "person", "Review the parser. " + "context " * 200 + "LATE_PERSON 界🙂"),
            entry(2, "agent", "I read parser.py. " + "context " * 200 + "LATE_AGENT 界🙂"),
        ]
        model = Replies()
        result = session_summary.summarize(
            rows, self.coverage, "claude", config=self.config, model=model, clock=lambda: 0
        )
        self.assertEqual("ok", result.state)
        record = model.prompts[0].split("Record:\n", 1)[1]
        self.assertIn("LATE_PERSON 界🙂", record)
        self.assertIn("LATE_AGENT 界🙂", record)

    def test_long_message_fragments_cover_the_original_text_and_cite_one_fact(self) -> None:
        words = "Review parser. " + "界🙂 prose " * 300 + "LATE_FINDING"
        model = Replies()
        result = session_summary.summarize(
            [entry(1, "person", words)],
            self.coverage,
            "claude",
            config=dataclasses.replace(self.config, session_summary_window_bytes=800),
            model=model,
            clock=lambda: 0,
        )
        windows = [p.split("Record:\n", 1)[1] for p in model.prompts if "Reply with one" in p]
        self.assertGreater(len(windows), 1)
        fragments = []
        for window in windows:
            self.assertLessEqual(len(window.encode()), 800)
            for line in window.splitlines():
                match = re.fullmatch(r"\[1\] asked \(characters (\d+)-(\d+) of (\d+)\): (.*)", line)
                self.assertIsNotNone(match, line)
                assert match is not None
                fragment = json.loads(match[4])
                self.assertEqual(len("".join(fragments)), int(match[1]))
                self.assertEqual(len(fragment), int(match[2]) - int(match[1]))
                self.assertEqual(len(words), int(match[3]))
                fragments.append(fragment)
        self.assertEqual(words, "".join(fragments))
        self.assertEqual({"fact-1"}, {c for b in result.blocks for p in b.phases for row in p.bullets for c in row.cites})

