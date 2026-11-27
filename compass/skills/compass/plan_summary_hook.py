# ruff: noqa: INP001 - launched as a script from the plugin root
"""Supply the opt-in plan summary as SessionStart context."""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_PAYLOAD_BYTES: Final = 1 << 20
# The plan settings file's name (`plan.settings.FILENAME`), checked before any plan module is
# imported: with the summary never configured, a session start costs one stat.
SETTINGS_FILENAME: Final = "compass-plan.json"


class _RefusedError(ValueError):
    pass


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    event: dict[str, object] = {}
    for key, value in pairs:
        if key in event:
            raise _RefusedError
        event[key] = value
    return event


def _constant(_text: str) -> object:
    raise _RefusedError


def state_home(environ: Mapping[str, str]) -> str:
    """`terminal_client.state_home`, without importing it before the settings check."""
    override = environ.get("COMPASS_HOME")
    if override and override.strip():
        return override
    return os.path.join(os.path.expanduser("~"), ".compass")


def _selection(event: object) -> tuple[str | None, str | None] | None:
    """The explicit lane and the working folder, or None when the event must get nothing."""
    if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
        return None
    cwd = event.get("cwd")
    if cwd is not None:
        if not isinstance(cwd, str):
            return None
        cwd.encode("utf-8")  # A lone surrogate refuses the whole event.
    lane = os.environ.get("COMPASS_LANE")
    if lane is not None:
        # An explicit lane needs no folder.
        return lane, None
    if cwd is None or not os.path.isabs(cwd):
        return None
    return None, cwd


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
        if len(raw) > MAX_PAYLOAD_BYTES:
            return 0
        event = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
        selected = _selection(event)
        home = state_home(os.environ)
        if selected is None or not os.path.lexists(
            os.path.join(os.path.abspath(home), SETTINGS_FILENAME)
        ):
            return 0
        from compass_runtime.plan import publish  # noqa: PLC0415 - after the cheap checks

        lane, cwd = selected
        summary = publish.session_summary(home, lane=lane, cwd=cwd)
        if summary:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": summary,
                        }
                    }
                )
            )
    except Exception:  # noqa: BLE001 - the harness must carry on without context on any error.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
