## Summary

<!-- What does this change and why? -->

## Test plan

- [ ] Ran the canonical pre-PR suite in `AGENTS.md` § Pre-PR Checks, including frontend lint, strict types, unit, coverage and build checks, and the Storybook stories for any UI change, and it is clean. A prose-only diff is not exempt: the `validate` check is unfiltered and runs the same tests
- [ ] Preserved Python 3.11 compatibility; CI's `runtime-floor` job launches the shipped entry point on that floor
- [ ] Invoked the `sync-docs` skill — the doc updates for this change ride in this PR, or there was nothing to reconcile
- [ ] Behavior changes to `server.py` or `compass_runtime/` include a regression test
- [ ] No version field was touched (`version-guard` fails any PR that bumps one)
- [ ] The hand-written CSS record matches the rules and respects the actual PR base
- [ ] PR title, user-facing docs and proposed release text contain no tracker names, issue keys or tracker links, including copied/generated sections; internal traceability stays in this PR body or development records
- [ ] Commits are signed off (`git commit -s`, DCO)

<!-- If this closes an issue, one line per issue — a comma-separated list does not autoclose: -->
<!-- Closes #NNN -->
