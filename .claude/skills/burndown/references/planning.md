# Plan and understand the work

Read this after selecting a tracker and loading its adapter. Steps 1–2 are read-only. Under
`--plan`, stop after step 2; do not run deep dives, browser walks or tracker repairs.

## 1. Load the milestone

Use the selected adapter's **Load** section to enumerate the complete scope, classify live states,
read dependencies and find work already in flight. Page every collection to exhaustion. A link in
an issue body is context, not scope membership. Keep external blockers visible without adding them
to the work list.

Record stale descriptions, incomplete reconciliations and metadata changes as **repairs**. Execute
them only after the plan is approved, never under `--plan`. Report unavailable reads rather than
inventing an empty result.

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
- Estimate. Most issues carry none. Use XS 1, S 2, M 3, L 5, mark an inferred estimate as yours,
  and let the adapter decide whether an approved repair can write it back. GitHub issues have no
  native estimate field; a plan estimate does not authorize creating a custom field or label.
- Design reference. When the design-project read is unavailable, leave the issue out of the plan
  and say so, as [the design reference rules](design-reference.md#planning) direct.

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
or read code to decide. The model families below are Claude Code defaults. Before recommending
names, inspect the current harness's available models and efforts. Where those families are not
available, recommend available equivalents for the same stage and risk tier, explaining the
mapping. `--models recommended` selects these available recommendations, not unavailable names.

| Stage | Default | Step up | Step down |
|---|---|---|---|
| Plan | Sonnet · medium | Opus · high when the group holds a decision issue, a `## Design reference`, a full-adversarial issue, or an issue citing a `DEC-*` or `NUI-*` ruling | Sonnet · low when every open issue is S or smaller and self-verify |
| Build | Sonnet · medium | Sonnet · high for a web-surface group of L or more, or one touching `config.py` or the shipped `SKILL.md`; Opus · high for a full-adversarial group | Haiku · medium for a self-verify group of XS or S that changes prose or tests only |
| Review | lenses Sonnet · medium, arbiter Sonnet · high | Opus · high for both on a full-adversarial group | none: a self-verify group has no reviewer subagent, and Haiku never reviews, because a false refutation or a false blocker costs a CI cycle |

A step-up or step-down applies to the groups that earn it, not the whole run, so the recommended
answer for a stage can be composite ("Sonnet · medium; Opus · high for G3"). Record each answer as
a rule keyed on the table's conditions (tier, size, surface), not on group names, so a group the
plan gains later (a discovery, a re-plan) takes its setting from the rule; ask again only when a new
group meets a step-up condition nobody answered. Never recommend `xhigh` or `max` unless the
caller asks for one. On Claude Code, stay within the three families above unless asked otherwise.

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

Use the selected adapter's **Understand** section for the issue's deep dive, at the plan stage's
model and effort. This workflow owns issue lifecycle, branches and merging. The result is a
scratchpad analysis named by canonical issue identity: classification, relevant code and contracts,
existing behavior, gaps, blockers and a concrete approach. Skip an interview or a branch/plan-file
hand-off from a supporting skill. An unresolved architectural choice becomes a decision issue.

If the issue has a `## Design reference`, load
[the design reference rules](design-reference.md) now, before the Mode 1 walk, and
never write its markup without having read what the section names.

Record that work has started using the adapter's lifecycle rule. A GitHub issue remains open;
`started` is not a GitHub issue state.

Read the adapter's contract notes that name the issue, including its container's maintained notes,
and any ruling the issue cites (the `DEC-*` sections of `docs/design-reading-a-session.md`, the `NUI-*` sections of
`docs/design-next-ui.md`).

**REQUIRED SUB-SKILL:** invoke `visual-review-and-fix` in `Mode 1: before development` for every
issue and let its own calibration table decide how deep to go. The orchestrator runs this walk
itself, for delegated groups too, because only it has the browser. The acceptance criteria come out
of that walk rather than out of the issue text, because a criterion written from source can state
the wrong thing about what the reader is told. Anything it finds that predates the issue is filed.
If the walk contradicts the issue's plan, correct the issue before writing code; plan approval
covers that write.

Draft a missing User value brief before the walk: two sentences, who notices and when. Use
[the development tracking taxonomy](../../../../docs/development-tracking.md#how-work-links-to-a-promise)
for the promise and move, and the adapter's metadata rules for any write. Public GitHub issues use
public promise wording; do not copy internal tracker provenance or manufacture labels. At least
one acceptance criterion is a property a user can see, with its own
`Verified by:` clause; when the move is `none`, the brief says instead why no user sees the
change.

**A decision issue** has no build. Make the question answerable, recommend one answer, and stop for
the ruling, for that issue and its dependents only. It closes when the ruling is written into the
documents its acceptance criteria name, and that docs change is its layer. When the owner delegates
a ruling ("choose what is best for the reader"), record their words with the ruling.

**A research issue** (its scope is to find something out, and it names no change) has no layer
either. Dispatch the research at the build stage's setting, verify its main claim yourself, and
close the issue on a findings comment; its receipt says there was no pull request. File what the
findings call for as new issues rather than building it under the research issue.

Next: after plan approval and issue understanding, read [delivery](delivery.md) for steps 4–5.
