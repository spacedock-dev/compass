"""The history store: what this server observed, kept on this machine.

`SECURITY.md`'s "Local history (the session history store)" section is the
contract these tests hold the code to. The bounds are DEC-6's ruling (Linear
DRC-4234), not this file's preferences, and the expected values here are
literals or come from `test_sessions.DECLARED_SESSION_FIELDS` rather than from
`history.py`'s own constants — a test that reads the subject's constants proves
only that the subject is self-consistent.
"""

from __future__ import annotations

import contextlib
import io as std_io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

from compass_runtime import history
from compass_runtime import sessions as runtime_sessions
from compass_runtime.config import COMPASS_HOME_ENV, STORE_ENV_VARS

from .support import make_config
from .support import os_name as support_os_name

if TYPE_CHECKING:
    from compass_runtime.config import RuntimeConfig

# Every field that can carry operator text onto a row. The first four are the
# ones the contract's never-list enumerates; the last four are the nested
# carriers it does not, which the runtime itself enumerates and which a store
# retaining whole rows would retain. AC2 exists because the never-list is
# incomplete against the row.
#
# The Spacedock one is here because AC1 bans the `spacedock` key while nothing
# gave that ban a value to find: a widening that routed a workflow or entity
# title into the existing `project` field would pass AC1 (the key set is
# unchanged) and pass AC2 (no sentinel to look for), which was demonstrated
# with the text on disk and 46 tests green.
# Separated by `_` rather than `-`, and that is the point rather than a style.
# `history._bounded_project` trims a dash-joined label to its last two segments,
# so a sentinel routed into `project` reached the store as `SPACEDOCK-e8` while
# an `assertNotIn` for `SENTINEL-SPACEDOCK-e8` stayed green — the oracle below
# could be defeated by the truncation it is supposed to see through. Neither
# separator the bound splits on appears in these strings, so any prefix of one
# that survives a trim is still a substring of the whole.
SENTINELS = {
    "title": "SENTINEL_TITLE_e1",
    "last_prompt": "SENTINEL_PROMPT_e2",
    "state_detail": "SENTINEL_DETAIL_e3",
    "instruction": "SENTINEL_INSTRUCTION_e4",
    "task_subject": "SENTINEL_TASKSUBJECT_e5",
    "task_active_form": "SENTINEL_ACTIVEFORM_e6",
    "subagent_name": "SENTINEL_SUBAGENT_e7",
    "spacedock_workflow": "SENTINEL_SPACEDOCK_e8",
}


def loaded_row(state: str = "working", *, last_activity: float = 1_000.0) -> dict[str, Any]:
    """A published row carrying operator text in every field that can hold it."""
    row = runtime_sessions.base_session("claude", "sid-1", "recce/compass")
    row.update(
        {
            "state": state,
            "last_activity": last_activity,
            "own_activity": last_activity,
            "title": SENTINELS["title"],
            "last_prompt": SENTINELS["last_prompt"],
            "state_detail": SENTINELS["state_detail"],
            "instruction": {"text": SENTINELS["instruction"], "kind": "plan"},
            "tasks": [
                {
                    "subject": SENTINELS["task_subject"],
                    "activeForm": SENTINELS["task_active_form"],
                    "status": "in_progress",
                }
            ],
            "subagents": [{"name": SENTINELS["subagent_name"], "sid": "child-1"}],
            "spacedock": {
                "role": "first-officer",
                "workflows": [{"label": SENTINELS["spacedock_workflow"], "stages": []}],
            },
        }
    )
    return row


def stub_spec(rows: list[dict[str, Any]]) -> Any:
    """A harness whose collector returns these rows, shaped as a real one shapes."""
    from compass_runtime import aggregate  # noqa: PLC0415
    from compass_runtime import sessions as rs  # noqa: PLC0415

    def discover(config: Any, state: Any) -> bool:
        del config, state
        return True

    def collect(
        config: Any, state: Any, now: float, window_hours: float, show_all: bool
    ) -> list[dict[str, Any]]:
        del config, state, now, window_hours, show_all
        out = []
        for row in rows:
            session = rs.base_session("claude", row["sid"], "recce/compass")
            session.update(row)
            out.append(session)
        return out

    return aggregate.HarnessSpec(key="claude", label="Claude", discover=discover, collect=collect)


def stub_application(
    config: RuntimeConfig,
    rows: list[dict[str, Any]],
    sink: list[str],
    *,
    now: float = 5_000.0,
    lane: bool = True,
) -> Any:
    """An application over one stub harness, built the way the CLI builds one."""
    from compass_runtime import aggregate  # noqa: PLC0415
    from compass_runtime import history as h  # noqa: PLC0415
    from compass_runtime.state import build_runtime_state  # noqa: PLC0415

    state = build_runtime_state(config, started=1_700_000_000.0)
    application = aggregate.Application(
        config,
        state,
        (stub_spec(rows),),
        native_notifier=lambda platform: f"stub@{platform}",
        popup_notifier=lambda *_: None,
        diagnostic_sink=sink.append,
        clock=lambda: now,
    )
    if lane:
        application.history_lane = h.Lane(config, diagnostic_sink=sink.append)
    return application


def seed_claude_transcript(projects: Path, encoded: str, *, when: float) -> Path:
    """One Claude transcript with no `cwd` record anywhere in it.

    The missing `cwd` is the trigger M-1 turns on: `project_from_cwd` returns
    "" and the collector falls back to the encoded directory name. It is also
    what gives `--diagnose` a row to record, which is what M-5's assertions
    need to mean anything.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    stamp = datetime.fromtimestamp(when, tz=UTC).isoformat()
    transcript = projects / encoded / "a1b2c3d4-0000-0000-0000-000000000000.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        "\n".join(
            json.dumps(record)
            for record in (
                {
                    "type": "user",
                    "uuid": "u1",
                    "timestamp": stamp,
                    "message": {"content": "hello"},
                },
                {
                    "type": "assistant",
                    "timestamp": stamp,
                    "message": {"usage": {"output_tokens": 10}, "content": []},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(transcript, (when, when))
    return transcript


def isolated_environment(state_home: str, user_home: str) -> dict[str, str]:
    """Every path-bearing variable pointed somewhere empty.

    `--diagnose` collects, so without this the assertions below would be about
    whichever harnesses the machine running the suite happens to have. The
    arbiter who reproduced the retention finding recorded the trap: redirecting
    `CLAUDE_CONFIG_DIR` alone leaves the real Codex and Droid stores producing
    transitions, and those would write the very file these tests say must not
    exist.
    """
    env = {"HOME": user_home, "USERPROFILE": user_home, COMPASS_HOME_ENV: state_home}
    env.update({name: os.path.join(user_home, name.lower()) for name in STORE_ENV_VARS})
    return env


def no_instance() -> Any:
    """`lifecycle.instance_status` reporting nothing on the port.

    Patched rather than probed, because `--forget` refuses while a dashboard
    answers and the machine running the suite may well have one on the default
    port: without this, whether the delete happens would depend on the
    developer's own dashboard.
    """
    from compass_runtime import lifecycle  # noqa: PLC0415

    return mock.patch.object(
        lifecycle,
        "instance_status",
        return_value={"state": "absent", "port": 4553, "pid": None, "log": ""},
    )


def run_one_shot_cli(argv: list[str], env: dict[str, str]) -> int:
    """One `cli.main()` over an isolated environment, with no socket bound.

    Stdout is captured rather than left to the runner: `--diagnose` prints a
    full store report, and forty lines of it per test buries whatever the suite
    was actually saying.
    """
    import contextlib  # noqa: PLC0415
    import io as std_io  # noqa: PLC0415

    from compass_runtime import cli, http_api  # noqa: PLC0415

    with (
        mock.patch.dict(os.environ, env),
        mock.patch.object(sys, "argv", ["server.py", *argv]),
        # Binding a socket here would be the defect: a one-shot command must
        # exit without ever standing a server up.
        mock.patch.object(http_api, "CompassHTTPServer") as served,
        contextlib.redirect_stdout(std_io.StringIO()),
    ):
        code = cli.main()
    served.assert_not_called()
    return int(code)


class HistoryStoreTestCase(unittest.TestCase):
    """One temporary state home per test, so no test reads another's store."""

    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        self.state_home = self._home.name
        self.diagnostics: list[str] = []

    def config(self, **changes: Any) -> RuntimeConfig:
        fields: dict[str, Any] = {
            "state_home": self.state_home,
            "state_dir": Path(self.state_home),
            "os_name": support_os_name(),
        }
        fields.update(changes)
        return make_config(**fields)

    def store_bytes(self, config: RuntimeConfig) -> bytes:
        with open(history.store_path(config), "rb") as handle:
            return handle.read()


class NothingPromptDerivedReachesTheStoreTest(HistoryStoreTestCase):
    """AC2: nothing in the store is prompt-derived, proven against a fixture
    that would carry it.

    Read at the bytes rather than at the schema on purpose. A schema assertion
    passes for a store that retains `tasks` and `subagents` wholesale, because
    those keys are themselves published; what the never-list bans is the text
    inside them. Reading the file is the only check that catches a nested
    carrier, which is the exposure triage found the contract's never-list omits.
    """

    def test_no_operator_text_appears_anywhere_in_the_store_bytes(self) -> None:
        config = self.config()
        history.record(config, [loaded_row()], now=1_000.0)
        raw = self.store_bytes(config)
        for field, sentinel in SENTINELS.items():
            with self.subTest(field=field):
                self.assertNotIn(
                    sentinel.encode("utf-8"),
                    raw,
                    f"{field} reached the history store",
                )

    def test_the_store_kept_the_observation_it_was_given(self) -> None:
        # The negative above is satisfiable by a store that writes nothing at
        # all, so it is paired with the positive: the recording cycle really did
        # run and really did keep the transition.
        config = self.config()
        history.record(config, [loaded_row()], now=1_000.0)
        payload = json.loads(self.store_bytes(config))
        self.assertEqual(1, len(payload["entries"]))
        self.assertEqual("working", payload["entries"][0]["state"])


class TheAnnotationBaselineIsAdmittedAndBoundedTest(HistoryStoreTestCase):
    """DEC-15b's first two admissions, end to end.

    The store's rule is that it holds nothing the live snapshot does not
    already serve. These two are served, on every row, and they are the only
    prompt-derived text in the record: what the reader typed one session should
    achieve and what they typed it should produce.
    """

    GOAL = "Capture every screen with live sessions"
    OUTPUT = "Six screenshots, one per screen"

    def annotated(self, state: str = "working", **fields: object) -> dict[str, object]:
        row = loaded_row(state)
        row.update(
            {
                "annotation_goal": self.GOAL,
                "annotation_line_1": self.OUTPUT,
                "annotation_line_1_source": "typed",
                "annotation_revision": 2,
                **fields,
            }
        )
        return row

    def test_the_words_the_reader_typed_reach_the_store_and_come_back(self) -> None:
        config = self.config()
        history.record(config, [self.annotated()], now=1_000.0)
        kept, reset = history.load(config)
        self.assertIsNone(reset)
        self.assertEqual(self.GOAL, kept[0]["annotation_goal"])
        self.assertEqual(self.OUTPUT, kept[0]["annotation_line_1"])
        self.assertEqual(2, kept[0]["annotation_revision"])

    def test_an_unannotated_row_stores_no_sentence_in_place_of_the_words(self) -> None:
        # The row carries an absence reason beside each field. Storing that is
        # storing a string nobody typed, in a store whose rule is that it holds
        # what a source published.
        config = self.config()
        row = loaded_row()
        row["annotation_goal_why"] = "No goal typed for this session."
        history.record(config, [row], now=1_000.0)
        kept, _reset = history.load(config)
        self.assertEqual("", kept[0]["annotation_goal"])
        self.assertNotIn(b"No goal typed", self.store_bytes(config))

    def test_editing_the_goal_records_a_transition_the_state_alone_would_miss(self) -> None:
        # Without the baseline in the transition comparison the store keeps the
        # old words until the session happens to move again, which makes its
        # copy stale by construction.
        config = self.config()
        history.record(config, [self.annotated()], now=1_000.0)
        history.record(
            config,
            [self.annotated(annotation_goal="A different goal", annotation_revision=3)],
            now=1_001.0,
        )
        kept, _reset = history.load(config)
        self.assertEqual(
            [self.GOAL, "A different goal"], [entry["annotation_goal"] for entry in kept]
        )

    def test_a_quiet_board_still_writes_nothing(self) -> None:
        # The widened comparison must not undo the dedupe it joined: the same
        # row twice is still one record.
        config = self.config()
        history.record(config, [self.annotated()], now=1_000.0)
        first = self.store_bytes(config)
        history.record(config, [self.annotated(last_activity=1_500.0)], now=1_500.0)
        self.assertEqual(first, self.store_bytes(config))

    def test_a_tampered_store_cannot_publish_a_container_as_the_goal(self) -> None:
        # This file is one any local process could have replaced, and every
        # field is re-validated on the way in. A mapping here would otherwise
        # reach the board.
        self.write_tampered({"annotation_goal": {"evil": 1}, "annotation_revision": "two"})
        kept, reset = history.load(self.config())
        self.assertIsNone(reset)
        self.assertEqual("", kept[0]["annotation_goal"])
        self.assertIsNone(kept[0]["annotation_revision"])

    def test_a_version_one_store_is_read_rather_than_discarded(self) -> None:
        # The migration, exercised for real now that a bump has happened. A v1
        # record is a v2 record with these three absent, and discarding one
        # would cost a reader fourteen days of history on an upgrade.
        self.assertEqual(4, history.SCHEMA_VERSION)
        self.assertEqual((1, 2, 3, 4), history.READABLE_VERSIONS)
        path = os.path.join(self.state_home, history.STORE_FILENAME)
        with open(path, "w") as handle:
            json.dump(
                {
                    "v": 1,
                    "entries": [
                        {
                            "harness": "claude",
                            "sid": "sid-1",
                            "project": "recce/compass",
                            "state": "working",
                            "last_activity": 1_000.0,
                        }
                    ],
                },
                handle,
            )
        kept, reset = history.load(self.config())
        self.assertIsNone(reset)
        self.assertEqual(1, len(kept))
        self.assertEqual("working", kept[0]["state"])
        self.assertEqual("", kept[0]["annotation_goal"])
        self.assertIsNone(kept[0]["annotation_revision"])

    def write_tampered(self, fields: dict[str, object]) -> None:
        path = os.path.join(self.state_home, history.STORE_FILENAME)
        entry = {
            "harness": "claude",
            "sid": "sid-1",
            "project": "recce/compass",
            "state": "working",
            "last_activity": 1_000.0,
            **fields,
        }
        with open(path, "w") as handle:
            json.dump({"v": history.SCHEMA_VERSION, "entries": [entry]}, handle)


class EveryStoredFieldIsAPublishedFieldTest(HistoryStoreTestCase):
    """AC1: every field in the store is a field the board publishes, and none is
    on the never-list.

    Both expected sets come from outside `history.py`: the published set is
    `test_sessions`'s hand-written declaration, and the ban list is a literal
    here. Reading `history.OBSERVATION_FIELDS` for both sides would prove only
    that the module agrees with itself.
    """

    # The contract's four named carriers plus the three nested ones it omits.
    # `spacedock` is a third nested object with the same exposure.
    BANNED = (
        "title",
        "last_prompt",
        "state_detail",
        "instruction",
        "tasks",
        "subagents",
        "spacedock",
    )

    def published_fields(self) -> frozenset[str]:
        from .test_sessions import DECLARED_SESSION_FIELDS  # noqa: PLC0415

        return frozenset(DECLARED_SESSION_FIELDS)

    def test_the_record_keeps_only_fields_the_board_already_publishes(self) -> None:
        record = history.observation(loaded_row())
        assert record is not None
        self.assertTrue(
            set(record) <= self.published_fields(),
            f"history keeps unpublished fields: {sorted(set(record) - self.published_fields())}",
        )

    def test_the_record_holds_no_operator_text_carrier(self) -> None:
        record = history.observation(loaded_row())
        assert record is not None
        self.assertEqual(frozenset(), frozenset(record) & frozenset(self.BANNED))

    def test_the_declared_field_tuple_is_what_a_record_actually_has(self) -> None:
        # Keeps the tuple the oracle above reads honest against the builder: a
        # field added to one and not the other would otherwise pass both.
        record = history.observation(loaded_row())
        assert record is not None
        self.assertEqual(set(history.OBSERVATION_FIELDS), set(record))

    def test_a_row_keyed_on_a_working_directory_is_not_what_gets_stored(self) -> None:
        # The never-list bans the paths the project label is derived from. The
        # label is kept (D4); a raw cwd is not, and no `cwd` key is published.
        record = history.observation(loaded_row())
        assert record is not None
        self.assertNotIn("cwd", record)
        self.assertEqual("recce/compass", record["project"])


class EvictionTest(HistoryStoreTestCase):
    """AC3: eviction is by age first and the cap cannot resurrect a dropped
    observation."""

    def entries(self, stamps: list[float]) -> list[history.Observation]:
        return [
            history.Observation(
                harness="claude",
                sid=f"s{int(stamp)}",
                project="p/q",
                state="working",
                last_activity=stamp,
                annotation_goal="",
                annotation_revision=None,
            )
            for stamp in stamps
        ]

    def test_records_outside_the_retention_window_are_gone(self) -> None:
        kept = history.evict(
            self.entries([100.0, 5_000.0]),
            now=10_000.0,
            retention_sec=6_000.0,
            max_bytes=1_048_576,
        )
        self.assertEqual([5_000.0], [e["last_activity"] for e in kept])

    def test_inside_the_window_the_size_cap_drops_the_oldest_first(self) -> None:
        # Falsified by a refuse-when-full policy like the dismissal store's,
        # under which the NEWEST records would be the ones missing.
        stamps = [float(x) for x in range(1_000, 1_100)]
        kept = history.evict(
            self.entries(stamps),
            now=1_100.0,
            retention_sec=1_000_000.0,
            max_bytes=400,
        )
        self.assertLess(len(kept), len(stamps))
        surviving = [e["last_activity"] for e in kept]
        self.assertEqual(sorted(surviving), surviving)
        self.assertEqual(max(stamps), surviving[-1], "the newest observation was evicted")
        self.assertNotIn(min(stamps), surviving, "the oldest observation survived the cap")

    def test_raising_the_cap_after_an_age_eviction_brings_nothing_back(self) -> None:
        config = self.config(history_retention_sec=500.0)
        history.record(config, [loaded_row(last_activity=1_000.0)], now=1_000.0)
        # A second collection, far enough on that the first observation is
        # outside the window, which writes the file without it.
        history.record(config, [loaded_row("idle", last_activity=9_000.0)], now=9_000.0)
        after_eviction = self.store_bytes(config)
        raised = self.config(history_retention_sec=500.0, history_max_bytes=8_388_608)
        entries, reset = history.load(raised)
        self.assertIsNone(reset)
        self.assertEqual(after_eviction, self.store_bytes(raised))
        self.assertNotIn(1_000.0, [e["last_activity"] for e in entries])


class OwnerOnlyWriteTest(HistoryStoreTestCase):
    """AC4: the file is created owner-only through a temp file and a rename."""

    @unittest.skipIf(os.name == "nt", "the mode is advisory on Windows")
    def test_the_store_is_owner_only_from_the_open_call(self) -> None:
        config = self.config()
        history.record(config, [loaded_row()], now=1_000.0)
        self.assertEqual(0o600, os.stat(history.store_path(config)).st_mode & 0o777)

    @unittest.skipIf(os.name == "nt", "the mode is advisory on Windows")
    def test_the_directory_is_owner_only(self) -> None:
        home = os.path.join(self.state_home, "nested")
        config = self.config(state_home=home, state_dir=Path(home))
        history.record(config, [loaded_row()], now=1_000.0)
        self.assertEqual(0o700, os.stat(home).st_mode & 0o777)

    def test_the_store_is_written_through_a_temp_file_and_renamed(self) -> None:
        # The atomicity half of AC4 had no oracle at all: writing in place
        # instead of temp-plus-rename passed all 46 tests in this file, and no
        # test in the repository asserted the shape for any store. Spied at the
        # two syscalls, so a simplification of the write path goes red here.
        config = self.config()
        target = history.store_path(config)
        opened: list[tuple[str, int | None]] = []
        renamed: list[tuple[str, str]] = []
        real_open, real_replace = os.open, os.replace

        def spy_open(path: Any, *args: Any, **kwargs: Any) -> int:
            # The mode argument, not merely the path. Recording the path alone
            # left AC4's own named falsifier green: `open()` then `os.chmod`
            # writes the same temp file to the same target, and only the mode
            # passed to the call tells the two apart while the file is on disk.
            mode = kwargs.get("mode", args[1] if len(args) > 1 else None)
            opened.append((str(path), mode))
            return int(real_open(path, *args, **kwargs))

        def spy_replace(src: Any, dst: Any, **kwargs: Any) -> None:
            renamed.append((str(src), str(dst)))
            real_replace(src, dst, **kwargs)

        with (
            mock.patch.object(os, "open", spy_open),
            mock.patch.object(os, "replace", spy_replace),
        ):
            self.assertTrue(history.save(config, [], diagnostic_sink=self.diagnostics.append))
        self.assertEqual(1, len(opened))
        path, mode = opened[0]
        self.assertTrue(path.endswith(".tmp"), path)
        self.assertNotEqual(target, path, "the target was opened directly")
        self.assertEqual(0o600, mode)
        self.assertEqual([(path, target)], renamed)

    def test_a_failed_write_leaves_no_temp_file_behind(self) -> None:
        # The rename fails, not `makedirs`: the old setup made `state_home` a
        # regular file, so `os.makedirs` raised before `os.open` was ever
        # reached and the test passed with zero temp files created and none to
        # clean up. Failing at the rename is the shape that leaves one behind.
        config = self.config()
        with mock.patch.object(os, "replace", side_effect=OSError("no rename")):
            self.assertFalse(
                history.save(
                    config,
                    [
                        history.Observation(
                            harness="claude",
                            sid="sid-1",
                            project="recce/compass",
                            state="working",
                            last_activity=1_000.0,
                            annotation_goal="",
                            annotation_revision=None,
                        )
                    ],
                    diagnostic_sink=self.diagnostics.append,
                ),
            )
        self.assertTrue(any("history store" in line for line in self.diagnostics))
        self.assertFalse(
            [name for name in os.listdir(self.state_home) if name.endswith(".tmp")],
            "the temp file was left behind",
        )
        self.assertFalse(os.path.exists(history.store_path(config)))


class UnreadableStoreIsDiscardedTest(HistoryStoreTestCase):
    """AC5: an unreadable store is discarded, the board starts empty, and the
    reason is distinguishable."""

    def write_store(self, payload: object) -> None:
        with open(os.path.join(self.state_home, history.STORE_FILENAME), "w") as handle:
            handle.write(payload if isinstance(payload, str) else json.dumps(payload))

    def test_corrupt_bytes_start_empty_and_report_a_corruption_reset(self) -> None:
        self.write_store("{not json at all")
        entries, reset = history.load(self.config())
        self.assertEqual((), entries)
        self.assertEqual(history.RESET_UNREADABLE, reset)

    def test_a_version_the_build_cannot_read_reports_a_version_reset(self) -> None:
        # D1: distinguishable from corruption, because a corruption reset may be
        # the user's disk and a version reset is ours.
        self.write_store({"v": history.SCHEMA_VERSION + 1, "entries": []})
        entries, reset = history.load(self.config())
        self.assertEqual((), entries)
        self.assertEqual(history.RESET_VERSION, reset)

    def test_every_version_this_build_names_is_read_rather_than_reset(self) -> None:
        """DEC-15b's admission path, and the reason it is not an equality check.

        Admitting an assessment field bumps the version, and under an equality
        check that bump discarded fourteen days of every existing user's
        history on upgrade. Nothing in the tree would have caught it: the store
        rebuilds itself from the next collection, so a wiped history looks like
        a quiet morning.
        """
        row = {
            "harness": "codex",
            "sid": "s1",
            "project": "compass",
            "state": "idle",
            "last_activity": 100.0,
        }
        for version in history.READABLE_VERSIONS:
            with self.subTest(version=version):
                self.write_store({"v": version, "entries": [row]})
                entries, reset = history.load(self.config())
                self.assertIsNone(reset)
                self.assertEqual(1, len(entries))
        self.assertIn(history.SCHEMA_VERSION, history.READABLE_VERSIONS)

    def test_a_version_that_is_not_a_number_is_refused(self) -> None:
        # `True in (1,)` is true in Python, so a boolean here read as version 1
        # under both this check and the equality check it replaced. This file is
        # one any local process could have written.
        for version in (True, "1", None, [1]):
            with self.subTest(version=version):
                self.write_store({"v": version, "entries": []})
                self.assertEqual(history.RESET_VERSION, history.load(self.config())[1])

    def test_a_store_larger_than_the_cap_is_discarded_unread(self) -> None:
        self.write_store({"v": history.SCHEMA_VERSION, "entries": []})
        entries, reset = history.load(self.config(history_max_bytes=4))
        self.assertEqual((), entries)
        self.assertEqual(history.RESET_UNREADABLE, reset)

    def test_the_two_reset_reasons_are_the_literals_the_header_will_read(self) -> None:
        # D1's distinguishable reason is the recommendation the gate ruled on,
        # and no test pinned either literal: setting `RESET_VERSION` to
        # "unreadable" passed 115 tests across three modules, so the assertion
        # that a corruption reset and a version reset differ could not fail.
        self.assertEqual("unreadable", history.RESET_UNREADABLE)
        self.assertEqual("version", history.RESET_VERSION)
        self.assertNotEqual(history.RESET_UNREADABLE, history.RESET_VERSION)

    def test_no_file_at_all_is_a_first_run_and_not_a_reset(self) -> None:
        # Reporting a reset here would tell a new user their history was lost.
        entries, reset = history.load(self.config())
        self.assertEqual((), entries)
        self.assertIsNone(reset)

    def test_one_malformed_record_does_not_discard_the_others(self) -> None:
        self.write_store(
            {
                "v": history.SCHEMA_VERSION,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "a",
                        "project": "p",
                        "state": "idle",
                        "last_activity": 5.0,
                    },
                    {"harness": "claude", "sid": "b"},
                ],
            }
        )
        entries, reset = history.load(self.config())
        self.assertIsNone(reset)
        self.assertEqual(["a"], [e["sid"] for e in entries])


class OffMeansOffTest(HistoryStoreTestCase):
    """AC6: with the store off, nothing is written and nothing is read back."""

    def test_nothing_is_written_when_the_store_is_off(self) -> None:
        config = self.config(history_enabled=False)
        history.record(config, [loaded_row()], now=1_000.0)
        self.assertFalse(os.path.exists(history.store_path(config)))

    def test_an_existing_store_is_not_read_back_when_off(self) -> None:
        # Falsified by gating only the write, which would leave the board
        # opening with a memory the user asked it not to keep.
        on = self.config()
        history.record(on, [loaded_row()], now=1_000.0)
        self.assertTrue(os.path.exists(history.store_path(on)))
        entries, reset = history.load(self.config(history_enabled=False))
        self.assertEqual((), entries)
        self.assertIsNone(reset)


class ForgetTest(HistoryStoreTestCase):
    """AC8's file half: `--forget` deletes the store whether or not it is on."""

    def test_the_file_is_removed(self) -> None:
        config = self.config()
        history.record(config, [loaded_row()], now=1_000.0)
        self.assertTrue(history.forget(config))
        self.assertFalse(os.path.exists(history.store_path(config)))

    def test_it_removes_the_file_even_with_the_store_disabled(self) -> None:
        # Falsified by deleting only when enabled: someone who turned the
        # feature off and then asked for the file to go must not be told there
        # was nothing to delete.
        on = self.config()
        history.record(on, [loaded_row()], now=1_000.0)
        self.assertTrue(history.forget(self.config(history_enabled=False)))
        self.assertFalse(os.path.exists(history.store_path(on)))

    def test_deleting_a_store_that_is_not_there_reports_it(self) -> None:
        self.assertFalse(history.forget(self.config()))


class TransitionsAreDerivedTest(HistoryStoreTestCase):
    """The record is a transition, not a sample: what makes the file grow with
    what changed rather than with how often the board was collected."""

    def test_an_unchanged_state_records_nothing_new(self) -> None:
        config = self.config()
        history.record(config, [loaded_row("working", last_activity=1_000.0)], now=1_000.0)
        history.record(config, [loaded_row("working", last_activity=1_100.0)], now=1_100.0)
        entries, _ = history.load(config)
        self.assertEqual(1, len(entries))

    def test_a_changed_state_is_recorded_once(self) -> None:
        config = self.config()
        history.record(config, [loaded_row("working", last_activity=1_000.0)], now=1_000.0)
        history.record(config, [loaded_row("idle", last_activity=1_100.0)], now=1_100.0)
        entries, _ = history.load(config)
        self.assertEqual(["working", "idle"], [e["state"] for e in entries])

    def test_the_baseline_survives_a_restart(self) -> None:
        # The baseline is read from the store rather than from process memory,
        # so the first collection after a restart does not re-record every
        # session's current state as a fresh transition.
        config = self.config()
        history.record(config, [loaded_row("working", last_activity=1_000.0)], now=1_000.0)
        history.record(config, [loaded_row("working", last_activity=2_000.0)], now=2_000.0)
        entries, _ = history.load(config)
        self.assertEqual(1, len(entries))

    def test_a_row_with_no_activity_reading_records_nothing(self) -> None:
        # One-sided on purpose: a 0 stamp is the declared default rather than a
        # measurement, and an observation stamped at the epoch is one age
        # eviction drops on its next pass.
        config = self.config()
        row = loaded_row()
        row["last_activity"] = 0
        history.record(config, [row], now=1_000.0)
        self.assertFalse(os.path.exists(history.store_path(config)))


class PublishedFieldTest(HistoryStoreTestCase):
    """The board carries the history, so a panel can be seeded from it.

    Built over stub harnesses the way `test_dismissals` is, because the subject
    is what `collect` publishes rather than what any real store contains.
    """

    def spec(self, rows: list[dict[str, Any]]) -> Any:
        return stub_spec(rows)

    def application(self, rows: list[dict[str, Any]], *, config: RuntimeConfig) -> Any:
        return stub_application(config, rows, self.diagnostics)

    def test_a_collection_publishes_the_observations_it_recorded(self) -> None:
        config = self.config()
        rows = [{"sid": "sid-1", "state": "working", "last_activity": 4_900.0}]
        payload = self.application(rows, config=config).collect(show_all=True)
        self.assertEqual(1, len(payload["history"]))
        self.assertEqual("working", payload["history"][0]["state"])
        self.assertEqual("recce/compass", payload["history"][0]["project"])

    def test_no_operator_text_reaches_the_published_field_either(self) -> None:
        # The store's bytes are checked by AC2; this is the other exit, because a
        # field published to the browser is as much a disclosure as a file.
        config = self.config()
        rows = [
            {
                "sid": "sid-1",
                "state": "working",
                "last_activity": 4_900.0,
                "title": SENTINELS["title"],
                "state_detail": SENTINELS["state_detail"],
                "tasks": [{"subject": SENTINELS["task_subject"], "status": "in_progress"}],
            }
        ]
        payload = self.application(rows, config=config).collect(show_all=True)
        published = json.dumps(payload["history"])
        for sentinel in SENTINELS.values():
            self.assertNotIn(sentinel, published)

    def test_the_field_is_absent_when_the_store_is_off(self) -> None:
        config = self.config(history_enabled=False)
        rows = [{"sid": "sid-1", "state": "working", "last_activity": 4_900.0}]
        payload = self.application(rows, config=config).collect(show_all=True)
        self.assertNotIn("history", payload)

    def test_a_version_reset_is_reported_to_the_header(self) -> None:
        with open(os.path.join(self.state_home, history.STORE_FILENAME), "w") as handle:
            json.dump({"v": history.SCHEMA_VERSION + 1, "entries": []}, handle)
        config = self.config()
        rows = [{"sid": "sid-1", "state": "working", "last_activity": 4_900.0}]
        payload = self.application(rows, config=config).collect(show_all=True)
        self.assertEqual(history.RESET_VERSION, payload["history_reset"])

    def test_a_clean_open_reports_no_reset(self) -> None:
        config = self.config()
        rows = [{"sid": "sid-1", "state": "working", "last_activity": 4_900.0}]
        payload = self.application(rows, config=config).collect(show_all=True)
        self.assertNotIn("history_reset", payload)

    def test_a_collection_with_no_lane_publishes_nothing_and_does_not_raise(self) -> None:
        # One shape for both ways of not recording: the key is present exactly
        # when the store is on and a lane is attached, which is the keying
        # `dismiss` uses. An empty series here would have to be told apart from
        # a board on which nothing has happened yet.
        config = self.config()
        rows = [{"sid": "sid-1", "state": "working", "last_activity": 4_900.0}]
        payload = stub_application(config, rows, self.diagnostics, lane=False).collect(
            show_all=True
        )
        self.assertNotIn("history", payload)
        self.assertFalse(os.path.exists(history.store_path(config)))


class LaneTest(HistoryStoreTestCase):
    """The recording lane, which is governed by `--no-history` alone."""

    def test_the_lane_records_and_returns_the_whole_history(self) -> None:
        from compass_runtime.history import Lane  # noqa: PLC0415

        config = self.config()
        lane = Lane(config, diagnostic_sink=self.diagnostics.append)
        first = lane.record([loaded_row("working", last_activity=1_000.0)], now=1_000.0)
        second = lane.record([loaded_row("idle", last_activity=1_100.0)], now=1_100.0)
        self.assertEqual(["working"], [e["state"] for e in first])
        self.assertEqual(["working", "idle"], [e["state"] for e in second])

    def test_the_lane_writes_nothing_when_the_store_is_off(self) -> None:
        from compass_runtime.history import Lane  # noqa: PLC0415

        config = self.config(history_enabled=False)
        lane = Lane(config, diagnostic_sink=self.diagnostics.append)
        self.assertEqual([], lane.record([loaded_row()], now=1_000.0))
        self.assertFalse(os.path.exists(history.store_path(config)))

    def test_the_reset_reason_is_latched_for_the_life_of_the_run(self) -> None:
        # Re-derived per collection it would announce the reset once and then
        # fall silent while the board it emptied was still on screen, because
        # the first recording rewrites the store.
        from compass_runtime.history import Lane  # noqa: PLC0415

        with open(os.path.join(self.state_home, history.STORE_FILENAME), "w") as handle:
            handle.write("{corrupt")
        config = self.config()
        lane = Lane(config, diagnostic_sink=self.diagnostics.append)
        lane.record([loaded_row()], now=1_000.0)
        entries, reset = history.load(config)
        self.assertIsNone(reset, "the store on disk is readable again")
        self.assertEqual(1, len(entries))
        self.assertEqual(history.RESET_UNREADABLE, lane.notice())


class ForgetIsACommandAndNotARouteTest(HistoryStoreTestCase):
    """AC8: `--forget` deletes the store and exits, and adds no route."""

    def test_forget_deletes_the_store_and_exits_without_serving(self) -> None:
        import sys  # noqa: PLC0415
        from unittest import mock  # noqa: PLC0415

        from compass_runtime import cli, http_api, reading_policy  # noqa: PLC0415

        config = self.config()
        reading_policy.set_consent(config, True, now=1_000.0)
        reading_policy.reserve(config, now=1_000.0)
        history.record(config, [loaded_row()], now=1_000.0)
        path = history.store_path(config)
        self.assertTrue(os.path.exists(path))
        with (
            mock.patch.dict(os.environ, {"COMPASS_HOME": self.state_home}),
            mock.patch.object(sys, "argv", ["server.py", "--forget"]),
            # Nothing on the port: the delete is refused while a dashboard
            # answers, and whether one does is a property of the machine
            # running the suite rather than of the code (M-2).
            no_instance(),
            mock.patch("time.time", return_value=1_001.0),
            # Binding a socket here would be the defect: a one-shot command must
            # exit without ever standing a server up.
            mock.patch.object(http_api, "CompassHTTPServer") as served,
        ):
            code = cli.main()
        self.assertEqual(0, code)
        self.assertFalse(os.path.exists(path))
        served.assert_not_called()
        answer = reading_policy.status(config, now=1_001.0)
        self.assertFalse(answer["consent"])
        self.assertEqual(1, answer["used"])

    def test_forget_reports_when_there_was_nothing_to_delete(self) -> None:
        import sys  # noqa: PLC0415
        from unittest import mock  # noqa: PLC0415

        from compass_runtime import cli  # noqa: PLC0415
        from compass_runtime import io as runtime_io  # noqa: PLC0415

        with (
            mock.patch.dict(os.environ, {"COMPASS_HOME": self.state_home}),
            mock.patch.object(sys, "argv", ["server.py", "--forget"]),
            no_instance(),
            mock.patch.object(runtime_io, "diag") as diag,
        ):
            self.assertEqual(0, cli.main())
        self.assertIn("no history store", " ".join(str(c) for c in diag.call_args_list))

    def test_the_post_surface_did_not_grow(self) -> None:
        # The contract lists "a history file reachable over the port" as a
        # security bug, so the count is asserted rather than trusted: the
        # twenty-entry exact-match table plus the two prefix matches ahead of
        # it, and no path naming history among them. DRC-4681 added
        # `/api/correction`, which reads and writes nothing but its reply. The
        # session summary added `/api/summary` and `/api/summary/cancel`; neither
        # reads or writes session history. `/api/goal/find` reads the reader's prompts and
        # stores no history.
        import ast  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        from compass_runtime import http_api  # noqa: PLC0415

        source = Path(http_api.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        post = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "do_POST"
        )
        tables = [node for node in ast.walk(post) if isinstance(node, ast.Dict)]
        self.assertEqual(1, len(tables), "do_POST grew a second route table")
        routes = [
            key.value
            for key in tables[0].keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
        self.assertEqual(20, len(routes))
        prefixes = [
            node
            for node in ast.walk(post)
            if isinstance(node, ast.Attribute) and node.attr == "startswith"
        ]
        self.assertEqual(2, len(prefixes))
        self.assertEqual(
            {"/api/events/", "/api/interaction/"},
            {
                node.args[0].value
                for node in ast.walk(post)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "startswith"
                and isinstance(node.args[0], ast.Constant)
            },
        )
        for route in routes:
            self.assertNotIn("history", route)
            self.assertNotIn("forget", route)

    def test_no_get_route_serves_the_history_file(self) -> None:
        from pathlib import Path  # noqa: PLC0415

        from compass_runtime import http_api  # noqa: PLC0415

        source = Path(http_api.__file__).read_text(encoding="utf-8")
        self.assertNotIn(history.STORE_FILENAME, source)
        self.assertNotIn("/api/history", source)


class ATamperedStoreCannotReorderTheBoardTest(HistoryStoreTestCase):
    """The store is a file any local process could have replaced, and its four
    strings reach the DOM through `/api/data`.

    The write path is safe by construction: every value comes off a row that has
    already been through `records.safe_text`. The read-back path is not, which is
    why `dismissals.py` bounds its own two strings on the way in and cites the
    same reason. This is that check, one store over.
    """

    def write_store(self, entry: dict[str, Any]) -> None:
        with open(os.path.join(self.state_home, history.STORE_FILENAME), "w") as handle:
            json.dump({"v": history.SCHEMA_VERSION, "entries": [entry]}, handle)

    def base(self, **changes: Any) -> dict[str, Any]:
        entry = {
            "harness": "claude",
            "sid": "sid-1",
            "project": "p/q",
            "state": "working",
            "last_activity": 1_000.0,
        }
        entry.update(changes)
        return entry

    def test_a_bidi_override_in_a_project_label_is_stripped(self) -> None:
        # U+202E reorders how everything after it renders, so a stored label
        # could make a row read as something it does not say.
        self.write_store(self.base(project="safe\u202egnop.exe"))
        entries, reset = history.load(self.config())
        self.assertIsNone(reset)
        self.assertNotIn("\u202e", entries[0]["project"])

    def test_control_characters_are_stripped_from_every_stored_string(self) -> None:
        self.write_store(
            self.base(harness="cla\x00ude", sid="s\x1bid", project="p\x7fq", state="wor\nking")
        )
        entries, _ = history.load(self.config())
        stored = entries[0]
        for field in ("harness", "sid", "project", "state"):
            with self.subTest(field=field):
                self.assertFalse(
                    any(ord(c) < 0x20 or ord(c) == 0x7F for c in str(stored[field])),
                    f"{field} kept a control character",
                )

    def test_an_overlong_stored_string_is_bounded(self) -> None:
        self.write_store(self.base(project="x" * 5_000))
        entries, _ = history.load(self.config())
        self.assertEqual(history.FIELD_CAP_CHARS, len(entries[0]["project"]))

    def test_the_zero_width_joiners_that_compose_an_emoji_survive(self) -> None:
        # ZWJ and ZWNJ cannot reorder text, and stripping them would break a
        # project label in Persian or several Indic scripts. Same carve-out
        # `records` makes, asserted here so an inlined table cannot drift into
        # the stricter range.
        self.write_store(self.base(project="a\u200cb\u200dc"))
        entries, _ = history.load(self.config())
        self.assertEqual("a\u200cb\u200dc", entries[0]["project"])


class NoOperatorTextSurvivesTheRealCollectionTest(HistoryStoreTestCase):
    """AC2 again, driven through `aggregate.collect` rather than a unit shim.

    The unit form of AC2 calls `history.record` directly, which proves the
    record is narrow but not that the caller hands it narrow rows. Since
    `aggregate` is what calls the lane, the fixture has to travel the real path:
    stub harness -> collect -> dedupe -> redaction -> overlays -> lane -> disk.
    A future caller that passed whole rows in would fail here and pass there.
    """

    def application(self, config: RuntimeConfig) -> Any:
        from compass_runtime import aggregate  # noqa: PLC0415
        from compass_runtime import history as h  # noqa: PLC0415
        from compass_runtime import sessions as rs  # noqa: PLC0415
        from compass_runtime.state import build_runtime_state  # noqa: PLC0415

        def discover(cfg: Any, st: Any) -> bool:
            del cfg, st
            return True

        def collect(
            cfg: Any, st: Any, now: float, window_hours: float, show_all: bool
        ) -> list[dict[str, Any]]:
            del cfg, st, now, window_hours, show_all
            # The full operator-text fixture, on a row a real collector shapes.
            row = rs.base_session("claude", "sid-1", "recce/compass")
            row.update(
                {
                    "state": "working",
                    "last_activity": 4_900.0,
                    "own_activity": 4_900.0,
                    "title": SENTINELS["title"],
                    "last_prompt": SENTINELS["last_prompt"],
                    "state_detail": SENTINELS["state_detail"],
                    "instruction": {"text": SENTINELS["instruction"], "kind": "plan"},
                    "tasks": [
                        {
                            "subject": SENTINELS["task_subject"],
                            "activeForm": SENTINELS["task_active_form"],
                            "status": "in_progress",
                        }
                    ],
                    "subagents": [{"name": SENTINELS["subagent_name"], "sid": "child-1"}],
                }
            )
            return [row]

        state = build_runtime_state(config, started=1_700_000_000.0)
        app = aggregate.Application(
            config,
            state,
            (
                aggregate.HarnessSpec(
                    key="claude", label="Claude", discover=discover, collect=collect
                ),
            ),
            native_notifier=lambda platform: f"stub@{platform}",
            popup_notifier=lambda *_: None,
            diagnostic_sink=self.diagnostics.append,
            clock=lambda: 5_000.0,
        )
        app.history_lane = h.Lane(config, diagnostic_sink=self.diagnostics.append)
        return app

    def test_no_sentinel_reaches_the_store_through_the_real_collection(self) -> None:
        config = self.config()
        payload = self.application(config).collect(show_all=True)
        # The row really did carry the fixture through to publication.
        self.assertEqual(SENTINELS["title"], payload["sessions"][0]["title"])
        # And the store really was written by that same collection.
        raw = self.store_bytes(config)
        self.assertIn(b'"working"', raw)
        for field, sentinel in SENTINELS.items():
            with self.subTest(field=field):
                self.assertNotIn(sentinel.encode("utf-8"), raw, f"{field} reached the store")


class AQuietBoardDoesNotGrowTheStoreTest(HistoryStoreTestCase):
    """The lane writes on an observed transition and never per collection.

    A store that grew on every poll of a quiet board would be an unbounded
    writer: the coordinator collects at least every `reconcile_interval_sec`
    whether or not anything moved, so per-cycle appends would put roughly 2,880
    records a day per session into a fourteen-day store that nothing had
    happened in. The oracle is the file itself, not a record count: mtime and
    bytes both have to hold still.
    """

    def test_repeated_collections_of_an_unchanged_board_rewrite_nothing(self) -> None:
        config = self.config()
        history.record(config, [loaded_row("working", last_activity=1_000.0)], now=1_000.0)
        path = history.store_path(config)
        before_bytes = self.store_bytes(config)
        before_mtime = os.stat(path).st_mtime_ns

        # Twenty further collections, the state unchanged, activity advancing
        # the way a working session's does.
        for tick in range(20):
            history.record(
                config,
                [loaded_row("working", last_activity=1_100.0 + tick)],
                now=1_100.0 + tick,
            )

        self.assertEqual(before_bytes, self.store_bytes(config), "the store was rewritten")
        self.assertEqual(before_mtime, os.stat(path).st_mtime_ns, "the file was touched")
        entries, _ = history.load(config)
        self.assertEqual(1, len(entries))

    def test_a_quiet_board_with_no_store_yet_creates_no_file(self) -> None:
        # An idle row whose state never changes still records its first
        # observation, but never a second.
        config = self.config()
        history.record(config, [loaded_row("idle", last_activity=1_000.0)], now=1_000.0)
        first = self.store_bytes(config)
        for tick in range(5):
            history.record(config, [loaded_row("idle", last_activity=1_010.0 + tick)], now=1_010.0)
        self.assertEqual(first, self.store_bytes(config))


class AFallbackProjectLabelIsNotAPathTest(HistoryStoreTestCase):
    """M-1: the stored label is bounded where the record is derived, rather than
    trusted to be two segments already.

    Driven through the real Claude collector, because the row is where the path
    came from: with no `cwd` in a transcript's first records — 29 of the 3,888
    real transcripts on this machine, and 1 of the 27 written in a day — the
    collector falls back to `sessions.project_label`, which strips the encoded
    home prefix and returns every remaining segment of a home-relative path
    joined by `-`. The never-list bans "neither a session's working directory
    nor any path a tool touched", so the oracle is the store's own bytes.
    """

    # Six directories: repos/recce/recce-cloud-infra/.claude/worktrees/
    # drc-3976-finish, encoded the way Claude encodes one, under the fake home
    # `make_config` builds. A real measured value, not an invented one.
    ENCODED = (
        "-nonexistent-compass-test-repos-recce-recce-cloud-infra--claude-worktrees-drc-3976-finish"
    )
    PUBLISHED = "repos-recce-recce-cloud-infra--claude-worktrees-drc-3976-finish"
    BOUNDED = "3976-finish"

    def collected(self) -> tuple[RuntimeConfig, dict[str, Any]]:
        import dataclasses  # noqa: PLC0415
        import time  # noqa: PLC0415
        from types import MappingProxyType  # noqa: PLC0415

        from compass_runtime import cli  # noqa: PLC0415
        from compass_runtime.state import build_runtime_state  # noqa: PLC0415

        when = time.time()
        projects = Path(self.state_home) / "projects"
        seed_claude_transcript(projects, self.ENCODED, when=when)
        config = self.config()
        roots = dict(config.store_roots)
        roots["claude.projects"] = (str(projects),)
        config = dataclasses.replace(config, store_roots=MappingProxyType(roots))
        state = build_runtime_state(config, started=when - 10)
        application = cli.build_application(
            config, state, clock=lambda: when, diagnostic_sink=self.diagnostics.append
        )
        return config, application.collect(show_all=True)

    def test_the_row_and_the_store_agree_on_the_bounded_label(self) -> None:
        # Non-vacuity, and DR-8's fix in one assertion. The uncapped fallback
        # still returns the whole six-segment path, so there is a path to bound;
        # the row the collector publishes carries the bounded label instead, so
        # the board groups this project under the same name the store keeps.
        # Before the bound moved, the row carried the path and the two disagreed.
        config, payload = self.collected()
        self.assertEqual(self.PUBLISHED, runtime_sessions.project_label(config, self.ENCODED))
        self.assertEqual(self.BOUNDED, payload["sessions"][0]["project"])
        self.assertEqual(self.BOUNDED, payload["history"][0]["project"])

    def test_the_store_holds_two_segments_and_never_the_path(self) -> None:
        config, payload = self.collected()
        raw = self.store_bytes(config)
        stored = json.loads(raw)["entries"][0]["project"]
        self.assertEqual(2, len(stored.split("-")), f"stored {stored!r}")
        self.assertEqual("3976-finish", stored)
        for segment in (b"repos", b"recce", b"cloud-infra", b"worktrees", b"claude-"):
            self.assertNotIn(segment, raw, f"{segment!r} reached the store")
        self.assertEqual(1, len(payload["history"]))
        self.assertEqual(stored, payload["history"][0]["project"])

    def test_the_store_bounds_on_the_path_separator_and_never_on_a_dash(self) -> None:
        # DR-8. The store used to split a label with no `/` on `-`, which is the
        # one thing it cannot do correctly: a hyphenated directory name and a
        # dash-encoded path are the same string here, and every name below is a
        # real directory on the machine this was measured on. The bound now lives
        # at `sessions.bounded_project_label`, where the label is built from path
        # segments and the difference is known.
        cases = [
            ("my-cool-project", "my-cool-project"),
            ("recce-cloud-infra", "recce-cloud-infra"),
            ("spacedock-ensign-drc-4044", "spacedock-ensign-drc-4044"),
            ("docs-sync-next-ui-design-parity", "docs-sync-next-ui-design-parity"),
            ("alpha-beta-gamma-delta-epsilon-zeta", "alpha-beta-gamma-delta-epsilon-zeta"),
            # The `/` bound stays: a label from `project_from_cwd` is at most two
            # segments already, and anything wider did not come from there.
            ("recce/my-cool-repo", "recce/my-cool-repo"),
            ("a/b/c", "b/c"),
        ]
        for label, expected in cases:
            with self.subTest(label=label):
                record = history.observation({**loaded_row(), "project": label})
                assert record is not None
                self.assertEqual(expected, record["project"])


class ForgetIsRefusedWhileADashboardCouldWriteItBackTest(HistoryStoreTestCase):
    """M-2: the delete has to survive the dashboard it is issued under.

    `--daemon` is the documented persistent shape and `--forget` is the only
    delete route, so the two meet: the lane latches its baseline on first read
    and never re-reads, so every deleted record came back on the next
    transition after the user was told `Compass: deleted ...`. Both halves are
    pinned, the refusal and the lane's own re-check, because the refusal can
    only see the port this invocation names.
    """

    def test_forget_refuses_and_keeps_the_store_while_an_instance_answers(self) -> None:
        from compass_runtime import cli, http_api, lifecycle  # noqa: PLC0415
        from compass_runtime import io as runtime_io  # noqa: PLC0415

        config = self.config()
        history.record(config, [loaded_row()], now=1_000.0)
        path = history.store_path(config)
        running = {"state": "running", "port": 4553, "pid": 4242, "started": 1.0, "log": ""}
        with (
            mock.patch.dict(os.environ, {COMPASS_HOME_ENV: self.state_home}),
            mock.patch.object(sys, "argv", ["server.py", "--forget"]),
            mock.patch.object(lifecycle, "instance_status", return_value=running) as probe,
            mock.patch.object(runtime_io, "diag") as diag,
            mock.patch.object(http_api, "CompassHTTPServer") as served,
        ):
            code = cli.main()
        self.assertEqual(1, code)
        self.assertTrue(os.path.exists(path), "the store was deleted under a live instance")
        said = " ".join(str(call) for call in diag.call_args_list)
        self.assertIn("--stop", said)
        # The same probe `--status` and `--stop` already use, on the port this
        # invocation names, so it needs neither a state file nor the home the
        # dashboard was started with.
        self.assertEqual(4553, probe.call_args.args[1])
        served.assert_not_called()

    def test_a_lane_does_not_write_back_a_store_deleted_under_it(self) -> None:
        config = self.config()
        lane = history.Lane(config, diagnostic_sink=self.diagnostics.append)
        lane.record([loaded_row("working", last_activity=1_000.0)], now=1_000.0)
        lane.record([loaded_row("idle", last_activity=1_100.0)], now=1_100.0)
        self.assertEqual(2, len(history.load(config)[0]))
        # The delete an instance on another port, or a hand, can still make.
        self.assertTrue(history.forget(config))
        published = lane.record([loaded_row("working", last_activity=1_200.0)], now=1_200.0)
        entries, _reset = history.load(config)
        self.assertEqual([1_200.0], [e["last_activity"] for e in entries])
        self.assertEqual(1, len(published), "the deleted records came back through the lane")


class ATamperedNumberDoesNotTakeTheBoardDownTest(HistoryStoreTestCase):
    """M-3: `Infinity`, `NaN`, and an integer no float can hold.

    `history.py` names this threat model four times — the file is one any local
    process could have replaced — and these three shapes passed the validation
    it had. Two of them cost the whole board rather than the history panel:
    `Infinity` made `json.dumps` emit a token `JSON.parse` rejects, so the
    entire `/api/data` body failed to parse, and a huge integer raised
    OverflowError out of `load` on every collection, so a live server answered
    HTTP 000 permanently and `--diagnose` crashed on the same line.
    """

    RECORD = '{"harness": "claude", "sid": "a", "project": "p", "state": "idle", '
    TAMPERED: ClassVar[dict[str, str]] = {
        "infinity": RECORD + '"last_activity": Infinity}',
        "nan": RECORD + '"last_activity": NaN}',
        "overflow": RECORD + '"last_activity": ' + "1" + "0" * 400 + "}",
    }

    def write(self, record: str) -> None:
        raw = '{"v": ' + str(history.SCHEMA_VERSION) + ', "entries": [' + record + "]}"
        with open(os.path.join(self.state_home, history.STORE_FILENAME), "w") as handle:
            handle.write(raw)

    def test_each_tampered_number_empties_the_store_and_reports_the_reset(self) -> None:
        for shape, record in self.TAMPERED.items():
            with self.subTest(shape=shape):
                self.write(record)
                entries, reset = history.load(self.config())
                self.assertEqual((), entries)
                self.assertEqual(history.RESET_UNREADABLE, reset)

    def test_the_published_body_carries_no_token_a_browser_would_reject(self) -> None:
        # The token is the oracle rather than a round trip: Python's own
        # `json.loads` accepts `Infinity` and `NaN` as an extension, and what
        # rejected the body was the browser's `JSON.parse`.
        self.write(self.TAMPERED["infinity"])
        config = self.config()
        rows = [{"sid": "sid-1", "state": "working", "last_activity": 4_900.0}]
        _revision, body = stub_application(config, rows, self.diagnostics).collect_json(
            show_all=True
        )
        self.assertNotIn(b"Infinity", body)
        self.assertNotIn(b"NaN", body)
        self.assertEqual(history.RESET_UNREADABLE, json.loads(body)["history_reset"])

    def test_a_row_carrying_a_non_finite_stamp_records_nothing(self) -> None:
        # The write path has no parse hook to lean on, and `stamp <= 0` is false
        # for NaN: the guard that rejects the declared default admitted the one
        # value that has no order, which is what distorts eviction.
        for stamp in (float("nan"), float("inf"), float("-inf"), 10**400):
            with self.subTest(stamp=repr(stamp)):
                self.assertIsNone(history.observation({**loaded_row(), "last_activity": stamp}))

    def test_a_record_carrying_a_non_finite_stamp_is_dropped_on_its_own(self) -> None:
        # `_entry` is the read-back validator and holds the guard independently
        # of the parse hooks, so a store reaching it by some other route cannot
        # seed a stamp with no order either.
        base = {"harness": "claude", "sid": "a", "project": "p", "state": "idle"}
        for stamp in (float("nan"), float("inf"), 10**400):
            with self.subTest(stamp=repr(stamp)):
                self.assertIsNone(history._entry({**base, "last_activity": stamp}))
        self.assertIsNotNone(history._entry({**base, "last_activity": 5.0}))

    def test_a_read_that_raises_discards_the_store_once_and_not_forever(self) -> None:
        # `_opened` was set after the read, so a raising `load` was retried on
        # every collection and the board never served again. Latched before it,
        # the store is discarded once with the reason the header names.
        config = self.config()
        lane = history.Lane(config, diagnostic_sink=self.diagnostics.append)
        with mock.patch.object(history, "load", side_effect=OverflowError("too large")) as read:
            first = lane.record([loaded_row("working", last_activity=1_000.0)], now=1_000.0)
            second = lane.record([loaded_row("idle", last_activity=1_100.0)], now=1_100.0)
        self.assertEqual(1, read.call_count, "the failing read was retried")
        self.assertEqual(history.RESET_UNREADABLE, lane.notice())
        self.assertEqual(["working"], [e["state"] for e in first])
        self.assertEqual(["working", "idle"], [e["state"] for e in second])

    def test_diagnose_still_runs_over_a_tampered_store(self) -> None:
        # `SKILL.md` sends the reader to --diagnose first whenever a harness is
        # missing, so the tool that reports the problem must not die of it.
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.write(self.TAMPERED["overflow"])
        code = run_one_shot_cli(["--diagnose"], isolated_environment(self.state_home, home.name))
        self.assertEqual(0, code)


class AQuietStoreStillExpiresTest(HistoryStoreTestCase):
    """M-4: retention was reachable only from a write.

    `evict` ran from `appended`, which returned before reaching it when no
    transition was produced, and neither `load` nor `_decode` evicted at all. So
    a finished project, an uninstalled harness, or a machine left running with
    nothing active kept its observations past the fourteen-day window — on disk
    and republished in `/api/data`.
    """

    NOW = 9_000_000.0
    AGED = 9_000_000.0 - 100 * 24 * 60 * 60  # a hundred days old

    def write_aged_store(self, config: RuntimeConfig, count: int = 5) -> None:
        entries = [
            {
                "harness": "claude",
                "sid": f"s{index}",
                "project": "p/q",
                "state": "idle",
                "last_activity": self.AGED + index,
            }
            for index in range(count)
        ]
        with open(history.store_path(config), "w") as handle:
            json.dump({"v": history.SCHEMA_VERSION, "entries": entries}, handle)

    def test_a_hundred_day_old_store_expires_with_no_transition_to_carry_it(self) -> None:
        config = self.config()
        self.write_aged_store(config)
        # A genuinely empty board: no rows at all, so nothing anywhere produces
        # a transition and the old path never reached `evict`.
        payload = stub_application(config, [], self.diagnostics, now=self.NOW).collect(
            show_all=True
        )
        self.assertEqual([], payload["history"], "expired observations were republished")
        self.assertEqual([], json.loads(self.store_bytes(config))["entries"])
        entries, reset = history.load(config)
        self.assertIsNone(reset)
        self.assertEqual((), entries)


class DiagnoseReadsAndNeverWritesTest(HistoryStoreTestCase):
    """M-5: `--diagnose` attached a recording lane and wrote the store.

    `SKILL.md` sends the reader to `--diagnose` first whenever a harness is
    missing, and it is the natural way to check that a delete took. One run into
    a clean `COMPASS_HOME` created a 26,086-byte store of 189 records spanning
    13.41 days, 176 of them outside `window_hours` and so records no serving
    collection could ever have made; `--forget && --diagnose` put the deleted
    file back.
    """

    def diagnosable_environment(self) -> dict[str, str]:
        """An isolated home with one discoverable session in it.

        The session is the point: `--diagnose` on a machine with no stores at
        all collects nothing and writes nothing whatever lane is attached, so an
        assertion made there would pass for the defect too. One transcript is
        enough to produce the transition that used to reach the file.
        """
        import time  # noqa: PLC0415

        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        env = isolated_environment(self.state_home, home.name)
        seed_claude_transcript(
            Path(env["CLAUDE_CONFIG_DIR"]) / "projects",
            "-nonexistent-compass-test-repos-recce-compass",
            when=time.time(),
        )
        return env

    def test_diagnose_over_a_discovered_session_leaves_no_store(self) -> None:
        env = self.diagnosable_environment()
        self.assertEqual(0, run_one_shot_cli(["--diagnose"], env))
        self.assertFalse(os.path.exists(os.path.join(self.state_home, history.STORE_FILENAME)))

    def test_forget_then_diagnose_does_not_put_the_store_back(self) -> None:
        config = self.config()
        history.record(config, [loaded_row()], now=1_000.0)
        env = self.diagnosable_environment()
        with no_instance():
            self.assertEqual(0, run_one_shot_cli(["--forget"], env))
        self.assertFalse(os.path.exists(history.store_path(config)))
        self.assertEqual(0, run_one_shot_cli(["--diagnose"], env))
        self.assertFalse(os.path.exists(history.store_path(config)), "--diagnose recreated it")


class TheSizeCapCostsOneSerialisationTest(HistoryStoreTestCase):
    """DR-1: the cap re-serialised the whole store once per dropped record.

    Measured before this change: 4.505 s and 593 `json.dumps` calls over a store
    an external tool had compacted, inside the collection memo lock on a thread
    that can be answering a request. And the premise the loop leaned on, that
    "an oversized store never reaches this loop", was false — `load` caps the
    raw file's bytes while `_payload` re-serialises 8.16% larger.
    """

    def entries(self, count: int) -> list[history.Observation]:
        return [
            history.Observation(
                harness="claude",
                sid=f"s{index:04d}",
                project="recce/compass",
                state="working",
                last_activity=1_000.0 + index,
                annotation_goal="",
                annotation_revision=None,
            )
            for index in range(count)
        ]

    def test_the_size_arithmetic_is_what_the_payload_actually_measures(self) -> None:
        # The replacement sizes the store from each record's own length, so this
        # is what keeps that arithmetic honest against the bytes `save` writes.
        for count in (0, 1, 2, 17):
            with self.subTest(records=count):
                records = self.entries(count)
                lengths = [len(json.dumps(dict(record))) for record in records]
                self.assertEqual(
                    len(history._payload(records)),
                    history._store_bytes(lengths),
                )

    def test_a_store_far_over_the_cap_lands_inside_it_and_drops_no_more(self) -> None:
        records = self.entries(600)
        kept = history.evict(records, now=1_600.0, retention_sec=1_000_000.0, max_bytes=2_000)
        self.assertLessEqual(len(history._payload(kept)), 2_000)
        self.assertEqual(records[-1]["last_activity"], kept[-1]["last_activity"])
        # And not one record more than it had to: putting the next-oldest back
        # exceeds the cap, which is what goes red if the arithmetic
        # over-subtracts and the loop drops too far.
        restored = [records[len(records) - len(kept) - 1], *kept]
        self.assertGreater(len(history._payload(restored)), 2_000)


class TheDefaultProductionPathRecordsTest(HistoryStoreTestCase):
    """DR-2: every history test drove the `--no-events` exit of
    `_apply_overlays`.

    Default flags take the other exit, because a coordinator is attached unless
    `--no-events` is passed. Mutating that exit to `return {}` disabled the
    whole feature for every default user — no store, no payload key — and left
    423 tests green.
    """

    def test_a_collection_with_a_coordinator_attached_still_records(self) -> None:
        from compass_runtime import observation  # noqa: PLC0415

        config = self.config()
        rows = [{"sid": "sid-1", "state": "working", "last_activity": 4_900.0}]
        application = stub_application(config, rows, self.diagnostics)
        # Constructed inert, exactly as `cli` constructs it before serving.
        application.overlays = observation.Observation(application)
        payload = application.collect(show_all=True)
        self.assertEqual(["working"], [e["state"] for e in payload["history"]])
        self.assertEqual(1, len(json.loads(self.store_bytes(config))["entries"]))


class ADismissedSessionsObservationSurvivesTest(HistoryStoreTestCase):
    """DR-3: the recording has to happen before the dismissal subtraction.

    A dismissal hides an alert; an observation that happened still happened.
    With the two lines swapped, a dismissed session's transitions are recorded
    not at all — and dismissing a row is a normal reader action rather than an
    edge case.
    """

    def test_the_row_is_subtracted_and_the_observation_is_still_recorded(self) -> None:
        from compass_runtime import dismissals  # noqa: PLC0415

        config = self.config()
        rows = [{"sid": "sid-1", "state": "working", "last_activity": 4_900.0}]
        application = stub_application(config, rows, self.diagnostics)
        self.assertTrue(
            dismissals.dismiss(
                config,
                application.state,
                "claude",
                "sid-1",
                now=5_000.0,
                diagnostic_sink=self.diagnostics.append,
            )
        )
        payload = application.collect(show_all=True)
        self.assertEqual([], payload["sessions"], "the mark did not hide the row")
        self.assertEqual(["working"], [e["state"] for e in payload["history"]])


class TheDedupeKeyIsPerSessionAndNotPerHarnessTest(HistoryStoreTestCase):
    """DR-4: no history test used more than one session.

    Collapsing the `(harness, sid)` baseline key to `harness` alone kept every
    test green and did two things, the second worse than the first: it
    suppressed a real transition, and it fabricated one that never happened —
    in a store whose entire contract is field provenance.
    """

    def row(self, sid: str, state: str, activity: float) -> dict[str, Any]:
        row = runtime_sessions.base_session("claude", sid, "recce/compass")
        row.update({"state": state, "last_activity": activity, "own_activity": activity})
        return row

    def test_two_sessions_keep_their_own_baselines(self) -> None:
        config = self.config()
        history.record(
            config,
            [self.row("sid-1", "working", 1_000.0), self.row("sid-2", "idle", 1_001.0)],
            now=1_001.0,
        )
        history.record(
            config,
            [self.row("sid-1", "working", 1_100.0), self.row("sid-2", "working", 1_101.0)],
            now=1_101.0,
        )
        entries, _reset = history.load(config)
        observed = [(e["sid"], e["state"], e["last_activity"]) for e in entries]
        self.assertEqual(
            [
                ("sid-1", "working", 1_000.0),
                ("sid-2", "idle", 1_001.0),
                ("sid-2", "working", 1_101.0),
            ],
            observed,
        )


class BothBoundsAreConfigurableTest(HistoryStoreTestCase):
    """The captain's ND-1 ruling: two knobs, so the contract's sentence is true.

    `SECURITY.md` said "Retention is 14 days by default, with a size cap, and
    both are configurable" while `build_runtime_config` accepted neither — the
    sentence was inherited verbatim from the plan doc the promotion came from,
    and nothing in the build could move either figure.
    """

    def parsed(self, argv: list[str]) -> Any:
        from compass_runtime import cli  # noqa: PLC0415

        return cli.build_parser().parse_args(argv)

    def built(self, argv: list[str]) -> RuntimeConfig:
        from compass_runtime import cli  # noqa: PLC0415

        with mock.patch.dict(os.environ, {COMPASS_HOME_ENV: self.state_home}):
            config, _state = cli.build_runtime(self.parsed(argv), started=1_700_000_000.0)
        return config

    def test_the_defaults_are_the_figures_the_contract_names(self) -> None:
        # Literals rather than the module's own constants: a test that reads the
        # subject's constants proves only that the subject agrees with itself,
        # and 14 days is what the promoted contract says in prose.
        config = self.built([])
        self.assertEqual(14 * 24 * 60 * 60, config.history_retention_sec)
        self.assertEqual(1_048_576, config.history_max_bytes)

    def test_both_flags_reach_the_configuration_the_lane_reads(self) -> None:
        config = self.built(["--history-days", "3", "--history-max-bytes", "4096"])
        self.assertEqual(3 * 24 * 60 * 60, config.history_retention_sec)
        self.assertEqual(4_096, config.history_max_bytes)

    def test_a_narrowed_window_is_the_window_the_lane_evicts_by(self) -> None:
        # The bound has to reach the eviction and not merely the dataclass, so
        # this drives a real lane: one observation a day old, a two-day window
        # narrowed to one, and the record has to be gone.
        config = self.built(["--history-days", "1"])
        lane = history.Lane(config, diagnostic_sink=self.diagnostics.append)
        day = 24 * 60 * 60.0
        lane.record([loaded_row("working", last_activity=1_000.0)], now=1_000.0)
        self.assertEqual(1, len(history.load(config)[0]))
        published = lane.record(
            [loaded_row("idle", last_activity=1_000.0 + 2 * day)], now=1_000.0 + 2 * day
        )
        self.assertEqual(["idle"], [e["state"] for e in published])
        self.assertEqual(["idle"], [e["state"] for e in history.load(config)[0]])

    def test_a_narrowed_cap_is_the_cap_the_lane_evicts_by(self) -> None:
        # DEC-22 adds four fields. Measure the actual single-row payload so
        # the test still asks whether the configured bound evicts, not whether
        # an obsolete hand-calculated size survives a schema admission.
        one = history.observation(loaded_row("working", last_activity=1_000.0))
        cap = len(json.dumps({"v": history.SCHEMA_VERSION, "entries": [one]}).encode()) + 8
        config = self.built(["--history-max-bytes", str(cap)])
        lane = history.Lane(config, diagnostic_sink=self.diagnostics.append)
        for tick, state in enumerate(("working", "idle", "working", "idle")):
            lane.record([loaded_row(state, last_activity=1_000.0 + tick)], now=1_000.0 + tick)
        kept, _reset = history.load(config)
        self.assertLessEqual(len(self.store_bytes(config)), cap)
        self.assertEqual(["idle"], [e["state"] for e in kept])
        self.assertEqual([1_003.0], [e["last_activity"] for e in kept])

    def test_neither_bound_accepts_a_nonsense_value(self) -> None:
        # Zero or negative is refused at parse time rather than clamped: a
        # window of zero days is a store that evicts everything it records,
        # which reads as broken rather than as off — and there is already a
        # switch that turns it off. Refused before a daemon can be respawned
        # with a bound the parent would not have accepted.
        for argv in (
            ["--history-days", "0"],
            ["--history-days", "-1"],
            ["--history-days", "nonsense"],
            ["--history-max-bytes", "0"],
            ["--history-max-bytes", "-4096"],
            ["--history-max-bytes", "1.5"],
        ):
            with (
                self.subTest(argv=" ".join(argv)),
                contextlib.redirect_stderr(std_io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                self.parsed(argv)


class ADirectoryAtTheStorePathOpensEmptyTest(HistoryStoreTestCase):
    """DR-6: `load`'s `except OSError` branch was dead to the suite.

    Deleting it kept 93 tests green, and with it gone a directory at the store
    path raises IsADirectoryError out of `Lane._open` into `Application.collect`
    and breaks the board rather than opening it empty.
    """

    def test_load_reports_a_reset_rather_than_raising(self) -> None:
        os.mkdir(os.path.join(self.state_home, history.STORE_FILENAME))
        entries, reset = history.load(self.config())
        self.assertEqual((), entries)
        self.assertEqual(history.RESET_UNREADABLE, reset)

    def test_a_lane_over_a_directory_still_serves_the_collection(self) -> None:
        os.mkdir(os.path.join(self.state_home, history.STORE_FILENAME))
        config = self.config()
        lane = history.Lane(config, diagnostic_sink=self.diagnostics.append)
        published = lane.record([loaded_row("working", last_activity=1_000.0)], now=1_000.0)
        self.assertEqual(["working"], [e["state"] for e in published])
        self.assertEqual(history.RESET_UNREADABLE, lane.notice())
        self.assertTrue(any("history store" in line for line in self.diagnostics))
