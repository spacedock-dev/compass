"""The typed client's shared fixtures are the real server's bytes, regenerated on demand.

TypeScript tests read `frontend/test/fixtures/client-contract/` verbatim. This module is the
other half of that contract: it rebuilds every file from the live `Application` and
`CompassHTTPServer` and requires byte equality, so a backend change that moves a response
fails here, in Python, before a client test can pass against a stale copy.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any, ClassVar, Self
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "frontend" / "test" / "fixtures" / "client-contract"

sys.path.insert(0, str(SCRIPTS))
import regen_client_fixtures as regen  # noqa: E402 - development script path

# The fixture map from the migration analysis, one entry per scenario a client must be
# able to replay. A scenario that cannot be produced by the real server is not listed
# here; the generator's own `UNREACHABLE` table says why, and the count is asserted below.
REQUIRED = frozenset(
    {
        "data-healthy",
        "data-empty",
        "data-unavailable",
        "data-identity-collisions",
        "data-show-all",
        "data-restarted-build",
        "data-forbidden-cross-site",
        "data-forbidden-host",
        "api-not-found",
        "stream-initial-revision",
        "stream-heartbeat",
        "stream-revision-after-change",
        "stream-restarted-build",
        "stream-forbidden-frame",
        "stream-forbidden-cross-site",
        "stream-budget-exhausted",
        "context-project",
        "context-focused-session",
        "context-missing-project",
        "context-overlong-project",
        "context-malformed-session",
        "context-refresh-without-session",
        "context-refresh-model-disabled",
        "context-forbidden-host",
        "annotations-empty",
        "annotations-populated",
        "annotations-disabled",
        "annotations-forbidden-host",
        "annotate-stored",
        "annotate-unchanged",
        "annotate-refused",
        "annotate-unwritable",
        "annotate-untrusted",
        "annotate-unreadable",
        "annotate-disabled",
        "annotate-too-large",
        "annotate-malformed-identity",
        "annotate-forbidden-origin",
        "direction-not-found",
        "direction-out-of-reach",
        "direction-malformed",
        "direction-forbidden-origin",
        "reading-model-disabled",
        "reading-malformed-press",
        "reading-too-large",
        "reading-forbidden-origin",
        "reading-provider-changed",
        "reading-revision-changed",
        "reading-adoption-refused",
        "reading-unknown-session",
        "reading-cancel-not-running",
        "correction-nothing-to-steer",
        "correction-copied-accepted",
        "correction-copied-malformed",
        "focus-focused",
        "focus-declined",
        "focus-forbidden-capability",
        "focus-throttled",
        "focus-disabled",
        "focus-too-large",
        "tripwire-disabled",
        "lane-reported",
        "lane-names-session",
        "lane-malformed",
        "answer-unknown-ask",
        "answer-disabled",
        "annotate-stale-lines",
        "annotate-current-revision",
        "reading-off",
        "reading-forbidden-same-site",
        "reading-cancel-malformed",
        "reading-cancel-model-disabled",
        "focus-missing-capability",
        "cleared-after-dismiss",
        "context-project-key",
        "reading-destination-changed",
        "reading-page-outdated",
        "reading-stale-model",
        "tripwire-invalid",
        "tripwire-removed",
        "tripwire-stale-revision",
        "tripwire-unwritable",
        "direction-opened",
        "annotate-adopted",
        "annotate-direction-added",
        "annotate-direction-refused",
        "annotate-cleared",
        "context-focused-prompts",
        "dismiss-persisted",
        "dismiss-disabled",
        "notify-accepted",
        "notify-too-large",
    }
)


class ClientContractFixtureTest(unittest.TestCase):
    generated: ClassVar[dict[str, bytes]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = regen.generate()

    def committed(self) -> dict[str, bytes]:
        return {path.name: path.read_bytes() for path in sorted(FIXTURES.glob("*.json"))}

    def test_every_committed_file_is_what_the_live_server_produces(self) -> None:
        committed = self.committed()
        self.assertEqual(sorted(self.generated), sorted(committed), "fixture set drifted")
        for name, body in self.generated.items():
            with self.subTest(fixture=name):
                self.assertEqual(
                    body,
                    committed[name],
                    f"{name} no longer matches the backend: run scripts/regen_client_fixtures.py",
                )

    def test_manifest_names_every_scenario_with_its_digest(self) -> None:
        manifest = json.loads((FIXTURES / "index.json").read_bytes())
        self.assertEqual(1, manifest["format"])
        names = [row["name"] for row in manifest["scenarios"]]
        self.assertEqual(sorted(names), names, "manifest rows are not in stable order")
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(set(names), REQUIRED)
        on_disk = {p.stem for p in FIXTURES.glob("*.json") if p.name != "index.json"}
        self.assertEqual(on_disk, set(names))
        for row in manifest["scenarios"]:
            with self.subTest(scenario=row["name"]):
                body = (FIXTURES / f"{row['name']}.json").read_bytes()
                self.assertEqual(hashlib.sha256(body).hexdigest(), row["sha256"])
                self.assertEqual({"name", "method", "route", "status", "sha256"}, set(row))
                fixture = json.loads(body)
                self.assertEqual(1, fixture["format"])
                self.assertEqual(row["name"], fixture["name"])
                self.assertEqual(row["status"], fixture["response"]["status"])
                self.assertEqual(row["method"], fixture["request"]["method"])
                self.assertEqual(
                    row["route"], fixture["request"]["path"].split("?", 1)[0], "route mismatch"
                )

    def test_the_manifest_digest_covers_the_bytes_a_client_reads(self) -> None:
        manifest = json.loads((FIXTURES / "index.json").read_bytes())
        self.assertEqual(
            regen.UNREACHABLE,
            manifest["unreachable"],
            "unreachable states must be listed with a reason, never hand-written",
        )
        self.assertTrue(all(reason.strip() for reason in manifest["unreachable"].values()))
        self.assertFalse(
            set(manifest["unreachable"]) & {row["name"] for row in manifest["scenarios"]}
        )

    def test_fixtures_carry_no_machine_paths_secrets_or_localhost(self) -> None:
        pattern = re.compile(
            r"/Users/|/home/|/private/|/var/folders|/tmp/|[A-Za-z]:\\\\|localhost"
            r"|AKIA[0-9A-Z]{8}|ASIA[0-9A-Z]{8}|sk-[A-Za-z0-9]{8}|ghp_|xoxb-|phc_"
        )
        for name, body in self.committed().items():
            with self.subTest(fixture=name):
                self.assertIsNone(pattern.search(body.decode("utf-8")), name)

    def test_fixtures_are_canonical_json_with_a_trailing_newline(self) -> None:
        for name, body in self.committed().items():
            with self.subTest(fixture=name):
                text = body.decode("utf-8")
                self.assertTrue(text.endswith("}\n"))
                parsed: Any = json.loads(text)
                self.assertEqual(
                    json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False) + "\n", text
                )

    def test_generation_never_reached_a_model_or_a_native_action(self) -> None:
        self.assertEqual(
            {"model_launches": 0, "native_notifications": 0, "subprocess_spawns": 0},
            regen.GUARD_COUNTS,
        )

    def test_recorded_stream_bytes_do_not_depend_on_how_fast_the_reader_is(self) -> None:
        # A reader that stalls past the 0.2 s heartbeat is sent more keepalive frames than one
        # that does not; the recorded text is cut at the frames the scenario is about.
        real = socket.create_connection

        class Stalled:
            def __init__(self, sock: Any) -> None:
                self.sock = sock
                self.reads = 0

            def recv(self, size: int) -> bytes:
                self.reads += 1
                if self.reads == 2:
                    time.sleep(0.7)
                data: bytes = self.sock.recv(size)
                return data

            def __getattr__(self, name: str) -> Any:
                return getattr(self.sock, name)

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_exc: object) -> None:
                self.sock.close()

        # Only the heartbeat scenario: the others publish while the reader reads, and a stalled
        # reader there is a race of its own that says nothing about the recorded bytes.
        recorder = regen.Recorder()
        scratch = regen.Scratch()
        try:
            with (
                mock.patch.object(
                    socket, "create_connection", lambda *a, **k: Stalled(real(*a, **k))
                ),
                regen.guarded(),
            ):
                regen.stream_heartbeat(recorder, scratch)
        finally:
            scratch.close()
        committed = self.committed()
        self.assertEqual(["stream-heartbeat"], sorted(recorder.scenarios))
        self.assertEqual(
            committed["stream-heartbeat.json"],
            regen.canonical(recorder.scenarios["stream-heartbeat"]),
        )

    def test_check_flag_is_cheap_and_agrees(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "regen_client_fixtures.py"), "--check"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
