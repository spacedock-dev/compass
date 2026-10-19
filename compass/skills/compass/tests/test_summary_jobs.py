"""Summary jobs use recorded replies and a budget independent of Analyze."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    io as runtime_io,
)
from compass_runtime import (
    observer,
    reading,
    reading_jobs,
    reading_policy,
    reading_route,
    session_source,
    session_summary,
    summary_jobs,
    summary_store,
    supervise,
)

from .support import make_runtime
from .test_session_summary import Replies, entry


def wait_job(application: Any, harness: str, sid: str, *, timeout: float) -> None:
    job = application.state.summary_jobs[f"{harness}:{sid}"]
    job.thread.join(timeout)
    if job.thread.is_alive():
        raise TimeoutError("Summary job did not finish")


class _SummaryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, self.state = make_runtime(
            state_home=self.home.name, state_dir=Path(self.home.name)
        )
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)


class SummaryGrantTest(_SummaryCase):
    def test_summary_off_survives_restart_without_changing_reading_or_goal_answers(self) -> None:
        reading_policy.note(
            self.config,
            kind="goal",
            provider="codex",
            destination="OpenAI",
            content=4,
            tool_output="",
            now=100.0,
        )
        before = reading_policy.status(self.config, now=100.0)
        self.assertTrue(reading_policy.summary_status(self.config, now=100.0)["consent"])
        reading_policy.set_summary_consent(self.config, False, now=101.0)
        restarted, _ = make_runtime(state_home=self.home.name, state_dir=Path(self.home.name))
        self.assertEqual(
            "summaries-off", reading_policy.summary_status(restarted, now=102.0)["reason"]
        )
        self.assertEqual(before, reading_policy.status(restarted, now=100.0))
        reading_policy.set_summary_consent(restarted, True, now=103.0)
        self.assertEqual(before, reading_policy.status(restarted, now=100.0))

    def test_turning_on_an_already_on_summary_does_not_revoke_a_running_grant(self) -> None:
        initial = reading_policy.summary_status(self.config, now=100.0)
        notice = reading_policy.note(
            self.config,
            kind="summary",
            provider="claude",
            destination="Anthropic",
            content=1,
            tool_output="",
            now=100.0,
        )
        answer = reading_policy.set_summary_consent(self.config, True, now=101.0)
        self.assertEqual(initial.get("generation", 0), answer.get("generation", 0))
        self.assertEqual(notice, answer["notices"]["summary"]["claude"])

    def test_idempotent_summary_receipts_and_separate_rolling_cap(self) -> None:
        config = dataclasses.replace(self.config, session_summary_rolling_cap=2)
        for receipt in ("one", "one", "two"):
            self.assertEqual(
                "", reading_policy.reserve_summary(config, now=100.0, receipt=receipt)["reason"]
            )
        self.assertEqual(
            "daily-cap",
            reading_policy.reserve_summary(config, now=101.0, receipt="three")["reason"],
        )
        self.assertEqual(2, reading_policy.summary_status(config, now=101.0)["used"])
        self.assertEqual(0, reading_policy.status(config, now=101.0)["used"])
        self.assertEqual(86500.0, reading_policy.summary_status(config, now=101.0)["retry_at"])
        self.assertEqual(
            "", reading_policy.reserve_summary(config, now=86501.0, receipt="four")["reason"]
        )

    def test_summary_notice_is_independent_of_readings_and_repeats_for_destination_or_content(
        self,
    ) -> None:
        args: dict[str, Any] = {
            "kind": "summary",
            "provider": "claude",
            "destination": "Anthropic",
            "content": 1,
            "tool_output": "",
            "now": 100.0,
        }
        self.assertIsNotNone(reading_policy.note(self.config, **args))
        self.assertIsNone(reading_policy.note(self.config, **args))
        reading_policy.set_consent(self.config, False, now=101.0)
        # Model calls paused refuses summaries too, so nothing new is due, but their record stays.
        self.assertIsNone(
            reading_policy.note(self.config, **{**args, "destination": "gateway.example"})
        )
        reading_policy.set_consent(self.config, True, now=101.5)
        self.assertIsNone(reading_policy.note(self.config, **args))
        self.assertIsNotNone(
            reading_policy.note(self.config, **{**args, "destination": "gateway.example"})
        )
        self.assertIsNotNone(
            reading_policy.note(
                self.config, **{**args, "destination": "gateway.example", "content": 2}
            )
        )

    def test_run_disabled_refuses_summary_charge(self) -> None:
        answer = reading_policy.reserve_summary(
            dataclasses.replace(self.config, model_calls_disabled=True), now=100.0, receipt="one"
        )
        self.assertEqual("run-disabled", answer["reason"])
        self.assertEqual(0, reading_policy.summary_status(self.config, now=100.0)["used"])


class SummaryJobTest(_SummaryCase):
    def setUp(self) -> None:
        super().setUp()
        self.jobs = summary_jobs
        self.application: Any = type("Application", (), {})()
        self.application.config = dataclasses.replace(self.config, session_summary_window_bytes=150)
        self.config = self.application.config
        self.application.state = self.state
        self.application.clock = lambda: 100.0
        self.application.diagnostic_sink = lambda _: None
        self.application.collect_json = lambda **_: (0, b"{}")
        self.entries = tuple(
            entry(n, words="Request " + str(n) + " " + "x" * 100) for n in range(1, 4)
        )
        self.coverage = session_source.SourceCoverage(True, None, 0, 100, (), "read", "read")
        self.page = session_source.SourcePage(
            "ok",
            "claude",
            "s1",
            self.entries,
            self.coverage,
            snapshot=session_source.SourceSnapshot(
                (1, 2, 100, 4),
                100,
                "a" * 64,
                tuple((e.fact_id, e.fingerprint, e.at) for e in self.entries),
                {},
                (),
                session_source.SourceCursor("identity", ()),
            ),
        )

    def run_job(self, model: Any = None) -> Any:
        code, answer = self.jobs.start(
            self.application,
            self.page,
            action="start",
            model=model or Replies(),
            destination="Anthropic",
        )
        self.assertEqual(202, code, answer)
        wait_job(self.application, "claude", "s1", timeout=5)
        return answer

    def assert_finished_prefix(self, summary: Any) -> None:
        """The first part's phases are kept and every later entry is named as a gap.

        The stored snapshot covers the whole read, so a prefix without the gap would compare
        as unchanged while lacking its newest entries.
        """
        first, *rest = summary.blocks
        self.assertTrue(first.phases)
        self.assertTrue(rest)
        self.assertTrue(all(block.reason for block in rest))
        self.assertEqual(self.entries[-1].fact_id, rest[-1].last)
        self.assertEqual(len(self.entries), sum(block.entries for block in summary.blocks))

    def test_first_run_notices_once_and_charges_each_part_without_analyze(self) -> None:
        first = self.run_job()
        self.assertEqual("summary", first["notice"]["kind"])
        stored = summary_store.get(self.config, "claude", "s1")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(3, len(stored.summary.blocks))
        self.assertEqual(4, reading_policy.summary_status(self.config, now=100.0)["used"])
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])
        self.assertNotIn("notice", self.run_job())

    def test_pausing_before_each_part_sends_no_more_session_text(self) -> None:
        for part in range(1, 5):
            with self.subTest(part=part):
                reading_policy.set_consent(self.config, True, now=100.0)
                replies = Replies()

                def pause(*, stop_at: int = part, **_: Any) -> tuple[int, bytes]:
                    current = self.state.summary_jobs.get("claude:s1")
                    if current is not None and current.attempts == stop_at:
                        reading_policy.set_consent(self.config, False, now=100.0)
                    return 0, b"{}"

                self.application.collect_json = pause
                self.run_job(replies)
                self.assertEqual(part - 1, len(replies.prompts))
                self.assertEqual("model-calls-paused", self.state.summary_jobs["claude:s1"].reason)

    def test_cancel_keeps_finished_parts_and_rejects_inflight_reply(self) -> None:
        entered, release = threading.Event(), threading.Event()
        replies = Replies()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            if replies.prompts:
                entered.set()
                self.assertTrue(release.wait(5))
            return replies(prompt, output_cap_bytes=output_cap_bytes)

        code, _ = self.jobs.start(
            self.application, self.page, action="start", model=model, destination="Anthropic"
        )
        self.assertEqual(202, code)
        self.assertTrue(entered.wait(5))
        try:
            self.assertTrue(self.jobs.cancel(self.application, "claude", "s1"))
        finally:
            release.set()
        wait_job(self.application, "claude", "s1", timeout=5)
        stored = summary_store.get(self.config, "claude", "s1")
        assert stored is not None
        self.assert_finished_prefix(stored.summary)
        job = self.jobs.published(self.application, "claude", "s1")
        assert job is not None
        self.assertEqual(("cancelled", [1]), (job["reason"], job["finished_parts"]))

    def test_off_then_on_does_not_allow_a_late_reply(self) -> None:
        entered, release = threading.Event(), threading.Event()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            entered.set()
            self.assertTrue(release.wait(5))
            return Replies()(prompt, output_cap_bytes=output_cap_bytes)

        code, _ = self.jobs.start(
            self.application, self.page, action="start", model=model, destination="Anthropic"
        )
        self.assertEqual(202, code)
        self.assertTrue(entered.wait(5))
        reading_policy.set_summary_consent(self.config, False, now=101.0)
        reading_policy.set_summary_consent(self.config, True, now=102.0)
        release.set()
        wait_job(self.application, "claude", "s1", timeout=5)
        self.assertIsNone(summary_store.get(self.config, "claude", "s1"))
        job = self.jobs.published(self.application, "claude", "s1")
        assert job is not None
        self.assertEqual("grant-changed", job["reason"])

    def test_plan_refuses_before_any_call_or_charge(self) -> None:
        self.application.config = dataclasses.replace(self.config, session_summary_max_calls=1)
        model = Replies()
        code, answer = self.jobs.start(
            self.application, self.page, action="start", model=model, destination="Anthropic"
        )
        self.assertEqual(422, code)
        self.assertEqual("planned_calls", answer["reason"])
        self.assertEqual([], model.prompts)
        self.assertIn("largest_read", answer)
        self.assertEqual(0, reading_policy.summary_status(self.config, now=100.0)["used"])

    def test_incremental_callback_keeps_the_existing_producer_result(self) -> None:
        results: list[Any] = []
        prior = session_summary.summarize(
            self.entries,
            self.coverage,
            "claude",
            config=self.config,
            model=Replies(),
            clock=lambda: 0.0,
        )
        result = session_summary.summarize(
            self.entries,
            self.coverage,
            "claude",
            config=self.config,
            model=Replies(),
            clock=lambda: 0.0,
            on_part=lambda summary, part, parts: results.append((summary, part, parts)),
        )
        self.assertEqual(prior, result)
        self.assertEqual([0, 1, 2, 3, 4], [r[1] for r in results])
        self.assertTrue(all(r[2] == 4 for r in results))

    def test_delete_rejects_inflight_reply_and_keeps_the_store_empty(self) -> None:
        entered, release = threading.Event(), threading.Event()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            entered.set()
            self.assertTrue(release.wait(5))
            return Replies()(prompt, output_cap_bytes=output_cap_bytes)

        code, _ = self.jobs.start(
            self.application, self.page, action="start", model=model, destination="Anthropic"
        )
        self.assertEqual(202, code)
        self.assertTrue(entered.wait(5))
        self.jobs.delete(self.application, "claude", "s1")
        release.set()
        wait_job(self.application, "claude", "s1", timeout=5)
        self.assertIsNone(summary_store.get(self.config, "claude", "s1"))
        self.assertEqual("deleted", self.state.summary_jobs["claude:s1"].reason)

    def test_revoke_between_parts_keeps_finished_prefix_and_makes_no_next_call(self) -> None:
        replies = Replies()
        real_put = summary_store.put

        def put(*args: Any, **kwargs: Any) -> str:
            result = real_put(*args, **kwargs)
            reading_policy.set_summary_consent(self.config, False, now=101.0)
            return result

        with mock.patch.object(summary_store, "put", side_effect=put):
            self.run_job(replies)
        stored = summary_store.get(self.config, "claude", "s1")
        assert stored is not None
        self.assert_finished_prefix(stored.summary)
        self.assertEqual(1, len(replies.prompts))
        self.assertEqual("summaries-off", self.state.summary_jobs["claude:s1"].reason)

    def test_cap_stops_before_next_part_and_keeps_completed_parts(self) -> None:
        self.config = dataclasses.replace(self.config, session_summary_rolling_cap=1)
        self.application.config = self.config
        replies = Replies()
        self.run_job(replies)
        stored = summary_store.get(self.config, "claude", "s1")
        assert stored is not None
        self.assert_finished_prefix(stored.summary)
        self.assertEqual("daily-cap", self.state.summary_jobs["claude:s1"].reason)
        self.assertEqual(1, len(replies.prompts))
        # The producer's final result is saved after the cap stopped it, not only the prefix.
        job = self.state.summary_jobs["claude:s1"]
        self.assertIn(job.parts, job.finished_parts)
        self.assertEqual("refused", stored.summary.reason)

    def test_restart_reports_finished_parts_without_resuming(self) -> None:
        entered, release = threading.Event(), threading.Event()
        replies = Replies()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            if replies.prompts:
                entered.set()
                self.assertTrue(release.wait(5))
            return replies(prompt, output_cap_bytes=output_cap_bytes)

        code, _ = self.jobs.start(
            self.application, self.page, action="start", model=model, destination="Anthropic"
        )
        self.assertEqual(202, code)
        self.assertTrue(entered.wait(5))
        directory = self.config.state_dir / self.jobs.MARKER_DIR
        path = next(directory.glob("*.json"))
        marker = json.loads(path.read_text())
        try:
            self.jobs.cancel(self.application, "claude", "s1")
        finally:
            release.set()
        wait_job(self.application, "claude", "s1", timeout=5)
        marker["pid"] = 999999
        path.write_text(json.dumps(marker))
        _, restarted = make_runtime(state_home=self.home.name, state_dir=Path(self.home.name))
        self.application.state = restarted
        self.assertEqual(1, self.jobs.recover(self.application, alive=lambda _: False))
        answer = self.jobs.published(self.application, "claude", "s1")
        assert answer is not None
        self.assertEqual(
            ("interrupted", "interrupted", [1]),
            (answer["state"], answer["reason"], answer["finished_parts"]),
        )
        self.assertEqual(0, self.jobs.recover(self.application, alive=lambda _: False))
        stored = summary_store.get(self.config, "claude", "s1")
        assert stored is not None
        self.assert_finished_prefix(stored.summary)
        self.assertEqual(2, reading_policy.summary_status(self.config, now=100.0)["used"])

    def test_bytes_and_seconds_plans_refuse_before_spending(self) -> None:
        for bound in ({"session_summary_max_bytes_sent": 1}, {"session_summary_max_seconds": 1.0}):
            self.application.config = dataclasses.replace(self.config, **bound)
            replies = Replies()
            code, answer = self.jobs.start(
                self.application, self.page, action="start", model=replies, destination="Anthropic"
            )
            self.assertEqual(422, code)
            self.assertIn(answer["reason"], {"planned_bytes", "planned_seconds"})
            self.assertEqual([], replies.prompts)
        self.assertEqual(0, reading_policy.summary_status(self.config, now=100.0)["used"])

    def test_analyze_and_summary_run_on_same_session_with_independent_slots(self) -> None:
        entered, release = threading.Event(), threading.Event()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            entered.set()
            self.assertTrue(release.wait(5))
            return Replies()(prompt, output_cap_bytes=output_cap_bytes)

        code, _ = self.jobs.start(
            self.application, self.page, action="start", model=model, destination="Anthropic"
        )
        self.assertEqual(202, code)
        self.assertTrue(entered.wait(5))
        analyze = reading.start_job(
            self.config, "claude:s1", provider="claude", label="Claude", now=100.0
        )
        assert analyze is not None

        def compose(hooks: Any) -> Any:
            guarded = reading_policy.GuardedModel(
                self.config,
                lambda *_args, **_kw: ("recorded", "ok"),
                lambda: 100.0,
                provider="claude",
                destination="Anthropic",
                before_reserve=hooks.before_reserve,
                on_reserved=hooks.reserved,
            )
            guarded("synthetic", output_cap_bytes=100)
            return None, reading.WITHHELD_INTERRUPTED, True

        try:
            thread = reading_jobs.launch(self.application, analyze, compose)
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(1, reading_policy.status(self.config, now=100.0)["used"])
            self.assertEqual(1, reading_policy.summary_status(self.config, now=100.0)["used"])
        finally:
            release.set()
            wait_job(self.application, "claude", "s1", timeout=5)

    def test_update_reads_only_new_entries_and_rerun_starts_fresh(self) -> None:
        self.run_job()
        extra = entry(4, words="A new synthetic direction")
        assert self.page.snapshot is not None
        page = dataclasses.replace(
            self.page,
            entries=(*self.entries, extra),
            snapshot=dataclasses.replace(
                self.page.snapshot,
                entries=tuple((e.fact_id, e.fingerprint, e.at) for e in (*self.entries, extra)),
            ),
        )
        model = Replies()
        code, _ = self.jobs.start(
            self.application, page, action="update", model=model, destination="Anthropic"
        )
        self.assertEqual(202, code)
        wait_job(self.application, "claude", "s1", timeout=5)
        self.assertEqual(2, len(model.prompts))
        self.assertTrue(all("Request 1" not in prompt for prompt in model.prompts))
        stored = summary_store.get(self.config, "claude", "s1")
        assert stored is not None
        self.assertEqual(4, len(stored.summary.blocks))
        model = Replies()
        code, _ = self.jobs.start(
            self.application, page, action="rerun", model=model, destination="Anthropic"
        )
        self.assertEqual(202, code)
        wait_job(self.application, "claude", "s1", timeout=5)
        self.assertIn("Request 1", model.prompts[0])

    def test_marker_failure_refuses_without_charge_or_model_call(self) -> None:
        model = Replies()
        with mock.patch.object(
            runtime_io, "atomic_write_owner_only", side_effect=OSError("disk full")
        ):
            code, answer = self.jobs.start(
                self.application, self.page, action="start", model=model, destination="Anthropic"
            )
        self.assertEqual((503, "job-unrecorded"), (code, answer["reason"]))
        self.assertEqual([], model.prompts)
        self.assertEqual(0, reading_policy.summary_status(self.config, now=100.0)["used"])

    def test_summary_exec_uses_its_system_prompt_and_configured_timeout(self) -> None:
        captured: list[Any] = []

        def runner(command: Any, **kwargs: Any) -> Any:
            captured.append((command, kwargs["timeout"]))
            kwargs["stdout"].write(b'{"lede":"A recorded answer","cites":[1]}')
            return SimpleNamespace(returncode=0)

        text, status = observer.claude_exec(
            self.config,
            "synthetic prompt",
            output_cap_bytes=1000,
            runner=runner,
            binary_resolver=lambda _: "/synthetic/claude",
            system_prompt=session_summary.SYSTEM_PROMPT,
            timeout=12.5,
        )
        self.assertEqual("ok", status)
        self.assertIn("A recorded answer", text)
        argv, timeout = captured[0]
        self.assertEqual(session_summary.SYSTEM_PROMPT, argv[argv.index("--system-prompt") + 1])
        self.assertEqual(12.5, timeout)

    def test_destination_change_between_parts_stops_without_a_second_charge(self) -> None:
        model = Replies()
        current = ["Anthropic"]
        real_put = summary_store.put

        def put(*args: Any, **kwargs: Any) -> str:
            result = real_put(*args, **kwargs)
            current[0] = "gateway.example"
            return result

        with (
            mock.patch.object(reading_route, "destination", side_effect=lambda _: current[0]),
            mock.patch.object(summary_store, "put", side_effect=put),
        ):
            self.run_job(model)
        self.assertEqual(1, len(model.prompts))
        self.assertEqual("destination-changed", self.state.summary_jobs["claude:s1"].reason)
        self.assertEqual(1, reading_policy.summary_status(self.config, now=100.0)["used"])

    def test_attempt_receipts_match_calls_including_one_empty_reply_retry(self) -> None:
        model = Replies(("", "unstopped"))
        self.run_job(model)
        job = self.state.summary_jobs["claude:s1"]
        self.assertEqual(5, len(model.prompts))
        self.assertEqual(5, reading_policy.summary_receipts(self.config, job.id))
        self.assertEqual(5, job.attempts)
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])

    def test_summary_off_makes_no_call_until_on_and_no_model_switch_always_refuses(self) -> None:
        model = Replies()
        reading_policy.set_summary_consent(self.config, False, now=100.0)
        for config in (self.config, dataclasses.replace(self.config, model_calls_disabled=True)):
            self.application.config = config
            code, answer = self.jobs.start(
                self.application, self.page, action="start", model=model, destination="Anthropic"
            )
            self.assertIn(code, (403, 503))
            self.assertIn(answer["reason"], ("summaries-off", "run-disabled"))
        self.assertEqual([], model.prompts)
        self.application.config = self.config
        reading_policy.set_summary_consent(self.config, True, now=101.0)
        self.run_job(model)
        self.assertGreater(len(model.prompts), 0)

    def test_summary_off_between_charge_and_model_seam_makes_no_model_call(self) -> None:
        replies = Replies()
        real = reading_jobs._publish
        turned = threading.Event()

        def publish(application: Any) -> None:
            job = self.state.summary_jobs.get("claude:s1")
            if job is not None and job.attempts == 1 and not turned.is_set():
                turned.set()
                self.jobs.set_consent(self.application, False)
            real(application)

        with mock.patch.object(reading_jobs, "_publish", side_effect=publish):
            self.run_job(replies)
        self.assertTrue(turned.is_set())
        self.assertEqual([], replies.prompts)
        self.assertEqual("summaries-off", self.state.summary_jobs["claude:s1"].reason)
        self.assertIsNone(summary_store.get(self.config, "claude", "s1"))

    def test_summary_off_cancels_a_call_already_running(self) -> None:
        entered, cancelled = threading.Event(), threading.Event()

        class Group:
            def cancel(self) -> None:
                cancelled.set()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            del prompt, output_cap_bytes
            self.state.summary_jobs["claude:s1"].group = Group()
            entered.set()
            self.assertTrue(cancelled.wait(5))
            return "", "cancelled"

        code, _ = self.jobs.start(
            self.application, self.page, action="start", model=model, destination="Anthropic"
        )
        self.assertEqual(202, code)
        self.assertTrue(entered.wait(5))
        self.jobs.set_consent(self.application, False)
        self.assertTrue(cancelled.is_set())
        wait_job(self.application, "claude", "s1", timeout=5)
        self.assertEqual("summaries-off", self.state.summary_jobs["claude:s1"].reason)
        self.assertIsNone(summary_store.get(self.config, "claude", "s1"))

    def test_readings_off_refuses_summary_start_and_stops_a_running_job(self) -> None:
        model = Replies()
        reading_policy.set_consent(self.config, False, now=100.0)
        code, answer = self.jobs.start(
            self.application, self.page, action="start", model=model, destination="Anthropic"
        )
        self.assertEqual((403, "model-calls-paused"), (code, answer["reason"]))
        status = reading_policy.summary_status(self.config, now=100.0)
        self.assertEqual((False, False), (status["consent"], status["off"]))
        self.assertEqual([], model.prompts)
        reading_policy.set_consent(self.config, True, now=101.0)
        entered, release = threading.Event(), threading.Event()

        def held(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            entered.set()
            self.assertTrue(release.wait(5))
            return model(prompt, output_cap_bytes=output_cap_bytes)

        code, _ = self.jobs.start(
            self.application, self.page, action="start", model=held, destination="Anthropic"
        )
        self.assertEqual(202, code)
        self.assertTrue(entered.wait(5))
        reading_policy.set_consent(self.config, False, now=102.0)
        self.jobs.stop_running(self.application, "model-calls-paused")
        release.set()
        wait_job(self.application, "claude", "s1", timeout=5)
        self.assertEqual(1, len(model.prompts))
        self.assertEqual("model-calls-paused", self.state.summary_jobs["claude:s1"].reason)
        self.assertIsNone(summary_store.get(self.config, "claude", "s1"))

    def extended_page(self) -> Any:
        extra = entry(4, words="A new synthetic direction")
        assert self.page.snapshot is not None
        return dataclasses.replace(
            self.page,
            entries=(*self.entries, extra),
            snapshot=dataclasses.replace(
                self.page.snapshot,
                entries=tuple((e.fact_id, e.fingerprint, e.at) for e in (*self.entries, extra)),
            ),
        )

    def test_cancelled_update_keeps_the_saved_lede(self) -> None:
        self.run_job()
        before = summary_store.get(self.config, "claude", "s1")
        assert before is not None
        self.assertIsNotNone(before.summary.lede)
        entered, release = threading.Event(), threading.Event()
        replies = Replies()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            if replies.prompts:
                entered.set()
                self.assertTrue(release.wait(5))
            return replies(prompt, output_cap_bytes=output_cap_bytes)

        code, _ = self.jobs.start(
            self.application,
            self.extended_page(),
            action="update",
            model=model,
            destination="Anthropic",
        )
        self.assertEqual(202, code)
        self.assertTrue(entered.wait(5))
        try:
            self.jobs.cancel(self.application, "claude", "s1")
        finally:
            release.set()
        wait_job(self.application, "claude", "s1", timeout=5)
        stored = summary_store.get(self.config, "claude", "s1")
        assert stored is not None
        self.assertEqual(before.summary.lede, stored.summary.lede)
        self.assertIsNone(stored.summary.lede_reason)

    def test_update_after_delete_refuses_instead_of_restoring_deleted_text(self) -> None:
        self.run_job()
        prior = summary_store.get(self.config, "claude", "s1")
        real_get = summary_store.get
        reads = iter([prior])

        def get(*args: Any, **kwargs: Any) -> Any:
            # The first read is the request's own, before Delete summary runs.
            return next(reads, None) or real_get(*args, **kwargs)

        self.jobs.delete(self.application, "claude", "s1")
        model = Replies()
        with mock.patch.object(summary_store, "get", side_effect=get):
            code, answer = self.jobs.start(
                self.application,
                self.extended_page(),
                action="update",
                model=model,
                destination="Anthropic",
            )
        self.assertEqual((422, "no-summary"), (code, answer["reason"]))
        self.assertEqual([], model.prompts)
        self.assertIsNone(summary_store.get(self.config, "claude", "s1"))

    def test_marker_is_removed_when_the_lock_fails_as_the_job_ends(self) -> None:
        failing = threading.Event()
        real = summary_jobs._locked
        replies = Replies()

        def locked(application: Any) -> Any:
            if failing.is_set():
                raise OSError("lock unavailable")
            return real(application)

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            answer = replies(prompt, output_cap_bytes=output_cap_bytes)
            failing.set()
            return answer

        with mock.patch.object(summary_jobs, "_locked", side_effect=locked):
            self.run_job(model)
        self.assertFalse(any((self.config.state_dir / self.jobs.MARKER_DIR).glob("*.json")))
        self.run_job()

    def test_torn_marker_neither_blocks_delete_nor_leaves_the_session_in_flight(self) -> None:
        self.run_job()
        marker = summary_jobs._marker(self.config, "claude", "s1")
        marker.write_text("{torn")
        self.assertEqual("deleted", self.jobs.delete(self.application, "claude", "s1"))
        self.assertIsNone(summary_store.get(self.config, "claude", "s1"))
        self.assertFalse(marker.exists())
        self.run_job()
        marker.write_text("{torn")
        self.assertEqual(0, self.jobs.recover(self.application, alive=lambda _: False))
        self.assertFalse(marker.exists())

    def test_run_disabled_still_reports_a_stored_summary_off(self) -> None:
        reading_policy.set_summary_consent(self.config, False, now=100.0)
        disabled = dataclasses.replace(self.config, model_calls_disabled=True)
        answer = reading_policy.summary_status(disabled, now=100.0)
        self.assertEqual(("run-disabled", True), (answer["reason"], answer["off"]))
        board = summary_jobs.board(disabled, now=100.0)
        self.assertTrue(board["off"])
