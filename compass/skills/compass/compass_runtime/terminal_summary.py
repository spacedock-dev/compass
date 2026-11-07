"""Stored cited phases in a terminal; display rules follow the session page.

The adapter never refreshes or reruns a stored summary on a plain read.
See docs/design-session-summary.md#terminal-summary.
"""

from __future__ import annotations

import contextlib
import re
import signal
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from compass_runtime import terminal_drift
from compass_runtime.terminal_sessions import names, printable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from types import FrameType
    from typing import TextIO

    from compass_runtime.terminal_client import Session


class Board(Protocol):
    port: int

    def summary(self, harness: str, sid: str) -> Any: ...
    def post(self, path: str, body: Mapping[str, Any]) -> tuple[int, Any]: ...


SPEECH = (
    "(?:asked|said|reported|confirmed|requested|wanted|told|noted"
    "|explained|mentioned|suggested|proposed|stated|replied|answe"
    "red|claimed|wrote)"
)
ADVERB = r"(?:(?:also|then|later|again|first|finally|now)\s+)?"
AGENT = re.compile(
    (
        "^(?:(?:the\\s+agent['\\u2019]s\\s+reply|the\\s+agent|agent|the\\s"
        "+assistant|assistant|claude)\\s+"
    )
    + ADVERB
    + SPEECH
    + r"\b|the\s+(?:agent|assistant)\b(?!['\u2019]s\b))",
    re.IGNORECASE,
)
PERSON = re.compile(r"^the\s+(?:person|user)\b(?!['\u2019]s\b)\s*", re.IGNORECASE)
PERSON_NAMED = re.compile(
    r"^(?:you|the\s+(?:person|user))\s+" + ADVERB + SPEECH + r"\b", re.IGNORECASE
)
THIRD = re.compile(r"^the\s+(?:person|user)\s+(" + ADVERB + SPEECH + r")\b\s*", re.IGNORECASE)
BARE = re.compile(r"^(asked|said)\b\s*", re.IGNORECASE)
YOU_VERB = {"has": "have", "is": "are", "was": "were", "does": "do", "goes": "go"}


def _you(rest: str) -> str:
    found = re.match(r"(\S+)([\s\S]*)", rest)
    if not found:
        return "You"
    verb, after = found.groups()
    agreed = YOU_VERB.get(
        verb.lower(),
        verb[:-1] if re.search(r"[^s]s$", verb.lower()) and not verb.endswith("'s") else verb,
    )
    return f"You {agreed}{after}".rstrip()


def asked(words: str) -> str:
    flat = words.strip()
    if re.match(r"^you\b", flat, re.IGNORECASE) or AGENT.search(flat):
        return words
    found = THIRD.search(flat) or BARE.search(flat)
    if found:
        rest = flat[found.end() :]
        verb = " ".join(found[1].lower().split())
        return (
            f"You {verb}: {rest[1:].lstrip()}" if rest.startswith(":") else f"You {verb} {rest}"
        ).rstrip()
    found = PERSON.search(flat)
    return _you(flat[found.end() :]) if found else f"You said: {words}"


def bullet_words(kind: str, words: str) -> str:
    flat = words.strip()
    person = PERSON_NAMED.search(flat) or PERSON.search(flat)
    if kind == "said":
        if person:
            you = asked(flat)
            return "The agent said " + you[0].lower() + you[1:]
        if AGENT.search(flat):
            return words
        rest = re.sub(r"^said\b(?:\s+that\b)?[\s:,]*", "", flat, flags=re.IGNORECASE)
        return f"The agent said: {rest}" if rest else words
    if kind == "asked" or (kind == "did" and person):
        return asked(words)
    if kind == "failed":
        mark = (
            "Failed:"
            if re.search(
                r"\breported\s+failed,\s*as\s+the\s+tool\s+reported\b", words, re.IGNORECASE
            )
            else "Failed as the tool reported:"
        )
        return f"{mark} {words}"
    return words


def lede_words(words: str) -> str:
    def replace(found: re.Match[str]) -> str:
        rest = found[2]
        first = re.match(r"[^\s,;:]+", rest.strip())
        verb = (
            "(?:\\w+ed|\\w+[^s'\\u2019]s|has|is|was|were|does|goes|will|woul"
            "d|can|could|should|must|may|might|did|had|chose|said|wrote|r"
            "an|took|made|saw|told|gave|got|found|felt|kept|left|began|we"
            "nt|knew|asked|wanted)"
        )
        return (
            found[1] + _you(rest)
            if first and re.fullmatch(verb, first[0], re.IGNORECASE)
            else found[0]
        )

    return re.sub(
        r"(^|[.!?]\s+)The\s+(?:person|user)\s+([^.!?]*)", replace, words, flags=re.IGNORECASE
    )


WITHHELD = {
    "completion_claim": (
        "Left out: this line said work was done or working, and the record does not back that."
    ),
    "no_citation": "Left out: this line cited no entry.",
    "shape_fault": "Left out: this line could not be shown in a form Compass accepts.",
    "too_long_cut": "Left out: this line was too long to show whole.",
}
GAPS = {
    "before_window": "This part was not summarized: the summary starts later in the session.",
    "no_valid_reply": (
        "This part could not be summarized: the model\u2019s reply could not be read."
    ),
    "no_output": "This part could not be summarized: the model returned nothing, twice.",
    "refused": "This part could not be summarized: the model call was refused.",
    "stopped": "This part was not summarized: the summary stopped before it.",
    "ceiling": "This part was not summarized: the summary reached one of its limits first.",
    "bytes": "This part was left out: the summary reached the largest size it may be saved at.",
}
UNKNOWN = (
    "Compass could not read the whole record now, so it cannot tell "
    "whether this summary is "
    "current."
)
RELEVANCE = (
    "Each line cites the entries it rests on. Compass checks that a "
    "cited entry exists and what kind it is, not that it supports the "
    "line."
)


def _shown(value: Any, *, title: bool = False) -> str:
    if isinstance(value, str):
        return value
    reason = value.get("reason", "") if isinstance(value, dict) else ""
    if title:
        return {
            "completion_claim": (
                "Phase title left out: it used a word that can say work is done, "
                "such as \u201cfix\u201d or \u201cdone\u201d, which a title may "
                "not."
            ),
            "shape_fault": "Phase title left out: it could not be shown in a form Compass accepts.",
            "too_long_cut": "Phase title left out: it was too long to show whole.",
        }.get(reason, "Phase title left out: Compass held it back.")
    return WITHHELD.get(reason, "Left out: Compass held this line back.")


def _freshness(summary: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    report = summary.get("out_of_date") or {}
    if report.get("kind") in (None, "unknown", "unavailable"):
        lines.append(UNKNOWN)
    elif report.get("action") == "update":
        count = report.get("new_entries", 0)
        lines.append(
            f"{count} new {'entry' if count == 1 else 'entries'}."
            if count
            else (
                "Some message text remains unsummarized. "
                "Update summary continues from where it stopped."
            )
        )
    elif report.get("action") == "summarize_again":
        lines.append(
            f"This summary needs a fresh read ({report.get('reason') or report.get('kind')}); "
            "use --summary --again."
        )
    elif report.get("kind") == "unchanged":
        lines.append("The record has not changed since this summary was written.")
    else:
        lines.append(UNKNOWN)
    return lines


def _notes(summary: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    report = summary.get("out_of_date") or {}
    blocks = summary.get("blocks") or []
    coverage = summary.get("coverage") or {}
    gaps = any(block.get("gap") for block in blocks)
    if coverage.get("complete") and gaps:
        lines.append("Source collection finished for this summary. Some parts were not summarized.")
    if any(
        b.get("span")
        and (
            b["span"].get("first_offset", 0) > 0
            or b["span"].get("last_offset", 0) < b["span"].get("last_total", 0)
        )
        for b in blocks
    ):
        lines.append(
            (
                "Long messages were split into fragments. Some fragments were not "
                "summarized; citations still open the original "
                "entries."
            )
            if gaps
            else "Long messages were read in fragments; citations open the original entries."
        )
    if any(not b.get("span") for b in blocks) or report.get("reason") == "legacy_text":
        lines.append(
            "This saved summary used message excerpts; full message coverage was not recorded."
        )
    if (
        coverage.get("start_offset", 0) > 0
        or any(
            isinstance(r, dict) and r.get("reason") == "before_window"
            for r in coverage.get("unread", [])
        )
        or (blocks and blocks[0].get("gap") and blocks[0].get("reason") == "before_window")
    ):
        lines.append(
            "This summary starts partway through the session, not at its "
            "first entry. Earlier entries were not summarized "
            "here."
        )
    if coverage.get("agent_replies") == "not_read":
        lines.append(
            "The agent\u2019s replies were not read for this harness, so the summary has none."
        )
    unread = [r.get("reason", "") for r in coverage.get("unread", []) if isinstance(r, dict)]
    for reason in dict.fromkeys(unread):
        lines.append(  # noqa: PERF401 - the reason table stays beside its lookup
            {
                "source_bytes": (
                    "Compass reached its source-reading byte limit. "
                    "Part of the record remains unread."
                ),
                "source_time": (
                    "Compass reached its source-reading time limit. "
                    "Part of the record remains unread."
                ),
                "source_memory": (
                    "Compass reached its source-reading memory limit. "
                    "Part of the record remains unread."
                ),
                "source_stalled": (
                    "Compass could not advance through the record within a source "
                    "page. Part of it remains "
                    "unread."
                ),
                "source_changed": (
                    "The record changed while Compass was reading it, so the summary "
                    "stopped before sending "
                    "it."
                ),
                "oversized_line": "A record line too large to read was skipped.",
                "unreadable_record": "A record line could not be read and was skipped.",
                "unreadable_subagent": "Part of a subagent\u2019s record could not be read.",
            }.get(reason, f"Source coverage limit: {reason}.")
        )
    return lines


def _phases(summary: Mapping[str, Any], cited: Callable[[str, list[str]], str]) -> list[str]:
    lines: list[str] = []
    for block in summary.get("blocks", []):
        if block.get("gap"):
            lines.append(
                GAPS.get(block.get("reason", "stopped"), "This part could not be summarized.")
            )
            continue
        for phase in block.get("phases", []):
            lines.append(
                _shown(
                    {"reason": "too_long_cut"}
                    if (phase.get("cut") or {}).get("title")
                    else phase.get("title"),
                    title=True,
                )
            )
            for bullet in phase.get("bullets", []):
                value = {"reason": "too_long_cut"} if bullet.get("cut") else bullet.get("text")
                text = (
                    bullet_words(bullet.get("kind", ""), value)
                    if isinstance(value, str)
                    else _shown(value)
                )
                lines.append("- " + cited(text, bullet.get("cites", [])))
                cut_cites = bullet.get("cites_cut", 0)
                if cut_cites:
                    noun = "citation was" if cut_cites == 1 else "citations were"
                    lines.append(f"{cut_cites} more {noun} cut")
            if (phase.get("cut") or {}).get("bullets"):
                count = phase["cut"]["bullets"]
                noun = "line was" if count == 1 else "lines were"
                lines.append(f"{count} more {noun} cut from this phase.")
        withheld = (block.get("withheld_phases") or {}).get("shape_fault", 0)
        if withheld:
            lines.append(
                f"{withheld} phases were left out: "
                "they could not be shown in a form Compass accepts."
            )
        cut = block.get("cut") or {}
        if cut.get("phases"):
            noun = "phase was" if cut["phases"] == 1 else "phases were"
            lines.append(f"{cut['phases']} more {noun} cut from this part.")
        if cut.get("reply"):
            lines.append(
                "The model\u2019s reply for this part was cut short, so only the "
                "phases it finished are "
                "shown."
            )
    return lines


def _stamp(summary: Mapping[str, Any]) -> str:
    stamp = str(summary.get("model_stamp") or "Model not recorded")
    if len(stamp.split(":")) >= 3:
        stamp = stamp.split(":")[1]
    running = (summary.get("job") or {}).get("state") in ("running", "stopping")
    made = summary.get("made_at")
    if isinstance(made, (int, float)):
        try:
            stamp += " · updated " if running else " · summarized at "
            stamp += datetime.fromtimestamp(made, UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            stamp += " · write time unavailable"
    else:
        stamp += " · write time unavailable"
    if running:
        stamp += " · still running"
    return stamp


def render(summary: Mapping[str, Any], labels: Mapping[str, str], *, page_url: str) -> list[str]:
    lines = ["Summary: written by a model from this session\u2019s record"]
    stamp = _stamp(summary)
    lines.append(stamp)
    job = summary.get("job") or {}
    if job.get("state") not in (None, "running", "stopping", "complete"):
        reason = f" ({job['reason']})" if job.get("reason") else ""
        lines.append(f"Summary job: {job['state']}{reason}; stored summary shown below.")
    lines.extend(_freshness(summary))
    lines.extend(_notes(summary))
    missing: set[str] = set()

    def cited(text: str, cites: list[str]) -> str:
        missing.update(c for c in cites if c not in labels)
        suffix = " ".join(f"[#{labels[c]}]" for c in cites if c in labels)
        return text + (" " + suffix if suffix else "")

    lede = summary.get("lede")
    if lede:
        text = (
            lede
            if lede.get("withheld")
            else ({"reason": "too_long_cut"} if lede.get("cut") else lede.get("text"))
        )
        words = (
            lede_words(text)
            if isinstance(text, str)
            else _shown(text).replace("this line", "this opening summary")
        )
        lines.append(cited(words, lede.get("cites", [])))
    else:
        lines.append(
            "No opening summary."
            + (f" ({summary['lede_reason']})" if summary.get("lede_reason") else "")
        )
    lines.extend(_phases(summary, cited))
    if summary.get("state") != "ok" or any(b.get("gap") for b in summary.get("blocks", [])):
        lines.append("This summary does not cover every part of the session.")
        if summary.get("reason"):
            lines.append(f"Summary stopped: {summary['reason']}.")
    if missing:
        lines.append(f"{len(missing)} cited entries have no available label here.")
    lines.extend((RELEVANCE, page_url))
    return lines


def _update(summary: Mapping[str, Any]) -> tuple[bool, str]:
    report = summary.get("out_of_date") or {}
    if report.get("kind") == "unchanged" and not report.get("action"):
        return False, ""
    if report.get("action") == "update":
        return True, ""
    return False, "This summary cannot be updated; read it or explicitly request --summary --again."


def _run(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915 - one bounded command with injected I/O and clocks
    *,
    named: Session,
    board: Board,
    out: TextIO,
    err: TextIO,
    update: bool = False,
    again: bool = False,
    in_session: bool = True,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    wait: float = 20.0,
) -> int:
    own: str | None = None
    who = {"harness": named.harness, "sid": named.sid}
    deadline = clock() + wait
    try:
        payload = board.summary(who["harness"], who["sid"])
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("session"), dict)
            or not names(payload["session"], named.sid)
            or payload["session"].get("harness") != named.harness
        ):
            print("Compass could not read this session\u2019s summary unambiguously.", file=err)
            return 1
        row = payload["session"]
        who = {"harness": row["harness"], "sid": row["sid"]}
        summary = payload["summary"]
        job = summary.get("job") or {}
        active = job.get("state") in ("running", "stopping")
        action = "rerun" if again else "update" if update else "start"
        start = again or update or not summary.get("exists")
        if update and summary.get("exists"):
            start, refusal = _update(summary)
            if refusal:
                print(refusal, file=err)
                return 1
        if start and not active:
            body = {**who, "action": action, "origin": "press"}
            if in_session:
                body["typed_action"] = (
                    "summary again" if again else "summary update" if update else "summary"
                )
            status, answer = board.post("/api/summary", body)
            if status != 202 or not isinstance(answer, dict) or not answer.get("job", {}).get("id"):
                reason = (
                    answer.get("reason", "unconfirmed")
                    if isinstance(answer, dict)
                    else "unconfirmed"
                )
                print(f"Summary request refused ({reason}); nothing else was requested.", file=err)
                return 1
            job = answer["job"]
            own = str(job["id"])
            notice = job.get("notice") or answer.get("notice")
            if notice:
                print(
                    printable(
                        str(
                            answer.get("disclosure")
                            or payload.get("summaries", {}).get("disclosure")
                            or "Summary notice: session text is sent through your Claude Code to "
                            + str(notice.get("destination", "the configured destination"))
                            + "."
                        )
                    ),
                    file=out,
                )
            active = True
        if summary.get("exists") and not (update or again):
            active = False
        while active:
            if clock() >= deadline:
                print("The summary is still running; read it again later with --summary.", file=err)
                return 1
            sleep(0.25)
            payload = board.summary(who["harness"], who["sid"])
            if not isinstance(payload, dict):
                raise terminal_drift.Lost("summary")  # noqa: TRY301 - shared lost-reply handling
            summary = payload["summary"]
            job = summary.get("job") or {}
            if own is not None and job.get("id") != own:
                print("The summary job changed; read it again with --summary.", file=err)
                return 1
            active = job.get("state") in ("running", "stopping")
        if not summary.get("exists"):
            print(
                f"No stored summary ({job.get('reason') or job.get('state') or 'unavailable'}).",
                file=err,
            )
            return 1
        url = terminal_drift.session_url(
            board.port, str(row.get("project") or ""), who["harness"], who["sid"]
        )
        text = "".join(
            printable(line) + "\n"
            for line in render(summary, payload.get("citation_labels", {}), page_url=url)
        )
        encoding = getattr(out, "encoding", None) or "utf-8"
        out.write(text.encode(encoding, "replace").decode(encoding, "replace"))
    except KeyboardInterrupt:
        if own is not None:
            try:
                board.post("/api/summary/cancel", {**who, "expected_job": own})
            except terminal_drift.Lost:
                print("Compass could not confirm cancellation; read the summary again.", file=err)
        print("Summary command interrupted.", file=err)
        return 130
    except terminal_drift.Lost:
        print(
            "Compass did not confirm the summary request; read it again before retrying a spend.",
            file=err,
        )
        return 1
    return 0


class TerminatedError(Exception):
    """A tool timeout stops waiting, without cancelling the admitted summary."""


@contextlib.contextmanager
def _termination(enabled: bool) -> Iterator[None]:
    def terminated(_signum: int, _frame: FrameType | None) -> None:
        raise TerminatedError

    if not enabled:
        yield
        return
    try:
        previous = signal.signal(signal.SIGTERM, terminated)
    except ValueError:
        # Only the main thread may install handlers; embedded callers retain their own.
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def run(  # noqa: PLR0913 - injected I/O and clock seams accompany command options
    *,
    named: Session,
    board: Board,
    out: TextIO,
    err: TextIO,
    update: bool = False,
    again: bool = False,
    in_session: bool = True,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    wait: float = 20.0,
) -> int:
    try:
        with _termination(in_session):
            return _run(
                named=named,
                board=board,
                out=out,
                err=err,
                update=update,
                again=again,
                in_session=in_session,
                clock=clock,
                sleep=sleep,
                wait=wait,
            )
    except TerminatedError:
        print(
            "The tool stopped waiting; any summary job already started keeps running, "
            "so read it again with --summary.",
            file=err,
        )
        return 143
