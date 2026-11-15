from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import dismissals, history, lifecycle
from compass_runtime import io as runtime_io

from .support import cfg


class OwnerWritesTest(unittest.TestCase):
    """DRC-4345: owner-only file writers, directory mode tightening, and atomic write helper."""

    def test_ensure_owner_dir_creates_new_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "sub", "dir")
            runtime_io.ensure_owner_dir(target, mode=0o700)
            self.assertTrue(os.path.isdir(target))
            if os.name != "nt":
                self.assertEqual(0o700, os.stat(target).st_mode & 0o777)

    def test_ensure_owner_dir_tightens_preexisting_loose_directory(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX directory modes do not apply on Windows")
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "loose_dir")
            os.makedirs(target, mode=0o777)
            os.chmod(target, 0o755)  # noqa: S103
            self.assertEqual(0o755, os.stat(target).st_mode & 0o777)

            runtime_io.ensure_owner_dir(target, mode=0o700)
            self.assertEqual(0o700, os.stat(target).st_mode & 0o777)

    def test_atomic_write_owner_only_writes_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_str = os.path.join(tmp, "test_str.json")
            runtime_io.atomic_write_owner_only(target_str, '{"ok": true}')
            self.assertEqual('{"ok": true}', Path(target_str).read_text(encoding="utf-8"))

            target_bin = os.path.join(tmp, "test_bin.bin")
            runtime_io.atomic_write_owner_only(target_bin, b"binary\x00data")
            self.assertEqual(b"binary\x00data", Path(target_bin).read_bytes())

            if os.name != "nt":
                self.assertEqual(0o600, os.stat(target_str).st_mode & 0o777)
                self.assertEqual(0o600, os.stat(target_bin).st_mode & 0o777)

    def test_atomic_write_owner_only_flags_and_randomized_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "test.json")
            opened_records: list[tuple[str, int, int | None]] = []
            real_open = os.open

            def spy_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
                mode = kwargs.get("mode", args[0] if args else None)
                opened_records.append((str(path), flags, mode))
                return int(real_open(path, flags, *args, **kwargs))

            with mock.patch.object(os, "open", spy_open):
                runtime_io.atomic_write_owner_only(target, "payload")

            temp_records = [record for record in opened_records if record[0].endswith(".tmp")]
            self.assertEqual(1, len(temp_records))
            tmp_path, flags, mode = temp_records[0]
            self.assertTrue(tmp_path.endswith(".tmp"))
            self.assertNotEqual(target, tmp_path)
            self.assertEqual(0o600, mode)
            # Verify randomized pattern: <target>.<pid>.<rand>.tmp
            pattern = re.escape(os.path.basename(target)) + r"\.\d+\.[0-9a-f]+\.tmp$"
            self.assertRegex(os.path.basename(tmp_path), pattern)

            # Check expected flags
            self.assertTrue(flags & os.O_CREAT)
            self.assertTrue(flags & os.O_EXCL)
            expected_nofollow = getattr(os, "O_NOFOLLOW", 0)
            if expected_nofollow:
                self.assertTrue(flags & expected_nofollow)

    def test_atomic_write_owner_only_cleans_up_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "fail.json")
            with (
                mock.patch.object(os, "replace", side_effect=OSError("disk error")),
                self.assertRaises(OSError),
            ):
                runtime_io.atomic_write_owner_only(target, "data")

            # Verify no temp file remained
            remaining = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
            self.assertEqual([], remaining, "temp file was not cleaned up on failure")
            self.assertFalse(os.path.exists(target))

    def test_write_state_tightens_preexisting_directory(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX directory modes do not apply on Windows")
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "compass_home")
            os.makedirs(home, mode=0o755)
            os.chmod(home, 0o755)  # noqa: S103
            self.assertEqual(0o755, os.stat(home).st_mode & 0o777)

            with mock.patch.dict(os.environ, {"COMPASS_HOME": home}):
                config = cfg()
                lifecycle.write_state(config, 4553, started=100.0)

            self.assertEqual(0o700, os.stat(home).st_mode & 0o777)
            state_file = lifecycle.state_path(config, 4553)
            self.assertTrue(os.path.exists(state_file))
            self.assertEqual(0o600, os.stat(state_file).st_mode & 0o777)

    def test_dismissals_save_tightens_preexisting_directory(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX directory modes do not apply on Windows")
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "compass_home")
            os.makedirs(home, mode=0o755)
            os.chmod(home, 0o755)  # noqa: S103
            self.assertEqual(0o755, os.stat(home).st_mode & 0o777)

            with mock.patch.dict(os.environ, {"COMPASS_HOME": home}):
                config = cfg()
                success = dismissals.save(config, [])

            self.assertTrue(success)
            self.assertEqual(0o700, os.stat(home).st_mode & 0o777)
            store_file = dismissals.store_path(config)
            self.assertTrue(os.path.exists(store_file))
            self.assertEqual(0o600, os.stat(store_file).st_mode & 0o777)

    def test_history_save_tightens_preexisting_directory(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX directory modes do not apply on Windows")
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "compass_home")
            os.makedirs(home, mode=0o755)
            os.chmod(home, 0o755)  # noqa: S103
            self.assertEqual(0o755, os.stat(home).st_mode & 0o777)

            with mock.patch.dict(os.environ, {"COMPASS_HOME": home}):
                config = cfg()
                success = history.save(config, [])

            self.assertTrue(success)
            self.assertEqual(0o700, os.stat(home).st_mode & 0o777)
            store_file = history.store_path(config)
            self.assertTrue(os.path.exists(store_file))
            self.assertEqual(0o600, os.stat(store_file).st_mode & 0o777)
