# Build, review and land

Read this when an approved group is ready to build. Apply the selected adapter's PR-link rules;
all stack, verification and merge rules here are shared. Read
[reconciliation](reconciliation.md) after each landing, before reporting an issue finished.

## 4. Build a layer

In the layer's worktree. Items 1, 2, 5 and 6 are the build stage, 4 is the review stage, and 3 is the
orchestrator's. The builder runs items 1, 2 and the final-head checks in item 5, then hands back
its worktree, commit, verification and review-server port. Apply the same checks to a correction
round's final head.

1. **REQUIRED SUB-SKILL:** invoke `superpowers:test-driven-development`. Write the failing test first
   and watch it fail, then the code. A change to a component or view updates its story, and
   `pnpm test:stories` (in the suite) proves it. If the layer touches the web surface, run
   `pnpm build` before the gate: the gate includes `pnpm build:check`, which fails on a stale
   bundle, and the Mode 2 walk serves whatever `react.html` is in the worktree, so without the build
   it reviews the old page. Run touched modules while building. Keep test probes and fixtures in
   a temporary directory outside the checkout, with copies of the config they need. A probe under
   `frontend/` raced the package test's directory copy and ejected #1035 with `ENOENT`.
   For each card or row that publishes an answer, give every answer and absence state its own
   Storybook story, including withdrawn, stale, failed over an earlier answer, unreadable and
   Codex when applicable. Each `play` asserts
   the exact words and excludes the other states' words. A withdrawn reading shown as current led
   a round with 17 confirmed findings. Check frontend matchers and assertions after a server
   sentence rename. A literal matcher and its old-word test escaped one layer.
   Base each parity or shape test on a fixture built from a captured real payload, as
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
   findings into false refutations. Apply the tier's [finding rules](delegation.md#when-the-stages-disagree).
5. Fix what the walk and the review found. One correction round per layer is the default; after a
   round with several fixes, re-check against a live board, because fix rounds here produce about
   one new defect per four fixes. The orchestrator makes a small fix (a few lines and its test)
   inline: measured on 2026-11-06, an inline fix took about 5 minutes and a fresh builder round 20
   to 45, most of it the full suite. A larger round goes to a builder: resume the one that built the
   layer when the harness still holds it, or dispatch a fresh build-stage subagent. Either way the
   round runs touched tests. For a **stacked page layer**, the builder runs
   `python3 scripts/pre_pr.py -j 4` once after the final commit and reports the lane summary.
   CI was the first full run for twelve redesign PRs. After that pass, fix failures this layer
   caused and rerun the printed failed commands. Repeat the gate only if the fix touches a file
   another lane reads. One builder spent about 20 minutes per pass and hit a two-hour cap.
   For a **standalone PR off main in this burndown**, run focused tests and let CI run the full gate.
   Three builders waiting on the shared lock cost up to two gate runs of idle time.
   **AGENTS.md, "Pre-PR Checks"** owns the commands and the runner's lane selection.
   When a standalone docs branch takes a base containing a newly landed page layer, use
   `scripts/ci_scope.py`'s `frontend_docs_tests` output to rerun the affected Vitest files before
   pushing. A newly landed Settings test pinned a sentence in `MANUAL.md` and caught the rewrite
   in CI.
6. Make the rebuilt bundle the last commit of any web-surface layer: after the last source change,
   `pnpm build`, commit the built files, then `pnpm build:check`. Never resolve or compute the
   bundle by hand.

If a criterion depends on a later layer, build the target or other reachable part now and report
the rest under `Deferred to <issue>`. Ship working links and controls. Four builders stopped on
later-layer dependencies before this hand-back convention.

## 5. Stack, submit and land

**Keep one line of history for the web surface.** Use two or three layers per slice, as the owner
ruled after restack work grew with the square of the layer count. Keep each upper slice on its
known base until the lower slice lands, then restack it onto `main`. An early restack would need
repeating if CI changed a lower tip. gh-stack shares its catalog across linked worktrees.
Have builders commit and stop before a restack. A dirty, busy or mid-rebase worktree blocks it.

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
Check its change against `git merge-base origin/main HEAD` so a moved `origin/main` cannot make a
standalone branch appear to edit the page. Keep any required web-surface edits for the page line
and report them under `Needs the page line`. A standalone terminal fix once rebuilt the page.
Parse `gh` stdout alone. Read the PR number with `gh pr list --head <branch>`: a stderr hint from
`gh pr create` once replaced the URL passed to `gh stack link`.

**Fix a lower layer.** After committing the fix with `-s`, use
[`restack.sh`](../scripts/restack.sh) in an idle worktree that can check out the affected branches.
Save each old parent tip before rewriting it and pass the layers bottom-up. Set
`RESTACK_GENERATED_PATHS` to the newline-separated relative build outputs and CSS budget files.
For Compass these are `react.html`, `react.integrity.json` and `react-licenses.txt` under the
runtime's `web/` directory, plus `frontend/css-budget.json` and `frontend/css-coverage.json`.
For Compass, set `RESTACK_PAGE_NOTES` to `docs/design-sample-session.md` and `RESTACK_PAGE_TEST` to
`frontend/build/page-size.test.mjs`. A known measurement conflict keeps both paragraphs and
the larger bound for remeasurement after the rebuild. The helper takes a temporary side for
generated conflicts, rebuilds from source, checks the result and stops on a source conflict.
Set `RESTACK_COMMIT_GIT=/usr/bin/git` for Compass's sign-off path.
Six agent restacks in slice 1 prompted the helper. Its first live run preserved the fix without
a new bundle commit.

Resolve source conflicts before continuing the restack. After a delegated resolution, compare
every affected file against both sides for unexpected shrinkage. One rebase truncated three
files. Check the exit status and resulting branch before any push or retarget. A failed rebase
once went through a pipeline that masked its exit and opened a PR on the old base. Run the layer's
affected checks and grep renamed symbols across the upper layers, then `gh stack push`.

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

**Know whether `main` has a merge queue** before landing:
`gh api 'repos/{owner}/{repo}/rules/branches/main' --jq '.[].type'` lists `merge_queue` when the
ruleset requires one. The commands below are the same either way; what they do differs.

- **With a queue,** `gh stack merge` adds a stack's pull requests to the queue instead of merging
  them, and so does `gh pr merge` for an independent pull request (on one whose checks are still
  running it turns on auto-merge, which enqueues it once they pass; never on a stacked branch, see
  below). Never pass `--admin`, which skips the queue. The queue builds
  each entry on top of `main` and the entries ahead of it, runs the required checks on that result,
  and lands it with its own merge method, squash. Nothing has to be up to date first, so never run
  `gh pr update-branch`. Landing is done when the pull requests show `MERGED`, not when the command
  returns. Poll PR `state`, `mergeStateStatus` and GraphQL `mergeQueueEntry.state`. A nonexistent
  field hid an ejection for hours. While a stack is queued, `gh stack sync` skips its queued
  branches and `gh stack modify` refuses. Restructure after it lands or leaves the queue.
  An entry whose group fails a check or
  conflicts is removed from the queue: fix it with the lower-layer procedure, wait for green on the
  new head, and merge again.
  Wait for a queued PR to land before linking another PR onto it. Restack and retarget the
  successor onto `main` after the landing. A queued layer once refused the next link.
- **Without one,** the ruleset requires each branch be up to date, and `gh stack merge` merges at
  once. A sibling landing first puts the stack behind: `gh stack sync` and a full CI re-run before
  merging.

**Merge only when every layer being landed is ready:** `git fetch origin main:main` first, because
`gh stack view --json` judges `needsRebase` against your local `main` and does not fetch; then
`gh stack view --json` shows no rebase needed (with a queue, a textual conflict with `main` still
needs one; being merely behind does not); every layer's checks are green on its **current**
head SHA (a run that finished before a push still reports green); `mergeStateStatus` is `CLEAN`; and
every review thread on every layer is resolved, because the ruleset requires thread resolution and
one open thread fails the whole atomic merge. Read Copilot's inline comments, not only top-level
reviews. Disposition each thread (fix it with the lower-layer procedure, or reply and file it), then
resolve it; a `BLOCKED` state with no failing check means an open thread. For a stack that fits
the queue window, or when there is no queue:

```bash
gh stack merge --squash --yes
gh stack sync --prune
```

With a queue, `gh stack merge` returns once the stack is enqueued, not landed. Wait until every
layer shows `MERGED` before running `gh stack sync --prune`, which skips queued branches and so
prunes nothing earlier, and before step 6.

Always pass `--squash`. Without a queue, `gh stack merge` otherwise uses your last-used method, and
the ruleset allows only squash and rebase; with one, the queue's own method (squash) decides, and
passing the flag keeps the command the same under either rule. Squash is the repository's method:
six native stacks, the largest fifteen layers, landed this way with verified signatures and one push run on `main` per stack.

**Land part of a stack:** `gh stack merge <pr> --squash --yes`, where `<pr>` is the highest layer to
land. A bare number is read as a stack number first, so check in `gh stack view` that no stack has
that number. Once those layers land, GitHub rebases and retargets the rest, which changes their
heads: `gh stack sync`, so the local branches and the pushed heads agree again, then wait for CI on
the new heads before merging again.

With Compass's measured queue window, enqueue at most five consecutive stacked entries at a time.
The sixth entry once failed `merge_conflict` outside that build window and ejected everything
above it. Only five of twelve merged. An entry outside the window can read `UNMERGEABLE` with no
merge-group commit while its PR reads `CLEAN`. Judge its checks once it enters the window.

**Never, on a stacked branch:** `gh pr merge` (it merges a layer into its parent branch, leaving
its code off `main` even if tracker automation calls it finished), `gh pr update-branch`, a plain `git rebase origin/main`,
`--delete-branch`, or the server-side "Rebase stack" button, whose commits are unsigned. A pull
request whose base is another feature branch but is not in a native stack gets closed when its base
is deleted (#251 and #252); link it with `gh stack link` or do not create it.

For an independent pull request: confirm `CLEAN` and current-head checks, then remove any worktree
that holds the branch. Without a queue, `gh pr merge <n> --squash --delete-branch`; if it is behind,
`gh pr update-branch` and wait for the new run. With a queue, `gh pr merge <n> --squash` enqueues it
and nothing needs updating; once it shows `MERGED`, delete the local branch. The repository deletes
a merged head branch on GitHub by itself either way.

Use [`wait-merge.sh`](../scripts/wait-merge.sh) for an approved independent landing. Dry-run it
once with `WAIT_MERGE_DRY_RUN=1` and verify the fields. The waiter checks the current head, confirms
an enqueue by observing a real entry, retries if it is still absent and reports only state changes.
Its result is one of `MERGED`, `CLOSED`, `CI FAILURE`, `DIRTY` and `TIMEOUT`. Two consecutive
`DIRTY` observations on the same head rule out the transient result after a force-push. A silent
merge failure once looked queued, and a single transient `DIRTY` once stopped a waiter. After a
stack landing, check independent PRs touching shared story files for conflicts. One such PR sat
dirty for an hour before the waiter gained that terminal state.

## Parallel work

Read **AGENTS.md, "Parallel Work"** before starting a second builder, and hand its contention list
to every one.

- Pipeline a page layer's build on the lower hand-back only when its files are disjoint from the
  lower fix round. A concurrent build and local gate recreated load flakes. An approved
  critical-path exception can accept known overlap and a later restack. One dependency blocked
  seven of eleven next-slice issues, and starting early saved about two hours at a cost of
  about 45 minutes resolving eight source conflicts. Keep the dependency landing order so the
  upper layer restacks once.
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
- Record every CI flake and every "Passed only on retry" test before re-running or re-queuing, as
  **AGENTS.md, "Flaky tests"** says. Run `python3 -m unittest scripts.tests.test_flaky_tally` after
  changing the ledger. A malformed test or status cell broke its parser. In Storybook, read
  positions after layout settles with `settledLayout` or `settledRect`: three stories failed
  on transitional geometry in two days. Keep browser shards when changing story coverage.
  Chromium previously closed around story 842 of 846, and three fresh browser shards fixed
  the recurring queue failure.

## Delivery invariants

- Never edit a version field. The Release workflow owns them.
- Never resolve the built bundle textually; rebuild it from the sources.
- Never trust an exit status from `gh stack sync` as proof that it pushed.
- Never rewrite a branch (restack, rebase, amend, reset) while a suite or a review is running on
  it. The orchestrator once rewrote a branch while a builder's suite ran on it; a verdict reached
  that way describes a tree that is no longer there.
- Never widen an issue's scope to make it feel complete. File the rest in the selected tracker.
- Never promote a deferred review finding into the layer in flight when it costs another CI round.
