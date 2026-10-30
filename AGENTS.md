# AGENTS.md

## Project Overview

This repository distributes Compass — an agnostic agent cartography and visualization tool — to Codex, Claude Code, Antigravity/AGY, and Gemini CLI. It contains one markdown-first plugin rather than a code application:

- `compass/` — the agent cartography dashboard skill, and the plugin root Claude Code, Codex
  and Antigravity all install
- `compass-gemini/` — a hooks-only Gemini CLI extension root. It exists because Claude Code and
  Gemini CLI both load extension hooks from `<root>/hooks/hooks.json` and neither lets that path
  be moved, so a shared root hands each harness the other's event vocabulary
- `compass-droid/` — a hooks-only Droid plugin root. It exists because Droid reads
  `.claude-plugin/plugin.json` and `<root>/hooks/hooks.json` by default, colliding with Claude Code's
  hook commands and sending events to `/api/events/claude` instead of `/api/events/droid`

Repository development skills are canonical under `.claude/skills/`. Claude Code discovers them
there; Codex discovers the same directories through relative symlinks under `.agents/skills/`.
Each canonical skill owns its `SKILL.md`, supporting files and `agents/openai.yaml` metadata.

The user-facing workflow lives in `compass/skills/compass/`. Every user-facing workflow must be usable as a skill so Codex can discover it; Claude-only agents and lifecycle hooks may remain in their native directories if ever added.

## Architecture

```
compass/                           # plugin root: Claude Code, Codex, Antigravity
├── .claude-plugin/plugin.json      # Claude Code manifest
├── .codex-plugin/plugin.json       # Codex manifest
├── plugin.json                     # Antigravity / AGY manifest
├── hooks/hooks.json                # Claude Code lifecycle hooks (its path, by convention)
├── hooks/codex-hooks.json          # Codex lifecycle hooks (declared in its manifest)
├── hooks.json                      # Antigravity lifecycle hooks (its path, at the root)
└── skills/
    └── compass/                   # the dashboard skill
        ├── SKILL.md                # shared skill body (all harnesses)
        ├── server.py               # the stable launcher: calls compass_runtime.cli.main
        ├── notify_hook.py          # loopback POST forwarder for the user-installed Claude hooks
        ├── event_hook.py           # posts Claude and Codex command-hook lifecycle events
        ├── opencode_plugin.js      # passive per-project OpenCode parent permission events
        ├── pi_extension.js         # Pi extension UI prompt events in persisted sessions
        ├── agy_hook.py             # posts Antigravity's hook events
        ├── statusline_hook.py      # posts Antigravity's status-line state
        ├── mcp_server.py           # stdio MCP server: the one tool a session calls to ask the reader
        ├── compass_runtime/       # importable dashboard runtime package
        │                           # per-module map: docs/design-runtime-architecture.md
        │   ├── collectors/         # one harness collector per file, one per supported harness
        │   └── web/                # the built React page, its integrity metadata and licenses, vendored
        │                           # terminal assets, fonts and the page loader (`page.py`)
        ├── agents/openai.yaml      # Codex presentation metadata
        └── tests/                  # dashboard unit tests and shared support
frontend/                           # React sources, unit tests, Storybook stories and on-demand browser proofs (Node and pnpm; not shipped)
├── .storybook/                     # offline component explorer and Chromium test config
├── stories/                        # component examples with play-function assertions
├── src/                            # the React page; `pnpm build` packages it into `web/react.html`
├── test/                           # test support, synthetic backends and the recorded answers
│                                   # (`test/golden/`: fixtures of record, never regenerated)
├── e2e/                            # Playwright browser proofs, run on demand by `pnpm test:*:browser`; not required by CI or the pre-PR list
└── build/ dev/                     # the packager and the contributor development supervisor
sample-session/                    # the anonymized example session behind "Sample session (view only)"; not shipped
│                                   # (`milestone-session.jsonl` and its README). The page's fixture built from it
│                                   # is `frontend/src/sample/session.fixture.json`; `scripts/cut_sample_session.py`,
│                                   # `sanitize_session.py` and `build_sample_fixture.py` make both
scripts/frozen-page/               # the retired page's script parts, outside the plugin: the paused study
│                                   # binds their digest (`scripts/frozen_page.py` loads them); not shipped
compass-gemini/                    # extension root: Gemini CLI (hooks only)
└── hooks/
    ├── hooks.json                  # Gemini CLI lifecycle hooks
    ├── event_hook.py               # posts Gemini command-hook lifecycle events
    └── notify_hook.py              # loopback POST forwarder
compass-droid/                     # plugin root: Droid (hooks only)
├── .factory-plugin/plugin.json     # Droid plugin manifest
└── hooks/
    ├── hooks.json                  # Droid lifecycle hooks
    ├── event_hook.py               # posts Droid command-hook lifecycle events
    └── notify_hook.py              # loopback POST forwarder
tests/                              # pushback session fixtures (not shipped, not a test suite)
├── raw_sessions/<session_id>/      # steering-excerpts.txt; the full sanitized .jsonl is gitignored
└── annotated_sessions/<session_id>/ # annotation.md: goal -> drift -> steering per part
```

The Codex/AGY marketplace lives at `.agents/plugins/marketplace.json`. There is no Claude
marketplace in this repository: compass is listed in the shared
[spacedock-dev/marketplace](https://github.com/spacedock-dev/marketplace), which tracks the
`stable` branch that the Release workflow advances on every release.

## Documentation

Docs are owned, not shared. Each file below owns a subject; every other file links to the owner
rather than restating it. The full map, including the constraints the validator places on the
shipped skill body, lives in the `sync-docs` skill at `.claude/skills/sync-docs/SKILL.md`.

| File | Owns |
|---|---|
| `README.md` | The front door: what Compass is, install per harness, skill inventory, links out. |
| `MANUAL.md` | The standalone `server.py` command reference: every option and alias, defaults, interactions, environment, files, exit status and examples. Keep its option rows current when changing `cli.build_parser`; the documentation suite checks their inventory. The installed skill remains self-contained. |
| `HOW_TO_USE.md` | What a person configures by hand: the harness settings the plugin does not install, one verified procedure per task. |
| `AGENTS.md` | **This file.** The repository contract for agents, the canonical pre-PR command list, the parallel-worktree hazards measured while burning down the roadmap, and how much review a change is worth (**Calibrating Effort**). |
| `CLAUDE.md` | Claude-Code-only addenda; imports this file. |
| `CONTRIBUTING.md` | The human contributor journey, and the dashboard implementation constraints. |
| `COMPATIBILITY.md` | The cross-harness and cross-platform contract, and the Python floor. |
| `SECURITY.md` | Security invariants, accepted exposures, and private reporting. |
| `compass/skills/compass/SKILL.md` | The shipped product surface. A validated artifact — see the portability rules below. |
| `docs/promise-map.md` | **Canonical** user-facing promise: one promise per stage of the user's day, the shipped capability behind each, and where each stops. Release notes and the README lede restate it rather than reinvent it. |
| `docs/development-tracking.md` | **Canonical** development taxonomy: promise IDs, journey labels, board columns, moves and tracker copies. It links to the public promise map without putting tracker provenance into that map. |
| `docs/design-runtime-architecture.md` | **Canonical** module map: what each runtime file owns, which way dependencies run, and how config/state/application are held. |
| `docs/design-reader-state.md` | **Canonical** rule for what survives a board refresh: one row per thing a reader can leave in the page, which React owner keeps it, and — for the two it does not manage — why. The code cites it instead of repeating it. |
| `docs/design-frontend-migration.md` | The React frontend: its boundaries, the recorded answers it is held to, its deviations from the retired page and why, and the retired measurement method and its recorded figures. `scripts/frontend-migration.json` maps the retired page's parts, surfaces, routes, reader state and browser storage to owners and proofs; `scripts/frontend_inventory.py` checks that each row is owned and names proofs that exist. |
| `docs/design-reading-a-session.md` | **Canonical** record of the four rulings that govern what Compass may say about a session against the words a reader typed: the evidence floor and the reader-requested model overlay, whether an assessment may be stored, that Compass never writes into a session, and the seven-rule shape contract a reading must satisfy. The runtime cites its headings, because three of those rules are built into the producer rather than checked after it. |
| [docs/design-adapter-packaging.md](docs/design-adapter-packaging.md) | **Canonical** adapter admission and packaging contract: identity normalizers, hook-shaped mappings, and implementation-language boundaries. |
| `docs/design-sample-session.md` | **Canonical** record of the Sample session (view only): the reserved route, the second shell, the view-only guard, the numbered marks, and what was rejected. |
| `sample-session/README.md` | What the sample session is made from: what is real and what is authored, the recorded exceptions to the transcript policy, the checks each transcript passed, and how to regenerate it. User-facing by default. |
| `docs/design-*.md` | Durable design rationale, including alternatives that were tried and rejected. Each links to the architecture owner rather than repeating its module map. |
| `docs/plans/*.md` | Transient plans for unshipped work. Delete a plan once its work ships. |
| `docs/roadmap-burndown/README.md` | The Spacedock workflow the roadmap burndown runs on: its stages, gates, and the measured rules each one earned. Machinery rather than prose — entity state lives on an orphan branch and is gitignored. |
| `docs/captures/` | Recorded hook payload shapes from real harness sessions: the evidence behind any adapter gate marked measured. Field names and timings, plus closed harness vocabularies such as `notification_type` and `reply`, each earned one at a time on the reasoning the captures README gives; never a value a person or a model wrote. |
| `.claude/skills/*/SKILL.md` | Canonical repository development skills (`sync-docs`, `sync-project`, `visibility-2x2`, `burndown`, `compass-release`, `visual-review-and-fix`) and their Codex presentation metadata. Not shipped with the plugin, so the portability rules below do not apply to them. |
| `.agents/skills/*` | Codex discovery aliases for repository development skills. Each entry is a relative symlink to the matching canonical directory under `.claude/skills/`; `scripts/validate_plugins.py` rejects missing, copied, orphaned or misdirected aliases. |
| `docs/abstention/` | The committed half of DEC-17's abstention check: a README saying what the file may hold and how to argue with a result, and — once a scoring run has been committed — the scorer's summary (case ids, marks, outcomes, counts, coverage, the marks digest). The cases, the local results and the rubric expectations stay under `~/.compass`; `SECURITY.md` owns that ruling. |
| `docs/evidence/intent-and-drift/` | The optional exploratory teammate prompt and participant notice, archived cold-study protocol, and redacted run template for live Intent and drift feedback. Raw sessions and screenshots stay outside Git; issue attachments require participant review. The owner retired the cold-study acceptance requirement on 2026-10-06; application verification and producer qualification remain required. |
| `tests/README.md` | The pushback session fixtures under `tests/raw_sessions/` and `tests/annotated_sessions/`: what is committed (steering excerpts and annotations), why the full sanitized session logs stay local and gitignored, the redaction tags, and how the sessions were chosen. |
| `docs/drift-replay/` | The committed half of the drift replay check: a README saying what the files may hold, the run order (blind marks before any output) and how to argue with a result, plus the marks digest and, once scored, the outcome summary. `scripts/drift_replay.py` runs it and `scripts/redact_session.py` makes its replayable fixtures; cases, marks and outputs stay under `~/.compass/drift-replay/` (or `COMPASS_HOME`), and the spend ledger under `~/.cargento/drift-replay/`. |
| `docs/visibility-2x2/` | The Visibility 2x2 prioritisation board and the blind-panel evidence behind its scores. A local working tool, opened by the `visibility-2x2` skill. |
| `docs/screenshots/` | Screenshots taken in this repository. Every capture — browser or screen — lands here unless the request names another location. Its contents are gitignored, so a capture never reaches a commit, and a committed `.gitkeep` holds the directory itself for a fresh clone. Write a descriptive filename, because the directory has no index and nothing prunes it. |

`scripts/validate_plugins.py` gates the docs as well as the plugin: across the files above it
resolves every relative Markdown link **and heading anchor**, and rejects the `localhost` spelling of
the dashboard URL (the server is IPv4-only). Deleting or renaming any of them fails the build. It also
owns `COMPASS_RUNTIME_FILES`, the inventory of every file the shipped dashboard needs at runtime;
`--runtime-files <plugin root>` checks an installed copy without the repository around it.

There is no blanket orphan-document gate. The documentation graph has no agreed scope or entry
roots, and an inbound-link count alone would not establish reachability from a reader's entry point.

Invoke the `sync-docs` skill before opening a PR (see Pre-PR Checks) so doc updates ride in the PR
that changes the code. Claude Code discovers it under `.claude/skills/`; Codex discovers the same
canonical directory through `.agents/skills/`.

The Linear surfaces are a separate subject with a separate failure mode, and `sync-project` owns
them: the project overview, the milestone descriptions and the shape of an issue. Repository docs go
stale, so `sync-docs` diffs them against the code. Tracker descriptions accrete instead, because
every burndown leaves behind a paragraph that was true when written and nothing removes one. Run
`sync-docs` first, since the promise wording is canonical in `docs/promise-map.md` and the tracker
copies it.

## Public documentation and release notes

User-facing docs and release notes must contain no Linear names, issue keys (such as `DRC-1234`)
or tracker URLs. This applies to the whole body, including examples, code fences, link definitions,
HTML, copied PR titles and generated release-note sections. Describe what a reader can do, its
limits and the public source that supports it; use public GitHub PR links for release traceability.
Do not remove a security fact, consent requirement or measured limitation just to remove its
tracker reference.

The user-facing set includes `README.md`, `HOW_TO_USE.md`, `COMPATIBILITY.md`, `SECURITY.md`,
`CODE_OF_CONDUCT.md`, `LICENSE`, `NOTICE` when present, all Markdown shipped in the plugin roots,
`docs/promise-map.md`, and the shared study entry point, participant kickoff and exploratory prompt
under `docs/evidence/intent-and-drift/`. New Markdown is user-facing by default unless it is in a
named development area. Shipped files remain user-facing even below a development-looking folder.

Development provenance may remain in `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, repository
development skills/agents, PR templates and bodies, tests and fixture annotations,
`docs/development-tracking.md`, `docs/plans/`, design records, capture schemas, roadmap/visibility
records, probes, feedback, exploration and abstention/drift study records. The facilitator protocol
and run records are development records; the shared study entry point, kickoff and prompt are
user-facing exceptions. The validator's audience classifier defines the exact development paths;
do not exempt an unknown document merely because it mentions engineering. Copying permitted
provenance into a public note does not preserve its exemption.

`scripts/validate_plugins.py` checks repository documents. Its `--public-text FILE` mode checks a
complete standalone draft before it is published. It scans raw text, not just rendered Markdown,
and refuses unreadable or invalid UTF-8 input. Validate the final assembled release body and any
announcement, including generated text, then read back the published body. A clean repository
check cannot certify an external release body it did not read. The development taxonomy and
tracker synchronization live in [development tracking](docs/development-tracking.md).

## Commit Conventions

```bash
git commit -s -m "feat(skill): add new capability to compass"
```

**Format:** `<type>(<scope>): <description>` with sign-off (DCO required)

- For multi-line commit messages with backticks, apostrophes, or special characters, write to a temp file and use `git commit -F <file>` instead of heredocs to avoid shell escaping issues.

## PR Workflow

- Always invoke the `sync-docs` skill right before opening a PR. Every code change must reconcile repository documentation against the code and pass the Step 10 verification checks before pushing and opening a PR. Any resulting doc updates must ride in the PR that changes the code.
- **`Closes #NNNN` is for GitHub issues, and this repository has almost none.** Work here is
  tracked in Linear as `DRC-NNNN`, which is not a GitHub issue number: `Closes #4589` points at
  nothing, and will point at the wrong thing once the repository's own numbering reaches it. Link
  Linear work as `Implements [DRC-NNNN](<issue url>)`, one per line, which is the form the merged
  PRs use. Reserve `Closes #NNNN` for an actual GitHub issue, and then use explicit lines, one per
  issue, never comma-separated, so autoclose works.
- PR titles must be ready for public release notes: plain shipped behavior, with no tracker brand, issue keys or tracker URLs. Generated notes copy these titles. Keep internal issue provenance in the PR body or development records.
- After requesting a PR review, always check for Copilot inline review comments in addition to top-level reviews.
- Never commit or push to another author's PR branch without explicit confirmation from the user.

## Pre-PR Checks

**This block is the canonical pre-PR suite.** Every other document points here rather than keeping
its own copy — divergent copies are how the gate drifts. Run it locally before opening any PR; do
not rely on CI to surface failures:

**One documented short path.** If the diff touches *only* prose — `HOW_TO_USE.md`, `AGENTS.md`,
`CLAUDE.md`, `CONTRIBUTING.md`, `COMPATIBILITY.md`, `CODE_OF_CONDUCT.md`,
`.github/PULL_REQUEST_TEMPLATE.md`, or a file under `docs/` outside the effective deny list below —
then the measurable quality-gate jobs skip. CI applies the same rule (see Quality Gate), so
the two agree by construction rather than by memory. Skipping those jobs is all the short path
buys: **run the suite locally anyway**, because `validate.yml` is unfiltered by design and runs the
same `unittest discover` on every PR. `validate_plugins.py` is not what catches a prose edit that
breaks an assertion — measured, one stranded row in `docs/captures/README.md`, which the detector
then called prose, left the validator at exit 0 and turned that suite red. **`SKILL.md` is not prose
for this purpose**: `tests/test_documentation.py` asserts its `~/...` paths against
`config.resolve_store_roots`. Neither are `SECURITY.md` and `README.md`, which that same module
opens by literal path — both sat on this list until someone read the tests. The effective docs deny
list has three sources: whole double-quoted paths found in dashboard tests, reviewed exceptions for
known composed paths (currently `docs/captures/README.md`), and every document the runtime cites a
heading anchor in, derived from the citation links themselves. That third source is derived rather
than listed because it *is* the citation checker's dependency set: the checker resolves each linked
target and requires the exact fragment, so renaming a heading in any of those documents turns
`test_documentation` red. Nine such documents were reachable and absent from the list on the commit
that introduced the checker, which is the same misclassification one layer up, so a hand-maintained
copy would have gone stale on the very change that created it.

Frontend and script-test sources also contribute quoted document paths and heading citations.
These measured dependencies are checked before the root prose allowlist, so a contributor doc
read by a frontend test cannot skip that test's job. Relevant frontend and release workflows are
code too. Composed reads still need a reviewed exception; a literal scan is not dependency analysis.

The literal scan is still not dependency analysis, and the first two sources do not discover every
way a test can read a document. Review new document dependencies against the list, and review the
root-document prose allowlist by hand. The unfiltered validate suite remains the backstop for
misclassification; the detector's job is to request all measurable jobs with `code=true` for
these dependencies.

The interface is verified in Storybook: a visible change is proven by a story whose `play` function
asserts it, and `pnpm build:storybook` with `pnpm test:stories` are required before a PR. The Playwright
browser proofs under `frontend/e2e` were retired from CI and from this list by the owner on 2026-10-12.
They stay in the repository and run on demand with `pnpm test:*:browser`, for example to investigate a
regression, but nothing requires them. CI exercises macOS and Linux; Windows dashboard and frontend
checks require a local run. See [Quality Gate](#quality-gate) for the retained jobs.

```bash
python3 -m pip install -r requirements-validation.txt -r requirements-dev.txt
ruff check .
ruff format --check .
mypy
python3 scripts/validate_plugins.py
python3 scripts/bump_version.py --current   # version-field parity across all owned locations
# `--current` proves the three version fields AGREE; `version-guard` additionally proves they
# have not MOVED since the merge base. Check that half yourself — nothing local does. No
# `*marketplace.json` pathspec: the one marketplace file left carries no `version` key at all.
git diff "$(git merge-base origin/main HEAD)"..HEAD \
  -- '*plugin.json' '*gemini-extension.json' | grep -E '^[+-].*"version"'
pnpm install --frozen-lockfile   # exact Node from .node-version; pnpm from package.json
pnpm lint   # Biome: lint rules and formatting; `pnpm format` rewrites the formatting
pnpm typecheck
pnpm test:styles --base origin/main   # exact CSS count, scale and live imports; CI uses the actual PR base SHA
pnpm test
pnpm test:coverage   # enforces the frontend coverage thresholds in vitest.config.mts
pnpm build:storybook
pnpm test:stories
pnpm test:dev
pnpm build
pnpm build:check
pnpm exec playwright install chromium   # lockfile-pinned browser, once per installation
coverage erase
python3 scripts/run_tests.py --coverage -s compass/skills/compass/tests -t .
python3 scripts/run_tests.py --coverage -s scripts/tests -t scripts/tests
coverage combine
coverage report   # enforces the fail_under threshold from pyproject.toml
# scripts/run_tests.py is the gate's own runner: the same discovery, fixtures and
# verdict as `python3 -m unittest discover`, spread over every core, with per-worker
# coverage files that `combine` merges. `-j N` caps the workers. Plain
# `unittest discover` still works and reaches the same verdict, serially.
# It holds what a passing test prints, as `unittest -b` does; `--no-buffer` shows it.
# On Python 3.14, `COVERAGE_CORE=sysmon` cuts the coverage run several-fold, as CI does;
# older Pythons refuse it with branch coverage and fall back to the slow tracer.
# `test_capture_terminal_identity` and `test_capture_focus_raise` exercise AppleScript
# against Terminal.app, and this suite now sends nothing. It used to: measured on a macOS desk with Terminal
# open, `test_capture_terminal_identity` sent 91 `tell application "Terminal"`
# events and `test_capture_focus_raise` sent 2, none of it disclosed anywhere.
# Both are read-only property reads that select nothing, activate nothing and
# open no window, but they are still automation of someone else's application.
# Two switches hold it shut, with different audiences: the test module sets
# `COMPASS_NO_TERMINAL_QUERY=1` on every recorder subprocess it starts, which a
# real capture never sets, so what an operator records is unchanged; and the one
# test that talks to a live Terminal on purpose is behind
# `COMPASS_ALLOW_APPLE_EVENTS=1` and skips without it. CI never sets that flag,
# so the live read runs on an operator's desk or nowhere, and the static shape
# test beside it is what still guards those scripts in CI.
# Native validators, if the CLIs are installed (they are not available on stock runners):
claude plugin validate ./compass --strict
agy plugin validate ./compass
```

Then reconcile the docs before you push. Invoke the `sync-docs` skill in your agent — it is not a
shell command — and let it commit any doc updates onto this same branch. Then:

```bash
git push -u origin HEAD && gh pr create
```

The `sync-docs` skill is a docs-only pass that diffs the docs against the code and fixes the drift the change
introduced. It also holds the human-facing prose docs it touched to the voice standard written out
in its own "Voice and tone" section — those docs are written for people, and an agent topping them
up in model-default voice is how that erodes — and greps them for the tone tells, since nothing in
CI checks that. The optional third-party `humanizer` skill automates that pass but is not required
and is not vendored here. Its canonical body lives at `.claude/skills/sync-docs/SKILL.md`.

## Parallel Work

Burning down a milestone means several agents in several git worktrees at once: a stack of layers
built serially in one worktree, and independent groups built beside it.
That is the normal shape of work here, not an exception. Everything below was measured while doing
it, and each item is a thing that produced a wrong answer rather than a thing that might.

**Assume a sibling is running.** Before trusting a red, a merge base or a scratch file, ask whether
another worktree is mid-flight. `git worktree list` answers it.

**Concurrent test suites manufacture failures.** Three at once took the suite from 73 s to 590 s and
produced errors that look like regressions and are not:

- `test_http_api` fails on loopback port binds, because two servers want the same port.
- `test_lifecycle.InstalledContractCharacterizationTest` hits `subprocess.TimeoutExpired` on
  `server.py --diagnose`, which is a real subprocess racing for CPU rather than a broken launcher.
  It is today the only class in the dashboard suite that subprocesses that command. A second name
  stood here, `test_page.FrontendAssetContractTest`, and was measured: it existed when this bullet
  was written and `8d2585c` (#247) deleted the whole module as collateral when the next UI replaced
  the old one. Its `--diagnose` coverage was not carried forward, so the name is removed rather than
  repointed. Do not substitute a plausible successor: the sibling that looks closest asserts against
  a live server, where the deleted one asserted against none with the web assets unlinked.
- `test_quota` times out on socket reads.

Run the full suite **once**, and confirm any failure in those modules by running that module alone
before believing it. Report both results rather than the convenient one. A load average above about
10 makes this near-certain. `scripts/run_tests.py` starts one worker per core by default, so a second
worktree's suite running beside it oversubscribes the machine at once: give each `-j` a share of the
cores rather than both the default.

**Build only the phase a test is exercising.** The study-guard tests added on 2026-10-06 took
Windows script tests from 97 seconds to 1,007 seconds. Rebuilding a 190-call predecessor ledger
for each later-lane test reread 76,362 reservation and settlement receipts per setup. Use a
test-only predecessor fixture checked by the real ledger validator for those setups, and retain
an end-to-end test of every reservation, settlement and the full 239-call ceiling. Do not cache
production receipt validation or relax durability to make a test faster.

**The built page is the conflict you will get.** `react.html`, `react.integrity.json` and
`react-licenses.txt` under `compass_runtime/web/` are build output. Two branches that change anything
the build reads (a source file, `page.py`'s font table, the font rows of `styles.css`, a lockfile)
produce a conflict where **each side is correct for a tree that no longer exists**, so a textual
resolution ships an artifact that matches neither. Resolve the sources, then rebuild with `pnpm build`
and check with `pnpm build:check`, which fails when the tracked files differ from a clean build of the
tree. Do not choose a side of the generated files.

**The recorded answers are the opposite case.** `frontend/test/golden/` holds what the retired page
said, and the page that produced it no longer exists, so it cannot be regenerated. A conflict or a diff
there is a mistake to undo, never something to resolve by re-recording. A change that needs a different
answer edits the test that asks for it and records the departure in
[the design record](docs/design-frontend-migration.md#held-to-recorded-answers).

**Three files are conflict hotspots** because every branch wants a line in them:

- `SKILL.md`'s **Project** bullet. Three branches appending to that one sentence collided. Keep
  `SKILL.md` edits inside the paragraph your feature belongs to.
- `COMPATIBILITY.md`'s `docs-synced-through` marker. Every parallel `sync-docs` pass wants to
  advance it, all of them would collide, and none can honestly vouch for a sibling's work it never
  read. Leave it alone per branch and stamp it once from `main` after the merges, naming what the
  range actually covers.
- `config.py`, where every feature adds a threshold. Usually additive, occasionally not.

**Merges serialize even when builds do not.** A ruleset requires branches be up to date, so landing
one PR puts every sibling `BEHIND` and each needs `gh pr update-branch` plus a full CI re-run. Plan
for one cycle per PR and pick the order deliberately: merge the branch that changes the shared file
first, so the others resolve against it once instead of twice. A native GitHub stack (`gh stack`)
avoids most of that: when `main` moves, `gh stack sync` rebases every layer and they re-run in
parallel, one cycle for the stack, and `gh stack merge --squash` lands the layers atomically. Never
run `gh pr update-branch` or `gh pr merge` on a stacked branch; the `burndown` skill owns the
procedure.

**A stale green will mislead you.** A CI run that finished before a branch update is still reported
green. Check `mergeStateStatus` is `CLEAN` and that the checks belong to the current head before
merging. Do not trust `git merge-tree`'s three-argument form to reveal conflicts; it did not, and a
real conflict followed.

**Clean up worktrees before deleting branches.** `gh pr merge --delete-branch` fails while a
worktree holds the branch, and `git reset --hard` used to shuffle a commit onto a branch will
discard uncommitted work in the main checkout. It destroyed a file that way once.

**Agents may share one temp directory.** Two agents in separate worktrees, writing a commit message
to the same scratch path, overwrote each other between the write and the `git commit -F`. Namespace
scratch files per branch.

**A session you spawn leaves daemons behind.** Driving a harness to reproduce something starts that
harness's own hooks, and they outlive the sandbox. Thirteen of them survived a deleted directory
here and drove the load average to 18, which then caused the contention failures above. Kill what
you started, and scope the kill to what you started.

## Calibrating Effort

Rigor is a dial, not a constant. Measured across one run that merged five PRs: adversarial review
cost **4h27m of wall clock and 6.9M tokens across 35 agents**, against **3h07m and 1.35M tokens
across 5** for the implementation it was reviewing. Those 35 agents produced **10 findings that
actually blocked a merge** — 3.5 agents per finding — and exhausted the session token budget twice.

The checking earned its keep: every one of those five PRs shipped a real defect that fully green CI
missed, and none was findable by reading the diff. It was the **uniformity** that cost. A 339-line
additive PR with no callers got the same six-agent treatment as the one that owned both frontend
byte-pin oracles (a pair of tests since removed).

**Review depth — pick per PR, not per session.**

| The change | Review |
|---|---|
| No user-visible behaviour change and nothing calls it yet | Self-verify: read the diff, run the checks, merge. |
| Security, credential handling, or data loss | Full adversarial — several lenses, a completeness critic, an arbiter. |
| Owns a conflict-prone surface (the built page, `SKILL.md`, `config.py`) | Two lenses plus an arbiter. |
| Anything else | Two lenses plus an arbiter. |

What makes the rest affordable is an **arbiter that reproduces findings rather than ranking them**.
Across that run it refuted 13 of the findings put to it — including two blockers the orchestrator
had asserted himself, and several that were correct numbers attached to the wrong conclusion.
Without that pass the lens count would have to rise to compensate.

**One PR per conflict surface, not one per issue.** Issues are units of reasoning; PRs are units of
merge risk. Five issues became five PRs on that run where three would have done. The only
constraint that genuinely forces a split is that exactly one line of history may touch
`compass_runtime/web/`: one PR, or one stack whose layers build on each other (see Parallel Work). Every extra PR costs a review, a fix round, a CI cycle, and — because a
ruleset requires branches be up to date — a merge serialization that puts every sibling behind.

**Review the diff in the worktree before opening the PR.** Reviewing after means every PR runs CI
twice: green, blocked by review, fixed, green again. That was roughly fifteen minutes per PR of
pure waiting, and it is avoidable by reordering two steps.

**Never promote a deferred finding into the current PR.** When an arbiter defers something, file
it. Promoting it buys another implement-and-CI round for a finding already judged not worth
blocking on. Four promotions on that run cost about an hour.

**Give an estimate before starting.** A directive to spend tokens freely is not a directive to
spend a day. Say what the work costs at full rigor and at calibrated rigor, and let the person
choose. Nobody asked for twelve hours; they asked for the work.

### Models for qualification review and marking

AGY reviewers and blind markers may use Gemini 3.8 Flash at Medium or higher. Select an explicit
model from the current AGY catalog; the approved Medium and High variants are
`gemini-3.8-flash-medium` and `gemini-3.8-flash-high`. Keep each review or marking receipt bound
to its selected model and effort.

The scored producer qualification binds its own model separately. The current Claude Code target
is Sonnet 5.5. Reviewer acceptance and scored producer results retain their separate model identities.

## Quality Gate

Every PR must pass the `quality-gate` required check (`.github/workflows/quality-gate.yml`): ruff with `select = ALL` (curated ignores documented in `pyproject.toml`), `ruff format --check`, `mypy --strict`, a direct-launch smoke test on the Python 3.11 runtime floor followed by the whole suite there, the same suite under `coverage` on 3.14 (for its `sysmon` tracer) with the `fail_under` threshold from `pyproject.toml` enforced once, and `platform-tests`, the same unit suite re-run natively on macOS with one dashboard leg and three script shards (Ubuntu is already covered by the two jobs before it). Python suite jobs use `scripts/run_tests.py`, one worker per core. The frontend suite has its own coverage threshold, 80% of statements, branches, functions and lines, set in `vitest.config.mts` and enforced by `Frontend tests + coverage threshold`. Each threshold only ratchets up; never lower one in a PR. A PR that must merge below either needs the `coverage-exception` label, which is visible in the PR timeline.

**The required context always reports; its constituent jobs may not run.** A `changes` job decides
whether the diff contains anything the gate can measure, and the measurable jobs are gated on
it. The `quality-gate` job itself always runs and always reports, so branch protection is never
left waiting. That is the failure mode that made a naive `paths:` filter unusable here: a
required check a filter excludes never reports, and GitHub reads a missing context as pending
forever rather than as passing. The detector **fails open**: anything it cannot compute runs the
full gate. The aggregator accepts `skipped` only when the detector said `code=false`, so a
job skipped because an upstream dependency died still fails the gate. `validate` and
`version-guard` are deliberately unfiltered for the same required-check reason, and `validate` is
in any case the check a prose change most needs: it resolves every relative Markdown link and
heading anchor, and it runs the dashboard suite. That second step is **not** a duplicate of the
gate's copy: it is the only run of the suite on a PR the detector called prose, so deleting it as
redundant would let a prose edit that breaks a test merge green. `validate.yml` says the same thing
at the step itself.

**CI exercises macOS and Linux.** Windows is no longer exercised by CI for the dashboard unit
suite or the frontend. `platform-tests` keeps the macOS dashboard leg and three script shards;
the Linux coverage and runtime-floor jobs still run both Python suites.

`Frontend (macos-latest)` uses pinned Node and pnpm for lint, strict types, unit tests and a clean
preview build. It checks the hand-written CSS record against the actual pull request base, and it
exercises owned development startup and cleanup (`pnpm test:dev`, Node tests). The browser proofs that
used to follow, including the separate `Frontend proofs` job retired earlier, are no longer part of
the gate (owner, 2026-10-12); the interface is verified by Storybook.

`Frontend tests + coverage threshold` runs the Vitest suite under coverage on Linux (`pnpm test:coverage`)
and fails below the thresholds in `vitest.config.mts`, unless the PR carries `coverage-exception`. It keeps
the read-only token every frontend job has, because it runs third-party test dependencies; the sticky PR
comment comes from `Frontend coverage comment`, a separate job that holds the write token, runs no
repository or package code, and never gates. Vitest runs `.ts` tests under Node and `.tsx` tests in jsdom
on VM workers, and a `.ts` test that needs a DOM says so with an `@vitest-environment jsdom` comment.

`Frontend production bundle` runs on Linux: it rebuilds the tracked artifact from its sources and
compares it, and runs no proof. The `Storybook (ubuntu-latest)` job builds the offline explorer and
runs the component assertions in pinned Chromium. All four frontend jobs are in the aggregator's
`needs` (the comment job is not), and a skipped result passes only when the detector said `code=false`. The required status
checks on main remain `validate`, `version-guard` and `quality-gate`. Native harness canary Node
requirements remain independent of this build toolchain.

## Measured Invariants

Three rules the code keeps that a green suite does not enforce. Each was learned by shipping the
defect, more than once in two cases, and each is cheap to check while writing and expensive to find
afterwards.

**A structurally-present default is not a measurement.** A field every row carries whether or not
anything ran cannot be counted, and a figure derived from one reports a fact about the schema as
though it were a fact about the session. Three instances in one milestone, none caught by a suite:
both caps in the unasked lane counted departures raised, so a board of healthy sessions never
advanced either count and the lane ran unbounded, reproduced at 480 subprocesses in a simulated day
against a documented cap of twelve; whether a session had been checked was derived from the lane
being attached, so every row claimed to have been checked the moment the switch was on, including
rows the lane never reads; and a per-session departure figure read the length of a list
`base_session` declares empty on every row, so a session nobody checked reported zero departures as
a finding. The test is to ask what the figure reads when nothing happened, and whether that differs
from the figure when something happened and found nothing. If it does not, the count is on the wrong
thing. The frontend's own shared contract says the adjacent half: every count in a sentence is
derived from the collection the rows render from, never authored.

**A new per-session published field is declared by hand in three places, and they are kept apart on
purpose.** `sessions.base_session` at its absent value, `DECLARED_SESSION_FIELDS` in
`tests/test_sessions.py`, and the owning producer's own `published()` mapping. `events.PATCHABLE` is
a fourth when an envelope may write the field, and `history.OBSERVATION_FIELDS` a fifth when it
enters session history. Two tests bind it, a constructor set-equality check and a payload
set-equality check across every harness fixture; the payload half is the one that catches a key
added after construction, and an undeclared key once left 2,325 tests green without it.

**A store that compares against `ended_at` attaches after the overlay pass, not before.** Only
`_apply_overlays` writes that field, so attaching earlier reads `None` on every row. Attaching
first retracted every `final` reading on every collection, each with a sentence saying the end was
no longer published about an end published seconds later. The comment above the
`_attach_annotations` call in `Application.collect` records it; read that before reordering
anything in that sequence, because three of the calls around it are ordered for reasons of their
own and one of them is deliberately ordered by convention alone.

A change to a component or view updates its story and passes `pnpm test:stories`. Storybook is where the
interface is verified now: a story's `play` function asserts what a reader sees and does, in pinned
Chromium, offline. New UI or UX behaviour is proven there, not in a new browser proof.

## Code Comments

Comments record decisions. The code already says what it does, and a comment that restates it goes stale the first time the line changes.

Write one when the reader could not otherwise know:

- **Why not the obvious alternative.** A constant that looks arbitrary, a branch that looks inconsistent with the one beside it, an ordering that someone could "tidy up" into a bug. This is the common case here, because the alternative is not in the file.
- **What was measured.** A value derived from a real observation, with the observation named.
- **What was tried and rejected.** If it is small, a comment. If re-deriving it would cost a day, it belongs in `docs/design-*.md` and the comment is a pointer.

Do not write one to restate the line below it, to summarize a function its name already summarizes, or to defend every small choice.

Length follows the decision, not the code. A one-line change can deserve two lines of why; it rarely deserves six. If the explanation runs longer than the code it explains, the reason is durable enough for `docs/design-*.md`, and the comment shrinks to a reference.

The citation syntax is checked by `RuntimeDecisionCitationsTest` in `test_documentation.py`.
It reads `.py`, `.js`, `.css` and `.html` recursively under `compass_runtime`, without importing
those files or using the network. The finite local-label grammar is `D1`, `D-1`, `DEC-1`, `AC1`,
`AC-1`, `DR-1`, `N-1`, `NUI-1`, `Q-1`, `R-1`, `S-1` and `U-1`, with decimal digits in place of
`1` and exact token boundaries (no adjoining word character or hyphen). Each retained active label
must be the entire link text of a same-line link, such as
`[D-4](docs/design-cross-platform.md#d-4)`, without whitespace
inside the target. Paths are repository-relative, confined to root Markdown or Markdown below
`docs/`, and include an exact heading fragment or explicit HTML anchor. The checker uses
`scripts.validate_plugins.heading_slugs`; keep long links intact on their own line when needed.

Intentionally absent historical records may use this per-occurrence form:

```text
decision-history: DR-8 | 4de75d29 | repaired grouping bug; the bound now lives in sessions
```

The marker exempts only the label immediately after `decision-history:`. It requires a lowercase
hex commit (7–40 characters) or an ISO date (`YYYY-MM-DD`), and a nonempty reason after the second
` | `. A history marker never exempts another label on the same line. If the old ruling still
justifies current behavior, cite the current contract too, or replace the shorthand with that
contract. Remove unnecessary labels instead of inventing archival headings to preserve them.

This is a lexical reachability check, not a semantic review: a link to an existing but wrong owner
passes. Reviewers must check that the ruling supports the sentence and that a history claim is true.
Bare tracker keys such as `DRC-4396`, roadmap identifiers such as `A5` and `B2`, lint/encoding tokens,
and new label families are outside its grammar. It neither queries trackers nor requires globally
unique labels, and has no line-number allowlist. The rest of this comment standard remains a review
obligation, like the prose voice standard in `sync-docs`.

## Versioning and Releases

The plugin version must be identical in three places: `compass/.claude-plugin/plugin.json` (the
source of truth `bump_version.py` reads and writes from), `compass/.codex-plugin/plugin.json`,
and `compass-gemini/gemini-extension.json`. The plugin description must be identical in four:
those three manifests plus the Antigravity `compass/plugin.json` (`compass-droid/.factory-plugin/plugin.json`
carries only name and description without a version field). `scripts/validate_plugins.py`
enforces both.

Version fields are **owned by the tag-driven Release workflow** — never edit them in a PR (the `version-guard` check fails any PR that does).

**A tracked `RELEASE_HOLD` file at the repository root puts releases on hold**, and none is tracked
now. The hold that covered the React cutover lifted for 1.0.0, after the legacy page and its
`--frontend legacy` rollback were removed and the Python-only install and backend-connected
development checks passed on one build of `main`. The guard is not prose:
`scripts/release_transition.py resolve` refuses while the file is on `main`, for a fresh release and a
resume, before any verifier or credential, `assert-checkout` asks again before anything is published,
an unreadable `main` refuses rather than passing, and `scripts/tests/test_release_transition.py` rehearses it
against temporary repositories. Do not edit or delete the file to get a release through; the owner lifts
it in a reviewed pull request. The `compass-release` skill owns the procedure.

Which number to cut is a separate question from how to cut it, and the `compass-release` skill owns it: it reads the surfaces changed since the last tag rather than the commit prefixes, and its own history section carries the measured reason why. It also owns the pre-flight checks, the post-tag verification, and the optional Slack announcement. Invoke it rather than reasoning from the commit log by hand. To release:

```bash
git checkout main && git pull
git tag v0.2.0        # v-prefixed is canonical (bare 0.2.0 also works — pick ONE form per release)
git push origin v0.2.0
```

The Release workflow is eight jobs, split by what each may hold:

- `resolve` (read-only token, no key) validates the tag (must be on main, strict semver, strictly greater than every existing release tag — back-tagging is impossible) and fixes one **target** commit before anything runs: the main tip for a fresh release, or the existing `chore(release): <tag>` commit for a resume.
- `verify-frontend` and `verify-tree` (read-only token, checkout with `persist-credentials: false`, no deploy key) check out exactly that target. The first installs the pinned Node and pnpm with dependency scripts denied, rebuilds the React bundle and compares it with the tracked artifact, runs lint, types and tests, and runs the Python-only installed proof. The second runs the contract validator, its own tests, the bump-version tests and the whole dashboard test suite, and exists because several of those start `node` whenever it is on PATH. Neither is the quality gate, which already ran on every commit that reached main. A release step that runs a command CI also runs has the same time limit as CI's step, held equal by `CiLimitsTest` in `test_release_workflow.py`: the first release run to share the frontend suite timed out at 3 minutes on a suite that had passed, because the gate gave it 6. If a CI step times out and you raise its limit, the test fails until the release step's limit matches.
- `build-cli` (read-only token, checkout of the target with `persist-credentials: false`, no deploy key) runs once per release target, on a host of that OS and architecture because PyInstaller cannot cross-compile: `macos-15`, `macos-15-intel`, `ubuntu-22.04-arm` and `ubuntu-22.04`. Each installs the exactly pinned toolchain from `requirements-cli.txt`, wheels only, under the pinned Python 3.12 that becomes the interpreter embedded in the binary, runs `scripts/package-cli.sh`, runs the packed archive with `scripts/smoke-cli.sh`, and uploads it as an artifact. The binary is built before `release` bumps the manifests, so `package-cli.sh` stamps its `--version` from the release version it is given, and the smoke run checks that `--version` agrees with the archive name. The Linux hosts are the oldest images offered, because a PyInstaller binary needs at least the glibc of the machine that built it. `release` waits for all four, so a failed build stops the release before anything is pushed, tagged or published.
- `release` is the only job with `RELEASE_DEPLOY_KEY`, and it runs no Node, pnpm, npm, corepack or frontend dependency code. Its first command is plain shell: fresh mode checks `HEAD` equals the target, resume mode detaches onto the target, so no repository script runs while `HEAD` is unverified. Then `assert-checkout` confirms both verifiers recorded that same SHA, one `chore(release)` bump commit is written via `scripts/bump_version.py`, `git archive` of that exact commit is proven with Python only (`scripts/verify_release_archive.py`: version parity, a diff confined to the `version` value of the owned manifests, a byte-identical React bundle, the runtime inventory, the page integrity check and a launcher start under an empty PATH), and only then the bump is pushed, the tag moved onto it, `stable` advanced (forward only) and a GitHub Release published.
- `attach-cli` holds the repository write token and no deploy key, so it can add files to a release and cannot push to main or move a tag. It downloads the four archives the build jobs made, then `scripts/publish-cli.sh` refuses anything but exactly `compass_<version>_<os>_<arch>.tar.gz` for the four targets, writes `checksums.txt` and runs `gh release upload --clobber`. It is its own job so that no artifact, which a third-party build dependency could have shaped, reaches the job that holds the key; it treats the archives as data and never unpacks or runs one. The cost is that `releases/latest` has no archives for about a minute after the release is created. A re-run attaches again.
- `marketplace` (read-only token, checkout of the target with `persist-credentials: false`) runs after `release` and holds a different key: `MARKETPLACE_DEPLOY_KEY`, the private half of a write deploy key on `spacedock-dev/marketplace` alone, so it can neither push to main here nor move a tag. The listing tracks `stable`, so a release reaches installs without this job; it stamps the released version onto the `compass` entry's `version` field, which is what the marketplace displays and what an installed copy compares against to notice an update. `scripts/publish-marketplace.sh` clones the marketplace, runs `scripts/update_marketplace.py`, and pushes one `compass <version>` commit to its main, retrying from a fresh clone when another product's release lands first and never forcing. The updater refuses an entry that does not point at `stable` under `compass/`, and never moves the version backwards, so re-running only this job is always safe. It runs git, ssh and the Python standard library, and no dependency code. Rotating the key is replacing the deploy key on the marketplace repository and this repository's secret together.
- `homebrew` (read-only token, checkout of the target with `persist-credentials: false`) runs after `attach-cli`, because the formula it writes names the four archives and their published checksums, and holds a third key: `HOMEBREW_TAP_DEPLOY_KEY`, the private half of a write deploy key on `spacedock-dev/homebrew-tap` alone. `scripts/publish-homebrew.sh` fetches the release's public `checksums.txt` with `curl` (no token), clones the tap, runs `scripts/update_homebrew.py` to render `Formula/compass.rb`, and pushes one `compass <version>` commit to its main, retrying from a fresh clone and never forcing. The formula installs the whole archive folder into `libexec` and links the program as `compass` and `spacedock-compass`, the name Spacedock looks for on PATH. It states `version` outright, and its test asserts that `compass --version` prints it. The renderer refuses a checksums file that is not exactly the four archives of the version and never moves the formula backwards, so re-running only this job is always safe. It runs git, ssh, curl, jq and the Python standard library, and no dependency code. Rotating the key is replacing the deploy key on the tap and this repository's secret together. The key covers the whole tap, so it could also overwrite other products' formulas, the same trade-off Subspace's key makes.

The archives are what Spacedock's installer reads. Each unpacks to one `compass/` directory holding the `compass` program and the interpreter and modules it carries, so a user needs no Python, and Spacedock's install table row for it is kind `tree` with program `compass/compass`. The `CLI package` workflow (`.github/workflows/cli-package.yml`) runs the same build and smoke run on all four targets for any pull request that touches the runtime, the packaging scripts or `requirements-cli.txt`, so a break is found in review instead of in a release; it is not a required check, because a path filter would leave a required context pending. COMPATIBILITY.md owns what the binary does and does not cover.

The decisions live in `scripts/release_transition.py`, not in YAML, and are tested against temporary repositories with a bare origin (`scripts/tests/test_release_transition.py`, `scripts/tests/test_verify_release_archive.py`); the job boundaries are pinned by `compass/skills/compass/tests/test_release_workflow.py`. The React bundle is version-independent, so a bump must leave it untouched; a changed bundle byte after verification stops the release before `stable` moves.

Every step is idempotent: a re-run after a partial failure resumes cleanly, verifying and publishing that tag's own release commit rather than a newer main, and tagging the version the manifests already carry releases it as-is (that is how the initial 0.1.0 ships). If main advances while the verifiers run, the `release` job fails before it pushes or tags anything. Recovery is **Re-run all jobs** on the same run, never Re-run failed jobs (which keeps the stale target) and never pushing the tag again (it already exists, so nothing starts): only a full re-run runs `resolve` again, which takes the new tip or resumes the tag's own release commit. If main advances between the tag push and `resolve`, the release includes those extra commits. A resume of a release commit that predates the frontend toolchain cannot pass `verify-frontend` and needs a manual release. Release tags are immutable — a tag ruleset blocks deleting or moving them.

## Portability Rules

Shared skill bodies must work in every harness:

- No `${CLAUDE_PLUGIN_ROOT}` in skill bodies — resolve resources relative to `SKILL.md`.
- No `.claude/skills/` paths in skill bodies — reference the bundled skill path, not a user cache.
- No host-specific tool names (`mcp__claude_ai_*`, `ToolSearch(`, `Skill(skill=`, `subagent_type`) — describe capabilities semantically.
- The validator (`scripts/validate_plugins.py`) rejects all six of these markers in any bundled Markdown.

These rules apply to Markdown **under `compass/skills/`**. In `AGENTS.md` and `CLAUDE.md` the same
strings are the documentation of the rule and must stay.
