# Linear adapter

Load this only after the entrypoint resolves Linear. The shared planning, delivery and
reconciliation stages remain in force.

## Prerequisites and defaults

Require Linear read access to issues, relations, labels, milestones, workflow states and project
overview. Execution also needs the corresponding writes, `sync-project`, and a
`linear-deep-dive` skill (`recce-dev:linear-deep-dive` or
`anthropic-skills:linear-deep-dive`). GitHub runs require none of these Linear capabilities.

The default project is **Cargento: Compass in the Terminal** (team `DRC`):
<https://linear.app/recce/project/cargento-compass-in-the-terminal-404cbf9cbce6/overview>.
The earlier **Cargento: Actions Front and Center** project is complete:
<https://linear.app/recce/project/cargento-actions-front-and-center-eed1852b11e6/overview>.
Use `--project` to choose another named project. A milestone name present in both is ambiguous:
ask which project. An issue identifies its own project and ignores `--project`.

Resolve a milestone name with the milestone lookup against the chosen project, never with
`linear-deep-dive`: that skill treats a name without a team prefix as a project search. A project
URL alone selects the project, not a milestone. Ask which milestone to work.

## Load

Step 1 reads. It writes nothing to Linear or git: what it finds that needs a write goes into the plan
as a **repair**, done after approval and never under `--plan`.

1. Resolve the milestone. Fetch the chosen project's issues ordered by `createdAt`, page until
   `hasNextPage` is false, and keep those whose `projectMilestone` is this one. The default
   `updatedAt` order shifts under your own writes.
2. Read the team's workflow states with their types once (the Linear status list). Classify issues
   by state **type**, never by name: `completed`, `canceled` and `duplicate` are finished, `triage`
   is not yet a candidate, everything else is open. The team's state names change over time, and
   more than one state can carry a type (`Done` and `Ready for Release` are both `completed`). The
   one exception is `Blocked`, which is a `started` state and can only be matched by name. When a
   step below moves an issue, it names a type; pick the team's state of that type. "Ready to start"
   is `Todo`, the team's `unstarted` state; `Backlog` is a separate `backlog` type and is not ready.
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

A single issue is understood in its milestone's plan, grouping with related work when the shared
rules warrant it; stop once that group has landed and been reconciled. An issue with no milestone
is a scope of one: no Verification issue and no milestone description.

## Understand

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

At work start, move the issue to a `started` state (`In Progress`). The ready state is `Todo`;
`Backlog` is not ready. Read the milestone's contract notes and linked rulings.

For a missing User value brief, use the shared planning recipe. Set `journey:*` and `move:*`
from [the development taxonomy](../../../../docs/development-tracking.md#how-work-links-to-a-promise).
Write inferred estimates back on the team's XS 1, S 2, M 3, L 5 scale as approved repairs.

## PR links

Name a layer's branch without an issue key unless it finishes that issue. Linear links a branch
named from `gitBranchName`, and merging that branch can close its issue.

Use `Implements [DRC-####](<issue url>)`, one line per issue, only on the layer that finishes it.
A partial layer uses `Part of [DRC-####](<issue url>)`. Linear can move an issue to completed
as soon as any linked PR merges, so completion still requires the shared `origin/main` check.
Inside the Linear Spacedock workflow, append ` — <issue title>` as its README requires.
`Closes #NNNN` is reserved for actual GitHub issues.

## Reconcile

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

## Discoveries

A discovery caused by this work belongs in the selected milestone. Give it a `blocks` edge to
a non-owner-gated Verification issue when one exists. A pre-existing defect belongs in the project
with no milestone and the `discovered-by-agent` label. These are the shared discovery categories;
the run's estimate and scope-approval limits still apply.

## Finish

A milestone is complete when every issue has state type `completed`, `canceled` or `duplicate`,
this run's closed issues have receipts and Verification issues closed last. Invoke `sync-project`
to rewrite it to the three-line complete form and clear its `Read before building` bullets, then
follow the shared docs-marker closeout. A single-issue run ends after its group is reconciled;
it does not close the containing milestone or claim that milestone's other work.

## Why these reconciliation edits exist

Roadmap work repeatedly desynced when closing an issue felt like finishing: a milestone still
claiming nothing shipped, an item held behind a resolved decision and a closed decision blocking
live work. The receipt makes an interrupted reconcile visible. Leave closed-to-closed edges alone:
they record what waited on what.
