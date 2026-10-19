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
3. **Summaries get a new store under the Compass home.** A summary must exist without an intent and
   must not be removed by Discard everything, so the annotation store cannot hold it. The store has
   its own SECURITY.md invariant 2 row, its own aggregate byte bound and an eviction that can never
   push out a reader's saved words, redaction on the way in and on the way out, a Delete summary
   control, and a place in `--forget`.
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
- `--no-observer-model` still refuses every model call. Turn off readings and Turn off summaries
  remain, and an answer of off already stored is kept: a reader who turned readings off is not opted
  back in by the upgrade.
- A changed destination shows the notice again, naming the new destination, rather than a blocking
  Allow.
- `--allow-tool-output` and `--observer-model` become accepted no-ops for one release.
- Summaries keep their own grant, cap and ceilings. Analyze's rolling cap is separate and unchanged
  at 100 attempts per 24 hours.

The product promise still holds, in the owner's words "nothing leaves your machine that you cannot
switch off", because the off switch is one press from the card and one flag at startup. The promise
map's wording for this changes with the work that ships it, not in this record.

### The layout reversal

[DEC-27](design-reading-a-session.md#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result),
as amended by the owner on 2026-10-12, made the session page two columns from 1101px: activity on
the left, the Intent and drift panel on the right. The owner reversed that amendment for this
milestone on 2026-10-19. The page becomes one column, top to bottom: the header, the answer block
when the session needs input, the Intent card, the What the session has done card, the Drift card,
and a collapsed Full activity section. The session page's More disclosure is retired, with every
control, sentence and limit in it given a new home, so DEC-27's principle that a privacy promise or
an honest limit moves and is never deleted still holds.

## What this amends, by name

| Earlier ruling | What changes | What stays |
| -- | -- | -- |
| [DEC-15b](design-reading-a-session.md#dec-15b-an-assessment-may-be-stored): "No new store, and no field admitted by implication." | A new summary store is admitted, by name, for summaries only. | Every summary field is still named and admitted; nothing is admitted by implication. The annotation store still holds readings. |
| [DEC-18](design-reading-a-session.md#dec-18-an-unasked-reading-is-permitted-and-gated-on-delivery-first) | Not engaged. A summary made on open is reader-requested. | The unasked lane, its preconditions and its default off. |
| [DEC-27](design-reading-a-session.md#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result), the owner's 2026-10-12 layout amendment | Reversed for this milestone: one column, More retired. | The signed table's principle that a promise or limit moves and is never deleted. |
| [SECURITY.md, Light harness usage](../SECURITY.md#light-harness-usage-asking-a-harness-a-bounded-question), "Opt-in, and off until answered" | Becomes opt-out with a notice for calls a reader's action starts. | The operator's own harness, redaction before it leaves, one bounded question, visible spend, the off switches, and "Future harness callers need their own entry", which [Session summary calls](../SECURITY.md#session-summary-calls) answers. |
| [Amended 2026-10-01: the first press is a consent step](design-reading-a-session.md#amended-2026-10-01-the-first-press-is-a-consent-step) | Superseded: the first press runs and shows the notice. | "Turn off readings" and its effect. |
| [Amended 2026-10-02 (owner): the Allow is bound to where the words go](design-reading-a-session.md#amended-2026-10-02-owner-the-allow-is-bound-to-where-the-words-go) | Superseded as a blocking step: a changed destination shows the notice again. | Detecting a change, and what cannot be detected while a destination is unnamed. A refusal still holds whatever the destination. |

The rulings that the consent change touches in passing, DEC-21 item 1 and its 2026-09-24
"Analyze drift and Allow and analyze" amendment, and DEC-23 item 7's fresh Allow for tool output,
are superseded for the same parts and for the same reason. Their other items stand.

## Alternatives rejected

- **A summary-only record in the annotation store.** It looked cheap because the store already has a
  lock, redaction and an owner-only write. It costs too much. The store's loader requires revisions,
  so a record with no saved intent needs a second record kind the loader must learn, and an older
  build that does not know it would refuse or drop it. Discard everything removes every record tied
  to a session's intent, so a summary would go with the words it did not depend on. And the store's
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
  check or a file write; otherwise `asked` when all are the person's words; otherwise `said` when all
  are the agent's words. The ruling does not assign a kind to a bullet that cites both the person's
  and the agent's words and nothing else; the build that makes the producer decides that case and
  records it here.
- **No completion words.** No string, lede, title or bullet, may say the work is fixed, done, working
  or verified. A check's result is quoted only as the tool's report, in
  [DEC-23 item 8's](design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work)
  wording ("as the tool reported"). A passed check does not show the requested work was delivered.
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
| The in-order, paged read with fact ids and fingerprints | `record_pages.py` and `project_context.py` |
| The summary producer and its closed-shape parser | A new producer module beside `reading.py` |
| The multi-part job, its ceilings and its own rolling cap | `reading_jobs.py`, `reading_policy.py` and `config.py` |
| The summary store, Delete summary and `--forget` | A new store module under the Compass home, and `cli.py` |
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

The owner pre-approved accepting the ceilings this measurement proposes. They are proposed values
until the build that enforces them records them in `config.py`.

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
