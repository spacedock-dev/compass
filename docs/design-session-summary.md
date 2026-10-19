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
| The in-order, paged read with fact ids and fingerprints | `session_source.py`, reusing `record_pages.py` message facts and `project_context.py` tool classification |
| The deterministic outline | `session_outline.py`, served on `/api/project-context` as `sources.outline` for a focused session only |
| The summary producer and its closed-shape parser | A new producer module beside `reading.py` |
| The multi-part job, its ceilings and its own rolling cap | `reading_jobs.py`, `reading_policy.py` and `config.py` |
| The summary store, Delete summary and `--forget` | A new store module under the Compass home, and `cli.py` |
| The one-column page and the retired More | `frontend/src/sessions/SessionDetail.tsx` |
| The ceilings' numbers | The measurement of a model summary against a deterministic outline |

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
