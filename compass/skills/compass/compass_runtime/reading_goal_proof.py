"""Private complete adopted-goal words, bound through existing source-selection policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from . import reading, records

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .reading_source_words import MessageWords


@dataclass(frozen=True)
class Proof:
    saved_goal: str
    source_kind: str
    source_at: float
    harness: str
    sid: str
    fact_id: str | None
    at: float
    source: str
    words: str

    def header(self, goal: str, provenance: Mapping[str, Any]) -> dict[str, Any]:
        """Validate the exact immutable payload; final invocation rechecks its G2 origin."""
        if (
            self.saved_goal != goal
            or self.source_kind not in reading.PROMPT_SOURCES
            or self.source_kind != provenance["goal_source"]
            or self.source_at != provenance["goal_source_at"]
            or reading.valid_prompt_time(self.source_at) is None
            or reading.valid_prompt_time(self.at) is None
            or any(
                not isinstance(value, str) or not value
                for value in (self.harness, self.sid, self.source)
            )
            or not _whole(self.words)
            or (
                self.source_kind == reading.SESSION_GOAL
                and (self.fact_id is not None or self.words != goal or goal.endswith("…"))
            )
            or (
                self.source_kind != reading.SESSION_GOAL
                and (not isinstance(self.fact_id, str) or not self.fact_id)
            )
        ):
            raise ValueError("Invalid restored goal proof")
        value = asdict(self)
        value.pop("saved_goal")
        return value


def _whole(words: Any) -> bool:
    if not isinstance(words, str) or not 0 < len(words) <= reading.LEDGER_WORDS_CAP_CHARS:
        return False
    try:
        words.encode("utf-8")
    except UnicodeError:
        return False
    # This equality refuses a changed/secret-shaped or clipped input. It never substitutes
    # normalized words for the caller's complete G2 value.
    return records.safe_text(words, reading.LEDGER_WORDS_CAP_CHARS).strip() == words


def _joined(
    facts: Sequence[Mapping[str, Any]], words: Sequence[MessageWords], harness: str, sid: str
) -> list[tuple[MessageWords, dict[str, Any]]]:
    by_identity: dict[tuple[str, float], list[Mapping[str, Any]]] = {}
    for fact in facts:
        identity, at = fact.get("fact_id"), reading.valid_prompt_time(fact.get("at"))
        if isinstance(identity, str) and at is not None:
            by_identity.setdefault((identity, at), []).append(fact)
    result = []
    for word in words:
        matching = by_identity.get((word.fact_id, word.at), [])
        if len(matching) != 1:
            continue
        fact = matching[0]
        evidence = fact.get("evidence")
        if (
            word.state == "whole"
            and word.reason == ""
            and word.binding in {"native", "parent_file"}
            and word.type == fact.get("type") == "user_message"
            and reading.author_of(fact) == reading.AUTHOR_PERSON
            and (word.harness, word.sid) == (harness, sid)
            and fact.get("source_session") == {"harness": harness, "sid": sid}
            and isinstance(evidence, dict)
            and evidence.get("source") == word.source
            and type(word.at) in (int, float)
            and reading.valid_prompt_time(word.at) is not None
            and _whole(word.words)
            and type(word.total) is int
            and word.total == len(word.words or "")
        ):
            result.append((word, {**fact, reading.WORDS_FIELD: word.words}))
    return result


def restore(
    row: Mapping[str, Any],
    revision: Mapping[str, Any],
    facts: Sequence[Mapping[str, Any]],
    words: Sequence[MessageWords],
) -> Proof | None:
    """No source reads, no new admission, and no promotion of the owner's 1,000-char clip.

    Ordinary adoption requires an exact complete G2 identity/word join and the existing
    adopted_prompt choice. A /goal is the saved stated condition itself, not a person prompt.
    """
    kind = revision.get("goal_source")
    at = reading.valid_prompt_time(revision.get("goal_source_at"))
    goal = str(revision.get("goal") or "")
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    if kind not in reading.PROMPT_SOURCES or at is None or not reading.asks_goal(goal):
        return None
    if kind == reading.SESSION_GOAL:
        return (
            Proof(goal, kind, at, harness, sid, None, at, kind, goal)
            if _whole(goal) and not goal.endswith("…")
            else None
        )
    joined = _joined(facts, words, harness, sid)
    candidates = reading._goal_source_candidates(  # noqa: SLF001 - existing ambiguity/copied policy
        row, facts, [fact for _, fact in joined]
    )
    selected = reading.adopted_prompt(revision, candidates, harness, sid)
    matches = [word for word, _ in joined if (word.fact_id, word.words) == selected]
    if selected is None or len(matches) != 1:
        return None
    word = matches[0]
    # selected words must be the complete G2 value, never adopted_prompt's clipped output.
    return Proof(goal, kind, at, harness, sid, word.fact_id, word.at, word.source, selected[1])
