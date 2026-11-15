from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import records
from compass_runtime import sessions as runtime_sessions
from compass_runtime import transcripts as runtime_transcripts
from compass_runtime import turns as runtime_turns
from compass_runtime.collectors import antigravity as agy_collector
from compass_runtime.collectors import gemini as gemini_collector

from .fixtures import (
    protobuf_bytes_field,
    protobuf_int_field,
    write_antigravity_metadata,
)
from .support import (
    REGISTRY,
    RuntimeTestCase,
    cfg,
    config_patch,
    make_config,
    make_runtime,
    runtime,
    state_of,
    store_patch,
)


# The generation-metadata half of an Antigravity store. `fixtures.py` writes the
# identity blob only, and this ticket needs a store that also has generations, so
# the shape lives here until the shared fixture grows a `gen_metadata` argument.
# One row per generation, newest last, exactly as the harness writes it: the
# collector reads `ORDER BY idx DESC LIMIT 1`, so the ordering is load-bearing.
def _write_antigravity_generations(path: Path, blobs: list[bytes]) -> None:
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB)")
        for index, blob in enumerate(blobs):
            connection.execute("INSERT INTO gen_metadata VALUES (?, ?)", (index, blob))
        connection.commit()


def _generation_blob(
    name: bytes,
    *,
    alias: bytes | None = None,
    trailing: bytes | None = None,
    trailing_field: int = 22,
    preamble: bytes | None = None,
) -> bytes:
    """One `gen_metadata.data` blob: top-level field 1, model name at field 21.

    `alias` is field 19, the internal model id the collector must never prefer.
    `trailing` appends a field *after* 21, which is what a future Antigravity
    build would do and what the terminal-field check exists to refuse.
    `trailing_field` picks its number, and the number decides which guard does
    the refusing: 16 and above encode to a two-byte tag whose lead byte is never
    a valid UTF-8 start, so the decoder refuses those before the length check is
    consulted; only a low number reaches the length check itself.
    `preamble` is bulk that sits before the name — conversation content, in a
    real store — and must stay outside the read window.
    """
    inner = b""
    if preamble is not None:
        inner += protobuf_bytes_field(9, preamble)
    if alias is not None:
        inner += protobuf_bytes_field(19, alias)
    inner += protobuf_bytes_field(21, name)
    if trailing is not None:
        inner += protobuf_bytes_field(trailing_field, trailing)
    return protobuf_bytes_field(1, inner)


class GeminiAntigravityCollectorTest(RuntimeTestCase):
    def test_a_chat_without_a_cwd_caps_its_project_directory_label(self) -> None:
        # DR-15. The cwd-less fallback is bound to `bounded_project_label`, and
        # nothing here saw that: no existing fixture drives the fallback with a
        # directory deeper than two segments, so reverting the bind to
        # `project_label` left the whole suite green.
        now = time.time()
        sid = "cccccccc-dddd-eeee-ffff-000000000000"
        home = "/Users/cl"
        encoded = f"{runtime_sessions.encoded_home_prefix(home)}-git-spacedock-subspace"
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "gemini-tmp"
            chats = legacy / encoded / "chats"
            chats.mkdir(parents=True)
            # No `directories`, so `project_from_cwd` returns "" and the encoded
            # directory name is the only label left.
            (chats / f"session-{sid}.jsonl").write_text(
                json.dumps({"sessionId": sid, "kind": "main"}) + "\n",
                encoding="utf-8",
            )
            os.utime(chats / f"session-{sid}.jsonl", (now - 30, now - 30))
            empty = Path(tmp) / "no-antigravity"
            empty.mkdir()
            with (
                store_patch(GEMINI_TMP=str(legacy), ANTIGRAVITY_CLI_DIR=str(empty)),
                config_patch(home=home),
            ):
                config, state = runtime()
                rows = gemini_collector.collect(config, state, now, 24, True)

        self.assertEqual(1, len(rows))
        self.assertEqual("spacedock-subspace", rows[0]["project"])

    def test_the_legacy_gemini_row_still_reads_its_own_store_alone(self) -> None:
        # Gemini CLI lost its consumer tiers, not its enterprise and API-key
        # ones, so this store is historical on some machines and live on others.
        # Either way the row stays. Splitting Antigravity out must not have taken
        # the Gemini arm with it, and the two predicates must not both claim one
        # store: that overlap is what put Gemini's name on live Antigravity
        # sessions in the first place.
        now = time.time()
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "gemini-tmp"
            chats = legacy / "proj" / "chats"
            chats.mkdir(parents=True)
            (chats / f"session-{sid}.jsonl").write_text(
                json.dumps({"sessionId": sid, "kind": "main", "directories": ["/w/proj"]})
                + "\n"
                + json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-08-04T00:00:00.000Z",
                        "content": "audit the retired store",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            os.utime(chats / f"session-{sid}.jsonl", (now - 30, now - 30))
            empty = Path(tmp) / "no-antigravity"
            empty.mkdir()
            with store_patch(GEMINI_TMP=str(legacy), ANTIGRAVITY_CLI_DIR=str(empty)):
                runtime_pair = runtime()
                gemini_spec = next(s for s in REGISTRY if s.key == "gemini")
                agy_spec = next(s for s in REGISTRY if s.key == "antigravity")
                discovered = gemini_spec.discover(*runtime_pair)
                agy_claimed = agy_spec.discover(*runtime_pair)
                config, state = runtime()
                sessions = gemini_collector.collect(config, state, now, 24, False)

        self.assertTrue(discovered)
        self.assertFalse(agy_claimed)
        self.assertEqual(1, len(sessions))
        self.assertEqual("gemini", sessions[0]["harness"])
        self.assertEqual(sid[:8], sessions[0]["session"])
        self.assertEqual(records.parse_ts("2026-08-04T00:00:00.000Z"), sessions[0]["started_at"])

    def test_record_fingerprint_is_stable_and_bounded(self) -> None:
        self.assertEqual(
            records.record_fingerprint({"a": 1, "b": 2}),
            records.record_fingerprint({"b": 2, "a": 1}),
        )
        self.assertEqual(16, len(records.record_fingerprint({"payload": "x" * 10_000})))

    def test_gemini_snapshot_expansion_keeps_only_records(self) -> None:
        first = {"type": "user", "content": "one"}
        second = {"type": "gemini", "content": "two"}
        snapshot = {"$set": {"messages": [first, "bad", second]}}

        self.assertEqual((first, second), records.gemini_records(snapshot))
        self.assertEqual((first,), records.gemini_records(first))

    def test_incremental_snapshot_returns_only_appended_records(self) -> None:
        first = {"type": "user", "content": "one"}
        second = {"type": "gemini", "content": "two"}
        third = {"type": "user", "content": "three"}
        state = {"gemini_snapshot_count": 0, "gemini_snapshot_tail": None}

        self.assertEqual(
            (first, second),
            records.incremental_gemini_records(
                {"$set": {"messages": [first, second]}},
                state,
            ),
        )
        self.assertEqual(
            (),
            records.incremental_gemini_records(
                {"$set": {"messages": [first, second]}},
                state,
            ),
        )
        self.assertEqual(
            (third,),
            records.incremental_gemini_records(
                {"$set": {"messages": [first, second, third]}},
                state,
            ),
        )

    def test_antigravity_head_keeps_partial_tail_without_a_line_cap(self) -> None:
        complete = [f"line-{index}" for index in range(40)]
        prefix = ("\n".join(complete) + "\npartial").encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cli.log"
            path.write_bytes(prefix + b"-continued")
            with config_patch(antigravity_log_head_bytes=len(prefix)):
                config, _state = runtime()
                lines = agy_collector._log_head_lines(config, str(path))

        self.assertEqual([*complete, "partial"], lines)

    def test_antigravity_combined_read_uses_one_config_for_head_and_tail(self) -> None:
        # The head and tail bounds have to come from the SAME config: as two
        # ambient lookups, a bound changing between them produced a head and a
        # tail that did not describe one file.
        config, _ = make_runtime(antigravity_log_head_bytes=13, tail_bytes=10)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cli.log"
            path.write_bytes(b"first-header\nmiddle\nlast-tail\n")
            lines = agy_collector._log_lines(config, str(path))

        # 13 head bytes cover "first-header\n"; 10 tail bytes cover "last-tail\n".
        # "middle" falls in neither window, so it is absent rather than counted twice.
        self.assertEqual(["first-header", "last-tail", ""], lines)

    def test_gemini_set_snapshot_updates_summary_and_turns(self) -> None:
        messages = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "content": "first prompt",
            },
            {
                "type": "gemini",
                "timestamp": "2026-01-01T00:00:05Z",
                "tokens": {"output": 42},
            },
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:10Z",
                "content": "resumed prompt",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session-test.jsonl"
            path.write_text(
                json.dumps({"$set": {"messages": messages[:2]}})
                + "\n"
                + json.dumps({"$set": {"messages": messages}})
                + "\n"
            )

            info = runtime_transcripts.analyze_gemini_transcript(make_config(), str(path))
            config, state = make_runtime()
            turns = runtime_turns.scan_turns(config, state, str(path), "gemini")

        self.assertEqual("resumed prompt", info["last_prompt"])
        self.assertEqual("resumed prompt", info["title"])
        self.assertEqual([(records.parse_ts("2026-01-01T00:00:05Z"), 42)], info["usage_events"])
        assert turns is not None
        self.assertEqual([5.0], turns["durations"])
        self.assertEqual(records.parse_ts("2026-01-01T00:00:10Z"), turns["turn_start"])

    def test_large_repeated_gemini_snapshot_does_not_churn_dedup_cache(self) -> None:
        messages = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "content": "first",
            },
            {
                "type": "gemini",
                "timestamp": "2026-01-01T00:00:05Z",
                "content": "answer",
            },
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:10Z",
                "content": "second",
            },
            {
                "type": "gemini",
                "timestamp": "2026-01-01T00:00:15Z",
                "content": "answer",
            },
        ]
        snapshot = json.dumps({"$set": {"messages": messages}})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session-test.jsonl"
            path.write_text(snapshot + "\n" + snapshot + "\n")
            config, state = make_runtime(gemini_seen_entries=2)
            turns = runtime_turns.scan_turns(config, state, str(path), "gemini")

        assert turns is not None
        self.assertEqual([5.0], turns["durations"])

    def test_antigravity_sessions_are_discovered_and_collected(self) -> None:
        now = time.time()
        session_id = "c38d2d70-a01e-46f8-9286-60493c4c0e7e"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "antigravity-cli"
            conversations = root / "conversations"
            logs = root / "log"
            legacy = Path(tmp) / "legacy-gemini"
            conversations.mkdir(parents=True)
            logs.mkdir()
            legacy.mkdir()
            (conversations / f"{session_id}.db").write_bytes(b"SQLite fixture")
            (logs / "cli-20260723_141844.log").write_text(
                "I0723 14:18:44.913145 server.go:237] Creating CLI server "
                "backend: product=antigravity "
                "workspaceDirs=[/Users/test/repos/recce/bridge] "
                f"appDataDir={root} cascadeManager=true\n"
                "I0723 14:19:32.952541 server.go:917] Created conversation "
                f"{session_id}\n"
                "I0723 14:47:19.285802 input_loop.go:34] HandleUserInput "
                'called with text: "show my assigned issues"\n'
                "I0723 14:47:19.285967 conversation_manager.go:499] "
                f"Forwarding user message to conversation {session_id} "
                "(items=1, media=0)\n"
            )

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root), GEMINI_TMP=str(legacy)),
            ):
                # Reach the predicate through a live registry spec, so this
                # still pins that the "antigravity" row is wired to the right
                # predicate and not merely that the key is present.
                runtime_pair = runtime()
                spec = next(s for s in REGISTRY if s.key == "antigravity")
                discovered = spec.discover(*runtime_pair)
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)
                # The legacy Gemini row must not claim this store: the two were
                # one bucket until Gemini CLI was retired, and a predicate left
                # matching both is exactly how the old label came back.
                gemini_spec = next(s for s in REGISTRY if s.key == "gemini")
                gemini_claimed = gemini_spec.discover(*runtime_pair)

        self.assertTrue(discovered)
        self.assertFalse(gemini_claimed)
        self.assertEqual(1, len(sessions))
        self.assertEqual("antigravity", sessions[0]["harness"])
        self.assertEqual(session_id[:8], sessions[0]["session"])
        self.assertEqual("recce/bridge", sessions[0]["project"])  # DRC-3963: <parent>/<basename>
        self.assertEqual("show my assigned issues", sessions[0]["title"])
        self.assertEqual("working", sessions[0]["state"])
        # DRC-4447. The fixture store is deliberately not a database, which is
        # the same reading a real store on an unrecognised schema gives, and the
        # empty activity snapshot behind it is what makes this row read as
        # working with a rate of zero. The title and the workspace above come
        # from the CLI log rather than the store and are unaffected.
        self.assertEqual(
            ["message history", "model", "token accounting"], sessions[0]["source_gaps"]
        )
        self.assertEqual(0, sessions[0]["rate_per_min"])

    def test_an_antigravity_store_that_reads_leaves_the_row_saying_nothing_extra(self) -> None:
        # The other half of the pair, and the reason the disclosure is not
        # furniture: a store whose `steps` table reads discloses nothing, even
        # when it holds no steps.
        now = time.time()
        session_id = "aaaa1111-a01e-46f8-9286-60493c4c0e7e"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "antigravity-cli"
            conversations = root / "conversations"
            logs = root / "log"
            conversations.mkdir(parents=True)
            logs.mkdir()
            db = conversations / f"{session_id}.db"
            write_antigravity_metadata(db, protobuf_bytes_field(6, session_id.encode()))
            _write_antigravity_generations(db, [])
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE steps (idx INTEGER, step_type TEXT, metadata BLOB)")
            con.commit()
            con.close()
            (logs / "cli-1.log").write_text(
                "workspaceDirs=[/work/acme/proj] "
                f"appDataDir={root} cascadeManager=true\n"
                f"Created conversation {session_id}\n"
            )
            with store_patch(ANTIGRAVITY_CLI_DIR=str(root)):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual([[]], [row["source_gaps"] for row in sessions])

    def test_antigravity_cache_primary_workspace_beats_added_directories(self) -> None:
        now = time.time()
        session_ids = (
            "deadbeef-a01e-46f8-9286-60493c4c0e7e",
            "deadbeef-b01e-46f8-9286-60493c4c0e7e",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "antigravity-cli"
            conversations = root / "conversations"
            logs = root / "log"
            cache = root / "cache" / "last_conversations.json"
            conversations.mkdir(parents=True)
            logs.mkdir()
            cache.parent.mkdir()
            for session_id in session_ids:
                write_antigravity_metadata(
                    conversations / f"{session_id}.db",
                    protobuf_bytes_field(6, session_id.encode()),
                )
            cache.write_text(json.dumps({"/work/acme/proj": session_ids[1]}))
            (logs / "cli-1.log").write_text(
                "workspaceDirs=[/work/acme/proj /work/shared/lib] "
                f"appDataDir={root} cascadeManager=true\n"
                f"Created conversation {session_ids[0]}\n"
                f"Created conversation {session_ids[1]}\n"
            )

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual(2, len(sessions))
        self.assertEqual({"acme/proj"}, {session["project"] for session in sessions})
        runtime_sessions.assign_display_ids(make_config(), sessions)
        self.assertEqual(2, len({session["session"] for session in sessions}))
        self.assertTrue(all(len(session["session"]) > 8 for session in sessions))

    def test_antigravity_unusable_cache_workspace_does_not_block_log_fallback(self) -> None:
        now = time.time()
        session_id = "c38d2d70-a01e-46f8-9286-60493c4c0e7e"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "antigravity-cli"
            conversations = root / "conversations"
            logs = root / "log"
            cache = root / "cache" / "last_conversations.json"
            conversations.mkdir(parents=True)
            logs.mkdir()
            cache.parent.mkdir()
            write_antigravity_metadata(
                conversations / f"{session_id}.db",
                protobuf_bytes_field(6, session_id.encode()),
            )
            cache.write_text(json.dumps({"relative/path": session_id}))
            (logs / "cli-1.log").write_text(
                "workspaceDirs=[/work/fallback/solo] "
                f"appDataDir={root} cascadeManager=true\n"
                f"Created conversation {session_id}\n"
            )

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual(1, len(sessions))
        self.assertEqual("fallback/solo", sessions[0]["project"])

    def test_antigravity_stale_log_can_anchor_active_workspace_context(self) -> None:
        now = time.time()
        active_sid = "11111111-a01e-46f8-9286-60493c4c0e7e"
        cached_sid = "22222222-b01e-46f8-9286-60493c4c0e7e"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "antigravity-cli"
            conversations = root / "conversations"
            logs = root / "log"
            cache = root / "cache" / "last_conversations.json"
            conversations.mkdir(parents=True)
            logs.mkdir()
            cache.parent.mkdir()
            for session_id in (active_sid, cached_sid):
                write_antigravity_metadata(
                    conversations / f"{session_id}.db",
                    protobuf_bytes_field(6, session_id.encode()),
                )
            cache.write_text(json.dumps({"/work/acme/proj": cached_sid}))
            workspace = (
                "workspaceDirs=[/work/acme/proj /work/shared/lib] "
                f"appDataDir={root} cascadeManager=true\n"
            )
            stale_log = logs / "cli-old.log"
            stale_log.write_text(workspace + f"Created conversation {cached_sid}\n")
            (logs / "cli-current.log").write_text(
                workspace + f"Created conversation {active_sid}\n"
            )
            stale = now - (25 * 3600)
            os.utime(stale_log, (stale, stale))
            os.utime(conversations / f"{cached_sid}.db", (stale, stale))

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual([active_sid], [session["sid"] for session in sessions])
        self.assertEqual("acme/proj", sessions[0]["project"])

    def test_antigravity_stale_log_can_anchor_an_additional_context(self) -> None:
        now = time.time()
        active_sid = "33333333-a01e-46f8-9286-60493c4c0e7e"
        cached_sid = "44444444-b01e-46f8-9286-60493c4c0e7e"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "antigravity-cli"
            logs = root / "log"
            cache = root / "cache" / "last_conversations.json"
            logs.mkdir(parents=True)
            cache.parent.mkdir()
            cache.write_text(json.dumps({"/work/acme/proj": cached_sid}))
            stale_context = (
                "workspaceDirs=[/work/acme/proj /work/shared/lib] "
                f"appDataDir={root} cascadeManager=true\n"
            )
            other_context = (
                "workspaceDirs=[/work/acme/proj /work/other/lib] "
                f"appDataDir={root} cascadeManager=true\n"
            )
            stale_log = logs / "cli-old.log"
            stale_log.write_text(stale_context + f"Created conversation {cached_sid}\n")
            (logs / "cli-current.log").write_text(
                stale_context
                + f"Created conversation {active_sid}\n"
                + other_context
                + f"Created conversation {cached_sid}\n"
            )
            stale = now - (25 * 3600)
            os.utime(stale_log, (stale, stale))

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, _state = runtime()
                metadata = agy_collector._session_metadata(config, now, 24, False)

        self.assertEqual("/work/acme/proj", metadata[active_sid]["cwd"])
        self.assertEqual("/work/acme/proj", metadata[cached_sid]["cwd"])

    def test_antigravity_steps_supply_rate_action_and_turn_progress(self) -> None:
        now = time.time()
        session_id = "c38d2d70-a01e-46f8-9286-60493c4c0e7e"

        def varint(value: int) -> bytes:
            encoded = bytearray()
            while value > 0x7F:
                encoded.append((value & 0x7F) | 0x80)
                value >>= 7
            encoded.append(value)
            return bytes(encoded)

        def int_field(number: int, value: int) -> bytes:
            return varint(number << 3) + varint(value)

        def bytes_field(number: int, value: bytes) -> bytes:
            return varint((number << 3) | 2) + varint(len(value)) + value

        def step_metadata(
            epoch: float,
            output_tokens: int | None = None,
            summary: str | None = None,
            action: str | None = None,
        ) -> bytes:
            timestamp = int_field(1, int(epoch))
            metadata = bytes_field(1, timestamp)
            if output_tokens is not None:
                usage = int_field(3, output_tokens)
                metadata += bytes_field(9, usage)
            if summary:
                metadata += bytes_field(30, summary.encode())
            if action:
                metadata += bytes_field(31, action.encode())
            return metadata

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "antigravity-cli"
            conversations = root / "conversations"
            logs = root / "log"
            legacy = Path(tmp) / "legacy-gemini"
            conversations.mkdir(parents=True)
            logs.mkdir()
            legacy.mkdir()
            database = conversations / f"{session_id}.db"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE steps ("
                "idx INTEGER PRIMARY KEY, step_type INTEGER, status INTEGER, "
                "metadata BLOB)"
            )
            rows = [
                (1, 14, 3, step_metadata(now - 180)),
                (2, 15, 3, step_metadata(now - 160, output_tokens=200)),
                (3, 15, 3, step_metadata(now - 130, output_tokens=300)),
                (4, 14, 3, step_metadata(now - 60)),
                (5, 15, 3, step_metadata(now - 50, output_tokens=600)),
                (
                    6,
                    21,
                    3,
                    step_metadata(
                        now - 40,
                        summary="Run project report",
                        action="Running project report",
                    ),
                ),
                (7, 15, 3, step_metadata(now - 10, output_tokens=400)),
            ]
            connection.executemany(
                "INSERT INTO steps (idx, step_type, status, metadata) VALUES (?, ?, ?, ?)",
                rows,
            )
            connection.commit()
            connection.close()
            (logs / "cli-20260723_141844.log").write_text(
                "I0723 14:18:44.913145 server.go:237] Creating CLI server "
                "backend: product=antigravity "
                "workspaceDirs=[/Users/test/repos/recce/bridge] "
                f"appDataDir={root} cascadeManager=true\n"
                "I0723 14:19:32.952541 server.go:917] Created conversation "
                f"{session_id}\n"
                "I0723 14:47:19.285802 input_loop.go:34] HandleUserInput "
                'called with text: "show my assigned issues"\n'
                "I0723 14:47:19.285967 conversation_manager.go:499] "
                f"Forwarding user message to conversation {session_id} "
                "(items=1, media=0)\n"
            )

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual(1, len(sessions))
        self.assertEqual(150, sessions[0]["rate_per_min"])
        self.assertEqual("Running project report", sessions[0]["state_detail"])
        self.assertEqual("1m", sessions[0]["turn"]["elapsed_h"])

    def test_antigravity_subagents_are_folded_under_parent(self) -> None:
        now = time.time()
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"

        parent_blob = protobuf_bytes_field(6, parent_sid.encode())
        sub_blob = protobuf_bytes_field(5, parent_sid.encode()) + protobuf_bytes_field(
            8, protobuf_bytes_field(2, b"Research Auditor")
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "antigravity-cli"
            conversations = root / "conversations"
            logs = root / "log"
            conversations.mkdir(parents=True)
            logs.mkdir(parents=True)

            for sid, blob in [(parent_sid, parent_blob), (sub_sid, sub_blob)]:
                write_antigravity_metadata(conversations / f"{sid}.db", blob)

            (logs / "cli-1.log").write_text(
                f"workspaceDirs=[/tmp/test-project] appDataDir=/tmp\n"
                f"Streaming conversation {parent_sid}\n"
                'HandleUserInput called with text: "Inspect codebase"\n'
                f"Forwarding user message to conversation {parent_sid}\n"
            )

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual(1, len(sessions))
        self.assertEqual(parent_sid, sessions[0]["sid"])
        self.assertEqual(
            [
                {
                    "name": "Research Auditor",
                    "model": None,
                    "started_at": None,
                    "active": None,
                    "parent": None,
                }
            ],
            sessions[0]["subagents"],
        )

    def test_antigravity_folded_subagent_rate_reaches_parent(self) -> None:
        now = time.time()
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            write_antigravity_metadata(
                conversations / f"{parent_sid}.db",
                protobuf_bytes_field(6, parent_sid.encode()),
            )
            sub_path = conversations / f"{sub_sid}.db"
            write_antigravity_metadata(
                sub_path,
                protobuf_bytes_field(5, parent_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"Research Auditor")),
            )
            timestamp = protobuf_int_field(1, int(now - 30))
            usage = protobuf_int_field(3, 600)
            step = protobuf_bytes_field(1, timestamp) + protobuf_bytes_field(9, usage)
            with contextlib.closing(sqlite3.connect(sub_path)) as connection:
                connection.execute(
                    "CREATE TABLE steps ("
                    "idx INTEGER PRIMARY KEY, step_type INTEGER, status INTEGER, metadata BLOB)"
                )
                connection.execute("INSERT INTO steps VALUES (1, 15, 3, ?)", (step,))
                connection.commit()

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual([parent_sid], [session["sid"] for session in sessions])
        self.assertEqual(60, sessions[0]["rate_per_min"])

    def test_antigravity_nested_subagent_activity_reaches_root(self) -> None:
        now = time.time()
        root_sid = "11111111-1111-1111-1111-111111111111"
        child_sid = "22222222-2222-2222-2222-222222222222"
        grandchild_sid = "33333333-3333-3333-3333-333333333333"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            write_antigravity_metadata(
                conversations / f"{root_sid}.db",
                protobuf_bytes_field(6, root_sid.encode()),
            )
            write_antigravity_metadata(
                conversations / f"{child_sid}.db",
                protobuf_bytes_field(5, root_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"Parent Worker")),
            )
            grandchild_path = conversations / f"{grandchild_sid}.db"
            write_antigravity_metadata(
                grandchild_path,
                protobuf_bytes_field(5, child_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"Nested Auditor")),
            )
            grandchild_mtime = os.path.getmtime(grandchild_path)
            stale = now - (25 * 3600)
            for sid in (root_sid, child_sid):
                os.utime(conversations / f"{sid}.db", (stale, stale))

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual([root_sid], [session["sid"] for session in sessions])
        self.assertEqual(
            [
                {
                    "name": "Nested Auditor",
                    "model": None,
                    "started_at": None,
                    "active": None,
                    "parent": None,
                }
            ],
            sessions[0]["subagents"],
        )
        self.assertEqual("working", sessions[0]["state"])
        self.assertEqual("running 1 subagent", sessions[0]["state_detail"])
        self.assertEqual(grandchild_mtime, sessions[0]["last_activity"])

    def test_antigravity_future_wal_does_not_hide_fresh_store(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "conversation.db"
            database.touch()
            os.utime(database, (now, now))
            wal = Path(f"{database}-wal")
            wal.write_bytes(b"\0" * 33)
            future = now + cfg().future_skew_tolerance_sec + 60
            os.utime(wal, (future, future))

            config, _state = runtime()
            mtime = agy_collector._store_mtime(config, str(database), now)

        self.assertEqual(now, mtime)

    def test_antigravity_empty_wal_does_not_invent_activity(self) -> None:
        now = time.time()
        database_mtime = now - cfg().working_threshold_sec - 1
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "conversation.db"
            database.touch()
            os.utime(database, (database_mtime, database_mtime))
            wal = Path(f"{database}-wal")
            wal.touch()
            os.utime(wal, (now, now))

            config, _state = runtime()
            mtime = agy_collector._store_mtime(config, str(database), now)

        self.assertEqual(database_mtime, mtime)

    def test_antigravity_stale_subagents_do_not_get_running_pills(self) -> None:
        now = time.time()
        parent_sid = "11111111-1111-1111-1111-111111111111"
        fresh_sid = "22222222-2222-2222-2222-222222222222"
        stale_sid = "33333333-3333-3333-3333-333333333333"
        parent_blob = protobuf_bytes_field(6, parent_sid.encode())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            write_antigravity_metadata(conversations / f"{parent_sid}.db", parent_blob)
            for sid, label in (
                (fresh_sid, b"Fresh Auditor"),
                (stale_sid, b"Finished Auditor"),
            ):
                blob = protobuf_bytes_field(5, parent_sid.encode()) + protobuf_bytes_field(
                    8, protobuf_bytes_field(2, label)
                )
                write_antigravity_metadata(conversations / f"{sid}.db", blob)
            stale = now - cfg().working_threshold_sec - 1
            os.utime(conversations / f"{stale_sid}.db", (stale, stale))

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual(
            [
                {
                    "name": "Fresh Auditor",
                    "model": None,
                    "started_at": None,
                    "active": None,
                    "parent": None,
                }
            ],
            sessions[0]["subagents"],
        )
        self.assertEqual("running 1 subagent", sessions[0]["state_detail"])

    def test_antigravity_skips_unrelated_stale_metadata_stores(self) -> None:
        now = time.time()
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"
        unrelated_sid = "33333333-3333-3333-3333-333333333333"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            write_antigravity_metadata(
                conversations / f"{parent_sid}.db",
                protobuf_bytes_field(6, parent_sid.encode()),
            )
            write_antigravity_metadata(
                conversations / f"{sub_sid}.db",
                protobuf_bytes_field(5, parent_sid.encode()),
            )
            write_antigravity_metadata(
                conversations / f"{unrelated_sid}.db",
                protobuf_bytes_field(6, unrelated_sid.encode()),
            )
            stale = now - (25 * 3600)
            for sid in (parent_sid, unrelated_sid):
                os.utime(conversations / f"{sid}.db", (stale, stale))

            inspected: list[str] = []
            real_session_info = agy_collector._session_info

            def inspect(cfg: Any, st: Any, path: str, sid: str) -> dict[str, Any]:
                inspected.append(sid)
                result: dict[str, Any] = real_session_info(cfg, st, path, sid)
                return result

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
                mock.patch.object(agy_collector, "_session_info", side_effect=inspect),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual({parent_sid, sub_sid}, set(inspected))
        self.assertEqual([parent_sid], [session["sid"] for session in sessions])

    def test_antigravity_running_subagent_precedes_parent_tool_action(self) -> None:
        now = time.time()
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            parent_path = conversations / f"{parent_sid}.db"
            write_antigravity_metadata(parent_path, protobuf_bytes_field(6, parent_sid.encode()))
            step = protobuf_bytes_field(1, protobuf_int_field(1, int(now))) + protobuf_bytes_field(
                31, b"Parent tool action"
            )
            with contextlib.closing(sqlite3.connect(parent_path)) as connection:
                connection.execute(
                    "CREATE TABLE steps (idx INTEGER PRIMARY KEY, step_type INTEGER, metadata BLOB)"
                )
                connection.execute(
                    "INSERT INTO steps VALUES (1, 21, ?)",
                    (step,),
                )
                connection.commit()
            write_antigravity_metadata(
                conversations / f"{sub_sid}.db",
                protobuf_bytes_field(5, parent_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"Research Auditor")),
            )

            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual("running 1 subagent", sessions[0]["state_detail"])

    def test_antigravity_blank_subagent_label_uses_session_prefix(self) -> None:
        now = time.time()
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            write_antigravity_metadata(
                conversations / f"{parent_sid}.db",
                protobuf_bytes_field(6, parent_sid.encode()),
            )
            write_antigravity_metadata(
                conversations / f"{sub_sid}.db",
                protobuf_bytes_field(5, parent_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"\x00\n")),
            )
            with (
                store_patch(ANTIGRAVITY_CLI_DIR=str(root)),
            ):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual(
            [
                {
                    "name": "subagent 22222222",
                    "model": None,
                    "started_at": None,
                    "active": None,
                    "parent": None,
                }
            ],
            sessions[0]["subagents"],
        )

    def test_antigravity_publishes_the_model_its_session_is_running_on(self) -> None:
        # No table in a conversation store has a model column, which is why a
        # `PRAGMA table_info` survey once concluded the harness does not report
        # one. It does: the product display name is the last field of the newest
        # `gen_metadata` blob.
        now = time.time()
        sid = "11111111-1111-1111-1111-111111111111"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            path = conversations / f"{sid}.db"
            write_antigravity_metadata(path, protobuf_bytes_field(6, sid.encode()))
            _write_antigravity_generations(path, [_generation_blob(b"Gemini 3.6 Flash (High)")])

            with store_patch(ANTIGRAVITY_CLI_DIR=str(root)):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual("Gemini 3.6 Flash (High)", sessions[0]["model"])
        # There is no measured provider: the blob's only vendor-adjacent fields
        # are per-generation booleans and an opaque placeholder enum, and reading
        # "google" off the string "Gemini" is inference.
        self.assertIsNone(sessions[0]["provider"])

    def test_the_newest_generation_wins_and_the_internal_alias_never_does(self) -> None:
        # Field 19 carries a model id too and is an alias: it reads
        # "gemini-pro-default" where field 21 reads "Gemini 3.1 Pro (High)".
        # Publishing it would need an alias-to-name table, which is a guess.
        sid = "11111111-1111-1111-1111-111111111111"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sid}.db"
            write_antigravity_metadata(path, protobuf_bytes_field(6, sid.encode()))
            _write_antigravity_generations(
                path,
                [
                    _generation_blob(b"Gemini 3.1 Pro (Low)"),
                    _generation_blob(b"Gemini 3.1 Pro (High)", alias=b"gemini-pro-default"),
                ],
            )
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(path), sid)

        self.assertEqual("Gemini 3.1 Pro (High)", info["model"])

    def test_a_trailing_field_whose_tag_breaks_the_decode_is_refused(self) -> None:
        # A future build that appends field 22 lands here, and the session must
        # report no model rather than a truncated or fused one. Which guard
        # refuses it is worth naming, because the name of this test used to claim
        # the other one: every field number from 16 up encodes to a two-byte tag
        # whose lead byte is 0x80-0xBF, never a valid UTF-8 start, so the decode
        # fails and the terminal-field check is never consulted. The check itself
        # is pinned by the low-numbered case below.
        sid = "11111111-1111-1111-1111-111111111111"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sid}.db"
            write_antigravity_metadata(path, protobuf_bytes_field(6, sid.encode()))
            _write_antigravity_generations(
                path,
                [_generation_blob(b"Gemini 3.6 Flash (High)", trailing=b"a-later-build")],
            )
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(path), sid)

        self.assertIsNone(info["model"])

    def test_a_trailing_low_numbered_field_is_refused_by_the_terminal_check(self) -> None:
        # Field 21 running to the last byte of the blob is an observed
        # serialization property, not a documented one, so the parse is accepted
        # only when it holds. A trailing field numbered 1-15 has a single-byte
        # ASCII tag, so the tail still decodes cleanly and the length check is the
        # only thing standing between a fused string and a card that presents it
        # as a measured model.
        sid = "11111111-1111-1111-1111-111111111111"
        blob = _generation_blob(
            b"Gemini 3.6 Flash (High)",
            trailing=b"gpt-oss-safety",
            trailing_field=9,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sid}.db"
            write_antigravity_metadata(path, protobuf_bytes_field(6, sid.encode()))
            _write_antigravity_generations(path, [blob])
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(path), sid)

        self.assertIsNone(info["model"])
        # And it was the length check that refused it, not the decoder: these are
        # the bytes the check rejects, and they decode without complaint. Remove
        # the check and this is what a card publishes.
        tail = blob[-64:]
        marker = tail.index(agy_collector._MODEL_FIELD_TAG)
        self.assertEqual(
            "Gemini 3.6 Flash (High)J gpt-oss-safety",
            records.safe_text(tail[marker + 3 :].decode("utf-8"), runtime_sessions.MODEL_CAP_CHARS),
        )

    def test_a_long_model_name_is_capped_and_its_control_bytes_scrubbed(self) -> None:
        # The name is untrusted vendor text on its way to the DOM, so it is
        # bounded and scrubbed like every other such string rather than published
        # as read. The 64-byte window admits 61 characters, well past the
        # 40-character cap, so the cap is the only thing holding the length.
        sid = "11111111-1111-1111-1111-111111111111"
        raw = b"Gemini 3.6 Ultra\x07Thinking Preview (Very High)"
        self.assertEqual(45, len(raw))  # admitted by the window, over the cap
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sid}.db"
            write_antigravity_metadata(path, protobuf_bytes_field(6, sid.encode()))
            _write_antigravity_generations(path, [_generation_blob(raw)])
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(path), sid)

        self.assertEqual("Gemini 3.6 Ultra Thinking Preview (Very", info["model"])
        self.assertLessEqual(len(info["model"]), runtime_sessions.MODEL_CAP_CHARS)
        self.assertNotIn("\x07", info["model"])

    def test_a_name_too_long_for_the_read_window_reports_no_model(self) -> None:
        # The window stays at 64 bytes for privacy, so a name past 61 characters
        # cannot be validated. That reads as "no model reported", which is the
        # right answer for a blob we could not check, not a reason to widen it.
        sid = "11111111-1111-1111-1111-111111111111"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sid}.db"
            write_antigravity_metadata(path, protobuf_bytes_field(6, sid.encode()))
            _write_antigravity_generations(path, [_generation_blob(b"G" * 62)])
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(path), sid)

        self.assertIsNone(info["model"])

    def test_the_model_read_stays_inside_the_window_and_the_open_connection(self) -> None:
        # Three invariants in one store, because they are the same constraint:
        # the read costs no extra connection, it asks SQLite for 64 bytes rather
        # than for the value, and the conversation content sitting before the
        # name never reaches the result. A wider tail on a real row holds
        # verbatim system-prompt text.
        #
        # `substr(data,-64)` would satisfy the last of those and fail the second:
        # a scalar function over a value materialises the whole row first. So the
        # SQL is asserted never to name the blob column, and the 64 bytes are
        # asserted to come through incremental blob I/O instead.
        sid = "11111111-1111-1111-1111-111111111111"
        secret = b"ALWAYS START your thought with recalling critical instructions"
        connections: list[Any] = []
        real_connect = runtime_io.sqlite_module.connect

        def spy(*args: Any, **kwargs: Any) -> Any:
            connection = mock.MagicMock(wraps=real_connect(*args, **kwargs))
            connections.append(connection)
            return connection

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sid}.db"
            write_antigravity_metadata(path, protobuf_bytes_field(6, sid.encode()))
            _write_antigravity_generations(
                path,
                [_generation_blob(b"Gemini 3.6 Flash (High)", preamble=secret)],
            )
            config, state = runtime()
            with mock.patch.object(
                runtime_io.sqlite_module,
                "connect",
                side_effect=spy,
            ) as connect:
                info = agy_collector._session_info(config, state, str(path), sid)

        self.assertEqual("Gemini 3.6 Flash (High)", info["model"])
        self.assertEqual(1, connect.call_count)
        self.assertNotIn("ALWAYS START", json.dumps(info))

        (connection,) = connections
        connection.blobopen.assert_called_once_with("gen_metadata", "data", mock.ANY, readonly=True)
        self.assertEqual(64, agy_collector._MODEL_TAIL_BYTES)
        statements = [call.args[0] for call in connection.execute.call_args_list]
        self.assertIn(agy_collector._MODEL_ROW_QUERY, statements)
        self.assertTrue(agy_collector._MODEL_ROW_QUERY.startswith("SELECT rowid FROM"))
        self.assertTrue(
            all(
                "gen_metadata" not in sql or sql == agy_collector._MODEL_ROW_QUERY
                for sql in statements
            ),
            statements,
        )

    def test_a_store_without_generation_metadata_still_reports_its_parent(self) -> None:
        # The model fails on its own terms. A store on a schema with no
        # `gen_metadata` at all is not a broken store, and the parent it does
        # report must survive the missing table.
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sub_sid}.db"
            write_antigravity_metadata(
                path,
                protobuf_bytes_field(5, parent_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"Research Auditor")),
            )
            with state_of().cache_lock:
                state_of().store_errors.clear()
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(path), sub_sid)

            self.assertNotIn(str(path), state_of().store_errors)

        self.assertEqual(parent_sid, info["parent_id"])
        self.assertEqual("Research Auditor", info["subagent_label"])
        self.assertIsNone(info["model"])

    def test_a_session_that_never_got_a_reply_reports_no_model_not_an_error(self) -> None:
        # Zero generations is a session that has not been answered yet. It reads
        # fine, so it must not reach the store-error diagnostics.
        sid = "11111111-1111-1111-1111-111111111111"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sid}.db"
            write_antigravity_metadata(path, protobuf_bytes_field(6, sid.encode()))
            _write_antigravity_generations(path, [])
            with state_of().cache_lock:
                state_of().store_errors.clear()
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(path), sid)

            self.assertNotIn(str(path), state_of().store_errors)

        self.assertIsNone(info["model"])

    def test_a_subagent_publishes_the_model_measured_in_its_own_store(self) -> None:
        # The live shape: a parent on Flash delegating to a subagent on Pro. Each
        # store is measured on its own, so both sides of the comparison the page
        # makes are readings rather than one reading and an assumption.
        now = time.time()
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            parent_path = conversations / f"{parent_sid}.db"
            write_antigravity_metadata(parent_path, protobuf_bytes_field(6, parent_sid.encode()))
            _write_antigravity_generations(
                parent_path, [_generation_blob(b"Gemini 3.6 Flash (High)")]
            )
            sub_path = conversations / f"{sub_sid}.db"
            write_antigravity_metadata(
                sub_path,
                protobuf_bytes_field(5, parent_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"Research Auditor")),
            )
            _write_antigravity_generations(sub_path, [_generation_blob(b"Gemini 3.1 Pro (Low)")])

            with store_patch(ANTIGRAVITY_CLI_DIR=str(root)):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual("Gemini 3.6 Flash (High)", sessions[0]["model"])
        self.assertEqual(
            [
                {
                    "name": "Research Auditor",
                    "model": "Gemini 3.1 Pro (Low)",
                    "started_at": None,
                    "active": None,
                    "parent": None,
                }
            ],
            sessions[0]["subagents"],
        )

    def test_an_unread_subagent_model_is_published_absent_never_inherited(self) -> None:
        # A subagent whose store holds no generations has not been measured. Its
        # model is None, never the parent's: a copied value renders identically
        # to a reading, which is the collapse this field exists to prevent.
        now = time.time()
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            parent_path = conversations / f"{parent_sid}.db"
            write_antigravity_metadata(parent_path, protobuf_bytes_field(6, parent_sid.encode()))
            _write_antigravity_generations(
                parent_path, [_generation_blob(b"Gemini 3.6 Flash (High)")]
            )
            write_antigravity_metadata(
                conversations / f"{sub_sid}.db",
                protobuf_bytes_field(5, parent_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"Research Auditor")),
            )

            with store_patch(ANTIGRAVITY_CLI_DIR=str(root)):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual("Gemini 3.6 Flash (High)", sessions[0]["model"])
        self.assertEqual(
            [
                {
                    "name": "Research Auditor",
                    "model": None,
                    "started_at": None,
                    "active": None,
                    "parent": None,
                }
            ],
            sessions[0]["subagents"],
        )

    def test_a_nested_subagent_carries_the_model_its_own_store_reports(self) -> None:
        # `descendants()` flattens the subtree, so a grandchild is listed on the
        # root's card beside its own parent. Each entry still carries the model
        # its own store reports and nothing else — the collector attributes no
        # model across stores, and the page compares what it is given.
        now = time.time()
        root_sid = "11111111-1111-1111-1111-111111111111"
        child_sid = "22222222-2222-2222-2222-222222222222"
        grandchild_sid = "33333333-3333-3333-3333-333333333333"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir()
            root_path = conversations / f"{root_sid}.db"
            write_antigravity_metadata(root_path, protobuf_bytes_field(6, root_sid.encode()))
            _write_antigravity_generations(
                root_path, [_generation_blob(b"Gemini 3.6 Flash (High)")]
            )
            child_path = conversations / f"{child_sid}.db"
            write_antigravity_metadata(
                child_path,
                protobuf_bytes_field(5, root_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"Parent Worker")),
            )
            _write_antigravity_generations(child_path, [_generation_blob(b"Gemini 3.1 Pro (Low)")])
            grandchild_path = conversations / f"{grandchild_sid}.db"
            write_antigravity_metadata(
                grandchild_path,
                protobuf_bytes_field(5, child_sid.encode())
                + protobuf_bytes_field(8, protobuf_bytes_field(2, b"Nested Auditor")),
            )
            _write_antigravity_generations(
                grandchild_path, [_generation_blob(b"Gemini 3.1 Pro (Low)")]
            )

            with store_patch(ANTIGRAVITY_CLI_DIR=str(root)):
                config, state = runtime()
                sessions = agy_collector.collect(config, state, now, 24, False)

        self.assertEqual([root_sid], [session["sid"] for session in sessions])
        self.assertEqual(
            {("Parent Worker", "Gemini 3.1 Pro (Low)"), ("Nested Auditor", "Gemini 3.1 Pro (Low)")},
            {(a["name"], a["model"]) for a in sessions[0]["subagents"]},
        )

    def test_antigravity_session_info_uses_decodable_fallback_fields(self) -> None:
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"
        blob = (
            protobuf_bytes_field(5, b"\xff")
            + protobuf_bytes_field(6, parent_sid.encode())
            + protobuf_bytes_field(
                8,
                protobuf_bytes_field(2, b"\xff") + protobuf_bytes_field(1, b"reviewer"),
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sub_sid}.db"
            write_antigravity_metadata(path, blob)
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(path), sub_sid)

        self.assertEqual(parent_sid, info["parent_id"])
        self.assertEqual("reviewer", info["subagent_label"])

    def test_antigravity_session_info_skips_blank_role_for_type_name(self) -> None:
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"
        blob = protobuf_bytes_field(5, parent_sid.encode()) + protobuf_bytes_field(
            8,
            protobuf_bytes_field(2, b" \t") + protobuf_bytes_field(1, b"reviewer"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{sub_sid}.db"
            write_antigravity_metadata(path, blob)
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(path), sub_sid)

        self.assertEqual(parent_sid, info["parent_id"])
        self.assertEqual("reviewer", info["subagent_label"])

    def test_antigravity_session_info_falls_back_for_clean_wal_store(self) -> None:
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"
        blob = protobuf_bytes_field(5, parent_sid.encode()) + protobuf_bytes_field(
            8, protobuf_bytes_field(2, b"Research Auditor")
        )
        plain = mock.MagicMock(spec=sqlite3.Connection)
        plain.execute.side_effect = sqlite3.OperationalError("unable to open database file")
        immutable = mock.MagicMock(spec=sqlite3.Connection)
        immutable.execute.return_value.fetchone.return_value = (blob,)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = Path(temporary.name) / "session.db"
        database.touch()
        with mock.patch.object(
            runtime_io.sqlite_module,
            "connect",
            side_effect=(plain, immutable),
        ) as connect:
            with state_of().cache_lock:
                state_of().store_errors.clear()
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(database), sub_sid)

        self.assertEqual(parent_sid, info["parent_id"])
        self.assertEqual("Research Auditor", info["subagent_label"])
        self.assertEqual(2, connect.call_count)
        self.assertIn("immutable=1", connect.call_args_list[1].args[0])
        self.assertNotIn(str(database), state_of().store_errors)
        plain.close.assert_called_once_with()
        immutable.close.assert_called_once_with()

    def test_antigravity_session_info_does_not_bypass_live_wal(self) -> None:
        connection = mock.MagicMock(spec=sqlite3.Connection)
        connection.execute.side_effect = sqlite3.OperationalError("database is locked")
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                runtime_io.sqlite_module, "connect", return_value=connection
            ) as connect,
        ):
            database = Path(tmp) / "session.db"
            database.touch()
            Path(f"{database}-wal").write_bytes(b"\0" * 33)
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(database), "session")

        self.assertEqual(
            {"parent_id": None, "subagent_label": None, "model": None, "model_unread": True}, info
        )
        self.assertEqual(1, connect.call_count)
        connection.close.assert_called_once_with()

    def test_antigravity_session_info_reads_closed_wal_store(self) -> None:
        parent_sid = "11111111-1111-1111-1111-111111111111"
        sub_sid = "22222222-2222-2222-2222-222222222222"
        blob = protobuf_bytes_field(5, parent_sid.encode()) + protobuf_bytes_field(
            8, protobuf_bytes_field(2, b"Research Auditor")
        )
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "session.db"
            with contextlib.closing(sqlite3.connect(database)) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    "CREATE TABLE trajectory_metadata_blob (id TEXT PRIMARY KEY, data BLOB)"
                )
                connection.execute(
                    "INSERT INTO trajectory_metadata_blob VALUES ('main', ?)",
                    (blob,),
                )
                connection.commit()
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            for sidecar in (Path(f"{database}-wal"), Path(f"{database}-shm")):
                with contextlib.suppress(FileNotFoundError):
                    sidecar.unlink()

            config, state = runtime()
            info = agy_collector._session_info(config, state, str(database), sub_sid)

        self.assertEqual(parent_sid, info["parent_id"])
        self.assertEqual("Research Auditor", info["subagent_label"])

    def test_antigravity_session_info_returns_empty_after_both_readers_fail(self) -> None:
        plain = mock.MagicMock(spec=sqlite3.Connection)
        plain.execute.side_effect = sqlite3.OperationalError("database is locked")
        immutable = mock.MagicMock(spec=sqlite3.Connection)
        immutable.execute.side_effect = sqlite3.OperationalError("database is malformed")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = Path(temporary.name) / "session.db"
        database.touch()
        with mock.patch.object(
            runtime_io.sqlite_module,
            "connect",
            side_effect=(plain, immutable),
        ) as connect:
            config, state = runtime()
            info = agy_collector._session_info(config, state, str(database), "session")

        self.assertEqual(
            {"parent_id": None, "subagent_label": None, "model": None, "model_unread": True}, info
        )
        self.assertEqual(2, connect.call_count)
        plain.close.assert_called_once_with()
        immutable.close.assert_called_once_with()

    def test_protobuf_fields_rejects_non_blob_payloads_before_conversion(self) -> None:
        with self.assertRaisesRegex(TypeError, "bytes-like"):
            next(agy_collector.protobuf_fields(8))

    def test_antigravity_activity_sees_uncheckpointed_wal_frames(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "live.db"
            writer = sqlite3.connect(db)
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute(
                "CREATE TABLE steps (idx INTEGER PRIMARY KEY, step_type INTEGER,"
                " status INTEGER, metadata BLOB)"
            )
            writer.commit()

            def step_metadata(epoch: float, output_tokens: int) -> bytes:
                def varint(value: int) -> bytes:
                    encoded = bytearray()
                    while value > 0x7F:
                        encoded.append((value & 0x7F) | 0x80)
                        value >>= 7
                    encoded.append(value)
                    return bytes(encoded)

                timestamp = varint(1 << 3) + varint(int(epoch))
                metadata = varint((1 << 3) | 2) + varint(len(timestamp)) + timestamp
                usage = varint(3 << 3) + varint(output_tokens)
                metadata += varint((9 << 3) | 2) + varint(len(usage)) + usage
                return metadata

            writer.execute(
                "INSERT INTO steps VALUES (1, 15, 3, ?)",
                (step_metadata(now - 30, 500),),
            )
            writer.commit()  # committed to the WAL; not yet checkpointed
            try:
                config, state = runtime()
                activity = agy_collector._step_activity(config, state, str(db), now)
            finally:
                writer.close()

        # An immutable=1-only reader misses these frames (rate stays 0).
        self.assertEqual(50, activity["rate_per_min"])

    def test_antigravity_activity_does_not_report_recovered_reader_error(self) -> None:
        now = time.time()
        timestamp = protobuf_int_field(1, int(now - 30))
        usage = protobuf_int_field(3, 500)
        metadata = protobuf_bytes_field(1, timestamp) + protobuf_bytes_field(9, usage)
        plain = mock.MagicMock(spec=sqlite3.Connection)
        plain.execute.side_effect = sqlite3.OperationalError("unable to open database file")
        immutable = mock.MagicMock(spec=sqlite3.Connection)
        immutable.execute.return_value.fetchall.return_value = [(15, metadata)]

        with state_of().cache_lock:
            state_of().store_errors.clear()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = Path(temporary.name) / "session.db"
        database.touch()
        with mock.patch.object(
            runtime_io.sqlite_module,
            "connect",
            side_effect=(plain, immutable),
        ):
            config, state = runtime()
            activity = agy_collector._step_activity(config, state, str(database), now)

        self.assertEqual(50, activity["rate_per_min"])
        self.assertNotIn(str(database), state_of().store_errors)
        plain.close.assert_called_once_with()
        immutable.close.assert_called_once_with()
