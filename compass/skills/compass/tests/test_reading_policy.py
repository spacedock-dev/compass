"""Remembered permission and rolling admission survive tabs and processes."""

from __future__ import annotations

import collections
import concurrent.futures
import contextlib
import functools
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import reading, reading_policy, reading_route, supervise

from .support import make_runtime


def _reserve_in_process(home: str) -> str:
    config, _ = make_runtime(state_dir=Path(home), state_home=home)
    return reading_policy.reserve(config, now=100.0)["reason"]


class ReadingPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)
        # An open model runner: GuardedModel refuses once it is shut.
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pausing_preserves_the_summary_answer_and_refuses_switch_presses(self) -> None:
        for allowed in (False, True):
            with self.subTest(allowed=allowed):
                reading_policy.set_consent(self.config, True, now=100.0)
                before = reading_policy.set_summary_consent(self.config, allowed, now=100.0)
                reading_policy.set_consent(self.config, False, now=101.0)
                for press in (True, False):
                    paused = reading_policy.set_summary_consent(self.config, press, now=102.0)
                    self.assertEqual("model-calls-paused", paused["reason"])
                    self.assertEqual(not allowed, paused["off"])
                    self.assertEqual(before["generation"], paused["generation"])
                self.assertEqual(
                    "model-calls-paused",
                    reading_policy.reserve_summary(self.config, now=103.0, receipt="paused")[
                        "reason"
                    ],
                )
                reading_policy.set_consent(self.config, True, now=104.0)
                self.assertEqual(before, reading_policy.summary_status(self.config, now=100.0))

    def test_resume_lifts_the_pause_and_grants_no_provider(self) -> None:
        reading_policy.set_consent(self.config, False, now=100.0)
        self.assertEqual(
            "model-calls-paused", reading_policy.reserve(self.config, now=100.0)["reason"]
        )
        answer = reading_policy.resume(self.config, now=101.0)
        self.assertFalse(answer["off"])
        self.assertTrue(answer["consent"])
        self.assertEqual(dict.fromkeys(reading_policy.PROVIDERS, False), answer["providers"])
        self.assertEqual("", reading_policy.reserve(self.config, now=102.0)["reason"])
        self.assertEqual("", reading_policy.summary_status(self.config, now=102.0)["reason"])

    def test_forget_stores_summaries_off_through_a_later_resume(self) -> None:
        for paused_first in (False, True):
            with self.subTest(paused_first=paused_first):
                reading_policy.set_consent(self.config, True, now=100.0)
                reading_policy.set_summary_consent(self.config, True, now=100.0)
                reading_policy.note(
                    self.config,
                    kind="summary",
                    provider="claude",
                    destination="Anthropic",
                    content=1,
                    tool_output="",
                    now=100.0,
                )
                if paused_first:
                    reading_policy.set_consent(self.config, False, now=100.5)
                self.assertTrue(reading_policy.forget(self.config, now=101.0))
                reading_policy.resume(self.config, now=102.0)
                answer = reading_policy.summary_status(self.config, now=103.0)
                self.assertTrue(answer["off"])
                self.assertEqual("summaries-off", answer["reason"])
                self.assertNotIn("summary", answer["notices"])
                self.assertEqual(
                    "summaries-off",
                    reading_policy.reserve_summary(self.config, now=103.0, receipt="forgot")[
                        "reason"
                    ],
                )

    def test_the_pause_outranks_a_spent_day(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0)
        for _ in range(reading_policy.DAILY_CAP):
            reading_policy.reserve(self.config, now=100.0)
        reading_policy.set_consent(self.config, False, now=101.0)
        for answer in (
            reading_policy.status(self.config, now=102.0),
            reading_policy.reserve(self.config, now=102.0),
        ):
            self.assertTrue(answer["off"])
            self.assertEqual("model-calls-paused", answer["reason"])
        resumed = reading_policy.resume(self.config, now=103.0)
        self.assertFalse(resumed["off"])
        self.assertEqual("daily-cap", resumed["reason"])

    def test_resume_under_a_disabled_run_keeps_the_stored_pause(self) -> None:
        reading_policy.set_consent(self.config, False, now=100.0)
        disabled, _ = make_runtime(state_dir=self.config.state_dir, model_calls_disabled=True)
        answer = reading_policy.resume(disabled, now=101.0)
        self.assertEqual("run-disabled", answer["reason"])
        self.assertFalse(answer["consent"])
        after = reading_policy.status(self.config, now=102.0)
        self.assertTrue(after["off"])
        self.assertEqual("model-calls-paused", after["reason"])

    def test_resume_lifts_a_pause_held_in_one_legacy_table_on_the_first_press(self) -> None:
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        ) as db:
            db.execute("CREATE TABLE permission (id INTEGER PRIMARY KEY, allowed INTEGER)")
            db.execute("INSERT INTO permission VALUES (1, 0)")
            db.commit()
        self.assertEqual(
            "model-calls-paused", reading_policy.summary_status(self.config, now=100.0)["reason"]
        )
        answer = reading_policy.resume(self.config, now=101.0)
        self.assertFalse(answer["off"])
        self.assertEqual("", answer["reason"])
        self.assertEqual("", reading_policy.reserve(self.config, now=102.0)["reason"])

    def test_summary_switch_leaves_analyze_coverage_and_goal_notice_unchanged(self) -> None:
        reading_policy.set_consent(
            self.config,
            True,
            now=100.0,
            provider="claude",
            destination="Anthropic",
            tool_output="Anthropic",
        )
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
        for allowed in (False, True):
            reading_policy.set_summary_consent(self.config, allowed, now=101.0)
            self.assertEqual(before, reading_policy.status(self.config, now=100.0))

    def test_summary_status_reads_without_a_write_lock_or_schema_writes(self) -> None:
        reading_policy.status(self.config, now=100.0)
        assert runtime_io.sqlite_module is not None
        path = reading_policy.store_path(self.config)
        with contextlib.closing(runtime_io.sqlite_module.connect(path)) as db:
            before = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master"))
        self.assertNotIn("summary_spends", before)
        answer = reading_policy.summary_status(self.config, now=100.0)
        self.assertEqual(("", 0, True), (answer["reason"], answer["used"], answer["consent"]))
        with contextlib.closing(runtime_io.sqlite_module.connect(path)) as db:
            after = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master"))
        self.assertEqual(before, after)
        # Another dashboard holding the write lock does not hold up a board read.
        reading_policy.reserve_summary(self.config, now=100.0, receipt="one")
        with contextlib.closing(
            runtime_io.sqlite_module.connect(path, isolation_level=None, timeout=0)
        ) as writer:
            writer.execute("BEGIN IMMEDIATE")
            answer = reading_policy.summary_status(self.config, now=100.0)
            writer.execute("ROLLBACK")
        self.assertEqual(("", 1), (answer["reason"], answer["used"]))
        # The window is the read's own filter; pruning stays on the write paths.
        self.assertEqual(0, reading_policy.summary_status(self.config, now=100.0 + 86_401)["used"])

    def test_pause_then_resume_shows_the_summary_notice_again(self) -> None:
        # SECURITY.md: Pause model calls clears the notices and Resume shows each again on the
        # next call, the summary's included. An earlier trigger of this branch that kept the
        # summary's notice is replaced on the next open.
        reading_policy.set_consent(self.config, True, now=100.0)
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        ) as db:
            for event in ("insert", "update"):
                for table in ("permission", "provider_permission"):
                    db.execute(f"DROP TRIGGER IF EXISTS notice_off_{table}_{event}")
                    db.execute(
                        f"CREATE TRIGGER reading_notice_off_{table}_{event} AFTER "  # noqa: S608
                        f"{event.upper()} ON {table} WHEN NEW.allowed=0 BEGIN "
                        "DELETE FROM notice WHERE kind != 'summary'; END"
                    )
            db.commit()
        args: dict[str, Any] = {
            "kind": "summary",
            "provider": "claude",
            "destination": "Anthropic",
            "content": 1,
            "tool_output": "",
        }
        self.assertIsNotNone(reading_policy.note(self.config, **args, now=100.0))
        reading_policy.note(
            self.config,
            kind="reading",
            provider="claude",
            destination="Anthropic",
            content=reading_policy.CONTENT_VERSION,
            tool_output="",
            now=100.0,
        )
        reading_policy.set_consent(self.config, False, now=101.0)
        self.assertEqual({}, reading_policy.summary_status(self.config, now=102.0)["notices"])
        answer = reading_policy.resume(self.config, now=103.0)
        self.assertEqual({}, answer["notices"])
        self.assertTrue(
            reading_policy.notice_due(reading_policy.summary_status(self.config, now=104.0), **args)
        )

    def test_fresh_store_is_on_without_explicit_unasked_coverage(self) -> None:
        answer = reading_policy.status(self.config, now=100.0)
        self.assertTrue(answer["consent"])
        self.assertFalse(answer["off"])
        self.assertEqual("", answer["reason"])
        self.assertEqual({"codex": False, "claude": False}, answer["providers"])
        self.assertEqual("", reading_policy.reserve(self.config, now=100.0)["reason"])

    def test_legacy_off_survives_upgrade_and_allow_turns_every_reader_call_on(self) -> None:
        # Frozen pre-rename schemas rather than ones the new writer defines: the
        # strict one, and the loose one an older build wrote with no CHECKs.
        schemas = {
            "strict": (
                (
                    "CREATE TABLE permission (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "allowed INTEGER NOT NULL CHECK(allowed IN (0,1)))"
                ),
                (
                    "CREATE TABLE provider_permission (provider TEXT PRIMARY KEY, "
                    "allowed INTEGER NOT NULL CHECK(allowed IN (0,1)))"
                ),
            ),
            "loose": (
                "CREATE TABLE permission (id INTEGER PRIMARY KEY, allowed INTEGER)",
                "CREATE TABLE provider_permission (provider TEXT PRIMARY KEY, allowed INTEGER)",
            ),
        }
        assert runtime_io.sqlite_module is not None
        for name, (permission, provider_permission) in schemas.items():
            with self.subTest(schema=name):
                reading_policy.store_path(self.config).unlink(missing_ok=True)
                with contextlib.closing(
                    runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
                ) as db:
                    db.execute(permission)
                    db.execute("INSERT OR REPLACE INTO permission VALUES (1, 0)")
                    db.execute(provider_permission)
                    db.execute("INSERT OR REPLACE INTO provider_permission VALUES ('claude', 0)")
                    db.commit()
                answer = reading_policy.status(self.config, now=100.0)
                self.assertTrue(answer["off"])
                self.assertFalse(answer["consent"])
                self.assertEqual(
                    "model-calls-paused", reading_policy.reserve(self.config, now=100.0)["reason"]
                )
                self.assertEqual(
                    "model-calls-paused",
                    reading_policy.reserve_summary(self.config, now=100.0, receipt="upgrade")[
                        "reason"
                    ],
                )
                self.assertTrue(reading_policy.set_consent(self.config, True, now=101.0)["consent"])
                self.assertEqual(
                    "", reading_policy.reserve(self.config, provider="claude", now=102.0)["reason"]
                )

    def test_notice_repeats_only_for_a_changed_disclosure_or_after_off(self) -> None:
        def note(**changes: Any) -> Any:
            args = {
                "kind": "reading",
                "provider": "claude",
                "destination": "Anthropic",
                "content": reading_policy.CONTENT_VERSION,
                "tool_output": "Anthropic",
                "now": 100.0,
            }
            return reading_policy.note(self.config, **{**args, **changes})

        first = note()
        self.assertEqual("Anthropic", first["destination"])
        self.assertEqual(
            first, reading_policy.status(self.config, now=100.0)["notices"]["reading"]["claude"]
        )
        self.assertIsNone(note())
        self.assertIsNotNone(note(destination="gateway.example"))
        self.assertIsNotNone(note(kind="goal"))
        self.assertIsNotNone(note(content=reading_policy.CONTENT_VERSION + 1))
        # A narrower press is covered by the wider record; a new tool-output
        # destination is not.
        self.assertIsNone(note(tool_output=""))
        self.assertIsNone(note(content=reading_policy.WORDS_CONTENT_VERSION))
        self.assertIsNotNone(note(tool_output="gateway.example"))
        reading_policy.set_consent(self.config, False, now=101.0)
        self.assertEqual({}, reading_policy.status(self.config, now=101.0)["notices"])
        self.assertIsNone(note())
        reading_policy.set_consent(self.config, True, now=102.0)
        self.assertIsNotNone(note())

    def test_notice_store_failure_refuses_and_disabled_run_records_nothing(self) -> None:
        args: dict[str, Any] = {
            "kind": "reading",
            "provider": "codex",
            "destination": "OpenAI",
            "content": reading_policy.WORDS_CONTENT_VERSION,
            "tool_output": "",
            "now": 100.0,
        }
        reading_policy.store_path(self.config).write_bytes(b"not sqlite")
        with self.assertRaises(reading_policy.RefusedError) as caught:
            reading_policy.note(self.config, **args)
        self.assertEqual("store-unavailable", caught.exception.answer["reason"])
        reading_policy.store_path(self.config).unlink()
        config, _ = make_runtime(state_dir=self.config.state_dir, model_calls_disabled=True)
        self.assertIsNone(reading_policy.note(config, **args))
        self.assertFalse(reading_policy.store_path(config).exists())

    def test_either_legacy_or_provider_off_alone_blocks_reader_calls(self) -> None:
        assert runtime_io.sqlite_module is not None
        for table, schema, values in (
            ("permission", "id INTEGER PRIMARY KEY, allowed INTEGER", "1, 0"),
            ("provider_permission", "provider TEXT PRIMARY KEY, allowed INTEGER", "'claude', 0"),
        ):
            with self.subTest(table=table):
                with contextlib.closing(
                    runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
                ) as db:
                    db.execute(f"CREATE TABLE {table} ({schema})")
                    db.execute(f"INSERT INTO {table} VALUES ({values})")  # noqa: S608 - fixed schema fixtures
                    db.commit()
                answer = reading_policy.status(self.config, now=100.0)
                self.assertTrue(answer["off"])
                self.assertEqual("model-calls-paused", answer["reason"])
                self.assertEqual(
                    "model-calls-paused", reading_policy.reserve(self.config, now=100.0)["reason"]
                )
                reading_policy.store_path(self.config).unlink()

    def test_old_build_turn_off_also_clears_the_notice_rows(self) -> None:
        reading_policy.note(
            self.config,
            kind="reading",
            provider="codex",
            destination="OpenAI",
            content=1,
            tool_output="",
            now=100.0,
        )
        assert runtime_io.sqlite_module is not None
        for table, statement in (
            ("permission", "INSERT OR REPLACE INTO permission VALUES (1, 0)"),
            (
                "provider_permission",
                "INSERT OR REPLACE INTO provider_permission VALUES ('claude', 0)",
            ),
        ):
            with self.subTest(table=table):
                reading_policy.set_consent(self.config, True, now=101.0)
                reading_policy.note(
                    self.config,
                    kind="goal",
                    provider="codex",
                    destination="OpenAI",
                    content=1,
                    tool_output="",
                    now=101.0,
                )
                with contextlib.closing(
                    runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
                ) as db:
                    db.execute(statement)
                    db.commit()
                answer = reading_policy.status(self.config, now=102.0)
                # Alone beside this build's Allow, a provider row's zero is not
                # an off (an older build's off always writes the legacy row too),
                # but the notices go either way.
                self.assertEqual(table == "permission", answer["off"])
                self.assertEqual({}, answer["notices"])

    def test_an_older_builds_allow_after_its_off_reads_as_on(self) -> None:
        # That build's Turn off wrote 0 for every provider and its Allow rewrote
        # only the provider allowed, so the reader's last answer was Allow.
        reading_policy.set_consent(self.config, False, now=100.0)
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        ) as db:
            db.execute("INSERT OR REPLACE INTO provider_permission VALUES ('claude', 1)")
            db.execute("INSERT OR REPLACE INTO permission_destination VALUES ('claude', 'A')")
            db.execute("INSERT OR REPLACE INTO permission_disclosure VALUES ('claude', 4, 'A')")
            db.commit()
        answer = reading_policy.status(
            self.config, now=101.0, provider="claude", destinations={"claude": "A"}
        )
        self.assertFalse(answer["off"])
        self.assertTrue(answer["consent"])
        self.assertEqual("", answer["reason"])
        self.assertEqual({"codex": False, "claude": True}, answer["providers"])
        self.assertEqual(
            "",
            reading_policy.reserve(self.config, now=102.0, provider="claude", destination="A")[
                "reason"
            ],
        )
        # And this build's off still stores off over it.
        self.assertTrue(reading_policy.set_consent(self.config, False, now=103.0)["off"])

    def test_alternating_routes_show_the_reading_notice_once(self) -> None:
        # Fallback routing: Claude Code reads its own sessions with tool output
        # and another harness's at the words tier, under one provider record.
        presses = (
            (reading_policy.CONTENT_VERSION, "Anthropic"),
            (reading_policy.WORDS_CONTENT_VERSION, ""),
        ) * 2
        shown = [
            reading_policy.note(
                self.config,
                kind="reading",
                provider="claude",
                destination="Anthropic",
                content=content,
                tool_output=tool_output,
                now=100.0 + index,
            )
            is not None
            for index, (content, tool_output) in enumerate(presses)
        ]
        self.assertEqual([True, False, False, False], shown)
        narrow_first = make_runtime(
            state_dir=Path(self.home.name) / "narrow", state_home=self.home.name
        )[0]
        shown = [
            reading_policy.note(
                narrow_first,
                kind="reading",
                provider="claude",
                destination="Anthropic",
                content=content,
                tool_output=tool_output,
                now=100.0 + index,
            )
            is not None
            for index, (content, tool_output) in enumerate(presses[1:])
        ]
        self.assertEqual([True, True, False], shown)

    def test_a_tampered_notice_row_is_not_published(self) -> None:
        reading_policy.note(
            self.config,
            kind="goal",
            provider="codex",
            destination="OpenAI",
            content=reading_policy.CONTENT_VERSION,
            tool_output="",
            now=100.0,
        )
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        ) as db:
            # Values the columns' affinity cannot coerce back to the right type.
            for row in (
                ("reading", "codex", b"OpenAI", 1, "", 100.0),
                ("reading", "claude", "Anthropic", "four", "", 100.0),
                ("summary", "codex", "OpenAI", 1, b"OpenAI", 100.0),
                ("summary", "claude", "Anthropic", 1, "", "soon"),
                ("goal", "claude", "Anthropic", 1, "", float("inf")),
            ):
                db.execute("INSERT OR REPLACE INTO notice VALUES (?, ?, ?, ?, ?, ?)", row)
            db.commit()
        notices = reading_policy.status(self.config, now=101.0)["notices"]
        self.assertEqual(["goal"], list(notices))
        self.assertEqual("OpenAI", notices["goal"]["codex"]["destination"])

    def test_retract_removes_only_the_notice_it_names(self) -> None:
        args: dict[str, Any] = {
            "kind": "reading",
            "provider": "codex",
            "destination": "OpenAI",
            "content": reading_policy.WORDS_CONTENT_VERSION,
            "tool_output": "",
        }
        first = reading_policy.note(self.config, **args, now=100.0)
        assert first is not None
        reading_policy.retract(self.config, first)
        self.assertEqual({}, reading_policy.status(self.config, now=101.0)["notices"])
        again = reading_policy.note(self.config, **args, now=102.0)
        self.assertIsNotNone(again)
        reading_policy.retract(self.config, first)
        self.assertEqual(
            again, reading_policy.status(self.config, now=103.0)["notices"]["reading"]["codex"]
        )

    def test_answer_survives_a_new_client_and_forget_preserves_spend(self) -> None:
        self.assertTrue(reading_policy.status(self.config, now=100.0)["consent"])
        self.assertTrue(reading_policy.set_consent(self.config, True, now=100.0)["consent"])
        self.assertEqual("", reading_policy.reserve(self.config, now=100.0)["reason"])
        self.assertEqual(1, reading_policy.status(self.config, now=101.0)["used"])
        answer = reading_policy.set_consent(self.config, False, now=102.0)
        self.assertFalse(answer["consent"])
        self.assertEqual(1, answer["used"])
        self.assertTrue(reading_policy.forget(self.config, now=103.0))
        self.assertEqual(1, reading_policy.status(self.config, now=103.0)["used"])

    def test_a_narrow_allow_retains_a_wider_allow_only_at_the_same_destination(self) -> None:
        reading_policy.set_consent(
            self.config, True, now=100.0, provider="codex", destination="OpenAI"
        )
        reading_policy.set_consent(
            self.config,
            True,
            now=101.0,
            provider="codex",
            destination="OpenAI",
            content=reading_policy.WORDS_CONTENT_VERSION,
        )
        self.assertTrue(
            reading_policy.status(self.config, now=101.0, destinations={"codex": "OpenAI"})[
                "consent"
            ]
        )
        reading_policy.set_consent(
            self.config,
            True,
            now=102.0,
            provider="codex",
            destination="changed.example",
            content=reading_policy.WORDS_CONTENT_VERSION,
        )
        refused = reading_policy.reserve(self.config, now=103.0, destination="changed.example")
        self.assertEqual("", refused["reason"])
        self.assertEqual(reading_policy.CONTENT_CHANGED, refused["rebind"]["codex"])
        self.assertEqual(1, refused["used"])

    def test_a_pre_fix_version_three_row_cannot_prove_its_disclosed_tier(self) -> None:
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        ) as db:
            db.execute("CREATE TABLE permission (id INTEGER PRIMARY KEY, allowed INTEGER)")
            db.execute("INSERT INTO permission VALUES (1, 1)")
            db.execute(
                "CREATE TABLE permission_destination (provider TEXT PRIMARY KEY, destination TEXT)"
            )
            db.execute("INSERT INTO permission_destination VALUES ('codex', 'OpenAI')")
            db.execute(
                "CREATE TABLE permission_disclosure "
                "(provider TEXT PRIMARY KEY, version INTEGER, destination TEXT)"
            )
            db.execute("INSERT INTO permission_disclosure VALUES ('codex', 3, 'OpenAI')")
            db.commit()
        refused = reading_policy.reserve(self.config, now=100.0, destination="OpenAI")
        self.assertEqual("", refused["reason"])
        self.assertEqual(reading_policy.CONTENT_CHANGED, refused["rebind"]["codex"])
        self.assertEqual(1, refused["used"])
        self.assertTrue(refused["words"]["codex"])
        reading_policy.set_consent(
            self.config, True, now=101.0, provider="codex", destination="OpenAI"
        )
        self.assertEqual(
            "", reading_policy.reserve(self.config, now=102.0, destination="OpenAI")["reason"]
        )

    def test_turn_off_clears_every_content_tier_and_tool_output_grant(self) -> None:
        reading_policy.set_consent(
            self.config,
            True,
            now=100.0,
            provider="codex",
            destination="OpenAI",
            content=reading_policy.WORDS_CONTENT_VERSION,
        )
        reading_policy.set_consent(
            self.config,
            True,
            now=100.0,
            provider="claude",
            destination="Anthropic",
            tool_output="Anthropic",
        )
        reading_policy.reserve(self.config, now=100.0, provider="claude", destination="Anthropic")
        reading_policy.set_consent(self.config, False, now=101.0)
        for provider, destination, content in (
            ("codex", "OpenAI", reading_policy.WORDS_CONTENT_VERSION),
            ("claude", "Anthropic", reading_policy.CONTENT_VERSION),
        ):
            with self.subTest(provider=provider):
                refused = reading_policy.reserve(
                    self.config,
                    now=102.0,
                    provider=provider,
                    destination=destination,
                    content=content,
                )
                self.assertEqual("model-calls-paused", refused["reason"])
                self.assertEqual(1, refused["used"])
                self.assertEqual({}, refused["tool_output"])

    def test_rolling_cap_expires_at_the_oldest_spend_not_midnight(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0)
        for offset in range(reading_policy.DAILY_CAP):
            self.assertEqual("", reading_policy.reserve(self.config, now=100.0 + offset)["reason"])
        refused = reading_policy.reserve(self.config, now=150.0)
        self.assertEqual("daily-cap", refused["reason"])
        self.assertEqual(86500.0, refused["retry_at"])
        self.assertEqual("", reading_policy.reserve(self.config, now=86500.0)["reason"])
        self.assertEqual("daily-cap", reading_policy.reserve(self.config, now=86500.0)["reason"])

    def test_concurrent_clients_cannot_admit_more_than_the_cap(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0)
        cap = reading_policy.DAILY_CAP
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(lambda _: reading_policy.reserve(self.config, now=100.0), range(2 * cap))
            )
        self.assertEqual(cap, sum(result["reason"] == "" for result in results))
        self.assertEqual(cap, reading_policy.status(self.config, now=100.0)["used"])

    def test_known_missing_cli_reserves_nothing(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0)
        for binary in (None, "relative/codex"):
            with self.subTest(binary=binary):
                model = reading.CodexReadingModel(
                    self.config, binary_resolver=mock.Mock(return_value=binary)
                )
                guarded = reading_policy.GuardedModel(self.config, model, lambda: 100.0)
                self.assertEqual(("", "unavailable"), guarded("prompt", output_cap_bytes=100))
                self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])

    def test_corrupt_store_never_resets_permission_or_budget(self) -> None:
        reading_policy.store_path(self.config).write_bytes(b"not a database")
        self.assertEqual(
            "store-unavailable", reading_policy.reserve(self.config, now=100.0)["reason"]
        )
        self.assertEqual(
            "store-unavailable", reading_policy.set_consent(self.config, True, now=100.0)["reason"]
        )

    def test_failed_model_attempt_is_charged_without_a_refund(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0)
        model = mock.Mock(side_effect=TimeoutError)
        guarded = reading_policy.GuardedModel(self.config, model, lambda: 100.0)
        with self.assertRaises(TimeoutError):
            guarded("prompt", output_cap_bytes=100)
        self.assertEqual(1, reading_policy.status(self.config, now=100.0)["used"])

    def test_a_committed_reservation_is_announced_and_a_refused_one_is_not(self) -> None:
        """DRC-4686: a reading job's restart marker is written from this seam.

        Called after the spend is committed and before the model runs, so a
        marker never says an attempt was spent when it was not.
        """
        used_when_told: list[int] = []

        def reserved() -> None:
            used_when_told.append(reading_policy.status(self.config, now=100.0)["used"])

        model = mock.Mock(return_value=("{}", "ok"))
        guarded = reading_policy.GuardedModel(
            self.config, model, lambda: 100.0, on_reserved=reserved
        )
        reading_policy.set_consent(self.config, False, now=100.0)
        with self.assertRaises(reading_policy.RefusedError):
            guarded("prompt", output_cap_bytes=100)
        self.assertEqual([], used_when_told)
        model.assert_not_called()
        reading_policy.set_consent(self.config, True, now=100.0)
        guarded("prompt", output_cap_bytes=100)
        self.assertEqual([1], used_when_told)
        model.available = mock.Mock(return_value=False)
        self.assertEqual(("", "unavailable"), guarded("prompt", output_cap_bytes=100))
        self.assertEqual([1], used_when_told)

    def test_a_marker_that_cannot_be_written_stops_the_call_before_it_spends(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0)
        model = mock.Mock(return_value=("{}", "ok"))
        guarded = reading_policy.GuardedModel(
            self.config, model, lambda: 100.0, before_reserve=mock.Mock(side_effect=OSError)
        )
        with self.assertRaises(OSError):
            guarded("prompt", output_cap_bytes=100)
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])
        model.assert_not_called()

    def test_a_call_made_while_compass_stops_is_refused_before_it_spends(self) -> None:
        """Verify N4: a job still preparing at shutdown must not be charged for nothing."""
        reading_policy.set_consent(self.config, True, now=100.0)
        model = mock.Mock(return_value=("{}", "ok"))
        stopping = threading.Event()
        stopping.set()
        with mock.patch.object(supervise, "_SHUTDOWN", stopping):
            guarded = reading_policy.GuardedModel(self.config, model, lambda: 100.0)
            self.assertEqual(("", "closed"), guarded("prompt", output_cap_bytes=100))
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])
        model.assert_not_called()

    def test_missing_sqlite_refuses_permission_and_launch(self) -> None:
        with mock.patch.object(runtime_io, "sqlite_module", None):
            self.assertEqual(
                "store-unavailable",
                reading_policy.set_consent(self.config, True, now=100.0)["reason"],
            )
            self.assertEqual(
                "store-unavailable", reading_policy.reserve(self.config, now=100.0)["reason"]
            )

    def test_separate_processes_share_the_same_admission_bound(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0)
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(_reserve_in_process, [self.home.name] * (2 * reading_policy.DAILY_CAP))
            )
        # Every reason, not two counts: on a Windows runner three presses came
        # back neither admitted nor capped, and the counts could not say why.
        cap = reading_policy.DAILY_CAP
        self.assertEqual({"": cap, "daily-cap": cap}, collections.Counter(results))

    def test_a_reservation_waits_out_a_write_that_outlasts_a_read(self) -> None:
        # DRC-4707: a press refused as store-unavailable while under the cap,
        # because another process held the store longer than the 2 s a write
        # used to wait. Held here past the read wait, the reservation must
        # still be waiting when the holder lets go, and then be admitted.
        reading_policy.set_consent(self.config, True, now=100.0)
        assert runtime_io.sqlite_module is not None
        holder = runtime_io.sqlite_module.connect(
            reading_policy.store_path(self.config), isolation_level=None
        )
        reasons: list[str] = []
        worker = threading.Thread(
            target=lambda: reasons.append(reading_policy.reserve(self.config, now=100.0)["reason"])
        )
        try:
            holder.execute("BEGIN IMMEDIATE")
            worker.start()
            worker.join(reading_policy.READ_WAIT_SEC + 0.5)
            waited = worker.is_alive()
            holder.execute("COMMIT")
        finally:
            holder.close()
        worker.join(reading_policy.WRITE_WAIT_SEC)
        self.assertTrue(waited, f"refused while the store was held: {reasons}")
        self.assertEqual([""], reasons)


class PermissionIsPerProviderTest(unittest.TestCase):
    """DRC-4650: allowing Codex to read a session is not allowing Anthropic to.

    The answer a reader gave named one receiver. A second provider receives a
    reader's words only after the page named it and the reader allowed it.
    """

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)

    def _consent(self, provider: str) -> bool:
        return reading_policy.status(self.config, now=100.0, provider=provider)["providers"][
            provider
        ]

    def test_a_reader_who_allowed_codex_has_not_allowed_claude_code(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0, provider="codex")
        self.assertTrue(self._consent("codex"))
        self.assertFalse(self._consent("claude"))
        refused = reading_policy.reserve(self.config, now=100.0, provider="claude")
        self.assertEqual("", refused["reason"])
        self.assertEqual(1, reading_policy.status(self.config, now=100.0)["used"])

    def test_allowing_claude_code_allows_only_claude_code(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0, provider="claude")
        self.assertTrue(self._consent("claude"))
        self.assertFalse(self._consent("codex"))
        self.assertEqual(
            "", reading_policy.reserve(self.config, now=100.0, provider="claude")["reason"]
        )

    def test_an_answer_saved_before_there_were_two_providers_reads_as_codex(self) -> None:
        path = reading_policy.store_path(self.config)
        path.parent.mkdir(parents=True, exist_ok=True)
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(path)
        db.execute(
            "CREATE TABLE permission (id INTEGER PRIMARY KEY CHECK(id=1), "
            "allowed INTEGER NOT NULL CHECK(allowed IN (0,1)))"
        )
        db.execute("CREATE TABLE spends (at REAL NOT NULL)")
        db.execute("INSERT INTO permission VALUES (1, 1)")
        db.execute("INSERT INTO spends VALUES (99.0)")
        db.commit()
        db.close()
        # Codex's answer, as it was. It names no destination, so it covers no
        # press until it is given again (owner, 2026-10-02), and only Codex
        # is asked again as an Allow that moved.
        answer = reading_policy.status(self.config, now=100.0)
        self.assertEqual({"codex": reading_policy.DESTINATION_CHANGED}, answer["rebind"])
        self.assertFalse(self._consent("claude"))
        self.assertEqual(1, answer["used"])

    def test_turning_readings_off_or_forgetting_revokes_every_provider(self) -> None:
        for revoke in ("off", "forget"):
            with self.subTest(revoke=revoke):
                for provider in ("codex", "claude"):
                    reading_policy.set_consent(self.config, True, now=100.0, provider=provider)
                    reading_policy.reserve(self.config, now=100.0, provider=provider)
                used = reading_policy.status(self.config, now=100.0)["used"]
                if revoke == "off":
                    reading_policy.set_consent(self.config, False, now=100.0)
                else:
                    self.assertTrue(reading_policy.forget(self.config, now=100.0))
                self.assertFalse(self._consent("codex"))
                self.assertFalse(self._consent("claude"))
                self.assertEqual(used, reading_policy.status(self.config, now=100.0)["used"])

    def test_the_rolling_cap_is_shared_across_providers(self) -> None:
        for provider in ("codex", "claude"):
            reading_policy.set_consent(self.config, True, now=100.0, provider=provider)
        for index in range(reading_policy.DAILY_CAP):
            provider = ("codex", "claude")[index % 2]
            self.assertEqual(
                "", reading_policy.reserve(self.config, now=100.0, provider=provider)["reason"]
            )
        for provider in ("codex", "claude"):
            with self.subTest(provider=provider):
                self.assertEqual(
                    "daily-cap",
                    reading_policy.reserve(self.config, now=100.0, provider=provider)["reason"],
                )

    def test_the_published_status_says_which_providers_are_allowed(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0, provider="claude")
        published = reading_policy.status(self.config, now=100.0)
        self.assertEqual({"codex": False, "claude": True}, published["providers"])

    def test_no_other_name_can_be_allowed(self) -> None:
        for name in ("", "gemini", "openai"):
            with self.subTest(name=name):
                answer = reading_policy.set_consent(self.config, True, now=100.0, provider=name)
                self.assertFalse(any(answer["providers"].values()))
        self.assertEqual(
            {"codex": False, "claude": False},
            reading_policy.status(self.config, now=100.0)["providers"],
        )

    def test_the_run_off_switch_outranks_a_claude_code_answer(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0, provider="claude")
        config, _ = make_runtime(
            state_dir=Path(self.home.name), state_home=self.home.name, model_calls_disabled=True
        )
        self.assertEqual(
            "run-disabled", reading_policy.status(config, now=100.0, provider="claude")["reason"]
        )
        self.assertEqual(
            "run-disabled", reading_policy.reserve(config, now=100.0, provider="claude")["reason"]
        )

    def test_a_guarded_claude_code_model_runs_without_explicit_permission(self) -> None:
        model = mock.Mock(return_value=("{}", "ok"))
        guarded = reading_policy.GuardedModel(self.config, model, lambda: 100.0, provider="claude")
        self.assertEqual(("{}", "ok"), guarded("prompt", output_cap_bytes=100))
        self.assertEqual(1, model.call_count)

    def test_a_known_missing_claude_code_reserves_nothing(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0, provider="claude")
        model = reading.ClaudeReadingModel(
            self.config, binary_resolver=mock.Mock(return_value=None)
        )
        guarded = reading_policy.GuardedModel(self.config, model, lambda: 100.0, provider="claude")
        self.assertEqual(("", "unavailable"), guarded("prompt", output_cap_bytes=100))
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])


class AnAllowGivenBeforeToolOutputWasNamedDoesNotCoverIt(unittest.TestCase):
    """DEC-23 item 7: tool output leaves only after a fresh Allow whose
    disclosure named it and its destination. The grant is its own row, keyed
    by provider and destination, so no older answer can be read as one."""

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)

    def _granted(self, provider: str, where: str) -> bool:
        answer = reading_policy.status(self.config, now=100.0, provider=provider)
        return reading_policy.tool_output_allowed(answer, provider, where)

    def test_a_reader_who_allowed_both_providers_before_this_build_sent_no_tool_output(
        self,
    ) -> None:
        for provider in ("codex", "claude"):
            reading_policy.set_consent(self.config, True, now=100.0, provider=provider)
        for provider in ("codex", "claude"):
            with self.subTest(provider=provider):
                self.assertTrue(
                    reading_policy.status(self.config, now=100.0, provider=provider)["consent"]
                )
                self.assertFalse(self._granted(provider, reading_route_vendor(provider)))

    def test_an_allow_naming_a_destination_covers_that_destination_and_no_other(self) -> None:
        answer = reading_policy.set_consent(
            self.config, True, now=100.0, provider="codex", tool_output="OpenAI"
        )
        self.assertTrue(answer["consent"])
        self.assertTrue(reading_policy.tool_output_allowed(answer, "codex", "OpenAI"))
        self.assertTrue(self._granted("codex", "OpenAI"))
        self.assertFalse(self._granted("codex", "gw.corp.example"))
        self.assertFalse(self._granted("claude", "OpenAI"))

    def test_an_empty_destination_is_never_a_grant(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0, provider="codex", tool_output="")
        self.assertFalse(self._granted("codex", ""))
        self.assertEqual({}, reading_policy.status(self.config, now=100.0)["tool_output"])

    def test_turning_readings_off_or_forgetting_withdraws_every_tool_output_grant(self) -> None:
        for revoke in ("off", "forget"):
            with self.subTest(revoke=revoke):
                reading_policy.set_consent(
                    self.config, True, now=100.0, provider="codex", tool_output="OpenAI"
                )
                if revoke == "off":
                    reading_policy.set_consent(self.config, False, now=100.0)
                else:
                    reading_policy.forget(self.config, now=100.0)
                self.assertFalse(self._granted("codex", "OpenAI"))

    def test_a_store_that_cannot_be_read_grants_nothing(self) -> None:
        reading_policy.store_path(self.config).write_bytes(b"not a database")
        answer = reading_policy.set_consent(
            self.config, True, now=100.0, provider="codex", tool_output="OpenAI"
        )
        self.assertEqual("store-unavailable", answer["reason"])
        self.assertFalse(reading_policy.tool_output_allowed(answer, "codex", "OpenAI"))


def reading_route_vendor(provider: str) -> str:
    return {"codex": "OpenAI", "claude": "Anthropic"}[provider]


class ARollbackCannotResurrectConsentTest(unittest.TestCase):
    """DRC-4666: a pre-L6 build's Turn off writes only the legacy row.

    That build runs `INSERT OR REPLACE INTO permission VALUES (1, 0)` and knows
    no other table, so without a trigger in the store's own schema its Turn off
    and `--forget` left `provider_permission('claude', 1)` standing, and the
    Claude Code answer came back on the next upgrade.
    """

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)

    def _old_build_writes(self, statement: str) -> None:
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        db.execute(statement)
        db.commit()
        db.close()

    def test_an_old_builds_turn_off_revokes_claude_code_and_its_tool_grants(self) -> None:
        for statement in (
            "INSERT OR REPLACE INTO permission VALUES (1, 0)",
            "UPDATE permission SET allowed = 0 WHERE id = 1",
        ):
            with self.subTest(statement=statement):
                reading_policy.set_consent(self.config, True, now=100.0, provider="codex")
                reading_policy.set_consent(
                    self.config, True, now=100.0, provider="claude", tool_output="Anthropic"
                )
                before = reading_policy.status(self.config, now=100.0, provider="claude")
                self.assertTrue(before["consent"])
                self.assertEqual({"claude": ["Anthropic"]}, before["tool_output"])
                self._old_build_writes(statement)
                after = reading_policy.status(self.config, now=100.0, provider="claude")
                self.assertFalse(after["consent"])
                self.assertEqual({"codex": False, "claude": False}, after["providers"])
                self.assertEqual({}, after["tool_output"])

    def test_an_old_builds_allow_leaves_claude_code_alone(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0, provider="claude")
        self._old_build_writes("INSERT OR REPLACE INTO permission VALUES (1, 1)")
        self.assertTrue(reading_policy.status(self.config, now=100.0, provider="claude")["consent"])


class TheCapOutranksConsentTest(unittest.TestCase):
    """DRC-4666: the page reads the Codex status, and the budget is shared.

    With only Claude Code allowed and the day's budget spent, the published
    answer said `consent-required`, which the page renders as nothing, so
    Analyze drift stayed enabled and the press answered 429.
    """

    def test_a_spent_budget_reads_daily_cap_for_a_provider_never_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, _ = make_runtime(state_dir=Path(home), state_home=home)
            reading_policy.set_consent(config, True, now=100.0, provider="claude")
            for offset in range(reading_policy.DAILY_CAP):
                self.assertEqual(
                    "",
                    reading_policy.reserve(config, now=100.0 + offset, provider="claude")["reason"],
                )
            published = reading_policy.status(config, now=200.0)
            self.assertTrue(published["consent"])
            self.assertEqual("daily-cap", published["reason"])
            self.assertEqual(
                "daily-cap", reading_policy.reserve(config, now=200.0, provider="codex")["reason"]
            )


class _StopAtTheInsert:
    """A connection that tries a shutdown at the moment the charge is inserted."""

    def __init__(self, db: Any, seen: list[bool]) -> None:
        self._db, self._seen = db, seen

    def execute(self, sql: str, *args: Any) -> Any:
        if sql.startswith("INSERT INTO spends"):
            stopper = threading.Thread(target=supervise.kill_all, daemon=True)
            stopper.start()
            stopper.join(0.3)
            self._seen.append(stopper.is_alive())
        return self._db.execute(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)


class TheReservationIsTheStopsLineTest(unittest.TestCase):
    """DRC-4712: a shutdown before the reservation commits spends nothing.

    The owner put the stop's line where the Cancel's is, at the reservation,
    and the reservation takes the lock `supervise.kill_all` takes. The seam's
    early `closed()` look is only the cheap path; these land after it.
    """

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        reading_policy.set_consent(self.config, True, now=50.0)

    def _stop_inside_the_transaction(self) -> Any:
        # `_allowed` runs after `BEGIN IMMEDIATE`, so a stop here has passed
        # every look taken before the transaction and lands before the commit.
        real = reading_policy._allowed

        def allowed(db: Any) -> Any:
            supervise.kill_all()
            return real(db)

        return mock.patch.object(reading_policy, "_allowed", allowed)

    def test_a_shutdown_while_the_reservation_is_open_reserves_nothing(self) -> None:
        with self._stop_inside_the_transaction():
            answer = reading_policy.reserve(self.config, now=100.0, job_id="j1")
        self.assertEqual("stopping", answer["reason"])
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])
        self.assertIs(False, reading_policy.charged(self.config, "j1", started_at=100.0, now=100.0))

    def test_the_guarded_seam_answers_a_stop_at_the_reservation_as_closed(self) -> None:
        model = mock.Mock(return_value=("{}", "ok"))
        guarded = reading_policy.GuardedModel(self.config, model, lambda: 100.0)
        with self._stop_inside_the_transaction():
            self.assertEqual(("", "closed"), guarded("prompt", output_cap_bytes=100))
        model.assert_not_called()
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])

    def test_a_shutdown_cannot_land_between_the_insert_and_the_commit(self) -> None:
        """Review T1: the lock covers the insert and the commit, not only the look."""
        seen: list[bool] = []
        real = reading_policy._connect
        with mock.patch.object(
            reading_policy,
            "_connect",
            lambda config, wait: _StopAtTheInsert(real(config, wait), seen),
        ):
            answer = reading_policy.reserve(self.config, now=100.0, job_id="j1")
        self.assertEqual([True], seen, "the shutdown ran while the charge was uncommitted")
        self.assertEqual("", answer["reason"])

    def test_a_shutdown_after_the_commit_leaves_the_charge_standing(self) -> None:
        self.assertEqual("", reading_policy.reserve(self.config, now=100.0, job_id="j1")["reason"])
        supervise.kill_all()
        self.assertEqual(1, reading_policy.status(self.config, now=100.0)["used"])
        self.assertIs(True, reading_policy.charged(self.config, "j1", started_at=100.0, now=100.0))


class TheJobLedgerTest(unittest.TestCase):
    """DRC-4713: the job id commits with its charge, in a table of its own."""

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        reading_policy.set_consent(self.config, True, now=50.0)

    def _charged(self, job_id: str, *, started_at: float = 100.0, now: float = 100.0) -> Any:
        return reading_policy.charged(self.config, job_id, started_at=started_at, now=now)

    def _rows(self) -> list[str]:
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        try:
            return [row[0] for row in db.execute("SELECT job FROM spend_jobs ORDER BY at")]
        finally:
            db.close()

    def test_the_ledger_drops_rows_past_30_days(self) -> None:
        """Review T2: SECURITY.md says 30 days, so the rows go at 30 days, not later."""
        reading_policy.reserve(self.config, now=100.0, job_id="j1")
        reading_policy.reserve(self.config, now=100.0 + 29 * 86_400.0, job_id="j2")
        self.assertEqual(["j1", "j2"], self._rows())
        reading_policy.status(self.config, now=100.0 + 31 * 86_400.0)
        self.assertEqual(["j2"], self._rows())

    def test_a_reservation_answers_the_count_it_made(self) -> None:
        self.assertEqual(1, reading_policy.reserve(self.config, now=100.0, job_id="j1")["used"])

    def test_a_prune_at_a_later_clock_is_not_read_as_no_charge(self) -> None:
        """F2: a row pruned under a clock that ran ahead is "cannot say", never "no charge"."""
        reading_policy.reserve(self.config, now=200.0, job_id="j1")
        reading_policy.status(self.config, now=200.0 + 31 * 86_400.0)
        # The clock is set back, and the marker's job now looks young again.
        self.assertIsNone(self._charged("j1", started_at=150.0, now=300.0))

    def test_a_store_recreated_after_the_job_started_cannot_answer_for_it(self) -> None:
        """F2: a deleted store's replacement knows nothing from before it was made."""
        reading_policy.reserve(self.config, now=200.0, job_id="j1")
        reading_policy.store_path(self.config).unlink()
        reading_policy.set_consent(self.config, True, now=400.0)
        self.assertIsNone(self._charged("j1", started_at=150.0, now=500.0))
        self.assertIs(False, self._charged("j2", started_at=450.0, now=500.0))

    def test_a_watermark_that_is_not_a_finite_number_cannot_answer(self) -> None:
        """Verify N1: a damaged watermark is "cannot say", never an exception."""
        assert runtime_io.sqlite_module is not None
        for value in ("not a number", float("inf"), None):
            with self.subTest(watermark=value):
                db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
                if value is None:
                    db.execute("UPDATE spend_jobs_since SET at = 'NaN' WHERE id = 1")
                else:
                    db.execute("UPDATE spend_jobs_since SET at = ? WHERE id = 1", (value,))
                db.commit()
                db.close()
                self.assertIsNone(self._charged("j2", started_at=1_000.0, now=2_000.0))

    def test_a_job_at_the_watermark_cannot_be_called_uncharged(self) -> None:
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        try:
            watermark = db.execute("SELECT at FROM spend_jobs_since WHERE id = 1").fetchone()[0]
        finally:
            db.close()
        self.assertIsNone(self._charged("absent", started_at=watermark, now=watermark + 1.0))
        self.assertIs(
            False, self._charged("absent", started_at=watermark + 0.5, now=watermark + 1.0)
        )

    def test_a_missing_watermark_cannot_answer_for_an_absent_job(self) -> None:
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        try:
            db.execute("DELETE FROM spend_jobs_since")
            db.commit()
        finally:
            db.close()
        self.assertIsNone(self._charged("absent", started_at=100.0, now=200.0))

    def test_a_reservation_records_its_job_and_no_other(self) -> None:
        reading_policy.reserve(self.config, now=100.0, job_id="j1")
        self.assertIs(True, self._charged("j1"))
        self.assertIs(False, self._charged("j2"))

    def test_the_guarded_seam_charges_under_the_id_its_marker_hook_names(self) -> None:
        model = mock.Mock(return_value=("{}", "ok"))
        guarded = reading_policy.GuardedModel(
            self.config, model, lambda: 100.0, before_reserve=lambda: "j9"
        )
        guarded("prompt", output_cap_bytes=100)
        self.assertIs(True, self._charged("j9"))

    def test_a_refused_reservation_records_no_job(self) -> None:
        reading_policy.set_consent(self.config, False, now=100.0)
        self.assertEqual(
            "model-calls-paused",
            reading_policy.reserve(self.config, now=100.0, job_id="j1")["reason"],
        )
        self.assertIs(False, self._charged("j1"))

    def test_the_ledger_outlives_the_budget_day_and_not_its_retention(self) -> None:
        reading_policy.reserve(self.config, now=100.0, job_id="j1")
        later = 100.0 + 2 * reading_policy.DAY_SEC
        reading_policy.reserve(self.config, now=later, job_id="j2")
        self.assertIs(True, self._charged("j1", now=later))
        past = 100.0 + reading_policy.JOB_LEDGER_SEC + 1.0
        reading_policy.reserve(self.config, now=past, job_id="j3")
        self.assertIsNone(self._charged("j1", now=past), "a pruned row read as uncharged")

    def test_a_ledger_that_cannot_answer_says_so(self) -> None:
        reading_policy.reserve(self.config, now=100.0, job_id="j1")
        with self.subTest("no job id"):
            self.assertIsNone(self._charged(""))
        with self.subTest("no usable start"):
            # A row answers whatever the start; only an absent one needs it.
            self.assertIs(True, self._charged("j1", started_at=float("nan")))
            self.assertIsNone(self._charged("j2", started_at=float("nan")))
        with self.subTest("SQLite missing"), mock.patch.object(runtime_io, "sqlite_module", None):
            self.assertIsNone(self._charged("j1"))
        with self.subTest("store corrupt"):
            reading_policy.store_path(self.config).write_bytes(b"not a database" * 100)
            self.assertIsNone(self._charged("j1"))
        with self.subTest("no store"):
            reading_policy.store_path(self.config).unlink()
            self.assertIsNone(self._charged("j1"))

    def test_a_store_from_before_the_ledger_cannot_answer(self) -> None:
        assert runtime_io.sqlite_module is not None
        reading_policy.store_path(self.config).unlink()
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        db.execute("CREATE TABLE spends (at REAL NOT NULL)")
        db.execute("INSERT INTO spends VALUES (100.0)")
        db.commit()
        db.close()
        self.assertIsNone(self._charged("j1"))

    def test_an_older_builds_reservation_still_works_on_the_new_store(self) -> None:
        """A rollback: that build writes one column to `spends` and knows no ledger."""
        assert runtime_io.sqlite_module is not None
        reading_policy.reserve(self.config, now=100.0, job_id="j1")
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM spends WHERE at <= ?", (100.0 - reading_policy.DAY_SEC,))
        db.execute("INSERT INTO spends VALUES (?)", (101.0,))
        db.execute("COMMIT")
        db.close()
        self.assertEqual(2, reading_policy.status(self.config, now=102.0)["used"])


class TheAllowForTheWordsIsBoundToItsDestination(unittest.TestCase):
    """Owner, 2026-10-02: "bind the allow to the destination".

    The tool-output grant was already keyed by destination; the Allow for the
    reader's words was not, so a daemon restarted under `ANTHROPIC_BASE_URL` or
    `CLAUDE_CODE_USE_BEDROCK` sent the goal and messages to the new endpoint
    under the old Allow. An Allow now covers a press only while the provider's
    destination is exactly the one its disclosure named.
    """

    ANTHROPIC: ClassVar[dict[str, str]] = {"codex": "OpenAI", "claude": "Anthropic"}

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _status(self, claude: str, provider: str = "claude") -> reading_policy.Status:
        return reading_policy.status(
            self.config,
            now=100.0,
            provider=provider,
            destinations={"codex": "OpenAI", "claude": claude},
        )

    def _allow(self, where: str, provider: str = "claude") -> reading_policy.Status:
        return reading_policy.set_consent(
            self.config, True, now=100.0, provider=provider, destination=where
        )

    def test_a_caller_that_names_no_destinations_is_never_covered(self) -> None:
        """Regressions minor 3 (ui5): `status`'s docstring says a provider left
        out of `destinations` reads as unnamed, so a caller that forgets it asks
        again rather than sends. Held for a future caller, with and without the
        argument and with the provider alone left out."""
        self._allow("Anthropic", provider="claude")
        self._allow("OpenAI", provider="codex")
        for name, destinations in (
            ("no argument", None),
            ("empty", {}),
            ("claude left out", {"codex": "OpenAI"}),
        ):
            with self.subTest(case=name):
                answer = reading_policy.status(
                    self.config, now=100.0, provider="claude", destinations=destinations
                )
                self.assertFalse(answer["providers"]["claude"])
                self.assertFalse(answer["providers"]["claude"])
                self.assertEqual(reading_policy.DESTINATION_CHANGED, answer["rebind"]["claude"])
        # And the reservation, which hands status only its own provider.
        refused = reading_policy.reserve(self.config, now=100.0, provider="claude")
        self.assertEqual("", refused["reason"])
        self.assertEqual(1, refused["used"])

    def test_an_unnamed_allow_keeps_covering_a_move_it_cannot_see(self) -> None:
        """Consent F2 (ui5): what SECURITY.md and the amendment's item 5 now
        say. Unnamed is its own value, so a move between two endpoints the
        resolver cannot name is not detected: on Windows, and between two
        Codex base URLs."""
        root = Path("/nonexistent-compass-root")
        for provider, before, after, system in (
            ("claude", {}, {"ANTHROPIC_BASE_URL": "https://elsewhere.example"}, "Windows"),
            ("claude", {}, {"CLAUDE_CODE_USE_BEDROCK": "1"}, "Windows"),
            (
                "codex",
                {"OPENAI_BASE_URL": "https://a.example"},
                {"OPENAI_BASE_URL": "https://b.example"},
                "Linux",
            ),
        ):
            with self.subTest(provider=provider, after=after, system=system):
                then, now = (
                    reading_route.destination(
                        provider,
                        environ={"HOME": "/home/r", "USER": "r", **environ},
                        root=root,
                        system=system,
                    )
                    for environ in (before, after)
                )
                self.assertEqual(("", ""), (then, now))
                reading_policy.set_consent(
                    self.config, True, now=100.0, provider=provider, destination=then
                )
                answer = reading_policy.status(
                    self.config, now=100.0, provider=provider, destinations={provider: now}
                )
                self.assertTrue(answer["providers"][provider])
                self.assertEqual({}, answer["rebind"])
                reading_policy.set_consent(self.config, False, now=100.0)

    def test_an_allow_covers_the_destination_it_was_given_for(self) -> None:
        answer = self._allow("Anthropic")
        self.assertTrue(answer["providers"]["claude"])
        self.assertTrue(self._status("Anthropic")["providers"]["claude"])
        self.assertEqual({"codex": False, "claude": True}, self._status("Anthropic")["providers"])
        self.assertEqual({}, self._status("Anthropic")["rebind"])

    def test_an_allow_for_anthropic_does_not_cover_a_base_url_host_or_bedrock(self) -> None:
        self._allow("Anthropic")
        for today in ("gw.corp.example", "Amazon Bedrock", ""):
            with self.subTest(today=today):
                answer = self._status(today)
                self.assertFalse(answer["providers"]["claude"])
                self.assertEqual("", answer["reason"])
                self.assertFalse(answer["providers"]["claude"])
                self.assertEqual({"claude": reading_policy.DESTINATION_CHANGED}, answer["rebind"])
                refused = reading_policy.reserve(
                    self.config, now=100.0, provider="claude", destination=today
                )
                self.assertEqual("", refused["reason"])
        self.assertEqual(3, self._status("Anthropic")["used"])

    def test_an_unnamed_destination_is_its_own_value(self) -> None:
        self._allow("")
        self.assertTrue(self._status("")["consent"])
        for today in ("Anthropic", "gw.corp.example"):
            with self.subTest(today=today):
                self.assertFalse(self._status(today)["providers"]["claude"])
                self.assertIn("claude", self._status(today)["rebind"])
        self.assertEqual(
            "", reading_policy.reserve(self.config, now=100.0, provider="claude")["reason"]
        )

    def test_a_new_allow_moves_the_binding_to_the_new_destination(self) -> None:
        self._allow("Anthropic")
        self._allow("gw.corp.example")
        self.assertTrue(self._status("gw.corp.example")["consent"])
        self.assertFalse(self._status("Anthropic")["providers"]["claude"])

    def test_the_job_admits_a_new_destination_without_an_allow(self) -> None:
        self._allow("Anthropic")
        model = mock.Mock(return_value=("{}", "ok"))
        guarded = reading_policy.GuardedModel(
            self.config, model, lambda: 100.0, provider="claude", destination="gw.corp.example"
        )
        self.assertEqual(("{}", "ok"), guarded("prompt", output_cap_bytes=100))
        self.assertEqual(1, self._status("Anthropic")["used"])

    def test_the_job_asks_where_the_words_go_again_at_its_reservation(self) -> None:
        """Consent F4 (ui5): a destination that moved after the press was
        admitted refuses the reservation, before the marker and the charge."""
        self._allow("Anthropic")
        model = mock.Mock(return_value=("{}", "ok"))
        marked = mock.Mock(return_value="job-1")
        for now, refused in (("gw.corp.example", True), ("", True), ("Anthropic", False)):
            with self.subTest(now=now):
                guarded = reading_policy.GuardedModel(
                    self.config,
                    model,
                    lambda: 100.0,
                    provider="claude",
                    destination="Anthropic",
                    resolve_destination=functools.partial(str, now),
                    before_reserve=marked,
                )
                if refused:
                    with self.assertRaises(reading_policy.RefusedError) as caught:
                        guarded("prompt", output_cap_bytes=100)
                    self.assertEqual("destination-changed", caught.exception.answer["reason"])
                    model.assert_not_called()
                    marked.assert_not_called()
                    self.assertEqual(0, self._status("Anthropic")["used"])
                else:
                    self.assertEqual(("{}", "ok"), guarded("prompt", output_cap_bytes=100))
        self.assertEqual(1, self._status("Anthropic")["used"])

    def test_an_allow_covers_the_same_destination_after_a_restart(self) -> None:
        self._allow("Anthropic")
        # Another process on the same home, as a respawned daemon is.
        config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)
        answer = reading_policy.status(
            config, now=100.0, provider="claude", destinations=self.ANTHROPIC
        )
        self.assertTrue(answer["providers"]["claude"])

    def test_a_decline_still_holds_across_a_destination_change(self) -> None:
        self._allow("Anthropic")
        reading_policy.set_consent(self.config, False, now=100.0)
        for today in ("Anthropic", "gw.corp.example", ""):
            with self.subTest(today=today):
                answer = self._status(today)
                self.assertFalse(answer["providers"]["claude"])
                # A refusal is never asked about as though the endpoint moved.
                self.assertEqual({}, answer["rebind"])

    def test_an_old_builds_allow_after_turn_off_does_not_revive_the_old_destination(
        self,
    ) -> None:
        self._allow("Anthropic")
        reading_policy.set_consent(self.config, False, now=100.0)
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        # What a pre-binding build's Allow writes, and nothing else.
        db.execute("INSERT OR REPLACE INTO provider_permission VALUES (?, ?)", ("claude", 1))
        db.commit()
        db.close()
        answer = self._status("Anthropic")
        self.assertFalse(answer["providers"]["claude"])
        self.assertIn("claude", answer["rebind"])

    def test_an_old_builds_turn_off_forgets_the_bound_destination(self) -> None:
        """That build knows only the legacy row, so a trigger in the schema does it."""
        self._allow("Anthropic")
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        # Its Turn off, then its Allow: neither statement names a destination.
        db.execute("INSERT OR REPLACE INTO permission VALUES (1, 0)")
        db.execute("INSERT OR REPLACE INTO provider_permission VALUES (?, ?)", ("claude", 1))
        db.commit()
        db.close()
        self.assertFalse(self._status("Anthropic")["providers"]["claude"])

    def test_the_tool_output_grants_rule_is_unchanged(self) -> None:
        answer = reading_policy.set_consent(
            self.config,
            True,
            now=100.0,
            provider="claude",
            tool_output="Anthropic",
            destination="Anthropic",
        )
        self.assertTrue(reading_policy.tool_output_allowed(answer, "claude", "Anthropic"))
        moved = self._status("gw.corp.example")
        # Still held for the destination it names, and never for an unnamed one.
        self.assertTrue(reading_policy.tool_output_allowed(moved, "claude", "Anthropic"))
        self.assertFalse(reading_policy.tool_output_allowed(moved, "claude", "gw.corp.example"))
        reading_policy.set_consent(
            self.config, True, now=100.0, provider="claude", tool_output="", destination=""
        )
        self.assertFalse(reading_policy.tool_output_allowed(self._status(""), "claude", ""))
        # Not even a row for "" that some other writer left in the table.
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        db.execute("INSERT INTO tool_output_permission VALUES ('claude', '')")
        db.commit()
        db.close()
        self.assertFalse(reading_policy.tool_output_allowed(self._status(""), "claude", ""))


class AStoreWrittenBeforeTheBindingIsMigratedInPlace(unittest.TestCase):
    """The schema a build before the destination binding leaves on disk.

    Its rows stay readable, by this build and by that one, and simply do not
    cover a press: each reader is asked once more, with the sentence saying
    why, and nothing else in the store changes.
    """

    SCHEMA = (
        (
            "CREATE TABLE permission (id INTEGER PRIMARY KEY CHECK(id=1), "
            "allowed INTEGER NOT NULL CHECK(allowed IN (0,1)))"
        ),
        (
            "CREATE TABLE provider_permission (provider TEXT PRIMARY KEY, "
            "allowed INTEGER NOT NULL CHECK(allowed IN (0,1)))"
        ),
        (
            "CREATE TABLE tool_output_permission (provider TEXT NOT NULL, "
            "destination TEXT NOT NULL, PRIMARY KEY (provider, destination))"
        ),
        "CREATE TABLE spends (at REAL NOT NULL)",
        "CREATE TABLE spend_jobs (job TEXT PRIMARY KEY, at REAL NOT NULL)",
        "CREATE TABLE spend_jobs_since (id INTEGER PRIMARY KEY CHECK(id=1), at REAL NOT NULL)",
        "INSERT INTO permission VALUES (1, 1)",
        "INSERT INTO provider_permission VALUES ('claude', 1)",
        "INSERT INTO tool_output_permission VALUES ('claude', 'Anthropic')",
        "INSERT INTO spends VALUES (99.0)",
        "INSERT INTO spend_jobs VALUES ('job-1', 99.0)",
        "INSERT INTO spend_jobs_since VALUES (1, 50.0)",
    )
    TODAY: ClassVar[dict[str, str]] = {"codex": "OpenAI", "claude": "Anthropic"}

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(self.home.name), state_home=self.home.name)
        path = reading_policy.store_path(self.config)
        path.parent.mkdir(parents=True, exist_ok=True)
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(path)
        for statement in self.SCHEMA:
            db.execute(statement)
        db.commit()
        db.close()

    def _rows(self, table: str) -> list[tuple[Any, ...]]:
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        try:
            return list(db.execute(f"SELECT * FROM {table} ORDER BY 1"))  # noqa: S608 - fixed names
        finally:
            db.close()

    def test_every_old_allow_is_on_but_explicit_coverage_still_needs_a_binding(self) -> None:
        answer = reading_policy.status(self.config, now=100.0, destinations=self.TODAY)
        self.assertEqual({"codex": False, "claude": False}, answer["providers"])
        self.assertEqual(
            dict.fromkeys(("codex", "claude"), reading_policy.DESTINATION_CHANGED),
            answer["rebind"],
        )
        self.assertEqual("", answer["reason"])
        self.assertTrue(answer["consent"])

    def test_nothing_else_in_the_store_is_lost(self) -> None:
        answer = reading_policy.status(self.config, now=100.0, destinations=self.TODAY)
        self.assertEqual(1, answer["used"])
        self.assertEqual({"claude": ["Anthropic"]}, answer["tool_output"])
        self.assertEqual([(1, 1)], self._rows("permission"))
        self.assertEqual([("claude", 1)], self._rows("provider_permission"))
        self.assertEqual([("job-1", 99.0)], self._rows("spend_jobs"))
        self.assertIs(
            True,
            reading_policy.charged(self.config, "job-1", started_at=60.0, now=100.0),
        )

    def test_an_older_build_can_still_write_the_migrated_store(self) -> None:
        reading_policy.status(self.config, now=100.0, destinations=self.TODAY)
        assert runtime_io.sqlite_module is not None
        db = runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        # Its own statements: two values each, which a third column would refuse.
        db.execute("INSERT OR REPLACE INTO provider_permission VALUES (?, ?)", ("claude", 1))
        db.execute("INSERT OR REPLACE INTO permission VALUES (1, ?)", (1,))
        db.execute("INSERT INTO spends VALUES (?)", (99.5,))
        db.commit()
        db.close()
        self.assertEqual(
            2, reading_policy.status(self.config, now=100.0, destinations=self.TODAY)["used"]
        )

    def test_one_fresh_allow_covers_that_provider_alone(self) -> None:
        reading_policy.set_consent(
            self.config, True, now=100.0, provider="claude", destination="Anthropic"
        )
        answer = reading_policy.status(self.config, now=100.0, destinations=self.TODAY)
        self.assertEqual({"codex": False, "claude": True}, answer["providers"])
        self.assertEqual({"codex": reading_policy.DESTINATION_CHANGED}, answer["rebind"])
