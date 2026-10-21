# Recommended changes to the session page

This file merges and de-duplicates the nine walk records in this folder. Each record follows one
path through the redesigned session page, using a real Haiku 5.5 session that was implementing an
issue at the time. The page was the `:4560` build of `feature/session-redesign`, compared against the
Session Redesign design (`Main.dc.html`) and the sample session.

| Record | Path | Session |
|---|---|---|
| [1ef27ca8](1ef27ca8-b981-41fa-8756-770e522d69f4-changes.md) | 1. Finished session: write the goal and outcome, then analyze | Analysis-reason guard, `compass` |
| [e14f8b08](e14f8b08-3815-4949-a1ae-9d9e4c35bc47-changes.md) | 2. Running session: write the goal and outcome, then analyze | CLL missing-parent fix, `recce` |
| [09741861](09741861-19f8-4fd8-a26b-620562b3d43e-changes.md) | 3. Update the intent | ProjectTabs ids, `compass` |
| [3ec91051](3ec91051-5ee6-4268-95df-9f48292f9d02-changes.md) | 4. Delete the summary and create it again | Launch-grant wording, `compass` |
| [70d59c47](70d59c47-3ecf-4a50-8bb1-5b8a40677212-changes.md) | 5. Create the summary | Check reason tokens, `compass` |
| [ef258ea0](ef258ea0-84d0-42ab-b8c6-76a5272cb548-changes.md) | 6. `Use this as my goal` | Worktree-write ruling, `compass` |
| [c0cffc90](c0cffc90-5cd9-4584-beb1-f4acb5960cbd-changes.md) | 7. `Steer back`, pasted, then read again | CSS coverage gate, `compass` |
| [a913471f](a913471f-269b-4c4e-a955-fd8a6ec19ea3-changes.md) | 8. `Mark as inaccurate`, undo, reload | How-to popup proof, `compass` |
| [3fb351f9](3fb351f9-f784-4e26-a65e-f363fce58b18-changes.md) | 9. `Discard everything` | Drift browser proofs, `compass` |

The happy path (a full analysis with departures) already matches the design closely. Nearly every
finding below is on the way to that state, or in a state the design does not draw. Severity: **P1**
breaks the flow or misleads, **P2** departs visibly from the design, **P3** polish. Sources cite the
record and its item number.

## Fix first

These either tell the reader something false or lose their work. The first four came from the
second round of walks. They are about whose words Compass thinks it is reading, and they undercut
every reading built on top.

1. **A message typed while the agent is working never reaches Compass.** Claude Code records a
   mid-turn message as a `queue-operation` absorbed into a tool result, not as a user turn. Compass
   showed `Later directions: none` and no outline phase, and the agent acted on the message anyway.
   A reading then sees the agent change course with no instruction behind it. Mid-turn correction is
   the normal way to steer a running agent. *(ef258ea0 #1, c0cffc90 #2)*
2. **Answers to the agent's own questions are invisible.** When the agent asks a multiple-choice
   question and the reader answers, that answer is a decision about the work. In one session the
   answer was "defer the cross-file half". The reading then named that deferral as the departure.
   *(ef258ea0 #2, c0cffc90 #1)*
3. **Compass treats its own pasted correction as the reader's new direction, then as departure
   evidence.** After pasting an unedited `Steer back` correction, the page offered `1 later
   direction` with `Use this as my goal`. The quote showed the harness's raw `<pasted_content id=…>`
   wrapper. The next reading's departure led with `You said: "Back to my goal…"`, the correction
   itself, and dated the departure to the moment of the steer. Recognise the correction (after
   stripping the paste wrapper) and settle it automatically. Never cite it as the reader's words in
   a departure. *(c0cffc90 #8, #10, #11)*
4. **A reading ignores a write Compass itself recorded.** "No file under frontend/e2e is edited"
   came back `Can't tell`, while the same card listed `Where the work went: frontend/e2e · 1 file`
   and the outline counted 13 files written there. A recorded write into a folder an outcome line
   forbids settles that line without a model. *(a913471f #1, 3fb351f9 #2)*
5. **A level with nothing behind it.** Drift shows `Medium` (bar and header pill) while the verdict
   is `Can't tell` on every line and there are no departures. When a later reading clears a
   departure, `Medium` stays. With no departure the level must read "Not enough recorded yet", or
   whatever the empty verdict is. *(1ef27ca8 #10, e14f8b08 #46)*
6. **A running session is read as if it had ended.** A reading taken mid-turn reported a departure
   because "the session ends with … no rerun and no push". The agent was running that rerun at that
   moment. While a turn is open, unfinished work is in progress, not a departure.
   *(e14f8b08 #37)*
7. **Saving a new goal silently moves what is read.** Rewriting the goal moved `reads from 10:57`
   to `reads from 11:05`. The next reading skipped the earlier work, and a line that had been
   `Consistent` became `Can't tell`. Keep the original start when the goal is edited, or say plainly
   that earlier work will no longer be read, and offer to keep it. `Use this as my goal` does the same:
   the window moved to the direction's time and the work the new goal describes went unread.
   *(09741861 #10, #13; ef258ea0 #7)*
8. **The reader's own kept direction is cited as the cause of drift.** The departure's `What` led
   with "You said: Keep option 1 only…", a direction the reader had just kept with `Keep my intent
   and analyze`. *(e14f8b08 #38; see also 3 above)*
9. **`Delete summary` has no confirmation, no pending state, no undo, and no message.** One press,
   two seconds of nothing, then the card collapses under the pointer as if no summary had existed.
   `Discard everything` already has the two-step confirm this needs. *(3ec91051 #4, #5, #6)*
10. **The form shows the drafted prompt while saving.** For about two seconds after `Save intent`,
    the goal reverted to the drafted prompt and the outcome lines emptied, then the typed words came
    back. *(e14f8b08 #16)*
11. **Later directions are acted on blind, and the first press does nothing.** The Drift card
    offers `Keep my intent and analyze` / `Add it to my intent` / `Use this as my goal` without
    quoting the direction. The first press only reveals it ("Read each direction, then press
    again"). Before any analysis, these buttons replace `Analyze drift` entirely.
    *(e14f8b08 #29, #35; 09741861 #2)*
12. **The one-time notices never collapse.** The first analysis and the first summary each open a
    ~300 to 400px "This request sends:" block inline. It stays above the result after the result
    arrives, with a second `Pause model calls` or `Turn off summaries` button inside. After it has been
    read, it should collapse to `What is sent ⌄`. *(e14f8b08 #23, 70d59c47 #6)*
13. **The outline of a young, busy session starts partway.** An 8-minute session with about 200k
    output tokens got "Compass read only the newest part of this session's record", and its one phase
    was titled `Before the first message of yours this outline read`. *(70d59c47 #2)*
14. **A caveat after almost every summary citation.** "(N cited entries are earlier checks or files
    that Full activity does not list, so they cannot be opened from here.)" Say it once at the foot of
    the card, or make those citations open. *(70d59c47 #11, 3ec91051 #3)*
15. **`Discard everything` keeps the summary and refills the intent.** After the confirmed discard,
    the model summary stayed, with no word that it was kept. The goal field immediately held the
    drafted first prompt again, so one stray `Save intent` brings an intent back. Say what is kept,
    and start the form empty. *(3fb351f9 #5, #6)*

## Page layout and header

- **Order the cards as the design does:** Intent, What the session has done, Drift. With no analysis
  yet, Drift currently sits between the goal and the work holding only controls. *(e14f8b08 #1)*
- **Use one quiet header line,** as in the design: `claude · Working · running Bash · turn 11m`.
  Today there are two lines, with the session id, a token rate, the project link, a state pill and
  an entry count, and "claude" and "Claude" both appear. *(e14f8b08 #2)*
- **Do not show a token rate on an idle session.** `4,106 tokens/min` persists after the turn ends.
  *(1ef27ca8 #2)*
- **Say a finished turn plainly:** "Turn ended 11:00 · waiting for you", not `idle · awaiting your
  message`. *(1ef27ca8 #1)*
- **File worktree sessions under their repository.** Sessions started in `.claude/worktrees/<name>`
  are filed under a project called `worktrees/<name>`, one per branch. *(1ef27ca8 #3)*
- **Use one entry count.** The header, the summary estimate and the outline gave 13, 20 and 22 for
  the same session at the same moment. *(1ef27ca8 #4)*
- **Fall back to the goal or first prompt when a session's title is only an issue key.** *(70d59c47 #1)*
- **Keep the page still under the reader.** Outline phases arriving above the Drift controls pushed
  them down, so a press missed. The deleted summary collapsing moved content under the pointer.
  *(e14f8b08 #21, 3ec91051 #5)*

## Intent card

- **Status:** one word on the right (`Saved`, `Unsaved changes`), as the design has. Drop the
  `How Intent and drift works` disclosure from the card header. *(e14f8b08 #3, 1ef27ca8 #7)*
- **Goal is a three-row textarea.** A 240-character goal currently scrolls sideways in a one-line
  input. *(e14f8b08 #5)*
- **Replace the `Use your prompt` select with the design's button and list.** The select's label is
  an action that changes from `Use your prompt` to `Replace with your prompt`. The list itself
  ("Your prompts in this session") is close to the design. *(e14f8b08 #4, 1ef27ca8 #8,
  09741861 #1)*
- **Shorten the goal hint** to the design's `Typed · saved 14:16` or `From your prompt · not
  saved`. The sentence about the 1,000-character prompt limit belongs in `What is sent`.
  *(e14f8b08 #6)*
- **Keep `+ Add a line`, `Save intent` and `Undo changes` together on the left,** and show `+ Add a
  line` and each row's `×` even when the outcome is empty. Today they are up to 900px apart, and
  appear only after typing. *(e14f8b08 #7, #8; 1ef27ca8 #9)*
- **`Save intent` rests quietly when nothing has changed.** *(e14f8b08 #19)*
- **Remove the meta row,** or reduce it to the one fact a reader needs. Before saving, a lone
  `Clear` with "Drift is measured against these…" sits under an empty form. After saving, `Saved ·
  reads from 10:57 ⌄`, `Clear`, that sentence, `About these saved words ⌄`, `Discard everything ⌄` and
  `Later directions: … ⌄` fill a row the design does not have. The one fact worth keeping visible is
  where reading starts (see Fix first, 3), at readable size. *(e14f8b08 #9, #18; 09741861 #13)*
- **Say times, not revision numbers.** "This reading read revision 2. Revision 3 is current" →
  "This reading is of your 11:05 intent; you changed it at 11:09." *(09741861 #11)*

## Later directions

- **Quote the direction, make one choice primary, and settle it beside the intent,** not in the
  Drift card. For example, under the expected outcome: "Your 11:05 message adds: … · Add as a line ·
  Make it the goal · Leave it". Two of the three choices edit the Intent card.
  *(e14f8b08 #29; 09741861 #2, #3)*
- **`Add it to my intent` should start from a rule, not the message.** It pastes the whole message
  (including "run the targeted tests, and push") into a draft line with "Write the rule, not the
  moment." underneath. *(09741861 #4)*
- **One save.** While a draft line is open, the card has the line's own `Save`, the card's `Save
  intent`, and a status that still says `Saved`. *(09741861 #5)*
- **Explain or drop `added from #7`.** Entry numbers mean nothing to a reader who has not opened
  Full activity. *(09741861 #6, e14f8b08 #15)*
- **`Use this as my goal` should start from a goal, not the message.** It pasted a 225-character
  message, including "Confirm levels.py is untouched… and update the PR body", as the goal, with no
  "write the rule" hint. *(ef258ea0 #3)*
- **After `Use this as my goal`, point at `Save intent`.** The goal becomes an unsaved edit, the
  pressed button stays enabled, `Keep my intent` turns hatched, and the save is a card away.
  *(ef258ea0 #4)*
- **Make "Keep your standing outcome lines with this goal?" answerable.** The question is right. Its
  answers, `Keep outcome lines` and `Clear outcome lines`, are small text links on the far right.
  Make them buttons beside the question. *(ef258ea0 #5)*
- **Keep the prompt control's label stable.** It flips between `Use your prompt` and `Replace with
  your prompt` as the goal's source changes. *(ef258ea0 #6)*

## Drift card before and during an analysis

- **An empty Drift card shows a heading, one sentence and `Analyze drift`.** `Pause model calls`, the
  `Live monitor` switch and its sentence, and `0 drift checks requested` are not in the design. The
  counter reports a thing that has not happened, is read twice by a screen reader, and says `0`
  while a check is running. *(e14f8b08 #10, #22; 1ef27ca8 #6)*
- **Show why Analyze is disabled next to `Save intent`,** where the fix is, not two cards down.
  *(e14f8b08 #17)*
- **Do not offer `Steer back` before there is a reading with a departure.** It appears on `Not
  checked yet`, and after a reading with no departure. *(e14f8b08 #20, 1ef27ca8 #11)*
- **Do not draw a four-step level bar with no level.** *(e14f8b08 #20)*
- **Running state replaces the heading** ("Analyzing…") instead of stacking under `Not checked yet`.
  On a re-run, keep the previous result in view, dimmed, until the new one lands.
  *(e14f8b08 #22, #36)*
- **Put `What is sent` in one place.** It appears in two cards and moves between three spots in
  the Drift card depending on state. *(e14f8b08 #11, 1ef27ca8 #18)*
- **Drop "Analyze is open: the session's last turn finished."** *(70d59c47 #5)*

## Drift result

- **State the verdict once.** Today it appears as `So far: Can't tell from what was read.`, then
  `Not enough recorded yet` over the bar, then `So far: Can't tell` again, with a stray `So far:`
  line. *(e14f8b08 #24, #41)*
- **Make the level agree with the lines.** All lines `Consistent` gave `Not enough recorded yet`
  behind a `Why not None or low ⌄` disclosure. If consistency resting only on the agent's own words
  holds the level back, say that in one sentence. Drop `Why not None or low` when there is no level.
  *(09741861 #7, e14f8b08 #25)*
- **Each line gets its own reason,** in the design's form: `Can't tell · <line>`, then why. Today
  every line is `Can't tell: what was read does not settle this · "<line>"` under a bold `Can't
  tell` heading, and evidence is a list of entry kinds (`File write [8.1]`, `not-recorded check
  [11.3]`). *(e14f8b08 #27; 1ef27ca8 #12, #13)*
- **Do not answer `Can't tell` on work the record shows.** A finished session with passing tests
  and a printed PR got `Can't tell` on every line, including "A draft PR is open". If the reading
  cannot see a command's output, say that. *(1ef27ca8 #14, e14f8b08 #47)*
- **Keep "the agent said" apart from what the record shows.** Lines marked `Consistent with what the
  agent said at [6]` rest on the agent's own message. Checks that ran are not cited.
  *(09741861 #8)*
- **Quote the claim.** `What the agent said at [13] is not shown by the record` / `Agent message
  [13]` never says what was claimed. The design: `What the agent claimed · "All green locally: 473
  tests pass" is not shown by the record`, with a reason. Drop `Claim to check at [13] · 4m ago`.
  *(e14f8b08 #43, 1ef27ca8 #15, #17)*
- **Say why a check has no result** (`not-recorded check`). This is the reason-token work in flight
  in draft PR #636. *(1ef27ca8 #13)*
- **Early in a running session, say it is early** ("3 minutes in; read again after its checks run")
  rather than giving three empty verdicts. *(e14f8b08 #28)*
- **Move "new work since" and "your intent changed" into the card header.** Today each is an amber
  box between the level and the lines, holding `Check again`, the counter and `What is sent`. The
  design's header line is `claude-sonnet-5-5 · read at 14:27`. Add "· New work since · Check again"
  there. *(e14f8b08 #30, #42; 09741861 #12)*
- **Say when a departure clears,** and why. *(e14f8b08 #48)*
- **Always offer a re-run** once a reading exists. Today the only re-run controls are `Check again`
  (after new work) and `Keep my intent and analyze` (after a direction). *(e14f8b08 #31,
  1ef27ca8 #16)*
- **Mark the header pill as provisional while running** (`Drift: Medium so far`). *(e14f8b08 #45)*
- **Quiet the footer.** `Mark as inaccurate` with its two-line explanation, and `Where the work
  went` with `[8.1]` citations, are not in the design. Put them in a menu or a collapsed footer.
  *(e14f8b08 #32, #33)*
- **Drop the "Delegated work" note from the result.** "Delegated work: 1 recorded launch; 1 of this
  session's launches has no recorded completion…" appeared on every second-round reading. It is tied
  to no line, and the reader has nothing to do with it. *(a913471f #4)*

### Mark as inaccurate

- **Disown the verdict visibly.** Marking hides the level and `Steer back`, but the line verdicts,
  their evidence and `Where the work went` stay at full weight. Dim them, or collapse them under
  "Marked inaccurate at 11:28 ⌄". *(a913471f #5)*
- **Ask what was wrong,** in one optional step (a line, the level, the evidence). Today one press
  loses what the reader knows. *(a913471f #6)*
- **Offer `Analyze again` after marking.** That is when a reader most wants a second reading.
  *(a913471f #7)*
- **Say it once, at the top, with `Undo` beside it.** Today two messages say the same thing, at the
  top and the bottom of the card. *(a913471f #8)*
- Keep: `Undo` restores everything immediately, the mark survives a reload, and the button's own
  explanation is accurate.

## Departure cards and Steer back

- **Title each departure with what happened** ("It changed PR 56's code"), not the goal sentence.
  *(e14f8b08 #39)*
- **`What` is one plain sentence,** not a list of `You said:` / `Agent said:` quotes cut mid-word.
  *(e14f8b08 #40)*
- **Steer back is its own section after the departures,** as in the design: heading, one sentence,
  the correction to paste. Today it is an inline button beside a dashed `Update intent instead`. It
  opens a monospace textarea labelled "Correction to copy" with a `705/5140` counter, instead of the
  design's "CORRECTION TO PASTE · Built from your saved intent and the reading at 14:27".
  *(e14f8b08 #44, c0cffc90 #4)*
- **Point the correction at the departure, not the last thing said.** It read "The session departed
  from my goal at 11:25, where you said "Draft PR: https://…/pull/638"". After the steer, it dated the
  departure to the steer itself (11:27). *(c0cffc90 #5, #11)*
- **Fix the joined punctuation** ("…is edited.: the session says this is done") and the stale
  counter after the correction is rebuilt. *(c0cffc90 #6, #13)*
- **Say what happened to the departure the steer addressed.** After the agent took the correction,
  the next reading found a different departure with a different reason. Nothing said the first one
  was resolved, so the reader cannot tell whether the steer worked. *(c0cffc90 #12)*
- Keep: `Copy correction` → `Copied`, and the correction's question when the agent claims something
  the record does not back ("Can you show evidence for …?"). The agent acted on the correction
  exactly.

## What the session has done: outline

- **Lead with the story, not an explanation of one.** Before the first summary the card opens with
  three sentences about what a summary is. Keep the estimate, but put it beside `Summarize`.
  *(e14f8b08 #12)*
- **Write outline phases as short sentences.** Today each is a mono line such as `8 messages with 4
  checks and files under them · 7 agent replies · 3 checks run, 1 failed as the tool reported · 1
  file written in tests/adapter/dbt_adapter (1)`, with a redundant `(5)` after "5 files". A finished
  session can be a single phase headed with the whole first prompt. *(e14f8b08 #13, #34;
  1ef27ca8 #5)*
- **Do not show a planned red test as a failure.** An agent's first, deliberately failing test
  appears in red at the top of the outline, and in the Drift card as "A check the agent ran failed".
  *(e14f8b08 #14)*
- **Drop `Starts at #1`, `Entries #1 to #13` and `Ends at #61`.** *(e14f8b08 #15)*
- **List the same failure once,** and truncate phase titles at a word boundary with an ellipsis
  ("…after Tu", "…the same foc"). *(70d59c47 #4, 3ec91051 #2)*
- **Show files written in a phase** when the agent edited files. One session's phases listed only
  checks. *(09741861 #9)*

## What the session has done: summary

- **Show the phases' bullets.** Every phase arrives and stays collapsed, while the design shows the
  opening paragraph and its bullets. If phases stay collapsed, open the one holding a departure.
  *(70d59c47 #8, #9; 3ec91051 #3)*
- **Write the opening in the design's voice:** what the agent did, with the reader as "you" or left
  out. Today it opens "The person asked the agent…". *(70d59c47 #10)*
- **Write shorter bullets.** Today's bullets are long and mechanical ("…reported not-recorded, as
  the tool reported, with the agent attributing…"). Drop the `Said:` prefix. *(70d59c47 #12, #13)*
- **Say why a line was left out in plain words:** "One line was left out because the record does not
  back it", not "it said, in the summary's own voice, that work was done or working".
  *(70d59c47 #14)*
- **Do not badge an environment failure** (a sandboxed Storybook run) as `1 failure` with the same
  weight as a real test failure. *(70d59c47 #15)*
- **Make estimate and progress agree.** `More than 94 entries … at least 2 parts, up to 10 minutes`
  became `part 1 of 3` and finished in 30 seconds. *(70d59c47 #3)*
- **Use the header format the design uses,** and do not claim `summarized at 11:06` while it is still
  summarizing. *(70d59c47 #7, 3ec91051 #9)*
- **Separate `Turn off summaries` from `Cancel`.** Turning off a feature should not be an equal
  button next to stopping one run. *(3ec91051 #1)*
- **Make `Delete summary` quiet, and confirm it** (see Fix first, 9). After deleting, say "Summary
  deleted at 11:08. Summarize writes a new one." When writing it again, note that a new summary can
  group the work differently. *(70d59c47 #16; 3ec91051 #6, #7, #8)*
- Keep: on a running session, `1 new entry since 11:29 · Update summary` is a good "keep it current"
  prompt. *(3fb351f9 #1)*

## Discard everything

- **Say what is discarded before the first press.** The open disclosure explains `Clear` ("The clear
  beside the goal and the remove beside each outcome line empty them…") and never says whether the
  reading or the summary go. *(3fb351f9 #3)*
- **Keep the two-step confirm, and say when it lapses.** "This offer lapses on its own" gives no
  time. *(3fb351f9 #4)*
- **Name what is kept: the summary and the record of checks run.** See Fix first, 15. The drift
  counter then reads `0 drift checks requested` while the result text says the record of the check
  stays. *(3fb351f9 #5, #7)*
- **Start empty after a discard.** Do not refill the goal with the drafted prompt. *(3fb351f9 #6)*
- **One result sentence, not three paragraphs,** and lift the session-history note ("holds its own
  fourteen-day copy… and --forget deletes that store") out of the middle of them.
  *(3fb351f9 #8, #9)*

## Not covered by these walks

- Codex, Gemini and other harnesses. All nine sessions were Claude Code.
- Narrow widths and keyboard-only use.
- `Pause model calls`, `Turn off summaries`, `Clear`, the `Live monitor` switch, `Update intent
  instead`, and `Update summary`, which were seen but not pressed.
