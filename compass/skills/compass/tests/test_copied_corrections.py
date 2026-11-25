"""A copied correction coming back unedited is recognised as Compass's words (DRC-4678).

Item 9 of
[DEC-24](docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy),
built to the owner's rulings of 2026-09-28. The server records a digest of the exact text the
reader copied; a later Claude Code user message whose raw text has the same digest, under one
normalisation applied to both sides, is `derived`: not a person's evidence, not a later direction,
never adopted. The normalisation is what the live paste capture on Claude Code 2.1.283 measured
the input box doing to a paste: CRLF and CR become LF, a tab becomes four spaces, and a short
paste loses its trailing whitespace.

Every text here is placeholder prose.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import http.client
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    aggregate,
    drift_view,
    http_api,
    observer,
    project_context,
    terminal_drift,
    terminal_sessions,
    transcripts,
)
from compass_runtime import annotations as annotation_store
from compass_runtime import copied_corrections as copies
from compass_runtime import io as runtime_io
from compass_runtime import reading as runtime_reading
from compass_runtime import sessions as runtime_sessions
from compass_runtime.collectors import codex
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from .support import SERVER_PATH, make_server, serve_until_closed
from .test_annotations_shared_home import _HOLD_LOCK
from .test_claude_checks import SHORT, START, Transcript
from .test_drift_view import BY_NAME, view
from .test_history import isolated_environment, no_instance, run_one_shot_cli

FIRST = "Add retry with backoff to the webhook handler."
NOW = START.timestamp() + 3600

# What the reader copied from Compass's box: over 112 characters, three lines, a tab, CRLF line
# ends and trailing whitespace, which is what a clipboard can hand back.
COPIED = (
    "Steer back to your intent: ship the placeholder parser and nothing else.\r\n"
    "\tLine 1 is not shown yet: the parser tests at #3 failed at 14:02.\r\n"
    "Keep the lexer as it is, and rerun the parser tests before anything else.  \n"
)
# What Claude Code 2.1.283 stored for that paste (paste4678, cases 2, 3 and 7): LF line ends, the
# tab as exactly four spaces, the trailing whitespace of a short paste gone.
STORED = (
    "Steer back to your intent: ship the placeholder parser and nothing else.\n"
    "    Line 1 is not shown yet: the parser tests at #3 failed at 14:02.\n"
    "Keep the lexer as it is, and rerun the parser tests before anything else."
)
OWN = "Actually, rename the placeholder lexer before the parser tests run again."


def _row(**extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict(runtime_sessions.base_session("claude", SHORT, "billing"))
    row.update(
        {
            "project": "billing",
            "state": "working",
            "active": True,
            "last_activity": NOW,
            "first_prompt": FIRST,
            "first_prompt_at": START.timestamp() + 5,
        }
    )
    row.update(extra)
    return row


def _paste(session: Transcript, text: str) -> float:
    """A user record whose content is the plain string Claude Code writes for a paste."""
    row = session._entry("user", [])
    row["message"]["content"] = text
    return START.timestamp() + session.seconds


class NormalisationTest(unittest.TestCase):
    """The owner's rule, applied to both sides before hashing."""

    def test_the_capture_cases_digest_alike(self) -> None:
        self.assertEqual(copies.digest(COPIED), copies.digest(STORED))

    def test_each_rewrite_the_input_box_makes_is_undone(self) -> None:
        cases = (
            ("CRLF", "first\r\nsecond", "first\nsecond"),
            ("lone CR", "first\rsecond", "first\nsecond"),
            ("tab", "stands\tagainst", "stands    against"),
            ("trailing whitespace", "short paste  \t\n\n", "short paste"),
            ("leading whitespace", "\n  indented", "indented"),
        )
        for label, pasted, stored in cases:
            with self.subTest(case=label):
                self.assertEqual(copies.digest(pasted), copies.digest(stored))

    def test_an_edit_is_a_different_digest(self) -> None:
        self.assertNotEqual(copies.digest(STORED), copies.digest(STORED + " now"))
        self.assertNotEqual(copies.digest(STORED), copies.digest(STORED.replace("14:02", "14:03")))
        # A tab is four spaces, not one: a fixed width, as the capture measured.
        self.assertNotEqual(copies.digest("a\tb"), copies.digest("a b"))


class _Store(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        cwd = self.root / "work" / "billing"
        cwd.mkdir(parents=True)
        self.path = self.root / "claude" / "projects" / "-work-billing" / f"{SHORT}-full.jsonl"
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            store_root_overrides={"claude.projects": str(self.root / "claude" / "projects")},
        )
        self.state = build_runtime_state(self.config, started=NOW)
        patcher = mock.patch.object(observer.CodexGoalModel, "__call__", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.session = Transcript(cwd)
        self.session.prompt(FIRST)
        self.session.bash("pytest", "5 passed")
        self.session.save(self.path)

    def position(self) -> tuple[int, int]:
        """Where the transcript ends now: the boundary a copy made now matches after."""
        info = os.stat(self.path)
        return (info.st_ino, info.st_size)

    def register(self, text: str = COPIED, *, now: float, sid: str = SHORT) -> str:
        return copies.register(self.config, "claude", sid, text, now=now, position=self.position())

    def facts(self) -> list[dict[str, Any]]:
        context = project_context.collect(
            self.config, self.state, [_row()], "billing", now=NOW, focus=("claude", SHORT)
        )
        return list(context["semantic"]["facts"])

    def user_facts(self) -> list[dict[str, Any]]:
        return [fact for fact in self.facts() if fact.get("type") == "user_message"]

    def matched(self) -> tuple[dict[str, Any], ...]:
        return copies.matched(self.config, self.state, "claude", SHORT)


class CopyStoreTest(_Store):
    def test_a_full_9700_character_correction_is_accepted(self) -> None:
        for char in ("x", "界", "😀"):
            with self.subTest(char=char):
                self.assertTrue(self.register(char * 9700, now=100.0))

    def test_a_copy_is_stored_once_and_a_second_registration_changes_nothing(self) -> None:
        self.assertEqual(copies.OUTCOME_STORED, self.register(now=100.0))
        self.assertEqual(copies.OUTCOME_UNCHANGED, self.register(now=200.0))
        held = copies.load(self.config)[("claude", SHORT)].copies
        self.assertEqual(1, len(held))
        # The first copy's time stands: a second registration cannot move where it matches from.
        self.assertEqual(100.0, held[0]["copied_at"])
        self.assertEqual(copies.digest(COPIED), held[0]["digest"])

    def test_eight_digests_per_session_and_the_oldest_goes(self) -> None:
        for n in range(10):
            self.register(f"Correction number {n} for the placeholder parser.", now=100.0 + n)
        held = copies.load(self.config)[("claude", SHORT)].copies
        self.assertEqual(copies.COPIES_PER_SESSION, len(held))
        self.assertEqual(8, copies.COPIES_PER_SESSION)
        self.assertEqual([102.0 + n for n in range(8)], [copy["copied_at"] for copy in held])
        on_disk = json.loads(Path(copies.store_path(self.config)).read_text(encoding="utf-8"))
        self.assertEqual(8, len(on_disk["entries"][0]["copies"]))

    def test_the_store_holds_digests_only_and_is_owner_only(self) -> None:
        self.register(now=100.0)
        path = Path(copies.store_path(self.config))
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("placeholder parser", raw)
        self.assertNotIn("Steer back", raw)
        if sys.platform != "win32":
            self.assertEqual(0o600, stat.S_IMODE(os.stat(path).st_mode))

    def test_what_cannot_be_a_copied_correction_is_refused_and_writes_nothing(self) -> None:
        cases: tuple[tuple[str, Any, str], ...] = (
            ("empty", "   \n\t ", "claude"),
            ("not a string", ["x"], "claude"),
            ("over 2,000 characters", "x" * (copies.CORRECTION_CAP_CHARS + 1), "claude"),
            ("a harness whose messages are not read", COPIED, "pi"),
        )
        for label, text, harness in cases:
            with self.subTest(case=label):
                self.assertEqual(
                    copies.OUTCOME_REFUSED,
                    copies.register(
                        self.config, harness, SHORT, text, now=100.0, position=self.position()
                    ),
                )
        self.assertEqual(
            copies.OUTCOME_REFUSED,
            copies.register(self.config, "claude", SHORT, COPIED, now=100.0, position=None),
        )
        self.assertFalse(os.path.lexists(copies.store_path(self.config)))
        self.assertEqual(
            copies.OUTCOME_STORED,
            self.register("x" * copies.CORRECTION_CAP_CHARS, now=100.0),
        )

    def test_nothing_is_stored_with_annotations_off(self) -> None:
        self.config = dataclasses.replace(self.config, annotations_enabled=False)
        self.assertEqual(copies.OUTCOME_REFUSED, self.register(now=100.0))
        self.assertFalse(os.path.lexists(copies.store_path(self.config)))

    def test_the_store_keeps_the_sessions_copied_from_most_recently(self) -> None:
        self.config = dataclasses.replace(self.config, annotation_max_sessions=2)
        for n, sid in enumerate(("first", "second", "third")):
            copies.register(self.config, "claude", sid, COPIED, now=100.0 + n, position=(1, 0))
        self.assertEqual({("claude", "second"), ("claude", "third")}, set(copies.load(self.config)))

    def test_a_copy_waits_for_another_dashboards_lock_and_stores_nothing_without_it(self) -> None:
        lock = copies.store_path(self.config) + ".lock"
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        holder = subprocess.Popen(
            [sys.executable, "-c", _HOLD_LOCK, str(Path(copies.__file__).parents[1]), lock, "hold"],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(holder.wait, 10)
        self.addCleanup(holder.kill)
        assert holder.stdout is not None
        self.assertEqual(runtime_io.LOCK_HELD, holder.stdout.readline().strip())
        with mock.patch.object(copies, "_LOCK_WAIT_SECONDS", 0.2):
            self.assertEqual(copies.OUTCOME_UNWRITABLE, self.register(now=100.0))
        self.assertFalse(os.path.lexists(copies.store_path(self.config)))

    def test_the_store_at_its_full_bound_reads_back_whole(self) -> None:
        # Every value at its widest: a sid at the key cap, times with every digit a float prints,
        # and the largest inode and offset a 64-bit stat gives. A store over the read cap reads
        # back as nothing, which un-marks every recognised paste at once (DRC-4678 verify, V1).
        sessions = self.config.annotation_max_sessions
        moment = 1790000000.1234567
        held = {
            ("codex", f"{n:0{copies._KEY_CAP_CHARS}d}"): copies.Held(
                tuple(
                    {
                        "digest": f"{n:032x}{c:032x}",
                        "folded": "0" * 64,
                        "copied_at": moment + c,
                        "ino": 2**64 - 1,
                        "offset": 2**63 - 1,
                        "prefix_count": 2**63 - 1,
                        "prefix_digest": "1" * 64,
                    }
                    for c in range(copies.COPIES_PER_SESSION)
                ),
                tuple(
                    {
                        "fact_id": f"fact:{n:08x}{m:08x}",
                        "at": moment + m,
                        "copied_at": moment + m,
                        "record_digest": "2" * 64,
                    }
                    for m in range(copies.MATCHES_PER_SESSION)
                ),
            )
            for n in range(sessions)
        }
        self.assertEqual(copies.OUTCOME_STORED, copies._write(self.config, held, print))
        size = os.path.getsize(copies.store_path(self.config))
        # A quarter of the cap spare, so a field added later has room before this reads empty.
        self.assertLess(size, copies._READ_CAP_BYTES * 3 // 4)
        loaded = copies.load(self.config)
        self.assertEqual(sessions, len(loaded))
        self.assertEqual(held, loaded)

    def test_forget_deletes_the_store(self) -> None:
        self.assertFalse(copies.forget(self.config))
        self.register(now=100.0)
        self.assertTrue(copies.forget(self.config))
        self.assertEqual({}, copies.load(self.config))


class MatchingTest(_Store):
    def test_a_reader_restarting_a_long_session_does_not_adopt_a_copied_correction_from_the_opening_range(
        self,
    ) -> None:
        copied_position = self.position()
        copied_at = START.timestamp() + self.session.seconds + 1
        pasted_at = _paste(self.session, STORED)
        self.session.save(self.path)
        padding = json.dumps({"type": "progress", "data": "x" * (1024 * 1024)}).encode() + b"\n"
        for size in (40, 100):
            with self.subTest(size=size):
                self.session.save(self.path)
                copies.forget(self.config)
                copies.register(
                    self.config, "claude", SHORT, COPIED, now=copied_at, position=copied_position
                )
                with self.path.open("ab") as handle:
                    for _ in range(size):
                        handle.write(padding)
                restarted = build_runtime_state(self.config, started=NOW)
                matches = copies.matched(self.config, restarted, "claude", SHORT)
                self.assertEqual([pasted_at], [entry["at"] for entry in matches])
                row = _row()
                copies.attach(self.config, restarted, [row])
                app = aggregate.Application(
                    self.config,
                    restarted,
                    (),
                    native_notifier=lambda _p: "",
                    popup_notifier=lambda _t, _b: None,
                    diagnostic_sink=lambda _m: None,
                    clock=lambda: NOW,
                )
                facts = http_api._prompt_facts(app, row, [])
                self.assertFalse(any(fact["at"] == pasted_at for fact in facts))

    """The collector half: each user message's digest from its raw text, before any clipping."""

    def test_an_exact_paste_after_the_copy_is_recognised_and_a_different_message_is_not(
        self,
    ) -> None:
        copied_at = START.timestamp() + self.session.seconds + 1
        self.register(now=copied_at)
        pasted_at = _paste(self.session, STORED)
        own_at = _paste(self.session, OWN)
        self.session.save(self.path)
        by_at = {float(fact["at"]): fact for fact in self.user_facts()}
        # The published summary is clipped at 112 characters; the digest was not.
        self.assertLessEqual(len(str(by_at[pasted_at]["summary"])), 112)
        self.assertGreater(len(STORED), 112)
        self.assertEqual(
            ({"fact_id": by_at[pasted_at]["fact_id"], "at": pasted_at},), self.matched()
        )
        self.assertNotIn(own_at, [entry["at"] for entry in self.matched()])

    def test_a_paste_before_the_copy_is_the_readers_own(self) -> None:
        _paste(self.session, STORED)
        self.session.save(self.path)
        self.register(now=START.timestamp() + self.session.seconds + 1)
        self.assertEqual((), self.matched())

    def test_a_digest_never_registered_matches_nothing(self) -> None:
        self.register("A different correction altogether.", now=START.timestamp())
        _paste(self.session, STORED)
        self.session.save(self.path)
        self.assertEqual((), self.matched())
        self.assertEqual((), copies.matched(self.config, self.state, "claude", "someone"))

    def test_a_digest_is_used_once_and_registering_it_again_matches_nothing_more(self) -> None:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        first = _paste(self.session, STORED)
        self.session.save(self.path)
        self.assertEqual(copies.OUTCOME_UNCHANGED, self.register(now=first + 1))
        second = _paste(self.session, STORED)
        self.session.save(self.path)
        self.assertEqual([first], [entry["at"] for entry in self.matched()])
        self.assertNotIn(second, [entry["at"] for entry in self.matched()])

    def test_an_edited_paste_is_the_readers_own_words(self) -> None:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        _paste(self.session, STORED + " now")
        _paste(self.session, "now.")
        self.session.save(self.path)
        self.assertEqual((), self.matched())

    def test_text_edited_in_compasss_box_before_copying_matches_what_was_copied(self) -> None:
        edited = COPIED.replace("rerun the parser tests", "rerun only the lexer tests")
        self.register(edited, now=START.timestamp() + self.session.seconds + 1)
        at = _paste(
            self.session, STORED.replace("rerun the parser tests", "rerun only the lexer tests")
        )
        self.session.save(self.path)
        self.assertEqual([at], [entry["at"] for entry in self.matched()])

    def test_a_long_paste_keeps_its_trailing_newlines_and_still_matches(self) -> None:
        # A collapsed paste keeps its own trailing whitespace (paste4678, case 9).
        self.register(now=START.timestamp() + self.session.seconds + 1)
        at = _paste(self.session, STORED + "\n\n")
        self.session.save(self.path)
        self.assertEqual([at], [entry["at"] for entry in self.matched()])

    def test_a_message_longer_than_the_bound_never_matches_its_prefix(self) -> None:
        text = "y" * copies.CORRECTION_CAP_CHARS
        self.register(text, now=START.timestamp() + self.session.seconds + 1)
        _paste(self.session, text + "z" * 9000)
        self.session.save(self.path)
        self.assertEqual((), self.matched())


class CodexDeliveryTest(unittest.TestCase):
    @contextlib.contextmanager
    def rollout(self) -> Any:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            config = build_runtime_config(
                environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
                platform_name="linux",
                os_name="posix",
                launcher_path=root / "server.py",
                store_root_overrides={"codex.sessions": str(sessions)},
            )
            sid = "019c3333-3333-7333-8333-333333333333"
            path = sessions / f"1970/01/01/rollout-{sid}.jsonl"
            path.parent.mkdir(parents=True)
            yield config, build_runtime_state(config, started=1000), sid, path

    @staticmethod
    def record(at: float, kind: str, **payload: Any) -> str:
        stamp = datetime.fromtimestamp(at, UTC).isoformat()
        return json.dumps({"timestamp": stamp, "type": kind, "payload": payload}) + "\n"

    def message(self, at: float, words: str) -> str:
        return self.record(
            at,
            "response_item",
            type="message",
            role="user",
            content=[{"type": "input_text", "text": words}],
        )

    def completed(self, at: float, words: str) -> str:
        return self.record(
            at,
            "event_msg",
            type="item_completed",
            item={
                "type": "UserMessage",
                "id": "item_1",
                "content": [{"type": "text", "text": words, "text_elements": []}],
            },
        )

    def test_same_inode_rewrite_cannot_reclassify_a_pre_copy_prompt(self) -> None:
        for warm in (False, True):
            with self.subTest(warm=warm), self.rollout() as (config, state, sid, path):
                meta = self.record(80, "session_meta", id=sid, cwd="/stats", source="cli")
                prior = self.message(170, STORED)
                path.write_text(meta + prior, encoding="utf-8")
                position = copies.transcript_position(config, state, "codex", sid)
                self.assertEqual(
                    "stored",
                    copies.register(
                        config,
                        "codex",
                        sid,
                        STORED,
                        now=180,
                        position=position,
                    ),
                )
                if warm:
                    self.assertEqual((), copies.matched(config, state, "codex", sid))
                extra = self.record(85, "turn_context", note="x" * (len(meta + prior) * 2))
                ino = path.stat().st_ino
                path.write_text(meta + extra + prior, encoding="utf-8")
                os.utime(path, (200, 200))
                self.assertEqual(ino, path.stat().st_ino)
                self.assertEqual((), copies.matched(config, state, "codex", sid))
                case = copy.deepcopy(BY_NAME["codex-later-direction-unsettled"])
                row = {**case["session"], "sid": sid, "project": "stats", "active": True}
                for fact in case["context"]["semantic"]["facts"]:
                    if fact.get("source_session"):
                        fact["source_session"]["sid"] = sid
                collected = project_context.collect(
                    config, state, [row], "stats", now=1000, focus=("codex", sid)
                )
                (person,) = (
                    fact
                    for fact in collected["semantic"]["facts"]
                    if fact["type"] == "user_message" and fact["at"] == 170
                )
                copies.attach(config, state, [row])
                self.assertEqual([], row["copied_prompts"])
                case["session"] = row
                case["context"]["semantic"]["facts"][1] = person
                case["context"] = copies.mark(case["context"], [row])
                self.assertEqual(
                    runtime_reading.AUTHOR_PERSON,
                    runtime_reading.author_of(case["context"]["semantic"]["facts"][1]),
                )
                self.assertEqual("cant-tell", view(case)["lines"][0]["state"])

    def test_shrinking_non_user_context_cannot_hide_a_later_paste(self) -> None:
        with self.rollout() as (config, state, sid, path):
            meta = self.record(80, "session_meta", id=sid, cwd="/stats", source="cli")
            first = self.message(90, FIRST)
            context = self.record(150, "turn_context", note="x" * 5000)
            path.write_text(meta + first + context, encoding="utf-8")
            position = copies.transcript_position(config, state, "codex", sid)
            self.assertEqual(
                "stored",
                copies.register(
                    config,
                    "codex",
                    sid,
                    STORED,
                    now=160,
                    position=position,
                ),
            )
            self.assertEqual((), copies.matched(config, state, "codex", sid))
            path.write_text(meta + first + self.message(170, STORED), encoding="utf-8")
            self.assertEqual(
                [170], [item["at"] for item in copies.matched(config, state, "codex", sid)]
            )

    def test_a_changed_pre_copy_user_record_leaves_the_boundary_unverified(self) -> None:
        with self.rollout() as (config, state, sid, path):
            meta = self.record(80, "session_meta", id=sid, cwd="/stats", source="cli")
            path.write_text(meta + self.message(90, FIRST), encoding="utf-8")
            position = copies.transcript_position(config, state, "codex", sid)
            self.assertEqual(
                "stored",
                copies.register(
                    config,
                    "codex",
                    sid,
                    STORED,
                    now=160,
                    position=position,
                ),
            )
            path.write_text(
                meta + self.message(90, OWN) + self.message(170, STORED), encoding="utf-8"
            )
            self.assertEqual((), copies.matched(config, state, "codex", sid))

    def test_a_legacy_codex_copy_without_prefix_proof_cannot_mark_a_paste(self) -> None:
        with self.rollout() as (config, state, sid, path):
            path.write_text(self.record(80, "session_meta", id=sid, source="cli"), encoding="utf-8")
            old_copy: copies.Copy = {
                "digest": copies.digest(STORED),
                "copied_at": 160.0,
                "ino": path.stat().st_ino,
                "offset": path.stat().st_size,
            }
            copies._write(config, {("codex", sid): copies.Held((old_copy,), ())}, self.fail)
            with path.open("a", encoding="utf-8") as output:
                output.write(self.message(170, STORED))
            self.assertEqual((), copies.matched(config, state, "codex", sid))

    def test_recognised_latest_prompt_is_never_a_goal_or_direction_floor(self) -> None:
        for delivery, last_at in (
            ("completion", 170.05),
            ("response-only", 170.0),
            ("first-and-latest", 170.05),
        ):
            with self.subTest(delivery=delivery), self.rollout() as (config, state, sid, path):
                opening = self.record(80, "session_meta", id=sid, cwd="/stats", source="cli")
                if delivery != "first-and-latest":
                    opening += self.record(85, "turn_context", note="x" * (2 << 20))
                    opening += self.message(90, FIRST)
                words = "Fix the queue and verify it using " + "the existing checks. " * 75
                path.write_text(opening, encoding="utf-8")
                position = copies.transcript_position(config, state, "codex", sid)
                self.assertEqual(
                    "stored",
                    copies.register(
                        config,
                        "codex",
                        sid,
                        words,
                        now=160,
                        position=position,
                    ),
                )
                with path.open("a", encoding="utf-8") as output:
                    output.write(self.message(170, words))
                    if delivery != "response-only":
                        output.write(self.completed(last_at, words))
                os.utime(path, (200, 200))

                def row_after_attach() -> dict[str, Any]:
                    (row,) = codex.collect(config, state, 200, 1, False)
                    copies.attach(config, state, [row])
                    return row

                row = row_after_attach()
                self.assertLess(len(row["title"]), len(words))
                self.assertEqual(last_at, row["prompt_at"])
                self.assertEqual(
                    ("", None), annotation_store.prompt_candidate(row, "latest-prompt")
                )
                self.assertTrue(runtime_reading.prompt_copied(row, "title"))
                if delivery == "first-and-latest":
                    self.assertTrue(runtime_reading.prompt_copied(row, "first_prompt"))
                else:
                    self.assertFalse(row["first_prompt"])
                self.assertEqual(
                    "refused",
                    annotation_store.adopt(
                        config,
                        state,
                        row,
                        source="latest-prompt",
                        expected_text=row["title"],
                        expected_at=last_at,
                        now=200,
                    ),
                )
                self.assertEqual((), annotation_store.load(config))
                self.assertIsNone(annotation_store.direction_floor(None, row))
                self.assertIsNone(drift_view.intent_draft({"annotate": True}, row, None))
                self.assertIsNone(terminal_drift.draft(row, {"annotate": True}))
                self.assertEqual(
                    ("Goal", ""),
                    terminal_sessions._goal(
                        row,
                        annotate=True,
                        unreadable=False,
                    ),
                )

                if delivery == "completion":
                    with path.open("a", encoding="utf-8") as output:
                        output.write(self.record(180, "turn_context", note="x" * 8200))
                    os.utime(path, (200, 200))
                    narrow = dataclasses.replace(
                        config, direction_scan_max_bytes=4096, tail_bytes=4096
                    )
                    reopened = build_runtime_state(narrow, started=200)
                    (persisted,) = codex.collect(narrow, reopened, 200, 1, False)
                    copies.attach(narrow, reopened, [persisted])
                    self.assertTrue(runtime_reading.prompt_copied(persisted, "title"))

                # This prompt can share the copied title and clock. Its exact response differs.
                typed = words + " Also check the queue worker."
                expected = row["title"]
                with path.open("a", encoding="utf-8") as output:
                    output.write(self.message(last_at, typed))
                os.utime(path, (201, 201))
                row = row_after_attach()
                self.assertFalse(runtime_reading.prompt_copied(row, "title"))
                self.assertEqual(
                    (expected, last_at), annotation_store.prompt_candidate(row, "latest-prompt")
                )
                self.assertEqual(
                    "stored",
                    annotation_store.adopt(
                        config,
                        state,
                        row,
                        source="latest-prompt",
                        expected_text=expected,
                        expected_at=last_at,
                        now=201,
                    ),
                )

    def test_warm_attach_indexes_codex_rollouts_once_for_completed_copies(self) -> None:
        with self.rollout() as (config, state, _, path):
            rows: list[dict[str, Any]] = []
            for index in range(3):
                sid = f"00000000-0000-4000-8000-{index:012d}"
                root = path.with_name(f"rollout-root-{sid}.jsonl")
                root.write_text(
                    self.record(80, "session_meta", id=sid, source="cli"), encoding="utf-8"
                )
                child = path.with_name(f"rollout-child-{sid}.jsonl")
                child.write_text(
                    self.record(
                        80,
                        "session_meta",
                        id=sid,
                        session_id="another-root",
                        thread_source="subagent",
                        source={"subagent": {"thread_spawn": {"parent_thread_id": "another-root"}}},
                    )
                    + self.message(175, STORED),
                    encoding="utf-8",
                )
                os.utime(child, (999, 999))
                position = copies.transcript_position(config, state, "codex", sid)
                self.assertEqual(
                    "stored",
                    copies.register(
                        config,
                        "codex",
                        sid,
                        STORED,
                        now=160,
                        position=position,
                    ),
                )
                with root.open("a", encoding="utf-8") as output:
                    output.write(self.message(170 + index, STORED))
                os.utime(root, (200, 200))
                rows.append(
                    {
                        "harness": "codex",
                        "sid": sid,
                        "title": transcripts.prompt_title(config, STORED),
                        "prompt_at": 170 + index,
                    }
                )
            copies.attach(config, state, rows)
            expected = [row["copied_prompts"] for row in rows]
            self.assertEqual([170, 171, 172], [found[0]["at"] for found in expected])
            self.assertTrue(all(found[0]["quoted_as"] == ["title"] for found in expected))
            self.assertFalse(any(entry.copies for entry in copies.load(config).values()))
            with mock.patch.object(
                transcripts, "codex_meta", wraps=transcripts.codex_meta
            ) as lookup:
                copies.attach(config, state, rows)
            self.assertEqual(expected, [row["copied_prompts"] for row in rows])
            self.assertLessEqual(lookup.call_count, 6)

    def test_captured_deliveries_keep_the_departure_and_match_the_collected_fact_id(self) -> None:
        capture_path = (
            SERVER_PATH.parents[3] / "docs/captures/codex/correction-delivery-0.172.0-macos.jsonl"
        )
        capture = [
            json.loads(line) for line in capture_path.read_text(encoding="utf-8").splitlines()
        ]
        short, long = [row["text"] for row in capture if row["event"] == "_correction_text"]
        for delivery, source, text in (
            ("exec resume argument", "exec", short),
            ("TUI mid-turn", "cli", short),
            ("TUI idle long paste", "cli", long),
            ("exec resume stdin", "exec", long),
        ):
            with self.subTest(delivery=delivery), tempfile.TemporaryDirectory() as tmp:
                self.check_delivery(Path(tmp), delivery, source, text)

    def test_codex_recognises_literal_paste_tags_in_a_correction_edited_before_copying(
        self,
    ) -> None:
        text = (
            'Back to my goal: Preserve the literal <pasted_content id="1">example</pasted_content>.'
        )
        with tempfile.TemporaryDirectory() as tmp:
            self.check_delivery(Path(tmp), "TUI mid-turn", "cli", text)

    def check_delivery(self, root: Path, delivery: str, source: str, text: str) -> None:
        case = copy.deepcopy(BY_NAME["codex-later-direction-unsettled"])
        row = case["session"]
        row["project"] = "stats"
        row["active"] = True
        sid = row["sid"]
        sessions = root / "sessions"
        path = sessions / "1970/01/01/rollout-stats.jsonl"
        path.parent.mkdir(parents=True)
        config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
            store_root_overrides={"codex.sessions": str(sessions)},
        )
        state = build_runtime_state(config, started=1000)

        def record(at: int, kind: str, **payload: Any) -> str:
            stamp = datetime.fromtimestamp(at, UTC).isoformat()
            return json.dumps({"timestamp": stamp, "type": kind, "payload": payload}) + "\n"

        def message(at: int, words: str) -> str:
            return record(
                at,
                "response_item",
                type="message",
                role="user",
                content=[{"type": "input_text", "text": words}],
            )

        # The resume and idle deliveries open a new task with no second session_meta.
        trigger = "exec" if source == "exec" else "user"
        mid_turn = delivery == "TUI mid-turn"
        opening = record(80, "session_meta", id=sid, cwd=str(root), source=source)
        opening += record(
            81, "event_msg", type="task_started", turn_id="first", turn_trigger=trigger
        )
        opening += message(90, "Fix the off-by-one bug in mean().")
        if not mid_turn:
            opening += record(155, "event_msg", type="task_complete", turn_id="first")
        path.write_text(opening, encoding="utf-8")
        position = copies.transcript_position(config, state, "codex", sid)
        self.assertIsNotNone(position)
        registered = copies.register(config, "codex", sid, text, now=160, position=position)
        with path.open("a", encoding="utf-8") as output:
            if not mid_turn:
                output.write(
                    record(
                        165, "event_msg", type="task_started", turn_id="next", turn_trigger=trigger
                    )
                )
            output.write(message(170, text))
            output.write(
                record(171, "event_msg", type="item_completed", item={"type": "UserMessage"})
            )
            output.write(
                record(
                    180, "event_msg", type="task_complete", turn_id="first" if mid_turn else "next"
                )
            )

        collected = project_context.collect(
            config, state, [row], "stats", now=1000, focus=("codex", sid)
        )
        (paste,) = (
            fact
            for fact in collected["semantic"]["facts"]
            if fact["type"] == "user_message" and fact["at"] == 170
        )
        case["context"]["semantic"]["facts"][1] = paste
        self.assertEqual("cant-tell", view(case)["lines"][0]["state"])
        self.assertEqual(copies.OUTCOME_STORED, registered)
        copies.attach(config, state, [row])
        self.assertEqual([paste["fact_id"]], [item["fact_id"] for item in row["copied_prompts"]])
        case["context"] = copies.mark(case["context"], [row])
        marked = case["context"]["semantic"]["facts"][1]
        self.assertEqual(runtime_reading.AUTHOR_DERIVED, runtime_reading.author_of(marked))
        self.assertEqual(["goal"], view(case)["departures"])
        self.assertEqual("departs", view(case)["lines"][0]["state"])


class _App(_Store):
    now = NOW

    def app(self, **row: Any) -> aggregate.Application:
        def collect(
            config: Any, state: Any, now: float, window_hours: float, show_all: bool
        ) -> list[dict[str, Any]]:
            del config, state, now, window_hours, show_all
            return [_row(**row)]

        spec = aggregate.HarnessSpec(
            key="claude", label="Claude", discover=lambda *_: True, collect=collect
        )
        return aggregate.Application(
            self.config,
            self.state,
            (spec,),
            native_notifier=lambda _p: "",
            popup_notifier=lambda _t, _b: None,
            diagnostic_sink=lambda _m: None,
            clock=lambda: self.now,
        )

    def pasted(self) -> tuple[float, float]:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        pasted_at = _paste(self.session, STORED)
        own_at = _paste(self.session, OWN)
        self.session.save(self.path)
        return pasted_at, own_at


class TreatedAsCompassAssistedTest(_App):
    """Adoption, rule 7 and DEC-16 read one mark, so the three stay one rule."""

    def test_the_row_publishes_the_recognised_message_and_every_row_carries_the_key(self) -> None:
        pasted_at, _ = self.pasted()
        rows = self.app().collect(show_all=True)["sessions"]
        self.assertEqual([pasted_at], [entry["at"] for entry in rows[0]["copied_prompts"]])
        self.assertEqual([], runtime_sessions.base_session("claude", "x", "p")["copied_prompts"])

    def test_the_facts_the_reading_reads_mark_it_derived_and_the_others_stay_yours(self) -> None:
        pasted_at, own_at = self.pasted()
        application = self.app()
        row = application.collect(show_all=True)["sessions"][0]
        facts = http_api._facts_of(http_api._session_context(application, row))
        authors = {
            float(fact["at"]): runtime_reading.author_of(fact)
            for fact in facts
            if fact.get("type") == "user_message"
        }
        self.assertEqual(runtime_reading.AUTHOR_DERIVED, authors[pasted_at])
        self.assertEqual(runtime_reading.AUTHOR_PERSON, authors[own_at])

    def test_the_window_for_typed_words_does_not_open_at_a_copied_correction(self) -> None:
        pasted_at, own_at = self.pasted()
        application = self.app()
        row = application.collect(show_all=True)["sessions"][0]
        facts = http_api._facts_of(http_api._session_context(application, row))
        # Saved between the paste and the reader's own message: the window opens at the reader's
        # previous message, never at the paste.
        start = runtime_reading.typed_window_start(facts, "claude", SHORT, pasted_at + 1)
        self.assertLess(start, pasted_at)
        self.assertEqual(own_at, runtime_reading.typed_window_start(facts, "claude", SHORT, NOW))

    def test_a_copied_correction_is_never_adopted_or_the_floor_for_a_later_direction(
        self,
    ) -> None:
        pasted_at, _ = self.pasted()
        latest = {"label": "asked", "text": STORED[:80], "at": pasted_at}
        row = self.app(first_prompt="", first_prompt_at=None, instruction=latest).collect(
            show_all=True
        )["sessions"][0]
        self.assertEqual(("", None), annotation_store.prompt_candidate(row, "latest-prompt"))
        self.assertIsNone(annotation_store.direction_floor(None, row))
        # The same row with nothing copied adopts the latest prompt as before.
        plain = {**row, "copied_prompts": []}
        self.assertEqual(
            (STORED[:80], pasted_at), annotation_store.prompt_candidate(plain, "latest-prompt")
        )


LINE = STORED.split("\n", maxsplit=1)[0]
# Enough later transcript to push a message out of the shortened tail these tests read.
BULK = "x" * 1500


class DurableRecognitionTest(_App):
    """A recognised message stays recognised: the tail moving on, a clock stepping back, or a
    paste the tail never held does not change what it was (DRC-4678 review, matching F1)."""

    def setUp(self) -> None:
        super().setUp()
        self.config = dataclasses.replace(self.config, tail_bytes=8192)

    def push_out_of_the_tail(self) -> None:
        for _ in range(20):
            self.session.bash("cat build.log", BULK)
        self.session.save(self.path)
        self.assertNotIn(LINE, "".join(runtime_io.read_tail(self.config, str(self.path))))

    def test_a_recognised_paste_pushed_past_the_tail_stays_recognised_and_is_never_adopted(
        self,
    ) -> None:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        pasted_at = _paste(self.session, STORED)
        self.session.save(self.path)
        latest = {"label": "asked", "text": LINE, "at": pasted_at}
        app = self.app(first_prompt="", first_prompt_at=None, instruction=latest)
        before = app.collect(show_all=True)["sessions"][0]["copied_prompts"]
        self.assertEqual([pasted_at], [entry["at"] for entry in before])
        self.push_out_of_the_tail()
        self.state.snapshot.clear()
        row = app.collect(show_all=True)["sessions"][0]
        self.assertEqual(before, row["copied_prompts"])
        self.assertEqual(("", None), annotation_store.prompt_candidate(row, "latest-prompt"))
        self.assertIsNone(annotation_store.direction_floor(None, row))
        # Whatever still publishes the message, history included, publishes it as Compass's.
        fact = {
            "type": "user_message",
            "fact_id": before[0]["fact_id"],
            "at": pasted_at,
            "source_session": {"harness": "claude", "sid": SHORT},
        }
        marked = copies.mark({"semantic": {"facts": [fact]}}, [row])
        self.assertIs(True, marked["semantic"]["facts"][0].get("copied"))

    def test_a_paste_the_tail_never_held_is_recognised(self) -> None:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        pasted_at = _paste(self.session, STORED)
        self.push_out_of_the_tail()
        self.assertEqual([pasted_at], [entry["at"] for entry in self.matched()])

    def test_a_clock_stepped_back_never_marks_a_message_written_before_the_copy(self) -> None:
        typed_at = _paste(self.session, STORED)
        self.session.save(self.path)
        # The copy's clock reads earlier than the message already in the transcript.
        self.register(now=typed_at - 600)
        self.assertEqual((), self.matched())

    def test_a_paste_after_the_copy_is_recognised_though_the_clock_stepped_back(self) -> None:
        self.register(now=START.timestamp() + 86400)
        pasted_at = _paste(self.session, STORED)
        self.session.save(self.path)
        self.assertEqual([pasted_at], [entry["at"] for entry in self.matched()])

    def test_dropping_the_oldest_waiting_copy_never_unmarks_a_recognised_message(self) -> None:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        pasted_at = _paste(self.session, STORED)
        self.session.save(self.path)
        self.assertEqual([pasted_at], [entry["at"] for entry in self.matched()])
        for n in range(copies.COPIES_PER_SESSION):
            self.register(f"Probe number {n} for the placeholder parser.", now=NOW + n)
        self.assertEqual([pasted_at], [entry["at"] for entry in self.matched()])
        held = copies.load(self.config)[("claude", SHORT)]
        self.assertEqual(copies.COPIES_PER_SESSION, len(held.copies))
        self.assertEqual([pasted_at], [match["at"] for match in held.matches])

    def test_recognised_messages_are_bounded_per_session_and_the_oldest_goes(self) -> None:
        self.assertEqual(32, copies.MATCHES_PER_SESSION)
        pasted: list[float] = []
        for n in range(copies.MATCHES_PER_SESSION + 1):
            text = f"Correction {n}: rerun the placeholder parser tests."
            self.register(text, now=START.timestamp() + self.session.seconds + 1)
            pasted.append(_paste(self.session, text))
            self.session.save(self.path)
            self.matched()
        self.assertEqual(pasted[1:], [entry["at"] for entry in self.matched()])
        on_disk = json.loads(Path(copies.store_path(self.config)).read_text(encoding="utf-8"))
        self.assertEqual(copies.MATCHES_PER_SESSION, len(on_disk["entries"][0]["matches"]))
        self.assertNotIn("rerun the placeholder", json.dumps(on_disk))


class AdoptionByFactIdTest(_App):
    """Adoption refuses the copied message itself, never a typed one that shares its time
    (DRC-4678 review, Codex 1)."""

    def shared_moment(self) -> tuple[float, float]:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        pasted_at = _paste(self.session, STORED)
        self.session.seconds -= 5
        own_at = _paste(self.session, OWN)
        self.session.save(self.path)
        self.assertEqual(pasted_at, own_at)
        return pasted_at, own_at

    def row(self, text: str, at: float) -> dict[str, Any]:
        latest = {"label": "asked", "text": text, "at": at}
        app = self.app(first_prompt="", first_prompt_at=None, instruction=latest)
        row: dict[str, Any] = app.collect(show_all=True)["sessions"][0]
        return row

    def test_a_typed_prompt_sharing_a_pasted_corrections_time_is_still_adoptable(self) -> None:
        pasted_at, own_at = self.shared_moment()
        row = self.row(OWN, own_at)
        self.assertEqual([pasted_at], [entry["at"] for entry in row["copied_prompts"]])
        self.assertEqual([], row["copied_prompts"][0]["quoted_as"])
        self.assertEqual((OWN, own_at), annotation_store.prompt_candidate(row, "latest-prompt"))

    def test_the_pasted_correction_at_that_time_is_still_refused(self) -> None:
        pasted_at, _ = self.shared_moment()
        row = self.row(LINE, pasted_at)
        self.assertEqual(["instruction"], row["copied_prompts"][0]["quoted_as"])
        self.assertEqual(("", None), annotation_store.prompt_candidate(row, "latest-prompt"))

    def test_a_line_no_message_explains_falls_back_to_refusing_by_time(self) -> None:
        pasted_at, _ = self.shared_moment()
        row = self.row("A line no message in the transcript renders to.", pasted_at)
        self.assertEqual(("", None), annotation_store.prompt_candidate(row, "latest-prompt"))


class FirstPromptTest(_App):
    """The first-prompt arm is reachable only where the transcript held no user message when the
    copy was made; there, a pasted first prompt is refused as the latest one is."""

    def test_a_pasted_first_prompt_is_never_adopted(self) -> None:
        self.session = Transcript(self.root / "work" / "billing")
        self.path.write_bytes(b"")
        self.register(now=START.timestamp())
        pasted_at = _paste(self.session, STORED)
        self.session.save(self.path)
        row = self.app(first_prompt=LINE, first_prompt_at=pasted_at).collect(show_all=True)[
            "sessions"
        ][0]
        self.assertEqual(["first_prompt"], row["copied_prompts"][0]["quoted_as"])
        self.assertEqual(("", None), annotation_store.prompt_candidate(row, "first-prompt"))
        plain = {**row, "copied_prompts": []}
        self.assertEqual(
            (LINE, pasted_at), annotation_store.prompt_candidate(plain, "first-prompt")
        )


class MarkTest(unittest.TestCase):
    def test_marking_one_session_never_marks_another(self) -> None:
        def fact(sid: str) -> dict[str, Any]:
            return {
                "type": "user_message",
                "fact_id": "fact:0123456789abcdef",
                "source_session": {"harness": "claude", "sid": sid},
            }

        copied = [{"fact_id": "fact:0123456789abcdef", "at": 1.0}]
        rows: list[dict[str, Any]] = [
            {"harness": "claude", "sid": "one", "copied_prompts": copied},
            {"harness": "claude", "sid": "two", "copied_prompts": []},
        ]
        marked = copies.mark({"semantic": {"facts": [fact("one"), fact("two")]}}, rows)
        flags = [item.get("copied") for item in marked["semantic"]["facts"]]
        self.assertEqual([True, None], flags)


class CopiedRouteTest(_App):
    """`POST /api/correction/copied` over a real socket."""

    ROUTE = "/api/correction/copied"

    @contextlib.contextmanager
    def serving(self) -> Any:
        httpd = make_server(application=self.app())
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def post(
        port: int,
        payload: Any,
        *,
        headers: dict[str, str] | None = None,
        declared: str | None = None,
        path: str = ROUTE,
    ) -> tuple[int, dict[str, Any]]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            if declared is None:
                conn.request(
                    "POST",
                    path,
                    body=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json", **(headers or {})},
                )
            else:
                conn.putrequest("POST", path)
                conn.putheader("Content-Length", declared)
                conn.endheaders()
            response = conn.getresponse()
            body = response.read()
        finally:
            conn.close()
        try:
            return response.status, json.loads(body)
        except ValueError:
            return response.status, {}

    def body(self, **over: Any) -> dict[str, Any]:
        return {"harness": "claude", "sid": SHORT, "text": COPIED, **over}

    def test_a_copy_through_the_route_recognises_the_paste_that_follows(self) -> None:
        with self.serving() as port:
            status, answer = self.post(port, self.body())
        self.assertEqual((200, {"ok": True}), (status, answer))
        self.assertEqual(NOW, copies.load(self.config)[("claude", SHORT)].copies[0]["copied_at"])

    def test_a_correction_at_the_cap_in_four_byte_characters_registers(self) -> None:
        # Escaped by `json.dumps` as surrogate pairs, the widest JSON spells a character: 12 bytes
        # each, four times the old shared body bound.
        text = "\U0001f600" * copies.CORRECTION_CAP_CHARS
        for wide in (text, "中" * copies.CORRECTION_CAP_CHARS):
            with self.subTest(first=wide[0]), self.serving() as port:
                self.assertEqual((200, {"ok": True}), self.post(port, self.body(text=wide)))
        self.assertEqual(2, len(copies.load(self.config)[("claude", SHORT)].copies))

    def test_the_body_bound_is_derived_from_the_cap(self) -> None:
        widest = json.dumps(
            {
                "harness": "\U0001f600" * 64,
                "sid": "\U0001f600" * 64,
                "text": "\U0001f600" * copies.CORRECTION_CAP_CHARS,
            }
        ).encode()
        self.assertLessEqual(len(widest), copies.COPY_BODY_CAP_BYTES)
        self.assertEqual(
            12 * (copies.CORRECTION_CAP_CHARS + 2 * 64) + 256, copies.COPY_BODY_CAP_BYTES
        )

    def test_a_second_registration_answers_the_same_body_and_stores_nothing_new(self) -> None:
        with self.serving() as port:
            self.post(port, self.body())
            status, answer = self.post(port, self.body())
        self.assertEqual((200, {"ok": True}), (status, answer))
        self.assertEqual(1, len(copies.load(self.config)[("claude", SHORT)].copies))

    def test_an_unknown_session_answers_one_body_and_stores_nothing(self) -> None:
        with self.serving() as port:
            unknown = self.post(port, self.body(sid="unknown-session"))
            other = self.post(port, self.body(harness="codex"))
        self.assertEqual((200, {"ok": True}), unknown)
        self.assertEqual((200, {"ok": True}), other)
        self.assertFalse(os.path.lexists(copies.store_path(self.config)))

    def test_every_accepted_registration_answers_one_body(self) -> None:
        with self.serving() as port:
            answers = {
                self.post(port, self.body())[1].__repr__(),
                self.post(port, self.body())[1].__repr__(),
                self.post(port, self.body(text="A new text."))[1].__repr__(),
                self.post(port, self.body(sid="unknown-session"))[1].__repr__(),
                self.post(port, self.body(harness="codex"))[1].__repr__(),
            }
        self.assertEqual({repr({"ok": True})}, answers)

    def test_a_forged_cross_origin_copy_is_refused_and_stores_nothing(self) -> None:
        cases = (
            ("cross-site origin", {"Origin": "http://evil.example"}),
            ("another local port", {"Origin": "http://127.0.0.1:1"}),
            ("rebound host", {"Host": "evil.example"}),
            ("cross-site fetch", {"Sec-Fetch-Site": "cross-site"}),
            ("same-site fetch", {"Sec-Fetch-Site": "same-site"}),
            ("document navigation", {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}),
        )
        with self.serving() as port:
            for label, headers in cases:
                with self.subTest(shape=label):
                    status, answer = self.post(port, self.body(), headers=headers)
                    self.assertEqual(403, status)
                    self.assertNotIn("registered", answer)
            self.assertEqual(
                413,
                self.post(port, None, declared=str(copies.COPY_BODY_CAP_BYTES + 1))[0],
            )
            for bad in (
                self.body(text=["x"]),
                self.body(text=""),
                self.body(text="x" * (copies.CORRECTION_CAP_CHARS + 1)),
                self.body(sid=7),
                {"harness": "claude"},
            ):
                with self.subTest(body=str(bad)[:40]):
                    self.assertEqual(400, self.post(port, bad)[0])
        self.assertFalse(os.path.lexists(copies.store_path(self.config)))

    def test_a_body_that_is_not_an_object_is_refused(self) -> None:
        with self.serving() as port:
            for bad in ([1, 2], "x", [self.body()]):
                with self.subTest(body=str(bad)[:40]):
                    self.assertEqual(400, self.post(port, bad)[0])
        self.assertFalse(os.path.lexists(copies.store_path(self.config)))

    def test_a_store_that_cannot_be_written_answers_503(self) -> None:
        # A directory where the store's file belongs: the rename over it fails.
        os.makedirs(copies.store_path(self.config))
        with self.serving() as port:
            self.assertEqual((503, {"ok": False}), self.post(port, self.body()))

    def test_the_copy_is_timed_when_it_arrives_not_after_the_board_is_collected(self) -> None:
        arrived = self.now
        looked_up = http_api._RequestHandler._session_row

        def slow(handler: Any, harness: str, sid: str) -> Any:
            self.now = arrived + 60
            return looked_up(handler, harness, sid)

        with (
            mock.patch.object(http_api._RequestHandler, "_session_row", slow),
            self.serving() as port,
        ):
            self.post(port, self.body())
        self.assertEqual(
            arrived, copies.load(self.config)[("claude", SHORT)].copies[0]["copied_at"]
        )

    def test_the_transcript_is_measured_when_the_copy_arrives(self) -> None:
        # A message written while the lookup collects the board is past the copy.
        self.now = START.timestamp() + self.session.seconds + 1
        looked_up = http_api._RequestHandler._session_row
        pasted: list[float] = []

        def paste_meanwhile(handler: Any, harness: str, sid: str) -> Any:
            pasted.append(_paste(self.session, STORED))
            self.session.save(self.path)
            return looked_up(handler, harness, sid)

        with (
            mock.patch.object(http_api._RequestHandler, "_session_row", paste_meanwhile),
            self.serving() as port,
        ):
            self.post(port, self.body())
        self.assertEqual(pasted, [entry["at"] for entry in self.matched()])

    def test_the_route_answers_503_with_annotations_off(self) -> None:
        self.config = dataclasses.replace(self.config, annotations_enabled=False)
        with self.serving() as port:
            self.assertEqual(503, self.post(port, self.body())[0])

    def test_the_project_context_marks_the_recognised_message_copied(self) -> None:
        self.now = START.timestamp() + self.session.seconds + 1
        with self.serving() as port:
            self.post(port, self.body())
            pasted_at = _paste(self.session, STORED)
            own_at = _paste(self.session, OWN)
            self.session.save(self.path)
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", f"/api/project-context?project=billing&session=claude:{SHORT}")
            context = json.loads(conn.getresponse().read())
            conn.close()
        marks = {
            float(fact["at"]): fact.get("copied")
            for fact in context["semantic"]["facts"]
            if fact.get("type") == "user_message"
        }
        self.assertIs(True, marks[pasted_at])
        self.assertIsNone(marks[own_at])

    def test_a_recognised_message_cannot_be_opened_as_a_later_direction(self) -> None:
        self.now = START.timestamp() + self.session.seconds + 1
        with self.serving() as port:
            self.post(port, self.body())
            pasted_at = _paste(self.session, STORED)
            own_at = _paste(self.session, OWN)
            self.session.save(self.path)
            by_at = {float(fact["at"]): str(fact["fact_id"]) for fact in self.user_facts()}
            pasted = self.post(
                port,
                {"harness": "claude", "sid": SHORT, "fact_id": by_at[pasted_at]},
                path="/api/direction",
            )
            own = self.post(
                port,
                {"harness": "claude", "sid": SHORT, "fact_id": by_at[own_at]},
                path="/api/direction",
            )
        self.assertEqual((200, False), (pasted[0], pasted[1]["ok"]))
        self.assertEqual((200, True, OWN), (own[0], own[1]["ok"], own[1]["text"]))

    def test_a_paste_written_during_the_registration_never_shows_as_the_readers_words(
        self,
    ) -> None:
        # A paste landing after the transcript's end is read and before the copy is stored is in
        # the lookup's own collection, unrecognised; that board must not be served afterwards
        # (DRC-4678 verify, V2: a paste 2 to 10 ms after the press showed as the reader's).
        self.now = START.timestamp() + self.session.seconds + 1
        real = copies.transcript_position
        pasted: list[float] = []

        def position_then_paste(*args: Any) -> copies._Position | None:
            found = real(*args)
            pasted.append(_paste(self.session, STORED))
            self.session.save(self.path)
            return found

        with (
            mock.patch.object(copies, "transcript_position", position_then_paste),
            self.serving() as port,
        ):
            self.assertEqual((200, {"ok": True}), self.post(port, self.body()))
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            # The all-sessions view, which is the board the lookup collected and memoised.
            conn.request("GET", "/api/data?all=1")
            data = json.loads(conn.getresponse().read())
            conn.close()
        rows = [row for row in data["sessions"] if row.get("sid") == SHORT]
        self.assertEqual(pasted, [entry["at"] for entry in rows[0]["copied_prompts"]])

    def test_no_copied_text_reaches_the_payload(self) -> None:
        with self.serving() as port:
            self.post(port, self.body())
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/api/data")
            data = conn.getresponse().read().decode("utf-8")
            conn.close()
        self.assertNotIn("rerun the parser tests", data)


class ForgetTest(unittest.TestCase):
    """`--forget` clears the digests: the machine's memory of an act, holding no text."""

    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.environ = isolated_environment(state.name, home.name)
        self.config = build_runtime_config(
            environ=self.environ,
            platform_name="linux",
            os_name="posix",
            launcher_path=Path(home.name) / "server.py",
        )

    def said(self, argv: list[str]) -> tuple[int, str]:
        with no_instance(), mock.patch.object(runtime_io, "diag") as diag:
            code = run_one_shot_cli(argv, self.environ)
        return code, " ".join(str(call.args[0]) for call in diag.call_args_list)

    def test_forget_deletes_the_copied_correction_store_and_says_so(self) -> None:
        copies.register(self.config, "claude", SHORT, COPIED, now=100.0, position=(1, 0))
        path = copies.store_path(self.config)
        self.assertTrue(os.path.exists(path))
        code, said = self.said(["--forget"])
        self.assertEqual(0, code)
        self.assertFalse(os.path.exists(path))
        self.assertIn(f"deleted {path}", said)
        _, again = self.said(["--forget"])
        self.assertIn(f"no copied-correction store at {path}", again)


if __name__ == "__main__":
    unittest.main()
