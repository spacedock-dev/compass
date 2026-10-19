#!/usr/bin/env python3
"""Anonymize a Claude Code session log into a public, realistic example, and verify the result.

The script holds no original value. Every name, path, project word and id to replace lives in a
local mapping file (`--mapping`), written outside the repository because it contains the
originals. The shape of that file is documented in
[sample-session/README.md](sample-session/README.md).

    sanitize_session.py --mapping M.json --input session.jsonl --output example-session.jsonl
    sanitize_session.py --mapping M.json --input session.jsonl --output example-session.jsonl \
        --verify

What it does, by walking every string value (and every key) of every record:

- Literal replacements from the mapping, longest first and in one pass, so a replacement is never
  rewritten by a later rule. An entry may be `"word": true` to match only whole words.
- Ids regenerated through one consistent mapping, so parent and child chains and tool_use and
  tool_result pairs stay linked: UUIDs, `toolu_`, `msg_` and `req_` ids, the commit hashes and long
  numbers the mapping lists, and any 40-hex hash.
- Dates shifted by a whole number of days (`day_shift`), so order, gaps and times of day survive
  and a date in a filename still agrees with the timestamps.
- Thinking blocks dropped, images replaced by a placeholder, secrets by `<REDACTED_TOKEN>`, any
  other email by `user@example.com`, any other home directory by `/Users/dev`.
- A parent that is no longer in the file (the cut starts mid-session) becomes `null`.

Verification (`--verify`) reparses both files, compares line counts, checks every parent and every
tool_use and tool_result pair, and searches the output for every original in the mapping, in plain,
case-insensitive, URL-encoded and JSON-escaped form, plus a sweep for the usual shapes of a leak.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
PREFIXED = re.compile(r"\b(toolu|msg|req)_([A-Za-z0-9]{8,})\b")
LONG_HASH = re.compile(r"\b[0-9a-f]{40}\b")
DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)(?:T(\d\d):(\d\d):(\d\d)(\.\d+)?Z)?")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)+")
OTHER_HOME = re.compile(r"(/Users/|/home/|C:\\\\?Users\\\\?)(?!dev\b)[A-Za-z0-9._-]+")
SECRET = re.compile(
    r"(?:AKIA|ASIA)[A-Z0-9]{16}"
    r"|sk-(?:ant-)?[A-Za-z0-9_-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[bpasr]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|lin_(?:api|oauth)_[A-Za-z0-9]{20,}|ntn_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}",
    re.DOTALL,
)
SWEEPS = {
    "email": re.compile(
        r"[A-Za-z0-9._%+-]+@(?!example\.com\b)[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)+"
    ),
    "ip address": re.compile(r"\b(?!127\.0\.0\.1\b)\d{1,3}(?:\.\d{1,3}){3}\b"),
    "home directory": re.compile(
        r"/Users/(?!dev\b|u\b)[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|C:\\\\?Users"
    ),
    # `sk-` only at the start of a token: "task-notification" is not an API key.
    "secret shape": re.compile(
        r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]|ghp_|gho_|github_pat_|AKIA|ASIA|xox[bpasr]-|eyJ[A-Za-z0-9_-]{6}|-----BEGIN"
    ),
    # A 40-hex commit hash is regenerated, so only a longer run (a digest, a token) is a leak.
    "long hex run": re.compile(r"\b[0-9a-f]{41,}\b"),
    "long base64 run": re.compile(r"[A-Za-z0-9+/=]{120,}"),
    # The sample ships inside the page, which carries no tracker brand, host or issue key.
    "tracker reference": re.compile(r"\bLinear\b|linear\.app|\bDRC-\d+|claude_ai_"),
    # A home directory as Claude Code encodes it in a project folder or scratch path.
    "encoded home directory": re.compile(r"-Users-(?!dev\b)[A-Za-z0-9._]+"),
    "machine temp directory": re.compile(r"/var/folders/"),
    # A link to the person's own remote-controlled session; a placeholder starts `01Example`.
    "remote session link": re.compile(r"claude\.ai/code/session_(?!01Example)"),
}
# Times written as text rather than as timestamps, shifted with the timestamps when the mapping asks
# (`shift_bare_times`): a tool's output and a monitor's log carry the real time, often in the local
# time zone, which the timestamps' shift would otherwise leave readable beside them.
# A Unix time in seconds (2023 to 2033, optionally with a fraction) or in milliseconds.
EPOCH = re.compile(r"(?<![\d.])(1[789]\d{8})(\.\d{1,6})?(?![\d])|(?<![\d.])(1[789]\d{11})(?![\d.])")
# A time of day with seconds, outside an ISO timestamp (which DATE already moved). A `ps` duration
# has the same shape and moves too; it said nothing private and still says nothing.
CLOCK = re.compile(r"(?<![\dT:.])([01]\d|2[0-3]):([0-5]\d):([0-5]\d)(?!\d|:\d)")
# A time of day without seconds only where the text says it is one, because the bare shape is also a
# slice, a ratio or a `ps` duration: after "at" ("failed at 13:58", "Status at 13:13:"), and as the
# clock that opens an `uptime` line ("12:47  up 16:10", whose "16:10" is a duration and stays).
CLOCK_AT = re.compile(r"(?<=\bat )([01]\d|2[0-3]):([0-5]\d)(?!\d|:\d)")
UPTIME = re.compile(r"(?<![\d:])([01]\d|2[0-3]):([0-5]\d)(?= +up\b)")
# A `ls -l` style month and day, with its time of day when it has one.
MONTH_DAY = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) {1,2}(\d{1,2})"
    r"(?: ([01]\d|2[0-3]):([0-5]\d))?\b"
)
# Vitest's "Start at" line is UTC in this repository: its config sets TZ=UTC for the suite.
UTC_CLOCK_PREFIXES = ("Start at  ",)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# Fields that name another record by uuid; one that names a record the cut removed becomes null.
REFERENCE_KEYS = (
    "parentUuid",
    "leafUuid",
    "messageId",
    "snapshotMessageId",
    "sourceToolAssistantUUID",
)
PLACEHOLDER_TOKEN = "<REDACTED_TOKEN>"  # noqa: S105 - a placeholder, not a credential


@dataclass
class Mapping:
    """What to replace, loaded from the local mapping file."""

    salt: str
    day_shift: int
    literals: list[dict[str, Any]]
    # Added to every timestamp that has a time of day, so the hours of the original working day,
    # which hint at a time zone, do not survive. A bare date moves by `day_shift` days alone.
    time_shift_seconds: int = 0
    ai_title: str = ""
    hashes: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    drop_blocks: list[str] = field(default_factory=lambda: ["thinking", "redacted_thinking"])
    # Off by default so the first sample regenerates byte for byte; its record holds no bare times.
    shift_bare_times: bool = False
    # How far the machine's local clock ran ahead of UTC. A bare time of day is local unless it
    # says UTC, and the timestamps are UTC, so leaving the difference would let a reader subtract
    # one from the other and recover the time zone. Removing it makes a local time read as UTC.
    local_clock_offset_seconds: int = 0

    @classmethod
    def load(cls, path: Path) -> Mapping:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            salt=str(raw["salt"]),
            day_shift=int(raw["day_shift"]),
            literals=list(raw["literals"]),
            time_shift_seconds=int(raw.get("time_shift_seconds", 0)),
            ai_title=str(raw.get("ai_title", "")),
            hashes=list(raw.get("hashes", [])),
            numbers=list(raw.get("numbers", [])),
            drop_blocks=list(raw.get("drop_blocks", ["thinking", "redacted_thinking"])),
            shift_bare_times=bool(raw.get("shift_bare_times", False)),
            local_clock_offset_seconds=int(raw.get("local_clock_offset_seconds", 0)),
        )


class Sanitizer:
    """One consistent original-to-replacement table, applied to every string."""

    def __init__(self, mapping: Mapping) -> None:
        self.mapping = mapping
        self.table: dict[str, tuple[str, str]] = {}
        self.counts: Counter[str] = Counter()
        self.categories: Counter[str] = Counter()
        entries = sorted(mapping.literals, key=lambda e: len(e["from"]), reverse=True)
        self.by_text = {e["from"]: e for e in entries}
        self.literal = re.compile("|".join(_alternative(e) for e in entries) or r"(?!)")
        self.hash_re = (
            re.compile(
                r"\b(?:"
                + "|".join(map(re.escape, sorted(mapping.hashes, key=len, reverse=True)))
                + r")\b"
            )
            if mapping.hashes
            else None
        )
        self.number_re = (
            re.compile(r"(?<!\d)(?:" + "|".join(map(re.escape, mapping.numbers)) + r")(?!\d)")
            if mapping.numbers
            else None
        )
        self.short_ids: dict[str, str] = {}
        self.short_re: re.Pattern[str] | None = None

    def learn_short_ids(self, raw: str) -> None:
        """Map the eight-character short form of every session or record id in the source.

        Compass and its URLs name a session by the first eight characters of its id, so the short
        form appears on its own in commands and links. It must become the short form of the id's
        replacement, or the replaced session would still be named by its original.
        """
        self.short_ids = {u[:8]: self._uuid_text(u)[:8] for u in set(UUID.findall(raw))}
        if self.short_ids:
            self.short_re = re.compile(
                r"(?<![0-9A-Za-z])(?:" + "|".join(sorted(self.short_ids)) + r")(?![0-9A-Za-z])"
            )

    def _uuid_text(self, original: str) -> str:
        h = self._digest(original)
        return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-{'89ab'[int(h[16], 16) % 4]}{h[17:20]}-{h[20:32]}"

    def _digest(self, original: str) -> str:
        return hashlib.sha256(f"{self.mapping.salt}|{original}".encode()).hexdigest()

    def _note(self, original: str, replacement: str, category: str) -> str:
        self.table.setdefault(original, (replacement, category))
        self.counts[original] += 1
        self.categories[category] += 1
        return replacement

    def _uuid(self, match: re.Match[str]) -> str:
        original = match.group(0)
        return self._note(original, self._uuid_text(original), "id: uuid")

    def _prefixed(self, match: re.Match[str]) -> str:
        original = match.group(0)
        kind, body = match.group(1), match.group(2)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        digits = int(self._digest(original), 16)
        chars = []
        for _ in body:
            digits, index = divmod(digits, len(alphabet))
            chars.append(alphabet[index])
        return self._note(original, f"{kind}_{''.join(chars)}", f"id: {kind}")

    def _hash(self, match: re.Match[str]) -> str:
        original = match.group(0)
        h = self._digest(original)
        text = (h * 2)[: len(original)]
        return self._note(original, text, "id: commit hash")

    def _number(self, match: re.Match[str]) -> str:
        """Same length, same spacing between neighbours: ids from one run stay close together."""
        original = match.group(0)
        low, span = 10 ** (len(original) - 1), 9 * 10 ** (len(original) - 1)
        offset = int(self._digest(f"number-length-{len(original)}"), 16) % span
        text = str(low + (int(original) - low + offset) % span)
        return self._note(original, text, "id: run or job number")

    def _date(self, match: re.Match[str]) -> str:
        year, month, day = (int(g) for g in match.groups()[:3])
        clock = match.groups()[3:6]
        try:
            if clock[0] is None:
                moved = date(year, month, day) + timedelta(days=self.mapping.day_shift)
                self.categories["timestamp (date part shifted)"] += 1
                return moved.isoformat()
            stamp = datetime(year, month, day, int(clock[0]), int(clock[1]), int(clock[2]))
        except ValueError:
            return match.group(0)
        stamp += timedelta(days=self.mapping.day_shift, seconds=self.mapping.time_shift_seconds)
        self.categories["timestamp (shifted)"] += 1
        return stamp.strftime("%Y-%m-%dT%H:%M:%S") + (match.group(7) or "") + "Z"

    def _epoch(self, match: re.Match[str]) -> str:
        shift = self.mapping.day_shift * 86400 + self.mapping.time_shift_seconds
        self.categories["unix time (shifted)"] += 1
        if match.group(3):
            return str(int(match.group(3)) + shift * 1000)
        return str(int(match.group(1)) + shift) + (match.group(2) or "")

    def _clock_shift(self, match: re.Match[str]) -> int:
        """The timestamps' shift, less the local offset for a time that is not already UTC."""
        utc = match.string[match.end() : match.end() + 4] == " UTC" or match.string[
            : match.start()
        ].endswith(UTC_CLOCK_PREFIXES)
        local = 0 if utc else self.mapping.local_clock_offset_seconds
        return self.mapping.time_shift_seconds - local

    def _clock(self, match: re.Match[str]) -> str:
        seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60
        has_seconds = match.re is CLOCK
        if has_seconds:
            seconds += int(match.group(3))
        moved = (seconds + self._clock_shift(match)) % 86400
        self.categories["clock time (shifted)"] += 1
        text = f"{moved // 3600:02d}:{moved % 3600 // 60:02d}"
        return f"{text}:{moved % 60:02d}" if has_seconds else text

    def _month_day(self, match: re.Match[str]) -> str:
        # The year is not written, so a fixed common year stands in: a shift across a leap day can
        # land one day off, which moves an illustration's date and reveals nothing.
        month = MONTHS.index(match.group(1)) + 1
        stamp = datetime(2001, month, int(match.group(2)), int(match.group(3) or 0))
        stamp += timedelta(days=self.mapping.day_shift, minutes=int(match.group(4) or 0))
        if match.group(3) is not None:
            stamp += timedelta(seconds=self._clock_shift(match))
        self.categories["month and day (shifted)"] += 1
        text = f"{MONTHS[stamp.month - 1]} {stamp.day:2d}"
        return f"{text} {stamp:%H:%M}" if match.group(3) is not None else text

    def _literal(self, match: re.Match[str]) -> str:
        entry = self.by_text[match.group(0)]
        return self._note(entry["from"], entry["to"], entry.get("category", "literal"))

    def text(self, value: str) -> str:
        value = self.literal.sub(self._literal, value)
        value = UUID.sub(self._uuid, value)
        if self.short_re:
            value = self.short_re.sub(
                lambda m: self._note(m.group(0), self.short_ids[m.group(0)], "id: short form"),
                value,
            )
        value = PREFIXED.sub(self._prefixed, value)
        if self.hash_re:
            value = self.hash_re.sub(self._hash, value)
        value = LONG_HASH.sub(self._hash, value)
        if self.number_re:
            value = self.number_re.sub(self._number, value)
        value = DATE.sub(self._date, value)
        if self.mapping.shift_bare_times:
            value = EPOCH.sub(self._epoch, value)
            value = MONTH_DAY.sub(self._month_day, value)
            value = CLOCK.sub(self._clock, value)
            value = CLOCK_AT.sub(self._clock, value)
            value = UPTIME.sub(self._clock, value)
        value = SECRET.sub(lambda m: self._note(m.group(0), PLACEHOLDER_TOKEN, "secret"), value)
        value = EMAIL.sub(
            lambda m: (
                m.group(0)
                if m.group(0) in {e["to"] for e in self.mapping.literals}
                else self._note(m.group(0), "user@example.com", "email")
            ),
            value,
        )
        return OTHER_HOME.sub(
            lambda m: self._note(m.group(0), m.group(1) + "dev", "home directory"), value
        )

    def value(self, node: Any) -> Any:
        if isinstance(node, str):
            return self.text(node)
        # A pull-request link record carries its number as a JSON integer, beside the same number
        # in its URL; left alone it would undo the URL's replacement. A token count that happens to
        # equal a listed number moves too, which says nothing about the session.
        if type(node) is int and self.number_re and (whole := self.number_re.fullmatch(str(node))):
            return int(self._number(whole))
        if isinstance(node, list):
            return [self.value(item) for item in node]
        if isinstance(node, dict):
            # A screenshot inside a tool's result, and its copy in `toolUseResult`, sit below the
            # message's own blocks, so the top-level image rule in `record` never sees them.
            source = node.get("source")
            if (
                node.get("type") == "image"
                and isinstance(source, dict)
                and source.get("type") != "text"
            ):
                self.categories["image replaced"] += 1
                node = {**node, "source": {"type": "text", "data": "[image omitted]"}}
            return {self.text(key): self.value(item) for key, item in node.items()}
        return node

    def record(self, record: dict[str, Any]) -> dict[str, Any]:
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(message, dict) and isinstance(content, list):
            kept = []
            for block in content:
                kind = block.get("type") if isinstance(block, dict) else None
                if kind in self.mapping.drop_blocks:
                    self.categories["thinking block dropped"] += 1
                    continue
                if kind == "image" and isinstance(block, dict):
                    self.categories["image replaced"] += 1
                    kept.append({**block, "source": {"type": "text", "data": "[image omitted]"}})
                else:
                    kept.append(block)
            record = {**record, "message": {**message, "content": kept}}
        cleaned: dict[str, Any] = self.value(record)
        if self.mapping.ai_title and cleaned.get("type") == "ai-title":
            cleaned["aiTitle"] = self.mapping.ai_title
        return cleaned


def _alternative(entry: dict[str, Any]) -> str:
    text = re.escape(entry["from"])
    return rf"(?<![A-Za-z]){text}(?![A-Za-z])" if entry.get("word") else text


def sanitize(mapping: Mapping, source: Path, target: Path) -> tuple[Sanitizer, dict[str, int]]:
    cleaner = Sanitizer(mapping)
    raw = source.read_text(encoding="utf-8")
    cleaner.learn_short_ids(raw)
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    out = [cleaner.record(record) for record in records]
    known = {record.get("uuid") for record in out if record.get("uuid")}
    orphans = 0
    for record in out:
        for key in REFERENCE_KEYS:
            target_id = record.get(key)
            if target_id and target_id not in known:
                # The cut starts mid-session, so these point at a record that is no longer here.
                record[key] = None
                orphans += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in out
        ),
        encoding="utf-8",
    )
    return cleaner, {"dangling_references_nulled": orphans, "lines": len(out)}


def originals(mapping: Mapping, source: Path) -> set[str]:
    """Everything that must not appear: the mapping's originals and every original id."""
    found = (
        {entry["from"] for entry in mapping.literals} | set(mapping.hashes) | set(mapping.numbers)
    )
    raw = source.read_text(encoding="utf-8")
    for pattern in (UUID, LONG_HASH):
        found.update(pattern.findall(raw))
    found.update(match.group(0) for match in PREFIXED.finditer(raw))
    found.update(u[:8] for u in UUID.findall(raw))
    return {item for item in found if len(item) >= 4}


def _forms(original: str) -> set[str]:
    """An original as it could sit in the output: plain, lower case, URL-encoded, JSON-escaped."""
    return {
        original,
        original.lower(),
        quote(original, safe=""),
        json.dumps(original)[1:-1],
        json.dumps(original, ensure_ascii=True)[1:-1].replace("/", "\\/"),
    }


def _structure_problems(records: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    uuids = {r.get("uuid") for r in records if r.get("uuid")}
    dangling = [r for r in records if r.get("parentUuid") and r["parentUuid"] not in uuids]
    if dangling:
        problems.append(f"{len(dangling)} parentUuid values do not resolve")
    uses: set[Any] = set()
    results: set[Any] = set()
    for record in records:
        content = (record.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                uses.add(block.get("id"))
            if isinstance(block, dict) and block.get("type") == "tool_result":
                results.add(block.get("tool_use_id"))
    if results - uses:
        problems.append(f"{len(results - uses)} tool_result ids have no tool_use")
    return problems


def _parsed(line: str) -> Any:
    try:
        return json.loads(line)
    except ValueError:
        return line  # an unparseable line is reported elsewhere; search it as text


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [text for item in node for text in _strings(item)]
    if isinstance(node, dict):
        return [text for key, item in node.items() for text in (key, *_strings(item))]
    return []


def _leak_problems(mapping: Mapping, source: Path, out_text: str) -> list[str]:
    problems: list[str] = []
    lowered = out_text.lower()
    # A run or issue number is replaced only where it stands alone in text, so it is a leak only
    # there: "4647" inside a token count of 146475, or a JSON number Claude Code wrote for a token
    # count, is a different number.
    texts = "\n".join(
        text for line in out_text.splitlines() if line.strip() for text in _strings(_parsed(line))
    )
    for original in sorted(originals(mapping, source)):
        if original.isdigit():
            if re.search(rf"(?<!\d){original}(?!\d)", texts):
                problems.append(f"original still present: {original!r}")
            continue
        for form in _forms(original):
            if form.lower() in lowered:
                problems.append(f"original still present: {original!r} (as {form!r})")
                break
    for label, pattern in SWEEPS.items():
        hits = Counter(match.group(0) for match in pattern.finditer(out_text))
        if hits:
            example = hits.most_common(1)[0][0][:60]
            problems.append(f"sweep '{label}': {sum(hits.values())} hit(s), e.g. {example!r}")
    return problems


def _scanner_problems(target: Path) -> list[str]:
    commands = {
        "gitleaks": [
            "gitleaks",
            "detect",
            "--no-git",
            "--source",
            str(target.parent),
            "--no-banner",
        ],
        "trufflehog": ["trufflehog", "filesystem", str(target)],
    }
    problems: list[str] = []
    for scanner, command in commands.items():
        if shutil.which(scanner):
            result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
            if result.returncode:
                problems.append(f"{scanner} reported findings")
    return problems


def verify(mapping: Mapping, source: Path, target: Path) -> list[str]:
    src_lines = [line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    out_text = target.read_text(encoding="utf-8")
    out_lines = [line for line in out_text.splitlines() if line.strip()]
    problems: list[str] = []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(out_lines, 1):
        try:
            records.append(json.loads(line))
        except ValueError:
            problems.append(f"line {number} is not valid JSON")
    if len(out_lines) != len(src_lines):
        problems.append(f"line count {len(out_lines)} != input {len(src_lines)}")
    return [
        *problems,
        *_structure_problems(records),
        *_leak_problems(mapping, source, out_text),
        *_scanner_problems(target),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--mapping", type=Path, required=True, help="local mapping file (holds the originals)"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--table", type=Path, help="write the original-to-replacement table here (local only)"
    )
    parser.add_argument(
        "--verify", action="store_true", help="verify the output instead of writing it"
    )
    args = parser.parse_args(argv)
    mapping = Mapping.load(args.mapping)
    if args.verify:
        problems = verify(mapping, args.input, args.output)
        for problem in problems:
            print(f"PROBLEM: {problem}")
        print("verification: " + ("FAILED" if problems else "passed"))
        return 1 if problems else 0
    cleaner, extra = sanitize(mapping, args.input, args.output)
    if args.table:
        args.table.write_text(
            json.dumps(
                {
                    k: {"to": v[0], "category": v[1], "count": cleaner.counts[k]}
                    for k, v in sorted(cleaner.table.items())
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    print(json.dumps({"replacements_by_category": dict(cleaner.categories), **extra}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
