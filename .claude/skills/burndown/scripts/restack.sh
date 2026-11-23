#!/bin/bash
# Usage: restack.sh <worktree> <new-base-ref> <branch>:<old-parent-tip> [...]
# Replaces repeated agent restacks with a bottom-up rebase, rebuild and check.
# Generated conflicts take a temporary side. Source conflicts stop for a human or agent.
# Set RESTACK_GENERATED_PATHS to a newline-separated list of repo-relative build outputs.
# Optional RESTACK_PAGE_NOTES and RESTACK_PAGE_TEST name the page measurements and bound test.
# Set RESTACK_COMMIT_GIT to select the git executable for the signed-off rebuild commit.
set -euo pipefail
if [[ $# -lt 3 || -z ${RESTACK_GENERATED_PATHS:-} ]]; then
  echo 'Usage: RESTACK_GENERATED_PATHS=... restack.sh <worktree> <new-base-ref> <branch>:<old-parent-tip> [...]' >&2
  exit 2
fi
cd -- "$1"
parent=$2
shift 2
page_notes=${RESTACK_PAGE_NOTES:-}
page_test=${RESTACK_PAGE_TEST:-}
generated=()
while IFS= read -r path; do
  if [[ -n $path ]]; then generated+=("$path"); fi
done <<< "$RESTACK_GENERATED_PATHS"
if (( ${#generated[@]} == 0 )); then
  echo 'restack: supply at least one generated file path' >&2
  exit 2
fi

if [[ -n $(git status --porcelain --untracked-files=no) ||
      -d $(git rev-parse --git-path rebase-merge) || -d $(git rev-parse --git-path rebase-apply) ]]; then
  echo 'restack: start in a clean, idle worktree' >&2
  exit 2
fi
for pair in "$@"; do
  if [[ $pair != ?*:?* ]] ||
     ! git show-ref --verify --quiet "refs/heads/${pair%%:*}" ||
     ! git merge-base --is-ancestor "${pair#*:}" "refs/heads/${pair%%:*}"; then
    printf 'restack: expected a local branch and its old ancestor, got %s\n' "$pair" >&2
    exit 2
  fi
done

build_log=$(mktemp -t burndown-restack.XXXXXXXX)
trap 'rm -f -- "$build_log"' EXIT

resolve_page_measurement() {
  # Both layers measured different trees. Keep the paragraphs and the larger
  # bound, then check the rebuilt tree. Leave other edits for source review.
  python3 - "$1" "$2" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
kind = sys.argv[2]
conflict = r"^<<<<<<< [^\n]*\n(.*?)^=======\n(.*?)^>>>>>>> [^\n]*\n"
bound = r"const PAGE_MAX_BYTES = ([\d_]+);\n"


def resolve(match):
    ours, theirs = match.groups()
    if kind == "notes":
        if not ours.strip() or not theirs.strip():
            raise ValueError("expected a measurement paragraph on both sides")
        return ours + "\n" + theirs
    values = [re.fullmatch(bound, side) for side in (ours, theirs)]
    if any(value is None for value in values):
        raise ValueError("expected only PAGE_MAX_BYTES on each side")
    size = max(int(value[1].replace("_", "")) for value in values)
    return f"const PAGE_MAX_BYTES = {size:_};\n"


try:
    contents, count = re.subn(conflict, resolve, path.read_text(), flags=re.M | re.S)
    if not count or re.search(r"^(<<<<<<< |=======|>>>>>>> )", contents, flags=re.M):
        raise ValueError("unresolved conflict markers")
except ValueError as error:
    sys.exit(f"restack: {path}: {error}")
path.write_text(contents)
PY
}

export GIT_LITERAL_PATHSPECS=1
for pair in "$@"; do
  branch=${pair%%:*}
  old_parent=${pair#*:}
  if ! git -c merge.conflictStyle=merge rebase --merge --onto "$parent" "$old_parent" "$branch"; then
    while :; do
      conflicts=()
      while IFS= read -r -d '' path; do
        conflicts+=("$path")
      done < <(git diff --name-only --diff-filter=U -z)
      if (( ${#conflicts[@]} == 0 )); then
        printf 'STOP %s: rebase failed without an unresolved file\n' "$branch" >&2
        exit 1
      fi
      for path in "${conflicts[@]}"; do
        if [[ $path == "$page_notes" ]]; then
          resolve_page_measurement "$path" notes
        elif [[ $path == "$page_test" ]]; then
          resolve_page_measurement "$path" bound
        elif printf '%s\n' "${generated[@]}" | grep -Fxq -- "$path"; then
          git checkout --theirs -- "$path"
        else
          printf 'STOP %s: source conflict in %s\n' "$branch" "$path" >&2
          exit 1
        fi
        git add -- "$path"
      done
      if GIT_EDITOR=true git -c merge.conflictStyle=merge rebase --continue; then break; fi
    done
  fi
  if [[ $(git symbolic-ref --quiet --short HEAD) != "$branch" ]]; then
    printf 'STOP %s: rebase did not restore the branch\n' "$branch" >&2
    exit 1
  fi

  if ! pnpm -s build > "$build_log" 2>&1; then
    cat "$build_log" >&2
    printf 'STOP %s: pnpm build failed\n' "$branch" >&2
    exit 1
  fi
  git add -- "${generated[@]}"
  if ! git diff --cached --quiet; then
    SKIP_CLAUDE_PRECOMMIT=1 "${RESTACK_COMMIT_GIT:-git}" commit -s -m 'build(frontend): rebuild the page after restacking'
  fi
  pnpm -s build:check
  if [[ -n $page_test ]] && ! node --test "$page_test"; then
    cat "$build_log" >&2
    printf 'STOP %s: re-measure PAGE_MAX_BYTES in %s and its measurement note %s\n' \
      "$branch" "$page_test" "$page_notes" >&2
    exit 1
  fi
  printf 'OK %s %s\n' "$branch" "$(git rev-parse --short HEAD)"
  parent=$branch
done
