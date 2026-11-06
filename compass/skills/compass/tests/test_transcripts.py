from __future__ import annotations

import dataclasses
import functools
import json
import os
import random
import tempfile
import threading
import time
import unicodedata
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, ClassVar

from compass_runtime import claude_data, records
from compass_runtime import io as runtime_io
from compass_runtime import transcripts as runtime_transcripts

from .support import (
    RuntimeTestCase,
    config_patch,
    make_config,
    make_runtime,
    runtime,
)

# The backward reader's linearity is a best-of-three timing ratio.
REAL_TIME_TESTS = True

CONFIG, STATE = make_runtime()


class CompassServerTest(RuntimeTestCase):
    def test_metadata_cache_is_safe_under_concurrent_reads(self) -> None:
        config, state = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meta.jsonl"
            path.write_text(json.dumps({"value": "ok"}) + "\n")
            parsed = threading.Event()
            parse_lock = threading.Lock()
            parse_count = 0

            def parse(value: dict[str, Any]) -> dict[str, Any]:
                nonlocal parse_count
                with parse_lock:
                    parse_count += 1
                    wait_for_pair = parse_count <= 2
                    if parse_count == 2:
                        parsed.set()
                if wait_for_pair and not parsed.wait(timeout=30):
                    raise AssertionError("concurrent readers did not reach the metadata parser")
                return {"value": value.get("value")}

            def read() -> Any:
                return runtime_transcripts.first_line_meta(config, state, str(path), parse)

            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(lambda _: read(), range(100)))

        self.assertTrue(all(result == {"value": "ok"} for result in results))
        self.assertEqual(1, len(state.metadata_cache))

    def test_read_tail_keeps_first_record_when_window_starts_on_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_bytes(b"aaaa\nbbbb\ncccc\n")  # 15 bytes

            # Window of 10 starts right after the newline at offset 4:
            # "bbbb" is a complete record and must be kept.
            aligned = runtime_io.read_tail(make_config(tail_bytes=10), str(path))
            # Window of 9 starts mid-"bbbb": the partial line must drop.
            misaligned = runtime_io.read_tail(make_config(tail_bytes=9), str(path))

        self.assertEqual(["bbbb", "cccc", ""], aligned)
        self.assertEqual(["cccc", ""], misaligned)


class BoundedReadTest(unittest.TestCase):
    def test_first_json_record_honors_before_at_and_after_cap(self) -> None:
        payload = b'{"x":1}'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.jsonl"
            path.write_bytes(payload)

            before = runtime_io.read_first_json(
                make_config(first_line_json_cap_bytes=len(payload) - 1),
                str(path),
            )
            at = runtime_io.read_first_json(
                make_config(first_line_json_cap_bytes=len(payload)),
                str(path),
            )
            after = runtime_io.read_first_json(
                make_config(first_line_json_cap_bytes=len(payload) + 1),
                str(path),
            )

        self.assertEqual({}, before)
        self.assertEqual({"x": 1}, at)
        self.assertEqual({"x": 1}, after)

    def test_first_json_record_rejects_non_objects_and_bad_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.jsonl"
            for raw in (b"[1,2]", b"{bad", b"\xff"):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    self.assertEqual(
                        {},
                        runtime_io.read_first_json(
                            make_config(first_line_json_cap_bytes=64),
                            str(path),
                        ),
                    )
            self.assertEqual(
                {},
                runtime_io.read_first_json(
                    make_config(first_line_json_cap_bytes=64),
                    str(Path(tmp) / "missing"),
                ),
            )

    def test_prefix_bytes_returns_only_the_requested_total_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prefix"
            path.write_bytes(b"abcdef")
            self.assertEqual(b"", runtime_io.read_prefix_bytes(str(path), max_bytes=0))
            self.assertEqual(b"abc", runtime_io.read_prefix_bytes(str(path), max_bytes=3))
            self.assertEqual(b"abcdef", runtime_io.read_prefix_bytes(str(path), max_bytes=6))
            self.assertEqual(b"abcdef", runtime_io.read_prefix_bytes(str(path), max_bytes=7))

    def test_bounded_lines_use_independent_per_call_caps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lines"
            path.write_bytes(b"abc\n12345\nz\n")
            self.assertEqual(
                [],
                list(
                    runtime_io.iter_bounded_text_lines(
                        str(path),
                        max_lines=0,
                        per_line_bytes=4,
                    )
                ),
            )
            self.assertEqual(
                ["abc\n", "1234"],
                list(
                    runtime_io.iter_bounded_text_lines(
                        str(path),
                        max_lines=2,
                        per_line_bytes=4,
                    )
                ),
            )
            self.assertEqual(
                ["abc\n", "1234", "5\n", "z\n"],
                list(
                    runtime_io.iter_bounded_text_lines(
                        str(path),
                        max_lines=4,
                        per_line_bytes=4,
                    )
                ),
            )

    def test_bounded_lines_replace_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lines"
            path.write_bytes(b"a\xff\n")
            self.assertEqual(
                ["a\ufffd\n"],
                list(
                    runtime_io.iter_bounded_text_lines(
                        str(path),
                        max_lines=1,
                        per_line_bytes=8,
                    )
                ),
            )


class ReverseLinesTest(unittest.TestCase):
    """Replaces the reverse mmap scans. A mapped region whose file is truncated
    underneath it raises SIGBUS on POSIX (uncatchable) and blocks the writer's
    truncate on Windows; these are transcripts a live agent may rotate."""

    def setUp(self) -> None:
        self.config = make_config()

    def write(self, tmp: str, text: str) -> str:
        path = Path(tmp) / "t.jsonl"
        # write_bytes, not write_text: Windows text mode translates "\n" to
        # "\r\n", and these tests assert on exact byte boundaries. Harnesses
        # write LF transcripts, which is what this reproduces.
        path.write_bytes(text.encode())
        return str(path)

    def read_back(self, path: str, **kwargs: Any) -> list[str]:
        config = kwargs.pop("config", None) or self.config
        return [raw.decode() for raw in runtime_io.reverse_lines(config, path, **kwargs)]

    def test_yields_lines_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "a\nb\nc\n")
            self.assertEqual(["", "c", "b", "a"], self.read_back(path))

    def test_file_without_a_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "a\nb\nc")
            self.assertEqual(["c", "b", "a"], self.read_back(path))

    def test_empty_and_missing_files_yield_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], self.read_back(self.write(tmp, "")))
            self.assertEqual([], self.read_back(str(Path(tmp) / "absent.jsonl")))

    def test_lines_spanning_chunk_boundaries_are_reassembled(self) -> None:
        # The whole risk of chunked reverse reading: a record split across two
        # reads must come back intact. Forced with a chunk far smaller than the
        # lines, at several sizes so no single alignment can hide a bug.
        lines = [f"{i:04d}-" + "x" * (i % 37) for i in range(200)]
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "\n".join(lines) + "\n")
            for chunk in (1, 2, 3, 7, 64, 1000):
                with self.subTest(chunk=chunk):
                    got = [
                        line
                        for line in self.read_back(
                            path,
                            config=dataclasses.replace(
                                self.config,
                                reverse_chunk_bytes=chunk,
                            ),
                        )
                        if line
                    ]
                    self.assertEqual(list(reversed(lines)), got)

    def test_contains_filter_never_hides_a_matching_line(self) -> None:
        # The filter tests whole chunks, so a match split across a chunk
        # boundary is exactly what could go missing. Sweep every alignment.
        with tempfile.TemporaryDirectory() as tmp:
            for offset in range(40):
                text = "x" * offset + "\nfiller\nNEEDLE-here\nfiller\n"
                path = self.write(tmp, text)
                for chunk in (1, 2, 3, 5, 8, 13):
                    with self.subTest(offset=offset, chunk=chunk):
                        got = [
                            raw.decode()
                            for raw in runtime_io.reverse_lines(
                                dataclasses.replace(
                                    self.config,
                                    reverse_chunk_bytes=chunk,
                                ),
                                path,
                                contains=b"NEEDLE",
                            )
                            if b"NEEDLE" in raw
                        ]
                        self.assertEqual(["NEEDLE-here"], got)

    def test_contains_filter_matches_the_unfiltered_walk(self) -> None:
        lines = [f"rec{i}" + ("-TARGET" if i % 97 == 0 else "") for i in range(500)]
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "\n".join(lines) + "\n")
            for chunk in (4, 16, 256):
                with self.subTest(chunk=chunk):
                    config = dataclasses.replace(self.config, reverse_chunk_bytes=chunk)
                    unfiltered = [
                        raw for raw in runtime_io.reverse_lines(config, path) if b"TARGET" in raw
                    ]
                    filtered = [
                        raw
                        for raw in runtime_io.reverse_lines(config, path, contains=b"TARGET")
                        if b"TARGET" in raw
                    ]
                    self.assertEqual(unfiltered, filtered)
                    self.assertEqual(6, len(filtered))

    def test_matches_a_trivial_reference_across_the_input_space(self) -> None:
        # The strongest guarantee available: compare against slice/split/reverse
        # over a generated corpus, at every chunk size, end_pos and max_bytes.
        # This is what caught the list-accumulation rewrite being correct.
        def reference(data: bytes, stop: int, max_bytes: int | None) -> list[bytes]:
            floor = 0 if max_bytes is None else max(0, stop - max_bytes)
            window = data[floor:stop] if floor else data[:stop]
            out = list(reversed(window.split(b"\n")))
            if floor:
                return out[:-1]  # oldest is a fragment when the walk is bounded
            return [] if stop == 0 else out

        rng = random.Random(11)
        alphabet = [b"a", b"bb", b"", b"NEEDLE", b"xNEEDLEy", b"c" * 40]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f"
            for _ in range(60):
                data = b"\n".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))
                if rng.random() < 0.5:
                    data += b"\n"
                path.write_bytes(data)
                size = len(data)
                for stop in {size, max(0, size // 2), max(0, size - 1), 0}:
                    for max_bytes in (None, 3, 10):
                        for chunk in (1, 2, 5, 4096):
                            got = list(
                                runtime_io.reverse_lines(
                                    dataclasses.replace(
                                        self.config,
                                        reverse_chunk_bytes=chunk,
                                    ),
                                    str(path),
                                    stop,
                                    max_bytes=max_bytes,
                                )
                            )
                            if got != reference(data, stop, max_bytes):
                                self.fail(
                                    f"data={data!r} stop={stop} max_bytes={max_bytes} "
                                    f"chunk={chunk}: {got} != {reference(data, stop, max_bytes)}"
                                )

    def test_the_contains_filter_never_hides_a_line(self) -> None:
        # The filter tests each chunk and the completed line rather than a
        # joined buffer, so a match spanning chunks is the risk.
        rng = random.Random(12)
        alphabet = [b"a", b"bb", b"", b"NEEDLE", b"xNEEDLEy", b"c" * 40]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f"
            for _ in range(60):
                data = b"\n".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))
                path.write_bytes(data + rng.choice([b"\n", b""]))
                for chunk in (1, 2, 3, 5, 17, 4096):
                    config = dataclasses.replace(self.config, reverse_chunk_bytes=chunk)
                    plain = [
                        raw
                        for raw in runtime_io.reverse_lines(config, str(path))
                        if b"NEEDLE" in raw
                    ]
                    filtered = [
                        raw
                        for raw in runtime_io.reverse_lines(
                            config,
                            str(path),
                            contains=b"NEEDLE",
                        )
                        if b"NEEDLE" in raw
                    ]
                    self.assertEqual(plain, filtered, f"chunk={chunk} data={data!r}")

    def test_crlf_transcripts_still_parse(self) -> None:
        # Harnesses write LF, but a transcript can pick up CRLF by being copied
        # through a Windows tool. Lines split on "\n" keep a trailing "\r";
        # that must not change what the readers extract.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crlf.jsonl"
            path.write_bytes(
                b"\r\n".join(
                    [
                        json.dumps({"type": "ai-title", "aiTitle": "CRLF title"}).encode(),
                        json.dumps({"type": "user", "uuid": "u-crlf"}).encode(),
                    ]
                )
                + b"\r\n"
            )
            config, state = runtime()
            self.assertEqual("CRLF title", claude_data.session_title(config, state, str(path)))
            config, state = runtime()
            self.assertEqual("u-crlf", claude_data.last_user_event(config, state, str(path)))

    def test_end_pos_limits_the_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "aaa\nbbb\nccc\n")
            self.assertEqual(["", "bbb", "aaa"], self.read_back(path, end_pos=8))

    def test_max_bytes_drops_the_oldest_partial_line(self) -> None:
        # Stopping mid-file means the oldest line reached is probably a
        # fragment, so it is discarded rather than parsed as a record.
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "aaaa\nbbbb\ncccc\n")
            self.assertEqual(["", "cccc"], self.read_back(path, max_bytes=6))

    def test_a_file_truncated_mid_scan_stops_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "\n".join(f"line{i}" for i in range(500)) + "\n")
            walker = runtime_io.reverse_lines(
                dataclasses.replace(self.config, reverse_chunk_bytes=16),
                path,
            )
            next(walker)
            Path(path).write_bytes(b"")  # writer rotates the transcript
            remaining = list(walker)  # must not raise
        self.assertIsInstance(remaining, list)

    def test_a_line_ending_exactly_at_end_pos_is_yielded(self) -> None:
        # Where the reverse and forward halves of scan_turns meet. The forward
        # pass resumes at the same offset, and a forward read starting on a
        # newline never sees the record that newline terminates — so the
        # reverse pass has to yield it. The previous mmap reader searched
        # rfind("\n", 0, end_pos), which excluded that byte and dropped the
        # record from both halves.
        #
        # Note this does not make the split lossless in general: a record
        # straddling the split offset is still missed by both halves. That is a
        # pre-existing limit of the bounded scan, unchanged by this PR.
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "first\nsecond\nthird\n")
            split = len("first\nsecond")  # the newline terminating "second"
            self.assertEqual(b"\n", Path(path).read_bytes()[split : split + 1])
            got = [
                raw.decode() for raw in runtime_io.reverse_lines(self.config, path, split) if raw
            ]
        self.assertEqual(["second", "first"], got)

    def test_title_and_user_event_still_scan_the_whole_file(self) -> None:
        # Both readers look past the bounded activity tail, which is why they
        # walk backward at all rather than reusing read_tail().
        filler = [json.dumps({"type": "assistant", "message": {}}) for _ in range(400)]
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(
                tmp,
                "\n".join(
                    [
                        json.dumps({"type": "ai-title", "aiTitle": "Old title"}),
                        json.dumps({"type": "user", "uuid": "u-old"}),
                        *filler,
                        json.dumps({"type": "ai-title", "aiTitle": "Newest title"}),
                        json.dumps({"type": "user", "uuid": "u-new"}),
                        *filler,
                    ]
                )
                + "\n",
            )
            with config_patch(reverse_chunk_bytes=128):
                config, state = runtime()
                self.assertEqual("Newest title", claude_data.session_title(config, state, path))
                config, state = runtime()
                self.assertEqual("u-new", claude_data.last_user_event(config, state, path))


class PromptTitleTest(unittest.TestCase):
    """A session with no generated title falls back to its first prompt, and
    the harness wraps some prompts in markup. Measured over 248 real
    transcripts, 138 titles rendered as raw tags before this."""

    def test_a_slash_command_reads_as_the_command(self) -> None:
        prompt = (
            "<command-name>/plugin</command-name>\n"
            "            <command-message>plugin</command-message>\n"
            "            <command-args></command-args>"
        )

        self.assertEqual("/plugin", runtime_transcripts.prompt_title(CONFIG, prompt))

    def test_a_command_keeps_its_arguments(self) -> None:
        prompt = (
            "<command-message>recce-dev:claude-code-review</command-message>\n"
            "<command-name>/recce-dev:claude-code-review</command-name>\n"
            "<command-args>https://example.test/pr/1 and fix the findings</command-args>"
        )

        self.assertEqual(
            "/recce-dev:claude-code-review https://example.test/pr/1 and fix the findings",
            runtime_transcripts.prompt_title(CONFIG, prompt),
        )

    def test_a_wrapped_payload_shows_its_content_not_the_envelope(self) -> None:
        """The single most common case in the wild: 113 of the 138."""
        prompt = (
            '<teammate-message teammate_id="team-lead">\n'
            "Read the dispatch file and start the review\n"
            "</teammate-message>"
        )

        self.assertEqual(
            "Read the dispatch file and start the review",
            runtime_transcripts.prompt_title(CONFIG, prompt),
        )

    def test_an_ordinary_prompt_is_left_alone(self) -> None:
        self.assertEqual(
            "Fix the flaky Windows test",
            runtime_transcripts.prompt_title(
                CONFIG, "Fix the flaky Windows test\nsecond line ignored"
            ),
        )

    def test_markup_with_no_content_yields_nothing(self) -> None:
        # Better to fall through to another signal than to title a card "<>".
        for empty in ("<local-command-stdout></local-command-stdout>", "<a></a>", "   ", ""):
            with self.subTest(prompt=empty):
                self.assertIsNone(runtime_transcripts.prompt_title(CONFIG, empty))

    def test_the_title_is_bounded(self) -> None:
        self.assertLessEqual(
            len(runtime_transcripts.prompt_title(CONFIG, "x " * 400, limit=10) or ""), 11
        )

    def test_absolute_paths_collapse_to_their_basename(self) -> None:
        self.assertEqual(
            "Round 3 review of PR #268 (repo pendulum-of-despair)",
            runtime_transcripts.prompt_title(
                CONFIG, "Round 3 review of PR #268 (repo /Users/jane/repos/pendulum-of-despair)"
            ),
        )

    def test_urls_and_relative_paths_survive_whole(self) -> None:
        """The repo and PR number in a link are the informative part, and a
        relative path names a file the reader can actually find."""
        for text in (
            "Review https://github.com/spacedock-dev/bridge/pull/77 fully",
            "In bridge, read internal/server/server.go and its siblings",
            "Research how Goose works (github.com/block/goose)",
        ):
            with self.subTest(text=text):
                self.assertEqual(text, runtime_transcripts.prompt_title(CONFIG, text))

    def test_truncation_lands_on_a_word_boundary(self) -> None:
        prompt = "Take your time and tell all subagents the same"
        title = runtime_transcripts.prompt_title(CONFIG, prompt, limit=30)

        assert title is not None
        self.assertTrue(title.endswith("…"), title)
        self.assertFalse(title.rstrip("…").endswith(" "), title)
        # A word was not cut in half. Compare against the prompt's WORDS: against
        # the bare string this passes on "su", a substring of "subagents", so it
        # could not fail for the mistake it exists to catch.
        self.assertIn(title.rstrip("…").split()[-1], prompt.split())

    def test_short_slashy_text_is_not_treated_as_a_path(self) -> None:
        """Only long paths eat the title budget, and short slash-runs are
        usually not paths at all. `^/api/v1/users$` collapsed to `^users$`
        before the length floor existed."""
        for text in (
            "Match the regex ^/api/v1/users$ in the router",
            "cd ~/repos/compass && make test",
            "Serve /a/b from the CDN",
        ):
            with self.subTest(text=text):
                self.assertEqual(text, runtime_transcripts.prompt_title(CONFIG, text))

    def test_a_clip_does_not_end_on_an_orphaned_combining_mark(self) -> None:
        # The base character it belongs to was cut away, so it would render
        # against the ellipsis instead.
        decomposed = unicodedata.normalize("NFD", "é") * 60
        orphaned = [
            limit
            for limit in range(3, 60)
            if (kept := runtime_transcripts.clip(decomposed, limit).rstrip("…"))
            and unicodedata.combining(kept[-1])
        ]

        self.assertEqual([], orphaned)

    def test_a_hard_cut_does_not_leave_dangling_punctuation(self) -> None:
        # One long token has no boundary to fall back to, and ".…" reads as a
        # typo rather than as truncation.
        self.assertEqual("aaaa…", runtime_transcripts.clip("aaaa.bbbbbbbbbbbb", limit=5))

    def test_the_path_floor_is_a_boundary_not_a_vibe(self) -> None:
        # Mutation-checked: `<` vs `<=` on prompt_path_collapse_min_length
        # survived the suite, so the exact cutover is pinned here.
        def path_of_length(total: int) -> str:
            return "/" + "a" * (total - 4) + "/bc"  # 1 + (total - 4) + 3

        floor = CONFIG.prompt_path_collapse_min_length
        just_under, just_over = path_of_length(floor - 1), path_of_length(floor)

        self.assertEqual((floor - 1, floor), (len(just_under), len(just_over)))
        self.assertEqual(
            just_under,
            runtime_transcripts.shorten_paths(CONFIG, just_under),
            "collapsed below floor",
        )
        self.assertEqual(
            "bc", runtime_transcripts.shorten_paths(CONFIG, just_over), "not collapsed at floor"
        )


class UnderscoreWrapperTest(unittest.TestCase):
    """Codex names its wrappers with underscores, Claude with hyphens.

    The tag matcher's name class carried `[a-z0-9-]` and no underscore, so every
    Codex wrapper survived stripping and the title rendered as the bare tag.
    Measured across 24,636 user-role texts, adding `_` moves 312 titles, all of
    them Codex, and none of the 21,899 Claude ones.
    """

    def test_each_measured_codex_wrapper_shows_its_content(self) -> None:
        wrapped = {
            "recommended_plugins": "Here is a list of plugins",
            "environment_context": "2026-07-02",
            "subagent_notification": "the worker finished",
            "user_shell_command": "git checkout main",
            "turn_aborted": "The user interrupted the previous turn",
        }
        for tag, body in wrapped.items():
            with self.subTest(tag=tag):
                title = runtime_transcripts.prompt_title(CONFIG, f"<{tag}>\n{body}\n</{tag}>")

                self.assertEqual(body, title)

    def test_a_hyphenated_wrapper_is_unaffected(self) -> None:
        # The Claude side is the live consumer today, and it must not move.
        self.assertEqual(
            "Read the dispatch file",
            runtime_transcripts.prompt_title(
                CONFIG,
                '<teammate-message teammate_id="lead">\nRead the dispatch file\n</teammate-message>',
            ),
        )

    def test_the_accepted_cost_is_prose_that_looks_like_a_tag(self) -> None:
        """Widening the class means an underscored angle-bracket token in real
        prose is now dropped as markup, name and all — the hyphenated class
        always did this, and the underscore extends the reach. That is the
        price, and it was paid against evidence: zero of the 21,899 measured
        Claude prose texts moved, and the 312 that did were all bare tags."""
        self.assertEqual(
            "the is a template hole",
            runtime_transcripts.prompt_title(CONFIG, "the <some_placeholder> is a template hole"),
        )


class CopilotSubagentEventsTest(unittest.TestCase):
    """Copilot's pending subagents: which child a pill is, and what it runs on.

    An element is `{"name": str, "model": str | None}`, and the two come off one
    `subagent.started` object. That is the reason this is the source rather than
    the billing ledger, whose `agent_id` is `sidekick-<name>-<epoch ms>` against a
    published name of `<name>` — related by string construction only, so
    recovering one from the other is prefix-parsing, and a parsed match renders
    exactly like a read one.

    None means the event reported no model. It is never a guess.
    """

    def analyze(self, *events: dict[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text("".join(json.dumps(e) + "\n" for e in events))
            return runtime_transcripts.analyze_copilot_events(CONFIG, str(path))

    def started(self, agent_id: str, name: str, model: Any = "gpt-5.4-mini") -> dict[str, Any]:
        """One start event in the live shape: the name and the model in `data`,
        the identity at the top level beside a per-event `id` of its own."""
        return {
            "type": "subagent.started",
            "agentId": agent_id,
            "id": "event-" + agent_id,
            "data": {"toolCallId": agent_id, "agentName": name, "model": model},
        }

    def test_a_finished_child_retires_itself_and_not_whichever_started_first(self) -> None:
        # The pre-existing defect this ticket makes visible. `subagent.completed`
        # carries a *different* top-level `id` from `subagent.started` — measured
        # on a live store — so keying on `id` never matched and the unmatched-key
        # fallback below retired the oldest pill instead. With one child that is
        # accidentally right. With two it retires the wrong one, and now that a
        # pill carries a model, the wrong model goes with the wrong name.
        #
        # `agentId` is the one candidate that holds the same value across started,
        # completed and failed, and it is the same value the billing ledger's
        # `agent_id` column carries.
        #
        # The second child is the one that finishes, precisely because retiring
        # the oldest would also leave exactly one pill behind and pass.
        info = self.analyze(
            self.started("a1", "researcher", "gpt-5.4-mini"),
            self.started("b1", "reviewer", "gpt-5.6-terra"),
            {"type": "subagent.completed", "agentId": "b1", "id": "some-other-event-id"},
        )

        self.assertEqual(
            [{"name": "researcher", "model": "gpt-5.4-mini"}],
            list(info["pending_agents"].values()),
        )

    def test_a_failed_child_stops_being_pending(self) -> None:
        # `subagent.failed` was unhandled, so a child that failed kept its pill
        # for the rest of the session — measured live, on one that failed with
        # "No response generated". It would now keep a model badge with it,
        # advertising a model nothing is running on.
        info = self.analyze(
            self.started("a1", "researcher"),
            {
                "type": "subagent.failed",
                "agentId": "a1",
                "data": {"agentName": "researcher", "error": "No response generated"},
            },
        )

        self.assertEqual({}, info["pending_agents"])

    def test_a_start_event_with_no_model_reports_none_rather_than_a_name(self) -> None:
        info = self.analyze(
            {"type": "subagent.started", "agentId": "a1", "data": {"agentName": "researcher"}}
        )

        self.assertEqual(
            [{"name": "researcher", "model": None}], list(info["pending_agents"].values())
        )

    def test_no_unusable_model_value_reaches_the_payload_as_a_model(self) -> None:
        unusable: list[Any] = ["", "   ", 5, ["gpt-5"], {"name": "gpt-5"}, None, True]
        for value in unusable:
            with self.subTest(value=repr(value)):
                info = self.analyze(self.started("a1", "researcher", value))

                self.assertEqual(
                    [{"name": "researcher", "model": None}], list(info["pending_agents"].values())
                )

    def test_the_name_is_bounded_here_and_the_model_is_carried_raw(self) -> None:
        # A vendor model string is untrusted text on its way to the DOM, exactly
        # like the name beside it, and it lands on the surface with the least room
        # of any. It is bounded by the collector rather than here, to the width
        # `sessions` declares for every model on the payload — this module may not
        # import `sessions`, and a second literal cap beside the declared one is
        # how two caps drift apart. `tests/test_copilot.py` pins the bound.
        info = self.analyze(self.started("a1", "n" * 200, "m" * 100))
        pill = next(iter(info["pending_agents"].values()))

        self.assertEqual("n" * 70, pill["name"])
        self.assertEqual("m" * 100, pill["model"])

    def test_an_unhashable_identity_does_not_take_the_session_reading_with_it(self) -> None:
        # The key is a dict key and the record is untrusted, so a JSON list under
        # `agentId` would raise straight out of the analyzer — taking the title,
        # the prompt and the activity stamp of a session that was read fine.
        info = self.analyze(
            {"type": "user.message", "data": {"text": "hello"}},
            {"type": "subagent.started", "agentId": ["a1"], "data": {"agentName": "researcher"}},
        )

        self.assertEqual("hello", info["last_prompt"])
        self.assertEqual(
            [{"name": "researcher", "model": None}], list(info["pending_agents"].values())
        )


class MalformedRecordTest(unittest.TestCase):
    """Every harness payload is untyped JSON read off disk. `x.get("k") or {}`
    is not a guard: any truthy non-dict passes the `or` and the next .get()
    raises, killing the collector for that refresh."""

    HOSTILE: ClassVar[list[Any]] = [5, "str", [1, 2], {"k": "v"}, None, True]
    PLACEHOLDER = "__HOSTILE__"
    # One record per harness that the analyzer really does parse, used to prove
    # a hostile neighbour did not leave it unable to read anything else.
    WELL_FORMED: ClassVar[dict[str, dict[str, Any]]] = {
        "claude": {
            "type": "user",
            "uuid": "u1",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        },
        "codex": {"type": "event_msg", "payload": {"type": "user_message", "message": "hello"}},
        "gemini": {"type": "user", "content": "hello"},
        "copilot": {"type": "user.message", "data": {"content": "hello"}},
        "droid": {"type": "user", "message": {"content": "hello"}},
    }

    def substitute(self, template: Any, value: Any) -> Any:
        if template == self.PLACEHOLDER:
            return value
        if isinstance(template, dict):
            return {k: self.substitute(v, value) for k, v in template.items()}
        if isinstance(template, list):
            return [self.substitute(v, value) for v in template]
        return template

    def templates(self) -> list[tuple[str, Any, list[dict[str, Any]]]]:
        hostile = self.PLACEHOLDER
        return [
            (
                "claude",
                functools.partial(claude_data.analyze_transcript, CONFIG, STATE),
                [
                    {"type": "assistant", "message": {"usage": hostile, "content": hostile}},
                    {"type": "user", "message": {"content": hostile}},
                    {"type": "assistant", "message": hostile},
                    {"type": "last-prompt", "lastPrompt": hostile},
                ],
            ),
            (
                "codex",
                functools.partial(runtime_transcripts.analyze_codex_transcript, CONFIG),
                [
                    {"type": "event_msg", "payload": hostile},
                    {"type": "event_msg", "payload": {"type": "token_count", "info": hostile}},
                    {
                        "type": "event_msg",
                        "payload": {"type": "token_count", "info": {"last_token_usage": hostile}},
                    },
                    {"type": "event_msg", "payload": {"type": "user_message", "message": hostile}},
                    {
                        "type": "response_item",
                        "payload": {"type": "function_call", "name": hostile},
                    },
                ],
            ),
            (
                "gemini",
                functools.partial(runtime_transcripts.analyze_gemini_transcript, CONFIG),
                [
                    {"type": "gemini", "toolCalls": hostile, "tokens": hostile},
                    {"type": "user", "content": hostile},
                    {"$set": hostile},
                    {"$set": {"messages": hostile}},
                ],
            ),
            (
                "copilot",
                functools.partial(runtime_transcripts.analyze_copilot_events, CONFIG),
                [
                    {"type": "session.start", "data": hostile},
                    {"type": "session.start", "data": {"context": hostile}},
                    {"type": "user.message", "data": hostile},
                    {"type": "subagent.started", "data": hostile},
                    # The identity is a dict key, so an unhashable one here would
                    # raise rather than merely read wrong.
                    {"type": "subagent.started", "agentId": hostile, "data": {"agentName": "n"}},
                    {"type": "subagent.completed", "agentId": hostile},
                    # The permission pair. `requestId` is a dict key, so an
                    # unhashable one raises rather than merely reading wrong, and
                    # `permissionRequest` is branched on before anything under it
                    # is read — a list or a bare string there must not raise
                    # either.
                    {"type": "permission.requested", "data": hostile},
                    {
                        "type": "permission.requested",
                        "data": {"requestId": hostile, "permissionRequest": {"kind": "shell"}},
                    },
                    {
                        "type": "permission.requested",
                        "data": {"requestId": "r1", "permissionRequest": hostile},
                    },
                    {"type": "permission.completed", "data": hostile},
                    {"type": "permission.completed", "data": {"requestId": hostile}},
                ],
            ),
            (
                "droid",
                functools.partial(runtime_transcripts.analyze_droid_transcript, CONFIG),
                [
                    {"type": "message", "message": hostile},
                    {"type": "message", "message": {"role": "user", "content": hostile}},
                    {"type": "message", "message": {"role": "assistant", "content": hostile}},
                ],
            ),
        ]

    def test_a_hostile_record_neither_raises_nor_poisons_the_analyzer(self) -> None:
        """The contract is that one bad record does not take a collector
        offline, so surviving the record is only half of it: the analyzer must
        still parse the good records around it. "Did not raise" would also pass
        an analyzer that bailed out and returned nothing from then on.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.jsonl"
            for harness, analyzer, templates in self.templates():
                for template in templates:
                    for value in self.HOSTILE:
                        record = self.substitute(template, value)
                        with self.subTest(harness=harness, record=json.dumps(record)[:70]):
                            path.write_text(json.dumps(record) + "\n")
                            result = analyzer(str(path))

                            self.assertIsInstance(
                                result, dict, "a collector cannot use a non-dict result"
                            )
                            # The same analyzer, on the same file, with the bad
                            # record followed by a well-formed one.
                            path.write_text(
                                json.dumps(record) + "\n" + json.dumps(self.WELL_FORMED[harness])
                            )

                            self.assertIsInstance(analyzer(str(path)), dict)

    def test_typed_accessors(self) -> None:
        not_dicts: list[Any] = [5, "str", [1, 2], None, True]
        for value in not_dicts:
            self.assertEqual({}, records.as_dict(value))
            self.assertEqual({}, records.message_dict({"message": value}))
        self.assertEqual({"a": 1}, records.as_dict({"a": 1}))
        self.assertEqual({"a": 1}, records.message_dict({"message": {"a": 1}}))
        self.assertEqual({}, records.message_dict("not-a-record"))
        not_lists: list[Any] = [5, "str", {"k": 1}, None, True]
        for value in not_lists:
            self.assertEqual([], records.as_list(value))
        self.assertEqual([1, 2], records.as_list([1, 2]))

    def test_safe_text_replaces_controls_and_truncates(self) -> None:
        self.assertEqual("a b c", records.safe_text("a\x00b\nc", 10))
        self.assertEqual("abc", records.safe_text("abcdef", 3))

    def test_safe_text_strips_what_can_reorder_a_row(self) -> None:
        # A record that reorders its own rendering can make a row read as
        # something it does not say. Escapes rather than literals here for the
        # same reason ruff bans them in source: this file has to stay readable.
        for name, char in (
            ("zero-width space", "\u200b"),
            ("left-to-right mark", "\u200e"),
            ("right-to-left mark", "\u200f"),
            ("right-to-left override", "\u202e"),
            ("first strong isolate", "\u2068"),
            ("pop directional isolate", "\u2069"),
        ):
            with self.subTest(name=name):
                self.assertEqual("a b", records.safe_text(f"a{char}b", 10))

    def test_safe_text_keeps_the_joiners_that_words_are_spelled_with(self) -> None:
        # ZWNJ sits inside Persian and Indic words and ZWJ composes an emoji
        # sequence. Neither can reorder anything, and stripping them would break
        # a title in those scripts anywhere in the product.
        for name, text in (
            ("persian zwnj", "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"),
            ("emoji zwj", "\U0001f468\u200d\U0001f4bb"),
        ):
            with self.subTest(name=name):
                self.assertEqual(text, records.safe_text(text, 50))


class ReviewFixTest(unittest.TestCase):
    """Regressions found by the adversarial review passes on PR #7."""

    NOW = 1_700_000_000.0

    def test_reverse_lines_stays_linear_on_one_long_record(self) -> None:
        # chunk + carry per chunk made this quadratic: a 64 MB single-line
        # transcript took 0.9s, and large tool results do produce such records.
        #
        # Best-of-three per size, because a single sample is what made this
        # flaky on the Windows runner: one slow read reported a 9.0x ratio for
        # 4x the bytes on code that really scales at ~4x. The minimum is the
        # least contaminated estimate, and a quadratic regression cannot hide
        # in it.
        #
        # 16/64 MB rather than 4/16 so the measured time clears the floor below
        # on every runner. The floor stops a fast machine's near-zero baseline
        # from collapsing the budget into the noise, but it also caps
        # sensitivity: the comparison only fails a quadratic regression while
        # timings[0] > floor / 2, so the floor has to stay well under a real
        # measurement rather than replace it.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "long.jsonl"
            timings = []
            for megabytes in (16, 64):
                path.write_bytes(b"x" * (megabytes * 1024 * 1024))
                samples = []
                for _ in range(3):
                    start = time.perf_counter()
                    list(runtime_io.reverse_lines(make_config(), str(path)))
                    samples.append(time.perf_counter() - start)
                timings.append(min(samples))
        # Quadratic would be ~16x for 4x the bytes. Linear is ~4x, and a loaded
        # hosted macOS runner measured 8.3x (13 ms against 112 ms) on code that is
        # linear, so allow 12x: still a clear margin under a quadratic regression.
        self.assertLess(timings[1], max(timings[0], 0.01) * 12, f"non-linear: {timings}")


class CodexInstructionTest(unittest.TestCase):
    """The backward walk that finds Codex's prompt, and the line beneath it.

    Every fixture here is built to fail if the reader ever narrows back to one
    record shape or drops the turn floor, because both were tried and both look
    correct on a small fixture.
    """

    PAD = 8_000

    @staticmethod
    def _at(offset: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(1_780_000_000 + offset)) + "Z"

    @classmethod
    def _task_started(cls, offset: float) -> dict[str, Any]:
        return {
            "timestamp": cls._at(offset),
            "type": "event_msg",
            "payload": {"type": "task_started", "started_at": cls._at(offset)},
        }

    @classmethod
    def _user_old(cls, offset: float, text: str) -> dict[str, Any]:
        """CLI 0.142-0.146: the `event_msg`/`user_message` shape."""
        return {
            "timestamp": cls._at(offset),
            "type": "event_msg",
            "payload": {"type": "user_message", "message": text},
        }

    @classmethod
    def _user_item(cls, offset: float, text: str) -> dict[str, Any]:
        """CLI 0.149: `item_completed` with a `UserMessage` item."""
        return {
            "timestamp": cls._at(offset),
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {"type": "UserMessage", "content": [{"type": "text", "text": text}]},
            },
        }

    @classmethod
    def _user_response(cls, offset: float, text: str) -> dict[str, Any]:
        """The `response_item` shape, present in 456 of 457 local rollouts."""
        return {
            "timestamp": cls._at(offset),
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        }

    @classmethod
    def _commentary_old(cls, offset: float, text: str) -> dict[str, Any]:
        return {
            "timestamp": cls._at(offset),
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": text, "phase": "commentary"},
        }

    @classmethod
    def _commentary_item(cls, offset: float, text: str) -> dict[str, Any]:
        return {
            "timestamp": cls._at(offset),
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "AgentMessage",
                    "phase": "commentary",
                    "content": [{"type": "Text", "text": text}],
                },
            },
        }

    @classmethod
    def _padding(cls, offset: float) -> dict[str, Any]:
        # Stands in for the `reasoning` records whose encrypted blobs flood the
        # tail on a real rollout. The fixtures below use it to put the prompt
        # genuinely out of a tail read's reach.
        return {
            "timestamp": cls._at(offset),
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {"blob": "z" * 400}},
        }

    def scan(self, *entries: dict[str, Any]) -> dict[str, Any]:
        config, state = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-x.jsonl"
            path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
            return runtime_transcripts.codex_instruction(config, state, str(path))

    def test_prompt_eligibility_uses_the_source_body_not_the_clipped_title(self) -> None:
        for prompt, accepted in (
            ("continue", False),
            ("/clear", False),
            ("/release", True),
            ("Fix this:\nThe goal is to repair the broken export and verify the results", True),
        ):
            with self.subTest(prompt=prompt):
                result = self.scan(self._user_old(1, prompt))
                self.assertIs(accepted, result.get("prompt_states_work"))

    def test_the_prompt_is_found_where_a_tail_read_cannot_reach_it(self) -> None:
        # The reported bug, as a fixture. 171 of the 276 local rollouts holding a
        # genuine prompt (62.0%) have the newest one outside `tail_bytes`.
        config, _ = make_runtime()
        entries = [
            self._task_started(0),
            self._user_old(1, "Reconcile the harness registry with the docs"),
        ]
        entries += [self._padding(2) for _ in range(1_200)]

        config2, state = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-deep.jsonl"
            path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
            blob = path.read_bytes()
            # Only meaningful if the prompt really is out of reach. Pin that too.
            self.assertNotIn(b"Reconcile the harness", blob[-config.tail_bytes :])
            result = runtime_transcripts.codex_instruction(config2, state, str(path))

        self.assertEqual("Reconcile the harness registry with the docs", result["title"])

    def test_all_three_user_record_shapes_are_read(self) -> None:
        # Not belt-and-braces: `event_msg`/`user_message` is live on 255 of 457
        # rollouts and gone by CLI 0.149.1, `response_item` covers 456 of 457,
        # and `item_completed`/`UserMessage` is the ONLY path carrying the prompt
        # on 4 files. Dropping any one blinds the reader on a real population.
        for name, build in (
            ("event_msg/user_message", self._user_old),
            ("event_msg/item_completed/UserMessage", self._user_item),
            ("response_item/message/user", self._user_response),
        ):
            with self.subTest(shape=name):
                result = self.scan(self._task_started(0), build(1, "Rewrite the collector docs"))

                self.assertEqual("Rewrite the collector docs", result["title"])
                self.assertEqual("Rewrite the collector docs", result["last_prompt"])

    def test_both_preamble_shapes_are_read(self) -> None:
        # The record moved at CLI 0.149. Measured across all 457 local rollouts:
        # the `agent_message` path fires on 0 of the 88 files on 0.149.1, and the
        # `item_completed` path fires on 0 of the 306 files before it.
        for name, build in (
            ("event_msg/agent_message", self._commentary_old),
            ("event_msg/item_completed/AgentMessage", self._commentary_item),
        ):
            with self.subTest(shape=name):
                result = self.scan(
                    self._task_started(0),
                    self._user_old(1, "proceed"),
                    build(2, "I'll compare the two registries, then reconcile the docs"),
                )

                self.assertEqual(
                    {
                        "label": "agent",
                        "text": "I'll compare the two registries, then reconcile the docs",
                        "at": records.parse_ts(self._at(2)),
                    },
                    result["instruction"],
                )

    def test_line_two_quotes_the_turns_first_commentary_and_not_its_last(self) -> None:
        # First is a statement of intent, last is a progress report, and they
        # differ in 227 of 281 current turns (80.8%). A plain backward walk
        # returns the last one, which is what the floor and the overwrite order
        # exist to correct.
        result = self.scan(
            self._task_started(0),
            self._user_old(1, "carry on"),
            self._commentary_old(2, "I'm taking over task 5 in the isolated worktree"),
            self._commentary_old(3, "The full gate is clean. Coverage remains 85.2%"),
        )

        assert result["instruction"] is not None
        self.assertEqual(
            "I'm taking over task 5 in the isolated worktree", result["instruction"]["text"]
        )

    def test_a_previous_turns_commentary_never_stands_in_for_this_turns_intent(self) -> None:
        # 26-43% of turns carry no commentary of their own. Without the explicit
        # `task_started` floor the walk crosses into the previous turn and
        # publishes its intent under this turn's label, which reads as a
        # measurement and is not one.
        result = self.scan(
            self._task_started(0),
            self._user_old(1, "Rebuild the quota cache from the receipts"),
            self._commentary_old(2, "I'll rebuild the cache and re-run the fetch"),
            self._task_started(3),
            self._user_old(4, "proceed"),
        )

        assert result["instruction"] is not None
        self.assertEqual("earlier", result["instruction"]["label"])
        self.assertEqual("Rebuild the quota cache from the receipts", result["instruction"]["text"])

    def test_a_walk_that_never_reaches_a_floor_publishes_no_preamble(self) -> None:
        # No `task_started` anywhere means the turn boundary was never observed,
        # so no commentary in the file can be shown as THIS turn's intent.
        result = self.scan(
            self._commentary_old(0, "I'll start by reading the registry"),
            self._user_old(1, "go on"),
        )

        self.assertIsNone(result["instruction"])

    def test_a_floor_behind_the_newest_prompt_does_not_validate_a_stale_preamble(
        self,
    ) -> None:
        # The floor's own failure mode. This turn has not written `task_started`
        # yet, so the walk runs past the newest prompt, picks up the PREVIOUS
        # turn's commentary, and then reaches that turn's floor — which
        # `reached_floor` alone reads as proof the preamble is current. The
        # record order is the real one: prompt, floor, commentary, work.
        result = self.scan(
            self._user_old(0, "Rebuild the quota cache from the receipts"),
            self._task_started(1),
            self._commentary_old(2, "PREVIOUS TURN INTENT: I'll rebuild the cache"),
            self._user_old(3, "proceed"),
        )

        assert result["instruction"] is not None
        # Not "agent"/"PREVIOUS TURN INTENT…", which is a statement of intent
        # made BEFORE the operator's newest instruction.
        self.assertEqual("earlier", result["instruction"]["label"])
        self.assertEqual("Rebuild the quota cache from the receipts", result["instruction"]["text"])

    def test_this_turns_own_commentary_survives_a_later_floor(self) -> None:
        # The other side of the same gate, so the fix cannot degrade to "never
        # publish a preamble". Commentary NEWER than the newest prompt is this
        # turn's by construction, whichever turn's `task_started` the walk
        # eventually lands on.
        result = self.scan(
            self._user_old(0, "Rebuild the quota cache from the receipts"),
            self._task_started(1),
            self._user_old(2, "proceed"),
            self._commentary_old(3, "Next I'll re-run the fetch against the cache"),
        )

        assert result["instruction"] is not None
        self.assertEqual("agent", result["instruction"]["label"])
        self.assertEqual(
            "Next I'll re-run the fetch against the cache", result["instruction"]["text"]
        )

    def test_an_injected_shape_is_never_published_as_a_prompt(self) -> None:
        # The naive "newest user record" read is injected on 230 of 456 rollouts
        # (50.4%), and on 143 the ONLY user records are `<recommended_plugins>`.
        for text in (
            "<recommended_plugins>\nHere is a list of plugins",
            "# AGENTS.md instructions for the repository",
            "[Request interrupted by user]",
            "<environment_context>\ncwd: /w/proj",
        ):
            with self.subTest(text=text):
                result = self.scan(self._task_started(0), self._user_old(1, text))

                self.assertIsNone(result["title"])
                self.assertEqual("", result["last_prompt"])
                self.assertIsNone(result["instruction"])

    def test_nothing_at_all_is_published_when_no_genuine_prompt_exists(self) -> None:
        # The publish-nothing branch, and the reason it is not a shortfall: the
        # page's title chain is a `||`, so a junk value there does not merely
        # mislead once, it masks the project name for the life of the row. On the
        # local corpus this is 177 of 457 rollouts (38.7%).
        result = self.scan(
            self._task_started(0),
            self._user_old(1, "<recommended_plugins>\nHere is a list"),
            self._commentary_old(2, "I'll read the plugin list first"),
        )

        self.assertEqual(
            {
                "title": None,
                "last_prompt": "",
                "instruction": None,
                "prompt_states_work": False,
                "prompt_at": None,
            },
            result,
        )

    def test_a_compaction_boundary_stops_an_older_prompt_being_quoted(self) -> None:
        # Behind a boundary is context the turn no longer holds. Codex crosses one
        # in 28.2% of mid-flight cases, so this is the common path, not the edge.
        shapes: list[tuple[str, dict[str, Any]]] = [
            ("event_msg/compacted", {"type": "event_msg", "payload": {"type": "compacted"}}),
            (
                "item_completed/ContextCompaction",
                {
                    "type": "event_msg",
                    "payload": {"type": "item_completed", "item": {"type": "ContextCompaction"}},
                },
            ),
        ]
        for name, compaction in shapes:
            with self.subTest(shape=name):
                result = self.scan(
                    self._task_started(0),
                    self._user_old(1, "Rebuild the quota cache from the receipts"),
                    {**compaction, "timestamp": self._at(2)},
                    self._task_started(3),
                    self._user_old(4, "proceed"),
                )

                self.assertIsNone(result["instruction"])

    def test_codex_never_repeats_its_own_title_on_the_second_line(self) -> None:
        # Codex's line 1 IS the newest prompt, verbatim, so an "asked" line
        # beneath it would say the same thing twice and cost a row two lines.
        result = self.scan(
            self._task_started(0),
            self._user_old(1, "Reconcile the harness registry with the docs"),
            self._commentary_old(2, "I'll compare the two registries first"),
        )

        self.assertEqual("Reconcile the harness registry with the docs", result["title"])
        self.assertIsNone(result["instruction"])

    def test_a_slash_command_is_the_operators_intent_and_survives(self) -> None:
        # The deliberate carve-out: `<command-name>` is a WRAPPER, not an
        # injection. Rejecting it left 213 of 3,100 gated sessions with no
        # recoverable intent at all.
        result = self.scan(
            self._task_started(0),
            self._user_old(
                1,
                "<command-message>burndown is running</command-message>"
                "<command-name>/burndown</command-name><command-args>DRC-4264</command-args>",
            ),
        )

        self.assertEqual("/burndown DRC-4264", result["title"])

    def test_the_reading_is_cached_on_size_and_mtime_and_reread_when_either_moves(self) -> None:
        config, state = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-c.jsonl"
            first = [self._task_started(0), self._user_old(1, "Draft the release notes")]
            path.write_text("".join(json.dumps(e) + "\n" for e in first), encoding="utf-8")
            self.assertEqual(
                "Draft the release notes",
                runtime_transcripts.codex_instruction(config, state, str(path))["title"],
            )
            second = [*first, self._task_started(2), self._user_old(3, "Publish the release")]
            path.write_text("".join(json.dumps(e) + "\n" for e in second), encoding="utf-8")
            os.utime(path, (time.time() + 5, time.time() + 5))

            self.assertEqual(
                "Publish the release",
                runtime_transcripts.codex_instruction(config, state, str(path))["title"],
            )

    def test_a_malformed_rollout_reads_as_nothing_rather_than_raising(self) -> None:
        # Every field is untyped JSON from disk. One bad rollout must not take the
        # whole Codex collector with it.
        hostile: list[Any] = [5, "str", [1, 2], {"k": "v"}, None, True]
        for value in hostile:
            with self.subTest(value=repr(value)):
                self.scan(
                    {"type": "event_msg", "payload": value},
                    {"type": "event_msg", "payload": {"type": "item_completed", "item": value}},
                    {"type": "response_item", "payload": {"type": "message", "role": value}},
                    {"type": value, "payload": value},
                )

    def test_a_missing_file_reads_as_nothing(self) -> None:
        config, state = make_runtime()

        self.assertEqual(
            {
                "title": None,
                "last_prompt": "",
                "instruction": None,
                "prompt_states_work": False,
                "prompt_at": None,
            },
            runtime_transcripts.codex_instruction(config, state, "/nonexistent/rollout.jsonl"),
        )
