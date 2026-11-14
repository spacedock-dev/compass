"""Terminal-steering text is removed from every printed CLI surface, 8-bit C1 spellings included."""

from __future__ import annotations

import http.client
import io
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    diagnostics,
    lifecycle,
    terminal_client,
    terminal_drift,
    terminal_summary,
)
from compass_runtime import terminal_sessions as ts

from .test_terminal_summary import Board

ESC = "\x1b"
# A marker, not a credential: it only has to be findable in the output.
PAYLOAD = "SECRETPAYLOAD"
OSC52_8BIT = f"\x9d52;c;{PAYLOAD}\x9c"
OSC52_7BIT = f"{ESC}]52;c;{PAYLOAD}\x07"
HOSTILE = (
    f"a{OSC52_8BIT}b{OSC52_7BIT}c\x90q;{PAYLOAD}{ESC}\\d\x98{PAYLOAD}\x9c"
    f"e\x9e{PAYLOAD}\x9cf\x9f{PAYLOAD}\x9cg{ESC}]8;;http://x\x07link{ESC}]8;;\x07"
    f"{ESC}[31mred\x9b0m \u202eevil\u2066 \r\x08z"
)


class PrintableStringSequencesTest(unittest.TestCase):
    def test_every_string_sequence_goes_with_its_payload(self) -> None:
        text = ts.printable(HOSTILE)
        self.assertNotIn(PAYLOAD, text)
        self.assertEqual(text, "abcdefglinkred evil z")

    def test_each_terminator_ends_the_sequence(self) -> None:
        for starter, end in (
            ("\x9d", "\x07"),
            ("\x9d", f"{ESC}\\"),
            ("\x9d", "\x9c"),
            ("\x90", "\x9c"),
            (f"{ESC}P", f"{ESC}\\"),
        ):
            with self.subTest(starter=starter, end=end):
                self.assertEqual(ts.printable(f"x{starter}{PAYLOAD}{end}y"), "xy")

    def test_unterminated_sequence_ends_at_its_line(self) -> None:
        self.assertEqual(ts.printable(f"keep\x9d52;c;{PAYLOAD}\nnext line"), "keep next line")
        self.assertEqual(ts.printable_text(f"one\x90{PAYLOAD}\n  two {ESC}]0;t"), "one\n  two ")

    def test_non_ascii_passes_through(self) -> None:
        text = "/Users/zoë/プロジェクト/\U0001f600 café"
        self.assertEqual(ts.printable(text), text)
        self.assertEqual(ts.printable_text(text), text)

    def test_printable_text_keeps_structure_byte_for_byte(self) -> None:
        report = "Compass diagnostics\n  home       /x/y\n    [  --] /z\n\nStores\n"
        self.assertEqual(ts.printable_text(report), report)
        self.assertEqual(ts.printable_text(None), "")

    def test_printable_text_cleans_line_by_line(self) -> None:
        text = ts.printable_text(f"  a{OSC52_8BIT}\n\tb\r\n  c\u202e")
        self.assertEqual(text, "  a\n b \n  c")


class DiagnoseTest(unittest.TestCase):
    def _report(self, hostile: str) -> dict[str, Any]:
        return {
            "platform": "p",
            "python": "3",
            "executable": hostile,
            "home": hostile,
            "compass_home": None,
            "sqlite": {"version": None, "error": hostile},
            "tripwires": {"path": None, "error": hostile},
            "unasked": {"enabled": False},
            "env": {"K": hostile},
            "harnesses": [{"label": "h", "discovered": True, "sessions": 1, "error": hostile}],
            "store_errors": {hostile: hostile},
            "project_scripts": [],
            "reader_checks": None,
            "stores": {
                "k": {
                    "candidates": [
                        {
                            "path": hostile,
                            "kind": "dir",
                            "entries": 1,
                            "readable": True,
                            "error": hostile,
                        }
                    ]
                }
            },
        }

    def test_rendered_report_is_clean_and_keeps_its_shape(self) -> None:
        clean = diagnostics.render_diagnosis(self._report("plain"))
        text = diagnostics.render_diagnosis(self._report(HOSTILE))
        self.assertNotIn(PAYLOAD, text)
        self.assertNotRegex(text, "[\x00-\x09\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
        self.assertEqual(text.count("\n"), clean.count("\n"))
        self.assertTrue(text.startswith("Compass diagnostics\n  platform   p (python 3)\n"))

    def test_ordinary_report_is_unchanged(self) -> None:
        report = self._report("/Users/zoë/プ")
        text = diagnostics.render_diagnosis(report)
        self.assertEqual(text, ts.printable_text(text))

    def test_reader_checks_are_clean(self) -> None:
        report = {"path": HOSTILE, "error": HOSTILE, "projects": 0, "ignored": []}
        text = diagnostics.render_reader_checks(report)
        self.assertNotIn(PAYLOAD, text)


class DriftEmitTest(unittest.TestCase):
    def test_emit_cleans_every_line(self) -> None:
        out = io.StringIO()
        terminal_drift._emit(out, ["  keep " + HOSTILE, "  second"])
        text = out.getvalue()
        self.assertNotIn(PAYLOAD, text)
        self.assertTrue(text.endswith("\n  second\n"))
        self.assertTrue(text.startswith("  keep abcdefg"))


class VersionGuardTest(unittest.TestCase):
    def test_a_hostile_dashboard_version_cannot_steer_the_terminal(self) -> None:
        found = terminal_client.Dashboard(4747, 1, 0.0, "9.9" + OSC52_8BIT + OSC52_7BIT)
        message = terminal_client.version_guard(found, "1.0.0") or ""
        self.assertNotIn(PAYLOAD, message)
        self.assertIn("version 9.9 ", message)


class LifecycleTest(unittest.TestCase):
    def test_log_tail_is_clean_and_keeps_lines(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            log = Path(home) / "d.log"
            log.write_bytes(f"  first\n{HOSTILE}\n    last é\n".encode())
            text = lifecycle.log_tail(str(log))
        self.assertNotIn(PAYLOAD, text)
        self.assertNotRegex(text, "[\x00-\x09\x0b-\x1f\x7f-\x9f]")
        self.assertEqual(text.split("\n")[0], "first")
        self.assertEqual(text.split("\n")[-1], "    last é")

    def test_render_status_cleans_a_recorded_pid(self) -> None:
        status = {"state": "stale", "port": 4800, "pid": "1" + OSC52_8BIT}
        self.assertNotIn(PAYLOAD, lifecycle.render_status(status))

    def test_stop_failure_text_is_clean(self) -> None:
        class Broken:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def request(self, *_args: object, **_kwargs: object) -> None:
                raise OSError(HOSTILE)

            def close(self) -> None:
                pass

        running = {"state": "running", "port": 4800, "pid": 7}
        with (
            mock.patch.object(lifecycle, "instance_status", return_value=running),
            mock.patch.object(http.client, "HTTPConnection", Broken),
            mock.patch.object(lifecycle, "await_release", return_value=False),
        ):
            message, code = lifecycle.stop_instance(mock.Mock(), 4800)
        self.assertEqual(code, 1)
        self.assertIn("could not stop port 4800", message)
        self.assertNotIn(PAYLOAD, message)
        self.assertNotRegex(message, "[\x00-\x1f\x7f-\x9f]")


class SummaryErrTest(unittest.TestCase):
    def test_refusal_reason_is_cleaned(self) -> None:
        board = Board({"exists": False})
        board.answer = (500, {"reason": HOSTILE})
        out, err = io.StringIO(), io.StringIO()
        terminal_summary.run(
            named=terminal_client.Session("claude", "s/1", "environment"),
            board=board,
            out=out,
            err=err,
        )
        self.assertIn("Summary request refused (", err.getvalue())
        self.assertNotIn(PAYLOAD, err.getvalue())
        self.assertNotRegex(err.getvalue(), "[\x00-\x09\x0b-\x1f\x7f-\x9f]")

    def test_no_stored_summary_reason_is_cleaned(self) -> None:
        board = Board({"exists": False, "job": {"reason": HOSTILE}})
        out, err = io.StringIO(), io.StringIO()
        terminal_summary.run(
            named=terminal_client.Session("claude", "s/1", "environment"),
            board=board,
            out=out,
            err=err,
        )
        self.assertNotIn(PAYLOAD, err.getvalue())


if __name__ == "__main__":
    unittest.main()
