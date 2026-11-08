"""Real child cleanup for tests whose assertion is not the reap deadline.

Deadline/probe-failure tests use the production clock and probe (or drive their
own clock). These fixtures keep real group observation and process reaping, but
charge only explicit poll sleeps to the cleanup clock. A descheduled ps spawn
cannot consume the unrelated assertion's entire reap budget.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import time
from typing import TYPE_CHECKING
from unittest import mock

from compass_runtime import supervise

if TYPE_CHECKING:
    from collections.abc import Iterator


class _ReapClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
        self.now += seconds


def _observe_group(pgid: int, _remaining: float) -> bool | None:
    # No timed worker: the native process completes before the logical clock
    # moves. Unknown/error states still refuse cleanup, as in production.
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pgid=,stat="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env={"LC_ALL": "C"},
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return supervise._group_state(result.stdout, pgid)


@contextlib.contextmanager
def controlled_reap() -> Iterator[None]:
    """Keep the five-second poll budget, excluding host scheduling and ps work."""
    if sys.platform == "win32":
        yield
        return
    real_finish = supervise.Group._finish

    def finish(group: supervise.Group) -> None:
        with (
            mock.patch.object(supervise, "time", _ReapClock()),
            mock.patch.object(supervise, "_group_running", _observe_group),
        ):
            real_finish(group)

    with mock.patch.object(supervise.Group, "_finish", finish):
        yield
