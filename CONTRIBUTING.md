# Contributing to Compass

Thanks for your interest in improving Compass. This document covers everything you need to get a change from idea to merged PR.

## What Compass is

Compass is an agnostic agent cartography and visualization tool, distributed as a cross-platform plugin (Claude Code, Codex, Antigravity/AGY, Gemini CLI). The repository is markdown-first: the product is the `compass/` plugin and its single `compass` skill, backed by a stdlib-only Python dashboard server.

Read [AGENTS.md](AGENTS.md) for the repository architecture and [COMPATIBILITY.md](COMPATIBILITY.md) for the cross-platform contract before making changes.

If you are looking for what to work on rather than how, [docs/visibility-2x2](docs/visibility-2x2/README.md) is a local board of candidate signals scored on how much a user could act on them against how hard the information is to get without Compass. Open it with the `visibility-2x2` skill. It is a working document, so treat it as an argument in progress rather than a committed roadmap.

## Development setup

Prerequisites: Python 3.11+ (`runtime-floor` runs the shipped entry point and the suite on 3.11,
while lint and types run on 3.12 and the coverage threshold on 3.14), `git`, the Node 26 version in
`.node-version`, the pnpm version in `package.json`, and optionally the Claude Code / AGY CLIs for native
validation. See [COMPATIBILITY.md](COMPATIBILITY.md) for why 3.11 is the floor.

```bash
git clone https://github.com/spacedock-dev/compass.git compass
cd compass
# PyYAML for the contract validator; ruff, mypy and coverage for the quality gate.
python3 -m pip install -r requirements-validation.txt -r requirements-dev.txt
pnpm install --frozen-lockfile
```

Repository development skills use Git symlinks so Claude Code and Codex load one canonical body.
On Windows, enable Developer Mode and run `git config --global core.symlinks true` before cloning.
If an existing checkout shows `.agents/skills/*` as plain files, configure symlink support and clone
again; changing the setting does not repair files already checked out. See the
[Git for Windows symlink guidance](https://gitforwindows.org/symbolic-links.html).

Run the dashboard locally without installing any plugin:

```bash
python3 compass/skills/compass/server.py --port 4553
python3 -m webbrowser -t http://127.0.0.1:4553/
```

### Component stories

Run `pnpm storybook` to explore components at `http://127.0.0.1:6006/`. Storybook uses the page's
dark stylesheet and embedded local fonts. It binds loopback only and disables telemetry and update
checks. Build its static explorer with `pnpm build:storybook`; the ignored `.storybook-build/`
directory stays outside the shipped page.

Write stories in `frontend/stories/<component>.stories.tsx`. Keep one file per component under
`frontend/src/ui`; a unit test fails when a new component has no story. Add examples for its variants,
disabled and pending states, and the transitions a reader can trigger. A `play` function should use
roles and accessible names to assert keyboard operation, visible words, native field behavior, focus
return and layout stability. Assert the result of an action rather than a class name.

A story that is about a whole page state rather than one component mounts the real page over a scripted
backend. `frontend/stories/Drift.stories.tsx` does this for the Intent and drift card, one story per
stage, harness limit and route reason, on the shared harness in `drift.scenario.tsx`. Its route fixtures
live in `drift.reasons.ts`. `drift.reasons.test.ts` (run by `pnpm test`) imports the producer's
`reading_route.REASONS` and the phases a running reading publishes with Python 3.11 or newer, and fails
when a reason has no fixture or no exported story or a phase is reworded. It does not skip without Python;
set `COMPASS_TEST_PYTHON` to name one. Add the story with the reason.

After changing a component or view, update its story. Run `pnpm build:storybook`, then
`pnpm test:stories`. The tests run in pinned Chromium with one worker, fail on console and page
errors or external requests, and check the static manager and preview offline. Stories have a separate
strict typecheck with dependency declaration checking skipped because Storybook 10.6.0's declarations
fail with TypeScript 6 and exact optional properties; the page's declaration checks stay strict.
Stories are excluded from page coverage and the CSS budget. They live outside Tailwind's explicit
source paths. `pnpm build:check` checks the page and its source provenance; dependency edits
require a refreshed integrity record even when the rendered page bytes stay unchanged.

The Select story uses shadcn Base UI Select with a reserved fixture width. It exercises opening,
keyboard choice, titled long labels, disabled and loading items, and keyboard scrolling through thirty
choices. The page's PromptSelect tests and Intent browser proof own the async prompt loader. The fixture does not certify the
page's prompt loader. Stories are how the interface is verified. The browser proofs, retired from the
gate, remain runnable on demand for routing, refresh continuity, backend behavior and installed-page
investigation, but no pull request needs them.

### Frontend development

The root package builds React source in `frontend/`. Install the exact Node and pnpm versions
declared above using verified distributions; Node does not provide pnpm through bundled Corepack.
Dependency install scripts are denied, and no dependency currently has a build approval.
Tailwind 4 runs in the preview builder, the owned development worker and Vitest. Its entry imports
theme and utilities only; the existing sheets live in the `legacy` layer. Preflight is absent.
The lockfile fixes package versions and integrity hashes. Installs check engine and peer
compatibility; project commands refuse stale installs.

```bash
pnpm dev
```

This starts the real Python backend at `http://127.0.0.1:4581/` and its owned Vite module server
at `http://127.0.0.1:4582/`. Open the Python URL. React edits refresh through Vite; type `r` in
the terminal to restart Python, then reload the page for its new instance. Ctrl+C stops both.
The command uses isolated fixture locations and disables model calls, quota fetching and native
actions. It reads no personal harness transcripts, so start the ordinary launcher to see your own
sessions; it serves the React page, which is the only page there is.

Use `--python` with an absolute Python executable and `--port`/`--vite-port` with distinct ports
when the defaults are occupied. Both servers bind to IPv4 loopback and refuse a collision rather
than moving to another port. Missing tools give an error; startup never installs them.

`pnpm dev:preview` retains the standalone view preview at `http://127.0.0.1:4577/`, without the
Python backend. `pnpm build:preview` writes `.frontend-build/`; `pnpm preview` serves that build
at `http://127.0.0.1:4578/`. These preview ports are fixed too.

`pnpm build` writes the tracked self-contained React page, integrity metadata and bundled licenses
inside the plugin. `pnpm build:check` rebuilds without writing and refuses stale output. Linux is
the canonical builder; macOS CI tests the same tracked artifact. API origins and optional
terminal assets remain local. The packaging boundaries are in the
[migration contract](docs/design-frontend-migration.md#candidate-packaging).

`pnpm exec playwright install chromium` installs the browser pinned by the lockfile. See
[AGENTS.md](AGENTS.md#pre-pr-checks) for the frontend checks. TypeScript checks source and dependency
types, Biome lints (JavaScript, TypeScript and React rules) and checks formatting through one
`pnpm lint`, with `pnpm format` rewriting what it reports, Vitest with Testing Library checks visible
behavior, and Storybook checks components and views in Chromium. Vitest runs `.ts` tests under Node and
`.tsx` tests in jsdom; a `.ts` test that needs a DOM starts with an `@vitest-environment jsdom` comment, and
one that forgets fails on a missing `document`. The jsdom tests run on VM workers, which give each file its
own context only when there are at least two, so the config never runs fewer and `--no-file-parallelism`
stops with an error. `pnpm test:coverage` runs the same suite under coverage and fails below the thresholds
in `vitest.config.mts`. The rule set and what it deliberately
does not cover are in the [migration contract](docs/design-frontend-migration.md#lint-and-format). Vite and its React plugin own the build and hot
refresh. Every story is also held to a contrast floor: after its `play` function, each visible text in the
state it ends in must measure 4.5:1 (3:1 for large text and glyphs) in computed style, through
`frontend/stories/a11y.audit.ts`, so a new state needs no list entry. Text over an image or gradient is
counted as unmeasured, not passed. `Accessibility.stories.tsx` holds the fit proofs at 375, 320, 188 and 160 CSS
px and at 640 (1280 at 200% zoom lays out at 640), and the Tab order. A reading set aside is drawn grey, not
faded, because a faded colour falls under the floor. Shared controls use vendored shadcn components backed by Base UI; routing and state remain
owned by the page. Node and pnpm are build tools: the shipped
Python dashboard still requires neither.

The typed client is tested against fixtures captured from the real server. After changing a route's
response, run `python3 scripts/regen_client_fixtures.py` and commit the result; `--check` shows
whether anything is stale. The browser proofs described in the rest of this paragraph and the next are
retired from CI and from the pre-PR suite (owner, 2026-10-12): they stay runnable on demand, nothing
requires them, and Storybook verifies the interface. `pnpm test:storage:browser` proves in Chromium that the React storage codecs read
and write what the retired page did with its storage. `pnpm test:shell:browser` checks the React shell's routes
against what that page did, and `pnpm test:controls:browser`
checks that focus, drafts, composition and open selects survive live updates. `pnpm test:sessions:browser`
checks Sessions and session detail against it, and `pnpm test:terminal:browser` does the same for
the timeline filter and the output-only terminal. `pnpm test:intent:browser` checks the Intent log and the
Intent panel's editors, including native undo and IME composition, and
`pnpm test:drift:browser` does the same for the Drift section, Analyze and its consent step, the result, Steer back
and the departures, over a scripted board that never reaches a model. `pnpm test:project:browser` checks the
Projects list and each project's recovery strip, scopes, Now and Course (text, order, links and
computed layout), and that the workstream collapse, a human-context note's caret and undo, a scope and an open
plan survive live updates and navigation, with no write, copy or notification the reader did not press for.
`pnpm test:console:browser` checks the
steering bar, the tripwires, the workflow stage conditions, the Decisions tab and the Console tab
over a real backend, and that drafts, carets, an open disclosure and the retained terminal survive
live updates, a change of tab and a route away and back; it takes no native action. `pnpm test:attention:browser`
checks the Attention view and the notification control against a scripted Notification
API, and `pnpm test:capacity:browser` does the same for the capacity strip, the quota line and the goal-summary
controls, checking that every board read asks for quota until Turn off and none after, and that no model request
or notification starts without an explicit press.
`pnpm test:css:browser` is the stylesheet's readability contract on the rendered page, over the Sessions, session,
Drift, Intent, Projects, project, Attention and capacity views of the fixture boards.

Every proof above serves the React side through the development server by default. `pnpm test:production:browser`
runs the same twelve proofs with `COMPASS_E2E_BUNDLE=production`, which has the Python backend serve the minified
`react.html` that readers get (no Vite child, no hot refresh, no StrictMode double effect), so a difference only the
shipped bytes show fails a proof. Pass `--shard a` or `--shard b` to run half of them; CI runs the two halves as
separate jobs. Every surface proof is driven through the shipped page's own mount points (the capacity strip in
the Sessions view, the consent and observer controls and the terminal in the Console tab, the timeline in the
Decisions tab). Two things stay harness-hosted: the controls proof mounts the controls gallery, which composes
shared controls no one page draws together and is served a production build of a scratch copy, and the storage
proof bundles its codec minified. A few readings that only a harness can take are replaced on the shipped page
by what a reader can observe, and the proofs say so where they do it; the receipt's `production_artifact` block
lists the limits. Set the variable yourself to run one proof against the bundle, for example
`COMPASS_E2E_BUNDLE=production pnpm test:attention:browser`.

The parity proofs and the unit differentials hold the React page to what the retired page said. That page no
longer exists, so what it said is a set of recordings, and nothing starts it. Browser proofs read
`frontend/test/golden/e2e/<proof>.json` through `frontend/e2e/support/golden.mjs`; the unit differentials read
`frontend/test/golden/vitest/` through `frontend/test/legacy_goldens.ts`. These are fixtures of record. They are
never regenerated, there is no mode or environment variable that records one, and a diff to one is a mistake
to undo.

A recording is keyed by the step and the input, so a step that was renamed, an input a generator now produces
differently, or a reading that was added fails with "no golden" instead of comparing against nothing. Every
key a recording holds must be read by the run, so a removed step fails too. A few step names still say "both
pages" or "the legacy page" because a key was recorded under that text; renaming one orphans its keys. A change
that has to read something different is an edit to the proof that says so, plus an entry in
[the design record](docs/design-frontend-migration.md#held-to-recorded-answers) naming the departure and why.
Values a run invents, such as ports, clock times and ids, were normalised before they were stored, and a value
the retired page measured in pixels is compared through a distance that does not depend on the font, because the
recordings are replayed on other operating systems. The recordings are committed and small (browser proofs under
3 MB in total, unit differentials under 4 MB); do not commit a raw session or a payload from a real store.

`python3 scripts/frontend_inventory.py` checks that every row of the migration inventory
(`scripts/frontend-migration.json`) has an owner, a contract and proofs that exist as files. Nothing
measures the page's fluidity any more, and a change to the React page needs no re-measuring to merge: the
measurement tooling and its receipts were retired once the default had flipped to React, and the
[migration contract](docs/design-frontend-migration.md#fluidity-measurements) keeps the method and the
figures that were recorded.

#### Adding a shadcn component

Use the hand-written `components.json`; `shadcn init` cannot detect this layout. Preview an addition
with `pnpm dlx shadcn@4.21.4 add button --dry-run`, then apply it without `--dry-run` in the layer that
first uses the component. The CLI stays outside the dependencies. Pin Base UI to 1.8.0 when it is first
needed and refuse any `minimumReleaseAgeExclude` change. Remove the registry's `cn` dependency,
rewrite its imports to `@/lib/utils`, tune the scale and format the vendored files as described in
[the adoption procedure](docs/design-shadcn-adoption.md#the-pull-request-procedure-for-a-component).

To update an existing component, preview the pinned CLI's registry diff with
`pnpm dlx shadcn@4.21.4 add <component> --dry-run --diff`, as described in the
[CLI reference](https://ui.shadcn.com/docs/cli#add). Compare the fetched upstream content with the local file
before applying changes; preserve the local recipes and reader-state contracts, and refresh the
upstream digest in the header when taking new upstream content. Repeat the import, scale and
formatting steps above, then run the affected stories with `pnpm test:stories`.

Each copied component starts with an upstream header naming the component, CLI version, registry URL
and SHA-256 of the fetched registry item's `content` before edits. Record why local changes were made.
The packager ships the full upstream MIT text from `frontend/build/shadcn-LICENSE.txt` alongside the
package notices. The vendored directory has a Biome export-rule override; formatting still applies.

The [adoption record](docs/design-shadcn-adoption.md#toolchain-layer) owns the source boundaries and
CSS byte ratchet. Button, Accordion, Collapsible, Popover and the local `cn` are shared consumers;
`frontend/src/lib/utils.ts` configures `extendTailwindMerge` with the entry's five type steps and
four radii, so type utilities survive alongside text-colour utilities. A new step or radius must update
that configuration and its theme inventory test. The CSS browser proof measures the Button gallery's type, target size and rings
at desktop and 320 px, and compares real-route Button and disclosure trigger chrome with their pre-adoption references.
Accordion and Collapsible stay controlled by the disclosure store, use `hiddenUntilFound`, and
re-apply a matching target hash after mount. Keep their panel bodies small; content stays mounted
while closed so browser fragment revelation can reach it. Popover uses the same controlled store,
the default non-modal mode and disabled initial and final focus. Mount its portal inside `#app`
through `container`, keeping the existing link targets. Preserve all-open Escape and the
related-target blur rule through the thin compatibility handlers; outside clicks keep their
chosen destination focus. `pnpm test:popover:browser` checks close paths, forced polls, narrow
viewports, popup chrome and announcements through Chrome's accessibility tree. Live regions remain
exposed in Base UI's modal modes too, so its modal mutation also requires ordinary outside content
to remain exposed. Render a Close part inside a popup only if a future ruling adopts modal mode.

Select composes the Base UI trigger, popup and option parts. Keep the controlled value and existing
change owner at the call site. The trigger carries the focus key, and `displayGate` holds background
paints only while its popup is open, including focus in the portal. Escape closes the popup first. Input and Textarea stay uncontrolled; pass first words
as `defaultValue` and read edits through the existing owners. Do not add content-driven sizing:
field memory restores the reader's dragged height. Associate visible Label elements with native
fields. The CSS proof compares real fields with the pre-swap reference and checks their type,
44 px targets, rings and chevron clearance at desktop, 375 and 320 px, including forced colours.
Controls and Intent proofs exercise native undo/redo, IME, caret, scroll and dragged size. The
[form record](docs/design-shadcn-adoption.md#form-controls-layer) owns the cascade audit and the
explicit Base UI Select departures.

Sessions uses Badge, Card, Separator and Alert with explicit surface recipes. Preserve article and
section roots when composing Card, keep health notes as notes, and keep answer failures polite. Intent,
Drift and steering reuse those display components on their existing roots. Static log notes and
drift nudges pass `announce={false}`; consent retains its labelled group, and held field owners
remain outside the components. The [family adoption record](docs/design-shadcn-adoption.md#intent-drift-and-steering-layer)
owns their chrome reference and native decisions.
The CSS proof compares their chrome and rendered width ratios with the pre-swap page. The
[Sessions record](docs/design-shadcn-adoption.md#sessions-layer) owns the native decisions and audit.

Project, Console, Timeline, shell and terminal chrome reuse those display components. ProjectTabs
uses route-controlled Base UI Tabs with automatic activation; keep the original labelled panel,
focus keys and modified-key behavior. Static stale and terminal absence messages use
`announce={false}`, and the xterm host stays outside the components. The
[family record](docs/design-shadcn-adoption.md#project-console-timeline-shell-and-terminal-layer)
owns the cascade audit and width reference.

Attention and Capacity reuse Card on their existing queue, window and consent roots. Observer
status paragraphs use polite Alert; blocked notifications use Badge while retaining native title
text. Preserve each quota figure and its own clock, in-flow consent, the per-origin answer and
request-on-press behavior. The [family record](docs/design-shadcn-adoption.md#attention-capacity-and-consent-layer)
owns the cascade audit, hover and rail contexts, and width reference.

Utilities beat `legacy` regardless of specificity: express surface chrome in variants or props
and leave layout in the surface sheet. Update the exact count when deleting rules; a PR cannot
raise its own allowance.

`pnpm test` includes the CSS coverage tests in `frontend/build/css-coverage.test.mjs`, which compare
the current sheets with the recorded proof union. A retained rule outside that union needs an exact
`file|context|selector` entry in `frontend/css-coverage.json`'s `exceptions`, with a reason explaining
why it belongs despite the missing fixture coverage. Delete exceptions when their rules disappear or
become covered, and check the record with `pnpm test:css:coverage`. The
[cleanup record](docs/design-shadcn-adoption.md#stylesheet-cleanup) owns collection and the method's limits.

## Before you open a PR

Run the canonical pre-PR suite in [AGENTS.md](AGENTS.md#pre-pr-checks) and make sure it is clean.
It is kept in one place deliberately. A second copy here would drift, and a contributor following a
short copy passes locally and then fails the required gate.

Finish with a docs pass. Invoke the `sync-docs` skill to reconcile the documentation against
whatever your change did to the code and commit the result onto your branch, so the doc updates
ride in the same PR. `.claude/skills/` is the canonical repository-skill tree; Codex discovers the
same directories through the relative symlinks under `.agents/skills/`.

### The quality gate

`quality-gate` is a required check and covers more than the contract validator:

- `ruff check .` with `select = ALL`. The curated ignore list, with a reason for each, is in
  `pyproject.toml`. Do not add an ignore without one.
- `ruff format --check .`
- `mypy` in `--strict` mode with `warn_unreachable`.
- `runtime-floor`, which launches the shipped `server.py` entry point directly from outside the
  checkout on Python 3.11, exercises `--help` and `--diagnose --json`, and then runs the whole suite
  on the floor without coverage.
- The full unittest suite under `coverage`, against the `fail_under` threshold in `pyproject.toml`.
  That threshold only ratchets up. A PR that must merge below it needs the `coverage-exception`
  label, which is visible in the PR timeline.
- `platform-tests`, the unit suite re-run natively on macOS, with one dashboard leg and three script
  shards. Ubuntu is covered by the coverage job and the runtime floor, which both run the whole suite there.
- `Frontend (macos-latest)`, with exact Node and pnpm pins, lint, strict types, unit tests, owned
  development startup and cleanup tests, and a clean preview build.
- `Frontend tests + coverage threshold`, the Vitest suite under coverage on Linux. Statements,
  branches, functions and lines must each reach the 80% set in `vitest.config.mts`, and the same
  `coverage-exception` label is the only bypass.
- `Frontend production bundle`, which rebuilds and compares the tracked artifact on Linux and runs no
  proof.
- `Storybook (ubuntu-latest)`, which builds the offline explorer and runs every story's assertions in
  pinned Chromium. The interface is verified here. The Playwright browser proofs were retired from CI
  and from the pre-PR suite on 2026-10-12; they remain runnable on demand.

CI exercises macOS and Linux. Windows is no longer exercised by CI for the dashboard unit suite or
frontend. The local pre-PR command list remains unchanged.

Those checks run when the diff contains something they can measure. A change to prose
documentation alone skips them, because none of them reads it. The `quality-gate` check itself
always runs and always reports, so a prose-only PR is never left waiting on a check that never
arrives. `SKILL.md`, `SECURITY.md`, `README.md` and any file under `docs/` that a test opens by
name count as code here, not as prose, because `test_documentation.py` reads every one of them.
`validate` runs on every PR regardless. It resolves the Markdown links and heading anchors, and it
also runs the dashboard suite, which on a PR the detector called prose is the only place that suite
runs. Do not delete that step as a duplicate of the gate's copy. Frontend and script tests also
contribute document dependencies before the prose allowlist. The quality gate, release and
frontend build workflows count as code; unrelated workflow prose retains the short path.

`scripts/bench_collect.py` is not part of the gate. It measures what a collection costs, in total and
per harness, against your own stores: `python3 scripts/bench_collect.py --repeat 7` prints a median,
and `--profile` gives a `cProfile` of one collect by function. Reach for it before optimising a
collector, since the cost is dominated by whichever harness has the most history on the machine and
that is not the same harness for everyone. It runs with usage fetching off, so a benchmark never makes
an outbound request.

`--simulate` asks the same question of a machine you do not have. It writes a synthetic store with a
named number of in-window sessions per harness, redirects every store root at it, and runs the same
collect, so a laptop with one busy harness can still measure what a balanced five-harness machine
would cost. `--list-simulations` names the built-in mixes, or pass your own as `claude=12,codex=12`.
The report prints the sessions each collector actually returned next to the number asked for: a
generator that drifts from a store shape collects nothing and would otherwise report a confident
share of an empty store.

`scripts/command_coverage.py` is outside the gate as well. It runs the runtime's own transcript parser over a directory of Claude Code sessions (the drift replay corpus by default, `--dir ~/.claude/projects --days 30` for your own) and prints counts only: how many sessions ran a closed-list check or polled CI, how many check runs recorded a result and why the rest did not, and the most common command heads the checks list does not cover. It never prints an argument or an output line. Run it before changing what counts as a check, so the change is argued from a share and not from one session.

`scripts/capture_hook.py` is also outside the gate. It answers the adapter-semantics question for the
event-driven work: what a harness lifecycle event means, how many arrive per turn, and in what order.
None of that is documented anywhere, so it has to be observed. `--report` summarises what has
accumulated, and captures land in `~/.compass/captures`.

`--install` does not print a block to paste. It reads your existing `settings.json`, appends the
capture hook as an extra matcher group on each event, and writes the result to
`settings_with_hooks.json` beside it. Nothing is written over: read the merged file, then swap it in
yourself. Appending a group rather than editing one in place is what makes an existing hook on the same
event safe, since Claude Code runs every group whose matcher matches. Running it twice adds nothing.

It records shape and refuses content. A capture line carries the event name, the session prefix, a
salted digest of the working directory, the sorted top-level keys the payload carried, the tool name,
and how long the hook itself took. It never records a prompt, a tool argument, a tool result, or a
path. A research tool that captured those would be a worse leak than the thing it is researching,
because it writes to disk and accumulates.

`scripts/observe_journey.py` is outside the gate as well. It records what one Compass server and the
programs it starts launch and connect to, from inside that process tree and with no privilege: `run
--mode MODE` starts this checkout's server under the recorder in `scripts/owned_observer.py` and
reports against SECURITY.md's launch and send tables, and `control` proves on your machine that the
recorder loses no short launch or connection. The server it starts makes the same model calls any
run would, so opening a finished session there starts a summary, but each run has a Claude call
budget and the recorder refuses the launch past it. [The owned-process
observer](docs/design-owned-process-observer.md) owns what it sees, what it cannot, and the runs
with their budgets.

`scripts/derive_prompt_shapes.py` re-derives the counts written into the harness-injected-prompt
comment block in `compass_runtime/records.py`: which markup tag leads a harness's own machinery,
how often, and which of those a turn scanner already refuses. Point it at your own store with
`--claude-root` and `--codex-root`, or run it bare for the defaults. Every count in that comment
block is one of its outputs, so a reviewer can check the numbers instead of trusting them, and a new
harness build that changes a tag shows up as a name the vocabulary does not list.

It obeys the same rule `capture_hook.py` does, and for a sharper reason: a derivation script reads
every prompt anyone ever typed, credentials included. It prints counts and shape names only, and the
guard is a whitelist rather than a filter, so a label that is not a short markup name, a literal
already in the source, or one of a fixed set of column headings raises instead of printing. Its test
seeds a distinctive prompt into a fixture store and asserts the whole output carries none of it.
Discovering a new prose prefix is out of scope for the same reason: it cannot be done without
printing prose.

`scripts/mark_abstention.py` and `scripts/score_abstention.py` are outside the gate too, and are a
pair. The first draws cases from a running dashboard (`--build`, against `--port`, 4553 by
default), or freezes a format 5 packet from a spec of recorded moments (`--freeze`), and collects the answer key for DEC-17's abstention check, one `judge` or `abstain` per
constraint, from whoever is not the author of the reading prompt. The second runs the reading
producer over those cases and reports, per case and per constraint, where each landed. `--build`,
`--freeze` and a live `--score` need the dashboard running; `--report` and marking read local files
only. Scoring needs `--producer claude` and spends Anthropic capacity (Codex may report but not
score): one call per case whose ledger holds anything citable, charged to the one spend ledger at
`~/.cargento/drc-4666-spend.json` (the study's own home, which the rename left in place). Its ceiling is the sealed grant's: 28 under no allowance, 99 under the tenth and at most 130 under its retry, and `--max-calls` defaults to 28, so a run under the tenth passes `--max-calls 99` (anything above the grant's ceiling is refused). Run `--report` first, which spends nothing, and `--score` on purpose. Neither
runs in CI, and neither may: the marks are a person's, and the run costs the operator's own quota.
What each file may hold and where the committed half lands is in `SECURITY.md` under The abstention
check, and the committed half's own README is `docs/abstention/README.md`.

### Tests

Every behavior change to `server.py` or `compass_runtime/` needs a regression test in
`compass/skills/compass/tests/`. The suite uses only the standard library, and the fixtures are
temp directories and in-memory SQLite databases. It has three layers, and a change usually touches
more than one:

- Pure-function tests. Platform- and clock-dependent decisions take their environment as an explicit
  argument rather than reading global state (design decision D-4), so one runner exercises the
  Linux, macOS and Windows branches. Prefer this shape for anything platform-dependent. It is what
  keeps new branches from being dead code on the gate runner.
- Behavioural contracts. A realistic store fixture per harness, asserted to discover when present,
  stay quietly undiscovered when absent, survive a corrupt store without taking the other harnesses
  down, and collapse to one row when the same session exists in two candidate roots. A new harness
  also needs a hostile-path case with glob metacharacters, `%`, `#`, spaces, and non-ASCII.
- Documentation-matches-code. Store paths, relocation variables, the Python floor and the loopback
  address documented in `SKILL.md` are asserted against the implementation, so doc drift fails the
  build. Documenting a path the code does not support is therefore a test failure.

Derive a test class from `support.RuntimeTestCase` unless there is a reason not to. It patches the
native notifier, and the suite refuses a notification spawn outright, so a test that reaches
`notifications.notify_mac` for real fails with an `AssertionError` from `support.py` naming the argv
it tried to send. Four unit tests used to send audible macOS banners about sessions that never
existed, which is what the refusal is there to stop. The three classes that need the composition to
run and only the process suppressed call `support.short_circuit_native_notifications` instead.

Before trusting a new contract, mutation-check it: break the behaviour deliberately and confirm the
targeted test actually fails. This is the only way to tell a test from a decoration, and skipping it
has shipped hollow tests here more than once. Two failure modes worth knowing:

- An assertion that cannot fail. `assertIn(word, "some string")` matches substrings, so a test
  meant to prove a word survived truncation passed on a fragment of it.
- An assertion that restates the implementation. Comparing a function's output to the very table it
  reads from moves both sides together, so the check holds no matter how wrong the table is. Assert
  literals, or patch the input to values the test chose.

A flipped comparison is the cheapest mutation to try, and the most revealing: change one `<` to
`<=`, or one `and` to `or`, and run the suite. Anything that still passes is a boundary nothing
pins.

### Rules the validator enforces

- The plugin version must be identical in the Claude, Codex and Gemini manifests, and the
  description in those three plus the Antigravity `plugin.json`. Never bump versions in a PR,
  because the `version-guard` check will fail it. See [Releases](#releases).
- Skill bodies must stay host-neutral: no `${CLAUDE_PLUGIN_ROOT}`, no host-specific tool names.
  Describe capabilities, not tool APIs.
- Repository development skills live canonically under `.claude/skills/`. Every one needs an
  `agents/openai.yaml` file and a matching relative symlink under `.agents/skills/`; the validator
  rejects a copied, missing, orphaned or misdirected Codex alias.
- The skill description is at most 300 characters, and `agents/openai.yaml` keeps its 25 to 64
  character short description.
- Every relative Markdown link, in the skill and in the repository's prose docs, must resolve within
  the repository, and so must every `#heading-anchor`. Anchors are slugged the way GitHub does it,
  so a link to a heading you renamed fails the build.
- No prose doc may spell the dashboard URL with `localhost`. The server is IPv4-only, so
  it is always `127.0.0.1:4553`.
- Two link forms the checker cannot parse, both avoidable: unbalanced parentheses in a bare
  destination (wrap the target in `<>`), and links inside a four-space-indented code block (use a
  fence instead).
- Every file the dashboard needs at runtime must be present, and must be a file rather than a
  directory. The list is `COMPASS_RUNTIME_FILES` in `scripts/validate_plugins.py`: the launcher, the
  hook forwarder, all three package initializers, every runtime module and collector, and every
  frontend source asset. Adding a runtime module or asset means adding it there, and a test compares
  the list against what the checkout actually ships so it cannot fall behind quietly.
  `python3 scripts/validate_plugins.py --runtime-files <plugin root>` checks an installed copy, which
  is what the `Plugin Compatibility` canary runs against the path Codex installed.

### Design constraints for the dashboard implementation

The module map, the inward-only dependency rule, and how one process's configuration, state and
services are held are owned by
[docs/design-runtime-architecture.md](docs/design-runtime-architecture.md). Read it before adding
a runtime file or an import between two of them: the import graph is asserted by a test, and its
allowlist changes only in a PR that makes a reviewed ownership decision.

- Stdlib only, Python 3.11+. No dependencies, ever. The skill must run on a bare `python3`.
- Read-only. The server only reads harness session stores. It must never write to them or block a
  live agent's writes, so use `mode=ro` SQLite connections with short timeouts.
- Defensive parsing. A broken or unexpected harness store is skipped, never fatal. One bad record
  must not take a collector offline.
- Loopback by default. The server binds `127.0.0.1` unless the operator passes `--host 0.0.0.0`, which is theirs to pass and not yours to default. Do not widen the default in code, and never admit a Host the bind itself did not ask for. See `SECURITY.md`.
- Never interpolate a literal path into a glob pattern. Go through `glob_under()`, which escapes
  glob metacharacters in the root and sorts the result. A home directory containing `[` otherwise
  breaks discovery completely and silently, and unsorted glob output makes "newest file wins" ties
  nondeterministic across platforms.
- Build every SQLite URI with `sqlite_ro_uri()`, never an f-string. SQLite percent-decodes the path,
  and a Windows path needs separator and drive-letter conversion. Never generalize `immutable=1`
  beyond the one documented Antigravity call site: on a live agent database it can return incorrect
  results or `SQLITE_CORRUPT`.
- Never `mmap` a file a live harness is writing. Truncation mid-read is an uncatchable `SIGBUS` on
  POSIX. Tail transcripts through `reverse_lines()`.
- Compute freshness only through `age()`, `is_fresh()` and `newest_plausible()`, which reject
  implausibly future timestamps rather than clamping them. A clamped zero reads as "just now", which
  is the bug.
- Read nothing inside a project except what `SECURITY.md` § Project reads permits. Today that is
  Spacedock workflow and entity-state frontmatter, from absolute paths the session itself recorded.
  Never derive a project path by guessing, scanning or walking.
- The React page reconciles each refreshed board into its existing nodes rather than rebuilding them. What
  triggers a refresh: the leader tab holds an `EventSource` on `/api/stream` and refetches when the server
  announces a new revision, with a 20-second safety net behind it, and only a browser without `EventSource`
  falls back to a five-second poll. A refresh that unmounts something (a route change, a list that drops
  a row) still loses whatever the reader set in it, so anything the reader set needs an explicit lifetime
  outside the node that holds it.
  [The reader-state inventory](docs/design-reader-state.md) owns what is kept and by which owner, and what is
  not, including document scroll and text selection. Two rules follow. Draw payload-derived strings as React
  text: nothing sets `innerHTML`, and a test fails if code does, because session titles come from files a
  project can write. And never sort rows on a value that ticks: order on the state, then on a fixed
  timestamp, then on the session id, or rows move under the reader between refreshes.
- The retired `next` query is rejected at the page boundary, not routed to another assembly path. The React
  page keeps the `compass.next.*` and `compass.project*` browser keys the previous page wrote, so old
  bookmarks and stored leases stay harmless, and `next-*` class names and `data-next-*` attributes survive in
  its markup; do not infer a second frontend from any of them. [docs/design-next-ui.md](docs/design-next-ui.md)
  owns the promotion decision and route grammar as history. The
  [React frontend record](docs/design-frontend-migration.md) and its machine-readable
  inventory define what the frontend preserves, including the browser-only checks that unit tests
  cannot establish.
- Keep stylesheet edits inside the file of the surface you are changing (`frontend/src/<area>/<area>.css`; the
  tokens are in `@theme static` in `frontend/src/styles/tailwind.css`; page chrome is in
  `frontend/src/styles/shell.css`), including its media queries.
  [The stylesheet contract](docs/design-next-ui.md#nui-2-one-stylesheet-owns-the-interface) records the
  dark-only palette and the type floor, which the React sheets keep. Board sentences use
  `--fs-body` (0.9375rem); compact labels and source metadata sit on one tier, `--fs-label`
  (0.8125rem). The scale is rem against a `100%` root, so the board follows the reader's own
  font-size setting; the rem figures are computed against 16px, which is what makes a default
  browser render what it always did. Borders stay px on purpose: a hairline in rem blurs.
  Every `font-size` is one of the five scale steps, `inherit`, `100%` or zero: `frontend/src/styles/css.test.ts`
  compiles the entry in memory and bans a pixel size, a step below 13px, a remaining `@import`, a remote or
  relative `url()` (quoted or not), a `prefers-color-scheme` rule and a broken or cyclic `var()`. It reads the
  compiled declarations, so it
  cannot see a rule that reaches an element through ancestors the selector never names. `pnpm test:css:browser`
  asks the browser's own cascade the same questions of every route and tab the fixture boards draw: nothing
  below the 13px step, sentences on the 15px step, absences sans and in the absence ink and never larger than
  what they replace, labels in the label register, actions on the sentence step, and a focus ring on every
  focusable element. A sentence that must sit at 13px, an absence that must stand at a figure's size or a
  control that relies on the browser's focus ring is named, with its reason, in the inventories at the top of
  `frontend/e2e/css-contract.mjs`; the sets are exact, so a new shape fails and so does a stale one. New sizes
  still need a named role.
- Reach an ink through its role register, not through its hex. `--ink-label`, `--ink-value`,
  `--ink-absence` and `--ink-caption` are declared in the static theme of `tailwind.css`. Three of the
  four resolve to the same ink on purpose; the stylesheet contract says why, and why an absence separates
  on shape rather than on brightness. `pnpm test:css:browser` holds it on the rendered page: label,
  absence and caption share one register, the value ink is another, and the third ink is spent only on what is
  inactive.
- Preserve the fixed palette's contrast. Every text ink measured above 4.5:1 against `--bg`, `--panel` and
  `--sunk` when the palette was set, and no test rechecks it, so recheck when you change a token. A selected
  state must stay distinguishable from an unselected one: the former dashboard's panel-on-background
  treatment measured 1.2:1 and made on and off indistinguishable. Its metadata ink once measured 3.1:1, below
  AA, on the smallest type.
- Test the page by running it, not by matching strings against its source. Component and model tests
  render the real component with Testing Library in jsdom and fire a click or a keystroke (`pnpm test`),
  and the browser proofs (`pnpm test:*:browser`) cover what jsdom cannot: native undo, IME composition, an
  open select list, layout and focus. A source-text assertion passes forever after the behavior behind
  it breaks.
- Load and verify the frontend before creating the daemon log, binding the socket, forking, or
  spawning a Windows child. Then acquire the log file and listening socket before forking (or, on Windows,
  before waiting on the re-spawned child). After the fork there is nowhere for a failure to go.
  Reporting one means pointing the user at the very log that could not be opened. Note that
  `os.makedirs(exist_ok=True)` is not this check: it succeeds for a directory that already exists
  whatever its mode, which is the likeliest bad state of all.
  Every asset the page needs must load before bind. A broken React build refuses and says to reinstall
  the plugin; it never serves a stand-in or starts a Node build. There is one renderer, so no option
  or environment variable selects it, and `--frontend` is refused.
- Never use `os.kill`, including `os.kill(pid, 0)` for liveness. CPython implements it on Windows
  through `TerminateProcess`, so a liveness check would kill the process it was asked to inspect.
  Probe `/api/health` instead.
- Stopping goes over HTTP, and a handler that stops the
  server must do it on its own thread. Not because a `ThreadingHTTPServer` handler would deadlock
  calling `server.shutdown()` inline. It would not, since every request already runs on its own
  thread and the accept loop is never the caller. The reason is that `shutdown()` blocks until the accept
  loop notices, up to one poll interval, and the client should not be held open for that just to hear
  "stopping".
- Because of that delay, nothing may report a stop as *finished* until the port is free. Ask by
  binding the port, not by connecting to it: a connect to a bound socket that nothing is accepting
  from still succeeds, and repeated connects fill the backlog and then report the port gone while it
  is still bound.
- Guard the sink, not the caller. A check against work landing after teardown belongs in the function
  that actually writes the DOM, the file or the socket: `render()`, not `refresh()`. Guarding a
  caller was wrong twice for the same stop button: first it missed the request already in flight,
  then it missed the other fourteen callers, one of which was a keystroke. If you do also guard a
  caller, it must be for something the sink cannot see, and say so.

The reasoning behind these, and the alternatives that were tried and rejected, is in [docs/design-cross-platform.md](docs/design-cross-platform.md); for the Spacedock reader, [docs/design-spacedock.md](docs/design-spacedock.md); for how a row is labelled and identified, [docs/design-session-identity.md](docs/design-session-identity.md); and for `--daemon`/`--status`/`--stop`, [docs/design-daemon.md](docs/design-daemon.md).

## Commits

We require [DCO](https://developercertificate.org/) sign-off and use conventional commit messages:

```bash
git commit -s -m "feat(skill): add new harness collector"
```

Format: `<type>(<scope>): <description>`, where type is one of `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

## Pull requests

1. Fork (or branch, for maintainers) and make your change.
2. Run the pre-PR suite in [AGENTS.md](AGENTS.md#pre-pr-checks), then invoke the `sync-docs` skill.
3. Open a PR against `main`. `main` is protected: PRs are required, the `validate`, `version-guard` and `quality-gate` checks must pass, history is linear (squash/rebase), all conversations must be resolved, and merged branches are deleted automatically.
4. If your PR closes an issue, use an explicit `Closes #NNN` line, one line per issue. A comma-separated list does not autoclose.

## Adding support for a new harness

This is the contribution we most want. Each harness is one registry entry: a key, a display label, a cheap discovery predicate, and a collector function. The runtime contract is `HarnessSpec` in `compass_runtime/aggregate.py`, whose discovery takes `(config, state)` and whose collector takes `(config, state, now, window_hours, show_all)`. The registry itself is `aggregate.default_harnesses()`, and every row is a module under `compass_runtime/collectors/`: add yours there, then add a row. Follow `collectors/codex.py` for the shape, and study `collectors/droid.py` (JSONL-based) or `collectors/goose.py` (SQLite-based) as templates. Requirements:

- Discovery must be cheap (an `isdir`, or one of the existence probes: `any_store_dir()`, `any_glob_under()`, `any_glob_stores()`). It answers one bit, so it must not build a match list it will not read, and `collect()` walks the same tree moments later anyway. The collector must degrade gracefully on schema drift.
- Resolve store roots through the candidate-set resolver rather than a single hardcoded path, and honor the harness's documented relocation variable if it has one.
- Document the data source and its caveats in `SKILL.md`'s data-sources list. The documentation-matches-code test asserts it.
- Add tests with a synthetic store fixture, including a hostile-path case.
- No frontend registry entry is needed. The page reads harness keys and labels from the payload's
  `harnesses` list, which is derived from `default_harnesses()`.
- Every row's field set is declared once, in `base_session` in `compass_runtime/sessions.py`, at `None`. Populate the fields your store can answer and leave the rest; do not add a key that only your harness sets, because then every consumer has to test for presence instead of for a value. `provider` and `model` are there for the same reason. `provider` is Pi's alone, since Pi is the one harness that spends another product's allowance rather than its own; `model` is filled by whichever collectors can read one.

Before writing any of it, settle whether the thing deserves a row of its own: two store formats can be one harness, and one vendor can be two. [`docs/design-harness-registry.md`](docs/design-harness-registry.md) owns that judgement and the one time it had to be revisited.

### Adding a quota source

A harness row can also publish quota, through the optional `usage` provider on `HarnessSpec`. There are three shapes, and which one applies is a question about the vendor rather than a choice: read it from the harness's own store (Codex, Copilot), fetch it with the harness's own credential (Claude, Cursor), or receive it from a harness that pushes its quota to a user-configured command (Antigravity). A fetch also sets `usage_is_fetch`, which is what raises the disclosure banner, and adds a row to `FETCH_VENDORS` in `quota.py`.

Two obligations are not optional. Name the endpoint and the credential location in `SECURITY.md` in the same PR as the code, because that section is the contract the fetch is held to. And capture a real payload from a live install before writing the parser: every quota source added so far had a field name, a unit, or a rendering that the vendor's own documentation got wrong, and the failures were silent ones (a counter reading zero, an amount in cents read as dollars). [`docs/design-usage-quota.md`](docs/design-usage-quota.md) records each of those and the surfaces that were tried and rejected.

## Releases

Releases are tag-driven and fully automated (maintainers only):

```bash
git checkout main && git pull
git tag v0.2.0        # v-prefixed is canonical; bare 0.2.0 also works, but pick ONE form per release
git push origin v0.2.0
```

The [Release workflow](.github/workflows/release.yml) refuses the tag unless it is on main, is
strict semver, and is strictly greater than every existing release tag. Semver only moves forward,
and back-tagging is impossible. It then fixes one commit to release and verifies exactly that commit
in jobs that hold no credentials: the frontend is rebuilt and compared with the tracked bundle, and
the contract validator, the bump-version and validator tests and the dashboard suite run on it.
That is not the whole quality gate, which already ran on every commit that reached main. Only the
final job holds the release deploy key, and it runs no Node or frontend dependency code. It refuses to
continue if main moved while the verifiers ran, writes one bump commit updating all owned version
fields, proves the archive of that exact commit with Python only, then moves the tag onto the
released commit, advances the `stable` branch to it (forward only, never back to an older release),
and publishes a GitHub Release with generated notes. `stable` is what the shared
[spacedock-dev/marketplace](https://github.com/spacedock-dev/marketplace) listing tracks, so a
release that did not move it would leave the marketplace serving an older Compass.
Beside that, four jobs with no credentials build the standalone `compass` binary with PyInstaller,
one on each OS and architecture, and the release waits for all four, so a failed build stops it
before anything is published. After the release is created, a separate job that holds the write
token but not the key attaches the four archives and `checksums.txt` to it, and another job with a
read-only token and a key to the marketplace repository alone stamps the new version onto Compass's
marketplace listing. A last job, once the archives are attached, holds a read-only token and a key to
the Homebrew tap alone, and writes `Formula/compass.rb` there from the release's published
`checksums.txt`. The `CLI package`
workflow runs the same build on pull requests that touch the runtime, so a break shows up in review.
The bump is skipped when the manifests already carry the tagged version, which is also how you
release the current version as-is. Every step is idempotent, so a partially failed release is
finished by **Re-run all jobs** on the same run. That is the only re-run that resolves the release
target again: **Re-run failed jobs** keeps the first target and fails again once main has moved, and
pushing the tag a second time does nothing because it already exists. Release tags are immutable (a
tag ruleset blocks deleting or moving them), and PRs can never change version fields (the
`version-guard` check).

To rehearse the sequence without GitHub, run `python3 scripts/release_transition.py --repo <throwaway
clone> rehearse --tag v0.2.0 --dry-run` in a clone whose remote is a local bare repository; it
refuses any remote that is not a local path. The `compass-release` skill describes it, and the
archive proof `scripts/verify_release_archive.py`, in full.

## Reporting bugs and requesting features

Use the [issue templates](https://github.com/spacedock-dev/compass/issues/new/choose). For security concerns, see [SECURITY.md](SECURITY.md), and please don't open public issues for those.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be excellent to each other.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
