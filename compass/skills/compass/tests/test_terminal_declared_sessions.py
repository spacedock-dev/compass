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
        self.assertNotIn("Waiting on Check build", output)
        self.assertIn("Ended", output)
