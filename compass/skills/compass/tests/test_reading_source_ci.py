"""Historical CI binding is frozen before canonical projection, without live reads."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest import mock

from compass_runtime import ci_read, reading_source
from compass_runtime import project_context as context
from compass_runtime import reading_source_collect as collector
from compass_runtime import reading_source_inventory as inventory

from . import test_reading_source as sources
from .test_claude_checks import REMOTE, SHORT, Transcript


class FrozenCiBindingTest(sources.CompleteReadingSourceFixture):
    def setUp(self) -> None:
        super().setUp()
        self.parent = Transcript(self.root)
        self.parent.prompt("Check the original pull request.")
        self.parent.rows.append({"type": "pr-link", "prRepository": REMOTE[1], "prNumber": 7})
        self.bound = self.parent.bash("gh pr checks 7", "all checks passed")
        self.unbound = self.parent.bash("gh pr checks 8", "all checks passed")
        push = self.parent.call("Bash", {"command": "git push"})
        self.parent.result(
            push,
            "pushed",
            is_error=False,
            tool_use_result={"gitOperation": {"push": {"branch": "fix/widget"}}},
        )
        self.branch = self.parent.bash("gh pr checks fix/widget", "all checks passed")
        created = self.parent.call("Bash", {"command": "gh pr create"})
        self.parent.result(
            created,
            "created",
            is_error=False,
            tool_use_result={
                "gitOperation": {
                    "pr": {
                        "action": "created",
                        "number": 11,
                        "url": f"https://github.com/{REMOTE[1]}/pull/11",
                    }
                }
            },
        )
        self.created_poll = self.parent.bash("gh pr checks 11", "all checks passed")
        self.parent.save(self.path)
        child = Transcript(self.root)
        child.calls, child.seconds = 200, 100
        self.child_poll = child.bash("gh pr checks 7 --watch", "all checks passed")
        # Child PR-link rows must not grant parent binding.
        child.rows.append({"type": "pr-link", "prRepository": REMOTE[1], "prNumber": 8})
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.child_path)

    def collect(self, **options: Any) -> collector.Collection:
        frozen = inventory.freeze(
            str(self.path), "claude", SHORT, max_entries=100, max_streams=10, max_seconds=1
        )
        return collector.collect(
            self.config, frozen, clock=options.pop("clock", lambda: 0.0), **options
        )

    def fact(self, result: Any, call: str) -> Any:
        return next(
            f for f in result.evidence.facts if f.get("branch", {}).get("record_id") == call
        )

    def test_native_parent_link_push_and_child_poll_match_exact_canonical_oracle(self) -> None:
        with mock.patch.object(ci_read, "folder_remote", return_value=REMOTE):
            scan = context._live_check_scan(self.config, str(self.path))
            expected = reading_source.from_complete_scan(self.config, scan, "claude", SHORT)
        project = reading_source.from_complete_scan

        def project_without_io(*args: Any, **options: Any) -> Any:
            with (
                mock.patch.object(
                    ci_read, "folder_remote", side_effect=AssertionError("lazy remote")
                ),
                mock.patch.object(
                    ci_read, "scan_records", side_effect=AssertionError("lazy records")
                ),
            ):
                return project(*args, **options)

        with (
            mock.patch.object(ci_read, "folder_remote", return_value=REMOTE) as remote,
            mock.patch.object(ci_read, "scan_records", side_effect=AssertionError("source reread")),
            mock.patch.object(reading_source, "from_complete_scan", side_effect=project_without_io),
        ):
            result = self.collect(page_bytes=127)
        self.assertEqual("", result.reason)
        assert result.evidence is not None
        self.assertEqual(expected.facts, result.evidence.facts)
        self.assertEqual(expected.press, result.evidence.press)
        for call in (self.bound, self.branch, self.child_poll, self.created_poll):
            self.assertEqual("ci_command", self.fact(result, call)["subject"])
            self.assertFalse(self.fact(result, call).get("cannot_fail", False))
        self.assertEqual("command", self.fact(result, self.unbound)["subject"])
        self.assertTrue(self.fact(result, self.unbound)["cannot_fail"])
        self.assertEqual(1, remote.call_count)
        self.assertEqual("available", result.ancillary_info.ci_binding)
        self.assertEqual(1, result.ancillary_info.remote_probes)

    def test_genuine_goal_link_binds_without_promoting_child_link(self) -> None:
        with mock.patch.object(ci_read, "folder_remote", return_value=REMOTE):
            result = self.collect(goal_texts=(f"Review https://github.com/{REMOTE[1]}/pull/8",))
        self.assertEqual("ci_command", self.fact(result, self.unbound)["subject"])
        self.assertEqual("available", result.ancillary_info.ci_binding)

    def test_wrong_repository_cwd_missing_remote_and_no_git_remain_unbound(self) -> None:
        other = self.root / "other"
        other.mkdir()
        wrong_repo = self.parent.bash("gh pr checks 7 --repo wrong/repository", "passed")
        wrong_cwd = self.parent.bash(f"cd {other} && gh pr checks 7", "passed")
        self.parent.save(self.path)

        def remote(_config: Any, cwd: str, *_args: Any) -> Any:
            return ("github.com", "wrong/repository") if cwd == str(other) else REMOTE

        with mock.patch.object(ci_read, "folder_remote", side_effect=remote):
            result = self.collect()
        self.assertTrue(self.fact(result, wrong_repo)["cannot_fail"])
        self.assertTrue(self.fact(result, wrong_cwd)["cannot_fail"])
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                self.config = replace(self.config, git_probe_enabled=enabled)
                with mock.patch.object(ci_read, "folder_remote", return_value=("", "")) as probe:
                    result = self.collect()
                self.assertEqual(
                    "unknown" if enabled else "disabled", result.ancillary_info.ci_binding
                )
                self.assertTrue(self.fact(result, self.bound)["cannot_fail"])
                if not enabled:
                    probe.assert_not_called()

    def test_probe_cap_and_remaining_full_timeout_are_explicit(self) -> None:
        with mock.patch.object(ci_read, "folder_remote", side_effect=AssertionError("probe cap")):
            result = self.collect(ci_remote_limit=0)
        self.assertEqual("unknown", result.ancillary_info.ci_binding)
        self.assertEqual(0, result.ancillary_info.remote_probes)
        self.assertTrue(self.fact(result, self.bound)["cannot_fail"])
        with mock.patch.object(
            ci_read, "folder_remote", side_effect=AssertionError("timeout room")
        ):
            result = self.collect(limits=replace(collector.Limits(), prepare_ms=9999))
        self.assertEqual("time", result.reason)
        self.assertIsNone(result.evidence)
        self.assertEqual(0, result.ancillary_info.remote_probes)

    def test_cancel_after_probe_and_goal_graph_limit_withhold_evidence(self) -> None:
        stopped = False

        def remote(*_args: Any) -> Any:
            nonlocal stopped
            stopped = True
            return REMOTE

        with mock.patch.object(ci_read, "folder_remote", side_effect=remote):
            result = self.collect(cancelled=lambda: stopped)
        self.assertEqual("cancelled", result.reason)
        self.assertIsNone(result.evidence)
        self.assertEqual(1, result.ancillary_info.remote_probes)
        with mock.patch.object(
            ci_read, "folder_remote", side_effect=AssertionError("unadmitted goals")
        ):
            result = self.collect(
                goal_texts=("x" * 100_000,),
                limits=replace(collector.Limits(), retained_bytes=90_000),
            )
        self.assertEqual("retained_bytes", result.reason)
        self.assertEqual(0, result.usage.source_bytes)

    def test_retained_record_validators_keep_order_caps_and_invalid_rejections(self) -> None:
        self.assertTrue(hasattr(ci_read, "records_from_rows"))
        rows = [
            {"type": "pr-link", "prRepository": REMOTE[1], "prNumber": number}
            for number in range(1, 46)
        ]
        rows += [
            {"type": "pr-link", "prRepository": REMOTE[1], "prNumber": True},
            {"toolUseResult": {"gitOperation": {"push": {"branch": "--bad"}}}},
            {"toolUseResult": {"gitOperation": {"push": {"branch": "fix/last"}}}},
        ]
        links, pushes = ci_read.records_from_rows(reversed(rows))
        self.assertEqual(tuple((REMOTE[1], n) for n in range(45, 5, -1)), links)
        self.assertEqual(("fix/last",), pushes)

    def test_retained_historical_window_keeps_the_existing_byte_bound(self) -> None:
        with (
            mock.patch.object(ci_read, "SCAN_BYTES", 128),
            mock.patch.object(ci_read, "folder_remote", return_value=REMOTE),
        ):
            scan = context._live_check_scan(self.config, str(self.path))
            expected = reading_source.from_complete_scan(self.config, scan, "claude", SHORT)
            with mock.patch.object(ci_read, "scan_records", side_effect=AssertionError("reread")):
                result = self.collect()
        assert result.evidence is not None
        self.assertEqual(expected.facts, result.evidence.facts)
        self.assertEqual(expected.press, result.evidence.press)
        self.assertTrue(self.fact(result, self.bound)["cannot_fail"])
        self.assertTrue(self.fact(result, self.branch)["cannot_fail"])
        # Structured creation remains the same canonical tally evidence; it
        # does not pretend the separately capped native link window included it.
        self.assertEqual("ci_command", self.fact(result, self.created_poll)["subject"])
