"""Plan publication through the HTTP parser, with in-memory request streams."""

from __future__ import annotations

import errno
import io
import json
import os
import subprocess
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    diagnostics,
    events,
    git_status,
    history,
    http_api,
    records,
    sessions,
)
from compass_runtime import io as runtime_io
from compass_runtime.plan import model, publish, readers, settings, sources

from .support import make_config
from .test_history import stub_application
from .test_plan_readers import LANE_TRACKER, STAND_IN, VARIANT, PlanRepoTestCase
from .test_project_script_checks import GIT, git
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
                        set(source) == {"label", "kind", "fileLabel", "position", "state", "reason"}
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

    def test_every_published_row_has_exactly_its_documented_keys(self) -> None:
        expected = {
            "goals": {"id", "title", "doneWhen", "lanes", "proposal"},
            "lanes": {"id", "title", "doneWhen", "state", "date", "sessions"},
            "asks": {"id", "text", "at", "timeLabel", "source", "lane"},
            "asks.lane": {"id", "title"},
            "design": {"title", "summary", "decided", "source", "date"},
            "tracker": {"title", "group", "source", "date"},
            "inventory": {"title", "group", "source", "date"},
            "diagrams": {"title", "caption", "kind", "source", "date", "linkHosts", "body"},
            "date": {"label", "at"},
            "sources": {"label", "kind", "fileLabel", "position", "state", "reason"},
        }
        self.assertEqual(publish.PLAN_ITEM_FIELDS, expected)
        for fixture, files, brief, brief_text, log in (
            ("stand-in", STAND_IN, "hull.md", "## Goal\nBuild it.\n", "ask hull:1 Sample?\n"),
            (
                "variant",
                VARIANT,
                "hull.brief.md",
                "**Objective:** Build it.\n",
                "2026-01-02T03:04:05Z ASK hull a1 Sample?\n",
            ),
        ):
            with self.subTest(fixture=fixture):
                self.write_sources(files)
                self.configure(fixture)
                (self.briefs / brief).write_text(brief_text, encoding="utf-8")
                self.log.write_text(log, encoding="utf-8")
                plan, _ = self.payload()
                rows = {name: plan[name] for name in expected.keys() - {"asks.lane", "date"}}
                rows["asks.lane"] = [ask["lane"] for ask in plan["asks"]]
                rows["date"] = [
                    row["date"]
                    for name in ("lanes", "design", "tracker", "inventory", "diagrams")
                    for row in plan[name]
                    if row["date"] is not None
                ]
                for name, fields in expected.items():
                    with self.subTest(row=name):
                        self.assertTrue(rows[name])
                        for row in rows[name]:
                            self.assertEqual(set(row), fields)

    def test_sources_tell_files_of_one_kind_apart_without_paths(self) -> None:
        self.write_sources(STAND_IN)
        (self.repo / "plan" / "parts.md").write_text(STAND_IN["built"], encoding="utf-8")
        git(self.repo, "add", "plan")
        git(self.repo, "commit", "-qm", "Synthetic parts")
        self.configure()
        file = self.home / settings.FILENAME
        doc = json.loads(file.read_bytes())
        # The second file is not committed, and the draft branch the fixture names does not exist.
        doc["repos"][0]["files"]["inventory"] = [
            "plan/built.md",
            "plan/uncommitted-canary.md",
            {"path": "plan/parts.md", "label": "Spare parts"},
        ]
        file.write_text(json.dumps(doc), encoding="utf-8")
        plan, body = self.payload()
        rows = [
            (s["kind"], s["fileLabel"], s["position"], s["state"], s["reason"])
            for s in plan["sources"]
            if s["kind"].endswith("inventory") or s["kind"].endswith("goals")
        ]
        self.assertEqual(
            rows,
            [
                ("goals", None, None, "ok", None),
                ("inventory", None, 1, "ok", None),
                ("inventory", None, 2, "refused", "not in branch"),
                ("inventory", "Spare parts", 3, "ok", None),
                ("draft goals", None, None, "refused", "branch missing"),
                ("draft inventory", None, 1, "refused", "branch missing"),
                ("draft inventory", None, 2, "refused", "branch missing"),
                ("draft inventory", "Spare parts", 3, "refused", "branch missing"),
            ],
        )
        self.assertTrue(all(set(s) == publish.PLAN_ITEM_FIELDS["sources"] for s in plan["sources"]))
        self.assertEqual({s["fileLabel"] for s in plan["sources"]}, {None, "Spare parts"})
        self.assertNotIn(b"uncommitted-canary", body)
        self.assertNotIn(b"parts.md", body)
        self.assertNotIn(os.fsencode(self.root), body)

    def test_lane_state_is_a_closed_group_or_null(self) -> None:
        self.assertEqual(
            publish.LANE_STATES,
            (
                "not_started",
                "running",
                "waiting",
                "blocked",
                "done",
                "dropped",
                "Status not recognised",
            ),
        )
        self.write_sources({"tracker": LANE_TRACKER})
        for slug in ("hull", "paint", "mast", "keel"):
            (self.briefs / f"{slug}.md").write_text("## Goal\nSample lane\n", encoding="utf-8")
        self.configure(tracker={"lane_column": "Lane"})
        plan, body = self.payload()
        self.assertEqual(
            {lane["id"]: lane["state"] for lane in plan["lanes"]},
            {"hull": "done", "paint": "Status not recognised", "mast": None, "keel": None},
        )
        self.assertNotIn(b"unusual seabird", body)
        self.assertTrue(
            all(set(row) == publish.PLAN_ITEM_FIELDS["tracker"] for row in plan["tracker"])
        )

        unmeasured, _ = self.payload(self.application(git_probe_enabled=False))
        self.assertEqual({lane["state"] for lane in unmeasured["lanes"]}, {None})

    def test_projection_publishes_only_closed_lane_states(self) -> None:
        source = model.Source("lane brief", "hull", "")
        lanes = tuple(
            model.Lane(f"lane-{n}", "Sample", None, (), source, state=state)
            for n, state in enumerate(("done", "Status not recognised", None, "seabird", "Done"))
        )
        plan = model.PlanModel((), (), (), (), (), lanes, (), (), None)
        self.assertEqual(
            [lane["state"] for lane in publish._project(plan, {})["lanes"]],
            ["done", "Status not recognised", None, None, None],
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
        credential = "xoxb-225556655-example-token"
        links = (
            ("https://key.example.test/p?key=CANARY_KEY", "key.example.test"),
            ("https://code.example.test/p?code=CANARY_CODE", "code.example.test"),
            ("https://hook.example.test/webhooks/CANARY_HOOK", "hook.example.test"),
            ("https://magic.example.test/magic/CANARY_MAGIC", "magic.example.test"),
            ("https://share.example.test/share/CANARY_SHARE", "share.example.test"),
            ("bare.example.test/share/CANARY_BARE", "bare.example.test"),
            ("bare.example.test?code=CANARY_BARE_QUERY", "bare.example.test"),
            ("_docs.example.test/d/CANARY_ITALIC/edit_", "docs.example.test"),
            ("-docs.example.test/d/CANARY_DASH/edit", "docs.example.test"),
            ("参考docs.example.test/d/CANARY_CJK/edit", "docs.example.test"),
            ("参考www.example.test/d/CANARY_CJK_WWW/edit", "www.example.test"),
            ("参考https://example.test/p/CANARY_CJK_SCHEME", "example.test"),
            ("@docs.example.test/d/CANARY_AT/edit", "docs.example.test"),
            ("a@docs.example.test/d/CANARY_EMAIL/edit", "docs.example.test"),
            ("docs.example.test:8443/d/CANARY_PORT", "docs.example.test"),
            ("staging.example.test:8443/invite?key=CANARY_PORT_QUERY", "staging.example.test"),
            ("docs.example.test#code=CANARY_FRAGMENT", "docs.example.test"),
            ("localhost:3000/reset?code=CANARY_LOCALHOST", "localhost"),
            ("192.168.1.1/hooks/CANARY_IPV4", "192.168.1.1"),
            ("192.168.1.10:8080/share/CANARY_IP_PORT", "192.168.1.10"),
            ("example.xn--p1ai/reset?code=CANARY_PUNY", "example.xn--p1ai"),
            ("user:CANARY_PASS@example.test/CANARY_PATH", "example.test"),
            ("exämple.test/share/CANARY_IDN", "[link]"),
            ("!www.prefix.example.test/CANARY_PUNCT", "www.prefix.example.test"),
            ("_www.prefix.example.test/CANARY_UNDERSCORE", "www.prefix.example.test"),
            ("-www.prefix.example.test/CANARY_HYPHEN", "www.prefix.example.test"),
            ("!mailto:CANARY_OPAQUE@example.test", "[link]"),
            ("slack:channel?code=CANARY_CUSTOM_OPAQUE", "[link]"),
            ("_tel:CANARY_OPAQUE_UNDERSCORE", "[link]"),
            ("-data:CANARY_OPAQUE_HYPHEN", "[link]"),
            ("https://quote.example.test/?q='CANARY_QUOTED TAIL'", "quote.example.test"),
            ("https://quote.example.test/?q=`CANARY_BACKTICK TAIL`", "quote.example.test"),
            ("https://quote.example.test/?q=value'_CANARY_SUFFIX'", "quote.example.test"),
            ("https://example.test/share/a' 'b/CANARY_PATH_QUOTE", "example.test"),
            ("www.example.test/share/a' 'b/CANARY_WWW_QUOTE", "www.example.test"),
            ("'https://example.test/p?q=foo' ,bar&key=CANARY_SINGLE'", "example.test"),
            ('"https://example.test/p?q=a",b&key=CANARY_DOUBLE"', "example.test"),
            ("`https://example.test/p?q=a`;key=CANARY_TICK`", "example.test"),
            ("https://example.test/a?x=1>2&key=CANARY_GT", "example.test"),
            ("[guide](https://md.example.test/p(CANARY_NESTED)tail)", "md.example.test"),
            ('[x](https://example.test/p?a=")"&key=CANARY_MD_QUOTE)', "example.test"),
            ("[x](https://example.test/r?mood=:)&key=CANARY_MD_PAREN)", "example.test"),
            ('[x](https://example.test/p?a=") CANARY_MD_QUOTED_SPACE"&key=Z)', "example.test"),
            ('[x](https://example.test/p(v) "title ) CANARY_MD_QUOTED_TITLE")', "example.test"),
            ("[x](https://example.test/c?f=sum(a)&key=CANARY_MD_NESTED)", "example.test"),
            ("[x](https://example.test/p)?code=CANARY_MD_TAIL", "example.test"),
            ("[x](<https://example.test/p>)?code=CANARY_MD_ANGLE_TAIL", "example.test"),
            ('[x](https://example.test/p "t")&key=CANARY_MD_TITLE_TAIL', "example.test"),
            ("[guide](../guide(CANARY_RELATIVE).md)", "[guide]"),
            ("[guide] (./secret/CANARY_SPACE_PAREN.md)", "[guide]"),
            ("[ref]: ./CANARY_REFERENCE.md", "[ref]"),
            (r"[a\]]: ./secret/CANARY_ESCAPED_REF.md", r"[a\]]"),
            (f"Authorization: Bearer {credential}", "REDACTED"),
            # A backslash after a host is a path separator to WHATWG, so the link is unnamed.
            ("example.test\\CANARY_BACKSLASH", "[link]"),
            ("localhost:3000\\CANARY_BACKSLASH_LOCAL", "[link]"),
            ("example.рф/r?c=CANARY_IDN_TLD", "[link]"),
            ("пример.рф/r?c=CANARY_IDN_HOST", "[link]"),
            ("sub.пример.рф/r?c=CANARY_IDN_SUB", "[link]"),
            ("example。test/CANARY_IDEOGRAPHIC_DOT", "[link]"),
            ("example\uff0etest/CANARY_FULLWIDTH_DOT", "[link]"),
            ("example｡test/CANARY_HALFWIDTH_DOT", "[link]"),
            ("example.test./CANARY_TRAILING_DOT", "example.test"),
            ("a-localhost:3000/reset/CANARY_GLUED_LOCAL", "localhost"),
            ("1localhost:3000/reset/CANARY_DIGIT_LOCAL", "localhost"),
            ("a.192.168.1.10/admin/CANARY_DOT_IP", "192.168.1.10"),
            ("a-10.0.0.5:8080/CANARY_DASH_IP", "10.0.0.5"),
            ("1192.168.1.10/admin/CANARY_DIGIT_IP", "192.168.1.10"),
            ("a-data:text/plain,CANARY_DASH_DATA", "[link]"),
            ("1data:text/plain,CANARY_DIGIT_DATA", "[link]"),
            ("adata:text/plain;base64,CANARY_LETTER_DATA", "[link]"),
            ("git@host:CANARY_ORG/CANARY_REPO.git", "host"),
            ("git@github.com:CANARY_ORG/repo.git", "github.com"),
            ("git@[::1]:CANARY_ORG/repo.git", "[::1]"),
            ("git@host:CANARY_REPO_ONLY.git", "host"),
            ("_git@host:CANARY_EMPHASIS.git_", "host"),
            ("CANARY_REMOTE_USER:CANARY_REMOTE_PASS@host:CANARY_ORG/repo.git", "host"),
            ("CANARY_IP_USER:CANARY_IP_PASS@1192.168.1.10/admin/CANARY_IP_PATH", "192.168.1.10"),
            ("CANARY_LOCAL_USER@a-localhost:3000/CANARY_LOCAL_PATH", "localhost"),
            ("CANARY_IDN_USER@пример.рф/CANARY_IDN_PATH", "[link]"),
            ("webcal:feed?c=CANARY_WEBCAL", "[link]"),
            ("web+example:opaque-CANARY_WEB_PLUS", "[link]"),
            ("1webcal:CANARY_GLUED_WEBCAL", "[link]"),
            # A known link later in the token keeps its own span; the added form masks the rest.
            ("CANARY_U1:CANARY_P1@1192.168.1.10/admin?r=//x", "192.168.1.10"),
            ("git@host:CANARY_ORG/repo.git#readme", "host"),
            ("example.рф/CANARY_NEXT?next=https://other.test/", "[link]"),
            ("webcal:CANARY_WEBCAL_NEXT?next=https://x.test/", "[link]"),
            ("a-localhost\\CANARY_GLUED_BACKSLASH", "[link]"),
            ("example.xn--p1ai\\CANARY_PUNY_BACKSLASH", "[link]"),
            ("x@webcal:org/CANARY_OPAQUE_REMOTE.git", "[link]"),
            ("参考docs.example.test\\CANARY_CJK_BACKSLASH", "参考[link]"),
            ("CANARY_U2:CANARY_P2%3A@host:org/repo.git", "host"),
            ("CANARY_U3:CANARY_P3!@host:org/repo.git", "host"),
            ("CANARY_U4:CANARY_P4@host:/srv/CANARY_SLASH.git", "[link]"),
            ("CANARY_U5:CANARY_P5@CANARY_P6@1192.168.1.10/CANARY_AT", "192.168.1.10"),
            ("adata:;base64,CANARY_DATA_PARAMS", "[link]"),
            ("उदाहरण.भारत/CANARY_DEVANAGARI", "[link]"),
            ("ตัวอย่าง.ไทย/CANARY_THAI", "[link]"),
            ("cafe\u0301.test/CANARY_COMBINING", "[link]"),
            ("пример1.рф/CANARY_MIXED_LABEL", "[link]"),  # noqa: RUF001 - a digit inside an IDN label
            ("git@host:CANARY_ORG\\repo.git", "[link]"),
            ("git@host:/srv/CANARY_ABSOLUTE.git", "[link]"),
            ("[repo](git@host:CANARY_ORG/repo.git)", "[repo]"),
            # A bracketed IPv6 address before a path, a query or a fragment.
            ("[::1]/CANARY_IPV6", "[::1]"),
            ("[2001:db8::1]/r?c=CANARY_IPV6_LONG", "[2001:db8::1]"),
            ("参考[::1]?code=CANARY_IPV6_QUERY", "[::1]"),
            ("CANARY_V6_USER@[::1]#CANARY_IPV6_FRAGMENT", "[::1]"),
            ("_[::1]/CANARY_IPV6_EMPHASIS_", "[::1]"),
            ("[fe80::1%25CANARY_ZONE]/CANARY_IPV6_ZONE", "[link]"),
            # Userinfo before a bare `www.` host with nothing after it.
            ("CANARY_W_USER:CANARY_W_PASS@www.example.test", "www.example.test"),
            # A full-width solidus or a zero-width character between a host and its path.
            ("example.test\uff0fCANARY_FULLWIDTH_SOLIDUS", "[link]"),
            (
                "\uff45\uff58\uff41\uff4d\uff50\uff4c\uff45\uff0e\uff43\uff4f\uff4d\uff0fCANARY_WIDE",
                "[link]",
            ),
            ("example.test\u200b/CANARY_ZERO_WIDTH", "[link]"),
            ("example.test\u200b:8443/CANARY_ZERO_WIDTH_PORT", "[link]"),
            ("localhost\uff0fCANARY_LOCAL_SOLIDUS", "[link]"),
            # Masked from the token's start, so a later link's userinfo is still covered.
            ("CANARY_PRE!example.test\uff0fx@host:org/r.git", "[link]"),
            (":/CANARY_SCHEME:WWW.a.bc\uff0f:pw@blob:x", "[link]"),
            ("example.test\u2060\u00ad?code=CANARY_WORD_JOINER", "[link]"),
            # A git remote whose path holds a colon: what follows the colon may be another link
            # form, so no host is named.
            ("git@host:CANARY_ORG:CANARY_COLON.git", "[link]"),
            ("git@host:22:CANARY_PORT_PATH/r.git", "[link]"),
            # A slash, a query mark or a hash inside a password.
            ("CANARY_S_USER:CANARY_S1/CANARY_S2@host:org/r.git", "host"),
            ("CANARY_T_USER:CANARY_T1/CANARY_T2@example.test/x", "example.test"),
            ("CANARY_Q_USER:CANARY_Q1?CANARY_Q2#CANARY_Q3@1192.168.1.10/x", "192.168.1.10"),
            ("CANARY_B64/CANARY_B64+x@www.example.test/x", "www.example.test"),
            # An `@` after a remote's colon may be a password's: the host after it is named, or
            # none is.
            ("CANARY_R1@CANARY_R2:CANARY_R3@host:org/r.git", "host"),
            ("CANARY_R4@CANARY_R5:CANARY_R6/x@host:org/r.git", "[link]"),
        )
        self.write_sources(
            {
                "goals": "## Goals\n"
                + "".join(f"- G{i}: {link}\n" for i, (link, _) in enumerate(links, 1)),
                "design": "".join(f"### Decision: {link}\n" for link, _ in links),
                "tracker": "| Item | Status |\n| --- | --- |\n"
                + "".join(f"| {link} | fixed |\n" for link, _ in links),
                "diagrams": "## Sample\n```mermaid\nflowchart LR\n"
                + "\n".join(link for link, _ in links)
                + "\n```\n",
            }
        )
        self.configure()
        self.log.write_text(
            "".join(f"ask hull:{i} {link}\n" for i, (link, _) in enumerate(links)), encoding="utf-8"
        )
        payload, body = self.payload()
        diagram = payload["diagrams"][0]["body"].splitlines()[1:]
        for index, (link, expected) in enumerate(links):
            with self.subTest(link=link):
                for actual in (
                    payload["goals"][index]["title"],
                    payload["design"][index]["title"],
                    payload["tracker"][index]["title"],
                    payload["asks"][index]["text"],
                    diagram[index],
                ):
                    self.assertIn(expected, actual)
                    self.assertNotIn("CANARY_", actual)
                    self.assertNotIn(credential, actual)
        self.assertNotIn(b"CANARY_", body)
        self.assertNotIn(b"https://", body)
        self.assertNotIn(credential.encode(), body)
        hosts = payload["diagrams"][0]["linkHosts"]
        self.assertNotIn("-docs.example.test", hosts)
        self.assertTrue({"host", "github.com", "[::1]", "localhost", "10.0.0.5"} <= set(hosts))
        self.assertFalse([host for host in hosts if not host.isascii() or "\\" in host])

    def test_multiline_diagram_link_destinations_are_stripped(self) -> None:
        long_label = "[" + "a" * 1000 + "]"
        self.write_sources(
            {
                "diagrams": "```\n[guide](\n./secret/CANARY_REL.md)\n"
                "[guide](  \n  ./secret/CANARY_INDENTED.md)\n"
                "[guide](\nhttps://example.test/p?code=CANARY_URL)\n"
                "[ref]:\n  ./secret/CANARY_REF.md\n"
                "[x](./guide.md\n)?code=CANARY_TAIL\n"
                "[outer]([inner](\n./secret/CANARY_NESTED_LEGACY.md))\n"
                '[x](https://example.test/p "title\nCANARY_INLINE_TITLE")\n'
                '[reference]: ./guide.md\n  "title\nCANARY_REFERENCE_TITLE"\n'
                f"{long_label}: ./secret/CANARY_LONG_LABEL.md\n"
                "Keep this line\n"
                "[mailto:CANARY_REFERENCE_LABEL<]:\n  ./guide.md\n```\n",
            }
        )
        self.configure()
        plan, body = self.payload()
        self.assertNotIn(b"CANARY_", body)
        self.assertEqual(
            plan["diagrams"][0]["body"],
            "[guide]\n[guide]\n[guide] (example.test)\n[ref]\n[x]\n[outer]\n"
            f"[x] (example.test)\n[reference]\n{long_label}\nKeep this line\n[[link]",
        )

    def test_common_markdown_destinations_are_stripped(self) -> None:
        self.write_sources(
            {
                "goals": "## Goals\n- G1: [Guide](./guide(v2).md) followed by words\n",
                "diagrams": "## Sample\n```\n[guide]: ./offline-guide.md\n```\n",
            }
        )
        self.configure()
        plan, _ = self.payload()
        self.assertEqual(plan["goals"][0]["title"], "[Guide] followed by words")
        self.assertNotIn("./offline-guide.md", plan["diagrams"][0]["body"])

    def test_lane_ids_follow_the_same_credential_redaction_as_text(self) -> None:
        credential = "xoxb-225556655-example-token"
        self.write_sources({"goals": f"## Goals\n- G1: Sample\n**Lanes:** {credential}, hull\n"})
        (self.briefs / f"{credential}.md").write_text("*Serves*: G1\n")
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n\n*Serves*: G1\n")
        self.log.write_text(f"ask {credential}:1 Sample question\n")
        self.only_goals()
        plan, body = self.payload()
        self.assertEqual([lane["id"] for lane in plan["lanes"]], ["hull"])
        self.assertEqual(plan["goals"][0]["lanes"], ["hull"])
        self.assertIsNone(plan["asks"][0]["lane"])
        self.assertNotIn(credential.encode(), body)

    def test_log_lane_and_projection_refuse_credential_shaped_lane_ids(self) -> None:
        credential = "xoxb-225556655-example-token"
        self.write_sources({"goals": "## Goals\n- G1: Sample\n**Lanes:** hull\n"})
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n", encoding="utf-8")
        self.log.write_text(f"ask {credential}:1 Sample question\n", encoding="utf-8")
        plan = readers.read_plan(self.only_goals()).model
        self.assertIsNone(plan.asks[0].lane)

        unsafe = replace(
            plan,
            goals=(replace(plan.goals[0], lanes=(credential, "hull")),),
            lanes=(*plan.lanes, model.Lane(credential, None, None, (), plan.lanes[0].source)),
            asks=(replace(plan.asks[0], lane=credential),),
        )
        projected = publish._project(unsafe, {credential: ["Synthetic session"]})
        self.assertEqual([lane["id"] for lane in projected["lanes"]], ["hull"])
        self.assertEqual(projected["goals"][0]["lanes"], ["hull"])
        self.assertIsNone(projected["asks"][0]["lane"])

        config_file = self.home / settings.FILENAME
        doc = json.loads(config_file.read_bytes())
        doc["briefs"]["lane_folders"][credential] = str(self.hull)
        config_file.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(settings.load(str(self.home)).reason, settings.MALFORMED)

    def test_caps_keep_redaction_markers_whole(self) -> None:
        from compass_runtime import records  # noqa: PLC0415

        for limit in (512, 8192):
            with self.subTest(limit=limit):
                marker = records.SECRET_MARKER
                for remaining in range(1, len(marker)):
                    text = "x" * (limit - 1 - remaining) + marker + " suffix"
                    capped = publish._cap(text, limit)
                    self.assertLessEqual(len(capped), limit)
                    self.assertNotIn(marker[:2], capped.removesuffix(marker))

    def test_private_child_session_never_joins_public_parent(self) -> None:
        child = self.hull / "sealed"
        child.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(child, target_is_directory=True)
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n")
        for private in (
            {"roots": [str(alias)]},
            {"markers": [{"value": "sealed", "mode": "component"}]},
            {"marker_files": [".restricted"]},
        ):
            with self.subTest(private=private):
                if "marker_files" in private:
                    (child / ".restricted").touch()
                self.configure(private=private)
                app = self.application()
                app.snapshot.publish(
                    (app.config.window_hours, False),
                    b"{}",
                    folders=(
                        ("claude", "private", str(child)),
                        ("claude", "alias", str(alias)),
                        ("claude", "public", str(self.hull)),
                    ),
                )
                self.assertEqual(
                    self.payload(app)[0]["lanes"][0]["sessions"], ['session:["claude","public"]']
                )

    def test_unmeasured_join_differs_from_warm_zero(self) -> None:
        for slug in ("hull", "none", "refused"):
            (self.briefs / f"{slug}.md").write_text("## Goal\nSample lane\n")
        refused = self.root / "refused"
        refused.mkdir()
        (refused / ".restricted").touch()
        self.configure(briefs={"lane_folders": {"hull": str(self.hull), "refused": str(refused)}})
        app = self.application()
        cold = {row["id"]: row["sessions"] for row in self.payload(app)[0]["lanes"]}
        app.snapshot.publish((app.config.window_hours, False), b"{}", folders=())
        warm = {row["id"]: row["sessions"] for row in self.payload(app)[0]["lanes"]}
        self.assertEqual(cold, {"hull": None, "none": None, "refused": None})
        self.assertEqual(warm, {"hull": [], "none": None, "refused": None})

    @unittest.skipIf(os.geteuid() == 0, "root reads a directory whatever its mode")
    def test_unexaminable_session_folder_leaves_the_join_unmeasured(self) -> None:
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n")
        locked = self.root / "locked"
        (locked / "inner").mkdir(parents=True)
        sealed = self.root / "sealed"
        (sealed / "inner").mkdir(parents=True)
        policy = self.configure(private={"roots": [str(sealed)]}).sources.policy
        app = self.application()

        def lanes(*folders: Path) -> Any:
            app.snapshot.publish(
                (app.config.window_hours, False),
                b"{}",
                folders=(
                    ("claude", "public", str(self.hull)),
                    *(("claude", f"s{index}", str(path)) for index, path in enumerate(folders)),
                ),
            )
            return self.payload(app)[0]["lanes"][0]["sessions"]

        public = ['session:["claude","public"]']
        self.assertEqual(lanes(locked / "inner", self.root / "gone"), public)
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o700)
        # The locked folder might sit below the lane folder, so neither a full nor an empty
        # list would be true.
        self.assertIsNone(lanes(locked / "inner"))
        self.assertIsNone(runtime_io.plan_session_ancestry(str(locked / "inner"), policy))
        # A private folder is excluded rather than unexamined, even when it cannot be listed.
        sealed.chmod(0o111)
        self.addCleanup(sealed.chmod, 0o700)
        self.assertEqual(lanes(sealed / "inner"), public)
        self.assertEqual(
            runtime_io.plan_session_ancestry(str(sealed / "inner"), policy), frozenset()
        )
        # A folder that can be entered but not listed cannot be cleared of marker files, so it
        # is not examined, unless an exact marker name or a private identity settles it.
        listed_only = self.hull / "exec"
        (listed_only / "inner").mkdir(parents=True)
        listed_only.chmod(0o111)
        self.addCleanup(listed_only.chmod, 0o700)
        self.assertIsNone(lanes(listed_only / "inner"))
        self.assertIsNone(runtime_io.plan_session_ancestry(str(listed_only / "inner"), policy))
        listed_only.chmod(0o700)
        (listed_only / ".restricted").touch()
        listed_only.chmod(0o111)
        self.assertEqual(lanes(listed_only / "inner"), public)
        # Even one that cannot be entered at all is identified by its metadata.
        sealed.chmod(0)
        self.assertEqual(lanes(sealed, sealed / "inner"), public)
        for folder in (sealed, sealed / "inner"):
            self.assertEqual(runtime_io.plan_session_ancestry(str(folder), policy), frozenset())

    def test_root_owned_and_crowded_ancestors_keep_the_join_measured(self) -> None:
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n")
        crowded = self.root / "crowded"
        (crowded / "inner").mkdir(parents=True)
        for index in range(4100):
            (crowded / f"entry-{index}").touch()
        policy = self.configure().sources.policy
        app = self.application()
        app.snapshot.publish(
            (app.config.window_hours, False),
            b"{}",
            folders=(
                ("claude", "public", str(self.hull)),
                ("claude", "root", "/"),
                ("claude", "tmp", "/tmp"),
                ("claude", "crowded", str(crowded / "inner")),
            ),
        )
        lanes = self.payload(app)[0]["lanes"]
        self.assertEqual(lanes[0]["sessions"], ['session:["claude","public"]'])
        for folder in ("/", "/tmp"):
            self.assertIsNotNone(runtime_io.plan_session_ancestry(folder, policy))
        # The root folder is examined, not merely excluded.
        self.assertTrue(runtime_io.plan_session_ancestry("/", policy))
        # Only a lookup the system refuses leaves the join unmeasured.
        for error, expected in (
            (errno.EMFILE, None),
            (errno.EIO, None),
            (errno.ENOENT, frozenset()),
            (errno.ENOTDIR, frozenset()),
            (errno.ELOOP, frozenset()),
        ):
            with (
                self.subTest(errno=errno.errorcode[error]),
                mock.patch.object(
                    runtime_io, "_session_identities", side_effect=OSError(error, "probe")
                ),
            ):
                self.assertEqual(runtime_io.plan_session_ancestry("/", policy), expected)
        # A marker scan over the cap cannot clear the folder, so it joins no lane.
        self.assertEqual(
            runtime_io.plan_session_ancestry(str(crowded / "inner"), policy), frozenset()
        )

    def test_refused_lane_folder_has_a_path_free_reason(self) -> None:
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n")
        (self.hull / ".restricted").touch()
        self.configure()
        app = self.application()
        plan, body = self.payload(app)
        self.assertIn(
            {
                "kind": "lane folder",
                "label": "hull",
                "fileLabel": None,
                "position": None,
                "state": "refused",
                "reason": "private",
            },
            plan["sources"],
        )
        self.assertNotIn(os.fsencode(self.hull), body)
        report = diagnostics._plan_report(app.state)
        self.assertIn({"kind": "lane folder", "reason": "private"}, report["sources"])
        self.assertNotIn(str(self.hull), json.dumps(report))

    def test_draft_unavailable_differs_from_measured_no_proposals(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Primary goal\n"})
        self.only_goals()
        git(self.repo, "branch", "draft/plan")
        measured, _ = self.payload()
        git(self.repo, "branch", "-D", "draft/plan")
        unavailable, body = self.payload()
        self.assertIn(
            {
                "kind": "draft goals",
                "label": "Example",
                "fileLabel": None,
                "position": None,
                "state": "ok",
                "reason": None,
            },
            measured["sources"],
        )
        self.assertIn(
            {
                "kind": "draft goals",
                "label": "Example",
                "fileLabel": None,
                "position": None,
                "state": "refused",
                "reason": "branch missing",
            },
            unavailable["sources"],
        )
        self.assertEqual(unavailable["goals"], measured["goals"])
        self.assertNotIn(b"draft/plan", body)

    def test_target_ref_marker_matches_case_and_nfd_variants_before_blob(self) -> None:
        git(self.repo, "config", "core.precomposeunicode", "false")
        self.write_sources({"anchor": "Keep the parent in the checkout"})
        run = git_status.PlanTreeReader._run
        for name, marker_file in (
            (".RESTRICTED", ".restricted"),
            (".re\u0301stricted", ".réstricted"),
        ):
            git(self.repo, "switch", "-qc", "target")
            (self.repo / "plan" / name).touch()
            self.write_sources({"goals": "## Goals\n- G1: CANARY_REF_MARKER\n"})
            git(self.repo, "switch", "main")
            git(self.repo, "branch", "-f", "draft/plan", "target")
            self.assertFalse((self.repo / "plan" / name).exists())
            self.only_goals(private={"marker_files": [marker_file]})
            path = self.home / settings.FILENAME
            doc = json.loads(path.read_bytes())
            doc["repos"][0]["files"]["goals"].append("plan/second.md")
            for primary in (True, False):
                with self.subTest(name=name, primary=primary):
                    doc["repos"][0]["ref"] = "target" if primary else "main"
                    path.write_text(json.dumps(doc), encoding="utf-8")
                    with mock.patch.object(
                        git_status.PlanTreeReader, "_run", autospec=True, side_effect=run
                    ) as observed:
                        plan, body = self.payload()
                    kind = "goals" if primary else "draft goals"
                    self.assertEqual(
                        next(row["reason"] for row in plan["sources"] if row["kind"] == kind),
                        "private",
                    )
                    self.assertNotIn(b"CANARY_REF_MARKER", body)
                    self.assertTrue(
                        all(call.args[1][0] != "cat-file" for call in observed.call_args_list)
                    )
                    listings = [
                        call.args[1]
                        for call in observed.call_args_list
                        if call.args[1][:2] == ("ls-tree", "-z")
                    ]
                    with self.subTest(listings=listings):
                        self.assertEqual(len(listings), 2 if primary else 4)
                        self.assertEqual(len(set(listings)), len(listings))
            git(self.repo, "branch", "-D", "target")

    def test_target_ref_marker_listing_fails_closed_before_blob(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: CANARY_LISTING\n"})
        self.only_goals()
        run = git_status.PlanTreeReader._run
        oid = b"a" * 40
        over_cap = b"".join(
            b"100644 blob " + oid + b"\tplan/entry-" + str(index).encode() + b"\0"
            for index in range(4097)
        )
        for listing in (None, over_cap):
            with self.subTest(over_cap=listing is not None):

                def broken_listing(
                    tree: git_status.PlanTreeReader,
                    args: tuple[str, ...],
                    deadline: float,
                    listing: bytes | None = listing,
                ) -> bytes:
                    if args[:2] == ("ls-tree", "-z") and args[-1] == "plan/":
                        if listing is None:
                            raise git_status.PlanGitError("unreadable")
                        return listing
                    return run(tree, args, deadline)

                with mock.patch.object(
                    git_status.PlanTreeReader, "_run", autospec=True, side_effect=broken_listing
                ) as observed:
                    plan, body = self.payload()
                self.assertEqual(plan["sources"][0]["state"], "refused")
                self.assertNotIn(b"CANARY_LISTING", body)
                self.assertTrue(
                    all(call.args[1][0] != "cat-file" for call in observed.call_args_list)
                )

    def test_draft_goal_has_proposal_status_without_progress_date(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Primary goal\n"})
        git(self.repo, "switch", "-qc", "draft/plan")
        self.write_sources({"goals": "## Goals\n- G1: Primary goal\n- G2: Draft goal\n"})
        git(self.repo, "switch", "main")
        self.only_goals()
        goals = self.payload()[0]["goals"]
        self.assertEqual([g["proposal"] for g in goals], [None, "Proposed, not merged"])
        self.assertTrue(all("date" not in goal and "at" not in goal for goal in goals))

    def test_untimestamped_ask_has_no_time_label(self) -> None:
        self.configure()
        self.log.write_text("ask hull:one Question\n")
        ask = self.payload()[0]["asks"][0]
        self.assertIsNone(ask["at"])
        self.assertIsNone(ask["timeLabel"])

    def test_diagnostics_only_echo_status_words(self) -> None:
        self.write_sources(
            {
                "tracker": "| Item | Status |\n| --- | --- |\n"
                "| Sample | https://example.test/a |\n"
                "| Other | unusual seabird |\n"
            }
        )
        self.configure(tracker={"tail_separators": []})
        report = diagnostics._plan_report(self.application().state)
        self.assertEqual(
            [row["word"] for row in report["unknown_statuses"]],
            ["Status not recognised", "unusual seabird"],
        )

    def test_diagnostics_hide_alpha_only_credentials(self) -> None:
        credential = "Bearer Abcdefghijklmnopqrstuvwx"
        self.write_sources(
            {"tracker": f"| Item | Status |\n| --- | --- |\n| Sample | {credential} |\n"}
        )
        self.configure(tracker={"tail_separators": []})
        report = diagnostics._plan_report(self.application().state)
        self.assertNotIn(credential, json.dumps(report))
        self.assertEqual(
            [row["word"] for row in report["unknown_statuses"]], ["Status not recognised"]
        )

    def test_disabled_payload_opens_nothing(self) -> None:
        self.configure()
        app = self.application(plan_enabled=False)
        with mock.patch.object(
            runtime_io, "read_plan_settings", wraps=runtime_io.read_plan_settings
        ) as read:
            self.assertEqual(
                publish.payload(app.config, app.state),
                {"state": "refused", "reason": "plan is off"},
            )
        read.assert_not_called()

    def test_disabled_collection_captures_no_folders(self) -> None:
        def captured_folders(enabled: bool) -> Any:
            app = self.application(
                [{"sid": "one", "state": "working", "last_activity": 4_900.0}],
                plan_enabled=enabled,
            )
            board = app.collect(show_all=False)

            def collect(*, show_all: bool) -> Any:
                self.assertFalse(show_all)
                sessions.apply_project_identity(app.config, board["sessions"][0], str(self.hull))
                return board

            with mock.patch.object(app, "collect", side_effect=collect):
                app.collect_json(show_all=False)
            return app.snapshot.session_folders((app.config.window_hours, False))

        self.assertEqual(captured_folders(False), ())
        self.assertEqual(captured_folders(True), (("claude", "one", str(self.hull)),))

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
        self.assertEqual(diagram["body"], 'flowchart LR\n  A["diagram.example.test --> B')
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
        self.assertIn("bounded.example.test --> B", diagram["body"])
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
        self.assertIsNone(lanes["empty"]["sessions"])
        self.assertEqual(lanes["hull"]["title"], lanes["paint"]["title"])
        self.assertEqual(
            [(row["source"], row["lane"], row["timeLabel"], row["at"]) for row in payload["asks"]],
            [
                ("Coordination", {"id": "paint", "title": "Same lane title"}, None, None),
                (
                    "Coordination",
                    {"id": "hull", "title": "Same lane title"},
                    "from the log",
                    "2026-01-02T03:04:05Z",
                ),
                ("Coordination", None, None, None),
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


class LinkProjectionTest(unittest.TestCase):
    def test_prose_that_only_resembles_a_link_is_kept(self) -> None:
        for text in (
            "metadata: foo, bar",
            "ping alice@corp: hello",
            "image@sha256:abcdef01",
            "release v1.2.3.4 shipped",
            "i.e.: see below",
            "notes on records.md",
            "a@b and c@d",
            "今日はリリース作業を行いました。次は?明日、レビューをお願いします。",
            "実験を行った．結果はA/Bの両方で改善した．詳細は付録を参照．",  # noqa: RUF001 - CJK prose
            "我们完成了迁移。下一步:更新文档，然后发布。",  # noqa: RUF001 - CJK prose
            "好的。为什么?",
            "完了。テスト:確認",
            "xwebcal:x",
            "git@host:x.gitx",
            "see webcal: later",
            "1tel: call me",
            "ping @team:design/ux",
            "arr[::2]/n",
            "[1:2]/3",
            "完了しました。詳細\uff0f補足は後で",
            "A\uff0fB testing",
            "see plan.md\u200b: notes",
            "ping alice@corp: 12:30/45",
        ):
            with self.subTest(text=text):
                self.assertEqual(records.hosts_only(text), (text, ()))

    def test_text_glued_to_a_link_stays_beside_its_host(self) -> None:
        for text, expected, host in (
            ("完了。https://example.test/p/CANARY", "完了。example.test", "example.test"),
            ("完了。example.test/p/CANARY", "完了。example.test", "example.test"),
            ("参考docs.example.test/d/CANARY", "参考docs.example.test", "docs.example.test"),
            ("a-localhost:3000/CANARY", "a-localhost", "localhost"),
            ("user:CANARY@host:org/repo.git", "host", "host"),
            ("参考docs.example.test\\CANARY", "参考[link]", None),
            ("ü-app.рф/CANARY", "[link]", None),
            ("例子。中国/CANARY，然后", "[link]，然后", None),  # noqa: RUF001 - CJK prose
            ("完了。example。test/CANARY", "完了。[link]", None),
            ("mail a@b then пример.рф/CANARY", "mail a@b then [link]", None),
            ("foo..example.рф/CANARY", "foo..[link]", None),
            ("u:p@secret-host:/srv/r.git", "[link][link]", None),
            ("webcal:CANARY@example.test/x", "example.test", "example.test"),
        ):
            with self.subTest(text=text):
                hosts = () if host is None else (host,)
                self.assertEqual(records.hosts_only(text), (expected, hosts))

    def test_prose_a_link_could_spell_stays_masked(self) -> None:
        # Each is prose here and a link elsewhere: `.md` is a country's top-level domain, git
        # reads `name@host:path` as a remote, and a word glued to a dotted quad is masked like
        # the hosts glued to one. Unmasking any of them would show what such a link carries.
        for text, expected, hosts in (
            ("README.md\\CANARY", "[link]", ()),
            ("v1.2.3.4/CANARY", "v1.2.3.4", ("1.2.3.4",)),
            ("docker image@sha256:abc/CANARY", "docker sha256", ("sha256",)),
            ("pkg@1.2.3:src/CANARY.js", "[link]", ()),
            ("完了。中国/CANARY", "[link]", ()),
        ):
            with self.subTest(text=text):
                self.assertEqual(records.hosts_only(text), (expected, hosts))


class KnownLinkOffsetsTest(unittest.TestCase):
    def test_linear_finder_matches_the_regex_search_at_every_offset(self) -> None:
        labels = [
            "a+b://x",
            "1+b://x y",
            "x.\u017f.com/",
            "\u017f" + "a" * 62 + ".com/",
            "a" * 63 + ".com/",
            "a" * 64 + ".com/",
            ".".join(["a"] * 126) + ".com/",
            ".".join(["a"] * 127) + ".com/",
            "\u0131example.com/ \u212a.test:80",
            "-a.com/ --.com/ a..b.com/",
            "a\u00e4.test/ \u017f-a.com/",
            "w\u0131ww.a/ localhost:3/",
        ]
        for text in labels:
            with self.subTest(text=text[:40]):
                known = records._KnownLinks(text)
                for offset in range(len(text) + 1):
                    found = known.match(offset)
                    expected = records._URL_START.search(text, offset)
                    self.assertEqual(
                        None if found is None else found.span(),
                        None if expected is None else expected.span(),
                    )


class LinkProjectionTimingTest(unittest.TestCase):
    # Measures elapsed time on adversarial input, to keep every link matcher linear.
    REAL_TIME_TESTS = True

    def test_adversarial_text_is_projected_in_linear_time(self) -> None:
        size = 250_000
        cases = {
            name: head + unit * ((size - len(head)) // len(unit)) + tail
            for name, head, unit, tail in (
                ("ascii and non-ascii letters", "", "aä", "!"),
                ("non-ascii letters and hyphens", "", "ä-a", "!"),
                ("scheme characters after plus signs", "", "a+", "!"),
                ("ideographic dots", "", "a。", "!"),
                ("full-width dotted labels", "", "ab\uff0e", "!"),
                ("non-ascii labels", "", "äb.", "!"),
                ("dashes", "", "-", "!"),
                ("scp-like remotes", "", "a@b:", "!"),
                ("userinfo", "", "a@", "!"),
                ("cyrillic", "", "п", "!"),
                ("digits and dots", "", "1.", "!"),
                ("glued data", "", "adata:", "!"),
                ("backslashes", "", "a.bc\\", "!"),
                ("brackets", "", "[", "!"),
                ("markdown destination", "[x](", "aä", ")"),
                ("markdown glued hosts", "", "[x](a-localhost/ ", "!"),
                ("userinfo before many glued hosts", "@", " x-localhost/", "!"),
                ("long s labels", "", "\u017f" * 63 + ".", "!"),
                ("kelvin labels", "", "\u212a" * 63 + ".", "!"),
                ("long s labels before a path", "", "\u017f" * 63 + ".", "com/"),
                ("overlong long s labels before a path", "", "\u017f" * 64 + ".", "com/"),
                ("repeated known links", "", "https://a.test/x ", "!"),
                ("repeated added links", "", "a.рф/x ", "!"),
                ("known links with no added form ahead", "", "//x ", "!"),
                ("bracketed addresses", "", "[::1]/ ", "!"),
                ("unclosed brackets of colons", "", "[1:", "!"),
                ("bracketed zones", "", "[::1%", "!"),
                ("full-width solidi after labels", "", "a.bc\uff0f", "!"),
                ("wide labels before solidi", "", "ab\uff0e\uff0f", "!"),
                ("zero-width characters after labels", "", "a.bc\u200b", "!"),
                ("a zero-width run before a path", "a.bc", "\u200b", "/"),
                ("scp-like remotes with colons", "", "a@b:c:", "!"),
                ("scp-like remotes before a far slash", "", "a@b:", "/x.git"),
                ("scp-like remotes with at signs", "", "a@b:c@", "/"),
                ("slashes, queries and hashes in userinfo", "", "a/?#", "@b.test/"),
                ("userinfo before www hosts", "", "a:b@www.", "!"),
            )
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                started = time.monotonic()
                records.hosts_only(text)
                # The slow shapes took 90 to 105 s before; linear projection takes under 0.4 s
                # here and up to 1.1 s on CI's 3.12 runner (measured 2026-11-27), so 5 s separates
                # them without failing on a slow runner.
                self.assertLess(time.monotonic() - started, 5.0)

    def test_an_added_link_before_a_known_one_scans_in_linear_time(self) -> None:
        # Linear time quadruples from 250 KB to 1 MB; a rescan to the line end for each added
        # link grows sixteenfold.
        for unit, tail in (
            ("a.рф/< //x ", "!"),
            ("x-localhost/< https://k.test/ ", ">"),
            ("[::1]/< www.k.test/ ", ">"),
            ("a.bc\uff0f< u:p@www.k.test ", ">"),
            # Each known link read the text back to an added link far after it: 4 s at 250 KB.
            ("//x ", "a.рф/x"),
        ):
            with self.subTest(unit=unit):
                took = []
                for size in (250_000, 1_000_000):
                    text = unit * (size // len(unit)) + tail
                    started = time.monotonic()
                    records.hosts_only(text)
                    took.append(time.monotonic() - started)
                self.assertLess(took[0], 5.0)
                self.assertLess(took[1], 8 * took[0])

    def test_a_long_userinfo_after_many_added_links_is_read_once(self) -> None:
        # Reading the userinfo back again for each added link before it was quadratic: 20 KB
        # of added links before a 20 KB token took 3.3 s (measured 2026-11-27).
        took = []
        for size in (250_000, 1_000_000):
            text = "a.рф/x " * (size // 14) + "a" * (size // 2) + "@b.test/"
            started = time.monotonic()
            self.assertEqual(records.hosts_only(text)[1][-1], "b.test")
            took.append(time.monotonic() - started)
        self.assertLess(took[0], 5.0)
        self.assertLess(took[1], 8 * took[0])
