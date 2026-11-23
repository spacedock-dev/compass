#!/bin/bash
# Usage: wait-merge.sh <owner/repo> <pr-number> <result-file>
# Waits for a green independent PR, checks that enqueue took, and watches for the
# merge. A failed enqueue and a DIRTY PR both went unseen in earlier waiters.
# WAIT_MERGE_DRY_RUN=1 reads one snapshot without enqueueing or writing a result.
set -eu
if [[ $# -ne 3 || ! $1 =~ ^[[:alnum:]_.-]+/[[:alnum:]_.-]+$ || ! $2 =~ ^[1-9][0-9]*$ ]]; then
  echo 'Usage: wait-merge.sh <owner/repo> <pr-number> <result-file>' >&2
  exit 2
fi
repo=$1
pr=$2
result=$3
polls=${WAIT_MERGE_POLLS:-90}
interval=${WAIT_MERGE_INTERVAL:-50}
settle=${WAIT_MERGE_SETTLE:-10}
if [[ ! $polls =~ ^[1-9][0-9]*$ || ! $interval =~ ^[0-9]+$ || ! $settle =~ ^[0-9]+$ ]]; then
  echo 'wait-merge: set a positive poll count and nonnegative intervals in seconds' >&2
  exit 2
fi

snapshot() {
  # GraphQL variables are supplied through gh, independent of the shell.
  # shellcheck disable=SC2016
  gh api graphql -f query='
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          state mergeStateStatus headRefOid mergeQueueEntry { state }
        }
      }
    }' -f owner="${repo%%/*}" -f repo="${repo#*/}" -F pr="$pr" \
    --jq '.data.repository.pullRequest | select(. != null) |
      "\(.state) \(.mergeStateStatus) \(.mergeQueueEntry.state // "none") \(.headRefOid)"' 2>/dev/null
}

finish() {
  printf '%s\n' "$1" > "$result"
  exit 0
}

if [[ ${WAIT_MERGE_DRY_RUN:-0} == 1 ]]; then
  row=$(snapshot) && [[ -n $row ]] || { echo "wait-merge: cannot read $repo#$pr" >&2; exit 1; }
  printf '%s\n' "$row"
  exit 0
fi

previous=
dirty_count=0
dirty_head=
last_attempt_head=
delay=$interval
for ((poll = 1; poll <= polls; poll++)); do
  if (( poll > 1 )); then sleep "$delay"; fi
  delay=$interval
  if ! row=$(snapshot) || [[ -z $row ]]; then
    if [[ $previous != unavailable ]]; then printf '%s\n' "$repo#$pr snapshot unavailable" >&2; fi
    previous=unavailable
    dirty_count=0
    continue
  fi
  read -r state merge_state queue_state head <<< "$row"
  if [[ $row != "$previous" ]]; then printf '%s %s\n' "$repo#$pr" "$row"; fi
  previous=$row
  case $state in
    MERGED|CLOSED) finish "$state" ;;
  esac

  # A force-push can briefly read DIRTY while GitHub recomputes. Count twice on one head.
  if [[ $merge_state == DIRTY && $queue_state == none ]]; then
    if [[ $head != "$dirty_head" ]]; then dirty_count=0; fi
    dirty_head=$head
    dirty_count=$((dirty_count + 1))
    if (( dirty_count >= 2 )); then finish DIRTY; fi
  else
    dirty_count=0
  fi
  if [[ $state != OPEN || $queue_state != none || $merge_state != CLEAN ]]; then
    last_attempt_head=
  fi
  if [[ $state != OPEN || $queue_state != none ]]; then continue; fi

  if ! checks=$(gh pr view "$pr" --repo "$repo" --json headRefOid,statusCheckRollup --jq '
    [.headRefOid, ([.statusCheckRollup[] | (.conclusion // .state // "") |
      select(test("^(FAILURE|ERROR|CANCELLED|TIMED_OUT|ACTION_REQUIRED|STARTUP_FAILURE|STALE)$"))] | length)]
    | join(" ")' 2>/dev/null); then
    continue
  fi
  read -r checked_head failures <<< "$checks"
  if [[ -z $head || $checked_head != "$head" || ! $failures =~ ^[0-9]+$ ]]; then continue; fi
  if (( failures > 0 )); then finish 'CI FAILURE'; fi
  if [[ $merge_state == CLEAN ]]; then
    # Recheck the first attempt promptly, then retry at the normal poll interval.
    gh pr merge "$pr" --repo "$repo" --squash --match-head-commit "$head" >/dev/null 2>&1 || true
    if [[ $last_attempt_head != "$head" ]]; then delay=$settle; fi
    last_attempt_head=$head
  fi
done
finish TIMEOUT
