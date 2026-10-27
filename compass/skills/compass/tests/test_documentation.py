from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar

from compass_runtime import (
    aggregate,
    claude_data,
    cli,
    ends,
    focus,
    git_status,
    history,
    project_context,
    reading,
    semantic_history,
)
from compass_runtime import config as runtime_config
from compass_runtime import events as runtime_events
from compass_runtime import transcripts as runtime_transcripts

from .decision_citations import citation_errors
from .support import (
    SERVER_PATH,
    make_config,
)


class CommandManualOptionsTest(unittest.TestCase):
    def test_option_rows_cover_every_parser_spelling(self) -> None:
        manual = (SERVER_PATH.parents[3] / "MANUAL.md").read_text(encoding="utf-8")
        first_cells = re.findall(r"^\| ([^|]+) \|", manual, flags=re.MULTILINE)
        documented = [
            option
            for cell in first_cells
            for option in re.findall(r"`(-{1,2}[a-z][a-z-]*)\b[^`]*`", cell)
        ]
        actual = {
            option for action in cli.build_parser()._actions for option in action.option_strings
        }
        self.assertEqual(set(documented), actual, "Update MANUAL.md option rows with the CLI")
        self.assertEqual(len(documented), len(set(documented)), "Document each spelling once")


class RuntimeDecisionCitationsTest(unittest.TestCase):
    def test_runtime_pointers_resolve(self) -> None:
        root = SERVER_PATH.parents[3]
        self.assertEqual(citation_errors(root, SERVER_PATH.parent / "compass_runtime"), [])

    def test_no_history_help_is_for_operators(self) -> None:
        help_text = cli.build_parser().format_help()
        self.assertIn("--no-history", help_text)
        self.assertNotIn("DEC-6", help_text)
        self.assertNotIn("SECURITY.md", help_text)

    def test_lexical_link_and_history_contract(self) -> None:
        cases = (
            ("# [D-4](docs/owner.md#ruling)", ""),
            ("// [NUI-1](docs/owner.md#explicit)", ""),
            ("/* [N-1](SECURITY.md#contract) */", ""),
            ("<!-- [AC1](docs/owner.md#ruling) -->", ""),
            ("# D-999", "missing local link or explicit history marker"),
            ("# [D-1](docs/missing.md#ruling)", "missing/nonlocal document"),
            ("# [D-1](docs/owner.md#absent)", "missing fragment"),
            ("# [D-1](docs/owner.md)", "missing fragment"),
            ("# [D-1](docs/owner.md#Ruling)", "missing fragment"),
            ("# [D-1](../SECURITY.md#contract)", "missing/nonlocal document"),
            ("# [D-1](other/owner.md#ruling)", "missing/nonlocal document"),
            ("# [D-1](https://example.com/a.md#ruling)", "missing/nonlocal document"),
            ("# decision-history: DR-8 | 4de75d29 | repaired grouping bug", ""),
            ("// decision-history: AC-3 | 2026-09-07 | replaced criterion", ""),
            ("# decision-history: D4 | 4de75d29 | ", "missing local link"),
            ("<!-- decision-history: D4 | 4de75d29 | -->", "missing local link"),
            ("/* decision-history: D4 | 4de75d29 | */", "missing local link"),
            ("# decision-history: D4 | yesterday | retired", "missing local link"),
            ("# decision-history: D4 | 4de75d29 | retired; D1 remains", "D1"),
            ("# [D1](docs/owner.md#ruling) D-2", "D-2"),
            ("# D-2 [context](docs/owner.md#ruling)", "D-2"),
            ("# [D-2]\n# (docs/owner.md#ruling)", "D-2"),
            ("# DRC-4396 A5 A6 A9 B2 S104 UTF-8 xD1 D1_suffix x-D1 D1-x", ""),
            # An existing unrelated heading passes: the reviewer checks meaning.
            ("# [DEC-13](docs/owner.md#unrelated)", ""),
        )
        with tempfile.TemporaryDirectory(prefix="bld-hyg-citations-") as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "owner.md").write_text(
                '# Ruling\n<a id="explicit"></a>\n## Unrelated\n', encoding="utf-8"
            )
            (root / "SECURITY.md").write_text("# Contract\n", encoding="utf-8")
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "nested").mkdir()
            (root / "tests").mkdir()
            (root / "tests/ignored.py").write_text("# D-999", encoding="utf-8")
            (runtime / "font.woff2").write_bytes(b"\xffD-999")
            for suffix in (".py", ".js", ".css", ".html"):
                source = runtime / "nested" / ("source" + suffix)
                for text, error in cases:
                    with self.subTest(suffix=suffix, text=text):
                        source.write_text(text, encoding="utf-8")
                        errors = citation_errors(root, runtime)
                        if error:
                            self.assertEqual(len(errors), 1, errors)
                            self.assertIn(error, errors[0])
                            self.assertIn(f"nested/source{suffix}:1:", errors[0])
                        else:
                            self.assertEqual(errors, [])
                source.unlink()


def _flat_section(security: str, heading: str) -> str:
    """The whitespace-collapsed text of ONE `## ` section of SECURITY.md.

    Four of the contract classes below assert clauses that now appear in several
    sections at once, because the groundwork sections deliberately reuse the
    unshipped-flag wording. An `assertIn` over the whole document then passes on
    a sibling's copy: measured, inverting the off-machine URL credential rule
    left its own class green, and inverting the light-harness flag claim went
    from red to green the moment a second copy existed. Slicing first is what
    makes each assertion about its own section again.

    Raises rather than returning an empty string if the heading is missing, so a
    renamed section fails loudly instead of making every assertion vacuous.
    """
    start = security.index(heading)
    rest = security[start + len(heading) :]
    end = rest.find("\n## ")
    body = rest if end == -1 else rest[:end]
    return re.sub(r"\s+", " ", heading + body)


def handler_methods(source: str) -> dict[str, str]:
    """Every method of `http_api._RequestHandler`, keyed by name.

    From the parse's line ranges rather than by slicing between two `def`
    markers. A slice inverts to the empty string the moment the two markers
    are reordered, and every `assertNotIn` against an empty string then passes
    without having read anything.
    """
    lines = source.splitlines(keepends=True)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "_RequestHandler":
            return {
                item.name: "".join(lines[item.lineno - 1 : item.end_lineno])
                for item in node.body
                if isinstance(item, ast.FunctionDef)
            }
    msg = "http_api._RequestHandler is gone; the pins below read its methods"
    raise AssertionError(msg)


class DocumentationMatchesCodeTest(unittest.TestCase):
    """Reviewers found documentation describing behaviour the code no longer
    had, twice. These assert the claims against the implementation."""

    SKILL = (SERVER_PATH.parent / "SKILL.md").read_text(encoding="utf-8")

    def posix_roots(self) -> dict[str, list[str]]:
        roots: dict[str, list[str]] = runtime_config.resolve_store_roots(
            platform_name="darwin", environ={}, home="/HOME"
        )
        return roots

    def test_intent_card_docs_do_not_describe_the_old_card(self) -> None:
        # The Intent card moved How Intent and drift works and Clear into its More menu
        # and draws Add a line, Remove, Save intent and Undo changes from the first view.
        root = SERVER_PATH.parents[3]
        stale = (
            "How Intent and drift works` button",
            "How Intent and drift works button",
            "appears after a goal edit",
            "Under the save, the Intent card holds the goal's",
            "`Remove` and `Add a line` appear",
        )
        for relative in (
            "compass/skills/compass/SKILL.md",
            "docs/promise-map.md",
            "docs/design-reader-state.md",
            "README.md",
        ):
            text = (root / relative).read_text(encoding="utf-8")
            for phrase in stale:
                self.assertNotIn(phrase, text, relative)
        reader_state = (root / "docs" / "design-reader-state.md").read_text(encoding="utf-8")
        self.assertIn("intent-menu", reader_state)

    def test_what_a_goal_with_no_outcome_line_reads_is_the_pages(self) -> None:
        # A goal alone is read for its own end state, or refused as too vague (owner, 2026-10-22). The
        # how-to on the page, the skill and the promise map say it in the same words, and none of them
        # says an outcome line is needed for a level, as the 2026-10-21 wording did.
        root = SERVER_PATH.parents[3]
        for relative in (
            "compass/skills/compass/SKILL.md",
            "docs/promise-map.md",
            "frontend/src/intent/HowTo.tsx",
        ):
            text = " ".join((root / relative).read_text(encoding="utf-8").split())
            with self.subTest(relative=relative):
                self.assertNotIn("is normal until you add an expected outcome line", text)
                self.assertNotIn("unless your goal departs", text)
                self.assertRegex(
                    text,
                    r"(?i)no outcome line, Compass reads your goal's end state"
                    r"[;,.] a goal too vague to read is\s+refused",
                )
        for relative in ("README.md", "docs/promise-map.md", "compass/skills/compass/SKILL.md"):
            text = " ".join((root / relative).read_text(encoding="utf-8").split())
            with self.subTest(relative=relative, sentence="needed"):
                self.assertNotIn("why an expected outcome line is needed for a drift level", text)

    def test_documented_store_paths_are_the_ones_searched(self) -> None:
        # Every "~/..." path in the data-source list must be a real default.
        # ".claude/settings" (the user's own hook config) and ".compass" (Compass's
        # own state and log directory) are not harness stores, so the store-root
        # assertion below does not apply to them.
        excluded_prefixes = (".claude/settings", ".compass")
        documented = {
            "~/" + match
            for match in re.findall(r"`~/([\w./*<>-]+?)[`/]", self.SKILL)
            if not match.startswith(excluded_prefixes)
        }
        searched = {
            root.replace("/HOME", "~") for roots in self.posix_roots().values() for root in roots
        }
        for path in sorted(documented):
            with self.subTest(documented=path):
                self.assertTrue(
                    any(
                        root.startswith(path.rstrip("/")) or path.startswith(root)
                        for root in searched
                    ),
                    f"SKILL.md documents {path} but nothing searches it: {sorted(searched)}",
                )

    def test_documented_env_overrides_are_the_ones_honoured(self) -> None:
        documented = {
            name
            for name in (
                "CLAUDE_CONFIG_DIR",
                "CODEX_HOME",
                "GEMINI_CLI_HOME",
                "COPILOT_HOME",
                "PI_CODING_AGENT_DIR",
                "PI_CODING_AGENT_SESSION_DIR",
            )
            if f"`{name}`" in self.SKILL
        }
        self.assertEqual(set(runtime_config.STORE_ENV_VARS), documented)
        # And each one actually redirects its store.
        for name, key, expected in (
            ("CLAUDE_CONFIG_DIR", "claude.projects", "/opt/x/projects"),
            ("CODEX_HOME", "codex.sessions", "/opt/x/sessions"),
            ("GEMINI_CLI_HOME", "gemini.tmp", "/opt/x/.gemini/tmp"),
            ("COPILOT_HOME", "copilot.root", "/opt/x"),
            ("PI_CODING_AGENT_DIR", "pi.sessions", "/opt/x/sessions"),
            ("PI_CODING_AGENT_SESSION_DIR", "pi.sessions", "/opt/x"),
        ):
            with self.subTest(env=name):
                roots = runtime_config.resolve_store_roots(
                    platform_name="linux", environ={name: "/opt/x"}, home="/HOME"
                )
                self.assertEqual([expected], roots[key])

    def test_the_documented_python_floor_matches_the_tooling(self) -> None:
        self.assertIn("Python 3.11+", self.SKILL)
        pyproject = (SERVER_PATH.parents[3] / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('python_version = "3.11"', pyproject)
        self.assertIn('target-version = "py311"', pyproject)

    def test_documented_urls_use_the_address_the_server_binds(self) -> None:
        # The listener is IPv4-only, so "localhost" can resolve to ::1 and fail.
        self.assertNotIn("http://localhost:4553", self.SKILL)
        self.assertIn("http://127.0.0.1:4553", self.SKILL)


class DocumentedCaptureFiguresTest(unittest.TestCase):
    """Prose that cites a capture file must still agree with the file.

    Four claims had drifted from the captures they name: a session count that
    was never five, a vocabulary comment saying every member was seen firing,
    and an "unobserved" its own paragraph refuted. A count stated in prose is
    checkable against the file it came from, so these check it.
    """

    ROOT = SERVER_PATH.parents[3]
    CAPTURES = ROOT / "docs" / "captures"
    NUMBERS: ClassVar[dict[int, str]] = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
    }

    @staticmethod
    def _every_pair(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """A JSON object with every pair kept, duplicates included.

        `json.loads` keeps the LAST value for a duplicate key and the discarded
        one never becomes a node in the walk, so a record carrying
        `{"record": "…", "record": "<a label>"}` passed the vocabulary check
        with the label sitting in the committed bytes. Verified as a defeat
        before this existed. The displaced value is parked under a slot named
        after the key it lost, which no vocabulary classifies, so a duplicate
        key fails the walk instead of hiding inside it. Last-wins is preserved
        for every other assertion, which reads these records as plain dicts.
        """
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                out[f"{key} <duplicate {len(out)}>"] = out[key]
            out[key] = value
        return out

    @classmethod
    def records(cls, path: Path) -> list[dict[str, Any]]:
        lines = path.read_text(encoding="utf-8").splitlines()
        return [
            json.loads(line, object_pairs_hook=cls._every_pair) for line in lines if line.strip()
        ]

    @staticmethod
    def unwrapped(relative: str) -> str:
        source = DocumentedCaptureFiguresTest.ROOT / relative
        return " ".join(source.read_text(encoding="utf-8").split())

    def test_the_documented_gemini_session_count_is_the_one_in_the_capture(self) -> None:
        # The hooks capture is the only Gemini file carrying a session marker,
        # so it is the only one that can settle the count the adapters cite.
        sessions = {
            record["session"]
            for record in self.records(self.CAPTURES / "gemini" / "hooks-0.53.1-macos.jsonl")
        }
        claim = f"Measured from {self.NUMBERS[len(sessions)]} real 0.53.1 sessions"
        for relative in (
            "compass/skills/compass/event_hook.py",
            "compass-gemini/hooks/event_hook.py",
            "compass-droid/hooks/event_hook.py",
        ):
            with self.subTest(source=relative):
                self.assertIn(claim, self.unwrapped(relative))

    def test_the_gemini_identity_capture_cannot_count_its_own_sessions(self) -> None:
        # `events.py` said five sessions. The file holds five verdict records
        # and no session marker at all, so it cannot say how many sessions
        # wrote them; the comment states the record count instead.
        records = self.records(self.CAPTURES / "gemini" / "identity-0.53.1-macos.jsonl")
        self.assertTrue(all("session" not in record for record in records))
        self.assertTrue(
            all(
                record["id_verdicts"]["session_id"]["equals_store_line1_sessionId"]
                for record in records
            )
        )
        claim = f"in {self.NUMBERS[len(records)]} recorded verdicts"
        self.assertIn(claim, self.unwrapped("compass/skills/compass/compass_runtime/events.py"))

    def test_an_unfired_gemini_event_is_named_beside_the_vocabulary(self) -> None:
        # The allowlist is the documented vocabulary, which is wider than the
        # measured one. A member that never fired has to be called out where
        # the set is declared, or the comment claims evidence it does not have.
        fired = {
            record["event"]
            for record in self.records(self.CAPTURES / "gemini" / "hooks-0.53.1-macos.jsonl")
        }
        source = (self.ROOT / "scripts" / "validate_plugins.py").read_text(encoding="utf-8")
        entry = source.split('/hooks/hooks.json": (\n        "gemini",', 1)[1]
        comment, names = entry.split("frozenset(", 1)
        declared = set(re.findall(r'"(\w+)"', names.split("}", 1)[0]))
        self.assertIn("SessionStart", declared)
        for name in sorted(declared - fired):
            with self.subTest(never_fired=name):
                self.assertIn(name, comment)

    # Globs rather than filenames. Both recorders are versioned in their own
    # names, so a re-record at a new harness build or a second drive lands
    # beside the file it supersedes -- and a hardcoded tuple then walks the old
    # one and nothing else, which is the same "read one of two files" defeat
    # this oracle was rewritten to close.
    REGISTRY_GLOB = "claude/team-registry-*.jsonl"
    DRIVE_GLOB = "claude/teammate-board-drive-*.jsonl"
    # Both DRC-4344 stores hold operator text, so the shapes-never-values rule
    # is checked over every file either recorder has written.
    TEAMMATE_CAPTURE_GLOBS: ClassVar[tuple[str, ...]] = (REGISTRY_GLOB, DRIVE_GLOB)

    # A POSITIVE vocabulary, and it has to be one. The first version of this
    # check bounded strings at 64 characters, which was defeatable six ways: it
    # walked values and never keys, it exempted two containers, and the bound sat
    # ABOVE the text it guarded, since the labels these files must not carry are
    # `agentName` values and workflow identifiers and the harness caps its own
    # names at 64. A structural rule fails for the same reason -- a workflow
    # identifier is shaped exactly like a field name. So every string in these
    # files, key or value, at any depth, must be a member of one of the sets
    # below or match one of the patterns. A string nobody has classified fails,
    # which is the only form of this check that a label cannot walk through.
    _SCHEMA_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            # The keys the two recorders write.
            "format",
            "harness",
            "os",
            "at",
            "record",
            "claude_version",
            "registry",
            "registry_mtime_age_days",
            "top_level_keys",
            "member_fields",
            "member_count",
            "members",
            "backendType",
            "isActive",
            "isActive_present",
            "joinedAt_type",
            "older_registry_fields",
            "newer_registry_fields",
            "added",
            "removed",
            "added_fields_the_runtime_reads",
            "added_fields_deliberately_unread",
            "layout",
            "session",
            "record_types_in_order",
            "first_timestamped_record_index",
            "header_fields",
            "files",
            "first_timestamped_record_index_per_file",
            "reads_at_index_zero",
            "verdict",
            "arm",
            "lead",
            "element_key_sets",
            "element_keys_uniform",
            "published_total",
            "published_with_a_measured_start",
            "published_with_a_null_start",
            "direct_children",
            "grandchildren",
            "grandchildren_active",
            "distinct_parents_named",
            "active_true",
            "active_false",
            "active_null",
            "state",
            "state_detail_shape",
            "state_detail_subagent_count",
            "chrome_running_subagents",
            "chrome_published_subagents",
            "registered_members",
            "before_published",
            "before_with_a_measured_start",
            "before_grandchildren_reachable",
            "after_published",
            "after_with_a_measured_start",
            "after_grandchildren_reachable",
            "after_distinct_parents_named",
            "grandchildren_active_while_running",
            "grandchildren_present_after_they_stopped",
            "grandchildren_active_after_they_stopped",
            "state_detail_counts_grandchildren",
            "ac4_state_fields_moved_old_vs_new",
            "ac4_sessions_compared",
            "state_detail_counts_only_direct_children",
            "a_quiet_teammate_reads_inactive_while_its_own_worker_runs",
            "state_may_lag_a_demoted_child_by_seconds",
        }
    )
    _HARNESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            # Field names read out of the harness's own stores. A new harness build
            # that adds one fails this check until somebody classifies it, which is
            # the behaviour an evidence file wants.
            "agentId",
            "agentName",
            "agentSetting",
            "agentType",
            "apiBlockIndex",
            "attributionAgent",
            "attributionPlugin",
            "attributionSkill",
            "color",
            "createdAt",
            "cwd",
            "effort",
            "entrypoint",
            "gitBranch",
            "isSidechain",
            "isSnapshotUpdate",
            "joinedAt",
            "leadAgentId",
            "leadSessionId",
            "leafUuid",
            "members",
            "message",
            "messageId",
            "model",
            "name",
            "parentUuid",
            "permissionMode",
            "planModeRequired",
            "prompt",
            "requestId",
            "sessionId",
            "session_id",
            "snapshot",
            "sourceToolAssistantUUID",
            "started_at",
            "subscriptions",
            "teamName",
            "timestamp",
            "tmuxPaneId",
            "toolUseResult",
            "type",
            "userType",
            "uuid",
            "version",
            "active",
            "parent",
        }
    )
    _HARNESS_TOKENS: ClassVar[frozenset[str]] = frozenset(
        {
            # Closed vocabularies the harness or the recorder picks from, never text
            # a person wrote. Same class as `tool` and `notification_type` in the
            # captures README.
            "agent-setting",
            "mode",
            "permission-mode",
            "user",
            "assistant",
            "attachment",
            "atis",
            "atis-latch",
            "last-prompt",
            "file-history-snapshot",
            "in-process",
            "tmux",
            "claude",
            "darwin",
            "working",
            "team_registry_shape",
            "registry_field_drift",
            "transcript_header_shape",
            "first_timestamp_index_verdict",
            "board_drive_arm",
            "board_drive_verdict",
            "top_level",
            "legacy_subagents",
            "positive",
            "negative",
            "control_before",
        }
    )
    _RECORDER_SENTENCES: ClassVar[frozenset[str]] = frozenset(
        {
            # Composed by the recorder from a measurement, not copied from a store.
            "a one-line read finds the start stamp",
            "a one-line read misses the start stamp",
            "running N subagents",
        }
    )
    _PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(?:null|bool|int|float|string|list|object|unknown)$"),  # type names
        re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),  # ISO stamp
        re.compile(r"^[0-9a-f]{8}$"),  # an 8-char session prefix, the README's allowance
        re.compile(r"^[0-9a-f]{12}$"),  # a salted digest
        re.compile(r"^\d+\.\d+\.\d+$"),  # a harness version
        re.compile(r"^agent-[0-9a-f]{2}$"),  # a legacy subagent filename prefix
    )
    FORBIDDEN: ClassVar[frozenset[str]] = frozenset({"prompt", "message"})

    @classmethod
    def strings(cls, node: Any, trail: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
        """Every string in the record, KEYS INCLUDED.

        Walking values alone was the hole: a key is a string a recorder chose to
        write and is exactly as capable of carrying a label as a value is.
        """
        if isinstance(node, dict):
            out: list[tuple[tuple[str, ...], str]] = []
            for key, value in node.items():
                out.append(((*trail, "<key>"), str(key)))
                out += cls.strings(value, (*trail, str(key)))
            return out
        if isinstance(node, list):
            return [pair for value in node for pair in cls.strings(value, trail)]
        return [(trail, node)] if isinstance(node, str) else []

    @classmethod
    def classified(cls, text: str) -> bool:
        if (
            text in cls._SCHEMA_KEYS
            or text in cls._HARNESS_FIELDS
            or text in cls._HARNESS_TOKENS
            or text in cls._RECORDER_SENTENCES
        ):
            return True
        return any(pattern.match(text) for pattern in cls._PATTERNS)

    def matching(self, pattern: str) -> list[Path]:
        found = sorted(self.CAPTURES.glob(pattern))
        self.assertTrue(found, f"{pattern} must match at least one capture")
        return found

    def registry_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in self.matching(self.REGISTRY_GLOB):
            found = self.records(path)
            self.assertTrue(found, f"{path.name} must not be empty")
            records += found
        return records

    def teammate_capture_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for pattern in self.TEAMMATE_CAPTURE_GLOBS:
            for path in self.matching(pattern):
                found = self.records(path)
                self.assertTrue(found, f"{path.name} must not be empty")
                records += found
        return records

    def test_every_string_in_a_teammate_capture_is_classified(self) -> None:
        # The whole privacy rule for these two files, in one assertion over both.
        # Falsified by: any string a recorder puts in either file that nobody has
        # classified -- an `agentName`, a workflow identifier, a description, a
        # path. A label cannot pass this the way it passed a length bound.
        unclassified = sorted(
            {
                text
                for record in self.teammate_capture_records()
                for _trail, text in self.strings(record)
                if not self.classified(text)
            }
        )
        self.assertEqual([], unclassified, "unclassified strings in a capture file")

    def test_a_teammate_captures_field_shapes_hold_only_type_names(self) -> None:
        # A field map may say what type a field holds and never what it held.
        # Falsified by: a shape map whose value is content rather than a type.
        types = {"null", "bool", "int", "float", "string", "list", "object", "unknown"}
        for record in self.teammate_capture_records():
            for name in ("member_fields", "header_fields"):
                for field, declared in (record.get(name) or {}).items():
                    self.assertLessEqual(
                        set(declared), types, f"{name}[{field}] must hold type names"
                    )

    def test_a_teammate_capture_names_a_forbidden_field_without_reading_it(self) -> None:
        # `prompt` and `message` may be named and never valued. Named `prompt`
        # must be, or the capture does not evidence the field the runtime refuses
        # to read.
        # Falsified by: a key called `prompt` holding a string, or dropping it
        # from the drift record.
        shape_maps = ("member_fields", "header_fields")
        name_lists = (
            "added",
            "removed",
            "top_level_keys",
            "older_registry_fields",
            "newer_registry_fields",
            "added_fields_the_runtime_reads",
            "added_fields_deliberately_unread",
        )
        for record in self.teammate_capture_records():
            for trail, value in self.strings(record):
                declared = bool(trail) and (trail[0] in shape_maps or trail[-1] in name_lists)
                if declared or (trail and trail[-1] == "<key>"):
                    continue
                self.assertNotIn(
                    trail[-1] if trail else "",
                    self.FORBIDDEN,
                    f"{'.'.join(trail)} records that field's value",
                )
                self.assertNotIn(value.strip().lower(), self.FORBIDDEN, f"{'.'.join(trail)}")
        drift = [r for r in self.registry_records() if r["record"] == "registry_field_drift"]
        self.assertTrue(drift, "the capture must record the registry's field drift")
        for record in drift:
            self.assertIn("prompt", record["added"])
            self.assertIn("prompt", record["added_fields_deliberately_unread"])
            self.assertNotIn("prompt", record["added_fields_the_runtime_reads"])

    def test_the_team_registry_capture_settles_the_start_stamp_index(self) -> None:
        # DRC-4344's first gap in one figure, and it must come from the file
        # rather than the code: a top-level transcript's first timestamped record
        # is not record 0, and a legacy subagent's is.
        # Falsified by: a capture whose two layouts agree, which would mean the
        # asymmetry the fix rests on was never measured.
        verdicts = {
            record["layout"]: record
            for record in self.registry_records()
            if record["record"] == "first_timestamp_index_verdict"
        }
        self.assertEqual({"top_level", "legacy_subagents"}, set(verdicts))
        top, legacy = verdicts["top_level"], verdicts["legacy_subagents"]
        self.assertEqual(0, top["reads_at_index_zero"], "no top-level file stamps record 0")
        self.assertEqual(
            legacy["files"], legacy["reads_at_index_zero"], "every legacy file stamps record 0"
        )
        self.assertNotEqual(top["verdict"], legacy["verdict"])

    _PERSONAL_PATH_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:/Users/|/home/|[A-Za-z]:[/\\]Users[/\\])", re.IGNORECASE
    )
    _EMAIL_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    )

    @classmethod
    def find_privacy_violations(
        cls, records: list[dict[str, Any]]
    ) -> list[tuple[int, tuple[str, ...], str]]:
        """Scan parsed JSONL records for personal path or email violations.

        Returns a list of (row_1_indexed, safe_trail, violation_kind).
        The actual offending string is NEVER included in the returned tuple
        to prevent diagnostic leakage.
        """
        violations: list[tuple[int, tuple[str, ...], str]] = []
        for row_idx, record in enumerate(records, start=1):
            for trail, text in cls.strings(record):
                kind: str | None = None
                if cls._PERSONAL_PATH_RE.search(text):
                    kind = "personal path detected"
                elif cls._EMAIL_RE.search(text):
                    kind = "email address detected"
                if kind is not None:
                    safe_trail = tuple(
                        "<sensitive-key>"
                        if (cls._PERSONAL_PATH_RE.search(elem) or cls._EMAIL_RE.search(elem))
                        else elem
                        for elem in trail
                    )
                    violations.append((row_idx, safe_trail, kind))
        return violations

    def test_every_capture_file_satisfies_corpus_privacy_contract(self) -> None:
        # Every committed docs/captures/**/*.jsonl record is checked, including
        # nested strings, string keys and duplicate-key values. Rejects captured
        # personal paths, email addresses, and prompt/tool text without echoing
        # the rejected values in diagnostic output.
        capture_paths = sorted(self.CAPTURES.glob("**/*.jsonl"))
        self.assertTrue(capture_paths, "must find capture files in docs/captures")
        all_violations: list[str] = []
        for path in capture_paths:
            rel = path.relative_to(self.ROOT)
            records = self.records(path)
            for row_idx, trail, kind in self.find_privacy_violations(records):
                all_violations.append(f"{rel}:{row_idx} at {'.'.join(trail)}: {kind}")
        self.assertEqual([], all_violations, "corpus capture files contain privacy violations")

    def test_corpus_privacy_assertion_rejects_synthetic_violations_without_echoing_content(
        self,
    ) -> None:
        synthetic_path = "/Users/secretuser/private_project/secret_file.txt"
        synthetic_email = "confidential_agent@example.com"

        # 1. Nested value carrying an absolute personal path
        records_nested_val = [json.loads(json.dumps({"outer": {"inner": synthetic_path}}))]
        v_val = self.find_privacy_violations(records_nested_val)
        self.assertEqual(1, len(v_val))
        self.assertEqual((1, ("outer", "inner"), "personal path detected"), v_val[0])

        # 2. Key carrying an absolute personal path
        records_key = [json.loads(json.dumps({synthetic_path: "clean_value"}))]
        v_key = self.find_privacy_violations(records_key)
        self.assertTrue(any("personal path detected" in v[2] for v in v_key))

        # 3. Duplicate key whose displaced value carried an absolute personal path
        dup_json = f'{{"path": "{synthetic_path}", "path": "safe"}}'
        records_dup = [json.loads(dup_json, object_pairs_hook=self._every_pair)]
        v_dup = self.find_privacy_violations(records_dup)
        self.assertTrue(any("personal path detected" in v[2] for v in v_dup))

        # 4. Email address
        records_email = [json.loads(json.dumps({"author": synthetic_email}))]
        v_email = self.find_privacy_violations(records_email)
        self.assertEqual(1, len(v_email))
        self.assertEqual((1, ("author",), "email address detected"), v_email[0])

        # 5. Permitted vocabulary control passes
        permitted = [
            json.loads(
                json.dumps(
                    {
                        "format": 2,
                        "harness": "codex",
                        "event": "Notification",
                        "notification_type": "permission_prompt",
                        "tool": "Bash",
                    }
                )
            )
        ]
        self.assertEqual([], self.find_privacy_violations(permitted))

        # 6. Verify that formatted reports do not echo sensitive strings
        formatted_reports = [
            f"file.jsonl:{row_idx} at {'.'.join(trail)}: {kind}"
            for row_idx, trail, kind in v_val + v_key + v_dup + v_email
        ]
        for report in formatted_reports:
            self.assertNotIn(synthetic_path, report)
            self.assertNotIn(synthetic_email, report)

    def test_the_capture_files_table_is_one_block(self) -> None:
        # Two rows were left stranded below the prose that follows the table,
        # and every capture PR adds its row by copying the one above it, so a
        # split table hands the next author a broken precedent.
        lines = (self.CAPTURES / "README.md").read_text(encoding="utf-8").splitlines()
        rows = [number for number, line in enumerate(lines) if line.startswith("| `")]
        self.assertEqual(list(range(rows[0], rows[0] + len(rows))), rows)

    def test_a_post_turn_idle_push_carries_an_id_in_the_antigravity_capture(self) -> None:
        # `statusline_hook.py` called this unobserved. One of its two arms ended
        # on exactly such a push: `idle`, after `working`, carrying an id. The
        # prose states the id's width and that it named a real db, so the filter
        # reads those two verdict fields rather than the dict's truthiness -- a
        # re-recorded capture carrying `{"len": 12, "matches_a_db_stem": false}`
        # would otherwise leave this green while the sentence went false.
        arms: dict[str, list[dict[str, Any]]] = {}
        for record in self.records(self.CAPTURES / "antigravity" / "statusline-macos.jsonl"):
            arms.setdefault(record["capture"], []).append(record)
        ended_idle_with_id = []
        for arm, pushes in arms.items():
            verdict = pushes[-1]["id_verdicts"]["conversation_id"] or {}
            if (
                pushes[-1]["agent_state"] == "idle"
                and verdict.get("len") == 36
                and verdict.get("matches_a_db_stem")
                and any(push["agent_state"] == "working" for push in pushes[:-1])
            ):
                ended_idle_with_id.append(arm)
        self.assertEqual(2, len(arms))
        claim = f"{self.NUMBERS[len(ended_idle_with_id)].capitalize()} of the two arms"
        # Both the shipped adapter and the durable design record state this. A
        # correction that lands in one leaves the repository contradicting
        # itself, which is the drift DRC-4193 exists to close.
        for relative in (
            "compass/skills/compass/statusline_hook.py",
            "docs/design-event-driven-observation.md",
        ):
            with self.subTest(source=relative):
                self.assertIn(claim, self.unwrapped(relative))


class EventEnvelopeEnumerationTest(unittest.TestCase):
    """Every prose count of the envelope, held to the sets those counts describe.

    Both SECURITY.md enumerations had drifted, silently, because nothing read the
    prose and the code together: the document said the envelope carries "the nine
    permitted fields" after `ALLOWED_FIELDS` reached twelve (the three `tmux_*`
    members arrived with DRC-4017), and it named six writable overlay fields
    while `PATCHABLE` held eight. A number in prose is a claim about a set, and
    an unchecked claim is how the security contract comes to describe a narrower
    system than the one that shipped — which is the direction that matters here.

    `config.py` is checked here too, and it is why: reading SECURITY.md alone let
    a third copy of the same stale nine survive the pass that fixed the other
    two. The cap it justifies is a security bound, so its stated reason is worth
    the same guard as the contract's.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    FLAT: ClassVar[str] = re.sub(r"\s+", " ", SECURITY)
    NUMBER_WORDS: ClassVar[dict[int, str]] = {
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
        11: "eleven",
        12: "twelve",
        13: "thirteen",
        14: "fourteen",
    }

    def test_the_documented_envelope_width_is_the_allowlist_the_code_enforces(self) -> None:
        word = self.NUMBER_WORDS[len(runtime_events.ALLOWED_FIELDS)]
        self.assertIn(f"builds the {word} permitted fields one at a time", self.FLAT)

    def test_the_body_caps_stated_reason_is_the_allowlist_the_code_enforces(self) -> None:
        # `event_body_cap_bytes` is justified by the envelope's width, so a stale
        # width there is a security bound resting on a number that is no longer
        # true.
        word = self.NUMBER_WORDS[len(runtime_events.ALLOWED_FIELDS)]
        source = (SERVER_PATH.parent / "compass_runtime" / "config.py").read_text(encoding="utf-8")
        self.assertIn(f"envelope is {word} short fields", " ".join(source.split()))

    def test_the_documented_overlay_writes_are_exactly_the_patchable_set(self) -> None:
        # Set equality against the backticked names in that one sentence, which is
        # why the sentence names every field rather than glossing one as "the
        # acquisition marker": a prose alias is a name this test cannot check.
        match = re.search(r"it can only write these (\w+) fields: (.*?)\. `--no-events`", self.FLAT)
        assert match is not None, "SECURITY.md no longer enumerates the overlay writes"
        self.assertEqual(self.NUMBER_WORDS[len(runtime_events.PATCHABLE)], match.group(1))
        self.assertEqual(
            set(runtime_events.PATCHABLE),
            set(re.findall(r"`([a-z_]+)`", match.group(2))),
        )


class PublishedTextCarrierEnumerationTest(unittest.TestCase):
    """The published-prompt-text list, held to the fields the sweep actually redacts.

    The list read as exhaustive and was not. It named five things — a session
    title, "the line beneath it", `last_prompt`, the observer goal and a Codex
    title — while `aggregate` redacts seven raw carriers, four of them nested in
    `tasks` and `subagents`, and `aggregate`'s own table comment records that
    `state_detail` and `subagents[].name` were each forgotten once already. So
    the count in prose was a claim about a set that nothing read.

    "The line beneath it" is gone from all three copies for the reason
    `EventEnvelopeEnumerationTest` gives for not glossing the acquisition
    marker: a prose alias is a name no test can check. It resolved to
    `state_detail`, and the phrase was defined nowhere in the repository.

    Keyed on `_RAW_ROW_TEXT` and `_RAW_NESTED_TEXT` rather than on the producing
    sites, which #295 already pinned in
    `IrreversibleActionsContractDocumentationTest`. Nested keys are compared as
    `field[].key`, the spelling the prose uses, so a key that moves between the
    two lists cannot satisfy the other one's entry.

    All three copies are checked because they had already drifted apart, and one
    of them is in `docs/design-credential-redaction.md`, outside SECURITY.md
    entirely: a fix that lands in one place leaves the other two contradicting
    it, which is worse than the original understatement.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    # The canonical copy, sliced, so the history section's copy cannot satisfy an
    # assertion made about this one.
    SECTION = _flat_section(SECURITY, "## Published text (credential redaction)")
    HISTORY = _flat_section(SECURITY, "## Local history (the session history store)")
    DESIGN: ClassVar[str] = re.sub(
        r"\s+",
        " ",
        (ROOT / "docs/design-credential-redaction.md").read_text(encoding="utf-8"),
    )
    NUMBER_WORDS: ClassVar[dict[int, str]] = {
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
    }
    # Terminated on a period FOLLOWED BY A SPACE, because `tasks[].subject`
    # carries a period of its own and a bare `\.` stops inside the first entry.
    CLAUSE: ClassVar[str] = r"the carriers that reach the page raw are these (\w+): (.*?)\. "

    @classmethod
    def carriers(cls) -> set[str]:
        return set(aggregate._RAW_ROW_TEXT) | {
            f"{field}[].{key}" for field, keys in aggregate._RAW_NESTED_TEXT for key in keys
        }

    def test_the_named_carriers_are_exactly_the_fields_the_sweep_redacts(self) -> None:
        match = re.search(self.CLAUSE, self.SECTION)
        assert match is not None, "SECURITY.md no longer enumerates the raw carriers"
        self.assertEqual(self.NUMBER_WORDS[len(self.carriers())], match.group(1))
        self.assertEqual(
            self.carriers(),
            set(re.findall(r"`([A-Za-z_]+(?:\[\]\.[A-Za-z_]+)?)`", match.group(2))),
        )

    def test_all_three_copies_of_the_list_name_the_same_carriers(self) -> None:
        canonical = re.search(self.CLAUSE, self.SECTION)
        assert canonical is not None
        for name, copy in (("Local history", self.HISTORY), ("the design doc", self.DESIGN)):
            with self.subTest(copy=name):
                found = re.search(self.CLAUSE, copy)
                assert found is not None, f"{name} no longer enumerates the raw carriers"
                self.assertEqual(canonical.group(0), found.group(0))

    def test_no_copy_still_glosses_a_carrier_as_the_line_beneath_it(self) -> None:
        for name, copy in (
            ("Published text", self.SECTION),
            ("Local history", self.HISTORY),
            ("the design doc", self.DESIGN),
        ):
            with self.subTest(copy=name):
                self.assertNotIn("the line beneath it", copy)


class GitProbeContractDocumentationTest(unittest.TestCase):
    """SECURITY.md's git-probe section is a contract, so the code must still meet it.

    The section was written and reviewed on its own cycle before this code existed
    (DRC-4274, promoted here from `docs/plans/git-probe-security-scope.md` and that
    file deleted in the same commit). Prose and code can only agree by accident
    unless something compares them, and this is the comparison.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    # Whitespace-collapsed, so a reflow that changes no words does not fail these.
    # The command assertion below deliberately reads the raw text instead.
    FLAT = re.sub(r"\s+", " ", SECURITY)
    RUNTIME = SERVER_PATH.parent / "compass_runtime"

    def test_the_documented_command_is_the_argv_the_probe_builds(self) -> None:
        # The contract prints the command as an indented code block. If either side
        # gains or loses a flag, this fails; none may be dropped quietly.
        self.assertIn(
            "    " + " ".join(git_status.GIT_STATUS_ARGV) + "\n",
            self.SECURITY,
        )

    def test_the_contract_section_survived_the_promotion(self) -> None:
        self.assertIn("## Repository git reads (the end-of-session probe)", self.SECURITY)
        # The two intro amendments that had to ride with it. Without the first the
        # section is filed under a Scope clause enumerating file reads, harness-store
        # writes and non-loopback traffic — none of which is subprocess execution.
        self.assertIn(
            "running any program inside a user's repository other than the probe described in "
            "Repository git reads (the end-of-session probe),",
            self.FLAT,
        )
        # Amended 2026-09-07 (DEC-11). The old wording said the probe "neither
        # writes there nor executes anything the repository supplies", and a
        # reproduction falsified both halves: four hooks at mode 0755 written by
        # one probe, and a filter driver executed. `core.hooksPath=/dev/null`
        # closed the hook write and nothing else. A probe on a FRESH CLONE, with
        # an empty local filter config, still ran git-lfs and still added a file
        # under `.git/lfs/objects/`, so no unqualified "writes nothing" survives.
        self.assertIn(
            "The git probe runs inside a repository the user chose rather than a harness store. "
            "Git writes nothing there on the probe's behalf, and Compass runs no program of its "
            "own;",
            self.FLAT,
        )
        self.assertNotIn("It writes nothing there", self.FLAT)
        # Not a bare assertNotIn: the focus section QUOTES the retracted wording
        # on purpose, to record what DEC-11 retracted and why. So this asserts
        # over everything BEFORE that section. Splitting at "## Project reads"
        # instead left "## Repository git reads" unguarded, which is the one
        # section where the claim would actually be restored.
        asserted = self.FLAT.split("### What the command can still cause")[0]
        self.assertNotIn("neither writes there nor executes anything", asserted)
        # And where it does survive, it is marked as history rather than standing.
        self.assertIn(
            "The git probe's contract used to carry the stronger claim, that it \"neither writes "
            'there nor executes anything the repository supplies", and DEC-11 retracted it',
            self.FLAT,
        )

    def test_the_contract_states_how_the_probe_is_spawned(self) -> None:
        # Two properties that are not visible in the argv the section prints, so
        # a reader checking the argv alone would conclude neither is enforced.
        # Both were measured falsifiable before the fix: a relative PATH element
        # supplied the binary from the session's own directory, and an inherited
        # GIT_DIR published another repository's reading for a clean one.
        self.assertIn("The executable is resolved, not looked up by the child.", self.FLAT)
        self.assertIn(
            "The child's environment is scrubbed of `GIT_DIR` and `GIT_WORK_TREE`.", self.FLAT
        )
        # The rule that both the register and its verifier stated wrongly, in
        # opposite directions. Stated here so the document carries the correction.
        self.assertIn("The rule is order rather than position", self.FLAT)
        # DRC-4454. The section used to say "Empty and relative elements are now
        # dropped rather than reordered", and the code dropped a named pair — the
        # empty element and `.` — so a bare `relbin` survived and supplied the
        # binary from the directory being probed. The replacement names both ends
        # of the guard, because one end has already been wrong once.
        self.assertIn(
            "Every non-absolute PATH element is dropped, and the resolution refuses a relative "
            "answer as well.",
            self.FLAT,
        )
        self.assertNotIn("Empty and relative elements are now dropped", self.FLAT)
        # And the violation clause has to name them, or they are documented
        # behaviour rather than boundaries.
        self.assertIn("an executable taken from anywhere but the resolved absolute path", self.FLAT)
        # Discovery includes gitfiles and local core.worktree configuration;
        # containment alone would contradict the accepted residual (DRC-4492).
        self.assertIn(
            "a reading published about any repository but the one git discovers from the "
            "directory it names, subject to the metadata and working-tree selection described above",
            self.FLAT,
        )
        self.assertNotIn("a reading published about any directory but the one it names", self.FLAT)

    def test_the_contract_states_the_bound_on_probes_in_flight(self) -> None:
        # DRC-4443. Derived from the runtime rather than written twice: the
        # ceiling moving in code and not in the section, or the reverse, fails
        # here. The cadence sentence beside it is not this claim — one edge per
        # session, at most once each, still allowed 960 live probes.
        ceiling = make_config().git_probe_max_inflight
        self.assertIn(f"at most {ceiling} in flight across every harness", self.FLAT)
        self.assertIn("a session already being probed is refused a second probe", self.FLAT)
        # The two gates refuse for different reasons and cost different things.
        # The section said only the per-key cost, which is a stale reading; a
        # ceiling refusal has no first probe to fall back on, until another
        # eligible end dispatches it (including a redelivery in the same process).
        self.assertIn("A session refused by the ceiling publishes no reading at all", self.FLAT)

    def test_the_scrubbed_names_are_the_ones_the_runtime_drops(self) -> None:
        # Derived rather than a second literal list: a name added to the code and
        # not to the section, or the reverse, fails here.
        for name in git_status.DETACHING_ENV:
            self.assertIn(f"`{name}`", self.SECURITY)

    def test_the_documented_command_names_the_hooks_path_flag_in_words(self) -> None:
        # The sibling above derives its expectation from GIT_STATUS_ARGV, so a
        # flag dropped from BOTH sides passes it. This literal is the half that
        # cannot agree with a wrong constant, and it exists for this flag in
        # particular because the section's own claim was falsified once without it.
        self.assertIn(
            "git -c core.fsmonitor= -c core.hooksPath=/dev/null "
            "-c status.showUntrackedFiles=normal --no-optional-locks status "
            "--porcelain",
            self.FLAT,
        )

    def test_the_section_states_the_residual_rather_than_implying_none(self) -> None:
        # A section that lists three flags and stops reads as a closed boundary.
        # The filter driver still runs AND still writes; no argv closes either,
        # so the document says so.
        self.assertIn(
            "### The residual: a filter driver can still run, and can still write",
            self.SECURITY,
        )
        self.assertIn(
            "The third flag suppresses the hook installation and neither the invocation nor what "
            "the driver does once running.",
            self.FLAT,
        )
        # The bound the first version of this section got wrong, and the reason
        # DEC-11's ruling says the two hazards must not be blurred. The git-lfs
        # half IS clone-portable; only an attacker-chosen driver command needs
        # the inspected repository's own config.
        self.assertIn("So this is clone-portable", self.FLAT)
        self.assertNotIn("so a clone does not carry it", self.FLAT)
        # And the trigger is not a modified file: a racy-clean tree reaches it.
        self.assertIn("it does not require a modified file", self.FLAT)
        # And the violation clause has to be true of shipped behaviour, or it is
        # a document admitting a bug it declines to name.
        self.assertIn(
            "any write inside the user's repository that Compass's own argv could have prevented.",
            self.FLAT,
        )

    def test_the_section_states_the_upward_walk_residual_and_why_it_stands(self) -> None:
        # DRC-4442 R11, decided 2026-09-07 as accept-and-document. Two things this
        # has to keep saying, and each one is a mistake somebody would otherwise
        # make again.
        #
        # First, the hazard is not claimed impossible. It is unreachable on the
        # machine that was measured, where $HOME is not a repository, and a
        # dotfiles checkout at $HOME reaches it. "Cannot happen" would be the
        # confident-wrong-answer-in-an-absence failure this project keeps hitting.
        #
        # Second, GIT_CEILING_DIRECTORIES is recorded as measured-not-to-work
        # rather than as a fix declined on cost. Both arms published the parent's
        # reading with the ceiling set to the probed cwd, identical to no ceiling,
        # so a reader who thinks it was merely too expensive will re-propose it.
        self.assertIn(
            "### The residual: the reading is about the repository, not about the directory",
            self.SECURITY,
        )
        self.assertIn(
            "`git status` discovers repository metadata by walking upward from the directory "
            "it runs in",
            self.FLAT,
        )
        self.assertIn(
            "It is not reachable on the machine these measurements were taken on", self.FLAT
        )
        self.assertIn("changed nothing in either arm", self.FLAT)
        self.assertIn("measured not to do the thing it was proposed to do", self.FLAT)
        # Never a claim of impossibility, however phrased. Scoped to this residual
        # rather than to the whole file: a legitimate "is impossible" elsewhere in
        # the document is not this defect, and a whole-file ban would fail on it.
        opens = self.FLAT.index("The residual: the reading is about the repository")
        closes = self.FLAT.index("What the probe publishes, per session")
        # Ordering asserted before slicing. A slice whose end precedes its start
        # is the empty string, and every assertNotIn below then passes on nothing:
        # reproduced by moving the residual after its own closing marker, which
        # left all four subTests green with "This hazard is impossible in
        # practice." sitting in the section. This is the same trap the
        # `handler_methods` helper at the top of this file was written to avoid.
        self.assertLess(opens, closes, "the residual no longer precedes its closing marker")
        block = self.FLAT[opens:closes]
        self.assertGreater(len(block), 200, "the residual slice is too short to be the section")
        for overclaim in ("cannot happen", "is impossible", "cannot occur", "never happens"):
            with self.subTest(overclaim=overclaim):
                self.assertNotIn(overclaim, block.lower())

    def test_the_probe_bounds_the_walk_by_nothing_which_is_what_the_residual_says(self) -> None:
        # The residual rests on there being no ceiling in the code. If one ever
        # arrives, the section describes a system that no longer exists, and the
        # census and the trade in it stop being the reason for anything.
        source = (self.RUNTIME / "git_status.py").read_text(encoding="utf-8")
        self.assertNotIn("GIT_CEILING_DIRECTORIES", source)
        self.assertIn("passes nothing that bounds the walk", self.FLAT)

    def test_the_plan_document_died_with_its_promotion(self) -> None:
        # Leaving it in place states the contract in two places and lets them drift.
        self.assertFalse((self.ROOT / "docs" / "plans" / "git-probe-security-scope.md").exists())

    def test_the_documented_off_switch_is_the_flag_the_parser_accepts(self) -> None:
        self.assertIn("The off switch is `--no-git`.", self.FLAT)
        args = cli.build_parser().parse_args(["--no-git"])
        self.assertTrue(args.no_git)

    def test_the_contract_says_entries_rather_than_files(self) -> None:
        # `changed` counts porcelain entries; git collapses an untracked directory
        # into one. Rendering it as a file count is a wrong number under a true name.
        self.assertIn("counts porcelain entries rather than files", self.FLAT)


class EndStoreContractDocumentationTest(unittest.TestCase):
    """SECURITY.md's session-end section is a contract, so the code must still meet it.

    DRC-4547. The store is written by default under `~/.compass`, so what the
    document says it holds, where it lives and what switches it off are claims
    a reader acts on; each one here is bound to the code rather than grepped
    from our own prose.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    FLAT = re.sub(r"\s+", " ", SECURITY)
    SOURCE = (SERVER_PATH.parent / "compass_runtime" / "ends.py").read_text(encoding="utf-8")

    def test_the_section_exists_and_the_written_paths_list_names_the_file(self) -> None:
        self.assertIn("## Session ends", self.SECURITY)
        lifecycle = self.FLAT.split("## Process lifecycle: written paths", 1)[1].split("## ", 1)[0]
        self.assertIn("`compass-ends.json`", lifecycle)

    def test_the_store_lives_where_the_contract_says_it_does(self) -> None:
        config = make_config(state_home="/tmp/compass-contract")
        self.assertEqual(
            os.path.join("/tmp/compass-contract", "compass-ends.json"),
            ends.store_path(config),
        )
        self.assertIn("`~/.compass/compass-ends.json`", self.FLAT)

    def test_the_documented_mode_is_the_one_in_the_open_call(self) -> None:
        section = self.FLAT.split("## Session ends", 1)[1].split("## ", 1)[0]
        self.assertIn("opened `0600` with the mode in the `open` call", section)
        self.assertIn("os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)", self.SOURCE)

    def test_the_documented_off_switch_and_deletion_command_are_flags_the_parser_accepts(
        self,
    ) -> None:
        # decisions.md, DRC-4547: the store rides `--no-events`, and `--forget`
        # removes it. Both sentences are bound to the parser, as the history
        # section's are, so neither is a claim about a build that cannot do it.
        section = self.FLAT.split("## Session ends", 1)[1].split("## ", 1)[0]
        self.assertIn("`--no-events` leaves it unread and unwritten", section)
        self.assertIn("`--forget` deletes it", section)
        self.assertTrue(cli.build_parser().parse_args(["--no-events"]).no_events)
        self.assertTrue(cli.build_parser().parse_args(["--forget"]).forget)

    def test_the_section_states_the_guard_and_its_exposure(self) -> None:
        # decisions.md, DRC-4547: the resumed-while-down guard and what it costs
        # are written down here rather than implied solved.
        section = self.FLAT.split("## Session ends", 1)[1].split("## ", 1)[0]
        self.assertIn("transcript", section)
        self.assertIn("after its end", section)
        self.assertIn("reads as it does today", section)


class HistoryStoreContractDocumentationTest(unittest.TestCase):
    """SECURITY.md's history section is a contract, so the code must still meet it.

    The direct analogue of `GitProbeContractDocumentationTest` above, and owed by
    the merged contract: the section was written and reviewed on its own cycle
    before this code existed (DRC-4330, promoted here from
    `docs/plans/history-store-security-scope.md` and that file deleted in the
    same commit). Prose and code can only agree by accident unless something
    compares them, and this is the comparison.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    # Whitespace-collapsed, so a reflow that changes no words does not fail these.
    FLAT = re.sub(r"\s+", " ", SECURITY)

    def test_the_contract_section_survived_the_promotion(self) -> None:
        self.assertIn("## Local history (the session history store)", self.SECURITY)

    def test_the_plan_document_died_with_its_promotion(self) -> None:
        # Leaving it in place states the contract in two places and lets them drift.
        self.assertFalse(
            (self.ROOT / "docs" / "plans" / "history-store-security-scope.md").exists()
        )

    def test_the_documented_off_switch_is_the_flag_the_parser_accepts(self) -> None:
        # The prose half is bound to a parser call, so it is not a grep over our
        # own words: until `--no-history` parses, this assertion would be one.
        self.assertIn("The off switch is `--no-history`.", self.FLAT)
        args = cli.build_parser().parse_args(["--no-history"])
        self.assertTrue(args.no_history)

    def test_the_documented_deletion_command_is_the_flag_the_parser_accepts(self) -> None:
        self.assertIn("`--forget` deletes the store and exits.", self.FLAT)
        args = cli.build_parser().parse_args(["--forget"])
        self.assertTrue(args.forget)

    def test_the_store_lives_where_the_contract_says_it_does(self) -> None:
        # "under Compass's own directory, next to the dismissals file" — bound to
        # the path the code builds rather than asserted about our own prose.
        config = make_config(state_home="/tmp/compass-contract")
        self.assertEqual(
            os.path.join("/tmp/compass-contract", "compass-history.json"),
            history.store_path(config),
        )
        self.assertIn("next to the dismissals file", self.FLAT)

    def test_the_retention_default_the_contract_names_is_the_configured_one(self) -> None:
        # "Retention is 14 days by default" — a figure in prose that no test
        # bound would drift from the constant the day either changed.
        self.assertIn("Retention is 14 days by default", self.FLAT)
        self.assertEqual(14 * 24 * 60 * 60, make_config().history_retention_sec)

    def test_the_bounds_the_contract_calls_configurable_are_flags(self) -> None:
        # The captain's ND-1 ruling of 2026-09-03. The sentence was inherited
        # verbatim from the plan doc and `build_runtime_config` accepted neither
        # figure, so it was prose about a build that could not do it. Bound to
        # the parser the way the off switch above is, rather than grepped: until
        # both flags parse, this assertion would be one about our own words.
        self.assertIn(
            "Retention is 14 days by default, with a size cap, and both are configurable.",
            self.FLAT,
        )
        args = cli.build_parser().parse_args(["--history-days", "3", "--history-max-bytes", "4096"])
        self.assertEqual(3.0, args.history_days)
        self.assertEqual(4_096, args.history_max_bytes)

    def test_the_kept_list_names_the_project_label_the_store_actually_keeps(self) -> None:
        # D4, the captain's ruling of 2026-09-03: the label was in an explicit
        # gap in the contract and the store needs it as the grouping key, so the
        # promotion put it in the kept-list. Bound to the record, so the prose
        # and the field set cannot drift apart.
        self.assertIn("the derived two-segment project label", self.FLAT)
        self.assertIn("project", history.OBSERVATION_FIELDS)

    @staticmethod
    def bullets(source: str, header: str) -> list[str]:
        """The bullet lines of the list directly under `header`.

        Scoped rather than grepped over the whole document, and that is the
        whole point of it. Every carrier name and every ban clause also occurs
        in this section's surrounding prose, so an `assertIn` over SECURITY.md
        is satisfied whatever these two lists actually say: `last_prompt` sits
        in the rationale paragraph, `state_detail` and the instruction line
        under Published text, `title` throughout. Matching the file instead of
        the list is the difference between binding a list and mentioning it.

        A moved or reworded header raises rather than widening back to the file,
        because the quiet failure here is an assertion that still passes while
        measuring nothing.
        """
        _, found, rest = source.partition(header)
        if not found:
            raise AssertionError(f"the block header moved: {header!r}")
        return [line for line in rest.split("\n\n", 1)[0].splitlines() if line.startswith("- ")]

    def test_the_absolute_bans_took_no_exception_and_still_have_none(self) -> None:
        # DEC-13 relaxed one of the four never-items and deliberately left the
        # other three alone. The count is pinned with them: a clause moved out
        # of this block and into the allowlist paragraph would still satisfy a
        # substring match on the file, which is exactly the relocation this is
        # here to refuse.
        bans = self.bullets(self.SECURITY, "with no exception available:\n\n")
        self.assertEqual(3, len(bans))
        block = " ".join(bans)
        for clause in (
            "Tool input, in whole or in part",
            "Paths.",
            "File contents, of any file",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, block)

    def test_the_contract_names_every_field_the_allowlist_admits(self) -> None:
        # DEC-13, the captain's ruling of 2026-09-04: the outright prompt-text
        # ban became a per-field allowlist. This is the direction that stops the
        # store from keeping something the contract never named.
        self.assertIn("Prompt-derived text is avoided by default and allowlisted", self.FLAT)
        entries = " ".join(self.bullets(self.SECURITY, "The allowlist, one line per field:\n\n"))
        for field in history.PROMPT_TEXT_ALLOWLIST:
            with self.subTest(field=field):
                self.assertIn(field, entries)
                # And the contract cannot name a field the store does not write:
                # an allowlist entry with no record behind it reads as an
                # exposure that exists when it does not.
                self.assertIn(field, history.OBSERVATION_FIELDS)

    def test_no_prompt_carrier_reaches_the_store_without_an_allowlist_entry(self) -> None:
        # The direction with teeth, and the one that replaces the old literal
        # quote. The ban used to be a sentence; it is now a comparison, so a
        # field added to the record without an allowlist entry fails here rather
        # than passing because nobody re-read the prose.
        for carrier in history.PROMPT_DERIVED_CARRIERS:
            if carrier in history.PROMPT_TEXT_ALLOWLIST:
                continue
            with self.subTest(field=carrier):
                self.assertNotIn(carrier, history.OBSERVATION_FIELDS)

    def test_the_checks_a_claude_code_session_ran_are_a_named_carrier(self) -> None:
        # DEC-23 item 6 names the new fact type here, so the comparison above
        # keeps it out of the store rather than review alone.
        self.assertIn(reading.TOOL_REPORT_TYPE, history.PROMPT_DERIVED_CARRIERS)
        self.assertNotIn(reading.TOOL_REPORT_TYPE, history.OBSERVATION_FIELDS)

    def test_the_allowlist_holds_baseline_fields_and_the_first_prompt(self) -> None:
        # The two have to agree about the count as well as about the contents.
        # This replaces an emptiness assertion: "nothing yet" was the claim a
        # reader of this contract acted on until DEC-15b earned the first two
        # entries, and a list that grew without this line moving would leave
        # the contract claiming an exposure it no longer has.
        # One bullet per outcome line, as condition 1 requires (DEC-24 item 3).
        lines = tuple(f"annotation_line_{k}" for k in range(1, 7))
        self.assertEqual(("first_prompt", "annotation_goal", *lines), history.PROMPT_TEXT_ALLOWLIST)
        entries = self.bullets(self.SECURITY, "The allowlist, one line per field:\n\n")
        self.assertEqual(8, len(entries))

    def test_a_reserved_name_is_not_an_admitted_one(self) -> None:
        # The contract names five assessment fields it has NOT admitted, so a
        # later change does not re-argue the naming. A reserved name that
        # reached the record without its own allowlist line would be the
        # admission happening by accident.
        for name in (
            "assessment_at",
            "assessment_cutoff",
            "assessment_revision_read",
            "assessment_goal_result",
            "assessment_output_result",
        ):
            with self.subTest(field=name):
                self.assertIn(name, self.SECURITY)
                self.assertNotIn(name, history.OBSERVATION_FIELDS)
                self.assertNotIn(name, history.PROMPT_TEXT_ALLOWLIST)


class SemanticHistoryContractDocumentationTest(unittest.TestCase):
    """SECURITY.md's semantic-history claims are a contract, so something must read them.

    DRC-4533's ninth item asked whether SECURITY.md names the prototype's
    semantic-work-history store. It does, and every sentence of it was true when
    written — but nothing compared any of it to the code, so a moved store name
    or a widened bound would have left the document asserting something false
    with the whole suite green. That is the same shape as the drift
    `HistoryStoreContractDocumentationTest` above exists to catch, and this file
    is where the comparison belongs.

    The store is the one carrier of typed words that `--forget` does not reach,
    which is why the deletion sentence is asserted here rather than taken on
    trust.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    def test_the_document_names_the_store_the_code_actually_writes(self) -> None:
        self.assertIn(semantic_history.STORE_NAME, self.SECURITY)
        self.assertIn(f"`~/.compass/{semantic_history.STORE_NAME}`", self.SECURITY)

    def test_the_documented_summary_bound_is_the_bound_the_code_applies(self) -> None:
        # Prose and a literal can only agree by accident. The constant exists so
        # that widening the bound is a two-file change a reviewer sees, rather
        # than a one-character edit that leaves the sentence quietly wrong.
        self.assertEqual(240, semantic_history.SUMMARY_CAP_CHARS)
        self.assertIn(
            f"`summary` is bounded at {semantic_history.SUMMARY_CAP_CHARS} characters",
            _flat_section(self.SECURITY, "## Operator-cockpit prototype"),
        )

    def test_the_documented_detail_bound_is_the_bound_the_code_applies(self) -> None:
        self.assertEqual(4096, semantic_history.RESULT_DETAIL_CAP_CHARS)
        self.assertIn(
            f"holds up to {semantic_history.RESULT_DETAIL_CAP_CHARS} characters",
            _flat_section(self.SECURITY, "## Operator-cockpit prototype"),
        )

    def test_forget_still_does_not_reach_this_store(self) -> None:
        # The document says so twice, and it is the sentence most likely to
        # become false: admitting this store to `--forget` is a natural-looking
        # improvement that would silently contradict both paragraphs.
        section = _flat_section(self.SECURITY, "## Operator-cockpit prototype")
        self.assertIn(
            "`--forget` deletes the session-history, session-end and summary stores, removes "
            "annotation discard records and copied-correction digests, and withdraws model "
            "permission; it does not reach this semantic-history store.",
            section,
        )
        # Every `forget` function the command reaches (DRC-4547 added the
        # second, DRC-4565 the third), so admitting this store through any one
        # of them turns this red.
        for module in ("history.py", "ends.py", "annotations.py", "summary_store.py"):
            source = (SERVER_PATH.parent / "compass_runtime" / module).read_text(encoding="utf-8")
            forget = source[source.index("def forget(") :]
            forget = forget.split("\ndef ", 1)[0]
            self.assertNotIn("semantic", forget.lower(), module)

    def test_the_store_is_written_owner_only_through_a_rename(self) -> None:
        section = _flat_section(self.SECURITY, "## Published text (credential redaction)")
        self.assertIn("written owner-only through a temp file and a rename", section)
        source = (SERVER_PATH.parent / "compass_runtime" / "semantic_history.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("0o600", source)
        self.assertIn("os.replace", source)


class LightHarnessUsageContractDocumentationTest(unittest.TestCase):
    """DEC-14's section is a contract for a pathway nothing uses yet.

    The other contract sections here bind prose to shipped code. This one has no
    shipped code to bind to, which is exactly the state that produced the ND-1
    defect: a section inherited from a plan, describing bounds the build could
    not honour, passing because nothing compared the two. So what is bound here
    is the emptiness. The section must keep saying the pathway is unused, and the
    parser must keep having no flag to switch it off, and the day either changes
    the other has to change with it.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    FLAT = re.sub(r"\s+", " ", SECURITY)
    # This section alone, so a clause a sibling section also carries
    # cannot satisfy an assertion made here.
    SECTION = _flat_section(
        SECURITY, "## Light harness usage (asking a harness a bounded question)"
    )

    def test_the_section_exists_under_a_heading_other_documents_can_anchor(self) -> None:
        self.assertIn("## Light harness usage (asking a harness a bounded question)", self.SECURITY)

    def test_the_observer_pathway_defaults_on_and_has_both_rollback_spellings(self) -> None:
        self.assertIn("The observer model is the first implementation", self.SECTION)
        self.assertIn("on by default", self.SECTION)
        self.assertIn("16,384 bytes", self.SECTION)
        for flag in ("--no-observer-model", "--no-harness-usage"):
            args = cli.build_parser().parse_args(["--observer-model", flag])
            config, _state = cli.build_runtime(args, started=0)
            self.assertFalse(config.observer_model_enabled)

    def test_the_invariant_names_the_second_outbound_kind_apart(self) -> None:
        # Invariant 1 used to call the quota poll "the single outbound
        # exception". A harness invocation carries session-derived text where the
        # poll carries none, so the amendment names them apart rather than
        # widening the one exception to cover both. A reader who only skims the
        # invariants has to see that distinction there.
        self.assertNotIn("The quota poll is the single outbound exception", self.FLAT)
        self.assertIn("no session content whatever", self.FLAT)
        self.assertIn(
            "the one pathway by which the operator's own words may leave this machine", self.FLAT
        )

    def test_the_consent_is_announced_where_the_quota_fetch_is_not(self) -> None:
        # The asymmetry is the point: reading a number is not spending capacity,
        # and the section has to say which one it is. DEC-28 (owner, 2026-10-19)
        # made a reader-started call opt-out with a notice; the opt-in bound it
        # replaces is named only as superseded.
        self.assertIn("Opt-out, with a notice, for a call a reader's action starts", self.FLAT)
        self.assertIn('replaces the former "Opt-in, and off until answered" bound', self.FLAT)
        self.assertNotIn("Until then", self.SECTION)
        self.assertNotIn("consent change ships", self.FLAT)
        self.assertIn("spends their capacity rather than reading a number", self.FLAT)
        self.assertIn("unasked drift checks", self.SECTION)

    def test_the_pathway_adds_no_credential_and_no_endpoint(self) -> None:
        # The quota section owns the endpoint list and the token rules, and this
        # pathway must not quietly extend either. It invokes the operator's own
        # signed-in harness instead.
        self.assertIn("never a Compass credential", self.FLAT)
        self.assertIn("adds no endpoint to the list in Usage quota reads", self.FLAT)


class PerProviderAllowDocumentationTest(unittest.TestCase):
    """The owner's 2026-10-02 ruling: an Allow is per provider, not per harness.

    The 2026-10-02 amendment's item 3 read as though a Pi or Codex session
    falling back to Claude Code asked a second time. It does not: an Allow
    given for a provider covers every session routed to it, which
    `ReadingRouteTest` binds over a socket. These keep the prose saying so.
    """

    ROOT = SERVER_PATH.parents[3]
    DESIGN = (ROOT / "docs/design-reading-a-session.md").read_text(encoding="utf-8")
    AMENDMENT = re.sub(
        r"\s+",
        " ",
        DESIGN.split("### Amended 2026-10-02: Claude Code is accepted", 1)[1].split("\n### ", 1)[0],
    )
    # That subsection alone, so a clause another one carries cannot satisfy it.
    SECURITY = re.sub(
        r"\s+",
        " ",
        (ROOT / "SECURITY.md")
        .read_text(encoding="utf-8")
        .split("### Reader-requested permission and rolling budget", 1)[1]
        .split("\n### ", 1)[0],
    )

    def test_the_amendment_says_an_allow_covers_every_session_routed_to_its_provider(
        self,
    ) -> None:
        self.assertIn("covers every session routed to that provider", self.AMENDMENT)
        self.assertIn('"What is sent to', self.AMENDMENT)
        self.assertIn("owner, 2026-10-02", self.AMENDMENT)
        # The words that implied a second consent step for a fallback session.
        self.assertNotIn('each provider keeps its own "Allow and analyze"', self.AMENDMENT)

    def test_security_says_the_same_of_its_per_provider_answer(self) -> None:
        self.assertIn("covers every session routed to that provider", self.SECURITY)


class BoundAllowDocumentationTest(unittest.TestCase):
    """Consent F2 (ui5): the binding detects a named destination moving, and
    nothing else. An Allow given while the destination was unnamed keeps
    covering every endpoint `destination` cannot name, which is every route on
    Windows and every Codex base URL. The prose once said any endpoint move
    asks again; these keep it saying where a change is and is not detected.
    """

    ROOT = SERVER_PATH.parents[3]
    AMENDMENT = re.sub(
        r"\s+",
        " ",
        (ROOT / "docs/design-reading-a-session.md")
        .read_text(encoding="utf-8")
        .split("### Amended 2026-10-02 (owner): the Allow is bound to where the words go", 1)[1]
        .split("\n### ", 1)[0],
    )
    SECURITY = PerProviderAllowDocumentationTest.SECURITY
    # The overclaims, as each document once worded them.
    OVERCLAIMS = (
        "any other setting that moves the endpoint therefore asks again",
        "or `OPENAI_BASE_URL` sent the goal",
    )

    def test_each_says_where_a_change_is_not_detected(self) -> None:
        for name, text in (("amendment", self.AMENDMENT), ("SECURITY", self.SECURITY)):
            with self.subTest(document=name):
                self.assertIn("keeps covering every endpoint it cannot name", text)
                self.assertIn("every destination on Windows", text)
                self.assertIn("Codex base URL", text)
                for overclaim in self.OVERCLAIMS:
                    self.assertNotIn(overclaim, text)


class OffMachineNudgeContractDocumentationTest(unittest.TestCase):
    """DEC-4's section is a contract for a pathway nothing uses yet.

    The sibling of `LightHarnessUsageContractDocumentationTest` below the same
    reasoning: there is no shipped code to bind prose to, so what is bound is the
    emptiness, plus the two claims about the runtime the section makes in passing.
    Those two are the ones worth a test, because both are claims that something
    does *not* exist, and DEC-4's own wording offered a third payload count that
    nothing measures.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    FLAT = re.sub(r"\s+", " ", SECURITY)
    # This section alone, so a clause a sibling section also carries
    # cannot satisfy an assertion made here.
    SECTION = _flat_section(SECURITY, "## Off-machine nudges")

    def test_the_section_exists_under_a_heading_other_documents_can_anchor(self) -> None:
        self.assertIn(
            "## Off-machine nudges (reaching the operator away from the desk)", self.SECURITY
        )

    def test_the_pathway_is_documented_and_the_parser_agrees(self) -> None:
        self.assertIn("The reach endpoint provides this capability", self.SECTION)
        self.assertIn("The feature ships `--no-reach` with it", self.SECTION)
        args = cli.build_parser().parse_args(["--no-reach"])
        self.assertTrue(args.no_reach)

    def test_the_payload_omits_the_count_no_threshold_backs(self) -> None:
        # The payload carries two counts and not DEC-4's three because no
        # threshold decides when quiet becomes notable. The ELAPSED reading is
        # not what is missing, and an earlier draft of the section said it was:
        # `last_activity` is published on every row and the board renders an idle
        # duration from it. So this asserts the true premise, that the only
        # `idle` field in `config.py` is the overlay's dwell, a render delay
        # rather than a nudge threshold. A genuine threshold arriving fails this
        # and sends whoever added it back to the section.
        fields = {
            name
            for name in re.findall(
                r"^    ([a-z_]+): ",
                (SERVER_PATH.parent / "compass_runtime" / "config.py").read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            if "idle" in name
        }
        self.assertEqual({"overlay_idle_dwell_sec"}, fields)
        self.assertIn("what is missing is not the elapsed reading but the threshold", self.SECTION)
        # And the retracted premise must not come back.
        self.assertNotIn("with nothing elapsed behind it", self.FLAT)
        # `last_activity` really is published, which is what makes the above true
        # rather than a second guess. Derived from the template, not a literal.
        template = (SERVER_PATH.parent / "compass_runtime" / "sessions.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"last_activity"', template)

    def test_the_url_is_held_to_the_credential_rules_the_quota_section_sets(self) -> None:
        self.assertIn("The URL is a credential", self.FLAT)
        self.assertIn("never printed by `--diagnose`", self.SECTION)


class IrreversibleActionsContractDocumentationTest(unittest.TestCase):
    """C6's section is a contract for a pathway nothing uses yet, plus an allowlist.

    The allowlist half is the load-bearing one and it is why this class is not
    just three emptiness assertions. The issue that filed the section wanted it to
    say the runtime never parses a tool call's input; that is false at HEAD in
    three expressions, and shipping it would have made the security contract
    narrower than the code. So the section names the reads instead, and this binds
    the naming to the reads: a fourth input read fails here until whoever adds it
    amends the section.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    FLAT = re.sub(r"\s+", " ", SECURITY)
    # This section alone, so a clause a sibling section also carries
    # cannot satisfy an assertion made here.
    SECTION = _flat_section(
        SECURITY, "## Irreversible actions (hook-side destructive-shape matching)"
    )
    RUNTIME = SERVER_PATH.parent / "compass_runtime"

    def test_the_section_exists_under_a_heading_other_documents_can_anchor(self) -> None:
        self.assertIn(
            "## Irreversible actions (hook-side destructive-shape matching)", self.SECURITY
        )

    def test_the_shipped_report_and_its_off_switch_agree(self) -> None:
        args = cli.build_parser().parse_args(["--no-irreversible"])
        config, _ = cli.build_runtime(args, started=1_700_000_000.0)
        self.assertFalse(config.irreversible_enabled)
        self.assertIn("nominal 5 ms", self.FLAT)
        self.assertIn("newest 1,000 reports globally", self.FLAT)
        self.assertIn("six fields", self.SECTION)

    def test_the_allowlist_names_every_input_read_the_package_makes(self) -> None:
        # Counted rather than listed, because the failure this guards against is
        # a *new* read nobody wrote into the section. Both spellings are here
        # because Codex writes its plan under `arguments` in one shape and
        # `input` in the other, and the section names both.
        # Subscripts too: a `block["input"]` read is a read, and the narrower
        # pattern once let two of them through uncounted (review, 2026-09-24).
        pattern = r'\.get\("(?:input|arguments)"\)|\["(?:input|arguments)"\]'
        found = {
            path.name: len(re.findall(pattern, text))
            for path in sorted(self.RUNTIME.rglob("*.py"))
            if (text := path.read_text(encoding="utf-8")) and re.search(pattern, text)
        }
        self.assertEqual(
            {"claude_data.py": 1, "codex.py": 1, "project_context.py": 4, "transcripts.py": 2},
            found,
        )
        self.assertIn("eight expressions in `compass_runtime` reach an input payload", self.FLAT)
        for named in (
            "`claude_data.input_summary`",
            "`transcripts.codex_plan`",
            "`collectors.codex._child_assignment`",
            "`project_context._tool_call_events`",
            "`project_context._tool_support`",
            "`project_context._pi_bash_check_runs`",
            "`project_context._pi_changes`",
            "`project_context.codex_dispatch_events`",
            "`project_context.claude_tool_reports`",
        ):
            with self.subTest(read=named):
                self.assertIn(named, self.FLAT)

    def test_the_pull_request_and_skill_reads_are_named_and_counted(self) -> None:
        # Neither read matches the `input` / `arguments` pattern above: the skill's name is read from
        # an input the check scan already holds, and a pull request from a result's
        # `gitOperation`, through `toolUseResult`. They are counted here so a second place that reads either fails until
        # SECURITY.md names it (owner, 2026-10-23).
        pattern = r'"gitOperation"|\.get\("skill"\)|\.get\("toolUseResult"\)'
        found = {
            path.name: len(re.findall(pattern, text))
            for path in sorted(self.RUNTIME.rglob("*.py"))
            if (text := path.read_text(encoding="utf-8")) and re.search(pattern, text)
        }
        # `observer.py` reads the question tool's own result and `project_context.py` three others
        # besides the pull request read; each is another place a result's structured field is read.
        # The sixth of `project_context.py`'s is the command listing's exemption for a call that
        # carries the record.
        # `ci_read.py` reads a `pr-link` row's fields, `toolUseResult` and `gitOperation.push` for a
        # pushed branch name, and SECURITY.md's Pull request CI reads section says so.
        self.assertEqual({"ci_read.py": 3, "observer.py": 1, "project_context.py": 6}, found)
        self.assertIn("`toolUseResult.gitOperation.push` (`branch`)", self.FLAT)
        for phrase in (
            "the `skill` name of a `Skill` call",
            "`toolUseResult.gitOperation.pr` (`number`, `url`, `action`)",
            "never the command or its output",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.SECTION)

    def test_the_claude_check_read_is_bounded_to_the_caps_the_section_states(self) -> None:
        # DEC-23 item 5's bounds, read out of the module rather than restated.
        for phrase in (
            f"clipped to {project_context.TOOL_REPORT_LINE_CHARS} characters",
            f"the last {project_context.TOOL_REPORT_TAIL_CHARS} characters of output",
            f"At most {project_context.TOOL_REPORT_MAX_ENTRIES} entries are listed",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.FLAT)

    def test_the_named_read_is_bounded_to_the_cap_the_section_states(self) -> None:
        config = make_config()
        self.assertIn(
            f"bounded at `config.input_summary_cap_chars`, {config.input_summary_cap_chars}"
            " characters",
            self.FLAT,
        )

    def test_the_codex_plan_read_is_bounded_to_the_caps_the_section_states(self) -> None:
        # The section promises that each named read "reduces what it read to a
        # bounded summary at parse time". The Claude bullet honoured that with a
        # number the test above reads out of the live config; the Codex bullet
        # stated no bound at all, and neither constant behind it appeared in any
        # Markdown file in the repository, so raising either would have widened
        # what this section implicitly promises with nothing in CI noticing.
        #
        # Read out of `transcripts` rather than typed here, and asserted against
        # this section alone: 160 is also `input_summary_cap_chars`, so an
        # assertion over the whole document would pass on the Claude bullet's
        # copy of the same number.
        self.assertIn(
            f"bounded at `transcripts.CODEX_PLAN_MAX_STEPS` steps,"
            f" {runtime_transcripts.CODEX_PLAN_MAX_STEPS},",
            self.SECTION,
        )
        self.assertIn(
            f"bounded at `transcripts.CODEX_PLAN_STEP_CAP_CHARS`,"
            f" {runtime_transcripts.CODEX_PLAN_STEP_CAP_CHARS} characters",
            self.SECTION,
        )

    def test_the_promise_map_states_the_step_bound_it_now_quotes(self) -> None:
        # `docs/promise-map.md` said "a plan title and a question are the two
        # that reach the board", which is true of Claude and undercounts Codex:
        # the whole plan reaches the board, every step and status, as a task
        # list. Saying so puts a second copy of the step bound in a document
        # AGENTS.md makes canonical for the user-facing promise, so it is bound
        # here rather than left to drift against the first.
        promise_map = re.sub(
            r"\s+", " ", (self.ROOT / "docs/promise-map.md").read_text(encoding="utf-8")
        )
        self.assertIn(
            f"up to {runtime_transcripts.CODEX_PLAN_MAX_STEPS} plan steps"
            " with their statuses from Codex",
            promise_map,
        )

    def test_the_two_input_tools_the_section_names_are_the_pair_the_code_gates_on(self) -> None:
        named = {
            match
            for match in re.findall(r"`([A-Za-z]+)` carries", self.FLAT)
            if match in claude_data.INPUT_TOOLS
        }
        self.assertEqual(set(claude_data.INPUT_TOOLS), named)

    def test_the_report_exception_keeps_lifecycle_privacy_explicit(self) -> None:
        self.assertIn("Ordinary lifecycle envelopes still drop the tool name", self.FLAT)
        self.assertIn("The prompt, the tool input and the tool output stay dropped", self.FLAT)
        self.assertIn("exactly six fields", self.FLAT)

    def test_the_posted_fields_are_the_shape_dec_5_allowed(self) -> None:
        # DEC-5 allowed an identifier, the tool name and a timestamp. An earlier
        # draft of this section dropped the tool name to protect the envelope
        # invariant, which narrowed the ruling instead of amending the invariant,
        # and a security contract narrower than its own decision is the defect
        # #289 spent a PR undoing in the other direction.
        self.assertIn(
            "an identifier for a shape from the named set, the tool name, and a timestamp",
            self.FLAT,
        )
        self.assertIn("which is the shape DEC-5 allowed", self.FLAT)

    def test_the_reason_the_tool_name_may_come_back_is_a_field_that_is_published(self) -> None:
        # The section's justification is that the snapshot already serves a failing
        # tool's name, so the envelope was dropping a value the board publishes.
        # Bound to the producer rather than to the page: `loop_signal` is where the
        # field is put into the snapshot. If the signal stops carrying it the justification is
        # gone and this says so.
        source = (self.RUNTIME / "turns.py").read_text(encoding="utf-8")
        self.assertIn('"tool": scan.get("err_tool")', source)
        self.assertIn("a failing tool's name reaches the page through the loop signal", self.FLAT)

    def test_the_gating_hook_rule_matches_what_the_antigravity_script_measured(self) -> None:
        # An earlier draft said the hooks stay incapable of blocking work because
        # `agy_hook.py` prints `{}`. That is backwards: `agy_hook.py`'s own
        # measured header records that an empty object at `PreToolUse` is a DENY,
        # so the safety property is the refusal to register there. A security
        # section that got this the wrong way round would read as reassurance
        # while describing the failure mode.
        source = (SERVER_PATH.parent / "agy_hook.py").read_text(encoding="utf-8")
        self.assertIn("an EMPTY object is a DENY", source)
        self.assertIn("Never register `PreToolUse` here", source)
        self.assertIn("an empty object there is a deny rather than an abstention", self.FLAT)
        self.assertIn("the hook is never registered there rather than", self.FLAT)

    def test_the_history_store_question_is_answered_rather_than_deferred(self) -> None:
        self.assertIn(
            "A field the live board does not publish is not a field history may keep", self.FLAT
        )


class HandOffRequestContractDocumentationTest(unittest.TestCase):
    """DEC-2's section is a contract for a verb nothing sends yet.

    Three of its clauses are checkable now and are the ones checked: the parser
    has no off switch, the read location it needs is absent from the documented
    store roots, and the facts it took from a harness's documentation are labelled
    as documented. That last one has a rule behind it rather than a preference:
    desk research here got the field, the unit or the rendering wrong five times
    out of five, so an unmeasured figure presented as measured is the defect.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    FLAT = re.sub(r"\s+", " ", SECURITY)
    # This section alone, so a clause a sibling section also carries
    # cannot satisfy an assertion made here.
    SECTION = _flat_section(SECURITY, "## Hand-off requests")

    def test_the_section_exists_under_a_heading_other_documents_can_anchor(self) -> None:
        self.assertIn("## Hand-off requests (one verb into a session)", self.SECURITY)

    def test_the_verb_is_documented_as_unsent_and_the_parser_agrees(self) -> None:
        self.assertIn("No shipped feature sends anything into a session", self.FLAT)
        self.assertIn("That flag does not exist yet", self.SECTION)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--no-handoff"])

    def test_the_two_unshipped_switches_are_the_only_no_flags_missing(self) -> None:
        # One oracle for all three sections. The parser's `--no-*` set is read off
        # its source the way `EventEnvelopeEnumerationTest` reads `config.py`, so
        # a fourth documented-but-unshipped flag cannot hide behind a passing
        # `SystemExit` assertion, and shipping one of these three fails the
        # section that calls it unshipped.
        shipped = set(
            re.findall(
                r'"(--no-[a-z-]+)"',
                (SERVER_PATH.parent / "compass_runtime" / "cli.py").read_text(encoding="utf-8"),
            )
        )
        self.assertEqual(
            {
                "--no-spacedock",
                "--no-usage",
                "--no-observer-model",
                "--no-harness-usage",
                "--no-git",
                "--no-ci-read",
                "--no-focus",
                "--no-history",
                "--no-dismiss",
                "--no-annotations",
                "--no-ask",
                "--no-events",
                "--no-irreversible",
                "--no-tripwires",
                "--no-reach",
                "--no-quiet-hours",
            },
            shipped,
        )
        for documented in ("--no-handoff",):
            with self.subTest(flag=documented):
                self.assertNotIn(documented, shipped)
                self.assertIn(f"`{documented}`", self.FLAT)

    def test_the_socket_read_is_absent_from_the_documented_store_roots(self) -> None:
        # Scope makes a read outside the documented store paths a security bug
        # "however the path was derived", so the section says this read is one
        # until `config.py` names its location. The three roots it names are
        # asserted against the resolver: a fourth Claude root arriving makes the
        # section's sentence stale, and this is what says so.
        roots = {
            key
            for key in runtime_config.resolve_store_roots(
                platform_name="darwin", environ={}, home="/HOME"
            )
            if key.startswith("claude")
        }
        self.assertEqual({"claude.projects", "claude.tasks", "claude.teams"}, roots)
        for named in sorted(roots):
            with self.subTest(root=named):
                self.assertIn(f"`{named}`", self.FLAT)
        self.assertIn("and no fourth", self.FLAT)

    def test_every_fact_taken_from_a_harness_document_is_labelled_as_such(self) -> None:
        # The four items DEC-2's groundwork took from Claude Code's documentation
        # rather than from a measurement. Each has to sit inside the labelled
        # block, so the label cannot be dropped while the facts stay.
        block = self.FLAT[
            self.FLAT.index("Four facts are documented, not measured") : self.FLAT.index(
                "The build that lands E7 measures all four first"
            )
        ]
        for fact in ("`crossSessionInbound`", "`dialogExpiry`", "counts toward usage", "cc-socks"):
            with self.subTest(fact=fact):
                self.assertIn(fact, block)

    def test_the_token_rule_covers_the_path_and_not_only_the_value(self) -> None:
        # The token is documented as part of the socket's filename, so a redaction
        # that covers the value and prints the path leaks it. The section has to
        # say both halves.
        self.assertIn("Neither is any path that contains it", self.FLAT)

    def test_the_ask_lane_direction_claims_are_true_after_this_section_lands(self) -> None:
        # The two sentences this section falsifies if they stand unamended. Both
        # were absolute and are now scoped to what ships, which is the amendment
        # #289 spent a whole PR establishing as the right direction.
        self.assertNotIn("The direction is the invariant. Compass never reaches into", self.FLAT)
        self.assertIn("The direction is the invariant for everything shipped", self.FLAT)
        self.assertIn("Compass reaches into no session today", self.FLAT)
        self.assertIn("One other direction is written down and unbuilt", self.FLAT)
        # The one clause DEC-2 confirmed rather than lifted stays exactly as it was.
        self.assertIn("the tool cannot answer a native permission prompt", self.FLAT)

    def test_the_scope_invariant_counts_the_outbound_kinds_it_now_enumerates(self) -> None:
        # Nothing pinned this count before, and a third documented pathway
        # falsifies both the old number and the closing clause (DRC-4434).
        self.assertNotIn("Two kinds of outbound request are in scope", self.FLAT)
        self.assertIn(
            "Four kinds of outbound request are implemented",
            self.FLAT,
        )
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("for all four", re.sub(r"\s+", " ", readme))


class FocusCommandContractDocumentationTest(unittest.TestCase):
    """SECURITY.md's focus section is a contract, so the code must still meet it.

    The direct analogue of `GitProbeContractDocumentationTest` above: the section
    was written and reviewed on its own cycle before this code existed (DRC-4383,
    promoted here from `docs/plans/session-focus-security-scope.md` and that file
    deleted, with the deep dive beside it, in the same commit). Prose and code can
    only agree by accident unless something compares them.
    """

    ROOT = SERVER_PATH.parents[3]
    SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    # Whitespace-collapsed, so a reflow that changes no words does not fail these.
    FLAT = re.sub(r"\s+", " ", SECURITY)

    def test_the_contract_section_survived_the_promotion(self) -> None:
        self.assertIn("## Reaching a session's terminal (the focus command)", self.SECURITY)
        # The two intro amendments that had to ride with it. Without the first,
        # the section sits under a Scope clause about running a program inside a
        # repository, which the focus command does not do — the technicality
        # DRC-4274 warned about, of a promoted section landing under a clause
        # that does not cover it.
        self.assertIn(
            "running a program to reach a session's terminal other than the focus command "
            "described in Reaching a session's terminal (the focus command),",
            self.FLAT,
        )
        self.assertIn(
            "The focus command writes nothing anywhere, reads nothing back, and touches no "
            "harness store;",
            self.FLAT,
        )

    def test_the_widening_stayed_scoped_to_its_own_clause(self) -> None:
        # Written generally, the sentence would make documented security bugs of
        # three paths Compass already ships. The whitelist has to stay a
        # whitelist of scoped clauses.
        self.assertIn(
            "a whitelist of two scoped clauses and not a general permission to execute",
            self.FLAT,
        )
        for shipped in (
            "compass_runtime/notifications.py",
            "compass_runtime/lifecycle.py",
            "compass_runtime/quota.py",
        ):
            source = (SERVER_PATH.parent / shipped).read_text(encoding="utf-8")
            with self.subTest(module=shipped):
                self.assertIn("subprocess", source)

    def test_the_plan_documents_died_with_their_promotion(self) -> None:
        # Leaving either in place states the contract in two places and lets them
        # drift.
        plans = self.ROOT / "docs" / "plans"
        self.assertFalse((plans / "session-focus-security-scope.md").exists())
        self.assertFalse((plans / "2026-09-05-drc-4383-deep-dive.md").exists())

    def test_the_documented_off_switch_is_the_flag_the_parser_accepts(self) -> None:
        # The prose half is bound to a parser call, so it is not a grep over our
        # own words: until `--no-focus` parses, this assertion would be one.
        self.assertIn("`--no-focus`, and one other flag turns it off", self.FLAT)
        args = cli.build_parser().parse_args(["--no-focus"])
        self.assertTrue(args.no_focus)

    def test_the_second_off_switch_the_contract_names_is_also_a_flag(self) -> None:
        self.assertIn(
            "The capability comes from the observation coordinator, which does not exist under "
            "`--no-events`, so that flag disables focus too.",
            self.FLAT,
        )
        self.assertTrue(cli.build_parser().parse_args(["--no-events"]).no_events)

    def test_the_documented_grammars_are_the_patterns_the_code_applies(self) -> None:
        # The contract's table, bound to the compiled patterns rather than
        # restated. The table was itself corrected after being executed against
        # its own claimed refusals, so a prose promise the pattern does not keep
        # is the exact failure this guards.
        for documented, pattern in (
            ("^%[0-9]{1,9}$", focus.TMUX_PANE_RE),
            ("^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$", focus.TMUX_SOCKET_RE),
            ("^/dev/[A-Za-z0-9][A-Za-z0-9._-]{0,119}$", focus.CLIENT_TTY_RE),
        ):
            with self.subTest(grammar=documented):
                self.assertIn(f"`{documented}`", self.SECURITY)
                self.assertEqual(documented, pattern.pattern)

    def test_the_refused_examples_in_the_table_are_refused(self) -> None:
        # Every value the table names as refused, run against the pattern the
        # same row names. The document's own examples, not examples chosen here.
        for pattern, refused in (
            (focus.TMUX_PANE_RE, ("%3; rm -rf", "-%3", "%", "%3 %4")),
            (focus.TMUX_SOCKET_RE, ("-L", "../x", "/tmp/s", ".hidden", "")),
            (
                focus.CLIENT_TTY_RE,
                (
                    "--dangerously-skip-permissions",
                    "; rm -rf ~",
                    "../../etc/passwd",
                    "/dev/..",
                ),
            ),
        ):
            for value in refused:
                with self.subTest(value=value):
                    self.assertIn(value, self.SECURITY)
                    self.assertIsNone(pattern.match(value))

    def test_no_apple_event_case_is_named_while_its_arm_is_unmeasured(self) -> None:
        # The contract permits one only once that arm has been run, and A2 is
        # inconclusive. The bound is on the code rather than on the prose,
        # because the prose is what grants the permission.
        self.assertIn("**No Apple Event case may be named until that arm has been run**", self.FLAT)
        runtime = SERVER_PATH.parent / "compass_runtime"
        pattern = re.compile(r"""["']osascript["']""")
        offenders = sorted(
            path.name
            for path in runtime.rglob("*.py")
            if pattern.search(path.read_text(encoding="utf-8"))
        )
        # Quoted, so the one prose mention in `http_api.py` is not counted as a
        # call site. `notifications.py` is the only one, and it runs
        # `display notification` — a StandardAdditions command with no
        # `tell application` block, so it is never checked against the Automation
        # privacy permission. That is an escaping precedent and not a permission
        # one, which is why it is named here rather than counted as a focus case:
        # a macOS focus case would be the FIRST Automation-checked call in this
        # codebase, not the second.
        self.assertEqual(["notifications.py"], offenders)

    def test_the_documented_grammar_table_carries_the_server_pid(self) -> None:
        # A pane id is an ordinal on ONE server, so the field that anchors a
        # target to the server that issued it is part of the target's shape and
        # belongs in the table with the other three.
        self.assertIn("`^[0-9]{1,10}$`", self.SECURITY)
        self.assertEqual("^[0-9]{1,10}$", focus.TMUX_SERVER_RE.pattern)
        self.assertIn("A pane id is an ordinal on one tmux server, not", self.FLAT)

    def test_the_documented_command_is_the_argv_the_module_builds(self) -> None:
        # The section prints the three commands verbatim, so the format strings
        # it prints have to be the ones the templates carry — a document naming
        # `#{session_name}` alone would be describing a lookup that cannot
        # decline a stale server.
        self.assertIn("display-message -p -t <pane> '#{pid} #{session_name}'", self.SECURITY)
        self.assertIn("#{pid} #{session_name}", focus.SESSION_NAME_ARGV)
        self.assertIn("#{client_tty}", focus.LIST_CLIENTS_ARGV)

    def test_the_clients_are_counted_by_lines_as_the_contract_now_says(self) -> None:
        # The document says the count is over lines, and the module is what has
        # to mean it: a control-mode client reports an empty `#{client_tty}`, and
        # a reader dropping that line counts two attached clients as one.
        self.assertIn("It is counted by lines, not by values.", self.FLAT)
        source = (SERVER_PATH.parent / "compass_runtime" / "focus.py").read_text(encoding="utf-8")
        self.assertNotIn("if line.strip()]", source)

    def test_the_unmeasured_platforms_record_no_target(self) -> None:
        self.assertIn(
            "Not a named case means no target is recorded there, and that is enforced where the "
            "target is stored",
            self.FLAT,
        )
        source = (SERVER_PATH.parent / "compass_runtime" / "observation.py").read_text(
            encoding="utf-8"
        )
        marker = source.index("def _mark_focus")
        self.assertIn('self.config.platform_name != "darwin"', source[marker : marker + 3_000])

    def test_the_documented_check_order_is_the_one_the_route_implements(self) -> None:
        # The promoted section said the focus route used `/api/events/<harness>`'s
        # order and 404d an unsupported case before the capability. The route
        # deliberately inverts that first step, and its own comment calls the
        # inversion the whole security property: a harness name is public and a
        # session id is not, so a lookup-first route would be an oracle for which
        # sessions exist. The document is what was wrong, so the document moved.
        self.assertIn(
            "The route's check order is deliberately **not** the one "
            "`POST /api/events/<harness>` uses",
            self.FLAT,
        )
        self.assertIn("**A session id is not.**", self.FLAT)
        self.assertIn("The focus route emits no 404 on any path", self.FLAT)
        source = (SERVER_PATH.parent / "compass_runtime" / "http_api.py").read_text(
            encoding="utf-8"
        )
        handler = source[source.index("def _focus(self)") : source.index("def do_POST(self)")]
        # Every status the route can answer with, and 404 is not among them.
        self.assertEqual(
            ["503", "403", "413", "429"],
            sorted(set(re.findall(r"_reject\((\d{3})\)", handler)), key=handler.index),
        )
        self.assertLess(handler.index("focus_authorized"), handler.index("claim_focus"))
        self.assertLess(handler.index("claim_focus"), handler.index("focus_target"))

    def test_the_capability_claim_stops_where_the_scope_section_stops(self) -> None:
        # The first draft offered the capability as the answer to another local
        # account, which `GET /` hands the token to. Scope already said so
        # correctly; the focus section now says the same rather than the reverse,
        # which is also what makes Scope's back-reference to it true.
        self.assertIn("against that account this route stands where `/api/dismiss` does", self.FLAT)
        self.assertIn(
            "What the capability actually separates is a page from a document navigation and "
            "from a local process that never fetched the board",
            self.FLAT,
        )

    def test_the_shared_session_window_is_named_and_the_clause_measures_the_lookup(self) -> None:
        # The rule is decided on `list-clients` and enforced by `switch-client`
        # about six milliseconds later, so the absolute clause was unsatisfiable
        # by any implementation this contract permits.
        self.assertIn(
            "The rule is decided on one command and enforced by the next, and the gap between "
            "them is named rather than narrowed.",
            self.FLAT,
        )
        self.assertIn("a raise on a lookup that reported more than one attached client", self.FLAT)
        self.assertNotIn("a raise on a multiplexer session with more than one attached", self.FLAT)

    def test_the_scope_paragraph_counts_the_capability_gates_the_code_has(self) -> None:
        # Nothing else in the suite pins this, and the paragraph is the one an
        # auditor of a `--host` bind reads. It said eight of nine had nothing to
        # authenticate with, which erases the one POST boundary a remote client
        # genuinely cannot cross.
        source = (SERVER_PATH.parent / "compass_runtime" / "http_api.py").read_text(
            encoding="utf-8"
        )
        do_post = source[source.index("def do_POST(self)") :]
        table = do_post[do_post.index("route = {") : do_post.index("}.get(path)")]
        # The exact-match table, plus the one prefix route matched ahead of it.
        routes = len(re.findall(r'"(/api/[a-z/-]+)":', table)) + int(
            'path.startswith("/api/events/")' in do_post
        )
        gated = len(re.findall(r"\bcoordinator\.(?:focus_)?authorized\(", source))
        self.assertEqual(22, routes)
        self.assertEqual(2, gated)
        self.assertIn("Writing is the twenty-two POST routes", self.FLAT)
        self.assertIn("There is nothing to authenticate with on twenty of them", self.FLAT)
        self.assertIn("Two carry a capability and they are not worth the same.", self.FLAT)

    def test_the_copied_correction_route_is_named_counted_and_its_residual_stated(self) -> None:
        # DRC-4678: the thirteenth mutating endpoint and the sixth disk writer, the
        # local-process residual, where the digests live and what clears them, and the
        # exemption of a reader's edits inside a copied correction from the floor.
        self.assertIn("Sixteen endpoints mutate", self.FLAT)
        self.assertIn("Nine write to disk.", self.FLAT)
        self.assertIn("`POST /api/correction/copied`", self.FLAT)
        self.assertIn("`compass-copied-corrections.json`", self.FLAT)
        self.assertIn(
            "any process that can reach the loopback route can record a digest", self.FLAT
        )
        self.assertIn(
            "Reader edits inside a copied correction are exempt from the later-direction floor",
            self.FLAT,
        )

    def test_the_documented_framing_header_is_the_one_the_server_sends(self) -> None:
        # The paragraph sits in Known and accepted, beside the capability count
        # this class already pins, and it is bound here because its motivation
        # is this section's: the served document carries the focus capability,
        # so a framed board is a raise one lured click away.
        #
        # The quantifier rides with the sentence it qualifies rather than as the
        # trailing fragment this first pinned. "carries `Content-Security-Policy:
        # ...`" on its own survives a rewrite to "The page response carries ...",
        # which is a far smaller promise passing for the one made here.
        self.assertIn(
            "Every response the server composes carries "
            "`Content-Security-Policy: frame-ancestors 'none'`, with the three "
            "exceptions named below",
            self.FLAT,
        )
        source = (SERVER_PATH.parent / "compass_runtime" / "http_api.py").read_text(
            encoding="utf-8"
        )
        methods = handler_methods(source)
        csp = 'self.send_header("Content-Security-Policy", "frame-ancestors \'none\'")'
        # The whole value, not a substring. `frame-ancestors` has no fallback to
        # `default-src`, so it is the only directive that can ride here without
        # restricting the page; a second one in this policy blanks a board built
        # from one inline script, one inline style and nine `data:` font URIs.
        self.assertIn(csp, methods["_send"])
        # The count, not just the names. The prose shipped claiming two carve-outs
        # while the code had three, because `_ask_poll` composes its own 204 and
        # nothing named it. The terminal upgrade now adds the same header as
        # `_send`; the two writers without it, plus `send_error` bodies, remain
        # the three exceptions. Pin both sets so another writer cannot bypass
        # this contract silently.
        #
        # Named rather than narrowed to "every response `_send` composes": a
        # reader of this section can count responses over the socket with curl,
        # and cannot check the reach of a private helper without the source. The
        # neighbouring promises in this section are counts earned the same way.
        self.assertEqual(
            {"_send", "_stream_forever", "_ask_poll", "_interaction_stream"},
            {name for name, body in methods.items() if "self.send_response(" in body},
        )
        self.assertEqual(
            {"_send", "_interaction_stream"},
            {name for name, body in methods.items() if csp in body},
        )
        self.assertIn("Three responses are outside it, deliberately", self.FLAT)
        for carve_out in (
            "`/api/stream` writes its own headers and an event stream has nothing to click",
            "a `send_error` body is the standard library's error template",
            "the `204` a poll of `/api/ask/<id>` returns while no answer has arrived",
        ):
            with self.subTest(carve_out=carve_out):
                self.assertIn(carve_out, self.FLAT)
        # If the stream ever routes through `_send`, the prose is what goes
        # stale, not the code.
        self.assertNotIn("self._send(", methods["_stream_forever"])

    def test_the_response_the_contract_promises_is_the_one_the_route_sends(self) -> None:
        self.assertIn("The response is a single boolean saying whether a focus happened", self.FLAT)
        source = (SERVER_PATH.parent / "compass_runtime" / "http_api.py").read_text(
            encoding="utf-8"
        )
        handler = source[source.index("def _focus(self)") : source.index("def do_POST(self)")]
        self.assertIn('{"focused": focused}', handler)
        for echoed in ("target", "tty", "pane", "socket", "reason"):
            with self.subTest(field=echoed):
                self.assertNotIn(f'"{echoed}":', handler)


class ReaderStateInventoryTest(unittest.TestCase):
    """`docs/design-reader-state.md` against the render it describes (DRC-4446).

    The rule for what outlives a redraw used to live in per-lane comment blocks,
    which is how three lanes shipped without one and were each found separately
    after the fact. A comment citation cannot be checked; these are the checks
    the document bought.
    """

    ROOT = SERVER_PATH.parents[3]
    WEB = SERVER_PATH.parent / "compass_runtime" / "web"
    DOC_NAME = "docs/design-reader-state.md"
    DOC = (SERVER_PATH.parents[3] / DOC_NAME).read_text(encoding="utf-8")

    def rows(self) -> dict[str, tuple[str, str]]:
        """The inventory table, keyed by its first cell."""
        found = {}
        for line in self.DOC.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 3 or cells[1] in {"Across a redraw", "---"}:
                continue
            found[cells[0]] = (cells[1], cells[2])
        return found

    def test_both_split_out_lanes_carry_a_verdict_and_a_reason(self) -> None:
        rows = self.rows()
        for lane in ("The document scroll offset", "A text selection over rendered text"):
            with self.subTest(lane=lane):
                self.assertIn(lane, rows)
                verdict, where = rows[lane]
                self.assertTrue(verdict)
                self.assertIn("#", where)


class ClaudeReaderLimitIsSaidInTwoPlacesTest(unittest.TestCase):
    """The README's limits line and the how-to popup say the Claude reader's limit in the same words.

    The owner ruled on 2026-10-14 that the sentence goes in both, and the popup is a React page the
    README cannot link a heading in, so only a comparison keeps the two from drifting apart.
    """

    ROOT = SERVER_PATH.parents[3]
    SENTENCE = (
        "The Claude reader's accuracy check has not passed, and its latest correction is "
        "unmeasured, so read a level as an account of the evidence, not a measurement."
    )

    def test_the_readme_says_it(self) -> None:
        readme = re.sub(r"\s+", " ", (self.ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn(self.SENTENCE, readme)

    def test_the_how_to_popup_draws_the_constant_that_says_it(self) -> None:
        sentences = (self.ROOT / "frontend/src/drift/sentences.ts").read_text(encoding="utf-8")
        self.assertIn(f'CLAUDE_READER_LIMIT =\n  "{self.SENTENCE}"', sentences)
        how_to = (self.ROOT / "frontend/src/intent/HowTo.tsx").read_text(encoding="utf-8")
        self.assertIn("{CLAUDE_READER_LIMIT}", how_to)


class TheLiveMonitorIsSaidToCallAModelTest(unittest.TestCase):
    """The Live monitor calls Haiku about once a minute while a session is viewed, and every page says so.

    The owner ruled it on 2026-10-23 (DEC-26's amendment of that date). The model-free estimate is the
    monitor's fallback and still calls no model, so a sentence may say that of the estimate and may not say
    it of the monitor.
    """

    ROOT = SERVER_PATH.parents[3]
    PAGES = (
        "README.md",
        "HOW_TO_USE.md",
        "MANUAL.md",
        "SECURITY.md",
        "docs/promise-map.md",
        "compass/skills/compass/SKILL.md",
    )

    def _text(self, relative: str) -> str:
        return re.sub(r"\s+", " ", (self.ROOT / relative).read_text(encoding="utf-8"))

    def test_no_user_facing_page_says_the_monitor_calls_no_model(self) -> None:
        retired = re.compile(
            r"(?i)live monitor[^.]{0,240}(calls no model|with no model call|needs no model|never sent to the server)"
        )
        for relative in self.PAGES:
            with self.subTest(page=relative):
                self.assertIsNone(retired.search(self._text(relative)))

    def test_no_shipped_docstring_says_the_monitor_calls_no_model(self) -> None:
        runtime = SERVER_PATH.parent / "compass_runtime"
        retired = re.compile(
            r"(?i)live monitor[^.]{0,200}(calls no model|with no model call|needs no model)"
        )
        for path in sorted(runtime.glob("*.py")):
            with self.subTest(module=path.name):
                self.assertIsNone(
                    retired.search(re.sub(r"\s+", " ", path.read_text(encoding="utf-8")))
                )

    def test_the_pages_say_it_calls_haiku_and_the_accuracy_check_has_not_run(self) -> None:
        for relative in ("README.md", "docs/promise-map.md", "compass/skills/compass/SKILL.md"):
            text = self._text(relative)
            with self.subTest(page=relative):
                self.assertIn("Live monitor · Haiku", text)
                self.assertRegex(text, r"(?i)accuracy check has not been run")
                self.assertRegex(text, r"(?i)about once a minute")

    def test_security_lists_the_monitor_with_what_it_sends_and_every_stop(self) -> None:
        text = self._text("SECURITY.md")
        raw = (self.ROOT / "SECURITY.md").read_text(encoding="utf-8")
        row = next(line for line in raw.splitlines() if line.startswith("| A Live monitor check"))
        for stop in (
            "the switch",
            "leaving the session",
            "hiding the tab",
            "the session ending",
            "Pause model calls",
            "`--no-observer-model`",
            "the 20-minute question",
        ):
            self.assertIn(stop, row)
        self.assertIn("--claude-monitor-model", text)
        self.assertIn("Haiku", row)

    def test_pause_lists_the_monitor_and_the_amendment_heading_is_unchanged(self) -> None:
        summary = (self.ROOT / "docs/design-session-summary.md").read_text(encoding="utf-8")
        self.assertIn(
            "### Amended 2026-10-19: Pause model calls, with the summaries switch nested under it",
            summary,
        )
        later = summary.split("### Amended 2026-10-19: Pause model calls", 1)[1]
        heading = re.search(
            r"^### Amended 2026-10-23 \(owner\): the Live monitor[^\n]*$", later, re.MULTILINE
        )
        self.assertIsNotNone(heading)
        self.assertIn(
            "Pause model calls",
            later.split(heading.group(0), 1)[1].split("\n### ", 1)[0] if heading else "",
        )
        self.assertIn("the Live monitor", self._text("docs/promise-map.md"))
        self.assertRegex(
            self._text("docs/promise-map.md"),
            r"Pause model calls stops Analyze drift, goal summaries, session summaries and the Live monitor",
        )

    def test_the_unasked_lane_stays_the_only_path_that_spends_with_nobody_watching(self) -> None:
        text = self._text("docs/promise-map.md")
        self.assertIn(
            "The Live monitor does not: it calls a model only while a reader is viewing the session.",
            text,
        )
