# Reading a session against what you asked for

Compass lets a person type what a session should achieve and what it should produce, then shows
that beside what the record says. Whether it may go further, and say something about how the two
compare, is a product question rather than an engineering one, and it was settled by four rulings
rather than by code.

This file is where those rulings live for the code to cite. They were made on the Compass
Visibility 2x2 roadmap, now closed, and their full arguments stay on its issues, but a runtime
comment cannot cite a tracker, and the shape contract below is not background: three of its rules
are built into the producer rather than checked after it.

For what each runtime file owns, see [the module map](design-runtime-architecture.md). For what
survives a redraw, including the unsent drafts in these fields, see
[the reader-state inventory](design-reader-state.md).

## DEC-15: the floor and the overlay

Two permissions, and they are not the same permission.

The floor needs no authorisation. The words a person typed, the directive the deterministic
observer retained, the observed work evidence and the end outcome are shown side by side, with
their sources and their limits. Nothing compares them. The reader does.

The overlay is a model reading of that evidence against those words, and it happens only when the
reader asks for it. Evaluation on a cadence is refused, so there is no always on drift indicator
and nothing evaluates in the background. A verdict on whether the work met the request is refused
too, which is why the shape contract below governs something narrower than "was this met".

The ruling also asked for an evaluation rubric before automatic assessments are enabled. That
sentence is the one DEC-17 had to read carefully.

Amended 2026-09-23: a Drift mark read from a stored record is not the indicator this section
refuses, because it evaluates nothing on a cadence. [DEC-20](#dec-20-the-first-screen-shows-goal-beside-direction-and-drift-has-one-home)
says why and what may show it.

### Amended 2026-09-24: a live estimate runs after every turn

[DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn) amends this section and its
2026-09-23 amendment. A live drift estimate is computed after every turn, which is evaluation on a
cadence, and it shows a level in the Drift section and the session header. It uses no model: it
reads the checks and file paths
[DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) admits against the
reader's saved intent. The switch that shows it is off by default and lives in the browser only, so
off hides the level and the pill; it does not stop the server computing the level. The level never
reaches a row, a total, a notification or the unasked lane. The overlay is still a reading the
reader asks for, and a verdict on whether the work met the request is still refused.

### Amended 2026-10-23 (owner): the Live monitor may evaluate on a cadence while the session is viewed

The owner ruled on 2026-10-23, in these words:

> I actually disagree and believe tha the Live monitor should use model calls. Specifically (lets focus
> on Claude for the moment), when the Live Monitor is on and a user is viewing the session, a sidecar
> with the latest Haiku model should check and keep an eye on the session. The estimate should only run
> once per minute, and if the session has ended, the "Live monitor" should turn off (if it is on) and
> the toggle should be disabled (because there is nothing "live" to monitor). Also, if a user navigates
> away from the session, the Live monitor should not continue to run. We can also add a, "Do you still
> want to monitor this session?" banner that shows up after 20 minutes that will stay active in the UI
> for 10 minutes. If the user does not respond to the banner, the Live monitor will turn off with a note
> (so as to not drain a users tokens accidentally). If they do respond to the banner, if they
> responded, "yes", the TTL will reset and the live monitor will continue. If they respond "no", the
> live monitor will turn off.

This section's refusal of "evaluation on a cadence" and the 2026-09-24 amendment's "it uses no model"
are amended for one case and no other: the Live monitor, for Claude Code sessions, while the reader
is viewing the session. Everything else on a cadence stays refused. There is still no always-on drift
indicator and nothing evaluates in the background: a session nobody is viewing is never checked, and a
check never runs for a session the reader has navigated away from. Other harnesses are unchanged for now.
[The DEC-26 amendment of the same date](#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)
holds the rulings and the remaining decisions.

[DEC-16](#dec-16-compass-does-not-write-into-a-session) still applies, unamended: the check runs as a
supervised child, is never resumed into the watched session and is never injected into it. The overlay
the reader asks for, and the refusal of a verdict on whether the work met the request, are also
unchanged.

## DEC-15b: an assessment may be stored

An outcome assessment and the annotation revision it read persist in session history, so both
reopen after a restart and after the live row leaves the board. That is what makes the feature
useful the morning after rather than only while the tab is open.

The price is paid rather than avoided. Each stored field gets its own named admission in the
history allowlist, appears in the prompt derived carrier inventory, is redacted before it is
bounded, inherits the existing history bounds and retention, and is deleted by the existing forget
path. No new store, and no field admitted by implication.

### Amended 2026-09-10: the store is the annotation store

The ruling above names session history and gives its reason in the same sentence, so both reopen
after a restart and after the live row leaves the board. Measured afterwards, the annotation store
already does both. It is bounded by two counts with no time to live, and an annotation is keyed on
harness and session id with no project, so it outlives the row by construction. History was named
before anyone checked.

A reading is stored beside the revisions it read. Nothing in the paragraph above about redaction
survives unchanged only by luck: the one model authored field goes through the same redact before
clip scrub the two typed fields do, on the way in and again on the way out, because any local
process can rewrite the file.

Two consequences, both accepted rather than discovered. The forget command deletes session history
alone and does not reach this file, so a reader who wants a model authored reading gone clears that
session, which deletes the reading with the words that produced it. And there is no fourteen day
expiry: a reading is evicted when its annotation is.

What this avoided is worth recording because the alternative looked cheap. Admitting the five
reserved names to history needed five new flat published row fields first, plus the allowlist
entries, plus the schema bump. The obvious way to write that bump refuses every store already on
disk, and one test would have caught it.

One hazard was worth recording because nothing in the tree caught it, and it is now closed.
`history.py` returned a reset whenever the stored version did not equal the running build's, unlike
the dismissal store. The version bump that comes with the first admission would therefore have
discarded fourteen days of every existing user's history on upgrade, silently: the store rebuilds
itself from the next collection, so a wiped history looks like a quiet morning.

`history.READABLE_VERSIONS` is the closed set of versions the build can read. An admission bumps
`SCHEMA_VERSION` and appends the old value there. Every admission is additive, because each field
is re-validated on its own and a record written before a field existed is a record with that field
absent. A version outside the set is still refused, which is the case the reset header exists to
report.

Two fields are admitted, and five more are named without being admitted.

Admitted: `annotation_goal` and `annotation_output`, the words the reader typed, with
`annotation_revision` beside them. That is the baseline a reading is read against, and it is what
lets the baseline reopen after a restart and after the live row leaves the board. The annotation
store keeps the current annotation, bounded by a session count and a revision count; history keeps
what was true at each transition, bounded by fourteen days. Those are different questions and the
second is the one a retained assessment needs.

Admitting them cost a published-row change first, because this store may hold nothing the live
snapshot does not already serve and the allowlist admits field names rather than paths into a
mapping. The row published `annotation` as one nested object; it now publishes fifteen flat
`annotation_*` fields, and one helper in the bundle rebuilds the object the renderers read. A
nested carrier is also the shape the store's own tests ban for `tasks`, `subagents` and
`spacedock`, and for the same reason: a name cannot reach inside one.

The transition comparison widened with them. History appends on a change rather than on a sample,
and comparing `state` alone would have held the old words until the session happened to move again,
which makes the store's copy stale by construction.

Named and not admitted: `assessment_at`, `assessment_cutoff`, `assessment_revision_read`,
`assessment_goal_result` and `assessment_output_result`. Nothing produces a reading, so no row
serves them and the store may not hold them. The names are recorded here and in SECURITY.md so the
change that admits them does not re-argue the naming, and each still needs its own allowlist line.

### Amended 2026-09-12: a stored row says why it is not verifiable

A stored reading has to mean the same thing when it is read back later, and six of its demotions
did not. A constraint never put to the model, a departure the rules demoted for citing nothing,
rule 4's backstop and rule 7's three all stored as `not verifiable from available evidence` and
nothing else, which is what a model that said `unverifiable` on its own leaves behind too. Rule 2
is the exception, and it was measured rather than assumed: a reply that could not be read stores no
`result` at all, so the page tells that row apart without help. The page was right on screen, because
it derives the limit from today's harness table, and wrong in the store, because a reading re-read
after that table moved rendered a never-asked constraint as a model verdict.

Each criterion now carries `why`, a token from a closed set the producer owns: empty when the
result is the model's own, otherwise the rule that withdrew it. The page maps a token to a sentence
it already owns rather than printing it, so this field is not a second route for producer prose.
Tokens rather than sentences was the call, and it was made on the same ground the shape contract
stands on: the page's own re-derivation stays authoritative, and a stored reason fills only the gap
that derivation leaves.

This is the second downgrade cost stacked in one release, beside `revision_read_at`. Both land in
the same release on purpose: no shipped release carries either, so a reader stepping back meets one
refusal, not two. The refusal is the existing one. A build that does not know the key refuses the
reading whole, publishes `reading_refused` beside the press count, and writes the raw reading back
untouched, so stepping forward again reads it. A reading stored before the field reads back with
the reason absent, which is a reading with less in it, not a diverged one; a token this build does
not know refuses the reading whole, like every other bad value in the store.

### Amended 2026-09-24: an intent revision and a reading hold more

[DEC-24](#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
adds stored items, each taking its own admission under the rules above: a revision's window start
beside its save time (item 13), its outcome lines with each line's source (item 3, flat per-line
fields in the history copy), a reading's `evidence_through` (item 6), and a digest of each copied
correction, bounded per session (item 9). It adds one token, the reader's Not accurate mark on a
reading, stored with the annotation entry and removed with it, never sent and not reached by
`--forget` (item 10). It also changes when a reading may run: a session waiting at its prompt after
a turn stop may be read through its last turn (item 13).

The outcome lines cost a downgrade, and this one crosses a shipped release: v0.27.0 stores one
`output`. A build that old reads a revision holding lines as one with no expected output, and its
next save writes the lines away. It refuses a reading keyed by line and keeps it verbatim, as it
refuses any reading it cannot read. The owner accepted the loss on 2026-09-24. Going forward, a
revision or reading stored with one `output` reads as one typed line and is written back as lines
by the next save. The history copy carries up to six line fields where it carried one, so an
annotated session's records are larger and the size cap ages other sessions out sooner. The owner
accepted that too.

The larger store costs a second downgrade, and the owner ruled on it on 2026-09-24: the read limit
stays at 16 MiB. A build that old refuses a store over 2.5 MiB as unreadable, and its next save
writes every session's saved words away, not only the lines. This build does the opposite: a store
it cannot read whole, whether unreadable, over its limit or not JSON, is never written over, and
every save answers `untrusted` until the file is readable again, and the board says so in place
of "nothing typed". A missing store is not that state; it is empty and takes the first save. One
session's entry that this build cannot read, such as seven lines or an unknown source from a later
build, is kept as it was: it is written back unchanged, and a save, adoption or discard of that
session answers `unreadable` rather than renumbering it from revision 1.

The window start (DRC-4679) costs less, because the revision field is optional. A build without it
drops `window_start` from a revision on its next save, and that revision then opens at its save
time, which is what every build did before. A reading is different: it carries the key
`window_start` and may carry the scope token `last-turn`, and a build that knows neither refuses
the reading whole and keeps it verbatim, the existing refusal. It lands in the same release as the
outcome lines, so a reader stepping back meets that refusal once. A withheld reason this build adds
("This session stopped its turn moments ago...") reads back as no reason on an older build. The
session publishes `annotation_window_start`, a scalar time, and it is not admitted to
`history.OBSERVATION_FIELDS`: nothing in history reads it yet, so it stays out, as `settled_at`
does.

### Amended 2026-10-19 (owner): summaries get a store of their own

[DEC-28](#dec-28-a-model-may-summarize-a-session-and-the-summary-is-kept) amends this section's "No
new store", by name and for summaries only. A model-written summary of a session must exist without
a saved intent and must not go with Discard everything, so it cannot live in the annotation store.
It gets a store of its own under the Compass home, with its own SECURITY.md invariant 2 row, its own
aggregate byte bound and an eviction that cannot push out a reader's saved words, redaction on the
way in and out, a Delete summary control and a place in `--forget`. Every field in it is still named
and admitted; "no field admitted by implication" stands. Readings stay in the annotation store as
the 2026-09-10 amendment above says.

## DEC-16: Compass does not write into a session

A departure is raised to the reader and nowhere else. Compass does not write into an agent, and
the steer box holds a note in the reader's browser rather than sending one. Automatic correction is
withheld, including when a later instruction contradicts the annotation: that is an unresolved
baseline conflict for the person to settle, not agent drift for the board to declare.

### Amended 2026-09-24: a correction you copy, and a later direction you keep or add

[DEC-24](#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
amends this section in four places, and Compass still writes nothing into a session. It composes a
correction without a model, from your goal, your outcome lines with their state and the cited entry
numbers and times, for you to edit and copy (item 7). Sending it into the session stays refused;
DEC-25, the follow-on that would decide that, is not ruled (DRC-4698). Before an analysis, an
unsettled later direction is still detected and not judged: "Keep my intent and analyze" settles
every one of them, as "The baseline still applies" does, and "Add it to my intent" puts the
direction's raw text into a new outcome line for review (items 4 and 8). A later message that
matches a correction you copied is not an unsettled later direction (item 9).

### What is detected, and what is not

Built 2026-09-10. The distinction is the whole of the block, so it is written down rather than left
in the code.

**Detected: that you gave a later direction.** A person-authored entry in the observed record whose
time is after the revision you last saved and after anything you have already settled. Both halves
are available without a model: the annotation carries an epoch, every fact carries its own, and
`nextReadingPersonAuthored` already owns the authorship question, so rule 7 and this cannot
disagree about who wrote a row.

**Not detected: whether it conflicts.** Deciding that a later instruction contradicts a typed goal
is a reading of two prose strings, which DEC-15 refused and DEC-18 permits only behind four
preconditions that are not met. So the block asks and the reader answers. A block that claimed to
have found a conflict would be the false claim this whole tab exists to avoid, and the word
conflict does not appear in anything a reader sees.

Amended 2026-09-23: [DEC-20](#dec-20-the-first-screen-shows-goal-beside-direction-and-drift-has-one-home)
labels this block "Conflict to settle", decided knowing it breaks the sentence above. The label puts
a question to the reader and records no finding: what raises it is still any unsettled later
direction, the detected superset, and nothing reads whether the two strings disagree. A block that
claimed a contradiction was found remains refused.

**The suppression keys on the detected superset**, not on a declared conflict. Any unsettled later
direction demotes a departure to `not verifiable from available evidence`, inside
`nextCockpitReadingCriterion` with every other rule rather than as a filter over the departures
list: filtering would leave the word `departure` rendered in the row above, which is the verdict
DRC-4511 forbids, on screen. Over-suppression is the safe direction, and the cost is a suppressed
departure on a session where the reader steered without contradicting themselves, which one click
clears.

**The answer is a settlement**, three scalars in the annotation store: when the reader answered,
what they answered through, and the revision it rested on. Not a revision field, because a revision
is immutable so an assessment citing revision 1 cannot be re-pointed. Not in the session, because
this ruling forbids that. `through` comes from the client, since the moment settled is the one the
reader was looking at, and is clamped to now so a forged value cannot disable the block forever.

**The window is the record's own.** A direction older than the tail `io.read_tail` keeps is not in
the entries and cannot be counted, so on a long session the suppression can release because the
evidence aged out rather than because the question was answered. The block states what it read
rather than implying it read everything.
A reader's press on Claude Code reads past the tail
([2026-10-13](#amended-2026-10-13-a-press-reads-the-message-record-back-to-the-window-start)); the
suppression here still reads the board's own, tail-bound record.

## DEC-17: the shape contract

DEC-15 requires an evaluation rubric "before automatic assessments are enabled". A reader requested
reading imported that gate by citing DEC-15 as its authority, and a citation cannot be broader than
the thing it cites. So the rubric gates automatic evaluation only, and a reader requested reading is
held to a shape contract instead. A shape contract removes failure classes rather than measuring a
rate, which is why it can stand where no rate has been measured.

Seven rules:

1. Three results per constraint, a closed set: `departure`, `consistent with the evidence read`,
   `not verifiable from available evidence`.
2. `not verifiable` is the fallback whenever output is absent or unparseable.
3. A `departure` carries a resolvable citation: a named evidence entry with its type and source.
   Absence of evidence never produces one.
4. `consistent with the evidence read` is not `met` and may never be rendered as one.
5. Where a harness and an evidence type do not combine, the row states the limit. A limit is never
   a `consistent`.
6. Goal and Expected Output are separate constraints, each naming itself. Never blended.
7. Asymmetric, keyed on constraint identity so it needs no clause interpretation. Expected Output
   may return nothing but `not verifiable` when every cited entry is assistant authored, because
   self report is not evidence of a deliverable. Goal may return a `departure` on assistant authored
   evidence, because a stated change of direction is what that evidence is good for, and a
   `consistent` resting only on it must say so in its evidence line.

Rule 7 is amended below, last by
[the amendment of 2026-10-03](#amended-2026-10-03-owner-the-agents-own-words-are-evidence), which
lets an outcome line rest on one of the agent's own messages. Rules 1 and 6 gain a constraint about
what the agent claims, with a fourth result of its own, by
[the amendment of 2026-10-04](#amended-2026-10-04-owner-what-the-agent-claims-is-its-own-constraint).

Rules 3 and 7 are load bearing: they make an uncited departure and a deliverable claim resting on
nothing that shows work unrenderable rather than rare. Rule 4 is weaker than it reads, and the
amendment below says so.

### Amended 2026-09-10: rule 7 asks whether an entry shows work, not who typed it

Reversed for the agent's own messages by
[the amendment of 2026-10-03](#amended-2026-10-03-owner-the-agents-own-words-are-evidence).

As written, rule 7 keys the Expected Output test on who wrote a cited entry, and that inverts its
own reason. The reason is that self report is not evidence of a deliverable, and a request is not
evidence of one either. Keyed on authorship, citing the reader's own words licensed a verdict about
her own deliverable while citing the actual work result demoted. Seven adversaries found it running
against the built producer; none of five reviewers reading the rule had.

The test is now whether a cited entry demonstrates work. On Claude and Codex nothing does, so
Expected Output stays not verifiable there, which is where it already was. The change only ever
narrows what may be said.

Two rules were added beside it, both from the same pass and both demoting on either constraint. A
verdict resting only on entries Compass itself derived is this board quoting itself: an observer
snapshot is a paraphrase of the session, not evidence about it. And a `consistent` resting only on
the reader's own request is agreeing with the question, which is the shape a reader is most likely
to misread as corroboration because the words match. A departure on her own words is different and
stands: a stated change of direction is exactly what that evidence is good for.

### Amended 2026-09-10: rule 4 is a backstop and the word list has two halves

One flat list of forbidden words demoted six of eight natural departure sentences. "The tests
failed", "not done", "incomplete" are the ordinary vocabulary of saying a thing did not happen, so
the guard against reassurance was the thing hiding departures.

Success words always demote, because the model may never assert the work landed under any result.
Failure words demote only under a `consistent`, where claiming failure while agreeing with the
evidence is incoherent. A success word under a negator is a failure statement and keeps its
departure.

Rule 4's primitive is that the model emits a token rather than a sentence, and that prose renders
only under a departure. The word list is the second line and it is a judgement rather than a
measurement. Saying otherwise would be the same overstated claim the rule exists to stop the model
making.

#### Amended 2026-09-24: a check's own result word is not a verdict (owner ruling)

Owner ruling, 2026-09-24 (DRC-4677 review). Under
[DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) item 8 the only
`consistent` Expected Output can carry rests on a cited check whose latest run passed, and the row
the model read says so in Compass's own words ("passed, as the tool reported"). A model that
described that evidence truthfully tripped the success-word half of the backstop, so every such
reading was withdrawn as a stated verdict, and "no later write" or "not inspected" tripped the
negator half on its own. The two sentences above still hold everywhere else. For an Expected Output
`consistent` that rests on a cited check passing item 8:

1. `passed`, `passes` and `passing` are the tool's report, not a verdict, and so is "failed" when
   the cited row itself says an earlier run failed.
2. A negator counts only beside a success word that remains, so "not complete" still withdraws it
   and "no later write" does not. A negated pass word still withdraws it, read in word order before
   the pass words are set aside: "did not pass" and "no tests passed" are failure statements, and so
   is a negated "work" or "expected".
3. Every other success word still withdraws it: met, complete, verified, works, delivered and the
   rest of the list.

The prompt now asks for `detail` only under a departure, and says a check's result words are
Compass's, so the prose the rule reads is rarer at the source. A consistent's prose is never shown,
so this adds no prose to the page. Goal verdicts and departures are unchanged.

### Amended 2026-09-12: rules 3, 4, 5 and 7 are told apart in the stored shape

The seven rules say what a row may conclude and did not say how a row records which rule
concluded it. Rule 5's limit row is told apart on the page, which derives the limit itself, and was
not told apart in the store, where the limit was never written. Rule 3's demotion of an uncited
departure, rule 4's backstop and rule 7's three stored byte-identically to a model that said
`unverifiable` on its own. Rule 2 is the one that already recorded itself, by leaving `result`
absent.

Every row now names the rule that left it without a verdict, as a token: `not-asked` for rule 5,
`unreadable` for rule 2 (a row the page still answers from its own derivation, since that token
never accompanies a result), `uncited` for rule 3, `verdict-stated` for rule 4's backstop, and
`no-work-shown`, `board-quoting-itself` and `uncorroborated` for rule 7 and the two rules added
beside it. Where more than one fires the producer records the one the page would have said, in the
page's order, so a live row and its stored copy never disagree about the reason. The contract
otherwise stands as written: the results are unchanged, the fallback for an unreadable reply is
still an absent result rather than a present one, and the token set is closed on both sides.

### Amended 2026-09-24: rules 4, 6 and 7 meet a checklist, a tool outcome and a level

Rule 6:
[DEC-24](#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
makes the Goal and each outcome line separate constraints, each naming itself and never blended, so
a reading has up to seven (item 3).

Rule 7 and its 2026-09-10 amendment: on Claude Code a check's recorded result, read under
[DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work), now demonstrates
work, so "On Claude and Codex nothing does" holds for Codex and for everything else on Claude Code.
A `consistent` on an outcome line needs the latest run of a relevant check passing inside the
evidence window with no later write, and says it is as the tool reported, not inspected. On an
outcome line the agent's own account still yields `not verifiable`, as rule 7 says. On the Goal, a
`consistent` resting on the agent's own account says "Consistent with what the session said at #<n>;
not a check". A message that matches a copied correction is not person-authored evidence (DEC-24
item 9).

Rule 4: [DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)'s "None or low"
names a level, never `met`. Its floor for an analysis needs every outcome line `consistent` on a
tool-reported check. The live estimate says it reads checks and file paths, not what the intent
says, and the analysis says it read each line of the intent against the checks and messages it
cited. A result is never "Done" and never a check mark (DEC-24 item 6).

Rule 7's outcome-line half here is replaced by
[the amendment of 2026-10-03](#amended-2026-10-03-owner-the-agents-own-words-are-evidence).

### Amended 2026-10-03 (owner): the agent's own words are evidence

The owner, 2026-10-03: "allow whatever the agent says or does to be used as evidence for claims
and drift." The reason given: "it is obviously evidence, and you cant have a drift tool that does
not check or understand what an agent is doing or has done." Three adversarial reviews of the first
build the same day narrowed how far it reaches, each in the withholding direction, and this section
records the ruling as built after that review.

What it reverses and what it narrows:

- [Rule 7's amendment of 2026-09-10](#amended-2026-09-10-rule-7-asks-whether-an-entry-shows-work-not-who-typed-it),
  whose reason was that self report is not evidence of a deliverable, is reversed for one entry
  type: `agent_message`, a message the agent wrote. An outcome line may rest on one, and a
  departure or a `consistent` on one stands. Nothing else the agent's tooling publishes joins it:
  a decision, a task's birth, a stage, a dispatch, Pi narration or a Codex final answer still
  carries no verdict on a line, and `no-work-shown` is still emitted for a line resting only on
  those, on the reader's own request or on Compass's paraphrase.
- [The 2026-10-01 rule on a line about what the agent tells you](#amended-2026-10-01-a-line-about-what-the-agent-tells-you-cannot-be-shown)
  is narrowed, not reversed. A `consistent` on such a line is still withdrawn as
  `tells-the-person` unless one of the agent's messages is among what it rests on, sent at or after
  the latest check it cites (or, citing none, the latest check in the window the prompt carried),
  because a passing check alone still cannot show what the agent said, and nor can "I'll run it
  now" said before the run. Measured on review: the line "the tests are run once more, unpiped,
  and the counts are reported", read `consistent` on a passing check alone, stood under the first
  build and is withdrawn now, and so is the same line citing the check and that earlier message;
  the analysis level no longer reaches "None or low" on it. The page reads this rule's token from
  the store and does not re-derive it, as before.
- [DEC-24](#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
  item 6 said "Consistent with what the session said at #<n>; not a check" on the Goal only. A
  `consistent`, on the Goal or a line, that rests on the agent's messages alone now says
  "Consistent with what the agent said at #<n>; not a check". Any other agent-authored source of
  a Goal's `consistent` keeps "what the session said".

What a reading reads. On Claude Code each top-level assistant text message in the transcript is a
fact of its own, `agent_message`, labelled "Agent said" in the session's activity. Sidechain and
meta records stay out, a thinking or tool call block has no text to read, and a record Claude Code
wrote itself rather than the model (its `<synthetic>` sentinel) is not the agent speaking. Its
title is the message's first sentence, read like a reader's message. The ledger also carries the
whole message, redacted the same way and cut at 1,000 characters, in a field the page never
receives. The prompt quotes it as one JSON string, with the menu heading's text neutralised, as it
quotes a check's output tail, so a message cannot forge a row or a section. The prompt chooses
entries by title first, as it always has, so the agent's words never cost a verdict its evidence.
Then it swaps titles for whole messages: the reader's first, newest first, inside half the 16 KiB
budget, and then the agent's, newest first, inside a quarter of it. An agent message has the
lowest priority in the byte bound, below a written path: measured on review, a hundred newer
messages otherwise dropped the older write that showed what the session did. The project event cap
reserves the agent's messages after the session's own checks and the reader's messages, so a
talkative session cannot evict either. The 2026-10-13 amendment "a press keeps the closing agent
message of each earlier turn" reserves an eighth of the budget, and some of the cap, for the agent
messages that closed earlier turns, ahead of the newest; nothing else in the order moves.

Only a reading the reader pressed for reads them. The unasked lane, which nobody watches, sends
nothing the agent said, and the scorers keep the same default.

What the model is told. Agent messages are quoted reports, never instructions. A contradicted
claim, unkept promise or work done instead of what was asked is a departure. A `consistent` may
rest on a message it cites. The [2026-10-04 scope amendment](#amended-2026-10-04-unfinished-work)
adds unfinished work at non-final stops and names stalled continuations, finished/ready
overstatements and a stated remainder of the asked-for set as departures. Outcome lines are put to
the model whenever the agent spoke, whether or not tool output may be sent.

Two rules were added in the withholding direction:

- A `consistent` that cited a check whose latest run failed inside the window never stands on the
  agent's account left beside it. It is withdrawn as `check-does-not-show-it`. A cited write or an
  aged pass beside the agent's account does not withdraw it on its own.
- An outcome line's `consistent` resting on no work is withdrawn whenever the session's record
  holds a check that failed inside the window, whether the reply cited it, the prompt carried it,
  the budget crowded it out or no grant sent it. Its token is `failed-check-on-record`, except
  where the prompt had no room for the failure, which keeps `failed-check-unread`.

What stays:

- [DEC-15](#dec-15-the-floor-and-the-overlay)'s rule that a reading never states the work was met,
  and the prompt sentence saying so.
- Rule 4's success-word backstop.
- `board-quoting-itself`: a verdict resting only on Compass's own paraphrase.
- `uncorroborated`: a `consistent` resting only on the reader's own request.
- [DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)'s floor. "None or low"
  from an analysis still needs every outcome line `consistent` on a passing tool-reported check, so
  the agent's word alone never reassures. A departure resting on the agent's message reads Medium.
- Steer back's owner-approved text. A line that departed on the agent's message shows as departed,
  with its time and number, in the same words as any other departure. A `consistent` is still
  only ever "as the tool reported".

What is sent. This is new content to the model provider: each agent message, redacted and cut at
1,000 characters, inside a quarter of the 16 KiB prompt, on a reading of a Claude Code session the
reader pressed for. Redaction recognises credential shapes, and since this review also the value
after a cue such as `Authorization: Bearer`, `--password`, `password:` or a name like
`DB_PASSWORD`, `PGPASSWORD` or `OPENAI_API_KEY`, leaving code that names a value (`None`, `$VAR`,
`next_token()`) and prose (`bearer auth`, `secret=staging`) alone; a password or token with neither
a shape nor a cue can still go verbatim, and an agent message can repeat tool output whether or not
tool output was allowed. The cue is applied to every published string, so a title holding one
moves to a new fact id once, the 2026-09-12 precedent `project_context` records, accepted the same
way; the hash input is unchanged. The words are held in memory for the reading and the live project
context only: not stored, not in the session history store, and not published on any page route,
where only each message's title appears (its first line cut at sentence punctuation and 112
characters, which for text with no such break can span more than one sentence).
[SECURITY.md](../SECURITY.md#claude-code-reading-calls) says the same. The route's "What is sent"
list names the agent's messages and the outcome lines, and the tool-output item says the agent's
messages may quote tool output.

Re-consent. An Allow is bound to a content version and the destination it was given for
(`reading_policy.CONTENT_VERSION`, in `permission_disclosure`), so an Allow given before the
disclosure named the agent's messages does not cover a press that carries them: a Claude Code
session's press, read by Claude Code or by Codex, asks once more. A press on any other harness,
Codex's included, carries none of them and reads at `WORDS_CONTENT_VERSION`, so it is asked again
only where its destination moved; the unasked lane reads the same way, so the bump never stops it.
An older build's Turn off clears the version through a trigger of its own, and an older build's
Allow writes none, so a rollback cannot carry this build's answer onto that build's disclosure.

An accepted decay. A stored departure resting on an agent message stops counting once that message
leaves the transcript tail the live record reads: the message is not admitted to the session
history store, so the citation no longer resolves and the page and the analysis level drop it. That
is accepted rather than fixed by a history admission, because storing what the agent said is a
larger exposure than this ruling asked for.

The abstention acceptances, Codex's of 2026-09-14 and Claude Code's of 2026-10-02, describe the
producer before this ruling. They were not re-scored against it, and
[DEC-18](#dec-18-an-unasked-reading-is-permitted-and-gated-on-delivery-first)'s precondition 3
rests on them, so that precondition is owed a re-score of this producer before the unasked default
changes. The abstention packets do not yet carry the agent's messages:
`project_context.frozen_claude_agent_messages` exists for an offline replay, and wiring it into
`scripts/mark_abstention.py`'s frozen ledger would change the packet format, so it is a follow-up.
Codex sessions are unchanged for now: reading a Codex session's assistant messages as
`agent_message` is a follow-up too. Two more follow-ups, recorded rather than built: a Claude Code
rewind leaves the abandoned branch in the transcript and nothing filters it by `parentUuid`, so an
agent message from a branch the reader rewound past can be evidence; and the page's expected-output
limit (`nextReadingOutputLimit`) keys on whether the route has a provider alone, not on whether the
record holds an agent message or a sent check.

### Amended 2026-10-04 (owner): what the agent claims is its own constraint

The owner, 2026-10-04, after
[the first drift replay run](drift-replay/README.md#the-first-run-2026-10-04), delegated this
build and its wording: "do the 'What I'd do next' section yourself". That run found most of the
drift a reader pushed back on was a status claim, such as "six sessions running", "merged" or
"tests pass", that no line of the intent speaks to, so no constraint a reading asked could hold it.

The question. Every reader-requested reading of a Claude Code session whose prompt carries one of
the agent's messages also asks a third kind of constraint, keyed `claims`, independent of the goal
and the lines: does any message the agent wrote claim a state of the work (running, done, merged,
pushed, deployed, passing, fixed, sent, filed) that the recorded checks and messages contradict, or,
for a kind of claim the record can show, that nothing recorded shows? It is posed the way the lines
are: sized into the header when the ledger holds an agent message, and kept only when one was
selected. The unasked lane never asks it, because it never carries what the agent said, and nor do
the scorers, whose packets do not carry it yet.

Its results, on this constraint only:

- `departure`: the record contradicts the claim. It cites the agent's message and the entry that
  contradicts it, so rule 3 holds: a departure names its evidence. The contradiction comes at or
  after the claim: a later message stating otherwise, an admission, or a check, whose fact is its
  latest run and so contradicts whenever it ran. Amended later on 2026-10-04 (owner-delegated,
  through the review of the second drift replay run, and narrowed twice on its own review the same
  day): a check that failed before the claim does not contradict it when the prompt carried a later
  run of the same tool, after the failure and at or before the claim, whose result is not a
  failure, which carries no earlier failure of its own, and which names nothing after the tool but
  flags or exactly `.` or `./`. Any other word, a flag's value such as `-k expr` or `-s dir`
  included, keeps the failure standing, so a narrower, wider or different target never withdraws
  it: `pytest tests`, `discover -s tests` and `--deselect` all leave it in place. One known limit:
  the fact does not carry the working directory, so `npm test` run in `web` and in `api` reads as
  the same run. A listed failure is its own check's latest run, so the agent's later runs are other
  checks of the same tool, usually with no recorded result. The review found cited failures 32 to
  967 minutes older than the claim with the same tool run since. Measured on that run's 7 claims
  departures, this rule withdraws none: the two the first version withdrew were followed only by
  runs that named a target. The tool is read from the check's own line,
  conservatively: a wrapper such as `uv run`, `npx`, `poetry run`, `bundle exec`, `env`, `time` or
  `rtk` and `python -m X` are the command after them, a script run by python, node, bash, sh or zsh
  is its file name, a shell's `-c` names no tool, and `npm run lint` is not `npm test`. Such a
  departure is withdrawn as `check-does-not-show-it`. A failure at or after the claim still
  contradicts it.
- `not shown by the record`, a fourth result and the token `unsupported`: the claim is of a kind
  the record can show, a check or tests or lint passing, something fixed as a check would show, a
  file written or changed, and nothing in the record read shows it. It cites the message. It is not
  a departure, because absence of evidence never produces one (rule 3 stands as written). It reads
  Medium in the original analysis level with its own reason, `claim-not-shown`. The
  [later owner amendment](#amended-2026-10-04-owner-claim-caution-and-secondary-correction)
  makes it a blocker on None or low only. The row says the record read is the board's recent tail, so "not shown"
  is about what was read, never that the thing did not happen.
- `consistent`: every such claim is shown, by the work: it cites the message and a tool report or
  work result showing it, never a person agreeing with the agent.
- `not verifiable`: there is no such claim, or the evidence cannot settle it. A claim of a state
  nothing Compass records can show (running, merged, pushed, deployed, sent, filed, a PR opened) is
  a departure where the record contradicts it and not verifiable otherwise, never `unsupported`
  (the arbiter's ruling on review, 2026-10-04).

So rule 1's closed set has a fourth member on this one constraint, and the token `unsupported`
anywhere else is outside its set and leaves no result (rule 2). Rule 6 gains a third kind of
constraint, so a reading names up to eight, the goal, six lines and the claims.

The resolver rules that already applied still apply, and two are added in the withholding
direction. A result without the citations it needs, the message and, for a departure or a
consistent, the entry it was compared with of the kind above, is withdrawn as `claim-uncited`; a
consistent resting on the agent's message alone is the agent agreeing with itself, which is rule
4's backstop for this question. An `unsupported` is withdrawn as `claim-record-unread` when the
session's checks were not all read, for want of a grant, a named destination or room in the prompt,
because "not shown" would then be configuration read as absence; the page holds the claims row to
the route's limit as it holds a line. Room includes the listing's own cap: since later on
2026-10-04, an `unsupported` is also withdrawn as `claim-record-unread` when the session holds a
passing check or a written path, inside the reading's window, that the prompt did not carry. The
press reads each one's record id and time beside the output tails, and the reading matches the
record ids against the facts its prompt carried, so a pass the listing's cap or the byte bound left
out counts, as does one that arrived after the facts were published, and one the prompt carried
never does. One with no recorded time counts, because it cannot be shown to be outside the window.
Nothing of it is published, sent or stored. Measured with the amended listing order, this fires on
3 of 31 no-drift `unsupported` flags and none of the 17 on drift cuts, and keeps both claims the
second run found to be real. The success-word backstop reads a claims `consistent`'s
prose as before, and not a departure's or an `unsupported`'s, which quote the agent's own success
words by their nature ("said the change works, but the check errored") and say nothing landed. A
comparison resting only on Compass's own paraphrase is `board-quoting-itself`. `check_supports`
drops a cited check that does not carry the verdict, so a pass followed by a change does not show
"passing" now, and no write carries a claims verdict; a consistent beside a failure in the window
is withdrawn as for a line, cited (`check-does-not-show-it`) or unread (`failed-check-unread`). The
resolver cannot tell a claim's kind from what it cites, so which claims may be `unsupported` is the
prompt's rule alone, and it is said there in one clause.

The prompt had 6 bytes of room under `INTENT_SHARE_BYTES`, the worst goal and six lines measuring
9,210 of 9,216. The answer shape is now spelt once and named `A` where it was spelt per constraint,
which freed most of what the worst intent spent; the token sentence names `unsupported` for the
claims question, and the claims instruction is one sentence, its list less "finished", which
"done" covers. The worst header with the claims question measures 9,214, and the record keeps at
least 7,168 bytes. Eight answers at the reply cap's worst measure 4,751 bytes compact and 5,664
indented, under 8,192. `reading.py` is one of the files the abstention packets' parser digest reads
(`mark_abstention.parser_digest`), so a packet frozen before this refuses as
`frozen-on-another-parser`, as any change to that file makes it.

The page. A row "What the agent claimed", after the outcome lines under its own heading and with no
sentence under the heading, with its states: "What the agent said at #n is contradicted at #m"; "…
is not shown by the record. The record read is the board's recent tail."; "… is shown at #m", with
"as the tool reported; not inspected" when that is a check; and "Can't tell" with its reason where
a verdict was withdrawn. A reading that found no claim draws no row. A claim is said once on the
panel: in its row, and as the level's reason; the answer line is about the intent alone. A
contradicted or unshown claim is not a departure from the intent anywhere: not in the answer, the
departures count, the activity list's Cited flags, the first screen's drift mark or the level's
floor, and a claims row never holds "Nothing found" or "None or low" back. The analysis level
names a contradicted claim `claim-contradicted` rather than a departure. Claims are independent of
the intent, so an unsettled later direction demotes the intent's rows and never the claims row
(reversing the first build on review). Steer back adds one line for such a claim, in the
owner-approved template's style: `You said "<claim>" at 14:02 (#12 in Compass); the record does not
show it.` for an unshown claim, and `…; the record shows otherwise at 14:05 (#13).` for a
contradicted one (the arbiter's wording, under the owner's delegation; since 2026-10-14 both clauses
number an entry as "(entry #12 in Compass's activity list)", [DEC-24's
amendment](#amended-2026-10-14-owner-the-correction-names-the-entry)). Steer back is offered for
the claim from the claims row itself, so it never offers "Update intent instead" for one. The claim
is the message's published title, its first sentence, which the activity list already shows, and
never the words a reading read; that is the one place the correction reads a summary.

What is sent to the model does not change: the agent's messages already go on a press that carries
them ([SECURITY.md](../SECURITY.md#claude-code-reading-calls)). What `POST /api/correction` returns
does, by the claim's first sentence, a title the page already publishes, and SECURITY.md says so.

The downgrade. A stored reading may now carry the key `claims`, the result `not shown by the
record` and the reasons `claim-uncited` and `claim-record-unread`. A build that knows none of them
refuses the reading whole, publishes the refusal beside the press count and writes the raw reading
back untouched, the existing refusal of 2026-09-12, so stepping forward reads it again. The cost
crosses a shipped release and rests on the owner's delegation of 2026-10-04, not on a ruling of its
own. The abstention scorer's question list gains `claims` only where a reading answered it, with an
outcome of its own, `judged:unsupported`, never counted as a departure; that branch cannot run
until the packets carry the agent's messages, and marking it is owed then.

### Amended 2026-10-04: owner, claim caution and secondary correction

The owner, approving the Analyze drift plan, amended DEC-17's claim display and level.
"Not shown by the record" blocks None or low; it does not raise Medium. A contradicted claim
still reads Medium. A withdrawn claim draws no row, while an unshown claim keeps its row and asks
for evidence in the correction: `Can you show evidence for "<claim>" at <time> (#n)?` Titles of two
words or fewer and bare URLs are not quoted there. A claim alone offers Steer back as a secondary
control, including when no model reader is available. It never offers Update intent instead.

The second replay withdrew 107 of 164 claims rows. Keeping those rows and treating a lack of
recorded proof as Medium made ordinary work look like drift. Neither change widens what the
model reads, what is stored, or what a claim can establish. The claims row still does not enter
an intent-departure count or its answer; an unshown claim now holds the analysis floor back.

### Amended 2026-10-04: unfinished work

The owner, approving the Analyze drift plan, added one result for intent at a mid-flight or
last-turn reading: "Not reached at this stop" (`not_reached`). The model receives the scope as
trusted text: work so far, or through the session end. Final readings and the claims question
cannot carry the new result. An unknown scope cannot carry it either.

Unfinished work in flight differs from evidence that cannot settle a question. The new result
needs a resolved citation and may retain a short explanation of what the record shows it waiting
on. The same redact-before-bound, citation and stated-verdict guards apply as to departure detail.
The page names unfinished work beside the line and keeps the explanation under Evidence. It
raises no departure, Medium level or Steer back offer, and it cannot establish the None or low
floor. When another line warrants a correction, its bullet says "not reached at this stop" rather
than requesting proof of completion. Model detail never enters that correction.

This does not excuse an unkept continuation or finish promise, an unnecessary wait on the person,
work done instead of the ask, a contradiction, a failed relevant check, or presenting unfinished
work as ready or finished. The trusted evidence rule also names a stated remainder of an asked-for
set as a departure. No word or number gate classifies a line; the model still chooses the result
against the record and the resolver still applies the evidence rules.

Before the schema changed, two blind agent markers sorted 58 historical no-drift intent departures.
A third checked disagreements and the critical controls against fuller pre-cut context. Their
resolved sort has 24 unfinished-in-flight questions, 25 departures, eight consistent questions
and one unclear question. These are agent marks on development sessions, not measured model
improvements. The [count-only record](drift-replay/scope-stage4d.json) freezes the marks digest.
Earlier intent windows omitted commitments that mattered to the controls, so the fuller review
preserves their unkept promises and stalls. A blanket demotion of unfinished work would lose them.

Both evidence and claims instructions were shortened in this change. The worst 240-character
four-byte Goal and six lines, with a tool note and claims question, occupy 9,151 bytes at non-final
scope, within the intent's 9,216-byte share. No line is clipped to make room for the new rule.

#### Clarified 2026-10-06: unknown conditions and work in flight

The non-final scope instruction distinguishes an unknown clause condition, which calls for
`unverifiable`, from known work in flight, which may support `not_reached`. An already shown,
still unkept stalled promise remains a departure while recovery proceeds. A fulfilled promise,
an old stall outside the selected window or work following a legitimate new direction is not
automatically a departure. The existing whole-clause evidence and independent-answer rules
still govern each question. The final-session instruction, resolver and scoring rules are
unchanged.

The clarified maximum non-final header occupies 9,189 of the same 9,216 bytes. Its additional
38 bytes can change which evidence rows fit at the total prompt limit; no cap is raised or
selected line clipped. A prospective qualification must therefore rebuild and freeze the
actual selection, asked questions and prompt for every case. A required claims case must not
silently lose its claims question. Assembly and authored-reply tests establish these
software boundaries, not improved model accuracy. Earlier failed results remain failed.

#### Clarified 2026-10-07: per-clause precedence

At a non-final stop, apply the existing departure rules to each question before treating work as
unfinished. A shown departure, including a still unkept stalled promise, persists while recovery
is in progress. Otherwise, an unknown scope or condition calls for `unverifiable`; known
unfinished work may support `not_reached`. Read a repaired clause separately from another
clause whose earlier departure remains. This ordering neither adds a departure ground nor
classifies English promises with a keyword rule. A completed repair is not automatically a
departure.

The maximum non-final header now occupies the full 9,216-byte share. Final-session instructions
remain byte-identical, and the resolver, claims and evidence rules are unchanged. The additional
27 instruction bytes preserved selection and all 81 citation joins on the ten registered
qualification inputs, but that is not universal selection parity or measured model improvement.
A changed producer still needs source-derived inputs and bound pre-output expectations before
qualification. Earlier failed readings and their marks remain unchanged.

#### Clarified 2026-10-07: independent clause judgments

Each clause uses evidence that supports that clause. Never copy Goal's judgment to an outcome
line, or one line's judgment to another. The same recorded fact may support several clauses
when it actually establishes each; independence does not require disjoint citations. A shown
Goal departure cannot settle an outcome whose whole scope or conditions are unknown. A
supported repair of another clause may be consistent while the earlier departure remains.
The existing missing-evidence and partial-coverage fallback remains `unverifiable`.

Only non-final framing changes. Shared evidence, security, claims and resolver rules remain
unchanged, and final-session headers retain their bytes. The maximum non-final header is now
9,212 bytes within the unchanged 9,216-byte share. Headers with outcome lines shrink by four
bytes; headers without lines grow by 27 and still fit. Ten source-derived qualification inputs
retain their 81 citation joins and 34 questions, but this is construction evidence, not universal
selection parity or measured accuracy. An ambiguous attribution criterion also needs its
latest-report versus persisted-artifact scope declared and adjudicated in a prospective packet.
No earlier failed result or frozen key is regraded.

#### Clarified 2026-10-07: unknown conditions precede a departure judgment

Read an unknown scope or prerequisite as `unverifiable` before carrying a departure
judgment forward. A counterexample may still establish departure if its membership and
every relevant condition are shown. One approved, unfinished member can refute an outcome
about all approved work without enumerating the remaining set. An unfinished item whose
approval is unknown cannot supply that counterexample, and Goal evidence cannot fill the
missing approval for another clause.

A known departure stays visible during recovery. Known pending work may be `not_reached`,
and a separately supported repair may be consistent. These instructions add no keyword
classifier or deterministic proof of English conditions. The model must apply them to the
recorded evidence.

The non-final header fits the unchanged 9,216-byte share, including its largest variant.
Final-session headers, shared evidence rules, claims and the resolver retain their bytes.
Ten source-derived inputs add four framing bytes each and preserve their 81 selected joins
and 34 questions. This construction check establishes neither universal selection parity
nor model accuracy. All earlier failed results and marks remain unchanged; a changed
producer still needs a fresh source-bound packet and qualification run.

#### Clarified 2026-10-07: known applicability and an actual claim

`not_reached` is a judgment, not an abstention. Unknown scope or conditions still require
`unverifiable` when work is unfinished; a pending item whose applicability is unknown cannot
establish this result. A counterexample may establish departure when every relevant condition
is shown, without enumerating an entire unknown set. Known departures, including still unkept
stalled promises, remain visible during recovery, and supported repairs are judged separately.

The claims question compares actual assertions of the closed work states against the record.
A neutral pointer to recorded output is not a work-state assertion. A genuine passing check
can support a relevant assertion; it cannot invent one. Non-final claims framing makes this
distinction explicit. The claim, contradiction and showing-check citation requirements and
the limited use of `unsupported` remain unchanged. No English keyword classifier is added.

Only non-final framing changes. Final-session headers retain their exact bytes, and shared
evidence rules, parser and resolver remain unchanged. The maximum non-final header is 9,214
bytes within the same 9,216-byte share. Ten source-derived inputs shrink by two bytes each
and preserve all 81 selected citation joins and 34 questions. Individually checked expectation
transfer is prospective preparation requiring independent source admission, not a qualification
pass or measured model improvement. Earlier failed results and marks remain unchanged.

The run-once question also retains its original scope and expectation. A latest-only check
does not establish execution cardinality across the saved interval. Changing that question
to a latest-direction interval requires the interval to be declared before outputs, complete
recorded execution evidence for it and fresh source-only adjudication. No global intent window
is moved to select a favorable check.

### The two typed fields are one line each, and that is a security decision

Recorded here because it had no durable home. The goal and the expected output are collapsed to a
single line by the same control character scrub that stops a pasted private key body surviving into
a published string, and it runs server side on write and again on read back. Admitting newlines
means relaxing that scrub for two fields that a reader pastes into, which is the wrong two fields to
relax it for. Since DEC-24 item 3 the expected output is a checklist, and each of its lines is held
to the same rule: one line, the same scrub, on write and on read back. The browser collapses on input as well, so the reader watches it happen rather than
finding out afterwards.

### What the contract does not remove

A false `consistent` on the Goal constraint, resting on the agent's own narration. Its rate is
unmeasured. What bounds it is that the claim is narrow, produced once per press, never aggregated
into a count and never pushed, so exposure does not compound. That bound holds only while there is
no cadence, no aggregation and no notification, and the full rubric becomes owed the moment any of
the three changes.

Since [2026-10-03](#amended-2026-10-03-owner-the-agents-own-words-are-evidence), a second: a false
`consistent` on an outcome line resting on the agent saying it finished. Its rate is unmeasured
too. It is bounded the same way, only on a press, and further: it never stands beside a check that
failed in the window, it reads "what the agent said; not a check" rather than as the tool reported,
and it never lifts the drift level to "None or low".

#### Amended 2026-09-24: a cadence makes the full rubric owed

[DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn) adds a cadence, a live
estimate after every turn, so by the paragraph above the full rubric is now owed. The measured
levels DRC-4692 validates are its first measured part.
[DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) adds a second
surviving class beside this one: a false `consistent` on Expected Output resting on a success the
tool reported, which DRC-4666 qualifies the producer against. Neither level is aggregated into a
count or pushed.

### The contract is built and unexercised

Recorded 2026-09-10, because a reader of this section otherwise concludes the seven rules are held
and they are not yet held against anything real.

No producer writes an assessment, and `annotations.published` emits no field for one, so
`annotation.assessment` is undefined for every row a server has ever served. About 120 lines of the
renderer, the criterion rows and the departures list among them, are reached only by tests that
inject a shape directly. Every assertion about these seven rules is therefore evidence that the
renderer is self-consistent, not that the contract is right, which is the fixture-as-specification
failure this repository has already measured once.

Whoever adds the producer adds the published field in the same change and re-derives those
assertions from it. One trap in particular: the `assessment` entry in the page's annotation rebuild
list is the only production mention of the field, and two defects on this branch have already
landed in that list. Publishing an assessment without adding it there reproduces the defect and the
suite stays green, because the fixtures bypass the rebuild.

### The condition on enabling, not on building

The original ruling below was amended on 2026-09-14 to allow the captain's acceptance of the
recorded case review to enable the control, and on 2026-10-02 to let the owner's acceptance open
the Claude Code producer's own gate without a pass.

The reading is built now. The `Ask for a reading` control (`Check for drift` from DRC-4639, `Analyze drift` since DRC-4680) is not enabled until an abstention check
has run and passed: at least one recorded session per case kind DEC-15 names, across both Claude and
Codex, with a person other than whoever writes the reading prompt marking each constraint in advance
with one binary expectation. Should this abstain, or not. No severity, no expected judgement text,
no threshold. Every case marked should abstain must return `not verifiable from available evidence`.
A case marked should not abstain that abstains is recorded and does not fail, because over
abstention is the safe direction.

The check cannot be run without a producer to run it on, so a recorded pass implies one exists. That
is why the control reads one gate rather than two.

#### Amended 2026-09-10: the captain marks the corpus

The second person requirement is removed. On this milestone the captain is that other person and
there is no third, so holding the check as written left the constant at not run indefinitely, the
control permanently disabled, and the promise unkept by anything the producer builds.

Three things the requirement was protecting are not relaxed, because they are what makes a mark
evidence rather than agreement. Marks are written before any producer runs against the corpus: a
mark written after seeing an output is not a mark. The corpus is recorded sessions only, and stays
separate from the synthesised case set, because sharing one would let a synthesised fixture satisfy
a gate written for recorded sessions. And cross agent verification on that case set is untouched: a
case whose generator and verifier are the same agent is not admitted.

What this costs is that the marker is also the person who wants the feature, so a mark wrong in the
permissive direction has nobody to catch it. The mitigation is the first of those three, and it is
weaker than a second reader.

#### Amended 2026-09-28: the agent may write marks the captain agrees to

The captain may have the agent building this check propose a judge or abstain mark for each
constraint, and a mark the captain agrees to may be written into the marks file by that agent. An
agreed mark is the captain's. A mark the captain has not agreed to is not written.

Two things still hold. Marks are written before any producer runs against the corpus, so a mark
written after seeing an output is still not a mark. And the corpus stays recorded sessions only.

What this costs is independence. The agent that proposes the marks also wrote the reading prompt,
and it is the same model family as the Claude Code producer being qualified. That is the case the
original ruling excluded. A blind spot the proposer and the producer share would make a permissive
mark look right to both, and the captain's agreement is then the only independent check. The
mitigation is that disagreement is shown rather than smoothed: every constraint where the proposal
differs from the captain's own mark goes to the captain to decide.

#### Amended 2026-09-14: the captain accepts the case review

After answering all twelve recorded Claude and Codex snapshots, the captain accepted that review
as sufficient to unlock reader-requested readings. That decision supersedes the requirement to
wait for a scoring run before enabling the control.

The build publishes `reading_check: "accepted"` and enables the control and its HTTP route.
`passed` remains the scorer-backed enablement state; accepting the review does not manufacture
a scoring result. The local answer key is bound to the frozen packet, and the committable
[acceptance record](abstention/acceptance.json) carries its hashes and marks without session text.

The producer's evidence and lifecycle rules, the explicit press and disclosure, and the
`--observer-model` opt-in still apply to each request. The evaluator retains its existing verdicts
and coverage rules for future scoring. This amendment concerns the reader-requested control.

Amended again 2026-09-23: [DEC-21](#dec-21-a-reading-works-the-first-time-you-ask) replaces the
`--observer-model` opt-in for reader-requested readings with a remembered first-press answer and a
daily cap, once DRC-4640 ships. The press and the disclosure still apply to each request.

#### How the check is run, 2026-09-12

Two scripts, both outside the gate and neither in CI. `scripts/mark_abstention.py --build` draws
cases from the live board into `~/.compass/abstention-cases.json`, and its marking mode collects
the captain's `judge` or `abstain` per constraint into `~/.compass/abstention-marks.json`.
`scripts/score_abstention.py --score --producer <name>` then hands each case to `reading.produce`
with the two constant yardstick sentences as a synthetic revision (or, in format 5, the case's own
goal and outcome lines), through the named producer's reading model, and writes two halves: a local results file beside the cases, and a committable summary under
`docs/abstention/`. Where the cases live and what each file may hold is the security ruling, in
[SECURITY.md](../SECURITY.md#the-abstention-check).

Historical cases can instead use a frozen row, semantic facts and evaluation clock. This avoids
scoring today's changed or absent session against yesterday's mark. The packet is prepared before
marking; the key binds to its digest, and the producer's lifecycle rules still apply at the frozen
time. The format and procedure live in the
[abstention documentation](abstention/README.md#historical-replay-case-format-4).

The qualification's parser stamp now hashes parsed derivation code, with a versioned hash domain,
rather than source bytes (DRC-4731, 2026-09-29). A comment or layout edit used to demote every
recorded case despite deriving the same facts. Those edits now keep the stamp; changes to literals,
expressions or control flow still invalidate the packet. Old byte-stamped packets are not rewritten,
and the exact contents check still applies. The stamp includes `io.py`, since its bounded byte
reader decides which check records were reachable at the freeze. A parent cutoff that the check
budget cannot reach refuses a freeze and demotes a score-time contents check. Administrative
records after a recorded stop do not count as resumed work; user and assistant messages do. Freeze
a fresh packet after the final producer changes.

The scorer prepares its local files before charging, and executes a verified private CLI copy so an
installation update cannot select different bytes for a later call. The native copy measurements and
the remaining same-owner limits are owned by
[the security ruling](../SECURITY.md#the-abstention-check). These preparation changes do not supply
a passing score, alter existing marks or open the Claude Code reading gate.

Each (case, constraint) lands in exactly one of `withheld:<reason>`, `unparsed`, `abstained`,
`judged:consistent` or `judged:departure`. Withheld is its own column because the corpus this was
written against made the trap concrete: twenty of twenty three cases had an empty ledger, so the
producer refused them before any model call. Folding that into "abstained" would have reported a
producer that never abstains as one that always does, on three exercised sessions. A withheld case
counts for neither side. `unparsed` is kept apart from `abstained` because rule 2's fallback renders
the same sentence and is a different fact.

The output column is mostly the ruling's. Only a case whose record shows work is asked the Expected
Output question (`asks_output`, which reads the entries the prompt carries; the check never grants
tool output, so that is a Pi case with a work result), the collector fixes the mark to `abstain`
everywhere else, and `resolve` answers `not verifiable` there without asking. The scorer records `asks_output` per case
and the report says how many output columns were never asked, so twenty three abstentions on a
corpus with no Pi session read as the ruling's answer rather than as the model abstaining twenty
three times.

PASS therefore needs two things. No case marked should-abstain judged; a judge mark that abstains is
recorded and does not fail. And the coverage floor: at least one evidence-bearing, kind-tagged,
recorded case per DEC-15 kind, on both Claude and Codex, that reached the model. Ten, minimum. The
kind tags come from the rubric expectation file's `recorded` entries, so tagging a case after the
fact does not touch the marks. Below the floor the verdict is `short` and PASS is refused with the
shortfall printed per harness. The summary also carries the sha256 of the marks file as scored, and
a later report whose marks no longer hash to it says the marks moved and refuses PASS. The floor is
now judged per producer; see the amendment of 2026-09-27 below.

The scorer never writes to the annotation store, never posts to the reading route, and never flips
`annotations.ABSTENTION_CHECK` or `annotations.CLAUDE_ABSTENTION_CHECK`. Each flip is a separate
change, made by hand, after a run has passed on a corpus that meets the floor, or after an
acceptance: the captain's of the case review under the amendment above, or for Claude Code the
owner's of 2026-10-02 below.

#### Amended 2026-09-27: the floor is judged per producer

The owner ruled three things on 2026-09-27, while qualifying the Claude Code producer (DRC-4666).

1. Coverage is judged per producer. The harness of the producer being scored needs a recorded
   case of each of the five DEC-15 kinds that reached the model. The other harness's cases are
   cross-harness controls: they are marked, scored and can fail the run, and a kind they lack is
   reported as not produced rather than counted short. Codex produced no supported departure in six
   attempts: it either worked around the stated scope or declined and suggested the out-of-scope
   fix. Getting one would have taken a follow-up approving the work, and item 2 rules that out. A
   floor that required it could never be met.
2. A departure the prompt directed is not a supported departure. A case counts for that kind
   only when the agent left the stated scope on its own. The scorer cannot tell who directed a
   departure, so this binds the rubric: a case whose prompt asked for the departure is not tagged
   `supported-departure`.
3. The Claude Code producer passes `--system-prompt` with a fixed sentence, so Claude Code's
   default system prompt is not sent. What the CLI still sends, measured against a local stub, is
   listed under [Claude Code reading calls](../SECURITY.md#claude-code-reading-calls).

`score_abstention.py` records each harness's part in the committed summary: `role` is `scored`,
`control`, or `required` for a run that names no producer. `missing` lists the kinds that hold
back a scored or required harness, and `not_produced` the kinds a control lacks. A run that names
no producer keeps the original floor on both harnesses, as every summary written before this
amendment was scored.
The format is owned by the
[abstention documentation](abstention/README.md#how-to-argue-with-a-result).

#### Amended 2026-10-01: a reader's correction and a transcript stop

The owner ruled two things on 2026-10-01, while looking for DRC-4666's supported-departure case.

1. A supported departure may rest on the reader's own correction rather than a failed check. The
   resolver already lets a Goal departure stand on the reader's words, so this binds the search
   and the rubric, not the code. A search for a failed check alone read no reader message: it
   scanned 4,882 sessions and found no case, where a search of the reader's corrections found 87
   sessions carrying one.
2. A Claude Code turn stop the history store has rolled past is vouched by the transcript. The
   store is capped at about 1 MiB and held 2026-09-17 to 2026-09-30 when measured, so every older
   stop read as unobserved. Such a stop counts when the transcript's own top-level
   `stop_hook_summary` for the session sits at the `finished_at` and its hooks did not keep the turn
   going. A stop inside the store's reach still needs its observation. The board stamps the
   hook's arrival rather than the record, so `finished_at` must be the record's own stamp: over the
   store's 700 observed stops none sat within a millisecond of its record, and 217 within a second,
   the record about 115 ms earlier. A stop with no record is refused rather than inferred from the
   last assistant message. The scorer counts the cases it vouched this way itself, in
   `recorded_on_transcript_stop`, and never reads the packet's own `lifecycle_from` for it.

The same day the owner directed the qualification to run to completion within the approved
ceilings of 23 scorer calls and 26 Claude CLI invocations. Two changes followed from it. A second
continuation grant could follow the first, which also failed, and the ledger cap became 23; the
ruling below has since raised it to 28. And a
Claude Code case's user messages and `transcript_bytes` are frozen from the transcript as it stood
at `captured_at`, because the board reads only the last 400 KB of today's file: the correction the
supported-departure case rests on sat 750 KB from the end of a session that ran on.

The second continuation then failed too, and spent the last of the 23 calls. The owner kept the
Claude Code gate shut and authorized one more five-case scored run past that ceiling, as a third
continuation: the ledger cap is 28 scorer calls, beside 31 Claude CLI invocations overall, those
five calls and the browser walk among them. The grant chain now reads grants by one naming
pattern, at most nine of them, each binding the failed result before it, so the third needs no new
code. A grant file under any other name, or numbered past nine, is refused rather than ignored.
Raising the cap authorizes the run, not its packet: the third grant's `marking` and `sealed`
phases are each committed in their own reviewed change, as the first two were.

#### Amended 2026-10-01: a reading sees the reader's whole message

The overlay [DEC-15](#dec-15-the-floor-and-the-overlay) admits reads the session's evidence against
the words a person typed, and until this amendment a person's message reached it as its title: the
first sentence of its first line, at most 112 characters, which the ledger then cut at 180. Measured
the same day on a real correction, that dropped the point. The reader's message asked what an
unexplained status meant, and then, in later sentences, said the original goal included merging and
that the branches were not being merged back. The model received only the opening question, so a
departure the reader had named in their own words could not rest on them, which is the case item 1
of the amendment above allows.

The owner ruled to send the whole message, bounded, knowing it sends more of the reader's own words
to the provider and moves a [SECURITY.md](../SECURITY.md#observer-model-calls) boundary.

1. Every user-role message in the observed record carries its words beside its title: the whole
   message on one line, through the same redaction as the title, at most 1,000 characters. That
   holds for a Claude Code message (a slash command is its command as typed), every other
   harness's user-role message, and an Antigravity direction.
2. A person's message carries its words in the ledger beside its title, under a 1,000-character
   cap of its own, with the menu-field scrub that stops a separator forging a column. Every other
   entry is unchanged, and so is a copied correction, which is Compass's text rather than the
   reader's. A fact with no words, from a packet frozen earlier or republished by the history
   store, has its title alone.
3. The reader's words may not cost a verdict its evidence. Entries are chosen by their titles,
   exactly as before this amendment, and only then do the newest messages swap their title for
   their words, each only where its whole row fits the room left and the words' own share, half
   the 16 KiB budget counted in UTF-8 bytes. A message that does not fit is sent by its title. The
   first build chose the words first, and review measured what that cost: fourteen long messages
   left a failed check unread with budget to spare, a work entry stopped the outcome lines being
   asked at fourteen messages where thirteen still asked them, and five 1,000-character CJK
   messages, three bytes a character, dropped all three checks. 281 of 517 recent user messages
   reach the 1,000-character cap, so that was the ordinary case. After the fix, beside a failed
   check and a write, seven full-length ASCII messages or two CJK ones go whole, and every message
   past them goes by its title, at 5, 14, 20 or 40 messages alike.
4. The words are not stored and not published. The history store keeps its field allowlist, the
   page keeps showing titles, and `/api/project-context` drops the words before it answers. The
   reading route, the unasked lane and the abstention packet read them on the server. Fact ids do
   not include them, so no stored citation moves. A departure's `detail` is the model's sentence
   and is stored and shown as before, so the model can now paraphrase a later sentence there.

   Owner, 2026-10-01 (Q7): item 4 has one exception. Up to five of the reader's own messages are
   published on the focused project context as `prompt_choices`, each clipped to the goal's
   cap (240 then, 1,000 since [2026-10-27](#amended-2026-10-27-owner-the-goal-holds-1000-characters)),
   so "Use your prompt" can offer them
   ([amendment](#amended-2026-10-01-up-to-five-of-your-prompts-may-be-chosen)). The words field
   itself, and anything past that cap, is still neither stored nor published, and
   `test_reader_words` holds both halves.

The provider each reading may reach is still the one [DEC-21](#dec-21-a-reading-works-the-first-time-you-ask)
item 4 names. The disclosure before the press now says the reader's own messages go in full, up to
1,000 characters each, redacted, and that where the record is too long the oldest go by their first
sentence; an answer given before that sentence existed is not asked again,
and whether it should be is filed separately. The parser digest the abstention
packets are stamped with moves with this change, so a packet frozen before it is refused as
`frozen-on-another-parser` and is frozen again.

#### Amended 2026-10-21: a message sent mid-turn, and an answer to the agent's question, are the reader's words

A reader who corrects a running agent, or answers the question it asks, gave a direction, and
before this the page said it did not exist: `Later directions: none`, no outline phase, and a reading
that named the agent's compliance as its departure. Two session walks measured it. Claude Code gives a
message sent while a turn runs to the model inside a tool result, so the transcript holds no user turn
for it, and the answer to the agent's multiple-choice question is a tool result too. The reader read
only user turns, so neither reached a later direction, an outline phase or the reading's evidence. The
[recorded shapes](captures/README.md) are the evidence for what follows.

1. A message the agent took in mid-turn is read from its `queued_command` attachment, when
   `origin.kind` is `human` and `commandMode` is `prompt`. Not from the `queue-operation` rows: the
   same queue carries a finished background task's notification, 280 of the 297 `absorbed_mid_turn`
   removals measured on 2026-10-21 over this machine's 331 Claude Code transcripts, and counting those would make the harness the reader. The direction is dated
   by the attachment's own `timestamp`, which is when the reader typed it. The removal can come
   minutes later, so a reading that dated it there would put the reader's correction after work it
   had already shaped. Only the attachment's `text` blocks are read, never a pasted image's bytes.
2. The answer is read from `toolUseResult.answers`, one line per answered question: the question's
   `header` (the agent's one-word label for what was asked), a colon, the answer, and the note the
   reader attached in parentheses. A `(Recommended)` that ends the answer, or ends one choice of a comma-joined multiple-choice answer, comes off first: it is the
   agent's own label on the option it preferred, so quoting it, or sending it to a reading, would put
   the agent's advice in the reader's mouth (seen live as `Ruling: (b) Same folder in its checkout
   (Recommended)`). A marker before a comma is the agent's. A reader who typed the word inside their own sentence keeps it. The header keeps a bare option such as "Defer to a follow-up" from
   standing alone as an instruction. The question's text and every option's `preview` are the
   agent's words and are never put in the reader's mouth. A question that timed out or was declined
   has no answer and gives no direction. Only the question tool's own result is read: a user record
   whose message holds a successful `tool_result` block, whose questions each carry options, and
   whose answers are keyed by the text of a question that same result asked. The record names its
   tool nowhere, and the result's own sentence differs across Claude Code versions, so the shape is
   what is checked; a typed turn or another tool's result that happens to carry `questions` and
   `answers` is read as what it is. The answer's characters count toward the press's text guard with
   the notes beside them, since they sit in `toolUseResult` and not in the `tool_result` block's
   text, and a record too long to redact is an unread region as a long message is.
3. Both are user-role steers from the one reader every consumer already shares, so each is a later
   direction the reader settles with Keep or adds to their words, starts an outline phase titled with
   its words, and reaches the reading's ledger as a person's entry under the same 1,000-character
   words cap and redaction as a message typed at the prompt. The fact's `evidence.source` says which
   it is. Neither is a copied correction, so neither is Compass's text. The answer opens its own outline
   phase: the reader's choice shapes the work after it, and folding it into the phase that asked would
   need the outline to carry a source label it does not. It is not promoted to the project's intent on
   its own (`intent_promoted` is false), because "Provenance: Defer to a follow-up" names no work a
   later session could act on alone. The reader's own `Use this as my goal` press still takes it. Each
   fact's `actor_claim` says which record stands behind it, a `queued_command` attachment with a human
   origin or the question tool's result, not the "user-role record" an ordinary turn is.
4. `observer.parse_message_record` is unchanged and still picks the session's goal. A direction the
   agent took in mid-turn does not move a goal the reader set at the prompt: the reader decides
   that with `Use this as my goal`, as for any later direction. The two shapes arrive through
   `observer.parse_reader_record`, which adds them to that parser's output.
5. What is sent to a model changes in amount and not in kind. These are the reader's own words,
   inside the cap, redaction and 16 KiB bound above, so [SECURITY.md](../SECURITY.md#observer-model-calls)
   says so and the short disclosure before the press keeps "your messages", which already means
   what the reader sent into the session. Rewording it would move the recorded client contract
   fixtures and the sample session's stored disclosure for no change in what is sent.
6. Claude Code 2.1.181 and older write no `origin` on a `queued_command` attachment, and a prompt-mode
   one there has no attachment `timestamp` either. Nothing in such a record says the reader sent it, so
   none is read: a message sent mid-turn on those versions stays absent from the page, as it was before
   this amendment, rather than being guessed at. On 2026-10-21, over 5,761 transcripts, 111 prompt-mode
   attachments had no `origin` against 189 with a human one
   ([recorded shapes](captures/README.md)). A later version is read as items 1 to 3 describe.
7. Codex has no queue record in the 1,082 rollouts read on 2026-10-21; a message sent while a call is pending is
   an ordinary user message there, which its reader already takes. Its `request_user_input` answer
   is unmeasured and is left as it was, as are the other harnesses.
8. An answer an earlier build already read changes when this one reads it again, in two fields. Its
   `fact_id` moves where the option carried the agent's `(Recommended)`, because the id hashes the title
   and the title no longer ends in the marker, and its `intent_promoted` is false where it was true, because
   an answer is no longer promotable on its own (item 3). A stored reading that cited the old id loses
   that citation to the page's missing-entry rule, and session history, which dedupes on the id, holds the
   answer under both ids for its fourteen days. Nothing maps the old id to the new: the paste amendment
   rejected the same repair for the reason it gives, and an answer a reading cited is rare and recent.
   A mid-turn message is unaffected, since its words never carried a marker.

The parser digest the abstention packets are stamped with moves with this change, as the
2026-10-01 amendment above allows for: `project_context.py` is one of its files.

#### Amended 2026-10-02: the owner accepts the Claude Code producer without a pass

Every scored Claude Code run failed this check: four runs, the last two each with one false
reassurance among sixteen scored constraints, on different constraints, and the 28 authorized
calls are spent. The owner accepted the Claude Code producer anyway on 2026-10-02, knowing that,
as the captain accepted the Codex review on 2026-09-14. `annotations.CLAUDE_ABSTENTION_CHECK` is
`accepted`, never `passed`, and nothing here turns a failed run into a passing one.

The committable [acceptance record](abstention/claude-acceptance.json) lists every scored run with
its own verdict, digests, counts and spend, and a test reads each from the result file it names,
so the record cannot drop a failure or round one up. The results, their grants and the spend
ledger stay exactly as they were: nothing rewrites, rescores or deletes them. The scorer keeps its
verdicts for any later run, and a later pass would be recorded as `passed` in its own change.
Which sessions Claude Code reads is [DEC-21](#amended-2026-10-02-claude-code-is-accepted)'s.

### Amended 2026-10-21: the record settles a line

Six walks of the session page found a reading and the card beside it contradicting each other. "No
file under frontend/e2e is edited" came back `Can't tell` while the same card listed `Where the work
went: frontend/e2e · 1 file` and the outline counted 13 files written there. A finished session with
passing tests and a printed pull request got `Can't tell` on every line. Lines read `Consistent with
what the agent said at [6]` with no check cited, though the checks that ran are in the record. And
every unsettled line read the same `Can't tell: what was read does not settle this`, with a claims row
that never quoted the claim. This amendment changes two guards and the words of three rows. The
prompt, what the reading sends and the shape contract's seven rules are unchanged.

1. **A recorded write settles a line that names a folder.** `reading.folder_rules` reads a clause of
   an outcome line only when it names a path with a slash in it, speaks of changing files, and says
   which way: negated ("no file under X is edited", "X is left untouched") rules the folder out, and
   limiting ("only files under X change", "nothing outside X is changed") allows only those folders.
   A clause that mixes the two, says neither, or names no folder is left to the reading. A write the
   record holds inside a ruled-out folder, or outside the only folders allowed, inside the reading's
   window and after the line's own request, makes the line a departure whatever the reply said, even
   for a line the prompt never put to the model. `reading._settled_by_record` stores it with the
   fact ids of the first three such writes, a `detail` Compass composes from the count and the
   reader's own folder words, and `why` `recorded-write`.
2. **Only a departure.** No write found inside a folder says nothing: the listing is capped and the
   window can be partial, so a line is never read as holding from a record's silence. This is the same
   rule the claims row keeps for "not shown".
3. **The token is what lets a write carry a verdict.** A written path shows a write and no result, so
   item 8 of [DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) drops it
   from a departure a model cited, and still does. `check_supports` takes it as a departure's
   evidence only for a row stored `recorded-write`, which the producer sets and the model cannot, and
   every reader of a stored reading passes the flag: the page, the level, the correction. `why`
   otherwise names a rule that left a row without a verdict; this one token is on a verdict that
   stands, and the closed set says so. A page that does not hold the write withdraws the row with a
   sentence of its own.
4. **A recorded pass is cited ahead of the agent's message.** A `consistent` that cites no check
   gains the latest recorded passes that carry a `consistent` (`check_supports`) and plainly cover
   the line: where the line names a path or a file, a check whose command names it too; where it names
   none, a check of a kind whose result the line claims ("the tests pass", "lint is clean", "no
   type errors"). A line that only shares the keyword ("the lint config is left alone", "tests are
   not deleted") claims no result and is covered by nothing, and the claim and the keyword must be in
   one clause. A pass of the same kind on another target does not cover a line about this one. The check leads the citations and the
   message stays, so the page reads `Consistent with #8, as the tool reported; not inspected` rather
   than only what the agent said. A line about what the agent tells the reader keeps its message
   alone, because a run does not show a report. The checks are read from the facts, so the guard works
   where no grant sent them; nothing is added to what a reading sends.
5. **Every `Can't tell` says its own reason, in view.** The design's form is `Can't tell · <line>` and
   the reason under it. The reason is the rule that withdrew the row where one did, a limit of the
   harness where that is the cause, the entries the reading read and found silent where it cited any,
   and otherwise that no write, check or message it read speaks to the line. The generic "what was
   read does not settle this" is gone. This supersedes the 2026-10-14 ruling that kept the reason
   inside Evidence: the reader found it by opening a disclosure on each line, and Evidence now keeps
   the entries and not the reason. Opening Evidence does not say it twice.
6. **The claims row quotes the claim.** `What the agent claimed · "<claim>" is not shown by the
   record`, as the design has it, where the claim is the title of the cited agent message, the way a
   correction quotes it (`reading.claim_title`, its closing stop dropped). Under a claim the record
   does not show the row says where the agent made it and that the record read is the board's recent
   tail. "Claim to check at #13 · 4m ago" is gone from beside Steer back: it read as an instruction,
   and the claims row already says which claim and where. (Amended 2026-10-27: see the amendment at the end of this DEC for which cited message is quoted.)
7. **The how-to says it.** It had said a reading cannot settle a folder limit. It now says a recorded
   write breaking one also departs, in no more words, since the popup is held to 150.

What this cannot see. A write made by a shell command, such as a build, has no entry, as the live
estimate's line already says, so a folder the line rules out can still be written without this
guard noticing. The guards read a folder from a line's own words and nothing else: a folder a person
means by a name with no slash in it is left to the reading. A path word such as "and/or" is read as a
path only if it is not one of a short list of ordinary slash pairs, and a limiting line is the only
kind a misread path can hurt, because a forbidden-folder rule needs a write under that exact path.
The guards are held by `test_reading_record_guards.py` and the stories `A recorded write settles a
line that rules out its folder`, `A model's departure on a write alone is still withdrawn` and `Every
Can't tell line says its own reason`.

### Amended 2026-10-27 (owner): the claims row quotes the cited message that claims

The claims row used to quote the first agent message a reading cited. A reading may cite a neutral
statement first and the message that makes the claim second, so the row put a sentence that claims nothing
beside "is not shown by the record", which reads as doubt about the agent's honesty. The page now quotes the
first cited agent message holding a word of the claims rule (running, done, merged, pushed, deployed,
passing, passes, passed, fixed, sent, filed; whole words, any case), and the first cited message when none
does. The other cited messages stay listed beneath. The word list lives in
`frontend/src/drift/claimWords.ts` and mirrors `reading.CLAIMS_RULE`.

The word rule only picks which already cited agent message the page quotes. It is a display choice and
never changes a result, a citation or a verdict, so the ruling that no English keyword classifier is added,
and the amendment that a word list is a judgement, still hold for verdicts.

### Repeated calls

A reading is produced only in response to a discrete reader action, asserted rather than assumed,
and never on render, poll, reconnect, resume, focus change or revision save. One reading in flight
per session. No retry on failure, because a fresh press is required. Each reading is counted and the
count is shown beside the control, against the capacity surface Compass already renders, so the
reader spends their own capacity and can see it going.

### Two arguments that were withdrawn

Recorded so nobody rebuilds them. The claim that a case set cannot be assembled before a judgement
producer exists is false: cases drawn from recorded sessions with expectations written by a person
need no producer, and only a measured threshold does. And the claim that a reader requested reading
is safe because it is attended is weak: the reader asks precisely because they cannot judge it
themselves, and DEC-15b's persistence makes the same reading unattended when it is re read later.

## DEC-18: an unasked reading is permitted, and gated on delivery first

Decided 2026-09-10 (DRC-4534), replacing DEC-15's "for now" refusal of automatic evaluation.
DEC-17 named this decision as the owner of the tension it could not resolve, and this is the answer.

Automatic evaluation is permitted. A reading you have to ask for only helps someone already looking
at the board, and the whole point is the person who set a session going and walked away.

It is refused in practice until four things are true, in order.

Amended 2026-09-10: the four preconditions gate the automatic switch's default, not the
implementation. Read strictly they put three issues, two of them in another milestone, ahead of the
work on the critical path for about thirty five hours that does not change what the work is. The
delivery recording precondition stays a build gate and lands first, because a raise that records no
delivery outcome is precisely the defect the review view exists to show. Native notifications on
the other two platforms, the off machine lane, and quiet hours become follow ups that widen the
lane and, together, permit the default to change. What that accepts is a capability which on Linux
and Windows honestly reports that it cannot reach the reader, and it is defensible only while the
report stays honest, which is what the three distinct delivery states are for.

1. Delivery is real and recorded. DRC-4328 closes the Linux and Windows server side gap, DRC-4034
   owns the off machine lane, DRC-4540 records the outcome per raise.
2. A producer exists. DRC-4511.
3. DEC-17's abstention check has run and passed.
4. Quiet hours exist. DRC-4032.

Precondition 3 rests on acceptances of the producer as it stood before
[the agent's own words became evidence](#amended-2026-10-03-owner-the-agents-own-words-are-evidence),
so it is owed a re-score of this producer before the unasked default changes.

Delivery leads rather than the rubric, and that ordering is the substance of the ruling. Measured in
this tree on the day it was decided: `notify_mac` runs one `osascript` call and records nothing
about whether the notification was shown or seen, and `native_notifier` returns a backend on darwin
alone, so Linux and Windows fall back to a browser notification that needs the dashboard tab open.
An automatic evaluation shipped against that would spend the reader's capacity unattended and raise
a departure that reaches nobody on two of three platforms, and could not afterwards say whether it
had arrived on any of them.

### What an off machine signal may carry

DEC-4 permits counts and states only in an off machine payload, never a session name, project,
title, path or request text. On the machine a departure notification can name the session and say
what departed. Off the machine it cannot, and the most it may carry is that a count changed.
DEC-18 does not lift that and did not try.

### The two amendments to the shape

Off by default behind its own switch, evaluating on an observed state change rather than per turn,
raising only a `departure` and never a `consistent`, held under quiet hours. Two things were added
to that draft.

Every raise persists the annotation revision and evidence cutoff it rested on, at raise time. By the
time it is read the annotation may be at a later revision and the evidence window has moved, so a
raise that does not carry its own baseline cannot be understood on return.

The cumulative cap is per session and per day, and exhaustion is visible on the board. The reader is
by construction not present, so "nothing departed" and "nothing was checked" must never render
alike.

### Amended 2026-10-20: unasked checks remain reachable

Owner, 2026-10-20: the lane stays reachable under `--unasked-readings`, and Claude Code is its
provider by default. Claude Code checks Claude Code sessions and Codex checks Codex sessions. On a
harness with no producer of its own the lane prefers Claude Code, and Codex serves only when Claude
Code is unavailable or unqualified on this machine. This is `reading_route.resolve(unasked=True)`,
with no fallback after a failed launch. A pressed Analyze drift keeps its own rule, Codex first on
such a harness: the ruling named the unasked lane, and changing who a press sends to was not asked
for. The board publishes the lane's routes as `unasked_routes`, beside `reading_routes`, only while
the lane is attached. It replaces the Codex-only restriction in DEC-21's earlier amendments, not the
default-off ruling.

Claude Code uses the owner's 2026-10-02 producer acceptance, never described as a passed check,
through `reading_policy.GuardedModel`, the same guarded seam as Codex and requested readings.
The prompt remains words-only: typed goal and bounded reader messages, no agent messages, expected
outcome lines. The one exception is a failed check or command on Claude Code, which goes with its masked
line, exit status and output tail ([the amendment](#amended-2026-10-27-owner-the-unasked-lane-reads-failed-results)). All eligibility gates, observed state-change trigger, quiet hours,
delivery records, one-flight slot, fifteen-minute floor and caps (three per session, twelve per rolling
day) remain. Only departures are raised. The preconditions for changing the default remain unmet.

Codex requires a deliberate provider grant bound to the current destination. With the flag on,
the session's Drift card shows "Allow Codex to run unasked checks", or the opposite to revoke it,
and Attention names sessions with typed goals waiting for that permission and links to their Drift
cards. The disclosure names the words, provider, destination and capacity used; the grant covers
all sessions routed to that provider at that destination. Claude Code needs no separate toggle,
but its Drift card names it and lists what each check sends: a reader who turned the flag on when
only a Codex grant could start a check would otherwise begin sending words to Anthropic with no
sign of it. A stored Codex grant keeps its revoke switch on every session page, whichever provider
checks that session today. The cue's "none of them has been checked yet" is derived from each
listed session's `departure_checked`. With the flag off, or under `--no-annotations` (which turns
the flag off), neither control nor cue is shown.

`reading_policy.set_unasked_grant` writes only this explicit words-only coverage. It is a separate
`unasked_grant: bool` body on the existing reading POST, with session identity, provider, model,
words destination and the normal explicit-press guards. It starts no analysis. It refuses paused
or disabled runs, non-loopback clients and document navigations. A grant is also refused for a
stale provider, model or destination and for a session Claude Code would check
(`no-grant-needed`); a revoke is not, and deletes the Codex grant whatever today's route is, since
a grant that could be revoked only while Codex held the route would return with it. Pause followed by Resume
clears the grant, so a reader who paused grants it again on purpose. Analyze,
legacy `allow: true` presses and Resume never grant it. Revocation cancels this daemon's running
call and refuses the next send; Pause stops both providers, and `--no-observer-model` still wins.
Already-sent words cannot be recalled. A cancelled call, or one that started and failed, keeps a
withdrawn check row for the caps, without a finding or a completed-check claim; without it a
signed-out Claude Code CLI was started again on every state change. A withdrawn row is no later
check for a standing raise's follow-up. The cancel test and the departure write share one lock, so
a revoke lands before the write or after it, and a revoke after the write still suppresses the
notification. A revoke removes the grant rather than writing the zero
that older stores interpret as the master pause.

### The alternative that was rejected

Automatic evaluation writing into the board only, with no push. It would have sidestepped the
notification contract, quiet hours, delivery recording and the platform gap, and it was the
recommendation put to the captain. Rejected because it gives up the capability the reopening was
about: a board only raise helps only the reader who comes back to look. It stays available as a
first slice if the delivery preconditions prove more expensive than they look.

### What still bounds the surviving failure class

DEC-17 records one class its rules do not remove: a false `consistent` on Goal resting on the
agent's own narration. What bounded it was that a reading was produced once per press, never
aggregated and never pushed. This decision breaks all three, which is why the rubric's acceptance
thresholds gate the switch defaulting to anything other than off. Since 2026-10-03 DEC-17 records a
second: a false `consistent` on an outcome line resting on the agent saying it finished. The
unasked lane reads no agent message, so it cannot produce that one, but the default still waits on
the re-score above. The case set is written in
parallel rather than after the build, because cases need no producer and only a threshold does.
DRC-4542 owns it.

One thing the ruling did not anticipate, found while filing that issue. A case set of source shaped
records is by construction a corpus of real session text, and `docs/captures/README.md` bans exactly
that from this repository: no prompt text, no tool input, no tool output, no file path, and never a
value a person or a model wrote. So where the cases live and what they may contain is settled on
DRC-4542 before any session is read, and it may need a ruling of its own. Synthesising the cases
instead is cheaper and carries no disclosure risk, but DEC-17 warns that a rubric validated on
fixtures the same pass writes is not validated, so the two pull opposite ways and the answer is
written down rather than settled by convenience.

Settled 2026-09-10, and built 2026-09-12: the cases stay local and uncommitted, only expectations
and results are committed, `records.safe_text` applies to anything synthesised, and a synthesised
case is admitted only when a different agent verified it than generated it. The rubric scores
judgement and extraction as two columns, never one. Judgement lands in one of five outcomes,
`correct`, `false-reassurance`, `false-alarm`, `missed-departure` and `over-abstention`, and the
report carries them as five counts with no composite figure, because the composite is exactly what
hides the one DEC-15 calls most damaging. Extraction is which expected citations the producer hit,
which it missed, and which it cited that were not expected. The file format and the admission rule
are in [docs/abstention/README.md](abstention/README.md); the cases and expectations themselves are
the captain's to write.

### What the build had to decide, 2026-09-11

The ruling settles the shape and leaves three choices to the implementation. All three were made
against the ruling rather than for convenience, and each is the kind of thing a later reader would
otherwise re-derive.

Two gates, not one, and they are different rules. One reading per collection is a flag on the loop
that offers rows; one reading at a time is an in-flight slot released when the worker finishes.
Relying on the slot for both was tried and reverted: it is released by the worker, so the
per-collection guarantee would rest on a `codex` subprocess outliving the loop rather than on
anything the function does. Measured with a synchronous worker, twenty candidate rows started twenty
readings.

The per-day cap counts over a rolling twenty-four hours rather than a calendar day. The reader this
exists for walked away at an arbitrary hour, so a midnight reset would hand a fresh allowance to a
board nobody is watching, and a calendar day needs a timezone this runtime does not otherwise carry.

The lane rides `record_history` rather than owning a second is-this-diagnose signal. `--diagnose` is
the one caller that says no to that flag, it runs a collection, and it must not start a subprocess
while reporting what the stores hold. A second flag meaning the same thing is the thing there must
not be two of.

Quiet hours are deferred to DRC-4032 and the switch ships off, which is what the amendment above
permits: the preconditions gate the default rather than whether the thing may be built.

## DEC-19: the page may report a lane, never a delivery

Decided 2026-09-11. Compass notifies through two independent producers. The server runs one
`osascript` call and exists on macOS alone. The page constructs a browser `Notification` and is the
only lane on Linux and Windows. They do not raise the same events, and the page reports nothing
back.

The page may now tell the server whether a notification lane exists in it: whether the browser
supports notifications, and what its permission is. On page load and on permission change, never
per raise, and carrying no session.

It may not report a delivery. Three things decided that, and the security argument was not one of
them: by this repository's own standard, which is what a forged post can suppress or mask, a
delivery report is side state of the same weight as `POST /api/notify`, which any local account can
already forge.

What decided it was that a per-raise report inflates the count by the number of open tabs, because
every tab computes the edge itself and constructs its own notification while the browser collapses
them to one banner; that it would be the first route on which the page asserts a fact about itself
rather than relaying a reader's action; and that a forged delivery is the single false statement
this milestone ranks worst, because it makes a reader's inaction read as their having ignored
something.

### The negative sentence, which is the part that is easy to get wrong

A report is stale by construction, and stale asymmetrically: a tab that opens sends one and a tab
that closes sends none. So an absence of availability means no lane has been reported since a given
moment, never that none existed when the raise happened.

The sentence says the first. It may not be tightened into the second, and the clause explaining why
is load bearing rather than decoration.

### Three sentences, not two, and what the build had to decide

The ruling names two cases. Building it found a third, and two rules the ruling implies without
saying.

A report has a time, and the time changes what it is evidence of. A lane reported three hours before
a raise and one reported a minute before are different evidence, and a sentence that omits the gap
makes them read alike. So the positive case carries the gap, and a report that arrived after the
raise gets its own sentence saying it is about a later moment. Rendering the positive sentence with a
negative gap would have been the quiet version of the same overclaim.

Only a working lane is a report. A tab reporting that it has no lane records nothing and clears
nothing, because several tabs can be open and one without permission says nothing about another that
has it. The absence of any report is the negative sentence above, which already claims nothing either
way.

The page resends on disagreement rather than on a timer. A report lives in the server's memory, so a
restart loses it, and the page has no way to know a restart happened. The condition is that this tab
has a lane and the payload says none has been reported. That covers the first render, the permission
grant and the restart, with no heartbeat and no token for the boot.

### One argument that was withdrawn

The first recommendation refused any report, on the ground that the page can only say a constructor
did not throw while the server can say what a subprocess returned. That asymmetry does not exist.
`osascript` exits zero under Do Not Disturb and with the hosting application's notifications
switched off, so a zero return means the scripting bridge accepted the call and nothing more. The
two lanes are the same strength, and a shared value name would have been defensible.

## DEC-20: the first screen shows goal beside direction, and drift has one home

Amended 2026-10-11 by [DEC-27](#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result): Sessions comes first in the tab order, the Sessions header carries one permanent orientation sentence and the how-to button (replacing "one screen-level sentence on a default run"), and a row's goal cell is a link on a typed goal too.

Decided 2026-09-23 (DRC-4633), on the Actions Front and Center project. DRC-4636 to DRC-4642 build
it. The session page (item 4, the session page half of item 3, and the primary control) is built by
DRC-4639 and DRC-4642. The landing view and its one screen-level sentence are built by DRC-4636,
and every session's page is one click away by DRC-4638. The row's goal slot and recorded Drift mark
are built by DRC-4637 and DRC-4641, as the amendment to
[NUI-16](design-next-ui.md#nui-16-operations-lead-observation-stays-reachable) describes.

The question was what a person sees about drift when they open Compass. Measured on a default run
the day it was decided, the honest answer was nothing: four of four sessions had no typed goal, none
had been read, and a departure comes only from a model reading, which a default run does not make.
A first screen built from drift results would have been an empty state. So the ruling puts DEC-15's
floor on the first screen and lets a result add to it, rather than the other way round.

1. Compass opens on Sessions. Drift belongs to a session, the journey never asks for grouping, and
   Projects caps each row's members and draws no member lines for a project whose sessions are all
   idle. NUI-3, NUI-5 and NUI-16 are amended to match.
2. Every row puts your goal beside the NOW line and leaves the comparison to you, which needs no
   model and no permission. With no typed goal, the goal slot shows the prompt DEC-22 permits,
   labelled "your latest prompt". Expected Output stays on the session page, because on Claude and
   Codex it reads not verifiable under DEC-17 rule 7 and a first screen of those would say nothing.
3. The word drift may name a mark, a section and a control. It never names a result: no surface says
   a session has no drift, because DEC-17 rule 4 forbids rendering `consistent with the evidence
   read` as met. An unsettled later instruction of yours is DEC-16's baseline question and reads
   "Conflict to settle", never Drift. The label asks; it does not say a contradiction was found.
4. Held to merges into the session view and the `held-to` slug aliases to it. A session with no
   project gets the same drift block once its page is routed, but reaching that page is a routing
   question this merge does not settle, so the dead end such a session reaches is not claimed
   removed here.

| State | Words on the row | Source record | Surfaces |
| -- | -- | -- | -- |
| A departure is on record, asked or unasked | Drift | the reading or the unasked check that raised it | first screen row, session page |
| A later instruction of yours is unsettled | Conflict to settle | DEC-16's later-direction floor | session page |
| A reading found the work consistent | none on the row | the stored reading, with its evidence line | session page only |
| Not checked | none on the row; the control offers "Check for drift" | absence of a stored reading | session page; one screen-level sentence on a default run |
| No goal typed | none on the row; the goal slot shows your latest prompt or is empty | absence of an annotation revision | first screen goal slot, session page |

The session page has at most one primary control, and it reads "Check for drift", replacing "Ask
for a reading" and the DRC-4603 ruling that held that label. A session blocked on you, by needs
input or an exact request, gives the primary to the raise when one is offered; without one nothing
is primary while the question is open, and the check sits below it as an ordinary control. The rule
is at most one primary, and none while a question is open without a raise.

### Amended 2026-09-24: the panel is Intent and drift, and the control is Analyze drift

[DEC-24](#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
and [DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn) amend items 2 and 3,
the state table and the primary-control paragraph.

Item 2: on the session page, a session with no saved goal shows the reader's first prompt as an
unsaved draft marked "from your prompt" (DEC-24 item 2). Expected Output becomes a checklist of up
to six lines, and on Claude Code a line may now be read against a check the session ran (DEC-23).
The row's goal slot still shows "your latest prompt": DEC-24 drafts on the session page only (item 2, as
DEC-22's 2026-09-24 amendment scopes it).

Item 3: answers name departures and never say "no drift" (DEC-24 item 1). The word drift may now
also name a level, in the Drift section and the session header pill only. "None or low" is a level
with a per-source floor, never a statement that a session has no drift, and it never reaches a row.
DEC-24 item 4 puts a question about an unsettled later direction in the Drift section. Whether it
replaces the "Conflict to settle" label for the same state is not ruled.

The state table: the "Not checked" row's control offers "Analyze drift". A level adds no words to a
row, and the Drift row mark still comes from a stored departure alone.

The primary control reads "Analyze drift", replacing "Check for drift". The rule of at most one
primary, and none while a question is open without a raise, is unchanged.

### What the session page build had to decide

Built 2026-09-23 (DRC-4639, DRC-4642). The ruling as first written said a blocked session "keeps
its answer control as the primary", and the first build read that as the first option of the first
exact request. The owner overruled that reading on 2026-09-23: no answer option is ever emphasised,
because a filled first option reads as advice to approve, and every option stays a plain control.
The primary goes to the raise that selects the waiting terminal's pane when one is offered, and
otherwise nothing on the page is primary while the question is open.

The block sits after the session's identity header rather than above it, and a blocked session's
question sits between the two, because the question outranks the check. The CURRENT ACTIVITY card is
the agent's direction beside the reader's words, moved into the block rather than copied, so the
NOW line has one renderer. The subagent rows follow the drift block, rather than sharing the
CURRENT ACTIVITY card: on a live session with 31 historical workers, those rows pushed the check
to 2019px on a 900px screen. All worker rows remain on the page.

Inside the block the check is on the first screen: the two goal fields, then the direction, then
`Check for drift` with its send disclosure beside it, then the reading, then the later-direction
block and the caveats on the typed words (the binding sentence, the discard explanation and its
button), then the departures. Measured on a live board at 1440 by 900 with a goal saved, the
button's top sat at 1010px while the disclosure stacked above it, and at 840px once the two shared a
row. The reading says it is never a verification once, in the server's disclosure, and the page's
own sentence renders only where no disclosure was published.

DEC-27 removes the resume control from the header and departures. Resume commands live on
Attention, the waiting panel and the project rail only. A terminal raise remains beside a
departure where available, whatever the session's state. Its caveat follows the rows it qualifies.

The departures section draws only with the unasked lane on, a departure on record, or a reading the
reader asked for, whose cutoff is printed there and nowhere else. That restores DRC-4543 on this
page: a panel on every session of a board whose switch is off is noise. Under `--no-annotations`
the check stays on the page, inert, with the annotations-off sentence as its one refusal.

### Where a drift row sorts, and why that makes no count

A session with drift on record joins the active group whatever its state, after sessions blocked on
you and before working ones. It is not counted in the `Active now` figure, which keeps NUI-16's
definition of that number. A `consistent` reading sorts exactly where not checked does.

The Sessions projection changes membership without changing the shared active-evidence model.
The mark reads stored departures only; it performs no fresh comparison. Its age comes from the
raise timestamp or the reading's `read_at`, not the time the goal was typed. Older readings carry
only an hour-and-minute stamp, so their age stays unknown. Both the store and page admit the new
optional timestamp while keeping those older records readable. A superseded revision uses the
session page's existing sentence. With annotations off, no mark or promotion is offered.

DEC-17 bounds its surviving failure class, a false `consistent` on Goal, partly by a reading never
being "aggregated into a count". Ordering rows by whether a departure is on record produces no count,
and because `consistent` neither shows on a row nor moves one, a false `consistent` gains no reach it
lacked. So the ranking is not the aggregation that would make a full rubric owed. A drift total on any
screen would be, and none is permitted.

### What DEC-15's indicator sentence now means

DEC-15 says there is no always on drift indicator. That sentence refused evaluation on a cadence, and
it still does: nothing here reads a session in the background. A Drift mark is a stored record shown
where it applies, the same kind of thing as an ended label, and it appears only after a reading the
reader asked for or the unasked lane DEC-18 permits. The skill body carries the same sentence and is
amended when DRC-4641 ships the mark, not before, because it describes the shipped product.

#### Amended 2026-09-24: an indicator on a cadence now exists, off by default

[DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn) amends this subsection. The
live estimate does evaluate after every turn, without a model, in the Drift section and the header
pill only. It is shown only once the reader turns its switch on, and the switch lives in the browser,
so off does not stop the server computing the level. The Drift row mark is still a stored record
shown where it applies. The skill body's cadence sentence is amended by DRC-4696 when the live
estimate ships.

## DEC-21: a reading works the first time you ask

Decided 2026-09-23 (DRC-4634). Items 1 and 2 are built by DRC-4640; item 3 by DRC-4649.
Item 4 is built and gated by DRC-4650; the amendment below records what that means. [The light harness usage bounds](../SECURITY.md#light-harness-usage-asking-a-harness-a-bounded-question)
record the current permission and producer boundaries.

On a default run the reading control tells the reader to restart the server with a flag. The press
already carries a disclosure and is already the consent a browser can give, so the startup flag was
doing a different job: it was one of the three things that stop a local process, which sends no
fetch metadata, from spending readings through a route with no capability token. Removing it is
allowed only with something that does that job instead.

1. **Superseded by [DEC-28](design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts).** The first press of "Check for drift" shows the reading disclosure with "Allow and check". The
   answer is kept in `~/.compass`, so every tab and a respawned daemon agree; `--forget` clears it,
   and the session page carries the off switch. The startup flag is no longer needed for
   reader-requested readings. It still governs goal summaries, which keep their own consent.
2. A daily cap on reader-requested readings replaces the flag as the bound on a local process. It
   counts over a rolling twenty-four hours, as the unasked lane's cap does, because this runtime
   carries no timezone for a calendar day.
3. `--no-observer-model` and its alias `--no-harness-usage` refuse every model call, the unasked
   lane included. Measured the day this was decided, the unasked lane did not read the flag at all,
   so `--unasked-readings --no-harness-usage` still started Codex readings. That was a security bug
   under the bounds, not a feature, and DRC-4649 fixed it: the off switch now attaches no lane.
4. A reading runs on the session's own harness: a Claude Code session is read by Claude Code, a
   Codex session by Codex. When that harness is not installed the check falls back to the other and
   says so before the press, so session text reaches a second provider only after the page has named
   it. The Claude Code producer needs its own caller entry under the bounds and a fresh abstention
   check before it is offered (DRC-4650).
5. The unasked check stays off by default for this milestone.

This amends DEC-17's 2026-09-14 amendment, which keeps the `--observer-model` opt-in on each
request. The press, remembered answer and daily cap now supply that opt-in. The cap was twelve
actual or reserved attempts per rolling twenty-four hours, admitted atomically before launch; it is
100 since [the 2026-10-16 amendment](#amended-2026-10-16-owner-the-budget-the-mark-and-what-it-read).
Off/on and `--forget` revoke consent without erasing unexpired spend; otherwise either would be
a way to refill the budget. A known missing Codex CLI is refused before admission.

### Amended 2026-09-23: Claude Code is built and gated

DRC-4650 builds item 4 and does not offer it. The owner ruled three things on 2026-09-23. The
gate in item 1 was opened on 2026-10-02 by the owner's acceptance; see
[that amendment](#amended-2026-10-02-claude-code-is-accepted).

1. The Claude Code producer has its own gate, `annotations.CLAUDE_ABSTENTION_CHECK`, recorded
   `not-run` because no eligible recorded case exists for it. While it stays there, no route,
   fallback, unasked lane, goal summary, page or forged request can offer, select or invoke it.
   Codex's 2026-09-14 `accepted` status was a review of Codex readings, so it does not open this
   gate.
2. While Claude Code is gated, Codex keeps reading a Claude Code session on a machine that has
   Codex, and the disclosure before the press names Codex and OpenAI and says Claude Code checks
   are built but not yet qualified. On a machine without Codex, "not yet qualified" is a state of
   its own, worded apart from "not installed". Once the gate passes, item 4 applies as written:
   the session's own harness first, then the other provider, disclosed before the press, and
   nothing else.
3. Qualifying the producer is DRC-4666's work, scorer included. The unasked lane and goal
   summaries stay on Codex.

One resolver, `reading_route.resolve`, decides the provider from the session's harness and this
machine. It reads each provider's gate before it looks for that provider's CLI, so a gated
provider is never even looked up. The page renders the route published for that session's
harness. The reading route resolves the route again from the payload's harness and refuses a
press that named a different provider, before it writes consent or reserves an attempt.
Permission is kept per provider, because allowing Codex to send a reader's words to OpenAI is not
allowing Claude Code to send them to Anthropic. An answer saved before the split reads as Codex's.
Pausing model calls and `--forget` revoke every provider, and the rolling cap (twelve attempts
then, 100 since 2026-10-16) is shared, so a second provider cannot double it. If the CLI is missing at launch, or a call fails,
nothing else is tried: a fresh press is the only retry. The flags the Claude Code call runs with,
and the fact that they are CLI restrictions rather than an OS sandbox, are in
[the light harness usage bounds](../SECURITY.md#claude-code-reading-calls).

### Amended 2026-10-05: selected Claude model keeps the Sonnet baseline

The owner replaced the single Sonnet 5 pin with a baseline policy. The selected explicit model
must meet the Sonnet 5 floor; the default request is Sonnet 5.5. Configuration, the published
route, the command and the reading stamp name that same selection. An unavailable selection
fails without retrying another model. [SECURITY.md](../SECURITY.md#amended-2026-10-05-claude-reading-model-baseline)
owns admission, provenance and the limit of the text-only model receipt. This opens no measured
qualification claim: each comparison remains bound to its own selected model and envelope.

### Amended 2026-09-24: Analyze drift and Allow and analyze

**Superseded by DEC-28:** the prior Allow step and destination/content re-authorization below are replaced by
[opt-out with a notice](design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts)
for reader-started calls. Explicit coverage still governs unasked checks.

[DEC-24](#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
renames item 1's labels: the first press of "Analyze drift" shows the reading disclosure with "Allow
and analyze". Where the answer is kept, what `--forget` revokes and the off switch are unchanged.
Keep does not count as the allow (owner, 2026-09-27, superseding this amendment's first wording):
where the disclosure has not been allowed it settles and sends nothing, and "Allow and analyze"
does the sending. A cancelled analysis is a spent attempt against the cap.
[DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) item 7 adds one
condition: the first reading that would send tool output needs a fresh "Allow and analyze" whose
disclosure names tool output and the receiving vendor as configured, and an answer given before that
does not cover it.

### Amended 2026-10-02: Claude Code is accepted

The owner, 2026-10-02: "I want you to accept the Claude Code checks so that Claude Code can be used
to check Claude Code sessions when Claude Code is running (or exists on the system)." This changes
item 1 of the 2026-09-23 amendment and leaves items 2 and 3 as they apply once the gate is open.

1. `annotations.CLAUDE_ABSTENTION_CHECK` is `accepted`. Every scored run failed, so this is the
   owner's acceptance and not a pass; DEC-17's
   [amendment of the same day](#amended-2026-10-02-the-owner-accepts-the-claude-code-producer-without-a-pass)
   and the [acceptance record](abstention/claude-acceptance.json) say so in full.
2. A Claude Code session is read by Claude Code when an absolute `claude` is on the server's PATH,
   and by Codex when it is not, which is item 4 as written. The disclosure before the press names
   whichever runs and its company, and on the Codex route says the Claude Code CLI was not found.
   With neither, the session says no analysis can run.
3. Item 4 also reaches the other way, as written: a session on any other harness, on a machine
   with `claude` and no `codex`, is read by Claude Code. Reworded (owner, 2026-10-02): the answer
   is kept per provider, so an Allow given for a provider covers every session routed to that
   provider. A reader who allowed Claude Code is not asked again for a Codex, Pi or other session
   that falls back to it; that route's disclosure, naming Claude Code and Anthropic, is in the
   session's "What is sent to Claude Code" popover beside Analyze drift, before the press.
   Allowing Codex does not allow Claude Code, so the first press routed to a provider with no
   Allow opens that provider's consent step.
4. Superseded for the unasked lane by the [2026-10-20 amendment](#amended-2026-10-20-unasked-checks-remain-reachable). At this date the unasked lane and goal summaries stayed on Codex, as item 3 of the 2026-09-23 amendment
   ruled, and the rolling cap (twelve attempts then, 100 since 2026-10-16) stays shared between
   providers.

`resolve` still reads each gate before it looks for that provider's CLI, so setting the constant
back to `not-run` closes the producer with no other change, and the "not qualified on this build"
sentences remain for that state.

### Amended 2026-10-14 (owner): the page says the Claude reader's accuracy check has not passed

The acceptance above opened the Claude Code route without a pass, and the page said nothing of it.
The README, the promise map and HOW_TO_USE promise a comparison with the goal and the reading's
limits, not accuracy, while SECURITY.md and the [abstention record](abstention/README.md) carry the
failed qualification. The owner ruled on 2026-10-14 that the "How Intent and drift works" popup and
one line of the README's limits say it, in these words: "The Claude reader's accuracy check has not
passed, and its latest correction is unmeasured, so read a level as an account of the evidence, not a
measurement."

The sentence adds a true limit and no claim. It changes no gate:
`annotations.CLAUDE_ABSTENTION_CHECK` stays `accepted`, and the [acceptance record](abstention/claude-acceptance.json)
still reads `qualification: failed` over ten scored runs, the last of which read 73 of 102 questions
correctly with 4 false reassurances. The ruling named the README and the popup only, so
`docs/promise-map.md` is unchanged. `ClaudeReaderLimitIsSaidInTwoPlacesTest` in
`test_documentation.py` holds the README and the popup to the same words. No abstention record or
qualification tool changes.

### Amended 2026-10-02 (owner): the Allow is bound to where the words go

**Superseded by DEC-28:** the prior Allow step and destination/content re-authorization below are replaced by
[opt-out with a notice](design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts)
for reader-started calls. Explicit coverage still governs unasked checks.

The owner, 2026-10-02: "bind the allow to the destination". The tool-output grant was already
keyed by destination (item 7 of DEC-23). The Allow for the reader's words was not, so a dashboard
restarted under a new `ANTHROPIC_BASE_URL` or `CLAUDE_CODE_USE_BEDROCK` sent the goal and messages
to the new endpoint under the old Allow, and the new destination appeared only in a closed popover.
The binding catches that move only where the destination was named, as item 5 says.

1. An Allow records the destination its disclosure named: `reading_route.destination` for that
   provider, published on every route as `words_destination`. It covers a press only while that
   destination is exactly the one recorded. An unnamed destination (`""`) is its own value, so an
   Allow given while nothing could be named covers presses only while nothing still can. The
   tool-output grant keeps its own rule, and is never given to `""`.
2. The press handler, the job's reservation and the page decide it from one value. The board
   publishes `providers` as covered only where the recorded destination is today's, the press
   check reads the same, and the job resolves the destination again at its reservation and is
   refused `destination-changed`, with nothing spent or sent, when it is no longer the one the
   press was admitted under (consent F4, ui5): a managed drop-in or remote settings file can move
   it while the job collects the record. An Allow whose disclosure named a destination that is no
   longer today's is refused `409 destination-changed` and records nothing.
3. A row written before the binding records no destination, so it covers no press and each reader
   is asked once more. When an Allow on record does not cover today's destination, for that reason
   or because the destination moved, the consent step opens with the server's line "Where your
   words go has changed since you allowed this, so allow it again." A refusal is never asked
   about that way: "Turn off readings" (renamed Pause model calls on 2026-10-19) and `--forget` hold whatever the destination.
4. The binding is a table of its own in the store, `permission_destination`, created in place
   inside the store's existing transaction. No column is added to an older table, so an older
   build's two-value writes still succeed against a migrated store, and an older build's Turn off
   clears every recorded destination by trigger, as it already clears every other answer.

5. What the binding detects is a change in what `destination` names. A named destination that
   moves is caught: to another host, to a cloud, or to unnamed. A move between two endpoints that
   cannot be named is not, because both are `""`, so an Allow given while the destination was
   unnamed keeps covering every endpoint it cannot name. That is every destination on Windows,
   where nothing is named and the Allow is in effect not bound. It is every Codex base URL, since
   `destination` names nothing wherever `OPENAI_BASE_URL` or `OPENAI_API_BASE` is set, so moving
   from one Codex base URL to another asks nothing; moving from OpenAI to one does. And it is every
   Claude Code setting SECURITY.md lists as naming nothing. The disclosure the reader answered says
   so: "wherever your ... settings send it, which Compass cannot name". The owner's rule that
   unnamed is a value of its own (item 1) stands.
6. The unasked lane sends under the same binding (consent F5, ui5). It sends the goal and messages
   to Codex with nobody at the desk, so before each send, at the model seam, it asks whether a
   Codex Allow covers today's destination, as a press would. Where a press would ask again, the
   check is skipped and logged, nothing is spent, and the lane's own caps are unchanged.
7. An Allow that names no destination is never bound (regressions major 1, ui5). A tab left open
   across the upgrade sends one, and is refused `400 page-outdated`. The page from before the
   binding answers a `409` by drawing the consent card again under a line about tool output, so
   the reply carries the one thing that page shows verbatim: a route with no provider, whose note
   says to reload. The board also publishes its page's `build`, and a page from this build on
   shows one line, "Reload to use the new version.", when it changes under an open tab.

This stays per provider, as item 3 of the acceptance above says: an Allow given for a provider
covers every session routed to that provider, at the destination it was given for.

#### Amended 2026-10-19 (owner): a changed destination shows the notice again

[DEC-28](#dec-28-a-model-may-summarize-a-session-and-the-summary-is-kept) supersedes this amendment
as a blocking step. A reading the reader starts no longer waits on an Allow, so a destination that is
no longer the one recorded shows the notice again, naming the new destination, before or beside the
result, rather than opening a consent step. What the binding detects and cannot detect, in item 5,
is unchanged, and so is the rule that a refusal holds whatever the destination: an answer of off
already stored is kept. The unasked lane, item 6, is not a call a reader starts and is not covered.
This is in force once the consent change ships.

### Where the unasked default stands

The unasked check is the only model reading that finds drift nobody went looking for. DEC-18 gates its
default on four preconditions and on the rubric's acceptance thresholds. Measured 2026-09-23:

| Precondition | State | Settled by |
| -- | -- | -- |
| Native delivery on Linux and Windows | not met | `notifications.native_notifier` returns a backend on darwin only; DRC-4328 |
| The off machine lane | built | #356, DRC-4034 |
| A delivery outcome recorded per raise | built | #320, DRC-4540 |
| A producer exists | met | `unasked.Lane` and `reading.CodexReadingModel`, DRC-4511 |
| DEC-17's abstention check has run and passed | not met | Codex's check is `accepted` (2026-09-14) and Claude Code's `accepted` (2026-10-02), neither `passed`; every scored Claude Code run in [docs/abstention](abstention/README.md) failed |
| Quiet hours exist | met | #357, DRC-4032 |
| The rubric's acceptance thresholds | not written | DRC-4542 owns the case set; no threshold exists to meet |

Two rows are not met and one cannot be met until someone writes it. That is the list this ruling
leaves open.

## DEC-22: your own prompt may become your goal

Decided 2026-09-23 (DRC-4635). Built by DRC-4643: the annotation store keeps typed and explicitly
adopted words with their source.

Most sessions have no goal from the reader, so there is nothing to check drift against. The fastest
goal is the one the reader already gave the agent. Existing rulings settle what may not be adopted:
text the agent wrote is DEC-17's surviving failure class by construction, and an observer goal is
derived the way the observer snapshot is, which the rule 7 amendment calls "a paraphrase of the
session, not evidence about it", and a paraphrase is no better as a baseline. Workflow goals are refused too, because who wrote one is mixed and they
join on newlines where the typed fields are one line each.

1. The reader's latest prompt or first prompt may be adopted. The latest is what the board already
   shows: on Claude the `asked` instruction, the first line of the newest prompt clipped to 140
   characters; on Codex the published title, only when `states_work` accepts it, because Codex titles
   a bare continuation too. The first prompt is a new published field on both harnesses, admitted to
   the history prompt-text allowlist with its own reason.
2. On a session with no goal, "Check for drift" adopts the prompt the goal slot shows and checks
   against it, so the path is one press. Choosing the first prompt, or adopting without checking, is
   in the goal field.
3. An adopted revision stores its source prompt's time beside the save time, and DEC-16's
   later-instruction floor and reading eligibility key on the source time. Both keyed on the save
   time when this was decided, so adopting a first prompt would have settled every later instruction
   silently, and adopting on an ended session would have withheld the reading with a false reason.
   Codex now publishes the timestamp paired with its latest and first prompts. A missing or
   invalid source time still refuses adoption with a sentence saying why.
4. The mark, "from your prompt" (since 2026-10-23 the source line reads "Drafted from your first prompt"), shows in the goal's source line, in the reading's evidence line and
   in one sentence of the board-wide disclosure. Editing adopted words makes an ordinary typed
   revision, because the reader has then typed them.
5. Adopted words do not make a session eligible for the unasked lane, so one press on many rows
   cannot quietly widen what that lane spends.

Authorship is inferred, not proven. A prompt counts as the reader's because the harness recorded it
as a user message and the injected-prompt filter did not recognise it, and that filter fails open. A
dispatch prompt from an orchestrator or a headless run also arrives as a user message. The mark
exists so a reading against adopted words says where they came from.

A source token and a source time are new published fields and take the three hand declarations
AGENTS.md's Measured Invariants names. They need a DEC-15b admission only if the history copy keeps
provenance. The first prompt needs the allowlist admission above whatever else is decided.

### What prompt adoption preserves

The server accepts a closed latest/first choice and the displayed text/time pair, then resolves
that pair from its own row. A changed pair refuses rather than choosing new words silently.
Implicit adoption refuses an existing goal; an explicit first/latest choice also compares the
saved revision. Save time remains the time of the reader's act. Source time controls the later
direction floor and final-reading eligibility. The assessment carries its own source even after
its revision is evicted. Output-only edits preserve goal provenance; explicitly saving a goal
makes a typed revision even when the letters match. No adopted current goal enters the unasked
lane, including one with typed output or older typed revisions.

First prompts are bounded published excerpts, not full transcripts. The first-record scan reads
at most two MiB, refuses an unread prefix, and never calls a later record the first. Both source
controls show the excerpt before adoption; clipped sources are named as excerpts. The same
annotation scrub and 240-character bound apply on save.


### Amended 2026-09-24: the session page drafts from your first prompt

[DEC-24](#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
amends items 2 and 3. On a session with no saved goal, the session page's goal field shows your
first prompt as a draft marked "from your prompt", and pressing Analyze drift adopts that draft in
the same press. The evidence window of adopted words starts at their source time. A message that
matches a correction you copied is never adopted as a goal.

### Amended 2026-10-01: up to five of your prompts may be chosen

Owner, 2026-10-01 (Q7 of the DRC-4758 decision block), amending item 1 and "What prompt adoption
preserves". The closed latest/first choice gains a third source, `chosen-prompt`: one of up to five
of the reader's own prompts from the session's observed record, offered by "Use your prompt".

- The list is `annotations.prompt_choices`: the earliest prompt in the record first, then the most
  recent, a repeated text offered once, at most five. Each is a `user_message` fact of this session
  that `reading.author_of` calls the person's, with a valid time and its whole words. A correction
  copied from Compass, a harness control and a local command are refused exactly as the
  first-prompt draft refuses them; a local command already reaches the record with no words.
- Each is resolved whole: its words as a reading reads them, clipped to the goal's cap (1,000
  characters since [2026-10-27](#amended-2026-10-27-owner-the-goal-holds-1000-characters))
  with `cut` saying the offer is an excerpt. The text offered is the text an adoption stores.
- It is published only on the focused `/api/project-context` as `prompt_choices`, beside the
  levels, and never on `/api/data`. It is not stored, not in session history and not a history
  field. Only an adopted choice's words become `annotation_goal`, the path the first and latest
  prompt already take.
- An adoption names the fact id (`prompt_fact`) with the displayed text and time. The server
  recomputes the list from its own record and adopts only an entry with that id whose text and
  time still match, under the source token `chosen-prompt` and the entry's own time, which then
  keys the later-direction floor, eligibility and the evidence window as the other two sources do.
  A pasted correction's fact id, a forged id and changed words all adopt nothing.
- Adding a direction over an unsaved chosen draft is not built: `add_direction`'s adoption still
  resolves only first and latest, and refuses this source. The page says so beside the pending
  line, as it does over an unsaved edit, and sends nothing.

### Amended 2026-10-01: "Use your prompt" fills the goal box

Owner, 2026-10-01 (Q7, DRC-4758 slice D2), amending item 2's last sentence ("Choosing the first
prompt, or adopting without checking, is in the goal field") and "Both source controls show the
excerpt before adoption" under What prompt adoption preserves. The nested "Use a prompt" and
"Your latest prompt" disclosures and the "Use latest prompt without checking" save are removed.

- The goal's label row holds one `<details>` menu, summary "Use your prompt", listing the server's
  `prompt_choices` in their order as buttons: "First prompt", then "Latest prompt", then "Earlier
  prompt", each with its own time and its words clamped to two lines. Over a session that opened
  with a harness control the first entry is named "Earliest prompt", since it is not the first.
  An excerpt says "Shown excerpt only." in its option. A `<details>` of buttons rather than a
  listbox popover or a `<select>`, because the disclosure lane restores its open state across a
  poll redraw and each option keeps its own focus key, where a popover's open state and active
  option are lost on every redraw (DRC-4758 critic 14).
- Choosing one saves nothing. It fills the Goal box as a pending adoption, held in tab memory
  (`nextIntentChosenPrompts`) and returned by `nextIntentDraft`, so the draft's tint, its marks
  ("from your prompt · HH:MM", "Shown excerpt only." for an excerpt, Looks right until
  2026-10-02), Analyze's
  implicit adoption and Keep all read it. Focus moves to the box and the polite region says "Goal
  filled from your prompt. Not saved."
- Looks right, or Analyze over an empty goal, adopts it under `chosen-prompt` naming its fact id.
  Amended 2026-10-02 (owner): Save intent replaces Looks right as that press.
  Over a saved goal, Save intent adopts it with the saved revision, and Analyze is refused with the
  unsaved-edit sentence until then, because `/api/reading` refuses an implicit adoption over saved
  words. One keystroke in the box makes the words typed (item 4).
- The choice goes on Undo changes, Escape, Clear, a typed save, once its words are the saved goal,
  and once the server no longer offers the same words at the same time under that fact.

### Amended 2026-10-02 (owner): a native select

Owner, 2026-10-02 (ask 2): "When I said to make it a dropdown, I literally meant for you to make it
a Select dropdown." The `<details>` of buttons in the first bullet above sat at the right of the
label row and, opened, took the whole row, so "Use your prompt" flashed to the left and a 227px list
pushed the box down. It is now a native `<select>`, which supersedes that bullet's rationale (critic
14): the poll already defers its paint while a select holds focus (`next-render.js`, the row "An
open `<select>` option list" in [reader state](design-reader-state.md#the-inventory) owns it), so a
redraw does not shut the list mid-choice.

- The closed face reads "Use your prompt", at the right end of the Goal label row, at most 18rem
  wide. The browser's own list drops over the page and moves nothing. Its accessible name is "Fill
  the goal from one of your prompts".
- Each option reads `First prompt · 08:02 — Make the retry queue survive…`: the name as above, the
  time, "· excerpt" where the server clipped the prompt, and the words cut at a word near 60
  characters. The box always receives the whole prompt.
- A pick fills the box exactly as a choice did, and focus stays on the select, so arrowing through
  it where each arrow is a change previews each prompt in the box without moving the reader into
  it. A poll that waited while the list had focus is taken by the pick, so the page draws once.
- While the box holds the pick untouched the select shows it; the first keystroke puts the face
  back to "Use your prompt" in place, so the same prompt can be picked again.
- The draft's marks ("from your prompt · 08:02") and the saved source line sit in the row under
  the box, between the count and Clear, as an outcome line's source sits between its count and
  Remove. That row keeps one control's height and does not wrap. Both earlier places moved
  something, measured in Chrome at 1440x900. Drawn between the label and the select, the marks
  wrapped the select 48px down the moment a pick drew them. Drawn on a line of their own under
  the label row, they moved the box the pick fills 25px down, and the first keystroke pulled it
  back up under the caret. The select, the box and the Expected outcome field below it now hold
  their places at rest, after a pick, after typing and after a redraw, at 1440, 760 and 375.

### Amended 2026-10-12 (owner): Base UI Select

The owner replaced all native choices with shadcn Base UI Select. The 2026-10-02 native-list
mechanism above is historical: after an async prompt read, browser activation had expired and
`showPicker()` could return without opening a list. The first press now opens a popup immediately
with "Loading your prompts" as a disabled item, then choices or a stated absence (none in the part read, or the read failed) in
the same popup. It drops below the trigger and moves no page content.

The chosen fact, pending adoption and save meaning remain the same. Arrow keys navigate the list;
confirmation chooses and returns focus to the trigger. Escape closes only the popup. The trigger
keeps its existing focus key and 18rem wide-screen width, filling the remaining label-row width on narrow screens.
React retains its open state through a refresh; the bounded board hold protects its anchor while
open. [Reader state](design-reader-state.md#an-open-option-list) owns the current mechanism.

### Amended 2026-10-04 (owner): an adopted goal is read whole

The owner, 2026-10-04, after
[the first drift replay run](drift-replay/README.md#the-first-run-2026-10-04), delegated this
build: "do the 'What I'd do next' section yourself". That run found a goal adopted from the
opening prompt keeps 240 characters, and on Claude Code a latest prompt only its first line, which
in one session cut off the instruction that mattered and in another kept only plan-file preamble.

- When the revision a reading reads was adopted (`goal_source` is one of the three prompt sources,
  with `goal_source_at`), the reading sends that prompt's whole words as the Goal the model reads,
  in place of the clip: the reader's own `user_message` at the source time, its `reader_words`, up
  to 1,000 characters, redacted as every reader's message is (`reading.adopted_prompt`). A copied
  correction is never the source; two prompts at the same moment are told apart by which one the
  goal's words open, and neither is guessed at.
- The stored goal, the page and the history keep the clip. Nothing new is stored or published, and
  the criterion's clause is still the goal box's words.
- The words come out of the reader's half of the prompt, before any other message is read whole,
  and only where the room left holds them, so they never cost an entry. That prompt's own row in the
  record then keeps its first sentence rather than sending the same words twice.
- If the prompt could not be found in the record read (no message of the reader's at its time,
  two within a millisecond that the goal's words do not tell apart, or one with no words left), or
  its words have no room, the reading reads the clip and the cutoff sentence says which.
- The owner, approving the Analyze drift plan, amended this on 2026-10-04. The tail lookup
  fell back to the goal clip in all 123 adopted readings in the replay. At a press, a separate
  source lookup now uses the [newest and opening reads](#long-session-direction-and-prompt-reads),
  retaining at most 4,096 user-message facts. It uses the same author, source-time and ambiguity checks as the tail lookup.
  Its capped, redacted words stay in memory, cached for at most eight transcripts by path,
  harness, session, size and modification time. Neither the cache nor its facts enter a store or
  a page response. They supply only the adopted Goal, leaving the evidence ledger unchanged.
  A model-free replay found the adopted source at all 99 cuts, with no fallback. A source outside
  these bounds still falls back with the cutoff note above.
- The goal box tells the reader: where an adopted prompt was clipped, "Shown excerpt only." under the
  box is now "Excerpt. Analyze reads up to 1,000 characters.", in the draft's marks and in the saved
  goal's source line alike, true past 1,000 characters and on the fallback alike. Short, because
  that row holds one control's height; the 375px layout was not re-measured in a browser for this
  change. "Use your prompt" still names an excerpt "· excerpt" in its option. (Since 2026-10-23 the cue
  reads "Shortened here; Analyze reads the whole prompt" and sits on the source line above the box.)

What is sent does not change in kind: the reader's own messages already go whole up to 1,000
characters ([the 2026-10-01 amendment](#amended-2026-10-01-a-reading-sees-the-readers-whole-message)),
and the adopted prompt is one of them.

### Amended 2026-10-27 (owner): the goal holds 1,000 characters

The owner, 2026-10-27, after choosing a prompt from "Use your prompt" and finding it cut at 240
characters mid-sentence, with the `/goal` instruction inside it out of reach. The ruling: Compass
works for the person using it, and a bound on their own words that makes it harder to use is not
needed. It relaxes the 2026-10-01 ruling that let "Use your prompt" publish only 240 characters of
each prompt.

- The goal has its own cap, `RuntimeConfig.annotation_goal_cap_chars`, 1,000 characters. That is
  `reading.LEDGER_WORDS_CAP_CHARS`, the most of an adopted prompt a reading already read in the
  clip's place (the amendment above), so a chosen prompt is now shown, saved and read as one string.
  Before, editing a clipped goal turned it into typed words and the reading went back to the 240.
- An expected outcome line keeps its 240, and so does every stored reading detail. The page
  receives the goal's cap as `annotate_goal_cap` beside `annotate_cap`, and its counter, its box
  and its "Shortened to fit" note read it; a page served without it falls back to the line's cap.
- Everything that offers a goal takes the goal's cap: `prompt_choices`, a later direction's
  `goal_choice`, a `/goal` condition's `offered` excerpt, and Find goal's answer. Session history
  keeps its own 256-character field, so a long goal is recorded there as its opening.
- Five budgets sized against a 240-character goal grew with it. The reading prompt's intent
  share went from 9,728 to 12,800 bytes, because the widest goal and lines (written in emoji)
  measured 12,515 and past the share every outcome line goes unasked; the record keeps at least
  3,584 bytes in that worst case. The annotation request body cap went from 12,288 to 16,384
  bytes for the widest pasted body, 14,798. The goal's clause in a stored reading keeps the
  goal's cap, so "What the analysis read" quotes the goal it read, and the level that reads a
  goal with no lines as its one line reads all of it. Steer back's lines went from
  2,000 to 2,760 characters, the 760 the goal gained, so no correction that composed before is
  refused; the cap is 2,760 + 8 × 277 + 7 × 132 = 5,900. The Live monitor sends the whole goal
  where it sent 600 characters. The annotation store's 16 MiB read limit did not move: 256
  sessions at 16 revisions of a 1,000-character goal and six full lines, with the widest fact ids,
  measured 13.6 MB.
- Not done: the first-prompt draft still comes from the row's 140-character `first_prompt`, so a
  long first prompt is drafted as its opening and read whole by Analyze, as before.

### Amended 2026-10-04 (owner): recover listed messages inside the window

At a reader's press on Claude Code or Codex, the producer now verifies each already-listed person message
inside the reading window, through its observed stop. A bounded reverse lookup reads at most the
latest 32 MiB of the parent transcript. Matching requires the same fact id and timestamp; meta,
sidechain and copied-correction records retain their existing author rules. Conflicting raw
sources (compared by a raw-content fingerprint), a missing file, or a file changed since collection
supply no words. The row keeps its
listed title rather than falling back to unverified words. A message outside the byte bound also
keeps its title. No new entry enters the citable list, and the history and listing limits still
apply. This recovers words a history row omitted; it does not turn the bounded ledger into a full
transcript.

The recovered words stay in memory, up to 1,000 characters each, and replace titles only within
the reader's existing share. Credentials are masked before whitespace is folded, including before
slash-command arguments are rendered. This press-only scan is uncached. The adopted Goal still
uses its separate [newest and opening lookup](#long-session-direction-and-prompt-reads); the press uses its uncached raw-masking arm. Default callers keep
the existing lookup cache and prompt. Nothing new is stored or published, and an unasked reading
does not run this recovery. Other harnesses retain their existing in-tail words.

### Amended 2026-10-04 (owner): disclose reply crops and use remaining room

Each complete bounded agent text record now supplies the length of its full masked, folded text.
When the prompt sends a cropped reply, its trusted row labels the excerpt "first 1,000 of N
characters", using the actual excerpt length when it is shorter. A legacy record with no measured
total makes no length claim. The count and words stay off the page and both history stores.

Entries are still selected by title first. The reader's half is offered before the agent's quarter;
after those passes, additional selected agent excerpts may use the remaining prompt room, newest
first. No entry is removed to fit words, the adopted Goal keeps its priority, and the 16 KiB cap
still includes the header and every row. This changes the amount of content already disclosed,
so the consent content version stays at 2. Sending a new class of content requires a new version.

### Amended 2026-10-05: source recovery retained with failed accuracy qualification

The owner delegated acceptance to adversarial agent review. That review accepts retaining
bounded source recovery and crop disclosure as source-fidelity behavior, with model accuracy
unresolved. The original expanded-input replay failed its gate: grouped no-drift departures
increased, intent and steering offers were lost, and four previously drawn protected rows across
four marked claims were withdrawn. Three of nine protected claims lost every former row; the
fourth affected claim retained another row. Remaining calls stopped. Source-only saved-reply
replay found no deterministic parser or page defect; it did not establish improved accuracy or
disprove the protected marks. CI, operational availability, agent review and a later limited
study cannot turn the failed campaign into a pass.

Recovery still verifies the selected source, reserves the reader's share, preserves selected
evidence and citation identities, and falls back when source or room is missing. Historical
marks, keys and guards remain. A rollback remains available: a blanket rollback would also
remove the separately promised adopted-goal recovery, while a narrower rollback of remaining-room
agent expansion can preserve that recovery and disclosure. The adopted-goal contract does not
require retaining agent expansion.

### Amended 2026-10-05: the original closed-proof proposal is retired

The all-flags closed-proof proposal is retired as infeasible under its approved scope. Its
original denominator is 61 wrong not-shown flag occurrences; subsequent protected re-marks leave
57 under current marks. These are occurrences, not distinct items. No closed-tier clearance was
verified. Even the generous incidence bound admits at most 35 original occurrences as having a
closed command in the claim's own turn; it proves neither execution, relevance, retained evidence
nor attribution. Feasibility evaluation is complete; the proposed publisher and its model gate
were not built or passed. Retirement authorizes neither a smaller denominator nor shell, worker,
background or connector expansion.

### Amended 2026-10-05: acceptance and empirical limits remain separate

Identified agent-operated application and ruling reviews may supply the owner's delegated
acceptance. The original cold study still requires two actual uncoached people. It remains
deferred until both use the ready build, select real sessions, give their own consent, answer the
protocol questions and approve the exact captures and destination. Agents cannot supply human
testimony. Historical delegated-work attribution remains unknown where original structural
parent links are absent; a new capture cannot establish them retroactively.

### Amended 2026-10-06 (owner): the cold-study requirement is retired

The owner removed the requirement for two uncoached participants and instructed that no cold
study will be run. DRC-4722 is cancelled and is no longer a prerequisite for final milestone
acceptance. This supersedes only the cold-study requirement in the preceding amendment. It
supplies no human usability verdict or producer accuracy qualification. Agent-operated
application acceptance remains allowed; the retained application, privacy and accuracy checks
still need their own evidence. Optional exploratory feedback retains participant consent,
capture review and redaction requirements. The former protocol and prior run records remain
available as historical evidence.

### Amended 2026-10-05 (owner): the newest recorded final reply is read whole

The owner asked that the agent's final answer reach the reading whole where it fits, because its
first 1,000 characters often dropped the sentence that says what was done. Delegated review
removes the retired closed-proof proposal as a prerequisite. This source change has its own
privacy and consent review, independent of the prospective 8b accuracy study. Neither review
qualifies the failed original 4b or DEC-17 for accuracy. A fresh campaign binds its actual
requested model and matched conditions, with exact predicates, repeats, blind marks and stop
rules frozen before output. Old outputs are not that campaign's baseline; model labels describe
routing, not qualification or a provider snapshot receipt. At this amendment the fresh
campaign is not runnable: its exact protocol and aggregate transport guards still need review.

What qualifies: A reply is final only when its own record says so: the top-level assistant
text record of the parent session carries `message.stop_reason` equal to `end_turn`, a UUID, a
timestamp and the parent session id, and is not meta, sidechain, a child agent's or the CLI's
`<synthetic>` notice. Text with no tool block, a quiet session, an idle state, adjacency to a
check and a newer timestamp each describe a mid-turn message as well, so none is evidence of
finality. `project_context._agent_message_event` is unchanged and still admits non-final text;
only the lookup tests the stop reason.

Where it is read: After the producer has applied the reading window and the observed stop and
the byte bound has selected its rows, `build_prompt` shows the lookup the identity and time of
the agent rows it selected, once. The lookup restores words for the unique newest of those that
is final and for no other row: it cannot widen the list, renumber a citation, revive an earlier
or later record, import a child transcript or infer an answer the prompt does not carry. A newer
selected row that the source cannot prove non-final, two finals at one instant, and a duplicate
UUID or fact that differs in any field that decides finality (compared as a fingerprint of the raw
record, before masking, so equal masked words cannot hide it) all keep the excerpt. An identical
duplicate is one source. A legacy fact with no source keeps its excerpt.

Which file: The press stamps the transcript (device, inode, size, modified time) before it
reads the session context, and the lookup refuses unless the file still has that stamp before and
after its scan. The scan is newest first over the complete file, in memory only, with a
32 MiB file bound and a 1 MiB bound on one assistant record. A larger file keeps the excerpt
and the cutoff says the whole reply could not be confirmed: a timestamp inside a tail cannot
prove an earlier conflicting duplicate is absent. Conflicting candidates also say so when none
can qualify; a missing or refused selected source or an incomplete scan does too. The
lookup checks the complete yielded byte count so a silent short read or I/O error cannot
qualify a tail. Only rows each proved non-final
are silent when no final qualifies. Nothing is cached, spooled, logged, put in
history or published; the lookup answers an outcome token, the row's own fact id and time, and
the words. The drift replay passes the same lookup under its cut file's stamp.

Whether it fits: The reader's words allocate first. Before prose masking, the lookup refuses
raw message text above 16,384 characters; a long single token otherwise spends seconds being
masked only to be rejected. Every duplicate still has its raw finality signature compared, but
its identity and whole words are recovered only once in the scan. The reply is normalised to one line,
masked as every excerpt is, quoted as one JSON string with the menu heading neutralised, and
admitted only as the complete row: its serialized UTF-8 size must fit the agent's quarter
(4,096 bytes at the 16,384-byte cap) and its growth over the summary row the room left. A reply
that does not fit is not clipped under a "whole" label; the original excerpt stands byte for byte
and the cutoff says the newest final reply was too long, or could not be confirmed. The agent's
other messages keep their 1,000-character bound and may take unused room as before.

The consent boundary: No consent tier is added. No shell or MCP output is added to the
prompt. The unasked lane never reaches the lookup. Because a reply sent whole is different content
from an excerpt, `reading_policy.CONTENT_VERSION` moves from 2 to 3 (`WORDS_CONTENT_VERSION` stays
1), and the route's "What is sent" list names the newest final reply and the 4,096-byte bound.
SECURITY.md's [Claude Code reading calls](../SECURITY.md#claude-code-reading-calls) says the same.

### Amended 2026-10-06: a whole final reply binds the native parent identity

The Claude collector publishes a shortened session key, while native assistant records
carry the full session UUID. Comparing those two strings verbatim refused real parent
replies even when their selected fact and timestamp matched. The lookup now uses the
canonical lifecycle identity normalizer to bind the shortened key to the complete UUID
filename, then compares each parent assistant record with that full identity. Meta and
child records stay excluded. Any missing or conflicting parent identity in the complete
scan refuses recovery, including an unselected reply from another full identity with the
same shortened key. The scan includes bounded JSON records that encode an assistant
type with Unicode escapes; an oversized escaped shape conservatively refuses recovery
before parsing. Exact session keys retain their existing path.

A prefix comparison alone was rejected: two native sessions can share a display key.
The file identity, complete scan and existing fact/time joins must agree. This repair
changes neither selected rows nor consent nor byte bounds. It corrects source recovery;
it supplies no evidence that a model assessment is accurate and does not qualify the
failed study. A fresh measurement must bind the repaired source bytes before output.

### Amended 2026-10-06: consent binds the disclosure shown by this route

A non-Claude press discloses words-only content, even when the same provider can later
read a Claude session with agent messages and its newest final reply. Writing the build
epoch for every Allow let the narrower disclosure cover that later content. The policy
now stores the tier derived by the server from the actual session harness. Client-supplied
version fields are ignored. An already verified wider Allow is retained on a later narrow
press only while both destination bindings and the provider still match.

Existing version-3 grants have no harness-origin record, so a valid wider grant cannot be
distinguished from a mislabeled narrower one. The wide epoch moves to 4: the next Claude
press renews once, then current consent is reused. A prospective-only repair was rejected
because it left ambiguous stored grants valid. Adding a column was also avoided so an
older build can still write its original three-field schema; its version-3 writes cannot
authorize this build at 4. The words-only tier stays 1, including the 2026-10-03
grandfathering ruling. This repair adds no content class and establishes no model accuracy.

## DEC-23: a Claude Code session's record of its checks may show the work

Decided 2026-09-24 (DRC-4674). DRC-4676 builds the record and keeps it off every model prompt.
DRC-4677 builds items 7 to 10 for the single Expected Output constraint: the tool-output grant keyed
by provider and destination, the destination named or refused, the result-bearing prompt row with
its output tail quoted as data, the reader's words reserved first in the byte bound, and item 8's
rules in the resolver and on the page, with the window read from the revision's stored window start
(DEC-24 item 13, built by DRC-4679), or from its `baseline_at` on a revision saved before it stored one. A pass that a later command may have changed files after, in
the same call or a later one, carries no `consistent` either (item 3's blocker, applied to a
reading). What counts as work is per harness: a work result on Pi and a check on Claude Code, and
never the agent's own final answer on Claude Code or Codex; on Pi the harness publishes its result as
work. The agent's account is not work. Since
[DEC-17's amendment of 2026-10-03](#amended-2026-10-03-owner-the-agents-own-words-are-evidence) one
of its messages may still carry a line's verdict, as what the agent said; a final answer may not.
Per-line outcome lines are DRC-4685's. SECURITY.md's
[Tool output in a Claude Code reading](../SECURITY.md#tool-output-in-a-claude-code-reading) says
what is sent and where.

A Claude Code reader who asks whether the session did what they asked gets "not verifiable" every
time, because the rule 7 amendment found that on Claude and Codex nothing in the record
demonstrates work. The Claude transcript does record every tool call and its result, and
`records.tool_outcome` already joins a call to its result by id and keeps the name only. DEC-5 let
the after-tool hook post a shape identifier and a tool name and nothing more. Pi, the one harness
whose record shows work, published only a derived count of validation checks passed, with no
command or output (`project_context._work_evidence`).

Pi's results now follow items 1, 2 and 8 as well (owner, 2026-09-27, DRC-4690). The count
grepped from any output read a failure as a pass, `0 passed` as a pass and `echo '5 passed'` as a
pass, and dropped a flagged failure entirely. A Pi validation run is now counted only for a runner
on the closed list, failure is read first, and a zero count is "ran, result not recorded". The
error flag is read as the 0.87.1 capture
([docs/captures/pi/validation-results-0.87.1-macos.jsonl](captures/pi/validation-results-0.87.1-macos.jsonl))
shows it: set with Pi's own "Command exited with code N" line it is a nonzero exit, set with a
timeout line it is a run with no result, and set with no status line the call never ran. The
latest run of each check is kept, and its fact carries `subject` and `result`, so item 8 applies
to it: `check_supports` now keys on a check on any harness, not only Claude Code's
`tool_report`. The title is Compass's and no command or output is published.

Three rulings from the review round (2026-09-27) hold it there. A Pi check never enters the
semantic history store, as item 6 already said of Claude Code's: the store keeps an allowlist of
fact keys without `subject` or `result`, so a superseded pass came back from it as a bare "5
validation checks passed" that nothing could supersede or age, and it carried a `consistent` while
the latest run had failed. A subjectless Pi bash result already on disk from an older build,
including the pass the build before this read from `echo '5 passed'`, supports no verdict at all.
A clear or absent flag beside Pi's own exit line is outside what the capture shows, since a
`tool_result` extension can clear the flag on a call that threw, so such a run is never a pass.
And every Pi tool except `read`, `grep`, `find` and `ls` ages an earlier pass, `powershell` and
extension tools included: guessing that an unknown tool only reads is what would produce a false
`consistent`.

The ruling is yes, bounded, and readable by a model. Two other answers were put beside it. Page
only, never sent to a model, shows the work but leaves no reading able to judge Expected Output on
Claude Code. Refusing leaves every check on a Claude Code session not verifiable. What the ruling
costs is a new content class that leaves the machine under the destination rule in item 7, and a
new surviving failure class: a false `consistent` resting on a success the tool reported. DRC-4666
qualifies the producer against it.

1. Three things are never conflated: what was run, what the harness recorded as its result, and
   whether the requested outcome exists, which Compass never claims. Evidence is the recorded
   result. A background launch is not a success, and an absent or malformed error flag is unknown,
   never success. `records.tool_outcome` turns an absent flag into `False` today, and that is the
   reading this item refuses.
2. A check's result comes from one of three sources, in this order, and otherwise reads "ran,
   result not recorded". First, the harness's explicit error flag, which is the whole call's status
   and is attributed as the closed lists set out: a pipe into `tail`, `head` or `grep` reports the
   last stage. Second,
   a runner summary line in the recorded output tail, from the closed set below. Third, for failure
   only, a failure marker in the recorded output tail, from the closed set below, which may record
   a failure and never a pass. Output text is never read as success any other way.
3. A check is a shell command whose runner is on the closed list below, matched per segment, split on
   `&&`, `||`, `;`, `|`, `&` and newlines, after stripping `cd ...`, `NAME=value` assignments and the wrappers the list names.
   The shell's `test` and `[` builtins are never checks. Among shell commands, only checks can
   support a departure or be cited in a correction (DEC-24 item 7); a person's or the agent's own
   words keep what DEC-17 and DEC-24 items 6 and 9 let them support. Other commands and probes, such as a
   `grep` with no match or an `ls` of a missing path, are counted and not listed. A segment that is
   neither a check nor on the closed read-only list below may change files without the transcript
   recording a write, so one run after any check's latest passing run blocks the live estimate's
   "None or low" (DEC-26 item 1). It is never counted as drift. The owner ruled this on review the same day,
   as part of this ruling.
4. For each distinct check only its latest run is listed and counts, and it says when an earlier
   run of the same check failed without listing that run. A file write after a passing run marks
   that pass as before the last change. At most 12 entries are listed, chosen in this order: latest
   runs that failed, then latest runs with no recorded result, then latest runs that passed, then
   written paths, newest first within each. Amended 2026-10-04: runs with no recorded result now
   come last ([the amendment](#amended-2026-10-04-no-recorded-result-is-listed-last)).
   The rest are counted ("and N more"). Every answer about
   checks is derived from the full scan, never from the listed entries alone, so a dropped entry
   can never produce "No check was recorded" or a reassuring answer.
5. Fields read: the check's own segment, its runner form and arguments and never the rest of the
   shell line (the owner narrowed this on review the same day, as part of this ruling), after
   credential redaction and masking, word by word, of the forms redaction cannot recognise: a
   `NAME=value` assignment; the value after `--password`, `--token`, `--api-key`, `--secret`,
   `--auth`, `-p` or `-P`, joined by `=` or in the next word (pytest's `-p no:<plugin>` is shown; see
   [the 2026-10-27 amendment](#amended-2026-10-27-owner-pytests--p-no-is-shown)); an
   `Authorization:` or `X-Api-Key:` header value; and the password in `user:password@`, up to
   the last `@`. These forms and no others, as SECURITY.md says. A substituted command is shown
   as `$(…)` and a trailing comment is dropped. Clipped to 120 characters; the last 180
   characters of output, the existing ledger cap, with redaction run over the whole read window
   first; a written path relative to the session's working directory, the folder it began in,
   which a later `cd` does not move; and, for a segment that is neither a check nor on the
   read-only list, its time only, never its text, used on this machine. No file content is read
   as a field, and never an Edit or Write result body; the output tail is whatever the runner
   printed.
6. Where it lives: the observed record only, as a new fact type the reading counts as work. It is
   kept out of the semantic history store and out of every session row field, and it is named in
   `history.PROMPT_DERIVED_CARRIERS`. SECURITY.md adds it to the named reads, moving the count
   `test_documentation` pins, and scopes the irreversible-actions sentence about tool output.
7. **The prior Allow requirement is superseded by [DEC-28](design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts); the destination and content bounds remain.** Where it may go: to the reading producer that reads the session, or to the fallback route
   `reading_route.resolve` selects and discloses before the press, and on either only after a fresh
   "Allow and analyze" (DEC-21's "Allow and check" as DEC-24 item 5 renames it) whose disclosure
   names tool output and the receiving vendor. An answer given before tool output was named does not
   cover it. The disclosure names the destination as configured, including an `ANTHROPIC_BASE_URL`,
   Bedrock or Vertex setting in the daemon's environment or in managed settings, which still apply
   under `--restricted`. Where the destination cannot be named, tool output is not sent. Those
   settings are examples, and SECURITY.md names the Codex route's equivalent. The live drift
   estimate (DEC-26) is a further consumer on the machine: it derives a level from these facts,
   published on the session payload only, never on a row, in history or in any off-machine payload.
8. What a reading may conclude. The latest run of a relevant check failing inside the evidence
   window may support a departure. A `consistent` on Expected Output needs the latest run of a
   relevant check passing inside the window with no later write, and is labelled as reported by the
   tool, not inspected. Absence supports neither. DEC-24 item 13 sets the evidence window.
   Amended 2026-10-14 (owner): a recorded write outside a named folder is not a check and does not
   settle a line ([the ruling](#amended-2026-10-14-owner-a-write-outside-a-named-folder-does-not-settle-a-line)).
9. Tool output is quoted into the reading's prompt as untrusted data, never into an instruction
   Compass writes.
10. The unasked lane never receives tool outcomes until DEC-18's rubric thresholds exist.

This amends the rule 7 amendment of 2026-09-10, whose "On Claude and Codex nothing does" no longer
holds for a Claude Code check; DEC-17 carries the amendment.

### The closed lists

The producer prompt states item 8's relevance rule for the whole Goal or outcome line, outside
the reader's words and quoted tool output. A generic passing suite does not establish a feature or
browser behavior that it does not exercise. Relevance remains a model judgement: the resolver
checks the recorded status, time and subsequent changes, but does not prove semantic coverage.
These instructions do not establish a passing qualification or open the Claude Code gate.
One class of line is the server's to settle instead: see
[the 2026-10-01 amendment](#amended-2026-10-01-a-line-about-what-the-agent-tells-you-cannot-be-shown).

The owner kept that admission contract on 2026-09-30 (DRC-4749). A command-status-only rule would
make ordinary feature and browser clauses not verifiable even when a relevant check ran. Keyword
overlap and a coverage flag supplied by the model would instead call an unproved connection proof.
The record scan selects each check's latest run. The resolver enforces what that selected record
can settle: provenance, result, evidence window and later changes. An always-consistent fake model
can test those guards and the agent-account boundary, but cannot establish whether an arbitrary
check covers a whole requested outcome. A fresh recorded DEC-17 qualification must include
premarked cases where a passing check does not cover the requested feature or browser behavior to
measure that semantic failure class; its general coverage floor alone does not require them. That
qualification was to keep the Claude Code producer gate closed until it passed; the owner's acceptance of
2026-10-02 opened it without one ([the amendment](#amended-2026-10-02-claude-code-is-accepted)).

Writing these lists out is part of item 3, which names the kinds (test, build, lint and type-check
runners) and leaves the list to this section. Each segment, split on `&&`, `||`, `;`, `|`, `&` and newlines, is matched
after stripping `cd ...`, `NAME=value` assignments and the wrappers `uv run`, `poetry run`,
`pipenv run`, `npx`, `pnpm exec`, `bunx`, `timeout N`, `time`, `rtk` and `env NAME=value`. The list is closed: a runner not
named here is not a check. The owner ruled `rtk` a wrapper on 2026-09-24, with one rule of its own:
because rtk may rewrite a runner's output, a check it wraps takes its result from the error flag
only, never from a summary line or a failure marker. `env`, named by its path or not, strips only
assignments, `-i`, `--ignore-environment`, `-`, `-u NAME`, `-uNAME`, `--unset NAME`,
`--unset=NAME` and `--`; `env -S`, `env -C` and every other option leave it unread.

The shell wrappers are `bash -c`, `sh -c`, `zsh -c` and `bash -lc`: the command string is parsed
again, and its segments stand in for the wrapper's segment. They were added on 2026-09-25; the
amendment below says how they are read.

Runners, matched on the first word or words of a stripped segment:

- Test: `pytest`, `py.test`, `python -m pytest`, `python3 -m pytest`, `python -m unittest`,
  `python3 -m unittest`, `nose2`, `tox`, `nox`, `node --test`, `npm test`, `npm run test`,
  `pnpm test`, `pnpm run test`, `yarn test`, `bun test`, `deno test`, `jest`, `vitest`, `mocha`,
  `go test`, `cargo test`, `cargo nextest`, `mvn test`, `gradle test`, `./gradlew test`,
  `gradle check`, `./gradlew check`, `storybook test`, `test-storybook`, `pnpm test:stories`,
  `yarn test:stories`, `npm run test:stories`, `pnpm run test:stories`, `yarn run test:stories`,
  `dotnet test`, `rspec`, `bundle exec rspec`, `rake test`, `phpunit`, `swift test`, `ctest`,
  `make test`, `make check`, and a program file whose name holds `test` or `tests` as a word of its
  own, with the name split on `_`, `-` and `.`: `run_tests.py`, `./test.sh` and
  `python3 scripts/run_tests.py` count, and `runtests.py` and `fetch_latest_creds.py` do not. Never
  the shell's `test` or `[` builtins.
- Build: `npm run build`, `pnpm build`, `pnpm run build`, `yarn build`, `bun run build`,
  `cargo build`, `go build`, `make build`, `mvn package`, `gradle build`, `./gradlew build`,
  `dotnet build`, `swift build`, `vite build`, and `tsc` without `--noEmit`.
- Lint: `ruff check`, `ruff format --check`, `flake8`, `pylint`, `black --check`, `eslint`,
  `biome check`, `biome ci`, `prettier --check`, `stylelint`, `golangci-lint`, `cargo clippy`,
  `rubocop`, `shellcheck`.
- Type-check: `mypy`, `pyright`, `tsc --noEmit`, `cargo check`, `go vet`.

Read-only commands, matched the same way, for segments that are not checks: `git status`,
`git log`, `git diff`, `git show`, `git rev-parse`, `git merge-base`, `ls`, `cat`, `head`, `tail`,
`grep`, `rg`, `find`, `wc`, `pwd`, `echo`, `which`, `file`, `stat`, `tree` and `less`; the portable
`date` display forms (no arguments or one `+format`, optionally with `-u`, `--utc` or `--universal`);
and REST `gh api` with one endpoint, no field, body, header or cache flags, and no method or an
explicit `GET`. Its accepted options are `--paginate`, `--slurp`, `--silent`, `--include`, `-i`,
`--verbose`, `--allow-escape-sequences`, `--jq`, `-q`, `--template`, `-t` and `--hostname`, plus
`--method` or `-X` for `GET`. Unknown options and the `graphql` endpoint stay changes. This is a
closed set: numeric clock-setting operands and GNU `date --set` stay changes, and BSD date parsing
forms are left unread. GitHub CLI fields imply `POST` unless a method overrides them, but field
forms remain outside this set even with explicit `GET`.
The [2026-10-27 amendment](#amended-2026-10-27-owner-ci-polling-commands-are-read-only) adds the CI polling commands
and the loop keywords around them.
Any other segment that is not a check, run after
any check's latest passing run, is the blocker item 3 names. This list is closed too. A segment is
not read-only, whatever its command, when it holds a command or process substitution whose own
command is not read-only by these same rules, a redirect `>` into anything but `/dev/null` or
another descriptor, or a writing option: `find -delete`, `-exec`, `-execdir`, `-ok`, `-fprint`, `-fprint0`, `-fprintf` or
`-fls`, `tree -o`, and `git diff`, `git log` or `git show` with `--output`.

Formatters and fixers are changes: `prettier --write`, `black` without `--check`, `ruff format`
without `--check`, and any run with `--fix` or `--write`, `ruff check --fix` and `eslint --fix`
among them. A change ages every earlier pass as a recorded write does, and a check that fixes, or a
fixer later in the same call, ages that check's own pass, so no timestamp tie inside one call hides
it.

The error flag, source (i), is the status of the whole call, not of one segment. The orchestrator
clarified how it is attributed on 2026-09-24, in the withholding direction, after review found a
failure credited to a check that never ran and a pass credited to one whose execution was unknown:

- a passing flag with only `&&` joiners in the call passes every check in it, because a chain of
  `&&` that exits zero ran every stage and each exited zero;
- a passing flag otherwise speaks only for a check that is the last segment of the call;
- a failing flag is attributed only to a check that is the last segment of the call, and every
  other check in that call reads "ran, result not recorded";
- summary lines and failure markers attribute only when the call holds exactly one check;
- anything after `||` has unestablished execution, so the flag says nothing about it and it reads
  "ran, result not recorded";
- `&` sends the whole `&&`/`||` list before it to the background, back to the previous `;`,
  newline or `&`, so `pytest && echo started &` runs pytest in the background.

The orchestrator clarified the attribution further on 2026-09-24, in the withholding direction,
after a verifier reproduced false results against the first clarification:

- a result Claude Code records as moved to the background ("Command running in background with
  ID", or "Command did not complete within its N s timeout and was moved to the background") makes
  every check in that call a background run: no result, and it supersedes as unrecorded;
- a failing flag is a run that exited nonzero only when the result opens `Exit code N` with N above
  zero; any other failing result is a call that never ran (a rejection, a cancelled parallel call, a
  sibling error, a hook block or an input error), so it is no run, is not listed and supersedes
  nothing;
- a failing flag is attributed only when the call holds exactly one segment after stripping `cd`,
  assignments and wrappers; otherwise every check in it reads "ran, result not recorded";
- summary lines and failure markers attribute only when the call holds exactly one check,
  background ones counted, and no other segment that is not read-only;
- beside a passing flag, only a failure summary line makes the check failed; a failure marker alone
  makes it "ran, result not recorded";
- an `rtk` check with a passing flag and failure text in its output reads "ran, result not
  recorded", never passed.

DRC-4890 names the rule on the published entry. A check whose result an attribution rule withholds
carries `result_reason`: `several_checks` when the call holds more than one check,
`directory_not_placeable` when a `cd` before it names a directory the shell places at run time, and
`piped_beside_other_commands` when a pipe sits in a call whose other segments print, or
`printed_beside_other_commands` for any other call where a command beside the check may print (added
by [the 2026-10-27 DEC-29 amendment](#amended-2026-10-27-owner-a-checks-own-summary-on-the-last-line-records-its-result),
which also reads the last line past such commands). The token is set
only when lifting that rule would publish a result, so a check the flag or the output's own wording
already leaves unrecorded carries none. The page words each token in its reason table, and
`frontend/test/fixtures/vocabulary.json` pins the two together.

DRC-4733 tightens the output attribution rule on 2026-09-29. Read-only means a command does not
record a change; it does not mean the command's output came from a check. Summary lines, failure
markers and Pi's check counts attribute only to a single check with no independent output-producing
segment. A following `head` or `tail` with a numeric line or byte limit, or `grep` with its pattern,
may preserve that attribution when connected only by pipes and reading only stdin. File operands,
an input redirect, another print before or after the check, and a preceding `cd` that can print its
destination withhold it. `pytest || echo '5 passed'` and `pytest; echo '5 passed'` therefore read
"ran, result not recorded". A trustworthy passing `&&` flag still establishes a pass, but an
independent print never supplies its count. The read-only list and write-ageing rules are unchanged.

Summary lines, source (ii), read from the recorded output tail, may record a pass or a failure:
pytest's `N passed`, `N failed` and `N error` or `N errors`; unittest's `OK`, only as the whole line (it may carry its own counts, such as `OK (skipped=N)`), and `FAILED (`; jest's
and vitest's `Tests:` line with its passed and failed counts; node's `ℹ pass N` and `ℹ fail N`
lines, where `ℹ fail 0` is a pass; cargo's `test result: ok` and `test result: FAILED`; mypy's
`Success: no issues found` and `Found N errors`; ruff's `All checks passed!` and `Found N errors`.
A pass needs a pass pattern and nothing in the same tail that records a failure: a failed count
above zero, a failure summary or a failure marker. So `1 failed, 9 passed` is a failure. go prints
`ok  <pkg>` once per package, so a later package's `ok` cannot vouch for the run, and it is never
read as a pass. go's `FAIL` is a failure, and a go pass comes from the error flag alone. ruff's
`Found N error (N fixed, 0 remaining)` after a fix is not a failure summary, and neither is
eslint's `(0 errors, N warnings)`. A pass whose count
is zero (`ℹ pass 0`, `0 passed`, `Ran 0 tests`), or a go run reporting `[no tests to run]`, or
`[no test files]` with no package reporting `ok`, reads "ran, result not recorded". Failure evidence
outranks a passing flag: when the flag passes and the tail holds a failure summary, the check
failed, since a script can swallow its runner's exit status; a failure marker alone withholds the
pass instead.

Failure markers, source (iii), read from the recorded output tail as evidence of failure only:
node's `✖` test lines, `failing tests:` and `ℹ cancelled N` above zero (a timed-out test prints
`ℹ fail 0` beside it and exits 1), `AssertionError`, `ERR_ASSERTION`, pytest's `FAILED ` and `ERROR `,
go's `--- FAIL:`, cargo's `panicked at`, and tsc's `error TS`. tsc prints nothing on success, so
its pass comes only from the error flag.

The owner settled these points on review the same day, as part of the ruling rather than as an
amendment: a program file counts only when `test` or `tests` stands alone as a word in its name; a
summary-line pass counts only when nothing in the same tail records a failure, a go pass comes only
from the error flag, and unittest's `OK` counts only as the whole line (it may carry its own counts, such as `OK (skipped=N)`); and the read-only list above.
The orchestrator added, on review the same day and in the withholding direction: the error-flag
attribution above, failure evidence outranking a passing flag, node's `ℹ cancelled N`, and go's
`[no test files]`. The owner added `rtk` as a wrapper whose checks read the flag alone.

#### Amended 2026-10-01: a line about what the agent tells you cannot be shown

Narrowed by
[DEC-17's amendment of 2026-10-03](#amended-2026-10-03-owner-the-agents-own-words-are-evidence):
the agent's messages are now in the record, so such a line stands where one of them is among what
it rests on, and is withdrawn as below where none is.

Owner ruling, DRC-4742. Three scored Claude Code qualification runs have failed DEC-17's check, and
the third had one false reassurance. The reader had asked the agent to run `node --test
tests/game.test.js` once more, unpiped, and report the counts. The outcome line said the check "is
run once, unpiped, and its counts are reported", and the reading called it `consistent`, citing
the passing run. The key says abstain. A record can show that a check ran and what it returned. It
cannot show what the agent then told the reader, and the agent's own account carries no outcome
verdict under [rule 7](#amended-2026-09-10-rule-7-asks-whether-an-entry-shows-work-not-who-typed-it).
The producer instruction from #450 already told the model that a passing suite cannot prove a run
count or piping it did not exercise, and that test counts are not the agent's report to the person.
The model gave the same verdict anyway.

The owner chose a server-side rule over more prompt wording. When an outcome line's own text says
the agent reports, tells, explains, summarises, says, describes or mentions something, or lets the
reader know, the resolver withdraws a `consistent` on that line to not verifiable. The stored
reason is `tells-the-person`, and the page says the line is about what the session told you, which
nothing in the record can show. The existing `check-does-not-show-it` sentence was not reused,
because it says the check's latest run did not pass with no change after it, and here it did.

Matching is on whole words and ignores case, and it reads the whole line rather than the
240-character clause stored on the row, so a telling word past that cap still counts. "Report"
matches as a noun as well as a verb, and "reporter", "reportage" and "sayings" do not match. The
one other exclusion is a word followed directly by `.` or `/` and then a letter, digit or
underscore, such as `report.csv` or `reports/summary.md`. Nothing else about paths or tools is
read, so "src/report", "~/report", "report-card.js", "npm run report", "the CLI reports 0 failures"
and "describe blocks pass" all abstain. That over-abstains on purpose: the ruling accepts it, and
telling the agent's account apart from a tool's would mean parsing the line's grammar.

The rule only ever moves a verdict toward abstaining. A departure on such a line stands, the Goal
is never touched, and a line that already rests only on the agent's account keeps rule 7's
`no-work-shown`. It runs in `reading._evidence_rules`, which every reading goes through, the
unasked lane included. The drift level that `levels.analysis_level` derives from a stored reading
runs the same resolver over each line's text, so a `consistent` stored before this rule existed
does not count as shown there either.

This knowingly narrows the coverage ruling above (DRC-4749), which left relevance to the model.
For this one class of line the server decides, because a passing check cannot speak to it whatever
the model concludes. More prompt wording was the alternative, and it was rejected because #450 had
already tried it and the next scored run produced this failure.

### What was measured before the text was fixed

On this repository's own transcripts, measured 2026-09-24, 775 of 848 test and lint runs were piped
and 1 set `pipefail`. That is why the error flag counts only when the runner is the final stage. A
list that matched only a command's leading form found 14 of 941 real check invocations, which is
why a check is matched per segment after stripping.

Five recorded Claude Code sessions the same day (Haiku 4.5; the session ids are on DRC-4673)
changed the ruling twice. Node's test runner prints its summary in its own form, so that form joined
the summary set. And a failing `node --test 2>&1 | tail -20` was recorded with the error flag
false. Node prints its failure details after its summary, so `tail` cut the summary line out, and
the last 180 characters held only the assertion object (`code: 'ERR_ASSERTION'`, `actual`,
`expected`). Under the flag and the summary line alone that run reads "ran, result not recorded",
never a failure; unpiped, the same failure sets the flag. The failure markers were added for it, and
because a marker can only record a failure, it cannot produce a false pass.

The same sessions confirmed item 1. A background launch records only a "will notify" result, and its
output is read later through a file Read, so it is never a recorded result. The field names these
readings rely on are in
[the transcript capture](captures/claude/transcript-tool-shapes-2.1.281-macos.jsonl). It also shows
the limit on writes: a shell command's result records its command and output and no path, so a
written path comes only from a file-write tool call, and a file a shell command changes is not a
recorded write. A check's own redirect into a file is the one exception since 2026-09-27; see
[the amendment of that date](#amended-2026-09-27-a-subshell-a-checks-own-redirect-a-write-at-the-same-time-and-when-a-result-arrived).

### Amended 2026-09-24: the live estimate reads these facts on the machine

[DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn) amends items 6 and 7. The
drift level is a derived state of the tool-outcome facts. It is published on the session payload
only, never on a row, in history or in an off-machine payload, and item 6's rule that nothing enters
a row field or the semantic history store holds for the level as it does for the facts.

### Amended 2026-09-25: one parser reads the line, shell wrappers, and unbalanced quoting

The owner ruled on DRC-4703 after the check line was found to leak on odd quoting, and a
four-lens review on 2026-09-27 tightened the parser; its changes are folded into the items below. A regex tokenizer,
a line-based heredoc strip and `shlex` read each line, and when `shlex` failed on an unterminated
quote the fallback split the value on spaces and masked only its first word. Over 8 masked forms,
9 quoting styles and 3 positions, 114 of 216 cases published at least half of a two-word placeholder secret, and the
check line is also the prompt row, so each leak reached the model. This amends item 3's stripping,
item 5's fields and the closed lists.

1. One parser. `project_context._ShellLexer` reads the call once, the way the shell does, into
   segments of decoded words: the words the program receives. It reads single and double quotes,
   `$'…'` with bash's escapes decoded, `$"…"` as a double-quoted string, a backslash-newline as
   nothing, `$(…)`, backticks and process substitutions to their matching end, and a comment at a
   word start. A `${…}` expansion is read whole, so a quoted `}` or a `)` inside it closes nothing,
   and inside a substitution a `case` pattern's `)` closes nothing either. `$((…))` and a `((…))`
   command are arithmetic, so `<<` in them is a shift. A redirection (`>out`, `2>&1`, `&>`, `<in`, `{fd}>`,
   `<<<`, a heredoc operator) ends the word before it and is kept apart from the words, because the
   shell strips it before the program receives its arguments: `--password 2>&1 value` reaches the
   program as a flag and its value side by side. A heredoc is recognised only as an unquoted `<<` or
   `<<-`, its delimiter is any word, quote-removed, and each body is read in order after the line
   ends. Quoting any part of the delimiter makes the body literal. In an unquoted body, command
   substitutions execute even between literal quote marks; backslash quotes `$`, backtick and
   backslash, and a backslash-newline joins only when the backslash was not itself escaped. Joining
   precedes delimiter matching, so a continued body line cannot expose later literal commands.
   Only those substitutions are read for their effects, never literal body lines, and no body text is
   published. The nesting bound still applies through a body inside a substitution.
   A body without its closing line runs to the end of the call, as bash reads it. Before this,
   a quoted `<<END` hid every line after it and a delimiter such as `MY-EOF` was not recognised, so
   its body was read as commands.
2. Unbalanced quoting means the call did not run. An unterminated `'`, `"`, `$'`, `$(`, `${` or
   backtick, and a heredoc operator or redirection with no word after it, is a syntax error in every
   shell. The call is not listed, it is counted in `not_run`, and nothing from its text is published.
   It still counts as a change, because bash runs the complete lines before it, so an earlier pass
   ages. A raw NUL in the command, nesting deeper than 32 substitutions or expansions, and any other
   fault in the parser are read the same way. A shell wrapper whose command string is unbalanced is
   different: the inner shell fails and the rest of the call runs, so only that wrapper segment is
   unread, and it is a change. A trailing lone backslash is not unbalanced: measured, bash runs the
   line and passes no argument for it.
3. `bash -c`, `sh -c`, `zsh -c` and `bash -lc` are runner wrappers. A shell
   named by its path counts. The option set is closed: single-letter clusters over `e`, `u`, `l` and
   `c`, `-o pipefail`, `--login`, `--noprofile` and `--norc`, with `-c` the last option and
   exactly one command word after it. Words after that are `$0` and the positional arguments, and
   are neither matched as runners nor published. Their named values still enter private masking
   and written-path withholding. The command word is parsed again and its segments are spliced
   in place of the wrapper's: the last inner segment takes the wrapper's joiner, so every attribution
   rule applies unchanged and only withholds. A wrapper sent to the background sends every inner
   segment with it, a background launch inside one is counted, a redirection on the wrapper applies
   to every inner segment, and a `cd` inside a wrapper does not carry past it. `-x` is left out,
   because xtrace echoes every word, a masked value included, into the output the prompt row
   carries. Only the inner segment is
   published, and a check's identity is its directory and inner segment, so `bash -c 'pytest'` and
   `pytest` in one directory are one check. Nesting stops at two wrappers; a third, or any other
   option, leaves the segment unread: not a check, and a change.
4. `env NAME=value cmd` is a wrapper, stripping the options the closed lists name. `env -S`
   re-splits a string and `env -C` changes directory, so neither is a wrapper, and neither is any
   other `env` option.
5. Masking reads decoded words. Because the parser decodes quoting first, one word holds a whole
   quoted value, and every named form masks it whole however it was quoted. The password in
   `user:password@` is masked up to the last `@` in the word, whitespace included. A NUL decoded
   from `$'…'` ends that string, as it ends the argument the program receives. An unquoted word
   holding a brace expansion (`{a,b}`, `{x..y}`) is published as `…`, since the words it becomes are
   unknown, and so is the word after it, since `--{x,password} value` expands to a named flag and
   its value. Each named value masked anywhere in the call, assignments, wrapper arguments and
   executed substitutions included, and each piece of it of four characters or more, is also
   removed from the output tail
   before redaction and clipping. Literal and shell re-quoted spellings, including xtrace's split
   apostrophe, match at filename and identifier boundaries, so masking `test` leaves `test_a.py`,
   `contest` and `src/test` readable. A wrapper's script is read as its inner words rather than as
   one assignment value; its ordinary runner and summary words are not masked. The named forms
   are unchanged: these forms and no others, except as amended in the
   [2026-10-27 amendment](#amended-2026-10-27-owner-more-shapes-and-forms-are-masked-and-a-stored-explanation-is-scrubbed).
   Short pieces and arbitrary encodings remain outside this scrub.
6. A redirection is not an argument and is not published: not its target, not a here-string's
   word, not a heredoc's delimiter. A heredoc body and a here-string word are stdin data. Amended
   2026-09-27: a check segment's redirect target inside the working directory is published as a
   written path, below. The operator and decoded target stay separate: `> '&1'` writes a file
   named `&1`, whereas `>&1` duplicates a descriptor and `>&-` closes one. A named descriptor
   redirect into `/dev/null` remains harmless. An input redirect on a pipeline filter, heredocs
   included, cannot credit that input's summary to the check upstream.
7. A substitution runs whatever it names. A command or process substitution anywhere in a call, in
   a check's own arguments, an assignment, a redirection target or a wrapper's other words, counts
   as a change unless its own command is read-only by the closed lists, read with these same rules.
   A segment that is only a redirection into a file (`> build/output`) writes that file, so it is a
   change too.
   `$((…))` is arithmetic and runs nothing unless it holds a substitution. Nested executable
   commands supply private named values without reading arithmetic literal text as shell commands;
   arithmetic holding a substitution keeps its unknown, changing classification. Single quote
   characters there, including the `$'…'` spelling, do not suppress nested command execution; a
   command can emit its named value before the expanded expression errors. A file redirect
   inside an executable body is checked before the empty-word and `cd` shortcuts, so neither can
   hide a write. This also settles
   DRC-4724's second acceptance criterion.

No published field was added or removed. Titles change for a wrapper and for values that are now
masked whole, and the scan counts move with the segmentation. Measured on this machine's
transcripts (counts only, 2026-09-25 and 2026-09-27): a line continuation had added a false change
after the check in 237 of 429 check calls that used one, and it adds none now. Those calls fall to
142 holding a check, because the old reading made each continued line its own segment, so a test file
named on one was read as a check. Of 315 shell `-c` calls, 6 are now read as checks, against 2
before, and 21 calls are now not run for unbalanced quoting. After the change the same matrix, with
the wrappers added, leaks in none of its 1,944 cases.

The review round's own figures, measured 2026-09-27 on the same transcripts (counts only): 18 more
calls are read as not run, 17 of them holding a raw NUL and 1 that both `bash -n` and `zsh -n`
reject. 700 calls stopped reading as a change, 489 of them because a `>` inside quotes is an
argument and not a redirection, and most of the rest because their substitution runs only
read-only commands; `shlex` finds a file write in 1 of the 700, the check's own redirect, which
DRC-4709 owns. 319 calls became a change, nearly all an assignment whose substitution runs
something. The matrix, with newline quotings and an unterminated `$'` added, leaks in none of its
2,592 cases.

### Amended 2026-09-27: a subshell, a check's own redirect, a write at the same time, and when a result arrived

The owner ruled on DRC-4702, DRC-4709 and DRC-4724 on 2026-09-27. This amends item 3 of the
2026-09-25 amendment (a subshell is read as a wrapper is), its item 6 (a check's redirect target),
and item 3's measured note that a written path comes only from a file-write tool call.

1. A `(` at command position opens a subshell, and its matching `)` restores the directory that was
   current at the `(`, as a shell wrapper already did. `(cd sub && pytest); pytest` runs its second
   check in the working directory, so a failure in `sub` is no longer superseded by a pass outside
   it. A `)` that matches no `(`, such as a `case` arm's, and the parentheses of `f()` or
   `a=(1 2)`, open and close nothing. No published byte changed; only a check's identity moved.
   Measured on this machine's transcripts (counts only): 7 of 9,703 check calls change directory,
   and none gains or loses a check. DRC-4727, DRC-4728 and DRC-4730 amend placement on 2026-09-29: unquoted
   braces and `then` put their commands in the current shell, so a brace group's `cd` persists
   after `}`. Conditional arms and the commands after an `if` or `case` leave relative placement
   unknown when the recorded call cannot establish which branch ran. A `case` pattern's `)` closes
   no enclosing subshell, and `time ( ... )` opens one. A `cd` in a pipeline or background list does
   not move the foreground shell. A nonempty explicit `CDPATH` makes a relative destination unknown;
   a literal absolute `cd` or the enclosing subshell's close restores placement. A `cd` after `do`
   is still outside the supported placement forms. When Claude's recorded cwd can no longer place
   a check, its private identity is specific to that call and segment. It cannot supersede a known
   check or another unplaced run. Checks in a known directory still share their existing identity;
   no guessed folder is published.
2. A file redirect on a check segment is a recorded write by its call, its target read from the
   directory that segment ran in. A target inside the session's working directory is published as a written
   path, as a file-write tool's path is, through the same redaction. A target outside it, or one the
   shell decides when it runs (a `$` expansion, a substitution, `~`, a withheld word), is counted in
   `outside_paths` and never published. So is a target that masking would change, or that holds
   any value masked anywhere in the call, assignments included, since the check row beside it
   shows that value masked. A `cd` the shell resolves at run time (`~`, `$VAR`, a substitution,
   no argument, `-`), and `pushd` or `popd`, leave the directory unknown until a literal absolute
   `cd` or the group's close places it again, and a relative target under an unknown directory
   counts outside. `-L`, `-P`, `-e`, `-@` and `--` are options to `cd`, not directories. A group's
   or a wrapper's own redirect (`(cd sub && pytest) > out`) is read from the directory the group
   started in, where the outer shell opens it. A redirect into `/dev/null`, `/dev/stdout`,
   `/dev/stderr`, `/dev/tty` or `/dev/fd/N`, by any operator, writes no file. The redirect does
   not age its own check's pass. It ages an earlier check in the same call, setting both
   `before_last_change` and `changed_after`, and any pass from an earlier call, and it does not
   set `last_changing_command_at`, because it is now a recorded write. Measured (counts only): 90
   redirect targets on check segments, every one counted outside. The analysis had counted 9 inside,
   and all 9 were `$VAR` targets, whose path the shell picks at run time.
3. A write or fixer run from another call, recorded at the same time as a pass, ages it, since the
   recorded times cannot say which came first. The pass's own call is still ordered by its segments,
   so `black . && pytest` keeps its pass current: a tie rule without that exclusion aged 11 of the
   747 fixer-before-check calls measured. No check call shared a time with a file write.
4. Each recorded foreground check run publishes `result_at`, the time of the record holding its
   result. A background run, or one with no result yet, has none. `at` stays the call time, so the
   fact id, the page's order and its numbers do not move when a result lands. The result time
   decides the evidence window and which run of a check is latest. Every change comparison
   (`before_last_change`, `changed_after`, the live floor's changing-command time) keeps the call
   time, because in 291 of 9,544 measured checks a changing command started while the check ran,
   and a result time would read it as before the pass. `reading.evidence_at` is the one helper, the
   page's `nextReadingEvidenceAt` is its copy, and a test runs both window rules over one table.
   With two parallel runs of one check, the published run can swap when the earlier call's result
   lands after the later call's, which moves the fact id. A stored citation of the old id then
   reads uncited, which errs safe.

DRC-4709's third item, a subagent's writes, landed with DRC-4687 in
[the amendment of 2026-09-28](#amended-2026-09-28-a-subagents-checks-and-writes-are-the-parents).

### Amended 2026-09-28: a subagent's checks and writes are the parent's

The owner ruled on DRC-4687 and on DRC-4709's subagent item together on 2026-09-28: count both
ways. A subagent's checks count for the parent session, labelled as the subagent's, and its writes
count against the parent's earlier passes. Landing only the writes would have marked down exactly
the sessions that delegated their tests, since their subagent's edits would age a pass while its
checks went uncredited. This amends item 3's "a shell command", item 4's "each distinct check" and
the measured note that DEC-23 reads the root session's calls alone.

1. A subagent is a transcript Claude Code writes beside its parent, under the parent's session
   directory: `subagents/agent-<id>.jsonl` for a Task or Agent call, and
   `subagents/workflows/<run>/agent-<id>.jsonl` for a workflow's agents. Every record in it is a
   sidechain carrying the parent's `sessionId`, and the parent's Agent result names the id
   ([the capture](captures/claude/subagent-transcript-shapes-2.1.281-macos.jsonl)). A file named
   `agent-<kind>-<id>` is a forked context, not a subagent: compaction, an aside question and a
   prompt suggestion replay the parent's context under the parent's own call ids, so reading them
   would count the parent's calls twice. A sidechain record inside the parent's own file is not read.
   A teammate of an agent team, which writes its own top-level transcript, and the older layout's
   `agent-*.jsonl` beside the project's sessions, are not read here; their checks count toward no
   session yet.
2. A subagent's checks count for the parent, read by the same parser and the same rules. A
   check's identity is still its directory and its segment, whoever ran it, so a check the parent
   and a subagent both ran is one check: its latest run counts, chosen by result time, and
   `earlier_failed` spans both. A failing subagent check is a failing check of the session, and a
   subagent's pass supports what a parent's would.
3. A subagent's entry is labelled in the record. The event and its published fact carry
   `worker_kind: "subagent"`, a key the fact already allows, on a check whose latest run was a
   subagent's and on a path a subagent wrote last. The parent's own entries carry none. The page
   renders no word for the key itself, so the evidence source line names the worker instead:
   "Claude subagent Bash call and paired result", "Claude subagent Edit call", and so on. The owner
   chose that wording on 2026-09-28 because the page already shows the source line and it needs no
   web change.
4. A subagent's writes count against the parent's earlier passes, with the same fields: a
   file-write tool's path, a check's own redirect, a fixer, and every changing shell command set
   `before_last_change`, `changed_after` and `last_changing_command_at` exactly as the parent's
   do. A parent write after a subagent's pass ages it the same way, and one subagent's write ages
   another's pass. A subagent working in another checkout still ages the parent's passes, as a write
   outside the working directory always has, and its written paths are relative to its own working
   directory. Amended 2026-10-14: the last clause no longer holds, see below.
5. One order across all of them. Each transcript keeps its own order, and the transcripts are
   merged by call time, the parent's first at a tie. The result time decides which run of a check
   is latest, across parent and subagent alike, as item 4 of the 2026-09-27 amendment set it; every
   change comparison keeps the call time, for the reason that amendment measured. A subagent run
   in the background beside its parent is ordered by its own records' times.
6. An Agent call is not itself a change. DRC-4709 named "an Agent call after a pass" because a
   subagent's work was unread; it is read now. The exposure left is a subagent whose transcript is
   not on this machine, whose writes Compass cannot see.
7. The bound, amended 2026-09-30. One check-evidence scan spends at most
   `turn_scan_max_bytes` (normally 8 MiB) on the parent and all admitted children together. It
   charges actual binary bytes returned, including invalid records, discarded partial lines and a
   frozen cutoff search. A smaller explicit override, including zero, is honored. The parent reads
   first. Live children follow newest modification time, then stable session-relative path. A
   frozen moment reads children by stable session-relative path, replacing the earlier
   last-record-time ranking; today's mtime cannot reorder historical evidence. It searches each
   transcript forward to the first stamped record after the moment or the held file's end, using
   the same allowance and never rereading a discovered prefix. If the parent's cutoff is beyond
   that allowance, the frozen check read refuses. A child whose cutoff cannot be reached is unread.
   No historical packet is rewritten and no persisted scan manifest is needed for this rule.

   `subagent_transcripts_unread` counts admitted children with no readable work and valid plain
   hex IDs named by paired parent Agent or legacy Task results whose child work is unavailable.
   Repeated IDs count once, and a discovered unread file is not counted twice. A numeric
   `reads_from` horizon still marks passes older than a partial window or unread child's possible
   work. If a clipped live parent keeps a valid Agent result but loses its earlier call, that
   result does not increase the named-child count. Until its child can be read completely, it
   still makes held passes incomplete; the missing call cannot certify that delegated work was
   absent. Any valid named child that remains unavailable marks every held passing check
   `read_incomplete`, even if the parent passed later. A failed check that was actually read keeps
   its failure and High level. An incomplete pass cannot support a consistent outcome or the live
   "None or low" floor; incompleteness alone is not a departure. Collection, press and frozen check
   scans each get their own allowance. Activity, identity and user-message reads are separate, so
   this is not a bound on the entire frozen admission or validation operation.
8. Where it goes is unchanged. A subagent's checks are the parent session's record, so items 6, 7,
   9 and 10 apply to them as written, and a press carries a subagent check's tail only under the
   tool-output grant the parent's needs.

Measured on this machine on 2026-09-28, counts only: 9,443 agent files under 594 sessions'
`subagents` directories, 9,119 of them plain subagents, 234 compactions, 74 prompt suggestions
and 16 aside questions. Of the forked contexts that held a call, 15 of 16 aside questions and 21 of
39 compactions replayed the parent's own call ids; 245 of 245 sampled subagents shared none with
their parent, and 60 sampled sessions' subagents shared none with each other. In 150 sampled
sessions, all 1,107 agent ids an Agent result named had a transcript. 3,000 agent files, forks
included, held 41,205 Bash, 11,944 Edit and 2,903 Write calls. The largest session held 389
subagent transcripts totalling 405 MB, and the 95th percentile 69 and 23 MB.

### Amended 2026-10-04: no recorded result is listed last

The owner delegated this change on 2026-10-04, through an adversarial review of what the
[second drift replay run](drift-replay/README.md#the-second-run-2026-10-04) suggested changing.
Item 4 listed latest runs that failed, then runs with no recorded result, then runs that passed,
then written paths. Across that run's 99 cuts the scan held 85 passing checks, at least one on 54
cuts, and 418 written paths, and the listing carried no pass and 22 writes: the runs with no
recorded result filled the 12 entries first. Such a run carries no verdict (`check_supports`), so
it was the least informative entry and it crowded out every pass. The page then showed a claim as
"not shown by the record" beside a scan sentence saying "1 passed".

The order is now failed, then passed, then written paths, then no recorded result, newest first
within each. On the same 99 cuts the listing now carries 70 of the 85 passes, on 51 cuts, and 291
writes; the other passes sit behind failures or newer passes, and 76 cuts list something different
from what the second run's readings were given. Failures still come first, so item 4's purpose holds: a pass is never
chosen over a failure. A check whose latest run has no recorded result but whose earlier run
failed is ranked with the failures, because that failure is the only result it recorded: ranked
last, twelve writes would push it out and leave the prompt with no failure at all (found on review
the same day). The reading's own byte bound keeps the same order after the reader's messages, so a run
with no recorded result never takes a pass's or a write's place in the prompt either. Everything
else in item 4 stands: every answer about checks still comes from the full scan.

### Amended 2026-10-14: the reader who runs the dashboard may grant tool output at launch

Item 7 admits tool output only under a grant for a named destination, written by an Allow whose
disclosure named it. That stands. The amendment adds a second writer of the same row: the person who
starts the dashboard may pass `--allow-tool-output`, or set `COMPASS_ALLOW_TOOL_OUTPUT=1`, and after
the bind Compass writes the grant for each provider whose destination it can name
(`reading_policy.grant_tool_output`). It writes no words Allow, so no reading runs on it alone, and
the disclosure says tool output was allowed when the dashboard started instead of "only after you
allow it". When the permission store cannot take the write, the start
prints one line and drops the flag for the run, so the card asks as usual. The server was safe
either way, since a press without the row is refused `403 tool-output-consent-required`; the page
was the part that overstated, and it was reading the flag where it should have read the outcome.
The wording still follows the flag afterwards: Pause model calls and `--forget` delete the row while
the flag stays set until a restart, so the card can keep saying it after a withdrawal.
`--no-observer-model` refuses it, "Turn off readings" (renamed Pause model calls on 2026-10-19) and `--forget` clear it, and the Windows
respawn forwards it.

Why a launch flag. A reader who found on a first walk that most lines read "Can't tell" had tool
output already granted: one press of "Allow and analyze" writes both. A default needs a reader who
chose it, and launching the dashboard with the flag is that choice, made once by the person who owns
the machine, for the destination Compass names on that machine.

Rejected, each because it sends the checks and written paths of a session to a vendor without the
reader having accepted a disclosure that names them:

- Upgrading a words-only Allow to cover tool output. An Allow given before tool output was named
  would widen after the fact, which item 7 forbids ("an answer saved before tool output was named
  never covers tool output").
- Granting from the first run with no card. The first press would send command lines, output tails
  and written paths with nothing accepted.

The row outlives the flag, as an Allow's does: starting again without it does not withdraw the grant.
A grant that should end with the run would need a store entry that records how it was written, which
was not built.

### Amended 2026-10-14: a written path is read from the session's directory

Item 5 says a written path is relative to the working directory, and item 4 of the 2026-09-28
amendment said a subagent's was relative to its own. Both now read from the session's directory.

What was wrong. Each path was read relative to the `cwd` of the record that carried it. A `cd`
moves the `cwd` of every later record, so a session that had changed folder published a bare
filename and "Where the work went" read "The working directory". The live folder signal saw the same
bare path, under no folder the intent names. Two subagents that each wrote `src/main.py` in their
own checkouts also published one path, so the count and a file row disappeared.

What stands. A relative path is still placed where the tool ran it, in that record's `cwd`. The
result is then read relative to the session's directory, so a write outside it is counted in
`outside_paths` and never published, as before. The session's directory is the first `cwd` at the
head of the parent transcript, because a clipped read of the tail can begin after a `cd`. Where the
head holds none, it is the first record read.

Consequence, stated plainly. A subagent in an isolation worktree under the session directory, for
example `.claude/worktrees/<name>/src/m.py`, now publishes with that prefix. The live estimate's
folder share counts it as outside a named folder such as `src`, since the path no longer starts with
`src`. That follows from keeping distinct checkouts distinct: two worktrees writing `src/m.py` are
two files. A checkout outside the session directory is counted and not published, as any write
outside it is. The share is not yet adjusted for worktrees; the 2026-10-21 ruling below decides how it will be.

### Amended 2026-10-21 (owner): a worktree checkout counts as its folder inside it

The question was whether a write in an isolation worktree under the session directory counts against
the session's named folders (a), counts against the same folder inside its checkout (b), or is weighed
separately (c). The owner chose (b).

What it means. The published path keeps its prefix: `.claude/worktrees/<name>/src/m.py` is still the
written path a reader sees under "Where the work went". Only the live folder share changes. Before
testing a path against a named folder, the leading `.claude/worktrees/<name>/` is removed, so that
write reads as `src/m.py` and counts inside `src`. A write in the same worktree to `web/m.py` still
counts outside `src`, because it is outside the folder in its checkout too.

Why (b). The subagent is doing the same work in the same folder, in its own copy of the tree. Counting
it outside `src` raised the live share for delegated work that stayed where the intent named, which is
the miscount this ruling corrects. Separate weighing (c) would add a state the live estimate and the
rules must read, for no change in what a reader can act on. Counting it as (a) keeps the published
prefix's error in the share.

What stands. A checkout outside the session directory is still counted in `outside_paths` and never
published. Two worktrees writing `src/m.py` are still two files; both count inside `src`, and the
share does not de-duplicate them. The ruling applies to the folder share only and to no other rule.
This record lands the ruling first. The code follows in a separate pull request: `levels.inside`
will own the prefix. Until then the two tests that check it, `TheWorktreeSubagentWriteTest` and
`test_a_worktree_checkout_write_is_read_inside_its_checkout`, are marked expected-to-fail, and the
live share still counts a worktree write to a named folder as outside it.

### Amended 2026-10-14 (owner): a write outside a named folder does not settle a line

Item 8 says absence supports neither a departure nor a consistent, and a recorded write is not a
check. The owner ruled on 2026-10-14 that a recorded write outside a folder the intent names does not
settle a scope line, and that a live Medium which rests on written paths alone does not offer Steer
back or Update intent instead. The folder signal stays what
[DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn) items 1 and 2 made it: an
input to the live level, shown with the entries it cites, and nothing more. The model analysis keeps
reading "Can't tell" on a line only a write could speak to, because on Claude Code a verdict on a
line rests on a check.

Found on a walk of 2026-10-14: a session whose goal named a folder wrote three files outside it. The
free live estimate read Medium and cited the write, and the analysis read "Can't tell" on both lines.
That pair is the intended behaviour, and the how-to now says which lines a reading can settle
([DEC-27's amendment](#amended-2026-10-14-what-the-how-to-the-live-line-and-a-late-save-say)).

Not done:

- A per-line verdict from recorded writes, so that a line naming a folder departs when files were
  written outside it.
- Steer back, or Update intent instead, for a Medium that rests on written paths alone.

Why. Item 8 already rules that the absence of a failing or passing check supports neither verdict,
and a write is evidence that a file changed, not that a line was met or missed. The folder signal has
measured false alarms from two sources, intent words read as folders and worktree sessions. A replay
of 99 recorded cuts found 18 folders the reader never named; dropping them took the no-drift sessions
that read High or Extreme from 29 to 19. The replay's findings are kept locally and are not
committed. Nineteen is not zero, which is enough for a level and not for a verdict a reader pastes
back into a session. And the Claude reader's accuracy check has not passed
([the DEC-21 amendment](#amended-2026-10-14-owner-the-page-says-the-claude-readers-accuracy-check-has-not-passed)),
so Compass does not add a second, weaker route to a correction. DEC-24 item 7's list of triggers
stays as it is: a surviving model departure, a contradicted or unshown claim, a failed check.

### Amended 2026-10-23 (owner): pnpm shorthand for a closed runner is a check

[The closed lists](#the-closed-lists) name `pnpm exec` as a wrapper and no other pnpm form. The owner
ruled on 2026-10-23 that `pnpm <runner>` counts as a check whenever `<runner>` is on the closed list,
the same as `pnpm exec <runner>`: `pnpm vitest run X`, `pnpm tsc --noEmit`, `pnpm eslint .`. A pnpm
word that is not a closed runner (`pnpm install`, `pnpm dev`, `pnpm playwright`) stays unread, and
`pnpm test` and `pnpm build` keep the pairs they already had. `poetry run` and `pipenv run` already
are the shorthand of their package managers, so no other manager gains a form.

Found on a real session whose agent proved a fix with `pnpm vitest run` on a regression test that
went red and then green; neither run was counted. The attribution rule is unchanged: a shorthand
call piped beside other `&&` segments still reads `piped_beside_other_commands`, and a lone one
piped only to an output filter reads its summary line as the `exec` form does.

### Amended 2026-10-23 (owner): PR and skill facts

Two things become evidence on Claude Code, each a closed fact kind added to [the closed lists](#the-closed-lists)
and neither read from shell text.

- **A pull request created.** The source is Claude Code's own structured record of creating it: the shell
  call's result carries `toolUseResult.gitOperation.pr` with `action: created`, and the same pull request is
  written again as a top-level `pr-link` record
  ([the capture](captures/claude/pr-and-skill-shapes-2.1.309-macos.jsonl), taken against a stub `gh` in a
  scratch repository). Compass reads the result alone, because the `pr-link` record repeats what the result
  holds and is written twice per pull request. A call that errored, an action other than `created`, and any URL
  that is not `https://github.com/<owner>/<repo>/pull/<number>` with a number matching the record publish
  nothing. The fact carries the repository, the number, the URL rebuilt from those parts, and the time the
  result was recorded (`pr_repository`, `pr_number`, `pr_url`, `at`). The command line and the output are not
  read: `gh pr create` is still not a check, and DEC-23 items 3 and 5 keep the rest of the command and its
  output out of every prompt. One pull request is one fact however many records name it.
- **A skill used.** The source is a `Skill` tool call whose result did not error, and only the skill's name is
  read, held to `[A-Za-z0-9][A-Za-z0-9_.:-]` up to 80 characters. The call's arguments are never read. One
  fact per name, at its first use.

Both are `tool_report` facts (subjects `pr` and `skill`), so they ride the existing admission: a reading is sent
them only under the tool-output grant for a named destination, beside checks and written paths, and the
unasked lane never receives them. The consent sentence says so: "the repository and number of a pull request
it created, and the names of skills it used", and because the sentence changed, a reader who allowed tool output
before is asked again. A pull request ranks with the passes and is listed beside the twelve-entry cap when newer
entries would push it out (up to twelve more), because the verdict check reads the listing. A skill ranks after
every other entry, so it can never push out a written path; a dropped path would be counted as outside the named
folders and raise the live level. Under the prompt's byte bound a pull request is reserved like a pass and a
skill after a write. A reading may cite either as `consistent` for a line the fact
shows done, inside the evidence window. Neither can carry a departure, since neither has a result that can fail.

The owner also ruled that `git commit` and `git push` keep counting as commands that may change files. That rule
is unchanged: a pull request created is a fact beside them and not a reason to read their text.

Found on a real session whose goal was to use a skill and create a pull request: the agent did both, Claude
Code recorded its own goal as met with a reason naming the pull request, and the analysis said Can't tell,
because neither the pull request nor the skill was anywhere in what a reading is sent.

### Amended 2026-10-27 (owner): items 3, 5 and 10 are widened by DEC-29 and DEC-31

Three rulings of 2026-10-27 reopen parts of this record, and each is written in its own section.

- Item 3 ("a runner not named here is not a check") is widened by
  [DEC-29](#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes):
  the closed list becomes tier 2 of three, project scripts and a pull request's CI commands join it, and any
  other command may settle a line as a labelled tier-3 result. The read-only list grows by the commands that
  section names, for ageing and for the cannot-fail rule except the CI-reading commands, which can fail and
  whose recorded result counts. The quoted rule is item 3's closed-list rule as written in
  [the closed lists](#the-closed-lists), and the restatement it widens is
  [the 2026-10-23 PR and skill amendment](#amended-2026-10-23-owner-pr-and-skill-facts).
- Item 5 ("its time only, never its text") is widened by
  [DEC-31](#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor): which vendor
  reads the session decides whether a command that is not a check may be sent with its masked line and output
  tail.
- Item 10 ("the unasked lane never receives tool outcomes") opens for failed results only, by the same
  [DEC-31](#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor) ruling, without
  waiting for DEC-18's rubric thresholds. Passes are never admitted.

Nothing above changes until the layers that build these rulings ship; this record states the decision, and
the amendments to the shipped skill, SECURITY.md and the promise map ride in those layers.

### Amended 2026-10-27 (owner): more shapes and forms are masked, and a stored explanation is scrubbed

Item 5's masking and the output tail's redaction covered fewer credentials than a command's output can
print, and a departure's explanation was cleaned by shape alone. Three changes, each stopping a credential
from reaching a page or a stored reading and none changing what a check records.

- **Output shapes.** `records.redact_secrets` now also removes a gcloud `ya29.` access token, an AWS
  `"SecretString"` value, the password of a netrc entry behind `login` or `machine`, a `PASSPHRASE`
  assignment, and the signature parameter of a pre-signed URL inside a query string. The name stays and
  the value becomes the marker. Ordinary runner output, paths and commit ids are unchanged, and a test
  holds that.
- **Command-line forms.** `records.mask_words` also masks the password of `curl -u`, `--user` and
  `--proxy-user` (only a word with a colon, so `git push -u` is untouched), the value of `--cookie`, a
  `Cookie:`, `Proxy-Authorization:` or vendor-key header (a name holding `api-key`, `auth-token`,
  `access-token`, `secret` or `password`), a header name standing alone with its value in the words after
  it, a dotted config key such as `http.extraheader=`, the word after `-a` or `--pass` for `redis-cli`
  only, the token word of `vault login`, and the value of `aws configure set` for a secret-named key.
  Over-masking stays the accepted direction.
- **A stored explanation.** The press now carries every value any shell call masked
  (`PressChecks.masked_values`, `ToolOutput.masked_values`), and `reading.resolve` removes them from a
  criterion's explanation before it is stored, with the same boundary and re-quoting rules the output
  tail uses (`records.scrub_values`), and then applies the shape redaction it always did. Before this
  the tail was scrubbed of a masked value and the model's prose about it was not. The unasked lane sends
  no tool output except a failed check or command on Claude Code, whose tail and masked values it
  carries ([the amendment](#amended-2026-10-27-owner-the-unasked-lane-reads-failed-results)).

#### Corrected after review, 2026-10-27

An adversarial review of the change above found it removed too much and too little, and the points
below replace what it said.

- **Where a flag is a password.** `-u`, `--user` and `--proxy-user` are a password only for `curl`,
  `wget`, `http`, `https` and `xh` (`-su` and `-fsSLu` clusters included for `curl`), not for
  `docker run -u 1000:1000` or `git push -u`. A dotted config key is masked by its last part, so
  `--max-tokens=4096` is a flag and not a key. A program is found behind `rtk`, `sudo`, `env`, `uv run`
  and `docker exec`, because this owner's hook rewrites commands to `rtk <cmd>`.
- **Where a header is expected.** The wider header names (`Cookie:`, `X-Vault-Token:`, any name holding
  `token`, `key`, `secret`, `password`, `passwd` or `credential`) are read after `-H`, `--header`,
  `--proxy-header` or `extraheader=`, or joined to them, and nowhere else. A person's typed direction
  reads only `Authorization:` and `X-Api-Key:`, so "Fix the password: handling" keeps its words.
- **Which values leave an explanation.** Only a masked value that can be a credential, so `CI=true`
  does not erase the word `true` from a sentence. A value ending a sentence or inside brackets is
  removed; one inside a longer word or path is not.
- **The output shapes.** A netrc entry needs its `login`, or a value with a digit or capital when it
  has none; a signature needs a signature-like value and accepts `&amp;` and `\u0026` before it; an
  AWS `"SecretString"` runs to its closing quote, in either quote, however long; an unclosed one is
  masked to the end of its line.

### Amended 2026-10-27 (owner): CI polling commands are read-only

A session that ran its tests, pushed, then watched CI showed every earlier pass as before a change. The
last recorded change was a polling loop: `for`, `do`, `sleep`, `gh pr checks` and the `$(...)` that held
its output were all outside the read-only list, so each counted as a command that may change files. In a
30-day corpus of the owner's own sessions, 85% of shell calls held at least one such segment.

The read-only list of item 3 gains these, matched the same way and with the same refusals:

- `sleep`, `seq`, `true`, `false`, `:`, `break`, `continue`, `test`, `[` and `[[`.
- `gh pr checks`, `gh pr view`, `gh run view`, `gh run list`, `gh run watch` and `glab ci status`. They
  read a pull request, a run or a pipeline and take no option that writes a file. `gh run download` and
  `gh pr checkout` are not on the list. `gh run view --log > out.txt` is still a change, because of the
  redirect and for no other reason.
- A `for NAME in WORDS` header. A substitution in the word list is read on its own, so
  `for f in $(rm x)` is still a change.

A loop adds nothing of its own. At the start of a command, `do`, `done`, `while`, `until` and `!` are
syntax, dropped the way `then` and `fi` always were, so the command after them is read as itself:
`for i in 1 2; do pytest -q; done` lists `pytest -q`, and `for f in *; do rm $f; done` is still a change
because of `rm`. A substitution whose body is read-only is read-only, so `out=$(gh pr checks 7)` ages
nothing, and one whose body is not read-only still hides a change.

Two consequences are the part a loop can get wrong:

- **`!` inverts the exit status.** A negated check is listed and its result is never read: the flag and the
  summary no longer say whether the code is sound, so it reads "ran, result not recorded", never a pass.
  A `!` that is not at a command's start, as in `[ ! -f x ]`, negates nothing.
  A negated group's extent is not tracked, so a check after a negated group closes in the same call is read
  as negated too (`! (cd . ; pytest -q) ; pytest -q`). That fails toward no recorded result, never a pass.
- **A loop body may run again from where it ended.** A relative `cd` inside a loop leaves the directory
  unplaced, and so does any `cd` that moved the directory inside a loop for the commands after `done`,
  because the loop may have run any number of times, or none.

Unchanged: `git commit` and `git push` stay commands that may change files (see the 2026-10-23 amendment
above). With the commit and the push in the session the earlier pass is still aged by them, and the polling
loop adds nothing; without them the loop alone does not age it.

### Amended 2026-10-27: the command a hook rewrote is the command that ran

A `PreToolUse` hook can replace a Bash call's command before it runs. RTK is one: it turns a typed
`ruff check x` into `rtk ruff check x` and the call returns the condensed output (`Ruff: No issues found`)
instead of ruff's own. Claude Code keeps the typed command in the `tool_use` block and records the rewrite
as a separate `attachment` row ([the capture](captures/claude/pretooluse-rewrite-shape-2.1.311-macos.jsonl)).
Compass read only the block, so a rewritten check was read as a raw one and its condensed output went through
rules written for the runner's own text, which the `rtk` rule of 2026-09-24 exists to avoid.

The rule: a Bash call is the command that ran. When an attachment named `PreToolUse:Bash` carries a
`toolUseID` equal to the call's id and its `stdout` parses as a JSON object with a non-empty string
`hookSpecificOutput.updatedInput.command`, that command replaces the typed one everywhere the call is read:
the check's identity, its title and its wrapper stripping, so a rewrite that adds `rtk` takes its result from
the error flag alone. A call with no such attachment reads as before. A `stdout` that is not JSON, not an
object, over 64 KiB, or whose command is missing, empty or not a string is no rewrite, and the typed command
stands. Nothing else in the attachment is read, and the join is by id only, so a rewrite of one call never
reaches another. The masking and clipping of a check line are unchanged and apply to the command that ran.

Measured against RTK 1.1.0 on synthetic projects: of eight condensed outputs (pytest and go test, each
passing, failing and finding nothing to run, and ruff passing and failing; ruff with nothing to run was not
run), none matched a summary rule wrongly. Four matched a rule for the
right reason, which the `rtk` rule would ignore anyway. Jest, cargo and tsc were not installed, so their
condensed formats are unmeasured.

A hook may also normalise the invocation, not only wrap it. RTK 1.1.0 rewrites `python3 -m pytest tests` to
`rtk pytest tests`, `npx vitest run` to `rtk vitest` and `npx eslint .` to `rtk lint .`. The check's title and
identity are those of the command that ran, so a session where a hook was added part-way lists one check under
two identities. Compass reads `rtk lint` as the eslint runner, including `--fix` as a change, and a bare `lint`
is still no runner. The rewrite is also applied to a call carried from an earlier page of the transcript.
A page read before the hook's record arrives has already published the fact for the typed command, and a
rewrite that changes the check's title gives it a different id, so the pages alone keep that earlier fact.
The source comparison names it as changed, whether the later read is a continuation or a whole read, and a
reader that acts on a change by reading the whole file again ends with the same checks as a read of the
whole file. Until it does, a reader holding only the earlier pages still has the typed command's check.

### Amended 2026-10-27 (owner): `rtk proxy` is not a wrapper that rewrites output

[The closed lists](#the-closed-lists) name `rtk` as a wrapper whose checks read the error flag alone. `rtk proxy`
is RTK's unfiltered mode: [the capture](captures/rtk/proxy-passthrough-1.1.0-macos.jsonl) shows a pass summary
printed unchanged with the command's own exit status, so `rtk proxy <runner>` is stripped to `<runner>` and read
from its output as if `rtk` were absent, and bare `rtk <runner>` keeps the flag-only rule. A different program,
Rust Type Kit, is also installed as `rtk`; the capture's version line reads `rtk X.Y.Z` for the one measured.
rtk 1.1.0 renamed `rtk proxy` to `rtk bypass` and kept `proxy` as a deprecated alias; the amendment of
2026-10-28 below reads `rtk bypass` the same way.

### Amended 2026-10-27 (owner): pytest's `-p no:<plugin>` is shown

Item 5 of this ruling masks the word after `-p` as a password for every runner, and a pytest check then read
`-p …REDACTED` where the agent had passed a plugin flag. After wrappers are stripped, a pytest runner (`pytest`,
`py.test`, `python -m pytest`) shows the word after `-p`, or the joined `-pno:<name>`, only when it is `no:` and an
identifier of letters, digits, `_` and `.`. Any other word stays masked, because `-p hunter2` cannot be told from
`-p myplugin`, and every other runner and `-P` keep the mask. A word deliberately spelled `no:<identifier>` after `-p` in a
pytest check is shown whatever it is; credential-shaped values are still redacted by shape. The output-tail scrub
and the call's masked-value set keep the unconditional `-p` mask, so a shown plugin word can still be erased from
an echoed tail: that side only over-masks.

### Amended 2026-10-27 (owner): the cutoff counts the commands the reading never received

"Read all 14 entries after your intent" read as everything, when the session had also run seven Bash calls that
are not checks, among them the CI polls that proved the goal. Compass reads only the time of the latest command
that can change files, to age an earlier pass (item 3), and nothing about the read-only ones. The cutoff now adds
one sentence when any ran: "The session ran 7 other commands, 4 of them read-only; Compass did not read what they
did." The sentence names the session and not the window, so a long session can read "412 other commands" beside
three listed entries. The two counts come from the session scan, are stored only when that scan read the whole
transcript, and are left unrecorded when the scan was cut from the tail, because a cut scan counted only the
commands after the cut. They sit beside the
[measured coverage](#amended-2026-10-04-owner-disclose-measured-reading-coverage) the reading already stores.
Read-only is the scan's own test of whether the command could change a file. A session that ran none says
nothing.

The figure counts foreground Bash calls that hold no check. Background launches, calls that did not balance or
never ran, and a call that also runs a check are not in it, and a call that holds several commands counts once, so
it is a count of calls and a floor. A reading from the unasked-check lane carries no counts, so the page says they
were not recorded.

The stored `coverage` mapping gains `other_commands` and `read_only_commands`, both or neither, so a reading
stored before this change keeps its five keys and still validates. The page says "How many other commands ran
beside the entries read was not recorded for this reading" for any reading without them, which includes a session
on a harness with no scan. A lone count, a count that is not a whole number, and a read-only count above the total
refuse the reading, because a malformed count read as zero would say no command ran. No command text is stored or
sent: both are integers, and the model's prompt does not change.

### Amended 2026-10-27 (owner): the unasked lane reads failed results

Item 10 ("the unasked lane never receives tool outcomes") is opened for failed results only, by
[DEC-31](#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor), without waiting
for DEC-18's rubric thresholds. This is the build.

- **What the lane receives.** A tool report is listed in the unasked ledger only when its result is
  `failed` and its subject is a check, a tier 3 command or a CI command
  ([DEC-29](#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)), and
  the command can fail. A pass, a run that recorded no result, a CI pass, a write, a pull request, a skill and
  a command that cannot fail are never listed. The output tail rides with a failed row alone. The same rule
  holds the ledger whatever the press read: `reading.build_ledger` takes `failed_only`, set by the lane and by
  nothing else.
- **Why failures and not passes.** The lane raises departures and never reassures. A failure adds signal
  against the goal; a pass would add a comfort the lane may not give, and the ruling's evidence floor is why.
  The reading says so in its cutoff, and the model's "no check found" stays unread rather than absent when a
  report was left out.
- **Where it applies.** Claude Code reading a Claude Code session, with a destination Compass can name.
  No grant is asked for, as for a pressed reading. A Codex fallback keeps the words-only Allow it runs under,
  which does not cover tool output, so it sends none. The output tail follows the vendor rule
  (`reading_route.tails_for`); on the one route that sends, the session's own vendor, that is every tail.
- **What stays.** The caps (three per session, twelve per rolling day, a fifteen-minute floor), the rule that
  only a typed goal makes a session a candidate, and the lane's refusal to send the agent's messages or an
  outcome line.
- **What was rejected.** Listing every result so the model could weigh a pass against a failure: it is the
  reassurance the lane is built not to give. Sending a failure's tail to Codex under a words-only Allow: it
  widens an Allow past the content it disclosed.

### Amended 2026-10-28 (owner): `rtk bypass` is read as unfiltered, like `rtk proxy`

`rtk bypass --help` says it executes the command without filtering and that `rtk proxy` is a deprecated alias
that behaves identically, and [the capture](captures/rtk/proxy-passthrough-1.1.0-macos.jsonl) now holds the
same three arms for both spellings with identical output and status. `rtk bypass <runner>` is stripped to
`<runner>` and read from its output as if `rtk` were absent, whether the agent typed it or a hook rewrote the
command to it. Bare `rtk <runner>` keeps the flag-only rule. The check reader, the masking pass and the tool
family reader each take `bypass` wherever they took `proxy`. So does the hook-side irreversible-shape matcher, a
separate closed list: `command_shape` in `event_hook.py`, and its copies in the Gemini and Droid roots, strips an
`rtk bypass` prefix as well as `rtk proxy`.

### Amended 2026-10-28 (owner): C-style and bare `for` headers are read-only

The polling rule above counted `for NAME in WORDS` as read-only, so a loop written `for ((i=0;i<3;i++))`,
`while ((i<3))` or `for i` aged every earlier local pass as "before a change", though none of them writes a
file. Under-coverage of this kind keeps a pass aged and never makes a false one.

- **The headers.** `for ((init; test; step))` is read as one arithmetic header, not split at its semicolons;
  bare `for NAME` (which loops over the positional parameters) is a header when `NAME` is an identifier; an
  arithmetic command such as `((i++))`, which `while ((…))` also uses, only sets a shell variable.
- **What still ages a pass.** A redirect on any of them, a substitution inside them that writes, and every
  body command that is not read-only, so `for ((;;)); do rm x; done` and `for ((i=0;i<3;i++)); do echo x > f;
  done` still count as changes. A check inside the loop is still found and listed.

### Amended 2026-10-28 (owner): Biome, Storybook and Gradle check runners join the closed list

A reader on a Java project, or on a monorepo that runs Biome or Storybook tests, saw those runs listed as
commands with no result. The closed list in item 3 grows by these runners, matched the same way as the rest
(first words of a stripped segment, with `pnpm exec`, `pnpm` shorthand, `npx` and the other wrappers removed):

- **Lint.** `biome check` and `biome ci`.
- **Test.** `storybook test`, `test-storybook`, and the `test:stories` script spelled `pnpm test:stories`,
  `yarn test:stories`, `npm run test:stories`, `pnpm run test:stories` and `yarn run test:stories`;
  `gradle check` and `./gradlew check`.
  `gradle test` and `./gradlew test` were already named. `gradle build` is not added for its check form: it
  was already a build, and it stays one.
- **Fixer spellings.** `biome check` or `biome ci` with `--write`, `--fix`, `--apply`, `--apply-unsafe` or
  `--unsafe`, `biome format --write`, and a Storybook test run with `-u`, `--update`,
  `--update-snapshots`, `--updateSnapshot` or `--update-snapshot` rewrite files. The `test:stories` script
  spellings above are fixers with the same flags, whether given directly or after a bare `--`. A run with
  one is a fixer that ages every earlier pass, as `eslint --fix` is, and a declared script whose body holds
  one is not a check. `-u` is read as a fixer only for the Storybook runners, because other programs use it
  for something else.
- **Last-line summaries.** The table in
  [DEC-29](#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes) gains
  two rows, each from output measured or documented. Biome prints `Checked N files in Xms. No fixes
  applied.` for a run with nothing to report, and a failing run ends on `Found N errors.` or on `Some errors
  were emitted while running checks.`, which one depending on how its streams interleave; a pass line is
  refused when either failure line sits above it, and a run that checked no files is not a pass. Gradle ends
  on `BUILD SUCCESSFUL in Ns` or `BUILD FAILED in Ns`, then an `N actionable tasks` line that is skipped from
  the end. Storybook's runners have no row: `test:stories` is a project script whose wrapper may print after
  the test runner's own summary, and the exit status alone speaks for them.
- **What was rejected.** Reading `Tests` lines for `storybook test` because it runs vitest: the line that ends
  the output belongs to whatever the project wraps around it, which a closed table cannot know.

## DEC-24: your intent is a drafted goal and a checklist, and a correction is yours to copy

Amended 2026-10-22: item 3's Expected outcome is folded into an accordion under the Goal, closed by default and labelled "Expected outcome (optional) · up to 6 lines". It opens by itself over saved lines, a drafted or pending line, and a departure citing a line, on each rise of that condition rather than whenever it holds, so a reader's close stands. `+ Add a line` moved inside it. The six-line and 240-character limits are unchanged.

Amended 2026-10-11 by [DEC-27](#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result): item 3's Expected outcome is one optional empty line by default, and the Direction question's summary shrinks to one line while Keep keeps its two presses.

Decided 2026-09-24 (DRC-4675). It brings the Session Drift Detection design's option C, "Unified
intent and drift panel", into the rulings. The panel is built by DRC-4680, the copied-correction
route by DRC-4678, Cancel by DRC-4693, Steer back by DRC-4681 and Update intent instead by
DRC-4697, among the milestone's other layers.

A reader who opens a session to see whether it drifted meets DRIFT, GOAL and EXPECTED OUTPUT, empty
fields, and a result that says "0 departures" beside "raised nothing and confirmed nothing". This
decides the words, the intent, the answer, when an analysis may run, and what Compass may hand
back.

The owner ruled four things first. The goal is drafted from the reader's first prompt. The expected
outcome is a checklist the reader writes, and nothing is inferred for it. Copy, not Send. Claude
Code only: other harnesses show the panel with a stated limit. The drift level is its own decision,
[DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn).

The ruling is the full shape below. The two alternatives were the words and the checklist with no
correction, and today's shape unchanged. What it costs: amendments to DEC-15b's eligibility,
DEC-16, DEC-17 rules 6 and 7, DEC-20 (item 2, its control label and its primary-control paragraph),
DEC-21 item 1, SECURITY.md's reader-requested section (labels "Analyze drift" / "Allow and
analyze") and DEC-22; new stored items (a revision's window start, its outcome lines with each
line's source, a reading's `evidence_through`, a digest of each copied correction) and one new
token, a reader's "not accurate" mark; and reader edits inside a copied correction are exempt from
the later-direction floor (item 9).

1. Words. The panel is "Intent and drift": an "Intent" section (Goal, Expected outcome) and a
   "Drift" section. The action is "Analyze drift", replacing DEC-20's "Check for drift". Answers
   name departures, never "no drift": "Departs from your intent", "Can't tell", "Nothing found
   against what it read". The attempt count stays beside the control.
2. The goal draft. On a session with no saved goal, the goal field shows the reader's first prompt
   as Compass publishes it (one line, a clipped excerpt marked as such), marked "from your
   prompt", unsaved. "Looks right" saves it; an edit saves it as typed; pressing Analyze drift
   adopts it in the same press (DEC-22). Nothing is inferred for the expected outcome. Amended
   2026-10-02 (owner): there is no "Looks right"; Save intent is enabled over the untouched draft
   and adopts it, so a drafted goal has one way to be saved, and Undo changes stays inert until
   there is an edit.
3. The checklist. The expected outcome starts with one optional empty line. Add a line and per-line
   Remove appear after use; the checklist still holds up to six lines the reader types, each at most 240
   characters and one line, each read and shown as its own constraint under DEC-17's rules. Each
   line records its source: typed, or added from entry #n. The bounds, fixed by DRC-4685, the layer
   that first stores and sends outcome lines:
   - The store holds 6 lines of at most 240 characters on each revision. A seventh line, or a line
     over 240 characters, is refused rather than clipped. The store's read limit is 16 MiB, and a
     write trims the least recently written entries until the file fits, so the next read reads
     what the write kept (owner, 2026-09-24). The entry being written is never the one trimmed:
     when it cannot fit even alone, nothing is written and the save answers `unwritable`.
   - The history copy is one flat field per line, at most 256 characters each, with a closed
     source token beside it and no entry id.
   - The goal and the lines take at most 12,800 of 16,384 bytes of the prompt (9,728 until the
     goal's cap rose to 1,000, [2026-10-27](#amended-2026-10-27-owner-the-goal-holds-1000-characters)). Over that share,
     every line is dropped together as not asked, never some of them.
   - The reply cap is 8,192 bytes, and a reply cut at the cap keeps each answer that arrived
     whole.
   - The annotation request body cap is 16,384 bytes. The widest body the page can send is a
     goal and six lines pasted as control characters, which the browser writes as six bytes each
     before the store collapses them: 14,798 bytes with a 64-character session id and a
     1,000-character goal (10,238 and a 12,288 cap before [2026-10-27](#amended-2026-10-27-owner-the-goal-holds-1000-characters)).
4. A later direction before an analysis. When the record holds an unsettled later direction of the
   reader's, the Drift section asks before the press, naming how many are unsettled. For one it
   says "You gave a later direction at #<n>: "<first line>"."; for several, "You gave <N> later
   directions since saving your intent, the earliest at #<n>: "<first line>"." Then it offers "Keep
   my intent and analyze" or "Add it to my intent". Keep settles all of them (DEC-16's "The
   baseline still applies") and analyzes in one press, and counts as "Allow" where the disclosure
   beside it has not been allowed yet. Add opens a new outcome line holding the direction's raw text
   for review. A direction over 240 characters or on several lines is edited by the reader to one
   line before saving, and never saved as a summary. When six lines exist, the reader replaces or
   merges an existing line, and a seventh line is refused with a sentence saying why. The goal is
   kept.
5. Background analysis. Analyze drift starts a job the server owns: a job id; phases that match
   real work ("Preparing what is sent", "Waiting for <provider>", "Checking the reply"), published
   over the existing push so a reload keeps them; and Cancel. The call runs in its own process
   group (a Job Object on Windows), so Cancel never signals the daemon's group. Cancel kills that
   group, releases the one-in-flight slot only after the child is reaped and its temporary files
   are removed, records a "cancelled" withheld reason as a spent attempt, and discards a reply that
   arrives after it. Amended 2026-09-24 (owner, DRC-4693): a cancel that lands before anything is
   reserved spends nothing. The hint under the button says what is read ("Reads the session up to
   <cutoff> against your intent. Runs in the background.") and carries the DEC-21 disclosure. The
   button reads "Allow and analyze" until allowed. Amended 2026-10-01 (owner, Q1, DRC-4758): the
   button reads "Analyze drift" in every state, and the first press that would send anything opens
   a consent step that shows the full disclosure, as the server's parts, before "Allow and
   analyze", with "Not now" beside it
   ([the consent step](#amended-2026-10-01-the-first-press-is-a-consent-step)).
6. The result. Per line: "Departs at #<n>" with its cited evidence, only for a valid departure. A
   consistent line names its source by the cited entry's type: "Consistent with #<n>, as the tool
   reported; not inspected" for a tool outcome, "Consistent with what the session said at #<n>; not
   a check" for the agent's own account, on the Goal only: on an outcome line the agent's own
   account yields `not verifiable` (DEC-17 rule 7). Changed by
   [DEC-17's amendment of 2026-10-03](#amended-2026-10-03-owner-the-agents-own-words-are-evidence),
   which says what a `consistent` resting on the agent's messages reads now. Never "Done" and
   never a check mark. Otherwise
   "Can't tell: nothing recorded shows this yet". Amended 2026-10-04: a blank row that cites
   entries instead says "Can't tell: what was read does not settle this"
   ([the coverage amendment](#amended-2026-10-04-owner-disclose-measured-reading-coverage)).
   A headline and short account render only under a departure,
   built from departure detail with its citations. "Where the work went" groups written paths by
   folder without a model. The session's activity flags each entry a departure cites ("Cited") and
   a later direction ("A later direction you gave"). A reading stores `evidence_through`, and it is
   stale when the intent revision or the evidence after that time changes: "Your intent changed
   after this analysis" or "New work since this analysis", each with "Analyze again".
   Amended 2026-10-01 (DRC-4758 fix round, the stored-reading word budget): in the Drift card's
   checklist the line in view names its source without the qualifier, "Consistent with #<n>" for a
   tool outcome and "Consistent with what the session said at #<n>" for the agent's own account.
   The whole sentence above, qualifier included, is the first line of that line's Evidence, and the
   tool qualifier stays in view once for the page in the activity record's footer ("Results are as
   the tool reported; not inspected."). Never "Done" and never a check mark still holds.
7. Steer back. The server composes a correction without a model, from these fields only: the goal,
   each outcome line with its state, and the cited entry numbers and times. No model prose, no tool
   output, and no recorded command as an instruction. It is editable before copying, at most 2,000
   characters, and offered from an analysis and, with no analysis, from the recorded facts (a
   failed check). A later direction alone ceased to offer one under the
   [owner amendment](#amended-2026-10-04-owner-correction-triggers-and-wording). Copy only, and the panel uses Copy-only wording where the
   design had a Send hint. Sending it into the session is DEC-25, a follow-on that is not ruled
   (DRC-4698). Since
   [2026-10-04](#amended-2026-10-04-owner-what-the-agent-claims-is-its-own-constraint) it also
   quotes one agent message's published title, for a claim the record contradicts or does not show.
   Amended 2026-10-14 (owner): each entry the page numbers reads "(entry #n in Compass's activity
   list)" ([the wording](#amended-2026-10-14-owner-the-correction-names-the-entry)), and a write
   outside a named folder is not a trigger
   ([the ruling](#amended-2026-10-14-owner-a-write-outside-a-named-folder-does-not-settle-a-line)).
   Amended 2026-10-20 (owner): each departure also carries the stored reading's explanation, and
   the cap changes to fit ([the amendment](#amended-2026-10-20-owner-the-correction-carries-the-explanation)).
8. Update intent instead. It opens Intent for editing and offers the later direction as a new
   outcome line under item 4's rules. It never replaces the goal.
9. A copied correction coming back. The server records a digest of the exact text the reader
   copied, edited or not, per session: bounded per session, one use per digest, matched only after
   the copy. Each user message's digest is computed from its raw text before any clipping. A later
   message that matches exactly is Compass-assisted: not adopted as the goal, not person-authored
   evidence, and not an unsettled later direction. No match, no special treatment. SECURITY.md
   names the route and its local-process residual. Built by DRC-4678 to the owner's rulings of
   2026-09-28: both sides normalise CRLF and CR to LF and a tab to four spaces and are trimmed at
   both ends, which is what a live paste into Claude Code 2.1.283 measured; eight digests per
   session, the oldest dropped; and the activity list labels a recognised message "You · Copied
   from Compass". An edited paste, a backspace that wipes it included, is the reader's own words.
   The review round added three things. "After the copy" is a position in the transcript, not a
   clock: a message counts only if it was written past where the transcript ended when the text
   was copied. A recognised message is stored by its fact id and stays recognised after the tail
   moves on, up to 32 per session, apart from the eight waiting digests. Adoption and every
   surface that shows a prompt as the reader's words (the stated goal, the assignment, an exact
   direction) compare fact ids, so a prompt typed in the same second as a paste stays the
   reader's while the tail holds it. Amended 2026-10-21: the harness's paste tags are taken off before
   the digest is computed, and a paste edited only in whitespace is also recognised
   ([the amendment](#amended-2026-10-21-a-pasted-correction-is-compasss-words-and-a-kept-direction-is-no-evidence)).
10. Not accurate. A token the reader can set on a reading, stored with the annotation entry and
    removed with it. `--forget` does not reach it. It is never sent, never counted and never entered
    into abstention marks, and SECURITY.md notes it. The
    [2026-10-04 amendment](#amended-2026-10-04-owner-correction-triggers-and-wording) also removes
    that reading from the derived level and correction until the mark is cleared.
11. Numbering. The activity list numbers entries in the evidence window, and a citation says
    "#<n>". It says "turn" only where the harness supplies a stable turn identity. Stored readings
    cite fact ids, so a number is recomputed, never stored. Amended 2026-10-20 (owner): a
    departure's explanation travels as text, never as a placeholder, and the page renumbers nothing
    inside it ([the amendment](#amended-2026-10-20-owner-the-correction-carries-the-explanation)).
12. The unasked lane receives none of this: no outcome lines, no work evidence, no drafted or
    confirmed goal, no correction, no digest and no Not accurate token. None of them makes a
    session eligible for the lane, or triggers, orders or gates it. A failed check or command on
    Claude Code is the one exception ([the amendment](#amended-2026-10-27-owner-the-unasked-lane-reads-failed-results)).
13. When an analysis may read, and against what. A session waiting at its prompt after a turn stop
    may be read through its last turn, saying so, and never as a reading of how it ended; a goal
    saved after the stop does not withhold it. The evidence window starts at the words' own time:
    the source time for adopted words (DEC-22); for typed words, the time of the latest
    person-authored message at or before the save, else the save time. It is stored on the revision
    beside the save time, as a new revision field admitted under DEC-15b, and a build that does not
    know it falls back to the save time. The page shows both times and labels work before the save
    with a "Last turn" word beside the head time, carrying "from the last turn" as its accessible name and tooltip. The unasked lane still withholds at a turn stop.
14. The answer reducer. Any valid departure gives "Departs from your intent", and other lines keep
    their own state. Otherwise any saved constraint without a valid `departure` or `consistent`,
    including a malformed or missing result and a line the reading could not ask, gives "Can't
    tell". Otherwise the answer is "Nothing found against what it read. This is not a check that the
    work was done." A failed check in the window outranks both "Nothing found" and "Can't tell". A
    departure count renders only beside a departure. "No reading was produced" and the refusals are
    process states, never answers. All of it is session-page only: never on a row, a total or a
    notification. Elsewhere than Claude Code the panel states the harness limit ("Compass can't
    read work from this harness"). "Stop session" is not offered (DEC-16, SECURITY.md).

### Amended 2026-10-05: verified request age belongs to a line

Delegated owner acceptance, 2026-10-05 (DRC-4783), narrows item 3 without changing item 13's
goal window. A typed checklist may describe work the reader wants to evaluate retrospectively.
Saving it does not prove when the agent received that requirement. Typed and legacy lines therefore
keep unknown request age; a line's save time is never substituted for its request time.

Add can bind a line to its actual parent-person request. The server verifies the source fact's
identity, parent session and time, and stores that time with fingerprints of the parent, source
identity and full request record, and reviewed line. These are local binding data, not additional copies of the request's
words. Unchanged and reordered lines keep the binding once; a newly typed duplicate or an edit
does not inherit it. A request at the save time, a future or copied request, duplicate source
identity or ambiguous same-time parent messages supplies no binding.

An edit made while first adding the entry also keeps unknown age. Only exact equality with the
complete authoritative request words, redacted and normalised as a saved line, can bind those
words to that earlier time. A shortened request, changed requirement or incomplete extraction
still saves the reviewed line and its source handle; none inherits the source's request age.

Loading a malformed, cross-session or after-save binding removes only that binding. The person's
words stay. Before a binding can affect a reading, it is checked again against the actual current
parent fact and the line's words. A missing or changed source leaves age unknown. A downgraded
build may discard this optional binding, which also leaves age unknown. No time is guessed for
older lines.

Source proof comes from the bounded newest and opening transcript reads, not from historical summaries.
The [long-session lookup](#long-session-direction-and-prompt-reads) owns their current bounds.
Each operation reuses one source lookup; the bounded cache checks device, inode, size and
modification time before reuse. A record beyond the byte or fact bound supplies no proof. The
transient raw-record and complete-word digests and source version never reach the page, model
prompt or history.

For a verified line, a citation can judge work against that request only if its action or call was
recorded strictly after the request. A call made earlier does not become later work when its
result arrives afterward. Same-time work is not ordered by the clock. The existing goal-window
check still uses result arrival for checks, and the global failure and visibility signals are not
weakened. Removing an earlier citation can only withdraw a verdict; it never creates reassurance
or a neutral unfinished-work result.

The focused page context carries only revalidated request times and source handles, tied to the
current intent revision. Binding fingerprints stay in the annotation store. The producer,
analysis level, page and correction apply the same action-time boundary. A historical reading
whose revision differs from the current intent carries no request-age exemption. Existing replay intents
have typed or legacy lines and retain unknown request age. No new class of words reaches the
model, so this changes neither the permission disclosure nor its content version.

### What the last-turn build decided, 2026-09-24

DRC-4679 built item 13. These are the calls the ruling left open, each made by the orchestrator
within the milestone's scope and recorded on the issue.

- Only Claude Code is read at a turn stop. `eligibility` takes an `admit_turn_stop` switch that is
  off by default, and only the reading route turns it on, for a harness in
  `reading.TURN_STOP_HARNESSES`. The unasked lane fires on every working-to-idle change, which is
  every turn stop, so it keeps the closed default. The test for that runs the lane with the real
  `reading.produce` and a model that counts its calls, because a lane test built on a fake producer
  cannot see the gate.
- A turn stop gets the same eight-second settle as a session end, with its own sentence, since the
  end's sentence says the session ended.
- Through the last turn means through the observed stop: the reading drops every entry timed after
  the stop (`reading.observed_stop`). A resumed turn whose state update lags leaves the row idle at the old stop while the
  record moves on, and without the cap a check from the new turn was cited in a reading that said it
  covered the last one.
- Words typed after a session end are still withheld. Only the turn stop is relaxed, and the
  withholding test still compares the save time, `baseline_at`. The window start moves only the
  evidence.
- Amended by the owner, approving the Analyze drift plan, 2026-10-04: unchanged typed goal words
  carry their existing window through a lines-only save or an added direction. New goal words
  recomputed the window until the owner's ruling of 2026-10-21 below. For those typed words it is
  the latest `user_message` of this session at or before the save, read on the server from the
  session's record, found in the all-sessions collection so a save from that view on an aged session
  still finds it. A permission approval is not a message, so it never moves the window. A record
  that cannot be read opens the window at the save and never refuses the save. Adopted words,
  including an adopted goal carried under a lines-only save, open at their source time. A clock
  moving backwards clamps the carried start to the save. "Saved" names the window beside the goal.
- A stored window start that is not a moment at or before its own save refuses the entry, as a bad
  provenance does, because reading around it could restore older words.
- A check keeps its call time. The window start alone fixes the case the live walk found: none of
  22 recorded Bash calls had a message from the reader between the call and its result. Using the
  result time would move layer 1's published timestamps, so it is filed separately.
- The page reads the window from the reading, and derives it the old way for a reading stored
  without one. It labels work "Last turn" beside its head time, with "from the last turn" as the accessible name and tooltip, only on a Claude Code session waiting at its
  prompt, and only the observed last turn inside the window: from the reader's latest message at or
  before the stop (or the window start, if later) up to the stop, never on the reader's own messages.
  The first build labelled from the window start to the save. That range is fixed at the save, so
  the next turn made it name an older one, and a save made mid-turn left the rest of that turn
  unlabelled.
- The hint says what an analysis reads: "Reads the session up to <cutoff> against your intent.",
  where the cutoff is now, its end, or its last turn, from the same end kind HOW IT LANDED shows. It
  shows only where a press could read: a provider, no refusal beside it, saved words, and words
  given before any observed end. The background job (DRC-4686) added "Runs in the background."
  after it; the Drift card dropped that second sentence on 2026-10-21, since the job box already says
  where the work runs.
- The later-direction floor stays at the save time. By construction no message of the reader's lies
  between the window start and the save, so moving it would change nothing on consistent data and
  would, on a fetch the server missed, turn a message into a later direction.

#### Amended 2026-10-02 (owner): Claude Code's transcript may show the turn stop

On a board no Claude Code hook reaches, no turn stop was ever observed, so Analyze drift opened
only while a write kept the row Working and closed 90 seconds after the last one. That covers a
dashboard on any port but the hooks' (4553 by default), every stop from before a restart, since
the coordinator holds stops in memory, and an `away_summary` that turned an idle row Working.
The owner's walk on 2026-10-02 saw Analyze go inert, live and inert again with no word why
(arbiter spec, `ui3`). Item 13 now admits a second kind of turn stop, for Claude Code alone:
the transcript's own top-level `stop_hook_summary` for this session, written when Claude Code
runs its Stop hooks, directly after the turn's last assistant reply, and with no `user` or
`assistant` record and no other activity newer than it by more than the activity grace. A
`user` record between that reply and the summary refuses it: a Stop hook that blocks the stop,
and a goal check that is not met, write their feedback as an `isMeta` user record there, then
the summary with `preventedContinuation` false, and the turn goes on. `preventedContinuation`
true is a hook ending the turn, and is a stop. The first build read that flag the other way
round and published a turn a hook kept going as finished (verifier S1, `ui3`, read from Claude
Code 2.1.287's own Stop-hook loop); the scorer's `_transcript_stop` shared the error and takes
the same correction, which is what its 2026-10-01 words "did not keep the turn going" meant. It is the record
the 2026-10-01 amendment measured about 115 ms ahead of the hook. It is read from the tail the
collector already reads and published as `turn_end_at`, and the row turns Idle as a hook Stop
would turn it. `finished_at` stays hook-only. A hook stop, when held, is the stop. Either kind
settles `reading_settle_sec` after its stamp, a reading through it drops every entry timed after
it, and its scope sentence says which kind it rested on. A last record that is a tool call, a
tool result, an interruption or a command is not a turn stop. Neither is a summary labelled for
any hooks but Stop: Claude Code 2.1.287's Stop path writes no `hookLabel`, and its own reader
knows a summary labelled `PreToolUse`, written mid-turn after a tool call and before the tool
runs, so only an absent label or `Stop` is admitted (verifier S2, `ui3`, read from the installed
bundle). No capture under `docs/captures/` records the label, and the test fixtures carry one only
where a test sets it. The press withholds a non-stop with Claude Code's own sentence. The unasked
lane still withholds at every turn stop, and no other harness changes. One thing does change for
it, on a board no hook reaches: a quick turn's row now changes state twice, Working to Idle at its
stop and back at the next prompt, where before it read Working throughout, and the lane, which
considers a typed-goal row whenever its state changes, may read it mid-flight at each return to
Working (verifier S3). That is what a hooked board already does, and the lane's own bounds hold
it: off by default, at most three readings per session, twelve a day, and 900 seconds apart
(`unasked_session_cap`, `unasked_daily_cap`, `unasked_session_floor_sec`). The final assistant message's `stop_reason` is not read: no capture records
it. This does not change the scorer's rule of 2026-10-01, which vouches for a recorded case
only at a matched stamp, and it infers nothing from the last assistant message.

#### Amended 2026-10-20 (owner): an idle session with no recorded finish is read up to its last entry

A fresh-eyes usability review found that a Claude Code session whose last turn had no recorded
finish (an interrupted turn, or one that went quiet mid-turn) could never be analyzed once it was
idle, and the only reason the page gave, "Analyze opens while this session runs.", would never come
true for a session nobody resumes. The owner ruled on 2026-10-20 that Analyze drift is allowed on
such a session: it is read up to its last recorded entry, the way a running session is.

- `reading.eligibility` admits an idle row with no observed stop and no observed end
  (`reading.IDLE_PRESS_KINDS`: `idle-unknown`, and `unobservable` for a scan-only row) on the same
  reader's press that admits a turn stop, for a harness in `TURN_STOP_HARNESSES` only. The scope is
  `mid-flight`, never `last-turn` or `final`: nothing in the record says the turn ended, so no
  verdict on how it ended may rest on it, and a goal saved later does not withhold it. No entry is
  cut, because there is no stop to cut at.
- The stored sentence is `reading.SCOPE_TEXT_MID_FLIGHT_IDLE`, admitted on read-back beside the
  running one, and the page draws it in the result as "Read up to the last recorded entry at HH:MM;
  the last turn was not recorded as finished.", the time being the reading's `evidence_through` in
  the reader's own zone. The answer still leads with "So far:".
- The unasked lane is unchanged: it never sets `admit_turn_stop`, so it withholds an idle row as it
  did. A running session, a turn stop, a session end and every other harness keep their rules.
- The Claude Code press line and Why sentence for an idle row are gone, since the board no longer
  refuses one. Every line the board can still publish states the condition that holds, a press on a
  refused Analyze opens its disclosure, and the disclosure is named "Why Analyze is off".

#### Amended 2026-10-21 (owner): editing the goal keeps the reading's start

The bullet above that says new goal words "recompute the window" is replaced. The owner's walk found
that rewriting a goal to widen it moved `reads from 10:57` to `reads from 11:05`, so the next reading
read only the entries after the edit and a line the earlier work had satisfied went from Consistent
to Can't tell. Editing the goal says the work already done still counts.

- A revision keeps the window of the revision before it. Saving new goal words, saving a line, and
  adopting a prompt or a later direction as the goal with Use this as my goal all leave the start
  where it was, so the next reading reads from the original start. Only the first save of a session,
  and the first save after a discard, open a window of their own, by the rules above.
  The first save that carries a goal opens the window, so a line saved before any goal does not
  count as the start: adopting a prompt over a revision holding lines alone opens at the prompt's
  own time, and typed goal words open at their own window.
- Reading from the edit onwards is the reader's explicit choice, offered beside Save (labelled Read from my latest message since 2026-10-21; see the amendment at the end of the Intent card's section)
  intent. `POST /api/annotate` takes `read_from_now: true` on a typed save or an adoption, and the
  save then opens the window as a first save would: the reader's latest message at or before the save
  for typed words, the source's own time for an adopted prompt. It is the reader's latest message and
  not the save instant because the turn that message started is still the work being read. The page
  says so beside the save in the same moment, with that time. Unchanged words saved this way still
  mint a revision, since the window is the thing the reader asked to move.
- A window start is still never later than its own save, and one that is stored without a window
  opens at its save, as above.
- A reading or a raise that predates a change of the goal says so in times the reader has seen (when
  it was made, and when the intent changed) and never by revision number. Revision numbers stay
  inside the store and the wire.

### What the background build decided, 2026-09-24

DRC-4686 built the background half of item 5; Cancel is DRC-4693. The owner's calls are on the
issue, and the rest were made within them.

- The press answers `202` with the job before the model is called. Every refusal the press had
  before stays synchronous and first. A second press answers `409` with the running job and starts
  nothing; `409` rather than `200`, because a forged press is read by its status.
- The job registry sits beside the one-in-flight slot in `reading`, under its lock, rather than
  replacing it. The unasked lane takes the same slot, and with the slot replaced it would either lose
  its guard or appear as a job the reader never started. A press that meets the lane's slot answers
  `409` with no job.
- The job is published board-wide as `reading_jobs`, keyed as the page keys a session, and not as a
  field on every row. A row field would be declared in three places and would enter history.
- Each phase begins at a real point: preparing at the press, waiting at the CLI's spawn (after the
  spend is committed), checking when a reply arrived. A withheld gate ends a job while it prepares
  and a failed call ends it while it waits; nothing publishes a phase that did not happen. The
  design's timed steps and its "Analyzing 38 turns" heading are overruled: the heading reads
  "Analyzing drift", because a Claude Code session has no stable turn identity (item 11).
- The store is written first, then the job is removed and the slot freed as one step, then one
  revision is published. Any other order lets a page show a finished box with no result, or a result
  under a running box.
- The permission and budget are read again at the model seam inside the job. A refusal there ends
  the job with nothing written, and the board's published permission already says why.
- A job lost to a restart is recorded, not dropped. A marker written before the reservation becomes
  a spent `interrupted` attempt at the next start, so the count stays equal to what the budget
  charged. Letting it vanish was the alternative, and it leaves a charged attempt nowhere in the
  count. Written before rather than after, because a marker that fails after the spend leaves the
  spend uncounted. The cost was that a dashboard dying between the marker and the reservation
  counted one attempt the budget never charged. The job ledger replaced that trade-off on
  2026-09-27 (see "What the accounting build decided" below).
- One job is one attempt. The outcome is stored under the job's id and a second write for that id
  counts nothing, and a marker is claimed by an atomic rename before it is recovered. The review
  measured a double count in up to 36 of 40 runs when the dashboard died between the write and the
  marker's removal; reordering alone would have traded it for a lost count.
- A marker's pid means a running dashboard only when a state file on this state directory names it,
  and this process's own pid means an earlier run: a container's dashboard is PID 1 on every start,
  and a bare liveness check never recovered its markers.
- A graceful stop records `interrupted` too. The shutdown kills the call before the next start can
  find its marker, so without this the job wrote "did not complete" for what was a stop.
- Every model call, the goal lane's and the unasked lane's included, uses the supervised runner. A
  timeout that kills only the direct child leaks the grandchild, which those lanes had too.
- Shutdown kills every supervised group, because a child in its own group no longer receives the
  terminal's signals. Leaving that to Cancel would have left one layer of the stack with a child
  that outlives the daemon. SIGHUP and SIGQUIT unwind through the same cleanup as SIGTERM, since a
  closed terminal otherwise left the CLI running untimed, and the shutdown closes the runner under
  its spawn lock, since a CLI spawned during the teardown was measured outliving it. A SIGHUP or
  SIGQUIT the server inherited as ignored stays ignored, or `nohup` would stop protecting it;
  SIGTERM always gets the handler, so `kill <pid>` stops the server as it did before. A reading not yet
  sent when the runner closes is refused before the reservation, so a stop never charges for it.
- On POSIX the group is signalled only while its leader is unreaped: the exit is watched without
  reaping (`waitid` with `WNOWAIT`, a kqueue exit filter on macOS, which has no `waitid`), the group
  is swept, and only then is the leader reaped, with the end of signalling marked in the same step
  under the group's lock. A group id signalled after the reap could name a stranger's group. kqueue
  reports a registration error as an event, so only ESRCH there counts as an exit; any other error
  leaves the exit unwatchable, and the call then polls rather than reading it as an exit and killing
  a running CLI. A helper that leaves the group is not reached, and the docs say so.
- A spent outcome the store refuses keeps its marker, marked as refused, and the next start records
  that the analysis ran and its outcome could not be stored, not that Compass stopped. A refused
  "interrupted" or "unstopped" keeps its own reason, so "may still be running" is never turned
  into "ran".
- A finished step is a filled mark and never a check mark. Item 6's rule is about results, but a
  check shape beside a reading is close enough to its reason that the design's check circle was
  not copied.

#### Amended 2026-10-20: a failed analysis names its cause

The usability review's first press failed because the Claude Code CLI was signed out, and the page
said only "The reading did not complete. Nothing was produced, and a fresh press is the only retry."
A failed Claude Code call now records the closed label `observer._claude_failure_reason` already
reads from at most 8 KiB of the CLI's output after a nonzero exit, or its `timeout` category, and
stores one sentence per label (`reading.CLAUDE_FAILURES`), such as "Analyze failed: Claude Code said
it is not logged in. Nothing was saved. Fix that, then press Analyze drift again." A call with no
label, or an unknown one, stores "Analyze failed: Claude Code returned an error. Nothing was saved;
press Analyze drift to try again." Codex discards its stderr and has its own unlabelled sentence, and
a job that failed inside Compass keeps `model-failed`, reworded the same way. That includes a
Claude Code job that failed before the CLI started, such as no private working directory, which
records no diagnostic (`reading.claude_failure` reads its absence as `model-failed`). No word of the CLI's
output is stored or shown: quoting a first line of stderr, as the review suggested, would carry text
SECURITY.md keeps off every surface, and a closed label says the same thing for every cause the list
knows. The sentence stored before this change maps to `model-failed` on read-back
(`reading.LEGACY_WITHHELD`). Each failure still counts as the spent attempt it was.

#### Amended 2026-10-01: a press the board says cannot read starts no job

DRC-4758 (slice A2). A walk on a board no hook reached found the press offered, a `202` job started,
and the reason it then withheld landing far below the button. The press-time withholds are now
decided once, before any job, by `reading.press_eligibility`, and the board publishes the same
answer on every row as `reading_eligibility: {ok, reason, until}`. None there means not computed
(annotations off), which is not the same reading as `ok: false`.

- The tokens it can publish are named in `reading.PRESS_WITHHELD`: `idle-unknown`, `unobservable`,
  `turn-stop`, `settling`, `stop-settling` and `revision-after-end`. Each is a fact the collection
  already holds about how the row ended. `until` is set for the two settling tokens, as the stop or
  end plus `reading_settle_sec`.
- Every other withheld token stays a job outcome. `record-unread` and `no-record-reader` need the
  observed record, which is a transcript read the collection must not make per row per poll, so
  `record_withheld` is left out. Consent, the budget, the CLI and the ledger are read where they
  were. `nothing-typed` and `discarded` are left out because a press over a draft adopts it first.
- An ineligible press answers `200` with `reason: "withheld"`, the token, its `WITHHELD` sentence
  and `until`. It registers no job, writes no outcome and counts no attempt. An Allow it carried is
  still recorded. This replaces the `202` such a press used to get, the first bullet above, for these
  tokens only.
- The page, the press check and the job read one function with the same `admit_turn_stop`, so they
  agree by construction. A test holds the job's pre-model withhold to the published one over a
  table of rows that reaches every token.
- Cost, measured on `bench_collect --simulate claude=40`: 0.05 ms for 40 rows against a 33 ms
  collect, under the 5% bar the plan set.

#### Amended 2026-10-01: a press says beside the button what it can do

DRC-4758 (slice B). The owner's walk pressed "Analyze drift" on a session the board could only
withhold: the box flashed, the panel went back to the bare button, and the reason sat in the READING
section below the fold.

- Where the row publishes `reading_eligibility.ok: false`, "Analyze drift" is inert
  (`aria-disabled`, never the stage's primary) and no Allow step is offered: the handler refuses on
  the same reason before it would ask, per
  [NUI-18](design-next-ui.md#nui-18-one-control-primitive-and-an-inert-control-stays-on-the-page).
  Directly under the button's row is one page-owned line keyed by the token
  (`NEXT_READING_PRESS_LINES`, one per `reading.PRESS_WITHHELD` token, each 12 words or fewer, walked
  by a test), and the server's own `WITHHELD` sentence, published beside the token as
  `reading_eligibility.sentence`, is under "Why it can't read". A Codex row between turns says
  "Codex sessions can be analyzed only while a turn is running." (owner Q8, 2026-10-01: Claude Code
  first). A Codex row whose turn is running is published eligible and can be pressed.
- A settling row is inert until `until`, read at render and at the press. No timer is added; the
  next collection drops the token.
- A row with no published eligibility (annotations off, or an older payload) offers the press and
  the server decides. A `200` withheld reply is held as that press's answer until the row publishes
  its own, so the inert line stands beside the button at once.
- Every account of a press sits directly under the button's row, before the hint and the
  disclosure: the refusal, this tab's last answer (including "Could not confirm the reading"), and
  a stored withhold as "Last analysis, 3m ago: <sentence>", aged from `reading_withheld_at`. The
  READING section no longer repeats the withheld sentence.

#### Amended 2026-10-02 (owner): a press shows it is working, and Analyze says when it opens or closes

The owner typed a goal and two outcome lines and pressed Save intent: "Nothing happened for a
couple seconds and then the page updated." Measured on the scratch board, the POST took about
900 ms and the first change to the page came at about 1.3 s, with Save intent a live button
throughout (arbiter spec, `ui3`).

- Save intent shows it is working. At the press it is `aria-disabled` and `aria-busy` (never
  `disabled`, which drops focus), with a spinner and "Saving…" drawn over its idle label, which
  stays as an invisible ghost so the control keeps its width. A second press, and a keystroke that
  would re-arm it, do nothing until it is answered. While it is pending the Drift line reads
  "Saving your intent…" rather than telling the reader to save it. The start is said to the polite
  region only when the request is still open after 400 ms, and the outcome only once the refresh
  has drawn it. A request with no answer is aborted at 15 s and the control comes back with
  "Compass did not answer, so this page cannot tell whether your intent was saved", never "Not
  saved", unless the refresh shows a newer revision holding exactly what was sent, which is the
  save. A 5 s backstop after the bound clears the busy state whatever the fetch did. The state is
  held by the control's focus key (`docs/design-reader-state.md`), and only the press that started
  an entry ends it, so a handler the backstop outlived cannot end a newer press's (verifier R2).
  Undo changes is inert while its save is in flight, on a redraw and on a keystroke alike, and a
  press on it does nothing, so the words being sent stay in the box (measured in Chrome, ui4).
  Escape in the goal or lines box is the same undo and does nothing then either (verifier V1).
- The Analyze family does the same. Analyze drift and Analyze again read "Starting…" with a
  spinner, solid and never hatched, until the Analyzing box is drawn. On Allow and analyze the
  question stays on screen with Allow reading "Starting…" and Not now inert, because the card is
  the consent; it closes on the answer. Keep reads "Keeping…" until its last request and refresh,
  and Cancel reads "Cancelling…" until the server accepts or answers that the job is not running.
  A lost request comes back with the control's existing sentence, so nothing stays busy forever.
- An inert Analyze says something true and actionable. No line says Analyze opens "once this
  session finishes a turn", which was false of a turn that had finished where Compass could not
  see it. Amended 2026-10-06: beside an idle row with no end, a Claude Code session reads "Last turn
  isn't recorded as finished. Run another turn to open Analyze." This names the working-turn
  path that `press_eligibility` admits, without promising a recorded finish. Codex keeps its own
  line, another harness reads "Analyze opens
  while this session runs." (or "…or once it ends." where its events reach the board), and a
  scan-only one reads "This harness sends no events, so Analyze opens only while it runs." The
  Why under it is `reading.withheld_sentence`, per harness, which names the How to use section
  that makes a board live; `WITHHELD` stays the job-time and stored sentence. A settling row's
  Why says Analyze opens by itself.
- No silent flips. When Analyze opens or closes with no press of the reader's, one short line under
  the button row says so ("Analyze is open again: the session is running.", "Analyze is open: the
  session's last turn finished.", "Analyze is open: the session ended.", "Analyze closed: the
  session went quiet.", or "Analyze closed: your intent was saved after the session
  ended."), drawn without a role and written once to the polite region, at most once a minute per
  session. A flip inside that minute is held, not dropped, and the newest is said when the minute
  is up, unless the region's last word is already the state the card shows (verifier F4). The
  close says "went quiet" rather than "stopped running", because a turn left on an open tool call
  or an interruption did not stop (verifier F5). Opening is drawn at once. Closing waits until the inert state has held for two
  payloads and ten seconds, so a session that pauses between turns, whose stop settles for eight,
  never closes it. A consent question Analyze closes under is withdrawn, "Analyze closed before
  you answered, so nothing was sent.", and never raised again without a press. A settling row
  draws a waiting dot beside "Ready in a few seconds." and opens at `until` with no new data, so
  this supersedes "No timer is added" in the 2026-10-01 press amendment: one page-wide timer
  serves the one drawn card, never a row. Levels and a scope change are not announced.
- A mid-flight analysis never looks final. On a running session the hint reads "Reads the work so
  far; the session is still running.", the Analyzing box says "Reads only the work so far.", and a
  stored reading whose scope is mid-flight leads its answer with "So far:".

#### Amended 2026-10-01: the first press is a consent step

**Superseded by DEC-28:** the prior Allow step and destination/content re-authorization below are replaced by
[opt-out with a notice](design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts)
for reader-started calls. Explicit coverage still governs unasked checks.

Owner ruling Q1, 2026-10-01 (DRC-4758 slice B). The first press asked its question by relabelling the
button "Allow and analyze" and moving it below the whole ~180-word disclosure, so the owner's walk
read it as a press that did nothing.

- The press that needs an Allow replaces the button's slot with a bordered step: the question "Send
  this session to <receiver> for analysis?", the disclosure as `route.disclosure_parts`, a short
  list in the server's order and unreworded and never inside a disclosure, then "Allow and analyze"
  (the stage's one primary) and "Not now". The parts join to the whole disclosure (a server test
  holds `" ".join(parts) == disclosure`), so DEC-21 item 1 and the account-details condition in
  SECURITY.md still hold before the consenting press.
- "Not now" sends, allows and records nothing, and brings the idle button back.
- The question takes the press's focus key, as the analyzing box's title does, so focus lands on
  it and a second Enter or the rest of a double-click cannot give consent unread. Allow carries
  `reading-allow:<key>`; Not now carries `reading-not-now:<key>` and falls back to the press's key.
- The step comes back whenever an Allow is needed again, such as a new tool-output destination
  or, since the owner's binding of 2026-10-02, a new destination for the words, when it opens
  with the server's line saying so
  ([the binding](#amended-2026-10-02-owner-the-allow-is-bound-to-where-the-words-go)).

##### Amended 2026-10-19 (owner): the first press runs and shows a notice

[DEC-28](#dec-28-a-model-may-summarize-a-session-and-the-summary-is-kept) supersedes this amendment.
The first press of Analyze drift runs the reading without a consent step and shows, once per kind of
call on this machine, a non-blocking notice naming what is sent and to which provider, with Turn off
readings beside it. "Turn off readings" (renamed Pause model calls on 2026-10-19) stays the off switch, and a reader who paused model calls is
not opted back in. This is in force once the consent change ships.

#### Amended 2026-10-01: idle, the disclosure is one worded click away

Owner ruling Q1, 2026-10-01 (DRC-4758 slice B). This supersedes the panel build's "Idle, the button
comes first and the DEC-21 disclosure follows it with the hint" for the idle stage.

- Idle, the order is the button, with the attempt count on its row ("0 requests" to the eye, the
  whole "0 model requests recorded for this session." to a screen reader), any account of a press,
  the one hint line, then the DEC-21 disclosure under a closed summary: "What is sent to
  <receiver>" until that receiver is allowed, and always while the route is a fallback, then "What
  is sent". The button stays described by the disclosure's paragraph. Pause model calls sits inside
  the summary, still on the page. Amended 2026-10-02 (NU-9): the count is a line of its own directly
  under the button row, ahead of any account of a press, because on the row it pushed "Analyze
  again" onto a second one beside Steer back and Update intent instead, which are now one row of
  the same secondary style after the primary. It reads "N model requests" in every state (idle,
  confirming, analyzing and stored), keeps the whole sentence for a screen reader, and is not drawn
  under an inert Analyze, which no press can spend. "Not accurate?" is the quiet button primitive.
- Idle sends nothing, so nothing is sent before the receiver is named. A press owed an Allow opens
  [the consent step](#amended-2026-10-01-the-first-press-is-a-consent-step), which shows the whole
  disclosure before "Allow and analyze". A press under an Allow already given sends at once, and
  the receiver it reaches was named either by that step or, on a fallback route, by the summary in
  view beside the button. An Allow given on another harness's session lets a fallback press reach
  its second provider with no step of its own, which is why that summary keeps the receiver's
  name. DEC-21 item 4 holds that way (fix round, 2026-10-01).
- While analyzing, the box stands alone with the count after it; the disclosure is not drawn,
  because the job sends nothing more.
- The summary's open state survives a redraw through `nextCockpitDisclosureAttr`, keyed by session,
  under the existing reader-state row for tier-2 caveat bodies.

#### Amended 2026-10-02 (owner): the disclosure is a short list

The owner, 2026-10-02: the disclosure "is long and arduous to read. The text should be clear and to
the point, stop overusing prose." It was 128 words for a Codex session, 239 for a Claude Code
session read by Claude Code and 202 for one read by Codex. It is now a list of one-line items, the
route's own `disclosure_parts`, still joined to `disclosure` by a single space. The first list was
75, 148 and 121 words for those three routes, in 5, 7 and 6 items, and verifier V2 found the Claude
Code one still repeating itself: the destination twice, the redaction twice, and "Claude Code reads
this Claude Code session." under a summary that names Claude Code. It is now 61, 120 and 101 words
in 4, 6 and 5 items, each said once:

1. The route's note: whose harness reads this session, and why when it is a fallback. On the
   session's own harness it reads "This session's own harness reads it."
2. `Sent:` the goal and a bounded set of the session's entries, with the reader's messages up to
   1,000 characters each. On Pi it adds the expected outcome lines when a work result is among
   them; on a harness with no work evidence the lines are never sent, so it says nothing of them.
3. On a route whose record lists checks, tool output only after it is allowed: the command,
   result and last 180 characters of output as printed, the paths written, and the expected
   outcome lines, which go only beside a check; or that none of it is sent where the destination
   cannot be named.
4. `To:` where the words go as `reading_route.destination` names it, with credential shapes
   redacted, through the provider's own CLI and sign-in, spending the reader's capacity: the
   company off this machine, or the cloud or base-URL host configured in its place, or, where
   nothing can be named, that Compass cannot name it. It follows everything it covers, tool
   output included, so it alone says where all of it goes. Until verifier C1 (2026-10-02) this
   item named the company whatever the environment said, so under Bedrock, a base URL or a unix
   socket the reader allowed one receiver and the words went to another.
5. On a Claude Code route, what its CLI adds: the working directory, platform, shell, OS version,
   date and device identifier, and under a Claude account sign-in the email address and account
   ID, which is the 2026-09-27 condition.
6. The caveat, last: a reading is a model's account of the evidence, never a verification.

Changed on 2026-10-03 by
[the agent's own words amendment](#amended-2026-10-03-owner-the-agents-own-words-are-evidence) and
its review. On a Claude Code session item 2 reads "with your messages and the agent's messages up
to 1,000 characters each, and your expected outcome lines": the lines go with the agent's messages,
not only beside a check. Item 3 no longer names the outcome lines, and both its forms say the
agent's messages may quote tool output. The Claude Code routes are now 129 and 110 words, and the
Codex route is unchanged at 61.

What was cut repeats another item or explains a mechanism: "a subprocess", "uses its own
authentication", "one of the paths that sends session content off this machine" (now `off this
machine`), and how a long record shortens the oldest messages, which sends less rather than more.
The [whole-message amendment](#amended-2026-10-01-a-reading-sees-the-readers-whole-message) said
the disclosure states that last point; it no longer does. The consent step still shows every item
before "Allow and analyze", and a test holds each fact listed above, a word budget per route, and
that no item repeats another. In the popover the paragraph under the list says only what a reading
reads ("What it reads is the evidence on this page …"), because the list has just said what a
reading is.

Idle, "What is sent to <receiver>" (or "What is sent") opens the same list as a popover, the
system the header's "Why" uses ([NUI-19](design-next-ui.md#nui-19-a-caveat-has-three-tiers)), in
place of the accordion the [idle amendment](#amended-2026-10-01-idle-the-disclosure-is-one-worded-click-away)
drew. Analyze drift stays described by the list, and Pause model calls stays inside it.

### What the Cancel build decided, 2026-09-24

DRC-4693 built Cancel, the rest of item 5. The owner ruled the spend, the unconfirmed kill and the
new strings on the issue; the other calls were made within them.

- Where the cancel lands decides the spend, and the line is the reservation itself: the job takes a
  commit point under the lock a cancel takes, immediately before it reserves. A cancel accepted
  before that point is unspent, reserves nothing and spawns nothing, and the stored
  sentence is "The analysis was cancelled before anything was sent. Nothing was sent or spent." From
  the reservation on it is spent with no refund, whether the call was still to be spawned, running,
  or had already replied: whether the provider billed a killed call is unknowable, and a refund
  would make press-then-cancel a loop around the cap. That sentence is "The analysis was cancelled
  before it finished. Nothing is shown from it, the attempt still counts, and a fresh press is the
  only retry." It says "nothing is shown", not "nothing was produced", because a reply may have
  arrived and been discarded, and it never says "you cancelled", because a forged local cancel reads
  the same. Counting every cancel as spent was the simpler alternative, rejected because it records
  a charge the budget never made. The first build checked the flag and then reserved, so a cancel
  landing in between was charged (review F1); the commit point closes that gap.
- The flag and the handle are read under the flight lock, by the cancel and by the spawn's handover
  alike, so a cancel that lands between the spawn and the handover is seen by one of them. Without
  that, a cancel in that gap found no process to kill and the CLI ran to completion.
- The route never waits for the reap. It sets the flag and kills without blocking; the call's own
  wait looks up every 0.1 s, then kills and reaps with the 5 s bound. A kill that cannot be
  confirmed in that bound records `unstopped` ("may still be running") and frees the slot, as the
  timeout and shutdown paths do. That departs from "only after the child is reaped"; a slot held
  forever would answer every later press `in-flight` until a restart.
- The outcome is decided at a seal just before the write. A cancel before it wins over whatever came
  back; a cancel after it answers `not-running` and changes nothing, because the result is already
  being stored. A cancelled job never lights "Checking the reply".
- Precedence: `unstopped` first, then the stop's own word (`interrupted`, or `stopping` when nothing
  was sent) over a cancel made after the shutdown began, then the cancel over a failed or finished
  call. The stop's word stands only where the stop reached the call first. A shutdown that begins
  just after the model seam's own `closed()` check, followed by a cancel before the commit point,
  records `cancelled-unsent`. Nothing was reserved, so the count still equals the charge. (Amended
  2026-09-27: with no cancel that job now records an unspent `stopping` too, because the
  reservation finds the runner shut; see "What the accounting build decided" below. Before that it
  reserved and recorded a spent `interrupted`.)
- `cancelled` is a kept marker reason, so a store that refuses it never recovers as "The analysis
  ran", and the cancel writes that reason into the marker, so a dashboard that dies before the
  write records the cancel at its next start.
- Its own route, `POST /api/reading/cancel`, naming the job id, rather than a field on the reading
  route. A stale tab cannot cancel a newer press, and no job, another job's id and an unknown
  session answer one `409 not-running` body.
- A job leaves the board only after its outcome is stored, and a collection samples the job
  registry before it reads the store, so one collection shows the job or its outcome and never
  neither. The job's final publish clears the snapshot under the collect lock, so a collection that
  was already running, and read the store before the write, cannot stand as the fresh snapshot
  afterwards. The live walk measured that stale body for about the snapshot floor: no box, the
  previous sentence and the previous count.
- On the page, Cancel sits in the box's header row. The press button's focus key moves to the box's
  title (`tabindex="-1"`), not to Cancel, because a keyboard press followed by a second Enter on
  Cancel cancelled the analysis it had just started, a spent attempt. Cancel has its own key and a
  fallback to the press, so focus lands on the press when the box goes. While a
  cancel finishes it keeps its label and is disabled, driven by the published `cancelling` flag so a
  reload draws the same. A lost answer says "Could not confirm the cancel. The analysis may still be
  running; refresh to check." The design goes straight back to idle with no sentence; the stored
  sentence is the ruling's addition.
- "Turn off readings" (renamed Pause model calls on 2026-10-19) does not cancel a running job in this layer: a withdrawal after the spawn does
  not stop a call already sent, and that is a separate decision.

### What the accounting build decided, 2026-09-27

DRC-4712, DRC-4713 and DRC-4667 made the count equal the charge on the paths the two builds above
left open. The owner ruled the stop's line, the ledger, the oversized token and its sentence, and
the poll-fallback limit on DRC-4713.

- The stop's line is the reservation, the same as the Cancel's. The reservation's insert and
  commit run under the lock `supervise.kill_all` takes, after SQLite's write lock is held, so a
  shutdown lands wholly before the charge or wholly after it. Before it, nothing is written, the
  seam answers as the stop it was, and the stored sentence is `stopping` ("Nothing was sent or
  spent"). After it, the attempt is spent and records `interrupted`, even when nothing had been
  spawned yet, as a cancel after the reservation is. The seam's early `closed()` look stays as the
  cheap path. The first build charged a shutdown that landed between that look and the reservation
  and then refused to spawn: one attempt counted for a call never sent. A refund on a certain
  non-send was the alternative, rejected because it would be the first refund path and would treat
  the stop and the cancel differently.
- A job ledger replaces the recovery trade-off. The reservation commits the job's id in a
  `spend_jobs` table in the same transaction as the charge, so no crash point separates them. It is
  a table and not a column on `spends`, because an older build's `INSERT INTO spends VALUES (?)`
  fails against a second column, and after a rollback every press would be refused. Rows are kept
  for 30 days, far past the budget's day, so a restart long after a crash still finds its row. A
  marker says it came from a build that reserves under the job's id. Recovery counts that marker's
  attempt as spent only when the ledger holds a charge for the id. When the ledger holds none, the
  marker recovers unspent, as `stopping`, or as `cancelled-unsent` when the marker says cancelled.
  When the ledger cannot answer (no store, no SQLite, a store from before the ledger, a marker older
  than the rows kept, or a marker from a build without the ledger), the attempt counts as spent, as
  it always did, because dropping a charged attempt is the loss Q2 ruled out. Rewriting the marker
  after the charge was the alternative, and it only moves the window: a death between the commit
  and the rewrite leaves a charged attempt uncounted.
- An output file past 1 MiB stops the call. The wait looks at the output file's size every
  0.01 s while the CLI runs, and once more after the group or Job Object has no live writer
  (DRC-4729). Watched POSIX cleanup keeps the leader unreaped while it observes group states;
  Windows waits for the Job Object's active-process count to reach zero. An uncertain or timed-out
  observation refuses the reply. The documented poll fallback cannot prove this quiescence. Past `observer.OUTPUT_FILE_LIMIT_BYTES` it kills the CLI's group or Job Object the way a
  Cancel does. The slice was 0.1 s in the first build, and an unpaused writer put 286 to 600 MiB on
  disk before the first look; at 0.01 s it measured 41 to 89 MiB. A CLI that wrote past the bound
  and exited inside one slice first read as an ordinary reply, which the look after the exit
  closes. The goal lane falls back on an oversized call as on any failure and records nothing. The outcome is a spent `oversized` attempt ("The reading was stopped because its CLI
  wrote far more output than a reading can use. Nothing was produced, the attempt still counts, and
  a fresh press is the only retry."), and `oversized` is a kept marker reason, so a store that
  refuses it never recovers as "ran". The bound is deliberately far above the 8 KiB read cap, since
  a reply past the read cap is salvaged as cut rather than failed. `RLIMIT_FSIZE` was rejected
  because it applies to every file the CLI writes, its own logs included, and has no Windows
  equivalent.
- The poll fallback's limit is documented, not fixed. When neither `waitid` nor kqueue can
  watch an exit, the call polls, and the poll reaps the leader, so helpers left in its group after
  a normal exit are not swept. A timeout, a shutdown or a Cancel still kills the group first. It has
  been seen only under forced errors, and a test pins it so the documents change if it does. On
  that path a helper still writing after the leader's exit is not reached either, whether it was
  already writing under the bound or starts afterwards, since the poll that sees the exit is the
  reap. The size is looked at before each poll, so a writer caught
  while the leader runs is killed with its group. Seeing the exit without reaping would need a third
  watcher (libc `waitid` with `WNOWAIT` through ctypes on macOS, measured working), which is the
  fix this ruling declined.
- The ledger answers "no charge" only for a job that started after its watermark. The watermark is
  the ledger's creation time, raised to 30 days back on every prune, so a row pruned under a clock
  that ran ahead and was then set back, or a store deleted and made again after the crash, reads as
  "cannot say" and the attempt counts. Without it, the first review measured a charged attempt
  recovering as unspent after a prune at a later wall clock. A row that exists answers "charged"
  whatever its age.
- Precedence among the spent words: `unstopped` > `cancelled` > `oversized` > `interrupted`. "May
  still be running" is the one sentence nothing hides. A cancel before the seal still becomes the
  cancel, as it does over a finished reply. A shutdown after a flood kill keeps `oversized`,
  because that kill came first and the file did pass the bound. All four are spent, so the order
  never moves the count. The owner accepted it on 2026-09-27.
- On Windows the prompt is fed from a thread, and the call waits with `process.wait`. CPython's
  Windows `communicate` writes stdin on the calling thread before any timed wait, so a CLI that
  never read a prompt larger than the pipe held the call past its own timeout.

### What the panel build decided, 2026-09-24

DRC-4680 built items 1 and 14 on the session page: the Intent and drift panel beside the session's
activity. The owner ruled the first three calls below on the issue; the orchestrator made the rest on
the analysis's recommendation.

- The harness limit replaces only the level and meter. "Compass can't read work from this harness"
  stands in the level's slot on every harness except Claude Code and Pi, and `Analyze drift` stays
  wherever the route names a reader, because DEC-21 item 4 still lets Codex read a Codex session.
  Never on Pi, whose work results are read, so the sentence would be false there. The observed
  record's old line "Compass reads those on Pi alone" is retired for the same reason: Claude Code's
  checks are read too.
- On Antigravity the limit stays true because only the person's typed directions are read, never
  its work (owner, 2026-09-27, DRC-4689). Those directions give a pressed reading something to read
  against. They do not give item 2's goal draft a first prompt there: nothing produces
  `first_prompt` for Antigravity, and prompt adoption is Claude Code and Codex only. On a harness
  with no observed-record reader, the press withholds with `no-record-reader` rather than saying
  the record is empty. The page's
  record column still prints "No entry in the observed record names this session." for those
  harnesses, because it reads `omitted` and not `sources.work.unavailable`; that is a web
  follow-up.
- With no reader on this machine, the route's reason replaces the button. The four no-producer
  tokens and an unpublished route draw no inert button, which narrows NUI-18 for this one case
  ([An inert control is present and refusing](design-next-ui.md#an-inert-control-is-present-and-refusing-never-absent)).
- Idle, the button comes first and the DEC-21 disclosure follows it with the hint, and the button is
  described by it. Confirming, the disclosure stays before "Allow and analyze", so the press that
  gives consent still follows the text naming the receiver.
- No meter, no header pill and no "Not checked yet" before a level exists (DRC-4695, DRC-4696). The
  design's idle title becomes false the moment a reading is stored, and a grey scale drawn with no
  level behind it reads the same on every session whether or not anything was read. Amended
  2026-10-01 (owner, Q2, DRC-4758): with a saved intent and no level from any source, and no
  reading stored, "Not checked yet" stands over the unlit four-segment meter and its labels
  ([the result in the button's place](#amended-2026-10-01-the-result-takes-the-buttons-place)).
  The pill stays level-only.
- The header shows the state in Compass's own words (working, needs input, idle), not the design's
  "Running", which would rename a state across the product from one page.
- The panel is not a scroll container and is not sticky; the page scrolls as one document, so the
  reader-state inventory gains no row. The panel comes first in the markup and the stylesheet places
  it in the second track, so it leads the single column below 1100px with no reordering trick.
- CURRENT ACTIVITY leads the activity column rather than sitting in the panel. The ask block stays
  full width above both columns, because the reader's answer outranks the check.
- The reading offer said "the observed record below", which was true of the markup and false to the
  eye once the record moved to the other column. It now names the column.
- One primary per stage: `Analyze drift` when idle and under a stored reading (DRC-4695 and DRC-4681
  change that later), "Allow and analyze" while confirming, none while analyzing and none with no
  reader. Amended 2026-10-01 (owner, Q3, DRC-4758): under a stored reading the result takes the
  button's place, "Analyze drift" is not drawn, its one "Analyze again" is secondary, and Steer
  back is that stage's primary where a departure stands. Amended 2026-10-12 under DEC-27:
  a current result has no run control; a stale result keeps one with its reason in the callout.
- No Stop session control (DEC-16).
- The fold, measured on a live board at 1440x900: the first build stacked the header one element
  per line (205px) and put Analyze drift's bottom at 1022 on a Claude Code session and 1085 on a
  Codex one, about 115px lower than the one-column page. Following C1's compact header, the header
  is now two rows (state, name and id; then the measured line with the copy controls), the
  revision stamp and "Each save is a revision." share one line, and an outcome line's box shares
  its row with its count and remove. That put the bottom at 820 and 879 with nothing removed. C1
  gives the aside no visible heading, only its "Intent and drift" label, so none was added.
- The fold criterion, reworded by the owner after review: "Analyze drift sits above the fold at
  1440x900 with a goal and up to three outcome lines (the design's textarea footprint); with more
  lines the Drift heading stays above the fold." The owner then scoped it to a session with no
  question waiting (2026-09-24). A waiting question runs full width above both columns, about
  183px with a one-line question, and while it waits answering it is the primary and Analyze drift
  is not; measured with one open, a goal and three lines put Analyze drift's bottom at 964 (Claude
  Code) and 996 (Codex). The owner's fix for the lines themselves: every
  saved line is one row of about one control height. The line grid had three tracks for four items
  (box, count, source, remove), so a saved line's source pushed remove onto a second row and each
  line cost 85px; it now has a track per item. That alone left a goal and three lines at 926 on a
  Codex session and six lines' Drift heading at 1018, so each field's count and controls moved into
  its heading row (before the box, in reading order as on screen) and the panel's gaps tightened.
  Measured at 1440x900 with a 198-character goal: three lines put Analyze drift's bottom at 788
  (Claude Code) and 820 (Codex); six lines put the Drift heading's bottom at 900 on both, with no
  margin, because the six-line notice ("An expected outcome holds six lines...") appears only then.
  Amended 2026-10-01 (owner, Q4, DRC-4758): the criterion is now that the Drift level and the
  Analyze control are visible at 1440x900 with a goal and up to three lines, under the roomier
  boxes of [the intent editor's boxes, buttons and footer](#amended-2026-10-01-the-intent-editors-boxes-buttons-and-footer).
  Amended 2026-10-02 (owner, ask 3): each outcome line is its box, then one row under it with the
  count on the left and Remove on the right, the Goal's own pattern, and a typed line names no
  source. That supersedes the one-row line above and Q4's fold arithmetic, and the owner ruled
  that the ask wins wherever the figure lands. Measured in Chrome with the page laid out at
  1440x900 CSS pixels, on a scratch board serving the assembled page against the panel tests'
  fixture (a 39-character goal, three lines, one added from an entry, Live monitor drawn): Analyze
  drift's bottom moved from 1135 at `5d95ac09` to 1273, about 46px per line. Both are under the
  fold on that fixture, so the 2026-10-01 criterion does not hold for it before or after the
  change; this is reported rather than worked around.
- The saved-intent introduction follows the complete action block (DRC-4748). With a saved
  55-character goal, three 240-character outcome lines and a High live estimate, its three
  lines above the fields put Analyze drift at 892.5 to 936.5 on a 1440x900 board. Moving the
  same words below the action put its bottom at 861.5. The drafted introduction stays with
  the fields the reader is choosing; consent disclosures keep their own order.
- The heading-row move is an owner-approved departure from C1's placement (2026-09-24): each
  field's count and controls sit beside the field's name rather than under its box. Reversed
  2026-10-01 (owner, Q6, DRC-4758): the reader could not tell which box a save belonged to, so
  each field is its label, box and counter again, with one footer under both
  ([the intent editor's boxes, buttons and footer](#amended-2026-10-01-the-intent-editors-boxes-buttons-and-footer)).
- One clean row, expand on focus (owner, 2026-09-24). A saved line longer than its box wrapped and
  showed a half-cut second row, and the goal box a half-cut third. At rest a line box is one
  unwrapped row ending in an ellipsis, and the goal box exactly two whole rows, with no bottom
  padding for a third to show through. On focus each grows to its full text (`field-sizing:
  content`) and returns on blur. It is CSS alone, so the expansion follows focus through a redraw
  and the reader-state inventory gains no row; resizing is off, because a dragged height is an
  inline style the redraw would restore over the focus rule. The value and its count stay the
  whole text. Measured at 1440x900 with a 198-character goal: three lines put Analyze drift's
  bottom at 781 (Claude Code) and 813 (Codex), and six lines put the Drift heading's bottom at 893.
  A focused 102-character line grows to its full text at 1440, 375 and 320 with no horizontal
  overflow. Where an engine lacks `field-sizing` (it ships in Chromium), an `@supports not`
  fallback gives a focused line four rows and the goal six, and the box scrolls inside them.
  Superseded 2026-10-01 (owner, Q4, DRC-4758): the boxes rest roomy and resize vertically, and the
  focus rules are gone ([the intent editor's boxes, buttons and footer](#amended-2026-10-01-the-intent-editors-boxes-buttons-and-footer)).
- At 760px and below, the sheet's existing narrow step, a line's box takes the whole first row and
  its count, source and remove follow on a second in the same order. Sharing one row, the box
  showed about 12 characters at 320; it is now 292px wide there and 327px at 375. At 1440 and 1100
  a line is still one row, so the fold numbers above do not move. Superseded 2026-10-02 (owner, ask
  3): the box has a row of its own at every width, so the narrow step keeps only the source's
  wrap.
- The goal's heading row is top-aligned, with the label and the count each one control tall, so an
  open prompt menu no longer leaves the count, clear and save floating beside its entries
  as though they were its controls. Since 2026-10-01 (owner, Q6) the count and Clear sit under the
  box and the save in the footer, so the heading holds only the label and the prompt marks.

#### Amended 2026-10-01: the intent editor's boxes, buttons and footer

Owner rulings Q4, Q5, Q6 and Q11, 2026-10-01 (DRC-4758 slice D1), on the owner's walk: the goal box
was two rows and each line one, neither resizable; "clear", "save", "add a line" and "remove" read
as bare text; and nothing said which box a save belonged to. This supersedes the heading-row move,
"One clean row, expand on focus" and the goal heading row's alignment above, and rewords the fold
criterion.

- The boxes (Q4). The goal rests at three rows and each outcome line at two; both wrap and resize
  vertically. A dragged height is an inline style that `nextCaptureInputState` carries across a
  redraw (the reader-state inventory's resized-dimensions row), which a test holds, so no rule
  sets a height that follows focus: the at-rest and focus pair put the box back over the drag on
  every blur, which is why resizing had been off. The untouched draft and the pending line still
  size to their text, and an inline height still outranks that. Fold criterion: the Drift level
  and the Analyze control are visible at 1440x900 with a goal and up to three lines.
- The controls (Q5) are the next-action primitive, secondary or quiet and never primary: Save
  intent is secondary; Undo changes, Clear and + Add a line are quiet; a line's remove is a quiet
  "×" named "Remove line N". Clear stays the lightest weight against the discard control's box and
  its armed 2px border, so the irreversible act still reads heavier (DRC-4590 AC-5, kept as a
  weight comparison). The field's own bare-button rule steps aside for the primitive.
- The layout (Q6). Each field is its label, its box and its counter. Clear sits under the goal box
  and + Add a line under the list. One footer under both fields holds the hint "Drift is measured
  against these. Edit anything that is off.", said once whether or not the goal is drafted, then
  Undo changes and Save intent, both inert while nothing has changed (NUI-18). The groups stand
  22px apart.
- Save intent writes both fields in one `POST /api/annotate`: `goal` where the box left the stored
  words and is not back at the draft, `lines` and `origins` where the list changed, and an absent
  or null field is left alone, with the revision both were drawn against. Over an untouched draft
  with nothing else changed a press adopts the draft, never a typed save of an excerpt. Undo changes
  is Escape for both fields at once. Its cue is one, in the footer. Amended 2026-10-02 (owner):
  Save intent is enabled over an untouched draft, since it is now the draft's only save; Looks
  right is gone.
- Absence (Q11). An empty field's absence is its empty box and placeholder. The sentence ("No goal
  typed for this session.", "No expected outcome typed.") stays in the DOM, visually hidden, as
  the inert save's description. The store-unreadable sentence stays in view, because it says the
  words may exist where the box shows none.
- The stamp over saved words reads "Saved", not the design's "Confirmed": a saved revision is the
  reader's own words, and nothing confirmed them.
- Not built here, noted as follow-ups: one multi-line Expected outcome box (the rows stay, drawn as
  one checklist); Enter, Backspace and multi-line paste splitting lines (IE-7); the "Use your
  prompt" menu, which is slice D2.
- The header chip says "needs input" whenever a question is waiting, whatever state the collector
  inferred. After `session_ended` pops the overlay, the state falls back to the collector's
  `working` or `idle` while the ask stays open, and the chip read "working" beside "ended".

#### Amended 2026-10-01: the session page's text is tiered to a word budget

Owner, 2026-10-01 (DRC-4758 slice E; Q9 of the decision block, and the complaint "so much text it
is unclear where to look"). The panel is held to a measured budget, counted by the shared
visibility helper with the boxes' own words left out: an idle-drafted aside on Claude Code with
consent given shows no more than about 90 words (79 at this build), and an aside under a stored
reading no more than about 160 (96 at this build). Every sentence moved to meet it stays in the
DOM behind a worded summary, under tier 2 of
[NUI-19](design-next-ui.md#nui-19-a-caveat-has-three-tiers); absences and anything the reader acts
on stay in view.

Amended by the owner on 2026-10-04: coverage belongs beside the answer, before the intent rows,
because an answer read from part of the window must not look like a reading of all of it. The
message-tail start, the minutes outside it, omitted passes or writes, checks with no room and an
adopted-source fallback stay in view when applicable. An older reading says its coverage was not
recorded. The existing stored-reading fixtures now show at most 167 words outside field values
(170 ceiling); the partial-tail fixture with three intent rows shows 248 (270 ceiling). Its
needed coverage and row labels account for the extra text. The full cutoff and general scope
remain behind "What it read". This amends the tiering pass, not the evidence rules.

The same owner approval requires the saved window beside the save and the prompt menu to remain
available when its source has left the live tail. With those controls, the stored fixtures show
at most 174 words (175 ceiling), the idle fixture 82 (85 ceiling), and the partial-tail fixture
255 (270 ceiling). The window explanation stays inside "Saved"; the menu loads when opened.

- What a reading is (the offer that opened the READING section) sits inside "What is sent", after
  the provider disclosure, while no reading is stored; where no disclosure is published it sits
  behind "What a reading reads". The READING section is drawn only for a stored reading this build
  could not read, and that sentence stays in view. A malformed reading keeps the section.
- The introduction sits behind "What analysis does". Amended 2026-10-06: a saved goal gets
  "When you analyze drift, Compass lists where this session departed from your saved goal."
  A row without a saved goal
  keeps "Choose a goal or use your prompt, then analyze drift..."; an unsaved prompt draft is
  not described as saved. Amended 2026-10-02 (NU-10): under a stored reading the introduction is
  not drawn, because the step it explains is done. Amended 2026-10-11 by
  [DEC-27](#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result): the
  "What analysis does" disclosure is replaced by the "How Intent and drift works" popover beside the
  Intent heading; one explainer, not two.
- The later-direction block is one summary naming its state: "Later directions: none since your
  save", "Later directions: settled 5m ago", or "Later directions: unknown (record unread)". The
  unread state is in the summary, so it is never a silent all-clear
  ([DEC-20](#dec-20-the-first-screen-shows-goal-beside-direction-and-drift-has-one-home)); the
  state sentences and the steer paragraph sit behind it.
- "Discard everything" is a summary holding the server's why, the `Discard everything` control
  (its summary's own words since NU-20, 2026-10-02; armed, it reads `Confirm discard`)
  and, once armed, its warning. Armed, it is drawn open and outside the restore lane, so a redraw
  cannot shut the warning that describes the armed control (DRC-4564). The account of a landed or
  failed discard stays in view.
- Departures (Q9). The section is drawn only where the unasked lane holds rows, collapsed under
  "Raised while you were away: N", and holds the definition, the rows with their ways back, how
  each was raised, the counts and the steer paragraph. With the lane on and nothing raised, the
  lane's own sentence (not checked, checked and found nothing, or a cap spent) stays in view with
  the rest behind "About these checks", because those are three facts and silence reads as the
  reassuring one. The reading's departures are said once, in the result: the section's "From the
  reading you asked for" part, its "No reading has been made at your request" sentence and its
  per-departure way back are not drawn, and the reading's cutoff moved into "What it read". The
  result-placement bullet's "a malformed reading, a refused one and no reading keep it" now reads
  "a malformed reading and a refused one keep it".
- The activity column beside the panel is tiered the same way (328 visible words to 125 on the
  idle-drafted fixture). Under the record, where the harness's work results are read, one clause
  stays in view ("Results are as the tool reported; not inspected.") and the mix, the bounds, the
  check scan and the full limit sit behind "About this record"; where none are read, the limit is
  the absence and stays in view. The route's tool-output sentence is said once on the page, in
  "What is sent"; the record's line no longer repeats it. The facts keep NEXT STEP and BLOCKED in
  view and put TURN, OUTCOME, GIT STATE and PROJECT behind "Session facts: <outcome> · <git
  state>", because HOW IT LANDED says both again; a block note that only restates its value
  ("Reporter available", "No block-state reading available") is not drawn, here or on the
  Sessions list. Command-shape reports, on the session page, are one summary while off or
  unsupported, and the list or "No command-shape reports." with the caveats behind "About these
  reports" while on; Attention keeps its whole section. DEC-27 removes the resume absence and
  its explanation. A missing terminal is one clause beside the header's controls
  ("No terminal to raise", "Terminal raise off"),
  said once per page before any departure (DRC-4658), with the cause behind "Why". HOW IT LANDED
  keeps "Neither card implies the other." in view with its reason behind "Why two cards", and the
  Intent-log pointer is the link with what it keeps behind "What it keeps".
- Not built here, noted as follow-ups: a per-row source behind a row-level disclosure; the ended
  note's shorter form; "Run setup" beside an off command-shape section; the same tiering on
  Attention's command-shape section.

### What the numbering build decided, 2026-09-25

DRC-4694 built item 11 and item 6's flags in the session's activity. The owner ruled the first four
calls below on the issue; the rest follow the analysis.

- What is numbered. With no saved intent, or with the annotation store off, the whole record is
  numbered from its first timed entry. With one, #1 is the first entry at the evidence-window start
  (item 13). Earlier entries are counted ("2 earlier entries") and not listed. An entry with no
  published time cannot be placed in a window, so it is counted the same way and never numbered.
- A cited entry from before the window, or with no time, is listed anyway, unnumbered: a
  pre-window one with its time, an untimed one with neither. Whether a reading should cite a
  pre-window entry at all was filed separately, and ruled on 2026-09-27: it may not
  ([what the window build decided](#what-the-window-build-decided-2026-09-27)). This path now serves
  a reading stored with no window start, and a check whose result landed inside the window though
  its call began before it, since numbering stays on the call time.
- A window that opens at a reader's message should have an entry at that moment. Where none sits
  there because the record read no longer reaches back that far, the list says so rather than
  calling a later entry #1. A window at the save time is typed words with no earlier message, and
  nothing is expected there.
- Until 2026-10-14, numbers were stable only while entries arrived at the end
  ([superseded](#amended-2026-10-14-owner-an-entry-keeps-its-number)). Four things renumbered every entry after
  the one that moved: a check re-runs, because the check tracker publishes one entry per check keyed
  by its latest run; a file is written again, because the latest write is kept; the listing of at
  most twelve checks and files reshuffles, because failures are kept first and a new one can evict a
  pass from the middle; and the observer snapshot moves with each snapshot. A fifth since
  [2026-10-03](#amended-2026-10-03-owner-the-agents-own-words-are-evidence): an agent message
  leaves the transcript tail the board reads, and since it is never stored in the session history
  it used to drop out of the list and the entries after it renumbered. Record pages now keep loaded
  messages for the open session page, independently of that tail. Loading older messages in the
  intent window can renumber every entry; the list says "Numbers count from the oldest entry loaded."
  After leaving, the next opening starts with the newest page. A departure citing an unloaded entry reads
  as citing nothing resolvable, with the generic sentence: a citation is a hashed fact id, so the
  page cannot tell that the entry it named was one of the agent's messages. The list and every
  citation are recomputed together on each render, so the screen never disagrees with itself, and
  item 7's correction carries times as well as numbers. A server-published ordinal per fact would
  fix this and is a Python layer of its own.
- Order is time, with the fact id breaking a tie, so two checks with one call time number the same
  whatever order the payload sent.
- "Cited" comes only from the current stored reading's departures that survived every page rule, and
  each criterion row now carries the ids it still rests on. A demoted departure, a consistent row, a
  refused or malformed reading and a replaced one flag nothing. A consistent row's entries are listed
  and not flagged.
- "A later direction you gave" is a person's entry after the words' own time, read by the same
  predicate the conflict block narrows to the unsettled ones, so the two cannot disagree. It stays
  flagged once settled, because settling says the baseline still applies, not that the direction was
  never given. It is never called drift (DEC-16).
- The readability bound was retired on 2026-10-12. Opening reads the newest fifty message entries and
  the newest page is read again when the session's activity changes, so a message that arrives while the
  page is open stays listed after the board's 400,000-byte tail moves past it; Show more alone reads each
  older page. Every loaded timed entry in the window is listed, and every
  check and file in the window. A check or file from before the window is counted with the earlier
  entries and not drawn, where every listed one used to be. When nothing is numbered but the record
  holds earlier or untimed entries, the list says no entry is from after the window opened (or that
  none has a time) rather than that the record names nothing. Every entry a departure cites is drawn as well, at its own number, so the gaps in
  the numbering show and no expand control is needed for a loaded citation. Revealed entries and
  open later directions are listed as well. Older message pages exist only after Show more; once
  they reach before the intent window, the list says "Everything since your intent's window opened
  is listed." and stops offering invisible older rows.
- The list sits right after CURRENT ACTIVITY under the column's "Session activity" heading, and the
  OBSERVED RECORD heading is retired. The header's second row says "N entries" and omits the count,
  rather than showing 0, when the record was not read.
- The design's strings this replaces: "Key turns" is gone; "Drift began", "Off goal" and "Breaks
  outcome" become "Cited" or "A later direction you gave"; "In progress" is the source's own words;
  an entry is one fact, so "2 files" and other per-turn counts are not drawn. Your message reads
  "You · Prompt", the agent's entries "Agent", and Compass's own summary of the session "Compass's
  summary", never the agent.

#### Amended 2026-10-14 (owner): an entry keeps its number

The bullet on stable numbers above is superseded for a Claude Code session whose own context has loaded. The owner
ruled that numbering counts the session, not the page: #1 is the oldest message of the session and
#n the newest, so a number is fixed and does not move. The server publishes
the position and the page draws it.

- A message is numbered by its rank among every message in the session, oldest first, ordered by
  time with the fact id breaking a tie, the order the page draws them in. It reads `#41`.
- A check or file takes the number of the message it follows and its place after that message:
  `#41.1`, `#41.2`. The label sorts `#41` before `#41.1` before `#42`. The place counts every
  check and file the transcript read holds, listed or not, so the listing of twelve evicting one
  leaves a gap and moves nothing after it. A check that runs again keeps the place of its first call,
  and a file written again keeps the place of its first write. This is why a re-run check can sit
  out of order on the screen: the list is still drawn by time, and the label is where the entry first
  appeared.
- The correction carries the same label: "A check failed at 13:58 (entry #41.2 in Compass's
  activity list)." The server counts a placeholder at its widest, now `#999999.9999`, so a
  correction within a few characters of the 2,000 cap is refused slightly earlier than before.
- Numbers survive a poll that displaces a check or file, a check that runs again, and Show more.
  A correction composed before Show more still names an entry the list can find afterwards.
- Where no fixed number exists the page counts what it holds from the oldest, as before, and says
  "Numbers count from the oldest entry loaded.": every other harness, and a Claude Code session
  until its own context has loaded, because the project context carries none for a session that is
  not the focus. An entry in the window that the server numbered nothing for (a workflow fact)
  is drawn without a number rather than with a wrong one.
- The anchor sentence for a window that opens where no entry sits is not drawn with fixed numbers,
  since #1 is no longer the first entry after the window.
- Held as known limits. A message written late with an earlier time lands in the middle of the
  order and moves the ones after it, which a resumed transcript can do and nothing else does. The
  check tally reads the newest 8 MiB of the session's transcripts, so where a gap spans that edge
  the oldest entries' places can change. A message index that cannot finish reading inside its
  allowance publishes no numbers at all, never a partial rank, and the page counts what it holds
  for that read. The first request on a long session pays one forward pass, measured at 0.18
  seconds for a generated 63 MB transcript, and later requests read only what the transcript
  gained. [The paging record](design-session-record-pages.md#fixed-positions) owns the index.

#### Amended 2026-10-14 (owner): a press says it in one line, what is sent reads as a list, a cited entry is tinted

Three things on the Session page's Drift card read badly with real data, and each was fixed without
removing a word a reader is owed.

- The answer to a press (Keep, Add it to my intent, Use this as my goal) printed under its button as
  a whole sentence, which moved every control beside it and wrapped to seven lines in the narrow
  column. It is now one short line with an info mark ("Direction unverified", "Direction out of
  reach", "Record changed, press again", "Intent kept"). The rest of the sentence opens from the
  mark on hover and on a press (Enter or Space from the keyboard). The whole sentence stays in the page for a screen reader as
  the button's description and in the polite region, so the popup is never the only copy. It is a
  popover and not a tooltip because the sentence is an outcome and a tooltip does not open on touch.
  An answer with no short form keeps its first sentence, cut at a word.
- Where Keep may analyze under an Allow already given, the direction question printed the whole
  disclosure as one paragraph: the form the owner called long and arduous on 2026-10-02, kept in
  that one place. It now uses the "What is sent" popover the idle Analyze button already has, with
  the server's parts unchanged and in order. The consent step still shows every part, before "Allow
  and analyze". In every place the list is drawn, an item that opens with its own label ("Sent:", "To:",
  "Tool output, only after you allow it:") sets the label in weight, so it reads as a short form.
- "Show cited entries" marked the cited entries with a line of text inside each row, which was hard
  to find in a long list. Each cited row is also tinted across and edged in the accent colour.

Rejected: a tooltip for the press answer (unreachable on touch), and folding the consent step's list
behind a disclosure (its ruling is that the whole disclosure is in view before the press that is the
consent).

### What the direction-adoption server build decided, 2026-09-27

#### Amended 2026-10-04: owner, any listed direction may be selected

Owner, approving the Analyze drift plan, 2026-10-04. A direction retained in history was listed
but Add could not open its source once it left the live tail. Add now verifies any listed
direction against its bounded source record. The question preselects the newest unsettled
direction and lets the reader select another. "Use this as my goal" fills a pending adoption,
asks whether to keep standing outcome lines, and waits for Save intent. A refused or too-long
Add offers that choice; its line editor says "Write the rule, not the moment". The menu's five
choices are resolved only when opened, under the same source checks as adoption.
They retain known source clipping after whitespace folds. The source-list cap limits returned
facts, not ambiguity checks against their identities within the consumed source ranges.
The [long-session lookup](#long-session-direction-and-prompt-reads) owns the current bounds.

A stored reading keeps the baseline it read: only unsettled directions at or before its
`read_at` demote its intent rows, answer, level and correction. A later message instead labels
the reading as preceding that message. The live monitor still considers all later directions.
The current-arm replay previously used wide drafted windows; those results do not measure the
window narrowing of the old lines-only save. The [window count](drift-replay/windows-stage3.json)
compares the two listings without a model call. Typed outcome lines have no stored source time;
a guard against judging earlier work against a newly added line needs that lineage first.

DRC-4682's server half built item 4's two answers and the store they write. The owner ruled that
Add over an unsaved draft adopts it in the same write, and that Keep settles even where no analysis
can start. The page half comes after it.

- The wire. Opening a direction is its own route, `POST /api/direction`, because it answers with
  text rather than the annotate reply. Saving it is the `add_direction` field of
  `POST /api/annotate`, beside the settle arm, because it writes the same annotation and answers
  the same way. SECURITY.md states what the open returns and to whom.
- What counts as later. A person's message in the session's own record after the words' own time:
  an adopted goal's source time, the time a typed goal's words were saved, and with no saved goal
  the draft's time, the first prompt or else the latest. A revision holding lines and no goal still
  counts as no goal. The typed goal's save time is its own stored field, `goal_saved_at`, published
  as `annotation_goal_saved_at`: a lines-only save and an added direction mint a revision without
  moving it, and only new goal words do. Review found that flooring typed words at the latest
  revision instead meant adding one direction hid a later one the reader never answered, where
  adopted words kept it open; the two now behave alike. A revision an older build saved has no
  such field and falls back to its save time.
- The text. As amended on 2026-10-04 above, it is read again from the bounded source by recomputing each message's fact id,
  because a Claude user message carries no record id. The id was not changed to add one: that
  would move every stored citation of a Claude message. A message absent from that source is refused
  with one sentence, never replaced by its clipped summary. The open returns the whole message
  scrubbed as a save would scrub it, up to 2,000 characters, with a clipped flag and the store's
  own answer to whether it fits as a line. The record reader cuts a message at the same 2,000
  characters first, so raw text that reaches the bound counts as clipped; one of exactly 2,000 is
  flagged too, which says less was shown than was, the safe error.
- One refusal body. An unknown session or fact, another session's entry, one that is not a
  person's message, one not later than the words and one outside the source bound answer HTTP 200. The [long-session lookup](#long-session-direction-and-prompt-reads)
  now distinguishes an unfinished search from an unverified direction without a separate unknown-session HTTP status.
- The write. The line, the settlement through that direction's time and, over a draft, the adopted
  goal go in one store write, under the revision the page drafted against. A full list is refused
  unless the body names the line to replace, counted from 0 as `origins` is. A settlement never
  moves back over one the reader already gave, so adding an older direction reopens nothing.
- Keep. The reading press carries `settle_through`, and the settlement, with the adoption over a
  draft, is written before the route, the permission and the job, so a press that starts nothing
  has still settled. Every later reply of that press carries the store's token as `settled`, a 503
  for want of a thread included, and a refused settlement answers 422 and starts nothing. Where no
  analysis can start at all, the page sends the same answer to `POST /api/annotate`. Both name
  `expected_revision`, checked under the store lock, so a stale tab settles nothing, and neither
  adopts over a saved goal that holds other words. A settlement never moves back over one already
  given, on Keep as on Add.
- One process. The revision check holds inside one dashboard process; two dashboards sharing the
  store can still race, and these writes share that gap with every other save (DRC-4661).
- Not permanent. A line added from an entry becomes a typed line once the reader edits it and
  saves, as an edited adopted goal becomes typed, so "added from #n" lasts until the first edit.


### Long-session direction and prompt reads

A failing-first 74 MB synthetic session proved that the earlier prefix lookup could
not open a recent direction or restore the recent prompt choices. A second test
proved that a paged direction could be present in the native record but absent
from semantic history. Opening and adopting a direction now recomputes its fact
identity from its own native source, independently of that history. The same
person-message parser, copied-correction exclusions, direction floor, redaction,
2,000-character review cap and saved revision checks still apply.

`config.DIRECTION_SCAN_MAX_BYTES` is 64 MiB and
`config.DIRECTION_SCAN_MAX_SECONDS` is two seconds. The direction lookup uses
`record_pages.scan_source`, the page reader's chunk and line-boundary machinery,
from the newest end. It compares device, inode, size and modification time before
and after the read and refuses any change, including an append during the request.
A refused scan starts over, up to three whole scans, each against a file that did not move
while it ran, so the ruling stands and only the number of tries changed. A working session
writes to its record every few seconds, and a lookup that fails on the first write is refused
at random: measured on 2026-10-14, a Keep pressed from a browser failed five times in five on a
live session, because Claude Code wrote the click's own tool result half a second into a scan
that took 1.4 seconds, while the same request from a script, which returned before the write,
succeeded seven times in seven. A file that moved under every try answers `changed`, with
"The session wrote to its record while Compass was reading it. Press again."
A conservative byte prefilter avoids decoding tool-result-only records; escaped
keys still reach the authoritative JSON parser. Lines larger than 16 MiB are
skipped to their delimiter and count as incomplete coverage. A local filesystem
operation or one decode must return before the next clock check can run.

Finding a match does not stop the scan. Every conflicting raw-content fingerprint for that identity
within the consumed allowance still refuses the words, even when the difference
is beyond the 2,000-character review crop. Copies outside the byte
or clock allowance cannot be checked; this is a bounded source verification,
not a claim that the entire transcript contains no conflicting copy. A direction
that is not found before an unfinished search answers `out_of_reach`. A complete
search with no match, an ambiguous source, or a known request that is
not later than the intent answers `not_found`. Both remain an HTTP 200 body;
unknown sessions use the latter body too. Older pages can read the `why` sentence
without understanding the new tokens. No fallback substitutes a listed summary.

The prompt and request-source lookup adds the newest 64 MiB to the opening read
of at most 32 MiB, with the same two-second clock shared across both. The ranges
do not duplicate complete records; a boundary fragment can be reread. At most
4,096 facts survive, reserving the oldest source alongside the newest facts so
an adopted opening prompt does not disappear merely because recent prompts fill
the allowance. Conflicting identities and same-time request ambiguity are checked
throughout the consumed ranges, including after the fact allowance fills for
identities still retained. Its cache binds the full file stamp, even when the
cached result is empty. The menu arm remains uncached and masks raw separators
before folding words. Analyze retains its separate word masking and ledger.

The focused prompt response carries `prompt_scan.state` and `prompt_scan.bound`,
never source paths, stamps or whole records. The menu offers at most five verified
native prompts, newest first, preserving an opening choice when it qualifies.
It no longer depends on semantic titles surviving eviction. A byte or clock stop
is stated beside the choices: "The prompt search reached its limit. Older prompts
may be outside this read." An empty successful read says "No usable prompts were
found in the parts of this session Compass read." A failed read states that it
could not read the prompts. Selecting still fills a draft and saves nothing.

Copied-correction recognition now covers the same newest 64 MiB and opening
32 MiB sources. A restart cannot expose an unmarked copied prompt merely because
it is farther than the former 32 MiB tail. Incremental reads also clamp their
cached end to the current tail allowance after a large append; they do not read
an unbounded gap. Opening-range matches are cached separately and overlap is
deduplicated in physical file order, preserving the first matching paste rule.
The store still holds only digests, offsets and recognized identities.

A refused Goal, Add, activity-row Add or Keep says what happened beside the
control pressed, with a persistent polite announcement, and keeps focus there.
The answer survives polls and remains until the next press or an intent edit,
including an edit in a pending direction line. Keys compare exact session
identities. Update intent instead uses the same local feedback path.
Successful Goal and Add still focus their respective editors. Keep first shows
every direction whole, and a later press alone settles it. A failure never focuses
the Goal box or draws a pending outcome line as though the read succeeded. A
successful Keep derives its settled count from the directions that press showed,
so several directions are not described as one.

Successful direction lookups use the freshly recomputed native fact as their author,
identity and timestamp proof. They no longer recompose project evidence for each source.
A failed lookup still checks the listed record to distinguish a known earlier request
from an out-of-reach one. The real scratch audit exposed the repeated composition cost
after the individual Add reads had all succeeded.

`POST /api/direction` accepts either the existing `fact_id` or `fact_ids`, a
nonempty list of at most 64 nonempty strings, each at most 256 characters. Sending
both forms, an invalid item or an oversized list answers HTTP 400 before a source
scan. The existing body-size, session and loopback guards still apply. A batch
answers HTTP 200 with `{"results": [...]}`: one result per requested id, in request
order, including repeated ids. Each result has exactly the single-id shape:
`ok`, `fact_id`, `text`, `clipped`, `fits` and `goal_choice` on success; `ok: false`,
`reason` and `why` on refusal. One backward walk shares its byte allowance, clock
and file-stamp checks across all ids. Each id's fingerprint is checked throughout
the consumed allowance. No source words are cached between requests.

Keep uses one batch for all missing source words under its existing 15-second
control deadline, including when its second press may analyze. Goal and per-row
Add retain the simpler single-id request. A partial batch draws successful words
and states the refusal beside Keep and in the polite live region. Nothing is
settled or analyzed while any direction is missing or clipped. Successful words
stay held in the page for a retry; recovering the missing words asks for another
review press before settlement. More than 64 missing directions is explicitly
refused without a request, rather than split into repeated scans.

Measured on 2026-10-13 with the same-size synthetic 73 MB and 105 MB fixtures,
one-MiB tool-result lines and 64 compact requests at the newest end. Fixture
construction and identity collection are excluded. Every request opened all its
requested ids and read 67,108,864 bytes once:

| Fixture bytes | Ids | Bytes read | Milliseconds |
|---:|---:|---:|---:|
| 73,407,766 | 1 | 67,108,864 | 494.030 |
| 73,407,766 | 5 | 67,108,864 | 504.218 |
| 73,407,766 | 20 | 67,108,864 | 495.186 |
| 73,407,766 | 64 | 67,108,864 | 504.404 |
| 104,868,016 | 1 | 67,108,864 | 497.351 |
| 104,868,016 | 5 | 67,108,864 | 492.056 |
| 104,868,016 | 20 | 67,108,864 | 488.315 |
| 104,868,016 | 64 | 67,108,864 | 489.128 |

The single-id scan measured about half a second, as in the previous run below.
A batch of 64 took at most 1.02 times its fixture's single-id cost.
The behavioural timing regression derives its limit from the measured single-id
read, with threefold scheduling headroom, and separately requires one scan.
A mounted page regression shows all twenty answers after one single-source reply
interval and settles only on the next press. Mutations of per-id requests,
per-id ambiguity, unreached refusal and request order each fail their regressions.
On the real scratch board, a fresh load with a seeded intent showed all twenty
unsettled directions 1,135 milliseconds after the first Keep press. None was
clipped, the review announcement appeared, and nothing was settled.

Measured locally on 2026-10-12 with synthetic one-MiB tool-result lines:

| Fixture bytes | Direction | Bytes read | Milliseconds | Result |
|---|---|---:|---:|---|
| 73,407,766 | Recent | 67,108,864 | 517.272 | Opened |
| 73,407,766 | Older, inside allowance | 67,108,864 | 518.431 | Opened |
| 73,407,766 | Opening, beyond allowance | 67,108,864 | 519.706 | Out of reach |
| 104,868,016 | Recent | 67,108,864 | 519.571 | Opened |
| 104,868,016 | Older, inside allowance | 67,108,864 | 526.601 | Opened |
| 104,868,016 | Opening, beyond allowance | 67,108,864 | 518.880 | Out of reach |

The menu returned all three synthetic prompts and request sources on both files.
Its two ranges read 74,449,762 bytes on the smaller file, including reread boundary
fragments, and 100,663,296 bytes on the larger file. The latter reported a byte
stop for the unread middle. Fixture construction is excluded from timings.
The two-second allowance leaves headroom over those reads; it does not guarantee
those timings on a loaded machine. No real prompt corpus was copied.

### Amended 2026-10-05: an adoption reply names its own saved revision

Delegated owner acceptance (DRC-4784) adds `saved_revision` to the successful
`POST /api/annotate` reply shape. The adoption captures the actual stored revision under the
annotation write lock. An unchanged repeat reports the revision it found, and a saved settlement
that mints no revision reports the one it kept. Refused or unwritten adoptions and every other
arm report `null`. The existing `revision` field still reports current state, which another write
may have advanced before the route rereads it.

A discard keeps its last revision number while publishing no live baseline, so the next adoption
can save revision 4 when the page posted baseline 0. Inferring an increment would refuse that
legitimate save. Reading the later current revision would instead let a concurrent write lend its
number to a different request. The receipt avoids both. It carries only a number generated by the
server, remains outside the annotation, session, reading and history schemas, and ignores
caller-authored receipt fields. The checklist save follows this receipt with the existing locked
revision guard. For an unchanged adoption it follows only when the receipt equals the frozen
baseline, because matching goal words can accept a stale revision while the checklist changed
elsewhere. The receipt reports that repeat honestly; it does not authorize rebasing the frozen
checklist. The frozen draft rule is owned by
[reader state](design-reader-state.md#the-inventory).

### What the draft and question page build decided, 2026-09-27

DRC-4682's page half, on the server half's wire, built to the owner's decisions of the same date:
no level or pill over an unsaved draft, every unsettled later direction drawn at its own number, the
question before the press in place of "Conflict to settle", and Add adopting a draft in its write.

- The draft. The goal box holds the first prompt as Compass publishes it, or the latest where no
  first prompt with a time is published, marked "from your prompt" (and "latest" for the second),
  with "Shown excerpt only." on a clipped one, a tinted box and (until the owner's 2026-10-02
  amendment, which leaves Save intent the one save) Looks right. It is derived on every
  render and never written, so it is not reader state; an edit rides the held draft as any other,
  and a box put back to the draft's words is the draft again, so saving it adopts rather than
  storing an excerpt as typed words. Nothing is drafted over a store this build cannot read. The
  design's line "Drift is measured against these. Edit anything that is off." takes the lede's
  place over a draft rather than adding a row: the six-line fold had 7px to spare at 1440x900, and
  still has (893 before and after).
- The edited box. Analyze, Keep and Add's save are refused whenever the goal box differs from what
  it stands on (the saved goal, or the draft) or the outcome-lines draft differs from what the
  server holds, because each would stand on words not on screen and then drop the edit. Analyze and
  Keep say "Save your intent, or undo your edit, to analyze drift."; Add says "Save your intent, or
  undo your edit, to add this direction." beside its pending line, not in the Drift control. A held
  goal is forgotten after a press only while it still equals the draft that press adopted, so
  nothing typed while a request is open is dropped (fix round). An outcome line typed while Add's
  save is open is kept too, and the stored line joins it with its place in the new list as its
  origin, so the next lines save keeps the added direction rather than deleting it (second fix
  round).
- No level. `nextIntentDrafted` is the one predicate the level and the live estimate consult;
  `nextDriftEstimate` is the empty seam they fill, and a test stubs it to prove the guard can fail.
  "Save your intent to see a live estimate" is DRC-4696's.
- The floor. The page reads `annotation_goal_saved_at` for a typed goal, as the server does, so the
  list's flag, the question and the route agree about what is later.
- The question. It stands in the control's place, with Keep the one primary and Add beside it.
  Keep is never the consent, so the disclosure stands after it, and only where Keep will analyze. "since your first prompt" replaces "since
  saving your intent" over a draft. Of several directions it quotes the earliest, the one Add
  opens (owner, 2026-09-28): quoting the latest named a direction Add could not reach until the
  ones before it were added or kept. The number is `nextCockpitEntryNumbers`'; the sentence drops it
  rather than naming one the list did not give. The block after the reading keeps only its neutral
  states (nothing since, settled, unread).
- Keep's route. Where the page already knows no analysis can start (no reader, model calls off, no
  provider enabled, a job running, the daily cap), Keep goes to `POST /api/annotate` and reads
  `Keep my intent`. Where an Allow is still owed it goes there too, with no `allow` and no
  `tool_output`, and then says "Kept your intent and settled the direction. Press Allow and analyze
  to send it for a reading." over the confirming step's "Allow and analyze" (owner, fix round).
  Otherwise it goes to `POST /api/reading`. Either way it names `expected_revision`, a refused
  settlement says nothing was settled, the outcome is written to the polite live region, and a
  settle hands focus to the next primary. The region is the only place it is announced: the
  sentence beside the control is drawn without `role="status"`, so a screen reader hears it once.
  Each press empties the region first if it still holds the last Keep sentence, so the same
  outcome twice is announced twice, and the unsaved-edit refusal is written there too. The next
  Analyze or Allow press takes Keep's sentence back out.
- Parity and polish (DRC-4732, DRC-4734, DRC-4726, DRC-4736; owner, 2026-09-28). Keep opens every
  direction it would settle through `POST /api/direction` before it settles anything. Only a sole
  direction whose whole text is the summary the question quotes settles in one press, because of
  several the question quotes the earliest alone. Otherwise the question draws them all whole,
  says nothing was settled, and the next press settles what was drawn under the revision captured
  at the draw; a direction arriving between the presses is drawn by the next one instead of
  settled. Where one cannot be opened, Keep is refused (fix round, wire review F1 and F2). Analyze and the plain goal save
  send the revision the page drew. `/api/reading` refuses a stale one with 409 `revision-changed`
  before the route, any Allow write, the adoption or the job, reading the store from disk under
  its lock and checking the entry handed to the job again, so another dashboard's save is caught, and the page says the approved stale
  sentence; the store already refused a stale goal save, and the typed words stay in the box.
  A typed save whose words and provenance equal the stored revision's answers "Already stored"
  whatever revision it names, because nothing is written (owner, 2026-10-02: a double press or a
  retry after a lost answer was told "Not saved" about words on disk).
  `nextReadingCheckSupports` mirrors `check_supports` on every harness, including `changed_after`,
  `read_incomplete` and the subjectless Pi rows an older build stored, held by a test built from the server's own Pi
  fixture; the record column opens with "Compass reads work results from Claude Code and Pi
  only." The analyzing box lost `role="status"`, which re-announced it on every render: its start
  and its outcome are written once each to the persistent polite region. The question adds no
  full stop after a quote that ends in its own mark, and the Intent heading's keyboard focus draws
  the accent ring.
- Landing and holding still. The Sessions goal link lands on the Intent heading over an untouched
  draft, and in the box only where nothing is drafted. The drafted box and the pending line are
  as tall as their text whether focused or not. The first fix round held the focused draft at its
  two-row resting height so Keep would not move under the press, and that hid the rest of the
  draft Keep adopts (137 characters showed about 80 at 375px). A box that grew on focus and shrank
  on the mousedown that blurred it swallowed the first press on the button below it, which is
  what the pending line did to its save, a second Add and Keep (second fix round).
- Add. It opens the earliest unsettled direction, so its save settles through that one only and the
  question comes back for any later one (fix round; the build first opened the newest, which
  settled the earlier ones unanswered). The pending line is one per session beside the lines draft,
  with no `maxlength`, so a long direction is shown whole and counted over the bound, and its save
  stays inert with a sentence rather than cutting it. At six saved lines the reader names the line
  to replace. The line label reads "from #n · not saved", with the number recomputed from the fact
  id on every render, and the line goes once its direction is no longer open. A second Add press
  while it is pending focuses it rather than reopening it over the reader's edits. "added from #n"
  on a saved line is DRC-4697's.
- Every open direction is drawn. One from before the intent's window is drawn with its time and no
  number, as a cited earlier entry is, and is not counted among the earlier entries left unlisted,
  so the question never names a direction the list does not show.

### What the window build decided, 2026-09-27

DRC-4715 asked whether a reading may cite an entry from before its evidence window. The owner ruled
no, and that such a citation is refused the way any other unsupported citation is. The build
decisions below follow that ruling and the DRC-4702 decisions of the same date.

- The rule covers every entry type, not only checks. An entry with no time cannot be placed after
  the words, so it is refused too once a window is open. A reading with no window start refuses
  nothing on these grounds.
- "Before the window" is read by when an entry's evidence arrived: a check's result time where one
  was recorded, its call time otherwise. A check whose call began before the words and whose result
  landed after them is inside the window.
- `reading.produce` drops these entries from the list it numbers, beside the last-turn cap, so the
  model is never offered one. That follows `_citable`'s rule that a row the resolver must refuse is
  never numbered. It is done there rather than in `build_ledger`, which is the page-parity contract
  and which the abstention scorer also reads.
- The resolver's rule 3 refuses such an entry as well, and the page's copy refuses one in a reading
  stored before this, so a line resting only on it reads "uncited" on both sides and falls to "not
  verifiable". No new reason token was needed.
- Two more reasons come before those, because a record that was never read is not an empty one
  (DRC-4689). `no-record-reader` is for a harness Compass has no observed-record reader for:
  Copilot, Cursor, OpenCode, Goose, Droid and Gemini CLI. Their collectors still read prompts and
  titles for the board, so the sentence says that and no more (owner, 2026-09-27): "Compass
  reads only this harness's prompts and titles, not the session's work, so there is nothing to
  read your words against. No reading was made and nothing was spent." `record-unread` is for a
  harness that has a reader and whose transcript was not found. Both withhold before the ledger
  and spend nothing.
  Antigravity has a reader for the person's typed directions alone, so its reading runs on those.
- Three reasons for reading nothing, each said only where it is true (owner, 2026-09-27).
  `ledger-empty` is for a record with no entry naming the session. `window-empty` is for a record
  whose every entry is from before the words or has no time. It is decided over the whole record,
  before the last-turn stop cut. `after-stop` is for a record that does hold entries after the
  words, every one of them after the session's last observed stop, as a resumed turn the row has
  not caught up with leaves it: "Everything after your words came after the session's last
  observed stop, so there is nothing finished to read yet."
- The cutoff sentence counts each set honestly (owner, 2026-09-27). Each clause appears only when
  its count is not zero, in the singular for one. Reworded 2026-10-16 in plain sentences, with the
  same counts: "Read 2 of the 3 entries after your intent: 1 from you, 1 message from the agent.
  The oldest is from about 2h ago. 1 earlier and 1 untimed entries were not read. 1 entry after the
  last observed stop was not read." The page lists each sentence as its own item under What the
  analysis read.

#### Amended 2026-10-04 (owner): disclose measured reading coverage

The cutoff counts what was available to this reading, not everything the session recorded. At a
press the server binds a regular transcript's identity, size and modification time before fact
collection to a bounded tail read after prompt preparation. A file missing, replaced or changed
across those reads has unknown coverage. An internally stable second read alone cannot describe
the earlier facts. A short file with a long silence is complete; a time gap alone proves no loss.

When a measured truncated tail starts inside the intent window, the cutoff names its start and
the approximate minutes outside it instead of equal "Read N of N" counts. Every intent row gets
"may be in the part not read", from those measurements. Claims remain independent. Checks can
come from an older scan, so the tail start does not describe the check listing. The mix separates
passed, failed and unrecorded runs, files written, launches, person messages, agent messages and
derived entries. Omitted pass and write counts cover only the reading's window through its stop,
not the session-wide count; checks the prompt could not fit have their own count. Loss and source
clauses fit the stored cutoff's 832-character bound without truncation. The newest-final
fallback and the largest accepted command counts raise the measured large-count case to 825 characters; this keeps every loss clause.

Coverage stores only an optional closed mapping of counts, a time, a boolean and the source state.
It changes no model prompt. A found adopted source already equal to the saved goal was read whole,
even though no expansion was needed. A missing or unroomed source is named beside the answer; only
a found source that was read gets the up-to-1,000-character promise. Drafts promise a lookup
attempt. Absent legacy measurements stay unknown, never measured zero.

#### Amended 2026-10-13: a press reads the message record back to the window start

A reader pressed Analyze on a Claude Code session whose Goal was its first prompt and read "Can't
tell ... may be in the part not read". The transcript was 1.82 MB and the 400,000-byte tail began
four minutes after the prompt, so the agent's own account of that first turn, the evidence a
reader most needs for an early Goal, was outside the reading. Only the agent's messages are lost
that way. The person's older messages come back from the history store and the window-words lookup,
and checks and writes read backward under their own 8 MiB budget. The history store never keeps an
agent message, so the tail was its only source.

A press now reads the focused Claude Code session's person and agent messages backward from the end
of the file (`project_context.press_message_events`) until it has read sixteen timestamped records in
a row older than the window. (It first stopped as well once it held more than 100 messages, which is
more than the project cap can keep; the amendment below that follows removed that stop.) One older record does not stop it, because a resumed transcript can rewrite earlier records
after newer ones. It runs under the press bounds the adopted-source lookup already uses (the newest
64 MiB under one two-second clock) and refuses a file that moved. It does not read a message whose
text is longer than 256 Ki characters: redaction is not linear in the worst case, the clock is only
asked between records, and a message worth reading is a few kilobytes. Such a message, like a line the
scan skips whole, is an unread region. The text is measured, not the record, because a pasted
screenshot makes a user record several megabytes of image data around a short question. The window is the one of the revision being read,
not the previous reading's: a first press has no stored one and an edited Goal has moved it.
Ordinary collection, every poll, and every other harness keep the tail. Enlarging `tail_bytes` stays
rejected ([session record pages](design-session-record-pages.md#rejected-alternatives)): it taxes every
collection and cannot cover a long session.

Coverage keeps its five keys and the page's wording. For a press that read back the two message keys
describe what was kept, not what was scanned. `tail_truncated` is true when the read stopped before the
window start (bytes, clock or a moved file), when an unread region lies inside the window, or when
the read or the project cap dropped any in-window message of the session. `tail_start` is where the record is whole
from: the oldest in-window time before the first unread region, or, after the cap, the oldest message
kept that is newer than the newest one lost. It is not the oldest message kept, because the cap keeps
the session's own reader messages ahead of the agent's, so that one is usually the Goal's own prompt at
the window start, and the page would then call a partial record complete. A record older than the
window never lowers it, so one replayed record cannot pull a partial read back to itself. A read that
reached the window start while the cap dropped its oldest messages would otherwise say the window was
covered, which reports a fact about the read as though it were one about the record. A truncated read
with no start to name says so in the cutoff, as the page already did. A reading stored before
this keeps the old meaning, the oldest time in a 400,000-byte tail and a size above it, and nothing
distinguishes old from new.

The page holds the board's own record, which is tail-bound, so it cannot resolve a citation to an
entry only the press read, and it demotes an unresolved citation to "can't tell, uncited". A row now
counts the cited ids it holds no entry for and, once a record page has loaded and older entries remain,
says that Show more may load them. "May", because the entry could also be newer than the last poll or
not a message the record pages return. The owner ruled on 2026-10-13 that the finishing of a press this
page watched asks the page to read older record pages for that session until each cited entry
resolves, the record reaches its start or its window, or 20 pages have been read, and nothing else
loads a page ([reader state](design-reader-state.md#the-inventory) owns the exception and its stops).
The sentence stays for where that stops short. Rejected: the focused context reaching back to the
stored window, because the page polls that context and it would repeat the tail enlargement for one
session on every poll.

This also amends DEC-24 item 6: an otherwise blank unverifiable row citing entries says "Can't
tell: what was read does not settle this". An uncited blank keeps the recorded-absence sentence.
The scope names unread git, gh and connected-tool replies and the person's screen. The Codex
limit explicitly says the agent's replies were not read. No detector verdict changes merely
because coverage is partial.

#### Amended 2026-10-13: a press keeps the closing agent message of each earlier turn

Reading back to the window start was not enough for a long window. Two limits still stood between
the first turns' messages and the model, and the first was not the prompt budget. Measured on the
session that prompted this (a 6.4 MB transcript, still growing): the press scan stopped once it held
more than 100 messages, 92 agent and 9 of the reader's, before the window start, and the project cap
then kept 79 agent messages, the oldest at 08:26, though the window opened at 07:59. All 79 fit the
16 KiB prompt, which came to 16,372 bytes, so the first turns were lost to retention and the budget
had not yet cost anything. A window with more agent messages than the budget holds loses them to
both, newest kept first.

The evidence an early Goal rests on is what the agent said it had done, and that is the last message
of a turn. A turn's first messages usually announce what the agent is about to do and carry no claim. So a
press now keeps, besides its newest 100 messages, the closing agent message of the oldest twelve
earlier turns (`PRESS_ANCHORS`): the last agent message before a reader's message going forward in
time, kept together with that reader's message, because the prompt recognises a turn's close by the
reader's message after it and the history store may not hold that one. It goes on reading to the
window start for them, under the same press bounds, and keeps only that handful in memory. The
project cap reserves the anchors after the session's own checks and the reader's messages and before
the rest of the agent's, oldest first, so they cost a reader's message or a check nothing. The
newest turn's closing is among the newest messages and is not reserved apart: reserving it would let
a reader-heavy session lose its newest reply to the oldest anchors. The same measurement after the change, on the transcript as it had grown to 7.2 MB: the press read
the whole window in 0.11 seconds, the oldest agent message in the ledger was 08:00:28, and the prompt
was 16,367 bytes. Reading to the window start has a cost the stop at the cap avoided. Redaction
dominates it, so a synthetic 20,000-message window (9 MB) spent the whole two-second clock, stopped
on time and reported the window as not reached; the coverage says so rather than claiming the first
turns.

The prompt reserves an eighth of its budget for these closings (`ANCHOR_SHARE_DIVISOR`, about ten
rows at 130 to 190 bytes), oldest first, before the newest agent messages take the rest. It is a
share of bytes, not a count: a flat count of 40 would take about 60% of the agent capacity and still
lose about 22 messages from the middle. It displaces, because a full prompt has no unused space, and
what it displaces is the middle: the messages between the oldest closings and the newest. A reader's
message, a check, a write and the newest agent messages keep their rank, and a prompt everything
fits in is selected exactly as before. A closing the share cannot hold falls back to the ordinary
newest-first order. Which messages closed a turn is derived from the ledger's own order, so no new
field is published and `for_page` is unchanged.

Coverage keeps its five keys. A read that did not keep every in-window message is truncated, and its
start is where the record is whole from: after the newest message the read or the cap lost. The kept
closings older than that are extra evidence, not a contiguous record, and never move it. When the read
stopped on bytes or the clock, or skipped an unread region, the start is no earlier than where the
contiguous read began. The cutoff
adds one clause to the message-tail sentence, naming how many agent messages that closed an earlier turn
were kept, so the split reads in plain counts.

Decided against: a Show more condition on what enters the prompt, since the prompt is built before
the page exists and cannot depend on what the reader has loaded without making a stored reading
irreproducible; since a finished press reads older record pages for itself, it is also unneeded. Not
done: the first agent message after each reader's message, which was proposed first and carries no
claim. Not covered: a window of one turn has a single closing, its newest message, so it behaves as
before; and a reading opened by a reload or a second tab does not run the page's read, so a citation
to a closing the page does not hold still shows as uncited until Show more loads it. No numbered rule
of the shape contract changes: it names no selection order, and the 2026-10-03 sentence that ranks
the agent's messages last is amended above.

### What the Steer back and Update intent build decided, 2026-09-28

DRC-4681 built item 7 and DRC-4697 built item 8, to the owner's rulings of 2026-09-28: the template
approved as exact text, the server composing with placeholders and times while the page fills in
"#n", no Steer back with nothing to steer from, consistent lines dropped before a refusal over 2,000
characters, the Copy cue reusing "Copied" and "Copy unavailable", the direction offered, and the
saved-line labels. The calls the rulings left open:

- The route is `POST /api/correction`, answering parts rather than a published field, because
  composition reads the record, and a per-session field would compose on every collection for a
  box few readers open. A part is text or `{"entry": fact_id}`. The page writes the first number
  it draws as "(#n in Compass)" and the rest as "(#n)", as the template shows them, and an entry
  it does not number keeps only its time, which the server already wrote. Since 2026-10-14 every
  number reads "(entry #n in Compass's activity list)"
  ([the amendment](#amended-2026-10-14-owner-the-correction-names-the-entry)).
- Each line's state is the stored reading's, re-derived against the record as it is now with the
  page's rules for whether a verdict survives: a reading of an older revision lends no state, an
  unsettled later direction demotes a departure, a citation must resolve inside the reading's
  window, and on Claude Code an outcome-line verdict stands only where the route can carry checks
  (`nextReadingOutputLimit`). A stored `why` the page knows never demotes a row, because the page
  applies one only after its own rules have left the row unverifiable; one it does not know demotes
  it as unreadable. Otherwise the text could claim a departure the panel beside it has demoted. A
  goal departure counts as something to steer from, and the template says it as "Back to my goal".
- The original template had one sentence each for a failed check and a later direction, settled
  or not. The [owner amendment](#amended-2026-10-04-owner-correction-triggers-and-wording) removes
  every later direction from this template and names only a failure after the last person message.
- Consistent lines are dropped one at a time, the last first, until the text fits. Every
  placeholder is counted at six digits, so the page's text never passes 2,000 whatever it numbers.
  Both sides count characters as code points: the page has no `maxlength`, which counts UTF-16
  units, so a correction of emoji is shown whole and one keystroke never cuts it. An edit past
  the cap is cut from the run it inserted, by whole characters, and never from the text already
  there: keeping the first 2,000 code points of the whole value cut a mid-text paste's tail and
  split "é" into a bare "e".
  DRC-4739 intercepts ordinary cap-crossing insertions before they land, using the browser's native
  edit transaction. On Chrome, assigning the trimmed value after a paste erased Undo; inserting
  the fitted text through the native edit command kept Undo and Redo. Paste uses its clipboard
  event because textarea `beforeinput` carried neither `data` nor `dataTransfer`. An unavailable
  native insertion refuses the edit and keeps the existing text. Return's null-data
  `insertLineBreak` and `insertParagraph` events mean a newline; one that fits, including by
  replacing a selection, proceeds as an ordinary edit. At the cap it keeps all existing text.
  Composition is different: its
  provisional text stands until the commit, and an overflowing commit is refused whole. Native
  Undo is used only when it restores the exact pre-composition text; otherwise that text is
  restored by assignment, with a sentence saying Undo is unavailable for the refused edit. This
  is preservation of the reader's words, not a claim that every browser supports the native edit.
  Automatic paints wait while the edited correction has focus, with a visible sentence saying
  updates are paused until the reader leaves the box. New payloads still arrive in memory. Blur
  draws the latest record after any pointer click dispatch and keeps the committed text;
  native Undo is preserved during editing,
  and ends when that redraw replaces the editor. Retaining and moving the same textarea did not
  keep Chrome's Undo history, even through a continuously connected atomic move.
- Claude Code only, as the copy route is, so a paste of the correction can be recognised coming
  back. An unknown session and another harness answer what a session with nothing to steer from
  does.
- Placement. Steer back takes the control's slot on the first screen rather than the result's rows,
  which ran to 2,567px at 1440x900 with six lines when it was first drawn there. Under a surviving
  departure it is the one primary with Update intent instead beside it, and Analyze drift follows
  as a secondary, the design's "Analyze again". With no reader it is the primary beside the route's
  reason. With a reader and no departure it is a secondary after Analyze drift. It is not drawn
  while the question before the press stands, since the question owns that slot and Keep is its
  primary. The result stage gains nothing, so DRC-4695 renders around it. Amended 2026-10-12
  under DEC-27: after a current result, Steer back has no Analyze again beside it. A stale result
  offers the one rerun in its reason callout.
- The box is labelled "Correction to copy" with the hint "Compass never sends this. Copy it and
  paste it into the session." Copy writes the box's text, frozen at the press, and posts it to
  `POST /api/correction/copied` only after the clipboard took it. The owner approved "Copy",
  "Nothing recorded now gives a correction to steer back from." and "Could not compose a
  correction. Press Steer back again to retry." on 2026-09-28. A press over either refusal asks
  again, in one press.
  Copy during a recomposition reads "Copy unavailable" and copies nothing; an active native
  composition is not copied either.
- An open box follows the record. The press stamps what composition read: the saved words'
  revision, the settlement, the stored reading's `read_at`, and the entries the parts cite. A
  change in any of them drops a text the reader has not edited, which is recomposed from the server
  where there is still something to steer from and closed where there is not, so Copy never records
  a text composed from a record that no longer holds. An edited text stays the reader's, marked
  "This was composed from an older record. Recompose replaces your edit with a correction from the
  record as it stands." beside a Recompose button; both wait on the owner.
  While a quiet recomposition is out, the old box keeps its exact last rendered text, including its
  old entry numbers. An edit or input-method composition begun before the answer keeps the reader's
  text and sets that answer aside. The [reader-state inventory](design-reader-state.md) owns the
  focused-edit and composition paint pauses.
- Update intent instead offers the direction a surviving departure cites, else the latest later
  direction, through Add's own `POST /api/direction`, skipping any direction already saved as a
  line; with none left it adds the empty line. The store refuses an entry already saved as another
  line through the same refusal a stale revision gets, so no route can add it twice. The pending line it opens stands while its
  direction is any later direction, settled or not, where Add's own line stands only while its
  direction is unsettled. With no later direction it adds an empty outcome line, focused, and at
  six lines it says the existing six-line sentence and adds nothing. Where a pending line's reason is
  that sentence (six saved lines, no line chosen to replace), it says it beside its own save and
  the list's copy is hidden, so it is drawn once rather than above and below the replace choices
  (DRC-4760). A line giving another reason (over the character bound, or an unsaved edit while the
  draft holds six lines) leaves the list's copy drawn, so the disabled add control keeps a reason
  on screen. Once a line to replace is chosen the line gives no reason and the list's copy stands. The server already added a
  settled direction: `annotations.direction_floor` never read the settlement.
- A saved line added from an entry reads "added from #12" where the list numbers that entry and
  "added from your direction at 14:04" where it does not. With no record read, or the entry gone
  from it, it keeps "added from an entry". The reading's row label beside a line still says "ADDED
  FROM AN ENTRY", which DRC-4695's result renders anew.

### Amended 2026-10-04: owner, correction triggers and wording

The owner, approving the Analyze drift plan, amended DEC-24 item 7 and the exact correction
built on 2026-09-28. A later direction alone offers no correction, settled or not, and no later
direction is copied into it. A surviving intent departure, a contradicted or unshown claim, or a
failed check after the person's last message may offer one. The page and composer use the same
boundary. Keeping an intent settles its direction question; it never turns a direction into drift.

A goal departure gets its own timed sentence. Claim and failed-check sentences precede the
outcome checklist, and departed outcome lines come before the others. An unconfirmed outcome asks
for evidence. A line judged consistent on the agent's words says "the session says this is done;
not confirmed by a tool". A clock outside today includes its date. An adopted goal cites its
source entry where the observed record holds it; otherwise the saved excerpt ends in an ellipsis.
The 2,000-character cap still drops consistent lines before refusing, and never truncates a line.

The triggering entry and age sit beside the correction control. The Analyze control also shows
the published rolling daily budget as "N of 12 left today"; unavailable budget storage publishes
no number. New checks, file writes and messages are counted after the reading's own time, not
a later intent save. The earlier correction put a later direction into 57 of 83 texts, and
33 of 298 offers named no departure. These are the measured reasons for narrowing the template.

The owner also amended item 10: marking a reading Not accurate removes that reading from the
analysis level and from correction composition. Independent recorded facts may still offer a
correction, and the live estimate still reads them. The reading and mark remain stored; clearing
the mark restores the reading. [SECURITY.md](../SECURITY.md#analyze-drift-cancel-and-copied-corrections)
owns the token and its exposure.

### Amended 2026-10-14 (owner): the correction names the entry

Item 7's template wrote the first entry the page numbered as "(#n in Compass)" and every later one as
"(#n)". An agent that has never seen Compass could not place either: given a pasted correction with
"08:51 (#36 in Compass)", it answered that it could not tell what the reference meant. The owner
approved new exact text on 2026-10-14: every entry the page numbers reads
" (entry #n in Compass's activity list)", in the goal line, the claim line, a departed or consistent
outcome line and the failed-check sentence alike. For example:

- `You said "<its first sentence>" at 14:02 (entry #12 in Compass's activity list); the record shows otherwise at 14:05 (entry #13 in Compass's activity list).`
- `A check failed at 14:05 (entry #13 in Compass's activity list).`

The fields do not change. The correction is still the goal, each outcome line with its state, and
cited entry numbers and times, with no command, tool output or model prose; a failed-check sentence
carries only its time and entry. Only the words around a number change, and the number is still
recomputed on the page from its own list and never stored (item 11). A placeholder is now counted at
43 characters instead of 21 for the first and 10 for the rest, still at six digits, so a correction
that sits within a few characters of the 2,000 cap is refused slightly earlier than before. The page
(`correctionText`) and the server (`correction.NUMBER_MAX_CHARS`) count it the same way, and the
frontend's differential against the recorded answers goes through one named projection back to the
old numbering ([the recorded departure](design-frontend-migration.md#held-to-recorded-answers)).

The triggers in item 7 are unchanged. The [DEC-23 amendment of the same day](#amended-2026-10-14-owner-a-write-outside-a-named-folder-does-not-settle-a-line)
records that a recorded write outside a named folder is not one of them, and why.

### Amended 2026-10-16 (owner): the budget, the mark and what it read

The reader-requested cap rose from 12 to 100 attempts per rolling 24 hours. The unasked lane keeps
its own cap of 12. The "N of 12 left today" line beside Analyze is gone: under the cap the count was
noise. Once the cap is spent, a banner sticks to the top of the session page and names the limit
and the local time the oldest attempt ages out. The refusal under Analyze uses the same words. It
says "you can analyze again at" rather than "it resets at", because a rolling window frees one
attempt at that time, not all of them.

"Not accurate?" became "Mark as inaccurate". Before the press, a line beside it says what the mark
does. After it, a status beside the control says what changed, the control reads "Undo", and the
level's slot says the level is hidden because of the mark. Before, the only change near the
button was its pressed state, while the level and Steer back vanished far above it and the column
jumped. The press now holds the control where it was pressed. The wording says the analysis "no
longer sets" the level or Steer back rather than that Steer back is hidden: a failed check after
the reader's last message still offers Steer back on its own, and the first draft said otherwise.

"What it read" became "What the analysis read", with four headings: the model, the intent (its
version, when it was saved, where it came from, each line quoted), the session, and what is never
read. The session list draws the scope from its token and gives each cutoff sentence its own item.
The reading definition and the long scope paragraph left this panel, since the page states both
elsewhere. The cutoff is reworded at the producer in plain sentences with the same counts
(see [what the window build decided](#what-the-window-build-decided-2026-09-27)). A reading stored before the change keeps the sentence it was stored with.

### Amended 2026-10-20 (owner): the correction carries the explanation

Item 7 fixed the correction as exact text with no model prose. A walk of the session page found
what that cost: the correction named what departed and at which entry, never why, so a reader
pasting it handed the agent a verdict it could not act on, and the Drift card beside it already
showed the reason. The owner amended item 7 on 2026-10-20: each departure in the correction also
carries its stored explanation, the reading's one bounded `detail` sentence, so the reader and the
agent can see why it is drift. The explanation is the reading's own text, redacted and bounded like
every stored reading string, labelled as Compass's reading, and never presented as the reader's
words. This supersedes, for the explanation only, item 7's "no model prose" and the sentence of
the [2026-10-14 amendment](#amended-2026-10-14-owner-the-correction-names-the-entry) that keeps
model prose out; every other field and sentence of the approved template stands.

The text. Under each surviving departure the correction adds one indented line:

```text
Back to my goal: Ship the retry queue (entry #1 in Compass's activity list)
The session departed from my goal at 14:05 (entry #9 in Compass's activity list).
  Why Compass reads this as drift: The agent rewrote the scheduler instead of the queue.
Where it stands against what I expect:
- The retry tests pass: departed at 14:06 (entry #10 in Compass's activity list)
  Why Compass reads this as drift: The retry tests failed after the last change.
- Lint is clean: consistent with 14:07 (entry #11 in Compass's activity list), as the tool reported
Please continue from here.
```

- The label is the Drift card's own heading, "Why Compass reads this as drift:", so the line says
  whose reading it is in the reader's words and the agent's. The line is indented under the line it
  explains, which keeps a bullet one item in Markdown and keeps the sentence out of the reader's
  first person ("Back to my goal", "what I expect").
- What carries one: a departed goal, a departed outcome line, and a claim the record contradicts
  (the claims row's own departure), each only while the line the correction writes for it stands. A
  line the page has demoted (an older revision, an unsettled later direction, Mark as inaccurate,
  a citation outside the window) takes its explanation with it. A consistent line, a line not
  reached at this stop, a can't-tell line and an unshown claim carry none: the producer keeps no
  detail for the last two, and the first is not drift.
- Missing or withheld, the line is the approved line unchanged. A detail that is empty, or empty
  once neutralised, adds nothing.
- The path, in this order (the order was corrected on review, 2026-10-20, because each earlier
  step had hidden something from a later one). First every invisible character is dropped: each
  Unicode format character (category Cf, which holds the byte-order mark, U+2060 to U+2064, U+180E,
  the bidi controls and the tag characters U+E0000 to U+E007F) except the zero-width joiner and
  non-joiner some scripts spell words with, and the variation selectors U+FE00 to U+FE0F and
  U+E0100 to U+E01EF. C0 and C1 controls, NEL and the Unicode line and paragraph separators become
  spaces, so it is always one line. Then a leading structural opener is removed, repeatedly, even
  where the reader edits the label away: `/`, `!`, `>` or `|` at the start, `#` before a space, a
  `-`, `*` or `+` list marker before a space, an ordered marker (digits then `.` or `)` then a
  space), and a `~~~` or ```` ``` ```` fence. A word that only starts like one keeps its first
  character: "-3 tests regressed" and "#1234 still open" are unchanged. Then the text is redacted,
  by the shape filter and again behind each hyphen or underscore inside a token, because the filter
  anchors most shapes at a word boundary and a key joined to "x-" or "-" published whole; and then
  bounded through `records.safe_text`, the redaction and bound every stored reading string takes
  (240 characters, `RuntimeConfig.annotation_text_cap_chars`'s default, with one closing "…" where
  cut, as the producer cuts; the store loads a detail at one character over that cap so the mark
  survives a reload). A redaction marker that would finish past that bound withholds the
  explanation rather than pass its room. Last come the swaps, after the opener strip so a swapped
  character can never shield an opener: a backtick becomes `'` (no code span or fence); `<` and `>`
  become `‹` and `›` (no tag an agent may read as an instruction block); and a word-initial `@`
  becomes `＠` (no file mention Claude Code reads in). Each swap is one character for one, so
  neutralising never lengthens it. A detail with nothing visible left adds nothing. What it cannot
  remove is what a model sentence says: SECURITY.md carries that residual.

The cap. The lines keep item 7's 2,000 characters, counted as before without the explanations,
with every placeholder at its widest; over it the consistent lines drop, last first, and then the
correction is refused with a sentence. The explanations get a fixed room on top, so adding
them never drops a line and never refuses a correction that composed before. The worst case is
every explanation a correction can carry, each at its widest: the goal, six outcome lines and a
contradicted claim make eight; each is the label's 36 characters (a line break, two spaces and
"Why Compass reads this as drift: "), 240 of detail and the "…", 277 in all; so
2,000 + 8 × 277 = 4,216. That is the hard bound: the page's editor, its counter, the copy route and
the composer all hold 4,216 (`copied_corrections.CORRECTION_CAP_CHARS`, the page's
`CORRECTION_CAP`), and `test_correction` composes that worst case to exactly 4,216 and refuses it at
one more character of lines. The refusal names what is bounded: "Your goal and lines would be
longer than 2,000 characters. Shorten a line of your intent.", since the counter beside it counts
the whole text to 4,216. The copy route reads a body of up to `copied_corrections.COPY_BODY_CAP_BYTES`
(twelve bytes a character for the text and both identity fields, the widest JSON spells a code
point, and 256 for the object), not the 12,288 the other annotation routes then shared (16,384 since 2026-10-27): at that bound
4,216 CJK characters were refused, the page still said Copied, and the paste then counted as the
reader's words. Recompose and the stale rules are unchanged but for one addition: the stamp is still
the saved words' revision, the settlement, the reading's `read_at` and the cited entries, and marking
the reading Not accurate now adds a fourth element, since marking moves none of the others and a
held correction would otherwise still carry the withdrawn departure and its explanation. An
explanation comes from the stored reading those already stamp, so it can change only when one of
them does.

The box. With an explanation under each departure, a correction with two departures ran past the
six rows the box opened with, and its closing request sat below the fold in the first walk at
1400 px. The box now opens with one row per line of the composed text and one more, from 6 to 16,
counted once when it opens so typing never resizes it; a longer text, or one wrapped at 400 px,
scrolls inside the box.

The placeholder contract (item 11). An explanation is a text part, never a placeholder. The page
fills only `{"entry": fact_id}` parts and renumbers nothing inside an explanation, so a number a
model wrote there is the model's own and is not one of the activity list's. The fields are now the
goal, each outcome line with its state, the cited entry numbers and times, a contradicted or unshown
claim's published title, and each departure's neutralised explanation; still no command, tool
output, check name or summary.

A copied correction coming back (item 9) is unchanged. An exact paste is Compass-assisted, so the
explanation in it is never the reader's evidence or a later direction. An edited paste is the
reader's own words, and the model sentence inside it travels with them, as the quoted claim already
did.

### Amended 2026-10-20 (owner): local time and quoted words

The usability review pasted a correction and found three things an agent could not use: it cited
"entry #5 in Compass's activity list", a list the agent never saw; its times were the server's clock
(01:15) while the page showed the reader's (09:15); and nothing in it let the agent find the moment
it was being steered from. The owner ruled on 2026-10-20: the correction uses the reader's local
time, drops "(entry #N in Compass's activity list)", and quotes the agent's own words. The rest of the
approved template, and the explanation line of the
[earlier amendment that day](#amended-2026-10-20-owner-the-correction-carries-the-explanation),
stay as they are.

- **Local time.** The page sends `time_zone`, the reader's IANA zone name from `Intl`, and
  `utc_offset_minutes`, the reader's zone in minutes east of UTC, with `POST /api/correction`, and
  the composer draws every time in that zone (`correction.zone_clock`), with a date where the moment
  is not the reader's today. A name in `zoneinfo.available_timezones()` is preferred, so each time
  takes the zone's own rules as the page's `clock()` does, and a daylight-saving change between two
  cited times no longer draws one an hour off (review, 2026-10-20). A name this machine does not
  know, or a Python without a time zone database, falls back to the offset, which is one for every
  time in the text and keeps that one-hour gap across a change. A `time_zone` that is not text, or an
  offset that is not a whole number of minutes within 16 hours of UTC, is refused with 400. With
  neither the server's own clock is used, as before, so an older page still composes. The page's
  labels beside Steer back ("from the check at") and on an idle reading ("Read up to the last
  recorded entry at") name the date on the same rule (`datedClock`), so they and the copied text
  name the same moment.
- **No entry numbers.** A placeholder is drawn as nothing. It stays in the parts, because the page
  reads the cited ids from it to tell when a held correction is stale (item 11 is otherwise
  unchanged), and it adds no width.
- **The agent's own words.** Where a departed goal or a departed outcome line is cited at one of
  the agent's messages, the line quotes that message's published title, the first sentence the
  activity list shows: `The session departed from my goal at 09:15, where you said "Done: the
  billing rate is now 0.25 in src/billing/invoice.ts".` The title is neutralised exactly as the
  explanation is (`correction.neutralised`: invisible characters, openers, redaction behind joints,
  `records.safe_text`, the look-alike swaps), bounded at the title's own 112 characters and one
  "…", and its closing stop is dropped as the claim line drops it. A check, a write or the reader's
  own message is never quoted: a command is not the agent's words, and the planted-command tests
  keep it out. The claim line already quotes its title, and a consistent line stands on a tool's
  report, so neither carries a quote.
- **The cap.** The quotes get a budget of their own on the explanations' terms, so no correction that
  composed before is refused or loses a line: the lines are measured without the quotes and with
  each placeholder at nothing. A quote is the label `, where you said "` (18 characters), 112 of
  title, the "…" and the closing quotation mark, 132 in all, and seven can appear (the goal and six
  outcome lines). The cap is 2,000 + 8 × 277 + 7 × 132 = 5,140, held in one place
  (`copied_corrections.CORRECTION_CAP_CHARS`) and mirrored by the page's `CORRECTION_CAP` and the
  vocabulary fixture; `test_correction` composes the worst case to exactly 5,140 and refuses it at
  one more character of lines. The lines' 2,000 became 2,760, and the cap 5,900, when the goal's
  own cap rose to 1,000 ([2026-10-27](#amended-2026-10-27-owner-the-goal-holds-1000-characters)).
- **Where Steer back stands.** While departures are listed, Steer back stays beside them, labelled
  "from the check at HH:MM" with the reading's `read_at` in the reader's zone, including when the
  session has gone idle and while a later direction's question stands (the question keeps the
  primary press, and Update intent instead is not offered there, since the question's Add is the
  same act). Copying sends nothing. Two withholds stay: a reading marked inaccurate, and one of an
  earlier version of the intent. There the departures say so in one line instead of the button
  going missing. Those two are the implementer's reading of the earlier rules (`steerOffer` and
  `steerWithheld` in `frontend/src/drift/correction.ts`, and `correction._current_rows` on the
  server), not part of the owner's ruling of 2026-10-20, which reads unqualified: "Steer back stays
  available while departures are listed." They are kept as the cautious side, because a correction
  pasted into the agent would then argue from a reading the reader has rejected or from words
  they have since replaced. The owner is asked to confirm them. If the owner does not, Steer back is
  offered there too, with that one line beside it, and the server compose stops demoting those
  rows.

### What the result build decided, 2026-09-28

DRC-4695 built items 6, 10 and 14 on the session page, with the analysis-derived level of
[DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn). The rulings left these open,
and each was settled on the withholding side.

- The level is the server's. `http_api` calls `levels.analysis_level` over the stored reading and
  the record as the focused project context holds it, and publishes it as
  `sources.work.analysis_levels` on that answer alone, recomputed on every fetch and never written.
  The lines a reading must answer are those of the revision it read, not today's; a revision the
  store no longer holds gives no level. The page draws it only for the reading it shows, matched by
  `read_at` and revision, in the level slot, labelled "Analysis" with its time and item 1's source
  line. It is drawn over the live estimate, as the design's result stage draws it, and its pill
  shows whichever way the live monitor is set, since the switch hides the live level only. A
  reading of a revision other than the saved one draws no level, in the slot or the pill, so the
  live estimate stands when the switch is on and nothing does when it is off. The server scores that
  reading against the lines it read, and a level for words the reader has since replaced says
  nothing about today's, which is the live estimate's own rule below. The reading keeps its
  "Your intent changed" banner and "Analyze again".
- The page holds "None or low" to its own rows. Where the level says None or low and a line the
  panel draws is not a consistent it can word, the level reads "Not enough recorded yet". The
  validated function counts a departure the page has demoted (an unsettled later direction, say),
  so the level can read Medium beside an answer of "Can't tell". That is the cautious direction and
  was left as validated rather than re-ruled here. Re-ruled 2026-10-21: the page draws a level
  above None or low only beside a departure it shows
  ([the amendment](#amended-2026-10-21-a-level-needs-a-departure)).
- Each line reads "Departs at #n", "Consistent with #n, as the tool reported; not inspected" for a
  Claude Code tool report or any harness's check, "Consistent with what the session said at #n; not
  a check" otherwise, or "Can't tell". In the Drift card the qualifier is said in the line's Evidence rather than
  in view (item 6's 2026-10-01 amendment). The number is the activity list's. An entry the list does not
  number is named by its time, as a line added from an unnumbered entry is. "Can't tell" carries
  the page's own reason beneath it where the page has one, and reads "Can't tell: nothing recorded
  shows this yet" where it has none. A line added from an entry is labelled by the list's number,
  "ADDED FROM #n", as the saved line above it reads.
- The answer reducer runs over the rows after every page rule. Under a surviving departure it is
  the headline "Departs from your intent" with the count beside it and, as the short account, each
  departure's detail followed by its citation. With no departure and at least one outcome line,
  a failed check after the latest person message gives "A check failed at #n." naming the one
  whose result arrived last (`reading.evidence_at`, the later entry on a tie), numbered from its
  call. The correction's sentence names the same check, timed at its result, and so does the
  page where it has no number to show (DRC-4780).
  This [owner amendment](#amended-2026-10-04-owner-a-failure-after-the-persons-last-message)
  replaces the original window-only test, which admitted checks with no recorded time; then any line without a valid verdict gives "Can't tell"; then
  "Nothing found against what it read. This is not a check that the work was done." That last
  rung needs at least one outcome line among the rows: otherwise a reading of a goal with no line,
  which the producer does not withhold, answers "Can't tell", as the level beside it reads "Not enough
  recorded yet" (DEC-26 item 1). A reading of
  the words shown now draws every line typed now, so a line it returned nothing for is a missing
  result and cannot tell; a reading of older words draws only the lines it read.
- Where the work went groups written paths in the saved analysis window by folder, with a path
  without a folder under "The working directory". Its count comes from the scan's distinct paths
  at or after that reading's cutoff, before the twelve-entry check and file listing is capped. A
  path last written before that cutoff is absent from both the rows and the count. The section can
  still show a count when all its paths fell out of the listing. A path retained from the saved
  window but absent from today's numbered view is labelled as unnumbered; it is not assigned a
  number from another entry. If the matching count is unavailable, the section says so.
- Stale says why. Changed words give "Your intent changed after this analysis." with the revision
  sentence the raises use; otherwise an entry newer than the reading's `evidence_through` gives "New
  work since this analysis.". A reading stored without that time, which only rows from before
  2026-09-24 are, counts from its `read_at` instead, so work after it still says so. "Analyze again"
  is drawn in the banner only where a press would run: a reader, no refusal, no job, and no question
  before the press standing, which Keep answers.
- Not accurate is a toggle on the reading shown, posted through `POST /api/annotate` with the
  reading's `read_at`, and the store refuses a mark naming any other reading. Only the token is
  stored. A press the store does not take says so under the button until the next press.

#### Amended 2026-10-01: the result takes the button's place

Owner rulings Q2, Q3 and Q10, 2026-10-01 (DRC-4758 slice C). The owner's walk never saw a level: the
result sat in a READING section below the fold, under a second "Analyze drift", and read as nothing
having happened. This supersedes the placement in the bullets above; their wording rules are kept.

- The Drift card's rows are the design's: "Drift" with its subtitle and the Live monitor switch;
  the one hint line where the switch can be turned on and no reading is stored; the level block;
  then the slot that holds the control or the result. Nothing is built from the rejected designs A
  and B.
- The level block is the level word with its source beside it, the four-segment meter, and the
  meter's labels "None or low", "Medium", "High", "Extreme" under its segments with the current one
  marked. The labels are hidden from a screen reader, which already has the level word.
- "Not checked yet" (Q2) is drawn over the unlit meter and its labels with a saved intent, no level
  from any source and no reading stored. It names a process state, never "no drift", is never drawn
  over an unsaved draft or once a reading is stored, and draws no pill.
- The time is said once. The source chip reads "Analysis" alone, the item 1 line keeps "From the
  analysis at <time>", and a caption under it carries the range alone: "#a to #b", the first and
  last entries the activity list numbers inside the window the reading read, or "#a" when they are
  one entry.
- Why the level is what it is: one page-owned sentence per closed `levels.REASONS` token
  (`NEXT_DRIFT_REASON_LINES` for what a level rests on, `NEXT_DRIFT_BLOCKER_LINES` for what holds one
  back, `NEXT_DRIFT_REASON_SILENT` for the three that need no sentence; a test walks the set and
  gives each token exactly one home). Under Medium and above the first reason reads under the
  meter, numbered from the level's cites where the cite is the kind the token names; under "Not
  enough recorded yet" the blockers sit behind "Why not None or low". A later direction is said as
  yours and unsettled, never as drift. An unknown token renders nothing. The live estimate's level
  uses the same maps.
- The live estimate's callout, "This is a quick estimate. Analyze to see what drifted and how to
  steer back.", sits directly under its level at High or Extreme, before the control; the
  analyzing box keeps "You can keep working. The result will appear here." under its steps.
- Under a stored, readable reading and no job, the slot holds the result in this order: the stale
  callout if any; the headline and its account under a departure only; the goal row; "Against
  expected outcome", an ordered list with one item per outcome line; Where the work went; Steer back
  and Update intent instead; Not accurate; then "What it read", one click away with
  the definition, the model stamp, the baseline's source, the cutoff and the revision. The READING
  section is not drawn there. A malformed reading, a refused one and no reading keep it.
- Each checklist line is a glyph, the line's own words as its title, the ruled status beneath, and
  "Evidence" one click away holding the source tag, the why and the limit. The glyph is shape first:
  a cross for departs in the panel's clay (Q10), a neutral filled dot for consistent, never a check
  and never green, and a dashed circle for can't tell. "#n" stays text because the page routes on
  its fragment. Amended 2026-10-12 under DEC-27: each finding with resolved citations has a
  button to jump within the page to its entries in Session activity. It resolves fact ids, scrolls
  to and focuses the first entry, and marks each with the finding's stored words and the entry's
  current number as text. Reduced motion uses an instant scroll. Missing citations keep the
  existing nothing-resolvable sentence and mark nothing. The jump starts no request or model
  and is outside DEC-27's measured click path.
- One "Analyze again" (Q3). It is the same control as "Analyze drift", so it keeps every refusal,
  the consent step and the count, and is inert with its reason wherever the press would be refused.
  It is never the stage's primary. A stale result holds it in the callout, and Steer back keeps its
  own row at the foot. Amended 2026-10-12 under DEC-27 row 3: a current result offers no
  second run control. New work or changed intent makes it stale, and its one Analyze again
  appears with the reason in the callout. The request count, disclosure and daily cap remain
  visible or reachable beside the result. While the question
  before the press stands, no press is drawn under the result. While a job runs the analyzing box
  takes the slot alone and the old result is not drawn.
  The session's run controls are Analyze drift before a result, Allow and analyze inside consent,
  Keep my intent and analyze while later directions are unsettled, and Analyze again for a stale
  result. A current result and a running job offer no run control. Cancel only cancels; Keep my
  intent where consent is owed only opens or settles directions and launches no reading.
- The end of a job that stored a reading is announced as "The analysis finished. Its result is in
  the Drift section.", with no positional word, so it is true at every width.

### What the slash-command build decided, 2026-10-01

DRC-4764. A Claude Code reader who directed work with `/pr-review-response 1287 …` or `/review`
had given a later direction that the observed record dropped, so a reading could call the work
they asked for a departure. The command is the reader's message in the harness's markup, and every
line of that markup opens with `<`, which the record reader skips.

- A prompt command is a direction, with arguments or without. It is published as
  `transcripts.prompt_title` renders it, `/name` and its arguments on one line, redacted and then
  bounded as any message is. It is a person entry in a reading's ledger and a later direction on
  the page, and "Add it to my intent" offers the command as typed, not its tags.
- A local command is not, with arguments or without: `/compact keep the notes` drives the harness.
  The record says which a command is by the tag it opens with. Measured over the local store's
  main-thread records: all 1,477 that open with `<command-message>` are followed by the command's
  expanded prompt, and all 945 that open with `<command-name>` are followed by the harness's own
  output, 903 of them after its local-command caveat. No command name falls in both. The local
  names seen were `/clear`, `/login`, `/plugin`, `/mcp`, `/compact`, `/add-dir`,
  `/reload-plugins`, `/model`, `/exit`, `/design-login`, `/chrome`, `/reload-skills`, `/effort`,
  `/rate-limit-options`, `/context`, `/install-github-app`, `/stickers`, `/usage-credits` and
  `/permissions`. The rule reads the tag rather than this list, so a new local command is refused
  without being named.
- A prompt command on `records.harness_control`'s list, `/insights` the one seen, is refused too.
- The goal slot and the instruction line beneath a title read controls by the same predicate,
  `transcripts.harness_control_prompt`, so the three cannot disagree. Before, they matched that
  list against the rendered line, which only a bare command can match, and published
  `/compact keep notes` as a goal and as the work asked for. Over the local store this refuses
  152 more prompts and refuses none it used to: `/compact` 90, `/add-dir` 21, `/plugin` 19,
  `/design-login` 7, `/chrome` 4, and 11 more records under six other names. A local command carrying arguments, `/model opus`
  for one, is a control now where it once published.
- The draft from your first prompt is not changed by this. On 550 of 1,601 local Claude sessions
  that first prompt is a control, `/clear` on 326 of them, and skipping it would mean drafting from
  a later record, which the first-prompt read refuses to do. The next section records the ruling.
- Whether a direction may be drafted as your intent is unchanged: the same three-word test as any
  message, so `/create-pr` alone is a direction and not a drafted intent.
- A command's arguments over several lines once published the last line, closing tag and all; 12
  such records in the local store change summary, and 3 local commands with such arguments stop
  being listed. Those facts' ids move. For up to 24 hours after the upgrade the semantic history
  store still holds the old facts, so an old citation resolves to the old row and a retitled
  record can show twice; once the history window ages them out, a citation stored to one no
  longer resolves.
- A command longer than the record reader's 2,000 characters loses its closing `</command-args>`
  (2 of the 1,477 measured). It is published with the arguments that arrived rather than as
  the bare name, and "Add it to my intent" offers them ending in an ellipsis and reports them
  clipped, so the reader edits the line before saving it and it is never offered as whole.

### What the control-first build decided, 2026-10-01

DRC-4766, built to the owner's ruling of the same date: a session whose first prompt is a harness
control drafts no goal, and the page says there is no first prompt to draft from, so the reader
types one.

- No draft at all, not a later one. The latest prompt is a later record, and the first-prompt read
  never drafts from one, so a control-first session does not fall back to it either. Skipping the
  control to the first prompt that states work was the alternative, and the ruling refused it.
- The server decides. `transcripts.first_prompt` publishes `first_prompt_control`, true when the
  first record is a control by `transcripts.harness_control_prompt`, the same rule the goal slot
  and the instruction line read. The page renders that verdict and does not classify the prompt
  itself. `annotations.prompt_candidate` refuses to adopt such a first prompt, so a request built
  by hand cannot save the command as the goal either.
- `first_prompt` still publishes the control, `/clear` or `/compact keep notes`, and session
  history keeps it as before. It is what the session opened with, and the history record is not a
  draft. The new field is a boolean, so it is not prompt text and needs no allowlist entry.
- The page says "This session opened with /clear, so there is no first prompt to draft a goal
  from." in the slot the draft's lede uses, so it costs the fold no row. It names the command and
  not its arguments. The Sessions goal cell shows "Add a goal" over such a session rather than
  the latest prompt, because the cell names what the session page drafts. "Use your prompt" still
  offers the reader's prompts, which the reader chooses rather than receives
  ([amended 2026-10-01](#amended-2026-10-01-use-your-prompt-fills-the-goal-box)).
- Measured over the local store, counts only: 550 of 1,601 Claude Code sessions with a first prompt
  publish it as a control (`/clear` 326, `/login` 115, `/plugin` 36, `/mcp` 24), and 9 of 469
  Codex sessions do. Before, every one of them drafted the command as the goal; now none does,
  and the other 1,051 Claude Code sessions draft as before.


## DEC-26: four drift levels, and a live estimate after every turn

Amended 2026-10-11 by [DEC-27](#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result): the live monitor switch moves into More (placement only), and an intent with no outcome line is stated in the how-to as a valid "Not enough recorded yet".

Amended 2026-10-22 by [the amendment at the end of this decision](#amended-2026-10-22-a-goal-alone-is-read-or-refused): an analysis no longer needs an outcome line, so item 1's "zero is too little" and rule L7 hold for the live estimate only, and a goal too vague to read against is refused.

Decided 2026-09-24 (DRC-4691). DRC-4692 defines and validates the levels on recorded Claude Code
sessions. DRC-4696 builds the live estimate in the panel and the header, and amends the skill body's
sentence "Nothing here evaluates on a cadence" when it ships, not before, because the skill body
describes the shipped product.

A reader who glances at a session wants to know how far it has moved from their intent without
pressing anything. The ruling takes option C's four levels as designed, None or low, Medium, High
and Extreme, with a live estimate after every turn and a header pill. The owner accepted these
costs knowingly:

- It amends DEC-15, including its 2026-09-23 amendment, which refused evaluation on a cadence.
- It amends DEC-17 rule 4 (consistent is never rendered as met) and "What the contract does not
  remove": a cadence makes the full rubric owed, and the levels research below is its first
  measured part.
- It amends DEC-20 item 3 (no surface says a session has no drift), its state table, and "What
  DEC-15's indicator sentence now means".
- It amends DEC-23 items 6 and 7: the level is a derived state of the tool-outcome facts, published
  on the session payload only, never on a row, in history or in an off-machine payload.
- It accepts the A9 failure class, a level that reads safe when little is seen, and puts a measured
  basis in front of it.

Six sub-questions were ruled the same day, each as recommended.

1. The basis is a separate rule per source. Each level has a written definition over named
   evidence, and DRC-4692 measures it. "None or low" has a floor for each source. For the live
   estimate: the latest run of every check has a recorded result and passed, nothing was written
   after that pass, no shell command that is neither a check nor on DEC-23's read-only list ran
   after that pass, and, where the saved intent names folders, every write is inside them; it says
   it read checks and file paths, not what the intent says. For an analysis: every outcome line is
   `consistent` on a tool-reported check under DEC-23 item 8, with no departure, and the Goal may
   rest on the session's own account; it says "From the analysis at <time>: each line of your intent
   against the checks and messages it cited." For both: no failed check, and no unsettled later
   direction. A later direction blocks "None or low", and so, for the live estimate, does such a
   shell command; neither is ever counted as drift. A check with no recorded result, and a pass
   before a later write, never count toward it. With too little evidence the level reads "Not
   enough recorded yet", never "None or low". Zero is too little: the live estimate needs at least
   one check whose latest run passed, and an analysis needs at least one outcome line, so a session
   with no check, or an intent with no outcome line, reads "Not enough recorded yet". DRC-4692
   measures what else is too little. A write here is a file-write tool call the transcript
   recorded. A file a shell command changes is not seen (DEC-23's capture), so "nothing was written
   after that pass" means no recorded write, not that nothing changed. The shell-command blocker
   narrows that gap. A read-only command is not read-only when it carries a command substitution,
   a redirect into a file, or a writing option the closed lists name (`find -delete`, `-exec` and
   `-fprint`, `tree -o`, `git diff`/`log`/`show --output`); what is still not seen is a command on
   the read-only list that changes files through anything else.
2. Two sources, labelled. "Live estimate" is computed without a model after each turn, from DEC-23's
   evidence and the reader's saved intent: failed checks, passes followed by writes, and the share
   of writes outside the folders the intent names. An unsettled later direction, and a shell command
   after any check's latest passing run that is neither a check nor read-only, only block "None or low".
   The folder signal is not used when the intent names no folder, so it is never read as 0%. Over
   an unsaved draft there is no live level: the Drift section reads "Save your intent to see a live
   estimate" and the pill is hidden. "Analysis" derives the level from a reading's per-line
   results, with no new model output. Each source says what it is and when it was computed.
3. Where it shows: the Drift section and the session header pill. Not a Sessions row, not a total
   and not a sort key. DEC-20's "Drift" row mark, its table, and DEC-23's no-row-field rule stay.
4. The live monitor switch is off by default, as the design's "Turn on for a quick, low-cost drift
   check after every turn" says. It is remembered per session in the browser only, and never sent
   to the server: there is no server-side store and no new route. DRC-4696 adds its row to
   [the reader-state inventory](design-reader-state.md). Off hides the live level and the pill;
   the analysis level is unaffected. Amended 2026-10-02 (NU-5): the hint reads "Shows a level
   after every turn, from checks and file paths, with no model call", because "low-cost"
   suggested a spend the estimate never makes.
5. No notification, desktop or page, comes from the live estimate (DEC-18, DEC-19). The live
   estimate and the analysis level never make a session eligible for the unasked lane, never
   trigger, order or gate it, and never feed it. The live estimate is not DEC-18's unasked reading:
   it calls no model and raises nothing.
6. History. Neither level is stored. The analysis level is recomputed from the stored reading, and
   "Rose from Medium at #33" from recorded evidence within the run. Each source keeps its own line
   from item 1: the live estimate says it reads checks and file paths, not what the intent says, and
   the analysis says it read each line of the intent against the checks and messages it cited.

DRC-4728 amends that recomputation on 2026-09-29. A stored departure must still have current,
citable evidence inside the reading's window, under the same source, authorship, work and check
rules that accepted the reading. A vanished citation or an aged-out entry cannot keep the level
raised. The server supplies all current facts from the cited session, including the person's
messages that may support a Goal departure; limiting the lookup to check rows would retract those
legitimate departures. This revalidation reads the published facts and calls no model or output
grant.

The owner answered two questions from review the same day, and both answers are part of this ruling
rather than an amendment. A shell command that is neither a check nor read-only, run after any
check's latest passing run, blocks the live estimate's "None or low" and is never drift (item 1, and DEC-23 item
3; the read-only list is in DEC-23's closed lists). The analysis level has its own source line, and
the line "reads checks and file paths, not what the intent says" is the live estimate's alone (items
1 and 6).

### What reading a `/goal` decided, 2026-10-22

DRC-4946, built against the shapes recorded in `docs/captures/claude/goal-2.1.308-macos.jsonl`. A
reader who gave Claude Code a goal with `/goal` has said what done looks like, and the command is a
local one, so the first-prompt read classes it as a control and drafts nothing from it.

- The goal is read from the transcript's own records and not from the command's prompt text. The set
  record is a `goal_status` attachment with `sentinel: true` that carries the condition and the
  instant the command ran, which is also the instant of the command's `user` record. The evaluator's
  verdict is a second attachment with `met: true` and no sentinel.
- The latest set wins. A `Goal cleared:` answer publishes nothing. A met goal keeps its condition,
  because the harness clears a met goal from itself and the session was still for it; the capture's
  `/goal clear` after a met goal printed `No goal set`, and that changes nothing. A verdict with no
  set record behind it in the bytes read has no known set time, and a time is never taken from the
  verdict instead, so it publishes nothing.
- A condition that cannot be held whole publishes nothing, as the first-prompt read refuses a cut
  prompt: over 2,000 characters here, though the harness accepts 4,000, because the longer words
  could only be offered as an excerpt.
- The published field is one mapping, `session_goal`, `{text, at}`. The harness verdict (met, when,
  the evaluator's reason) joins it as keys later, and nothing is renamed.
- The source token is `session-goal`, in `reading.PROMPT_SOURCES`. The reader typed the command, so it
  is adopted words keyed on their own time like the other sources, and every place that branches on
  the closed list reads it that way: the window baseline is the command's instant and a saved one is
  "saved" and not "typed". It is not a person's message in the observed record, so a reading finds no
  source fact for it and reads the goal box's words, with the existing sentence saying so.
- Rejected: reading the condition out of the command record's `<command-args>`. The record reader cuts a
  message at 2,000 characters and drops the closing tag, and the attachment is not cut.
- Not decided here: how the page offers the goal, which the next section records.

### What the measured `/goal` shapes changed, 2026-10-23

Amends the section above, built against `docs/captures/claude/goal-clear-replace-verdicts-2.1.309-macos.jsonl`.

- A clear is the set sentinel with `met: true` and no reason. The section above read every `met: true`
  attachment as the evaluator's verdict, so an interactive clear, which writes nothing else, showed the
  cleared goal as marked met. The `Goal cleared:` answer is kept as a second signal; `claude -p` writes both.
- The length limit is 4,000 characters, from the harness: 4,001 is refused with a printed sentence and
  no record. The 2,000 above was the record reader's own cap and had no basis in the command, so a
  3,000-character goal, accepted by Claude Code, published nothing. The cap is now 4,000, and the Goal
  field's own excerpt (`offered`, `cut`) carries the words it cannot hold. The reader-side message cap is
  unchanged, which is why the condition is still never read from `<command-args>`.
- An impossible verdict is `met: false` with `failed: true`. It joins no verdict, as a not-met one does,
  so the card never says the harness marked it met. Whether the goal still stands afterwards was not
  measured; it stays published. Superseded by the amendment of
  2026-10-23 below: it was measured, the goal is ended, and the give-up is published as its own claim.
- Left as they were, now measured: a replacement is a second set, the latest wins; a resume writes no
  goal record, so an active goal survives it; an untimed set publishes nothing, because every captured
  record carries a time and one without cannot be given a guessed one.
- A goal set before the 8 MiB the cold read covers publishes nothing, so the Goal field offers no
  detected goal and the reader types or adopts one. Reading the head of the file instead was rejected:
  it would make every collection of a large transcript read it end to end.

### What offering a `/goal` decided, 2026-10-22

DRC-4947, owner rulings of the same date. The page uses a detected goal and does not hold it back for a save.

- A `/goal` is the working goal until the reader edits it. With no goal saved it is the draft, ahead of
  the first and latest prompt and ahead of the harness-control check, because a session that opened with
  `/goal` has no first prompt to draft and still has this goal. The box, Save intent and Analyze drift all
  read it through `intentDraft`, so Analyze adopts it by name (`adopt: session-goal`, its words and its time)
  as it does a drafted prompt. The server's later-direction floor takes the same draft time
  (`annotations.direction_floor`), so the page and the store agree on which directions are later.
- The page marks it "Goal detected" and the line under the box reads "From /goal", with the time. Typing
  replaces it and the line says "From /goal, edited" or "Typed"; choosing a prompt replaces it and the line
  names the prompt. The prompt list leads with it. (Wording since 2026-10-23, and the line sits above the box:
  "From your /goal at 11:53 · not saved", "Your edit of your /goal · not saved", "You typed this · not saved",
  "Drafted from the prompt you chose · not saved".)
- A `/goal` that appears after the reader saved a goal never replaces their words. The page offers it
  beside the field, naming the condition and its time, with Use this goal and Keep my goal. "After" is the
  moment the saved words stand at, as `direction_floor` reads it: an adopted goal by its source's time, typed
  words by when they were saved. Use this goal fills the box as a pending adoption, so Save intent records the
  new source and time; Keep my goal declines that `/goal` and any older one, and a later one asks again.
- A condition over the Goal field's 1,000 characters (240 before 2026-10-27) is offered as the server's excerpt with a note that it
  was cut. The row carries `offered` and `cut` only for such a goal, and `prompt_candidate` resolves `offered`,
  so the words on screen, the words an adoption names and the words the store keeps are one string. The page
  never clips on its own, and an adoption naming the whole words is refused.
- Rejected: saving the detected goal on open. Nothing in Compass writes the reader's words without a press.
- Rejected: Use this goal as an immediate write. A pick from the prompt list fills the box and saves
  nothing, and a second kind of pick that saves would make the list inconsistent with itself.

### Amended 2026-10-22: Find goal reads your prompts

DRC-4953, owner rulings of the same date. A session with no `/goal` and no saved goal can still state its
goal across the prompts the reader typed. A button beside "Use your prompt", Find goal, reads those prompts
and offers the goal when it can tie it to the reader's own words.

- The call is the reader's. It runs only on a press, one call per press, and never on a render, a poll, a
  focus change or a revision save. It is refused with the pause and counted against the same rolling cap as a
  reading, at the same model seam (`reading_policy.GuardedModel`), so a press that finds nothing is charged
  because the call was made. A press that sends nothing (no prompts, a missing CLI, a refusal known beforehand)
  is not.
- It reads the reader's prompts and nothing else: the person-authored messages `_prompt_facts` already
  verifies, minus a correction the reader copied from Compass, masked and folded as a chosen goal is.
  Agent messages, tool output and pasted content Compass strips are never sent. A session over 40 prompts
  keeps the first five and the latest.
- High confidence is three mechanical rules and not a score. The model must quote the words the goal comes
  from. Each quote must be verbatim, whitespace aside, in the prompt it names, in the text Compass sent
  (masked and clipped as sent); one paraphrased quote drops the goal, and so does a quote filed under another
  prompt's number. The model must also call the goal clear. The prompt carries the same end-state
  wording as a reading's `reading.GOAL_UNCLEAR_RULE`, without importing it; a test holds the shared phrase. A goal over the Goal field's 1,000 characters is dropped and never cut.
- The vague-goal test is the model's judgement made in the same call. No keyword or length rule makes it,
  as for a saved goal, and a second model call over the same words would double the cost of a press. The
  limit is accepted and written in SECURITY.md: a finder more lenient than a later analysis can show a goal
  that analysis would call unclear, and the quotes are what the reader checks it against.
- The found goal cites the prompts it quotes by the entry numbers Full activity shows (`entry_numbers`), drawn
  as the Drift card draws a cited entry, beside the source line, which since 2026-10-23 reads "Found in your prompts at" the time it was found. Pressing
  one opens Full activity at that entry and reads older pages for it when the page does not hold it.
  The checked quotes sit under that line, each led by its entry number, because the hover shows the entry as
  the activity list abbreviates it and the quote is what ties the goal's wording to the prompt.
- Precedence is the reader's saved goal, a `/goal`, a found goal, then the first or latest prompt drafts. A
  found goal stands only while the box holds its words, so an edit replaces it, and a result that arrives after
  a saved goal, a `/goal` or the reader's own typing does not touch the box.
- Nothing is stored. The answer is held in the page as the box's pending words and saved, if at all, as typed
  words by Save intent, so the store never holds a model's sentence the reader did not keep.
- Rejected: a new adoption source resolved by the server, as `session-goal` is. The server would have to keep
  the found goal between the press and the save, which is storing an assessment of the session before the
  reader has kept it, or call the model again at save time. Rejected: a keyword or length rule for "vague",
  for the reason the amendment above gives. Rejected: running it unasked on open. The owner ruled a reader-started
  call, like Analyze drift.

### Amended 2026-10-22: a goal met verdict is a claim

DRC-4948, owner ruling of the same date. When a Claude Code session ran with `/goal`, its evaluator can write a
`met` verdict. Compass shows that verdict and checks it, and relies on its own reading.

- The row publishes the latest `met: true` verdict on the goal it belongs to, as `session_goal.verdict`
  (`{met, at, reason}`). The key is absent before the evaluator decides, so no goal carries an empty one, and a
  later `/goal` or a clear takes it away with the goal it was about. The reason is the evaluator model's own
  sentence, masked, folded to one line and cut at 500 characters with an ellipsis. A not-met verdict is not
  published (a give-up is, as its own claim: see the amendment of 2026-10-23 below): the evaluator repeats it on every iteration while the goal is open (a real session holds
  more than twenty), so it is progress rather than an end state, and the card reports only the end state.
- The card says it as the harness's claim, in the reader's words: "Claude Code marked this goal met at 16:44",
  under the label "The harness's claim", with the reason quoted. It is drawn from the row alone, so a verdict
  with no analysis yet reads as the claim with a line saying nothing has checked it and no level is implied.
- The analysis tests the claim the way it tests an agent saying a task is done. The test is code over the
  recorded writes and checks (`reading.check_goal_verdict`), never a model call, and it reads only the record
  from the goal's own set time. The facts the reason cites are the files it names and the kinds of check it says
  passed. A cited file recorded as written, or a claimed kind of check that passed, at or before the verdict
  **agrees**, and a recorded fact that undoes it **disputes**: a cited file written again after the verdict, or
  a check of a claimed kind whose latest run failed and that no later whole-suite run before the verdict
  superseded. A dispute outweighs what agrees. Nothing found, or a reason that names nothing checkable, is
  **unconfirmed**, and never disputed, because the listing is capped and absence of a write is not
  contradiction (rule 3).
- The result is stored beside the criteria as `goal_verdict` (`{at, check, why, cites}`), not among them. `at`
  is the verdict's own time, so a reading that predates a verdict, or carries no test, leaves it unchecked and
  the card says to analyze again. `check` and `why` are closed tokens; the page owns the sentences, as it does
  for a criterion's `why`, and a stored value outside the tokens refuses the reading whole.
- The verdict never lowers a level and never counts as a passing check. The producer builds the criteria
  without reading it, and the check is not in `Recorded`, so nothing that cites a check can cite it. Where
  Compass disagrees the card says "Compass disputes it", and "Compass's own reading stands": the level shown is
  the analysis's and nothing else's.
- Rejected: a model call to judge the reason. The reason is already a small model's summary, and a second
  model reading it would add a reading of a reading. Rejected: reading an absent cited fact as a dispute. It
  would turn a capped listing, or a file that existed before the session, into an accusation. Rejected:
  letting a disputed verdict raise the level. A level rests on departures the record shows, and a claim the
  record contradicts is a caution on the claim, as a contradicted agent claim is.

Amended 2026-10-23 (owner feedback, DRC-4948): a file taken away disputes the claim too. A real session
had the evaluator say met over a file a later turn removed with `rm`, and the card said only that Compass
could not confirm it, because a deletion was nowhere in the record the test read. The scan of the
transcript's shell calls now notes each file `rm`, `unlink`, `rmdir` or `mv` took away (a `mv` removes its
sources, not its destination; globs, unplaceable targets, a `-t` move and `git rm` are not read), skipping
a call whose own output reports that command failing. The notes are read at the press and go to no model.
They are not facts: a published fact is a closed kind, and the removal exists only to test this claim.
Where a file the reason or the goal's condition names, or a folder holding it, was taken away after the
verdict and not written again after that, the test **disputes** it with `deleted-after` or `moved-after`,
stored with the one file and the moment (`{at, check, why, cites, path, changed_at}`, the two extra keys
together and only beside those tokens), so the card can say "Compass disputes it: docs/e2e/notes.md was
deleted at 22:59, after the verdict." A file written again after its removal stays the `written-after`
dispute. "Could not confirm it" remains the answer where nothing in the record supports or contradicts the
claim, and Compass's own level stands either way.


### Amended 2026-10-24: the words that report a created pull request or a used skill

A live walk of the owner's session showed a goal line that asked for a skill and a pull request still read Can't
tell, though the reading cited both facts and the verdict check agreed: the reading's explanation carried a word
of [the success list](#amended-2026-09-24-a-checks-own-result-word-is-not-a-verdict-owner-ruling) and the backstop
withdrew the result as a stated verdict. The stored reading does not keep a withdrawn explanation, so the words
were reproduced on a synthetic goal, where "successfully created" and "the record confirmed" tripped it.
Where every entry a consistent cites is one of those two facts inside the window, `successfully` and
`confirmed` are now set aside, as a check's own result words are for a check; `delivered`, `works`, `completed`
and the rest of the list still withdraw it, and a pull request cited beside a check keeps the check's rule.
"Created" and "opened" were never on the list. Not done: a sentence in the trusted instructions telling the model
to describe only what a pull request or skill entry shows. The header's bytes are pinned for final readings and
its budget is tight, so that costs a re-pin and a requalification for a rule the set-aside already covers.

### Amended 2026-10-23: a verdict may name a pull request

[The 2026-10-22 amendment](#amended-2026-10-22-a-goal-met-verdict-is-a-claim) lists the facts a verdict's reason
may cite as the files it names and the kinds of check it says passed. A third is added by
[the pull request and skill amendment](#amended-2026-10-23-owner-pr-and-skill-facts) to DEC-23: a pull request
the reason names, as `PR #7`, `PR 7`, `PR (#7)`, `pull request #7`, a list (`PRs #6 and #7`, `PRs #7, #8`), `pull/7` or a `github.com/<owner>/<repo>/pull/7` URL (a bare `#7` is not read, because it is as often an issue), which
agrees when the record holds a created-pull-request fact for that number (and that repository, where the reason
gives one) at or before the verdict and no earlier than the goal's own set time. The stored `why` for it is
`pr-created-before`. A written file the reason names still agrees first, and a failed check of a claimed kind
still disputes before either. Without the fact the result stays **unconfirmed** with `not-found`, never
disputed: absence is not contradiction (rule 3). A reason that names none of a file, a check kind or a pull
request number is still `nothing-checkable`.

A pull request cannot be disputed by a later record, because the record holds no event that undoes a creation.

### Amended 2026-10-23: a goal that ended is said to have ended

DRC-4956, owner ruling of the same date, built on a measured run recorded in
`docs/captures/claude/goal-give-up-ends-goal-2.1.309-macos.jsonl`. It amends the paragraph above that says a
not-met verdict is not published, and the rulings elsewhere that call a `failed: true` verdict "neither a
verdict nor an end". That was written before the later state was measured. After Claude Code writes the
failed record the goal is **ended**: a bare `/goal` prints "No goal set" and a clear prints the same, and
neither writes a goal record.

- A give-up is published as `session_goal_gave_up` (`{at, reason}`), a top-level per-session field of its own
  and never under `verdict`, because every reader of a met goal keys on that. The goal itself becomes None, so
  naming, drafting and adoption read as they do for any session with no goal. The reason goes through the same
  masking as a verdict's: one line, cut at 500 characters. No iterations, tokens or duration are published.
- A clear is published as `session_goal_cleared` (`{at}`), also top level. The goal is None after it. Where
  `claude -p` writes two clear signals, the sentinel and then the printed line, the first time wins.
- A goal that follows another carries `earlier` (`{how, at}`) on `session_goal`: `replaced` only when the
  earlier goal was still active when the next `/goal` arrived, at that moment; `met` at the verdict's time;
  `gave-up` at the give-up's time. Never the earlier goal's words. A set with the same words at the same
  millisecond is a duplicate record, not a replacement, and a later set takes the clear and the give-up away.
- All of it lives in the same cache entry as the goal, so an incremental read keeps it. A cold read that starts
  mid-file publishes none of it: absent means unknown, never "did not happen". The two new fields are declared
  by hand where `AGENTS.md` names, and are in neither `PATCHABLE` nor session history.
- The Drift card says a give-up as the harness's claim, "Claude Code gave up on this goal at 16:44", with the
  reason quoted and a line that Compass has not checked it and the level does not change. It is never "met",
  never "Analyze again to check it", never a level or a check, and never model-judged. Compass's own reading
  stands, as it does for a met claim.
- The Intent card says under the Goal field what became of an earlier goal ("Replaced an earlier /goal at
  14:05", "An earlier /goal was met at 14:05", "Claude Code gave up on an earlier /goal at 14:05") and, where a
  clear left no goal, "Your /goal was cleared at 14:05". Over a Goal field that still holds a prompt draft, the
  clear names it ("...; the draft below is your first prompt", "your latest prompt", "a prompt you chose", "a
  goal found in your prompts"), so the note is not read as a caption for the draft; typed words and an empty
  box need no name. (Superseded 2026-10-23: the note reads "Your /goal was cleared at 14:05" alone, and the
  source line directly under it names the draft; the "; the draft below is ..." clause is gone.) Where the session opened with `/goal`, the existing
  "This session opened with /goal" sentence takes the clear instead, so it is said once. None of these shows
  while the update offer ("Your /goal changed at") is on screen.
- Rejected: holding a given-up goal and adding the note. The run showed the goal ended, and a held goal would
  keep naming the session, being drafted and offering an update for a goal the harness had stopped. Rejected:
  publishing the earlier goal's words. A replaced goal's text is not the reader's to be shown a second time,
  and nothing needs it.

### Amended 2026-10-27: a CI job named in the reason is not a local check

A reason that said `server-unittest pass` was read as a claim that the tests passed, because the job's name holds
the word `unittest`. The check then looked for local test runs and could agree on one that had nothing to do
with the job the evaluator meant. A phrase that names a remote job is now left out of the claims the check
matches to local runs. Three shapes count, and nothing more:

- a token joined by hyphens or slashes directly before `pass`, `passed`, `fail` or `failed` (`server-unittest pass`,
  `ci/lint fail`), which is dropped whole and never split to find a kind word inside it. A joined token whose every part is itself a check
  word (`pytest/ruff pass`, `lint/type-check pass`, `tests/lint pass`) is a list of kinds, not a job name, and keeps
  them; `ci/lint` and `build-and-test` hold a part that is no check word, so they stay job names. `type-check` and
  `typecheck` are not job names for this purpose, so "type-check passed" is still a local claim;
- a clause that says `CI`, `Actions`, a workflow, or `check on` or `checks on` something, so "the tests pass in CI"
  claims nothing about a local run. `CI` and `Actions` are read in capitals only, because a bare lowercase `ci` and `actions` are
  ordinary words in a sentence (lowercase `github actions` and `in`, `on`, `via` or `per` `ci` are read too), and
  `CI-related` or `Actions:` do not count;
- a CI run URL (`.../actions/runs/<n>`, or a GitLab `pipelines` or `jobs` URL), which marks its clause the same way.

Clauses are still split at commas, full stops, semicolons and `and`, so "All 14 tests pass locally and the
server-unittest check on the PR passed" agrees on the local claim alone. "The tests pass", "pytest passes" and
"lint is clean" keep their match. Such a phrase contributes no kind, so a reason that is only remote reads as
`nothing-checkable`. A ratio (`14/14 pass`) or a path after `in`, `under` or `of` is not a job name. Hyphen-joined local-sounding
tokens with a part that is no check word, such as `unit-tests` and `lint-staged`, are an accepted loss: they read as nothing-checkable. Only the goal
verdict reads this way; outcome-line coverage (`covers_line`) and what a write bears on are unchanged.
Matching a job's name to a recorded CI fact is a separate rule and is not built here.
Rejected: reading `server-unittest` as a test claim when a local test run exists, which is the wrong-reason
agreement this removes.

### What reading a Codex `/goal` decided, 2026-10-27

Built against `docs/captures/codex/goal-0.164.0-macos.jsonl`. Codex 0.164.0 has a `/goal` with edit,
pause, resume and clear, and the reader typed it, so it is the same source as a Claude Code `/goal`: the
same `session_goal` field, the same `session-goal` adoption token, and the same page.

- The set is the `thread_goal_updated` event, not the `user.goal` message beside it. The message is Codex's
  restatement and drops any objective of 699 characters or more; the event keeps it whole to 4,000. The time
  is the goal's `createdAt`, so an edit (which keeps it) is the same goal in new words and says nothing about
  an earlier goal, while a pause and a resume change nothing the row publishes.
- A goal the model creates with `create_goal`, including every `codex exec "/goal ..."`, writes no event and
  is not read: its objective is the model's wording, not the reader's.
- A clear is the `User cleared the goal.` line and counts only over a held goal. Codex writes the same line
  for a clear with no goal and before every goal set over a completed one (20 of 20 measured), so on its own
  it does not mean a reader dropped a goal. A replace writes that line and then the new set, so a Codex goal
  never carries `earlier: replaced`.
- An objective over 4,000 characters is stored as "Read the Codex goal objective file at ...". That sentence
  is the harness's, and it publishes nothing.
- The `<codex_internal_context>` wrapper joins the Codex injected-tag list. All 83 leading occurrences
  measured on one machine were Codex's own (55 goal actions, 27 goal continuation instructions, 1 daemon
  recovery notice); before this they were read as the reader's prompts, and a goal-only session drafted
  "User set the goal: ..." as its goal.
- A Codex session started with `/goal` and never prompted since has no prompt to name it, so its goal does.
- Deferred at first, then done the same day: reading `goals_1.sqlite` for the met state. Completion never
  reaches the rollout (21 of 21 measured), so the file is the only place a met Codex goal shows. The working
  model marks its own goal complete, so it is a weaker claim than Claude Code's separate evaluator, and it is
  published the same way, as `session_goal.verdict` with an empty reason, and tested the same way. It
  attaches only where the file's row has the session's thread id and the goal's set time and words: an edit
  keeps the set time and rewrites the words, a replace starts a new row, and a clear deletes it, so a
  completion never lands on the wrong goal. A claim with no reason is tested against what the goal names, so
  a Codex verdict can agree, and the page words that answer by the goal rather than by a reason. Only `complete` is read. `blocked`, `usage_limited` and `budget_limited` were not captured, and a
  status the record has not shown is not published as an ending.

### What reading an Antigravity `/goal` decided, 2026-10-27

Built against `docs/captures/antigravity/goal-1.4.7-macos.jsonl`. agy 1.4.7 has a `/goal` slash command that
keeps the model working through a stop hook until the model writes `<!-- GOAL_COMPLETE -->` or
`<!-- GOAL_CANCELLED -->`. The person typed it, so it is the same source as the other two: `session_goal`,
`session-goal` and the same page.

- The goal is the person's `USER_INPUT` whose request opens `/goal ` and whose metadata carries the fixed
  `/goal is a [Slash Command]` paragraph (9 of 9 goal inputs carried it, print and interactive). The paragraph
  is required, so a request that only starts with the word is not a goal, and `/edit_goal`, which is not a
  command in 1.4.7, never is.
- It is read from `transcript_full.jsonl`, not the `transcript.jsonl` the directions come from. The short
  file keeps the first and last 2,048 characters of a long input, so a long condition would lose its middle
  while the marker in the tail still matched.
- The latest `/goal` wins and the row publishes no `earlier`, no clear and no verdict. Nothing on the record
  ends a goal: a replace writes only the next set, and met or cancelled is the model's own marker, which the
  2026-09-27 ruling keeps unread. Saying "Replaced an earlier /goal" would be wrong whenever the earlier one
  had been met.
- Amended the same day (owner): Antigravity has its own 16,000-character bound
  (`ANTIGRAVITY_GOAL_CAP_CHARS`). The 4,000 the other two use is their own harness's limit; agy accepted 5,000
  and refused nothing, so a shared 4,000 published nothing for a real goal. 16,000 is well above anything
  measured and still keeps a pasted document from riding every board payload. A longer condition publishes
  nothing, and anything over the Goal field's 1,000 is offered as its excerpt, as for the other two.
- The server adopts `session-goal` from an Antigravity row and nothing else from it: its prompts were never
  adoptable, and this does not change that.
- Rejected: reading the `GOAL_COMPLETE` marker as a verdict. It is the working model's own claim, and one
  reply wrote it again a turn after its goal was already met, so the marker alone does not even show a goal
  was active.

### The starting definitions

These are what DRC-4692 validates, not a measured result. Medium: a pass is followed by writes, or
some writes fall outside the named folders. High: the latest run of any check failed, or most writes
fall outside the named folders. Extreme: both hold. "None or low" is the per-source floor in item 1.
Since [2026-10-04](#amended-2026-10-04-owner-what-the-agent-claims-is-its-own-constraint) a stored
reading may carry a `claims` key beside the lines, and the analysis reads Medium on a claim the
record contradicts (`claim-contradicted`). Under the
[later owner amendment](#amended-2026-10-04-owner-claim-caution-and-secondary-correction), a claim
the record does not show (`claim-not-shown`) blocks None or low only.

### What the levels build decided, 2026-09-24

DRC-4692 built the two functions in `compass_runtime/levels.py`, and `scripts/levels_cases.py`
to measure them. The ruling left these open. Each was settled on the withholding side, and each is
part of what the owner's marks validate.

- "Both hold" means both of High's conditions: a failed latest run and most writes outside the named
  folders. An analysis reads no folder, so it never reads Extreme. A first draft reached Extreme
  from an analysis when a failure came with departures on most lines. Its own failed-check case then
  read Extreme on a one-line intent, and the rule was one nobody had ruled, so it was dropped.
- A folder is a path-shaped word in the goal or a line: two or more parts joined by `/`
  (`web/app`, `src/components`), a trailing `/` (`server/`, `.github/`), or a leading `./` (`./web`).
  A last part with a dot names its folder instead (`src/retry.py` names `src`, `web/.env` names
  `web`), unless a trailing `/` marks the word itself. A closed list of prose pairs names nothing:
  and/or, either/or, client/server, input/output, read/write, true/false, yes/no, on/off and
  before/after. A bare word and a URL name nothing either. An absolute path inside the session's
  working directory is read relative to it, even with one part left. One outside it stays a named
  folder, and since written paths are published relative to the working directory, no write is ever
  inside it. A review round first refused every multi-part word without a marker, to keep prose out,
  and that made "only touch web/app" name nothing and read lower, so it was reverted to the closed
  list.
- A write outside the working directory counts as outside every folder, and so does a write the
  twelve-entry listing dropped. Review found that counting only the listed writes made the share a
  lower bound reported as the share, so a capped listing could lower the level.
- Layer 1 publishes `changed_after` on each check, from the command order the press already used:
  whether a command that may change files followed the check's latest run, in the same call or a
  later one. The live floor blocks on it. Across calls, a changing command whose recorded time
  equals the pass's is read as after it, because the times cannot say which ran first.
- The live floor also withholds when the scan counts a background launch, because a check only ever
  run in the background is neither listed nor counted (DEC-23 item 1) and the launch count cannot
  tell it from a server. The [delegated-launch amendment](#amended-2026-10-04-owner-delegated-launches)
  later changed this blocker to unpaired launches. It also withholds when the listed entries cannot
  place every pass, and
  when the scan is missing any count, which reads as too little rather than as zero.
- An analysis needs at least one outcome line, whatever its Goal says, and a reading whose rows are
  not all objects, or whose keys are not exactly the Goal and `line_1` to `line_N` for the intent it
  read, reads "Not enough recorded yet". An outcome line is shown only by a `consistent` with no
  `why` that cites a passing check. A cited pass that was followed by a change, when read or since,
  reads Medium, as a pass followed by a write does on the live side. The cited pass must also be
  inside the reading's window, as `reading.check_supports` requires. A failed check in the reading's
  window originally read High whether or not the reading cited it, and a check with no time counted
  as inside. The [owner amendment](#amended-2026-10-04-owner-a-failure-after-the-persons-last-message)
  now requires a listed failure after the latest person message and limits an aged failure to
  Medium. Both boundaries read a check by when its result arrived, where one was recorded
  (DRC-4702, 2026-09-27). An older or unplaced failure still blocks "None or low".
- The case tool takes the marks before any reading exists. Cases are built without readings, both
  levels are marked from the evidence and the intent alone, the digest is committed, and readings
  are attached afterwards, stamped with that commit. The first build showed a stored reading on the
  marking screen, which let the reading shape the key.
- The readings are replayed from the frozen cases, not pressed on a live board (owner,
  2026-09-28). A press on these recorded sessions withholds `idle-unknown`, because no turn stop or
  end was ever observed for them, and a cut case on a live board reads more than was frozen.
  `levels_cases.py --read` hands `reading.produce` the case's frozen facts and intent, with the
  row stopped at the case's own `captured_at`. It goes over the Codex route, charged on the reading
  home's ledger, the count a press uses. The evidence rules, the prompt and every withheld reason
  are the press's, and a withheld case is recorded as refused. On this corpus the readings are not
  spent (owner, 2026-09-28): the dry run's synthetic replies show the evidence alone fixes the
  analysis outcome of seven of the nine readable cases. The
  [replay section](drift-levels/README.md#readings-replayed-from-the-frozen-cases) owns the rest.
- A level passes the owner's mark when it matches or reassures less. "Not enough recorded yet" is
  more cautious than "None or low" only. Said of a case marked Medium or higher, it hides drift the
  owner saw.

### Amended 2026-10-04: owner, a failure after the person's last message

The owner, approving the Analyze drift plan, amended DEC-26, DEC-23 item 4, and the levels build
of 2026-09-24. Live level, analysis level, answer and correction all anchor a failed check after
the person's latest recorded message. The result's arrival time places it. A same-time, older,
untimed or unlisted failure cannot raise High; it only blocks None or low and stays visible as a
named check with its age. A fresh failure followed by recorded file changes, with no passing
re-run, reads Medium at most on that signal. A separate proven outside-folder signal may raise
High. The Analyze nudge needs a cited signal after that same person boundary.

The zero-outcome-line gate remains first: a goal-only reading answers Can't tell before a failed
check can become its answer. An analysis level of Not enough recorded yet does not replace a
measured live pill (changed 2026-10-21: a stored reading that stands owns the level slot, with a
level or with none; see [the amendment](#amended-2026-10-21-a-level-needs-a-departure)). A
departure leads the analysis reasons. Its short source line is "Analysis
at <time>, intent against cited checks and messages".

A broader recorded pass retires a narrower failure only where explicit Python unittest or pytest
selectors prove coverage, under the same execution prefix, working directory and worker. Module
or file selectors may cover their tests; filtering options, implicit discovery, unknown placement,
another interpreter or explicit environment, another runner and an earlier pass prove no coverage.
The private replay checkpoint holds hashes of the scope and selector ancestry, never the raw
execution prefix. A broader run without a recorded pass leaves the failure in place.

A path-shaped word is weighed as a folder only if that directory exists or contains a recorded
write. Lexical shape alone cannot turn a branch name into a folder. No named folder is a caveat,
not a blocker on None or low. The replay can measure the write half only, because its working
directory is redacted. Before this amendment all 29 realistic-arm High cuts rested on failed
checks; 20 failures were over an hour old, including five about 60 hours old. Exact command
identity kept method failures active after whole-module passes. These changes remove stale alarms;
they do not establish that drift is detected.

### What the live estimate build decided, 2026-09-28

DRC-4696 built the live estimate in the panel and the header. The ruling left these open, and each
was settled on the withholding side.

- The server computes it, not the page. `live_estimate.py` replays the focused session's calls
  through the same tally the record is published from and asks `levels.live_level` after every write
  or shell call, so the level now is the validated function over the published facts and "Rose from"
  comes from the same replay. It is published on the focused project context only, and only when
  the request's project is the session's. The reading route's context, which the unasked lane
  reads, carries none, and neither does a row.
- The replay asks for the level after the last 64 writes or shell calls only. An unbounded replay
  took 24 s on a 3,000-call transcript of targeted checks. A rise older than that window is
  withheld. The replay is held in the server's memory per session and saved words, never written.
  An unchanged parent and child inventory reads no transcript content. A changed inventory gets
  the same bounded scan as the published record. Exact append growth or a safely removable old
  head reuses normalized tally state, while the current window is evaluated again. An unsafe head
  change or uncertain overlap takes the fresh path. Concurrent requests for the same words and
  evidence share one computation.
- The switch is never sent, so the server computes the estimate for the focused session whenever it
  has a saved intent, and the page decides whether to draw it.
- "Rose from <level> at #<n>" is said only when both levels are on the scale and the entry the rise
  came from is still in the record the page numbers. "Not enough recorded yet" is no level to rise
  from, and a call whose entry a later run replaced has no number, so the sentence is left out
  rather than pointed at another entry.
- A level computed against a revision other than the one the panel shows is not drawn.
- The pill shows a level on the scale only. "Not enough recorded yet" stays in the Drift section,
  and the pill is not a link, because the page routes on its fragment.
- The nudge is drawn and never announced: no live region, because the live estimate raises nothing
  (item 5). It is not drawn while an analysis runs, when the level keeps its title and pill, dims
  its meter and drops its detail line, as the design's analyzing state does. Over an unsaved edit to
  saved words the nudge goes too, because Analyze is refused there; the level and the pill stay,
  since they are about the saved words.


### Amended 2026-10-04 (owner): delegated launches

Owner, approving the Analyze drift plan, 2026-10-04. Four reviewed Claude Code
sessions contained five direct questions about delegated work. In two, the work
had stopped after a true running claim. A background launch followed by thirty
quiet minutes occurred at five stops, including both stalls and two development
servers deliberately left running. The parser cannot distinguish those uses.

The page names recorded launches, with counts and clocks, only inside the At-risk item below; the
Drift card no longer draws a Delegated work line
([the amendment](#where-everything-in-more-went)). Partial or
unavailable attribution is named; an unknown count stays unknown. Unpaired and quiet counts
concern this session's own launches, while launch totals can include admitted children. Thirty
quiet minutes after an unpaired launch in the last turn adds an At-risk item and a generic
question to copy into the session. It infers no running process, completion or drift and adds
no words to an Analyze prompt.

Item 6 now admits a timed `background_launch` tool-report fact. It carries the
launch count, tool kind, and completion and activity times when recorded; it
carries no command, task description or output. Explicit background Bash calls,
structural shell background lists, and background Agent, Task and Monitor calls
qualify. `nohup` without a background operator remains a foreground call.

A matching task-notification with a terminal status or an agent result envelope,
or a terminal TaskOutput status, pairs a single launch with completion. One
notification cannot retire several shell jobs launched by the same call. Notifications remain harness records, never the person's intent.
Their text is not published or stored. Only plain hexadecimal child transcript
files under the parent-owned subagent layout qualify, including when the
collector supplies its cached inventory. Compaction copies and links cannot
supply launches or completions. A qualifying child's own sidechain records can
pair its launch; raw tool identifiers match only within their originating
stream, so a child's notification cannot retire a parent's or sibling's launch.
Launch facts stay out of the Analyze
ledger entirely: its existing non-check report formatter calls a row a file
write, which cannot describe a launch. Launches, completions and attributed
child activity are counts and times, never evidence that a process is running.
Independent command-line sessions have no proven parent link and cannot be
joined merely by repository or time. The page must disclose that visibility gap.

The background-run blocker in [DEC-26](#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)
now reads unpaired launches rather than the cumulative launch count. This does
not raise a drift level. The thirty-minute quiet observation belongs to Attention,
with the same distinction between a server and a job left explicit.


### Amended 2026-10-06 (owner): assessment explanations and recorded signals

The Drift result shows each surviving departure's read criterion and retained explanation under
Model assessment, followed by every citation that still resolves after the page's evidence rules.
What the agent claimed keeps its separate explanation and citations. An absent explanation is
named; a withdrawn verdict supplies neither departure prose nor evidence. The existing warnings
for a changed intent, newer work and a reading marked not accurate remain beside the historical
result. The not-accurate warning precedes the promoted account. A running analysis keeps its
existing control slot and hides the old explanation.

Each cited entry shows its activity number when this view has one, its short type, published
harness and worker kind, and recorded event time. A Claude tool-report check's structural call time and paired result time
have separate labels. Other harnesses retain the generic evidence-time label. Dates and UTC make
older evidence unambiguous; an absent time stays unknown. Collector descriptions remain
under Source. Its disclosure key includes the criterion or live-signal scope as well as the cited
entry, following the [reader-state inventory](design-reader-state.md#the-inventory); two accounts
citing the same entry keep their open state and summary focus independently. Reader clauses and
native entry summaries stay upright; retained model detail keeps its own register. These times
locate evidence; they do not date the onset of a departure, and the analysis timestamp remains
the time the reading ran. A departure status now says "Departs; evidence #n".

The live estimate exposes its existing computed citation IDs only in the focused context's
`sources.work.live_levels`. This is not a new session field and does not enter the board, the
reading route or the unasked lane. Its Recorded signals show native check and path reasons and cited event
times, alongside the existing disclosure that it reads checks and file paths rather than intent
meaning. Before any stored reading or attempt, it explicitly says no model assessment exists
yet. A missing entry is still named as unlisted, and a missing reader suppresses the Analyze
nudge. This presentation adds no model call and does not establish that the live estimate
detects semantic drift.

Live reasons admit only the thirteen native check, path and coverage tokens the live producer
can emit. Model-assessment reasons and blockers, including an absent outcome line, and unknown
tokens supply no live explanation. Limits of this estimate separates coverage gaps from recorded events.
At a live estimate's Not enough recorded yet, every known reason stays once in the existing closed
Why not None or low disclosure, except the visible limit that the intent names no folder. An
analysis draws no such level since 2026-10-21, and says its reasons in the answer sentence. Cited entries
remain visible even when no event sentence is needed. An unresolved citation stays unlisted,
never replaced with another entry. A named failed check retains its age and whether files
changed after it. Recorded UTC times retain the complete date and seconds; an absent check
result time says "Result time not recorded."


The owner's 2026-10-06 request for plain explanations and evidence times supersedes the earlier
175-word ceiling for the canonical stored-departure fixture only: its measured limit is now
215 words outside field values. The canonical partial-departure fixture keeps its coverage
limits visible and has a 295-word ceiling, replacing its earlier 270. The unchanged
nondeparture fixtures retain 175. DEC-27 moves the idle explanation to the how-to popup;
its opened body has a 150-word ceiling, including the board-derived limit line, replacing the 85-word idle explanation ceiling. HowTo.test.tsx asserts it on the minimal payload; the real session page's how-to measures over it (178 words) and is a known follow-up. The historical ceilings above record
what was agreed then; this amendment does not rewrite them. These are regression ceilings for
those two canonical examples, not universal reading budgets or runtime citation limits. A
valid reading with two or more citations keeps every surviving support and its recorded times,
even when its explanation needs more words than the one-citation example.

### Amended 2026-10-22: a goal alone is read or refused

Decided by the owner on 2026-10-22. A goal almost always carries its expected outcome, so a reader
who saves only a Goal and presses Analyze drift gets a drift level. This retires rule L7 for the
analysis: `levels.analysis_level` no longer returns "Not enough recorded yet" with `no-outcome-line`
when the intent read holds no outcome line, and item 1's "an analysis needs at least one outcome
line" no longer holds. The live estimate is unchanged (it never read the lines). The other rules
stand: a level needs a departure or a failed check ([2026-10-21](#amended-2026-10-21-a-level-needs-a-departure)),
the evidence floor, and the stored-reading checks.

- **The Goal stands as the one line.** With no outcome line the producer's prompt says so ("No outcome
  lines are given. Read the goal's own stated end state as the outcome, and answer the goal against
  it."), and the level rules treat the Goal row as the one line: `None or low` still needs a
  `consistent` that cites a passing check, so the agent's word alone, or a verdict the model could not
  settle, leaves "Not enough recorded yet" with `line-not-shown-by-a-check`. A departure reads Medium
  and a fresh failed check High, as with a line. No analysis is ever Extreme; that was never changed.
  An outcome line, where one is saved, is read as before and the Goal is not also treated as a line.
- **The reading says which it read.** The cutoff gains "Read against your goal." when the revision
  read holds none. Amended 2026-10-23 (owner): it first read "Read against your goal; no expected
  outcome lines were saved.", and the second half was dropped because noting the absence of an
  optional field tells a reader nothing. A goal-only reading stored before that change keeps the
  longer sentence it was stored with. It is keyed on the revision and not on what the
  press sent, because the unasked lane reads the goal alone while lines are saved, and that is not the
  same statement.
- **`no-outcome-line` stays a known token.** A reading's level is recomputed from the stored reading
  on every collection and never stored, so a level published before this change is recomputed
  under the new rule. The token stays in `levels.REASONS` and the page keeps its sentence ("No
  expected outcome line was saved."), so a stored or older payload that carries it still renders its
  original sentence and not a blank.
- **A fifth result, `goal_unclear`, on the Goal row alone.** Where the shape contract's rule 1 holds
  three results per constraint and the claims row adds a fourth, the Goal row may now answer
  "goal too vague to analyze against" (`reading.RESULT_GOAL_UNCLEAR`, the token `goal_unclear`). It is
  the model's judgement of the words alone, made before it reads the entries, from the Goal and the
  outcome lines if there are any: no keyword and no length rule makes it, and the resolver cannot tell
  a vague goal from a clear one. Like `unsupported` on claims, the token means nothing on an outcome
  line or the claims row, and the store refuses a reading that carries it elsewhere.
- **It stands in place of everything else.** The row takes no citation and no prose. Every other row
  of that reading is published as `not verifiable` with the reason `not-asked`, whatever the reply held,
  so no departure, level, claim or Steer back is drawn for that run. `levels.analysis_level` returns
  "Not enough recorded yet" with the reason `goal-unclear` before any tally.
- **The page says it under the Goal field**, in Compass's voice: "This goal is too vague to analyze
  against. Rewrite it with what should be true when the work is done, then try again." It is read from
  the stored reading, so it stays while the saved goal is the one read and clears the moment the goal
  box is edited or a new revision is saved. A refused run is stored like any reading and counts against
  the daily cap, because the model call was made and the reader's capacity spent.
- **What it cost the prompt.** The trusted header gained two instructions, so the worst header
  measures 9,475 bytes of the share. `INTENT_SHARE_BYTES` rises from 9,216 to 9,728 and the record keeps
  at least 6,656 bytes where it kept 7,168. The final-scope header digests the suite pins changed
  with it and were re-pinned.
- **Not changed.** The abstention study tooling (`mark_abstention.py`, `score_abstention.py`) still
  freezes cases with no outcome line as having no analysis question: it measures a frozen method, and
  amending it is a separate decision.

Amended 2026-10-23 (owner, DRC-4950): the evidence floor stays. A goal-only reading that finds nothing
still draws no level until a passing check shows the goal done, and the card now says so plainly and
says what would let a level be drawn: "Nothing departs from your goal, but no check shows it done, so no
level is drawn. Run a check that shows the goal is done (a test, lint or build), then analyze again."
The sentence is the verdict line's own for the goal-only blocker; where outcome lines exist the existing
wording ("Nothing found against what it read, but no level is drawn: a line of your intent is not shown
by any check.") is unchanged.

### Amended 2026-10-23 (owner): the live level comes from a Haiku check

Amends items 2, 4 and 5 for Claude Code, and [DEC-15's amendment of the same date](#amended-2026-10-23-owner-the-live-monitor-may-evaluate-on-a-cadence-while-the-session-is-viewed)
carries the owner's words. Items 1, 3 and 6 stand, and so does item 5's other half: the monitor never
makes a session eligible for the unasked lane, never feeds, triggers, orders or gates it, and raises no
notification, desktop or page.

**The owner's four follow-up rulings, the same day.**

1. The Haiku check produces the live drift level. It replaces the checks-and-paths estimate as the level
   on the Drift card and in the header pill, in this decision's four levels. An Analyze reading outranks
   it. It never makes a verdict on whether the work met the goal. The model-free estimate stays as the
   fallback when the check is paused, capped, failed or has not run.
2. It ships labelled "Live monitor · Haiku" and is qualified later. The qualification run (an abstention
   check bound to the explicit Haiku id, with an AGY reviewer at `gemini-3.8-flash-medium` or
   `gemini-3.8-flash-high`) is its own piece of work. It blocks nothing, and the Verification issue does
   not wait on it. [DEC-21's 2026-09-23 amendment](#amended-2026-09-23-claude-code-is-built-and-gated)
   is the rule a new producer falls under; this ruling ships ahead of it, on the owner's word.
3. An exact Haiku id is pinned in a separate monitor model setting, defaulting to the newest released
   Haiku id at merge, and a release checklist item names the bump. Floating aliases stay refused, and the
   Sonnet floor for readings is unchanged: the reading validator still refuses Haiku.
4. "Viewing" means the session route is mounted and the tab is visible. A hidden tab pauses ticks, and they
   resume when the tab is visible again within the TTL.

**What changes in the items.** Item 2's "computed without a model" now describes the fallback only. Item 4's
"browser-only, never sent to the server, no new route" is superseded: the switch drives a server lease and
adds routes. An "on" is not remembered across reloads, so a reload shows the switch off until it is pressed.
Item 5's "calls no model" is superseded and its "raises nothing" holds. The source line for the level reads
"Live monitor · Haiku", and says it read the latest turns of the transcript, not that it judged the goal met.

**The remaining decisions.** The lane, cap, TTL, stops, `ended_at` and reload decisions are the
recommendations, taken as given. The ruling on Analyze against a tick is the owner's own, and the
level's floor is ruled in [its own amendment](#amended-2026-10-23-owner-the-haiku-levels-own-none-or-low-floor)
below, which supersedes the floor bullet here.

- **Lane.** A call the reader starts, under [DEC-28's widening](design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts),
  with its own notice kind `monitor` and a one-press off beside it. It is kept out of the unasked lane,
  which is off by default and whose 900 s per-session floor cannot meet a once-a-minute cadence. The
  20-minute banner is the re-consent.
- **Cap.** The monitor's own caps, apart from Analyze's `DAILY_CAP`: at most 30 ticks per session per TTL
  window, and a rolling 24 h cap across the board. Spending either leaves the other untouched. A tick
  skipped because the transcript did not change makes no call and costs nothing. Reservation follows
  `reading_policy`: charge before launch, never refund uncertain spend.
- **Analyze against a tick.** A press of Analyze while a tick holds the `reading.claim` slot cancels the
  tick, and the press then takes the slot. The tick's reserved spend is not refunded, because it is
  uncertain. The owner decided this on 2026-10-23; it is no longer a recommendation.
- **TTL.** The clock is held on the server. The banner is due 20 minutes after the start or after the last
  Yes, and the deadline is 10 minutes after that. No answer by the deadline turns the monitor off with a
  note saying why, Yes resets the clock and No turns it off.
- **Stops.** Pause model calls and `--no-observer-model` both stop the monitor and refuse to start it.
  Pause cancels a tick in flight. Under DEC-28's opt-out, consent means "not paused": the monitor has
  no grant of its own for a reader to give, the `monitor` notice is recorded with the first charged
  call, and a store that cannot say whether the reader paused refuses the call.
- **Sessions with no `ended_at` stamp.** The TTL banner is what stops the monitor. Idleness is not read as
  an end. A session that has an end turns the monitor off and disables the switch.
- **The level's floor.** Superseded by [the owner's floor amendment](#amended-2026-10-23-owner-the-haiku-levels-own-none-or-low-floor).
  The level is held to [DEC-17's shape contract](#dec-17-the-shape-contract) and carries no verdict.
  The model level is absent, not low, until a tick completes.

### Amended 2026-10-23 (owner): the Haiku level's own None or low floor

The owner ruled on 2026-10-23 that the Haiku level has a floor of its own for "None or low", apart from
item 1's floor for the model-free estimate, which asks for a passing check. A model "None or low" stands
when Haiku cites at least one turn it was sent and the estimate shows neither of the blockers item 1
shares across both sources: **no failed check, and no unsettled later direction**. "Too little recorded",
including no passing check, does not block it, so a pull request created with no check run, read by Haiku
as None or low, is published as None or low.

- **The live-only shell blocker is not included.** Item 1 names a shell command that is neither a check
  nor read-only, run after a check's latest pass, as a blocker "for the live estimate" and not for both
  sources, so it binds the estimate alone. The estimate's other blockers (a check not recorded, a
  background run, an incomplete scan, entries not listed) are not item 1's shared two and do not block it
  either.
- **Where a blocker holds**, the estimate's own answer stands in place of the model's None or low: its
  raised level, or "Not enough recorded yet", never None or low.
- **The floor works both ways.** A raised estimate (Medium, High or Extreme) above what the model said is
  published over it, because a model reading a window of turns cannot clear a failed check it was never
  shown. A model that says Not enough over an estimate of None or low keeps its abstention.
- **The model level is published beside the estimate** as the fallback it replaces, with the estimate's
  reasons, so a page can say which one decided.

### Amended 2026-10-24 (owner): an Analyze reading's None or low may rest on recorded harness facts

This extends [the 2026-10-23 ruling on the Haiku level's own floor](#amended-2026-10-23-owner-the-haiku-levels-own-none-or-low-floor),
which let the monitor's None or low stand with no passing check, to the stored reading's analysis level, more
strictly. It was taken under the owner's standing instruction to act on the lead's recommendations, after a
live walk where a session that used a skill and created a pull request read Consistent on its goal line and
still drew no level, because no check had run.

An analysis level may be None or low with no passing check when all of these hold:

- every goal line, and every outcome line, is Consistent, and none carries a `why`;
- every outcome line that is Consistent cites at least one recorded harness fact: a pull request created, a
  skill used (item 3's amendment of 2026-10-23), or a passing check as before, and not only the agent's or
  the reader's messages. A goal that stands alone as the one outcome line is read the same way;
- there is no failed check, no unsettled later direction, no departure and no unsettled claim, which is the
  floor's own blockers and unchanged;
- the scan is complete enough that the existing abstention rules do not already block it.

The agent's words alone still never lift the level, and a line resting on words beside one resting on a fact
keeps the floor off. A pull request or a skill does not age: it is a record that something was done, so a
later file write does not turn it into a pass followed by a change. The live estimate's floor (item 1) is not
touched; it still asks for a passing check.

### Amended 2026-10-27 (owner): a CI fact is a recorded harness fact

A pull request's CI state read under
[DEC-30](#dec-30-compass-may-read-a-pull-requests-ci-state-when-the-reader-presses-analyze) counts as a
recorded harness fact for the analysis level's None or low, the same as a pull request created or a skill used
in the 2026-10-24 amendment above. The other conditions of that amendment hold unchanged. A pending CI state is
never a pass, a head that moved past the session's commit does not settle the session's lines, and a session
that changed the CI configuration carries the caution DEC-30 names, so the floor rests on a CI fact only when
DEC-30 lets that fact stand. Later file writes in the transcript do not age a CI fact, and DEC-30 item 4's
head-equals-HEAD test is the only ageing it has. The live estimate's floor (item 1) is not touched.

### Amended 2026-10-27 (owner): text a reason quotes, found in a recorded check's output

A real session's evaluator quoted two CI rows from the last poll (`"coverage-gate pass"`, `"server-unittest pass"`)
and the card could only say it could not confirm the claim, because
[the verdict test](#amended-2026-10-22-a-goal-met-verdict-is-a-claim) reads a reason for file names, check kinds and
pull requests and nothing else. The test now also asks whether text the reason puts in quotes is in the output of a
check Compass recorded, and says where it is.

- **Where it may look.** Only the output the press already attributes to one recorded check
  ([DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) item 2, the single-check and
  no-other-printer rule, with the last-line reading of
  [DEC-29](#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)), for a
  tier 1 or 2 check whose latest foreground run came at or before the verdict, at or after the goal's own set
  time, with no later command that may have changed files. A read, a `WebFetch`, an `echo`, a command beside the
  check, a second check in the same call and a tier 3 command are never searched. The text searched is the last
  180 characters the press already holds for the check, redacted; the search reads nothing more and widens no
  allowance.
- **Why not anywhere in the transcript.** The evaluator read the transcript, so its quote is in some tool output by
  construction, and `echo "coverage-gate pass"` would satisfy a search of all of it. The only text that can say
  something is output a recorded check owns.
- **Which spans.** Double or curly double quotes only: a reason sets a file, a command or an identifier in backticks
  or single quotes far more often than a line a run printed, so those are not read. A span must be 12 to 180
  characters (the output searched is only the last 180) once whitespace is folded and case is ignored, and at most
  eight are looked for. A span made only of result words ("pass", "ok", "all checks passed", "no issues found") is
  ignored. A span the check's own command line holds is not found there, and neither are the `> ` lines a package
  runner echoes for its recipe; a line the script itself prints is still the check's output and is searched. A span that
  names a remote job (the shapes
  [the 2026-10-27 CI job amendment](#amended-2026-10-27-a-ci-job-named-in-the-reason-is-not-a-local-check) lists) is
  left to the pull request's CI facts. A span that holds a credential shape or a redaction marker is never searched.
- **What it says.** "The quoted text is in the output of check #n", and the answer stays `unconfirmed`: output that
  holds a phrase is not a passing check, so this never yields `agrees` and never raises a level. It comes after every
  other answer, so a failed check still disputes and a written file or a passing check of the claimed kind still
  agrees as before. The stored `why` is `quoted-in-check` with `cites` the check entries and `quoted`, the count of
  distinct spans found (1 to 8). Nothing of the searched output or of the span is stored, published or sent. The
  search runs whether or not tool output is allowed, since it sends nothing.
- **Rejected:** searching every tool output (an `echo` satisfies it); searching a check's output for the quote and
  calling it agreement (a phrase in output is not a result); matching a quoted job name to a CI fact by its name,
  which stays with the pull request's CI facts and the number the reason names.

## DEC-27: the first view of a session is the goal, Analyze drift and the result

Decided 2026-10-11 (DRC-4855), on the Actions Front and Center project, in the milestone "Intent
and drift first". DRC-4856 to DRC-4866 build it. The owner signed every row below as recommended.

The question was what a new reader sees first. A reviewer who tried Compass on recorded sessions
said the interface is too complicated, that people do not know where to start, and that only three
things matter: the goal, a view of where the session drifted from it, and the analysis. They asked
for an experiment that keeps those three and removes the rest. The owner's direction of the same
day asked for the Copy ID, Copy link and Copy command buttons to go, a how-to popup beside the
feature, and a path to a result in as few clicks as possible.

Two principles decide every row. The first view of a session is the goal, one Analyze drift control
and the result; anything else is quiet or one press away. A privacy promise or an honest limit
moves and is never deleted: Discard everything, "What is sent", the off switch for readings and the
sentence about work the page cannot see stay reachable.

### The signed table

| # | Item | Ruling | Amends |
| -- | -- | -- | -- |
| 1 | Expected outcome | One optional empty line by default, labelled optional. "Add a line" and per-line Remove appear after use. The field stays: the level and the copied correction are built from it. | DEC-24 item 3 |
| 2 | The resume command after the Copy buttons go | It lives on Attention, the waiting panel and the project rail only, not on the session page. | The promise map's P2 "way back" clause and its line beside departures, NUI-5, NUI-8 |
| 3 | "Analyze again" | One run control per state. A second press appears only when new work was recorded or the intent changed after the result, and it names which. | The 2026-10-01 amendment "the result takes the button's place" (Q3) |
| 4 | The Direction question | Its summary shrinks to one line with the count. Keep still draws every direction whole before settling, so it keeps its two presses. | Nothing; the 2026-09-28 ruling stands and is part of the click budget |
| 5 | A typed goal on an ended session | The goal box says before the reader types that what they save now is kept but Analyze will not check the session against it; intent saved before the end and the goal taken from their prompt remain eligible (reworded 2026-10-23 so a new reader can parse it). Amended 2026-10-14: a confirmed save repeats the same caveat beside "Saved as a new revision." | The 2026-10-01 note on what a press says beside the button |
| 6a | Use your prompt | Stays visible beside the goal. It is the only way to choose a different goal on an ended session. | Nothing |
| 6b | Live monitor | Moves into More. It is off by default and needs no model. | DEC-26 item 4 (placement only) |
| 6c | Discard everything | Moves into More and stays reachable. | Nothing; SECURITY.md still describes it |
| 6d | What analysis does | Replaced by the "How Intent and drift works" popup. One explainer, not two. | Nothing |
| 6e | Delegated work | Moved into More and stayed reachable from Analyze drift. Amended 2026-10-21: the Drift card no longer draws the line, and the launches surface only in the At-risk item ([where it went](#where-everything-in-more-went)). It is an honest limit. | Nothing |
| 6f | Pause model calls | Moves into More. The promise map's off switch stays. | Nothing |
| 6g | Add to my intent on each activity row | Always visible on a row that holds a later direction. Amended 2026-10-12: a control that appears only on hover is one a reader never learns is there. DEC-24 item 3 needs it. | Nothing |
| 6h | "No terminal to raise" and its "Why" | Shown only when the session is blocked on the reader. | DEC-20 (the raise is primary when a session is blocked) |

The first view at rest holds about eight buttons, links and disclosure summaries: How Intent and
drift works, Use your prompt, the goal box, Save intent, Analyze drift (or the control the rules
make primary), What is sent, More, and the way back to Sessions. The optional outcome line is a
field and is not counted.

Amended 2026-10-12 by the owner: from 1101px wide the page is two columns, the session's activity on
the left and the Intent and drift panel on the right, level at the top. Below that it is one column
with the panel first, so the goal stays in the first view on a phone. The count above is the panel
and the page chrome. The activity column's own disclosures (About this record, Session facts and the
reports line) now also show beside it at 1280 by 800, and are held by the complete inventory of 14.

### Amended 2026-10-14: what the how-to, the live line and a late save say

Four sentences, each at the place a reader relies on it. None adds a control.

- The how-to popup says which lines a reading can settle and which it cannot. A command whose latest
  run, not piped into another command, fails settles a departure, and one that passes with nothing
  written after it settles a consistent. A statement about the whole tree, such as a folder limit, was
  not settled by a reading and the live estimate weighed it; a recorded write that breaks one now
  also departs ([the 2026-10-21 amendment](#amended-2026-10-21-the-record-settles-a-line)). The popup also carries the Claude
  reader's limit
  ([the DEC-21 amendment](#amended-2026-10-14-owner-the-page-says-the-claude-readers-accuracy-check-has-not-passed)).
  The 150-word ceiling above holds: the opened body now measures 146 words on Claude Code and Pi and
  150 on a harness with no reader, and the two additions were written to fit it.
- The reason for "Can't tell" stays inside Evidence, as this design keeps evidence one click away
  (owner, 2026-10-14; superseded: [the reason is now in view](#amended-2026-10-21-the-record-settles-a-line)). Its sentence for `check-does-not-show-it` no longer says "The check it cited":
  the producer empties a reading's published cites whenever it withdraws a verdict, so the page
  cannot tell a check that does not show the line from a write, or nothing, that was cited. It reads
  "What it cited does not show this: a departure needs its latest run failing, and a consistent its
  latest run passing with no change after it, both after the words you saved."
- The live estimate's line keeps "Reads checks and file paths, not what your intent says" (DEC-26
  item 1 quotes that clause) and adds that files written by shell commands, such as a build, are not
  seen. That is item 1's own record ("a file a shell command changes is not seen"); the command itself
  is not ignored, because a shell command that is neither a check nor read-only, run after a passing
  check, still blocks None or low.
- Signed-table row 5: on an ended session, a confirmed save repeats the goal box's caveat, in the same
  words, beside "Saved as a new revision.", and only there. The goal box still carries it before the
  reader types.

### The Sessions screen

Keep the "running" and "waiting on you" counters; move the "exact requests" and "reported blocks"
counters to Attention. Merge the two header disclosures, "How rows are split" and "Goal sources",
into the how-to. Keep all six columns: cutting NEXT or BLOCKED would change what the promise map
says about what a session plans next and whether it is blocked, and that is a promise change for
the owner to make on its own. The header carries one permanent orientation sentence and the
how-to button, which amends DEC-20's state table ("one screen-level sentence on a default run").
Sessions comes before Projects in the tab order.

### Measured 2026-10-11

The deterministic analysis level for an intent with a goal and no outcome line, on a synthetic
reading with no evidence: `levels.analysis_level(reading, evidence, outcome_lines=0)` returns
`not_enough` with the reason `no-outcome-line`, which the page words "Not enough recorded yet"
(DEC-26 item 1, rule L7: zero outcome lines is too little whatever the Goal says). A reading that
exists but is not well formed also returns `not_enough`, with `reading-malformed`. The model
reading itself poses the Goal and each outcome line as separate constraints (the shape contract's
rule 6), so an analysis runs on a goal alone and answers the Goal. What the model says to a goal
alone was not measured: that takes a model call under the reader's Allow and is part of the
verification walk.

### What it costs

A reader who adds no outcome line never sees a level on the pill: the analysis answers the Goal
only. The how-to says so, and says that one line gives a level. The result then reads "Can't tell"
unless the goal departs, which is a valid result and not an error (amended 2026-10-21: the card no
longer draws "Not enough recorded yet" for a reading, see
[a level needs a departure](#amended-2026-10-21-a-level-needs-a-departure)). A goal typed and saved after the end is still refused; a typed goal
saved before the end remains eligible. The note in row 5 says so before the reader types. Removing
the departure rows' Copy command retracts a clause of the
promise map, and this ruling authorises it. The click budget that follows from the rows is in the
milestone: three clicks for an accepted draft, four with later directions, four or five for a
typed goal.

### Session first-view build, 2026-10-12

The unblocked session header follows the goal and analysis panel, before Session activity; a blocked
session retains its header raise and waiting panel above the goal. More had six groups at most
(amended 2026-10-21: Delegated work left, so five, and the groups themselves moved out of More, see
[where everything in More went](#where-everything-in-more-went)):
Live monitor with its explanation, saved-word caveats and Discard everything, Pause model calls, Saved with Clear, and settled or unread later directions. The privacy disclosure,
model-request count and daily cap stay beside Analyze. The goal and primary fit at 1280 by 800 and
375 by 667; 320 px and the 640 px layout representing 200% zoom retain wrapping and document scroll.

The count-only Direction summary quotes no whole text, so even a sole short direction needs the
opening press before the settlement press. The first-view browser proof injects one extra button
and rejects it. The idle drafted fixture's visible panel text, excluding field values and closed
bodies, has a 90-word ceiling. The opened how-to retains its separate 150-word ceiling.

The fresh Claude Code fixture inventory below includes the session's project link and the Sessions
breadcrumb. Before: 19 controls across the page, 13 in the 1280 by 800 viewport. After: 14 across
the page, eight in that viewport. The activity disclosures remain below the first view in one column; none of
their sentences or controls are removed. (Beside the panel from 1101px wide, three of them showed in
that viewport under the 2026-10-12 amendment above; the 2026-10-19 reversal to one column supersedes
that, and Full activity is collapsed at the foot of the page.) The switch's accessible name is Live monitor.

| Button, link or disclosure | Before | After |
| -- | -- | -- |
| Sessions breadcrumb | First view | First view |
| Project link | First view | First view |
| No terminal to raise: Why | First view | Blocked only |
| How Intent and drift works | First view | The Intent card's More menu |
| Use your prompt | First view | First view |
| Clear | First view | The Intent card's More menu |
| Remove line 1 | First view | First view |
| + Add a line | First view | First view |
| Undo changes | First view | First view, inert until there is something to undo |
| Save intent | First view | First view |
| Live monitor | Below fold | More |
| Analyze drift | Below fold | First view |
| What is sent | Below fold | First view |
| More | Absent | First view |
| About this record | First view | Below fold |
| Session facts | First view | Below fold |
| Command-shape reports: off | First view | Below fold |
| Why two cards | Below fold | Below fold |
| Intent log | Below fold | Below fold |
| What it keeps | Below fold | Below fold |

Correction round, 2026-10-12: the surviving departure's Steer back precedes the result's evidence
rows so it remains in the first view. Add a line shares the Save intent row,
removing one separate row before Keep. A used outcome has Remove beside its box. Keep precedes
the level and direction selector; the visible summary is the count, with its floor retained in
the accessible sentence. A blocked header limits the visible title to two lines, retaining the
full title in its text and title attribute, and moves its measured counts to Session activity.
The session age appends to the existing identity line, wrapping only when necessary at the
phone width. It uses the published start or the first message time, states that fallback in its
exact-local-time tooltip, and draws nothing when both are absent. It adds no separate metadata
block before the signed content. Storybook verifies phone wrapping; the retired first-view proof
is not a new measurement of this addition.
The first-view proof covers stored results, one and four
unsettled directions, short and wrapped blocked headers, and touch activity actions at desktop
and phone sizes; each placement and the touch fallback have a rejecting mutation.

### Amended 2026-10-19 (owner): one column again

The owner reversed the 2026-10-12 layout amendment above for the session page in the milestone that
adds a session summary. From top to bottom the page is the header, the answer block when the session
needs input, the Intent card, the What the session has done card, the Drift card, and a collapsed
Full activity section, at every width. The session page's More disclosure is retired, and every
control, sentence and limit in it gets a new home, so the principle above, that a privacy promise or
an honest limit moves and is never deleted, still holds. The record is
[DEC-28](#dec-28-a-model-may-summarize-a-session-and-the-summary-is-kept).

The owner signed this reversal on 2026-10-19 in the milestone "Session page: what the session did,
and where it left your intent"; that sign-off supersedes the 2026-10-12 layout amendment above.

#### Where everything in More went

The written inventory of the retired session More, by group in its order, with the new home of each
part. Nothing in it was dropped. The stories under `Sessions/One-column page` assert each row by role,
name or text in its new home, with three exceptions no fixture there reaches: What became of discarded
words, the armed confirmation of Discard everything (its offer is asserted), and Pause model calls
under the control where no popover is drawn (its place in the popover is asserted).

| More held | Kind | New home |
| -- | -- | -- |
| Live monitor switch | Control | Drift settings in the Drift card's heading ([the one-state amendment](#amended-2026-10-21-the-drift-card-has-one-state-at-a-time)) |
| "How far the session has moved from the goal" | Sentence | The Drift card's heading, under the title |
| "Shows a level after every turn, from checks and file paths, with no model call. The level shows here and in the header." (Claude Code, annotations on) | Limit | Drift settings, under the switch, as its description |
| About these saved words (the ended-session note and the binding sentence) | Disclosure and limits | The Intent card, under the save |
| What became of discarded words | Sentences | The Intent card, under the save |
| Discard everything, and its armed confirmation | Control and warning | The Intent card, under the save |
| Delegated work, and the "still running?" check | Limit | Not on the Drift card (amended 2026-10-21): it was a bookkeeping fact about subagents tied to no line of the reading, and the reader had no action to take on it |
| Pause model calls | Control | Drift settings, and the "What is sent" disclosure beside what it stops; Resume model calls beside Drift settings while paused; under the control where no disclosure is drawn (a running analysis, no reader, the consent step, a route with no disclosure) |
| Saved · reads from, with its revision line, "Each save is a revision." and the binding key | Disclosure | The Intent card, beside its More menu |
| "Drift is measured against these. Edit anything that is off." | Sentence | The Intent card, under the save |
| Clear | Control | The Intent card's More menu |
| Later directions: unknown, none or settled, with "Nothing here decides…" | Disclosure and limit | The Intent card, last |

The activity column becomes **Full activity**, collapsed at the foot of the page. It keeps CURRENT
ACTIVITY, the numbered list newest first, subagents, session facts, the current task, health,
tasks, command-shape reports, notifications and How it landed, in that order, and a blocked
session's measured line. The header gains a status dot beside the state word, which now leads the
measured line ("working · running Bash · turn started 3m ago"); the raise control, the drift pill
and the reading cap banner stay where they were. A finding's citation, drawn as "Show cited entries in
Full activity" when this amendment was written and since replaced by each cited entry's own number
(see the departure-card amendment below), opens the section, reads older record pages until every cited entry is held, the
record's start or the page cap, and moves focus to the first cited row. It is offered while any cited
entry is unloaded and the record has older pages, whatever the intent's current window, so a retained
reading that cites an entry from before that window keeps its way there. An entry no page returns is
named in a status sentence, which takes focus instead. The sentence says the record does not list the
entry only when the read reached the record's start; a read the page cap or a failed page ended says
it stopped short and that Show more may load it. Where every cited entry is held but the reading's own
window, request or limit sets them aside, the sentence says that. The sentence answers one press on one
reading: a later press, a new reading or another session takes it down, and a read that ends after a
later press began publishes nothing. Escape on the row, the sentence or "Back to the finding" returns
focus to the citation without leaving the session page, and both moves scroll without animation when
the reader prefers reduced motion.

### Amended 2026-10-19 (owner): each departure is a card

The 2026-10-15 feedback read "2 departures" above two "Model assessment" blocks as something it did
not know how to read, and read "Analysis at 22:27" as a time inside the session. The Drift card's
result is now drawn as the design file draws it. Nothing about the reading changes: the producer,
what it stores and the page's evidence rules are as before.

- The card header names the model, from the stored stamp's `<model> · read at` shape and nothing
  else, and "Analysis last run HH:MM" from `read_at`. The header is the one place on the card that says the
  read time: the level's analysis line and What the analysis read leave it out (amended 2026-10-21).
  A refused or malformed reading draws no header line.
- Under a departure the answer reads "Departs from your intent" with its count, then one card per
  departure in the reading's order. A card's label names the constraint ("Departure · Goal",
  "Departure · Expected outcome 2", numbered only where more than one line was read). Its headline is
  the constraint's own saved words, because no model writes one
  ([DEC-28](design-session-summary.md#the-ruling), answer 7). What is the cited entries, each as its
  activity number and the kind of entry Compass names ("failed check", "Agent message", "Your message"),
  never the entry's own summary: for a message that is the agent's or the person's text, and an agent's
  "Done" would then stand inside the result. Why, under "Why Compass reads this as
  drift", is the stored `detail`, the one string the model wrote. The ruled status ("Departs;
  evidence #n") follows, and the line's label, full status, limit and each entry's recorded time and
  source stay one press away under Evidence. "Model assessment" and "Read intent:" are gone; the
  headline carries the read words.
- The shape already guarantees that a departure holds at least one cited entry: a row with no resolved
  citation is demoted to can't tell, so no card stands on nothing a reader can reach.
- Every other line follows a divider as one quiet row, in the words `resultStatus` and `claimStatus`
  already used: not reached at this stop, consistent with a check, the agent or the session, can't
  tell, nothing shown, and the claim states. The reason for can't tell stayed inside Evidence, as the
  2026-10-14 ruling kept it; [the 2026-10-21 amendment](#amended-2026-10-21-the-record-settles-a-line)
  supersedes that. A contradicted claim keeps its
  explanation in view, or "No explanation was retained for this assessment." where none was stored,
  and its cited entries' records under Evidence. A claims row the shape withdraws is not
  drawn, as before, so a claim the page cannot place has no row of its own.
- Each number replaces "Show cited entries". It opens Full activity at that entry, with every entry
  the finding cites marked, and "Back to the finding" returns to the number. Where no cited entry is
  held yet, "Load the cited entries" keeps the press that reads older pages.
- Steer back follows the rows, and its weight is unchanged: primary under a departure, or under a
  failed check with no reader, never for a claim alone, and not while the session waits on the
  reader. Update intent instead stays beside it, and the correction still opens in place.
- Mark as inaccurate and What the analysis read share one footer row, with their effects and Undo.
- The question before a later direction, a missing reader, a refused or malformed reading and the
  departures raised while you were away keep their behavior and their place.

This supersedes the layout of [the 2026-10-06 amendment](#amended-2026-10-06-owner-assessment-explanations-and-recorded-signals)
for a departure's explanation and citations, not what it shows.

### Amended 2026-10-20: the answer first, and What quotes the entry

A fresh-eyes usability review of the built page found that the Drift card buried its answer: the
monitor's description, a range line, a goal-source note and a status line stood between the heading
and the departures, and What gave "#5 Agent message" while the line the departure is about sat
behind Evidence. Nothing about the reading changes; these are placement and wording.

- One plain sentence leads the card: the analysis level's word, the count of departures and what
  and when they rest on ("Medium: 2 departures, both at the agent's message at 09:15."), derived
  from the stored reading and the entries it cites. "Can't tell" and "Not reached" carry no level
  word, so the sentence never reassures where the reading could not settle. It is not drawn over a
  running analysis, an unreadable reading or one marked inaccurate.
- The level meter follows it in every state, including while a later direction's question stands.
- What on a departure card gives each cited entry's own words, attributed and quoted ('Agent said:
  "…"', 'You said: "…"', "Failed check: …"), bounded and on one line, with a check glyph said as
  "[check mark]". This amends the 2026-10-19 amendment's "never the entry's own summary" for
  departure cards only, on the strength of the attributed-speech ruling: quoted and attributed, an
  agent's "Done" reads as the agent's. Quiet rows keep the entry's kind, so a line read as consistent
  never stands beside the agent's own "Done". The owner may reverse this; the switch is one
  argument (`CitedEntries` `quote`).
- "Departs; evidence #n" is said once, inside Evidence. The analysis level's entry range and reason,
  and the goal-source note ("The adopted source was found…"), are under What the analysis read. The
  Live monitor's description is the switch's helper text.
- Evidence heads with the line's label in a sentence's case, then "#n · Agent message · HH:MM", with
  the record-type tag under Source and recorded times in the reader's local zone.
- The count beside the control reads "N drift checks requested": the store counts readings alone,
  and "model requests" read 2 beside four model calls once summaries also ran.
- Pause model calls, or Resume model calls while paused, stands in the card's head in every state.
  A press on the copy inside What is sent closes that popover. While paused, Analyze stays in its
  place, refused, rather than becoming a second Resume.
- A stale result's banner names the reader's message it predates ("This check is from before your
  09:20 message."), and its one run control reads "Check again". A later direction's question still
  owns the only run path while it stands, as DEC-27 rules.

### Amended 2026-10-21: a level needs a departure

Three walks of the session page (a finished session, a mid-turn reading, a consistent reading)
found the Drift level reported where the reading found nothing to report: Medium in the bar and
the header with "Can't tell" on every line; Medium left standing after a later reading cleared the
departure it rested on; and, on the other side, "Not enough recorded yet" behind "Why not None or
low" over a reading whose every line was Consistent. This is the repository's "structurally
present default" invariant: a level was a field every reading carried, so it said something about
the schema and not about the session.

The rule: the page draws a level above None or low only beside a departure the reading it shows
carries, counted after the page's own rules (a departure whose citation the record does not hold is
not one). It reads the departures from the same shape the departure cards and the answer read, so
the level, the count and the cards cannot disagree.

- `levels.analysis_level` is unchanged. It still reads Medium from a contradicted claim or a pass
  followed by a change and High from a failed check, and publishes the reasons; those stay data. The
  page withholds the level in `analysisLevel` (`frontend/src/drift/level.ts`), the way it already held
  "None or low" to its own rows. A failed check is still said: the answer reads "A check failed at
  11:03." beside the level's absence, and a contradicted claim keeps its row. This re-rules the
  2026-10-20 amendment's wording that a Medium with no departure "says why the level stands", and
  the sentence of the levels build that a level could read Medium beside "Can't tell".
- A stored reading that stands owns the level slot, with a level or with none. With none, the
  live estimate does not draw in its place: it reads checks and file paths and never the intent, so a
  Medium from it beside a reading that found no departure is the same claim in another source's
  voice. The live estimate draws when no reading stands for the saved words, and keeps its own source
  line there. This reverses the 2026-10-04 sentence that an analysis of "Not enough recorded yet"
  does not replace a measured live pill.
- With no level, the card draws no bar. The one answer sentence says what the reading did find, and
  where every line is Consistent and the level is held back it says why in the same sentence ("Nothing
  found against what it read, but no level is drawn: a line of your intent is not shown by any
  check."). The "Why not None or low" disclosure is a live estimate's alone. When the page itself
  holds a server None or low back, it adds the row that held it as a reason.
- The header pill says "so far" while the session runs, and when the reading it shows read a running
  turn, because a running session's level can still move and a mid-flight reading covers only the work up
  to it. A state the board does not publish claims neither.
- A departure that clears is named once, on the reading that no longer finds it ("The departure from
  the 11:02 reading no longer holds."), with the count where there were several, and where a reading
  departs less often than the one before it, with the difference: two departures that become one name
  the one that went. A departure that only moved (the same count, worded or cited differently, with no
  correction pasted between) was no clear, because a model words one finding differently each time it
  reads; amended 2026-10-21 (the edges of recognising a pasted correction, item 3), a departure replaced
  by one that shares neither its reason nor a cited entry is named. Without a correction the count is
  the larger of the fall and the departures replaced one for one, never more than were no longer found
  or than now stand, so a reworded survivor never overstates what the tab watched. A correction pasted between the two readings keeps
  its own rule: each departure it named that no longer stands is named, with another standing or not.
  The page holds the
  earlier reading's departure count in the tab and says nothing it did not watch, so a reload
  names nothing. Storing the earlier departures with the reading was rejected: it is a new published
  field declared in five places (the invariant above), it would name the clear for as long as the
  record lasts, and the owner's complaint was a silent change between two readings the reader watched.
  The line does not say why the departure cleared, because nothing the page holds says.

What this does not claim. The withheld level is a correction of what the page draws and not a
measurement: a session with a failed check and no departure draws no level at all. The owner may
prefer the live estimate to keep drawing beside such a reading; that is one expression in
`buildModel` and `DriftLevelView` (`analysis ?? estimate`), and the four behaviours above are
asserted by `LevelNeedsDeparture.test.tsx`, `ClearedDeparture.test.tsx`, `verdict.test.ts` and the
stories under "Drift / A level needs a departure".

#### Clarified 2026-10-21: the edges of the departure-backed level

Three cases the main rule left open, each said only where the page can show it is true.

- A reading that stands with no level owns the level slot, so a live estimate the reader switched
  on, with a level to draw, is hidden behind it. The card says so under the verdict ("The live
  estimate is not drawn while this reading stands: it reads checks and file paths, never your
  intent."), without naming the hidden level, because naming it would draw the Medium the rule
  withholds. It says nothing with the switch off, with no live level to hide, or over a reading that
  draws its own level.
- An empty verdict early in a session says it is early. The answer must be the empty one ("Can't
  tell from what was read.") over a line that names an expected outcome, the reading must not be of a
  finished session, and the record must have been read from its start, because a start the page cannot
  see would make "early" a default (the invariant `AGENTS.md` calls a structurally present default).
  The span is the first entry the page holds to the end of what the reading read, and it is early
  under ten minutes: a judgement, not a measurement, set where a session has usually not yet run a
  check. It names that span ("Early: this reading covers only the first 8m of the session. Read again
  once it has run its checks.").
- The how-to, the skill and the promise map said "Not enough recorded yet" is normal until an expected
  outcome line is added. The card no longer draws that level for a reading, so the sentence now says
  what a reader sees: with no expected outcome line, no level, and "Can't tell" unless your goal departs.
  "Not enough recorded yet" stays the live estimate's word.

A departure that moved is named as replaced even where no correction was pasted, as the amendment on the
edges of recognising a pasted correction records; the decision that stood here was reversed there.

### Amended 2026-10-21: a running turn is unfinished

A reading taken mid-turn reported a departure because "the session ends with the probe still
showing wrong output, no rerun and no push", while the agent was running that rerun. The reading
was read at the mid-flight scope, which the prompt already tells the model covers the work so far
and gives it `not_reached` for; it answered in the shape of a final reading anyway.

Decision: a guard in the resolver, not a change to the prompt. The non-final header has 27 of 9,216
bytes spare, a changed header needs a fresh qualification before a scored result stands (the
2026-10-06 clarification), and no number of added words makes a model reliable. The producer already
applies every other rule that way, so a departure that does not hold never reaches storage.

The guard (`reading._while_running`, applied by `reading.resolve` after each constraint's own rules):
at the mid-flight scope, a departure on an intent line whose every citation is words (the person's
or the agent's own messages) is stored as `not reached at this stop`, with its explanation kept as
what the record shows it waiting on, when work is going on after the latest of those words. Work is
going on in two ways:

- A call is still in flight, in a Claude Code session only. A call has no entry until its result
  arrives, so the press reads the transcript itself for the newest call it has no result for (`project_context.claude_open_call_at`)
  and passes its time to `resolve`. A question put to the reader is not work going on, and a message
  the reader sent after a call closes it: an interrupted call is never answered, and nothing is
  running then. Nothing is stored; the call is read at press time and used once.
- A check or a write recorded after the words **bears on the line**. A goal has no narrower meaning
  than the whole session, so any later check or write bears on it. An outcome line that names a path or
  claims the result of a kind of check ("the tests pass") is borne on only by a check that covers it
  (`covers_line`) or by a write to a path it names; a line that does neither cannot tell one piece of
  work from another, so any later work bears on it. A lint pass beside "the tests pass", or a write to
  a docs file beside a line about `src/probe.py`, leaves the departure standing.

Everything the 2026-10-04 amendment says unfinished work does not excuse stands:

- A citation that shows work, a failed check or a write, is what the departure rests on and the
  guard leaves it. A failed relevant check is still a departure, with a call in flight or not.
- A stall stands: with nothing in flight and no check or write that bears on the line recorded after
  the cited words, nothing kept going.
- The claims row is untouched; a contradicted claim is not unfinished work.
- A last-turn or final reading is untouched: the turn is over.
- The idle press that reads mid-flight (an idle session with no recorded finish) is covered by the
  recorded half of the guard, as a running session is, because both are read up to their last
  recorded entry. It is not covered by the in-flight half: the session is not running, so an
  unanswered call there is an interruption, and `produce` asks for the call only of a running
  session.

What it cannot see. The in-flight half is Claude Code's alone: the press passes `produce` the lookup
only for a Claude Code row with a transcript (`http_api`), and every other harness is held by the recorded
half. Extending it was not done: each harness records an unanswered call differently or not at all, and a
lookup that reads one wrongly would excuse a real departure. A call in flight is read from the tail of the transcript the press reads, so a
call older than that tail, or one a subagent runs in a transcript of its own, is not seen; the
subagent's launching call in the parent is. It is an assembly control, not a measurement of model
accuracy: the case is a recorded shape (the agent said what it would do, kept working, and the model
read the missing end as a departure), held by
`AReadingOfARunningTurnDoesNotCallWorkInProgressADeparture` in `test_reading.py` and by
`test_running_turn_guard.py`, which builds a mid-call transcript in the recorded field shapes and
reads it through `produce`. Eleven negative controls hold the other side: nine in the first class
and two in the second. A message-only departure that is real still returns at the next reading, and
at the session's end as a final one. A `not_reached` line raises no level and no Steer back (the
2026-10-04 amendment), so the demotion errs the cautious way.

### Amended 2026-10-21: a pasted correction is Compass's words, and a kept direction is no evidence

A reader who pasted a Steer back correction into the session and read it again saw `1 later
direction` with `Use this as my goal` offered for it, the direction quoted inside the harness's
`<pasted_content id=…>` tags, a departure whose What led with `You said: "Back to my goal…"`, and a
rebuilt correction that dated the departure to the moment of the steer. Two session walks measured it
(the recorded shape is in [the captures](captures/README.md)). Claude Code 2.1.305 stores a paste as
the content string `\n\n<pasted_content id="N">\nTEXT\n</pasted_content>\n`, so the digest of the
pasted message never equalled the digest of the text the reader copied, and item 9 of
[DEC-24](#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
never recognised it. The same walks showed a direction the reader had just kept with `Keep my intent`
as the first quote under a later departure.

1. The two tags are the harness's, and the words between them are the reader's or, for a correction
   pasted back, Compass's. `records.strip_paste_wrapper` takes the tags off, and nothing else: a
   tag that only begins the same is another tag. It runs where a user message becomes the words the
   page quotes (`observer._message_from`, so the fact's `reader_words`, the direction a press opens
   and the draft of `Use this as my goal` never carry the wrapper) and before the digest of a
   message is taken (`copied_corrections`). The page strips the same tags from a direction an older
   server or a republished history still sends with them. Words typed around a paste stay in the
   message, so a correction with a sentence before or after it is the reader's own.
2. Item 9's normalisation is exact, by the owner's ruling of 2026-09-28, and stays what the first
   digest computes. A second digest of the text with every run of whitespace folded to one space
   forgives a reader who reflowed lines or widened a gap, as this issue's scope asked ("unedited, or
   edited only in whitespace"). It is stored beside the first, `folded` on each waiting copy, and a
   copy stored before it existed keeps matching on the first alone. A changed word, or a space
   inside a word, is still the reader's own message. This departs from item 9's "any edit is a
   different digest" for whitespace alone.
3. A departure never stands on the reader's words that settled nothing. `reading.settled_reader_words`
   names the user messages that are a correction Compass built (`copied`) or a later direction the
   reader kept (after the intent's floor, up to what Keep settled through), and `resolve` drops
   them from a departure's citations, whatever the model cited. A departure that rested only on them
   is stored as uncited, which is `not verifiable`. Every other verdict keeps its citations. The
   producer applies the rule, so a stored reading is never wrong that way; a reading stored before it
   still cites what it cited, and the page does not second-guess a stored shape. Steer back's rebuilt
   correction reads the stored reading through the same rule, so the moment it names is the agent's
   work and never the paste.
4. The card says when a steer worked. The page already names a departure that clears
   ([the level amendment](#amended-2026-10-21-a-level-needs-a-departure)); where a correction the
   server recognised as Compass's own words sits in the session between the two readings, the line
   reads "The departure your correction named, from the 11:02 reading, no longer holds." That is the
   page's inference from two facts it holds (a recognised paste, and the reading the tab drew before),
   not a stored link between a correction and its departure. Storing the earlier departure itself
   stays with the open question under DEC-15b.

Rejected: matching the wrapped message by prefix or by the longest common run, which would let a
correction with a sentence typed around it read as Compass's; and folding the first digest's
whitespace, which would have moved every stored copy. The parser digest the abstention packets are
stamped with moves with this change, because `reading.py` is one of its files.

### Amended 2026-10-21: the edges of recognising a pasted correction

The rule above shipped with four edges left, found in review and in the walk of a session whose reading,
stored before the strip, lost its departure.

1. A message's fact id keeps the value it had. The id hashes the title, and the strip changed the title of
   a paste whose tag shares a line with the reader's typed words, so a reading stored before it cited an id
   that no longer existed and the page demoted the citation. The event now carries the title as it was hashed
   (`ID_TITLE_FIELD`, server-only and stripped by `for_page`) and only where the strip changed it, so the id
   is the one the earlier build gave and the published title is clean. The tag is looked for in a string
   content and in the text blocks of a list content (a message that carries an image), because the strip
   reads both. Mapping old ids to new on every read
   was rejected: it needs the stored reading to carry a second id per message, and the history store, which
   dedupes on the id, would hold the same message under both. A paste whose tag stands alone on its own
   line never moved, because a title skips a line that opens with `<`; the walked session was that shape,
   so what its reading lost was the citation that [amendment's third item](#amended-2026-10-21-a-pasted-correction-is-compasss-words-and-a-kept-direction-is-no-evidence) removes for a
   recognised paste, not an id. `AWrappedPastesFactIdIsTheOneItAlreadyHadTest`
   holds a stored reading that cites a wrapped paste through the strip.
2. The page draws a message's words from one entry list, so the tags come off where the list is made
   (`workEntries`, for a user message only: an agent's words are its own text). The direction select's
   title, the quote of a cited message and the work list read it, and a story holds each.
3. The cleared line names the departure a correction addressed, whether or not another stands. Between two
   readings with a correction pasted (`copied`, after the first reading and no later than the second), a
   departure of the first that the second no longer finds is cleared, though the second departs on
   something else. A departure is the same one when it is on the same line and either gives the same reason
   or cites an entry the first cited; a model words one finding differently each time, so the reason alone
   would call every re-read a replacement. With no correction between, the line is also said for a departure replaced one for
   one by another that shares neither its reason nor a cited entry (amended 2026-10-21: it was said only when the
   reading carried none), and counts no more than the departures that stand or went. It reads "your correction" for one pasted between the two readings and
   "your corrections" for more; a correction pasted before the first reading or after the second is not
   counted.
4. The copied-flag test beside the kept-direction one now has a control that departs on the same words
   without the flag and with nothing kept, so the flag is the only thing that can drop the citation.

### Amended 2026-10-21: the Drift card has one state at a time

Four walks of the session page (a running session, a finished one, a re-run, a later direction) read
the card as parts that each said something true and together said too much: before any analysis it
held Pause model calls, the Live monitor and its sentence, Analyze drift, "0 drift checks requested",
What is sent, an empty four-step bar and Steer back; while it ran, "Not checked yet" and the empty
bar stood above the progress and the old result vanished; the first analysis's notice stood open over
the result for good; the answer was said three times; "New work since this analysis" and "Your intent
changed after this analysis" were amber boxes between the level and the lines; and, after a reading,
the only way to read again was one of those boxes. The design's Drift card is a heading, the model and
the time it was read at, and the result. This amendment gives the card the controls each moment needs
and no more. It changes what the page draws and where; the reading, its level rules
([a level needs a departure](#amended-2026-10-21-a-level-needs-a-departure)) and its wording are
unchanged.

1. **Before an analysis the card is a heading, one sentence and Analyze drift.** "Not checked yet" and
   its bar are not drawn: a level of nothing labelled four ways measured nothing. The count is drawn
   only once a check was made, and as one node, so a screen reader hears it once; "0 drift checks
   requested" counted something that had not happened. What is sent stays one press from the button,
   because consent is read before the press.
2. **Drift settings is one control in the heading.** The Live monitor switch with its sentence, and
   Pause model calls with its explanation, sit behind it, in every state. While model calls are paused
   Resume model calls stands beside it and not behind it: a paused card has to say how to resume
   without a second press. This supersedes the 2026-10-20 ruling that Pause stood in the heading
   beside the switch, which put four controls and two sentences in the card's first view.
3. **A run replaces the card's body, and over a reading it keeps that reading in view.** While an
   analysis runs the progress and Cancel are the card's state, with no level or counter beside them.
   A run over a stored reading draws "Reading again" above that reading, dimmed, busy and inert, until
   the new one lands; the verdict, level and result stay in the tree so the page does not jump. Focus
   goes from the title to the verdict, as it went to the result's heading.
4. **A one-time notice is open only while the request it came with runs.** After that it is the same
   words inside What is sent, with Pause model calls, and What is sent is drawn once per card state: under
   Analyze drift before a reading, in the footer after one. The notice stays a card above a running
   analysis, where it is what the reader is waiting beside. The summary card draws its own notice and
   keeps it until that card is reworked; `NoticeBody` is shared so it can take the same rule.
5. **The answer is said once.** The verdict sentence under the heading is the only statement of what the
   reading found. The "Departs from your intent" heading, the count and the "Can't tell" line under the
   level are not drawn beside it; over a reading the reader marked inaccurate, where the sentence is not
   drawn, the heading still is. Amended 2026-10-21: the level word is said once too. Where the sentence names
   an analysis level, the level view's head leaves its own word out and keeps the source, the meter and
   its scale; where the sentence names none (can't tell, not reached) no level is drawn at all.
6. **The header says what has happened since the reading, and holds the way to read again.** The model and
   "Analysis last run HH:MM", then "New work since this analysis" or "Your intent changed after this
   analysis", then the re-run control, on one line. The control is Check again over a reading new work or
   changed words left behind, Analyze again over a current one, and it is there in every state a reading
   can be in: inert while calls are paused, while another press is in flight, while an analysis runs
   (Cancel is that state's control), over an unsaved edit and while a later direction's question stands,
   which owns the run path and is named in the control's description. Not drawn where no reader exists on
   this machine, where the reason already stands in the control's place. A refusal, a held closing and
   what the last press came to stay under the result, where the reader looks.
7. **Steer back is offered with a departure.** A failed check, or a claim the record does not show, with
   no departure from the intent, offered a correction over "Not checked yet" and over readings that found
   nothing, with nothing for it to steer from. The page no longer offers it; the server still composes a
   correction from either, and `steerOffer` keeps the legacy page's rule so the differential tests still
   bind it. `DriftBody` takes the departure as the page's gate.
8. **The footer is quiet.** Mark as inaccurate, What the analysis read, What is sent and the count, on
   one line. What Mark as inaccurate does is its description and no longer a second line of the card;
   marked, the state is said beside the way back. Where the work went moved under What the analysis read,
   drawn once there is a reading to describe.
9. **An opening of Analyze is said to the polite region and not drawn.** "Analyze is open: the session's
   last turn finished." was a gate's own words for a control standing pressable beside it. A closing keeps
   its line, because it explains a control that went inert.
10. **Each verdict and the read time are said once (amended 2026-10-21).** The header's "Analysis last run
    HH:MM" is the card's one read time: the level's line says only what the analysis was made against, and
    What the analysis read names the model alone. The delegated-work limit left the result altogether: it
    was moved under Not read and was still a fact about subagents with nothing for the reader to do.
11. **A claim the record does not show says why for that claim.** A claim that names a kind of check (tests,
    lint, types, build) is explained from what the record read holds of that kind: none recorded, a run with
    no recorded result, or a run the analysis did not tie to the claim. A claim that names no kind
    says where the agent made it and that the record read is the board's recent tail, then how many checks
    that record held in the window ("No check was recorded in what was read." or "2 checks were recorded in
    what was read, and the analysis tied none to this claim."; amended 2026-10-21), so no two read the same
    unless they sit beside the same record.
12. **A fixed red test is not a failed check.** A failed run that a later pass of the same check followed,
    the same check being the server's own identity for it (the directory it ran in and its command line,
    published on each check as `check_id`), is a red test written first and fixed. The command line alone is
    not the identity: `pytest -q` passing in one package says nothing of it failing in another, and a check
    that carries no identity is never matched. It raises neither the failed-check verdict
    nor Steer back's offer, which is made only with a departure, the rule the session outline already holds
    for its phases. The server's list is one run per check and never holds a fixed one; the page keeps the entries
    of earlier loads, so it can.

Rejected: a banner above the result for new work and a changed intent, which is what the walk objected to
and what a header line replaces; a settings dialog for the monitor, whose switch would then be
unreachable while a popover is the page's one floating layer; drawing the re-run control only after new
work, which left a reader with an unchanged finished session no way to read again; collapsing the
notice by a stored "seen" flag, a new published field declared in five places for a fact the job's
ending already states; and removing `steerOffer`'s claim and failed-check offers, which the server and
the legacy oracle still hold.

### Amended 2026-10-23 (owner): the Live monitor row and its switch describe a Haiku check

Row 6b's "off by default and needs no model" no longer holds for Claude Code: with the switch on, a Haiku
check of the latest turns runs about once a minute while the session is viewed, under
[the DEC-26 amendment of this date](#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check). The
switch is still off by default and its placement in row 6b, in Drift settings, is unchanged. Its state is
the server's lease, so a reload shows it off, and it is disabled with a reason once the session has ended.

The copy table's switch description, "Shows a level after every turn, from checks and file paths, with no
model call. The level shows here and in the header.", now reads, for Claude Code with annotations on: "Asks Haiku, through your Claude Code, where the latest turns are heading, about once a minute while this session is on screen. Until a check returns, the level comes from checks and file paths. The level shows here and in the header." Other harnesses keep the earlier sentence. A banner after 20 minutes
asks "Do you still want to monitor this session?" and stays for 10 minutes; its answers, and the note left
when it goes unanswered, are in the DEC-26 amendment.

## DEC-28: a model may summarize a session, and the summary is kept

Decided by the owner on 2026-10-19. The ruling, what it amends, the alternatives it rejected, the
closed summary shape and the harness table are in
[the session summary record](design-session-summary.md). In short:

1. A model may author stored text that describes a session, in a closed shape: a lede and phases with
   titled bullets, each bullet citing at least one entry by fact id. The code sets each bullet's kind
   (`did`, `said`, `asked`, `failed`) from its citations. No string may state completion, a check's
   result is quoted only as the tool's report, a bullet that breaks a rule is withheld in place, and a
   part that could not be summarized shows as a gap. The code cannot check that a citation is relevant
   to its sentence, and the record says so.
2. A summary needs no saved intent.
3. Summaries get a new store, which amends
   [DEC-15b](#dec-15b-an-assessment-may-be-stored)'s "No new store" by name.
4. Consent is opt-out with a notice, for every model call a reader's action starts: summaries,
   Analyze drift, Claude Code tool output and Codex goal summaries. Unasked drift checks are not
   covered and stay off by default behind `--unasked-readings` and
   [DEC-18](#dec-18-an-unasked-reading-is-permitted-and-gated-on-delivery-first).
   `--no-observer-model` still refuses every call, and a stored off is kept. This supersedes
   [the consent step](#amended-2026-10-01-the-first-press-is-a-consent-step) and
   [the destination binding](#amended-2026-10-02-owner-the-allow-is-bound-to-where-the-words-go) as
   blocking steps.
5. A finished session is summarized when the reader opens it, unless summaries are off; a running
   session updates only on Update summary. This is reader-requested, so DEC-18 is not engaged.
6. Each summary has whole-job ceilings and summaries have their own rolling cap, set by measurement.
7. No model-written departure headline in this milestone.

The owner also reversed [DEC-27](#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result)'s
two-column layout for this milestone; see the amendment directly above.

### Amended 2026-10-21: the Intent card follows the design

The card the 2026-10-12 build left was a one-line goal, a select whose label changed, Undo and
Add a line that appeared only after typing, a status of two sentences and a meta row of six
parts. It now matches the design's form, and a save no longer shows the draft while it settles.

- **A save keeps the reader's words on screen.** The held goal and lines are dropped after the
  board refresh that follows the reply, not before it. Dropped first, the boxes read the drafted
  prompt and empty outcome lines until the row arrived, about two seconds. The same order holds for
  an adopted prompt. A story with a held refresh asserts it.
- **The form.** The goal is a three-row box. `Use your prompt` is one button with one label that
  opens "Your prompts in this session"; it no longer becomes `Replace with your prompt` or shows the
  chosen prompt. `+ Add a line`, `Save intent` and `Undo changes` sit together on the left and are
  drawn from the first view, the last two inert until there is something to write or undo, and each
  line's `×` is drawn before the reader types.
- **Status is a word.** `Saved`, `Unsaved changes`, `Draft` over a goal drafted from a prompt or detected from a `/goal`, and
  the refusals `Not saved` and `Not confirmed`. Which prompt a draft came from is the goal's source
  line, and `How Intent and drift works` is in the menu below.
- **The goal's hint** no longer carries the prompt-length sentence. "Analyze reads at most the
  first 1,000 characters of any prompt" is in What is sent, beside the parts a reading sends.
- **The meta row** keeps the reading's start (`Saved · reads from 10:57`) and one quiet `More`
  menu holding the measured sentence, `Clear`, `About these saved words`, `Discard everything`,
  `Later directions` and the how-to. What became of discarded words stays on the card, because it
  says what became of the reader's words.

No differential test over the recorded answers changed. The on-demand browser proofs under
`frontend/e2e` still carry the old card's text and were not run for this change.

### Amended 2026-10-21: the edges of the Intent card

What the first pass left, finished.

- **`Use your prompt` is a button.** It opens a popover list headed "Your prompts in this session",
  and holds no value, so its accessible role is button (not combobox) and its options are the list's
  buttons. The popup still opens before the read, and the same popup shows loading, the prompts or
  a stated absence.
- **An armed Discard everything stays where it was drawn.** The offer stays in More. The arming
  press moves the question into the card: the warning, Confirm discard and a Keep my words button
  are drawn in the card's quiet row, outside the menu, until the reader confirms, keeps (the
  button, or Escape) or the 30 second offer lapses. In the menu the warning was hidden whenever the
  menu was closed, and the menu moved between the first press and the second.
- **No lone `More`.** The menu is left out while the store and the boxes hold no words, because it
  held only the how-to there. That includes a discarded form with nothing typed since: the account
  of the discard is drawn in the card, and the menu has nothing to act on.
- **`Save intent` looks inert when it is.** The accent border and text belong to a Save that would
  write something.
- **No revision in a sentence the page words.** "Saved as a new revision." is "Saved."; the
  unchanged answer is "Already saved. These words match what is stored, so nothing new was saved."
  and the saved disclosure says "Each save is kept on its own." Revision stays the store's
  bookkeeping, and that includes the discard sentences the server composes
  (`annotations.DISCARD_SENTENCES`): they say "everything you asked of this session" and "your
  earlier saves" in place of a revision.
- **A direction is named by its time**, never `#n`: the picker reads `10:57 · the words`. When
  several are listed, the one `Add as a line` and `Make it the goal` act on is marked in the list
  ("the one the buttons below use") and carries `aria-current`.
- **`Read from now` is `Read from my latest message`.** The start it opens is the reader's latest
  message, and for a lines-only save over an adopted goal that is the typed message too: the
  adopted prompt's own time is used only when a save adopts one. The label and tooltip now say so.
- **Held-refresh coverage.** A story holds the board refresh after saving an adopted prompt,
  the slow-save story releases its held fetch on failure, and a story asserts the 1,000-character
  sentence in What is sent. `IntentVocabulary.test.tsx` holds the page's own sentences, the recorded discard
  sentences, and the card as drawn (menu open, discard armed, discard landed), to no revision or entry
  number.

The on-demand browser proofs were brought forward to the new names and the card-level armed
question; they were not run for this change.

### Amended 2026-10-21: a later direction is quoted where it is settled

The question over a later direction used to name the number of an entry the reader had not been shown,
quote only its first sentence, and offer `Keep my intent and analyze`, `Add it to my intent` and
`Use this as my goal`. Its first press only revealed the whole message, so every choice took two
presses, and two of the three edited a card above it.

- **Quoted first.** "Your 11:05 message adds:" is followed by the message whole, under the time the
  reader sent it; of several, each is quoted under its own time. Compass reads those words when the
  question is drawn, one read of every open direction, because the reader must see what each choice
  acts on before it acts ([DEC-27](#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result)'s
  rule that Keep settles only words it has drawn is kept). The read adds no session or store state of its own and starts no model,
  and a read that fails leaves the entry's first sentence quoted and Leave it to read again on its press.
- **One press.** `Add as a line`, `Make it the goal` and `Leave it` each act on their first press. Add and
  Make start from the rule in the message (its first sentence), not the whole of it, and both say "Write the
  rule, not the moment." The rule is only where the reader starts: they edit it before anything is saved.
- **Analyze drift stays.** `Keep my intent and analyze` is gone, so settling never starts a model. `Analyze
  drift` sits beside the choices (and `Analyze again` stays in the card head over a stored reading)
  and leaves the directions pending.
- **One save.** The pending line draws no Save. The card's `Save intent` saves it, after any unsaved goal or
  line words, in a second write that settles through that direction only. The two outcome-lines answers
  after `Make it the goal` are buttons beside the question.
- **A source is a time.** A saved line reads "added from your 11:05 message", where it read "added from
  #7", a number the reader may never have been shown.

### Amended 2026-10-21: departure cards and Steer back read as the design does

A departure titled itself with the whole goal sentence, listed `You said` and `Agent said` quotes cut mid-word
that often did not show the departure, and Steer back was an inline button beside a dashed twin over a box
titled "Correction to copy". The correction joined a line ending in a stop to its state with a colon.

- **The headline is what happened.** The stored reading keeps a `detail` and no headline, and no model is asked
  for one, so the title is derived from the entry the departure cites: "It changed `<path>`" for a recorded
  write, "A check failed" for a failed check, and for the agent's own message "What the agent said departs from
  this". A write or a check outranks a message, which only reports on one. Where no cited entry is held the card
  keeps the constraint's own words, as before. The title does not claim the entry is the departure; Why still
  carries the reading's explanation.
  *Refined the same day, review notes.* Two cards on two agent messages, or two failed checks, both read "What
  the agent said departs from this" or "A check failed" (seen on the sample session). Still with no model call,
  the title now carries the entry's time and the constraint it departs from, both of which the card already
  holds: "What the agent said at 11:25 departs from the goal", "A check failed at 11:26 against expected outcome
  2", "It changed `<path>` against the goal". A time that was not recorded is left out, not drawn as zero. A
  written path too long for the title keeps its end, the file name, and gives up the directories in front of
  it; a long unbroken URL or path in What is cut after its last "/" rather than inside a name. The
  correction dates and quotes the same entry the card titles (`correction._headline`, a write or a check before
  a message), where it took the first cite.
- **What is one sentence.** "At 11:25 the agent changed `<path>`." or `At 11:25 the agent said “…”.`, about the
  same entry, with each cited entry's number after it. A quote ends on a whole word before its ellipsis wherever
  the cut falls; a single unbroken word longer than the bound, a URL, is still cut where it stands.
- **Steer back is a section.** It follows the departures and the quiet rows: a heading, "Compass writes a
  correction for you to paste into the session. It never types into the session itself.", the press with
  Update intent instead as a quiet secondary, and the correction under them. The box is labelled "Correction to
  paste" and says "Built from your saved intent and the reading at HH:MM", where it said "from the check at"
  beside the button, because the correction is built from the reading and not from a check. This replaces the
  wording of the earlier rulings above; copy, never send, is unchanged.
- **The correction.** A saved line's own closing stop is dropped where its state is joined to it, so
  "…is edited.: the session says this is done" reads "…is edited: the session says this is done"
  (`correction._label`), and so does a closing question or exclamation mark, while an ellipsis, written "…" or
  "...", is kept because it marks a cut. The departure's time and, at the agent's own message, its words were already named.
- **The counter follows the text.** The count belongs to the box it was typed in; a rebuilt correction draws its
  own length rather than the previous box's.


### Amended 2026-10-23 (owner): the citations are the source

An owner walk of the Sample session on the draft pull request found the Drift card repeating itself. "What
the agent claimed" listed "Agent message [43]", "Your message [80]", which told a reader nothing. Its Evidence
fold then gave each entry's words again with the harness name and an "Evidence recorded at" line, and each
entry's Source fold repeated the one record-type list ("agent_message · timestamped top-level assistant text
record · exact"), once per entry. A departure card had the same Evidence fold under a What that already quoted
the agent. Nothing about the reading changes; this is placement and wording on the card.

- Each cited entry on a departure card, on the claims row and on every quiet goal or outcome row is one line
  in its own words, then its number, which still opens Full activity at that entry and lights every entry the
  finding cites, then a muted time of day: `Agent said: “…” [43] 18:47`, `You said: “…” [80]`,
  `Failed check: <command> [81]`, `File write: <path> [n]`, the wording `citedLine` gives the citation card,
  clipped the way the card clips it. A departure's titled entry takes the same form, so every line on the card
  reads alike; What no longer opens with "At 18:43 the agent said". This amends the 2026-10-20 amendment, which
  kept a quiet row to the entry's kind so that a line read as consistent never stood beside the agent's own
  "Done": the owner ruled that a cited message is the agent's words, attributed, wherever it is cited, and the
  check mark is still said as "[check mark]" and never drawn.
- The Evidence fold and every Source fold are gone from the result: a departure card, the claims row and the
  quiet rows. What only they held either moved inline or was dropped. Moved: the status qualifier a
  consistent line carries ("as the tool reported; not inspected", "not a check"), the stored `why`, the detail of
  a line never reached, the harness's limit and the reason for Can't tell now draw in view under the line
  (`StatusQualifier`, `Qualifiers`). Dropped: the label repeated as a heading, the "Departs; evidence #n"
  status (the label and What say it), the harness and worker lines, the long-form time ("Evidence recorded at",
  "Call recorded at"), a check's "Result recorded at" time and the record-type tags ("agent_message · …"),
  which were the same for every entry of a kind. A person who needs the raw record opens the entry in Full
  activity, whose Source toggle is unchanged. The 2026-10-14 ruling that kept the reason for Can't tell inside
  Evidence was already superseded by the 2026-10-21 amendment; this removes the fold itself.
- The live level's recorded signals keep their own evidence list, which is not a card or a line of the result.
- The how-to and `HOW_TO_USE.md` say nothing about these folds and are unchanged. This change updates the
  sample tour (`frontend/src/sample/tour.ts`), the shipped skill body (`SKILL.md`) and the pointer in
  [the frontend migration record](design-frontend-migration.md).

## DEC-29: a command's result is evidence by tier, and a command that cannot fail never passes

Decided by the owner on 2026-10-27 (DRC-4972). This layer writes the ruling down; the layers that follow build
it, and none of this is shipped by the commit that carries this section. SECURITY.md, the shipped skill and the
promise map change in those layers, not here.

The owner's direction for the whole milestone applies: Compass runs on the reader's machine, in the reader's own
sessions, so the aim is an answer that helps, and a rule stays only if it stops a wrong answer.

**The question.** [DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) item 3 says a
runner not on its closed list is not a check. On a real machine that rule left almost every check unread.
Measured over 30 days of one machine, with no session ids kept: 52% of sessions that used a shell ran a
closed-list check, and 95.6% of 2,159 foreground closed-list check runs recorded no result at all, so they could
not settle a line. A project's own commands, such as `pnpm typecheck` or `python3 scripts/validate_plugins.py`,
were never evidence. May a result from outside the list count, and how far may each kind be trusted?

**The ruling is option (a), with tier 3 allowed to count.**

1. **Three tiers.**
   - Tier 1 is a structured harness record: a pull request created, a push, a skill used. These already exist
     under DEC-23's 2026-10-23 amendment.
   - Tier 2 is a known runner: the DEC-23 closed list; a project's own test, lint, build and typecheck scripts,
     when the script body is itself a closed-list runner; and `gh pr checks`, `gh run view` and `glab ci status`.
   - Tier 3 is any other command.
2. **A tier-3 result may settle a line.** It may stand as `consistent`, labelled "the command exited 0; Compass
   does not know what it checks", it counts toward the level, and a tier-3 failure may support a departure.
   Whether a command is relevant to a line stays the model's judgement. Compass does not use keyword overlap to
   decide it, so the 2026-09-30 rejection of keyword relevance stands.
3. **A command that cannot fail never counts as a pass, whatever its tier**, and the server enforces it, not the
   prompt: `echo`, `printf`, `true`, `:`, `exit 0`, anything ending `|| true` or `; exit 0`, and any command on
   the read-only list, except the CI-reading commands (see item 6).
4. **Tier and ageing are independent.** Every command that is not on the read-only list ages an earlier pass
   ([DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) item 3's blocker), whatever
   tier its own result has.
5. **Each new fact subject is admitted per consumer from an explicit allowlist.** The consumers are the work
   floor, `check_supports`, the live level, the Live monitor's turn text, `check_goal_verdict`, the history's
   prompt-derived carriers and the unasked ledger. One test covers every subject against every consumer, so a
   subject added later cannot reach a consumer nobody chose.
6. **The read-only list grows.** `sleep`, `gh pr checks`, `gh pr view`, `gh run view`, `gh run list`,
   `gh run watch` and `glab ci status` join DEC-23 item 3's list, with their writing options excluded.
   The read-only list governs ageing and the fields read, and item 3's never-a-pass clause applies to every
   command on it except the three tier-2 CI commands, which can report a failure. `sleep`, `gh pr view`,
   `gh run list` and `gh run watch` are read-only and never pass. For the three, only the exit status counts.
   `gh pr checks` counts by its exit status, which is non-zero on failing or pending checks, so pending is never
   a pass. `gh run view` exits 0 on a failed run, so it counts only with `--exit-status`; without it the command
   is read-only and records no result. `glab ci status` counts only if a later layer measures that it exits
   non-zero on a failed pipeline; until then it records no result. A CI command the agent ran counts only by its
   recorded result as
   [DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) item 2 defines it, never by
   rows parsed from its output, and the provider read in
   [DEC-30](#dec-30-compass-may-read-a-pull-requests-ci-state-when-the-reader-presses-analyze) is the stronger
   fact.
7. **Attribution, as a direction.** When a check is the last command before a `tail` or `head` filter, a summary
   on the output's last line is that check's result, even beside earlier setup commands that print. This ships
   only once a measured sample shows the false-attribution rate, and until then the existing rule stands. The
   sample came back on 2026-10-27, and
   [the amendment at the end of this section](#amended-2026-10-27-owner-a-checks-own-summary-on-the-last-line-records-its-result)
   records the rule that shipped.
8. **Harnesses.** Every harness whose record carries commands and their exit status: Claude Code now, Codex
   next.
9. **Qualification runs after this ships, not before**, for the new false-`consistent` class: a pass on a command
   Compass does not understand. This follows the 2026-10-02 acceptance of the Claude Code reader. A change to the
   prompt header is accepted, and the prompt's pinned digest is re-pinned.

**What it reopens.** DEC-23 item 3, whose closed-list rule ("a runner not named here is not a check") is written
in [the closed lists](#the-closed-lists), and
[the 2026-10-23 PR and skill amendment](#amended-2026-10-23-owner-pr-and-skill-facts) that restates it. It does
not reopen the 2026-09-30 rejection of keyword overlap for relevance.

**What was rejected, and why.**

- **(b) Tier 3 on the machine only.** The page would show a pass the reading cannot use, so the reader sees
  "ran" beside a level that ignores it. The same evidence would count in one place and not in another, which
  helps nobody.
- **(c) Grow the list one runner at a time.** Each addition is a release, and the list is always behind the
  commands a project actually has. The 95.6% figure above is the cost of waiting.
- **(d) The closed list plus declared checks, with no tier 3.** It asks every reader to declare what they run
  before Compass helps, which is a setup step on a tool that is meant to work in the reader's own sessions
  unmodified, and it still reads nothing for a command nobody declared.

**Built by**, in words: the layers that follow add the tier classification, the cannot-fail rule, the
read-only additions, the per-consumer allowlist and its one covering test, and the prompt header. The
attribution direction in item 7 shipped later, under the amendment below.

### Amended 2026-10-27 (owner): a check's own summary on the last line records its result

The measured sample item 7 waited for is in, and the owner ruled that the direction ships.

**The rule.** The last check of a call is read from the last non-empty line of its output when nothing follows
it but `tail`, `head` or `grep` filters that read stdin, whatever earlier setup commands printed. The line counts
only when it is one the check's own runner prints, from a closed table: unittest (`OK`, `OK (skipped=N)`,
`OK (expected failures=N)`, `FAILED (...)`), pytest (the counted summary with its timing), mypy (`Success` and
`Found N errors in ...`), ruff check (`All checks passed!`, `Found N errors.` and the fixable-count line under
it), vitest (its `Tests` line) and `node --test` (its `fail` line), and, from a later amendment, biome
and gradle. A runner that prints no summary of its own (`tsc`, `eslint`) never takes another command's line. A check wrapped in `rtk` stays flag-only, and a
check that is not the last of the call is unchanged. Only the last line is read, so a failure printed earlier in
the window by another command does not fail a later passing check.

**Claude Code's own trailer lines are not the command's output.** A result may end with a line saying the shell
directory was reset, with the notice that the command modified files the session had read (ending `Call Read
before editing.`) or with `(Bash completed with no output)`. Those exact shapes are dropped from the end of the
output, and only the end, before the window is cut or the last line is read. The same words in the middle of the
output are the command's own and are kept.

**Every result an attribution rule withholds names its reason.** A result such a rule withholds publishes one of four closed tokens; the
fourth, `printed_beside_other_commands`, covers the setup shapes the other three did not name, which showed as
"no token".

**What was measured**, counts only. Over 2,183 check runs on one machine: the rule for the one check last before
a filter records 98 runs that were withheld, with 0 false of 33 hand-labelled (upper bound 8.7%) and 0 false of
98 in a census (upper bound 3.0%). Extending it to the last of several checks adds 139 runs and had 3 false
attributions (2.2%): two where a failing lint run printed its count last and it was read as a type check that
never ran, and one silent type check that took a test runner's line. Requiring the summary to be one the check's
own runner prints removes the three measured shapes. A check whose call holds an earlier check of the same runner never takes the last-of-several read, because with `&&` the later one may not have run and both print the same shape of line. Reading the whole 180-character window instead of the last line flips 12
runs to false failures. Trailer lines ended 274 of 925 tails that matched no pattern and pushed the summary out
of the window in 103. unittest's `OK (skipped=N)` form accounts for 158 runs the plain `OK` pattern never
matched, and 17 withheld runs carried no reason.

**A failing flag is not outvoted, an empty run is not a pass, and the runner's own tail is read.** A call whose
error flag is set and that speaks for no one check records a passing last line as "ran, result not recorded":
the failure may be a setup command, and the last line says nothing about it. A failing last line still records
a failure, and a one-check call still takes the flag. unittest's `OK` counts only with a `Ran N tests` line
above it and N above zero, since an empty discovery prints `OK` too. vitest and node print their summary
before a few closing lines (`Start at` and `Duration`; `cancelled`, `skipped`, `todo` and `duration_ms`), and
those exact lines are skipped from the end before the last line is read. A last line longer than 200
characters is not read.

**What it does not change.** The tiers, the never-a-pass rule and the ageing rule above stand. The summary of a
runner in the table is evidence only for that runner's check; nothing here lets one command's line speak for
another.

### Amended 2026-10-27 (owner): the tiers are built

The layer that follows the ruling adds the fact subjects, the consumer table and the cannot-fail rule. What
the build had to decide, in the order a reader meets it:

- **Two subjects, neither `check`.** A tier 3 command is `command` and a tier 2 CI read is `ci_command`, each
  carrying its tier. A check's subject was never reused, so a consumer that tests `check` reads no command by
  accident, and the scan counts them under `command_*` and `ci_*` beside the check counters the page and the
  live floor already read.
- **The CI reads.** `gh pr checks` counts by exit status: 0 is a pass, and 1 is a failure unless its output says
  no checks were reported or names a login or request error. 8 (pending), 2 (cancelled), 4 (login) and any
  other code record no result, so a tool error or a pull request with no CI is never a failed CI read.
  `gh run view` counts only with `--exit-status`, and then only a failure: it exits 0 for a run still in
  progress, so a pass is not recorded. `glab ci status` lists
  nothing, because no measurement of its exit status exists yet. All three stay on the read-only list, so a
  CI poll never ages a pass.
- **What cannot fail is not listed.** `echo`, `printf`, `true`, `:`, `export`, `unset` and `exit 0` never become a
  command: `export` and `unset` were added to the ruling's list because they only change the shell's variables
  and a pass of one is no evidence. A command whose status a later `|| true`, `; true` or `; exit 0` forces is
  listed with no result and `cannot_fail` set. The producer always publishes `cannot_fail`, true or false,
  and the resolver trusts it; it reads the published line only for an older stored fact that lacks the key, so
  `find build -delete`, which writes, is never withdrawn as one that cannot fail. Every spelling counts: a
  program by path (`/bin/true`), behind `command`, `nohup` or `time`, `exit 00`, `return 0`, and `set`, `eval`
  and `tee` too. A stage after a `|` that follows other work records no result, since the call's status speaks
  for the filter. `false` is not on the list: it always fails, which is a result.
- **A structured git record stands alone.** A call whose result carries Claude Code's `gitOperation` publishes
  that record (the pull request) and no command line, because a pull request's title and body are free text
  the record deliberately never carried.
- **One table decides every consumer.** `reading.CONSUMER_SUBJECTS` names the subjects each consumer reads,
  and `test_subject_consumers` runs a fact of every subject through the real consumer. The work floor and the
  verdict resolver read both new subjects. The live level reads the CI read as a check and a command only as a
  blocker of its floor, and only until a later check or command passes: commands supersede one another by
  identical text alone, so a retried command would otherwise pin the level for the session. A tier 3 pass is
  never unchanged, since its own call is a changing command. A failed or pending CI read reads as a failed or
  unrecorded check does, in the live level and in a stored reading's level. The Live monitor sends both. The goal verdict reads neither, because it
  matches a check's words to the claim by keyword, which the 2026-09-30 rejection of keyword relevance rules
  out for a command whose purpose Compass does not know. The history store and the unasked lane read no
  command.
- **The listing.** A command takes no place number, so the number of every check and file after it in a session
  already read does not move. It is listed after every other kind of entry, failures first within its own tier,
  and the scan counts every one the cap left out. In a prompt it follows the reader's words, every check, write,
  pull request, skill and CI read and the checks with no result, and ahead of the agent's messages.
- **The label.** A command's result reads "exited 0; Compass does not know what it checks" or "exited
  non-zero; Compass does not know what it checks", on the row the model reads and on the page, where it never
  uses a check's mark or its words (a command that exited 0 draws a terminal glyph, not a check's tick) and is
  not folded into a run of checks.
- **The prompt header is unchanged**, so its pinned digest stands. The new false-`consistent` class is the
  qualification item 9 owes after the wave ships, and it has not run.

### Amended 2026-10-27 (owner): a project's own scripts are tier 2 checks

Item 1 puts a project's own test, lint, build and typecheck scripts in tier 2 "when the script body is itself
a closed-list runner". This layer builds that, and what the build had to decide is below.

- **What counts.** A package script, a make target or a just recipe is a check when its own body is a closed-list
  runner or a `&&` chain of them, and its name carries a check verb (`test`, `lint`, `typecheck`, `check`,
  `build`, as a whole word of the name split on `:`, `-`, `_` and `.`). A script that names another declared
  script runs through the same test, four levels deep at most. A body that redirects into a file, opens a
  subshell, substitutes a command, backgrounds anything, joins with `;`, `||` or a pipe, or holds a fixer
  (`--fix`, `--write`, `format` without `--check`) never counts. Neither does a name carrying a word like
  `fix`, `format`, `deploy`, `clean`, `dev` or `watch`, since a body such as `tsc --build --clean` looks like a
  runner and is not a check. An installer, `echo`, `true`, `:`, `exit 0` and a deploy are not on the closed list,
  so no body of them passes. `npm` and `pnpm` run `pre<name>` and `post<name>` around a script, so one that is
  declared and is not itself a check withdraws the script. A body that watches, rewrites snapshots or
  autocorrects (`--watch`, `-u`, `--update`, `--snapshot-update`, `-A`) is not a check either, while a warning
  filter such as `python -m pytest -W error` is. `format:check` counts when every body line says `--check`.
  A make target counts only when `.PHONY` in the same file lists it or it has a prerequisite, because
  `make test` beside a `test/` directory prints "up to date" and runs nothing; a trailing `#` comment on a
  rule line is dropped, unless the line also holds a `$`.
- **What the session typed.** `pnpm <name>`, `pnpm run <name>`, `npm run <name>`, `yarn <name>`, `make <targets>`
  and `just <recipes>`, from the toplevel of the work tree (`bun run <name>` reads as `npm run`). A package
  manager option before or after the name and before a literal `--` (`--filter`, `-r`, `-C`, `--dir`,
  `--prefix`, `--workspace`, `--script-shell`) selects another package or stops the script, so its declaration
  is not the one that ran. A `--fix` or `--write` anywhere can turn a check into a writer, a make variable on
  the command line rewrites a recipe, and a variable that steers the run (`npm_config_*`, `MAKEFLAGS`, `MAKE`,
  `JUST_*`) changes what runs. Each leaves the command an ordinary tier 3 command. An argument after `--`
  reaches the script, so `npm run typecheck -- --noEmit` still counts. `pnpm test`, `npm run test`, `make test` and the other names
  already on the closed list count as they did, whatever their script holds.
- **Where the declaration is read.** The agent can write every declaring file, so a declaration is read from the
  git object database, at the newest first-parent commit of HEAD that is no newer than the transcript's first
  stamped record, and never from the working tree alone. Compass does not record the commit a session began on,
  and the transcript carries a branch name at most, so the first record's time stands in for it; a commit the
  session made later is never the base. The working-tree file must also be a regular file whose bytes equal that
  commit's, and a cached read is checked against the work tree again before it is used. A session that edited
  it by any tool, or by a shell command, leaves it different, so it declares nothing, and a recorded write by a write tool withdraws that kind of file even when the session restored it.
  An edit made by a shell command and then put back is the one case neither check sees; the work tree after the
  session is the same file the commit held.
- **Bounds.** Only the toplevel of the work tree of the directory the session began in; `lstat` before any open,
  regular files only, no link followed, a non-blocking open; 256 KiB a file, 4,096 characters a line, 500 scripts, seven files, one five
  second deadline for all of git. A symlink, a FIFO, an oversized file, an unparseable one and a Makefile that
  uses `include`, conditionals, `define`, `.ONESHELL` or a custom `SHELL` add nothing, and `--diagnose` names the
  file and a closed reason, never its content. A command in a subfolder runs that folder's scripts, which are not
  read. Workflow `run:` steps are out of scope, because no YAML parser ships. On Windows a checkout that converts
  line endings differs from its commit byte for byte, so its declarations are skipped as edited.
- **What stays a command.** The closed list is the whole vocabulary of a body: any runner not on it leaves its
  script tier 3 until the list grows or a later layer reads them. This layer did not widen the list; `biome
  check`, `biome ci`, `storybook test`, `test-storybook` and `gradle`/`./gradlew check` joined it later, see the
  [DEC-23 amendment](#amended-2026-10-28-owner-biome-storybook-and-gradle-check-runners-join-the-closed-list).
- **Ageing and the answer.** A declared script is a check and still a change, as item 4 says of every command
  that is not read-only: it ages the passes before it, its own pass stands, and a later one ages that. Its result is
  read as any check's is, from the call's exit status and the output the producer already reads. The line
  published is the session's own command, never the script's body.
- **Three readers, one classification.** The published facts, the source pages and the model-free live level all
  take the same declarations from one read, and the live replay restarts when which scripts are declared
  changes. The live level therefore starts git, four read-only commands against the object database, and the
  test that pins "no process" for it allows exactly those. `--no-git` stops the read, and the scripts become
  commands again.
- **The command.** `git -c core.fsmonitor= -c core.hooksPath=/dev/null --no-optional-locks` with `rev-parse
  --show-toplevel`, `rev-list -1 --first-parent --before=<ISO date in UTC> HEAD`, `ls-tree -l -z <commit> --
  <names>` and `cat-file blob <id>`, in `git_status.py` beside the status probe, by the same resolved executable
  and scrubbed environment, with `GIT_NO_REPLACE_OBJECTS=1` set so a replace ref cannot present an edited
  file as the committed one. Measured: `--before=<digits>` is not a timestamp, since git matched a commit newer
  than the bound, so the date is written out. None of the four reads the index, runs a filter or an fsmonitor.
  [SECURITY.md](../SECURITY.md#the-committed-file-read-project-check-scripts) states the contract.

### Amended 2026-10-27 (owner): a reader may list a project's checks

A project's check is sometimes something no rule finds: a custom script, `bazel test //...`. Item 1's tier
2 now also holds the commands a reader lists for a project, and this amends the closed list of
[DEC-23 item 3](#the-closed-lists) per project, for that reader only.

- **Where.** One file in the Compass home, `compass-project-checks.json` (`COMPASS_HOME` moves it, as it
  moves every store). It is the reader's. Nothing is ever read from a `.compass` folder inside a
  repository, because a repository's files are the agent's to write and a listing is what makes the agent's
  own command count as evidence.
- **Shape.** `{"projects": {"<project>": ["<command>", ...]}}`; a `v` key is neither required nor read. A project is named by the absolute path
  of its repository (`~/` works, and a linked worktree is its repository's project), or by the key the board
  publishes for it. At most 64 projects, 32 commands each and 512 characters a command. The file is read to a
  64 KiB cap as the other stores are: one that will not parse, is over the cap or has the wrong shape lists
  nothing, is never repaired, and `--diagnose` says why.
- **What counts.** A command typed in a session of that project whose words equal a listed entry's is a
  tier 2 check. A program on the PATH or by an absolute path counts from any folder; a script named by a
  relative path (`./check.sh`) is a file of the project, so it counts only where it ran from the project's
  root, and not when the session wrote that file by a write tool or by a shell command that names it. A
  listing keyed by a path the session's folder no longer has (a deleted worktree) matches nothing. Such a check
  is a tier 2 check, with the result of its exit status read as any check's is. `bazel test //...`
  listed does not make `bazel test //other/...` one. Such a check is published with `listed_by_reader`, and the
  page and the row the model reads both say "counted because you listed it", so a pass is never read as a runner
  Compass knows.
- **What never counts, however it is listed.** A shell builtin (the whole bash and zsh set), `echo`, `printf`,
  `true`, `:`, `exit` in any form and anything else that cannot fail, judged through `sudo`, `nice`, `nohup`,
  `ionice`, `xargs`, `env`, `time` and `timeout`, a command on the read-only list, a fixer (`--fix`, `--write`, `format`
  without `--check`), and any line that is not one plain command (a `&&` chain, a pipe, a redirect into a file,
  a substitution). Item 3's never-a-pass clause is not a thing a listing overrides. `--diagnose` names each
  ignored entry by a bare program name and the reason, and nothing else: an assignment (`NAME=value`) or a
  path is never printed, the list is capped at 64 rows with the rest counted, and entries or projects past the
  caps are reported rather than dropped quietly.
- **Ageing is unchanged.** A listed command is still a command that is not read-only, so it ages the passes
  before it, and its own pass stands until a later change (item 4).
- **A session that writes the file.** A recorded write by a write tool to a file of that name, in any folder,
  or a shell command whose text names that file at all (a redirect, `cp`, `tee`, an interpreter's argument, or
  a read, which fails closed), withdraws every listed command for that session, and the page says the session
  wrote the file where the reader lists checks, but only when the reader had listed something. The paged
  reader carries that fact across pages, so it agrees with a whole read. The residual is an indirect write: a
  script or a variable that builds the path.
- **`--no-git` does not stop it.** No git command runs for a listing; it is one file read.
- **What was rejected.** Reading a `.compass/` folder in the repository, so a team could share a list: the
  file would be one the agent can write. A listing keyed by project name alone, which two repositories share.
  Matching by prefix, so a listed command covers any arguments: a flag after `--` or an environment variable
  can turn one into a writer, and the reader can list each command they run.

### Amended 2026-10-28 (owner): biome and gradle join the last-line table

The closed table of runner summaries gains two rows, biome and gradle, and `biome` is no longer in the list of
runners that print no summary of their own (`tsc` and `eslint` still are). The shapes each row reads, and why
Storybook's runners have no row, are in the
[DEC-23 amendment](#amended-2026-10-28-owner-biome-storybook-and-gradle-check-runners-join-the-closed-list).

### Amended 2026-10-28 (owner): a closed-list name the project declares is judged by its body

`pnpm test`, `npm test`, `npm run test`, `yarn test` and `pnpm test:stories` are on the closed list as
the usual runner behind each name. A project that declares a script of that name has made it something
else, and the list used to skip the declared body, so `"test": "echo skipped"`, `"test": "true"` or
`"test:stories": "storybook test -u"` read as a passed check. Where the declarations were read for the
folder the call ran in and hold a script of that name, the declared body decides: a body that is a
runner, or a `&&` chain of them, keeps the invocation a check, and a body that is not a runner, is a
fixer or cannot fail makes it an ordinary command. Where nothing is declared under that name, or no
declaration was read (`--no-git`, not a repository), the closed list stands as before.

## DEC-30: Compass may read a pull request's CI state when the reader presses Analyze

Decided by the owner on 2026-10-27 (DRC-4973). This layer writes the ruling down; the layers that follow build
it. SECURITY.md, the shipped skill and the promise map change in those layers, not here.

**The question.** A session that opens a pull request usually ends with the real check, the pull request's CI,
running somewhere the transcript does not record. May Compass ask GitHub or GitLab for that state when a reader
presses Analyze?

**The ruling is (a): yes, on by default, folded into Analyze drift.**

1. **One control, with a turn-off.** There is no separate button. Like the quota read, it has a page setting and
   a `--no-ci-read` option. One line naming the read joins the existing notice, and there is no consent step,
   as [DEC-28](#dec-28-a-model-may-summarize-a-session-and-the-summary-is-kept) already rules for model calls.
2. **Binding.** The pull request is the goal's URL, or Claude Code's `pr-link` and push records when their
   repository matches the session folder's own git remote. A `/goal` the reader typed counts as the reader's
   words. When the goal names one pull request and the record another, the goal wins.
3. **What green means.** Pending is never a pass. Skipped checks count as neither a pass nor a failure, so a
   pass on the checks that ran stands. Zero completed checks is no result. Where the provider reports which
   checks are required, they are preferred.
4. **The session's commit.** CI counts only when the pull request's head equals the HEAD of the session's
   folder, read with the existing git probe. A head that moved past it is named, and that CI does not settle the
   session's lines.
5. **A session that edited CI configuration is not blocked.** For `.github/workflows/**` or `.gitlab-ci.yml`
   the reading carries a caution line that the session changed the CI config, and the model judges whether that
   weakened CI.
6. **A CI fact is a recorded harness fact** for an Analyze reading's None or low, as the DEC-26 amendment of
   2026-10-27 records.
7. **Stored with the reading**, labelled with the time it was read.
8. **Harnesses.** Any harness with a goal URL. Binding through transcript records is Claude Code only for now.
9. **Where it does not run.** Not the Live monitor and not the unasked lane for now, so no network call happens
   without a press.
10. **Launch safeguards.**
    - An absolute binary, resolved against a PATH with no relative entries, as the git probe does.
    - A Compass-private empty working directory.
    - `GH_*`, `GITLAB_*` and `GL_*` overrides stripped, with prompts and update checks off.
    - An explicit `--repo HOST/OWNER/REPO`, validated against a closed pattern.
    - Known hosts only: `github.com`, or a host in the tool's own hosts configuration; https; never an IP
      literal.
    - A hard timeout that kills the process group.
    - JSON parsed whatever the exit code, size-capped and schema-validated.
    - Stderr never stored beyond a closed error token.
    - Check names are writable by whoever writes the workflows, so they take a closed character set, are
      clipped, and are sent as quoted fields. Description, link and log text are never read.
11. **Refusal order and rate.** `--no-observer-model`, Pause model calls and the Analyze cap are checked before
    any launch. There is one read per pull request per press, with a cache floor.

**What it reopens.** SECURITY.md scope item 1, where three outbound kinds become four, and the 2026-10-23 choice
not to read `pr-link` ([DEC-23](#amended-2026-10-23-owner-pr-and-skill-facts)). The repository and the pull
request number are session content, and they leave the machine with the reader's own login.

**What was rejected, and why.**

- **(b) A separate Check CI control.**
  [DEC-27](#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result) keeps one primary
  action on the first view, and a second press for the evidence the first needs asks the reader to know which to
  press.
- **(c) Parse CI rows from shell text.** It misses polling loops such as `out=$(...)`, an output-rewriting hook
  can change what the transcript holds, and `echo` forges the same text. It reads what the agent printed, not
  what the provider recorded.
- **(d) No.** The pull request's own checks are the strongest evidence a session of this kind can have, and
  leaving them out is the 95.6% problem
  [DEC-29](#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes) measured,
  one layer up.

**Built by**, in words: the layers that follow add the binder, the guarded launcher for `gh` and `glab`, the
fact and its store, the page setting and `--no-ci-read`, and the notice line.

### Amended 2026-10-27 (owner): the `gh` read is built, for `github.com`

This layer builds the ruling for GitHub only. `glab` and a host from the tool's own hosts file are not
built, so the known hosts are `github.com` and nothing else, and a goal that names another host
contributes no pull request, and the session's own records may still bind one. The ruling's other items stand as written, and these are the choices it left open.

- **One fact per check, built from the stored record.** A `ci_check` entry carries the check's name,
  bucket and completion time, and Compass's own word for whether it may settle (`ci_counts`). The record
  is stored beside `criteria` as `ci` and the entries are rebuilt from it every time, so a citation
  resolves in the prompt, in the stored reading and in the level, with the same ids. The entry's time
  is the read's, because the pull request's state at the press is no event of the session. A last-turn
  reading's stop therefore does not cut it, and the head test of item 4 is what ties it to the session. For
  the same reason a read never stands in for a session that did nothing since the reader's words: the
  window and the stop are tested over the session's own entries, and a reading with none still withholds.
  The page rebuilds the same entries from the stored record (`ciEntries`) so a citation of one resolves and
  a line resting on a check that does not count is refused there as it was here. They are in no list and no
  numbering.
- **What counts.** A pass counts when the pull request's head is the session folder's HEAD and every
  check that counts has passed, with none pending, failed or cancelled and at least one passed. A failure
  counts when the head matches. Where GitHub names required checks, only those are listed and counted.
  Anything else is listed so the reading can say it, and settles nothing. A session folder that cannot
  be read (`--no-git`, a missing directory) gives no head to match, so nothing settles.
- **Binding order.** A goal that names exactly one pull request by URL binds, and one that names two
  binds none. Otherwise the newest `pr-link` record of the folder's own `origin` binds, and then the
  newest pushed branch of it, which is looked up once for its number. That look-up sends GitHub the
  branch's name once, the one place a push-bound read sends more than the repository and the number. A record naming another
  repository binds nothing, because a transcript can say anything and only the folder's own remote says
  it is this one.
- **The harness's own verdict.** A goal verdict that names the bound pull request agrees when its CI
  counts as passed and is disputed when a failing check counts. The goal's own words are read when the
  reason is empty, as for a created pull request.
- **A caution, not a block.** A write to a workflow file or `.gitlab-ci.yml` puts the caution on every
  `ci_check` entry the model reads, and the reading still settles.
- **The page's setting is a marker file** in the state directory, so every dashboard of this account
  and every tab reads one answer. `--no-ci-read` wins and the page cannot lift it.
- **One read per pull request, and a floor.** A press reads a pull request once: the head, the checks, the
  required checks, then the head again, because `gh pr checks` names no commit and a push between the first
  look and the listing would put the new commit's checks under the old head. A pull request read within 30
  seconds is not read again, and only a read that answered is kept, so a reader who fixes a missing or
  signed-out `gh` is not told the old answer.
- **The notice carries one line** about the read, only while the read is on, and the page's switch sits
  under the list. The notice's content epoch is not bumped, so a reader who has seen the notice before sees
  the new line in the route's disclosure under What is sent and is not shown the notice again.

### Amended 2026-10-27 (owner): the `glab` read is built, for a goal URL on a host glab names

This layer builds the GitLab half of the ruling on the `gh` read above. The ruling's other items stand
as written, and these are the choices it left open.

- **Binding is the goal's URL alone.** A goal that names exactly one merge request by
  `https://HOST/GROUP/.../PROJECT/-/merge_requests/N` binds it, and one that names two requests binds
  none, across both providers. No transcript record binds a GitLab merge request, because whether
  Claude Code writes a `pr-link` for one is not measured
  ([the note](captures/claude/gitlab-merge-request-read-unmeasured.md)). A goal that names a GitHub pull
  request and a GitLab merge request binds none.
- **Hosts come from glab's own file, before anything starts.** The host names under `hosts:` in
  `glab-cli/config.yml` are the only hosts read; no value in that file is kept. A goal URL on any other
  host binds, because the reader's words name it, and then launches nothing and is said beside the
  reading as `host-not-configured`. A host is read only when it is a dotted name, exactly equal to one
  in the file, over https, and never an IP literal or one carrying a port. This is the ruling's item
  10, "known hosts only", as it applies to a tool whose hosts the reader configured.
- **No token reaches a host it was not given for.** `GITLAB_TOKEN` applies to any host a command
  names, so it is stripped with `GITLAB_HOST`, `GL_HOST`, `GLAB_*`, `OAUTH_TOKEN` and `REMOTE_ALIAS`.
  The cost is that a reader who signs in by `GITLAB_TOKEN` alone reads nothing; `glab auth login` keys
  its stored login by host and works.
- **The same fact, with a closed status table.** `glab api` makes fixed GETs: the merge request for
  its head commit and pipeline, the pipeline's jobs (a hundred a page, ten pages, and more than that
  is unreadable and never a pass), and the merge request again for the head. A job's status maps to
  the bucket vocabulary the GitHub read defines. A job allowed to fail counts as neither a pass nor a
  failure, a manual job is pending unless it may be skipped, and a status outside the table makes the
  read unreadable. GitLab names no required checks, so `required_only` stays false. A pipeline whose
  own status disagrees with its jobs, as when a trigger job's child failed, is listed as a check named
  `pipeline`, so a green set of jobs never stands over a failed pipeline. A pipeline replaced between
  the two looks matches nothing, as a moved head does.
- **The pipeline must have run the request's head.** The merge request answer's `head_pipeline`
  carries the `sha` the pipeline ran. A pass counts only when that equals the request's head and the
  session's commit, both looks, so a pipeline that lags a new push, was skipped by rules, or ran a
  merged-results commit is listed and settles nothing.
- **A host whose configuration redirects the call is not read.** `glab` resolves `--hostname`
  through `api_protocol`, `api_host` and `skip_tls_verify` in the host block. A host whose block
  sets a protocol other than https, an API host other than itself, or skipped TLS verification is
  dropped, so it reads as `host-not-configured` and launches nothing. Only those three values are
  read, and no token.
- **A repository is stored with its host.** A GitLab repository is `host/group/.../project`, and no
  GitHub `owner/repo` holds a dot, so the stored record, the fact and the page tell the providers
  apart from that one field and the record gains no key. The facts say `gitlab`, the source
  `GitLab merge request pipeline job, read by Compass`, and the page names the merge request by `!N`.
  A harness verdict that names the merge request by its URL, `MR !N` or `merge request N` agrees or
  is disputed as it does for a pull request.
- **The notice line and the switch name both providers.** `--no-ci-read` and the page's switch govern
  both, and the line under What is sent says GitHub or GitLab.

## DEC-31: the text of a command that is not a check may leave the machine, by vendor

Decided by the owner on 2026-10-27 (DRC-4987). This layer writes the ruling down; the layers that follow build
it. SECURITY.md, the shipped skill and the promise map change in those layers, not here.

**The question.** [DEC-23](#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work) item 5 keeps
the text of a command that is not a check on the machine: "its time only, never its text". May that text leave
in a reading?

**The ruling is a vendor rule, not a content rule.** A Claude Code session has already sent every command and
every output to its own vendor. Reading it through the same vendor exposes nothing new.

1. **Same vendor as the session.** A Claude Code session read by Claude Code, the Live monitor's Haiku
   included: every command's masked line and its redacted output tail may be sent.
2. **A different vendor.** For example Codex reading a Claude Code session: every command and its exit status
   may be sent, and output tails for tier 1 and tier 2 only
   ([DEC-29](#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)'s
   tiers).
3. **One line in the existing one-time notice names it.** The first press runs, as
   [DEC-28](#dec-28-a-model-may-summarize-a-session-and-the-summary-is-kept) already rules, with no hold until
   the notice is seen.
4. **Upkeep, never blocking.** Redaction learns the shapes found leaking: gcloud `ya29.` tokens,
   `SecretString` values, netrc passwords, `curl -u user:pass`, `Cookie:` headers and others. A stored
   departure explanation is scrubbed with the call's masked values. Neither holds a build or a press.
5. **Item 10 of DEC-23 opens for failed results only.** The unasked lane receives failed results now, without
   waiting for DEC-18's rubric thresholds, and never receives passes, because a failure raises departures and a
   pass never reassures.

**What it reopens.** DEC-23 item 5, "its time only, never its text", as narrowed on 2026-09-24 and restated in
[the 2026-10-23 PR and skill amendment](#amended-2026-10-23-owner-pr-and-skill-facts), and DEC-23 item 10, "the
unasked lane never receives tool outcomes", for failed results only.

**What was rejected, and why.**

- **(a) Nothing more leaves.** It protects against a disclosure the same vendor has already received, and it is
  the reason a reading of a session full of project commands could not name one of them.
- **(b) Program name and exit status only.** It tells a reading that something ran and not what, so the model
  cannot judge whether the command bears on a line, which is the judgement
  [DEC-29](#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes) leaves to
  it.
- **(c) A closed list of programs.** It is DEC-29's rejected option (c) again, for text: always behind the
  commands a project has.
- **(d) The masked line and tail for every command to every vendor.** Unsafe across vendors with today's
  redaction. A second vendor has received none of it, and the shapes in item 4 show redaction still learning.
  Cross-vendor therefore stays at the command and its status.

**Built by**, in words: the layers that follow add the vendor comparison, the two admission levels, the notice
line, the redaction shapes and the scrub of a stored explanation, and the failed-results-only admission for
the unasked lane.

### Amended 2026-10-27 (owner): the vendor rule is built

The press compares the vendor of the route with the vendor of the session's harness
(`reading_route.same_vendor`). The same vendor sends every command's masked line and redacted tail. Another
vendor sends each command's line and status, and `reading_route.tails_for` drops a tail whose call holds a
tier 3 command, since a tail is the whole call's output and a call that held both a check and a command would
otherwise carry the command's text across. The one sentence in the notice's tool-output item says which
applies: "Other commands go too, with their output." or "Other commands go with their exit status and no
output." The Live monitor sends no output tail at all, so it needed no second rule.

A line is masked as a check's is, with one addition: a quoted word that the masking cannot read word by word
is shown as `…`. A `bash -c` script that did not parse is the case that showed it, and masking one word at a
time left half of a value behind.
