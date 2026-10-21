# A model-written summary of what a session did

DEC-28, ruled by the owner on 2026-10-19. A reader who opens a long session wants to know what the
agent did without reading every entry, and the session page answers that with a written summary.
This record says whether Compass may write and keep one, and on what terms, and names every earlier
ruling it changes. The rulings it amends live in
[Reading a session against what you asked for](design-reading-a-session.md), which links here from
its own [DEC-28 section](design-reading-a-session.md#dec-28-a-model-may-summarize-a-session-and-the-summary-is-kept).
For what each runtime file owns, see [the module map](design-runtime-architecture.md).

Until this ruling a reading's model was a selector. It saw a numbered menu the code built and
returned tokens, citations and one bounded `detail` sentence per constraint
([DEC-17](design-reading-a-session.md#dec-17-the-shape-contract); SECURITY.md, invariant 2, "A
reading carries one model-authored string"). A summary is model-authored prose about the whole
session, so it needed a ruling of its own.

## The ruling

The owner accepted every recommended answer, changed question 4 the same day, and widened that
change into a rule for every model call a reader's action starts.

1. **A model may author stored text that describes a session**, in the closed shape below. Every
   displayed string is held to the backstop: the lede, the phase titles and the bullets alike.
2. **A summary does not need a saved intent.** A reader with no goal yet is the one who most needs to
   know what happened.
3. **Summaries get a new store under the Compass home.** A summary must exist without an intent, so
   the annotation store cannot hold it. The store has
   its own SECURITY.md invariant 2 row, its own aggregate byte bound and an eviction that can never
   push out a reader's saved words, redaction on the way in and on the way out, a Delete summary
   control, and a place in `--forget`. This answer first said Discard everything must not remove
   the summary; the owner reversed that on 2026-10-21, and
   [the amendment](#amended-2026-10-21-owner-discard-everything-also-deletes-the-summary) owns the
   rule now. The store stays separate, which is what lets a summary exist without an intent.
4. **Consent is opt-out, with a notice.** Summaries have a grant of their own, separate from
   Analyze, granted by default and withdrawn only when the reader turns it off. The first summary on
   this machine shows a non-blocking notice naming what is sent and to which provider, with Turn off
   summaries beside it. Declining or turning off summaries leaves Analyze as it was. Consent,
   destination and the tool-output grant are checked again before every part of a multi-part
   summary. See [the widening](#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts)
   below, which made this the rule for Analyze too.
5. **A finished session is summarized when the reader opens it**, unless summaries are turned off,
   and every later open reads the store. A running session updates only on Update summary, reading
   only the new entries. There is no interval. Opening a session is the reader's own act, so a summary
   is a reader-requested call and not a
   [DEC-18](design-reading-a-session.md#dec-18-an-unasked-reading-is-permitted-and-gated-on-delivery-first)
   automatic reading.
6. **Each summary has whole-job ceilings** on calls, bytes sent and seconds, and summaries have a
   rolling cap of their own, so a long summary cannot use up Analyze. The numbers are set by the
   measurement of a model summary against a deterministic outline on real long sessions, and the
   owner has pre-approved accepting them there. They are not guessed here.
7. **No model-written departure headline in this milestone.** It would be a second model-authored
   field in the reading, a change to `reading.py`'s prompt and parser inside a nearly full byte
   budget, and it would invalidate the recorded parser digest. The drift card uses the constraint's
   name, the cited entries for What, and the stored `detail` for Why.

The owner also reversed DEC-27's two-column layout for this milestone; see
[the layout reversal](#the-layout-reversal).

### The widening: opt-out with a notice for every call a reader starts

The owner's first answer to question 4 made summaries opt-out and kept Analyze opt-in. The amended
ruling of the same day supersedes that: opt-out with a notice is the rule for **every model call a
reader's action starts**.

- The call runs without a prior question. The first call of each kind on this machine shows a
  non-blocking notice naming what is sent (the words, and tool output where it is included) and to
  which provider and destination, with a one-press off switch beside it.
- It covers session summaries, reader-requested Analyze drift (the consent step goes), Claude Code
  tool output on a reading (included by default and named in the notice), and Codex goal summaries
  (on by default).
- It does not cover unasked drift checks. No reader action starts them, so they stay off by default
  behind `--unasked-readings` and DEC-18's preconditions.
- `--no-observer-model` still refuses every model call. Pause model calls and Turn off summaries
  remain, and an answer of off already stored is kept: a reader who paused model calls is not opted
  back in by the upgrade.
- A changed destination shows the notice again, naming the new destination, rather than a blocking
  Allow.
- `--allow-tool-output` and `--observer-model` become accepted no-ops for one release.
- Summaries keep their own grant, cap and ceilings. Analyze's rolling cap is separate and unchanged
  at 100 attempts per 24 hours.

The product promise still holds, in the owner's words "nothing leaves your machine that you cannot
switch off", because the off switch is one press from the card and one flag at startup. The promise
map's wording for this changes with the work that ships it, not in this record.

### Amended 2026-10-19: Pause model calls, with the summaries switch nested under it

The owner renamed "Turn off readings" to
**Pause model calls**, with **Resume model calls** as its opposite. This supersedes the
earlier wording here and in SECURITY.md. Beside the control the page says:
"Compass stops sending session text to Claude Code or Codex, so it uses none of your tokens,
and stays paused until you resume."

- **Paused:** Analyze drift, goal summaries and session summaries send nothing and refuse
  with `model-calls-paused`. A running summary stops at its next part; a call already
  spawned is cancelled and its reply cannot publish.
- **Resumed:** each kind of call runs on the reader's action, showing its one-time notice
  the first time. Resume changes permission only; it starts no Analyze or summary.
- **Turn off summaries:** stops only session summaries. While model calls are paused its
  control stays visible and disabled, with "Model calls are paused" beside it. Neither
  pausing nor resuming writes the summary answer or its generation. After Resume model
  calls, summaries are exactly as the reader left them.
- **Startup refusal:** `--no-observer-model` overrides both switches and refuses every call.
- **Upgrade:** the SQLite filename, tables, columns and stored off answer are unchanged.
  An off answer saved by an earlier build remains paused after upgrading. Only the
  internal reason token changes to `model-calls-paused`.

The master pause still posts `{consent: "off", press: true, observer_model: 1}`.
Resume posts the same guard fields with `consent: "on"`, without a session or provider.
It clears the stored pause (`reading_policy.resume`) and writes no Allow, so it grants no Codex
unasked permission. The unasked lane still needs DEC-18's flag and preconditions, plus that explicit
grant for Codex. Claude Code resumes under its existing acceptance when the flag is on.
Under the startup refusal Resume answers `run-disabled` and writes nothing, so the stored
pause outlives a run started with `--no-observer-model`.
The earlier explicit `allow: true` request remains accepted for older pages, including
its destination checks. Summary presses keep `{consent: "off"}` and `{consent: "on"}`;
while paused they answer 403 without changing the saved summary answer.

### Amended 2026-10-21 (owner): Discard everything also deletes the summary

The owner reversed the part of answer 3 that kept the summary through Discard everything. A reader
who discards what they asked of a session, then finds a model's account of that session still
standing under it, has been told the discard was total when it was not. Walk records of a
session with an intent, a reading and a summary found the summary surviving with no word that it
had been kept.

- The discard now removes every revision of the session's saved words, any reading of
  them, and the session's stored summary. A summary job still running is stopped first, exactly as
  Delete summary stops it, so a reply returning afterwards cannot publish the text back. The job's
  reason is `discarded`, which reads as cancelled. Only that session's summary goes; no other
  session's does.
- It keeps the record that a check ran, which bounds how often one may run; the discard
  record itself (when, and no text); and session history, which holds its own fourteen-day copy of
  the goal and each outcome line where it is recording, and which `--forget` deletes. The page says
  all of this before the second press and once after it.
- The summary is deleted only on a clear that landed over words that existed. A request
  over a session nothing was typed against, or one already discarded, deleted no words and leaves
  the summary alone: a summary does not depend on a saved intent, and a hand-made request must not
  take it. The reply carries `summary`: `deleted`, `absent` (nothing was stored), `stopped` (nothing was stored and a job was running, which the
  discard stopped; amended 2026-10-21), a refusal token from the store (`unwritable`, `unavailable`), or `untouched` where the
  press owed it nothing. The field is always present, so one key has one meaning.
- Whether words existed is decided by the annotation store under its lock, on the revisions it
  finds there, and not on the dashboard's cached copy, which a save from another tab can outrun. The
  reply carries `removed`, the count of revisions that call took (null on any arm that is not a
  discard, so zero is a discard that found nothing). A save that lands before the lock is a revision
  the discard takes too, and one that lands after is a new revision over the discard record; neither
  leaves the summary standing under words that went.
- The page's sentence follows the summary's own answer, one sentence each: `deleted` says the summary
  went; `absent` says no summary was stored and does not claim one went; `stopped` says that and that the one
  being written was stopped; a `refused` write reads as `unwritable`, and a token the page does not know says
  Compass could not tell, so a summary may still be stored, and claims neither that it went nor that it stayed; `unwritable` says it could
  not be deleted and names Delete summary; `unavailable` says the store could not be read, so whether
  one exists is unknown, and names no remedy. Where the old summary is gone or never was, the sentence
  adds that opening a finished session again writes a new one unless summaries are turned off (rule 5
  above). A `removed` of zero says nothing was discarded.
- A summary that cannot be deleted leaves the annotation discarded and the summary standing.
  The page then says so and names Delete summary as the way to finish, rather than the categorical
  sentence. When the departure store also failed to withdraw, that sentence leads, because it stops
  a reader believing quotations went, and the summary's own outcome follows it in the words that case uses
  (amended 2026-10-21: the summary used to go unsaid there).
- The form starts empty. A discarded session's goal box is not refilled with the drafted first
  prompt: one stray Save intent would bring back an intent the reader had just deleted. The prompt
  stays one press away under Use your prompt.
- The result is one sentence. The record of the discard waits for the result's thirty seconds to lapse
  rather than standing beside it.
- The counter: the drift card counts only checks the store counted, and says nothing at zero.
  A discard record keeps no count, so it reads as no counter, not as zero checks beside a sentence
  that says the check record stays.

The three places that stated the old rule follow it: answer 3 above, the alternatives paragraph
below, and the store section's "Discard everything leaves it alone", which now reads that it deletes the discarded session's entry ([the store contract](#store-contract)).

Delete summary is two presses. The first arms the control and says what goes (this machine's
copy of the summary) and what does not (anything else), that Summarize writes a new one by sending
the session to the model again, that nothing has been deleted yet, and that the offer lapses in
the cue window, 30 seconds. The armed discard and this lapse both read it from one value: the
server's `CUE_WINDOW_SECONDS` for the discard's sentence, the page's `CUE_TTL_MS` for Delete summary,
and a vocabulary fixture test fails if they part. Keep summary and Escape take it back, and a press inside the 1.2 second dwell after the
arm, or a double click, is another arm and never the deletion, as for Discard everything. The
control sits quietly after What is sent. The second press shows its pending state, and the card
then says "Summary deleted at 11:08. Summarize writes a new one." until a summary starts again, so
a card that returns to its first-visit state does not read as though no summary had existed.

### The layout reversal

[DEC-27](design-reading-a-session.md#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result),
as amended by the owner on 2026-10-12, made the session page two columns from 1101px: activity on
the left, the Intent and drift panel on the right. The owner reversed that amendment for this
milestone on 2026-10-19. The page becomes one column, top to bottom: the header, the answer block
when the session needs input, the Intent card, the What the session has done card, the Drift card,
and a collapsed Full activity section. The session page's More disclosure is retired, with every
control, sentence and limit in it given a new home, so DEC-27's principle that a privacy promise or
an honest limit moves and is never deleted still holds.

### Phases fold, and a citation shows its entry

The owner and design lead settled on 2026-10-20 that What the session has done is the high-level
play-by-play, and the page order puts it after the Drift card. The lede stays open. Each phase is an
accordion, which [the 2026-10-21 amendment](#amended-2026-10-21-the-card-reads-like-the-design) opens
by default. What a reader should know about a phase sits on its heading, outside
the fold and right-aligned as pills: one for each departure the phase holds evidence for, which goes to
that card, and a red count of its failed test runs. A phase with nothing to say has no pill. The open
state is the reader's own, kept in the disclosure store under the session and the phase's place.

A citation is a bracketed number. Hovering or focusing it shows the cited entry's own words in a
card with "See in context of the session", which closes the card and lands on the row in Full
activity. Pressing the number opens the card and does not scroll, because a press that moved the
reader across the page every time read as disconnected. Compass's own sentences that name an entry,
such as "Departure evidence at [41]" and the list of entries an analysis read, draw the number the same
way. A model's own words keep every `#` they were written with.

## What this amends, by name

| Earlier ruling | What changes | What stays |
| -- | -- | -- |
| [DEC-15b](design-reading-a-session.md#dec-15b-an-assessment-may-be-stored): "No new store, and no field admitted by implication." | A new summary store is admitted, by name, for summaries only. | Every summary field is still named and admitted; nothing is admitted by implication. The annotation store still holds readings. |
| [DEC-18](design-reading-a-session.md#dec-18-an-unasked-reading-is-permitted-and-gated-on-delivery-first) | Not engaged. A summary made on open is reader-requested. | The unasked lane, its preconditions and its default off. |
| [DEC-27](design-reading-a-session.md#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result), the owner's 2026-10-12 layout amendment | Reversed for this milestone: one column, More retired. | The signed table's principle that a promise or limit moves and is never deleted. |
| [SECURITY.md, Light harness usage](../SECURITY.md#light-harness-usage-asking-a-harness-a-bounded-question), "Opt-in, and off until answered" | Becomes opt-out with a notice for calls a reader's action starts. | The operator's own harness, redaction before it leaves, one bounded question, visible spend, the off switches, and "Future harness callers need their own entry", which [Session summary calls](../SECURITY.md#session-summary-calls) answers. |
| [Amended 2026-10-01: the first press is a consent step](design-reading-a-session.md#amended-2026-10-01-the-first-press-is-a-consent-step) | Superseded: the first press runs and shows the notice. | "Turn off readings" (renamed Pause model calls on 2026-10-19) and its effect. |
| [Amended 2026-10-02 (owner): the Allow is bound to where the words go](design-reading-a-session.md#amended-2026-10-02-owner-the-allow-is-bound-to-where-the-words-go) | Superseded as a blocking step: a changed destination shows the notice again. | Detecting a change, and what cannot be detected while a destination is unnamed. A refusal still holds whatever the destination. |

The rulings that the consent change touches in passing, DEC-21 item 1 and its 2026-09-24
"Analyze drift and Allow and analyze" amendment, and DEC-23 item 7's fresh Allow for tool output,
are superseded for the same parts and for the same reason. Their other items stand.

## Alternatives rejected

- **A summary-only record in the annotation store.** It looked cheap because the store already has a
  lock, redaction and an owner-only write. It costs too much. The store's loader requires revisions,
  so a record with no saved intent needs a second record kind the loader must learn, and an older
  build that does not know it would refuse or drop it. A summary must also exist with no saved
  intent, which the annotation store's entries cannot express, so deleting one with the other is a
  step the discard takes over two stores and not a property of one. And the store's
  bound counts sessions and revisions, so a large set of summaries would evict a reader's saved
  words, which the ruling forbids.
- **Reusing the reading's `CONTENT_VERSION`.** Bumping it for summaries would ask every reader again
  about Analyze for a change that is not Analyze's. Summaries have their own grant instead.
- **A model-written departure headline.** Rejected for this milestone, for the reasons in answer 7.
- **Updating a running session's summary on an interval.** A timer spends the reader's capacity
  without an act of theirs, which would make it the automatic evaluation DEC-18 gates. Update summary
  is the reader's act.
- **Always pressing to summarize a finished session.** Opening the session is already the reader's
  act, and a second press would put a wait in front of the thing they opened the session to read. A
  later open reads the store and spends nothing.

## The closed summary shape

A summary is a lede and a list of phases. A phase has a title and a list of bullets. A bullet has
its text, a kind and its citations. Nothing else in a summary is model prose. The title belongs to
the phase, and a bullet has no title of its own: the ruling's "phases with titled bullets" reads
against question 1 of the body it accepted, which holds "the lede, phase titles and bullets alike"
to the backstop and gives a bullet no other field.

- **Citations.** Every bullet cites at least one entry by fact id. A bullet that cites none is
  withheld.
- **Kind, set by the code.** The model may propose a kind, and the code overrides it from what the
  citations are. `failed` when one is a failed check; otherwise `did` when one is a tool call, a
  check or a file write; otherwise `asked` when any are the person's words; otherwise `said` when all
  are the agent's words. A bullet citing only person and agent words is `asked`: in all five
  measured cases the person was deciding on the agent's proposal. Relayed text is neither the
  person's words nor the agent's, so a bullet whose citations are relayed text alone, or relayed
  text and agent words with no person entry, has no kind it may claim and is withheld as a
  `shape_fault`; it never gets the speech licence `said` carries.
- **No completion claims in the summary's own voice.** The lede, titles and bullets may report
  what a named speaker said, but may not themselves state that work is fixed, done, working or
  verified. A check's result is quoted only as the tool's report, in
  [DEC-23 item 8's](design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work)
  wording ("as the tool reported"). A passed check does not show the requested work was delivered.
  The [ruled amendment](#amended-2026-10-19-owner-the-summarys-own-voice)
  defines attribution, names, tracker states and the conditions that still withhold a string.
- **Withheld in place.** A bullet that breaks a rule is withheld, and the place it held says so. It
  is not silently dropped.
- **Gaps.** A part of the session that could not be summarized is shown as a gap, not skipped.
- **Redaction.** Every string is redacted on the way into the store and again on the way out,
  because any local process can rewrite the file.

### The known limit: relevance is not checked

The code can check that a citation names a real entry and that its kind matches what the entry is.
It cannot check that the cited entry is relevant to the sentence that cites it. A bullet can cite a
real check while describing something else, and nothing in the shape catches that. The measurement
counts wrong citations, and the page must not present a citation as proof of the sentence beside it.

## What a summary can read, by harness

What a summary can cite is what Compass can page through in a session's record today. These are the
harnesses with that record, from `record_pages.HARNESSES` and `AGENT_MESSAGE_HARNESSES` (held equal
in `project_context` and `reading_route`).

| Harness | Paged record | The person's words | The agent's words | Checks and files |
| -- | -- | -- | -- | -- |
| Claude Code | Yes | Yes | Yes | Yes, as [DEC-23](design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) admits them |
| Codex | Yes | Yes | No: the builder does not admit Codex assistant records, and the read says so | From its bounded record sources |
| Pi and every other harness | No | Not paged | Not paged | Not paged |

A summary of a Codex session therefore lacks the agent's replies and must say so. Pi and the other
harnesses have no paged record; the ruling is silent on whether a summary is offered for them, and
until a later change adds their record they say they cannot be summarized.

## What is built where

| Part | Where |
| -- | -- |
| The notice, the default-on grants and the off switches for every reader-started call | `reading_policy.py`, `reading_route.py` and the session page's "What is sent" popover |
| The in-order, paged read with fact ids and fingerprints | `session_source.py`, reusing `record_pages.py` message facts and `project_context.py` tool classification |
| The deterministic outline | `session_outline.py`, served on `/api/project-context` as `sources.outline` for a focused session only |
| The What the session has done card and the outline drawn in it | `frontend/src/sessions/WhatItDid.tsx` and `outline.ts`, parsing `sources.outline` in `frontend/src/api/outline.ts` |
| The summary drawn in that card, its controls, its notice and the departure marks | `frontend/src/sessions/SummaryParts.tsx`, `summary.ts`, `summaryState.ts`, `summaryActions.ts`, `summaryHeld.ts` and `summaryMarks.ts`, parsing `sources.summary` and the board's `summaries` block in `frontend/src/api/summary.ts` |
| The summary producer and its closed-shape parser | `session_summary.py` |
| The multi-part job, its ceilings and its own rolling cap | `summary_jobs.py`, `session_summary.py`, `reading_policy.py` and `config.py` |
| The summary store, Delete summary and `--forget` | `summary_store.py`, `summary_jobs.py`, `http_api.py` and `cli.py` |
| The one-column page and the retired More | `frontend/src/sessions/SessionDetail.tsx` |
| The ceilings' numbers | The measurement of a model summary against a deterministic outline |

## Measurement and ceilings

Measured on 2026-10-19 on the owner's machine, to set the numbers answer 6 leaves open and to
decide whether the multi-part summary is worth building. Nothing from the sessions is committed:
this section holds counts, timings and the method only. The scripts, the outputs and the prompts
stayed outside the repository.

### Method

Four real Claude Code sessions of this repository's own work were summarized, none of them
running at the time. A is a milestone burndown that ran for about 14 hours and holds a pasted
correction and a person's interrupt. B is a medium session ending in a major release. C has a
known steering moment: the person rejected a tool call, interrupted and restated the request with
one item dropped. D is a small session driven by a coordinating agent rather than a person.

Each record was cut into numbered entries: the person's words (`asked`), the agent's text
(`said`), each tool call by name and main argument (`did`), and each tool error (`failed`).
Successful tool output was left out. Every entry was redacted with `records.redact_secrets` and
then clipped. Two products were made from those entries:

- **The outline**, made by code: one block at each person message, with counts of what followed.
- **The summary**, made by the model: the entries cut into contiguous windows of at most 16 KiB of
  record text, one call per window asking for phases with titled bullets, a proposed kind and
  citations by entry number, then one lede call over the phase titles and the person's entries,
  bounded to 16 KiB. The calls ran one after another through `observer.claude_exec`, with the
  reader's argv, model (`claude-sonnet-5-5`, effort high), scrubbed environment and 180-second
  timeout. Only the one-line system prompt was changed, from assessing against goals to
  summarizing. A call that returned no output was retried once.

Accuracy was judged by hand against the entries. A second, independent judge (Codex,
`gpt-6.1-sol`, reasoning effort high, read-only sandbox) checked 15 of session A's sampled
bullets against the same cited entries. The CLI's text output reports no token counts, so model
capacity is given in bytes. Bytes divided by four suggests about 175,000 input tokens and 29,000
output tokens for the whole run, but that figure was estimated, not measured.

### Cost and latency

| Session | Transcript | Lines | Entries | Span | Windows | Calls | Calls with no output | Bytes sent | Bytes back | Wall time |
| -- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| A | 45.0 MiB | 12,805 | 2,266 | 849 min | 30 | 36 | 6 | 541,407 | 87,999 | 307 s |
| B | 4.3 MiB | 2,296 | 370 | 250 min | 5 | 6 | 0 | 91,945 | 16,500 | 51 s |
| C | 2.9 MiB | 1,172 | 204 | 72 min | 3 | 4 | 0 | 49,173 | 10,265 | 28 s |
| D | 0.98 MiB | 256 | 47 | 18 min | 1 | 3 | 1 | 17,810 | 2,939 | 12 s |
| All | | | | | 39 | 49 | 7 | 700,335 | 117,703 | 398 s |

- A window call took a median of 8.9 s, with a p90 of 10.1 s and a maximum of 12.3 s, across 38
  calls. A lede call took 2.0 to 2.8 s. No call came near the 180-second timeout.
- The largest prompt was 17,714 bytes, which is 16 KiB of record text plus the instructions. The
  largest reply was 3,839 bytes.
- The 45 MiB burndown took 5.1 minutes end to end, which is under the owner's 10-minute estimate.
  A cut was not needed for it.
- Seven of the 49 calls ended with status `unstopped` and no output after 2 to 11 seconds, so they
  probably spent capacity. Each was retried once. One of session A's windows failed twice and
  became a gap of 86 entries. The cause was not investigated. A job must treat a call with no
  output as a spent call and a failed part.

### Accuracy

| | A | B | C | D |
| -- | --: | --: | --: | --: |
| Phases, bullets | 109, 419 | 20, 79 | 12, 49 | 3, 12 |
| Outline blocks with no cited entry | 2 of 46 | 0 of 12 | 0 of 9 | 0 of 3 |
| Parts lost to failed calls (shown as a gap) | 1 of 30 | 0 | 0 | 0 |
| Completion statements the cited entries do not back | 20 | 6 | 2 | 0 |
| Wrong or irrelevant citations, in a sample | 0 of 25 | 0 of 25 | 0 of 25 | 0 of 12 |
| Partly supported bullets, same sample | 1 of 25 | 1 of 25 | 0 of 25 | 0 of 12 |
| Bullets whose kind the code overrides | 80 | 14 | 5 | 2 |
| Bullets citing only the person's and the agent's words | 3 | 1 | 1 | 0 |

- **Omitted phases.** The two uncovered blocks in A were a short merge request and an
  "update main" request. The model returned an empty, untitled phase at the end of that window.
  A also had three phases with no title, two of them with no bullets. The parser must withhold an
  untitled phase as a shape fault.
- **Completion statements.** A plain word list (fixed, done, complete, working, verified, passed,
  merged, green and their forms) matched 138 of the 707 displayed strings. Of those, 28 were
  completion claims in the summary's own voice whose cited entries show only that a command was
  issued or an edit made. These are the counts above, and they include two phase titles. 66 were
  attributed speech, such as "the agent said …" or "as the tool reported", and 3 were backed by
  the output a cited tool error carried. The other 41 used the word for something else, such as a
  branch name, a tracker state or the person's own words. A backstop that withholds every match
  would withhold about one string in five, so the backstop has to tell the summary's own voice
  from attributed speech. A plain word list cannot do that.
- **Citations.** No bullet across all 559 lacked a citation, cited an entry that does not exist,
  or cited outside its window. Hand judging found no wrong citation in 87 sampled bullets. The
  partial ones state a detail the cited entries do not show.
- **Kinds.** The model's own kind differed from the code-set kind on 101 of 559 bullets. In 79 of
  them the model said `said` where the bullet also cites a tool call. The independent judge chose
  the code-set kind on 15 of 15 bullets, and the model's own kind on 12 of them. The five bullets
  that cite only the person's and the agent's words were each a person deciding on the agent's
  proposal.
- **Independent judge.** It agreed with the hand judging on wrong citations (none, 15 of 15) and on
  unbacked completion statements (13 of 15). It was stricter on support, rating 7 of 15 bullets
  partly supported against 1 by hand, and agreed on that rating for 9 of 15. Four of its seven
  partial ratings were for a cited command or browser action whose outcome is not in the record,
  because successful tool output was left out.
- **Departures.** None of the four ledes mentions a departure or a correction, although A and C
  each had one. In both sessions a bullet carried the moment.

### What a reader can find, outline against summary

- **The goal.** The outline is as fast or faster. The first block's head is the person's own
  words, and every later instruction heads its own block. The summary's lede restated the goal
  correctly in all four sessions, but as a paraphrase. In A, 10 of the outline's 46 blocks were
  messages from other agents or the text of a resumed conversation, shown as though the person had
  written them. The summary named them correctly, but the record as cut here kinds them as the
  person's, so the outline needs the fix in recommendation 3 as much as the summary does.
- **The work.** The summary is much faster. An outline block is a person's words and a count, and
  A's largest block covered 177 entries, so the work under it was invisible. The summary names that
  work in titled phases with citations a reader can follow. For B to D, the phases matched the
  record's actual steps in order.
- **The departure.** Neither surfaced it unprompted. In A and C the summary did carry the moment as
  a cited bullet, either as a `failed` bullet for the rejected tool call or as an `asked` bullet
  for the pasted correction, so a reader who scans the phases finds it. In the outline, the
  departure is visible only if the person's words make it so.
- **A correction.** The outline is better for the person's side. The restated request is its own
  block head next to the original, and the change shows by comparison. The summary is better for
  what the agent did about it. It recorded C's rejected call and restated request, and A's
  investigation after the pasted correction, but did not name the item the person dropped in C.

### Proposed ceilings

The owner pre-approved accepting the ceilings this measurement proposes. The producer now records
them in `config.py`; `summary_jobs` wires the per-call timeout and rolling admission.

| Ceiling | Value | Basis |
| -- | --: | -- |
| Window | 16 KiB of redacted record text | 17.7 KB prompts answered in 12.3 s or less, and 30 windows covered the largest session measured |
| Windows per summary | 32 | The 45 MiB burndown needed 30 |
| Calls per summary | 37 | 32 windows, 1 lede and 4 retries. The burndown used 36 |
| Bytes sent per summary | 768 KiB | 37 calls at the measured maximum prompt is about 640 KiB. The burndown sent 529 KiB |
| Seconds per summary | 600 | 37 calls at the measured maximum is about 455 s. The burndown took 307 s |
| Per-call timeout | 180 s, unchanged | The slowest call took 12.3 s |
| Summary rolling cap | 200 calls per 24 hours | Five summaries the size of the largest measured, or about 33 of the medium one. Separate from Analyze's 100 attempts |

- **Cutting rule.** Keep windows contiguous. When the next entry would overflow the window, cut
  before the last person message in the window's back half, or at the overflow when there is none.
  This kept a person's instruction and the work after it in one window.
- **Longer sessions.** A session that needs more than 32 windows is summarized from its newest 32
  windows. The summary states the entry it starts at, and the part before it shows as a gap that
  points to the outline. Update summary on a running session reads only windows that end after
  the stored summary, plus one new lede, under the same ceilings.
- **Retries.** A call with no output is retried once, within the call ceiling. A second failure
  leaves a gap. The job stops at the first ceiling it reaches, and every window after it shows as a
  gap.

### Recommendation

Build the multi-part summary as designed, sequential, with these changes:

1. **Hold the backstop to the summary's own voice.** Withhold a completion word in the summary's
   own voice. Admit it when it is attributed to the agent or the person, or quoted as the tool's
   report. A word list alone would withhold one string in five, and four in five of those
   withholdings would be wrong.
2. **Add a bounded outcome to each tool call in the record**, such as an exit status and a short
   prefix of the output, inside the same window budget. Most partly supported bullets and most
   unbacked completion statements cited a command whose outcome the model never saw.
3. **Kind the person's entries by who wrote them.** Messages from other agents and the text of a
   resumed conversation are not the person's words. Without this, the code sets `asked` from text
   the person did not write, and the outline heads blocks with it.
4. **Give a bullet that cites only the person's and the agent's words the kind `asked`.** In every
   measured case the person was deciding on what the agent proposed.
5. **Add a lede rule for the departure.** If the reader is meant to see a departure or a correction
   in the lede, the lede prompt must ask for it, because no measured lede mentioned one.

Keep the outline as the free view, and as the place every gap points to. Stopping at the outline
is not recommended. It was no help with the work in long sessions, which is what a reader opening
one most wants to know.

## Producer contract

`session_summary.summarize(entries, coverage, harness, *, config, model, clock)` takes a sequence
of `SourceEntry`, its `SourceCoverage`, a harness name, frozen runtime configuration, a callable
`model(prompt, *, output_cap_bytes) -> (text, status)`, and a monotonic clock. Only `claude` is
supported. Every other harness returns `unsupported`, reason `harness_not_supported`, without a
model call. This does not widen the source's admission rules for Codex or any other harness.

The producer reads no transcript and owns no store, cache, thread or subprocess. The caller keeps
the frozen result. The production seam is **not** the reading policy's `GuardedModel`: its
`__call__` always calls `reading_policy.reserve()`, which charges Analyze's one rolling ledger and
refuses on Analyze's off switch and daily cap, both of which
[Session summary calls](../SECURITY.md#session-summary-calls) forbids a summary to touch. The
summary's own guard, `summary_jobs.GuardedSummaryModel`, stands in front of the model instead: its
own grant and off check, its own ledger for `session_summary_rolling_cap`, and the consent,
destination and tool-output checks again before every part. The existing Claude reading invocation fixes its own system prompt, so
its exec path needs a system-prompt parameter, carrying `session_summary.SYSTEM_PROMPT` and that
prompt's provenance digest in the stored model stamp. `summary_jobs` wires
`session_summary_call_timeout` through the exec path. The [store contract](#store-contract)
names the separate storage and delete endpoint.

### Menu, windows and prompts

Entries receive numbers 1 through N in source order for this job. The producer alone holds their
number-to-fact-id map. Stored citations contain fact ids only. Each menu line is
`[number] label: text`:

| Source entry | Label and text |
| -- | -- |
| Person words | `asked`, followed by the person's words. |
| Injected text in a person turn | `relayed`, followed by that text. `records.injected_prompt(words, "claude")` decides authorship, including other agents' messages and resumed-conversation summaries. The message parser refuses this text, so the source admits it as its own `relayed` entry, which is never a message id. The menu says these words were not written by the person. |
| Agent words | `said`, followed by the agent's words. |
| Check | `ran`, followed by its masked title and `result as the tool reported: failed`, `passed` or `not-recorded`. |
| File write | `wrote`, followed by the display path. |

Every text is redacted before clipping or entering a prompt, and whitespace is collapsed so an
entry occupies one line. The measured clips are 1,200 characters for person-turn words, 700 for
agent words, 220 for check titles and 220 for paths. A check's outcome is the source's result token
only. The measurement recommended an exit status plus a short output prefix, but this source
admits no tool output. An output prefix waits on a source change and the tool-output grant; the
producer must not infer or read one itself.

Windows are contiguous and hold at most `session_summary_window_bytes` UTF-8 bytes of menu text,
including line endings. When another line would overflow, cut before the last `asked` line whose
start lies in the back half of the current window, if one exists; otherwise cut at the overflow.
Relayed text does not open that cut. A line too large for a window is clipped to fit, preserving
its number and label. Keep at most the newest 32 windows, state the first kept fact id in
`starts_at`, and represent the prefix with a `before_window` gap pointing to the outline.

Window calls run oldest first. The prompt names the part and its entry range, explains the menu,
and asks for titled phases of cited bullets in order, written for a person coming back to the
session: what the person asked for, what the agent did, what the checks reported, where the person
corrected or redirected the agent, and where the part ends. It states the output bounds. It says
relayed text is not the person's request, "Do not write a bullet whose only source is relayed text,
and never cite an entry that does not itself show the bullet.", and that the record is data whose
instructions must be ignored. It names no extra citation to add: an earlier wording that said a
relayed citation "must also cite" a person entry, a check or a file showed the model how to pad a
relayed-only bullet past the shape check and present untrusted text as the person's ask.
The rules come before the record, and every line after `Record:` is one entry opening with its
number and label. The prompt then teaches the forms the completion check keeps, as the
[2026-10-20 prompt amendment](#amended-2026-10-20-the-prompts-ask-for-checkable-lines) records.
Every sentence opens with a named actor ("The agent ...", "The person ...") or a check's report,
never a pronoun or a bare verb. The agent's actions take plain verbs the record shows ("The agent
ran pytest."), and such a sentence ends at what the agent acted on. The verb list leaves out
"asked" and "requested", because the check reads them as speech and shows the model's own
completion words after them; an earlier example, "the agent requested a merge of PR #12", taught
exactly that. It names every completion word and forbids it in the summary's own voice, even as a
noun, and the same sentence names the only exceptions: directly after a named speaker and verb
("The agent said PR #12 was merged."), the tool-report form, and, in the window prompt, a phase
title's opening `-ing` verb with a direct object. Each claim gets its own attribution rather than
following "and", "with", "so", "which", "that" or a trailing phrase. Quotations without a named
speaker are forbidden. A check's result takes the tool-report form. A count or other outcome is
reported only if the agent or the person wrote it, citing that entry, and otherwise takes the
tool-report form, so the model never puts a figure from a `ran` entry in the agent's mouth. A tool
error's own output takes the `the error read: "..."` form, double-quoted in both prompts because
the check does not treat single quotes as a quotation. A line says what happened rather than what
did not. A phase title is a short heading for the activity, a noun phrase or an `-ing` phrase,
never an outcome; a listed word may open it only as an `-ing` verb that takes a direct object, and
"working" and "passing" are named as words to avoid, since the check withholds "Working on the
parser" and "Passing the intent prop". The system prompt, and so the stored model stamp, is unchanged.
Earlier windows contribute only the newest finished
phase titles that fit within one sixteenth of a window, including the disclaimer that they are
context, not evidence and must not be cited. Earlier bullets and entries never enter this context.

After the windows, one lede call receives only menu lines cited by surviving phases. Selection
prefers the person's entries, then other entries in order, within one window's byte allowance;
the selected lines retain source order and their original numbers. The prompt asks for two plain
sentences within the lede character bound. The first says what the agent did, with the agent as
its subject; the person's goal is not asked for. The second says where those entries end, as they
report it, naming any correction or redirection they show. It carries the window prompt's forms except the title rule.
It receives no phase prose or titles. Its citations must name entries actually given to it. A failed lede leaves `lede: null`
and `lede_reason`, preserving the phases.

### Replies, kinds and withheld text

A window reply is `{"phases":[{"title":"...","bullets":[{"text":"...","kind":"...","cites":[1]}]}]}`.
A lede reply is `{"lede":"...","cites":[1]}`. Unknown keys are dropped. A surrounding triple
backtick fence, including a `json` fence, is removed. JSON decoding runs first. If it fails and
the reply opens with an object, complete members and complete elements of the phases array are
salvaged up to the first incomplete element. Prose around JSON is unreadable: salvage applies only
to a truncated object, and a complete object followed by any other text is `no_valid_reply`. An
incomplete phase is never salvaged as a partial phase.

A phase needs a nonempty title and at least one shaped bullet with a resolved citation. Missing
titles and empty phases are withheld as shape faults, counted in `withheld_phases.shape_fault`.
A bullet needs nonempty
text; a row that is not an object with nonempty string text keeps its place, and its bullet slot,
as a `shape_fault` marker. Its citations accept integers only, refuse booleans, deduplicate, and drop numbers outside
that window. A bullet left with no citations keeps its place as a `no_citation` marker beside
the phase's cited bullets. A phase with no cited bullet is a shape fault. A window
with no shaped phase is a `no_valid_reply` gap; other windows survive.

The code overrides the model's kind, recording `kind_overridden` on every bullet. Priority is
`failed` for a cited failed check, then `did` for a check or file write, then `asked` if any cited
words are the person's, then `said` only when every citation is the agent's words. The `asked`
case includes person words plus agent or relayed words, as decided by the measurement. Any other
mix (relayed text alone, or relayed text with agent words) is withheld as a `shape_fault`. Citations trimmed by the citation bound
no longer contribute to the kind.

Every displayed string is redacted and checked on its whole text before any character cap.
A failing string becomes `{"withheld":true,"reason":"completion_claim"}` with no text.
A withheld title keeps its bullets. Text without a citation uses reason `no_citation`.
Admitted long text ends with an ellipsis and carries `cut`; if the cut creates an unsafe claim
or leaves no text, it becomes a `too_long_cut` marker instead. Phase, bullet and citation list
cuts report how many were dropped. A cut reply is marked on its block.

### Amended 2026-10-20 (owner): withheld lines are shown collapsed

The page draws a run of withheld bullets in a phase as one muted line: how many were hidden, why,
in the reason table's words, and the range of entries they cite ("2 lines hidden: they cited no
entry. Entries #50.1 to #55."; the 2026-10-21 amendment words a withheld completion claim as "2 lines were
left out because the record does not back them"). Each hidden
line's own reason and citations stay one keyboard-reachable press away under "Why each was
hidden". A kept bullet between two runs splits them. No result label leads a hidden line: the page
once drew "Failed as the tool reported: Withheld: ...". A withheld phase title keeps its own muted
marker. A withheld line, title and phase say "Left out:" with what was wrong in plain words (no citation, too long to
show whole, not in a form Compass accepts, or the record not backing a completion claim), and an opening summary
says "this opening summary" where a bullet says "this line"; the jargon of the rule names is gone from every
sentence. What the producer withholds, and why, is unchanged. The owner did not choose to merge
departures that share evidence into one card.

The page also names the speaker a bullet's words name. An `asked` bullet whose text opens with
"The agent said" reads as written, not "You said: The agent said ...", and a `said` bullet that
names the person reads "The agent said you asked ...". The code-set kind and its citations are
unchanged. (This once drew a "Said:" label; the 2026-10-21 amendment removed it.)

### Amended 2026-10-21: the card reads like the design

The design review of finished and running summaries found the card accurate and hard to read. The
page and the prompts changed as follows. The producer's check, its clause code, the kinds, the
ceilings and every earlier ruling are unchanged.

- **The Full activity limit is said once.** A citation to an earlier check or file has no entry in
  Full activity, so no chip can open it. The page counted these after the opening and most bullets.
  It now counts the distinct ids across the whole summary and says it in one line at the foot of
  the card, before the relevance sentence. A chip still draws wherever the page can open one.
- **Phases arrive open.** Each phase opens the first time its key is drawn, so a reader sees the
  opening and its bullets with no press, and each phase appears open as a part lands. A phase the
  reader closes stays closed through every later board, because the write that opens it is the
  disclosure store's own and the reader's close is the next one. [The reader-state row](design-reader-state.md#the-inventory)
  owns this. A phase that holds a departure is open for the same reason.
- **The opening describes what the agent did.** The lede prompt's first sentence says what the
  agent did with the agent as its subject; its second says where the entries end and names any
  correction. What the person set out to do was the first sentence and is not asked for, because
  the Intent card holds it.
- **Bullets are short clauses with the agent as subject.** Both prompts ask for one short clause
  per sentence, 15 words or fewer, the agent as subject, and no chains joined by "then", "while" or
  a semicolon. The `Said:` label is gone. A stored line that names no speaker is drawn "The agent
  said: ...", so it never reads as the summary's own claim, and a line that names its speaker is
  drawn as written.
- **A withheld completion claim is worded for the reader.** "One line was left out because the
  record does not back it", with the entry range; each line's own reason stays under "Why each was
  hidden".
- **The failure badge counts failed test runs.** The producer marks a bullet `failed` when a
  cited check failed, which includes a build and a browser run the agent's sandbox refused. The
  page badges a `failed` bullet only when its words name a test run and do not put the failure down
  to the sandbox or environment. It reads the producer's text because the page holds nothing else
  of the check. The line itself is still drawn as a failure. A build, lint or type-check command
  is never badged, even when its words name a test (`pnpm build:storybook`, `ruff check tests`).
  The test is a word match, so it can miss a real test failure the agent never named as a test, and
  it can still badge a sandbox failure the text does not name as the environment.
- **The estimate and the progress agree.** A plan off a partial read counted a floor on the parts
  ("at least 2 parts, up to 10 minutes") and the job then counted 3, and finished in about 30
  seconds. The page now quotes parts and minutes only for a plan of a whole read, and otherwise says
  what the outline counted and that Compass plans the parts when the summary starts. While a job
  writes the summary the header says "summarizing…" and not "summarized at".
- **Turn off summaries stands apart from Cancel.** It turns summaries off for every session where
  Cancel stops one run, so it is a quiet control in its own row below Cancel.
- **The notice folds once the summary stands.** While a request runs the notice is the whole card.
  After it, the notice folds to "What this request sent to Claude Code", with Turn off summaries
  inside, instead of staying open above the summary.
- **A summary written again says it can group differently.** After Summarize again, or a start after a
  delete made in this tab, the card says a summary written again can group the work into different
  phases. The page holds that in memory for the tab and draws it only while the rerun job runs: once a later
  context read shows the job over, the note is cleared and a later start does not bring it back. The server
  publishes no history of rewrites.

**Measured.** The current and the previous prompts were run through the production producer and
`observer.claude_exec` over the committed sample session (96 entries: two windows and a lede, three
calls per run), two runs of each. The harness stayed in a local scratch directory and records counts
only. Withheld strings, previous prompts: 3 of 43 and 10 of 41, 13 of 84 (15.5%). Current prompts: 1
of 51 and 2 of 47, 3 of 98 (3.1%). The current prompts withheld nothing for a shape fault and
nothing from a title, and the mean bullet fell from 20.7 words to 13.9. A first pair of runs
miscounted the lede and is not used. Each arm is two runs of one session, so this shows that the
rate is no worse than the 13.3% the earlier prompts reached, not by how much it improved.

### No completion words

The producer holds the summary's own voice to DEC-28 question 1 under the
[owner's amendment](#amended-2026-10-19-owner-the-summarys-own-voice), widened by the
[2026-10-20 amendment](#amended-2026-10-20-owner-more-attributed-phrasing-is-accepted).
An unlicensed completion word withholds the whole title, bullet or lede. Attributed speech,
tracker states, names, noun uses, title activities and headings, and a check's own report are
admitted only in the structures those sections give.
Citing a passed check admits nothing else: `Tests passed` and `The build went green` are withheld.

The word list covers fix, done, complete, work, verify, success, succeed, pass, resolve, land,
ship, merge, green, finish, solve, repair, implement, deliver, deploy and accomplish in their
existing inflected forms. Text is NFKC-folded before matching, and a word that mixes Latin letters
with letters of another script (`fix` followed by a Cyrillic `е`) is withheld, because folding does
not map look-alike letters. A string holding a check or tick glyph (U+2713, U+2714, U+2705,
U+2611, U+221A, U+10102, U+1F5F8, U+1F5F9 or U+1FBB1) is withheld wherever the glyph stands, quoted or attributed,
because a result is never a check mark. That is the exact set, matched after NFKC folding: every character
Unicode names a check mark, plus U+221A as a tick look-alike; U+237B (not check mark) and U+2612
(ballot box with X) are excluded. The page withholds the same set again, from a stored or
hand-edited summary the producer never checked, and a page test lists all nine so the two copies
cannot drift apart unnoticed. The same refusal applies
to titles, bullets and the lede, including a glyph inside a named speaker's quotation. These
checks run on the whole string before any character cap and on the clipped string after it. A cap must not hide an unsafe suffix or strip the attribution from a
surviving claim. Citation relevance remains the
[known limit](#the-known-limit-relevance-is-not-checked).

### Amended 2026-10-19 (owner): the summary's own voice

The owner's final ruling narrows the completion backstop to the summary's own voice. A displayed
string is withheld when the summary itself states that work is fixed, done, working or verified
without a passed check behind it. Attributed speech, including a tool error's own output, names
and tracker states are not completion claims by the summary. A passed check still licenses only
its reported result, never a claim that the work is done.

The measured basis is unchanged: 138 of 707 displayed strings matched the literal word list, and
28 of those were own-voice claims. Withholding every match would withhold about one string in
five, and about four in five of those withholdings would be wrong. The amendment replaces that
blanket refusal with structures the code can check:

- **Clauses.** The splitter fails closed: a speech verb never covers a second clause, so any
  punctuation it has no rule for also ends a licence. It splits at `.`, `!` or `?` followed by
  space, end or a letter (`ran.The`), and at the same marks before a closing single quote
  (`'I will inspect it.' The`). It also splits at semicolons, commas, dashes (en, em, a spaced
  hyphen or `--`), brackets, line ends (checked before whitespace is collapsed for display) and
  Unicode sentence terminators such as `。`. A colon splits too, except one directly after a speech
  verb, which introduces the reported words (`the error read: ...`). The joiners are `so`, `which`,
  `and`, `but`, `then`, `because`, `while`, `after`, `although`, `though`, `yet`, `until`, `since`,
  `as`, `once`, `when`, `or`, `however`, `thus` and `therefore`. A dot inside a name such as
  `file.py` is not a sentence end, `then` inside `the agent then said` is an adverb, and `as`
  inside `marked the ticket as Done` is part of the state. Invisible format characters (Unicode
  category Cf, such as a zero-width joiner) are removed after NFKC folding and before splitting,
  so they cannot hide a joiner or a word. Straight and curly double quotes and backtick spans are
  atomic; their internal punctuation and joiners do not split them. A closed quote followed by
  more unquoted words ends its clause at the closing quote, unless a trailing speaker attribution
  follows or the quote is a backticked name (`` the agent said `parser.py` works ``).
- **Named attribution in the same clause.** A speaker is `the agent`, `the person`, `the user`,
  `the subagent`, `the teammate` or `the reviewer`, and its verb is one of `said`, `says`,
  `reported`, `reports`, `stated`, `replied`, `answered`, `asked`, `told`, `noted`, `claimed`,
  `confirmed`, `explained`, `mentioned`, `suggested`, `proposed`, `requested` or `wanted`. The only
  tool speaker is an error, because the ruling admits a tool error's own output and quotes a check
  result only as the tool's report: `the error`, `the tool error` or `the check error`, optionally
  followed by `output`, `message` or `log`, with `read`, `reads`, `said` or `says`. `The tool output
  showed the tests passed` and `The check reports the tests passed` are withheld. The verb must
  follow its speaker directly, with at most one adverb (a `-ly` word, `then`, `also`, `later`,
  `again` or `first`) between them, and the completion word must follow the verb. `read` and
  `wrote` are not speech for a person or the agent: `the agent read the log before fixing the
  parser` and `the agent wrote a working parser` are the summary's own claims. The reported words
  may open with a speaker of their own, after an optional `that`: `the person asked the agent to
  fix the parser`, `the agent told the user the parser is fixed` and `the person said the agent
  fixed it` are admitted. A speaker later in the words ends the licence, so `the person asked about
  the bug the agent fixed` is withheld. A quote immediately followed by a speaker and its verb also
  admits the words inside that quote: `"the parser is fixed," the agent said`. The attribution
  cannot come from inside an unattributed quote. A trailing attribution licenses only its quote,
  not words before the quote or after that attribution.
- **Implicit subject only for speech bullets.** A code-set `said` or `asked` bullet may begin its
  first clause with a speech verb: `Said the parser is fixed`, `Asked the agent to fix the parser`
  or `Reported the tests pass`. This admits nothing in later clauses. The model's proposed kind
  cannot grant this licence. Titles and the lede have no kind and get no implicit subject licence.
- **Tracker states.** A verb `moved`, `set`, `changed`, `marked` or `switched`, an object `issue`,
  `ticket`, `card`, `task`, `status`, `state` or `item`, or an issue key such as `ABC-1`, an
  optional `from <State>`, then `to` or `as`, may name a state. A state is a Capitalized word, up
  to three Capitalized words (with `for`, `in`, `to`, `of` or `on` between them) that end the
  clause, or a backticked label of one to three words. Only the states are admitted: `Moved the
  issue to Done`, `Moved the ticket from Todo to Done`, `Moved the issue to Ready for Merge` and
  ``Marked the ticket as `Done` ``. A bare lowercase state, a backticked phrase such as
  `` `fixed and verified` `` or `` `the parser is fixed` ``, and `to Done Fixed the parser` are
  withheld.
- **Names.** A name has a name's shape. An identifier joined by `_` or `.` with no spaces is a name
  when it holds an underscore or a digit, or when its last dotted part is a short lowercase file
  extension (`fixed.py`, `hotfix_parser.py`); `Parser.fixed`, `it.is.fixed` and `works.Now` are
  not. A slashed token is a name only when it also holds a hyphen, underscore, dot or digit, as in
  `fix/parser-crash` and `feature/done-list`, because `Fixed/verified the parser` is prose. A
  hyphenated or slashed compound is also a name immediately after `branch`, `tag`, `ref`, `path`,
  `file`, `directory`, `folder` or `label`, as in `branch fix-parser`. Backticks alone do not make a
  compound a name, so `` Created `fix-parser` `` is withheld. No name is made only of completion
  words (`Fixed.Verified`, `branch fixed-done`) or holds a filler word (`all`, `is`, `are`, `was`,
  `were`, `be`, `been`, `being`, `and`, `or`, `but`, `so`, `yet`, `it`, `the`, `now`, `fully`,
  `totally`, `completely`, `really`), so `` `all-fixed` ``, `` `parser-is-fixed` `` and `branch
  fully-fixed` are withheld. A result verb is matched only as a whole word outside a name, so
  `got.py` is not `got`.
- **Tool reports.** Only the `<check> reported <result>, as the tool reported` form is admitted,
  with result `passed`, `failed` or `not-recorded` and the comma required. The whole report,
  `reported` included, ends its clause, so it licenses only itself: neither words before it nor
  words after its attribution inherit permission. The postfix form `<check> passed, as the tool
  reported` is withheld, because the code cannot tell a check's name from the work's
  (`Everything passed, as the tool reported`). Both prompts teach the reported form, and the
  error-output form `the error read: <its words>`; text after `<check> failed:` is not admitted.

The refusal conditions stay. Unattributed quotations such as `Quoted "the parser is fixed"`,
`"Fixed the parser."`, a bare backticked `fixed` and `all fixed` are withheld. A speech verb does
not cover a second clause: `The agent said it ran, the bug is fixed`, `The agent reported the root
cause, so the bug is fixed`, `The agent reported the tests passed, so it works` and `The agent said
it ran, which fixed the bug` are withheld. The same boundary holds at sentence ends, semicolons and
each joiner above, including `The agent said "I will inspect it." The parser is fixed.`

Result verbs `got`, `managed`, `made`, `brought` and `gotten` in the summary's own voice override
the implicit-subject, state and name exceptions. `Got everything to Verified.`, `Got the tests to
pass`, `The agent managed to fix the parser bug.` and `Brought the build to green` are withheld.
Real attribution still admits `the agent said it got the tests to pass`. Unreported check results
such as `Tests passed` and `The build went green.` remain withheld. NFKC folding, mixed-script
refusal and checks before and after clipping remain in force.

This is a structural backstop, not a language or relevance judge. The
[2026-10-20 amendment](#amended-2026-10-20-owner-more-attributed-phrasing-is-accepted)
admits noun uses such as `a list of fixes`, `a pass over the docs` and `the work so far`, a
subordinator that opens reported words (`the person asked when it would be done`), `according to
the agent, ...`, a quote attached to a word inside reported words (`the agent said file."py" is
fixed`) and title headings such as `Merge and numbering follow-up`. `The done list` remains
withheld, as do a speaker whose verb is not on the list, a pronoun speaker (`It said the tests
pass`), a subordinator later in the reported words (`the agent said it would hold until the tests
pass`), a free-standing quote followed by more words (`the agent said "ok" the parser is fixed`),
a second reported clause that opens with `and that` (`said it ran, and that it opened the PR`),
nouns coordinated inside reported words (`said Codex and AGY had finished`, because `and` ends
the licence) and any noun after a light verb (`Ran the merge`, `Ran the deploy script`).
Ambiguous modified plurals (`the CI fixes`) and plural modifiers before a completion noun stay
withheld to keep subject-and-verb claims such as `the parser works` and `the tests pass` out.
A quote ending in sentence or clause punctuation still ends reported words; an unquoted completion
verb directly after a closed quote also stays withheld (`the agent said "it ran" fixed the parser`).
Before matching, a small table folds the Latin look-alikes NFKC leaves alone (the hooked `ƒ`, the dotless `ı` and
`ȷ`, the script `ɑ` and `ɡ`, and the small capitals) to plain letters, and an underscore that does
not join two letters or digits (`Fixed_ the parser`) is read as a space; an underscore inside a
name (`test_passes_when_ok`) still makes an identifier. Invisible marks other than format
characters (a combining accent) and look-alikes outside that table still defeat the word match.
The code does not check whether an
attributed sentence is relevant to its citations. Where the ruling leaves malformed quotations
unspecified, an unclosed quoted span stays atomic through the end of the string and cannot supply
its own attribution.

### Amended 2026-10-20 (owner): more attributed phrasing is accepted

> The completion check accepts more attributed phrasing. The check still withholds a string that
> states completion in the summary's own voice. It stops withholding attributed speech the first
> build treated conservatively: "according to the agent", reported words that contain a
> subordinator or a result verb, lowercase tracker states, noun uses of a completion word, and
> clauses where each carries its own attribution. A change is accepted only if it keeps every
> own-voice claim in the adversarial set withheld and measurably lowers the share of correct lines
> withheld in real summaries.

The amendment adds these structures. A licence covers only its reported words, state or noun;
one unlicensed completion word still withholds the entire displayed string. The prompts, stored
shape and reason tokens are unchanged.

- **Speakers without an article, and the team lead.** `agent`, `user`, `person`, `subagent`,
  `teammate`, `reviewer` and `team lead` may have `the` or no article, in any case. `Agent reported
  the patch merged` is admitted; `The tool reported the patch merged` is withheld. A bare speaker
  counts only at the start of a clause, after a clause break, or after a joiner or preposition
  (`and`, `then`, `as`, `to`, `that`, `when` and the like). After any other word or character it is
  a tool's name: `The build agent said the deploy succeeded`, `The user-agent reported tests
  passed`, `The build_ agent said`, `Lint+agent said`, `Build @agent said` and `The tools' agent
  said` are withheld. A possessive is not a speaker (`The agent's suite ran and reported passed`),
  and no speaker pattern reaches across quoted words (`The agent "never" said the decoder is
  fixed`, `Team "CI" lead said`, ``according to the `CI` agent``). Pronouns and arbitrary nouns
  cannot speak for a person. The existing error-speaker form still speaks for tool errors. A
  `saying` gerund carries a speaker's words only after that speaker sent, left, wrote or posted a
  note, message, comment, reply or request, or commented on something: `Team lead sent a request
  saying the report was delivered` is admitted; `The agent read a log line saying all tests
  passed` and `The agent ran a check saying the build is green` quote the log and the check and
  are withheld.
- **According to, and postposed reports.** `According to the agent, the decoder is fixed` and
  `The decoder is fixed, according to the agent` are admitted. So is `All checks passed, as the
  reviewer reported`, with `said`, `reported`, `stated` or `noted` in the postfix. A prefix covers
  only the clause after its comma; a postfix covers only the clause directly before its comma,
  back to the previous break, never past the start of its own sentence or a closing quote, and must
  end its sentence. `"Tests passed." The agent checked logs, as the user noted` and `Tests passed.
  It ran, according to the agent` are withheld. `The decoder is fixed, according to the agent's
  plan` and `The decoder is fixed, as the agent said it would be` state the result in the
  summary's voice and are withheld.
  `Fixed the decoder; tests passed, as the agent reported` and `Tests passed, as the tool reported`
  stay withheld. Words after a postfix need their own attribution and a real break before any
  implicit subject; the postfix's end supplies neither, and no later clause of the bullet borrows
  an unstated subject once a postfix has appeared (`Fixed the decoder, according to the agent.
  Said the build is green` is withheld).
- **A later clause with its own speech verb.** After a joiner or punctuation break, a clause may
  open with `said`, `says`, `saying`, `reported`, `reports`, `reporting`, `stated`, `told`,
  `replied`, `answered`, `asked` or `claimed`. `Ran lint, and said the checks pass` and `Paused
  after saying the checks passed` are admitted. `Ran lint, and confirmed the decoder works` is
  withheld. `confirmed`, `noted`, `explained`, `mentioned`, `suggested`, `proposed`, `requested`
  and `wanted` receive no new implicit licence. Only the first clause of a code-set `said` or
  `asked` bullet retains the wider set; an initial `Said the decoder is fixed` in a title, lede
  or `did` bullet stays withheld. The later clause borrows its sentence's subject, and only after
  `and`, `then`, a comma, a sentence end or `after`. `which`, `without`, `before` and the other
  subordinators lend the object's voice instead: `Ran the test suite, which reported all checks
  passed` and `Ran pytest without saying it passed` are withheld. A sentence ends where a clause
  break ends one (`.`, `!` or `?` before a space or a letter, `;`, a line end or a Unicode
  terminator), except inside a name such as `items.json`. The sentence must open with a named
  speaker or with a past-tense verb whose unstated subject is the bullet's own: `The suite ran and
  reported passed` and `CI ran; reported the tests passed` quote a tool and are withheld. An `-ed`
  word followed by a noun and then another verb is an adjective on a tool's name, not that verb:
  `Automated checks ran and reported passed` and `Shared CI ran and reported the tests passed`
  are withheld, while `Inspected logs then said the reading completed` is admitted.
- **Subordinators that open reported words.** A subordinator stays inside an attributed span
  only when it opens the reported words: any of `when`, `whether`, `if`, `once`, `until`, `after`,
  `before`, `since`, `how`, `why` and `what` after `that` (`The agent said that once the merge
  lands it will tag`); `whether` directly after any speech verb and an optional named listener
  (`The person asked the agent whether it works`); and `when`, `if`, `how`, `why` or `what`
  directly after `asked` (`The person asked when it would be done`). `or` after `whether to
  <verb>` continues the words only when the alternative is one bare word that is not a
  completion word, optionally after `to`, followed by the end or a break (`The person asked
  whether to fix or revert`). `asked whether it ran or tests passed`, `asked whether it failed or
  is fixed`, `asked whether to revert or merged it` and `asked whether to fix or the decoder is
  fixed` are withheld.
  A condition or time limit inside a reported plan or request is part of it. When the reported
  words before the subordinator hold an infinitive, a modal verb or open with a gerund, `if` and
  `unless` stay inside them, and so do `before`, `until`, `once`, `when` and `after` when what
  follows has no finite verb of its own (a gerund, or a noun phrase such as `any merge`). In both
  cases no past or participle completion form may follow. `The agent said it would wait before
  merging`, `The agent said to rebase before merging`, `The user asked the agent to stop if the
  tests pass` and `The agent suggested waiting unless the deploy succeeds` are admitted; `The
  agent said it would merge if the tests passed` and `The agent said it would hold until the
  tests pass` are withheld. Elsewhere a subordinator may modify the saying instead, so it still
  ends the licence: `The agent replied after the tests passed`, `The agent said when the parser
  was fixed` and `The agent said nothing after the parser was fixed` are withheld. `The agent
  said it ran, so the decoder is fixed` is withheld. Every other break still ends attribution,
  including punctuation, `and`, `but`, `then`, `because`, `which`, `therefore`, `thus`,
  `however`, `yet`, `while`, `although` and `though`. The contrast and premise words `whereas`,
  `despite`, `given`, `without`, `except` and `considering`, and `unless` outside a plan, became
  breaks too, because `The agent said nothing whereas all tests passed` states the result in the
  summary's voice; that hole predated the amendment. A named subject directly after a
  subordinator belongs to the reported words; an otherwise later speaker without its own verb
  still ends them. So do a participle (`having`, `managing`, `leaving`) not preceded by `that`, an
  opening `with`, `using` or `without`, and a `with` or `using` phrase holding a past completion
  form: `Agent said hi having fixed the parser`, `Agent replied with production deployed` and
  `Agent said ok with everything merged` are withheld, with or without the article.
- **Result verbs within reported words.** `Said it got the checks to pass` in a code-set `said`
  bullet is admitted, as is `The agent said it managed to fix it`. `Got the checks to pass and
  said so` and `Managed to fix it, the agent said` stay withheld. An unquoted trailing speaker
  without the prescribed `according to` or `as` structure does not turn preceding prose into
  reported speech. A result verb outside reported words still defeats a name, state or noun
  exception; `got.py` remains a name.
- **Closed quotes within reported words.** A quote inside a word, as in `The agent said
  file."py" is fixed`, does not revoke attribution when the sentence continues. A quote after a
  space, a speech verb, a colon or another quote stands alone and ends the reported words, because
  the words after it may be the summary's own: `The agent said "ok" the decoder is fixed`, `The
  agent said:"ok" the decoder is fixed`, `The agent said"ok" the decoder is fixed` and `Agent said
  "hello" having fixed the parser` are withheld. `Read "ok" the decoder is fixed` remains withheld,
  because a quote supplies no attribution. Punctuation at the end of the quoted words still ends
  their licence, and an immediately following unquoted completion verb remains unlicensed.
- **Lowercase tracker states and counts of states.** The full tracker structure still requires
  a move/set/change/mark/switch verb, a tracker object or issue key, and `to` or `as`. A
  capitalized or backticked state keeps the first build's form. A lowercase state must be a
  tracker's own word: `done`, `todo`, `to do`, `backlog`, `triage`, `in progress`, `in review`,
  `on hold`, `blocked`, `canceled`, `duplicate`, `fixed`, `verified`, `open`, `closed`,
  `reopened`, `resolved` or `ready for <word>`, ending its clause. `Marked the issue as done`,
  `Moved ABC-17 to in progress` and `Set the task state to fixed` are admitted; `Set the task to
  quickly fix`, `Marked the issue as clearly fixed`, `Marked the item as passing`, `Changed the
  status as unit tests passed` and `Moved the ticket to closed build succeeded` are withheld. A
  single-word or backticked state may name where it lives with `in`, `on`, `under` or `within`
  (`Moved the issue to Done in Linear`, `Set the status to Verified on main`); a completion word
  in that place phrase is still unlicensed. Filler words and a completion word before the last
  state word cannot hide prose: `Marked the issue as fixed and verified` and `Moved the ticket to
  done the decoder is fixed` stay withheld. A complete comma-separated list of at least two
  counts with capitalized single-word labels, such as `92 Done, 2 Duplicate`, is also admitted.
  `Done` is the only completion word such a label may be: `12 Passed, 1 Failed`, `12 Pass, 1
  Fail` and `12 Green, 0 Red` count results and stay withheld. A lone count or lowercase count
  label gets no state licence.
- **Nouns and activity titles.** A determiner (`a`, `an`, `the`, `this`, `that`, `these`, `those`,
  `its`, `their`, `our`, `each`, `every`, `another`, `no` or a numeral), at most two modifiers, and
  a base or plural noun form of `fix`, `work`, `pass`, `merge`, `deploy`, `repair` or `ship` may
  name an object, and only in object position. The phrase must follow a verb (a past or `-ing`
  form, a listed irregular verb, or an infinitive after `to`) or a preposition, with at most an
  adverb such as `only` between. After it may come the end of the clause, a preposition or `so
  far`, or one head noun (`the merge state`, `their repair notes`); a hyphenated or possessive
  compound may take one more (`the work-row number column in CSS`, `the sample work's files`).
  The head may not be a verb, adverb or adjective from a fixed list (`went`, `holds`, `now`,
  `ok` and the like), an `-ed`, `-ing` or completion word, or a plural followed by more words.
  After a verb that takes a clause (`confirmed`, `checked`, `saw`, `found`, `noted` and the like)
  the head must be a known compound head such as `state`, `conflict` or `list`. `Reviewed the CI
  fix`, `Read a list of fixes`, `Agent checked the PR merge state` and `Inspected a ship model` are
  admitted; `Confirmed the fix holds`, `Watched the fix go in` and `The change is a fix` are
  withheld. A determiner phrase opening a clause is a subject: `The fix holds`, `The merge went
  through`, `Their work paid off`, `Each fix sticks` and `Some fix the decoder` are withheld.
  The one exception is a clause that is only a noun phrase with a singular determiner and no
  plural, numeric or adverb modifier, after earlier words and not before a colon or dash (`after
  the merge`, `between a minor and a bug fix release`); `The fix: in` and `The merge, then
  nothing` are withheld. `some` and `any` never license a noun.
  A noun after a light verb (`do`, `ran`, `performed`, `executed`, `committed`, `conducted`,
  `carried out`, with an optional adverb between) gets no licence, because it is the action
  itself: `Ran the merge`, `Did all the work` and `Carried out the merge of PR #701` stay
  withheld. A copula or verb of being anywhere earlier in the clause (`is indeed a fix`,
  `constitutes a fix`), or a following copula or auxiliary (`The repair was certified`), also
  prevents a noun licence. Determiner and numeral agreement keeps `This works`, `Those pass` and
  `1 fixes the decoder` out. Neither `success`, `done`, `complete`, `green` nor verification forms
  become nouns here.
  In titles only, a clause opening with a transitive completion verb in `-ing` form followed by
  an object names an activity: `Merging PRs 701 and 702`, `Merging PR 5 into main` and `Fixing
  the view-only guard` are admitted. Only the object and prepositional or numeric material may
  follow; a verb, adverb, copula, result or listed predicate word anywhere after it, or an `-s`
  word with more words after it, refuses the licence: `Merged PR #701`, `Working decoder`,
  `Finishing now`, `Shipping today`, `Merging the PRs went fine`, `Merging the PR was clean`,
  `Deploying the build now`, `Merging the PR unblocks deploys` and `Fixing the parser eliminated
  the crash` stay withheld. The title flag is passed only at the title call site, so the same
  activity wording in a lede still refuses. A title clause may also end on a bare `fix` or
  `repair` noun after at most two words that are not a completion word, pronoun, quantifier,
  adverb, copula, auxiliary or speaker, or consist of `merge` or `deploy` alone. This heading
  licence holds only when every break in the title is a comma, `and` or a parenthesis and no
  item opens on a predicate word, so `Deploy: live in production` and `Deploy, live in production`
  are withheld. A plural word directly before a bare `fix` or `repair` is a subject (`Patches
  fix`, `Both patches fix`, `Patches cleanly fix`), except as the one modifier of an item in a list
  (`Docs fix, stories review and increment 4`). A bare `merge` or `deploy` must open the title,
  follow a comma, or end a list of three or more (`Windows deferral, notarization and merge`);
  `Branches rebase and merge` and `Branches rebase, and merge` are withheld. `Type fixes and
  Storybook story` and `Merge and numbering follow-up` are admitted; `It fixes`, `Agent merges`,
  `Patch fixes crash`, `Fix merged` and `Tests pass` are withheld. `pass` and `work` get no heading
  licence, because `Tests pass` and `Build works` read as results.
- **Names.** An underscore-joined file name with a common source extension is a name whatever its
  words, so `Inspected fix_the_parser.py` and `Ran test_it_works.py` are admitted. A completion
  word inside any other underscore identifier still needs a licence (`Agent said it ran;
  fixed_and_verified` is withheld).
- **Each joined clause may carry attribution.** `Agent said it ran and user said it passed` and
  `The agent reported an attempt, then the person asked whether it was done` are admitted.
  `Agent said it ran and the decoder is fixed` stays withheld: the joiner ends the first licence
  and the second clause supplies none.

The existing glyph, Unicode normalization, mixed-script and look-alike refusals still apply before
these exceptions. Runs of spaces and tabs are collapsed after an underscore is read as a space, so
`The build_ agent` meets the speaker guard as `The build agent`. The whole redacted string, the
cleaned string and the clipped prefix are each checked; losing an attribution or the object of an
activity heading to clipping withholds the slot. Citation relevance remains outside this check.

Known limits of this amendment, each failing closed: a pronoun speaker (`It said the checks
pass`) is withheld even when the pronoun means the agent, so the prompts' instruction to name the
speaker in the same clause still matters; a past-tense verb list cannot tell a noun such as
`Speed` from a verb at a sentence start; nouns coordinated inside reported words split at `and`
(`The agent said Codex and AGY had both finished` is withheld); and a second reported clause
opened by `and that` or `, that` gets no licence. A completion noun inside a subject is withheld
even when it only modifies another noun (`polled PR #624 until its merge state read CLEAN`, `the
numbering problem the fix leaves alone`, `until a deploy key exists`). The verb, adverb and
compound-head lists are finite, so a predicate the lists miss after a noun in object position
can still pass as a head noun; the check is a backstop for the prompts, not a parser.

**Measured.** A replay ran every displayed string of the measurement's four real Claude Code
summaries and the sample lane's recorded summary (733 strings: 581 bullets, 147 titles and five
ledes) through the check before and after this amendment. Withheld strings fell from 243 to 172
(33.2% to 23.5%): bullets from 200 to 153, titles from 38 to 15 and ledes from five to four.
Within this replay, no string the earlier check showed was withheld by the new one. Outside it,
the new check does withhold strings the earlier one showed, each a claim in the summary's voice
that the earlier check missed (`The agent said nothing whereas all tests passed`, `The agent
replied with production deployed`). A random sample of 80 of the 243 earlier withholdings was labelled by hand:
62 were wrongly withheld (attributed speech, names, states, negations or non-completion uses), 11
were own-voice claims and seven were merge actions in the summary's voice. An independent second
labelling of 30 of them by a different model agreed on every withhold-or-show verdict and
differed only on whether one merge line was an action or a claim. After the amendment 33 of the
80 are still wrongly withheld (41.3%, down from 77.5%), and all 18 own-voice and action lines are
still withheld. Two adversarial review passes by a second model found 38 own-voice strings that
an earlier draft of these rules admitted, and a later review of the first build of this amendment
found more than 80 in nine families (subject-position nouns, title licences, free-form states,
quote placement, borrowed subjects, punctuation before a speaker, participles and the `whether`
alternative) plus nine strings the first build wrongly withheld. Each is now withheld or shown as
reviewed and pinned in the tests, alongside the earlier adversarial cases grouped by refusal
family. Closing those holes withheld three real lines the first build showed: the three
subject-position compounds listed under the known limits. The remaining wrongly withheld lines
are mostly pronoun speakers, negations (`did not merge`), a verb that is not a completion claim
(`pass the intent prop`), unattributed quoted labels and lines that paraphrase a check's result
outside the tool-report form.

### Amended 2026-10-20: the prompts ask for checkable lines

After the owner's amendment the replay still withheld 172 of 733 strings. Most of the remaining
withholdings were lines the model wrote in a form the check must refuse: a pronoun speaker, a
completion verb for the agent's own action, a result stated as the summary's fact, a title that
states an outcome, and a bullet citing only relayed text. A withheld lede or title makes a summary
read as broken. The check, its clause code, the kinds, the ceilings and the rulings are unchanged.
Only the window and lede prompts changed, as
[Menu, windows and prompts](#menu-windows-and-prompts) describes, so that the model writes lines
in the forms the check keeps. `SummaryPromptTest` in `test_session_summary.py` pins each
instruction, the record's delimiting, and that every example the prompts teach is one the check
shows. The window prompt's instructions grew from 1,620 to 3,340 bytes and the lede's from 868 to
2,040, so a full 16 KiB window prompt is about 19.7 KB. Thirty-seven such calls stay inside the
768 KiB byte ceiling, which is unchanged.

The current and the new prompts were measured through the production producer and
`observer.claude_exec`, with the summary system prompt and the per-call timeout, on the same
windows: the committed sample session (two windows and a lede) and the first window of each of the
two smallest measured sessions, C and D (no lede). The model was called 16 times, one run per
prompt. Nothing from the sessions is recorded here. The harness that ran the calls and recounted
them, `harness.py` and `analyze.py`, and the call logs under `runs/`, stayed in that session's local
scratch directory (`waveH/prompt/`) and are not committed, because the logs hold session content.
The figures can be recounted only from that local copy.

| | Current prompts | New prompts |
| -- | --: | --: |
| Strings withheld | 17 of 62 (27.4%) | 10 of 75 (13.3%) |
| Bullets withheld | 15 of 47 (10 completion, 5 shape fault) | 10 of 58 (5 completion, 5 shape fault) |
| Titles withheld | 1 of 14 | 0 of 16 |
| Lede withheld | 1 of 1 | 0 of 1 |
| Usefulness, 30 bullets each, 1 to 5, as written, scored by the agent that wrote the prompts | 3.67 | 3.37 |
| The same, derived from the withheld share (a withheld bullet scores 0) | 2.40 | 2.73 |
| Usefulness by a second model (Codex `gpt-6.1-sol`), 15 of the same bullets | 4.43 (7) | 4.38 (8) |
| Citations pointing at the right entries, 25 sampled bullets, by hand | 25 of 25 | 25 of 25 |
| Citations the second model judged right | 6 of 7 | 7 of 8 |
| Shown strings holding a completion word | 11 | 12 |
| Of those, own-voice completion claims, checked by hand | 0 | 0 |

The result is directional, and the owner accepted it as that rather than as a measured
improvement:

- The withheld share fell from 17 of 62 to 10 of 75, but that is one run of each prompt, and
  Fisher's exact test gives p of about 0.052. Against the second revision below (11 of 66) it gives
  p of about 0.64, so the difference is within the spread between revisions of similar wording.
  The aim was below 12% withheld, and the new prompts reached 13.3%, so the target was missed.
- The usefulness scores came from the agent that wrote the prompts, which scored both sets, so they
  are not independent. As written, usefulness fell from 3.67 to 3.37; the new bullets are shorter and more
  numerous, 58 against 47. The row for what a reader sees is not a separate measurement, since it
  only folds the withheld share into the same scores. The second model scored the two sets about
  the same.
- All five remaining shape faults were bullets citing only relayed text, or relayed text and the
  agent's words. The rest were a second claim joined after one attribution, a completion word
  inside a name or a quoted label, and a negation in the summary's own voice.
- A second revision, which spelled out the relayed-citation rule and the joined-claim rule, cut
  shape faults from five to one but withheld 11 of 66 strings (16.7%), including two titles. It was
  not adopted, and the call budget ended there.

The prompts were revised after this measurement, without new model calls, to close what review
found: the relayed-citation sentence now forbids a relayed-only bullet instead of naming a
citation to add, the merge example and "asked" left the action verbs, the lede's error form is
double-quoted, the title rule and the ban sentence name their exceptions, and a count is reported
only from the entry that states it. The figures above describe the measured wording, not this one.
`SummaryPromptTest` pins the revised wording against the check: each taught example is shown in
both prompts, each taught action verb followed by a joined result is refused, and every word the
check refuses is one the prompt names, and the reverse.

### Bounds, spend and gaps

All tunable bounds are declared once in `config.py` and carried by `RuntimeConfig`:

| RuntimeConfig field | Default | Decision |
| -- | --: | -- |
| `session_summary_window_bytes` | 16,384 | Measured 16 KiB windows; largest prompt was 17,714 bytes including instructions. |
| `session_summary_max_windows` | 32 | Largest measured session used 30. |
| `session_summary_max_calls` | 37 | 32 windows, one lede, four retries; largest measured job used 36. |
| `session_summary_max_bytes_sent` | 786,432 | 768 KiB covers the measured maximum prompt across 37 calls. |
| `session_summary_max_seconds` | 600 | Headroom over the measured 307-second job. |
| `session_summary_call_timeout` | 180 seconds | Equal to `observer.OBSERVER_READING_TIMEOUT_SEC`; the job lane wires it. Slowest measured call was 12.3 seconds. |
| `session_summary_rolling_cap` | 200 calls per 24 hours | Separate summary admission, enforced by the job lane. |
| `session_summary_output_cap_bytes` | 65,536 | The measurement's per-call output allowance, passed to the model seam. |
| `session_summary_max_phases` | 4 | The measured window prompt's phase bound. |
| `session_summary_max_bullets` | 6 | The measured prompt's bound per phase. |
| `session_summary_max_cites` | 8 | Bound citation rows and repeated fact ids per bullet or lede. |
| `session_summary_title_chars` | 60 | The measured prompt's title width. |
| `session_summary_bullet_chars` | 200 | The measured prompt's bullet width. |
| `session_summary_lede_chars` | 400 | A short lede without another window of prose. |
| `session_summary_max_bytes` | 524,288 | 32 windows × 4 phases × 6 bullets × 200 characters plus eight ordinary fact ids and JSON overhead fits in 512 KiB at ordinary text widths. A 256 KiB bound would cut that shape even in ASCII; wider text and ids still hit the byte bound. |
| `session_summary_person_chars` | 1,200 | The measurement's clip for person-turn words, asked or relayed. |
| `session_summary_agent_chars` | 700 | The measurement's clip for the agent's words. |
| `session_summary_check_chars` | 220 | The measurement's clip for a masked check title. |
| `session_summary_path_chars` | 220 | The measurement's clip for a display path. |
| `session_summary_attempts_per_part` | 2 | One retry for an empty reply; the focused plan's call bound counts both attempts. |
| `summary_freshness_retry_sec` | 300 | A focused freshness answer clipped by the read's time allowance is reused this long for an unchanged transcript. Re-reading it each board revision cost about two seconds a poll on 42 and 52 MiB transcripts. |

Before the first call the producer plans the retained windows plus a lede. Exceeding planned
calls or prompt bytes refuses the job with `planned_calls` or `planned_bytes`, spending nothing.
A seconds allowance smaller than one call timeout refuses with `planned_seconds`.
The byte plan reserves the full lede window and each later context allowance because their
actual contents depend on replies. Retries are not prepaid; every call checks remaining calls,
prompt bytes and elapsed monotonic seconds immediately before invoking the seam. Reaching a
ceiling leaves the current and all later windows as `ceiling` gaps. A call starts only when the
elapsed seconds plus `session_summary_call_timeout` stay within `session_summary_max_seconds`, so
the job ends inside its ceiling without cancelling a call in flight. With the defaults, no call
starts after 420 seconds; the largest measured job took 307. The job lane's per-call timeout
bounds each wait. The producer does not pass a timeout to any subprocess function. The job lane
checks the job's deadline again after its own lock waits and board collection, immediately before
spawning, and gives the call the smaller of `session_summary_call_timeout` and the seconds left.

`session_summary.plan(entries, harness, *, config, prior=None, change=None)` runs that same
admission without a model and returns `reason`, `parts` (retained windows plus one lede) and
`largest_read`, so a job refuses before it writes a marker or charges anything. `summarize` and
`update` take an optional `on_part(summary, part, parts)` callback, called with part 0 before the
first call, after every window, and with the final result as part `parts`. The intermediate
summaries carry the unanswered windows as one `stopped` gap; the final one is offered unless its
state is `refused`. The callback changes no result: the returned `Summary` is the one produced
without it.

An empty reply, including `unstopped`, counts as a call and is retried once within those ceilings.
Two empty replies leave `no_output`. Nonempty invalid text leaves `no_valid_reply` without a
retry. `unavailable`, `closed` and `cancelled` stop immediately with `stopped` gaps and no retry; the
guarded seam and the CLI return them before any reservation or spawn, so they add nothing to spend.
A `RefusedError` leaves `refused` gaps and stops; because the guarded refusal precedes the
reservation, it adds no call or bytes to spend. `spend` reports calls, prompt bytes sent, reply
bytes back, monotonic seconds and retries for this invocation, including an update invocation.

Any other exception from the seam also stops the job with `stopped` gaps, keeping finished
blocks and spend. Nothing says whether such a call was reserved first, so it stays counted. A retry
is counted only when its attempt reaches the model.

Every gap has `gap: true`, first/last fact ids, entry count, span fingerprint, a reason and
`see: outline`. Reasons are `before_window`, `no_valid_reply`, `no_output`, `refused`, `stopped`,
`ceiling` and `bytes`. When any block was dropped for bytes, the result's `reason` is `bytes`, and
so is `lede_reason` when no lede survives. Source coverage remains alongside the result, so an unread source region
is not presented as evidence the model saw. The byte bound removes newest whole blocks into
one `bytes` gap. It reserves space for a worst-width lede before selecting lede evidence and
checks the final compact UTF-8 JSON size again. It never splits or rewrites a finished block.
An allowance too small for the word-free envelope returns `refused`, reason
`output_bound_too_small`; callers must supply enough space for metadata and retained prior blocks.

### Frozen result and updates

`Summary`, its blocks, phases, bullets, display values, lede and spend are frozen dataclasses
with tuple collections. `as_dict()` returns a fresh plain JSON-compatible tree. The result has
`state` (`ok`, `partial`, `unsupported`, `refused`, `source_changed`; unchanged updates return the
prior object), `reason`, `harness`, `starts_at`, `lede`, `lede_reason`, `blocks`, `spend`,
`coverage`, `change` and `affected_blocks`. A lede holds text and fact-id citations, or a withheld
marker and citations. Every block holds `first`, `last`, `entries` and a 32-hex SHA-256
fingerprint over the span's ordered `(fact_id, fingerprint)` pairs, plus either phases or a gap.
A phase has a title or withheld-title marker and bullets. Each bullet has text or a withheld
marker, kind, fact-id citations and `kind_overridden`, with cut metadata when applicable. No
source `words` or menu-number citation survives in this result. `partial` names gaps, incomplete
source coverage or a failed lede; withheld fields remain visible in their places.

`update(prior, entries, coverage, change, *, config, model, clock)` takes a **full** new source
sequence, including earlier spans, and the `SourceChange` from `session_source.compare`.
`truncated`, `replaced`, `changed_earlier`, or any earlier span whose count or fingerprint no
longer matches returns `source_changed`, with the change kind and affected block indexes, and
makes no call. Prior blocks must tile the source from its first entry, each starting where the
previous one ended. An entry between two prior spans, such as a subagent's check merged in by
time after the earlier summary, is reason `late_evidence`, because no earlier prompt read it.

One earlier change is appendable. A check summarized while its result was pending resolves in a
later read, which `compare` reports as `changed_earlier` with reason `check_result`. When every
change is such a result inside the newest prior block, that block is summarized again together
with the appended entries, and every earlier block is kept by identity. A result change in any
earlier block is still `source_changed`.

Before any call, an update checks that the prior's JSON size, a worst-width lede, a gap for the
new span and one smallest phase fit within `session_summary_max_bytes`. Prior blocks are kept
whole and accumulate across updates, so without this check a long-running session would spend
calls on blocks that can only become one `bytes` gap. When they do not fit, the update returns
`refused`, reason `output_bound_full`, the prior blocks and lede and no spend; the caller runs a
fresh summary instead. It never guesses from a missing span. An unchanged source returns the prior
object with no call. An append summarizes only entries after the prior last block's last fact,
preserves prior blocks by identity, appends new blocks and asks for one new lede under fresh job
ceilings. Gap spans also mark the previous job's examined frontier. To keep the update's promise
that no earlier entry text is resent, its new lede reads only newly cited entries. The caller
receives that limited new lede, not a rewritten account of the whole earlier session. When the
new lede fails, the prior lede is kept rather than lost.

## Source and outline contract

`session_source.read(config, path, harness, sid, after=None, newest=False, max_bytes=None,
deadline=None)` is a forward, contiguous JSONL read, independent of a reading's retained messages
and anchors. `deadline` is an absolute monotonic deadline. The module retains nothing between
calls. Its frozen dataclasses are the contract for the later summary producer:

| Shape | Fields and meaning |
| -- | -- |
| `SourceEntry` | `fact_id`, `fingerprint`, `kind` (`person`, `agent`, `check`, `file`), `actor` (`parent`, `subagent`), `stream`, `at`, masked `title`, optional `result`, display `path`, `folder`, grouping `subject`, and server-only `words`. |
| `UnreadRegion` | `start_offset`, `end_offset`, `reason`, `stream`. Offsets belong to the named stream, so two transcripts never share a byte coordinate. |
| `SourceCoverage` | `complete`, `starts_at`, `start_offset`, `end_offset`, `unread`, `agent_replies`, `checks_and_files`, `notes`. |
| `SourcePage` | `state` (`ok`, `unsupported`, `unavailable`, `stale`), `harness`, `sid`, tuple `entries`, optional `coverage`, `next`, `snapshot`, and tuple `notes`. Non-ok pages contain no entries. |
| `SourceCursor` | Source identity digest, tuple of `StreamCursor` frontiers, unresolved `PendingCall` inputs, session directory, and accumulated id/fingerprint/time and subject metadata. A stream frontier holds its file stamp, consumed offset, last complete-line boundary and SHA-256 digest, and bounded unfinished-line state. These are server-only Python values, not HTTP cursors. |
| `SourceSnapshot` | Parent `(device, inode, size, mtime_ns)` stamp, `end_offset`, `boundary_digest`, accumulated `(fact_id, fingerprint, at)` entries, read-only `subjects` mapping to latest fact and result/write fingerprint, `pending_calls`, continuation `cursor`, `message_ids`, and boundary hashes measured by this read. `verified_boundary` records a continuation's comparison against its previous boundary. `result_calls` names processed `(stream, call id)` result pairs, including a refused call that retracts an earlier unknown run. `snapshot(page)` returns this same value. |
| `SourceChange` | `kind`, tuple `changed` of `(fact_id, reason)`, tuple `appended` of new fact ids. |

Message ids come from `record_pages._fact`, including its title normalization and redaction.
Check and file ids use `project_context._semantic_fact_from_event` on the same tally events the
project context publishes for Full activity: `_check_entry` for a run and `_write_entry` for a
path. There is no separate tool-id hash in the source, so the two cannot drift. Result changes
move fingerprints, not ids. The published report lists one entry per check, its newest run, and
one per written path, its newest write; the source keeps every run and every write. The newest
run or write therefore carries the published id, and an earlier one, in an earlier call, carries
the id the same derivation gives its own call and time, which no published entry holds. Within
one compound call the published report puts every check's entry on the call's own id, so two
foreground runs there that share a title (the same check twice, or one check in two directories,
`cd a && pytest tests; cd ../b && pytest tests`) derive one published fact id, a collision the
published side carries and the source does not repeat. The source keeps one run per title in the
call on the call id, the one the published `_latest` would choose among that call's foreground
runs, and every other run supplies `<call id>:segment:<shell segment>` as the event's `record_id`.
A background run in the call is no candidate, so `pytest tests; pytest tests &` keeps the
foreground run on the published id. Two paths written in one call whose clipped titles match
likewise derive one published id; the first keeps it and each later one supplies
`<call id>:write:<n>`. Two source entries therefore never share an id, and the run or write left
on a segment or write id has no published entry. A citation to an earlier run or write is counted as one Full
activity cannot open rather than pointed at the newer entry, because a `failed` line citing a run
that later passed must not open the pass.

A fingerprint is 32 hexadecimal SHA-256 characters over masked content: title and whole words for a message; title, tool-reported result
and result source and recorded-result presence for a check; display path and call id for a file. Fact ids are keys. Displayed
`#n` labels remain derived at render time by the
[fixed-position index](design-session-record-pages.md#fixed-positions); neither an ordinal nor a
byte offset is a fact identity.

Entries preserve each transcript's physical order, including a message appended with an earlier
timestamp. Parent and subagent streams merge by the next entry's call time, parent first at a tie.
This deliberately does not globally sort a replayed message back into the past. Each check run is
its own entry; `subject` groups its check identity across runs and streams. A run launched in the
background, or moved there, is not a check entry: the published tool report drops those runs and
names a launch with no command text, so the source carries no command for one either. Each admitted write is
its own entry, grouped by path. Classification, masked command titles, write admission and the
paired call's result come from the existing project-context tally, with no second shell parser.
Only classifier inputs and already-emitted fact ids of unresolved calls cross pages; write contents
and old/new edit strings
are excluded. A result arriving on a later page may return an updated fact with the same id.

`words` contains the complete admitted, normalized and masked person or agent text, without a
reading's prompt cap. `entry_for_page` omits it, and the outline never copies it. The coverage
status is named `agent_replies` rather than `agent_words`, because `for_page` strips every
`agent_words` key as message prose and a privacy filter takes no exceptions.

### Coverage and continuations

`complete` means this call read from byte zero through the last complete line with no unread
region. It does not mean that every evidence type is admitted for the harness. `agent_replies` is
`read` or `not_read`; `checks_and_files` is `read` or `not_admitted`. The parent offsets delimit its
whole-line coverage. A partial final line is held for continuation and is never decoded before
its newline. `page.next` continues an incomplete read and is `None` once every stream has been
consumed to its end, including when a partial final line is held; even after reaching the current
end, `page.snapshot.cursor` can read a later append and completes that held line. The cursor accumulates only metadata and unresolved
inputs, not previously emitted message words.

`newest=True` begins at the first line boundary at or after `size - max_bytes`. It names `[0,
start_offset)` as `before_window`, and `starts_at` names the first emitted fact when coverage is
partial. Other unread reasons are `bytes`, `time`, `oversized_line`, and `unreadable_subagent`.
An oversized message is skipped before masking, as is a line above the line ceiling. Fragments
crossing page allowances are held only to that ceiling; oversized bytes are discarded while
hashing continues. A child with no readable allowance names `unreadable_subagent` as well as its
limiting region. An unreadable child's unknown extent is represented as `[0, 0)` with its stream
name, rather than invented offsets. A child's stream name is its path below `subagents/` without
the extension (`agent-<hex>` or `workflows/<wf>/agent-<hex>`), because admission accepts both
directories and one agent id can appear in each. Children are opened without following a link
swapped in after admission, as the published tool report's child reads are; the parent follows
links exactly where that report's transcript read does.

Boundary verification consumes the same byte/time allowance as new records. A smaller allowance
than the old boundary line may therefore return no new evidence; a caller must increase that
allowance to verify it. File identities and boundaries are checked before continuation and stamps
are checked again after reading. A source changed during the call returns `stale`; it is never
silently accepted as an empty session. Local filesystem operations and a single parse or masking
operation must return before the next monotonic deadline check can run; this is not I/O cancellation.

Change comparison works on either a full re-read or a continuation:

| Change kind | Evidence and reasons |
| -- | -- |
| `unchanged` | No new fact or changed fingerprint. |
| `appended` | Only new ids, with no earlier evidence changed. |
| `changed_earlier` | `content` for an earlier id's changed content; `check_result` for a pending result or a different result on a later run, naming the earlier fact; `file_rewritten` for another write to a previously written path, naming the earlier fact; `reordered` for a newly appended message older than the previous newest message. New ids also appear in `appended`. |
| `truncated` | Same inode, smaller than the previous consumed end. |
| `replaced` | Different device/inode or a different line digest at the old boundary. |

An unavailable page, or a stale page that establishes neither truncation nor replacement, cannot
establish `unchanged`: `compare` raises `ValueError` and the caller must restart the source read.
Scanning stops at `session_source_classify_share` short of the deadline, so classifying the calls
scanned usually fits. If classification still reaches the deadline, the calls already classified
and the messages before the first unclassified call's row are kept, the stream's frontier moves
back to just before that row, and the rest of the stream names `time`. The unclassified call and
any result already read for it are read again on continuation rather than lost; an earlier page's
unresolved call whose result lies past the new frontier is carried forward as pending. The first
row holding a call always classifies, so each page with a call makes progress. An earlier version
moved the whole stream back to where the page began; because the scan only stops once the deadline
has passed, that discarded every page holding a call and `page.next` repeated without end.

### Bounds and focused grouping

These are implementation allowances for reading and deterministic grouping, not the model-summary
job ceilings whose numbers still require measurement:

| RuntimeConfig field | Default | Decision |
| -- | -- | -- |
| `session_source_page_max_bytes` | 64 MiB | Match the press's image-heavy scan allowance; continue rather than sample. |
| `session_source_page_max_seconds` | 2 seconds | Match the press's time allowance. |
| `session_source_classify_share` | 0.25 | Hold back a quarter of that time from scanning for classifying what was scanned. |
| `session_source_line_max_bytes` | 16 MiB | Match the forward index's line skip before masking. |
| `session_outline_max_bytes` | 2 MiB | A focused poll pays less than a press and names its unread prefix. |
| `session_outline_head_bytes` | 256 KiB | Read the start of the record for the first prompt's part, once the newest window begins after it. |
| `session_outline_max_seconds` | 0.25 seconds | Bound work repeated on focused polls. |
| `session_outline_max_blocks` | 20 | Keep recent turns in a bounded focused response. |
| `session_outline_highlights` | 3 | Bound each block's failures, folders and check examples separately. |
| `session_outline_cache_limit` | 16 | Match the message-index cache's session count. |

`session_outline.build(page, config, opening=None)` returns `state`, `made_by: compass`, `basis:
grouping`, `reason`, `harness`, `coverage`, `blocks` and `more_blocks`. Each block has `prompt` (fact id,
title and time, or null for work before the first held prompt), `opening` and `partial` (below), a
`span` (first/last fact ids, entry count, from/to times), `counts` (checks, failing checks, fixed
checks, unknown checks, files, agent messages, subagent entries), bounded `failures` and `checks` (fact id, title,
tool-reported result), and bounded `folders` (folder and write count). Folders sort by count
descending then name; check examples and failures keep the newest entries in their block. Rewrites
count as write entries, not unique paths. The block cap bounds the newest parts; extra parts are
dropped from the front of those and counted in `more_blocks`, and the opening part is never one of
them.

**A fixed check.** A failed run that a later passing run of the same check followed, anywhere in
the read, is a red test that was fixed. Matching is by the check's `subject`, so it holds across
parts and across the parent and its subagents. `checks_failed` counts checks whose newest failed
run in the part no pass followed, one per check, and `failures` lists exactly those, one row per
check: a check run twice and failing twice is one failure. `checks_fixed` counts the checks whose
newest failed run was followed by a pass. `counts.checks` still counts every run. A write is never
inferred from a shell command: a file an agent changed with a script rather than a write tool or a
redirect has no entry, and the part says nothing about it.

A check is listed as failing once. A check still red in a later part is the failure of the part it
first failed in; a later part does not list or count it again, and a pass between the two would have
made the first one fixed. A failure in the opening part is `checks_unknown`, not failing, when the
read ended inside that part, before the window began, or held later work the outline drops (`gap`):
a pass in that work would fix it, and nothing in the outline can say. The card says it did not read whether a later run fixed it.

This is Compass's grouping, never a summary or a completion verdict. Its titles quote the
existing masked evidence; its result tokens are as the tool reported. It authors no prose about
whether the requested work was delivered. It requires no model grant and makes no model call.
`for_session` resolves one transcript and caches only the built, word-free answer and summary plan,
under a lock. `for_session_with_plan` returns both from that same pass; no source words are cached.
The cache key includes outline and summary-plan bounds and parent and admitted child stamps; a
child-only append rebuilds the outline. An outline whose coverage names a `time` region is returned but not cached: the window
reads forward from its start, so a time-clipped outline lacks the newest turns, and caching it
would serve that until the transcript changed, for a finished session the life of the process. An unchanged transcript costs a stat, with admission discovery and a stat for each
owned child when present. Only a focused project/session answer gains `sources.outline`, before
`for_page`. When the focus matches no single row, `session_outline.unmatched` returns the same
labelled shape with `state: unavailable` and `reason: session_not_matched`, reading nothing. Session rows gain nothing.

### The outline always opens at the first prompt

The newest window is bounded in bytes, and a busy session passes the bound in minutes: an
eight-minute session with about 200 thousand output tokens produced an outline whose only part was
the work after the window began, headed by no prompt. The window is unchanged. When it begins after
byte zero (`coverage.start_offset` above zero), `for_session` makes one more read from the start of
the record, bounded by `session_outline_head_bytes` and by where the window begins so the two never
overlap, and keeps the first part that starts at a person's message. `build` shows that part first
with `opening: true`. `partial: true` marks an opening part whose read ended before the next
prompt, so its counts are a floor; the card says so. A complete read marks its own first part
`opening` and `partial` is false.

The head spends what the window left of the one `session_outline_max_seconds` budget, so a focused
poll never waits for more than that once; a head the window left no time for is clipped, and the
outline is not cached.

The head is a second read, not a larger window. A larger window would have moved the same cliff
to bigger sessions and made every focused poll pay for it; the head costs at most its byte bound
and is skipped when the window already starts at zero. A head read that its clock clipped is not
cached, as a clipped window is not. The block cap applies to the newest parts after the opening
one, so the outline holds at most the cap plus one parts. What lies between the opening part and the
window is named by `coverage` and is not outlined; Full activity lists it.

The card draws each part as a quoted prompt and short sentences ("The agent replied 7 times, ran 3
checks and wrote 5 files in frontend/src/drift."), not a line of counts. A count is said once: a
failing check has its own red row, and "ran N checks" counts every check run, a failing one included,
so the sentence adds no failure count of its own; a fixed check is said in the sentence in the plain
colour. A failure is an episode, the failed runs of one check with no pass between them: it is counted
fixed, or listed as still failing, in the first part it failed in and not again in a later part, while a
failure after a pass is a new episode. A failure the three-row highlight cap dropped was never shown, so
the next part that fails it lists it. A part carries no entry numbers, since `#1 to #13` named entries
the reader had not seen; only a failed check's row keeps a chip, once the page holds that entry.
A prompt's title is cut by the server and only there: it bounds the title at 112 characters (or the
goal cap, if that is lower), cuts back to a word and adds an ellipsis. A title of exactly the bound
that ends in a sentence stop is a whole sentence the bound happened to fit and is kept; one that ends
without a stop at exactly the bound cannot be told from a cut and is still clipped. The page's
180-character `trimPrompt` never meets a title from the server, so it is a backstop for text from a
source with no bound of its own. `ServerCutTitleEndsAtAWord` draws a title held in
`frontend/test/fixtures/server-cut-title.json`, and `test_session_outline` fails when the server
stops making that title from the fixture's prompt, which is how reverting the cut turns the story's
claim red. The card's notice and controls stand above the outline in every state, so they do not jump from
below it to above it when a summary opens or runs, and the read-size estimate sits in the row with
`Summarize`.

### Evidence admitted by this build

This table describes the implementation and does not amend the owner-ruled table above.

| Harness | Person words | Agent words | Checks and files | Outline |
| -- | -- | -- | -- | -- |
| Claude Code | Parent messages | Parent messages | Parent and admitted subagent transcripts | Yes, within the named coverage |
| Codex | Person messages | Not read; `codex_agent_words_not_admitted` | Not admitted; `codex_checks_and_files_not_admitted` | Yes, from person messages only |
| Pi and every other harness | Not read | Not read | Not read | `unsupported`, `reason: no_paged_record`, no disk resolution |

### Open questions

- Codex checks and files are not admitted pending an owner ruling. The earlier table's "From its
  bounded record sources" does not admit a command classifier or any command onto a page; this
  implementation reads none. That narrows the source issue's scope, which says a Codex read has
  person words, checks and files, so this build does not meet the Codex scope until the owner
  acknowledges the deferral. The follow-up the source issue requires, covering Codex checks and
  files, Codex agent words, and Pi and the other harnesses, is not yet filed or linked here.
- Resolved on 2026-10-19: a check or file entry's id is the id the context publishes for the same
  newest run or write. Measured before on the sample session through the development server, the
  outline's two failed checks were `fact:1b41…` and `fact:a84c…` while the context named them
  `fact:3d5b…` and `fact:f4cc…`. An earlier run of a check or an earlier write of a path still has
  no published entry, as the paragraph above records.
- The card says its outline starts partway only when `start_offset` is above zero or an unread
  region is `before_window`. `starts_at` is not that signal: it is set for any partial coverage, so
  a read from the start that stopped at its time or byte limit carries it too.
- The card reads the focused context itself, once per board revision, with no gate on annotations:
  under `--no-annotations` the Intent card's read does not run and nothing else on the session page
  would start one.
- Resolved on 2026-10-19: the sample session's fixture now carries `sources.outline` and a stored
  `sources.summary`, captured with its reading from one isolated server
  ([the sample's README](../sample-session/README.md#what-is-real-and-what-is-not)).
- Resolved on 2026-10-19: an absent summary's focused answer publishes
  [the focused plan](#the-focused-plan) from the outline's bounded source pass and cache, so the
  card says "in 4 parts, up to 10 minutes" before a start. Off a partial outline read the parts
  are a floor ("in at least"), and the minutes fall back to the whole-job ceiling.
- A summary citation's chip on a `said` or `asked` line reads older record pages for its fact id,
  because a message id is the record's own, so it either lands or says it could not be loaded.
  Record pages hold messages only, so a `did` or `failed` line and the lede get a chip for an
  entry the page holds, as the outline's chips do, read no pages, and say how many cited entries
  Full activity cannot open from here. With the ids aligned, a cited newest check run or write
  now lands on the context's entry on a cold reopen; only an earlier run or write is counted. The departure mark
  says only what a narrowed span still supports: with any summary id the page has not numbered, a
  departure is placed in a phase or a gap, or before a numbered start, and is otherwise unplaced.
- A summary left partway by Cancel, a revoke or a restart compares as unchanged, so the card offers
  Summarize again whenever the saved summary has a gap a rerun could fill, its lede stopped, or its
  last job ended partial, cancelled or interrupted. A `before_window` or `bytes` gap offers nothing,
  because a rerun meets the same limit. Whether a rerun's first saved part replaces the stored
  summary before the rerun finishes is the job's, not the card's; the card draws what is saved.
- The departure mark places a departure's cited entries against the summary by the activity list's
  `#n`. A phase publishes no bounds, so its span is the span its own bullets cite, and an entry
  between two phases is in neither ("inside the span the summary covers, but in no phase"). An entry
  the page has not numbered cannot be placed, and the departure card says so.
- Delete summary sits at the foot of a saved summary, beside What is sent. The ruling requires the
  control and names no place for it. Deleting does not summarize the session again on the same open.
- The view-only sample never posts an open start: its fixture carries a stored summary. Its board
  publishes the `summaries` block as a fresh store reads it
  ([the timeline rewrites](../sample-session/README.md#what-is-real-and-what-is-not)), so the card
  draws its controls, and the sample's guard holds every one of them ([View only](design-sample-session.md#view-only)).
- Subagent messages remain excluded. The existing ruling admits their checks and writes, while
  the message builder admits top-level messages only.
- A relative written path resolves against the directory at the transcript's head, read with the
  same bounded head read the published tool report uses, so a newest window that begins after a
  `cd` still names the same path the activity list does.
- A prompt before a clipped window is unknown. Work in that window has a null-prompt leading
  block; no earlier prompt is inferred from retained anchors or saved intent.
- Cursors are process-local Python values, with copy-on-extension hash state for unfinished
  oversized lines. Durable cursor serialization and on-disk snapshot loading belong to the future
  summary store, which must validate its own input; this module creates no store.

## Consent notice payload

Reader-started readings and goal summaries use the reading off switch, and a stored reading off
also refuses session summaries. Session summaries use `summary` notices with a durable off switch
of their own; the [job and grant contract](#job-and-grant-contract)
records their admission and publication shapes. No new session field is added.

- `board.reading.consent: bool` is true unless an explicit stored off exists, model calls are
  disabled for this run, or the store is unavailable. A missing store or missing answer is on.
  `board.reading.off: bool` reports an explicit stored off: a legacy or provider row with
  `allowed=0` and no row with `allowed=1`. This build's off writes 0 for every provider and its
  Resume clears them, so both values stand together only after an older build's Allow, which
  rewrote just the provider it allowed and left its own off's zeros; that store reads as on.
  Disabled/unavailable responses use false because they do not read that answer.
- `board.reading.reason: str` is `""`, `"daily-cap"`, `"model-calls-paused"`, `"run-disabled"` or
  `"store-unavailable"`. The master pause outranks the rolling cap when both apply; run-disabled and
  store-unavailable outrank both. Consent remains true at the cap unless off. The cap, reservation,
  spend ledger and job recovery are unchanged.
- `board.reading.notices` is an object keyed by kind, then provider (`codex` or `claude`). Missing
  kinds/providers have no recorded notice. Each last record is
  `{kind: str, provider: str, destination: str, content: int, tool_output: str, at: number}`.
  `at` is Unix seconds; `destination` names where the words go or is `""` when unknown;
  `tool_output` names its destination or is `""` when omitted. Content is the server's tier:
  `WORDS_CONTENT_VERSION` (1) without agent messages, `CONTENT_VERSION` (4) with them (Claude
  sessions and goal summaries).
- Each `board.reading_routes[harness].notice_due: bool` says whether a reading notice goes beyond
  that route's last record: no record, another destination, a wider tier, or a tool-output
  destination the record does not name. A narrower press to the same destination is covered by a
  wider record, so fallback routing that alternates tiers under one provider shows it once.
  It is false while off, disabled or unavailable; it may be true at the cap, though no reading
  can run then. The existing route's `provider`, `vendor`, `label`, `words_destination`,
  `destination`, `disclosure` and `disclosure_parts` name the provider, content and destination
  for the page to show beside the button before or beside the result.
- An admitted `POST /api/reading` replies 202 with `{ok: true, job, notice?}`. `notice` has exactly
  the record shape above and appears only when first recorded or changed; a second identical
  press omits it. `job.notice` is the same object when due, and the running entry in
  `board.reading_jobs["harness:sid"].notice` carries it through reloads. Jobs are removed when
  finished, as before; afterward `board.reading.notices` retains the last record. No new finished
  job persistence or session identifier is added to the permission store. A notice-store failure
  refuses the press with `store-unavailable`, without launching or charging a model. A press whose
  job cannot launch withdraws the notice it recorded, so the next press carries it.
- Pause model calls keeps the request `{consent: "off", press: true, observer_model: 1}`. It
  stores off for all providers, clears notices, and replies 200. It is accepted under
  `--no-annotations`, with no qualified reading provider, and under `--no-observer-model`, since
  goal summaries need none of those; the loopback, navigation, `observer_model` and `press` guards
  still apply. Subsequent presses reply 403
  with `reading.reason: "model-calls-paused"` and `reading.consent: false`.
  Resume model calls uses `consent: "on"` with the same press guards and starts no call.
  Older pages may still send `allow: true` with the route's provider and destinations. Stale Allow destinations still reply 409
  `destination-changed`; missing `words_destination` replies 400 `page-outdated`. A plain press
  after a destination change runs with a new notice instead. Off and `--forget` never reset spend.
- Project-context `observer_model.enabled: bool` is true by default and false under
  `--no-observer-model` or its alias. `observer_model.disclosure: str` states what a focused
  refresh sends, the configured destination and the off switches. `observer_model.notice?` has
  the same record shape with `kind: "goal"`, `provider: "codex"`, content 4 (the prompt carries the
  agent's messages) and `tool_output: ""`; it appears only when an actual goal call records a due
  notice, including a failed model attempt and a call made for an active child session.
  The page must still send `observer_model=1` on the focused refresh (the reader's act), with
  refresh, loopback and non-navigation guards unchanged, but removes its browser consent card.
  Passive or cached reads do not record notices. Goal status is `model-calls-paused` for stored off,
  `disabled` for the run's model refusal, and `consent-required` only when no reader request was
  supplied. A stored off is `model-calls-paused` even when the rolling cap is also spent. Goal calls
  are not charged to that cap. Notice storage failure refuses a goal call as `store-unavailable`.
- Legacy `providers`, `words`, `rebind` and `tool_output` keep their old explicit-Allow coverage,
  narrower words coverage, rebinding explanations and explicit tool-output grants. They do not
  describe default-on admission. The current page still reads them; the frontend lane must remove
  those uses for reader-started calls. Codex unasked checks require explicit `words.codex`
  coverage at the current destination; Claude Code uses the owner's acceptance without a separate
  grant. `unasked_routes[harness]`, published only while the lane is attached, is the route an
  unasked check of that harness takes, and its `disclosure_parts` is the words-only disclosure,
  excluding tool output, agent messages and outcome lines. The explicit toggle posts
  `unasked_grant: bool` with the session identity, provider, model, `words_destination`, `press: true`
  and `observer_model: 1` to the existing reading route, returning `{ok, produced: false, reading}`, or `{ok: false, reason}` with 409 for a stale route.
  It does not Analyze or lift Pause. It is refused while disabled/paused, without the startup flag,
  or with stale provider/destination or unsafe fetch metadata. Attention derives its waiting cue
  from typed-goal sessions whose `unasked_routes` entry is Codex, without current `words` coverage; no session field is added. `tool-output-consent-required` and
  `consent-required` no longer occur on the reading route. The client-contract fixture `reading-consent-required` is
  replaced by `reading-off` (a press after Pause model calls), since a fresh store no longer refuses.

The notice is non-blocking and names the words sent (including the agent's words on Claude
sessions), tool output where included, provider, destination and Pause model calls. A changed tier
or destination repeats it. An old explicit off survives upgrade; an old Allow is on, conservatively
showing the new notice once. Compatibility flags and the tool-output environment variable are
accepted no-ops for this release. No browser consent or implicit Allow is written by a plain press.

## Store contract

`summary_store.py` owns persistence only: no model seam, job, timer or automatic generation.
The job lane calls these functions with frozen runtime configuration and a source snapshot from
the read that produced the summary:

| Function | Return |
| -- | -- |
| `store_path(config: RuntimeConfig) -> str` | `config.state_home / config.summary_store_filename`, default `~/.compass/compass-summaries.json`; shared across ports. |
| `put(config, harness: str, sid: str, summary: Summary, snapshot: SourceSnapshot, *, made_at: float, model_stamp: str) -> str` | `stored`, `refused` (invalid shape or cannot fit alone), `unavailable` (unreadable existing store) or `unwritable` (lock/write failure). Redacts before validation and bounding. |
| `load(config) -> Store` | `Store(state="ok", entries: tuple[StoredSummary, ...])`, including an empty tuple for a missing file, or `state="unavailable"` with no records. This read does not touch access times. The parsed, redacted answer is reused while the file's device, inode, size and modification time are unchanged, because the board loads the store on every collection. |
| `get(config, harness: str, sid: str, *, now: float \| None = None) -> StoredSummary \| None` | A redacted record, or `None` for absent/unavailable. Persists last access time under the writer lock, at most once per `summary_store_touch_interval_sec` (one hour), so a focused poll does not rewrite the file; the interval is checked again after the locked reload, so two focused reads that both waited rewrite it once. A failed touch still serves the readable record. `now` defaults to wall time. Use `load` to distinguish missing from unavailable. |
| `delete(config, harness: str, sid: str) -> str` | `deleted`, `absent`, `unavailable` or `unwritable`. Never touches annotations. A missing store answers `absent` before any lock, creating no state home or lock file. |
| `forget(config) -> str` | `deleted`, `absent` or `unwritable`. A missing store answers `absent` before any lock. Deletes even an unreadable file under the writer lock, and also when the filesystem lock is unsupported, denied or cannot be created; only a lock another holder keeps past the wait answers `unwritable`. |
| `last_checked(state: RuntimeState, entry: StoredSummary \| None) -> dict[str, Any] \| None` | The `kind` and `reason` of the last focused report cached for this exact record (same made-at time, model stamp and block fingerprints), or `None`. Reads no transcript and stats no file. |
| `published(entry: StoredSummary \| None, *, available: bool = True, checked: dict[str, Any] \| None = None) -> dict[str, Any]` | Exactly one declared session-row field, `summary`: `exists`, store `state`, saved `coverage`, `made_at`, `out_of_date` (the `checked` report, or `null`), `job: null`. No blocks or prose. |
| `focused(config, harness: str, sid: str, page: SourcePage \| None, *, now: float \| None = None) -> dict[str, Any]` | Saved `Summary.as_dict()` plus `exists`, `made_at`, `model_stamp`, `out_of_date` and `job: null`; absent/unavailable states carry no prose. Comparison metadata never reaches HTTP. |
| `for_session(config, state: RuntimeState, harness: str, sid: str) -> dict[str, Any]` | Resolves the focused transcript through the observer and performs a bounded source read, then answers as `focused` does. The report is cached in runtime state per session, keyed by the transcript and admitted children's stamps and the stored record's identity, so reopening an unchanged session costs a stat; a read clipped by the time allowance is not cached. No model calls or grants are involved. |

`StoredSummary` holds `harness`, `sid`, `summary: Summary`, `snapshot: SourceSnapshot`,
`made_at: float`, `model_stamp: str`, and `accessed_at: float`. The model stamp is the job's
provider/model identity string; it is informational, not a grant or destination binding. A caller
must check its own grant and source stability before publishing a result. The store does not
serialize a resumable cursor. `get().snapshot` is for `session_source.compare`, not continuation
reads. The job re-reads the full source before calling `session_summary.update`.

The on-disk envelope is exactly `{"v": 2, "entries": [...]}`. Version 2 changes check/file
citation ids to the published derivation. This store is unreleased: version 1 is unavailable as a
whole, with no migration and no trusted stale citations. Loading never deletes it, and normal
save/delete refuses to overwrite it; an explicit `--forget` still removes it. Each entry admits
exactly `harness`, `sid`, `summary`, `source`, `made_at`, `model_stamp`, `accessed_at`. `summary` is the closed
`Summary.as_dict()` shape described above, including its lede, coverage, gaps and spend. Its
redacted UTF-8 encoding must fit `session_summary_max_bytes` (512 KiB). `source` admits only:

- `stamp`: four integers (device, inode, byte length, modification nanoseconds), `end_offset` and
  `boundary_digest`, for replacement and truncation checks;
- `entries`: fact-id/fingerprint/time triples, `subjects`: subject/fact-id/result-or-fingerprint
  triples, and `message_ids`, for source change classification;
- `pending`: objects holding only `stream`, `call_id`, `fact_ids`, to recognize a later check
  result. No pending tool input, source words, path, fragment, hash state or cursor is stored.

Harness and session keys are nonempty and bounded by `summary_store_key_cap_chars` (64), enough
for a full UUID, matching the annotation key width. The model stamp is bounded by
`summary_store_model_stamp_cap_chars` (256), because every focused answer resends it. All nested keys and primitive types are validated. Unknown schema versions, unknown fields,
malformed records, duplicate session keys, torn JSON and oversized files refuse the whole file.
A normal save/delete never overwrites such a file. Every string is redacted with
`records.redact_secrets` on entry and again on read, before serialized size checks, because another
local process can rewrite the file. Identifiers are matched rather than read, so they are checked
instead of rewritten: when redaction would change the harness, session id, a citation, a block's
first or last fact id or fingerprint, or anything under `source`, a save is `refused` and a load is
unavailable. A redacted key would be unreachable by `get` and `delete`, and a second save would
write a duplicate key that refuses the whole file. Redaction does not authenticate the prose or its citations.

`summary_store_max_bytes` is **64 MiB**: 64 summaries x 512 KiB = 32 MiB, plus 32 MiB for comparison
metadata and envelopes. This is a chosen retention budget, not a measurement or a promise that
64 unusually large snapshots fit. Actual serialized UTF-8 bytes determine eviction, dropping the
least recently read/written record until the file fits; the entry being saved or touched is kept.
If it cannot fit alone the write is refused. There is no age expiry. The file is independent of
`compass-annotations.json`, so even a worst-case summary set cannot evict saved intent.

Each mutation and access-time touch takes a path-keyed process lock followed by
`io.held_file_lock(filename + ".lock")`, with one deadline (`summary_store_lock_wait_sec`, default ten seconds), across the fresh read,
eviction and rename. Unsupported or unavailable locks refuse writes; unlike irreplaceable saved
intent, summaries can be regenerated. `forget` is the exception: it is an irreversible privacy
delete, not a write that could be lost, so only a busy lock stops it. `io.atomic_write_owner_only` creates a randomized exclusive
0600 temporary file in the state home and replaces the target atomically. Two writers serialize
and readers see one whole envelope. These files have the same advisory Windows permission limit
as the other Compass stores.

Freshness reuses `session_source.compare` and `session_summary.change_report`, which is also the
check used by `update`, without a model call. `out_of_date` carries `kind`, `reason`, zero-based
`affected_blocks`, `new_entries`, `appendable` and `action`:

| Kind | Action |
| -- | -- |
| `unchanged` | None; serve the saved summary without a summary call or charge. |
| `appended` | `update`, with the number of new entries; offers Update summary. |
| `changed_earlier` | `summarize_again`, naming affected blocks; offers Summarize again. A `check_result` change wholly inside the newest block is appendable and offers `update` instead. |
| `truncated` or `replaced` | `summarize_again`; keep the saved blocks visible with their age. |
| `unavailable` | No action; source missing, unreadable or incomplete. Never infer freshness from missing evidence. |

Freshness is computed only for the focused answer. Board collection loads stored metadata once
and reads no transcript for this field. A row carries the `kind` and `reason` of the last focused
report this process cached for that same record, and `out_of_date: null` when it has none. That
report is as of the last focused check: an append made since moves it only when the session is
opened again. The focused
read uses the source's byte/time allowance. If that cannot reach every prior span, freshness is
unavailable (`source_incomplete`), preserving the summary. Physical truncation/replacement can
still be reported from an incomplete read. A read stopped by the byte allowance is cached while
the transcript is unchanged: the same allowance would stop at the same place, and a finished long
session would otherwise pay that read on every focused poll. A read whose coverage names a `time`
region is returned but not cached, as for the outline: a slow disk or a loaded CPU stops it early,
and caching it would show a finished session as unavailable for the life of the process. A report's `reason` may additionally name a span
mismatch or late evidence, which requires Summarize again.

`GET /api/project-context?...&session=harness:sid` attaches this answer as `sources.summary` beside
`sources.outline` only for one matched session in the project. A project-only answer has neither
summary prose nor an implicit summary call. `POST /api/summary/delete` accepts exactly
`{"harness": "...", "sid": "..."}` and returns `{"outcome": "..."}`. Loopback, Host/Origin,
fetch-site and non-navigation guards run before parsing the body or reading the store. Local
processes without browser metadata can delete summaries; this is not authentication.

`--forget` deletes this file even with annotations disabled. Discard everything deletes the
discarded session's entry from it (see
[the amendment](#amended-2026-10-21-owner-discard-everything-also-deletes-the-summary)), and
leaves every other session's.
The ruling was silent on `--no-annotations`: it does **not** govern this independent store.
`--no-observer-model` is the job's call gate and does not hide or prevent deleting saved summaries.
Start/cancel routes and summary generation follow the [job and grant contract](#job-and-grant-contract).
Neither `events.PATCHABLE` nor `history.OBSERVATION_FIELDS` admits `summary`: events cannot write
this store-derived field, and session observation history must not duplicate summary state or prose.


## Job and grant contract

`summary_jobs.py` owns the server thread and its slot, independent of Analyze. Only Claude Code
summaries are admitted. Leaving the page does not stop a job. There is no interval or timer, and
GET requests never start summary work. Opening a finished session is expressed by the page as an
explicit POST with `origin: "open"`.

### Requests and replies

Every summary POST first checks loopback, Host/Origin, fetch site and document navigation, before
parsing the body or touching the store. Rejected transport metadata answers 403. Local processes
without browser metadata remain admitted; this is a loopback boundary, not authentication.
Malformed JSON, unknown keys, invalid identity strings and invalid action/origin pairs answer 400;
bodies above `annotation_body_cap_bytes` answer 413. Identity widths use
`summary_store_key_cap_chars`, not a second limit.

`POST /api/summary` accepts exactly one of these shapes:

```json
{"harness":"claude","sid":"session-id","action":"start","origin":"open"}
{"harness":"claude","sid":"session-id","action":"update","origin":"press"}
{"harness":"claude","sid":"session-id","action":"rerun","origin":"press"}
{"consent":"off"}
{"consent":"on"}
```

`start` also accepts `origin: "press"`. Open accepts only `start`, only for a published session
with `ended_at` set, no stored summary, and summaries on. It refuses `session-running` or
`summary-exists` with 409 and does no model work or charge. `session-unavailable` also answers
409 without confirming whether an unlisted session exists. An unavailable summary store answers
503 `store-unavailable`, never masquerading as an absent summary. Store presence is checked again
under the publication lock at admission, so an open racing the previous job's final save cannot
launch a second job. Later opens continue to read `sources.summary` from the focused GET.

An admitted start/update/rerun answers 202:

```json
{"ok":true,"job":{"id":"random-id","state":"running","part":0,"parts":12,"reason":"","finished_parts":[],"attempts":0,"started_at":1900000000.0,"notice":null}}
```

When a notice is due, `notice` in the job is the record below and the same record also appears as
`notice` beside `job` in that response. An identical later job omits that top-level key. Notices
are non-blocking: no Allow reply is needed.

```json
{"kind":"summary","provider":"claude","destination":"Anthropic","content":1,"tool_output":"","at":1900000000.0}
```

The server's disclosure names exactly what is sent: redacted session text in 16 KiB menu windows
with the person's words, relayed text in a person turn, agent replies, masked check titles with
`failed`, `passed` or `not-recorded` as their per-check tool-reported result, and file-write display
paths. Earlier phase titles are context, and cited menu entries are resent for the lede. No tool
output is sent because the source admits none. The notice names Claude Code/Anthropic, the
configured destination (or that it is unknown), Turn off summaries and Turn summaries on. A wider
content tier or changed destination shows it again. An unnamed destination has the same detection
limit as a reading route: changes between two unnamed endpoints cannot be distinguished.

Since 2026-10-20 the disclosure says those facts in plain words, with the destination first and
the redaction fact after the list it covers: "Sends to
Anthropic through your Claude Code, at most 16 KiB at a time: your messages, text relayed in your
turn, the agent's replies, check names with their result (failed, passed or not recorded), and
the paths of files written. Titles of earlier parts go along as context, and the entries a summary
cites are sent again for its opening line. Everything is redacted first. No command, file or other
tool output is sent." The usability review read "lede" and "the source admits none" as jargon, and
read "No command output" as leaving file reads and fetched pages open, so the sentence names every
tool kind. The sample
session's fixture carries this wording since it was captured again on 2026-10-20, because it is
rebuilt from a real server reading and never edited by hand; `test_sample_session_files` fails when
the two differ.

An independent stored off is honoured through restart and upgrade. While the master is not paused, grant presses answer
`{"ok":true,"summaries": <the board summaries block>}` with 200 (503 on store failure), including
under `--no-observer-model` and `--no-annotations`. They change neither Analyze's answer nor a
stored goal-summary answer. `--no-observer-model` refuses every model call with 503 `run-disabled`.
Summary off refuses starts with 403 `summaries-off`; the rolling cap refuses them with 429 `daily-cap`.
A stored master pause refuses starts with 403 `model-calls-paused` and stops each later part.
The summary `off` field still reports only the summary answer. Summary-switch presses while
paused answer 403 `model-calls-paused` and leave that answer and its generation untouched.
Turning summaries off, and Pause model calls, stop every job this process runs: the job is marked
`stopping` with that reason, its marker is rewritten, and a call already spawned is cancelled. A
part already charged rechecks the grant after the board publish that follows its charge and before
the model seam, so an off that lands in between sends nothing (the charge stays).
The master pause outranks the cap and summary off in board status; neither turning on nor off resets spend. `--forget`
stores summaries off and model calls paused, summaries first, so the summary off is written even
when model calls were already paused and survives a later Resume model calls. It forgets the answer
as Pause model calls does, and the ruling is silent on whether forgetting should instead return to
the default of on, so the conservative reading is kept. It never resets the summary ledger.

`POST /api/summary/cancel` accepts exactly `{"harness":"claude","sid":"session-id"}`.
It answers 202 `{"ok":true,"cancelling":true}` when a job is running, otherwise 409
`{"ok":false,"reason":"not-running"}`. An unavailable publication lock or an unwritable marker
answers 503 `store-unavailable`. A marker that cannot be parsed is rewritten from the job this
process runs, or removed when no such job is running (cancel then answers `not-running`); Delete
summary still deletes, and startup recovery removes such a marker rather than leaving the session
in flight. If the publication lock is unavailable when a job ends, its own marker is removed
without the lock, since the slot is that job's. It keeps already saved parts and refuses later replies.
The identity names the current job, so a stale tab can cancel a newer job on that same session;
this conservative choice follows the specified identity-only request. Delete uses the existing
`/api/summary/delete` shape and outcome; it cancels the job and deletes the stored summary under
the publication lock; a lock failure answers the existing `unwritable` outcome. Discard
everything, on the Intent card, does the same under the reason `discarded`: `summary_jobs.discard`
stops the job and deletes the session's entry in one step under the publication lock, and
`/api/annotate`'s clear arm calls it after a clear that landed over words that existed (see
[the amendment](#amended-2026-10-21-owner-discard-everything-also-deletes-the-summary)).

`update` requires a stored summary (`422 no-summary` otherwise), fully re-reads the source and
calls `session_summary.update` with its saved snapshot. Only new evidence is sent, subject to the
producer's newest-block check-result exception. Earlier source changes refuse before any call;
`rerun` calls `summarize` fresh. A part saved while the job runs carries the windows not yet
answered as one `stopped` gap, with `lede_reason: "stopped"`, so a summary left by Cancel, a revoke
or a restart names what it does not cover instead of comparing as unchanged against a snapshot of
the whole read. The producer's final result is offered for saving even after a ceiling or the cap
stopped it, keeping its named gaps; it is never offered when its state is `refused`. Only the
producer's own stops (`daily-cap`, `model-unavailable`, `stopping`) still save; every publication
bar (a grant, generation or destination change, either off switch, Cancel, Delete summary, an
unavailable store) refuses the save. An update's intermediate parts carry the saved lede, so an
update stopped part-way keeps it. An update re-reads the stored summary under the publication lock
at admission and refuses `no-summary` (422) if Delete summary removed it since the request read
it, or `summary-changed` (409) if another job replaced it. Summarize
again covers the remainder; an unchanged update preserves the saved answer. A start on a session
whose job is still `running` or `stopping` answers 409 `in-flight` before the source is read.

### Published fields

The grant is published as a board-level `summaries` block, beside `reading` but outside the
`annotate` group, because the summary store does not depend on the annotation store and so the
block is present under `--no-annotations` too. It is not `summary`, because that key already
holds the board's session counts. The grant-press reply and the start refusals carry the same
object under `summaries`:

```json
{"consent":true,"off":false,"used":0,"limit":200,"retry_at":null,"reason":"","notice_due":true,"provider":"claude","destination":"Anthropic","disclosure":"server-authored disclosure","notices":{}}
```

`notices` maps provider `claude` to the last summary notice record; it is empty before the first
notice. `consent` is true by default and at the cap, false while explicitly off, run-disabled or
store-unavailable. `off` means an explicit stored off (false when that answer cannot be read).
`retry_at` is Unix seconds for the oldest unexpired charge plus 24 hours when at the cap, otherwise
null. `reason` is exactly `""`, `daily-cap`, `summaries-off`, `model-calls-paused`, `run-disabled` or
`store-unavailable`; `consent` is also false under `model-calls-paused`. Under `--no-observer-model`, `off`
still reads the stored summary answer, read-only, while `reason` stays `run-disabled`.
The summary content tier is 1 and has its own epoch, independent of the reading's epoch.

Each row's already-declared `summary.job` and focused `sources.summary.job` is null until this
process knows a job, then the exact job shape in the 202 example. No prose is added to board rows.
`part` is the current one-based part, or zero before work; `parts` is the planned retained windows
plus one lede. `finished_parts` contains one-based parts successfully saved, including a finished
window represented by a gap. `attempts` counts charged seam attempts, including retries. While a
part is in flight the page can say `part 3 of 12`. Terminal metadata stays in the runtime's bounded
`max_cache_entries` registry until replaced or evicted; saved prose stays in the summary store.

Job states are `running`, `stopping` (Cancel accepted while the worker unwinds), `complete`,
`partial`, `cancelled`, `refused` and `interrupted`. A restart never resumes a job: a dead marker
becomes an `interrupted` job carrying its saved part numbers and charged attempts. Terminal
metadata itself is not a new persistent store. A later restart without a marker still serves
saved prose, but no longer carries that process's terminal job metadata.

Job reasons are `""`, `cancelled`, `deleted`, `summaries-off`, `model-calls-paused`, `grant-changed` (including
off then on while a reply was in flight), `destination-changed`, `daily-cap`, `run-disabled`,
`store-unavailable`, `stopping`, `model-unavailable`, `interrupted`, `job-failed`, `store-refused`,
`store-unwritable`, and producer outcomes `gaps`, `bytes`, `source_incomplete`, `no_entries`,
`ceiling`, `refused`, `stopped` or `output_bound_too_small`. The job is `cancelled`
for cancel and delete, `refused` for other reasons with no finished parts, and `partial` when
parts were kept. A recovered marker is always state `interrupted`, preserving its stop reason if
one was recorded. Stored summary states and gap tokens remain the producer's contract above.

Admission failures use `{"ok":false,"reason":"token"}`. An occupied slot adds `job` (possibly
null when another process holds it) and answers 409 `in-flight`. Other preflight refusals answer
422 with the producer's `plan` and `largest_read`: `harness_not_supported`, `invalid_bounds`,
`planned_calls`, `planned_bytes`, `planned_seconds`, `output_bound_full`, or source-change reasons
`truncated`, `replaced`, `changed_earlier`, `late_evidence`, `span_mismatch`, `unknown_change`.
A missing/unreadable source answers 422 `source-unavailable`; a marker that cannot be written
answers 503 `job-unrecorded`; a thread that cannot start answers 503 `no-thread`. Both spend
nothing and withdraw any notice they recorded without launching.

```json
{"reason":"planned_calls","parts":12,"largest_read":{"windows":32,"window_bytes":16384,"calls":37,"bytes_sent":786432,"seconds":600,"call_timeout":180}}
```

`largest_read` gives the maximum retained window count under the configured window/call limits
and the independent byte/time bounds, not a promise that arbitrary entries fit all of them.
The byte plan includes instructions, earlier-title allowance and a whole lede window. Preflight
refuses without charging if any planned bound fails. The producer rechecks whole-job ceilings at
every attempt; no call starts unless its entire timeout fits within the remaining 600 seconds.

### The focused plan

For a matched focused session with no summary and a readable store, `sources.summary.plan` is:

```json
{"reason":null,"complete":true,"parts":4,"windows":3,"calls":8,"minutes":10,"largest_read":{"windows":32,"window_bytes":16384,"calls":37,"bytes_sent":786432,"seconds":600,"call_timeout":180}}
```

It is `session_summary.plan` run on the entries of the outline's own source pass, so it costs no
second transcript read, no grant and no model call, and it is cached with the outline under the
same stamps, bounds (the summary ceilings included), eviction and refusal to cache a time-clipped
read. `parts` is the retained windows plus one lede (zero for no entries) and `windows` is
`parts - 1`. `reason` is the token the 422 preflight would give for these entries
(`planned_calls`, `planned_bytes`, ...) or null. `largest_read` is exactly the 422 refusal's
object, so the largest read allowed has one shape wherever it appears, rather than a second
bytes-only field under the same name.

`complete` is the outline read's own coverage. The outline reads a newest window of at most
`session_outline_max_bytes`, while a start reads the whole source, so off a partial read `parts`
is a floor. `calls` is an upper bound on charged attempts: with a complete read it is
`min(parts x session_summary_attempts_per_part, session_summary_max_calls)`, because a part makes one retry
after an empty reply and no more; with a partial read it is the whole-job call ceiling. `minutes`
is `ceil(min(calls x session_summary_call_timeout, session_summary_max_seconds) / 60)`, an upper
bound from configured ceilings, never a timing measurement.

The card says "About N entries to read in N parts, up to N minutes", "More than ... in at least N
parts" for a partial read, with singular forms as needed. Without a plan, with no parts, or with a
plan the preflight would refuse, it keeps its previous entry-count sentence. The plan is null when
a summary exists, the store or source is unavailable, the focus is unmatched, or the harness is not
Claude Code. It is focused metadata only, never a session-row field.

The entry count in that sentence is the numbered list's, the same figure the session header and the
since-intent count read. The list holds the newest record pages (fifty entries each), so while older
pages remain unread the count is a floor: the card says "More than N", and the header says "at least
N entries", rather than quoting one page as the whole session.

### Markers, charges and publication

One hashed session path in `state_dir/summary-jobs/` is the cross-process slot. It is written before
the first atomic charge, contains only job/session identifiers, pid, times, destination/grant
generation and progress (never source text or model prose), and is removed after the worker ends.
Startup takes `summary-jobs.lock`, recovers dead markers once, and leaves live processes alone.
Finished parts have already gone through `summary_store.put`; recovery makes no model call.

`summary_permission` and `summary_spends` are new tables in `compass-reading-permission.sqlite3`.
The first holds `id`, `allowed`, `generation`; the second holds a primary-key `receipt` and `at`.
A receipt is random job id plus one-based attempted call number, never a harness/session identity.
Each transaction checks off and the rolling 200-call cap, inserts once, and commits before the
model seam. Failed, empty and timed-out attempts stay charged. Receipts remain for 30 days for
restart accounting; only the newest 24 hours count against the cap. Analyze's `spends` and
`spend_jobs` are untouched. Revocation never refunds either ledger.

Every part checks the summary grant generation and current destination again, even after a
previous part was admitted. The tool-output tier is fixed absent on this source, so no legacy
Analyze tool-output grant is borrowed. Publication checks the same gates under the lock used by
Delete, Cancel and grant presses. A reply admitted before a revoke cannot publish after
it, even if the reader has since turned summaries on again. The last admitted call may publish
at the rolling limit; a refused subsequent call publishes nothing. Nothing from that call or a
later part overwrites the finished prefix. The supervised Claude call uses the summary system
prompt and configured per-call timeout; the stored model stamp includes the prompt's SHA-256.
