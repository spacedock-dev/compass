"""The terminal preview and registered session hook show the same published lane."""

from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import time
import unittest
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

import plan_summary_hook
from compass_runtime import records, terminal_client
from compass_runtime.plan import publish, readers, settings, sources, summary_states

from .support import SERVER_PATH, make_config, server_command
from .test_history import stub_application
from .test_plan_publish import request
from .test_plan_readers import STAND_IN, VARIANT, PlanRepoTestCase
from .test_project_script_checks import GIT

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

SKILL = SERVER_PATH.parent
PLUGIN = SKILL.parents[1]
HOOK = "plan_summary_hook.py"
EXPECTED = (
    "Goal: Restore the model ship\n"
    "Done when: The model floats.\n"
    "Progress: not measured\n"
    "Lane state: not measured\n"
    "Ask: Is the hull ready?\n"
)
MEASURED_GOALS = "## Goals\n- G1: Restore the model ship\n**Lanes:** hull, paint\n"
# Words for every board group, so each state can be set from a tracker row.
WORDS = {
    "open": "not_started",
    "driving": "running",
    "parked": "waiting",
    "stuck": "blocked",
    "fixed": "done",
    "abandoned": "dropped",
}


def tracker(**rows: str) -> str:
    body = "".join(f"| Work on {lane} | {lane} | {word} |\n" for lane, word in rows.items())
    return "| Item | Lane | Status |\n| --- | --- | --- |\n" + body


def _snapshot(states: dict[str, str], goals: Sequence[Sequence[str]]) -> summary_states.Snapshot:
    return summary_states.Snapshot(states, tuple(tuple(goal) for goal in goals))


class SummaryHarness(PlanRepoTestCase):
    """Helpers for the hook and preview tests; no tests of its own."""

    def setup_summary(self) -> None:
        self.configure(summary={"enabled": True})
        self.write_brief("hull", "Restore the model ship", "The model floats.")
        self.log.write_text("ask hull:1 Is the hull ready?\n", encoding="utf-8")

    def setup_measured(self, **states: str) -> None:
        """Two lanes serving G1, with the tracker setting each named lane's state."""
        self.write_sources({"goals": MEASURED_GOALS, "tracker": tracker(**states)})
        self.configure(summary={"enabled": True}, tracker={"lane_column": "Lane", "words": WORDS})
        self.write_brief("hull", "Restore the model ship", "The model floats.", serves="G1")
        self.write_brief("paint", "Paint the deck", "It dries.", serves="G1")
        self.log.write_text("ask hull:1 Is the hull ready?\n", encoding="utf-8")

    def write_brief(self, lane: str, goal: str, done: str, *, serves: str | None = None) -> None:
        text = f"## Goal\n{goal}\n\n## Done\n{done}\n"
        if serves is not None:
            text += f"\n*Serves*: {serves}\n"
        (self.briefs / f"{lane}.md").write_text(text, encoding="utf-8")

    def board(self, **changes: Any) -> dict[str, Any]:
        """Build the plan the way the board does, which saves the lane states for the hook."""
        config = make_config(state_home=str(self.home), state_dir=self.home, **changes)
        status, _, body = request(stub_application(config, [], []))
        self.assertEqual(status, 200)
        published: dict[str, Any] = json.loads(body)
        return published

    @property
    def states_file(self) -> Path:
        return self.home / summary_states.FILENAME

    def env(self, lane: str | None = None) -> dict[str, str]:
        env = {**os.environ, "COMPASS_HOME": str(self.home)}
        env.pop("COMPASS_LANE", None)
        if lane is not None:
            env["COMPASS_LANE"] = lane
        return env

    def registered(self, harness: str) -> list[str]:
        name = "hooks.json" if harness == "claude" else "codex-hooks.json"
        registration = json.loads((PLUGIN / "hooks" / name).read_bytes())
        hooks = [
            hook
            for group in registration["hooks"]["SessionStart"]
            for hook in group["hooks"]
            if HOOK in hook["command"]
        ]
        self.assertEqual(len(hooks), 1)
        entry = hooks[0]
        root = "${CLAUDE_PLUGIN_ROOT}" if harness == "claude" else "${PLUGIN_ROOT}"
        expected = f'python3 "{root}/skills/compass/launch.py" "{root}/skills/compass/{HOOK}"'
        self.assertEqual(entry, {"type": "command", "command": expected, "timeout": 2})
        args = [arg.replace(root, str(PLUGIN)) for arg in shlex.split(entry["command"])]
        return [sys.executable, *args[1:]]

    def run_hook(
        self,
        *,
        harness: str = "claude",
        cwd: Path | None = None,
        lane: str | None = None,
        raw: bytes | None = None,
        process_cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            self.registered(harness),
            input=raw
            if raw is not None
            else json.dumps(
                {"hook_event_name": "SessionStart", "cwd": str(cwd or self.hull)}
            ).encode(),
            cwd=process_cwd or self.root,
            env=self.env(lane),
            capture_output=True,
            timeout=10,
            check=False,
        )

    def context(self, **kwargs: Any) -> str:
        result = self.run_hook(**kwargs)
        self.assertEqual((result.returncode, result.stderr), (0, b""))
        delivered = json.loads(result.stdout)
        self.assertEqual(set(delivered), {"hookSpecificOutput"})
        self.assertEqual(delivered["hookSpecificOutput"]["hookEventName"], "SessionStart")
        context: str = delivered["hookSpecificOutput"]["additionalContext"]
        return context

    def preview(self, *args: str, lane: str | None = None) -> str:
        result = subprocess.run(
            server_command("--plan-slice", *args),
            cwd=self.hull,
            env=self.env(lane),
            capture_output=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return result.stdout

    def assert_silent(self, **kwargs: Any) -> None:
        result = self.run_hook(**kwargs)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))

    def assert_everywhere(self, lane: str, expected: str) -> None:
        """Both registered hooks and the preview, by explicit lane and (for hull) by folder."""
        self.assertEqual(self.preview("--lane", lane), expected)
        self.assertEqual(self.preview(lane=lane), expected)
        for harness in ("claude", "codex"):
            with self.subTest(harness=harness, lane=lane):
                self.assertEqual(self.context(harness=harness, lane=lane), expected.rstrip("\n"))
        if lane == "hull":
            self.assertEqual(self.preview(), expected)
            self.assertEqual(self.context(), expected.rstrip("\n"))


@unittest.skipIf(GIT is None or os.name == "nt", "Needs Git and POSIX directory descriptors")
class PlanSummaryHookTest(SummaryHarness):
    def test_registered_handlers_emit_exactly_the_preview_as_harness_context(self) -> None:
        self.setup_summary()
        self.assertEqual(self.preview(), EXPECTED)
        for harness in ("claude", "codex"):
            with self.subTest(harness=harness):
                result = self.run_hook(harness=harness)
                self.assertEqual((result.returncode, result.stderr), (0, b""))
                self.assertEqual(
                    json.loads(result.stdout),
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": EXPECTED.rstrip("\n"),
                        }
                    },
                )

    def test_the_board_saves_lane_states_the_hook_and_preview_report(self) -> None:
        self.setup_measured(hull="fixed", paint="driving")
        published = self.board()
        self.assertEqual(
            {lane["id"]: lane["state"] for lane in published["lanes"]},
            {"hull": "done", "paint": "running"},
        )
        self.assert_everywhere(
            "hull",
            "Goal: Restore the model ship\nDone when: The model floats.\n"
            "Progress: 1 of 2 lanes are done\nLane state: Done\nAsk: Is the hull ready?\n",
        )
        self.assert_everywhere(
            "paint",
            "Goal: Paint the deck\nDone when: It dries.\n"
            "Progress: 1 of 2 lanes are done\nLane state: In progress\n",
        )

    def test_zero_done_lanes_read_as_the_plan_page_does(self) -> None:
        self.setup_measured(hull="stuck", paint="parked")
        self.board()
        self.assert_everywhere(
            "hull",
            "Goal: Restore the model ship\nDone when: The model floats.\n"
            "Progress: 0 of 2 lanes are done\nLane state: Blocked\nAsk: Is the hull ready?\n",
        )
        self.assertIn("Lane state: Waiting\n", self.preview("--lane", "paint"))

    def test_a_dropped_lane_is_shown_and_left_out_of_progress(self) -> None:
        self.setup_measured(hull="abandoned", paint="fixed")
        self.board()
        self.assert_everywhere(
            "hull",
            "Goal: Restore the model ship\nDone when: The model floats.\n"
            "Progress: 1 of 1 lane is done\nLane state: Dropped\nAsk: Is the hull ready?\n",
        )
        self.setup_measured(hull="abandoned", paint="abandoned")
        self.board()
        self.assertIn("Progress: not measured\nLane state: Dropped\n", self.preview())

    def test_an_unmeasured_lane_is_not_counted(self) -> None:
        self.setup_measured(hull="open")
        self.board()
        self.assertIn("Progress: 0 of 1 lane is done\nLane state: Planned\n", self.preview())
        self.assertIn(
            "Progress: 0 of 1 lane is done\nLane state: not measured\n",
            self.preview("--lane", "paint"),
        )

    def test_a_missing_stale_or_damaged_state_file_is_not_measured(self) -> None:
        self.setup_measured(hull="fixed", paint="driving")
        unmeasured = (
            "Goal: Restore the model ship\nDone when: The model floats.\n"
            "Progress: not measured\nLane state: not measured\nAsk: Is the hull ready?\n"
        )
        self.assert_everywhere("hull", unmeasured)
        self.board()
        saved = json.loads(self.states_file.read_bytes())
        day = summary_states.MAX_AGE_SECONDS
        for name, written in (
            ("stale", time.time() - day - 60),
            ("future", time.time() + 3600),
            ("boolean", True),
        ):
            with self.subTest(name):
                self.states_file.write_text(json.dumps({**saved, "written": written}))
                self.assert_everywhere("hull", unmeasured)
        self.states_file.write_text(json.dumps({**saved, "written": time.time() - day + 60}))
        self.assertIn("Lane state: Done\n", self.preview())
        for name, damage in (
            ("not JSON", "{"),
            ("NaN", json.dumps(saved).replace('"written": ', '"written": NaN, "x": ')),
            ("raw word", json.dumps({**saved, "lanes": {"hull": "FIXED", "paint": "done"}})),
            ("unsafe lane", json.dumps({**saved, "lanes": {"../x": "done", "hull": "done"}})),
            ("version", json.dumps({**saved, "v": 2})),
            ("repeated key", json.dumps(saved)[:-1] + ', "v": 1}'),
            ("extra field", json.dumps({**saved, "title": "Restore"})),
            ("draft goal", json.dumps({**saved, "goals": [["hull", "hull"]]})),
        ):
            with self.subTest(name):
                self.states_file.write_text(damage)
                self.assertIn("Progress: not measured\nLane state: not measured\n", self.preview())
        # A link to a valid file is refused too.
        elsewhere = self.root / "elsewhere.json"
        elsewhere.write_text(json.dumps({**saved, "written": time.time()}))
        self.states_file.unlink()
        self.states_file.symlink_to(elsewhere)
        self.assertIn("Lane state: not measured\n", self.preview())

    def test_the_board_writes_the_state_file_only_with_the_summary_on(self) -> None:
        self.setup_measured(hull="fixed", paint="driving")
        tracker_settings = {"lane_column": "Lane", "words": WORDS}
        self.configure(tracker=tracker_settings, summary={"enabled": False})
        self.board()
        self.assertFalse(self.states_file.exists())
        self.configure(tracker=tracker_settings, summary={"enabled": True})
        self.board()
        saved = json.loads(self.states_file.read_bytes())
        self.assertEqual(set(saved), {"v", "written", "lanes", "goals"})
        self.assertEqual(saved["lanes"], {"hull": "done", "paint": "running"})
        self.assertEqual(saved["goals"], [["hull", "paint"]])
        self.assertEqual(self.states_file.stat().st_mode & 0o777, 0o600)
        text = self.states_file.read_text()
        for fragment in ("Restore", "model", "Paint", "G1", "Work on"):
            self.assertNotIn(fragment, text)

    def test_no_plan_writes_and_removes_nothing_and_forget_deletes_the_file(self) -> None:
        self.setup_measured(hull="fixed", paint="driving")
        status, _, _ = request(
            stub_application(
                make_config(state_home=str(self.home), state_dir=self.home, plan_enabled=False),
                [],
                [],
            )
        )
        self.assertEqual(status, 404)
        self.assertFalse(self.states_file.exists())
        self.board()
        before = self.states_file.read_bytes()
        request(
            stub_application(
                make_config(state_home=str(self.home), state_dir=self.home, plan_enabled=False),
                [],
                [],
            )
        )
        self.assertEqual(self.states_file.read_bytes(), before)
        self.assertEqual(self.preview("--no-plan"), "")
        forgot = subprocess.run(
            server_command("--forget", "--port", "45399"),
            env=self.env(),
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        self.assertEqual(forgot.returncode, 0, forgot.stdout + forgot.stderr)
        self.assertFalse(self.states_file.exists())
        self.assertIn(summary_states.FILENAME, forgot.stdout)

    def test_a_settings_refusal_on_the_board_silences_the_hook(self) -> None:
        self.setup_summary()
        # A private root inside a checkout whose `.git` cannot be read: the board, with Git
        # reads on, cannot place the root in that repository's tree and refuses the settings.
        outer = self.root / "checkout"
        sealed = outer / "sealed-root"
        sealed.mkdir(parents=True)
        self.configure(summary={"enabled": True}, private={"roots": [str(sealed)]})
        (outer / ".git").write_text("not a gitdir line\n", encoding="utf-8")
        published = self.board()
        self.assertEqual(published["state"], "refused")
        self.assert_silent()
        self.assert_silent(lane="hull")
        self.assertEqual(self.preview(), "")
        self.assertEqual(self.preview("--lane", "hull"), "")

    def test_missing_off_and_refused_settings_are_silent(self) -> None:
        self.assert_silent()
        self.assertEqual(self.preview(), "")
        self.configure()
        self.write_brief("hull", "A goal that would otherwise be shown", "It works.")
        self.assert_silent()
        self.assertEqual(self.preview(), "")
        self.configure(summary={"enabled": True})
        settings_path = self.home / "compass-plan.json"
        settings_path.write_text('{"summary": {"enabled": "yes"}}', encoding="utf-8")
        self.assert_silent()
        self.assertEqual(self.preview(), "")

    def test_folder_reads_abstain_on_no_match_ambiguity_and_privacy(self) -> None:
        self.setup_summary()
        self.assert_silent(cwd=self.root)
        self.assert_silent(cwd=self.hull / "missing")
        nested = self.hull / "other"
        nested.mkdir()
        self.configure(
            summary={"enabled": True},
            briefs={"lane_folders": {"hull": str(self.hull), "paint": str(nested)}},
        )
        # A declared folder whose brief is missing does not make the match ambiguous.
        self.assertEqual(self.context(cwd=nested), EXPECTED.rstrip("\n"))
        self.write_brief("paint", "Paint the deck", "It dries.")
        self.assert_silent(cwd=nested)
        self.assertEqual(self.preview(), EXPECTED)
        (nested / ".restricted").touch()
        self.assert_silent(cwd=nested)
        # A lane folder declared through a link is refused, as on the board, though a stat of it
        # lands inside the working folder's ancestry.
        link = self.root / "hull-link"
        link.symlink_to(self.hull, target_is_directory=True)
        self.configure(summary={"enabled": True}, briefs={"lane_folders": {"hull": str(link)}})
        self.assert_silent(cwd=self.hull)

    def test_explicit_lane_precedes_folder_and_invalid_explicit_lane_abstains(self) -> None:
        self.setup_summary()
        self.write_brief("paint", "Paint the deck", "It dries.")
        result = self.run_hook(cwd=self.root, lane="paint")
        self.assertIn(b"Paint the deck", result.stdout)
        self.assertEqual(self.preview("--lane", "hull", lane="paint"), EXPECTED)
        for lane in ("", "../hull", "absent", "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ"):
            with self.subTest(lane=lane):
                self.assert_silent(lane=lane)
                self.assertEqual(self.preview(lane=lane), "")

    def test_names_that_normalise_alike_are_refused_for_the_summary_too(self) -> None:
        self.setup_summary()
        file = self.home / "compass-plan.json"
        doc = json.loads(file.read_bytes())
        doc["briefs"]["filename"] = [
            {"name": "lane", "kind": "slug", "max_chars": 64},
            ".\u00e9.md",
        ]
        file.write_text(json.dumps(doc), encoding="utf-8")
        (self.briefs / "hull.md").rename(self.briefs / "hull.\u00e9.md")
        self.assertEqual(self.preview("--lane", "hull"), EXPECTED)
        try:
            (self.briefs / "hull.e\u0301.md").write_text("## Goal\nTwin\n", encoding="utf-8")
        except OSError:
            self.skipTest("This file system cannot hold both spellings")
        if len(list(self.briefs.iterdir())) != 2:
            self.skipTest("This file system folds both spellings to one name")
        self.assertEqual(self.preview("--lane", "hull"), "")

    def test_only_the_selected_lane_s_asks_appear(self) -> None:
        self.setup_summary()
        self.write_brief("paint", "Paint the deck", "It dries.")
        self.log.write_text(
            "ask paint:1 Which colour?\nask hull:1 Is the hull ready?\nask paint:2 Gloss?\n",
            encoding="utf-8",
        )
        published = self.board()
        self.assertEqual(
            [(ask["lane"]["id"], ask["text"]) for ask in published["asks"]],
            [("paint", "Which colour?"), ("hull", "Is the hull ready?"), ("paint", "Gloss?")],
        )
        hull = self.context(lane="hull")
        self.assertIn("Ask: Is the hull ready?", hull)
        self.assertNotIn("colour", hull)
        self.assertNotIn("Gloss", hull)
        paint = self.preview("--lane", "paint")
        self.assertEqual(paint.splitlines()[-2:], ["Ask: Which colour?", "Ask: Gloss?"], paint)
        self.assertNotIn("hull ready", paint)

    def test_input_errors_are_silent(self) -> None:
        self.setup_summary()
        valid = json.dumps({"hook_event_name": "SessionStart", "cwd": str(self.hull)}).encode()
        cap = plan_summary_hook.MAX_PAYLOAD_BYTES
        for raw in (
            b"",
            b"\xff",
            b"{",
            b"[]",
            b'{"hook_event_name":"SessionStart","cwd":5}',
            b" " * (1 << 20),
            valid + b" " * (cap + 1 - len(valid)),
            valid[:-1] + b', "extra": NaN}',
            valid[:-1] + b', "hook_event_name": "SessionEnd"}',
            b'{"hook_event_name":"SessionEnd",' + valid[1:],
            valid.replace(b"SessionStart", b"SessionEnd"),
            b'{"hook_event_name":"SessionStart","cwd":"/synthetic/\\udcff"}',
        ):
            for lane in (None, "hull"):
                with self.subTest(size=len(raw), head=raw[:60], lane=lane):
                    self.assert_silent(raw=raw, lane=lane)
        delivered = self.context(raw=valid + b" " * (cap - len(valid)))
        self.assertEqual(delivered, EXPECTED.rstrip("\n"))

    def test_a_relative_or_absent_cwd_needs_an_explicit_lane(self) -> None:
        self.setup_summary()
        relative = json.dumps({"hook_event_name": "SessionStart", "cwd": "work/hull"}).encode()
        # The relative folder would name the hull lane from the hook's own working folder.
        self.assert_silent(raw=relative, process_cwd=self.root)
        for raw in (relative, b'{"hook_event_name":"SessionStart"}'):
            with self.subTest(raw=raw):
                self.assertEqual(self.context(raw=raw, lane="hull"), EXPECTED.rstrip("\n"))

    def test_a_reader_error_abstains_without_output(self) -> None:
        self.setup_summary()
        event = json.dumps({"hook_event_name": "SessionStart", "cwd": str(self.hull)})
        out = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.env(), clear=True),
            mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(event.encode()))),
            mock.patch.object(sys, "stdout", out),
            mock.patch.object(sys, "stderr", err),
            mock.patch.object(readers, "lane_asks", side_effect=OSError("Synthetic error")),
        ):
            self.assertEqual(plan_summary_hook.main(), 0)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        with mock.patch.object(readers, "lane_briefs", side_effect=OSError("Synthetic error")):
            self.assertEqual(publish.session_summary(str(self.home), lane="hull"), "")

    def test_an_invalid_explicit_lane_reads_no_settings(self) -> None:
        self.setup_summary()
        with mock.patch.object(settings, "load") as load:
            self.assertEqual(publish.session_summary(str(self.home), lane="../hull"), "")
        load.assert_not_called()

    def test_without_settings_the_hook_loads_no_plan_module(self) -> None:
        probe = (
            "import io, json, sys\n"
            f"sys.path.insert(0, {str(SKILL)!r})\n"
            "import plan_summary_hook\n"
            "sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps("
            "{'hook_event_name': 'SessionStart', 'cwd': '/'}).encode()))\n"
            "plan_summary_hook.main()\n"
            "print(sorted(m for m in sys.modules if m.startswith('compass_runtime')))\n"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", probe],
            env=self.env("hull"),
            capture_output=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertEqual((result.returncode, result.stderr, result.stdout), (0, "", "[]\n"))

    def test_the_hook_finds_the_same_home_as_the_terminal_client(self) -> None:
        self.assertEqual(plan_summary_hook.SETTINGS_FILENAME, settings.FILENAME)
        for environ in (
            {},
            {"COMPASS_HOME": ""},
            {"COMPASS_HOME": "   "},
            {"COMPASS_HOME": str(self.home)},
            {"COMPASS_HOME": "relative/home"},
        ):
            with self.subTest(environ=environ):
                self.assertEqual(
                    plan_summary_hook.state_home(environ), terminal_client.state_home(environ)
                )

    def test_only_three_open_asks_are_shown_and_the_rest_are_counted(self) -> None:
        self.setup_summary()
        self.log.write_text(
            "ask paint:1 Other lane?\n"
            "ask hull:1 First?\nask hull:2 Answered?\nanswer hull:2\n"
            "ask hull:3 Second?\nask hull:4 Third?\nask hull:5 Fourth?\nask hull:6 Fifth?\n",
            encoding="utf-8",
        )
        self.assertEqual(
            self.preview().splitlines()[-4:],
            ["Ask: First?", "Ask: Second?", "Ask: Third?", "More open asks: 2"],
        )

    def test_summary_uses_only_published_values_over_both_plan_fixtures(self) -> None:
        for fixture, data, briefs, events in (
            (
                "stand-in",
                {
                    **STAND_IN,
                    "goals": MEASURED_GOALS,
                    "tracker": tracker(hull="fixed", paint="stuck", mast="driving"),
                },
                (
                    (
                        "hull.md",
                        "## Goal\nRestore the model ship\n## Done\nThe model floats.\n*Serves*: G1",
                    ),
                    ("paint.md", "## Goal\nPaint the deck\n\n*Serves*: G1"),
                    ("mast.md", "## Goal\nhttps://mast.example.test/p?key=CANARY Rig it"),
                ),
                (
                    "2026-01-02T03:04:05Z ask hull:1 Hull question?\n"
                    "ask paint:2 Another lane?\nask hull:3 Answered?\nanswer hull:3\n"
                    + "".join(f"ask mast:{n} Mast {n}?\n" for n in range(5))
                ),
            ),
            (
                "variant",
                VARIANT,
                (("hull.brief.md", "**Objective:** Align the mount\n**Exit:** No wobble."),),
                "2026-01-02T03:04:05Z ASK hull a1 Which mount?\n",
            ),
        ):
            with self.subTest(fixture=fixture):
                for brief in self.briefs.iterdir():
                    brief.unlink()
                self.write_sources(data)
                lane_column = (
                    {"lane_column": "Lane", "words": WORDS} if fixture == "stand-in" else {}
                )
                self.configure(
                    fixture,
                    summary={"enabled": True},
                    **({"tracker": lane_column} if lane_column else {}),
                )
                for name, text in briefs:
                    (self.briefs / name).write_text(text, encoding="utf-8")
                self.log.write_text(events, encoding="utf-8")
                published = self.board()
                states = {lane["id"]: lane["state"] for lane in published["lanes"]}
                primary = [goal["lanes"] for goal in published["goals"] if goal["proposal"] is None]
                for lane in published["lanes"]:
                    asks = [
                        ask["text"]
                        for ask in published["asks"]
                        if ask["lane"] and ask["lane"]["id"] == lane["id"]
                    ]
                    serving = [goal for goal in primary if lane["id"] in goal]
                    counted = [
                        states[other]
                        for goal in serving[:1]
                        for other in goal
                        if states.get(other) not in (None, "dropped", "Status not recognised")
                    ]
                    progress = "not measured"
                    if len(serving) == 1 and counted:
                        done = counted.count("done")
                        unit = "lane is" if len(counted) == 1 else "lanes are"
                        progress = f"{done} of {len(counted)} {unit} done"
                    fields = [
                        ("Goal", lane["title"]),
                        ("Done when", lane["doneWhen"]),
                        ("Progress", progress),
                        ("Lane state", publish._STATE_WORDS.get(lane["state"], "not measured")),
                        *(("Ask", text) for text in asks[:3]),
                    ]
                    if len(asks) > 3:
                        fields.append(("More open asks", str(len(asks) - 3)))
                    expected = "".join(f"{k}: {v}\n" for k, v in fields if v is not None)
                    with self.subTest(lane=lane["id"]):
                        self.assertEqual(self.preview("--lane", lane["id"]), expected)
                        self.assertEqual(self.context(lane=lane["id"]), expected.rstrip("\n"))
                        if lane["id"] == "hull":
                            self.assertEqual(self.context(), expected.rstrip("\n"))
                        self.assertNotIn("2026-01-02", expected)
                        self.assertNotIn("CANARY", expected)

    def test_canaries_from_refused_and_unpublished_sources_stay_out_of_preview(self) -> None:
        self.setup_summary()
        private = self.root / "sealed"
        private.mkdir()
        (private / "private.md").write_text("## Goal\nCANARY_PRIVATE\n", encoding="utf-8")
        self.configure(
            private={"roots": [str(private)]},
            summary={"enabled": True},
        )
        private_alias = self.root / "alias"
        private_alias.symlink_to(private, target_is_directory=True)
        (self.briefs / "private.md").symlink_to(private_alias / "private.md")
        (self.briefs / "outside.txt").write_text("## Goal\nCANARY_OUTSIDE\n", encoding="utf-8")
        (self.briefs / "hard.md").hardlink_to(self.briefs / "outside.txt")
        links = (
            "https://key.example.test/p?key=CANARY_KEY",
            "https://code.example.test/p?code=CANARY_CODE",
            "https://hook.example.test/webhooks/CANARY_HOOK",
            "https://magic.example.test/magic/CANARY_MAGIC",
            "https://share.example.test/share/CANARY_SHARE",
        )
        self.write_brief("hull", " ".join(links[:2]), " ".join(links[2:]))
        self.log.write_bytes(
            b"ask hull:1 https://ask.example.test/?key=CANARY_ASK\n"
            b"free text CANARY_RAW\n"
            b'{"text":"CANARY_JSON"}\n'
            b"unknown hull:2 CANARY_VERB\n"
            b"ask hull:3 CANARY_OVERLONG " + b"x" * 512 + b"\n"
            b"ask hull:4 CANARY_CR\rspoof\n"
            b"ask hull:5 CANARY_CONTROL\x1b[0m\n"
        )
        summary = self.preview()
        self.assertIn("key.example.test", summary)
        self.assertIn("ask.example.test", summary)
        self.assertNotIn("CANARY_", summary)
        self.assertNotIn("https://", summary)
        for lane in ("private", "outside", "hard"):
            self.assertEqual(self.preview("--lane", lane), "")
        (self.briefs / ".RESTRICTED").touch()
        self.assertEqual(self.preview(), "")
        self.assert_silent()

    def test_oversize_text_is_cut_whole_and_counts_omitted_asks(self) -> None:
        self.setup_summary()
        self.write_brief("hull", "⚓" * 198, "船" * 270 + " xoxb-225556655-example-token")
        self.log.write_text(
            "".join(f"ask hull:{i} {'帆' * 160}{i}\n" for i in range(5)), encoding="utf-8"
        )
        text = self.preview()
        lines = text.splitlines()
        self.assertLessEqual(len(text.encode()), 1500)
        self.assertLessEqual(len(lines), 12)
        self.assertEqual(
            [line.split(": ", 1)[0] for line in lines],
            ["Goal", "Done when", "Progress", "Lane state", "Ask", "Ask", "Ask", "More open asks"],
        )
        self.assertNotIn("225556655", text)
        for index, line in enumerate(lines[4:7]):
            self.assertTrue(f"Ask: {'帆' * 160}{index}".startswith(line.removesuffix("…")))
        self.assertEqual(lines[-1], "More open asks: 2")

        self.write_brief("hull", "Restore the model ship", "Mask xoxb-225556655-example-token")
        text = self.preview()
        self.assertIn("Done when: Mask xoxb-…REDACTED", text.splitlines())

    def test_the_preview_survives_a_non_utf8_terminal(self) -> None:
        self.setup_summary()
        self.write_brief("hull", "Restore the ⚓ ship", "The model floats.")
        result = subprocess.run(
            server_command("--plan-slice"),
            cwd=self.hull,
            env={**self.env(), "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"},
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual((result.returncode, result.stderr), (0, b""))
        self.assertEqual(result.stdout.decode("utf-8"), EXPECTED.replace("the model", "the ⚓"))


class PlanSliceOptionsTest(unittest.TestCase):
    def test_plan_slice_refuses_other_operations(self) -> None:
        for extra in (
            ("--stop",),
            ("--daemon",),
            ("--sessions",),
            ("--port", "9999"),
            ("--status",),
            ("--forget",),
        ):
            with self.subTest(extra=extra):
                result = subprocess.run(
                    [sys.executable, str(SERVER_PATH), "--plan-slice", *extra],
                    env={**os.environ, "COMPASS_HOME": "/nonexistent/compass-home"},
                    capture_output=True,
                    encoding="utf-8",
                    timeout=20,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("--plan-slice", result.stderr)

    def test_lane_needs_plan_slice(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SERVER_PATH), "--lane", "hull"],
            capture_output=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--lane requires --plan-slice", result.stderr)


@unittest.skipIf(GIT is None or os.name == "nt", "Needs Git and POSIX directory descriptors")
class PlanSummarySpeedTest(SummaryHarness):
    # Measures the registered hook's wall time against its two-second harness limit.
    REAL_TIME_TESTS = True

    def test_only_the_selected_lane_is_read_and_sanitized(self) -> None:
        self.setup_summary()
        for n in range(20):
            self.write_brief(f"lane{n}", f"Other lane {n}", "Done.")
        self.log.write_text(
            "ask hull:1 Is the hull ready?\n"
            + "".join(f"ask lane{n}:{n} Unrelated {n}?\n" for n in range(500)),
            encoding="utf-8",
        )
        read_brief = sources.Sources.read_brief
        with (
            mock.patch.object(
                sources.Sources, "read_brief", autospec=True, side_effect=read_brief
            ) as briefs,
            mock.patch.object(
                records, "redact_secrets", side_effect=records.redact_secrets
            ) as redact,
        ):
            summary = publish.session_summary(str(self.home), lane="hull")
        self.assertEqual(summary, EXPECTED.rstrip("\n"))
        self.assertEqual([call.args[1] for call in briefs.call_args_list], ["hull.md"])
        scanned = [str(call.args[0]) for call in redact.call_args_list]
        self.assertFalse(any("Unrelated" in text or "Other lane" in text for text in scanned))

    def test_a_dense_log_and_a_full_brief_folder_fit_the_harness_limit(self) -> None:
        self.setup_summary()
        for n in range(196):
            self.write_brief(f"lane{n}", f"Other lane {n}", "Done.")
        with self.log.open("a", encoding="utf-8") as log:
            index = 0
            while True:
                line = f"ask lane{index % 196}:{index} Q\n"
                if log.tell() + len(line) > 1 << 20:
                    break
                log.write(line)
                index += 1
        self.assertGreater(index, 50_000)
        start = time.monotonic()
        result = self.run_hook()
        elapsed = time.monotonic() - start
        self.assertEqual(
            json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"],
            EXPECTED.rstrip("\n"),
        )
        self.assertLess(elapsed, 1.5)


class PlanSummaryFormatTest(unittest.TestCase):
    LANE: ClassVar[dict[str, Any]] = {"id": "hull", "title": "Carve", "doneWhen": None}

    def summary(
        self,
        snapshot: summary_states.Snapshot | None,
        *,
        lane: dict[str, Any] | None = None,
        asks: Sequence[str | None] = (),
    ) -> str:
        return publish._summary(lane or self.LANE, list(asks), snapshot)

    def test_lane_state_words_are_a_closed_table(self) -> None:
        self.assertEqual(set(publish._STATE_WORDS), {*publish.LANE_STATES})
        self.assertEqual(
            publish._STATE_WORDS,
            {
                "not_started": "Planned",
                "running": "In progress",
                "waiting": "Waiting",
                "blocked": "Blocked",
                "done": "Done",
                "dropped": "Dropped",
                "Status not recognised": "Status not recognised",
            },
        )
        for state, word in publish._STATE_WORDS.items():
            with self.subTest(state=state):
                self.assertIn(
                    f"Lane state: {word}\n", self.summary(_snapshot({"hull": state}, [])) + "\n"
                )

    def test_an_unknown_or_missing_state_is_not_measured(self) -> None:
        for snapshot in (
            None,
            _snapshot({}, [["hull"]]),
            _snapshot({"paint": "done"}, [["hull", "paint"]]),
        ):
            with self.subTest(snapshot=snapshot):
                lines = self.summary(snapshot).splitlines()
                self.assertIn("Lane state: not measured", lines)
        self.assertIn(
            "Progress: not measured",
            self.summary(_snapshot({}, [["hull"]])).splitlines(),
        )
        # A word outside the closed table is never echoed, even if one reached the snapshot.
        summary = self.summary(_snapshot({"hull": "CANARY_RAW", "x": "DONE"}, [["hull", "x"]]))
        self.assertNotIn("CANARY", summary)
        self.assertEqual(
            summary.splitlines()[-2:], ["Progress: not measured", "Lane state: not measured"]
        )

    def _goal(self, states: Sequence[str | None]) -> str:
        ids = [f"l{n}" for n in range(len(states))]
        snapshot = _snapshot(
            {i: s for i, s in zip(ids, states, strict=True) if s is not None} | {"x": "done"},
            [ids, ["x"]],
        )
        return self.summary(snapshot, lane={"id": "l0", "title": "T", "doneWhen": None})

    def test_progress_counts_done_among_measured_lanes_serving_the_goal(self) -> None:
        for states, progress in (
            (["done", "running"], "1 of 2 lanes are done"),
            (["done"], "1 of 1 lane is done"),
            (["running", "blocked"], "0 of 2 lanes are done"),
            (["running"], "0 of 1 lane is done"),
            (["done", None, "Status not recognised"], "1 of 1 lane is done"),
            (["done", "dropped", "waiting", "not_started"], "1 of 3 lanes are done"),
            (["done", "dropped"], "1 of 1 lane is done"),
            (["dropped"], "not measured"),
            (["dropped", None, "Status not recognised"], "not measured"),
            ([None, None], "not measured"),
            (["Status not recognised"], "not measured"),
        ):
            with self.subTest(states=states):
                summary = self._goal(states)
                self.assertIn(f"Progress: {progress}\n", summary + "\n")
                self.assertNotIn("0 of 0", summary)

    def test_progress_is_not_measured_without_exactly_one_serving_goal(self) -> None:
        self.assertIn("Progress: not measured", self.summary(_snapshot({"hull": "done"}, [])))
        self.assertIn(
            "Progress: not measured",
            self.summary(_snapshot({"hull": "done"}, [["hull"], ["hull", "x"]])),
        )

    def test_draft_goals_are_not_saved_beside_primary_goals(self) -> None:
        projected = {
            "lanes": [
                {"id": "hull", "state": "done"},
                {"id": "paint", "state": "running"},
                {"id": "mast", "state": None},
            ],
            "goals": [
                {"lanes": ["hull", "paint"], "proposal": None},
                {"lanes": ["hull"], "proposal": "Proposed, not merged"},
                {"lanes": [], "proposal": None},
            ],
        }
        snapshot = summary_states.from_published(projected)
        self.assertEqual(snapshot.states, {"hull": "done", "paint": "running"})
        self.assertEqual(snapshot.goals, (("hull", "paint"),))
        self.assertIn("Progress: 1 of 2 lanes are done", self.summary(snapshot))

    def test_oversize_fields_are_cut_not_dropped(self) -> None:
        summary = self.summary(
            None, lane={"id": "hull", "title": "🚀" * 512, "doneWhen": "Short done."}
        )
        lines = summary.splitlines()
        self.assertTrue(lines[0].startswith("Goal: 🚀"))
        self.assertTrue(lines[0].endswith("…"))
        self.assertEqual(lines[1], "Done when: Short done.")

    def test_asks_keep_their_order_and_count_only_what_is_left_out(self) -> None:
        lines = self.summary(None, asks=["帆" * 500, "Second ask?", "Third ask?"]).splitlines()
        self.assertTrue(lines[-3].startswith("Ask: 帆"))
        self.assertEqual(lines[-2:], ["Ask: Second ask?", "Ask: Third ask?"])
        big = {"id": "hull", "title": "a" * 506, "doneWhen": "b" * 501}
        lines = self.summary(None, lane=big, asks=["c" * 390]).splitlines()
        self.assertTrue(lines[-1].startswith("Ask: ccc"))
        self.assertFalse(any(line.startswith("More open asks") for line in lines))
        lines = self.summary(None, asks=["One?", None, "Two?", "Three?", "Four?"]).splitlines()
        self.assertEqual(lines[-4:], ["Ask: One?", "Ask: Two?", "Ask: Three?", "More open asks: 2"])

    def test_the_widest_summary_fits_the_caps(self) -> None:
        lane = {"id": "hull", "title": "⚓" * 512, "doneWhen": "船" * 512}
        snapshot = _snapshot(
            {f"l{n}": "running" for n in range(4096)} | {"hull": "Status not recognised"},
            [["hull", *(f"l{n}" for n in range(4096))]],
        )
        summary = self.summary(snapshot, lane=lane, asks=["帆" * 512] * 999_999)
        self.assertLessEqual(len(summary.encode("utf-8")), 1500)
        self.assertLessEqual(len(summary.splitlines()), 12)
        self.assertTrue(summary.endswith("More open asks: 999996"))

    def test_a_cut_keeps_a_redaction_marker_whole(self) -> None:
        marker = records.SECRET_MARKER
        for pad in range(280, 330):
            value = "x" * pad + " xoxb-" + marker + " tail"
            first = self.summary(None, lane={"id": "hull", "title": value, "doneWhen": None})
            first = first.splitlines()[0]
            with self.subTest(pad=pad):
                self.assertTrue(first.endswith(("…", " tail")))
                kept = first.removesuffix("…")
                self.assertFalse(any(kept.endswith(marker[:n]) for n in range(2, len(marker))))

    def test_a_value_that_is_not_one_line_is_left_out(self) -> None:
        for value in ("two\nlines", "bidi \u202e text", "nul \x00"):
            with self.subTest(value=value):
                summary = self.summary(None, lane={"id": "hull", "title": value, "doneWhen": None})
                self.assertFalse(summary.startswith("Goal:"))
