"""The end-of-session git probe: what it runs, what it refuses to do, what it publishes.

The two behavioural tests here are DEC-3's measurement turned into an oracle. They
build real repositories and run the real `git`, because the hazards both flags
disarm are properties of git rather than of this module, and a mocked runner
cannot observe either one.

Each of those two runs a POSITIVE CONTROL first: the same command with the one
flag removed, in its own repository, which must exhibit the hazard. Without it
neither test can tell "the flag worked" from "the mechanism was never armed
here", and both were vacuous on at least one supported platform — the fsmonitor
script was written with `Path.write_text`, whose default newline translation
makes the shebang `#!/bin/sh\r` on Windows, where `chmod(S_IEXEC)` is a no-op
besides; and the index test is equally vulnerable on a filesystem whose mtime
granularity is coarser than git's racy window. A mechanism the control cannot
arm now skips with its reason rather than passing.
"""

from __future__ import annotations

import ast
import contextlib
import io
import ntpath
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tokenize
import tracemalloc
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest import mock

if TYPE_CHECKING:
    from collections.abc import Iterator

from compass_runtime import ci_read, git_status

GIT = shutil.which("git")

# The two positive controls. Written as literals rather than filtered out of
# `GIT_STATUS_ARGV`, so a change to that constant cannot quietly turn a control
# into a second copy of the probe and make the hazard test pass by agreement.
WITHOUT_NO_OPTIONAL_LOCKS = ("git", "-c", "core.fsmonitor=", "status", "--porcelain")
WITHOUT_FSMONITOR_OFF = ("git", "--no-optional-locks", "status", "--porcelain")
# The shipped argv minus the one flag, plus an explicit `core.hooksPath` naming
# the repository's own default. Without that second part the control inherits a
# global override on hosts that set one, its four hooks land outside the sandbox
# the test inspects, and the test skips with a message saying git-lfs installed
# nothing — which would be false, and would leave the flag unguarded there.
WITHOUT_HOOKS_PATH_OFF = (
    "git",
    "-c",
    "core.fsmonitor=",
    "-c",
    "core.hooksPath=.git/hooks",
    "--no-optional-locks",
    "status",
    "--porcelain",
)

LFS = shutil.which("git-lfs")

# Every shipped module a git call could be added to, not just the package. The
# AC1 oracle used to read `compass_runtime/**/*.py` alone, and the five hook
# adapters plus the launcher and the MCP server sit outside that glob —
# `event_hook.py` most of all, because it is the file that runs inside a user's
# harness lifecycle and so the likeliest place a second git call gets written.
_SHIPPED_SIBLINGS: tuple[str, ...] = (
    "server.py",
    "notify_hook.py",
    "event_hook.py",
    "agy_hook.py",
    "statusline_hook.py",
    "mcp_server.py",
)

# Anything shipped here that can put a program on the CPU, plus `runner`: the
# repository's injected-runner seam is how `git_status.probe` and `quota` both
# spawn, so an oracle that does not follow it cannot see the one call site that
# exists and would be vacuous rather than strict.
_SPAWNERS = frozenset(
    {
        "run",
        "runner",
        "Popen",
        "call",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
        "system",
        "popen",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        # DRC-4465. `os.posix_spawn` is the one spawner in the standard library
        # that takes the program as its FIRST argument and an argv beside it, so
        # a call built from a resolved path names `git` nowhere the grep can see
        # it. `spawn` is here for a helper named after the family rather than for
        # an `os` attribute; there is no `os.spawn`.
        "spawn",
        "posix_spawn",
        "posix_spawnp",
        "create_subprocess_exec",
        "create_subprocess_shell",
    }
)

# `git`, `/usr/bin/git`, `...\git.exe`, or `git` as a word in a shell string.
# Anchored on a separator at both ends, so `git_status`, `git.failed`,
# `compass-git-probe` and `.git/index` are names rather than programs.
_PROGRAM = re.compile(
    r"(?:^|[\s;|&()<>])(?:[^\s;|&()<>]*[/\\])?git(?:\.exe)?(?:$|[\s;|&()<>])",
    re.IGNORECASE,
)


_SKILL = Path(__file__).resolve().parent.parent


def _shipped_sources() -> list[Path]:
    """The shipped Python the oracles below read: the package and its siblings."""
    return sorted((_SKILL / "compass_runtime").rglob("*.py")) + [
        _SKILL / name for name in _SHIPPED_SIBLINGS
    ]


def _bound_names(tree: ast.Module) -> dict[str, list[ast.expr]]:
    """Every name assigned anywhere in this module, so a name standing for an argv resolves.

    Without this the walker below cannot see `GIT_STATUS_ARGV`, which is the one
    real call site: the argv is a constant and the call passes the name.

    DRC-4465. This read `tree.body` alone, which binds module scope only, so
    `exe = "/usr/bin/git"` INSIDE a function was opaque to the walker and the
    grep had no quote adjacent to `git` either — ordinary code, missed by both.
    Scopes are deliberately flattened rather than tracked: this is an oracle that
    must not go silent, so over-reaching on a shadowed name costs a false
    offender that a reader can see, where under-reaching costs a second git call
    site nobody sees. A name bound more than once keeps every value for the same
    reason — the last write winning would drop a candidate rather than add one.
    """
    bound: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, []).append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            bound.setdefault(node.target.id, []).append(node.value)
    return bound


def _argument_strings(node: ast.AST, bound: dict[str, list[ast.expr]], seen: set[str]) -> list[str]:
    """Every string this expression could hand a spawner, folded where it is built.

    Walking the whole subtree is what reaches a list, a tuple, an f-string's
    literal parts, the receiver of a `.split()` and an `os.environ.get` default
    without a case for each. The two special cases are what a plain walk misses:
    a name that stands for a module constant, and a literal split across a `+`.
    """
    out: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            out.append(child.value)
        elif isinstance(child, ast.BinOp) and isinstance(child.op, ast.Add):
            left, right = child.left, child.right
            if (
                isinstance(left, ast.Constant)
                and isinstance(left.value, str)
                and isinstance(right, ast.Constant)
                and isinstance(right.value, str)
            ):
                out.append(left.value + right.value)
        elif isinstance(child, ast.Name) and child.id in bound and child.id not in seen:
            # `seen` is a cycle guard, not a cache: a self-referential module
            # constant would otherwise recurse until the interpreter gives up.
            seen.add(child.id)
            for value in bound[child.id]:
                out.extend(_argument_strings(value, bound, seen))
    return out


def _called_name(node: ast.Call) -> str | None:
    """The bare name this call names, whether it is called plainly or on a receiver."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _spawners_in(tree: ast.Module) -> frozenset[str]:
    """`_SPAWNERS`, plus every function in this module that reaches one.

    DRC-4465. A call to a private helper — `self._spawn(["/usr/bin/git", ...])`
    where `_spawn` calls `subprocess.run` — was invisible to both oracles: the
    walker never looked inside a call it did not recognise as a spawner, and the
    absolute path gives the grep no quote adjacent to `git`. A helper that
    spawns IS a spawner, so it is resolved here rather than added to the literal
    set, which would mean guessing at every name a helper might be given.

    To a fixpoint rather than one pass, because a helper calling a helper is one
    hop further out and a module this size costs nothing to walk again.
    """
    names = set(_SPAWNERS)
    functions = [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    growing = True
    while growing:
        growing = False
        for node in functions:
            if node.name in names:
                continue
            if any(
                _called_name(inner) in names
                for inner in ast.walk(node)
                if isinstance(inner, ast.Call)
            ):
                names.add(node.name)
                growing = True
    return frozenset(names)


def _spawned_programs(source: str) -> list[str]:
    """Program-shaped strings reaching a spawn call in this source."""
    tree = ast.parse(source)
    bound = _bound_names(tree)
    spawners = _spawners_in(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _called_name(node) not in spawners:
            continue
        found.extend(
            text for text in _argument_strings(node, bound, set()) if _PROGRAM.search(text)
        )
    return found


def _quotes_git(source: str) -> bool:
    """The text grep, with comments removed first.

    The comment strip is the fix for its one measured false positive: a comment
    containing a quoted `git` used to make the file an offender, so the grep
    could be tripped by prose that spawns nothing.
    """
    try:
        body = "\n".join(
            token.string
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type != tokenize.COMMENT
        )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A source this cannot tokenize is scanned raw rather than skipped: a
        # file the oracle cannot read must not become a file it approves.
        body = source
    return bool(re.search(r"""["']git["']""", body))


@contextlib.contextmanager
def _environment(environ: dict[str, str], *, cwd: Path | None = None) -> Iterator[None]:
    """Swap `os.environ`, and optionally the process cwd, for the duration.

    The probe reads neither directly, which is the point: what it must not do is
    hand either to the subprocess it spawns.
    """
    saved_environ = dict(os.environ)
    saved_cwd = Path.cwd()
    os.environ.clear()
    os.environ.update(environ)
    if cwd is not None:
        os.chdir(cwd)
    try:
        yield
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_environ)


# `.bat` on Windows because `shutil.which` resolves a bare name through PATHEXT
# there, and a stub with no extension is not a program it will hand back.
_STUB_NAME = "git.bat" if os.name == "nt" else "git"


def _write_stub(path: Path, body: str = "") -> Path:
    """An executable file named as git, doing nothing unless a body says otherwise."""
    path.write_text(body, newline="")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@contextlib.contextmanager
def _git_on_path() -> Iterator[str]:
    """A PATH holding exactly one directory, holding exactly one stub git.

    What this buys is the property `GitProbeCallSiteTest`'s docstring claims and
    #293 took away: `probe` now returns before it reaches `runner` when nothing
    resolves, so on a host with no git the spy tests recorded nothing and read
    `seen[0]`. A stub `which` can find restores them without giving the runtime a
    second seam to bypass the resolution guard through.
    """
    with tempfile.TemporaryDirectory() as tmp:
        _write_stub(Path(tmp) / _STUB_NAME)
        with _environment({**os.environ, "PATH": tmp}):
            yield tmp


def _run(*argv: str, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, capture_output=True)


def _fresh(parent: Path, name: str, *, fsmonitor_log: Path | None = None) -> Path:
    """A repository of its own under `parent`.

    Every hazard test needs two — one for the control and one for the probe —
    and they must not share a `.git`, because the control's run is exactly the
    write or the execution the probe's repository must not have seen.
    """
    root = parent / name
    root.mkdir(parents=True)
    return _repo(root, fsmonitor_log=fsmonitor_log)


def _filtered(parent: Path, name: str) -> Path:
    """A repository whose committed attributes route a tracked path through LFS.

    The precondition is not the attribute on its own — that arm installs nothing,
    measured. It is a tracked path matching a filter attribute whose content git
    must hash, so `blob.bin` is committed raw first and then rewritten at the
    SAME SIZE, which leaves the stat racy and forces the clean filter to run.

    Every git call here carries its own `core.hooksPath`, pointed inside the
    temporary directory. Building the repository runs the same filter driver
    through `add` and `commit`, and the driver installs hooks wherever git says
    they belong: on a host whose global config sets `core.hooksPath`, that is a
    directory shared with the operator's real repositories. Without this the
    fixture writes four executables into it and the test then SKIPS, because the
    control's hooks never land in the sandbox it inspects — so the escape and the
    unguarded flag would both be hidden behind a passing suite. The suite has no
    `GIT_CONFIG_GLOBAL` isolation, and it must not have any here: the global
    config is where the git-lfs driver itself comes from, and removing it would
    disarm the mechanism this test exists to observe.
    """
    root = parent / name
    root.mkdir(parents=True)
    sandbox = root / "sandbox-hooks"
    sandbox.mkdir()

    def git(*argv: str) -> None:
        _run("git", "-c", f"core.hooksPath={sandbox}", *argv, cwd=root)

    git("init", "-q")
    git("config", "user.email", "probe@example.invalid")
    git("config", "user.name", "Probe")
    (root / "blob.bin").write_bytes(b"A" * 64)
    git("add", "blob.bin")
    git("commit", "-q", "-m", "raw blob")
    (root / ".gitattributes").write_text("*.bin filter=lfs\n")
    git("add", ".gitattributes")
    git("commit", "-q", "-m", "attributes")
    (root / "blob.bin").write_bytes(b"B" * 64)
    return root


def _installed_hooks(root: Path) -> list[str]:
    """Hook names in the repository, ignoring git's own `.sample` templates."""
    hooks = root / ".git" / "hooks"
    if not hooks.is_dir():
        return []
    return sorted(p.name for p in hooks.iterdir() if not p.name.endswith(".sample"))


def _clear_hooks(root: Path) -> None:
    """Empty the hook directory, so what is found afterwards has one cause.

    Building the repository runs `git add` and `git commit` through the same
    filter driver, and the driver installs its hooks there too. Without this the
    test reads hooks the SETUP wrote and attributes them to the probe, which is
    how it passes with the flag removed and fails with it present.
    """
    hooks = root / ".git" / "hooks"
    if not hooks.is_dir():
        return
    for path in hooks.iterdir():
        if not path.name.endswith(".sample"):
            path.unlink()


def _repo(root: Path, *, fsmonitor_log: Path | None = None) -> Path:
    """A repository in the racy-clean state the hazards need.

    The rewrite with identical content is the point: it leaves the file's mtime
    inside git's racy window without changing the tree, which is the state a
    repository a live session is editing is normally in.
    """
    _run("git", "init", "-q", cwd=root)
    _run("git", "config", "user.email", "probe@example.invalid", cwd=root)
    _run("git", "config", "user.name", "Probe", cwd=root)
    (root / "a.txt").write_text("one\n")
    _run("git", "add", "a.txt", cwd=root)
    _run("git", "commit", "-q", "-m", "one", cwd=root)
    if fsmonitor_log is not None:
        hook = root / "fsmonitor.sh"
        # newline="" so the shebang stays `#!/bin/sh` on Windows too. The default
        # translation writes `#!/bin/sh\r`, which no shell honours, and the test
        # that reads the log then passes for a reason that is not the flag.
        hook.write_text(f'#!/bin/sh\necho ran >> "{fsmonitor_log}"\nexit 1\n', newline="")
        hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
        _run("git", "config", "core.fsmonitor", str(hook), cwd=root)
    # Rewrite with identical content, so the tree is clean and the stat is racy.
    time.sleep(0.01)
    (root / "a.txt").write_text("one\n")
    return root


class RemoteStampTest(unittest.TestCase):
    """`remote_stamp` keys a cached `origin` on two stats and starts no program, so a hand-built
    `.git` stands in for a repository and nothing here needs git."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.git_dir = self.root / ".git"
        self.git_dir.mkdir()
        (self.git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        self.config = self.git_dir / "config"
        self.config.write_text('[remote "origin"]\n\turl = a\n', encoding="utf-8")

    def test_a_same_size_rewrite_in_the_same_tick_changes_the_stamp(self) -> None:
        before = git_status.remote_stamp(str(self.root))
        seen = self.config.stat()
        swap = self.git_dir / "config.new"
        swap.write_text('[remote "origin"]\n\turl = b\n', encoding="utf-8")
        os.utime(swap, ns=(seen.st_atime_ns, seen.st_mtime_ns))
        swap.replace(self.config)
        os.utime(self.config, ns=(seen.st_atime_ns, seen.st_mtime_ns))
        after = git_status.remote_stamp(str(self.root))
        self.assertEqual(seen.st_size, self.config.stat().st_size)
        self.assertNotEqual(before, after)

    def test_a_fifo_where_the_git_file_belongs_never_blocks_the_reader(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("no named pipes here")
        shutil.rmtree(self.git_dir)
        fifo = self.root / ".git"
        os.mkfifo(fifo)
        found: list[object] = []
        # Measured at well under a millisecond; a blocked open waits for ever, so the bound is a
        # loaded runner's allowance and not a speed claim.
        worker = threading.Thread(
            target=lambda: found.append(git_status.remote_stamp(str(self.root))), daemon=True
        )
        worker.start()
        worker.join(5)
        if worker.is_alive():
            with contextlib.suppress(OSError):
                os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
        self.assertFalse(worker.is_alive(), "remote_stamp blocked on a named pipe")
        self.assertEqual([None], found)

    def test_a_fifo_for_commondir_never_blocks_the_reader(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("no named pipes here")
        shutil.rmtree(self.git_dir)
        tree = self.root / "tree"
        tree.mkdir()
        gitdir = self.root / "wt-gitdir"
        gitdir.mkdir()
        (tree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        os.mkfifo(gitdir / "commondir")
        found: list[object] = []
        worker = threading.Thread(
            target=lambda: found.append(git_status.remote_stamp(str(tree))), daemon=True
        )
        worker.start()
        worker.join(5)
        if worker.is_alive():
            with contextlib.suppress(OSError):
                os.close(os.open(gitdir / "commondir", os.O_WRONLY | os.O_NONBLOCK))
        self.assertFalse(worker.is_alive(), "remote_stamp blocked on a named pipe")

    def test_no_git_computes_no_stamp(self) -> None:
        config = SimpleNamespace(git_probe_enabled=False)
        with mock.patch.object(git_status, "remote_stamp") as stamp:
            remote = ci_read.folder_remote(
                config,  # type: ignore[arg-type]
                str(self.root),
                git_status.StampCache(),
            )
        self.assertEqual(("", ""), remote)
        stamp.assert_not_called()


@unittest.skipIf(GIT is None, "git is not on PATH")
class GitProbeContractTest(unittest.TestCase):
    """AC1 and AC2: one argv, and the three hazards its flags disarm.

    "Neither writes nor executes" is no longer the whole claim. The probe does not
    write the index and does not run the repository's fsmonitor script, and since
    2026-09-07 it installs no hook either; a filter driver named by the inspected
    repository's own `.git/config` can still run. SECURITY.md owns that residual.
    """

    def test_the_probe_is_exactly_the_one_bounded_command(self) -> None:
        # Bound 1 of DEC-3, as amended: this literal, or there is no probe. All
        # three flags are independently load-bearing (see the three tests below),
        # so this asserts the whole argv rather than membership of any one flag.
        self.assertEqual(
            (
                "git",
                "-c",
                "core.fsmonitor=",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "status.showUntrackedFiles=normal",
                "--no-optional-locks",
                "status",
                "--porcelain",
            ),
            git_status.GIT_STATUS_ARGV,
        )

    def test_untracked_entries_survive_display_config(self) -> None:
        # Removing the override must fail the three suppressing arms, while
        # clean and ignored controls still follow Git's tracking/ignore rules.
        with tempfile.TemporaryDirectory(
            prefix="fix-git-probe-untracked-and-refusal-record-"
        ) as tmp:
            parent = Path(tmp)
            template = parent / "empty-template"
            template.mkdir()
            xdg_config = parent / "empty-xdg-config"
            xdg_config.mkdir()
            global_config = parent / "global-config"
            global_config.write_text("[status]\n\tshowUntrackedFiles = no\n")
            base = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            base.update(
                GIT_CONFIG_GLOBAL=os.devnull,
                GIT_CONFIG_SYSTEM=os.devnull,
                GIT_CONFIG_NOSYSTEM="1",
                GIT_TEMPLATE_DIR=str(template),
                # Git's default XDG ignore file survives disabling global config.
                XDG_CONFIG_HOME=str(xdg_config),
            )
            arms = {
                "baseline": {},
                "GIT_CONFIG_GLOBAL": {"GIT_CONFIG_GLOBAL": str(global_config)},
                "GIT_CONFIG_COUNT": {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "status.showUntrackedFiles",
                    "GIT_CONFIG_VALUE_0": "no",
                },
                "local-config": {},
            }
            for arm, config in arms.items():
                with _environment({**base, **config}):
                    root = _fresh(parent, arm)
                    if arm == "local-config":
                        _run(
                            "git", "config", "--local", "status.showUntrackedFiles", "no", cwd=root
                        )
                    with self.subTest(arm=arm, state="clean"):
                        self.assertEqual(
                            git_status.GitStatus(dirty=False, changed=0),
                            git_status.probe(str(root), timeout_sec=10.0),
                        )
                    (root / "work.txt").write_text("untracked\n")
                    control = subprocess.run(
                        (GIT or "git", "--no-optional-locks", "status", "--porcelain"),
                        cwd=root,
                        capture_output=True,
                        check=True,
                    )
                    with self.subTest(arm=arm, state="display-control"):
                        self.assertEqual(
                            b"?? work.txt\n" if arm == "baseline" else b"", control.stdout
                        )
                    with self.subTest(arm=arm, state="untracked"):
                        self.assertEqual(
                            git_status.GitStatus(dirty=True, changed=1),
                            git_status.probe(str(root), timeout_sec=10.0),
                        )
                    excludes = parent / f"{arm}-excludes"
                    excludes.write_text("work.txt\n")
                    _run("git", "config", "--local", "core.excludesFile", str(excludes), cwd=root)
                    with self.subTest(arm=arm, state="ignored"):
                        self.assertEqual(
                            git_status.GitStatus(dirty=False, changed=0),
                            git_status.probe(str(root), timeout_sec=10.0),
                        )

    def test_the_probe_does_not_write_the_index(self) -> None:
        # `--no-optional-locks` is what stops this. Without it git resolves the
        # racy stat by rewriting `.git/index`, which breaks the read-only posture
        # SECURITY.md states for everything Compass touches.
        with tempfile.TemporaryDirectory() as tmp:
            control = _fresh(Path(tmp), "control")
            control_index = control / ".git" / "index"
            control_before = control_index.stat().st_mtime_ns
            subprocess.run(WITHOUT_NO_OPTIONAL_LOCKS, cwd=control, check=False, capture_output=True)
            if control_index.stat().st_mtime_ns == control_before:
                # The write this test exists to prevent did not happen even with
                # the flag removed, so passing below would say nothing. Coarse
                # mtime granularity relative to git's racy window is the way this
                # is reached, and a silent pass is exactly the vacuity R7 named.
                self.skipTest("git did not rewrite the index without --no-optional-locks")
            root = _fresh(Path(tmp), "probed")
            index = root / ".git" / "index"
            before = index.stat().st_mtime_ns
            git_status.probe(str(root), timeout_sec=10.0)
            self.assertEqual(before, index.stat().st_mtime_ns)

    def test_the_probe_does_not_execute_a_repository_supplied_script(self) -> None:
        # `-c core.fsmonitor=` is what stops this. Without it a script named by
        # the inspected repository's own `.git/config` runs under Compass's
        # identity — arbitrary execution sourced from the directory being read.
        with tempfile.TemporaryDirectory() as tmp:
            control_log = Path(tmp) / "control.log"
            control = _fresh(Path(tmp), "control", fsmonitor_log=control_log)
            subprocess.run(WITHOUT_FSMONITOR_OFF, cwd=control, check=False, capture_output=True)
            if not control_log.exists():
                # The mechanism could not be armed on this host, so an empty log
                # below would prove nothing about the flag. Git for Windows is
                # the case in hand: no exec bit and a shell that may decline the
                # script outright.
                self.skipTest("git did not run the repository's fsmonitor without -c fsmonitor=")
            log = Path(tmp) / "fsmonitor.log"
            root = _fresh(Path(tmp), "probed", fsmonitor_log=log)
            git_status.probe(str(root), timeout_sec=10.0)
            self.assertFalse(log.exists(), "the repository's fsmonitor script ran")

    @unittest.skipIf(LFS is None, "git-lfs is not on PATH")
    def test_the_probe_does_not_install_a_hook_in_the_repository(self) -> None:
        # `-c core.hooksPath=/dev/null` is what stops this. Without it, hashing a
        # tracked path whose committed attributes name a filter driver lets that
        # driver install its own hooks: measured 2026-09-07 at git 2.55.0 with
        # git-lfs 3.8.0, four files at mode 0755 — post-checkout, post-commit,
        # post-merge and pre-push — written inside a repository the probe was
        # only meant to read. `.git/index` was untouched in both arms, so neither
        # existing flag sees this and neither existing test could have caught it.
        with tempfile.TemporaryDirectory() as tmp:
            control = _filtered(Path(tmp), "control")
            _clear_hooks(control)
            subprocess.run(WITHOUT_HOOKS_PATH_OFF, cwd=control, check=False, capture_output=True)
            if not _installed_hooks(control):
                # The driver installed nothing even with the flag removed, so an
                # empty directory below would prove nothing about the flag. A
                # git-lfs that does not install hooks from the clean filter, or
                # one whose global config names no filter driver, reaches this.
                self.skipTest("git-lfs installed no hook without -c core.hooksPath=")
            root = _filtered(Path(tmp), "probed")
            _clear_hooks(root)
            self.assertEqual([], _installed_hooks(root), "the clear did not take")
            git_status.probe(str(root), timeout_sec=10.0)
            self.assertEqual([], _installed_hooks(root), "a hook was installed in the repository")


@unittest.skipIf(GIT is None, "git is not on PATH")
class GitProbeEnvironmentTest(unittest.TestCase):
    """The reading is about the directory it names, and about no other.

    Both tests here run a POSITIVE CONTROL first, for the same reason the three
    hazard tests above do: without it neither can tell "the scrub worked" from
    "the mechanism was never armed here".
    """

    def test_an_inherited_git_dir_cannot_point_the_reading_elsewhere(self) -> None:
        # R16. Measured before the fix: probe() on a CLEAN repository returned
        # a dirty reading belonging to a different repository, because the
        # subprocess inherited GIT_DIR and GIT_WORK_TREE from the environment.
        # `isdir` does not help — a directory that is not a repository at all
        # returned the other repository's reading too.
        with tempfile.TemporaryDirectory() as tmp:
            outer = _fresh(Path(tmp), "outer")
            (outer / "one.txt").write_text("changed\n")
            (outer / "two.txt").write_text("new\n")
            (outer / "three.txt").write_text("new\n")
            inner = _fresh(Path(tmp), "inner")
            clean = git_status.probe(str(inner), timeout_sec=10.0)
            self.assertEqual(git_status.GitStatus(dirty=False, changed=0), clean)

            environ = {
                **os.environ,
                "GIT_DIR": str(outer / ".git"),
                "GIT_WORK_TREE": str(outer),
            }
            control = subprocess.run(
                git_status.GIT_STATUS_ARGV,
                cwd=inner,
                capture_output=True,
                env=environ,
                check=False,
            )
            leaked = sum(1 for line in control.stdout.split(b"\n") if line.strip())
            if leaked == 0:
                # The environment did not redirect git on this host, so an equal
                # reading below would prove nothing about the scrub.
                self.skipTest("GIT_DIR did not redirect git on this host")

            with _environment(environ):
                self.assertEqual(clean, git_status.probe(str(inner), timeout_sec=10.0))

    def test_a_relative_path_element_cannot_supply_the_executable(self) -> None:
        # R12. The rule is ORDER, not position: ANY empty or relative PATH
        # element before the first element holding a real `git` hijacks. The
        # register and its verifier both stated this wrongly, in opposite
        # directions, because /usr/bin/git exists on macOS and contaminated
        # both readings. The trailing arms are asserted NEGATIVE so this test
        # cannot pass by resolving nothing at all.
        with tempfile.TemporaryDirectory() as tmp:
            probed = Path(tmp) / "probed"
            probed.mkdir()
            fake = probed / "git"
            # Seven entries, a count no real repository here produces, and the
            # probed directory is deliberately NOT a repository so real git
            # returns None and any reading at all means the fake ran.
            fake.write_text(
                '#!/bin/sh\nfor i in 1 2 3 4 5 6 7; do echo " M f$i"; done\n', newline=""
            )
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            git_free = Path(tmp) / "git-free"
            git_free.mkdir()
            real = str(Path(GIT or "/usr/bin/git").parent)

            hijacks = {
                "leading relative": f".:{real}",
                "leading empty": f":{real}",
                "interior empty": f"{git_free}::{real}",
                "interior relative": f"{git_free}:.:{real}",
            }
            harmless = {
                "trailing empty": f"{real}:",
                "trailing relative": f"{real}:.",
                "unmodified": real,
            }
            # The negative controls run FIRST and unconditionally, so they cannot
            # be stranded behind a skip the arming decides (DRC-4466 AC2).
            for label, path in harmless.items():
                with (
                    self.subTest(arm=label),
                    _environment({**os.environ, "PATH": path}, cwd=probed),
                ):
                    self.assertIsNone(git_status.probe(str(probed), timeout_sec=10.0))

            # DRC-4466. The arming used to ask the code under test whether the
            # hijack had worked: `armed` was set only where `probe` returned
            # `changed == 7`, so a guard that holds disarmed the test's own
            # report. `44525c0` (#293) added this test and, in the same commit, a
            # scrub over `frozenset({"", "."})` — precisely the two forms all
            # four arms below are built from — so the arms were neutralised on
            # the commit that introduced them and this skipped on every green
            # tree since, stranding the three controls above behind the skip.
            #
            # Narrower than "it could never fail", which was measured and is not
            # true: with BOTH ends of the guard reverted the old arming failed
            # here too, on all four arms. What it could never do is RUN.
            #
            # So the arm is armed by the HOST's resolver instead, the way the
            # sibling below does it: if `shutil.which` hands back a non-absolute
            # answer for this PATH from the probed directory, a probe that
            # trusted PATH would run that file and the assertion means something.
            armed = False
            for label, path in hijacks.items():
                with self.subTest(arm=label):
                    with _environment({**os.environ, "PATH": path}, cwd=probed):
                        hijacked = shutil.which("git", path=path)
                        reading = git_status.probe(str(probed), timeout_sec=10.0)
                    if hijacked is not None and not os.path.isabs(hijacked):
                        armed = True
                    self.assertNotEqual(
                        7,
                        getattr(reading, "changed", None),
                        f"the probed directory's own `git` supplied the executable ({label})",
                    )
            if not armed:
                # No arm's mechanism could be armed here, so a pass above would
                # prove nothing. Recorded rather than passed silently, per this
                # file's rule. Windows reaches this: `which` resolves a bare name
                # through PATHEXT, which the stub written here does not carry.
                self.skipTest("no PATH shape resolves to a relative git on this host")

    def test_a_bare_relative_path_element_cannot_supply_the_executable(self) -> None:
        # DRC-4454, and it is a confusion of deputy rather than only a scrub gap:
        # `shutil.which` validates the binary against the DASHBOARD's working
        # directory and the child then resolves the SAME relative string against
        # the directory being probed, which is session-supplied. Measured at
        # 6de8f0a: `which` returned the decoy's two entries and the reading
        # published seven, from a directory that is not a repository at all.
        #
        # The sibling above covers `.` and empty elements only, which is exactly
        # the pair the old scrub dropped, so it could not have caught this.
        with tempfile.TemporaryDirectory() as tmp:
            dash = Path(tmp) / "dash"
            probed = Path(tmp) / "probed"
            (dash / "relbin").mkdir(parents=True)
            (probed / "relbin").mkdir(parents=True)
            # Two entries where `which` looks, seven where the child resolves.
            # Seven is a count no repository here produces, and `probed` is
            # deliberately not a repository, so any reading means a stub ran.
            _write_stub(dash / "relbin" / "git", '#!/bin/sh\necho " M a"\necho " M b"\n')
            _write_stub(
                probed / "relbin" / "git",
                '#!/bin/sh\nfor i in 1 2 3 4 5 6 7; do echo " M f$i"; done\n',
            )
            real = str(Path(GIT or "/usr/bin/git").parent)

            hijack = f"relbin{os.pathsep}{real}"
            with _environment({**os.environ, "PATH": hijack}, cwd=dash):
                decoy = shutil.which("git", path="relbin")
                if decoy is None or os.path.isabs(decoy):
                    # The mechanism could not be armed here — `which` resolved
                    # nothing, or resolved it absolutely — so a null below would
                    # prove nothing. Recorded rather than passed silently, per
                    # this file's rule. Windows reaches this: `which` resolves a
                    # bare name through PATHEXT, which this stub does not carry.
                    self.skipTest("a relative PATH element resolves to no git here")
                reading = git_status.probe(str(probed), timeout_sec=10.0)
            self.assertIsNone(
                reading,
                "the probed directory's own `git` supplied the executable (bare relative)",
            )
            # And the control, so this cannot pass by resolving nothing at all:
            # the same probe with an absolute-only PATH reaches real git, which
            # refuses a directory that is not a repository.
            with _environment({**os.environ, "PATH": real}, cwd=dash):
                self.assertIsNone(git_status.probe(str(probed), timeout_sec=10.0))
                self.assertTrue(os.path.isabs(git_status._executable({"PATH": real}) or ""))


class SingleInvocationTest(unittest.TestCase):
    """AC1's other half: the runtime builds a git subprocess at exactly one site.

    Before this feature that count was zero — a grep for git across
    `compass_runtime/` returned nothing — so "exactly one" is a baseline this
    test establishes rather than an assumption it inherits. The likely second site
    is a `rev-parse` to answer "is this a repository?", and it must be folded into
    the one invocation instead: a non-repository is already distinguishable from
    the single command's exit status.

    Undecorated, for `GitProbeCallSiteTest`'s reason and measured the same way:
    every test here reads source text and spawns nothing, and with PATH pointed at
    an empty directory the `skipIf(GIT is None)` this class used to carry made the
    whole of AC1's second half disappear on exactly the host where a reviewer
    checking the boundary is most likely to be looking.

    Why a linter is not the oracle: `ruff check --select S6 .` is clean repo-wide
    and always was. `S607` (partial-executable-path) is syntactic, and argv[0] at
    the one call site is a variable — the resolved path — so the rule can never
    see it. That is the whole of what survives the cancelled DRC-4437.

    Two oracles, because neither subsumes the other. The shape walker reads the
    invocation and so sees `shell=`, an absolute path, `os.system`, a folded
    concatenation, an `os.environ.get` default and an f-string; the grep reads the
    text and so still sees a quoted `git` handed to something the walker cannot
    recognise as a spawner. Measured against ten evasion shapes introduced one at
    a time: the walker caught ten of ten, the grep three.
    """

    def test_the_oracles_read_the_shipped_siblings_too(self) -> None:
        # The widening is the load-bearing half of R14, and the guard written for
        # it could not see it go vacuous. `_shipped_sources` builds the sibling
        # half FROM `_SHIPPED_SIBLINGS` with no existence check, so asserting the
        # tuple's own names appear in that list compared a tuple against a set
        # derived from the same tuple. Measured: the tuple emptied and
        # `os.system("git status --porcelain")` planted in `event_hook.py` left
        # this class at 6 tests OK with both oracles blind.
        #
        # So the expectation comes off the filesystem, through the same
        # non-recursive glob `scripts/tests/test_validate_plugins.py` already pins
        # `COMPASS_RUNTIME_FILES` against. A hook adapter renamed, added or
        # dropped fails here, and the two inventories agree by construction
        # rather than by two people remembering the same list.
        self.assertEqual(
            sorted(path.name for path in _SKILL.glob("*.py")), sorted(_SHIPPED_SIBLINGS)
        )
        # The package half is an rglob and cannot go vacuous the same way, but an
        # empty scan set would still pass every oracle below.
        self.assertIn("git_status.py", {path.name for path in _shipped_sources()})

    def test_only_git_status_spawns_a_program_named_git(self) -> None:
        # The invocation-shape oracle. `git_status.py` must be the ONE offender:
        # an empty result here would mean the walker stopped following the
        # injected-runner seam, not that the runtime got safer.
        offenders = sorted(
            path.name
            for path in _shipped_sources()
            if _spawned_programs(path.read_text(encoding="utf-8"))
        )
        self.assertEqual(["git_status.py"], offenders)

    def test_only_the_git_probe_and_lexical_hook_matcher_name_git(self) -> None:
        offenders = sorted(
            path.name
            for path in _shipped_sources()
            if _quotes_git(path.read_text(encoding="utf-8"))
        )
        # The hook compares a literal without executing it; the invocation
        # oracle immediately above still permits only the probe to spawn git.
        self.assertEqual(["event_hook.py", "git_status.py"], offenders)

    def test_the_shape_oracle_sees_the_evasions_the_grep_cannot(self) -> None:
        # Each of these was introduced into a real shipped file one at a time and
        # measured; they are held here as source fragments so the measurement is
        # repeatable without editing the runtime. The first three are the only
        # ones the grep alone caught.
        for label, source in (
            ("list literal", 'subprocess.run(["git", "status"], check=False)'),
            ("tuple literal", 'subprocess.run(("git", "status"), check=False)'),
            ("os.execvp", 'os.execvp("git", ["git", "status"])'),
            ("shell string", 'subprocess.run("git status --porcelain", shell=True, check=False)'),
            ("absolute path", 'subprocess.run(["/usr/bin/git", "status"], check=False)'),
            ("os.system", 'os.system("git status --porcelain")'),
            ("concatenated name", 'subprocess.run(["gi" + "t", "status"], check=False)'),
            ("env default", 'subprocess.run(os.environ.get("P", "git s").split(), check=False)'),
            ("f-string name", 'd = "/usr/bin"\nsubprocess.run([f"{d}/git", "s"], check=False)'),
            ("injected runner", 'runner(("git", "status"), check=False)'),
            # DRC-4465's three, each measured missed by BOTH oracles before this
            # commit. The first is the one that matters: it is ordinary code
            # rather than obfuscation, so a second call site written this way
            # would have left the whole suite green.
            (
                "function-local absolute name",
                'def f():\n    exe = "/usr/bin/git"\n    subprocess.run([exe, "s"], check=False)',
            ),
            (
                "private spawn helper",
                (
                    "def _spawn(argv):\n"
                    "    return subprocess.run(argv, check=False)\n"
                    'def go():\n    return _spawn(["/usr/bin/git", "status"])'
                ),
            ),
            (
                "os.posix_spawn, non-literal program",
                (
                    'def f():\n    exe = "/usr/bin/git"\n'
                    '    os.posix_spawn(exe, ["git", "s"], os.environ)'
                ),
            ),
            # And a fourth found while measuring those: the argv never binds to a
            # name at all, it is passed as an argument to a helper that spawns.
            (
                "argv handed to a helper that spawns",
                (
                    "def _go(argv):\n"
                    "    subprocess.run(argv, check=False)\n"
                    'def f():\n    _go(["/usr/bin/git", "status"])'
                ),
            ),
        ):
            with self.subTest(shape=label):
                self.assertTrue(_spawned_programs(source), f"{label} evaded the shape oracle")

    def test_the_oracles_do_not_claim_to_see_a_name_computed_at_runtime(self) -> None:
        # The boundary, recorded so the class above is not read as complete.
        # These four evade BOTH oracles and are left evading on purpose: each
        # computes the spawner or the program name at runtime, so catching them
        # means interpreting the module rather than reading it, and none is a
        # shape a second git call site gets written in by accident. What the
        # oracles guard is ordinary Python, which is why DRC-4465's three are
        # asserted above and these are only named.
        #
        # Measured 2026-09-08 against the widened walker: all four still missed.
        for label, source in (
            ("getattr spawner", 'getattr(subprocess, "run")(["/usr/bin/git", "s"], check=False)'),
            ("functools.partial", 'functools.partial(subprocess.run, ["/usr/bin/git"])()'),
            ("exec of a source string", "exec(\"subprocess.run(['/usr/bin/git'])\")"),
            ("hex-decoded name", 'n = bytes.fromhex("676974").decode()\nsubprocess.run([n])'),
        ):
            with self.subTest(shape=label):
                self.assertFalse(
                    _spawned_programs(source) or _quotes_git(source),
                    f"{label} is now caught; move it into the table above",
                )

    def test_neither_oracle_fires_on_prose(self) -> None:
        # The grep's one measured false positive, and the shape walker's own
        # exposure to the same class. A file that only TALKS about git is not an
        # offender, or the oracles cost more to keep green than they are worth.
        comment = "# a comment mentioning 'git' on purpose\nx = 1\n"
        self.assertFalse(_quotes_git(comment))
        self.assertFalse(_spawned_programs(comment))
        docstring = '"""What `git` does, and a git word in prose."""\nx = 1\n'
        self.assertFalse(_spawned_programs(docstring))

    def test_the_argv_is_a_tuple_a_caller_cannot_extend(self) -> None:
        # A list would let a caller append to the argv it was handed, which is the
        # cheapest way a second flag or a pathspec reaches the one bounded command.
        self.assertIsInstance(git_status.GIT_STATUS_ARGV, tuple)


# `_repo` runs `git init` with `check=True`, so without this guard these two
# ERROR rather than skip where git is absent, which AC2 forbids in as many words.
# Measured with PATH pointed at a shim: 2 errors, 6 skips. The sixth arrived
# with the hook test, which skips on a host with no git-lfs.
@unittest.skipIf(GIT is None, "git is not on PATH")
class GitProbeReadingTest(unittest.TestCase):
    """What the two published scalars actually mean."""

    def test_a_clean_tree_reads_clean_with_no_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            result = git_status.probe(str(root), timeout_sec=10.0)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertFalse(result.dirty)
            self.assertEqual(0, result.changed)

    def test_changed_counts_porcelain_entries_rather_than_files(self) -> None:
        # The measured case from triage: one modified tracked file plus an
        # untracked directory holding three files is 2 entries for 4 changed
        # files, because git collapses the untracked directory into one entry.
        # Publishing 4 here would be a file count wearing an entry count's name.
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            (root / "a.txt").write_text("two\n")
            nested = root / "new"
            nested.mkdir()
            for name in ("x", "y", "z"):
                (nested / name).write_text("x\n")
            result = git_status.probe(str(root), timeout_sec=10.0)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.dirty)
            self.assertEqual(2, result.changed)


class GitProbeCallSiteTest(unittest.TestCase):
    """What `probe()` actually hands `runner` — the argv constant proves nothing about it.

    Undecorated on purpose: this needs no git, and the pin must hold on a host
    where the three behavioural tests above skip. Measured before it existed:
    stripping BOTH flags from the `runner(...)` call left
    `test_the_probe_is_exactly_the_one_bounded_command` green, because that test
    reads the constant and nothing read the call.

    That claim stopped being true when #293 taught `probe` to resolve its own
    executable and return before `runner` if it finds none: measured with PATH
    pointed at an empty directory, one failure and two errors here, all three
    reading `seen[0]` of an empty list. `_git_on_path` is what restores it — a
    stub the resolver can find, rather than a second injection seam past the
    resolution guard.
    """

    def _spy(self) -> tuple[Any, list[tuple[Any, dict[str, Any]]]]:
        seen: list[tuple[Any, dict[str, Any]]] = []

        def runner(argv: Any, **kwargs: Any) -> Any:
            seen.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        return runner, seen

    def test_the_probe_passes_the_bounded_argv_and_nothing_else(self) -> None:
        runner, seen = self._spy()
        with _git_on_path(), tempfile.TemporaryDirectory() as tmp:
            # A real directory, because `probe` returns before spawning anything
            # when `isdir` is false — which is how this test would go vacuous.
            git_status.probe(tmp, timeout_sec=3.5, runner=runner)
        self.assertEqual(1, len(seen), "the probe ran other than exactly one command")
        argv, _kwargs = seen[0]
        # argv[0] is the RESOLVED path, not the bare name the constant prints.
        # Asserting absoluteness is the point: a bare name is resolved by the
        # child against a PATH the probe does not control, and that is how an
        # empty or relative element ahead of the first real `git` supplied the
        # binary from the session's own directory.
        self.assertTrue(os.path.isabs(argv[0]), f"argv[0] is not an absolute path: {argv[0]!r}")
        self.assertEqual("git", Path(argv[0]).stem)
        # Everything after argv[0] is the constant, unchanged.
        self.assertEqual(git_status.GIT_STATUS_ARGV[1:], tuple(argv[1:]))
        self.assertIn("status.showUntrackedFiles=normal", argv)

    def test_the_probe_scrubs_the_environment_it_hands_the_child(self) -> None:
        # The scrub is asserted here as well as behaviourally above, because this
        # one runs on a host with no git and pins the exact keys.
        runner, seen = self._spy()
        with _git_on_path() as bindir:
            hostile = {
                **os.environ,
                "PATH": bindir,
                "GIT_DIR": "/elsewhere/.git",
                "GIT_WORK_TREE": "/elsewhere",
            }
            with tempfile.TemporaryDirectory() as tmp, _environment(hostile):
                git_status.probe(tmp, timeout_sec=3.5, runner=runner)
        _argv, kwargs = seen[0]
        self.assertNotIn("GIT_DIR", kwargs["env"])
        self.assertNotIn("GIT_WORK_TREE", kwargs["env"])
        # And the child gets an environment at all, rather than inheriting.
        self.assertIsNotNone(kwargs.get("env"))

    def test_the_scrub_drops_every_element_a_working_directory_could_resolve(self) -> None:
        # A unit assertion on the helper, so the rule is stated once where it can
        # be read: nothing the resolver would resolve against a working directory
        # survives, which is what makes the order of what remains irrelevant.
        #
        # DRC-4454. The predecessor of this test exercised `.` and `""` alone, so
        # it passed while every other relative form was kept: a bare `relbin`,
        # `./bin`, `..` and `sub/bin` all survived, and one of them supplied the
        # executable from the directory being probed.
        #
        # DRC-4469 renamed it off "non-absolute", which was the wrong property to
        # name: `ntpath.isabs(r"\bin")` is True at the 3.11 and 3.12 the gate
        # runs, so the last two elements below are ones Windows calls absolute
        # and this filter must drop anyway. On this POSIX host they are dropped
        # for the ordinary reason and prove nothing; the arm that bites runs on
        # the `platform-tests` Windows runner, and the sibling below arms the
        # Windows predicate here.
        absolute = os.path.abspath(os.sep + "usr" + os.sep + "bin")
        for element in (
            "",
            ".",
            "..",
            "relbin",
            "." + os.sep + "bin",
            "sub" + os.sep + "bin",
            "\\bin",
            "C:bin",
        ):
            with self.subTest(element=element):
                path = os.pathsep.join([element, absolute])
                self.assertEqual(
                    absolute,
                    git_status.probe_environment({"PATH": path})["PATH"],
                    f"an element a working directory could resolve survived: {element!r}",
                )
        # The second trusted element is built with `abspath` like the first rather
        # than written as `/bin`. A literal `/bin` is a driveless root on Windows,
        # so it is one of the elements DRC-4469 makes the filter DROP there, and
        # asserting it survives would fail the Windows runner. `abspath` gains the
        # current drive there and changes nothing on POSIX.
        second = os.path.abspath(os.sep + "bin")
        scrubbed = git_status.probe_environment(
            {"PATH": f".{os.pathsep}{os.pathsep}{absolute}{os.pathsep}.{os.pathsep}{second}"}
        )
        self.assertEqual(f"{absolute}{os.pathsep}{second}", scrubbed["PATH"])
        # An entirely untrusted PATH leaves nothing, and `which` then finds no
        # git, which publishes None rather than falling back to the ambient PATH.
        self.assertEqual("", git_status.probe_environment({"PATH": f".{os.pathsep}"})["PATH"])

    def test_a_driveless_root_is_untrusted_under_the_windows_flavour(self) -> None:
        # DRC-4469, armed HERE rather than only on the Windows runner. The element
        # list above cannot bite off Windows — `\bin` is plainly relative to
        # `posixpath`, so it is dropped there for the ordinary reason and proves
        # nothing about the predicate this test is for. Swapping the flavour runs
        # the real `_rooted` against real `ntpath` semantics on any host.
        #
        # The three calls are made inside the patched window and asserted outside
        # it, so nothing but a pure predicate ever sees a mismatched `os.name` and
        # `os.path`.
        if sys.version_info < (3, 13):
            # The reason the guard exists, pinned rather than left in a comment:
            # measured 2026-09-08, `ntpath.isabs(r"\bin")` is True on 3.11.9 and
            # 3.12.13 and False on 3.13.13 and 3.14.7. The gate runs 3.11 and
            # 3.12, so this is the reading that ships. If CPython ever backports
            # the change, this says so instead of the comment going stale.
            self.assertTrue(
                ntpath.isabs("\\bin"),
                "`os.path.isabs` no longer keeps a driveless root; re-read DRC-4469",
            )
        with mock.patch.object(os, "name", "nt"), mock.patch.object(os, "path", ntpath):
            driveless = git_status._rooted("\\bin")
            drive_relative = git_status._rooted("C:bin")
            fully_qualified = git_status._rooted("C:\\bin")
        # A driveless root resolves against the process's current drive, which is
        # part of its working directory, so it is exactly what the filter claims
        # to drop — and what `os.path.isabs` alone kept at the 3.11/3.12 floor.
        self.assertFalse(driveless, "a driveless root survived the Windows predicate")
        # The drive-relative form `isabs` already refused. Kept as a control, so
        # this test cannot pass by refusing everything.
        self.assertFalse(drive_relative, "a drive-relative element survived")
        self.assertTrue(fully_qualified, "a fully qualified Windows path was refused")

    def test_the_resolver_refuses_a_driveless_root_under_the_windows_flavour(self) -> None:
        # The OTHER end, under the same flavour. `_executable`'s docstring claims
        # the duplication holds if the scrub is ever wrong again, and DRC-4469 is
        # the second time it was, so the claim gets a check rather than a
        # sentence. On Windows `shutil.which` answers with a path built from the
        # PATH element it matched, so a `\bin` element yields `\bin\git.exe` —
        # which `os.path.isabs` alone calls absolute at the 3.11/3.12 floor and
        # would hand straight to the child. `which` is stubbed because a real one
        # cannot be made to answer that way off Windows.
        with (
            mock.patch.object(os, "name", "nt"),
            mock.patch.object(os, "path", ntpath),
            # The module object this test imported, which is the same one
            # `git_status` imported; reaching it through `git_status.shutil`
            # instead is a re-export `mypy --strict` refuses.
            mock.patch.object(shutil, "which", return_value="\\bin\\git.exe"),
        ):
            resolved = git_status._executable({"PATH": "\\bin"})
        self.assertIsNone(resolved, "the resolver accepted a driveless-root answer")

    def test_the_resolver_refuses_a_git_it_could_only_resolve_relatively(self) -> None:
        # The OTHER end of the same guard, asserted where the scrub cannot reach
        # it: `_executable` is handed a PATH the scrub never saw. The scrub filter
        # has already been wrong once — it named this property and enforced two
        # elements of it — so a future change to that one list cannot reopen the
        # hijack while this end also refuses.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "relbin").mkdir()
            _write_stub(root / "relbin" / _STUB_NAME)
            with _environment(dict(os.environ), cwd=root):
                # The arm is armed: `which` really does resolve this, relatively.
                self.assertIsNotNone(shutil.which("git", path="relbin"))
                self.assertIsNone(git_status._executable({"PATH": "relbin"}))

    def test_the_probe_passes_the_bounds_the_contract_names(self) -> None:
        # The cwd it was asked about, the caller's timeout, and a closed stdin so
        # a repository configured to ask for a credential cannot stall the probe.
        # No `shell=`, which is AC1's evasion shape the argv assertion cannot see.
        runner, seen = self._spy()
        with _git_on_path(), tempfile.TemporaryDirectory() as tmp:
            git_status.probe(tmp, timeout_sec=3.5, runner=runner)
        _argv, kwargs = seen[0]
        self.assertEqual(tmp, kwargs["cwd"])
        self.assertEqual(3.5, kwargs["timeout"])
        self.assertEqual(subprocess.DEVNULL, kwargs["stdin"])
        self.assertNotIn("shell", kwargs)


class PorcelainCountTest(unittest.TestCase):
    """The count, against the expression it replaced. Needs no git and spawns nothing.

    DRC-4444. `_reading` used to build the whole list of lines to count them; it
    now walks one line at a time, and this class exists because a counting
    refactor that changes an edge case is indistinguishable from one that does
    not until something compares them. The parity oracle below is that
    comparison: the old expression, held here as the specification.

    Which is exactly why the parity oracle cannot also guard the memory property
    the rewrite was FOR: `_former` is the specification, so restoring the old
    expression satisfies it by construction. The two oracles are therefore
    independent, and the second one measures rather than compares.
    """

    @staticmethod
    def _former(raw: bytes) -> int:
        """What `_reading` counted before the streaming rewrite."""
        return sum(1 for line in raw.split(b"\n") if line.strip())

    def test_the_count_agrees_with_the_expression_it_replaced(self) -> None:
        for raw in (
            b"",
            b"\n",
            b" M a\n",
            # No trailing newline, which is what a truncated read looks like.
            b" M a\n M b",
            # A blank line and a whitespace-only line are entries in neither.
            b" M a\n\n M b\n",
            b"   \n\t\n",
            b"?? new/\n M a\nR  b -> c\n",
            b" M \xff\xfe\n",
            b"\r\n M a\r\n",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(
                    self._former(raw),
                    git_status._reading(raw).changed,
                    "the streaming count disagrees with the expression it replaced",
                )

    def test_the_count_does_not_materialise_the_whole_output(self) -> None:
        # AC1's stated second half, and the only oracle over the property the
        # rewrite exists for. Measured with the streaming loop replaced by the
        # `raw.split(b"\n")` expression it replaced: `test_git_status`,
        # `test_observation` and `test_documentation` were all green.
        #
        # The payload is built before the trace starts, so the peak is the count's
        # own allocation rather than the output's. The bound has three orders of
        # magnitude of headroom on purpose: the split peaks around 1.3 MB at this
        # N against a few hundred bytes streaming, and a tight pin would flake
        # across the 3.11/3.12 by three-platform matrix for no extra strictness.
        entries = 20000
        raw = b"".join(b" M src/module/file%05d.py\n" % index for index in range(entries))
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            reading = git_status._reading(raw)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        # Counted correctly, or a loop that allocates nothing because it walks
        # nothing would pass the bound below.
        self.assertEqual(entries, reading.changed)
        self.assertLess(
            peak,
            64 * 1024,
            f"the count allocated {peak} bytes over a {len(raw)}-byte output; it must stream",
        )

    def test_dirty_is_the_count_being_nonzero_and_nothing_else(self) -> None:
        self.assertEqual(git_status.GitStatus(dirty=False, changed=0), git_status._reading(b"\n"))
        self.assertEqual(
            git_status.GitStatus(dirty=True, changed=2), git_status._reading(b" M a\n?? b\n")
        )

    def test_a_stdout_that_is_neither_bytes_nor_text_reads_clean(self) -> None:
        # `runner` is injectable, so `stdout` is whatever the seam returned. A
        # None here must publish "no entries" rather than raise on a thread
        # nobody joins.
        self.assertEqual(git_status.GitStatus(dirty=False, changed=0), git_status._reading(None))
        self.assertEqual(git_status.GitStatus(dirty=True, changed=1), git_status._reading(" M a\n"))


class GitProbeRefusalTest(unittest.TestCase):
    """Every cause of a null, at the module's own boundary."""

    def test_a_directory_that_is_not_a_repository_is_not_probed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(git_status.probe(tmp, timeout_sec=10.0))

    def test_a_missing_directory_is_not_probed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gone = os.path.join(tmp, "nope")
            self.assertIsNone(git_status.probe(gone, timeout_sec=10.0))

    def test_git_absent_from_the_path_is_not_probed(self) -> None:
        def missing(*_args: object, **_kwargs: object) -> object:
            raise FileNotFoundError("git")

        self.assertIsNone(git_status.probe("/tmp", timeout_sec=10.0, runner=missing))

    def test_a_probe_that_timed_out_is_not_probed(self) -> None:
        def slow(*_args: object, **_kwargs: object) -> object:
            raise subprocess.TimeoutExpired(cmd="git", timeout=1.0)

        self.assertIsNone(git_status.probe("/tmp", timeout_sec=1.0, runner=slow))


if __name__ == "__main__":
    unittest.main()
