"""Generic incremental turn scanning and turn display data."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from . import io as runtime_io
from . import records, sessions

if TYPE_CHECKING:
    from .config import RuntimeConfig
    from .state import RuntimeState


def _clear_error_run(st: dict[str, Any]) -> None:
    """Forget the failure run. Called at every turn boundary, and at the
    mid-turn quiet gap that re-anchors the clock: a run of failures split by
    five minutes of silence is a session waiting on a person, not a loop, which
    is the only thing this count is for."""
    st["err_run"] = 0
    st["err_peak"] = 0
    st["err_tool"] = None


def _apply_tool_outcome(st: dict[str, Any], record: Any, harness: str) -> None:
    """Track the run of consecutive failed tool calls inside this turn."""
    calls, results = records.tool_outcome(record, harness, sessions.TOOL_NAME_CAP_CHARS)
    if calls:
        # Replace rather than merge. Claude writes a batch's results before the
        # next assistant record, so the batch just issued is the only one whose
        # ids can still be looked up — which bounds this map to one batch by
        # construction, with no cap and no eviction rule to get wrong.
        st["tool_names"] = calls
    for tool_id, failed in results:
        if not failed:
            st["ok_total"] += 1
            st["err_run"] = 0
            continue
        st["err_total"] += 1
        st["err_run"] += 1
        # Every failure, not just one that sets a new peak. The page says "most
        # recently", and naming it only at the peak made that false whenever the
        # failures after the peak used a different tool: three Bash failures, a
        # success, three Read failures published "most recently Bash".
        st["err_tool"] = st["tool_names"].get(tool_id)
        # The peak, not the live run, is what the turn publishes.
        st["err_peak"] = max(st["err_peak"], st["err_run"])


def _apply_usage(st: dict[str, Any], value: int | None) -> None:
    """Add one measured usage reading where the scan covers its whole range."""
    if value is None:
        return
    if st["scanned_from_zero"]:
        st["session_output_tokens"] = (st["session_output_tokens"] or 0) + value
    if st["turn_complete"]:
        st["turn_output_tokens"] = (st["turn_output_tokens"] or 0) + value


def _apply_turn_record(
    config: RuntimeConfig,
    st: dict[str, Any],
    record: Any,
    harness: str,
) -> None:
    """Apply one chronological transcript record to incremental turn state."""
    usage = records.usage_signal(record, harness)
    model = records.model_signal(record, harness, sessions.MODEL_CAP_CHARS)
    if model:
        # Overwrite on every hit, so the last declaration in file order wins.
        # That is the model in current use and the whole of what is published:
        # no sort, no comparison against the previous value, and no claim about
        # whether the session ever changed model.
        #
        # Read before the timestamp guard below, because a model is a fact
        # about the session rather than about a moment in it, and a record
        # arriving without a usable stamp should not cost the reading.
        st["model"] = model
    ep = records.parse_ts(record.get("timestamp") or "")
    if not ep:
        # Usage is ordered by the file rather than by wall-clock arithmetic, so
        # a malformed timestamp does not make an otherwise measured count vanish.
        _apply_usage(st, usage)
        return
    if st["first_ts"] is None:
        st["first_ts"] = ep
    # A quiet stretch longer than the gap-reset window inside a turn means the
    # agent was not generating (permission wait, AskUserQuestion, sleep).
    # Bank the active segment and restart the clock at the post-gap event so
    # "elapsed" reflects work, not waiting.
    if st["turn_start"] and st["prev_ts"] and ep - st["prev_ts"] > config.turn_gap_reset_sec:
        if st["prev_ts"] > st["turn_start"]:
            st["durations"].append(st["prev_ts"] - st["turn_start"])
        st["turn_start"] = ep
        st["last_start"] = ep
        _clear_error_run(st)
    sig = records._turn_signal(record, harness)  # noqa: SLF001
    if sig:
        kind, override = sig
        if kind == "end":
            if st["turn_start"] and ep > st["turn_start"]:
                st["durations"].append(ep - st["turn_start"])
            st["turn_start"] = None
        else:
            if (
                kind == "prompt"
                and st["turn_start"]
                and st["prev_ts"]
                and st["prev_ts"] > st["turn_start"]
            ):
                st["durations"].append(st["prev_ts"] - st["turn_start"])
            start = records.norm_epoch(override) or ep
            st["turn_start"] = start
            st["last_start"] = start
            # A prompt/start is the completeness boundary for the turn total.
            # Quiet-gap re-anchoring above is deliberately not: it changes the
            # duration clock but does not begin a new human turn.
            st["turn_output_tokens"] = None
            st["turn_complete"] = True
            # The totals reset HERE and not in `_clear_error_run`, because that
            # is also called at the quiet gap, and a gap re-anchors the clock
            # without beginning a new request. Zeroing `ok_total` there let a
            # permission wait manufacture "none succeeded" about a request whose
            # calls had succeeded before the wait: five successes, a six-minute
            # pause, three failures, and the page said nothing had worked.
            st["err_total"] = 0
            st["ok_total"] = 0
        _clear_error_run(st)
    # After the boundary reset, so a reading on the same record belongs to the
    # turn that record opens rather than to the one it closes.
    _apply_usage(st, usage)
    # Last, so the ordering against the boundary resets above is stated rather
    # than incidental: an outcome belongs to the turn its own record sits in.
    _apply_tool_outcome(st, record, harness)
    st["prev_ts"] = ep


def _latest_turn_context(
    config: RuntimeConfig,
    path: str,
    end_pos: int,
    harness: str,
) -> dict[str, Any]:
    """Find the nearest turn boundary before ``end_pos`` without loading the
    prefix into memory. Used when the file is larger than the forward-read
    budget so a long current turn is not lost.

    ``model`` is in the returned mapping only when this pass actually read one.
    ``scan_turns`` merges the result with ``st.update()``, so a key carrying
    None would overwrite a model an earlier pass already found — the key is
    absent, never null, and absence there means "this pass has nothing to say".
    """
    context: dict[str, Any] = {"turn_start": None, "last_start": None, "prev_ts": None}
    if end_pos <= 0:
        return context
    active_decided = False
    later_ts: float | None = None
    for raw in runtime_io.reverse_lines(config, path, end_pos):
        if not raw.startswith(b"{"):
            continue
        try:
            decoded = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(decoded, dict):
            continue
        transcript_records = (
            reversed(records.gemini_records(decoded)) if harness == "gemini" else (decoded,)
        )
        for record in transcript_records:
            # Walking backward, the first declaration met is the last one in
            # file order, so the first hit is kept and later ones ignored. The
            # forward pass over the tail runs after this and legitimately
            # overwrites it, being later still.
            if "model" not in context:
                model = records.model_signal(record, harness, sessions.MODEL_CAP_CHARS)
                if model:
                    context["model"] = model
            ep = records.parse_ts(record.get("timestamp") or "")
            if not ep:
                continue
            # Walking backward: `later_ts` is the timestamp of the record that
            # chronologically FOLLOWS this one. A quiet gap re-anchors the turn
            # at the post-gap record, same rule as the forward scanner.
            if later_ts is not None and later_ts - ep > config.turn_gap_reset_sec:
                if not active_decided:
                    context["turn_start"] = later_ts
                context["last_start"] = later_ts
                return context
            later_ts = ep
            if context["prev_ts"] is None:
                context["prev_ts"] = ep
            sig = records._turn_signal(record, harness)  # noqa: SLF001
            if not sig:
                continue
            kind, override = sig
            if not active_decided:
                active_decided = True
                if kind != "end":
                    context["turn_start"] = records.norm_epoch(override) or ep
            if kind != "end":
                context["last_start"] = records.norm_epoch(override) or ep
                return context
    return context


# What a scan result carries. The scanner's own bookkeeping stays behind — the
# id-to-name map for the last tool batch, and Gemini's dedup ledger, which no
# caller reads and which alone costs 5.9 us a call to copy against 0.55 for all
# of these together.
_RESULT_FIELDS = (
    "pos",
    "scanned_from_zero",
    "first_ts",
    "turn_start",
    "last_start",
    "prev_ts",
    "model",
    "session_output_tokens",
    "turn_output_tokens",
    "err_run",
    "err_peak",
    "err_total",
    "ok_total",
    "err_tool",
    "turn_complete",
)


def _snapshot(st: dict[str, Any]) -> dict[str, Any]:
    """Detach a result from the accumulator ``state.turn_scan`` keeps.

    Returning ``st`` itself made every result an alias of the next one, so a
    caller holding the first read the second call's numbers — which showed up
    as a false test failure during DRC-4024 rather than as a bug. ``durations``
    is copied rather than shared because it is appended to in place and rebound
    by the tail trim, so a top-level copy alone still points at the list the
    next call grows.

    0.55 us a call, against a 32 ms collection pass over the `balanced-five`
    bench profile whose 48 scanned paths make that 0.08% of the pass.
    """
    snapshot = {field: st[field] for field in _RESULT_FIELDS}
    snapshot["durations"] = list(st["durations"])
    return snapshot


def scan_turns(
    config: RuntimeConfig,
    state: RuntimeState,
    path: str,
    harness: str,
) -> dict[str, Any] | None:
    """Whole-file turn tracker for JSONL harnesses. The transcript tail can
    be shorter than the current turn (long turns bury the prompt beyond the
    tail window), so turns are tracked incrementally: each call parses only
    bytes appended since the last call and carries state in ``turn_scan``.

    Serialized via the scanner lock — concurrent /api/data requests would
    otherwise double-advance pos and double-count durations.

    Returns a snapshot, never the accumulator itself; see ``_snapshot``."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    with state.scanner_lock:
        st = state.turn_scan.get(path)
        if st is None or st["pos"] > size:  # new, truncated, or rotated file
            if len(state.turn_scan) >= config.max_cache_entries:
                state.turn_scan.pop(next(iter(state.turn_scan)))
            st = {
                "pos": 0,
                "scanned_from_zero": True,
                "first_ts": None,
                "turn_start": None,
                "last_start": None,
                "durations": [],
                "prev_ts": None,
                # The model the transcript last declared, or None for "not
                # read". Tracked here rather than in the tail analyzer because
                # the declaration sits far behind EOF on real files — a median
                # of 273 KB and up to 3 MB — while this scanner's budget is
                # 8 MB and reaches every one of them.
                "model": None,
                # Both counters start unmeasured. An explicit zero usage record
                # turns one into 0; merely supporting the harness does not.
                "session_output_tokens": None,
                "turn_output_tokens": None,
                # A bounded tail cannot count a turn until its opening
                # prompt/start appears in the bytes read forward. Two readings
                # depend on it: the turn token total, and whether `loop_signal`
                # may say anything about what the request did NOT do.
                "turn_complete": False,
                # The failure run inside the current turn: the live count, the
                # peak it reached, the totals that no success resets, the tool
                # that failed at the peak, and the id → name map the last tool
                # batch declared. All six are turn state, so an evicted or
                # rotated file recomputes them on the way forward rather than
                # carrying a stale count.
                "err_run": 0,
                "err_peak": 0,
                "err_total": 0,
                "ok_total": 0,
                "err_tool": None,
                "tool_names": {},
                "gemini_seen": {},
                "gemini_snapshot_count": 0,
                "gemini_snapshot_tail": None,
            }
            state.turn_scan[path] = st
        if size == st["pos"]:
            return _snapshot(st)
        if size - st["pos"] > config.turn_scan_max_bytes:
            # Locate the active turn boundary in the skipped prefix by reading
            # backward in chunks, then process the bounded tail forward.
            st["scanned_from_zero"] = False
            # The skipped bytes may contain usage. Withhold rather than publish
            # a partial session total or a smaller current-turn count.
            st["session_output_tokens"] = None
            st["turn_output_tokens"] = None
            st["turn_complete"] = False
            tail_start = size - config.turn_scan_max_bytes
            st.update(_latest_turn_context(config, path, tail_start, harness))
            st["pos"] = tail_start
        with os.fdopen(runtime_io.open_harness(path), "rb") as f:
            f.seek(st["pos"])
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return _snapshot(st)  # incomplete line, wait for more bytes
        st["pos"] += end + 1
        for raw in data[:end].split(b"\n"):
            if not raw.startswith(b"{"):
                continue
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            transcript_records = (
                records.incremental_gemini_records(d, st) if harness == "gemini" else (d,)
            )
            for record in transcript_records:
                if harness == "gemini":
                    fingerprint = records.record_fingerprint(record)
                    if fingerprint in st["gemini_seen"]:
                        continue
                    if len(st["gemini_seen"]) >= config.gemini_seen_entries:
                        st["gemini_seen"].pop(next(iter(st["gemini_seen"])))
                    st["gemini_seen"][fingerprint] = None
                _apply_turn_record(config, st, record, harness)
        st["durations"] = st["durations"][-50:]
        return _snapshot(st)


def started_at(scan: dict[str, Any] | None) -> float | None:
    """The transcript's first timestamp, only when the scan covered its head."""
    if not scan or scan.get("scanned_from_zero") is not True:
        return None
    value = scan.get("first_ts")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def turns_from_events(events: list[tuple[float, bool]]) -> dict[str, Any]:
    """Turn state from chronologically sorted (epoch, is_user_prompt) pairs —
    used by DB-backed harnesses where messages come from SQL, not a file."""
    turn_start = prev = None
    durations = []
    for ep, is_user in events:
        if not ep:
            continue
        if is_user:
            if turn_start and prev and prev > turn_start:
                durations.append(prev - turn_start)
            turn_start = ep
        prev = ep
    return {"turn_start": turn_start, "durations": durations[-50:]}


def loop_signal(scan: dict[str, Any] | None, config: RuntimeConfig) -> dict[str, Any] | None:
    """What went wrong inside the current turn, once it is worth saying out
    loud, else None.

    Read off the peak rather than the live run, and not gated on the session
    state the way `turn_progress` is: both would retract the signal the instant
    the loop stopped, and a loop that has stopped is what the reader is walking
    back to the machine to find.

    `errors` stays the peak run and keeps its meaning, because the page says
    "in a row" about it. `failures` is the turn total, which no success resets,
    and it carries its own higher threshold: four scattered failures through a
    productive turn is ordinary work, and reusing the run threshold here would
    have fired on it.

    `failures` and `barren` are absent, rather than false, when the scan never
    read the turn open. Both describe the whole turn, and `barren` is a claim
    about what did NOT happen, which no partial view can support.
    """
    if not scan:
        return None
    peak = scan.get("err_peak") or 0
    total = scan.get("err_total") or 0
    # Both totals are counts of the whole turn, so neither may be spoken from a
    # partial view of it. `turn_complete` is false when the forward scan never
    # read the turn open, which is the same state that already withholds
    # `turn_output_tokens`; the module knew it could not vouch for these numbers
    # and published them anyway. The run is different and stays ungated: four
    # consecutive failures actually seen are four consecutive failures, whatever
    # came before the bytes read.
    complete = scan.get("turn_complete") is True
    # Three readings of one turn, not three signals. The run says a loop is
    # tight, the total says how much of the turn failed however it was spaced,
    # and barren says nothing in it has worked yet. A turn can trip any of them
    # alone: 3 fail, 1 ok, 3 fail never reaches a run of four and is the case
    # this counter was added for.
    ok_count = scan.get("ok_total") or 0
    barren = complete and ok_count == 0 and total >= config.loop_barren_failure_threshold
    # The count alone is not enough, and this was measured rather than reasoned:
    # replaying 60 real Claude transcripts, 3 reached six scattered failures on
    # turns that were plainly healthy, the worst being 7 failures among 198
    # successes with a longest run of 2. So the turn's failures must also
    # outnumber its successes. The two groups sit about fourteen times apart, and
    # the shape this rung exists for (3 fail, 1 ok, 3 fail) clears it easily.
    over_total = complete and total >= config.loop_error_total_threshold and total > ok_count
    if peak < config.loop_error_run_threshold and not over_total and not barren:
        return None
    signal: dict[str, Any] = {"errors": peak, "tool": scan.get("err_tool")}
    if complete:
        signal["failures"] = total
        signal["barren"] = barren
    return signal


def turn_progress(
    scan: dict[str, Any] | None,
    session_state: str,
    now: float,
    config: RuntimeConfig,
) -> dict[str, Any] | None:
    """Naive current-turn ETA: estimated total = median of this session's
    past turns that lasted at least as long as the current one has so far."""
    if session_state != "working" or not scan or not scan.get("turn_start"):
        return None
    elapsed = sessions.age(config, now, scan["turn_start"])
    if elapsed is None:
        return None  # turn start is implausibly ahead of the clock; no ETA
    history = scan.get("durations") or []
    cands = sorted(d for d in history if d >= elapsed)
    if cands:
        est_total = cands[len(cands) // 2]
        return {
            "elapsed_h": sessions.fmt_duration(elapsed),
            "eta_h": sessions.fmt_duration(est_total - elapsed),
            "pct": min(99, round(elapsed * 100 / est_total)) if est_total else 99,
            "long": max(est_total, elapsed) >= config.long_turn_warn_sec,
        }
    return {
        "elapsed_h": sessions.fmt_duration(elapsed),
        "eta_h": None,  # running longer than any recent turn
        "pct": 99 if history else None,
        "long": elapsed >= config.long_turn_warn_sec,
    }
