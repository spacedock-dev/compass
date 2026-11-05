"""Advisory HTTP preview and closed ingress shape; neither admits work."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import annotations as annotation_store
from . import observer, reading_long_plan, reading_route, settings

if TYPE_CHECKING:
    from .aggregate import Application


def identity(harness: Any, sid: Any) -> bool:
    return all(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value) is not None
        for value in (harness, sid)
    )


def valid_ingress(payload: dict[str, Any]) -> bool:
    """Omitted mode is legacy Analyze; the only opt-in mode is long.

    Check before settings, Keep, adoption or unasked dispatch. This is shape
    validation only: the preview digest is not permission or a reservation.
    """
    if "mode" not in payload:
        return "plan_binding" not in payload
    if payload["mode"] != "long" or any(
        key in payload for key in ("consent", "ci_read", "unasked_grant")
    ):
        return False
    return (
        identity(payload.get("harness"), payload.get("sid"))
        and isinstance(payload.get("plan_binding"), str)
        and re.fullmatch(r"[0-9a-f]{64}", payload["plan_binding"]) is not None
        and type(payload.get("expected_revision")) is int
        and 0 < payload["expected_revision"] < 2**53
        and payload.get("provider") in ("claude", "codex")
        and isinstance(payload.get("destination"), str)
        and len(payload["destination"]) <= 1024
        and all(
            isinstance(payload.get(key), str) and 0 < len(payload[key]) <= 1024
            for key in ("model", "words_destination")
        )
    )


def _published(
    application: Application, harness: str, sid: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Never collect on a cache miss: preview must not read session bodies."""
    for show_all in (False, True):
        saved = application.state.snapshot.current((application.config.window_hours, show_all))
        if saved is None:
            continue
        try:
            body = json.loads(saved[1])
            rows = [
                row
                for row in body["sessions"]
                if isinstance(row, dict) and row.get("harness") == harness and row.get("sid") == sid
            ]
            policy = body.get("reading")
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            continue
        if rows:
            return (rows[0] if len(rows) == 1 else None), policy if isinstance(
                policy, dict
            ) else None
    return None, None


def describe(application: Application, harness: str, sid: str) -> dict[str, Any]:
    """Current saved intent/route/settings, advisory board allowance and native stat.

    A cold or missing row stays unknown. Only Claude's resolver is metadata
    only; other harness resolvers may read bodies and must never run here.
    Nothing freezes an endpoint or captures live execution authority.
    """
    config = application.config
    now = application.clock()
    row, policy = _published(application, harness, sid)
    source = None
    entry = None
    if row is not None:
        fresh = annotation_store.fresh(config, application.state, application.diagnostic_sink)
        if fresh.entries is not None:
            entry = annotation_store.find(fresh.entries, harness, sid)
        if harness == "claude":
            try:
                path = observer.resolve_transcript(config, application.state, harness, sid)
                info = Path(path).lstat() if path else None
                if info is not None and stat.S_ISREG(info.st_mode):
                    source = reading_long_plan.SourceEstimate(
                        harness, sid, "native-claude", info.st_size, now
                    )
            except (OSError, ValueError):
                pass
    return reading_long_plan.describe(
        row=row if row is not None else {"harness": harness, "sid": sid},
        entry=entry,
        route=reading_route.resolve(harness, config=config),
        preferences=settings.load(config),
        policy_status=policy,
        source=source,
        now=now,
        settle_sec=config.reading_settle_sec,
    )


def changed(payload: dict[str, Any], preview: dict[str, Any]) -> bool:
    route = preview["route"]
    return (
        preview["binding"] != payload["plan_binding"]
        or preview["intent"]["revision"] != payload["expected_revision"]
        or route is None
        or any(
            payload[key] != route[key]
            for key in ("provider", "model", "destination", "words_destination")
        )
    )
