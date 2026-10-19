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

## Consent notice payload

Reader-started readings and goal summaries use the durable off switch. Session summaries are not
implemented by this change; `NOTICE_KINDS = ("reading", "goal", "summary")` reserves their kind.
No session field is added.

- `board.reading.consent: bool` is true unless an explicit stored off exists, model calls are
  disabled for this run, or the store is unavailable. A missing store or missing answer is on.
  `board.reading.off: bool` reports an explicit stored off (any legacy or provider row with
  `allowed=0`); disabled/unavailable responses use false because they do not read that answer.
- `board.reading.reason: str` is `""`, `"daily-cap"`, `"readings-off"`, `"run-disabled"` or
  `"store-unavailable"`. The rolling cap outranks off when both apply; run-disabled and
  store-unavailable outrank both. Consent remains true at the cap unless off. The cap, reservation,
  spend ledger and job recovery are unchanged.
- `board.reading.notices` is an object keyed by kind, then provider (`codex` or `claude`). Missing
  kinds/providers have no recorded notice. Each last record is
  `{kind: str, provider: str, destination: str, content: int, tool_output: str, at: number}`.
  `at` is Unix seconds; `destination` names where the words go or is `""` when unknown;
  `tool_output` names its destination or is `""` when omitted. Content is the server's tier:
  `WORDS_CONTENT_VERSION` (1) without agent messages, `CONTENT_VERSION` (4) on Claude sessions.
- Each `board.reading_routes[harness].notice_due: bool` says whether a reading notice differs from
  that route's last record in destination, tier or tool-output destination, or has no record.
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
  refuses the press with `store-unavailable`, without launching or charging a model.
- Turn off readings keeps the request `{consent: "off", press: true, observer_model: 1}`. It
  stores off for all providers, clears notices, and replies 200. Subsequent presses reply 403
  with `reading.reason: "readings-off"` and `reading.consent: false` (429 if the cap is also spent).
  Turning back on keeps `allow: true`, the route's `provider` and `words_destination`, and its
  `tool_output` destination when named. Stale Allow destinations still reply 409
  `destination-changed`; missing `words_destination` replies 400 `page-outdated`. A plain press
  after a destination change runs with a new notice instead. Off and `--forget` never reset spend.
- Project-context `observer_model.enabled: bool` is true by default and false under
  `--no-observer-model` or its alias. `observer_model.disclosure: str` states what a focused
  refresh sends, the configured destination and the off switches. `observer_model.notice?` has
  the same record shape with `kind: "goal"`, `provider: "codex"`, content 1 and `tool_output: ""`;
  it appears only when an actual goal call records a due notice, including a failed model attempt.
  The page must still send `observer_model=1` on the focused refresh (the reader's act), with
  refresh, loopback and non-navigation guards unchanged, but removes its browser consent card.
  Passive or cached reads do not record notices. Goal status is `readings-off` for stored off,
  `disabled` for the run's model refusal, and `consent-required` only when no reader request was
  supplied. Notice storage failure refuses a goal call as `store-unavailable`.
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
