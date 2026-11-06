"""Real-file stage entry and durable intent boundaries."""

from __future__ import annotations

import dataclasses
import http.client
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import cli, deliveries, spacedock, tripwires
from compass_runtime.state import build_runtime_state

from .support import make_runtime, make_server, poll_fast

# How long a test waits for a step that happens at once on an idle runner: a busy runner
# is slower, not red.
WAIT_SEC = 30.0


class TripwireTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config, self.state = make_runtime(state_home=str(self.root / "home"))
        self.now = 1_800_000_000.0
        self.workflow = self.root / "workflow"
        self.workflow.mkdir()
        (self.workflow / "README.md").write_text(
            "---\ncommissioned-by: spacedock@0.27.2\nstages:\n  states:\n"
            "    - name: intake\n      initial: true\n    - name: build\n"
            "    - name: review\n    - name: done\n      terminal: true\n---\n"
        )
        self.boot = [
            {
                "command": "boot",
                "definition_dir": str(self.workflow),
                "entity_dir": str(self.workflow),
                "dispatchable": [],
            }
        ]
        self.notify = mock.Mock(return_value="handed-over")

    def write(self, stage: str, slug: str = "task") -> None:
        path = self.workflow / (slug + ".md")
        path.write_text("---\nstatus: " + stage + "\n---\nPRIVATE BODY\n")
        os.utime(path, (self.now, self.now))

    def observe(self) -> dict[str, Any]:
        source: dict[str, Any] = spacedock.session_workflows(
            self.config, self.state, self.boot, [], self.now, 3600
        )[0]["tripwire_source"]
        return source

    def collect(self) -> dict[str, Any]:
        source = self.observe()
        return tripwires.collect(self.config, self.state, [source], self.now, "mac", self.notify)

    def act(self, action: str, stage: str = "review", revision: str = "") -> dict[str, Any]:
        return tripwires.mutate(
            self.config,
            self.state,
            {
                "action": action,
                "id": self.observe()["id"],
                "stage": stage,
                "expected_revision": revision,
            },
            self.now,
        )

    def test_source_is_current_frontmatter_and_initial_stage_is_evaluated(self) -> None:
        self.write("intake")
        source = self.observe()
        self.assertEqual(64, len(source["id"]))
        self.assertNotIn(str(self.root), json.dumps(source))
        self.assertNotIn("PRIVATE BODY", json.dumps(source))
        self.assertEqual("intake", source["entities"][0]["stage"])
        self.assertEqual(self.now, source["entities"][0]["source_written_at"])
        self.assertEqual("entity-state", source["entities"][0]["source"])

    def test_one_shot_rearm_restart_and_failed_latch_retry(self) -> None:
        self.write("build")
        self.collect()
        self.assertTrue(self.act("save")["ok"])
        self.collect()
        self.notify.assert_not_called()
        self.now += 1
        self.write("review")
        with mock.patch.object(tripwires, "save", return_value=False):
            failed = self.collect()
        self.notify.assert_not_called()
        self.assertIn("Could not save the trip", failed["rules"][0]["why"])
        tripped = self.collect()["rules"][0]
        self.assertEqual("tripped", tripped["state"])
        self.assertEqual(1, self.notify.call_count)
        self.now += 1
        self.write("review", "second")
        self.collect()
        self.assertEqual(1, self.notify.call_count)
        self.config, self.state = make_runtime(state_home=self.config.state_home)
        self.collect()
        self.assertEqual(1, self.notify.call_count)
        self.assertTrue(self.act("rearm", revision=tripped["revision"])["ok"])
        self.collect()
        self.now += 1
        self.write("build")
        self.collect()
        self.now += 1
        self.write("review")
        self.collect()
        self.assertEqual(2, self.notify.call_count)

    def test_unchanged_save_preserves_latch_and_revision_until_explicit_rearm(self) -> None:
        self.write("build")
        self.collect()
        armed = self.act("save")["rule"]
        self.assertEqual(armed, self.act("save", revision=armed["revision"])["rule"])
        self.now += 1
        self.write("review")
        tripped = self.collect()["rules"][0]
        before = Path(tripwires.store_path(self.config)).read_bytes()
        saved = self.act("save", revision=tripped["revision"])
        self.assertEqual("tripped", saved["rule"]["state"])
        self.assertEqual(tripped["revision"], saved["rule"]["revision"])
        self.assertEqual(before, Path(tripwires.store_path(self.config)).read_bytes())
        self.assertEqual(409, self.act("save", revision="0" * 32)["status"])
        for stage in ("build", "review"):
            self.now += 1
            self.write(stage)
            self.collect()
        self.assertEqual(1, self.notify.call_count)
        rearmed = self.act("rearm", revision=tripped["revision"])["rule"]
        self.assertEqual("armed", rearmed["state"])
        self.assertNotEqual(tripped["revision"], rearmed["revision"])
        edited = self.act("save", stage="done", revision=rearmed["revision"])["rule"]
        self.assertEqual("done", edited["stage"])
        self.assertNotEqual(rearmed["revision"], edited["revision"])
        self.now += 1
        self.write("done")
        self.collect()
        self.assertEqual(2, self.notify.call_count)

    def test_gaps_unknown_stages_future_files_and_skipped_stages_never_cross(self) -> None:
        self.write("build")
        self.collect()
        self.act("save")
        for kind in ("gap", "missing", "unknown", "future", "clock"):
            with self.subTest(kind=kind):
                self.now += 1
                self.write("build")
                self.collect()
                if kind == "gap":
                    self.now += 61
                elif kind == "missing":
                    (self.workflow / "task.md").unlink()
                    self.collect()
                elif kind == "unknown":
                    self.write("unknown")
                    self.collect()
                elif kind == "future":
                    path = self.workflow / "task.md"
                    os.utime(path, (self.now + 100, self.now + 100))
                    self.collect()
                else:
                    self.now -= 20
                    self.collect()
                self.now += 1
                self.write("review")
                self.collect()
                self.notify.assert_not_called()
        self.now += 1
        self.write("done")
        self.collect()
        self.notify.assert_not_called()

    def test_state_directory_identity_and_display_cap_do_not_bind_or_limit_rules(self) -> None:
        self.write("build")
        original = self.observe()["id"]
        other = self.root / "other"
        other.mkdir()
        self.boot[0]["entity_dir"] = str(other)
        self.assertNotEqual(original, self.observe()["id"])
        self.boot[0]["entity_dir"] = str(self.workflow)
        for number in range(20):
            self.write("build", f"task-{number}")
        source = self.observe()
        self.assertEqual(21, source["evaluated"])
        self.collect()
        self.act("save")
        self.now += 1
        self.write("review", "task-19")
        self.collect()
        self.assertEqual(1, self.notify.call_count)
        for number in range(100):
            self.write("build", f"capped-{number}")
        self.assertEqual(96, self.observe()["evaluated"])
        self.assertTrue(self.observe()["partial"])

    def test_duplicate_slug_is_unavailable_even_when_its_twin_is_beyond_the_cap(self) -> None:
        self.write("build")
        folder = self.workflow / "task"
        folder.mkdir()
        path = folder / "index.md"
        path.write_text("---\nstatus: review\n---\n")
        self.now += 1
        os.utime(path, (self.now, self.now))
        for capped in (False, True):
            with self.subTest(capped=capped):
                if capped:
                    self.now += 1
                    for number in range(100):
                        self.write("build", f"filler-{number}")
                    self.now += 1
                    os.utime(path, (self.now, self.now))
                source = self.observe()
                self.assertNotIn("task", [row["slug"] for row in source["entities"]])
                self.assertTrue(source["partial"])
                self.collect()
                old = tripwires.load(self.config) or {}
                self.act("save", revision=next(iter(old.values()))["revision"] if old else "")
                self.now += 1
                self.collect()
                self.notify.assert_not_called()

    def test_store_corruption_off_switch_and_atomic_mode(self) -> None:
        self.write("build")
        self.collect()
        result = self.act("save")
        self.assertTrue(result["ok"])
        path = Path(tripwires.store_path(self.config))
        if os.name == "posix":
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
        original = path.read_bytes()
        overflow = json.loads(original)
        overflow["rules"][0]["saved_at"] = 10**1000
        for corrupt in (
            b"{",
            b'{"v":2,"rules":[]}',
            b"x" * (tripwires.READ_CAP + 1),
            json.dumps(overflow).encode(),
        ):
            path.write_bytes(corrupt)
            self.assertIn("could not be read", self.collect()["error"])
            self.assertFalse(self.act("save")["ok"])
            self.assertEqual(corrupt, path.read_bytes())
            self.notify.assert_not_called()
        path.write_bytes(original)
        self.config = dataclasses.replace(self.config, tripwires_enabled=False)
        with (
            mock.patch.object(tripwires, "load") as read,
            mock.patch.object(tripwires, "save") as write,
        ):
            tripwires.collect(self.config, self.state, [], self.now, "mac", self.notify)
            tripwires.mutate(self.config, self.state, {}, self.now)
        read.assert_not_called()
        write.assert_not_called()
        self.config = dataclasses.replace(
            self.config, tripwires_enabled=True, spacedock_enabled=False
        )
        result = tripwires.collect(self.config, self.state, [], self.now, "mac", self.notify)
        self.assertEqual(1, len(result["rules"]))
        self.assertFalse(result["rules"][0]["available"])
        self.assertFalse(result["source_enabled"])
        self.assertIn("Project reads are off", result["rules"][0]["why"])

    def test_sixty_fifth_rule_is_refused_without_eviction(self) -> None:
        self.write("build")
        source = self.observe()
        for number in range(65):
            candidate = {**source, "id": f"{number:064x}"}
            tripwires.collect(self.config, self.state, [candidate], self.now, "", self.notify)
            result = tripwires.mutate(
                self.config,
                self.state,
                {
                    "action": "save",
                    "id": candidate["id"],
                    "stage": "review",
                    "expected_revision": "",
                },
                self.now,
            )
            self.assertEqual(number < 64, result["ok"])
        stored = tripwires.load(self.config)
        assert stored is not None
        self.assertEqual(64, len(stored))
        self.assertIn("0" * 64, stored)

    def app(self) -> Any:
        root = self.root / "sessions"
        path = root / "2026" / "09" / "14" / "rollout-source.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        wrapped = json.dumps(
            {"status": "fulfilled", "value": {"exit_code": 0, "output": json.dumps(self.boot[0])}}
        )
        rows = [
            {"type": "session_meta", "payload": {"id": "source", "cwd": str(self.root)}},
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": [{"type": "input_text", "text": wrapped}],
                },
            },
        ]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        os.utime(path, (self.now, self.now))
        self.config = dataclasses.replace(
            self.config, store_roots={**self.config.store_roots, "codex.sessions": (str(root),)}
        )
        app = cli.build_application(self.config, self.state, clock=lambda: self.now)
        app.native_notifier = lambda _platform: "mac"
        app.popup_notifier = self.notify
        return app

    def socket(self, app: Any) -> Any:
        httpd = make_server(application=app)
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()

        def request(
            method: str, path: str, body: dict[str, Any] | None = None, origin: str = ""
        ) -> tuple[int, bytes]:
            connection = http.client.HTTPConnection(
                "127.0.0.1", httpd.server_port, timeout=WAIT_SEC
            )
            try:
                connection.request(
                    method,
                    path,
                    body=json.dumps(body) if body else None,
                    headers={
                        "Content-Type": "application/json",
                        **({"Origin": origin} if origin else {}),
                    },
                )
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        def close() -> None:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        self.addCleanup(close)
        return request

    def test_actual_collector_application_socket_and_concurrent_latch(self) -> None:
        self.write("build")
        app = self.app()
        request = self.socket(app)
        code, body = request("GET", "/api/data")
        self.assertEqual(200, code)
        source = json.loads(body)["tripwires"]["sources"][0]
        self.assertEqual("entity-state", source["entities"][0]["source"])
        mutation = {
            "action": "save",
            "id": source["id"],
            "stage": "review",
            "expected_revision": "",
        }
        self.assertEqual(403, request("POST", "/api/tripwire", mutation, "http://other.invalid")[0])
        self.assertEqual(
            400, request("POST", "/api/tripwire", {**mutation, "path": "/tmp/forged"})[0]
        )
        self.assertEqual(400, request("POST", "/api/tripwire", {**mutation, "at": self.now})[0])
        self.assertEqual(
            413, request("POST", "/api/tripwire", {**mutation, "stage": "x" * 1100})[0]
        )
        self.assertEqual(200, request("POST", "/api/tripwire", mutation)[0])
        self.assertEqual(409, request("POST", "/api/tripwire", mutation)[0])
        self.notify.assert_not_called()
        self.now += 1
        self.write("review")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: app.collect(show_all=False), range(4)))
        self.assertEqual(1, self.notify.call_count)
        self.assertTrue(all(r["tripwires"]["rules"][0]["state"] == "tripped" for r in results))
        delivery = deliveries.load(self.config)
        self.assertEqual("stage-tripwire", delivery[-1]["lane"])
        self.assertEqual("handed-over", delivery[-1]["outcome"])
        self.assertNotIn(str(self.root), json.dumps(results[0]["tripwires"]))
        path = Path(tripwires.store_path(self.config))
        overflow = json.loads(path.read_bytes())
        overflow["rules"][0]["saved_at"] = 10**1000
        corrupt = json.dumps(overflow).encode()
        path.write_bytes(corrupt)
        self.now += 1
        code, body = request("GET", "/api/data")
        self.assertEqual(200, code)
        self.assertTrue(json.loads(body)["sessions"])
        self.assertIn("could not be read", json.loads(body)["tripwires"]["error"])
        self.assertEqual(corrupt, path.read_bytes())
        self.assertEqual(1, self.notify.call_count)

    def test_application_sequence_survives_handled_clear_replacement_and_restart(self) -> None:
        self.write("review")
        request = self.socket(self.app())
        source = json.loads(request("GET", "/api/data")[1])["tripwires"]["sources"][0]
        mutation = {
            "action": "save",
            "id": source["id"],
            "stage": "review",
            "expected_revision": "",
        }
        self.assertEqual(200, request("POST", "/api/tripwire", mutation)[0])
        request("GET", "/api/data")
        counts = [self.notify.call_count]

        def observe(stage: str, slug: str = "task") -> Any:
            self.now += self.config.collect_memo_sec + 1
            self.write(stage, slug)
            return json.loads(request("GET", "/api/data")[1])

        observe("build")
        counts.append(self.notify.call_count)
        observe("review")
        counts.append(self.notify.call_count)
        observe("review", "second")
        counts.append(self.notify.call_count)
        result = observe("review")
        counts.append(self.notify.call_count)
        self.assertEqual([0, 0, 1, 1, 1], counts)
        rule = result["tripwires"]["rules"][0]
        mutation.update(action="rearm", expected_revision=rule["revision"])
        self.assertEqual(200, request("POST", "/api/tripwire", mutation)[0])
        observe("build")
        observe("review")
        self.assertEqual(2, self.notify.call_count)
        self._assert_session_lifecycle_keeps_rule(request, source)

    def _assert_session_lifecycle_keeps_rule(self, request: Any, source: dict[str, Any]) -> None:
        path = Path(tripwires.store_path(self.config))
        before = path.read_bytes()
        self.assertEqual(
            200, request("POST", "/api/dismiss", {"harness": "codex", "sid": "source"})[0]
        )
        dismissed = json.loads(request("GET", "/api/data")[1])
        self.assertEqual([], dismissed["sessions"])
        self.assertEqual("tripped", dismissed["tripwires"]["rules"][0]["state"])
        rollout = next((self.root / "sessions").rglob("rollout-*.jsonl"))
        with rollout.open("a") as handle:
            handle.write(
                json.dumps(
                    {"type": "event_msg", "payload": {"type": "user_message", "message": "/clear"}}
                )
                + "\n"
            )
        self.now += self.config.collect_memo_sec + 1
        os.utime(rollout, (self.now, self.now))
        request("GET", "/api/data")
        self.assertEqual(before, path.read_bytes())
        replacement = rollout.with_name("rollout-replacement.jsonl")
        replacement.write_text(rollout.read_text().replace('"id": "source"', '"id": "replacement"'))
        rollout.unlink()
        self.now += self.config.collect_memo_sec + 1
        os.utime(replacement, (self.now, self.now))
        replaced = json.loads(request("GET", "/api/data")[1])
        self.assertEqual("replacement", replaced["sessions"][0]["sid"])
        self.assertEqual(source["id"], replaced["tripwires"]["sources"][0]["id"])
        self.state = build_runtime_state(self.config, started=self.now)
        restarted = cli.build_application(self.config, self.state, clock=lambda: self.now)
        restarted.native_notifier = lambda _platform: "mac"
        restarted.popup_notifier = self.notify
        request = self.socket(restarted)
        result = json.loads(request("GET", "/api/data")[1])
        self.assertEqual("tripped", result["tripwires"]["rules"][0]["state"])
        replacement.unlink()
        self.now += self.config.collect_memo_sec + 1
        absent = json.loads(request("GET", "/api/data")[1])
        self.assertEqual([], absent["sessions"])
        self.assertEqual("tripped", absent["tripwires"]["rules"][0]["state"])
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(2, self.notify.call_count)

    def test_taxonomy_change_and_symlink_reacquisition_reset_the_baseline(self) -> None:
        self.write("build")
        self.collect()
        self.act("save")
        readme = self.workflow / "README.md"
        original = readme.read_text()
        readme.write_text(original.replace("    - name: review\n", "    - name: verify\n"))
        self.now += 1
        self.write("review")
        self.assertFalse(self.collect()["rules"][0]["available"])
        readme.write_text(original)
        self.assertIn("baseline reset", self.collect()["rules"][0]["why"])
        self.notify.assert_not_called()
        self.now += 1
        self.write("build")
        self.collect()
        path = self.workflow / "task.md"
        external = self.root / "outside.md"
        external.write_text("---\nstatus: review\n---\n")
        path.unlink()
        try:
            path.symlink_to(external)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with mock.patch.object(spacedock, "open_regular", wraps=spacedock.open_regular) as reader:
            self.collect()
        self.assertNotIn(str(external), [call.args[0] for call in reader.call_args_list])
        self.notify.assert_not_called()
        path.unlink()
        self.now += 1
        self.write("review")
        self.collect()
        self.notify.assert_not_called()

    def test_latch_precedes_notifier_and_failed_atomic_replace_keeps_old_intent(self) -> None:
        self.write("build")
        self.collect()
        rule = self.act("save")["rule"]
        path = Path(tripwires.store_path(self.config))
        before = path.read_bytes()
        with mock.patch("compass_runtime.tripwires.os.replace", side_effect=OSError("read-only")):
            self.assertFalse(self.act("save", stage="done", revision=rule["revision"])["ok"])
        self.assertEqual(before, path.read_bytes())
        self.assertEqual([], list(path.parent.glob(".tripwires-*")))
        self.now += 1
        self.write("review")

        def notified(_title: str, _message: str) -> str:
            stored = tripwires.load(self.config)
            assert stored is not None
            self.assertEqual("tripped", stored[rule["id"]]["state"])
            return "refused"

        self.notify.side_effect = notified
        row = self.collect()["rules"][0]
        self.assertEqual("tripped", row["state"])
        self.assertIn("returned an error", row["delivery_why"])
        self.config, self.state = make_runtime(state_home=self.config.state_home)
        self.collect()
        self.assertEqual(1, self.notify.call_count)

    def test_equal_names_and_slugs_stay_distinct_through_application(self) -> None:
        a = self.workflow
        b = self.root / "other" / a.name
        b.mkdir(parents=True)
        (a / "README.md").write_text(
            (a / "README.md").read_text().replace("stages:", "title: First workflow\nstages:", 1)
        )
        (b / "README.md").write_text(
            (a / "README.md").read_text().replace("First workflow", "Second workflow")
        )
        self.write("build")
        (b / "task.md").write_text("---\nstatus: build\n---\n")
        os.utime(b / "task.md", (self.now, self.now))
        app = self.app()
        rollout = next((self.root / "sessions").rglob("rollout-*.jsonl"))
        second_boot = {**self.boot[0], "definition_dir": str(b), "entity_dir": str(b)}
        with rollout.open("a") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "output": json.dumps(second_boot),
                        },
                    }
                )
                + "\n"
            )
        os.utime(rollout, (self.now, self.now))
        request = self.socket(app)
        sources = json.loads(request("GET", "/api/data")[1])["tripwires"]["sources"]
        self.assertEqual(2, len(sources))
        first = next(row for row in sources if row["goal"] == "First workflow")
        self.assertEqual(
            200,
            request(
                "POST",
                "/api/tripwire",
                {"action": "save", "id": first["id"], "stage": "review", "expected_revision": ""},
            )[0],
        )
        self.now += self.config.collect_memo_sec + 1
        (b / "task.md").write_text("---\nstatus: review\n---\n")
        os.utime(b / "task.md", (self.now, self.now))
        request("GET", "/api/data")
        self.notify.assert_not_called()
        self.now += self.config.collect_memo_sec + 1
        self.write("review")
        output = json.loads(request("GET", "/api/data")[1])["tripwires"]
        self.assertEqual(1, self.notify.call_count)
        self.assertEqual(first["id"], output["rules"][0]["id"])
        self.assertNotIn(str(self.root), json.dumps(output))

    def test_indistinguishable_workflows_refuse_arming_and_shared_source_is_one_rule(self) -> None:
        self.write("build")
        source = self.observe()
        session: dict[str, Any] = {
            "harness": "codex",
            "sid": "one",
            "title": "Same label",
            "spacedock": {
                "workflows": [
                    {"tripwire_source": source},
                    {"tripwire_source": {**source, "id": "b" * 64}},
                ]
            },
        }
        sources = tripwires.sources_from_sessions([session])
        self.assertTrue(all(row["ambiguous"] for row in sources))
        tripwires.collect(self.config, self.state, sources, self.now, "", self.notify)
        self.assertEqual(tripwires.AMBIGUOUS, self.act("save")["error"])
        session["spacedock"]["workflows"].pop()
        shared = tripwires.sources_from_sessions([session, {**session, "sid": "two"}])
        self.assertEqual(1, len(shared))
        self.assertFalse(shared[0]["ambiguous"])
