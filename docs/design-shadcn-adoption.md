# Adopting shadcn/ui and Tailwind 4

This record owns what was measured before the frontend moved to shadcn/ui components and a Tailwind 4
stylesheet, the ruling that came out of it, and the rules every layer of the migration follows. The
[frontend record](design-frontend-migration.md) owns what the React page is and how it was held to the page
it replaced; the [reader-state inventory](design-reader-state.md#the-inventory) owns what a redraw must keep.

## Verdict

Adopted with the reader-state contracts intact. The last measured page stayed inside every fluidity time budget;
the layer records below describe the browser proofs and platform checks that were run. The original go
decision required repeated Linux production drift checks for the disclosure and popover layers after the
spike crashed Chromium's renderer. Those layers record their qualification separately from the spike
findings. While the receipt existed, each change to the page required fresh fluidity measurements and a
recomposed receipt, because the Python suite checked its final form on every pull request. The tooling and
the receipt were retired on 2026-10-14, so those measurements are the last ones. The work was larger than installing
a package: ten things broke or silently misbehaved under a naive install, each listed below.

The ten, in the order they are met:

1. pnpm writes a supply-chain exclusion for a package younger than its release-age policy instead of refusing it.
2. The `shadcn` command line is 282 packages as a dev dependency.
3. `shadcn init` cannot detect this repository's layout.
4. `shadcn add` installs an unrelated npm package named `cn` and imports it.
5. Two components import a whole icon library for two chevrons.
6. Under the scale reset, default size, radius, animation and data-variant classes generate nothing, silently.
7. Tailwind's `dark:` variant emits a `prefers-color-scheme` rule, and the vendored classes read variables the
   page does not declare; both fail the production CSS contract.
8. Vendored files nothing uses still emit CSS, because Tailwind reads files as text.
9. The development server, the unit-test config and `tsconfig.json` each need the toolchain or the alias
   written into them separately.
10. Biome rejects the vendored files' formatting and their export shape.

Owner rulings: popovers use the shadcn Popover; tailwind-merge is kept; the page is served from the reader's
own machine, so growth in size is accepted and the guard against slowness is time, not bytes. After the
measurement the owner confirmed (2026-10-10) that the component flavour is Base UI and that the fluidity
receipt's byte ceiling is re-based to 2,000,000 bytes, to be raised again if a layer needs it.

## End state

Fourteen shadcn components are vendored under `frontend/src/ui/`, using the Base UI flavour and the
local `cn` merger. The directory also holds Compass's inline disclosure chevron, Phosphor icon
gateway and Button tests.
The components keep the existing semantic roots, field owners and disclosure store.

| Vendored file | Shipped use | Layer record |
|---|---|---|
| `button.tsx` | Shared actions, pending actions, tabs, switches and filters; plain links use `buttonVariants`. | [Button](#button-layer) |
| `accordion.tsx` | The accordion variant of `Disclosure`, including session, project and timeline evidence. | [Disclosures](#accordion-and-collapsible-layer) |
| `collapsible.tsx` | The armed Intent discard offer. | [Disclosures](#accordion-and-collapsible-layer) |
| `popover.tsx` | The popover variant of `Disclosure`, including Sessions caveats, reentry Why and Drift sending details. | [Popover](#popover-layer) |
| `select.tsx` | Prompt, workflow stage and pending direction choices through shadcn Base UI Select. | [Fields](#form-controls-layer) |
| `input.tsx` | Project steering and local tripwire drafts through `DraftInput`. | [Fields](#form-controls-layer) |
| `textarea.tsx` | Goal, outcomes, pending direction, context notes and correction drafts through their existing uncontrolled owners. | [Fields](#form-controls-layer) |
| `label.tsx` | Native field associations in Intent, context, correction and stage controls. | [Fields](#form-controls-layer) |
| `badge.tsx` | Session and drift state, prompt origin, activity flags, course tags, read-only terminal and blocked notifications. | [Sessions](#sessions-layer), [Intent and Drift](#intent-drift-and-steering-layer), [Project](#project-console-timeline-shell-and-terminal-layer), [Attention](#attention-capacity-and-consent-layer) |
| `card.tsx` | Session rows and panels, Intent and Drift panels, project and Console surfaces, timeline evidence, terminal chrome, Attention queues and Capacity windows and consent. | [Sessions](#sessions-layer), [Intent and Drift](#intent-drift-and-steering-layer), [Project](#project-console-timeline-shell-and-terminal-layer), [Attention](#attention-capacity-and-consent-layer) |
| `alert.tsx` | Health notes, polite failures and shell or observer status; static log, drift, timeline and terminal messages disable announcements. | [Sessions](#sessions-layer), [Intent and Drift](#intent-drift-and-steering-layer), [Project](#project-console-timeline-shell-and-terminal-layer), [Attention](#attention-capacity-and-consent-layer) |
| `separator.tsx` | The decorative notification boundary in session details. | [Sessions](#sessions-layer) |
| `tooltip.tsx` | Activity marks and the Last turn word, with accessible full words and a text legend. | [Icons and tooltips](#icons-and-tooltips) |
| `tabs.tsx` | Route-controlled `ProjectTabs` with automatic keyboard activation; only Root, List and Trigger are retained. | [Project](#project-console-timeline-shell-and-terminal-layer) |

Native menus keep their deliberate exemption from Escape dismissal. Select choices use Base UI popup and keyboard handling; uncontrolled
editor nodes retain native focus, undo, composition and dragged dimensions. Native progress elements
and title tooltips remain because the swap offered no gain; the Capacity budget bar keeps its two
independent quantities. Facts, evidence rows, switches, meter segments, result glyphs and conditional
status paragraphs keep the semantic grouping or lifecycle named in their layer records. The xterm host
and persistent live regions retain their owners. Empty was not vendored; absence sentences remain in
their existing groups and roles. Unused Card and Alert parts and TabsContent were omitted, the last
because a second panel lifecycle would duplicate route ownership. Icon-library imports, the npm `cn`
package, Preflight and animation-package imports were also omitted for the reasons in the findings.

The last page measured before the 2026-10-12 Select replacement was 1,608,668 bytes against a
2,000,000-byte ceiling. Hand-written CSS at that measurement was 124,635 bytes
across the same thirteen counted sheets. The cleanup's rough starting estimate was about 135,500 bytes;
its recorded start was 136,243, a reduction of 11,608 bytes. The whole migration started at 161,464
counted bytes. The [cleanup](#stylesheet-cleanup) removed 83 rule entries, including the alias block,
duplicate keyframe steps and redundant Raise weight, and retired all eighteen `--ctl-*` aliases.
The counting rule excludes the Tailwind entry, so moving the 42 page tokens into its static theme
contributes to the saving without deleting those tokens.

The coverage record retains 57 exact exception identities covering 58 rule entries, with reasons for
optional evidence, transient states, browser-specific progress and individual animation steps. The computed-style contract gained no
readability exception; the form layer removed four native focus-ring exceptions. The coverage method's
five limits are recorded in [Stylesheet cleanup](#stylesheet-cleanup).

The three-run fluidity measurement on 2026-10-11, before the Base UI Select replacement, passed every budget. For 5, 50
and 250 sessions, first-render medians are 148.6, 94.3 and 127.6 ms; poll-to-paint medians are 44.7, 44.5 and 61.4
ms. The earlier layer measurements below remain the history of how the page reached this state; the cleanup
measurement in [Stylesheet cleanup](#stylesheet-cleanup) records the page before the fix (1,608,412 bytes).

## What was measured, and how

The spike figures in Findings came from a throwaway branch off `main` at `cde1188b` (never merged) on one machine
(macOS arm64, Node 26.10.0, pnpm 12.9.1, Chrome 156) unless a row says otherwise. The branch added
`tailwindcss` and `@tailwindcss/vite` 4.3.3, `@base-ui/react` 1.8.0, `class-variance-authority` 0.7.1,
`clsx` 2.1.1 and `tailwind-merge` 3.7.0, vendored eight shadcn components (Button, Accordion, Collapsible,
Popover, NativeSelect, Input, Textarea, Label) and rendered each of them, hidden, from the real page so the
bundle carried and ran them. The browser behaviour comparison was run in headless Chromium through
Playwright 1.63 against one small page per library, and the popover and a pending button were repeated by
hand in headed Chrome 156. The layer sections record their own later measurements.

## Findings

### Installing under the pnpm policy

`pnpm add` succeeds under `ignoreScripts`, `strictDepBuilds`, `allowBuilds: {}`, `strictPeerDependencies` and
the frozen lockfile, with no build script and no approval. The lockfile carries the Tailwind native packages
for every platform (twelve `@tailwindcss/oxide-*` variants, including linux x64 and win32 x64), so no
platform needs a resolution of its own.

Three things were not what the plan assumed.

- `@base-ui/react` 1.9.0 was published a day before the measurement and is younger than pnpm's minimum
  release age. pnpm did not refuse it: it wrote `minimumReleaseAgeExclude` entries for it and for
  `@base-ui/utils` into `pnpm-workspace.yaml`, which switches the supply-chain delay off for those packages.
  The branch pins 1.8.0 instead (published 2026-09-04) and the workspace file is unchanged. A change that
  adds a `minimumReleaseAgeExclude` line is a change to the security policy and is reviewed as one.
- Adding the `shadcn` command line as a dev dependency adds 282 packages to the lockfile for a tool that runs
  on a developer's machine a few times a year. `pnpm dlx shadcn@4.21.4 <command>` runs the same pinned version
  without touching the lockfile, and was measured to start in 1.4 seconds with the store warm. The procedure
  uses `dlx` with an exact version.
- `shadcn init` stops with "could not detect a supported framework": the Vite config lives in `frontend/`, not
  at the repository root. `components.json` is written by hand (Base UI flavour, `frontend/src/styles/tailwind.css`
  as the stylesheet, `@/ui` as the component directory) and `shadcn add` works from it.

### What `shadcn add` writes

- The registry item lists `cn` as an npm dependency. `shadcn add` therefore added the npm package `cn` 0.4.0
  (published by the shadcn author, 380 KB unpacked, "a drop-in replacement for clsx and tailwind-merge") to
  `package.json` and wrote `import { cn } from "cn"` into every component. The branch removed the package,
  wrote `frontend/src/lib/utils.ts` and rewrote the imports. Every later `add` needs the same two steps, which
  the procedure records.
- Two components import from `lucide-react`, a package of hundreds of icons, for two chevrons. They are two
  inline SVGs in `frontend/src/ui/icons.tsx`.
- Defaults are written for shadcn's own scale: `text-sm`, `rounded-lg`, `h-8`, thirty-two `dark:` classes, and
  `data-open:` and `animate-in` classes that come from `tw-animate-css` and `shadcn/tailwind.css`. Under
  Compass's scale reset (below) the size, radius and animation classes generate nothing, silently. The branch
  rewrote them with one script (`text-sm` to `text-body`, `rounded-lg` to `rounded-control`, `h-8` to
  `min-h-11`, `dark:` and animation classes removed). The vendored files are Compass's code after that, and a
  scan test must catch a default-scale class entering one (see the rules).
- `shadcn/tailwind.css` is not imported. It is 16 KB of custom variants, keyframes and scroll-fade utilities;
  the vendored files use two of its variants (`data-open` and `data-closed`), which are copied into the entry
  stylesheet.

### The single-file build and the CSS gates

- `pnpm build` passes: one chunk, one CSS asset, no `@import` and no non-`data:` `url()` in the built CSS, the
  fifteen fonts, and a thirteenth bundled licence (Base UI, its utilities and floating-positioning packages,
  tailwind-merge, clsx and cva) found and written by the existing notices step. The notices step covers
  packages, not copied source: the copied shadcn licence text was absent from `react-licenses.txt` in the
  spike; the toolchain layer now ships the full copied-source notice.
- `css.test.ts` fails once, on the Tailwind entry's `@import`. A two-line allowance, for exactly
  `@import 'tailwindcss/theme.css' layer(theme);` and `@import 'tailwindcss/utilities.css' layer(utilities);`,
  is enough, and a third import still fails. The type-size, variable and scheme tests pass.
- `css-contract.mjs` passes in development and production-bundle mode with the inventory of exceptions
  unchanged, once the token bridge is complete. Before that it failed in production mode with five undeclared
  custom properties (`--foreground`, `--secondary`, `--radius-md`, `--accordion-panel-height` and
  `--transform-origin`; the last two are set at run time by Base UI) and with a `prefers-color-scheme` rule
  that Tailwind's default `dark:` variant emits. The bridge declares the missing variables and redefines the
  `dark` variant so it never emits a media query. The contract compares `--ink*` registers as strings only
  (`rgbOf` strips whitespace and nothing more), so any colour form works as long as those registers are not
  redefined.
- It does not check 44 px targets. Several proofs do on the real routes (`controls-continuity.mjs`,
  `capacity-parity.mjs` and others); the contract would need a step to cover the component gallery.

### Cascade, layers and the terminal stylesheet

Tailwind puts utilities in a cascade layer, and an unlayered rule beats any layered one, so the thirteen
hand-written sheets were wrapped, mechanically, in `@layer legacy { ... }` below the `theme` and `utilities`
layers. Preflight is not imported: the UA defaults that the exact-set exceptions rely on (`offScale`,
`uaLinks`, `uaFocusRing`) do not move, which the unchanged inventory shows. The terminal stylesheet is
loaded at run time from `/assets/xterm.css` and is unlayered, so it now beats the layered page rules wherever
they overlap; the terminal proof passes in both bundle modes. An overlap that matters would be a regression in
how the terminal host looks, which a proof about behaviour does not measure, so the layer that touches the
terminal checks it by eye.

### Source detection

Tailwind reads files as text, not imports. With the default settings it read all thirteen vendored files and
emitted 27.7 KB of utility CSS for components nothing used. Boundaries work: `source(none)` plus
`@source '..'` and `@source not` globs for tests, the gallery and stylesheets removes it (1,609,020 bytes
against 1,609,756 for the page with eight used components). Vendoring each component in the layer that first
uses it, and deleting one with no importer, keeps the scan honest.

### Scale and tokens

`@theme { --text-*: initial; --radius-*: initial; --color-*: initial; }` followed by the five type steps, four
radii and the semantic colours mapped onto the existing tokens as hex works: a default `text-sm` generates
nothing. shadcn's own `--accent` and Compass's `--accent` are different things (a hover surface and a lime
colour), so the semantic names are reached only through `--color-*`, and plain `--foreground` and
`--secondary` are declared because the vendored classes read them directly.

### tailwind-merge

Kept, as ruled. Unconfigured it reads Compass's type steps as colours: `twMerge('text-body', 'text-muted-foreground')`
returns only `text-muted-foreground`. shadcn's own `cn` package has the same behaviour. The branch configures
`extendTailwindMerge` with the five steps and four radii, and a test reads the theme names from the entry
stylesheet and fails if a step or radius exists that the configuration does not know, and a real conflict
(`p-2` then `p-4`) still resolves.

### Flavour

React Aria (`react-aria-components` 1.22) and Base UI were compared in Chromium on the four things Compass
depends on. Base UI is the choice. The detail is in the table.

| Behaviour | Base UI 1.8.0 | React Aria 1.22 |
|---|---|---|
| Pending button stays focusable, ignores click, Enter, Space | yes; `aria-disabled` set, no `disabled`; app supplies `aria-busy` and any announcement | yes; `aria-disabled` set; announces the button's own label assertively only when focused; no `aria-busy` |
| Closed section revealed by same-document fragment navigation | yes with `hiddenUntilFound` (`beforematch` fires) | yes, always on |
| Same, on a fresh load of a client-rendered page | no | no |
| Open popover with a polite live region beside the app root | live region stays exposed in every modal mode; focus can be left on the trigger; portal can mount in a given container | default modal mode makes the live region `inert`, so announcements are lost; fixable only with `isNonModal`, which loses the stock dialog focus handling |
| Controlled open state | follows an external store exactly; one change callback per click; never writes back | follows; writes back an out-of-range value through its own callback |
| Raw JS, Button, Button plus Accordion, plus Popover (over react-dom alone, 219,486 bytes) | +7,857, +22,762, +113,348 | +37,191, +42,725, +96,532 |

Both fail a deep link on a fresh load because the page mounts after the browser's fragment pass; the page has
to re-apply the hash after first render if it wants one. In headed Chrome 156 `window.find()` did not reveal a
closed section; the browser's own find bar could not be driven by the available tooling, so the in-page find
claim rests on the fragment-navigation behaviour and is not confirmed with the real bar.

### Cost in time

Three fresh fluidity runs per page on the same machine, base page against the page carrying the adopted set:

| | Base page (1,376,448 bytes) | With the adopted set (1,609,756 bytes) |
|---|---|---|
| First render median, small / median / large cohort | 145.5 / 95.7 / 127.8 ms | 149.1 / 95.0 / 127.8 ms |
| Poll to paint median, small / median / large | 45.7 / 46.1 / 63.2 ms | 45.5 / 45.5 / 63.3 ms |
| Long tasks | none | none |
| Budgets (first render, poll to paint) | pass | pass |
| Resource counts after collection | constant | constant |

The page grew by 233 KB and first render moved by at most 3.6 ms, inside the run-to-run spread. The byte
ceiling in the fluidity receipt (1.25 times the replaced page, 1,816,276 bytes) was a proxy for that cost; the
time budgets are the guard. The owner re-based the ceiling to 2,000,000 bytes, which keeps the proxy as a
tripwire and left room for the display components adopted in later layers. A layer that would cross it
raises it in its own pull request, with its measured times.

### Tooling

- Biome: the vendored files fail formatting (shadcn writes double quotes) and fail
  `useComponentExportOnlyModules` for the variant helpers they export next to components. One override for
  `frontend/src/ui/**` turns that rule off, and `biome format --write` on that directory is a step after every
  `add`.
- TypeScript 6 rejects `baseUrl` (deprecated); `paths` alone resolves the `@/` alias. With `skipLibCheck: false`
  the new packages' types check cleanly.
- The owned development server (`frontend/dev/vite-worker.mjs`) creates its own Vite server with
  `configFile: false`, so it needs `tailwindcss()` and the alias of its own; without them every
  `@/ui/...` import returned 500 and the development proofs timed out. The unit-test config
  (`vitest.config.mts`) needs the alias too. Three configs, one alias.
- jsdom 30 needed no polyfill for Button, Accordion, Popover or the then NativeSelect (seven tests, no
  warnings). That measurement predates the 2026-10-12 swap to the Base UI Select, which is exercised
  through its combobox and option roles instead.
- Linux (arm64 container, Node 26.10): `pnpm build:check` reproduces the macOS artifact byte for byte,
  `pnpm test` passes (1,439 tests) and `pnpm typecheck` passes.
- Continuous integration on the throwaway pull request (the three platform legs of the frontend job): the frozen
  install takes 5 seconds on Windows, 6 on macOS and 2 on Linux, under the unchanged policy; the clean preview
  build takes 3, 1 and 1 seconds; the canonical rebuild on Linux x64 reproduces the tracked artifact byte for
  byte; the owned development lifecycle tests and the Python plus Vite hot refresh proof pass on all three.
  The unit-test step took 159 seconds on Windows (110 on macOS, 113 on Linux) against a step limit of 180, so
  the Windows margin is 21 seconds and shrinks with every added test.
- Windows found one defect in the branch's own test change: the allowance for the Tailwind entry compared a
  relative path with a forward slash, and Windows reports a backslash, so the narrow `@import` allowance did not
  apply. The comparison normalises separators now. Any new path comparison in a test needs the same care.

### Gates that were run on the branch

Dev and production-bundle `css-contract.mjs`, terminal, controls, shell, sessions and intent proofs (all
pass), the owned development lifecycle tests and the Python plus Vite development proof (pass), and the whole
vitest suite (1,432 tests at the time). The full proof set was not run on the branch.

### What the gates already require, and what broke

- `scripts/tests/test_frontend_cutover.py` ran `frontend_cutover.py check --final` against the committed
  receipts, in the Python suite, on every pull request, until both were retired on 2026-10-14. Any change to
  the page therefore turned the Python jobs red until the fluidity receipt was re-measured and composed again. The earlier assumption that only the
  release hold reads the final form was wrong. Every layer re-measures three times (about 45 seconds on this
  machine) and recomposes; `compose` does not carry the embedded legacy control block over, so the layer
  restores it, and this should be one command.
- On Linux the production-bundle drift proof crashed Chromium's renderer ("Target crashed", then every later
  step failing on `about:blank`) in 7 of 13 container runs (three of six with the container's shared memory raised
  to 2 GB, so it is not shared memory) and in 2 of 2 runs of the pull request's Ubuntu production job, with the
  full adopted set bundled and rendered. The unmodified page passed 5 of 5; Tailwind
  alone passed 5 of 5; the light components (Button, Input, Textarea, Label, NativeSelect with tailwind-merge)
  passed 5 of 5; the set with Accordion and Collapsible and without Popover passed 5 of 5; the set with
  Popover and without Accordion and Collapsible passed 5 of 5. The same proof passed on macOS. The cause was
  unknown at the spike: no single component reproduced it, and only the full set did. The original gate
  required five clean production drift runs before the disclosure and popover layers merged. The later
  [single-file build record](design-frontend-migration.md#candidate-packaging) identifies Chromium's
  callback source-name growth and the short `sourceURL` that bounded it; the popover layer records the
  clean production proof after that fix.

## What each pattern becomes

| Pattern | Decision | Reason |
|---|---|---|
| Button, link-as-button | adopt Button; links use `buttonVariants` on a plain `<a>` | Base UI Button always sets `role="button"`, which would hide a link |
| Pending button | adopt, `aria-disabled` and `aria-busy` kept, ghost label kept | Base UI keeps it focusable; `aria-busy` and the announcement are Compass's |
| Disclosure, accordion variant | adopt Accordion and Collapsible with `hiddenUntilFound` | needs the reactive store first; state precedence is specified in that layer |
| Disclosure, popover variant | adopt Popover (owner ruling), non-modal, initial focus left on the trigger | live regions must stay exposed |
| Disclosure, menu variant | keep native | not dismissed by Escape by design; not a popover |
| Select | adopt Base UI Select (owner, 2026-10-12) | an async prompt read outlives native picker activation; the popup opens immediately and retains React state |
| Textarea, input | restyle with Textarea and Input classes; stay uncontrolled | native undo and composition |
| Tabs (`ProjectTabs`) | adopted route-controlled Tabs after testing automatic activation and modifier keys | original labelled panel and route ownership retained |
| `role="status"` banner | adopted polite Alert; static messages disable announcements | the registry's assertive default would change the contract |
| `<progress>`, `title` tooltips | keep native | nothing gained; hover-only text is worse on touch |
| Badge, Card, Separator | adopted on the surfaces named in the layer records | shared recipes retain the original semantic roots |
| Empty | not vendored | absence sentences retain their existing groups and roles |

## Rules every layer follows

1. One stack. Component layers change `react.html`, so they land in dependency order from one stack, each rebuilt
   from a clean `node_modules`. Every layer changing the page re-measured fluidity three times and recomposed the receipt, because
   the Python suite checked the final form on every pull request, so each layer's page was release-qualified when
   it merged. The release hold stayed until 1.0.0. A merged layer that regressed was reverted by its own pull
   request and its receipts reconciled.
2. Keep public APIs: `Disclosure`, `ActionButton` and `HeldTextarea` keep their props.
3. Own the code. A component is vendored into `frontend/src/ui/` in the layer that first uses it, tuned to
   Compass's scale, with a header naming the upstream component, the CLI version, the registry source and a
   hash of the upstream file as fetched (the registry serves each item as JSON, so the hash is the hash of its
   `content`). Upstream MIT licence text for copied code ships in `react-licenses.txt`. A vendored file with
   no importer in shipped code is deleted. After every `add`: remove the `cn` package it adds, rewrite the
   `cn` import, run `biome format --write frontend/src/ui`, and run the scale rewrite.
4. Native stays native where the reader-state contract needs it: the uncontrolled textarea,
   `title`, `<progress>`, the live regions, and the menu disclosure variant until a ruling changes it. Each is
   a recorded decision with its reason.
5. A layer deletes the CSS it replaces in the same layer and moves the gate edits with it (size, focus,
   absence, target size, exact-set exceptions, mutation fixtures); the pull request shows each gate still
   failing against a mutation that removes the rule.
6. A layer re-points the proofs for what it moves to roles and `data-slot`; no new class-name selector enters
   a proof.
7. No new type size, colour space or motion outside the existing tokens. A scan fails a default-scale class
   (`text-sm`, `rounded-lg`) and an arbitrary font size in a component, because under the reset they would
   silently style nothing. A hand-written CSS ratchet records the exact byte total and its counting rule, fails
   when the actual total differs, and a CI check fails when the record rose against the pull request base.
8. Adoption follows the owner's brief: use the shadcn component wherever a hand-written pattern has a
   corresponding one, for consistency, unless it cannot keep a reader-state contract. Each layer is held to the
   fluidity time budgets and the proofs.
9. Review tier: the form-control layer gets full adversarial review (typed words); the disclosure and popover
   layers get two lenses plus an arbiter; others follow `AGENTS.md`.
10. Each layer runs `sync-docs` and updates the documents its change makes false.

## The pull request procedure for a component

```bash
pnpm dlx shadcn@4.21.4 add <component> -y
pnpm remove cn                                  # the registry lists the npm package `cn` as a dependency
sed -i 's#from "cn"#from "@/lib/utils"#' frontend/src/ui/<component>.tsx
pnpm exec biome format --write frontend/src/ui
pnpm build && pnpm build:check
```

Then run the scale rewrite, add the upstream header, add the gallery entry, and delete the CSS the component
replaces.

## What was not verified

The spike did not verify the browser's find bar, any screen reader, Firefox and WebKit, touch, or Windows
and Linux x64 timings outside what its pull request's CI legs recorded. It did not run the full browser proof set.

## Toolchain layer

The first layer adds Tailwind 4.3.3, its Vite plugin, clsx and class-variance-authority. No component,
`cn`, Base UI or tailwind-merge is introduced. The thirteen sheets gain only an outer `legacy` layer;
their rule bodies are unchanged. The entry imports theme and utilities without Preflight.

Scanning all of `frontend/src` emitted utility rules from ordinary words such as `hidden` and `filter`
despite there being no utility callers. The entry therefore scans `ui/**/*.{ts,tsx}` and
`lib/**/*.{ts,tsx}`, excludes tests, the gallery and stylesheets, and uses `source(none)`. Later layers
added an explicit source glob for utility callers outside those directories. Nothing was vendored in
this layer. `frontend/build/style-policy.mjs` rejects a vendored module unreachable from the shipped
entry through runtime imports, exports or dynamic imports with literal targets (including template
literals without substitutions). Type-only imports and unreachable modules do not qualify; imports inside `if (false)`
still count. It scans TS and TSX strings outside tests for default scale classes and arbitrary font
sizes, using the pinned Tailwind compiler to distinguish font sizes from colors. Custom variants in
the excluded entry may contain selectors and `@slot;` only; declarations are refused.

`frontend/css-budget.json` records 161,464 bytes and its counting rule. Count UTF-8 bytes after CRLF
to LF normalization, including comments, across every CSS file under `frontend/`, except the
directive-only Tailwind entry. Strip only the mechanical outer `@layer legacy` wrapper. The record
inventories paths; a new sheet outside that inventory fails. Ordinary rules in the excluded entry
fail separately, so moving a rule there cannot hide it. The actual total must equal the record.

CI compares the record with `github.event.pull_request.base.sha`, fetched with full history, and
refuses an increased count or an added counted path. When introducing the record, it derives the
allowance from the base's actual sheets instead of trusting the new record. An implementation PR
cannot grant itself an increase. An owner-approved increase requires a separate reviewed baseline
change, with the justified rules and matching record, landed using an explicit required-check
override; subsequent layers use that new base. There is no label or head-side opt-out in the gate.

The package includes the configuration, entry and any later vendored files in provenance. Copied
shadcn source gets the full upstream MIT notice in `react-licenses.txt`. The component CLI procedure
and upstream-header fields are in [Contributing](../CONTRIBUTING.md#adding-a-shadcn-component).

Measured on 2026-10-10: the page grows from 1,376,448 to 1,376,752 bytes, an increase of 304. JavaScript
stays byte for byte at 701,374 bytes; CSS grows by 229 bytes for layers and bridged variables, with no
utility rules and no imports in the built CSS. Three fresh fluidity runs pass every budget, retain
native editor state and settle resource counts after collection. The historical legacy control is
preserved by the cutover tooling's `remeasure` command (since retired), which first checked the clean build and
left the previous receipt untouched if measurement failed.

All development and production proofs pass on macOS, including the owned development worker and
terminal's first asset load. Both CSS bundle modes keep the exception inventory unchanged across
87 views. Linux arm64 reproduces the artifact and passes all twelve production proof commands plus
an extra production drift run. Five deliberate mutations fail: default type scale, arbitrary font
size, an unused vendored module, CSS growth and a rule hidden in the excluded entry. Native Windows
was not run here; the separator normalization is tested, and the unit-test step now allows six
minutes against the spike's measured 159 seconds.

## Button layer

The first component layer vendors Base UI Button with the pinned registry procedure, adds Base UI
1.8.0 and tailwind-merge 3.7.0, and introduces `frontend/src/lib/utils.ts`. Its merger knows the five
type steps and four radii. Tests compare those names with the entry stylesheet, so an added theme
step requires an explicit merger update.

All 46 button elements use Button. The ten anchor elements stay plain links with `buttonVariants`;
no link is rendered through Base UI. Surface-specific tabs, switches, filters and row layouts keep
their own rules through the native variant. ActionButton keeps its public props. Call sites name
their weight explicitly; the wrapper no longer translates deleted shared class names. Surface chrome is expressed by variants and props.

A pending button owns its keyboard and click handling. Base UI's focusable-disabled path cancelled
Escape and the shell shortcuts as well as activation, so Button keeps the native node enabled,
emits `aria-disabled` and `aria-busy`, and suppresses only clicks, Enter and Space. Escape, Tab and
the shell shortcuts remain uncancelled. The unit test checks both halves. An inert action that
must explain a refusal still delivers its press to the handler. The busy label sits over a hidden idle label in an absolute overlay, so the old
answer button's measured growth from 94.23 to 114.63 px is gone. A caller's explicit reserve still
holds a wider busy label at rest and while pending. This verifies exposed ARIA state, not screen-reader announcement.

The shared chrome, copy and raise states, terminal button chrome, answer padding and busy rules
are removed from the sheets. The CSS record falls from 161,464 to 153,203 bytes. The component
gallery includes default, hover, keyboard focus, pending, disabled, retry, long text, primary, quiet
and linked actions, plus an explicit width reservation. The initial adoption measured the gallery at
1280 and 320 px in both bundle modes, alongside real-route type, ring and target checks. The
correction was checked in development at this stage; production verification belonged to the stack-head rebuild.

The target floor stays at 44 CSS px, as in the replaced rule. A first attempt using Tailwind's
rem-based spacing step made the Console tab at least 88 px wide at 200% text size and overflowed
the 320 px shell by one pixel. The shell layout proof caught it; the fixed pixel floor lets text
and padding grow without doubling the minimum width of a tab.

Recorded-answer normalization ignores the shared utility classes and Base UI's redundant native
button role and default tab index. It still compares semantic surface classes, explicit roles,
nondefault tab order, text, targets and action attributes. The recorded fixtures are unchanged.

The utilities layer beats `legacy` regardless of selector specificity. The correction audit moved
conflicting surface chrome into Button variants and props, including menu rows, capacity windows,
memo controls, consent, muted actions, waiting-card padding and Raise refusal borders. The
[call-site audit](design-shadcn-button-audit.md) lists the ownership decisions.
`css-contract.mjs` compares every button instance on its real routes with a computed-style table
from `30bac258`: colour, background, four borders, display, padding, alignment and font. Mutating
the shared ink makes this gate fail. The gallery separately checks memo chrome, the solid retry boundary and both amber Raise
refusal states. The quiet pending border now stays solid on all four sides, preserving its 118.38 px resting width instead
of shrinking to 116.38 px with a bottom border only. The spinner is an inline SVG arc in place of
the CSS border spinner. Both changes are deliberate; neither changes the request or its label.

The fluidity receipt records three runs on 2026-10-10 that pass the unchanged budgets. Core HTML
is 1,436,780 bytes against the 2,000,000-byte ceiling. For 5, 50 and 250 sessions, first-render
medians are 143.7, 93.8 and 126.1 ms, and poll-to-paint medians are 43.1, 44.8 and 59.7 ms. The
receipt retains the historical legacy control; no timing allowance changed.

## Reactive disclosure state layer

This layer keeps native `details` and the public `Disclosure` props. It adds versioned snapshots
and a subscription to the keyed store, with the store as the single writer of open state. The
[reader-state record](design-reader-state.md#disclosure-write-precedence) owns grouping, queued
native events, focus, motion and dismissal. The accordion and popover component swaps remain
separate layers.

A summary activation writes the store synchronously and prevents the browser's later default
toggle. Native attribute changes from fragment navigation are captured with their version;
write notifications drain those records before React renders a newer write. This distinction
keeps a delayed native event from undoing a dismissal without treating a rendered attribute
change as another reader gesture.

Headless Chromium reveals a closed section through same-document fragment navigation, publishes
the opening to the store, and retains it through two polls and a remount. The actual browser find
bar is still unverified. Tests also cover external writes, rapid presses, independent siblings,
idempotent publishing and delayed events. A redundant close advances write precedence and
reapplies the store projection, so Escape also wins before a native opening has published. Mutations that remove version precedence, echo a
rendered toggle, omit subscriptions, publish repeated values, omit native capture or drop
dismissal all fail. Two more mutations that omit redundant-write precedence or projection fail.
The redundant-close test delivers a stale native opening after the close, because the browser
can coalesce its own queued events into a closing event that would hide missing precedence.
The controls proof's memory mutation drops the native opening's store write, so fragment
revelation cannot publish its opening for a remount.

Measured on 2026-10-10 in three fresh fluidity runs on the stacked page: the page is 1,438,844 bytes, 2,064 more than
the Button layer. First-render medians for small, median and large cohorts are 145.2, 93.4
and 126.5 ms; poll-to-paint medians are 44.9, 46.2 and 61.1 ms. Every budget passes, no long
task is recorded, edited and open nodes retain identity, and resource counts settle after
collection. The receipt preserves the historical legacy control.

## Accordion and Collapsible layer

The accordion variant of `Disclosure` uses a controlled Base UI Accordion with one keyed item per
root. Independent siblings form no exclusive group, so several sections in one session can stay
open together. The armed discard offer was a controlled Collapsible inside the More menu; since 2026-10-21 it is
drawn in the card, outside the menu, so a closed menu cannot hide its warning. Popover and menu variants keep native details and their existing dismissal
contracts. `Disclosure` keeps its public props and call sites.

Both panels use `hiddenUntilFound`. Base UI's `beforematch` callback writes the keyed store; the
library does not own open state. `useRevealFragment` re-applies a matching target hash after the
panel mounts, because the browser's initial fragment pass precedes client rendering. The controls
proof reaches text in a closed panel through same-document and fresh-load fragments, then checks
polls and remounts. The browser's own find bar cannot be driven by this tooling, so that bar remains
unverified.

The fresh-load proof mounts after the document's load event and waits for the first payload. A
same-hash assignment after load does nothing, so replay replaces the current history entry while
keeping the public URL and history length. Replay is remembered per disclosure key and hash: the
first payload can replace a loading-scope key, and that new owner still needs to reveal its target.
A same-key remount does not replay navigation over a reader's later close.

Panels transition height through `--accordion-panel-height` or `--collapsible-panel-height`, and
opacity through the existing 200 ms duration and easing tokens. No animation package is added.
Base UI suppresses an opening transition when the panel mounts open. Reduced motion disables
transitions; the proof checks computed transition property, animation name and stable open-panel heights.
Reduced motion also overrides Base UI's starting and ending height and opacity flags, which
otherwise draw one collapsed frame even with transitions disabled.
The trigger still holds background paint for 220 ms, except under reduced motion. The armed
warning opens without a transition. Each panel adds no inner content wrapper, and the inline
chevron replaces the registry's icon-library imports.

The cascade audit keeps surface chrome in the legacy sheets and gives adopted triggers only the
target floor and focus ring utilities. Native button defaults are reset in the legacy layer so
surface font, padding, alignment and ink rules still win there. Setup and timeline rules target
their own triggers, because a descendant selector would also restyle nested disclosures. Accordion item and header wrappers
carry no competing chrome. `frontend/e2e/disclosure-chrome-reference.json` records the actual
pre-swap cascade on `7d4a23c3`, measured over the CSS proof's 87 views before changing the markup.
The gate compares every reached trigger, including hidden controls; it does not change the retired
page's golden fixtures. The inline-size reference adds measurements from an archive of `7d4a23c3`
under the worktree's ignored `docs/screenshots/acc-fix/baseline/`, built once with the packager.
It compares row filling against parent content width and exact width for content-sized triggers,
before and after opening panels, and includes the populated Decisions timeline at 375 and
1280 px. Rounding has a 1.5 px allowance; clock labels allow 8 px for proportional digits.
Existing chrome columns stay unchanged.

Native block summaries filled their row at `inline-size:auto`; auto-width buttons
shrink instead, so the timeline trigger explicitly takes `100%` in `legacy`. The shared trigger
has no maximum-width utility to override surface caps, and the chevron reserves the native
marker's `.4em`. The setup surface keeps the container cap the pre-swap cascade computed.
A mutation restoring auto width must fail this gate. Setup proof locators target only the
setup's own trigger, excluding its nested accordions.

The gallery checks Accordion and Collapsible targets, type and focus at 1280 and 320 px.
Measured on 2026-10-10 in three fresh fluidity runs: the page is 1,465,036 bytes, 26,192 more than the
reactive state layer. First-render medians are 129.3, 92 and 125.6 ms and poll-to-paint medians are
44.4, 45.3 and 62.2 ms; every budget passes, and the opened session-facts disclosure keeps its node and its
open state across a poll. The measurement driver reads the disclosure by its accordion trigger now. The production
drift crash condition moved to qualification on hosted Linux runners for this layer.

The CSS proof now settles opened panels before measuring their text. The native proof read inside
the opening transition and missed some bodies at zero height. Newly reached harness-source prose,
recovery evidence and terminal-registration instructions use the existing 15 px sentence step;
no readability exception is added. Clock text in Saved triggers is normalized only for identity,
with all computed chrome still compared exactly.

Measured locally on 2026-10-10: controls and intent unit tests pass (238 tests), as do the dev
supervisor tests (17) and controls, sessions, intent, project and CSS browser proofs. The CSS proof
compares 403 reached disclosure triggers across 87 views. Ten controls mutations and four CSS
mutations fail at their intended gates, including delayed replay, loading-scope identity, history,
keyboard, revelation, motion, store memory, remounts, target floor and focus. Hand-written CSS falls
from 153,203 to 149,833 bytes, with the path inventory unchanged. Lint, typecheck and style policy
pass. These measurements do not certify the unbuilt production bundle or its fluidity receipt.


## Popover layer

The popover variant of `Disclosure` vendors shadcn Popover through the pinned Base UI registry
procedure. Base UI remains at 1.8.0; the temporary npm `cn` dependency is removed and the local
merger is used. No icon-library import or animation package is added. Menus retain native details.
The keyed store supplies `open` and receives every `onOpenChange`; Popover owns no competing
open state. The [reader-state record](design-reader-state.md#disclosure-write-precedence) owns the
close paths and their focus destinations.

The popup uses Base UI's default non-modal mode and disables initial and final focus. Its portal
receives the app root through `container`, and waits for that container before mounting, so no
popup link falls outside the existing 44 px rules. Opening scrolls the body once after two frames;
a poll or restored-open mount does not scroll it. Positioning flips and shifts against the
viewport with a 16 px collision inset. The body keeps the old reading measure and maximum window
width, and can scroll internally when larger text leaves less vertical space.

Base UI's Escape callback closes one popup, while Compass closes all and chooses one trigger.
`popoverEscape.ts` keeps only that document-level compatibility rule. In the browser proof, Base UI
left a popup open when focus moved to another page control after window blur. A blur handler on
the trigger and portalled popup closes those departures and ignores a missing related target. Outside presses remain with Base UI and deliver the destination's click without
returning focus. The former `popoverDismissal.ts` is deleted.

### Popover cascade audit

Utilities outrank every legacy selector, so the trigger receives only target and focus utilities.
Its native button defaults are reset alongside Accordion and Collapsible; the surface still owns
its font and chrome. No rule leaves the legacy layer and no `!important` is added.

| Instance or rule | Ownership after the swap |
|---|---|
| Sessions group caveat and session reentry Why | Existing transparent background, zero border and padding, flex display and inherited font stay in legacy. |
| Drift What is sent and its caveats | `next-cockpit-why` targets the Popover trigger too, retaining the 500-weight, 15 px, 1.55-line-height recipe. |
| Popup body | The vendored utilities keep 10 px vertical and 12 px horizontal padding, line border, control radius, raise background and the existing shadow. |
| Absolute end anchor and narrow-screen start anchor | Replaced by Base UI collision positioning; both old positioning rules and the obsolete Sessions selector are deleted. |
| Native popup marker and details-content fade | Replaced by the shared inline chevron and a 160 ms opacity transition; reduced motion suppresses the transition. Menu rules remain. |

Six native popover trigger identities were measured on `47ed3654` before the swap, across the
CSS proof's same 87 views. They extend `disclosure-chrome-reference.json`; the existing trigger
reference and the retired page's golden fixtures remain unchanged. Popover triggers are excluded
from the Button chrome table and checked in the disclosure table. Popup bodies stay mounted, as the native bodies did. Buttons inside a popup
keep their pre-swap reference identity through the popup's labelled trigger, with computed chrome
still read from their actual portalled nodes. Popup prose is measured with
each popup open separately, because an outside press correctly closes a sibling. The runtime
positioning variable `--available-height` has a default in the token bridge, like the existing
panel-height variables. Hand-written CSS falls from 149,833 to 147,587 bytes, with the counted
path inventory unchanged.

`popover-continuity.mjs` runs with the controls proof in development and production modes. It
checks every close path, document-order fallback, an outside click's delivery and destination
focus, window blur, simultaneous external openings, one opening scroll, a forced poll, popup
chrome, app-root targets and containment at 320 and 375 px and at 200 percent zoom. It reads a
new polite announcement through CDP `Accessibility.getFullAXTree`. Base UI exposes live regions
in modal modes too, as the original measurement found; the modal mutation therefore also checks
that ordinary outside page content remains exposed. That mutation renders Close inside Popup,
as Base UI requires for modal focus handling; the actual non-modal variant has no Close part.

Measured locally on 2026-10-10: the controls unit tests pass (114), and the controls, Sessions,
Intent, Project and CSS browser proofs pass. The CSS gate reaches 449 disclosure triggers and
1,387 Button instances over 87 views, with the existing exception inventory unchanged. Twenty-one
behavioural mutations fail at their intended gates, including destination focus theft, window
blur, all-open Escape, event ownership, document order, menu exemption, store memory, polling,
viewport containment, link targets, polite announcements and modal hiding. A separate cascade mutation fails on 46 popover trigger
instances. Logs, screenshots and the accessibility-tree capture stay under this worktree's
ignored `docs/screenshots/popover-layer/` directory. The dev lifecycle tests pass (17), as do
lint, typecheck and the CSS ratchet against `origin/main`.

Measured on 2026-10-10 in three fresh fluidity runs: the page is 1,590,632 bytes, 125,596 more than the
accordion layer and 409,368 under the 2,000,000-byte ceiling; the popover primitive and its positioning
code are the growth the owner accepted. First-render medians are 134.9, 94.2 and 126.4 ms and
poll-to-paint medians are 45, 45.3 and 62.2 ms; every budget passes. The production drift proof runs
clean against this bundle (see the source-name note in the migration record).

## Form controls layer

Select, Input, Textarea and Label use the pinned Base UI registry procedure. On 2026-10-12 the
owner reversed the original NativeSelect decision: the prompt request outlived the click's
transient activation, so the later `showPicker()` could fail silently after "Loading your prompts".
The replacement vendors the Base UI `select` registry item and removes NativeSelect.

The local merger, inline chevrons and check, page fonts, sunk trigger background, token border,
15 px sentence tier, 44 px targets and shared field focus ring replace registry defaults. No
icon library, animation package, size variant or dependency is added. Storybook's explicit optimizer
list adds the existing Select entry so its CommonJS store shim is prebundled. A non-modal portal drops
below the trigger with `alignItemWithTrigger=false`, scrolls within the available height, and
uses two-line items with full titles. Non-modal mode keeps the page and its live regions exposed.

PromptSelect (a button over a popover list since 2026-10-21; the Select this paragraph describes is retired for the prompt, though its opening order holds) opens before fetching and shows a disabled loading item in that popup, then choices
or one of two stated absences (none found in the part of the session read, or the read failed) in the same popup. The trigger stays "Use your prompt" until a
choice stands in the goal as a pending adoption, and reads "Replace with your prompt" beside a saved
typed goal; choosing saves nothing. It reserves 18rem on
wide screens and fills the remaining label-row width on narrow screens. Stage and direction keep
their controlled values and existing change owners. The focus keys remain on the trigger buttons.

The bounded background hold now reads actual trigger expansion, including focus in the portal;
a focused closed trigger does not hold. Popup closure releases once. React retains the popup
through ordinary, manual and capped paints. Escape closes only the popup before a disclosure or
route handler. The browser proof can now inspect the list itself, its position and its node.

Input and Textarea supply native nodes and chrome. DraftInput, DraftTextarea, HeldTextarea and the
correction owner keep their existing uncontrolled `defaultValue`, input callbacks, keys and refs.
No owner is moved into Base UI Field or given a controlled value. Content-driven sizing and its
fallback heights are removed from both Intent and Project sheets: rows set the initial height,
the reader can drag it vertically, and field memory restores the resulting dimensions. Visible
labels use Label with native associations; outcome rows also have individual accessible names.

### Field cascade audit

Utilities outrank legacy selectors before specificity is considered. The recipes therefore own
chrome explicitly, while surface sheets retain grid columns, flex placement and labels.

| Field | Recipe and retained surface rules |
|---|---|
| Project steer and local tripwire input | Input owns panel background, foreground ink, 8 px padding, border, radius, sans type and 1.55 line height. Steering keeps label flex and form layout. |
| Human-context note | Textarea memo owns sunk background, foreground ink, 8 px padding, radius, five-rem floor and 1.5 line height. Recovery keeps the field's grid column. |
| Goal and outcome line | Textarea intent owns value ink, panel background, 7 px padding, 1.55 line height and vertical resizing. An untouched drafted goal uses sunk background. Intent keeps grid placement. |
| Pending direction | The same intent recipe, with a 44 px floor. Content sizing no longer overrides a remembered drag. |
| Correction to paste | Textarea correction owns the former panel/value recipe and 120 px floor. Its existing composition and paint-pause owner stays in place. |
| Prompt, stage and direction select | Base UI SelectTrigger owns token border, sunk background, sans sentence type and a 44 px floor. Prompt and stage keep medium weight. The prompt wrapper reserves 18rem on wide screens and the remaining row width on narrow screens, unchanged through loading. Flex placement and an eight-pixel gap keep the inline ten-pixel chevron clear of the value. |
| Gallery draft | Textarea draft replaces the deleted ctl-draft chrome; the gallery choice uses Base UI Select. |

`field-chrome-reference.json` records sixteen identities from the pre-swap page at `bd79507d`,
the merge base of this layer and its predecessor. The same measurement helper rejects conflicting
styles for a repeated identity. The regular route sweep is supplemented by editable notes, an added
tripwire, a workflow stage choice, later-direction fields and a correction box. Keys contain
semantic owners and attributes, including the drafted flag, and no clock or count text. The gate
compares every reached field with that reference. Its explicit select adjustments replace UA
chrome with tokens and raise the direction choice from 13.3333 px Arial to the 15 px control tier.
The two prompt identities also record the approved 288 px desktop width, measured explicitly
so an intrinsic-width regression fails the gate. Other measured field chrome is unchanged.
Focus rings are shared two-pixel solid outlines, including
forced colours; the four former UA-ring exceptions are deleted.

The gallery checks field type, 44 px targets, focus, forced colours, chevron clearance and fixed
sizing at 1280, 375 and 320 px. Controls checks native Input, DraftTextarea and context notes;
Intent checks the real goal, outcome, pending direction, correction, context, steer and tripwire
fields. Keyboard undo/redo, Chromium IME, caret, inner scroll and a real vertical drag must survive
forced redraws. Mutations cover controlled fields, select deferral, chrome, type, targets, focus,
content sizing, chevron overlap, narrow-screen overflow and viewport restoration. Fourteen
browser mutations and three controlled-field unit mutations fail at their intended assertions.

The scoped controls, intent and steering unit run passes 287 tests in 32 files with two workers.
The 17 development lifecycle tests and development-mode Controls, Intent, Sessions, Project and
CSS proofs pass. The CSS sweep reaches 87 views and compares 128 fields with the pre-swap table.

Hand-written CSS falls from 147,587 to 143,657 bytes with the path inventory unchanged. Measured on
2026-10-10 in three fresh fluidity runs: the page is 1,592,656 bytes, 2,024 more than the popover layer.
First-render medians are 139.7, 93.5 and 126.6 ms and poll-to-paint medians are 44.3, 44.9 and 62.2 ms;
every budget passes, and in all three runs the edited textarea and the focused select keep their nodes and
the select keeps its choice. Local checks do not certify a native autofill popup, screen readers, Firefox
or WebKit.

## Sessions layer

Badge, Card, Separator and Alert are copied through the pinned Base UI registry procedure.
The temporary npm `cn` dependency is removed; the package and lockfile are unchanged. Each copied
file names its upstream content digest. Unused Card and Alert subcomponents are not retained.

Session rows, current activity, the held request and the two landing panels use Card. Their
original article, section and div roots remain. The header state pill uses Badge. Health uses
Alert with its original aside and note role; the answer failure uses Alert with a polite status
role. A failure retains its node and text through polls, so the same notice is not inserted again.
The notification boundary uses a decorative Separator. The registry's orientation variants
expected attributes the pinned Base UI does not emit. They now read `data-orientation`, which
preserves the measured one-pixel rule.

### Sessions cascade audit

| Surface | Component chrome and retained layout |
|---|---|
| Session row | Card owns grid display, full row width, ink, lower rule, hover surface and the small-screen border, radius and panel background. The sheet keeps column layouts, overlay positioning, lifecycle shadows and semantic children. |
| Current activity | Card owns the 14 by 17 px padding, rule border, two-pixel tone edge, panel background and card radius. Tone is passed explicitly from the observed session. |
| Held request | Card owns the 13 by 16 px padding, rule border, amber edge, panel background and card radius. The existing question, option order and answer owner stay in place. |
| Landing panels | Card owns flex display, four-pixel gap, nine-pixel inset and the left rule. The sheet keeps the two-column arrangement, sentence registers and wrapping. |
| State pill | Badge owns the two by eight px padding, line border, pill radius, muted ink and mono label type. The visually hidden State prefix stays. |
| Health and failure | Alert owns their measured padding, ink, type and borders. Margins remain with the surface sheet. Health keeps note semantics; only the answer failure is a live status. |
| Notification rule | Separator replaces the section's top border. Its one-pixel height and ten-pixel lower space retain the old boundary and heading position. |

Facts retain native dl, dt and dd grouping. Their row rules, task and worker boundaries and the
left rules grouping departure evidence remain part of those semantic rows. Fleet fact cells,
plain lifecycle labels and collision sentences are not independent panels or pills. Lifecycle
dots keep their filled, quiet and ended shapes. Source-gap lists, native title tooltips and
progress elements retain their contracts. The separately owned Intent and Drift panels are
outside this family. No reader-state owner moves, and no legacy rule leaves its layer.

`session-chrome-reference.json` records 24 identities from `a5aae027` before the swap. An archive
of `origin/main` under this worktree's ignored screenshots directory was built once. The existing
87-view sweep recorded 232 instances; additional notification fixtures recorded the old rule.
Transient answer failures were measured at wide and narrow widths. Keys name surfaces, viewport
bands and semantic tones, never clocks, counts or absolute widths. The gate compares ink,
background, four borders, display, padding, radius and type on each adopted instance. Row widths
are fractions of parent content width, with a 0.015 rounding allowance. The pill's width is
compared with its actual rendered text plus chrome, with a 15 percent allowance for font metrics.
This catches a panel or row shrinking to its text without pinning macOS pixel widths on Linux.
The notification rule compares the old border's ink and thickness with the Separator's background
and height, plus the rendered width ratio. This projection compares the visible rule across its
change from a section border to a decorative child.

The Sessions browser comparison locates adopted surfaces by slot and retains the original logical
health-part name in its recorded summary. Text, evidence order, disclosure state and action lists
remain compared. No recorded fixture changes. Hand-written CSS falls from 143,898 to 142,131 bytes,
with the counted paths unchanged. Measured on 2026-10-11 in three fresh fluidity runs: the page is 1,597,124 bytes, 4,468 more than the
form controls layer; first-render medians are 141, 94.3 and 127.6 ms and poll-to-paint medians are 43.4, 44.7 and 61.2 ms;
every budget passes.

The dev CSS sweep passes with 234 adopted instances across 87 views. Scoped mutations fail the
Sessions comparison for Card padding (18 differences), row width (3), Badge ink (18), Alert padding
(1) and Separator thickness (2). The scoped sweeps also report their expected coverage omissions;
those omissions are not the mutation verdict. An assertive failure role fails the live-region
test, changed health evidence fails the recorded text differential, and a wrong logical health-part
name fails the browser differential at seed 2. The unmutated Sessions browser proof passes all
18 steps without a new departure.

## Intent, Drift and steering layer

This family reuses Badge, Card and Alert from the Sessions layer. No new component or package is
vendored. Card keeps the Intent log row, Intent editor, Drift section, running analysis, consent
step, stale-reading callout, correction box, observed-work panel and local steering receipt on
their original div or section roots. Badge keeps the drift pill, prompt-origin tag and activity
flags as spans. Alert keeps the Intent log notes and high-drift nudge as paragraphs.

### Intent and Drift cascade audit

| Surface | Component chrome and retained layout |
|---|---|
| Intent log row | Card owns flex display, three-pixel gap, nine-pixel inset and the left rule. The cells, words and links keep their original classes. |
| Intent editor | Card owns column display, six-pixel gap and zero padding, the recipe previously selected by its session-panel ancestor. Field layout, labels, held nodes and keys stay with Intent. |
| Drift section | Card owns block display, zero margin, four-pixel bottom padding, rule border, panel background and card radius. Heading and child spacing stay in the sheet. |
| Analysis and consent | Card owns column display, token gap and padding, panel background, card radius and reading measure; consent retains its line border and labelled group role. The job keeps no live-region role. |
| Stale reading and correction | Card owns column display and gap, plus the stale callout's amber border, padding and control radius. The correction retains its top margin and its existing uncontrolled editor owner. |
| Observed work and local receipt | Card owns the work panel's column layout and padding, and the receipt's ten-pixel padding, amber edge and panel background. Semantic rows and receipt children remain in their sheets. |
| Pills and tags | Badge owns the measured padding, borders, radius, ink and type. The drift pill retains its inline meter; activity flags retain their sibling spacing. |
| Log notes and nudge | Alert owns their measured type and chrome. Nudge margins remain with the surface. Both pass `announce={false}` because they were static paragraphs; the live estimate explicitly promises no announcement. Other Alerts retain their polite default. |

The live-monitor switch, meter segments and result glyphs remain native: a switch carries its
existing checked state, and result glyphs distinguish evidence states without a reassuring check
mark. State-dependent refusal paragraphs remain native because their role is conditional on
whether the persistent region already announced the sentence. Source labels, checklist and
activity-row rules, and the result-footer boundary remain part of their semantic groups rather
than new independent panels or Separators. Native title tooltips and progress elements are kept.
The existing controlled Collapsible for armed discard and keyed Accordion and Popover disclosures
are reused without changing their callbacks. No reader-state owner moves, no legacy rule leaves
its layer, and no golden or study-bound script changes.

`intent-chrome-reference.json` records 22 identities from `fd3e0ece`, the Sessions-layer tip before
this swap. An archive of that commit under this worktree's ignored screenshots directory was built
once. The existing 87-view sweep recorded the native surfaces; supplementary consent, live-level,
stale-result, correction and steering-receipt states completed the table. The same helper reads
native selectors only while recording, and component slots during verification. Keys contain
surfaces, viewport bands and activity-flag kinds, with no clocks, counts or absolute widths.
The gate compares ink, background, four borders, display, padding, radius and type on every reached
adopted instance. It compares row width with parent content width, allowing 0.015 for rounding,
and badge width with its actual content plus chrome, allowing 15 percent for font metrics.
Non-finite ratios fail. Static Alert roles are checked separately.

The development CSS sweep passes across 87 views, comparing 160 adopted instances. A smaller
family-only mode reaches the same reference identities for deliberate mutations. Card padding,
row width alone, Badge ink, Alert padding and an unwanted live-region role each fail the family
gate. Dropping the consent step in a scratch copy fails the existing Drift consent proof at its
missing-card assertion. Hand-written CSS falls from 142,131 to 140,163 bytes, a reduction of 1,968 bytes, with the
counted paths unchanged. The whole Vitest suite passes 1,486 tests and the build tests pass 23.
The final verification report records the browser-proof results. Measured on 2026-10-11 in three fresh fluidity runs: the page is 1,598,216 bytes, 1,092 more than the
Sessions layer; first-render medians are 147.8, 93.3 and 126.2 ms and poll-to-paint medians are 44.1, 44.4 and 61.2 ms;
every budget passes. Native Windows, Linux, screen readers, Firefox and WebKit were not measured locally.

## Project, Console, Timeline, shell and terminal layer

Tabs is copied through the pinned Base UI registry procedure. Only Root, List and Trigger are
retained; no new package remains after removing the CLI's temporary npm `cn` dependency. Its
header records the upstream content digest. This family reuses the existing Card, Badge and Alert.

ProjectTabs controls Tabs from the route and enables automatic activation on List. Arrow keys
wrap and activate the destination route; Home and End activate the first and last tab. Base UI
leaves Alt, Control and Meta presses uncancelled. The browser proof checks five real keyboard
activations, each tab's tabindex and twelve modified presses. The original nav, tab buttons,
labelled panel, ids, cues and focus keys remain. Root uses display:contents; the existing plain
panel keeps its children and their owners. No TabsContent is vendored because a second panel
lifecycle would duplicate the route's ownership. Unit keyboard assertions await Base UI's focus
microtask rather than assuming synchronous focus.

### Project and Console cascade audit

| Surface | Component chrome and retained layout |
|---|---|
| Project rows | Card owns grid display, full width, padding, line border, tone edge, radius, background and hover/focus border states. The sheet keeps columns, gaps, children and history labels. |
| Recovery and goal | Card owns grid display and the recovery boundary, plus the goal's column layout, gap, zero side padding, top rule and transparent surface. Cell layout, margins and words stay in the sheet. |
| Course and stage rules | Card owns course row padding and lower rule, and stage rule padding, border and radius. Badge owns course tag ink, mono label type, weight, normal line height and tracking. Semantic children and editor owners stay in place. |
| Console rail | Card owns panel column layout, gap, padding and first/last boundaries, plus waiting card padding, amber edge, radius and background. The rail's width and responsive placement remain in the sheet. |
| Timeline evidence | Card owns the evidence grid, gap, padding, left rule, background and type. Alert owns the stale paragraph's reading measure and normal-weight type. Margins, lanes, ordered evidence and disclosures remain unchanged. |
| Shell notices | Alert owns wrapping, padding, tone edge, background and sentence type. Reset and build notices retain their muted edge; every notice keeps its original polite status role. |
| Terminal chrome | Card owns the aside's column layout, border, radius, background, overflow and type. Badge owns the read-only tag's margin and ink. Alert owns absence padding and reading measure. |

The shell header and breadcrumbs keep their headings, navigation links and existing shared
controls. Timeline lanes and their rules, recovery cell dividers, source facts and rail child
boundaries remain part of semantic groups rather than independent Separators. Tab counts retain
their labelled cue markup; they are evidence, not independent pills. The terminal checking status
stays native because its conditional lifecycle belongs to the terminal owner. Static terminal
absence and stale timeline messages pass announce=false. The xterm host is untouched; the terminal
proof still accounts for exactly its two same-origin assets on first open. Native progress
and title tooltips remain. No reader-state owner or stored key moves, and no legacy rule leaves
its cascade layer.

`project-chrome-reference.json` records 63 identities from `f7b7f11f`, the starting commit before
this swap. Its archive was built once under this worktree's ignored screenshots directory.
The 87-view sweep and supplementary course, stage, stale timeline, open terminal, reset, build
and failed-refresh states record the native selectors. Verification reads the adopted slots.
Keys name surfaces, viewport bands, semantic states and inheritance contexts, never clocks,
counts or absolute widths. The gate compares ink, background, four borders, display, padding,
radius, type and roles. Row width is a fraction of the nearest rendered parent's content width,
with a 0.015 allowance; text width uses visible text plus chrome, with a 15 percent allowance
for font metrics. Visually hidden cue glosses do not contribute to that width. Non-finite ratios
fail. The development CSS proof passes across 87 views and 516 adopted instances, including the
existing Button, disclosure, field, Sessions and Intent gates.

The whole Vitest suite passes 1,487 tests in 132 files; build tests pass 23. Development browser
proofs pass Project (19 steps), Console (29), Terminal (19), Timeline filtering (13), shell (29),
Controls (22), Popover (10), Sessions (18), Intent (20), Drift (30), Attention (15) and Capacity (17).
The shell retains its existing first-payload absence departure; no recording changes.
Six scratch-copy chrome mutations fail the family gate: Card padding and row width each produce
four differences, Badge ink twenty, static Alert role two, tab-strip width twelve and shell Alert
padding six. Disabling the route callback fails the real keyboard activation step; restoring the
source passes that step. Removing display-class normalization fails the mounted differential.
Ten new helper tests reject non-finite widths, row shrinkage, changed ink, missing identities
and unwanted live roles while allowing the stated text-metric tolerance.

Hand-written CSS falls from 140,163 to 137,209 bytes, a reduction of 2,954 bytes with the counted
paths unchanged. Measured on 2026-10-11 in three fresh fluidity runs: the page is 1,619,656 bytes, 21,440 more than the
Intent and Drift layer; first-render medians are 144.2, 93.8 and 143.1 ms and poll-to-paint medians are 44.2, 44.6 and 61.6 ms;
every budget passes. Native Windows, Linux, screen readers, Firefox and WebKit are not measured locally.

## Attention, Capacity and consent layer

This family reuses Card, Badge and Alert from the previous layers. No new component or package
is vendored. Card keeps the Attention coverage brief and queue articles, each quota window row,
the selected window's prospect, and the quota and observer consent sections on their original
roots. Badge keeps the blocked-notification span and its native title. Alert keeps the observer
status and refusal paragraphs polite, with the same text and request lifecycle.

### Attention and Capacity cascade audit

| Surface | Component chrome and retained layout |
|---|---|
| Coverage brief | Card owns grid display, gap, padding, rule border, accent edge, panel background and card radius. Coverage children, labels and disclosure stay in Attention. |
| Queue article | Card owns grid display, padding, rule border, tone edge, background and radius. The sheet keeps responsive columns, gaps and evidence cells; off-board risks retain a transparent surface. |
| Quota window | Card owns grid display, padding, lower rule and hover background, including narrow-screen padding. The sheet keeps columns, labels, the selection marker and the single keyboard button's full-row pointer target. |
| Prospect | Card owns padding, accent edge, corner shape, panel background and sentence type. The sheet keeps margins, labelled numbers and text wrapping. |
| Consent | Card owns padding, amber edge, panel background, type and line height. The rail's smaller padding and label type are explicit contextual utilities. The sheet keeps action layout, paragraph spacing and margins. |
| Observer status | Alert preserves the existing status role and paragraph root. It inherits consent type, including the rail's smaller tier. |
| Blocked notifications | Badge owns the existing ink. The span's native title and notification owner remain unchanged. |

Risk and waiting evidence stays in its labelled cells: these are sourced sentences and elapsed
figures, rather than independent pills. Coverage rows, open-board subjects and the remaining-window
summary keep their list and grouping rules. Column captions, model sub-limit values, scope labels
and consent switch state are measurements or labels, rather than new badges. The budget-against-clock
bar stays native because its fill and its elapsed tick express two independent quantities; a
single progress value would discard that comparison. Existing progress elements and title tooltips
stay native. Consent remains in flow with its existing labelled region, focus keys and per-origin
storage; allowing model summaries still sends nothing until Summarize is pressed. No reader-state
owner, storage key, golden or frozen legacy source moves. No legacy rule leaves its layer.

`attention-chrome-reference.json` records 46 identities from `34045be7`, the branch tip before this
swap, using an archive built once under this worktree's ignored screenshots directory. The existing 87-view sweep
is supplemented with Attention, quota windows and observer consent at 1280, 800 and 375 px, including
the blocked-notification state. Keys contain surface, viewport band, tone, rail context, hover state
and visible or hidden sizing, with no clocks, counts or absolute widths. The notification tag also
distinguishes the fleet header's layout with running counts from the project header's layout with
a More menu. The recorder refuses conflicting values within one identity. The gate compares ink, background, all four borders,
display, padding, radius, type and role on every adopted instance. Row width is a fraction of parent
content width with a 0.015 tolerance; the notification tag's width is compared with its rendered
text plus chrome with a 15 percent tolerance for font metrics. Non-finite ratios fail.

The development CSS sweep passes across 87 views, comparing 216 adopted instances and retaining
all earlier component gates. Six scratch-copy mutations fail this family's gate: queue padding
and width each produce 18 differences, band padding and Badge ink nine each, and assertive status
and quota-consent padding three each. The width mutation changes no chrome property. Ten helper
tests reject non-finite ratios, collapsed widths, changed ink, missing identities and unwanted
live roles while allowing the text-metric tolerance. Replacing a quota percentage with `safe`
fails both the existing browser differential and the mounted Capacity differential; restoring
the source passes the mounted comparison. No broader normalization or golden change is needed.
The whole Vitest suite passes 1,491 tests in 132 files with two workers; build tests pass 23.
Development browser proofs pass Attention (16 steps including captures), Capacity (17), Sessions
(18), Intent (20), Drift (30), Project (19), Console (29), Terminal (19), Timeline filtering (13),
shell (29), Controls (22) and Popover (10). No recorded fixture changes.

Hand-written CSS falls from 137,209 to 136,243 bytes, a reduction of 966 bytes, with the counted
paths unchanged. Measured on 2026-10-11 in three fresh fluidity runs: the page is 1,621,296 bytes, 1,640 more than the
Project and Console layer; first-render medians are 146, 94.3 and 126.4 ms and poll-to-paint medians are 44.5, 45.8 and 62.5 ms;
every budget passes. This
layer's local development checks do not certify native Windows or Linux, screen readers, Firefox or WebKit.

## Stylesheet cleanup

The cleanup starts at `b86823fc`, with every component family present and 136,243 counted
bytes. Coverage was collected before deleting any rule, over the existing CSS, controls,
Sessions, Intent, Drift, Project, Console, Attention, Capacity, Terminal, shell and storage
proofs in both development and production modes. Controls also reaches popovers; Terminal
also reaches timeline filtering. That is 28 proof/mode pairs, 425 pages and 12,117 stylesheet
observations, including the 87-view CSS sweep, narrow layouts and reduced motion.

`frontend/e2e/support/css-coverage-hook.mjs` starts Playwright CSS coverage on each page.
Vite injects anonymous styles that Playwright drops from its result, so a second CDP rule
usage reader retains those styles without changing them. It drains usage before navigation
and after proof reads, then unions the counts. A used layer container cannot certify its
children: a count must intersect a declaration inside the individual style rule. Selector,
conditional context and declaration values identify retained rules. Hover, focus, active,
disabled and pseudo-element rules are retained conservatively when their base selector
matches. No class grep substitutes for this measurement.

The method has five limits. The rule-boundary check discards Playwright ranges Chromium
coalesces across adjacent used rules, so CDP rule-usage counts carry the certification
alone. A comma-separated selector list is certified by its first matching selector, so a
dead selector appended to a used rule is not detected. `coverageKey` omits the file, so a
dead rule duplicating a covered rule's selector and declarations in another file is not
detected. Two rules with the same file, context and selector share one exception identity.
`@font-face` blocks are not walked; the font checks protect those rows instead.

The deletion groups were verified separately against the CSS proof and all seven chrome
tables. Group one removes 66 retired control, layout, memo and native-popover rules for
7,514 bytes. Group two removes 13 obsolete Drift, Intent and subject rules for 1,510 bytes.
Group three removes the alias block, two duplicate keyframe steps and a redundant Raise
weight rule; folding the tokens and shortening their consumers lowers the counted total
by another 2,584 bytes. The working dot still uses the animation in `sessions.css`.

The 42 page properties now live in `@theme static` in `tailwind.css`, with their original
names and values. Controls and Popover read them directly; all 18 `--ctl-*` aliases are gone.
Native dark colour scheme stays in the legacy root rule. Font rows and the xterm host are
unchanged. The ratchet remains 13 sheets under its existing counting rule, which excludes
the directive and theme entry; the token movement is therefore part of the counted saving,
not a claim that those properties disappeared. It records 124,635 bytes, 11,608 fewer than
this layer started with and 36,829 fewer than the milestone start of 161,464.

`frontend/css-coverage.json` holds the measured union and exact exceptions with their
reasons. Optional published evidence, transient settling, browser-specific progress and
individual animation steps remain when the proof fixtures do not exercise them. The
coverage tests check the current sheets, require every baseline proof/mode pair, reject
stale, covered or unexplained exception identities and fail an added dead-rule mutation.
`pnpm test:css:coverage` runs that inventory directly. To collect a new run, set
`COMPASS_CSS_COVERAGE` to a directory under this worktree and preload the hook with
`NODE_OPTIONS=--import=<absolute hook path>`. Run the proofs sequentially in each bundle
mode, then use `node frontend/build/css-coverage.mjs collect <directory>` to produce the
local union under `docs/screenshots/css-cleanup/` before reviewing it for the tracked record.

`css.test.ts` now compiles the actual Vite entry in memory instead of opening a list of
source sheets. It checks the emitted stylesheet for the five type steps, root body type,
dark-only scheme, local assets and resolved custom-property chains. Both `font-size` and
the size component of `font` shorthands must use the scale. Deliberate mutations
remove type, body, absence ink, scheme and variable declarations or add off-scale type,
external assets, imports, a light-scheme query and a variable cycle. The browser contract
continues to measure links, controls, rings and every rendered ink. Its exact exception
sets and all locating hooks stay unchanged; mutation needles use direct tokens.

The final CSS sweep passes across 87 views and 9,233 text elements, comparing 3,090
component instances and 918 disclosure widths with the existing reference tables. Before
and after fixture captures retain the unreadable-source sentences, narrow wrapping and
amber stale-reading warning. The seven chrome gates and exact contract exception sets
are unchanged.

All 16 development proof commands pass, including preview, parser, installed-plugin,
controls, Sessions, Intent, Drift, Project, Console, Attention, Capacity, Terminal, shell,
storage, development supervisor and CSS. The whole Vitest suite passes 1,483 tests; the
build and coverage tests pass 29, and supervisor unit tests pass 17. Twelve compiled
mutations and six browser mutations fail at their intended guarantees, covering type,
body type, dark scheme, variables, absence ink, control colour, target floors and focus.
The current-shell dead-rule mutation also fails the coverage inventory.

Measured on 2026-10-11 in three fresh fluidity runs: the page is 1,608,412 bytes, 12,884 fewer than the
Attention and Capacity layer; first-render medians are 136.8, 94.2 and 124.3 ms and poll-to-paint medians are 43.7, 46 and 60.1 ms;
every budget passes. Production
coverage is the pre-deletion baseline; native Windows and Linux are checked by the pull request.

## Component stories

Storybook is a development dependency and is never imported by the shipped entry. Its configuration
lives under `frontend/.storybook` and its asserted examples under `frontend/stories`, outside the
Tailwind source scan. No docs, MDX, onboarding or hosted service addon is installed. The static output
is ignored and kept outside `frontend/src`. The component explorer reuses the page's styles, Tailwind
plugin, dark palette and fifteen embedded font faces.

On 2026-10-11 the npm registry dated Storybook 10.6.0 to September 2 and 10.6.1 to September 29.
The two-week delay therefore selects 10.6.0 for `storybook`, `@storybook/react-vite` and
`@storybook/addon-vitest`; no release-age exclusion was added. The eligible addon supports Vitest 4,
so Vitest and its Playwright provider are pinned to 4.1.11 (August 18) with Playwright 1.63.0, the
existing browser lock. Strict peers and the script-denied frozen install remain in force.
The dates can be checked in the [registry publication record](https://registry.npmjs.org/storybook).

Play functions test the words, roles, native elements, keyboard actions, focus and dimensions a reader
observes. Every story runs with console and page errors and external requests treated as failures;
a separate static-manager check covers the explorer shell as well. These checks make component
changes reviewable in isolation. They do not replace the application browser proofs or measure live
board refreshes, backend routes, installed packaging or fluidity. `pnpm build:check` is the proof that
the built page matches its recorded source provenance. It hashes the complete package manifest
and lockfile, so dependency edits require a new integrity record even when HTML and licenses
remain identical. See [Component stories](../CONTRIBUTING.md#component-stories)
for contributor commands and the current prompt-select fixture boundary.

## Icons and tooltips

The activity list adopts Phosphor through `react-icons` 5.7.0 (MIT). Only
`frontend/src/ui/icons.tsx` imports the icon package. One family keeps stroke, corners and optical
weight consistent across result marks and run controls. Phosphor's weights keep the hollow versus
marked circle in one hand, and its status coverage includes the clock-counter-clockwise, warning,
checks and caret shapes. These distinctions and MIT licensing made it the choice over Lucide,
shadcn's default, and the other families in React Icons. The package declares `sideEffects: false`;
the build retains only imported glyphs and their shared runtime. The final measured build delta
is recorded below, rather than inferred from the package's installed size. The info mark (`PiInfo`)
joined it on 2026-10-14 for the short line a press leaves under its button.

That line is a Popover, not a Tooltip, even though it reads like one. A tooltip does not open on a
touch screen, and what it holds is the outcome of a press (what was not settled, and that no analysis
started), so it opens on hover and on a press (Enter or Space from the keyboard). The whole sentence is also in the page,
visually hidden, as the button's description, and the polite region still announces it, so the popup
is never the only copy.

The existing hand SVG `DisclosureChevron` stays for the other disclosures, and native title
tooltips elsewhere stay. The fold alone passes a Phosphor caret to the existing Collapsible trigger.
The tooltip is the vendored shadcn Base UI Tooltip, with local `cn`, the page's popup surface,
border and shadow instead of an inverted pill, no arrow or registry animation classes, bounded
width, the existing motion tokens and an explicit tooltip role, which the pinned Base UI popup
does not supply. The existing copied-source shadcn MIT notice in the bundle's license file also
covers Tooltip.

One TooltipProvider serves the activity list. Non-focusable spans open on hover without adding
Tab stops. Short result words and icon shapes remain visible; full words are accessible names,
and the Marks legend states all five meanings for touch. A tooltip therefore never carries the
only copy, preserving the earlier ruling about hover text on touch. The unknown circle uses the
same muted caption ink as the other marks, with no green or filled success state. The story checks
the dark theme ink; the palette's `--ink2` (#cdc7b4) against `--panel` (#24231b) has a 9.3:1
contrast ratio. The fold trigger retains the 44px control floor. Mounted members preserve row
hooks while closed; failed and cited evidence never requires expansion.

Measured with pinned Node 26.10.0 and `pnpm build` on this worktree: before the activity change,
the React core was 1,674,151 bytes with 13 bundled package licenses. Afterward it is 1,707,435
bytes with 14 package licenses, an increase of 33,284 bytes for the icons, Tooltip, activity
components and their utilities together. The notices file adds the full `react-icons@5.7.0`
license, including its icon-family attribution list and Phosphor MIT reference; the existing
shadcn copied-source notice is unchanged. These are byte measurements, not a fluidity qualification.

## Checkbox and Radio Group layer

Checkbox and Radio Group are the base-nova items from the shadcn 4.21.4 registry
(`https://ui.shadcn.com/r/styles/base-nova/checkbox.json` and `radio-group.json`), hand-ported onto
the pinned `@base-ui/react` 1.8.0, which already ships `checkbox`, `radio` and `radio-group`. No npm
package is added and the lockfile is unchanged. Each file's header names the CLI version, the
registry source and the SHA-256 of the item's `content` as fetched, which is the record rule 3 asks
of a CLI copy.

The deviations are the ones every layer makes: the local `cn`, the page's own check glyph from
`ui/icons.tsx` in place of the registry's icon import, `rounded-control` and `rounded-pill` for the
page's radius tokens, the shared two-pixel outline focus ring, and no `dark:` or field-group
variants. The box and the dot stay 16px. The 44px target is the full-width option label around each
one, so the whole row takes the press, and an `after:` inset widens the control's own hit area. The
existing shadcn copied-source notice in `react-licenses.txt` covers both files, so the notices file
is unchanged. Storybook's explicit optimizer list adds `@base-ui/react/checkbox`, `radio` and
`radio-group`. `checkbox.stories.tsx` asserts that Space and a press on the label toggle the box,
that the label row is at least 44px tall and that a disabled box ignores both;
`radio-group.stories.tsx` asserts that the arrow keys move the one checked item and that the group
has one tab stop.

Three existing ui files changed with it. Button gains a `filter-chip` variant, Tailwind only, for a
removable filter: one press removes it, so the remove glyph sits inside the button's name.
`ui/icons.tsx` adds `search` (`PiMagnifyingGlass`) and `check` (`PiCheck`) and reuses `remove`.
`PopoverContent` passes Base UI's `collisionAvoidance` through to its positioner.

### Find sessions controls

The Sessions toolbar is the first user of both components. The
[Sessions search record](design-sessions-search.md#the-toolbar) owns its behaviour; this section
owns which component draws each part.

| Part | Component |
|---|---|
| Search field and Find a project | Input, through `DraftInput`: uncontrolled, with field memory, as the form-controls layer requires of every typed field |
| Six filter buttons and their popovers | The popover variant of `Disclosure`, so open state stays in the keyed store and Escape and blur follow the Popover layer |
| Filter options | Checkbox for Project, Harness, State, Drift and Goal and the no-stamp checkbox; Radio Group for Date's Filter by and When |
| A count on a filter button | Badge |
| Presets | Button `variant="native"` with `aria-pressed` in a named group, the activity filter's idiom, instead of Toggle Group |
| Chips | Button `variant="filter-chip"` |
| Show all stored sessions, and back | `buttonVariants({ variant: 'native' })` on a plain `<a>`, so the link keeps its role |
| The hidden-waiting guard | Alert, static (`announce={false}`), on the amber token |
| Dividers inside popovers | Separator |

The filter popovers keep the Popover layer's contract: non-modal, initial and final focus left alone,
and Escape through `popoverEscape.ts`, which closes all popovers and returns focus to the trigger. The
popover variant of `Disclosure` gains three props for them. `triggerClassName` adds the border, since
the trigger's own class is only a minimum size and a focus outline and the chevron stays. `vertical`
turns off side flipping (`side: 'none'`, `align: 'shift'`, `fallbackAxisSide: 'none'`), so a list
opens below its button and scrolls inside the available height; in a short window the tall Date list
had flipped beside its button, over the search field. `holdPaint` marks the trigger with
`data-hold-paint`, which holds the board's background paint while the popover is open, as an open
Select does ([An open option list](design-reader-state.md#an-open-option-list)).

Not added, with the reasons the Sessions search record gives: Kbd, Input Group, Toggle Group, Switch,
Calendar, Command, Combobox, DropdownMenu, Sheet, Drawer and Empty.

Rule 9 puts a layer that adds a typed-words control under full adversarial review, and the search
field is one, so this layer takes that tier rather than two lenses. The toolbar is Tailwind only:
`SessionsFilters.tsx` joins the sessions `@source` list in `tailwind.css`, and hand-written CSS is
unchanged at 121,030 bytes. Measured with `pnpm build` on this layer, the page grows from 2,174,695 to
2,237,347 bytes (62,652 bytes for both components, the toolbar and the filter rules together), with
14 bundled licenses before and after. These are byte measurements, not a fluidity qualification.
