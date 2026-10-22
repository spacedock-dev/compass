#!/bin/sh
# Write the Homebrew formula for a released version into spacedock-dev/homebrew-tap and push it.
#
# The release workflow runs this from the one job that holds the tap deploy key, after
# `attach-cli` has attached the archives and `checksums.txt` to the release. The key reaches only
# the tap, so it can neither move a release tag here nor push to this repository's main. The
# checksums are read from the public release over plain HTTPS, so no repository token is needed,
# and nothing here downloads or runs an archive; the rendering is scripts/update_homebrew.py.
#
# The tap is pushed to by other products' releases too, so a rejected push is retried from a
# fresh clone, which is what picks up their commit, rather than forced.
#
# Usage: publish-homebrew.sh <tag>      (X.Y.Z or vX.Y.Z, as the release is tagged)
#
# Environment:
#   HOMEBREW_TAP_DEPLOY_KEY  private half of a write deploy key on the tap repository.
#                            Required for an SSH remote and ignored for any other.
#   HOMEBREW_TAP_REMOTE      the repository to push to (default: the real tap over SSH).
#                            The tests point it at a local bare repository.
#   COMPASS_RELEASE_URL      where releases are downloaded from (default: this repository's
#                            GitHub releases). The tests point it at a local directory.
#   HOMEBREW_RETRY_DELAY     seconds to wait before a retry (default 5)
set -eu
tag="${1:?usage: publish-homebrew.sh <tag>}"
version="${tag#v}"
remote="${HOMEBREW_TAP_REMOTE:-git@github.com:spacedock-dev/homebrew-tap.git}"
releases="${COMPASS_RELEASE_URL:-https://github.com/spacedock-dev/compass/releases/download}"
delay="${HOMEBREW_RETRY_DELAY:-5}"
here="$(cd "$(dirname "$0")" && pwd)"

umask 077
scratch="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/homebrew.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT

case "$remote" in
git@* | ssh://*)
	[ -n "${HOMEBREW_TAP_DEPLOY_KEY:-}" ] || {
		echo "publish-homebrew.sh: HOMEBREW_TAP_DEPLOY_KEY is empty" >&2
		exit 1
	}
	printf '%s\n' "$HOMEBREW_TAP_DEPLOY_KEY" >"$scratch/key"
	# GitHub's host keys come from its API over TLS rather than from the first connection, so a
	# strict check can still refuse an impostor.
	curl --fail --silent --show-error https://api.github.com/meta |
		jq -r '.ssh_keys[] | "github.com " + .' >"$scratch/known_hosts"
	[ -s "$scratch/known_hosts" ] || {
		echo "publish-homebrew.sh: no GitHub host keys fetched" >&2
		exit 1
	}
	GIT_SSH_COMMAND="ssh -i $scratch/key -o IdentitiesOnly=yes -o IdentityAgent=none -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$scratch/known_hosts"
	export GIT_SSH_COMMAND
	;;
esac

curl --fail --silent --show-error --location --retry 3 \
	--output "$scratch/checksums.txt" "$releases/$tag/checksums.txt" || {
	echo "publish-homebrew.sh: cannot fetch checksums.txt for $tag" >&2
	exit 1
}

attempt=1
while :; do
	clone="$scratch/clone"
	rm -rf "$clone"
	git clone --quiet --depth 1 "$remote" "$clone"
	python3 -I "$here/update_homebrew.py" "$clone/Formula/compass.rb" "$scratch/checksums.txt" "$tag"
	# A formula the tap does not have yet is untracked, so `git diff` alone would call it unchanged.
	if [ -z "$(git -C "$clone" status --porcelain -- Formula/compass.rb)" ]; then
		exit 0
	fi
	git -C "$clone" add -- Formula/compass.rb
	git -C "$clone" diff --cached --check
	git -C "$clone" -c user.name=github-actions -c user.email=actions@github.com \
		commit --quiet --signoff -m "compass $version"
	if git -C "$clone" push --quiet origin HEAD:main; then
		exit 0
	fi
	[ "$attempt" -lt 3 ] || {
		echo "publish-homebrew.sh: the tap rejected the push $attempt times" >&2
		exit 1
	}
	attempt=$((attempt + 1))
	sleep "$delay"
done
