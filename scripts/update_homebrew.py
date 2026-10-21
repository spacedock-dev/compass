#!/usr/bin/env python3
"""Render the Homebrew formula for a released Compass version.

Usage:
    python3 scripts/update_homebrew.py <Formula/compass.rb> <checksums.txt> <tag>

`<tag>` is the release tag, with or without its leading `v`. `checksums.txt` is the one
scripts/publish-cli.sh attaches to the release: `sha256  filename` lines for exactly the four
installer archives. The formula names each archive by URL and checksum, so Homebrew is the only
thing that downloads, verifies and installs it.

Two refusals keep a wrong formula from landing:

- A checksums file that is not exactly the four archives of this version, each with a lowercase
  SHA-256, fails instead of rendering a formula that names a missing or unverified download.
- A formula that already carries a newer version is left alone. A resumed older release must not
  roll the tap back.

Writes the formula only when its text changes, and prints which of the three outcomes it reached.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LISTED_VERSION_RE = re.compile(r"/compass_([^_/\n]+)_(?:darwin|linux)_")
REPOSITORY = "https://github.com/spacedock-dev/compass"

PLATFORMS = (
    ("on_macos", "darwin", (("on_arm", "arm64"), ("on_intel", "amd64"))),
    ("on_linux", "linux", (("on_arm", "arm64"), ("on_intel", "amd64"))),
)


def parse_semver(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise SystemExit(f"error: {value!r} is not strict semver (X.Y.Z)")
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


def archive_name(version: str, os_name: str, arch: str) -> str:
    return f"compass_{version}_{os_name}_{arch}.tar.gz"


def read_checksums(path: Path, version: str) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"error: cannot read {path}: {exc}") from exc
    sums: dict[str, str] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 2:
            raise SystemExit(f"error: {path} has a line that is not 'sha256  filename': {line!r}")
        digest, name = fields
        if name in sums:
            raise SystemExit(f"error: {path} lists {name} twice")
        sums[name] = digest
    wanted = {
        archive_name(version, os_name, arch)
        for _, os_name, arches in PLATFORMS
        for _, arch in arches
    }
    if set(sums) != wanted:
        raise SystemExit(f"error: {path} must list exactly {sorted(wanted)}, found {sorted(sums)}")
    for name, digest in sums.items():
        if not SHA256_RE.fullmatch(digest):
            raise SystemExit(f"error: {name} has no lowercase SHA-256 in {path}: {digest!r}")
    return sums


def render(tag: str, version: str, sums: dict[str, str]) -> str:
    lines = [
        "class Compass < Formula",
        '  desc "Agnostic agent cartography and visualization tool"',
        f'  homepage "{REPOSITORY}"',
        '  license all_of: ["Apache-2.0", "OFL-1.1"]',
        "",
    ]
    for block, os_name, arches in PLATFORMS:
        lines.append(f"  {block} do")
        for arch_block, arch in arches:
            name = archive_name(version, os_name, arch)
            lines += [
                f"    {arch_block} do",
                f'      url "{REPOSITORY}/releases/download/{tag}/{name}"',
                f'      sha256 "{sums[name]}"',
                "    end",
            ]
        lines += ["  end", ""]
    lines += [
        "  def install",
        '    libexec.install Dir["*"]',
        '    bin.install_symlink libexec/"compass" => "compass"',
        '    bin.install_symlink libexec/"compass" => "spacedock-compass"',
        "  end",
        "",
        "  test do",
        '    assert_match "Compass", shell_output("#{bin}/compass --help")',
        "  end",
        "end",
    ]
    return "\n".join(lines) + "\n"


def listed_version(formula: Path) -> str | None:
    try:
        match = LISTED_VERSION_RE.search(formula.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"error: cannot read {formula}: {exc}") from exc
    return match.group(1) if match else None


def write_formula(formula_path: Path, checksums_path: Path, tag: str) -> str:
    version = tag.removeprefix("v")
    target = parse_semver(version)
    sums = read_checksums(checksums_path, version)
    listed = listed_version(formula_path)
    if listed is not None and SEMVER_RE.fullmatch(listed) and parse_semver(listed) > target:
        return f"tap lists compass {listed}, newer than {version}; leaving it"
    text = render(tag, version, sums)
    if formula_path.exists() and formula_path.read_text(encoding="utf-8") == text:
        return f"tap already lists compass {version}"
    formula_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=formula_path.parent, prefix=f"{formula_path.name}.", delete=False
    ) as handle:
        handle.write(text)
        staged = Path(handle.name)
    staged.replace(formula_path)
    return f"tap now lists compass {version}"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    print(write_formula(Path(argv[0]), Path(argv[1]), argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
