from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

from compass_runtime import spacedock

from .support import (
    config_patch,
    make_runtime,
    runtime,
    state_of,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class SpacedockParserTest(unittest.TestCase):
    """Pure parsers, so every branch runs on every OS runner (decision D-4)."""

    DEBUG_FLYWHEEL: ClassVar[list[str]] = [
        "intake",
        "reproduce",
        "discover",
        "hypothesize",
        "verify",
        "fix-and-harden",
        "uat",
        "closed",
    ]

    def frontmatter(self, body: str) -> list[str]:
        config, _runtime = runtime()
        lines: list[str] = spacedock.frontmatter_lines(config, body)
        return lines

    def test_stage_names_read_document_order_past_sibling_blocks(self) -> None:
        """`transitions:` and a nested `decision:` must not leak into the spine."""
        config, _runtime = runtime()
        body = (
            "---\n"
            "commissioned-by: spacedock@0.22.0\n"
            "state: .spacedock-state\n"
            "stages:\n"
            "  defaults:\n"
            "    worktree: false\n"
            "  states:\n"
            "    - name: intake\n"
            "      initial: true\n"
            "    - name: review\n"
            "    - name: fix-and-harden\n"
            "      worktree: true\n"
            "    - name: escalated\n"
            "      gate: true\n"
            "      decision:\n"
            "        field: verdict\n"
            "        options:\n"
            "          - {label: Close, value: CLOSED, handoff: fo}\n"
            "    - name: posted\n"
            "      terminal: true\n"
            "  transitions:\n"
            "    - from: review\n"
            "      to: intake\n"
            "      label: needs rework\n"
            "---\n"
            "# Prose\n"
        )
        lines = self.frontmatter(body)

        self.assertEqual("spacedock@0.22.0", spacedock.scalar(lines, "commissioned-by"))
        self.assertEqual(
            ["intake", "review", "fix-and-harden", "escalated", "posted"],
            [entry["name"] for entry in spacedock.stage_entries(config, lines)],
        )
        # The initial and terminal flags belong to the item they are nested
        # under, and `gate:`/`worktree:`/the decision options are not flags.
        self.assertEqual(
            [("intake", True, False), ("posted", False, True)],
            [
                (entry["name"], entry["initial"], entry["terminal"])
                for entry in spacedock.stage_entries(config, lines)
                if entry["initial"] or entry["terminal"]
            ],
        )

    def test_stage_flags_accept_yamls_true_ish_spellings(self) -> None:
        config, _runtime = runtime()
        body = (
            "---\n"
            "stages:\n"
            "  states:\n"
            "    - name: intake\n"
            '      initial: "true"\n'
            "    - name: review\n"
            "      terminal: false\n"
            "    - name: posted\n"
            "      terminal: yes\n"
            "---\n"
        )

        self.assertEqual(
            [("intake", True, False), ("review", False, False), ("posted", False, True)],
            [
                (e["name"], e["initial"], e["terminal"])
                for e in spacedock.stage_entries(config, self.frontmatter(body))
            ],
        )

    def test_frontmatter_requires_a_closed_leading_fence(self) -> None:
        for label, body in [
            ("no fence", "# Just prose\n"),
            ("unterminated", "---\nstages:\n"),
            ("prose first", "intro\n---\nstages:\n---\n"),
        ]:
            with self.subTest(case=label):
                self.assertEqual([], self.frontmatter(body))

    def test_stage_names_refuse_shapes_the_scanner_cannot_model(self) -> None:
        """An unmodellable construct must render no strip, never a wrong one."""
        config, _runtime = runtime()
        cases = {
            "flow sequence": "stages:\n  states: [intake, review]\n",
            "no states block": "stages:\n  defaults:\n    worktree: false\n",
            "stages absent": "state: .spacedock-state\n",
            "illegal name": "stages:\n  states:\n    - name: Intake_Bad\n",
            "flow item": "stages:\n  states:\n    - {name: intake}\n    - name: review\n",
            "single char name": "stages:\n  states:\n    - name: x\n",
            "duplicate name": "stages:\n  states:\n    - name: review\n    - name: review\n",
        }
        for label, block in cases.items():
            with self.subTest(case=label):
                lines = ("---\n" + block + "---\n").split("\n")[1:-2]
                self.assertEqual([], spacedock.stage_entries(config, lines))

    def test_workers_are_attributed_to_a_known_slug(self) -> None:
        """Cycle markers appear on either side of the stage, and a slug may end
        in a cycle-shaped token of its own — so the slug must be known, never
        guessed off the name."""
        slugs = ["case-7", "verify-the-thing", "case-7-r3"]
        cases = [
            ("spacedock-ensign-case-7-uat", ("case-7", "uat", "")),
            ("spacedock-ensign-case-7-fix-and-harden", ("case-7", "fix-and-harden", "")),
            ("spacedock-ensign-case-7-cycle2-verify", ("case-7", "verify", "cycle2")),
            ("spacedock-ensign-case-7-verify-c2", ("case-7", "verify", "c2")),
            ("spacedock-ensign-case-7-verify-pass2b", ("case-7", "verify", "pass2b")),
            # A slug ending in a cycle-shaped token is one entity, not a retry of
            # a shorter slug: longest-slug-first keeps them apart.
            ("spacedock-ensign-case-7-r3-verify", ("case-7-r3", "verify", "")),
            # A slug containing a stage name survives intact.
            ("spacedock-ensign-verify-the-thing-uat", ("verify-the-thing", "uat", "")),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    expected,
                    spacedock.attribute_worker(name, slugs, self.DEBUG_FLYWHEEL),
                )

    def test_workers_are_rejected_rather_than_mis_attributed(self) -> None:
        slugs = ["case-7"]
        for label, name in [
            ("not an ensign", "some-other-agent-uat"),
            ("slug unknown to this workflow", "spacedock-ensign-case-9-uat"),
            ("no known stage", "spacedock-ensign-case-7-shipit"),
            ("real content beside the stage", "spacedock-ensign-case-7-uat-extra"),
        ]:
            with self.subTest(case=label):
                self.assertIsNone(spacedock.attribute_worker(name, slugs, self.DEBUG_FLYWHEEL))

    def test_boot_records_require_tool_result_provenance(self) -> None:
        """Boot output is command output. Conversation text that merely contains
        an envelope must not be able to nominate a path for Compass to open."""
        config, _runtime = runtime()
        envelope = (
            '{"command":"boot","id_style":"slug",'
            '"dispatchable":[{"slug":"drc-1","current":"review","next":"disposition"}],'
            '"definition_dir":"/w/one","entity_dir":"/w/one"}'
        )

        def line(block_type: str) -> bytes:
            return json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [{"type": block_type, "content": "=== BOOT ===\n" + envelope}]
                    },
                }
            ).encode()

        records = spacedock.boot_records(config, line("tool_result"))

        self.assertEqual(1, len(records))
        self.assertEqual("/w/one", records[0]["definition_dir"])
        self.assertEqual({"drc-1": "review"}, spacedock.boot_entities(records, "/w/one"))
        self.assertEqual(["/w/one"], spacedock.workflow_dirs(config, records))
        # Same bytes, ordinary text block: no provenance, no record.
        self.assertEqual([], spacedock.boot_records(config, line("text")))
        self.assertEqual([], spacedock.boot_records(config, b'{"not":"jsonl definition_dir"}'))

    def test_boot_records_finds_pi_tool_result_format(self) -> None:
        """Pi writes tool results as a ``toolResult`` role message whose
        ``content`` blocks carry ``type: "text"`` — the same provenance as
        Claude's ``tool_result`` content blocks in a different transcript
        shape. The boot reader must find the envelope in that format.
        Falsifying edit: remove the ``toolResult`` branch from
        ``tool_result_text`` — ``boot_records`` returns []."""
        config, _runtime = runtime()
        envelope = (
            '{"command":"boot","id_style":"slug",'
            '"definition_dir":"/w/one","entity_dir":"/w/one",'
            '"dispatchable":[]}'
        )
        record = json.dumps(
            {
                "type": "message",
                "id": "tr1",
                "parentId": "call-1",
                "timestamp": "2026-08-21T00:00:00Z",
                "message": {
                    "role": "toolResult",
                    "content": [{"type": "text", "text": "=== BOOT ===\n" + envelope}],
                },
            }
        ).encode()

        records = spacedock.boot_records(config, record)

        self.assertEqual(1, len(records))
        self.assertEqual("/w/one", records[0]["definition_dir"])

    def test_boot_records_finds_codex_tool_output_format(self) -> None:
        """Codex writes tool output under ``payload``, in two spellings and two
        value shapes, and had no branch at all — so the observer's stage half was
        structurally unreachable there and every rollout running a workflow
        published ``stage: ""``.

        All four shapes are measured on the local rollout store rather than read
        off an API description: ``function_call_output`` carries ``output`` as a
        string on 15,730 records and as a block list on 897,
        ``custom_tool_call_output`` as a string on 2,956 and as a block list on
        18,477. Falsifying edit: remove the ``_codex_tool_output`` call from
        ``tool_result_text`` — every arm below returns [].
        """
        config, _runtime = runtime()
        envelope = (
            '{"command":"boot","id_style":"slug",'
            '"definition_dir":"/w/one","entity_dir":"/w/one",'
            '"dispatchable":[{"slug":"drc-1","current":"review"}]}'
        )
        text = "=== BOOT ===\n" + envelope

        def line(payload_type: str, output: Any) -> bytes:
            return json.dumps(
                {
                    "timestamp": "2026-08-21T00:00:00Z",
                    "type": "response_item",
                    "payload": {"type": payload_type, "call_id": "call-1", "output": output},
                }
            ).encode()

        for payload_type in ("function_call_output", "custom_tool_call_output"):
            for label, output in (
                ("string", text),
                ("blocks", [{"type": "input_text", "text": text}]),
            ):
                with self.subTest(payload=payload_type, shape=label):
                    found = spacedock.boot_records(config, line(payload_type, output))
                    self.assertEqual(1, len(found))
                    self.assertEqual("/w/one", found[0]["definition_dir"])
                    self.assertEqual({"drc-1": "review"}, spacedock.boot_entities(found, "/w/one"))

    def test_codex_conversation_text_cannot_nominate_a_path(self) -> None:
        """The negative twin: the provenance rule is the same one Pi's branch
        carries, and a Codex record that is not a tool OUTPUT must not nominate a
        directory. A ``function_call``'s arguments are the model's request, and a
        message is a person or a model talking. Falsifying edit: drop the payload
        type gate in ``_codex_tool_output``.
        """
        config, _runtime = runtime()
        envelope = (
            '{"command":"boot","id_style":"slug",'
            '"definition_dir":"/w/one","entity_dir":"/w/one",'
            '"dispatchable":[]}'
        )
        for payload_type in ("function_call", "custom_tool_call", "message", "reasoning"):
            with self.subTest(payload=payload_type):
                record = json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": payload_type,
                            "output": envelope,
                            "arguments": envelope,
                            "content": [{"type": "input_text", "text": envelope}],
                        },
                    }
                ).encode()
                self.assertEqual([], spacedock.boot_records(config, record))

    def test_a_codex_tool_output_block_that_is_not_a_string_is_skipped(self) -> None:
        """The same isinstance guard the Pi branch needs, on the Codex arm.

        A block whose ``text`` is an object reaches ``str.find`` in the boot
        scanner otherwise, and the ``AttributeError`` escapes the collector to
        blank every row for that harness. An ``output`` that is neither a string
        nor a list is the same class of untrusted value. Falsifying edit: drop
        the isinstance checks from ``_codex_tool_output``.
        """
        config, _runtime = runtime()
        for output in ([{"type": "input_text", "text": {"definition_dir": "/w/x"}}], 7, None):
            with self.subTest(output=type(output).__name__):
                record = json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "output": output,
                            "note": "definition_dir",
                        },
                    }
                ).encode()
                self.assertEqual([], spacedock.boot_records(config, record))

    def test_pi_conversation_text_cannot_nominate_a_path(self) -> None:
        """The negative twin of the Pi format test above.

        Boot output is command output. The ``toolResult`` role is the only thing
        separating "a tool printed an envelope" from "somebody pasted a workflow
        path into a chat", and a pasted path would otherwise be canonicalised and
        opened. Falsifying edit: widen the role gate in ``tool_result_text`` to
        accept ``user`` or ``assistant`` and this returns one record.
        """
        config, _runtime = runtime()
        envelope = (
            '{"command":"boot","id_style":"slug",'
            '"definition_dir":"/w/one","entity_dir":"/w/one",'
            '"dispatchable":[]}'
        )

        def line(role: str) -> bytes:
            return json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": role,
                        "content": [{"type": "text", "text": "=== BOOT ===\n" + envelope}],
                    },
                }
            ).encode()

        self.assertEqual(1, len(spacedock.boot_records(config, line("toolResult"))))
        for role in ("user", "assistant", "system", "toolCall"):
            with self.subTest(role=role):
                self.assertEqual([], spacedock.boot_records(config, line(role)))

    def test_a_tool_result_text_block_that_is_not_a_string_is_skipped(self) -> None:
        """``isinstance(text, str)`` in the Pi branch is load-bearing.

        A block whose ``text`` is an object reaches ``str.find`` in the boot
        scanner otherwise, and the ``AttributeError`` escapes the collector to
        blank every row for that harness. Falsifying edit: drop the isinstance
        check and this raises instead of returning [].
        """
        config, _runtime = runtime()
        record = json.dumps(
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "content": [{"type": "text", "text": {"definition_dir": "/w/x"}}],
                },
            }
        ).encode()

        self.assertEqual([], spacedock.boot_records(config, record))

    def test_a_hostile_envelope_path_never_raises_out_of_the_reader(self) -> None:
        """The invariant that holds on every platform.

        A lone surrogate survives JSON decoding, so an envelope can carry one.
        Everything below here is wrapped in ``except (OSError, ValueError)``, and
        the failure boundary above is per harness, so anything that escapes
        blanks every row for that harness rather than costing one session its
        strip.
        """
        config, runtime_state = runtime()
        boot = [
            {
                "command": "boot",
                "definition_dir": "/\ud800",
                "entity_dir": "/\udfff",
                "dispatchable": [],
            }
        ]

        self.assertEqual([], spacedock.session_workflows(config, runtime_state, boot, [], 0.0, 1.0))
        for workflow_dir in spacedock.workflow_dirs(config, boot):
            self.assertIsNone(spacedock.read_workflow(config, runtime_state, workflow_dir))

        # Called directly, because the two assertions above cannot reach the
        # handlers this is about: `_usable_dir` refuses the path first, so
        # `workflow_dirs` returns nothing and the loop never runs. Narrowing
        # `read_workflow` or `entity_files` back to `except OSError` left the
        # suite green on all three platforms. Neither reader consults
        # `_usable_dir`, so a direct call meets the `UnicodeEncodeError` that
        # `os.path.realpath` raises on POSIX — a `ValueError`, which is the whole
        # reason the handlers were widened. On Windows the same calls raise an
        # ordinary `OSError`, still caught, same answer.
        self.assertIsNone(spacedock.read_workflow(config, runtime_state, "/\ud800"))
        self.assertEqual([], spacedock.entity_files(config, "/\udfff"))

    def test_a_deeply_nested_envelope_candidate_is_absorbed_not_raised(self) -> None:
        """`RecursionError` is a `RuntimeError`, so it needs naming separately.

        The scanned text is already unescaped, so nesting a tool happened to
        print is real nesting to the decoder. Nothing between here and
        `aggregate`'s per-harness boundary catches a `RuntimeError`, and that
        boundary blanks every row for the harness. Falsifying edit: drop
        `RecursionError` from either handler in `boot_records` — this raises.
        """
        config, _state = runtime()
        # 20k openers, not a thousand: CPython's limit is well above the default
        # recursion depth for this decoder, and a shallower nest simply parses.
        line = json.dumps(
            {
                "message": {
                    "role": "toolResult",
                    "content": [
                        {"type": "text", "text": 'definition_dir {"command": ' + "[" * 20_000}
                    ],
                }
            }
        ).encode()

        self.assertEqual([], spacedock.boot_records(config, line))

    @unittest.skipIf(
        os.name == "nt", "Windows encodes lone surrogates (PEP 529 surrogatepass); POSIX cannot"
    )
    def test_an_unencodable_envelope_path_is_refused(self) -> None:
        """On POSIX the guard has to refuse the path outright.

        The filesystem handler is ``surrogateescape``, which cannot encode
        ``\\ud800``, so ``os.fsencode`` raises ``UnicodeEncodeError``. That is a
        ``ValueError``, not an ``OSError``, so it would sail through every
        handler below. Windows uses ``surrogatepass`` and encodes it, where the
        path merely fails to exist and the ordinary ``OSError`` path covers it.
        Falsifying edit: drop the ``os.fsencode`` probe from ``_usable_dir`` and
        ``read_workflow`` raises instead of returning None.
        """
        config, _runtime = runtime()
        boot = [
            {
                "command": "boot",
                "definition_dir": "/\ud800",
                "entity_dir": "/\udfff",
                "dispatchable": [],
            }
        ]

        self.assertEqual([], spacedock.workflow_dirs(config, boot))
        self.assertEqual("", spacedock.boot_entity_dir(boot, "/\ud800"))

    def test_boot_scan_is_bounded_against_decoy_candidates(self) -> None:
        """Every unbalanced candidate used to rescan to the end of the blob."""
        config, _runtime = runtime()
        decoys = '{"command"' * 40_000
        payload = json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result", "content": decoys + " definition_dir"}]
                },
            }
        ).encode()
        started = time.monotonic()

        self.assertEqual([], spacedock.boot_records(config, payload))

        self.assertLess(time.monotonic() - started, 5.0)

    RENDERED_BOOT = (
        'command: "boot"\n'
        "mods:\n"
        "  idle:\n"
        '    - "pr-merge"\n'
        'id_style: "slug"\n'
        "dispatchable:\n"
        "  -\n"
        '    id: "drc-4029"\n'
        '    slug: "drc-4029"\n'
        '    current: "selection"\n'
        '    next: "triage"\n'
        "  -\n"
        '    slug: "drc-4021"\n'
        '    current: "selection"\n'
        'definition_dir: "/w/one"\n'
        'entity_dir: "/w/one/.spacedock-state"\n'
        'entity_dir_present: "true"\n'
    )

    def tool_result(self, text: str) -> bytes:
        return json.dumps(
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": text}]}}
        ).encode()

    def test_boot_records_read_an_envelope_the_session_rendered(self) -> None:
        """The first officer is told to consume `status --boot --json`, not to
        echo it verbatim, and every real session measured here piped it through
        a formatter — so the raw object never reaches the transcript and the
        JSON branch alone found nothing in 120 transcripts over 21 days.
        Falsifying edit: drop the `rendered_envelope` call from `boot_records`
        and this returns []."""
        config, _runtime = runtime()

        records = spacedock.boot_records(config, self.tool_result(self.RENDERED_BOOT))

        self.assertEqual(1, len(records))
        self.assertEqual("/w/one", records[0]["definition_dir"])
        self.assertEqual("/w/one/.spacedock-state", spacedock.boot_entity_dir(records, "/w/one"))
        self.assertEqual(["/w/one"], spacedock.workflow_dirs(config, records))
        self.assertEqual(
            {"drc-4029": "selection", "drc-4021": "selection"},
            spacedock.boot_entities(records, "/w/one"),
        )

    def test_a_rendering_without_a_boot_command_nominates_nothing(self) -> None:
        """This module's own source names every key the renderer prints, and it
        gets catted into tool results routinely. `command: boot` is what keeps
        that from nominating a path, exactly as the JSON branch requires."""
        config, _runtime = runtime()
        source = 'value = record.get("definition_dir")\nentity_dir: "/w/two"\n'

        self.assertEqual([], spacedock.boot_records(config, self.tool_result(source)))

    def test_a_nested_rendered_key_cannot_nominate_a_path(self) -> None:
        """Only column-0 keys are read, so a `definition_dir` printed inside a
        nested block is data the session displayed, not the envelope's own."""
        config, _runtime = runtime()
        text = 'command: "boot"\nfindings:\n  definition_dir: "/w/evil"\ndefinition_dir: "/w/ok"\n'

        records = spacedock.boot_records(config, self.tool_result(text))

        self.assertEqual(["/w/ok"], spacedock.workflow_dirs(config, records))

    def test_a_rendered_envelope_needs_a_definition_dir(self) -> None:
        config, _runtime = runtime()

        self.assertEqual([], spacedock.boot_records(config, self.tool_result('command: "boot"\n')))

    def test_workflow_dirs_reject_relative_and_nul_paths(self) -> None:
        config, _runtime = runtime()
        records: list[dict[str, Any]] = [
            {"command": "boot", "definition_dir": "docs/spacedock/rel"},
            {"command": "boot", "definition_dir": "/abs/ok"},
            {"command": "boot", "definition_dir": "/abs/ok"},
            {"command": "boot", "definition_dir": ""},
        ]

        self.assertEqual(["/abs/ok"], spacedock.workflow_dirs(config, records))


class SpacedockReadContractTest(unittest.TestCase):
    """The one project read Compass performs, and its refusals."""

    README = (
        "---\n"
        "commissioned-by: spacedock@0.22.0\n"
        "state: .spacedock-state\n"
        "stages:\n"
        "  states:\n"
        "    - name: intake\n"
        "      initial: true\n"
        "    - name: review\n"
        "    - name: posted\n"
        "      terminal: true\n"
        "---\n"
    )

    def setUp(self) -> None:
        _config, state = runtime()
        with state_of().cache_lock:
            state.spacedock_workflow_cache.clear()
            state.spacedock_boot_cache.clear()
            state.spacedock_role_cache.clear()
            state.spacedock_entity_cache.clear()

    def test_the_boot_scan_walks_forward_across_refreshes(self) -> None:
        """A first officer does not necessarily boot at session start. The two
        real sessions measured here booted at 69% and 73% of their transcripts,
        past any head-only window, so the window advances instead of sitting:
        nothing on the first pass, the envelope on a later one, and the file is
        never rescanned from the top. Falsifying edit: pin the read back to
        `handle.read(scan_bytes)` from offset 0 and the envelope is never seen."""
        holder = tempfile.TemporaryDirectory(prefix="compass-boot-")
        self.addCleanup(holder.cleanup)
        path = str(Path(holder.name) / "session.jsonl")
        filler = json.dumps({"type": "user", "message": {"content": "x" * 900}}) + "\n"
        envelope = (
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "content": 'command: "boot"\ndefinition_dir: "/w/late"\n',
                            }
                        ]
                    },
                }
            )
            + "\n"
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(filler * 4 + envelope)

        with config_patch(spacedock_boot_scan_bytes=1024):
            config, state = runtime()
            first = spacedock.transcript_boot(config, state, path)
            passes = 1
            while not spacedock.transcript_boot(config, state, path) and passes < 12:
                passes += 1
            found = spacedock.transcript_boot(config, state, path)

        self.assertEqual([], first)
        self.assertEqual(["/w/late"], spacedock.workflow_dirs(config, found))
        # Progress is remembered, so the walk terminates instead of restarting.
        self.assertLessEqual(passes, 6)
        self.assertGreaterEqual(state.spacedock_boot_cache[path][1], os.path.getsize(path))

    def test_a_shorter_transcript_restarts_the_walk(self) -> None:
        """Progress is recorded against a file, not a path. A path that now
        holds fewer bytes than the walk already covered is not that file, and
        resuming mid-way through it would skip whatever it now begins with."""
        holder = tempfile.TemporaryDirectory(prefix="compass-boot-")
        self.addCleanup(holder.cleanup)
        path = str(Path(holder.name) / "session.jsonl")
        envelope = (
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "content": 'command: "boot"\ndefinition_dir: "/w/fresh"\n',
                            }
                        ]
                    },
                }
            )
            + "\n"
        )
        config, state = runtime()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": "x" * 4000}}) + "\n")
        self.assertEqual([], spacedock.transcript_boot(config, state, path))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(envelope)

        records = spacedock.transcript_boot(config, state, path)

        self.assertEqual(["/w/fresh"], spacedock.workflow_dirs(config, records))

    def workflow(self, body: str | None = None) -> Path:
        holder = tempfile.TemporaryDirectory(prefix="compass-sd-")
        self.addCleanup(holder.cleanup)
        root = Path(holder.name).resolve() / "wf"
        root.mkdir()
        if body is not None:
            (root / "README.md").write_text(body, encoding="utf-8")
        return root

    def entity(self, state: Path, slug: str, status: str, *, folder: bool = False) -> Path:
        state.mkdir(exist_ok=True)
        body = f'---\nid:\ntitle: "a thing"\nstatus: {status}\n---\n\n# report\n'
        if folder:
            (state / slug).mkdir()
            path = state / slug / "index.md"
        else:
            path = state / f"{slug}.md"
        path.write_text(body, encoding="utf-8")
        return path

    def test_commissioned_readme_yields_its_ordered_stages(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README)

        self.assertEqual(
            {
                "name": "wf",
                "stages": ["intake", "review", "posted"],
                "resting": ["intake", "posted"],
                "goal": "",
            },
            spacedock.read_workflow(config, state, str(root)),
        )

    def test_workflow_goal_passes_through_the_frontmatter_title(self) -> None:
        """The session view's goal line reads `workflow.goal`, which is the
        frontmatter `title` scalar passed through from `read_workflow`. A
        workflow with a title publishes it; one without publishes an empty
        string. Fails if the `scalar(lines, "title")` call is removed."""
        config, state = runtime()
        body = (
            "---\n"
            "commissioned-by: spacedock@0.22.0\n"
            "title: Ship session view\n"
            "state: .spacedock-state\n"
            "stages:\n"
            "  states:\n"
            "    - name: intake\n"
            "      initial: true\n"
            "    - name: posted\n"
            "      terminal: true\n"
            "---\n"
        )
        root_with_title = self.workflow(body)
        result = spacedock.read_workflow(config, state, str(root_with_title))
        assert result is not None
        self.assertEqual("Ship session view", result["goal"])

        # A workflow without a title publishes an empty goal.
        root_no_title = self.workflow(self.README)
        result_no = spacedock.read_workflow(config, state, str(root_no_title))
        assert result_no is not None
        self.assertEqual("", result_no["goal"])

    def test_the_goal_is_bounded_and_stripped_like_every_other_row_value(self) -> None:
        """The one piece of project-authored *text* that reaches `/api/data`.

        Every other published value is a grammar-checked slug or a stage name,
        so this is the only one that needed a width. Unbounded, the README byte
        cap was the only limit — a 64 KiB title on every snapshot and every SSE
        push. And a bidi control in it reorders how the line after it renders,
        which is how a title reads as something it does not say.

        Falsifying edit: drop the `records.safe_text` call at the `goal` key.
        """
        config, state = runtime()

        def workflow_with(title: str) -> Path:
            return self.workflow(
                "---\n"
                "commissioned-by: spacedock@0.22.0\n"
                f"title: {title}\n"
                "stages:\n"
                "  states:\n"
                "    - name: intake\n"
                "---\n"
            )

        long_root = workflow_with("x" * 5_000)
        long_result = spacedock.read_workflow(config, state, str(long_root))
        assert long_result is not None
        self.assertEqual(config.spacedock_goal_cap_chars, len(long_result["goal"]))

        # U+202E, right-to-left override.
        hostile_root = workflow_with("Ship it\u202e nope")
        hostile = spacedock.read_workflow(config, state, str(hostile_root))
        assert hostile is not None
        self.assertNotIn("\u202e", hostile["goal"])

    def test_session_workflows_publish_goal_alongside_stages(self) -> None:
        """The goal survives the trip from `read_workflow` through
        `session_workflows` into the render-ready workflow strip."""
        config, state = runtime()
        body = (
            "---\n"
            "commissioned-by: spacedock@0.22.0\n"
            "title: Ship session view\n"
            "state: .spacedock-state\n"
            "stages:\n"
            "  states:\n"
            "    - name: intake\n"
            "      initial: true\n"
            "    - name: posted\n"
            "      terminal: true\n"
            "---\n"
        )
        root = self.workflow(body)
        boot = [
            {
                "command": "boot",
                "definition_dir": str(root),
                "dispatchable": [{"slug": "drc-1", "current": "intake"}],
            }
        ]
        strips = spacedock.session_workflows(config, state, boot, [], time.time(), 3600)
        self.assertEqual(1, len(strips))
        self.assertEqual("Ship session view", strips[0]["goal"])

    def test_uncommissioned_or_absent_readme_yields_nothing(self) -> None:
        config, state = runtime()
        cases = [
            ("absent", None),
            ("not commissioned", "---\nstages:\n  states:\n    - name: intake\n---\n"),
            ("commissioned but no stages", "---\ncommissioned-by: spacedock@1.0.0\n---\n"),
        ]
        for label, body in cases:
            with self.subTest(case=label):
                self.assertIsNone(spacedock.read_workflow(config, state, str(self.workflow(body))))

    @unittest.skipUnless(hasattr(os, "symlink"), "platform has no symlink")
    def test_a_symlinked_readme_is_refused_not_followed(self) -> None:
        config, state = runtime()
        root = self.workflow(None)
        target = root.parent / "elsewhere.md"
        target.write_text(self.README, encoding="utf-8")
        try:
            (root / "README.md").symlink_to(target)
        except OSError:  # pragma: no cover - Windows without the privilege
            self.skipTest("symlink creation not permitted")

        self.assertIsNone(spacedock.read_workflow(config, state, str(root)))

    def test_the_readme_read_stops_at_its_configured_bounds(self) -> None:
        # These are project reads, not store reads, so the byte and line bounds
        # are the read policy rather than an optimisation. Mutation-checked:
        # raising either bound passed the whole suite, because every other
        # fixture is far smaller than the shipped defaults.
        root = self.workflow(self.README)
        head = self.README.index("states:")

        generous, state = make_runtime()
        self.assertIsNotNone(spacedock.read_workflow(generous, state, str(root)))

        # A byte bound that stops before the states block yields no stages.
        byte_bound, byte_runtime = make_runtime(spacedock_readme_bytes=head)
        truncated = spacedock.read_workflow(byte_bound, byte_runtime, str(root))
        self.assertEqual([], (truncated or {}).get("stages", []))

        # A line bound of one cannot reach the states block either.
        line_bound, line_runtime = make_runtime(spacedock_max_frontmatter_lines=1)
        clipped = spacedock.read_workflow(line_bound, line_runtime, str(root))
        self.assertEqual([], (clipped or {}).get("stages", []))

    def test_only_frontmatter_is_read_however_long_the_body(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README + ("prose line\n" * 40_000))

        result = spacedock.read_workflow(config, state, str(root))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(["intake", "review", "posted"], result["stages"])

    def test_session_workflows_prefer_live_workers_then_boot_entities(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README)
        boot = [
            {
                "command": "boot",
                "definition_dir": str(root),
                "dispatchable": [
                    {"slug": "drc-1", "current": "review"},
                    {"slug": "drc-2", "current": "intake"},
                    {"slug": "drc-3", "current": "not-a-stage"},
                ],
            }
        ]

        strips = spacedock.session_workflows(
            config, state, boot, ["spacedock-ensign-drc-1-posted"], time.time(), 3600
        )

        self.assertEqual(1, len(strips))
        self.assertEqual(["intake", "review", "posted"], strips[0]["stages"])
        # The live worker wins for drc-1 (posted, not the booted review) and is
        # marked live; drc-3 is dropped because its stage is not declared.
        self.assertEqual(
            [("drc-1", "posted", True), ("drc-2", "intake", False)],
            [(e["slug"], e["stage"], e["live"]) for e in strips[0]["entities"]],
        )

    def test_entity_state_anchors_a_first_officer_that_booted_an_empty_queue(self) -> None:
        """The regression this whole path exists for. A first officer that boots
        before any entity is intaken reports `dispatchable: []` for the rest of
        the session; without the state directory there is no slug to anchor the
        live worker on, and the workflow renders no strip at all."""
        config, state = runtime()
        root = self.workflow(self.README)
        entity_state = root / ".spacedock-state"
        self.entity(entity_state, "drc-7", "intake")  # queued, not moving
        self.entity(entity_state, "drc-8", "review")  # moving, no live worker
        self.entity(entity_state, "drc-9", "posted")  # finished
        self.entity(entity_state, "pr-42", "review")  # the live worker's entity
        boot = [
            {
                "command": "boot",
                "definition_dir": str(root),
                "entity_dir": str(entity_state),
                "entity_dir_present": "false",
                "dispatchable": [],
            }
        ]

        strips = spacedock.session_workflows(
            config, state, boot, ["spacedock-ensign-pr-42-posted"], time.time(), 3600
        )

        self.assertEqual(1, len(strips))
        # pr-42 is live and at the worker's stage, not the file's; drc-8 is in
        # flight; drc-7 (initial) and drc-9 (terminal) are resting, not moving.
        self.assertEqual(
            [("pr-42", "posted", True), ("drc-8", "review", False)],
            [(e["slug"], e["stage"], e["live"]) for e in strips[0]["entities"]],
        )

    def test_entity_state_is_read_newest_first_in_both_file_shapes(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README)
        entity_state = root / ".spacedock-state"
        older = self.entity(entity_state, "drc-1", "review")
        newer = self.entity(entity_state, "drc-2", "review", folder=True)
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_700_000_100, 1_700_000_100))

        self.assertEqual(
            [("drc-2", "review"), ("drc-1", "review")],
            spacedock.read_entities(
                config,
                state,
                str(entity_state),
                ["intake", "review", "posted"],
                1_700_000_200,
                3600,
            ),
        )

    def test_entity_state_refuses_everything_that_is_not_an_entity(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README)
        entity_state = root / ".spacedock-state"
        self.entity(entity_state, "drc-1", "review")
        # Spacedock retires finished entities into _archive/, operators leave
        # reports beside the entity_state, and a stage the workflow never declared
        # cannot be placed on the spine.
        self.entity(entity_state / "_archive", "drc-0", "review")
        (entity_state / "REVIEW-REPORT-DRC-1.md").write_text(
            "---\nstatus: review\n---\n", encoding="utf-8"
        )
        (entity_state / "notes.txt").write_text("---\nstatus: review\n---\n", encoding="utf-8")
        self.entity(entity_state, "drc-2", "not-a-declared-stage")
        self.entity(entity_state, "drc-3", "")

        self.assertEqual(
            [("drc-1", "review")],
            spacedock.read_entities(
                config, state, str(entity_state), ["intake", "review", "posted"], time.time(), 3600
            ),
        )

    def test_entity_files_report_a_stat_that_identifies_the_file(self) -> None:
        """`scandir` caches a stat, and on Windows that cached result reports
        st_ino and st_dev as zero — which can never match the fstat of an open
        descriptor, so every entity file would be refused on that platform
        alone. Reproduced here by simulating the cached stat, because a POSIX
        runner cannot otherwise see it."""
        config, state = runtime()
        root = self.workflow(self.README)
        entity_state = root / ".spacedock-state"
        self.entity(entity_state, "drc-1", "review")
        real_scandir = os.scandir

        class WindowsLikeEntry:
            def __init__(self, entry: os.DirEntry[str]) -> None:
                self.name, self.path = entry.name, entry.path
                self._entry = entry

            def is_dir(self, *, follow_symlinks: bool = True) -> bool:
                return self._entry.is_dir(follow_symlinks=follow_symlinks)

            def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
                real = self._entry.stat(follow_symlinks=follow_symlinks)
                fields = list(real)
                fields[1] = 0  # st_ino
                fields[2] = 0  # st_dev
                # Only the identity fields are zeroed. The nanosecond times
                # have to be carried through the extended dict or they come
                # back as None and the failure under test is masked by a
                # TypeError in the sort.
                return os.stat_result(
                    fields,
                    {
                        "st_atime_ns": real.st_atime_ns,
                        "st_mtime_ns": real.st_mtime_ns,
                        "st_ctime_ns": real.st_ctime_ns,
                    },
                )

        @contextlib.contextmanager
        def windows_like_scandir(path: str) -> Iterator[list[WindowsLikeEntry]]:
            with real_scandir(path) as entries:
                yield [WindowsLikeEntry(entry) for entry in entries]

        with mock.patch.object(os, "scandir", windows_like_scandir):
            found = spacedock.entity_files(config, str(entity_state))
            self.assertEqual(1, len(found))
            _, path, info = found[0]
            self.assertEqual(
                (os.stat(path).st_dev, os.stat(path).st_ino),
                (info.st_dev, info.st_ino),
            )
            self.assertEqual(
                [("drc-1", "review")],
                spacedock.read_entities(
                    config,
                    state,
                    str(entity_state),
                    ["intake", "review", "posted"],
                    time.time(),
                    3600,
                ),
            )

    def test_entity_state_older_than_the_window_is_history_not_work(self) -> None:
        """A first officer discovers every workflow in the project. One retired
        months ago still has entities frozen mid-pipeline."""
        config, state = runtime()
        root = self.workflow(self.README)
        entity_state = root / ".spacedock-state"
        stale = self.entity(entity_state, "drc-1", "review")
        os.utime(stale, (1_700_000_000, 1_700_000_000))

        self.assertEqual(
            [],
            spacedock.read_entities(
                config,
                state,
                str(entity_state),
                ["intake", "review", "posted"],
                1_700_000_000 + 90_000,
                86_400,
            ),
        )

    @unittest.skipUnless(hasattr(os, "symlink"), "platform has no symlink")
    def test_a_symlinked_entity_file_is_refused_not_followed(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README)
        entity_state = root / ".spacedock-state"
        target = self.entity(entity_state, "drc-1", "review")
        try:
            (entity_state / "drc-2.md").symlink_to(target)
        except OSError:  # pragma: no cover - Windows without the privilege
            self.skipTest("symlink creation not permitted")

        self.assertEqual(
            [("drc-1", "review")],
            spacedock.read_entities(
                config, state, str(entity_state), ["intake", "review", "posted"], time.time(), 3600
            ),
        )

    def test_entity_frontmatter_is_reread_only_when_the_file_changes(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README)
        entity_state = root / ".spacedock-state"
        path = self.entity(entity_state, "drc-1", "review")
        stages = ["intake", "review", "posted"]
        now = time.time()

        reads: list[str] = []
        real = spacedock.read_frontmatter

        def counting(cfg: Any, p: str, limit: int, expect: os.stat_result) -> list[str]:
            reads.append(p)
            lines: list[str] = real(cfg, p, limit, expect)
            return lines

        # Written long enough ago to be settled: a file still inside its
        # timestamp tick is re-read on purpose (the racy-stat tests below).
        os.utime(path, (now - 60, now - 60))

        with mock.patch.object(spacedock, "read_frontmatter", counting):
            spacedock.read_entities(config, state, str(entity_state), stages, now, 3600)
            spacedock.read_entities(config, state, str(entity_state), stages, now, 3600)
            self.assertEqual(1, len(reads))
            self.entity(entity_state, "drc-1", "posted")
            os.utime(path, (now + 1, now + 1))
            self.assertEqual(
                [("drc-1", "posted")],
                spacedock.read_entities(config, state, str(entity_state), stages, now + 2, 3600),
            )
        self.assertEqual(2, len(reads))

    @staticmethod
    def _same_tick(info: os.stat_result, first: os.stat_result) -> os.stat_result:
        """``info`` as Windows reports a rewrite inside ``first``'s timestamp tick.

        ``st_ctime`` there is the creation time, so it never moves on a write, and
        ``st_mtime`` only moves when the clock has ticked since the last write.
        """
        fields: list[Any] = [*list(info)[:10]]
        fields += [info.st_atime, first.st_mtime, first.st_ctime]
        fields += [info.st_atime_ns, first.st_mtime_ns, first.st_ctime_ns]
        return os.stat_result(fields)

    def test_a_same_size_readme_rewrite_inside_one_timestamp_tick_is_reread(self) -> None:
        # DRC-4707: on windows-latest a README renamed a stage and was restored
        # within one tick, at the same size, and the board kept the renamed
        # taxonomy: every part of the stat key matched the first reading.
        config, state = runtime()
        root = self.workflow(self.README)
        readme = root / "README.md"
        first = os.lstat(readme)
        self.assertIn("review", (spacedock.read_workflow(config, state, str(root)) or {})["stages"])
        readme.write_text(self.README.replace("name: review", "name: verify"), encoding="utf-8")
        real = os.lstat

        def lstat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            info = real(path, *args, **kwargs)
            return self._same_tick(info, first) if os.fspath(path) == str(readme) else info

        with mock.patch.object(os, "lstat", lstat):
            result = spacedock.read_workflow(config, state, str(root))
        self.assertEqual(["intake", "verify", "posted"], (result or {})["stages"])

    def test_a_settled_readme_is_read_once(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README)
        settled = time.time() - 60
        os.utime(root / "README.md", (settled, settled))
        reads: list[str] = []
        real = spacedock.read_frontmatter

        def counting(cfg: Any, p: str, limit: int, expect: os.stat_result) -> list[str]:
            reads.append(p)
            lines: list[str] = real(cfg, p, limit, expect)
            return lines

        with mock.patch.object(spacedock, "read_frontmatter", counting):
            spacedock.read_workflow(config, state, str(root))
            spacedock.read_workflow(config, state, str(root))
        self.assertEqual(1, len(reads))

    def test_a_same_size_entity_rewrite_inside_one_timestamp_tick_is_reread(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README)
        path = self.entity(root / ".spacedock-state", "drc-1", "review")
        first = os.lstat(path)
        self.assertEqual("review", spacedock.entity_stage(config, state, str(path), first))
        self.entity(root / ".spacedock-state", "drc-1", "verify")
        same_tick = self._same_tick(os.lstat(path), first)
        self.assertEqual("verify", spacedock.entity_stage(config, state, str(path), same_tick))

    def test_the_entity_dir_is_taken_from_boot_and_must_be_absolute(self) -> None:
        records: list[dict[str, Any]] = [
            {"command": "boot", "definition_dir": "/w", "entity_dir": "relative/state"},
            {"command": "boot", "definition_dir": "/other", "entity_dir": "/other/state"},
            {"command": "boot", "definition_dir": "/w", "entity_dir": "/w/state"},
            {"command": "boot", "definition_dir": "/w", "entity_dir": 17},
        ]

        self.assertEqual("/w/state", spacedock.boot_entity_dir(records, "/w"))
        self.assertEqual("/other/state", spacedock.boot_entity_dir(records, "/other"))
        self.assertEqual("", spacedock.boot_entity_dir(records, "/absent"))

    def test_a_failed_wrap_does_not_leak_the_descriptor(self) -> None:
        """os.fdopen leaves the fd open when it raises, and this runs every
        refresh — a leak here exhausts the descriptor table."""
        config, state = runtime()
        root = self.workflow(self.README)
        opened: list[int] = []
        real_open = os.open

        def counting_open(*args: object, **kwargs: object) -> int:
            descriptor = real_open(*args, **kwargs)  # type: ignore[arg-type]
            opened.append(descriptor)
            return descriptor

        with (
            mock.patch.object(os, "open", counting_open),
            mock.patch.object(os, "fdopen", side_effect=OSError("boom")),
        ):
            self.assertIsNone(spacedock.read_workflow(config, state, str(root)))

        self.assertEqual(1, len(opened))
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    def test_no_workflow_no_strip(self) -> None:
        config, state = runtime()
        now = time.time()
        self.assertEqual([], spacedock.session_workflows(config, state, [], [], now, 3600))
        self.assertEqual(
            [],
            spacedock.session_workflows(
                config,
                state,
                [{"command": "boot", "definition_dir": "/nonexistent/wf"}],
                [],
                now,
                3600,
            ),
        )

    def test_a_workflow_with_no_state_directory_still_costs_no_walk(self) -> None:
        config, state = runtime()
        root = self.workflow(self.README)
        boot = [
            {
                "command": "boot",
                "definition_dir": str(root),
                "entity_dir": str(root / ".spacedock-state"),
                "dispatchable": [],
            }
        ]

        self.assertEqual(
            [], spacedock.session_workflows(config, state, boot, [], time.time(), 3600)
        )
