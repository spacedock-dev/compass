"""The repo-wide ISO-8601 rule: an offset-less stamp means UTC.

The rule only has teeth on a machine whose local time is not UTC: where it is,
a naive-means-local bug and a naive-means-UTC fix produce identical numbers, so
an assertion cannot tell them apart. That is why the original defect survived in
`parse_ts` and `quota._epoch` unnoticed, and it shapes this file into two layers.

Every assertion here states the contract directly, comparing against an
explicitly UTC-constructed instant. Those run everywhere, and they discriminate
on any developer machine that is not itself UTC, which is where the defect was
found.

On top of that, the tests marked with `needs_tz` **force** a non-UTC timezone, so
the discrimination does not depend on where the suite happens to run. That needs
`time.tzset`, which is Unix-only, so they skip on Windows rather than erroring:
the first version of this file called it unconditionally and took out the whole
`platform-tests` Windows job. The contract-level assertions still run there.
"""

from __future__ import annotations

import datetime as dt
import os
import shlex
import time
import unittest
from contextlib import contextmanager
from typing import TYPE_CHECKING

from compass_runtime import quota, records

if TYPE_CHECKING:
    from collections.abc import Iterator

# +08:00 with no DST, so the offset is the same in every season and a failure
# reads as a timezone bug rather than as a date-dependent flake. This is also
# the offset the defect was found on.
TZ = "Asia/Taipei"

# `time.tzset` exists on Unix only. Probed rather than keyed off `sys.platform`
# so the skip follows the capability the tests actually need.
HAS_TZSET = hasattr(time, "tzset")
needs_tz = unittest.skipUnless(
    HAS_TZSET, "time.tzset is Unix-only, so the process timezone cannot be forced here"
)


@contextmanager
def tz(name: str) -> Iterator[None]:
    """Run the body with `TZ` set, restoring both the variable and libc's cache.

    `time.tzset` is what actually moves `datetime.timestamp()`'s idea of local
    time; setting the environment variable alone changes nothing in a process
    that has already read it. Callers must carry `@needs_tz`.
    """
    before = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if before is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = before
        time.tzset()


class IsoEpochTest(unittest.TestCase):
    # 2026-01-02T03:04:05Z, chosen so every field differs and a transposition
    # cannot pass by symmetry.
    UTC_EPOCH = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC).timestamp()

    @needs_tz
    def test_a_naive_stamp_is_read_as_utc_not_as_local(self) -> None:
        # The regression. Under +08:00 the old `fromisoformat().timestamp()`
        # returned this instant minus eight hours, which is what pushed a live
        # turn out of the activity window.
        with tz(TZ):
            self.assertEqual(self.UTC_EPOCH, records.iso_epoch("2026-01-02T03:04:05"))

    @needs_tz
    def test_the_naive_reading_does_not_move_with_the_timezone(self) -> None:
        readings = []
        for name in ("UTC", TZ, "America/New_York"):
            with tz(name):
                readings.append(records.iso_epoch("2026-01-02T03:04:05"))
        self.assertEqual([self.UTC_EPOCH] * 3, readings)

    @needs_tz
    def test_an_explicit_offset_is_honoured_rather_than_overridden(self) -> None:
        # The common case in practice: every source measured on 2026-08-06 sends
        # one. A fix that forced UTC onto an aware stamp would break these.
        with tz(TZ):
            self.assertEqual(self.UTC_EPOCH, records.iso_epoch("2026-01-02T03:04:05+00:00"))
            self.assertEqual(self.UTC_EPOCH, records.iso_epoch("2026-01-02T11:04:05+08:00"))
            self.assertEqual(self.UTC_EPOCH, records.iso_epoch("2026-01-01T22:04:05-05:00"))

    @needs_tz
    def test_a_trailing_z_is_accepted(self) -> None:
        with tz(TZ):
            self.assertEqual(self.UTC_EPOCH, records.iso_epoch("2026-01-02T03:04:05Z"))

    def test_unusable_input_is_nothing_rather_than_a_guess(self) -> None:
        unusable: tuple[object, ...] = (
            "",
            "not a date",
            "2026-13-45T99:99:99",
            None,
            1_700_000_000,
            [],
            {},
        )
        for value in unusable:
            self.assertIsNone(records.iso_epoch(value), repr(value))


class ContractTest(unittest.TestCase):
    """The rule stated without forcing a timezone, so Windows checks it too.

    These compare against an explicitly UTC-constructed instant, which is the
    contract itself rather than a proxy for it. They cannot fail on a machine
    whose local time is already UTC, and they catch the defect on every machine
    that is not, which includes the one it was found on. The `needs_tz` tests
    above remove that dependency where the platform allows it; these are what
    keeps the Windows runner from asserting nothing at all.
    """

    NAIVE = "2026-01-02T03:04:05"
    EXPECTED = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC).timestamp()

    def test_every_reader_agrees_a_naive_stamp_is_the_utc_instant(self) -> None:
        # One assertion per reader, because the whole defect was two of the four
        # disagreeing with the other two.
        self.assertEqual(self.EXPECTED, records.iso_epoch(self.NAIVE))
        self.assertEqual(self.EXPECTED, records.parse_ts(self.NAIVE))
        self.assertEqual(self.EXPECTED, records.parse_utc_sql(self.NAIVE.replace("T", " ")))
        self.assertEqual(self.EXPECTED, quota._epoch(self.NAIVE))

    def test_a_naive_stamp_and_its_utc_spelling_are_the_same_instant(self) -> None:
        # The rule as an equality between two inputs rather than against a
        # constant, so it holds whatever the machine's clock is set to.
        for aware in (self.NAIVE + "Z", self.NAIVE + "+00:00"):
            self.assertEqual(records.iso_epoch(aware), records.iso_epoch(self.NAIVE), aware)
            self.assertEqual(records.parse_ts(aware), records.parse_ts(self.NAIVE), aware)

    def test_an_offset_is_never_overridden(self) -> None:
        # Tz-independent by construction: +08:00 and -05:00 name the same instant
        # as the Z spelling, whatever the reader's own zone.
        self.assertEqual(
            records.iso_epoch("2026-01-02T03:04:05Z"),
            records.iso_epoch("2026-01-02T11:04:05+08:00"),
        )
        self.assertEqual(
            records.iso_epoch("2026-01-02T03:04:05Z"),
            records.iso_epoch("2026-01-01T22:04:05-05:00"),
        )


class ParseTsTest(unittest.TestCase):
    """`parse_ts` is the transcript reader: Claude, Pi, turns, transcripts."""

    @needs_tz
    def test_a_naive_transcript_stamp_is_utc(self) -> None:
        with tz(TZ):
            self.assertEqual(
                dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC).timestamp(),
                records.parse_ts("2026-01-02T03:04:05"),
            )

    @needs_tz
    def test_it_agrees_with_the_shared_helper(self) -> None:
        # Both readers must not drift again, which is how they came to disagree.
        with tz(TZ):
            for value in ("2026-01-02T03:04:05", "2026-01-02T03:04:05Z", "bad"):
                self.assertEqual(records.iso_epoch(value), records.parse_ts(value), value)


class UsageSignalTest(unittest.TestCase):
    @staticmethod
    def _record(value: object) -> dict[str, object]:
        return {
            "type": "assistant",
            "message": {"usage": {"output_tokens": value}},
        }

    def test_claude_output_tokens_are_the_only_measured_signal(self) -> None:
        self.assertEqual(37, records.usage_signal(self._record(37), "claude"))
        self.assertEqual(0, records.usage_signal(self._record(0), "claude"))

    def test_a_claude_shaped_record_is_refused_for_every_other_scanned_harness(self) -> None:
        record = self._record(37)
        for harness in ("codex", "copilot", "gemini", "droid"):
            with self.subTest(harness=harness):
                self.assertIsNone(records.usage_signal(record, harness))

    def test_malformed_or_unmeasured_values_are_nothing_not_zero(self) -> None:
        malformed: tuple[object, ...] = (None, True, -1, 1.5, "37", {}, [])
        for value in malformed:
            with self.subTest(value=value):
                self.assertIsNone(records.usage_signal(self._record(value), "claude"))
        self.assertIsNone(
            records.usage_signal(
                {"type": "user", "message": {"usage": {"output_tokens": 37}}},
                "claude",
            )
        )
        self.assertIsNone(records.usage_signal({"type": "assistant"}, "claude"))


class ParseUtcSqlTest(unittest.TestCase):
    """`parse_utc_sql` reads Copilot's and Goose's SQLite text columns."""

    @needs_tz
    def test_sqlites_space_separated_default_spelling_is_read_as_utc(self) -> None:
        with tz(TZ):
            self.assertEqual(
                dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC).timestamp(),
                records.parse_utc_sql("2026-01-02 03:04:05"),
            )

    @needs_tz
    def test_an_offset_bearing_column_is_honoured(self) -> None:
        # Copilot's real store was measured sending these, so the naive branch is
        # a guard rather than the normal path.
        with tz(TZ):
            self.assertEqual(
                dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC).timestamp(),
                records.parse_utc_sql("2026-01-02 11:04:05+08:00"),
            )

    def test_unusable_input_is_zero_because_the_callers_window_on_it(self) -> None:
        for value in (None, "", "nonsense", 0):
            self.assertEqual(0, records.parse_utc_sql(value), repr(value))


class QuotaEpochTest(unittest.TestCase):
    """`quota._epoch` reads `resets_at`, which drives every reset countdown."""

    @needs_tz
    def test_a_naive_reset_stamp_is_utc(self) -> None:
        # An eight-hour error here moves the countdown and, since A5, the burn
        # projection that fires off `resetAt`.
        with tz(TZ):
            self.assertEqual(
                dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC).timestamp(),
                quota._epoch("2026-01-02T03:04:05"),
            )

    @needs_tz
    def test_an_offset_bearing_reset_stamp_is_honoured(self) -> None:
        with tz(TZ):
            self.assertEqual(
                dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC).timestamp(),
                quota._epoch("2026-01-02T03:04:05+00:00"),
            )

    @needs_tz
    def test_a_numeric_stamp_still_passes_through_unchanged(self) -> None:
        # The endpoint has sent both shapes; epoch seconds carry no timezone
        # question and must not be routed through the ISO reader.
        with tz(TZ):
            self.assertEqual(1_700_000_000.0, quota._epoch(1_700_000_000))
            self.assertIsNone(quota._epoch(0))
            self.assertIsNone(quota._epoch(True))


class StripPromptWrappersTest(unittest.TestCase):
    """The image marker is an envelope around a prompt, not a prompt.

    Both spellings were measured in the wild: Codex writes an XML-ish
    `<image …>` and Claude writes `[Image: source: …]` in plain text.
    """

    def test_a_codex_image_wrapper_yields_the_text_behind_it(self) -> None:
        # All 36 Codex records that open with one carried operator text after
        # it, so this is the case that rejecting on the tag would have lost.
        text = (
            '<image name=[Image #1] path="/var/folders/tmp/Screenshot.png"> </image> '
            "Where are you seeing this?"
        )

        self.assertEqual("Where are you seeing this?", records.strip_prompt_wrappers(text))

    def test_an_unquoted_attribute_with_spaces_and_hashes_does_not_stop_it(self) -> None:
        # Codex spells the name `[Image #1]` with no quotes at all, so an
        # attribute matcher that expected quoting would leave the tag in place.
        self.assertEqual("ok", records.strip_prompt_wrappers("<image name=[Image #1]> </image> ok"))

    def test_several_attachments_are_all_peeled(self) -> None:
        # One message can carry several screenshots, each its own marker.
        codex = '<image path="/a.png"></image><image path="/b.png"></image>look at both'
        claude = "[Image: source: /a.png] [Image: source: /b.png] look at both"

        self.assertEqual("look at both", records.strip_prompt_wrappers(codex))
        self.assertEqual("look at both", records.strip_prompt_wrappers(claude))

    def test_the_no_colon_spelling_is_peeled_too(self) -> None:
        # One record in 386 spells it this way, which is why the separator is a
        # character class rather than a literal colon.
        self.assertEqual("go", records.strip_prompt_wrappers("[Image source: /a.png] go"))

    def test_a_marker_only_message_strips_to_nothing(self) -> None:
        # 385 of 386 Claude `[Image:` records are exactly this.
        self.assertEqual("", records.strip_prompt_wrappers("[Image: source: /a.png]"))

    def test_ordinary_text_is_returned_unchanged_apart_from_trimming(self) -> None:
        self.assertEqual(
            "Fix the flaky test", records.strip_prompt_wrappers("  Fix the flaky test  ")
        )


class InjectedPromptTest(unittest.TestCase):
    """Which user records are the harness talking, rather than the operator.

    Every shape asserted here was counted in a local corpus: 2,737 Codex
    user-role texts across 457 rollouts, and 21,899 Claude user-role texts
    across 3,769 transcripts.
    """

    def test_every_measured_codex_tag_is_rejected(self) -> None:
        for tag in sorted(records._CODEX_USER_TAGS | records._CODEX_DEVELOPER_TAGS):
            with self.subTest(tag=tag):
                self.assertTrue(records.injected_prompt(f"<{tag}>body</{tag}>", "codex"))

    def test_every_measured_claude_tag_is_rejected(self) -> None:
        for tag in sorted(records._CLAUDE_USER_TAGS):
            with self.subTest(tag=tag):
                self.assertTrue(records.injected_prompt(f"<{tag}>body</{tag}>", "claude"))

    def test_the_measured_vocabulary_is_pinned_literally(self) -> None:
        """The two tests above iterate the very sets they assert against, so
        they stay green for any contents: delete the corpus's largest injection
        shape and nothing fails. These figures are the vocabulary itself, so a
        tag that goes missing or an unmeasured one that creeps in is caught.
        """
        self.assertEqual(12, len(records._CODEX_USER_TAGS))
        self.assertEqual(7, len(records._CODEX_DEVELOPER_TAGS))
        self.assertEqual(9, len(records._CLAUDE_USER_TAGS))
        self.assertEqual(
            {
                "bash-input",
                "bash-stdout",
                "local-command-stdout",
                "task-notification",
                "teammate-message",
            },
            (records._CODEX_USER_TAGS | records._CODEX_DEVELOPER_TAGS) & records._CLAUDE_USER_TAGS,
        )
        for tag in (
            "recommended_plugins",
            "skill",
            "subagent_notification",
            "user_shell_command",
            "codex_internal_context",
        ):
            self.assertIn(tag, records._CODEX_USER_TAGS)
        for tag in ("permissions", "multi_agent_mode", "collaboration_mode"):
            self.assertIn(tag, records._CODEX_DEVELOPER_TAGS)
        for tag in ("local-command-caveat", "system-reminder", "local-command-stderr"):
            self.assertIn(tag, records._CLAUDE_USER_TAGS)
        # The slash-command wrappers are absent on purpose; see the test below.
        for tag in ("command-message", "command-name", "command-args"):
            self.assertNotIn(tag, records._ANY_INJECTED_TAG)

    def test_a_slash_command_is_the_operator_speaking(self) -> None:
        """A slash command is what the person asked for, in harness markup.

        Rejecting it cost 1,493 of 15,109 `_turn_signal`-reachable Claude
        prompts, and `transcripts.prompt_title` renders these same bytes as
        `/review 1287`, so the predicate agreeing with it is the contract.
        """
        text = (
            "<command-message>review is running…</command-message>\n"
            "<command-name>/review</command-name>\n"
            "<command-args>1287</command-args>"
        )
        for harness in ("codex", "claude", "droid"):
            with self.subTest(harness=harness):
                self.assertFalse(records.injected_prompt(text, harness))

    def test_a_teammate_message_is_still_not_the_operator(self) -> None:
        # The measured cost is accepted, not overlooked: 563 local sessions
        # carry one and will show nothing from it.
        self.assertTrue(
            records.injected_prompt("<teammate-message>go</teammate-message>", "claude")
        )

    def test_an_attribute_bearing_tag_is_still_recognised(self) -> None:
        # The commonest injection of all carries attributes, so a matcher that
        # only understood `<name>` would miss 1,176 Claude records.
        self.assertTrue(
            records.injected_prompt(
                '<teammate-message teammate_id="lead">go</teammate-message>', "claude"
            )
        )

    def test_the_two_harness_vocabularies_do_not_transfer(self) -> None:
        """Codex underscores and Claude hyphens are different sets, and only
        five names are in both. Treating one list as universal would reject
        operator text on the harness that never sends that shape."""
        self.assertTrue(records.injected_prompt("<recommended_plugins>x", "codex"))
        self.assertFalse(records.injected_prompt("<recommended_plugins>x", "claude"))
        self.assertTrue(records.injected_prompt("<local-command-caveat>x", "claude"))
        self.assertFalse(records.injected_prompt("<local-command-caveat>x", "codex"))

    def test_an_unmeasured_harness_gets_the_union(self) -> None:
        # No evidence to narrow with, and every name in either set is machinery
        # no operator opens a prompt with.
        for tag in ("recommended_plugins", "local-command-caveat"):
            with self.subTest(tag=tag):
                self.assertTrue(records.injected_prompt(f"<{tag}>x", "droid"))

    def test_an_image_wrapper_is_stripped_rather_than_rejected(self) -> None:
        text = '<image name=[Image #1] path="/tmp/a.png"></image> Where are you seeing this?'

        self.assertFalse(records.injected_prompt(text, "codex"))

    def test_a_wrapper_around_an_injection_is_still_rejected(self) -> None:
        # Stripping happens first, so what the envelope carries is what decides.
        self.assertTrue(
            records.injected_prompt("[Image: source: /a.png] Stop hook feedback: retry", "claude")
        )

    def test_nothing_left_after_stripping_is_a_rejection(self) -> None:
        for empty in ("", "   ", "[Image: source: /a.png]", "<image></image>"):
            with self.subTest(text=empty):
                self.assertTrue(records.injected_prompt(empty, "claude"))

    def test_every_untagged_prefix_is_rejected_on_both_harnesses(self) -> None:
        """No tag regex can reach these: the harness writes them as prose."""
        for prefix in records._INJECTED_PROMPT_PREFIXES:
            for harness in ("codex", "claude"):
                with self.subTest(prefix=prefix, harness=harness):
                    self.assertTrue(records.injected_prompt(prefix + " and then some", harness))

    def test_warmup_is_matched_whole_not_as_a_prefix(self) -> None:
        # All 97 occurrences are exactly this word. As a prefix it would reject
        # a person asking for a warmup, which is a person saying something.
        self.assertTrue(records.injected_prompt("Warmup", "claude"))
        self.assertFalse(records.injected_prompt("Warmup the cache before the run", "claude"))

    def test_a_leading_invisible_character_does_not_defeat_every_branch(self) -> None:
        """The one degenerate class that failed OPEN.

        ``str.strip()`` removes whitespace and none of these is whitespace to
        Python, so a single one in front of a record defeated the leading-tag
        regex, the prose prefixes and the whole-body set at once — all three
        branches — and `injected_prompt` answered "the operator said this" about
        the harness's own machinery. `safe_text` strips most of the same set, but
        it runs after this on every path that reads a prompt.

        Falsifying edit: drop `_PROMPT_TRIM_RE` from `strip_prompt_wrappers`.
        """
        for name, lead in (
            ("BOM", "\ufeff"),
            ("zero-width space", "\u200b"),
            ("word joiner", "\u2060"),
            ("LRM", "\u200e"),
            ("RLO", "\u202e"),
            ("two of them", "\ufeff\u2060"),
            ("one either side of a space", "\ufeff \u2060"),
        ):
            for body in (
                "<local-command-caveat>x",
                "Stop hook feedback: retry",
                "Warmup",
            ):
                with self.subTest(lead=name, body=body):
                    self.assertTrue(records.injected_prompt(lead + body, "claude"))
        # And the other direction: the trim must not turn a real prompt into an
        # injection, which it would if it ate anything visible.
        self.assertFalse(records.injected_prompt("\ufeffFix the flaky Windows test", "claude"))

    def test_operator_text_survives(self) -> None:
        for text in (
            "Fix the flaky Windows test",
            "commit and push the changes",
            "1",
            # Markup that is not at the front is not an envelope.
            "Replace the <div> wrapper in the header",
            # An unlisted tag is somebody pasting markup, not the harness.
            "<RecceActionProvider> renders twice, find out why",
        ):
            with self.subTest(text=text):
                self.assertFalse(records.injected_prompt(text, "claude"))


class InstructionLineTest(unittest.TestCase):
    """The line-2 primitives: what counts as a continuation, and what publishes."""

    def test_a_short_acknowledgement_is_a_continuation_and_a_short_order_is_not(self) -> None:
        # The whole reason this is a word count rather than a character count.
        # "create a pr" is 11 characters and states work; "yes, go ahead and do
        # that" is 27 and states none. A character threshold picks the wrong one
        # of those two, which is how a "<40 chars" rule came to replace 402 good
        # lines to fix 81 bad ones.
        for text in ("proceed", "continue", "yes, do that", "1 and 2", "sure, proceed"):
            with self.subTest(text=text):
                self.assertTrue(records.bare_continuation(text))
        for text in (
            "resolve the blocker and create the pr",
            "Fix the flaky Windows test and report what moved",
        ):
            with self.subTest(text=text):
                self.assertFalse(records.bare_continuation(text))

    def test_a_reading_with_no_label_is_never_published(self) -> None:
        # The label is what makes a second-hand or stale line survivable, so an
        # unlabelled one is not a degraded reading — it is a claim the runtime
        # cannot support, and there is no branch that may emit one.
        self.assertIsNone(records.instruction_line("", "real text", 100.0))
        self.assertIsNone(records.instruction_line("agent", "", 100.0))
        self.assertIsNone(records.instruction_line("agent", None, 100.0))
        self.assertIsNone(records.instruction_line("agent", "   ", 100.0))

    def test_the_text_is_bounded_and_scrubbed_like_every_other_vendor_string(self) -> None:
        # `last_prompt` beside it is published raw at the collector; this field
        # is not, and the difference is deliberate. The value is untrusted
        # transcript text on its way to the DOM.
        hostile = "drop\u202ethe bidi\x07 override " + "x" * 400
        line = records.instruction_line("earlier", hostile, 12.0)

        assert line is not None
        # Cap plus one, not the cap: the ellipsis `clip` appends sits one past
        # the width it cut to, and scrubbing at the cap takes it back off. This
        # is the bound, not the rendered width \u2014 every real caller hands this
        # already-clipped text, so one character of headroom is what keeps the
        # truncation marked. See the docstring, and line 1's identical `+ 1`.
        self.assertEqual(records.INSTRUCTION_CAP_CHARS + 1, len(line["text"]))
        self.assertNotIn("\u202e", line["text"])
        self.assertNotIn("\x07", line["text"])
        self.assertEqual("earlier", line["label"])
        self.assertEqual(12.0, line["at"])

    def test_a_clipped_line_keeps_the_ellipsis_that_marks_it_clipped(self) -> None:
        # 29 of 1,906 published Claude lines ended in an unmarked mid-token cut,
        # because `clip` appends `\u2026` AFTER cutting to the cap and the scrub then
        # trimmed exactly that character off. A cut with no marker reads as the
        # operator having written a truncated sentence.
        clipped = "x" * records.INSTRUCTION_CAP_CHARS + "\u2026"
        line = records.instruction_line("asked", clipped, 12.0)

        assert line is not None
        self.assertTrue(line["text"].endswith("\u2026"), line["text"][-20:])

    def test_an_unusable_stamp_is_published_as_zero_rather_than_as_now(self) -> None:
        # The page renders an age from this. A missing stamp read as the current
        # time would label a two-hour-old line "earlier, 0s", which is the one
        # reading the label exists to prevent.
        for stamp in (None, 0, -5.0):
            with self.subTest(stamp=stamp):
                line = records.instruction_line("agent", "text", stamp)
                assert line is not None
                self.assertEqual(0, line["at"])


class RedactSecretsTest(unittest.TestCase):
    """Credential shapes on their way to the DOM.

    Every value below is synthetic and deliberately obvious: a documented
    placeholder, or a real prefix followed by a run of one letter. Nothing in
    this repository — test, fixture, capture or commit message — may carry a
    value that would work, which is the whole reason the shape list was measured
    by counting rather than by reading.
    """

    # (name, a fake of that shape, what the operator should be shown instead)
    FAKES = (
        ("anthropic api key", "sk-ant-api03-" + "A" * 95, "sk-ant-…REDACTED"),
        ("anthropic oauth token", "sk-ant-oat01-" + "B" * 95, "sk-ant-…REDACTED"),
        ("openai key", "sk-" + "C" * 48, "sk-…REDACTED"),
        ("stripe secret key", "sk_live_" + "U" * 24, "sk_live_…REDACTED"),
        ("stripe restricted key", "rk_test_" + "U" * 24, "rk_test_…REDACTED"),
        # The documented AWS placeholder, and its session-credential sibling.
        ("aws access key", "AKIAIOSFODNN7EXAMPLE", "AKIA…REDACTED"),
        ("aws session key", "ASIAIOSFODNN7EXAMPLE", "ASIA…REDACTED"),
        ("github pat", "ghp_" + "D" * 36, "ghp_…REDACTED"),
        ("github oauth", "gho_" + "E" * 36, "gho_…REDACTED"),
        ("github fine-grained pat", "github_pat_" + "V" * 60, "github_pat_…REDACTED"),
        ("gitlab pat", "glpat-" + "W" * 20, "glpat-…REDACTED"),
        ("npm token", "npm_" + "X" * 36, "npm_…REDACTED"),
        ("linear api key", "lin_api_" + "Z" * 40, "lin_api_…REDACTED"),
        # The cued shape. What names the kind is the key name in front of the
        # value, so that is what survives instead of a fixed count of leading
        # characters, and `AKIA…REDACTED` stops implying the pair is covered.
        (
            "aws secret access key",
            "aws_secret_access_key = " + "Q" * 40,
            "aws_secret_access_key = …REDACTED",
        ),
        ("slack bot token", "xoxb-" + "0" * 12 + "-" + "0" * 12 + "-" + "F" * 24, "xoxb-…REDACTED"),
        ("slack app token", "xapp-1-" + "Y" * 20, "xapp-…REDACTED"),
        ("posthog key", "phc_" + "G" * 43, "phc_…REDACTED"),
        ("google api key", "AIza" + "H" * 35, "AIza…REDACTED"),
        ("jwt", "eyJ" + "I" * 20 + "." + "J" * 20 + "." + "K" * 20, "eyJ…REDACTED"),
        (
            "pem private key",
            "-----BEGIN RSA PRIVATE KEY-----\n" + "L" * 64 + "\n-----END RSA PRIVATE KEY-----",
            "-----BEGIN …REDACTED",
        ),
        (
            "connection string",
            "postgres://someone:NOTAREALPASSWORD@db.example:5432/app",
            "postgres://…REDACTED@db.example:5432/app",
        ),
        # The `cued` shape: no shape of its own, so the cue in front names it and
        # stays, and only the value goes (review, 2026-10-03).
        ("bearer value", "Authorization: Bearer placeholder123", "Authorization: Bearer …REDACTED"),
    )

    # Every cue the `cued` shape reads, each with a synthetic value, and the forms it
    # leaves alone: code that assigns, prose that merely names a cue, and a short word.
    CUED = (
        ("password=placeholder1", "password=…REDACTED"),
        ('Password="placeholder1"', 'Password="…REDACTED"'),
        ("passwd=placeholder1", "passwd=…REDACTED"),
        ("pwd=placeholder1", "pwd=…REDACTED"),
        ("secret=placeholder1", "secret=…REDACTED"),
        ("token=placeholder1", "token=…REDACTED"),
        ("api_key=placeholder1", "api_key=…REDACTED"),
        ("APIKEY=placeholder1", "APIKEY=…REDACTED"),
        ("DB_PASSWORD=placeholder1 make run", "DB_PASSWORD=…REDACTED make run"),
        ("GH_TOKEN=placeholder1", "GH_TOKEN=…REDACTED"),
        ("APP_SECRET=placeholder1", "APP_SECRET=…REDACTED"),
        ("STRIPE_KEY=placeholder1", "STRIPE_KEY=…REDACTED"),
        # The names the final review found the first spelling missed (2026-10-03).
        ("MY_DB_PASSWORD=placeholder1", "MY_DB_PASSWORD=…REDACTED"),
        ("GITHUB_API_TOKEN=placeholder1", "GITHUB_API_TOKEN=…REDACTED"),
        ("OPENAI_API_KEY=placeholder1", "OPENAI_API_KEY=…REDACTED"),
        ("AWS_SESSION_TOKEN=placeholder1", "AWS_SESSION_TOKEN=…REDACTED"),
        ("PGPASSWORD=placeholder1", "PGPASSWORD=…REDACTED"),
        ("db_password=placeholder1", "db_password=…REDACTED"),
        ("my_api_key=placeholder1", "my_api_key=…REDACTED"),
        ('{"password": "place holder1"}', '{"password": "…REDACTED"}'),
        ("password: placeholder1", "password: …REDACTED"),
        ("--password placeholder1", "--password …REDACTED"),
        ("--token=placeholder1", "--token=…REDACTED"),
        ("DB_PASSWORD = placeholder1", "DB_PASSWORD = …REDACTED"),
        ("DB_PASSWORD='place holder 1'", "DB_PASSWORD='…REDACTED'"),
        ("password=placeholder", "password=…REDACTED"),
        # Bearer: after `Authorization:` anything, otherwise a credential-like value.
        ("Authorization: Bearer abc", "Authorization: Bearer …REDACTED"),
        ("bearer placeholder1placeholder2", "bearer …REDACTED"),
    )
    CUED_LEFT_ALONE = (
        "token = next_token()",
        "the tokens are fine",
        "sort_key=name",
        "the bearer of it",
        "http://127.0.0.1:4553",
        # Prose and code that names a value rather than holding one.
        "Add bearer auth to the API client",
        "bearer placeholder1",
        "secret=staging",
        "token=$NEXT",
        "TOKEN=${GH_TOKEN}",
        "password = None",
        "api_key = os.environ",
        "secret = self.secret",
        "Monkey: banana",
        "primary key: id",
        "secret: the plan",
        "PWD=/home/someone/repo",
    )

    def test_a_cued_value_with_no_shape_is_masked_and_its_cue_kept(self) -> None:
        for fake, expected in self.CUED:
            with self.subTest(fake=fake):
                self.assertEqual(expected, records.redact_secrets(fake))
        for text in self.CUED_LEFT_ALONE:
            with self.subTest(text=text):
                self.assertEqual(text, records.redact_secrets(text))

    def test_every_measured_shape_is_replaced_by_a_visible_marker(self) -> None:
        for name, fake, expected in self.FAKES:
            with self.subTest(shape=name):
                self.assertEqual(expected, records.redact_secrets(fake))

    def test_the_words_around_a_credential_survive_it(self) -> None:
        # Dropping the line would lose the instruction, which is the useful part
        # and the whole reason the card carries one.
        line = f"rotate {'ghp_' + 'M' * 36} then push the branch"
        self.assertEqual("rotate ghp_…REDACTED then push the branch", records.redact_secrets(line))

    def test_the_marker_is_visible_rather_than_silent(self) -> None:
        # An operator who cannot see that something was removed never learns
        # their prompt history holds a live key, and so never rotates it.
        self.assertIn("REDACTED", records.redact_secrets("AIza" + "N" * 35))

    def test_two_credentials_on_one_line_are_both_replaced(self) -> None:
        line = f"{'sk-ant-api03-' + 'P' * 90} and {'ghp_' + 'Q' * 36}"
        redacted = records.redact_secrets(line)
        self.assertEqual("sk-ant-…REDACTED and ghp_…REDACTED", redacted)

    def test_what_the_filter_must_leave_alone(self) -> None:
        # Each of these is a thing that really appears in a prompt and really
        # looks like a secret to a careless rule. A blanked instruction line is
        # the cost of getting one of them wrong.
        for name, text in (
            ("git sha", "revert e83c5163316f89bfbde7d9ab23ca2e25604af290 and rerun"),
            ("uuid", "session 9f3c1a55-0000-4000-8000-000000000000 is stuck"),
            ("base64 in a diff", "+ QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlq=="),
            ("long path", "/Users/x/repos/p/compass/skills/compass/compass_runtime/records.py"),
            ("prose with gh", "check the highlight tonight and the light in the right place"),
            ("hyphenated token", "dask-scheduler-configuration-defaults-file-name"),
            ("plain url", "see https://github.com/spacedock-dev/marketplace/pull/223"),
            ("scp remote", "git@github.com:spacedock-dev/marketplace.git"),
            ("ssh url", "ssh://git@github.com/spacedock-dev/marketplace.git"),
            # The dashboard's own address. A port reads as `host:number` and the
            # `@` test lets it through the gate, so this is the false positive
            # that would have blanked the most instruction lines in this repo.
            ("dashboard url", "open http://127.0.0.1:4553/api/data?all=1"),
            ("url with a user and no password", "clone https://someone@github.com/o/r.git"),
            ("image tag", "docker run postgres:16 with the seed applied"),
            ("hex blob", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
            ("iso stamp", "2026-08-27T07:15:44.002Z"),
        ):
            with self.subTest(name=name):
                self.assertEqual(text, records.redact_secrets(text))

    def test_a_shape_inside_a_longer_token_is_left_alone(self) -> None:
        # The anchor. Without it an ordinary hyphenated identifier that happens
        # to contain `sk-` reads as a key and the line is blanked.
        inside = "not-a-sk-" + "R" * 40
        self.assertEqual(inside, records.redact_secrets(inside))

    def test_an_unambiguous_key_is_redacted_whatever_precedes_it(self) -> None:
        # The anchor used to fail OPEN: one character in front of a key and the
        # whole thing published verbatim, same length, no marker. Anyone who has
        # pasted a key onto the end of a word had published it. Above the length
        # where a shape has no innocent reading the anchor no longer applies.
        for lead in ("x", "1", "_", "-"):
            for name, fake in (
                ("anthropic", "sk-ant-api03-" + "A" * 100),
                ("aws", "AKIAIOSFODNN7EXAMPLE"),
                ("github fine-grained", "github_pat_" + "C" * 40),
            ):
                with self.subTest(shape=name, lead=lead):
                    redacted = records.redact_secrets(lead + fake)
                    self.assertIn("REDACTED", redacted)
                    self.assertLess(len(redacted), len(lead + fake))
        # And below it the anchor still holds, which is what rejects 78 of the
        # 177 `sk-` candidates in the local store.
        short = "x" + "sk-ant-" + "B" * 20
        self.assertEqual(short, records.redact_secrets(short))

    def test_a_rejected_span_does_not_shield_a_later_credential(self) -> None:
        # `re.sub` resumes at the end of the span it just declined, so a
        # near-miss swallowed the correctly anchored key behind it and both
        # published. Scanning resumes one character in instead.
        line = "x" + "sk-" + "R" * 40 + " then AKIAIOSFODNN7EXAMPLE"
        redacted = records.redact_secrets(line)
        self.assertIn("AKIA…REDACTED", redacted)
        self.assertNotIn("EXAMPLE", redacted)
        self.assertIn("R" * 40, redacted, "the near-miss itself is not a credential")

    def test_a_url_credential_with_no_username_is_redacted(self) -> None:
        # `redis://:password@host` is the form Redis documents, and the username
        # half required a character, so every one of these published the whole
        # password. NOTAREALPASSWORD is the fixture the connection-string fake
        # above uses.
        for scheme in ("redis", "rediss", "postgres", "postgresql", "mysql", "mongodb", "amqp"):
            with self.subTest(scheme=scheme):
                line = f"connect {scheme}://:NOTAREALPASSWORD@db.example:6379/0"
                redacted = records.redact_secrets(line)
                self.assertNotIn("NOTAREALPASSWORD", redacted)
                self.assertEqual(
                    f"connect {scheme}://…REDACTED@db.example:6379/0",
                    redacted,
                )

    def test_a_url_credential_clipped_before_the_at_sign_is_redacted(self) -> None:
        # A title is cut at 80 characters and `last_prompt` at 140, and the cut
        # can land between the password and the `@` the shape was anchored on.
        # Two corpus records sit at the title cap. Every clip that keeps any of
        # the password must still be marked.
        line = "redis://someone:NOTAREALPASSWORD@db.example:6379/0"
        for clip in range(line.index(":", 8) + 2, line.index("@") + 2):
            with self.subTest(clip=clip):
                redacted = records.redact_secrets(line[:clip])
                self.assertIn("REDACTED", redacted)
                self.assertNotIn("NOTAREALPASSWORD"[: clip - 16], redacted)

    def test_a_host_and_port_at_the_end_of_a_line_is_left_alone(self) -> None:
        # The guard on the clipped-`@` arm. Without it every address ending in a
        # port reads as a credential, and the dashboard's own URL is in prompts
        # here constantly. The `@` puts each of these on the slow path, so the
        # pattern is doing the work rather than the gate.
        for name, text in (
            ("dashboard url at the end", "mail me@example.com then open http://127.0.0.1:4553"),
            ("https with a port", "ping ops@example.com about https://example.com:8443"),
            ("scheme, port and a path", "me@x.io said http://127.0.0.1:4553/api/data?all=1"),
            ("ssh url", "ssh://git@github.com/o/r.git beside http://127.0.0.1:4553"),
        ):
            with self.subTest(name=name):
                self.assertEqual(text, records.redact_secrets(text))

    def test_a_separator_inside_a_key_leaves_its_tail_beside_the_marker(self) -> None:
        # The residual, pinned rather than described. A control character
        # through the middle of a key defeats the match on the whole key, and
        # `safe_text` turns that character into a space: the head still matches
        # on its own and redacts, and the tail behind it is a run with no prefix
        # to match on. Both SECURITY.md and the design doc used to say the match
        # was defeated and stop there, which reads as "nothing is published".
        split = "sk-ant-api03-" + "A" * 40 + "\x01" + "B" * 75
        published = records.safe_text(f"rotate {split} now", 400)
        self.assertIn("sk-ant-…REDACTED", published)
        self.assertEqual(75, published.count("B"))
        self.assertNotIn("A" * 4, published, "the head in front of the separator still redacts")

    def test_a_body_longer_than_the_format_issues_stops_at_the_cap(self) -> None:
        # Greedy hyphen-inclusive bodies over-reached: a key glued to the words
        # behind it took the words with it, 85 characters matched with 71 of
        # them instruction. The cap is the vendor's own longest key, so what a
        # run past it can cost is bounded.
        run = "sk-ant-oat01-" + "A" * 40 + "-then" * 40
        redacted = records.redact_secrets(run)
        self.assertIn("sk-ant-…REDACTED", redacted)
        # `sk-ant-` plus the 110-character cap is the most one match can eat, so
        # everything past it stands. Without the cap the whole run was one match.
        survivors = redacted[len("sk-ant-…REDACTED") :]
        self.assertGreaterEqual(len(survivors), len(run) - 117)
        self.assertTrue(survivors.endswith("-then"))

    def test_a_key_of_each_vendors_documented_length_is_fully_redacted(self) -> None:
        # The other half of the cap: it may not fall short of a real key, or the
        # tail past it publishes. One synthetic key per shape at the longest
        # length that vendor issues, asserted to leave no body behind.
        for name, fake in (
            ("anthropic", "sk-ant-api03-" + "A" * 95),
            ("openai project", "sk-proj-" + "C" * 156),
            ("openrouter", "sk-or-v1-" + "c" * 64),
            ("stripe", "sk_live_" + "U" * 99),
            ("github classic", "ghp_" + "D" * 36),
            ("github fine-grained", "github_pat_" + "V" * 82),
            ("gitlab", "glpat-" + "W" * 50),
            ("slack app", "xapp-1-A" + "0" * 10 + "-" + "1" * 13 + "-" + "F" * 64),
            ("posthog", "phc_" + "G" * 43),
            ("linear", "lin_api_" + "Z" * 40),
        ):
            with self.subTest(shape=name):
                redacted = records.redact_secrets(f"rotate {fake} today")
                self.assertTrue(redacted.startswith("rotate "))
                self.assertTrue(
                    redacted.endswith("\u2026REDACTED today"),
                    "characters of the key survived past the cap",
                )

    def test_the_marker_is_never_published_half_written(self) -> None:
        # Measured on `last_prompt`: a key starting at lead 124 to 131 published
        # a marker with its tail cut off, and one at 132 or beyond published the
        # kept prefix and no marker at all — a row ending in `sk-ant-`, which
        # reads as a truncated key rather than a redacted one. No key body was
        # published at any lead, so this is about what the operator can believe.
        key = "sk-ant-api03-" + "Z" * 95
        for lead in range(110, 141):
            with self.subTest(lead=lead):
                published = records.safe_text("x" * lead + " " + key, 140)
                self.assertNotIn("Z", published)
                self.assertTrue(
                    published.endswith("sk-ant-…REDACTED"),
                    "the marker is cut in half or missing entirely",
                )

    def test_a_pem_body_does_not_survive_the_control_character_scrub(self) -> None:
        # `safe_text` substitutes a space for every line break BEFORE the filter
        # runs, so a body class holding `\r\n` and not a space could not match
        # one character of a body on the path that publishes it: the header
        # redacted and the whole key went out behind it.
        body = "\n".join(["L" * 64] * 6)
        pem = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----"
        published = records.safe_text(pem, 600)
        self.assertEqual("-----BEGIN …REDACTED", published)

    def test_an_indented_pem_body_does_not_survive_either(self) -> None:
        # The separator, not the body class. A block pasted inside a fenced
        # example or a YAML value keeps its indent once the line break becomes a
        # space, and at an indent of 4 the run chain broke after the header: 6
        # body lines and 468 characters published behind the marker. Probed at
        # the indents either side of where it used to break.
        for indent in (0, 1, 3, 4, 8, 20):
            with self.subTest(indent=indent):
                pad = " " * indent
                body = "\n".join([pad + "L" * 64] * 6)
                pem = (
                    f"{pad}-----BEGIN RSA PRIVATE KEY-----\n{body}\n"
                    f"{pad}-----END RSA PRIVATE KEY-----"
                )
                published = records.safe_text(pem, 600)
                self.assertNotIn("L" * 16, published)
                self.assertIn("…REDACTED", published)

    def test_a_header_with_no_key_behind_it_costs_no_sentence(self) -> None:
        # The reason the body is base64 runs rather than a class holding the
        # space: all 1,058 local PEM occurrences are a header naming the format
        # with prose behind it. A PEM line is 64 characters and a word is not.
        line = "-----BEGIN RSA PRIVATE KEY----- appears in the documentation for it"
        self.assertEqual(
            "-----BEGIN …REDACTED appears in the documentation for it",
            records.redact_secrets(line),
        )

    def test_a_bare_forty_character_run_is_not_an_aws_secret(self) -> None:
        # The cue is what makes the shape decidable. Without it a git SHA, a
        # base64 chunk of a diff and a path segment all read as a secret key,
        # and the filter would blank an instruction line on every one.
        for name, text in (
            ("base64 blob", "paste " + "Q" * 40 + " into the form"),
            ("a nearby but unrelated word", "the secret is " + "Q" * 40),
            ("a cue with no value behind it", "set aws_secret_access_key from the vault"),
        ):
            with self.subTest(name=name):
                self.assertEqual(text, records.redact_secrets(text))

    def test_a_credential_is_redacted_before_the_line_is_bounded(self) -> None:
        # Bounding first would publish the head of the key: a hundred characters
        # of it fit inside the cap, and the tail that fell off is what stops the
        # shape matching afterwards.
        line = "x" * 100 + " " + "sk-ant-api03-" + "S" * 95
        # What bounding first would have published: the cap falls inside the key.
        self.assertIn("S" * 20, line[: records.LAST_PROMPT_CAP_CHARS])

        bounded = records.safe_text(line, records.LAST_PROMPT_CAP_CHARS)
        self.assertIn("sk-ant-…REDACTED", bounded)
        self.assertNotIn("S", bounded)
        self.assertLessEqual(len(bounded), records.LAST_PROMPT_CAP_CHARS)

    def test_the_instruction_line_carries_no_credential(self) -> None:
        # The surface PR #223 added, and the one that widened the exposure.
        line = records.instruction_line("asked", "deploy with " + "sk-ant-oat01-" + "T" * 95, 12.0)
        assert line is not None
        self.assertEqual("deploy with sk-ant-…REDACTED", line["text"])

    def test_the_gate_reaches_every_shape_on_the_list(self) -> None:
        # The literal gate is an optimization, and an optimization in front of a
        # security filter is a way to ship a measured shape switched off. Each
        # alternative gets a fake here, so a shape added without a hint fails.
        listed = {name for name, _, _, _ in records._SECRET_SHAPES}
        covered = set()
        for _name, fake, expected in self.FAKES:
            match = records._SECRET_RE.search(fake)
            assert match is not None
            covered.add(match.lastgroup)
            with self.subTest(shape=match.lastgroup):
                self.assertEqual(expected, records.redact_secrets(fake))
        self.assertEqual(listed, covered)


def mask(line: str) -> str:
    """A command line masked the way a check line is: shell words, one by one."""
    return " ".join(records.mask_words(shlex.split(line)))


class MaskCommandTest(unittest.TestCase):
    def test_the_string_masker_that_split_on_whitespace_is_gone(self) -> None:  # V9
        # It leaked a quoted value's tail; the check line masks shell words.
        self.assertFalse(hasattr(records, "mask_command"))

    """The credential forms a shape filter cannot recognise, masked in a command line.

    DEC-23 item 5: a short password matches no credential shape, so a check's
    command line is masked by FORM before `redact_clip` runs over it. Every
    value here is synthetic; what matters is that it never survives.
    """

    VALUE = "hunter2x"

    def test_an_environment_assignment_keeps_its_name_and_loses_its_value(self) -> None:
        masked = mask(f"PGPASSWORD={self.VALUE} psql -h db pytest")
        self.assertNotIn(self.VALUE, masked)
        self.assertIn("PGPASSWORD=", masked)

    def test_a_password_flag_in_every_spelling_loses_its_value(self) -> None:
        for line in (
            f"mysql -p {self.VALUE} -e 'select 1'",
            f"mysql -p{self.VALUE} -e 'select 1'",
            f"tool --password {self.VALUE} run",
            f"tool --password={self.VALUE} run",
        ):
            with self.subTest(line=line):
                self.assertNotIn(self.VALUE, mask(line))

    def test_a_url_with_a_user_and_password_keeps_the_user_and_loses_the_password(self) -> None:
        for line in (
            f"pytest --db postgres://app:{self.VALUE}@localhost/test",
            f"pytest --db app:{self.VALUE}@localhost:5432",
        ):
            with self.subTest(line=line):
                masked = mask(line)
                self.assertNotIn(self.VALUE, masked)
                self.assertIn("app:", masked)

    def test_a_password_holding_whitespace_is_masked_to_the_last_at(self) -> None:
        # DRC-4703: the password ran `\S*`, so a space inside one shell word
        # stopped it short of the `@` and the whole password was published.
        for word in (
            "app:EXAMPLEaa EXAMPLEbb@db",
            "postgres://app:EXAMPLEaa EXAMPLEbb@db/x",
            "postgres://u:EXAMPLEaa b@EXAMPLEbb@h",
            "app:EXAMPLEaa\tEXAMPLEbb@db",
        ):
            with self.subTest(word=word[:12]):
                (masked,) = records.mask_words([word])
                self.assertNotIn("EXAMPLEaa", masked)
                self.assertNotIn("EXAMPLEbb", masked)
                self.assertIn("app:" if "app" in word else "u:", masked)

    def test_the_userinfo_mask_keeps_the_user_and_the_host(self) -> None:
        self.assertEqual(["app:\u2026REDACTED@db"], records.mask_words(["app:EXAMPLEaa@db"]))

    def test_a_command_with_nothing_to_mask_reads_as_it_was_typed(self) -> None:
        line = "python3 -m pytest tests/test_retry.py -q 2>&1 | tail -20"
        self.assertEqual(line, mask(line))


if __name__ == "__main__":
    unittest.main()
