"""Observer analyzer, transcript resolution, and HTTP route tests."""

from __future__ import annotations

import dataclasses
import http.client
import inspect
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import cli, observer, project_context, records, supervise
from compass_runtime import io as runtime_io

from .support import (
    RuntimeTestCase,
    make_config,
    make_runtime,
    make_server,
    poll_fast,
    process_alive,
    runtime,
    store_patch,
)


def _pi_message(
    msg_id: str,
    parent: str | None,
    role: str,
    content: str,
    *,
    ts: str = "2026-08-17T02:00:00Z",
) -> str:
    """One Pi-style JSONL message record."""
    return json.dumps(
        {
            "type": "message",
            "id": msg_id,
            "parentId": parent,
            "timestamp": ts,
            "message": {"role": role, "content": content},
        }
    )


def _pi_session(sid: str, cwd: str = "/home/test/project") -> str:
    return json.dumps({"type": "session", "id": sid, "cwd": cwd})


def _claude_message(
    uuid: str,
    role: str,
    content: Any,
    *,
    ts: str = "2026-08-17T02:00:00Z",
    sidechain: bool = False,
    meta: bool = False,
) -> str:
    """One Claude-style JSONL record: ``type`` is the role, ``uuid`` is the id.

    The field names are the ones a live transcript carries — surveyed over
    `~/.claude/projects`, where all 289 user and assistant records in the sample
    carried `parentUuid`, `isSidechain`, `type`, `message`, `uuid` and
    `timestamp`, and **none** carried a top-level `id`. The text is invented,
    per the convention `docs/captures/` sets: shapes, never values.
    """
    record: dict[str, Any] = {
        "parentUuid": None,
        "isSidechain": sidechain,
        "userType": "external",
        "cwd": "/home/test/project",
        "sessionId": "s-1",
        "version": "2.1.222",
        "gitBranch": "main",
        "type": role,
        "message": {"role": role, "content": content},
        "uuid": uuid,
        "timestamp": ts,
    }
    if meta:
        record["isMeta"] = True
    return json.dumps(record)


def _codex_message(
    payload_id: str | None,
    role: str,
    text: str,
    *,
    ts: str = "2026-08-17T02:00:00Z",
) -> str:
    """One Codex-style JSONL record: ``response_item`` wrapping a message payload.

    Again the live shape: the id lives at `payload.id` (never at the top level),
    the text at `payload.content[].text`, and the block type differs by role —
    `input_text` for the operator, `output_text` for the agent.

    ``payload_id=None`` writes the record with no ``id`` key at all, which is the
    MAJORITY shape and not an edge case: 599 of the 784 Codex user-message
    records (76.4%) inside the observer's own head and tail windows carry none,
    measured over the whole local rollout store. Every fixture here wrote the
    id-carrying minority before, which is how the dedup fallback went untested.
    """
    block = "input_text" if role == "user" else "output_text"
    payload: dict[str, Any] = {
        "type": "message",
        "role": role,
        "content": [{"type": block, "text": text}],
    }
    if payload_id is not None:
        payload = {"id": payload_id, **payload}
    return json.dumps({"timestamp": ts, "type": "response_item", "payload": payload})


def _codex_session_meta(
    sid: str, cwd: str = "/home/test/project", *, subagent: bool = False
) -> str:
    """A Codex rollout's line 1, which is what `transcripts.codex_meta` reads.

    ``thread_source`` is the field the collector's subagent test reads, and a
    subagent thread's rollout carries its PARENT's session id — measured on 262
    of 262 local subagent rollouts, none of which declared an id of its own.
    """
    payload: dict[str, Any] = {"id": sid, "cwd": cwd, "cli_version": "0.149.1"}
    if subagent:
        payload["thread_source"] = "subagent"
        payload["agent_nickname"] = "explorer"
    return json.dumps(
        {
            "timestamp": "2026-08-17T01:59:00Z",
            "type": "session_meta",
            "payload": payload,
        }
    )


def _write_entity(entity_dir: Path, slug: str, status: str) -> Path:
    """Write one entity file with ``status:`` frontmatter."""
    entity_dir.mkdir(parents=True, exist_ok=True)
    path = entity_dir / f"{slug}.md"
    path.write_text(f"---\nstatus: {status}\ntitle: {slug}\n---\nbody\n", encoding="utf-8")
    return path


def _write_workflow(workflow_dir: Path, stages: list[str]) -> Path:
    """A Spacedock workflow README declaring `stages`, the discriminator's source.

    The analyzer publishes a stage only when the entity's `status` names one this
    README declares — the per-file discriminator SECURITY.md names as standing in
    for the containment check a split-root state directory cannot get. A fixture
    with no README is a fixture whose stage is empty, which is what the observer
    must do with a state directory nothing vouched for.
    """
    workflow_dir.mkdir(parents=True, exist_ok=True)
    states = "".join(f"    - name: {stage}\n" for stage in stages)
    readme = workflow_dir / "README.md"
    readme.write_text(
        "---\ncommissioned-by: spacedock@0.22.0\nstages:\n  states:\n" + states + "---\n",
        encoding="utf-8",
    )
    return readme


def _boot_line(mid: str, parent: str | None, workflow_dir: Path, entity_dir: Path) -> str:
    """A `spacedock status --boot` envelope in a transcript record.

    Written in the `type: "tool_result"` block shape rather than Pi's
    `toolResult` *role*, and that is a branch dependency rather than a
    preference: reading the role shape is what `#127` adds to
    `spacedock.tool_result_text`, and on this branch it is not there yet. Both
    shapes reach the same `boot_records` scan once that lands, so this fixture
    stays correct either way. The envelope's first key must be `command`, which
    is what `boot_records` searches for.
    """
    envelope = json.dumps(
        {
            "command": "boot",
            "definition_dir": str(workflow_dir),
            "entity_dir": str(entity_dir),
        }
    )
    return json.dumps(
        {
            "type": "message",
            "id": mid,
            "parentId": parent,
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "content": envelope}],
            },
        }
    )


class ObserverAnalyzerTest(unittest.TestCase):
    """The observer analyzer: goal + stage + block from a transcript, read-only."""

    NOW = 1_700_000_000.0
    WINDOW = 86_400.0

    def setUp(self) -> None:
        self.config, self.state = make_runtime()

    def analyze(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """`observer.analyze` on this test's runtime and a fixed clock."""
        return observer.analyze(
            self.config, self.state, path, now=self.NOW, window_sec=self.WINDOW, **kwargs
        )

    def _write_transcript(self, tmp: str, lines: list[str]) -> str:
        path = Path(tmp) / "session.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def test_no_goal_session_yields_sentinel_not_hallucination(self) -> None:
        """AC2: a session with only a generic opener and no assistant output
        returns 'no goal derived' without calling the model."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("neg-001"),
                    _pi_message(
                        "m1",
                        None,
                        "user",
                        "Use $spacedock:first-officer for this whole Pi session.",
                    ),
                ],
            )

            # A model that fabricates a goal: the short-circuit must bypass it.
            def fabricating_model(_head: str, _ctx: str) -> str:
                return "fabricated goal that must not appear"

            result = self.analyze(path, model=fabricating_model)

        self.assertEqual("no goal derived", result["goal"])
        self.assertEqual("generic-opener-only-no-work", result["reason"])
        # The model was not called: the short-circuit bypassed it entirely.

    def test_positive_case_derives_goal_stage_and_block(self) -> None:
        """AC1: a known FO session produces a goal referencing the recent
        concrete directive, and the stage of the newest in-flight entity."""
        with tempfile.TemporaryDirectory() as tmp:
            workflow_dir = Path(tmp) / "wf"
            entity_dir = workflow_dir / ".spacedock-state"
            _write_workflow(workflow_dir, ["intake", "implementation", "posted"])
            _write_entity(entity_dir, "observer-agent-pattern", "implementation")
            os.utime(entity_dir / "observer-agent-pattern.md", (self.NOW, self.NOW))
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("pos-001"),
                    _pi_message(
                        "m1",
                        None,
                        "user",
                        "Use $spacedock:first-officer for this whole Pi session.",
                    ),
                    _pi_message(
                        "m2",
                        "m1",
                        "assistant",
                        "I'll start by running spacedock status --boot.",
                    ),
                    _pi_message(
                        "m3",
                        "m2",
                        "user",
                        "report the remaining pi related test and ergonomics issues",
                        ts="2026-08-17T02:05:00Z",
                    ),
                    _pi_message(
                        "m4",
                        "m3",
                        "assistant",
                        "I am blocked on a missing dependency in the test suite.",
                        ts="2026-08-17T02:06:00Z",
                    ),
                    _boot_line("m5", "m4", workflow_dir, entity_dir),
                ],
            )
            result = self.analyze(path)

        # The goal tracks the most recent concrete user directive, not the
        # generic opener. Falsified by editing the directive to a different
        # objective and observing the goal not track it.
        self.assertIn("report the remaining pi related test", result["goal"])
        # The stage is the entity's `status`, and only because the workflow
        # README declares it. Falsified by renaming the stage in the README:
        # `read_entities` then drops the entity and the stage comes back empty.
        self.assertEqual("implementation", result["stage"])
        # The block comes from recent assistant text containing a block indicator.
        self.assertIn("blocked", result["block"])

    def test_claude_outer_role_records_supply_a_real_goal(self) -> None:
        """Claude writes `type: user`, while Pi writes `type: message`."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    json.dumps(
                        {
                            "type": "user",
                            "uuid": "captain-1",
                            "timestamp": "2026-08-24T20:00:00Z",
                            "message": {
                                "role": "user",
                                "content": "Show the project observer goal",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "user",
                            "uuid": "meta-1",
                            "isMeta": True,
                            "message": {
                                "role": "user",
                                "content": [{"type": "text", "text": "Injected skill body"}],
                            },
                        }
                    ),
                ],
            )

            result = self.analyze(path)

        self.assertEqual("Show the project observer goal", result["goal"])

    def test_codex_response_messages_supply_goal_and_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    json.dumps(
                        {
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "id": "user-1",
                                "role": "user",
                                "content": [
                                    {"type": "input_text", "text": "Shape my session mirror"}
                                ],
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "id": "assistant-1",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "I am blocked on a missing browser connection.",
                                    }
                                ],
                            },
                        }
                    ),
                ],
            )

            result = self.analyze(path)

        self.assertEqual("Shape my session mirror", result["goal"])
        self.assertIn("blocked", result["block"])

    def test_child_assignment_can_be_model_derived_from_readable_assistant_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    json.dumps(
                        {
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "id": "assistant-1",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "I am revising the assignment roster.",
                                    }
                                ],
                            },
                        }
                    )
                ],
            )
            model = mock.Mock(return_value="Improve the assignment roster")
            result = observer.derive_child_assignment(self.config, path, model)

        self.assertEqual("Improve the assignment roster", result)
        model.assert_called_once()

    def _fo_transcript(
        self, tmp: str, *, stage: str, declared: list[str], age_sec: float = 0.0
    ) -> str:
        """One first-officer transcript over a workflow whose entity sits on `stage`."""
        workflow_dir = Path(tmp) / "wf"
        entity_dir = workflow_dir / ".spacedock-state"
        _write_workflow(workflow_dir, declared)
        entity = _write_entity(entity_dir, "drc-1", stage)
        written = self.NOW - age_sec
        os.utime(str(entity), (written, written))
        return self._write_transcript(
            tmp,
            [
                _pi_session("fo-001"),
                _pi_message("m1", None, "user", "Ship the observer route"),
                _pi_message("m2", "m1", "assistant", "Booting the workflow."),
                _boot_line("m3", "m2", workflow_dir, entity_dir),
            ],
        )

    def test_ordinary_reporting_prose_is_not_a_block(self) -> None:
        # The false-positive case, which the indicator table had none of. A bare
        # `cannot`/`can't`/`failed to`/`error:` matches an agent describing work
        # it has finished, and a block is the one field on the panel a reader
        # would act on. Falsifying edit: put the bare words back — every line
        # here publishes a block.
        for line in (
            "I can't reproduce the failure any more, so the fix holds.",
            "The old code cannot have worked; the new one does.",
            "It failed to build before the patch. It builds now.",
            "The log said error: missing header, which the include fixes.",
            "I was unable to reproduce it until I widened the window.",
            "Waiting for the suite to finish, then I will push.",
            # `blocked on` went the same way once the parser reached Claude and
            # Codex: over 857 real sessions it produced four blocks and all four
            # were prose about a PR or another issue. Both lines below are the
            # shape of those four.
            "The PR is mergeable and blocked only by required review.",
            "Your conclusion that live egress is still blocked on the other PR is correct.",
            # The last three bare phrases went the same way. Re-measured over
            # the whole local Claude corpus the table produced 7 blocks, and
            # `not permitted`, `permission denied` and `waiting for your`
            # supplied 4 of them — every one inside a quoted or fenced span, two
            # of them hitting the 200-character cap with the trigger truncated
            # away. Falsifying edit: put any of the three bare phrases back.
            'The hook refused it: the log line was "operation not permitted".',
            (
                "The rebase printed `permission denied` for the vendored "
                "submodule, which the checkout fixes."
            ),
            "The release is waiting for your PR to land, so nothing is needed here.",
            # `waiting for you` is a prefix of `waiting for your`, so the trailing
            # word-boundary test is what makes the line above stop matching.
            # Falsifying edit: drop `_BLOCK_TRAILING_RE` from `_indicator_hit`.
            "Everyone is waiting for your review of the design doc.",
        ):
            with self.subTest(line=line), tempfile.TemporaryDirectory() as tmp:
                path = self._write_transcript(
                    tmp,
                    [
                        _pi_session("fp-001"),
                        _pi_message("m1", None, "user", "Fix the build"),
                        _pi_message("m2", "m1", "assistant", line),
                    ],
                )
                self.assertEqual("", self.analyze(path)["block"])

    def test_a_resolved_block_is_not_walked_back_to(self) -> None:
        # Scanning backwards through every assistant message found a block that
        # had been reported and then resolved, and published it as current.
        # Falsifying edit: drop the `return ""` after the newest assistant
        # message — this publishes the twenty-turn-old block.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("res-001"),
                    _pi_message("m1", None, "user", "Fix the build"),
                    _pi_message("m2", "m1", "assistant", "I am blocked on a missing token."),
                    _pi_message("m3", "m2", "user", "Here is the token."),
                    _pi_message("m4", "m3", "assistant", "Thanks — the build is green now."),
                ],
            )
            self.assertEqual("", self.analyze(path)["block"])

    def test_a_current_block_is_still_reported(self) -> None:
        # The other side: narrowing the table must not cost the real case.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("cur-001"),
                    _pi_message("m1", None, "user", "Deploy it"),
                    _pi_message(
                        "m2",
                        "m1",
                        "assistant",
                        "I pulled the manifest. I am blocked on a missing AWS role.",
                    ),
                ],
            )
            self.assertEqual("I am blocked on a missing AWS role.", self.analyze(path)["block"])

    def test_the_first_person_replacements_still_report_a_real_block(self) -> None:
        # Narrowing three bare phrases must not cost the case they were there
        # for. Each line is the self-state form of one of them, and the last is
        # the bare `waiting for you` that survives the word-boundary test the
        # possessive now fails. Falsifying edit: delete the first-person entries
        # from `_BLOCK_INDICATORS` — every line here loses its block.
        for line, expected in (
            (
                "I pulled the manifest. I am not permitted to write to that bucket.",
                "I am not permitted to write to that bucket.",
            ),
            (
                "I read the config. I do not have permission to restart the service.",
                "I do not have permission to restart the service.",
            ),
            (
                "The diff is ready. I am waiting for your decision on the schema.",
                "I am waiting for your decision on the schema.",
            ),
            ("The branch is pushed, waiting for you.", "The branch is pushed, waiting for you."),
        ):
            with self.subTest(line=line), tempfile.TemporaryDirectory() as tmp:
                path = self._write_transcript(
                    tmp,
                    [
                        _pi_session("fp-002"),
                        _pi_message("m1", None, "user", "Deploy it"),
                        _pi_message("m2", "m1", "assistant", line),
                    ],
                )
                self.assertEqual(expected, self.analyze(path)["block"])

    def test_a_rejected_indicator_hit_does_not_hide_a_later_real_one(self) -> None:
        # `str.find` returns the FIRST occurrence, so a possessive earlier in the
        # message would otherwise shadow a genuine hand-off after it. Falsifying
        # edit: replace `_indicator_hit`'s loop with a single `lower.find`.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("fp-003"),
                    _pi_message("m1", None, "user", "Deploy it"),
                    _pi_message(
                        "m2",
                        "m1",
                        "assistant",
                        "The release is waiting for your PR to land. "
                        "The branch is pushed, waiting for you.",
                    ),
                ],
            )
            self.assertEqual("The branch is pushed, waiting for you.", self.analyze(path)["block"])

    def test_a_block_past_the_publish_cap_is_still_found(self) -> None:
        # Bounding `extract_text` bounded what the block scan can SEE, not only
        # what it publishes. Pi and Droid carry a bare string rather than a list
        # of blocks, so the 2,000-character default put an indicator past that
        # offset out of reach and the field came back empty with nothing saying
        # so. Falsifying edit: drop the `cap=` argument in `_message_from` — the
        # indicator sits at offset 2,520, past the default and inside the 8,192
        # the observer vouches for.
        filler = "I read the manifest and checked the store. " * 60
        indicator = "I am blocked on the missing credential for the staging store."
        body = f"{filler}{indicator}"
        self.assertGreater(body.index(indicator), records.EXTRACT_TEXT_CAP_CHARS)
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("cap-001"),
                    _pi_message("m1", None, "user", "Deploy the staging store"),
                    _pi_message("m2", "m1", "assistant", body),
                ],
            )
            self.assertEqual(indicator, self.analyze(path)["block"])

    def test_no_spacedock_withdraws_the_project_reads(self) -> None:
        # `--no-spacedock` is the switch that turns off the project reads, and
        # SECURITY.md's project-read contract is written against it. The route
        # read the entity frontmatter regardless, so the switch withdrew a
        # strip and left this reading the same files.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fo_transcript(tmp, stage="review", declared=["intake", "review"])
            self.assertEqual("review", self.analyze(path)["stage"])

            self.config = dataclasses.replace(self.config, spacedock_enabled=False)
            result = self.analyze(path)

        # The transcript half survives — a transcript read is not a project read.
        self.assertIn("Ship the observer route", result["goal"])
        self.assertEqual("", result["stage"])

    def test_an_undeclared_status_publishes_no_stage(self) -> None:
        # The per-file discriminator. SECURITY.md names `status in declared` as
        # what stands in for `read_workflow`'s containment check, because a
        # split-root workflow's state directory legitimately sits outside the
        # definition directory. Reading the scalar directly published whatever
        # the newest file in an unverified directory happened to say.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fo_transcript(
                tmp, stage="/etc/passwd he said", declared=["intake", "review"]
            )
            self.assertEqual("", self.analyze(path)["stage"])

    def test_a_stale_entity_publishes_no_stage(self) -> None:
        # The freshness gate. A first officer discovers every workflow in the
        # project, and one retired months ago still has entities frozen
        # mid-pipeline; those are history, not work in flight.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fo_transcript(
                tmp, stage="review", declared=["intake", "review"], age_sec=self.WINDOW * 2
            )
            self.assertEqual("", self.analyze(path)["stage"])

    def test_sidecar_path_refuses_a_name_that_is_not_a_name(self) -> None:
        # `safe_text` strips control characters and truncates; it passes `/`,
        # `\` and `..` straight through, so a session id carrying separators
        # walked out of the observer store and truncated whatever it landed on.
        config, _state = make_runtime()
        # `..` alone is absent on purpose: it lands as `pi_...json`, a legitimate
        # name inside the observer store, so refusing it would be superstition.
        # What has to be refused is anything that can leave that directory.
        for sid in (
            "x/../../../../.claude/settings",
            "a/b",
            "a\\b",
            "",
            "x" * 129,
        ):
            with self.subTest(sid=sid):
                self.assertIsNone(observer.sidecar_path(config, "pi", sid))
                self.assertIsNone(observer.write_sidecar(config, "pi", sid, {"goal": "x"}))
        self.assertIsNone(observer.sidecar_path(config, "../pi", "ok-1"))
        # A real id still resolves, inside the observer store.
        path = observer.sidecar_path(config, "pi", "abcdef12-3456-7890-abcd-ef1234567890")
        assert path is not None
        self.assertEqual(
            os.path.normpath(os.path.join(str(config.state_dir), "observer")),
            os.path.dirname(os.path.normpath(path)),
        )

    def test_read_only_invariant(self) -> None:
        """AC3: the observer never mutates the observed session's repo/state.
        The sidecar is written to the observer's own store, not the target tree."""
        with (
            tempfile.TemporaryDirectory() as target_tmp,
            tempfile.TemporaryDirectory() as store_tmp,
        ):
            observer_store = Path(store_tmp) / "observer-store"
            observer_store.mkdir()
            config = make_config(state_dir=observer_store, state_home=str(observer_store))
            workflow_dir = Path(target_tmp) / "wf"
            entity_dir = workflow_dir / ".spacedock-state"
            transcript = self._write_transcript(
                target_tmp,
                [
                    _pi_session("ro-001"),
                    _pi_message("m1", None, "user", "Fix the failing build"),
                    _pi_message("m2", "m1", "assistant", "Running the tests now."),
                    # The boot line matters to the README assertion below:
                    # without it the stage reader opens neither file, and "the
                    # README was not modified" would hold because it was never
                    # read at all.
                    _boot_line("m3", "m2", workflow_dir, entity_dir),
                ],
            )
            _write_workflow(workflow_dir, ["backlog", "doing"])
            entity_file = _write_entity(entity_dir, "task-one", "backlog")
            os.utime(str(entity_file), (self.NOW, self.NOW))
            readme_mtime = os.path.getmtime(str(workflow_dir / "README.md"))

            # Record mtimes before the run.
            transcript_mtime = os.path.getmtime(transcript)
            entity_mtime = os.path.getmtime(str(entity_file))

            # Make the target tree read-only (chmod -w the directory and files).
            os.chmod(transcript, 0o444)
            os.chmod(str(entity_file), 0o444)
            os.chmod(target_tmp, 0o555)  # noqa: S103
            os.chmod(str(entity_dir), 0o555)  # noqa: S103
            try:
                result = observer.analyze(
                    config, self.state, transcript, now=self.NOW, window_sec=self.WINDOW
                )
                sidecar = observer.write_sidecar(config, "pi", "ro-001", result)
            finally:
                # Restore permissions so cleanup can delete.
                os.chmod(target_tmp, 0o755)  # noqa: S103
                os.chmod(str(entity_dir), 0o755)  # noqa: S103
                os.chmod(transcript, 0o644)
                os.chmod(str(entity_file), 0o644)

            # The run produced a sidecar and a goal.
            self.assertIn("Fix the failing build", result["goal"])
            assert sidecar is not None
            self.assertTrue(os.path.isfile(sidecar))
            # The sidecar is outside the target tree.
            self.assertFalse(sidecar.startswith(target_tmp))
            # No file under the target tree was modified — the README the stage
            # reader now opens included.
            self.assertEqual(transcript_mtime, os.path.getmtime(transcript))
            self.assertEqual(entity_mtime, os.path.getmtime(str(entity_file)))
            self.assertEqual(readme_mtime, os.path.getmtime(str(workflow_dir / "README.md")))

    def test_model_failure_degrades_to_deterministic_fallback(self) -> None:
        """A model error degrades to the deterministic fallback, never crashes
        or hallucinates."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("model-fail-001"),
                    _pi_message("m1", None, "user", "Review the PR"),
                    _pi_message("m2", "m1", "assistant", "Starting the review."),
                ],
            )

            def crashing_model(_head: str, _ctx: str) -> str:
                raise RuntimeError("model unavailable")

            result = self.analyze(path, model=crashing_model)

        # The deterministic goal survives the model crash.
        self.assertIn("Review the PR", result["goal"])
        self.assertIsNone(result["reason"])

    def test_analyze_names_which_arm_produced_the_goal(self) -> None:
        """The published goal says which arm derived it, and keeps the
        deterministic line beside it.

        Without this the model arm's reassignment is invisible: `goal` is one
        string whether a transcript line or a model wrote it, so a reader told
        the harness published this cannot be distinguished from one reading a
        model's paraphrase. DRC-4509 renders exactly that distinction, so the
        distinction has to survive as far as the payload.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("provenance-001"),
                    _pi_message("m1", None, "user", "Review the PR"),
                    _pi_message("m2", "m1", "assistant", "Starting the review."),
                ],
            )

            plain = self.analyze(path)
            enhanced = self.analyze(path, model=lambda _head, _ctx: "Review the PR and land it")

            def crashing_model(_head: str, _ctx: str) -> str:
                raise RuntimeError("model unavailable")

            degraded = self.analyze(path, model=crashing_model)

        # No model ran, so the deterministic line is the published goal.
        self.assertEqual("deterministic", plain["goal_source"])
        self.assertEqual(plain["goal"], plain["deterministic_goal"])

        # The model ran and replaced the goal. Both lines stay reachable, and
        # the source names which one `goal` now holds.
        self.assertEqual("model", enhanced["goal_source"])
        self.assertIn("land it", enhanced["goal"])
        self.assertIn("Review the PR", enhanced["deterministic_goal"])
        self.assertNotEqual(enhanced["goal"], enhanced["deterministic_goal"])

        # A model that failed did not produce the goal, so it is not credited.
        self.assertEqual("deterministic", degraded["goal_source"])
        self.assertEqual(degraded["goal"], degraded["deterministic_goal"])

    def test_codex_goal_model_pins_luna_max_and_runs_ephemerally(self) -> None:
        recorded: dict[str, Any] = {}

        def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            recorded["command"] = command
            recorded["prompt"] = kwargs["input"]
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text("Resume the accepted project checkpoint\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as tmp:
            config = dataclasses.replace(
                self.config,
                state_dir=Path(tmp),
                state_home=tmp,
                observer_model_enabled=True,
            )
            caller = observer.CodexGoalModel(
                config,
                runner=run,
                binary_resolver=lambda _name: "/opt/bin/codex",
                consent=True,
                session_key="pi:model-test",
            )

            result = caller("Captain requested the exact checkpoint", "shaping")

        command = recorded["command"]
        self.assertEqual("Resume the accepted project checkpoint", result)
        self.assertEqual("gpt-5.6-luna", command[command.index("--model") + 1])
        self.assertIn("model_reasoning_effort=max", command)
        self.assertIn("--ephemeral", command)
        for feature in ("shell_tool", "unified_exec", "hooks", "plugins", "apps", "multi_agent"):
            self.assertIn(f"features.{feature}=false", command)
        self.assertIn('web_search="disabled"', command)
        self.assertIn("project_doc_max_bytes=0", command)
        self.assertIn("skills.include_instructions=false", command)
        self.assertEqual("read-only", command[command.index("--sandbox") + 1])
        self.assertIn("<transcript_excerpt>", recorded["prompt"])
        self.assertEqual("used", caller.metadata()["status"])

    def test_codex_no_goal_output_keeps_the_deterministic_goal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("model-empty-001"),
                    _pi_message("m1", None, "user", "Review the release checkpoint"),
                ],
            )

            result = self.analyze(path, model=lambda _recent, _stage: observer.NO_GOAL + ".")

        self.assertEqual("Review the release checkpoint", result["goal"])

    def test_no_goal_sentinel_not_overridden_by_model(self) -> None:
        """The deterministic short-circuit bypasses the model entirely: a
        model that would fabricate a goal must not override the sentinel."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(
                tmp,
                [
                    _pi_session("neg-002"),
                    _pi_message("m1", None, "user", "skill(spacedock:first-officer)"),
                ],
            )

            def fabricator(_head: str, _ctx: str) -> str:
                return "inferred goal from the opener"

            result = self.analyze(path, model=fabricator)

        self.assertEqual("no goal derived", result["goal"])


class ObserverRecordShapeTest(unittest.TestCase):
    """One test per harness record shape, so this cannot revert to Pi-only.

    The analyzer required ``type: "message"`` — Pi's shape and Droid's — and
    returned zero messages on 3,769 of 3,769 local Claude transcripts and 457 of
    457 Codex rollouts, publishing the ``no goal derived`` sentinel for sessions
    full of work. Teaching it the other two shapes and nothing else would have
    been worse: measured here over the same corpora, the published goal was a
    harness-injected shape on 234 of 457 Codex rollouts (51.2%) and 247 of a
    seeded 400-transcript Claude sample (61.8%). A confident wrong answer where
    there had been a silent one.
    """

    NOW = 1_700_000_000.0
    WINDOW = 86_400.0

    def setUp(self) -> None:
        self.config, self.state = make_runtime()

    def analyze(self, lines: list[str], **changes: Any) -> dict[str, Any]:
        config = dataclasses.replace(self.config, **changes) if changes else self.config
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return observer.analyze(
                config, self.state, str(path), now=self.NOW, window_sec=self.WINDOW
            )

    def test_a_claude_transcript_derives_a_goal(self) -> None:
        result = self.analyze(
            [
                _claude_message("u1", "user", "Rewrite the changelog for the release"),
                _claude_message(
                    "u2",
                    "assistant",
                    [{"type": "text", "text": "Reading the tags now."}],
                    ts="2026-08-17T02:01:00Z",
                ),
            ]
        )
        self.assertEqual("Rewrite the changelog for the release", result["goal"])

    def test_a_codex_rollout_derives_a_goal(self) -> None:
        result = self.analyze(
            [
                _codex_session_meta("019f1c51-6cf9-7981-9a2d-172428800000"),
                _codex_message("p1", "user", "Rewrite the changelog for the release"),
                _codex_message("p2", "assistant", "Reading the tags now.", ts="2026-08-17T02:01Z"),
            ]
        )
        self.assertEqual("Rewrite the changelog for the release", result["goal"])

    def test_the_pi_and_droid_shape_still_parses(self) -> None:
        # The union is additive on purpose. Falsifying edit: gate the shapes on a
        # `harness` argument and this fixture stops parsing.
        result = self.analyze(
            [
                _pi_session("shape-001"),
                _pi_message("m1", None, "user", "Rewrite the changelog for the release"),
                _pi_message("m2", "m1", "assistant", "Reading the tags now."),
            ]
        )
        self.assertEqual("Rewrite the changelog for the release", result["goal"])

    def test_an_injected_shape_is_never_published_as_the_goal(self) -> None:
        # The whole reason this change could not ship on the parser alone. Each
        # pair below is one harness's own machinery in the user channel; the
        # analyzer must fall back to the sentinel rather than publish it.
        for label, lines in (
            (
                "claude-tag",
                [
                    _claude_message(
                        "u1", "user", "<task-notification>agent done</task-notification>"
                    ),
                    _claude_message("u2", "assistant", "Acknowledged.", ts="2026-08-17T02:01:00Z"),
                ],
            ),
            (
                "claude-compaction",
                [
                    _claude_message(
                        "u1", "user", "Analyze this conversation and determine what happened."
                    ),
                    _claude_message("u2", "assistant", "Acknowledged.", ts="2026-08-17T02:01:00Z"),
                ],
            ),
            (
                "claude-sidechain",
                [
                    _claude_message(
                        "u1", "user", "Search the tree for the dead route", sidechain=True
                    ),
                    _claude_message("u2", "assistant", "Acknowledged.", ts="2026-08-17T02:01:00Z"),
                ],
            ),
            (
                "claude-meta",
                [
                    _claude_message("u1", "user", "Set the model to opus", meta=True),
                    _claude_message("u2", "assistant", "Acknowledged.", ts="2026-08-17T02:01:00Z"),
                ],
            ),
            (
                "codex-tag",
                [
                    _codex_session_meta("019f1c51-6cf9-7981-9a2d-172428800001"),
                    _codex_message("p1", "user", "<recommended_plugins>\nHere is a list."),
                    _codex_message("p2", "assistant", "Acknowledged.", ts="2026-08-17T02:01Z"),
                ],
            ),
            (
                "codex-prose",
                [
                    _codex_session_meta("019f1c51-6cf9-7981-9a2d-172428800002"),
                    _codex_message("p1", "user", "# AGENTS.md instructions for /home/test/project"),
                    _codex_message("p2", "assistant", "Acknowledged.", ts="2026-08-17T02:01Z"),
                ],
            ),
        ):
            with self.subTest(shape=label):
                result = self.analyze(lines)
                self.assertEqual(observer.NO_GOAL, result["goal"])
                # Assistant work exists, so this is the "unknown, not
                # fabricated" branch rather than the generic-opener one.
                self.assertIsNone(result["reason"])

    def test_a_slash_command_is_the_operators_intent_and_is_published(self) -> None:
        # The deliberate carve-out. `records.injected_prompt` does not reject the
        # slash-command wrappers, because a slash command is what the person
        # asked for, spelled in the harness's markup — and `transcripts.prompt_title`
        # owns reading it back out. Falsifying edit: add `command-message` to
        # `records._CLAUDE_USER_TAGS` and this session loses its goal entirely.
        result = self.analyze(
            [
                _claude_message(
                    "u1",
                    "user",
                    "<command-message>code-review is running…</command-message>\n"
                    "<command-name>/code-review</command-name>\n"
                    "<command-args>1287 with fresh eyes</command-args>",
                ),
                _claude_message("u2", "assistant", "Reading the diff.", ts="2026-08-17T02:01:00Z"),
            ]
        )
        self.assertEqual("/code-review 1287 with fresh eyes", result["goal"])

    def test_a_bare_harness_control_command_is_not_an_objective(self) -> None:
        # `/clear`, `/login`, `/plugin`, `/mcp` and the rest drive the harness,
        # not the work, and they rendered into the ordinary goal slot looking
        # exactly like a derived objective: 200 of 1,469 published Claude goals
        # (13.6%) and 4 of 141 Codex ones.
        #
        # The guard beside this one could not fire, and the reason is an
        # ordering bug rather than a missing rule: `_is_generic_opener` reads the
        # RAW `<command-name>/clear</command-name>` spelling while the value
        # actually published is `prompt_title(raw)` — `/clear`. The two
        # spellings never meet. Falsifying edit: move the `_is_harness_control`
        # test off the rendered value and back onto `msg["text"]`.
        for harness, lines in (
            (
                "claude",
                [
                    _claude_message(
                        "u1",
                        "user",
                        "<command-message>clear</command-message>\n"
                        "<command-name>/clear</command-name>\n"
                        "<command-args></command-args>",
                    ),
                    _claude_message("u2", "assistant", "Cleared.", ts="2026-08-17T02:01:00Z"),
                ],
            ),
            (
                "codex",
                [
                    _codex_session_meta("019f1c51-6cf9-7981-9a2d-172428800009"),
                    _codex_message("p1", "user", "/login"),
                    _codex_message("p2", "assistant", "Signed in.", ts="2026-08-17T02:01Z"),
                ],
            ),
        ):
            with self.subTest(harness=harness):
                self.assertEqual(observer.NO_GOAL, self.analyze(lines)["goal"])

    def test_a_control_command_does_not_displace_the_objective_beneath_it(self) -> None:
        # The rejection happens where `_is_generic_opener`'s does — over the
        # directive list — rather than at the point of publication, so the real
        # objective the session already contains survives the `/clear` typed
        # after it. Measured: 25 of the 200 Claude cases are this shape.
        result = self.analyze(
            [
                _claude_message(
                    "u1", "user", "Fix the flaky quota test", ts="2026-08-17T02:00:00Z"
                ),
                _claude_message("u2", "assistant", "On it.", ts="2026-08-17T02:01:00Z"),
                _claude_message(
                    "u3",
                    "user",
                    "<command-name>/clear</command-name>",
                    ts="2026-08-17T02:02:00Z",
                ),
            ]
        )
        self.assertEqual("Fix the flaky quota test", result["goal"])

    def test_a_bare_skill_invocation_is_still_an_objective(self) -> None:
        # The rule is a measured name list and NOT "a bare command carries no
        # arguments, so it carries no goal". That structural rule was checked
        # against the same corpus and is wrong: 39 further bare-command goals
        # are skill invocations, and a skill invoked with no arguments is
        # exactly what the operator asked for. Falsifying edit: reject on
        # `_BARE_COMMAND_RE` alone and this goal disappears.
        result = self.analyze(
            [
                _claude_message(
                    "u1",
                    "user",
                    # The recorded shape: a prompt command opens with `<command-message>`.
                    "<command-message>create-pr</command-message>\n"
                    "<command-name>/create-pr</command-name>",
                ),
                _claude_message("u2", "assistant", "Opening it.", ts="2026-08-17T02:01:00Z"),
            ]
        )
        self.assertEqual("/create-pr", result["goal"])

    def test_the_injected_tag_set_is_gated_on_the_record_s_harness(self) -> None:
        # Each arm of `_parse_message_record` hands `injected_prompt` its own
        # harness literal, and nothing else in the suite pinned that: mutating
        # the Claude arm's literal to `"codex"` left the whole suite green while
        # degrading 4 real Claude goals, every one of them a `<system-reminder>`
        # published as the operator's objective.
        #
        # Two directions, because one literal per arm needs one test per arm.
        # Falsifying edits: `"claude"` -> `"codex"` in `_claude_message`, and
        # `"codex"` -> `"claude"` in the `response_item` branch.
        claude_only = self.analyze(
            [
                _claude_message(
                    "u1",
                    "user",
                    "<system-reminder>\nYou are running in non-interactive mode.",
                ),
                _claude_message("u2", "assistant", "Understood.", ts="2026-08-17T02:01:00Z"),
            ]
        )
        self.assertEqual(observer.NO_GOAL, claude_only["goal"])
        codex_only = self.analyze(
            [
                _codex_session_meta("019f1c51-6cf9-7981-9a2d-172428800010"),
                _codex_message("p1", "user", "<recommended_plugins>\nHere is a list."),
                _codex_message("p2", "assistant", "Understood.", ts="2026-08-17T02:01Z"),
            ]
        )
        self.assertEqual(observer.NO_GOAL, codex_only["goal"])

    def test_the_newest_directive_is_the_newest_by_stamp_not_by_position(self) -> None:
        # `_extract_messages` concatenates the head window and the tail window,
        # and `_derive_goal_deterministic` takes `directives[-1]`, so "newest"
        # used to mean "last in that concatenation". File position is not record
        # order: a resumed Claude session replays the earlier transcript's
        # records into the new file, and the replayed block carries its original
        # stamps while sitting after records written later.
        #
        # Falsifying edit: drop the `ordered.sort` in `_extract_messages` — the
        # goal then becomes "the replayed opening prompt".
        result = self.analyze(
            [
                _claude_message("u1", "user", "the newest prompt", ts="2026-08-17T09:00:00Z"),
                _claude_message("u2", "assistant", "Working.", ts="2026-08-17T09:01:00Z"),
                _claude_message(
                    "u3", "user", "the replayed opening prompt", ts="2026-08-17T02:00:00Z"
                ),
            ]
        )
        self.assertEqual("the newest prompt", result["goal"])

    def _two_window_lines(self) -> list[str]:
        """A transcript whose goal is only in the head and whose block is only in
        the tail, at the shrunk window sizes the caller passes."""
        filler = [
            _claude_message(f"f{i}", "assistant", "x" * 200, ts=f"2026-08-17T02:{i:02d}:00Z")
            for i in range(2, 40)
        ]
        return [
            _claude_message("u1", "user", "the opening prompt", ts="2026-08-17T02:00:00Z"),
            *filler,
            _claude_message(
                "u2", "assistant", "I am blocked on a missing token.", ts="2026-08-17T02:59:00Z"
            ),
        ]

    def test_the_head_window_and_the_tail_window_are_both_read(self) -> None:
        # The two windows are disjoint on any file over head + tail (465,536 B
        # with the shipped figures), and the opening directive lives in the head.
        # The windows are shrunk here rather than the file grown: a 465 KB
        # fixture proves the same thing and costs a disk write per run.
        #
        # Both readings are asserted, and the second one is the point: this test
        # asserted the GOAL alone, which comes out of the head, so stubbing
        # `read_tail` to return nothing left it green. The block comes only out
        # of the tail, so it fails when either window is not read.
        result = self.analyze(self._two_window_lines(), observer_head_bytes=1_200, tail_bytes=1_200)
        self.assertEqual("the opening prompt", result["goal"])
        self.assertEqual("I am blocked on a missing token.", result["block"])

    def test_the_tail_assertion_is_load_bearing(self) -> None:
        # The falsification, committed rather than described: with `read_tail`
        # stubbed out the head still supplies the goal, and only the block
        # disappears. If a later edit makes the block reachable from the head,
        # this fails and the test above stops proving anything.
        with mock.patch.object(runtime_io, "read_tail", return_value=[]):
            result = self.analyze(
                self._two_window_lines(), observer_head_bytes=1_200, tail_bytes=1_200
            )
        self.assertEqual("the opening prompt", result["goal"])
        self.assertEqual("", result["block"])

    def test_a_repeated_prompt_does_not_keep_its_oldest_position(self) -> None:
        # The dedup key read `record["id"]`, which **0 of 8,312 Claude and 0 of
        # 14,389 Codex records carry**, so it degraded silently to the message
        # text: a prompt repeated verbatim later in the session was dropped as a
        # duplicate of its own first occurrence, and the goal stayed on whatever
        # came between them. Falsifying edit: key on `record.get("id")` again.
        result = self.analyze(
            [
                _claude_message("u1", "user", "align the release notes", ts="2026-08-17T02:00:00Z"),
                _claude_message("u2", "user", "run the migration", ts="2026-08-17T02:01:00Z"),
                _claude_message("u3", "user", "align the release notes", ts="2026-08-17T02:02:00Z"),
                _claude_message("u4", "assistant", "On it.", ts="2026-08-17T02:03:00Z"),
            ]
        )
        self.assertEqual("align the release notes", result["goal"])

    def test_a_repeated_codex_prompt_with_no_payload_id_keeps_the_newest(self) -> None:
        # The same bug where it actually bites. `payload.id` is absent on 599 of
        # the 784 Codex user-message records (76.4%) inside the observer's own
        # windows, so the key falls through to the fallback on three records in
        # four — and every Codex fixture here used to write the id-carrying
        # minority, which is why this went untested. Falsifying edit: make the
        # fallback `parsed["text"]` again and the goal becomes "run the
        # migration".
        result = self.analyze(
            [
                _codex_session_meta("019f1c51-6cf9-7981-9a2d-172428800011"),
                _codex_message(None, "user", "align the release notes", ts="2026-08-17T02:00:00Z"),
                _codex_message(None, "user", "run the migration", ts="2026-08-17T02:01:00Z"),
                _codex_message(None, "user", "align the release notes", ts="2026-08-17T02:02:00Z"),
                _codex_message(None, "assistant", "On it.", ts="2026-08-17T02:03:00Z"),
            ]
        )
        self.assertEqual("align the release notes", result["goal"])

    def test_a_replayed_record_is_still_deduped_by_its_own_id(self) -> None:
        # The positional fallback must not cost the case the key exists for: a
        # resumed transcript replays earlier records into the new file, carrying
        # their original ids and their original stamps. Falsifying edit: drop the
        # `seen` set — the replayed opener is then read twice, and the second
        # copy is what `directives[-1]` would have to sort past.
        lines = [
            _claude_message("u1", "user", "the opening prompt", ts="2026-08-17T02:00:00Z"),
            _claude_message("u2", "assistant", "Working.", ts="2026-08-17T02:01:00Z"),
        ]
        config = dataclasses.replace(self.config)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")
            messages = observer._extract_messages(config, str(path))
        self.assertEqual(
            [("user", "the opening prompt"), ("assistant", "Working.")],
            [(m["role"], m["text"]) for m in messages],
        )

    def test_a_clipped_goal_keeps_its_ellipsis(self) -> None:
        # `prompt_title` appends the ellipsis AFTER cutting to the cap, so a
        # clipped goal is cap + 1 characters and a scrub at the cap took the `…`
        # straight back off — an unmarked mid-token cut on 8 of the 1,295 goals
        # the local Claude corpus publishes. Falsifying edit: drop the `+ 1` from
        # the `safe_text` bound in `_derive_goal_deterministic`.
        # One long token, so `clip` finds no word boundary in the last third and
        # cuts hard at the cap: that is the shape whose ellipsis is the 201st
        # character and therefore the one the scrub used to remove.
        cap = self.config.observer_goal_cap_chars
        result = self.analyze(
            [
                _claude_message("u1", "user", "x" * (cap + 50)),
                _claude_message("u2", "assistant", "On it.", ts="2026-08-17T02:01:00Z"),
            ]
        )
        self.assertEqual("x" * cap + "…", result["goal"])

    def test_a_tool_result_echo_is_not_a_directive(self) -> None:
        # A user turn whose content is a tool_result is the harness echoing its
        # own output back, on every one of the three shapes.
        result = self.analyze(
            [
                _claude_message("u1", "user", "Fix the failing build", ts="2026-08-17T02:00:00Z"),
                _claude_message(
                    "u2",
                    "user",
                    [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
                    ts="2026-08-17T02:05:00Z",
                ),
            ]
        )
        self.assertEqual("Fix the failing build", result["goal"])


class CachedDeterministicGoalTest(unittest.TestCase):
    def test_only_saved_deterministic_words_reach_the_board(self) -> None:
        cases: tuple[tuple[dict[str, Any], str | None], ...] = (
            ({"goal": "Saved", "goal_source": "deterministic"}, "Saved"),
            ({"goal": "Model", "goal_source": "model"}, None),
            ({"goal": "Unknown"}, None),
            ({"goal": "Unknown", "goal_source": []}, None),
            ({"goal": "Model", "goal_source": "model", "deterministic_goal": "Saved"}, "Saved"),
            ({"deterministic_goal": "Saved", "transcript": ["stale", 1]}, "Saved"),
            ({"deterministic_goal": {"text": "Malformed"}}, None),
            ({"deterministic_goal": " \u202e\u0000 "}, None),
            ({"deterministic_goal": "No goal derived."}, None),
            ({"goal": "no goal derived", "goal_source": "deterministic"}, None),
            ({}, None),
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = dataclasses.replace(make_config(), state_dir=Path(tmp))
            for payload, expected in cases:
                with self.subTest(payload=payload):
                    observer.write_sidecar(config, "codex", "saved", payload)
                    result = observer.cached_deterministic_goal(config, "codex", "saved")
                    if expected is None:
                        self.assertIsNone(result)
                    else:
                        self.assertEqual(
                            {"goal": expected, "source": "deterministic", "observed_at": None},
                            result,
                        )

    def test_a_saved_time_is_preserved_or_unknown_never_invented(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = dataclasses.replace(make_config(), state_dir=Path(tmp))
            at: object
            for at in (150.5, None, True, "150", [], -1, 0, float("nan"), float("inf"), 10**400):
                with self.subTest(at=at):
                    observer.write_sidecar(
                        config, "pi", "saved", {"deterministic_goal": "Ship it", "observed_at": at}
                    )
                    result = observer.cached_deterministic_goal(config, "pi", "saved")
                    self.assertIsNotNone(result)
                    assert result is not None
                    self.assertEqual(150.5 if at == 150.5 else None, result["observed_at"])

    def test_hostile_saved_words_are_scrubbed_before_the_existing_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = dataclasses.replace(make_config(), state_dir=Path(tmp))
            cap = config.observer_goal_cap_chars
            secret = "sk-proj-" + "a" * 160
            observer.write_sidecar(
                config,
                "pi",
                "saved",
                {"deterministic_goal": "\u202eShip\u0000 " + "x" * (cap - 30) + " " + secret},
            )
            result = observer.cached_deterministic_goal(config, "pi", "saved")
            assert result is not None
            self.assertNotIn("a" * 20, result["goal"])
            self.assertNotIn("\u202e", result["goal"])
            self.assertNotIn("\u0000", result["goal"])
            self.assertIn("REDACTED", result["goal"])
            self.assertLessEqual(len(result["goal"]), cap)

    def test_absent_unreadable_and_oversized_sidecars_publish_no_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = dataclasses.replace(
                make_config(), state_dir=Path(tmp), state_read_cap_bytes=80
            )
            self.assertIsNone(observer.cached_deterministic_goal(config, "pi", "missing"))
            path = observer.write_sidecar(config, "pi", "saved", {})
            assert path is not None
            for raw in ("{", "[]", '\u007b"deterministic_goal":"' + "x" * 100 + '"}'):
                Path(path).write_text(raw, encoding="utf-8")
                self.assertIsNone(observer.cached_deterministic_goal(config, "pi", "saved"))
            with mock.patch("builtins.open", side_effect=OSError("unreadable")):
                self.assertIsNone(observer.cached_deterministic_goal(config, "pi", "saved"))


class ObserverTranscriptResolutionTest(RuntimeTestCase):
    """Which transcript `/api/observe?harness=&sid=` resolves to, per harness."""

    def test_a_claude_transcript_resolves_one_directory_down(self) -> None:
        # `projects/<encoded-cwd>/<session-id>.jsonl`, which is how
        # `collectors/claude.py` globs it. A flat `*.jsonl` matched nothing, so
        # `?harness=claude` was a 404 on every machine — the route advertised a
        # harness it could never answer for.
        sid = "abcdef12-3456-7890-abcd-ef1234567890"
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            (projects / "-home-me-repo").mkdir(parents=True)
            wanted = projects / "-home-me-repo" / f"{sid}.jsonl"
            wanted.write_text("{}\n", encoding="utf-8")
            with store_patch(PROJECTS_DIR=str(projects)):
                config, state = runtime()
                found = observer.resolve_transcript(config, state, "claude", sid)
                # The dashboard shortens an id for display, so a prefix resolves.
                short = observer.resolve_transcript(config, state, "claude", sid[:8])
        self.assertEqual(str(wanted), found)
        self.assertEqual(str(wanted), short)

    def test_an_ambiguous_claude_prefix_resolves_to_nothing(self) -> None:
        # Codex-style time-ordered ids share long prefixes, and the old
        # `sid in basename` substring match handed back whichever transcript
        # happened to contain the characters. Two candidates is no answer.
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            (projects / "-home-me-repo").mkdir(parents=True)
            for suffix in ("aa", "bb"):
                (projects / "-home-me-repo" / f"sess-{suffix}.jsonl").write_text("{}\n")
            with store_patch(PROJECTS_DIR=str(projects)):
                config, state = runtime()
                self.assertIsNone(observer.resolve_transcript(config, state, "claude", "sess-"))

    def test_a_codex_rollout_resolves_by_session_meta_and_newest_wins(self) -> None:
        # A rollout's uuid sits at the END of `rollout-<timestamp>-<uuid>.jsonl`,
        # so the Claude branch's stem `startswith` cannot be reused; the id is
        # matched against `session_meta` instead, which is the field
        # `collectors/codex.py` keys on.
        #
        # Newest mtime and not the first match, because one `session_id` is
        # legitimately spread over several files: a resume and each subagent
        # thread write their own rollout under it. The first by glob order is the
        # oldest — the one nothing is being written to.
        sid = "019f1c51-6cf9-7981-9a2d-172428800003"
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "2026" / "08" / "17"
            day.mkdir(parents=True)
            older = day / f"rollout-2026-08-17T01-00-00-{sid}.jsonl"
            newer = day / f"rollout-2026-08-17T09-00-00-{sid}.jsonl"
            other = day / "rollout-2026-08-17T10-00-00-019f1c51-6cf9-7981-9a2d-172428800004.jsonl"
            for path, resumed in ((older, sid), (newer, sid), (other, "other-session")):
                path.write_text(_codex_session_meta(resumed) + "\n", encoding="utf-8")
            os.utime(str(older), (1_700_000_000, 1_700_000_000))
            os.utime(str(newer), (1_700_000_900, 1_700_000_900))
            with store_patch(CODEX_SESSIONS_DIR=str(tmp)):
                config, state = runtime()
                found = observer.resolve_transcript(config, state, "codex", sid)
        self.assertEqual(str(newer), found)

    def test_a_subagent_rollout_never_stands_in_for_its_parent(self) -> None:
        # A subagent thread's rollout carries its PARENT's `session_id` — 262 of
        # 262 locally — so a max-mtime pick over the id alone hands back the
        # child whenever the child is the file being written, and `analyze` then
        # publishes the parent agent's dispatch prompt as the operator's goal.
        # In 262 of 262 local subagent runs there is a window where that is what
        # the resolver returns (32.8 h of 102.8 h of aggregate subagent
        # wall-clock); the static corpus shows 0 only because each of its 31
        # mixed groups was captured after the parent resumed writing, which is
        # exactly why a fixture is needed rather than a corpus count.
        #
        # Falsifying edit: drop the `meta.get("subagent")` test from the Codex
        # branch of `resolve_transcript` and the NEWER child file is returned.
        sid = "019f1c51-6cf9-7981-9a2d-172428800005"
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "2026" / "08" / "17"
            day.mkdir(parents=True)
            parent = day / f"rollout-2026-08-17T01-00-00-{sid}.jsonl"
            child = day / "rollout-2026-08-17T09-00-00-019f1c51-6cf9-7981-9a2d-172428800006.jsonl"
            parent.write_text(_codex_session_meta(sid) + "\n", encoding="utf-8")
            # The child declares the parent's id, which is the whole collision.
            child.write_text(_codex_session_meta(sid, subagent=True) + "\n", encoding="utf-8")
            os.utime(str(parent), (1_700_000_000, 1_700_000_000))
            os.utime(str(child), (1_700_000_900, 1_700_000_900))
            with store_patch(CODEX_SESSIONS_DIR=str(tmp)):
                config, state = runtime()
                found = observer.resolve_transcript(config, state, "codex", sid)
        self.assertEqual(str(parent), found)

    def test_a_session_that_is_only_a_subagent_thread_resolves_to_nothing(self) -> None:
        # The exclusion is not "prefer the parent", it is "a child is never the
        # answer": a subagent rollout is not a session a person opened.
        sid = "019f1c51-6cf9-7981-9a2d-172428800007"
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "2026" / "08" / "17"
            day.mkdir(parents=True)
            child = day / "rollout-2026-08-17T09-00-00-019f1c51-6cf9-7981-9a2d-172428800008.jsonl"
            child.write_text(_codex_session_meta(sid, subagent=True) + "\n", encoding="utf-8")
            with store_patch(CODEX_SESSIONS_DIR=str(tmp)):
                config, state = runtime()
                self.assertIsNone(observer.resolve_transcript(config, state, "codex", sid))

    def test_an_unregistered_harness_and_an_unnamed_id_resolve_to_nothing(self) -> None:
        # The Codex store is patched to an empty directory on purpose: without
        # it `runtime()` resolves the developer's real `~/.codex/sessions`, and
        # this assertion passed vacuously on a machine with no rollouts.
        with tempfile.TemporaryDirectory() as tmp, store_patch(CODEX_SESSIONS_DIR=tmp):
            config, state = runtime()
            self.assertIsNone(observer.resolve_transcript(config, state, "codex", "abc"))
            self.assertIsNone(observer.resolve_transcript(config, state, "gemini", "abc"))
            self.assertIsNone(observer.resolve_transcript(config, state, "pi", "a/../b"))

    def test_a_codex_session_id_resolves_through_first_line_metadata(self) -> None:
        sid = "01a035ee-2a7b-76f0-873f-eaddc97860c3"
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            rollout = sessions / "2026" / "08" / "24" / f"rollout-{sid}.jsonl"
            rollout.parent.mkdir(parents=True)
            rollout.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {"id": sid, "cwd": "/repo", "source": "cli"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with store_patch(CODEX_SESSIONS_DIR=str(sessions)):
                config, state = runtime()
                found = observer.resolve_transcript(config, state, "codex", sid)

        self.assertEqual(str(rollout), found)

    def test_a_codex_child_thread_id_resolves_to_its_rollout(self) -> None:
        root_sid = "11111111-1111-1111-1111-111111111111"
        child_sid = "22222222-2222-2222-2222-222222222222"
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            rollout = sessions / "2026" / "01" / "01" / "rollout-child.jsonl"
            rollout.parent.mkdir(parents=True)
            rollout.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": child_sid,
                            "session_id": root_sid,
                            "thread_source": "subagent",
                            "source": {
                                "subagent": {"thread_spawn": {"parent_thread_id": root_sid}}
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with store_patch(CODEX_SESSIONS_DIR=str(sessions)):
                config, state = runtime()
                found = observer.resolve_transcript(config, state, "codex", child_sid)

        self.assertEqual(str(rollout), found)


class ObserverRouteTest(RuntimeTestCase):
    """`GET /api/observe`, which had no test of its own."""

    def _get(self, server: Any, query: str) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request("GET", "/api/observe" + query)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response.status, body

    def test_the_route_answers_with_the_sidecar_and_writes_it(self) -> None:
        # A CLAUDE-shaped record in the Claude store. It used to be Pi's
        # `type: "message"` shape — which occurs 0 times in 3,774 real Claude
        # transcripts — so the only end-to-end test of this route exercised a
        # parser arm the route can never reach on a real machine.
        sid = "abcdef12-3456-7890-abcd-ef1234567890"
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            (projects / "-home-me-repo").mkdir(parents=True)
            (projects / "-home-me-repo" / f"{sid}.jsonl").write_text(
                "\n".join(
                    [
                        _claude_message("u1", "user", "Fix the failing build"),
                        _claude_message(
                            "u2",
                            "assistant",
                            [{"type": "text", "text": "I am blocked on a missing token."}],
                            ts="2026-08-17T02:01:00Z",
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            home = Path(tmp) / "compass-home"
            with (
                store_patch(PROJECTS_DIR=str(projects)),
                mock.patch.dict(os.environ, {"COMPASS_HOME": str(home)}),
            ):
                httpd = make_server()
                thread = threading.Thread(target=poll_fast(httpd), daemon=True)
                thread.start()
                try:
                    status, body = self._get(httpd, f"?harness=claude&sid={sid}")
                    missing, _ = self._get(httpd, "?harness=claude&sid=deadbeef")
                    unnamed, _ = self._get(httpd, "?harness=claude&sid=a%2Fb")
                    bare, _ = self._get(httpd, "?harness=claude")
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)
                # The path the *server's* config resolves, not a second one: the
                # store home comes off the environment and both must agree. And
                # checked in here, before the temp tree is torn down.
                sidecar = observer.sidecar_path(httpd.application.config, "claude", sid)
                assert sidecar is not None
                wrote_sidecar = os.path.isfile(sidecar)

        self.assertEqual(200, status)
        payload = json.loads(body)
        self.assertIn("Fix the failing build", payload["goal"])
        self.assertEqual("I am blocked on a missing token.", payload["block"])
        self.assertEqual("", payload["stage"])  # no workflow booted
        # A sid that resolves to no transcript is a 404, not an empty 200: the
        # panel must be able to tell "nothing to observe" from "nothing found".
        self.assertEqual(404, missing)
        # A sid that is not a name never reaches the resolver.
        self.assertEqual(404, unnamed)
        self.assertEqual(400, bare)
        self.assertTrue(wrote_sidecar)

    def test_the_route_answers_for_a_codex_rollout(self) -> None:
        # The route advertises three harnesses and only one of them had an
        # end-to-end test. Codex reaches every arm differently: the resolver
        # matches `session_meta` rather than a filename stem, the parser reads
        # `response_item` rather than `type: "user"`, and the records carry no
        # `payload.id` — the majority shape on a real store.
        sid = "019f1c51-6cf9-7981-9a2d-172428800012"
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "sessions" / "2026" / "08" / "17"
            day.mkdir(parents=True)
            (day / f"rollout-2026-08-17T02-00-00-{sid}.jsonl").write_text(
                "\n".join(
                    [
                        _codex_session_meta(sid),
                        _codex_message(None, "user", "Rewrite the changelog for the release"),
                        _codex_message(
                            None,
                            "assistant",
                            "I am blocked on a missing token.",
                            ts="2026-08-17T02:01:00Z",
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            home = Path(tmp) / "compass-home"
            with (
                store_patch(CODEX_SESSIONS_DIR=str(Path(tmp) / "sessions")),
                mock.patch.dict(os.environ, {"COMPASS_HOME": str(home)}),
            ):
                httpd = make_server()
                thread = threading.Thread(target=poll_fast(httpd), daemon=True)
                thread.start()
                try:
                    status, body = self._get(httpd, f"?harness=codex&sid={sid}")
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)
                sidecar = observer.sidecar_path(httpd.application.config, "codex", sid)
                assert sidecar is not None
                wrote_sidecar = os.path.isfile(sidecar)

        self.assertEqual(200, status)
        payload = json.loads(body)
        self.assertEqual("Rewrite the changelog for the release", payload["goal"])
        self.assertEqual("I am blocked on a missing token.", payload["block"])
        self.assertEqual("", payload["stage"])  # no workflow booted
        self.assertTrue(wrote_sidecar)


class CodexExecArgvTest(unittest.TestCase):
    """Every flag that sandboxes the model call, pinned.

    Nothing in this suite asserted any of them before this class existed: a
    change that dropped `--sandbox read-only`, `--ignore-user-config` or any of
    the feature disables would have shipped green. That matters more now than
    it did, because a second lane is about to call the same subprocess and a
    lane that quietly ran unsandboxed would look exactly like one that did not.
    """

    def _capture(self) -> tuple[list[Any], observer.CodexGoalModel]:
        seen: list[Any] = []

        def runner(command: Any, **kwargs: Any) -> Any:
            seen.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")

        config = dataclasses.replace(
            make_config(), observer_model_enabled=True, state_dir=Path(tempfile.mkdtemp())
        )
        caller = observer.CodexGoalModel(
            config,
            runner=runner,
            binary_resolver=mock.Mock(return_value="/usr/bin/codex"),
            consent=True,
            session_key="codex:one",
        )
        return seen, caller

    def test_the_model_call_is_sandboxed_ephemeral_and_ignores_local_configuration(self) -> None:
        seen, caller = self._capture()
        caller("a transcript tail", "stage")

        self.assertEqual(1, len(seen), "the model was not invoked exactly once")
        command, kwargs = seen[0]

        self.assertEqual("/usr/bin/codex", command[0])
        self.assertEqual("exec", command[1])
        self.assertEqual("-", command[-1], "the prompt must arrive on stdin, never as an argument")

        for flag in (
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-rules",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, command)

        for pair in (
            ("--sandbox", "read-only"),
            ("--model", observer.OBSERVER_MODEL),
            ("--config", 'web_search="disabled"'),
            ("--config", "project_doc_max_bytes=0"),
            ("--config", "skills.include_instructions=false"),
            ("--config", f"model_reasoning_effort={observer.OBSERVER_MODEL_REASONING_EFFORT}"),
        ):
            with self.subTest(pair=pair):
                # The VALUE that follows this flag, not merely the flag's
                # presence: `--sandbox` with the wrong mode is the failure.
                values = [command[i + 1] for i, tok in enumerate(command[:-1]) if tok == pair[0]]
                self.assertIn(pair[1], values)

        self.assertEqual(subprocess.DEVNULL, kwargs["stdout"])
        self.assertEqual(subprocess.DEVNULL, kwargs["stderr"])
        self.assertEqual(observer.OBSERVER_MODEL_TIMEOUT_SEC, kwargs["timeout"])
        self.assertFalse(kwargs["check"], "a raising subprocess would crash a collection")
        self.assertEqual(str(caller.config.state_dir), kwargs["cwd"])

    def test_every_execution_and_integration_feature_is_disabled_on_the_command(self) -> None:
        seen, caller = self._capture()
        caller("a transcript tail", "stage")
        command, _ = seen[0]

        # Read-only sandboxing still permits reading files, and ignoring user
        # config still leaves default-on hooks and plugin discovery available.
        self.assertGreaterEqual(
            len(observer._MODEL_DISABLED_FEATURES),
            14,
            "a feature was removed from the disable list rather than from Codex",
        )
        for feature in observer._MODEL_DISABLED_FEATURES:
            with self.subTest(feature=feature):
                self.assertIn(f"features.{feature}=false", command)

    def test_the_prompt_reaches_the_model_on_stdin_and_never_on_disk(self) -> None:
        seen, caller = self._capture()
        caller("a transcript tail", "stage")
        _, kwargs = seen[0]

        self.assertIn("a transcript tail", kwargs["input"])
        self.assertTrue(kwargs["text"])
        self.assertEqual("utf-8", kwargs["encoding"])


class ClaudeExecTest(unittest.TestCase):
    """The Claude Code reading call, pinned flag by flag (DRC-4650).

    Claude Code has no `--sandbox read-only`. What removes its capabilities is
    a set of CLI flags, so each one is asserted on its own: a change that drops
    any single flag must turn one subtest red rather than leave the call
    looking exactly like a restricted one.
    """

    PROMPT = "read this session against: ship the parser"

    def _config(self) -> Any:
        state_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, state_dir, True)
        return dataclasses.replace(make_config(), state_dir=state_dir)

    def _run(
        self,
        *,
        reply: bytes = b"{}",
        returncode: int = 0,
        raises: BaseException | None = None,
        binary: str | None = "/usr/local/bin/claude",
        cap: int = 1920,
    ) -> tuple[list[tuple[list[str], dict[str, Any], dict[str, Any]]], str, str, Any]:
        config = self._config()
        seen: list[tuple[list[str], dict[str, Any], dict[str, Any]]] = []

        def runner(command: list[str], **kwargs: Any) -> Any:
            cwd = Path(kwargs["cwd"])
            observed = {
                "cwd_exists": cwd.is_dir(),
                "cwd_mode": cwd.stat().st_mode & 0o777 if cwd.is_dir() else None,
                "cwd_entries": sorted(os.listdir(cwd)) if cwd.is_dir() else None,
            }
            seen.append((list(command), kwargs, observed))
            if raises is not None:
                raise raises
            kwargs["stdout"].write(reply)
            return subprocess.CompletedProcess(command, returncode)

        text, status = observer.claude_exec(
            config,
            self.PROMPT,
            output_cap_bytes=cap,
            runner=runner,
            binary_resolver=mock.Mock(return_value=binary),
        )
        return seen, text, status, config

    @staticmethod
    def _values(command: list[str], flag: str) -> list[str]:
        return [command[i + 1] for i, tok in enumerate(command[:-1]) if tok == flag]

    def test_a_reading_by_claude_code_runs_with_every_capability_removing_flag(self) -> None:
        seen, _text, status, _config = self._run()
        self.assertEqual("ok", status)
        self.assertEqual(1, len(seen), "the model was not invoked exactly once")
        command = seen[0][0]
        self.assertEqual("/usr/local/bin/claude", command[0])
        for flag in (
            "--print",
            "--safe-mode",
            "--restricted",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-chrome",
            "--no-session-persistence",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, command)
        for flag, value in (
            ("--tools", ""),
            ("--mcp-config", observer.CLAUDE_EMPTY_MCP_CONFIG),
            ("--permission-mode", "dontAsk"),
            ("--permission-prompts", "none"),
            ("--output-format", "text"),
            ("--model", observer.CLAUDE_READING_MODEL),
            ("--effort", observer.CLAUDE_READING_EFFORT),
        ):
            with self.subTest(flag=flag):
                # The value after the flag, not the flag's presence: an empty
                # tool set and a default one differ only in that token.
                self.assertEqual([value], self._values(command, flag))

    def test_a_fixed_system_prompt_replaces_claude_codes_default(self) -> None:
        # DRC-4666, owner ruling: Claude Code's default system prompt is not
        # the reader's to send. `--system-prompt` replaces it whole;
        # `--append-system-prompt` would keep it, so it must never appear.
        seen, _text, _status, _config = self._run()
        command = seen[0][0]
        self.assertEqual(
            [observer.CLAUDE_READING_SYSTEM_PROMPT], self._values(command, "--system-prompt")
        )
        self.assertNotIn("--append-system-prompt", command)
        self.assertNotIn("--system-prompt-file", command)

    def test_the_fixed_system_prompt_names_nothing_of_this_machine(self) -> None:
        text = observer.CLAUDE_READING_SYSTEM_PROMPT
        self.assertTrue(text.strip())
        self.assertEqual(text, " ".join(text.split()), "one line, no layout to carry anything")
        home = str(Path.home())
        for leaked in (home, os.getcwd(), os.environ.get("USER") or "\0", "/", "\\", "~"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, text)
        self.assertFalse(text.startswith("-"), "a value, never read as a flag")

    def test_the_empty_mcp_config_names_no_server(self) -> None:
        self.assertEqual({"mcpServers": {}}, json.loads(observer.CLAUDE_EMPTY_MCP_CONFIG))

    def test_the_default_reading_model_is_explicit_and_the_effort_is_bounded(self) -> None:
        self.assertTrue(observer.CLAUDE_READING_MODEL.startswith("claude-"))
        self.assertIn(observer.CLAUDE_READING_EFFORT, ("low", "medium", "high"))

    def test_nothing_that_widens_the_call_is_ever_on_the_command(self) -> None:
        seen, _text, _status, _config = self._run()
        command = seen[0][0]
        for token in (
            "--bare",
            "--dangerously-skip-permissions",
            "--allow-dangerously-skip-permissions",
            "bypassPermissions",
            "--json-schema",
            "--add-dir",
            "--chrome",
            "--continue",
            "-c",
            "--resume",
            "-r",
            "--allowedTools",
            "--allowed-tools",
            "--plugin-dir",
            "--settings",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, command)

    def test_the_prompt_arrives_on_stdin_and_never_as_an_argument(self) -> None:
        seen, _text, _status, _config = self._run()
        command, kwargs, _ = seen[0]
        self.assertEqual(self.PROMPT, kwargs["input"])
        self.assertTrue(kwargs["text"])
        self.assertEqual("utf-8", kwargs["encoding"])
        self.assertNotIn(self.PROMPT, command)
        # Every token after the binary is a flag or the value of the flag
        # before it, so no positional prompt can ride along. Each value-taking
        # flag here is followed by exactly one value.
        valued = {
            "--tools",
            "--mcp-config",
            "--permission-mode",
            "--permission-prompts",
            "--output-format",
            "--model",
            "--effort",
            "--system-prompt",
        }
        index = 1
        while index < len(command):
            token = command[index]
            self.assertTrue(token.startswith("--"), f"positional token {token!r}")
            index += 2 if token in valued else 1

    def test_the_call_is_never_a_shell_and_is_timed_and_unchecked(self) -> None:
        seen, _text, _status, _config = self._run()
        command, kwargs, _ = seen[0]
        self.assertIsInstance(command, list)
        self.assertNotIn("shell", kwargs)
        self.assertNotIn("capture_output", kwargs)
        self.assertEqual(subprocess.DEVNULL, kwargs["stderr"])
        self.assertEqual(observer.OBSERVER_READING_TIMEOUT_SEC, kwargs["timeout"])
        self.assertFalse(kwargs["check"])

    def test_the_model_runs_in_a_fresh_owner_only_empty_directory(self) -> None:
        seen, _text, _status, config = self._run()
        _command, kwargs, observed = seen[0]
        cwd = Path(kwargs["cwd"])
        self.assertNotEqual(config.state_dir, cwd, "the store directory is not a scratch cwd")
        self.assertEqual(Path(tempfile.gettempdir()).resolve(), cwd.parent.resolve())
        self.assertTrue(observed["cwd_exists"])
        if os.name != "nt":  # POSIX permission bits; Windows uses ACLs
            self.assertEqual(0o700, observed["cwd_mode"])
        self.assertEqual([], observed["cwd_entries"])

    @unittest.skipIf(os.name == "nt", "the system temp directory is under the profile there")
    def test_the_working_directory_names_neither_the_home_nor_the_state_directory(self) -> None:
        # Measured 2026-09-27 on 2.1.283 against a local stub: even with
        # `--system-prompt`, the CLI sends an environment block naming its
        # working directory. Under the state directory that path carried the
        # account's home, and with it the user name (DRC-4666).
        seen, _text, _status, config = self._run()
        cwd = Path(seen[0][1]["cwd"]).resolve()
        for root in (Path.home().resolve(), Path(config.state_dir).resolve()):
            with self.subTest(root=root):
                self.assertNotEqual(root, cwd)
                self.assertNotIn(root, cwd.parents)
        self.assertFalse(cwd.exists(), "the working directory outlived the call")

    @unittest.skipIf(os.name == "nt", "the account and /tmp rules are POSIX")
    def test_a_tmpdir_under_home_falls_back_to_tmp(self) -> None:
        # Sent F2: TMPDIR under home (direnv, Nix shells, ~/tmp) put the home
        # path and user name in the environment block the CLI sends.
        fake_home = Path(tempfile.mkdtemp(), "Users", "alicequux")
        under = fake_home / "tmp"
        under.mkdir(parents=True)
        with (
            mock.patch.object(observer, "_account", return_value=(str(fake_home), "alicequux")),
            mock.patch.object(tempfile, "tempdir", str(under)),
        ):
            seen, _text, status, _config = self._run()
        self.assertEqual("ok", status)
        cwd = Path(seen[0][1]["cwd"]).resolve()
        self.assertEqual(Path("/tmp").resolve(), cwd.parent)

    @unittest.skipIf(os.name == "nt", "the account and /tmp rules are POSIX")
    def test_a_temp_path_naming_the_user_falls_back_to_tmp(self) -> None:
        named = Path(tempfile.mkdtemp(), "scratch-alicequux")
        named.mkdir()
        with (
            mock.patch.object(
                observer, "_account", return_value=("/nonexistent-home", "alicequux")
            ),
            mock.patch.object(tempfile, "tempdir", str(named)),
        ):
            seen, _text, _status, _config = self._run()
        self.assertEqual(Path("/tmp").resolve(), Path(seen[0][1]["cwd"]).resolve().parent)

    @unittest.skipIf(os.name == "nt", "the account and /tmp rules are POSIX")
    def test_a_tmpdir_under_home_spelled_in_another_case_falls_back_to_tmp(self) -> None:
        # Review N1: on a case-insensitive volume `/Users/ALICE/...` is the
        # home, and the CLI canonicalises the case before naming it. The name
        # here is short, so only the home test can catch it.
        base = Path(tempfile.mkdtemp())
        fake_home = base / "hq"
        (fake_home / "tmp").mkdir(parents=True)
        upper = base / "HQ" / "tmp"
        if not upper.is_dir():
            self.skipTest("this volume is case-sensitive")
        with (
            mock.patch.object(observer, "_account", return_value=(str(fake_home), "q")),
            mock.patch.object(tempfile, "tempdir", str(upper)),
        ):
            seen, _text, status, _config = self._run()
        self.assertEqual("ok", status)
        self.assertEqual(Path("/tmp").resolve(), Path(seen[0][1]["cwd"]).resolve().parent)

    @unittest.skipIf(os.name == "nt", "the account and /tmp rules are POSIX")
    def test_a_temp_path_naming_the_user_in_another_case_falls_back_to_tmp(self) -> None:
        # Review N1: the CLI sent `/private/tmp/<USER>-cgverify` and the name
        # test, being case-sensitive, let it through.
        named = Path(tempfile.mkdtemp(), "ALICEQUUX-scratch")
        named.mkdir()
        with (
            mock.patch.object(
                observer, "_account", return_value=("/nonexistent-home", "alicequux")
            ),
            mock.patch.object(tempfile, "tempdir", str(named)),
        ):
            seen, _text, _status, _config = self._run()
        self.assertEqual(Path("/tmp").resolve(), Path(seen[0][1]["cwd"]).resolve().parent)

    @unittest.skipIf(os.name == "nt", "the account and /tmp rules are POSIX")
    def test_no_temp_location_outside_home_refuses_before_anything_runs(self) -> None:
        fake_home = Path(tempfile.mkdtemp(), "home", "alicequux")
        (fake_home / "tmp").mkdir(parents=True)
        with (
            mock.patch.object(observer, "_account", return_value=(str(fake_home), "alicequux")),
            mock.patch.object(tempfile, "tempdir", str(fake_home / "tmp")),
            mock.patch.object(observer, "READING_FALLBACK_TMP", str(fake_home / "tmp")),
        ):
            seen, text, status, config = self._run()
        self.assertEqual(("", "failed"), (text, status))
        self.assertEqual([], seen)
        self.assertEqual([], os.listdir(config.state_dir))

    def test_stdout_goes_to_an_owner_only_file_outside_the_working_directory(self) -> None:
        seen: list[tuple[str, int]] = []

        def runner(command: list[str], **kwargs: Any) -> Any:
            out = kwargs["stdout"]
            seen.append((out.name if hasattr(out, "name") else "", os.fstat(out.fileno()).st_mode))
            self.assertNotEqual(subprocess.PIPE, out)
            self.assertNotEqual(subprocess.DEVNULL, out)
            out.write(b"{}")
            return subprocess.CompletedProcess(command, 0)

        config = self._config()
        observer.claude_exec(
            config,
            "p",
            output_cap_bytes=10,
            runner=runner,
            binary_resolver=lambda _n: "/bin/claude",
        )
        self.assertEqual(1, len(seen))
        if os.name != "nt":  # POSIX permission bits; Windows uses ACLs
            self.assertEqual(0o600, seen[0][1] & 0o777)

    def test_the_reply_is_read_only_up_to_its_byte_cap(self) -> None:
        _seen, text, status, _config = self._run(reply=b"x" * 10_000, cap=64)
        self.assertEqual("ok", status)
        self.assertEqual("x" * 64, text)

    def test_nothing_is_left_behind_on_any_path(self) -> None:
        cases: tuple[tuple[str, dict[str, Any], str], ...] = (
            ("ok", {}, "ok"),
            ("nonzero exit", {"returncode": 1}, "failed"),
            ("timeout", {"raises": subprocess.TimeoutExpired("claude", 60)}, "failed"),
            ("os error", {"raises": OSError("gone")}, "failed"),
        )
        for label, kwargs, expected in cases:
            with self.subTest(path=label):
                seen, text, status, config = self._run(**kwargs)
                self.assertEqual(expected, status)
                if expected == "failed":
                    self.assertEqual("", text)
                self.assertEqual(1, len(seen))
                self.assertEqual([], os.listdir(config.state_dir), f"{label} left files")

    def test_no_absolute_claude_spends_nothing_and_creates_nothing(self) -> None:
        for binary in (None, "", "claude", "./claude", "bin/claude"):
            with self.subTest(binary=binary):
                seen, text, status, config = self._run(binary=binary)
                self.assertEqual(("", "unavailable"), (text, status))
                self.assertEqual([], seen)
                self.assertEqual([], os.listdir(config.state_dir))

    MARKERS = (
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_SESSION_ATTENDED",
        "CLAUDE_CODE_MESSAGING_SOCKET",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CLAUDE_PID",
        "CLAUDE_EFFORT",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
    )
    KEPT = (
        "PATH",
        "HOME",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
    )

    def test_a_reading_started_from_inside_a_claude_session_is_not_that_session(self) -> None:
        """A daemon opened from a Claude Code session carries its markers.

        The CLI drops these itself when it spawns a fresh session; a reading
        that kept them would register as the opener's child and could reach
        its peer-messaging socket.
        """
        environ = dict.fromkeys((*self.MARKERS, *self.KEPT), "x")
        scrubbed = observer.claude_environment(environ)
        for name in self.MARKERS:
            with self.subTest(dropped=name):
                self.assertNotIn(name, scrubbed)
        for name in self.KEPT:
            with self.subTest(kept=name):
                self.assertEqual("x", scrubbed.get(name))
        self.assertIn("CLAUDECODE", environ, "the caller's mapping was modified")

    def test_a_reading_turns_off_the_clis_nonessential_traffic(self) -> None:
        # Sent F3: measured under a no-egress sandbox, the CLI looked up six
        # other hosts per reading, and none with this variable set.
        for environ in ({}, {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "0"}):
            with self.subTest(environ=environ):
                scrubbed = observer.claude_environment(environ)
                self.assertEqual("1", scrubbed["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"])
        seen, _text, _status, _config = self._run()
        self.assertEqual("1", seen[0][1]["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"])

    def test_the_call_runs_with_the_scrubbed_environment(self) -> None:
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s"}):
            seen, _text, _status, _config = self._run()
            expected = observer.claude_environment(os.environ)
        env = seen[0][1]["env"]
        self.assertEqual(expected, env)
        self.assertNotIn("CLAUDECODE", env)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)

    def test_the_resolver_is_asked_for_claude_and_never_for_codex(self) -> None:
        resolver = mock.Mock(return_value=None)
        observer.claude_exec(
            self._config(), "p", output_cap_bytes=1, runner=mock.Mock(), binary_resolver=resolver
        )
        resolver.assert_called_once_with("claude")


class ReadingTimeoutTest(unittest.TestCase):
    """A reading gets its own timeout; a goal summary keeps 60 s (DRC-4759).

    Each test reads the timeout the runner was HANDED, not the constant, so a
    producer that kept the shared 60-second figure turns one test red.
    """

    def _config(self) -> Any:
        state_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, state_dir, True)
        return dataclasses.replace(make_config(), observer_model_enabled=True, state_dir=state_dir)

    @staticmethod
    def _runner(seen: list[float]) -> Any:
        def runner(command: Any, **kwargs: Any) -> Any:
            seen.append(kwargs["timeout"])
            stdout = kwargs.get("stdout")
            if stdout is not None and hasattr(stdout, "write"):
                stdout.write(b"{}")
            return subprocess.CompletedProcess(command, 0, "", "")

        return runner

    def test_the_two_figures(self) -> None:
        self.assertEqual(180, observer.OBSERVER_READING_TIMEOUT_SEC)
        self.assertEqual(60, observer.OBSERVER_MODEL_TIMEOUT_SEC)

    def test_a_codex_reading_is_handed_the_reading_timeout(self) -> None:
        from compass_runtime import reading  # noqa: PLC0415

        seen: list[float] = []
        model = reading.CodexReadingModel(
            self._config(),
            runner=self._runner(seen),
            binary_resolver=mock.Mock(return_value="/usr/bin/codex"),
        )
        model("a reading prompt", output_cap_bytes=64)
        self.assertEqual([180], seen)

    def test_a_claude_reading_is_handed_the_reading_timeout(self) -> None:
        from compass_runtime import reading  # noqa: PLC0415

        seen: list[float] = []
        model = reading.ClaudeReadingModel(
            self._config(),
            runner=self._runner(seen),
            binary_resolver=mock.Mock(return_value="/usr/local/bin/claude"),
        )
        _, status = model("a reading prompt", output_cap_bytes=64)
        self.assertEqual("ok", status)
        self.assertEqual([180], seen)

    def test_a_prepared_claude_call_is_handed_the_reading_timeout(self) -> None:
        # The charged qualification path enters `prepare_claude_exec` itself.
        seen: list[float] = []
        with observer.prepare_claude_exec(
            self._config(),
            runner=self._runner(seen),
            binary_resolver=mock.Mock(return_value="/usr/local/bin/claude"),
        ) as prepared:
            prepared("a reading prompt", output_cap_bytes=64)
        self.assertEqual([180], seen)

    def test_a_goal_summary_keeps_sixty_seconds(self) -> None:
        seen: list[float] = []
        caller = observer.CodexGoalModel(
            self._config(),
            runner=self._runner(seen),
            binary_resolver=mock.Mock(return_value="/usr/bin/codex"),
            consent=True,
            session_key="codex:one",
        )
        caller("a transcript tail", "stage")
        self.assertEqual([60], seen)


class ObserverModelSecurityTest(unittest.TestCase):
    def test_cli_defaults_on_and_rollback_always_wins(self) -> None:
        for flags, enabled in (
            ([], True),
            (["--observer-model"], True),
            (["--observer-model", "--no-observer-model"], False),
            (["--no-observer-model", "--observer-model"], False),
        ):
            with self.subTest(flags=flags):
                args = cli.build_parser().parse_args(flags)
                config, _state = cli.build_runtime(args, started=0)
                self.assertEqual(enabled, config.observer_model_enabled)

    def test_disabled_model_never_resolves_or_runs(self) -> None:
        runner, resolver = mock.Mock(), mock.Mock()
        caller = observer.CodexGoalModel(
            make_config(observer_model_enabled=False), runner=runner, binary_resolver=resolver
        )
        self.assertIsNone(caller("private transcript", "stage"))
        runner.assert_not_called()
        resolver.assert_not_called()
        self.assertEqual("disabled", caller.status)

    def test_enabled_model_requires_scoped_consent_and_session(self) -> None:
        config = dataclasses.replace(make_config(), observer_model_enabled=True)
        for kwargs in ({}, {"consent": True}, {"session_key": "codex:one"}):
            with self.subTest(kwargs=kwargs):
                runner = mock.Mock()
                caller = observer.CodexGoalModel(config, runner=runner, **kwargs)
                self.assertIsNone(caller("private", "stage"))
                runner.assert_not_called()

    def test_goal_notice_is_recorded_at_call_and_stored_off_prevents_the_runner(self) -> None:
        from compass_runtime import reading_policy  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as home:
            config = make_config(state_dir=Path(home))
            prompts: list[str] = []

            def runner(argv: Any, **kwargs: Any) -> Any:
                prompts.append(kwargs["input"])
                Path(argv[argv.index("--output-last-message") + 1]).write_text("ship parser")
                return subprocess.CompletedProcess(argv, 0)

            def caller() -> Any:
                return observer.CodexGoalModel(
                    config,
                    runner=runner,
                    binary_resolver=lambda _: "/usr/bin/codex",
                    consent=True,
                    session_key="pi:one",
                )

            first = caller()
            first("private transcript", "stage")
            self.assertEqual(1, len(prompts))
            self.assertEqual("goal", first.notice["kind"])
            self.assertEqual("", first.notice["tool_output"])
            second = caller()
            second("private transcript", "stage")
            self.assertIsNone(second.notice)
            reading_policy.set_consent(config, False, now=time.time())
            off = caller()
            self.assertIsNone(off("private transcript", "stage"))
            self.assertEqual("readings-off", off.status)
            self.assertEqual(2, len(prompts))

    def test_relative_resolution_is_refused(self) -> None:
        config = dataclasses.replace(make_config(), observer_model_enabled=True)
        for binary in ("codex", "./codex", "bin/codex"):
            runner = mock.Mock()
            caller = observer.CodexGoalModel(
                config,
                runner=runner,
                binary_resolver=mock.Mock(return_value=binary),
                consent=True,
                session_key="codex:one",
            )
            self.assertIsNone(caller("private", "stage"))
            runner.assert_not_called()
            self.assertEqual("unavailable", caller.status)

    def test_transcript_extraction_redacts_credentials_crossing_each_earlier_cap(self) -> None:
        secret = "AKIA" + "A" * 16
        for cap in (2000, 8192):
            text = "Fix the observer. " + "x" * (cap - 37) + " " + secret
            for content in (text, [{"type": "text", "text": text}], {"content": text}):
                with self.subTest(cap=cap, content_type=type(content).__name__):
                    parsed = observer._message_from("user", content, "pi", cap)
                    assert parsed is not None
                    self.assertNotIn(secret[:-1], parsed["text"])
                    self.assertIn("REDACTED", parsed["text"])

    def test_parent_and_child_model_prompts_never_receive_clipped_credentials(self) -> None:
        secret = "AKIA" + "A" * 16
        with tempfile.TemporaryDirectory() as tmp:
            config, state = make_runtime(
                state_dir=Path(tmp), observer_model_enabled=True, spacedock_enabled=False
            )
            for child, cap in ((False, 8192), (True, 2000)):
                text = "Fix the observer. " + "x" * (cap - 36) + " " + secret
                path = Path(tmp) / f"{child}.jsonl"
                path.write_text(
                    json.dumps(
                        {
                            "type": "message",
                            "message": {"role": "assistant" if child else "user", "content": text},
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                runner = mock.Mock(return_value=subprocess.CompletedProcess([], 1))
                caller = observer.CodexGoalModel(
                    config,
                    runner=runner,
                    binary_resolver=lambda _name: "/bin/codex",
                    consent=True,
                    session_key=f"pi:{child}",
                )
                if child:
                    observer.derive_child_assignment(config, str(path), caller)
                else:
                    observer.analyze(
                        config, state, str(path), now=0, window_sec=86400, model=caller
                    )
                runner.assert_called_once()
                prompt = runner.call_args.kwargs["input"]
                self.assertNotIn(secret[:-1], prompt)
                self.assertIn("REDACTED", prompt)

    def test_entire_prompt_is_redacted_before_utf8_byte_cap(self) -> None:
        secret = "sk-ant-api03-" + "a" * 93
        recorded: dict[str, Any] = {}

        def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            recorded.update(kwargs)
            return subprocess.CompletedProcess(command, 1)

        with tempfile.TemporaryDirectory() as tmp:
            config = dataclasses.replace(
                make_config(), state_dir=Path(tmp), observer_model_enabled=True
            )
            caller = observer.CodexGoalModel(
                config,
                runner=run,
                binary_resolver=lambda _name: "/opt/bin/codex",
                consent=True,
                session_key="codex:one",
            )
            caller(secret + "界" * 20000 + secret, secret)
        prompt = recorded["input"]
        self.assertNotIn(secret, prompt)
        self.assertNotIn("sk-ant-api03-", prompt)
        self.assertIn("sk-ant-…REDACTED", prompt)
        self.assertLessEqual(len(prompt.encode("utf-8")), observer.OBSERVER_MODEL_MAX_PROMPT_BYTES)
        self.assertEqual(60, recorded["timeout"])

    def test_one_in_flight_per_session_and_failure_releases_slot(self) -> None:
        entered, release = threading.Event(), threading.Event()

        def run(_command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test did not release model")
            raise OSError("provider unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            config = dataclasses.replace(
                make_config(), state_dir=Path(tmp), observer_model_enabled=True
            )
            first = observer.CodexGoalModel(
                config,
                runner=run,
                binary_resolver=lambda _name: "/bin/codex",
                consent=True,
                session_key="codex:one",
            )
            runner = mock.Mock(return_value=subprocess.CompletedProcess([], 1))
            second = observer.CodexGoalModel(
                config,
                runner=runner,
                binary_resolver=lambda _name: "/bin/codex",
                consent=True,
                session_key="codex:one",
            )
            other = observer.CodexGoalModel(
                config,
                runner=runner,
                binary_resolver=lambda _name: "/bin/codex",
                consent=True,
                session_key="codex:two",
            )
            thread = threading.Thread(target=first, args=("goal", "stage"))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertIsNone(second("goal", "stage"))
                self.assertEqual("in-flight", second.status)
                runner.assert_not_called()
                other("goal", "stage")
                runner.assert_called_once()
            finally:
                release.set()
                thread.join(3)
            second("goal", "stage")
            self.assertEqual(2, runner.call_count)


class ObserverConsentRouteTest(RuntimeTestCase):
    def test_only_explicit_refresh_consent_reaches_the_collector(self) -> None:
        server = make_server()
        thread = threading.Thread(target=poll_fast(server), daemon=True)
        thread.start()
        try:
            for query, headers, expected in (
                ("&refresh=1", {}, False),
                ("&refresh=1&usage=1", {}, False),
                ("&observer_model=1", {}, False),
                ("&refresh=1&observer_model=1", {"Sec-Fetch-Site": "same-site"}, False),
                ("&refresh=1&observer_model=1", {"Sec-Fetch-Site": "same-origin"}, True),
                ("&refresh=1&observer_model=1", {}, True),
                ("&refresh=1&observer_model=1&observer_model=0", {}, False),
                (
                    "&refresh=1&observer_model=1",
                    {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
                    False,
                ),
            ):
                with (
                    self.subTest(query=query, headers=headers),
                    mock.patch.object(project_context, "collect", return_value={}) as collect,
                ):
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=5
                    )
                    try:
                        connection.request(
                            "GET",
                            "/api/project-context?project=test&session=codex:one" + query,
                            headers=headers,
                        )
                        response = connection.getresponse()
                        response.read()
                        self.assertEqual(200, response.status)
                        self.assertEqual(expected, collect.call_args.kwargs["model_consent"])
                    finally:
                        connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


class SupervisedModelCallTest(unittest.TestCase):
    """Every model call goes through the supervised runner (DRC-4686, Q3).

    The goal lane, the unasked lane and the reading route all reach
    `codex_exec` or `claude_exec`, so the default runner there is what each of
    them gets. `on_spawn` is passed only when a caller gives one, which keeps a
    runner with `subprocess.run`'s signature valid.
    """

    def setUp(self) -> None:
        from compass_runtime import supervise  # noqa: PLC0415

        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _config(self) -> Any:
        state_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, state_dir, True)
        return dataclasses.replace(make_config(), state_dir=state_dir)

    def test_a_child_that_would_not_die_is_its_own_status_and_not_a_failure(self) -> None:
        """Codex review F6: a kill that failed is surfaced, never read as an ordinary failure."""
        from compass_runtime import supervise  # noqa: PLC0415

        def runner(_command: Any, **_kwargs: Any) -> Any:
            raise supervise.UnstoppedError(4242)

        config = self._config()
        for call in (observer.codex_exec, observer.claude_exec):
            with self.subTest(call=call.__name__):
                _, status = call(
                    config,
                    "p",
                    output_cap_bytes=64,
                    runner=runner,
                    binary_resolver=lambda name: f"/usr/local/bin/{name}",
                )
                self.assertEqual("unstopped", status)

    def test_every_model_caller_defaults_to_the_supervised_runner(self) -> None:
        import inspect  # noqa: PLC0415

        from compass_runtime import reading, supervise  # noqa: PLC0415

        for caller in (
            observer.codex_exec,
            observer.claude_exec,
            observer.CodexGoalModel,
            reading.CodexReadingModel,
            reading.ClaudeReadingModel,
        ):
            with self.subTest(caller=caller.__qualname__):
                default = inspect.signature(caller).parameters["runner"].default
                self.assertIs(supervise.run, default)

    def test_on_spawn_reaches_the_runner_only_when_a_caller_gives_one(self) -> None:
        from compass_runtime import reading  # noqa: PLC0415

        seen: list[dict[str, Any]] = []

        def runner(command: Any, **kwargs: Any) -> Any:
            seen.append(kwargs)
            stdout: Any = kwargs.get("stdout")
            if hasattr(stdout, "write"):
                stdout.write(b"{}")
            return subprocess.CompletedProcess(command, 0)

        def spawned(_group: Any) -> None:
            return None

        config = self._config()
        found = mock.Mock(side_effect=lambda name: f"/usr/local/bin/{name}")
        for model in (reading.CodexReadingModel, reading.ClaudeReadingModel):
            with self.subTest(model=model.__name__):
                seen.clear()
                model(config, runner=runner, binary_resolver=found)("p", output_cap_bytes=64)
                self.assertNotIn("on_spawn", seen[0])
                model(config, runner=runner, binary_resolver=found, on_spawn=spawned)(
                    "p", output_cap_bytes=64
                )
                self.assertIs(spawned, seen[1]["on_spawn"])

    @unittest.skipIf(os.name == "nt", "a shebang script stands in for the CLI")
    def test_a_cli_that_floods_its_output_file_is_stopped_near_the_bound(self) -> None:
        """DRC-4667: 50 MiB to the reply file is stopped near 1 MiB, and the file goes."""
        import sys  # noqa: PLC0415
        import time  # noqa: PLC0415

        # Claude Code's reply is its stdout; Codex writes the file it is named.
        where = {
            "claude": "sys.stdout.buffer",
            "codex": "open(sys.argv[sys.argv.index('--output-last-message') + 1], 'wb')",
        }
        for name, call in (("claude", observer.claude_exec), ("codex", observer.codex_exec)):
            with self.subTest(cli=name):
                config = self._config()
                bin_dir = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, bin_dir, True)
                peak_file = bin_dir / "peak"
                peak_file.write_text("0")
                fake = bin_dir / name
                # The count is published by rename: `open(..., 'w')` truncates
                # before it writes, and the kill this test provokes landed in
                # that gap 4 runs in 25 under load, leaving '' to parse.
                fake.write_text(
                    f"#!{sys.executable}\n"
                    "import os, sys, time\n"
                    "sys.stdin.read()\n"
                    f"out = {where[name]}\n"
                    "chunk = b'x' * (1 << 20)\n"
                    "for n in range(50):\n"
                    "    out.write(chunk); out.flush()\n"
                    f"    open({str(peak_file) + '.part'!r}, 'w').write(str(n + 1))\n"
                    f"    os.replace({str(peak_file) + '.part'!r}, {str(peak_file)!r})\n"
                    "    time.sleep(0.02)\n"
                    "time.sleep(60)\n"
                )
                fake.chmod(0o700)
                started = time.monotonic()
                output, status = call(
                    config, "prompt", output_cap_bytes=64, binary_resolver=lambda _n, f=fake: str(f)
                )
                self.assertEqual(("", "oversized"), (output, status))
                self.assertLess(time.monotonic() - started, 20)
                self.assertLess(int(peak_file.read_text()), 10, "the flood ran far past the bound")
                self.assertEqual([], sorted(p.name for p in config.state_dir.iterdir()))

    def test_the_bound_reaches_only_the_supervised_runner(self) -> None:
        """A runner with `subprocess.run`'s signature is never handed `output_limit`."""
        seen: list[dict[str, Any]] = []

        def runner(command: Any, **kwargs: Any) -> Any:
            seen.append(kwargs)
            return subprocess.CompletedProcess(command, 0)

        config = self._config()
        for call in (observer.codex_exec, observer.claude_exec):
            with self.subTest(call=call.__name__):
                seen.clear()
                call(
                    config,
                    "p",
                    output_cap_bytes=64,
                    runner=runner,
                    binary_resolver=lambda name: f"/usr/local/bin/{name}",
                )
                self.assertNotIn("output_limit", seen[0])
                self.assertEqual(1 << 20, observer.OUTPUT_FILE_LIMIT_BYTES)

    @unittest.skipIf(os.name == "nt", "a shebang script stands in for the CLI")
    def test_a_claude_call_past_its_timeout_takes_its_tree_and_its_files_with_it(self) -> None:
        import sys  # noqa: PLC0415
        import time  # noqa: PLC0415

        config = self._config()
        bin_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bin_dir, True)
        pid_file = bin_dir / "grandchild.pid"
        fake = bin_dir / "claude"
        fake.write_text(
            f"#!{sys.executable}\n"
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
            "time.sleep(60)\n"
        )
        fake.chmod(0o700)
        with mock.patch.object(observer, "OBSERVER_READING_TIMEOUT_SEC", 3):
            _, status = observer.claude_exec(
                config, "prompt", output_cap_bytes=64, binary_resolver=lambda _n: str(fake)
            )
        self.assertEqual("failed", status)
        self.assertEqual([], sorted(p.name for p in config.state_dir.iterdir()))
        grandchild = int(pid_file.read_text())
        deadline = time.monotonic() + 10
        while process_alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(process_alive(grandchild), "the CLI's grandchild outlived the timeout")


class ClaudeDiagnosticTest(unittest.TestCase):
    """Closed failure receipts without retaining a CLI error or private answer."""

    def _run(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        code: int = 1,
        raises: BaseException | None = None,
    ) -> tuple[str, str, dict[str, Any]]:
        self.assertIn("on_diagnostic", inspect.signature(observer.claude_exec).parameters)
        events: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as root:
            config = dataclasses.replace(make_config(), state_dir=Path(root))

            def runner(command: list[str], **kwargs: Any) -> Any:
                kwargs["stdout"].write(stdout)
                kwargs["stderr"].write(stderr)
                if os.name != "nt":
                    self.assertEqual(0o600, os.fstat(kwargs["stderr"].fileno()).st_mode & 0o777)
                if raises is not None:
                    raise raises
                return subprocess.CompletedProcess(command, code)

            with mock.patch.object(time, "monotonic", side_effect=[10.0, 10.125]):
                text, status = observer.claude_exec(
                    config,
                    "PRIVATE PROMPT",
                    output_cap_bytes=32,
                    runner=runner,
                    binary_resolver=lambda _name: "/usr/local/bin/claude",
                    on_diagnostic=events.append,
                )
            self.assertEqual(
                [], list(Path(root).iterdir()), "private output files survived cleanup"
            )
        self.assertEqual(1, len(events))
        self.assertEqual(125, events[0]["elapsed_ms"])
        encoded = json.dumps(events)
        for private in ("PRIVATE", "token-secret", "/Users/alice", "@example"):
            self.assertNotIn(private, encoded)
        return text, status, events[0]

    def test_login_error_on_stderr_keeps_actual_exit_code_without_private_text(self) -> None:
        text, status, event = self._run(
            stderr=b"Not logged in. Please run /login. token-secret /Users/alice alice@example.com",
            code=7,
        )
        self.assertEqual(("", "failed"), (text, status))
        self.assertEqual(7, event["returncode"])
        self.assertEqual("login-required", event["reason"])
        self.assertEqual("stderr", event["reason_source"])
        self.assertIsNone(event["exception_kind"])

    def test_nonzero_stdout_login_error_is_classified_without_returning_it(self) -> None:
        text, status, event = self._run(stdout=b"Please run /login. PRIVATE")
        self.assertEqual(("", "failed"), (text, status))
        self.assertEqual("login-required", event["reason"])
        self.assertEqual("stdout", event["reason_source"])

    def test_success_does_not_treat_answer_or_stderr_as_an_error(self) -> None:
        text, status, event = self._run(
            stdout=b"answer mentions not logged in", stderr=b"Please run /login PRIVATE", code=0
        )
        self.assertEqual(("answer mentions not logged in", "ok"), (text, status))
        self.assertEqual("none", event["reason"])
        self.assertEqual("none", event["reason_source"])
        self.assertEqual(0, event["returncode"])

    def test_classifier_reads_only_a_bounded_prefix(self) -> None:
        _, _, event = self._run(stderr=b"x" * 8192 + b"Please run /login PRIVATE")
        self.assertEqual("unknown", event["reason"])
        self.assertEqual(8192, event["diagnostic_prefix_bytes"])

    def test_timeout_is_distinct_from_nonzero_exit_and_keeps_no_exception_text(self) -> None:
        _, status, event = self._run(
            raises=subprocess.TimeoutExpired("PRIVATE", 180, stderr=b"token-secret")
        )
        self.assertEqual("failed", status)
        self.assertEqual("timeout", event["exception_kind"])
        self.assertIsNone(event["returncode"])

    def test_os_error_is_distinct_and_never_serializes_the_exception(self) -> None:
        _, status, event = self._run(raises=OSError("token-secret PRIVATE /Users/alice"))
        self.assertEqual("failed", status)
        self.assertEqual("os-error", event["exception_kind"])
        self.assertEqual("unknown", event["reason"])

    def test_error_labels_are_closed_matches_not_copied_cli_messages(self) -> None:
        for message, reason in (
            (b"Invalid API key. PRIVATE", "authentication-rejected"),
            (b"Rate limit exceeded. PRIVATE", "rate-limited"),
            (b"Unknown model: PRIVATE", "model-unavailable"),
            (b"Connection failed: ECONNREFUSED PRIVATE", "network-error"),
            (b"error: unknown option --PRIVATE", "cli-option-error"),
            (b"unrecognized arbitrary error PRIVATE", "unknown"),
        ):
            with self.subTest(reason=reason):
                _, _, event = self._run(stderr=message)
                self.assertEqual(reason, event["reason"])

    def test_supervisor_exception_categories_are_closed(self) -> None:
        for error, status, category in (
            (supervise.UnstoppedError(123), "unstopped", "unstopped"),
            (supervise.OversizedError(123), "oversized", "output-limit"),
            (supervise.ClosedError("PRIVATE"), "failed", "closed"),
            (subprocess.SubprocessError("PRIVATE"), "failed", "subprocess-error"),
        ):
            with self.subTest(category=category):
                _, actual, event = self._run(raises=error)
                self.assertEqual(status, actual)
                self.assertEqual(category, event["exception_kind"])
                self.assertIsNone(event["returncode"])

    def test_callback_error_aborts_delivery_and_still_removes_private_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            config = dataclasses.replace(make_config(), state_dir=Path(root))
            events: list[dict[str, Any]] = []

            def runner(command: list[str], **kwargs: Any) -> Any:
                kwargs["stdout"].write(b"{}")
                kwargs["stderr"].write(b"PRIVATE")
                return subprocess.CompletedProcess(command, 0)

            def sink(event: dict[str, Any]) -> None:
                events.append(event)
                raise OSError("private receipt write failed")

            with self.assertRaisesRegex(OSError, "receipt write failed"):
                observer.claude_exec(
                    config,
                    "PRIVATE",
                    output_cap_bytes=32,
                    runner=runner,
                    binary_resolver=lambda _name: "/usr/local/bin/claude",
                    on_diagnostic=sink,
                )
            self.assertEqual("ok", events[0]["status"])
            self.assertEqual([], list(Path(root).iterdir()))

    @unittest.skipIf(
        os.name == "nt", "POSIX executable fixture; Windows supervision tested separately"
    )
    def test_real_supervisor_stops_stderr_without_changing_the_stdout_stream(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            binary = base / "local-error-fixture"
            binary.write_text(
                "#!/usr/bin/env python3\nimport os\nos.write(2, bytes([120]) * 8192)\n"
            )
            binary.chmod(0o700)
            state = base / "state"
            config = dataclasses.replace(make_config(), state_dir=state)
            events: list[dict[str, Any]] = []
            with mock.patch.object(observer, "OUTPUT_FILE_LIMIT_BYTES", 4096):
                text, status = observer.claude_exec(
                    config,
                    "PRIVATE",
                    output_cap_bytes=32,
                    binary_resolver=lambda _name: str(binary),
                    on_diagnostic=events.append,
                )
            self.assertEqual(("", "oversized"), (text, status))
            self.assertEqual("output-limit", events[0]["exception_kind"])
            self.assertEqual([], list(state.iterdir()))

    def test_local_output_read_failure_does_not_classify_successful_answer_as_cli_error(
        self,
    ) -> None:
        read = runtime_io.read_prefix_bytes

        def fail_answer_read(path: str, *, max_bytes: int) -> bytes:
            if max_bytes == 32:
                raise OSError("PRIVATE")
            return read(path, max_bytes=max_bytes)

        with mock.patch.object(runtime_io, "read_prefix_bytes", side_effect=fail_answer_read):
            _, status, event = self._run(stdout=b"Please run /login PRIVATE", code=0)
        self.assertEqual("failed", status)
        self.assertEqual("os-error", event["exception_kind"])
        self.assertEqual("unknown", event["reason"])

    def test_interrupted_prepared_call_still_removes_both_private_streams(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            config = dataclasses.replace(make_config(), state_dir=Path(root))
            events: list[dict[str, Any]] = []
            with (
                self.assertRaises(KeyboardInterrupt),
                observer.prepare_claude_exec(
                    config,
                    on_diagnostic=events.append,
                    binary_resolver=lambda _name: "/usr/local/bin/claude",
                ) as prepared,
            ):
                paths = [prepared.output_path, prepared.error_path, prepared.workdir]
                raise KeyboardInterrupt
            self.assertEqual([], events)
            self.assertTrue(all(not Path(path).exists() for path in paths))

    def test_stderr_allocation_failure_never_starts_the_runner(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            config = dataclasses.replace(make_config(), state_dir=Path(root))
            runner = mock.Mock()
            real_mkstemp = tempfile.mkstemp
            calls = 0

            def allocator(**kwargs: Any) -> tuple[int, str]:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("PRIVATE")
                return real_mkstemp(**kwargs)

            with mock.patch.object(tempfile, "mkstemp", side_effect=allocator):
                self.assertEqual(
                    ("", "failed"),
                    observer.claude_exec(
                        config,
                        "PRIVATE",
                        output_cap_bytes=32,
                        runner=runner,
                        on_diagnostic=lambda _event: None,
                        binary_resolver=lambda _name: "/usr/local/bin/claude",
                    ),
                )
            runner.assert_not_called()
            self.assertEqual([], list(Path(root).iterdir()))
