"""Stand-ins for `curl`, `jq` and `ssh` on PATH, for the publish script tests.

The publish scripts talk to GitHub over HTTPS and SSH. These shims answer on the network's
behalf and write down every argument they were given, so a test can assert the flags a
download carries and the exact argv `ssh` received, with no network and no real key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

RELEASES_URL = "https://github.com/spacedock-dev/compass/releases/download"
HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeHostKeyForTestsOnly"

# One line per call, the arguments separated by a unit separator so a value with spaces
# survives. A download is served from $FAKE_RELEASES when its URL is under RELEASES_URL;
# anything else is refused, as an unreachable host would be.
CURL = f"""#!/bin/sh
line=""
for arg in "$@"; do line="$line$arg$(printf '\\037')"; done
printf '%s\\n' "$line" >>"$FAKE_LOG/curl"
out=""
url=""
while [ $# -gt 0 ]; do
	case "$1" in
	--output) out="$2"; shift 2 ;;
	--proto | --proto-redir | --retry) shift 2 ;;
	-*) shift ;;
	*) url="$1"; shift ;;
	esac
done
case "$url" in
https://api.github.com/meta) printf '{{"ssh_keys":["{HOST_KEY}"]}}\\n' ;;
{RELEASES_URL}/*)
	file="$FAKE_RELEASES/${{url#{RELEASES_URL}/}}"
	[ -f "$file" ] || exit 22
	cp "$file" "$out"
	;;
*) exit 6 ;;
esac
"""

JQ = f"""#!/bin/sh
cat >/dev/null
printf '%s\\n' "github.com {HOST_KEY}"
"""

# git runs GIT_SSH_COMMAND through the shell and appends the host and the remote command.
# This records the argv ssh would have been started with, notes whether the identity and
# known_hosts files it was pointed at exist, and fails the connection.
SSH = """#!/bin/sh
for arg in "$@"; do printf '%s\\n' "$arg"; done >"$FAKE_LOG/ssh"
prev=""
for arg in "$@"; do
	case "$prev" in
	-i) [ -f "$arg" ] && echo "identity file present" >>"$FAKE_LOG/ssh-files" ;;
	esac
	case "$arg" in
	UserKnownHostsFile=*)
		[ -s "${arg#UserKnownHostsFile=}" ] && echo "known_hosts present" >>"$FAKE_LOG/ssh-files"
		;;
	esac
	prev="$arg"
done
exit 1
"""


def install(bin_dir: Path, log_dir: Path) -> None:
    """Write the three shims into `bin_dir`; they log into `log_dir`."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    for name, body in {"curl": CURL, "jq": JQ, "ssh": SSH}.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)


def curl_calls(log_dir: Path) -> list[list[str]]:
    """Every curl invocation, as its argument list."""
    path = log_dir / "curl"
    if not path.exists():
        return []
    return [line.split("\x1f")[:-1] for line in path.read_text(encoding="utf-8").splitlines()]


def ssh_argv(log_dir: Path) -> list[str]:
    path = log_dir / "ssh"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def ssh_files(log_dir: Path) -> list[str]:
    path = log_dir / "ssh-files"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []
