---
name: burndown
description: Use when burning down a milestone of the Compass Actions Front and Center project to completion, planning how to group and stack its issues, or closing out a single DRC issue.
---

# burndown

Take one milestone, group its issues by the functionality they change, build each group as a layer
of a GitHub stack or as an independent pull request, land them, reconcile every issue, and repeat
until the milestone is closed.

The project is Compass's roadmap in Linear (team `DRC`). Linear still names it **Cargento: Actions
Front and Center**, from before the product was renamed:
<https://linear.app/recce/project/cargento-actions-front-and-center-eed1852b11e6/overview>.
Invoke the required supporting skills inside the current workflow. Delegating work to a subagent is
normal here and is covered by the parallelism rules below.

This skill runs on its own. The Spacedock workflow in
[docs/roadmap-burndown/README.md](../../../docs/roadmap-burndown/README.md) is a second driver that
takes its pick order from this skill's step 2 plan. When a run is inside that workflow, its gates and
its stage `model:` fields govern, and step 2's model question is not asked.

## Invocation

- `burndown "<milestone name>"`: plan the milestone, ask the model questions with the plan, wait
  for approval, then build, land and reconcile until the milestone is complete or blocked.
- `burndown "<milestone name>" --plan`: print the plan, with its model recommendations, and stop.
  Write nothing to Linear or git.
- `burndown "<milestone name>" --merge`: the caller pre-approves the plan and its merges. Still
  print the plan before the first mutation, and still ask the model questions unless `--models`
  answers them.
- `burndown DRC-####`: work that one issue, inside its milestone's plan, as a group of one if it
  groups with nothing. The run ends once that group has landed and been reconciled. An issue with no
  milestone is planned as a milestone of one: no Verification issue, no milestone description.
- `--models recommended`, or `--models plan=<model>:<effort>,build=…,review=…`: answer step 2's
  model questions in the invocation. A stage the flag leaves out is still asked.

The milestone name is resolved against the project with the Linear milestone lookup. Do not hand a
milestone name to `linear-deep-dive`: its parser treats a string without a team prefix as a project
search.

Merging to `main` is what closes an issue, and this skill merges. The caller's approval of the plan
block in step 2 is the authorization for every merge in that plan, every repair the plan lists, and
the issue corrections and label writes step 3 makes to planned issues, and for nothing outside it.
Approval, and `--merge`, still cover the plan as recomputed when the only changes are discoveries
filed under step 7's **Discoveries** (a discovery is not "a new issue in product scope"), a small fix
riding an open layer, and issues moving later because of `blockedBy`. A new issue in product scope, a
changed review tier or a reordered stack needs a fresh yes, `--merge` or not. Neither approval nor
`--merge` lets the run answer a decision issue. The trunk is always `main`: never stack on, target
or promote a long-lived branch such as `feat/future-ui`.

## Prerequisites

- Linear read and write access to the `DRC` team: issues, relations, labels, milestones and the
  project overview.
- A `linear-deep-dive` skill. It ships as `recce-dev:linear-deep-dive` and as
  `anthropic-skills:linear-deep-dive`; use whichever is installed. Step 3 uses only its fetch,
  classification, exploration and approach proposal, so either copy serves.
- The `superpowers:test-driven-development`, `sync-docs`, `sync-project` and
  `visual-review-and-fix` skills.
- `gh` with the `github/gh-stack` extension at v0.3.0 or later (`gh extension list`;
  `gh extension upgrade gh-stack` when it lags upstream), able to push to `origin`, open and merge
  pull requests. Every worktree of this clone must use the same gh-stack version: they share one
  stack catalog in the git common directory.
- A Git checkout that can create worktrees, run the canonical pre-PR suite and make DCO-signed
  commits (`git commit -s`).
- A browser automation capability for the `visual-review-and-fix` walks. Its absence degrades the
  run rather than stopping it: say so, and name the walks that did not happen.
- A design-project read capability whenever an issue carries a `## Design reference` section. See
  [the design reference rules](references/design-reference.md).

If a required capability is missing, stop before the read or mutation that needs it.

## Stop, and when

Stop means: make no further mutation, say what has already been written to Linear and to git, name
every branch, worktree, stack, pull request, server and subagent this run started, then wait. It
does not mean switch to other work unless the step says so.

Stop and ask, in one block (what is waiting, the recommended answer, what yes does), when:

- an issue needs a decision, filed or not. File the decision issue in this milestone if nobody has,
  and link it as a blocker. This stops only that issue and its dependents: put the ruling request
  and any re-plan in one block, and once the re-plan is approved, continue the groups that do not
  depend on it;
- a design-project read is refused after the plan was approved (at planning time, step 2 leaves the
  issue out instead);
- a full-adversarial review returns NO-GO;
- a second correction round is wanted on a layer without a named user-visible regression it closes;
- CI is red twice on the same head after the suite was green locally;
- the plan must change beyond what the Invocation section says approval already covers;
- a stage keeps failing at its chosen model and effort (see step 2);
- the run passes its estimate by half.

Between landings, report measured state only: each pull request with its head SHA and check
conclusions, the Linear state of each issue read back, the receipts posted, and every worktree,
server and subagent still alive. Check background work in the same turn you report on it.

## 1. Load the milestone

Step 1 reads. It writes nothing to Linear or git: what it finds that needs a write goes into the plan
as a **repair**, done after approval and never under `--plan`.

1. Resolve the milestone. Fetch the project's issues ordered by `createdAt`, page until
   `hasNextPage` is false, and keep those whose `projectMilestone` is this one. The default
   `updatedAt` order shifts under your own writes.
2. Read the team's workflow states with their types once (the Linear status list). Classify issues
   by state **type**, never by name: `completed`, `canceled` and `duplicate` are finished, `triage`
   is not yet a candidate, everything else is open. The team's state names change over time, and
   more than one state can carry a type (`Done` and `Ready for Release` are both `completed`). The
   one exception is `Blocked`, which is a `started` state and can only be matched by name. When a
   step below moves an issue, it names a type; pick the team's state of that type, and `Todo` for
   "ready to start" since `Backlog` shares its `unstarted` type.
3. For every `completed` issue closed by a merge or a ruling, look for a step 6 receipt comment.
   Many issues closed before receipts were kept have none, so a missing receipt is not by itself an
   interrupted reconcile. List those whose milestone or project text still describes them as open
   or waiting (the reconcile visibly did not run) as repairs. A `canceled` or `duplicate` issue needs
   none.
4. Read the milestone description as a hint, not as state. `Read before building` (one milestone
   spells it `Read before merging`; treat it the same) carries contract notes keyed by issue ID,
   `Waits on` names outside blockers, and `Decide before building` names an open question. Check
   every issue ID it names against the live state, take blockers from `blockedBy` rather than from
   the prose, and list a description that has gone stale as a repair (a `sync-project` pass).
5. Scope is the milestone. An issue in the project with no milestone, or in another milestone, is
   out of scope even when it is unblocked.
6. An open issue in a `started` state other than `Blocked` may have work in flight. Find its branch
   (`gitBranchName`, `gh pr list --search DRC-####`, `git worktree list`) and its pull request. A
   partial issue whose `Part of` pull request merged can sit in `Ready for Review` with nothing in
   flight: treat it as open work with a landed part. When the pull request is open, plan it as that
   pull request or layer; never open a second one. When a worktree holds the branch, decide whether
   something live owns it (a running agent or session, a server, a lock) or whether it is an orphan
   from an earlier run: plan an orphan normally and adopt it, and leave a live one out of the plan
   and name it.
7. An issue in `Blocked` whose `blockedBy` holds no open issue is a reconcile that never ran: list
   moving it to `Todo` as a repair and plan it.

## 2. Plan: group, order, estimate, choose models

Read each open issue's `blockedBy`, labels, estimate and Scope (the files and views it names), and
whether it carries a `## Design reference`. Set the `Verification`-labelled issues aside; they run
last.

**Tag each issue:**

- Surface. The **web surface** is `frontend/`, the built `compass_runtime/web/` bundle, and
  everything `pnpm build` reads: `page.py`'s font table, the font rows of `styles.css` and the
  lockfile (**AGENTS.md, "Parallel Work"**). Otherwise: the shipped `SKILL.md`, `SECURITY.md` or
  `HOW_TO_USE.md`, `config.py`, or Python only.
- Review tier, from the table in **AGENTS.md, "Calibrating Effort"**: **self-verify** for a change
  with no user-visible behaviour change that nothing calls yet; **full adversarial** for the
  `Security` label, credential handling, data loss, or a change to a boundary `SECURITY.md` names
  (such as the history prompt-text allowlist); **two lenses plus an arbiter** otherwise.
- Estimate. Most issues carry none. Give an unestimated issue one on the team's scale (XS 1, S 2,
  M 3, L 5) from its Scope, mark it as yours in the plan, and write it back as a repair.
- Design reference. When the design-project read is unavailable, leave the issue out of the plan
  and say so, as [the design reference rules](references/design-reference.md#planning) direct.

**Group.** Issues share one pull request when all of these hold: they change the same view or the
same contract (the same NUI amendment, the same drift block, the same route); no issue outside the
group lies on a `blockedBy` path between two issues in it; they share a review tier; and their
estimates sum to no more than 7 points (L 5 plus S 2). A tier is the merge-risk unit; an issue stays
the reconcile unit. A self-verify issue groups only with other self-verify issues. Keep a
full-adversarial issue out of a group that would inflate its review with unrelated UI diff.

**Arrange.**

- Every group that touches the web surface becomes one layer of a single stack, in topological
  order of `blockedBy`. Exactly one stack whose layers touch the web surface may be in flight; a
  second web-surface group becomes a higher layer or waits. Layers are linear by construction, so
  each carries the built bundle for its own tree.
- A group that touches none of the web surface, `SKILL.md`, `config.py` or another in-flight group's
  files is an independent pull request on `main`, built in parallel.
- A group that touches `SKILL.md` or `config.py` but not the web surface is either a layer of the
  stack (when a web-surface layer depends on it) or a single pull request that waits until no other
  in-flight group touches that file. It is never built in parallel with one that does.
- Order by: an unblocked `Security`, Urgent or High priority group lands first. Off the web surface,
  it is its own pull request; on it, it is the bottom layer and the stack lands partially up to it
  (step 5). Then the longest estimate-weighted path to the Verification issues; then the smaller
  estimate. Any other full-adversarial group goes into the stack only when it touches the web
  surface or a web-surface layer depends on it, and then as high as its dependents allow, so the
  layers below can land without it.

**Verification issues.** With none in the milestone, say so in the plan and order by the longest
estimate-weighted `blockedBy` path instead. With several, all of them run last. One that waits on the
owner (its text says so, or it carries a ruling it cannot make) is not where discoveries hang their
`blocks` edge: name it in the plan as owner-gated.

**Estimate.** Give wall clock and tokens at full rigor and at calibrated rigor, from the measured
run in **AGENTS.md, "Calibrating Effort"**, at the recommended model settings below. Review dominates
CI here, but not by as much as it did: a `quality-gate` run took about seven minutes in October 2026
(`gh run list --workflow quality-gate.yml` gives today's figure).

**Choose a model and effort for each stage.** The work is dispatched to subagents in three stages, and
each stage runs at its own model and effort so a cheap stage is not paid for at the expensive one's
price:

| Stage | What the subagent does | Steps |
|---|---|---|
| Plan | the deep dive, the User value brief, a decision issue's recommendation | 3 |
| Build | the failing test, the code, the suite, `sync-docs`; after the walk and review, the fixes, the re-run and the bundle | 4.1, 4.2, 4.5, 4.6 |
| Review | the lenses and the arbiter at the group's tier | 4.4 |

The orchestrating session keeps steps 1, 2, 5, 6 and 7, step 3's Mode 1 walk, acceptance criteria
and tracker writes, step 4.3's Mode 2 walk, and a self-verify review, on its own model. Those are
reads, `gh` commands, tracker writes and the browser, and the walks cannot be delegated at all.

Recommend from the plan table you just built. That table is the light check: do not run a deep dive
or read code to decide.

| Stage | Default | Step up | Step down |
|---|---|---|---|
| Plan | Sonnet · medium | Opus · high when the group holds a decision issue, a `## Design reference`, a full-adversarial issue, or an issue citing a `DEC-*` or `NUI-*` ruling | Sonnet · low when every open issue is S or smaller and self-verify |
| Build | Sonnet · medium | Sonnet · high for a web-surface group of L or more, or one touching `config.py` or the shipped `SKILL.md`; Opus · high for a full-adversarial group | Haiku · medium for a self-verify group of XS or S that changes prose or tests only |
| Review | lenses Sonnet · medium, arbiter Sonnet · high | Opus · high for both on a full-adversarial group | none: a self-verify group has no reviewer subagent, and Haiku never reviews, because a false refutation or a false blocker costs a CI cycle |

A step-up or step-down applies to the groups that earn it, not the whole run, so the recommended
answer for a stage can be composite ("Sonnet · medium; Opus · high for G3"). Record each answer as
a rule keyed on the table's conditions (tier, size, surface), not on group names, so a group the
plan gains later (a discovery, a re-plan) takes its setting from the rule; ask again only when a new
group meets a step-up condition nobody answered. Never recommend `xhigh` or `max`, nor a model
outside these three, unless the caller asks for one.

Ask the three stage questions together with the plan, so the caller answers once: in Claude Code,
one structured question per stage, each offering the recommendation first and labelled
`(Recommended)`, then a uniform step down where the table has one (Review has none) and a uniform
step up, plus a fourth question for approving the plan when the run is waiting for that yes. Elsewhere ask in one plain-text block with the same
options. Skip a stage `--models` already answered. Under `--plan`, print the recommendations in the
plan block and ask nothing.

Every subagent dispatched for a stage gets the chosen model and effort; in Claude Code that is the
Agent tool's `model` and `effort`. A forked subagent ignores model and effort overrides, so do not
fork stage work. Work you do inline instead of dispatching runs on the session's own model whatever was chosen,
so dispatch it when the choice differs. In a harness with no per-subagent model choice, say so in
the plan block and ask about effort only. Never change a stage's setting on your own: when a stage
keeps failing at it (a review finds a defect the build should have caught on two layers, or a deep
dive the Mode 1 walk contradicts twice), stop and recommend the step up. When a step-up stage comes
back clean on every group, say so in the next report, so the next run can recommend lower.

**Print the plan** as one block: a table of groups (issues, surface, tier, estimate, stack position
or independent, base), the repairs, the issues left out and why, the order, the closing
`docs-synced-through` pull request step 7 opens, the estimate, and the model and effort per stage
with what each recommendation rests on. With `--plan`, stop here.
Otherwise wait for the caller's yes, unless they passed `--merge`, and for the model answers. Then
do the repairs, reading each write back.

## 3. Understand each issue in the group

**REQUIRED SUB-SKILL:** invoke `linear-deep-dive` for the issue, through its approach proposal and
no further. Dispatch it at the plan stage's model and effort. This skill owns everything after the
proposal: issue lifecycle, branches and merging.

- Stop at the start of its Propose Approach step and write the proposal yourself from its analysis.
  Do not run that step's interview of the user or its hand-off to a divergent-options skill: a
  subagent cannot interview anyone, and either stalls a `--merge` run. An open architectural
  question goes into the analysis; one that blocks the build becomes a decision issue under "Stop,
  and when". For the same reason, skip the `recce-dev` copy's question about how familiar the user is
  with the subsystem, and run its blind-spot pass at "read it" depth.
- Write its analysis to the session scratchpad, named by issue. Skip its write to `docs/plans/` and
  any edit it proposes to `.git/info/exclude`: a plan written there is not for this run, and a local
  exclude is invisible to everyone else. If `docs/plans/` is already excluded in this clone, say so
  in the report, because new plan files there no longer show in `git status`.
- Its branch handling creates branches from `main`, which is wrong for a stack layer. Ignore it.

If the issue has a `## Design reference`, load
[the design reference rules](references/design-reference.md) now, before the Mode 1 walk, and
never write its markup without having read what the section names.

Move the issue to a `started` state (`In Progress`) when you start it. Nothing else does, and an
issue left in `Backlog` is what lets a sibling agent pick it.

Read the milestone's `Read before building` bullets that name the issue, and any ruling the issue
cites (the `DEC-*` sections of `docs/design-reading-a-session.md`, the `NUI-*` sections of
`docs/design-next-ui.md`).

**REQUIRED SUB-SKILL:** invoke `visual-review-and-fix` in `Mode 1: before development` for every
issue and let its own calibration table decide how deep to go. The orchestrator runs this walk
itself, for delegated groups too, because only it has the browser. The acceptance criteria come out
of that walk rather than out of the issue text, because a criterion written from source can state
the wrong thing about what the reader is told. Anything it finds that predates the issue is filed.
If the walk contradicts the issue's plan, correct the issue before writing code; plan approval
covers that write.

If the issue carries no `journey:*` label, draft its User value brief before the walk: two
sentences, who notices and when, then the promise ID and the move from
[the development tracking taxonomy](../../../docs/development-tracking.md#how-work-links-to-a-promise). Set `journey:*` and
`move:*` to match. At least one acceptance criterion is a property a user can see, with its own
`Verified by:` clause; when the move is `none`, the brief says instead why no user sees the
change.

**A decision issue** has no build. Make the question answerable, recommend one answer, and stop for
the ruling, for that issue and its dependents only. It closes when the ruling is written into the
documents its acceptance criteria name, and that docs change is its layer.

## 4. Build a layer

In the layer's worktree. Items 1, 2, 5 and 6 are the build stage, 4 is the review stage, and 3 is the
orchestrator's. A build subagent stops after item 2 and hands back its worktree and review-server
port; after the review, dispatch a build-stage subagent into the same worktree for items 5 and 6.

1. **REQUIRED SUB-SKILL:** invoke `superpowers:test-driven-development`. Write the failing test first
   and watch it fail, then the code. A change to a component or view updates its story, and
   `pnpm test:stories` (in the suite) proves it. If the layer touches the web surface, run
   `pnpm build` before the suite: the suite includes `pnpm build:check`, which fails on a stale
   bundle, and the Mode 2 walk serves whatever `react.html` is in the worktree, so without the build
   it reviews the old page. Then run the canonical pre-PR suite from **AGENTS.md, "Pre-PR Checks"**,
   from there rather than from a copy. Give `scripts/run_tests.py` a `-j` share of the cores when
   another suite is running.
2. Invoke `sync-docs` in the layer that ships the behaviour, never once for the whole stack. The
   shipped `SKILL.md` and `HOW_TO_USE.md` change in the layer that ships what they describe. Never
   advance `COMPATIBILITY.md`'s `docs-synced-through` marker in a layer.
3. **REQUIRED SUB-SKILL:** the orchestrator invokes `visual-review-and-fix` in
   `Mode 2: after development`. What this layer introduced goes to item 5; what predates it is filed
   with the base comparison that proves so.
4. Review the layer at the depth its tier sets, before it is submitted. Reviewing an open pull
   request costs a second CI cycle. Self-verify is the orchestrator's own read of the diff and the
   checks; the other tiers are reviewer subagents at the review stage's model. Freeze the stack while
   a reviewer is reading: a restack rewrites the layers above under them and turns correct findings
   into false refutations. File what a review defers.
5. Fix what the walk and the review found. One correction round per layer is the default; after a
   round with several fixes, re-check against a live board, because fix rounds here produce about
   one new defect per four fixes. If `sync-docs`, the walk or a review changed a file, rebuild if the
   change touched the web surface, and run the suite again. `test_documentation` asserts
   `SKILL.md`, `SECURITY.md` and `README.md`.
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

Name a layer's branch without an issue key unless the layer finishes that issue: Linear links a
branch named from `gitBranchName` to its issue, and a merge of that branch can close it.

**Submit.** `gh stack submit --auto --open` opens a ready pull request for every layer that has
none, and there is no way to leave one out. Submit before you `gh stack add` the next, unreviewed
layer. Once a layer above is unreviewed, update the existing pull requests with `gh stack push` and
run `submit` again only when the top layer has been reviewed. Without `--open` new pull requests are
drafts, and a draft blocks the stack merge. `submit` writes the title and body only when it creates a
pull request, and its titles come from the branches, so then run
`gh pr edit <n> --title "<title>" --body-file <file>` for each layer, with scratch files named per
branch. The title follows **AGENTS.md, "PR Workflow"**: the shipped behaviour in a plain sentence,
ready for release notes, with no tracker brand, issue key or tracker URL (recent titles look like
"Find sessions: search and filter the Sessions page"). Each body carries:

- `Implements [DRC-####](<issue url>)`, one line per issue, **only on the layer that finishes the
  issue**. A layer that delivers part of an issue says `Part of [DRC-####](<issue url>)`, because
  Linear moves an issue to a `completed` state the moment any merged pull request says it implements
  it. Inside the Spacedock workflow, append ` — <issue title>` to the line, as its README asks.
- A `## Verification` section naming what ran and what it said.
- `Closes #NNNN` only for a real GitHub issue, one line each.

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

**Never, on a stacked branch:** `gh pr merge` (it merges a layer into its parent branch, which
Linear reads as done while the code is off `main`: measured, PR #178 into a feature branch moved
DRC-4219 to Done in three seconds), `gh pr update-branch`, a plain `git rebase origin/main`,
`--delete-branch`, or the server-side "Rebase stack" button, whose commits are unsigned. A pull
request whose base is another feature branch but is not in a native stack gets closed when its base
is deleted (#251 and #252); link it with `gh stack link` or do not create it.

For an independent pull request: confirm `CLEAN` and current-head checks, then
`gh pr merge <n> --squash --delete-branch`, after removing any worktree that holds the branch. The
repository deletes a merged head branch on GitHub by itself; `--delete-branch` also removes the
local one. If it is behind, `gh pr update-branch` and wait for the new run.

## 6. Reconcile every issue that landed

Only once the merge is confirmed on `origin/main`, and once per issue, in `blockedBy` order:

1. Confirm the issue is in a `completed` state and its change is on `origin/main`. Linear's
   automation usually got there first. An issue a `Part of` layer delivered only partly stays open:
   the automation leaves it in `Ready for Review` or `In Progress`. Move it back to `In Progress` if
   it was flipped to `completed` anyway, and reconcile it only when its finishing layer lands.
2. **REQUIRED SUB-SKILL:** invoke `sync-project` for the milestone and the project overview. Take
   the issue's `What is left` line out and correct anything the merge made false. Never write a
   dated "what shipped" section; the pull request holds that.
3. If the merge changed a contract a remaining item builds on, add one bullet under the milestone's
   `## Read before building`, as `- DRC-1234: the note`, on the milestone of the item that must
   read it. Delete a bullet once every issue it names is finished. `sync-project` preserves this
   section, but it rewrites from its template, so confirm the section survived step 2.
4. Check the issue's `blocks`. Move anything newly free to `Todo`, including out of `Blocked`.
5. Where the closed issue still blocks an open issue, replace the edge with `relatedTo`. Leave an
   edge between two closed issues alone: it records what waited on what.
6. If the move was `extend` or `new`, draft the promise wording change for `sync-docs` (the two
   repository copies) and `sync-project` (the Linear copy). For `keep` or `sharpen`, say no wording
   changes.

Post the receipt as a comment on the issue: all six items in order, "not applicable, because ..."
for any that did not apply, the pull request and the merge commit. A receipt names only its own
issue, because a comment naming another issue adds a `relatedTo` edge: report items 4 and 5 as
counts ("2 issues moved to Todo; 1 edge replaced with relatedTo"), and the relations panel holds the
names. Read the relations back after each write; Linear can echo a stale save and lag on the next
read.

## 7. Next landing, or close the milestone

Tear down what the landing finished, scoped to what this run started: its review servers, worktrees
(before their branches), and subagents. Keep the stack's worktree until the whole stack has merged.
Never bind, stop or kill a dashboard the run did not start.

Then refetch the milestone (issues move outside this session), recompute the plan, and continue. A
changed plan needs approval as the Invocation section sets out.

**Discoveries.** A defect this milestone's work created, or a gap a review deferred, is filed in
this milestone with a `blocks` edge to the Verification issue (not to an owner-gated one; with none,
no edge), and burned in this run. A small fix may ride the next open layer instead. A pre-existing
defect is filed in the project with no milestone and labelled `discovered-by-agent`, and the report
names it.

**The Verification issues run last,** once every other milestone issue is finished, on a live board
built from `origin/main`. Each closes on its verdict comment, since a clean walk has no pull request.
Each defect one finds is fixed or filed as above. An owner-gated one is handed to the owner, not
walked.

**The milestone is complete** when every issue's state type is `completed`, `canceled` or
`duplicate`, every issue this run closed has its receipt, and the Verification issues closed last.
Then invoke `sync-project` to rewrite the milestone to its three-line complete form and clear its
`Read before building` bullets. Then, from `main`, run `sync-docs` once to advance `COMPATIBILITY.md`'s
`docs-synced-through` marker over the range the milestone merged, as one docs-only pull request,
which **AGENTS.md, "Parallel Work"** reserves for after the merges. Report the issue count, pull
request count and date range.

**The milestone is blocked** when no open issue can start: name each blocker and stop.

## Parallel work

Read **AGENTS.md, "Parallel Work"** before starting a second builder, and hand its contention list
to every one.

- The web-surface stack is built serially in one worktree. Its layers depend on each other's trees.
- An independent group may run in its own worktree with its own subagent, its own review-server
  port, and a `-j` share of the cores. Its builder stops after step 4.2 and hands back; the
  orchestrator walks it, and a fresh build-stage subagent takes steps 4.5 and 4.6.
- Dispatch subagents from the repository root, at their stage's model and effort, and confirm each
  produced work before calling it running.
- A loopback-port failure under concurrent suites is contention, not a regression: rerun that module
  alone before believing it.

## Hard rules

- Never edit a version field. The Release workflow owns them.
- Never report an issue closed before its change is on `origin/main`, except a Verification issue,
  which closes on its verdict.
- Never merge a stack layer on its own with `gh pr merge`; land stacks with `gh stack merge --squash`.
- Never resolve the built bundle textually; rebuild it from the sources.
- Never trust one page of Linear issues, or a state name instead of a state type. The exceptions are
  `Blocked`, which only a name can pick out, and `Todo`, the ready state among the `unstarted` ones;
  `In Progress` and `Ready for Review` above are examples of `started` states.
- Never trust an exit status from `gh stack sync` as proof that it pushed.
- Never widen an issue's scope to make it feel complete. File the rest.
- Never promote a deferred review finding into the layer in flight when it costs another CI round.

## Why step 6 is written the way it is

Roadmap work here has repeatedly desynced when closing an issue felt like finishing: a milestone
claiming nothing had shipped after two of its items had, an item held behind a decision it no longer
needed, and a closed decision still holding a `blocks` edge on live work (PR #128's reconcile). Six
closed-to-closed edges found by the audit in PR #147 are why item 5 leaves those alone. Each was one
edit away from right. The receipt exists so an interrupted reconcile is visible to the next run.
