---
name: visual-review-and-fix
description: Use before and after building a Compass change, to walk the board as its user, hold new work to what that user expects, and keep the tests behavioural.
---

# visual-review-and-fix

Open the dashboard, use it the way its reader does, and find what the suite cannot see.

This skill rests on one measured claim. **Compass's defect class is the confident wrong answer in
an absence.** A9 was cancelled over a light that read "safe" exactly when nothing could be seen. A5
produced five false greens inside a binary verdict, none of them in the numbers. C2 published
"nothing succeeded" off state it had not finished reading. The framing header shipped claiming two
carve-outs where there were three. A cached quota reading was republished as current for as long as
the poll stayed off. None of those was found by a failing test, because a test asserts what the code
does with data it was handed, and this class is about what the surface says when the data is not
there.

So the review is not a look at the layout. It is a walk through the reader's day with the awkward
cases forced, and a check that every silence on the screen is a stated absence rather than an
implied all-clear.

Run it **twice**: once before development, to find what is already wrong and to write down what the
build will be held to, and once after, to catch what the change broke. The two modes are below.

## When it is owed, and how much

Rigor is a dial. `AGENTS.md` measured what happens when it is a constant: a 339-line additive change
with no callers got the same treatment as the one owning the built bundle.

| The change | Before | After |
|---|---|---|
| Renders anything a person reads: `frontend/src`, a published row field, a threshold that gates a claim | Full walk | Full walk |
| Changes what a collector publishes, without touching the page | The stages that render it | The same stages |
| A doc claim about what the board shows or says | The one surface it describes | The same surface |
| Makes a terminal or skill behaviour reachable: an action word, a terminal command, a hook a session fires | The stages it reports on | Those stages, and a real session (Mode 2, step 6) |
| Runtime only, nothing published changes | Skip, and say in the report that you skipped it | Skip, and say so |
| Prose with no claim about the board | Skip | Skip |

The two Skip rows are a real answer, not an escape. Say which mode you skipped and why, so the next
reader knows the walk was considered rather than forgotten.

## Prerequisites

- A browser automation capability. The walk is the point; there is no reading-only substitute for
  it, and the section on delegation below says why a subagent cannot do this part.
- The dashboard runnable from the tree under review: `python3 server.py --daemon --port <spare>`
  from `compass/skills/compass`.
- `docs/promise-map.md` open. It is canonical for what the product promises at each stage of the
  reader's day, and for where each promise stops.
- For a terminal or skill behaviour, a logged-in `claude` on PATH. `scripts/session_smoke.py`
  drives it; Mode 2, step 6 says when.

Never review on the port the operator is already using. Pick a spare one, and stop what you start.

## Mode 1: before development

### 1. Name the promise you are about to touch

Read the stage of the reader's day the issue belongs to in
[the promise map](../../../docs/promise-map.md), and write down three things: the promise sentence
verbatim, the shipped capability behind it, and the limit that keeps it honest. The issue's own
`journey:*` label says which stage.

If you cannot name the promise, the issue has no user-visible property to review and the calibration
table's "Runtime only" row applies.

### 2. Bring the surface up with real data

Start the dashboard from the tree, and read `/api/data` before you read the screen. Two reasons: the
payload is the ground truth the page renders from, so a disagreement between them is itself a
finding, and you need to know what the board *can* show before you judge what it does show.

The board must have something to show. A walk over an empty board tests nothing but the empty state,
which is step 4's job rather than step 3's.

### 3. Walk the stages the change touches

[`references/the-walk.md`](references/the-walk.md) carries the five stages of the reader's day, each
with its promise, the surface that renders it, the absences to force, and the stated limit to check
is disclosed. Walk the stages the issue touches, and the whole set only when the change reaches the
whole page.

Read the rendered text, never the source, and quote it in your report. Two issues filed off a
code-reading pass in this repository stated the user-visible claim wrongly: one asserted the page
called a project "busiest" when only a comment did, which made its acceptance criterion
unsatisfiable, and the other proposed a fix that would have shipped a regression. The screen is the
only authority on what the reader is told.

### 4. Attack the absences

This is the highest-yield part of the walk and the reason the skill exists, and the split is
measured: of the nine findings the two milestone verifications produced, **seven needed an
absence, a stale reading or a degraded state to reach at all.** Only two were ordinary
present-state mistakes. If you have time for one step, it is this one.

For every surface the issue touches, force the state where there is nothing to say and check the
screen says that rather than implying the opposite:

- No sessions, no gate, no quota answer, no reachable terminal.
- A harness present but unable to report the thing this surface is about.
- A capability the operator has switched off.
- A reading that arrived once and has since gone stale.
- A value the vendor publishes that this surface does not render.

The standard to hold new work to is the code's own. `frontend/src/capacity` prints "Recent pace not
measured: no second reading yet from this vendor" instead of a pace of zero, and marks an expired
reset "not projected" rather than projecting from it. `collectors/codex.py` returns nothing at all
for a snapshot older than the activity window, because "the band's empty state is more honest than a
number that old". Anything new that approximates where those withhold is a finding.

Then check the stated limit from step 1 is actually disclosed on the screen, not merely true in a
document. A capability that exists but cannot fire under the operator's own configuration is the
sharpest version of this: the coverage line counting a harness as reporting is accurate about the
mechanism and still lets that harness's silence read as an all-clear.

### 5. Write the criteria the build will be held to

Turn the walk into acceptance criteria the `burndown` skill can carry, each one a property a reader
can see, each with its own `Verified by:` clause naming the observation that would settle it. A
criterion that can only be checked by reading the source is not one this skill produced.

State the rendered text you expect, not the shape of the data. "The row says the dashboard restarted
and the page needs reloading" is reviewable; "the 403 branch sets state" is not.

### 6. Dispose of what you found

Everything Mode 1 finds **predates the change you are about to make**, so it is filed, never folded
into the branch you are about to open. `AGENTS.md` measured four such promotions at about an hour
each in extra implement-and-CI rounds. File it with the rendered text, the payload that produced it,
and the stage of the day it belongs to.

The exception is a finding that makes the issue's own plan wrong. That is not a defect to file, it is
a correction to the issue, and it belongs there before any code is written. Two issues in this
project had their plan overturned before a line was written, both by one cheap observation, and both
times the observation was worth more than the feature.

## Mode 2: after development, before the pull request opens

Run this in the worktree with the change applied and **before `gh pr create`**. `AGENTS.md` measured
the cost of the other order at roughly fifteen minutes of CI waiting per pull request, because a
review after the PR opens means green, blocked, fixed, green again.

### 1. Re-walk what you walked before

Same stages, same absences, same rendered text. You are looking for two things: the property the
issue promised, and anything that used to read correctly and now does not.

### 2. Compare against the merge base, not against your memory

For anything that looks wrong, run the same probe against the base before calling it a regression.
This is what separates "the change made it worse" from "this was always so", and the distinction
decides whether it is fixed here or filed. One finding in this repository was promoted deliberately
on exactly that basis: against the base a mid-flight render produced a *neutral* control, and with
the change it produced a *misleading* one, so the change had made that axis worse and the fix
belonged in the same branch.

### 3. Check the regression classes this repository has actually shipped

Not a generic checklist. Every one of these has happened here:

- **State a refresh throws away.** The React page redraws on every board refresh, and anything
  held only in a node is lost when that node remounts. Each lane that must survive has an owner in
  `docs/design-reader-state.md` (the controls provider, the disclosure store, the held drafts, the
  focus lane). A confirmation cue, keyboard focus, unsaved text and a disclosure's open state were
  each lost this way on the previous page, separately. Click a control, let a refresh land, and
  check the answer survives; a lane with no owner in that record has no restoration.
- **Two channels of the same page disagreeing.** A visual cue saying one thing while the live region
  says another. Check the screen-reader text against the colour, not just each alone.
- **A quantity replaced by a conclusion.** A column that should carry a number carrying a verdict
  instead, so the reader cannot make the comparison the design reserves for them.
- **A count or a provenance claim that is true of the wrong set.** A concurrency figure counted
  across all harnesses and attached to one vendor's historical average was observed claiming three
  agents on a row where two of the three had never touched that vendor.
- **A universal claim over a set nobody enumerated.** Count the members before writing "every" or
  "the two exceptions". This blocked a merge here over a third carve-out that existed and was unnamed.
- **A capability whose reach the operator's own configuration silently removes.** A harness that
  reports a gate through a hook cannot report one where the operator has approvals off, so the
  coverage line counts it as reporting, truthfully, while its silence reads as an all-clear.
- **Agreement between the number and the words around it.** A sentence picked its verb from a count
  in one place and hardcoded it in the next, so every count but one read wrongly.

### 4. Hold the tests to behaviour

Apply "Behavioural testing first" below to the tests the change added. If it shipped without a
behavioural test for the property a reader sees, that is a Mode 2 finding about the change
rather than a suggestion for later.

### 5. Dispose

- **Your change introduced it**: fix it here, before the PR opens.
- **It predates your change**: file it, with the base comparison that proves it predates.
- **You cannot tell**: say so, and file it as unsettled rather than guessing. A finding attributed to
  the wrong cause costs more than an unattributed one.

### 6. Walk a real session when the change reaches one

A browser shows the board. It does not show what a session sees when it types a skill action or
runs a terminal command, and that path has its own ways to fail: a permission prompt the
pre-approval did not cover, a key one surface publishes and another looks up, context a long
session no longer holds. Walk it at the first layer that makes the behaviour reachable, not only in
the final Verification walk:

```bash
python3 scripts/session_smoke.py --tree <worktree> sessions "sessions waiting"
```

It starts a board from the worktree on a spare port (4795 by default, never the operator's 4553),
creates a headless Claude Code session in a scratch project with a real first prompt (a Compass
command is never adopted as a goal), types each `/compass:compass <action>` into it, and prints the
permission denials, the tool commands and their results. The board, the session and its hooks share
a scratch Compass home, so the operator's board receives none of the session's events and no other
session's terminal client sees the spare board. The skill's commands ask the newest-started board,
and the default port's board is always a candidate, so before each action the helper checks that
its own board is still the newest and stops if it is not. It stops the board it started and kills
each command's process group on every exit it can catch. A process that left its group survives
that: check for leftovers as `AGENTS.md`, "Parallel Work" says.

Read the denials first: an action the skill pre-approves should run with none. Then read the tool
result as rendered text, the way step 3 reads the screen.

The helper refuses `drift again`, plain `drift` and any action it cannot show is free, unless
`--allow-spend` is passed, because a fresh session has no stored reading and plain `drift` then
presses one. Ask before passing that flag. The scratch home starts with model calls not allowed, so a
press there stops at Compass's permission answer rather than spending.

Measured on 2026-11-06: the two most expensive defects of a milestone passed about 9,000 tests and
19 review agents, because every fixture agreed with itself. One was the full session UUID looked up
against the board's 8-character key; the other a citation lost outside the context window. Both
surfaced only in the final walk, which then cost a fix pull request, a CI cycle and about 40
minutes, and the recipe that found them took minutes once known. Fixtures for a parity or shape
test come from a captured real payload for the same reason.

## Behavioural testing first

The repository already requires a failing test before the fix. This skill is about what that test is
allowed to assert.

A behavioural test here:

- **Drives the page as the reader meets it**: the built bundle in a real browser (`frontend/e2e`),
  or the mounted component in its React test, not a function in isolation. The page is one
  canonical artifact and the reader meets it whole.
- **Is named as a sentence about a person.** `test_a_stale_capability_names_the_restart_and_the_remedy`
  reads as a claim someone can check. `test_403_branch` does not. This is the house style rather than
  a new ask: 82% of the suite's 2,180 test names already carry an article or a pronoun, and six of
  them are terse enough to be four tokens or fewer. Match what is there.
- **Asserts the rendered text**, not the shape of the data behind it.
- **Covers the absence**, because that is where this product fails.

Then prove it. **Break the source the test defends and watch it go red.** A mutation that comes back
green does not mean the code is safe, it means the test is wrong: that happened five times across
this project's recent work and every one was a real test defect, including two where a fixture
constructed both sides of the comparison so they agreed no matter what the code did. In one case a
single deleted attribute silently un-fixed an entire lane of the interface with the whole suite
green.

Restore by file copy, never by `git checkout --`. Restoring with git discarded a builder's own
uncommitted work here and invalidated the loop it was in the middle of.

## Delegating to Codex and Antigravity

Detect what is installed and spread the reading:

```bash
command -v codex && codex --version
command -v agy   && agy --version
```

Then hand each one a self-contained, read-only job, in the background, writing to a file:

```bash
codex exec --sandbox read-only "$(cat prompt-a.txt)" > out-a.txt 2>err-a.txt &
agy --sandbox --print-timeout 25m -p="$(cat prompt-b.txt)" > out-b.txt 2>err-b.txt &
```

Four things measured about this:

- **`agy`'s `-p` consumes the very next token, whatever it is.** So the prompt must come immediately
  after it, or be attached with `-p="…"`. Writing `agy -p --sandbox … "prompt"` makes `-p` swallow
  `--sandbox` as the prompt and leaves yours as an ignored argument. It says so rather than failing
  silently, which is the only reason it was caught. `-p "prompt"` on its own is fine; the trap is a
  flag sitting between `-p` and the text.
- **Give both a read-only sandbox.** They must not edit the tree you are reviewing. An edit landing
  mid-review turns correct findings into false refutations.
- **They appear on the board as sessions.** Your own delegates become rows in the thing you are
  reviewing, and in one run they produced four `AT RISK` identity-collision entries because several
  shared a display label. Write down what you spawned before you read the board, and discount those
  rows in the report.
- **`codex` may print an unrelated MCP transport error** to stderr on start. It is noise from the
  operator's own configuration, not a failure of the job.

**What to delegate:** falsifying a claim against the code, mining the repository for stated limits
and counts, replaying real stores or transcripts, and independently recomputing a figure.

**What never to delegate:** the walk. Only the orchestrator has the browser. A subagent asked to
"verify in the browser" will reason from the source instead and sound convincing doing it. One
delegated pass in this project returned a confident FALSIFIED on a rendering claim; it was right
about the code and wrong about what the reader is told, and the thing that was actually false turned
out to be a sentence in the project's own records.

Treat every delegated verdict as a candidate. Default to refuted, ask for `file:line` evidence, and
reproduce anything you intend to act on.

## Browser harness traps

Each of these produced a wrong conclusion here before it was understood:

- **Navigating to the same URL with an unchanged fragment does not reload the document.** A "fresh"
  page still holds the old bundle and the old capability, and the fix you just made looks broken.
  Use an explicit reload.
- **A reference held across a route change or remount can be stale.** A live region created lazily
  on first use did not exist when the reference was taken, so the announcement read as missing when
  it had fired. Re-query after the change, or watch with a `MutationObserver`.
- **Restarting the server invalidates the page's capability.** Every raise then answers 403 and the
  data lane keeps working perfectly, so the board looks healthy and one control is permanently dead.
  If you restart, reload the page. This was diagnosed as a broken handshake before it was understood
  as a stale tab, and the underlying defect, that the page said nothing useful about it, was real.
- **State with a lifetime expires between tool calls.** A cue held for thirty seconds reads as absent
  if the click and the assertion are in separate calls. Do both in one script.
- **Open a disclosure with a real click, not script.** The disclosure store records what the reader
  does, so a scripted opening can read as shut in the next screenshot. Refresh once and check it
  stayed open.
- **A programmatic click cannot always write the clipboard**, because the document is not focused. A
  `failed` copy state there is the harness, not the product.
- **Consent is per origin.** A different port is a different origin, so a consent-gated feature has
  to be answered again on the review port.
- **`resize_window` does not shrink, and it succeeds while not shrinking.** Measured over two agents
  and four attempts: 980 was requested three times and 1000 once, and `innerWidth` never moved below
  its starting value. Only upward resizes took effect, and nothing reported a failure. A narrow
  viewport measured this way is silently the viewport you started at.
- **The board cannot be framed, so the iframe route is not available.** It sends
  `Content-Security-Policy: frame-ancestors 'none'`, which is correct and was not worked around.
  Worth knowing as a property rather than only as an obstacle.
- **The route that does work is CDP `Emulation.setDeviceMetricsOverride`.** Launch Chrome with
  `--headless=new --remote-debugging-port=<port>`, attach to the page target from `/json/list`, and
  set the metrics before navigating. Two things that cost a cycle each: the override is **per CDP
  connection**, so setting it in one script and measuring in another gives you the default viewport
  back; and it must be set before `Page.navigate` or the first layout happens at the old width.
  Verified 2026-09-21 at `innerWidth: 980`, the width `resize_window` could not reach.

## What this review cannot see

A walk that claims to catch everything is the confident wrong answer this skill exists to prevent.
Four classes need something else, and each one has a shipped instance here:

- **Security boundaries.** A missing framing header, a response that composes its own reply outside
  the policy, the accepted local-process exposure: the rendered board looks identical before and
  after. That defect was measured over a real socket, and only a socket could have measured it.
- **Anything invisible to a screenshot.** A focus ring turned off, an accessible label that leaks a
  target it must not name, a deleted live-region announcement. These are reachable from a browser but
  only as explicit checks: read `document.activeElement`, watch the live region with a
  `MutationObserver`, read the accessibility tree. Looking at the page will not do it, and tests
  stayed green through all three of those here.
- **Provenance and hidden-source errors.** A browser cannot know that five earlier successes fell
  outside a bounded transcript scan, that a capture omitted the session ids its verdict rested on, or
  that a percentage is on the wrong vendor's scale. Q-2 in
  [`docs/design-usage-quota.md`](../../../docs/design-usage-quota.md) says outright that no unit
  fixture can settle that last one, because a self-authored fixture agrees with either scale. Those
  need transcript replay, a real capture, or a live install.
- **Whether an external action actually happened.** The board saying it happened is not evidence that
  it did. The raise control says SENT rather than RAISED precisely because a zero exit status did not
  prove a window came forward. Validating that class means watching the terminal, not the dashboard.

When a finding falls in one of these, say which, and name the instrument that would settle it. Do not
stretch the walk to cover it.

## Hard rules

Never review on the operator's own dashboard port, and stop every server and session you start.

Never edit the tree while a verification is running, yours or a delegate's.

Never promote a Mode 1 finding into the branch. File it.

Never assert a defect from source alone when the claim is about what the reader sees. Quote the
screen.

Say what you did not check. A walk that skipped a stage, an absence you could not force, a harness
you had no install for: name it. An unstated gap reads as a clean result.

## Why this skill exists

Measured on this repository, over two days of work on two milestones that were both marked complete
and whose suite was fully green throughout.

A browser walk over those two milestones found **six defects**, four of them things a reader would
have hit: a control that failed permanently after a restart while the board around it looked
healthy, keyboard focus discarded on every refresh, a false claim about how many agents a
measurement covered, and a column that withheld the number the reader was supposed to compare. Three
further findings came from the same pass and were filed rather than fixed. The suite stood at 2,164
tests and passed on every commit involved, before and after; the structural reason is the same in
every case, which is that none of them is reachable without a real server and a real browser.

The same pass corrected four records that had gone false, including two sentences in the
project's own milestone descriptions and one canonical design document whose rule the shipped code
had been breaking since the feature landed.

It also refuted three candidate findings before they were filed, two of which were mistakes in the
review itself rather than in the product. That ratio is why this skill defaults to refuted and asks
for the rendered text.
