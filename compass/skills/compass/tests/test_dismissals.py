"""The dismissal store: one of the two files Compass writes on the reader's behalf.

Every test here builds its own application over stub harnesses, the way
`ApplicationIsolationTest` does, because the subject is what `collect` publishes
rather than what any real store contains.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

from compass_runtime import aggregate, cli, dismissals
from compass_runtime import sessions as runtime_sessions

from .support import make_config
from .support import os_name as support_os_name

if TYPE_CHECKING:
    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState


def _spec(key: str, rows: list[dict[str, Any]]) -> aggregate.HarnessSpec:
    """A stub harness that publishes exactly the rows it was handed."""

    def discover(config: RuntimeConfig, state: RuntimeState) -> bool:
        del config, state
        return True

    def collect(
        config: RuntimeConfig,
        state: RuntimeState,
        now: float,
        window_hours: float,
        show_all: bool,
    ) -> list[dict[str, Any]]:
        del config, state, now, window_hours, show_all
        out = []
        for row in rows:
            session = runtime_sessions.base_session(key, row["sid"], "proj")
            session.update(row)
            out.append(session)
        return out

    return aggregate.HarnessSpec(key=key, label=key.title(), discover=discover, collect=collect)


class DismissalStoreTestCase(unittest.TestCase):
    """One temporary state home per test, so no test reads another's store."""

    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        self.state_home = self._home.name
        self.diagnostics: list[str] = []
        self.popups: list[str] = []

    def runtime(self, **changes: Any) -> tuple[RuntimeConfig, RuntimeState]:
        from compass_runtime.state import build_runtime_state  # noqa: PLC0415

        fields: dict[str, Any] = {
            "state_home": self.state_home,
            "state_dir": Path(self.state_home),
            "os_name": support_os_name(),
        }
        fields.update(changes)
        config = make_config(**fields)
        return config, build_runtime_state(config, started=1_700_000_000.0)

    def application(
        self,
        harnesses: tuple[aggregate.HarnessSpec, ...],
        *,
        clock: float = 5_000.0,
        config: RuntimeConfig | None = None,
        state: RuntimeState | None = None,
    ) -> aggregate.Application:
        if config is None or state is None:
            config, state = self.runtime()
        return aggregate.Application(
            config,
            state,
            harnesses,
            native_notifier=lambda platform: f"stub@{platform}",
            popup_notifier=lambda title, message: self.popups.append(f"{title}:{message}"),
            diagnostic_sink=self.diagnostics.append,
            clock=lambda: clock,
        )

    def write_store(self, payload: object) -> str:
        path = os.path.join(self.state_home, "compass-dismissals.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload if isinstance(payload, str) else json.dumps(payload))
        return path


class SubtractionTest(DismissalStoreTestCase):
    def test_a_dismissed_row_leaves_the_payload_and_every_summary_count(self) -> None:
        harness = _spec(
            "alpha",
            [
                {
                    "sid": "blocked",
                    "state": "needs_input",
                    "active": True,
                    "last_activity": 4_000.0,
                },
                {"sid": "busy", "state": "working", "active": True, "last_activity": 4_900.0},
            ],
        )
        config, state = self.runtime()
        self.write_store(
            {
                "v": 1,
                "entries": [
                    {"harness": "alpha", "sid": "blocked", "at": 4_500.0, "seen_activity": 4_500.0}
                ],
            }
        )
        data = self.application((harness,), config=config, state=state).collect(show_all=True)

        self.assertEqual(["busy"], [s["sid"] for s in data["sessions"]])
        self.assertEqual(0, data["summary"]["needs_input"])
        self.assertEqual(1, data["summary"]["active_sessions"])
        self.assertEqual(1, data["cleared"])

    def test_a_dismissal_lapses_once_the_session_writes_again(self) -> None:
        harness = _spec(
            "alpha",
            [{"sid": "blocked", "state": "needs_input", "active": True, "last_activity": 4_600.0}],
        )
        config, state = self.runtime()
        self.write_store(
            {
                "v": 1,
                "entries": [
                    {"harness": "alpha", "sid": "blocked", "at": 4_500.0, "seen_activity": 4_500.0}
                ],
            }
        )
        data = self.application((harness,), config=config, state=state).collect(show_all=True)

        self.assertEqual(["blocked"], [s["sid"] for s in data["sessions"]])
        self.assertEqual(1, data["summary"]["needs_input"])
        self.assertEqual(0, data["cleared"])

    def test_forget_keeps_dismissed_and_marked_read_sessions(self) -> None:
        config, state = self.runtime()
        self.assertTrue(dismissals.dismiss(config, state, "claude", "risk", now=4_500.0))
        self.assertTrue(dismissals.dismiss(config, state, "codex", "read", now=4_501.0))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli._forget_stores(config), 0)
        self.assertEqual(
            {(entry["harness"], entry["sid"]) for entry in dismissals.load(config)},
            {("claude", "risk"), ("codex", "read")},
        )

    def test_the_watermark_is_the_servers_own_clock_not_the_callers(self) -> None:
        """A dismissal can never outlive the session's next write.

        The caller sends no timestamp at all, so there is no value it could send
        that would hide a row forever: the watermark is this process's clock at
        the moment of the dismissal, and any later write exceeds it.
        """
        config, state = self.runtime()
        dismissals.dismiss(config, state, "alpha", "blocked", now=4_500.0)
        entries = dismissals.active(config, state)

        self.assertEqual(1, len(entries))
        self.assertEqual(4_500.0, entries[0]["seen_activity"])
        self.assertEqual(4_500.0, entries[0]["at"])


class StoreFailureTest(DismissalStoreTestCase):
    def test_a_corrupt_store_hides_nothing(self) -> None:
        harness = _spec(
            "alpha",
            [{"sid": "blocked", "state": "needs_input", "active": True, "last_activity": 4_000.0}],
        )
        for payload in (
            '{"v": 1, "entries": [{"harness": "alpha", "sid": "blo',  # truncated
            "[]",  # not an object
            '{"v": 1, "entries": {"harness": "alpha"}}',  # entries not a list
            '{"v": 1, "entries": [null, 7, "alpha"]}',  # entries are not objects
            "",  # empty
            # Deep enough to raise RecursionError rather than ValueError, and
            # still under the read cap so the parser is actually reached. The same
            # depth `test_read_state_rejects_a_corrupt_file_instead_of_raising`
            # uses, because it is the same parser and the same failure.
            "[" * 30_000 + "]" * 30_000,
        ):
            with self.subTest(payload=payload[:24]):
                config, state = self.runtime()
                self.write_store(payload)
                data = self.application((harness,), config=config, state=state).collect(
                    show_all=True
                )
                self.assertEqual(["blocked"], [s["sid"] for s in data["sessions"]])
                self.assertEqual(0, data["cleared"])

    def test_a_store_past_the_read_cap_hides_nothing(self) -> None:
        config, state = self.runtime()
        self.write_store({"v": 1, "entries": [{"harness": "a" * 200_000, "sid": "x"}]})
        self.assertEqual((), dismissals.load(config))
        del state

    def test_an_unwritable_home_still_serves_and_reports(self) -> None:
        config, state = self.runtime(state_home=os.path.join(self.state_home, "missing", "\0bad"))
        persisted = dismissals.dismiss(
            config, state, "alpha", "blocked", now=4_500.0, diagnostic_sink=self.diagnostics.append
        )
        self.assertFalse(persisted)
        self.assertTrue(any("dismissal" in line for line in self.diagnostics), self.diagnostics)
        # The row still leaves this session's board: the write failed, the intent
        # did not.
        self.assertEqual(1, len(dismissals.active(config, state)))

    def test_a_hostile_entry_cannot_widen_a_row(self) -> None:
        # The store is a file any local process can rewrite, and both fields reach
        # the DOM through the reveal endpoint. Written as escapes rather than as
        # the literal characters: a right-to-left override sitting in this source
        # would reorder the test itself for the next reader.
        config, _state = self.runtime()
        self.write_store(
            {
                "v": 1,
                "entries": [
                    {
                        "harness": "al\u202epha",
                        "sid": "x" * 10_000,
                        "at": "soon",
                        "seen_activity": None,
                    },
                    {"harness": "", "sid": "nameless", "at": 1.0, "seen_activity": 1.0},
                ],
            }
        )
        entries = dismissals.load(config)
        self.assertEqual(1, len(entries), entries)
        entry = entries[0]
        self.assertNotIn("\u202e", entry["harness"])
        self.assertLessEqual(len(entry["sid"]), dismissals.KEY_CAP_CHARS)
        self.assertEqual((0.0, 0.0), (entry["at"], entry["seen_activity"]))

    def test_the_store_is_capped_and_evicts_the_oldest_dismissal(self) -> None:
        config, state = self.runtime(dismissal_max_entries=3)
        for index in range(5):
            dismissals.dismiss(config, state, "alpha", f"s{index}", now=100.0 + index)
        self.assertEqual(
            ["s2", "s3", "s4"], sorted(e["sid"] for e in dismissals.active(config, state))
        )
        # And the file agrees with the cache: the bound is applied on the write,
        # not only in memory.
        self.assertEqual(3, len(dismissals.load(config)))


class DisabledTest(DismissalStoreTestCase):
    def test_the_rollback_switch_leaves_the_store_unread_and_unwritten(self) -> None:
        harness = _spec(
            "alpha",
            [{"sid": "blocked", "state": "needs_input", "active": True, "last_activity": 4_000.0}],
        )
        config, state = self.runtime(dismissals_enabled=False)
        self.write_store(
            {
                "v": 1,
                "entries": [
                    {"harness": "alpha", "sid": "blocked", "at": 4_500.0, "seen_activity": 4_500.0}
                ],
            }
        )
        data = self.application((harness,), config=config, state=state).collect(show_all=True)

        self.assertEqual(["blocked"], [s["sid"] for s in data["sessions"]])
        self.assertEqual(0, data["cleared"])
        self.assertNotIn("dismiss", data)
        self.assertFalse(dismissals.dismiss(config, state, "alpha", "blocked", now=1.0))

    def test_the_capability_flag_rises_only_with_the_feature_on(self) -> None:
        harness = _spec("alpha", [{"sid": "x", "state": "idle", "active": False}])
        config, state = self.runtime()
        data = self.application((harness,), config=config, state=state).collect(show_all=True)
        self.assertIs(True, data["dismiss"])


class RestoreTest(DismissalStoreTestCase):
    def test_restoring_puts_the_row_back(self) -> None:
        harness = _spec(
            "alpha",
            [{"sid": "blocked", "state": "needs_input", "active": True, "last_activity": 4_000.0}],
        )
        config, state = self.runtime()
        dismissals.dismiss(config, state, "alpha", "blocked", now=4_500.0)
        hidden = self.application((harness,), config=config, state=state).collect(show_all=True)
        self.assertEqual([], hidden["sessions"])

        self.assertTrue(dismissals.restore(config, state, "alpha", "blocked"))
        shown = self.application((harness,), config=config, state=state).collect(show_all=True)
        self.assertEqual(["blocked"], [s["sid"] for s in shown["sessions"]])
        self.assertEqual((), dismissals.load(config))

    def test_a_second_compass_writing_the_file_is_seen_on_the_next_collection(self) -> None:
        """The file is the record; the in-memory list is only this run's copy."""
        harness = _spec(
            "alpha",
            [{"sid": "blocked", "state": "needs_input", "active": True, "last_activity": 4_000.0}],
        )
        config, state = self.runtime()
        application = self.application((harness,), config=config, state=state)
        self.assertEqual(1, len(application.collect(show_all=True)["sessions"]))

        other_config, other_state = self.runtime()
        dismissals.dismiss(other_config, other_state, "alpha", "blocked", now=4_500.0)

        self.assertEqual([], application.collect(show_all=True)["sessions"])


class PopupSuppressionTest(DismissalStoreTestCase):
    def test_a_cleared_session_raises_no_native_popup(self) -> None:
        from compass_runtime import notifications  # noqa: PLC0415

        config, state = self.runtime()
        dismissals.dismiss(config, state, "claude", "abcd1234", now=4_500.0)
        notifications.maybe_popup(
            config,
            state,
            notifications.PopupSubject(
                harness="claude", label="Claude", prefix="abcd1234", activity=4_000.0
            ),
            "needs_input",
            "open question",
            popup_notifier=lambda title, message: self.popups.append(f"{title}:{message}"),
        )
        self.assertEqual([], self.popups)

    def test_a_lapsed_dismissal_stops_suppressing_the_popup(self) -> None:
        from compass_runtime import notifications  # noqa: PLC0415

        config, state = self.runtime()
        dismissals.dismiss(config, state, "claude", "abcd1234", now=4_500.0)
        notifications.maybe_popup(
            config,
            state,
            notifications.PopupSubject(
                harness="claude", label="Claude", prefix="abcd1234", activity=4_600.0
            ),
            "needs_input",
            "open question",
            popup_notifier=lambda title, message: self.popups.append(f"{title}:{message}"),
        )
        self.assertEqual(["Claude is waiting on you:open question"], self.popups)


class ConfigTest(DismissalStoreTestCase):
    def test_the_store_lives_beside_the_state_file_and_not_per_port(self) -> None:
        config, _state = self.runtime()
        self.assertEqual(
            os.path.join(self.state_home, "compass-dismissals.json"),
            dismissals.store_path(config),
        )

    def test_the_defaults_are_bounded(self) -> None:
        config = make_config()
        self.assertGreater(config.dismissal_max_entries, 0)
        self.assertGreater(config.dismissal_read_cap_bytes, 0)
        self.assertIs(True, config.dismissals_enabled)
        self.assertIs(True, dataclasses.replace(config, dismissals_enabled=True).dismissals_enabled)


class MatchableKeyTest(DismissalStoreTestCase):
    """DRC-4179: an unmatchable key cannot consume a slot or evict a real dismissal."""

    def test_an_unmatchable_claude_uuid_is_refused(self) -> None:
        config, state = self.runtime()
        # Full 36-char UUID for Claude: can never match an 8-character prefix row.
        uuid_sid = "12345678-1234-1234-1234-123456789abc"
        persisted = dismissals.dismiss(config, state, "claude", uuid_sid, now=1000.0)
        self.assertFalse(persisted)
        self.assertEqual((), dismissals.load(config))

    def test_an_unmatchable_entry_in_store_is_dropped_on_load(self) -> None:
        config, _state = self.runtime()
        self.write_store(
            {
                "v": 1,
                "entries": [
                    # Real 8-char Claude sid
                    {"harness": "claude", "sid": "abcd1234", "at": 100.0, "seen_activity": 100.0},
                    # Junk 36-char UUID sid that can never match
                    {
                        "harness": "claude",
                        "sid": "12345678-1234-1234-1234-123456789abc",
                        "at": 200.0,
                        "seen_activity": 200.0,
                    },
                ],
            }
        )
        loaded = dismissals.load(config)
        self.assertEqual(1, len(loaded))
        self.assertEqual("abcd1234", loaded[0]["sid"])


if __name__ == "__main__":
    unittest.main()
