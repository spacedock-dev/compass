---
commissioned-by: spacedock@0.27.1
entity-type: roadmap_issue
entity-label: issue
entity-label-plural: issues
id-style: slug
state: .spacedock-state
stages:
  defaults:
    worktree: false
    concurrency: 2
    model: sonnet
  states:
    - name: selection
      initial: true
      model: haiku
    - name: triage
      gate: true
      model: opus
      concurrency: 8
    - name: implementation
      worktree: true
      model: opus
      context-sections:
        - Review-finding disposition
    - name: review
      worktree: true
      fresh: true
      model: opus
      feedback-to: implementation
      gate: true
      context-sections:
        - Review-finding disposition
    - name: done
      terminal: true
    - name: recorded
  transitions:
    - from: selection
      to: triage
      label: picked
    - from: triage
      to: implementation
      label: drafts approved at the gate
    - from: implementation
      to: review
      label: PR opened
    - from: implementation
      to: recorded
      label: no delivery — the cycle's product was a Linear record change, not code
    - from: review
      to: done
      label: merged
---

# Burn down the Compass roadmap

One roadmap issue at a time, from picked to merged, with the Linear records left true afterwards.

The default project is **Cargento: Compass in the Terminal** in Linear (team `DRC`):
<https://linear.app/recce/project/cargento-compass-in-the-terminal-404cbf9cbce6/overview>. The
earlier project, **Cargento: Actions Front and Center**
(<https://linear.app/recce/project/cargento-actions-front-and-center-eed1852b11e6/overview>), is
complete, and a milestone may belong to either. Each issue on the chosen board is one entity here.
The workflow runs until the board is empty.

This workflow does not invent its own picking rules, its own build discipline, or its own
reconcile list. Those already exist and are owned elsewhere: the `burndown` skill owns planning and
reconciling, `recce-dev:linear-deep-dive` owns issue analysis, `superpowers:test-driven-development`
owns the build, and **AGENTS.md, "Pre-PR Checks"** owns the gate. What this workflow adds is the
part none of them own — a durable place for one issue's journey to sit between sessions, an
adversarial pass over the issue text itself before anyone builds against it, and a review whose
depth is chosen rather than assumed.

## Why the issue text gets reviewed before the code does

This board has been running long enough that its issues have accumulated history: approaches that
were tried and abandoned, scores from a panel that has since been re-run, decisions recorded in
prose that a `blockedBy` edge still contradicts. An agent handed a stale issue builds the stale
thing, confidently, and every check downstream passes because nothing downstream reads the issue.

So `triage` is a real stage with a real gate, not a formality. It is the only point where the
thing being built is compared against what the project currently wants.

## File Naming

Each issue lives as a flat markdown file named for its Linear identifier: `drc-4029.md`. Use the
folder form `drc-4029/index.md` only when an issue produces sibling artifacts (a capture, a
transcript, a comparison table) that belong beside the tracker.

The slug is the identity. Linear already assigns these numbers and is the single writer of them,
so this workflow does not mint IDs of its own — a generated ID would be a second counter competing
with the one that already exists.

## Schema

Every issue file has YAML frontmatter. Fields are documented below; see **Issue Template** for a
copy-paste starter.

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Optional. `id-style: slug` means the filename slug (`drc-4029`) is the effective ID. |
| `title` | string | The Linear issue title, verbatim. Changed here only when it is changed in Linear. |
| `status` | enum | One of: selection, triage, implementation, review, done, recorded. `done` is terminal; `recorded` is parked. |
| `source` | string | Always the Linear issue URL. This is the record of where the truth lives. |
| `started` | ISO 8601 | When active work began |
| `completed` | ISO 8601 | When the issue reached terminal status |
| `verdict` | enum | PASSED or REJECTED — set at review. Left **empty** on an entity that parks at `recorded`: a cycle whose product was a Linear record change was neither delivered nor rejected, and stamping either would be a false record. |
| `score` | number | Release-row weight, 0.0–1.0. A sort hint, **not** the pick order — see **Scoring**. |
| `worktree` | string | Worktree path while a dispatched agent is active, empty otherwise. Set on first dispatch into a worktree stage, sticky across non-terminal advancement, cleared at terminal merge. |
| `issue` | string | GitHub issue reference, only when a mirrored GitHub issue actually exists. Usually empty. |
| `pr` | string | GitHub PR reference (e.g. `#57`). Set by the `pr-merge` mod when the PR opens. |
| `mod-block` | string | Pending mod-declared blocking action, format `{lifecycle_point}:{mod_name}` |
| `linear-status` | string | The Linear state as last observed (`Backlog`, `Todo`, `In Progress`, `Ready for Review`, `Blocked`, `Done`). A cache for selection, never authority. |
| `milestone` | string | The owning Linear milestone name, or empty. The milestone `triage` reviews and `done` reconciles. |
| `release` | string | The `release:*` label row: `r1`, `r2`, `r3`, `later`, or empty. Kept for the `score` below. |
| `promise` | string | The promise ID from the `journey:*` label, `P1` to `P5`, or empty. Cached at `selection`; the label is authority. |
| `move` | enum | The `move:*` label: `keep`, `sharpen`, `extend`, `new`, `none`, or empty when not yet labelled. Empty means triage has not labelled it. |
| `estimate` | string | The Linear estimate (`XS`/`S`/`M`/`L`/`XL`), or empty. |
| `reconciled` | ISO 8601 | When the post-merge Linear reconcile completed. Written and committed **before** `merge guard` terminalizes. Empty on an archived entity with `pr` set means the reconcile was interrupted. |

### ID Style

`id-style: slug`. The `id` field is optional and left blank; the effective ID is the slug, which is
the lowercased Linear identifier. `status --next-id` is not applicable.

```yaml
id-style: slug
```

## Scoring

`score` is the release-row weight and nothing more: `r1` 0.9, `r2` 0.7, `r3` 0.5, `later` 0.2,
unlabeled 0.6. It exists so `spacedock status` sorts into something readable.

**It is not the pick order.** `selection` takes the next issue in the `burndown` skill's approved
plan (its step 2): `blockedBy` order, then priority, then the estimate-weighted path to the
Verification issue. No single float can encode that, and a float that appeared to would be a
confidently wrong number, of exactly the kind this project has been burned by before. When the plan
and this number disagree, the plan wins and the number is stale.

Unlabeled issues sit at 0.6 rather than 0 because a probe or a bug carries no `release:*` label and
ranks on what it settles, not on a label it was never given.

## Stages

**Model routing.** Each stage names the model its ensign runs on, so the First Officer's own model, which is the session's and is often Fable, is not inherited by every worker. The default is Sonnet. `selection` picks from a board and runs on Haiku. `triage`, `implementation` and `review` carry the reasoning and run on Opus. A model change between stages forces a fresh dispatch at that boundary, because a reused worker must match the next stage's model; `review` is already `fresh: true`, so only the `selection` to `triage` and `triage` to `implementation` boundaries pay it. Values come from Spacedock's Claude-host enum (`sonnet`, `opus`, `haiku`, `fable`); other hosts ignore the field.

### `selection`

An issue sits in `selection` when it is on the board and has not yet been picked. The stage's work
is choosing which one leaves, and reconciling the board against Linear before choosing.

- **Inputs:** A live Linear fetch of the project's issues, their states, labels, estimates,
  milestones and `blockedBy` relations. The `burndown` skill's approved plan. The existing entity
  files. `docs/visibility-2x2/items.json` for panel scores **only** — its `state` fields are
  deliberately stale and are the dated record of what was scored, never what shipped.
- **Outputs:**
  - **Before anything else:** any **non-archived** entity with `pr` set and `reconciled` empty is an
    interrupted post-merge reconcile. Finish it before picking. An issue whose code merged but whose
    Linear record still reads open is otherwise picked a second time and rebuilt.
  - **An *archived* entity in that shape cannot be repaired at all** — `status --set` refuses an
    archived entity as read-only, so `reconciled` has exactly one window and `merge guard` closes it
    permanently. Do not try to stamp it. Confirm the reconcile happened by reading the **receipt
    comment on the Linear issue**, which is why `done` requires one, and move on. Measured 2026-08-28
    on `drc-4274`, the first entity this workflow merged: its reconcile ran correctly but *after* the
    guard, so it is archived unstamped and its receipt is the proof. A known false positive of this
    query, not an outstanding task.
  - Board reconciled next, before any pick: an entity created for every open project issue that
    has none, and any entity whose Linear issue is now `Done` or `Canceled` noted as closed outside
    this workflow. A pick made against a stale board is a pick of the wrong thing.
  - An entity already parked at `recorded` is handled by reading its Linear state, per the table in
    that stage — left alone while `Blocked`, noted while `Done`, moved back here once open and free. When that
    blocker closes, the issue leaves `Blocked` in Linear and the entity becomes an ordinary
    candidate again with no special handling — move it back to `selection` at that point rather
    than filing a second entity for the same issue.
  - `linear-status`, `release`, `estimate`, `milestone`, `promise` and `move` refreshed on the
    surviving entities from the fetch, so the cached fields are not lying to the next stage.
  - The pick and its reasoning stated in **one line** before anything is touched, naming which rule
    decided it.
  - Every candidate dropped for an open blocker named, with the blocker. A decision issue that is
    not `Done` is an open blocker even when its body records the call — check `blockedBy`, not prose.
  - Exactly one issue advanced to `triage`.
  - When no candidate survives the rules, say which of the two endings it is: **board empty** (every
    project issue `Done` or `Canceled` — report the burndown complete, with the count worked and the
    date range) or **board blocked** (candidates remain but every one is held by an open blocker —
    name each blocker and what it gates, because that is a decision backlog, not a finish). Silence
    is not a valid ending; a stalled loop and a finished one look identical from outside.
  - An entity unpickable by state rather than by rank — `Blocked` in Linear, or already `Ready for
    Review` — is reported once per cycle in a single line and not re-reasoned. Re-deriving the same
    "not eligible" every cycle is noise that hides a real change of state when one happens.
- **Good:** The reasoning is falsifiable — it names the rule and the losing candidate, so a reader
  can disagree with a specific step. Promotion out of a later release row happens only when
  something the promoted item gates sits in the row being worked, and says which item that is.
- **Bad:** Picking from the entity files without re-fetching Linear, because issues move outside
  this session. Reading `items.json` for what has shipped. Treating a decision issue's recorded
  prose as settling the gate its `blockedBy` edge still holds. Advancing more than one issue at a
  time without having read **Parallel Work** in `AGENTS.md` first.

### `triage`

The picked issue is adversarially reviewed — the issue and its owning milestone both — and a rewrite
is drafted so that what they say is what the project currently wants. The drafts stay in this entity
until the gate approves them; `implementation` writes them to Linear as its first action. This is
the only stage whose product is a change to the roadmap records rather than to the code.

- **Inputs:** The live Linear issue body, its comments, its relations, its labels; the owning
  milestone's description; the project overview's "As of" block; the repository as it stands today.
- **Outputs:**
  - An adversarial read of the issue against the current codebase, answering: is the problem still
    real, is the described approach still the one that fits, does any part of the body describe a
    state that no longer exists?
  - The original issue body and the owning milestone description copied **verbatim** into this
    entity under `## Linear edits made`, before anything else, as the pre-edit record.
  - The issue's **User value** brief drafted as the first section of the rewrite: two sentences,
    who notices this and when in their day, then the promise ID and the move, in the vocabulary of
    [the development tracking taxonomy](../development-tracking.md#how-work-links-to-a-promise). For a decision issue, the
    promise the ruling unblocks or forecloses.
  - The `journey:*` and `move:*` labels to set, named here and written by `implementation` with
    the rewrite. Until they are set the issue ranks as `none` at `selection`.
  - The rewritten issue body **drafted into this entity, not written to Linear.** Superseded content
    is **demoted to a dated historical section, not deleted** — the record of what was believed and
    when is what makes a later reader able to trust the rest.
  - The corrected milestone description drafted the same way, wherever the issue's rewrite made the
    existing one false.
  - Acceptance criteria written into this entity as end-state properties with `Verified by:`
    clauses, each split as **offline** (a test, command, or on-disk state a fresh agent reproduces)
    or **interactive** (needs a human or a live drive). The split is declared here, at the gate, so
    a plan to build a harness that automates an interactive AC is visible before the harness exists.
    **The heading is exactly `## Acceptance criteria`, and that is machine-read rather than
    stylistic.** `status --read {slug} --ac-scan` matches that string literally: `## Acceptance`
    and `## Acceptance criteria, with verification` both return `Error: no ## Acceptance criteria
    section in this file`, which leaves the triage gate and every later review gate without their
    structured acceptance read — and the error appears only when the FO runs the read, not when
    the criteria are written. Measured 2026-09-17 on DRC-4587 and DRC-4588, which drew the heading
    from the Linear issue's own `## Acceptance` section and each cost a repair round. The captured
    original under `## Linear edits made` keeps whatever heading Linear holds: it is a verbatim
    record, so it is exempt, and renaming it would falsify the restore point.
    **Two further things must hold, and both fail silently.** The heading alone is not enough: a
    correct heading over criteria the scanner cannot see returns `{"acs":[]}`, which reads as "this
    entity has no acceptance criteria" rather than as an error. Worse, a criterion list where only
    some items parse returns a partial scan that looks like a complete one.

    1. **The id is hyphenated** — `AC-1`, never `AC1`.
    2. **The bold label opens and closes on the same line.** A label whose bold run wraps before
       its closing marker is skipped, so in a hard-wrapped file a long property silently drops its
       own criterion.

    Write the bullet form, which satisfies both by construction — the bold closes right after the
    mark, so the property may wrap freely:

    ```text
    - **AC-1 — offline:** {end-state property, wraps freely}. **Verified by:** {command, test or
      on-disk state, and what it returns today}. **Falsified by:** {the change that flips it}.
    ```

    Measured 2026-09-17 in an isolated throwaway workflow, one file per run: unhyphenated `AC4` is
    skipped; a bold label wrapped across a newline is skipped; a bullet whose bold closes after the
    mark parses however far the property wraps. The live cost was three repair rounds across
    DRC-4587 and DRC-4588, two of them spent on first officer guesses — the heading, then a
    supposedly-required bullet list — made before anything was measured. The partial-scan state was
    found by the DRC-4587 ensign, whose paragraph rewrite resolved exactly one of seven criteria:
    the only one short enough to close its bold on a single line. **Probe shapes in a throwaway
    workflow, never in the state checkout**, which has concurrent writers.

    Citations resolve from later stage reports that name `AC-N`, so criteria authored here are
    expected to scan as unevidenced at this gate. That is correct, not a defect — `implementation`
    and `review` supply the evidence, and the cross-check earns its keep at the review gate.
  - At least one acceptance criterion that is a property a user can see, with its own `Verified
    by:` clause. When the move is `none`, one sentence in the brief on why no user sees this
    change instead, and the gate is told so up front.
  - An expected surface estimate with tolerance, and the semantics the change may move. **Cost the
    oracles separately from the runtime, and check whether any existing required check compels a new
    test file before declaring** — an import-graph allowlist that rejects a new module, a protocol
    fake that must be satisfied, a documentation drift-guard. Measured on DRC-4037's PR 1, where the
    runtime landed at exactly the declared figure across exactly the declared files while tests came
    in at 9 files and +541 against 6 declared, three of them compelled rather than chosen. The
    estimate was not wrong about the work; it was wrong about what the repository's own contracts
    would demand of it. An overrun of that shape is accepted once — if a later one repeats it, fix
    the estimating method rather than stretching the tolerance again.
- **Good:** The rewrite is shorter than what it replaced and a stranger could build from it. The
  historical section is dated and labelled as history. Every claim about the current code was
  checked against the code rather than against the issue's own prose.
- **Bad:** Deleting history instead of dating it. Widening scope to make the issue feel complete —
  the board's estimates assume the narrow reading. Writing acceptance criteria whose only proof is
  a review of this entity's own prose. Proceeding when the issue turns out to need a product
  decision nobody has filed: file the decision issue, link it as a blocker, and send this back to
  `selection` instead of guessing. Writing the rewrite to Linear before the gate approves it — the
  issue and its milestone are records other people read, so an unapproved rewrite sitting on the
  board is a false statement of what the project wants, and rejecting it afterwards does not
  un-publish it.
**When the picked issue is itself a decision** (a `DEC-N` item), the shape changes and this stage
becomes the only one that does real work. `triage` does not answer the question — it makes the
question answerable, and **the gate is where the captain rules.** Its product is: the question
stated in one sentence a person can say yes or no to; the evidence that bears on it, gathered from
the code and from live stores rather than from the issue's own prose; each available answer with
what it costs and what it forecloses; the precedent, and honestly whether the precedent settles it;
and what is already settled and is not being reopened. Recommend one answer — the captain is owed a
recommendation, not a menu — but never record the decision as made. `implementation` writes the
captain's ruling into Linear, closes the issue, and moves whatever it gated to `Todo`; the entity
then parks at `recorded`. A decision issue must not be sent back to `selection` for want of a
decision: it *is* the decision, and that would be a loop.

- **Gate content:** Show the User value brief and the labels first, then the captured original
  against the drafted rewrite, the drafted milestone correction, what was demoted to history and
  why, the acceptance criteria with their offline/interactive split and each `Verified by:`
  clause, the expected surface and tolerance, and the approach chosen with the simplest rejected
  alternative and the reason it cannot deliver the value. **Nothing has been written to Linear yet
  — this gate authorizes that write.** For a decision issue, show instead the one-sentence
  question, the evidence for and against each answer, what each answer costs, whether the
  precedent settles it, and the recommended answer — **and this gate is where the captain rules,
  not merely where a draft is approved.**

### `implementation`

The rewritten issue is approved and gets built in a dedicated worktree on its own branch.

- **Inputs:** The approved entity body and its acceptance criteria. The repository. **AGENTS.md**,
  in particular "Pre-PR Checks", "Parallel Work" and "Code Comments".
- **Outputs:**
  - **First action:** the drafts the gate approved written to Linear — the issue body, the owning
    milestone description, and the `journey:*` and `move:*` labels named at triage. Nothing else in
    this stage starts until that write lands, so the board and the branch describe the same intent
    from the moment work begins.
  - `recce-dev:linear-deep-dive` run for this issue and **stopped at step 6, Propose Approach** —
    its classification, key files and risks are used; its own workflow past step 6 is not continued,
    because this stage owns what happens next.
  - The failing test written first and **watched to fail for the right reason**. A test that passes
    the moment it is written is testing what already worked.
  - The canonical pre-PR suite run from **AGENTS.md, "Pre-PR Checks"** — read from there, not from
    a copy, because a local copy is how someone passes locally and fails the required check.
  - `sync-docs` invoked, its doc updates committed onto this same branch. It is a step of the gate,
    not an optional extra.
  - The actual surface measured against the triage estimate **before the PR opens**:
    `git diff --numstat "$(git merge-base main HEAD)"..HEAD`, reported as files and LOC versus
    declared, with the percentage. Beyond the declared tolerance, stop and put it to the captain as
    a design reset rather than opening the PR. An estimate exceeded silently is how a narrow issue
    becomes a wide one without anyone deciding to widen it, and a tolerance nothing measures is
    decoration.
  - A PR opened whose body starts `Implements [DRC-####](url) — <issue title>` and carries a
    `## Verification` section naming what was run and what it said. `Closes #NNNN` only when a
    mirrored GitHub issue actually exists, one line per issue, never comma-separated.
  - The diff reviewed **in the worktree before the PR is opened**. Reviewing after means every PR
    runs CI twice — green, blocked by review, fixed, green again — at roughly fifteen minutes of
    pure waiting per PR, avoidable by reordering two steps.
- **Issues group into pull requests; each issue is still reconciled on its own.** A group of
  issues that change the same view or contract is the unit of merge risk, and an issue remains the
  unit of Linear reconcile, with its own receipt. The `burndown` skill owns the grouping rule and
  the stack procedure. The hard constraint survives in one form: exactly one line of history may
  touch `compass_runtime/web/`, which is one pull request or one stack of layers built on each
  other.
- **Good:** The change is the narrow reading of the issue. Commits are DCO signed off. Comments
  record decisions — why not the obvious alternative, what was measured, what was rejected — and
  never restate the line below them.
- **Bad:** Editing a version field; the tag-driven Release workflow owns them and `version-guard`
  fails any PR that touches one. Widening scope. Filing a second problem as part of this branch
  instead of filing it as its own issue. Believing a failure in `test_http_api`, `test_page`,
  `test_lifecycle` or `test_quota` without re-running that module alone — concurrent suites
  manufacture those, and a load average above about 10 makes it near-certain.
- When a finding arrives, follow `## Review-finding disposition`: investigate read-only, preserve
  its evidence, propose materiality, ownership and disposition, and obtain distinct FO
  authorization before any candidate edit, commit, or reviewer rerun.

### `review`

A fresh agent that did not build the change reviews the PR at a depth it chooses. **It observes and
verifies; it does not edit.** Confirmed material findings route back to `implementation` over the
`feedback-to` edge, which fixes them and returns the PR for re-review. `fresh: true` buys a reviewer
with no stake in the change, and that is spent the instant it edits — from the first edit onward it
would be reviewing its own work.

- **Inputs:** The PR, its diff, its CI state, the acceptance criteria from `triage`, and
  **AGENTS.md, "Calibrating Effort"**.
- **Outputs:**
  - **Review depth chosen from the diff and stated up front**, per the Calibrating Effort table:
    self-verify for a change with no user-visible behaviour that nothing calls yet; full adversarial
    for security, credential handling or data loss; two lenses plus an arbiter for everything else,
    including anything touching `frontend/`, the built `compass_runtime/web/` bundle, `SKILL.md` or `config.py`.
    Uniform depth is the failure this table exists to prevent — it cost 35 agents and 6.9M tokens
    for 10 blocking findings on one measured run.
  - **An arbiter that reproduces findings rather than ranking them.** On the measured run it refuted
    13, including two blockers the orchestrator had asserted himself. Without that pass the lens
    count has to rise to compensate, which is the expensive direction.
  - Each acceptance criterion reproduced from its `Verified by:` clause rather than trusted from
    the implementation's self-report. Interactive criteria are settled by a live drive or by the
    captain, never by new automation built here.
  - **Copilot inline review comments read, in addition to top-level reviews** (AGENTS.md, PR
    Workflow). A review that reads only top-level is how an inline finding gets merged past.
  - Confirmed material findings routed back to `implementation` through the `feedback-to` edge with
    their evidence, classification and authorized disposition transported unchanged — never
    re-triaged, and never fixed here.
  - CI green on the **current head**. After any sibling merge this PR goes `BEHIND` and needs a
    **full CI re-run**: `gh pr update-branch` for a standalone PR, `gh stack sync` for a stacked
    layer, never the former on a stack. The re-run is the point, because the previous green
    belonged to a superseded head.
  - A GO or NO-GO verdict with the findings that produced it.
  - On GO, the worktree removed **before** the branch is deleted. `gh pr merge --delete-branch`
    fails while a worktree still holds the branch, and the tempting unstick — `git reset --hard` in
    the main checkout — destroyed uncommitted work here once. Remove the worktree, then merge.
- **Good:** The depth is justified by the diff before the review starts, not after. Findings that
  are correct but disproportionate are recorded as declines rather than dutifully fixed. A verdict
  cites what was reproduced.
- **Bad:** Trusting a green CI run that finished before the last push — check `mergeStateStatus` is
  `CLEAN` and that the checks belong to the current head. Trusting `git merge-tree`'s
  three-argument form to reveal conflicts; it did not, and a real conflict followed. Promoting a
  deferred finding into this PR — file it; promoting buys another implement-and-CI round for
  something already judged not worth blocking on, and four promotions cost about an hour once.
  Resolving a conflict in the built bundle (`react.html`, `react.integrity.json`) textually: rebuild
  it with `pnpm build`, because each side is correct for a tree that no longer exists. Editing the PR branch from this stage at all — a fix
  belongs to `implementation`, and a reviewer that has edited can no longer say the change was
  checked by someone who did not write it. Reading only top-level reviews and calling the review
  complete.
- When a finding arrives, follow `## Review-finding disposition`.
- **Gate content:** Show the chosen review depth and the diff property that justified it, the
  findings under their disposition labels with what the arbiter reproduced or refuted, each
  acceptance criterion with the evidence reproduced for it, the CI state and the head SHA it belongs
  to, `mergeStateStatus`, whether Copilot left inline comments and what became of them, and the
  GO/NO-GO verdict. This gate authorizes the merge; on rejection the findings route to
  `implementation` rather than being fixed here.

### `done`

Terminal. The PR is merged — tracked on the `pr` field by the `pr-merge` mod and finalized by
`spacedock merge guard`, which terminalizes and archives atomically. Reached by a real merge, never
by a manual flag flip.

**The merge is not the end of the work.** `## Post-merge Linear reconcile` below is required and
runs at merge detection. An issue whose code landed and whose Linear records still say otherwise is
the specific failure this workflow exists to stop.

**Order, and it is not optional.** The merge lands, then the reconcile runs, then `reconciled` is
stamped, and only then is `merge guard` invoked. The guard terminalizes **and archives** in one
locked write, and an archived entity is read-only — so calling it first makes `reconciled`
permanently unsettable and leaves a false positive in `selection`'s guard forever. The tempting
wrong order is the natural one, because the guard is what confirms delivery. Resist it. Learned by
getting it wrong on `drc-4274`.

- **Inputs:** The merged PR and its merge commit, the entity's acceptance criteria, the owning
  milestone description, the project overview's "As of" block, and the closed issue's `blocks`
  relations.
- **Outputs:**
  - All six edits in `## Post-merge Linear reconcile`, in order.
  - A comment posted on the Linear issue naming all six edits and the merge commit. This is the
    **external receipt**: it lives in the system the reconcile is about, it survives the entity
    being archived, and it is visible to someone who never opens this workflow.
  - `reconciled: {ISO 8601}` written to the entity frontmatter and committed **before**
    `merge guard` terminalizes. `merge guard` terminalizes and archives atomically, so an entity
    that reaches the archive with `pr` set and `reconciled` empty is an interrupted reconcile — and
    it is recoverable only because the field is absent. Without it, a session that dies between the
    merge and step 3 leaves an issue whose code shipped and whose Linear record still reads open,
    and the next `selection` cycle picks it again and rebuilds it.
- **Good:** All six edits made against the merged state, not against the pre-merge intent. The
  milestone edit names what actually shipped. Step 5 leaves closed-to-closed edges alone.
- **Bad:** Reporting the issue closed before the receipt is posted. Sweeping a closed-to-closed
  `blocks` edge — that turns a satisfied dependency into no dependency, which is a different and
  less true statement than the one the edge was making.

### `recorded`

**Parked, not terminal.** The cycle's deliverable was a change to the **Linear record** rather than
to the repository. Two shapes reach it, and both are real outcomes rather than failures:

- **Escalated.** `triage` found the issue needs a decision nobody had filed. `implementation` filed
  the decision issue, added its `blocks` edge, rewrote the body and corrected the milestone. The
  issue stays open in Linear as `Blocked`.
- **Decided.** The issue *was* the decision. `triage` sharpened the question and assembled the
  evidence, **the captain ruled at the gate**, and `implementation` wrote that ruling into Linear,
  closed the issue, and moved whatever it gated to `Todo`. The issue is `Done` in Linear.

**Why parked rather than terminal**, measured on DRC-4029 rather than assumed:

- Terminal is the wrong claim for the escalated shape. A blocked issue is waiting on a decision, not
  done, and `terminal` would say the cycle ended forever.
- Terminal is mechanically hostile for both. `status --set` treats a terminal status **and clearing
  `worktree=`** as terminal updates, and a workflow declaring a `merge:` hook refuses any terminal
  update with no `pr` and no `mod-block`. So a terminal end state could only ever be reached with
  `--force`, on every no-delivery cycle — and this board carries five open decision issues, so those
  recur. A normal path that needs `--force` is a design error, not a fact of life.
- The scheduler leaves a parked entity alone. Verified 2026-08-28: with DRC-4029 at this stage,
  `status --next` returned it in neither `dispatchable` nor `ready_gates`.

- **Inputs:** The completed `implementation` stage report, and the Linear identifiers it wrote —
  the decision issue filed, or the issue closed and the dependents released.
- **Outputs:**
  - `status: recorded`, and nothing else in frontmatter moved. `verdict` empty, `completed` empty —
    the issue was neither delivered nor rejected, and the binary agrees: an empty verdict "always
    passes", and the verdict gate keys on the finalize action rather than on reaching a stage.
  - The relevant Linear identifier in the entity body, so a later reader follows the chain in one
    hop without re-deriving it.
  - No archive. Archiving is refused while a `merge:` hook has not run, and there is no delivery to
    run it against. Leaving the entity on the board is also the more useful state:
    `spacedock status --where status=recorded` is then the list of cycles that ended in the record.
- **Good:** The Linear identifier is reachable from the entity in one hop, and **Linear — not this
  stage — is what `selection` reads to decide what happens next.** This workflow does not track why
  an entity is here; the issue's own state does.
- **Bad:** Parking here on a hunch that an issue is hard. This stage means a real, checkable change
  landed in Linear — a filed decision issue holding a `blocks` edge, or a closed issue with its
  dependents released. Setting `verdict: REJECTED` to satisfy a guard: it is the one value that
  makes the merge-hook guard stand down, which makes it exactly the tempting lie, and it records a
  judgment on the work that nobody made.

**Closeout sequence**, in this order. Derived on DRC-4029; the ordering is not arbitrary, because
two of the steps trip guards when combined.

1. `status --set {slug} status=recorded` — **alone.** Do not add `worktree=` to this call: clearing
   `worktree` is itself classified a terminal update, so combining them trips the merge-hook guard
   and the whole call refuses.
2. `status --set {slug} worktree= --force` — field-scoped, and the one `--force` this path needs.
   Before using it, prove the guard's premise is false rather than assuming: `pr` empty, `mod-block`
   empty, and the worktree at the trunk tip with zero commits ahead. There was no delivery, so no
   ceremony step was skipped. Clearing is not optional — `recorded` is neither initial, gated nor
   terminal, so a non-empty `worktree` makes the post-dispatch guard demand a
   `## Stage Report: recorded` that will never exist, and the entity could not be moved later.
3. `git worktree remove {path}` then `git branch -d {branch}`. Use `-d`, never `-D`: it refuses if
   the branch carries unmerged work, which is the check, not an inconvenience.
4. `state commit {slug}`.

**What `selection` does with it next**, decided by reading Linear rather than this stage:

| The issue's Linear state | What happens |
|---|---|
| `Blocked` | Left alone. Rule 1 drops it while the `blockedBy` edge is live. |
| `Done` / `Canceled` | Closed. Note it and leave the entity parked; it is the record of the cycle. |
| Open and unblocked | An ordinary candidate again — move the entity `recorded → selection` for a fresh cycle. **Do not file a second entity for the same issue.** |

## Review-finding disposition

Every finding enters this checkpoint when it arrives during implementation, review, a detached
audit, consequential FO quick work, or a correction routed from a rejected gate.

1. The reviewer owns observation, not task ownership or authorization.
2. The worker preserves the finding, investigates without candidate mutation, records the four
   evidence fields, and proposes materiality, task ownership, and disposition separately. Its
   `actor:ensign` round Resolution is advisory.
3. The FO sends a distinct `fix`, `decline`, `hold`, or `route for decision` authorization through
   the runtime's addressable-worker boundary.
4. The reviewer recommends `PASSED` or `REJECTED`; a new finding re-enters step 1.
5. Only the captain changes approved scope, accepted value, thresholds, tolerance, or acceptance
   criteria.
6. After revise is selected, rejection routing transports the evidence, workflow classifications,
   authorized dispositions, and concrete assignment unchanged; it never re-triages.

Before FO authorization, candidate bytes and Git HEAD stay unchanged, no candidate commit is made,
and no reviewer rerun starts. Read-only file/history inspection, non-mutating reproductions,
existing tests, and adversarial work in a throwaway checkout are allowed. After authorization,
perform only that disposition; `hold` and `route for decision` forbid mutation and rerun. Changed
evidence re-enters the checkpoint, and an unobservable runtime authorization means hold and
re-consult.

The four evidence fields are released user and normal workflow; observable harm; affected value AC
or non-negotiable boundary; and trigger evidence. Field 3 uses `value-ac[AC-N]`,
`captain-ruling[YYYY-MM-DD]`, or `contract[repo/relative/path#anchor]` plus a nonblank claim;
`none:` plus a rationale cannot establish Material.

- **Material:** all four fields establish supported-workflow harm to a value AC or protected boundary.
- **Deferred risk:** the trigger is hypothetical, unsupported, unobserved, or outside current
  promises; record its promote-to-material condition. **File it in Linear** rather than promoting it
  into the current PR.
- **Polish:** no current user-visible loss or protected boundary is at risk.
- **Needs decision:** the task cannot own the required scope, product, or compatibility decision.

Materiality and task ownership are independent. Owned Material is eligible for an FO-authorized fix;
out-of-scope Material holds unchanged as Needs decision. Deferred risk or Polish may be declined
only after FO authorization.

After reviewer and worker entries and FO consultation, the First Officer appends the Cycle line
directly from the authorized package. Then the First Officer invokes
`${SPACEDOCK_BIN:-spacedock} gate record --round` with the canonical Briefing/log before reviewer
re-run or next-gate preparation. The neutral recorder retains those bytes and advances
`review-round`; it applies no gate or status change, and it does not parse classifications or
project workflow prose. A correction round uses
`- Cycle {N}: {verdict} — {reviewer/loop}; surface {files}/{LOC} vs estimate {declared} ({P}%); AC {unchanged | narrowed: <note>}`.
Compare `git diff --numstat "$(git merge-base main HEAD)"..HEAD` with the triage estimate; beyond
declared tolerance or on narrowed AC, require a captain-visible design reset. Cycle 3 escalates.
## Post-merge Linear reconcile

Required, and the reason this workflow exists rather than just the skills it calls. Runs when the
merge is detected, before the entity is reported closed to the captain.

The six edits live in the `burndown` skill's
[Linear reconciliation adapter](../../.claude/skills/burndown/references/linear.md#reconcile),
and not here. This section used to carry
its own copy, against this document's own lede, and the copy drifted: it kept a dated historical
section on milestones that `sync-project` removes, it required an "As of" block of derived numbers
on the project overview that `sync-project` forbids, and its third item was a different instruction
from the skill's third rather than a reworded one. Follow that adapter's six reconciliation items
under the [shared landing lifecycle](../../.claude/skills/burndown/references/reconciliation.md).
The evidence for why the step is not optional lives with the adapter.

What this workflow adds on top is set out at the `merge` stage above and is not the skill's: the
receipt comment on the Linear issue, and the `reconciled` stamp written before `merge guard`
archives. One thing reconciliation item 2 needs from here: the milestone write resends the whole
description, so
the milestone-edit rule in `## Workflow-specific rules` applies to it. Report what the serializer
moves; do not repair it.

## Writing a dispatch checklist

The FO authors the checklist at each dispatch. Two rules, both learned the hard way on 2026-08-28.

**An item must be satisfiable by the worker it is given to.** `spacedock status` refuses to advance
an entity away from an entered worktree stage while its report carries a `FAILED` item, and that
guard sits deliberately before every `--force` bypass. So an item the worker cannot pass parks the
entity, and the only honest exits are a re-dispatch against a corrected criterion or the captain
authorizing an amendment. On DRC-4029 an item required confirming that a milestone's pre-existing
sections were untouched — which `save_milestone` cannot deliver, because it has no patch operation
and resends the whole description. No worker could have passed it.

**An addendum to a stage report must not reuse the `## Stage Report: {stage}` heading.** The report
selector takes the **latest** section matching that prefix and stops, so a second one silently
*replaces* the first rather than supplementing it — the original's items become invisible to
`status --read --checklist` and to the completion guard, and the entity cannot advance. Nest an
addendum as a `###` subsection inside the existing report instead, and give every item an evidence
continuation line on its own line, since an item whose evidence shares its line parses as having
none. Measured 2026-08-28 on DRC-4037, where a correctly-motivated append — preserving the original
report as written, which is the right instinct — hid three fully-evidenced items from the machine.

**Name the artifact, not a category.** An item that says "leave the issue in a state that reflects
X" does not say whether it means the Linear workflow state, a relation, or a body section — and if
another item already owns one of those, the ambiguity is invisible to the author and obvious to the
worker. Name the field, the relation, or the heading. Measured twice: a self-contradicting milestone
draft on DRC-4122, and an under-specified "state" clause on DRC-4037. Both times the worker stopped
and asked rather than picking silently, which is the behaviour to protect — but the cost was mine to
avoid.

**Separate the process obligation from the outcome assertion.** Ask for the obligation, which the
worker controls: *perform the read-back and report every discrepancy.* Do not fold in an outcome the
worker does not control: *and nothing drifted.* A conjunctive item fails whole on any one part, so an
outcome clause turns a correctly-performed check into a `FAILED` and hides the good work inside it.
Discrepancies are dispositioned by the FO under `## Review-finding disposition`; they are not the
worker's to pass or fail.

## Workflow-specific rules

The FO/ensign operating contract already governs generic stage semantics and proof discipline:
prefer the cheapest check that can fail — a shipped guard's run, an existing mechanical check, a
one-off falsifiable exercise recorded in the report, then the captain's judgment — with new standing
enforcement as the last resort; prove by exercising rather than re-reading; and reject any AC whose
only proof is a review of its own prose. The rules below add the specifics of this repository.

- **Linear is the only source of state.** `docs/visibility-2x2/items.json` holds the panel's scores
  and its `state` fields are deliberately stale, kept as the dated record of what was scored. Use it
  for scores, never for what has shipped.
- **One issue per branch.** If a second problem turns up, file it and carry on. Several issues at
  once means several worktrees, which is normal here and has its own failure modes: read **Parallel
  Work** in `AGENTS.md` before starting the second, and hand its contention list to every builder.
  An agent that has not been told will report a loopback-port collision as a regression, and it
  reads convincingly.
- **Never edit a version field.** The tag-driven Release workflow owns them and `version-guard`
  fails any PR that changes one.
- **A milestone edit rewrites the whole description, and Linear's serializer will move some
  emphasis.** Measured 2026-08-28 on DRC-4029's milestone write: `save_milestone` has no patch
  operation, so inserting a section resends the entire existing description, and Linear re-serializes
  it from its document model on the way back. A bold run whose boundary directly touches an inline
  code span or a link gets its mark boundary moved or the run split — five occurrences on that one
  write, three of them in pre-existing text the edit was not touching. Text content was unchanged in
  every case. The trigger is **adjacency**, not the presence of code or links: `` `long` **latches** ``
  has a space between the two, was already canonical, and round-tripped untouched.
  **The space mitigation is weaker than first recorded.** Measured twice on 2026-08-28: a space
  between an emphasis run and a *following* code span did **not** prevent the move — the bold run
  swallowed the space, and an italic run containing a code span came back split at it. Sibling
  bullets whose runs were followed by ordinary text round-tripped clean, so the trigger is **a code
  span following the run**, not adjacency in general. The reliable avoidance is structural: **do not
  end an emphasis run immediately before a code span** — restructure the sentence. **In text you
  author, whichever stage you are in**, that is the guard.

  **The structural avoidance is proven, not theorised.** On the same day, a section authored to keep
  every code span away from every emphasis run round-tripped **byte-identical, zero boundary moves**,
  through the same API that damaged the hard-wrapped draft beside it.

  **And the damage is progressive, which "the boundary moves" understates.** A first write moves the
  boundary, leaving the malformed `**label. **` shape; a *later* write resolves that malformed
  nesting by **dropping the mark entirely**. Measured 2026-08-28 on DRC-4122, where five pre-existing
  lead-ins lost their bold outright — with the visible cost that option B's label is now unbolded
  while A, C and D remain bold, so a closed decision record's option list reads inconsistently. This
  happened through a `patch` **append** op that re-transmitted no existing byte, which is the
  sharpest confirmation yet that a targeted patch is not a targeted write.

  **Repair provably cannot succeed**, measured on both halves of one cycle: sending the clean
  ``**label.** `code` `` returns the damaged ``**label. **`code` ``, so repairing a damaged run
  re-creates the exact input the next write drops. There is no stable state to repair toward. Author
  it correctly the first time or accept the seam. The guard binds the **author**, and `implementation` authors prose too — an `## Outcome`
  section composed from a ruling is authored, not copied. What `implementation` must never do is
  **alter approved prose** to satisfy the guard: a draft the gate approved is immutable, and editing
  it is a second unapproved change to a record other people read. So: apply the guard to what you
  write, write approved drafts verbatim, and report the boundary move either way. This rule has been
  revised three times, each time after a real miss — first written as "expect it", then wrongly
  narrowed to `triage` only, now bound to authorship. **In pre-existing text nobody is touching** it is unavoidable regardless, because the
  whole description is resent.
  There, say so in the stage report and **do not repair it.** A repair cannot succeed, and that is
  measured rather than inferred: the pre-write capture showed all three affected spots already in the
  clean form, the write resent those captured clean bytes verbatim, and they came back shifted. So
  sending clean bytes is precisely what produces the shifted form, and a second write would reproduce
  it — it is not merely *likely* to be a no-op. Nothing is visibly wrong where people read it either,
  since Linear renders from its document model rather than from this markdown. This matters because
  `## Post-merge Linear reconcile` step 2 edits a milestone description on every completed issue.
- **The first `gate prepare` on a flat entity makes it a folder entity.** `prepare` writes the room
  under `{slug}/review/...`, and `status --validate` then warns that a flat `{slug}.md` beside it
  leaves every retained room unreadable. Fix it in one commit —
  `git mv {slug}.md {slug}/index.md` **and** rewrite every `room-ref: ./{slug}/` to `room-ref: ./` —
  and do it while **no worker holds the entity**, because moving the file out from under a running
  agent breaks its writes. The right moment is right after a stage report lands and before the next
  dispatch. What is at stake is the briefing that records a captain's decision, so it is an audit
  trail rather than a tidy-up. Seen on DRC-4029 and again on DRC-4271; expect it every cycle.
- **`save_issue`'s `patch` is not a targeted write either.** Measured 2026-08-28 on DRC-4029: a
  `patch` call re-serialized the whole document and moved emphasis boundaries outside the patched
  range. The milestone rule above is really a Linear-write rule — it applies to every issue and
  milestone body write, however targeted the call looks.
- **Any issue reference in body text becomes a mention, and a mention creates relations.** This is a
  second mechanism, distinct from the serializer, and it does two things: it can drop an adjacent
  bold or italic run, and it **silently adds `relatedTo` edges nobody asked for**. **Markdown links
  do not prevent it** — measured 2026-08-28, when five unrequested edges appeared across two issues
  despite *every* identifier being written as a link, because a link whose href is a Linear issue URL
  is parsed as a mention too. There is therefore no safe way to reference an issue in a body: expect
  relations from any reference, and **read back the relation set after any body write that mentions an issue.**
  It has not been observed creating a `blocks` or `blockedBy` edge; if it ever does, that is Material
  immediately, because the plan's `blockedBy` order reads exactly those and a silent gate would drop a
  live candidate.
- **Check a Linear error against read-back state before retrying it.** **Reproducible, not a
  one-off** — observed three times across two cycles (2026-08-28): a `save_issue` call returns
  `Error: Failed to remove 1 relation(s)` while every part of it has in fact landed — body patch, state change, `blockedBy` cleared, `relatedTo` added. Adding `relatedTo`
  appears to convert the existing blocking relation, leaving `removeBlockedBy` nothing to remove. A
  retry on the error alone would have been a second unapproved write to a shared record.
- **A milestone correction may go in a comment when there is no capture to script from.**
  `save_milestone` has no patch operation, so any description edit resends the whole body — and the
  rule above requires such an edit be built by script from a pre-write capture with an exactly-once
  assertion and a diff. When the capture exists only in an agent's context rather than on disk,
  hand-reconstructing thousands of words to satisfy a rule about not hand-reconstructing them is the
  wrong trade. A dated comment on the milestone renders with the description, is additive, and
  carries no resend risk. State in the comment why it is a comment.
- **Send Linear bodies unwrapped.** Entity files here are hard-wrapped at 100 columns; Linear reads
  those newlines as hard breaks and re-marks emphasis **per line**, producing split runs and ragged
  mid-sentence breaks the draft never intended. Measured 2026-08-28 on DRC-4037, where a hard-wrapped
  draft produced stray marker artifacts while two unwrapped drafts sent the same day showed none.
  Join paragraphs to one line before sending; the wording does not change.
- **Build a milestone edit by script from a pre-write capture, and diff it before sending.** The
  whole description is resent on every write, so a hand-assembled body is an unbounded diff nobody
  has read. Capture the live description first, apply the authorized replacements programmatically,
  assert each target passage is present **exactly once** before replacing it, and diff the result —
  the hunk count should equal the number of authorized edits and nothing else should move. Adopted
  as the default after DRC-4122's cycle used it and could state "exactly three hunks, no other
  change" as a fact rather than an intention.
- **Verify PR content at the SHA, never from `gh pr diff`.** Measured 2026-08-28 on PR #238: a
  `gh pr diff` grep returned added lines carrying a harness name list that was present in **no**
  version of the file — not the pre-correction head, not the corrected head. It was pre-PR draft text
  the author had already removed, served from a stale view, and it nearly produced a false alarm
  against an accurate review. The authoritative reads are `git show <sha>:<path>` and the contents
  API at that ref, compared by checksum. Use them before contradicting anyone.
- **Write records specific enough to be contradicted, and when a later measurement disagrees with a
  recorded figure, suspect a hidden variable before suspecting a miscount.** DEC-3 recorded a
  `core.fsmonitor` hook running "twice per invocation" **at git 2.55.0**. Two cycles later a build
  re-measured it varying only the hook's exit code: exit 0 gives one invocation, exit 1 gives two,
  because git re-runs a hook that signals failure. **Both figures were right and neither cycle
  miscounted** — but the intervening correction, which the FO authorized, recorded it as a wrong
  figure and misrepresented what had happened. Two lessons, and the second is the one worth keeping.
  The FO had been told the exit-code nuance by an earlier review and still wrote the simpler version;
  simpler was less true. And the discrepancy was **findable at all only because the original record
  named a number and a version** — a hedged note saying the hook "may run more than once" would have
  absorbed it silently and the mechanism would never have been learned. Prefer the falsifiable claim
  to the safe one.
- **Re-baseline the surface estimate at a correction round.** A round's content is the findings, and
  findings are by definition unknown when the estimate is declared — so measuring a post-correction
  branch against a pre-review figure measures how much review found, not how accurate the estimate
  was. Declare the round's own surface separately. Measured on DRC-4037 PR 1, where correction round
  1 came to +414 lines of which roughly **four were functional**: the rest were oracles the review
  had explicitly demanded, because R3's entire finding was that the guards were unpinned and R5's was
  that an acceptance criterion's named oracle did not exist. Trimming to the original tolerance would
  have deleted exactly what the round was routed to add. This is the fix the captain's
  accepted-once caveat asked for, not a way around it.
- **Never mark an issue `Done` before its PR is merged to `main`.**
- **Never widen scope to make an issue feel complete.** The board's estimates assume the narrow
  reading.
- **Repo-mutation worktree layer.** `implementation` and `review` run in a worktree against the
  codebase, and `review` is `fresh` so an agent that did not build the change checks it. PR state
  lives on the `pr` field, managed by the `pr-merge` mod — there is no `pr-open` or `awaiting-merge`
  stage.
- **No prose-grep over instruction files.** A string, substring, or regex match over an instruction
  file the model reads (this README, `AGENTS.md`, a skill) never proves a behavioral claim. The
  matched text was written by the same implementer the check polices, so it asserts only that the
  file contains what we put in it. A valid paraphrase fails it and an inverted clause passes it. To
  settle a case, ask whether the expected value comes from outside the file under test; if it does
  not, the check is a tautology and is banned. A check binding two independent values that can
  diverge — the plugin manifest's version sharing a major.minor with the binary's — is legitimate.
  Prose-greps are one-off validation evidence, never committed tests.
- **Evidence must be able to fail.** Each AC's cited evidence names the concrete change that would
  flip it. An author who cannot name what would make the evidence fail has not shown it can fail,
  and the criterion does not count.
- **The built bundle is the conflict you will get.** `react.html`, `react.integrity.json` and
  `react-licenses.txt` are generated from `frontend/`. Rebuild with `pnpm build` and confirm with
  `pnpm build:check` rather than resolving a conflict textually. Exactly one in-flight PR may touch
  `frontend/` or `compass_runtime/web/`.
- **A session you spawn leaves daemons behind.** Driving a harness to reproduce something starts
  that harness's own hooks and they outlive the sandbox. Thirteen survived a deleted directory once
  and drove the load average to 18, which caused the contention failures above. Kill what you
  started, and scope the kill to what you started.
- **Test-first authoring.** For a code or fixture deliverable, write the failing test first, watch
  it fail for the right reason, then write the minimum code to pass. The test is what the gate
  judges.
- **Detached adversarial audit** for high-stakes surfaces — a front-door launcher, status or guard
  mutation paths, shipped contract or scaffolding, CI and release machinery. Run a read-only audit
  on a throwaway checkout that tries to refute the review with an edit the deliverable's own tests
  should catch. "Refuted nothing material" is a valid recorded outcome. The audit also fires on AC
  provenance: when an AC's expected value is derived from the same package's production functions
  or constants, run the adversarial-edit check on it — that provenance is the tautology tell.
- **Live scenario for runtime claims.** When an AC's truth is what an agent or model *does* at
  runtime, prove it with a scripted live scenario graded on durable before→after state plus observed
  output, with a negative case that reds the grade. Mark it
  `Verified by: live <ci-run:<id> | session:<path>>`. An offline proxy or a contract-text check
  proves the watcher or the words, never the runtime behavior.

## Captain's standing directives

Given 2026-09-03, in the captain's own words where quoted. They bind the first officer's conduct in
this workflow and override the defaults above wherever the two differ.

- **When waiting on the captain, be extremely clear, concise and to the point.** A decision request
  is one short block: what is waiting, the recommended answer, and what saying yes does. It is never
  buried in a status report, never restated across several messages, and never mixed with things
  that are not waiting. "It is way too easy for these to get lost."
- **Gate approval approves everything discussed.** When the captain approves a gate, every
  recommendation and disposition the first officer put in that presentation is approved with it —
  finding dispositions, filings, follow-ups. Only what the captain asks to revise needs amending.
  Do not re-ask.
- **Small findings are fixed in the PR in flight, not filed.** A one-clause wording fix, a wrong
  count, a stale citation: integrate it into the PR being worked, or the next one already open,
  rather than opening a Linear issue for it. Only a finding that needs its own cycle — a contract
  decision, a design question, work with its own acceptance criteria — becomes a Linear issue. This
  narrows the "never promote a deferred finding" rule to findings large enough to be their own
  cycle; a small fix is not a promotion, it is a fix.
- **Do not wait for "yes, that's fine."** Reversible follow-through — filing the issues a review
  produced, folding small fixes into a PR, dispatching the next stage the captain already directed —
  happens without a confirmation round. Ask only for choices that are hard to reverse or genuinely
  the captain's to make. "I want to get things done."

### Given 2026-09-17, for the Clean and Cogent UI/UX milestone

Two rulings, in the captain's own words, scoped to this milestone's burndown.

- **Group the PRs by dependency tier, not one per issue.** All twelve issues in the milestone touch
  `compass_runtime/web/`, and exactly one in-flight PR may. The `burndown` skill already provides
  for it — "the second issue rides that PR or waits for it" — so a tier lands as one branch carrying
  several issues. **One-issue-per-branch above is suspended for this milestone only**, and the cost
  it was buying is paid another way: the post-merge Linear reconcile still runs **once per issue**,
  and the PR body carries one `Implements [DRC-####](url)` line per issue it closes. A tier is the
  merge-risk unit; an issue remains the reconcile unit.

  Superseded 2026-09-23: grouping is now the `burndown` skill's standing rule for every milestone,
  and the `web/` constraint is one line of history (one pull request or one stack), not one pull
  request. The ruling above is kept as the record.
- **Standing conn for this milestone: "I pre-approve all the triage and merge gates, just automate
  this entire process and do it."** The first officer renders triage and review gate decisions
  itself, recorded `agent:first-officer` with the grant quoted, and drives to terminal without
  stopping. It still stops for anything only the captain may change: approved scope, accepted value,
  thresholds, tolerance, or acceptance criteria — item 5 of `## Review-finding disposition` is not
  delegated by this grant. The `pr-merge` merge hook's push approval is covered, because the grant
  names the merge gates and says to do it; the draft is still presented before the push.

### Given 2026-09-17, in the captain's own words, and they override the defaults above

- **Take the recommended route; do not wait for a decision you have already made.** "If you have a
  strong recommendation, I want you to take that recommended route. Do not wait for me unless you
  absolutely need my input." A first officer that recommends one direction and then waits has not
  saved the captain a decision, it has added one. Act, and report what was done and why. This
  extends the "do not wait for yes, that's fine" directive from anything reversible to anything the
  FO holds a clear view on — including acceptance-criterion judgments the FO would otherwise route
  up under `## Review-finding disposition` item 5, **unless** the call genuinely turns on product
  intent only the captain holds.
- **When input IS genuinely needed, pull it out where it cannot be missed.** "It is EXTREMELY
  difficult for me to see that you need me because you are burying the need for my attention within
  a lot of prose and content that is not applicable to me." The ask goes at the TOP of the message
  under its own heading, before any status, with the question, the recommendation, and what saying
  yes does. Everything not waiting on the captain goes after it, or is left out.
- **A filed follow-up is not a disposal route.** "Don't just let it dangle." A gap deferred out of
  one PR is worked inside the same milestone, and the milestone is not complete while it is open.
  Filing it records the gap; scheduling it is what closes it.
## The first officer's own failure mode: asserting provenance it has not traced

Three times in one session on 2026-09-17, the FO stated where something came from with the
confidence it should have reserved for something it had actually followed. Workers caught all three.

- It told the captain a pull request was blocked by the ruleset's unattributed-changes clause. The
  real cause was an unresolved Copilot review thread, and the captain found it. The tell was there:
  `mergeStateStatus: BLOCKED` with **no failing check**, which the FO read as confirming its guess
  instead of as a thing it had not explained.
- It told the captain a worktree reflog entry pointed at an ensign's own tooling. It was the
  reviewer, which had already owned it in its report — and which pointed out that `git archive`, the
  FO's other candidate, cannot touch HEAD at all, so that guess was not merely wrong but impossible.
- It sent an ensign a correction for a claim that ensign had never made. The claim belonged to a
  sibling's report. The ensign grepped its own report, found nothing, and sent it back: an accepted
  correction becomes part of the record, and a misattributed one hardens into a fault on a report
  that never carried it.

The shape is always the same — a plausible attribution offered as a finding. **Trace it or mark it
untraced.** "I have not checked which of these it was" costs one clause and is worth more than a
confident wrong answer, which is the defect class this whole product exists to remove. The FO is
not exempt from the standard it holds its workers to, and a worker that pushes back on a
misattribution is doing the job.

**A second FO failure sits beside it and is not the same one: asserting current STATE from a stale
read.** Three of four consecutive messages to one worker on 2026-09-17 described a state that had
already changed — a report said to be missing that had been committed and pushed minutes earlier, a
branch said to be untouched that had already been rebased, a rebase instruction whose premise no
longer held. Each cost a round trip, and one of them would have corrupted a branch had the worker
complied instead of checking.

That is distinct from an unchecked *provenance* claim: nothing was misattributed, the reading was
simply old. The trigger is specific and easy to guard — **the FO asserts state most confidently
right after dispatching a write to it**, when its own read is guaranteed stale. Re-read immediately
before asserting, and when telling a worker what its own artifact contains, prefer asking it to
confirm over telling it what is there. The worker holds the current copy; the FO holds a snapshot.

**And the fix is structural rather than a resolution to be more careful**, which is the sharper
version and belongs to the ensign that offered it. Each of those three was caught by the party
holding the artifact — the captain who could see the pull request, the reviewer whose reflog entry
it was, the ensign who could grep its own report. **A provenance claim is cheaply checkable by
whoever owns the source and nearly unfalsifiable by anyone else**, so the receiving party is
structurally the wrong place to verify it. Route the claim to the owner of the source before
asserting it, or state it as unverified when the owner is not reachable. Vigilance does not scale
here; addressing does.

## Cost the contracts, not just the code — the estimating method, fixed

**AGENTS.md** already ruled that an overrun of this shape "is accepted once — if a later one repeats
it, fix the estimating method rather than stretching the tolerance again." It has now repeated. The
recorded case was DRC-4037's PR 1, where runtime landed at exactly the declared figure and tests came
in at 9 files and +541 against 6 declared. On 2026-09-17 DRC-4588 and DRC-4590 landed at **194% of a
combined estimate** with no criterion widened and nothing built outside the acceptance criteria, and
DRC-4587's docs reached 344% of its own. Three occurrences, one cause: **the estimate models the
code and the repository charges for its contracts.**

So a triage estimate costs these as separate lines, not as a margin on the runtime figure:

- **Comments, at this repository's standard.** Measured on DRC-4588: comment lines were **55% of the
  runtime additions**. Applying AGENTS.md's own remedy — move a rationale longer than the code it
  explains into `docs/design-*.md` and shrink the comment to a reference — took runtime from +117 to
  +88 net and moved the volume into docs, which doubled. That is not a saving, it is a transfer, and
  an estimate that budgets only the runtime line sees it as an overrun on both.
- **Falsifiability clauses in tests, and the measured unit is the acceptance criterion.** Every
  criterion names what would make its evidence fail, and several existing tests need their *claims*
  restated rather than their numbers flipped. That clause is what the gate reads, so it is never the
  thing to trim to hit a number. **Price it at ~35 lines of behavioural test per acceptance
  criterion in this suite** — measured 2026-09-17 on DRC-4591 and DRC-4594, whose triages each
  assumed ~9 and came in four times over on the test line alone while the runtime line stayed inside
  tolerance. Eight criteria is therefore roughly 280 lines of test before a single line of the
  feature. Estimate from the criterion count, not from the feature's size.
- **Compelled files.** Not the ones the change chooses — the ones the repository demands: a
  literal-shape assertion a class token breaks, a canonical design doc whose own rule gained a case,
  a `SKILL.md` sentence for the user-visible half. DRC-4037 was compelled into three; DRC-4588 into
  three more, each named in its report.

**And the runtime figure splits again, into executable lines and comment lines.** Measured
2026-09-17 on DRC-4592's group: **161% of the declared runtime estimate on raw lines, 90% on
executable lines**, the difference being 128 decision comments, with every per-file executable
figure inside its declared band. A single raw-line runtime estimate therefore reads a repository
*standard* as an overrun, and reports a change whose shape has not grown as one that has. Declare
the executable figure and the comment figure separately, and judge the design-reset question on the
executable one — the shape of the change is what a reset is for.

The estimate then declares five figures with their own tolerances — executable runtime, comments,
tests, docs, oracles — rather than one. The oracle line is already separate here and works: it has been exact every time,
because byte pins are countable in advance. The others are being estimated the way the oracles were
before anyone counted them.

**An overrun whose cause is the estimate's model is not scope creep, and the two must not be reported
as the same thing.** Ask the diagnostic question: was a criterion widened, or was anything built
outside the acceptance criteria? If no to both, the number is evidence about the method. If yes to
either, it is a design reset and goes to the captain.

## A figure an instrument cannot fully see is a floor, not a count

DRC-4587 produced four counts of the same set in one afternoon — seventeen, fifteen, nineteen,
twenty-one — and **every move between them was a defect in the instrument, never a change in the
tree.** Seventeen came from a `font:` shorthand regex matching the weight instead of the size,
silently dropping two rules. Fifteen was a hand enumeration that under-listed. Nineteen fixed the
regex. Twenty-one added two rules already known by name.

The retraction is the lesson, not the arithmetic. All four came from a per-rule census, and a
per-rule census **cannot see a rule whose family or line-height arrives through the cascade**. So
none of them was a count; each was a floor, and every one was stated as a count. The implementation
that produced twenty-one retracted it an hour after asking the first officer to carry it to Linear,
and removed every figure from the document rather than rewording them. That also retired a
twenty-one-versus-nineteen disagreement instead of settling it, which is the better outcome: two
floors from the same blind instrument cannot adjudicate each other.

Three rules follow, and they cost two correction rounds:

- **State the unit before comparing two figures.** One census counted sans-prose *rules* in a pixel
  band; another counted *selectors* resolving below a floor by composition. Different populations,
  different methods, neither refuting the other — but set side by side without their definitions,
  the later reader takes one as contradicting the other.
- **An element tally is a fact about a moment.** The same shape measured 163 elements and then 183
  forty minutes later, because the board renders whatever sessions exist. Any element count
  reaching a document carries its date and commit; the stable unit is the rule set.
- **And state the narrowest true version of the control, not the convenient one.** The first
  officer wrote that pair up as taken "on an unchanged stylesheet". It was not: the two readings
  sat either side of a commit that changed `styles.css` by 13 insertions and 6 deletions. The true
  claim is narrower — none of those lines touched the rules resolving that shape, so the resolution
  was identical. A sentence whose whole job is to stop a number being read as a property of the
  code cannot itself overstate by a step, and this one did until a reviewer checked it.
- **A count can survive a retraction by being a comparison.** The same document kept "the set is
  comparable in size to the one this branch already moved" after every digit was removed — a claim
  of sixty-seven, in words, that a sweep for numerals never sees. It was also the least supported
  figure in the file: every measured floor was in the teens to low thirties, so the surviving claim
  asserted two to three times the highest of them. Retracting a number and leaving its comparison
  is the same error in the confident direction.
- **A rule whose own example violates it teaches the opposite.** The document's element-count rule
  now carries provenance on its own illustration for exactly that reason.

## A grouped pull request still owes a stage report per entity

Measured on PR #362, the first grouped PR this milestone shipped. The captain's tier-grouping ruling
puts several issues on one branch with one worker, and that worker naturally writes **one** stage
report. The advance guard is **per entity**:

```
Error: entity drc-4590 cannot change status away from entered stage "implementation"
until a durable, complete ## Stage Report: implementation is committed.
```

So the entity whose slug does not name the branch silently has no report, and the group cannot
advance to review until it does. The guard is right — an entity with no report has no evidence
anyone did its work — and grouping is what makes it easy to miss.

**Say it in the dispatch:** a grouped worker writes a `## Stage Report: {stage}` into **every**
entity in the group, each covering that issue's share against the same checklist. Combined surface
figures are fine as long as they are declared as combined rather than repeated in each report as
though they were that issue's alone; the same goes for the Linear relation edges, which belong in
the report of the issue whose write created them.

This is the second per-entity obligation grouping does not relax. The first is the post-merge Linear
reconcile, which the captain's ruling already states runs **once per issue** — a tier is the
merge-risk unit, an issue remains the reconcile unit, and now also the report unit.

## Tell the worker its pull request merged, before it keeps building on the branch

A near-miss on DRC-4587, and it would have undone the merge. The first officer merged the PR and did
not tell the implementation ensign, which was still alive and still holding the branch. It kept
working, and — reading a narrowing instruction as superseding an earlier one — **withdrew the very
commit that had merged**, re-raising twenty rules and re-creating ten inversions that four review
cycles had removed. Nothing landed only because the FO owns pushes and checked `origin/main` before
acting on the report.

Two rules, and the first is the cheap one:

- **A merge is an event the worker must be told**, in the same turn it happens, before it can act on
  a stale instruction. A worker cannot see the merge from inside its worktree, and its branch still
  looks live.
- **A narrowing instruction says what it supersedes.** "Do only X, drop everything else I sent" is
  ambiguous when an earlier message carried a scope decision: the worker read "drop the scope-back"
  and that reading was defensible. Name what survives, not just what is dropped — the ambiguity is
  the instruction's defect, not the worker's comprehension.

What made this recoverable rather than costly: the worker **refused to rewrite history** with a
sibling stacked on its branch and withdrew by checking paths out instead, so the stacked branch
rebased cleanly onto the merged trunk rather than onto a rewritten base. Preserve that instinct.

## What blocks a merge: a regression this change created, and nothing else

**This is the rule the first officer failed to apply, and the failure cost a session.** DRC-4587 took
four review cycles and four correction rounds. Every cycle surfaced real findings. Only some of them
were reasons not to merge.

**A finding blocks a merge only if it is a user-visible regression THIS change created.** Everything
else is filed as a Linear issue and shipped past:

- a defect that **predates the branch**, however related it looks;
- the **remainder** of a criterion accepted on an enumerated verifier;
- an **unbound prose claim**, an off-by-one in a table, a vague quantifier;
- work the reviewer **names as the next issue** rather than as a defect here.

The reviewer's job is to find things; the first officer's is to decide which of them stop a merge.
Treating every `NO-GO` as an automatic correction round abdicates that to the reviewer, who is not
positioned to make it and does not claim to be — on this branch the reviewer's own closing note said
the remainder was "one disposition on one slot" and "a re-derivation of a table that's nearly right",
which the FO then answered with a full scope-back.

**Two mechanical consequences:**

- **One correction round per pull request is the default.** A second needs a reason stated in one
  line: which user-visible regression it closes. If there is none, file and merge.
- **Never serialise the rest of a milestone behind one pull request.** Only `implementation` and
  `review` are bound by the one-line-of-history-per-`web/` constraint, and a stack satisfies it
  while several layers are open at once. A fix to a lower layer still means regenerating the byte
  pins in every `web/` layer above it. Twelve
  gate-approved issues sat idle behind one branch through four review cycles because the FO waited
  on a verdict instead of dispatching the work that did not depend on it.

## When a second review finds more of the same class, stop fixing instances

Measured on DRC-4587, and the cost is the point. Three correction rounds fixed exactly what each was
handed — three cells, then six slots, then four more — and each time the next review found more of the
same defect. Only at the fourth attempt was the instruction "fix the class structurally" rather than
"fix these". **That fix was CSS only: zero emitter files, eight lines added and two removed — cheaper
than any of the three instance rounds it followed.**

The first officer wrote all four assignments. Rounds 1 to 3 were not careless; round 2's emitter
method was a genuine improvement and found every slot it looked for. The dispatcher error was
repeating the *shape* of an assignment that had already failed once.

**Do not over-read this into "the structural fix was available from cycle 1".** The FO wrote that
first and the reviewer corrected it: what was available from cycle 1 was the *question*. The
register that made membership checkable — a sans absence paired with a mono value — only became
measurable once four instances existed to see the pattern in. The honest rule is narrower and it is
about the dispatcher's next move rather than a missed insight: **when a reviewer rejects twice on
the same axis, ask the next round for the rule rather than the next list.**

**And when the rule round still rejects, read what is left before widening the response.** The FO's
first instinct after the fourth rejection was to scope the whole change back — which would have
discarded three verified fixes, a promotion test that killed a previously-surviving mutation, and
three closed findings, in order to avoid two small ones. The reviewer's measurement was that the
remainder was "one disposition on one slot" and "a re-derivation of a table that's nearly right".
Rejection count is not a measure of remaining work, and a class containing defects that **predate
the branch** is not the branch's to close — the standard is that it creates none, not that it ends
them.

**The trigger is cheap to watch for: a second review that finds more of the same class, rather than
something new.** One round finding a miss is ordinary. Two rounds finding the same defect in new
places means the set was never bounded, so completeness could only be asserted — and a third round
of instances will produce a third assertion.

What the structural round must produce, and what the three before it could not:

- **A membership rule the reviewer can check.** Here it turned out three of the four inversions paired
  a sans absence with a mono value, so "figure-paired" resolved to a register the document already
  owned rather than a judgment per slot.
- **A published bound, re-derivable in one command.** Twenty files scanned, eight can contain a
  pairing, twelve cannot. A bound nobody can re-derive is the same assertion wearing a table.
- **An explicit statement of what was NOT checked.** Three helper functions hid 31 pairings inside
  call sites; the round listed them as unverified rather than letting a completeness claim cover
  them. Unchecked-and-named is a reviewable residual; unchecked-and-silent is the next finding.

## A recorded figure goes stale on a commit that never touches the sentence

Measured on DRC-4587 at the moment of merge. The design document said sixty-seven rules resolve to
the sentence token, forty-nine carry the measure cap, and eighteen do not. The tree held **54**, **40**
and **14** — and the sentence's own arithmetic, eight plus eight plus two, no longer closed against
its own total.

**Nothing edited that paragraph.** It was true when written. What made it false was the *revert* three
commits later, which removed rules carrying the token and left the counting prose untouched. A figure
can be accurate on the commit that writes it and wrong on a commit that never opens the file.

Two consequences:

- **A revert is a change, and it invalidates records the same way an addition does.** Re-derive every
  census the reverted rules feed. This is easy to miss precisely because a revert feels like a return
  to a known-good state rather than a new one.
- **This is the argument for binding a census rather than re-checking it.** A bound census fails on
  the commit that breaks it; a prose census fails silently and is discovered by whoever next reads
  it carefully. The stale figures above were found by a reviewer doing a regression pass, not by any
  check, and they had already merged.

## Enumerating the forms of a thing you want gone is the defect, not the search

The same claim survived **four** sweeps of one document, wearing a different form each time: first
"two literals", then "four literals", then a **comparison** to a number three paragraphs up, then
the hedge **"a handful"**. Each sweep enumerated the forms a count can take — digits, then
number-words, then comparisons — and each finished satisfied. A fourth form appeared every time.

**The enumeration is the defect.** No list of spellings is closed, so a search built from one is
never finished; it just stops. The question that catches all four is not *which forms are present*
but **"does this sentence tell a reader how many"** — and no grep answers that, which is exactly why
three passes by two different agents each believed the job was done.

This generalises past counts. Whenever a rule bans a *property* — a magnitude, a promise, an
unhedged claim, a credential — a search enumerating its known spellings will miss the next one.
Either ask the semantic question of each candidate sentence, or bind the property mechanically so
the form does not matter. The forms are unbounded; the property is not.

## A rule written in prose does not audit the prose around it

The sharpest finding of the DRC-4587 cycles, and it belongs to the ensign that hit it twice in one
edit. **Both errors were introduced by the paragraphs written to prevent them.**

- A paragraph retracting every count of a set — because each figure was a floor a blind instrument
  produced — left the size stated as a **comparison** to another number three paragraphs up. Three
  separate passes believed they had removed every count; two were wrong, and the sweep that finally
  worked had to look for digits, number-words *and* comparisons.
- A paragraph establishing that an element tally is a fact about a moment, not about the code,
  **overstated the provenance of its own example**, claiming the two readings were taken on an
  unchanged stylesheet when a commit sat between them.

Neither error was careless, and neither was catchable by the rule it violated, because a rule
written in prose cannot audit the prose around it — including the sentence that states it.

**So bind the claim mechanically wherever it can be made mechanical.** On this branch the tier
sentence stopped being prose the moment a promotion test bound the six promoted rules directly; the
claims that stayed prose are the ones that needed three passes. When a finding is closed in prose,
say so explicitly and carry it as a named residual rather than treating the edit as the fix — a
reviewer can then check the sentence, which is more than the sentence can do for itself.

## Check the property the claim is about, not one that usually moves with it

The general form of every guard failure this milestone produced, and it belongs to the ensign that
stated it. Five guards were green, mutation-checked, and could not witness the thing they were named
for:

| The claim | What the guard actually checked |
|---|---|
| an absence never outranks its value | the two sizes **compared** — blind when both moved together |
| the recovery rows hold their tier | a DOM the emitter never builds |
| a prose absence keeps the floor | the absence **alone**, so it pinned the inversion as correct |
| the primitive owns the resting box | `border-radius` and `border:1px`, blind to a `font-size` override |
| the sentence tier is universal | one rule at a time, blind to a cascade composed across three |

**In every case the assertion was sound and the framing was not.** Nothing was carelessly written;
each guard checked a property that *usually* moves with the claim, and passed at the moment the two
came apart. That is also why mutation-checking did not save them — a mutation of the property being
checked dies correctly, and says nothing about the property being claimed.

**A sixth instance, and it is the one that shows deletion is not enough.** An entry in that census
named a class its own change **deleted**. It did not fail: the resolver walks the element path, so
with the rule gone the absence inherited 15.0 from the section, compared equal to its value, and
passed — green, over a DOM the emitter no longer builds. The fix that worked asserts **both halves**:
the pair's sizes *and* that the emitter stopped building the path, because leaving the rule behind is
how a later revert finds a selector waiting for it. Where a guard names a thing being removed, assert
the removal at the emitter, not only the consequence in the sheet.

**A seventh, and it is a different shape from the other six: a fix that makes its own test vacuous.**
The guards above checked a proxy for their claim. This one checked the claim's *symptom*, and the fix
removed the symptom while leaving the cause. A leaked entry could no longer reach any render path, so
deleting the fix left **every rendered assertion green** — the entry lives forever and nothing
observable changes. Reported upward, that reads as "fixed and green". The answer was to bind the
cause directly: assert the lane is empty, not only that nothing visible is wrong.

**So mutation-check the fix, not only the code it fixes.** A mutation that removes the fix must fail;
if it does not, the test is measuring a symptom the fix happens to suppress.

**And the original defect survived because two criteria were each right alone.** One asserted the
refusal text was present after a press — which *was* the duplicate — and the other never pressed.
Neither criterion was wrong about its own clause; the *interaction* was unasserted. No per-criterion
review catches that, which argues for at least one criterion per issue that exercises two others
together.

Ask one question of a new guard: **if this claim were false, would this assertion change?** If the
honest answer is "usually", the guard is a proxy, and the milestone's record is that proxies fail on
exactly the case worth catching. The defence that worked every time was reading the emitter — what
the product actually builds — rather than the stylesheet, the test fixture, or the rule.

A related distinction, cheap and worth keeping: **"I committed it" and "the remote has it" are
different claims**, and only the second unblocks anyone waiting on it. Check the pushed blob.

## A comparison test cannot see both sides moving together

A corollary, found when the mutation checks were re-run at the FO's instruction after a fixture bug
was fixed — **four mutations killed and one survived.** Reverting a value dropped the value *and* its
absence together, so a test asserting `value >= absence` stayed green while the value silently left
the tier the document records it on.

**A test that compares two things cannot detect both moving together.** Where the contract is that a
thing sits on a named tier, bind it to the tier directly; a relation between two movable quantities
is a weaker claim than either of the positions it is standing in for. This was the second test on
this branch that passed over the defect it was written for — the first had a fixture that built a DOM
the application never renders — and both were found by re-running mutations rather than by reading.

## A polymorphic slot is invisible to both a selector sweep and a live walk

Measured across two review cycles on DRC-4587, at the cost of two correction rounds. **A value and
the absence that replaces it never co-exist in one render.** One expression picks a class — a known
class or an absent class — so the pair exists in the *emitter*, never on the screen at one moment
and never in one CSS rule.

Three instruments therefore cannot see it, and all three were used before it was found:

- A **selector sweep** compares rules, and the pair is not a rule. DRC-4587's round-1 fix swept the
  class, raised seven value rules, justified nine exemptions — and still missed six slots, two of
  them *behind* exemptions it had written reasons for.
- A **live walk of a populated board** compares siblings in one render, which is exactly what the
  pair never is. The reviewer's own cycle-1 sweep used this and it recorded the method failure
  against itself.
- A **green test suite**, because the invariant test written in round 1 pinned seven CSS pairs and
  would have stayed green through all six.

The sharpest single piece of evidence: `.pc-substrate-reason,.pc-terminal-identity p` is **one
declaration**, and the round raised the values paired with one half of it while leaving the values
paired with the other half on that same line.

**Read the emitter, and resolve both branches.** For each ternary choosing between a value class
and an absence class, compute both sides and compare them. Any invariant test binding a
value-and-absence relationship must key on the emitters for the same reason; one that reads the
stylesheet binds the shape the defect is not in.

The class generalises past font size. Wherever a slot is polymorphic — value or absence, present or
withheld, measured or unmeasurable — a change that touches one branch has touched a pair, and the
branch it did not touch is the one to check.

## Never let a pull request sit blocked on an unresolved Copilot thread

The `main` ruleset sets `required_review_thread_resolution: true`, and Copilot reviews every pull
request here automatically. One unresolved Copilot thread therefore holds the merge, with
`mergeStateStatus` reading `BLOCKED` and **no failing check to point at** — which is how it gets
misread. Measured 2026-09-17 on PR #361: the FO diagnosed the block as the ruleset's
`require_extra_approval_for_unattributed_changes` clause and asked the captain for an approving
review. That was the wrong cause; the captain found the real one and resolved the thread by hand.

**The merge ceremony reads and dispositions every review thread before it reports a PR blocked.**
Not "checks for Copilot comments" — reads them, decides on each, and resolves it. `gh pr view` does
not show them; they are a GraphQL surface:

```bash
gh api graphql -F owner=spacedock-dev -F repo=compass -F pr=<N> -F query=@q.graphql \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved==false) | ...'
```

and each is closed with the `resolveReviewThread` mutation against its thread id. The FO can do
both; neither needs the captain.

**Resolving is not dispositioning, and the order matters.** Read the finding first and rule on it
under `## Review-finding disposition`. On PR #361 Copilot was **right**: `docs/design-next-ui.md`
claimed the uppercase label tier carries one tracking value with three exceptions, and the
stylesheet had nine rules off that value — one of them, `.next-capacity-head span`, rendering the
literal `WINDOW` and `USED` on the label tier at `.06em`. A thread resolved without being read
would have merged a false record into a repository whose whole discipline is records specific
enough to be contradicted. Per the captain's standing directive a fix that small rides the PR in
flight rather than being filed.

## Do not stop while the milestone is open

Given by the captain on 2026-09-17: "I forbid you to stop until the milestone is fully taken care
of." It followed a session where the FO reported a blocked pull request and then waited, having
dispatched nobody — the captain's view was "nothing has changed" and it was accurate.

**A blocked PR is work, not a stopping point.** A red check is triaged and re-run or fixed the same
turn it is seen. The FO never ends a turn on "PR is blocked" without having either routed the
failure or dispatched something else.

**Independent work always exists while the milestone has open issues.** Triage holds no worktree
and takes no lock, so every issue not yet triaged can be triaged NOW, in parallel, up to the
stage's concurrency — waiting for a PR to merge before triaging the next issue serialises a stage
that has no reason to serialise. Only `implementation` and `review` are bound by the
one-in-flight-PR-per-`web/` constraint.

**Arm a watch before yielding.** When the next event genuinely is external — CI settling, a merge —
arm the runtime's monitor on it so the session is woken by the event rather than waiting on a
human to notice. Yield only with a watch armed AND no dispatchable work left, and say which watch
is armed.

**The end condition is the milestone, not the PR.** The burndown is done when every issue in the
milestone is `Done` or `Canceled` in Linear with its reconcile receipt posted — including issues
filed mid-milestone out of a deferred finding.

## The first officer commits in a worktree, never in the primary checkout

Given by the captain on 2026-09-17: "you can use worktrees in order to minimize any accidental
resets causing local destruction."

**The primary checkout is read-only for commits.** Every commit this session makes lands in a
worktree on a branch — the FO's own process-doc edits to this README included. New worktrees branch
from `origin/main`, not from local `main`:

```bash
git worktree add -b fo/{topic} .worktrees/fo-{topic} origin/main
```

The state checkout already works this way, which is why state commits have never put the code
branch at risk while FO commits on `main` did. What went wrong once, on 2026-09-17: seven FO
process-doc commits accumulated on local `main`, which is protected and cannot be pushed, so they
could neither land nor be discarded without a `reset` on a checkout holding someone else's
uncommitted work. They were recovered by moving them onto the in-flight PR's branch, and the
`reset --hard` that would have "cleaned up" was refused by a guardrail — the same operation
**AGENTS.md, "Parallel Work"** records as having destroyed a file here once.

Branching from `origin/main` is the half that prevents recurrence on its own: a worktree cut from a
local `main` that has drifted carries that drift into its pull request, where it reads as scope
nobody asked for.


### Do not run git inside another agent's worktree at all, even read-only

The first officer detached a live worktree's HEAD **twice in one day** — once mid-implementation,
recovered by the ensign with a tag, and once while verifying byte pins on a frozen integration
branch. The second time was after writing this rule down and quoting it at someone else.

So the rule is not "be careful in someone else's worktree". Care did not work. The rule is that a
first officer has no reason to be in one:

- To read a file at a commit: `git show <sha>:<path>` from the primary checkout. No worktree, no
  checkout, nothing to detach.
- To compute something over a tree: write the blob to a temporary file and work on that.
- To need a real checkout: `git worktree add /tmp/<name> <sha>`, which is yours and disposable.

`git checkout` inside a worktree another agent is working in is the one command that looks read-only
and is not. Both incidents recovered without loss, and both times the recovery was luck rather than
design: the first because the ensign read `[detached HEAD ...]` in output it had already skimmed
four times, the second because the branch ref, HEAD and origin all happened to be the same commit.
## Two branches implemented one ruling without coordination, and only one is safe

A captain's ruling said exactly one rule may assign a colour to `[data-next-withheld]`. Two branches
delivered it independently and neither knew the other had. DRC-4592 removed the competing
`--ink2` rule; DRC-4589 removed the guard rule that was beating it. Resolved through
`tests/css_cascade.py`'s `matches()` down a real element path, on four trees:

| tree | renders | winning selector |
|---|---|---|
| `origin/main` | `--ink3` | `.next-cockpit-scope-tree small[data-next-withheld]` (0,2,1) |
| DRC-4589 | **`--ink2`, the value ink** | `.next-cockpit-scope-tree small` (0,1,1) |
| DRC-4592 | `--ink3` | the bare `[data-next-withheld]` (0,1,0) |
| DRC-4595 | `--ink3` | the (0,2,1) guard |

So the three correct trees are correct for three different reasons, and only DRC-4592's is correct
on its own. DRC-4589's edit is not merely insufficient alone — once 4592 lands it is **redundant**,
because 4592 deletes the whole rule. An absence rendering in the value ink, on the branch whose
entire job is holding those inks apart.

The merge hazard is precise and no hunk conflicts: **take 4589's deletion of the guard while keeping
the `--ink2` rule from main, and the defect reappears on a tree where every side was green in
isolation.** Resolve the element path on the consolidated sheet; never infer it from each branch.

Four things this earned:

- **Run the falsifier, not just the verifier.** DRC-4589's AC-3 already contained the property — its
  *Falsified by* said "or the register resolving to anything other than `--ink3`". The implementer
  built the *Verified by* oracle, encoded that oracle as the test, and never ran the falsifier. The
  suite is green on a criterion whose own falsifier is tripped. This is sharper than an
  under-specified criterion and the fix is procedural: every criterion here carries both halves, and
  only one of them was being run.
- **Count-shaped criteria invite this.** "Exactly one rule colours it" is satisfied by the broken
  tree and the correct one alike. Write the criterion as the property a reader sees and verify it by
  resolving.
- **Verify a cascade property at the end of the integration**, not after the pick that raises it. The
  tree is legitimately wrong in between.
- **A cross-branch dependency that lives only in an agent's head is recorded nowhere.** Neither
  entity said so. Ask the author which it was — a dependency to write down, or a misread of which
  rule wins — because only one of those is a defect.

## A second fixture cannot fail on the surface nobody thought to add

A criterion's verifier was found not to reach a surface the same change had introduced. The obvious
repair is to add that surface to the fixture. It is the weaker one, and the reason generalises:
**the next surface is also not in the fixture.** Adding one closes the instance and leaves the class,
which is how the gap was created in the first place.

The stronger repair was already the house style and had simply not been applied here — one
neighbouring test walks every `.py`, `.js`, `.css` and `.html` under the runtime rather than naming
files, and the helper's own docstring makes the argument. The derived version of the failing check
came to about ten lines: sweep the emitted literals across every file, reject the ones that match,
**and assert the file count**, so a walk that reaches nothing cannot pass green.

That last clause is the part people leave out. A sweep with no subjects and a sweep with no
violations report the same thing, which is the vacuity failure recorded above in another costume.

**Adding one arm moves the gap rather than closing it.** The same round had a criterion promising a
cross-product of six branch combinations and exercising one. Adding a second arm would leave it
claiming six and exercising two — better, and still a criterion implying coverage it does not have.
The two honest answers are to assert across the whole cross-product, or to narrow the wording and say
what it covers. Silently covering more than before and less than promised is not one of them.

**Say the sweep's blind spot in its docstring.** The derived check above cannot see an href composed
through a template hole, because the helper splits literals at `${...}`. A derived instrument with an
unstated limit is how the next reader concludes it proves more than it does.

## A verdict carries a head move when nothing it depends on moved — including the code that asserts it

The crude question is *did the head move*. The useful one is **did it move anything my conditions
depend on**, and the hard half is enumerating the dependency set.

Measured here twice in one round. A guardrail verdict was carried forward on the reason "the
stylesheet is unchanged" — true, and too narrow: **three of its four conditions were assertions in a
test file the commit did touch**, not assertions about the stylesheet. The reviewer checked both
halves rather than accepting the carry, extracted the asserting class from both blobs, and found it
byte-identical. The verdict carried, now on a dependency set someone had actually enumerated.

> A condition's dependencies include the code that asserts it, not only the code it asserts about.

The other half of the same round: a verdict was correctly *not* carried, because the file its test
lived in had moved by 218 lines — and the reviewer that wrote it observed that "re-run, don't
re-derive" was right **only because the commit had not touched the classifier**, and would have been
wrong if it had.

Compare the thing, do not read the hunk headers. Byte-comparing an extracted class answers the
question; a diffstat naming the file does not.

## A baseline that errors invalidates every verdict in the round

A reviewer's first pass named the wrong test class and everything came back `errors=1` — including
the baseline. It discarded the entire round rather than read verdicts under it.

That is the same trap as a mutation that never applied, one layer up: **the baseline is an instrument
too**, and a broken one reports on nothing while producing output shaped exactly like results. Check
the baseline is clean before reading any verdict measured against it, and throw away the whole pass
if it is not — the individual results are not salvageable, because none of them measured what it
claims.

## A pre-registered contract cannot rest on line numbers

A reviewer pinned its re-check conditions into the entity files so they would survive its own session
ending — and the very next commit moved its anchors: an ordering test from 11119 to 11149, a fixture
from 7681 to 7682, a guard from 35 to 36. **A contract meant to survive a fix round cannot rest on
numbers that drift under it**, and the round it exists to check is precisely the round that moves
them.

Two repairs, both cheap:

- **Anchor on greppable strings**, not offsets — a test class name, a selector, a literal.
- **Mark measured offsets as re-measure-on-the-fix rather than compare-against-these.** An A/B
  baseline is evidence the property was real, not a value the fix must reproduce.

## Consolidating two blind readers makes one shared blindness, not a fix

Two readers of the same map were independently blind to a state. The right repair was to give them
one classifier to ask, and that repair is genuinely better: the remaining defect became one condition
in one function instead of two readers to keep in step.

But it converts two independent bugs into one shared bug, and the reviewer that spotted it drew the
warning worth keeping: **"the two readers now agree" must not be written as "the state is handled".**
The commit message framed the win as the two resolving one read, which a later reader can take as
coverage. Say what agrees and what is still open.

This is the same hazard as a comment asserting an invariant its own function violates — three of
those shipped in this milestone — except a commit message has a longer half-life and no one greps it
when the behaviour changes.

## Pre-register the re-check conditions before the fix exists

Two reviewers, waiting on a fix round, wrote down what they would accept **before** the fix was
written, and committed it. One said why in a sentence worth keeping: written afterwards, the
conditions can be shaped by the fix.

It paid immediately. The conditions named the trap the obvious repair was about to fall into — a
`.error` test placed inside a `!entry.data` branch, which is the natural place and does nothing,
because `!data` is *false* in exactly the state that is invisible. That reached the implementer as a
target rather than as a re-check failure, which is the difference between one CI round and two.

It also produced the more unusual discipline: **one reviewer recorded what would make its own plan
wrong.** If the fix dropped a storage mirror rather than keying it, two of its three conditions
dissolved — and it said so explicitly, rather than leaving a plan standing that could be used to
argue down a legitimate answer. A pre-registered condition that cannot be wrong is a preference
wearing a measurement's clothes.

Three properties make a pre-registered condition worth having:

- **It is falsifiable by the fix**, not just by the defect.
- **It names the shape that would pass it wrongly** — a fix that namespaces a write but resolves its
  fallback from the wrong scope passes "press A, open B" and fails "press B, re-open A", so the
  condition has to demand both directions.
- **It says what the fixture must be able to do**, not only what it must contain. A multi-project
  fixture is necessary and not sufficient while an existing test still seeds the collided value as
  its expected result.

## The fixture's shape hides what the assertion's strength cannot reach

The worst defect this milestone shipped was a `localStorage` key that collapsed to the same value for
every project, so one project's press rewrote every other project's tab and survived a reload. Both
of its oracles passed, and **one of them seeded the collided key as the expected value.**

The reviewer that found it drew the rule: **a defect needing two projects to be visible cannot be
found by mutating a one-project fixture, at any width and with any assertion.** Strengthening the
assertion would not have caught it. Only a second project does.

So when a criterion quantifies over instances of a thing — projects, sessions, tabs, panels — ask
whether the fixture contains **two** of that thing before asking whether the assertion is strong
enough. A single-instance fixture cannot express a collision, an ordering, or an interference, and no
amount of mutation testing over it will say so: every mutant dies or survives for reasons that have
nothing to do with the property.

An oracle that seeds the defect as its expected value is the end state of this. It is worse than
having no oracle, because it converts the defect into a documented requirement.

## A SURVIVED can also mean the run never loaded the test that kills it

A second false-SURVIVED cause, found the same day as the no-op one and its exact mirror. Three
mutations were reported as surviving; re-run against the full 564-test selection rather than a narrow
one, all three died — two killed board-wide by a module the narrow run never loaded.

So a survivor has three explanations, not two, and they need separating before it becomes a finding:

1. The oracle genuinely does not catch it.
2. **Nothing was mutated** — the substitution did not match the file.
3. **Nothing that catches it was run** — the selection was too narrow.

The reviewer withdrew all three findings and said plainly that the criticism narrowed to verifier
hygiene rather than an unguarded property. Withdrawing a finding costs nothing here; a fix round
spent closing a hole that was never open costs a CI cycle and a merge serialization.

## A map written only on settle cannot carry an in-flight marker; one written at request time can

Two shared maps in the same bundle produced opposite defects, and the difference is when they are
written, not how carefully.

`nextCockpitContexts` has every `.set` inside a `.then` or `.catch`, so an entry is only ever
replaced **on settle** and no in-flight marker is written onto a live entry. `projectTerminalBySession`
writes `{state:"registered", loading:true}` at **request** time, and that is the one that produced a
re-check flipping a working capability to unknown on every poll.

That is the property to state in the comment on any shared map: **which discipline it keeps.** It
tells the next writer what they may not do, where a comment describing the current readers goes stale
the first time a reader is added.

The two defects those maps produced are worth naming as a pair, because they are the same family
pointing opposite ways. **One called a working capability unknown. The other called a failed read
fine.** The second is worse, because it is silent — the first at least shows a reader something has
gone wrong, while the second renders a stale answer identically to a fresh one.

Three reviewers found the second independently, by three different routes: a reader keying off the
wrong field, a writer's merge semantics, and the writers disagreeing on their field sets. None had
seen another's work. Where two agreeing can still be one layer short — as happened here on the merge
semantics — three arriving separately is what makes a finding safe to act on without re-deriving it.

## Asserting a class is emitted says nothing about whether the class is styled

The obvious test for a new render variant is to assert its class name appears in the output. It is
worthless, and worse than worthless here, because of what an unstyled variant inherits.

Measured while fixing a cue that reported a failed read as still pending: **deleting the new
variant's CSS rule entirely left the whole cockpit module green.** Only the byte pins reddened — and
those fire on any stylesheet edit, so they are evidence of nothing. An unstyled variant falls back to
its base rule's ink, which on this board is `--ink2`, the **value** ink. So a stated absence would
render exactly as loudly as the figure it replaces: the milestone's central defect, reintroduced by
the guard that was supposed to prevent it.

The repair is the same shape as every other oracle repair here. **Derive the variants from the
producer and resolve each through the cascade against the unstyled base**, rather than asserting a
string appears. Doing it that way also caught a second, pre-existing variant that had been equally
unguarded — which an assertion naming the new class by hand could not have reached.

The general form: **a name is not a property.** A test that checks a class, an attribute or an id is
present has checked that an emitter ran. Whether anything downstream honours it is a different
question, and on a cascading medium the default answer is that it does not — it inherits something,
and what it inherits is usually the thing the variant exists to differ from.

## A criterion number is not a search key, and its falsifier may have more than one arm

**Two rules, and the first officer got the second one wrong twice before measuring it.**

**Ten issues in this burndown each carry an AC-3.** A bare criterion number is ambiguous ten ways, so
it must never be the key you search on, and a criterion must be cited as `DRC-NNNN AC-N` in messages,
test docstrings and commit messages alike.

**But ambiguity was not what went wrong here.** The first officer grepped for a criterion number,
found a matching assertion, declared the criterion closed, and overruled a reviewer that had executed
the falsifier at four heads. Then, correcting that, diagnosed it as two issues sharing a number. The
reviewer measured again: the test was the right issue's, in the right class, with the right criterion
in its docstring. **The conflation was inside one criterion, between two manifestations of its own
falsifier.**

Deleting the guard produces an empty paragraph two ways: inside a disclosure when the caller passes a
summary, and bare when it does not. The assertion aimed at the first. With the guard deleted the tab
rendered **one bare empty paragraph and zero empty disclosure bodies** — so the assertion is genuine,
and simply **unfalsifiable by that mutation**, because the caller it watches always passes a non-empty
body and the guarded branch never fires there.

Three things follow:

- **A falsifier can have arms, and covering one is not covering the criterion.** Ask which callers
  reach the guarded branch before deciding an assertion covers it.
- **State an acceptance by shape, not by number.** "Add an empty-body assertion" would have landed on
  the disclosure again and survived a fifth head. "A behavioural test must red on the no-summary arm"
  cannot be satisfied the wrong way.
- **A correction is a claim and owes the same proof as the finding.** Both of the first officer's
  attempts here were reasoned from reading; both were wrong; the reviewer measured each time and was
  right each time.

## Know which facts entail which, because a contradiction is free to catch

A relayed message said, in the same breath, "no runtime file moved" and "the pins moved again". Those
cannot both be true: the assembled page cannot change when nothing it assembles has. **The reader
caught it without measuring anything** — the message refuted itself.

That is a cheaper class of error than a stale figure, and worth engineering for. Where a stale figure
costs a re-derivation to catch, an internally inconsistent one costs a moment's thought. **If A
entails B, then observing A tells you for free whether a claimed not-B is wrong.**

Four pairs worth holding in mind here, each of which makes a class of relay error catchable without
measurement:

- no runtime file changed → the assembled pin is unchanged
- the assembled digest changed → some part or `styles.css` changed
- CI is green on head H → those checks belong to H
- **a mutant was killed → the mutation applied**

The fourth does quiet work throughout. It also **derives** the survivors-owe-a-proof rule recorded
above rather than leaving it as a separate fact: "killed" entails "applied", because a no-op cannot
change behaviour against a green baseline — so a red carries its own proof and only a survivor is
ambiguous.

## A per-case assertion cannot detect that the cases are the same case

A six-case matrix collapsed twice. The first time it exercised one arm. The second time — in the
repair — it exercised **six copies of one arm**, because a stub returned an object without the method
the probe requires, so every case drew the same branch.

Both times the per-case guards passed, and they were correctly written: they asserted that the anchor
and both rows rendered, and those render on *every* branch. **Guarding each case cannot see that the
cases are identical.** The cardinality is a separate property and needs a separate assertion — here,
asserting the six shapes *differ*, which now reds with `6 != 2` when the broken stub is restored.

This sits beside *a name is not a property* as the same kind of gap: something the test never asked
about, because the thing it did ask about was true.

## Ask what a check would report if it were disconnected from the thing it tests

This is the general form of most of what this milestone found, and the sections below it are
instances rather than separate rules. It is `AGENTS.md`'s first Measured Invariant — *ask what the
figure reads when nothing happened, and whether that differs from the figure when something happened
and found nothing* — aimed one layer out, at the instrument instead of the data:

> **What would this check report if it were disconnected from the thing it tests?** If that answer is
> identical to its passing output, the check proves nothing.

It does not matter how the disconnection happened. A mutation whose pattern never matched the file. A
mutation that matched the wrong thing — a pinned fragment's capitalisation rather than the prose. A
test whose class lacked the fixtures it needed. A one-project fixture that cannot express a
collision. A sample taken four microtasks after the reply had already landed. In every case the
instrument reported on something other than the subject, **and said so in exactly the words it would
have used if it had worked.**

The framing earns its place by telling you what to *do*, where the taxonomy only says what to avoid.
**Disconnect the check deliberately and confirm it still reports.**

- For a mutation: that is the substitution proof — grep the token, or better, watch the rendered
  property move.
- For a timing-sensitive test: run it against unmutated code at the same sample point. If it passes
  there too, the sample point is the subject, not the code.
- For a fixture: ask what it would print with the defect made impossible. A one-project fixture
  prints the same thing either way, which is why no assertion over it could have caught a
  cross-project collision.

It also explains cleanly why survivors and reds divide the way they do. **A red reports a
*difference*, and a disconnected instrument cannot produce one.** Only a claim of *sameness* is
ambiguous between "nothing differs" and "nothing was measured" — which is why a survivor owes a
proof and a red does not.

**The same failure appears at two scales, and a reviewer named the pair after committing one of
them.** A six-case matrix collapsed because six cases silently became one. A reported measurement
collapsed because one reading silently spanned three heads. Both are a claim covering more than was
measured, and both read as evidence — the matrix because every case passed its own guard, the
measurement because it was true when taken.

What distinguished the things that survived the churn from the things that did not, in that
reviewer's own words: the contracts held because they were **string-anchored and re-run on every
head**; the claim did not, because it was **neither**. That is the test. Not how carefully something
was written, but whether it is re-derived when the ground moves.

## A mutation that does not match the file's text is a no-op, and reads as SURVIVED

A falsifier survived a set-equality assertion it should have killed. The oracle was fine: the `perl`
substitution had not matched the file's actual line wrapping, so nothing was mutated and the test
passed because nothing had changed.

It was caught only because the survival was **too convenient to believe**. That is the part worth
recording, because it does not generalise: a mutant whose survival looked *reasonable* would have
been written down as "not detected by this oracle", and a working oracle would have been rewritten
or reported as toothless.

So the check is mechanical rather than a matter of judgement. **Before trusting a SURVIVED result,
grep for the mutated string and assert the count changed.** Confirm the substitution applied, then
read the verdict.

**The check applies to SURVIVED, not to RED**, and the asymmetry is worth stating as *why* rather
than as a rule to remember. **A red is self-proving: it reports a behaviour change, and a no-op
cannot produce one against a green baseline.** A survivor reports an *absence* of change — and
"nothing changed because the oracle is blind" and "nothing changed because nothing was mutated" are
the same observation until someone goes and looks. That is the entire rule, and it is why only a
survivor owes a substitution proof. Bounding it this way matters, because a rule applied to every mutation doubles
the cost of a pass that is mostly reds.

**And a grep is not always sufficient proof.** The strongest version confirms the mutant reached the
*thing under test*, not merely the file: one repair here proved old-string 1→0 and new-string 0→1
**and** that the resolved ink moved `var(--ink-label)` → `var(--ink-caption)` down a real element
path. The text changed, the rendered property changed, and 319 tests still passed — which is what
makes the surviving oracle a genuine finding rather than a possible miss.

This is the same family as a test that landed in a class without its fixtures and read green twice:
in both, the thing under test was never reached, and the result says nothing about the oracle. A
SURVIVED reported as a finding is a claim about an oracle, and if the mutation silently failed it is
a defect report about code that has no defect — which will read convincingly, because a clean run
with a plausible explanation always does.

## A mutation check that includes the byte-pin oracles measures nothing

DRC-4592 mutation-checked four assertions and reported all four killed. Re-running with the byte-pin
tests excluded, the real answer was different: the pin test fires on **any** stylesheet edit, so it
reports "killed" for every mutation and says nothing about whether the semantic oracle works.

Exclude `test_next_page`, `test_next_flag` and `test_focus` from every mutation check on a stylesheet
change, or "killed" means only that the file changed.

The same run produced the other half of the rule. A surviving assertion can be stronger or weaker
than the one it replaces, and only a mutation says which: three cue tuples were confirmed droppable
because the surviving test killed all three planted mutations and is strictly stronger, while a
title/meta tuple that looked equally redundant turned out to be the only thing catching `--fs-2xs`
being redefined above `--fs-sm` in `:root` — the surviving assertions pin which *token* each half
uses and cannot see the token move underneath them.

## A count passes a compensating swap

`assertEqual(70, len(above))` over a sentence-tier census reds when a rule leaves the tier, and reds
when one leaves for a lower tier. It **passes** when one rule leaves and another joins at the same
size. DRC-4589 moving `.next-cockpit-authority>span` off the tier while `>small` joins it is exactly
that swap, so the integration carrying both is the case that walks through the hole, and the oracle
would be green on the change that defeats it.

Repairing an oracle that the merge itself defeats is not a promoted finding, and the no-promotion
rule does not apply to it.

**Assert the set and the count, not one of them.** "Compare the set rather than its length" was the
first answer here and it is half of one: two selectors in this census are declared twice, so the
collection held 61 entries across 60 distinct selectors, and a set alone silently loses that
duplicate. The set catches the compensating swap; the count catches a duplicate appearing or
vanishing. **Neither is a superset of the other** — that is the whole reason, and without it the
next reader will reasonably simplify the pair back to one. A set cannot see a duplicate appear or
vanish because it collapses them; a count cannot see a swap because the total does not move. Either
alone is an oracle with a hole in it that nobody will look for again, because the first hole is
closed and the assertion reads thorough.

## Report the measurement you took, not the one you meant to take

The divergence between two bases was reported here as 333 insertions across four test files. It is
399 across seven paths, and the seven include `styles.css` and a whole file that exists on one side
and not the other. The figure came from a `git diff --stat` scoped to one directory, read from a
truncated tail, and then stated as the total. The integrator re-measured and corrected it.

Nothing about the conclusion changed, which is why it survived being wrong: a scoped measurement
that happens to support the right answer is the easiest kind to ship. State the scope in the same
sentence as the figure, and read the summary line rather than the tail.

## One pull request per conflict surface, not one per branch

Four branches were queued to land one at a time, each rebased onto the previous merge. All four
rewrite `compass_runtime/web/styles.css` and all four move the same three byte-pin oracles, so that
plan resolves the same conflict four times against a file moving underneath each resolution — the
"each side is correct for a tree that no longer exists" failure `AGENTS.md` already names. They were
consolidated into one integration instead: one resolution with all four intents visible, one pin
regeneration, one CI cycle, one review.

`AGENTS.md`'s **Calibrating Effort** already says the only constraint that genuinely forces a split
is that exactly one pull request may touch `compass_runtime/web/`. Read that as an instruction to
**combine**, not merely as a limit to respect. Branches that share the forcing surface belong in one
pull request; the split was costing four merge serializations to avoid one conflict resolution.

Deriving the integration is where the work is, and it is not the same as merging the branches.
Verify, do not assume:

- **Which commits are actually unique.** Three of the four branches carried a dozen commits already
  on main under different SHAs, from a squash merge. Merging them would have re-resolved all of it;
  cherry-picking the six unique commits did not.
- **That the shared base is the base that merged.** Three branches sat on `2a07380` and one on
  `1d847b0`. The two carry the same commit message and are not the same tree — they differ by
  roughly 333 insertions across four test files, and `1d847b0` is the one that merged. Every byte pin
  on those three branches was therefore correct for a tree that never landed. Regenerate from the
  assets; never resolve a pin textually.
- **That a squash leaves no ancestry.** After a squash merge the branch tip is not an ancestor of
  main, so an ancestry check reads as "not merged" on work that is fully landed. Verify by content.

Order the picks largest-delta-first on the shared file, so the later ones resolve against the fuller
sheet once instead of twice. Keep the implementers alive through the integration and ask them what a
hunk was for: three sent unprompted dossiers of load-bearing constraints that no diff shows, and the
one contradiction between them was the finding above.

## A dead worker still holds its pane

Five workers killed by a usage limit stayed on the roster and kept their tmux panes. The next
dispatch failed with `fork failed: Device not configured` — read as a spawn problem, when the cause
was five processes that had already stopped doing anything. `ListAgents` shows them as ordinary
teammates; nothing distinguishes a dead one from a busy one.

Reap before dispatching replacements. `TaskStop` takes the qualified `name@session` form, not the
` [ref]` suffix a listing prints — passing the ref fails with "No task found" and lists the running
teammates, which is the form to copy from.

And check for durable output before re-dispatching: of four triages killed mid-flight, one had
committed 25KB of work to its entity and another had committed nothing. A replacement told to start
over discards the first; a replacement told to read the tree first does not.

## The launcher's help cannot tell you whether a subcommand exists

`spacedock state commit <slug> --workflow-dir <dir>` works, and has been run dozens of times here.
`spacedock state --help` lists only `init`. An ensign checked the help, correctly concluded the
command was not there, and hand-rolled the path-scoped `git add`/`git commit` substitute instead.

Probing further makes it worse rather than better. `state commit --help` does not error: it falls
through and prints the **top-level** help at exit 0. So does `state --help`. So does
`state notarealsubcommand --help`. A real-but-undocumented subcommand and an invented one produce
byte-identical output and the same exit code, so the help cannot distinguish them **in either
direction** — an agent that does the right thing and reads it gets a confident, well-formed answer
that is wrong.

Two consequences for a dispatch:

- **Name the launcher commands a stage needs, and say they are verified.** A worker that meets an
  undocumented one will otherwise either hand-roll a substitute, which is fine, or skip the step,
  which is not.
- **Do not ask a worker to probe an unknown state subcommand to find out.** The state checkout is one
  shared index with sibling writers mid-flight, and a command whose staging behaviour is unknown is
  how somebody else's staged entity gets swept into your commit. The ensign here declined to probe
  for exactly that reason and was right to.

## Never pin a SHA or a figure table into a brief for a branch still moving

Four reviewers were dispatched against an integration branch with its head SHA and its five
regenerated byte pins written into their assignments. The integrator committed once more while they
were starting, so all four were reviewing a superseded tree against pins that were ten bytes wrong,
and would have reported a clean result about a tree nobody was going to merge.

The same error had already been made twice that day in different clothes: a dispatch base derived
before a pull request merged, which three triages caught and re-derived; and a divergence figure
measured with a path scope and then stated as a total. All three are one mistake — **a figure
handed on without the moment it was true**.

The fix is to hand over the derivation rather than the answer. A brief says:

- **Derive the head yourself when you start**, from the branch tip or the pull request's
  `headRefOid`, whichever is later. Never take a SHA from a brief.
- **Re-derive every byte pin from the assets**, and compare against no list at all — including a
  corrected one, because a list in a message is a claim about a minute ago.
- **Re-check the head immediately before writing a verdict, and state which SHA was reviewed.** If
  it moved underneath, say so rather than quietly re-running.

A worker reviewing an in-flight branch also needs somewhere to stand. An unpushed commit is still a
valid object in the shared store, so `git worktree add /tmp/review-<slug> <sha>` works without
touching the branch's own worktree — which stays off limits, along with every frozen branch, because
those are the only copy of that work if any of it has to be redone.

The general form: **holding a push to finish one small confirmation costs more than the confirmation
is worth** once anyone else is reading the branch. Push, let the gate run, and land the answer as a
follow-up commit.

## A criterion's wording and its verifier are written at different moments

An implementer audited its own fourteen criteria after a reviewer found one that was green over a
defect, and reported the structural reason rather than an apology:

> I wrote each criterion's wording and its verifier at different moments and never diffed one
> against the other. The wording reaches for the property a user cares about, which is naturally
> universal. The verifier reaches for what is cheap to assert, which is naturally a list. Nothing
> forced me to reconcile them, and the gate reads the bullet rather than the test.

The audit found **four** universal-worded criteria on enumerated verifiers, not the one the reviewer
had found, and the widest was the criterion its whole issue turns on: "every caveat sentence that
exists on the pre-change tree still exists verbatim", quantifying over roughly twenty-three emission
sites with five strings in the test. "Nothing is deleted" verified over a fifth of the set.

So: **ask of every criterion whether its wording is universal while its verifier is an enumeration**,
and sort the answers into three, not two.

1. Universal wording, universal verifier.
2. **Enumerated wording, enumerated verifier** — fine, and the honest form. One criterion in that
   set is the pattern: it states it is interactive, says it is deliberately not automated, and names
   the condition under which it should become offline.
3. Universal wording, enumerated verifier — the defect.

Category 3 is not automatically a blocker. This milestone has knowingly accepted universal-sounding
criteria on enumerated verifiers and filed the remainder as its own issue; two issues exist only
because of that. What is not acceptable is the criterion implying coverage silently, so the fix is
sometimes to widen the verifier and sometimes to narrow the wording, and which one is a judgement
about cost.

**A frozen list can be a derivation rather than an enumeration, and the difference is reproducibility.**
Widening the worst of the four meant listing every string on a fixed pre-change tree, which looks
like a longer enumeration. It is not, provided the test records the base revision and the exact
command that extracted the set, and says the list is a derivation from that revision rather than a
selection from it. A reader who re-runs the command gets the same set; that is what an enumeration
cannot offer.

**Two smaller shapes from the same audit.** A criterion can be half-covered — one whose two halves
had different verifiers, genuinely universal on one and resting on a single fixture on the other,
read as though both were covered; the fix was to say which half is which, not to build a second
checker. And a list-shaped verifier can fail *twice* over the same gap: an omitted item was both
absent from the list and invisible to the filter the list was passed through, which is why that form
cannot be patched by adding an item.

**Check which verifier a criterion declares, not which test you remember writing.** One criterion in
the audit was expected to be a gap and was not: its declared verifier was a different class from the
one its author had in mind, and that class covered the whole set. The author checked before claiming
it.

## Workflow State

View the workflow overview:

```bash
spacedock status --workflow-dir docs/roadmap-burndown
```

Output columns: ID, SLUG, STATUS, TITLE, SCORE, SOURCE.

Find dispatchable issues ready for their next stage:

```bash
spacedock status --workflow-dir docs/roadmap-burndown --next
```

### Restoring a fresh clone

Two things in this directory are deliberately **not** in git, and a clone needs both before the
workflow runs.

**The mod.** `_mods/pr-merge.md` is vendored from the Spacedock plugin at install time. Restore it
with:

```bash
mkdir -p docs/roadmap-burndown/_mods
cp "$(dirname "$(dirname "$(command -v spacedock)")")"/../mods/pr-merge.md docs/roadmap-burndown/_mods/ \
  2>/dev/null || cp ~/.claude/plugins/cache/spacedock/spacedock/*/mods/pr-merge.md docs/roadmap-burndown/_mods/
```

It is ignored rather than committed for two reasons, and the second is the load-bearing one. A
committed copy is a fork of the plugin's own file that drifts silently the moment the plugin
updates. And it **fails this repository's documentation gate**: `scripts/validate_plugins.py`
rglobs `docs/**/*.md` and reads the mod's template placeholders — `/{state-owner}/{state-repo}/…` —
as relative links escaping the repository. Editing a file the first officer executes from, in order
to satisfy a linter, is the wrong trade.

**A known divergence follows from that, and it is a papercut worth fixing.** The validator rglobs the
**working tree**, not the git index, so once the mod is restored `python3 scripts/validate_plugins.py`
reports two errors locally against a file that is not in the repository. **CI is unaffected** — it
checks out committed files only, and the mod is not one. But AGENTS.md tells contributors to run that
validator before opening a PR, and a gate that cries wolf locally is one people learn to skip.

The real fix is to move this workflow out of `docs/` entirely — the directory is machinery rather than
documentation, and the validator's `docs/**` rglob is only reaching it because of where it was placed
at commission time. That move touches a linked worktree and a live entity, so it is deliberately not
done here. **Filed as the next housekeeping task on this workflow.** Until then, the honest local
check is to run the validator against a clean export of the committed tree:

```bash
T=$(mktemp -d) && git archive HEAD | tar -x -C "$T" && (cd "$T" && python3 scripts/validate_plugins.py)
```

**The state.** Entity state lives on the `spacedock-state/roadmap-burndown` orphan branch, checked
out as a linked worktree at `docs/roadmap-burndown/.spacedock-state/`. Stage transitions commit there and never
touch the code branch. On a fresh clone, run `spacedock state init` to fetch the branch and re-add
the worktree.

## Issue Template

```yaml
---
id:
title: The Linear issue title, verbatim
status: selection
source: https://linear.app/recce/issue/DRC-XXXX/...
started:
completed:
verdict:
score:
worktree:
issue:
pr:
mod-block:
linear-status:
milestone:
release:
promise:
move:
estimate:
reconciled:
---

One line on what this issue is, from Linear. The authoritative body lives in Linear; `triage`
fetches it live and writes the sharpened version back there.

## User value

{Triage: two sentences. Who notices this and when in their day. Then the promise ID and the move,
per [development tracking](../development-tracking.md#how-work-links-to-a-promise). When the move is `none`, why no user sees it.}

## Problem

{Triage: what is broken or missing, why it matters now, and what a fix must cover — checked against
the current codebase, not restated from the issue.}

## Proposed approach

{Triage: the direction chosen, and the simplest alternative rejected with the reason it cannot
deliver the value.}

## Linear edits made

{Triage, before any Linear write: the original issue body and owning milestone description copied
verbatim, then the drafted rewrite of each. The gate compares them and authorizes the write;
`implementation` performs it as its first action. This section is both the restore point and the
audit trail.}

## Expected surface and tolerance

Estimate: {+NNN} net LOC across {M} files, tolerance {±NN%}.
Semantics this may change: {command grammar, stored formats, authority, runtime behavior, or `none`}.

## Acceptance criteria

Each AC names a property of the finished change (not a stage action) and how it is verified. Mark
each **offline** or **interactive**.

**AC-1 — {End-state property.}** (offline)
Verified by: {test name / command output or exit code / file the change produces / resulting on-disk
state — something outside this entity body that a future reader can reproduce and that can fail.}
Falsified by: {the concrete change that would make this evidence fail.}

## Test plan

{What tests verify the implementation, estimated cost, whether E2E is needed.}

## Review depth

{Review: the depth chosen from AGENTS.md's Calibrating Effort table, and the property of the diff
that justified it.}

### Feedback Cycles

{First officer appends one `- Cycle {N}: ...` line per correction round; the review gate reads
findings from here.}

## Out of scope

{What this issue deliberately does not address.}
```

## Commit Discipline

- Commit status changes at dispatch and merge boundaries
- Commit issue body updates when substantive
- Implementation commits land on the worktree branch, DCO signed off; merge to `main` happens via
  the `pr-merge` mod after the review gate
- Entity state commits land on the state orphan branch, never on the code branch
