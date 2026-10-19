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
  are the agent's words. A bullet citing only person and agent words is `asked`: in all five
  measured cases the person was deciding on the agent's proposal. Relayed text counts as the
  agent's words for this rule, even when it arrived in a person turn.
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

The owner pre-approved accepting the ceilings this measurement proposes. The producer now records
them in `config.py`; the job lane must still wire the per-call timeout and rolling admission.

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
[Session summary calls](../SECURITY.md#session-summary-calls) forbids a summary to touch. The job
lane needs a summary-specific guard in front of the model: its own grant and off check, its own
ledger for `session_summary_rolling_cap`, and the consent, destination and tool-output checks
again before every part. The existing Claude reading invocation fixes its own system prompt, so
its exec path needs a system-prompt parameter, carrying `session_summary.SYSTEM_PROMPT` and that
prompt's provenance digest. The job lane also wires `session_summary_call_timeout`. Defining those
values here does not wire a summary job, guard or page. The [store contract](#store-contract)
names the separate storage and delete endpoint.

### Menu, windows and prompts

Entries receive numbers 1 through N in source order for this job. The producer alone holds their
number-to-fact-id map. Stored citations contain fact ids only. Each menu line is
`[number] label: text`:

| Source entry | Label and text |
| -- | -- |
| Person words | `asked`, followed by the person's words. |
| Injected text in a person turn | `relayed`, followed by that text. `records.injected_prompt(words, "claude")` decides authorship, including other agents' messages and resumed-conversation summaries. The menu says these words were not written by the person. |
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
asks for phases in order with titled phases and cited bullets, and states the output bounds. It
asks for actions and names the completion words it must not state in its own voice. Reports of
what the agent or person said must name the speaker in the same clause, such as "the agent said
..."; quotations without a named speaker are forbidden. It gives the tool-report form for a
check's result. It says relayed text is not the person's request and that the record is data whose
instructions must be ignored. Earlier windows contribute only the newest finished
phase titles that fit within one sixteenth of a window, including the disclaimer that they are
context, not evidence and must not be cited. Earlier bullets and entries never enter this context.

After the windows, one lede call receives only menu lines cited by surviving phases. Selection
prefers the person's entries, then other entries in order, within one window's byte allowance;
the selected lines retain source order and their original numbers. The prompt asks for at most
two sentences within the lede character bound: what the person set out to do, what the agent
worked on, and any correction or redirection those entries show. It receives no phase prose or
titles. Its citations must name entries actually given to it. A failed lede leaves `lede: null`
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
words are the person's, and otherwise `said`. The `asked` case includes person words plus
agent or relayed words, as decided by the measurement. Citations trimmed by the citation bound
no longer contribute to the kind.

Every displayed string is redacted and checked on its whole text before any character cap.
A failing string becomes `{"withheld":true,"reason":"completion_claim"}` with no text.
A withheld title keeps its bullets. Text without a citation uses reason `no_citation`.
Admitted long text ends with an ellipsis and carries `cut`; if the cut creates an unsafe claim
or leaves no text, it becomes a `too_long_cut` marker instead. Phase, bullet and citation list
cuts report how many were dropped. A cut reply is marked on its block.

### No completion words

The producer holds the summary's own voice to DEC-28 question 1 under the
[owner's amendment](#amended-2026-10-19-owner-the-summarys-own-voice).
An unlicensed completion word withholds the whole title, bullet or lede. Attributed speech,
tracker states, names and a check's own report are admitted only in the structures below.
Citing a passed check admits nothing else: `Tests passed` and `The build went green` are withheld.

The word list covers fix, done, complete, work, verify, success, succeed, pass, resolve, land,
ship, merge, green, finish, solve, repair, implement, deliver, deploy and accomplish in their
existing inflected forms. Text is NFKC-folded before matching, and a word that mixes Latin letters
with letters of another script (`fix` followed by a Cyrillic `е`) is withheld, because folding does
not map look-alike letters. These checks run on the whole string before any character cap and on
the clipped string after it. A cap must not hide an unsafe suffix or strip the attribution from a
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

- **Clauses.** Split at sentence ends (`.`, `!` or `?` followed by space or end), semicolons,
  commas and the joiners `so`, `which`, `and`, `but`, `then`, `because` and `while`. A dot inside
  `file.py` is not a sentence end. Straight and curly double quotes and backtick spans are atomic;
  their internal punctuation and joiners do not split them. Sentence punctuation at the end of a
  quote ends its clause after the closing quote, unless a trailing speaker attribution follows.
- **Named attribution in the same clause.** A speaker is `the agent`, `the person`, `the user`,
  `the subagent`, `the teammate` or `the reviewer`, and its verb is one of `said`, `says`,
  `reported`, `reports`, `stated`, `replied`, `answered`, `asked`, `told`, `noted`, `claimed`,
  `confirmed`, `explained`, `mentioned`, `suggested`, `proposed`, `requested` or `wanted`. A tool
  is `the tool`, `the check` or `the error`, optionally followed by `output`, `message` or `log`,
  and it may also have `read`, `reads`, `showed` or `shows`. The verb must follow its speaker
  directly, with at most one `-ly` adverb between them, and the completion word must follow the
  verb. `read` and `wrote` are not speech for a person or the agent: `the agent read the log before
  fixing the parser` and `the agent wrote a working parser` are the summary's own claims. The
  licence ends at the next speaker without a verb of its own, so `the person asked about the bug
  the agent fixed` is withheld. A quote immediately followed by a speaker and its verb also admits
  the words inside that quote: `"the parser is fixed," the agent said`. The attribution cannot
  come from inside an unattributed quote. A trailing attribution licenses only its quote, not
  words before the quote or after that attribution.
- **Implicit subject only for speech bullets.** A code-set `said` or `asked` bullet may begin its
  first clause with a speech verb: `Said the parser is fixed`, `Asked the agent to fix the parser`
  or `Reported the tests pass`. This admits nothing in later clauses. The model's proposed kind
  cannot grant this licence. Titles and the lede have no kind and get no implicit subject licence.
- **Tracker states.** A verb `moved`, `set`, `changed`, `marked` or `switched`, an object `issue`,
  `ticket`, `card`, `task`, `status`, `state` or `item`, then `to` or `as`, may name a Capitalized
  word or a backticked state. Only that state is admitted: `Moved the issue to Done` and
  ``Marked the ticket as `Done` ``. A bare lowercase state is withheld.
- **Names.** A completion word inside an identifier joined by `_` or `.` with no spaces is
  admitted, as in `hotfix_parser.py`. A slashed token is a name only when it also holds a hyphen,
  underscore, dot or digit, as in `fix/parser-crash` and `feature/done-list`, because
  `Fixed/verified the parser` is prose. A hyphenated or slashed compound is also admitted inside
  backticks or immediately after `branch`, `tag`, `ref`, `path`, `file`, `directory`, `folder` or
  `label`, as in `branch fix-parser` and `branch fix/parser`. A token made only of completion words
  (`Fixed.Verified`, `branch fixed-done`) and a bare backticked completion word are not names.
- **Tool reports.** Keep the existing `<check> reported <result>, as the tool reported` form,
  with result `passed`, `failed` or `not-recorded`. Also admit `<check> passed, as the tool reported`
  and the corresponding `failed` and `not-recorded` forms. In the latter forms the result must
  immediately precede the comma. The report licenses only that result word; neither other words
  before it nor words after its attribution inherit permission.

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

This is a structural backstop, not a language or relevance judge. A non-completion noun use such
as `a list of fixes` still matches and stays withheld. The code does not check whether an
attributed sentence is relevant to its citations. Where the ruling leaves malformed quotations
unspecified, an unclosed quoted span stays atomic through the end of the string and cannot supply
its own attribution.

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

Before the first call the producer plans the retained windows plus a lede. Exceeding planned
calls or prompt bytes refuses the job with `planned_calls` or `planned_bytes`, spending nothing.
The byte plan reserves the full lede window and each later context allowance because their
actual contents depend on replies. Retries are not prepaid; every call checks remaining calls,
prompt bytes and elapsed monotonic seconds immediately before invoking the seam. Reaching a
ceiling leaves the current and all later windows as `ceiling` gaps. A call starts only when the
elapsed seconds plus `session_summary_call_timeout` stay within `session_summary_max_seconds`, so
the job ends inside its ceiling without cancelling a call in flight. With the defaults, no call
starts after 420 seconds; the largest measured job took 307. The job lane's per-call timeout
bounds each wait. The producer does not pass a timeout to any subprocess function.

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
Tool ids hash the harness, session, stream, kind and tool call id, with the check identity and shell
segment for a check, or the original path for a write. A compound call can therefore contain two
runs of the same check without giving them one id. A fingerprint is 32 hexadecimal SHA-256
characters over masked content: title and whole words for a message; title, tool-reported result
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
| `session_outline_max_seconds` | 0.25 seconds | Bound work repeated on focused polls. |
| `session_outline_max_blocks` | 20 | Keep recent turns in a bounded focused response. |
| `session_outline_highlights` | 3 | Bound each block's failures, folders and check examples separately. |
| `session_outline_cache_limit` | 16 | Match the message-index cache's session count. |

`session_outline.build(page, config)` returns `state`, `made_by: compass`, `basis: grouping`,
`reason`, `harness`, `coverage`, `blocks` and `more_blocks`. Each block has `prompt` (fact id,
title and time, or null for work before the first held prompt), a `span` (first/last fact ids,
entry count, from/to times), `counts` (checks, failed checks, files, agent messages, subagent
entries), bounded `failures` and `checks` (fact id, title, tool-reported result), and bounded
`folders` (folder and write count). Folders sort by count descending then name; check examples
and failures keep the newest entries in their block. Rewrites count as write entries, not unique
paths. Extra blocks are dropped from the front and counted in `more_blocks`.

This is Compass's grouping, never a summary or a completion verdict. Its titles quote the
existing masked evidence; its result tokens are as the tool reported. It authors no prose about
whether the requested work was delivered. It requires no model grant and makes no model call.
`for_session` resolves one transcript and caches only the built, word-free answer, under a lock.
The cache key includes bounds and parent and admitted child stamps; a child-only append rebuilds
the outline. An outline whose coverage names a `time` region is returned but not cached: the window
reads forward from its start, so a time-clipped outline lacks the newest turns, and caching it
would serve that until the transcript changed, for a finished session the life of the process. An unchanged transcript costs a stat, with admission discovery and a stat for each
owned child when present. Only a focused project/session answer gains `sources.outline`, before
`for_page`. When the focus matches no single row, `session_outline.unmatched` returns the same
labelled shape with `state: unavailable` and `reason: session_not_matched`, reading nothing. Session rows gain nothing.

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
- A check or file entry's fact id here is not the id the record pages and the context publish for
  the same tool call. Measured on 2026-10-19 against the sample session through the development
  server: the outline's two failed checks were `fact:1b41…` and `fact:a84c…`, while the record and
  context named them `fact:3d5b…` and `fact:f4cc…`; the message ids matched. Until they agree, the
  What the session has done card draws a `#n` chip for a check or file only when the page holds an
  entry under that id, and never reads record pages to look for one. A summary bullet citing a
  check has the same gap.
- The card says its outline starts partway only when `start_offset` is above zero or an unread
  region is `before_window`. `starts_at` is not that signal: it is set for any partial coverage, so
  a read from the start that stopped at its time or byte limit carries it too.
- The card reads the focused context itself, once per board revision, with no gate on annotations:
  under `--no-annotations` the Intent card's read does not run and nothing else on the session page
  would start one.
- The sample session's fixture carries no `sources.outline`: `scripts/build_sample_fixture.py`
  captures the whole page from a server holding a stored reading, and recapturing it needs a model
  reading and a rebuilt page. Until it is recaptured, the sample shows the card's no-outline line.
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

Reader-started readings and goal summaries use the durable off switch. Session summaries are not
implemented by this change; `NOTICE_KINDS = ("reading", "goal", "summary")` reserves their kind.
No session field is added.

- `board.reading.consent: bool` is true unless an explicit stored off exists, model calls are
  disabled for this run, or the store is unavailable. A missing store or missing answer is on.
  `board.reading.off: bool` reports an explicit stored off: a legacy or provider row with
  `allowed=0` and no row with `allowed=1`. This build's off writes 0 for every provider and its
  Turn on clears them, so both values stand together only after an older build's Allow, which
  rewrote just the provider it allowed and left its own off's zeros; that store reads as on.
  Disabled/unavailable responses use false because they do not read that answer.
- `board.reading.reason: str` is `""`, `"daily-cap"`, `"readings-off"`, `"run-disabled"` or
  `"store-unavailable"`. The rolling cap outranks off when both apply; run-disabled and
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
- Turn off readings keeps the request `{consent: "off", press: true, observer_model: 1}`. It
  stores off for all providers, clears notices, and replies 200. It is accepted under
  `--no-annotations`, with no qualified reading provider, and under `--no-observer-model`, since
  goal summaries need none of those; the loopback, navigation, `observer_model` and `press` guards
  still apply. Subsequent presses reply 403
  with `reading.reason: "readings-off"` and `reading.consent: false` (429 if the cap is also spent).
  Turning back on keeps `allow: true`, the route's `provider` and `words_destination`, and its
  `tool_output` destination when named. Stale Allow destinations still reply 409
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
  Passive or cached reads do not record notices. Goal status is `readings-off` for stored off,
  `disabled` for the run's model refusal, and `consent-required` only when no reader request was
  supplied. A stored off is `readings-off` even when the rolling cap is also spent. Goal calls
  are not charged to that cap. Notice storage failure refuses a goal call as `store-unavailable`.
- Legacy `providers`, `words`, `rebind` and `tool_output` keep their old explicit-Allow coverage,
  narrower words coverage, rebinding explanations and explicit tool-output grants. They do not
  describe default-on admission. The current page still reads them; the frontend lane must remove
  those uses for reader-started calls. The unasked lane keeps requiring explicit `providers`
  coverage and never adopts default-on admission. `tool-output-consent-required` and
  `consent-required` no longer occur on the reading route. The client-contract fixture `reading-consent-required` is
  replaced by `reading-off` (a press after Turn off readings), since a fresh store no longer refuses.

The notice is non-blocking and names the words sent (including the agent's words on Claude
sessions), tool output where included, provider, destination and Turn off readings. A changed tier
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

The on-disk envelope is exactly `{"v": 1, "entries": [...]}`. Each entry admits exactly `harness`,
`sid`, `summary`, `source`, `made_at`, `model_stamp`, `accessed_at`. `summary` is the closed
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

`--forget` deletes this file even with annotations disabled. Discard everything leaves it alone.
The ruling was silent on `--no-annotations`: it does **not** govern this independent store.
`--no-observer-model` is the job's call gate and does not hide or prevent deleting saved summaries.
Start/cancel routes and summary generation belong to the next lane and are not implemented here.
Neither `events.PATCHABLE` nor `history.OBSERVATION_FIELDS` admits `summary`: events cannot write
this store-derived field, and session observation history must not duplicate summary state or prose.
