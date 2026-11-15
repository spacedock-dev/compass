#!/usr/bin/env python3
"""Query OSV for every exact Python requirement pin, without installing dependency code.

Only public package names and versions leave CI. All marker branches are included so the
check also covers dependencies installed only by another OS or Python version.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.osv.dev/v1/querybatch"
ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE = 4 * 1024 * 1024


def pins(root: Path) -> list[tuple[str, str]]:
    packages = set()
    for path in sorted(root.glob("requirements-*.txt")):
        text = path.read_text(encoding="utf-8")
        for name, version in re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", text, re.MULTILINE):
            packages.add((re.sub(r"[-_.]+", "-", name).lower(), version))
    if not packages:
        raise ValueError("no exact requirement pins found")
    return sorted(packages)


def advisories(packages: list[tuple[str, str]]) -> list[str]:
    payload = {
        "queries": [
            {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
            for name, version in packages
        ]
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # The workflow step also has a wall-clock timeout. No package, executable or advisory
    # text from the response runs on the host; only advisory identifiers are printed.
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint
        body = response.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise ValueError("OSV response exceeds allowance")
    result = json.loads(body)
    rows = result.get("results") if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) != len(packages):
        raise ValueError("incomplete OSV results")
    findings = []
    for (name, version), row in zip(packages, rows, strict=True):
        if (
            not isinstance(row, dict)
            or set(row) - {"vulns", "next_page_token"}
            or row.get("next_page_token")
        ):
            raise ValueError("incomplete OSV result page")
        vulns = row.get("vulns", [])
        if not isinstance(vulns, list):
            raise TypeError("invalid OSV advisory list")
        for vuln in vulns:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str):
                raise TypeError("invalid OSV advisory id")
            identifier = vuln["id"]
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", identifier):
                raise TypeError("invalid OSV advisory id")
            findings.append(f"{name}=={version}: {identifier}")
    return findings


def main() -> int:
    try:
        packages = pins(ROOT)
        findings = advisories(packages)
    except (OSError, ValueError, TypeError, urllib.error.URLError) as error:
        print(f"Python advisory check failed: {type(error).__name__}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding)
    print(f"Checked {len(packages)} exact Python pins; {len(findings)} advisories")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
