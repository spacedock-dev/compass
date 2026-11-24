#!/bin/sh

fetch_github_host_keys() (
	set +x # The caller can source this helper from a traced shell.
	# Keep the header out of argv and the token out of curl's environment. Reject characters
	# outside the bearer-token alphabet because curl reads one header per line from stdin.
	unset github_meta_token
	github_meta_token="${GITHUB_TOKEN:-}"
	unset GITHUB_TOKEN
	case "$github_meta_token" in
	*[!abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._~+/=-]*) return 1 ;;
	esac

	body="$1/github-meta.json"
	retry_delay=1
	while :; do
		result=0
		# A curlrc could add redirects or traces. --disable only works as the first option.
		status=$(
			if [ -n "$github_meta_token" ]; then
				printf 'Authorization: Bearer %s\n' "$github_meta_token"
			fi | curl --disable --proto '=https' --tlsv1.2 --fail --silent --max-time 8 \
				--header @- --output "$body" --write-out '%{http_code}' \
				https://api.github.com/meta 2>/dev/null
		) || result=$?
		case "$result:$status" in
		0:200)
			rows=$(jq -ers '
				"\\A[A-Za-z0-9@._+-]+ [A-Za-z0-9+/]+={0,2}( [^\\p{Cc}]+)?\\z" as $key |
				select(length == 1) | .[0].ssh_keys | arrays |
				select(length > 0 and all(.[]; type == "string" and test($key))) |
				.[] | split(" ") | .[0:2] | "github.com " + join(" ")' \
				<"$body" 2>/dev/null) || return 1
			# Fingerprinting a whole file can succeed even if OpenSSH skips an invalid row.
			key_file="$1/github-host-key"
			while IFS= read -r row; do
				printf '%s\n' "$row" >|"$key_file" || return 1
				ssh-keygen -l -f "$key_file" >/dev/null 2>&1 || return 1
			done <<EOF
$rows
EOF
			printf '%s\n' "$rows"
			return
			;;
		# A fresh request can clear DNS, connect, timeout, TLS handshake and stream I/O
		# failures. Treat certificate verification and local I/O errors as terminal.
		22:403 | 22:429 | 22:5[0-9][0-9] | \
		5:* | 6:* | 7:* | 16:* | 18:* | 28:* | 35:* | 52:* | 55:* | 56:* | 92:* | 95:* | 96:* | 97:*) ;;
		*) return 1 ;;
		esac
		# Four 8-second requests and waits of 1, 2 and 4 seconds take at most 39 seconds.
		[ "$retry_delay" -le 4 ] || return 1
		sleep "$retry_delay"
		retry_delay=$((retry_delay * 2))
	done
)
