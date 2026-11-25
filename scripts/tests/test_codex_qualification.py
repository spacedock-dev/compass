"""A person qualifies Codex with fake transports and capture-shaped temporary sources only."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
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
    from tests.codex_source_support import AT, config, entry, review_receipt, rollout
else:
    from codex_source_support import AT, config, entry, review_receipt, rollout


class _CodexInstallationFixture(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        self.package = self.home / "node_modules/@openai/codex"
        self.launcher = self.package / "bin/codex.js"
        self.node = self.home / "bin/node"
        self.verification_platform = "linux"
        self.verification_machine = "x86_64"
        self.native = self.package / "vendor/x86_64-unknown-linux-musl/codex/codex"
        self.launcher.parent.mkdir(parents=True)
        self.native.parent.mkdir(parents=True)
        self.launcher.write_text("#!/usr/bin/env node\n// @openai/codex launcher\n")
        self.launcher.chmod(0o700)
        self.node.parent.mkdir()
        self.node.write_bytes(b"FAKE NODE; NEVER EXECUTE")
        self.node.chmod(0o700)
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
        resolve = scorer._codex_optional_manifest

        def resolve_package(node: str, launcher: str, package: str) -> str | None:
            if Path(node) != self.home / "bin/node":
                return resolve(node, launcher, package)
            manifest = self.package.parent / "codex-linux-x64/package.json"
            return str(manifest) if manifest.is_file() else None

        patch = mock.patch.object(scorer, "_codex_optional_manifest", side_effect=resolve_package)
        patch.start()
        self.addCleanup(patch.stop)

    def verify(self) -> Any:
        return scorer.verify_codex_binary(
            binary_resolver=lambda _: str(self.launcher),
            node_resolver=lambda _: str(self.node),
            runner=self.version_runner,
            platform=self.verification_platform,
            machine=self.verification_machine,
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
    def test_node_runtime_must_match_the_verified_platform_target(self) -> None:
        node = shutil.which("node")
        if node is None or os.name != "posix":
            self.skipTest("the npm launcher check requires Node on POSIX")
        with self.assertRaisesRegex(scorer.BinaryError, "Node platform"):
            scorer._codex_optional_manifest(
                os.path.realpath(node), str(self.launcher), "@openai/codex-win32-x64"
            )

    def setup_node_launcher(self) -> None:
        node = shutil.which("node")
        if node is None or sys.platform not in ("darwin", "linux"):
            self.skipTest("the npm launcher check requires Node on POSIX")
        self.node = Path(node)
        arch = subprocess.run(
            [node, "-p", "process.arch"], check=True, capture_output=True, text=True, timeout=5
        ).stdout.strip()
        if arch not in ("x64", "arm64"):
            self.skipTest("the npm launcher check needs a supported Codex architecture")
        self.verification_platform = sys.platform
        self.verification_machine = (
            "x86_64" if arch == "x64" else "arm64" if sys.platform == "darwin" else "aarch64"
        )
        platform_target = "apple-darwin" if sys.platform == "darwin" else "unknown-linux-musl"
        processor = "x86_64" if arch == "x64" else "aarch64"
        self.target = f"{processor}-{platform_target}"
        self.platform_package_name = f"codex-{sys.platform}-{arch}"
        native = self.package / "vendor" / self.target / "codex/codex"
        if native != self.native:
            native.parent.mkdir(parents=True)
            self.native.rename(native)
            self.native = native
        if sys.platform == "darwin":
            self.native.write_bytes(b"\xcf\xfa\xed\xfeFAKE TEST EXECUTABLE; NEVER EXECUTE")
        # Match the optional-package lookup and bin layout of the published npm launcher.
        self.launcher.write_text(
            f"""#!/usr/bin/env node
const {{ spawnSync }} = require("node:child_process");
const path = require("node:path");
let root = path.dirname(__dirname);
try {{ root = path.dirname(require.resolve("@openai/{self.platform_package_name}/package.json")); }}
catch {{}}
const native = path.join(root, "vendor", "{self.target}", "bin", "codex");
const child = spawnSync(native, process.argv.slice(2), {{ stdio: "inherit" }});
process.exit(child.status ?? 1);
"""
        )

    def test_launcher_native_layout_mismatch_refuses_before_approval(self) -> None:
        self.setup_node_launcher()
        advertised = self.version_runner.return_value

        def version(command: list[str], *, check: bool, **kwargs: Any) -> Any:
            if command[0] == str(self.native):
                return advertised
            return subprocess.run(command, check=check, **kwargs)

        self.version_runner.side_effect = version
        with self.assertRaises(scorer.BinaryError):
            self.verify()

    def test_new_platform_package_cannot_redirect_verified_launcher(self) -> None:
        self.setup_node_launcher()
        native = self.native.parent.parent / "bin" / "codex"
        native.parent.mkdir()
        self.native.rename(native)
        self.native = native
        verified = self.verify()
        pin = scorer.PinnedCodex(verified)
        marker = self.home / "alternate-native-ran"
        for modules in (self.package / "node_modules", self.home / "node_modules"):
            with self.subTest(modules=modules):
                package = modules / "@openai" / self.platform_package_name
                redirected = package / "vendor" / self.target / "bin/codex"
                redirected.parent.mkdir(parents=True)
                try:
                    (package / "package.json").write_text("{}")
                    redirected.write_text('#!/bin/sh\ntouch "$1"\n')
                    redirected.chmod(0o700)
                    with self.assertRaises(scorer.BinaryError):
                        subprocess.run(
                            [str(self.node), pin("codex"), str(marker)], check=True, timeout=5
                        )
                    self.assertFalse(marker.exists())
                finally:
                    shutil.rmtree(package)

    def test_a_person_records_the_installation_and_native_bytes_separately(self) -> None:
        verified = self.verify()
        self.assertEqual(str(self.launcher), verified.path)
        self.assertEqual(str(self.native), verified.native)
        self.assertEqual(scorer.file_identity(str(self.native)), verified.identity)
        self.assertEqual("codex-cli 0.167.0", verified.version)
        self.version_runner.assert_called_once()
        self.assertEqual(
            [str(self.node), str(self.launcher), "--version"],
            self.version_runner.call_args.args[0],
        )
        self.assertNotEqual(verified.installation_digest, verified.identity[-1])

    def test_the_pinned_executable_is_the_production_npm_launcher(self) -> None:
        verified = self.verify()
        pinned = scorer.PinnedCodex(verified)
        self.assertEqual(str(self.launcher), pinned("codex"))
        self.launcher.write_bytes(self.launcher.read_bytes() + b"// changed")
        with self.assertRaises(scorer.BinaryError):
            pinned("codex")

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
        self.assertEqual(str(self.launcher), pinned("codex"))
        for path in (self.native, self.node, self.launcher, self.package / "package.json"):
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
        self.assertEqual(str(self.native), self.verify().native)

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
        self.reviews: dict[str, Any] = {}
        parser_patch = mock.patch.object(sources, "parser_digest", return_value=self.parser)
        parser_patch.start()
        self.addCleanup(parser_patch.stop)
        # A CODEX_HOME must exist, be this account's and be writable by no other before the
        # route names OpenAI (`claude_settings.verified_folder`).
        (self.home / "codex").mkdir(mode=0o700)
        for patch in (
            mock.patch.object(authority, "real_home", return_value=str(self.home)),
            mock.patch.object(authority, "codex_reviews", return_value=self.reviews),
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
        study = self.study()
        anchor = study.initialize()
        receipt = review_receipt(study, 0, authority.progress(anchor, []))
        proof = authority.digest(receipt)
        self.reviews[proof] = receipt
        self.grant.update(phase="sealed", activation_anchor=anchor, genesis_review=proof)
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

    def review_batch(self, batch: int) -> None:
        study = self.study()
        receipt = review_receipt(study, batch, study.checkpoint())
        proof = authority.digest(receipt)
        self.reviews[proof] = receipt
        study.review_batch(batch, proof)

    def fake_runner(self, argv: list[str], **kwargs: Any) -> Any:
        if self.before_launch:
            self.before_launch()
        calls = self.study()._state()[2]
        self.assertEqual("charged", calls[-1]["status"])
        self.launches.append({"argv": argv, "prompt": kwargs["input"], "charge": calls[-1]["id"]})
        self.assertEqual(argv, self.transport["argv"])
        self.assertEqual(str(self.launcher), argv[0])
        self.assertEqual(str(self.node.parent), kwargs["env"]["PATH"].split(os.pathsep)[0])
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

    def reconcile(self, charge: str | None, status: str) -> int:
        with (
            mock.patch.object(scorer, "verify_codex_binary", return_value=self.verified),
            mock.patch.object(scorer, "_load_corpus", return_value=self.corpus),
            mock.patch.object(scorer, "results_path_for", return_value=self.results),
            mock.patch.object(
                scorer._runtime()[0], "build_runtime_config", return_value=self.config
            ),
            contextlib.redirect_stdout(io.StringIO()),
            mock.patch.object(sys, "stdin", io.StringIO()),
        ):
            args = ["reconcile-codex", status, "--out", self.summary]
            if charge is not None:
                args.extend(("--confirm-charge", charge))
            return scorer.main(args)

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
        self.assertNotIn(str(self.home), self.output.getvalue())
        self.assertNotIn("Please repair", self.output.getvalue())
        for request in self.requests[:10]:
            self.assertIn(request["request_digest"], self.output.getvalue())
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

    def test_a_person_runs_exactly_the_ten_listed_calls_and_checkpoints_each_before_returning(
        self,
    ) -> None:
        self.assertEqual(2, self.run_one())
        self.assertEqual(10, len(self.launches))
        self.assertEqual(
            [r["prompt"] for r in self.requests[:10]],
            [marker.normalized_production_prompt(r["prompt"]) for r in self.launches],
        )
        nonces = [r["prompt"].split('<intent id="', 1)[1].split('"', 1)[0] for r in self.launches]
        self.assertEqual(10, len(set(nonces)))
        self.assertNotIn("0" * 12, nonces)
        for launch, nonce in zip(self.launches, nonces, strict=True):
            self.assertIn(f'</intent id="{nonce}">', launch["prompt"])
        result = json.loads(Path(self.results).read_text())
        self.assertEqual(10, len(result["records"]["attempts"]))
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(10, len(self.launches))
        self.assertIn("Review batch 1", self.output.getvalue())
        self.assertIn(self.requests[10]["request_digest"], self.output.getvalue())

    def test_a_person_resumes_an_interrupted_batch_without_relaunching_a_charged_call(self) -> None:
        checkpoint = scorer._codex_checkpoint

        def stop_after_three(*args: Any, **kwargs: Any) -> Any:
            result = checkpoint(*args, **kwargs)
            if len(result["calls"]) == 3 and not result["pending"]:
                raise KeyboardInterrupt
            return result

        with (
            mock.patch.object(scorer, "_codex_checkpoint", side_effect=stop_after_three),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.run_one()
        self.assertEqual(3, len(self.launches))
        self.assertEqual(2, self.run_one(approve=False, resume=True))
        self.assertEqual(10, len(self.launches))
        self.assertEqual(10, len({r["charge"] for r in self.launches}))

    def test_a_person_stops_before_the_next_launch_if_a_request_in_the_batch_changes(self) -> None:
        original = self.fake_runner

        def change_after_first(argv: list[str], **kwargs: Any) -> Any:
            result = original(argv, **kwargs)
            self.corpus.cases["cases"][1]["production_reading"]["prompt_digest"] = "0" * 64
            return result

        with mock.patch.object(self, "fake_runner", side_effect=change_after_first):
            self.assertEqual(2, self.run_one())
        self.assertEqual(1, len(self.launches))
        self.assertEqual(1, self.study().used())

    def test_a_person_resumes_the_included_retry_at_the_last_slot_before_batch_review(self) -> None:
        checkpoint = scorer._codex_checkpoint

        def stop_at_last(*args: Any, **kwargs: Any) -> Any:
            result = checkpoint(*args, **kwargs)
            if len(result["calls"]) == 10 and not result["pending"]:
                raise KeyboardInterrupt
            return result

        original = self.fake_runner

        def last_unusable(argv: list[str], **kwargs: Any) -> Any:
            self.status = "failed" if len(self.launches) == 9 else "ok"
            return original(argv, **kwargs)

        with (
            mock.patch.object(self, "fake_runner", side_effect=last_unusable),
            mock.patch.object(scorer, "_codex_checkpoint", side_effect=stop_at_last),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.run_one()
        self.status = "ok"
        self.assertEqual(2, self.run_one(approve=False, resume=True))
        self.assertEqual(11, len(self.launches))
        calls = self.study()._state()[2]
        self.assertTrue(calls[-1]["retry"])
        self.assertEqual(calls[-2]["slot"], calls[-1]["slot"])

    def test_a_person_needs_three_complete_passing_repetitions(self) -> None:
        for n in range(3):
            code = self.run_one(resume=n > 0)
            self.assertEqual(0 if n == 2 else 2, code, self.output.getvalue())
            self.assertEqual((n + 1) * 10, len(self.launches))
            if n < 2:
                self.review_batch(n + 1)
        summary = json.loads(Path(self.summary).read_text())
        self.assertEqual("passed", summary["verdict"])
        self.assertEqual(["passed"] * 3, [r["summary"]["verdict"] for r in summary["repetitions"]])
        self.assertEqual(30, self.study().used())
        self.assertEqual(0, self.run_one(resume=True))
        self.assertEqual(30, len(self.launches))

    def test_a_person_sees_only_the_availability_retry_included_in_the_batch_approval(self) -> None:
        original = self.fake_runner

        def first_unusable(argv: list[str], **kwargs: Any) -> Any:
            self.status = "failed" if not self.launches else "ok"
            return original(argv, **kwargs)

        with mock.patch.object(self, "fake_runner", side_effect=first_unusable):
            self.assertEqual(2, self.run_one())
        self.assertEqual(11, len(self.launches))
        attempts = json.loads(Path(self.results).read_text())["records"]["attempts"]
        self.assertEqual([False, True] + [False] * 9, [a["retry"] for a in attempts])
        self.assertEqual(["unusable"] + ["usable"] * 10, [a["classification"] for a in attempts])
        self.assertEqual(11, self.study().used())
        self.assertEqual(2, self.run_one(approve=False, resume=True))
        self.assertEqual(11, len(self.launches))

    def test_a_person_cannot_retry_a_semantic_failure(self) -> None:
        self.semantic = True
        self.assertEqual(1, self.run_one())
        self.assertEqual(10, len(self.launches))
        calls = self.study()._state()[2]
        self.assertTrue(all(c["status"] == "semantic-failed" and not c["retry"] for c in calls))
        self.review_batch(1)
        self.semantic = False
        self.run_one(resume=True)
        self.assertEqual(20, len(self.launches))
        calls = self.study()._state()[2]
        self.assertEqual(20, len({c["slot"] for c in calls}))
        self.assertTrue(all(not c["retry"] for c in calls))

    def test_a_stale_output_alias_refuses_before_spending_a_slot_or_retry(self) -> None:
        argv = self.transport["argv"]
        output = Path(argv[argv.index("--output-last-message") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("left behind")
        self.assertEqual(2, self.run_one())
        self.assertEqual(0, self.study().used())
        self.assertEqual([], self.launches)
        self.assertEqual("left behind", output.read_text())
        output.unlink()
        self.assertEqual(2, self.run_one())
        self.assertEqual(10, self.study().used())
        self.assertFalse(any(call["retry"] for call in self.study()._state()[2]))

    def test_the_owner_can_settle_an_interrupted_charge_and_resume(self) -> None:
        self.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.run_one()
        self.interrupt = False
        charge = self.launches[0]["charge"]
        self.assertEqual(2, self.reconcile(charge, "refunded"))
        self.assertEqual(0, self.reconcile(charge, "unusable"))
        attempt = Path(self.study().path + ".results", charge + ".json")
        self.assertEqual("unusable", json.loads(attempt.read_text())["classification"])
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(11, len(self.launches))
        self.assertEqual(1, sum(row["charge"] == charge for row in self.launches))

    def test_reconciliation_keeps_the_witnessed_output_if_settlement_was_interrupted(self) -> None:
        with (
            mock.patch.object(authority.CodexLedger, "settle", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.run_one()
        charge = self.launches[0]["charge"]
        record = Path(self.study().path + ".results", charge + ".json")
        written = record.read_bytes()
        self.assertEqual(0, self.reconcile(charge, "usable"))
        self.assertEqual(written, record.read_bytes())
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(10, len(self.launches))

    def test_interrupted_protection_failure_can_be_retained_without_retry(self) -> None:
        from compass_runtime import observer  # noqa: PLC0415 - deferred runtime

        checkpoint = scorer._codex_checkpoint

        def interrupt_after_settlement(*args: Any, **kwargs: Any) -> None:
            if not kwargs.get("pending"):
                raise KeyboardInterrupt
            checkpoint(*args, **kwargs)

        for settled in (False, True):
            with self.subTest(settled=settled):
                self.doCleanups()
                self.setUp()
                interrupt = (
                    mock.patch.object(
                        scorer, "_codex_checkpoint", side_effect=interrupt_after_settlement
                    )
                    if settled
                    else mock.patch.object(
                        authority.CodexLedger, "settle", side_effect=KeyboardInterrupt
                    )
                )
                with (
                    mock.patch.object(observer, "OUTPUT_FILE_LIMIT_BYTES", 100),
                    interrupt,
                    self.assertRaises(KeyboardInterrupt),
                ):
                    self.run_one()
                charge = self.launches[0]["charge"]
                attempt = Path(self.study().path + ".results", charge + ".json")
                written = attempt.read_bytes()
                self.assertEqual(2, self.reconcile(charge, "unusable"))
                self.assertEqual(2, self.reconcile(charge, "refunded"))
                self.assertEqual(0, self.reconcile(charge, "usable"))
                self.assertEqual(written, attempt.read_bytes())
                self.assertEqual("protection-failed", self.study()._state()[2][0]["status"])
                self.assertEqual(1, self.study().used())
                self.assertEqual(2, self.run_one(resume=True))
                self.assertEqual(1, len(self.launches))

    def test_a_refund_before_the_launch_fence_reopens_the_same_slot_without_a_retry(self) -> None:
        checkpoint = scorer._codex_checkpoint

        def stop_before_launch(*args: Any, **kwargs: Any) -> Any:
            result = checkpoint(*args, **kwargs)
            if kwargs.get("pending"):
                raise KeyboardInterrupt
            return result

        with (
            mock.patch.object(scorer, "_codex_checkpoint", side_effect=stop_before_launch),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.run_one()
        charge = self.study()._state()[2][-1]["id"]
        self.assertEqual([], self.launches)
        self.assertEqual(2, self.reconcile("0" * 32, "refunded"))
        self.assertEqual(2, self.reconcile(None, "refunded"))
        self.assertEqual(0, self.reconcile(charge, "refunded"))
        self.assertEqual(0, self.study().used())
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(10, len(self.launches))
        self.assertIn("Codex qualification: 10 charged attempts", self.output.getvalue())
        self.assertEqual(10, self.study().used())
        self.assertEqual(10, json.loads(Path(self.summary).read_text())["spend"]["charged"])
        local = json.loads(Path(self.results).read_text())
        self.assertEqual("refunded", local["records"]["attempts"][0]["classification"])
        self.assertFalse(any(row["retry"] for row in local["calls"]))

    def test_a_witnessed_but_missing_output_can_be_reconciled_as_unusable(self) -> None:
        write = authority.write_receipt

        def stop_before_result(path: str, body: Any) -> None:
            if Path(path).parent.name.startswith(".attempt-"):
                Path(path).write_bytes(b'{"partial":')
                raise KeyboardInterrupt
            write(path, body)

        with (
            mock.patch.object(authority, "write_receipt", side_effect=stop_before_result),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.run_one()
        charge = self.launches[0]["charge"]
        self.assertEqual(2, self.reconcile(charge, "usable"))
        self.assertEqual(0, self.reconcile(charge, "unusable"))
        self.assertEqual(2, self.run_one(resume=True))

    def test_missing_witnessed_failure_never_unlocks_availability_retry(self) -> None:
        write = authority.write_receipt

        def interrupt_publication(path: str, body: Any) -> None:
            if Path(path).parent.name.startswith(".attempt-"):
                raise KeyboardInterrupt
            write(path, body)

        for status in ("semantic-failed", "coverage-failed", "protection-failed"):
            for published in (False, True):
                with self.subTest(status=status, published=published):
                    self.doCleanups()
                    self.setUp()
                    interrupt = (
                        mock.patch.object(
                            authority.CodexLedger, "settle", side_effect=KeyboardInterrupt
                        )
                        if published
                        else mock.patch.object(
                            authority, "write_receipt", side_effect=interrupt_publication
                        )
                    )
                    with (
                        mock.patch.object(scorer, "_repeat_classification", return_value=status),
                        interrupt,
                        self.assertRaises(KeyboardInterrupt),
                    ):
                        self.run_one()
                    charge = self.launches[0]["charge"]
                    if published:
                        Path(self.study().path + ".results", charge + ".json").unlink()
                    self.assertEqual(0, self.reconcile(charge, "unusable"))
                    self.assertEqual(status, self.study()._state()[2][0]["status"])
                    self.run_one(resume=True)
                    calls = self.study()._state()[2]
                    self.assertFalse(any(call["retry"] for call in calls))
                    self.assertEqual(10 if status == "semantic-failed" else 1, len(self.launches))
                    if status == "semantic-failed":
                        self.assertEqual(
                            scorer.VERDICT_FAILED,
                            json.loads(Path(self.summary).read_text())["verdict"],
                        )

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
        self.assertEqual(10, len(self.launches))

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
        self.run_one()
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

    def test_pin_refusal_before_spawn_keeps_reservation_refundable(self) -> None:
        link = os.link
        native = self.native.read_bytes()

        def change_after_alias(*args: Any, **kwargs: Any) -> None:
            link(*args, **kwargs)
            self.native.write_bytes(native + b"changed before the runner")

        with mock.patch.object(os, "link", side_effect=change_after_alias):
            self.assertEqual(2, self.run_one())
        self.assertEqual([], self.launches)
        call = self.study()._state()[2][-1]
        self.assertIs(call["launch_armed"], False)
        self.assertEqual("charged", call["status"])
        self.native.write_bytes(native)
        self.verified = self.verify()
        self.assertEqual(0, self.reconcile(call["id"], "refunded"))
        self.assertEqual(0, self.study().used())
        self.assertEqual(2, self.run_one(resume=True))
        calls = self.study()._state()[2]
        self.assertEqual(call["slot"], calls[1]["slot"])
        self.assertEqual(10, len(self.launches))
        self.assertFalse(any(attempt["retry"] for attempt in calls))

    def test_a_person_cannot_swap_the_cli_while_the_launch_fence_lands(self) -> None:
        arm = authority.CodexLedger.arm_launch

        def change_after_fence(ledger: Any, charge: str) -> None:
            arm(ledger, charge)
            self.launcher.write_bytes(self.launcher.read_bytes() + b"// changed while arming")

        with mock.patch.object(authority.CodexLedger, "arm_launch", change_after_fence):
            self.assertEqual(2, self.run_one())
        self.assertEqual([], self.launches)
        call = self.study()._state()[2][-1]
        self.assertIs(call["launch_armed"], True)
        self.assertEqual("charged", call["status"])

    def test_a_person_cannot_redirect_an_immutable_attempt_receipt(self) -> None:
        self.run_one()
        call = self.study()._state()[2][0]
        receipt = Path(self.study().path + ".results") / (call["id"] + ".json")
        copied = self.home / "copied-result.json"
        copied.write_bytes(receipt.read_bytes())
        receipt.unlink()
        receipt.symlink_to(copied)
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(10, len(self.launches))

    def test_a_person_cannot_overwrite_a_historical_result_with_codex_output(self) -> None:
        protected = self.home / "prior-claude-results.json"
        protected.write_text("earlier result stays fixed")
        self.run_one()
        self.summary = str(protected)
        with mock.patch.object(scorer, "CLAUDE_SUMMARY_PATH", str(protected)):
            self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual("earlier result stays fixed", protected.read_text())
        self.assertEqual(10, len(self.launches))

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

    def test_a_person_can_approve_one_cli_batch_without_any_claude_prerequisite(self) -> None:
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
        self.assertEqual(10, len(self.launches))
        self.assertEqual(10, self.study().used())

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
        self.assertEqual(10, len(self.launches))

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
                self.assertEqual(10, len(self.launches))
        path.write_text(json.dumps(before))

    def test_a_person_cannot_resume_after_an_earlier_attempt_record_changes(self) -> None:
        self.run_one()
        call = self.study()._state()[2][0]
        receipt = Path(self.study().path + ".results") / (call["id"] + ".json")
        before = json.loads(receipt.read_text())
        before["cutoff"] = "rewritten synthetic explanation"
        receipt.write_text(json.dumps(before))
        self.assertEqual(2, self.run_one(resume=True))
        self.assertEqual(10, len(self.launches))

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
