# The walk

The five stages of the reader's day, in the order the product puts them, with the promise each one
makes and the absences that break it. Walk the stages the issue touches, not all five, unless the
change reaches the whole page.

Promises here are quoted from [`docs/promise-map.md`](../../../../docs/promise-map.md), which is
canonical. Read them from that file at review time rather than trusting this copy: the same sentence
lives in three places and they have been observed disagreeing. If your walk concludes a promise's
wording is wrong, do not edit one copy. See "If a promise is wrong" at the bottom.

## The routes

Sessions is the entry. The fragment is the address:

- `#n=sessions` (Sessions) shows the session list and its filters. It also opens when the address
  has no route.
- `#n=projects` (Projects) shows projects and links to their sessions. Keep it in the navigation
  even when no project is selected.
- `#n=attention` (Needs you) shows Waiting on you, Worth a look, Ready to wrap up and What Compass
  can't see. Follow a row title to its Session page.
- `#n=intent` (Goal history) shows recorded goal changes.
- `#n=settings` (Settings) shows saved choices.

`n` opens Needs you, `p` Projects and `s` Sessions. Fragment changes alone do not reload the document.
When Help ships, include it in the navigation walk.

**Walk the routes before you walk the stages, with the mouse only.** From each top-level view, check
that every other one is offered and that the one you are standing on is marked. Put the keyboard
down to do it: a shortcut nothing advertises is not a way a reader finds a screen.

This is the reachability check, and it is distinct from the disclosure check further down. A path
existing is not a path a reader can find, and the two questions have different answers: Attention
shipped as a whole view with no entry in the header, reachable only by typing a fragment, pressing a
key nothing mentions, or clicking a status chip that exists only while a block is reported. A first
pass here confirmed a path existed and stopped, which was the wrong question. The operator found it
by opening the board and looking at the header.

Two tests were pinning it in place, both by naming the two views they knew about, so the suite
reported the gap as correct. Derive a nav assertion from the router's own view set rather than from a
list you type, and assert the current one is marked on **every** view, which is the assertion a test
that never navigates to a view cannot make about it.

## P1. Which of my agents are running?

> every session on this machine, across ten harnesses, on one screen, with what is active now kept
> apart from what is only recent history.

**On screen:** the header's Working count, At a glance, then Right now and the earlier group
named for its time window. The Working count includes only sessions shown as Working. Use the
Sessions legend to read the state tiles and the Worth a look flag.

**Force these absences:**

- An agent Compass discovered without sessions to show. Its filter entry still shows that it
  was discovered and has no sessions in view.
- A row whose agent publishes no title, no location or no activity. Look for each absence in
  words, including State not published when the state is missing.
- Sessions sharing a display label. They collide into one identity row, which is correct, and the
  count beside it must match the payload.

**The limit to check is disclosed:** a row counts as active only when its harness published evidence
that it is, and a recent observation cannot prove a harness is still open.

## P2. What is it doing, and when should I come back?

> for each live session, what it is doing now, what it plans next, how far into the current turn it
> is, and an estimate of when that turn ends. It tells you when that changes instead of making you
> poll.

**On screen:** open a working session and read Right now. Check the current work, any coming
step, what the session is waiting for and the turn's progress against the available evidence.

**Force these absences:**

- No coming step published. Right now says what is missing.
- A turn with failures. Check the sentence against the evidence for that turn. Consecutive failures,
  total failures and a request where nothing succeeded each need their own wording.
- A turn Compass has only partly read. Check that Right now withholds claims about the whole request.

**The limit:** Compass reads a tool call's name and whether it failed, never what it contained.

## P3. Is anything waiting on me?

> one queue of everything blocked on you, with what it is waiting for and how long it has waited. A
> session can also ask you a question directly and wait for your answer.

**On screen:** in Needs you, read the Waiting on you reason and how long the session has waited.
Open the Session page from the row. Where Copy command is available, verify it copies the agent's
own command for returning to the session. Check any terminal switch action on the surface that
offers it, including when that action is the only one available.

**Force these absences:**

- Nothing waiting. The queue reads zero and What Compass can't see still explains the coverage.
- An agent that cannot report a request at all. Look for the coverage limit on its row so the
  silence does not read as an all-clear.
- An agent that can report requests when its hook is enabled, with that hook switched off. Check
  that the coverage explains the condition even when it counts the agent as able to report.
- A request from a session with no reachable terminal. The terminal action is absent. Copy command
  remains available wherever the agent has a command for returning to that session.
- A second press while a terminal switch request is in flight. It is refused page-wide. The
  announcement keeps the reason as broad as the response supports.

**The limit:** four of the ten harnesses can report a gate, and they are Claude Code, Codex, Copilot
and Cursor.

## P4. Will I hit the wall before the work finishes?

> your quota in one place across vendors, with each window's budget shown against its own clock, so
> you can see whether there is room before you start rather than partway through.

**On screen:** Your AI allowance. Read the fill, the clock tick, the pace, when the budget ends
and when the window resets. The earliest budget end determines the row order.

**This is the stage where this product has failed most often.** Force all of these:

- **Both quantities present in every row.** The budget's end and the window's reset sit in adjacent
  columns and nothing adjudicates between them. A column carrying a verdict where a time belongs is
  the defect, because the reader cannot compare what they were not shown.
- Before the disclosure is answered: no window at all for a credential-fetched vendor.
- After it is switched off: nothing stale presented as current.
- A reading older than the activity window: withheld, not rendered.
- A reset already past: not projected.
- A budget fully spent: says spent, rather than printing the present minute as a deadline.
- A pace measured at zero, and a pace not measured at all: two different sentences, neither of them
  a projection.
- A value the vendor publishes that the strip does not render at all.

**The limit:** what a vendor exposes is what you get.

## P5. Did anything die quietly?

> nothing finishes invisibly. Work that finished and was never read is flagged, and a session that
> ends leaving uncommitted changes says so.

**On screen:** the Ended state and any outcome evidence. Check Needs you for a clean end in
Ready to wrap up and a dirty end in Worth a look. Open the session's technical details to
read the underlying git evidence when it is available.

**Force these absences:**

- A session that went quiet without reporting. Compare it with a session at its prompt whose
  evidence is identical. Both show the same text. If neither published a state, both show
  State not published.
- A session that published an end. Check that it leaves the Working count and shows Ended.
  Follow a clean end to Ready to wrap up and a dirty one to Worth a look. Read the section
  headings on the page and hold the documented names to them.
- An agent whose activity Compass can only scan, and a run under `--no-events`. Check that the row
  states the limit when Compass cannot observe an end.
- A session whose git state was not measured, one measured clean and one measured dirty.
  Look for a distinct sentence in each case.

**The limit:** the probe runs one bounded command and publishes two numbers, never a pathname. It
is not read-only and not non-executing: DEC-11 retracted both adjectives, because a committed filter
attribute can make git invoke a driver that writes inside the repository.

## If a promise is wrong

The `We promise:` sentence is duplicated verbatim in three places:
[`docs/promise-map.md`](../../../../docs/promise-map.md),
[`docs/visibility-2x2/items.json`](../../../../docs/visibility-2x2/items.json) in `columns[].promise`,
and the Linear project overview. Change one and change all three, in the same commit for the two that
live in the repository.

Nothing enforces this. The copies have been observed disagreeing, with one of them promising a
projection the project had already decided three times not to build, so diff them as part of the walk
rather than assuming they match. A promise may not enter the map before the capability ships, and a
capability narrow enough to be absent from most rows belongs in the backing list with its limit
stated rather than in the headline.
