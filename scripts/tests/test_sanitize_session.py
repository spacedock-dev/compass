"""The sample-session sanitizer: what it replaces, what it must keep, and what it must refuse to ship.

Every value here is invented. The real mapping, which holds originals, lives outside the repository.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sanitize_session as ss

SALT = "test-salt"
UID = "11111111-2222-4333-8444-555555555555"
PARENT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
CHILD = "99999999-8888-4777-8666-555555555555"
MAPPING = {
    "salt": SALT,
    "day_shift": -10,
    "time_shift_seconds": 3600,
    "ai_title": "A neutral title",
    "literals": [
        {
            "from": "/Users/pat/repos/zeta/atlas",
            "to": "/Users/dev/repos/acme/dashboard",
            "category": "path",
        },
        {"from": "/Users/pat", "to": "/Users/dev", "category": "home"},
        {"from": "Pat Example", "to": "Alex Doe", "category": "name"},
        {"from": "pat@zeta.io", "to": "dev@example.com", "category": "email"},
        {"from": "atlas", "to": "dashboard", "category": "project"},
        {"from": "zeta", "to": "acme", "category": "org", "word": True},
    ],
    "hashes": ["abc1234"],
    "numbers": ["41000000001"],
}


def records() -> list[dict[str, object]]:
    return [
        {
            "type": "user",
            "uuid": PARENT,
            "parentUuid": "00000000-0000-4000-8000-000000000000",
            "sessionId": UID,
            "cwd": "/Users/pat/repos/zeta/atlas",
            "timestamp": "2026-07-31T01:00:00.000Z",
            "message": {"role": "user", "content": "Fix atlas for Pat Example, mail pat@zeta.io"},
        },
        {
            "type": "assistant",
            "uuid": CHILD,
            "parentUuid": PARENT,
            "sessionId": UID,
            "timestamp": "2026-07-31T01:00:30.250Z",
            "message": {
                "role": "assistant",
                "id": "msg_0123456789abcdefghij",
                "content": [
                    {"type": "thinking", "thinking": "private thought", "signature": "x" * 40},
                    {
                        "type": "text",
                        "text": "Run ran on commit abc1234 in /Users/pat/repos/zeta/atlas/src",
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_ABCDEFGHIJKLMNOP",
                        "name": "Bash",
                        "input": {"command": "gh run view 41000000001 --repo zeta/atlas"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "uuid": "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff",
            "parentUuid": CHILD,
            "sessionId": UID,
            "timestamp": "2026-07-31T01:00:31Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_ABCDEFGHIJKLMNOP",
                        "content": json.dumps({"path": "/Users/pat/x", "owner": "Pat Example"}),
                    }
                ],
            },
        },
        {"type": "ai-title", "aiTitle": "An old title about atlas", "sessionId": UID},
    ]


class SanitizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "in.jsonl"
        self.target = self.root / "out.jsonl"
        self.mapping_path = self.root / "mapping.json"
        self.source.write_text("".join(json.dumps(r) + "\n" for r in records()), encoding="utf-8")
        self.mapping_path.write_text(json.dumps(MAPPING), encoding="utf-8")
        self.mapping = ss.Mapping.load(self.mapping_path)

    def run_it(self) -> list[dict[str, object]]:
        ss.sanitize(self.mapping, self.source, self.target)
        return [json.loads(line) for line in self.target.read_text(encoding="utf-8").splitlines()]

    def test_a_replacement_is_the_same_everywhere_and_longest_first(self) -> None:
        out = self.run_it()
        text = self.target.read_text(encoding="utf-8")
        self.assertEqual("/Users/dev/repos/acme/dashboard", out[0]["cwd"])
        self.assertIn("Fix dashboard for Alex Doe, mail dev@example.com", text)
        self.assertIn("/Users/dev/repos/acme/dashboard/src", text)
        self.assertNotIn("atlas", text)
        self.assertNotIn("Pat Example", text)

    def test_a_word_only_entry_leaves_a_longer_word_alone(self) -> None:
        self.source.write_text(
            json.dumps({"type": "x", "text": "zeta and zetas and a zeta."}) + "\n", encoding="utf-8"
        )
        out = self.run_it()
        self.assertEqual("acme and zetas and a acme.", out[0]["text"])

    def test_ids_are_regenerated_consistently_so_chains_stay_linked(self) -> None:
        out = self.run_it()
        uuids = {r["uuid"] for r in out if "uuid" in r}
        self.assertEqual(3, len(uuids))
        self.assertNotIn(PARENT, uuids)
        self.assertEqual(out[0]["uuid"], out[1]["parentUuid"])
        self.assertEqual(out[1]["uuid"], out[2]["parentUuid"])
        self.assertEqual({out[0]["sessionId"]}, {r["sessionId"] for r in out if "sessionId" in r})
        use = out[1]["message"]["content"][1]  # type: ignore[index]
        result = out[2]["message"]["content"][0]  # type: ignore[index]
        self.assertEqual(use["id"], result["tool_use_id"])
        self.assertNotEqual("toolu_ABCDEFGHIJKLMNOP", use["id"])
        self.assertEqual(len("toolu_ABCDEFGHIJKLMNOP"), len(use["id"]))

    def test_the_same_input_gives_the_same_output_and_another_salt_gives_another(self) -> None:
        first = json.dumps(self.run_it())
        self.assertEqual(first, json.dumps(self.run_it()))
        self.mapping.salt = "another"
        self.assertNotEqual(first, json.dumps(self.run_it()))

    def test_a_string_that_holds_json_is_cleaned_inside_and_stays_valid_json(self) -> None:
        inner = self.run_it()[2]["message"]["content"][0]["content"]  # type: ignore[index]
        self.assertEqual({"path": "/Users/dev/x", "owner": "Alex Doe"}, json.loads(inner))

    def test_times_move_by_one_fixed_offset_so_gaps_survive(self) -> None:
        out = self.run_it()
        self.assertEqual("2026-07-21T02:00:00.000Z", out[0]["timestamp"])
        self.assertEqual("2026-07-21T02:00:30.250Z", out[1]["timestamp"])
        self.assertEqual("2026-07-21T02:00:31Z", out[2]["timestamp"])

    def test_thinking_blocks_are_dropped_and_the_record_stays(self) -> None:
        content = self.run_it()[1]["message"]["content"]  # type: ignore[index]
        self.assertEqual(["text", "tool_use"], [block["type"] for block in content])

    def test_commit_hashes_and_run_numbers_keep_their_length_and_change(self) -> None:
        text = self.target.read_text(encoding="utf-8") if self.run_it() else ""
        self.assertNotIn("abc1234", text)
        self.assertNotIn("41000000001", text)
        self.assertRegex(text, r"commit [0-9a-f]{7} in")
        self.assertRegex(text, r"run view \d{11} --repo")

    def test_a_listed_number_held_as_a_json_integer_moves_with_its_text(self) -> None:
        self.mapping.numbers = ["618"]
        cleaner = ss.Sanitizer(self.mapping)
        record = cleaner.value({"prNumber": 618, "prUrl": "pull/618", "count": 61, "ok": True})
        self.assertEqual(f"pull/{record['prNumber']}", record["prUrl"])
        self.assertNotEqual(618, record["prNumber"])
        self.assertEqual((61, True), (record["count"], record["ok"]))

    def test_numbers_from_one_run_stay_close_together(self) -> None:
        self.mapping.numbers = ["41000000001", "41000000048"]
        cleaner = ss.Sanitizer(self.mapping)
        a, b = int(cleaner.text("41000000001")), int(cleaner.text("41000000048"))
        self.assertEqual(47, b - a)

    def test_a_parent_that_the_cut_removed_becomes_null(self) -> None:
        out = self.run_it()
        self.assertIsNone(out[0]["parentUuid"])

    def test_the_title_is_replaced_when_the_mapping_names_one(self) -> None:
        self.assertEqual("A neutral title", self.run_it()[3]["aiTitle"])

    def test_any_other_email_home_and_secret_is_replaced_whatever_the_mapping_says(self) -> None:
        cleaner = ss.Sanitizer(self.mapping)
        text = cleaner.text(
            "mail someone@other.org at /Users/stranger/code with sk-abcdefghijklmnopqrstuv0123"
        )
        self.assertIn("user@example.com", text)
        self.assertIn("/Users/dev/code", text)
        self.assertIn("<REDACTED_TOKEN>", text)
        self.assertNotIn("stranger", text)

    def test_a_screenshot_inside_a_tool_result_and_its_copy_are_replaced(self) -> None:
        shot = {"type": "image", "source": {"type": "base64", "data": "QUJD" * 50}}
        cleaner = ss.Sanitizer(self.mapping)
        record = cleaner.record(
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "content": [shot]}]},
                "toolUseResult": [shot],
            }
        )
        text = json.dumps(record)
        self.assertNotIn("QUJD", text)
        self.assertEqual(2, text.count("[image omitted]"))

    def test_the_short_form_of_an_id_becomes_the_short_form_of_its_replacement(self) -> None:
        cleaner = ss.Sanitizer(self.mapping)
        cleaner.learn_short_ids(json.dumps({"sessionId": UID}))
        new = cleaner.text(UID)
        self.assertEqual(
            f"open #n=session:claude:{new[:8]}&x", cleaner.text("open #n=session:claude:11111111&x")
        )
        self.assertEqual("x11111111", cleaner.text("x11111111"))

    def test_bare_times_move_with_the_timestamps_only_when_asked(self) -> None:
        text = "at 13:58, [heavy] 12:56:09 start, Oct 14 13:02 file, epoch 1791957580.5 and 1791957580957"
        self.assertEqual(text, ss.Sanitizer(self.mapping).text(text))
        self.mapping.shift_bare_times = True  # day_shift -10, one hour later
        self.assertEqual(
            "at 14:58, [heavy] 13:56:09 start, Oct  4 14:02 file, "
            "epoch 1791097180.5 and 1791097180957",
            ss.Sanitizer(self.mapping).text(text),
        )

    def test_a_local_time_loses_its_zone_and_a_utc_one_keeps_its_place(self) -> None:
        self.mapping.shift_bare_times = True
        self.mapping.local_clock_offset_seconds = 8 * 3600  # local ran eight hours ahead of UTC
        self.assertEqual(
            "18:21:20 STATUS; at 06:58; 11:51:58 UTC; Start at  11:46:25; Status at 06:13: ok; "
            "05:47  up 16:10, 3 users; 91391    02:59 codex",
            ss.Sanitizer(self.mapping).text(
                "01:21:20 STATUS; at 13:58; 10:51:58 UTC; Start at  10:46:25; Status at 13:13: ok; "
                "12:47  up 16:10, 3 users; 91391    02:59 codex"
            ),
        )

    def test_an_iso_time_is_moved_once_and_not_again_as_a_clock(self) -> None:
        self.mapping.shift_bare_times = True
        self.assertEqual(
            "2026-07-21T02:00:00Z and 2026-07-21 02:00:00",
            ss.Sanitizer(self.mapping).text("2026-07-31T01:00:00Z and 2026-07-31 01:00:00"),
        )

    def test_the_sweeps_flag_tracker_and_machine_shapes_and_not_ordinary_words(self) -> None:
        def hits(text: str) -> list[str]:
            return [label for label, pattern in ss.SWEEPS.items() if pattern.search(text)]

        self.assertEqual(["tracker reference"], hits("see DRC-12 in Linear"))
        self.assertEqual(["encoded home directory"], hits("/tmp/claude/-Users-pat-repos-x"))
        self.assertEqual(["machine temp directory"], hits("/var/folders/ab/xyz/T/shot.jpg"))
        self.assertEqual(["remote session link"], hits("https://claude.ai/code/session_01Real"))
        self.assertEqual([], hits("a task-notification, a linear scan, -Users-dev-repos"))

    def test_verification_reads_a_number_only_where_the_rule_replaces_it(self) -> None:
        self.mapping.numbers = ["4647"]
        self.source.write_text(
            json.dumps({"type": "x", "t": "issue 4647"}) + "\n", encoding="utf-8"
        )
        self.run_it()
        clean = self.target.read_text(encoding="utf-8")
        self.target.write_text(
            json.dumps({"type": "x", "t": json.loads(clean)["t"], "tokens": 4647, "n": "146475"})
            + "\n",
            encoding="utf-8",
        )
        self.assertEqual([], ss.verify(self.mapping, self.source, self.target))
        self.target.write_text(
            json.dumps({"type": "x", "t": "issue 4647"}) + "\n", encoding="utf-8"
        )
        problems = ss.verify(self.mapping, self.source, self.target)
        self.assertTrue(any("'4647'" in p for p in problems), problems)

    def test_verification_passes_a_clean_output(self) -> None:
        self.run_it()
        self.assertEqual([], ss.verify(self.mapping, self.source, self.target))

    def test_verification_catches_a_leaked_original_in_every_form(self) -> None:
        self.run_it()
        for leak in ("Pat Example", "pat%20example", "PAT EXAMPLE"):
            with self.subTest(leak=leak):
                clean = self.target.read_text(encoding="utf-8")
                self.target.write_text(
                    clean + json.dumps({"type": "x", "t": leak}) + "\n", encoding="utf-8"
                )
                problems = ss.verify(self.mapping, self.source, self.target)
                self.assertTrue(any("original still present" in p for p in problems), problems)
                self.target.write_text(clean, encoding="utf-8")

    def test_verification_catches_a_broken_chain_and_a_lost_line(self) -> None:
        self.run_it()
        rows = [json.loads(line) for line in self.target.read_text(encoding="utf-8").splitlines()]
        rows[2]["parentUuid"] = "00000000-1111-4222-8333-444444444444"
        self.target.write_text("".join(json.dumps(r) + "\n" for r in rows[:3]), encoding="utf-8")
        problems = ss.verify(self.mapping, self.source, self.target)
        self.assertTrue(any("line count" in p for p in problems), problems)
        self.assertTrue(any("parentUuid" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
