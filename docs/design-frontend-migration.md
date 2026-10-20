# The React frontend

This record owns what the React frontend is, how it was held to the interface it replaced, the
deviations from that interface and why they stand, and the measurement method. The
[runtime architecture](design-runtime-architecture.md) owns the module map; the
[reader-state inventory](design-reader-state.md#the-inventory) owns what a redraw must keep. The
frontend preserves the [existing promises](promise-map.md), including their limits.

The interface it replaced is called the legacy page below. It is gone: it is not served, not
rendered, and its shell, its rollback flag and the tests that pinned its bytes were removed. What
remains of it is kept on purpose and is not part of any page or of the shipped product. The twenty
legacy script parts (`next-*.js` and `project.js`) moved out of `compass_runtime/web/` to
`scripts/frozen-page/`, byte for byte, because the paused Intent and drift study evaluates their text
and binds the digest of `frozen_page.load_script()`; the plugin, the standalone binary, the runtime
and the frontend neither carry nor read them. Deleting them is separate work that has to rebind that
study first. The recorded answers the React page is held to are described in the next section.

## Held to recorded answers

2026-10-20: the owner ruled that Steer back's correction carries each departure's explanation
([the amendment](design-reading-a-session.md#amended-2026-10-20-owner-the-correction-carries-the-explanation)),
and the correction's cap rose from 2,000 to 4,216 characters to hold them. The retired page was
recorded at 2,000. `correction.differential.test.ts` now passes that recorded cap, as
`RECORDED_CAP`, to `correctionFit` when it compares the edit arithmetic with the recording, so the
cut is still held to the recorded answer at the recorded cap; the page's own cap is asserted in
`SteerBack.test.tsx` and the Steer back correction stories. The composition refusal sentence names
4,216 where the frozen page named 2,000. Golden files are unchanged.

2026-10-20, second ruling: the correction drops Compass entry numbers, draws its times in the
reader's zone and quotes the agent's own words
([the amendment](design-reading-a-session.md#amended-2026-10-20-owner-local-time-and-quoted-words)),
so the cap rose again, to 5,140. A placeholder is now drawn as nothing, where the retired page drew
"(#n in Compass)" and "(#n)". `correction.differential.test.ts` compares the recorded correction text
through `recordedWithoutNumbers`, which removes the recorded numbers, in place of the
`recordedNumbering` projection of 2026-10-14; the recorded cap is still passed as `RECORDED_CAP`.
On the same day the owner allowed Analyze drift on an idle Claude Code session with no recorded turn
finish, so Claude Code lost its own idle press line ("Last turn isn't recorded as finished. Run
another turn to open Analyze." on the retired page). `route.differential.test.ts` maps that recorded
line to the line every harness gets for an idle row. The same row now gets a line before the press,
"Reads the session up to its last recorded entry; its last turn was not recorded as finished.",
where the retired page's `nextObservedReadHint` returned nothing. `observed.differential.test.ts`
holds every other row to the recording and asserts the recording was empty for that one; the line
itself is asserted in `observed.test.ts`. Golden files are unchanged.

2026-10-20: unasked checks keep their opt-in flag and gain a destination-bound Codex grant
in the Drift card, with an Attention cue linking sessions waiting for it. Claude Code needs no
separate toggle. The page reads who the lane reaches from `unasked_routes`, never from
`reading_routes`, because on a harness with no producer of its own the lane prefers Claude Code
where Analyze prefers Codex. No golden recording or differential
comparison was changed for this addition; permission behavior is held by `UnaskedPermission.test.tsx`
and `UnaskedChecks.stories.tsx`.

2026-10-19: the owner renamed the master switch to Pause model calls / Resume model calls.
The pause reason is `model-calls-paused`. Resume changes permission without starting Analyze.
The summary switch stays visible and disabled while paused and keeps its saved answer through resume.
`intent-parity.mjs` filters the renamed master switch from the same moved-control comparison as before;
its recorded oracle is unchanged. Tests and stories assert the new words and behavior.


2026-10-19, owner ruling DEC-28: reader-started calls run opt-out with a notice, as
[the widening](design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts)
requires. The recorded `nextReadingConsent`, `nextReadingToolOutputGranted`,
`nextReadingNeedsAllow` and `nextReadingAnyConsent` admission answers in
`route.differential.test.ts` no longer apply: their oracle calls remain in sequence but those
four comparisons are withdrawn by name. Other route and refusal comparisons remain.
`ReadingCapBanner.test.tsx` uses `model-calls-paused` for its under-cap policy case in place of the
retired `consent-required` case; the budget and reset comparisons are unchanged. Analyze and
Keep run directly, notices accompany due calls, and a stored off requires Resume model calls before another analysis. Goal summaries also run on the explicit focused refresh without a browser consent card.
Golden files remain unchanged; the new behavior is asserted in component tests and Drift stories.
The CSS display census visits a running notice instead of the removed consent card. Its chrome
comparison maps only `reading-notice` to the recorded `reading-consent` recipe and
`observer-controls` to `observer-consent`; these preserve the same card styling, not the old admission behavior.
The on-demand browser proofs `drift-parity.mjs` and `journey-budget.mjs` still drive the removed
consent card, so `drift-parity.mjs` is no longer an oracle for the Analyze notice row of
`scripts/frontend-migration.json`, and the consent-step journeys in both are retired until they
are rewritten for the notice. Their shared fixture policy, once `UNCONSENTED`, is
`FIRST_PRESS`: readings on with no notice recorded.

The rename kept saved browser choices readable until 1.0.0: a missing Compass key read the matching
Cargento key through the shared storage adapter. 1.0.0 removed that fallback with the adapter code
and its test, so a saved choice made under a `cargento.` key is not carried over.


The owner renamed the application to Compass on 2026-10-12. The named
`frontend/test/recorded-name.ts` projection changes only the three case variants of the
former product name in recorded answers, including object keys used for browser storage.
The Vitest seam maps renamed arguments back to the recorded spelling before computing
lookup and state hashes, then projects the encoded answer before decoding it. The browser
seam projects recorded values when loading them and maps lookup labels and input digests
back to their recorded spelling, including storage labels before length-based truncation.
Live observations, assertion shapes,
case counts and all golden bytes remain unchanged. These are test projections, with no
runtime fallback for old stores, storage keys or environment variables.
The same mechanical rename changes literals in the retained retired-page script parts;
their earlier source bindings require renewed evidence.
The Python tests use `tests/recorded_name.py` to restore only the three name
spellings before comparing retained study source and final reading headers with their
historical byte pins. Every original size and digest remains unchanged, and all other
bytes are still checked. This comparison proves the mechanical rename, not qualification
of the renamed study or producer.

The DEC-27 correction keeps Sessions orientation in the compared header, qualified by the
annotation store and reading routes. Project instruction order follows instruction timestamps;
undated cards say Published instruction and saved rows say Your saved words. Ordinary projects
use plain attention states. The wording adapters change named UI regions and protect published
quoted values, including instructions containing an old label. The recorded fixtures stay intact.

While the legacy page existed, each port was proved against it: the pure functions by running the
legacy function next to its TypeScript twin over generated inputs, and each rendered surface by
serving one board to both pages in one Chromium and comparing what a reader can read. Those
comparisons are now fixtures of record. The legacy page can no longer be run, so what it said was
recorded once and the React page stays held to the recording:

- The vitest differentials replay `frontend/test/golden/vitest/<test file>.json.gz` through
  `frontend/test/legacy_goldens.ts`. A harness there stands in for the legacy functions. A key is a
  hash of the harness, the method, its arguments and the state the earlier calls left it in, so a
  call with no recorded answer fails with the name of the call, never passes.
- The browser parity proofs (retired from CI and the pre-PR suite on 2026-10-12, and kept to run on
  demand; Storybook now verifies the interface) replay `frontend/test/golden/e2e/<proof>.json` through
  `frontend/e2e/support/golden.mjs`. A key is the step name plus its label, an unread key fails the
  run, and a reading taken twice fails it. Several keys still contain the words "legacy page" or "both
  pages" because that text is the step name the key was recorded under.
- Entry numbers are labels, whole or dotted (`41`, `41.2`), where the retired page counted whole
  numbers, and a session entry now carries the server's `ordinal` and `ordinal_sub`. The recorded
  answers are keyed by call arguments, and the retired page was never handed those fields, so the
  harness drops the named fields (`withoutLaterFields` in `frontend/test/legacy_goldens.ts`) from
  every argument before it hashes one, and the differential tests give the retired functions their
  recorded whole-number maps while the new code reads the same numbers as text. Without fixed numbers
  a label is the count the retired page made, so every recorded answer still agrees. No recording was
  remade.
- The recordings cannot be remade. A changed generator, input, step or label has no recorded answer
  and fails. A deliberate departure from a recorded behaviour is an edit to the test that says so and an
  entry under the surface's deviations below, so the departure is a recorded fact rather than a
  silent change.

Each proof still holds the React side to its own assertions in every run. The recordings hold what the
legacy page said; they say nothing the React page was not also asserted to do. Sections below that say a
port was "run next to" or "compared with" the legacy page describe how it was proved while that page
existed.

The one-column session page is a deliberate departure (owner, 2026-10-19;
[the reversal](design-reading-a-session.md#amended-2026-10-19-owner-one-column-again)). The
`sessions__detail` comparison in `frontend/src/sessions/detail.differential.test.tsx` reads it back in
the recorded order and words before comparing: the state badge, which now leads the measured line
with a status dot, returns to the start of the title row without its dot, and the Full activity
trigger reads as the recorded "Session activity" heading. The header still comes first, the panel is
still outside the comparison, and every other sentence of the activity, in its recorded order, is
compared unchanged. The recording is untouched.

Base UI Select is a deliberate departure from native option DOM (owner, 2026-10-12). The Intent
editor comparison retires its native-menu column and excludes the combobox trigger from action
buttons; its browser role proof checks offered labels, order and pending adoption. The Console
comparison projects the selected native option onto the controlled value and disabled trigger.
The mounted stage comparison still enumerates every offered option, with effective disabled state,
over 80 generated boards. Goldens remain unchanged. [The Intent record](#the-intent-log-and-the-intent-panel)
records the popup, width, Escape and refresh behavior and the four adjusted field reference rows.

Accordion adoption keeps recorded labels, text and independent open-state observations, while
proofs locate the new triggers and panels by their slots. A session-facts part retains its recorded
logical part name after the former `details` tag becomes an Accordion root. The fixture files are
unchanged. The adoption record owns the component chrome reference and the mounted-panel limits.

Vitest DOM comparisons use `frontend/test/disclosures.ts` to read an Accordion disclosure as
native `details`: the trigger becomes its summary, `aria-expanded` supplies its open state, and
the panel's children remain its body even when closed with `hidden="until-found"`. The item,
header and panel wrappers, decorative chevron, generated trigger attributes and default vertical
orientation are component chrome rather than recorded content. Root surface attributes and body
markup remain comparable. Project and timeline summaries also compare ordered disclosure readings
with their summary, open state and body text. Mutation proofs reject missing or changed bodies,
renamed summaries, flipped open state, removed disclosures and reordered disclosures or evidence.
Missing triggers or panels and inconsistent open state fail normalization. These equivalents
preserve the legacy observations without changing a recording or dropping closed evidence.

The same normalizer reads a Popover disclosure as native `details`. The recorded closed
popover bodies include their evidence, and the current `keepMounted` portal retains those bodies
inside the app root. A cloned snapshot rejoins each popup to the trigger named by its
`aria-labelledby`, preserving summary text and `aria-expanded` state without opening the popup
or moving live nodes. Portal wrappers, focus guards and portal ownership markers are component
chrome. Missing or ambiguously labelled panels refuse normalization. Sessions and session-detail
comparisons use that snapshot and compare ordered summary, open state and body readings;
mutation proofs reject changes to each. The recorded fixtures and shipped bundle are unchanged.

Sessions display components keep the original semantic roots and text. The decorative notification
Separator adds no recorded text. Browser comparisons locate Card and Alert slots and map the
health slot back to its recorded logical part name; the health sentence is still compared.
The Vitest text summaries need no broader normalization. Goldens, disclosure readings, option
order and action lists remain unchanged. The [Sessions adoption](design-shadcn-adoption.md#sessions-layer)
owns the computed chrome reference and native decisions.

Intent, Drift and steering display components likewise retain their semantic roots, cell classes,
text, field keys, consent group and action order. Static Alert paragraphs retain their absence of
a live-region role. The existing DOM and text summaries therefore need no wider normalization;
unchanged recordings still compare consent, drafts and the first Copy press. The
[family adoption](design-shadcn-adoption.md#intent-drift-and-steering-layer) owns the computed chrome
reference and keep-native decisions.

Project, Console, Timeline, shell and terminal display components retain their semantic roots,
evidence and action order. The delegation DOM differential drops utility classes only on shared
Card, Badge and Alert roots, retaining semantic surface classes, attributes, text and children.
A mounted comparison rejects changed evidence, session identity, surface classes and live roles;
removing the normalization fails at its class comparison. ProjectTabs adds a display:contents
Root around the original nav and panel. The route still owns selection, ids and panel content.
The Button chrome summary ignores Base UI Tabs' redundant aria-disabled=false, while true
remains compared. Recorded fixtures and frozen legacy sources are unchanged. The
[family adoption](design-shadcn-adoption.md#project-console-timeline-shell-and-terminal-layer)
owns the keyboard contract, measured reference and native decisions.

Attention, Capacity and consent display components keep their articles, sections, paragraphs,
spans, list order, numeric readings, clock ticks and action attributes. Existing display-component
utility-class normalization already handles these roots; no wider normalization or recorded-fixture
change is needed. The Attention text and Capacity tree differentials still compare each waiting
source and each window's own figures. A number-to-verdict mutation is checked against the existing
Capacity browser and mounted differentials. The [family adoption](design-shadcn-adoption.md#attention-capacity-and-consent-layer)
owns the chrome reference, rail inheritance and native bar decision.

Three owner departures of 2026-10-14 change what the retired page said, so the recordings are compared
through named projections and nothing is re-recorded. The reason for a withdrawn verdict began "The check
it cited does not show this" and now begins "What it cited does not show this", because the page cannot
tell a check from a write, or nothing, among cites the producer has emptied. A correction's entry
numbers read "(entry #n in Compass's activity list)" on every number, where the page said "(#n in
Compass)" on the first and "(#n)" after. The live estimate's line adds that files written by shell
commands are not seen. `retiredWording` in `frontend/src/drift/legacy.test.helper.ts` projects the
first back for the shape and result differentials, `recordedNumbering` in
`frontend/src/drift/correction.differential.test.ts` projects the second for the correction text, and
the drift browser proof restates the second and the third in the recorded steer box and live estimate.
Every other word, the placeholders dropped and their order stay held to the recording.

The Intent card's redesign of 2026-10-19 departs from the recorded editor in four places, and nothing is
re-recorded. The draft marks' dashed "from your prompt" badge and its excerpt cue became one plain source line
beside the count, "From your prompt · first|latest|HH:MM · not saved." with the cap sentence the 2026-10-13
departure ruled ("Analyze reads at most the first 1,000 characters of any prompt.") and, for an excerpt, the
excerpt cue. The checklist's label reads "Expected outcome · up to 6 lines" where it read "Expected outcome
(optional)". Every character count reads "n / cap" where it read "n/cap". And the prompt menu's trigger is named
"Use your prompt". `intentEditorDeviations` in `frontend/e2e/support/intent-editor-deviations.mjs` projects the
first three onto the recorded editor; the browser proofs that read the retired badge or the old menu name now
read the source line and the new name.

The analysis level's line says "Analysis last run 14:03" where the retired page said "Analysis at 14:03"
(owner, 2026-10-19), because the old words read as a time inside the session; the Drift card header
says the same beside the model. The `drift__level` comparison in
`frontend/src/drift/level.differential.test.ts` projects that one prefix back to the recorded words
before comparing, and every other field of the analysis level stays held to the recording, which is
untouched. The departure cards that replace "Model assessment" in the same change draw from the same
`result.ts` functions, which the `drift__result` comparison still holds unchanged. The first analysis
journey proof (`frontend/e2e/journey-budget.mjs`, run on demand) now finds the departure's account in
its card and its cited entries under What; each entry's recorded time moved behind Evidence.

## The ownership map

[The machine-readable inventory](../scripts/frontend-migration.json) maps each legacy script
part, visible surface, route, reader-state row and persisted browser key to its migration owner
and the proofs that hold it. One row has one owner. A shared helper was migrated before its
callers, rather than copied into each view. The shell owns the revision/value helpers that
Intent reads from the project renderer.

`python3 scripts/frontend_inventory.py` checks the map without importing the dashboard or reading
local session stores. Every row names a migration owner, a contract and oracles that exist inside the
checkout; a row that names a file that is gone refuses the map. The reader-state rows must match the
table in the reader-state inventory, and the storage rows must match the keys the React codec owns
(`frontend/src/storage/keys.ts`). The `parts` rows are the historical map of the twenty legacy parts
and are checked for form only, because their source is frozen and no longer a thing to derive coverage
from. Surface and route rows are a reviewed enumeration, not proof that a static scanner can discover
every workflow. Differential tests protect semantic contracts; they cannot certify native undo,
composition, open option lists or browser layout, which the browser proofs cover.

## One page

There is one renderer. A request or URL never selects it, and neither does an environment variable
or a stored setting. `server.py` refuses `--frontend`: the option existed only as the process-level
switch to the legacy page during the migration, and the parser has abbreviations off so
`--frontend react` is refused rather than read as the start of `--frontend-dev-manifest`. A build that
cannot load refuses before the socket is bound and never serves a stand-in, because a dashboard that
looks fine over a damaged installation would hide the damage. While the candidate was being built,
React was the opt-in page and any route it had not ported said so in the page, naming the later step
by what it brings, never by a tracker key, because that text ships in the page.

The served page and published build identity refer to the same document. Identity is derived from
deterministic content, independent of release versions and per-run capabilities, and keeps its
`react-` prefix (`react-dev-` under the contributor command). `/api/data` no longer publishes a
`frontend` field: nothing read it once there was one renderer, and the committed client-contract
fixtures were regenerated without it. The focus capability is injected at startup at an unambiguous
template position; it is never built into the tracked artifact.

## Build and development boundaries

React/TypeScript source lives outside the plugin. Pinned Node 26 and pnpm build a tracked Vite
artifact, so repository, tag, stable and source-archive installs work without Node. Core HTML is
self-contained and offline. Packaging decides whether the existing optional xterm assets remain
lazy same-origin files or become part of that HTML, with their size/startup cost measured. Fonts
and bundled modules retain their licenses and provenance. Canonical builds use Linux unless a
cross-platform probe establishes byte equality.

The Tailwind toolchain imports theme and utilities without Preflight, with the existing sheets in
the `legacy` layer. Its source boundary, scale reset and CSS ratchet are owned by
[the adoption record](design-shadcn-adoption.md#toolchain-layer). The packager includes
`components.json`, the entry stylesheet and vendored source in provenance, and ships the upstream
MIT text for copied shadcn code alongside bundled package licenses.

The shared Button owns the 46 button elements and the styling recipe used by ten plain anchors.
ActionButton keeps its caller props, focus registration and pending-store subscription. The Button
owns the ghost label, spinner and suppression of repeated pending activation. Tabs and switches keep
their explicit roles. See [the Button adoption](design-shadcn-adoption.md#button-layer).

In development Python owns the document and API origin. The explicitly enabled page imports
Vite modules and the React-refresh preamble from a validated loopback child. Strict ports,
an owned-child handshake and exact origin checks prevent accidentally loading a different local
process. Production exposes no HMR path. Build plugins and dependency scripts never receive
release push credentials; publication verifies the exact fresh or resumed target tree.

## Lint and format

Biome, pinned exactly, lints and formats `frontend/**/*.{ts,tsx,mts,mjs}`, the two root tool configs
and `biome.json`. `pnpm lint` runs `biome check` with warnings as errors, so one command covers rules
and formatting; `pnpm format` rewrites. CSS, HTML and the captured JSON fixtures are outside the file
set: the fixtures are byte-exact Python captures, and the previous linter never read the CSS or HTML.
Line width is 100, the same as ruff's.

These checks replaced `scripts/lint_embedded.py`, which syntax-checked the legacy page's JavaScript,
checked its CSS structure and its DOM ids, and ran as a step of the lint job. Its targets are gone, and
each thing it guarded has an owner now: Biome covers rules and formatting over the React sources and
scripts, `tsc` strict covers types, the unit suite covers behaviour, the hostile-literal parser proof
(`pnpm test:parser`) executes hostile JavaScript and CSS values in the built page, and `pnpm build:check`
fails when the tracked `react.html` differs from a clean rebuild of its sources. The lint job keeps its
name in the workflow because a branch ruleset may require that exact context; the frontend sources are
linted by the `frontend` job.

`biome.json` starts from no preset and enables, rule by rule, what the ESLint configuration it
replaced enforced: the JavaScript recommended set, typescript-eslint strict without type
information, the react-hooks rules and react-refresh. Biome's own recommended preset adds
accessibility and style policy that configuration never carried, so it stays off. Import organizing
is off for the same reason, and because CSS side-effect imports are order-sensitive.

After a Biome upgrade, probe one defect per rule class and confirm `pnpm lint` fails on it. The
React Compiler checks (set-state-in-effect, purity, refs, immutability, globals, static components,
error boundaries, `useMemo` returns, set-state-in-render) come from `nursery/useReactCompiler`,
which is experimental and can change between releases without a deprecation. The compiler reports
only on functions that look like components or hooks and return JSX.

Three kinds of difference were weighed and settled:

- **Stricter in Biome, so relaxed.** `noShadowRestrictedNames` rejects any global name, where ESLint
  rejects only a handful; `noUnsafeOptionalChaining` rejects a cast over an optional read, which a
  test uses on purpose; `useComponentExportOnlyModules` rejects unexported helper components, which
  react-refresh skips in `*.test.*` files. Each is off for test files only. `useErrorCause` does not
  require a catch parameter, matching ESLint's default.
- **No equivalent, accepted.** `no-dynamic-delete` (Biome's `noDelete` flags static keys instead,
  the opposite rule), `ban-ts-comment` for `@ts-nocheck` and undescribed `@ts-expect-error`
  (`@ts-ignore` is covered, and none is used), `triple-slash-reference`, `no-invalid-regexp` for
  string-built patterns, `no-useless-assignment`, empty or constructor-only classes, and unused
  trailing parameters in the `.mjs` scripts (`tsc` covers them in TypeScript). Biome also has one
  global set, so a browser-only global in a Node script is not rejected.
- **Not applicable.** The compiler's `config`, `gating`, `unsupported-syntax` and
  `incompatible-library` diagnostics: no compiler configuration is in use, and the build does not
  run the compiler.

A suppression carries its reason in the `biome-ignore` comment. Three exist: the timeline's context
read re-runs on the board revision without reading it, the terminal test harness exports nothing,
and one `hasOwnProperty.call` stays because `Object.hasOwn` would change the shipped page.

## Candidate packaging

The core page embeds compiled JavaScript and CSS as base64 data resources. These are packaged
bytes, not HTTP asset downloads. Encoding adds roughly a third to their size, which counts against
the HTML budget. It preserves comparison operators, regular expressions and tagged raw templates
without allowing their text to change the HTML parser's state. A global replacement of `<` would
break operators; replacing only script end tags would miss HTML comment and script parser states.
The browser tests must execute hostile literals, rather than infer safety from a string check.

The JavaScript resource ends with a fixed `sourceURL=compass-bundle.js` comment. Without
that short name, Chromium captured the full 1.1 MB data URL in callback source locations;
repeated production drift loads reached 8.3 GiB renderer RSS while the JavaScript heap
stayed below 65 MiB. The short name kept the same proof below 478 MiB. The callback-stack
check in `frontend/e2e/parser.test.mjs` bounds those names with a production-sized module.
The comment changes no fetch URL or executable bytes.

A data module has its own `import.meta.url`. The build must therefore refuse residual imports,
chunk-relative resource construction and unexpected emitted assets instead of silently resolving
them against that URL. API requests must use the document's Python origin; the typed client layer
must prove that boundary on the served page. Packaging smoke proves the embedded core and served
build identity. The page reads only that origin through the typed client. The existing framing policy
remains in force.

The fifteen packaged font faces and their ranges come from the existing canonical descriptors and
WOFF2 payloads. Their licenses and source records remain packaged. Bundled JavaScript has its own
full license inventory derived from actual compiler module ownership, not the list of development
dependencies. Missing ownership or licenses refuse packaging. Build provenance uses relative paths
and content hashes; release versions, machine paths, timestamps and per-run capabilities do not
enter the artifact.

The optional terminal remains a lazy same-origin exception. Its JavaScript and CSS total 495,775
raw bytes before embedding overhead, which every reader would otherwise download at first open.
There is no measured startup benefit to bundling it. Installed checks distinguish the React core's
offline launch from the existing terminal renderer's local asset and read-only stream checks;
they do not stand in for the React terminal's own browser proof, described under Sessions below.

Python verifies the selected document and license payload against packaged integrity metadata.
That detects missing, corrupt or stale build output. It does not authenticate a local actor who
replaces the artifact and its metadata together. A selected bad build fails before binding;
recovery commands remain available.

## Integrated development

The contributor command owns a Vite worker and the actual foreground Python launcher. Python
serves the document, APIs and SSE; Vite serves modules and hot refresh. Its startup ticket is
read once, and a fresh HMAC challenge binds both exact loopback origins, the worker PID and both
process generations. The shared secret stays in owned IPC and a private startup file, which the
supervisor removes after readiness. This prevents adopting an accidental listener; it does not
authenticate against another process able to read the same user's private files.

Vite's built-in host, CORS, token and filesystem settings do not establish the whole boundary.
They accept extra loopback authorities, and the measured source-directory symlink test escaped
the configured filesystem allowlist. Admission therefore checks exact raw Host/Origin headers
and canonical filesystem paths before Vite dispatch. An unbound public WebSocket dispatcher
receives only admitted upgrades. HMR retains Vite's token check; its token-free ping protocol
still passes the same exact host, origin and path admission.
Python keeps its own origin, framing and capability checks; its routes never proxy through Vite.

All harness and platform data-location inputs point inside the owned scratch tree, and Python
checks the actual resolved collector candidates before starting. Windows retains only the system
directory inputs its socket loader requires. Model calls, quota fetching and native actions are
disabled. Normal development exposes no focus capability; a separate inert fixture verifies
capability transport and refusal without claiming a terminal was raised.

Hot refresh preserves the document's development identity. Explicit Python restart waits for the
old child to close, repeats the worker admission and changes the backend generation and build.
The contributor reloads for that instance. Worker failure stops Python too; interruption, EOF and
failed startup clean only captured children and owned files. Production uses its committed page
and content identity, with no development modules or HMR endpoint.

## Typed client and store

The React data layer lives in `frontend/src/{api,store,transport,storage}` and owns every request,
timer, event stream and browser-storage key the page uses. Components subscribe to one external
immutable store and never fetch, poll, open a stream or touch `localStorage` themselves. A runtime
owner starts and disposes those resources explicitly. It is idempotent under StrictMode and HMR
replacement, aborts only requests it started, closes only streams it opened, and holds the
pending-action registry and the one per-document storage instance for as long as it lives.

The legacy source won wherever a prose description disagreed with it, because the port had to stay
compatible with the page a reader could roll back to; the recorded answers keep that outcome. Measured
differences from the first written port map, all resolved toward the legacy code: the guardrail cap keeps the first fifty valid rules on read and the last fifty on add;
the twelve-hold select deferral resets only when a deferred commit is waiting, never past the cap;
the usage load counts an empty-key entry against its 200 before dropping it; and a real navigation
does not release the leader lease, because the stream reports closed before `pagehide` fires.
The refresh controller, election and revision logic were checked differentially against the real
legacy files over thousands of random schedules with no divergence, before the legacy page was removed.

Rules the layer keeps that a green suite does not enforce on its own:

- An action is sent once. A POST is never retried, a second focus press while one is in flight is
  answered locally as throttled, and an empty harness, session or capability sends nothing.
- A refusal, an outage and an unreadable body stay distinct from an empty healthy board, and the
  last accepted data survives a failed read.
- The exact harness and session pair is the identity of a request. The compatibility key
  (`sid`, falling back to the display session) names storage entries only.
- A read of any storage family writes nothing, so a mount or poll cannot trim or rewrite a value
  an earlier build wrote and would still accept.

The fixtures under `frontend/test/fixtures/client-contract/` are captured from the real
application and HTTP server with models, quota fetching and native actions off, and a guard counts
that none ran. `python3 scripts/regen_client_fixtures.py` rewrites them and `--check` fails when
the server's answer has drifted. The Python suite regenerates every file and compares bytes, and
the TypeScript suite replays each recorded request and classification, so a backend change breaks
both sides. The standard library's error pages vary by Python version, so an error page is recorded
as its status and the markers it must contain rather than as raw text, and the stream heartbeat is
cut at its first frame so its bytes do not depend on reader speed. Routes that need a model, a
native action or a per-run value are listed with their reason in the index instead of being
written by hand.

Storage conformance holds the codec to what the legacy page did with its storage, in both directions for
all twelve families. The legacy page ran in Chromium against the real backend when the answers were
recorded, and the proof now hands the real codec a blank same-origin page and applies each recorded
change to it, so the codec reads exactly what that page wrote and every codec write is checked against
what the legacy page did with it. A direction is labelled by what exercised it: the page's own UI,
passive page behaviour, a legacy function run in the page when no reachable control exists without a
model or credential path, or a codec-level check (`recorded-ui`, `recorded-passive`,
`recorded-function` and `codec-level` in the receipt it prints). The receipt counts each kind and does
not fold them into one total.

## React shell, routes and controls

Deviation (DEC-27, 2026-10-12): Sessions precedes Projects in the primary tab order. The
shell proof normalizes that recorded array swap and still compares every route, label and origin.

The shell is a React page, not a layer over the legacy one. One tree holds the page and
five live regions as siblings, and the regions are never inside the subtree a route replaces, because
a node that arrives carrying its text is the one a reader's software skips. Announcements are
written once per standing key, forgotten when the pending action that caused them ends so the next
press is spoken again, and counted under StrictMode so a double effect cannot repeat one.

Routes keep the released fragment grammar exactly. The router was checked against the real legacy
parser over hundreds of generated fragments, and a browser test compares the canonical hash, document
title, current navigation item, breadcrumb, history depth after Back, reload and Escape for every route
contract with what the legacy page did. A bare or malformed
fragment lands on the Sessions view, a retired held-to alias opens its exact session, and an
unknown `from` is dropped. `?all=1` is the only query that widens data, and the retired `next` query
is never read by the page.

Absences are stated. Before the first payload the page says it is waiting, a refresh failure shows
nothing at one failure and a notice naming the retry interval at two consecutive failures, a newer
server build asks for a reload, and no view prints a count it has not measured. Two deliberate
differences from the legacy page: the header says "Waiting for the first board." before the first
payload, where legacy printed zeros that read as a measured empty board, and Retry uses
`aria-disabled` instead of `disabled` so keyboard focus survives its own removal.

Copy briefing announces why it cannot copy (the project is no longer in the payload) instead of blaming
the clipboard. The control that copies a session link, the project briefing, the "Attention updated"
announcement and the notification control are each built in the step that owns the surface they sit on.

Shared controls keep reader state the redraw would otherwise discard. A keyed focus lane restores
the same control or a named fallback without scrolling an offscreen one, a field memory keeps an
unsaved draft, caret, undo and composition across live updates, and an open Base UI Select holds the
background board paint for at most twelve consecutive attempts and catches up once when the popup closes. React retains its value and open state through manual refresh and paints past the cap.
Disclosures keep their node and derive open state from the subscribed keyed store, hold background
commits for 220 ms around the 200 ms motion, and skip the hold under reduced motion. The
[reader-state record](design-reader-state.md#disclosure-write-precedence) owns write precedence,
independent grouping, native fragment revelation and popover dismissal. The Base UI popup exposes listbox and option roles, so Chromium now inspects the open list, its position, keyboard choice and close paths directly.

## Sessions, session detail, the timeline and the terminal

Deviations (DEC-27, 2026-10-12): Sessions precedes Projects in primary navigation and retains
its landing route. Every goal cell, including saved words, opens the session with the existing
Intent focus rule. The header keeps its orientation and shared how-to on checked and unchecked
boards; the row-splitting and goal-source sentences move intact into that popover. Exact requests
and reported blocks move to Attention, while the two active/working counters and all row facts
stay. Assignment labels on Sessions and session detail become Current task, and the Sessions
command-surface eyebrow goes. The single-column header places the title, orientation, optional
unchecked clause and how-to in reading order. The disclosure chrome reference replaces the two
retired triggers with the measured row-filling how-to; its fonts, inks and borders remain unchanged. Recorded-side
normalizers account for labels and counter placement; the proof asserts the first-step controls
and counts one click on each of four active/recent, saved/drafted fixtures. Goldens stay unchanged.

Deviation (2026-10-20): ACTIVE NOW counts the cards listed under Active now, which include a
session holding recorded drift. The legacy count left drift out, so a browser walk read
"ACTIVE NOW 0" above a listed drift card. WORKING is unchanged and still never counts an idle
session with drift. The recorded side of `sessions.differential.test.tsx` sets that one count to its
own active group's rows; every other fact still compares.

The observed model that Sessions, the header counts and session detail all stand on is a full port of
the legacy `next-observed.js`, checked by executing the real legacy file next to it over hundreds of
generated payloads with no difference, and by mutants that show the comparison can fail. The header
counts and the rows come from the same collection, never an authored number. The Sessions screen and
the detail page were compared the same way against the real legacy views over about a thousand seeds,
then in one Chromium against the same board: group membership and order, row text, absence sentences
and the one-step link to each session. A harness whose store could not be read is named, which the
legacy page does not do. A question answer posts one numeric `index`, only a confirmed answer retires
the question, and a second press while one is in flight sends nothing.

The timeline filter keeps `active`, `all` and `decisions` per project and session in the existing
graph-mode storage key, with the caller's choice over the stored one over the default, and the old
empty-scope key dropped. The terminal stays lazy, local and offline: nothing loads before the press,
then exactly the two vendored xterm assets. It is output-only in the strongest sense the legacy page
allows, since the legacy page sends no client frame at all and the server revokes a socket that sends
one, so the browser proof asserts zero client frames while typing, pasting and pressing keys. Its
lifetime follows the exact harness and session, so leaving the route and returning keeps the retained
screen and StrictMode opens one socket. Follow is measured against the live position, not the scroll
maximum, because the legacy page's own textarea rule makes xterm's helper element 44 px tall.

The timeline and the terminal are mounted in the project view's Decisions and Console tabs.

Deviations (DEC-27, 2026-10-11): Sessions rows no longer offer Copy ID; session headers
no longer offer Copy ID, Copy link or Copy command, and departure rows no longer offer Copy
command. The header's resume absence and explanation go with that control. Terminal raise and
its limits remain on blocked sessions; the unblocked absence and Why are retired from the recorded
side. An unblocked header now follows the panel, before activity, with its evidence intact. Resume commands remain on Attention, the waiting panel and the project rail;
Steer back still copies a correction. The unused absolute-session-link builder is retired.
Recorded-side normalizers remove just these controls and the resume explanation; the current
page still has to assert their absence. The fixture recordings are unchanged.

## The Intent log and the Intent panel

The Intent log (`#n=intent`) and the panel on the session page (the goal and expected-outcome editor,
the prompt menu, later directions, Keep, discard and the live monitor switch) are ports of the legacy
`next-intent.js` and the editor half of `next-cockpit.js`. Every pure function was checked by running the
legacy function next to its TypeScript twin over generated inputs, with mutants that show the comparison
can fail; the differential caught one real divergence (a chosen prompt kept past a store that was
switched off). A browser proof serves one board to the legacy page and the React page in one Chromium and
compares the log and each editor state.

The editors are native. A revision announced over the real stream, a poll, StrictMode and an IME
composition leave the node, text, caret, selection and native undo where they were; the proof types, moves
the caret, composes through the debugger protocol and lets revisions land. Unsaved text survives leaving
the route and returning, but the node and its undo history do not, because the Intent view unmounts; that
limit is stated rather than hidden. Nothing is sent by a mount, StrictMode, a poll or a route change, a
save is one POST and never retried, and a save in flight when the reader navigates away is sent once.

What the Analyze step builds on is exported from `frontend/src/intent`: `DirectionQuestion` (Keep settles
through the annotation route until a reading is supplied), `openPendingDirection` for Update intent
instead (one direction read, nothing saved), `intentForReading`, the live monitor switch and the shared
reading-feedback lane. The per-entry Add to my intent buttons of the legacy activity list are drawn by the
Drift step's numbered activity list.

Deviations (owner, 2026-10-12): prompt, stage and direction choices now use shadcn Base UI Select.
The prompt opens immediately, shows "Loading your prompts" as a disabled item while fetching,
and keeps that popup open for choices or a stated absence for an empty read or a failed read after an empty or failed
read. The trigger stays "Use your prompt" at rest and carries `aria-busy` during the request.
Beside a saved typed goal its face reads "Replace with your prompt" (2026-10-20), because "Use your
prompt" beside "Typed · saved" read as the goal's source; its accessible name stays "Use your prompt".
Its width is 18rem on wide screens and the remaining label-row width on narrow screens. The Goal label and trigger retain one row on narrow screens, preserving the first-view positions of Analyze, results, direction questions and Steer back. The popup drops
below the trigger, scrolls without shifting the page, and clamps each titled item to two lines.
Escape closes only the popup before any disclosure or route dismissal. A choice fills a pending
adoption and saves nothing. The request still runs once per opening, never on a poll or mount.

Direction action feedback now stays beside the exact control pressed, including
activity-row Add and Update intent instead. It is held across polls until the next press or an intent edit, including the pending line,
announced through the existing persistent polite region, and keeps focus at a
failed action. The two source refusal tokens have separate page-owned sentences;
no failed Goal adoption focuses the Goal box. The prompt menu shows newest choices
first and states an unfinished search beside the list. These repairs are covered
by `IntentDirections.test.tsx`, `PromptSelect.test.tsx` and
`IntentDirections.stories.tsx`, including the phone pending-line layout. No
recorded golden answer was regenerated.

`PromptSelect.test.tsx` covers same-popup loading, arrival, absence and dismissal.
`intent-parity.mjs` checks first-frame opening and stable widths at 1280, 375 and 320 px, with
`auto-prompt-width` and `wide-select` mutations. The four select rows in
`field-chrome-reference.json` now name trigger buttons: two prompt identities, workflow stage
and later direction. They record flex display and inline chevron padding explicitly, while
retaining border, ink, font and the 288 px desktop prompt width. Other field rows are unchanged.
The Button chrome sweep excludes these triggers because the field sweep owns them.

The StageConditions mounted differential projects a trigger and its portalled options onto the
recorded choice inventory, including effective disabled state inherited from a disabled root.
That text comparison forces the real popups open to enumerate unavailable choices too; the
interaction tests separately open enabled choices by gesture. The editor comparison retires its
native option-DOM column and excludes the new trigger from ordinary action buttons; the popup's
role proof checks offered prompt labels, order and pending adoption. The Console comparison projects the selected native option onto the controlled value and disabled trigger; its Save, Rearm and Remove proof chooses real options by role. The mounted stage differential still compares every offered value and disabled state across 80 boards. No golden file changes.

The controls proof measures popup node, position, value and options across held polls, and keeps
it open across manual refresh and the twelve-poll cap. The fluidity driver measures a nonempty
chosen prompt and open popup over thirteen fallback polls, separately from native editor focus
and undo. A synthetic transcript for its current session supplies the real prompt endpoint;
cohort rows retain the baseline shape. Removing the native prompt-wrapper rule lowers hand-written CSS by 100 bytes to 123,040; its coverage key is retired with the rule.

DEC-27 trims the first view: one optional outcome line, its Add and Remove controls after use,
Undo after a goal edit or prompt choice, and six groups in the session-scoped More disclosure. Saved reads-from and
Clear move there with Live monitor, Discard everything, Delegated work, Pause model calls and
neutral later-direction state. The idle monitor explanation and editor hint move with their owners.
The count-only Direction summary draws no text, so every Keep requires the whole-text opening
press before settlement. Activity Add stays mounted and becomes visible on hover or focus.
Below 1101 px the panel precedes the activity in one column; from 1101 px the activity reads on the left
and the panel on the right, level at the top (owner request, 2026-10-12). The unblocked header moves into
the activity area.
The owner reversed that on 2026-10-19: the page is one column at every width, More is retired, and
each of its parts has a new home in the Intent card, the Drift card or the "What is sent" popover
([the inventory](design-reading-a-session.md#where-everything-in-more-went)).
From 761 px the Intent section is a card like the Drift card, 24 px above it, and its text fields show
three lines; at 760 px and below the earlier compact spacing and one-line fields stay so the goal and the
primary control remain in the 375 by 667 first view. The field chrome reference table records the card's
background, border, radius and padding for the wide Intent panel; nothing else in it changes.
The ended-session note appears beside the Goal field before typing. Claude's idle session without
 an observed stop is analyzed up to its last recorded entry since 2026-10-20, so it carries no
refusal; the route projection maps the retired page's refusal sentence to the line every harness
gets for an idle row. Recorded-side projections adapt those placements and
controls; field values, evidence and requests remain asserted.
The idle drafted panel has a 90-word ceiling outside field values and closed bodies; the browser
first-view proof checks the viewport, the control set, a one-button mutation and the limit paths.
The CSS proof projects the relocated control identities on the reference side. More uses the
existing tier-2 chrome and a 49.266 px natural width, with the same font-metric allowance as other
summaries. Closed More bodies may be hidden; opened widths retain their recorded checks. At wide
viewports, nudges keep 16 px margins and reading jobs and consent keep their 33.75 rem cap against
the wider row. The relocated subtitle uses the 15 px prose step. No recording under
`frontend/test/golden/` is edited.

DEC-27 replaces What analysis does with the keyed How Intent and drift works popover beside
the Intent heading. Its three steps explain the goal, Analyze and the correction. Its limit line
uses the shared work and steering harness lists and the board's reading route, including a
missing reader's reason; it retains the promise that Compass never writes into sessions.
The shared Popover proof covers click, keyboard, Escape, outside press, focus return and 320 px.
No browser storage or first-visit marker is added. The old disclosure is removed only from the
recorded-side Drift snapshot; the remaining limits and privacy disclosures are still compared.

## The Drift card, Analyze and Steer back

The Drift section of the session page (the live and analysis levels, the reading card, Analyze and its
consent, the result, Cancel, Steer back and the departures raised while the reader was away) and the
numbered activity list it cites are ports of the drift half of `next-cockpit.js`. The pure parts (the
reading shape contract, result wording, route and refusal ranking, level, correction arithmetic, the
numbered list) were run next to the lifted legacy source over hundreds of generated cases each; the flip
ledger and job cues are covered by behaviour tests. One browser proof serves a scripted board to the legacy
page and the React page and compares the whole card in every state: no reading, pending, withheld,
completed, failed, cancelling, superseded, a gap and the lane off.

Only an explicit press after consent starts a reading. Mounting, StrictMode, a poll, a reconnect, a route
change, hover, focus and a key press send nothing, and every POST is one attempt that is never retried. One
exception is stated rather than hidden: a Steer back box the reader opened and left unedited composes again,
once, when the record it was composed from changes. That is a deterministic server read of the correction the
reader asked for, never a model call; a closed box and an edited one send nothing. A press sends what the card
it was made on showed: the receiver, both destinations, the model and the revision floor as drawn. Where the
board has moved since (a card can be held while a board arrives), nothing is sent and the card says why: a
changed destination or reader, or the revision sentence. A server refusal of a changed destination answers
with the stated reason and sends nothing more. A refusal on an adopted prompt is drawn from the shared request lane the Keep
action writes. Steer back composes an editable correction (2000 code points) that is only ever copied, never
written to the session; the proof drives typing, caret, selection and native undo through board ticks, IME
composition through the debugger protocol, a paste over the cap, and a pointer held through the click.

Deviation (2026-10-20): the line saying what put Steer back on offer names a departure by its first cited
entry, the one its result row and its reason line name. The legacy line took the latest of all its citations,
so one card read "Departs; evidence #3" beside "Departure evidence at #4". A failed check there reads "A
check the agent ran failed", because a bare "Check failed" under "Not checked yet" read as the drift check
having failed. `correction.differential.test.ts` gives the recorded side the same first citation and wording.

Deviations, each recorded rather than hidden. The card, the numbered list and the departures hold the last
board they drew while the reader is in the correction box (untouched or edited), composing, or holding a
pointer on a control they left it for, and say "Updates are paused" instead of the legacy whole-page queue,
because the shell's display gate is wired to open selects. The box keeps its node, caret, selection and undo
for as long as it holds focus; a stale mark that moves it after the reader leaves it remounts the box, and the
words survive but native undo does not. A failed read of the project's observed record says "could not be
read" where the legacy page, which reads only the focused session's record, says "not read yet": the Intent
panel here reads both, and neither sentence is an empty record. Dismissal has no legacy web surface (nothing in
the web assets calls the dismiss route), so none was built.

Two departures from the recorded answers, 2026-10-13. The coverage line's adopted-source sentence said
"Analyze read up to 1,000 characters" for every adopted source whatever the prompt's length, so it read as
a limit that had bitten. The cap is real (a reading takes the head of a prompt's words) and the sentence now
says only that: "Analyze reads at most the first 1,000 characters of any prompt." `result.differential.test.ts`
swaps the retired sentence for the new one before comparing, and no other recorded text changes. And a
reading that cites an entry the page holds none for, while older entries remain to load, adds one sentence
naming the count and pointing at Show more. The criterion carries that count as `unloaded`; the retired page
had no such field, so both differentials drop it before a recorded answer's key is computed
(`withoutKey` in `legacy.test.helper.ts`). The page still loads no record page by itself
([reader state](design-reader-state.md#the-inventory)).

DEC-27 row 3 removes Analyze again from a current result; the count, disclosure and cap stay.
A stale result keeps one run control in its reason callout, and a direction question replaces it.
Finding buttons jump by stored fact id to the current activity rows, reveal cited rows outside
the display bound, label them with the finding's stored words and current numbers, and focus
the first. Each button names its constraint and stored clause; Enter and Space both activate it.
A selection is discarded when its session, reading or resolved citations disappear, so returning
cannot restore its marks. After a keyboard-started analysis finishes, the current result heading
inherits the running title's focus key. Reduced motion scrolls instantly. The drift proof compares
retained content against unchanged recordings with the new jump buttons removed from its comparison snapshot and
the obsolete current-result run button removed from the recorded side. Dedicated assertions
cover every added button, missing citations, renumbering, focus, scrolling and zero non-GET requests
or launches, including while ordinary GET polling continues.

### The first analysis click budget

[DEC-27](design-reading-a-session.md#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result)
holds the path from a Sessions row's goal link to a stored analysis to these ceilings.
`frontend/e2e/journey-budget.mjs`, run by `pnpm test:journey:browser`, observes trusted
browser activations. A pointer press or Enter activation of a control or link counts once,
including clicking into the goal box. Typing, focus moves and waiting for the background job
do not count. The how-to is opened and closed outside the counted path.

| Fixture | Counted path | Click ceiling |
| -- | -- | -- |
| Accept the first-prompt draft, with no later direction | Row goal link, Analyze drift, Allow and analyze | 3 |
| Accept the draft, with two later directions | Row goal link, Keep my intent twice, Allow and analyze | 4 |
| Type over a draft on a running session | Row goal link to Intent heading, goal box, Save intent, Analyze drift, Allow and analyze | 5 |
| Type with no draft on a running session | Row goal link into the box, Save intent, Analyze drift, Allow and analyze | 4 |

Both draft paths run for a running session, an ended session and a Claude turn-stop with its
last turn recorded. The first Keep draws every direction whole and saves nothing; the second
settles them and opens consent. Neither draft path presses Save intent. A typed save sets the
goal's baseline to now, leaving no later direction at that moment.

Each fixture has a fresh browser context and no Allow for the route's receiver, its words
destination or its tool-output destination. The synthetic Intent backend performs saves and
prompt adoption; the Drift script supplies the model job and stored assessment without calling
a model. Completion requires the level, findings and cited evidence with recorded times to be
read in place without another activation. A goal-only result can say Not enough recorded yet.
The nondeparture fixture keeps the same three-click ceiling and reads the cited entry in
Session activity without another press; a departure is not required to qualify as a result.

Two refusal fixtures also remain on the path: a goal typed on an ended session states before
typing that words saved now cannot be read against it, then says "saved after this session ended"
with no result; idle without a recorded stop keeps Analyze inert and shows its refusal sentence.
Their attempted paths cost four and two activations respectively, without a model request.

The proof runs in development and `COMPASS_E2E_BUNDLE=production` modes, packaging only
its worktree scratch copy. `JOURNEY_MUTATION=confirm-step` adds a confirmation before Allow;
it must fail the three-click draft ceiling at four clicks. Production shard a carries the
proof once, with shard membership pinned by `test_frontend_quality_gate.py`.

The other end of the journey, from a stored reading to a copied correction, is held by a unit
test in the pre-PR suite, `frontend/src/drift/CopiedCorrectionPresses.test.tsx`. It starts on the
Sessions list and counts activations the same way: the row's goal link, Steer back, Copy, three
in all, with no model request and no post besides composing the correction and recording the
copy. Making Copy need a second press fails it on the clipboard assertion.

## Project views, steering and the Console

Deviations (2026-10-12): The recovery strip uses Where this project stands, Current task,
Running now, Needs you, Latest result and Latest instruction. Its source and absence labels say
instruction rather than goal; the session's own words remain intact. The steering bar is
Your note (this tab only), shortened to stay on one line at 375 px. Its explanatory sentence
is unchanged. The authority gloss is conditional on a first-officer
session or an enabled stage source, and Workflow stage conditions becomes Stage alerts with
its enabled-source gate retained. Needs you still names a waiting session above the tabs.
Task evidence uses Evidence · task source and Task evidence not published; the workflow
continuation says FO CONTINUES · Continue current task. Instruction sources say latest
instruction. Missing child tasks and sources say task unavailable and task source unavailable
in the recovery and Decisions render layers, while internal sentinels and published values
stay intact. Observed-model comparisons rename only the derived instruction-source fields;
the Console proof normalises the recorded contributor region while preserving published values.
Member rows request the Sessions goal link's Intent focus in one click. Project parity changes
only the recorded labels and conditional gloss; chrome references retain measured styles and
note the renamed instruction surface. The shorter task-source disclosure measures 173.969 px
at both 1280 and 375 px, replacing the recorded 227.891 px text width; its styles and row
filling are unchanged. The no-workflow fixture rejects old labels and counts
member clicks. Goldens stay unchanged.

The Projects list and history, project detail with its workflow plans, the scope tree and switcher, the
recovery briefing, the human-context notes, Now and Course, the workstream panel, the steering bar, local
and workflow-stage tripwires, the Decisions timeline with its lanes and the Console operating rail
(delegation, waiting, capacity as the project page draws them) are ports of the project half of the legacy
page. The pure functions were run next to the legacy source, the whole legacy page loaded in one `vm`
for the project model, over hundreds to thousands of generated boards each, with sensitivity mutants and
non-vacuity floors so a green run cannot be an empty comparison. Two browser proofs serve one board to the
legacy page and the React page in one Chromium: the project views over the list and every project state
(no sessions, stale focus, a failed read, no plan, ended without an end stamp, hostile text), and the
steering, tripwire, Decisions and Console surfaces over a real backend, including the retained terminal.

Drafts and notes are native editors keyed by the exact project or session: text, caret, selection and
native undo survive board revisions, tab changes and a route away and back, and are never reused for
another project, which is the defect the Intent step found. Tripwires and steering text are browser
preferences. They are never sent to a session and the surfaces say they are not enforcement. A stage
condition saves through one explicit POST with the shared 15 second bound, never retried, and a lost or
non-JSON answer says "Could not save the stage condition." The workstream observes the board from the
first payload (the shell starts it) and keeps the legacy collapse key without adopting the old
unnamespaced one; a missing window reads "since this tab opened", never zero.

Deviations, each recorded rather than hidden: Add human context is not offered at a focused session (the
legacy page offered a button that opened an editor nothing drew); the recovery strip, Now and Course build
delegation lanes from the project-scope assignments, where the legacy page read a cache the Decisions tab
happened to seed, while the Decisions tab builds them from the selected scope's own context read, a
focused session's when one is selected, as the legacy page does; a
non-record member of the hierarchy is skipped where legacy throws; the tripwire box takes focus when it
opens and gives it back to its button, and an Enter that commits an IME composition adds no rule; a usage
entry with no harness name states the absence where legacy throws; disclosures use the shared accordion;
panels are plain sections inside the shell's tab panel. Not ported because nothing in the legacy source
calls them: `nextCockpitNowState`, `ActiveDelegation`, `NeedsYou`, `SystemDetails`, `TaskSubject`,
`MemoFields`, `ProjectStatus`, `RecoveryOutcome` and `nextProjectWorkstream`.

## Attention, notifications, capacity and the consent controls

Deviation (DEC-27, 2026-10-12): Exact requests and reported blocks move here from Sessions,
with their wording, figures and notes unchanged. Mounted and browser assertions check them
beside the existing Attention evidence; the recorded queues and notification comparisons remain.

The Attention view (exact-owner asks and checkpoints, gates, risks, outcomes and coverage), the
notification control and owner, the capacity strip, the usage consent and the observer-model consent
controls are ports of `next-attention.js`, `next-notify.js`, `next-capacity.js` and the Console observer
parts of `next-cockpit.js`. The models and text builders were run next to the legacy source over
hundreds to thousands of generated boards, the owner in lockstep over 300 sequences, and two browser
proofs compare the rendered pages in one Chromium and use a scripted `Notification` API: nothing here
ever creates a native notification.

Consent is a press and nothing else. The quota parameter rides `/api/data` only after an explicit yes
answered on this origin and stops when it is turned off; unanswered and declined send nothing and read no
credential, through mount, StrictMode, polls, reconnects, route changes, reload and another tab's storage
event. An answer removed from storage is withdrawn at the next read, where the legacy page kept a copy in
memory alive until reload. The observer-model press names the consent and the offer the reader saw and is
refused locally, with a rendered sentence and no request, if either changed; quota consent never
authorizes it, and a double click sends one request. The notification prompt opens only from its button,
a reload with permission already granted raises nothing for gates already on the board, a native lane
suppresses the browser's, and the lane report is one attempt that names no session. The runtime now says
whether this tab holds the live stream, so only that tab raises a workflow stage banner.

Deviations from the legacy page, recorded rather than hidden: the lane report is sent as soon as the
reader grants rather than at the next payload; a stamp that is not a date prints without a time, where the
legacy Attention view throws and draws nothing; a board that published no session collection says so
instead of printing "0 of 0"; a usage entry with no harness name is drawn with the absence stated; the
unknown reading count clause is dropped where legacy printed "null readings"; answering the usage
question refreshes the board by hand, as legacy did, and focus lands on the new switch instead of being
lost; and Console usage sits in the Console rail where the project page draws its operating rail. A board
with usage but no session collection (the server always publishes one) draws the Sessions view's absence
sentence without the capacity strip.

## Reader state and storage

Each reader-state row specifies stable identity, stored state, retained deferral or a mechanism
that can be retired only after a browser proves it unnecessary. Unmanaged text selection remains
an explicit limit, not an invented guarantee. Native editors may require uncontrolled elements
and refs: replacing a textarea or writing its value can erase undo even when its text looks right.
Open selects, composition, disclosure motion and pointer dispatch retain their tested behavior.

Browser storage stays readable by earlier builds, which a reader's browser may still hold, and by this
one. Key formats, value types, scope, TTLs and bounds are kept, including dormant keys until their
retirement is justified. Unsaved Intent and correction text remains in memory rather than browser storage.
Actions run only after explicit reader presses; mounting, StrictMode and HMR cannot start readings,
clipboard writes, saves or credential-backed usage fetches.

## Fluidity measurements

Measure the assembled production page against controlled small, median and large session cohorts.
Record fixture sizes, page digest/bytes, browser version, platform and sampling method. Use repeated
new-document loads and actual background polls to measure first render, poll-to-paint and long tasks.
Count removed nodes and whether edited/open nodes keep identity. Track listener, timer and socket
counts over repeated navigation, without calling an unobserved metric zero.

Before cutover, compare the same fixtures, browser and method. Set timing budgets from measured
baseline medians with a documented noise margin; bundle growth has its own explicit allowance.
Edited or open nodes must not be replaced by unrelated updates. Resource counts must settle rather
than grow with navigation. A fast component test is not a browser performance measurement.

Retired on 2026-10-14. The tooling that composed and checked these measurements
(`scripts/frontend_cutover.py`, the fluidity driver and its fixture) and the three receipts it read
(`docs/frontend-baseline.json`, `docs/frontend-fluidity.json` and `docs/frontend-cutover-receipt.json`) were
removed once the default had flipped to React and the legacy page was gone. The baseline they compared
against could not be re-measured, and the Python suite checked the fluidity receipt against the digest of the
built page, so every change to the page turned the suite red until someone re-measured in Chrome and
recomposed the receipt. What follows is the record of what was measured and ruled. The files are in git
history at `16591221` and earlier. Nothing now re-measures these budgets, so a change that could move first
render, poll-to-paint or retained listeners is measured by hand, the way the method above describes.

The pre-React baseline recorded three complete runs: three first-render observations and nine poll
observations per cohort. The probe and the fixture that produced it were removed with the legacy page, so it
could not be re-measured. Its budgets and medians derived from the runs it embedded. The 5/50/250 cohorts
are controlled scenarios, not a measured distribution of real users. Each run started a fresh browser profile; later cohorts shared that profile and may reuse browser/font
caches. Update samples invoked the actual `nextRefreshPoll` path, not a manual refresh that bypasses its
open-select hold. The metric ends two animation frames after the title marker appears, so it is a
frame-boundary proxy rather than proof of compositor presentation.

The baseline bound the runtime page and both measurement scripts by digest. On the same recorded
machine/browser/method, the timing budget is the baseline median multiplied by 1.5 plus 50 ms.
The historical core HTML budget allowed 25% growth; packaging accounts separately for the optional terminal. These are
comparison budgets, not cross-platform CI deadlines. Native goal typing kept words, caret and
focus in every run, while its node was replaced. Correction undo and composition remain separate
browser obligations. TCP, EventSource resource counts and retained detached nodes were not measured.

The React measurement held three complete runs of the fluidity driver against the assembled React page, on
the same platform, fixtures, browser family and method as the baseline. The driver began as the baseline
driver and differed from it in seven ways. The React page has no global poll function, so the update
trigger is the page's own 20 second fallback-poll callback, captured from `setInterval` and invoked: the
background-poll path with its open-select and motion deferrals, not a manual refresh. The runs also count
open streams and removed nodes per update, hold an opened disclosure and the prompt select beside the typed
goal, check that native undo survives, and read a second navigation series after a forced collection. The
shared instrumentation was held line by line to the baseline's own text, apart from the additions it
declared, while the baseline probe existed. A control block, taken on the day of the runs, re-ran the
unchanged baseline driver and page with the same Chrome, so machine drift was visible: its medians sat
within noise of the recorded baseline.

The figures below are historical. Later layers recorded their measurements in
[the adoption record](design-shadcn-adoption.md#toolchain-layer).

At the legacy page's retirement on 2026-10-10 (Chrome 156.0.8078.12 against the baseline's 156.0.8078.4, a load average near 4 on ten
cores, measured against the final shipped page after the last rebuild) every timing budget passed by a wide
margin. First-render medians were 124.3, 95.0 and 128.5 ms against budgets of 199.1, 159.5 and 192.8;
poll-to-paint medians were 46.8, 47.0 and 63.5 ms against 119.8, 121.4 and 146.4; no run recorded a long
task. Against the legacy page re-run on 2026-10-09 with the same Chrome (control medians of 90.9, 62.6 and
96.5 ms first render, taken under a heavier load of about 5), React's first render is slower by 37%, 52% and
33%, inside every budget, and poll-to-paint is level (46.8, 47.0 and 63.5 ms against 47.3, 47.3 and
64.2). The core page is 1,376,448 bytes against the ceiling the baseline recorded, 1,816,276, and the legacy
page's 1,453,021,
which is 5.3% smaller; the optional terminal assets (488,663 and 7,112 bytes) are accounted apart, as they
were. The typed goal, an opened disclosure and the focused prompt select kept their nodes through a poll
that changed every row title, and the draft, caret, focus and native undo survived, where the baseline
replaced the goal node on every poll. The cohort polls removed no node; the editor update removed two.

The ceiling stopped being the baseline's. On 2026-10-10 the owner re-based it to a fixed 2,000,000 bytes
because the page is served from the reader's machine and the time budgets measure the cost the size stood in
for. The baseline's own record kept its figure and its digest. A layer that needed more raised the ceiling in
its own pull request with its measured times; see [the adoption record](design-shadcn-adoption.md).

Read the baseline's way, with no collection forced, the page's JavaScript event listeners grow by 37 per
navigation round (1,815 to 2,000 across five rounds through Projects, Attention and Sessions) where the
legacy page held 48, and its node count grows by 531 a round where the legacy page's grew by 583 with no
listeners on those nodes. Timers, intervals, WebSockets and the one live stream stay flat. After a forced
collection before each reading, listeners, nodes and documents are exactly constant (207, 664 and 1) in all
three runs, so the raw growth is detached nodes the browser had not yet collected, not retained ones. The rule
is that resource counts must settle rather than grow with navigation, and retained growth is what matters, so
the settle criterion is evaluated after a forced collection: every counter must be exactly constant across
the five rounds, and a mutation that left a count higher after collection failed it. The uncollected series
was kept in the receipt as `gc_pending`, round by round beside the legacy page's own, informational and not a
budget. The forced-collection criterion was ruled by the migration lead at cutover review on 2026-10-09,
under the owner's standing delegation; the owner has not reviewed it. The first composition judged the
raw listener series and recorded it as a failed budget, and that receipt was recomposed from its own runs
under the ruling. A later rebuild changed the page, and the runs recorded here were taken against that final
page and judged under the ruling from the start.

## The cutover receipt

Retired on 2026-10-14 with the fluidity tooling. The mapped receipt mapped every row of the ownership map
(20 parts, 39 surfaces, 17 routes, 49 reader-state rows and 12 storage families) to the React-side proof that
stood for it: a vitest file and test title, a browser proof and its step, a Python test for server code both
pages share, or a fluidity verdict. A row was proven, proven with a recorded deviation, deferred to a named
owner, or an explicit gap, and a Python test checked that every named file, title and step still existed, so a
renamed proof could not leave a row quietly unproven. It proved that the named proof existed, not that it was
adequate: each mapping was chosen against the row's contract text, and a reviewer owned that judgement. A
second block recorded, for each surface class, the proof for keyboard operation, 320 and 375 CSS px, 200% zoom
and native editor continuity. It held no gaps.

What checks the map now is `python3 scripts/frontend_inventory.py` (see [the ownership map](#the-ownership-map)):
every row has an owner, a contract and oracles that exist as files. It does not check test titles or browser
step names, so renaming a proof is no longer caught by a check of its own. The proof either still runs or its
own suite fails.

Every parity proof can run against the shipped `react.html` rather than the development server:
`COMPASS_E2E_BUNDLE=production` makes the Python backend serve the minified page, `pnpm
test:production:browser` runs all twelve, and CI runs them as the `Frontend production bundle` job in two
shards. The limits of that run are these. The controls
proof mounts the controls gallery, a combination of shared controls no one page draws together, so in the
shipped composition those controls are proven through the shell, sessions, project, intent, drift and
attention proofs and not by the gallery's own cases. The storage proof's React side is the storage codec
bundled minified in a browser, not a served page. Three harness-only readings are replaced on the shipped
page by what a reader can observe (the terminal owner's counters become the renderer count and the open
sockets, the console's accepted-board count becomes the count of board answers, and a manual refresh
becomes another tab's revision announcement), and the proofs say so where they do it. StrictMode double
effects exist only in development, so every development proof remains runnable locally. Since
2026-10-11, CI keeps the macOS frontend checks, including hot refresh, storage, shell, controls and
sessions, and the Linux production job's two shards. The separate `Frontend proofs` job and the
Linux and Windows development matrix legs have been retired after the major refactor. Windows is
also no longer exercised by the dashboard unit suite in CI; macOS and Linux still are. The local
pre-PR command list is unchanged.

The legacy compatibility seam `next-cockpit-compat.js` has no React twin by design. The React timeline and
terminal are native components, so nothing lends them globals.

## Retiring the legacy page and final verification

The default flip came first: React was made the default through one constant, `DEFAULT_FRONTEND`, which
the parser, `build_runtime_config` and the detached child's argument list all read, with
`--frontend legacy` as the explicit process-level rollback. Candidate parity, native editor checks,
degraded states and measured budgets were complete before it. The removal followed, and left nothing that
can serve, assemble, select or roll back to the legacy page:

- The legacy page's assembly, its shell (`index.html`), its style rules and its tests are gone (`styles.css`
  keeps only the font-face rows the build embeds): the byte-pin
  and source-text tests, the Python harness that evaluated its JavaScript, `scripts/lint_embedded.py` and
  `scripts/regen_byte_pins.py`. A test that was about Python server behaviour and only used that harness
  was kept and adapted rather than deleted.
- `--frontend`, `DEFAULT_FRONTEND`, `FRONTENDS`, `RuntimeConfig.frontend`, `lifecycle.probe_frontend`, the
  status and in-use sentences that named the renderer on a busy port, and the rollback text in the
  load-failure message are gone. `load_frontend_page()` and `build_id()` take no argument.
- The twenty legacy script parts and `frozen_page.load_script()` stay, frozen, under
  `scripts/frozen-page/` for the paused study's source binding only. They are not shipped, not served,
  not rendered, and nothing in the frontend or the runtime may read them. They left the plugin for
  1.0.0 without changing a byte, so every digest the study bound still holds. Deleting them has to
  rebind the study.
- What replaced the removed oracles is a behavioural or build-integrity check for each: the recorded
  vitest and browser differentials above, the React-side behaviour and browser proofs the
  inventory names, the hostile-literal parser proof, the installed
  smoke proof and `pnpm build:check`. The inventory rows that named a deleted Python test now name those.

Candidate parity runs against the shipped bytes as well as the development server. Setting
`COMPASS_E2E_BUNDLE=production` makes the shared proof support (`frontend/e2e/support/world.mjs`) start the
Python backend with no development ticket, so it serves the minified `react.html`;
the default stays the development server, and a StrictMode-specific assertion keeps running there because
the production build has no double effect. A proof that serves a scratch copy of the tree (a harness
entry, the controls gallery or a deliberate mutation) has that copy packaged with the same `packageFrontend`
the tracked artifact comes from, so it is served a production build too. Measured on a desktop, all twelve
parity proofs passed in production mode with no behavioural difference from development; the harness-hosted
proofs differ from the shipped page in composition, which the limits above state.
`pnpm test:production:browser` runs them, and CI runs two shards of it as `Frontend production bundle`.
The two native `frontend` legs share their proofs with a second job, `Frontend proofs`, so no leg runs
every proof in one sitting.

The hold was a tracked `RELEASE_HOLD` file at the repository root, and was lifted for 1.0.0. `release_transition.py resolve`
refuses while main carries it, so a fresh release and a resume stop in the credential-free job
before any verifier, tag move or push, and `assert-checkout` reads main again in the publishing job, so a hold
merged while the verifiers ran still stops a resume before the bump, the tag move or `stable`; the owner lifts it by deleting the file in a reviewed pull
request. The release skill owns the procedure. Hold releases until the final same-main-build browser,
Python-only install and backend-connected development checks pass.

### Final verification record

The evidence pass ran on the merged retirement (the tree of its last pull request head, byte for byte) and
on the one product change it found.

- Browser: every development and production-bundle proof, the computed-style proof and the hostile-literal
  parser proof passed on that tree on a desktop, and the same proofs ran on Linux, macOS and Windows in CI. The
  hosted runs needed two reruns for failures outside the change (a Windows-only race in the annotation store's
  thread test, and the drift proof's teardown described below); neither touched code the change altered.
- Fluidity: three fresh runs on 2026-10-10 judged against the same budgets, none failed (figures above).
- Installed: a copy of the plugin without Node passes the runtime inventory (119 files) and the installed smoke
  proof, which refuses external requests and hides Node from Python.
- Development: the Python plus Vite proof (hot refresh, event stream, backend restart, refused origins) passes.
  It failed in 4 of 29 local runs before a fix and in none of 30 after: Chromium reported a response the restart
  cut short as `net::ERR_CONTENT_LENGTH_MISMATCH`, which the proof's allowance for restart-time network errors
  did not name.
- Teardown: the drift proof failed on the hosted Ubuntu runner in two of three runs with an unhandled
  `route.fetch: Request context disposed`, from a scripted handler still in flight when the proof closed its
  context. Closing a context mid-fetch reproduced it on demand; the handlers now set aside only that closing error.
- Release transition: in a throwaway clone whose remote is a local bare repository, `rehearse` refused while
  `RELEASE_HOLD` was present, before verifying, bumping or tagging anything. With the file removed in that clone
  only, a fresh release of an invented tag ran resolve, verify, bump, archive proof, tag move and `stable`, the
  bump changed only the three owned manifests and left `react.html` byte for byte, and a second run resumed the
  same release commit. Nothing touched the real remote.
- Defect: the computed-style proof found `box-shadow: var(--e-raise)` in the project popover naming a custom
  property the previous page declared in its root block and `shell.css` did not, so the popover drew no shadow.
  It is declared now, the proof's pin is gone, and the page was rebuilt and measured again.

What this cannot show: real GitHub Actions, the deploy key and the repository rulesets behave as the rehearsal
does, because no disposable fork was available; the Release workflow's job boundaries are pinned by tests and
actionlint, not exercised. Controlled fixtures prove frontend behaviour, not model accuracy. The hold stays until
the owner lifts it in a reviewed pull request.

The Intent and drift study remains paused. Controlled reading fixtures prove frontend parity,
not model accuracy. Earlier failed measurements stay failed. A future study resume must bind the
final runtime again rather than reuse a pre-migration source binding.


### Activity list order

The retired page listed the numbered activity oldest first and showed "Add to my intent" only on hover.
The owner ruled on 2026-10-12 that the list reads newest first and that the button is always drawn. The
numbers are the oldest-first ones every "#<n>" and citation names, so the column
reads from the highest down to #1. `frontend/src/drift/WorkListView.test.tsx` holds both. The drift
parity proof restates the rows in number order on a copy before it compares them with the recorded
answer, which is unchanged. The list is ordered by time over every kind of entry; a check or a message
the agent wrote sits between the prompts either side of it. Where the rows look grouped, the record read
for the session holds no entry of the other kind in that stretch: the agent's messages come from the record pages, within the harness limits in the [page contract](design-session-record-pages.md#route-contract).

Opening a session reads its newest fifty message entries through `/api/session-record`, and reads
the newest page again whenever the session's published activity changes, merging it by `fact_id`
so an entry that arrives while the page is open is never lost when the board's tail-bound context
moves past it. Show more alone requests each older page, up to fifty entries; no poll, manual
refresh or idle control prefetches one. The page merges context and record facts by `fact_id`, with the record
winning a conflict; checks and workflow facts still come from context. An unsaved direction
opened from a record page keeps its words in the existing intent store across leaving and
returning. Discarding record pages does not prove that its older source entry is gone; reconciliation
waits for that entry or the record start, without retaining the old page. Every loaded timed entry
in the intent window is listed, together with cited or revealed entries and open later directions.
The former twenty general rows and ten agent messages are retired. Where the server
publishes fixed numbers, each entry is drawn with its own and loading older entries renumbers nothing;
where it does not, loading older entries in the window recomputes every number, oldest first, and the list
says "Numbers count from the oldest entry loaded." The full merged set remains available for citations.

Focus remains on Show more after an append. If it disappears, focus reaches the first new row,
or the boundary sentence when the page added no visible row, without scrolling. A later focus
chosen by the reader wins. The paging control states loading, failure and retry, a byte or time stop with its measured MB,
record start, unsupported harness and a stale restart. A stale response drops held pages and
restarts once; another stale response waits for the reader. Once the oldest loaded record entry
predates the intent window, the control is replaced by "Everything since your intent's window
opened is listed." The [reader-state row](design-reader-state.md#the-inventory) owns the record's lifetime, its
newest-end refresh and the abort on leave. `frontend/src/drift/record.test.tsx` and
`frontend/src/transport/record.test.ts` hold paging and survival; `frontend/stories/RecordPages.stories.tsx`
asserts each control state and scroll and focus during an append in Chromium.

The recorded-side `projectRecordedLoadedSource` in the work differential replaces the old
source slice and its shown count with the recording's full source. `projectRecordedLoadedActivity`
in `frontend/test/recorded-loaded-activity.ts` retains every existing recorded row, reconstructs
only rows hidden by the old caps from the recorded full source, and removes only the retired cap
caption. Both full comparisons still run every recorded seed. The golden files are unchanged.
The browser parity snapshot omits the new paging region on its cloned panel; its scripted backend
now answers record reads from its synthetic facts. No browser parity run is claimed.

The header appends "Started about <duration> ago" to the existing identity line. It reads
`started_at`, falling back to `first_prompt_at`, and draws nothing when neither is published.
The title contains exact local time; the fallback says "From the first message in the record".
`projectRecordedSessionAge` in the session detail differential appends the age from the
recording's published timestamp before comparing the retained header. The shared browser recorded-side projection in `frontend/e2e/support/session-deviations.mjs` does the same for session headers, guarded by its Node tests. Session detail tests and
`frontend/stories/SessionAge.stories.tsx` hold start, fallback, absence and phone wrapping.

The same ruling shortens the row head. The actor and type now say "Agent said" once. The model
keeps the original `toolReportLine` words exactly, while a check shows "No result", "Passed" or
"Failed" beside a Phosphor mark. Each mark carries the full result words as its accessible name and
hover tooltip; "About this record" also states every mark in its Marks legend. "Before the last
change" and "An earlier run failed" are icon-only alongside the result. All marks use muted caption
ink, including the hollow absence circle. Time moves into the head's right cluster after flags and
"Last turn", whose accessible name and tooltip remain "from the last turn". The entry's own words
remain in its body.

Three or more consecutive eligible checks fold into a closed Collapsible. Failed checks, checks
with an earlier failure, cited checks, selected finding entries and written files split a run and
stay listed. The header states counts, number range and newest-to-oldest times. Members stay mounted
under `hiddenUntilFound`; expanding shows them in drawn order. The footer still counts entries.
Open state belongs to the existing disclosure store under the oldest member id, project and exact
session scope. A new check at the newest end does not close it. The [reader-state inventory](design-reader-state.md#the-inventory)
and both migration records map that state to the mounted survival test.

`frontend/test/recorded-activity.ts` projects only the retired "Agent said" type to "said" on the
recorded side of the model differential. No fixture or assertion is loosened. On its cloned panel,
`frontend/e2e/drift-parity.mjs` flattens mounted fold members, omits headers and the new legend,
restates heads from `data-next-entry-words`, and puts time and the full last-turn phrase back in the
body before comparing oldest first. It applies the same exact actor correction to the recorded
head. The browser proof was edited but not run for this change. Component stories assert marks,
hover, fold opening, failure splits and narrow head wrapping. No browser or fluidity measurement
is claimed by those stories.

### Popover snapshot ancestry

Popover bodies move through a portal inside the app root, retaining their mounted content while
closed. Sessions' recorded text snapshots included closed native bodies. The proof rejoins a
cloned popup body to its labelled trigger in a virtual snapshot; it never moves the live nodes.
Popover triggers are now native buttons, so the snapshot's existing action-button list excludes
those triggers just as it excluded native summaries. The controls and popover proofs check their
new button role, focus and target floor directly. The computed Button reference uses the same
trigger identity for portalled descendants and reads their actual computed styles. The recorded
fixtures are unchanged. [The adoption record](design-shadcn-adoption.md#popover-layer) owns the
component and cascade decisions.
