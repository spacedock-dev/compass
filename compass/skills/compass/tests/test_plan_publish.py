"""Plan publication through the HTTP parser, with in-memory request streams."""

from __future__ import annotations

import io
import json
import os
import subprocess
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    events,
    git_status,
    history,
    http_api,
    sessions,
)
from compass_runtime.plan import settings, sources

from .support import make_config
from .test_history import stub_application
from .test_plan_readers import STAND_IN, VARIANT, PlanRepoTestCase
from .test_project_script_checks import GIT
from .test_sessions import DECLARED_SESSION_FIELDS

READY_FIELDS = {
    "state",
    "goals",
    "lanes",
    "asks",
    "design",
    "tracker",
    "inventory",
    "diagrams",
    "sources",
    "logRejected",
    "limits",
}
LIMITS = "Compass cannot detect health information or confidential text typed into these sources."


def request(
    application: Any,
    *,
    peer: str = "127.0.0.1",
    host: str = "127.0.0.1:8000",
    headers: str = "",
) -> tuple[int, bytes, bytes]:
    handler: Any = http_api._RequestHandler.__new__(http_api._RequestHandler)
    handler.server = SimpleNamespace(
        bound_host="0.0.0.0",
        server_port=8000,
        application=application,
    )
    handler.client_address = (peer, 12345)
    handler.rfile = io.BytesIO(
        f"GET /api/plan HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n{headers}\r\n".encode()
    )
    handler.wfile = io.BytesIO()
    handler.connection = SimpleNamespace()
    handler.handle()
    head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    return int(head.split()[1]), head, body


class PlanAdmissionTest(unittest.TestCase):
    def test_denied_calls_do_not_check_settings(self) -> None:
        cases = (
            {"peer": "192.0.2.10"},
            {"peer": "192.0.2.10", "host": "board.example"},
            {"host": "board.example"},
            {"headers": "Forwarded: for=192.0.2.10\r\n"},
            {"headers": "X-Forwarded-For: 192.0.2.10\r\n"},
            {"headers": "Sec-Fetch-Site: same-site\r\nSec-Fetch-Dest: empty\r\n"},
            {
                "headers": "Sec-Fetch-Site: same-origin\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: document\r\n"
            },
            {"headers": "Sec-Fetch-Site: same-origin\r\nSec-Fetch-Dest: iframe\r\n"},
            {
                "host": "board.example",
                "headers": "X-ExeDev-Email: reader@example.net\r\nSec-Fetch-Site: same-origin\r\n",
            },
        )
        for enabled in (True, False):
            application = SimpleNamespace(
                config=make_config(
                    allowed_hosts=("board.example",),
                    login_proxy="exe.dev",
                    allowed_users=("reader@example.net",),
                    plan_enabled=enabled,
                )
            )
            for case in cases:
                with (
                    self.subTest(enabled=enabled, case=case),
                    mock.patch.object(settings, "load") as load,
                ):
                    self.assertEqual(request(application, **case)[0], 403)
                    load.assert_not_called()
        with mock.patch.object(settings, "load") as load:
            self.assertEqual(request(application)[0], 404)
            load.assert_not_called()


@unittest.skipIf(GIT is None or os.name == "nt", "Needs Git and POSIX directory descriptors")
class PlanPublicationTest(PlanRepoTestCase):
    def application(self, rows: list[dict[str, Any]] | None = None, **changes: Any) -> Any:
        config = make_config(state_home=str(self.home), state_dir=self.home, **changes)
        return stub_application(config, rows or [], [])

    def payload(self, application: Any | None = None) -> tuple[dict[str, Any], bytes]:
        status, headers, body = request(application or self.application())
        self.assertEqual(status, 200)
        self.assertIn(b"Cache-Control: no-store", headers)
        self.assertIn(b"Content-Type: application/json", headers)
        return json.loads(body), body

    def test_missing_and_refused_settings_have_no_partial_data(self) -> None:
        self.assertEqual(self.payload()[0], {"state": "not-configured"})
        self.configure()
        config_file = self.home / settings.FILENAME
        configured = json.loads(config_file.read_bytes())
        configured["repos"][0]["label"] = "CANARY_BAD_SETTINGS"
        configured["log"]["unknown"] = "unexpected"
        config_file.write_text(json.dumps(configured), encoding="utf-8")
        self.assertEqual(self.payload()[0], {"state": "refused", "reason": "malformed settings"})

    def test_projection_fields_match_the_closed_inventory(self) -> None:
        from compass_runtime.plan.publish import PLAN_FIELDS  # noqa: PLC0415

        self.assertEqual(set(PLAN_FIELDS), READY_FIELDS)
        self.assertEqual(len(PLAN_FIELDS), len(READY_FIELDS))
        self.write_sources(STAND_IN)
        self.configure()
        payload, _ = self.payload()
        self.assertEqual(set(payload), set(PLAN_FIELDS))

    def test_every_configured_fixture_publishes_the_same_fields(self) -> None:
        from compass_runtime.plan.publish import PLAN_FIELDS  # noqa: PLC0415

        for fixture, files in (("stand-in", STAND_IN), ("variant", VARIANT)):
            with self.subTest(fixture=fixture):
                self.configure(fixture)
                self.write_sources(files)
                payload, body = self.payload()
                self.assertEqual(set(payload), set(PLAN_FIELDS))
                self.assertEqual(payload["state"], "ready")
                self.assertEqual(payload["limits"], LIMITS)
                self.assertTrue(
                    all(
                        set(source) == {"label", "kind", "state", "reason"}
                        for source in payload["sources"]
                    )
                )
                self.assertNotIn(os.fsencode(self.root), body)
                self.assertNotIn(b"unusual seabird", body)
                self.assertNotIn(b"hidden tail", body)
                if fixture == "stand-in":
                    self.assertIn(
                        "Status not recognised", [row["group"] for row in payload["tracker"]]
                    )
                    self.assertEqual(payload["goals"][0]["doneWhen"], "The model floats.")
                    self.assertEqual(
                        payload["design"][0]["date"], {"label": "Changed", "at": "2026-09-01"}
                    )

    def test_no_git_refuses_git_sources_and_keeps_the_log(self) -> None:
        self.write_sources(STAND_IN)
        self.configure()
        self.log.write_text("ask hull:1 Is the model ready?\n", encoding="utf-8")
        with mock.patch.object(git_status, "plan_reader") as git:
            payload, _ = self.payload(self.application(git_probe_enabled=False))
        git.assert_not_called()
        self.assertEqual(payload["goals"], [])
        self.assertEqual(payload["asks"][0]["text"], "Is the model ready?")
        git_sources = [s for s in payload["sources"] if s["kind"] in sources.FILE_KINDS]
        self.assertEqual(len(git_sources), 5)
        self.assertTrue(
            all(s["state"] == "refused" and s["reason"] == "git reads are off" for s in git_sources)
        )

    def test_canary_link_forms_publish_only_hosts_in_every_source_kind(self) -> None:
        links = (
            ("https://key.example.test/p?key=CANARY_KEY", "key.example.test"),
            ("https://code.example.test/p?code=CANARY_CODE", "code.example.test"),
            ("https://hook.example.test/webhooks/CANARY_HOOK", "hook.example.test"),
            ("https://magic.example.test/magic/CANARY_MAGIC", "magic.example.test"),
            ("https://share.example.test/share/CANARY_SHARE", "share.example.test"),
        )
        self.write_sources(
            {
                "goals": "## Goals\n"
                + "".join(f"- G{i}: {link}\n" for i, (link, _) in enumerate(links, 1)),
                "design": "".join(f"### Decision: {link}\n" for link, _ in links),
                "tracker": "| Item | Status |\n| --- | --- |\n"
                + "".join(f"| {link} | fixed |\n" for link, _ in links),
            }
        )
        self.configure()
        self.log.write_text(
            "".join(f"ask hull:{i} {link}\n" for i, (link, _) in enumerate(links)), encoding="utf-8"
        )
        payload, body = self.payload()
        hosts = [host for _, host in links]
        self.assertEqual([row["title"] for row in payload["goals"]], hosts)
        self.assertEqual(
            [row["title"] for row in payload["design"]], [f"Decision: {host}" for host in hosts]
        )
        self.assertEqual([row["title"] for row in payload["tracker"]], hosts)
        self.assertEqual([row["text"] for row in payload["asks"]], hosts)
        self.assertNotIn(b"CANARY_", body)
        self.assertNotIn(b"https://", body)

    def test_diagram_body_source_labels_and_links_are_filtered_before_the_cap(self) -> None:
        from compass_runtime import records  # noqa: PLC0415

        self.write_sources(
            {
                "diagrams": "## Model assembly\n```mermaid\nflowchart LR\n"
                '  A["https://login:password@diagram.example.test:8443/path?key=CANARY_DIAGRAM"] --> B\n'
                "```\n"
            }
        )
        self.configure(log={"label": "https://log.example.test/path?code=CANARY_SOURCE"})
        payload, body = self.payload()
        diagram = payload["diagrams"][0]
        self.assertEqual(diagram["body"], 'flowchart LR\n  A["diagram.example.test"] --> B')
        self.assertEqual(diagram["linkHosts"], ["diagram.example.test"])
        self.assertTrue(any(row["label"] == "log.example.test" for row in payload["sources"]))
        self.assertNotIn(b"CANARY_", body)
        self.assertNotIn(b"password", body)
        self.assertNotIn(b":8443", body)
        text, hosts = records.hosts_only(
            "See [the note](<https://note.example.test/path?key=CANARY_NOTE>) "
            "and <//team.example.test/share/CANARY_TEAM>. "
            "Also [a file](../CANARY_LOCAL)."
        )
        self.assertEqual(hosts, ("note.example.test", "team.example.test"))
        self.assertNotIn("CANARY_", text)

    def test_diagram_cap_applies_after_redaction_and_host_replacement(self) -> None:
        lines = (
            'flowchart LR\n  A["'
            + "x " * 4050
            + "https://bounded.example.test/"
            + "CANARY_LONG_URL_" * 250
            + '"] --> B\n'
            + '  B["Authorization: Bearer xoxb-225556655-example-token"]\n'
            + '  C["'
            + "X " * 180
            + '"]'
        )
        self.write_sources({"diagrams": f"## Assembly\n```mermaid\n{lines}\n```\n"})
        self.configure()
        payload, body = self.payload()
        diagram = payload["diagrams"][0]
        self.assertEqual(len(diagram["body"]), 8192)
        self.assertTrue(diagram["body"].endswith("…"))
        self.assertIn('bounded.example.test"] --> B', diagram["body"])
        self.assertNotIn(b"CANARY_LONG_URL_", body)
        self.assertNotIn(b"xoxb-22555", body)
        self.assertIn("REDACTED", diagram["body"])

    def test_lane_sessions_match_one_folder_identity_and_asks_keep_lane_ids(self) -> None:
        self.write_sources(STAND_IN)
        other = self.root / "work" / "other"
        nested = self.hull / "nested"
        child = self.hull / "child"
        for folder in (other, nested, child):
            folder.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(self.hull, target_is_directory=True)
        for slug in ("hull", "paint", "nested", "empty"):
            (self.briefs / f"{slug}.md").write_text(
                "## Goal\nSame lane title\n\n*Serves*: G1\n", encoding="utf-8"
            )
        self.configure(
            briefs={
                "lane_folders": {
                    "hull": str(self.hull),
                    "paint": str(other),
                    "nested": str(nested),
                }
            }
        )
        self.log.write_text(
            "ask paint:1 Choose a color\n"
            "2026-01-02T03:04:05Z ask hull:2 Pick a material\n"
            "ask unknown:3 No admitted lane\n",
            encoding="utf-8",
        )
        folders = {"one": alias / "child", "two": nested, "three": other, "four": self.root}
        app = self.application(
            [{"sid": sid, "state": "working", "last_activity": 4_900.0} for sid in folders]
        )
        collect = app.collect

        def collect_with_folders(*, show_all: bool) -> Any:
            # Feed the same metadata hook the real collectors use, before the
            # collection becomes a snapshot. Goose has no transcript resolver.
            board = collect(show_all=show_all)
            for row in board["sessions"]:
                if row["sid"] == "three":
                    row["harness"] = "goose"
                sessions.apply_project_identity(app.config, row, str(folders[row["sid"]]))
            return board

        with mock.patch.object(app, "collect", side_effect=collect_with_folders):
            _, before = app.collect_json(show_all=False)
        payload, body = self.payload(app)
        lanes = {row["id"]: row for row in payload["lanes"]}
        self.assertEqual(set(payload["goals"][0]["lanes"]), set(lanes))
        self.assertEqual(lanes["hull"]["sessions"], ['session:["claude","one"]'])
        self.assertEqual(lanes["paint"]["sessions"], ['session:["goose","three"]'])
        self.assertEqual(lanes["nested"]["sessions"], [])
        self.assertEqual(lanes["empty"]["sessions"], [])
        self.assertEqual(lanes["hull"]["title"], lanes["paint"]["title"])
        self.assertEqual(
            [(row["source"], row["lane"], row["timeLabel"], row["at"]) for row in payload["asks"]],
            [
                ("Coordination", {"id": "paint", "title": "Same lane title"}, "from the log", None),
                (
                    "Coordination",
                    {"id": "hull", "title": "Same lane title"},
                    "from the log",
                    "2026-01-02T03:04:05Z",
                ),
                ("Coordination", None, "from the log", None),
            ],
        )
        self.assertNotIn(os.fsencode(self.root), body)
        self.assertEqual(app.snapshot.current((app.config.window_hours, False))[1], before)
        for row in json.loads(before)["sessions"]:
            self.assertLessEqual(set(row), DECLARED_SESSION_FIELDS)
        self.assertLessEqual(set(events.PATCHABLE), DECLARED_SESSION_FIELDS)
        self.assertEqual(
            set(sessions.base_session("claude", "one", "demo")), DECLARED_SESSION_FIELDS
        )

    def test_plan_canary_stays_out_of_collection_and_saved_history(self) -> None:
        canary = "CANARY_PLAN_ONLY_q917"
        self.write_sources({"goals": f"## Goals\n- G1: {canary}\n"})
        self.configure()
        app = self.application([{"sid": "one", "state": "working", "last_activity": 4_900.0}])
        self.assertIn(canary.encode(), self.payload(app)[1])
        _, board = app.collect_json(show_all=False)
        self.assertNotIn(canary.encode(), board)
        saved = Path(history.store_path(app.config)).read_bytes()
        self.assertNotIn(canary.encode(), saved)
        entries, _ = history.load(app.config)
        self.assertTrue(entries)
        self.assertEqual(set(entries[0]), set(history.OBSERVATION_FIELDS))

    def test_slow_git_shares_the_request_deadline_across_commands_and_repos(self) -> None:
        self.write_sources(STAND_IN)
        self.configure()
        config_file = self.home / settings.FILENAME
        config = json.loads(config_file.read_bytes())
        config["repos"].append({**config["repos"][0], "label": "Second repository"})
        config_file.write_text(json.dumps(config), encoding="utf-8")

        now = 100.0
        timeouts: list[float] = []

        def runner(argv: tuple[str, ...], *, timeout: float, **_: Any) -> Any:
            nonlocal now
            timeouts.append(timeout)
            if len(timeouts) == 1:
                now += 0.75
                return subprocess.CompletedProcess(argv, 0, b"\n", b"")
            now += timeout
            raise subprocess.TimeoutExpired(argv, timeout)

        factory = git_status.plan_reader
        app = self.application(git_probe_timeout_sec=1.0)
        with (
            mock.patch.object(time, "monotonic", side_effect=lambda: now),
            mock.patch.object(
                git_status,
                "plan_reader",
                side_effect=lambda *a, **kw: factory(*a, **kw, runner=runner),
            ),
        ):
            payload, _ = self.payload(app)
        self.assertEqual(timeouts, [1.0, 0.25])
        self.assertEqual(now, 101.0)
        self.assertEqual(payload["goals"], [])
        refused = [source for source in payload["sources"] if source["reason"] == "git timed out"]
        self.assertEqual(len(refused), 10)
