"""A person qualifies Codex with fake transports and capture-shaped temporary sources only."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import abstention_ledger as authority
import analyze_campaign as campaign
import codex_case_sources as sources
import mark_abstention as marker
import score_abstention as scorer

if TYPE_CHECKING:
    from tests.codex_source_support import AT, config, entry, rollout
else:
    from codex_source_support import AT, config, entry, rollout


class _CodexInstallationFixture(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        self.package = self.home / "node_modules/@openai/codex"
        self.launcher = self.package / "bin/codex.js"
        self.native = self.package / "vendor/x86_64-unknown-linux-musl/codex/codex"
        self.launcher.parent.mkdir(parents=True)
        self.native.parent.mkdir(parents=True)
        self.launcher.write_text("#!/usr/bin/env node\n// @openai/codex launcher\n")
        self.native.write_bytes(b"\x7fELF" + b"FAKE TEST EXECUTABLE; NEVER EXECUTE")
        self.native.chmod(0o700)
        (self.package / "package.json").write_text(
            json.dumps(
                {"name": "@openai/codex", "version": "0.167.0", "bin": {"codex": "bin/codex.js"}}
            )
        )
        self.version_runner = mock.Mock(
            return_value=mock.Mock(returncode=0, stdout="codex-cli 0.167.0\n")
        )

    def verify(self) -> Any:
        return scorer.verify_codex_binary(
            binary_resolver=lambda _: str(self.launcher),
            runner=self.version_runner,
            platform="linux",
            machine="x86_64",
        )

    def platform_package(self) -> Path:
        """Published @openai/codex 0.167.0 platform-alias metadata, with fake bytes."""
        platform_package = self.package.parent / "codex-linux-x64"
        native = platform_package / "vendor/x86_64-unknown-linux-musl/bin/codex"
        native.parent.mkdir(parents=True)
        self.native.rename(native)
        self.native = native
        (platform_package / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openai/codex",
                    "version": "0.167.0-linux-x64",
                    "os": ["linux"],
                    "cpu": ["x64"],
                }
            )
        )
        manifest = json.loads((self.package / "package.json").read_text())
        manifest["optionalDependencies"] = {
            "@openai/codex-linux-x64": "npm:@openai/codex@0.167.0-linux-x64"
        }
        (self.package / "package.json").write_text(json.dumps(manifest))
        return platform_package / "package.json"


class CodexInstallationTest(_CodexInstallationFixture):
    def test_a_person_records_the_installation_and_native_bytes_separately(self) -> None:
        verified = self.verify()
        self.assertEqual(str(self.native), verified.path)
        self.assertEqual(scorer.file_identity(str(self.native)), verified.identity)
        self.assertEqual("codex-cli 0.167.0", verified.version)
        self.version_runner.assert_called_once()
        self.assertEqual([str(self.native), "--version"], self.version_runner.call_args.args[0])
        self.assertNotEqual(verified.installation_digest, verified.identity[-1])

    def test_a_person_cannot_trust_a_version_string_from_an_unrecognized_installation(self) -> None:
        fake = self.home / "codex"
        fake.write_text("#!/bin/sh\necho codex-cli 0.167.0\n")
        fake.chmod(0o700)
        with self.assertRaises(scorer.BinaryError):
            scorer.verify_codex_binary(
                binary_resolver=lambda _: str(fake), runner=self.version_runner
            )
        self.version_runner.assert_not_called()

    def test_a_person_cannot_launch_after_the_native_binary_or_installation_changes(self) -> None:
        verified = self.verify()
        pinned = scorer.PinnedCodex(verified)
        self.assertEqual(str(self.native), pinned("codex"))
        for path in (self.native, self.launcher, self.package / "package.json"):
            with self.subTest(path=path.name):
                before = path.read_bytes()
                path.write_bytes(before + b" ")
                with self.assertRaises(scorer.BinaryError):
                    pinned("codex")
                path.write_bytes(before)
                verified = self.verify()
                pinned = scorer.PinnedCodex(verified)

    def test_a_person_cannot_treat_a_script_or_wrong_version_as_the_native_cli(self) -> None:
        self.native.write_text("#!/bin/sh\nexit 0\n")
        with self.assertRaises(scorer.BinaryError):
            self.verify()
        self.version_runner.assert_not_called()

    def test_a_person_can_pin_the_current_platform_package_layout(self) -> None:
        self.platform_package()
        self.assertEqual(str(self.native), self.verify().path)

    def test_a_person_cannot_accept_a_native_version_that_differs_from_the_package(self) -> None:
        self.version_runner.return_value.stdout = "codex-cli 0.168.0"
        with self.assertRaises(scorer.BinaryError):
            self.verify()

    def test_a_person_refuses_malformed_package_metadata_before_running_version(self) -> None:
        path = self.package / "package.json"
        manifest = json.loads(path.read_text())
        bad_bins: tuple[Any, ...] = (None, [], "bin/codex.js")
        for value in bad_bins:
            with self.subTest(bin=value):
                manifest["bin"] = value
                path.write_text(json.dumps(manifest))
                with self.assertRaises(scorer.BinaryError):
                    self.verify()
        self.version_runner.assert_not_called()

    def test_a_person_refuses_a_platform_alias_with_changed_identity_version_or_target(
        self,
    ) -> None:
        path = self.platform_package()
        original = json.loads(path.read_text())
        root_path = self.package / "package.json"
        root_manifest = json.loads(root_path.read_text())
        for field, value in (
            ("name", "other"),
            ("version", "0.168.0-linux-x64"),
            ("os", ["darwin"]),
            ("cpu", ["arm64"]),
        ):
            with self.subTest(field=field):
                path.write_text(json.dumps({**original, field: value}))
                with self.assertRaises(scorer.BinaryError):
                    self.verify()
        path.write_text(json.dumps(original))
        root_manifest["optionalDependencies"]["@openai/codex-linux-x64"] = (
            "npm:@openai/codex@0.168.0-linux-x64"
        )
        root_path.write_text(json.dumps(root_manifest))
        with self.assertRaises(scorer.BinaryError):
            self.verify()
        self.version_runner.assert_not_called()


@unittest.skipIf(sys.platform == "win32", "Codex account authority refuses Windows")
class CodexQualificationTest(_CodexInstallationFixture):
    parser: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.parser = sources.parser_digest()

    def setUp(self) -> None:
        super().setUp()
        self.config = config(self.home)
        parser_patch = mock.patch.object(sources, "parser_digest", return_value=self.parser)
        parser_patch.start()
        self.addCleanup(parser_patch.stop)
        for patch in (
            mock.patch.object(authority, "real_home", return_value=str(self.home)),
            mock.patch.object(authority, "CODEX_GRANT_PATH", str(self.home / "grant.json")),
            mock.patch.object(scorer, "HOME", str(self.home / "packet")),
            mock.patch.dict(
                os.environ,
                {
                    "HOME": str(self.home),
                    "CODEX_HOME": str(self.home / "codex"),
                    "COMPASS_HOME": str(self.home / "packet"),
                },
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.verified = self.verify()
        self.transport = scorer.codex_transport(self.config, self.verified)
        cases = []
        reviews = {}
        for n, kind in enumerate((*scorer.KINDS, *scorer.PASSING_CHECK_ADVERSARIES)):
            sid = f"00000000-0000-4000-8000-{n + 1:012d}"
            root = self.home / "codex/sessions"
            path = rollout(root, sid=sid)
            spec = entry(root, path)
            spec["sid"] = sid
            case = sources.freeze_case(self.config, spec)
            cases.append(case)
            reviews[case["id"]] = {
                "kind": kind,
                "case_digest": authority.digest(case),
                "markers": ["marker-a", "marker-b"],
                "reviewed_by": "kind-reviewer",
                "review_receipt": authority.digest([kind, case["id"]]),
                "spontaneous": kind == scorer.KIND_SUPPORTED_DEPARTURE,
                "authored_by": "author",
                "verified_by": "independent-verifier",
            }
        body = {"v": marker.FORMAT_CODEX, "cases": cases, "codex_kind_reviews": reviews}
        marks: dict[str, Any] = {
            "cases_digest": marker.cases_digest(body),
            "marks": {
                c["id"]: dict.fromkeys(c["production_reading"]["constraints"], "abstain")
                for c in cases
            },
        }
        rubric = {
            "v": 1,
            "cases": {
                c["id"]: {
                    "kind": scorer.KIND_LEGITIMATE_CHANGE,
                    "origin": "recorded",
                    "harness": "codex",
                    "expect": {
                        key: {"result": "unverifiable", "cites": []}
                        for key in marks["marks"][c["id"]]
                    },
                }
                for n, c in enumerate(cases)
            },
        }
        self.corpus = scorer.Corpus(body, marks, json.dumps(marks).encode(), rubric)
        self.requests = scorer.prepare_codex_requests(self.corpus, self.config, self.transport)
        self.inputs = scorer.codex_bindings(self.corpus)
        self.grant = {
            "v": 1,
            "study": "codex-qualification",
            "phase": "prepared",
            "producer": "codex",
            "bindings": self.inputs,
            "transport": authority.digest(self.transport),
            "allowance": 31,
            "retry_limit": 1,
            "exposures": [
                {key: r[key] for key in ("slot", "case", "repetition", "request_digest")}
                for r in self.requests
            ],
            "activation_anchor": "",
            "genesis_review": "",
        }
        self.grant_path = self.home / "grant.json"
        self.write_grant()
        anchor = self.study().initialize()
        self.grant.update(phase="sealed", activation_anchor=anchor, genesis_review="d" * 64)
        self.write_grant()
        self.results = str(self.home / "packet/abstention-codex-results.json")
        self.summary = str(self.home / "codex-results.json")
        self.launches: list[dict[str, Any]] = []
        self.status = "ok"
        self.interrupt = False
        self.semantic = False
        self.before_launch: Any = None
        self.binding = scorer.codex_result_binding(self.transport, self.verified)

    def write_grant(self) -> None:
        self.grant_path.write_text(json.dumps(self.grant))

    def study(self) -> Any:
        return campaign.CodexCampaign(bindings=self.inputs, transport=self.transport)

    def fake_runner(self, argv: list[str], **kwargs: Any) -> Any:
        if self.before_launch:
            self.before_launch()
        calls = self.study()._state()[2]
        self.assertEqual("charged", calls[-1]["status"])
        self.launches.append({"argv": argv, "prompt": kwargs["input"], "charge": calls[-1]["id"]})
        self.assertEqual(argv, self.transport["argv"])
        if self.interrupt:
            raise KeyboardInterrupt
        names = self.corpus.cases["cases"][0]["production_reading"]["constraints"]
        answer = {
            key: {
                "result": "consistent" if self.semantic and key == "line_1" else "unverifiable",
                "cites": [2] if self.semantic and key == "line_1" else [],
                "detail": "Synthetic reply",
            }
            for key in names
        }
        Path(argv[argv.index("--output-last-message") + 1]).write_text(json.dumps(answer))
        return mock.Mock(returncode=0 if self.status == "ok" else 1)

    def run_one(self, *, approve: bool = True, resume: bool = False) -> int:
        prior = json.loads(Path(self.results).read_text()) if resume else None
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            return scorer.score(
                1,
                self.corpus,
                config=self.config,
                model=scorer.codex_model(
                    self.config, self.verified, self.transport, runner=self.fake_runner
                ),
                results_path=self.results,
                summary_path=self.summary,
                now=AT + 30,
                binding=self.binding,
                tool_destination="OpenAI",
                codex_transport=self.transport,
                codex_approve=(lambda _report: approve),
                resume=prior,
            )

    def test_a_person_prepares_thirty_registered_exposures_without_launching(self) -> None:
        self.assertEqual(30, len(self.requests))
        self.assertEqual(30, len({r["slot"] for r in self.requests}))
        self.assertEqual({1, 2, 3}, {r["repetition"] for r in self.requests})
        self.assertEqual([], self.launches)
        self.assertEqual(0, self.study().used())

    def test_a_person_without_one_approval_launches_nothing(self) -> None:
        self.assertEqual(2, self.run_one(approve=False))
        self.assertEqual([], self.launches)
        self.assertEqual(0, self.study().used())
        for word in (
            "case",
            "repetition",
            "request_digest",
            "effort",
            "CLI",
            "evidence",
            "remaining",
        ):
            self.assertIn(word, self.output.getvalue())

    def test_a_person_runs_one_exact_source_prompt_and_checkpoints_before_returning(self) -> None:
        self.assertEqual(2, self.run_one())
        self.assertEqual(1, len(self.launches))
        self.assertEqual(self.requests[0]["prompt"], self.launches[0]["prompt"])
        result = json.loads(Path(self.results).read_text())
        self.assertEqual(1, len(result["records"]["attempts"]))
        self.assertEqual("usable", result["records"]["attempts"][0]["classification"])
        self.assertEqual("blocked", json.loads(Path(self.summary).read_text())["verdict"])

    def test_a_person_needs_three_complete_passing_repetitions(self) -> None:
        for n in range(30):
            code = self.run_one(resume=n > 0)
            self.assertEqual(0 if n == 29 else 2, code, self.output.getvalue())
            self.assertEqual(n + 1, len(self.launches))
            if n in (9, 19):
                self.study().review_batch(n // 10 + 1, authority.digest([n, "review"]))
        summary = json.loads(Path(self.summary).read_text())
        self.assertEqual("passed", summary["verdict"])
        self.assertEqual(["passed"] * 3, [r["summary"]["verdict"] for r in summary["repetitions"]])
        self.assertEqual(30, self.study().used())
        self.assertEqual(0, self.run_one(resume=True))
        self.assertEqual(30, len(self.launches))

    def test_a_person_sees_one_charged_retry_and_never_an_automatic_retry(self) -> None:
        self.status = "failed"
        self.assertEqual(2, self.run_one())
        self.assertEqual(1, len(self.launches))
        self.assertEqual(2, self.run_one(approve=False, resume=True))
        self.assertEqual(1, len(self.launches))
        self.status = "ok"
        self.run_one(resume=True)
        attempts = json.loads(Path(self.results).read_text())["records"]["attempts"]
        self.assertEqual([False, True], [a["retry"] for a in attempts])
        self.assertEqual(["unusable", "usable"], [a["classification"] for a in attempts])
        self.assertEqual(2, self.study().used())

    def test_a_person_cannot_retry_a_semantic_failure(self) -> None:
        self.semantic = True
        self.assertEqual(1, self.run_one())
        self.assertEqual(1, len(self.launches))
        self.assertEqual("semantic-failed", self.study()._state()[2][0]["status"])
        self.semantic = False
        self.run_one(resume=True)
        self.assertEqual(2, len(self.launches))
        calls = self.study()._state()[2]
        self.assertNotEqual(calls[0]["slot"], calls[1]["slot"])
        self.assertFalse(calls[1]["retry"])

    def test_a_person_cannot_resume_an_interrupted_launch_as_an_unused_slot(self) -> None:
        self.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.run_one()
        self.assertEqual(1, self.study().used())
        self.assertTrue(
            Path(self.results).is_file(), "the charged launch needs a durable pending checkpoint"
        )
        self.interrupt = False
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(1, len(self.launches))
        self.assertIn("charged", Path(self.results).read_text())

    def test_a_person_cannot_rewrite_earlier_results_or_start_over(self) -> None:
        self.run_one()
        before = Path(self.results).read_bytes()
        self.assertEqual(2, self.run_one())
        self.assertEqual(before, Path(self.results).read_bytes())
        body = json.loads(before)
        body["records"]["attempts"][0]["classification"] = "semantic-failed"
        Path(self.results).write_text(json.dumps(body))
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(1, len(self.launches))

    def test_a_person_cannot_launch_when_the_cli_changes_after_approval(self) -> None:
        def swap(_report: Any, _approve: Any) -> bool:
            self.native.write_bytes(self.native.read_bytes() + b"changed")
            return True

        with mock.patch.object(scorer, "_codex_owner_approval", side_effect=swap):
            self.run_one()
        self.assertEqual([], self.launches)

    def test_a_person_cannot_fill_recorded_coverage_from_rubric_labels(self) -> None:
        case = self.corpus.cases["cases"][0]
        self.corpus.cases["codex_kind_reviews"][case["id"]]["spontaneous"] = False
        cast("dict[str, Any]", self.corpus.marks)["cases_digest"] = marker.cases_digest(
            dict(self.corpus.cases)
        )
        with self.assertRaises(marker.FreezeError):
            scorer.prepare_codex_requests(self.corpus, self.config, self.transport)
        self.assertEqual([], self.launches)

    def test_a_person_cannot_send_a_changed_prompt_or_skip_a_batch_review(self) -> None:
        case = self.corpus.cases["cases"][0]
        original = case["production_reading"]["prompt_digest"]
        case["production_reading"]["prompt_digest"] = "0" * 64
        self.assertEqual(2, self.run_one())
        self.assertEqual([], self.launches)
        case["production_reading"]["prompt_digest"] = original
        for n in range(10):
            self.run_one(resume=n > 0)
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(10, len(self.launches))

    def test_a_person_cannot_reuse_an_approval_without_consuming_a_new_receipt(self) -> None:
        study = self.study()
        request = self.requests[0]
        charged = scorer._Charged(
            study,
            request["case"],
            scorer.codex_model(self.config, self.verified, self.transport, runner=self.fake_runner),
            binding=self.binding,
            codex_transport=self.transport,
        )
        with self.assertRaises(authority.LedgerError):
            charged(request["prompt"], output_cap_bytes=request["output_cap_bytes"])
        self.assertEqual([], self.launches)
        self.assertEqual(0, study.used())

    def test_a_person_cannot_bypass_the_exact_prompt_seal_before_charge(self) -> None:
        launch = mock.Mock(return_value=("{}", "ok"))
        sealed = scorer._SourcePinnedModel(launch, "0" * 64)
        with self.assertRaises(marker.FreezeError):
            sealed("changed synthetic prompt", output_cap_bytes=1)
        launch.assert_not_called()

    def test_a_person_cannot_swap_the_cli_between_approval_and_the_runner(self) -> None:
        link = os.link

        def swap(*args: Any, **kwargs: Any) -> None:
            link(*args, **kwargs)
            self.native.write_bytes(self.native.read_bytes() + b"changed at launch")

        with mock.patch("score_abstention.os.link", side_effect=swap):
            self.assertEqual(2, self.run_one())
        self.assertEqual([], self.launches)
        self.assertEqual(1, self.study().used())

    def test_a_person_cannot_redirect_an_immutable_attempt_receipt(self) -> None:
        self.run_one()
        call = self.study()._state()[2][0]
        receipt = Path(self.study().path + ".results") / (call["id"] + ".json")
        copied = self.home / "copied-result.json"
        copied.write_bytes(receipt.read_bytes())
        receipt.unlink()
        receipt.symlink_to(copied)
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(1, len(self.launches))

    def test_a_person_cannot_overwrite_a_historical_result_with_codex_output(self) -> None:
        protected = self.home / "prior-claude-results.json"
        protected.write_text("earlier result stays fixed")
        self.run_one()
        self.summary = str(protected)
        with mock.patch.object(scorer, "CLAUDE_SUMMARY_PATH", str(protected)):
            self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual("earlier result stays fixed", protected.read_text())
        self.assertEqual(1, len(self.launches))

    def test_a_person_does_not_publish_native_paths_or_retain_prompt_files(self) -> None:
        self.run_one()
        summary = Path(self.summary).read_text()
        self.assertNotIn(str(self.home), summary)
        self.assertNotIn("00000000-0000-4000", summary)
        self.assertNotIn("Please repair", summary)
        self.assertFalse(list(Path(self.config.state_dir).glob("observer-model-*")))
        self.assertFalse((Path(self.config.state_dir) / "codex-qualification-output.txt").exists())

    def test_a_person_cannot_change_model_effort_or_argv_before_approval(self) -> None:
        for field, changed in (("model", "other"), ("effort", "high"), ("argv", ["changed"])):
            before = copy.deepcopy(self.transport[field])
            self.transport[field] = changed
            try:
                with self.assertRaises(authority.LedgerError):
                    scorer.codex_model(
                        self.config, self.verified, self.transport, runner=self.fake_runner
                    )
                self.assertEqual([], self.launches)
            finally:
                self.transport[field] = before

    def test_a_person_needs_a_separate_independent_verifier_for_each_adversary(self) -> None:
        case = self.corpus.cases["cases"][-1]
        review = self.corpus.cases["codex_kind_reviews"][case["id"]]
        review["verified_by"] = review["authored_by"]
        cast("dict[str, Any]", self.corpus.marks)["cases_digest"] = marker.cases_digest(
            dict(self.corpus.cases)
        )
        with self.assertRaises(marker.FreezeError):
            scorer.prepare_codex_requests(self.corpus, self.config, self.transport)
        self.assertEqual([], self.launches)

    def test_a_person_can_prepare_at_the_cli_without_claude_or_a_producer_launch(self) -> None:
        with (
            mock.patch.object(scorer, "_load_corpus", return_value=self.corpus),
            mock.patch.object(scorer, "verify_codex_binary", return_value=self.verified),
            mock.patch.object(
                scorer, "verify_claude_binary", side_effect=AssertionError("Claude was inspected")
            ),
            mock.patch.object(scorer, "CLAUDE_VERSIONS_ROOTS", ()),
            contextlib.redirect_stdout(io.StringIO()) as printed,
        ):
            self.assertEqual(0, scorer.main(["--prepare-codex", "--producer", "codex"]))
        self.assertIn('"exposures"', printed.getvalue())
        self.assertNotIn("Please repair", printed.getvalue())
        self.assertEqual([], self.launches)
        self.assertEqual(0, self.study().used())

    def test_a_person_can_approve_one_cli_exposure_without_any_claude_prerequisite(self) -> None:
        construct = scorer.codex_model
        with (
            mock.patch.object(scorer, "_load_corpus", return_value=self.corpus),
            mock.patch.object(scorer, "verify_codex_binary", return_value=self.verified),
            mock.patch.object(
                scorer, "verify_claude_binary", side_effect=AssertionError("Claude was inspected")
            ),
            mock.patch.object(scorer, "CLAUDE_VERSIONS_ROOTS", ()),
            mock.patch.object(marker, "CLAUDE_PROJECTS_ROOT", None),
            mock.patch.object(marker, "STORE_HOME", None),
            mock.patch.object(authority, "LEDGER_PATH", None),
            mock.patch.object(
                scorer,
                "codex_model",
                side_effect=lambda config, verified, transport: construct(
                    config, verified, transport, runner=self.fake_runner
                ),
            ),
            mock.patch("builtins.input", return_value="approve"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                2, scorer.main(["--score", "--producer", "codex", "--out", self.summary])
            )
        self.assertEqual(1, len(self.launches))
        self.assertEqual(1, self.study().used())

    def test_a_person_cannot_prepare_cases_with_an_unscored_required_expectation(self) -> None:
        case = self.corpus.cases["cases"][0]
        self.corpus.rubric["cases"][case["id"]]["expect"].pop("goal")
        with self.assertRaises(marker.FreezeError):
            scorer.prepare_codex_requests(self.corpus, self.config, self.transport)
        self.assertEqual([], self.launches)

    def test_a_person_keeps_the_production_output_and_spawn_guards(self) -> None:
        from compass_runtime import observer, supervise  # noqa: PLC0415 - deferred runtime

        def supervised(argv: list[str], **kwargs: Any) -> Any:
            self.assertEqual(
                (
                    self.transport["argv"][
                        self.transport["argv"].index("--output-last-message") + 1
                    ],
                    observer.OUTPUT_FILE_LIMIT_BYTES,
                ),
                kwargs["output_limit"],
            )
            kwargs["before_spawn"]()
            return self.fake_runner(argv, **kwargs)

        construct = scorer.codex_model
        with (
            mock.patch.object(supervise, "run", side_effect=supervised),
            mock.patch.object(
                scorer,
                "codex_model",
                side_effect=lambda config, verified, transport, **_kw: construct(
                    config, verified, transport
                ),
            ),
        ):
            self.assertEqual(2, self.run_one())
        self.assertEqual(1, len(self.launches))

    def test_a_person_cannot_continue_a_changed_or_pending_checkpoint(self) -> None:
        self.run_one()
        path = Path(self.results)
        before = json.loads(path.read_text())
        for field, value in (
            ("binding", {}),
            ("inputs_digest", "0" * 64),
            ("marks_digest", "0" * 64),
            ("calls", []),
            ("pending", "unreconciled"),
            ("records_digest", "0" * 64),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(before)
                changed[field] = value
                path.write_text(json.dumps(changed))
                self.assertEqual(2, self.run_one(resume=True))
                self.assertEqual(1, len(self.launches))
        path.write_text(json.dumps(before))

    def test_a_person_cannot_resume_after_an_earlier_attempt_record_changes(self) -> None:
        self.run_one()
        call = self.study()._state()[2][0]
        receipt = Path(self.study().path + ".results") / (call["id"] + ".json")
        before = json.loads(receipt.read_text())
        before["cutoff"] = "rewritten synthetic explanation"
        receipt.write_text(json.dumps(before))
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(1, len(self.launches))

    def test_a_person_cannot_admit_omitted_native_checks_or_a_historical_packet(self) -> None:
        case = self.corpus.cases["cases"][0]
        case["producer_facts"] = [
            f for f in case["producer_facts"] if f.get("type") != "tool_report"
        ]
        self.corpus.cases["codex_kind_reviews"][case["id"]]["case_digest"] = authority.digest(case)
        cast("dict[str, Any]", self.corpus.marks)["cases_digest"] = marker.cases_digest(
            dict(self.corpus.cases)
        )
        with self.assertRaises(marker.FreezeError):
            scorer._codex_cases(self.corpus, self.config)
        cast("dict[str, Any]", self.corpus.cases)["v"] = 5
        with self.assertRaises(marker.FreezeError):
            scorer._codex_cases(self.corpus, self.config)

    def test_a_person_cannot_inherit_a_fallback_producer(self) -> None:
        from compass_runtime import reading_route  # noqa: PLC0415 - deferred runtime

        route = dict(scorer._codex_route(self.config, self.verified))
        route["fallback"] = True
        with (
            mock.patch.object(reading_route, "resolve", return_value=route),
            self.assertRaises(scorer.BinaryError),
        ):
            scorer._codex_route(self.config, self.verified)
        self.assertEqual([], self.launches)

    def test_a_person_receives_a_native_reply_even_when_its_writer_replaces_the_output(
        self,
    ) -> None:
        original = self.fake_runner

        def atomic(argv: list[str], **kwargs: Any) -> Any:
            result = original(argv, **kwargs)
            output = Path(argv[argv.index("--output-last-message") + 1])
            other = output.with_suffix(".replacement")
            other.write_bytes(output.read_bytes())
            other.replace(output)
            return result

        construct = scorer.codex_model
        with mock.patch.object(
            scorer,
            "codex_model",
            side_effect=lambda config, verified, transport, **_kw: construct(
                config, verified, transport, runner=atomic
            ),
        ):
            self.assertEqual(2, self.run_one())
        self.assertEqual("usable", self.study()._state()[2][0]["status"])

    def test_a_person_cannot_attach_a_different_model_binding_to_a_real_request(self) -> None:
        self.binding["effort"] = "high"
        self.assertEqual(2, self.run_one())
        self.assertEqual([], self.launches)

    def test_a_person_cannot_redirect_the_attempt_directory(self) -> None:
        target = self.home / "other-results"
        target.mkdir(mode=0o700)
        Path(self.study().path + ".results").symlink_to(target, target_is_directory=True)
        self.assertEqual(2, self.run_one())
        self.assertEqual([], self.launches)

    def test_a_person_retains_a_charged_protection_failure_without_retrying(self) -> None:
        from compass_runtime import observer  # noqa: PLC0415 - deferred runtime

        with mock.patch.object(observer, "OUTPUT_FILE_LIMIT_BYTES", 100):
            self.assertEqual(2, self.run_one())
            self.assertEqual("protection-failed", self.study()._state()[2][0]["status"])
            self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(1, len(self.launches))


if __name__ == "__main__":
    unittest.main()
