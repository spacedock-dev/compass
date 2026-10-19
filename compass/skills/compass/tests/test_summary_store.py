"""Durable summaries stay separate from saved intent and never invoke a model."""

from __future__ import annotations

import dataclasses
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import cli, lifecycle, session_source, session_summary
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from .test_claude_checks import Transcript
from .test_session_summary import Replies


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = importlib.import_module("compass_runtime.summary_store")
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
        self.transcript = Transcript(self.root)
        self.state = build_runtime_state(self.config, started=0.0)

    def read(self) -> session_source.SourcePage:
        self.transcript.save(self.path)
        return session_source.read(self.config, str(self.path), "claude", "root")

    def save(self, page: session_source.SourcePage, sid: str = "root", **kw: Any) -> None:
        assert page.coverage is not None
        summary = session_summary.summarize(
            page.entries,
            page.coverage,
            "claude",
            config=self.config,
            model=Replies(),
            clock=lambda: 0.0,
        )
        self.assertEqual(
            "stored",
            self.store.put(
                self.config,
                "claude",
                sid,
                summary,
                page.snapshot,
                made_at=100.0,
                model_stamp="synthetic-model",
                **kw,
            ),
        )

    def focused(self) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.store.focused(self.config, "claude", "root", self.read(), now=200.0),
        )


class SummaryStoreTest(_StoreCase):
    def test_round_trip_keeps_blocks_coverage_model_and_time(self) -> None:
        self.transcript.prompt("Inspect the parser")
        page = self.read()
        self.save(page)
        record = self.store.get(self.config, "claude", "root", now=110.0)
        self.assertIsNotNone(record)
        self.assertEqual("synthetic-model", record.model_stamp)
        self.assertEqual(100, record.made_at)
        self.assertEqual(page.coverage, record.summary.coverage)
        self.assertEqual("unchanged", self.focused()["out_of_date"]["kind"])
        self.assertEqual(0o600, os.stat(self.store.store_path(self.config)).st_mode & 0o777)

    def test_previous_schema_is_unavailable_and_normal_save_preserves_file(self) -> None:
        self.transcript.prompt("Inspect the parser")
        page = self.read()
        self.save(page)
        path = Path(self.store.store_path(self.config))
        raw = json.loads(path.read_text())
        raw["v"] = 1
        path.write_text(json.dumps(raw))
        before = path.read_bytes()
        self.assertEqual("unavailable", self.store.load(self.config).state)
        record = raw["entries"][0]
        assert page.coverage is not None
        summary = session_summary.summarize(
            page.entries,
            page.coverage,
            "claude",
            config=self.config,
            model=Replies(),
            clock=lambda: 0.0,
        )
        self.assertEqual(
            "unavailable",
            self.store.put(
                self.config,
                "claude",
                "root",
                summary,
                page.snapshot,
                made_at=200.0,
                model_stamp=record["model_stamp"],
            ),
        )
        self.assertEqual("unavailable", self.store.delete(self.config, "claude", "root"))
        self.assertEqual(before, path.read_bytes())

    def test_append_reports_new_entry_count_and_update(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        self.transcript.prompt("Inspect more")
        result = self.focused()["out_of_date"]
        self.assertEqual(
            ("appended", 1, "update"), (result["kind"], result["new_entries"], result["action"])
        )

    def test_changed_earlier_check_names_affected_block(self) -> None:
        self.transcript.bash("pytest tests", "1 passed")
        self.transcript.prompt("Next phase " + "x" * 120)
        page = self.read()
        self.config = dataclasses.replace(self.config, session_summary_window_bytes=100)
        self.save(page)
        self.transcript.bash("pytest tests", "1 failed", is_error=True)
        result = self.focused()["out_of_date"]
        self.assertEqual("changed_earlier", result["kind"])
        self.assertEqual("summarize_again", result["action"])
        self.assertIn(0, result["affected_blocks"])

    def test_newest_check_result_is_appendable(self) -> None:
        call = self.transcript.call("Bash", {"command": "pytest tests"})
        self.save(self.read())
        self.transcript.result(call, "1 passed", is_error=False)
        result = self.focused()["out_of_date"]
        self.assertEqual("changed_earlier", result["kind"])
        self.assertEqual("update", result["action"])
        self.assertTrue(result["appendable"])

    def test_rewritten_earlier_file_requires_new_summary(self) -> None:
        self.transcript.write(str(self.root / "a.py"))
        self.save(self.read())
        self.transcript.edit(str(self.root / "a.py"))
        self.assertEqual("changed_earlier", self.focused()["out_of_date"]["kind"])
        self.assertEqual("summarize_again", self.focused()["out_of_date"]["action"])

    def test_truncation(self) -> None:
        self.transcript.prompt("Inspect")
        self.transcript.prompt("Continue")
        self.save(self.read())
        self.transcript.rows.pop()
        self.assertEqual("truncated", self.focused()["out_of_date"]["kind"])

    def test_replaced_source(self) -> None:
        self.transcript.prompt("Inspect")
        page = self.read()
        self.save(page)
        replacement = self.root / "replacement"
        replacement.write_bytes(self.path.read_bytes())
        os.replace(replacement, self.path)
        current = session_source.read(self.config, str(self.path), "claude", "root")
        self.assertEqual(
            "replaced",
            self.store.focused(self.config, "claude", "root", current)["out_of_date"]["kind"],
        )

    def test_secret_rewritten_on_disk_is_redacted_on_read(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        path = Path(self.store.store_path(self.config))
        raw = json.loads(path.read_text())
        raw["entries"][0]["summary"]["lede"]["text"] = "token ghp_" + "A" * 36
        path.write_text(json.dumps(raw))
        record = self.store.get(self.config, "claude", "root")
        self.assertNotIn("A" * 36, json.dumps(record.summary.as_dict()))
        self.assertIn("REDACTED", json.dumps(record.summary.as_dict()))

    def test_torn_file_is_unavailable_and_not_overwritten(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        path = Path(self.store.store_path(self.config))
        path.write_text('{"v":1,"entries":[')
        self.assertEqual("unavailable", self.store.load(self.config).state)
        self.assertEqual("unavailable", self.store.delete(self.config, "claude", "root"))
        self.assertEqual('{"v":1,"entries":[', path.read_text())

    def test_oversized_file_is_unavailable(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        small = dataclasses.replace(self.config, summary_store_max_bytes=10)
        self.assertEqual("unavailable", self.store.load(small).state)

    def test_unknown_schema_is_unavailable(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        path = Path(self.store.store_path(self.config))
        raw = json.loads(path.read_text())
        raw["v"] = 999
        path.write_text(json.dumps(raw))
        self.assertEqual("unavailable", self.store.load(self.config).state)

    def test_unknown_record_field_refuses_whole_file(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        path = Path(self.store.store_path(self.config))
        raw = json.loads(path.read_text())
        raw["entries"][0]["source"]["words"] = "not admitted"
        path.write_text(json.dumps(raw))
        self.assertEqual("unavailable", self.store.load(self.config).state)

    def test_two_writers_keep_whole_records(self) -> None:
        self.transcript.prompt("Inspect")
        page = self.read()
        self.save(page)
        record = self.store.get(self.config, "claude", "root")

        def write(n: int) -> str:
            return str(
                self.store.put(
                    self.config,
                    "claude",
                    str(n),
                    record.summary,
                    page.snapshot,
                    made_at=float(n),
                    model_stamp=str(n),
                )
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(["stored"] * 20, list(pool.map(write, range(20))))
        loaded = self.store.load(self.config)
        self.assertEqual("ok", loaded.state)
        self.assertEqual(21, len(loaded.entries))
        self.assertTrue(all(e.model_stamp == e.sid for e in loaded.entries if e.sid != "root"))

    @unittest.skipIf(os.name != "posix", "flock is the POSIX half of the writer lock")
    def test_another_process_holding_the_lock_blocks_a_writer(self) -> None:
        self.transcript.prompt("Inspect")
        page = self.read()
        self.save(page)
        record = self.store.get(self.config, "claude", "root")
        path = Path(self.store.store_path(self.config))
        before = path.read_bytes()
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import fcntl,sys\n"
                    "f=open(sys.argv[1],'a+')\n"
                    "fcntl.flock(f,fcntl.LOCK_EX)\n"
                    "print('held',flush=True)\n"
                    "sys.stdin.read()\n"
                ),
                str(path) + ".lock",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual("held\n", holder.stdout.readline() if holder.stdout else "")
            short = dataclasses.replace(self.config, summary_store_lock_wait_sec=0.2)
            outcome = self.store.put(
                short,
                "claude",
                "other",
                record.summary,
                page.snapshot,
                made_at=1.0,
                model_stamp="m",
            )
            self.assertEqual("unwritable", outcome)
            self.assertEqual(before, path.read_bytes())
        finally:
            holder.communicate("", timeout=10)
        self.assertEqual(
            "stored",
            self.store.put(
                self.config,
                "claude",
                "other",
                record.summary,
                page.snapshot,
                made_at=1.0,
                model_stamp="m",
            ),
        )

    def test_eviction_at_bound_never_touches_saved_intent(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        record = self.store.get(self.config, "claude", "root")
        annotations_path = Path(annotation_store.store_path(self.config))
        self.assertEqual(
            "stored",
            annotation_store.annotate(
                self.config,
                self.state,
                "claude",
                "root",
                goal="Keep my saved intent",
                now=90.0,
            ),
        )
        original = annotations_path.read_bytes()
        cites = tuple(f"fact-{n}-" + "x" * 56 for n in range(8))
        bullet = session_summary.Bullet(session_summary.Display("🙂" * 200), "did", cites, False)
        phase = session_summary.Phase(session_summary.Display("x" * 60), (bullet,) * 6)
        blocks: tuple[session_summary.Block, ...] = ()
        while True:
            block = session_summary.Block(
                cites[0],
                cites[-1],
                8,
                "a" * 32,
                (phase,) * 4,
            )
            candidate = dataclasses.replace(record.summary, blocks=(*blocks, block))
            if (
                len(
                    json.dumps(
                        candidate.as_dict(), ensure_ascii=False, separators=(",", ":")
                    ).encode()
                )
                > self.config.session_summary_max_bytes
            ):
                break
            blocks = candidate.blocks
        big = dataclasses.replace(record.summary, blocks=blocks)
        self.assertGreater(len(json.dumps(big.as_dict(), ensure_ascii=False).encode()), 500_000)
        self.store.delete(self.config, "claude", "root")
        small = dataclasses.replace(self.config, summary_store_max_bytes=2 * 524_288)
        for n in range(4):
            self.assertEqual(
                "stored",
                self.store.put(
                    small,
                    "claude",
                    str(n),
                    big,
                    record.snapshot,
                    made_at=float(n),
                    model_stamp="test",
                ),
            )
        self.assertLessEqual(
            Path(self.store.store_path(small)).stat().st_size, small.summary_store_max_bytes
        )
        self.assertEqual(2, len(self.store.load(small).entries))
        self.assertEqual(original, annotations_path.read_bytes())

    def test_delete_and_forget_ignore_annotation_switch(self) -> None:
        self.transcript.prompt("Inspect")
        page = self.read()
        self.save(page)
        config = dataclasses.replace(self.config, annotations_enabled=False)
        self.assertEqual("deleted", self.store.delete(config, "claude", "root"))
        self.save(page)
        self.assertEqual("deleted", self.store.forget(config))
        self.assertFalse(Path(self.store.store_path(config)).exists())

    def test_forget_deletes_the_store_when_the_lock_file_is_unusable(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        Path(self.store.store_path(self.config) + ".lock").unlink()
        Path(self.store.store_path(self.config) + ".lock").mkdir()
        self.assertEqual("unwritable", self.store.delete(self.config, "claude", "root"))
        self.assertEqual("deleted", self.store.forget(self.config))
        self.assertFalse(Path(self.store.store_path(self.config)).exists())

    def test_forget_and_delete_on_a_fresh_machine_make_no_state_home(self) -> None:
        self.assertEqual("absent", self.store.forget(self.config))
        self.assertEqual("absent", self.store.delete(self.config, "claude", "root"))
        self.assertFalse(Path(self.config.state_home).exists())

    def test_a_credential_shaped_identifier_refuses_the_record(self) -> None:
        self.transcript.prompt("Inspect")
        page = self.read()
        self.save(page)
        assert page.coverage is not None
        summary = session_summary.summarize(
            page.entries,
            page.coverage,
            "claude",
            config=self.config,
            model=Replies(),
            clock=lambda: 0.0,
        )
        sid = "ghp_" + "A" * 36
        for _ in range(2):
            self.assertEqual(
                "refused",
                self.store.put(
                    self.config,
                    "claude",
                    sid,
                    summary,
                    page.snapshot,
                    made_at=100.0,
                    model_stamp="synthetic-model",
                ),
            )
        store = self.store.load(self.config)
        self.assertEqual("ok", store.state)
        self.assertEqual(["root"], [entry.sid for entry in store.entries])

    def test_an_oversized_model_stamp_is_refused(self) -> None:
        self.transcript.prompt("Inspect")
        page = self.read()
        assert page.coverage is not None
        summary = session_summary.summarize(
            page.entries,
            page.coverage,
            "claude",
            config=self.config,
            model=Replies(),
            clock=lambda: 0.0,
        )
        stamp = "m" * (self.config.summary_store_model_stamp_cap_chars + 1)
        self.assertEqual(
            "refused",
            self.store.put(
                self.config,
                "claude",
                "root",
                summary,
                page.snapshot,
                made_at=1.0,
                model_stamp=stamp,
            ),
        )
        self.save(page)
        path = Path(self.store.store_path(self.config))
        raw = json.loads(path.read_text())
        raw["entries"][0]["model_stamp"] = stamp
        path.write_text(json.dumps(raw))
        self.assertEqual("unavailable", self.store.load(self.config).state)

    def test_discard_everything_keeps_the_summary(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        self.assertEqual(
            "stored",
            annotation_store.annotate(
                self.config,
                self.state,
                "claude",
                "root",
                goal="Inspect the parser",
                now=90.0,
            ),
        )
        self.assertEqual(
            "stored",
            annotation_store.clear(
                self.config,
                self.state,
                "claude",
                "root",
                now=110.0,
            ),
        )
        self.assertIsNotNone(self.store.get(self.config, "claude", "root"))

    def test_forget_command_removes_summary_even_with_annotations_off(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        args = cli.build_parser().parse_args(["--forget", "--no-annotations"])
        config = dataclasses.replace(self.config, annotations_enabled=False)
        with (
            mock.patch.object(lifecycle, "instance_status", return_value={"state": "absent"}),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(0, cli.run_one_shot(args, config, self.state))
        self.assertFalse(Path(self.store.store_path(config)).exists())

    def test_board_metadata_reads_no_transcript_and_contains_no_blocks(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        with mock.patch.object(session_source, "read", side_effect=AssertionError("board read")):
            store = self.store.load(self.config)
            result = self.store.published(store.entries[0])
        self.assertEqual({"summary"}, set(result))
        self.assertTrue(result["summary"]["exists"])
        self.assertIsNone(result["summary"]["out_of_date"])
        self.assertNotIn("blocks", result["summary"])

    def test_access_time_protects_a_record_from_eviction(self) -> None:
        self.transcript.prompt("Inspect")
        page = self.read()
        self.save(page)
        record = self.store.get(self.config, "claude", "root", now=100.0)
        size = Path(self.store.store_path(self.config)).stat().st_size
        config = dataclasses.replace(self.config, summary_store_max_bytes=2 * size - 20)
        self.assertEqual(
            "stored",
            self.store.put(
                config,
                "claude",
                "other",
                record.summary,
                record.snapshot,
                made_at=101.0,
                model_stamp="model",
            ),
        )
        self.store.get(
            config, "claude", "root", now=100.0 + config.summary_store_touch_interval_sec
        )
        self.assertEqual(
            "stored",
            self.store.put(
                config,
                "claude",
                "new",
                record.summary,
                record.snapshot,
                made_at=102.0,
                model_stamp="model",
            ),
        )
        self.assertEqual({"root", "new"}, {e.sid for e in self.store.load(config).entries})

    def test_stored_source_metadata_excludes_words_and_pending_inputs(self) -> None:
        self.transcript.prompt("PRIVATE SYNTHETIC SOURCE WORDS")
        self.transcript.call("Bash", {"command": "pytest tests", "unused": "PRIVATE INPUT"})
        self.save(self.read())
        source = json.loads(Path(self.store.store_path(self.config)).read_text())["entries"][0][
            "source"
        ]
        self.assertNotIn("PRIVATE", json.dumps(source))
        self.assertNotIn("input_json", json.dumps(source))
        self.assertNotIn("cursor", source)

    def test_redaction_precedes_the_per_summary_byte_bound(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        record = self.store.get(self.config, "claude", "root")
        secret = "ghp_" + "A" * 36
        summary = dataclasses.replace(
            record.summary,
            lede=session_summary.Lede(
                session_summary.Display((secret + " ") * 14_000),
                ("fact",),
            ),
        )
        self.assertGreater(
            len(json.dumps(summary.as_dict()).encode()), self.config.session_summary_max_bytes
        )
        self.assertEqual(
            "stored",
            self.store.put(
                self.config,
                "claude",
                "root",
                summary,
                record.snapshot,
                made_at=200.0,
                model_stamp=secret,
            ),
        )
        raw = Path(self.store.store_path(self.config)).read_text()
        self.assertNotIn(secret, raw)
        self.assertIn("REDACTED", raw)

    def test_gap_withheld_and_cut_fields_round_trip(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        record = self.store.get(self.config, "claude", "root")
        bullet = session_summary.Bullet(
            session_summary.Display(reason="completion_claim"),
            "said",
            ("fact",),
            True,
            2,
        )
        phase = session_summary.Phase(
            session_summary.Display(reason="completion_claim"), (bullet,), 2
        )
        block = dataclasses.replace(
            record.summary.blocks[0],
            phases=(phase,),
            phases_cut=1,
            withheld_phases=1,
            reply_cut=True,
        )
        gap = dataclasses.replace(block, phases=(), reason="no_output")
        summary = dataclasses.replace(
            record.summary,
            state="partial",
            reason="gaps",
            blocks=(block, gap),
            lede=session_summary.Lede(session_summary.Display(reason="no_citation"), (), 2),
        )
        self.assertEqual(
            "stored",
            self.store.put(
                self.config,
                "claude",
                "root",
                summary,
                record.snapshot,
                made_at=200.0,
                model_stamp="model",
            ),
        )
        self.assertEqual(
            summary.as_dict(), self.store.get(self.config, "claude", "root").summary.as_dict()
        )


class SummaryStoreCostTest(_StoreCase):
    """A focused poll and a board collection must not pay for the whole store or transcript."""

    def test_reading_within_the_touch_interval_does_not_rewrite_the_file(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        path = Path(self.store.store_path(self.config))
        before = path.stat()
        with mock.patch.object(self.store.runtime_io, "atomic_write_owner_only") as write:
            for now in (101.0, 100.0 + self.config.summary_store_touch_interval_sec - 1):
                self.assertIsNotNone(self.store.get(self.config, "claude", "root", now=now))
            write.assert_not_called()
        self.assertEqual(before.st_mtime_ns, path.stat().st_mtime_ns)
        self.store.get(
            self.config, "claude", "root", now=100.0 + self.config.summary_store_touch_interval_sec
        )
        self.assertNotEqual(before.st_ino, path.stat().st_ino)

    def test_an_unchanged_store_file_is_parsed_once(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        first = self.store.load(self.config)
        with mock.patch.object(self.store, "_parse", side_effect=AssertionError("parsed")):
            self.assertIs(first, self.store.load(self.config))

    def test_a_rewritten_store_file_is_parsed_again(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        self.assertEqual("ok", self.store.load(self.config).state)
        Path(self.store.store_path(self.config)).write_text("{", encoding="utf-8")
        self.assertEqual("unavailable", self.store.load(self.config).state)

    def test_a_touch_another_reader_made_while_this_one_waited_is_not_repeated(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        stale = self.store.load(self.config)
        later = 100.0 + self.config.summary_store_touch_interval_sec
        self.store.get(self.config, "claude", "root", now=later)
        touched = self.store.load(self.config)
        with (
            mock.patch.object(self.store, "load", side_effect=[stale, touched]),
            mock.patch.object(self.store.runtime_io, "atomic_write_owner_only") as write,
        ):
            record = self.store.get(self.config, "claude", "root", now=later + 1)
        write.assert_not_called()
        self.assertEqual(later, record.accessed_at)

    def test_a_time_clipped_freshness_read_is_reused_only_for_its_retry_interval(self) -> None:
        from compass_runtime import observer  # noqa: PLC0415

        self.transcript.prompt("Inspect")
        self.save(self.read())
        rushed = dataclasses.replace(self.config, session_source_page_max_seconds=0.0)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            clipped = self.store.for_session(rushed, self.state, "claude", "root")
            self.assertEqual("source_incomplete", clipped["out_of_date"]["reason"])
            # A finished large session is polled once per board revision; within the interval
            # an unchanged transcript costs a stat, not another clipped read.
            with mock.patch.object(session_source, "read", side_effect=AssertionError("reread")):
                again = self.store.for_session(rushed, self.state, "claude", "root")
            self.assertEqual(clipped, again)
            # Past the interval the read runs again, so one slow read is not pinned.
            later = self.config.summary_freshness_retry_sec + 1
            clock = SimpleNamespace(monotonic=lambda: time.monotonic() + later, time=time.time)
            with mock.patch.object(self.store, "time", clock):
                full = self.store.for_session(self.config, self.state, "claude", "root")
        self.assertEqual("unchanged", full["out_of_date"]["kind"])

    def test_delete_and_forget_drop_the_cached_parse(self) -> None:
        for drop in ("delete", "forget"):
            with self.subTest(drop=drop):
                self.transcript.prompt("Inspect")
                self.save(self.read())
                self.assertEqual(1, len(self.store.load(self.config).entries))
                path = self.store.store_path(self.config)
                self.assertIn(path, self.store._LOADED)
                if drop == "delete":
                    self.assertEqual("deleted", self.store.delete(self.config, "claude", "root"))
                else:
                    self.assertEqual("deleted", self.store.forget(self.config))
                self.assertNotIn(path, self.store._LOADED)

    def test_a_board_row_carries_coverage_without_serializing_the_summary(self) -> None:
        self.transcript.prompt("Inspect")
        self.save(self.read())
        entry = self.store.load(self.config).entries[0]
        with mock.patch.object(
            session_summary.Summary, "as_dict", side_effect=AssertionError("whole summary")
        ):
            row = self.store.published(entry)
        self.assertEqual(entry.summary.as_dict()["coverage"], row["summary"]["coverage"])

    def test_the_board_row_carries_the_last_focused_report_without_a_read(self) -> None:
        from compass_runtime import observer  # noqa: PLC0415

        self.transcript.prompt("Inspect")
        self.save(self.read())
        entry = self.store.load(self.config).entries[0]
        self.assertIsNone(self.store.last_checked(self.state, entry))
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            self.store.for_session(self.config, self.state, "claude", "root")
        with mock.patch.object(session_source, "read", side_effect=AssertionError("board read")):
            checked = self.store.last_checked(self.state, entry)
            row = self.store.published(entry, checked=checked)
        self.assertEqual({"kind": "unchanged", "reason": None}, row["summary"]["out_of_date"])
        resummarized = dataclasses.replace(entry, made_at=entry.made_at + 1)
        self.assertIsNone(self.store.last_checked(self.state, resummarized))

    def test_reopening_an_unchanged_session_reads_no_transcript(self) -> None:
        from compass_runtime import observer  # noqa: PLC0415

        self.transcript.prompt("Inspect")
        self.save(self.read())
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first = self.store.for_session(self.config, self.state, "claude", "root")
            with mock.patch.object(session_source, "read", side_effect=AssertionError("reread")):
                second = self.store.for_session(self.config, self.state, "claude", "root")
            self.assertEqual("unchanged", first["out_of_date"]["kind"])
            self.assertEqual(first, second)
            self.transcript.prompt("Then the parser")
            self.transcript.save(self.path)
            third = self.store.for_session(self.config, self.state, "claude", "root")
        self.assertEqual("appended", third["out_of_date"]["kind"])
