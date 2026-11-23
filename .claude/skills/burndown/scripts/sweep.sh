#!/bin/bash
# Usage: sweep.sh <worktree> [--dry-run]
# TERM leftover processes that name this run's worktree after a capped kill.
# A Storybook server escaped its builder's group and held the port for 74m.
set -eu
if [[ $# -lt 1 || $# -gt 2 || ( $# -eq 2 && $2 != --dry-run ) ]]; then
  echo 'Usage: sweep.sh <worktree> [--dry-run]' >&2
  exit 2
fi
worktree=$(cd -- "$1" && pwd -P)
if [[ $worktree == / || $worktree != "$(git -C "$worktree" rev-parse --show-toplevel)" ]]; then
  echo 'sweep: supply a worktree root' >&2
  exit 2
fi
logical_tree=$(cd -- "$1" && pwd -L)

# Filter a snapshot literally and omit this script and its ancestors. Match the
# end of the path or a boundary so a neighbouring worktree stays out of scope.
candidates=$(ps -axo pid=,ppid=,command= | SWEEP_TREE="$worktree" LOGICAL_SWEEP_TREE="$logical_tree" awk -v self="$$" '
  function names_tree(rest, path,    at,before) {
    while ((at=index(rest, path)) != 0) {
      before=at==1 ? " " : substr(rest, at-1, 1)
      rest=substr(rest, at+length(path))
      if (before ~ /[[:space:]="\047]/ && rest ~ /^([[:space:]\/"\047]|$)/) return 1
    }
    return 0
  }
  { pid=$1; parent[pid]=$2; sub(/^[[:space:]]*[0-9]+[[:space:]]+[0-9]+[[:space:]]+/, ""); command[pid]=$0 }
  END {
    for (i=self; i>0 && !skip[i]; i=parent[i]) skip[i]=1
    for (pid in command) {
      for (i=parent[pid]; i>1 && i!=self; i=parent[i]) {}
      if (!skip[pid] && i!=self && (names_tree(command[pid], ENVIRON["SWEEP_TREE"]) ||
                                   names_tree(command[pid], ENVIRON["LOGICAL_SWEEP_TREE"])))
        print pid, command[pid]
    }
  }')
while read -r pid command; do
  [[ -n $pid ]] || continue
  if [[ ${2:-} == --dry-run ]]; then
    printf 'would stop %s %s\n' "$pid" "$command"
  elif [[ $(ps -o command= -p "$pid" 2>/dev/null) == "$command" ]]; then
    printf 'stopping %s %s\n' "$pid" "$command"
    kill -TERM "$pid" 2>/dev/null || true
  fi
done <<< "$candidates"
