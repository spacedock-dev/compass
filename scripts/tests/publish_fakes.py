"""Stand-ins for `curl` and `ssh` on PATH, for the publish script tests.

The publish scripts talk to GitHub over HTTPS and SSH. These shims answer on the network's
behalf and write down every argument they were given, so a test can assert the flags a
download carries and the exact argv `ssh` received, with no network and no real key.
"""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

RELEASES_URL = "https://github.com/spacedock-dev/compass/releases/download"
META_URL = "https://api.github.com/meta"
TEST_BEARER = "ghs_compass_test_token"
TEST_DEPLOY_KEY = "compass_fixture_deploy_key"
# Wire-format Ed25519 public key from the host-key parser review fixture.
HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f"

# One line per call, the arguments separated by a unit separator so a value with spaces
# survives. A download is served from $FAKE_RELEASES when its URL is under RELEASES_URL;
# anything else is refused, as an unreachable host would be.
CURL = f"""#!/bin/sh
line=""
for arg in "$@"; do line="$line$arg$(printf '\\037')"; done
printf '%s\\n' "$line" >>"$FAKE_LOG/curl"
out=""
url=""
header=""
write_out=""
fail=""
while [ $# -gt 0 ]; do
	case "$1" in
	--output) out="$2"; shift 2 ;;
	--header)
		if [ "$2" = @- ]; then header="$(cat)"; else header="$2"; fi
		shift 2 ;;
	--write-out) write_out="$2"; shift 2 ;;
	--fail) fail=yes; shift ;;
	--proto | --proto-redir | --retry | --max-time) shift 2 ;;
	-*) shift ;;
	*) url="$1"; shift ;;
	esac
done
case "$header" in
"Authorization: Bearer {TEST_BEARER}") auth=bearer ;;
"") auth=none ;;
*) auth=unexpected ;;
esac
[ "${{GITHUB_TOKEN+x}}" != x ] || auth="$auth-with-exported-token"
printf '%s\\n' "$auth" >>"$FAKE_LOG/auth"
case "$url" in
{META_URL})
	[ "$write_out" = '%{{http_code}}' ] || exit 2
	printf '\\n' >>"$FAKE_LOG/meta"
	call=$(wc -l <"$FAKE_LOG/meta")
	set -- ${{FAKE_META_RESPONSES:-200}}
	while [ "$call" -gt 1 ] && [ "$#" -gt 1 ]; do shift; call=$((call - 1)); done
	if [ "$1" = timeout ]; then
		printf '000'
		exit 28
	fi
	printf '%s' "$1"
	case "$1:$fail" in
	[45]??:yes) exit 22 ;;
	esac
	# The redirect also offers a keys-shaped body. Only a 200 should be usable.
	cp "$FAKE_LOG/github-meta.json" "$out"
	;;
{RELEASES_URL}/*)
	file="$FAKE_RELEASES/${{url#{RELEASES_URL}/}}"
	[ -f "$file" ] || exit 22
	cp "$file" "$out"
	;;
*) exit 6 ;;
esac
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

SLEEP = """#!/bin/sh
printf '%s\\n' "$1" >>"$FAKE_LOG/sleep"
"""


def install(bin_dir: Path, log_dir: Path) -> None:
    """Install the network and sleep shims and create their log directory."""
    if shutil.which("jq") is None:
        message = "jq is required on PATH for the publisher tests to exercise the host-key filter"
        raise AssertionError(message)
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "github-meta.json").write_text(
        json.dumps({"ssh_keys": [HOST_KEY], "ssh_key_fingerprints": {}}) + "\n", encoding="utf-8"
    )
    for name, body in {"curl": CURL, "ssh": SSH, "sleep": SLEEP}.items():
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


def ssh_publish_env(
    remote: Path, url: str, trace: Path, *, token: str = TEST_BEARER
) -> dict[str, str]:
    """Exercise the publisher's SSH setup, then let Git clone and push to a local bare remote."""
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{remote.as_uri()}.insteadOf",
        "GIT_CONFIG_VALUE_0": url,
        "GIT_TRACE": str(trace),
        "GITHUB_TOKEN": token,
    }
