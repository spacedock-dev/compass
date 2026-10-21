"""The annotation store: what the reader typed a session should achieve.

DRC-4508. These tests are the acceptance criteria the issue can actually hold
this store to. The two it cannot are named in the module docstring of
`annotations` and in the pull request, not silently skipped here.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import aggregate, cli, departures, project_context, unasked
from compass_runtime import annotations as annotation_store
from compass_runtime import observer as runtime_observer
from compass_runtime import reading as runtime_reading
from compass_runtime.config import RuntimeConfig, build_runtime_config
from compass_runtime.state import build_runtime_state

from .support import SERVER_PATH, make_runtime


class AnnotationStoreTest(unittest.TestCase):
    NOW = 1_800_000_000.0

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.harness_store = self.root / "harness-own-store"
        self.harness_store.mkdir()
        self.config = self._config()
        self.state = build_runtime_state(self.config, started=self.NOW)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _config(self, **overrides: Any) -> RuntimeConfig:
        return build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            store_root_overrides={"pi.sessions": str(self.harness_store)},
            **overrides,
        )

    # --- what the reader typed comes back ---------------------------------

    def test_an_annotation_survives_a_restart_and_writes_only_to_our_own_store(self) -> None:
        """Given a typed goal, when the process restarts, it is still there.

        The write-destination half of the same criterion: a harness's own store
        is a place Compass reads and never writes, so the assertion is that the
        fixture's harness root is untouched rather than that ours was written.
        """
        before = sorted(os.listdir(self.harness_store))

        annotation_store.annotate(
            self.config, self.state, "pi", "sess-1", goal="Ship the cockpit", now=self.NOW
        )

        # A second state object is this process restarted: nothing cached.
        restarted = build_runtime_state(self.config, started=self.NOW + 10)
        entry = annotation_store.find(
            annotation_store.active(self.config, restarted), "pi", "sess-1"
        )

        assert entry is not None
        self.assertEqual("Ship the cockpit", entry["revisions"][-1]["goal"])
        self.assertEqual(before, sorted(os.listdir(self.harness_store)))
        self.assertTrue(annotation_store.store_path(self.config).startswith(str(self.root)))

    def test_a_typed_line_break_is_stored_as_one_space(self) -> None:
        """The product call, recorded where it binds: these fields are one line.

        DRC-4533 asked whether they are single-line or multi-line. Single, and
        the reason is not layout. Relaxing the control-character strip for these
        two fields would reopen a closed credential hole: the scrub is what
        stops a pasted PEM body surviving, which `test_records` holds shut. So
        the store keeps collapsing, and the box collapses too, so the reader
        watches it happen rather than finding it afterwards.
        """
        annotation_store.annotate(
            self.config,
            self.state,
            "pi",
            "sess-1",
            goal="ship it\n\nand the doc",
            output="a PR\tgreen CI",
            now=self.NOW,
        )

        entry = annotation_store.find(
            annotation_store.active(self.config, self.state), "pi", "sess-1"
        )
        assert entry is not None
        revision = entry["revisions"][-1]
        self.assertEqual("ship it and the doc", revision["goal"])
        self.assertEqual("a PR green CI", revision["lines"][0]["text"])
        for text in (revision["goal"], revision["lines"][0]["text"]):
            with self.subTest(text=text):
                self.assertNotIn("\n", text)
                self.assertNotIn("\t", text)

    def test_activity_after_the_annotation_does_not_erase_it(self) -> None:
        """The deliberate difference from `dismissals`, which lapses on activity.

        A dismissal says "I have handled this", so later movement makes the row
        news again. An annotation says "this is what I asked for", which later
        movement does not answer. There is no watermark to compare against, and
        this test is what stops one being added by analogy.
        """
        annotation_store.annotate(
            self.config, self.state, "pi", "sess-1", goal="Ship the cockpit", now=self.NOW
        )
        entries = annotation_store.active(self.config, self.state)

        # Asserted on the PUBLISHED ROW, far past any plausible watermark,
        # because that is where a lapse would be observable. A predicate in the
        # store used to stand here and took an activity argument it ignored, so
        # adding the lapse to the binding left this test green; it is deleted
        # and this is what replaces it.
        rows: list[dict[str, object]] = [
            {
                "harness": "pi",
                "sid": "sess-1",
                "state": "working",
                "last_activity": self.NOW + 1_000_000,
            }
        ]
        aggregate._attach_annotations(rows, entries)

        self.assertEqual("Ship the cockpit", rows[0]["annotation_goal"])
        self.assertEqual("", rows[0]["annotation_goal_why"])

    # --- revisions ---------------------------------------------------------

    def test_each_save_appends_a_numbered_revision_and_mutates_none(self) -> None:
        """An assessment names the revision it read, so a revision is immutable.

        Editing in place would silently re-point every assessment that cited
        revision 1 at text it never saw.
        """
        annotation_store.annotate(self.config, self.state, "pi", "s", goal="First", now=self.NOW)
        annotation_store.annotate(
            self.config, self.state, "pi", "s", goal="Second", now=self.NOW + 5
        )

        entry = annotation_store.find(annotation_store.active(self.config, self.state), "pi", "s")
        assert entry is not None
        revisions = entry["revisions"]
        self.assertEqual([1, 2], [rev["n"] for rev in revisions])
        self.assertEqual("First", revisions[0]["goal"])
        self.assertEqual("Second", revisions[1]["goal"])
        self.assertEqual(self.NOW, revisions[0]["at"])

    def test_the_two_fields_are_optional_and_independent(self) -> None:
        """Either alone is a real annotation, and the absent one says why."""
        annotation_store.annotate(
            self.config, self.state, "pi", "goal-only", goal="G", now=self.NOW
        )
        annotation_store.annotate(
            self.config, self.state, "pi", "out-only", output="O", now=self.NOW
        )

        entries = annotation_store.active(self.config, self.state)
        goal_only = annotation_store.published(annotation_store.find(entries, "pi", "goal-only"))
        out_only = annotation_store.published(annotation_store.find(entries, "pi", "out-only"))

        self.assertEqual("G", goal_only["goal"])
        self.assertEqual("", goal_only["line_1"])
        self.assertTrue(goal_only["lines_why"])
        self.assertEqual("O", out_only["line_1"])
        self.assertTrue(out_only["goal_why"])

        # A session nobody annotated is an absence with a reason, never a blank
        # and never a placeholder.
        absent = annotation_store.published(None)
        self.assertEqual("", absent["goal"])
        self.assertTrue(absent["goal_why"])
        self.assertEqual(0, absent["revision_count"])

    def test_saving_one_field_does_not_destroy_the_other(self) -> None:
        """An omitted field is unchanged; an empty one is cleared.

        Collapsing the two would make a client that posts only the goal wipe the
        expected output beside it, which is the opposite of the independence
        these two fields are documented to have.
        """
        annotation_store.annotate(
            self.config, self.state, "pi", "s", goal="G1", output="O1", now=self.NOW
        )
        # Only the goal is sent. The expected output is not mentioned.
        annotation_store.annotate(self.config, self.state, "pi", "s", goal="G2", now=self.NOW + 1)
        entry = annotation_store.find(annotation_store.active(self.config, self.state), "pi", "s")
        assert entry is not None
        self.assertEqual(
            ("G2", ({"text": "O1", "source": "typed"},)),
            (entry["revisions"][-1]["goal"], entry["revisions"][-1]["lines"]),
        )

        # An explicit empty string is a clear of that one field.
        annotation_store.annotate(
            self.config, self.state, "pi", "s", lines=[], expected_revision=2, now=self.NOW + 2
        )
        entry = annotation_store.find(annotation_store.active(self.config, self.state), "pi", "s")
        assert entry is not None
        self.assertEqual(
            ("G2", ()), (entry["revisions"][-1]["goal"], entry["revisions"][-1]["lines"])
        )

    def test_an_unannotated_session_publishes_no_zero_revision_and_no_epoch(self) -> None:
        """`revision: 0` and `at: 0.0` are the zeros the first rule forbids.

        A render printing the annotation timestamp would show 1 January 1970 for
        every session nobody annotated.
        """
        absent = annotation_store.published(None)
        self.assertIsNone(absent["revision"])
        self.assertIsNone(absent["at"])

    def test_a_prefix_binding_says_so_and_an_exact_one_stays_quiet(self) -> None:
        """The hazard DRC-4508 named, reported rather than claimed away.

        `collectors/claude.py` passes the transcript stem's first eight
        characters to `base_session`, so a Claude row's sid IS the display
        prefix and the full stem is published beside it as `resume_id`.
        """
        rows: list[Any] = [
            {
                "harness": "claude",
                "sid": "77aa41c2",
                "resume_id": "77aa41c2-aaaa-4aaa",
                "state": "x",
            },
            {"harness": "pi", "sid": "full-identity", "resume_id": None, "state": "x"},
        ]
        aggregate._attach_annotations(rows, ())
        self.assertTrue(rows[0]["annotation_binding_why"], "a truncated identity said nothing")
        self.assertEqual("", rows[1]["annotation_binding_why"])

    def test_a_display_length_identity_says_so_even_with_no_resume_id(self) -> None:
        """DRC-4533, second item. The length proxy missed the case the Claude
        collector documents.

        A Claude row that reached the loop from the task store alone has no
        transcript and therefore no `resume_id`, which that collector records as
        the None case. Its sid is still the eight-character prefix, so the row
        claimed an exact binding it never had.
        """
        rows: list[Any] = [
            {"harness": "claude", "session": "77aa41c2", "sid": "77aa41c2", "resume_id": None},
        ]
        aggregate._attach_annotations(rows, ())
        self.assertTrue(
            rows[0]["annotation_binding_why"],
            "a display-length identity with no resume id claimed exact binding",
        )

    def test_a_saved_revision_that_repeats_the_last_one_is_not_appended(self) -> None:
        """Re-saving unchanged text is not a new request, so it is not a revision.

        Otherwise a reader who opens the field and closes it burns a revision
        number that an assessment will later cite as a change of intent.
        """
        annotation_store.annotate(self.config, self.state, "pi", "s", goal="Same", now=self.NOW)
        annotation_store.annotate(self.config, self.state, "pi", "s", goal="Same", now=self.NOW + 5)

        entry = annotation_store.find(annotation_store.active(self.config, self.state), "pi", "s")
        assert entry is not None
        self.assertEqual(1, len(entry["revisions"]))

    # --- untrusted input ---------------------------------------------------

    def test_a_credential_is_redacted_before_the_text_is_bounded(self) -> None:
        """Order matters, and `records.redact_clip` records why.

        Bounding first can cut a key's tail off, leaving a head that no longer
        matches the shape list and is published intact.
        """
        secret = "AKIA" + "Q" * 16
        cap = self.config.annotation_text_cap_chars
        # Straddling the cap on purpose. A short fixture never reaches the clip,
        # so clip-then-redact and redact-then-clip are indistinguishable and the
        # test proves nothing about the order it is named for. Here the tail
        # falls outside the bound, so clipping first would leave a head the
        # shape list no longer matches and publish it intact.
        annotation_store.annotate(
            self.config, self.state, "pi", "s", goal="x" * (cap - 10) + " " + secret, now=self.NOW
        )
        entry = annotation_store.find(annotation_store.active(self.config, self.state), "pi", "s")
        assert entry is not None
        stored = entry["revisions"][-1]["goal"]
        self.assertNotIn(secret, stored)
        self.assertNotIn(secret[:12], stored, "a clipped head of the key survived")

    def test_text_is_clipped_to_the_configured_bound(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "pi", "s", goal="x" * 5_000, now=self.NOW
        )
        entry = annotation_store.find(annotation_store.active(self.config, self.state), "pi", "s")
        assert entry is not None
        self.assertLessEqual(
            len(entry["revisions"][-1]["goal"]), self.config.annotation_text_cap_chars
        )

    def test_binding_uses_the_full_session_id_not_a_display_prefix(self) -> None:
        """Two Claude sessions sharing an eight-character prefix are two rows.

        `sessions.py` publishes both `session` (the prefix) and `sid` (the full
        id) on every row, so exact binding needs no new identity work. Keying on
        the prefix would let one session's words appear under another's name.
        """
        first = "77aa41c2" + "-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        second = "77aa41c2" + "-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        annotation_store.annotate(
            self.config, self.state, "claude", first, goal="Mine", now=self.NOW
        )

        entries = annotation_store.active(self.config, self.state)
        self.assertIsNotNone(annotation_store.find(entries, "claude", first))
        self.assertIsNone(annotation_store.find(entries, "claude", second))
        self.assertIsNone(annotation_store.find(entries, "claude", "77aa41c2"))

    # --- degradation -------------------------------------------------------

    def test_a_corrupt_store_reads_as_empty_and_one_bad_entry_costs_one_entry(self) -> None:
        path = annotation_store.store_path(self.config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text("{ not json", encoding="utf-8")
        self.assertEqual((), annotation_store.load(self.config))

        Path(path).write_text(
            json.dumps(
                {
                    "v": 1,
                    "entries": [
                        {"harness": "pi", "sid": "good", "revisions": [{"n": 1, "goal": "kept"}]},
                        "not a record",
                        {"sid": "no harness", "revisions": []},
                    ],
                }
            ),
            encoding="utf-8",
        )
        kept = annotation_store.load(self.config)
        self.assertEqual(1, len(kept))
        self.assertEqual("good", kept[0]["sid"])

    def test_the_off_switch_reads_empty_and_writes_nothing(self) -> None:
        off = self._config(annotations_enabled=False)
        state = build_runtime_state(off, started=self.NOW)
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            annotation_store.annotate(off, state, "pi", "s", goal="G", now=self.NOW),
        )
        self.assertEqual((), annotation_store.load(off))
        self.assertFalse(os.path.exists(annotation_store.store_path(off)))

    def test_clearing_removes_the_session_and_leaves_the_others(self) -> None:
        annotation_store.annotate(self.config, self.state, "pi", "keep", goal="K", now=self.NOW)
        annotation_store.annotate(self.config, self.state, "pi", "drop", goal="D", now=self.NOW)
        annotation_store.clear(self.config, self.state, "pi", "drop")

        entries = annotation_store.active(self.config, self.state)
        self.assertIsNotNone(annotation_store.find(entries, "pi", "keep"))
        # The words go and a discard record stands where they were (DRC-4565).
        # `find` returning something is not the assertion this test is about;
        # that nothing typed survives is.
        dropped = annotation_store.find(entries, "pi", "drop")
        assert dropped is not None
        self.assertEqual((), dropped["revisions"])
        self.assertTrue(annotation_store.is_discarded(dropped))
        self.assertNotIn("D", json.dumps(dropped))

    def test_the_store_is_bounded_by_sessions_and_by_revisions(self) -> None:
        """Two count bounds and no time-to-live, for `dismissals._bounded`'s reason.

        A TTL would delete what the reader asked for while the session it
        describes is still on the board.
        """
        limit = self.config.annotation_max_sessions
        for index in range(limit + 3):
            annotation_store.annotate(
                self.config, self.state, "pi", f"s{index}", goal="G", now=self.NOW + index
            )
        self.assertEqual(limit, len(annotation_store.load(self.config)))
        # The oldest gave way, the newest is present.
        self.assertIsNone(annotation_store.find(annotation_store.load(self.config), "pi", "s0"))

        # Newer than every session above, or the session bound evicts this one
        # between saves and its numbering restarts. The two bounds are
        # independent and a fixture that lets them interact tests neither.
        revision_limit = self.config.annotation_max_revisions
        for index in range(revision_limit + 3):
            annotation_store.annotate(
                self.config,
                self.state,
                "pi",
                "many",
                goal=f"G{index}",
                now=self.NOW + 9_000 + index,
            )
        entry = annotation_store.find(annotation_store.load(self.config), "pi", "many")
        assert entry is not None
        self.assertEqual(revision_limit, len(entry["revisions"]))
        # Numbering keeps counting, so a dropped revision reads as dropped
        # rather than as one that never existed.
        self.assertEqual(revision_limit + 3, entry["revisions"][-1]["n"])

    # --- a repeated save is already stored (spec ui3 item 1) ----------------

    def _stored_twice(self) -> None:
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.annotate(
                self.config, self.state, "pi", "s", goal="G", lines=["A", "B"], now=self.NOW
            ),
        )
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.annotate(
                self.config,
                self.state,
                "pi",
                "s",
                goal="G2",
                lines=["A", "B"],
                expected_revision=1,
                now=self.NOW + 1,
            ),
        )

    def test_a_reader_whose_second_identical_save_arrives_after_the_first_is_told_the_words_are_already_stored(
        self,
    ) -> None:
        """A double press, a retry after a lost answer, or a second tab, all drafted at 1.

        The first save minted revision 2; the second carries the same words and
        the revision it was drafted against. Refusing it would tell the reader
        "Not saved" about words that are on disk.
        """
        self._stored_twice()
        outcome = annotation_store.annotate(
            self.config,
            self.state,
            "pi",
            "s",
            goal="G2",
            lines=["A", "B"],
            expected_revision=1,
            now=self.NOW + 2,
        )
        self.assertEqual(annotation_store.OUTCOME_UNCHANGED, outcome)
        entry = annotation_store.find(annotation_store.load(self.config), "pi", "s")
        assert entry is not None
        self.assertEqual(2, entry["revisions"][-1]["n"])

    def test_a_reader_on_a_stale_tab_who_sends_different_words_is_still_refused(self) -> None:
        self._stored_twice()
        outcome = annotation_store.annotate(
            self.config,
            self.state,
            "pi",
            "s",
            goal="G3",
            lines=["A", "B"],
            expected_revision=1,
            now=self.NOW + 2,
        )
        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        lines_only = annotation_store.annotate(
            self.config,
            self.state,
            "pi",
            "s",
            goal="G2",
            lines=["A"],
            expected_revision=1,
            now=self.NOW + 3,
        )
        self.assertEqual(annotation_store.OUTCOME_REFUSED, lines_only)
        entry = annotation_store.find(annotation_store.load(self.config), "pi", "s")
        assert entry is not None
        self.assertEqual(2, entry["revisions"][-1]["n"])


class SettlingALaterDirectionTest(unittest.TestCase):
    """The reader's answer to an unresolved baseline conflict.

    DEC-16 forbids writing into a session, so the annotation store is the only
    place Compass holds a decision the reader made. The mark is three scalars
    and no prose, which is what keeps it out of DEC-15b's admission path.
    """

    NOW = 1_800_000_000.0

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.state = build_runtime_state(self.config, started=self.NOW)

    def _typed(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "pi", "s1", goal="Ship the cockpit", now=self.NOW
        )

    def _published(self) -> dict[str, Any]:
        return annotation_store.published(
            annotation_store.find(annotation_store.active(self.config, self.state), "pi", "s1")
        )

    def test_a_settlement_records_what_it_answered_and_the_revision_it_rested_on(self) -> None:
        self._typed()

        landed = annotation_store.settle(
            self.config,
            self.state,
            "pi",
            "s1",
            through=self.NOW + 60,
            now=self.NOW + 120,
        )

        # The token and not a truthiness test: every outcome is a non-empty
        # string, so `assertTrue` would pass for a refusal.
        self.assertEqual(annotation_store.OUTCOME_STORED, landed)
        published = self._published()
        self.assertEqual(self.NOW + 120, published["settled_at"])
        self.assertEqual(self.NOW + 60, published["settled_through"])
        # The baseline it answered about. A settlement that does not carry it
        # cannot be understood on return, which is DEC-18's amendment.
        self.assertEqual(1, published["settled_revision"])

        # Again at a LATER revision, because asserting only against revision 1
        # cannot tell "the revision it rested on" from a hardcoded 1 — measured:
        # that mutation survived a version of this test that stopped above.
        annotation_store.annotate(
            self.config, self.state, "pi", "s1", goal="Ship it twice", now=self.NOW + 200
        )
        annotation_store.settle(
            self.config, self.state, "pi", "s1", through=self.NOW + 300, now=self.NOW + 300
        )

        self.assertEqual(2, self._published()["settled_revision"])

    def test_the_client_cannot_settle_the_future(self) -> None:
        self._typed()

        annotation_store.settle(
            self.config,
            self.state,
            "pi",
            "s1",
            through=self.NOW + 10_000_000,
            now=self.NOW + 5,
        )

        # Clamped to now. Unclamped, one local POST would disable the block for
        # this session forever; clamped, the damage is "settled as of now" and
        # any later direction re-opens it.
        self.assertEqual(self.NOW + 5, self._published()["settled_through"])

    def test_settling_a_session_with_nothing_typed_is_refused(self) -> None:
        landed = annotation_store.settle(
            self.config, self.state, "pi", "s1", through=self.NOW, now=self.NOW
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, landed)
        self.assertIsNone(self._published()["settled_at"])

    def test_a_non_numeric_through_is_refused_including_a_bool(self) -> None:
        self._typed()

        for value in (True, "now", None, {"at": 1}):
            with self.subTest(value=value):
                self.assertEqual(
                    annotation_store.OUTCOME_REFUSED,
                    annotation_store.settle(
                        self.config, self.state, "pi", "s1", through=value, now=self.NOW
                    ),
                )
        self.assertIsNone(self._published()["settled_at"])

    def test_a_new_revision_carries_the_settlement_rather_than_discarding_it(self) -> None:
        self._typed()
        annotation_store.settle(self.config, self.state, "pi", "s1", through=self.NOW, now=self.NOW)

        annotation_store.annotate(
            self.config, self.state, "pi", "s1", goal="Ship it twice", now=self.NOW + 200
        )

        published = self._published()
        self.assertEqual(2, published["revision"])
        # The mark survives and still names revision 1, which is what it
        # answered about. The block clears by the new revision's own stamp.
        self.assertEqual(self.NOW, published["settled_through"])
        self.assertEqual(1, published["settled_revision"])

    def test_a_settlement_written_by_hand_into_the_file_is_not_trusted(self) -> None:
        self._typed()
        path = Path(annotation_store.store_path(self.config))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["entries"][0]["settled"] = {"at": True, "through": 1.0, "revision": 1}
        path.write_text(json.dumps(payload), encoding="utf-8")

        # A fresh process: nothing cached.
        restarted = build_runtime_state(self.config, started=self.NOW)
        entry = annotation_store.find(annotation_store.active(self.config, restarted), "pi", "s1")

        assert entry is not None
        # `isinstance(True, int)` is true, so a bool would otherwise become a
        # settlement at the epoch. The words survive; only the mark is dropped.
        self.assertIsNone(annotation_store.published(entry)["settled_at"])
        self.assertEqual("Ship the cockpit", entry["revisions"][-1]["goal"])

    def test_the_mark_survives_a_restart(self) -> None:
        self._typed()
        annotation_store.settle(
            self.config, self.state, "pi", "s1", through=self.NOW, now=self.NOW + 1
        )

        restarted = build_runtime_state(self.config, started=self.NOW + 9)
        entry = annotation_store.find(annotation_store.active(self.config, restarted), "pi", "s1")

        assert entry is not None
        self.assertEqual(self.NOW + 1, annotation_store.published(entry)["settled_at"])


class AnUnwritableStoreIsReportedRatherThanSwallowedTest(unittest.TestCase):
    """DRC-4533: `save()`'s failure arm and the `persisted:false` it feeds.

    Both were untested. The diagnostic sentence was corrected on this branch
    from "next restart" to "next collection" and was then defended by nothing,
    which is the shape of a claim that quietly goes stale.

    What the arm has to get right is narrow and easy to get wrong: the write
    fails, the words stay in this process, the caller is told, and the next
    collection reloads from disk and drops them. The page's cue says exactly
    that, so if this arm changes, that sentence becomes a lie.
    """

    NOW = 1_800_000_000.0

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # A FILE where the state home has to be a directory. `os.makedirs` then
        # raises FileExistsError, which is an OSError, on a real filesystem
        # rather than through a patched-out `open`: the arm under test is the
        # one a full disk or a read-only home reaches, and a mock of the write
        # would not prove `os.replace` and the temp-file cleanup are inside it.
        self.blocked = self.root / "state"
        self.blocked.write_text("not a directory", encoding="utf-8")
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.blocked)},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.state = build_runtime_state(self.config, started=self.NOW)
        self.said: list[str] = []

    def test_the_write_fails_loudly(self) -> None:
        landed = annotation_store.save(self.config, (), diagnostic_sink=self.said.append)

        self.assertFalse(landed)
        self.assertTrue(
            any("could not write the annotation store" in line for line in self.said),
            self.said,
        )
        # The sentence names the collection, not a restart. A reader who is told
        # the wrong horizon plans around the wrong one.
        self.assertTrue(any("gone at the next collection" in line for line in self.said), self.said)

    def test_a_write_that_fails_after_the_temp_file_exists_cleans_it_up(self) -> None:
        """The cleanup arm, which needs a failure LATER than the first one.

        Written as its own case because the obvious fixture cannot reach it: an
        unwritable home fails at `makedirs`, before `os.open` has made anything
        to clean up, so a leftover assertion there passes with the cleanup
        deleted. Measured: that mutation survived. Here the home is real and the
        TARGET is a directory, so the temp file is written and `os.replace` is
        what fails.
        """
        home = self.root / "writable"
        home.mkdir()
        config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(home)},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        # A directory exactly where the store file goes.
        pathlib.Path(annotation_store.store_path(config)).mkdir(parents=True)

        landed = annotation_store.save(config, (), diagnostic_sink=self.said.append)

        self.assertFalse(landed)
        strays = [name for name in os.listdir(home) if ".tmp" in name]
        self.assertEqual([], strays, "the partial write was left behind")

    def test_annotate_reports_the_failure_while_this_process_keeps_the_words(self) -> None:
        landed = annotation_store.annotate(
            self.config,
            self.state,
            "pi",
            "sess-1",
            goal="Ship the cockpit",
            now=self.NOW,
            diagnostic_sink=self.said.append,
        )

        # Unwritable, which the endpoint publishes as `persisted:false` with
        # `outcome:"unwritable"`, and not a refusal.
        self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, landed)
        # And yet the revision IS in this process: `annotate` sets
        # `state.annotations` before it writes, inside the lock. That is the
        # whole reason the page may not treat a false here as a lost save
        # without also saying the words are about to go.
        held = annotation_store.find(
            annotation_store.active(self.config, self.state), "pi", "sess-1"
        )
        assert held is not None
        self.assertEqual("Ship the cockpit", held["revisions"][-1]["goal"])

    def test_the_next_collection_is_what_actually_takes_the_words(self) -> None:
        annotation_store.annotate(
            self.config,
            self.state,
            "pi",
            "sess-1",
            goal="Ship the cockpit",
            now=self.NOW,
            diagnostic_sink=self.said.append,
        )

        # `aggregate` calls this on every collection. It reloads from disk, and
        # disk never got the write, so the words go here rather than at a
        # restart. The page's `unpersisted` cue is written against this fact.
        annotation_store.refresh(self.config, self.state)

        gone = annotation_store.find(
            annotation_store.active(self.config, self.state), "pi", "sess-1"
        )
        self.assertIsNone(gone)


class AnnotationWiringTest(unittest.TestCase):
    """The two wirings a copy-paste breaks silently.

    Both off-switch tests elsewhere construct the config directly, and the
    documentation oracle only greps `cli.py` for the flag string, so neither
    would notice `annotations_enabled=not args.no_dismiss`.
    """

    NOW = 1_800_000_000.0

    def test_the_flag_reaches_the_config(self) -> None:
        """Through `build_runtime`, not through argparse.

        An earlier version of this test asserted only that the parser sets
        `args.no_annotations`, which argparse guarantees. The arbiter proved it
        hollow by mutating line 381 to `annotations_enabled=not args.no_dismiss`
        and watching the whole suite stay green. It reads the config now.
        """
        parser = cli.build_parser()
        off, _state = cli.build_runtime(parser.parse_args(["--no-annotations"]), started=self.NOW)
        self.assertFalse(off.annotations_enabled)
        # And not by accident of another flag: the plausible copy-paste is
        # `not args.no_dismiss`, so pin that the two switches are independent.
        self.assertTrue(off.dismissals_enabled)
        on, _state2 = cli.build_runtime(parser.parse_args([]), started=self.NOW)
        self.assertTrue(on.annotations_enabled)
        dismiss_off, _s3 = cli.build_runtime(parser.parse_args(["--no-dismiss"]), started=self.NOW)
        self.assertTrue(dismiss_off.annotations_enabled)

    def test_the_capability_is_published_only_when_the_store_is_live(self) -> None:
        """The flag's help text says the page offers no field to type them in,
        which needs the page to be told."""
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        on_config, on_state = make_runtime(state_home=home, state_dir=Path(home))
        on_collect = cli.build_application(on_config, on_state, clock=lambda: 0.0).collect(
            show_all=True
        )
        self.assertIs(True, on_collect.get("annotate"))
        self.assertEqual("accepted", on_collect.get("reading_check"))
        off_config, off_state = make_runtime(
            state_home=home, state_dir=Path(home), annotations_enabled=False
        )
        off_collect = cli.build_application(off_config, off_state, clock=lambda: 0.0).collect(
            show_all=True
        )
        self.assertIs(False, off_collect.get("annotate"))
        self.assertEqual("not-run", off_collect.get("reading_check"))

    def test_absent_reading_check_and_annotate_published_under_no_annotations(self) -> None:
        """DRC-4550. An absent capability or check states its absent value rather
        than omitting the keys, distinguishing a run with annotations off from a
        build that predates reading fields."""
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        config, state = make_runtime(
            state_home=home, state_dir=Path(home), annotations_enabled=False
        )
        data = cli.build_application(config, state, clock=lambda: 0.0).collect(show_all=True)
        self.assertIn("annotate", data)
        self.assertIn("reading_check", data)
        self.assertIs(False, data["annotate"])
        self.assertEqual("not-run", data["reading_check"])


class DiscardingIsNotTheClearBesideTheBoxTest(unittest.TestCase):
    """DRC-4561. Two acts, one word, and only the weaker one had a control.

    The board's `clear` empties a box; the save after it mints a revision
    holding an empty string, every earlier revision survives, and every
    departure quoting the deleted words keeps quoting them on the wire. The
    endpoint's `clear` arm is the other act and nothing reached it. The
    sentences for it live here, beside the store that performs it, because the
    success sentence claims something about the departure store the page never
    reads.
    """

    def test_the_success_sentence_names_every_effect_and_counts_nothing(self) -> None:
        said = annotation_store.DISCARD_STORED

        # Every revision, the reading kept beside them, and the quotations in
        # the other store — `clear` drops the whole entry and
        # `_withdraw_raises` blanks the rows.
        self.assertIn("Every revision", said)
        self.assertIn("reading", said)
        self.assertIn("summary", said)
        self.assertIn("quotes them any more", said)
        # And the row that survives on purpose, because it is what bounds the
        # lane's spend.
        self.assertIn("bounds how often one may run", said)
        # No count of anything: `departures.withdraw` returns True whether it
        # blanked five rows or none, so nothing here could measure one.
        self.assertFalse([word for word in said.split() if word.isdigit()])

    def test_the_confirmation_names_the_effects_before_the_act_and_not_after(self) -> None:
        """The armed sentence is the only one a reader sees before the write.

        It said no more than that a second press would discard, and the four
        names arrived after the deletion, so `SKILL.md`'s promise that the
        board says what it will delete and what it will withdraw rested on a
        sentence printed too late to act on. Same four names as the success
        sentence, in the future tense.
        """
        said = annotation_store.DISCARD_ARMED

        self.assertIn("Every revision", said)
        self.assertIn("reading", said)
        # The summary goes too, and one being written goes with it (owner's ruling, 2026-10-21).
        self.assertIn("summary, including one being written", said)
        self.assertIn("will quote them any more", said)
        self.assertIn("the record that a check ran stays", said.lower())
        # And it still says nothing has happened yet, which is what makes it a
        # confirmation rather than a receipt.
        self.assertIn("Nothing has been deleted yet", said)
        # And says when the offer lapses, because "on its own" gave a reader no time to act in.
        self.assertIn("lapses in 30 seconds", said)

    def test_the_half_landed_sentence_does_not_claim_the_quotations_went(self) -> None:
        """`departures.withdraw` can fail alone, and the entry is gone by then.

        The categorical success sentence was printed over rows the page was
        about to redraw with the discarded words in them, because the route
        threw the departure store's answer away.
        """
        said = annotation_store.DISCARD_UNWITHDRAWN

        self.assertIn("Every revision", said)
        self.assertIn("goes on quoting them", said)
        self.assertNotIn("quotes them any more", said)

    def test_the_standing_sentence_separates_the_two_acts_by_name(self) -> None:
        said = annotation_store.DISCARD_WHY

        self.assertIn("clear", said)
        self.assertIn("keeps every earlier revision", said)
        self.assertIn("Discarding everything", said)
        # What goes and what stays, before the act: the summary goes, the check record and
        # session history stay, and --forget is the way to clear that history.
        for named in ("summary", "record that a check ran", "Session history", "--forget"):
            self.assertIn(named, said)

    def test_the_half_landed_summary_sentence_names_the_control_that_finishes_it(self) -> None:
        said = annotation_store.DISCARD_SUMMARY_KEPT

        self.assertIn("summary could not be deleted", said)
        self.assertIn("Delete summary", said)

    def test_no_discard_sentence_is_one_of_the_save_cues(self) -> None:
        """ "Saved as a new revision." after a deletion is DRC-4543 re-shipped."""
        said = set(annotation_store.DISCARD_SENTENCES.values())

        self.assertEqual(len(annotation_store.DISCARD_SENTENCES), len(said))
        self.assertEqual(16, len(said))
        self.assertNotIn("Saved as a new revision.", said)
        for sentence in said:
            with self.subTest(sentence=sentence[:32]):
                self.assertNotIn("still in the box", sentence)

    def test_clearing_a_session_with_no_entry_still_answers_stored(self) -> None:
        """Pinned as it is, not fixed. `UNCHANGED` would look tidier and skip
        `_withdraw_raises`, and the reachable state where an annotation was
        evicted while its departure rows survive would then keep the
        quotations standing forever. The control is gated on
        `revision_count > 0` instead, which is why nothing here needs to move.
        """
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        config, state = make_runtime(state_home=home, state_dir=Path(home))

        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.clear(
                config, state, "pi", "never-annotated", diagnostic_sink=lambda _line: None
            ),
        )

    def _two_dashboards(self) -> tuple[RuntimeConfig, Any, Any]:
        """One Compass home and two states: a discarding dashboard and the one that saves."""
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        config, discarding = make_runtime(state_home=home, state_dir=Path(home))
        return config, discarding, build_runtime_state(config, started=0.0)

    def test_a_discard_decides_on_the_stored_revisions_and_not_on_this_dashboards_copy(
        self,
    ) -> None:
        """DRC-4939. A save from another tab landed after this dashboard last read the file.

        The discard route chose whether to take the summary from `active`, the unlocked cached
        copy, so a save that this dashboard had not yet seen left words discarded and the
        summary standing. The count of what went is taken under the lock, from the file.
        """
        config, discarding, saving = self._two_dashboards()
        silent = lambda _line: None  # noqa: E731 - a sink with nothing to say
        self.assertEqual((), annotation_store.active(config, discarding))
        for goal in ("First", "Second"):
            annotation_store.annotate(
                config, saving, "pi", "raced", goal=goal, output="", diagnostic_sink=silent
            )
        self.assertEqual((), annotation_store.active(config, discarding))

        receipt: dict[str, int] = {}
        outcome = annotation_store.clear(
            config, discarding, "pi", "raced", diagnostic_sink=silent, receipt=receipt
        )

        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        self.assertEqual(2, receipt["removed_revisions"])
        entry = annotation_store.find(annotation_store.refresh(config, saving), "pi", "raced")
        self.assertTrue(annotation_store.is_discarded(entry))
        self.assertEqual(2, annotation_store.discarded_revision(entry))

    def test_a_save_after_a_discard_is_a_new_revision_never_half_of_the_old_entry(self) -> None:
        """DRC-4939. The two orders of a save and a discard each leave one whole state."""
        config, discarding, saving = self._two_dashboards()
        silent = lambda _line: None  # noqa: E731 - a sink with nothing to say
        annotation_store.annotate(
            config, saving, "pi", "order", goal="Before", output="", diagnostic_sink=silent
        )
        receipt: dict[str, int] = {}
        annotation_store.clear(
            config, discarding, "pi", "order", diagnostic_sink=silent, receipt=receipt
        )
        annotation_store.annotate(
            config, saving, "pi", "order", goal="After", output="", diagnostic_sink=silent
        )

        entry = annotation_store.find(annotation_store.refresh(config, discarding), "pi", "order")
        self.assertEqual(1, receipt["removed_revisions"])
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(["After"], [r["goal"] for r in entry["revisions"]])
        self.assertEqual(2, entry["revisions"][-1]["n"])

    def test_a_discard_that_removed_nothing_says_so_in_its_receipt(self) -> None:
        config, discarding, saving = self._two_dashboards()
        silent = lambda _line: None  # noqa: E731 - a sink with nothing to say
        never: dict[str, int] = {}
        annotation_store.clear(
            config, discarding, "pi", "never", diagnostic_sink=silent, receipt=never
        )
        self.assertEqual(0, never["removed_revisions"])

        annotation_store.annotate(
            config, saving, "pi", "twice", goal="Words", output="", diagnostic_sink=silent
        )
        annotation_store.clear(config, saving, "pi", "twice", diagnostic_sink=silent)
        again: dict[str, int] = {}
        annotation_store.clear(
            config, discarding, "pi", "twice", diagnostic_sink=silent, receipt=again
        )
        self.assertEqual(0, again["removed_revisions"])

    def test_a_discard_the_store_refused_leaves_no_count_to_claim(self) -> None:
        """A refusal removed nothing, and a missing count must not read as zero removed."""
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        config, state = make_runtime(
            state_home=home, state_dir=Path(home), annotations_enabled=False
        )
        receipt: dict[str, int] = {}
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            annotation_store.clear(
                config, state, "pi", "off", diagnostic_sink=lambda _line: None, receipt=receipt
            ),
        )
        self.assertNotIn("removed_revisions", receipt)

    def test_the_sentences_ride_the_payload_only_where_the_store_is_live(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        on_config, on_state = make_runtime(state_home=home, state_dir=Path(home))
        off_config, off_state = make_runtime(
            state_home=home, state_dir=Path(home), annotations_enabled=False
        )

        self.assertEqual(
            annotation_store.DISCARD_SENTENCES,
            cli.build_application(on_config, on_state, clock=lambda: 0.0)
            .collect(show_all=True)
            .get("annotate_discard"),
        )
        self.assertIsNone(
            cli.build_application(off_config, off_state, clock=lambda: 0.0)
            .collect(show_all=True)
            .get("annotate_discard")
        )


class ADiscardLeavesARecordThatSaysWhenTest(unittest.TestCase):
    """DRC-4565. Absence, presence and discarded are three answers, not two.

    `clear` used to delete the entry, so the only account of the act was a cue
    with a thirty second lifetime and the session vanished from the one surface
    built to outlive it. The record it leaves now carries no text at all: what
    it says is that the act happened, when, and how far the revisions had got.

    The half these tests exist for is not the record. It is that the record
    must never read as a session nobody typed against, which is the failure
    this milestone has shipped four times.
    """

    NOW = 1_800_000_000.0

    def setUp(self) -> None:
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.config, self.state = make_runtime(state_home=self.home, state_dir=Path(self.home))

    def _discard(self, sid: str = "s") -> None:
        annotation_store.annotate(
            self.config, self.state, "pi", sid, goal="Ship the cockpit", now=self.NOW
        )
        annotation_store.clear(
            self.config, self.state, "pi", sid, now=self.NOW + 60, diagnostic_sink=lambda _l: None
        )

    def _entry(self, sid: str = "s") -> annotation_store.Annotation | None:
        return annotation_store.find(annotation_store.load(self.config), "pi", sid)

    # --- the record itself -------------------------------------------------

    def test_a_discard_leaves_an_entry_that_says_when_and_holds_no_text(self) -> None:
        self._discard()

        entry = self._entry()
        assert entry is not None, "the discard deleted the entry outright"
        self.assertEqual((), entry["revisions"])
        self.assertEqual(self.NOW + 60, entry.get("discarded"))
        # Text-free, and asserted over the whole serialised record rather than
        # field by field: a field added later that carried the words would pass
        # a list of names and fail this.
        self.assertNotIn("Ship the cockpit", json.dumps(entry))

    def test_the_record_survives_a_restart(self) -> None:
        """The cue lapses in thirty seconds; this is the half that does not."""
        self._discard()
        _config, second = make_runtime(state_home=self.home, state_dir=Path(self.home))

        entry = annotation_store.find(annotation_store.active(self.config, second), "pi", "s")
        assert entry is not None
        self.assertEqual(self.NOW + 60, entry.get("discarded"))

    def test_discarding_a_session_that_never_had_words_records_nothing(self) -> None:
        """Discarding nothing is not a discard.

        The outcome stays `STORED`, which
        `test_clearing_a_session_with_no_entry_still_answers_stored` pins and
        this must not overturn: it is what keeps `_withdraw_raises` sweeping
        departure rows whose annotation was evicted out from under them.
        """
        outcome = annotation_store.clear(
            self.config, self.state, "pi", "never", diagnostic_sink=lambda _l: None
        )

        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        self.assertIsNone(self._entry("never"))

    # --- find, and the guard that composes for free ------------------------

    def test_find_returns_the_record_and_has_typed_words_still_says_no(self) -> None:
        """decisions.md says to prove this rather than reason it.

        `has_typed_words` reads the latest revision and a record has none, so
        the DRC-4560 guard already routes the away lane and the check sentence
        without a gate of its own. Proved, because the alternative reading --
        that an entry existing means words exist -- is the exact defect that
        guard was built for.
        """
        self._discard()

        entry = self._entry()
        self.assertIsNotNone(entry)
        self.assertFalse(annotation_store.has_typed_words(entry))
        # And the two states it must not be confused with, from the same call.
        self.assertFalse(annotation_store.has_typed_words(None))
        annotation_store.annotate(self.config, self.state, "pi", "live", goal="G", now=self.NOW)
        self.assertTrue(annotation_store.has_typed_words(self._entry("live")))

    # --- the board payload, through the overlay pass -----------------------

    def test_two_rows_side_by_side_do_not_carry_the_same_annotation_fields(self) -> None:
        """The walk's sharpest measurement: all eighteen keys held identical
        values for a session whose words were discarded and one nobody ever
        typed against. Compared as whole field sets rather than key by key, so
        a field added later that fails to distinguish them fails here."""
        self._discard("gone")
        rows: list[Any] = [
            {"harness": "pi", "sid": "gone", "state": "working"},
            {"harness": "pi", "sid": "never", "state": "working"},
        ]

        aggregate._attach_annotations(rows, annotation_store.load(self.config))

        discarded = {k: v for k, v in rows[0].items() if k.startswith("annotation_")}
        absent = {k: v for k, v in rows[1].items() if k.startswith("annotation_")}
        self.assertNotEqual(absent, discarded)
        self.assertEqual(self.NOW + 60, discarded["annotation_discarded_at"])
        self.assertIsNone(absent["annotation_discarded_at"])
        self.assertNotEqual(annotation_store.NO_GOAL_TYPED, discarded["annotation_goal_why"])
        self.assertEqual(annotation_store.NO_GOAL_TYPED, absent["annotation_goal_why"])
        # And no revision of the discarded words reaches the row.
        self.assertNotIn("Ship the cockpit", json.dumps(rows[0]))

    # --- the away lane, which needs no gate of its own ---------------------

    def test_the_away_lane_skips_a_discard_record_without_a_gate_for_it(self) -> None:
        """decisions.md says to prove the free composition rather than assume it.

        The lane's own `not entry.get("revisions")` continue is what does it,
        and `departures.why` is told `has_words=False` through
        `has_typed_words`, so neither claims a check could have run against
        words that are gone.
        """
        self._discard()
        entries = annotation_store.load(self.config)
        row = {"harness": "pi", "sid": "s"}

        published = unasked.published(self.config, (), row, entries=entries, now=self.NOW + 120)

        self.assertEqual([], published["departures"])
        self.assertIs(False, published["departure_checked"])
        # And no sentence at all, which is the half `has_words` could not carry.
        # It routes the LANE correctly and the ladder still answered "not
        # checked", a claim about the past printed under a record that has
        # already said what happened. `discarded` is what stands it down, and
        # the never-typed session below earns it on the same call.
        self.assertEqual("", published["departure_why"])
        never = unasked.published(
            self.config,
            (),
            {"harness": "pi", "sid": "never"},
            entries=entries,
            now=self.NOW + 120,
        )
        self.assertEqual(departures.NEVER_CHECKED, never["departure_why"])

    # --- the third state on the published row ------------------------------

    def test_the_published_row_tells_discarded_from_never_typed(self) -> None:
        self._discard()

        discarded = annotation_store.published(self._entry())
        absent = annotation_store.published(None)

        self.assertNotEqual(absent, discarded)
        self.assertEqual(self.NOW + 60, discarded["discarded_at"])
        self.assertIsNone(absent["discarded_at"])
        self.assertTrue(discarded["discarded_why"])
        self.assertEqual("", absent["discarded_why"])
        # And the sentence the walk measured as identical on both.
        self.assertEqual(annotation_store.NO_GOAL_TYPED, absent["goal_why"])
        self.assertNotEqual(annotation_store.NO_GOAL_TYPED, discarded["goal_why"])
        self.assertNotEqual(annotation_store.NO_LINES_TYPED, discarded["lines_why"])

    def test_a_live_entry_publishes_no_discard(self) -> None:
        """The third state is a state and not a field every row carries a value
        in: a session still holding words has not been discarded."""
        annotation_store.annotate(self.config, self.state, "pi", "live", goal="G", now=self.NOW)

        published = annotation_store.published(self._entry("live"))

        self.assertIsNone(published["discarded_at"])
        self.assertEqual("", published["discarded_why"])
        self.assertEqual("", published["goal_why"])

    # --- a save over the record --------------------------------------------

    def test_a_save_over_the_record_makes_the_entry_live_and_drops_it(self) -> None:
        self._discard()

        outcome = annotation_store.annotate(
            self.config, self.state, "pi", "s", goal="Something else", now=self.NOW + 120
        )

        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        entry = self._entry()
        assert entry is not None
        self.assertNotIn("discarded", entry)
        self.assertEqual("Something else", entry["revisions"][-1]["goal"])
        self.assertIsNone(annotation_store.published(entry)["discarded_at"])

    def test_a_save_over_the_record_does_not_reuse_a_discarded_revision_number(self) -> None:
        """Revision numbers are immutable identities, not a counter that resets.

        Two revisions went; the next is 3. Restarting at 1 would let a
        withdrawn departure row that recorded "read revision 2" point at text
        that revision never held, which is the same re-pointing `Revision`'s
        own docstring refuses in place.
        """
        annotation_store.annotate(self.config, self.state, "pi", "s", goal="one", now=self.NOW)
        annotation_store.annotate(self.config, self.state, "pi", "s", goal="two", now=self.NOW + 1)
        annotation_store.clear(
            self.config, self.state, "pi", "s", now=self.NOW + 2, diagnostic_sink=lambda _l: None
        )

        annotation_store.annotate(
            self.config, self.state, "pi", "s", goal="three", now=self.NOW + 3
        )

        entry = self._entry()
        assert entry is not None
        self.assertEqual(3, entry["revisions"][-1]["n"])

    # --- nothing may be written onto the record ----------------------------

    def test_a_reading_is_refused_against_the_record(self) -> None:
        """`_record`'s own reason, one state further on: a reading of nothing
        is not a reading, and there is no baseline to have read."""
        self._discard()

        outcome = annotation_store.record_withheld(
            self.config,
            self.state,
            "pi",
            "s",
            reason=runtime_reading.WITHHELD_LEDGER_EMPTY,
            spent=True,
            diagnostic_sink=lambda _l: None,
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        entry = self._entry()
        assert entry is not None
        self.assertNotIn("withheld", entry)
        self.assertNotIn("readings", entry)

    def test_settling_the_record_is_refused(self) -> None:
        """The docstring already says a session with nothing typed is refused.
        A record has nothing typed, and the latest-revision read behind that
        rule raises on one."""
        self._discard()

        outcome = annotation_store.settle(
            self.config,
            self.state,
            "pi",
            "s",
            through=self.NOW + 61,
            now=self.NOW + 62,
            diagnostic_sink=lambda _l: None,
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)

    # --- the bound ---------------------------------------------------------

    def test_a_record_is_evicted_before_any_entry_that_still_holds_words(self) -> None:
        """A discard may never push out words a reader still has.

        Age alone would: the record is stamped later than every entry typed
        before it, so oldest-first would evict the reader's own words to keep
        a tombstone.
        """
        config, state = make_runtime(
            state_home=self.home, state_dir=Path(self.home), annotation_max_sessions=3
        )
        annotation_store.annotate(config, state, "pi", "old", goal="oldest", now=self.NOW)
        annotation_store.annotate(config, state, "pi", "mid", goal="middle", now=self.NOW + 1)
        annotation_store.annotate(config, state, "pi", "gone", goal="doomed", now=self.NOW + 2)
        annotation_store.clear(
            config, state, "pi", "gone", now=self.NOW + 3, diagnostic_sink=lambda _l: None
        )

        annotation_store.annotate(config, state, "pi", "new", goal="newest", now=self.NOW + 4)

        kept = {entry["sid"] for entry in annotation_store.load(config)}
        self.assertEqual({"old", "mid", "new"}, kept)

    def test_a_store_of_live_entries_alone_still_evicts_oldest_first(self) -> None:
        """The boring outcome, tested: a rule that only fires on the
        interesting input bounds nothing."""
        config, state = make_runtime(
            state_home=self.home, state_dir=Path(self.home), annotation_max_sessions=2
        )
        annotation_store.annotate(config, state, "pi", "old", goal="oldest", now=self.NOW)
        annotation_store.annotate(config, state, "pi", "mid", goal="middle", now=self.NOW + 1)

        annotation_store.annotate(config, state, "pi", "new", goal="newest", now=self.NOW + 2)

        self.assertEqual({"mid", "new"}, {entry["sid"] for entry in annotation_store.load(config)})

    def test_the_oldest_record_goes_before_a_newer_one(self) -> None:
        config, state = make_runtime(
            state_home=self.home, state_dir=Path(self.home), annotation_max_sessions=2
        )
        for index, sid in enumerate(("first", "second")):
            annotation_store.annotate(config, state, "pi", sid, goal="g", now=self.NOW + index)
            annotation_store.clear(
                config, state, "pi", sid, now=self.NOW + 10 + index, diagnostic_sink=lambda _l: None
            )

        annotation_store.annotate(config, state, "pi", "third", goal="g", now=self.NOW + 20)

        self.assertEqual(
            {"second", "third"}, {entry["sid"] for entry in annotation_store.load(config)}
        )

    # --- the machine's memory of the act -----------------------------------

    def test_forget_removes_the_records_and_leaves_the_reader_their_words(self) -> None:
        """`--forget` deletes the machine's memory of what it observed. A
        record of a deletion is squarely that class; the words a reader typed
        are not, which is why this sweeps rather than deleting the store.
        """
        annotation_store.annotate(self.config, self.state, "pi", "live", goal="keep me")
        self._discard("gone")

        self.assertEqual(annotation_store.FORGET_SWEPT, annotation_store.forget(self.config))

        sids = {entry["sid"] for entry in annotation_store.load(self.config)}
        self.assertEqual({"live"}, sids)

    def test_forget_says_nothing_went_only_when_there_was_nothing_to_remove(self) -> None:
        annotation_store.annotate(self.config, self.state, "pi", "live", goal="keep me")

        self.assertEqual(annotation_store.FORGET_NOTHING, annotation_store.forget(self.config))
        self.assertEqual(1, len(annotation_store.load(self.config)))

    def test_forget_sweeps_a_store_this_run_is_not_reading(self) -> None:
        """`--no-annotations` is a switch for a run and not a statement about
        the file. `history.forget` is deliberately independent of its own flag
        for the reason its docstring gives, and this sibling copied the shape
        and dropped the guarantee: measured, the sweep answered "nothing to
        remove" over a store that still held a record.
        """
        self._discard("gone")
        off = dataclasses.replace(self.config, annotations_enabled=False)
        self.assertEqual((), annotation_store.load(off))

        self.assertEqual(annotation_store.FORGET_SWEPT, annotation_store.forget(off))

        # Read back through the enabled config, because `load` under the off
        # switch returns nothing whether or not the sweep landed.
        self.assertEqual((), annotation_store.load(self.config))

    def test_a_store_it_could_not_write_is_not_a_store_with_nothing_in_it(self) -> None:
        """The boring outcome, which is the one that was wrong. Both failures
        answered the same token, so the command told a reader their records
        were gone over a file it had not touched.
        """
        self._discard("gone")

        with mock.patch.object(annotation_store, "_write", return_value=False) as write:
            self.assertEqual(
                annotation_store.FORGET_UNWRITABLE, annotation_store.forget(self.config)
            )

        self.assertEqual(1, write.call_count)
        self.assertEqual({"gone"}, {entry["sid"] for entry in annotation_store.load(self.config)})


class WordsAreWhatAReadingCouldHaveReadTest(unittest.TestCase):
    """DRC-4560. An entry can stand with nothing typed in it, and does.

    `has_typed_words` is the predicate the unasked path is told, because
    `departures` is a leaf that cannot ask this store. It is the same test
    `reading._readable` applies before spending anything, so "nothing to read
    against" means one thing on the asked and the unasked path.
    """

    NOW = 1_800_000_000.0

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.state = build_runtime_state(self.config, started=self.NOW)

    def test_no_entry_at_all_has_no_words(self) -> None:
        self.assertIs(False, annotation_store.has_typed_words(None))

    def test_a_blank_save_leaves_an_entry_standing_with_nothing_in_it(self) -> None:
        """The reachable route, run rather than read: clear the box, then save.

        The board's `clear` control empties the box and the save after it posts
        `goal: ""`. That is the `annotate` arm and not the `clear` arm, so a
        revision holding two empty strings is minted and the entry survives.
        """
        annotation_store.annotate(
            self.config, self.state, "pi", "sess-1", goal="Ship the cockpit", now=self.NOW
        )

        annotation_store.annotate(
            self.config, self.state, "pi", "sess-1", goal="", now=self.NOW + 10
        )

        entry = annotation_store.find(
            annotation_store.active(self.config, self.state), "pi", "sess-1"
        )
        assert entry is not None
        self.assertEqual(2, len(entry["revisions"]))
        self.assertEqual("", entry["revisions"][-1]["goal"])
        self.assertEqual((), entry["revisions"][-1]["lines"])
        self.assertIs(False, annotation_store.has_typed_words(entry))

    def test_words_in_either_field_of_the_latest_revision_are_words(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "pi", "sess-2", output="Six screenshots", now=self.NOW
        )

        entry = annotation_store.find(
            annotation_store.active(self.config, self.state), "pi", "sess-2"
        )
        self.assertIs(True, annotation_store.has_typed_words(entry))


class AnnotationOnTheRowTest(unittest.TestCase):
    """The store reaching the published payload.

    `AnnotationStoreTest` covers the store. This covers the one thing every
    surface downstream depends on: that a session row carries what the reader
    typed, and that a row with nothing typed carries the absence and its reason
    rather than no key at all. A missing key renders as `undefined`, which is
    the blank the shared contract's first rule forbids.
    """

    def test_a_row_carries_what_was_typed_and_an_unannotated_row_says_why(self) -> None:
        rows: list[Any] = [
            {"harness": "pi", "sid": "typed", "state": "working"},
            {"harness": "pi", "sid": "untouched", "state": "working"},
        ]
        entries: Any = (
            {
                "harness": "pi",
                "sid": "typed",
                "revisions": ({"n": 2, "at": 5.0, "goal": "Ship it", "lines": ()},),
            },
        )
        aggregate._attach_annotations(rows, entries)

        self.assertEqual("Ship it", rows[0]["annotation_goal"])
        self.assertEqual(2, rows[0]["annotation_revision"])
        self.assertEqual("", rows[0]["annotation_goal_why"])
        # No outcome line was typed, so the list names its absence.
        self.assertTrue(rows[0]["annotation_lines_why"])

        # Present, not absent: the key exists so the render has something to ask.
        self.assertEqual("", rows[1]["annotation_goal"])
        self.assertTrue(rows[1]["annotation_goal_why"])
        self.assertEqual(0, rows[1]["annotation_revision_count"])

    def test_binding_on_the_row_is_the_full_sid_not_the_display_prefix(self) -> None:
        """`sessions.py` publishes both. Keying on `session` would let one
        session's words appear under another's name."""
        rows: list[Any] = [
            {"harness": "claude", "session": "77aa41c2", "sid": "77aa41c2-aaaa", "state": "x"}
        ]
        entries: Any = (
            {
                "harness": "claude",
                "sid": "77aa41c2-bbbb",
                "revisions": ({"n": 1, "at": 1.0, "goal": "Not yours", "lines": ()},),
            },
        )
        aggregate._attach_annotations(rows, entries)
        self.assertEqual("", rows[0]["annotation_goal"])
        self.assertTrue(rows[0]["annotation_goal_why"])


class ProvenanceReachesTheDurableRecordTest(unittest.TestCase):
    """DRC-4533, first item. The record must not say a model wrote a line a
    transcript wrote.

    `goal_source` was added so the two can be told apart. The writer that
    persists an observer goal into semantic work history did not read it, and
    stamped every one of them as model-derived including the deterministic ones
    that are the default.
    """

    def test_a_deterministic_goal_is_not_recorded_as_model_derived(self) -> None:
        rows = [
            {
                "harness": "pi",
                "sid": "a",
                "observed_at": 10.0,
                "goal": "From the transcript",
                "goal_source": "deterministic",
                "source": "observer",
            },
            {
                "harness": "pi",
                "sid": "b",
                "observed_at": 11.0,
                "goal": "Reworded",
                "goal_source": "model",
                "source": "observer",
            },
            {
                "harness": "pi",
                "sid": "c",
                "observed_at": 12.0,
                "goal": "Older sidecar",
                "source": "observer",
            },
        ]
        facts = project_context._semantic_observer_facts(rows)
        claims = [f["actor_claim"] for f in facts]
        self.assertEqual(3, len(claims))
        self.assertNotIn("model", claims[0], "a transcript line recorded as model-derived")
        self.assertIn("model", claims[1])
        # A sidecar predating the field claims neither, rather than defaulting
        # to the one that is wrong more often.
        self.assertNotIn("model", claims[2])
        self.assertNotEqual(claims[0], claims[2], "unknown provenance read as deterministic")


class CachedSidecarIsUntrustedTest(unittest.TestCase):
    """DRC-4533, third item. The cached branch republishes fields nothing checks.

    Any local process can rewrite a sidecar. `goal` is type-checked and
    `goal_source` is checked against a frozen set; the four beside them are not.
    """

    def test_a_rewritten_sidecar_cannot_publish_a_non_string_or_an_unbounded_goal(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        state = build_runtime_state(config, started=1.0)
        transcript = root / "t.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")

        runtime_observer.write_sidecar(
            config,
            "pi",
            "hostile",
            {
                "goal": "ok",
                "observed_at": 10.0,
                "transcript": "sig",
                "deterministic_goal": {"k": "AKIAQQQQQQQQQQQQQQQQ"},
                "stage": ["not", "a", "string"],
                "block": {"nested": True},
                "reason": 12345,
            },
        )
        out = project_context._observe_session(
            config, state, str(transcript), ("pi", "hostile"), now=20.0, refresh=False
        )
        assert out is not None
        for field in ("deterministic_goal", "stage", "block", "reason"):
            self.assertNotIsInstance(out[field], (dict, list), f"{field} published a container")

        # And a plausible but enormous string is bounded like every other
        # published goal line.
        runtime_observer.write_sidecar(
            config,
            "pi",
            "hostile",
            {
                "goal": "ok",
                "observed_at": 11.0,
                "transcript": "sig",
                "deterministic_goal": "x" * 5_000,
            },
        )
        out2 = project_context._observe_session(
            config, state, str(transcript), ("pi", "hostile"), now=20.0, refresh=False
        )
        assert out2 is not None
        self.assertLessEqual(len(out2["deterministic_goal"]), config.observer_goal_cap_chars + 1)

    def test_a_rewritten_sidecar_cannot_publish_a_huge_stage_block_or_reason(self) -> None:
        """A type check is not a bound, and these three had only the type check.

        The sidecar is read under `state_read_cap_bytes` (64 KiB), so a rewritten
        one could publish a stage, block or reason of roughly that size straight
        into the served payload. `deterministic_goal` beside them was already
        bounded; these three were the half of the item that had not been done.
        """
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        state = build_runtime_state(config, started=1.0)
        transcript = root / "t.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")

        runtime_observer.write_sidecar(
            config,
            "pi",
            "huge",
            {
                "goal": "ok",
                "observed_at": 10.0,
                "transcript": "sig",
                "stage": "s" * 5_000,
                "block": "b" * 5_000,
                "reason": "r" * 5_000,
            },
        )
        out = project_context._observe_session(
            config, state, str(transcript), ("pi", "huge"), now=20.0, refresh=False
        )
        assert out is not None
        for field in ("stage", "block", "reason"):
            value = out[field]
            self.assertIsInstance(value, str, f"{field} lost its type check")
            self.assertLessEqual(
                len(value),
                config.observer_block_cap_chars + 1,
                f"{field} published {len(value)} characters from a rewritten sidecar",
            )

    def test_a_rewritten_sidecar_cannot_smuggle_a_control_character_onto_the_page(self) -> None:
        """The same three fields carried no scrub either, only an isinstance.

        `safe_text` is what collapses a C0 run to one space, and it is the
        control the single-line annotation fields rest on. A sidecar is a file
        any local process can rewrite, so the cached path needs it too.
        """
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        state = build_runtime_state(config, started=1.0)
        transcript = root / "t.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")

        runtime_observer.write_sidecar(
            config,
            "pi",
            "ctrl",
            {
                "goal": "ok",
                "observed_at": 10.0,
                "transcript": "sig",
                "stage": "one\ntwo",
                "block": "three\r\nfour",
                "reason": "five\tsix",
            },
        )
        out = project_context._observe_session(
            config, state, str(transcript), ("pi", "ctrl"), now=20.0, refresh=False
        )
        assert out is not None
        for field in ("stage", "block", "reason"):
            value = out[field]
            assert isinstance(value, str)
            self.assertNotIn("\n", value, f"{field} kept a newline")
            self.assertNotIn("\r", value, f"{field} kept a carriage return")
            self.assertNotIn("\t", value, f"{field} kept a tab")


class AReadingIsKeptBesideTheWordsItReadTest(unittest.TestCase):
    """DEC-15b as amended: the store is this one, not session history.

    The ruling named history and gave its reason in the same sentence -- so
    both reopen after a restart and after the live row disappears. This store
    already did both, and the amendment followed the measurement.
    """

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        self.state = build_runtime_state(self.config, started=1.0)
        annotation_store.annotate(
            self.config, self.state, "claude", "s1", goal="rename the flag", now=10.0
        )

    @staticmethod
    def _assessment(**over: Any) -> Any:
        base = {
            "revision_read": 1,
            "stamp": "read at 10:00",
            "cutoff": "Read 1 of the 1 entry after your words",
            "scope": runtime_reading.SCOPE_FINAL,
            "scope_text": runtime_reading.SCOPE_TEXT[runtime_reading.SCOPE_FINAL],
            "ended_at_read": 99.0,
            "criteria": {
                "goal": {
                    "result": runtime_reading.RESULT_DEPARTURE,
                    "cites": ("f1",),
                    "detail": "it renamed a different flag",
                    "clause": "rename the flag",
                },
                "line_1": {
                    "result": runtime_reading.RESULT_UNVERIFIABLE,
                    "cites": (),
                    "detail": "",
                    "clause": "",
                },
            },
        }
        base.update(over)
        return base

    def test_reading_time_survives_a_restart_and_legacy_age_is_unknown(self) -> None:
        for supplied, expected in (({}, None), ({"read_at": 90.0}, 90.0)):
            with self.subTest(supplied=supplied):
                annotation_store.record_reading(
                    self.config, self.state, "claude", "s1", assessment=self._assessment(**supplied)
                )
                entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
                assert entry is not None
                self.assertEqual(expected, entry["assessment"]["read_at"])

    def _published(self) -> dict[str, Any]:
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        return annotation_store.published(entry)

    def test_a_withheld_press_publishes_when_it_was_withheld(self) -> None:
        # DRC-4758 slice A3: a reload says how long ago, from the time the
        # store already writes beside the reason, read back from disk.
        with mock.patch("time.time", return_value=500.0):
            annotation_store.record_withheld(
                self.config,
                self.state,
                "claude",
                "s1",
                reason=runtime_reading.WITHHELD_LEDGER_EMPTY,
                spent=False,
            )
        published = self._published()
        self.assertTrue(published["reading_withheld"])
        self.assertEqual(500.0, published["reading_withheld_at"])
        # A later save moves the entry's write time, not the withheld time.
        with mock.patch("time.time", return_value=900.0):
            annotation_store.annotate(
                self.config, self.state, "claude", "s1", goal="rename it", now=900.0
            )
        self.assertEqual(500.0, self._published()["reading_withheld_at"])

    def test_a_reading_that_arrives_retires_the_withheld_time_with_its_reason(self) -> None:
        annotation_store.record_withheld(
            self.config,
            self.state,
            "claude",
            "s1",
            reason=runtime_reading.WITHHELD_LEDGER_EMPTY,
            spent=False,
        )
        annotation_store.record_reading(
            self.config, self.state, "claude", "s1", assessment=self._assessment()
        )
        published = self._published()
        self.assertEqual("", published["reading_withheld"])
        self.assertIsNone(published["reading_withheld_at"])
        # The file still carries the old stamp beside the cleared reason, and
        # a copy held in memory is published by the same rule.
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert entry is not None
        held: Any = {**entry, "withheld": "", "withheld_at": 5.0}
        self.assertIsNone(annotation_store.published(held)["reading_withheld_at"])

    def test_a_reason_stored_before_its_time_was_kept_publishes_no_time(self) -> None:
        path = annotation_store.store_path(self.config)
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = raw["entries"] if isinstance(raw, dict) else raw
        entries[0]["withheld"] = runtime_reading.WITHHELD[runtime_reading.WITHHELD_LEDGER_EMPTY]
        Path(path).write_text(json.dumps(raw), encoding="utf-8")
        published = self._published()
        self.assertTrue(published["reading_withheld"])
        self.assertIsNone(published["reading_withheld_at"], "an unknown time was guessed")
        self.assertIsNone(annotation_store.published(None)["reading_withheld_at"])

    def test_a_reader_who_restarts_still_has_the_reading_they_asked_for(self) -> None:
        self.assertTrue(
            annotation_store.record_reading(
                self.config, self.state, "claude", "s1", assessment=self._assessment()
            )
        )
        # A second process, reading the file the first one wrote.
        reloaded = annotation_store.load(self.config)
        entry = annotation_store.find(reloaded, "claude", "s1")
        assert entry is not None
        self.assertEqual(1, entry["assessment"]["revision_read"])
        self.assertEqual(1, entry["readings"])
        self.assertEqual(
            runtime_reading.RESULT_DEPARTURE, entry["assessment"]["criteria"]["goal"]["result"]
        )

    def test_a_reader_typing_again_does_not_lose_the_reading_they_already_have(self) -> None:
        annotation_store.record_reading(
            self.config, self.state, "claude", "s1", assessment=self._assessment()
        )
        annotation_store.annotate(
            self.config, self.state, "claude", "s1", goal="rename it properly", now=20.0
        )
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert entry is not None
        # Carried, not cleared. It named revision 1 and it still does; the
        # board says so with the stale line rather than by discarding it.
        self.assertEqual(1, entry["assessment"]["revision_read"])
        self.assertEqual(2, len(entry["revisions"]))

    def test_a_reader_clearing_their_words_clears_the_reading_of_them(self) -> None:
        annotation_store.record_reading(
            self.config, self.state, "claude", "s1", assessment=self._assessment()
        )
        annotation_store.clear(self.config, self.state, "claude", "s1")

        # The discard record standing in the entry's place carries no reading,
        # which is what keeps `clear`'s original reasoning true: nothing left
        # behind is citable, because nothing left behind holds words
        # (DRC-4565).
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert entry is not None
        self.assertTrue(annotation_store.is_discarded(entry))
        self.assertNotIn("assessment", entry)
        self.assertIsNone(annotation_store.published(entry)["assessment"])

    def test_a_half_written_reading_is_dropped_whole_rather_than_half_shown(self) -> None:
        # The worst of the three outcomes is the middle one: the page renders
        # whichever half happened to be well-formed rather than whichever half
        # is true.
        for broken in (
            self._assessment(revision_read=0),
            self._assessment(revision_read=True),
            self._assessment(scope="invented"),
            self._assessment(criteria={"goal": {}}),
            self._assessment(smuggled="x"),
        ):
            with self.subTest(broken=sorted(broken)[:2]):
                self.assertIsNone(annotation_store._assessment(broken, 240))

    def test_a_rewritten_store_cannot_publish_a_result_the_board_does_not_own(self) -> None:
        criteria = {
            "goal": {"result": "met", "cites": (), "detail": "", "clause": "g"},
            "line_1": {"result": None, "cites": (), "detail": "", "clause": ""},
        }
        self.assertIsNone(annotation_store._assessment(self._assessment(criteria=criteria), 240))

    def test_a_reader_who_pressed_and_got_nothing_can_tell_that_from_not_pressing(self) -> None:
        published = annotation_store.published(
            annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        )
        self.assertEqual(0, published["reading_count"])
        self.assertEqual("", published["reading_withheld"])

        annotation_store.record_withheld(
            self.config,
            self.state,
            "claude",
            "s1",
            reason=runtime_reading.WITHHELD_TURN_STOP,
            spent=False,
        )
        after = annotation_store.published(
            annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        )
        self.assertEqual(
            runtime_reading.WITHHELD[runtime_reading.WITHHELD_TURN_STOP],
            after["reading_withheld"],
        )
        # Nothing reached the model, so nothing was spent and the count that
        # tells the reader what they have spent must not move.
        self.assertEqual(0, after["reading_count"])

    def test_a_model_call_that_started_and_failed_still_costs_the_reader_a_press(self) -> None:
        annotation_store.record_withheld(
            self.config,
            self.state,
            "claude",
            "s1",
            reason=runtime_reading.WITHHELD_MODEL_FAILED,
            spent=True,
        )
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert entry is not None
        self.assertEqual(1, entry["readings"])

    def test_a_reading_of_a_session_nobody_annotated_is_refused(self) -> None:
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            annotation_store.record_reading(
                self.config, self.state, "claude", "never-typed", assessment=self._assessment()
            ),
        )

    def test_a_stored_reading_keeps_why_each_row_is_unverifiable(self) -> None:
        # DRC-4544 item 3. The reason a row is `not verifiable` is part of what
        # the reading means, and a reading re-read under a later build cannot
        # re-derive it from today's harness.
        criteria = {
            "goal": {
                "result": runtime_reading.RESULT_UNVERIFIABLE,
                "cites": (),
                "detail": "",
                "clause": "rename the flag",
                "why": runtime_reading.WHY_UNREADABLE,
            },
            "line_1": {
                "result": runtime_reading.RESULT_UNVERIFIABLE,
                "cites": (),
                "detail": "",
                "clause": "",
                "why": runtime_reading.WHY_NOT_ASKED,
            },
        }
        annotation_store.record_reading(
            self.config, self.state, "claude", "s1", assessment=self._assessment(criteria=criteria)
        )
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert entry is not None
        stored = entry.get("assessment")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(runtime_reading.WHY_UNREADABLE, stored["criteria"]["goal"]["why"])
        self.assertEqual(runtime_reading.WHY_NOT_ASKED, stored["criteria"]["line_1"]["why"])

    def test_a_reason_this_build_does_not_know_refuses_the_reading_whole(self) -> None:
        # A closed set, refused whole like every other bad key: a half-read
        # reading is worse than none, and a reason invented by a rewrite of the
        # file would otherwise render as the board's own sentence.
        def criteria(why: Any) -> dict[str, Any]:
            return {
                "goal": {
                    "result": runtime_reading.RESULT_UNVERIFIABLE,
                    "cites": (),
                    "detail": "",
                    "clause": "g",
                    "why": why,
                },
                "line_1": {
                    "result": runtime_reading.RESULT_UNVERIFIABLE,
                    "cites": (),
                    "detail": "",
                    "clause": "",
                    "why": "",
                },
            }

        for why in ("a-token-from-the-future", 3, None, ["uncited"]):
            with self.subTest(why=why):
                self.assertIsNone(
                    annotation_store._assessment(self._assessment(criteria=criteria(why)), 240)
                )
        # And a reading stored before the field existed reads back with the
        # reason absent rather than being refused: a missing key is a reading
        # with less in it, not a diverged one.
        criteria_before = criteria("")
        for row in criteria_before.values():
            del row["why"]
        parsed = annotation_store._assessment(self._assessment(criteria=criteria_before), 240)
        assert parsed is not None
        self.assertEqual(runtime_reading.WHY_STANDS, parsed["criteria"]["goal"]["why"])


class AFinalReadingRetractsItselfWhenTheEndStopsBeingPublishedTest(unittest.TestCase):
    """`final` is a durable claim about a session id, not a state of the page.

    Every test here drives the two passes in the order `collect` runs them.
    An earlier version fed the retraction a row already carrying `ended_at`,
    which no row does at that moment, and asserted the resulting retraction as
    correct. Both were green while every final reading on a real board was
    retracted with a sentence that was false.
    """

    @staticmethod
    def _assessment() -> Any:
        return {
            "revision_read": 1,
            "stamp": "",
            "cutoff": "",
            "scope": runtime_reading.SCOPE_FINAL,
            "scope_text": runtime_reading.SCOPE_TEXT[runtime_reading.SCOPE_FINAL],
            "ended_at_read": 99.0,
            "criteria": {
                name: {
                    "result": runtime_reading.RESULT_UNVERIFIABLE,
                    "cites": (),
                    "detail": "",
                    "clause": "",
                }
                for name in (runtime_reading.CONSTRAINT_GOAL, "line_1")
            },
        }

    def _through_the_pipeline(self, ended_at: float | None, *, scope: str | None = None) -> Any:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        state = build_runtime_state(config, started=1.0)
        annotation_store.annotate(config, state, "claude", "s1", goal="rename", now=10.0)
        assessment = self._assessment()
        if scope is not None:
            assessment["scope"] = scope
            assessment["scope_text"] = runtime_reading.SCOPE_TEXT[scope]
        annotation_store.record_reading(config, state, "claude", "s1", assessment=assessment)
        rows: list[dict[str, object]] = [
            {"harness": "claude", "sid": "s1", "state": "idle", "ended_at": None}
        ]
        # What `_apply_overlays` does, and the only thing in the runtime that
        # ever writes this field. It runs BEFORE the attach, which is the
        # ordering under test.
        rows[0]["ended_at"] = ended_at
        aggregate._attach_annotations(rows, annotation_store.load(config))
        return rows[0]["annotation_assessment"]

    def test_a_reading_of_a_transcript_stop_keeps_its_own_sentence_when_read_back(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        state = build_runtime_state(config, started=1.0)
        annotation_store.annotate(config, state, "claude", "s1", goal="rename", now=10.0)
        for stored, expected in (
            (
                runtime_reading.SCOPE_TEXT_LAST_TURN_TRANSCRIPT,
                runtime_reading.SCOPE_TEXT_LAST_TURN_TRANSCRIPT,
            ),
            # Words of the sidecar's own are never read back.
            ("Anything at all.", runtime_reading.SCOPE_TEXT[runtime_reading.SCOPE_LAST_TURN]),
        ):
            with self.subTest(stored=stored):
                assessment = self._assessment()
                assessment["scope"] = runtime_reading.SCOPE_LAST_TURN
                assessment["scope_text"] = stored
                annotation_store.record_reading(
                    config, state, "claude", "s1", assessment=assessment
                )
                entry = annotation_store.find(annotation_store.load(config), "claude", "s1")
                assert entry is not None
                self.assertEqual(
                    expected, annotation_store.published(entry)["assessment"]["scope_text"]
                )
        # A transcript sentence on another scope is not admitted either.
        assessment = self._assessment()
        assessment["scope_text"] = runtime_reading.SCOPE_TEXT_LAST_TURN_TRANSCRIPT
        annotation_store.record_reading(config, state, "claude", "s1", assessment=assessment)
        entry = annotation_store.find(annotation_store.load(config), "claude", "s1")
        assert entry is not None
        self.assertNotEqual(
            runtime_reading.SCOPE_TEXT_LAST_TURN_TRANSCRIPT,
            annotation_store.published(entry)["assessment"]["scope_text"],
        )

    def test_a_reader_whose_session_really_ended_is_still_told_the_reading_is_final(self) -> None:
        published = self._through_the_pipeline(99.0)
        assert isinstance(published, dict)
        self.assertEqual(runtime_reading.SCOPE_FINAL, published["scope"])
        self.assertNotIn("no longer published", published["scope_text"])

    def test_a_reader_returning_to_a_resumed_session_is_not_told_it_is_final(self) -> None:
        for ended in (None, 0.0, 150.0):
            with self.subTest(ended_at=ended):
                published = self._through_the_pipeline(ended)
                assert isinstance(published, dict)
                self.assertEqual(runtime_reading.SCOPE_WITHDRAWN, published["scope"])
                self.assertIn("no longer published", published["scope_text"])

    def test_a_mid_flight_reading_is_never_retracted_by_this_rule(self) -> None:
        published = self._through_the_pipeline(None, scope=runtime_reading.SCOPE_MID_FLIGHT)
        assert isinstance(published, dict)
        self.assertEqual(runtime_reading.SCOPE_MID_FLIGHT, published["scope"])

    def test_the_retraction_runs_after_the_field_it_reads_is_written(self) -> None:
        """The ordering itself, because nothing else can see it.

        The tests above drive the passes by hand, so moving the CALL in
        `collect` is invisible to them, which is exactly how the defect was
        green. This reads `collect`'s own body: the annotation pass carries
        the retraction, and it must run after `_apply_overlays`, the only
        thing in the runtime that writes the field the retraction compares.
        """
        source = (SERVER_PATH.parent / "compass_runtime" / "aggregate.py").read_text(
            encoding="utf-8"
        )
        collect = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef) and node.name == "collect"
        )
        calls = {
            node.func.id: node.lineno
            for node in ast.walk(collect)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        attrs = {
            node.func.attr: node.lineno
            for node in ast.walk(collect)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("_attach_annotations", calls, "the annotation pass is not called")
        self.assertIn("_apply_overlays", attrs, "the overlay pass moved or was renamed")
        self.assertGreater(
            calls["_attach_annotations"],
            attrs["_apply_overlays"],
            "the retraction reads `ended_at` before anything writes it, so every final "
            "reading is retracted with a sentence that is false",
        )

    def test_the_retraction_lives_in_the_pass_the_ordering_assertion_guards(self) -> None:
        # Otherwise the assertion above guards a pass that no longer does the
        # thing the ordering exists for, and goes on passing while it does not.
        source = (SERVER_PATH.parent / "compass_runtime" / "aggregate.py").read_text(
            encoding="utf-8"
        )
        body = source[
            source.index("def _attach_annotations(") : source.index("def _hide_unmeasured")
        ]
        self.assertIn("_withdraw_stale_finality", body)


class TheSavePathReportsTruthfullyTest(unittest.TestCase):
    """DRC-4543. Five ways the board's own report about a save was untrue.

    Each of these is a sentence the reader is shown, not a field they read, so
    every assertion here is on what the endpoint answers rather than on what
    the store holds.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        self.state = build_runtime_state(self.config, started=self.NOW)
        self.root = root

    NOW = 1_800_000_000.0

    def test_a_type_error_out_of_the_dump_is_caught_like_any_other_write_failure(self) -> None:
        # `load` already catches RecursionError; `save` did not, so a payload
        # the encoder refuses dropped the connection instead of answering.
        # Latent today because every field is a str, int or float, and the
        # whole point of the failure arm is that a write failure never reaches
        # the reader as a dropped socket.
        said: list[str] = []
        with mock.patch("compass_runtime.annotations.json.dump", side_effect=TypeError("nope")):
            ok = annotation_store.save(self.config, (), diagnostic_sink=said.append)

        self.assertFalse(ok)
        self.assertTrue(any("could not write the annotation store" in line for line in said))

    def test_a_recursion_error_out_of_the_dump_is_caught_too(self) -> None:
        said: list[str] = []
        with mock.patch("compass_runtime.annotations.json.dump", side_effect=RecursionError):
            ok = annotation_store.save(self.config, (), diagnostic_sink=said.append)

        self.assertFalse(ok)

    def test_a_write_that_fails_leaves_no_temporary_file_behind(self) -> None:
        with mock.patch("compass_runtime.annotations.json.dump", side_effect=TypeError("nope")):
            annotation_store.save(self.config, (), diagnostic_sink=lambda _line: None)

        leftovers = [name for name in os.listdir(self.config.state_home) if name.endswith(".tmp")]
        self.assertEqual([], leftovers)

    def test_the_bytes_and_then_the_rename_reach_the_disk_in_that_order(self) -> None:
        # A rename is atomic against a concurrent reader and says nothing about
        # power loss: the file's bytes need an fsync before it, and the
        # directory entry the rename wrote needs one after it, or the store
        # can come back as the OLD file with the new bytes durable and
        # unreachable. The store holds prose a person composed and cannot
        # retype from anywhere else. An ordered log rather than a count,
        # because a count of one forbade the second sync and observed no order.
        calls: list[str] = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(fd: int) -> None:
            calls.append("file fsync")
            real_fsync(fd)

        def replace(src: str, dst: str) -> None:
            calls.append("replace")
            real_replace(src, dst)

        with (
            mock.patch("compass_runtime.annotations.os.fsync", side_effect=fsync),
            mock.patch("compass_runtime.annotations.os.replace", side_effect=replace),
            mock.patch(
                "compass_runtime.annotations._fsync_directory",
                create=True,
                side_effect=lambda _path: calls.append("directory fsync"),
            ),
        ):
            ok = annotation_store.save(self.config, (), diagnostic_sink=lambda _l: None)

        self.assertTrue(ok)
        self.assertEqual(["file fsync", "replace", "directory fsync"], calls)

    def test_a_rename_that_is_briefly_refused_is_tried_again_and_the_words_land(self) -> None:
        # Windows refuses to replace a file something else has open for an instant (an indexer or a scanner
        # that read the previous version), and the hosted runner's thread test lost saves to it: "could not
        # write the annotation store" for words that were one retry from landing. A refusal that clears is
        # not a failed save.
        real_replace = os.replace
        refused = [PermissionError(13, "Access is denied"), PermissionError(13, "Access is denied")]
        calls: list[str] = []
        said: list[str] = []

        def replace(src: str, dst: str) -> None:
            calls.append("replace")
            if refused:
                raise refused.pop()
            real_replace(src, dst)

        with (
            mock.patch("compass_runtime.annotations.os.replace", side_effect=replace),
            mock.patch("compass_runtime.annotations.time.sleep") as sleep,
        ):
            ok = annotation_store.save(self.config, (), diagnostic_sink=said.append)

        self.assertTrue(ok)
        self.assertEqual(["replace"] * 3, calls)
        self.assertEqual(2, sleep.call_count)
        self.assertEqual([], said)
        leftovers = [name for name in os.listdir(self.config.state_home) if name.endswith(".tmp")]
        self.assertEqual([], leftovers)

    def test_a_rename_that_stays_refused_is_a_failed_save_after_a_bounded_wait(self) -> None:
        calls: list[str] = []
        said: list[str] = []

        def replace(_src: str, _dst: str) -> None:
            calls.append("replace")
            raise PermissionError(13, "Access is denied")

        with (
            mock.patch("compass_runtime.annotations.os.replace", side_effect=replace),
            mock.patch("compass_runtime.annotations.time.sleep") as sleep,
        ):
            ok = annotation_store.save(self.config, (), diagnostic_sink=said.append)

        self.assertFalse(ok)
        self.assertEqual(annotation_store._REPLACE_ATTEMPTS, len(calls))
        self.assertLessEqual(sum(call.args[0] for call in sleep.call_args_list), 1.0)
        self.assertTrue(any("could not write the annotation store" in line for line in said))
        leftovers = [name for name in os.listdir(self.config.state_home) if name.endswith(".tmp")]
        self.assertEqual([], leftovers)

    def test_a_refusal_that_is_not_a_permission_error_is_not_tried_again(self) -> None:
        calls: list[str] = []
        said: list[str] = []

        def replace(_src: str, _dst: str) -> None:
            calls.append("replace")
            raise OSError(28, "No space left on device")

        with (
            mock.patch("compass_runtime.annotations.os.replace", side_effect=replace),
            mock.patch("compass_runtime.annotations.time.sleep") as sleep,
        ):
            ok = annotation_store.save(self.config, (), diagnostic_sink=said.append)

        self.assertFalse(ok)
        self.assertEqual(["replace"], calls)
        sleep.assert_not_called()

    def test_a_directory_that_cannot_be_synced_does_not_report_the_words_as_lost(self) -> None:
        # Windows refuses to open a directory at all, and some filesystems
        # refuse to fsync one. By then the bytes are durable and the rename has
        # happened; only the rename's durability is in doubt. Reporting that
        # as a failed save tells the reader their words are gone when they are
        # on disk, which is DRC-4543's lie in the other direction.
        said: list[str] = []
        with mock.patch(
            "compass_runtime.annotations._fsync_directory",
            create=True,
            side_effect=PermissionError("directories cannot be opened here"),
        ):
            ok = annotation_store.save(self.config, (), diagnostic_sink=said.append)

        self.assertTrue(ok)
        self.assertEqual([], said)
        self.assertTrue(os.path.exists(annotation_store.store_path(self.config)))

    def test_a_platform_without_o_directory_still_saves_and_syncs_the_bytes(self) -> None:
        # The Windows arm of `_fsync_directory` is the early return taken when
        # `os.O_DIRECTORY` does not exist. Every other test here patches the
        # whole function out, so nothing ran its body, and on the Linux
        # coverage runner the constant always exists. Simulated rather than
        # skipped: without the guard the `os.open` call raises AttributeError,
        # which is not in `save`'s except tuple, so the Windows leg of every
        # saving test would die on it.
        calls: list[str] = []
        real_fsync = os.fsync

        def fsync(fd: int) -> None:
            calls.append("fsync")
            real_fsync(fd)

        said: list[str] = []
        with (
            mock.patch("compass_runtime.annotations.os.O_DIRECTORY", None, create=True),
            mock.patch("compass_runtime.annotations.os.fsync", side_effect=fsync),
        ):
            ok = annotation_store.save(self.config, (), diagnostic_sink=said.append)

        self.assertTrue(ok)
        # The file's own bytes, and nothing else: there is no directory to open.
        self.assertEqual(["fsync"], calls)
        self.assertEqual([], said)
        self.assertTrue(os.path.exists(annotation_store.store_path(self.config)))

    def test_an_unchanged_save_says_it_minted_nothing(self) -> None:
        # Re-saving the same words mints no revision, and the store said `True`
        # for it, which the page read as "Saved as a new revision." with the
        # revision count unchanged in the very same reply. Asserted on the
        # stored value: the token is what the endpoint forwards to the page.
        first = annotation_store.annotate(
            self.config, self.state, "pi", "s", goal="Same", now=self.NOW
        )
        again = annotation_store.annotate(
            self.config, self.state, "pi", "s", goal="Same", now=self.NOW + 5
        )

        self.assertEqual(annotation_store.OUTCOME_STORED, first)
        self.assertEqual(annotation_store.OUTCOME_UNCHANGED, again)
        entry = annotation_store.find(annotation_store.active(self.config, self.state), "pi", "s")
        assert entry is not None
        self.assertEqual(1, len(entry["revisions"]))

    def test_a_refusal_and_a_failed_write_are_told_apart(self) -> None:
        # Four refusal arms and one write failure used to share a single
        # `False`, which the page could only render as the lost-write cue. A
        # refusal means the request will never work as sent; a failed write
        # means try again. The reader is owed the difference.
        refused_settle = annotation_store.settle(
            self.config, self.state, "pi", "nobody", through=1.0, now=self.NOW
        )
        refused_empty = annotation_store.annotate(
            self.config, self.state, "pi", "s", goal=None, output=None, now=self.NOW
        )
        refused_key = annotation_store.clear(self.config, self.state, "", "s")
        off = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            annotations_enabled=False,
        )
        refused_off = annotation_store.annotate(
            off, build_runtime_state(off, started=self.NOW), "pi", "s", goal="G", now=self.NOW
        )

        blocked = self.root / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        unwritable_config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(blocked)},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        unwritable = annotation_store.annotate(
            unwritable_config,
            build_runtime_state(unwritable_config, started=self.NOW),
            "pi",
            "s",
            goal="Ship the cockpit",
            now=self.NOW,
            diagnostic_sink=lambda _line: None,
        )

        self.assertEqual(
            [annotation_store.OUTCOME_REFUSED] * 4,
            [refused_settle, refused_empty, refused_key, refused_off],
        )
        self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, unwritable)
        # The vocabulary is closed and every token is a distinct string, so no
        # two outcomes can render as one sentence by accident.
        self.assertEqual(6, len(set(annotation_store.OUTCOMES)))
        self.assertNotIn(True, annotation_store.OUTCOMES)
        self.assertNotIn(False, annotation_store.OUTCOMES)

    def test_a_recorded_reading_names_its_outcome_too(self) -> None:
        # `_record` shares the write with the three mutators, so it speaks the
        # same vocabulary: a reading of a session nobody annotated is refused,
        # a reason this build does not know is refused, and a landed one is
        # stored.
        reason = runtime_reading.WITHHELD_MODEL_UNAVAILABLE
        nobody = annotation_store.record_withheld(
            self.config, self.state, "pi", "nobody", reason=reason, spent=False
        )
        annotation_store.annotate(self.config, self.state, "pi", "s", goal="G", now=self.NOW)
        unknown = annotation_store.record_withheld(
            self.config, self.state, "pi", "s", reason="not-a-reason", spent=False
        )
        landed = annotation_store.record_withheld(
            self.config, self.state, "pi", "s", reason=reason, spent=False
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, nobody)
        self.assertEqual(annotation_store.OUTCOME_REFUSED, unknown)
        self.assertEqual(annotation_store.OUTCOME_STORED, landed)


class AReadingTheStoreRefusesIsNotAReadingNobodyAskedForTest(unittest.TestCase):
    """DRC-4545's second half, driven through a real read rather than injected.

    `_assessment` refuses a stored reading whole on any bad key, which is
    right. But `readings` is read from an independent key and survives, so the
    row published a press with nothing to show and the page rendered both
    "1 reading asked for on this session" and "No reading has been made".
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )

    def _write(self, assessment: Any) -> dict[str, Any]:
        os.makedirs(self.config.state_home, mode=0o700, exist_ok=True)
        payload = {
            "v": annotation_store.SCHEMA_VERSION,
            "entries": [
                {
                    "harness": "codex",
                    "sid": "s-1",
                    "revisions": [{"n": 1, "at": 100.0, "goal": "ship it", "output": ""}],
                    "readings": 1,
                    "assessment": assessment,
                }
            ],
        }
        with open(annotation_store.store_path(self.config), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        entries = annotation_store.load(self.config)
        self.assertEqual(1, len(entries))
        return dict(annotation_store.published(entries[0], binding_why=""))

    def test_a_reading_carrying_a_key_this_build_does_not_know_is_published_as_refused(
        self,
    ) -> None:
        row = self._write({"revision_read": 1, "a_key_from_the_future": True})

        self.assertIsNone(row["assessment"])
        self.assertEqual(1, row["reading_count"])
        self.assertTrue(row["reading_refused"])

    def test_a_session_nobody_pressed_on_is_not_refused(self) -> None:
        row = self._write(None)

        self.assertIsNone(row["assessment"])
        self.assertFalse(row["reading_refused"])

    def test_the_refusal_is_never_written_back_to_disk(self) -> None:
        # It is a fact about this build reading that file, so a build that can
        # read the reading must publish no refusal without anything clearing a
        # stored flag.
        self._write({"revision_read": 1, "a_key_from_the_future": True})
        entries = annotation_store.load(self.config)
        annotation_store.save(self.config, entries, diagnostic_sink=lambda _line: None)

        with open(annotation_store.store_path(self.config), encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertNotIn("refused", written["entries"][0])

    def test_a_reading_carrying_why_is_refused_whole_by_a_build_that_predates_it(self) -> None:
        """DRC-4544 item 3, the downgrade half: what v0.23.0 does with `why`.

        The older build is simulated by its criterion key list. It must refuse
        the reading whole, publish the refusal beside the press count, and
        write the raw reading back untouched so this build reads it again --
        the path `revision_read_at` already takes at the assessment level.
        """
        stored = {
            "revision_read": 1,
            "revision_read_at": 100.0,
            "stamp": "read at 10:00",
            "cutoff": "Read 1 of the 1 entry after your words",
            "scope": runtime_reading.SCOPE_FINAL,
            "scope_text": runtime_reading.SCOPE_TEXT[runtime_reading.SCOPE_FINAL],
            "ended_at_read": 99.0,
            "criteria": {
                "goal": {
                    "result": runtime_reading.RESULT_UNVERIFIABLE,
                    "cites": [],
                    "detail": "",
                    "clause": "ship it",
                    "why": "unreadable",
                },
                "line_1": {
                    "result": runtime_reading.RESULT_UNVERIFIABLE,
                    "cites": [],
                    "detail": "",
                    "clause": "",
                    "why": "not-asked",
                },
            },
        }
        older_build = ("result", "cites", "detail", "clause")
        with mock.patch.object(runtime_reading, "CRITERION_KEYS", older_build):
            row = self._write(stored)
            self.assertIsNone(row["assessment"])
            self.assertTrue(row["reading_refused"])
            self.assertEqual(1, row["reading_count"])
            entries = annotation_store.load(self.config)
            self.assertTrue(annotation_store.save(self.config, entries, diagnostic_sink=print))
        with open(annotation_store.store_path(self.config), encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual(stored, written["entries"][0]["assessment"])
        # This build reads what the older one carried.
        current = self._write(stored)
        self.assertFalse(current["reading_refused"])
        assert current["assessment"] is not None
        self.assertEqual("not-asked", current["assessment"]["criteria"]["line_1"]["why"])


class IntentRevisionTest(unittest.TestCase):
    """The log changes independently of the sessions still on the board."""

    NOW = 1_800_000_000.0

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config, self.state = make_runtime(
            state_home=temporary.name, state_dir=Path(temporary.name), started=self.NOW
        )
        self.now = self.NOW
        self.application = aggregate.Application(
            self.config,
            self.state,
            (),
            native_notifier=lambda _platform: "",
            popup_notifier=lambda _title, _body: None,
            diagnostic_sink=lambda _message: None,
            clock=lambda: self.now,
        )

    def _revision(self) -> str:
        payload = self.application.collect(show_all=False)
        self.assertIn("intent_revision", payload)
        revision = payload["intent_revision"]
        self.assertIsInstance(revision, str)
        self.assertRegex(revision, r"^[a-f0-9]{64}$")
        self.assertEqual([], payload["sessions"])
        return str(revision)

    def _annotate(self, goal: str = "Private goal") -> str:
        return annotation_store.annotate(
            self.config, self.state, "pi", "off-board", goal=goal, now=self.now
        )

    def _check(self) -> None:
        self.assertTrue(
            departures.record(
                self.config,
                [
                    {
                        "harness": "pi",
                        "sid": "off-board",
                        "at": self.NOW,
                        "constraint": "goal",
                        "clause": "Private goal",
                        "reading": "A departure",
                        "evidence": "transcript",
                        "revision": 1,
                        "cutoff": self.NOW,
                        "cutoff_text": "One entry",
                        "withdrawn": False,
                    }
                ],
            )
        )

    def test_time_and_unchanged_saves_do_not_change_the_token(self) -> None:
        self._annotate()
        first = self._revision()
        self.now += 10
        self.assertEqual(first, self._revision())
        self.assertEqual(annotation_store.OUTCOME_UNCHANGED, self._annotate())
        self.assertEqual(first, self._revision())
        self.assertNotIn("Private goal", first)

    def test_off_board_discard_changes_the_token(self) -> None:
        absent = self._revision()
        self._annotate()
        annotated = self._revision()
        self.assertNotEqual(absent, annotated)
        annotation_store.clear(self.config, self.state, "pi", "off-board", now=self.now)
        discarded = self._revision()
        self.assertNotEqual(annotated, discarded)
        self.assertNotEqual(absent, discarded)

    def test_another_process_write_is_seen_at_the_next_collection(self) -> None:
        before = self._revision()
        other = build_runtime_state(self.config, started=self.NOW + 1)
        annotation_store.annotate(
            self.config, other, "pi", "off-board", goal="Written elsewhere", now=self.now
        )
        self.assertNotEqual(before, self._revision())

    def test_departures_and_their_withdrawal_change_the_token(self) -> None:
        self._annotate()
        before = self._revision()
        self._check()
        raised = self._revision()
        self.assertNotEqual(before, raised)
        self.assertTrue(departures.withdraw(self.config, "pi", "off-board"))
        self.assertNotEqual(raised, self._revision())

    def test_daily_cap_expiry_changes_the_token_only_at_the_boundary(self) -> None:
        self.application.config = dataclasses.replace(self.config, unasked_daily_cap=1)
        self._annotate()
        self._check()
        exhausted = self._revision()
        self.now += departures.DAY_SEC
        self.assertEqual(exhausted, self._revision())
        self.now += 1
        expired = self._revision()
        self.assertNotEqual(exhausted, expired)
        self.now += 1
        self.assertEqual(expired, self._revision())

    def test_restart_and_cap_changes_are_distinguishable(self) -> None:
        before = self._revision()
        self.application.state = build_runtime_state(self.config, started=self.NOW + 1)
        restarted = self._revision()
        self.assertNotEqual(before, restarted)
        self.application.config = dataclasses.replace(self.config, unasked_session_cap=99)
        self.assertNotEqual(restarted, self._revision())

    def test_failed_write_does_not_claim_changed_persisted_content(self) -> None:
        self._annotate()
        before = self._revision()
        with mock.patch.object(annotation_store, "save", return_value=False):
            self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, self._annotate("Not saved"))
        self.assertEqual(before, self._revision())

    def test_disabled_annotations_publish_no_token(self) -> None:
        self.application.config = dataclasses.replace(self.config, annotations_enabled=False)
        self.assertNotIn("intent_revision", self.application.collect(show_all=False))

    def test_collection_does_not_read_either_store_again_for_the_token(self) -> None:
        with (
            # The file read itself: `refresh` reads it through `_read_store`,
            # which also says whether it could be read.
            mock.patch.object(
                annotation_store, "_read_store", wraps=annotation_store._read_store
            ) as annotations,
            mock.patch.object(departures, "load", wraps=departures.load) as checks,
        ):
            self._revision()
        annotations.assert_called_once()
        checks.assert_called_once()


if __name__ == "__main__":
    unittest.main()
