"""A session's entries keep the number they were first given (DRC-4897).

A message is numbered by its rank among every message in the session, oldest first. A check or file is
numbered by the message it follows and its place after that message. Both are read from the transcript,
which only ever gains records at its end, so neither moves as the session grows.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import entry_numbers, http_api, observer, record_pages
from compass_runtime.state import build_runtime_state

from .test_claude_checks import SHORT, ClaudeChecksTestCase

KEY = b"entry-numbers-test"


class EntryNumbersTestCase(ClaudeChecksTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.state = build_runtime_state(self.config, started=0)

    def say(self, text: str) -> None:
        self.session._entry("assistant", [{"type": "text", "text": text}])

    def index(self) -> entry_numbers.MessageIndex:
        self.session.save(self.path)
        found = entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        assert found is not None
        return found

    def message_ids(self) -> list[str]:
        """The record page's message ids, oldest first."""
        page = record_pages.read(
            self.config, str(self.path), "claude", SHORT, cursor_key=KEY, limit=50
        )
        return [str(entry["fact_id"]) for entry in reversed(page["entries"])]

    def positions(self, **provider: Any) -> dict[str, tuple[int, int]]:
        """Each listed entry's `(number, place)` for the session as saved, keyed by its title."""
        self.session.save(self.path)

        def provide() -> entry_numbers.MessageIndex | None:
            return entry_numbers.message_index(
                self.config, self.state, str(self.path), "claude", SHORT
            )

        entries, _scan = project_context_reports(self, provide, **provider)
        return {
            str(row["title"]): (row["ordinal"], row["ordinal_sub"])
            for row in entries
            if "ordinal" in row
        }


def project_context_reports(
    case: ClaudeChecksTestCase, provide: Any, **kwargs: Any
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from compass_runtime import project_context  # noqa: PLC0415

    return project_context.claude_tool_reports(
        case.config, str(case.path), SHORT, index_provider=provide, **kwargs
    )


class MessageIndexTest(EntryNumbersTestCase):
    def test_a_message_is_numbered_by_its_rank_among_the_sessions_messages(self) -> None:
        self.say("First answer.")
        self.session.bash("pytest -q", "1 passed")
        self.session.prompt("Now the second thing.")
        index = self.index()
        ids = self.message_ids()
        # The setUp prompt, the answer and the second prompt; the tool call and its result are not messages.
        self.assertEqual([1, 2, 3], [index.ordinal(fact_id) for fact_id in ids])
        self.assertIsNone(index.ordinal("not-a-fact"))

    def test_a_number_never_moves_as_the_session_grows(self) -> None:
        self.say("One.")
        before = self.index()
        first = {fact_id: before.ordinal(fact_id) for fact_id in self.message_ids()}
        self.session.bash("pytest -q", "1 passed")
        self.say("Two.")
        self.session.prompt("Three.")
        after = self.index()
        self.assertEqual(first, {fact_id: after.ordinal(fact_id) for fact_id in first})
        self.assertEqual(
            list(range(1, 5)), [after.ordinal(fact_id) for fact_id in self.message_ids()]
        )

    def test_a_line_still_being_written_waits_for_its_newline(self) -> None:
        self.say("Done.")
        self.session.save(self.path)
        whole = json.dumps(self.session.rows[-1])
        # The last record cut short: no newline and not yet valid JSON.
        cut = self.path.read_bytes().rsplit(b"\n", 2)[0] + b"\n" + whole[:40].encode()
        self.path.write_bytes(cut)
        index = entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        assert index is not None
        self.assertEqual(1, len(index.keys))
        self.path.write_bytes(cut[: -len(whole[:40])] + whole.encode() + b"\n")
        index = entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        assert index is not None
        self.assertEqual(2, len(index.keys))

    def test_a_last_record_without_its_newline_is_numbered_as_the_page_reads_it(self) -> None:
        self.say("Done.")
        self.session.save(self.path)
        self.path.write_bytes(self.path.read_bytes().rstrip(b"\n"))
        index = entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        assert index is not None
        self.assertEqual(2, len(index.keys))
        self.assertEqual(
            [1, 2], [index.ordinal(fact_id) for fact_id in self.message_ids()][::-1][::-1]
        )
        with self.path.open("ab") as handle:
            handle.write(b"\n")
        again = entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        assert again is not None
        self.assertEqual(2, len(again.keys))

    def test_a_transcript_that_shrinks_or_is_replaced_is_read_again_from_its_start(self) -> None:
        self.say("One.")
        self.say("Two.")
        self.assertEqual(3, len(self.index().keys))
        self.session.rows = self.session.rows[:1]
        self.assertEqual(1, len(self.index().keys))

    def test_a_pass_that_runs_out_of_time_keeps_what_it_read_and_resumes(self) -> None:
        for n in range(6):
            self.say(f"Answer {n}.")
        self.session.save(self.path)
        clock = iter([0.0, 0.0, 0.0, 0.0, 99.0, 99.0, 99.0])
        with mock.patch(
            "compass_runtime.entry_numbers.time.monotonic", side_effect=lambda: next(clock, 99.0)
        ):
            self.assertIsNone(
                entry_numbers.message_index(
                    self.config, self.state, str(self.path), "claude", SHORT
                )
            )
        held = next(iter(self.state.entry_indexes.values()))
        self.assertFalse(held.complete)
        read = len(held.keys)
        self.assertLess(read, 7)
        index = entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        assert index is not None
        self.assertEqual(7, len(index.keys))
        self.assertEqual(
            list(range(1, 8)), [index.ordinal(fact_id) for fact_id in self.message_ids()]
        )

    def test_a_message_line_over_the_cap_is_skipped_and_the_rest_still_numbered(self) -> None:
        self.say("Before.")
        self.say("x" * 5000)
        self.say("After.")
        with mock.patch.object(entry_numbers, "_LINE_CAP", 2500):
            index = self.index()
        self.assertEqual(3, len(index.keys))
        numbers = [index.ordinal(fact_id) for fact_id in self.message_ids()]
        self.assertEqual([1, 2], sorted(x for x in numbers if x is not None)[:2])
        self.assertEqual(1, numbers.count(None))

    def test_a_very_long_single_word_message_costs_the_index_no_masking(self) -> None:
        self.say("Before.")
        self.say("x" * (300 * 1024))
        self.say("After.")
        started = time.monotonic()
        index = self.index()
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(4, len(index.keys))

    def test_the_index_and_the_pages_give_a_long_message_the_same_id(self) -> None:
        self.say("Before.")
        self.say("word " * 20_000)
        index = self.index()
        ids = self.message_ids()
        self.assertEqual(sorted(index.seen), sorted(ids))

    def test_a_missing_transcript_publishes_nothing(self) -> None:
        self.assertIsNone(
            entry_numbers.message_index(
                self.config, self.state, str(self.root / "gone.jsonl"), "claude", SHORT
            )
        )

    def test_the_cache_keeps_a_bounded_number_of_indexes(self) -> None:
        self.say("One.")
        self.session.save(self.path)
        limit = self.config.entry_index_limit
        for n in range(limit + 4):
            entry_numbers.message_index(self.config, self.state, str(self.path), "claude", f"s{n}")
        self.assertEqual(limit, len(self.state.entry_indexes))

    def test_message_facts_gain_their_number_and_the_input_is_never_changed(self) -> None:
        self.say("One.")
        index = self.index()
        ids = self.message_ids()
        facts = [
            {"fact_id": ids[0], "type": "user_message"},
            {"fact_id": "x", "type": "tool_report"},
        ]
        numbered = entry_numbers.with_message_ordinals(index, facts)
        self.assertEqual(1, numbered[0]["ordinal"])
        self.assertNotIn("ordinal", numbered[1])
        self.assertNotIn("ordinal", facts[0])


class LargeTranscriptTest(EntryNumbersTestCase):
    """The first request on a long session pays for one forward pass, inside the record page bound."""

    def write_large(self, megabytes: int) -> int:
        """Tool results dominate a real transcript's bytes; a message is one record in six."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        messages = 0
        written = 0
        number = 0
        with self.path.open("w") as handle:
            while written < megabytes * 1024 * 1024:
                number += 1
                stamp = f"2026-10-01T{(number // 3600) % 24:02}:{(number // 60) % 60:02}:{number % 60:02}Z"
                if number % 6 in {0, 1}:
                    role = "user" if number % 6 == 0 else "assistant"
                    content: list[dict[str, Any]] = [{"type": "text", "text": f"Step {number}."}]
                    messages += 1
                else:
                    role = "user"
                    content = [
                        {"type": "tool_result", "tool_use_id": f"x{number}", "content": "y" * 40000}
                    ]
                line = json.dumps(
                    {
                        "type": role,
                        "timestamp": stamp,
                        "uuid": f"r{number}",
                        "message": {"role": role, "content": content},
                    }
                )
                handle.write(line + "\n")
                written += len(line) + 1
        return messages

    def test_the_first_pass_over_sixty_megabytes_is_inside_the_record_page_bound(self) -> None:
        messages = self.write_large(60)
        self.assertGreaterEqual(self.path.stat().st_size, 60 * 1024 * 1024)
        started = time.monotonic()
        index = entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        elapsed = time.monotonic() - started
        assert index is not None
        self.assertEqual(messages, len(index.keys))
        self.assertLess(elapsed, self.config.record_page_max_seconds)

    def test_the_next_request_reads_only_what_the_transcript_gained(self) -> None:
        messages = self.write_large(8)
        index = entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        assert index is not None
        read_to = index.end
        with self.path.open("a") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-10-02T00:00:00Z",
                        "uuid": "late",
                        "message": {"role": "user", "content": [{"type": "text", "text": "More."}]},
                    }
                )
                + "\n"
            )
        started = time.monotonic()
        again = entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        elapsed = time.monotonic() - started
        assert again is not None
        self.assertIs(index, again)
        self.assertEqual(messages + 1, len(again.keys))
        self.assertGreater(again.end, read_to)
        self.assertLess(elapsed, 0.25)


class ToolPositionTest(EntryNumbersTestCase):
    def test_a_check_or_file_is_numbered_by_the_message_it_follows(self) -> None:
        self.session.bash("pytest tests/a.py", "1 passed")
        self.session.write(self.file("src/one.py"))
        self.say("Wrote it.")
        self.session.bash("pytest tests/b.py", "1 passed")
        found = self.positions()
        self.assertEqual(
            {
                "pytest tests/a.py": (1, 1),
                "src/one.py": (1, 2),
                "pytest tests/b.py": (2, 1),
            },
            {title: found[title] for title in found},
        )

    def test_a_check_that_runs_again_keeps_the_place_of_its_first_run(self) -> None:
        self.session.bash("pytest tests/a.py", "1 failed", is_error=True)
        self.say("Fixing it.")
        self.session.prompt("Go on.")
        before = self.positions()["pytest tests/a.py"]
        self.session.bash("pytest tests/a.py", "1 passed")
        entries, _scan = project_context_reports(self, self.provider())
        row = next(row for row in entries if row["title"] == "pytest tests/a.py")
        self.assertEqual(before, (row["ordinal"], row["ordinal_sub"]))
        self.assertEqual(("passed", 1), (row["result"], row["ordinal"]))

    def test_a_failed_check_a_later_pass_covers_leaves_the_files_number_alone(self) -> None:
        self.say("Starting.")
        self.session.bash("python3 -m pytest tests/a.py::T::t1", "1 failed", is_error=True)
        self.session.write(self.file("src/fix.py"))
        before = self.positions()
        self.assertIn("python3 -m pytest tests/a.py::T::t1", before)
        self.session.bash("python3 -m pytest tests/a.py", "2 passed")
        after = self.positions()
        self.assertNotIn("python3 -m pytest tests/a.py::T::t1", after)
        self.assertEqual(before["src/fix.py"], after["src/fix.py"])
        self.assertEqual(
            before["python3 -m pytest tests/a.py::T::t1"][0],
            after["python3 -m pytest tests/a.py"][0],
        )

    def test_a_new_message_moves_no_number(self) -> None:
        self.session.bash("pytest tests/a.py", "1 passed")
        self.say("Done.")
        before = self.positions()
        self.session.prompt("And another thing.")
        self.session.bash("pytest tests/b.py", "1 passed")
        after = self.positions()
        self.assertEqual(before, {title: after[title] for title in before})
        self.assertEqual((3, 1), after["pytest tests/b.py"])

    def test_the_listing_of_twelve_evicts_entries_and_no_other_number_moves(self) -> None:
        self.session.bash("pytest tests/pass.py", "1 passed")
        for n in range(11):
            self.session.bash(f"pytest tests/f{n}.py", "1 failed", is_error=True)
        twelve = self.positions()
        self.assertEqual(12, len(twelve))
        self.assertEqual((1, 1), twelve["pytest tests/pass.py"])
        for n in range(11, 13):
            self.session.bash(f"pytest tests/f{n}.py", "1 failed", is_error=True)
        fourteen = self.positions()
        # Failures are kept first and newest first, so the pass and the oldest failure leave the listing.
        self.assertEqual(12, len(fourteen))
        evicted = {"pytest tests/pass.py", "pytest tests/f0.py"}
        self.assertFalse(evicted & set(fourteen))
        survivors = {title: place for title, place in twelve.items() if title not in evicted}
        self.assertEqual(survivors, {title: fourteen[title] for title in survivors})
        # Their places are gaps, not renumbered: the next entries take the next places.
        self.assertEqual((1, 13), fourteen["pytest tests/f11.py"])
        self.assertEqual((1, 14), fourteen["pytest tests/f12.py"])

    def test_a_file_written_again_keeps_the_place_of_its_first_write(self) -> None:
        self.session.write(self.file("shared.py"))
        self.say("Wrote it.")
        first = self.positions()["shared.py"]
        self.session.edit(self.file("shared.py"))
        self.assertEqual(first, self.positions()["shared.py"])

    def test_no_position_is_published_without_an_index(self) -> None:
        self.session.bash("pytest tests/a.py", "1 passed")
        entries, _scan = self.read()
        self.assertTrue(entries)
        self.assertFalse([row for row in entries if "ordinal" in row])

    def provider(self) -> Any:
        self.session.save(self.path)
        return lambda: entry_numbers.message_index(
            self.config, self.state, str(self.path), "claude", SHORT
        )


class ToolPositionFunctionTest(EntryNumbersTestCase):
    def test_a_candidate_before_every_message_follows_message_zero(self) -> None:
        index = entry_numbers.MessageIndex("claude", SHORT)
        index._add("a", 10.0)
        positions = entry_numbers.tool_positions(index, [("first", 5.0), ("second", 6.0)])
        self.assertEqual({"first": (0, 1), "second": (0, 2)}, positions)

    def test_entries_that_share_a_time_keep_one_order_by_key(self) -> None:
        index = entry_numbers.MessageIndex("claude", SHORT)
        index._add("a", 1.0)
        left = entry_numbers.tool_positions(index, [("b", 2.0), ("a", 2.0)])
        right = entry_numbers.tool_positions(index, [("a", 2.0), ("b", 2.0)])
        self.assertEqual(left, right)
        self.assertEqual({"a": (1, 1), "b": (1, 2)}, left)

    def test_a_pull_request_or_skill_never_moves_the_number_of_an_older_kind(self) -> None:
        # Owner review, 2026-10-23: a saved number is what a reader sees and cites. A pull request or
        # skill joining a message's group must not shift any check, file or launch after it.
        index = entry_numbers.MessageIndex("claude", SHORT)
        index._add("a", 1.0)
        before = entry_numbers.tool_positions(
            index, [("check:x", 2.0), ("write:f", 3.0), ("launch:l", 4.0)]
        )
        after = entry_numbers.tool_positions(
            index,
            [
                ("check:x", 2.0),
                ("pr:o/r#1", 2.5),
                ("write:f", 3.0),
                ("skill:s", 3.5),
                ("launch:l", 4.0),
            ],
        )
        for key, position in before.items():
            self.assertEqual(position, after[key], key)
        self.assertEqual(5, len(set(after.values())))

    def test_a_pull_request_keeps_its_number_as_later_checks_arrive(self) -> None:
        index = entry_numbers.MessageIndex("claude", SHORT)
        index._add("a", 1.0)
        first = entry_numbers.tool_positions(index, [("check:x", 2.0), ("pr:o/r#1", 3.0)])
        later = entry_numbers.tool_positions(
            index, [("check:x", 2.0), ("pr:o/r#1", 3.0), ("check:y", 4.0), ("write:f", 5.0)]
        )
        self.assertEqual(first["pr:o/r#1"], later["pr:o/r#1"])


class FocusedContextTest(EntryNumbersTestCase):
    def app(self) -> Any:
        return SimpleNamespace(config=self.config, state=self.state)

    def context(self) -> dict[str, Any]:
        self.say("One.")
        self.session.save(self.path)
        facts = [
            {"fact_id": fact_id, "type": "user_message", "summary": "m"}
            for fact_id in self.message_ids()
        ]
        facts.append({"fact_id": "check-1", "type": "tool_report", "summary": "pytest"})
        return {"semantic": {"facts": facts}, "project": "p"}

    def test_the_focused_contexts_message_facts_carry_their_number(self) -> None:
        context = self.context()
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            out = http_api._with_message_ordinals(self.app(), context, ("claude", SHORT))
        numbers = [fact.get("ordinal") for fact in out["semantic"]["facts"]]
        self.assertEqual([1, 2, None], numbers)
        # The facts can be shared with a cache, so the input is left as it was.
        self.assertFalse([f for f in context["semantic"]["facts"] if "ordinal" in f])

    def test_a_context_without_a_transcript_or_facts_is_returned_as_it_was(self) -> None:
        context = self.context()
        with mock.patch.object(observer, "resolve_transcript", return_value=None):
            self.assertIs(
                context, http_api._with_message_ordinals(self.app(), context, ("claude", SHORT))
            )
        bare: dict[str, Any] = {"project": "p"}
        self.assertIs(bare, http_api._with_message_ordinals(self.app(), bare, ("claude", SHORT)))
