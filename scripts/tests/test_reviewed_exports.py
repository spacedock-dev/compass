"""Explicit reviewed synthetic exports exercise native intake, never qualification truth."""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mark_abstention as marking
import score_abstention as scoring

marking._reading()
from compass_runtime.config import build_runtime_config  # noqa: E402

# A Python start and an import, which a busy runner can stretch past a couple of seconds; the
# defect it guards is an open that never returns.
WAIT_SEC = 30.0


class ReviewedExportIntakeTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.sid = "12345678-1234-4234-8234-123456789abc"
        self.path = self.root / (self.sid + ".jsonl")
        self.start = dt.datetime(2026, 9, 24, tzinfo=dt.UTC).timestamp()
        self.rows: list[dict[str, Any]] = [
            self.record("user", 1, "Keep keyboard focus.", "person", None),
            self.record("assistant", 10, "Focus retained. " + "x" * 1200, "final", "person"),
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "uuid": "stop",
                "parentUuid": "final",
                "sessionId": self.sid,
                "isSidechain": False,
                "preventedContinuation": False,
                "timestamp": self.stamp(20),
            },
            {"type": "system", "subtype": "turn_duration", "timestamp": self.stamp(21)},
        ]
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root)},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.entry: dict[str, Any] = {
            "harness": "claude",
            "sid": self.sid[:8],
            "captured_at": self.start + 30,
            "row": {"state": "idle", "finished_at": self.start + 20},
            "intent": {
                "at": self.start,
                "goal": "Keep keyboard focus.",
                "lines": [{"text": "Tab keeps focus"}],
            },
            "transcript": str(self.path),
        }
        self.manifest = self.root / "reviewed.json"
        self.write_source()

    def stamp(self, offset: float) -> str:
        return dt.datetime.fromtimestamp(self.start + offset, dt.UTC).isoformat()

    def record(
        self, role: str, offset: float, text: str, uuid: str, parent: str | None
    ) -> dict[str, Any]:
        return {
            "type": role,
            "sessionId": self.sid,
            "uuid": uuid,
            "parentUuid": parent,
            "isSidechain": False,
            "isMeta": False,
            "timestamp": self.stamp(offset),
            "message": {
                "role": role,
                "stop_reason": "end_turn" if role == "assistant" else None,
                "content": [{"type": "text", "text": text}],
            },
        }

    def write_source(self) -> None:
        self.path.write_bytes("".join(json.dumps(row) + "\n" for row in self.rows).encode("utf-8"))
        self.receipt: dict[str, Any] = {
            "v": 1,
            "review": {"approved": True, "by": "synthetic-reviewer", "at": self.start},
            "exports": [
                {
                    "path": str(self.path),
                    "sid": self.sid,
                    "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                }
            ],
        }
        self.write_manifest()

    def write_manifest(self) -> None:
        self.manifest.write_text(json.dumps(self.receipt))
        self.digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def test_fixture_jsonl_has_exact_lf_bytes_even_with_windows_text_translation(self) -> None:
        actual_write_text = Path.write_text

        def translated(path: Path, text: str, *args: Any, **kwargs: Any) -> int:
            if path == self.path:
                path.write_bytes(text.encode().replace(b"\n", b"\r\n"))
                return len(text)
            return actual_write_text(path, text, *args, **kwargs)

        with mock.patch.object(Path, "write_text", autospec=True, side_effect=translated):
            self.write_source()
        self.assertEqual(
            "".join(json.dumps(row) + "\n" for row in self.rows).encode(),
            self.path.read_bytes(),
        )

    def resolver(self) -> marking.ReviewedExports:
        constructor = getattr(marking, "ReviewedExports", None)
        if constructor is None:
            self.fail("explicit trusted reviewed-export resolver is required")
        result: marking.ReviewedExports = constructor(str(self.manifest), self.digest)
        return result

    def freeze(self, resolver: marking.ReviewedExports | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"production_reading": True}
        if resolver is not None:
            kwargs["reviewed_exports"] = resolver
        return marking.freeze_case(self.config, self.entry, [], **kwargs)

    def vouch(self, resolver: marking.ReviewedExports | None) -> Any:
        return marking.make_vouch(
            observations=(), ends=(), index={}, config=self.config, reviewed_exports=resolver
        )

    @staticmethod
    def model(called: list[Any]) -> Any:
        def invoke(prompt: str, **_kwargs: Any) -> tuple[str, str]:
            called.append(prompt)
            return "{}", "ok"

        return invoke

    def test_explicit_native_stop_admits_export_without_history_and_default_stays_refused(
        self,
    ) -> None:
        default = self.freeze()
        self.assertEqual("synthetic", default["origin"])
        self.assertIn("lifecycle-unconfirmed", default["unconfirmed"])
        constructor = getattr(marking, "ReviewedExports", None)
        resolver = constructor(str(self.manifest), self.digest) if constructor else None
        case = self.freeze(resolver)
        self.assertEqual("recorded", case["origin"])
        self.assertEqual("reviewed-export", case["lifecycle_from"])
        self.assertEqual([], case["unconfirmed"])
        self.assertNotIn("reviewed_export", case["production_reading"])
        vouch = self.vouch(resolver)
        self.assertEqual([], vouch(case))
        self.assertEqual("reviewed-export", vouch.lifecycle(case))
        self.assertFalse((self.root / "compass-history.json").exists())

    def test_missing_opt_in_or_receipt_does_not_upgrade_old_matching_sid(self) -> None:
        resolver = self.resolver()
        case = self.freeze(resolver)
        plain = marking.make_vouch(observations=(), ends=(), index={}, config=self.config)
        self.assertIn("reviewed-export-opt-in-required", plain(case))
        old = self.freeze()
        self.assertTrue(self.vouch(resolver)(old))
        self.assertIsNone(self.vouch(resolver).lifecycle(old))
        for key in ("manifest_sha256", "source_sha256", "prefix_sha256", "intake_code_sha256"):
            altered = copy.deepcopy(case)
            altered["reviewed_export"][key] = "0" * 64
            self.assertTrue(self.vouch(resolver)(altered), key)

    def test_native_source_callbacks_and_actual_score_use_same_explicit_resolver(self) -> None:
        resolver = self.resolver()
        case = self.freeze(resolver)
        seal = case["production_reading"]
        with mock.patch.object(
            marking, "_transcript_index", side_effect=AssertionError("no fallback")
        ):
            person = marking.native_case_person_lookup(
                case, config=self.config, reviewed_exports=resolver
            )
            final = marking.native_case_final_lookup(
                case, config=self.config, reviewed_exports=resolver
            )
            assert person is not None and final is not None
            self.assertTrue(person(seal["person_wanted"]))
            self.assertEqual("whole", final(seal["final_wanted"])["outcome"])
            called: list[Any] = []
            scoring.score_case(
                self.config,
                case,
                case["row_snapshot"],
                case["producer_facts"],
                {},
                model=self.model(called),
                now=case["captured_at"],
                revision=marking.case_revision(case),
                reviewed_exports=resolver,
            )
            self.assertEqual(1, len(called))
            self.assertEqual(seal["prompt_digest"], hashlib.sha256(called[0].encode()).hexdigest())

    def test_manifest_source_and_current_intake_code_recheck_at_last_precharge(self) -> None:
        resolver = self.resolver()
        case = self.freeze(resolver)
        called: list[Any] = []
        pinned = scoring._SourcePinnedModel(
            self.model(called),
            hashlib.sha256(b"prompt").hexdigest(),
            reviewed_exports=resolver,
            case=case,
            config=self.config,
        )
        for mutation in ("manifest", "source", "code"):
            with self.subTest(mutation=mutation):
                source = self.path.read_bytes()
                manifest = self.manifest.read_bytes()
                with (
                    mock.patch.object(marking, "intake_code_digest", return_value="0" * 64)
                    if mutation == "code"
                    else __import__("contextlib").nullcontext()
                ):
                    if mutation == "source":
                        future = {
                            "type": "system",
                            "timestamp": self.stamp(35),
                            "sessionId": self.sid,
                        }
                        self.path.write_bytes(source + (json.dumps(future) + "\n").encode())
                    if mutation == "manifest":
                        self.manifest.write_bytes(manifest + b" ")
                    with self.assertRaises(marking.FreezeError):
                        pinned("prompt")
                self.path.write_bytes(source)
                self.manifest.write_bytes(manifest)
        self.assertEqual([], called)

    def test_source_mutation_after_lookup_or_wrong_selected_ids_refuses(self) -> None:
        resolver = self.resolver()
        case = self.freeze(resolver)
        lookup = marking.native_case_final_lookup(
            case, config=self.config, reviewed_exports=resolver
        )
        assert lookup is not None
        wanted = case["production_reading"]["final_wanted"]
        self.assertEqual("whole", lookup(wanted)["outcome"])
        with self.assertRaises(marking.FreezeError):
            lookup([])
        self.path.write_text(self.path.read_text() + "\n")
        with self.assertRaises(marking.FreezeError):
            lookup(wanted)

    def test_closed_manifest_full_identity_path_and_size_refusals(self) -> None:
        for mutation in (
            "unknown",
            "review",
            "digest",
            "filename",
            "relative",
            "parent",
            "prefix-collision",
            "duplicate",
        ):
            with self.subTest(mutation=mutation):
                self.write_source()
                if mutation == "unknown":
                    self.receipt["unknown"] = True
                if mutation == "review":
                    self.receipt["review"]["approved"] = False
                if mutation == "digest":
                    self.receipt["exports"][0]["sha256"] = "0" * 64
                if mutation == "filename":
                    self.receipt["exports"][0]["sid"] = "87654321-1234-4234-8234-123456789abc"
                if mutation == "relative":
                    self.receipt["exports"][0]["path"] = self.path.name
                if mutation == "parent":
                    self.receipt["exports"][0]["path"] = str(
                        self.root / "child" / ".." / self.path.name
                    )
                if mutation in ("prefix-collision", "duplicate"):
                    another = copy.deepcopy(self.receipt["exports"][0])
                    if mutation == "prefix-collision":
                        another["sid"] = "12345678-4321-4321-8321-123456789abc"
                    self.receipt["exports"].append(another)
                self.write_manifest()
                with self.assertRaises(marking.FreezeError):
                    self.freeze(self.resolver())
        self.write_source()
        folder = self.root / "links"
        folder.mkdir()
        link = folder / self.path.name
        link.symlink_to(self.path)
        self.receipt["exports"][0]["path"] = str(link)
        self.write_manifest()
        with self.assertRaisesRegex(marking.FreezeError, "path-invalid"):
            self.resolver()

    def test_exact_stop_and_physical_parent_are_required(self) -> None:
        self.entry["row"]["finished_at"] += 0.0005
        with self.assertRaises(marking.FreezeError):
            self.freeze(self.resolver())
        self.entry["row"]["finished_at"] = self.start + 20
        self.rows[1]["parentUuid"] = "later-parent"
        self.rows.insert(
            2,
            {
                "type": "attachment",
                "uuid": "later-parent",
                "parentUuid": "person",
                "sessionId": self.sid,
                "timestamp": self.stamp(9),
            },
        )
        self.write_source()
        with self.assertRaises(marking.FreezeError):
            self.freeze(self.resolver())

    def test_physically_prior_attachment_clock_skew_is_admitted(self) -> None:
        self.rows.insert(
            1,
            {
                "type": "attachment",
                "uuid": "notice",
                "parentUuid": "person",
                "sessionId": self.sid,
                "timestamp": self.stamp(0.999),
            },
        )
        self.rows[2]["parentUuid"] = "notice"
        self.write_source()
        resolver = self.resolver()
        try:
            case = self.freeze(resolver)
        except marking.FreezeError as error:
            self.fail(f"physically earlier native attachment clock skew was refused: {error}")
        self.assertEqual("recorded", case["origin"])
        self.assertEqual([], self.vouch(resolver)(case))

    def test_stop_parent_and_person_need_native_text_events(self) -> None:
        original = copy.deepcopy(self.rows)
        for mutation in ("thinking", "synthetic", "injected-person"):
            with self.subTest(mutation=mutation):
                self.rows = copy.deepcopy(original)
                if mutation == "injected-person":
                    self.rows[0]["message"]["content"] = (
                        "<local-command-caveat>Injected only</local-command-caveat>"
                    )
                else:
                    earlier = self.record(
                        "assistant", 3, "Earlier final reply.", "earlier", "person"
                    )
                    self.rows.insert(1, earlier)
                    if mutation == "thinking":
                        self.rows[2]["message"]["content"] = [
                            {"type": "thinking", "thinking": "Internal only"}
                        ]
                    else:
                        self.rows[2]["message"]["model"] = "<synthetic>"
                self.write_source()
                with self.assertRaises(marking.FreezeError):
                    self.freeze(self.resolver())

    def test_bare_cr_between_native_json_records_refuses(self) -> None:
        source = self.path.read_bytes()
        marker = (json.dumps(self.rows[1]) + "\n").encode()
        changed = source.replace(marker, marker[:-1] + b"\r", 1)
        self.assertNotEqual(source, changed)
        self.path.write_bytes(changed)
        self.receipt["exports"][0]["sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.write_manifest()
        with self.assertRaises(marking.FreezeError):
            self.freeze(self.resolver())

    def test_native_person_eligibility_does_not_require_prompt_selection(self) -> None:
        self.entry["intent"]["at"] = self.start + 5
        self.entry["intent"]["window_start"] = self.start + 5
        resolver = self.resolver()
        case = self.freeze(resolver)
        self.assertEqual("recorded", case["origin"])
        self.assertEqual([], case["production_reading"]["person_wanted"])
        self.assertEqual([], self.vouch(resolver)(case))

    def test_literal_cr_inside_person_final_or_stop_record_refuses(self) -> None:
        original = self.path.read_bytes()
        for index in (0, 1, 2):
            with self.subTest(record=index):
                line = (json.dumps(self.rows[index]) + "\n").encode()
                changed = line.replace(b",", b",\r", 1)
                self.assertEqual(self.rows[index], json.loads(changed))
                mutated = original.replace(line, changed, 1)
                self.assertNotEqual(original, mutated)
                self.path.write_bytes(mutated)
                self.receipt["exports"][0]["sha256"] = hashlib.sha256(
                    self.path.read_bytes()
                ).hexdigest()
                self.write_manifest()
                with self.assertRaisesRegex(marking.FreezeError, "record-invalid"):
                    self.freeze(self.resolver())

    def test_crlf_terminators_and_escaped_json_carriage_return_are_admitted(self) -> None:
        self.rows[0]["message"]["content"][0]["text"] = "Keep\rkeyboard focus."
        self.write_source()
        original = self.path.read_bytes()
        self.assertNotIn(b"\r\n", original)
        changed = original.replace(b"\n", b"\r\n")
        self.assertNotEqual(original, changed)
        self.path.write_bytes(changed)
        self.receipt["exports"][0]["sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.write_manifest()
        resolver = self.resolver()
        case = self.freeze(resolver)
        self.assertEqual("recorded", case["origin"])
        self.assertEqual([], self.vouch(resolver)(case))

    def test_nonlinear_ancestry_and_physical_future_cut_are_preserved(self) -> None:
        unrelated = self.record("assistant", 5, "Another branch", "branch", "person")
        self.rows.insert(1, unrelated)
        self.rows.append(self.record("user", 35, "Future", "future", "final"))
        self.rows.append(self.record("user", 25, "Backdated later write", "backdated", "final"))
        self.write_source()
        resolver = self.resolver()
        case = self.freeze(resolver)
        self.assertEqual([], self.vouch(resolver)(case))
        self.assertNotIn("Backdated", json.dumps(case))

    def test_native_person_blocks_require_nonempty_string_text(self) -> None:
        for text in (7, " \t\n "):
            with self.subTest(text=text):
                self.rows[0]["message"]["content"] = [{"type": "text", "text": text}]
                self.write_source()
                with self.assertRaises(marking.FreezeError):
                    self.freeze(self.resolver())

    def test_actual_prompt_pipeline_race_refuses_before_delegate(self) -> None:
        resolver = self.resolver()
        case = self.freeze(resolver)
        reading = marking._reading()
        original = reading.build_prompt
        original_lookup = marking.native_case_final_lookup
        callback_completed = False
        called: list[Any] = []
        ledger = mock.Mock(campaign=None)
        charged = scoring._Charged(ledger, case["id"], self.model(called))

        def lookup(*args: Any, **kwargs: Any) -> Any:
            actual = original_lookup(*args, **kwargs)
            assert actual is not None

            def final(rows: Any) -> Any:
                nonlocal callback_completed
                result = actual(rows)
                callback_completed = True
                return result

            return final

        def raced(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            if callback_completed:
                self.manifest.write_bytes(self.manifest.read_bytes() + b" ")
            return result

        with (
            mock.patch.object(reading, "build_prompt", side_effect=raced),
            mock.patch.object(marking, "native_case_final_lookup", side_effect=lookup),
        ):
            scoring.score_case(
                self.config,
                case,
                case["row_snapshot"],
                case["producer_facts"],
                {},
                model=charged,
                now=case["captured_at"],
                revision=marking.case_revision(case),
                reviewed_exports=resolver,
            )
        self.assertEqual([], called)
        self.assertTrue(callback_completed)
        ledger.charge.assert_not_called()

    def test_native_stop_final_parent_continuation_and_settle_refusals(self) -> None:  # noqa: C901, PLR0912 - explicit independent shape mutations
        original = copy.deepcopy(self.rows)
        for mutation in (
            "label",
            "prevented",
            "sidechain",
            "meta",
            "role",
            "end_turn",
            "parent",
            "orphan",
            "uuid-reuse",
            "continuation",
            "tool-continuation",
            "meta-continuation",
            "wrong-sid",
            "unsettled",
        ):
            with self.subTest(mutation=mutation):
                self.rows = copy.deepcopy(original)
                self.entry["captured_at"] = self.start + 30
                if mutation == "label":
                    self.rows[2]["hookLabel"] = "PreToolUse"
                if mutation == "prevented":
                    self.rows[2]["preventedContinuation"] = True
                if mutation == "sidechain":
                    self.rows[1]["isSidechain"] = True
                if mutation == "meta":
                    self.rows[1]["isMeta"] = True
                if mutation == "role":
                    self.rows[1]["message"]["role"] = "user"
                if mutation == "end_turn":
                    self.rows[1]["message"]["stop_reason"] = "tool_use"
                if mutation == "parent":
                    self.rows[2]["parentUuid"] = "person"
                if mutation == "orphan":
                    self.rows[1]["parentUuid"] = None
                if mutation == "uuid-reuse":
                    self.rows.insert(1, copy.deepcopy(self.rows[0]))
                if mutation in ("continuation", "tool-continuation", "meta-continuation"):
                    later = self.record("user", 25, "Continue", "later", "final")
                    if mutation == "tool-continuation":
                        later["message"]["content"] = [
                            {"type": "tool_result", "tool_use_id": "x", "content": "ok"}
                        ]
                    if mutation == "meta-continuation":
                        later["isMeta"] = True
                    self.rows.append(later)
                if mutation == "wrong-sid":
                    self.rows[0]["sessionId"] = self.sid[:-1] + "d"
                if mutation == "unsettled":
                    self.entry["captured_at"] = self.start + 21
                self.write_source()
                with self.assertRaises(marking.FreezeError):
                    self.freeze(self.resolver())

    def test_exact_case_and_prompt_tampering_never_reaches_delegate(self) -> None:
        resolver = self.resolver()
        original = self.freeze(resolver)
        for mutation in ("goal", "capture", "snapshot", "facts", "prompt"):
            case = copy.deepcopy(original)
            if mutation == "goal":
                case["intent"]["goal"] = "Other goal"
            if mutation == "capture":
                case["captured_at"] += 1
            if mutation == "snapshot":
                case["row_snapshot"]["finished_at"] += 1
            if mutation == "facts":
                case["producer_facts"][0]["summary"] = "Other content"
            if mutation == "prompt":
                case["production_reading"]["prompt_digest"] = "0" * 64
            called: list[Any] = []
            scoring.score_case(
                self.config,
                case,
                case["row_snapshot"],
                case["producer_facts"],
                {},
                model=self.model(called),
                now=case["captured_at"],
                revision=marking.case_revision(case),
                reviewed_exports=resolver,
            )
            self.assertEqual([], called, mutation)

    def test_freeze_cli_export_route_does_not_contact_board_or_history(self) -> None:
        resolver = self.resolver()
        spec = self.root / "spec.json"
        spec.write_text(json.dumps({"cases": [self.entry]}))
        with (
            mock.patch.object(marking, "CASES_PATH", str(self.root / "cases.json")),
            mock.patch.object(marking, "MARKS_PATH", str(self.root / "marks.json")),
            mock.patch.object(marking, "_runtime_config", return_value=self.config),
            mock.patch.object(
                marking, "_session_facts", side_effect=AssertionError("board forbidden")
            ),
            mock.patch.object(
                marking, "_observed_stores", side_effect=AssertionError("history forbidden")
            ),
        ):
            self.assertEqual(
                0,
                marking.main(
                    [
                        "--freeze",
                        str(spec),
                        "--production-reading",
                        "--reviewed-exports",
                        str(self.manifest),
                        "--reviewed-exports-sha256",
                        resolver.digest,
                    ]
                ),
            )
            self.assertEqual(
                "recorded", json.loads((self.root / "cases.json").read_text())["cases"][0]["origin"]
            )

    def test_actual_both_cli_parsers_thread_explicit_context_and_report_vouch(self) -> None:
        args = ["--reviewed-exports", str(self.manifest), "--reviewed-exports-sha256", self.digest]
        with (
            mock.patch.object(marking, "freeze", return_value=0) as freeze,
            contextlib.redirect_stderr(__import__("io").StringIO()),
        ):
            try:
                status = marking.main(["--freeze", "spec.json", "--production-reading", *args])
            except SystemExit as error:
                status = error.code if isinstance(error.code, int) else 2
            self.assertEqual(0, status)
            self.assertEqual(self.digest, freeze.call_args.kwargs["reviewed_exports"].digest)
        corpus = mock.Mock()
        corpus.cases = {"v": 5, "cases": [{"id": "fixture"}]}
        with (
            mock.patch.object(scoring, "_load_corpus", return_value=corpus),
            mock.patch.object(marking, "print_packet"),
            mock.patch.object(marking, "machine_vouch", return_value="explicit-vouch") as vouch,
            mock.patch.object(scoring, "report", return_value=0) as report,
            contextlib.redirect_stderr(__import__("io").StringIO()),
        ):
            try:
                status = scoring.main(["--report", *args])
            except SystemExit as error:
                status = error.code if isinstance(error.code, int) else 2
            self.assertEqual(0, status)
            self.assertEqual(self.digest, vouch.call_args.kwargs["reviewed_exports"].digest)
            self.assertEqual("explicit-vouch", report.call_args.kwargs["vouch"])
        from compass_runtime import reading_route  # noqa: PLC0415 - local stub CLI path

        verified = mock.MagicMock()
        verified.path = str(self.root / "never-launched-claude")
        verified.identity = (0, 0, 0, 0, "a" * 64)
        verified.__enter__.return_value = verified
        with (
            mock.patch.object(scoring, "_load_corpus", return_value=corpus),
            mock.patch.object(marking, "print_packet"),
            mock.patch.object(marking, "machine_vouch", return_value="explicit-vouch"),
            mock.patch.object(scoring, "verify_claude_binary", return_value=verified),
            mock.patch.object(reading_route, "destination", return_value="Anthropic"),
            mock.patch.object(marking._reading(), "ClaudeReadingModel", return_value="stub-model"),
            mock.patch.object(scoring, "score", return_value=0) as score,
        ):
            self.assertEqual(0, scoring.main(["--score", "--producer", "claude", *args]))
            self.assertEqual(self.digest, score.call_args.kwargs["reviewed_exports"].digest)
            self.assertEqual("stub-model", score.call_args.kwargs["model"])
            self.assertEqual("explicit-vouch", score.call_args.kwargs["vouch"])

    def test_unpaired_cli_flags_refuse_before_source_load_or_execution(self) -> None:
        for cli in (marking.main, scoring.main):
            for args in (
                ["--reviewed-exports", str(self.manifest)],
                ["--reviewed-exports-sha256", self.digest],
            ):
                with (
                    mock.patch.object(
                        marking, "ReviewedExports", side_effect=AssertionError("load")
                    ),
                    mock.patch.object(marking, "freeze", side_effect=AssertionError("freeze")),
                    mock.patch.object(
                        scoring, "verify_claude_binary", side_effect=AssertionError("CLI")
                    ),
                    contextlib.redirect_stdout(__import__("io").StringIO()),
                ):
                    self.assertEqual(2, cli(args))

    def test_export_cli_identity_shapes_refuse_before_any_fallback(self) -> None:
        bad_sids: tuple[Any, ...] = (self.sid, [], {}, "not-eight-hex")
        for sid in bad_sids:
            with self.subTest(sid=sid):
                entry = copy.deepcopy(self.entry)
                entry["sid"] = sid
                spec = self.root / "bad-identity.json"
                canonical = copy.deepcopy(self.entry)
                canonical["sid"] = "87654321"
                spec.write_text(json.dumps({"cases": [canonical, entry]}))
                with (
                    mock.patch.object(marking, "CASES_PATH", str(self.root / "cases.json")),
                    mock.patch.object(marking, "MARKS_PATH", str(self.root / "marks.json")),
                    mock.patch.object(marking, "_runtime_config", return_value=self.config),
                    mock.patch.object(
                        marking, "_observed_stores", return_value=((), ())
                    ) as history,
                    mock.patch.object(marking, "_transcript_index", return_value={}) as index,
                    mock.patch.object(marking, "_session_facts", return_value=[]) as board,
                    contextlib.redirect_stdout(__import__("io").StringIO()),
                ):
                    try:
                        status = marking.main(
                            [
                                "--freeze",
                                str(spec),
                                "--production-reading",
                                "--reviewed-exports",
                                str(self.manifest),
                                "--reviewed-exports-sha256",
                                self.digest,
                            ]
                        )
                    except (TypeError, marking.FreezeError) as error:
                        self.fail(
                            f"CLI identity refusal escaped instead of a nonzero result: {error}"
                        )
                    self.assertNotEqual(0, status)
                    history.assert_not_called()
                    board.assert_not_called()
                    index.assert_not_called()
                    self.assertFalse((self.root / "cases.json").exists())

    def test_actual_report_and_default_vouch_need_no_canonical_index_for_exports(self) -> None:
        resolver = self.resolver()
        case = self.freeze(resolver)
        corpus = scoring.Corpus({"v": 5, "cases": [case]}, {}, b"{}", {"cases": []})
        with (
            mock.patch.object(scoring, "_load_corpus", return_value=corpus),
            mock.patch.object(marking, "_runtime_config", return_value=self.config),
            mock.patch.object(marking, "_observed_stores", side_effect=AssertionError("history")),
            mock.patch.object(marking, "_transcript_index", side_effect=AssertionError("index")),
            mock.patch.object(marking, "print_packet"),
            contextlib.redirect_stdout(__import__("io").StringIO()),
        ):
            vouch = scoring._default_vouch(None, {"producer": "claude"}, resolver)
            assert vouch is not None
            self.assertEqual([], vouch(case))
            self.assertEqual(
                0,
                scoring.main(
                    [
                        "--report",
                        "--reviewed-exports",
                        str(self.manifest),
                        "--reviewed-exports-sha256",
                        self.digest,
                        "--out",
                        str(self.root / "summary.json"),
                    ]
                ),
            )

    def test_missing_opt_in_actual_scoring_is_zero_delegate_and_demoted(self) -> None:
        resolver = self.resolver()
        case = self.freeze(resolver)
        called: list[Any] = []
        scoring.score_case(
            self.config,
            case,
            case["row_snapshot"],
            case["producer_facts"],
            {},
            model=self.model(called),
            now=case["captured_at"],
            revision=marking.case_revision(case),
        )
        self.assertEqual([], called)
        self.assertEqual("synthetic", scoring._vouched(case, self.vouch(None))["origin"])
        old = self.freeze()
        self.assertEqual("synthetic", scoring._vouched(old, self.vouch(resolver))["origin"])

    def test_component_bounds_and_descriptor_race_are_actual_refusals(self) -> None:
        self.resolver()
        original = self.path.read_bytes()
        self.path.write_bytes(original + b" " * (32 * 1024 * 1024))
        self.receipt["exports"][0]["sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.write_manifest()
        with self.assertRaisesRegex(marking.FreezeError, "size-or-type-invalid"):
            self.resolver()
        self.path.write_bytes(original)
        self.rows[0]["message"]["content"][0]["text"] = "x" * (1024 * 1024)
        self.write_source()
        with self.assertRaisesRegex(marking.FreezeError, "record-too-large"):
            self.freeze(self.resolver())
        self.rows[0]["message"]["content"][0]["text"] = "Keep keyboard focus."
        self.write_source()
        actual_stat = os.stat

        class Moved:
            st_dev = self.path.stat().st_dev
            st_ino = self.path.stat().st_ino + 1
            st_size = self.path.stat().st_size
            st_mtime_ns = self.path.stat().st_mtime_ns

        def raced(path: Any, *args: Any, **kwargs: Any) -> Any:
            if str(path) == str(self.path) and kwargs.get("follow_symlinks") is False:
                return Moved()
            return actual_stat(path, *args, **kwargs)

        with (
            mock.patch.object(os, "stat", side_effect=raced),
            self.assertRaises(marking.FreezeError),
        ):
            self.resolver()

    @unittest.skipIf(os.name == "nt", "Windows holds an opened file against atomic replacement")
    def test_actual_source_replacement_during_read_is_refused(self) -> None:
        original_open = os.fdopen
        replaced = False

        @contextlib.contextmanager
        def raced(descriptor: int, mode: str) -> Any:
            nonlocal replaced
            with original_open(descriptor, mode) as handle:
                proxy = mock.Mock(wraps=handle)

                def read(size: int) -> bytes:
                    nonlocal replaced
                    result: bytes = handle.read(size)
                    if not replaced and os.fstat(descriptor).st_ino == self.path.stat().st_ino:
                        replacement = self.root / "replacement"
                        replacement.write_bytes(self.path.read_bytes())
                        replacement.replace(self.path)
                        replaced = True
                    return result

                proxy.read.side_effect = read
                yield proxy

        with (
            mock.patch.object(os, "fdopen", side_effect=raced),
            self.assertRaisesRegex(marking.FreezeError, "source-moved"),
        ):
            self.resolver()
        self.assertTrue(replaced)

    def test_actual_source_replacement_after_close_before_path_stat_is_refused(self) -> None:
        actual_stat = os.stat
        before = self.path.stat()
        replaced = False
        moved_inode: int | None = None

        def raced(path: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal replaced, moved_inode
            if (
                str(path) == str(self.path)
                and kwargs.get("follow_symlinks") is False
                and not replaced
            ):
                replacement = self.root / "replacement-after-close"
                replacement.write_bytes(self.path.read_bytes())
                replacement.replace(self.path)
                replaced = True
                moved_inode = actual_stat(path).st_ino
            return actual_stat(path, *args, **kwargs)

        with (
            mock.patch.object(os, "stat", side_effect=raced),
            self.assertRaisesRegex(marking.FreezeError, "source-moved"),
        ):
            self.resolver()
        self.assertTrue(replaced)
        self.assertNotEqual(before.st_ino, moved_inode)

    def test_default_vouch_threads_trusted_context_without_relabeling_existing_case(self) -> None:
        resolver = self.resolver()
        with mock.patch.object(marking, "machine_vouch", return_value="vouch") as native:
            self.assertEqual(
                "vouch", scoring._default_vouch(None, {"producer": "claude"}, resolver)
            )
            self.assertIs(resolver, native.call_args.kwargs["reviewed_exports"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_nonregular_source_refuses_without_blocking_on_open(self) -> None:
        self.path.unlink()
        os.mkfifo(self.path)
        program = (
            "import sys;sys.path.insert(0,sys.argv[1]);import mark_abstention as m\n"
            "try: m.ReviewedExports(sys.argv[2],sys.argv[3])\n"
            "except m.FreezeError: print('refused')\n"
        )
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    program,
                    str(Path(marking.__file__).parent),
                    str(self.manifest),
                    self.digest,
                ],
                capture_output=True,
                text=True,
                timeout=WAIT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("nonregular source blocked before the regular-file check")
        self.assertEqual("refused", result.stdout.strip())
