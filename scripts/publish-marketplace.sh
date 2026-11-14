#!/bin/sh
# Stamp a released version onto the compass entry of spacedock-dev/marketplace and push it.
#
# The release workflow runs this from the one job that holds the marketplace deploy key, after
# `stable` has advanced. The key reaches only the marketplace repository, so it can neither
# move a release tag here nor push to this repository's main. Nothing here builds or runs
# anything from a release archive; the JSON edit is scripts/update_marketplace.py.
#
# The marketplace is pushed to by other products' releases too, so a rejected push is retried
# from a fresh clone, which is what picks up their commit, rather than forced.
#
# Usage: publish-marketplace.sh <X.Y.Z>
#
# Environment:
#   MARKETPLACE_DEPLOY_KEY   private half of a write deploy key on the marketplace repository.
#                            Required for an SSH remote and ignored for any other.
#   MARKETPLACE_REMOTE       the repository to push to (default: the real marketplace over SSH).
#                            The tests point it at a local bare repository.
#   MARKETPLACE_RETRY_DELAY  seconds to wait before a retry (default 5)
set -eu
version="${1:?usage: publish-marketplace.sh <X.Y.Z>}"
remote="${MARKETPLACE_REMOTE:-git@github.com:spacedock-dev/marketplace.git}"
delay="${MARKETPLACE_RETRY_DELAY:-5}"
here="$(cd "$(dirname "$0")" && pwd)"

umask 077
scratch="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/marketplace.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT

case "$remote" in
git@* | ssh://*)
	[ -n "${MARKETPLACE_DEPLOY_KEY:-}" ] || {
		echo "publish-marketplace.sh: MARKETPLACE_DEPLOY_KEY is empty" >&2
		exit 1
	}
	COMPASS_SSH_KEY_FILE="$scratch/key"
	COMPASS_SSH_KNOWN_HOSTS="$scratch/known_hosts"
	export COMPASS_SSH_KEY_FILE COMPASS_SSH_KNOWN_HOSTS
	printf '%s\n' "$MARKETPLACE_DEPLOY_KEY" >"$COMPASS_SSH_KEY_FILE"
	# GitHub's host keys come from its API over TLS rather than from the first connection, so a
	# strict check can still refuse an impostor.
	curl --proto '=https' --tlsv1.2 --fail --silent --show-error https://api.github.com/meta |
		jq -r '.ssh_keys[] | "github.com " + .' >"$COMPASS_SSH_KNOWN_HOSTS"
	[ -s "$COMPASS_SSH_KNOWN_HOSTS" ] || {
		echo "publish-marketplace.sh: no GitHub host keys fetched" >&2
		exit 1
	}
	# git runs this through the shell. The paths travel in the environment and are expanded by
	# that shell inside double quotes, so no character in the scratch path can split an argument
	# or end the command, as it could when the path was spliced into the string here.
	# shellcheck disable=SC2016,SC2089 # quoted and expanded by the shell git starts, not this one
	GIT_SSH_COMMAND='ssh -i "$COMPASS_SSH_KEY_FILE" -o IdentitiesOnly=yes -o IdentityAgent=none -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$COMPASS_SSH_KNOWN_HOSTS"'
	# shellcheck disable=SC2090 # the same: git hands the string to sh -c
	export GIT_SSH_COMMAND
	;;
esac

attempt=1
while :; do
	clone="$scratch/clone"
	rm -rf "$clone"
	git clone --quiet --depth 1 "$remote" "$clone"
	python3 -I "$here/update_marketplace.py" "$clone/.claude-plugin/marketplace.json" "$version"
	if git -C "$clone" diff --quiet -- .claude-plugin/marketplace.json; then
		exit 0
	fi
	git -C "$clone" diff --check
	git -C "$clone" add -- .claude-plugin/marketplace.json
	git -C "$clone" -c user.name=github-actions -c user.email=actions@github.com \
		commit --quiet --signoff -m "compass $version"
	if git -C "$clone" push --quiet origin HEAD:main; then
		exit 0
	fi
	[ "$attempt" -lt 3 ] || {
		echo "publish-marketplace.sh: the marketplace rejected the push $attempt times" >&2
		exit 1
	}
	attempt=$((attempt + 1))
	sleep "$delay"
done
