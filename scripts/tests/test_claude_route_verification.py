"""One browser-route attempt consumes one held live slot, never qualification quota."""

from __future__ import annotations

import copy
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RouteSidecarGuards(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.route = importlib.import_module("claude_route_verification")
        except ImportError:
            self.fail("the single-attempt route verifier is absent")
        self.assertTrue(
            hasattr(self.route, "profile_binding"), "durable public genesis binding is absent"
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.owner = self.root
        self.context_dir = self.root / ".cargento" / "claude-route-verification"
        self.context_dir.mkdir(mode=0o700, parents=True)
        self.context_dir.parent.chmod(0o700)
        self.state = self.root / ".cargento" / "analyze-closure-route-spend.json"
        self.profile = self.root / "profile.json"
        self.handoff = self.root / "handoff.json"
        for name, path in (
            ("PROFILE_PATH", self.profile),
            ("HANDOFF_PATH", self.handoff),
            ("STATE_PATH", self.state),
            ("PRIVATE_DIR", self.context_dir),
            ("OWNER_HOME", self.owner),
            ("ACTIVATION_PATH", self.root / ".cargento" / "claude-route-live00.ACTIVATED.json"),
        ):
            patch = mock.patch.object(self.route, name, path, create=True)
            patch.start()
            self.addCleanup(patch.stop)
        self.ui_file = self.context_dir / "before-press.png"
        self.ui_file.write_bytes(b"test-only screenshot fixture")
        self.ui_file.chmod(0o600)
        self.context = {
            "v": 1,
            "startup": {
                "pid": 1,
                "nonce": "a" * 32,
                "config_digest": "b" * 64,
                "page_sha256": "4" * 64,
            },
            "selected": {"sid": "12345678", "full_sid": "12345678-1234-4234-8234-123456789abc"},
            "app_binding": "c" * 64,
            "prompt_sha256": self.route.sha(b"owned prompt"),
            "output_cap_bytes": 8192,
            "source_files": [
                {"path": str(self.ui_file), "sha256": self.route.sha(self.ui_file.read_bytes())}
            ],
            "ui_before_press_sha256": self.route.sha(self.ui_file.read_bytes()),
        }
        self.context_path = self.context_dir / "context.json"
        self.write_private(self.context_path, self.context)
        self.write_private(self.context_dir / "startup.json", self.context["startup"])
        self.snapshot = {
            "native_calls": 68,
            "qualification_calls": 30,
            "shared_calls": 40,
            "review_digest": "e" * 64,
            "summary_sha256": "f" * 64,
            "state_digest": "1" * 64,
        }
        self.snapshot_patch = mock.patch.object(
            self.route, "qualification_snapshot", return_value=self.snapshot
        )
        self.snapshot_patch.start()
        self.addCleanup(self.snapshot_patch.stop)
        self.body = {
            "v": 1,
            "phase": "prepared",
            "activation_anchor": None,
            "slot": "held-live-00",
            "attempt_cap": 1,
            "retry_cap": 0,
            "held": {"live": 17, "replay": 190},
            "shared_cap": 249,
            "qualification": self.snapshot,
            "context_sha256": self.route.sha(self.context_path.read_bytes()),
            "wrapper_sha256": self.route.source_digest(),
            "transport": {
                "provider": "claude",
                "destination": "Anthropic",
                "model": "claude-sonnet-5-5",
                "effort": "high",
                "binary_sha256": "2" * 64,
                "argv_digest": "3" * 64,
            },
        }
        self.snapshot["transport"] = copy.deepcopy(self.body["transport"])
        self.profile.write_text(json.dumps(self.body))
        self.review = {
            "v": 1,
            "verdict": "GO",
            "prepared_by": "operator",
            "reviewed_by": "reviewer",
            "profile_digest": self.route.profile_binding(self.body),
            "activation_anchor": None,
            "qualification_review_digest": self.snapshot["review_digest"],
        }
        self.handoff.write_text(json.dumps(self.review))

    @staticmethod
    def write_private(path: Path, body: Any) -> None:
        path.write_text(json.dumps(body))
        path.chmod(0o600)

    def verifier(self) -> Any:
        return self.route.RouteVerification()

    def initialize(self) -> Any:
        current = self.verifier()
        anchor = current.initialize()
        return self.seal(anchor)

    def seal(self, anchor: str) -> Any:
        self.body.update(phase="sealed", activation_anchor=anchor)
        self.profile.write_text(json.dumps(self.body))
        self.review["activation_anchor"] = anchor
        self.handoff.write_text(json.dumps(self.review))
        return self.verifier()

    def request(self) -> dict[str, Any]:
        return {
            "app_binding": self.context["app_binding"],
            "prompt_sha256": self.context["prompt_sha256"],
            "output_cap_bytes": 8192,
            "transport": self.body["transport"],
        }

    def test_explicit_initialization_and_one_charge_leave_all_other_attempts_held(self) -> None:
        current = self.verifier()
        with self.assertRaises(self.route.RefusalError):
            current.reserve(self.request())
        current = self.seal(current.initialize())
        self.assertEqual(0, current.budget_view()["route_attempts"])
        charge = current.reserve(self.request())
        self.assertEqual(41, current.budget_view()["shared_charged"])
        self.assertEqual({"live": 17, "replay": 190}, current.budget_view()["held"])
        current.settle_transport(charge, "ok", output_digest="4" * 64)
        with self.assertRaises(self.route.RefusalError):
            current.reserve(self.request())
        with self.assertRaises(self.route.RefusalError):
            current.initialize()

    def test_ninth_qualification_allocation_admits249_without_borrowing_retry(self) -> None:
        self.snapshot.update(native_calls=68, qualification_calls=30, shared_calls=40)
        self.body["shared_cap"] = 249
        self.profile.write_text(json.dumps(self.body))
        self.review["profile_digest"] = self.route.profile_binding(self.body)
        self.handoff.write_text(json.dumps(self.review))
        try:
            current = self.initialize()
        except self.route.RefusalError as error:
            self.fail(f"fixed ninth qualification profile should be admitted: {error}")
        current.reserve(self.request())
        view = current.budget_view()
        self.assertEqual(41, view["shared_charged"])
        self.assertEqual(249, view["shared_cap"])
        self.assertEqual(1, view["qualification_retry_held"])
        self.assertEqual(249, view["shared_charged"] + view["qualification_retry_held"] + 17 + 190)
        with self.assertRaises(self.route.RefusalError):
            current.reserve(self.request())

    def test_qualification_retry_used_does_not_change_the_one_live_attempt(self) -> None:
        self.snapshot.update(native_calls=69, qualification_calls=31, shared_calls=41)
        self.profile.write_text(json.dumps(self.body))
        self.review["profile_digest"] = self.route.profile_binding(self.body)
        self.handoff.write_text(json.dumps(self.review))
        current = self.initialize()
        current.reserve(self.request())
        view = current.budget_view()
        self.assertEqual(42, view["shared_charged"])
        self.assertEqual(0, view["qualification_retry_held"])
        self.assertEqual(249, view["shared_charged"] + 17 + 190)

    def test_wrong_prompt_provider_source_and_unreviewed_profile_refuse_before_charge(self) -> None:
        current = self.initialize()
        for field, bad in (
            ("app_binding", "0" * 64),
            ("prompt_sha256", "0" * 64),
            ("output_cap_bytes", 9000),
            ("transport", {**self.body["transport"], "provider": "codex"}),
        ):
            with self.subTest(field=field):
                request = self.request()
                request[field] = bad
                with self.assertRaises(self.route.RefusalError):
                    current.reserve(request)
                self.assertEqual(0, current.budget_view()["route_attempts"])
        self.context_path.write_text("{}")
        with self.assertRaises(self.route.RefusalError):
            current.reserve(self.request())

    def test_deleted_state_or_receipt_never_refunds_a_charge(self) -> None:
        current = self.initialize()
        charge = current.reserve(self.request())
        self.state.unlink()
        with self.assertRaises(self.route.RefusalError):
            self.verifier().initialize()
        with self.assertRaises(self.route.RefusalError):
            current.settle_transport(charge, "ok", output_digest="4" * 64)

    def test_unusable_exception_and_orphan_stop_without_retry(self) -> None:
        current = self.initialize()
        charge = current.reserve(self.request())
        current.settle_transport(charge, "failed", output_digest="4" * 64)
        with self.assertRaises(self.route.RefusalError):
            current.reserve(self.request())
        self.assertEqual(1, current.budget_view()["route_attempts"])
        with self.assertRaises(self.route.RefusalError):
            current.settle_transport(charge, "ok", output_digest="4" * 64)

    def test_transport_ok_is_not_route_acceptance(self) -> None:
        current = self.initialize()
        charge = current.reserve(self.request())
        current.settle_transport(charge, "ok", output_digest="4" * 64)
        self.assertFalse(current.budget_view()["route_accepted"])
        with self.assertRaises(self.route.RefusalError):
            current.accept_route({"verdict": "passed"})

    def test_no_arbitrary_allocation_extra_retry_or_same_reviewer(self) -> None:
        for field, bad in (
            ("slot", "held-live-01"),
            ("attempt_cap", 2),
            ("retry_cap", 1),
            ("shared_cap", 246),
        ):
            with self.subTest(field=field):
                body = {**self.body, field: bad}
                self.profile.write_text(json.dumps(body))
                self.review["profile_digest"] = self.route.profile_binding(body)
                self.handoff.write_text(json.dumps(self.review))
                with self.assertRaises(self.route.RefusalError):
                    self.verifier()
        self.profile.write_text(json.dumps(self.body))
        self.review["profile_digest"] = self.route.profile_binding(self.body)
        self.review["reviewed_by"] = "operator"
        self.handoff.write_text(json.dumps(self.review))
        with self.assertRaises(self.route.RefusalError):
            self.verifier()

    def test_missing_qualification_acceptance_and_symlink_account_refuse(self) -> None:
        self.snapshot_patch.stop()
        with (
            mock.patch.object(
                self.route,
                "qualification_snapshot",
                side_effect=self.route.RefusalError("missing acceptance"),
            ),
            self.assertRaises(self.route.RefusalError),
        ):
            self.verifier()
        self.snapshot_patch.start()
        current = self.initialize()
        self.state.rename(self.state.with_suffix(".saved"))
        try:
            self.state.symlink_to(self.state.with_suffix(".saved"))
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(self.route.RefusalError):
            current.reserve(self.request())

    def test_a_different_admitted_model_cannot_inherit_qualification(self) -> None:
        body = copy.deepcopy(self.body)
        body["transport"]["model"] = "claude-opus-5-5"
        self.profile.write_text(json.dumps(body))
        self.review["profile_digest"] = self.route.profile_binding(body)
        self.handoff.write_text(json.dumps(self.review))
        with self.assertRaises(self.route.RefusalError):
            self.verifier()

    def test_two_concurrent_reservations_execute_at_most_once(self) -> None:
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415 - this race only

        current = self.initialize()

        def reserve() -> str:
            try:
                return cast("str", current.reserve(self.request()))
            except self.route.RefusalError:
                return "refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _n: reserve(), range(2)))
        self.assertEqual(1, results.count("refused"))
        self.assertEqual(1, current.budget_view()["route_attempts"])

    def test_a_late_binding_failure_can_settle_failed_but_never_refund(self) -> None:
        current = self.initialize()
        charge = current.reserve(self.request())
        self.context_path.write_text("{}")
        with self.assertRaises(self.route.RefusalError):
            current.settle_transport(charge, "ok", output_digest="4" * 64)
        self.assertIsNone(json.loads(self.state.read_bytes())["settlement"])
        try:
            current.settle_transport(charge, "failed", output_digest="4" * 64)
        except self.route.RefusalError as error:
            self.fail(f"the charged late failure must remain durably settleable: {error}")
        body = json.loads(self.state.read_bytes())
        self.assertEqual("failed", body["settlement"]["status"])
        self.assertEqual(charge, body["attempt"]["id"])
        with self.assertRaises(self.route.RefusalError):
            current.reserve(self.request())

    def test_unknown_terminal_status_refuses_before_stale_account_access(self) -> None:
        current = self.initialize()
        charge = current.reserve(self.request())
        self.context_path.write_text("{}")
        with mock.patch.object(current, "_state") as state:
            with self.assertRaises(self.route.RefusalError):
                current.settle_transport(charge, "unknown", output_digest="4" * 64)
            state.assert_not_called()
        self.assertIsNone(json.loads(self.state.read_bytes())["settlement"])

    def test_erasing_all_private_history_cannot_reinitialize_a_sealed_profile(self) -> None:
        import shutil  # noqa: PLC0415 - isolated synthetic account deletion

        current = self.initialize()
        current.reserve(self.request())
        self.state.unlink()
        shutil.rmtree(current.receipts)
        with self.assertRaises(self.route.RefusalError):
            self.verifier().initialize()

    def test_prepared_profile_rollback_cannot_remint_erased_live_attempt(self) -> None:
        current = self.initialize()
        current.reserve(self.request())
        self.route.shutil.rmtree(current.receipts)
        self.state.unlink()
        self.body.update(phase="prepared", activation_anchor=None)
        self.profile.write_text(json.dumps(self.body))
        self.review["activation_anchor"] = None
        self.handoff.write_text(json.dumps(self.review))
        with self.assertRaises(self.route.RefusalError):
            self.verifier().initialize()

    def test_activation_tombstone_precedes_genesis_and_partial_activation_refuses(self) -> None:
        current = self.verifier()
        original = self.route._exclusive

        def interrupt(path: Path, body: Any) -> None:
            if path.name == "GENESIS.json":
                self.assertTrue(self.route.ACTIVATION_PATH.is_file())
                raise OSError("test-only interruption after durable tombstone")
            original(path, body)

        with (
            mock.patch.object(self.route, "_exclusive", side_effect=interrupt),
            self.assertRaises(OSError),
        ):
            current.initialize()
        with self.assertRaises(self.route.RefusalError):
            self.verifier()

    def test_missing_or_partial_activation_tombstone_refuses_existing_history(self) -> None:
        self.initialize()
        marker = self.route.ACTIVATION_PATH
        self.assertTrue(marker.is_file())
        marker.unlink()
        with self.assertRaises(self.route.RefusalError):
            self.verifier()
        marker.write_bytes(b"{")
        marker.chmod(0o600)
        with self.assertRaises(self.route.RefusalError):
            self.verifier()

    def test_changed_activation_anchor_or_aliased_tombstone_refuses_history(self) -> None:
        self.initialize()
        marker = self.route.ACTIVATION_PATH
        body = json.loads(marker.read_bytes())
        body["genesis_digest"] = "0" * 64
        self.write_private(marker, body)
        with self.assertRaises(self.route.RefusalError):
            self.verifier()
        if sys.platform != "win32":
            target = marker.with_suffix(".alias")
            marker.rename(target)
            marker.symlink_to(target)
            with self.assertRaises(self.route.RefusalError):
                self.verifier()

    def test_daemon_and_background_model_flags_cannot_escape_the_owned_guard(self) -> None:
        self.route._runtime()
        from compass_runtime import cli  # noqa: PLC0415 - genuine entry point must not be called

        for flag in (
            "--daemon",
            "--stop",
            "--status",
            "--diagnose",
            "--observer-model",
            "--unasked-readings",
            "--no-observer-model",
            "--no-annotations",
        ):
            with self.subTest(flag=flag), mock.patch.object(cli, "main", return_value=0) as main:
                with self.assertRaises(self.route.RefusalError):
                    self.route.run_server([flag])
                main.assert_not_called()

    def test_missing_startup_or_prepress_evidence_cannot_arm_the_route(self) -> None:
        (self.context_dir / "startup.json").unlink()
        with self.assertRaises(self.route.RefusalError):
            self.verifier()
        self.write_private(self.context_dir / "startup.json", self.context["startup"])
        self.context["source_files"] = []
        self.write_private(self.context_path, self.context)
        self.body["context_sha256"] = self.route.sha(self.context_path.read_bytes())
        self.profile.write_text(json.dumps(self.body))
        self.review["profile_digest"] = self.route.profile_binding(self.body)
        self.handoff.write_text(json.dumps(self.review))
        with self.assertRaises(self.route.RefusalError):
            self.verifier()

    def test_native_model_and_consent_policy_charge_before_the_real_callback_seam(self) -> None:
        self._exercise_native_job_status("ok")

    def test_unstopped_native_status_keeps_the_real_job_running_warning(self) -> None:
        self._exercise_native_job_status("unstopped")

    def test_oversized_native_status_keeps_the_real_job_output_limit_reason(self) -> None:
        self._exercise_native_job_status("oversized")

    def test_changed_source_during_unstopped_call_keeps_shutdown_warning_and_settlement(
        self,
    ) -> None:
        self._exercise_native_job_status("unstopped", source_changed=True)

    def test_changed_source_during_oversized_call_keeps_shutdown_reason_and_settlement(
        self,
    ) -> None:
        self._exercise_native_job_status("oversized", source_changed=True)

    def _assert_native_job_outcome(self, app: Any, guarded: Any, status: str) -> None:
        from compass_runtime import (  # noqa: PLC0415 - actual job outcome seam
            reading,
            reading_jobs,
            supervise,
        )

        def compose(_hooks: Any) -> Any:
            with mock.patch.object(supervise, "closed", return_value=False):
                raw, actual_status = guarded("owned prompt", output_cap_bytes=8192)
            self.assertEqual(("native test-only reply", status), (raw, actual_status))
            failure = reading._call_failed(guarded, actual_status)
            assert failure is not None
            why, spent = failure
            return None, why, spent

        from types import SimpleNamespace  # noqa: PLC0415 - spent actual seam outcome

        with mock.patch.object(supervise, "closed", return_value=True):
            self.assertEqual(
                (None, status, True),
                reading_jobs._outcome(app, compose, cast("Any", SimpleNamespace(spent=True))),
            )
        settlement = json.loads(self.state.read_bytes())["settlement"]
        self.assertEqual(status, settlement["status"])
        self.assertEqual(self.route.sha(b"native test-only reply"), settlement["output_digest"])

    def _exercise_native_job_status(self, status: str, *, source_changed: bool = False) -> None:
        from types import SimpleNamespace  # noqa: PLC0415 - owned test-only application

        _annotations, observer, reading, policy, _route = self.route._runtime()
        from compass_runtime import cli, supervise  # noqa: PLC0415 - real runtime seams
        from compass_runtime import (  # noqa: PLC0415 - actual runtime configuration
            config as runtime_config,
        )

        config = runtime_config.build_runtime_config(
            environ={"HOME": str(self.owner), "COMPASS_HOME": str(self.root / "app-state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            observer_model_enabled=False,
            unasked_enabled=False,
        )
        app = SimpleNamespace(config=config, clock=lambda: 100.0, diagnostic_sink=lambda _: None)
        (self.context_dir / "startup.json").unlink()

        def spawned(_group: Any) -> None:
            pass

        sent: list[str] = []

        def native(config_arg: Any, prompt: str, **kwargs: Any) -> tuple[str, str]:
            self.assertIs(config, config_arg)
            self.assertEqual(1, self.verifier().budget_view()["route_attempts"])
            self.assertIs(supervise.run, kwargs["runner"])
            self.assertIs(self.route.shutil.which, kwargs["binary_resolver"])
            self.assertIs(spawned, kwargs["on_spawn"])
            sent.append(prompt)
            if source_changed:
                self.ui_file.write_bytes(b"test-only evidence change during charged native call")
            return "native test-only reply", status

        with (
            mock.patch.object(observer, "claude_exec", side_effect=native),
            mock.patch.object(cli, "build_server", return_value=object()),
            mock.patch.object(self.route, "app_binding", return_value=self.context["app_binding"]),
            mock.patch.object(self.route, "transport_binding", return_value=self.body["transport"]),
            mock.patch.object(
                self.route.shutil,
                "which",
                side_effect=lambda name: (
                    str(self.root / "native-cli") if name == "claude" else None
                ),
            ),
        ):
            original_exec = observer.claude_exec
            with self.route.install_native_guard() as captured:
                cli.build_server(
                    ("127.0.0.1", 0),
                    cast("Any", app),
                    b"real page",
                    None,
                    interaction_session=None,
                    interaction_registration_file=None,
                )
                self.context["startup"] = captured["startup"]
                self.write_private(self.context_path, self.context)
                self.body["context_sha256"] = self.route.sha(self.context_path.read_bytes())
                self.profile.write_text(json.dumps(self.body))
                self.review["profile_digest"] = self.route.profile_binding(self.body)
                self.handoff.write_text(json.dumps(self.review))
                current = self.initialize()
                policy.set_consent(
                    config,
                    True,
                    now=100.0,
                    provider="claude",
                    destination="Anthropic",
                    content=policy.CONTENT_VERSION,
                )
                model = reading.ClaudeReadingModel(
                    config, binary_resolver=self.route.shutil.which, on_spawn=spawned
                )
                guarded = policy.GuardedModel(
                    config,
                    model,
                    app.clock,
                    provider="claude",
                    destination="Anthropic",
                    resolve_destination=lambda: "Anthropic",
                    content=policy.CONTENT_VERSION,
                )
                if status == "ok":
                    self.assertEqual(
                        ("native test-only reply", status),
                        guarded("owned prompt", output_cap_bytes=8192),
                    )
                else:
                    self._assert_native_job_outcome(app, guarded, status)
                self.assertEqual(["owned prompt"], sent)
                with self.assertRaises(self.route.RefusalError):
                    observer.codex_exec(config, "unapproved codex", output_cap_bytes=8192)
                with self.assertRaises(self.route.RefusalError):
                    model("owned prompt", output_cap_bytes=8192)
                if source_changed:
                    self.assertIsNone(json.loads(self.state.read_bytes())["acceptance"])
                    with self.assertRaises(self.route.RefusalError):
                        current.accept_route({})
                else:
                    self.assertFalse(current.budget_view()["route_accepted"])
            self.assertIs(original_exec, observer.claude_exec)

    def test_native_exception_stays_charged_and_unarmed_guard_never_sends(self) -> None:
        from types import SimpleNamespace  # noqa: PLC0415 - owned test-only application

        _annotations, observer, reading, _policy, _route = self.route._runtime()
        from compass_runtime import cli  # noqa: PLC0415 - real runtime seams
        from compass_runtime import (  # noqa: PLC0415 - actual runtime configuration
            config as runtime_config,
        )

        config = runtime_config.build_runtime_config(
            environ={"HOME": str(self.owner), "COMPASS_HOME": str(self.root / "app-state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            observer_model_enabled=False,
            unasked_enabled=False,
        )
        app = SimpleNamespace(config=config, clock=lambda: 100.0)
        (self.context_dir / "startup.json").unlink()
        with (
            mock.patch.object(
                observer, "claude_exec", side_effect=RuntimeError("test-only native failure")
            ) as delegate,
            mock.patch.object(cli, "build_server", return_value=object()),
            mock.patch.object(self.route, "app_binding", return_value=self.context["app_binding"]),
            mock.patch.object(self.route, "transport_binding", return_value=self.body["transport"]),
            self.route.install_native_guard() as captured,
        ):
            cli.build_server(
                ("127.0.0.1", 0),
                cast("Any", app),
                b"page",
                None,
                interaction_session=None,
                interaction_registration_file=None,
            )
            self.context["startup"] = captured["startup"]
            self.write_private(self.context_path, self.context)
            self.body["context_sha256"] = self.route.sha(self.context_path.read_bytes())
            self.profile.write_text(json.dumps(self.body))
            self.review["profile_digest"] = self.route.profile_binding(self.body)
            self.handoff.write_text(json.dumps(self.review))
            model = reading.ClaudeReadingModel(config)
            with self.assertRaises(self.route.RefusalError):
                model("owned prompt", output_cap_bytes=8192)
            delegate.assert_not_called()
            current = self.initialize()
            with self.assertRaises(RuntimeError):
                model("owned prompt", output_cap_bytes=8192)
            self.assertEqual(1, delegate.call_count)
            self.assertEqual(1, current.budget_view()["route_attempts"])
            self.assertEqual("failed", json.loads(self.state.read_bytes())["settlement"]["status"])
            with self.assertRaises(self.route.RefusalError):
                model("owned prompt", output_cap_bytes=8192)
            self.assertEqual(1, delegate.call_count)

    def test_actual_app_binding_reads_native_source_saved_intent_and_real_consent(self) -> None:
        from types import SimpleNamespace  # noqa: PLC0415 - test-only collected row owner

        annotations, _observer, _reading, policy, _route = self.route._runtime()
        from compass_runtime import config as runtime_config  # noqa: PLC0415 - real configuration
        from compass_runtime import state as runtime_state  # noqa: PLC0415 - real state and stores

        config = runtime_config.build_runtime_config(
            environ={"HOME": str(self.owner), "COMPASS_HOME": str(self.root / "app-state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            observer_model_enabled=False,
            unasked_enabled=False,
        )
        state = runtime_state.build_runtime_state(config, started=50.0)
        full = self.context["selected"]["full_sid"]
        source = self.root / ".claude" / "projects" / "owned" / (full + ".jsonl")
        source.parent.mkdir(parents=True)
        source.write_text(
            json.dumps({"type": "user", "sessionId": full, "message": {"content": "owned goal"}})
            + "\n"
        )
        outcome = annotations.annotate(
            config, state, "claude", full, goal="Continue the requested work.", lines=[], now=80.0
        )
        self.assertEqual(annotations.OUTCOME_STORED, outcome)
        row = {
            "harness": "claude",
            "sid": self.context["selected"]["sid"],
            "resume_id": full,
            "state": "working",
            "finished_at": None,
            "ended_at": None,
            "acquisition": "native",
        }
        app = SimpleNamespace(
            config=config,
            state=state,
            clock=lambda: 100.0,
            collect_json=lambda **_kwargs: (None, json.dumps({"sessions": [row]}).encode()),
        )
        native_destination = _route.destination
        with (
            mock.patch.object(
                self.route.shutil,
                "which",
                side_effect=lambda name: (
                    str(self.root / "native-cli") if name == "claude" else None
                ),
            ),
            mock.patch.object(_route.platform, "system", return_value="Linux"),
            mock.patch.dict(
                _route.os.environ, {"HOME": str(self.owner), "USER": "route-fixture"}, clear=True
            ),
            mock.patch.object(
                _route,
                "destination",
                side_effect=lambda provider, **kwargs: native_destination(
                    provider, **{**kwargs, "root": self.owner}
                ),
            ),
        ):
            with self.assertRaises(self.route.RefusalError):
                self.route.app_binding(app, self.context["selected"])
            policy.set_consent(
                config,
                True,
                now=100.0,
                provider="claude",
                destination="Anthropic",
                content=policy.CONTENT_VERSION,
            )
            original = self.route.app_binding(app, self.context["selected"])
            self.assertRegex(original, r"^[0-9a-f]{64}$")
            with mock.patch.object(_route.platform, "system", return_value="Windows"):
                self.assertEqual("", _route.destination("claude"))
                with self.assertRaisesRegex(
                    self.route.RefusalError, "provider, model or privatePATH"
                ):
                    self.route.app_binding(app, self.context["selected"])
            source.write_text(
                source.read_text()
                + json.dumps(
                    {"type": "assistant", "sessionId": full, "message": {"content": "work changed"}}
                )
                + "\n"
            )
            self.assertNotEqual(original, self.route.app_binding(app, self.context["selected"]))
            row["resume_id"] = "different-session"
            with self.assertRaises(self.route.RefusalError):
                self.route.app_binding(app, self.context["selected"])

    def test_verified_transport_probe_uses_captured_native_executor_and_closes_copy(self) -> None:
        from types import SimpleNamespace  # noqa: PLC0415 - test-only verified native identity

        self.route._runtime()
        import score_abstention as scorer  # noqa: PLC0415 - genuine binary and argv helpers

        config = SimpleNamespace(claude_reading_model="claude-sonnet-5-5")
        verified = mock.MagicMock()
        verified.identity = (1, 2, 3, 4, 5, "2" * 64)
        context = mock.MagicMock()
        context.__enter__.return_value = verified
        captured_native = object()
        with (
            mock.patch.object(scorer, "verify_claude_binary", return_value=context),
            mock.patch.object(scorer, "file_identity", return_value=verified.identity),
            mock.patch.object(scorer, "argv_digest", return_value="3" * 64) as argv,
            mock.patch.object(
                self.route.shutil, "which", return_value=str(self.root / "native-cli")
            ),
            mock.patch.object(self.route._runtime()[4], "destination", return_value="Anthropic"),
        ):
            bound = self.route.transport_binding(config, claude_executor=captured_native)
        self.assertEqual(self.body["transport"], bound)
        argv.assert_called_once_with("claude", config, claude_executor=captured_native)
        context.__exit__.assert_called_once()


class GenuineQualificationAdmission(unittest.TestCase):
    route: ClassVar[Any]
    fixture: ClassVar[Any]
    current: ClassVar[Any]
    result_path: ClassVar[Path]
    summary: ClassVar[dict[str, Any]]
    original_native: ClassVar[bytes]
    original_shared: ClassVar[bytes]

    @classmethod
    def setUpClass(cls) -> None:
        if TYPE_CHECKING:
            from tests import (  # noqa: PLC0415 - actual bounded qualification fixtures
                test_analyze_campaign as acceptance,
            )
            from tests import (  # noqa: PLC0415 - actual bounded qualification fixtures
                test_qualification_conditional_priority as precursor,
            )
        else:
            import test_analyze_campaign as acceptance  # noqa: PLC0415 - test-only precursor
            import test_qualification_conditional_priority as precursor  # noqa: PLC0415 - actual finite authority fixture

        cls.route = importlib.import_module("claude_route_verification")
        canonical_tmp = mock.patch("tempfile.tempdir", str(Path(tempfile.gettempdir()).resolve()))
        canonical_tmp.start()
        cls.addClassCleanup(canonical_tmp.stop)
        cls.addClassCleanup(precursor.QualificationConditionalPriority.doClassCleanups)
        precursor.QualificationConditionalPriority.setUpClass()
        cls.fixture = precursor.QualificationConditionalPriority()
        cls.fixture.setUp()
        cls.addClassCleanup(cls.fixture.doCleanups)
        original_result_path = cls.route.ledger.result_path
        patch = mock.patch.object(
            cls.route.ledger,
            "result_path",
            side_effect=lambda n: str(Path(original_result_path(n)).resolve()),
        )
        patch.start()
        cls.addClassCleanup(patch.stop)
        binding = {
            "producer": "claude",
            "model": "claude-sonnet-5-5",
            "destination": "Anthropic",
            "binary": "synthetic-native",
            "binary_sha256": "2" * 64,
            "argv_digest": "3" * 64,
            "cli_version": "synthetic-version",
            "signature": "synthetic-test-only",
        }
        import score_abstention as scorer  # noqa: PLC0415 - qualified native provenance keys

        cls.fixture.model_key = cls.route.digest(
            {key: binding.get(key) for key in scorer.BINDING_KEYS}
        )
        cls.fixture.manifest["protocols"]["qualification"] = "closure-three-repeats"
        cls.fixture.manifest["evidence"]["qualification"].update(
            source=cls.route.campaigns.runtime_source_digest(
                cls.route.ROOT / "compass/skills/compass/compass_runtime"
            ),
            scorer=cls.route.sha(Path(scorer.__file__).read_bytes()),
        )
        cls.fixture.binding = cls.route.digest(
            {
                k: v
                for k, v in cls.fixture.manifest.items()
                if k not in ("phase", "activation_anchor")
            }
        )
        cls.fixture.next_path.write_text(json.dumps(cls.fixture.manifest))
        cls.fixture.grant["conditional_priority_allowance"]["campaign_binding"] = (
            cls.fixture.binding
        )
        cls.fixture.grant["conditional_priority_allowance"]["model_binding"] = cls.fixture.model_key
        cls.fixture.native_fixture.grant_paths[8].write_text(json.dumps(cls.fixture.grant))
        cls.fixture.handoff["successor"].update(
            model_binding=cls.fixture.model_key,
            manifest_digest=cls.fixture.binding,
            evidence=cls.fixture.manifest["evidence"]["qualification"],
            grant_digest=cls.route.digest(cls.fixture.grant),
        )
        cls.fixture.write_handoff()
        cls.current = cls.fixture.activate()
        native = cls.fixture.native(cls.current)
        cls.seed_qualified_epoch(native)
        for number in range(len(cls.current.manifest["batches"]["qualification"])):
            cls.current.review_batch(
                "qualification", number, cls.fixture.measurement(cls.current, number)
            )
        cls.result_path = cls.fixture.native_fixture.result_paths[8]
        cls.summary = {
            **binding,
            "v": 2,
            "protocol": "closure-three-repeats",
            "producer": "claude",
            "verdict": "passed",
            "stopped": False,
            "model": "claude-sonnet-5-5",
            "destination": "Anthropic",
            "binary_sha256": "2" * 64,
            "argv_digest": "3" * 64,
            "ledger_chain": cls.route.ledger.chain_of(native.path),
            "counts": {
                "unique_cases": 10,
                "registered_exposures": 30,
                "attempts": 31,
                "unusable_attempts": 1,
            },
            "repetitions": [
                {
                    "repeat": n,
                    "summary": {
                        "verdict": "passed",
                        "coverage": {"claude": {"kinds": 5, "missing": [], "role": "scored"}},
                        "counts": {"cases": 10, "reached_model": 10},
                    },
                }
                for n in (1, 2, 3)
            ],
        }
        cls.result_path.write_text(json.dumps(cls.summary))
        proof = acceptance.acceptance(cls.current, "qualification")
        proof["output_digest"] = cls.route.sha(cls.result_path.read_bytes())
        cls.current.accept("qualification", proof)
        cls.original_native = cls.fixture.native_fixture.ledger_path.read_bytes()
        cls.original_shared = cls.fixture.statepath.read_bytes()

    @classmethod
    def seed_qualified_epoch(cls, native: Any) -> None:
        """Declare only the post-qualified unit-fixture phase, then validate real joins.

        Financial/scorer controls elsewhere perform every real charge and seal.
        These synthetic receipts are not model evidence or public qualification.
        No production snapshot or source/receipt validation is patched or cached.
        """
        import uuid  # noqa: PLC0415 - synthetic immutable receipt identities

        shared = json.loads(cls.fixture.statepath.read_bytes())
        state = shared["epochs"][4]["state"]
        body = cls.route.ledger.read(native.path)
        original_prefix = copy.deepcopy(body["calls"])
        slots = cls.current.manifest["slots"]["qualification"]
        declared = [
            (slots[0], False, "unusable"),
            *[(slot, slot == slots[0], "usable") for slot in slots],
        ]
        cls.current.receipts.mkdir(mode=0o700)
        for index, (slot, retry, status) in enumerate(declared):
            case, repeat = slot.split(":r")
            shared_id = uuid.uuid4().hex
            call = {
                "id": shared_id,
                "at": 100.0 + index,
                "lane": "qualification",
                "slot": slot,
                "binding": cls.current.manifest["requests"]["qualification"][slot],
                "retry": retry,
                "availability_attempt": index + 1 if index < 2 else 0,
                "status": status,
            }
            state["calls"].append(call)
            (cls.current.receipts / (shared_id + ".json")).write_text(
                json.dumps(cls.route.campaigns._receipt(call))
            )
            (cls.current.receipts / (shared_id + "-SETTLED.json")).write_text(
                json.dumps(
                    {"id": shared_id, "status": status, "manifest_digest": cls.current.binding}
                )
            )
            body["calls"].append(
                {
                    "id": uuid.uuid4().hex,
                    "at": call["at"],
                    "case": case,
                    "producer": "claude",
                    "status": "unavailable" if status == "unusable" else "ok",
                    "marks_digest": native.marks_digest,
                    "inputs_digest": native.inputs_digest,
                    "repeat": int(repeat),
                    "retry": retry,
                    "campaign_charge": shared_id,
                }
            )
        cls.fixture.statepath.write_text(json.dumps(shared))
        Path(native.path).write_text(json.dumps(body))
        cls.route.ledger.read(native.path)
        cls.current._state()
        assert original_prefix == cls.route.ledger.read(native.path)["calls"][:38]
        assert len(cls.current._state()["calls"]) == 31

    def tearDown(self) -> None:
        self.result_path.write_text(json.dumps(self.summary))
        self.fixture.statepath.write_bytes(self.original_shared)
        self.fixture.native_fixture.ledger_path.write_bytes(self.original_native)

    def test_actual_finite_campaign_admits_three_passes_and_preserves_original_accounts(
        self,
    ) -> None:
        before_native = self.fixture.native_fixture.ledger_path.read_bytes()
        before_shared = self.fixture.statepath.read_bytes()
        snapshot = self.route.qualification_snapshot()
        self.assertEqual(69, snapshot["native_calls"])
        self.assertEqual(41, snapshot["shared_calls"])
        self.assertEqual(31, snapshot["qualification_calls"])
        self.assertEqual(before_native, self.fixture.native_fixture.ledger_path.read_bytes())
        self.assertEqual(before_shared, self.fixture.statepath.read_bytes())

    def test_public_pass_without_a_third_complete_recorded_kind_pass_is_refused(self) -> None:
        body = copy.deepcopy(self.summary)
        body["repetitions"][2]["summary"]["coverage"]["claude"]["kinds"] = 4
        self.result_path.write_text(json.dumps(body))
        with self.assertRaises(self.route.RefusalError):
            self.route.qualification_snapshot()

    def test_a_semantic_failure_cannot_arm_despite_claimed_pass_and_acceptance(self) -> None:
        stopped = copy.deepcopy(self.current._state())
        stopped["calls"][1]["status"] = "semantic-failed"
        with (
            mock.patch.object(self.current, "_state", return_value=stopped),
            mock.patch.object(
                self.route.campaigns, "ConditionalPriorityCampaign", return_value=self.current
            ),
            self.assertRaises(self.route.RefusalError),
        ):
            self.route.qualification_snapshot()

    def test_explicit_protection_stop_cannot_arm_a_previously_accepted_qualification(self) -> None:
        self.current.stop("protection-failed")
        try:
            with self.assertRaises(self.route.RefusalError):
                self.route.qualification_snapshot()
        finally:
            (self.current.receipts / "STOP.json").unlink()
            self.fixture.statepath.write_bytes(self.original_shared)

    def test_a_published_pass_cannot_replace_missing_independent_lane_acceptance(self) -> None:
        statepath = self.fixture.statepath
        body = json.loads(statepath.read_bytes())
        del body["epochs"][4]["state"]["accepted"]["qualification"]
        statepath.write_text(json.dumps(body))
        with self.assertRaises(self.route.RefusalError):
            self.route.qualification_snapshot()

    def test_native_current_prefix_cannot_be_replaced_by_a_shared_hash_claim(self) -> None:
        path = self.fixture.native_fixture.ledger_path
        body = json.loads(path.read_bytes())
        body["calls"][38]["campaign_charge"] = body["calls"][39]["campaign_charge"]
        path.write_text(json.dumps(body))
        summary = copy.deepcopy(self.summary)
        summary["ledger_chain"] = self.route.ledger.chain_of(str(path))
        self.result_path.write_text(json.dumps(summary))
        with self.assertRaises(self.route.RefusalError):
            self.route.qualification_snapshot()

    def test_a_different_summary_model_cannot_replace_the_native_grant_identity(self) -> None:
        summary = copy.deepcopy(self.summary)
        summary["model"] = "claude-opus-5-5"
        self.result_path.write_text(json.dumps(summary))
        with self.assertRaises(self.route.RefusalError):
            self.route.qualification_snapshot()

    def test_lane_acceptance_must_bind_actual_public_summary_bytes(self) -> None:
        path = self.current.receipts / "qualification-ACCEPTED.json"
        original = path.read_bytes()
        body = json.loads(original)
        body["output_digest"] = "0" * 64
        path.write_text(json.dumps(body))
        statepath = self.fixture.statepath
        state = json.loads(statepath.read_bytes())
        state["epochs"][4]["state"]["accepted"]["qualification"] = self.route.digest(body)
        statepath.write_text(json.dumps(state))
        try:
            with self.assertRaises(self.route.RefusalError):
                self.route.qualification_snapshot()
        finally:
            path.write_bytes(original)

    def test_changed_current_runtime_cannot_inherit_the_old_qualified_seal(self) -> None:
        with (
            mock.patch.object(self.route.campaigns, "runtime_source_digest", return_value="0" * 64),
            self.assertRaises(self.route.RefusalError),
        ):
            self.route.qualification_snapshot()

    def test_changed_current_scorer_cannot_inherit_the_old_qualified_seal(self) -> None:
        import score_abstention as scorer  # noqa: PLC0415 - exact qualified source

        original = Path.read_bytes
        scorerpath = Path(scorer.__file__)

        def changed(path: Path) -> bytes:
            return b"test-only changed scorer" if path == scorerpath else original(path)

        with (
            mock.patch.object(Path, "read_bytes", changed),
            self.assertRaises(self.route.RefusalError),
        ):
            self.route.qualification_snapshot()

    def test_source_gate_refuses_unknown_evidence_fields_hashes_and_protocol(self) -> None:
        # Isolate this source admission check after genuine ledger validation.
        # Otherwise campaign validation would mask the route's own missing gate.
        accepted_state = self.current._state()
        original = copy.deepcopy(self.current.manifest)
        for mutation in ("extra", "missing", "hash", "protocol"):
            altered = copy.deepcopy(original)
            evidence = altered["evidence"]["qualification"]
            if mutation == "extra":
                evidence["unknown"] = "a" * 64
            elif mutation == "missing":
                del evidence["marks"]
            elif mutation == "hash":
                evidence["marks"] = "not-a-digest"
            else:
                altered["protocols"]["qualification"] = "unknown-protocol"
            with (
                self.subTest(mutation=mutation),
                mock.patch.object(self.current, "manifest", altered),
                mock.patch.object(self.current, "_state", return_value=accepted_state),
                mock.patch.object(
                    self.route.campaigns, "ConditionalPriorityCampaign", return_value=self.current
                ),
                self.assertRaises(self.route.RefusalError),
            ):
                self.route.qualification_snapshot()
