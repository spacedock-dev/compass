"""Long-job permission snapshots cannot survive a pause or a recreated store."""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import reading_policy, supervise

from .support import make_runtime

# How long a test waits for a step that happens at once on an idle runner: a busy runner
# is slower, not red.
WAIT_SEC = 30.0


class LongPermissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def capture(self, config: Any = None) -> Any:
        capture: Any = getattr(reading_policy, "capture_long_permission", None)
        self.assertTrue(callable(capture))
        return capture(self.config if config is None else config, now=100.0)

    def reserve(self, permission: Any, config: Any = None) -> Any:
        reserve: Any = getattr(reading_policy, "reserve_long", None)
        self.assertTrue(callable(reserve))
        return reserve(self.config if config is None else config, permission=permission, now=100.0)

    def test_capture_is_stable_without_spend_or_changes_to_public_status(self) -> None:
        before = reading_policy.status(self.config, now=100.0)
        token = self.capture()
        self.assertIsNotNone(token)
        self.assertEqual(token, self.capture())
        self.assertEqual(before, reading_policy.status(self.config, now=100.0))
        reserved = self.reserve(token)
        self.assertEqual("", reserved["reason"])
        self.assertEqual(1, reserved["used"])
        self.assertEqual(set(before), set(reserved))

    def test_pause_and_forget_cannot_be_undone_for_an_old_job_by_resume(self) -> None:
        for operation in ("pause", "forget"):
            with self.subTest(operation=operation):
                reading_policy.resume(self.config, now=100.0)
                token = self.capture()
                before = reading_policy.status(self.config, now=100.0)["used"]
                if operation == "pause":
                    reading_policy.set_consent(self.config, False, now=100.0)
                else:
                    self.assertTrue(reading_policy.forget(self.config, now=100.0))
                self.assertIsNone(self.capture())
                self.assertEqual("model-calls-paused", self.reserve(token)["reason"])
                reading_policy.resume(self.config, now=100.0)
                self.assertEqual("permission-changed", self.reserve(token)["reason"])
                self.assertEqual(before, reading_policy.status(self.config, now=100.0)["used"])
                fresh = self.capture()
                self.assertEqual(token.lineage, fresh.lineage)
                self.assertGreater(fresh.epoch, token.epoch)
                self.assertEqual("", self.reserve(fresh)["reason"])

    def test_legacy_off_insert_and_update_on_either_table_invalidate_after_resume(self) -> None:
        assert runtime_io.sqlite_module is not None
        cases = (
            ("permission", "INSERT OR REPLACE INTO permission VALUES (1, 0)"),
            ("permission", "UPDATE permission SET allowed=0 WHERE id=1"),
            ("provider", "INSERT OR REPLACE INTO provider_permission VALUES ('claude', 0)"),
            ("provider", "UPDATE provider_permission SET allowed=0 WHERE provider='claude'"),
        )
        for table, sql in cases:
            with self.subTest(sql=sql):
                reading_policy.store_path(self.config).unlink(missing_ok=True)
                reading_policy.set_consent(
                    self.config,
                    True,
                    now=100.0,
                    provider="codex" if table == "permission" else "claude",
                )
                if table == "permission":
                    reading_policy.set_consent(self.config, True, now=100.0, provider="claude")
                token = self.capture()
                with contextlib.closing(
                    runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
                ) as legacy:
                    legacy.execute(sql)
                    legacy.commit()
                self.assertTrue(reading_policy.status(self.config, now=100.0)["off"])
                reading_policy.resume(self.config, now=100.0)
                self.assertEqual("permission-changed", self.reserve(token)["reason"])
                self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])

    def test_provider_zero_beside_an_allow_does_not_invent_a_global_pause(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0, provider="codex")
        token = self.capture()
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        ) as legacy:
            legacy.execute("INSERT OR REPLACE INTO provider_permission VALUES ('claude', 0)")
            legacy.commit()
        self.assertFalse(reading_policy.status(self.config, now=100.0)["off"])
        self.assertEqual(token, self.capture())
        self.assertEqual("", self.reserve(token)["reason"])

    def test_recreated_allowed_database_never_reuses_an_old_lineage(self) -> None:
        token = self.capture()
        reading_policy.store_path(self.config).unlink()
        reading_policy.resume(self.config, now=100.0)
        self.assertEqual("permission-changed", self.reserve(token)["reason"])
        fresh = self.capture()
        self.assertNotEqual(token.lineage, fresh.lineage)
        self.assertEqual(token.epoch, fresh.epoch)
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])
        self.assertEqual("", self.reserve(fresh)["reason"])

    def test_old_store_migrates_without_resetting_spend_or_changing_legacy_writes(self) -> None:
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        ) as legacy:
            legacy.execute("CREATE TABLE permission (id INTEGER PRIMARY KEY, allowed INTEGER)")
            legacy.execute("CREATE TABLE spends (at REAL NOT NULL)")
            legacy.execute("INSERT INTO permission VALUES (1, 1)")
            legacy.execute("INSERT INTO spends VALUES (100.0)")
            legacy.commit()
        token = self.capture()
        self.assertIsNotNone(token)
        self.assertEqual(1, reading_policy.status(self.config, now=100.0)["used"])
        with contextlib.closing(
            runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        ) as legacy:
            legacy.execute("INSERT OR REPLACE INTO permission VALUES (1, 0)")
            legacy.execute("INSERT OR REPLACE INTO permission VALUES (1, 1)")
            legacy.execute("INSERT INTO spends VALUES (100.0)")
            legacy.commit()
        self.assertEqual("permission-changed", self.reserve(token)["reason"])
        self.assertEqual(2, reading_policy.status(self.config, now=100.0)["used"])

    def test_summary_switch_and_grants_do_not_change_the_analyze_token(self) -> None:
        reading_policy.set_consent(
            self.config,
            True,
            now=100.0,
            provider="claude",
            destination="Anthropic",
            tool_output="Anthropic",
        )
        reading_policy.note(
            self.config,
            kind="reading",
            provider="claude",
            destination="Anthropic",
            content=6,
            tool_output="Anthropic",
            now=100.0,
        )
        before = reading_policy.status(self.config, now=100.0)
        token = self.capture()
        self.assertEqual(before, reading_policy.status(self.config, now=100.0))
        summary = reading_policy.summary_status(self.config, now=100.0)
        self.assertNotIn("generation", before)
        for allowed in (False, True):
            reading_policy.set_summary_consent(self.config, allowed, now=100.0)
            self.assertEqual(token, self.capture())
            self.assertEqual(before, reading_policy.status(self.config, now=100.0))
        self.assertGreater(
            reading_policy.summary_status(self.config, now=100.0)["generation"],
            summary["generation"],
        )
        self.assertEqual("", self.reserve(token)["reason"])

    def test_token_is_checked_after_a_real_sqlite_lock_wait(self) -> None:
        token = self.capture()
        assert runtime_io.sqlite_module is not None
        entering = threading.Event()
        connect = reading_policy._connect

        def observed_connect(*args: Any, **kwargs: Any) -> Any:
            db = connect(*args, **kwargs)
            db.set_trace_callback(lambda sql: entering.set() if sql == "BEGIN IMMEDIATE" else None)
            return db

        with contextlib.closing(
            runtime_io.sqlite_module.connect(
                reading_policy.store_path(self.config), isolation_level=None
            )
        ) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with (
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool,
                mock.patch.object(reading_policy, "_connect", side_effect=observed_connect),
            ):
                waiting = pool.submit(self.reserve, token)
                try:
                    self.assertTrue(entering.wait(WAIT_SEC))
                    self.assertFalse(waiting.done())
                    writer.execute("INSERT OR REPLACE INTO permission VALUES (1, 0)")
                    writer.execute("DELETE FROM permission WHERE allowed=0")
                    writer.execute("DELETE FROM provider_permission WHERE allowed=0")
                finally:
                    writer.execute("COMMIT")
                self.assertEqual("permission-changed", waiting.result(timeout=WAIT_SEC)["reason"])
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])

    def test_long_reservations_share_the_existing_cap_and_shutdown_barrier(self) -> None:
        token = self.capture()
        for _ in range(99):
            self.assertEqual("", reading_policy.reserve(self.config, now=100.0)["reason"])
        self.assertEqual(100, self.reserve(token)["used"])
        self.assertEqual("daily-cap", self.reserve(token)["reason"])
        self.assertEqual(100, reading_policy.status(self.config, now=100.0)["used"])
        reading_policy.store_path(self.config).unlink()
        token = self.capture()
        supervise._SHUTDOWN.set()
        self.assertEqual("stopping", self.reserve(token)["reason"])
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])

    def test_invalid_tokens_never_fall_back_to_ordinary_reservation(self) -> None:
        token = self.capture()
        invalid: Any
        for invalid in (
            None,
            {},
            "",
            token.lineage,
            dataclasses.replace(token, epoch=True),
            dataclasses.replace(token, epoch=-1),
            dataclasses.replace(token, lineage=""),
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual("permission-changed", self.reserve(invalid)["reason"])
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])

    def test_disabled_or_unavailable_store_cannot_capture_or_reserve(self) -> None:
        token = self.capture()
        disabled, _ = make_runtime(state_dir=self.config.state_dir, model_calls_disabled=True)
        self.assertIsNone(self.capture(disabled))
        self.assertEqual("run-disabled", self.reserve(token, disabled)["reason"])
        with mock.patch.object(runtime_io, "sqlite_module", None):
            self.assertIsNone(self.capture())
            self.assertEqual("store-unavailable", self.reserve(token)["reason"])
        reading_policy.store_path(self.config).write_bytes(b"not SQLite")
        self.assertIsNone(self.capture())
        self.assertEqual("store-unavailable", self.reserve(token)["reason"])
