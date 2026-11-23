#!/bin/bash
# Usage: launch-lenses.sh <repo-dir> <run-dir> <review-worktree-root> <layer-id> <base> <head> <title> <task-files> <notes-file> <lens-preamble> <builder-hand-back> <port-a> <port-b>
# Creates two detached reviews, writes both prompts, starts Codex and AGY under
# capped.sh, then registers both. One launch replaces serial lens setup.
# Set CODEX_MODEL, CODEX_EFFORT and AGY_MODEL from the approved live model table.
set -euo pipefail
if [[ $# -ne 13 || ! $4 =~ ^[[:alnum:]_-]+$ || ! ${12} =~ ^[1-9][0-9]*$ ||
      ! ${13} =~ ^[1-9][0-9]*$ || ${12} == "${13}" ]]; then
  sed -n '2s/^# //p' "$0" >&2
  exit 2
fi
: "${CODEX_MODEL:?Set CODEX_MODEL}" "${CODEX_EFFORT:?Set CODEX_EFFORT}" "${AGY_MODEL:?Set AGY_MODEL}"
cap=${LENS_CAP_SECONDS:-3600}
typical=${LENS_TYPICAL_MINUTES:-12}
maximum=${LENS_MAX_MINUTES:-25}
if [[ ! $cap =~ ^[1-9][0-9]*$ || ! $typical =~ ^[1-9][0-9]*$ ||
      ! $maximum =~ ^[1-9][0-9]*$ ]]; then
  echo 'launch-lenses: use positive integers for cap and ETA values' >&2
  exit 2
fi
script_dir=$(cd -- "$(dirname -- "$0")" && pwd -P)
repo=$(cd -- "$1" && pwd -P)
run_dir=$(cd -- "$2" && pwd -P)
worktree_root=$(cd -- "$3" && pwd -P)
layer=$4
base=$(git -C "$repo" rev-parse --verify "$5^{commit}")
head=$(git -C "$repo" rev-parse --verify "$6^{commit}")
title=$7
tasks=$8
notes=$9
preamble=${10}
handback=${11}
port_a=${12}
port_b=${13}
command -v codex agy >/dev/null
[[ -r $preamble && -r $notes && -r $handback ]]
handback=$(cd -- "$(dirname -- "$handback")" && printf '%s/%s\n' "$(pwd -P)" "$(basename -- "$handback")")

for lens in a b; do
  worktree=$worktree_root/rv-$layer-$lens
  probe=$run_dir/probe-$layer-$lens
  prompt=$run_dir/prompt-lens-$layer-$lens.md
  output=$run_dir/lens-$layer-$lens.md
  log=$run_dir/log-lens-$layer-$lens.txt
  if [[ -e $worktree || -e $probe || -e $prompt || -e $output || -e $log ]]; then
    printf 'launch-lenses: artifacts already exist for %s %s\n' "$layer" "$lens" >&2
    exit 1
  fi
done

for lens in a b; do
  worktree=$worktree_root/rv-$layer-$lens
  probe=$run_dir/probe-$layer-$lens
  prompt=$run_dir/prompt-lens-$layer-$lens.md
  if [[ $lens == a ]]; then port=$port_a; else port=$port_b; fi
  mkdir -- "$probe"
  {
    cat -- "$preamble"
    printf '\n---\n\n## Layer under review: %s, %s\n\n' "$layer" "$title"
    # The backticks belong to the Markdown prompt.
    # shellcheck disable=SC2016
    printf -- '- Base: %s. Head: %s. Review `git diff %s..%s`.\n' "$base" "$head" "$base" "$head"
    printf -- '- Task file(s): %s. Builder hand-back: %s\n' "$tasks" "$handback"
    printf -- '- Rulings and coordinator notes:\n'
    sed 's/^/  /' "$notes"
    printf '\n%s\n' '- Use bounded or literal searches over the built page.'
    printf -- '- Probe directory: %s\n- Review port, if needed: %s\n' "$probe" "$port"
  } > "$prompt"
  git -C "$repo" worktree add --detach "$worktree" "$head"
  printf 'worktree  %s  detached %s\nport  %s  lens %s %s\n' \
    "$worktree" "$head" "$port" "$layer" "$lens" >> "$run_dir/ledger.txt"
done

cd -- "$worktree_root/rv-$layer-a"
nohup "$script_dir/capped.sh" "$cap" codex exec -m "$CODEX_MODEL" \
  -c "model_reasoning_effort=$CODEX_EFFORT" --sandbox danger-full-access -C "$PWD" \
  -o "$run_dir/lens-$layer-a.md" "$(cat -- "$run_dir/prompt-lens-$layer-a.md")" \
  < /dev/null > "$run_dir/log-lens-$layer-a.txt" 2>&1 &
pid_a=$!
started=$(date +%s)
printf 'pid  %s  lens %s a (cap %ss)\n' "$pid_a" "$layer" "$cap" >> "$run_dir/ledger.txt"
printf '%s\t%s lens A (Codex %s %s)\t%s\t%s\t%s\t%s\n' \
  "$pid_a" "$layer" "$CODEX_MODEL" "$CODEX_EFFORT" "$started" "$typical" "$maximum" \
  "$run_dir/lens-$layer-a.md" >> "$run_dir/tasks.tsv"

cd -- "$worktree_root/rv-$layer-b"
nohup "$script_dir/capped.sh" "$cap" agy --model "$AGY_MODEL" --dangerously-skip-permissions \
  --add-dir "$run_dir/probe-$layer-b" -p "$(cat -- "$run_dir/prompt-lens-$layer-b.md")" \
  < /dev/null > "$run_dir/lens-$layer-b.md" 2> "$run_dir/log-lens-$layer-b.txt" &
pid_b=$!
started=$(date +%s)
printf 'pid  %s  lens %s b (cap %ss)\n' "$pid_b" "$layer" "$cap" >> "$run_dir/ledger.txt"
printf '%s\t%s lens B (AGY %s)\t%s\t%s\t%s\t%s\n' \
  "$pid_b" "$layer" "$AGY_MODEL" "$started" "$typical" "$maximum" \
  "$run_dir/lens-$layer-b.md" >> "$run_dir/tasks.tsv"
printf 'lenses for %s: %s %s\n' "$layer" "$pid_a" "$pid_b"
