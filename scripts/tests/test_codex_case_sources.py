"""A person can trust a frozen Codex source only while its native proof stands."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if TYPE_CHECKING:
    from tests.codex_source_support import (
        AT,
        CHILD,
        SID,
        command,
        config,
        entry,
        event,
        message,
        rollout,
        stamp,
        write,
    )
else:
    from codex_source_support import (
        AT,
        CHILD,
        SID,
        command,
        config,
        entry,
        event,
        message,
        rollout,
        stamp,
        write,
    )
import codex_case_sources as sources
import levels_cases as levels
import mark_abstention as marker
import score_abstention as scorer
from compass_runtime import annotations as annotation_store
from compass_runtime import (
    http_api,
    reading_policy,
    reading_route,
    settings,
    state,
)
from compass_runtime import (
    project_context as context,
)


class CodexQualificationSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.config = config(self.home)

    def authored_spec(self, **changes: Any) -> dict[str, Any]:
        root = self.home / "authored"
        return {
            **entry(root, rollout(root)),
            "origin": "synthesised",
            "kind": "misleading-completion",
            "authored_by": "author",
            "verified_by": "different-person",
            **changes,
        }

    def test_a_person_cannot_author_an_uncovered_kind(self) -> None:
        with self.assertRaisesRegex(marker.FreezeError, "codex-authored-kind-ineligible"):
            sources.freeze_case(self.config, self.authored_spec(kind="legitimate-change"))

    def test_a_person_cannot_verify_their_own_authored_case(self) -> None:
        with self.assertRaisesRegex(marker.FreezeError, "codex-authored-identities-required"):
            sources.freeze_case(self.config, self.authored_spec(verified_by="author"))

    def test_a_person_must_supply_nonblank_string_source_paths(self) -> None:
        spec = self.authored_spec()
        with contextlib.chdir(spec["sessions_root"]):
            for field in ("sessions_root", "transcript"):
                for value in ("", " \t", None, 1):
                    with (
                        self.subTest(field=field, value=value),
                        self.assertRaisesRegex(marker.FreezeError, "codex-source-root-invalid"),
                    ):
                        sources.freeze_case(self.config, {**spec, field: value})

    def test_a_person_cannot_freeze_rollouts_from_a_nested_checkout(self) -> None:
        spec = self.authored_spec()
        nested = Path(spec["sessions_root"]) / "checkout"
        nested.mkdir()
        (nested / ".git").mkdir()
        path = rollout(nested, sid=CHILD)
        for selection in ({**spec, "transcript": str(path), "sid": CHILD}, spec):
            with (
                self.subTest(transcript=selection["transcript"]),
                mock.patch.object(sources, "_head", wraps=sources._head) as head,
                self.assertRaisesRegex(marker.FreezeError, "codex-source-outside-selection"),
            ):
                sources.freeze_case(self.config, selection)
            head.assert_not_called()

    def test_a_person_cannot_reuse_marks_after_an_authored_case_changes(self) -> None:
        spec = self.authored_spec()
        case = sources.freeze_case(self.config, spec)
        body = {"v": marker.FORMAT_CODEX, "cases": [case]}
        with mock.patch("builtins.input", return_value="n"):
            marks = marker._bound_marks(body, {case["id"]: marker._mark_one(body, case)})
        self.assertEqual(
            set(case["production_reading"]["constraints"]), set(marks["marks"][case["id"]])
        )
        cases_path = self.home / "cases.json"
        marks_path = self.home / "marks.json"
        cases_path.write_text(json.dumps(body))
        marks_path.write_text(json.dumps(marks))
        before = marks_path.read_bytes()
        body["cases"] = [
            sources.freeze_case(self.config, {**spec, "verified_by": "other-verifier"})
        ]
        cases_path.write_text(json.dumps(body))
        with (
            mock.patch.object(marker, "CASES_PATH", str(cases_path)),
            mock.patch.object(marker, "MARKS_PATH", str(marks_path)),
            mock.patch.object(marker, "_ledger_refusal", return_value=False),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(1, marker.mark())
        self.assertEqual(before, marks_path.read_bytes())

    def test_a_person_freezes_the_analyze_prompt_without_codex_agent_text(self) -> None:
        root = self.home / "codex/sessions/2026/11/07"
        path = rollout(root)
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[3:3] = [
            command(2 + number / 100, command_text=f"python3 -m pytest tests/test_{number:02d}.py")
            for number in range(64)
        ]
        commentary = "Distinct synthetic commentary."
        final = rows[-2]["payload"]["content"][0]["text"]
        rows.insert(
            -2,
            {
                **rows[-2],
                "timestamp": stamp(4.5),
                "payload": {
                    **rows[-2]["payload"],
                    "id": "commentary-a",
                    "phase": "commentary",
                    "content": [{"type": "output_text", "text": commentary}],
                },
            },
        )
        write(path, rows)
        case, production, frozen = self.analyze_and_freeze(entry(root.parents[2], path))
        self.assertIn("python3 -m pytest", production)
        self.assertGreater(len(production.encode()), 16_384)
        for text in (commentary, final):
            self.assertNotIn(text, production)
            self.assertNotIn(text, frozen)
            self.assertNotIn(text, json.dumps(case))
        self.assert_prompt_equal(production, frozen)
        self.assertEqual(
            marker.production_prompt_digest(production), case["production_reading"]["prompt_digest"]
        )

    def test_a_person_freezes_the_focused_timeline_when_checks_fill_it(self) -> None:
        root = self.home / "codex/sessions"
        path = rollout(root / "2026/11/07")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        settings.save(self.config, {"analyze_record_events": 100})
        rows[3:3] = [
            command(2 + number / 250, command_text=f"python3 -m pytest tests/test_{number:03d}.py")
            for number in range(120)
        ]
        change = command(4.5)
        change["payload"]["item"] = {
            "id": "write-proof",
            "type": "FileChange",
            "status": "completed",
            "changes": {"/synthetic/project/src/example.py": {"type": "add", "content": "sample"}},
            "stdout": "",
            "stderr": "",
        }
        rows.insert(-1, change)
        write(path, rows)
        spec = entry(root, path)
        spec["intent"]["at"] = AT + 2.95
        _, production, frozen = self.analyze_and_freeze(spec)
        self.assertNotIn("src/example.py", production)
        self.assert_prompt_equal(production, frozen)

    def test_a_persons_in_window_message_survives_a_timeline_full_of_checks(self) -> None:
        root = self.home / "codex/sessions"
        path = rollout(root / "2026/11/07")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        instruction = rows[2]["payload"]["content"][0]["text"]
        settings.save(self.config, {"analyze_record_events": 100})
        # The two existing runs of the same command contribute one latest check.
        rows[3:3] = [
            command(2 + number / 250, command_text=f"python3 -m pytest tests/test_{number:03d}.py")
            for number in range(99)
        ]
        write(path, rows)
        case, production, frozen = self.analyze_and_freeze(entry(root, path))
        self.assertEqual(100, sum(fact["type"] == "tool_report" for fact in case["producer_facts"]))
        scored, leveled = self.replay_prompts(case)
        self.assertIn(instruction, production)
        for name, prompt in (("frozen", frozen), ("scored", scored), ("levels", leveled)):
            with self.subTest(prompt=name):
                self.assert_prompt_equal(production, prompt)

    def test_a_persons_long_message_survives_freeze_and_both_replays(self) -> None:
        root = self.home / "codex/sessions"
        path = rollout(root / "2026/11/07")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        sentinel = "TAIL_MARKER_PAST_1500: do not touch billing.py."
        rows[2] = message(
            "Please verify the change. " + "Background context sentence. " * 60 + sentinel
        )
        write(path, rows)
        case, production, frozen = self.analyze_and_freeze(entry(root, path))
        original = rows[2]["payload"]["content"][0]["text"]
        duplicate = message(original.replace(sentinel, "Verify billing.py instead."))
        with path.open("a") as handle:
            for row in (event("task_started", 40, turn_id="turn-b"), duplicate):
                handle.write(json.dumps(row) + "\n")
        scored, leveled = self.replay_prompts(case)
        for name, prompt in (("frozen", frozen), ("scored", scored), ("levels", leveled)):
            with self.subTest(prompt=name):
                self.assertIn(sentinel, prompt)
                self.assert_prompt_equal(production, prompt)

    def replay_prompts(self, case: dict[str, Any]) -> tuple[str, str]:
        tool_output = scorer._tool_output(case, "OpenAI", "Codex", {"v": marker.FORMAT_CODEX})
        score_sink = mock.Mock(return_value=("{}", "ok"))
        result = scorer.score_case(
            self.config,
            case,
            case["row_snapshot"],
            case["producer_facts"],
            {},
            model=score_sink,
            now=case["captured_at"],
            revision=marker.case_revision(case),
            tool_output=tool_output,
        )
        levels_sink = mock.Mock(return_value=("{}", "ok"))
        levels._produce(self.config, case, levels_sink, tool_output, case["captured_at"])
        self.assertEqual(1, score_sink.call_count, result)
        levels_sink.assert_called_once()
        return score_sink.call_args.args[0], levels_sink.call_args.args[0]

    def assert_prompt_equal(self, expected: str, actual: str) -> None:
        self.assertEqual(
            marker.normalized_production_prompt(expected).encode(),
            marker.normalized_production_prompt(actual).encode(),
        )

    def analyze_and_freeze(self, spec: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        frozen_prompts: list[str] = []
        build_prompt = marker._reading().build_prompt

        def capture_frozen_prompt(*args: Any, **kwargs: Any) -> Any:
            result = build_prompt(*args, **kwargs)
            frozen_prompts.append(result[0])
            return result

        with mock.patch.object(marker._reading(), "build_prompt", capture_frozen_prompt):
            case = sources.freeze_case(self.config, spec)
        row = {**case["row_snapshot"], "project": "synthetic", "acquisition": "event"}
        revision = cast("annotation_store.Revision", marker.case_revision(case))
        handler = object.__new__(http_api._RequestHandler)
        handler.server = mock.Mock(
            application=mock.Mock(
                config=self.config,
                state=state.RuntimeState(self.config, AT),
                clock=lambda: AT + 20,
            )
        )
        sink = mock.Mock(return_value=("{}", "ok"))
        route = cast(
            "reading_route.Route",
            {
                "provider": reading_route.CODEX,
                "harness": "codex",
                "model": "gpt-5.6-luna",
                "label": "Codex",
                "destination": "OpenAI",
                "words_destination": "OpenAI",
            },
        )
        with (
            mock.patch.object(reading_policy, "GuardedModel", return_value=sink),
            mock.patch.object(http_api, "_read_ci", return_value=None),
        ):
            _, why, _ = handler._compose_reading(
                row,
                {"harness": "codex", "sid": SID, "revisions": (revision,)},
                route,
                mock.Mock(),
            )
        self.assertEqual(1, sink.call_count, why)
        self.assertEqual(1, len(frozen_prompts))
        return case, sink.call_args.args[0], frozen_prompts[0]


class FrozenCodexRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.path = rollout(self.home / "codex/sessions")
        self.config = config(self.home)

    def test_a_person_gets_the_checks_that_existed_before_a_later_failure(self) -> None:
        before, _ = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        with self.path.open("a") as f:
            f.write(json.dumps(command(30, 1)) + "\n")
        after, _ = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        self.assertTrue(before)
        self.assertEqual(before, after)

    def test_a_person_can_use_their_tagged_and_older_untagged_messages(self) -> None:
        for tagged in (True, False):
            with self.subTest(tagged=tagged):
                self.path = rollout(self.home / "sessions", tagged=tagged)
                whole, tail = context.frozen_codex_user_messages(
                    self.config, str(self.path), SID, until=AT + 10
                )
                self.assertEqual(len(whole), 1)
                self.assertEqual(whole, tail)
                self.assertIn("Please repair", whole[0][context.READER_WORDS_FIELD])

    def test_a_person_is_not_credited_with_an_unattributable_older_message(self) -> None:
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows.insert(
            3,
            message(
                "<codex_internal_context>injected</codex_internal_context>", tagged=False, delta=2
            ),
        )
        write(self.path, rows)
        whole, _ = context.frozen_codex_user_messages(
            self.config, str(self.path), SID, until=AT + 10
        )
        self.assertEqual(len(whole), 1)

    def test_a_person_is_not_credited_with_a_tagged_injected_message(self) -> None:
        row = message("Unrecognizable injected prose", delta=2)
        row["payload"]["internal_chat_message_metadata_passthrough"]["content_item_metadata"][0][
            "provenance"
        ]["type"] = "agents_md"
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        whole, _ = context.frozen_codex_user_messages(
            self.config, str(self.path), SID, until=AT + 10
        )
        self.assertEqual(len(whole), 1)

    def test_a_person_is_not_credited_with_malformed_untagged_content(self) -> None:
        contents: tuple[Any, ...] = (None, "PRIVATE-INJECTED", [], [None], [{"text": []}])
        for content in contents:
            with self.subTest(shape=content):
                row = message(tagged=False)
                row["payload"]["content"] = content
                self.assertFalse(context.codex_person_record(row))

    def test_a_person_keeps_explicit_provenance_for_multiple_text_items_and_markup(self) -> None:
        row = message("<user_instructions>person text</user_instructions>")
        self.assertTrue(context.codex_person_record(row))
        row["payload"]["content"].append({"type": "input_text", "text": "second person item"})
        row["payload"]["internal_chat_message_metadata_passthrough"]["content_item_metadata"] *= 2
        self.assertTrue(context.codex_person_record(row))

    def test_a_person_gets_redaction_before_message_clipping(self) -> None:
        from compass_runtime import observer  # noqa: PLC0415

        secret = "AKIA" + "A" * 16
        for cap in (112, context.READER_WORDS_CAP_CHARS, 2000):
            text = "Fix the observer. " + "x" * (cap - 37) + " " + secret
            row = message(text)
            parsed = observer.parse_reader_record(row, cap=cap)
            assert parsed is not None
            self.assertNotIn(secret[:-2], parsed["text"])
            self.assertIn("REDACTED", parsed["text"])
            rows = [json.loads(line) for line in self.path.read_text().splitlines()]
            rows[2] = row
            write(self.path, rows)
            whole, _ = context.frozen_codex_user_messages(
                self.config, str(self.path), SID, until=AT + 10
            )
            self.assertNotIn(secret[:-2], json.dumps(whole))

    def test_a_person_cannot_freeze_an_unreachable_cutoff(self) -> None:
        from dataclasses import replace  # noqa: PLC0415

        with self.assertRaises(context.FrozenCheckCutoffUnreachableError):
            context.frozen_codex_checks(
                replace(self.config, turn_scan_max_bytes=64), str(self.path), SID, until=AT + 10
            )

    def test_a_person_distinguishes_late_same_turn_results_from_resumed_work(self) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(command(8, 1)) + "\n")
            f.write(
                json.dumps({"type": "event_msg", "payload": {"type": "thread_settings_applied"}})
                + "\n"
            )
        self.assertFalse(context.codex_activity_between(str(self.path), AT + 6, AT + 10))
        with self.path.open("a") as f:
            f.write(json.dumps(event("task_started", 9, turn_id="turn-b")) + "\n")
        self.assertTrue(context.codex_activity_between(str(self.path), AT + 6, AT + 10))

    def test_a_person_cannot_treat_an_unreadable_command_as_an_empty_check_history(self) -> None:
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows[3]["payload"]["item"]["command"] = ["unrecognized-shell"]
        write(self.path, rows)
        with self.assertRaises(context.FrozenCheckCutoffUnreachableError):
            context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        with self.assertRaisesRegex(context.FrozenCheckCutoffUnreachableError, "checks incomplete"):
            sources.freeze_case(self.config, entry(self.path.parent, self.path))

    def test_a_person_cannot_lose_a_named_worker_when_its_rollout_is_missing(self) -> None:
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows.insert(
            3,
            {
                "timestamp": rows[2]["timestamp"],
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "call_id": "spawn-a",
                    "name": "spawn_agent",
                    "arguments": "{}",
                },
            },
        )
        write(self.path, rows)
        with self.assertRaises(context.FrozenCheckCutoffUnreachableError):
            context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        with self.assertRaisesRegex(context.FrozenCheckCutoffUnreachableError, "checks incomplete"):
            sources.freeze_case(self.config, entry(self.path.parent, self.path))

    def test_a_person_keeps_changed_after_as_it_was_before_a_later_write(self) -> None:
        _, press = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        late = event(
            "item_completed",
            30,
            item={
                "type": "FileChange",
                "id": "write-a",
                "status": "completed",
                "changes": {
                    "/synthetic/project/example.py": {
                        "type": "update",
                        "content": "",
                        "unified_diff": "",
                        "move_path": None,
                    }
                },
            },
            completed_at_ms=int((AT + 30) * 1000),
            started_at_ms=int((AT + 29) * 1000),
        )
        with self.path.open("a") as f:
            f.write(json.dumps(late) + "\n")
        _, before = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        _, after = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 40)
        self.assertEqual(before.changed_after, press.changed_after)
        self.assertNotEqual(before.changed_after, after.changed_after)

    def test_a_person_cannot_retain_a_temporary_raw_cut_after_an_exception(self) -> None:
        import os  # noqa: PLC0415

        with (
            self.assertRaisesRegex(ValueError, "synthetic refusal"),
            context.frozen_codex_sources(self.config, str(self.path), until=AT + 10) as (cut, _),
        ):
            self.assertEqual(os.stat(cut).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(Path(cut).parent).st_mode & 0o777, 0o700)
            raise ValueError("synthetic refusal")
        self.assertFalse(Path(cut).exists())
