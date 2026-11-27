# ruff: noqa: INP001 - launched as a script from the plugin root
"""Supply the opt-in plan summary as SessionStart context."""

from __future__ import annotations

import json
import os
import sys
from typing import Final

MAX_PAYLOAD_BYTES: Final = 1 << 20


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
        if len(raw) > MAX_PAYLOAD_BYTES:
            return 0
        event = json.loads(raw.decode("utf-8"))
        if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
            return 0
        cwd = event.get("cwd")
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            return 0
        from compass_runtime.plan import publish  # noqa: PLC0415 - after the bounded input check
        from compass_runtime.terminal_client import state_home  # noqa: PLC0415

        summary = publish.session_summary(
            state_home(os.environ), lane=os.environ.get("COMPASS_LANE"), cwd=cwd
        )
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
