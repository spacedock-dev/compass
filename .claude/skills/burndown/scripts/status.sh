#!/bin/bash
# Usage: status.sh <run-dir>
# Shows elapsed time, ETA and health. The original board missed a hung probe
# because capped.sh puts the agent in a different process group.
# tasks.tsv columns: pid, label, start_epoch, typical_min, max_min, output_file
set -eu
if [[ $# -ne 1 ]]; then
  echo 'Usage: status.sh <run-dir>' >&2
  exit 2
fi
run_dir=$(cd -- "$1" && pwd -P)
now=$(date +%s)
printf '%-34s %8s %10s %-8s %s\n' TASK ELAPSED ETA STATE NOTE
if [[ -f $run_dir/tasks.tsv ]]; then
  while IFS=$'\t' read -r pid label start typical maximum output || [[ -n $pid ]]; do
    [[ -z $pid || $pid == \#* ]] && continue
    if [[ ! $pid =~ ^[1-9][0-9]*$ || ! $start =~ ^[0-9]+$ ||
          ! $typical =~ ^[0-9]+$ || ! $maximum =~ ^[0-9]+$ ]]; then
      printf 'status: invalid task row for %s\n' "$pid" >&2
      continue
    fi
    elapsed=$(( (now - 10#$start) / 60 ))
    if kill -0 "$pid" 2>/dev/null; then
      state=running
      note=
      if (( elapsed < 10#$typical )); then
        eta="~$((10#$typical - elapsed))m"
      elif (( elapsed < 10#$maximum )); then
        eta="≤$((10#$maximum - elapsed))m"
      else
        eta=overdue
        state=OVERDUE
      fi
      # Follow the wrapper and its children's groups without reading any report body.
      while read -r child cpu age; do
        [[ -z $child ]] && continue
        state='STUCK?'
        note="child $child at ${cpu}% for $age"
        break
      done < <(ps -axo pid=,ppid=,pgid=,pcpu=,etime= | awk -v root="$pid" '
        { pid[NR]=$1; parent[$1]=$2; group[$1]=$3; cpu[$1]=$4; age[$1]=$5 }
        END {
          if (group[root] == root) groups[root]=1
          for (i in parent)
            if (parent[i] == root && group[i] != group[root]) groups[group[i]]=1
          for (n=1; n<=NR; n++) {
            i=pid[n]
            if (i == root || cpu[i]+0 < 90) continue
            ancestor=parent[i]
            while (ancestor > 1 && ancestor != root) ancestor=parent[ancestor]
            if (!groups[group[i]] && ancestor != root) continue
            if (age[i] ~ /-/ || split(age[i], parts, ":") > 2 || parts[1]+0 >= 20)
              print i, cpu[i], age[i]
          }
        }')
    else
      state='done'
      eta=-
      note='no output'
      if [[ -s $output ]]; then
        bytes=$(wc -c < "$output" | tr -d '[:space:]')
        note="$bytes bytes"
      fi
    fi
    printf '%-34s %7sm %10s %-8s %s\n' "$label" "$elapsed" "$eta" "$state" "$note"
  done < "$run_dir/tasks.tsv"
fi

# A chain missing here never fires. Launch it with its absolute run-dir path.
chains=$(ps -axo command= | RUN_CHAIN_PREFIX="$run_dir/chain-" awk '
  BEGIN { prefix=ENVIRON["RUN_CHAIN_PREFIX"] }
  { at=index($0, prefix)
    if (at) {
      name=substr($0, at+length(prefix))
      if (match(name, /^[[:alnum:]_-]+\.sh([[:space:]]|$)/))
        print "chain-" substr(name, 1, index(name, ".sh")+2)
    }
  }' | sort -u | paste -sd ' ' -)
printf 'chains waiting: %s\n' "${chains:-none}"
