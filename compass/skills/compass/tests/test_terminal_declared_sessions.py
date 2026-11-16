"""The declared-session words are shared with the page's parity test."""

import copy
import json
import unittest

from compass_runtime import terminal_project, terminal_sessions

from .support import SERVER_PATH

FIXTURE = json.loads(
    (SERVER_PATH.parents[3] / "frontend/test/fixtures/declared-sessions.json").read_text()
)


class DeclaredSessionWordsTest(unittest.TestCase):
    def test_a_reader_sees_the_same_links_groups_and_waits_in_both_commands(self) -> None:
        payload = terminal_sessions.list_payload(FIXTURE["payload"])
        output = "\n".join(terminal_sessions.render_sessions(payload))
        project = "\n".join(
            terminal_project.render(
                terminal_project.derive(payload, None, label="demo"), caller=("claude", "parent")
            )
        )
        for lines in FIXTURE["expected"].values():
            for line in lines:
                self.assertIn(line, output)
                self.assertIn(line, project)

    def test_a_parent_that_left_the_board_is_not_presented_as_a_link(self) -> None:
        payload = copy.deepcopy(FIXTURE["payload"])
        payload["sessions"] = [payload["sessions"][0]]
        payload["sessions"][0].update(
            declared_parent=None, declared_parent_state="not_linked", group=None, group_source=None
        )
        output = "\n".join(terminal_sessions.render_sessions(payload))
        self.assertIn("Declared parent is not on the board; not linked.", output)
        self.assertNotIn("Child of", output)
        self.assertNotIn("Group:", output)

    def test_an_ended_child_does_not_imply_a_parent_is_still_waiting(self) -> None:
        payload = copy.deepcopy(FIXTURE["payload"])
        payload["sessions"][0].update(state="idle", ended_at=1899999999)
        payload["sessions"][2].update(state="idle", waiting_on_child=None)
        output = "\n".join(terminal_sessions.render_sessions(payload))
        self.assertNotIn('Waiting on child "Check build"', output)
        self.assertIn("Ended", output)

    def render_both(self, payload: terminal_sessions.Row) -> tuple[str, str]:
        return (
            "\n".join(terminal_sessions.render_sessions(payload)),
            "\n".join(
                terminal_project.render(
                    terminal_project.derive(payload, None, label="demo"),
                    caller=("claude", "parent"),
                )
            ),
        )

    def test_a_not_linked_declaration_never_names_a_present_parent(self) -> None:
        payload = copy.deepcopy(FIXTURE["payload"])
        payload["sessions"][0]["declared_parent_state"] = "not_linked"
        for output in self.render_both(payload):
            self.assertIn("Declared parent is not on the board; not linked.", output)
            self.assertNotIn("Child of Coordinate release", output)

    def test_an_absent_waiting_child_is_stated_in_both_commands(self) -> None:
        payload = copy.deepcopy(FIXTURE["payload"])
        payload["sessions"] = payload["sessions"][1:]
        for output in self.render_both(payload):
            self.assertIn("Waiting on child not on the board", output)
            self.assertNotIn('Waiting on child "Check build"', output)

    def test_relationship_text_cannot_steer_the_terminal(self) -> None:
        payload = copy.deepcopy(FIXTURE["payload"])
        payload["sessions"][2]["title"] = "Coordinate\nrelease\x1b[31m\u202e"
        payload["sessions"][0]["title"] = "Check\rbuild\x1b]52;c;secret\x07"
        payload["sessions"][0]["group"] = "release\tteam\x00\u202e"
        for output in self.render_both(payload):
            self.assertIn("Child of Coordinate release", output)
            self.assertIn('Waiting on child "Check build"', output)
            self.assertIn("Group: release team (from parent)", output)
            for unsafe in ("\x1b", "\x00", "\u202e", "\t", "secret"):
                self.assertNotIn(unsafe, output)

    def test_project_relationship_fields_clip_long_parent_and_child_titles(self) -> None:
        payload = copy.deepcopy(FIXTURE["payload"])
        payload["sessions"][2]["title"] = "P" * 220
        payload["sessions"][0]["title"] = "C" * 220
        output = self.render_both(payload)[1]
        relationships = [
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith(("Child of ", "Waiting on "))
        ]
        self.assertEqual(len(relationships), 2)
        self.assertIn("Child of " + "P" * 150 + "…", relationships)
        self.assertIn('Waiting on child "' + "C" * 141 + "…", relationships)
        self.assertTrue(all(len(line) == 160 for line in relationships))

    def test_prompt_first_child_title_is_quoted_as_a_child_in_both_commands(self) -> None:
        payload = copy.deepcopy(FIXTURE["payload"])
        payload["sessions"][0]["title"] = "You are verifying a fix round"
        for output in self.render_both(payload):
            self.assertIn('Waiting on child "You are verifying a fix round"', output)
            self.assertNotIn("Waiting on You are", output)
