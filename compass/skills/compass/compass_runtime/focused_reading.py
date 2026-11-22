"""Local evidence shared by the focused reading and Sessions snapshot."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from . import annotations as annotation_store
from . import (
    ci_read,
    compass_turns,
    copied_corrections,
    correction,
    drift_view,
    entry_numbers,
    levels,
    live_estimate,
    record_pages,
)
from . import io as runtime_io
from . import observer as runtime_observer
from . import project_context as runtime_project_context
from . import reading as runtime_reading

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .aggregate import Application


# Board polls can revalidate a small record with the same evidence as the focused view.
BOARD_TRANSCRIPT_MAX_BYTES = 1024 * 1024


def record_page(
    application: Any,
    matching: list[dict[str, Any]],
    harness: str,
    sid: str,
    *,
    cursor_key: bytes,
    limit: int,
    before: str | None,
) -> dict[str, Any]:
    """One page of a session's record as `/api/session-record` answers it, before `for_page`.

    Shared with the Drift view, which reads the newest page the way the page does on opening a
    session, so a message the focused context's bounded window left out is still there to cite.
    """
    result = record_pages.empty(harness, sid, "unavailable")
    index = None
    if len(matching) == 1:
        path = runtime_observer.resolve_transcript(
            application.config, application.state, harness, sid
        )
        result = record_pages.read(
            application.config,
            path or "",
            harness,
            sid,
            cursor_key=cursor_key,
            limit=limit,
            before=before,
        )
        # After the page is read, so the index reaches at least as far as the page does.
        if path and result["entries"]:
            index = entry_numbers.message_index(
                application.config, application.state, path, harness, sid
            )
    marked = compass_turns.mark(
        application.config,
        application.state,
        {"semantic": {"facts": result["entries"]}},
        matching,
    )
    marked = copied_corrections.mark(marked, matching)
    result["entries"] = marked["semantic"]["facts"]
    if index is not None:
        # Each message's fixed number (DRC-4897), so a page of any age numbers it the same way.
        result["entries"] = entry_numbers.with_message_ordinals(index, result["entries"])
    return result


def line_requests(
    entry: annotation_store.Annotation | None, facts: list[Any], row: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The page receives verified times, never untrusted stored binding digests."""
    if not entry or not entry["revisions"]:
        return []
    latest = entry["revisions"][-1]
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    own = [fact for fact in facts if isinstance(fact, dict)]
    floors = runtime_reading.line_request_floors(latest, own, harness, sid)
    lines = {
        name: {"at": at, "source_id": latest["lines"][int(name.split("_")[1]) - 1]["source_id"]}
        for name, at in floors.items()
    }
    return (
        [{"harness": harness, "sid": sid, "revision": latest["n"], "lines": lines}] if lines else []
    )


def analysis_levels(
    application: Any,
    context: dict[str, Any],
    row: dict[str, Any],
    entry: annotation_store.Annotation | None,
    floor: float | None,
    *,
    request_sources: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """The analysis-derived level of the stored reading, recomputed now and never stored.

    `levels.analysis_level` over the reading and the record as the context
    holds it: the session's tool reports, their full-scan counts and its
    unsettled later directions (items 1, 2 and 6 of
    [DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)).
    The lines it must answer are those of the revision it read, not today's;
    a revision the store no longer holds gives no level rather than a guess.
    """
    assessment = entry.get("assessment") if entry else None
    if not entry or not assessment or entry.get("not_accurate") is True:
        return []
    read = next(
        (rev for rev in entry["revisions"] if rev["n"] == assessment.get("revision_read")), None
    )
    if read is None:
        return []
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    facts = facts_of(context)
    mine = tuple(
        fact
        for fact in facts
        if isinstance(fact, dict)
        and isinstance(fact.get("source_session"), dict)
        and (fact["source_session"].get("harness"), fact["source_session"].get("sid"))
        == (harness, sid)
    )
    # The CI checks this reading stored, as the facts the press numbered them as, so a citation
    # of one resolves here and a head that has since moved does not unsettle what was read.
    mine = (*mine, *ci_read.facts(assessment.get("ci"), harness, sid))
    scan = runtime_project_context.scan_of(context, harness, sid)
    evidence = levels.Evidence(
        mine,
        scan,
        correction.unsettled_directions(row, facts, floor=floor, until=assessment.get("read_at")),
    )
    level = levels.analysis_level(
        assessment,
        evidence,
        outcome_lines=len(read["lines"]),
        lines=runtime_reading.outcome_lines(read),
        line_requests=runtime_reading.line_request_floors(read, request_sources, harness, sid)
        if read["n"] == entry["revisions"][-1]["n"]
        else {},
    )
    return [
        {
            "harness": harness,
            "sid": sid,
            "revision_read": assessment.get("revision_read"),
            "read_at": assessment.get("read_at"),
            "computed_at": application.clock(),
            "level": level.level,
            "reasons": list(level.reasons),
            "cites": list(level.cites),
        }
    ]


def request_sources(
    application: Any,
    row: Mapping[str, Any],
    facts: list[Any],
    entry: annotation_store.Annotation | None = None,
) -> list[Mapping[str, Any]]:
    """One version-checked newest and opening read, shared by this operation's consumers."""
    if entry is not None and (
        not entry["revisions"] or not runtime_reading.has_line_requests(entry["revisions"][-1])
    ):
        return []
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    path = runtime_observer.resolve_transcript(application.config, application.state, harness, sid)
    recovered = (
        runtime_project_context.transcript_user_facts(
            application.config, application.state, path, harness, sid
        )
        if path
        else []
    )
    return runtime_reading.listed_request_sources(
        [fact for fact in facts if isinstance(fact, dict)], recovered
    )


def facts_of(context: dict[str, Any]) -> list[Any]:
    semantic = context.get("semantic")
    facts = semantic.get("facts", []) if isinstance(semantic, dict) else []
    return list(facts) if isinstance(facts, list) else []


def with_message_ordinals(
    application: Any, context: dict[str, Any], focus: tuple[str, str]
) -> dict[str, Any]:
    """Number copies of the focused session's message facts, which may be cached."""
    semantic = context.get("semantic")
    if not isinstance(semantic, dict) or not isinstance(semantic.get("facts"), list):
        return context
    path = runtime_observer.resolve_transcript(application.config, application.state, *focus)
    if not path:
        return context
    index = entry_numbers.message_index(application.config, application.state, path, *focus)
    if index is None:
        return context
    facts = entry_numbers.with_message_ordinals(index, semantic["facts"])
    return {**context, "semantic": {**semantic, "facts": facts}}


def stored_work(
    application: Any,
    context: dict[str, Any],
    row: dict[str, Any],
    entry: annotation_store.Annotation | None,
) -> dict[str, Any]:
    requests = request_sources(application, row, facts_of(context), entry) if entry else []
    return {
        "line_requests": line_requests(entry, requests, row),
        "analysis_levels": analysis_levels(
            application,
            context,
            row,
            entry,
            annotation_store.direction_floor(entry, row),
            request_sources=requests,
        ),
    }


def _stored_progress(
    application: Application,
    payload: dict[str, Any],
    row: dict[str, Any],
    entry: annotation_store.Annotation,
) -> str:
    """Read the stored result on the same local record the focused view uses."""
    config, state = application.config, application.state
    harness, sid = row["harness"], row["sid"]
    rows = payload["sessions"]
    label = str(row.get("project") or "")
    project = str(row.get("project_key") or label)
    # The page opens a shared display label under the label itself. That can
    # bring in another history bucket even if the other location is quiet.
    if (
        not project
        or len(project) > config.ask_project_cap_chars
        or any(
            peer.get("project") == label and str(peer.get("project_key") or label) != project
            for peer in rows
        )
    ):
        return "withheld"
    path = runtime_observer.resolve_transcript(config, state, harness, sid)
    stamp = runtime_project_context.transcript_stamp(path) if path else None
    if not path or stamp is None or stamp[2] > BOARD_TRANSCRIPT_MAX_BYTES:
        return "withheld"
    context = runtime_project_context.collect(
        config,
        state,
        rows,
        project,
        focus=(harness, sid),
        now=payload["generated"],
        read_only=True,
    )
    if not context:
        return "withheld"
    context = copied_corrections.mark(context, rows)
    context = compass_turns.mark(config, state, context, [row])
    context = with_message_ordinals(application, context, (harness, sid))
    context["sources"]["work"].update(stored_work(application, context, row, entry))
    page = record_page(
        application, [row], harness, sid, cursor_key=b"", limit=record_pages.PAGE_SIZE, before=None
    )
    if page["state"] != "ok" or runtime_project_context.transcript_stamp(path) != stamp:
        return "withheld"
    # The focused view reads a board decoded from JSON. In this pre-serialization row,
    # annotations still hold tuples (for example, the stored criteria's citations).
    board_row: dict[str, Any] = json.loads(json.dumps(row))
    return drift_view.stored_progress(board_row, payload, context, page["entries"])


def published(
    application: Application, payload: dict[str, Any], row: dict[str, Any]
) -> dict[str, str | None]:
    """Only a current saved assessment asks the board to open any evidence."""
    return {"stored_progress": _progress_for_row(application, payload, row)}


def _progress_for_row(
    application: Application, payload: dict[str, Any], row: dict[str, Any]
) -> str | None:
    if payload.get("annotate") is not True or row["harness"] not in live_estimate.HARNESSES:
        return None
    raw = row.get("annotation_assessment")
    if not isinstance(raw, dict):
        return "withheld" if row.get("annotation_reading_refused") else None
    revision = row.get("annotation_revision")
    revision_read = raw.get("revision_read")
    if payload.get("annotate_unreadable") or row.get("annotation_not_accurate"):
        return "withheld"
    if raw.get("scope") == runtime_reading.SCOPE_WITHDRAWN:
        return "out_of_date"
    if revision is None or revision_read != revision:
        return "out_of_date" if revision is not None and revision_read is not None else "withheld"
    return _revalidate(application, payload, row, raw, revision)


def _revalidate(
    application: Application,
    payload: dict[str, Any],
    row: dict[str, Any],
    raw: dict[str, Any],
    revision: int,
) -> str:
    config, state = application.config, application.state
    identity = (row["harness"], row["sid"])
    try:
        entry = annotation_store.find(annotation_store.active(config, state), *identity)
        if (
            not entry
            or entry.get("not_accurate")
            or not entry["revisions"]
            or entry["revisions"][-1]["n"] != revision
            or entry.get("assessment") != raw
        ):
            return "withheld"
        result = _stored_progress(application, payload, row, entry)
        current = annotation_store.find(annotation_store.active(config, state), *identity)
    except Exception as exc:  # noqa: BLE001 - a failed revalidation cannot cost the board
        runtime_io.diag(
            f"Compass: stored progress could not be read ({exc.__class__.__name__}).",
            application.diagnostic_sink,
        )
        return "withheld"
    else:
        return result if current == entry else "withheld"
