---
name: burndown
description: Use when burning down a Compass GitHub issue with sub-issues, a GitHub or Linear milestone, or a single issue; also when planning how to group and stack that work.
---

# burndown

Plan a bounded work scope, group its issues, build and review stacked or independent PRs, land
them on `main`, and reconcile every issue. One delivery workflow serves both trackers; the
selected adapter owns tracker reads and writes. Keep work in its source tracker.

## Select the tracker and scope

Resolve the target before checking tracker-specific prerequisites:

| Input | Route |
|---|---|
| `https://github.com/OWNER/REPO/issues/N` or `OWNER/REPO#N` | GitHub issue; with native children, a parent-tree scope; otherwise one issue |
| `https://github.com/OWNER/REPO/milestone/N` | GitHub milestone |
| `#N` or a bare number | GitHub issue only when `--repo` or an unambiguous repository context identifies the repository |
| `https://linear.app/.../issue/...` or an issue key such as `DRC-1234` | Linear issue |
| Linear project/milestone URL | Linear; a project alone still needs a milestone selection |
| Milestone name | Use an explicit tracker, the tracker already established in this conversation/workflow, or ask which tracker |

`--tracker github|linear` supplies missing tracker context; `--repo OWNER/REPO` selects GitHub;
`--project "<name>"` selects Linear. A flag conflicting with a URL/key, or `--repo` combined
with `--project`, needs clarification before tracker calls. A bare number is an issue number,
not a milestone ID.

Infer a missing GitHub repository only from an established repository context or an unambiguous
GitHub `origin`. Confirm the target repository against the checkout before building. Ask about
ambiguous repositories, unsupported hosts and target shapes. A failed lookup or denied read does
not identify a different tracker: never fall back silently to Linear.

Load **one** adapter: [GitHub](references/github.md) or [Linear](references/linear.md). Record
the tracker, canonical target, repository/project and exact scope in the plan. A cross-tracker
link can supply context or an external blocker; it authorizes neither mirroring nor writes to the
other tracker.

## Invocation

- `burndown <target>`: plan, present model recommendations, wait for plan/model approval, then
  build, land and reconcile until complete or blocked.
- `--plan`: read and print the plan, then stop. No tracker/git writes, claims, label repairs,
  deep dives, builds or model dispatches. Read access alone suffices.
- `--merge`: pre-approve the printed plan and its merges. Still print it before mutation; ask
  model questions unless `--models` answers them.
- `--models recommended`, or `--models plan=<model>:<effort>,build=…,review=…`: answer the
  shared planning stage's model questions. Ask only for stages not answered.
- A milestone name uses the selected tracker's project/repository. The Linear adapter retains
  Compass in the Terminal as its default project after Linear has been selected.

Examples:

```text
burndown https://github.com/spacedock-dev/compass/issues/758 --plan
burndown spacedock-dev/compass#758 --merge --models recommended
burndown https://github.com/spacedock-dev/compass/milestone/4 --plan
burndown DRC-1234 --plan
burndown "Long session coverage" --tracker github --repo spacedock-dev/compass --plan
```

## Load only the current stage

| When | Read | Owns |
|---|---|---|
| Planning and issue understanding | [Planning, steps 1–3](references/planning.md) | Scope inventory, grouping, dependencies, estimates, review tiers, stage models and issue analysis |
| An approved group is ready to build | [Delivery, steps 4–5](references/delivery.md) | TDD, visual walks, reviews, stacks, CI, merges and parallel-work rules |
| After each landing and at closeout | [Reconciliation, steps 6–7](references/reconciliation.md) | Receipts, discoveries, cleanup, replanning and completion |
| An issue has `## Design reference` | [Design-reference rules](references/design-reference.md) | Required design reads and markup constraints |

Read only the selected adapter and the current stage; revisit the next stage when reached. Do not
preload all references. Here, “milestone” in the shared stages means the selected scope, including
a GitHub parent tree or one issue. “Container” means its milestone or parent issue, if any.
`blockedBy`, `blocks`, ready, started and finished are concepts mapped by the adapter, not
assumed API fields or GitHub states. File discoveries and decision issues in the selected tracker.

## Authorization and stop rules

Plan approval authorizes its merges, listed repairs and planned issue corrections/labels. Approval
and `--merge` also cover discoveries caused by this work within the estimate, a small fix riding
an open layer, and issues moving later because of blockers. New product scope, a changed review
tier or a reordered stack needs fresh approval. Neither approval nor `--merge` answers a decision
issue or authorizes committing/pushing to another author's PR branch.

During execution, file a missing decision issue in the selected scope, link it as a native blocker
of affected issues and recommend an answer before stopping for the owner ruling. Under `--plan`,
list those writes as repairs instead. Continue independent groups only under an approved replan.
Stop and ask when a design read is refused after approval, full-adversarial review says
NO-GO, a second correction round lacks a named user-visible regression, CI is red twice on the same
head after local green, the plan changes beyond its authorization, a chosen stage model repeatedly
fails, or the run exceeds its estimate by half.

On stopping, report written tracker/git changes and every branch, worktree, stack, PR, server and
subagent this run started. Between landings, report current-head checks, read-back issue states,
receipts and live background work. Stop before an operation whose required capability is missing.

## Shared prerequisites and boundaries

Execution needs TDD, `sync-docs`, `visual-review-and-fix`, DCO commits and the canonical
**AGENTS.md, “Pre-PR Checks”** suite. Stacked delivery needs `gh-stack` v0.3.0 or later, the same
version across worktrees. Missing browser automation degrades the walks: report which did not run.
The real-session check needs a logged-in `claude` on PATH; without one, say so in the pull request
rather than skipping it silently. Design access is required only for issues carrying a design
reference. Linear-only prerequisites live in its adapter; GitHub planning must not depend on them.

The trunk is `main`. Code issues finish only when their change reaches `origin/main`; research
and Verification issues may finish on their verified findings/verdict. Use native stack merges
with `--squash`, rebuild generated bundles from sources and leave version fields to releases.

The [Spacedock roadmap driver](../../../docs/roadmap-burndown/README.md) remains Linear-specific.
Inside that workflow its gates and stage `model:` fields govern; skip the shared model questions.
A standalone GitHub run uses this skill's stages, not that driver's Linear reconciliation.
