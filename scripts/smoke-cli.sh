#!/bin/sh
# Prove a packed archive runs on this machine the way a user would run it: unpack it, start the
# dashboard as a daemon under an empty-ish environment, fetch the page, ask for status, stop it.
# What it checks is that the embedded interpreter and the bundled page work; the dashboard's own
# behaviour has its own suite.
#
# Usage: smoke-cli.sh <archive.tar.gz>
set -eu
archive="${1:?usage: smoke-cli.sh <archive.tar.gz>}"
work="$(mktemp -d)"
home="$work/home"
mkdir -p "$home" "$work/unpacked"
port=$((20000 + $$ % 20000))
# Only the system directories: the program must not need anything the user installed, and in
# particular not a Python of ours. HOME is private so nothing lands in the real ~/.compass.
run() { env -i HOME="$home" PATH=/usr/bin:/bin "$work/unpacked/compass/compass" "$@"; }
cleanup() { run --stop --port "$port" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

tar -xzf "$archive" -C "$work/unpacked"
[ -x "$work/unpacked/compass/compass" ] || { echo "smoke-cli.sh: the archive has no compass/compass program" >&2; exit 1; }

run --help >/dev/null || { echo "smoke-cli.sh: --help failed" >&2; exit 1; }
want="$(basename "$archive")"
want="${want#compass_}"
want="${want%%_*}"
got="$(run --version)" || { echo "smoke-cli.sh: --version failed" >&2; exit 1; }
[ "$got" = "$want" ] || { echo "smoke-cli.sh: --version printed '$got', but the archive is named for $want" >&2; exit 1; }
run --port "$port" --daemon >"$work/daemon.out" 2>&1 \
	|| { cat "$work/daemon.out" >&2; echo "smoke-cli.sh: the daemon did not start" >&2; exit 1; }

tries=0
until page="$(curl -fsS "http://127.0.0.1:$port/" 2>/dev/null)"; do
	tries=$((tries + 1))
	[ "$tries" -lt 40 ] || { cat "$home"/.compass/*.log >&2 2>/dev/null || true; echo "smoke-cli.sh: the dashboard never answered on port $port" >&2; exit 1; }
	sleep 0.5
done
case "$page" in *"<title>Compass</title>"*) ;; *) echo "smoke-cli.sh: port $port answered, but not with the Compass page" >&2; exit 1 ;; esac
run --status --port "$port" | grep -q "running on port $port" || { echo "smoke-cli.sh: --status does not see the daemon" >&2; exit 1; }
run --stop --port "$port" >/dev/null
echo "smoke-cli.sh: ok ($archive)"
