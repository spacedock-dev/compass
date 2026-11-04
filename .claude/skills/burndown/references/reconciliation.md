# Reconcile landings and finish the scope

## 6. Reconcile every issue that landed

Only once the merge is confirmed on `origin/main`, reconcile once per finished issue in dependency
order, using the selected adapter's **Reconcile** section. Its receipt records the delivered
criteria, the PR and merge commit, verification, remaining scope, dependent work and any contract
wording changes. Read back tracker writes and relations. A partially delivered issue remains open.
A research or Verification issue may close on its findings/verdict as the planning rules allow.

## 7. Next landing, or close the milestone

Tear down what the landing finished, scoped to what this run started: its review servers, worktrees
(before their branches), and subagents. Keep the stack's worktree until the whole stack has merged.
Never bind, stop or kill a dashboard the run did not start.

Then refetch the milestone (issues move outside this session), recompute the plan, and continue. A
changed plan needs approval as the Invocation section sets out.

**Discoveries.** Use the selected adapter to file a defect this scope's work created, or a gap a
review deferred, in the current scope with a blocking dependency to the Verification issue (not an
owner-gated one; with none, no edge). Burn it in this run while the run is inside its estimate.
A small fix may ride the next open layer instead. Group a review's minor deferred items into one
issue rather than one each.
When burning the discoveries would take the run past its estimate, stop and ask, with the
discoveries grouped and sized, before starting them: reviews of new work keep finding more, so
"burn every discovery" has no natural end. A pre-existing defect is filed outside the current
scope using the adapter's discovery rules, and the report names it.

**The Verification issues run last,** once every other milestone issue is finished, on a live board
built from `origin/main`. Each closes on its verdict comment, since a clean walk has no pull request.
Each defect one finds is fixed or filed as above. An owner-gated one is handed to the owner, not
walked.

**The scope is complete** when every planned issue has a verified disposition, every issue this
run closed has its receipt, the Verification issues ran last and the container's acceptance is met.
Use the adapter's **Finish** section to reconcile or close the container. Closed children alone do
not prove that a parent's promised behavior shipped. A new child or changed requirement found on
refetch goes through the existing plan-change approval rules.

For a multi-issue scope, from `main`, run `sync-docs` once to advance `COMPATIBILITY.md`'s
`docs-synced-through` marker over the range the scope merged, as one docs-only pull request, which
**AGENTS.md, "Parallel Work"** reserves for after the merges. Report the issue count, pull request
count and date range. A one-issue run follows the single-issue finish rule in its adapter.

**The milestone is blocked** when no open issue can start: name each blocker and stop.


The per-tracker reconciliation recipes own the measured reasons for their tracker edits. Keep
those recipes there rather than duplicating them in the shared lifecycle or a workflow driver.
