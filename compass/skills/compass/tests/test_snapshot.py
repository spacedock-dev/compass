"""The published dashboard snapshot: revisions, variants, and staleness."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import snapshot as runtime_snapshot
from compass_runtime.config import COMPASS_HOME_ENV

from . import fixtures, support


class SnapshotTest(unittest.TestCase):
    def _snap(self, started: float = 1000.0) -> runtime_snapshot.Snapshot:
        return runtime_snapshot.Snapshot(server_started=started)

    def test_publishing_returns_a_monotonic_counter(self) -> None:
        snap = self._snap()
        first = snap.publish((24.0, False), b'{"a":1}')[0]
        second = snap.publish((24.0, False), b'{"a":2}')[0]
        self.assertEqual(first[1] + 1, second[1])

    def test_the_counter_is_shared_across_keys_so_it_orders_the_whole_process(self) -> None:
        # A client holds one cursor, not one per variant, so a per-key counter
        # would let ?all=1 and the default view report the same number for
        # different states.
        snap = self._snap()
        a = snap.publish((24.0, False), b"{}")[0]
        b = snap.publish((24.0, True), b"{}")[0]
        self.assertNotEqual(a[1], b[1])

    def test_the_revision_carries_the_server_start_stamp(self) -> None:
        snap = self._snap(started=1234.5)
        self.assertIsNone(snap.current((24.0, False)))
        published = snap.publish((24.0, False), b"{}")[0]
        self.assertEqual(published[0], 1234.5)

    def test_current_returns_the_published_bytes_and_its_revision(self) -> None:
        snap = self._snap()
        rev = snap.publish((24.0, False), b'{"x":1}')[0]
        got = snap.current((24.0, False))
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got, (rev, b'{"x":1}'))

    def test_an_unpublished_key_is_absent_rather_than_empty(self) -> None:
        self.assertIsNone(self._snap().current((24.0, True)))

    def test_age_measures_from_the_publish_clock(self) -> None:
        snap = self._snap()
        snap.publish((24.0, False), b"{}", now=500.0)
        age = snap.age((24.0, False), now=502.5)
        self.assertIsNotNone(age)
        assert age is not None
        self.assertAlmostEqual(age, 2.5)

    def test_age_of_an_unpublished_key_is_none_not_zero(self) -> None:
        # Zero would read as "fresh" and skip the collection a cold GET needs.
        self.assertIsNone(self._snap().age((24.0, False), now=1.0))

    def test_clear_drops_every_variant_so_the_next_read_collects(self) -> None:
        snap = self._snap()
        snap.publish((24.0, False), b"{}", now=1.0)
        snap.publish((24.0, True), b"{}", now=1.0)
        snap.clear()
        self.assertIsNone(snap.current((24.0, False)))
        self.assertIsNone(snap.current((24.0, True)))
        self.assertIsNone(snap.age((24.0, False), now=1.0))

    def test_clear_does_not_rewind_the_revision_counter(self) -> None:
        # A cleared snapshot must still mint a strictly higher revision, or a
        # client holding a cursor would ignore the state that follows a reset.
        snap = self._snap()
        before = snap.publish((24.0, False), b"{}")[0]
        snap.clear()
        after = snap.publish((24.0, False), b"{}")[0]
        self.assertGreater(after[1], before[1])

    def test_a_body_collected_across_a_clear_is_answered_but_not_kept(self) -> None:
        snap = self._snap()
        before = snap.generation()
        snap.clear()
        late, dropped = snap.publish((24.0, False), b'{"old":1}', now=1.0, generation=before)
        self.assertFalse(dropped)
        self.assertIsNone(snap.current((24.0, False)))
        kept, stored = snap.publish(
            (24.0, False), b'{"new":1}', now=1.0, generation=snap.generation()
        )
        self.assertTrue(stored)
        self.assertGreater(kept[1], late[1])
        self.assertEqual(snap.current((24.0, False)), (kept, b'{"new":1}'))

    def test_format_revision_is_stable_and_restart_qualified(self) -> None:
        self.assertEqual(runtime_snapshot.format_revision((1700000000.0, 7)), "1700000000.7")

    def test_two_snapshots_with_different_starts_never_collide(self) -> None:
        # The whole point of the pair: a tab holding revision 512 from a previous
        # process must not treat the new process's revision 3 as older.
        a = self._snap(started=1000.0).publish((24.0, False), b"{}")[0]
        b = self._snap(started=2000.0).publish((24.0, False), b"{}")[0]
        self.assertEqual(a[1], b[1])
        self.assertNotEqual(a, b)


class ApplicationSnapshotTest(support.RuntimeTestCase):
    """collect_json publishes, reuses inside the floor, and recollects after it."""

    def test_a_second_call_inside_the_floor_reuses_the_published_bytes(self) -> None:
        app = support.build_app()
        calls: list[int] = []
        real = app.collect

        def counting(*, show_all: bool, notify: bool = True) -> dict[str, object]:
            calls.append(1)
            return real(show_all=show_all, notify=notify)

        app.collect = counting  # type: ignore[method-assign]
        first_rev, first_body = app.collect_json(show_all=False)
        second_rev, second_body = app.collect_json(show_all=False)
        self.assertEqual(len(calls), 1, "the second call must not recollect")
        self.assertEqual(first_body, second_body)
        self.assertEqual(first_rev, second_rev, "reuse must not mint a revision")

    def test_the_two_variants_are_published_separately(self) -> None:
        app = support.build_app()
        default_rev, _ = app.collect_json(show_all=False)
        all_rev, _ = app.collect_json(show_all=True)
        self.assertNotEqual(default_rev, all_rev)
        self.assertIsNotNone(app.snapshot.current((app.config.window_hours, False)))
        self.assertIsNotNone(app.snapshot.current((app.config.window_hours, True)))

    def test_the_payload_is_unchanged_apart_from_its_generated_stamp(self) -> None:
        """The snapshot is a delivery change, not a payload change.

        Verified byte-for-byte against the pre-snapshot branch by hand as well;
        this keeps the guarantee in the suite so a later change cannot drift it.

        Two collections, not two applications, and both over a seeded fixture
        store on a pinned clock. Reading the developer's real store is what made
        this flake (DRC-4088): a session generating in another window moves
        `rate_per_min` and every other time-derived field between the two
        collections, and the payloads then differ for a reason that has nothing
        to do with the snapshot. CI never saw it because a runner's store is
        empty — which is also the trap the assertion below guards, since an
        override that misses reads an empty store and the comparison passes
        having compared nothing.

        The clock is pinned as well as the store. A fixture store alone leaves
        `now - mtime` to be evaluated twice milliseconds apart, which is a
        rounding boundary away from the same flake at a much lower rate.
        """
        pinned = support.SERVER_STARTED + 300.0
        with tempfile.TemporaryDirectory() as tmp:
            seeded = fixtures.build_claude(
                Path(tmp), pinned - 120.0, "5eeded00-1111-2222-3333-444444444444", "seeded session"
            )
            with support.store_patch(**seeded):
                app = support.build_app()
                app.clock = lambda: pinned
                _first_rev, first_body = app.collect_json(show_all=False)
                app.snapshot.clear()
                _second_rev, second_body = app.collect_json(show_all=False)

        first = json.loads(first_body)
        second = json.loads(second_body)
        self.assertEqual(
            [x["sid"] for x in first["sessions"]],
            ["5eeded00"],
            "the fixture store was not the one collected, so the comparison proves nothing",
        )
        first.pop("generated", None)
        second.pop("generated", None)
        self.assertEqual(first, second)

    def test_a_reader_who_saves_mid_collection_gets_the_saved_words_back_at_once(self) -> None:
        """DRC-4760. The save's own refresh must not be answered with words it replaced.

        A collection reads the annotation store near its start and publishes
        at its end, seconds later on a real board. `/api/annotate` drops the
        snapshot after its write, but a collection already past the store
        read published the pre-save words over that drop with a fresh stamp,
        so the page's refresh straight after the confirmed save was served
        them for the whole freshness floor and the reader waited for the next
        poll (6.6 s measured on the DRC-4719 walk).
        """
        pinned = support.SERVER_STARTED + 300.0
        with tempfile.TemporaryDirectory() as tmp:
            seeded = fixtures.build_claude(
                Path(tmp), pinned - 120.0, "5eeded00-1111-2222-3333-444444444444", "seeded session"
            )
            home = Path(tmp) / "home"
            home.mkdir()
            with (
                support.store_patch(**seeded),
                mock.patch.dict(os.environ, {COMPASS_HOME_ENV: str(home)}),
            ):
                app = support.build_app()
                app.clock = lambda: pinned
                row = json.loads(app.collect_json(show_all=False)[1])["sessions"][0]
                harness, sid = row["harness"], row["sid"]

                def save(goal: str) -> None:
                    # What `_annotate` does: write, then drop the snapshot.
                    annotation_store.annotate(
                        app.config, app.state, harness, sid, goal=goal, now=pinned
                    )
                    app.snapshot.clear()

                save("First words")
                # The harness scan is the window the save lands in: after the
                # store read, before the publish.
                real = app._collect_harnesses

                def collecting_while_the_reader_saves(*args: Any) -> Any:
                    save("Second words")
                    return real(*args)

                with mock.patch.object(
                    app, "_collect_harnesses", side_effect=collecting_while_the_reader_saves
                ):
                    app.collect_json(show_all=False)
                after = json.loads(app.collect_json(show_all=False)[1])["sessions"][0]

        self.assertEqual(after["annotation_goal"], "Second words")
        self.assertEqual(after["annotation_revision"], 2)

    def test_a_saves_collection_does_not_wake_other_tabs_for_a_body_it_never_kept(self) -> None:
        """A body collected across a clear is never served again, so it is not announced.

        Announced, every connected tab fetched once for it and was served the
        next collection instead, which is the second and third GET of the
        owner's one save (2026-10-02). The next kept collection announces.
        """
        app = support.build_app()
        woken: list[Any] = []
        real = app._collect_harnesses

        def cleared_mid_collection(*args: Any) -> Any:
            app.snapshot.clear()
            return real(*args)

        with mock.patch.object(app.state.streams, "publish", side_effect=woken.append):
            with mock.patch.object(app, "_collect_harnesses", side_effect=cleared_mid_collection):
                app.collect_json(show_all=False)
            self.assertEqual([], woken)
            kept, _body = app.collect_json(show_all=False)
        self.assertEqual([kept], woken)

    def test_a_stale_snapshot_recollects_and_mints_a_new_revision(self) -> None:
        app = support.build_app()
        first_rev, _ = app.collect_json(show_all=False)
        # Advance past the floor rather than sleeping: the clock is injected.
        base = app.clock()
        app.clock = lambda: base + app.config.collect_memo_sec + 1
        second_rev, _ = app.collect_json(show_all=False)
        self.assertGreater(second_rev[1], first_rev[1])

    def test_a_snapshot_dated_in_the_future_does_not_block_collection(self) -> None:
        app = support.build_app()
        base = app.clock()
        first_rev, _ = app.collect_json(show_all=False)
        app.clock = lambda: base + app.config.collect_memo_sec - 12
        second_rev, _ = app.collect_json(show_all=False)
        self.assertGreater(second_rev[1], first_rev[1])

    def test_elapsed_snapshot_age_stays_bounded_after_wall_clock_catches_up(self) -> None:
        app = support.build_app()
        base = app.clock()
        wall, elapsed = base, 0.0
        app.clock = lambda: wall
        app.monotonic = lambda: elapsed
        first = app.collect_json(show_all=False)

        wall, elapsed = base + 1, 13.0
        key = (app.config.window_hours, False)
        self.assertEqual(1.0, app.snapshot.age(key, now=wall))
        new = app.collect_json(show_all=False)
        self.assertGreater(new[0][1], first[0][1])
        self.assertEqual(first[0][0], new[0][0])
        self.assertEqual(0.0, app.snapshot.age(key, now=wall))
        wall += 1
        elapsed += 1
        self.assertEqual(new, app.collect_json(show_all=False))


if __name__ == "__main__":
    unittest.main()
