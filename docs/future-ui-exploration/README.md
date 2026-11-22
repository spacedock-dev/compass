---
commissioned-by: spacedock@0.27.2
entity-type: design_experiment
entity-label: experiment
entity-label-plural: experiments
id-style: slug
state: .spacedock-state
stages:
  defaults:
    worktree: false
    concurrency: 1
    model: sonnet
  states:
    - name: framing
      initial: true
      gate: true
      model: fable
    - name: reconnaissance
      model: sonnet
    - name: prototyping
      model: opus
    - name: crucible
      fresh: true
      gate: true
      model: opus
      feedback-to: prototyping
    - name: accepted
      terminal: true
  transitions:
    - from: crucible
      to: prototyping
      label: evidence supports the direction but exposes a material correction
    - from: crucible
      to: framing
      label: evidence invalidates the underlying interaction or information model
    - from: crucible
      to: accepted
      label: captain and first officer judge the direction genuinely strong
---

# Future UI exploration

This workflow explores bold ways for Compass to give people a straightforward understanding of what is happening across all of their harnesses and sessions. It treats the Next UI as a command surface rather than an inventory: the overall situation, the work that matters now, current execution, the next action, and captain responsibility must lead; evidence and detail remain reachable without competing with those facts.

The durable integration branch is `feat/future-ui`. Ordinary experiment work, product checkpoints, and accepted corrections stay on that branch. A captain may explicitly approve a promotion PR from `feat/future-ui` to `main`. That promotion does not retire, merge away, or change the role of the experiment branch.

## File naming

Each experiment lives in a folder named with a lowercase, hyphenated slug. Its canonical state file is `index.md`; screenshots, review briefs, and comparison artifacts may live beside it when the experiment needs them.

## Schema

Every experiment has YAML frontmatter with the following fields.

| Field | Type | Description |
|---|---|---|
| `id` | string | Blank for `id-style: slug`; the slug is the durable identity. |
| `title` | string | Human-readable experiment name. |
| `status` | enum | One of `framing`, `reconnaissance`, `prototyping`, `crucible`, or `accepted`. |
| `source` | string | The request, debrief, observation, or prior round that produced the experiment. |
| `started` | ISO 8601 | When active work began. |
| `completed` | ISO 8601 | When the captain accepts the direction. |
| `verdict` | enum | `PASSED` only after the captain accepts the direction. |
| `score` | number | Optional priority from 0.0 to 1.0. |
| `worktree` | string | The dedicated checkout used after the experiment reaches a product-changing stage. |
| `issue` | string | Optional GitHub issue reference. |
| `pr` | string | Optional PR reference. Ordinary workflow PRs target `feat/future-ui`; a PR to `main` requires explicit captain approval. |

## Stages

**Model routing.** Each stage names the model its ensign runs on, so the First Officer's own model is not inherited by every worker. `framing` is where the design judgment lives and runs on Fable. `reconnaissance` surveys and runs on Sonnet. `prototyping` and `crucible` build and test the artifacts and run on Opus. A model change between stages forces a fresh dispatch at that boundary; `crucible` is already `fresh: true`. Values come from Spacedock's Claude-host enum (`sonnet`, `opus`, `haiku`, `fable`); other hosts ignore the field.

### `framing`

The experiment is in framing while the crew turns the underlying ask into a bold, falsifiable design bet without assuming the current dashboard structure should survive.

- Inputs include the 2026-08-27 project-cockpit debrief, the current `?next=true` UI, captain direction, available design records, and known source limitations.
- Outputs include a concise bet, which of the five questions in [the development tracking taxonomy](../development-tracking.md#how-work-links-to-a-promise) it answers by ID and which move the bet would be, the command-risk baseline, explicit non-goals, and evidence that would invalidate the model rather than merely suggest polish.
- A good frame attacks the information or interaction model, names what should lead, and permits a materially different UI.
- A bad frame treats the work as incremental cleanup, preserves existing regions by default, or defines success as visual preference.
- The gate shows the bet, why it could improve comprehension, what it risks, how it will be falsified, and what the three harnesses must exercise.

### `reconnaissance`

The experiment is in reconnaissance while Codex, Claude Code, and AGY generate and inspect real activity against the current Next UI.

- Inputs include the approved frame, the live dashboard at `http://127.0.0.1:4553/?next=true`, exact session identities, live APIs, relevant source, and the registered interaction origins available to each harness.
- Outputs include one observed session from each harness, screenshots of the project overview and a session drill-down, a fact-versus-inference inventory, and findings ranked by comprehension or command risk.
- Good reconnaissance gives each harness distinct observable evidence, keeps missing sources explicit, and distinguishes UI failure from unavailable underlying data.
- Bad reconnaissance relies on mocks, reviews a static screenshot without live state, lets reviewer-created activity replace the session under study, or treats an empty signal as proof that no captain action exists.

### `prototyping`

The experiment is in prototyping while the crew implements the strongest candidate on `feat/future-ui`, starting from the accepted checkpoint of the prior round.

- Inputs include the approved frame, reconnaissance evidence, current branch bytes, prior crucible findings, and the repository's frontend byte-pin contract.
- Outputs include a coherent candidate at `?next=true`, one durable checkpoint per accepted correction, focused tests, updated byte pins derived from assembled assets, and before/after captures tied to exact candidate bytes.
- Good prototyping permits large structural bets, makes the lede legible in a five-second scan, gives project overview and session detail different jobs, and keeps semantic claims source-bound.
- Bad prototyping adds panels instead of choosing priority, buries command truth under provenance, implies causal links the data does not establish, changes unrelated shipped UI, or runs competing full suites in parallel.

### `crucible`

The experiment is in crucible while fresh reviewers try to disprove that the candidate gives users a truthful, immediate understanding of all harnesses and sessions.

- Inputs include the live candidate, fresh screenshots, current APIs, source and renderer fixtures, exact three-harness session evidence, focused test results, and every unresolved finding from the prior round.
- Outputs include independent reviews of visual hierarchy, information architecture, command truth, cross-harness comprehension, session detail, accessibility, and adversarial states. They also include reproduced material findings, a disposition for every finding, and a recommendation to revise, reframe, or accept.
- Good crucible review uses fresh reviewers, exercises each material claim where it can fail, implements accepted findings before another review, and resolves disagreement with reproduced evidence.
- Bad crucible review becomes attached to the prior design, ranks unsupported findings by confidence, optimizes style after command truth is complete, or claims convergence because tests are green.
- The gate leads with the recommendation. It shows whether a person can quickly answer overall situation, current assignment, execution state, current activity, next action, and captain responsibility. It also shows the promise the bet serves, in the promise map's words. It names every material uncertainty and its owner, then asks the captain to revise, reframe, or accept.

### `accepted`

The experiment is accepted only when the captain and first officer both judge the direction genuinely strong. Acceptance records the exploration outcome on `feat/future-ui`. It does not by itself authorize a promotion to `main`; the captain must approve that separately and explicitly.

- Inputs include a captain-approved crucible verdict and the exact accepted branch checkpoint.
- Outputs include a terminal record linking the accepted checkpoint, evidence, known limits, and remaining product decisions.
- A good accepted result satisfies the comprehension outcome and preserves honest scope and provenance.
- A bad acceptance terminalizes because a schedule expired, a fixed iteration count was reached, or reviewers ran out of findings.

## Review package

The [dashboard UI design record](../design-next-ui.md) explains the earlier board decisions. The
[Calm Compass record](../design-calm-compass.md) governs the redesign and its
[screenshot evidence policy](../design-calm-compass.md#screenshot-evidence-policy). For a walkthrough,
open the [Sample session](../../sample-session/README.md). Live stage reports and correction history
remain in the split-root Spacedock state checkout.

## Workflow-specific rules

- `feat/future-ui` is the durable product branch this workflow advances. Product commits and accepted correction checkpoints remain there. Routine workflow PRs target that branch. Only an explicit captain decision may promote an approved checkpoint from `feat/future-ui` to `main`, and the branch remains independent afterward.
- The pilot is one rolling experiment so all work touching `compass_runtime/web/next/` stays on one conflict surface. New hypotheses become recorded rounds inside the experiment unless the captain commissions another independent direction.
- Large bets are in scope. A round may replace the information architecture, navigation model, visual hierarchy, or session interaction model. Compatibility with the current Next layout is not a value criterion.
- The primary frame must expose assignment, execution, next action, and captain state without opening Evidence. It must also make project scope and current session activity obvious. Once those facts are truthful and unmistakable, another round needs a material comprehension risk rather than a style preference.
- Reconnaissance and crucible must include observed Codex, Claude Code, and AGY sessions. A harness that cannot produce evidence is reported as a source limit, never replaced by a mock.
- A fresh antagonistic review follows every accepted correction. Each round begins from the prior accepted checkpoint. Concurrent product edits are forbidden, while independent read-only lenses may run in parallel.
- Screenshots establish hierarchy, live APIs and source establish semantic claims, adversarial fixtures test missing or conflicting data, and focused tests protect behavior. A prose assertion cannot prove runtime comprehension.
- Check sibling worktrees before trusting failures. Run the full suite once and serialize it. Retry known load-sensitive modules alone before classifying a failure as a regression.

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

## Workflow state

View the workflow with:

```bash
spacedock status --workflow-dir docs/future-ui-exploration
```

## Experiment template

```yaml
---
id:
title: Experiment name
status: framing
source:
started:
completed:
verdict:
score:
worktree:
issue:
pr:
---

## Design bet

A bold, falsifiable claim about how Compass can make cross-harness and session state easier to understand.

## User questions

Which of the promise map's five questions this bet answers, by ID, and which move it would be.

## Baseline and command risk

What users can and cannot understand today, with reproducible evidence.

## Method

How Codex, Claude Code, and AGY will exercise the candidate and how fresh antagonistic review will challenge it.

## Acceptance criteria

Each criterion names a user-visible property of the finished command surface and a check outside this file that can fail.

## Iteration record

One entry per implemented and reviewed checkpoint: hypothesis, evidence, correction, disposition, and exact branch commit.

## Known limits

Sources or authority the UI cannot honestly recover.

## Out of scope

What this experiment deliberately does not attempt.
```

## Commit discipline

- Commit workflow-state changes at dispatch and gate boundaries.
- Commit each accepted product correction on `feat/future-ui` before the next antagonistic review.
- Keep ordinary workflow PRs and merges on `feat/future-ui`.
- Create a promotion PR from `feat/future-ui` to `main` only after the captain explicitly approves that checkpoint. The promotion does not close the branch or move future experiment work to `main`.
