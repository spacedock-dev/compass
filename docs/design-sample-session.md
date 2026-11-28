# The sample session

A new reader opens Compass with nothing on the board, or with sessions that have never drifted. The
Intent and drift feature is the part of the product that needs the most explaining, and it is hardest
to explain before there is a session that drifted. The sample session is a finished example they can
open without running an agent: a real, anonymized Claude Code session, a goal saved against it, a stored summary of what the session did, a stored reading that finds
drift, and the correction Compass composes to steer it back. It is view only, and seven numbered (i)
marks say what each part of the page is for.

[sample-session/README.md](../sample-session/README.md) owns what the data is and how it was made.
This record owns how the page treats it, and what was tried and rejected.

## What was chosen

The sample is the kind of session Compass is for: a long run toward a milestone, with the goal set
once. It is about ninety minutes of an agent coordinating other agents to burn down a milestone, cut
from a fourteen-hour session. The person's goal is to close every issue in the milestone. The agent,
short of that, suggests moving an unfinished issue out of the milestone so it can close, and the
person steers it back: the issue stays and is to be finished. That drift can be said in a sentence
without knowing the project, which is why this session was picked over the other long ones measured
for the summary work ([the README](../sample-session/README.md#why-this-session-and-why-this-stretch)
says more).

On the page the stored summary has seven phases in two parts, three of them marked as holding the
evidence for the departure from the goal; the reading finds one departure, on the goal, and one row
about what the agent claimed. Is it on track? shows Slightly off course. The quotes link opens
Evidence with the reading's explanation and the cited entries. Steer back opens an editable
two-sentence message based on the saved goal.

### The intent is a goal alone (owner, 2026-10-23)

The first capture saved the person's own words from the record: the goal "Burn down fully the
milestone" and an expected outcome that said the same thing. The Drift card then showed two
departures resting on the same evidence, three phases carried both pills, and the goal was an
activity with stray closing quotes where it quoted the milestone's name. A new reader could not tell
what the second box was for.

The sample now saves one goal written as an end state, "Every issue in the milestone is closed" (with
the milestone's name as the record spells it), and no expected outcome. The reading was made again
against it. It found the departure from the goal and a separate row about what the agent claimed,
which is not a departure from the intent, so the card shows departures from the goal alone. The
summary was made again in the same run, in the same home, so both come from one transcript. The
2026-10-20 summary was tried first and dropped: copied into the new home, the server read it as made
from a replaced record, and the page then told every reader to summarize again.

A goal-only reading used to say in its cutoff that no expected outcome lines were saved. Noting the
absence of an optional field tells a reader nothing, so the product sentence is now "Read against your
goal." for every session (owner, 2026-10-23), and the sample shows it as it comes. A reading stored
before that change keeps the longer sentence. A test fails if the intent carries a line or any sentence
the sample draws from the reading names an expected outcome. The real Intent card's own optional
Expected outcome field is the product's and stays.

The banner and the tour say, in order, how a reader reaches the same page with their own session:
open a session from Sessions, set its goal (type it, use one of their prompts, press Find goal, or let
Compass pick up a goal set with /goal), press Analyze drift, then read where the session departed and
press Steer back for a correction to paste. Neither mentions an expected outcome.

### Rejected: the first sample

The first sample, made on 2026-10-14, was one turn: a request to resolve a pull request's merge
conflicts, and the agent starting to change code when only history was meant to change. Feedback on
2026-10-15 said it "looks like an issue" when the product is meant for work at the level of a
milestone, and the redesigned page leads with a summary of what the session did, which a one-turn
session barely needs. It also needed one edit to what the session did (two test runs piped through
`tail` recorded as failures), where this one needs none. It was replaced rather than kept beside the
new one, because two samples would need a chooser and two tours, and its transcript, its shaping
file and the script that applied it were removed with it.

## Where it lives

The route is `#n=session:acme%2Fdashboard:claude:sample`, an ordinary session route with a reserved
project and session id. `sample` is not a shape any real session id takes, so it cannot collide with
one. `RoutedView` in `frontend/src/shell/views.tsx` wraps the real `SessionView` for that route and
for no other, so the page a reader sees is the page every session gets, with the same components, the
same wording and the same layout. A reader opens it from See an example above the Sessions list or on Help. Not now hides the Sessions invitation in this browser. The Help entry remains available.
The new sample kept the route, the project label and the id, so a link to the first sample opens this
one.

## A second shell, not rows in the board

The page already holds one shell: a runtime that polls `/api/data`, a store, a display gate and the
controls. The sample runs a second one, created by `createSampleShell`, over an in-memory server and
in-memory storage. It shares only the router and the live-region announcer with the page around it.

Rejected, with the reason:

- Putting a sample row into the real board's store. The board's next poll replaces it, and while it
  is there it would be counted in Sessions, Projects and Attention, so the sample would change the
  numbers a real reader relies on.
- Serving the sample from the server as a fake session. It would need a server change for a feature
  that lives in the page, and it would put a session into the server's own session list. The sample
  needs no server at all.
- A framed copy of the page. The dashboard sends `frame-ancestors 'none'`, deliberately, and a second
  bundle would double the page.
- A screenshot or recording. It cannot be hovered, and it goes stale the first time the page changes.
  Because the sample draws the live components, it never does.

## What is in the fixture

`frontend/src/sample/session.fixture.json` holds the answers the page asks for, captured from a real
Compass server run against an isolated home that held only the sample session: the board row with
the board's reading and summary grants, the focused project context (which carries the outline and
the stored summary, `sources.outline` and `sources.summary`, as the server publishes them), the same
context with the prompts, the session record and the composed correction. The record is every page
of it, back to the start: the newest page as `record`, and each older page under `older`, keyed
`older-1`, `older-2` and so on. This session's record is two pages, so it has `older-1`.
`scripts/build_sample_fixture.py` takes the capture, so nothing in it was typed by hand.

Rewrites make the capture a stable sample and not a snapshot of one afternoon:

- The session id becomes `sample`.
- Every time within six hours of the capture moves to just after the session's last record, so
  "1m ago" reads the same on any day. The sample's clock (`sampleClock` in `sampleShell.ts`) starts
  at that moment and runs on from it. The summary is placed 30 seconds after the last record, as it
  is made when the finished session is opened, the reading 45 seconds after it and the settling of
  the later directions 60 seconds after it. The reading and the settle are placed rather than
  shifted, because a reading may be kept from an earlier capture than the summary's.
- The reading's sentence counting how old its entries are ("The oldest is from about 3933h ago") is
  counted from the reading's place on that timeline instead, "about 1h ago".
- The board's permissions read as a store with no stored off: readings and summaries on, nothing
  refused and no notice records kept, with no notice due because both kinds of call were made, and
  with one reading and the stored summary's three calls counted.
- The correction keeps each time as its moment, `{{clock:<seconds>}}`, and the sample's server draws
  it on the reader's clock. The composer writes the reader's local time (owner, 2026-10-20), and a
  correction drawn in the capture's zone, UTC, would name 11:23 beside a cited message the page
  draws at 19:23 for a reader eight hours east. Rejected: storing it in UTC with a note, because the
  reader copies the text into a session, where the note does not travel.

The board's digest of the store the reading was saved in, and the summary prompt's digest in the
summary's model stamp, are cut to 32 characters, so nothing in the file is a credential-length value
and the leak sweep stays strict. The server's record cursors are replaced by `older-<n>` for the same
reason, and because each one binds the capture machine's file (its device, inode, size and time) and
a key that died with that server. The summary's job metadata is absent, because the capture was taken
from a server restarted after the job, and a restart keeps the saved summary but not the finished
job's metadata.

### Every page, not the first one

A reading or a summary may cite any entry in the session, and a long session's board context holds
only its tail, so the page finds an older entry by reading older record pages until it appears. The
sample's server used to answer every older-page request with nothing and `reached_start: true`: with a
one-page record that was true, but with a longer one it would say a cited entry does not exist when its
page was simply never captured. The capture reads every page instead, and refuses a record longer than
the page's own cap on pages read for a citation (20 pages of 50), since a citation past it could never
be shown. The sample's server answers an older page by its cursor, and answers a cursor it never issued
as the real server answers one it cannot read (`state: "stale"`), so the page starts again from the
newest entries rather than concluding anything.

The first sample was one page, so its stories split its record into three made-up pages to cite an
entry on each. This sample's record is two real pages, so its stories press real citations: the
person's first message, #1, on the older page; the person asking for the walk, partway through; and
the agent's last reply, #81. Each opens in Full activity.

Rejected: capturing one flat list of entries and paging it in the sample's server. It would need the
server's page boundaries reproduced in the page, which are byte-bounded scans rather than a count, and
the captured pages already are those boundaries.

## How big it may be

On 2026-11-24, before the rebase, the Sessions progress pill, filters and Help measured
2,487,863 packaged bytes.

The fixture ships inside `react.html`, and every install and every page load carries it, so its size is
bounded before a sample is built, not measured after. The initial bounds were set on 2026-10-19, before this
sample was captured:

- The page was limited to 1,884,747 bytes, the page as built that day, plus 400 KiB: 2,294,347 bytes.
- The fixture may be at most 250,000 bytes of compact JSON. The page carries its script
  base64-encoded, so a fixture byte costs about four thirds of a page byte, and the step from the first
  sample's 75,130 bytes to the bound is at most about 233 KB of page, which leaves the rest of the
  400 KiB to the code that ships beside it.

The Help and Projects layer measured 2,423,571 bytes for the packaged page on 2026-11-23,
up 8,312 bytes from its starting page of 2,415,259 bytes. The page bound rises once from
2,418,919 to the measured 2,423,571 bytes. The fixture bound stays at 250,000 bytes.

The same day's review fixes added 2,608 bytes for measured project states and end outcomes,
one project notes editor, the shared Timeline evidence control and the narrow Projects layout.
The new measured page bound is 2,426,179 bytes. The example fixture is unchanged.

With the session story and first-layer guard underneath, Help and Projects package to
2,430,667 bytes on Node 26.10.0 and pnpm 12.17.0. That is 10,964 bytes above the session
story's measured page. The bound follows the measured combined page, and the fixture bound
stays at 250,000 bytes.

On 2026-11-23, the Settings layer packaged at 2,462,879 bytes, up 39,308 bytes (1.62%)
from the 2,423,571-byte Help and Projects page. The new stepped slider and Settings cards
ship in the page. The page bound rises once to the measured 2,462,879 bytes. The fixture
bound stays at 250,000 bytes.

The Settings review fixes packaged at 2,466,095 bytes, up 3,216 bytes. The increase
covers save confirmation, browser availability and the fallback for unreadable preferences.
The page bound rises to the measured size. The fixture bound stays at 250,000 bytes.

With the landed Help, Projects and Session changes underneath, Settings packages to
2,473,199 bytes on Node 26.10.0 and pnpm 12.17.0. The page bound follows the measured build,
42,532 bytes above the previous page on main. The fixture bound stays at 250,000 bytes.

On 2026-11-23, the Needs you, Goal history and phone layout layer packaged at 2,466,879
bytes, an increase of 4,000 bytes (0.16%) from the 2,462,879-byte Settings page.
The review fixes restore independent quota and goal evidence, report failed saves, and make
dismissal writes sequential. The corrected build measures 2,468,711 bytes, 1,832 bytes
(0.07%) above the first package. The page bound is the measured 2,468,711 bytes. The fixture
bound stays at 250,000 bytes.

After restacking Needs you, Goal history and the phone layout on the landed Settings page,
the packaged page measures 2,479,799 bytes on Node 26.10.0 and pnpm 12.17.0. The 6,600-byte
increase over the 2,473,199-byte Settings page includes the rebuilt navigation and the phone
layout for the slider labels. The page bound follows the measured build. The fixture bound
stays at 250,000 bytes.

DRC-5510 packages the shared AI use pause notice at 2,479,707 bytes on Node 26.10.0
and pnpm 12.17.0, 92 bytes below the preceding Needs you build. The page bound follows
that measurement. The fixture bound stays at 250,000 bytes.

On 2026-11-24, the dependency bump to React 19.3.1, Vite 8.3.7, Tailwind CSS 4.3.5 and
pnpm 12.19.0 packages the page at 2,478,431 bytes on Node 26.12.1, 1,276 bytes below the
2,479,707-byte page before it. The page bound follows that measurement. The fixture bound
stays at 250,000 bytes.

Later on 2026-11-24, letting an opened panel's text span the panel packages the page at
2,478,519 bytes on Node 26.12.1 and pnpm 12.19.0, 88 bytes above the dependency bump's page. The
page bound follows that measurement. The fixture bound stays at 250,000 bytes.

Later on 2026-11-24, laying out Sessions rows as the redesign canvas draws them packages the page
at 2,475,615 bytes on Node 26.12.1 and pnpm 12.19.0, 2,904 bytes below the panel-width page,
because the retired column rules come out of the stylesheet. The page bound follows that
measurement. The fixture bound stays at 250,000 bytes.

Later on 2026-11-24, putting the Sessions list in one card and saying a row's end and git facts once
packages the page at 2,477,135 bytes on Node 26.12.1 and pnpm 12.19.0, 1,520 bytes above the canvas
row's page. The page bound follows that measurement. The fixture bound stays at 250,000 bytes.

Later on 2026-11-24, saying "No goal yet" on a Sessions row with no goal, in place of its Add a goal
link, packages the page at 2,477,391 bytes on Node 26.12.1 and pnpm 12.19.0, 256 bytes above the list
card's page. The page bound follows that measurement. The fixture bound stays at 250,000 bytes.

Later on 2026-11-24, giving every Sessions row a status tile in a fixed column, with the new State not
known tile, drawing the list's empty lines and in-row absences as plain quiet text, and matching the
search field to the Filters button packages the page at 2,479,987 bytes on Node 26.12.1 and pnpm
12.19.0, 2,596 bytes above the No goal yet page. The page bound follows that measurement. The fixture
bound stays at 250,000 bytes.

Later on 2026-11-24, the canvas buttons and their calm disabled look, the Session page's helper
tiles, Project counts and in-card Check progress, and drawing every absence as plain quiet text
package the page at 2,481,691 bytes on Node 26.12.1 and pnpm 12.19.0, 1,704 bytes above the tile
column page. The page bound follows that measurement. The fixture bound stays at 250,000 bytes.

Later on 2026-11-24, giving the card's Check progress room and keeping the summary's time column
packages the page at 2,482,079 bytes on Node 26.12.1 and pnpm 12.19.0, 388 bytes above the Session
page canvas build. The page bound follows that measurement. The fixture bound stays at 250,000
bytes.

Moving Your AI allowance to the top of Sessions packages the page at 2,482,083 bytes, 4 bytes above
the spacing build, on the same toolchain. The page bound follows that measurement.

Later on 2026-11-24, drawing a Not checked yet word in a far-right Sessions row cell, saying Saved goal
unavailable for a goal that cannot be read (on the row, the session page and Goal history), naming saved
outcome lines in the Goal cell, and sharing one No goal yet predicate between the filter chips packages the
page at 2,484,987 bytes on Node 26.12.1 and pnpm 12.19.0, 2,904 bytes above the preceding build. The page
bound follows that measurement. The fixture bound stays at 250,000 bytes.

Later on 2026-11-24, holding Turn off quota reading on every quota surface, so the project's Usage
and alerts view and Needs you hide Claude's and Cursor's figures as the Sessions strip does and say
a hidden figure is hidden, packages the page at 2,485,899 bytes on Node 26.12.1 and pnpm 12.19.0, 912
bytes above the Not checked yet page. The page bound follows that measurement. The fixture bound stays
at 250,000 bytes.

Later on 2026-11-24, saying why a stored check shows no level once what it read has changed since,
on the Is it on track? card and in the Evidence tab, and saying the same for a later direction that
holds a departure back, packages the page at 2,487,303 bytes on Node 26.12.1 and pnpm 12.19.0, 1,404
bytes above the quota-reading page. The page bound follows that measurement. The fixture bound stays
at 250,000 bytes.

This sample's fixture is 139,981 bytes of compact JSON. `frontend/build/page-size.test.mjs` checks
both, in `pnpm test`, which CI runs. Raising either is a decision to record here, with the measurement
that justifies it.

On 2026-11-05, the explicit long-analysis preview, progress, coverage and recovery controls raised
the page built from source checkpoint `a027886b` (2,260,171 bytes) to the one built from
`d090c5ff` (2,307,015 bytes): 46,844 bytes
(2.07%). The page allowance is therefore increased by 32 KiB, to the same 1,884,747-byte baseline
plus 432 KiB: 2,327,115 bytes, leaving 20,100 bytes above the measured build. The fixture
allowance remains 250,000 bytes.

The comparison used the same owned native session (32 entries, 3,207,429 source bytes), synthetic
saved intent and warm backend caches, with ten alternating runs per version after two warmups.
Both versions ran in the same headless Chromium 153.0.8010.12 process on a ten-core macOS machine,
at 1440 × 1050; the recorded load averages were 4.98, 7.32 and 5.69. Median navigation through the
common Analyze control becoming visible and fonts becoming ready was 250.550 ms before and
209.750 ms after. Median opening of Drift settings through visibility and two animation frames
was 274.949 ms before and 276.888 ms after. There were no model calls, JavaScript errors or
external requests. These local measurements support this bounded allowance; they are not a
service-level target or a claim that the page is generally faster.

On 2026-11-13, the settings-refusal sentences (Find goal, summaries and the Live monitor, each
saying that nothing was sent or charged and what to check, with a Codex variant) and the Live
monitor's resend of a full-dashboard refusal raised the page built on `main` at `2a8a0e15`
(2,325,571 bytes, 1,544 under the bound) to 2,327,423 bytes with the sentences and 2,328,127 bytes
with both: 2,556 bytes (0.11%), 1,012 over the bound. The page allowance is increased by 8 KiB, to
the same 1,884,747-byte baseline plus 440 KiB: 2,335,307 bytes, leaving 7,180 bytes above the
measured build. No timing comparison was run for an increase of this size. The fixture
allowance remains 250,000 bytes.

On 2026-11-16, launcher-declared parent links and group labels (child sessions nested under
their parent, "Waiting on child", the Group filter and grouping, and the native-state helper that
keeps a child's hold out of reading and timeline derivations) raised the page built on `main` at
`6f031ea5` (2,331,807 bytes) to 2,339,091 bytes: 7,284 bytes (0.31%), 3,784 over the bound. The
page allowance is increased by 8 KiB, to the same 1,884,747-byte baseline plus 448 KiB:
2,343,499 bytes, leaving 4,408 bytes above the measured build. No timing comparison was run for an
increase of this size. The fixture allowance remains 250,000 bytes.

On 2026-11-22 the Phosphor Bold glyphs, Sessions legend and evidence-based status rendering
brought the page from 2,339,139 bytes on the fixed Inter layer to 2,347,559 bytes. That is
an increase of 8,420 bytes (0.36%) and 4,060 bytes above the old bound. The 4 KiB increase
sets the allowance at the same baseline plus 452 KiB, or 2,347,595 bytes, with 36
bytes to spare. The fixture allowance stays at 250,000 bytes. Both builds used Node 26.10.0.

On 2026-11-23, the shared buttons, title links, cards and notices brought the page from
2,347,567 bytes on the icons and style guide layer at `b64a11a3` to 2,350,359 bytes on the
restacked buttons and cards layer, an increase of 2,792 bytes (0.12%) and 2,764 bytes above
the previous bound. The page allowance rises by 7 KiB to the same baseline plus 459 KiB,
or 2,354,763 bytes, leaving 4,404 bytes above the measured build. The new build used Node
26.10.0. The fixture allowance stays at 250,000 bytes.

On 2026-11-23, the shared Switch accessibility and narrow-layout fixes brought the page
from 2,354,223 bytes at `9303135c` to 2,355,311 bytes with Node 26.10.0. The increase of
1,088 bytes (0.05%) put the page 548 bytes above the previous bound. The allowance rises
by 1 KiB to the same baseline plus 460 KiB, or 2,355,787 bytes, with 476 bytes to spare.
The fixture allowance stays at 250,000 bytes.

On 2026-11-23, the Sessions status tiles, keyboard tooltips and stored-progress pills brought
the page from 2,355,311 bytes on the shared Switch layer to 2,358,771 bytes on Node 26.10.0.
The 3,460-byte increase (0.15%) exceeded the previous bound by 2,984 bytes. The page allowance
rises by 3 KiB to the same baseline plus 463 KiB, or 2,358,859 bytes, leaving 88 bytes above
the build. The fixture allowance stays at 250,000 bytes.

On 2026-11-23, the corrected Sessions absence words, row facts and tooltip target brought
the page to 2,359,323 bytes on Node 26.10.0, 552 bytes above the previous build and 464 bytes
above its allowance. The allowance rises by 1 KiB to the same baseline plus 464 KiB, or
2,359,883 bytes, with 560 bytes to spare. The fixture allowance stays at 250,000 bytes.

Removing progress levels from Sessions rows on 2026-11-23 reduced the page by 768 bytes
to 2,358,555 bytes on Node 26.10.0. The 2,359,883-byte allowance leaves 1,328 bytes to spare.

Removing progress absence words from Sessions rows reduced the page by another 1,624 bytes,
to 2,356,931 bytes on Node 26.10.0. The same allowance leaves 2,952 bytes to spare.

On 2026-11-23, the shared attention selector, inline Worth a look flag and counted Sessions
filter raised the restacked page from 2,356,931 bytes at `98130e04` to 2,360,587 bytes on Node
26.10.0. The 3,656-byte increase put the page 704 bytes above the previous bound. The
allowance rises by 3 KiB to the same baseline plus 467 KiB, or 2,362,955 bytes, leaving
2,368 bytes to spare. The fixture allowance stays at 250,000 bytes.

On 2026-11-23, the Worth a look follow-up brought the restacked page from 2,360,587 to
2,362,371 bytes on Node 26.10.0. The 1,784-byte increase left 584 bytes under the previous
bound. The follow-up's 2 KiB allowance increase brings the bound to the same baseline plus
469 KiB, or 2,365,003 bytes, leaving 2,632 bytes above the measured build. The fixture
allowance stays at 250,000 bytes.

On 2026-11-23, readable times and summary sizes brought the restacked page from
2,362,475 bytes at `4440747d` to 2,365,691 bytes on Node 26.10.0. The 3,216-byte increase
put the build 688 bytes above the 2,365,003-byte bound. The allowance rises by those
688 bytes to 2,365,691 bytes. The fixture allowance stays at 250,000 bytes.

On 2026-11-23, spelling out the duration in the unconfirmed wait note brought the page from
2,365,691 to 2,365,695 bytes on Node 26.10.0. The allowance rises by those four bytes, to
2,365,695 bytes. The fixture allowance stays at 250,000 bytes.

On 2026-11-23, the Sessions overview and shared Needs you queues brought the page from
2,365,695 to 2,372,971 bytes on Node 26.10.0. The allowance rises by 7,276 bytes to
2,372,971 bytes. The fixture allowance stays at 250,000 bytes.

On 2026-11-23, the Sessions status tabs, inline filters, and evidence-based counts brought the page from
2,372,971 to 2,377,735 bytes on Node 26.10.0. The allowance rises by 4,764 bytes to
2,377,735 bytes. The fixture allowance stays at 250,000 bytes.

On 2026-11-23, preserving published wording while auditing the Sessions page brought the page from
2,377,735 to 2,379,479 bytes on Node 26.10.0. The allowance rises by 1,744 bytes to
2,379,479 bytes. The fixture allowance stays at 250,000 bytes.

On 2026-11-23, the Session's inline technical details and Activity log filters bring the
packaged page to 2,405,367 bytes on the pinned Node 26.10.0. The page bound rises by the
measured 25,888 bytes. The fixture bound stays at 250,000 bytes.

On 2026-11-23, the inline session technical tabs brought the page from 2,405,367 bytes
at `35977ce8` to 2,417,291 bytes, an increase of 11,924 bytes (0.50%). The page bound
is the measured 2,417,291 bytes. The fixture allowance stays at 250,000 bytes.

On 2026-11-23, the rebased and corrected session technical tabs packaged at 2,418,351
bytes with Node 26.12.1 and pnpm 12.17.0. The rebased Activity log page at `6f4b1317`
measures 2,404,243 bytes. This sets the page bound to the measured 2,418,351 bytes, an
increase of 1,060 bytes over the previous bound. The fixture bound is 250,000 bytes.

On 2026-11-23, the progress check control labels, Uses AI note, level source lines and sending
disclosures packaged at 2,418,739 bytes on the corrected technical tabs. The review fixes add 180
bytes, for a measured page bound of 2,418,919 bytes on Node 26.10.0 and pnpm 12.17.0.
The fixture bound stays at 250,000 bytes.

On 2026-11-23, the Session layout, side cards and story brought the packaged page from
2,415,259 bytes at `5289924f` to 2,417,811 bytes. The review fixes increased it by
1,892 bytes to 2,419,703 bytes on Node 26.10.0 and pnpm 12.17.0.
The page bound is the measured 2,419,703 bytes. The fixture allowance stays at 250,000 bytes.

On 2026-11-24, the rebased Sessions review fixes packaged at 2,488,543 bytes on Node 26.12.1
and pnpm 12.19.0, setting the page bound to that measurement.

On 2026-11-26, the notice for an action refused through a web proxy or network address
packaged at 2,489,131 bytes on Node 26.12.1 and pnpm 12.19.0, up 588 bytes. The page bound
rises to that measurement. The fixture bound stays at 250,000 bytes.

The Plan glossary rows package at 2,489,999 bytes on Node 26.12.1 and pnpm 12.19.0,
868 bytes above the previous page. The production stylesheet is byte-identical to the
previous build. Storybook compiles the Plan utilities while the page has no app route.
The page bound follows the measured package. The fixture bound stays at 250,000 bytes.


The configured Plan destination packages at 2,512,259 bytes on Node 26.10.0 and pnpm 12.19.0,
up 22,260 bytes (0.89%). The increase covers the Plan transport, page and styles. The bound
follows the measured package. The fixture bound stays at 250,000 bytes.

Grouping Plan lanes by their tracker state packages at 2,513,539 bytes on Node 26.12.1 and
pnpm 12.19.0, up 1,280 bytes (0.05%) for the lane groups, the not-counted note and the two
glossary words. The bound follows the measured package. The fixture bound stays at 250,000 bytes.

The Plan review fixes package at 2,520,447 bytes on Node 26.12.1 and pnpm 12.19.0, up 6,908
bytes (0.27%). The increase covers the field-by-field check of the plan reply, the plan read's
four states, the plain sentence for each source refusal, the undecided design notes and the new
glossary words. The bound follows the measured package. The fixture bound stays at 250,000 bytes.

Showing an ask with no words and dropping only an unreadable plan item package at 2,521,071 bytes
on Node 26.12.1 and pnpm 12.19.0, up 624 bytes. The bound follows the measured package. The fixture
bound stays at 250,000 bytes.

Telling a repository's files apart on the Plan page's Sources list, folding a missing draft branch
into one row and counting the lane briefs that were read package at 2,522,259 bytes on Node 26.12.1
and pnpm 12.19.0, up 1,188 bytes. The bound follows the measured package. The fixture bound stays
at 250,000 bytes.

The review fixes for that list package at 2,522,607 bytes on Node 26.12.1 and pnpm 12.19.0, up 348
bytes, for counting refused lane briefs that have no lane name by reason. The bound follows the
measured package. The fixture bound stays at 250,000 bytes.

GitHub plans package at 2,527,047 bytes on Node 26.12.1 and pnpm 12.19.0, up 4,440 bytes.
The page adds tracker source states, due dates and expiration of tracker rows in the browser.
The page bound follows the measured package, and the fixture bound stays at 250,000 bytes.

The GitHub plan review fixes package at 2,527,827 bytes on the same toolchain, up 780 bytes.
The bound follows the measured package.

Showing GitHub asks in Waiting on you and limiting file sections to declared sources package
at 2,530,783 bytes on Node 26.12.1 and pnpm 12.19.0, up 2,956 bytes. The page bound follows
that measurement. The fixture bound stays at 250,000 bytes.

## View only

Two layers hold it, and either alone is enough.

The server layer is `createSampleFetch`. A read answers from the fixture. It uses the same
`correction.compose` output as a live session. The builder writes it with `--recompose`, and
`test_sample_session_files` checks that the stored correction agrees with the composer. Copying
is accepted locally. Other writes return a 403 explaining the sample, including starting,
canceling and deleting a summary.

The press layer is `ViewOnly`. It stops a press that would edit, save, allow or run, before it reaches
a handler, and says in one line why, so a reader sees a sentence and not an error from a request that
was never going to work. Links, disclosures, the select, the marks, a finding's cited entry numbers and
Back to the finding, a summary line's cited entries and its links to a departure card, Steer back and
Copy stay live, because they only read or compose words. The Live monitor switch shows or hides the
sample's estimate without taking a lease. The guard allows the hidden checkbox beside that switch
because Base UI sends activation through it. Every summary control is held: Summarize,
Update summary, Summarize again, Cancel, Delete summary, Turn off summaries and Turn summaries on, and
Pause model calls and Resume model calls beside them. The finished sample shows only some of them, so
its stories draw it in each state that offers the others and press each one. A control inside a
popover (What is sent, on either card) is drawn in a portal outside the guard's node, and is held all
the same, because React delivers a press through the component tree rather than the document's.
Typing needs its own listener: React's `onBeforeInput` is an older event than the browser's
`beforeinput`, which is what typing, pasting and deleting raise, so the guard listens for the native
one on the node, in the capture phase. Every text field on the sample's page sits inside the guard's node,
none in a popover, so the portal is not a way around it.

The view-only sample never posts an open start: its fixture carries a stored summary, and a session
with one is never summarized on open.

## The marks

Each mark is numbered in reading order. The progress card comes before What's happened so far
in the current [Session layout](design-reading-a-session.md#amended-2026-11-22-owner-the-session-page-has-two-columns-from-1100-px).

1. **Your goal**, on the Goal card.
2. **A departure, and its evidence**, beside the finding that links to Evidence.
3. **Steer back**.
4. **What is sent, and Pause all AI use**, beside the progress card's disclosure.
5. **What's happened so far**, beside the story card's heading.
6. **A phase that holds a departure**, on the first phase that carries the flag.
7. **Activity log**, beside the technical details trigger.

The activity note says a number never moves, which holds for the entries a summary line or a finding
cites. A number written inside quoted speech counts the original session's live board, as
[the README](../sample-session/README.md#what-is-real-and-what-is-not) records.

They are popovers that open on hover (`openOnHover`), and also on a press and from the keyboard. A
tooltip was rejected because it is unreachable by touch and by keyboard, and the sample is most likely
to be opened from a link on a phone or a laptop with no one at the keyboard to explain it. The banner
repeats every note as text under "Read the tour as text", so a popup is never the only copy of a fact.
The marks draw nothing outside the sample: `SampleMark` reads a context that only the sample provides.

The marks style themselves with Tailwind utilities, and `tailwind.css` reads files by an explicit
`@source` list, so `frontend/src/sample/` is on that list. A utility class in a file that is not on it
generates no CSS and fails silently: the first build of the marks drew them unstyled until the path
was added.

## Known limits

- The summary and the reading are snapshots of one model's answers to one prompt each. They do not
  change when either prompt does. Regenerate the fixture (README) when a change to what they say
  should show.
- A few of the summary's lines can be withheld, and say so in their place, because this session is
  about merging pull requests and closing issues and the summary may not say that in its own voice.
  Two of 37 lines are withheld in this capture; the opening summary and every phase title are shown.
  That is the ruled backstop at work, not a fault in the capture, and the sample shows it as any
  session would.
- The fixture is the shape of the page's payloads on the day it was captured. A payload change the
  page cannot parse fails the sample's tests, and a change it can parse leaves the sample as it was.
- Times in the session are shifted by one fixed offset, a whole number of days plus a time of day, so
  the order and the gaps survive and no timestamp shows the real date or hour. The page shows them in
  the reader's own time zone. The session is about this product, so its feature names, files and tool
  versions stay, and a reader with the public repository can place it within a few weeks; its quoted
  commit hashes, branch names, pull-request titles and commit subjects are replaced so that none
  leads to a dated commit ([the README](../sample-session/README.md#what-is-real-and-what-is-not)
  says what is replaced and what is not).
- The transcript is committed. That is an exception to the policy in
  [tests/README.md](../tests/README.md#what-is-committed-and-what-is-not), made by the owner on
  2026-10-19 for this one session, with its mapping kept out of the repository.
