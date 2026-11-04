"""A short SQLite writer fence orders final publication against every off writer."""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import threading
import unittest
from typing import Any
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import reading_policy as policy

from . import test_reading_long_permission as permission_tests


class PublicationFenceTest(unittest.TestCase):
    def setUp(self) -> None:
        fixture = permission_tests.LongPermissionTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.config = fixture.config
        self.permission = fixture.capture()
        assert runtime_io.sqlite_module is not None
        self.sqlite = runtime_io.sqlite_module

    def fence(self, **changes: Any) -> Any:
        function: Any = getattr(policy, "long_publication_permission", None)
        self.assertTrue(callable(function), "a held permission publication fence is required")
        return function(
            changes.get("config", self.config), changes.get("permission", self.permission)
        )

    def publish(self) -> str:
        with self.fence() as reason:
            return str(reason)

    def observe_wait(self, entered: threading.Event) -> Any:
        connect = self.sqlite.connect
        main = threading.current_thread()

        def traced(*args: Any, **kwargs: Any) -> Any:
            db = connect(*args, **kwargs)
            db.set_trace_callback(
                lambda sql: (
                    entered.set()
                    if sql == "BEGIN IMMEDIATE" and threading.current_thread() is not main
                    else None
                )
            )
            return db

        return mock.patch.object(self.sqlite, "connect", side_effect=traced)

    def dump(self) -> list[str]:
        with contextlib.closing(self.sqlite.connect(policy.store_path(self.config))) as db:
            return list(db.iterdump())

    def test_last_budget_permission_is_held_without_migration_charge_or_prune(self) -> None:
        with contextlib.closing(self.sqlite.connect(policy.store_path(self.config))) as db:
            db.executemany("INSERT INTO spends VALUES (?)", [(100,)] * 100 + [(1,)])
            db.commit()
        before = self.dump()
        with (
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(policy, "_long_permission_schema", side_effect=AssertionError),
            mock.patch.object(policy, "_transaction", side_effect=AssertionError),
            self.fence() as reason,
        ):
            self.assertEqual("", reason)
            self.assertEqual("", policy.long_permission_reason(self.config, self.permission))
        self.assertEqual(before, self.dump())

    def test_current_pause_waits_until_the_prior_publication_finishes(self) -> None:
        entered = threading.Event()
        order: list[str] = []

        def pause() -> Any:
            answer = policy.set_consent(self.config, False, now=100)
            order.append("pause-returned")
            return answer

        with (
            concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool,
            self.observe_wait(entered),
        ):
            with self.fence() as reason:
                self.assertEqual("", reason)
                waiting = pool.submit(pause)
                self.assertTrue(entered.wait(2))
                self.assertFalse(waiting.done())
                order.append("published")
            self.assertTrue(waiting.result(timeout=5)["off"])
        self.assertEqual(["published", "pause-returned"], order)
        self.assertEqual("permission-changed", self.publish())

    def test_legacy_off_writer_waits_and_its_trigger_invalidates_after_resume(self) -> None:
        entered = threading.Event()
        order: list[str] = []

        def legacy_pause() -> None:
            with contextlib.closing(
                self.sqlite.connect(policy.store_path(self.config), isolation_level=None)
            ) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT OR REPLACE INTO provider_permission VALUES ('claude', 0)")
                db.execute("COMMIT")
            order.append("off-committed")

        with (
            concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool,
            self.observe_wait(entered),
        ):
            with self.fence() as reason:
                self.assertEqual("", reason)
                waiting = pool.submit(legacy_pause)
                self.assertTrue(entered.wait(2))
                self.assertFalse(waiting.done())
                order.append("published")
            waiting.result(timeout=5)
        self.assertEqual(["published", "off-committed"], order)
        policy.resume(self.config, now=100)
        self.assertEqual("permission-changed", self.publish())

    def test_off_and_resume_while_publication_waits_are_checked_after_the_lock(self) -> None:
        entered = threading.Event()
        with contextlib.closing(
            self.sqlite.connect(policy.store_path(self.config), isolation_level=None)
        ) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with (
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool,
                self.observe_wait(entered),
            ):
                waiting = pool.submit(self.publish)
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertFalse(waiting.done())
                    writer.execute("INSERT OR REPLACE INTO permission VALUES (1, 0)")
                    writer.execute("DELETE FROM permission WHERE allowed=0")
                finally:
                    writer.execute("COMMIT")
                self.assertEqual("permission-changed", waiting.result(timeout=5))

    def test_pause_first_and_same_epoch_off_cannot_publish(self) -> None:
        policy.set_consent(self.config, False, now=100)
        self.assertEqual("permission-changed", self.publish())
        with contextlib.closing(self.sqlite.connect(policy.store_path(self.config))) as db:
            current = policy.LongPermission(
                *db.execute("SELECT lineage, epoch FROM long_permission").fetchone()
            )
        with self.fence(permission=current) as reason:
            self.assertEqual("model-calls-paused", reason)

    def test_database_replacement_during_lock_wait_cannot_validate_old_connection(self) -> None:
        entered = threading.Event()
        path = policy.store_path(self.config)
        with contextlib.closing(self.sqlite.connect(path, isolation_level=None)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with (
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool,
                self.observe_wait(entered),
            ):
                waiting = pool.submit(self.publish)
                try:
                    self.assertTrue(entered.wait(2))
                    path.rename(path.with_suffix(".old"))
                    fresh = policy.capture_long_permission(self.config, now=100)
                    self.assertIsNotNone(fresh)
                    self.assertNotEqual(self.permission, fresh)
                finally:
                    writer.execute("ROLLBACK")
                self.assertEqual("store-unavailable", waiting.result(timeout=5))

    def test_unknown_invalid_and_recreated_stores_never_create_or_refresh_authority(self) -> None:
        with self.fence(
            config=dataclasses.replace(self.config, model_calls_disabled=True)
        ) as reason:
            self.assertEqual("run-disabled", reason)
        invalid: Any
        for invalid in (None, {}, dataclasses.replace(self.permission, epoch=True)):
            with self.fence(permission=invalid) as reason:
                self.assertEqual("permission-changed", reason)
        missing = dataclasses.replace(self.config, state_dir=self.config.state_dir / "absent")
        with self.fence(config=missing) as reason:
            self.assertEqual("store-unavailable", reason)
        self.assertFalse(missing.state_dir.exists())
        policy.store_path(self.config).unlink()
        self.assertEqual("store-unavailable", self.publish())
        self.assertFalse(policy.store_path(self.config).exists())
        fresh = policy.capture_long_permission(self.config, now=100)
        self.assertNotEqual(self.permission, fresh)
        self.assertEqual("permission-changed", self.publish())

    def test_legacy_or_corrupt_store_is_not_migrated_and_symlink_is_not_followed(self) -> None:
        with contextlib.closing(self.sqlite.connect(policy.store_path(self.config))) as db:
            db.execute("DROP TABLE long_permission")
            db.commit()
        before = self.dump()
        self.assertEqual("store-unavailable", self.publish())
        self.assertEqual(before, self.dump())
        path = policy.store_path(self.config)
        path.write_bytes(b"PRIVATE CORRUPT DATABASE")
        self.assertEqual("store-unavailable", self.publish())
        target = path.with_suffix(".old")
        path.rename(target)
        path.symlink_to(target)
        self.assertEqual("store-unavailable", self.publish())
        self.assertEqual(b"PRIVATE CORRUPT DATABASE", target.read_bytes())

    def test_failed_lock_yields_refusal_once_and_callback_exception_releases_lock(self) -> None:
        with contextlib.closing(
            self.sqlite.connect(policy.store_path(self.config), isolation_level=None)
        ) as writer:
            writer.execute("BEGIN IMMEDIATE")
            try:
                with mock.patch.object(policy, "WRITE_WAIT_SEC", 0):
                    self.assertEqual("store-unavailable", self.publish())
            finally:
                writer.execute("ROLLBACK")

        class PublicationError(Exception):
            pass

        with self.assertRaises(PublicationError), self.fence() as reason:
            self.assertEqual("", reason)
            raise PublicationError("caller failure must not become a second yield")
        self.assertTrue(policy.set_consent(self.config, False, now=100)["off"])

    def test_sqlite_unavailable_yields_no_success(self) -> None:
        with mock.patch.object(runtime_io, "sqlite_module", None):
            self.assertEqual("store-unavailable", self.publish())
