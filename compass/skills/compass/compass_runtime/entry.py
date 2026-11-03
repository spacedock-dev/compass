"""What `server.py` runs: the terminal client's short operations, else the CLI.

`cli` is imported inside the function and nowhere else: it loads every collector, and a short
operation must not pay for that.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from compass_runtime import terminal_client

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if terminal_client.handles(args):
        return terminal_client.run(args)
    from compass_runtime import cli  # noqa: PLC0415

    return cli.main(args)
