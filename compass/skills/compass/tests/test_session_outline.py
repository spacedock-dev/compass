"""The focused outline groups recorded evidence without a model or word publication."""

from __future__ import annotations

import dataclasses
import http.client
import importlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlparse

from compass_runtime import http_api, observer
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from . import test_record_pages
from .support import make_server, poll_fast
from .test_claude_checks import Transcript


class SessionOutlineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "session.jsonl"
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.state = build_runtime_state(self.config, started=1)
        self.outline = importlib.import_module("compass_runtime.session_outline")
        self.source = importlib.import_module("compass_runtime.session_source")

    def test_blocks_include_leading_work_spans_counts_failures_and_folders(self) -> None:
        transcript = Transcript(self.root)
        transcript.bash("pytest tests", "1 failed", is_error=True)
        transcript.prompt("Change the synthetic module.")
        transcript.write(str(self.root / "src/a.py"))
        transcript.bash("pytest tests", "1 passed")
        transcript.prompt("Add another synthetic case.")
        transcript.save(self.path)
        page = self.source.read(self.config, str(self.path), "claude", "root")
        result = self.outline.build(page, self.config)
        self.assertEqual(("compass", "grouping"), (result["made_by"], result["basis"]))
        self.assertEqual(3, len(result["blocks"]))
        leading, middle, last = result["blocks"]
        self.assertIsNone(leading["prompt"])
        self.assertEqual(1, leading["counts"]["checks_failed"])
        self.assertEqual("failed", leading["failures"][0]["result"])
        self.assertEqual(3, middle["span"]["entries"])
        self.assertEqual([{"folder": "src", "files": 1}], middle["folders"])
        self.assertEqual(page.entries[-1].fact_id, last["span"]["last"])
        self.assertNotIn('"words":', json.dumps(result))

    def test_block_cap_keeps_newest_and_counts_dropped_blocks(self) -> None:
        self.path.write_text(
            "".join(
                json.dumps(test_record_pages.RecordPagesTest.record(i)) + "\n" for i in range(5)
            )
        )
        config = dataclasses.replace(self.config, session_outline_max_blocks=2)
        result = self.outline.build(
            self.source.read(config, str(self.path), "claude", "root"), config
        )
        self.assertEqual(3, result["more_blocks"])
        self.assertEqual(
            ["Build synthetic step 3.", "Build synthetic step 4."],
            [b["prompt"]["title"] for b in result["blocks"]],
        )

    def test_highlights_are_bounded_and_counts_are_not(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Run synthetic checks.")
        for n in range(6):
            transcript.bash(f"pytest tests/test_{n}.py", "1 failed", is_error=True)
            transcript.write(str(self.root / f"folder{n}/a.py"))
        transcript.save(self.path)
        config = dataclasses.replace(self.config, session_outline_highlights=2)
        block = self.outline.build(
            self.source.read(config, str(self.path), "claude", "root"), config
        )["blocks"][0]
        self.assertEqual(6, block["counts"]["checks_failed"])
        for key in ("checks", "failures", "folders"):
            self.assertEqual(2, len(block[key]))

    def test_cache_reuses_object_and_rebuilds_after_append(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Read the synthetic record.")
        transcript.save(self.path)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first = self.outline.for_session(self.config, self.state, "claude", "root")
            with mock.patch.object(
                self.source, "read", side_effect=AssertionError("cache must stat only")
            ):
                self.assertIs(
                    first, self.outline.for_session(self.config, self.state, "claude", "root")
                )
            transcript.prompt("Read the next synthetic record.")
            transcript.save(self.path)
            later = self.outline.for_session(self.config, self.state, "claude", "root")
        self.assertIsNot(first, later)
        self.assertEqual(2, len(later["blocks"]))

    def test_unsupported_does_not_resolve_or_stat(self) -> None:
        with mock.patch.object(
            observer, "resolve_transcript", side_effect=AssertionError("no disk")
        ):
            result = self.outline.for_session(self.config, self.state, "pi", "root")
        self.assertEqual(
            ("unsupported", "no_paged_record", []),
            (result["state"], result["reason"], result["blocks"]),
        )

    def test_cache_rebuilds_for_child_only_append(self) -> None:
        parent = Transcript(self.root)
        parent.prompt("Delegate synthetic checks.")
        parent.save(self.path)
        child = Transcript(self.root)
        child.bash("pytest tests", "1 passed")
        path = self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl"
        for row in child.rows:
            row["isSidechain"] = True
        child.save(path)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first = self.outline.for_session(self.config, self.state, "claude", "root")
            child.bash("pytest tests", "1 failed", is_error=True)
            for row in child.rows:
                row["isSidechain"] = True
            child.save(path)
            later = self.outline.for_session(self.config, self.state, "claude", "root")
        self.assertIsNot(first, later)
        self.assertEqual(1, sum(block["counts"]["checks_failed"] for block in later["blocks"]))

    def check_handler(self, handler: Any) -> None:
        application = handler.server.application
        application.config = self.config
        application.state = self.state
        row = {"harness": "claude", "sid": "root", "project": "synthetic"}
        application.collect_json = lambda **_: (1, json.dumps({"sessions": [row]}).encode())
        for harness in ("claude", "codex", "pi"):
            row["harness"] = harness
            self.path.write_text(
                json.dumps(test_record_pages.RecordPagesTest.record(1, harness=harness)) + "\n"
            )
            with (
                mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
                mock.patch.object(
                    observer, "prepare_claude_exec", side_effect=AssertionError("no model")
                ) as claude,
                mock.patch.object(
                    observer, "codex_exec", side_effect=AssertionError("no model")
                ) as codex,
            ):
                result = self.request(
                    handler, f"/api/project-context?project=synthetic&session={harness}:root"
                )
            self.assertEqual(0, claude.call_count + codex.call_count)
            outline = result["sources"]["outline"]
            self.assertEqual("unsupported" if harness == "pi" else "ok", outline["state"])
            if harness == "pi":
                self.assertEqual("no_paged_record", outline["reason"])
            else:
                self.assertEqual(1, len(outline["blocks"]))
                self.assertEqual(
                    "not_read" if harness == "codex" else "read",
                    outline["coverage"]["agent_replies"],
                )
            self.assertNotIn('"words":', json.dumps(outline))
        self.assertNotIn(
            "outline", self.request(handler, "/api/project-context?project=synthetic")["sources"]
        )

    def request(self, handler: Any, path: str) -> Any:
        handler._project_context(urlparse(path))
        return json.loads(handler._send.call_args.args[0])

    def test_focused_http_handler_adds_outline_without_model_consent(self) -> None:
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = mock.Mock(application=mock.Mock())
        handler.server.application.clock.return_value = 1_790_000_000.0
        handler._local_ok = lambda: True
        handler._send = mock.Mock()
        self.check_handler(handler)

    def test_focused_http_over_ephemeral_loopback(self) -> None:
        try:
            server = make_server()
        except PermissionError:
            self.skipTest("sandbox denies loopback socket binding")
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=poll_fast(server), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        handler = mock.Mock(server=server)

        def request(_handler: Any, path: str) -> Any:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            self.addCleanup(connection.close)
            connection.request("GET", path)
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            return json.loads(response.read())

        with mock.patch.object(self, "request", side_effect=request):
            self.check_handler(handler)
