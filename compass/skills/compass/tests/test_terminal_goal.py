"""A person reads and edits intent through the page's own store and adoption route.

Transcripts use the captured tool shapes in test_claude_checks and /goal shapes in
test_session_goal. HTTP payloads are produced by the real server, never authored here.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    claude_data,
    footer_lines,
    http_api,
    reading,
    terminal_client,
    terminal_drift,
    terminal_goal,
)

from .support import SERVER_PATH
from .test_claude_checks import SHORT, SID, START
from .test_live_lease_http import LeaseRoute
from .test_session_goal import CONDITION, set_goal


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class APersonUsesTheirGoal(LeaseRoute):
    def app(self, **row: Any) -> Any:
        application = super().app(**row)
        spec = application.harnesses[0]

        def collect(*args: Any, **kwargs: Any) -> Any:
            rows = spec.collect(*args, **kwargs)
            rows[0]["session_goal"] = claude_data.session_goal(
                self.config, self.state, str(self.path)
            )
            return rows

        application.harnesses = (dataclasses.replace(spec, collect=collect),)
        return application

    def command(self, port: int, *args: str, tty: bool = True) -> tuple[int, str, str]:
        out, err = Terminal() if tty else io.StringIO(), io.StringIO()
        with (
            mock.patch.object(
                terminal_client,
                "ensure_dashboard",
                return_value=terminal_client.Dashboard(port, 1, 1, "1.0.0"),
            ),
            mock.patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": SID}),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = terminal_client.run(list(args))
        return code, out.getvalue(), err.getvalue()

    def entry(self) -> Any:
        return annotation_store.find(annotation_store.load(self.config), "claude", SHORT)

    def test_a_person_reading_through_a_pipe_with_an_older_encoding_still_gets_the_goal(
        self,
    ) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", SHORT, goal="Ship parser — café"
        )
        buffer = io.BytesIO()
        out = io.TextIOWrapper(buffer, encoding="ascii")
        self.addCleanup(out.close)
        err = io.StringIO()
        with (
            self.serving() as port,
            mock.patch.object(
                terminal_client,
                "ensure_dashboard",
                return_value=terminal_client.Dashboard(port, 1, 1, "1.0.0"),
            ),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = terminal_client.run(["--goal", "--session", "claude:" + SID])
        out.flush()
        self.assertEqual((0, ""), (code, err.getvalue()))
        self.assertIn("Goal: Ship parser ? caf?", buffer.getvalue().decode("ascii"))

    def test_a_person_reads_the_fresh_intent_source_revision_outcomes_and_page_without_a_post(
        self,
    ) -> None:
        with self.serving() as port, mock.patch.object(terminal_client, "post") as post:
            status, payload = self.call(port, "GET", f"/api/session?harness=claude&sid={SID}")
            self.assertEqual(200, status)
            code, out, err = self.command(port, "--goal", "--session", "claude:" + SID)
            self.assertEqual((0, ""), (code, err))
            row = payload["session"]
            self.assertIn(terminal_drift.goal_text(row, payload), out)
            self.assertIn(terminal_drift.goal_source_line(row, payload), out)
            self.assertIn("Saved revision: 1", out)
            self.assertIn(row["annotation_line_1"], out)
            self.assertIn(row["annotation_binding_why"], out)
            self.assertIn(terminal_drift.session_url(port, row["project"], "claude", SHORT), out)
            post.assert_not_called()
            self.assertIsNone(self.application.live_leases)
            self.assertEqual({}, reading.published_jobs(self.config))

    def test_a_person_saves_only_the_goal_and_sees_the_normalized_words_without_a_level(
        self,
    ) -> None:
        before = self.entry()["revisions"][-1]
        with (
            self.serving() as port,
            mock.patch.object(terminal_client, "post", wraps=terminal_client.post) as post,
        ):
            code, out, err = self.command(
                port, "--goal", "  Ship the parser  ", "--session", "claude:" + SID
            )
            self.assertEqual((0, ""), (code, err))
            self.assertIn("Saved goal as revision 2", out)
            self.assertIn("Goal: Ship the parser", out)
            self.assertNotIn("Goal:   Ship", out)
            self.assertNotIn("level", out.lower())
            body = post.call_args.args[2]
            self.assertEqual(
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "goal": "  Ship the parser  ",
                    "expected_revision": 1,
                },
                body,
            )
            self.assertIsNone(self.application.live_leases)
        after = self.entry()["revisions"]
        self.assertEqual(2, len(after))
        self.assertEqual(before["lines"], after[-1]["lines"])
        self.assertEqual(before, after[0])

    def test_a_person_saving_identical_words_is_told_they_are_already_saved(self) -> None:
        goal = self.entry()["revisions"][-1]["goal"]
        with self.serving() as port:
            code, out, err = self.command(port, "--goal", goal, "--session", "claude:" + SID)
        self.assertEqual((0, ""), (code, err))
        self.assertIn("already saved", out)
        self.assertEqual(1, len(self.entry()["revisions"]))

    def test_a_person_clears_the_goal_keeps_history_and_outcomes_and_is_offered_a_draft(
        self,
    ) -> None:
        before = self.entry()["revisions"][-1]
        with (
            self.serving() as port,
            mock.patch.object(terminal_client, "post", wraps=terminal_client.post) as post,
        ):
            code, out, err = self.command(port, "--goal", "--clear", "--session", "claude:" + SID)
            self.assertEqual((0, ""), (code, err))
            self.assertIn("draft is now offered", out)
            self.assertIn("not saved", out)
            self.assertEqual("", post.call_args.args[2]["goal"])
            self.assertNotIn("clear", post.call_args.args[2])
        revisions = self.entry()["revisions"]
        self.assertEqual(2, len(revisions))
        self.assertEqual(before, revisions[0])
        self.assertEqual(before["lines"], revisions[1]["lines"])
        self.assertEqual("", revisions[1]["goal"])

    def test_a_person_adopts_the_harness_goal_with_its_source_time_and_revision(self) -> None:
        at = START.timestamp() + 100
        self.session.rows.extend(set_goal(at))
        self.session.save(self.path)
        with (
            self.serving() as port,
            mock.patch.object(terminal_client, "post", wraps=terminal_client.post) as post,
        ):
            code, out, err = self.command(port, "--goal", "--adopt", "--session", "claude:" + SID)
            self.assertEqual((0, ""), (code, err))
            self.assertIn("Saved goal as revision 2", out)
            self.assertEqual(
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "adopt": "session-goal",
                    "expected_prompt": CONDITION,
                    "expected_prompt_at": at,
                    "expected_revision": 1,
                },
                post.call_args.args[2],
            )
        revision = self.entry()["revisions"][-1]
        self.assertEqual(CONDITION, revision["goal"])
        self.assertEqual("session-goal", revision["goal_source"])
        self.assertEqual(at, revision["goal_source_at"])

    def test_a_person_whose_goal_was_discarded_on_the_board_meanwhile_keeps_the_discard(
        self,
    ) -> None:
        Path(annotation_store.store_path(self.config)).unlink()
        self.session.rows.extend(set_goal(START.timestamp() + 100))
        self.session.save(self.path)
        original = terminal_client.post
        discarded = None

        def changed(port: int, path: str, body: Any, **kwargs: Any) -> Any:
            nonlocal discarded
            self.assertEqual(0, body["expected_revision"])
            annotation_store.annotate(
                self.config, self.state, "claude", SHORT, goal="Another tab's goal"
            )
            annotation_store.clear(self.config, self.state, "claude", SHORT)
            discarded = self.entry()
            return original(port, path, body, **kwargs)

        with (
            self.serving() as port,
            mock.patch.object(terminal_client, "post", side_effect=changed),
        ):
            code, out, err = self.command(port, "--goal", "--adopt", "--session", "claude:" + SID)
        self.assertEqual(discarded, self.entry())
        self.assertTrue(annotation_store.is_discarded(self.entry()))
        self.assertEqual((1, ""), (code, out))
        self.assertIn("goal was discarded on the board meanwhile", err)
        self.assertNotIn("Saved goal", out + err)

    def test_a_person_cannot_overwrite_a_changed_goal_prompt_or_time_by_adopting(self) -> None:
        at = START.timestamp() + 100
        self.session.rows.extend(set_goal(at))
        self.session.save(self.path)
        for change in ("words", "time", "revision"):
            with self.subTest(change=change), self.serving() as port:
                original = terminal_client.post

                def changed(
                    port: int,
                    path: str,
                    body: Any,
                    change: str = change,
                    original: Any = original,
                    **kwargs: Any,
                ) -> Any:
                    if change == "revision":
                        annotation_store.annotate(
                            self.config, self.state, "claude", SHORT, goal="Someone else's save"
                        )
                    else:
                        self.session.rows.extend(
                            set_goal(at + 1, CONDITION if change == "time" else "A changed goal")
                        )
                        self.session.save(self.path)
                    return original(port, path, body, **kwargs)

                with mock.patch.object(terminal_client, "post", side_effect=changed):
                    code, out, err = self.command(
                        port, "--goal", "--adopt", "--session", "claude:" + SID
                    )
                self.assertEqual(1, code)
                self.assertEqual("", out)
                self.assertIn("not saved", err)
                self.session.rows.extend(set_goal(at))
                self.session.save(self.path)

    def test_a_person_must_name_a_session_and_use_a_terminal_before_any_write_or_start(
        self,
    ) -> None:
        for mode in (("--goal", "New goal"), ("--goal", "--clear"), ("--goal", "--adopt")):
            for extra, tty in (((), True), (("--session", "claude:" + SID), False)):
                with (
                    self.subTest(mode=mode, extra=extra),
                    mock.patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": SID}, clear=True),
                    mock.patch.object(terminal_client, "post") as post,
                    mock.patch.object(terminal_client, "ensure_dashboard") as ensure,
                ):
                    out, err = Terminal() if tty else io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        code = terminal_client.run([*mode, *extra])
                    self.assertEqual(1, code)
                    self.assertIn("explicit --session and terminal stdout", err.getvalue())
                    post.assert_not_called()
                    ensure.assert_not_called()

    def test_a_person_sees_a_failed_save_instead_of_success_when_the_store_refuses_it(self) -> None:
        with (
            self.serving() as port,
            mock.patch.object(
                annotation_store, "annotate", return_value=annotation_store.OUTCOME_UNWRITABLE
            ),
        ):
            code, out, err = self.command(port, "--goal", "New goal", "--session", "claude:" + SID)
        self.assertEqual((1, ""), (code, out))
        self.assertIn("not saved", err)

    def test_a_person_cannot_send_overlong_words_to_the_store(self) -> None:
        with self.serving() as port, mock.patch.object(terminal_client, "post") as post:
            code, out, err = self.command(port, "--goal", "x" * 1001, "--session", "claude:" + SID)
        self.assertEqual((1, ""), (code, out))
        self.assertIn("1,000", err)
        post.assert_not_called()

    def test_a_person_adopts_a_drafted_prompt_even_outside_the_default_window(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", SHORT, goal="")
        application = self.app()
        collect = application.collect_json

        def aged(*, show_all: bool) -> Any:
            revision, raw = collect(show_all=show_all)
            payload = json.loads(raw)
            if not show_all:
                payload["sessions"] = []
            return revision, json.dumps(payload).encode()

        with (
            self.serving(application) as port,
            mock.patch.object(application, "collect_json", side_effect=aged),
        ):
            code, out, err = self.command(port, "--goal", "--adopt", "--session", "claude:" + SID)
        self.assertEqual((0, ""), (code, err))
        self.assertIn("From your first prompt", out)
        self.assertEqual("first-prompt", self.entry()["revisions"][-1]["goal_source"])

    def test_a_person_with_no_candidate_cannot_adopt_or_post(self) -> None:
        with self.serving() as port, mock.patch.object(terminal_client, "post") as post:
            code, out, err = self.command(port, "--goal", "--adopt", "--session", "claude:" + SID)
        self.assertEqual((1, ""), (code, out))
        self.assertIn("No goal candidate", err)
        post.assert_not_called()

    def test_a_persons_save_receipt_names_their_revision_when_another_save_follows_it(self) -> None:
        annotate = annotation_store.annotate

        def another_save(*args: Any, **kwargs: Any) -> str:
            outcome = annotate(*args, **kwargs)
            annotate(self.config, self.state, "claude", SHORT, goal="Another tab's goal")
            return outcome

        with (
            self.serving() as port,
            mock.patch.object(annotation_store, "annotate", side_effect=another_save),
        ):
            status, answer = self.call(
                port,
                "POST",
                "/api/annotate",
                {"harness": "claude", "sid": SHORT, "goal": "My goal", "expected_revision": 1},
            )
        self.assertEqual(200, status)
        self.assertEqual(3, answer["revision"])
        self.assertEqual(2, answer["saved_revision"])

    def test_a_person_sees_a_newer_save_after_their_clear_without_being_told_it_is_empty(
        self,
    ) -> None:
        annotate = annotation_store.annotate

        def another_save(*args: Any, **kwargs: Any) -> str:
            outcome = annotate(*args, **kwargs)
            annotate(self.config, self.state, "claude", SHORT, goal="Another tab's goal")
            return outcome

        with (
            self.serving() as port,
            mock.patch.object(annotation_store, "annotate", side_effect=another_save),
        ):
            code, out, err = self.command(port, "--goal", "--clear", "--session", "claude:" + SID)
        self.assertEqual((0, ""), (code, err))
        self.assertIn("Saved goal as revision 2", out)
        self.assertIn("Another save followed this one", out)
        self.assertIn("Goal: Another tab's goal", out)
        self.assertNotIn("The saved goal is empty", out)
        self.assertNotIn("draft is now offered", out)

    def test_a_persons_terminal_save_hides_the_old_footer_level_until_a_monitor_rechecks(
        self,
    ) -> None:
        application = self.app()
        collected = json.loads(application.collect_json(show_all=False)[1])
        source = http_api.FooterMonitorSource(application)
        with (
            mock.patch.object(
                source, "state", return_value={"on": True, "episode": 1, "started_at": self.now}
            ),
            mock.patch.object(source, "view", return_value={"pill": {"level": "medium"}}),
            mock.patch("time.monotonic", return_value=0.0),
            self.serving(application) as port,
        ):
            lines = footer_lines.Lines(self.config.state_home, monitor=source)
            application.footer_lines = lines
            self.addCleanup(lines.remove_all)
            row = collected["sessions"][0]
            path = Path(lines.directory) / footer_lines.line_name(
                "claude", row.get("resume_id") or row["sid"]
            )
            lines.update(collected, self.now)
            lines.touch(self.now)
            self.assertEqual("medium", json.loads(path.read_text())["level"])
            code, out, err = self.command(
                port, "--goal", "A changed goal", "--session", "claude:" + SID
            )
            self.assertEqual((0, ""), (code, err))
            self.assertNotIn("level", out.lower())
            self.assertIsNone(json.loads(path.read_text())["level"])
            lines.touch(self.now + 15)
            self.assertEqual("medium", json.loads(path.read_text())["level"])


class APersonChoosesOneGoalOperation(unittest.TestCase):
    def test_a_person_reading_a_goal_never_starts_a_dashboard(self) -> None:
        with (
            mock.patch.object(terminal_client, "find_dashboard", return_value=None),
            mock.patch.object(terminal_client, "start_daemon") as start,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                1,
                terminal_client.run_goal(
                    terminal_client.GoalRequest(session="claude:abc"), environ={}
                ),
            )
        start.assert_not_called()

    def test_a_person_cannot_hide_unrelated_flags_beside_a_goal_in_the_full_parser(self) -> None:
        from compass_runtime import cli  # noqa: PLC0415

        for argv in (
            ["--goal", "--port", "4553", "--stop"],
            ["--goal", "--goal"],
            ["--goal", "--clear", "--adopt"],
            ["--goal", "Text", "--clear"],
            ["--clear"],
            ["--adopt"],
        ):
            with (
                self.subTest(argv=argv),
                mock.patch.object(terminal_client, "run_goal") as run,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                cli.main(argv)
            self.assertEqual(2, raised.exception.code)
            run.assert_not_called()

    def test_a_person_reads_the_same_goal_source_and_outcomes_as_a_fresh_intent_card(self) -> None:
        fixture = SERVER_PATH.parents[3] / "frontend/test/fixtures/terminal-goal.json"
        with mock.patch.object(terminal_drift, "clock_text", return_value="03:04"):
            for case in json.loads(fixture.read_text()):
                with self.subTest(case=case["name"]):
                    payload = case["payload"]
                    row = payload["session"]
                    expected = case["expected"]
                    self.assertEqual(expected["goal"], terminal_drift.goal_text(row, payload))
                    self.assertEqual(
                        expected["source"], terminal_drift.goal_source_line(row, payload)
                    )
                    output = "\n".join(terminal_goal.render(payload, port=4553))
                    for text in [expected["goal"], expected["source"], *expected["outcomes"]]:
                        self.assertIn(text, output)

    def test_a_person_with_only_whitespace_outcomes_is_told_none_are_saved(self) -> None:
        fixture = SERVER_PATH.parents[3] / "frontend/test/fixtures/terminal-goal.json"
        payload = json.loads(fixture.read_text())[0]["payload"]
        for n in range(1, 7):
            payload["session"][f"annotation_line_{n}"] = " \t\n "
        output = "\n".join(terminal_goal.render(payload, port=4553))
        self.assertIn("No expected outcome lines saved.", output)
        self.assertNotIn("Outcome ", output)
        payload["session"]["annotation_line_3"] = "Tests pass"
        output = "\n".join(terminal_goal.render(payload, port=4553))
        self.assertIn("Outcome 3: Tests pass", output)
        self.assertNotIn("No expected outcome lines saved.", output)

    def test_a_person_reads_a_harness_goal_draft_and_its_adoption_in_the_parity_cases(self) -> None:
        fixture = SERVER_PATH.parents[3] / "frontend/test/fixtures/terminal-goal.json"
        cases = {case["name"]: case for case in json.loads(fixture.read_text())}
        for name in ("harness-goal-draft", "adopted-harness-goal"):
            with self.subTest(case=name):
                case = cases[name]
                row = case["payload"]["session"]
                self.assertIsNotNone(row["session_goal"])
                self.assertNotEqual(row["first_prompt"], row["session_goal"]["text"])
                self.assertEqual(row["session_goal"]["text"], case["expected"]["goal"])
                if name == "adopted-harness-goal":
                    self.assertEqual("session-goal", row["annotation_goal_source"])
                    self.assertEqual(row["session_goal"]["at"], row["annotation_goal_source_at"])
                else:
                    self.assertFalse(row["annotation_goal"])

    def test_a_person_can_choose_each_goal_form_but_cannot_combine_them(self) -> None:
        for argv in (
            ["--goal"],
            ["--goal", "Ship"],
            ["--goal=Ship"],
            ["--goal", "--clear"],
            ["--session=claude:abc", "--goal", "--adopt"],
        ):
            with self.subTest(argv=argv):
                self.assertIsNotNone(terminal_client.parse_goal_args(argv))
                self.assertTrue(terminal_client.handles(argv))
        for argv in (
            ["--goal", "--goal"],
            ["--goal", "Ship", "more"],
            ["--goal", "--adopt", "--clear"],
            ["--goal", "Ship", "--clear"],
            ["--goal", "--off"],
            ["--goal", "--session", "claude:a", "--session", "claude:b"],
        ):
            with self.subTest(argv=argv):
                self.assertIsNone(terminal_client.parse_goal_args(argv))

    def test_a_persons_goal_command_dispatches_without_loading_the_dashboard(self) -> None:
        code = f"""
import sys
from unittest import mock
sys.path.insert(0, {str(SERVER_PATH.parent)!r})
from compass_runtime import entry, terminal_client
with mock.patch.object(terminal_client, 'ensure_dashboard', return_value=terminal_client.Refusal('No board')):
    assert entry.main(['--goal', '--session', 'claude:abc']) == 1
assert 'compass_runtime.cli' not in sys.modules
assert 'compass_runtime.aggregate' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=False
        )
        self.assertEqual(0, result.returncode, result.stderr)
