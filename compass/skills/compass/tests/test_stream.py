"""The SSE client registry: one-slot mailboxes, budgets, and shutdown."""

from __future__ import annotations

import threading
import unittest

from compass_runtime import snapshot as runtime_snapshot
from compass_runtime import stream as runtime_stream

from . import support

# How long the test waits for a wake that happens at once; the waiter's own timeout is longer,
# so a close that did not wake it fails the wait instead of the timeout waking it.
WAIT_SEC = 30.0


class StreamClientTest(unittest.TestCase):
    def test_wait_returns_the_offered_revision(self) -> None:
        client = runtime_stream.StreamClient()
        client.offer((1000.0, 5))
        self.assertEqual((1000.0, 5), client.wait(timeout=0.01))

    def test_wait_times_out_to_none_so_the_caller_can_heartbeat(self) -> None:
        self.assertIsNone(runtime_stream.StreamClient().wait(timeout=0.01))

    def test_the_mailbox_holds_one_slot_and_keeps_the_newest(self) -> None:
        # A slow reader falls behind by skipping revisions, never by growing a
        # backlog. The client refetches the whole payload, so only the newest
        # revision is worth delivering.
        client = runtime_stream.StreamClient()
        client.offer((1000.0, 1))
        client.offer((1000.0, 2))
        client.offer((1000.0, 3))
        self.assertEqual((1000.0, 3), client.wait(timeout=0.01))
        self.assertIsNone(client.wait(timeout=0.01))

    def test_close_wakes_a_waiter_and_marks_the_client_closed(self) -> None:
        client = runtime_stream.StreamClient()
        woke = threading.Event()

        def waiter() -> None:
            client.wait(timeout=2 * WAIT_SEC)
            woke.set()

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        client.close()
        self.assertTrue(woke.wait(timeout=WAIT_SEC), "close must wake a blocked waiter")
        self.assertTrue(client.closed)
        thread.join(timeout=2.0)


class StreamRegistryTest(unittest.TestCase):
    def test_register_returns_a_client_and_counts_it(self) -> None:
        registry = runtime_stream.StreamRegistry()
        client = registry.register(limit=2)
        self.assertIsNotNone(client)
        self.assertEqual(1, registry.count)

    def test_register_refuses_past_the_budget(self) -> None:
        registry = runtime_stream.StreamRegistry()
        self.assertIsNotNone(registry.register(limit=1))
        self.assertIsNone(registry.register(limit=1), "the budget must be a hard cap")
        self.assertEqual(1, registry.count)

    def test_release_frees_a_slot(self) -> None:
        registry = runtime_stream.StreamRegistry()
        first = registry.register(limit=1)
        assert first is not None
        registry.release(first)
        self.assertEqual(0, registry.count)
        self.assertIsNotNone(registry.register(limit=1))

    def test_publish_reaches_every_registered_client(self) -> None:
        registry = runtime_stream.StreamRegistry()
        a = registry.register(limit=4)
        b = registry.register(limit=4)
        assert a is not None and b is not None
        registry.publish((1000.0, 9))
        self.assertEqual((1000.0, 9), a.wait(timeout=0.01))
        self.assertEqual((1000.0, 9), b.wait(timeout=0.01))

    def test_publish_with_no_clients_is_a_no_op(self) -> None:
        runtime_stream.StreamRegistry().publish((1000.0, 1))

    def test_close_all_closes_every_client_and_empties_the_registry(self) -> None:
        registry = runtime_stream.StreamRegistry()
        client = registry.register(limit=4)
        assert client is not None
        registry.close_all()
        self.assertTrue(client.closed)
        self.assertEqual(0, registry.count)

    def test_a_released_client_stops_receiving(self) -> None:
        registry = runtime_stream.StreamRegistry()
        client = registry.register(limit=4)
        assert client is not None
        registry.release(client)
        registry.publish((1000.0, 2))
        self.assertIsNone(client.wait(timeout=0.01))


class RevisionShapeTest(unittest.TestCase):
    def test_the_stream_revision_matches_the_snapshot_revision(self) -> None:
        """stream.py deliberately does not import snapshot, so pin the shape."""
        self.assertEqual(runtime_snapshot.Revision, runtime_stream.Revision)


class PublishNotifiesStreamsTest(support.RuntimeTestCase):
    def test_a_fresh_collection_reaches_a_connected_client(self) -> None:
        app = support.build_app()
        client = app.state.streams.register(limit=4)
        assert client is not None
        revision, _body = app.collect_json(show_all=False)
        self.assertEqual(revision, client.wait(timeout=0.01))

    def test_a_reused_snapshot_does_not_wake_a_client(self) -> None:
        # Nothing changed, so there is nothing to tell a client about. Waking it
        # would make every warm GET cost every stream a needless refetch.
        app = support.build_app()
        app.collect_json(show_all=False)
        client = app.state.streams.register(limit=4)
        assert client is not None
        app.collect_json(show_all=False)
        self.assertIsNone(client.wait(timeout=0.01))


if __name__ == "__main__":
    unittest.main()
