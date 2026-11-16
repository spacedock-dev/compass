"""Terminal diagnostics keep paths and failures readable without terminal commands."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    cli,
    copied_corrections,
    declared_parent_store,
    ends,
    frontend_dev,
    history,
    interaction_prototype,
    lifecycle,
    reading_policy,
    summary_store,
    terminal_sessions,
)
from compass_runtime import io as runtime_io
from compass_runtime.config import build_runtime_config

from .support import SERVER_PATH

ATTACK = "\x1b]0;PWN\x07\x1b[31mred\x1b[0m\x00\x08\x85\u202e"
CLEAN = "red"
FORGED = "\nFORGED SUCCESS\tend"


class DiagnosticOutputTest(unittest.TestCase):
    def test_foreground_failures_cannot_send_terminal_commands(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            runtime_io.diag(f"collector {ATTACK}: {RuntimeError(ATTACK)}", print)
        self.assertEqual("collector red: red\n", output.getvalue())

    def test_a_foreground_collection_failure_cannot_forge_a_report_line(self) -> None:
        stop = mock.Mock()
        stop.wait.side_effect = [False, True]
        application = mock.Mock()
        application.state.streams.count = 1
        application.collect_json.side_effect = RuntimeError(ATTACK + FORGED)
        application.diagnostic_sink = print
        with contextlib.redirect_stdout(io.StringIO()) as output:
            lifecycle.run_producer(mock.Mock(application=application), stop=stop, interval=0)
        self.assertEqual(
            "Compass: producer collection failed: red FORGED SUCCESS end\n", output.getvalue()
        )

    def test_a_terminal_registration_failure_cannot_forge_a_report_line(self) -> None:
        with (
            mock.patch.object(Path, "is_file", return_value=True),
            mock.patch.object(
                interaction_prototype,
                "_read_registration_file",
                side_effect=interaction_prototype.RegistrationUnsupportedError(ATTACK + FORGED),
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = interaction_prototype._run_waiting_tmux_client(Path("unused"))
        self.assertEqual(1, result)
        self.assertEqual(
            "terminal registration unsupported: red FORGED SUCCESS end\n", output.getvalue()
        )

    def test_redirected_logs_keep_report_lines_without_terminal_commands(self) -> None:
        output = io.StringIO()
        runtime_io.diag(f"report\n\t{ATTACK} café\n  done", output.write)
        self.assertEqual("report\n\tred café\n  done", output.getvalue())

    def test_an_ascii_fallback_does_not_restore_hidden_payloads(self) -> None:
        written: list[str] = []

        def ascii_sink(message: str) -> None:
            message.encode("ascii")
            written.append(message)

        runtime_io.diag(f"{ATTACK} café", ascii_sink)
        self.assertEqual([r"red caf\xe9"], written)

    def test_a_frontend_asset_failure_cannot_send_terminal_commands(self) -> None:
        output = io.StringIO()
        with (
            mock.patch(
                "compass_runtime.web.page.load_frontend_page", side_effect=OSError(ATTACK + FORGED)
            ),
            contextlib.redirect_stderr(output),
        ):
            page = cli.load_frontend_page()
        self.assertIsNone(page)
        self.assertEqual(
            "Compass: cannot load frontend assets (OSError: red FORGED SUCCESS end).\n"
            "Compass: reinstall the plugin to repair this build.\n",
            output.getvalue(),
        )

    def test_a_frontend_admission_failure_cannot_send_terminal_commands(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(frontend_dev, "admit", side_effect=RuntimeError(ATTACK + FORGED)),
            contextlib.redirect_stderr(output),
        ):
            _, page = cli.prepare_frontend(
                build_runtime_config(
                    environ={}, launcher_path=SERVER_PATH, platform_name="linux", os_name="posix"
                ),
                argparse.Namespace(frontend_dev_manifest="manifest"),
            )
        self.assertIsNone(page)
        self.assertEqual(
            "Compass: cannot admit development frontend (red FORGED SUCCESS end).\n",
            output.getvalue(),
        )


class ForgetOutputTest(unittest.TestCase):
    def test_forget_paths_are_readable_in_every_store_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config = build_runtime_config(
                environ={"HOME": home + ATTACK.replace("\x00", "") + FORGED},
                launcher_path=SERVER_PATH,
                platform_name="linux",
                os_name="posix",
            )
            for deleted in (False, True):
                for annotation in (
                    annotation_store.FORGET_SWEPT,
                    annotation_store.FORGET_NOTHING,
                    annotation_store.FORGET_UNWRITABLE,
                    annotation_store.FORGET_UNTRUSTED,
                ):
                    with (
                        self.subTest(deleted=deleted, annotation=annotation),
                        mock.patch.object(history, "forget", return_value=deleted),
                        mock.patch.object(ends, "forget", return_value=deleted),
                        mock.patch.object(annotation_store, "forget", return_value=annotation),
                        mock.patch.object(copied_corrections, "forget", return_value=deleted),
                        mock.patch.object(summary_store, "forget", return_value="unwritable"),
                        mock.patch.object(declared_parent_store, "forget", return_value=False),
                        mock.patch.object(reading_policy, "forget", return_value=False),
                        contextlib.redirect_stdout(io.StringIO()) as output,
                    ):
                        cli._forget_stores(config)
                    text = output.getvalue()
                    self.assertIn(home + CLEAN, text)
                    self.assertIn("compass-history.json", text)
                    self.assertIn("summary store", text)
                    self.assertNotRegex(text, r"[\x00-\x09\x0b-\x1f\x7f-\x9f\u202e]")
                    self.assertNotIn("PWN", text)
                    self.assertTrue(all(line.startswith("Compass:") for line in text.splitlines()))

    def test_forget_refusals_print_safe_paths_and_cleanup_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home, ATTACK.replace("\x00", "") + FORGED)
            config = build_runtime_config(
                environ={"COMPASS_HOME": str(root)},
                launcher_path=SERVER_PATH,
                platform_name="linux",
                os_name="posix",
            )
            for reason in ("running", "folder", "unreadable", "lock"):
                with (
                    self.subTest(reason=reason),
                    mock.patch.object(
                        lifecycle,
                        "instance_status",
                        return_value={"state": "running" if reason == "running" else "stopped"},
                    ),
                    mock.patch.object(
                        os,
                        "listdir",
                        return_value=[] if reason == "lock" else ["compass-4554.json"],
                    ),
                    mock.patch.object(lifecycle, "read_state", return_value=None),
                    contextlib.ExitStack() as stack,
                    contextlib.redirect_stdout(io.StringIO()) as output,
                ):
                    if reason == "unreadable":
                        stack.enter_context(
                            mock.patch.object(os, "listdir", side_effect=OSError(ATTACK))
                        )
                    elif reason == "lock":
                        stack.enter_context(
                            mock.patch.object(
                                lifecycle,
                                "state_folder_lock",
                                side_effect=lifecycle.StateOwnershipError(ATTACK + FORGED),
                            )
                        )
                    self.assertEqual(1, cli._forget(config, 4553))
                text = output.getvalue()
                self.assertIn("red", text)
                self.assertNotRegex(text, r"[\x00-\x09\x0b-\x1f\x7f-\x9f\u202e]")
                self.assertNotIn("PWN", text)
                self.assertEqual(1, len(text.splitlines()))


class InvisibleOutputTest(unittest.TestCase):
    def test_hidden_format_characters_cannot_hide_terminal_words(self) -> None:
        hidden = [
            0x200B,
            *range(0x2060, 0x2065),
            0xAD,
            0x180E,
            *range(0xFFF9, 0xFFFC),
            *range(0xE0000, 0xE0080),
        ]
        for render in (terminal_sessions.printable, terminal_sessions.printable_text):
            for code in hidden:
                with self.subTest(render=render.__name__, code=hex(code)):
                    self.assertEqual("beforeafter", render("before" + chr(code) + "after"))

    def test_typed_flags_and_joined_emoji_print_unchanged(self) -> None:
        for render in (terminal_sessions.printable, terminal_sessions.printable_text):
            for region in ("gbeng", "gbsct", "gbwls", "usca", "fridf"):
                flag = "\U0001f3f4" + "".join(chr(0xE0000 + ord(c)) for c in region) + "\U000e007f"
                text = "start " + flag + " 👩‍💻 👨‍👩‍👧‍👦 🇹🇼 end"
                with self.subTest(render=render.__name__, region=region):
                    self.assertEqual(text, render(text))
                    self.assertEqual(text, render("\u200b" + text + "\U000e0061"))

    def test_unfinished_and_unknown_flag_tags_cannot_hide_terminal_words(self) -> None:
        for render in (terminal_sessions.printable, terminal_sessions.printable_text):
            for region, end in (("gbeng", ""), ("secret", "\U000e007f")):
                text = "\U0001f3f4" + "".join(chr(0xE0000 + ord(c)) for c in region) + end
                self.assertEqual("\U0001f3f4", render(text))
