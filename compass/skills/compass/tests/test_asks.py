"""The ask registry: one-slot answer mailboxes, budgets, expiry, and shutdown.

Two things here are worth more than the rest of the file. The first is that
`wait` releases its lock: a waiter that held one would freeze every reader of
the registry for the length of a poll, so the test parks a real thread in
`wait` and proves another thread can still read. The second is first-wins
resolution, because a declined ask that could later read as answered would hand
an agent a choice the reader never made.
"""

from __future__ import annotations

import ast
import inspect
import threading
import unittest

from compass_runtime import asks as runtime_asks


def make_ask(
    *,
    question: str = "Ship it?",
    options: tuple[str, ...] = ("yes", "no"),
    created: float = 1000.0,
) -> runtime_asks.PendingAsk:
    return runtime_asks.PendingAsk(
        harness="claude",
        session_id="s1",
        project="compass",
        question=question,
        options=options,
        created=created,
    )


def register(
    registry: runtime_asks.AskRegistry,
    ask: runtime_asks.PendingAsk,
    *,
    limit: int = 4,
    deadline: float = 10_000.0,
    retention: float = 10_000.0,
) -> bool:
    """Register with the sweep effectively switched off.

    The windows are deliberately absurd so that a test which does not care about
    the registration sweep cannot accidentally exercise it. The sweep tests below
    pass their own.
    """
    return registry.register(ask, limit=limit, deadline=deadline, retention=retention)


def pending(
    registry: runtime_asks.AskRegistry,
    *,
    now: float,
    deadline: float,
    retention: float = 10_000.0,
) -> list[runtime_asks.PendingAsk]:
    """Collect the cards, with retention effectively switched off by default."""
    return registry.pending(now=now, deadline=deadline, retention=retention)


class LayeringTest(unittest.TestCase):
    def test_asks_imports_nothing_from_the_runtime(self) -> None:
        """The layering rule that lets `state` own the registry without a cycle.

        `test_contracts` asserts the whole import graph; this asserts the one
        edge that would break if someone reached for `records.safe_text`.
        """
        tree = ast.parse(inspect.getsource(runtime_asks))
        named: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                named.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                named.append(node.module or "." * node.level)
        self.assertEqual([], [name for name in named if "compass" in name or name.startswith(".")])


class PendingAskTest(unittest.TestCase):
    def test_every_ask_gets_its_own_generated_id(self) -> None:
        first, second = make_ask(), make_ask()
        self.assertTrue(first.id)
        self.assertNotEqual(first.id, second.id)

    def test_options_are_stored_as_a_tuple_whatever_the_caller_hands_over(self) -> None:
        ask = runtime_asks.PendingAsk(
            harness="codex",
            session_id="",
            project="",
            question="Which?",
            options=["a", "b"],
            created=1.0,
        )
        self.assertEqual(("a", "b"), ask.options)

    def test_a_fresh_ask_is_unresolved_and_wait_times_out_to_none(self) -> None:
        ask = make_ask()
        self.assertFalse(ask.resolved)
        self.assertIsNone(ask.outcome)
        self.assertIsNone(ask.wait(timeout=0.01))

    def test_resolve_records_the_index_and_wait_returns_it(self) -> None:
        ask = make_ask()
        self.assertTrue(ask.resolve(1))
        self.assertTrue(ask.resolved)
        self.assertEqual(("answered", 1), ask.outcome)
        self.assertEqual(("answered", 1), ask.wait(timeout=0.01))

    def test_resolve_rejects_an_out_of_range_index_without_resolving(self) -> None:
        # Negative included: a bare `index < len(options)` check would accept -1
        # and hand the agent options[-1], which is the wrong option rather than
        # a refusal.
        for index in (-1, -2, 2, 99):
            ask = make_ask()
            self.assertFalse(ask.resolve(index), f"index {index} must be refused")
            self.assertFalse(ask.resolved)
            self.assertIsNone(ask.outcome)

    def test_resolve_on_an_ask_with_no_options_is_always_refused(self) -> None:
        ask = make_ask(options=())
        self.assertFalse(ask.resolve(0))
        self.assertIsNone(ask.outcome)

    def test_resolve_is_idempotent_and_first_wins(self) -> None:
        ask = make_ask()
        self.assertTrue(ask.resolve(0))
        self.assertFalse(ask.resolve(1))
        self.assertEqual(("answered", 0), ask.outcome)

    def test_a_declined_ask_can_never_later_read_as_answered(self) -> None:
        ask = make_ask()
        ask.decline()
        ask.decline()
        self.assertFalse(ask.resolve(0))
        self.assertEqual(("declined", None), ask.outcome)

    def test_an_expired_ask_can_never_later_read_as_answered_or_declined(self) -> None:
        ask = make_ask()
        ask.expire()
        ask.expire()
        ask.decline()
        self.assertFalse(ask.resolve(1))
        self.assertEqual(("expired", None), ask.outcome)

    def test_an_answered_ask_stays_answered_through_decline_and_expire(self) -> None:
        ask = make_ask()
        self.assertTrue(ask.resolve(1))
        ask.decline()
        ask.expire()
        self.assertEqual(("answered", 1), ask.outcome)

    def test_resolve_wakes_a_parked_waiter(self) -> None:
        ask = make_ask()
        seen: list[runtime_asks.Outcome | None] = []
        parked = threading.Event()

        def waiter() -> None:
            parked.set()
            seen.append(ask.wait(timeout=30.0))

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        self.assertTrue(parked.wait(timeout=30.0))
        ask.resolve(0)
        thread.join(timeout=30.0)
        self.assertEqual([("answered", 0)], seen)

    def test_wait_releases_the_lock_so_the_registry_stays_readable(self) -> None:
        """A waiter holding its lock across the wait would freeze the dashboard.

        The reader runs on its own thread so a regression fails the assertion at
        its bound rather than blocking until the waiter's own timeout and then
        passing. The reader's bound must stay below the waiter's for that to hold.
        """
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        self.assertTrue(register(registry, ask, limit=4))
        parked = threading.Event()
        read = threading.Event()

        def waiter() -> None:
            parked.set()
            ask.wait(timeout=60.0)

        def reader() -> None:
            # Both touch the ask's own condition lock, which is what `wait` must
            # have released.
            if (
                registry.count == 1
                and not ask.resolved
                and pending(registry, now=1000.0, deadline=60.0)
            ):
                read.set()

        waiting = threading.Thread(target=waiter, daemon=True)
        waiting.start()
        self.assertTrue(parked.wait(timeout=30.0))
        reading = threading.Thread(target=reader, daemon=True)
        reading.start()
        self.assertTrue(read.wait(timeout=30.0), "a held ask lock froze the registry readers")
        ask.decline()
        waiting.join(timeout=30.0)
        reading.join(timeout=30.0)


class AskRegistryTest(unittest.TestCase):
    def test_register_stores_the_ask_and_counts_it(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        self.assertTrue(register(registry, ask, limit=2))
        self.assertEqual(1, registry.count)
        self.assertIs(ask, registry.get(ask.id))

    def test_register_past_the_budget_returns_false_and_stores_nothing(self) -> None:
        registry = runtime_asks.AskRegistry()
        self.assertTrue(register(registry, make_ask(), limit=1))
        refused = make_ask()
        self.assertFalse(register(registry, refused, limit=1), "the budget must be a hard cap")
        self.assertEqual(1, registry.count)
        self.assertIsNone(registry.get(refused.id))

    def test_get_of_an_unknown_id_is_none(self) -> None:
        self.assertIsNone(runtime_asks.AskRegistry().get("nope"))

    def test_release_frees_a_slot(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=1)
        registry.release(ask.id)
        self.assertEqual(0, registry.count)
        self.assertIsNone(registry.get(ask.id))
        self.assertTrue(register(registry, make_ask(), limit=1))

    def test_release_of_an_unknown_id_is_a_no_op(self) -> None:
        runtime_asks.AskRegistry().release("nope")

    def test_answer_resolves_the_named_ask(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=2)
        self.assertTrue(registry.answer(ask.id, 1))
        self.assertEqual(("answered", 1), ask.wait(timeout=0.01))

    def test_answer_refuses_an_unknown_id(self) -> None:
        self.assertFalse(runtime_asks.AskRegistry().answer("nope", 0))

    def test_answer_refuses_an_out_of_range_index(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=2)
        self.assertFalse(registry.answer(ask.id, 7))
        self.assertFalse(ask.resolved)

    def test_answer_refuses_a_second_answer(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=2)
        self.assertTrue(registry.answer(ask.id, 0))
        self.assertFalse(registry.answer(ask.id, 1))
        self.assertEqual(("answered", 0), ask.outcome)

    def test_pending_expires_what_is_older_than_the_deadline_and_returns_the_rest(self) -> None:
        registry = runtime_asks.AskRegistry()
        stale = make_ask(question="old", created=100.0)
        fresh = make_ask(question="new", created=990.0)
        register(registry, stale, limit=4)
        register(registry, fresh, limit=4)
        self.assertEqual([fresh], pending(registry, now=1000.0, deadline=300.0))
        self.assertEqual(("expired", None), stale.outcome)
        self.assertIsNone(registry.get(stale.id), "an expired ask is dropped, not kept")
        self.assertEqual(1, registry.count)

    def test_pending_returns_oldest_first(self) -> None:
        registry = runtime_asks.AskRegistry()
        second = make_ask(created=1000.0)
        first = make_ask(created=999.0)
        register(registry, second, limit=4)
        register(registry, first, limit=4)
        self.assertEqual([first, second], pending(registry, now=1000.0, deadline=300.0))

    def test_pending_omits_an_ask_that_already_has_an_outcome(self) -> None:
        # It is still stored, because its poller has not collected the answer
        # yet, but a resolved ask rendered as a card offers a choice that has
        # already been made.
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=4)
        registry.answer(ask.id, 0)
        self.assertEqual([], pending(registry, now=1000.0, deadline=300.0))
        self.assertIs(ask, registry.get(ask.id))

    def test_pending_expiry_is_exclusive_at_the_deadline(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask(created=700.0)
        register(registry, ask, limit=4)
        self.assertEqual([ask], pending(registry, now=1000.0, deadline=300.0))
        self.assertEqual([], pending(registry, now=1000.1, deadline=300.0))

    def test_decline_all_wakes_a_parked_waiter(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=4)
        seen: list[runtime_asks.Outcome | None] = []
        parked = threading.Event()

        def waiter() -> None:
            parked.set()
            seen.append(ask.wait(timeout=30.0))

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        self.assertTrue(parked.wait(timeout=30.0))
        registry.decline_all()
        thread.join(timeout=30.0)
        self.assertEqual([("declined", None)], seen)
        self.assertEqual(0, registry.count)

    def test_decline_all_with_no_asks_is_a_no_op(self) -> None:
        runtime_asks.AskRegistry().decline_all()


class SelfMaintainingTest(unittest.TestCase):
    """The table has to heal itself with nobody reading it.

    Every sweep used to ride on `pending`, whose only caller is a collection,
    and a collection happens only when the coordinator has a dirty generation or
    a connected browser tab. So on the path the ask lane exists for -- a long
    autonomous run with no tab open -- nothing ever expired an ask, nothing ever
    released an answered one, and the budget filled with outcomes nobody had
    collected. Measured on the branch this fixes: after filling a cap of 16 and
    answering 14, registration was refused at t+10s, t+321s and t+341s while the
    payload reported zero cards.

    Nothing in this class calls `pending`. That is the point of it.
    """

    def test_a_table_full_of_answered_asks_still_accepts_a_registration(self) -> None:
        registry = runtime_asks.AskRegistry()
        limit = 16
        filled = [make_ask(created=1000.0) for _ in range(limit)]
        for ask in filled:
            self.assertTrue(register(registry, ask, limit=limit))
        for ask in filled[:14]:
            self.assertTrue(registry.answer(ask.id, 0))

        self.assertTrue(
            registry.register(
                make_ask(created=1010.0), limit=limit, deadline=300.0, retention=60.0
            ),
            "an answered ask holds no slot worth rationing",
        )

    def test_registration_expires_the_overdue_before_it_checks_the_budget(self) -> None:
        registry = runtime_asks.AskRegistry()
        overdue = [make_ask(created=1000.0) for _ in range(2)]
        for ask in overdue:
            self.assertTrue(register(registry, ask, limit=2))

        fresh = make_ask(created=1400.0)
        self.assertTrue(registry.register(fresh, limit=2, deadline=300.0, retention=60.0))
        for ask in overdue:
            self.assertEqual(("expired", None), ask.outcome)
            self.assertIsNone(registry.get(ask.id))
        self.assertEqual(1, registry.count)

    def test_a_budget_full_of_live_questions_is_still_a_hard_cap(self) -> None:
        # The other half of the fix. Sweeping on registration must not turn the
        # cap into a suggestion: two questions nobody has answered and nobody
        # has abandoned are two cards on the page, and the honest answer to a
        # third is still a refusal.
        registry = runtime_asks.AskRegistry()
        for _ in range(2):
            self.assertTrue(register(registry, make_ask(created=1000.0), limit=2))
        refused = make_ask(created=1010.0)
        self.assertFalse(registry.register(refused, limit=2, deadline=300.0, retention=60.0))
        self.assertIsNone(registry.get(refused.id))

    def test_count_is_how_many_asks_still_need_a_slot(self) -> None:
        registry = runtime_asks.AskRegistry()
        answered, live = make_ask(), make_ask()
        register(registry, answered, limit=4)
        register(registry, live, limit=4)
        self.assertEqual(2, registry.count)
        self.assertTrue(registry.answer(answered.id, 0))
        self.assertEqual(1, registry.count, "count means unresolved, not stored")
        self.assertIs(answered, registry.get(answered.id), "its poller has not collected yet")

    def test_an_answered_ask_survives_the_sweep_that_would_have_expired_it(self) -> None:
        # The 0.35-second hole. The answer landed at t=299.7 against a
        # 300-second deadline, the next sweep ran at t=300.05, and the ask was
        # deleted before its poller ever woke -- so the agent was told nobody
        # answered a question a reader had answered a third of a second earlier.
        registry = runtime_asks.AskRegistry()
        ask = make_ask(created=0.0)
        register(registry, ask, limit=4)
        self.assertTrue(registry.answer(ask.id, 1))

        self.assertEqual([], pending(registry, now=300.05, deadline=300.0, retention=60.0))
        self.assertIs(ask, registry.get(ask.id))
        self.assertEqual(("answered", 1), ask.outcome)

    def test_a_resolved_ask_is_dropped_once_its_retention_runs_out(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask(created=0.0)
        register(registry, ask, limit=4)
        self.assertTrue(registry.answer(ask.id, 0))

        # The first sweep to see the outcome is what starts the window: the ask
        # itself has no clock of its own to stamp a resolution with.
        self.assertEqual([], pending(registry, now=10.0, deadline=300.0, retention=60.0))
        self.assertIs(ask, registry.get(ask.id))
        self.assertEqual([], pending(registry, now=70.0, deadline=300.0, retention=60.0))
        self.assertIs(ask, registry.get(ask.id), "60 seconds is not yet past 60 seconds")
        self.assertEqual([], pending(registry, now=70.1, deadline=300.0, retention=60.0))
        self.assertIsNone(registry.get(ask.id))
        self.assertEqual(("answered", 0), ask.outcome, "the outcome outlives the row")

    def test_registration_reclaims_a_resolved_ask_past_retention(self) -> None:
        registry = runtime_asks.AskRegistry()
        gone = make_ask(created=0.0)
        register(registry, gone, limit=1)
        self.assertTrue(registry.answer(gone.id, 0))
        # Two registrations, because the first is what stamps the outcome.
        self.assertFalse(
            registry.register(make_ask(created=1.0), limit=0, deadline=300.0, retention=60.0)
        )
        self.assertTrue(
            registry.register(make_ask(created=100.0), limit=1, deadline=300.0, retention=60.0)
        )
        self.assertIsNone(registry.get(gone.id))


class WithdrawTest(unittest.TestCase):
    def test_withdraw_declines_the_ask_and_frees_its_slot(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=1)
        self.assertTrue(registry.withdraw(ask.id))
        self.assertEqual(("declined", None), ask.outcome)
        self.assertIsNone(registry.get(ask.id))
        self.assertEqual(0, registry.count)

    def test_withdraw_of_an_unknown_id_is_false_and_changes_nothing(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=2)
        self.assertFalse(registry.withdraw("nope"))
        self.assertEqual(1, registry.count)

    def test_withdraw_is_not_a_second_answer(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=2)
        self.assertTrue(registry.answer(ask.id, 1))
        self.assertTrue(registry.withdraw(ask.id), "the row goes either way")
        self.assertEqual(("answered", 1), ask.outcome)

    def test_withdraw_wakes_a_parked_waiter(self) -> None:
        registry = runtime_asks.AskRegistry()
        ask = make_ask()
        register(registry, ask, limit=2)
        seen: list[runtime_asks.Outcome | None] = []
        parked = threading.Event()

        def waiter() -> None:
            parked.set()
            seen.append(ask.wait(timeout=30.0))

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        self.assertTrue(parked.wait(timeout=30.0))
        self.assertTrue(registry.withdraw(ask.id))
        thread.join(timeout=30.0)
        self.assertEqual([("declined", None)], seen)


if __name__ == "__main__":
    unittest.main()
