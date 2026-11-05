"""Private current CI acquisition through existing owners and a shared source budget.

The caller supplies live authorization/currentness and the existing job's remaining
time. CI subprocess waits count against preparation; native byte/page counters do
not count network or Git I/O. Live source revalidation runs outside the budget lock.
"""

from __future__ import annotations

import json
import math
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from . import ci_read, git_status, reading_preparation, supervise

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from .config import RuntimeConfig
    from .reading_source_collect import Collection, CurrentCiInputs

Reason = Literal[
    "",
    "not-requested",
    "source-unavailable",
    "input-unavailable",
    "current",
    "cancelled",
    "job-time",
    "prepare-time",
    "retained-bytes",
    "retained-units",
    "budget",
    "ci-read",
    "output",
    "context-error",
]


@dataclass(frozen=True)
class Result:
    """Owned input association plus an immutable owner record, never native origins.

    ci_calls/git_calls count runner invocation attempts; spawned counts observed
    supervisor callbacks. Neither counter claims a number of server requests.
    """

    inputs: CurrentCiInputs | None
    state: Literal["complete", "unavailable", "stopped"]
    reason: Reason
    ci_calls: int = 0
    git_calls: int = 0
    spawned: int = 0
    record_json: str | None = None

    def value(self) -> dict[str, Any] | None:
        """Fresh owner-shaped dict for ci_read.facts/recorded consumers."""
        if self.record_json is None:
            return None
        value = json.loads(self.record_json)
        if not isinstance(value, dict):
            raise TypeError("Invalid private CI record")
        return value


class _StopError(Exception):
    def __init__(self, reason: Reason):
        self.reason = reason


class _Read:
    def __init__(
        self,
        config: RuntimeConfig,
        collection: Collection,
        budget: reading_preparation.Budget,
        *,
        current: Callable[[], str],
        cancelled: Callable[[], bool],
        remaining_seconds: Callable[[], float],
        on_spawn: Callable[[Any], None],
        runner: Callable[..., Any],
    ) -> None:
        self.config, self.collection, self.budget = config, collection, budget
        self.current, self.cancelled = current, cancelled
        self.remaining_seconds, self.on_spawn, self.runner = remaining_seconds, on_spawn, runner
        self.stack: ExitStack | None = None
        self.keep: Callable[[Any], None] | None = None
        self.ci_calls = self.git_calls = self.spawned = 0

    def close(self) -> None:
        stack, self.stack, self.keep = self.stack, None, None
        if stack is not None:
            stack.close()

    def open(self) -> None:
        stack = ExitStack()
        stage = stack.enter_context(self.budget.stage())
        self.stack, self.keep = stack, stage.keep

    def live(self, timeout: float = 0.0) -> None:
        """A gate may itself revalidate source and meter the shared account."""
        self.close()
        if self.cancelled():
            raise _StopError("cancelled")
        if self.current() != "":
            raise _StopError("current")
        if self.cancelled():
            raise _StopError("cancelled")
        remaining = self.remaining_seconds()
        if (
            type(remaining) not in (int, float)
            or not math.isfinite(remaining)
            or remaining <= 0
            or remaining < timeout
        ):
            raise _StopError("job-time")
        left = (self.budget.account.limits.prepare_ms - self.budget.account.usage.prepare_ms) / 1000
        if left <= 0 or left < timeout:
            raise _StopError("prepare-time")

    def spawned_group(self, group: Any) -> None:
        self.spawned += 1
        self.on_spawn(group)

    def ci(self, command: Sequence[str], **options: Any) -> Any:
        self.live(ci_read.TIMEOUT_SEC)
        self.open()
        # Wrapping supervise.run hides its identity from ci_read._run. Preserve
        # that owner's active file-output enforcement explicitly.
        options["output_limits"] = (
            (options["stdout"].name, ci_read.OUTPUT_LIMIT_BYTES),
            (options["stderr"].name, ci_read.STDERR_LIMIT_BYTES),
        )
        options["on_spawn"] = self.spawned_group
        self.ci_calls += 1
        return self.invoke(command, options)

    def git(self, command: Sequence[str], **options: Any) -> Any:
        self.live(self.config.git_probe_timeout_sec)
        self.open()
        # is_ancestor consumes only the exit code. Keep its owner argv/env/cwd,
        # but supervise the group and discard output instead of capturing pipes.
        options.pop("capture_output", None)
        options.pop("stdin", None)
        options.update(
            input=b"",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            on_spawn=self.spawned_group,
        )
        self.git_calls += 1
        return self.invoke(command, options)

    def invoke(self, command: Sequence[str], options: dict[str, Any]) -> Any:
        try:
            return self.runner(command, **options)
        except (supervise.ClosedError, supervise.UnstoppedError) as error:
            # These subclass errors the CI/Git owners classify as read failures.
            # A stopped process supervisor instead forbids paid continuation.
            raise _StopError("current") from error

    def result(
        self,
        state: Literal["complete", "unavailable", "stopped"],
        reason: Reason,
        record_json: str | None = None,
    ) -> Result:
        return Result(
            self.collection.current_ci,
            state,
            reason,
            self.ci_calls,
            self.git_calls,
            self.spawned,
            record_json,
        )

    def read(self, now: float, environ: Mapping[str, str] | None) -> Result:
        self.live()
        snapshot, inputs = self.collection.snapshot, self.collection.current_ci
        if (
            self.collection.reason
            or not self.collection.source_verified
            or snapshot is None
            or self.budget.account is not snapshot.account
        ):
            return self.result("stopped", "source-unavailable")
        if inputs is None:
            return self.result("unavailable", "not-requested")
        self.open()
        binding = inputs.binding
        if binding != ci_read.bind(inputs.goal_texts, inputs.links, inputs.pushes, inputs.remote):
            raise _StopError("source-unavailable")
        if (
            binding is not None
            and ci_read.validate(
                ci_read.refused(
                    binding,
                    ci_read.ERROR_NO_COMMIT,
                    session_head=inputs.session_head,
                    caution=inputs.caution,
                    now=now,
                )
            )
            is None
        ):
            raise _StopError("output")
        raw = None
        if inputs.state != "ready" or binding is None:
            if binding is not None:
                raw = ci_read.refused(
                    binding,
                    ci_read.ERROR_NO_FOLDER
                    if inputs.state == "no-folder"
                    else ci_read.ERROR_NO_COMMIT,
                    session_head=inputs.session_head,
                    caution=inputs.caution,
                    now=now,
                )
            reason: Reason = "input-unavailable"
        else:
            raw = ci_read.read(
                binding,
                session_head=inputs.session_head,
                caution=inputs.caution,
                now=now,
                environ=environ,
                runner=self.ci,
                on_spawn=self.spawned_group,
                clock=self.budget.clock,
                contains=lambda commit: git_status.is_ancestor(
                    inputs.folder,
                    commit,
                    inputs.session_head,
                    timeout_sec=self.config.git_probe_timeout_sec,
                    runner=self.git,
                ),
            )
            reason = "ci-read" if raw.get("error") else ""
        record = ci_read.validate(raw) if raw is not None else None
        if raw is not None and record is None:
            raise _StopError("output")
        encoded = (
            json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if record is not None
            else None
        )
        result = self.result("unavailable" if reason else "complete", reason, encoded)
        if self.keep is None:
            raise _StopError("budget")
        self.keep((raw, record, result))
        self.close()
        # A change during the last call must withdraw the result before maps.
        self.live()
        return result


def acquire(  # noqa: PLR0913 - explicit live gates and owned transport seams
    config: RuntimeConfig,
    collection: Collection,
    budget: reading_preparation.Budget,
    *,
    current: Callable[[], str],
    cancelled: Callable[[], bool],
    remaining_seconds: Callable[[], float],
    on_spawn: Callable[[Any], None],
    now: float,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = supervise.run,
) -> Result:
    """Read once, with no permission grant, retry, cache floor or fresh allowance.

    current must cover source, route, off/Pause, shutdown and generation/intent.
    Return an empty string only while those are current. remaining_seconds must
    come from the existing live job deadline. A stopped result forbids continuing
    paid map calls. Consumer copies/facts must be kept in their shared stage.
    """
    owner = _Read(
        config,
        collection,
        budget,
        current=current,
        cancelled=cancelled,
        remaining_seconds=remaining_seconds,
        on_spawn=on_spawn,
        runner=runner,
    )

    def limited(error: reading_preparation.LimitError) -> Result:
        reasons: dict[str, Reason] = {
            "prepare-time": "prepare-time",
            "retained-bytes": "retained-bytes",
            "retained-units": "retained-units",
        }
        return owner.result("stopped", reasons.get(error.reason, "budget"))

    try:
        result = owner.read(now, environ)
    except _StopError as error:
        result = owner.result("stopped", error.reason)
    except reading_preparation.LimitError as error:
        result = limited(error)
    except Exception:  # noqa: BLE001 - unknown callbacks must stop paid continuation
        result = owner.result("stopped", "context-error")
    finally:
        try:
            owner.close()
        except reading_preparation.LimitError as error:
            result = limited(error)
        except Exception:  # noqa: BLE001 - unknown callbacks must stop paid continuation
            result = owner.result("stopped", "budget")
    return result
