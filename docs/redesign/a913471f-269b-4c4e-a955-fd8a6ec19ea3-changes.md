# Session a913471f: "Mark as inaccurate"

**Path:** a reading the reader can see is wrong, marked inaccurate, undone, marked again and
reloaded.

**Session:** Haiku 5.5 moving the how-to popup's narrow-screen proof onto the real session header in
`compass` (worktree `haiku-4867`, draft PR #639). I saved an intent whose outcome line forbade
edits under `frontend/e2e`, knowing the issue's proof lives there, so the session was certain to
break that line. The agent asked one product question mid-way (a 178-word how-to against a 150-word
ceiling); I chose to keep the ceiling on the minimal payload only. Observed on the `:4560` build of
`feature/session-redesign`.

Severity: **P1** breaks the flow or misleads, **P2** departs visibly from the design, **P3** polish.

## The reading that needed marking

1. **P1 · The reading says "Can't tell" about a line that Compass's own record breaks.** The outcome
   "No file under frontend/e2e is edited; the proof lives in Storybook." came back `Can't tell`.
   The same card lists `Where the work went: frontend/e2e · 1 file [12.1]`, and the outline says `14
   files written in frontend/e2e (13), docs (1)`. A deterministic record of a write into a folder
   the outcome line forbids should settle that line as departing, without a model judgment. The
   reader is shown the contradiction and the verdict side by side.
2. **P2 · The goal line is "Consistent" on the agent's word alone.** "Prove the how-to popup fits at
   320px against the real session header…" was `Consistent with what the agent said at [30]`, with
   no check cited. The agent did run the proof and its mutation, and those runs are in the record.
3. **P2 · Steer back is offered on a reading with no departure** (`Steer back · from the check at
   11:27`). See 1ef27ca8 item 11.
4. **P2 · "Delegated work: 1 recorded launch; 1 of this session's launches has no recorded
   completion…".** It appears in this card and the other second-batch cards. It is a
   bookkeeping fact about subagents. It is not tied to any line, and the reader has no action to
   take.

## Mark as inaccurate

5. **P2 · It hides the level but leaves the verdict at full weight.** After the press, the bar and
   the bold verdict were replaced by "Drift level hidden because you marked this analysis
   inaccurate." The `Can't tell` heading, the three line verdicts, their evidence and `Where the work
   went` all stayed, unchanged in style. A reader scanning later sees verdict lines with no sign that
   they were disowned. Dim them, or collapse them under "Marked inaccurate at 11:28 ⌄".
6. **P2 · It asks nothing about what was wrong.** One press, with no "What was wrong?" (a line, the
   level, the evidence). The reader's knowledge (here: the record shows an e2e write) is lost, and
   nothing reaches the reading's next run.
7. **P2 · No way forward after marking.** The card offers `Undo` and `What the analysis read ⌄`,
   but no `Analyze again`. Marking a reading inaccurate is exactly when a reader wants a second
   reading, perhaps after fixing the intent. `Steer back` disappears, as promised.
8. **P3 · Two messages say the same thing.** "Drift level hidden because you marked this analysis
   inaccurate." at the top and "Marked inaccurate. This analysis no longer sets the drift level or
   Steer back." at the bottom beside `Undo`. Keep one, with `Undo` beside it, at the top.

## What worked

- `Undo` restored the level, the verdict heading and `Steer back` immediately.
- The mark survived a full page reload, with the same two messages and `Undo`.
- The button's own explanation ("Stops this analysis from setting the drift level or Steer back.
  Nothing is sent or re-run.") says exactly what happens.
