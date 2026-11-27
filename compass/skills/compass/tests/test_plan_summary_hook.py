"""The terminal preview and registered session hook show the same published lane."""

from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import unittest
from typing import TYPE_CHECKING, Any
from unittest import mock

import plan_summary_hook
from compass_runtime.plan import publish, readers

from .support import SERVER_PATH, make_config, server_command
from .test_history import stub_application
from .test_plan_publish import request
from .test_plan_readers import STAND_IN, VARIANT, PlanRepoTestCase
from .test_project_script_checks import GIT

if TYPE_CHECKING:
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


@unittest.skipIf(GIT is None or os.name == "nt", "Needs Git and POSIX directory descriptors")
class PlanSummaryHookTest(PlanRepoTestCase):
    def setup_summary(self) -> None:
        self.configure(summary={"enabled": True})
        self.write_brief("hull", "Restore the model ship", "The model floats.")
        self.log.write_text("ask hull:1 Is the hull ready?\n", encoding="utf-8")

    def write_brief(self, lane: str, goal: str, done: str) -> None:
        (self.briefs / f"{lane}.md").write_text(
            f"## Goal\n{goal}\n\n## Done\n{done}\n", encoding="utf-8"
        )

    def env(self, lane: str | None = None) -> dict[str, str]:
        env = {**os.environ, "COMPASS_HOME": str(self.home)}
        env.pop("COMPASS_LANE", None)
        if lane is not None:
            env["COMPASS_LANE"] = lane
        return env

    def run_hook(
        self,
        *,
        harness: str = "claude",
        cwd: Path | None = None,
        lane: str | None = None,
        raw: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
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
        return subprocess.run(
            [sys.executable, *args[1:]],
            input=raw
            if raw is not None
            else json.dumps(
                {"hook_event_name": "SessionStart", "cwd": str(cwd or self.hull)}
            ).encode(),
            cwd=self.root,
            env=self.env(lane),
            capture_output=True,
            timeout=10,
            check=False,
        )

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
        self.write_brief("paint", "Paint the deck", "It dries.")
        self.assert_silent(cwd=nested)
        self.assertEqual(self.preview(), EXPECTED)
        (nested / ".restricted").touch()
        self.assert_silent(cwd=nested)

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

    def test_input_errors_are_silent(self) -> None:
        self.setup_summary()
        for raw in (
            b"",
            b"\xff",
            b"{",
            b"[]",
            b'{"hook_event_name":"SessionEnd","cwd":"/example"}',
            b'{"hook_event_name":"SessionStart","cwd":5}',
            b" " * (1 << 20),
        ):
            with self.subTest(size=len(raw), head=raw[:50]):
                self.assert_silent(raw=raw)

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
            mock.patch.object(readers, "read_plan", side_effect=OSError("Synthetic error")),
        ):
            self.assertEqual(plan_summary_hook.main(), 0)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_progress_is_derived_only_from_measured_published_lane_states(self) -> None:
        plan = {
            "lanes": [
                {"id": "hull", "title": "Carve", "doneWhen": None, "state": "done"},
                {"id": "paint", "title": "Paint", "doneWhen": None, "state": "in-progress"},
            ],
            "asks": [],
        }
        self.assertIn(
            "Progress: 1 of 2 lanes are done\nLane state: in-progress",
            publish._summary(plan, "paint"),
        )
        plan["lanes"][0]["state"] = None
        self.assertIn("Progress: not measured", publish._summary(plan, "paint"))

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

    def test_preview_uses_only_published_values_over_both_plan_fixtures(self) -> None:
        for fixture, sources, briefs, events in (
            (
                "stand-in",
                STAND_IN,
                ("hull.md", "## Goal\nRestore the model ship\n## Done\nThe model floats."),
                (
                    "2026-01-02T03:04:05Z ask hull:1 Hull question?\n"
                    "ask paint:2 Another lane?\nask hull:3 Answered?\nanswer hull:3\n"
                ),
            ),
            (
                "variant",
                VARIANT,
                ("hull.brief.md", "**Objective:** Align the mount\n**Exit:** No wobble."),
                "2026-01-02T03:04:05Z ASK hull a1 Which mount?\n",
            ),
        ):
            with self.subTest(fixture=fixture):
                self.write_sources(sources)
                self.configure(fixture, summary={"enabled": True})
                (self.briefs / briefs[0]).write_text(briefs[1], encoding="utf-8")
                self.log.write_text(events, encoding="utf-8")
                app = stub_application(make_config(state_home=str(self.home)), [], [])
                status, _, body = request(app)
                self.assertEqual(status, 200)
                published = json.loads(body)
                for lane in published["lanes"]:
                    asks = [
                        ask["text"]
                        for ask in published["asks"]
                        if ask["lane"] and ask["lane"]["id"] == lane["id"]
                    ]
                    fields = [
                        ("Goal", lane["title"]),
                        ("Done when", lane["doneWhen"]),
                        ("Progress", "not measured"),
                        ("Lane state", lane["state"] or "not measured"),
                        *(("Ask", text) for text in asks),
                    ]
                    summary = self.preview("--lane", lane["id"])
                    self.assertEqual(summary.splitlines(), [f"{k}: {v}" for k, v in fields])
                    self.assertNotIn("2026-01-02", summary)

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

    def test_oversize_text_uses_whole_lines_and_counts_omitted_asks(self) -> None:
        self.setup_summary()
        self.write_brief("hull", "⚓" * 198, "船" * 270 + " xoxb-225556655-example-token")
        self.log.write_text(
            "".join(f"ask hull:{i} {'帆' * 160}{i}\n" for i in range(5)), encoding="utf-8"
        )
        text = self.preview()
        lines = text.splitlines()
        self.assertLessEqual(len(text.encode()), 1500)
        self.assertLessEqual(len(lines), 12)
        self.assertIn("Goal: " + "⚓" * 198, lines)
        self.assertIn("Progress: not measured", lines)
        self.assertFalse(any(line.startswith("Done when: ") for line in lines))
        self.assertNotIn("225556655", text)
        asks = [line for line in lines if line.startswith("Ask: ")]
        self.assertLessEqual(len(asks), 3)
        self.assertTrue(all(line == f"Ask: {'帆' * 160}{i}" for i, line in enumerate(asks)))
        self.assertEqual(lines[-1], f"More open asks: {5 - len(asks)}")

        self.write_brief("hull", "Restore the model ship", "Mask xoxb-225556655-example-token")
        text = self.preview()
        self.assertIn("Done when: Mask xoxb-…REDACTED", text.splitlines())
