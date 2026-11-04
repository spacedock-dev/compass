"""Native preparation shares the source account and refuses before model construction."""

from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest import mock

from compass_runtime import (
    reading,
    reading_long_diagnostics,
    reading_map_series,
    reading_native,
    reading_pass_types,
    reading_passes,
    reading_preparation,
    reading_reconcile_packet,
    reading_source_collect,
)

from . import test_reading_native as native_tests

if TYPE_CHECKING:
    from collections.abc import Callable


class PreparationBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = native_tests.NativeProducerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare()
        snapshot = self.fixture.collection.snapshot
        assert snapshot is not None
        self.snapshot = snapshot
        self.plan = deepcopy(self.fixture.fixture.marker.declared)
        self.clock = [10.0]

    def budget(self, clock: Callable[[], float] | None = None) -> reading_preparation.Budget:
        return reading_preparation.Budget(
            self.snapshot, self.plan, clock=clock or (lambda: self.clock[0])
        )

    def boundary(self) -> reading_native.CallPreparation:
        f = self.fixture
        return reading_native.prepare_calls(
            config=f.fixture.source.config,
            row=f.row,
            revisions=[f.revision],
            collection=f.collection,
            route=f.route,
            now=f.row["ended_at"] + 60,
            plan=self.plan,
        )

    def assert_released_and_exhausted(self) -> None:
        self.assertTrue(self.snapshot.account.lock.acquire(blocking=False))
        self.snapshot.account.lock.release()
        with self.assertRaises(reading_preparation.LimitError), self.budget().stage():
            self.fail("A fresh wrapper must not restore refused allowance")
        checked = reading_source_collect.revalidate(self.snapshot, clock=lambda: 100.0)
        self.assertIsNone(checked.snapshot)

    def test_shared_elapsed_and_retained_graph_survive_fresh_wrapper(self) -> None:
        budget = self.budget()
        before = self.snapshot.account.usage
        with budget.stage() as stage:
            prepared = self.fixture.call_prepare()
            self.clock[0] += 0.03
            stage.keep(prepared)
        self.assertAlmostEqual(before.prepare_ms + 30, self.snapshot.account.usage.prepare_ms)
        self.assertGreater(self.snapshot.account.retained_base_bytes, before.retained_bytes)
        prior = self.snapshot.account.usage
        with self.budget().stage() as stage:
            stage.keep(prepared)
            self.clock[0] += 0.02
        self.assertAlmostEqual(prior.prepare_ms + 20, self.snapshot.account.usage.prepare_ms)
        self.assertGreaterEqual(self.snapshot.account.usage.retained_bytes, prior.retained_bytes)

    def test_cumulative_time_limit_is_visible_to_source_revalidation(self) -> None:
        self.plan["limits"]["prepare_ms"] = 20
        with self.assertRaises(reading_preparation.LimitError) as caught, self.budget().stage():
            self.clock[0] += 0.03
        self.assertEqual("prepare-time", caught.exception.reason)
        self.assert_released_and_exhausted()

    def test_graph_limit_charges_known_elapsed_and_cannot_reset(self) -> None:
        budget = self.budget()
        self.snapshot.account.limits = replace(
            self.snapshot.account.limits,
            retained_bytes=self.snapshot.account.retained_base_bytes + 100,
        )
        before = self.snapshot.account.usage
        with self.assertRaises(reading_preparation.LimitError) as caught, budget.stage() as stage:
            self.clock[0] += 0.02
            stage.keep("x" * 10000)
        self.assertEqual("retained-bytes", caught.exception.reason)
        self.assertAlmostEqual(before.prepare_ms + 20, self.snapshot.account.usage.prepare_ms)
        self.assertEqual(before.source_bytes, self.snapshot.account.usage.source_bytes)
        self.assert_released_and_exhausted()

    def test_body_exception_still_charges_elapsed_and_releases_lock(self) -> None:
        before = self.snapshot.account.usage.prepare_ms
        with self.assertRaisesRegex(OSError, "body failed"), self.budget().stage():
            self.clock[0] += 0.02
            raise OSError("body failed")
        self.assertAlmostEqual(before + 20, self.snapshot.account.usage.prepare_ms)
        with self.budget().stage():
            self.clock[0] += 0.01
        self.assertAlmostEqual(before + 30, self.snapshot.account.usage.prepare_ms)

    def test_start_clock_exception_never_holds_lock_or_grants_fresh_time(self) -> None:
        def broken() -> float:
            raise OSError("private clock detail")

        with (
            self.assertRaises(reading_preparation.LimitError) as caught,
            self.budget(broken).stage(),
        ):
            self.fail("Invalid clock must refuse the stage")
        self.assertEqual("prepare-clock-invalid", caught.exception.reason)
        self.assertNotIn("private clock detail", str(caught.exception))
        self.assert_released_and_exhausted()

    def test_end_clock_exception_and_backward_or_nonfinite_clock_fail_closed(self) -> None:
        for value in (float("nan"), float("inf"), 9.0, True, "invalid", OSError("clock")):
            with self.subTest(value=value):
                # Independent source accounts, rather than resetting any consumed budget.
                self.fixture.prepare()
                snapshot = self.fixture.collection.snapshot
                assert snapshot is not None
                self.snapshot = snapshot
                budget = self.budget()
                budget.clock = mock.Mock(side_effect=[10.0, value])
                with self.assertRaises(reading_preparation.LimitError), budget.stage():
                    pass
                self.assert_released_and_exhausted()

    def test_unexpected_graph_measurement_failure_charges_elapsed_and_poison_is_shared(
        self,
    ) -> None:
        before = self.snapshot.account.usage.prepare_ms
        budget = self.budget()
        with (
            mock.patch.object(
                reading_source_collect, "_measure", side_effect=OSError("private graph detail")
            ),
            self.assertRaises(reading_preparation.LimitError) as caught,
            budget.stage() as stage,
        ):
            stage.keep({"retained": "original"})
            self.clock[0] += 0.02
        self.assertEqual("retained-unmeasurable", caught.exception.reason)
        self.assertAlmostEqual(self.snapshot.account.usage.prepare_ms, before + 20)
        self.assert_released_and_exhausted()

    def test_plan_acceptance_ends_metering_before_model_wait(self) -> None:
        before = self.snapshot.account.usage.prepare_ms
        with self.budget().stage() as stage:
            self.clock[0] += 0.02
            prepared = self.fixture.call_prepare().prepared
            assert prepared is not None
            plan = reading_passes.plan_packets(
                prepared.originals,
                goal=prepared.inputs.revision["goal"],
                lines=(),
                protocol_prefix="Map",
                max_bytes=10000,
                max_passes=1,
                final=prepared.final,
            )
            self.assertTrue(stage.accept_plan(plan))
            self.clock[0] += 30
        self.assertAlmostEqual(before + 20, self.snapshot.account.usage.prepare_ms)

    def test_known_final_floor_unfit_and_ci_gap_refuse_before_factories(self) -> None:
        self.plan["limits"]["prompt_bytes"] = 100
        result = self.boundary()
        self.assertEqual("prompt-unfit", result.reason)
        self.assertIsNone(result.prepared)
        self.fixture.route["ci_read"] = "on"
        self.fixture.collection = replace(
            self.fixture.collection,
            ancillary_info=replace(self.fixture.collection.ancillary_info, ci_binding="unknown"),
        )
        result = self.boundary()
        self.assertEqual("frozen-context", result.reason)
        self.assertIsNone(result.prepared)
        self.assertEqual(0, self.fixture.fixture.marker.fixture.spends())

    def test_real_maps_report_exact_one_plan_after_metering_before_charge(self) -> None:
        f = self.fixture
        boundary = self.boundary()
        self.assertEqual("", boundary.reason)
        p, budget = boundary.prepared, boundary.budget
        assert p is not None and budget is not None
        reported: list[reading_passes.PacketPlan] = []
        with budget.stage() as stage:

            def ready(plan: reading_passes.PacketPlan) -> bool:
                self.assertEqual(0, f.fixture.marker.fixture.spends())
                if not stage.accept_plan(plan):
                    return False
                reported.append(plan)
                return True

            with mock.patch.object(
                reading_passes,
                "plan_packets",
                wraps=reading_passes.plan_packets,
            ) as planner:
                series = reading_map_series.run(
                    p.originals,
                    goal=p.inputs.revision["goal"],
                    lines=reading.outcome_lines(p.inputs.revision),
                    clauses=("goal", "line_1", "line_2"),
                    plan=self.plan,
                    model_for=f.fixture.model_for,
                    stop_reason=lambda: None,
                    on_observation=f.fixture.marker.observe,
                    frozen_context=p.context,
                    final=p.final,
                    on_plan=ready,
                )
        self.assertEqual(1, planner.call_count)
        self.assertEqual([series.plan], reported)
        self.assertGreater(len(series.passes), 0)
        self.assertGreater(self.snapshot.account.usage.prepare_ms, f.collection.usage.prepare_ms)

    def test_plan_callback_refusal_or_exception_keeps_all_ranges_uncalled(self) -> None:
        boundary = self.boundary()
        p = boundary.prepared
        assert p is not None
        for response in (False, OSError("private publication detail")):
            callback = mock.Mock(
                return_value=response,
                side_effect=response if isinstance(response, Exception) else None,
            )
            factory = mock.Mock()
            with mock.patch.object(
                reading_passes,
                "plan_packets",
                wraps=reading_passes.plan_packets,
            ) as planner:
                series = reading_map_series.run(
                    p.originals,
                    goal=p.inputs.revision["goal"],
                    lines=reading.outcome_lines(p.inputs.revision),
                    clauses=("goal", "line_1", "line_2"),
                    plan=self.plan,
                    model_for=factory,
                    stop_reason=lambda: None,
                    frozen_context=p.context,
                    final=p.final,
                    on_plan=callback,
                )
            self.assertEqual(1, callback.call_count)
            self.assertEqual(1, planner.call_count)
            factory.assert_not_called()
            self.assertEqual("plan-unresolved", series.reason)
            self.assertEqual((), series.passes)
            self.assertEqual(
                tuple(s for packet in series.plan.packets for s in packet.primary),
                series.unassigned_primary,
            )
            self.assertNotIn("private publication detail", repr(series))
            diagnostic = reading_long_diagnostics.derive(plan=self.plan, series=series)
            self.assertEqual("plan-unresolved", diagnostic["maps"]["reason"])

    def test_invalid_start_clock_value_exhausts_account_and_releases_lock(self) -> None:
        with (
            self.assertRaises(reading_preparation.LimitError),
            self.budget(lambda: 10**400).stage(),
        ):
            self.fail("Unrepresentable clock cannot start preparation")
        self.assert_released_and_exhausted()

    def test_constructor_validation_and_graph_are_inside_shared_metering(self) -> None:
        before = self.snapshot.account.usage
        with mock.patch.object(
            reading_pass_types,
            "validate_plan",
            wraps=reading_pass_types.validate_plan,
        ) as validate:
            self.budget(mock.Mock(side_effect=[10.0, 10.025]))
        self.assertEqual(1, validate.call_count)
        self.assertAlmostEqual(before.prepare_ms + 25, self.snapshot.account.usage.prepare_ms)
        self.assertGreater(self.snapshot.account.retained_base_bytes, before.retained_bytes)

    def test_nested_or_concurrent_account_stage_refuses_without_releasing_owner_lock(self) -> None:
        budget, other = self.budget(), self.budget()
        with budget.stage():
            with self.assertRaises(ValueError), other.stage():
                self.fail("Shared account cannot have concurrent preparation")
            self.assertFalse(self.snapshot.account.lock.acquire(blocking=False))
            with self.assertRaises(ValueError):
                self.budget()
        self.assertTrue(self.snapshot.account.lock.acquire(blocking=False))
        self.snapshot.account.lock.release()

    def test_mandatory_final_floor_uses_actual_utf8_bytes_and_original_identity(self) -> None:
        boundary = self.boundary()
        p, floor = boundary.prepared, boundary.final_floor
        assert p is not None and floor is not None and floor.packet is not None
        self.assertEqual((), floor.navigation)
        expected = {o.row["id"] for o in p.originals if o.row["type"] != reading.AGENT_MESSAGE_TYPE}
        assert p.final is not None
        expected.add(p.final["fact_id"])
        self.assertEqual(expected, {r["id"] for r in floor.packet.selection.entries})
        size = len(floor.packet.prompt.encode("utf-8"))
        for bound, fits in ((size, True), (size - 1, False)):
            checked = reading_reconcile_packet.preflight(
                p.originals,
                goal=p.inputs.revision["goal"],
                lines=reading.outcome_lines(p.inputs.revision),
                scope=p.scope,
                scope_floor=p.floor,
                final=p.final,
                frozen_context=p.context,
                slot=reading_map_series.FinalSlot(17, bound, reading.REPLY_CAP_BYTES),
            )
            self.assertEqual(fits, checked.packet is not None)
            if not fits:
                self.assertEqual("prompt-unfit", checked.reason)
                self.assertIn("final-unfit", checked.unresolved)
        self.assertEqual(0, self.fixture.fixture.marker.fixture.spends())

    def test_preflight_missing_person_or_complete_words_refuses_explicitly(self) -> None:
        p = self.boundary().prepared
        assert p is not None
        person = next(o for o in p.originals if o.row["type"] == "user_message")
        for originals in (
            tuple(o for o in p.originals if o is not person),
            tuple(replace(o, words=None) if o is person else o for o in p.originals),
        ):
            with self.subTest(originals=len(originals)):
                checked = reading_reconcile_packet.preflight(
                    originals,
                    goal=p.inputs.revision["goal"],
                    lines=reading.outcome_lines(p.inputs.revision),
                    scope=p.scope,
                    scope_floor=p.floor,
                    final=p.final,
                    frozen_context=p.context,
                    slot=reading_map_series.FinalSlot(17, 20000, reading.REPLY_CAP_BYTES),
                )
                self.assertIsNone(checked.packet)
                self.assertEqual("original-unavailable", checked.reason)

    def test_plan_measurement_exception_seals_stage_and_refuses_without_calls(self) -> None:
        boundary = self.boundary()
        p, budget = boundary.prepared, boundary.budget
        assert p is not None and budget is not None
        factory = mock.Mock()
        with budget.stage() as stage:

            def ready(plan: reading_passes.PacketPlan) -> bool:
                with mock.patch.object(
                    reading_source_collect, "_measure", side_effect=RuntimeError("private graph")
                ):
                    return stage.accept_plan(plan)

            series = reading_map_series.run(
                p.originals,
                goal=p.inputs.revision["goal"],
                lines=reading.outcome_lines(p.inputs.revision),
                clauses=("goal", "line_1", "line_2"),
                plan=self.plan,
                model_for=factory,
                stop_reason=lambda: None,
                frozen_context=p.context,
                final=p.final,
                on_plan=ready,
            )
        factory.assert_not_called()
        self.assertEqual("plan-unresolved", series.reason)
        self.assertEqual("retained-unmeasurable", budget.reason)
        self.assert_released_and_exhausted()

    def test_interrupted_clock_releases_lock_and_cannot_restore_unknown_interval(self) -> None:
        budget = self.budget()
        budget.clock = mock.Mock(side_effect=[10.0, KeyboardInterrupt()])
        with self.assertRaises(KeyboardInterrupt), budget.stage():
            pass
        self.assert_released_and_exhausted()

    def test_smaller_declared_source_byte_or_page_cap_refuses_existing_usage(self) -> None:
        for field, reason in (("source_bytes", "source-bytes"), ("source_pages", "source-pages")):
            with self.subTest(field=field):
                self.fixture.prepare()
                snapshot = self.fixture.collection.snapshot
                assert snapshot is not None
                self.snapshot = snapshot
                self.plan = deepcopy(self.fixture.fixture.marker.declared)
                before = self.snapshot.account.usage
                used = getattr(before, field)
                self.assertGreater(used, 1)
                self.plan["limits"][field] = used - 1
                result = self.boundary()
                self.assertEqual(reason, result.reason)
                self.assertIsNone(result.prepared)
                self.assertIsNone(result.budget)
                self.assertEqual(before.source_bytes, self.snapshot.account.usage.source_bytes)
                self.assertEqual(before.source_pages, self.snapshot.account.usage.source_pages)
                self.assertGreaterEqual(self.snapshot.account.usage.prepare_ms, before.prepare_ms)
                self.assertEqual(0, self.fixture.fixture.marker.fixture.spends())
                self.assert_released_and_exhausted()
                # A larger later declaration cannot undo the tightened shared account.
                self.plan = deepcopy(self.fixture.fixture.marker.declared)
                self.assert_released_and_exhausted()

    def test_exact_consumed_source_ceiling_still_allows_preparation_without_new_io(self) -> None:
        before = self.snapshot.account.usage
        self.plan["limits"]["source_bytes"] = before.source_bytes
        self.plan["limits"]["source_pages"] = before.source_pages
        result = self.boundary()
        self.assertEqual("", result.reason)
        self.assertIsNotNone(result.prepared)
        self.assertEqual(before.source_bytes, self.snapshot.account.usage.source_bytes)
        self.assertEqual(before.source_pages, self.snapshot.account.usage.source_pages)
        self.assertEqual(0, self.fixture.fixture.marker.fixture.spends())
