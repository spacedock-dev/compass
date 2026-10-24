#!/usr/bin/env python3
"""The answer key for "does a reading know when to say I can't tell".

DEC-17's evaluation needs expected answers written down BEFORE the producer is
pointed at them. A mark written after seeing an output is agreement, not a
mark. This collects those answers. The captain accepted the recorded case review
as sufficient to enable readings on 2026-09-14, and the owner accepted the
Claude Code producer on 2026-10-02 after its scored runs failed; scoring remains
a separate act.

    mark_abstention.py --build      assemble cases from the live board
    mark_abstention.py              mark the unmarked ones, one call each
    mark_abstention.py --report     progress, and the spread of what is marked
    mark_abstention.py --freeze F   freeze a format 5 packet from the spec in F
    mark_abstention.py --freeze F --production-reading
                                   prospectively freeze typed Claude production inputs

The prospective flag admits parent agent excerpts and binds the exact production
selection against a stamped historical source prefix. Whole final replies remain
in memory: packets store digests, and scoring rereads and checks the source.
Adopted goals and request-aged lines refuse this v1 scope. Existing packets are
never upgraded, and this source freeze establishes no accuracy verdict.

## What a case has to put on screen, and why two versions of this failed

Twice, and both times for the same reason: the questions turned on something the
display did not show.

v1 drew cases from the history store, which keeps five fields per observation by
a deliberate allowlist. Every case rendered as a harness and a poll count. Four
identical rows in a row, fifty four questions, and a key marked unanimously
because there was nothing to tell the cases apart.

v2 moved to the live board and showed session metadata: a directive fragment, a
turn percentage, a state. Better, and still wrong. A reading does not read
metadata. It reads the **ledger** -- the `project_context` facts for that
session, filtered to the ones carrying a type, a source and a summary. Two of
six cases still rendered byte identical. The complaint was the same complaint.

So this version fetches the ledger per case and shows it. The question "can it
judge this" is operationally "does that ledger hold anything citable", and that
number is now on screen.

## Three properties, each a decision rather than a preference

**The marker is not the author.** Whoever wrote the producer must not write the
key, or the key records what the code already does. The tool refuses to guess a
mark, has no default, and has no "mark the rest like that one".

**A question with a fixed answer is not asked.** The Expected Output constraint
is only ever put to the model when the record it reads holds work evidence
(`reading.asks_output`), and this tool never grants tool output, so that is a
Pi session with a demonstrated work result. Asking it about any other session is
asking the marker to transcribe a constant, and half of v2's prompts did exactly
that. This reads the producer's own predicate over the case's ledger to know
which cases to skip. That is the producer's **contract**, not its output, and
the two are not the same thing: a tool that knows which questions are asked
cannot thereby agree with an answer.

**A mark is keyed on identity, never on position.** v2 hashed the row's index in
the board's session list. The board reorders on every state change, so a rebuild
silently re-attached answers to different sessions -- measured, four of six. The
key is now a hash of `(harness, sid)`, which is stable, and still carries no
session identity into the file that gets committed.

## What a scorer has to do, written down so it is not discovered later

The two constraints below live in this file, not in the annotation store. A
producer handed a session with no stored revision refuses it outright with
`nothing-typed`, before any evidence is read. So `score_abstention.py` hands
`reading.produce` these two lines as a **synthetic revision**, per case, as an
argument: nothing is written to `compass-annotations.json`, no reading count
moves, and the Intent log stays the reader's. The first draft of this paragraph
had the scorer write and clear a store revision instead; `produce` takes
`revisions` as a parameter, so that was a write for nothing, and a write into
a file that is the reader's.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import pathlib
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeGuard, cast

import abstention_ledger
import store_paths

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from typing import BinaryIO

_SKILL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "compass", "skills", "compass"
)


def _reading() -> Any:
    """The producer's CONTRACT, reached the way every sibling script reaches it.

    Deferred rather than imported at the top, because `scripts` is on mypy's
    path as well as being a package to the tests, and a module-level runtime
    import makes this file resolvable under two names. `bench_collect.py` does
    the same thing for the same reason.

    What is read is which constraints are asked and which entry types count as
    work, never a produced reading. A tool that knows the questions cannot
    thereby agree with an answer; one that can see outputs can.
    """
    if _SKILL not in sys.path:
        sys.path.insert(0, _SKILL)
    from compass_runtime import reading  # noqa: PLC0415

    return reading


HOME = store_paths.store_home()
# Read once, with HOME: a report from the default home was once posted as the
# marks for a packet that lived elsewhere, so every mode that reads a packet
# says when this was the case.
DEFAULT_HOME = not os.environ.get("COMPASS_HOME")
CASES_PATH = os.path.join(HOME, "abstention-cases.json")
MARKS_PATH = os.path.join(HOME, "abstention-marks.json")

# The same pair against every case. Held constant so the evidence is the only
# thing that varies; a per-case goal is the obvious place for the author's thumb.
GOAL = "Finish the work this session was started for."
OUTPUT = "Something I can check: a diff, a test run, or a file I can open."

# Format 5 (DRC-4666): each case carries its own intent, a goal and the outcome
# lines a reader would save, and a Claude Code case carries its checks frozen
# as they stood at the capture. The constant pair above cannot pose a line a
# passing test does not cover, which is the class DEC-23 left standing.
FORMAT_INTENT = 5
# When a case's intent counts as typed, unless it names its own time: before
# every session end, for the reason `score_abstention.YARDSTICK_AT` gives.
INTENT_AT = 1.0
# A frozen case the machine's own records do not vouch for: scored, and never
# counted toward the recorded floor (DRC-4666 review, F4).
ORIGIN_SYNTHETIC = "synthetic"
# Where a recorded session's words can come from. A transcript anywhere else
# was written by somebody, not recorded by the harness.
CLAUDE_PROJECTS_ROOT = abstention_ledger.canonical_path(".claude", "projects")
# Where the freeze reads the dashboard's own history and ends: the store the
# lifecycle was observed into, never the packet's directory.
STORE_HOME = abstention_ledger.canonical_store_path()

# Cases per (harness, end shape), so the corpus spreads instead of filling up
# with whichever harness ran most today. v2 had this constant and no bucketing,
# which is how a six case corpus came to be six Claude sessions in one state.
PER_BUCKET = 3


# What each case format's cases carry, as the code that writes them writes
# them: `build` for 3, `freeze_case` for 5, and for 4, which nothing writes any
# more, what the marker reads. A packet short of these was written by another
# version of this file, and `_show` died on the first missing key (DRC-4666).
_CASE_FIELDS: dict[int, tuple[str, ...]] = {
    3: (
        "id",
        "harness",
        "sid",
        "end_shape",
        "facts",
        "citable",
        "work_results",
        "reached",
        "asks_output",
    ),
    4: ("id", "harness", "sid", "producer_facts"),
    5: (
        "id",
        "harness",
        "sid",
        "origin",
        "captured_at",
        "row_snapshot",
        "intent",
        "producer_facts",
        "unconfirmed",
    ),
}
_CLAUDE_FROZEN_FIELDS = ("tool_output", "transcript_bytes", "parser")


def display_path(path: str) -> str:
    """A path under the account's home in `~` form, spelled with `/` on every platform."""
    home = abstention_ledger.canonical_home()
    if home is not None and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home) :].replace(os.sep, "/")
    return path


def packet_lines(path: str, body: dict[str, Any]) -> list[str]:
    """Which packet was read, said first by every mode that reads one."""
    cases = body.get("cases")
    count = len(cases) if isinstance(cases, list) else 0
    held = f"{count} case" + ("" if count == 1 else "s")
    lines = [f"Packet: {display_path(path)} ({held if os.path.exists(path) else 'not found'})"]
    if DEFAULT_HOME:
        lines.append(
            f"COMPASS_HOME is not set, so this read the default home, {display_path(HOME)}. "
            "Set COMPASS_HOME to the packet's directory if this is not the packet you meant."
        )
    return lines


def print_packet(path: str, body: dict[str, Any]) -> None:
    for line in packet_lines(path, body):
        print(line)


def packet_mismatch(body: dict[str, Any]) -> str:
    """Why this version cannot read the packet's cases, or empty."""
    version = body.get("v")
    if "v" not in body:
        return "It names no case format."
    if type(version) is not int or version not in _CASE_FIELDS:
        return f"It is case format {version}, and this version reads formats 3, 4 and 5."
    raw = body.get("cases")
    cases: list[Any] = raw if isinstance(raw, list) else []
    short: list[str] = []
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            return f"Its case {index} is not an object."
        needs = _CASE_FIELDS[version]
        if version == FORMAT_INTENT and case.get("harness") == "claude":
            needs += _CLAUDE_FROZEN_FIELDS
        missing = [field for field in needs if field not in case]
        if missing:
            name = case.get("id") if isinstance(case.get("id"), str) else ""
            short.append(f"case {index}{f' ({name})' if name else ''} lacks {', '.join(missing)}")
    if not short:
        return ""
    return (
        f"{len(short)} of {len(cases)} cases lack fields this version needs; the first: {short[0]}."
    )


def _refuse_mismatch(body: dict[str, Any], nothing: str) -> bool:
    """True, having said why and what to do, when the packet is not this version's."""
    why = packet_mismatch(body)
    if not why:
        return False
    print("Refused: this packet was frozen by a different version of these scripts.")
    print(f"  {why}")
    print("  Run from an up-to-date checkout (git pull) and try again. If this checkout is")
    print("  current, the packet is older than these scripts: build or freeze a new one in a")
    print("  fresh COMPASS_HOME.")
    print(nothing)
    return True


def cases_digest(body: dict[str, Any]) -> str:
    """Bind replay marks to the evidence and yardstick the marker saw."""
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def is_intent_packet(body: dict[str, Any]) -> bool:
    return body.get("v") == FORMAT_INTENT


def _epoch(value: Any) -> TypeGuard[float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == value  # noqa: PLR0124 - NaN is the one value unequal to itself
        and 0 < value < float("inf")
    )


def case_revision(case: dict[str, Any]) -> dict[str, Any]:
    """A format 5 case's intent as the one revision `reading.produce` reads.

    Handed in as an argument, never written to the store, as the yardstick is.
    """
    raw = case.get("intent")
    intent: dict[str, Any] = raw if isinstance(raw, dict) else {}
    revision: dict[str, Any] = {
        "n": 1,
        "at": intent["at"] if _epoch(intent.get("at")) else INTENT_AT,
        "goal": str(intent.get("goal") or ""),
        "lines": list(intent.get("lines") or []),
    }
    for key in ("window_start", "goal_source", "goal_source_at"):
        if key in intent:
            revision[key] = intent[key]
    return revision


def case_lines(case: dict[str, Any]) -> tuple[str, ...]:
    return tuple(_reading().outcome_lines(case_revision(case)))


def case_constraints(body: dict[str, Any], case: dict[str, Any]) -> tuple[str, ...]:
    """What is marked and scored for this case: goal and output, or goal and each line."""
    if is_intent_packet(body):
        source = case.get("production_reading")
        if isinstance(source, dict):
            constraints = source.get("constraints")
            if not isinstance(constraints, list) or not all(
                isinstance(c, str) for c in constraints
            ):
                raise FreezeError("production-constraints-invalid")
            return tuple(constraints)
        return tuple(_reading().constraints_for(case_lines(case)))
    return ("goal", "output")


def case_checks(
    body: dict[str, Any], case: dict[str, Any]
) -> tuple[dict[str, str] | None, frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    """Frozen tails, later-command pairs and incomplete-read pairs.

    Only a format 5 Claude Code case carries checks. Older packets lack the
    incomplete-read field; an absent field means no such pass was frozen.
    """
    if not is_intent_packet(body) or case.get("harness") != "claude":
        return None, frozenset(), frozenset()
    raw = case.get("tool_output")
    frozen: dict[str, Any] = raw if isinstance(raw, dict) else {}
    tails = frozen.get("tails")

    def pairs(key: str) -> frozenset[tuple[str, str]]:
        values = frozen.get(key)
        return (
            frozenset(
                (str(pair[0]), str(pair[1]))
                for pair in values or ()
                if isinstance(pair, (list, tuple)) and len(pair) == 2
            )
            if isinstance(values, list)
            else frozenset()
        )

    return (
        {str(k): str(v) for k, v in tails.items()} if isinstance(tails, dict) else {},
        pairs("changed_after"),
        pairs("read_incomplete"),
    )


def case_ledger(body: dict[str, Any], case: dict[str, Any]) -> tuple[Any, ...]:
    """The frozen ledger the producer will read, checks included where frozen."""
    tails, changed, incomplete = case_checks(body, case)
    return tuple(
        _reading().build_ledger(
            case.get("producer_facts") or [],
            str(case.get("harness") or ""),
            str(case.get("sid") or ""),
            tool_output=tails,
            changed_after=changed,
            read_incomplete=incomplete,
            read_agent_words="production_reading" in case,
        )
    )


def _source_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _wanted(rows: Sequence[Any], kind: str) -> list[dict[str, Any]]:
    return [
        {key: row[key] for key in ("id", "type", "author", "at")}
        for row in rows
        if row.get("type") == kind
    ]


def _final_metadata(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        **{key: value for key, value in result.items() if key != "words"},
        **({"words_digest": _source_digest(result["words"])} if "words" in result else {}),
    }


def _bounded_source_cut(handle: BinaryIO, captured: float, max_bytes: int) -> int:
    """Find the cut on the opened source, with one bounded future-record lookahead."""
    from compass_runtime import project_context  # noqa: PLC0415 - see `_reading`

    offset = 0
    while raw := handle.readline(project_context.FINAL_WORDS_RECORD_MAX_BYTES + 1):
        if len(raw) > project_context.FINAL_WORDS_RECORD_MAX_BYTES:
            raise FreezeError("production-source-record-too-large")
        try:
            record = json.loads(raw)
        except (ValueError, RecursionError):
            record = None
        at = (
            project_context._record_timestamp(record)  # noqa: SLF001
            if isinstance(record, dict)
            else None
        )
        if at is not None and at > captured:
            return offset
        offset += len(raw)
        if offset > max_bytes:
            raise FreezeError("production-source-too-large")
    return offset


@contextlib.contextmanager
def _historical_source(case: dict[str, Any], transcript: str) -> Iterator[tuple[str, str]]:
    """An owned bounded capture prefix; raw/full words never enter the packet."""
    from compass_runtime import project_context  # noqa: PLC0415 - see `_reading`

    size = case.get("transcript_bytes")
    if type(size) is not int or size < 0 or size > project_context.FINAL_WORDS_SCAN_MAX_BYTES:
        raise FreezeError("production-source-too-large")
    stamp = project_context.transcript_stamp(transcript)
    if stamp is None:
        raise FreezeError("production-source-differs")
    descriptor = os.open(transcript, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != stamp:
            raise FreezeError("production-source-moved")
        if (
            _bounded_source_cut(
                handle, float(case["captured_at"]), project_context.FINAL_WORDS_SCAN_MAX_BYTES
            )
            != size
        ):
            raise FreezeError("production-source-differs")
        handle.seek(0)
        prefix = handle.read(size)
    if len(prefix) != size or project_context.transcript_stamp(transcript) != stamp:
        raise FreezeError("production-source-moved")
    digest = hashlib.sha256(prefix).hexdigest()
    frozen = case.get("production_reading")
    if isinstance(frozen, dict) and frozen.get("prefix_digest") != digest:
        raise FreezeError("production-source-differs")
    with tempfile.TemporaryDirectory(prefix="compass-native-source-") as folder:
        path = os.path.join(folder, os.path.basename(transcript))
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(prefix)
        yield path, digest


def _production_capture(config: Any, case: dict[str, Any], transcript: str) -> dict[str, Any]:
    """Capture the actual production selection using a model-free prompt sink."""
    reading = _reading()
    from compass_runtime import project_context  # noqa: PLC0415 - see `_reading`

    revision = case_revision(case)
    if (
        case.get("harness") != "claude"
        or revision.get("goal_source") in reading.PROMPT_SOURCES
        or reading.has_line_requests(revision)
    ):
        raise FreezeError("production-intent-source-unsupported")
    frozen: dict[str, Any] = {"v": 1, "final_wanted": [], "newest_final": None}
    with _historical_source(case, transcript) as (path, digest):
        frozen["prefix_digest"] = digest
        stamp = project_context.transcript_stamp(path)

        def person(rows: Sequence[Any]) -> list[dict[str, Any]]:
            frozen["person_wanted"] = _wanted(rows, "user_message")
            words = project_context.transcript_window_words(
                config,
                path,
                "claude",
                str(case["sid"]),
                rows,
                expected_stamp=stamp,
            )
            frozen["person_words_digest"] = _source_digest(words)
            return words

        def final(rows: Sequence[Any]) -> dict[str, Any]:
            frozen["final_wanted"] = _wanted(rows, reading.AGENT_MESSAGE_TYPE)
            result = project_context.transcript_newest_final_words(
                config,
                path,
                "claude",
                str(case["sid"]),
                rows,
                expected_stamp=stamp,
            )
            frozen["newest_final"] = _final_metadata(result)
            return result

        prompts: list[str] = []

        def sink(prompt: str, **_kwargs: Any) -> tuple[str, str]:
            prompts.append(prompt)
            return "{}", "ok"

        tails, changed, incomplete = case_checks({"v": FORMAT_INTENT}, case)
        assessment, _why, _spent = reading.produce(
            config,
            case["row_snapshot"],
            [revision],
            case["producer_facts"],
            now=float(case["captured_at"]),
            stamp_text="native source freeze",
            model=sink,
            read_lines=True,
            read_agent_words=True,
            admit_turn_stop=True,
            # Not the idle admission of 2026-10-20, as `score_abstention` passes it: the cases are
            # marked under the earlier rule, which withheld an idle session with no recorded
            # finish, and a freeze that admitted one would capture a prompt the scorer never sends.
            admit_idle=False,
            tool_output=reading.ToolOutput(
                destination="native-dry",
                label="native dry",
                tails=tails or {},
                changed_after=changed,
                read_incomplete=incomplete,
            ),
            person_source_lookup=person,
            final_source_lookup=final,
        )
    if len(prompts) != 1 or "person_wanted" not in frozen:
        raise FreezeError("production-prompt-unavailable")
    if assessment is None:
        raise FreezeError("production-prompt-unavailable")
    frozen["constraints"] = list(assessment["criteria"])
    frozen["prompt_digest"] = hashlib.sha256(prompts[0].encode()).hexdigest()
    return frozen


def _native_source_lookup(
    case: dict[str, Any],
    kind: str,
    *,
    config: Any = None,
    index: dict[str, str] | None = None,
    reviewed_exports: ReviewedExports | None = None,
) -> Callable[[Sequence[Any]], Any] | None:
    if "production_reading" not in case:
        return None
    frozen = case["production_reading"]
    if not isinstance(frozen, dict) or frozen.get("v") != 1:
        raise FreezeError("production-source-invalid")
    reading = _reading()
    from compass_runtime import project_context  # noqa: PLC0415 - see `_reading`

    actual_config = config if config is not None else _runtime_config()
    exported = "reviewed_export" in case
    if exported:
        if reviewed_exports is None:
            raise FreezeError("reviewed-export-opt-in-required")
        reviewed_exports.validate(case, actual_config)
        path = ""
    else:
        sources = index if index is not None else _transcript_index()
        path = sources.get(str(case.get("sid") or "")[:8], "")
        if not path:
            raise FreezeError("no-transcript")

    def lookup(rows: Sequence[Any]) -> Any:
        final = kind == reading.AGENT_MESSAGE_TYPE
        key = "final_wanted" if final else "person_wanted"
        if _wanted(rows, kind) != frozen.get(key):
            raise FreezeError("production-selection-differs")
        source_context = (
            reviewed_exports.source(case, actual_config)
            if exported and reviewed_exports is not None
            else _historical_source(case, path)
        )
        with source_context as (source, _digest):
            stamp = project_context.transcript_stamp(source)
            result: Any
            if final:
                result = project_context.transcript_newest_final_words(
                    actual_config,
                    source,
                    "claude",
                    str(case["sid"]),
                    rows,
                    expected_stamp=stamp,
                )
                matches = _final_metadata(result) == frozen.get("newest_final")
            else:
                result = project_context.transcript_window_words(
                    actual_config,
                    source,
                    "claude",
                    str(case["sid"]),
                    rows,
                    expected_stamp=stamp,
                )
                matches = _source_digest(result) == frozen.get("person_words_digest")
        if not matches:
            raise FreezeError("production-source-differs")
        return result

    return lookup


def native_case_person_lookup(
    case: dict[str, Any], **kwargs: Any
) -> Callable[[Sequence[Any]], Any] | None:
    """Restore only the frozen selected reader words, from source in memory."""
    return _native_source_lookup(case, "user_message", **kwargs)


def native_case_final_lookup(
    case: dict[str, Any], **kwargs: Any
) -> Callable[[Sequence[Any]], Any] | None:
    """Recover the bound newest final in memory; the packet retains only its digest."""
    return _native_source_lookup(case, _reading().AGENT_MESSAGE_TYPE, **kwargs)


def _get(url: str, timeout: int = 30) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed loopback
        return json.loads(response.read().decode("utf-8"))


def _text(value: Any) -> str:
    """The row publishes several of these as an object carrying a label."""
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value or "")


_TRANSCRIPTS: dict[str, str] | None = None


def _transcript_index() -> dict[str, str]:
    """Walk the Claude project tree once, not once per case.

    Measured: walking it per case took the build past two minutes on this
    machine, because the tree is large and every case paid for the whole of it.
    """
    global _TRANSCRIPTS  # noqa: PLW0603 - a process-lifetime index, built once
    if _TRANSCRIPTS is not None:
        return _TRANSCRIPTS
    index: dict[str, str] = {}
    root = CLAUDE_PROJECTS_ROOT
    if root is None:
        return index
    try:
        for base, _dirs, names in os.walk(root):
            for name in names:
                if name.endswith(".jsonl"):
                    index.setdefault(name[:8], os.path.join(base, name))
    except OSError:
        pass
    _TRANSCRIPTS = index
    return index


def _first_ask(harness: str, sid: str) -> str:
    """What the session was started for, in the reader's own words.

    The board publishes `instruction`, which is `directives[-1]` -- the LATEST
    usable directive, not the opening one. For a long session that is some
    mid-flight command: one case rendered as "commit and push once tests pass"
    for a session whose purpose was finding a quick-win issue, which left the
    marker judging a sentence with no context. DRC-4509 records the same
    distinction from the other side.

    Stops at the first real user turn rather than reading the file, because
    these transcripts run to megabytes and only the opening ask is wanted.
    """
    if harness != "claude":
        return ""
    path = _transcript_index().get(sid[:8])
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("type") != "user":
                    continue
                content = (record.get("message") or {}).get("content")
                text = (
                    content
                    if isinstance(content, str)
                    else " ".join(
                        b.get("text", "")
                        for b in content or []
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                )
                text = " ".join(str(text).split())
                # A skill body, a caveat banner and an interrupt notice all
                # arrive as user turns and none of them is something asked.
                skip = ("<", "Caveat:", "[Request interrupted", "Base directory")
                if text and not text.startswith(skip):
                    return text
    except OSError:
        return ""
    return ""


def _case_id(harness: str, sid: str) -> str:
    """A stable key over identity, and nothing readable.

    Not the position, which was v2's fatal defect. Not the state, which moves.
    The marks file is the half that gets committed, and a session id in it would
    publish which of the reader's sessions were used, so it is hashed. The cases
    file keeps the identity and stays on this machine.
    """
    return hashlib.sha256(f"{harness}|{sid}".encode()).hexdigest()[:16]


def _end_shape(row: dict[str, Any]) -> str:
    """How this session ended, in the producer's own three-way distinction."""
    if row.get("ended_at"):
        return "session end observed"
    if str(row.get("state") or "") not in {"idle", "ended"}:
        return "still running"
    if row.get("finished_at"):
        return "a turn stopped, no session end"
    return "went quiet, no end observed"


def _ledger(port: int, row: dict[str, Any]) -> dict[str, Any]:
    """What a reading would actually have to cite for this session.

    `facts` is the ledger the producer would hold and `citable` the subset a
    reading can build a claim on, which are `produce`'s two refusals in order.
    `work_results` is the subset that demonstrates work rather than describing
    a request, which is what the Expected Output constraint needs.

    Both numbers come from the producer's own `build_ledger` and `_citable`
    rather than a second copy of their rules, because a second copy drifted:
    this counted a fact citable on `type` and `summary` alone, where rule 3
    also needs a named evidence source, and it scoped the list with
    `fact["sid"]` -- a key `project_context` does not write, so the filter
    admitted every fact the endpoint returned for the project. Both errors run
    the same way, toward a screen that says there is evidence where the
    producer will find none, and a case marked judge on that screen is refused
    before the model and counts for neither side.
    """
    project = str(row.get("project_key") or row.get("project") or "")
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    blank = {"facts": 0, "citable": 0, "work_results": 0, "reached": False}
    if not project:
        return blank
    query = urllib.parse.urlencode({"project": project, "session": f"{harness}:{sid}"})
    try:
        body = _get(f"http://127.0.0.1:{port}/api/project-context?{query}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return blank
    reading = _reading()
    facts = ((body or {}).get("semantic") or {}).get("facts") or []
    # The endpoint answers for the focused session and for its children and
    # the project-scoped facts they share a work item with, so the scoping is
    # the producer's to do, not this tool's to assume.
    mine = reading.build_ledger(facts, harness, sid)
    citable = [entry for entry in mine if reading._citable(entry)]  # noqa: SLF001 - see above
    work = [entry for entry in citable if reading.demonstrates_work(entry)]
    return {
        "facts": len(mine),
        "citable": len(citable),
        "work_results": len(work),
        "reached": True,
    }


def _signature(case: dict[str, Any]) -> tuple[Any, ...]:
    """What makes two cases the same question.

    Measured: cases 19 and 20 of a 23 case run rendered byte identical -- same
    harness, no ask, no directive, no facts, no end -- and were asked as two
    separate questions. A marker answering the same screen twice is being
    charged twice for one judgement.
    """
    barren = not case.get("asked_for") and not case["citable"]
    return (
        # A session with no recorded ask and no citable fact is the same
        # question on every harness: should the board speak about something it
        # recorded nothing of. Keeping the harness split it into four screens
        # that differed only by a name in the header.
        "" if barren else case["harness"],
        bool(case.get("asked_for")),
        bool(case.get("directive")),
        case["end_shape"],
        case["citable"] > 0,
        case["work_results"] > 0,
    )


def _dedupe(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One case per distinct question."""
    seen: set[tuple[Any, ...]] = set()
    kept = []
    for case in cases:
        signature = _signature(case)
        if signature in seen:
            continue
        seen.add(signature)
        case["stands_for"] = sum(1 for other in cases if _signature(other) == signature)
        kept.append(case)
    return kept


def _bucket(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Take PER_BUCKET of each (harness, end shape), so the corpus spreads."""
    seen: dict[tuple[str, str], int] = {}
    kept = []
    for case in cases:
        key = (str(case["harness"]), str(case["end_shape"]))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] <= PER_BUCKET:
            kept.append(case)
    return kept


def build(port: int, *, force: bool = False) -> int:
    """Draw cases from the live board and enrich each with its ledger.

    `all=1` matters. Without it the board returns only what ran inside
    `window_hours`, which is a day, and the corpus is then whatever happened
    today. The sessions that have actually ended -- the ones a final reading
    turns on -- are mostly older than that.
    """
    existing = _load(MARKS_PATH)
    held = dict(existing.get("marks") or {}) if existing else {}

    try:
        payload = _get(f"http://127.0.0.1:{port}/api/data?all=1")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        print(f"Could not read the board on port {port}: {error}")
        print("Start the dashboard first, then run this again.")
        return 1

    rows = payload.get("sessions") or []
    if not rows:
        print(f"The board on port {port} returned no sessions, so there is no corpus.")
        print("Nothing was written. Start the dashboard where your sessions are.")
        return 1

    cases: list[dict[str, Any]] = []
    for row in rows:
        harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
        if not harness or not sid:
            continue
        cases.append(
            {
                "id": _case_id(harness, sid),
                "harness": harness,
                "sid": sid,
                "project": row.get("project"),
                "title": row.get("title"),
                "asked_for": _first_ask(harness, sid),
                "directive": _text(row.get("instruction")) or _text(row.get("last_prompt")),
                "state": row.get("state"),
                "end_shape": _end_shape(row),
                "acquisition": row.get("acquisition") or "events",
                "annotated": bool(row.get("annotation_revision")),
            }
        )

    cases = _bucket(cases)
    print(f"Fetching the evidence ledger for {len(cases)} sessions.")
    for case in cases:
        case.update(_ledger(port, {"project_key": case["project"], **case}))
        # The Expected Output constraint is only ever put to the model where
        # the ledger holds work evidence. Elsewhere the answer is fixed by the
        # ruling and asking for it wastes the marker.
        case["asks_output"] = bool(case.get("work_results"))

    unique = _dedupe(cases)
    dropped = len(cases) - len(unique)
    cases = unique

    orphans = [k for k in held if k not in {c["id"] for c in cases}]
    if orphans and not force:
        print(f"\n{len(orphans)} existing marks name sessions this build does not include.")
        print("Rebuilding would leave them pointing at nothing. Re-run with --force")
        print("to rebuild anyway; the marks themselves are never deleted by a build.")
        return 1

    _write(CASES_PATH, {"v": 3, "goal": GOAL, "output": OUTPUT, "cases": cases})

    shapes = {c["end_shape"] for c in cases}
    harnesses = {c["harness"] for c in cases}
    with_facts = sum(1 for c in cases if c["citable"])
    print(f"\nBuilt {len(cases)} cases: {len(harnesses)} harnesses, {len(shapes)} end shapes.")
    if dropped:
        print(f"  {dropped} were dropped as the same question asked twice.")
    print(f"  {with_facts} carry citable evidence, {len(cases) - with_facts} carry none.")
    print(f"  {sum(1 for c in cases if c['asks_output'])} can be asked the OUTPUT question.")
    # Proportional, not merely non-zero. Measured: a 21 case corpus where one
    # case carried evidence and twenty did not passed a `not in {0, len}` test
    # and was still twenty near identical screens. A dimension that splits one
    # from twenty does not separate a producer that abstains from one that
    # never does.
    thin = min(with_facts, len(cases) - with_facts) < max(2, len(cases) // 5)
    if len(shapes) < 2 or thin:
        print("\n  This corpus does not vary in what the questions turn on, so a key")
        print("  marked against it cannot fail a producer that never abstains.")
        print("  It wants sessions that ended and sessions that did not, and some")
        print("  with recorded evidence and some without.")
    print(f"\nWritten to {CASES_PATH} (stays on this machine, never committed).")
    return 0


def _runtime_config() -> Any:
    """The runtime config the dashboard would build here, for the freeze's reads."""
    _reading()
    from compass_runtime import config  # noqa: PLC0415 - see `_reading`

    return config.build_runtime_config(
        environ=os.environ,
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=pathlib.Path(_SKILL, "server.py"),
    )


def _session_facts(port: int, project: str, harness: str, sid: str) -> list[dict[str, Any]] | None:
    query = urllib.parse.urlencode({"project": project, "session": f"{harness}:{sid}"})
    try:
        body = _get(f"http://127.0.0.1:{port}/api/project-context?{query}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    facts = ((body or {}).get("semantic") or {}).get("facts") or []
    return [fact for fact in facts if isinstance(fact, dict)]


class FreezeError(ValueError):
    """Why a spec entry cannot become a recorded case. Closed words, no session text."""


def intake_code_digest() -> str:
    """Bind the two intake scripts in addition to the existing runtime parser stamp."""
    return _source_digest(
        {
            name: hashlib.sha256(pathlib.Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("mark_abstention.py", "score_abstention.py")
        }
    )


def _export_require(condition: bool, reason: str) -> None:
    if not condition:
        raise FreezeError(reason)


def _export_bytes(path: str, cap: int) -> bytes:
    """Read one canonical regular file from a stable opened descriptor, never a link."""
    try:
        selected = pathlib.Path(path)
        _export_require(
            selected.is_absolute() and str(selected.resolve(strict=True)) == path,
            "reviewed-export-path-invalid",
        )
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            _export_require(
                stat.S_ISREG(before.st_mode) and before.st_size <= cap,
                "reviewed-export-size-or-type-invalid",
            )
            data = handle.read(cap + 1)
            after = os.fstat(handle.fileno())
        current = os.stat(path, follow_symlinks=False)

        def signature(value: os.stat_result) -> tuple[int, int, int, int]:
            return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

        _export_require(
            len(data) == before.st_size
            and signature(before) == signature(after) == signature(current)
            and str(selected.resolve(strict=True)) == path,
            "reviewed-export-source-moved",
        )
    except (OSError, RuntimeError) as error:
        raise FreezeError("reviewed-export-source-unavailable") from error
    return data


def _export_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _export_require(key not in result, "reviewed-export-duplicate-field")
        result[key] = value
    return result


class ReviewedExports:
    """Explicit caller-reviewed finite source receipt, not authentication or model authority.

    Every use rechecks the manifest, complete file and actual settled native Stop.
    Cases retain metadata only; their own paths cannot choose or approve a source.
    """

    def __init__(self, path: str, expected_sha256: str) -> None:
        self.path = path
        self.digest = expected_sha256
        raw = _export_bytes(path, 65_536)
        _export_require(
            re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None
            and hashlib.sha256(raw).hexdigest() == expected_sha256,
            "reviewed-export-manifest-differs",
        )
        try:
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=_export_object)
        except (UnicodeError, ValueError, RecursionError) as error:
            raise FreezeError("reviewed-export-manifest-invalid") from error
        _export_require(
            isinstance(body, dict)
            and set(body) == {"v", "review", "exports"}
            and type(body["v"]) is int
            and body["v"] == 1,
            "reviewed-export-manifest-invalid",
        )
        review = body["review"]
        _export_require(
            isinstance(review, dict)
            and set(review) == {"approved", "by", "at"}
            and review["approved"] is True
            and isinstance(review["by"], str)
            and 0 < len(review["by"].strip()) <= 128
            and _epoch(review["at"]),
            "reviewed-export-review-invalid",
        )
        entries = body["exports"]
        _export_require(
            isinstance(entries, list) and 0 < len(entries) <= 32, "reviewed-export-manifest-invalid"
        )
        entries_by_sid: dict[str, Any] = {}
        paths: set[str] = set()
        for entry in entries:
            _export_require(
                isinstance(entry, dict)
                and set(entry) == {"path", "sid", "sha256"}
                and all(isinstance(value, str) for value in entry.values()),
                "reviewed-export-entry-invalid",
            )
            sid = entry["sid"]
            _export_require(
                re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", sid) is not None
                and pathlib.Path(entry["path"]).name == sid + ".jsonl"
                and sid[:8] not in entries_by_sid
                and entry["path"] not in paths
                and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is not None,
                "reviewed-export-entry-invalid",
            )
            source = _export_bytes(entry["path"], 32 * 1024 * 1024)
            _export_require(
                hashlib.sha256(source).hexdigest() == entry["sha256"],
                "reviewed-export-source-differs",
            )
            entries_by_sid[sid[:8]] = MappingProxyType(dict(entry))
            paths.add(entry["path"])
        self.entries = MappingProxyType(entries_by_sid)

    def includes(self, entry: dict[str, Any]) -> bool:
        if entry.get("harness") != "claude":
            return False
        sid = entry.get("sid")
        _export_require(
            isinstance(sid, str) and re.fullmatch(r"[0-9a-f]{8}", sid) is not None,
            "reviewed-export-case-identity-invalid",
        )
        return sid in self.entries

    def _source(  # noqa: C901, PLR0915 - independent bounded identity/lifecycle guards
        self, case: dict[str, Any], config: Any, *, frozen: bool
    ) -> tuple[str, bytes, dict[str, Any]]:
        from compass_runtime import project_context  # noqa: PLC0415 - same native source boundary

        _export_require(
            hashlib.sha256(_export_bytes(self.path, 65_536)).hexdigest() == self.digest,
            "reviewed-export-manifest-differs",
        )
        _export_require(self.includes(case), "reviewed-export-entry-missing")
        entry = self.entries[str(case["sid"])]
        _export_require(
            frozen or not case.get("transcript") or case["transcript"] == entry["path"],
            "reviewed-export-entry-differs",
        )
        raw = _export_bytes(entry["path"], project_context.FINAL_WORDS_SCAN_MAX_BYTES)
        _export_require(
            hashlib.sha256(raw).hexdigest() == entry["sha256"], "reviewed-export-source-differs"
        )
        capture = case.get("captured_at")
        snapshot = case.get("row_snapshot") if frozen else case.get("row")
        _export_require(
            _epoch(capture)
            and isinstance(snapshot, dict)
            and snapshot.get("state") == "idle"
            and snapshot.get("ended_at") is None
            and _epoch(snapshot.get("finished_at"))
            and float(capture) >= float(snapshot["finished_at"]) + float(config.reading_settle_sec),
            "reviewed-export-lifecycle-invalid",
        )
        snapshot = cast("dict[str, Any]", snapshot)
        capture = cast("float", capture)
        _export_require(
            not frozen
            or (
                snapshot.get("harness") == "claude"
                and snapshot.get("sid") == case["sid"]
                and case.get("id") == _case_id("claude", str(case["sid"]))
            ),
            "reviewed-export-case-identity-invalid",
        )
        stop_at = snapshot["finished_at"]
        prefix = bytearray()
        native: list[dict[str, Any]] = []
        future = False
        for line in io.BytesIO(raw):
            _export_require(
                len(line) <= project_context.FINAL_WORDS_RECORD_MAX_BYTES,
                "reviewed-export-record-too-large",
            )
            _export_require(
                b"\r" not in line.removesuffix(b"\n").removesuffix(b"\r"),
                "reviewed-export-record-invalid",
            )
            try:
                record = json.loads(line.decode("utf-8"), object_pairs_hook=_export_object)
            except (UnicodeError, ValueError, RecursionError) as error:
                raise FreezeError("reviewed-export-record-invalid") from error
            _export_require(isinstance(record, dict), "reviewed-export-record-invalid")
            named = record.get("sessionId")
            _export_require(
                named is None or named == entry["sid"], "reviewed-export-full-identity-differs"
            )
            at = project_context._record_timestamp(record)  # noqa: SLF001 - native timestamp contract
            future = future or (at is not None and at > float(capture))
            if not future:
                prefix.extend(line)
                native.append(record)
        by_id: dict[str, dict[str, Any]] = {}
        positions: dict[str, int] = {}
        latest: dict[str, Any] | None = None
        stop: dict[str, Any] | None = None
        for position, record in enumerate(native):
            uuid = record.get("uuid")
            if uuid is not None:
                _export_require(
                    isinstance(uuid, str) and bool(uuid) and len(uuid) <= 128 and uuid not in by_id,
                    "reviewed-export-native-uuid-invalid",
                )
                by_id[uuid] = record
                positions[uuid] = position
            kind = record.get("type")
            at = project_context._record_timestamp(record)  # noqa: SLF001
            if kind in {"user", "assistant"}:
                message = record.get("message")
                _export_require(
                    record.get("sessionId") == entry["sid"]
                    and _epoch(at)
                    and isinstance(uuid, str)
                    and isinstance(message, dict)
                    and message.get("role") == kind,
                    "reviewed-export-conversation-invalid",
                )
                at = cast("float", at)
                _export_require(
                    stop is None and float(at) <= float(stop_at), "reviewed-export-continued"
                )
                latest = record
            if kind == "system" and record.get("subtype") == "stop_hook_summary" and at == stop_at:
                _export_require(
                    stop is None
                    and isinstance(uuid, str)
                    and record.get("sessionId") == entry["sid"]
                    and record.get("isSidechain") is False
                    and record.get("preventedContinuation") is False
                    and record.get("hookLabel", "Stop") == "Stop",
                    "reviewed-export-stop-invalid",
                )
                message = (latest or {}).get("message")
                _export_require(
                    isinstance(message, dict)
                    and latest is not None
                    and latest.get("type") == "assistant"
                    and message.get("role") == "assistant"
                    and message.get("stop_reason") == "end_turn"
                    and latest.get("isMeta") is not True
                    and latest.get("isSidechain") is False
                    and not latest.get("agentId")
                    and record.get("parentUuid") == latest.get("uuid")
                    and project_context._agent_message_event(  # noqa: SLF001 - same native eligibility, not selection
                        config, latest, "claude", str(case["sid"])
                    )
                    is not None,
                    "reviewed-export-final-invalid",
                )
                stop = record
        _export_require(stop is not None and latest is not None, "reviewed-export-stop-missing")
        stop = cast("dict[str, Any]", stop)
        latest = cast("dict[str, Any]", latest)
        cursor: dict[str, Any] | None = latest
        visited: set[str] = set()
        person = False
        while cursor is not None:
            uuid = str(cursor.get("uuid") or "")
            _export_require(uuid not in visited, "reviewed-export-parent-invalid")
            visited.add(uuid)
            message = cursor.get("message")
            if (
                cursor.get("type") == "user"
                and cursor.get("isMeta") is not True
                and cursor.get("isSidechain") is False
            ):
                content = message.get("content") if isinstance(message, dict) else None
                if (
                    (isinstance(content, str) and content.strip())
                    or (
                        isinstance(content, list)
                        and any(
                            isinstance(block, dict)
                            and block.get("type") == "text"
                            and isinstance(block.get("text"), str)
                            and block["text"].strip()
                            for block in content
                        )
                    )
                ) and project_context._instruction_event(  # noqa: SLF001 - same native person event parser
                    config, cursor, "claude", str(case["sid"])
                ) is not None:
                    person = True
                    break
            parent = cursor.get("parentUuid")
            _export_require(
                parent is None or (isinstance(parent, str) and parent in by_id),
                "reviewed-export-parent-invalid",
            )
            if parent:
                _export_require(
                    positions[parent] < positions[uuid],
                    "reviewed-export-parent-invalid",
                )
            cursor = by_id.get(parent) if parent else None
        _export_require(person, "reviewed-export-parent-invalid")
        proof = {
            "v": 1,
            "manifest_sha256": self.digest,
            "entry_sha256": _source_digest(dict(entry)),
            "full_sid": entry["sid"],
            "source_sha256": entry["sha256"],
            "prefix_bytes": len(prefix),
            "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
            "stop_uuid": stop["uuid"],
            "final_uuid": latest["uuid"],
            "stop_at": stop_at,
            "capture_at": capture,
            "parser_sha256": parser_digest(),
            "intake_code_sha256": intake_code_digest(),
        }
        return entry["path"], bytes(prefix), proof

    def receipt(self, case: dict[str, Any], proof: dict[str, Any]) -> dict[str, Any]:
        return {
            **proof,
            "case_sha256": _source_digest(
                {
                    key: value
                    for key, value in case.items()
                    if key not in {"reviewed_export", "stop_vouched_by", "demoted"}
                }
            ),
        }

    @contextlib.contextmanager
    def source(
        self, case: dict[str, Any], config: Any, *, frozen: bool = True
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        path, prefix, proof = self._source(case, config, frozen=frozen)
        if frozen:
            _export_require(
                case.get("reviewed_export") == self.receipt(case, proof),
                "reviewed-export-receipt-differs",
            )
        with tempfile.TemporaryDirectory(prefix="compass-reviewed-export-") as folder:
            owned = os.path.join(folder, os.path.basename(path))
            descriptor = os.open(owned, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(prefix)
            yield owned, proof
        self._source(case, config, frozen=frozen)

    def validate(self, case: dict[str, Any], config: Any) -> None:
        with self.source(case, config) as (path, _proof):
            _export_require(
                not content_refusal(config, case, path), "reviewed-export-content-differs"
            )

    def freeze(self, config: Any, entry: dict[str, Any]) -> dict[str, Any]:
        from compass_runtime import project_context  # noqa: PLC0415 - native source reconstruction

        _export_require(
            isinstance(entry.get("intent"), dict) and bool(case_lines(entry)), "no-outcome-line"
        )
        with self.source(entry, config, frozen=False) as (path, proof):
            captured, sid = float(entry["captured_at"]), str(entry["sid"])
            checks, press = project_context.frozen_claude_checks(config, path, sid, until=captured)
            size = capture_prefix(path, captured)
            _, people = project_context.frozen_claude_user_messages(
                config, path, sid, until=captured, size=size
            )
            _, agents = project_context.frozen_claude_agent_messages(
                config, path, sid, until=captured, size=size
            )
            case = {
                "id": _case_id("claude", sid),
                "harness": "claude",
                "sid": sid,
                "origin": "recorded",
                "project": entry.get("project"),
                "title": entry.get("title"),
                "captured_at": captured,
                "row_snapshot": {
                    "harness": "claude",
                    "sid": sid,
                    "state": "idle",
                    "finished_at": entry["row"]["finished_at"],
                    "ended_at": None,
                },
                "intent": entry["intent"],
                "lifecycle_from": "reviewed-export",
                "unconfirmed": [],
                "transcript_bytes": size,
                "transcript_cut": "capture",
                "parser": parser_digest(),
                "tool_output": {
                    "tails": dict(press.tails),
                    "changed_after": sorted(map(list, press.changed_after)),
                    "read_incomplete": sorted(map(list, press.read_incomplete)),
                },
                "producer_facts": [*people, *agents, *checks],
            }
            case["production_reading"] = _production_capture(config, case, path)
            case["reviewed_export"] = self.receipt(case, proof)
        return case


def load_reviewed_exports(path: str | None, expected_sha256: str | None) -> ReviewedExports | None:
    """Only paired explicit controller inputs create the trusted export context."""
    if not path and not expected_sha256:
        return None
    if not path or not expected_sha256:
        raise FreezeError("reviewed-export-path-and-digest-required")
    return ReviewedExports(path, expected_sha256)


def revalidate_reviewed_export(
    case: dict[str, Any], resolver: ReviewedExports | None, config: Any
) -> None:
    """A receipt has no admission or source-serving power without the explicit context."""
    if "reviewed_export" not in case:
        return
    if resolver is None:
        raise FreezeError("reviewed-export-opt-in-required")
    resolver.validate(case, config)


def _inside(path: str, root: str | None) -> bool:
    if root is None:
        return False
    real, base = os.path.realpath(path), os.path.realpath(root)
    return real.startswith(base + os.sep)


def _transcript_is_the_session(path: str, sid: str) -> bool:
    """Whether every record in it names this session, and at least one does."""
    seen = False
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                named = record.get("sessionId") if isinstance(record, dict) else None
                if named is None:
                    continue
                if not isinstance(named, str) or not named.startswith(sid):
                    return False
                seen = True
    except OSError:
        return False
    return seen and len(sid) >= 8


def _same(a: Any, b: Any) -> bool:
    return _epoch(a) and _epoch(b) and abs(float(a) - float(b)) < 1e-3


def _lifecycle_recorded(
    snapshot: dict[str, Any],
    captured: float,
    observations: Any,
    ends: Any,
    transcript: str = "",
) -> str | None:
    """Which of the machine's records vouch for the lifecycle the spec claims, if any.

    A running row needs a `working` observation at the capture itself; an end
    needs the ends store's stamp; a turn stop needs an `idle` observation at
    the stop. Anything else is hand-typed. Returns `history` for those.

    A Claude Code turn stop older than the history store's oldest observation
    is out of the store's reach: it is capped and rolls, so a stop it once held
    or never saw reads the same. That stop alone may be vouched by the
    transcript's own Stop-hook record at the stop, and returns `transcript`
    (owner ruling, 2026-10-01, DRC-4666). A stop the store still reaches never
    falls back, so its silence there stays a refusal.
    """
    key = (snapshot["harness"], snapshot["sid"])
    mine = [
        o for o in observations if isinstance(o, dict) and (o.get("harness"), o.get("sid")) == key
    ]
    if snapshot.get("ended_at") is not None:
        return (
            "history"
            if any(
                isinstance(e, dict)
                and (e.get("harness"), e.get("sid")) == key
                and _same(e.get("at"), snapshot["ended_at"])
                for e in ends
            )
            else None
        )
    if snapshot.get("state") == "working":
        return (
            "history"
            if any(
                o.get("state") == "working" and _same(o.get("last_activity"), captured)
                for o in mine
            )
            else None
        )
    if snapshot.get("state") != "idle" or snapshot.get("finished_at") is None:
        return None
    stop = snapshot["finished_at"]
    if any(o.get("state") == "idle" and _same(o.get("last_activity"), stop) for o in mine):
        return "history"
    floor = _history_floor(observations)
    if (
        snapshot["harness"] == "claude"
        and transcript
        and floor is not None
        and _epoch(stop)
        and float(stop) < floor
        and _transcript_stop(transcript, str(snapshot["sid"]), float(stop))
    ):
        return "transcript"
    return None


def _history_floor(observations: Any) -> float | None:
    """The oldest moment the history store still holds, across every session."""
    stamps = [
        float(o["last_activity"])
        for o in observations
        if isinstance(o, dict) and _epoch(o.get("last_activity"))
    ]
    return min(stamps) if stamps else None


def _transcript_stop(transcript: str, sid: str, stop: float) -> bool:
    """Whether the transcript records this session's turn ending at `stop`.

    Claude Code writes a `stop_hook_summary` when its Stop hooks run, the event
    the dashboard stamps a turn stop from. The board stamps the hook's arrival,
    not the record: measured 2026-10-01 over the store's 700 observed stops,
    none sat within a millisecond of its record and 217 within a second, the
    record about 115 ms earlier. So `finished_at` must be the record's own
    stamp, copied from the transcript, and a stop with no record is refused.
    Only a summary whose newest `user` or `assistant` record before it is an
    assistant reply is a stop: a Stop hook that blocks the stop, or a goal
    check not met, writes an `isMeta` user record first and keeps the turn
    going (verifier S1). `preventedContinuation` true is a hook ending the
    turn, which is a stop. A subagent's record is not the session's, and a
    summary labelled for any hooks but Stop is not a stop (verifier S2). `sid` is
    matched as a prefix, as `_transcript_is_the_session` does, because a packet
    names a Claude Code session by the eight characters the board publishes.
    """
    if len(sid) < 8:
        return False
    from compass_runtime import project_context  # noqa: PLC0415 - see `_reading`

    try:
        with open(transcript, encoding="utf-8", errors="replace") as handle:
            conversation: str | None = None
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                after = conversation
                if record.get("type") in ("user", "assistant"):  # any JSON value
                    conversation = record["type"]
                if not (
                    after == "assistant"
                    and record.get("type") == "system"
                    and record.get("subtype") == "stop_hook_summary"
                    and record.get("isSidechain") is False
                    and isinstance(record.get("preventedContinuation"), bool)
                    and isinstance(record.get("sessionId"), str)
                    and record.get("hookLabel", "Stop") == "Stop"
                    and record["sessionId"].startswith(sid)
                ):
                    continue
                if _same(project_context._record_timestamp(record), stop):  # noqa: SLF001
                    return True
    except OSError:
        return False
    return False


def _frozen_checks(
    config: Any,
    entry: dict[str, Any],
    sid: str,
    captured: float,
    unconfirmed: list[str],
    snapshot: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], int, list[dict[str, Any]]]:
    """A Claude Code case's checks, length and user messages, as they stood at the capture.

    Notes in `unconfirmed` what the transcript cannot vouch for. The user
    messages are the board's own derivation over the bounded tail a press at
    `captured_at` read, which ended where the transcript then ended. Read from
    today's file instead, a session that ran on past the board's 400 KB tail
    after the capture left none of the reader's words in the case (measured
    2026-10-01: the supported-departure correction sat 750 KB from the end).
    """
    transcript = str(entry.get("transcript") or _transcript_index().get(sid[:8]) or "")
    if not transcript or not os.path.isfile(transcript):
        raise FreezeError("no-transcript")
    if not _inside(transcript, CLAUDE_PROJECTS_ROOT):
        unconfirmed.append("transcript-outside-projects")
    if not _transcript_is_the_session(transcript, sid):
        unconfirmed.append("transcript-other-session")
    from compass_runtime import project_context  # noqa: PLC0415 - see `_reading`

    size = capture_prefix(transcript, captured)
    stop = _stop(snapshot)
    if stop is not None and project_context.claude_activity_between(transcript, stop, captured):
        raise FreezeError("activity-after-stop")
    try:
        checks, press = project_context.frozen_claude_checks(
            config, transcript, sid, until=captured
        )
    except project_context.FrozenCheckCutoffUnreachableError as error:
        raise FreezeError("check-cutoff-unreachable") from error
    _whole, said = project_context.frozen_claude_user_messages(
        config, transcript, sid, until=captured, size=size
    )
    return (
        checks,
        {
            "tails": dict(press.tails),
            "changed_after": sorted([list(pair) for pair in press.changed_after]),
            "read_incomplete": sorted([list(pair) for pair in press.read_incomplete]),
        },
        size,
        said,
    )


def capture_prefix(transcript: str, captured: float) -> int:
    """The transcript's length in bytes as it stood at `captured`.

    Everything before the first line stamped after the capture, the cut the
    check scan makes too: an append-only file holds nothing written later
    before that line, and a line stamped earlier after it was written later.
    """
    from compass_runtime import project_context  # noqa: PLC0415 - see `_reading`

    offset = 0
    with open(transcript, "rb") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except (ValueError, RecursionError):
                record = None
            at = (
                project_context._record_timestamp(record)  # noqa: SLF001
                if isinstance(record, dict)
                else None
            )
            if at is not None and at > captured:
                return offset
            offset += len(line)
    return offset


# The files whose code turns a transcript into the facts and checks a case holds
# (review, Scoring F7). A packet frozen under other code is named as such
# rather than read as tampered, since every case would then differ.
_PARSER_FILES = ("io.py", "project_context.py", "reading.py")


def parser_digest() -> str:
    """Versioned AST digest: comments/layout do not change the derivation contract.

    Literal strings, expressions and control flow remain part of the stamp.
    The format prefix keeps old byte stamps conservatively incompatible;
    neither frozen packets nor owner marks are rewritten to fit new code.
    """
    digest = hashlib.sha256(b"compass-parser-ast-v1\0")
    for name in _PARSER_FILES:
        with open(os.path.join(_SKILL, "compass_runtime", name), "rb") as handle:
            tree = ast.parse(handle.read(), filename=name)
        digest.update(name.encode() + b"\0")
        digest.update(ast.dump(tree, include_attributes=False).encode() + b"\0")
    return digest.hexdigest()


def _stop(snapshot: dict[str, Any]) -> float | None:
    """The recorded end or turn stop a capture follows, if the row has one."""
    for field in ("ended_at", "finished_at"):
        if _epoch(snapshot.get(field)):
            return float(snapshot[field])
    return None


# Keep the ordered provenance refusals together: the parser-stamp check must
# precede any transcript read, and an unreachable check cutoff has its own reason.
def content_refusal(config: Any, case: dict[str, Any], transcript: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915 - ordered source refusals
    """Why a Claude Code case's contents are not what its transcript holds (DRC-4711).

    Rebuilt as the freeze built them, at the case's own `captured_at`, so turns
    appended since are not a mismatch, and compared as the ledger rows the
    producer reads. A capture with a user or assistant message between its
    stop and itself is not the moment the stop recorded (`activity-after-stop`).
    The checks and the press reads must be exactly the transcript's, since dropping a failed
    check changes a verdict as surely as inventing a pass. The user messages
    must be the newest ones up to the capture, in order, none missing between
    and none twice, and at least as many as the board's bounded tail reads of
    the file as it stood at the freeze, its first `transcript_bytes` bytes:
    the board read a file no larger, so its tail reached at least that far
    back. Older ones may be absent. A transcript now shorter than that size,
    or a case that records none, is `transcript-truncated`.
    """
    if case.get("parser") != parser_digest():
        return ["frozen-on-another-parser"]
    size = case.get("transcript_bytes")
    try:
        on_disk = os.path.getsize(transcript)
    except OSError:
        return ["transcript-missing"]
    if type(size) is not int or size < 0 or size > on_disk:
        return ["transcript-truncated"]
    # A packet frozen at the capture's own length must still name that length,
    # and no packet may name less: a shorter one would shrink the tail and
    # excuse dropped messages. Every earlier freeze recorded at least that much,
    # so the floor holds for packets with no `transcript_cut` too.
    prefix = capture_prefix(transcript, float(case["captured_at"]))
    cut_differs = size < prefix or (case.get("transcript_cut") == "capture" and size != prefix)
    reading = _reading()
    sid = str(case.get("sid") or "")
    captured = float(case["captured_at"])
    from compass_runtime import project_context  # noqa: PLC0415 - see `_reading`

    stop = _stop(case.get("row_snapshot") or {})
    production = "production_reading" in case
    agents: list[dict[str, Any]] = []
    agent_tail: list[dict[str, Any]] = []
    try:
        checks, press = project_context.frozen_claude_checks(
            config, transcript, sid, until=captured
        )
        held, tail = project_context.frozen_claude_user_messages(
            config, transcript, sid, until=captured, size=size
        )
        if production:
            agents, agent_tail = project_context.frozen_claude_agent_messages(
                config, transcript, sid, until=captured, size=size
            )
        moved = stop is not None and project_context.claude_activity_between(
            transcript, stop, captured
        )
    except project_context.FrozenCheckCutoffUnreachableError:
        return ["check-cutoff-unreachable"]
    except OSError:
        return ["transcript-missing"]
    reasons: list[str] = ["activity-after-stop"] if moved else []
    if cut_differs:
        reasons.append("transcript-bytes-differ")
    tails = dict(press.tails)
    frozen = {
        "tails": tails,
        "changed_after": sorted([list(pair) for pair in press.changed_after]),
        "read_incomplete": sorted([list(pair) for pair in press.read_incomplete]),
    }
    captured_output = case.get("tool_output")
    if isinstance(captured_output, dict):
        captured_output = {"read_incomplete": [], **captured_output}
    if json.loads(json.dumps(frozen)) != captured_output:
        reasons.append("tool-output-differs")
    facts = [f for f in case.get("producer_facts") or () if isinstance(f, dict)]
    tool = reading.TOOL_REPORT_TYPE

    def rows(these: list[dict[str, Any]], tails: dict[str, str] | None) -> list[Any]:
        return list(
            reading.build_ledger(
                json.loads(json.dumps(these)),
                "claude",
                sid,
                tool_output=tails,
                changed_after=press.changed_after,
                read_incomplete=press.read_incomplete,
                read_agent_words=production,
            )
        )

    if rows([f for f in facts if f.get("type") == tool], tails) != rows(checks, tails):
        reasons.append("checks-differ")
    mine = rows(
        [
            f
            for f in facts
            if f.get("type") != tool
            and (not production or f.get("type") != reading.AGENT_MESSAGE_TYPE)
        ],
        None,
    )
    whole = rows(held, None)
    newest = whole[len(whole) - len(mine) :] if mine else []
    if (
        mine != newest
        or len(mine) < len(rows(tail, None))
        or (production and mine != rows(tail, None))
    ):
        reasons.append("facts-unconfirmed")
    if production:
        mine_agents = rows([f for f in facts if f.get("type") == reading.AGENT_MESSAGE_TYPE], None)
        whole_agents = rows(agents, None)
        newest_agents = whole_agents[len(whole_agents) - len(mine_agents) :] if mine_agents else []
        if mine_agents != newest_agents or mine_agents != rows(agent_tail, None):
            reasons.append("agent-facts-unconfirmed")
        try:
            if _production_capture(config, case, transcript) != case["production_reading"]:
                reasons.append("production-source-differs")
        except (FreezeError, OSError, KeyError, TypeError, ValueError):
            reasons.append("production-source-differs")
    return reasons


def provenance(  # noqa: C901, PLR0912 - export exception precedes unchanged canonical guards
    case: dict[str, Any],
    *,
    observations: Any,
    ends: Any,
    index: dict[str, str],
    config: Any = None,
    reviewed_exports: ReviewedExports | None = None,
) -> list[str]:
    """Why a frozen case cannot be called recorded, from the machine's own records.

    The freeze's checks, repeated at score time, because the packet is
    hand-editable and the scorer read `origin` as written (V2). `index` maps a
    Claude Code sid's first eight characters to its transcript, as
    `_transcript_index` builds it from `CLAUDE_PROJECTS_ROOT`. A Claude Code
    case's contents are rebuilt from that transcript too (`content_refusal`),
    under `config`, the runtime config the freeze would build when none is given.
    """
    if "reviewed_export" in case:
        if reviewed_exports is None:
            return ["reviewed-export-opt-in-required"]
        try:
            reviewed_exports.validate(case, config if config is not None else _runtime_config())
        except (FreezeError, OSError, ValueError, KeyError, TypeError):
            return ["reviewed-export-unconfirmed"]
        return []
    snapshot = case.get("row_snapshot")
    captured = case.get("captured_at")
    if not isinstance(snapshot, dict) or not _epoch(captured):
        return ["lifecycle-unconfirmed"]
    reasons: list[str] = []
    # The freeze refuses a capture taken before its stop or end settled; the
    # packet is hand-editable, so the scorer refuses the same, or a lifecycle
    # moved past the capture would be vouched by a stop that came later.
    settle = float((config if config is not None else _runtime_config()).reading_settle_sec)
    for field in ("ended_at", "finished_at"):
        stamp = snapshot.get(field)
        if stamp is not None and (not _epoch(stamp) or float(captured) < float(stamp) + settle):
            reasons.append("captured-before-settled")
            break
    sid = str(case.get("sid") or "")
    transcript = index.get(sid[:8]) if case.get("harness") == "claude" else None
    if not _lifecycle_recorded(snapshot, float(captured), observations, ends, transcript or ""):
        reasons.append("lifecycle-unconfirmed")
    if case.get("harness") == "claude":
        if not transcript:
            reasons.append("transcript-missing")
        else:
            if not _inside(transcript, CLAUDE_PROJECTS_ROOT):
                reasons.append("transcript-outside-projects")
            if not _transcript_is_the_session(transcript, sid):
                reasons.append("transcript-other-session")
            if not reasons:
                reasons.extend(
                    content_refusal(
                        config if config is not None else _runtime_config(), case, transcript
                    )
                )
    return reasons


def make_vouch(
    *,
    observations: Any,
    ends: Any,
    index: dict[str, str],
    config: Any = None,
    reviewed_exports: ReviewedExports | None = None,
) -> Any:
    """`provenance` bound to one set of records, for the scorer to call per case."""

    def vouch(case: Any) -> list[str]:
        return provenance(
            dict(case),
            observations=observations,
            ends=ends,
            index=index,
            config=config,
            reviewed_exports=reviewed_exports,
        )

    def lifecycle(case: Any) -> str | None:
        """Which record vouched for the case's lifecycle, derived here, never read from it."""
        if "reviewed_export" in case:
            return "reviewed-export" if reviewed_exports is not None and not vouch(case) else None
        snapshot, captured = case.get("row_snapshot"), case.get("captured_at")
        if not isinstance(snapshot, dict) or not _epoch(captured):
            return None
        sid = str(case.get("sid") or "")
        transcript = index.get(sid[:8]) if case.get("harness") == "claude" else None
        return _lifecycle_recorded(snapshot, float(captured), observations, ends, transcript or "")

    vouch.lifecycle = lifecycle  # type: ignore[attr-defined]
    return vouch


def machine_vouch(
    store_home: str | None, *, reviewed_exports: ReviewedExports | None = None
) -> Any:
    """`make_vouch` over this machine's history, ends and Claude Code transcripts."""
    if reviewed_exports is not None:
        exported = make_vouch(
            observations=(),
            ends=(),
            index={},
            config=_runtime_config(),
            reviewed_exports=reviewed_exports,
        )
        canonical: Any = None

        def selected(case: dict[str, Any]) -> Any:
            nonlocal canonical
            if "reviewed_export" in case:
                return exported
            if canonical is None:
                canonical = machine_vouch(store_home)
            return canonical

        def vouch(case: dict[str, Any]) -> list[str]:
            result: list[str] = selected(case)(case)
            return result

        vouch.lifecycle = lambda case: selected(case).lifecycle(case)  # type: ignore[attr-defined]
        return vouch
    observations, ends = _observed_stores(store_home)
    return make_vouch(
        observations=observations,
        ends=ends,
        index=_transcript_index(),
        config=_runtime_config(),
        reviewed_exports=reviewed_exports,
    )


def freeze_case(  # noqa: C901 - retain legacy provenance order with opt-in source capture
    config: Any,
    entry: dict[str, Any],
    facts: list[dict[str, Any]],
    *,
    observations: Any = (),
    ends: Any = (),
    production_reading: bool = False,
    reviewed_exports: ReviewedExports | None = None,
) -> dict[str, Any]:
    """One recorded case, frozen as the session stood at `captured_at`.

    The case is `recorded` only when the machine vouches for it: a Claude Code
    transcript inside `CLAUDE_PROJECTS_ROOT` whose records name this session,
    and a lifecycle the dashboard's history or ends store observed
    (`observations`, `ends`), or, for a turn stop the history store has rolled
    past, the transcript's own Stop-hook record (`_lifecycle_recorded`).
    Anything short of that is `synthetic`, with the
    reasons listed in `unconfirmed`, and never counts toward the floor.

    Facts are kept only where dated at or before the capture. A Claude Code
    check is never one of them: its latest run, earlier failure and later
    change are computed over the whole transcript, so it is rebuilt from the
    transcript as it stood (`project_context.frozen_claude_checks`), with the
    output tails and changed-after pairs a press at that moment carried.

    A row may be a recorded history `working` observation, which is how a
    Codex case exists at all: Codex has no session-end hook and is never read
    at a turn stop (DRC-4666, decisions of 2026-09-24).
    """
    if reviewed_exports is not None and reviewed_exports.includes(entry):
        if not production_reading:
            raise FreezeError("reviewed-export-production-required")
        return reviewed_exports.freeze(config, entry)
    harness, sid = str(entry.get("harness") or ""), str(entry.get("sid") or "")
    at = entry.get("captured_at")
    if not harness or not sid:
        raise FreezeError("no-identity")
    if not _epoch(at):
        raise FreezeError("bad-captured-at")
    captured = float(at)
    raw_row = entry.get("row")
    row: dict[str, Any] = raw_row if isinstance(raw_row, dict) else {}
    snapshot = {
        "harness": harness,
        "sid": sid,
        "state": row.get("state"),
        "finished_at": row.get("finished_at"),
        "ended_at": row.get("ended_at"),
    }
    settle = float(config.reading_settle_sec)
    for field in ("ended_at", "finished_at"):
        stamp = snapshot[field]
        if stamp is not None and (not _epoch(stamp) or captured < float(stamp) + settle):
            raise FreezeError("captured-before-settled")
    intent = entry.get("intent")
    if not isinstance(intent, dict) or not case_lines({"intent": intent}):
        raise FreezeError("no-outcome-line")
    kept = [
        fact
        for fact in facts
        if isinstance(fact.get("source_session"), dict)
        and (fact["source_session"].get("harness"), fact["source_session"].get("sid"))
        == (harness, sid)
        and fact.get("type") != _reading().TOOL_REPORT_TYPE
        and _epoch(fact.get("at"))
        and fact["at"] <= captured
    ]
    unconfirmed: list[str] = []
    transcript = (
        str(entry.get("transcript") or _transcript_index().get(sid[:8]) or "")
        if harness == "claude"
        else ""
    )
    lifecycle_from = _lifecycle_recorded(snapshot, captured, observations, ends, transcript)
    if lifecycle_from is None:
        unconfirmed.append("lifecycle-unconfirmed")
    case: dict[str, Any] = {
        "id": _case_id(harness, sid),
        "harness": harness,
        "sid": sid,
        "origin": "recorded",
        "project": entry.get("project"),
        "title": entry.get("title"),
        "captured_at": captured,
        "row_snapshot": snapshot,
        "intent": intent,
        "lifecycle_from": lifecycle_from,
    }
    if harness == "claude":
        checks, case["tool_output"], case["transcript_bytes"], said = _frozen_checks(
            config, entry, sid, captured, unconfirmed, snapshot
        )
        # The reader's words as a press at the capture read them, not the board's
        # tail of today's file (`_frozen_checks`); `transcript_cut` pins the length.
        kept = [*said, *checks]
        case["transcript_cut"] = "capture"
        case["parser"] = parser_digest()
        if production_reading:
            from compass_runtime import project_context  # noqa: PLC0415 - see `_reading`

            _whole, agents = project_context.frozen_claude_agent_messages(
                config, transcript, sid, until=captured, size=case["transcript_bytes"]
            )
            kept = [*said, *agents, *checks]
    case["producer_facts"] = kept
    if production_reading:
        case["production_reading"] = _production_capture(config, case, transcript)
    case["unconfirmed"] = unconfirmed
    if unconfirmed:
        case["origin"] = ORIGIN_SYNTHETIC
    return case


def _observed_stores(store_home: str | None) -> tuple[Any, Any]:
    """The dashboard's history observations and session ends, read from `store_home`."""
    if store_home is None:
        raise FreezeError("account-home-unavailable")
    _reading()
    from compass_runtime import config as config_mod  # noqa: PLC0415 - see `_reading`
    from compass_runtime import ends, history  # noqa: PLC0415 - see `_reading`

    config = config_mod.build_runtime_config(
        environ={**os.environ, "COMPASS_HOME": store_home},
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=pathlib.Path(_SKILL, "server.py"),
    )
    return history.load(config)[0], ends.load(config)


def freeze(  # noqa: PLR0911 - refuse each distinct source/identity preparation failure
    port: int,
    spec_path: str,
    *,
    force: bool = False,
    store_home: str = "",
    production_reading: bool = False,
    reviewed_exports: ReviewedExports | None = None,
) -> int:
    """Write a format 5 packet from a spec of recorded moments. Spends nothing.

    The spec is local and hand-written: per case the harness, sid, project,
    `captured_at`, the recorded `row` lifecycle, the `intent` and, for Claude
    Code, optionally the transcript path.
    """
    spec = _load(spec_path)
    entries = spec.get("cases") if isinstance(spec.get("cases"), list) else []
    if not entries:
        print(f"No cases in {spec_path}.")
        return 1
    if _marks(_load(MARKS_PATH)) and not force:
        print("Marks already exist here and would belong to a different packet.")
        print("Use a fresh COMPASS_HOME, or --force to write the packet anyway.")
        return 1
    config = _runtime_config()
    try:
        exported_entries = [
            reviewed_exports is not None
            and isinstance(entry, dict)
            and reviewed_exports.includes(entry)
            for entry in entries
        ]
    except FreezeError as error:
        print(f"Refused: {error}. Nothing was written.")
        return 1
    all_exported = reviewed_exports is not None and all(exported_entries)
    observations, ends = ((), ()) if all_exported else _observed_stores(store_home or STORE_HOME)
    cases: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            print(f"Case {index}: not an object")
            return 1
        exported = exported_entries[index - 1]
        facts = (
            []
            if exported
            else _session_facts(
                port,
                str(entry.get("project") or ""),
                str(entry.get("harness")),
                str(entry.get("sid")),
            )
        )
        if facts is None:
            print(f"Case {index}: the board on port {port} did not answer for it")
            return 1
        try:
            cases.append(
                freeze_case(
                    config,
                    entry,
                    facts,
                    observations=observations,
                    ends=ends,
                    production_reading=production_reading,
                    reviewed_exports=reviewed_exports,
                )
            )
        except FreezeError as error:
            print(f"Case {index}: {error}")
            return 1
    if reviewed_exports is not None and len({case["id"] for case in cases}) != len(cases):
        print("Duplicate case identities in reviewed-export freeze. Nothing was written.")
        return 1
    _write(CASES_PATH, {"v": FORMAT_INTENT, "cases": cases})
    synthetic = sum(1 for case in cases if case["origin"] == ORIGIN_SYNTHETIC)
    print(f"Froze {len(cases)} cases into {CASES_PATH} (stays on this machine).")
    if synthetic:
        print(f"  {synthetic} are synthetic: the machine's records do not vouch for them.")
    return 0


def _write(path: str, body: dict[str, Any]) -> None:
    """Atomically, because this file is somebody's evening.

    v2 truncated in place: a Ctrl-C between `open` and `dump` left a zero length
    file and the next run died on it with no backup.
    """
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    # Its own temporary file: two runs sharing one `.tmp` crashed in review.
    descriptor, tmp = tempfile.mkstemp(prefix=".write-", suffix=".tmp", dir=os.path.dirname(path))
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(body, handle, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _load(path: str) -> dict[str, Any]:
    """Never a traceback. This reads files a person can edit or interrupt."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except (OSError, ValueError) as error:
        print(f"Could not read {path}: {error}")
        return {}
    if not isinstance(body, dict):
        print(f"{path} is not an object, so it is not one of ours. Ignoring it.")
        return {}
    return body


def _marks(body: dict[str, Any]) -> dict[str, Any]:
    """Only the entries that carry both columns. A half written one is not a mark."""
    raw = body.get("marks")
    if not isinstance(raw, dict):
        return {}
    return {
        k: v
        for k, v in raw.items()
        if isinstance(v, dict)
        and isinstance(v.get("goal"), str)
        and ("output" in v or "line_1" in v)
    }


def _ask(prompt: str) -> str | None:
    """One call, no default. Returns None if the marker wants to stop."""
    while True:
        try:
            reply = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if reply in {"y", "yes"}:
            return "judge"
        if reply in {"n", "no"}:
            return "abstain"
        if reply in {"s", "skip"}:
            return "skip"
        if reply in {"q", "quit"}:
            return None
        print("  y = it should judge, n = it should refuse, s = skip, q = stop")


def _short(text: str, limit: int) -> str:
    """Cut at a word boundary, and say that it was cut.

    A mid-word cut reads as a typo and a silent one reads as the whole ask.
    """
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " ..."


def _headline(case: dict[str, Any]) -> str:
    """The ask, reduced to something a question can carry.

    A pasted plan is hundreds of words and its first line is a preamble, so the
    first sentence is taken where there is one and the derived title otherwise.
    """
    asked = " ".join(str(case.get("asked_for") or "").split())
    if not asked:
        return str(case.get("title") or "what you asked")
    first = asked.split(". ")[0]
    return _short(first if 12 <= len(first) <= 110 else asked, 110)


def _show(case: dict[str, Any], position: str) -> None:
    """One self contained screen: what was asked, what is recorded, the question.

    The question used to name a GOAL defined once in a header, which by case 20
    was far off the top of the terminal. A marker cannot judge against a
    sentence they cannot see, so the ask is restated on every screen, in the
    session's own words rather than a constant.
    """
    asked = str(case.get("asked_for") or "")
    latest = str(case.get("directive") or "")
    print("\n" + "=" * 72)
    stands = case.get("stands_for") or 1
    also = f"   (this shape covers {stands} sessions)" if stands > 1 else ""
    harness = case.get("harness") or "unknown harness"
    print(f"  {position}   {harness} - {case.get('project') or 'no project'}{also}")

    print("\n  YOU ASKED IT TO")
    if asked:
        print(f"    {_short(asked, 260)}")
    elif case.get("title"):
        print(f"    {case.get('title')}   (a title Compass derived; the ask was not recorded)")
    else:
        print("    nothing Compass managed to record")
    if latest and latest[:60] != asked[:60]:
        print(f"\n  LAST TOLD\n    {_short(latest, 180)}")

    print("\n  WHAT COMPASS HAS TO GO ON")
    if not case.get("reached"):
        print("    the evidence ledger could not be read")
    elif case.get("citable"):
        print(
            f"    {case.get('citable')} citable facts, "
            f"{case.get('work_results') or 0} of them showing work done"
        )
    else:
        print("    nothing. no facts it could cite.")
    print(f"    {case.get('end_shape') or 'how it ended was not recorded'}")


def _question(case: dict[str, Any]) -> str:
    """The question, naming both answers in plain words.

    "Can it judge whether this met the GOAL" asks about a capability in the
    abstract. This asks what the board should say, which is the thing being
    marked.
    """
    tail = "    y = it has enough to answer    n = it must say it cannot tell\n    [y/n/s/q] "
    if not case.get("asked_for"):
        return (
            "\n  Compass never recorded what this session was asked for.\n"
            "  Should it still say whether the session did it?\n" + tail
        )
    return (
        f"\n  You want to know: did it {_headline(case)}\n"
        "  Should Compass answer that, or say it cannot tell?\n" + tail
    )


def _show_intent_case(body: dict[str, Any], case: dict[str, Any], position: str) -> None:
    """A format 5 screen: the case's own intent, then the frozen record, checks included."""
    revision = case_revision(case)
    print("\n" + "=" * 72)
    print(f"  {position}   {case.get('harness')} - {case.get('title') or case.get('id')}")
    print(f"  Recorded lifecycle: {_reading().end_kind(case.get('row_snapshot') or {})}")
    print(f"  Captured at: {case.get('captured_at')}")
    if case.get("asked_for"):
        print(f"  Opening request (review context): {_short(case.get('asked_for') or '', 260)}")
    print(f"\n  GOAL: {revision['goal']}")
    for k, line in enumerate(revision["lines"], 1):
        text = line.get("text") if isinstance(line, dict) else line
        source = line.get("source") if isinstance(line, dict) else ""
        print(f"  OUTCOME LINE {k}: {text}" + (f"   ({source})" if source else ""))
    print("  FROZEN PRODUCER LEDGER (review excerpts are not model evidence)")
    ledger = case_ledger(body, case)
    for entry in ledger:
        flags = [
            word
            for word, on in (
                ("changed after", entry.get("changed_after") is True),
                ("work record not fully read", entry.get("read_incomplete") is True),
                ("stale", entry.get("stale") is True),
            )
            if on
        ]
        more = f"  [{', '.join(flags)}]" if flags else ""
        print(f"    {entry['id']} | {entry['type']} | {entry['source']} | {entry['summary']}{more}")
        if entry.get("tail"):
            print(f"        output tail: {entry['tail']}")
        if "production_reading" in case and entry.get("agent_words"):
            print(f"        agent excerpt: {entry['agent_words']}")
    if "production_reading" in case:
        result = case["production_reading"].get("newest_final")
        if isinstance(result, dict):
            print(f"  NEWEST FINAL SOURCE: {result.get('outcome')}")
            print(
                f"    {result.get('fact_id')} | {result.get('at')} | "
                f"word digest {result.get('words_digest')}"
            )
    if not any(_reading().demonstrates_work(entry) for entry in ledger):
        print("    no check or written file in this record")


def _show_mark_case(body: dict[str, Any], case: dict[str, Any], position: str) -> None:
    if is_intent_packet(body):
        _show_intent_case(body, case, position)
        return
    if body.get("v") != 4:
        _show(case, position)
        return
    print("\n" + "=" * 72)
    print(f"  {position}   {case.get('harness')} - {case.get('title') or case.get('id')}")
    print(f"  Recorded lifecycle: {_reading().end_kind(case.get('row_snapshot') or {})}")
    if case.get("asked_for"):
        print(f"  Opening request (review context): {_short(case.get('asked_for') or '', 260)}")
    print(f"\n  GOAL YARDSTICK: {body.get('goal') or ''}")
    print(f"  OUTPUT YARDSTICK: {body.get('output') or ''}")
    print("  FROZEN PRODUCER LEDGER (review excerpts are not model evidence)")
    for entry in _reading().build_ledger(
        case.get("producer_facts") or [], str(case.get("harness") or ""), str(case.get("sid") or "")
    ):
        print(f"    {entry['id']} | {entry['type']} | {entry['source']} | {entry['summary']}")


def _mark_question(body: dict[str, Any], case: dict[str, Any], constraint: str) -> str:
    if is_intent_packet(body):
        revision = case_revision(case)
        if constraint == "goal":
            what = f"this goal: {revision['goal']}"
        elif constraint == "claims":
            what = "the agent's claims against the recorded work"
        else:
            k = int(constraint.rsplit("_", 1)[1])
            what = f"outcome line {k}: {case_lines(case)[k - 1]}"
        return (
            f"\n  Against {what}\n"
            "  Should Compass answer from the frozen record, or say it cannot tell?\n"
            "    y = it has enough to answer    n = it must say it cannot tell\n    [y/n/s/q] "
        )
    if body.get("v") == 4:
        return (
            f"\n  Against this {constraint} yardstick: {body.get(constraint) or ''}\n"
            "  Should Compass answer from the frozen ledger, or say it cannot tell?\n"
            "    y = it has enough to answer    n = it must say it cannot tell\n    [y/n/s/q] "
        )
    if constraint == "goal":
        return _question(case)
    return (
        "\n  And could it say whether a checkable deliverable came out,\n"
        "  a diff, a test run, a file you can open?\n    [y/n/s/q] "
    )


def _mark_asks_output(body: dict[str, Any], case: dict[str, Any]) -> bool:
    """The producer's own predicate, over the ledger it will read.

    A format 5 Claude Code case's ledger carries its frozen checks, as the
    scorer's press does; every other ledger holds none.
    """
    if is_intent_packet(body):
        text = " ".join(case_lines(case))
        return bool(_reading().asks_output(text, case_ledger(body, case)))
    if body.get("v") == 4:
        ledger = _reading().build_ledger(
            case.get("producer_facts") or [],
            str(case.get("harness") or ""),
            str(case.get("sid") or ""),
        )
        return bool(_reading().asks_output(str(body.get("output") or ""), ledger))
    return bool(case.get("asks_output"))


def _bound_marks(body: dict[str, Any], entries: dict[str, Any]) -> dict[str, Any]:
    if is_intent_packet(body):
        return {"v": 4, "marks": entries, "cases_digest": cases_digest(body)}
    if body.get("v") == 4:
        return {"v": 3, "marks": entries, "cases_digest": cases_digest(body)}
    return {"v": 2, "marks": entries}


def _mark_one(body: dict[str, Any], case: dict[str, Any]) -> dict[str, str] | None:
    """One case's answers, {} when skipped, None when the marker stopped."""
    names = case_constraints(body, case)
    answers: dict[str, str] = {}
    goal = _ask(_mark_question(body, case, "goal"))
    if goal is None or goal == "skip":
        return None if goal is None else {}
    answers["goal"] = goal
    if _mark_asks_output(body, case):
        for name in names[1:]:
            got = _ask(_mark_question(body, case, name))
            if got is None or got == "skip":
                return None if got is None else {}
            answers[name] = got
        return answers
    # Not asked, and saying so is the point. The constraint is never put to the
    # model where the record holds no work evidence, so the answer is the
    # ruling's rather than the marker's.
    answers.update(dict.fromkeys(names[1:], "abstain"))
    print("  The outcome question is not asked here: this record shows no check or")
    print("  demonstrated work result, so the ruling already fixes the answer.")
    return answers


def _ledger_refusal(*, continuation: bool = False, cases_digest: str = "") -> bool:
    """True, having said why, once the qualification has charged any call.

    A mark written after an output was seen is agreement, not a mark, so the
    key is frozen from the first charge (review, F1). An unreadable ledger
    counts as charged: fail closed.
    """
    if continuation:
        why = abstention_ledger.marking_refusal(cases_digest)
        if not why:
            return False
        print(f"The fresh packet cannot be marked: {why}.")
        return True
    committed = abstention_ledger.committed_chain(abstention_ledger.CLAUDE_SUMMARY_PATH)
    if not abstention_ledger.has_calls(abstention_ledger.LEDGER_PATH) and committed is None:
        return False
    print("The spend ledger already holds a call, so the answer key is frozen.")
    print("Marks cannot be written or discarded after anything has been spent.")
    return True


def _save_marks(body: dict[str, Any], entries: dict[str, Any], *, continuation: bool) -> bool:
    """Save the key, sharing the charge lock only for a continuation's final write."""
    if not continuation:
        _write(MARKS_PATH, _bound_marks(body, entries))
        return True
    path = abstention_ledger.LEDGER_PATH
    if path is None:
        print("The account's canonical spend ledger is unavailable.")
        return False
    # The interactive questions stay unlocked. Only the final recheck and
    # write share the scorer's charge lock: a new call cannot slip between.
    with abstention_ledger.locked(path):
        if _ledger_refusal(continuation=True, cases_digest=cases_digest(body)):
            return False
        _write(MARKS_PATH, _bound_marks(body, entries))
    return True


def mark(*, continuation: bool = False) -> int:  # noqa: PLR0911 - guard before and after marking
    body = _load(CASES_PATH)
    print_packet(CASES_PATH, body)
    if _ledger_refusal(continuation=continuation, cases_digest=cases_digest(body)):
        return 1
    cases = body.get("cases") if isinstance(body.get("cases"), list) else None
    if not cases:
        print(f"No cases at {CASES_PATH}. Run --build first.")
        return 1
    if _refuse_mismatch(body, "Nothing was shown or marked."):
        return 1
    saved = _load(MARKS_PATH)
    entries = _marks(saved)
    replay = body.get("v") in (4, FORMAT_INTENT)
    digest = cases_digest(body)
    if replay and entries and saved.get("cases_digest") != digest:
        print("These marks belong to a different or unfrozen case set. Nothing was changed.")
        print("Keep that key with its original cases; use a separate COMPASS_HOME for this packet.")
        return 1

    todo = [c for c in cases if c.get("id") not in entries]
    if not todo:
        print(f"All {len(cases)} cases are marked. Nothing to do.")
        _warn_if_unanimous(entries, cases)
        return 0

    print(f"\n{len(todo)} of {len(cases)} left. y, n, s to skip, q to stop and keep what you did.")
    print("\nEach screen restates what that session was asked, so you never have to")
    print("scroll back. You are saying what Compass SHOULD be able to say about it,")
    print("not what it currently does.")

    done = 0
    for index, case in enumerate(todo, 1):
        _show_mark_case(body, case, f"{index}/{len(todo)}")
        answers = _mark_one(body, case)
        if answers is None:
            break
        if not answers:
            continue
        entries[case["id"]] = answers
        done += 1

    if not _save_marks(body, entries, continuation=continuation):
        return 1
    _warn_if_unanimous(entries, cases)

    left = len([c for c in cases if c.get("id") not in entries])
    print(f"\nSaved {done} this round. {len(entries)} marked, {left} left.")
    print("Run it again when you have a minute." if left else "That is the whole key.")
    return 0


def _warn_if_unanimous(entries: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    """Say so when a column that COULD have varied did not.

    Per column, and never about the OUTPUT column on a corpus that cannot vary
    it: warning about an answer the ruling fixed punishes the marker for being
    right. v2 did that, and then told them to delete the key.
    """
    if len(entries) < 8:
        return
    askable = {c["id"] for c in cases if c.get("asks_output")}
    columns = [("goal", set(entries)), ("output", askable & set(entries))]
    for column, scope in columns:
        if len(scope) < 8:
            continue
        answers = {entries[k][column] for k in scope}
        if len(answers) == 1:
            print(f"\n  Every case that could vary was marked {answers.pop()!r} on {column}.")
            print("  A column that answers one way throughout cannot fail a producer")
            print("  that never abstains. Look at whether the cases differ in what")
            print("  that question turns on. The marks already given are not the problem.")


def report() -> int:
    body = _load(CASES_PATH)
    print_packet(CASES_PATH, body)
    cases = body.get("cases") if isinstance(body.get("cases"), list) else []
    if not cases:
        print("No cases built yet.")
        return 1
    if _refuse_mismatch(body, "Nothing was counted."):
        return 1
    entries = _marks(_load(MARKS_PATH))
    live = {c["id"] for c in cases}
    orphans = [k for k in entries if k not in live]
    print(f"{len(entries) - len(orphans)} of {len(cases)} marked.")
    if orphans:
        print(f"  {len(orphans)} marks name sessions no longer in the case set.")
    columns = ("goal", "lines") if is_intent_packet(body) else ("goal", "output")
    for column in columns:
        answers = [
            answer
            for k, v in entries.items()
            if k in live
            for name, answer in v.items()
            if name == column or (column == "lines" and name.startswith("line_"))
        ]
        judge = answers.count("judge")
        print(f"  {column:7} {judge} judge, {len(answers) - judge} abstain")
    _warn_if_unanimous({k: v for k, v in entries.items() if k in live}, cases)
    return 0


def main(argv: list[str] | None = None) -> int:  # noqa: C901, PLR0911, PLR0912 - one refusal per mode
    parser = argparse.ArgumentParser(description="Collect the abstention answer key.")
    parser.add_argument("--build", action="store_true", help="assemble cases from the live board")
    parser.add_argument("--port", type=int, default=4553, help="the dashboard port to read")
    parser.add_argument("--force", action="store_true", help="rebuild even if it orphans marks")
    parser.add_argument("--report", action="store_true", help="how far through the key you are")
    parser.add_argument("--reset", action="store_true", help="discard the marks and start over")
    parser.add_argument(
        "--continue-mark",
        action="store_true",
        help="mark the reviewed fresh case set after a failed run",
    )
    parser.add_argument("--freeze", metavar="SPEC", help="freeze a format 5 packet from a spec")
    parser.add_argument(
        "--production-reading",
        action="store_true",
        help="freeze typed Claude Intent with production agent/source evidence",
    )
    parser.add_argument(
        "--store-home", default=STORE_HOME, help="where the dashboard's history and ends live"
    )
    parser.add_argument(
        "--reviewed-exports", metavar="MANIFEST", help="explicit finite reviewed export manifest"
    )
    parser.add_argument(
        "--reviewed-exports-sha256", metavar="SHA256", help="independently pinned manifest digest"
    )
    args = parser.parse_args(argv)
    try:
        reviewed_exports = load_reviewed_exports(
            args.reviewed_exports, args.reviewed_exports_sha256
        )
    except FreezeError as error:
        print(f"Refused: {error}.")
        return 2
    if reviewed_exports is not None and not (args.freeze and args.production_reading):
        print(
            "Reviewed exports require --freeze and --production-reading; old cases stay unchanged."
        )
        return 2
    if args.production_reading and not args.freeze:
        print("--production-reading requires --freeze; existing packets are never upgraded.")
        return 2
    if (
        abstention_ledger.LEDGER_PATH is None
        or CLAUDE_PROJECTS_ROOT is None
        or STORE_HOME is None
        or abstention_ledger.canonical_home() is None
    ):
        print("Refused: this account's canonical home is unavailable. Nothing ran.")
        return 2
    if args.continue_mark and (args.build or args.reset or args.report or args.freeze):
        print("--continue-mark only marks; it cannot build, reset, freeze or report.")
        return 2
    if args.freeze:
        return freeze(
            args.port,
            args.freeze,
            force=args.force,
            store_home=args.store_home,
            production_reading=args.production_reading,
            reviewed_exports=reviewed_exports,
        )
    if args.build and args.reset:
        print("--build and --reset together are ambiguous. Run them one at a time.")
        return 2
    if args.reset:
        if _ledger_refusal():
            return 1
        if os.path.exists(MARKS_PATH):
            os.remove(MARKS_PATH)
            print(f"Discarded {MARKS_PATH}. The cases are untouched.")
        else:
            print("No marks to discard.")
        return 0
    if args.build:
        return build(args.port, force=args.force)
    if args.report:
        return report()
    return mark(continuation=args.continue_mark)


if __name__ == "__main__":
    raise SystemExit(main())
