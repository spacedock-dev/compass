"""The live drift estimate for one Claude Code session, replayed without a model (DRC-4696).

This is the model-free level, and it still calls no model. It is the fallback the Live monitor uses:
the monitor's own Haiku check is `live_monitor`, and its level replaces this one on the page once a
check has returned.

Items 2 to 6 of
[DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn).
`levels.live_level` is the estimate; this module feeds it. It replays the session's calls through
the same tally `project_context.claude_tool_reports` publishes from, one call at a time, and asks
for the level after each of the last `LIVE_REPLAY_STEPS` calls that can move it, so the level now
is the one the published record gives and "Rose from <level> at #<n>" comes from the same record.
The replay is held in this process's memory, keyed by the parent and delegated transcript
inventory and the saved words. Nothing is written, and no model or process is started.

The route publishes the answer on the focused session's project context only (`http_api`), never
on a Sessions row, in history, or in the reading route's own context, which is what the unasked
lane reads (items 3 and 5). Whether the reader has the switch on is never sent to the server
(item 4), so this runs for the focused session whenever it has a saved intent.

It reads the same private check scan, result pairing and call order as `project_context`'s
published tally. That file is in DRC-4666's qualification digest, so edits here require a fresh
qualified run before an unqualified frozen-case result is used as evidence.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from . import correction, levels
from . import project_context as pc

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from .config import RuntimeConfig

HARNESSES = frozenset({"claude"})
# The calls whose arrival can move the level: a write, or a shell command. A
# read or a search never changes the tally; delegated launches now block its floor.
_MOVING_TOOLS = frozenset({*pc._WRITE_TOOLS, "Bash", "Agent", "Task", "Monitor"})  # noqa: SLF001
# How many of the latest moving calls the level is asked after. Each ask
# re-derives the entries from the whole tally, so an unbounded replay grew
# about cubically: 24 s for a 3,000-call transcript of targeted checks, and
# 212 s for 5,000 (review of d2854fc1, F1). A turn rarely makes more than a
# few dozen writes and shell calls, so 64 still finds a rise inside the last
# turns, and a rise older than that is withheld rather than guessed at.
LIVE_REPLAY_STEPS = 64
# One replay per session and set of words, kept in this process only. A request
# that finds all inputs unchanged reads no transcript content. A changed scan
# can reuse a stable prefix or a safely removable head and re-evaluates the
# current 64-step window. A handful of entries covers the sessions a reader
# has open; beyond that the oldest goes.
_CACHE_ENTRIES = 16
# Two normalized tallies may be held per entry. Bound the aggregate source
# window represented by the LRU as well as its session count.
_CACHE_SCAN_BYTES = 32 * 1024 * 1024


@dataclasses.dataclass
class _Replayed:
    signature: tuple[Any, ...]
    # Each moving call read, in order, with its result or None. A call whose
    # mark differs, including a result that arrived since, changes its own
    # step and every one after it; the steps before it stand.
    marks: list[bytes]
    context: tuple[Any, ...]
    # The level after each moving call by its position, and -1 for before the first.
    steps: dict[int, str]
    # The level, its reasons and where it rose; and the whole answer last published.
    found: dict[str, Any]
    published: dict[str, Any] = dataclasses.field(default_factory=dict)
    # A normalized tally before the last 64 moving calls. It holds no raw
    # paired results or output tails; a shifted scan can delete safe old head
    # calls from it and replay only the current window.
    checkpoint: pc._ToolReportTally | None = None
    safe_head: list[tuple[str, int] | None] = dataclasses.field(default_factory=list)
    final_tally: pc._ToolReportTally | None = None
    scanned_bytes: int = 0


_cache: OrderedDict[tuple[Any, ...], _Replayed] = OrderedDict()
_cache_lock = threading.Lock()
_flights: dict[tuple[Any, ...], threading.Event] = {}


def saved_intent(row: Mapping[str, Any]) -> levels.Intent:
    """The saved words on the row, or an unsaved intent where no revision holds any."""
    revision = row.get("annotation_revision")
    goal = str(row.get("annotation_goal") or "")
    lines = tuple(
        text for k in range(1, 7) if (text := str(row.get(f"annotation_line_{k}") or "")).strip()
    )
    saved = (
        isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision > 0
        and bool(goal.strip() or lines)
    )
    return levels.Intent(saved=saved, goal=goal, lines=lines)


def _published(
    tally: pc._ToolReportTally,
    sid: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The tally's entries and scan as `claude_tool_reports` would publish them now.

    `entries` adds to the scan every time it is called, so the whole scan is put
    back afterwards rather than a list of the counters it touches today, which
    went stale silently when one was missed (review of d2854fc1, F2).
    """
    kept = dict(tally.scan)
    rows = tally.entries(sid)
    scan = dict(tally.scan)
    tally.scan.clear()
    tally.scan.update(kept)
    return rows, scan


def _fact(row: Mapping[str, Any]) -> dict[str, Any]:
    return pc._semantic_fact_from_event(dict(row), str(row["kind"]), "tool_report", "")  # noqa: SLF001


def _live_signature(config: RuntimeConfig, transcript_path: str) -> tuple[Any, ...] | None:
    """Metadata identity for every input the shared live check scan may admit."""
    paths = [transcript_path, *pc._subagent_transcripts(transcript_path)]  # noqa: SLF001
    found: list[tuple[Any, ...]] = []
    try:
        for path in paths:
            stat = os.stat(path, follow_symlinks=path == transcript_path)
            found.append(
                (path, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            )
    except OSError:
        return None
    return (config.turn_scan_max_bytes, config.reverse_chunk_bytes, *found)


def for_session(
    config: RuntimeConfig,
    row: Mapping[str, Any],
    transcript_path: str,
    facts: Iterable[Any],
    *,
    floor: float | None,
    now: float,
) -> dict[str, Any]:
    """The live level for one session now, and where it last rose from.

    `facts` is the session's published record, read for its later directions
    only; `floor` is `annotations.direction_floor` for the saved words.
    """
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    intent = saved_intent(row)
    revision = row.get("annotation_revision")
    answer: dict[str, Any] = {
        "harness": harness,
        "sid": sid,
        "revision": revision if isinstance(revision, int) and not isinstance(revision, bool) else 0,
        "computed_at": now,
        "rose_from": None,
        "rose_at": None,
    }
    if not intent.saved:
        # Over an unsaved draft there is no live level (item 2), and nothing is read.
        level = levels.live_level(levels.Evidence((), {}, 0), intent)
        return {**answer, "level": level.level, "reasons": list(level.reasons)}
    unsettled = correction.unsettled_directions(row, facts, floor=floor)
    goal_texts = pc.goal_texts_of(row)
    key = (
        transcript_path,
        harness,
        sid,
        answer["revision"],
        intent.goal,
        intent.lines,
        unsettled,
        goal_texts,
    )
    while True:
        signature = _live_signature(config, transcript_path)
        if signature is None:
            uncertain = _replay(
                config,
                transcript_path,
                sid,
                intent,
                unsettled,
                None,
                force_incomplete=True,
                goal_texts=goal_texts,
            )
            return {**answer, **uncertain.found}
        with _cache_lock:
            previous = _cache.get(key)
            if previous is not None and previous.signature == signature:
                _cache.move_to_end(key)
                return dict(previous.published)
            flight = _flights.get(key)
            leader = flight is None
            if flight is None:
                flight = threading.Event()
                _flights[key] = flight
        if not leader:
            flight.wait()
            continue
        try:
            replayed = _replay(
                config, transcript_path, sid, intent, unsettled, previous, goal_texts=goal_texts
            )
            after = _live_signature(config, transcript_path)
            if after != signature:
                # A moving file cannot support a complete cached assurance.
                uncertain = _replay(
                    config,
                    transcript_path,
                    sid,
                    intent,
                    unsettled,
                    None,
                    force_incomplete=True,
                    goal_texts=goal_texts,
                )
                return {**answer, **uncertain.found}
            replayed.published = {**answer, **replayed.found}
            replayed.signature = signature
            with _cache_lock:
                _cache[key] = replayed
                _cache.move_to_end(key)
                while (
                    len(_cache) > _CACHE_ENTRIES
                    or sum(item.scanned_bytes for item in _cache.values()) > _CACHE_SCAN_BYTES
                ):
                    _cache.popitem(last=False)
            return dict(replayed.published)
        finally:
            with _cache_lock:
                _flights.pop(key, None)
                flight.set()


def _reusable(previous: _Replayed | None, marks: list[bytes]) -> int:
    """How many leading steps of `previous` still stand for the calls read now."""
    valid = 0
    for old, new in zip(previous.marks if previous is not None else [], marks, strict=False):
        if old != new:
            break
        valid += 1
    return valid


def _checkpoint(tally: pc._ToolReportTally) -> pc._ToolReportTally:
    """Copy only normalized check state; never retain raw results or tails."""
    saved = pc._ToolReportTally(  # noqa: SLF001
        {}, tally.session_dir, tally.declared, tally.ci_binding
    )
    saved._hash_identities = True  # noqa: SLF001
    saved.runs = {
        _cached_identity(identity, tally): [{**run, "tail": ""} for run in history]
        for identity, history in tally.runs.items()
    }
    saved.commands = {
        _cached_identity(identity, tally): [{**run, "tail": ""} for run in history]
        for identity, history in tally.commands.items()
    }
    saved.writes = {path: dict(write) for path, write in tally.writes.items()}
    saved.launches = {key: dict(row) for key, row in tally.launches.items()}
    saved.completed_launch_calls = dict(tally.completed_launch_calls)
    saved.write_calls = list(tally.write_calls)
    saved.shell_seq = tally.shell_seq
    saved.changing_seqs = list(tally.changing_seqs)
    saved.reads_from = tally.reads_from
    saved.named_unread = tally.named_unread
    saved.parent_failed = tally.parent_failed
    saved.orphan_unread = tally.orphan_unread
    saved.scan = dict(tally.scan)
    saved._entry_cache = {  # noqa: SLF001
        _cached_identity(identity, tally): dict(entry)
        for identity, entry in tally._entry_cache.items()  # noqa: SLF001
        if not identity.startswith("command:")
    }
    return saved


def _cached_identity(identity: str, tally: pc._ToolReportTally) -> str:
    if tally._hash_identities:  # noqa: SLF001
        return identity
    return hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()


def _safe_head_effect(
    tally: pc._ToolReportTally,
    before: tuple[dict[str, Any], int, int, int],
    name: str,
) -> tuple[str, int] | None:
    """A head call whose entire contribution can be removed from a checkpoint."""
    before_scan, writes, write_calls, changing_seqs = before
    if name != "Bash" or len(tally._last_added_runs) != 1:  # noqa: SLF001
        return None
    identity, run = tally._last_added_runs[0]  # noqa: SLF001
    if (
        run["result"] != "passed"
        or run["background"]
        or run["fixes"]
        or run["changes_later_in_call"]
        # Redirects and fixers affect later passes even if `entries` has not
        # yet copied their effects into scan counters.
        or len(tally.writes) != writes
        or len(tally.write_calls) != write_calls
        or len(tally.changing_seqs) != changing_seqs
        or tally.scan["shell_calls"] != before_scan["shell_calls"] + 1
        or tally.scan["check_runs"] != before_scan["check_runs"] + 1
    ):
        return None
    if any(
        tally.scan[key] != value
        for key, value in before_scan.items()
        if key not in {"shell_calls", "check_runs"}
    ):
        return None
    return _cached_identity(identity, tally), run["seq"]


def _head_state(tally: pc._ToolReportTally) -> tuple[dict[str, Any], int, int, int]:
    return (dict(tally.scan), len(tally.writes), len(tally.write_calls), len(tally.changing_seqs))


def _suffix_offset(old: list[bytes], new: list[bytes]) -> int | None:
    matches = [
        offset
        for offset, mark in enumerate(old)
        if new
        and mark == new[0]
        and len(new) >= len(old) - offset
        and new[: len(old) - offset] == old[offset:]
    ]
    return matches[0] if len(matches) == 1 else None


def _drop_safe_head(tally: pc._ToolReportTally, effects: list[tuple[str, int] | None]) -> bool:
    for effect in effects:
        if effect is None:
            return False
        identity, seq = effect
        history = tally.runs.get(identity)
        if history is None:
            return False
        kept = [run for run in history if run["seq"] != seq]
        if len(kept) != len(history) - 1:
            return False
        if kept:
            # The identity's first surviving run would move behind other
            # identities in a fresh scan. Keeping its dictionary slot changes
            # stable ordering at the twelve-entry listing boundary.
            return False
        del tally.runs[identity]
        tally._entry_cache.pop(identity, None)  # noqa: SLF001
        tally.scan["shell_calls"] -= 1
        tally.scan["check_runs"] -= 1
    return True


def _shifted_checkpoint(
    previous: _Replayed | None,
    marks: list[bytes],
    context: tuple[Any, ...],
    results: dict[str, Any],
    *,
    unread: int,
) -> tuple[pc._ToolReportTally, int, list[tuple[str, int] | None]] | None:
    """Reuse a checkpoint only for an exact old suffix plus a new tail."""
    if previous is None or previous.checkpoint is None or not marks:
        return None
    # A moving child inventory, cwd or refusal state changes the meaning of
    # the baseline. A new horizon alone is safe after every cached entry is
    # invalidated: the last 64 levels are then evaluated against it afresh.
    if previous.context[:2] + previous.context[3:] != context[:2] + context[3:]:
        return None
    offset = _suffix_offset(previous.marks, marks)
    if offset is None or offset > len(previous.safe_head):
        return None
    tally = _checkpoint(previous.checkpoint)
    if not _drop_safe_head(tally, previous.safe_head[:offset]):
        return None
    if previous.context[2] != context[2]:
        tally._entry_cache.clear()  # noqa: SLF001
    tally.reads_from = context[2]
    if context[2] is None:
        tally.scan.pop("reads_from", None)
    else:
        tally.scan["reads_from"] = context[2]
    tally.scan["subagent_transcripts_unread"] = unread
    tally.results = results
    return tally, len(previous.safe_head) - offset, previous.safe_head[offset:].copy()


def _found_from_steps(
    current: levels.Level,
    steps: dict[int, str],
    rows: list[dict[str, Any]],
    calls: list[tuple[float, str, str, str, dict[str, Any], str]],
    first: int,
) -> dict[str, Any]:
    window = [steps[p] for p in range(first - 1, len(calls))]
    rose = levels.rose_from(window)
    found: dict[str, Any] = {
        "level": current.level,
        "reasons": list(current.reasons),
        "cites": list(current.cites),
    }
    if rose is not None:
        call = calls[first - 1 + rose[1]]
        # A call id can collide across streams, and a Bash call can publish
        # both a check and a redirect write. Only cite a unique row belonging
        # to this exact call in the final list; otherwise withhold the rise.
        subject = "check" if call[3] == "Bash" else "write"
        mine = [
            row
            for row in rows
            if row.get("record_id") == call[2]
            and row.get("at") == call[0]
            and row.get("worker_kind", "") == (pc.SUBAGENT_WORKER if call[5] else "")
            and row.get("subject") == subject
        ]
        if len(mine) == 1:
            found.update(rose_from=rose[0], rose_at=_fact(mine[0])["fact_id"])
    return found


def _prefix_replay(  # noqa: PLR0913, PLR0917
    previous: _Replayed | None,
    calls: list[tuple[float, str, str, str, dict[str, Any], str]],
    marks: list[bytes],
    context: tuple[Any, ...],
    results: dict[str, Any],
    sid: str,
    intent: levels.Intent,
    unsettled: int,
    scanned_bytes: int,
) -> _Replayed | None:
    """Append to an unchanged ordered window from normalized tally state."""
    if (
        previous is None
        or previous.final_tally is None
        or previous.checkpoint is None
        or previous.context != context
        or len(marks) <= len(previous.marks)
        or marks[: len(previous.marks)] != previous.marks
    ):
        return None
    first = max(0, len(calls) - LIVE_REPLAY_STEPS)
    if first > len(previous.marks):
        return None
    checkpoint = _checkpoint(previous.checkpoint)
    checkpoint.results = results
    safe_head = previous.safe_head.copy()
    for position in range(len(safe_head), first):
        before = _head_state(checkpoint)
        checkpoint.add(*calls[position])
        safe_head.append(_safe_head_effect(checkpoint, before, calls[position][3]))
    next_checkpoint = _checkpoint(checkpoint)
    tally = _checkpoint(previous.final_tally)
    tally.results = results
    steps = {
        p: value for p, value in previous.steps.items() if first - 1 <= p < len(previous.marks)
    }
    rows: list[dict[str, Any]] = []
    current: levels.Level | None = None
    cwd = str(context[0])
    for position in range(len(previous.marks), len(calls)):
        tally.add(*calls[position])
        rows, scan = _published(tally, sid)
        facts = tuple(_fact(row) for row in rows)
        current = levels.live_level(levels.Evidence(facts, scan, unsettled, cwd), intent)
        steps[position] = current.level
    if current is None:
        return None
    return _Replayed(
        (),
        marks,
        context,
        steps,
        _found_from_steps(current, steps, rows, calls, first),
        checkpoint=next_checkpoint,
        safe_head=safe_head,
        final_tally=_checkpoint(tally),
        scanned_bytes=scanned_bytes,
    )


def _new_tally(
    scan: pc._CheckScan, results: dict[str, Any], *, force_incomplete: bool
) -> pc._ToolReportTally:
    tally = pc._ToolReportTally(  # noqa: SLF001
        results, scan.session_dir, scan.declared, scan.ci_binding
    )
    tally.completed_launch_calls = pc._stream_completed_background_calls(scan.parent, scan.children)  # noqa: SLF001
    tally.reads_from = scan.horizon
    tally.scan["last_user_at"] = pc._last_person_at(scan.parent)  # noqa: SLF001
    tally.named_unread = scan.named_unread
    tally.parent_failed = scan.parent_failed or force_incomplete
    tally.orphan_unread = scan.orphan_unread
    tally.scan.update(
        subagent_transcripts=len(scan.children), subagent_transcripts_unread=scan.unread
    )
    if scan.horizon is not None:
        tally.scan["reads_from"] = scan.horizon
    return tally


def _replay_seed(
    scan: pc._CheckScan,
    results: dict[str, Any],
    previous: _Replayed | None,
    marks: list[bytes],
    context: tuple[Any, ...],
    first: int,
    *,
    force_incomplete: bool,
) -> tuple[pc._ToolReportTally, int, list[tuple[str, int] | None], bool]:
    shifted = _shifted_checkpoint(previous, marks, context, results, unread=scan.unread)
    if shifted is not None and shifted[1] <= first:
        tally, start, safe_head = shifted
        return tally, start, safe_head, True
    return _new_tally(scan, results, force_incomplete=force_incomplete), 0, [], False


def _replay(
    config: RuntimeConfig,
    transcript_path: str,
    sid: str,
    intent: levels.Intent,
    unsettled: int,
    previous: _Replayed | None,
    *,
    force_incomplete: bool = False,
    goal_texts: Sequence[str] = (),
) -> _Replayed:
    """The level now and where it rose, over the last `LIVE_REPLAY_STEPS` moving calls."""
    scan = pc._live_check_scan(config, transcript_path, goal_texts=goal_texts)  # noqa: SLF001
    cwd = scan.session_dir
    results = pc._merged_check_results(scan.parent, scan.children)  # noqa: SLF001
    context = (
        cwd,
        scan.unread,
        scan.horizon,
        scan.named_unread,
        scan.parent_failed or force_incomplete,
        tuple(sorted(pc._stream_completed_background_calls(scan.parent, scan.children).items())),  # noqa: SLF001
        scan.orphan_unread,
        len(scan.children),
        pc._last_person_at(scan.parent),  # noqa: SLF001 - invalidate a turn without new tools
        # A replayed call keeps the class it was given, so a change in which scripts are
        # declared checks starts the replay over.
        None
        if scan.declared is None
        else (
            scan.declared.toplevel,
            scan.declared.commit,
            tuple(sorted(scan.declared.files)),
            tuple(sorted(scan.declared.listed)),
        ),
    )
    calls = [
        call
        for call in pc._merged_check_calls(scan.parent, scan.children)  # noqa: SLF001
        if call[3] in _MOVING_TOOLS
    ]
    # Check rows keep parent-first result pairing; launches use the call's
    # own stream. A late result in either view invalidates its replay prefix.
    found_results = [
        (
            results.get(call[2]),
            results.get(pc._launch_record_id(call[2], call[5] or "parent")),  # noqa: SLF001
        )
        for call in calls
    ]
    marks = [
        hashlib.sha256(
            repr(
                (call, tuple(None if got is None else (got.at, got.block) for got in paired))
            ).encode("utf-8", "replace")
        ).digest()
        for call, paired in zip(calls, found_results, strict=True)
    ]
    valid = (
        _reusable(previous, marks) if previous is not None and previous.context == context else 0
    )
    if (
        previous is not None
        and previous.context == context
        and valid == len(marks) == len(previous.marks)
    ):
        # No new moving call and no late result: the tally is as it was.
        return dataclasses.replace(
            previous, found=dict(previous.found), scanned_bytes=scan.budget.spent
        )
    prefix = _prefix_replay(
        previous, calls, marks, context, results, sid, intent, unsettled, scan.budget.spent
    )
    if prefix is not None:
        return prefix
    first = max(0, len(calls) - LIVE_REPLAY_STEPS)
    tally, start_position, safe_head, shifted = _replay_seed(
        scan, results, previous, marks, context, first, force_incomplete=force_incomplete
    )
    # A checkpoint carries the binding of the scan it came from, whose records are read once.
    tally.ci_binding = scan.ci_binding
    kept = previous.steps if previous is not None and valid and not shifted else {}
    # The last call's step is always asked afresh, because `current` is whatever the
    # loop asked last: kept from a longer transcript that lost its tail, it left the
    # level of an older call published (review of d1cfa929, V1).
    steps = {p: level for p, level in kept.items() if first - 1 <= p < min(valid, len(calls) - 1)}
    rows: list[dict[str, Any]] = []

    def level_now(position: int) -> levels.Level:
        nonlocal rows
        rows, scan = _published(tally, sid)
        now_facts = tuple(_fact(r) for r in rows)
        found = levels.live_level(levels.Evidence(now_facts, scan, unsettled, cwd), intent)
        steps[position] = found.level
        return found

    # The first step is the level before the window, so a run of the current
    # level that reaches back past it reads as no rise (`rose_from`'s start 0).
    current = level_now(-1) if first == 0 and -1 not in steps else None
    checkpoint = _checkpoint(tally) if first == 0 else None
    if shifted and start_position == first and first > 0:
        current = level_now(first - 1)
        checkpoint = _checkpoint(tally)
    for position in range(start_position, len(calls)):
        call = calls[position]
        before = _head_state(tally) if position < first else None
        tally.add(*call)
        if before is not None:
            safe_head.append(_safe_head_effect(tally, before, call[3]))
        if position >= first - 1 and position not in steps:
            current = level_now(position)
        if position == first - 1:
            checkpoint = _checkpoint(tally)
    if current is None:
        # Not reached: the last moving call is always read afresh here. Typed only.
        current = level_now(-1)
    found = _found_from_steps(current, steps, rows, calls, first)
    return _Replayed(
        (),
        marks,
        context,
        steps,
        found,
        checkpoint=checkpoint,
        safe_head=safe_head,
        final_tally=_checkpoint(tally),
        scanned_bytes=scan.budget.spent,
    )
