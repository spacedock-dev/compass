# Cleanup pass

Read this when the run starts (the ledger), at closeout after the last landing, and whenever the
run stops early. It tears down what this run made without asking, then counts what earlier runs
and other sessions left behind and asks the owner which of that to remove.

A burndown makes a lot of things: a worktree per layer and per reviewer, branches and backup
refs, spare-port boards, forwarders, monitors and delegated CLI runs. Each is cheap while the run
needs it. None removes itself, and the next run cannot tell an orphan from a sibling's live work
without the checks below.

Measured 2026-11-17, at the end of one Linear burndown: 78 clean worktrees from three earlier runs
sat under `.claude/worktrees/`, holding 21 local branches whose pull requests had all merged. A
`python3 -` started 20 days earlier from an old results checkout had been orphaned to pid 1 and
was holding a full core; stopping it took the one-minute load average from about 12 to 4.4. Every
one of those had been reported at some stopping point and none had been removed, because removal
was nobody's step.

## The run ledger

Start it before the first write of the run, in the session scratchpad as `ledger.txt`, one line per
thing the run creates, written when it is created:

```text
worktree  .claude/worktrees/<name>  <branch or detached>  <purpose>
branch    <name>                    <PR number once opened>
ref       <backup or temporary ref>
port      <spare port>              <what listens: board, forwarder>
pid       <pid>                     <command>  <how it stops>
monitor   <task id>                 <what it watches>
```

Record a delegated Codex or AGY run by the pid its wrapper prints, a `nohup` job by `$!`, and a
spare board by its port. The ledger is what makes "this run started it" a fact rather than a guess
from a name: worktree prefixes (`b3-`, `rv3-`) repeat across runs, and an earlier run's orphans
were adopted into this one under the same names.

## 1. Tear down this run's own artifacts

No question needed: [reconciliation step 7](reconciliation.md#7-next-landing-or-close-the-milestone)
already owns this, scoped to the ledger. Keep the stack's worktrees until the whole stack has
merged, and the closing docs worktree until its pull request has.

- **Processes first.** Stop each ledger pid by its own stop path (`server.py --stop --port <p>`
  for a board, `kill -TERM` otherwise), wait, and confirm with `kill -0` that it is gone. Stop a
  monitor with its task stop. A process that left its group survives a group kill; check by name
  as **AGENTS.md, "Parallel Work"** says.
- **Worktrees, then branches.** Remove each ledger worktree whose tracked tree is clean
  (`git worktree remove --force`, since `node_modules` is untracked). Then delete its branch only
  when `gh pr view <branch> --json state` says `MERGED`: a squash merge leaves the branch's
  commits off `main`, so `git branch -d` refuses every merged branch here and `-D` is the only
  delete, which is why the pull request state is the check. Delete backup refs the run made.
- **Run `git worktree prune`** and `gh stack sync --prune` from a stack worktree before removing it.

## 2. Census what else is left

Count before asking, so the question carries numbers. Each line below is something a run made,
found, or that this session measured as left behind.

| Category | How to find it | Exclude |
|---|---|---|
| Older worktrees | `git worktree list --porcelain`, those under `.claude/worktrees/` not in the ledger | `docs/*/.spacedock-state` (live Spacedock workflow state), the main checkout, any listed in the ledger |
| Merged branches | local branches with no worktree whose pull request is `MERGED` | branches with no pull request or an open one: report them with `git rev-list --count origin/main..<b>` |
| Orphaned processes | `ps -axo pid,ppid,%cpu,etime,command` with ppid 1, at least an hour old, matching `python3`, `node`, `codex exec`, `agy`, `server.py`, a test runner or a forwarder | the operator's own dashboard on 4553, the Codex app-server daemons, browser extension hosts, system services, anything you cannot name |
| Spare-port listeners | `lsof -nP -iTCP -sTCP:LISTEN` for `server.py` or `python3` on ports other than 4553 | 4553 and any port a live session owns |
| Old scratch | earlier sessions' scratch directories under the harness temp root, older than a week | the current session's scratchpad, and any directory holding an uncommitted hand-back the owner has not read |

For each candidate, collect the evidence the question will show: age, CPU, working directory
(`lsof -a -p <pid> -d cwd`), and what launched it if the parent still exists.

## 3. Check each candidate is safe to remove

A candidate passes only if every check holds. Anything that fails is reported, not removed.

- **A worktree** is clean (`git status --porcelain --untracked-files=no` prints nothing), and no
  live Claude, Codex or AGY session has its working directory inside it. Read activity times
  before running any `git status`, because `status` refreshes the index and makes every worktree
  look touched a moment ago.
- **A process holding a worktree's files open** is not proof of use. Here it was macOS's
  Virtualization VM, which holds read handles across the home directory through a shared folder.
  Name the process (`ps -o command -p <pid>`) before treating it as a user.
- **A branch** has a `MERGED` pull request. Never delete one that is ahead of `main` without one.
- **A process** is named: its command, working directory and age say what it is and that nothing
  depends on it. Stop it with `kill -TERM`, confirm it is gone, and use `kill -KILL` only after
  a TERM that did not take.
- Never touch `git stash` (it is shared by every worktree), the operator's dashboard, a
  `.spacedock-state` worktree, or another author's branch.

## 4. Ask the owner

Ask once, with every category that has candidates, after this run's own teardown. In Claude Code
use one structured question per category with the census numbers in the question and the
recommendation first; elsewhere one plain-text block with the same options. A category with no
candidates is reported, not asked. The answer applies to this run only.

| Category | Options |
|---|---|
| Older worktrees | Remove the clean ones (Recommended) · Remove only those whose branch merged · Keep them |
| Merged branches | Delete them (Recommended) · Keep them |
| Orphaned processes | Stop the named ones (Recommended) · Show me each first · Leave them |
| Spare-port listeners | Stop them (Recommended) · Leave them |
| Old scratch | Remove those older than a week · Keep them (Recommended, since a hand-back may be unread) |

An orphaned process the census could not name is never an option: report it with its pid, command
and working directory for the owner to decide.

## 5. Report

Say what was removed, by category and count, what was kept and why (dirty, unmerged, unnamed,
excluded), and what was skipped by the owner's answer. Name every kept item a later run might
otherwise adopt by mistake. Then run `git worktree list` and the process check once more, and quote
what remains.

## Keeping the next run cleaner

- Write the ledger line when you create the thing, not at the end.
- Give every reviewer worktree a run-specific prefix and remove it as soon as its verdict is read;
  a verdict file is all a later round needs.
- Bound every delegated or background job (`perl -e 'alarm shift; exec @ARGV' <seconds>` on macOS)
  so a hung one ends on its own.
- Never `ln -s` into a path that may already be a directory. `ln -sf <dir> node_modules` into an
  existing `node_modules` made a stray symlink inside it here, which only an `ls` showed.
