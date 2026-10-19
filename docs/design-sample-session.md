# The sample session

A new reader opens Compass with nothing on the board, or with sessions that have never drifted. The
Intent and drift feature is the part of the product that needs the most explaining, and it is hardest
to explain before there is a session that drifted. The sample session is a finished example they can
open without running an agent: a real, anonymized Claude Code session, a goal and two expected
outcomes saved against it, a stored reading that finds drift, and the correction Compass composes to
steer it back. It is view only, and seven numbered (i) marks say what each part of the page is for.

[sample-session/README.md](../sample-session/README.md) owns what the data is and how it was made.
This record owns how the page treats it, and what was tried and rejected.

## What was chosen

The sample is the session a reader would most want to see: the live level reads High from recorded
checks alone, the stored reading finds a departure from the goal and cites the entries it rests on,
and Steer back composes a correction that names those entries by number. Other candidate sessions were
read for this, and this one was picked because its drift can be explained in a sentence without
knowing the project.

The story is one turn. The person asks the agent to resolve a pull request's merge conflicts by
rebasing, and to leave the pull request's code alone. The agent rebases cleanly, then reproduces a
Windows-only test failure, adds a test and starts on a fix. Only history was meant to change, so that
is the drift.

## Where it lives

The route is `#n=session:acme%2Fdashboard:claude:sample`, an ordinary session route with a reserved
project and session id. `sample` is not a shape any real session id takes, so it cannot collide with
one. `RoutedView` in `frontend/src/shell/views.tsx` wraps the real `SessionView` for that route and
for no other, so the page a reader sees is the page every session gets, with the same components, the
same wording and the same layout. A reader finds it from a line above the Sessions list, and by link.

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

`frontend/src/sample/session.fixture.json` holds five answers, captured from a real Compass server
run against an isolated home that held only the sample session: the board row, the project context,
the prompts, the session record and the composed correction. `scripts/build_sample_fixture.py` takes
the capture, so nothing in it was typed by hand except the authored intent (see the README).

Three rewrites make the capture a stable sample and not a snapshot of one afternoon:

- The session id becomes `sample`.
- Every time within six hours of the capture moves to just after the session's last record, so
  "1m ago" reads the same on any day. The sample's clock (`sampleNow`) starts at that moment and runs
  on from it.
- The one sentence in the reading that counted entries "about 3718h ago" says "all within the last
  hour", which is what the same words said when the reading was read.

The board's digest of the store the reading was saved in is cut to 32 characters, so nothing in the
file is a credential-length value and the leak sweep stays strict.

## View only

Two layers hold it, and either alone is enough.

The server layer is `createSampleFetch`. A read answers from the fixture. Composing a correction
answers the correction the real server composed, and recording that it was copied is accepted and goes
nowhere. Every other write is refused with a 403 and a sentence saying this is a sample.

The press layer is `ViewOnly`. It stops a press that would edit, save, allow or run, before it reaches
a handler, and says in one line why, so a reader sees a sentence and not an error from a request that
was never going to work. Links, disclosures, the select, the marks, a finding's cited entry numbers and
Back to the finding, Steer back and Copy stay live, because they only read or compose words. Typing needs its own listener: React's
`onBeforeInput` is an older event than the browser's `beforeinput`, which is what typing, pasting and
deleting raise, so the guard listens for the native one on the node, in the capture phase.

## The marks

Each mark is a numbered (i) beside the part it explains. They are popovers that open on hover
(`openOnHover`), and also on a press and from the keyboard. A tooltip was rejected because it is
unreachable by touch and by keyboard, and the sample is most likely to be opened from a link on a
phone or a laptop with no one at the keyboard to explain it. The banner repeats every note as text
under "Read the tour as text", so a popup is never the only copy of a fact. The marks draw nothing
outside the sample: `SampleMark` reads a context that only the sample provides.

The marks style themselves with Tailwind utilities, and `tailwind.css` reads files by an explicit
`@source` list, so `frontend/src/sample/` is on that list. A utility class in a file that is not on it
generates no CSS and fails silently: the first build of the marks drew them unstyled until the path
was added.

## Known limits

- The reading is a snapshot of one model's answer to one prompt. It does not change when the reading
  prompt does. Regenerate the fixture (README) when a change to what a reading says should show.
- The fixture is the shape of the page's payloads on the day it was captured. A payload change the
  page cannot parse fails the sample's tests, and a change it can parse leaves the sample as it was.
- Times in the session are shifted by one fixed offset, a whole number of days plus a time of day, so
  the order and the gaps survive and the real dates and hours do not. The page shows them in the
  reader's own time zone.
- The transcript is committed. That is an exception to the policy in
  [tests/README.md](../tests/README.md#what-is-committed-and-what-is-not), made by the owner on
  2026-10-14 for this one session, with its mapping kept out of the repository.
