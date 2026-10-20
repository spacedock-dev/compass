#!/usr/bin/env python3
"""Score the reading producer against marks written before it ran.

DEC-17's scoring check requires every case the
captain marked "should abstain" to come back `not verifiable from available
evidence`. `mark_abstention.py` collects the marks. This runs the producer over
the same cases and says, per case and per constraint, what it did.
The captain's accepted case review enables readings separately; this script
continues to report measured outcomes and never substitutes acceptance for PASS.
The owner's acceptance of the Claude Code producer on 2026-10-02 is the same
kind of decision: it opened that producer's gate, and every committed Claude
Code result this script wrote still says `failed`.

    score_abstention.py --report                       where the corpus stands; spends nothing
    score_abstention.py --score --producer claude      run the Claude Code producer once per case
    score_abstention.py --score --producer claude --resume
                                                       re-call only the cases the model failed
    score_abstention.py --probe-argv                   one call to a local stub; writes nothing

`--producer claude` is required to score, and is the only producer that may: no
Codex spend is authorized. A result names the producer, the model, a digest of
the argv, the destination and the CLI it ran under, and goes to its own file,
`docs/abstention/claude-results.json`, or a continuation's own fixed file beside
it. Every model call is charged first to the one ledger `abstention_ledger`
owns, which stops at 28 calls across every run (DRC-4666: the DRC-4758 ceiling
of 23, and the five more the owner authorized on 2026-10-01).

## Two corpora, two files, two questions

The marks file is DEC-17's binary check: judge or abstain, per constraint, on
recorded sessions only. The rubric expectation file is DEC-15's: which of the
five case kinds this is, what result was expected and what it should have
cited, on recorded and synthesised cases alike. They are never merged. Sharing
one file would let a synthesised fixture satisfy a gate written for recorded
sessions, and would let a binary key stand in for an expected judgement.

## What a pair lands in, and why "withheld" is its own column

Each (case, constraint) lands in exactly one of `withheld:<reason>`,
`unparsed`, `abstained`, `judged:consistent` or `judged:departure`. The first
is the one that matters most. Twenty of the twenty three cases on the machine
this was written on have an empty ledger, so the producer refuses them before
any model call. Folding that refusal into "abstained" would report a producer
that never abstains as one that always does, on a corpus that exercised it on
three sessions. A withheld case counts for neither side, is printed apart, and
is why PASS also needs the coverage floor below.

`unparsed` is kept apart from `abstained` for the same reason in miniature:
rule 2's fallback renders the same sentence on the page and is a different
fact, the model said nothing usable.

## What PASS needs

No case marked should-abstain judged; and at least one evidence-bearing,
kind-tagged, recorded case per DEC-15 kind that actually reached the model,
judged per producer: the harness of the producer being scored needs all five,
and the other harness's cases are cross-harness controls whose absent kinds
are reported as not produced (the DEC-17 amendment of 2026-09-27). A run that
names no producer keeps the original floor, both harnesses. A judge mark that abstains is
recorded and does not fail, because over-abstention is the safe direction.
The kind tags come from the rubric file's `recorded` entries, never from the
marks file, which is the captain's and is not altered.

Case format 4 replays the frozen `row_snapshot`, `producer_facts` and
`captured_at` offline. Format 5 adds a per-case `intent`, a goal and outcome
lines scored one constraint each, and a Claude Code case's checks frozen as
they stood at `captured_at` (`tool_output`). The marks bind to that packet before scoring; malformed
snapshots never fall back to today's board. Older formats retain live scoring.

The report never prints one figure for all of this and never uses the word
that would invite one: false reassurance, false alarm, missed departure and
over-abstention are four counts, and extraction (which citations hit, missed
or were extra) is a separate column from judgement.

## What this writes, and what it never touches

Two halves. `~/.compass/abstention-results.json` stays on this machine and may
carry the withheld reason and the producer's cutoff sentence. The committable
summary carries case ids (sixteen hex characters of a hash), marks, outcomes,
counts, coverage, the sha256 of the marks file as scored, and when. A later
report whose marks no longer hash to that digest says so and refuses PASS.
Replay summaries also hash the cases and rubric and refuse PASS if either moved.

The yardstick, the two constant sentences in `mark_abstention`, is handed to
`reading.produce` as a synthetic revision. Nothing is written to the
annotation store, no reading count moves, and the Intent log stays the
reader's. The disclosure this rests on is written at
[The abstention check](SECURITY.md#the-abstention-check).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import http.server
import json
import math
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, BinaryIO, Self

import abstention_ledger
import mark_abstention

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
    from typing import TypeGuard

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL = os.path.join(_ROOT, "compass", "skills", "compass")


def _runtime() -> tuple[Any, Any, Any]:
    """(config, reading, records), reached the way `mark_abstention` reaches them.

    Deferred for the reason given there: `scripts` is on mypy's path and a
    package to the tests, and a top-level runtime import makes this module
    resolvable under two names.
    """
    if _SKILL not in sys.path:
        sys.path.insert(0, _SKILL)
    from compass_runtime import config, reading, records  # noqa: PLC0415

    return config, reading, records


HOME = mark_abstention.HOME
CASES_PATH = mark_abstention.CASES_PATH
MARKS_PATH = mark_abstention.MARKS_PATH
RESULTS_PATH = os.path.join(HOME, "abstention-results.json")
RUBRIC_PATH = os.path.join(HOME, "abstention-rubric.json")
# The committable half. docs/abstention/ rather than docs/captures/, decided
# 2026-09-12: every file under captures costs a row in a README table a test
# reads, and these two files are not hook payloads.
SUMMARY_PATH = os.path.join(_ROOT, "docs", "abstention", "results.json")
# The Claude Code producer's result is its own file (DRC-4666): the Codex
# acceptance of 2026-09-14 does not qualify Claude, and one file per producer
# keeps the one from being read as the other.
CLAUDE_SUMMARY_PATH = abstention_ledger.CLAUDE_SUMMARY_PATH
# A fresh packet never overwrites the scored failure that froze the key before
# it: each continuation writes its own generation's file, which
# `abstention_ledger.result_path` names.
PRODUCERS = ("claude", "codex")
# The owner's ceiling, 28 real readings across every packet since 2026-10-01
# (DRC-4666). `abstention_ledger` owns the cap and the one ledger.
MAX_CALLS = abstention_ledger.MAX_CALLS
PASSING_CHECK_ADVERSARIES = (
    "goal-unrelated",
    "outcome-unrelated",
    "browser-unrelated",
    "stale-before-write",
    "partial-check",
)
# Where the native installer puts each Claude Code version, one file per version
# named for it. A `claude` resolving anywhere else is refused: a PATH stub
# answered as `claude-sonnet-5` in review, and nothing in the result showed it.
_CLAUDE_VERSIONS_ROOT = abstention_ledger.canonical_path(".local", "share", "claude", "versions")
CLAUDE_VERSIONS_ROOTS = () if _CLAUDE_VERSIONS_ROOT is None else (_CLAUDE_VERSIONS_ROOT,)
_CLAUDE_VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+) \(Claude Code\)$")

# DEC-15's five kinds, as the rubric file must spell them.
KIND_SUPPORTED_DEPARTURE = "supported-departure"
KIND_LEGITIMATE_CHANGE = "legitimate-change"
KIND_INCORRECT_EXECUTION = "matching-intent-incorrect-execution"
KIND_MISLEADING_COMPLETION = "misleading-completion"
KIND_INSUFFICIENT_EVIDENCE = "insufficient-evidence"
KINDS = (
    KIND_SUPPORTED_DEPARTURE,
    KIND_LEGITIMATE_CHANGE,
    KIND_INCORRECT_EXECUTION,
    KIND_MISLEADING_COMPLETION,
    KIND_INSUFFICIENT_EVIDENCE,
)
# DEC-17 names these two because their evidence shapes differ. A third
# harness may be scored; only these two are required.
COVERAGE_HARNESSES = ("claude", "codex")
# A harness's part in the floor. The producer scored needs every kind; the
# other harness's cases are cross-harness controls (owner, 2026-09-27).
COVERAGE_SCORED = "scored"
COVERAGE_CONTROL = "control"
COVERAGE_REQUIRED = "required"
# What a rubric entry's `harness` may say. Three values rather than the
# runtime's registry: the two the floor requires, and Pi, whose record
# publishes demonstrated work results (`project_context._work_evidence`), the
# only other harness this check has a reason to speak about. Anything else is refused
# rather than copied, because the field lands in a committed file and the
# rubric is hand-typed. Add a name here when a case is written for one.
RUBRIC_HARNESSES = (*COVERAGE_HARNESSES, "pi")

ORIGIN_RECORDED = "recorded"
ORIGIN_SYNTHESISED = "synthesised"
ORIGINS = (ORIGIN_RECORDED, ORIGIN_SYNTHESISED)
# A frozen case the machine's own records do not vouch for (DRC-4666, F4):
# scored, and never counted toward the recorded floor.
ORIGIN_SYNTHETIC = mark_abstention.ORIGIN_SYNTHETIC

# A case id is `sha256("<harness>|<sid>")[:16]`, and nothing else may key a
# rubric entry: the key is copied into the committed summary, and a hand-edited
# file put a session id there.
CASE_ID_RE = re.compile(r"^[0-9a-f]{16}$")

OUTCOME_ABSTAINED = "abstained"
OUTCOME_UNPARSED = "unparsed"
OUTCOME_JUDGED_CONSISTENT = "judged:consistent"
OUTCOME_JUDGED_DEPARTURE = "judged:departure"
# The claims question's fourth result (owner, 2026-10-04): a judgement, and
# never counted as a departure, which it is not.
OUTCOME_JUDGED_UNSUPPORTED = "judged:unsupported"
OUTCOME_JUDGED_NOT_REACHED = "judged:not-reached"
WITHHELD_PREFIX = "withheld:"
# Our own withheld reason, not the producer's: the board no longer lists the
# session the case was drawn from.
WITHHELD_ROW_ABSENT = "row-absent"
# Ours too: the spend ledger was full, so the case never reached the model.
WITHHELD_SPEND_CAP = "spend-cap"
# Ours: the case claims recorded and the machine's records do not vouch for it,
# so no call is spent on it (N3). A case the packet calls synthetic is not this.
WITHHELD_NOT_RECORDED = "not-recorded"

# What a judged constraint rests on, from the entries it cites. A Goal
# `consistent` resting on the agent's own account is DRC-4666's named case and
# must never be counted as tool-reported, so `tool` needs a cited check or
# written file, and `account` is anything else the agent wrote.
BASIS_TOOL = "tool"
BASIS_ACCOUNT = "account"
BASIS_PERSON = "person"
BASIS_DERIVED = "derived"

RUBRIC_CORRECT = "correct"
RUBRIC_FALSE_REASSURANCE = "false-reassurance"
RUBRIC_FALSE_ALARM = "false-alarm"
RUBRIC_MISSED_DEPARTURE = "missed-departure"
RUBRIC_OVER_ABSTENTION = "over-abstention"
# Not a sixth way of being wrong: a constraint whose expectation could not be
# read is not scored at all, and is counted here so it cannot hide inside
# `correct`.
RUBRIC_UNSCORED = "unscored:bad-expectation"
# Every constraint of a case the rubric tags is required. One with no
# expectation is not scored, and an expectation under a key the case does not
# have is counted rather than copied: the key is hand-typed. Either blocks a
# pass, since a false reassurance hid behind exactly that (review, F6).
RUBRIC_UNSCORED_MISSING = "unscored:missing-expectation"
RUBRIC_UNKNOWN = "unscored:unknown-constraint"
RUBRIC_OUTCOMES = (
    RUBRIC_CORRECT,
    RUBRIC_FALSE_REASSURANCE,
    RUBRIC_FALSE_ALARM,
    RUBRIC_MISSED_DEPARTURE,
    RUBRIC_OVER_ABSTENTION,
    RUBRIC_UNSCORED,
    RUBRIC_UNSCORED_MISSING,
    RUBRIC_UNKNOWN,
)

# Why a rubric entry may not be scored, as closed tokens. The offending value
# is never one of them and never reaches the summary.
REFUSED_SELF_VERIFIED = "self-verified"
REFUSED_KIND = "bad-kind"
REFUSED_ORIGIN = "bad-origin"
REFUSED_HARNESS = "bad-harness"
REFUSAL_SENTENCES = {
    REFUSED_SELF_VERIFIED: "generated and verified by the same agent",
    REFUSED_KIND: "the kind is not one of DEC-15's five",
    REFUSED_ORIGIN: "the origin is neither recorded nor synthesised",
    REFUSED_HARNESS: "the harness is not one this check knows",
}

VERDICT_PASSED = "passed"
VERDICT_FAILED = "failed"
VERDICT_SHORT = "short"
VERDICT_STALE = "stale"
VERDICT_BLOCKED = "blocked"

MARK_JUDGE = "judge"
MARK_ABSTAIN = "abstain"
CONSTRAINTS = ("goal", "output")

# When the yardstick was "typed". `eligibility` withholds `revision-after-end`
# when the revision is stamped after the session's end, so the stamp is one
# second past the epoch: before every session end there will ever be, and
# still a positive number `norm_epoch` accepts.
YARDSTICK_AT = 1.0

# The tokens a rubric author writes, and the sentence each becomes. Spelt here
# rather than read from `reading.RESULT_BY_TOKEN` so the rubric format is
# stable on its own; `RubricTokensMirrorTheProducerTest` holds the two equal.
RESULT_BY_TOKEN = {
    "departure": "departure",
    "consistent": "consistent with the evidence read",
    "unverifiable": "not verifiable from available evidence",
    "not_reached": "not reached at this stop",
}
_UNVERIFIABLE = RESULT_BY_TOKEN["unverifiable"]
_CONSISTENT = RESULT_BY_TOKEN["consistent"]
_DEPARTURE = RESULT_BY_TOKEN["departure"]
_NOT_REACHED = RESULT_BY_TOKEN["not_reached"]
# Spelt here for the rubric's reason above; `reading.RESULT_UNSUPPORTED`, held
# equal by `RubricTokensMirrorTheProducerTest`.
_UNSUPPORTED = "not shown by the record"
CLAIMS_RESULT_BY_TOKEN = {
    **{key: result for key, result in RESULT_BY_TOKEN.items() if key != "not_reached"},
    "unsupported": _UNSUPPORTED,
}


@dataclasses.dataclass(frozen=True)
class Corpus:
    """Everything a run reads, loaded once so a test can hand it over whole."""

    cases: Mapping[str, Any]
    marks: Mapping[str, Any]
    marks_bytes: bytes
    rubric: Mapping[str, Any]


def _get(url: str, timeout: int = 30) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed loopback
        return json.loads(response.read().decode("utf-8"))


# ------------------------------------------------------------- spend and argv

BINDING_KEYS = (
    "producer",
    "model",
    "argv_digest",
    "destination",
    "binary",
    "binary_sha256",
    "cli_version",
    "signature",
)
WITHHELD_LEDGER = "ledger-refused"


def marks_digest(corpus: Corpus) -> str:
    return hashlib.sha256(corpus.marks_bytes).hexdigest()


class _Charged:
    """One case's model behind the ledger: charged before, settled after, never past the cap."""

    def __init__(
        self,
        ledger: abstention_ledger.Ledger,
        case_id: str,
        model: Callable[..., tuple[str, str]],
        *,
        repeat: int = 1,
        retry: bool = False,
        binding: Mapping[str, str] | None = None,
        diagnostics_path: str | None = None,
    ) -> None:
        self.diagnostics_path = diagnostics_path
        self.diagnostic: dict[str, Any] | None = None
        self.repeat = repeat
        self.retry = retry
        self.binding = binding
        self.charge_id: str | None = None
        self.ledger = ledger
        self.case_id = case_id
        self.model = model
        self.unavailable_reason: str | None = getattr(model, "unavailable_reason", None)

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        from compass_runtime import observer, reading  # noqa: PLC0415 - see `_runtime`

        available = getattr(self.model, "available", None)
        if available is not None and not available():
            return "", "unavailable"
        # Only Claude needs the empty cwd, but the charged and live producers
        # share its preparation rather than predicting whether mkdir will work.
        context = (
            observer.prepare_claude_exec(
                self.model.config,
                runner=self.model.runner,
                binary_resolver=self.model.binary_resolver,
                on_diagnostic=self._diagnostic if self.diagnostics_path else None,
            )
            if isinstance(self.model, reading.ClaudeReadingModel)
            else contextlib.nullcontext(self.model)
        )
        try:
            with context as prepared:
                if self.diagnostics_path and isinstance(self.model, reading.ClaudeReadingModel):
                    self._diagnostic_directory()
                request_binding = ""
                if self.ledger.campaign is not None:
                    from analyze_campaign import (  # noqa: PLC0415 - only the new closure grant binds actual prompts
                        request_digest,
                        runtime_source_digest,
                    )

                    request_binding = request_digest(
                        prompt,
                        {k: (self.binding or {}).get(k) for k in BINDING_KEYS},
                        runtime_source_digest(pathlib.Path(observer.__file__).parent),
                        output_cap_bytes,
                    )
                charge = self.ledger.charge(
                    self.case_id,
                    repeat=self.repeat,
                    retry=self.retry,
                    request_binding=request_binding,
                )
                self.charge_id = charge
                raw, status = prepared(prompt, output_cap_bytes=output_cap_bytes)
                self.ledger.settle(charge, status)
                if self.diagnostics_path and self.diagnostic is not None:
                    self._write_diagnostic(charge, request_binding)
                return raw, status
        except observer.ClaudePreparationError as error:
            return "", error.status

    def _diagnostic(self, event: dict[str, Any]) -> None:
        self.diagnostic = event

    def _diagnostic_directory(self) -> pathlib.Path:
        if self.diagnostics_path is None:
            raise abstention_ledger.LedgerError("the diagnostic directory was not requested")
        folder = pathlib.Path(self.diagnostics_path)
        try:
            folder.mkdir(mode=0o700, exist_ok=True)
            info = folder.lstat()
            if not stat.S_ISDIR(info.st_mode) or (
                os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise OSError("diagnostic directory is not private")  # noqa: TRY301 - one closed local refusal
            fd, probe = tempfile.mkstemp(prefix=".diagnostic-write-", dir=folder)
            try:
                os.close(fd)
            finally:
                os.unlink(probe)
        except OSError as error:
            raise abstention_ledger.LedgerError(
                "the private diagnostic directory is unavailable"
            ) from error
        return folder

    def _write_diagnostic(self, charge: str, request_binding: str) -> None:
        """A failed executor must not erase the reason or refund its attempt."""
        folder = self._diagnostic_directory()
        try:
            body = {
                "v": 1,
                "charge_id": charge,
                "case_id": self.case_id,
                "repeat": self.repeat,
                "retry": self.retry,
                "request_binding": request_binding,
                "model_binding": abstention_ledger.digest(
                    {k: (self.binding or {}).get(k) for k in BINDING_KEYS}
                ),
                "diagnostic": self.diagnostic,
            }
            fd = os.open(folder / (charge + ".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(body, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise abstention_ledger.LedgerError(
                "the charged call's private diagnostic could not be saved"
            ) from error


class BinaryError(Exception):
    """The `claude` on PATH is not an installed Claude Code CLI this check can name."""


def _display_path(path: str) -> str:
    home = abstention_ledger.canonical_home()
    if home is not None and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home) :].replace(os.sep, "/")
    return path


# The native CLI's signer, measured with `codesign -dv` on 2.1.283
# (2026-09-27): "Developer ID Application: Anthropic PBC", team Q6L2SF6YDW,
# identifier com.anthropic.claude-code. Pinned as one code requirement, so a
# stub saved in the install layout, unsigned or signed by anyone else, is
# refused before it is ever run (DRC-4710, V4).
CLAUDE_TEAM_ID = "Q6L2SF6YDW"
CLAUDE_SIGNING_ID = "com.anthropic.claude-code"
CLAUDE_CODE_REQUIREMENT = (
    f'=anchor apple generic and identifier "{CLAUDE_SIGNING_ID}" '
    f'and certificate leaf[subject.OU] = "{CLAUDE_TEAM_ID}"'
)
_CODESIGN = "/usr/bin/codesign"


def _signature(real: str, *, platform: str, runner: Callable[..., Any]) -> str:
    """What vouches for the binary's origin, as a closed phrase, or a refusal.

    macOS checks the pinned requirement with `codesign`, and a missing or
    failing `codesign` refuses. No other platform checks a signature: Linux
    has none to check, and whether the Windows build carries Authenticode was
    never measured. There the binary's sha256 is recorded instead, which says
    which file ran, not who built it. SECURITY.md states that limit.
    """
    if platform == "darwin":
        try:
            result = runner(
                [_CODESIGN, "--verify", "--strict", "-R", CLAUDE_CODE_REQUIREMENT, real],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            msg = "`codesign` could not check the CLI's signature"
            raise BinaryError(msg) from error
        if getattr(result, "returncode", 1) != 0:
            msg = f"`claude` is not signed by Anthropic (team {CLAUDE_TEAM_ID})"
            raise BinaryError(msg)
        return f"Developer ID {CLAUDE_TEAM_ID} {CLAUDE_SIGNING_ID}"
    digest = hashlib.sha256()
    with open(real, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"unchecked sha256:{digest.hexdigest()}"


Identity = tuple[int, int, int, int, int, str]


def _open_cli(path: str) -> BinaryIO:
    # Nonblocking prevents a swapped FIFO from hanging before fstat; nofollow
    # refuses a new symlink after realpath. Neither flag changes regular reads.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        _metadata(os.fstat(descriptor))
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _metadata(value: os.stat_result) -> tuple[int, int, int, int, int]:
    if not stat.S_ISREG(value.st_mode):
        raise OSError("the CLI is not a regular file")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def file_identity(path: str) -> Identity:
    """The identity and sha256 of one stable regular-file handle.

    Change time catches swap-and-restore even with identical bytes/mtime.
    Sampling before and after hashing refuses a concurrent rewrite.
    """
    digest = hashlib.sha256()
    with _open_cli(path) as handle:
        before = os.fstat(handle.fileno())
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
        if _metadata(os.fstat(handle.fileno())) != _metadata(before):
            raise OSError("the CLI changed while its identity was read")
    return (*_metadata(before), digest.hexdigest())


@dataclasses.dataclass(frozen=True)
class VerifiedClaude:
    """A verified private executable, kept until scoring/probing finishes."""

    shown: str
    version: str
    path: str
    signature: str
    identity: Identity
    directory: str = dataclasses.field(default="", repr=False, compare=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.directory:
            _remove_claude_copy(self.directory, self.path)


def _remove_claude_copy(directory: str, copied: str) -> None:
    # Windows refuses to delete a read-only file. Restore owner write only
    # once the copy is no longer eligible to run, before removing its directory.
    with contextlib.suppress(OSError):
        os.chmod(copied, 0o700)
    shutil.rmtree(directory, ignore_errors=True)


class PinnedClaude:
    """Refuse changed private bytes before every call, permanently for this run.

    The installed path is no longer used after the held-handle copy. The
    owner-only directory prevents another account replacing the verified
    executable, but cannot defend against another process of this owner
    rewriting it between the identity check and spawn (SECURITY.md).
    """

    def __init__(self, path: str, identity: Identity) -> None:
        self.path = path
        self.identity = identity
        self.refused = False

    def __call__(self, _name: str) -> str | None:
        if not self.refused:
            try:
                self.refused = file_identity(self.path) != self.identity
            except OSError:
                self.refused = True
            if self.refused:
                print(
                    f"Refused: {_display_path(self.path)} changed after it was verified. "
                    "No further call runs."
                )
        return None if self.refused else self.path


MAX_CLAUDE_COPY_BYTES = 512 << 20


def _copy_claude(source: str, destination: str) -> str:
    """Copy one held regular-file handle, refusing changes during the read."""
    digest = hashlib.sha256()
    with _open_cli(source) as original:
        before = os.fstat(original.fileno())
        if before.st_size > MAX_CLAUDE_COPY_BYTES:
            raise BinaryError("`claude` exceeds the private-copy size limit")
        copied_bytes = 0
        with open(destination, "xb") as copied:
            for block in iter(lambda: original.read(1 << 20), b""):
                copied_bytes += len(block)
                if copied_bytes > MAX_CLAUDE_COPY_BYTES:
                    raise BinaryError("`claude` grew past the private-copy size limit")
                digest.update(block)
                copied.write(block)
        after = os.fstat(original.fileno())
        if _metadata(before) != _metadata(after):
            raise BinaryError("`claude` changed while its private copy was read")
    os.chmod(destination, 0o500)
    return digest.hexdigest()


def verify_claude_binary(
    *,
    resolver: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
    platform: str = sys.platform,
) -> VerifiedClaude:
    """Verify and run only a private copy of the native installed CLI.

    A single held handle supplies the bytes. The copy is checked before it
    executes even `--version`, and survives until the caller closes the
    returned context. The display path names the installation provenance;
    the identity and sha256 name the executable that actually runs.
    """
    _runtime()
    from compass_runtime import observer  # noqa: PLC0415 - see `_runtime`

    found = resolver("claude")
    if not found or not os.path.isabs(found):
        raise BinaryError("no absolute `claude` on PATH")
    real = os.path.realpath(found)
    roots = [os.path.realpath(root) for root in CLAUDE_VERSIONS_ROOTS]
    if os.path.dirname(real) not in roots:
        raise BinaryError(
            f"`claude` resolves to {_display_path(real)}, outside the installed versions"
        )
    root = observer.reading_workdir_root()
    if root is None:
        raise BinaryError("no private CLI-copy location outside the account's home")
    directory = ""
    copied = ""
    try:
        directory = tempfile.mkdtemp(prefix="reading-claude-bin-", dir=root)
        copied = os.path.join(directory, os.path.basename(real))
        digest = _copy_claude(real, copied)
        return _verify_private_claude(real, copied, digest, directory, platform, runner)
    except BaseException as error:
        if directory:
            _remove_claude_copy(directory, copied)
        if isinstance(error, (OSError, subprocess.SubprocessError)):
            raise BinaryError("the private CLI copy could not be prepared or verified") from error
        raise


def _verify_private_claude(
    source: str,
    copied: str,
    digest: str,
    directory: str,
    platform: str,
    runner: Callable[..., Any],
) -> VerifiedClaude:
    identity = file_identity(copied)
    if identity[-1] != digest:
        raise BinaryError("the private CLI copy differs from the held source bytes")
    signature = _signature(copied, platform=platform, runner=runner)
    if file_identity(copied) != identity:
        raise BinaryError("the private CLI copy changed during signature verification")
    result = runner([copied, "--version"], capture_output=True, text=True, timeout=30, check=False)
    line = str(getattr(result, "stdout", "") or "").strip()
    match = _CLAUDE_VERSION_RE.fullmatch(line)
    if getattr(result, "returncode", 1) != 0 or match is None:
        raise BinaryError("`claude --version` did not answer as Claude Code")
    if match.group(1) != os.path.basename(source):
        raise BinaryError("`claude --version` names another version than its source file")
    if file_identity(copied) != identity:
        raise BinaryError("the private CLI copy changed while it was being verified")
    return VerifiedClaude(_display_path(source), line, copied, signature, identity, directory)


class _ArgvCapturedError(Exception):
    pass


def argv_digest(producer: str, config: Any, *, claude_executor: Any = None) -> str:
    """sha256 of the argv the producer's exec would run, read without running it.

    The exec is handed a runner that records its command and raises, so no
    process starts and nothing is spent. The binary is named by its basename
    and anything under the throwaway state directory by a placeholder, so the
    digest moves with a flag, a model or an effort and with nothing else.
    """
    _runtime()
    from compass_runtime import observer  # noqa: PLC0415 - see `_runtime`

    seen: list[list[str]] = []

    def runner(command: Sequence[str], *_args: Any, **_kwargs: Any) -> Any:
        seen.append([str(part) for part in command])
        raise _ArgvCapturedError

    run = (
        (claude_executor if claude_executor is not None else observer.claude_exec)
        if producer == "claude"
        else observer.codex_exec
    )
    with tempfile.TemporaryDirectory() as state:
        scratch = dataclasses.replace(config, state_dir=pathlib.Path(state))
        with contextlib.suppress(_ArgvCapturedError):
            run(
                scratch,
                "",
                output_cap_bytes=1,
                runner=runner,
                binary_resolver=lambda name: f"/{name}",
            )
        root = str(pathlib.Path(state).resolve())
    if not seen:
        msg = f"the {producer} exec built no command"
        raise RuntimeError(msg)
    argv = [os.path.basename(seen[0][0])] + [
        "<state>" if str(pathlib.Path(part).resolve()).startswith(root) and part else part
        for part in seen[0][1:]
    ]
    return hashlib.sha256(json.dumps(argv).encode()).hexdigest()


# ---------------------------------------------------------------- pure rules


def outcome(criterion: Mapping[str, Any] | None, withheld: str) -> str:
    """Where one (case, constraint) pair lands, keeping unfinished work separate."""
    if withheld:
        return f"{WITHHELD_PREFIX}{withheld}"
    result = (criterion or {}).get("result")
    if not result:
        return OUTCOME_UNPARSED
    if result == _UNVERIFIABLE:
        return OUTCOME_ABSTAINED
    if result == _CONSISTENT:
        return OUTCOME_JUDGED_CONSISTENT
    if result in (_UNSUPPORTED, _NOT_REACHED):
        return OUTCOME_JUDGED_UNSUPPORTED if result == _UNSUPPORTED else OUTCOME_JUDGED_NOT_REACHED
    return OUTCOME_JUDGED_DEPARTURE


def rubric_outcome(expected_token: str, got: str | None, *, criterion: str = "") -> str:
    """One of five, and the three failure classes are never one class.

    `got` is the producer's published sentence, or None where rule 2 left no
    result at all. Absence is read as an abstention here, because that is
    what the page renders; the DEC-17 column keeps them apart.

    An expectation this cannot read is refused rather than defaulted. Reading a
    misspelt or missing token as `unverifiable` scored `correct` against a line
    nobody wrote, and took the matching `missed-departure` off the count. Case
    and surrounding space are forgiven exactly as `reading.parse_reply` forgives
    them in the producer's own reply, so the rubric is not stricter than the
    thing it grades.
    """
    tokens = CLAIMS_RESULT_BY_TOKEN if criterion == "claims" else RESULT_BY_TOKEN
    expected = tokens.get(expected_token.strip().casefold())
    if expected is None:
        return RUBRIC_UNSCORED
    result = got or _UNVERIFIABLE
    if result == expected:
        return RUBRIC_CORRECT
    if result == _CONSISTENT:
        return RUBRIC_FALSE_REASSURANCE
    if result == _DEPARTURE:
        return RUBRIC_FALSE_ALARM
    # The producer abstained where something was expected.
    if expected == _DEPARTURE:
        return RUBRIC_MISSED_DEPARTURE
    return RUBRIC_OVER_ABSTENTION


def extraction(expected_cites: Iterable[str], got_cites: Iterable[str]) -> dict[str, int]:
    """Which citations hit, which were missed, which were extra. Not a score."""
    wanted = {str(c) for c in expected_cites}
    got = {str(c) for c in got_cites}
    return {"hit": len(wanted & got), "miss": len(wanted - got), "extra": len(got - wanted)}


def admitted(entry: Mapping[str, Any]) -> bool:
    """Whether a rubric case may be scored at all.

    A synthesised case is admitted only when a different agent verified it than
    generated it. DEC-17 names the failure this closes, and this repository has
    recorded it once: three findings out of nine were fixture copy read back as
    specification.
    """
    if str(entry.get("origin") or "recorded") != "synthesised":
        return True
    generated = str(entry.get("generated_by") or "").strip()
    verified = str(entry.get("verified_by") or "").strip()
    return bool(generated) and bool(verified) and generated != verified


def yardstick(words: tuple[str, str]) -> list[dict[str, Any]]:
    """The two constant sentences, as the one revision `produce` reads.

    Handed in as an argument, never written to the store. Decided 2026-09-12
    against the collector's first draft, which had the scorer write and clear
    a revision: `produce` takes `revisions`, so nothing need touch
    `compass-annotations.json`, no reading count moves, and the Intent log
    stays the reader's.
    """
    goal, output = words
    return [{"n": 1, "at": YARDSTICK_AT, "goal": goal, "output": output}]


# ------------------------------------------------------------ one case scored


def _stored_name(name: str) -> str:
    """The criterion key for a constraint: the legacy `output` came back as `line_1`."""
    _config, reading, _records = _runtime()
    return reading.outcome_line(1) if name == "output" else name


def basis(criterion: Mapping[str, Any] | None, ledger: Sequence[Mapping[str, Any]]) -> str:
    """What a judged criterion rests on, as a closed token; empty where nothing was judged."""
    _config, reading, _records = _runtime()
    if not criterion or criterion.get("result") not in (_CONSISTENT, _DEPARTURE):
        return ""
    wanted = {str(c) for c in criterion.get("cites") or ()}
    cited = [entry for entry in ledger if str(entry.get("id")) in wanted]
    # A check with a recorded result, and nothing else: a written file shows
    # the agent acted, not that anything checked it (review, F8), so a Goal
    # resting on one is the agent's account.
    if any(
        entry.get("type") == reading.TOOL_REPORT_TYPE
        and entry.get("subject") == reading.CHECK_SUBJECT
        and entry.get("result") in (reading.RESULT_PASSED, reading.RESULT_FAILED)
        for entry in cited
    ):
        return BASIS_TOOL
    authors = {entry.get("author") for entry in cited}
    if reading.AUTHOR_AGENT in authors:
        return BASIS_ACCOUNT
    if reading.AUTHOR_PERSON in authors:
        return BASIS_PERSON
    return BASIS_DERIVED if authors else ""


def _production_source(case: Mapping[str, Any]) -> Mapping[str, Any]:  # noqa: C901, PLR0912 - closed prospective source schema
    """Require the typed Claude protocol; presence alone never proves source parity."""
    frozen = case.get("production_reading")
    fields = {
        "v",
        "prefix_digest",
        "person_wanted",
        "person_words_digest",
        "final_wanted",
        "newest_final",
        "prompt_digest",
        "constraints",
    }
    if (
        not isinstance(frozen, dict)
        or set(frozen) != fields
        or type(frozen.get("v")) is not int
        or frozen["v"] != 1
    ):
        raise mark_abstention.FreezeError("production-source-invalid")
    reading = _runtime()[1]
    revision = mark_abstention.case_revision(dict(case))
    if (
        case.get("harness") != "claude"
        or revision.get("goal_source") in reading.PROMPT_SOURCES
        or reading.has_line_requests(revision)
    ):
        raise mark_abstention.FreezeError("production-intent-source-unsupported")
    for key in ("prefix_digest", "person_words_digest", "prompt_digest"):
        if not isinstance(frozen[key], str) or re.fullmatch(r"[0-9a-f]{64}", frozen[key]) is None:
            raise mark_abstention.FreezeError("production-source-invalid")
    for key, kind in (
        ("person_wanted", "user_message"),
        ("final_wanted", reading.AGENT_MESSAGE_TYPE),
    ):
        rows = frozen[key]
        if not isinstance(rows, list) or any(
            not isinstance(row, dict)
            or set(row) != {"id", "type", "author", "at"}
            or row.get("type") != kind
            or not all(isinstance(row.get(name), str) and row[name] for name in ("id", "author"))
            or type(row.get("at")) not in (int, float)
            or not math.isfinite(row["at"])
            for row in rows
        ):
            raise mark_abstention.FreezeError("production-selection-invalid")
    names = list(reading.constraints_for(reading.outcome_lines(revision)))
    if frozen["constraints"] not in (names, [*names, reading.CONSTRAINT_CLAIMS]):
        raise mark_abstention.FreezeError("production-constraints-invalid")
    final = frozen["newest_final"]
    if final is not None:
        if not isinstance(final, dict) or final.get("outcome") not in {
            "none",
            "source-moved",
            "scan-limit",
            "oversized",
            "unproven",
            "not-final",
            "ambiguous",
            "too-long",
            "whole",
        }:
            raise mark_abstention.FreezeError("production-final-invalid")
        expected = {"outcome"}
        if final["outcome"] in ("too-long", "whole"):
            expected |= {"fact_id", "at"}
            if (
                not isinstance(final.get("fact_id"), str)
                or not final["fact_id"]
                or (type(final.get("at")) not in (int, float) or not math.isfinite(final["at"]))
            ):
                raise mark_abstention.FreezeError("production-final-invalid")
        if final["outcome"] == "whole":
            expected.add("words_digest")
            if (
                not isinstance(final.get("words_digest"), str)
                or re.fullmatch(r"[0-9a-f]{64}", final["words_digest"]) is None
            ):
                raise mark_abstention.FreezeError("production-final-invalid")
        if set(final) != expected:
            raise mark_abstention.FreezeError("production-final-invalid")
    return frozen


class _SourcePinnedModel:
    """Validate the frozen actual source prompt before any charging wrapper."""

    def __init__(
        self,
        inner: Any,
        expected: str,
        *,
        reviewed_exports: mark_abstention.ReviewedExports | None = None,
        case: Mapping[str, Any] | None = None,
        config: Any = None,
    ) -> None:
        self.inner = inner
        self.expected = expected
        self.unavailable_reason = getattr(inner, "unavailable_reason", "model-unavailable")
        self.reviewed_exports = reviewed_exports
        self.case = case
        self.config = config

    def available(self) -> bool:
        return bool(getattr(self.inner, "available", lambda: True)())

    def __call__(self, prompt: str, **kwargs: Any) -> tuple[str, str]:
        if hashlib.sha256(prompt.encode()).hexdigest() != self.expected:
            raise mark_abstention.FreezeError("production-prompt-differs")
        if self.case is not None and "reviewed_export" in self.case:
            mark_abstention.revalidate_reviewed_export(
                dict(self.case), self.reviewed_exports, self.config
            )
        return self.inner(prompt, **kwargs)  # type: ignore[no-any-return]


def score_case(  # noqa: PLR0913 - one keyword per thing a case decides
    config: Any,
    case: Mapping[str, Any],
    row: Mapping[str, Any] | None,
    facts: Sequence[Mapping[str, Any]],
    mark: Mapping[str, Any],
    *,
    model: Callable[..., tuple[str, str]],
    now: float,
    words: tuple[str, str] = ("", ""),
    revision: Mapping[str, Any] | None = None,
    tool_output: Any = None,
    withhold: str = "",
    read_agent_words: bool = False,
    reviewed_exports: mark_abstention.ReviewedExports | None = None,
) -> dict[str, Any]:
    """One producer call, classified. The only place the model is reached.

    `revision` is a format 5 case's own intent; without one the yardstick
    `words` stand in, as they always did. `tool_output` is the frozen checks,
    handed to `produce` exactly as the reading route hands a press's.
    """
    _config, reading, _records = _runtime()
    revisions = [dict(revision)] if revision is not None else yardstick(words)
    lines = reading.outcome_lines(revisions[-1])
    names = CONSTRAINTS if revision is None else tuple(reading.constraints_for(lines))
    marks = {name: str(mark.get(name) or "") for name in names}
    harness = str((row or {}).get("harness") or case.get("harness") or "")
    if withhold or row is None:
        assessment, why, spent = None, withhold or WITHHELD_ROW_ABSENT, False
    else:
        try:
            mark_abstention.revalidate_reviewed_export(dict(case), reviewed_exports, config)
            source_kwargs: dict[str, Any] = {}
            if "production_reading" in case:
                frozen = _production_source(case)
                names = tuple(frozen["constraints"])
                source_kwargs = {
                    "person_source_lookup": mark_abstention.native_case_person_lookup(
                        dict(case), config=config, reviewed_exports=reviewed_exports
                    ),
                    "final_source_lookup": mark_abstention.native_case_final_lookup(
                        dict(case), config=config, reviewed_exports=reviewed_exports
                    ),
                }
                model = _SourcePinnedModel(
                    model,
                    str(frozen["prompt_digest"]),
                    reviewed_exports=reviewed_exports,
                    case=case,
                    config=config,
                )
                read_agent_words = True
            assessment, why, spent = reading.produce(
                config,
                row,
                revisions,
                facts,
                now=now,
                stamp_text="abstention check",
                model=model,
                tool_output=tool_output,
                # The outcome lines are asked as the reading route asks them;
                # the yardstick's one output line comes back as `line_1`.
                read_lines=True,
                read_agent_words=read_agent_words,
                # As the route passes it: a reader's press on a harness that
                # may be read at a turn stop, and nowhere else.
                admit_turn_stop=harness in reading.TURN_STOP_HARNESSES,
                # Not the idle admission of 2026-10-20: these cases were marked under the
                # earlier rule, which withheld an idle session with no recorded finish, and
                # re-scoping the check is the owner's decision, not this replay's.
                admit_idle=False,
                **source_kwargs,
            )
        except abstention_ledger.SpendCapError:
            assessment, why, spent = None, WITHHELD_SPEND_CAP, False
        except abstention_ledger.LedgerError:
            assessment, why, spent = None, WITHHELD_LEDGER, False
        except mark_abstention.FreezeError:
            assessment, why, spent = None, "production-source-refused", False
    stored = assessment["criteria"] if assessment else {}
    # Legacy packets retain their old questions. Prospective source freezes
    # bind the actual claims question before output and replay the same source.
    if reading.CONSTRAINT_CLAIMS in stored and reading.CONSTRAINT_CLAIMS not in names:
        names = (*names, reading.CONSTRAINT_CLAIMS)
    marks = {name: str(mark.get(name) or "") for name in names}
    criteria = {name: stored[_stored_name(name)] for name in names if _stored_name(name) in stored}
    # The producer's own predicate over the ledger it read, so the scorer
    # cannot call a column asked that `resolve` answered without asking. Where
    # the record holds no work evidence the outcome lines are never posed and
    # the producer returns `not verifiable` unasked, so those columns are the
    # ruling's answer. The ledger carries the frozen checks where the case
    # does; the predicate reads the whole of it where `produce` reads its
    # selection, which only differs when the byte bound drops work.
    tails = tool_output.tails if tool_output is not None and tool_output.destination else None
    ledger = reading.build_ledger(
        facts,
        harness,
        str((row or {}).get("sid") or ""),
        tool_output=tails,
        changed_after=tool_output.changed_after if tool_output is not None else frozenset(),
        read_incomplete=tool_output.read_incomplete if tool_output is not None else frozenset(),
    )
    return {
        "id": str(case.get("id") or ""),
        "harness": str(case.get("harness") or ""),
        "constraints": list(names),
        "marks": marks,
        "outcomes": {name: outcome(criteria.get(name), why) for name in names},
        "basis": {name: basis(criteria.get(name), ledger) for name in names},
        "reached_model": assessment is not None,
        "asks_output": row is not None and bool(reading.asks_output(" ".join(lines), ledger)),
        "spent": spent,
        # Local-half fields. `summarize` copies none of them.
        "withheld": why,
        "cutoff": str(assessment["cutoff"]) if assessment else "",
        "criteria": criteria,
    }


def _names(record: Mapping[str, Any] | None) -> tuple[str, ...]:
    return tuple((record or {}).get("constraints") or CONSTRAINTS)


def rubric_refusal(entry: Mapping[str, Any], harness: str) -> str:
    """Why this entry may not be scored, as a closed token. Empty admits it.

    Every field below is hand-typed and three of them are copied into a
    committed file, so each is checked against a closed set rather than
    `str()`-ed through. A rubric file with a session id where the kind should
    be put that session id under `docs/`.
    """
    if str(entry.get("origin") or ORIGIN_RECORDED) not in ORIGINS:
        return REFUSED_ORIGIN
    if str(entry.get("kind") or "") not in KINDS:
        return REFUSED_KIND
    if not harness:
        return REFUSED_HARNESS
    if not admitted(entry):
        return REFUSED_SELF_VERIFIED
    return ""


def rubric_harness(entry: Mapping[str, Any], record: Mapping[str, Any] | None) -> str:
    """Which harness this case is, or empty where the entry may not say.

    A recorded case takes it from the record, never from the rubric: the
    harness is a collector fact, and the coverage floor is the only thing
    between an all-Claude corpus and PASS, so five Claude cases tagged `codex`
    by hand would meet the Codex half of it.
    """
    if record is not None:
        return str(record.get("harness") or "")
    named = str(entry.get("harness") or "")
    return named if named in RUBRIC_HARNESSES else ""


def _required(record: Mapping[str, Any] | None) -> tuple[str, ...]:
    """The constraints a rubric entry must expect: the goal, and each line that was asked."""
    names = _names(record)
    if record is not None and not record.get("asks_output", True):
        return names[:1]
    return names


def rubric_case(
    entry: Mapping[str, Any],
    record: Mapping[str, Any] | None,
    case_id: str,
    *,
    case_origin: str | None = None,
) -> dict[str, Any]:
    """One rubric entry scored against the producer's record for that case.

    `case_origin` is the packet's own word for the case. It wins over the
    entry's, which is hand-typed: a frozen case the machine's records did not
    vouch for stays synthetic whatever the rubric says.
    """
    harness = rubric_harness(entry, record)
    refused = rubric_refusal(entry, harness)
    is_admitted = not refused
    reached = bool(record and record["reached_model"]) and is_admitted
    raw_expect = entry.get("expect")
    expect: dict[str, Any] = raw_expect if isinstance(raw_expect, dict) else {}
    judgement: dict[str, str] = {}
    cites: dict[str, dict[str, int]] = {}
    criteria = record["criteria"] if record and reached else {}
    required = _required(record)
    for name in _names(record):
        wanted = expect.get(name) if isinstance(expect.get(name), dict) else None
        if not reached:
            continue
        if wanted is None:
            if name in required:
                judgement[name] = RUBRIC_UNSCORED_MISSING
            continue
        got = criteria.get(name) or {}
        judgement[name] = rubric_outcome(
            str(wanted.get("result") or ""), got.get("result"), criterion=name
        )
        cites[name] = extraction(wanted.get("cites") or (), got.get("cites") or ())
    unknown = sum(1 for key in expect if key not in _names(record)) if reached else 0
    kind = str(entry.get("kind") or "")
    origin = case_origin or str(entry.get("origin") or ORIGIN_RECORDED)
    return {
        "id": case_id,
        # Closed tokens or nothing. A refused entry keeps its refusal, not the
        # value that earned it.
        "kind": kind if kind in KINDS else "",
        "harness": harness,
        "origin": origin if origin in (*ORIGINS, ORIGIN_SYNTHETIC) else "",
        "admitted": is_admitted,
        "refused": refused,
        # Whether the producer ran on this id at all. An entry with no record
        # is not a case the model withheld; nothing was asked of it.
        "scored": record is not None,
        "reached_model": reached,
        "judgement": judgement,
        "extraction": cites,
        "unknown_expectations": unknown,
    }


def _fully_scored(record: Mapping[str, Any]) -> bool:
    return not record.get("unknown_expectations") and not any(
        str(got).startswith("unscored:") for got in (record.get("judgement") or {}).values()
    )


# ------------------------------------------------------------------ summary


def _dec17(records: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Which cases failed the binary check, and which abstained on a judge mark."""
    failed: list[str] = []
    held: list[str] = []
    for record in records:
        for name in _names(record):
            mark, got = record["marks"].get(name), record["outcomes"][name]
            if mark == MARK_ABSTAIN and got.startswith("judged:"):
                failed.append(record["id"])
            elif mark == MARK_JUDGE and got in (OUTCOME_ABSTAINED, OUTCOME_UNPARSED):
                held.append(record["id"])
    return {"failed": sorted(set(failed)), "held": sorted(set(held))}


def _coverage(
    rubric_records: Sequence[Mapping[str, Any]], producer: str = ""
) -> dict[str, dict[str, Any]]:
    """Kinds per required harness that a recorded case carried to the model.

    Recorded only: DEC-17 asks for one recorded session per kind, and a
    synthesised case satisfying it would be the substitution the two-corpora
    rule exists to refuse. Withheld cases count for nothing here, whatever
    kind they are tagged with: a producer that never saw the case proved
    nothing about the kind.

    Judged per producer (owner ruling of 2026-09-27, the DEC-17 amendment of
    that date). The harness of the producer being scored is `scored` and
    needs every kind; the other is a cross-harness `control`, and its absent
    kinds are `not_produced`, never `missing`. A run that names no producer
    keeps both `required`, the floor every earlier summary was scored under.
    """
    out: dict[str, dict[str, Any]] = {}
    for harness in COVERAGE_HARNESSES:
        kinds = {
            str(r["kind"])
            for r in rubric_records
            if r["harness"] == harness
            and r["origin"] == "recorded"
            and r["admitted"]
            and r["reached_model"]
            and r["kind"] in KINDS
            and _fully_scored(r)
        }
        absent = [k for k in KINDS if k not in kinds]
        role = (
            COVERAGE_REQUIRED
            if producer not in COVERAGE_HARNESSES
            else COVERAGE_SCORED
            if harness == producer
            else COVERAGE_CONTROL
        )
        control = role == COVERAGE_CONTROL
        out[harness] = {
            "kinds": len(kinds),
            "role": role,
            "missing": [] if control else absent,
            "not_produced": absent if control else [],
        }
    return out


def _verdict(
    dec17: Mapping[str, list[str]],
    coverage: Mapping[str, Mapping[str, Any]],
    rubric_counts: Mapping[str, int] | None = None,
) -> str:
    # A rubric false reassurance fails the run as a judged should-abstain mark
    # does: it is the failure DEC-17 exists to catch, and DEC-23's surviving
    # class, a `consistent` on a line a passing check does not cover, is often
    # visible only to the rubric (decision of 2026-09-24).
    counts = rubric_counts or {}
    if dec17["failed"] or counts.get(RUBRIC_FALSE_REASSURANCE, 0):
        return VERDICT_FAILED
    if any(count for name, count in counts.items() if name.startswith("unscored:")):
        return VERDICT_BLOCKED
    # `missing`, not `kinds`: a control's absent kinds are never short, and a
    # coverage entry written before roles existed carries `missing` too.
    if any(coverage[h]["missing"] for h in COVERAGE_HARNESSES if h in coverage):
        return VERDICT_SHORT
    return VERDICT_PASSED


def summarize(
    records: Sequence[Mapping[str, Any]],
    *,
    marks: Mapping[str, Any],  # noqa: ARG001 - kept for callers; see the "marks" key below
    marks_bytes: bytes,
    now: float,
    rubric_records: Sequence[Mapping[str, Any]] = (),
    binding: Mapping[str, str] | None = None,
    transcript_stops: Collection[str] = (),
) -> dict[str, Any]:
    """The committable half. Ids, marks, outcomes, counts, coverage, digest, when.

    Nothing readable about a session: no sid, no project, no title, no ask,
    no intent, no check or its output, no cutoff sentence and no model prose.
    The local half carries those. `binding` names the producer, its model and
    the argv digest the run used, closed values the scorer computed.
    """
    outcome_counts: dict[str, int] = {}
    for record in records:
        for name in _names(record):
            got = str(record["outcomes"][name])
            key = "withheld" if got.startswith(WITHHELD_PREFIX) else got
            outcome_counts[key] = outcome_counts.get(key, 0) + 1
    rubric_counts = dict.fromkeys(RUBRIC_OUTCOMES, 0)
    for entry in rubric_records:
        for got in entry["judgement"].values():
            rubric_counts[got] = rubric_counts.get(got, 0) + 1
        rubric_counts[RUBRIC_UNKNOWN] += int(entry.get("unknown_expectations") or 0)
    dec17 = _dec17(records)
    coverage = _coverage(rubric_records, str((binding or {}).get("producer") or ""))
    bound = {key: str((binding or {})[key]) for key in BINDING_KEYS if key in (binding or {})}
    return {
        **bound,
        "v": 1,
        "scored_at": now,
        "marks_digest": hashlib.sha256(marks_bytes).hexdigest(),
        # From the scored records only, as closed tokens: the marks file is
        # hand-editable, and a note or an orphan key in it reached the
        # committed file once (review, F5). `marks` is the caller's parsed
        # file and is deliberately not read here.
        "marks": {r["id"]: _closed_marks(r) for r in records if CASE_ID_RE.fullmatch(r["id"])},
        "cases": {
            r["id"]: {
                "harness": r["harness"],
                "marks": _closed_marks(r),
                "outcomes": dict(r["outcomes"]),
                "reached_model": bool(r["reached_model"]),
                "asks_output": bool(r.get("asks_output", True)),
                "basis": {
                    k: v
                    for k, v in (r.get("basis") or {}).items()
                    if v in ("", BASIS_TOOL, BASIS_ACCOUNT, BASIS_PERSON, BASIS_DERIVED)
                },
            }
            for r in records
        },
        "counts": {
            "cases": len(records),
            "reached_model": sum(1 for r in records if r["reached_model"]),
            "withheld": sum(1 for r in records if not r["reached_model"]),
            "output_not_asked": sum(1 for r in records if not r.get("asks_output", True)),
            "goal_consistent_on_account": sum(
                1
                for r in records
                if r["outcomes"].get("goal") == OUTCOME_JUDGED_CONSISTENT
                and (r.get("basis") or {}).get("goal") == BASIS_ACCOUNT
            ),
            "outcomes": outcome_counts,
            # Recorded cases whose turn stop the transcript vouched for, because
            # the history store had rolled past it (DEC-17, amended 2026-10-01).
            "recorded_on_transcript_stop": sum(
                1
                for r in rubric_records
                if r["origin"] == ORIGIN_RECORDED and r["id"] in transcript_stops
            ),
        },
        "dec17": dec17,
        "coverage": coverage,
        "rubric": {
            "cases": {
                r["id"]: {
                    "kind": r["kind"],
                    "harness": r["harness"],
                    "origin": r["origin"],
                    "admitted": r["admitted"],
                    "refused": str(r.get("refused") or ""),
                    "scored": bool(r.get("scored", True)),
                    "reached_model": r["reached_model"],
                    "judgement": dict(r["judgement"]),
                    "extraction": {k: dict(v) for k, v in r["extraction"].items()},
                    "unknown_expectations": int(r.get("unknown_expectations") or 0),
                }
                for r in rubric_records
            },
            "counts": rubric_counts,
        },
        "verdict": _verdict(dec17, coverage, rubric_counts),
    }


def _closed_marks(record: Mapping[str, Any]) -> dict[str, str]:
    marks = record.get("marks") or {}
    return {
        name: str(marks.get(name)) if marks.get(name) in (MARK_JUDGE, MARK_ABSTAIN) else ""
        for name in _names(record)
    }


def check_marks(summary: Mapping[str, Any], marks_bytes: bytes) -> dict[str, Any]:
    """The summary, stale if the marks no longer hash to what was scored.

    A mark written after seeing an output is agreement, not a mark. Nothing
    here can tell which way a mark moved, so any movement refuses PASS.
    """
    out = dict(summary)
    if hashlib.sha256(marks_bytes).hexdigest() != summary.get("marks_digest"):
        out["verdict"] = VERDICT_STALE
    return out


def local_results(
    records: Sequence[Mapping[str, Any]], summary: Mapping[str, Any], *, home: str
) -> dict[str, Any]:
    """The half that stays on this machine: the reasons and the sentences."""
    return {
        "v": 1,
        "home": home,
        "summary": dict(summary),
        "cases": {
            r["id"]: {"withheld": r["withheld"], "cutoff": r["cutoff"], "spent": r["spent"]}
            for r in records
        },
        # Whole, for `--resume`, which re-scores only the model's failures
        # and carries every other record over as it was.
        "records": {r["id"]: dict(r) for r in records},
    }


def exit_code(summary: Mapping[str, Any]) -> int:
    """Non-zero only for a failed check. Short and stale print, and exit 0."""
    return 1 if summary.get("verdict") == VERDICT_FAILED else 0


# ----------------------------------------------------------------- rendering


def _pair_phrase(name: str, mark: str, got: str, *, asks_output: bool) -> str:
    if got.startswith(WITHHELD_PREFIX):
        return "withheld before the model, proves nothing about it"
    if name != "goal" and not asks_output:
        return "not asked, nothing it read shows work: the ruling's answer, not a measurement"
    if got == OUTCOME_UNPARSED:
        # Named before the marks are consulted, because it answers neither
        # mark: the page renders rule 2's fallback as the abstention sentence,
        # and calling it one here would report a model that said nothing usable
        # as a model that abstained.
        return "unparsed: no usable verdict, rendered on the page as an abstention"
    if mark == MARK_ABSTAIN:
        return (
            "abstained as marked"
            if got == OUTCOME_ABSTAINED
            else "a case marked should-abstain judged"
        )
    if got == OUTCOME_ABSTAINED:
        return "abstained on a judge mark: recorded, not a failure"
    return "judged as marked"


def case_line(record: Mapping[str, Any]) -> str:
    asks_output = bool(record.get("asks_output", True))
    parts = []
    for name in _names(record):
        mark, got = str(record["marks"].get(name) or ""), str(record["outcomes"][name])
        phrase = _pair_phrase(name, mark, got, asks_output=asks_output)
        parts.append(f"{name} {mark or '?'} -> {got} ({phrase})")
    return f"  {record['id']}  " + "; ".join(parts)


def rubric_line(case_id: str, name: str, judgement: str, cites: Mapping[str, int]) -> str:
    return (
        f"  {case_id}  {name}: judgement {judgement}; cites hit {cites['hit']}, "
        f"miss {cites['miss']}, extra {cites['extra']}"
    )


def _render_rubric(summary: Mapping[str, Any]) -> list[str]:
    rubric = summary.get("rubric") or {}
    cases = rubric.get("cases") or {}
    if not cases:
        return ["Rubric (DEC-15): no expectation file was scored."]
    lines = ["Rubric (DEC-15), judgement and extraction as two columns:"]
    for name, count in (rubric.get("counts") or {}).items():
        lines.append(f"  {name}: {count}")
    for case_id, entry in cases.items():
        if not entry["admitted"]:
            reason = str(entry.get("refused") or REFUSED_SELF_VERIFIED)
            lines.append(f"  {case_id}  not admitted: {REFUSAL_SENTENCES.get(reason, reason)}")
            continue
        if not entry.get("scored", True):
            lines.append(f"  {case_id}  no case with this id was scored")
            continue
        if not entry["reached_model"]:
            lines.append(f"  {case_id}  withheld before the model, proves nothing about it")
            continue
        lines.extend(
            rubric_line(
                case_id,
                name,
                judgement,
                entry["extraction"].get(name) or {"hit": 0, "miss": 0, "extra": 0},
            )
            for name, judgement in entry["judgement"].items()
        )
        if entry.get("unknown_expectations"):
            lines.append(
                f"  {case_id}  {entry['unknown_expectations']} expectations under keys this case "
                "does not have: not scored, and PASS is refused"
            )
    return lines


def render(summary: Mapping[str, Any]) -> list[str]:
    """The report. Counts and names, never one figure for the whole."""
    if summary.get("v") == 2 and summary.get("protocol") == "closure-three-repeats":
        counts = summary["counts"]
        return [
            (
                f"Closure qualification: 3 repetitions; {counts['unique_cases']} unique cases, "
                f"{counts['registered_exposures']} exposures; {counts['attempts']} charged."
            ),
            *[f"  repeat {r['repeat']}: {r['summary']['verdict']}" for r in summary["repetitions"]],
            f"Verdict: {summary['verdict']}; original failed studies remain unchanged.",
        ]
    counts = summary["counts"]
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(summary["scored_at"]))
    lines = [
        f"Abstention check (DEC-17), scored {stamp}, marks digest {summary['marks_digest'][:16]}",
        (
            f"  {counts['cases']} cases: {counts['reached_model']} reached the model, "
            f"{counts['withheld']} withheld before it (counted for neither side)"
        ),
    ]
    if summary.get("producer"):
        lines.append(
            f"  producer {summary['producer']}, model {summary.get('model') or '?'}, "
            f"argv digest {str(summary.get('argv_digest') or '')[:16]}"
        )
    lines.extend(f"  {name}: {count}" for name, count in sorted(counts["outcomes"].items()))
    if counts.get("goal_consistent_on_account"):
        lines.append(
            f"  goal judged consistent on the agent's own account, no check cited: "
            f"{counts['goal_consistent_on_account']} (never counted as tool-reported)"
        )
    if counts.get("recorded_on_transcript_stop"):
        lines.append(
            f"  recorded on a turn stop its transcript vouched for, the history store having "
            f"rolled past it: {counts['recorded_on_transcript_stop']}"
        )
    if counts.get("output_not_asked"):
        lines.append(
            f"  output column not asked on {counts['output_not_asked']} of {counts['cases']} "
            "cases: the collector fixes abstain there, so that column is the ruling's answer, "
            "not a measurement"
        )
    dec17 = summary["dec17"]
    if dec17["failed"]:
        lines.append("a case marked should-abstain judged: " + ", ".join(dec17["failed"]))
    else:
        lines.append("No case marked should-abstain judged.")
    lines.extend(
        f"  {case_id} abstained on a judge mark: recorded, not a failure"
        for case_id in dec17["held"]
    )
    lines.append("Coverage, recorded cases that reached the model:")
    lines.extend(_coverage_lines(summary["coverage"]))
    lines.extend(_render_rubric(summary))
    lines.append(_verdict_sentence(summary))
    return lines


_ROLE_WORDS = {
    COVERAGE_SCORED: " (the producer scored: every kind required)",
    COVERAGE_CONTROL: " (cross-harness control: counted neither short nor covered)",
}


def _coverage_lines(coverage: Mapping[str, Mapping[str, Any]]) -> list[str]:
    lines = []
    for harness, cover in coverage.items():
        role = _ROLE_WORDS.get(str(cover.get("role") or ""), "")
        kinds = f"{cover['kinds']} of {len(KINDS)} kinds reached the model"
        gaps = ""
        if cover.get("missing"):
            gaps += f" (missing: {', '.join(cover['missing'])})"
        if cover.get("not_produced"):
            gaps += f" (not produced: {', '.join(cover['not_produced'])})"
        lines.append(f"  {harness}{role}: {kinds}{gaps}")
    return lines


def _verdict_sentence(summary: Mapping[str, Any]) -> str:  # noqa: PLR0911 - one per verdict
    verdict = summary["verdict"]
    if verdict == VERDICT_STALE:
        return (
            "STALE: marks changed after scoring. The marks predate nothing this run "
            "recorded, so PASS is refused. Score again against the marks as they are."
        )
    if verdict == VERDICT_FAILED:
        if not (summary.get("dec17") or {}).get("failed"):
            return "FAILED: the rubric records a false reassurance."
        return "FAILED: a case marked should-abstain judged."
    if verdict == VERDICT_BLOCKED:
        return (
            "BLOCKED: the rubric left a required judgement unscored, a constraint with no "
            "expectation, one it cannot read, or an expectation under a key the case lacks. "
            "PASS is refused until every required judgement is scored."
        )
    if verdict == VERDICT_SHORT:
        scored = [
            h
            for h, cover in (summary.get("coverage") or {}).items()
            if cover.get("role") == COVERAGE_SCORED
        ]
        where = f"on {scored[0]}, the producer scored" if scored else "on both Claude and Codex"
        return (
            "SHORT: no failure, and PASS is refused because the coverage floor is not met. "
            "It wants one evidence-bearing, kind-tagged recorded case per DEC-15 kind "
            f"{where}, each reaching the model."
        )
    unparsed = int((summary["counts"].get("outcomes") or {}).get(OUTCOME_UNPARSED, 0))
    if unparsed:
        return (
            f"PASSED: no should-abstain case was judged, and the coverage floor is met. "
            f"{unparsed} pairs were unparsed rather than abstentions: the model said nothing "
            "usable, and the page renders that as the same sentence."
        )
    return "PASSED: every should-abstain case abstained, and the coverage floor is met."


# --------------------------------------------------------------- the two runs


def _synthesised(entry: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A synthesised case's row and facts, scrubbed the way a real record is.

    Everything here was written by an agent, so it goes through `safe_text`
    before it reaches the producer: redaction before the clip, the order
    `records.safe_text` owns.
    """
    _config, reading, records = _runtime()
    given = entry.get("row")
    raw_row: dict[str, Any] = given if isinstance(given, dict) else {}
    row = {
        "harness": records.safe_text(raw_row.get("harness"), 32),
        "sid": records.safe_text(raw_row.get("sid"), 160),
        "state": records.safe_text(raw_row.get("state"), 32),
        "ended_at": raw_row.get("ended_at"),
        "finished_at": raw_row.get("finished_at"),
    }
    facts: list[dict[str, Any]] = []
    for fact in entry.get("facts") or ():
        if not isinstance(fact, dict):
            continue
        raw_evidence = fact.get("evidence")
        evidence: dict[str, Any] = raw_evidence if isinstance(raw_evidence, dict) else {}
        facts.append(
            {
                "fact_id": records.safe_text(fact.get("fact_id"), 160),
                "type": records.safe_text(fact.get("type"), 64),
                "by": records.safe_text(fact.get("by"), 64),
                "summary": records.safe_text(fact.get("summary"), reading.LEDGER_SUMMARY_CAP_CHARS),
                "at": fact.get("at"),
                "evidence": {
                    "source": records.safe_text(evidence.get("source"), 160),
                    "confidence": records.safe_text(evidence.get("confidence"), 32),
                },
                "source_session": {"harness": row["harness"], "sid": row["sid"]},
            }
        )
    return row, facts


def _board_rows(port: int) -> dict[tuple[str, str], dict[str, Any]] | None:
    try:
        payload = _get(f"http://127.0.0.1:{port}/api/data?all=1")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        print(f"Could not read the board on port {port}: {error}")
        return None
    return {
        (str(r.get("harness") or ""), str(r.get("sid") or "")): r
        for r in payload.get("sessions") or []
        if isinstance(r, dict)
    }


def _board_facts(port: int, case: Mapping[str, Any]) -> list[dict[str, Any]]:
    project = str(case.get("project") or "")
    if not project:
        return []
    query = urllib.parse.urlencode(
        {"project": project, "session": f"{case.get('harness')}:{case.get('sid')}"}
    )
    try:
        body = _get(f"http://127.0.0.1:{port}/api/project-context?{query}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return []
    facts = ((body or {}).get("semantic") or {}).get("facts") or []
    return [f for f in facts if isinstance(f, dict)]


def _rubric_entries(rubric: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = rubric.get("cases")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict) and CASE_ID_RE.match(str(k))}


def _epoch(value: Any) -> TypeGuard[float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def replay_refusal(case: Mapping[str, Any], *, synthetic_ok: bool = False) -> str:
    """Closed reasons only: neither malformed text nor a foreign fact gets relabelled.

    A missing state looks running to the live producer. Replay must require an
    observed state, and timestamps must establish the cutoff before production.
    Review excerpts are deliberately outside this interface.
    """
    origins = (ORIGIN_RECORDED, ORIGIN_SYNTHETIC) if synthetic_ok else (ORIGIN_RECORDED,)
    if case.get("origin") not in origins:
        return "replay-not-recorded"
    at = case.get("captured_at")
    if not _epoch(at):
        return "replay-bad-time"
    row = case.get("row_snapshot")
    if not isinstance(row, dict) or row.get("state") not in ("working", "needs_input", "idle"):
        return "replay-missing-state"
    identity = (case.get("harness"), case.get("sid"))
    if (
        case.get("harness") not in RUBRIC_HARNESSES
        or not all(isinstance(part, str) and part.strip() for part in identity)
        or (row.get("harness"), row.get("sid")) != identity
        or case.get("id") != mark_abstention._case_id(str(identity[0]), str(identity[1]))  # noqa: SLF001
    ):
        return "replay-wrong-session"
    if any(
        row.get(field) is not None and (not _epoch(row[field]) or row[field] > at)
        for field in ("ended_at", "finished_at")
    ):
        return "replay-bad-lifecycle-time"
    return _replay_facts_refusal(case, identity, at)


def intent_refusal(case: Mapping[str, Any]) -> str:
    """A format 5 case's intent and frozen checks, as closed reasons."""
    _config, reading, _records = _runtime()
    intent = case.get("intent")
    if not isinstance(intent, dict) or not isinstance(intent.get("goal"), str):
        return "replay-bad-intent"
    raw = intent.get("lines")
    if (
        not isinstance(raw, list)
        or not 1 <= len(raw) <= reading.MAX_OUTCOME_LINES
        or len(reading.outcome_lines(intent)) != len(raw)
    ):
        return "replay-bad-intent"
    frozen = case.get("tool_output")
    if frozen is None:
        return ""
    if case.get("harness") != "claude" or not isinstance(frozen, dict):
        return "replay-bad-tool-output"
    tails = frozen.get("tails", {})
    pairs = [frozen.get(key, []) for key in ("changed_after", "read_incomplete")]
    tails_ok = isinstance(tails, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in tails.items()
    )
    if not tails_ok or not all(
        isinstance(values, list)
        and all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p)
            for p in values
        )
        for values in pairs
    ):
        return "replay-bad-tool-output"
    return ""


def _replay_facts_refusal(case: Mapping[str, Any], identity: tuple[Any, Any], at: float) -> str:
    facts = case.get("producer_facts")
    if not isinstance(facts, list):
        return "replay-missing-facts"
    for fact in facts:
        if not isinstance(fact, dict) or not _epoch(fact.get("at")) or fact["at"] > at:
            return "replay-undated-or-future-fact"
        source = fact.get("source_session")
        if not isinstance(source, dict) or (source.get("harness"), source.get("sid")) != identity:
            return "replay-foreign-fact"
    return ""


def _inputs_digest(corpus: Corpus) -> str:
    return mark_abstention.cases_digest({"cases": corpus.cases, "rubric": corpus.rubric})


def _replay_marks_match(corpus: Corpus) -> bool:
    if corpus.marks.get("cases_digest") != mark_abstention.cases_digest(dict(corpus.cases)):
        print(
            "Replay marks are missing or belong to different cases. Mark this frozen packet first."
        )
        return False
    body = dict(corpus.cases)
    if body.get("v") == mark_abstention.FORMAT_INTENT:
        return _intent_marks_refusal(body, corpus.marks) == ""
    marks = mark_abstention._marks(dict(corpus.marks))  # noqa: SLF001
    for case in body.get("cases") or ():
        mark = marks.get(case["id"])
        if mark is None:
            continue
        names = mark_abstention.case_constraints(body, case)
        if any(mark.get(name) not in (MARK_JUDGE, MARK_ABSTAIN) for name in names):
            # A line with no mark can neither fail nor hold, so a packet with
            # one would score a question nobody answered.
            print(f"Case {case['id']}: marked without every constraint. Mark it again.")
            return False
    return True


def _intent_marks_refusal(body: Mapping[str, Any], marks_file: Mapping[str, Any]) -> str:
    """A format 5 key must be whole and closed before a single call (review, F5 and F7).

    Every case marked, on exactly its own constraints, with `judge` or
    `abstain` and nothing else. The authorization says every case is marked
    before any reading runs, and a key with room for text is a key that can
    carry it into the committed file.
    """
    raw = marks_file.get("marks")
    cases = {str(c["id"]): c for c in body.get("cases") or ()}
    why = ""
    if not isinstance(raw, dict):
        why = "the marks file holds no marks"
    elif set(raw) - set(cases):
        why = f"{len(set(raw) - set(cases))} marks name no case in this packet"
    elif set(cases) - set(raw):
        why = f"{len(set(cases) - set(raw))} cases are not marked; mark every case first"
    else:
        for case_id, mark in raw.items():
            names = set(mark_abstention.case_constraints(dict(body), dict(cases[case_id])))
            if not isinstance(mark, dict) or set(mark) != names:
                why = f"case {case_id} is marked on other constraints than its own"
            elif any(value not in (MARK_JUDGE, MARK_ABSTAIN) for value in mark.values()):
                why = f"case {case_id} carries a mark other than judge or abstain"
            if why:
                break
    if why:
        print(f"Refused: {why}.")
    return why


def _replay_preflight(corpus: Corpus) -> bool:
    """Check the whole packet before spending on even its first marked case."""
    intents = corpus.cases.get("v") == mark_abstention.FORMAT_INTENT
    if corpus.cases.get("v") not in (4, mark_abstention.FORMAT_INTENT):
        print("Frozen snapshots require case format v4 or v5; refusing a live fallback.")
        return False
    cases = corpus.cases.get("cases")
    if not isinstance(cases, list) or not cases:
        print("Replay needs a nonempty cases list.")
        return False
    seen: set[str] = set()
    valid = True
    for index, case in enumerate(cases, 1):
        case_id = case.get("id") if isinstance(case, dict) else None
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id) or case_id in seen:
            print(f"Case {index}: replay-bad-or-duplicate-id")
            valid = False
            continue
        seen.add(case_id)
        why = replay_refusal(case, synthetic_ok=intents) or (
            intent_refusal(case) if intents else ""
        )
        if why:
            print(f"Case {case_id}: {why}")
            valid = False
    if not intents and not all(
        isinstance(corpus.cases.get(key), str) and corpus.cases[key].strip() for key in CONSTRAINTS
    ):
        print("Replay needs the goal and output yardstick shown to the marker.")
        valid = False
    return valid


def _is_replay(corpus: Corpus) -> bool:
    return corpus.cases.get("v") in (4, mark_abstention.FORMAT_INTENT) or any(
        isinstance(case, dict) and {"row_snapshot", "producer_facts", "captured_at"} & case.keys()
        for case in corpus.cases.get("cases") or ()
    )


def rubric_skipped(rubric: Mapping[str, Any]) -> int:
    """Entries dropped before anything read them: the key is not a case id.

    Dropped rather than listed, because here the offending value IS the key,
    and the summary keys its rubric cases by it.
    """
    raw = rubric.get("cases")
    total = len(raw) if isinstance(raw, dict) else 0
    return total - len(_rubric_entries(rubric))


def _print_rubric_skipped(rubric: Mapping[str, Any]) -> None:
    skipped = rubric_skipped(rubric)
    if skipped:
        print(f"{skipped} rubric entries skipped: the key is not a case id.")


def _tool_output(
    case: Mapping[str, Any], destination: str | None, label: str, body: Mapping[str, Any]
) -> Any:
    """The frozen checks as the `ToolOutput` a press would carry, or None.

    None where no destination was asked for (a legacy run) or the harness
    publishes no checks. An empty destination is refused before this runs.
    """
    _config, reading, _records = _runtime()
    tails, changed, incomplete = mark_abstention.case_checks(dict(body), dict(case))
    if destination is None or tails is None:
        return None
    return reading.ToolOutput(
        destination=destination,
        label=label,
        tails=tails,
        changed_after=changed,
        read_incomplete=incomplete,
    )


def _run_digest(records: Mapping[str, Any], binding: Mapping[str, str] | None) -> str:
    """Authenticate the producer with its records in the ledger's opaque run digest.

    Summary fields are editable, so matching them cannot vouch for the bytes
    that produced carried records. The domain also refuses records-only legacy
    run digests rather than attaching a new copied-byte claim to old results.
    """
    return abstention_ledger.digest(
        {
            "domain": "compass-scoring-run-v1",
            "records": records,
            "binding": {key: (binding or {}).get(key) for key in BINDING_KEYS},
        }
    )


def _resume_matches(
    resume: Mapping[str, Any],
    corpus: Corpus,
    binding: Mapping[str, str] | None,
    ledger: abstention_ledger.Ledger | None,
) -> bool:
    """A resume continues the same run or none, and only on records the ledger vouches for.

    The local results file is hand-editable, so its records are carried over
    only when they hash to what the ledger recorded as that run's (review, F9):
    a hand-edited outcome would otherwise reach the committed summary.
    """
    raw = resume.get("summary")
    before: Mapping[str, Any] = raw if isinstance(raw, dict) else {}
    records = resume.get("records")
    try:
        last = ledger.last_run() if ledger is not None else None
    except abstention_ledger.LedgerError:
        last = None
    same = (
        isinstance(records, dict)
        and before.get("inputs_digest") == _inputs_digest(corpus)
        and before.get("marks_digest") == marks_digest(corpus)
        and all(before.get(k) == (binding or {}).get(k) for k in BINDING_KEYS)
        and last is not None
        and last["records_digest"] == _run_digest(records, binding)
        and (last["marks_digest"], last["inputs_digest"])
        == (marks_digest(corpus), _inputs_digest(corpus))
    )
    if not same:
        print(
            "The results to resume are not the last run the ledger recorded for these cases, "
            "marks and producer. Nothing ran."
        )
    return same


def _write_halves(
    records: Mapping[str, Mapping[str, Any]],
    summary: Mapping[str, Any],
    *,
    results_path: str,
    summary_path: str,
) -> None:
    mark_abstention._write(results_path, local_results(list(records.values()), summary, home=HOME))  # noqa: SLF001
    folder = os.path.dirname(summary_path) or "."
    os.makedirs(folder, exist_ok=True)
    descriptor, tmp = tempfile.mkstemp(prefix=".result-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, summary_path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    print()
    for line in render(summary):
        print(line)
    print(f"\nLocal results: {results_path} (stays on this machine).")
    print(f"Committable summary: {summary_path}.")


def _chain_holds(ledger: abstention_ledger.Ledger | None, summary_path: str) -> bool:
    """Whether the ledger still begins with every committed result's chain (V3).

    The committed Claude Code result at its fixed path is always read, and the
    one at `--out` too when that is elsewhere: reading only `--out` let a
    deleted ledger and a fresh `--out` reset the cap (V3b). A result without a
    chain is refused rather than skipped (V3d).
    """
    if ledger is None:
        return True
    try:
        grant = abstention_ledger.continuation()
    except abstention_ledger.LedgerError as error:
        print(f"Refused: {error}.")
        return False
    fixed = _continuation_summary(grant)
    if fixed is not None and os.path.abspath(summary_path) != os.path.abspath(fixed):
        print("Refused: a continuation writes only its fixed separate result file.")
        return False
    # Every committed result the chain runs through, then this run's own.
    count = 1 if grant is None else len(grant["segments"])
    earlier = [abstention_ledger.result_path(k) for k in range(count)]
    paths = dict.fromkeys((*earlier, fixed or summary_path, summary_path))
    for path in paths:
        committed = abstention_ledger.committed_chain(path)
        if committed is None:
            continue
        if not committed:
            print(f"Refused: the committed result at {path} records no ledger chain.")
            return False
        if not abstention_ledger.begins_with(ledger.path, committed):
            print(
                f"Refused: the spend ledger does not begin with the chain the result at {path} "
                "recorded. It was deleted, replaced or rewritten, so the key is not frozen."
            )
            return False
    return True


def _overwrites(
    ledger: abstention_ledger.Ledger | None, resume: Mapping[str, Any] | None, summary_path: str
) -> bool:
    """Whether a fresh run would replace a written result that spent, which it refuses to.

    A written result is the record of what its key spent. A fresh run over it
    would re-spend that key and replace the record, which the old cap of 19
    bounded to one call and the ceiling of 28 does not; `--resume` re-calls
    only the calls that failed. A result that charged nothing records no
    spend, so it may be replaced. One that cannot be read counts as spent.
    """
    if ledger is None or resume is not None:
        return False
    if os.path.islink(summary_path):
        print(f"Refused: the result at {summary_path} is a symlink.")
        return True
    held = abstention_ledger.committed_chain(summary_path)
    if held is None or (isinstance(held.get("calls"), int) and held["calls"] == 0):
        return False
    print(
        f"Refused: a result is already written at {summary_path}. A fresh run never "
        "replaces one: use --resume to re-call failed cases, or a new grant for a new packet."
    )
    return True


def _default_vouch(
    vouch: Callable[[Mapping[str, Any]], list[str]] | None,
    binding: Mapping[str, str] | None,
    reviewed_exports: mark_abstention.ReviewedExports | None = None,
) -> Callable[[Mapping[str, Any]], list[str]] | None:
    if vouch is None and (binding or {}).get("producer") == "claude":
        native: Callable[[Mapping[str, Any]], list[str]] = mark_abstention.machine_vouch(
            mark_abstention.STORE_HOME,
            **({"reviewed_exports": reviewed_exports} if reviewed_exports is not None else {}),
        )
        return native
    return vouch


def _vouched(
    case: Mapping[str, Any], vouch: Callable[[Mapping[str, Any]], list[str]] | None
) -> Mapping[str, Any]:
    """The case, demoted to synthetic when the machine's records do not vouch for it."""
    if vouch is None or case.get("origin") != ORIGIN_RECORDED:
        return case
    reasons = vouch(case)
    if not reasons:
        # Derived at score time, never the packet's own `lifecycle_from`, which
        # is hand-editable: the summary counts it (DEC-17, amended 2026-10-01).
        lifecycle = getattr(vouch, "lifecycle", None)
        return {**case, "stop_vouched_by": lifecycle(case) if lifecycle else None}
    print(
        f"Case {case.get('id')}: claims recorded and is not vouched for ({', '.join(reasons)}): "
        "withheld without a model call, and never counted toward coverage."
    )
    return {**case, "origin": ORIGIN_SYNTHETIC, "unconfirmed": list(reasons), "demoted": True}


def _binding_refusal(corpus: Corpus, binding: Mapping[str, str] | None) -> str:
    """A Claude Code result is written only from a format 5 packet, to Anthropic (F3, F7)."""
    if (binding or {}).get("producer") != "claude":
        return ""
    _runtime()
    from compass_runtime import reading_route  # noqa: PLC0415 - see `_runtime`

    if corpus.cases.get("v") != mark_abstention.FORMAT_INTENT:
        return "a Claude Code result is scored only from a format 5 packet"
    if (binding or {}).get("destination") != reading_route.VENDORS["claude"]:
        return "the reading call would not reach Anthropic, so nothing it said qualifies Claude"
    return ""


def parser_mismatch(corpus: Corpus) -> list[str]:
    """Why this checkout cannot score the packet's stamped cases, or nothing.

    The score-time re-check demotes a case whose `parser` stamp differs from
    this checkout's (`frozen-on-another-parser`). Measured before this refusal:
    the run still went ahead, withheld each such case unscored and charged
    every other case to the ledger, so the calls bought a result that could
    only read short.
    """
    if corpus.cases.get("v") != mark_abstention.FORMAT_INTENT:
        return []
    cases = [c for c in corpus.cases.get("cases") or () if isinstance(c, dict)]
    here = mark_abstention.parser_digest()
    other = [c for c in cases if "parser" in c and c["parser"] != here]
    if not other:
        return []
    return [
        (
            "Refused: this checkout's io.py, project_context.py or reading.py differs from the one "
            "these cases were frozen on."
        ),
        (
            f"  {len(other)} of {len(cases)} cases carry another parser digest, and every one "
            "of them would be demoted to synthetic and withheld, while the rest were still charged."
        ),
        (
            "  Fix: check out the commit the packet was frozen on and score from there, or "
            "re-freeze the packet from this checkout (a re-frozen packet needs marking again)."
        ),
    ]


def _may_score(
    corpus: Corpus,
    tool_destination: str | None,
    resume: Mapping[str, Any] | None,
    binding: Mapping[str, str] | None,
    ledger: abstention_ledger.Ledger | None,
) -> bool:
    """Every refusal a run makes before its first call, in one place.

    The parser check comes first, before the ledger is read or charged.
    """
    stale = parser_mismatch(corpus)
    if stale:
        for line in [*stale, "Nothing was charged and no model was called."]:
            print(line)
        return False
    refused = _binding_refusal(corpus, binding)
    if refused:
        print(f"Refused: {refused}.")
        return False
    if _is_replay(corpus) and not (_replay_preflight(corpus) and _replay_marks_match(corpus)):
        return False
    body = dict(corpus.cases)
    if (
        body.get("v") == mark_abstention.FORMAT_INTENT
        and tool_destination == ""
        and any(
            mark_abstention.case_checks(body, c)[0] is not None for c in body.get("cases") or ()
        )
    ):
        print("Compass cannot name where the producer would send these checks. Nothing ran.")
        return False
    if ledger is not None:
        why = ledger.check()
        # A full ledger still lets a resume carry its records over; any other
        # refusal stops the run before it starts.
        if why and not (resume is not None and why.startswith("the spend ledger already holds")):
            print(f"Refused: {why}.")
            return False
    return resume is None or _resume_matches(resume, corpus, binding, ledger)


def _scoring_ledger(
    ledger_path: str | None,
    corpus: Corpus,
    binding: Mapping[str, str] | None,
    max_calls: int,
) -> abstention_ledger.Ledger | None:
    grant = abstention_ledger.continuation() if ledger_path else None
    closure = abstention_ledger.closure_allowance(grant)
    campaign = None
    model_binding = ""
    if closure:
        from analyze_campaign import (  # noqa: PLC0415 - optional reviewed closure admission
            active_campaign,
        )

        try:
            campaign = active_campaign()
            if campaign is None:
                raise abstention_ledger.LedgerError("the bound campaign authority is absent")  # noqa: TRY301 - report admission refusal
            _runtime()
            from analyze_campaign import (  # noqa: PLC0415 - optional closure source binding
                runtime_source_digest,
            )
            from compass_runtime import (  # noqa: PLC0415 - runtime installed by prior admission
                observer,
            )

            evidence = campaign.manifest["evidence"]["qualification"]
            actual = {
                "source": runtime_source_digest(pathlib.Path(observer.__file__).parent),
                "scorer": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                "marks": marks_digest(corpus),
            }
            if evidence != actual:
                raise abstention_ledger.LedgerError(  # noqa: TRY301 - one reported closure admission refusal
                    "the qualification source, scorer or blind marks changed"
                )
        except abstention_ledger.LedgerError as error:
            print(f"Refused: {error}.")
            raise
        model_binding = abstention_ledger.digest({k: (binding or {}).get(k) for k in BINDING_KEYS})
    return (
        abstention_ledger.Ledger(
            ledger_path,
            cap=max_calls,
            marks_digest=marks_digest(corpus),
            inputs_digest=_inputs_digest(corpus),
            producer=str((binding or {}).get("producer") or ""),
            cases_digest=mark_abstention.cases_digest(dict(corpus.cases)),
            model_binding=model_binding,
            campaign=campaign,
        )
        if ledger_path
        else None
    )


def score(  # noqa: C901, PLR0913 - legacy route plus isolated closure admission
    port: int,
    corpus: Corpus,
    *,
    config: Any,
    model: Callable[..., tuple[str, str]],
    results_path: str,
    summary_path: str,
    now: float,
    binding: Mapping[str, str] | None = None,
    tool_destination: str | None = None,
    ledger_path: str | None = None,
    max_calls: int = MAX_CALLS,
    resume: Mapping[str, Any] | None = None,
    vouch: Callable[[Mapping[str, Any]], list[str]] | None = None,
    reviewed_exports: mark_abstention.ReviewedExports | None = None,
) -> int:
    """Run the producer once per case, write both halves, print the report.

    `vouch` re-checks each case the packet calls recorded against the
    machine's own records, as the freeze did, and returns why it cannot be,
    or nothing. The packet is hand-editable, so its word alone never meets the
    floor (V2). A Claude Code run with none uses the machine's.

    `tool_destination` is where the producer sends a Claude Code case's frozen
    checks, `reading_route.destination`'s answer; empty refuses the run, as a
    press withholds checks it cannot name a receiver for. `ledger_path` is the
    one spend ledger, charged under this packet's digests; `resume` is the
    local half of the last run, whose records are kept except where the model
    failed.
    """
    try:
        ledger = _scoring_ledger(ledger_path, corpus, binding, max_calls)
    except abstention_ledger.LedgerError:
        return 2
    closure = ledger is not None and ledger.campaign is not None
    replay = _is_replay(corpus)
    if (
        not _may_score(corpus, tool_destination, resume, binding, ledger)
        or not _chain_holds(ledger, summary_path)
        or _overwrites(ledger, resume, summary_path)
    ):
        return 2
    intents = corpus.cases.get("v") == mark_abstention.FORMAT_INTENT
    body = dict(corpus.cases)
    kept = dict((resume or {}).get("records") or {})
    vouch = _default_vouch(vouch, binding, reviewed_exports)
    cases = {
        str(c["id"]): _vouched(c, vouch) if intents else c
        for c in corpus.cases.get("cases") or ()
        if isinstance(c, dict) and c.get("id")
    }
    marks = mark_abstention._marks(dict(corpus.marks))  # noqa: SLF001 - the collector's own reader
    if closure and ledger:
        return _score_repeated(
            corpus,
            cases,
            ledger,
            config=config,
            model=model,
            results_path=results_path,
            summary_path=summary_path,
            now=now,
            binding=binding,
            tool_destination=tool_destination,
            resume=resume,
            reviewed_exports=reviewed_exports,
        )
    words = (str(corpus.cases.get("goal") or ""), str(corpus.cases.get("output") or ""))
    rows = {} if replay else _board_rows(port)
    if rows is None:
        return 2
    _config, reading, _records = _runtime()
    label = reading_label(str((binding or {}).get("producer") or ""))

    def charged(case_id: str) -> Callable[..., tuple[str, str]]:
        return _Charged(ledger, case_id, model) if ledger is not None else model

    records: dict[str, dict[str, Any]] = {}
    for case_id, mark in marks.items():
        case = cases.get(case_id)
        if case is None:
            continue
        prior = kept.get(case_id)
        if (
            isinstance(prior, dict)
            and prior.get("withheld") != reading.WITHHELD_MODEL_FAILED
            and not (intents and case.get("demoted"))
        ):
            records[case_id] = prior
            print(case_line(prior))
            continue
        row = case["row_snapshot"] if replay else rows.get((str(case["harness"]), str(case["sid"])))
        facts = (
            case["producer_facts"]
            if replay
            else _board_facts(port, case)
            if row is not None
            else []
        )
        records[case_id] = score_case(
            config,
            case,
            row,
            facts,
            mark,
            words=words,
            revision=mark_abstention.case_revision(dict(case)) if intents else None,
            # Only a demoted claim is withheld. A case the packet itself calls
            # synthetic is scored and can fail the run, and never covers (the
            # README's format 5 contract as of 1dc5f86b).
            withhold=WITHHELD_NOT_RECORDED if intents and case.get("demoted") else "",
            tool_output=_tool_output(case, tool_destination, label, body) if intents else None,
            model=charged(case_id),
            now=case["captured_at"] if replay else now,
            reviewed_exports=reviewed_exports,
        )
        print(case_line(records[case_id]))
    rubric_records = _score_rubric(
        corpus,
        records,
        config=config,
        words=words,
        charged=charged,
        now=now,
        origins={case_id: str(case.get("origin") or "") for case_id, case in cases.items()},
    )
    summary = summarize(
        list(records.values()),
        marks=marks,
        marks_bytes=corpus.marks_bytes,
        now=now,
        rubric_records=rubric_records,
        binding=binding,
        transcript_stops={
            case_id
            for case_id, case in cases.items()
            if case.get("stop_vouched_by") == "transcript"
        },
    )
    if replay:
        summary["inputs_digest"] = _inputs_digest(corpus)
    if ledger is not None:
        summary["spend"] = {"charged": ledger.used(), "cap": ledger.cap}
        summary["ledger_chain"] = abstention_ledger.chain_of(ledger.path)
        ledger.record_run(_run_digest(records, binding))
    _write_halves(records, summary, results_path=results_path, summary_path=summary_path)
    if any(r["withheld"] == WITHHELD_SPEND_CAP for r in records.values()):
        print(f"STOPPED at the spend ledger's cap of {ledger.cap if ledger else MAX_CALLS} calls.")
    return exit_code(summary)


def _repeat_classification(
    record: Mapping[str, Any], judged: Mapping[str, Any], charge_id: str | None
) -> str:
    if not charge_id:
        return "coverage-failed"
    if record["withheld"] or any(
        value == OUTCOME_UNPARSED for value in record["outcomes"].values()
    ):
        return "unusable"
    if _dec17([dict(record)])["failed"] or RUBRIC_FALSE_REASSURANCE in judged["judgement"].values():
        return "semantic-failed"
    if any(value.startswith("unscored:") for value in judged["judgement"].values()):
        return "coverage-failed"
    return "usable"


def _repetition_summaries(
    corpus: Corpus, attempts: list[dict[str, Any]], now: float, binding: Mapping[str, str] | None
) -> tuple[list[dict[str, Any]], str]:
    marks = mark_abstention._marks(dict(corpus.marks))  # noqa: SLF001 - native mark reader
    repetitions: list[dict[str, Any]] = []
    for repeat in (1, 2, 3):
        latest = {a["id"]: a for a in attempts if a["repeat"] == repeat}
        native = summarize(
            list(latest.values()),
            marks=marks,
            marks_bytes=corpus.marks_bytes,
            now=now,
            rubric_records=[a["rubric"] for a in latest.values()],
            binding=binding,
        )
        if (
            len(latest) != 10 or any(a["classification"] != "usable" for a in latest.values())
        ) and native["verdict"] != VERDICT_FAILED:
            native["verdict"] = VERDICT_BLOCKED
        repetitions.append({"repeat": repeat, "summary": native})
    verdicts = [r["summary"]["verdict"] for r in repetitions]
    verdict = (
        VERDICT_FAILED
        if VERDICT_FAILED in verdicts
        else VERDICT_PASSED
        if all(v == VERDICT_PASSED for v in verdicts)
        else VERDICT_BLOCKED
    )
    return repetitions, verdict


def _score_repeated(  # noqa: C901, PLR0912, PLR0913, PLR0915 - explicit charge/classify/checkpoint/stop state machine
    corpus: Corpus,
    cases: Mapping[str, Any],
    ledger: abstention_ledger.Ledger,
    *,
    config: Any,
    model: Callable[..., tuple[str, str]],
    results_path: str,
    summary_path: str,
    now: float,
    binding: Mapping[str, str] | None,
    tool_destination: str | None,
    resume: Mapping[str, Any] | None,
    reviewed_exports: mark_abstention.ReviewedExports | None = None,
) -> int:
    """Three registered native passes; preserve every attempt and campaign stop policy."""
    marks = mark_abstention._marks(dict(corpus.marks))  # noqa: SLF001
    rubric = _rubric_entries(corpus.rubric)
    campaign = ledger.campaign
    ordered = [f"{cid}:r{repeat}" for repeat in (1, 2, 3) for cid in marks]
    if (
        corpus.cases.get("v") != mark_abstention.FORMAT_INTENT
        or len(cases) != 10
        or set(cases) != set(marks)
        or set(rubric) != set(cases)
        or campaign is None
        or campaign.manifest["slots"]["qualification"] != ordered
    ):
        print("Refused: the ten-case, three-repeat packet is not the registered campaign.")
        return 2
    recorded_kinds = {
        rubric[cid].get("kind")
        for cid, case in cases.items()
        if case.get("origin") == ORIGIN_RECORDED
        and not case.get("demoted")
        and _evidence_bearing(case, replay=True, body=corpus.cases)
        and rubric_harness(rubric[cid], None) == "claude"
        and not rubric_refusal(rubric[cid], "claude")
    }
    roles = corpus.cases.get("closure_kinds")
    if (
        not isinstance(roles, dict)
        or set(roles) != set(cases)
        or sorted(roles.values()) != sorted((*KINDS, *PASSING_CHECK_ADVERSARIES))
        or campaign.manifest.get("qualification_kinds") != roles
        or any(
            roles[cid] in KINDS
            and (
                case.get("origin") != ORIGIN_RECORDED
                or case.get("demoted")
                or rubric[cid].get("kind") != roles[cid]
            )
            for cid, case in cases.items()
        )
    ):
        print("Refused: core kinds and five distinct passing-check adversaries are not frozen.")
        return 2
    if recorded_kinds != set(KINDS):
        print("Refused: recorded five-kind coverage is missing before any model call.")
        return 2
    try:
        for case in cases.values():
            _production_source(case)
    except mark_abstention.FreezeError:
        print("Refused: every closure case needs the complete typed-Claude production source seal.")
        return 2
    if resume is not None and (
        resume.get("v") != 2
        or not isinstance(resume.get("records"), dict)
        or not isinstance(resume["records"].get("attempts"), list)
    ):
        print("Refused: legacy successful records cannot skip registered repetitions.")
        return 2
    attempts: list[dict[str, Any]] = list((resume or {}).get("records", {}).get("attempts", []))
    stop_on_semantic_failure = campaign.stop_on_semantic_failure
    _config, reading, _records = _runtime()
    stopped = any(
        str(a.get("classification") or "").endswith("-failed")
        and (stop_on_semantic_failure or a.get("classification") != "semantic-failed")
        for a in attempts
    )
    label = reading_label(str((binding or {}).get("producer") or ""))
    for repeat in (1, 2, 3):
        for cid, mark in marks.items():
            if stopped:
                break
            prior = [a for a in attempts if a["id"] == cid and a["repeat"] == repeat]
            # A measured semantic failure is terminal evidence, never a retry slot.
            if prior and (
                prior[-1]["classification"] == "usable"
                or (
                    not stop_on_semantic_failure
                    and prior[-1]["classification"] == "semantic-failed"
                )
            ):
                continue
            if campaign.review_pending("qualification", f"{cid}:r{repeat}"):
                print("Paused before the next registered batch: measured review is required.")
                stopped = True
                break
            case = cases[cid]
            retry = bool(prior)
            while True:
                charged = _Charged(
                    ledger,
                    cid,
                    model,
                    repeat=repeat,
                    retry=retry,
                    binding=binding,
                    diagnostics_path=results_path + ".diagnostics",
                )
                record = score_case(
                    config,
                    case,
                    case["row_snapshot"],
                    case["producer_facts"],
                    mark,
                    model=charged,
                    now=case["captured_at"],
                    revision=mark_abstention.case_revision(dict(case)),
                    tool_output=_tool_output(case, tool_destination, label, corpus.cases),
                    read_agent_words=True,
                    reviewed_exports=reviewed_exports,
                )
                judged = rubric_case(rubric[cid], record, cid, case_origin=case.get("origin"))
                classification = _repeat_classification(record, judged, charged.charge_id)
                if not stop_on_semantic_failure and record["withheld"] in (
                    reading.WITHHELD_UNSTOPPED,
                    reading.WITHHELD_OVERSIZED,
                ):
                    classification = "protection-failed"
                record.update(
                    repeat=repeat,
                    retry=retry,
                    charge_id=charged.charge_id,
                    classification=classification,
                    rubric=judged,
                )
                if charged.diagnostic is not None:
                    record["transport_diagnostic"] = charged.diagnostic
                attempts.append(record)
                if not charged.charge_id:
                    campaign.stop("coverage-failed")
                if charged.charge_id:
                    try:
                        ledger.finish_exposure(charged.charge_id, classification)
                        if classification == "protection-failed":
                            campaign.stop("protection-failed")
                    except abstention_ledger.LedgerError:
                        stopped = True
                if classification.endswith("-failed") and (
                    stop_on_semantic_failure or classification != "semantic-failed"
                ):
                    stopped = True
                checkpoint = {
                    **{k: str((binding or {})[k]) for k in BINDING_KEYS if k in (binding or {})},
                    "v": 2,
                    "protocol": "closure-three-repeats",
                    "marks_digest": marks_digest(corpus),
                    "inputs_digest": _inputs_digest(corpus),
                    "ledger_chain": abstention_ledger.chain_of(ledger.path),
                    "verdict": VERDICT_BLOCKED,
                }
                records = {"attempts": attempts}
                ledger.record_run(_run_digest(records, binding))
                mark_abstention._write(  # noqa: SLF001 - native atomic writer
                    results_path,
                    {"v": 2, "summary": checkpoint, "attempts": attempts, "records": records},
                )
                # A single registered retry cannot hide the failed attempt. The campaign
                # lock refuses a second retry or a pending/orphan charge across processes.
                if (
                    classification == "unusable"
                    and charged.charge_id
                    and not retry
                    and f"{cid}:r{repeat}" != campaign.manifest["batches"]["qualification"][0][0]
                ):
                    retry = True
                    continue
                if classification not in ("usable", "semantic-failed") or (
                    stop_on_semantic_failure and classification == "semantic-failed"
                ):
                    stopped = True
                break
        if stopped:
            break
    repetitions, verdict = _repetition_summaries(corpus, attempts, now, binding)
    summary: dict[str, Any] = {
        **{k: str((binding or {})[k]) for k in BINDING_KEYS if k in (binding or {})},
        "v": 2,
        "protocol": "closure-three-repeats",
        "scored_at": now,
        "marks_digest": marks_digest(corpus),
        "inputs_digest": _inputs_digest(corpus),
        "ledger_chain": abstention_ledger.chain_of(ledger.path),
        "spend": {"charged": ledger.used(), "cap": ledger.cap},
        "counts": {
            "unique_cases": len({a["id"] for a in attempts}),
            "registered_exposures": len({(a["id"], a["repeat"]) for a in attempts}),
            "attempts": sum(bool(a["charge_id"]) for a in attempts),
            "unusable_attempts": sum(a["classification"] == "unusable" for a in attempts),
        },
        "repetitions": repetitions,
        "verdict": verdict,
        "stopped": stopped,
    }
    local: dict[str, Any] = {
        "v": 2,
        "summary": summary,
        "attempts": attempts,
        "records": {"attempts": attempts},
    }
    ledger.record_run(_run_digest(local["records"], binding))
    mark_abstention._write(results_path, local)  # noqa: SLF001 - same native atomic writer
    mark_abstention._write(summary_path, summary)  # noqa: SLF001 - same native atomic writer
    print(f"Repeated qualification: {summary['counts']['attempts']} attempts; {verdict}.")
    return 0 if verdict == VERDICT_PASSED else 1 if verdict == VERDICT_FAILED else 2


def _score_rubric(
    corpus: Corpus,
    records: Mapping[str, dict[str, Any]],
    *,
    config: Any,
    words: tuple[str, str],
    charged: Callable[[str], Callable[..., tuple[str, str]]],
    now: float,
    origins: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Each rubric entry against its record, scoring an admitted synthesised case here.

    `origins` is each case's origin after the score-time re-check, which wins
    over both the packet's word and the rubric's.
    """
    rubric_records: list[dict[str, Any]] = []
    _print_rubric_skipped(corpus.rubric)
    for case_id, entry in _rubric_entries(corpus.rubric).items():
        record = records.get(case_id)
        synthesised = entry.get("origin") == ORIGIN_SYNTHESISED
        admissible = not rubric_refusal(entry, rubric_harness(entry, None))
        if record is None and synthesised and admissible:
            row, facts = _synthesised(entry)
            record = score_case(
                config,
                {"id": case_id, "harness": row["harness"]},
                row,
                facts,
                {},
                words=words,
                model=charged(case_id),
                now=now,
            )
        origin = (origins or {}).get(case_id)
        rubric_records.append(rubric_case(entry, record, case_id, case_origin=origin))
    return rubric_records


def reading_label(producer: str) -> str:
    """The name a cutoff sentence gives the producer, as the route names it."""
    _runtime()
    from compass_runtime import reading_route  # noqa: PLC0415 - see `_runtime`

    return str(reading_route.LABELS.get(producer, ""))


def _evidence_bearing(
    case: Mapping[str, Any], *, replay: bool, body: Mapping[str, Any] | None = None
) -> bool:
    if not replay:
        return int(case.get("citable") or 0) > 0
    _config, reading, _records = _runtime()
    ledger = mark_abstention.case_ledger(dict(body or {}), dict(case))
    return any(reading._citable(entry) for entry in ledger)  # noqa: SLF001


def _coverage_line(
    corpus: Corpus,
    cases: Sequence[Mapping[str, Any]],
    harness: str,
    tagged: set[str],
    vouch: Callable[[Mapping[str, Any]], list[str]] | None,
) -> str:
    mine = [c for c in cases if c.get("harness") == harness]
    total = len(mine)
    if vouch is not None:
        mine = [c for c in mine if c.get("origin") == ORIGIN_RECORDED and not vouch(c)]
    evidence = sum(
        1 for c in mine if _evidence_bearing(c, replay=_is_replay(corpus), body=corpus.cases)
    )
    kinds = sum(1 for c in mine if str(c.get("id")) in tagged)
    if vouch is None:
        return f"  {harness}: {evidence} evidence-bearing, {kinds} kind-tagged, of {total}"
    return (
        f"  {harness}: {len(mine)} confirmed recorded, {kinds} kind-tagged, "
        f"{evidence} evidence-bearing, of {total}"
    )


def report(
    corpus: Corpus,
    summary: Mapping[str, Any] | None,
    *,
    vouch: Callable[[Mapping[str, Any]], list[str]] | None = None,
) -> int:
    """Where the corpus stands, and what the last run said. Spends nothing.

    With `vouch`, the machine's check the scorer will run, a case counts only
    when it is confirmed recorded: the packet's word alone read as a met
    floor before a run that could only be short (N3).
    """
    cases = [c for c in corpus.cases.get("cases") or () if isinstance(c, dict)]
    marks = mark_abstention._marks(dict(corpus.marks))  # noqa: SLF001
    live = {str(c.get("id")) for c in cases}
    print(f"{sum(1 for k in marks if k in live)} of {len(cases)} cases marked.")
    # Said at the preflight, so the refusal `--score` would make is no surprise.
    for line in parser_mismatch(corpus):
        print(line.replace("Refused:", "--score will refuse:", 1))
    if _is_replay(corpus):
        if not _replay_preflight(corpus):
            return 2
        _config, reading, _records = _runtime()
        print("Historical replay: frozen row, facts and clock; no live board reads.")
        for case in cases:
            print(f"  {case['id']}: {reading.end_kind(case['row_snapshot'])}")
    _print_rubric_skipped(corpus.rubric)
    tagged = {
        cid
        for cid, e in _rubric_entries(corpus.rubric).items()
        if e.get("kind") in KINDS and str(e.get("origin") or ORIGIN_RECORDED) == ORIGIN_RECORDED
    }
    for harness in COVERAGE_HARNESSES:
        print(_coverage_line(corpus, cases, harness, tagged, vouch))
    if summary is None:
        print("No scoring run has been recorded, so nothing here says what the producer did.")
        return 0
    print()
    checked = check_marks(summary, corpus.marks_bytes)
    if (_is_replay(corpus) or "inputs_digest" in summary) and summary.get(
        "inputs_digest"
    ) != _inputs_digest(corpus):
        checked["verdict"] = VERDICT_STALE
    drift = _ledger_drift(summary)
    if drift:
        print(drift)
        checked["verdict"] = VERDICT_STALE
    for line in render(checked):
        print(line)
    return 0


def _ledger_drift(summary: Mapping[str, Any]) -> str:
    """Why the spend ledger contradicts a Claude Code result, or empty.

    Every call the qualification made is in the one ledger, under the digests
    it was charged under. A call under other marks or other cases means the
    key or the packet moved after something was spent, and this result is not
    the whole story.
    """
    if summary.get("producer") != "claude":
        return ""
    try:
        calls = abstention_ledger.read(abstention_ledger.LEDGER_PATH)["calls"]
        grant = abstention_ledger.continuation()
    except abstention_ledger.LedgerError as error:
        return f"The spend ledger cannot vouch for this result: {error}."
    held = summary.get("ledger_chain")
    if isinstance(held, dict) and not abstention_ledger.begins_with(
        abstention_ledger.LEDGER_PATH, held
    ):
        return (
            "The spend ledger does not begin with the chain this result recorded: it was "
            "deleted or replaced after the result was written."
        )
    bound = (summary.get("marks_digest"), summary.get("inputs_digest"))
    if grant is not None:
        return _continuation_drift(bound, calls, grant)
    other = [c for c in calls if (c["marks_digest"], c["inputs_digest"]) != bound]
    if other:
        return (
            f"The spend ledger holds {len(other)} calls charged under other marks or other "
            "cases than this result was scored against."
        )
    return ""


def _continuation_drift(
    bound: tuple[Any, Any], calls: list[dict[str, Any]], grant: Mapping[str, Any]
) -> str:
    previous = grant["previous"]
    prior = previous["ledger_chain"]
    if not abstention_ledger.begins_with(abstention_ledger.LEDGER_PATH, prior):
        return "The spend ledger lost the failed result's chain."
    earlier = [tuple(pair) for _end, pair in grant["segments"]]
    if grant["phase"] != "sealed":
        if bound in earlier and len(calls) == prior["calls"]:
            return ""
        return "The continuation grant is not sealed."
    next_packet = grant["next"]
    new_pair = (next_packet["marks_digest"], next_packet["inputs_digest"])
    if bound in (*earlier, new_pair) and abstention_ledger.follows(calls, grant, new_pair):
        return ""
    return "The spend ledger does not follow the granted old and new packet keys."


def _continuation_summary(grant: Mapping[str, Any] | None) -> str | None:
    """The fixed result file the active grant writes, or None with no grant."""
    if grant is None:
        return None
    return abstention_ledger.result_path(len(grant["segments"]))


def _load_corpus(rubric_path: str) -> Corpus:
    marks_bytes = b""
    if os.path.exists(MARKS_PATH):
        with open(MARKS_PATH, "rb") as handle:
            marks_bytes = handle.read()
    return Corpus(
        cases=mark_abstention._load(CASES_PATH),  # noqa: SLF001
        marks=mark_abstention._load(MARKS_PATH),  # noqa: SLF001
        marks_bytes=marks_bytes,
        rubric=mark_abstention._load(rubric_path) if os.path.exists(rubric_path) else {},  # noqa: SLF001
    )


def results_path_for(producer: str) -> str:
    """The local half, one per producer, so a resume never picks up the other's run."""
    if producer == "claude":
        return local_results_path(abstention_ledger.generation())
    return RESULTS_PATH


def local_results_path(generation: int) -> str:
    """Packet `generation`'s local half, beside the committed one `result_path` names."""
    if generation == 0:
        return os.path.join(HOME, "abstention-claude-results.json")
    if generation == 1:
        return os.path.join(HOME, "abstention-claude-continuation-results.json")
    return os.path.join(HOME, f"abstention-claude-continuation-{generation}-results.json")


def summary_path_for(producer: str | None, out: str | None) -> str:
    """The failed result remains a fixed, read-only predecessor of a continuation."""
    if out is not None:
        return out
    if producer != "claude":
        return SUMMARY_PATH
    generation = abstention_ledger.generation()
    return abstention_ledger.result_path(generation) if generation else CLAUDE_SUMMARY_PATH


def _argument_refusal(args: argparse.Namespace) -> str:  # noqa: C901, PLR0911 - cold admission precedes data reads; one refusal per guard
    if (
        abstention_ledger.LEDGER_PATH is None
        or mark_abstention.CLAUDE_PROJECTS_ROOT is None
        or mark_abstention.STORE_HOME is None
        or not CLAUDE_VERSIONS_ROOTS
        or abstention_ledger.canonical_home() is None
    ):
        return "Refused: this account's canonical home is unavailable. Nothing ran."
    if (args.score or args.probe_argv) and abstention_ledger.home_moved():
        # V1: every path this check trusts is the account's, so a HOME that
        # names another directory is a second machine's worth of ledger.
        return "Refused: HOME names another directory than this account's home. Unset it."
    if args.score and args.probe_argv:
        return "--probe-argv never scores; run it on its own."
    if args.score and not args.producer:
        return "--score needs --producer claude: a result names what ran."
    if args.score and args.producer == "codex":
        # No Codex spend is authorized for this qualification (2026-09-24).
        return "--producer codex may report but not score: no Codex spend is authorized."
    ceiling = MAX_CALLS
    if args.max_calls > MAX_CALLS:
        try:
            grant = abstention_ledger.continuation()
        except abstention_ledger.LedgerError:
            grant = None
        if grant:
            ceiling = abstention_ledger.allowance_cap(grant)
    if not 1 <= args.max_calls <= ceiling:
        return f"--max-calls must be between 1 and {ceiling}, the authorized spend."
    if args.resume and not args.score:
        return "--resume continues a scoring run; pass --score with it."
    return ""


# Every variable that can move a Claude Code call off the stub, or sign it in as
# the operator: the endpoint and provider switches `reading_route` reads, the
# credentials and the config directory, and the proxies, lower and upper case,
# plus the three CLI-specific proxy names the 2.1.283 binary reads (review, Sent
# F5). Stripped, never trusted.
_PROBE_DROPPED_PREFIXES = (
    "ANTHROPIC_",
    "CLAUDE_CODE_USE_",
    "CLAUDE_CODE_CUSTOM_OAUTH",
    "CLAUDE_CODE_OAUTH",
)
_PROBE_DROPPED = frozenset(
    {
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "claude_code_http_proxy",
        "claude_code_https_proxy",
        "claude_code_proxy_url",
        "claude_config_dir",
    }
)
PROBE_PROMPT = "Reply with the word ok."
# The block 2.1.283 adds under OAuth sign-in, accepted and disclosed (owner
# ruling, 2026-09-27). Only this sentence and `metadata.user_id` may carry the
# account; anywhere else is a leak the probe reports.
_DISCLOSED_EMAIL = re.compile(r"The user's email address is [^\n\\]*")
_DISCLOSED_UUID = re.compile(r'(\\?"account_uuid\\?"\s*:\s*\\?")[0-9a-fA-F-]{36}')


def _probe_events(message: Mapping[str, Any], nonce: str) -> bytes:
    """The Messages stream a real endpoint sends, answering `nonce` and nothing else."""
    events = [
        ("message_start", {"type": "message_start",
                           "message": {**message, "content": [], "stop_reason": None}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": nonce}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 1}}),
        ("message_stop", {"type": "message_stop"}),
    ]  # fmt: skip
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events).encode()


class _ProbeHandler(http.server.BaseHTTPRequestHandler):
    """Answers the CLI for `_ProbeStub`, which it reaches as `self.server.probe`."""

    def _answer(self, status: int, kind: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._answer(200, "application/json", b"{}")

    def do_HEAD(self) -> None:
        self._answer(200, "application/json", b"")

    def do_POST(self) -> None:
        stub: _ProbeStub = self.server.probe  # type: ignore[attr-defined]
        text = self.rfile.read(int(self.headers.get("content-length") or 0)).decode(
            "utf-8", "replace"
        )
        if not self.path.split("?")[0].endswith("/v1/messages"):
            self._answer(200, "application/json", json.dumps({"input_tokens": 1}).encode())
            return
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = {}
        body: Mapping[str, Any] = parsed if isinstance(parsed, dict) else {}
        stub.saw(text, str(self.headers))
        usage = {"input_tokens": 1, "output_tokens": 1}
        message = {"id": "msg_probe", "type": "message", "role": "assistant",
                   "model": str(body.get("model") or ""), "stop_sequence": None,
                   "usage": usage}  # fmt: skip
        if body.get("stream"):
            self._answer(200, "text/event-stream", _probe_events(message, stub.nonce))
            return
        whole = {**message, "content": [{"type": "text", "text": stub.nonce}],
                 "stop_reason": "end_turn"}  # fmt: skip
        self._answer(200, "application/json", json.dumps(whole).encode())

    def log_message(self, *_args: Any) -> None:
        pass


class _ProbeStub:
    """A Messages endpoint on this machine that answers every call with a nonce.

    The nonce is in no request the CLI sends, so a reply carrying it came from
    here: a real model reached through anything else cannot produce it. Only
    derived yes-or-no facts about each request are kept, never its text.
    `needles` are looked for anywhere in the headers and body; `account`
    needles are looked for inside the disclosed OAuth block and outside it.
    """

    def __init__(
        self, nonce: str, *, needles: Mapping[str, str], account: Mapping[str, str] | None = None
    ) -> None:
        self.nonce = nonce
        self.needles = dict(needles)
        self.account = dict(account or {})
        self.requests = 0
        self.found: dict[str, bool] = dict.fromkeys(needles, False)
        self.disclosed = False
        self.elsewhere = False
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
        self.server.probe = self  # type: ignore[attr-defined]
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def saw(self, text: str, headers: str = "") -> None:
        self.requests += 1
        whole = f"{headers}\n{text}"
        # Casefolded (review N1): the CLI names the canonical spelling of a
        # path, which need not be the case the needle was taken in.
        folded = whole.casefold()
        for name, needle in self.needles.items():
            self.found[name] = self.found[name] or needle.casefold() in folded
        email = self.account.get("email", "")
        if email:
            self.disclosed = self.disclosed or email in "".join(_DISCLOSED_EMAIL.findall(text))
            rest = _DISCLOSED_UUID.sub(r"\1", _DISCLOSED_EMAIL.sub("", whole))
            self.elsewhere = self.elsewhere or any(
                value and value in rest for value in self.account.values()
            )

    def __enter__(self) -> Self:
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def probe_environment(
    environ: Mapping[str, str], host: str, *, config_dir: str = "", oauth: bool = False
) -> dict[str, str]:
    """The operator's environment with every route off this machine removed, pointed at `host`.

    Signed in with a placeholder no real endpoint accepts: an API key, or with
    `oauth` a placeholder OAuth token and `config_dir`, a directory holding the
    probe's own placeholder account, so the operator's account is never read.
    Background traffic is turned off, as for every reading.
    """
    import secrets  # noqa: PLC0415

    env = {
        key: value
        for key, value in environ.items()
        if not key.startswith(_PROBE_DROPPED_PREFIXES) and key.lower() not in _PROBE_DROPPED
    }
    env["ANTHROPIC_BASE_URL"] = f"http://{host}"
    if oauth:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = f"compass-probe-placeholder-{secrets.token_hex(8)}"
    else:
        env["ANTHROPIC_API_KEY"] = f"compass-probe-placeholder-{secrets.token_hex(8)}"
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    env["NO_PROXY"] = "127.0.0.1"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def _placeholder_account(folder: str) -> dict[str, str]:
    """A signed-in account that is nobody's, written where the CLI reads its global config."""
    import secrets  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    account = {
        "email": f"probe-{secrets.token_hex(6)}@example.invalid",
        "uuid": str(uuid.uuid4()),
    }
    body = {
        "hasCompletedOnboarding": True,
        "oauthAccount": {
            "emailAddress": account["email"],
            "accountUuid": account["uuid"],
            "organizationUuid": str(uuid.uuid4()),
        },
    }
    path = os.path.join(folder, ".claude.json")
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        json.dump(body, handle)
    return account


def _probe_once(
    config: Any,
    binary: str,
    *,
    mode: str,
    runner: Callable[..., Any] | None,
    environ: Mapping[str, str],
    pinned: Callable[[str], str | None] | None,
) -> int:
    """One sign-in mode's call. 2 refused, 1 something leaked, 0 clean."""
    import secrets  # noqa: PLC0415

    _runtime()
    from compass_runtime import observer, reading_route, supervise  # noqa: PLC0415

    nonce = secrets.token_hex(16)
    needles = {
        "instruction": observer.CLAUDE_READING_SYSTEM_PROMPT,
        "home": abstention_ledger.real_home(),
        "user": os.path.basename(abstention_ledger.real_home().rstrip(os.sep)) or "\0",
        "state": str(config.state_dir),
    }
    oauth = mode == "OAuth"
    argv: list[list[str]] = []
    root = observer.reading_workdir_root() or tempfile.gettempdir()
    with tempfile.TemporaryDirectory(prefix="compass-probe-config-", dir=root) as folder:
        account = _placeholder_account(folder) if oauth else {}
        with _ProbeStub(nonce, needles=needles, account=account) as stub:
            env = probe_environment(environ, stub.host, config_dir=folder, oauth=oauth)
            where = reading_route.destination("claude", environ=env)
            if where != stub.host:
                print(
                    f"Refused: the CLI would reach {where or 'an unnamed host'}, "
                    "not the probe's stub."
                )
                return 2
            spawn = runner if runner is not None else supervise.run

            def run(command: Sequence[str], **kwargs: Any) -> Any:
                argv.append([str(part) for part in command])
                return spawn(command, **{**kwargs, "env": observer.claude_environment(env)})

            raw, status = observer.claude_exec(
                config,
                PROBE_PROMPT,
                output_cap_bytes=256,
                runner=run,
                binary_resolver=pinned or (lambda _name: binary),
            )
    if status != "ok" or nonce not in raw or not stub.requests:
        print(
            f"Refused ({mode} sign-in): the CLI's answer ({status}) did not come from the probe's "
            "own stub, so this says nothing about what it sends. Nothing was written."
        )
        return 2
    command = argv[0] if argv else []
    flagged = "--system-prompt" in command and (
        command[command.index("--system-prompt") + 1] == observer.CLAUDE_READING_SYSTEM_PROMPT
    )
    facts = {
        "argv carries --system-prompt": flagged,
        "request carries the fixed instruction": stub.found["instruction"],
        "request names the home directory": stub.found["home"],
        "request names the account's user name": stub.found["user"],
        "request names the state directory": stub.found["state"],
    }
    if oauth:
        facts["request carries the account's email in the disclosed block"] = stub.disclosed
        facts["request names the account's email or UUID anywhere else"] = stub.elsewhere
    # What the stub saw, not what the CLI did elsewhere: only an OS sandbox
    # can say no other host was reached (review, Sent F3).
    print(f"Probe ({mode} sign-in): {stub.requests} request(s) reached the probe's own stub.")
    for name, value in facts.items():
        print(f"  {name}: {'yes' if value else 'no'}")
    leaked = any(stub.found[name] for name in ("home", "user", "state")) or stub.elsewhere
    return 0 if flagged and stub.found["instruction"] and not leaked else 1


def probe_argv(
    config: Any,
    binary: str,
    *,
    runner: Callable[..., Any] | None = None,
    environ: Mapping[str, str] | None = None,
    pinned: Callable[[str], str | None] | None = None,
) -> int:
    """A call to a stub this starts itself, per sign-in mode. Writes and charges nothing.

    Refused rather than charged (DRC-4710, V5): no operator setting chooses
    the endpoint or the account. Each pass starts its own stub, strips every
    variable that could move the call or sign it in as the operator
    (`probe_environment`), confirms `reading_route` names that stub, and
    counts the call good only when the reply carries the stub's nonce. The
    OAuth pass signs in as a placeholder account the probe writes, because
    the CLI adds the account's email and UUID there (owner ruling of
    2026-09-27: accepted and disclosed), and reports whether either appears
    anywhere beyond the disclosed block.
    """
    source = os.environ if environ is None else environ
    worst = 0
    for mode in ("api-key", "OAuth"):
        code = _probe_once(config, binary, mode=mode, runner=runner, environ=source, pinned=pinned)
        if code == 2:
            return 2
        worst = max(worst, code)
    print("Nothing was written and nothing was charged.")
    return worst


def _claude_model_arg(value: str) -> str:
    _runtime()
    from compass_runtime import cli  # noqa: PLC0415 - import after installing the runtime path

    return cli.claude_reading_model_arg(value)


def main(argv: list[str] | None = None) -> int:  # noqa: C901, PLR0911, PLR0915 - explicit CLI gates
    parser = argparse.ArgumentParser(description="Score the reading producer against the marks.")
    parser.add_argument("--score", action="store_true", help="run the producer; spends")
    parser.add_argument("--report", action="store_true", help="where things stand; spends nothing")
    parser.add_argument("--producer", choices=PRODUCERS, help="required with --score")
    parser.add_argument("--claude-reading-model", type=_claude_model_arg, default=None)
    parser.add_argument(
        "--max-calls", type=int, default=MAX_CALLS, help=f"spend ledger cap, at most {MAX_CALLS}"
    )
    parser.add_argument("--resume", action="store_true", help="re-call only model failures")
    parser.add_argument(
        "--probe-argv", action="store_true", help="one call to a local stub; writes nothing"
    )
    parser.add_argument("--port", type=int, default=4553, help="the dashboard port to read")
    parser.add_argument("--rubric", default=RUBRIC_PATH, help="the DEC-15 expectation file")
    parser.add_argument("--out", default=None, help="where the committable summary goes")
    parser.add_argument(
        "--reviewed-exports", metavar="MANIFEST", help="explicit finite reviewed export manifest"
    )
    parser.add_argument(
        "--reviewed-exports-sha256", metavar="SHA256", help="independently pinned manifest digest"
    )
    args = parser.parse_args(argv)
    try:
        reviewed_exports = mark_abstention.load_reviewed_exports(
            args.reviewed_exports, args.reviewed_exports_sha256
        )
    except mark_abstention.FreezeError as error:
        print(f"Refused: {error}.")
        return 2
    refusal = _argument_refusal(args)
    if refusal:
        print(refusal)
        return 2
    config_mod, reading, _records = _runtime()
    from compass_runtime import reading_route  # noqa: PLC0415 - see `_runtime`

    config = config_mod.build_runtime_config(
        environ=os.environ,
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=pathlib.Path(_SKILL, "server.py"),
        observer_model_enabled=True,
        claude_reading_model=args.claude_reading_model or config_mod.CLAUDE_READING_DEFAULT_MODEL,
    )
    if args.probe_argv:
        try:
            probed = verify_claude_binary()
        except BinaryError as error:
            print(f"Refused: {error}.")
            return 2
        with probed:
            return probe_argv(
                config, probed.path, pinned=PinnedClaude(probed.path, probed.identity)
            )
    out = summary_path_for(args.producer, args.out)
    corpus = _load_corpus(args.rubric)
    mark_abstention.print_packet(CASES_PATH, dict(corpus.cases))
    if not corpus.cases.get("cases"):
        print(f"No cases at {CASES_PATH}. Run mark_abstention.py --build or --freeze first.")
        return 1
    if not args.score:
        summary = mark_abstention._load(out) if os.path.exists(out) else None  # noqa: SLF001
        vouch = (
            mark_abstention.machine_vouch(
                mark_abstention.STORE_HOME,
                **({"reviewed_exports": reviewed_exports} if reviewed_exports is not None else {}),
            )
            if corpus.cases.get("v") == mark_abstention.FORMAT_INTENT
            else None
        )
        return report(corpus, summary or None, vouch=vouch)
    destination = reading_route.destination("claude")
    if destination != reading_route.VENDORS["claude"]:
        where = destination or "an unnamed host"
        print(f"Refused: the reading call would reach {where}, not Anthropic.")
        return 2
    try:
        verified = verify_claude_binary()
    except BinaryError as error:
        print(f"Refused: {error}.")
        return 2
    with verified:
        binding = {
            "producer": "claude",
            "model": config.claude_reading_model,
            "argv_digest": argv_digest("claude", config),
            "destination": destination,
            "binary": verified.shown,
            "binary_sha256": verified.identity[-1],
            "cli_version": verified.version,
            "signature": verified.signature,
        }
        results_path = results_path_for("claude")
        resume = None
        if args.resume:
            resume = mark_abstention._load(results_path)  # noqa: SLF001
            if not resume:
                print(f"No earlier run at {results_path} to resume.")
                return 2
        return score(
            args.port,
            corpus,
            config=config,
            # The private copy, re-checked before each call; never the install path.
            model=reading.ClaudeReadingModel(
                config, binary_resolver=PinnedClaude(verified.path, verified.identity)
            ),
            results_path=results_path,
            summary_path=out,
            now=time.time(),
            binding=binding,
            tool_destination=destination,
            ledger_path=abstention_ledger.LEDGER_PATH,
            max_calls=args.max_calls,
            resume=resume,
            vouch=mark_abstention.machine_vouch(
                mark_abstention.STORE_HOME,
                **({"reviewed_exports": reviewed_exports} if reviewed_exports is not None else {}),
            ),
            reviewed_exports=reviewed_exports,
        )


if __name__ == "__main__":
    raise SystemExit(main())
