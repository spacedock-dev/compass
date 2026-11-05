"""Private ordinary parent words from an already verified native corpus.

This join establishes ordinary text completeness only. It proves neither finality
nor all-agent coverage, and is not a word cache or a source reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from . import events, records
from . import project_context as context
from . import reading_source_stream as raw_source

if TYPE_CHECKING:
    from .config import RuntimeConfig

Key = tuple[str, float]
Binding = Literal["native", "parent_file"]
Refusal = Literal["source", "admission", "conflict", "empty", "final_unfit"]


@dataclass(frozen=True)
class MessageWords:
    fact_id: str
    at: float
    type: str
    harness: str
    sid: str
    source: str
    state: Literal["whole", "unknown", "unavailable"] = "unknown"
    reason: Literal["missing", "", "source", "admission", "conflict", "empty", "final_unfit"] = (
        "missing"
    )
    binding: Binding | None = None
    words: str | None = None
    total: int | None = None


@dataclass(frozen=True)
class Join:
    """Collector-owned staging state; all signatures/indices count as retention."""

    parent: raw_source.FrozenParent
    identities: dict[Key, MessageWords]
    signatures: dict[Key, str] = field(default_factory=dict)
    positions: dict[Key, int] = field(default_factory=dict)
    refused: dict[Key, Refusal] = field(default_factory=dict)
    results: tuple[MessageWords, ...] = ()

    @classmethod
    def begin(
        cls,
        facts: tuple[dict[str, Any], ...],
        parent: raw_source.FrozenParent,
        *,
        unfit_final: Key | None = None,
    ) -> Join:
        ordered = sorted(
            (fact for fact in facts if fact.get("type") in {"user_message", "agent_message"}),
            key=lambda fact: (fact["type"] != "user_message", -float(fact.get("at") or 0)),
        )
        identities: dict[Key, MessageWords] = {}
        refused: dict[Key, Refusal] = {}
        for fact in ordered:
            session = records.as_dict(fact.get("source_session"))
            identity = MessageWords(
                fact["fact_id"],
                fact["at"],
                fact["type"],
                str(session.get("harness") or ""),
                str(session.get("sid") or ""),
                str(records.as_dict(fact.get("evidence")).get("source") or ""),
            )
            key = identity.fact_id, identity.at
            identities.setdefault(key, identity)
            if session != {"harness": parent.harness, "sid": parent.sid}:
                refused[key] = "source"
            if key == unfit_final:
                refused[key] = "final_unfit"
        return cls(parent, identities, refused=refused)

    def _binding(self, record: dict[str, Any]) -> Binding | None:
        native = record.get("sessionId")
        if native is None:
            return "parent_file"
        # This owner exposes a full native filename binding without doing a
        # final-reply lookup. Ordinary text gains no finality claim from it.
        expected = context._final_source_sid(self.parent.path, self.parent.harness, self.parent.sid)  # noqa: SLF001
        if expected != self.parent.sid:
            return "native" if native == expected else None
        if (
            isinstance(native, str)
            and native
            and (
                native == expected
                or events.normalize_session_id(self.parent.harness, native) == expected
            )
        ):
            return "native"
        return None

    def observe(self, config: RuntimeConfig, row: raw_source.RawRecord, position: int) -> Join:
        """Index raw identities/conflicts before retaining any complete words."""
        record = row.value
        if record.get("isSidechain") or record.get("isMeta") or record.get("agentId"):
            return self
        if context._message_text_chars(record) > context.PRESS_TEXT_MAX_CHARS:  # noqa: SLF001
            # Match G2's typing-time refusal for an oversized queued duplicate:
            # its exact identity cannot be recovered safely under admission.
            at = records.parse_ts(context._reader_stamp(record) or record.get("timestamp") or "")  # noqa: SLF001
            return replace(
                self,
                refused={
                    **self.refused,
                    **{key: "admission" for key in self.identities if key[1] == at},
                },
            )
        fact = context._ordinary_word_fact(config, record, self.parent.harness, self.parent.sid)  # noqa: SLF001
        if fact is None:
            return self
        return self._index_fact(fact, record, position)

    def _index_fact(self, fact: dict[str, Any], record: dict[str, Any], position: int) -> Join:
        key = fact["fact_id"], fact["at"]
        wanted = self.identities.get(key)
        if wanted is None or key in self.refused:
            return self
        binding = self._binding(record)
        if binding is None or (
            wanted.type != fact["type"]
            or wanted.source != records.as_dict(fact.get("evidence")).get("source")
        ):
            return replace(self, refused={**self.refused, key: "source"})
        signature = context._ordinary_word_signature(record)  # noqa: SLF001
        if key in self.signatures:
            if self.signatures[key] != signature:
                return replace(self, refused={**self.refused, key: "conflict"})
            return self
        return replace(
            self,
            identities={**self.identities, key: replace(wanted, binding=binding)},
            signatures={**self.signatures, key: signature},
            positions={**self.positions, key: position},
        )

    def materialize(
        self, config: RuntimeConfig, key: Key, rows: tuple[raw_source.RawRecord, ...]
    ) -> Join:
        """Mask and normalize a whole admitted source only after conflict resolution."""
        result = self.identities[key]
        if key in self.refused:
            result = replace(result, state="unavailable", reason=self.refused[key])
        elif key in self.positions:
            row = rows[self.positions[key]]
            words = context.whole_message_words(
                config, row.value, self.parent.harness, len(row.raw)
            )
            result = (
                replace(result, state="whole", reason="", words=words, total=len(words))
                if words
                else replace(result, state="unavailable", reason="empty")
            )
        return replace(self, results=(*self.results, result))
