#!/bin/sh
# Build the standalone `compass` binary for THIS machine's OS and architecture and pack it
# as compass_<version>_<os>_<arch>.tar.gz: one top-level `compass/` directory holding the
# `compass` program and the interpreter and modules it carries. A user needs no Python.
#
# PyInstaller embeds the interpreter it runs under and cannot cross-compile, so each of the
# four release targets is built on a matching host (see .github/workflows/release.yml).
#
# Usage: package-cli.sh <version> [out-dir] [source-root]
#   PYTHON  the interpreter that carries PyInstaller (default python3); it is the one embedded
set -eu
version="${1:?usage: package-cli.sh <version> [out-dir] [source-root]}"
out="${2:-dist}"
src="${3:-.}"
python="${PYTHON:-python3}"

case "$(uname -s)" in
Darwin) os=darwin ;;
Linux) os=linux ;;
*) echo "package-cli.sh: unsupported OS $(uname -s); releases target darwin and linux" >&2; exit 1 ;;
esac
case "$(uname -m)" in
arm64 | aarch64) arch=arm64 ;;
x86_64 | amd64) arch=amd64 ;;
*) echo "package-cli.sh: unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac

# The floor in COMPATIBILITY.md is what the dashboard needs; the interpreter embedded here is
# what users get, so refuse one below it rather than ship a binary the runtime would reject.
"$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null \
	|| { echo "package-cli.sh: $python must be Python 3.11 or newer" >&2; exit 1; }
"$python" -m PyInstaller --version >/dev/null 2>&1 \
	|| { echo "package-cli.sh: PyInstaller is not installed for $python; install requirements-cli.txt" >&2; exit 1; }

skill="$(cd "$src" && pwd)/compass/skills/compass"
[ -f "$skill/server.py" ] || { echo "package-cli.sh: no $skill/server.py" >&2; exit 1; }

mkdir -p "$out"
out="$(cd "$out" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# --collect-submodules: the collectors are imported by name at run time, which static analysis
# does not see. --add-data: the page and its fonts are read from disk next to the package, and
# so is the version `compass --version` prints. The stamp comes from $version, not from the
# manifests: the release job bumps them after the binaries are built.
# Every output lands under $work, so the source tree is never written to.
printf '%s\n' "$version" >"$work/release-version.txt"
"$python" -m PyInstaller --noconfirm --clean --onedir --console --name compass \
	--distpath "$work/dist" --workpath "$work/build" --specpath "$work/spec" \
	--paths "$skill" \
	--collect-submodules compass_runtime \
	--add-data "$skill/compass_runtime/web:compass_runtime/web" \
	--add-data "$work/release-version.txt:compass_runtime" \
	"$skill/server.py" >"$work/pyinstaller.log" 2>&1 \
	|| { cat "$work/pyinstaller.log" >&2; echo "package-cli.sh: PyInstaller failed" >&2; exit 1; }

archive="compass_${version}_${os}_${arch}.tar.gz"
COPYFILE_DISABLE=1 tar -czf "$out/$archive" -C "$work/dist" compass
echo "$out/$archive"
