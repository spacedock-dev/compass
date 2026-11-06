"""A reader pages through the same bounded titles as the project context."""

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

from compass_runtime import copied_corrections, project_context, reading
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from .support import make_server, poll_fast


class RecordPagesTest(unittest.TestCase):
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
        self.key = b"synthetic-test-key"

    @staticmethod
    def record(
        n: int, *, harness: str = "claude", role: str = "user", text: str | None = None
    ) -> dict[str, Any]:
        words = text or f"Build synthetic step {n}. Later words stay private."
        stamp = f"2026-10-01T00:{n // 60:02}:{n % 60:02}Z"
        if harness == "codex":
            return {
                "type": "response_item",
                "timestamp": stamp,
                "payload": {"type": "message", "role": role, "content": words},
            }
        return {
            "type": role,
            "timestamp": stamp,
            "uuid": f"record-{n}",
            "message": {"role": role, "content": [{"type": "text", "text": words}]},
        }

    def write(self, rows: list[dict[str, Any]]) -> None:
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def page(self, **kwargs: Any) -> dict[str, Any]:
        self.assertIsNotNone(
            importlib.util.find_spec("compass_runtime.record_pages"),
            "the reader needs a bounded backward record reader",
        )
        module = importlib.import_module("compass_runtime.record_pages")
        return dict(
            module.read(
                self.config, str(self.path), "claude", "root", cursor_key=self.key, **kwargs
            )
        )

    def test_a_reader_with_a_week_long_session_sees_the_newest_fifty_entries_first(self) -> None:
        self.write([self.record(n, role="assistant" if n % 2 else "user") for n in range(130)])
        page = self.page()
        self.assertEqual(50, len(page["entries"]))
        self.assertEqual("Build synthetic step 129.", page["entries"][0]["summary"])
        self.assertFalse(page["reached_start"])
        self.assertIsNotNone(page["next"])
        self.assertIsNone(page["bound"])

    def test_a_reader_crossing_chunk_boundaries_gets_every_forward_scanned_entry_once(self) -> None:
        rows = [self.record(n, text=f"Build step {n}. " + "x" * (n * 23)) for n in range(17)]
        self.write(rows)
        self.config = dataclasses.replace(self.config, record_page_chunk_bytes=97)
        found = []
        cursor = None
        for _ in range(30):
            page = self.page(limit=3, before=cursor)
            found.extend(page["entries"])
            cursor = page["next"]
            if cursor is None:
                self.assertTrue(page["reached_start"])
                break
        self.assertEqual(17, len(found))
        self.assertEqual(17, len({row["fact_id"] for row in found}))
        events = project_context.instruction_events(self.config, str(self.path), "claude", "root")
        expected = project_context.for_page(
            [
                project_context._semantic_fact_from_event(event, "steer", "user_message", "")
                for event in events
            ]
        )
        self.assertEqual(
            sorted(expected, key=lambda row: row["fact_id"]),
            sorted(found, key=lambda row: row["fact_id"]),
        )

    def test_a_reader_sees_masked_titles_and_the_same_agent_fact_ids_as_context(self) -> None:
        secret = "sk-ant-api03-" + "a" * 93
        self.write(
            [
                self.record(1, text="Build with " + secret + ". Private second sentence."),
                self.record(2, role="assistant", text="Finished safely. Private agent words."),
            ]
        )
        page = self.page()
        self.assertNotIn(secret, json.dumps(page))
        self.assertNotIn("Private", json.dumps(page))
        self.assertIn("REDACTED", json.dumps(page))
        events = project_context.instruction_events(self.config, str(self.path), "claude", "root")
        events += project_context.agent_message_events(
            self.config, str(self.path), "claude", "root"
        )
        expected = project_context.for_page(
            [
                project_context._semantic_fact_from_event(
                    event,
                    event["kind"],
                    "user_message" if event["kind"] == "steer" else "agent_message",
                    "",
                )
                for event in events
            ]
        )
        self.assertEqual(
            sorted(expected, key=lambda row: row["fact_id"]),
            sorted(page["entries"], key=lambda row: row["fact_id"]),
        )

    def test_a_reader_gets_the_same_fields_from_the_collected_context(self) -> None:
        self.write([self.record(1), self.record(2, role="assistant")])
        page = self.page()
        row = {
            "harness": "claude",
            "sid": "root",
            "project": "synthetic",
            "state": "idle",
            "active": True,
        }
        with mock.patch("compass_runtime.observer.resolve_transcript", return_value=str(self.path)):
            context = project_context.collect(
                self.config,
                build_runtime_state(self.config, started=1),
                [row],
                "synthetic",
                now=page["entries"][0]["at"],
                focus=("claude", "root"),
            )
        facts = project_context.for_page(context)["semantic"]["facts"]
        messages = [fact for fact in facts if fact["type"] in ("user_message", "agent_message")]
        self.assertEqual(
            sorted(messages, key=lambda row: row["fact_id"]),
            sorted(page["entries"], key=lambda row: row["fact_id"]),
        )

    def test_a_reader_can_continue_after_the_real_sixty_four_mib_budget(self) -> None:
        self.write([self.record(1)])
        with self.path.open("ab") as handle:
            handle.write(b'{"type":"image","data":"' + b"x" * (65 * 1024 * 1024) + b'"}\n')
        page = self.page()
        self.assertEqual(64 * 1024 * 1024, page["scanned_bytes"])
        self.assertFalse(page["reached_start"])
        self.assertEqual("bytes", page["bound"])
        self.assertIsNotNone(page["next"])
        rest = self.page(before=page["next"])
        self.assertEqual(1, len(rest["entries"]))
        self.assertTrue(rest["reached_start"])

    def test_a_reader_keeps_a_prompt_split_by_the_page_byte_budget(self) -> None:
        self.write([self.record(n, text=f"Build step {n}. " + "x" * 100) for n in range(7)])
        self.config = dataclasses.replace(
            self.config, record_page_max_bytes=550, record_page_chunk_bytes=71
        )
        cursor = None
        ids: list[str] = []
        for _ in range(10):
            page = self.page(before=cursor)
            ids.extend(fact["fact_id"] for fact in page["entries"])
            cursor = page["next"]
            if cursor is None:
                break
        self.assertEqual(7, len(ids))
        self.assertEqual(7, len(set(ids)))

    def test_a_reader_can_continue_after_an_image_filled_byte_budget(self) -> None:
        self.write([self.record(1), {"type": "image", "data": "x" * 500}])
        self.config = dataclasses.replace(
            self.config, record_page_max_bytes=128, record_page_chunk_bytes=32
        )
        page = self.page()
        self.assertEqual([], page["entries"])
        self.assertFalse(page["reached_start"])
        self.assertEqual("bytes", page["bound"])
        self.assertEqual(128, page["scanned_bytes"])
        self.assertIsNotNone(page["next"])
        self.config = dataclasses.replace(self.config, record_page_max_bytes=1024)
        rest = self.page(before=page["next"])
        self.assertEqual(["Build synthetic step 1."], [row["summary"] for row in rest["entries"]])
        self.assertTrue(rest["reached_start"])

    def test_a_reader_restarts_when_the_source_shrinks_is_replaced_or_rewritten(self) -> None:
        for change in ("shrink", "replace", "rewrite"):
            with self.subTest(change=change):
                self.write([self.record(n) for n in range(8)])
                cursor = self.page(limit=2)["next"]
                if change == "shrink":
                    self.write([self.record(1)])
                elif change == "replace":
                    self.path.rename(self.root / "old.jsonl")
                    self.write([self.record(n) for n in range(8)])
                else:
                    self.path.write_bytes(self.path.read_bytes().replace(b"Build", b"Check"))
                page = self.page(before=cursor)
                self.assertEqual("stale", page["state"])
                self.assertEqual([], page["entries"])
                self.assertFalse(page["reached_start"])

    def test_a_reader_can_page_an_appending_session_without_duplicates(self) -> None:
        self.write([self.record(n) for n in range(8)])
        page = self.page(limit=3)
        with self.path.open("a") as handle:
            handle.write(json.dumps(self.record(8)) + "\n")
        rest = self.page(before=page["next"])
        self.assertEqual("ok", rest["state"])
        self.assertEqual(5, len(rest["entries"]))
        self.assertFalse(
            {row["fact_id"] for row in page["entries"]}
            & {row["fact_id"] for row in rest["entries"]}
        )

    def test_a_reader_restarts_when_a_previously_grown_file_shrinks(self) -> None:
        self.write([self.record(n) for n in range(8)])
        first = self.page(limit=2)
        with self.path.open("a") as handle:
            for n in (8, 9):
                handle.write(json.dumps(self.record(n)) + "\n")
        second = self.page(limit=2, before=first["next"])
        self.write([self.record(n) for n in range(9)])
        self.assertEqual("stale", self.page(before=second["next"])["state"])

    def test_a_reader_gets_a_stale_reply_with_measured_bytes_if_the_source_vanishes_mid_page(
        self,
    ) -> None:
        self.write([self.record(n) for n in range(8)])
        size = self.path.stat().st_size
        build = project_context._instruction_event

        def moved(*args: Any, **kwargs: Any) -> Any:
            self.path.unlink(missing_ok=True)
            return build(*args, **kwargs)

        with mock.patch.object(project_context, "_instruction_event", side_effect=moved):
            page = self.page(limit=2)
        self.assertEqual("stale", page["state"])
        self.assertEqual(size, page["scanned_bytes"])
        self.assertEqual([], page["entries"])

    def test_a_reader_cannot_use_another_files_cursor_or_a_tampered_cursor(self) -> None:
        self.write([self.record(n) for n in range(8)])
        cursor = self.page(limit=2)["next"]
        other = self.root / "other.jsonl"
        other.write_bytes(self.path.read_bytes())
        original = self.path
        self.path = other
        self.assertEqual("stale", self.page(before=cursor)["state"])
        self.path = original
        for value in ("!", "a" * 2000, cursor[:-1] + ("A" if cursor[-1] != "A" else "B")):
            self.assertEqual("stale", self.page(before=value)["state"])

    def test_a_reader_gets_an_honest_unsupported_or_unavailable_state(self) -> None:
        self.write([])
        module = importlib.import_module("compass_runtime.record_pages")
        self.assertEqual(
            "unsupported",
            module.read(self.config, str(self.path), "pi", "root", cursor_key=self.key)["state"],
        )
        self.path.unlink()
        self.assertEqual("unavailable", self.page()["state"])

    def test_a_reader_gets_codex_user_messages_under_the_existing_contract(self) -> None:
        self.write(
            [self.record(1, harness="codex"), self.record(2, harness="codex", role="assistant")]
        )
        module = importlib.import_module("compass_runtime.record_pages")
        page = module.read(self.config, str(self.path), "codex", "root", cursor_key=self.key)
        self.assertEqual(["user_message"], [row["type"] for row in page["entries"]])
        self.assertEqual(["user_message", "agent_message"], page["kinds"])

    def test_a_reader_does_not_treat_a_partial_last_line_as_a_complete_entry(self) -> None:
        self.write([self.record(1)])
        with self.path.open("ab") as handle:
            handle.write(b'{"type":"user","message":')
        page = self.page()
        self.assertEqual(1, len(page["entries"]))
        self.assertTrue(page["reached_start"])

    def test_a_reader_can_continue_after_the_clock_budget(self) -> None:
        self.write([self.record(n) for n in range(8)])
        with mock.patch("compass_runtime.record_pages.time.monotonic", side_effect=[0.0, 6.0]):
            page = self.page()
        self.assertFalse(page["reached_start"])
        self.assertEqual("time", page["bound"])
        self.assertIsNotNone(page["next"])
        self.assertEqual(0, page["scanned_bytes"])
        self.assertEqual(8, len(self.page(before=page["next"])["entries"]))

    def test_a_reader_keeps_the_copied_correction_flag_after_page_projection(self) -> None:
        self.write([self.record(1)])
        page = self.page()
        fact_id = page["entries"][0]["fact_id"]
        marked = copied_corrections.mark(
            {"semantic": {"facts": page["entries"]}},
            [
                {
                    "harness": "claude",
                    "sid": "root",
                    reading.COPIED_PROMPTS: [{"fact_id": fact_id}],
                }
            ],
        )
        self.assertTrue(project_context.for_page(marked)["semantic"]["facts"][0]["copied"])

    def test_a_reader_gets_pages_only_for_a_bounded_known_project_session(self) -> None:
        self.write([self.record(n) for n in range(60)])
        server = make_server()
        self.addCleanup(server.server_close)
        row: dict[str, Any] = {
            "harness": "claude",
            "sid": "root",
            "project": "example",
            "project_key": "git:example",
        }
        event = project_context._instruction_event(self.config, self.record(59), "claude", "root")
        assert event is not None
        fact = project_context._semantic_fact_from_event(event, "steer", "user_message", "")
        row[reading.COPIED_PROMPTS] = [{"fact_id": fact["fact_id"]}]
        server.application.collect_json = lambda **_: (1, json.dumps({"sessions": [row]}).encode())
        thread = threading.Thread(target=poll_fast(server), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)

        def request(query: str, **headers: str) -> tuple[int, Any]:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
            connection.request("GET", "/api/session-record" + query, headers=headers)
            response = connection.getresponse()
            body = response.read()
            connection.close()
            return response.status, json.loads(body) if response.status == 200 else None

        with mock.patch("compass_runtime.observer.resolve_transcript", return_value=str(self.path)):
            status, page = request("?project=git:example&session=claude:root")
            self.assertEqual(200, status)
            self.assertEqual(50, len(page["entries"]))
            self.assertTrue(page["entries"][0]["copied"])
            self.assertNotIn("reader_words", json.dumps(page))
            # Each message carries its fixed number: 60 messages, newest first, so 60 down to 11 here
            # and the older page picks up at 10 whatever was loaded before it (DRC-4897).
            self.assertEqual(list(range(60, 10, -1)), [e["ordinal"] for e in page["entries"]])
            older = request("?project=git:example&session=claude:root&before=" + page["next"])[1]
            self.assertEqual(list(range(10, 0, -1)), [e["ordinal"] for e in older["entries"]])
            for query in (
                "",
                "?project=example",
                "?project=example&session=bad",
                "?project=" + "x" * 2000 + "&session=claude:root",
            ):
                self.assertEqual(400, request(query)[0])
            self.assertEqual(
                403, request("?project=example&session=claude:root", Host="evil.example")[0]
            )
            self.assertEqual(
                "unavailable", request("?project=elsewhere&session=claude:root")[1]["state"]
            )
            self.assertEqual(
                1, len(request("?project=example&session=claude:root&limit=0")[1]["entries"])
            )
            self.assertEqual(
                50, len(request("?project=example&session=claude:root&limit=500")[1]["entries"])
            )
            self.assertEqual(
                1,
                len(
                    request("?project=example&session=claude:root&limit=-" + "9" * 100)[1][
                        "entries"
                    ]
                ),
            )
