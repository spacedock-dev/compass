"""Descriptor-relative links and strict state descendants keep their distinct policies."""

from __future__ import annotations

import dataclasses
import errno
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest import mock

import notify_hook
from compass_runtime import ci_read, observer, quota
from compass_runtime import io as runtime_io

from .support import make_config

if TYPE_CHECKING:
    from collections.abc import Callable


class OwnerIoRound2Test(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.root = Path(home.name)

    @unittest.skipIf(os.name == "nt", "POSIX descriptor-relative targets")
    def test_relative_links_after_depth_changing_root_read_actual_target(self) -> None:
        real = self.root / "deep" / "real"
        actual = self.root / "deep" / "sibling"
        decoy = self.root / "sibling"
        for directory in (real, actual, decoy):
            directory.mkdir(parents=True)
        (actual / "data").write_bytes(b"actual")
        (decoy / "data").write_bytes(b"decoy")
        root = self.root / "root"
        root.symlink_to("deep/real", target_is_directory=True)
        (real / "directory").symlink_to("../sibling", target_is_directory=True)
        (real / "leaf").symlink_to("../sibling/data")
        for path in (root / "directory" / "data", root / "leaf"):
            with self.subTest(path=path), os.fdopen(runtime_io.open_harness(str(path)), "rb") as f:
                self.assertEqual(b"actual", f.read())
        for module in (runtime_io, notify_hook):
            with self.subTest(module=module.__name__):
                fd = module._owner_directory_fd(str(root / "directory"))
                try:
                    self.assertEqual(actual.stat().st_ino, os.fstat(fd).st_ino)
                finally:
                    os.close(fd)

    @unittest.skipIf(os.name == "nt", "POSIX openat errno")
    def test_nonlink_parent_preserves_open_errno(self) -> None:
        file = self.root / "file"
        file.write_text("regular")
        original = os.open
        for module in (runtime_io, notify_hook):
            with self.subTest(module=module.__name__, error="ENOTDIR"):
                with self.assertRaises(OSError) as caught:
                    module._directory_fd(str(file / "child"))
                self.assertEqual(errno.ENOTDIR, caught.exception.errno)

            def denied(path: str, flags: int, *args: Any, **kwargs: Any) -> int:
                if path == "denied":
                    raise PermissionError(errno.EACCES, "denied", path)
                return original(path, flags, *args, **kwargs)

            (self.root / "denied").mkdir(exist_ok=True)
            with self.subTest(module=module.__name__, error="EACCES"):
                with (
                    mock.patch.object(module.os, "open", side_effect=denied),
                    self.assertRaises(OSError) as caught,
                ):
                    module._directory_fd(str(self.root / "denied"))
                self.assertEqual(errno.EACCES, caught.exception.errno)

    def test_observer_linked_large_transcript_keeps_head(self) -> None:
        real = self.root / "real"
        real.mkdir()
        path = real / "session"
        path.write_text("opening prompt\n" + "filler\n" * 1000)
        leaf = self.root / "leaf"
        leaf.symlink_to(path)
        linked = self.root / "linked"
        linked.symlink_to(real, target_is_directory=True)
        config = dataclasses.replace(make_config(home=str(self.root)), tail_bytes=100)
        expected = observer._window_lines(config, str(path))
        self.assertIn("opening prompt", expected)
        for name in (leaf, linked / "session"):
            with self.subTest(path=name):
                self.assertEqual(expected, observer._window_lines(config, str(name)))

    def test_linux_quota_owned_linked_credentials(self) -> None:
        real = self.root / "real"
        real.mkdir()
        path = real / ".credentials.json"
        path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "synthetic"}}))
        linked = self.root / "linked"
        linked.symlink_to(real, target_is_directory=True)
        results = []
        for base in (real, linked):
            config = make_config(
                home=str(self.root),
                platform_name="linux",
                store_roots={"claude.projects": (str(base / "projects"),)},
            )
            results.append(quota._read_token(config, mock.Mock()))
        self.assertIsNone(results[0][2])
        self.assertEqual(results[0], results[1])
        target = real / "credentials-target"
        path.rename(target)
        path.symlink_to(target.name)
        self.assertEqual(results[0], quota._read_token(config, mock.Mock()))

    def test_glab_owned_linked_config(self) -> None:
        real = self.root / "real"
        config = real / "glab-cli" / "config.yml"
        config.parent.mkdir(parents=True)
        config.write_text("hosts:\n  gitlab.example.com:\n    user: synthetic\n")
        linked = self.root / "linked"
        linked.symlink_to(real, target_is_directory=True)
        expected = frozenset({"gitlab.example.com"})
        for base in (real, linked):
            with self.subTest(base=base):
                self.assertEqual(expected, ci_read.glab_hosts({"XDG_CONFIG_HOME": str(base)}))
        target = config.with_name("target")
        config.rename(target)
        config.symlink_to(target.name)
        self.assertEqual(expected, ci_read.glab_hosts({"XDG_CONFIG_HOME": str(real)}))

    def test_ci_run_owned_linked_tmpdir(self) -> None:
        real = self.root / "real"
        real.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(real, target_is_directory=True)

        def runner(*_args: object, **kwargs: Any) -> mock.Mock:
            kwargs["stdout"].write(b'{"ok":true}')
            return mock.Mock(returncode=0)

        for base in (real, linked):
            with self.subTest(base=base), mock.patch.object(tempfile, "tempdir", str(base)):
                self.assertEqual({"ok": True}, ci_read._run(runner, "unused", [], {}))
        with mock.patch.object(runtime_io, "read_prefix_bytes", side_effect=OSError("refused")):
            with self.assertRaises(ci_read._FailureError) as caught:
                ci_read._run(runner, "unused", [], {})
            self.assertEqual(ci_read.ERROR_FAILED, caught.exception.token)
        outside = self.root / "outside-output"
        outside.write_text('{"outside":true}')

        def substituted(*_args: object, **kwargs: Any) -> mock.Mock:
            output = Path(kwargs["stdout"].name)
            output.unlink()
            output.symlink_to(outside)
            return mock.Mock(returncode=0)

        with self.assertRaises(ci_read._FailureError) as caught:
            ci_read._run(substituted, "unused", [], {})
        self.assertEqual(ci_read.ERROR_FAILED, caught.exception.token)
        self.assertEqual('{"outside":true}', outside.read_text())

    def test_windows_state_descendant_link_refused(self) -> None:
        self._state_descendants(windows=True)
        # A junction or another reparse point need not carry symlink mode bits.
        root = os.path.realpath(self.root / "state")
        descendant = os.path.join(root, "reparse")
        os.mkdir(descendant)
        original = os.lstat

        def reparse(path: str, *args: Any, **kwargs: Any) -> Any:
            info = original(path, *args, **kwargs)
            if os.fspath(path) == descendant:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with (
            mock.patch.object(os, "name", "nt"),
            mock.patch.object(os, "lstat", side_effect=reparse),
        ):
            for module in (runtime_io, notify_hook):
                with self.subTest(module=module.__name__), self.assertRaises(OSError):
                    module.ensure_owner_dir(os.path.join(descendant, "new"), root=root)
        self.assertEqual([], os.listdir(descendant))

    def test_runtime_and_hook_state_readers_refuse_descendant_links(self) -> None:
        self._state_descendants(read_only=True)

    def test_hook_writer_refuses_descendant_links(self) -> None:
        self._state_descendants(hook_only=True)

    def _state_descendants(
        self, *, windows: bool = False, read_only: bool = False, hook_only: bool = False
    ) -> None:
        root = self.root / "state"
        outside = self.root / "outside"
        root.mkdir()
        outside.mkdir()
        (outside / "data").write_text("outside")
        (root / "descendant").symlink_to(outside, target_is_directory=True)
        alias = self.root / "alias"
        alias.symlink_to(root, target_is_directory=True)
        path, anchor = str(alias / "descendant" / "data"), str(alias)
        mode_before = outside.stat().st_mode
        operations: list[Callable[[], Any]] = [
            lambda: os.close(runtime_io.open_regular(path, root=anchor)),
            lambda: os.close(notify_hook._open_state(path, root=anchor)),
        ]
        if not read_only:
            operations += [
                lambda: notify_hook.write_owner_json(path, {"bad": True}),
            ]
            if not hook_only:
                operations += [
                    lambda: runtime_io.atomic_write_owner_only(path, "bad", root=anchor),
                    lambda: runtime_io.open_owner_append(path, root=anchor).close(),
                    lambda: runtime_io.ensure_owner_dir(path + "/nested", root=anchor),
                ]
        with (
            mock.patch.dict(os.environ, {"COMPASS_HOME": anchor}),
            mock.patch.object(os, "name", "nt" if windows else os.name),
        ):
            for index, operation in enumerate(operations):
                with self.subTest(operation=index), self.assertRaises(OSError):
                    operation()
            good = os.path.join(anchor, "good")
            runtime_io.atomic_write_owner_only(good, "ok", root=anchor)
            with os.fdopen(runtime_io.open_regular(good, root=anchor)) as f:
                self.assertEqual("ok", f.read())
            notify_hook.write_owner_json(good, {"ok": True})
            with os.fdopen(notify_hook._open_state(good, root=anchor)) as f:
                self.assertEqual({"ok": True}, json.load(f))
        self.assertEqual("outside", (outside / "data").read_text())
        self.assertEqual(["data"], sorted(p.name for p in outside.iterdir()))
        self.assertEqual(mode_before, outside.stat().st_mode)

    @unittest.skipIf(os.name == "nt", "POSIX bounded descriptor traversal")
    def test_harness_leaf_and_directory_link_cycles_are_bounded(self) -> None:
        (self.root / "leaf").symlink_to("leaf")
        (self.root / "directory").symlink_to("directory", target_is_directory=True)
        skill = str(Path(runtime_io.__file__).parents[1])
        script = """
import errno, os, sys
sys.path.insert(0, sys.argv[1])
import notify_hook
from compass_runtime import io
module = io if sys.argv[2] == 'runtime' else notify_hook
try:
    fd = (module.open_harness(sys.argv[3]) if sys.argv[4] == 'leaf'
          else module._directory_fd(sys.argv[3]))
except OSError as exc:
    assert exc.errno == errno.ELOOP, exc
else:
    os.close(fd)
    raise AssertionError('cycle admitted')
"""
        for module, kind in (("runtime", "leaf"), ("runtime", "directory"), ("hook", "directory")):
            with self.subTest(module=module, kind=kind):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        script,
                        skill,
                        module,
                        str(self.root.resolve() / kind),
                        kind,
                    ],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr.decode())

    @unittest.skipIf(os.name == "nt", "POSIX ownership")
    def test_directory_walk_rejects_foreign_descendant(self) -> None:
        foreign = self.root / "foreign"
        leaf = foreign / "owned"
        leaf.mkdir(parents=True)
        foreign_inode = foreign.stat().st_ino
        original = os.fstat

        def foreign_stat(fd: int) -> os.stat_result:
            info = original(fd)
            if info.st_ino == foreign_inode and stat.S_ISDIR(info.st_mode):
                values = list(info)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return info

        for module in (runtime_io, notify_hook):
            with (
                self.subTest(module=module.__name__),
                mock.patch.object(os, "fstat", side_effect=foreign_stat),
                self.assertRaises(OSError),
            ):
                fd = module._directory_fd(str(leaf))
                os.close(fd)
