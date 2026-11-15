"""Bot proposals, including security updates, must not evade the fourteen-day floor."""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import check_dependency_age as age


class PinAgeTest(unittest.TestCase):
    def test_parses_python_npm_bootstrap_pnpm_and_action_pins(self) -> None:
        self.assertEqual(
            {("pip", "pyyaml", "6.0.3")},
            age.package_pins("requirements-release.txt", "PyYAML==6.0.3 \\\n --hash=sha256:abc"),
        )
        self.assertEqual(
            {("npm", "@scope/pkg", "1.2.3")},
            age.package_pins(
                "pnpm-lock.yaml", "packages:\n  '@scope/pkg@1.2.3':\n    resolution: {}"
            ),
        )
        self.assertEqual(
            {("npm", "pkg", "1.2.3")},
            age.package_pins(
                "tools/pnpm-bootstrap/package-lock.json",
                '{"packages": {"node_modules/pkg": {"version": "1.2.3"}}}',
            ),
        )
        self.assertEqual(
            {("actions", "owner/repo", "a" * 40)},
            age.package_pins(
                ".github/actions/local/action.yml",
                "runs:\n  steps:\n    - uses: owner/repo/subdir@" + "a" * 40,
            ),
        )

    def test_age_boundary_and_missing_dates_fail_closed(self) -> None:
        now = dt.datetime(2026, 11, 15, tzinfo=dt.UTC)
        for days, expected in ((13, False), (14, True), (15, True)):
            stamp = (now - dt.timedelta(days=days)).isoformat()
            with self.subTest(days=days):
                self.assertEqual(expected, age.old_enough([stamp], now))
        self.assertFalse(age.old_enough([], now))

    def test_pypi_uses_newest_uploaded_file_and_npm_uses_version_publish_time(self) -> None:
        with mock.patch.object(
            age,
            "get_json",
            return_value={
                "urls": [
                    {"upload_time_iso_8601": "2026-10-01T00:00:00Z"},
                    {"upload_time_iso_8601": "2026-11-14T00:00:00Z"},
                ]
            },
        ):
            self.assertEqual(
                ["2026-10-01T00:00:00Z", "2026-11-14T00:00:00Z"], age.published(("pip", "pkg", "1"))
            )
        with mock.patch.object(
            age, "get_json", return_value={"time": {"1": "2026-10-01T00:00:00Z"}}
        ):
            self.assertEqual(["2026-10-01T00:00:00Z"], age.published(("npm", "pkg", "1")))

    def test_a_hash_only_refresh_still_checks_the_existing_versions_age(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "requirements-one.txt").write_text("package==1 --hash=sha256:new\n")
            (root / "pnpm-lock.yaml").write_text("")
            (root / "tools/pnpm-bootstrap").mkdir(parents=True)
            (root / "tools/pnpm-bootstrap/package-lock.json").write_text('{"packages": {}}')

            def previous(command: Any, **_kwargs: Any) -> Any:
                text = (
                    "package==1 --hash=sha256:old\n"
                    if command[-1].endswith("requirements-one.txt")
                    else ""
                )
                return subprocess.CompletedProcess(command, 0, text, "")

            with (
                mock.patch.object(age, "ROOT", root),
                mock.patch("subprocess.run", side_effect=previous),
            ):
                self.assertEqual({("pip", "package", "1")}, age.proposed_pins("a" * 40))

    def test_action_commit_timestamp_and_invalid_registry_response(self) -> None:
        with mock.patch.object(
            age,
            "get_json",
            return_value={"commit": {"committer": {"date": "2026-10-01T00:00:00Z"}}},
        ):
            self.assertEqual(
                ["2026-10-01T00:00:00Z"], age.published(("actions", "owner/repo", "a" * 40))
            )
        with (
            mock.patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps([]).encode())),
            self.assertRaises(TypeError),
        ):
            age.get_json("https://registry.npmjs.org/example")

    def test_bot_gate_fails_closed_on_young_pins_or_missing_metadata(self) -> None:
        for stamps, expected in (
            (["2099-01-01T00:00:00Z"], 1),
            ([], 1),
            (OSError("offline"), 2),
            (["2000-01-01T00:00:00Z"], 0),
        ):
            with (
                self.subTest(stamps=stamps),
                mock.patch.dict(os.environ, {"BASE_SHA": "a" * 40}),
                mock.patch.object(age, "proposed_pins", return_value={("npm", "pkg", "1")}),
                mock.patch.object(
                    age,
                    "published",
                    side_effect=stamps if isinstance(stamps, Exception) else None,
                    return_value=stamps,
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO),
                mock.patch("sys.stderr", new_callable=io.StringIO),
            ):
                self.assertEqual(expected, age.main())
