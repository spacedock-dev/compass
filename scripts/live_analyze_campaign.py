"""Instrumented production-server launch for the reviewed live Analyze study.

This wraps the real restricted Claude executor; it does not drive another CLI.
The UI/HTTP consent route stays unchanged. Successful transport remains pending
until native live evidence is classified and reviewed outside the server. This
instrumentation is not a process/network trace or a pristine-main walkthrough.
"""

# ruff: noqa: INP001 - operator scripts intentionally have no package root
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import abstention_ledger
import analyze_campaign
import score_abstention


class LiveTransport:
    """Reserve immediately before the actual executor, never on a declined UI press."""

    def __init__(self, observer: Any, *, verified: Any, retry_slot: str = "") -> None:
        self.observer = observer
        self.inner = observer.claude_exec
        self.source = Path(observer.__file__).parent
        self.retry_slot = retry_slot
        self.campaign = analyze_campaign.Campaign()
        self.verified = verified
        self.pinned_binary = score_abstention.PinnedClaude(verified.path, verified.identity)

    def __call__(  # noqa: PLR0913 - must preserve the production executor signature
        self,
        config: Any,
        prompt: str,
        *,
        output_cap_bytes: int,
        on_spawn: Any = None,
        runner: Any = None,
        binary_resolver: Any = None,
        on_diagnostic: Any = None,
        system_prompt: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str, str]:
        from compass_runtime import supervise  # noqa: PLC0415 - exact production default seam

        # The reading model passes its own failure sink since 2026-10-20. It is never forwarded:
        # the campaign keeps its own receipts, so its calls write no stderr file and a failure
        # reads as the unlabelled one.
        del on_diagnostic
        if (
            runner not in (None, supervise.run)
            or binary_resolver not in (None, shutil.which)
            # Only the reading's own call reaches this wrapper. A summary call names its own
            # prompt and timeout, and the Analyze campaign must never carry one.
            or system_prompt is not None
            or timeout is not None
        ):
            raise abstention_ledger.LedgerError("the live wrapper refuses a substituted executor")
        if self.observer.claude_exec is not self:
            raise abstention_ledger.LedgerError(
                "the live production transport seam is not installed"
            )
        if not self.pinned_binary("claude"):
            raise abstention_ledger.LedgerError("the verified live binary changed before reserve")
        producer = analyze_campaign.verified_transport_binding(
            config, self.verified, self.observer, claude_executor=self.inner
        )
        source = analyze_campaign.runtime_source_digest(self.source)
        request = analyze_campaign.request_digest(prompt, producer, source, output_cap_bytes)
        slot = self.retry_slot or self.campaign.request_slot("live", request)
        charge = self.campaign.reserve("live", slot, request, retry=bool(self.retry_slot))
        self.retry_slot = ""
        raw, status = self.inner(
            config,
            prompt,
            output_cap_bytes=output_cap_bytes,
            on_spawn=on_spawn,
            runner=supervise.run,
            binary_resolver=self.pinned_binary,
        )
        if status != "ok":
            self.campaign.settle(charge, "unusable")
        return raw, status


def _refuse_unmetered_codex(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
    """The Claude-only live allowance grants no unmetered alternate executor."""
    raise abstention_ledger.LedgerError("the live campaign refuses unmetered Codex calls")


def main(argv: list[str] | None = None) -> int:
    """Launch the shipped server with guarded Claude calls and no alternate executor."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compass/skills/compass"))
    from compass_runtime import cli, observer  # noqa: PLC0415 - runtime path installed here

    args = list(sys.argv[1:] if argv is None else argv)
    retry = ""
    if len(args) >= 2 and args[0] == "--retry-slot":
        retry = args.pop(1)
        args.pop(0)
    # The shipped argparse parser also accepts these unambiguous abbreviations.
    if any(
        len(option := arg.split("=", 1)[0]) >= 4 and "--daemon".startswith(option) for arg in args
    ):
        raise abstention_ledger.LedgerError(
            "the instrumented server must stay in the pinned foreground process"
        )
    actual = observer.claude_exec
    actual_codex = observer.codex_exec
    with score_abstention.verify_claude_binary() as verified:
        observer.claude_exec = LiveTransport(observer, verified=verified, retry_slot=retry)
        observer.codex_exec = _refuse_unmetered_codex
        try:
            return cli.main(args)
        finally:
            observer.claude_exec = actual
            observer.codex_exec = actual_codex


if __name__ == "__main__":
    raise SystemExit(main())
