"""Spacedock workflow cartography: parsing, attribution and the read policy.

Every read here is a project read or a dispatch-directory read rather than a
store read, so the identity checks, symlink refusal and byte bounds in this
module are the security boundary described in SECURITY.md.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat as stat_module
import time
from typing import TYPE_CHECKING, Any, TypeGuard

from compass_runtime import records, sessions
from compass_runtime import state as runtime_state

if TYPE_CHECKING:
    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState


# Spacedock drives work items ("entities") through an ordered list of named
# stages, with a "first officer" session dispatching "ensign" workers. Four
# facts make it visible to a passive reader, in decreasing order of authority:
#
# 1. The launcher starts the session with `--agent spacedock:first-officer`, so
#    the transcript's first records carry an ``agentSetting``. That alone proves
#    the session is Spacedock, and costs nothing: it is in the head bytes the
#    subagent classifier already reads.
# 2. The first officer runs `spacedock status --boot` — measured here at 69%
#    and 73% of the way through a transcript, not at startup — and the
#    envelope lands in the transcript as a tool result, carrying the ABSOLUTE
#    workflow directory and the ABSOLUTE entity-state directory, so nothing has
#    to be discovered by scanning.
# 3. The ordered stage list, and which stages are initial or terminal, is the one
#    fact that envelope's `dispatchable` view omits, so it is read from the
#    workflow README's frontmatter. See SECURITY.md for the contract these reads
#    operate under.
# 4. The entity-state directory holds one file per entity, whose frontmatter
#    ``status`` is the stage it is parked on right now.
#
# Fact 4 exists because ``dispatchable`` is a snapshot of what was dispatchable
# AT BOOT, not the entity roster. A long-running first officer that boots an
# empty queue and intakes work later (the common case) reports
# `dispatchable: []` forever, so a strip anchored on it alone never renders.
#
# Every parser here is pure so the whole matrix is exercisable on any runner
# (design decision
# [D-4](docs/design-cross-platform.md#d-4)).
SPACEDOCK_FO = "spacedock:first-officer"


SPACEDOCK_ENSIGN = "spacedock:ensign"


# A stat key cannot tell two writes apart when they land inside one filesystem
# timestamp tick at the same size ("racy git"), and on Windows `st_ctime` is the
# creation time, so it does not move on a write either. A file read inside its
# tick is therefore re-read rather than cached, or the first reading is served
# until the file next changes. Measured on windows-latest (DRC-4707): a README
# restored within one tick of a same-size stage rename kept the renamed stages.
# Two seconds covers the coarsest mtime in common use (FAT); NTFS ticks in about
# 16 ms and HFS+ in one second.
RACY_STAT_NS = 2_000_000_000


def _settled(info: os.stat_result) -> bool:
    """Whether a later write is certain to change ``info``'s mtime.

    Compared against the wall clock, not the application's clock: this is a
    question about the filesystem's own timestamps.
    """
    return time.time_ns() - info.st_mtime_ns >= RACY_STAT_NS


SD_STAGE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


SD_CYCLE_RE = re.compile(r"^(?:cycle|pass|round|c|v|p|r)\d+[a-z]?$|^(?:retry|rerun)$")


SD_COMMISSIONED_PREFIX = "spacedock@"


# Where `spacedock dispatch build` leaves ensign prompts. It is transcript grammar from the dispatch
# contract, not a location Compass creates or writes, and it sits in the shared temporary namespace,
# so every read of it goes through `read_dispatch_artifact`. SECURITY.md, "Cockpit dispatch and
# terminal reads", is the contract.
DISPATCH_DIRECTORY = "/tmp/spacedock-dispatch"  # noqa: S108 — legacy producer path; checked reads below.
DISPATCH_MAX_BYTES = 64 * 1024
_DISPATCH_FILE_PREFIX = "spacedock-ensign-"


def dispatch_directories() -> tuple[str, ...]:
    """The dispatch directories in lookup order: the private runtime one first, when set."""
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime and os.path.isabs(runtime):
        return (os.path.join(runtime, "spacedock-dispatch"), DISPATCH_DIRECTORY)
    return (DISPATCH_DIRECTORY,)


def dispatch_artifact_identity(artifact: str) -> tuple[str, str] | None:
    """The (entity, stage) an exact ``spacedock-ensign-<entity>-<stage>.md`` path names, or None."""
    directory, name = os.path.split(artifact)
    if (
        directory not in dispatch_directories()
        or not name.startswith(_DISPATCH_FILE_PREFIX)
        or not name.endswith(".md")
    ):
        return None
    name = name[len(_DISPATCH_FILE_PREFIX) : -len(".md")]
    slug, separator, stage = name.rpartition("-")
    if not separator or not SD_STAGE_RE.fullmatch(slug):
        return None
    if not SD_STAGE_RE.fullmatch(stage):
        return None
    return slug, stage


def read_dispatch_artifact(artifact: str) -> bytes:
    """The whole of one dispatch artifact, or ``b""`` when any check refuses it.

    The one reader of a dispatch directory: every caller takes these checks rather than opening
    the path itself, because a plain open follows a planted symlink and blocks on a planted FIFO.
    """
    if (
        dispatch_artifact_identity(artifact) is None
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "getuid")
    ):
        return b""
    directory = os.path.dirname(artifact)
    try:
        resolved_directory = os.path.realpath(directory)
        if os.path.dirname(os.path.realpath(artifact)) != resolved_directory:
            return b""
        # The directory fd anchors the open even if an entry is replaced between
        # realpath and open. Inspect the opened file, never a pre-open stat.
        with contextlib.ExitStack() as stack:
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, directory_fd)
            # A group- or world-writable directory lets another account create a name in it,
            # and the sticky bit does not prevent that, so either write bit refuses.
            directory_info = os.fstat(directory_fd)
            if directory_info.st_uid != os.getuid() or directory_info.st_mode & 0o022:
                return b""
            descriptor = os.open(
                os.path.basename(artifact),
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if (
                    not stat_module.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o022
                    # A second name is a hard-link plant; macOS has no protected_hardlinks.
                    # Spacedock writes each file in place, so its own files have one link.
                    or info.st_nlink != 1
                    or info.st_size > DISPATCH_MAX_BYTES
                ):
                    return b""
                # One byte past the bound catches growth after the fstat.
                raw = handle.read(DISPATCH_MAX_BYTES + 1)
                return raw if len(raw) <= DISPATCH_MAX_BYTES else b""
    except (OSError, ValueError):
        return b""


def frontmatter_lines(config: RuntimeConfig, text: str) -> list[str]:
    """The lines between a leading ``---`` fence and its closer, else [].

    Mirrors Spacedock's own fence finder: a leading BOM is stripped, truly
    empty leading lines are skipped, and the first content line must be exactly
    ``---``. CRLF is normalized so a ``---\\r`` fence still matches.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    start = None
    for index, raw in enumerate(lines):
        line = raw.removeprefix("﻿") if index == 0 else raw
        if line == "":
            continue
        if line.strip() != "---":
            return []
        start = index + 1
        break
    if start is None:
        return []
    out: list[str] = []
    for raw in lines[start:]:
        if raw.strip() == "---":
            return out
        if len(out) >= config.spacedock_max_frontmatter_lines:
            return []
        out.append(raw)
    return []  # unterminated frontmatter is not frontmatter


def scalar(lines: list[str], key: str) -> str:
    """A column-0 scalar from frontmatter lines, unquoted."""
    prefix = key + ":"
    for raw in lines:
        if raw.startswith(prefix):
            return raw[len(prefix) :].strip().strip("\"'")
    return ""


def truthy(value: str) -> bool:
    """YAML's true-ish scalars, quoted or bare. Anything else is false."""
    return value.strip().strip("\"'").lower() in {"true", "yes", "on"}


def stage_entries(config: RuntimeConfig, lines: list[str]) -> list[dict[str, Any]]:
    """The ordered ``stages.states[]`` list, or [] if unrecognised.

    Each entry is ``{"name", "initial", "terminal"}``. An indentation-scoped
    scan, not a YAML evaluator: enter ``stages:``, then ``states:``, then take
    each ``- name:`` until the block dedents to a sibling key
    (``transitions:``), attributing the ``initial:``/``terminal:`` flags nested
    under an item to it. Document order is the stage order — Spacedock's own
    advancement indexes this list.

    Anything the scan cannot model yields [] so the dashboard renders no strip
    rather than a wrong one. That deliberately covers flow-style sequences,
    quoted keys, anchors and aliases.
    """
    entries: list[dict[str, Any]] = []
    names: set[str] = set()
    stages_indent: int | None = None
    states_indent: int | None = None
    item_indent: int | None = None
    for raw in lines:
        body = raw.strip()
        if not body or body.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if stages_indent is None:
            if body == "stages:":
                stages_indent = indent
            continue
        if states_indent is None:
            if indent <= stages_indent:
                return []  # left the stages block without finding states
            if body == "states:":
                states_indent = indent
            continue
        if indent <= states_indent and not body.startswith("- "):
            break  # dedented to a sibling of states:
        if body.startswith("- "):
            if item_indent is None:
                item_indent = indent
            if indent == item_indent and not body.startswith("- name:"):
                # A states entry this scanner cannot model (flow style
                # `- {name: x}`, a quoted key, an anchor). Skipping it would emit
                # a spine missing a stage the workflow really declares — a wrong
                # strip, the one outcome worse than no strip. Deeper `- ` items
                # are nested values (a stage's `decision.options`), not states.
                return []
        if not body.startswith("- name:") or indent != item_indent:
            # A flag nested under the item currently being built. Deeper `- `
            # items reach here too, but they cannot start with these keys.
            if entries and item_indent is not None and indent > item_indent:
                for flag in ("initial", "terminal"):
                    if body.startswith(flag + ":"):
                        entries[-1][flag] = truthy(body[len(flag) + 1 :])
            continue
        value = body[len("- name:") :].strip().strip("\"'")
        if not value or not SD_STAGE_RE.match(value) or value in names:
            return []
        if len(entries) >= config.spacedock_max_stages:
            return []
        names.add(value)
        entries.append({"name": value, "initial": False, "terminal": False})
    return entries


def _codex_boot(config: RuntimeConfig, text: str) -> dict[str, Any] | None:
    """One complete direct result, measured rendering, or successful wrapper."""
    text = text.strip().removeprefix("=== BOOT ===\n")
    try:
        wrapper = json.loads(text)
    except (ValueError, RecursionError):
        return None if text[:1] in ("{", "[", '"') else rendered_envelope(config, text)
    if not isinstance(wrapper, dict) or (
        wrapper.get("command") == "boot" and "status" not in wrapper
    ):
        return wrapper if isinstance(wrapper, dict) else None
    value = wrapper.get("value")
    if wrapper.get("status") != "fulfilled" or not isinstance(value, dict):
        return None
    output = value.get("output")
    if (
        type(value.get("exit_code")) is not int
        or value["exit_code"] != 0
        or not isinstance(output, str)
    ):
        return None
    try:
        boot = json.loads(output)
    except (ValueError, RecursionError):
        return None
    return boot if isinstance(boot, dict) and boot.get("command") == "boot" else None


def _codex_tool_output(record: dict[str, Any]) -> list[str] | None:
    """A Codex rollout's tool-output text, or None when the record is not one.

    None rather than ``[]`` so the caller can tell "not a Codex record" from "a
    Codex tool output that said nothing", and fall through to the Claude and Pi
    shapes only in the first case.

    Two payload spellings and two value shapes, all four measured on the local
    rollout store rather than inferred from an API description:
    ``function_call_output`` carries ``output`` as a string on 15,730 records and
    as a list of ``{"type": …, "text": …}`` blocks on 897;
    ``custom_tool_call_output`` carries it as a string on 2,956 and as such a
    list on 18,477. Of the 23 rollouts naming a ``definition_dir``, 14 carry an
    envelope this parses, 9 of them on a ``function_call_output`` and 6 on a
    ``custom_tool_call_output`` (one file carries both). Counting files with a
    ``{"command"`` candidate rather than a parsed envelope gives 18 and 12
    instead, which is a different question; see
    [S-6](docs/design-spacedock.md#s-6).

    Nothing else under ``payload`` is read. A ``function_call``'s own arguments
    are the model's request rather than the command's output, which is the
    provenance distinction the caller's docstring is about.
    """
    payload = record.get("payload")
    if record.get("type") != "response_item" or not isinstance(payload, dict):
        return None
    if payload.get("type") not in ("function_call_output", "custom_tool_call_output"):
        return None
    output = payload.get("output")
    if isinstance(output, str):
        return [output]
    if not isinstance(output, list):
        return []
    return [
        block["text"]
        for block in output
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]


def tool_result_text(record: dict[str, Any]) -> list[str]:
    """The text of every ``tool_result`` block in one transcript record.

    Provenance matters: boot output is *command output*, so it counts only when
    it arrives in a tool result. Scanning the raw line would let ordinary
    conversation text — anything a user pasted or a model echoed — nominate an
    absolute path for Compass to open.

    Three transcript shapes carry that provenance. Claude writes tool results as
    ``content`` blocks with ``type: "tool_result"``. Pi writes them as a
    ``toolResult`` role message whose blocks carry ``type: "text"``. Codex writes
    neither — it has no ``message`` key at all and puts the echo under
    ``payload`` — which is why the observer's stage half was structurally
    unreachable there, publishing ``stage: ""`` for every rollout that ran a
    workflow.

    The Claude and Pi shapes are read exclusively, not additively: a
    ``toolResult`` role returns on its own blocks and never falls through to the
    ``tool_result`` scan below. Nothing writes both shapes in one message today,
    so no behaviour changes, but a transcript that did would lose the second
    half.
    """
    codex = _codex_tool_output(record)
    if codex is not None:
        return codex
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    out: list[str] = []
    if message.get("role") == "toolResult":
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                out.append(text)
        return out
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        text = block.get("content")
        if isinstance(text, str):
            out.append(text)
        elif isinstance(text, list):
            out.extend(
                part["text"]
                for part in text
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
    return out


def _usable_dir(value: object) -> TypeGuard[str]:
    """A boot-envelope directory Compass is willing to touch.

    Absolute and NUL-free, and encodable for this filesystem. That last check is
    not decoration: a lone surrogate survives JSON decoding, so an envelope can
    carry one, and every guard below this point is wrapped in ``except OSError``.
    ``os.fsencode`` raises ``UnicodeEncodeError``, which is a ``ValueError``, so
    it would sail through those handlers and out of the collector, and one such
    line in one transcript blanks every row for that harness until the session
    leaves the freshness window.

    The probe is platform-dependent and deliberately not the only defence.
    POSIX encodes with ``surrogateescape`` and cannot represent a lone
    surrogate; Windows uses ``surrogatepass`` and encodes it happily, where the
    path simply fails to exist. So the readers that consume these paths catch
    ``ValueError`` beside ``OSError`` rather than trusting this to refuse first.
    """
    if not isinstance(value, str) or not value:
        return False
    if not os.path.isabs(value) or "\x00" in value:
        return False
    try:
        os.fsencode(value)
    except (UnicodeEncodeError, ValueError):
        return False
    return True


def rendered_pair(raw: str) -> tuple[str, str] | None:
    """``(key, value)`` from one line of a rendered boot envelope, or None.

    Only the shape ``key: value`` is assumed. The key may carry JSON's quotes
    or none and the value may carry quotes and a trailing comma, because what
    reaches the transcript is whatever the session chose to print. Partitioning
    on the FIRST colon keeps a Windows value (``C:\\...``) intact.
    """
    line = raw.strip()
    head, sep, tail = line.partition(":")
    if not sep:
        return None
    key = head.strip().strip("\"'")
    if not key:
        return None
    return (key, tail.strip().rstrip(",").strip().strip("\"'"))


def rendered_envelope(config: RuntimeConfig, text: str) -> dict[str, Any] | None:
    """The boot envelope a session PRINTED rather than pasted, or None.

    The first officer is told to consume ``status --boot --json``, and nothing
    tells it to echo that JSON verbatim. Measured on this machine: every real
    first-officer session piped the envelope through a formatter, so the
    transcript carried an indented rendering and the raw object never appeared
    once in 120 transcripts over 21 days — the JSON branch above has never
    matched a genuine session, only Compass's own source and fixtures catted
    into a tool result. The fields the strip needs survive any such rendering,
    so they are read line by line rather than decoded.

    Gated on a top-level ``command: boot`` for the same reason the JSON branch
    checks ``envelope["command"] == "boot"``: without it, a tool result that
    merely prints these key names — this module's own source — nominates a path.
    Only top-level keys are read, so a nested decoy cannot supply one either.

    No line bound is imposed here: the text is already a slice of the at most
    ``spacedock_boot_scan_bytes`` the caller read, and this scan is linear with
    trivial per-line work, unlike the ``raw_decode`` the candidate cap protects.
    """
    out: dict[str, Any] = {}
    dispatchable: list[dict[str, str]] = []
    item: dict[str, str] = {}
    booted = False
    in_dispatchable = False
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        pair = rendered_pair(raw)
        if pair is None:
            continue
        key, value = pair
        if not raw[:1].isspace():
            in_dispatchable = key == "dispatchable"
            if key == "command":
                booted = booted or value == "boot"
            elif key in ("definition_dir", "entity_dir") and value and key not in out:
                # First occurrence wins, so a decoy in a trailing blob cannot
                # displace the envelope the session actually booted from.
                out[key] = value
            continue
        if not in_dispatchable or len(dispatchable) >= config.spacedock_max_entities:
            continue
        # Paired on `slug` rather than on the list syntax, so both the
        # `-`-delimited and inline renderings of an item read the same.
        if key == "slug" and value:
            if item:
                dispatchable.append(item)
            item = {"slug": value}
        elif key == "current" and value and item and "current" not in item:
            item["current"] = value
    if item and len(dispatchable) < config.spacedock_max_entities:
        dispatchable.append(item)
    if not booted or "definition_dir" not in out:
        return None
    out["command"] = "boot"
    out["dispatchable"] = [
        entry for entry in dispatchable if entry.get("slug") and entry.get("current")
    ]
    return out


def boot_records(config: RuntimeConfig, data: bytes) -> list[dict[str, Any]]:
    """Every ``spacedock status --boot`` envelope in a slice of a transcript.

    Decoded line by line as the JSONL it is, so the JSON decoder does the
    unescaping and each envelope is located inside already-plain text. An
    earlier version scanned the escaped bytes with a hand-rolled brace balancer,
    which both mis-sliced a path containing a brace and rescanned to the end of
    the blob for every unbalanced marker — quadratic, under the collection lock.
    """
    out: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    for line in data.split(b"\n"):
        if b"definition_dir" not in line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(record, dict):
            continue
        for text in tool_result_text(record):
            if record.get("type") == "response_item":
                envelope = _codex_boot(config, text)
                if envelope is not None:
                    out.append(envelope)
                    if len(out) >= config.spacedock_max_boot_records:
                        return out
                continue
            found = len(out)
            position = 0
            for _ in range(config.spacedock_max_boot_candidates):
                begin = text.find('{"command"', position)
                if begin < 0:
                    break
                try:
                    envelope, position = decoder.raw_decode(text, begin)
                except (ValueError, RecursionError):
                    # raw_decode fails at the first bad byte, so stepping past a
                    # bad candidate cannot degrade into a whole-blob rescan.
                    #
                    # `RecursionError` beside it because this text is already
                    # unescaped, so nesting a tool happened to print is real
                    # nesting to the decoder. It is a `RuntimeError`, not a
                    # `ValueError`, so it would sail past every handler between
                    # here and `aggregate`'s per-harness boundary — and that
                    # boundary blanks the whole harness's rows, which is a
                    # steep price for one deep line in one transcript.
                    position = begin + 1
                    continue
                if isinstance(envelope, dict) and envelope.get("command") == "boot":
                    out.append(envelope)
                    if len(out) >= config.spacedock_max_boot_records:
                        return out
            if len(out) > found:
                continue
            rendered = rendered_envelope(config, text)
            if rendered is not None:
                out.append(rendered)
                if len(out) >= config.spacedock_max_boot_records:
                    return out
    return out


def workflow_dirs(config: RuntimeConfig, envelopes: list[dict[str, Any]]) -> list[str]:
    """Distinct absolute workflow directories named by boot envelopes.

    Order is first-seen so the display order matches the boot order. Only
    absolute paths are kept: a relative value cannot be resolved without
    guessing a base, and guessing is what the read contract forbids.
    """
    out: list[str] = []
    for record in envelopes:
        value = record.get("definition_dir")
        if not _usable_dir(value):
            continue
        if value not in out:
            out.append(value)
        if len(out) >= config.spacedock_max_workflows:
            break
    return out


def boot_entities(envelopes: list[dict[str, Any]], workflow_dir: str) -> dict[str, str]:
    """``{slug: current_stage}`` for one workflow, newest envelope winning.

    A first officer boots once per workflow and may re-boot; later envelopes
    carry fresher stages, so they overwrite earlier ones.
    """
    out: dict[str, str] = {}
    for record in envelopes:
        if record.get("definition_dir") != workflow_dir:
            continue
        items = record.get("dispatchable")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            current = item.get("current")
            if isinstance(slug, str) and slug and isinstance(current, str) and current:
                out[slug] = current
    return out


def boot_entity_dir(envelopes: list[dict[str, Any]], workflow_dir: str) -> str:
    """The absolute entity-state directory one workflow's boot output names.

    Same provenance and same authority as ``definition_dir``: the session's own
    command output, in a tool result. The newest envelope wins, and the value is
    kept only if it is absolute — a relative path cannot be resolved without
    guessing a base, and guessing is what the read contract forbids. A
    ``split-root`` workflow legitimately stores state outside its definition
    directory, so containment is NOT required here; the discriminator is applied
    per file instead (see :func:`read_entities`).
    """
    out = ""
    for record in envelopes:
        if record.get("definition_dir") != workflow_dir:
            continue
        value = record.get("entity_dir")
        if _usable_dir(value):
            out = value
    return out


def transcript_boot(config: RuntimeConfig, state: RuntimeState, path: str) -> list[dict[str, Any]]:
    """Boot envelopes from a transcript, scanned forward across refreshes.

    An earlier version read only the first ``spacedock_boot_scan_bytes``, on the
    reasoning that boot output is written once at session start and never
    rewritten. Measured against real first-officer sessions on this machine, it
    is not: two of them booted 69% and 73% of the way through their transcripts,
    at bytes 803,503 and 821,199, because a first officer greets and discovers
    before it boots and Claude Code writes records up to 109 KB apiece. A
    head-only window found neither.

    So the window walks rather than sits. Each pass reads at most
    ``spacedock_boot_scan_bytes`` of not-yet-scanned bytes and remembers how far
    it reached, which holds the per-refresh cost the head scan had while the
    whole file is covered eventually. Progress is cached per path rather than
    per ``(path, size)`` so a growing session keeps its place instead of
    restarting the walk on every write.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    with state.cache_lock:
        cached = state.spacedock_boot_cache.get(path)
    records: list[dict[str, Any]]
    scanned: int
    records, scanned = cached if cached is not None else ([], 0)
    if scanned > size:
        # The file is shorter than the walk already covered, so it is not the
        # one that progress was recorded against. Start it over.
        records, scanned = [], 0
    if scanned >= size or len(records) >= config.spacedock_max_boot_records:
        return records
    try:
        with open(path, "rb") as handle:
            handle.seek(scanned)
            blob = handle.read(config.spacedock_boot_scan_bytes)
    except OSError:
        return records
    chunk = blob
    if scanned + len(blob) >= size:
        consumed = len(blob)
    else:
        cut = blob.rfind(b"\n") + 1
        if cut:
            # Stop on a line boundary so an envelope straddling the window edge
            # is read whole on the next pass instead of halved on this one.
            chunk, consumed = blob[:cut], cut
        else:
            # One record longer than the whole window. Nothing in it can be
            # read as a line, so step over it rather than stall here forever.
            chunk, consumed = b"", len(blob)
    if b"definition_dir" in chunk:
        records = (records + boot_records(config, chunk))[: config.spacedock_max_boot_records]
    with state.cache_lock:
        runtime_state.bounded_put(
            state.spacedock_boot_cache,
            path,
            (records, scanned + consumed),
            limit=config.max_cache_entries,
        )
    return records


def open_regular(path: str) -> int | None:
    """Open ``path`` read-only, refusing symlinks and non-regular files.

    ``O_NOFOLLOW`` is absent on Windows, so there the refusal rests on the
    ``lstat`` classification alone and a racing reparse-point swap could still
    be followed — the same unclosable class as the FILE_SHARE_DELETE window
    documented in SKILL.md.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        if stat_module.S_ISLNK(os.lstat(path).st_mode):
            return None
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat_module.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            return None
    except OSError:
        os.close(descriptor)
        return None
    return descriptor


class SdMismatchError(Exception):
    """The opened file is not the one that was stat'd. Distinct from an empty
    read, which is merely a file with no frontmatter."""


def read_frontmatter(
    config: RuntimeConfig, path: str, limit: int, expect: os.stat_result
) -> list[str]:
    """The frontmatter lines of a regular, non-symlink file, or [].

    At most ``limit`` bytes are read, and the descriptor must describe the same
    file ``expect`` does. O_NOFOLLOW guards only the final path component, so a
    parent-directory swap between the stat and the open would otherwise seed a
    cache from a different file under a trusted key — that raises
    :class:`SdMismatchError` so the caller can decline to cache. Only the frontmatter
    lines leave this function; the body is never returned.
    """
    descriptor = open_regular(path)
    if descriptor is None:
        return []
    try:
        opened = os.fstat(descriptor)
        same_file = (opened.st_dev, opened.st_ino) == (expect.st_dev, expect.st_ino)
    except OSError:
        same_file = False
    if not same_file:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        raise SdMismatchError(path)
    raw = b""
    try:
        handle = os.fdopen(descriptor, "rb")
    except OSError:
        # os.fdopen does not close the descriptor when it fails to wrap it,
        # and this runs on every refresh — leaking here exhausts the table.
        with contextlib.suppress(OSError):
            os.close(descriptor)
    else:
        with handle, contextlib.suppress(OSError):
            raw = handle.read(limit)
    return frontmatter_lines(config, raw.decode("utf-8", "replace"))


def read_workflow(
    config: RuntimeConfig,
    state: RuntimeState,
    workflow_dir: str,
    *,
    definition_root: str | None = None,
) -> dict[str, Any] | None:
    """The stage taxonomy of one workflow directory, or None.

    ``workflow_dir`` is canonicalised and at most
    ``config.spacedock_readme_bytes`` are read. A session-recorded workflow
    keeps the default strict boundary: its README must be a regular,
    non-symlink file inside that directory. Project discovery may pass the
    already verified ``.spacedock`` definition root; then an immediate workflow
    child may link its README to another definition below that same root. This
    supports Spacedock's repository-owned definition layout without allowing a
    discovered link to leave the project boundary.

    The result counts only if the frontmatter declares ``commissioned-by:
    spacedock@`` — Spacedock's own workflow discriminator. No directory is
    walked. Only derived scalars leave this function, plus the frontmatter
    ``title`` — the goal line, and the one piece of project-authored text on the
    surface, bounded by
    ``config.spacedock_goal_cap_chars`` and stripped by ``records.safe_text``.
    No body text and no filesystem path leaves.

    ``resting`` is the subset of stages an entity is not moving through: the
    initial stage it is queued on and the terminal stages it has finished at.
    """
    try:
        root = os.path.realpath(workflow_dir)
        readme = os.path.join(root, "README.md")
        resolved = os.path.realpath(readme)
        containment_root = os.path.realpath(definition_root) if definition_root else root
        if (definition_root and os.path.dirname(root) != containment_root) or os.path.commonpath(
            (containment_root, resolved)
        ) != containment_root:
            return None
        read_path = resolved if definition_root else readme
        info = os.lstat(read_path)
        if not stat_module.S_ISREG(info.st_mode):
            return None
    except (OSError, ValueError):
        return None
    key = (root, info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mtime_ns, info.st_size)
    with state.cache_lock:
        if key in state.spacedock_workflow_cache:
            return state.spacedock_workflow_cache[key]
    result: dict[str, Any] | None = None
    try:
        lines = read_frontmatter(config, read_path, config.spacedock_readme_bytes, info)
    except SdMismatchError:
        return None
    if scalar(lines, "commissioned-by").startswith(SD_COMMISSIONED_PREFIX):
        entries = stage_entries(config, lines)
        if entries:
            result = {
                "name": os.path.basename(root) or root,
                "stages": [entry["name"] for entry in entries],
                "resting": [
                    entry["name"] for entry in entries if entry["initial"] or entry["terminal"]
                ],
                # Through `safe_text`, like every other untrusted string that
                # reaches a row: bounded, and stripped of the bidi controls that
                # would let a title render as something it does not say. This is
                # project-authored prose, not a grammar-checked slug.
                "goal": records.safe_text(scalar(lines, "title"), config.spacedock_goal_cap_chars),
            }
    if _settled(info):
        with state.cache_lock:
            runtime_state.bounded_put(
                state.spacedock_workflow_cache, key, result, limit=config.max_cache_entries
            )
    return result


def entity_stage(
    config: RuntimeConfig, state: RuntimeState, path: str, info: os.stat_result
) -> str:
    """The ``status`` scalar in one entity file's frontmatter, or "".

    Cached on ``(path, st_mtime_ns, st_size)`` once settled (``RACY_STAT_NS``),
    so a state directory in which only one entity is moving costs one read per
    refresh and a stat per file.
    """
    key = (path, info.st_mtime_ns, info.st_size)
    with state.cache_lock:
        cached = state.spacedock_entity_cache.get(key)
    if cached is not None:
        return cached
    try:
        lines = read_frontmatter(config, path, config.spacedock_entity_bytes, info)
    except SdMismatchError:
        return ""
    stage = scalar(lines, "status")
    if _settled(info):
        with state.cache_lock:
            runtime_state.bounded_put(
                state.spacedock_entity_cache, key, stage, limit=config.max_cache_entries
            )
    return stage


def _entity_candidates(entity_dir: str) -> list[tuple[str, str, os.stat_result]]:
    """``(slug, path, stat)`` for a state directory's entity files, newest first.

    Spacedock writes an entity as either ``<slug>.md`` or ``<slug>/index.md``
    (the folder form, for entities that accumulate per-stage artifacts). One
    ``scandir`` of the directory the boot output named; nothing below it is
    walked, and ``_archive/`` — where Spacedock retires finished entities — is
    skipped along with every other name that is not a well-formed slug.

    Newest-first because the cap that follows is a budget: a mature queue holds
    far more entities than it is running, and the ones being written are the
    ones in flight.

    Every candidate is `lstat`ed for real rather than taking the stat
    ``scandir`` already cached. On Windows that cached result reports
    ``st_ino`` and ``st_dev`` as zero, which can never match the ``fstat`` of an
    open descriptor — so the identity check in :func:`read_frontmatter`
    would refuse every entity file and the strip would come back empty on that
    platform alone. A silent per-platform false negative is exactly the failure
    mode
    [D-4](docs/design-cross-platform.md#d-4)
    exists to keep out.
    """
    try:
        with os.scandir(os.path.realpath(entity_dir)) as entries:
            found = list(entries)
    except (OSError, ValueError):
        return []
    out: list[tuple[str, str, os.stat_result]] = []
    for entry in found:
        name = entry.name
        slug = name.removesuffix(".md")
        # Spacedock's slug grammar is its stage grammar: lowercase kebab. That
        # rejects `_archive`, `README.md` and the report files operators leave
        # beside the state without a second pass over the listing.
        if not SD_STAGE_RE.match(slug):
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                path = os.path.join(entry.path, "index.md")
            elif name.endswith(".md"):
                path = entry.path
            else:
                continue
            info = os.lstat(path)
        except (OSError, ValueError):
            continue  # entity written or retired between the listing and the stat
        if not stat_module.S_ISREG(info.st_mode):
            continue  # a symlinked entity file is refused, not followed
        out.append((slug, path, info))
    out.sort(key=lambda item: -item[2].st_mtime_ns)
    return out


def entity_files(config: RuntimeConfig, entity_dir: str) -> list[tuple[str, str, os.stat_result]]:
    return _entity_candidates(entity_dir)[: config.spacedock_max_entity_files]


def read_entities(
    config: RuntimeConfig,
    state: RuntimeState,
    entity_dir: str,
    stages: list[str],
    now: float,
    window_sec: float,
) -> list[tuple[str, str]]:
    """``[(slug, stage)]`` for one workflow's recent entity state, newest first.

    The authoritative, current answer to "where is each entity", against which
    the boot envelope's ``dispatchable`` snapshot is only a stale hint. An entity
    counts only when:

    - its state file was written within ``window_sec`` — the same freshness
      window every collector applies to a session. A first officer discovers
      every workflow in the project, and a workflow retired months ago still has
      entities frozen mid-pipeline; those are history, not work in flight.
    - its frontmatter ``status`` names a stage this workflow declares — the
      per-file discriminator that stands in for the containment check
      :func:`read_workflow` performs, since a ``split-root`` workflow may
      legitimately keep its state outside the definition directory.
    """
    declared = set(stages)
    out: list[tuple[str, str]] = []
    for slug, path, info in entity_files(config, entity_dir):
        if not sessions.is_fresh(config, now, info.st_mtime, window_sec):
            continue
        stage = entity_stage(config, state, path, info)
        if stage in declared:
            out.append((slug, stage))
    return out


def attribute_worker(name: str, slugs: list[str], stages: list[str]) -> tuple[str, str, str] | None:
    """``(slug, stage, cycle)`` for a worker, anchored on a *known* slug.

    Guessing the slug by stripping cycle-shaped tokens is wrong twice over: real
    entity slugs end in cycle-shaped tokens of their own (`…-pr-1506-r3` is one
    entity, not `…-pr-1506` on round 3), and a guessed slug matches every other
    workflow that declares the same stage. So the slug comes from this
    workflow's own boot snapshot, longest first so a slug that prefixes another
    cannot win.
    """
    body = name.removeprefix("spacedock-ensign-")
    if body == name:
        return None
    for slug in sorted(slugs, key=len, reverse=True):
        remainder = body.removeprefix(slug + "-")
        if remainder == body:
            continue
        tokens = remainder.split("-")
        for stage in sorted(stages, key=len, reverse=True):
            stage_tokens = stage.split("-")
            for offset in range(len(tokens) - len(stage_tokens), -1, -1):
                if tokens[offset : offset + len(stage_tokens)] != stage_tokens:
                    continue
                rest = tokens[:offset] + tokens[offset + len(stage_tokens) :]
                if any(not SD_CYCLE_RE.match(token) for token in rest):
                    continue
                return (slug, stage, "-".join(rest))
    return None


def workflow_observation(
    config: RuntimeConfig,
    _state: RuntimeState,
    workflow_dir: str,
    entity_dir: str,
    info: dict[str, Any],
    now: float,
    window_sec: float,
) -> dict[str, Any]:
    """Current entity evidence, independent of the twelve-row display roster."""
    pair = ["compass-workflow-v1", os.path.realpath(workflow_dir), os.path.realpath(entity_dir)]
    identity = hashlib.sha256(json.dumps(pair).encode()).hexdigest()
    observed: list[dict[str, Any]] = []
    files = _entity_candidates(entity_dir)
    counts: dict[str, int] = {}
    for slug, _path, _stat in files:
        counts[slug] = counts.get(slug, 0) + 1
    selected = files[: config.spacedock_max_entity_files]
    for slug, path, stat in selected:
        if counts[slug] != 1 or not 0 <= now - stat.st_mtime <= window_sec:
            continue
        try:
            lines = read_frontmatter(config, path, config.spacedock_entity_bytes, stat)
        except SdMismatchError:
            continue
        stage = scalar(lines, "status")
        if stage in info["stages"]:
            observed.append(
                {
                    "slug": slug,
                    "stage": stage,
                    "source": "entity-state",
                    "source_written_at": stat.st_mtime,
                    "observed_at": now,
                }
            )
    try:
        directory = os.stat(entity_dir)
        generation = hashlib.sha256(
            json.dumps([directory.st_dev, directory.st_ino, info["stages"]]).encode()
        ).hexdigest()
    except (OSError, ValueError):
        generation = ""
    return {
        "id": identity,
        "workflow": records.safe_text(info["name"], 120),
        "goal": info.get("goal", ""),
        "stages": info["stages"],
        "generation": generation,
        "entities": observed,
        "evaluated": len(observed),
        "partial": len(files) > len(selected) or len(observed) < len(selected),
    }


def session_workflows(
    config: RuntimeConfig,
    state: RuntimeState,
    boot: list[dict[str, Any]],
    worker_names: list[str],
    now: float,
    window_sec: float,
) -> list[dict[str, Any]]:
    """Render-ready workflow strips for one session.

    An entity earns a strip when it is *in flight*: named by a live worker, or
    parked on a stage it is moving through, or listed as dispatchable at boot.
    Three sources in decreasing order of freshness — live workers first and
    marked, then the entity state directory, then the boot snapshot — deduped by
    slug so the freshest answer for an entity wins.

    Entities resting on the initial or a terminal stage are left out of the
    middle source. A mature queue is mostly those: reporting thirty entities
    parked on ``intake`` would push the handful that are actually moving off the
    end of the strip. They still appear if boot called them dispatchable, which
    is Spacedock's own statement that they are next to move.
    """
    out: list[dict[str, Any]] = []
    for workflow_dir in workflow_dirs(config, boot):
        info = read_workflow(config, state, workflow_dir)
        if info is None:
            continue
        stages: list[str] = info["stages"]
        resting: set[str] = set(info["resting"])
        booted = boot_entities(boot, workflow_dir)
        entity_dir = boot_entity_dir(boot, workflow_dir)
        roster = (
            read_entities(config, state, entity_dir, stages, now, window_sec) if entity_dir else []
        )
        # Live worker names carry a stage but not a slug boundary, so the slug
        # has to come from a roster. The state directory is what makes that
        # roster non-empty for a first officer that booted an empty queue.
        slugs = list({slug for slug, _ in roster} | set(booted))
        entities: list[dict[str, Any]] = []
        seen: set[str] = set()
        for name in worker_names:
            attributed = attribute_worker(name, slugs, stages)
            if attributed is None:
                continue
            slug, stage, cycle = attributed
            if slug in seen:
                continue
            seen.add(slug)
            entities.append({"slug": slug, "stage": stage, "cycle": cycle, "live": True})
        for slug, stage in roster:
            if slug in seen or stage in resting:
                continue
            seen.add(slug)
            entities.append({"slug": slug, "stage": stage, "cycle": "", "live": False})
        for slug, stage in booted.items():
            if slug in seen or stage not in stages:
                continue
            seen.add(slug)
            entities.append({"slug": slug, "stage": stage, "cycle": "", "live": False})
        source = (
            workflow_observation(config, state, workflow_dir, entity_dir, info, now, window_sec)
            if entity_dir and config.tripwires_enabled
            else None
        )
        if not entities and (source is None or not source["generation"]):
            continue
        out.append(
            {
                **({"tripwire_source": source} if source is not None else {}),
                "workflow": info["name"],
                "goal": info.get("goal", ""),
                "stages": stages,
                "entities": entities[: config.spacedock_max_entities],
            }
        )
    return out
