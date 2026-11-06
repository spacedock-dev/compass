# Build, review and land

Read this when an approved group is ready to build. Apply the selected adapter's PR-link rules;
all stack, verification and merge rules here are shared. Read
[reconciliation](reconciliation.md) after each landing, before reporting an issue finished.

## 4. Build a layer

In the layer's worktree. Items 1, 2, 5 and 6 are the build stage, 4 is the review stage, and 3 is the
orchestrator's. A build subagent stops after item 2 and hands back its worktree and review-server
port. After the review, item 5 says who makes the fixes; item 6 goes with them.

1. **REQUIRED SUB-SKILL:** invoke `superpowers:test-driven-development`. Write the failing test first
   and watch it fail, then the code. A change to a component or view updates its story, and
   `pnpm test:stories` (in the suite) proves it. If the layer touches the web surface, run
   `pnpm build` before the suite: the suite includes `pnpm build:check`, which fails on a stale
   bundle, and the Mode 2 walk serves whatever `react.html` is in the worktree, so without the build
   it reviews the old page. Run the touched test modules and the checks that can catch what changed,
   not the whole suite: the suite runs once per pull request, in item 5. A parity or shape test is
   held to a fixture built from a captured real payload, as
   [planning](planning.md#2-plan-group-order-estimate-choose-models) says.
2. Invoke `sync-docs` in the layer that ships the behaviour, never once for the whole stack. The
   shipped `SKILL.md` and `HOW_TO_USE.md` change in the layer that ships what they describe. Never
   advance `COMPATIBILITY.md`'s `docs-synced-through` marker in a layer.
3. **REQUIRED SUB-SKILL:** the orchestrator invokes `visual-review-and-fix` in
   `Mode 2: after development`. What this layer introduced goes to item 5; what predates it is filed
   with the base comparison that proves so. Two walks cost more than a page: the board opens a session
   page only for sessions observed in the last 24 hours, and some states appear only after an Analyze
   press, which is a model call. When a walk needs a paid reading, or a harness session beyond the
   real-session check below, ask the owner first; otherwise name the story or press test that stands
   in for it in the pull request.

   **Walk a real session at the first layer that makes a terminal or skill behaviour reachable**: a
   new action word, a terminal command, or anything a session's own hook or tool call reaches. Do it
   at that layer, not only at the final Verification walk. `scripts/session_smoke.py` starts a
   spare-port board from the worktree, creates a headless Claude Code session in a scratch project
   with a real first prompt, types each action into it, and prints the permission denials, the tool
   commands and their results. The board and the session share a scratch Compass home, so neither
   the owner's board nor a sibling's sees them. It stops the board it started and kills each
   command's process group; a process that left its group survives, so check for leftovers as
   **AGENTS.md, "Parallel Work"** says. On
   2026-11-06 the two most expensive defects of the run passed about 9,000 tests and 19 review
   agents, because every fixture agreed with itself: the full session UUID against the board's
   8-character key, and a citation lost outside the context window. Both surfaced only in the final
   walk, which cost a fix pull request, a CI cycle and about 40 minutes. The same recipe took minutes
   once known. The helper refuses `drift again`, plain `drift` (a fresh session has no stored
   reading, so it presses) and any action it cannot show is free, unless `--allow-spend` is passed;
   ask the owner before passing it. Even then the scratch home starts with model calls not allowed,
   so a press stops at Compass's permission answer. Put its output summary in the pull request's
   Verification.
4. Review the layer at the depth its tier sets, before it is submitted. Reviewing an open pull
   request costs a second CI cycle. Self-verify is the orchestrator's own read of the diff and the
   checks; the other tiers are reviewer subagents at the review stage's model. Spend the depth on the
   layer that makes behaviour reachable, and review the combined diff of the layers below it there:
   on 2026-11-06 layer D's full adversarial review found four defects in layer C's code that C's own
   two-lens review had missed, once D made that code reachable without a prompt. So a layer that
   nothing calls yet is not submitted on its own: build the reachable layer on top, review the two
   together at the higher of their tiers, and submit them together. Submitting the lower one first
   would cost a second CI cycle for every fix the combined review finds in it. Freeze the stack
   while a reviewer is reading: a restack rewrites the layers above under them and turns correct
   findings into false refutations. File what a review defers.
5. Fix what the walk and the review found. One correction round per layer is the default; after a
   round with several fixes, re-check against a live board, because fix rounds here produce about
   one new defect per four fixes. The orchestrator makes a small fix (a few lines and its test)
   inline: measured on 2026-11-06, an inline fix took about 5 minutes and a fresh builder round 20
   to 45, most of it the full suite. A larger round goes to a builder: resume the one that built the
   layer when the harness still holds it, or dispatch a fresh build-stage subagent. Either way the
   round runs the touched tests. Then, once per pull request and before it is submitted, rebuild if
   anything touched the web surface and run the canonical pre-PR suite from **AGENTS.md, "Pre-PR
   Checks"**, from there rather than from a copy. Give `scripts/run_tests.py` a `-j` share of the
   cores when another suite is running. `test_documentation` asserts `SKILL.md`, `SECURITY.md` and
   `README.md`.
6. Make the rebuilt bundle the last commit of any web-surface layer: after the last source change,
   `pnpm build`, commit the built files, then `pnpm build:check`. Never resolve or compute the
   bundle by hand.

Keep CI waiting productive: once a layer is submitted, build the next layer on top of it while its
checks run.

## 5. Stack, submit and land

**Build the web-surface stack serially in one worktree,** because each layer's tree depends on the
one below. gh-stack keeps one stack catalog in the git common directory, shared by every linked
worktree, and `rebase` and `sync` update a branch checked out in another worktree as long as that
worktree is clean and idle. A dirty, busy or mid-rebase worktree blocks the update, and neither
command stashes for you, so have builders commit and stop before you restack.

- Layer by layer in the stack's worktree: `gh stack init --base main <branch-1>`, commit, then
  `gh stack add <branch-2>` for the next layer, and so on.
- Adopting existing branches: `gh stack init --base main <b1> <b2> <b3>`, then `gh stack rebase`
  so each layer contains the one below, resolving pins as below. `init` adopts without rebasing.
- An in-flight pull request that is already in a native stack: `gh stack checkout <pr-url>`. A URL,
  because a bare number is read as a stack number first. An ordinary pull request is not in a stack,
  and `checkout` refuses it: adopt its branch with `init`, or, for an independent group, leave it a
  plain pull request.

Use the selected adapter's branch and PR-link rules. A partial layer must not imply that the
whole issue is finished. Never commit or push to another author's PR branch without the user's
explicit confirmation, including when a plan authorizes its eventual merge.

**Submit.** `gh stack submit --auto --open` opens a ready pull request for every layer that has
none, and there is no way to leave one out. Submit a reviewed layer before you `gh stack add` the
next, unreviewed one, unless it is held for the layer that makes it reachable (step 4, item 4). Once a layer above is unreviewed, update the existing pull requests with `gh stack push` and
run `submit` again only when the top layer has been reviewed. Without `--open` new pull requests are
drafts, and a draft blocks the stack merge. `submit` writes the title and body only when it creates a
pull request, and its titles come from the branches, so then run
`gh pr edit <n> --title "<title>" --body-file <file>` for each layer, with scratch files named per
branch. The title follows **AGENTS.md, "PR Workflow"**: the shipped behaviour in a plain sentence,
ready for release notes, with no tracker brand, issue key or tracker URL (recent titles look like
"Find sessions: search and filter the Sessions page"). Each body carries:

- The selected adapter's issue links: finishing links only on the layer that completes that issue;
  partial layers use non-closing references. GitHub parent containers close only after their
  children and parent acceptance have been reconciled.
- A `## Verification` section naming what ran and what it said.

An independent group is an ordinary pull request on `main`: `gh pr create`, then land it as below.

**Fix a lower layer.** `gh stack checkout <branch-k>`, commit with `-s`, then
`gh stack rebase --upstack`. When a rebase stops on one of the built files (`react.html`,
`react.integrity.json`, `react-licenses.txt`), take either side, run `pnpm build`, `git add` the
result, and `gh stack rebase --continue`. Resolve a conflict in a source under `frontend/` by hand,
then rebuild. Then check out each layer above from the bottom up and run `pnpm build:check` and the
suite; where `build:check` fails with no textual conflict, rebuild, amend that layer's bundle commit
and `gh stack rebase --upstack` from it. Then `gh stack push`. Only layer k and the layers above
it re-run CI. A clean rebase can still break at runtime: grep the renamed symbols across every
layer.

**Main moved** (an independent pull request landed, or a sibling): once no review is reading the
stack, `gh stack sync`. It fetches, rebases and pushes every layer. On a rebase conflict it restores
the branches and exits non-zero: `gh stack rebase`, resolve as above, then `gh stack push`. When the
local stack and the one on GitHub disagree about which pull requests belong to it, a non-interactive
`sync` prints `Sync aborted` and **exits 0 having pushed nothing**: import the remote stack with
`gh stack checkout <pr-url>` and sync again. Either way, before waiting on CI, confirm each layer's
pushed head (`gh pr view <n> --json headRefOid`) is the local branch tip. All layers re-run in
parallel, which costs one CI cycle, not one per layer.

**Land the stack** when its planned layers are built, reviewed and green, or land the reviewed lower
part of it earlier (below) when a higher layer will take a while, or when a group outside the stack
is waiting on a lower layer. Each landing is followed by step 6 for the issues it finished.

**Merge only when every layer being landed is ready:** `git fetch origin main:main` first, because
`gh stack view --json` judges `needsRebase` against your local `main` and does not fetch; then
`gh stack view --json` shows no rebase needed; every layer's checks are green on its **current**
head SHA (a run that finished before a push still reports green); `mergeStateStatus` is `CLEAN`; and
every review thread on every layer is resolved, because the ruleset requires thread resolution and
one open thread fails the whole atomic merge. Read Copilot's inline comments, not only top-level
reviews. Disposition each thread (fix it with the lower-layer procedure, or reply and file it), then
resolve it; a `BLOCKED` state with no failing check means an open thread. Then:

```bash
gh stack merge --squash --yes
gh stack sync --prune
```

Always pass `--squash`. Without it `gh stack merge` uses your last-used method, and the ruleset
allows only squash and rebase. Squash is the repository's method: six native stacks, the largest
fifteen layers, landed this way with verified signatures and one push run on `main` per stack.

**Land part of a stack:** `gh stack merge <pr> --squash --yes`, where `<pr>` is the highest layer to
land. A bare number is read as a stack number first, so check in `gh stack view` that no stack has
that number. GitHub rebases and retargets the rest, which changes their heads: `gh stack sync`, so
the local branches and the pushed heads agree again, then wait for CI on the new heads before
merging again.

**Never, on a stacked branch:** `gh pr merge` (it merges a layer into its parent branch, leaving
its code off `main` even if tracker automation calls it finished), `gh pr update-branch`, a plain `git rebase origin/main`,
`--delete-branch`, or the server-side "Rebase stack" button, whose commits are unsigned. A pull
request whose base is another feature branch but is not in a native stack gets closed when its base
is deleted (#251 and #252); link it with `gh stack link` or do not create it.

For an independent pull request: confirm `CLEAN` and current-head checks, then
`gh pr merge <n> --squash --delete-branch`, after removing any worktree that holds the branch. The
repository deletes a merged head branch on GitHub by itself; `--delete-branch` also removes the
local one. If it is behind, `gh pr update-branch` and wait for the new run.

## Parallel work

Read **AGENTS.md, "Parallel Work"** before starting a second builder, and hand its contention list
to every one.

- The web-surface stack is built serially in one worktree. Its layers depend on each other's trees.
- An independent group may run in its own worktree with its own subagent, its own review-server
  port, and a `-j` share of the cores. Its builder stops after step 4.2 and hands back; the
  orchestrator walks it, and steps 4.5 and 4.6 go as item 5 of step 4 says.
- Dispatch subagents from the repository root, at their stage's model and effort, and confirm each
  produced work before calling it running.
- Give every agent a time limit when you dispatch it, about twice what that stage usually takes,
  and stop it when the limit passes. A review pair once hung for 50 minutes with nothing to stop it.
  Where the dispatch takes no timeout (the Claude Code `Agent` tool does not), arm a wake-up at
  dispatch, such as a `Monitor` or a scheduled check.
- Use unnamed agents for one-shot work (a lens, an arbiter, a deep dive), and stop each one once it
  has delivered (in Claude Code, `TaskStop`). Named agents could not acknowledge a shutdown
  request, and they piled up. Keep a builder that handed back after item 2 until its layer needs no
  further round, so a larger correction round can resume it with its context; stop it then. Use
  only the agent lifecycle and model-selection capabilities the current harness actually exposes.
- A loopback-port failure under concurrent suites is contention, not a regression: rerun that module
  alone before believing it.

## Delivery invariants

- Never edit a version field. The Release workflow owns them.
- Never resolve the built bundle textually; rebuild it from the sources.
- Never trust an exit status from `gh stack sync` as proof that it pushed.
- Never rewrite a branch (restack, rebase, amend, reset) while a suite or a review is running on
  it. The orchestrator once rewrote a branch while a builder's suite ran on it; a verdict reached
  that way describes a tree that is no longer there.
- Never widen an issue's scope to make it feel complete. File the rest in the selected tracker.
- Never promote a deferred review finding into the layer in flight when it costs another CI round.
