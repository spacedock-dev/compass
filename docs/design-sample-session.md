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
about what the agent claimed, and the drift level reads Medium from the two. Steer back composes a correction that gives each departure's
time on the reader's clock, quotes the agent's words at that moment and carries the reading's
explanation, with no entry numbers.

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
stored summary is the 2026-10-20 one, kept, because the transcript is unchanged and a summary does not
read the intent ([the README](../sample-session/README.md#what-is-real-and-what-is-not) says how it
was carried over).

A goal-only reading says, in its cutoff, that it read no outcome lines. That sentence is the
producer's and is right for any session, so the product keeps it. The capture drops it for the sample
(`cutoff_on_timeline` in `scripts/build_sample_fixture.py`), because the sample's job is to show a
goal alone and a sentence about a line nobody saved sends the reader looking for it. A test fails if
the intent carries a line or any sentence the sample draws from the reading names an expected
outcome. The real Intent card's own optional Expected outcome field is the product's and stays.

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
same wording and the same layout. A reader finds it from a line above the Sessions list, and by link.
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
- The reading's sentence counting how old its entries are ("The oldest is from about 3846h ago") is
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

The fixture ships inside `react.html`, and every install and every page load carries it, so its size is
bounded before a sample is built, not measured after. The bounds were set on 2026-10-19, before this
sample was captured:

- The page may be at most 1,884,747 bytes, the page as built that day, plus 400 KiB: 2,294,347 bytes.
- The fixture may be at most 250,000 bytes of compact JSON. The page carries its script
  base64-encoded, so a fixture byte costs about four thirds of a page byte, and the step from the first
  sample's 75,130 bytes to the bound is at most about 233 KB of page, which leaves the rest of the
  400 KiB to the code that ships beside it.

This sample's fixture is 140,642 bytes of compact JSON. `frontend/build/page-size.test.mjs` checks
both, in `pnpm test`, which CI runs. Raising either is a decision to record here, with the measurement
that justifies it.

## View only

Two layers hold it, and either alone is enough.

The server layer is `createSampleFetch`. A read answers from the fixture. Composing a correction
answers the correction `correction.compose` makes from the fixture's own row and record (the builder
writes it with `--recompose`, and `test_sample_session_files` fails while the stored one differs, so
the demo shows each departure's explanation the real composer carries), with each kept moment drawn
on the reader's clock by `datedClock`, the page's copy of the composer's rule, and recording that it was
copied is accepted and goes nowhere. Every other write is refused with a 403 and a sentence saying this is a sample, the summary's
start, cancel and delete included.

The press layer is `ViewOnly`. It stops a press that would edit, save, allow or run, before it reaches
a handler, and says in one line why, so a reader sees a sentence and not an error from a request that
was never going to work. Links, disclosures, the select, the marks, a finding's cited entry numbers and
Back to the finding, a summary line's cited entries and its links to a departure card, Steer back and
Copy stay live, because they only read or compose words. Every summary control is held: Summarize,
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

Each mark is a numbered (i) beside the part it explains, in the order a reader meets the parts down
the one-column page, which puts What the session has done before the Drift card as the design draws it
(owner, 2026-10-21; it was the other way round from 2026-10-20):

1. **Your intent**, on the Intent card.
2. **What the session has done**, beside the summary card's heading, outside it, so the card's name
   stays the heading's words.
3. **A phase that holds a departure**, on the first phase marked as holding one, once.
4. **A departure, and its evidence**, beside the goal departure's cited entries.
5. **Steer back**.
6. **What is sent, and Pause model calls**, beside the drift card's What is sent.
7. **Full activity**, beside its trigger.

The first sample's tour noted the drift level and the analysis headline instead of the summary and
the phase. Neither is noted now, because the summary is what the redesigned page leads with.

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
- Several of the summary's lines are withheld, and say so in their place, because this session is
  about merging pull requests and closing issues and the summary may not say that in its own voice.
  Seven of 35 lines are withheld, including the whole last phase, which holds the steer; the opening
  summary and every phase title are shown. That is the ruled backstop at work, not a fault in the
  capture, and the sample shows it as any session would.
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
