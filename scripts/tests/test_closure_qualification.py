"""Bounded closure continuation: synthetic account files, never provider calls."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import abstention_ledger as ledger

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.test_abstention_claude import (
        BINDING,
        _claude_case,
        _Config,
        _Model,
        _reply,
    )
    from tests.test_abstention_continuation import _TwoFailedResults
    from tests.test_analyze_campaign import acceptance, seed_predecessor

    from tests import test_abstention_continuation as continuation_cases
else:
    import test_abstention_continuation as continuation_cases
    from test_abstention_claude import BINDING, _claude_case, _Config, _Model, _reply
    from test_abstention_continuation import _TwoFailedResults
    from test_analyze_campaign import acceptance, seed_predecessor


class GrantFourAllowance(_TwoFailedResults):
    """Catch old-key reopening, unbound model upgrades and prefix loss."""

    if TYPE_CHECKING:
        # Runtime borrows these helpers over the same inherited fixture attributes.
        def grant_3(self, phase: str = "sealed", **previous: str) -> None: ...

        def fourth(self, cap: int = 28) -> ledger.Ledger: ...
    else:
        grant_3 = continuation_cases.AThirdFailedContinuationChainsAFourthPacket.grant_3
        fourth = continuation_cases.AThirdFailedContinuationChainsAFourthPacket.fourth

    def setUp(self) -> None:
        super().setUp()
        self.grant_2("sealed")
        third = ledger.Ledger(
            str(self.ledger_path),
            cap=28,
            producer="claude",
            marks_digest=self.third_marks,
            inputs_digest=self.third_inputs,
            cases_digest=self.third_cases,
        )
        for _ in range(5):
            third.settle(third.charge("3" * 16), "ok")
        self.third_chain = ledger.chain_of(str(self.ledger_path))
        self.third_summary_path.write_text(
            json.dumps(
                {
                    "verdict": "failed",
                    "producer": "claude",
                    "ledger_chain": self.third_chain,
                    "marks_digest": self.third_marks,
                    "inputs_digest": self.third_inputs,
                }
            )
        )
        self.fourth_cases, self.fourth_marks, self.fourth_inputs = "4" * 64, "5" * 64, "6" * 64
        self.grant_3()
        old = self.fourth()
        for _ in range(5):
            old.settle(old.charge("4" * 16), "ok")
        self.prefix = self.ledger_path.read_bytes()
        self.fourth_summary_path.write_text(
            json.dumps(
                {
                    "verdict": "failed",
                    "producer": "claude",
                    "ledger_chain": ledger.chain_of(str(self.ledger_path)),
                    "marks_digest": self.fourth_marks,
                    "inputs_digest": self.fourth_inputs,
                }
            )
        )
        self.new_key = {
            "cases_digest": "8" * 64,
            "marks_digest": "9" * 64,
            "inputs_digest": "0" * 64,
        }
        self.model_key = "1" * 64
        self.campaign_key = "2" * 64

    def closure_grant(self, **changes: Any) -> None:
        body = {
            "v": 1,
            "phase": "sealed",
            "previous": {
                "ledger_chain": ledger.chain_of(str(self.ledger_path)),
                "marks_digest": self.fourth_marks,
                "inputs_digest": self.fourth_inputs,
            },
            "next": self.new_key,
            "closure_allowance": {
                "additional_calls": 31,
                "previous_calls": 28,
                "repeats": 3,
                "retry_calls": 1,
                "model_binding": self.model_key,
                "campaign_binding": self.campaign_key,
            },
        }
        body.update(changes)
        self.grant_paths[3].write_text(json.dumps(body))

    def fifth(self) -> ledger.Ledger:
        value = ledger.Ledger(
            str(self.ledger_path),
            cap=59,
            producer="claude",
            marks_digest=self.new_key["marks_digest"],
            inputs_digest=self.new_key["inputs_digest"],
            cases_digest=self.new_key["cases_digest"],
        )
        value.model_binding = self.model_key
        return value

    def test_sealed_grant_four_unlocks_only_the_bound_new_model_key(self) -> None:
        self.closure_grant()
        self.assertEqual("", self.fifth().check())
        self.assertEqual(59, self.fifth().cap)
        self.assertEqual(self.prefix, self.ledger_path.read_bytes())

    def test_a_wrong_model_cannot_use_the_new_allowance(self) -> None:
        self.closure_grant()
        value = self.fifth()
        value.model_binding = "f" * 64
        self.assertNotEqual("", value.check())
        self.assertEqual(self.prefix, self.ledger_path.read_bytes())

    def test_allowance_on_an_older_generation_is_refused(self) -> None:
        self.closure_grant()
        grant = json.loads(self.grant_paths[3].read_text())
        prior = json.loads(self.grant_3_path.read_text())
        prior["closure_allowance"] = grant["closure_allowance"]
        self.grant_3_path.write_text(json.dumps(prior))
        self.assertNotEqual("", self.fifth().check())

    def test_new_charge_cannot_bypass_the_shared_aggregate_reservation(self) -> None:
        self.closure_grant()
        with self.assertRaises(ledger.LedgerError):
            self.fifth().charge("a" * 16)
        self.assertEqual(self.prefix, self.ledger_path.read_bytes())

    def test_cli_ceiling_can_raise_only_with_the_sealed_new_allowance(self) -> None:
        import argparse  # noqa: PLC0415 - isolated test fixture modules

        import score_abstention  # noqa: PLC0415 - isolated test fixture modules  # noqa: PLC0415 - isolated test fixture modules

        args = argparse.Namespace(
            score=True,
            probe_argv=False,
            producer="claude",
            max_calls=59,
            resume=False,
            claude_reading_model=None,
        )
        with mock.patch.object(ledger, "continuation", return_value=None):
            self.assertNotEqual("", score_abstention._argument_refusal(args))
        self.closure_grant()
        self.assertEqual("", score_abstention._argument_refusal(args))
        self.closure_grant(phase="marking")
        self.assertNotEqual("", score_abstention._argument_refusal(args))


class RepeatedQualification(GrantFourAllowance):
    """Exercise native produce, rubric, ledgers and repeated outputs with a local fake model."""

    def setUp(self) -> None:  # noqa: C901, PLR0915 - complete source-pinned native protocol fixture
        super().setUp()
        import analyze_campaign  # noqa: PLC0415 - isolated test fixture modules

        self.campaign_module = analyze_campaign
        import mark_abstention  # noqa: PLC0415 - isolated test fixture modules
        import score_abstention  # noqa: PLC0415 - isolated test fixture modules

        self.score_module = score_abstention
        self.config = _Config()
        self.binding = dict(BINDING)
        self.model_key = ledger.digest(
            {k: self.binding.get(k) for k in score_abstention.BINDING_KEYS}
        )
        for helper in ("native_case_person_lookup", "native_case_final_lookup"):
            callback: Callable[[Any], list[Any] | None] = (
                (lambda _rows: []) if helper.endswith("person_lookup") else (lambda _rows: None)
            )
            source_patch = mock.patch.object(mark_abstention, helper, return_value=callback)
            source_patch.start()
            self.addCleanup(source_patch.stop)
        cases = []
        for n in range(10):
            case = _claude_case()
            sid = f"fixture-{n}"
            case["sid"] = sid
            case["id"] = mark_abstention._case_id("claude", sid)
            case["row_snapshot"]["sid"] = sid
            for fact in case["producer_facts"]:
                fact["source_session"]["sid"] = sid
                if "branch" in fact:
                    fact["branch"]["sid"] = sid
            if n >= 5:
                case["origin"] = "synthetic"
            captured_prompts: list[str] = []

            def source_sink(
                prompt: str, *, sink_prompts: list[str] = captured_prompts, **_kwargs: Any
            ) -> tuple[str, str]:
                sink_prompts.append(prompt)
                return "", "failed"

            score_abstention.score_case(
                self.config,
                case,
                case["row_snapshot"],
                case["producer_facts"],
                {},
                model=source_sink,
                now=case["captured_at"],
                revision=mark_abstention.case_revision(case),
                tool_output=score_abstention._tool_output(case, "Anthropic", "claude", {"v": 5}),
                read_agent_words=True,
            )
            self.assertEqual(1, len(captured_prompts))
            case["production_reading"] = {
                "v": 1,
                "prefix_digest": "a" * 64,
                "person_wanted": [],
                "person_words_digest": "b" * 64,
                "final_wanted": [],
                "newest_final": None,
                "prompt_digest": hashlib.sha256(captured_prompts[0].encode()).hexdigest(),
                "constraints": ["goal", "line_1", "line_2"],
            }
            cases.append(case)
        body = {
            "v": 5,
            "cases": cases,
            "closure_kinds": {
                c["id"]: (*score_abstention.KINDS, *score_abstention.PASSING_CHECK_ADVERSARIES)[n]
                for n, c in enumerate(cases)
            },
        }
        marks: dict[str, Any] = {
            "v": 4,
            "cases_digest": mark_abstention.cases_digest(body),
            "marks": {
                c["id"]: dict.fromkeys(("goal", "line_1", "line_2"), "abstain") for c in cases
            },
        }
        rubric = {
            "cases": {
                c["id"]: {
                    "kind": score_abstention.KINDS[n % 5],
                    "origin": "recorded" if n < 5 else "synthesised",
                    "harness": "claude",
                    "expect": {
                        k: {"result": "unverifiable", "cites": []}
                        for k in ("goal", "line_1", "line_2")
                    },
                }
                for n, c in enumerate(cases)
            }
        }
        self.corpus = score_abstention.Corpus(body, marks, json.dumps(marks).encode(), rubric)
        self.new_key = {
            "cases_digest": mark_abstention.cases_digest(body),
            "marks_digest": score_abstention.marks_digest(self.corpus),
            "inputs_digest": score_abstention._inputs_digest(self.corpus),
        }
        request = ledger.digest(
            {
                "marks_digest": self.new_key["marks_digest"],
                "inputs_digest": self.new_key["inputs_digest"],
                "model_binding": self.model_key,
            }
        )
        manifest = self.root / "campaign-manifest.json"
        state = self.root / "campaign.json"
        old_replay = self.root / "old-replay.json"
        old_replay.write_text(json.dumps({"calls": [{} for _ in range(631)]}))
        self.slots = {
            "replay": [f"replay{n:03}" for n in range(190)],
            "qualification": [f"{c['id']}:r{repeat}" for repeat in (1, 2, 3) for c in cases],
            "live": [f"live{n:03}" for n in range(14)],
        }
        authority: dict[str, Any] = {
            "v": 1,
            "phase": "sealed",
            "limits": {"replay": 190, "qualification": 31, "live": 18},
            "retry_limits": {"replay": 0, "qualification": 1, "live": 4},
            "bindings": {"replay": "a" * 64, "qualification": request, "live": "b" * 64},
            "slots": self.slots,
            "qualification_kinds": body["closure_kinds"],
            "requests": {
                lane: dict.fromkeys(
                    slots, {"replay": "a" * 64, "qualification": request, "live": "b" * 64}[lane]
                )
                for lane, slots in self.slots.items()
            },
            "order": ["replay", "qualification", "live"],
            "batches": {
                lane: [
                    slots[n : n + (10 if lane == "qualification" else 25)]
                    for n in range(0, len(slots), 10 if lane == "qualification" else 25)
                ]
                for lane, slots in self.slots.items()
            },
            "protocols": dict.fromkeys(self.slots, "synthetic-test-v1"),
            "evidence": {
                lane: dict.fromkeys(("scorer", "source", "marks"), "e" * 64) for lane in self.slots
            },
            "historical": {
                "replay": {
                    "calls": 631,
                    "sha256": hashlib.sha256(old_replay.read_bytes()).hexdigest(),
                    "calls_digest": ledger.digest(json.loads(old_replay.read_text())["calls"]),
                },
                "qualification": {
                    "calls": 28,
                    "sha256": hashlib.sha256(self.ledger_path.read_bytes()).hexdigest(),
                    "calls_digest": ledger.digest(
                        json.loads(self.ledger_path.read_text())["calls"]
                    ),
                },
            },
        }
        from compass_runtime import (  # noqa: PLC0415 - actual source stamp in synthetic fixture
            observer,
        )

        authority["evidence"]["qualification"] = {
            "source": analyze_campaign.runtime_source_digest(Path(observer.__file__).parent),
            "scorer": hashlib.sha256(Path(score_abstention.__file__).read_bytes()).hexdigest(),
            "marks": self.new_key["marks_digest"],
        }
        actual_requests = {}
        for case in cases:
            captured: list[str] = []

            def capture(
                prompt: str, *, output_cap_bytes: int, captured_requests: list[str] = captured
            ) -> tuple[str, str]:
                captured_requests.append(
                    analyze_campaign.request_digest(
                        prompt,
                        {k: self.binding.get(k) for k in score_abstention.BINDING_KEYS},
                        authority["evidence"]["qualification"]["source"],
                        output_cap_bytes,
                    )
                )
                return "", "failed"

            score_abstention.score_case(
                self.config,
                case,
                case["row_snapshot"],
                case["producer_facts"],
                marks["marks"][case["id"]],
                model=capture,
                now=case["captured_at"],
                revision=mark_abstention.case_revision(case),
                tool_output=score_abstention._tool_output(
                    case, "Anthropic", "claude", self.corpus.cases
                ),
                read_agent_words=True,
            )
            self.assertEqual(1, len(captured))
            actual_requests.update({f"{case['id']}:r{repeat}": captured[0] for repeat in (1, 2, 3)})
        authority["requests"]["qualification"] = actual_requests
        for lane, slots in self.slots.items():
            size = 10 if lane == "qualification" else 25
            authority["batches"][lane] = [
                slots[:1],
                *[slots[n : n + size] for n in range(1, len(slots), size)],
            ]
        manifest.write_text(json.dumps(authority))
        for key, value in (
            ("MANIFEST_PATH", manifest),
            ("LEDGER_PATH", state),
            ("REPLAY_PATH", old_replay),
            ("QUALIFICATION_PATH", self.ledger_path),
            ("SUCCESSOR_MANIFEST_PATH", self.root / "successor.json"),
            ("SUCCESSOR_HANDOFF_PATH", self.root / "handoff.json"),
            ("LOGIN_RESUME_MANIFEST_PATH", self.root / "login-resume.json"),
            ("LOGIN_RESUME_HANDOFF_PATH", self.root / "login-handoff.json"),
            ("CLAUSE_CONTINUATION_MANIFEST_PATH", self.root / "clause-continuation.json"),
            ("CLAUSE_CONTINUATION_HANDOFF_PATH", self.root / "clause-handoff.json"),
            ("CLAUSE_ZERO_RESEAL_PATH", self.root / "zero-reseal.json"),
            ("CLAUSE_ISOLATION_MANIFEST_PATH", self.root / "clause-isolation.json"),
            ("CLAUSE_ISOLATION_HANDOFF_PATH", self.root / "clause-isolation-handoff.json"),
            ("CONDITIONAL_PRIORITY_MANIFEST_PATH", self.root / "conditional-priority.json"),
            ("CONDITIONAL_PRIORITY_HANDOFF_PATH", self.root / "conditional-priority-handoff.json"),
            ("TENTH_MANIFEST_PATH", self.root / "tenth.json"),
            ("TENTH_HANDOFF_PATH", self.root / "tenth-handoff.json"),
            ("RETRY_MANIFEST_PATH", self.root / "retry.json"),
            ("RETRY_HANDOFF_PATH", self.root / "retry-handoff.json"),
        ):
            patch = mock.patch.object(analyze_campaign, key, str(value))
            patch.start()
            self.addCleanup(patch.stop)
        authority["phase"] = "prepared"
        manifest.write_text(json.dumps(authority))
        anchor = analyze_campaign.Campaign().initialize()
        authority.update(phase="sealed", activation_anchor=anchor)
        manifest.write_text(json.dumps(authority))
        campaign = analyze_campaign.Campaign()

        seed_predecessor(campaign, "replay")
        self.campaign_key = campaign.binding
        self.closure_grant()
        self.safe_reply = _reply(
            goal=("unverifiable", ()), line_1=("unverifiable", ()), line_2=("unverifiable", ())
        )
        self.model_class = _Model
        self.output = self.result_paths[3]
        self.local = self.root / "private-repeated.json"

    def run_score(self, model: Any, *, review: bool = True) -> int:

        kwargs = {
            "config": self.config,
            "model": model,
            "results_path": str(self.local),
            "summary_path": str(self.output),
            "now": 1000.0,
            "binding": self.binding,
            "tool_destination": "Anthropic",
            "ledger_path": str(self.ledger_path),
            "max_calls": 59,
            "vouch": lambda _case: [],
        }
        resume = None
        with mock.patch("builtins.print"):
            for _ in range(5):
                result = self.score_module.score(1, self.corpus, resume=resume, **kwargs)
                if not review or result != 2 or not self.local.exists():
                    return result
                local = json.loads(self.local.read_text())
                attempts = local["attempts"]
                if attempts[-1]["classification"] == "unusable":
                    if len(attempts) >= 2 and all(
                        a["classification"] == "unusable" for a in attempts[-2:]
                    ):
                        return result
                    resume = (
                        local  # Explicit operator-equivalent resume, not automatic scorer retry.
                    )
                    continue
                campaign = self.campaign_module.Campaign()
                state = campaign._state()
                for batch, group in enumerate(campaign.manifest["batches"]["qualification"]):
                    own = [
                        c
                        for c in state["calls"]
                        if c["lane"] == "qualification" and c["slot"] in group
                    ]
                    latest = {c["slot"]: c["status"] for c in own}
                    if f"qualification:{batch}" not in state.get("accepted_batches", {}) and all(
                        latest.get(slot) == "usable" for slot in group
                    ):
                        campaign.accept_batch(
                            "qualification", batch, acceptance(campaign, "qualification", batch)
                        )
                        resume = local
                        break
                else:
                    return result
        return result

    def test_batch_review_pause_is_not_an_attempt_or_semantic_failure(self) -> None:
        model = self.model_class((self.safe_reply, "ok"))
        self.assertEqual(2, self.run_score(model, review=False))
        self.assertEqual(1, len(model.prompts))
        state = self.campaign_module.Campaign()._state()
        self.assertNotIn("stop", state)
        self.assertEqual(1, sum(c["lane"] == "qualification" for c in state["calls"]))

    def test_a_changed_final_prompt_cannot_reach_the_qualification_executor(self) -> None:
        reading = self.score_module._runtime()[1]
        native = reading.build_prompt

        def changed(*args: Any, **kwargs: Any) -> Any:
            prompt, selected = native(*args, **kwargs)
            return prompt + "\nchanged-after-registration", selected

        model = self.model_class((self.safe_reply, "ok"))
        with mock.patch.object(reading, "build_prompt", side_effect=changed):
            self.assertEqual(2, self.run_score(model))
        self.assertEqual([], model.prompts)
        state = self.campaign_module.Campaign()._state()
        self.assertEqual(0, sum(c["lane"] == "qualification" for c in state["calls"]))

    def test_missing_full_production_metadata_refuses_before_any_attempt(self) -> None:
        self.corpus.cases["cases"][0].pop("production_reading", None)
        model = self.model_class((self.safe_reply, "ok"))
        self.assertEqual(2, self.run_score(model))
        self.assertEqual([], model.prompts)

    def test_malformed_full_production_metadata_refuses_before_any_attempt(self) -> None:
        self.corpus.cases["cases"][0]["production_reading"] = {"v": 1}
        model = self.model_class((self.safe_reply, "ok"))
        self.assertEqual(2, self.run_score(model))
        self.assertEqual([], model.prompts)

    def test_repeat_protocol_itself_requires_source_seal_without_outer_key_masking(self) -> None:
        cases = {case["id"]: dict(case) for case in self.corpus.cases["cases"]}
        cases[next(iter(cases))].pop("production_reading")
        native = self.fifth()
        native.campaign = self.campaign_module.Campaign()
        model = self.model_class((self.safe_reply, "ok"))
        with mock.patch("builtins.print"):
            self.assertEqual(
                2,
                self.score_module._score_repeated(
                    self.corpus,
                    cases,
                    native,
                    config=self.config,
                    model=model,
                    results_path=str(self.local),
                    summary_path=str(self.output),
                    now=1000.0,
                    binding=self.binding,
                    tool_destination="Anthropic",
                    resume=None,
                ),
            )
        self.assertEqual([], model.prompts)
        self.assertEqual(28, native.used())

    def test_successful_repeated_exposures_are_thirty_not_ten(self) -> None:
        model = self.model_class((self.safe_reply, "ok"))
        self.assertEqual(0, self.run_score(model))
        self.assertEqual(30, len(model.prompts))
        summary = json.loads(self.output.read_text())
        self.assertEqual("passed", summary["verdict"])
        self.assertEqual(10, summary["counts"]["unique_cases"])
        self.assertEqual(30, summary["counts"]["registered_exposures"])
        self.assertEqual(3, len(summary["repetitions"]))
        self.assertEqual(58, len(ledger.read(str(self.ledger_path))["calls"]))

    def test_explicit_export_context_reaches_actual_repeated_score_case(self) -> None:
        # This is transport-context wiring over the existing synthetic campaign,
        # not source admission. Real receipt/native-source checks live in test_reviewed_exports.
        resolver = mock.Mock()
        bad = _reply(
            goal=("unverifiable", ()), line_1=("consistent", (2,)), line_2=("unverifiable", ())
        )
        model = self.model_class((bad, "ok"))
        with (
            mock.patch.object(
                self.score_module, "score_case", wraps=self.score_module.score_case
            ) as case,
            mock.patch("builtins.print"),
        ):
            self.assertEqual(
                1,
                self.score_module.score(
                    1,
                    self.corpus,
                    config=self.config,
                    model=model,
                    results_path=str(self.local),
                    summary_path=str(self.output),
                    now=1000.0,
                    binding=self.binding,
                    tool_destination="Anthropic",
                    ledger_path=str(self.ledger_path),
                    max_calls=59,
                    vouch=lambda _case: [],
                    reviewed_exports=resolver,
                ),
            )
        self.assertEqual(1, len(model.prompts))
        self.assertIs(resolver, case.call_args.kwargs["reviewed_exports"])

    def test_first_semantic_failure_stops_before_second_provider_attempt(self) -> None:
        bad = _reply(
            goal=("unverifiable", ()), line_1=("consistent", (2,)), line_2=("unverifiable", ())
        )
        model = self.model_class((bad, "ok"), (self.safe_reply, "ok"))
        self.assertEqual(1, self.run_score(model))
        self.assertEqual(1, len(model.prompts))
        self.assertEqual("failed", json.loads(self.output.read_text())["verdict"])
        state = self.campaign_module.Campaign()._state()
        self.assertEqual("semantic-failed", state["calls"][-1]["status"])

    def test_one_transport_retry_remains_visible_and_charged(self) -> None:
        model = self.model_class(("", "failed"), (self.safe_reply, "ok"))
        self.assertEqual(0, self.run_score(model))
        self.assertEqual(31, len(model.prompts))
        summary = json.loads(self.output.read_text())
        self.assertEqual(31, summary["counts"]["attempts"])
        self.assertEqual(59, len(ledger.read(str(self.ledger_path))["calls"]))
        local = json.loads(self.local.read_text())
        self.assertEqual(31, len(local["attempts"]))
        self.assertTrue(local["attempts"][0]["withheld"])

    def test_two_unusable_attempts_stop_without_third_call(self) -> None:
        model = self.model_class(("", "failed"), ("", "failed"), (self.safe_reply, "ok"))
        self.assertNotEqual(0, self.run_score(model))
        self.assertEqual(2, len(model.prompts))
        self.assertEqual(30, len(ledger.read(str(self.ledger_path))["calls"]))

    def test_classified_first_exposure_is_checkpointed_before_an_interruption(self) -> None:
        class Interrupted(_Model):
            def __call__(self, prompt: str, **kw: Any) -> tuple[str, str]:
                if self.prompts:
                    raise SystemExit("fixture interruption")
                return super().__call__(prompt, **kw)

        model = Interrupted((self.safe_reply, "ok"))
        with self.assertRaises(SystemExit):
            self.run_score(model)
        self.assertTrue(self.local.exists())
        local = json.loads(self.local.read_text())
        self.assertEqual(1, len(local["attempts"]))
        self.assertEqual("usable", local["attempts"][0]["classification"])

    def test_repeated_summary_can_be_reported_without_collapsing_cases(self) -> None:
        model = self.model_class((self.safe_reply, "ok"))
        self.run_score(model)
        summary = json.loads(self.output.read_text())
        self.assertIn("3 repetitions", "\n".join(self.score_module.render(summary)))
