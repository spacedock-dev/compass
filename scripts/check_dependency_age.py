#!/usr/bin/env python3
"""Check newly proposed Dependabot pins against the repository's fourteen-day age floor.

Cooldown excludes security updates. This check uses registry publication timestamps and action
commit timestamps for both update kinds, with no dependency installation and no credential.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
Pin = tuple[str, str, str]


def package_pins(path: str, text: str) -> set[Pin]:
    if path.startswith("requirements-"):
        return {
            ("pip", re.sub(r"[-_.]+", "-", name).lower(), version)
            for name, version in re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", text, re.MULTILINE)
        }
    if path == "pnpm-lock.yaml":
        # Only package keys at two spaces, not snapshots' peer-resolution suffixes.
        return {
            ("npm", name, version)
            for name, version in re.findall(
                r"^  ['\"]?(@?[^\s'\"]+?)@([0-9][^:'\"()]*)(?:\([^\n]*\))?['\"]?:",
                text,
                re.MULTILINE,
            )
        }
    if path.endswith("package-lock.json"):
        lock = json.loads(text or "{}")
        return {
            ("npm", value.get("name") or name.rsplit("node_modules/", 1)[-1], value["version"])
            for name, value in lock.get("packages", {}).items()
            if name and value.get("version")
        }
    return {
        ("actions", name, sha)
        for name, sha in re.findall(
            r"\buses:\s*['\"]?([\w.-]+/[\w.-]+)(?:/[^@\s]+)?@([0-9a-f]{40})\b", text
        )
    }


def get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - fixed registry HTTPS URLs
        data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("registry response too large")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise TypeError("registry returned no object")
    return result


def published(pin: Pin) -> list[str]:
    ecosystem, name, version = pin
    if ecosystem == "pip":
        data = get_json(
            f"https://pypi.org/pypi/{quote(name, safe='')}/{quote(version, safe='')}/json"
        )
        return [file["upload_time_iso_8601"] for file in data["urls"]]
    if ecosystem == "npm":
        data = get_json("https://registry.npmjs.org/" + quote(name, safe=""))
        return [data["time"][version]]
    data = get_json(f"https://api.github.com/repos/{name}/commits/{version}")
    return [data["commit"]["committer"]["date"]]


def old_enough(stamps: list[str], now: dt.datetime) -> bool:
    return bool(stamps) and all(
        now - dt.datetime.fromisoformat(stamp) >= dt.timedelta(days=14) for stamp in stamps
    )


def proposed_pins(base: str) -> set[Pin]:
    paths = [
        *ROOT.glob("requirements-*.txt"),
        *ROOT.glob("requirements-*.in"),
        ROOT / "pnpm-lock.yaml",
        ROOT / "tools/pnpm-bootstrap/package-lock.json",
        *(ROOT / ".github/workflows").glob("*.y*ml"),
        *(ROOT / ".github/actions").rglob("*.y*ml"),
    ]
    changed = set()
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        previous = subprocess.run(  # noqa: S603 - validated SHA and tracked relative path
            ["/usr/bin/git", "show", f"{base}:{relative}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if (
            previous.returncode
            and "does not exist" not in previous.stderr
            and "exists on disk, but not in" not in previous.stderr
        ):
            raise ValueError("cannot read base dependency pins")
        current = path.read_text(encoding="utf-8")
        current_pins = package_pins(relative, current)
        if relative.startswith("requirements-") and current != previous.stdout:
            # A hash refresh can admit a newly uploaded wheel without changing the version.
            changed.update(current_pins)
        else:
            changed.update(current_pins - package_pins(relative, previous.stdout))
    return changed


def main() -> int:
    base = os.environ.get("BASE_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        print("pin age check requires the pull request base SHA", file=sys.stderr)
        return 2
    try:
        pins = proposed_pins(base)
        now = dt.datetime.now(dt.UTC)
        young = [pin for pin in sorted(pins) if not old_enough(published(pin), now)]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Pin age check unavailable: {type(error).__name__}", file=sys.stderr)
        return 2
    for ecosystem, name, version in young:
        print(f"Pin younger than fourteen days: {ecosystem} {name}@{version}")
    print(f"Checked {len(pins)} proposed pins; {len(young)} below the age floor")
    return int(bool(young))


if __name__ == "__main__":
    raise SystemExit(main())
