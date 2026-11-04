# GitHub adapter

Load this only after the entrypoint resolves GitHub. All issues, discoveries, receipts and scope
updates stay in GitHub. Use the shared delivery workflow; do not invoke `linear-deep-dive` or
`sync-project`, require Linear access, or create a Linear mirror.

## Prerequisites and identity

Use connected GitHub tools when they cover the operation. Use authenticated `gh api` for missing
capabilities such as native sub-issues, dependencies or milestones. Require only reads under
`--plan`; execution needs issue/comment writes and the shared Git/PR capabilities.

Resolve each issue by owner, repository and number; retain its URL and API ID. REST relationship
writes use the numeric API ID, not the issue number. Bind the repository to the checkout's
`origin` before building. A target in another repository needs the corresponding checkout, not
a PR against this one. GitHub Projects boards and their custom fields are outside this adapter.

## Load

**Issue entrypoint:** read the issue and every page of its comments and native sub-issues. With
children, walk the native tree recursively, including closed intermediate parents, and deduplicate
by repository and number. The root is the container, not an extra implementation task. Read its
acceptance criteria and the criteria of intermediate containers. Plan unallocated acceptance as
a proposed child issue or an owner decision; do not silently execute an extra parent layer. New
product scope still needs approval. With no children, the scope is that one issue.

**Milestone entrypoint:** fetch the repository milestone and all its issues, open and closed,
ordered by creation time. Filter PR objects out of the issues endpoint. A named milestone requires
an exact match among all repository milestones; ask on multiple matches. A child outside that
milestone is an external dependency/context, not automatic scope expansion. A single leaf issue
does not expand to its siblings merely because it has a parent or milestone.

Use native membership as authority. A Markdown checklist, a body mention and a PR link do not make
an issue a child. If the native read is denied or unsupported, report that failure and ask for a
confirmed scope; do not treat it as an empty tree. Page sub-issues, comments, milestones,
dependencies and issue/PR collections to exhaustion. Preserve closed intermediate containers in
the inventory even when their descendants are open.

For each in-scope issue:

1. Read the body, all comments, labels, assignees, `state`, `state_reason`, native parent/children,
   native `blocked_by` and `blocking` dependencies, linked PRs and closure evidence. Fetch outside
   blockers for status only; a dependency does not add work to the approved scope.
2. An `open` issue is unfinished. A `closed` issue with reason `not_planned` is a waived item,
   not shipped work. Record duplicate disposition and its canonical issue where supported.
   A `closed/completed` code issue counts as delivered only with evidence its change reached
   `origin/main`. Research, decision and Verification items use their stated findings/ruling/
   verdict evidence. Investigate missing or contradictory closure reasons instead of guessing.
3. GitHub's open/closed states do not encode ready, started, triage or blocked. Use verified native
   blockers and an explicit work claim. Honor existing repository labels/status conventions where
   known; missing labels alone do not remove an open issue from consideration.
4. Inspect linked PRs, timeline references, branch heads and `git worktree list`. Find partial
   deliveries and existing work before opening a new PR. A merge into a feature branch is not a
   delivery to `main`. List premature closure, stale container text and absent required receipts
   as repairs; older closed work need not gain a receipt merely because none exists.
5. Keep another author's active PR out of autonomous branch edits. Reuse its plan slot or mark it
   externally owned; never create a competing PR. Committing or pushing to that branch needs
   explicit user confirmation, even under `--merge`.

A parent/child edge means membership, not implementation order. Use native dependencies for the
dependency graph. If issue text names an additional prerequisite, verify it and record a proposed
dependency repair in the plan. An unavailable dependency API leaves ordering unknown; report the
gap rather than treating every item as unblocked.

For example, read a milestone without the default open-only filter:

```bash
gh api --method GET --paginate 'repos/OWNER/REPO/issues?milestone=4&state=all&sort=created&direction=asc&per_page=100'
```

For a parent such as `spacedock-dev/compass#758`, enumerate its native children and descendants
instead of searching for every issue that mentions `758`.

## Understand

Use the plan-stage subagent to read the GitHub issue, comments, dependencies, linked PRs and
relevant code/contracts. Return a scratchpad analysis: current behavior, reproducible failure or
missing capability, acceptance gaps, files/views affected, dependencies and a concrete approach.
Do not pass the GitHub target through a Linear-specific parser. Follow the shared design-reference
and visual-walk rules.

Before building, read relevant contract notes in the issue, all native ancestor issue comments
and its milestone description, including maintained progress notes that name this issue. These
are contextual reads and do not expand a leaf or milestone scope. GitHub milestones have
descriptions, not comment threads. A missing decision is filed in the selected parent tree or
milestone and linked as a native blocking dependency, under the entrypoint's authorization rules.

At work start, keep the issue open and post or update one concise work claim identifying the
implementer and PR/branch. Reuse an existing claim; check whether it is still live. An assignee alone
does not prove an agent is working. Keep estimates in the plan; GitHub has no native issue estimate.
Use existing public labels when appropriate and approved; do not invent workflow states, custom
fields, `journey:*` or `move:*` labels. User value briefs use public promise wording, with no
internal tracker names, keys or links.

## PR links

On a finishing PR, use `Closes #N` for each actual issue in the same repository, one line each.
Use `Closes OWNER/REPO#N` across repositories. A partial layer says `Part of #N` without a
closing keyword. Do not put the parent's closing keyword on a PR that finishes only one child.
GitHub interprets closing keywords on PRs targeting the default branch; stack layers targeting a
feature branch still need explicit reconciliation after the stack reaches `origin/main`.
Read back the issue state instead of assuming automation closed it.

## Reconcile

Once the finishing change is confirmed on `origin/main`, and once per issue in dependency order:

1. Verify the delivered acceptance criteria and mainline merge evidence. Close the issue as
   completed if automation has not. Keep a partial issue open; correct a premature closure as
   an approved repair. A non-code disposition identifies its findings, ruling or verdict.
2. Reconcile the parent/milestone's remaining-work and blocker statements with live state. Preserve
   the reporter's original report and acceptance criteria. Prefer a concise maintained progress
   comment on a parent issue over overwriting a contributor's body; update this run's existing
   progress comment. For a milestone, maintain the remaining-work notes in its description.
3. Record any new contract a remaining item needs in that item's GitHub issue or the container's
   maintained parent-issue progress comment or milestone description, with an explicit link to
   the affected issue. Remove obsolete notes.
4. Re-read dependent issues and dependencies. Identify newly ready work. A completed prerequisite
   satisfies the dependency; a waived or duplicate prerequisite may still require an owner ruling
   or a replacement dependency before work can proceed.
5. Preserve native dependencies as history when they remain accurate. Do not translate Linear's
   `relatedTo` edits into GitHub or remove an edge just because its prerequisite closed. An
   inaccurate relation needs a verified, approved repair.
6. Draft any change to public promise wording for `sync-docs`. Keep its GitHub copies consistent
   when present; there is no Linear copy to update.

Post one receipt on the issue covering these six items, with not-applicable reasons where needed,
the finishing PR and merge commit, checks and remaining work. Update this run's existing receipt
on retries. Keep public wording free of internal tracker provenance. Validate complete public
drafts with `python3 scripts/validate_plugins.py --public-text FILE`, then read back the published
text, states and native relations.

## Discoveries

A defect introduced by this work or deferred by its review becomes a native sub-issue of the
selected parent, or an issue in the selected milestone. Use a native blocking dependency to a
non-owner-gated Verification item when applicable. A pre-existing defect stays outside that parent
tree/milestone and links back as related context. Use existing labels where suitable. These writes
still obey the shared approval and estimate limits.

## Finish

Refetch scope membership, states, dependencies and parent acceptance before declaring completion.
Closed children with waived work do not prove that the parent's acceptance criteria were met.
A closed intermediate container with open descendants is a repair, not a completed subtree.

Close a parent only when its applicable criteria are met, all in-scope work has a verified
disposition and required Verification work ran last. Post a concise final comment with the
delivered behavior, PRs, checks and any limitations. Close a milestone only when its issue scope
and acceptance are complete; retain its purpose and replace stale remaining-work text with a short
completion note. A leaf-issue run closes only that issue and reconciles its parent/milestone's
progress; it does not close either container. Follow the shared docs-marker closeout for a
multi-issue scope.

## API references

- [Native sub-issues](https://docs.github.com/en/rest/issues/sub-issues)
- [Native issue dependencies](https://docs.github.com/en/rest/issues/issue-dependencies)
- [Milestones](https://docs.github.com/en/rest/issues/milestones)
- [PR closing keywords](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)
