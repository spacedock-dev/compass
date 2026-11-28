"""Run only the CLI commands assembled by a registered Plan adapter."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from compass_runtime import ci_read, git_status, io, supervise

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from .tracker_source import Declaration

STDOUT_LIMIT = 256 * 1024
STDERR_LIMIT = 8 * 1024
REFRESH_BYTES = 1024 * 1024
REFRESH_CALLS = 32

_TOKEN_OVERRIDES = frozenset(
    {"GITHUB_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GIT_DIR", "GIT_WORK_TREE"}
)
_CLI_OVERRIDES = ("GH_", "GITLAB_", "GL_", "GLAB_", "OAUTH_TOKEN", "REMOTE_ALIAS")


class Reason(StrEnum):
    DISABLED = "disabled"
    REFRESHING = "refreshing"
    CLI_MISSING = "cli-missing"
    SIGNED_OUT = "signed-out"
    RATE_LIMITED = "rate-limited"
    TIMEOUT = "timeout"
    NOT_FOUND = "not-found-or-inaccessible"
    PARTIAL = "partial-result"
    UNREADABLE_OUTPUT = "unreadable-output"
    LIMIT_EXCEEDED = "limit-exceeded"
    CLI_FAILED = "cli-failed"


class TrackerError(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def environment(environ: Mapping[str, str]) -> dict[str, str]:
    # Windows treats environment names case-insensitively, including account and host overrides.
    return ci_read.environment(
        {
            key: value
            for key, value in environ.items()
            if key.upper() not in _TOKEN_OVERRIDES and not key.upper().startswith(_CLI_OVERRIDES)
        }
    )


def resolve(source: Declaration, environ: Mapping[str, str]) -> str | None:
    executable = git_status.executable(source.executable, environ)
    if os.name == "nt" and executable is not None and not executable.lower().endswith(".exe"):
        # Windows may interpret a batch file through a shell even with argv and shell=False.
        return None
    return executable


def _exit_reason(stderr: bytes) -> Reason:
    text = stderr.decode("utf-8", "replace")
    if re.search(r"\b429\b|rate limit", text, re.IGNORECASE):
        return Reason.RATE_LIMITED
    if re.search(
        r"\b401\b|gh auth login|not logged in|authentication required|bad credentials",
        text,
        re.IGNORECASE,
    ):
        return Reason.SIGNED_OUT
    if re.search(
        r"\b40[34]\b|not found|could not resolve to|resource not accessible", text, re.IGNORECASE
    ):
        return Reason.NOT_FOUND
    return Reason.CLI_FAILED


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _non_json_constant(_word: str) -> object:
    raise ValueError("non-JSON constant")


def _response(code: int, stdout: bytes, stderr: bytes, *, graphql: bool) -> object:
    if code == 4:
        raise TrackerError(Reason.SIGNED_OUT)
    if code != 0 and not graphql:
        raise TrackerError(_exit_reason(stderr))
    try:
        value = json.loads(
            stdout.decode("utf-8"),
            object_pairs_hook=_json_object,
            parse_constant=_non_json_constant,
        )
    except (ValueError, RecursionError):
        raise TrackerError(_exit_reason(stderr) if code else Reason.UNREADABLE_OUTPUT) from None
    # gh can print a GraphQL response with partial data before reporting errors on stderr.
    if code != 0:
        if isinstance(value, dict) and value.get("errors") and value.get("data") is not None:
            raise TrackerError(Reason.PARTIAL)
        raise TrackerError(_exit_reason(stderr))
    return value


class TrackerCLI:
    """One source refresh's rooted executable, private launch context and remaining allowance."""

    def __init__(
        self,
        source: Declaration,
        *,
        deadline: float,
        clock: Callable[[], float] = time.monotonic,
        environ: Mapping[str, str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[Any]] | None = None,
        check_current: Callable[[], None] | None = None,
    ) -> None:
        self._deadline = deadline
        self._clock = clock
        self._runner = runner
        self._check_current = check_current
        self._env = environment(os.environ if environ is None else environ)
        executable = resolve(source, self._env)
        if executable is None:
            raise TrackerError(Reason.CLI_MISSING)
        self._executable = executable
        self._calls = 0
        self._bytes = 0

    def _remaining(self) -> float:
        if self._check_current is not None:
            self._check_current()
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise TrackerError(Reason.TIMEOUT)
        return remaining

    def _before_spawn(self) -> None:
        self._remaining()

    def _capture(self, arguments: tuple[str, ...]) -> tuple[int, bytes, bytes]:
        with (
            tempfile.TemporaryDirectory(prefix="compass-tracker-cwd-") as cwd,
            tempfile.TemporaryDirectory(prefix="compass-tracker-out-") as output_dir,
        ):
            with (
                tempfile.NamedTemporaryFile(dir=output_dir, delete=False) as stdout,
                tempfile.NamedTemporaryFile(dir=output_dir, delete=False) as stderr,
            ):
                options: dict[str, Any] = {
                    "input": b"",
                    "cwd": cwd,
                    "stdout": stdout,
                    "stderr": stderr,
                    "env": self._env,
                    "timeout": self._remaining(),
                    "deadline": self._deadline,
                    "before_spawn": self._before_spawn,
                    "check": False,
                    "output_limits": ((stdout.name, STDOUT_LIMIT), (stderr.name, STDERR_LIMIT)),
                }
                if self._runner is None:
                    result = supervise.run([self._executable, *arguments], **options)
                else:
                    result = self._runner([self._executable, *arguments], **options)
            self._remaining()
            out = io.read_prefix_bytes(stdout.name, max_bytes=STDOUT_LIMIT + 1, root=output_dir)
            err = io.read_prefix_bytes(stderr.name, max_bytes=STDERR_LIMIT + 1, root=output_dir)
        return result.returncode, out, err

    def read_json(self, arguments: tuple[str, ...]) -> object:
        """Read a fixed adapter command with validated operands. Any refusal discards its output."""
        self._remaining()
        if self._calls >= REFRESH_CALLS or self._bytes >= REFRESH_BYTES:
            raise TrackerError(Reason.LIMIT_EXCEEDED)
        self._calls += 1
        try:
            code, stdout, stderr = self._capture(arguments)
        except subprocess.TimeoutExpired:
            raise TrackerError(Reason.TIMEOUT) from None
        except supervise.OversizedError:
            raise TrackerError(Reason.LIMIT_EXCEEDED) from None
        except (OSError, subprocess.SubprocessError):
            raise TrackerError(Reason.CLI_FAILED) from None
        self._bytes += len(stdout) + len(stderr)
        if len(stdout) > STDOUT_LIMIT or len(stderr) > STDERR_LIMIT or self._bytes > REFRESH_BYTES:
            raise TrackerError(Reason.LIMIT_EXCEEDED)
        return _response(code, stdout, stderr, graphql=arguments[:2] == ("api", "graphql"))
