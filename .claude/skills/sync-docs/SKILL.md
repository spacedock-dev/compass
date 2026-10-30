---
name: sync-docs
description: Use when reconciling Compass's docs before a pull request or release, or whenever the repository documentation may be stale.
---

# sync-docs

Keep the docs true to the code and free of bloat. This is a **docs-only** skill: it never changes
Python, manifests, workflow YAML, or version fields — only Markdown. Each run is a
diff-and-reconcile pass, not a rewrite.

## Hard boundaries — this repository will reject you otherwise

- **Never touch a version field.** The plugin version appears in
  `compass/.claude-plugin/plugin.json` (the source of truth), `compass/.codex-plugin/plugin.json`
  and `compass-gemini/gemini-extension.json`, and is owned by the tag-driven Release workflow. The
  `version-guard` check fails any PR that changes one. Never write a version literal into Markdown
  either — it would drift permanently and unwatched. Illustrative tags (`git tag v0.2.0`) are fine.
- **Never change the plugin description casually.** It must stay byte-identical across five
  manifests; `scripts/validate_plugins.py` enforces parity. If a correction genuinely requires a new
  description, change all five in the same commit — or leave it and report it as unresolved.
- **Never edit application code**, even to make a doc claim true. If a doc is right and the code is
  wrong, report it; do not fix it here. The one exception is a comment that cites a document you
  deleted or renamed — repointing that reference is part of the deletion (step 5).
- **Never weaken a validator rule to make an edit pass.** If a doc fix and a validator rule are
  jointly unsatisfiable, stop and surface it rather than leaving a required check red.
- **Respect the exclusion list** below. Some Markdown here is an input to a program, not prose.

## When to run

- **Before opening a PR** (the primary trigger). Per `AGENTS.md`, invoking the `sync-docs` skill is a step in the
  branch → commit → validation suite → **sync-docs** → push → `gh pr create` workflow, so the doc
  updates for a change ride in the same PR and the docs never drift between merges. Scope the pass
  to what your branch touched (step 1).
- Periodically, or before tagging a release, as a full reconcile even without a code change.

## The doc-ownership map — consolidate, don't proliferate

| File | Owns | Rule |
|------|------|------|
| `README.md` | The front door: what Compass is, prerequisites, per-harness install, the skill inventory table, a short "how it works", links out. | Keep short. No command suites and no reference tables — link to the owner. **Validator-asserted:** the literals `/compass:compass` and `codex plugin add compass@compass-marketplace` must appear verbatim; rewording either fails the required `validate` check. |
| `docs/how-it-works.md` | The user-facing walkthrough: what runs where, what can leave the machine and how to stop it, the dashboard's tabs and a session's page, and a worked drift check, with Mermaid diagrams. | Plain and visual. SECURITY.md stays the authority on outbound traffic and MANUAL.md on options; this page summarises and links to them. The README's "How it works" section is a short summary that links here. User-facing: no tracker keys. **String-asserted:** `TheLiveMonitorIsSaidToCallAModelTest` requires its Live monitor sentences (`Live monitor · Haiku`, about once a minute, the accuracy check not yet run). |
| `MANUAL.md` | The standalone `server.py` CLI reference: all options and aliases, defaults, interactions, environment, files, exit status and examples. | Reconcile against `cli.build_parser`, runtime configuration and lifecycle behavior when the CLI changes. `CommandManualOptionsTest` checks the option-row inventory, not the semantics. Link to HOW_TO_USE for configuration tasks and SECURITY for exposure/consent contracts. The installed skill retains its own portable reference because the manual is not shipped. |
| `HOW_TO_USE.md` | What the reader configures by hand, one task per section: registering the stdio MCP server per harness, the hooks and status line the plugin cannot install, and resolving the installed plugin path every one of those snippets needs. | Task-oriented, and **every command and snippet must have been run before it is written down**: nothing in CI checks a command block, so an unrun one ships wrong. It may name repository paths and real config paths, which is exactly why it exists, since the shipped skill body is forbidden both. It owns no contract and no install steps. **Frozen path** once it is in `ROOT_DOCS`, and any heading `COMPATIBILITY.md` cites is frozen with it. |
| `AGENTS.md` | **Canonical** repository contract and the source of truth for process: architecture tree, doc map, commit conventions, PR workflow, the pre-PR command list, the quality gate, versioning/releases, portability rules. | Every process command list is defined here once; other docs link. `CLAUDE.md` imports it, so edits propagate. Never rename or move it — Codex and Claude both load it by name. |
| `CLAUDE.md` | Claude-Code-only addenda. | Line 1 must stay the bare `@AGENTS.md` import. Nothing that would also be true in Codex — that belongs in `AGENTS.md`. |
| `CONTRIBUTING.md` | The human contributor journey: clone → dev setup → run locally → the quality gate → tests → what the validator enforces → `server.py` design constraints → commits → PRs → adding a harness → releases. | Task-oriented. Reference the pre-PR suite in `AGENTS.md` rather than re-listing it; duplicated command lists are how they drift. |
| `COMPATIBILITY.md` | **Canonical** cross-harness and cross-platform contract: the per-runtime surface matrix, the per-OS capability matrix, the platform caveats, the native per-runtime validators, and **the Python floor** (with the list of every other place it is restated). Carries the sync marker. | Matrices and their footnotes. *Why* a row reads the way it does belongs in `docs/design-*.md`. |
| `SECURITY.md` | Security posture: the invariants, the known-and-accepted exposures, and private reporting. Covers the whole shipped surface — `server.py` **and** `notify_hook.py`. | Anything that weakens an invariant is a security bug and belongs here. Keep the contact address equal to the one in `CODE_OF_CONDUCT.md`; nothing checks it. |
| `compass/skills/compass/SKILL.md` | **Canonical** product surface: per-harness data sources, session states, start/stop, notifications, options, interpretation notes, common mistakes. | A *shipped, validated artifact* — see the constraints below. It is installed without the repository, so it must never contain a repo-relative link or repo process. |
| `docs/promise-map.md` | **Canonical** user-facing promise: the five questions of a user's day, one promise each, the shipped capability that backs it, and the limit that keeps it honest. | A promise may not enter it before the capability ships, and the wording of each promise is duplicated verbatim in `docs/visibility-2x2/items.json` (`columns[].promise`) and in the Linear project description. Change one, change all three. [Development tracking](../../../docs/development-tracking.md#how-work-links-to-a-promise) owns promise IDs and the move taxonomy; keep them out of user-facing tracker prose. |
| `docs/development-tracking.md` | **Canonical** development taxonomy: promise IDs, journey labels, board columns, moves and tracker copies. | Preserve development provenance here; the public promise map owns reader-facing behavior and limits. |
| `docs/design-runtime-architecture.md` | **Canonical** module map: what each runtime file owns, the inward-only dependency rule, top-level import identity, and the config/state/application split. | Other design docs link here for the module map instead of restating it. The import allowlist it describes is asserted by a test. |
| `docs/design-*.md` | The durable *why/how* per area — decisions that outlive the build, **including alternatives that were tried and rejected and the reason why**. | A decision earns a place here if re-deriving it would cost a day, or if a maintainer would otherwise re-attempt something already proven wrong. |
| `docs/plans/*.md` | **Transient** plans for *unshipped* work only. | Once the work ships, fold the durable *what* into the owning doc and the durable *why* into `docs/design-*.md`, then **delete the plan file.** |
| `.github/PULL_REQUEST_TEMPLATE.md` | The PR author's checklist. | Must mirror the real gate in `AGENTS.md` — if the gate gains a step, this gains a checkbox. Never rename; GitHub loads it by path. The HTML comments are deliberate hints. |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1, verbatim. | **Never edit the text.** Only the enforcement contact is ours. |
| `.claude/skills/*/SKILL.md` and `.agents/skills/*` | Repository development skills, including this one. Not shipped with the plugin. | `.claude/skills/` is canonical. Each `.agents/skills/` entry is a relative symlink to its matching canonical directory so Codex and Claude Code read one body. Each canonical skill directory contains its own `agents/openai.yaml`. The banned portability literals are legal here because this tree is not shipped; the validator link-checks the canonical files but does not marker-scan them. |

### Constraints on `compass/skills/compass/SKILL.md`

`scripts/validate_plugins.py` scans every Markdown file under `compass/skills/`, and
The dashboard test suite asserts the skill body against the code. Both are required checks:

- Frontmatter fields are exactly `name`, `description`, `license` — nothing else, no duplicate keys.
  `name` must be lowercase kebab-case and equal the directory name.
- `description` is required, **at most 300 characters** (300 exactly passes), and may not contain
  `<` or `>`.
- The body must stay host-neutral. These six literal substrings are rejected anywhere in the file:
  `${CLAUDE_PLUGIN_ROOT}`, the user-cache skills path, `mcp__claude_ai_`, `ToolSearch(`,
  `Skill(skill=`, `subagent_type`. *(That second one is why this skill's own path must never be
  pasted into the skill body — write it out in prose instead.)*
- Every relative Markdown link and `#heading-anchor` must resolve inside the repository. In
  practice: **do not add links to repo files at all**, because the plugin is installed without the
  repository around it.
- The documentation-matches-code test additionally requires: every backticked `~/…` path must
  prefix-match (in either direction) a real `resolve_store_roots` output, except `~/.claude/settings*`
  which is carved out; the set of backticked store environment variables must **equal**
  `STORE_ENV_VARS` in the code; the literal `Python 3.11+` must appear; and the body must contain
  `http://127.0.0.1:4553` and must not contain the equivalent `localhost:4553` URL. The repository
  validator applies that same ban to every prose doc — including this file, which is why the banned
  spelling is not written out here.

After any edit under `compass/skills/`, run `python3 scripts/validate_plugins.py` and
`python3 -m unittest discover -s compass/skills/compass/tests -t .` before committing.

## Public text boundary

Follow [AGENTS.md's public documentation rule](../../../AGENTS.md#public-documentation-and-release-notes).
User-facing docs and release notes contain no Linear names, issue keys or tracker URLs, including
fenced examples, reference links, HTML and copied/generated text. Keep the security fact, date,
ruling and limit; replace its tracker pointer with the durable public contract or a plain behavior
statement. Do not delete development provenance from allowed records to make the public scan quiet.

Unknown/new Markdown defaults to user-facing. Shipped Markdown and the promise map are always
user-facing. The shared study entry point, participant kickoff and exploratory prompt remain
user-facing even inside the evidence tree; facilitator protocols and run records are development
records. The validator's explicit audience classifier owns the exceptions. Internal issue links
remain legal in development records and PR bodies.

Repository validation scans full raw public text. Use the validator's standalone `--public-text FILE`
mode for the entire proposed release/announcement body, including generated sections, before
publishing. An external body must be read back and checked after publication; the repository scan
cannot inspect it. Moving the promise taxonomy also requires repointing all development consumers
to [its owner](../../../docs/development-tracking.md#how-work-links-to-a-promise) while keeping the
five canonical promise sentences unchanged.

## Voice and tone

The prose docs are written for people, and they were humanized in one deliberate pass. An agent
topping them up in model-default voice, one sync at a time, is how that gets undone. Step 7 of the
Procedure exists to stop it, and check (e) in step 10 is the mechanical backstop, since nothing in CI
enforces tone.

**This section is the contract, not the `humanizer` skill.** That skill automates the pass and is
worth using where a harness has it, but this repository does not vendor it and a clean checkout will
not have it. Everything needed to apply the standard by hand is written out below, deliberately, so
the rule survives the tool going missing.

In scope, and the exact set check (e) greps:

```
README.md  MANUAL.md  HOW_TO_USE.md  CONTRIBUTING.md  COMPATIBILITY.md  SECURITY.md  docs/how-it-works.md  docs/promise-map.md  docs/design-*.md  docs/plans/*.md
```

Out of scope, deliberately: `AGENTS.md` and `CLAUDE.md` (agent contracts loaded verbatim as
instructions), `compass/skills/compass/SKILL.md` (a validated artifact with test-asserted
literals, shipped to other harnesses as agent instructions), and this file. Leave their voice alone.

The standard, in order of how often it is violated:

- No em dashes, en dashes, or curly quotes. This is the hard one, and the one check (e) catches.
  Use a period, a comma, a colon, or parentheses instead.
- No mechanical boldface, and no inline-header lists (`- **Thing:** the thing is...`). A list is
  fine; bolding the first two words of every item is the tell.
- Sentence case in headings, not Title Case.
- Prefer `is`/`are`/`has` over "serves as", "stands as", "boasts", "features".
- Cut the AI-vocabulary words: crucial, pivotal, seamless, robust, leverage, delve, showcase,
  underscore, testament, landscape (figurative), tapestry.
- No participle tails bolted on for depth ("..., ensuring reliability", "..., highlighting its
  importance").
- No generic upbeat closers. End on the last concrete fact.

Two things not to do in the name of tone. Never drop a fact to make a sentence flow, and never add
one to make it land: the pass keeps the information and changes only the shape. And do not
flatten the specifics that make these docs worth reading. The measured numbers, the named failure
modes, and above all the rejected-alternatives lists in `docs/design-*.md` are the human signal, not
the noise.

## Markdown that is not documentation — never reconcile these

Some Markdown here is consumed by a program, reproduced verbatim from upstream, or generated.
Editing it changes behavior or breaks a licence, silently.

| Path / pattern | Why it is off-limits | Allowed action |
|---|---|---|
| `CODE_OF_CONDUCT.md` | Verbatim Contributor Covenant 2.1. The version is pinned by the README badge and by the self-attestation near the end. | Fix the enforcement contact only. Never reword the covenant. |
| `LICENSE`, `NOTICE` | Apache-2.0 text and its §4(d) attribution. Extensionless, so no `*.md` sweep reaches them — but a "tidy the docs" pass can. | None. Edits are legal changes. |
| `.github/ISSUE_TEMPLATE/*.yml` | GitHub issue *forms*: prose inside a validated schema. | Edit `label` / `description` strings only; never touch keys, `id`s or `labels:`. Keep the harness options aligned with the registry, but do not delete the non-harness catch-all option. |
| `.github/ISSUE_TEMPLATE/config.yml` | Chooser config. Its `name`/`about` strings do render, but the security-advisory URL is load-bearing. | None — and if it must change, keep it consistent with `SECURITY.md`. |
| `coverage-comment.md` | Written by a CI step and read back by the next one; its marker comment must stay byte-identical to what the comment action matches on. Untracked. | Never. If it appears locally it is CI debris. |
| Markdown under `**/tests/**` or created by a fixture | Test input; its content is asserted on. | Never. New fixtures must live **outside** `compass/skills/`, or the validator will scan them and fail the build. |
| `compass/commands/*.md` | Rejected outright by the validator as legacy commands. | Never create Markdown there. |
| `.git/`, `.mypy_cache/`, `.ruff_cache/`, `__pycache__/`, `node_modules/`, `.venv/` | Not source. | Never. |

### Classifying Markdown this table does not list

Before editing any `*.md` you have not touched before, run the checks — never judge by filename:

```bash
F=<path>
# 1. Tracked? Untracked Markdown is generated or scratch until proven otherwise.
git ls-files --error-unmatch "$F" >/dev/null 2>&1 || echo "UNTRACKED — establish why before editing"
# 2. Does a program reach it? Search the basename outside Markdown.
grep -rn --exclude-dir={.git,.mypy_cache,.ruff_cache,__pycache__} -F "$(basename "$F")" \
  --include='*.py' --include='*.yml' --include='*.yaml' --include='*.json' --include='*.toml' .
```

Then apply, in order:

1. **A hit is a candidate, not a consumer.** It is a consumer only if the path is opened, read,
   globbed, counted, or asserted on there. A filename inside a comment or an error string is not.
   Open the hit and read it. Then split the verdict by *what* is consumed: a file whose mere
   existence or links are checked has a **frozen path but editable content** — deleting or renaming
   it fails the build, editing it does not. A file whose *strings* are asserted has those specific
   strings frozen. Every entry in `ROOT_DOCS` in `scripts/validate_plugins.py` is in the first
   category; `README.md` and the shipped skill body are in both.
2. **Location outranks content.** Anything under `compass/skills/` is a shipped artifact and gets
   the full constraint set above, including `references/` or `operations/` files that do not exist
   yet. Anything a required check asserts against code is system-consumed even when it reads like
   prose — in this repository that is the skill body and `README.md`.
3. **Convention-located files keep their exact path.** `AGENTS.md`, `CLAUDE.md`, `SECURITY.md`,
   `CODE_OF_CONDUCT.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/*`, and every
   `SKILL.md`. "Grep found no consumer" means nothing for this class.
4. **Verbatim upstream is never-touch — but match the whole document, not a mention.** The test is
   whether the file *is* the upstream artifact, not whether it links to one. `README.md` and
   `CONTRIBUTING.md` both link the licence and are ordinary docs.
5. **A command block under a "Validation", "Test plan" or "Pre-PR" heading is executable content.**
   Every line must stay literally runnable, and the block must be complete relative to the real
   gate. Do not reword a command for readability.
6. **Stable in-document identifiers are part of the contract.** Decision IDs (`D-1`…`D-6` in
   `docs/design-*.md`) and heading anchors are cited from code comments and from other docs, and
   only the anchors are gate-checked. Before renumbering or renaming one, grep the identifier across
   `*.py`, `*.toml` and `*.md` and repoint every citation — or don't renumber.
7. **Most restrictive wins; never-touch beats everything.** Where two rules conflict irreconcilably,
   stop and ask.

When in doubt, leave the file alone and list it under `Unresolved:` in the report. A missed doc
update is cheap; a silently broken fixture or system prompt is not.

## Extract the "code truth"

Run these from the repository root; the output is what the docs MUST match.

```bash
S=compass/skills/compass/server.py
A=compass/skills/compass/compass_runtime/aggregate.py
C=compass/skills/compass/compass_runtime/config.py
R=compass/skills/compass/compass_runtime/state.py
W=compass/skills/compass/compass_runtime/web
G=compass/skills/compass/compass_runtime/diagnostics.py
H=compass/skills/compass/compass_runtime/http_api.py
L=compass/skills/compass/compass_runtime/lifecycle.py
I=compass/skills/compass/compass_runtime/cli.py

# HTTP routes the server actually serves, split by method, and who owns the
# listener. Read by AST over the three functions that dispatch, because no
# single grep survives this file: GET compares `url.path` in `_get_api` (not in
# `do_GET`, which only owns "/"), one GET and one POST route are prefix matches
# rather than comparisons, and `do_POST` dispatches through a DICT LITERAL. A
# comparison-only pattern therefore reports the GET routes and silently finds
# NONE of the nine POST ones, which is how SECURITY.md's "nine POST routes"
# came to be unverifiable from this block. Cross-check the count: SECURITY.md
# states it, and states how many of them carry a capability.
python3 - "$H" <<'ROUTES'
import ast
import pathlib
import re
import sys

source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
lines = source.splitlines()
owners = {"do_GET": "GET", "_get_api": "GET", "do_POST": "POST"}
found: dict[str, set[str]] = {"GET": set(), "POST": set()}
for node in ast.walk(ast.parse(source)):
    if isinstance(node, ast.FunctionDef) and node.name in owners:
        body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
        found[owners[node.name]].update(re.findall(r'"(/(?:api/)?[a-z/<>-]*)"', body))
for method, routes in found.items():
    print(f"{method}: {len(routes)}")
    for route in sorted(routes):
        print("   ", route)
ROUTES
grep -nE '^(class CompassHTTPServer|class _RequestHandler)|^def (normalize_host|reuse_address_allowed|bind_error_message)' "$H"
# CLI flags and their defaults. These live in cli.build_parser now, not in the
# launcher: `server.py` is seven lines and greps of it silently find nothing.
grep -E -A4 'add_argument\(' "$I" | grep -E '"--|default='
# The launcher contract: one import of cli.main and nothing else.
cat "$S"
# The harness registry: one row per supported harness, in the order the page
# renders its chips. Read it from `aggregate.default_harnesses` rather than by
# matching source text, because the rows are multi-line. The third column is
# each callback's defining module. Every row must resolve under
# `compass_runtime.collectors`, with no exception: Claude's used to be a
# wrapper the registry built to bind a popup notifier, and the popup decision
# now belongs to `Application` instead.
python3 - "$A" <<'PY'
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(sys.argv[1]).parents[1]))
from compass_runtime import aggregate

for spec in aggregate.default_harnesses():
    print(f"{spec.key:10} {spec.label:10} {spec.collect.__module__}")
PY
# Lifecycle operations, and the one respawn contract --daemon uses on Windows
grep -nE '^def (tcp_port|compass_home|state_path|log_path|write_state|read_state|probe_port|port_released|await_release|instance_status|render_status|stop_instance|fork_daemon|await_daemon|spawn_argv|spawn_detached|await_spawned|prepare_daemon_home|serve)' "$L"
# The application boundary and the registry contract it consumes
grep -nE '^(class Application|class HarnessSpec)|^def default_harnesses|^    def collect' "$A"
grep -nE '^HARNESSES|^def (_legacy_application|_bound_popup_notifier)' "$S"
# What --diagnose reports, and the pinned order it reports stores in
grep -nE '^(_REPORT_KEY_ORDER|def (store_primaries|candidate_report|diagnose|render_diagnosis))' "$G"
# Store-relocation environment variables the resolver advertises
grep -nE '^(STORE_ENV_VARS|COMPASS_HOME_ENV) = ' "$C"
# Immutable configuration fields, builders, and locked defaults
grep -nE '^(class RuntimeConfig|def (build_runtime_config|resolve_store_roots|store_roots|primary_store))' "$C"
awk '/return RuntimeConfig\\(/,/^    \\)/' "$C"
# Mutable state fields, lock/dictionary factories, and builder/helper bodies
sed -n '/^class CollectMemoEntry/,$p' "$R"
# Python floor: the ruff target and the mypy pin must agree, and match the docs
grep -nE 'target-version|python_version|fail_under' pyproject.toml
# Frontend identity: the served page is `react.html`, verified against `react.integrity.json`.
# `pnpm build:check` proves the tracked bundle matches the sources in `frontend/`.
python3 - "$W" <<'PY'
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

web = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("compass_web_page", web / "page.py")
assert spec and spec.loader
page_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page_mod)
page = page_mod.load_frontend_page()
print("served page", len(page), hashlib.sha256(page).hexdigest())
metadata = json.loads((web / "react.integrity.json").read_text(encoding="utf-8"))
print("document", metadata["document"]["bytes"], metadata["document"]["sha256"])
print("fonts", len(metadata["provenance"]["fonts"]), "sources", len(metadata["provenance"]["sources"]))
PY
# The real CI command surface
grep -nE '^\s+(- name:|run:|  +[a-z].*)$' .github/workflows/quality-gate.yml | grep -E 'ruff|mypy|coverage|unittest|validate_plugins'
grep -nE 'run: ' .github/workflows/validate.yml
# What the validator enforces on documentation
grep -nE 'PORTABILITY_MARKERS|SHARED_FRONTMATTER_FIELDS|ROOT_DOCS|BANNED_DOC_LITERALS|validate_repository_skills|maximum is 300' \
  scripts/validate_plugins.py
```

Cross-check every count a doc states — "eight harnesses", "five places", a port, a threshold in
minutes, a Python version. Stale counts are this repository's most common drift.

## Procedure

1. **Scope the diff.** Find what landed since the last sync. Drive this off the
   `docs-synced-through` marker at the bottom of `COMPATIBILITY.md`, **not** off the last commit
   that touched the file — once any commit on this branch edits `COMPATIBILITY.md`, that commit
   *is* the last one to touch it and the range collapses to empty exactly when you need it:
   ```bash
   MARKER=$(grep -oE 'docs-synced-through: [0-9a-f]+' COMPATIBILITY.md | awk '{print $2}')
   git log --oneline "${MARKER:-origin/main}..HEAD"
   git log --stat "${MARKER:-origin/main}..HEAD" -- '*.py' '*.toml' '*.yml'
   ```
   The `--stat` output tells you which subsystems moved, so you know where to look; the extraction
   above is the ground truth. If the marker is missing or unresolvable, fall back to
   `origin/main..HEAD` and say so in the report.
2. **Reconcile each doc against the code truth.** Every real item must appear correctly wherever it
   is documented, and every doc claim must still match the code. Build the full checklist of edits
   before making any. **Prune as you go:** tighten entries that bloated into specs, collapse an
   explanation repeated across docs down to the one owner plus a link, and delete shipped TODOs and
   caveats that no longer apply.
3. **Diff the command lists against each other.** The pre-PR suite, the CI workflows and the PR
   template checklist drift apart quietly, and a short local copy is worse than none — a contributor
   follows it, passes, and then fails the required gate. `AGENTS.md` owns the canonical list; every
   other mention must match it or link to it. Actually run any command you document for the first
   time.
4. **Retire implemented plan docs.** For each file under `docs/plans/`: decide whether the work
   shipped by checking the **code**, not the document's own status markers — a plan that says "DONE"
   is a claim, not evidence. If it shipped, make sure its durable *what* reached the owning doc and
   its durable *why* reached `docs/design-*.md` — **especially the alternatives that were tried and
   rejected**, which are the expensive things to lose — then **delete the plan file**. Keep only
   plans for genuinely unshipped work, trimmed to what remains.
5. **Fix cross-references.** After deleting or renaming any doc, repoint everything that referenced
   it, including non-Markdown files, which are the easy misses:
   ```bash
   grep -rn --exclude-dir={.git,.mypy_cache,.ruff_cache,__pycache__} \
     -e 'docs/plans/' -e 'docs/design-' -e '<the-deleted-file>' .
   ```
   Comments in `.py`, `.toml` and `.yml` count. Repointing them is allowed here even though this is
   a docs-only skill: a comment naming a file you deleted is a doc reference, not behavior.
6. **Update the pointers.** Keep the `AGENTS.md` architecture tree and doc map, and `README.md`'s
   links, current. `CLAUDE.md` imports `AGENTS.md`, so those edits propagate — but check that no
   Claude-only bullet has become universally true (move it up) or obsolete (delete it).
7. **Hand the tracker to `sync-project`.** The Linear project overview, the milestone descriptions
   and the shape of an issue are that skill's subject, not this one's. Invoke it in the same pass,
   after this one, because a promise sentence is canonical in `docs/promise-map.md` and the tracker
   copies it: reconcile the source first, then the copies.

   This split exists because the two surfaces fail in opposite directions. Repository docs go
   **stale**, so this skill diffs them against the code. Tracker descriptions **accrete**, because
   every burndown leaves behind a paragraph that was true when written and nothing ever removes one.
   A skill that diffs for staleness will not catch a page that is entirely accurate and four times
   too long. Measured 2026-09-08: this step's own rules were followed and the overview still reached
   about 25,000 characters, of which three lines were current state.

   One thing stays here, because it is about this repository rather than about Linear: the promise
   wording is duplicated verbatim in `docs/promise-map.md`, in `docs/visibility-2x2/items.json`, and
   in the Linear project description. Change one and change all three. `sync-project` owns the third
   copy; make sure the first two agree before handing over.

8. **Bring the tone back to the standard.** The prose docs are written for humans, and the fastest
   way for that to rot is an agent topping them up in model-default voice one sync at a time. Apply
   the Voice and tone section to every human-facing doc this pass edited, and re-read the result: it
   must keep every fact and lose only the tells. Do not touch `AGENTS.md`, `CLAUDE.md`, the shipped
   skill body, or this file.

   The `humanizer` skill automates this and is worth using **if your harness has it**, in file mode,
   one doc at a time. It is a third-party skill that this repository does not vendor, so treat it as
   an accelerant and never as a prerequisite. Voice and tone is the contract; a contributor with no
   humanizer installed applies it by hand and is equally done.
9. **Stamp the sync only from a standalone main-based reconciliation.** A feature branch leaves the
   marker at the bottom of `COMPATIBILITY.md` alone, because parallel branches cannot vouch for one
   another and all editing it manufactures a conflict. After the relevant branches merge, a
   standalone reconciliation updates `<!-- docs-synced-through: <short-sha> (<YYYY-MM-DD>) -->` on
   its docs branch. Stamp the `origin/main` tip that branch is based on, **not** its branch `HEAD`:
   ```bash
   git rev-parse --short "$(git merge-base origin/main HEAD)"
   ```
   `main` is squash-merged, so a branch commit stops existing the moment the PR lands, and step 1
   then cannot resolve the marker it is supposed to read. A merge-base sha is already on `main` and
   stays there. (This was learned twice the hard way: markers pointing at `a4eb54c` and `ef480af`
   were both orphaned by the squash that shipped them.)
10. **Verify.** All five checks, every run. Use `git status`/`git diff HEAD`, **not** plain
   `git diff` — a bare `git diff` shows neither your new untracked docs nor a staged deletion, so it
   reports "clean" for exactly the changes this pass makes:
   ```bash
   # a. Nothing but docs changed (comment-only repoints from step 5 are the allowed exception).
   git status --porcelain -uall | awk '{print $NF}' | grep -vE '\.md$'

   # b. No version field moved anywhere on this branch. `version-guard` compares the PR head
   #    against the MERGE BASE, so an already-committed bump is invisible to `git diff HEAD` and
   #    passes `bump_version.py --current` (which only checks three-field parity, not immutability).
   git diff "$(git merge-base origin/main HEAD)"..HEAD \
     -- '*plugin.json' '*marketplace.json' '*gemini-extension.json' | grep -E '^[+-].*"version"'

   # c. The validator: link and anchor resolution across prose docs and bundled skill Markdown,
   #    the public tracker boundary, banned literals, description length, and portability markers.
   python3 scripts/validate_plugins.py

   # d. If you touched the skill body, the documentation-matches-code assertions.
   python3 -m unittest discover -s compass/skills/compass/tests -t .

   # e. Tone: no em/en dashes or curly quotes in the human-facing prose docs. Nothing in CI
   #    enforces this, so it is the one anti-drift check that only exists here.
   #    `git ls-files` builds the list, for two reasons. Step 4 deletes plan docs, and a bare
   #    `docs/plans/*.md` that matches nothing stays literal and makes grep exit 2 on a
   #    "No such file" error. And `docs/plans/` is where per-issue deep-dive notes are kept
   #    locally, excluded per file in .git/info/exclude: those are somebody's scratch, not
   #    this repository's prose, and globbing them made the check red for text no reviewer
   #    will ever read. Tracked files are exactly the ones the standard governs.
   #    The explicit if/else is here because a bare `grep && echo` exits 1 when the docs are
   #    CLEAN, which reads as failure to anyone (or anything) checking the status.
   #    NOTE: the carve-out is for INLINE spans only, not fenced blocks. A dash inside a
#    ``` fence turns this red, and HOW_TO_USE.md is made of config snippets, so it is
#    the likeliest file here to trip that way. Snippets need ASCII quotes and hyphens.
#    Inline code spans are stripped first. A backticked span is a quoted literal, not prose:
   #    the dashed model slot renders as a real em dash, and a doc that documents that string
   #    has to contain it. Matching inside code spans made the check permanently red, which
   #    ends with someone mangling a documented literal to quiet it.
   #    The per-file loop keeps the filename in the output; piping every doc through one sed
   #    would report a line number with nothing to open.
   if for f in $(git ls-files -- README.md MANUAL.md HOW_TO_USE.md CONTRIBUTING.md COMPATIBILITY.md \
        SECURITY.md docs/how-it-works.md docs/promise-map.md 'docs/design-*.md' 'docs/plans/*.md'); do
        sed 's/`[^`]*`//g' "$f" | grep -n '—\|–\|[“”‘’]' | sed "s|^|$f:|"
      done | grep .; then
     echo "TONE DRIFT: reapply Voice and tone to the files listed above"
   else
     echo "tone clean"
   fi
   ```
   **Then decide whether you owe the full gate, by who authors the PR:**
   - **Pre-PR-gate run** — checks a to e are enough. The suite in `AGENTS.md` § Pre-PR Checks ran on
     this same tree minutes ago and the human author owns the result.
   - **Standalone/periodic run** — you are the PR author, so run the **whole** pre-PR suite from
     `AGENTS.md` before opening anything. `quality-gate` is a required check covering ruff, format,
     `mypy --strict`, the frontend lint, strict types and tests, coverage against `fail_under`, and `platform-tests` on
     macOS and Windows; none of that is implied by a to e. Opening a PR you have not gated pushes your own
     verification onto the reviewer.

   Never open or update a PR on the strength of a to e alone.
11. **Stage, commit in the right place, then report.** Never commit to `main`. Stage explicitly —
    new docs are untracked, so `git commit -a` would silently skip them:
    ```bash
    git add -A -- '*.md'          # plus any comment-only repoints from step 5, named individually
    git status --short            # confirm the staged set is what you expect
    ```
    - **Pre-PR-gate run** (invoked on an existing `feat/…`/`fix/…` branch before `gh pr create`):
      commit onto **that same branch** with `git commit -s` — do not create a new branch or a second
      PR; the doc updates ride in the PR you are about to open.
    - **Standalone/periodic run** (started from `main`, no feature work in flight): create a
      `docs/…` branch, commit, and open its own PR — having run the full suite per step 10.

    **A standalone run is not finished when the PR opens; it is finished when the required checks are
    green.** Watch them. If one goes red, either it is your doing — fix it — or it is unrelated to a
    docs-only diff, in which case *prove* that before dismissing it: show the diff touches no code the
    failing test exercises, name the failure mode, and re-run the job. "Probably flaky" without
    evidence is how a real regression ships.

    End with a one-line report:
    `Added: … | Corrected: … | Retired (deleted): … | Unresolved: …`, plus the new sync marker.

## When NOT to change something

- A doc deliberately records a known gap or an accepted trade-off — the skill body's "Known gap"
  note, `COMPATIBILITY.md`'s unsupported-WSL-topology paragraph, `SECURITY.md`'s "Known and
  accepted" section. Preserve it. Remove such a note only when the underlying code changed; quietly
  deleting an honest caveat is worse than the caveat.
- A `docs/design-*.md` entry that explains why an approach was **rejected**. It describes code that
  does not exist, which is exactly what makes it look stale and exactly why it is there. Never
  prune it on those grounds.
- Version and description fields, per the hard boundaries above.
- Any file in the exclusion table, or any file whose classification you are unsure of.
