"""The advisory check audits pins as data and fails closed on incomplete responses."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import audit_python_dependencies as audit


class AdvisoryCheckTest(unittest.TestCase):
    def test_reads_every_generated_requirement_and_deduplicates_exact_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "requirements-a.txt").write_text(
                "# header\nPyYAML==6.0.3 \\\n --hash=sha256:abc\n"
            )
            (root / "requirements-b.txt").write_text(
                "pyyaml==6.0.3\nother==1.2 ; python_version < '3.13'\n"
            )
            self.assertEqual([("other", "1.2"), ("pyyaml", "6.0.3")], audit.pins(root))

    def test_reports_advisory_ids_and_returns_failure_without_installing(self) -> None:
        packages = [("pyyaml", "6.0.3")]
        response = io.BytesIO(
            json.dumps({"results": [{"vulns": [{"id": "PYSEC-EXAMPLE"}]}]}).encode()
        )
        with mock.patch("urllib.request.urlopen", return_value=response) as opener:
            self.assertEqual(["pyyaml==6.0.3: PYSEC-EXAMPLE"], audit.advisories(packages))
        request = opener.call_args.args[0]
        self.assertEqual(audit.ENDPOINT, request.full_url)
        self.assertEqual(
            {"queries": [{"package": {"name": "pyyaml", "ecosystem": "PyPI"}, "version": "6.0.3"}]},
            json.loads(request.data),
        )
        self.assertGreater(opener.call_args.kwargs["timeout"], 0)

    def test_clean_result_is_empty_and_incomplete_results_fail_closed(self) -> None:
        payload: dict[str, Any]
        for payload in (
            {"results": [{}]},
            {"results": []},
            {"results": [{"error": "query failed"}]},
            {"results": [{"next_page_token": "more"}]},
            {"results": [{"vulns": "invalid"}]},
        ):
            with (
                self.subTest(payload=payload),
                mock.patch(
                    "urllib.request.urlopen",
                    return_value=io.BytesIO(json.dumps(payload).encode()),
                ),
            ):
                if payload == {"results": [{}]}:
                    self.assertEqual([], audit.advisories([("package", "1")]))
                else:
                    with self.assertRaises((ValueError, TypeError)):
                        audit.advisories([("package", "1")])

    def test_main_fails_on_findings_and_service_errors(self) -> None:
        for value, status in (([], 0), (["pkg==1: ID"], 1), (OSError("offline"), 2)):
            with (
                self.subTest(value=value),
                mock.patch.object(audit, "pins", return_value=[("pkg", "1")]),
                mock.patch.object(
                    audit,
                    "advisories",
                    side_effect=value if isinstance(value, Exception) else None,
                    return_value=value,
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO),
                mock.patch("sys.stderr", new_callable=io.StringIO),
            ):
                self.assertEqual(status, audit.main())
