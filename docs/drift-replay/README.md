# The drift replay check, committed half

This directory holds what blind agents marked at each cut of the pushback sessions, and what Compass's
drift detectors did there. It never holds the session text either one came from.
[SECURITY.md](../../SECURITY.md#the-abstention-check) holds the ruling for this check and its two
siblings, the abstention check and the [drift levels check](../drift-levels/README.md).

The question it answers is whether Compass catches drift a person actually pushed back on. The
golden key is `tests/annotated_sessions/<sid>/annotation.md`. The data is each session's log: the
redacted copy under `tests/raw_sessions/<sid>/`, which is gitignored and made by
`scripts/redact_session.py`, or the original with `--source original`.

## What lives here

- [Ordinary persisted-turn preparation](ordinary-driver-preparation.md) describes the model-free
  four-run preparation and required external admission. It records no native walk or drift-replay result.

- `marks-digest.json`, written each time marks are saved. It holds the sha256 of
  `~/.compass/drift-replay/marks.json`, the digest of the case set the marks belong to, and counts.
  It is committed before any run, and every run reads it from `HEAD`, never from the working copy.
- `results.json`, once a score has been committed. Per case it holds a case id salted with a local
  secret, the reconciled agent mark (drift, no drift or unclear) and its class, the case's roles, and one outcome
  per detector and intent arm. Historical summaries leave unclear cuts out. New summaries retain them for the blind column, and exclude them from final-key counts. They also hold the digests and counts. It names no session,
  path, command, word or model sentence.
- `claim-marks-digest.json`, once claims have been marked true or false: the sha256 of
  `~/.compass/drift-replay/claim-marks.json` and counts. `results.json` then also holds a
  `claims_truth` section, keyed by salted claim ids.
- `results-<tag>.json`, the score of a narrowed, tagged re-read, in the same shape as `results.json`.
- `coverage-<tag>.json`, a model-free reconstruction's counts of measured transcript-tail coverage.
  It holds counts and runtime provenance, no transcript times or session text.
- [windows-stage3.json](windows-stage3.json) compares the wide drafted current-arm window with
  the old lines-only save's narrowed window. At 68 of 99 cuts, a median 40 minutes differs:
  wide listings hold 213 person messages, 380 tool reports and 871 agent messages; narrow
  listings hold 69, 211 and 472. One stored claims reading cites a listed check, retained in
  both windows. These are model-free listings from counterfactual history. Earlier current-arm
  results used the wide window; this count measures no change in detector accuracy.

## What does not live here

The cases, the marks, the live and read outputs, the spend ledger and the salt stay in
`~/.compass/drift-replay/`. The cases name sessions and times; the outputs hold the agent's and
the person's words through the readings.

## Repeated-read pilot, 2026-10-05

[pilot-stage4a.json](pilot-stage4a.json) measures 29 usable reads on seven frozen current-arm
prompts after the model-free changes merged. Four prompts were read five times, three critical
controls three times. Every repeated app-prompt digest matched. Of 31 case/question pairs, 13 kept
the same resolved verdict across repeats and 15 kept the same raw token. The other 18 resolved
questions varied. Resolver guards and citations explain why raw and resolved agreement differ.
The file also holds citation overlap, with an empty/empty pair defined as overlap 1.

These are seven development-set prompts under agent marks, from the same four sessions. This is
variation on unchanged prompts, not a detector rate or person outcome. A later changed-prompt
result must be read against this spread; one changed verdict alone demonstrates no improvement.

## Word recovery before paired reads

[words-stage4b.json](words-stage4b.json) rebuilds the 16 historical readings whose flagged claim
reply had been sent as its title. With verified person-word recovery, measured agent crops and
unused-room allocation, 15 of those 16 now carry the reply excerpt. All 16 claim entries remain
selected. The largest prompt is 16,336 bytes; substituting a worst-case goal and six outcome lines
raises the maximum to 16,373, below the unchanged 16,384-byte cap. This is a model-free measurement
of wording and room. It does not show that a flag became right or that the complete reply was read:
the agent excerpt is still capped at 1,000 characters.

## Window comparison stopped at a failed guard, 2026-10-05

The [window comparison](window-stage4b.json) stopped after 168 changed reads and two
unchanged-prompt controls. All 170 were usable. The controls have byte-identical application
prompts to their five pilot repeats; all changed reads use one frozen runtime and recorded
history. The run leaves 28 planned changed reads unrun, including 20 no-drift case-arms.

The actual page has measured 122 of the 142 no-drift case-arms. One salted session's adopted
arm already has nine citable intent departures against six across its entire old baseline;
another session's current arm has two against one. None comes from the old refused reading.
Unread cases cannot remove those observed flags, so the no-increase guard fails when tested
separately for each session and arm. The plan does not explicitly settle pooling; this is the
conservative interpretation because the two arms compare different requests. A pooled
per-session failure and a full-cohort total decrease are not claimed.

Historical adopted reads used a clipped goal, and the new run adds recorded history as well as
word recovery. The comparison cannot isolate a prompt effect or establish an accuracy
regression. The artifact separates full baseline counts, observed lower bounds, unavailable
pages and the matched subset. Its lost-flag and offer lists cover only measured pairs, never
the unread remainder. Across 40 matched drift case-arms, ten previously flagged arms no
longer flag and nine lose a correction offer. Of ten formerly drawn claims rows marked right,
four are withdrawn across four items; three of the nine unique marked claim items lose every
formerly drawn row and the fourth affected item keeps another row.
Two surviving rows also stop citing the previously marked agent record. Those losses are
listed by salted case and claim ids, without treating unread cases as losses. The right-row
protection check therefore fails too. All marks are agents' development judgments.

This campaign remains failed and stopped. The owner subsequently delegated acceptance to
adversarial agent review, which retained bounded source recovery as explicitly unqualified and
retired the original closed git/gh proof proposal on feasibility grounds. Command incidence
covers at most 35 of the original 61 wrong not-shown flag occurrences before attribution and
truncation guards; current re-marks leave 57. No closed-tier clearance was verified, and its
publisher and model gate were not built or passed. The
[dated ruling](../design-reading-a-session.md#amended-2026-10-05-source-recovery-retained-with-failed-accuracy-qualification)
keeps the failed result and a narrower rollback option.

That ruling removes the retired proposal as a prerequisite for prospective newest-final work.
Independent source, privacy and consent checks still gate that work. No new Analyze measurement
qualifies newest-final or turn-scope accuracy. A later preregistered campaign must bind fresh
matched conditions and its actual model; it cannot convert this campaign into a pass. At the
2026-10-05 amendment it is not runnable until its exact protocol and aggregate transport guards
are built and reviewed.

The ledger ends at 631 of 870, with 239 left: 199 verified calls in this run, plus five
conservative reservations for earlier test calls whose execution could not be proved. The
two-unusable-call budget stop did not fire. Spend stopped at the failed measurement guard.

## The shared closure guard

The previous [eighth Claude qualification](../abstention/claude-results-continuation-8.json) failed after
two parsed readings. An approval-qualified outcome was judged without established scope,
triggering the persistent safety stop. All ten shared and 38 native charges remained spent;
29 qualification attempts stayed held, alongside 190 replay and 18 live attempts. No availability
retry, remaining first pass, repeated reading or browser verification followed. A working
transport and a correctly answered opening do not qualify the producer.

The [ninth Claude result](../abstention/claude-results-continuation-9.json) completed all thirty
registered readings on ten cases repeated three times. Its verdict is `failed`; the owner
removed its first-failing-semantic-batch stop, so `stopped: false` records completed
measurement rather than success. All wrong answers remain scored. Native charges are
68 of 69 and shared charges are 40. The unused availability retry stays held, alongside
190 replay and 18 live attempts. The
[outcome record](../abstention/README.md#ninth-qualification-outcome-2026-10-07) owns the
counts and interpretation. Earlier stopped runs and the operational acceptance are unchanged.

The [tenth continuation amendment](../../SECURITY.md#tenth-qualification-continuation-2026-10-30)
admits one more epoch, six, under the same measurement rule. It carries the held retry and
renews thirty attempts, for ceilings of 99 native and 279 shared. If it fails, one retry epoch,
seven, may follow with at most 31 more calls (at most 130 native and 310 shared). Replay and
live stay held.
The [tenth Claude result](../abstention/claude-results-continuation-10.json) completed all
thirty registered readings in epoch six and failed, with five semantic failures and no unusable
attempt. Native charges are 98 of 99 and shared charges are 70. Its unused availability retry
carries to the one funded retry epoch, seven, whose ceilings would be 129 native and 309 shared.
The [outcome record](../abstention/README.md#tenth-qualification-outcome-2026-10-30) owns the
counts and interpretation. The spend ledgers this README names stay under `~/.cargento`, where
they were written; the cases, marks and outputs still follow `COMPASS_HOME`.

Technical guards and the finite cap remain. An independently reviewed batch is measured,
not qualified. Only a full passing result and
qualification acceptance may arm the separately guarded Claude-only browser reading. Its
one attempt comes from the existing live allowance, leaving 17 live and 190 replay held.
The [dated security amendment](../../SECURITY.md#conditional-priority-qualification-measurement-2026-10-07)
owns this exception and the [browser contract](../../SECURITY.md#one-qualified-claude-only-browser-reading-2026-10-07)
owns the one-call route. Neither construction nor source preparation is a measured pass.

The follow-up allowance is 239 additional Analyze attempts in total: 190 replay, 31 qualification
and 18 live. The original failed campaign, its charges, marks and results stay unchanged.
The [security contract](../../SECURITY.md#shared-closure-allowance-2026-10-05) owns the fixed
account ledger, immutable receipts and activation rule.

`scripts/analyze_campaign.py` requires a reviewed manifest at
`docs/drift-replay/closure-campaign.json` before spending. The manifest binds actual final
requests, source code, blind marks, batch boundaries and lane order. Source-only preparation
and fake transports do not qualify the model. Each batch needs native semantic measurements
and independent review before acceptance. A passing transport cannot supply that acceptance.
Earlier campaigns stop at their first failed semantic, coverage or protection guard. The
[ninth-generation amendment](../../SECURITY.md#conditional-priority-qualification-measurement-2026-10-07)
permits completing its registered semantic measurement while retaining failures; technical
guards and final qualification acceptance remain required.

The default lane order remains replay, qualification, live. An owner-authorized prospective
qualification-first campaign may instead use qualification, replay, live within the unchanged
239-attempt total. Qualification keeps all 30 bound request slots and its 31-attempt ceiling,
including one retry. Replay's 190 and live's 14 planned slots must all be deferred; their request
maps are empty and their protocol, binding and evidence fields are explicitly `null`. Planned
slot identities and batch partitions are retained without invented requests or evidence.
Partially held later lanes, held qualification slots and any other order refuse.

The [dated security ruling](../../SECURITY.md#qualification-first-priority-2026-10-06)
lets this qualification lane launch without replay acceptance. Native source admission,
sealed grant and actual model/packet/request bindings, independent batch review, the original
631/28 charges and whole-campaign stop conditions remain required. Held lanes cannot reserve
or pass acceptance, and their allowances cannot be transferred. The authority has no unholding
or reset API; a later release needs a separate reviewed design that preserves charges.
Source preparation and blind marking can proceed before any lane spends.

The owner renewed qualification with 31 fresh attempts after its semantic stop. The
[successor contract](../../SECURITY.md#charge-preserving-qualification-successor-2026-10-06)
preserves the original stopped campaign and appends one separately bound epoch. Its fixed
manifest and independent handoff bind the original two shared charges, thirty native charges
and actual failure receipt before a new zero-charge activation can be reviewed. The new
qualification cap is 31; replay and live remain held, with no allowance transfer or inherited
opening acceptance. Fresh prompts, selections, asked questions and marks must be frozen before
calls. Installing the guard does not activate this continuation or qualify the producer.

The [fresh qualification manifest](closure-campaign-successor.json) and
[independent handoff](closure-successor-handoff.json) bind that continuation to the rebuilt
ten-case packet and its 34 prospectively marked questions. The original manifest and failed
result remain unchanged. This epoch registers only qualification requests; replay and live
remain wholly deferred. Its first batch is one exposure, followed by batches of nine, ten
and ten after measured independent acceptance. An authority or activation receipt establishes
no accuracy result.

`scripts/drift_study_controls.py` isolates experimental reading modules for matched conditions;
the native replay accepts one through its explicit `reading_override` argument. Scope pairs
reserve common room under the longer trusted header and retain equal numbered evidence.
They compare a bundled header and token contract, rather than estimating a pure sentence
effect or reconstructing an old runtime. The production pilot forwards the supplied,
stamp-bound final lookup to the native prompt builder, as the shipped reading press does.
The `newest-final-whole` condition does likewise; `reply-first1000` and both matched scope
controls retain their explicit comparison behavior. Complete newest-final restoration may
reallocate other agent excerpts within the unchanged cap. These conditions need fresh actual-model
measurements; they inherit no historical accuracy claim.

The model-free `scripts/drift_closure_operator.py` owns serial native replay execution.
It binds the checkout and a fixed inventory of ten native implementation files, plus
actual frozen sources, controls and shipped page projection, before a reservation.
Every registration requires an exact positive integer repeat and a unique
`(phase, case, arm, condition, repeat)` identity. Boolean repeats and extra row metadata
cannot alias or shadow another pair.
Every critical predicate must name its requested criterion and source clause, even
when it has no raw-token condition. Every declared case, arm, phase and condition group
needs exactly three static registrations with distinct integer repeats 1, 2 and 3
before preparation can pass. Missing groups refuse before a charge; a complete plan
may still have future outputs pending. The ten original protected rows must have
distinct `(case, arm, claim)` identities, retain nine claim keys and four recorded
withdrawals, and have independent source admission before the first pilot. Missing or
unknown admission refuses without a model charge.

If neither observed arm draws a required protected claim, the grader reports that
comparison as unresolved and adds a coverage failure. The measured report stays short
and cannot be accepted, including when every registered output is present. A partial
plan with no outputs yet defers future comparisons. A new arm that draws the claim does
not require a favorable legacy result; a claim drawn by the legacy arm and withdrawn by
the new arm remains a protection failure. These checks change no original marks, ten-row
denominator, nine claim keys or four recorded losses.

Semantic conditions use two explicit values. `required_page_state` accepts only
`drawn-grounded-departure`: the exact requested criterion must resolve to departure,
remain drawn on the page, and cite every independently admitted joint support member
in raw, native and page citations. Those support identities must be registered before
output even when there is no raw-token condition. `legacy_scope_baseline` accepts only
`report-all-repeats`: each declared case and arm needs three scope/legacy-scope
registrations with integer repeats 1, 2 and 3. The final report records all three actual
criterion results in repeat order, without requiring a favorable legacy result. Missing
or invalid baseline observations leave final coverage short. The same predicate cannot
also declare that report-only legacy condition as a critical-result group; preparation
refuses the overlap rather than dropping a declared obligation.

Arbitrary or prose values in those semantic fields refuse. `failure`, `reporting` and
`rationale` are nonempty descriptive notes, not additional executable conditions.
Historical protocols with unsupported prose conditions remain unchanged and cannot
execute as prospective registrations. A separate new registration must translate their
approved obligations into the supported fields under independent review before
activation. Translation alone admits no source or mark and repairs no historical failure.

The operator then uses the native tagged dry/read route with a distinct charge for each
repeat. Its private journal holds metadata, not recovered reply text. Raw-token predicates
also require every admitted joint support member in raw, native and page citations. The
grader checks all declared critical groups against actual observations before final acceptance.

Each batch waits for an independent review outside the operator artifact directory, bound
to the actual report and attempts. Acceptance hashes the same bounded review bytes it
parsed and refuses a changed file. Restart regrades interrupted durable results; charged
failures remain charged, while a source refusal before any reservation is not a measured
failure. This helper activates no authority and admits no unsupported source or blind mark.
The live launcher refuses alternate unmetered Codex execution during the Claude study.

Unknown future live requests remain explicitly held and unbound. The owner
[retired the cold-study requirement](../design-reading-a-session.md#amended-2026-10-06-owner-the-cold-study-requirement-is-retired)
on 2026-10-06; no cold-study pass is claimed. Complete subprocess and outbound attribution
remains a separate measurement. No registered campaign, qualification grant or measured
result is implied by the guard's source checks.

The [fifth qualification result](../abstention/claude-results-continuation-5.json) stopped after
its opening and one availability retry both returned `model-failed`, with no parsed answers.
Both fresh attempts remain charged; 29 of the 31 fresh attempts are held, and the single retry is
exhausted. The native total is 32, with the original thirty preserved. The original shared epoch
retains its two charges beside the successor's separate two. No opening acceptance or accuracy
verdict was earned. Replay and live stay held; the replay ledger remains at 631 of 870.

After the owner reported repairing Claude Code sign-in, the
[login recovery contract](../../SECURITY.md#login-repaired-qualification-continuation-2026-10-07)
authorizes carrying forward the 29 unused qualification attempts plus two additional attempts.
The new allowance is 31, including its opening diagnostic reading and one retry. Earlier four
shared charges and 32 native charges remain spent; no replay or live allowance is transferred.
The [fixed manifest](closure-campaign-login-resume.json) and
[independent handoff](closure-login-resume-handoff.json) bind that finite continuation.
Private execution diagnostics now retain closed failure categories without raw error text.
The [sixth qualification result](../abstention/claude-results-continuation-6.json) now records
two parsed readings: both Claude Code calls exited successfully, with no unusable attempt or
retry. Only the opening batch was accepted. The next case failed the frozen abstention check
and stopped the campaign. Across seven questions there were four correct judgements, no false
reassurance, one missed departure and two over-abstentions against the rubric. Goal missed an
earlier stall; one outcome line judged an unverifiable condition `not-reached`, and another
abstained instead of the expected `consistent`.

All five recorded case kinds were admitted before spending, but only two reached the model.
The other eight first-pass cases and all second and third readings were not attempted. The
new allowance has spent two of 31 attempts; 29 unused attempts remain held. Native charges are
34 of 63. The shared ledger preserves the original two charges and two in each successor, six
in total. Replay and live remain held; the replay ledger is unchanged at 631 of 870. No
allowance is borrowed, refunded or reset. The result is failed, not a completed qualification.
Investigating non-final conditions and earlier stalls is the next producer task; any change
must fit the 9,216-byte instruction limit and earn its own measured result.

The owner has authorized a corrected per-clause producer and one fresh qualification under the
[seventh continuation contract](../../SECURITY.md#per-clause-qualification-continuation-2026-10-07).
It preserves 34 native and six shared charges, carrying 29 held attempts and adding two for
31 available. The new native ceiling is 65 and the cumulative shared allocation is 245;
replay and live remain held. Source-derived inputs, pre-output expectations, exact model and
request bindings, and an independent charge-preserving handoff must precede execution. The
instruction correction was subsequently measured, and the sixth run remains failed.
The [fixed manifest](closure-campaign-clause-continuation.json) and
[independent handoff](closure-clause-continuation-handoff.json) preserve every stopped ancestor
and bind the new requests before spending.
The [one-time zero-charge reseal](closure-clause-zero-reseal.json) records the scope omission
caught by the full suite and the corrected binding. It preserves the original activation and
changes no charge or allowance.

The [seventh result](../abstention/claude-results-continuation-7.json) failed after two parsed
readings. Both Goal departures were identified, but an approval-qualified outcome marked
should-abstain was judged `departure`, triggering the persistent stop. The frozen rubric counts
three of seven questions correct, two false alarms and two over-abstentions. One attribution
criterion has a latest-report versus persisted-artifact ambiguity; its original count remains
unchanged, and the separate approval-qualified line independently fails the check.

The fresh allowance spent two of 31 attempts, with 29 held and the retry unused. Native charges
are 36 of 65; the shared account preserves all eight charges across its original and successor
epochs. Replay remains 631 of 870, and the held replay and live allowances are untouched.
Only two recorded kinds reached the model; every later case and repeat was unattempted.
The [outcome record](../abstention/README.md#seventh-qualification-outcome-2026-10-07) owns the
full interpretation. Neither this failure nor the earlier operational acceptance qualifies
the producer. A new packet needs clause scope clarified before output and a separately bound
finite continuation; no failed run, key or charge is reset.

## Model-free gap studies, 2026-10-05

These studies keep the original 99 cases and their reads intact. Two agents mark the evidence
without detector output; a third settles disagreements. Initial marks are saved before any later
proof is opened. A separate private cohort is imported with `--study-import <file> --tag <tag>`.
Its `study-<tag>-marks-digest.json` must be committed before `--study-live` or `--study-score` can
produce output. Output closes marking. All these modes call no model.

The [per-question gap study](results-study-gap-truth.json) revisits 161 historical non-claims
departures on four arms, deduplicated to 131 questions at 70 cuts. Of those questions, agent marks
confirm 11 gaps with specific later recorded proof, reject 87 and leave 33 unclear. A positive
needs a later person correction, failed check, retraction or completed sibling result about that
same gap. An opinion, generic continuation or a parent merge receipt alone is insufficient.
Repeated appearances yield 12 positive, 113 negative and 36 unclear flags across the arms. These
are developmental judgments, not a detector accuracy rate. The [committed marks digest](study-gap-truth-marks-digest.json)
binds the private case and proof key.

The [in-drift live study](results-study-in-drift.json) measures all 291 recorded stops, including
104 stops inside 28 annotated drift episodes. The [blind marks digest](study-in-drift-marks-digest.json)
was committed first. This model-free cold-board counterfactual includes recorded history
(`--include-history`), rather than reproducing a particular live board. Agents marked 74 visible gaps, 26 no gap and four unclear stops. All 28
episodes have a measured baseline; 12 contain more than one stop. No early catch is credited:
none of the 17 recorded failure candidates was judged relevant to the current gap. A new cause
must arise inside the episode and have its exact relevance marked before it can count. Other
cause relevance remains unmeasured. There is no lead-time estimate from a zero-catch run.

Outside the half-open annotated spans, 176 stops have a dated opening intent; per salted session
their flagged counts are 30 of 36, nine of 36, zero of 78 and 25 of 26. Eleven earlier stops have
no dated opening intent and cannot produce this arm. The current parser thus finds 187 outside
stops, rather than reproducing the earlier estimate of 183. Being outside a pushback span does
not establish no gap, so these remain raw counts. Within the blind classes, the live estimate
flags nine of 59 defect cuts, three of 16 scope cuts, none of three status cuts and nine of 26
no-gap cuts. Those counts do not establish timeliness or value to a person.

The [Codex parent study](results-study-codex-parent-v2.json) holds one salted annotated case and
counts for 354 parent messages after four canonical injected contexts are excluded. The local
annotation traces a genuine request, an agent handoff that leaves that request unfinished and
the person's correction. `--codex-study <file> --tag <tag>` loads the actual CLI or editor parent
log and masks its words before local storage. It rejects exec and worker metadata and uses the
runtime's measured injection filter. Loading a research case grants no Analyze eligibility, adds
no Codex runtime fact and demonstrates no Codex detector performance.

The [one-case agent-plan measurement](agent-plan-stage4e.json) finds an earlier plan 2,055,393 bytes
before the cut, outside the 400,000-byte tail and absent from its 12 listed agent messages. The
person directed the later detour and had not accepted that plan. This is one agent-marked case,
not a plan detector or evidence that rereading it would improve a verdict. It spent no model call.

The cold walk with two real participants is no longer required under the owner's
[2026-10-06 amendment](../design-reading-a-session.md#amended-2026-10-06-owner-the-cold-study-requirement-is-retired).
Consent and capture review still apply to optional exploratory feedback. Agent browser checks
supply no human participant outcome or producer accuracy qualification.

## The order: cases, blind marks, digest, runs, score

A mark written after seeing an output is agreement, not a mark, so the tool holds this order.

1. `--build` finds every cut: the last turn stop before each pushback, a seeded sample of eight
   ordinary turn stops per session, the stop before each episode's drift began, and the first stop
   after the agent answered the pushback. One cut can hold several of these roles.
2. Mark blind (no flag). One shuffled screen per cut shows your opening message and the last eight
   messages before the cut, and nothing after it: no annotation, no role, no detector output. It asks
   whether the agent had drifted from what you wanted by that point, and if so, what kind.
3. `--reconcile` shows the annotations' answer beside each blind mark that disagrees with it, and you
   decide. Both answers are kept. A mark you have not agreed to is not written (the 2026-09-28 rule).
4. Commit `marks-digest.json`. Marking closes once any output exists.
5. `--live` runs the live estimate and Steer back at every cut. No model, no spend.
6. `--read --dry-run` counts the calls that would reach the model and records that plan. `--read`
   refuses without a plan for the same cases and arms, or when the plan needs more calls than the
   ledger has left, and charges each call before it is made. Two consecutive charged failures
   (`model-failed`, `unstopped`, `oversized`) or replies with no parsed answer stop the batch.
   Failed cut-arms are not saved as read; a tagged retry can read them again, at another charge.
7. `--score` writes `results.json`.

```bash
python3 scripts/redact_session.py --out tests/raw_sessions ~/.claude/projects/<proj>/<sid>.jsonl ...
python3 scripts/drift_replay.py --build
python3 scripts/drift_replay.py                # blind marks; q stops, re-run continues
python3 scripts/drift_replay.py --reconcile
git add docs/drift-replay/marks-digest.json && git commit -s
python3 scripts/drift_replay.py --live
python3 scripts/drift_replay.py --read --dry-run
python3 scripts/drift_replay.py --read         # spends: capped at 870 calls in all
python3 scripts/drift_replay.py --score
```

## The intent arms

Each cut can be read under five intent arms. Four use the person's words dated before the cut; hindsight is written afterwards.

- realistic: the first 240 characters of your opening prompt, saved as typed words when you sent it.
- part: the first message you typed in the annotated part the cut belongs to.
- hindsight: the goal the annotation wrote afterwards. It is a retrospective comparison, not an upper bound or a headline.
- adopted: the opening prompt taken with "Use your prompt", so the producer knows its source.
- current: a goal and up to three outcome lines drafted from your own messages before the cut, by
  agents shown nothing the session's agent said, as if you kept your intent up to date. They live in
  `~/.compass/drift-replay/current-intents.json`, with the time they would have been saved.

## How to argue with a result

Each detector lands in one outcome per cut and arm.

On a cut you marked as drift:

- flag after start: it flagged, and what raised it happened at or after the drift began. This is a time test, not a judgement that the flag names the gap. For the live
  estimate that is the rise it names, or else the latest failed check; for Analyze, what a
  departure cites
- irrelevant flag: it flagged on something older, such as a check that failed hours before
- unattributed flag: it flagged, and nothing says what raised it, or the cut has no drift start
- echo: an Analyze departure that cites only your own messages. Each departed question is judged
  on its own cites, and a claims departure leaves out the claim it names before it is judged, so
  "the agent said X, and you said otherwise" is an echo
- withheld: "Not enough recorded yet" or not verifiable
- not reached: a cited unfinished-work result at a non-final stop, kept apart from withheld and reassurance
- reassured: None or low, or consistent; the worst outcome
- refused: the apparatus could not read the cut, or the model call failed

On a cut you marked as no drift: false alarm, quiet, withheld or refused.

New schema runs also retain the not-reached outcome on no-drift cuts. A separate departure still
counts; unfinished work never hides it. The page-answer column can say "Can't tell" when another
line remains unverifiable, even when one line is unfinished.

Before changing the non-final schema, agents blind to detector output sorted 58 historical
current-arm no-drift intent departures. The [frozen sort](scope-stage4d.json) records 24 safely
unfinished questions, 25 departures, eight consistent questions and one unclear question, with
the marks digest. Critical controls were checked against fuller pre-cut context before the prompt
changed. This is a pre-change semantic sort, not evidence that a new model reading improved.

Historical runs counted the composer's offer, even where the page showed a Keep/Add question instead. They did not store correction text. New runs retain the composed text locally and execute the shipped page reducers to count questions, primary and secondary offers, and no offer. They name whether the reader is available and whether Keep is assumed.

Withheld counts as a miss when the question is whether drift was found, and it is shown on its own
because abstaining is the designed behaviour. Only the first pushback of an episode counts toward
catches; a later one is persistence. A departure that rests only on your own earlier correction is
an echo, not a catch.

Four sessions from one person is a development set. It supports "caught this, here, because of that"
and "cannot see this kind at all". It does not support a rate. A rate needs sessions collected after
the check is frozen.

## The first run, 2026-10-04

The owner delegated the marking. Two fresh agents marked all 99 cuts blind, a third broke two
ties, and two more reconciled the 26 cuts where the blind answer disagreed with the annotations,
each seeing what the person typed next; four final cuts are unclear and left out of historical final-key counts. None
of them had seen any detector output, and the marks digest was committed before any run. Every
marker is an agent, likely of the same model family as the Claude Code reader being scored, so this
is not a human key.

Live estimate and Steer back ran at every cut and arm. Analyze ran the realistic and part arms only
(195 calls of the 240 authorized; the hindsight arm would have passed the cap), and every call came
back as a reading. A score models a reader who presses "Keep my intent and analyze", because the
page otherwise shows a departure as not verifiable while a later direction is unsettled.

What it found, on four sessions from one person (a development set, so no rates):

- Neither detector separated drift from no drift. On the realistic arm, Analyze raised a departure at
  8 of 22 first-pushback drift cuts and 26 of 71 no-drift cuts; the live estimate flagged 8 of 22 and
  19 of 71, every time on a failed check, some of them days old.
- Two blind judges, shown each flag's evidence beside the drift without being told which detector
  raised it, rated none of the live estimate's 14 flags on drift cuts as pointing at the drift, and
  one Analyze cut as doing so: a "running" claim at a later pushback in the same episode. The later claim-truth pass marked it true; a launch alone does not prove continuing activity. It was not a first-pushback catch.
- The intent fed to Analyze drove most of the result. A goal adopted from the opening prompt keeps
  240 characters, which in one session cut off the instruction that mattered and in another kept
  only plan-file preamble, and after the work moved on, many later turns read as departures from it. The result was not monotonic in the number of later messages. About 7 of the 26 no-drift departures were model errors, two of them reading a
  passing run as failed.
- Most of the drift the person pushed back on (false status claims, buried questions, effects seen
  only on their screen) was not settled by the blind markers' clipped screen. That does not establish invisibility in the full record; screen-only effects remain outside Compass's view.
- Steer back was offered at 68% of drift cuts and 72% of the rest.

The historical `relevant-flag` outcome in `results.json` uses the time rule above (new scores call it `flag-after-start`), which nearly every flag
passes because a departure usually cites the agent's last message; the blind judges' ratings are
the stricter reading. `results.json` counts 24 drift cuts; 22 of them are first pushbacks.

## The second run, 2026-10-04

After the first run, two product changes merged in #482. The intended change reads a goal adopted from your prompt whole, up to 1,000 characters, and every reading also asks a `claims` question that does not depend
on the intent: does a status claim in the agent's own words go against the record, or does nothing
in the record show it? The second run read the same 99 cuts against the same marks, on two new arms.
The adopted arm marks your opening prompt as adopted. The source was outside the tail at every cut, so all 99 reads fell back to the 240-character clip; this run did not test the whole-prompt behavior promised by DEC-22. The current arm is a goal plus up to three
outcome lines, which fresh agents drafted from your own messages before each cut, without seeing
anything the agent said. That took 198 Analyze calls, so 393 of the 440 authorized have been used.
`results.json` scores Analyze as a whole, and the intent questions and the claims question
separately.

On the 22 first-pushback drift cuts against the 71 no-drift cuts:

| Detector | Adopted arm | Current arm |
|---|---|---|
| Analyze, any departure | 12 of 22, 42 of 71 | 14 of 22, 38 of 71 |
| Intent questions only | 10 of 22, 29 of 71 | 7 of 22, 29 of 71 |
| Claims question only | 9 of 22, 20 of 71 | 9 of 22, 16 of 71 |
| Live estimate | 8 of 22, 19 of 71 | 9 of 22, 29 of 71 |

A fresh critic checked every flag before these numbers were reported, and most of the apparent gain
did not survive:

- The judged first-pushback catch at d133d4d6 was a claim that reviews were running. It was marked true, and neither arm reproduced the flag on an unchanged-prompt re-read. This is not a stable catch. The blind judges rated two more cuts as catches. One rests on the person's own
  screenshot complaint, which makes it an echo the scorer's rule lets through because one other cite
  is an agent message. The other repeats the agent's own admission that the tool was unusable. A
  later "nothing is running" catch on a persistence cut is also an admission.
- The claims question's lean toward drift (9 of 22 against 16 of 71 on the current arm) comes mostly
  from one hour of one session. Outside it the split is 5 of 17 against 12 of 57. The question is
  also unstable: it does not depend on the intent, yet the two arms agreed on only 12 of the 42 cuts
  either one flagged.
- Of the 36 claims flags on no-drift cuts, 17 were claims the prompt already says to leave alone
  (merged, CI running, posted) or were not status claims, 13 were true claims the record could not
  show, 5 were model errors that read a failure 45 to 76 minutes old as contradicting a later green
  run, and 1 was a real unsupported claim ("Built and working", half an hour before the person found
  the tool broken). The marks measure pushback, not whether a claim was true, so that one scores as
  a false alarm.
- The reading saw too little of the record to answer the claims question. Across the 99 cuts it saw
  1,062 checks with no recorded result, 48 failures and no passes, and 22 file writes. Most runs
  have no recorded result because they are compound commands, such as a search, then a test run
  piped to `tail`, and their output cannot be attributed to the check. That is not why no pass was
  seen. The collector's own scan of those cuts held 85 passing checks, at least one on 54 cuts, and
  418 written paths, and the 12 listed entries put runs with no recorded result ahead of passes and
  writes, so none of the passes and few of the writes reached the reading. A "suite is green" or
  "file written" claim was therefore nearly always "not shown by the record".
- Steer back on the current arm was offered at 2 of 22 drift cuts and 12 of 71 others, at 15 of the 29 cuts with a failed check, where the failed check was inside the window. That is an artefact: each drafted intent was saved at your
  last message, so no later direction exists, and the replay never hands Steer back a reading. The live estimate's extra flags came from path-shaped words in the drafted intent, including branch names and issue pairs read as folders. Missing later directions only block None or low; they do not raise High.
- No drafted current intent encoded the coming pushback. Several restate an earlier complaint, which
  is what an intent kept up to date should do.

So the second run does not show that either new question detects drift. What it supports is three
changes. Let the claims question treat a check whose result was not recorded as unread, and stop it
citing a failure as a contradiction when a later run of the same check exists. Enforce in code the
claim kinds `unsupported` may apply to (passing, fixed, written), which would remove 17 of the 36
false alarms above. And score a departure as an echo when its contradicting evidence is your own
message or the agent's own admission. A third run would also mark each claim as true or false rather
than by pushback, so an early warning like the one above counts.

## After the second run: what review left standing

Three reviewers attacked those three changes on 2026-10-04, and the owner delegated building what
survived. The first change was dropped: treating every run with no recorded result as unread would
also silence the real catches, because nearly every cut has one. The second was dropped too: a word
list over the agent's message removes real catches, and the answer has no room for a claim kind.
Admissions are not read by a word list either, because the one tried flipped a real catch and missed
its own case. What was built instead:

- The listing puts passes and writes ahead of runs with no recorded result (DEC-23 item 4, amended
  in [the design record](../design-reading-a-session.md#amended-2026-10-04-no-recorded-result-is-listed-last)).
- A claim is not "not shown by the record" when the session holds a pass or a write inside the
  reading's window that the prompt did not carry. A failure does not contradict a claim when, after
  it and before the claim, the agent ran the same tool again, the run did not fail and had no
  earlier failure, and it named nothing after the tool but flags or `.`. A run naming any target,
  or a flag's value, leaves the contradiction standing. The working directory is not recorded, so
  the same command in two folders reads as one run
  ([DEC-17](../design-reading-a-session.md#amended-2026-10-04-owner-what-the-agent-claims-is-its-own-constraint)).
  On the second run's 7 claims departures this withdraws none.
- The scorer judges each departed criterion on its own cites, and a claims departure leaves the
  claim itself out before asking whether everything left is your own words. On the second run's
  readings this turns one judged catch, on the current arm, into an echo.
- Claims can be marked on whether they were true and whether you could have seen it, and a narrowed
  re-read can be written beside the second run's output. Both are below.

### Marking claims true or false

`--claims-export` collects every claims flag the reads raised, `departure` or "not shown by the
record", into `~/.compass/drift-replay/claim-items.json`, one item per cut and claimed message.
An item names the session, the cut and where the claim is in the log, and never the case, which
arm or question raised it, or what the reading said: the case id keys `results.json`, so naming it
would show the outcome. `--claims-mark` then shows each one: the eight messages before the claim,
the claim itself with its own time, found inside the reply that holds it with a little of that
reply before and after, and up to 40 messages after it, with the cut's time. It asks two questions
and a one-line reason:

- true: was the claim true when it was made, judged from the whole session, including what came
  after (yes, no or unclear)
- visible: did anything you could see in the session at that time show it (yes, no or unclear)

The answers go to `~/.compass/drift-replay/claim-marks.json`, and `claim-marks-digest.json` here
holds its sha256. Commit the digest before scoring. `--score` then adds a `claims_truth` section to
`results.json`, but only when the local marks hash to the digest as committed at `HEAD`. Per arm, a
`departure` is right when the claim was false, and a "not shown by the record" is right when the
claim was false or you could not see it; each count also says how many were wrong, unclear or
unmarked. Items are keyed by salted ids, as cases are.

### A narrowed re-read

`--read --tag <tag>` writes `read-<tag>.json` and its own plan, `plan-<tag>.json`, so the second
run's `read.json` is never touched. `--case <id>` narrows it to one cut on every `--arm` given, and
`--case <id>:<arm>` to one cut and one of those arms; an id may be its first eight characters. The ledger, its cap
and the dry-run plan rule are unchanged, and the ledger's floor counts every read file.
`--score --tag <tag>` scores that file into `results-<tag>.json` and leaves `results.json` alone; a
cut and arm the plan did not choose reads `not-run`.

As of the owner's 2026-10-05 amendment, `--read --claude-reading-model <id>` chooses an admitted
Claude model under the [Sonnet baseline policy](../../SECURITY.md#amended-2026-10-05-claude-reading-model-baseline).
The default is `claude-sonnet-5-5`. Give the same selection to the dry run and the spending run:
the plan and each charged record bind the selected model, admission policy and restricted argv
digest. Every charged attempt, including an unusable reply, also binds its tag to that producer
in the spend ledger. The ledger records a digest of the tag's output location rather than its raw
path; it adds no prompt words. Failed cut-arms remain retryable with the same producer, and their
charges are not refunded. A tag with another model, or old records or a historical plan without
that binding, requires a fresh tag.

Before spending, the runner rebuilds every pending prompt without a provider and compares its
digest and byte count with the dry plan. A changed fixture, producer or pending prompt requires
another dry run. A second comparison at each charge catches a prompt that changes after this
preflight; completed cut-arms retain their existing results on resume.
The selected ID does not establish the served snapshot, which remains unknown; historical
qualification belongs to its recorded model and execution envelope.

```bash
python3 scripts/drift_replay.py --claims-export
python3 scripts/drift_replay.py --claims-mark
git add docs/drift-replay/claim-marks-digest.json && git commit -s
python3 scripts/drift_replay.py --read --dry-run --tag listing --case <id>:current ...
python3 scripts/drift_replay.py --read --tag listing --case <id>:current ...   # spends
python3 scripts/drift_replay.py --score --tag listing
```

## The third run, 2026-10-04

The third run asked two questions. Were the claims the second run flagged true? And did the changes
above make the flags better?

Two fresh agents marked every claim the second run flagged, 51 of them, blind to which arm or
question raised each one and to what it said. They agreed on 47, and a third agent settled the
other four. Each marker read the session after the claim to judge whether it was true. Like the
first run's marks, these are agents' marks, not a human key.

- 44 claims were true, and the session showed them in a command's output or a tool's result before
  the agent said so. Five were false in part, with the true part shown, one was false and not shown,
  and one was unclear and not shown.
- Scored that way, "not shown by the record" was right on 6 of 50 flags (1 of 27 on the adopted
  arm, 5 of 23 on the current arm), and a claims departure was right on 2 of 7.
- The right ones were claims that went beyond the work: every case "mutation-verified" when one
  never was, a tool "built and working" that the person could not use, a merge expected to pass
  that left 34 failures. The earlier flags were not two reproduced catches. "Built and working" was false, and the earlier "reviews are running" judgement was true. The re-mark below distinguishes proof of a launch from proof of continuing activity.
- Most of the wrong ones were true claims shown by output Compass does not read: plain shell output, `git` and `gh` results, and replies from connected tools. Listing passes cannot fix that. The
  reading carries checks and file writes, and the person sees everything.

The re-read took 34 calls (the ledger now stands at 427 of 440). It read the 32 flagged cuts and
arms whose listing changed, plus the two arms of d133d4d6, whose prompt did not change, as controls.
`results-third.json` scores it.

- On those cuts and arms the flags fell from 34 to 20: 19 to 9 on cuts with no drift, 12 to 10
  on drift cuts and 3 to 1 on unclear ones. Against the claim marks, right flags fell from 5 to 2
  and wrong ones from 29 to 18. Nine of the new flags named claims nobody had marked; both markers
  found all nine true and shown.
- The new rules withdrew five: three as `claim-record-unread`, where the listing or byte bound had
  left a pass or write out, and two as `check-does-not-show-it`.
- Both controls changed with no change to what was sent: each went from "not shown by the record"
  to withdrawn, because the model did not cite the claim. Two reads of one prompt differ about as
  much as the change did, so this run cannot credit the drop in flags to the listing.

So listing passes and writes gives the reading the evidence it lacked. It does not make "not shown
by the record" worth showing. On these sessions it is wrong about nine times in ten, because the
claims are mostly true and their proof sits in tool output the reading never gets. That leaves two
choices. The reading can carry the output a claim rests on (a `gh` or `git` result, a tool's reply),
which changes what is sent and needs the owner's ruling. Or "not shown by the record" can stop
counting toward Medium until it does.

## The instrument repair, 2026-10-05

The old arms and stored model replies stay unchanged. New tagged scores execute the shipped page's answer and level guards, show the blind marks beside the reconciled key, and split counts by kind and salted session group. Stops inside an annotated drift window are listed separately from ordinary no-drift controls. Every mark is an agent's; the owner's review remains pending.

The first instrument score passed a truthy object as the page reducer's route-limit notice and
silently demoted claim and outcome rows. It is superseded by this repaired measurement. The
[corrected old-arm score](results-stage0-old-corrected.json) reuses the stored replies, with no new model calls. Its final key has 22 drift cuts, two persistence cuts and 71 no-drift cuts; four unclear cuts contribute only to the blind column. With no outcome lines, all 95 adopted-arm page levels say "Not enough recorded yet", despite model departures. On the current arm, the 71 no-drift cuts show 12 High, 27 Medium, 31 "Not enough recorded yet" and one refused reading. These are page levels after Keep plus analysis, not model verdicts or an evaluation of a new prompt.

A complete-input, model-free baseline reproduces all 492 composer offers. Worktrees need the nested child logs as well as the four parent logs; omitting them changed 19 offers. With an available reader and no analysis, the actual page shows 214 later-direction questions, 65 secondary Steer back offers and 213 with neither; its offered boolean agrees on all 492. The adopted-source dry run finds the prompt at all 99 cuts, with no fallback. That repairs the source lookup; stored adopted reads remain evidence for the old clipped arm until new reads test the change.

`--include-history` is a labelled cold-board counterfactual: bounded, title-only backfill, 24 hours and 512 events. At 99 cuts it retains 1,405 event observations, prunes 134 by age and none by the event cap. These are repeated observations across cuts, not distinct events. A model-disabled live board lists an older direction that Add still refuses outside the tail. The intent-window carry must ship before the revised current arm is measured.

Two fresh blind agents re-marked nine distinct running or waiting claims (eleven review memberships overlap); they agreed on eight, and a third resolved one tie. Three answers changed. Launch or status wording alone is not proof that work is still active, and collapsed output is not proof a person could not see it. The local key preserves the previous marks and each labelled answer; the digest records 55 agreements and five ties across all 60 items.

New reads keep their raw verdict, model status, prompt digest and saved intent/window locally, before rule effects. An adopted arm whose recorded sources all fall back is refused by the scorer. Tagged live runs preserve the old live.json; `--counterfactual-read base` explicitly models Keep plus the stored read. Scoring can name its inputs with `--score-read base` and `--score-live <tag>`, while `--tag` names the new result. Correction words, paths and model sentences stay outside Git.

No run evaluated the unasked lane. Its rules and daily cap exclude many away-person moments; these four Claude Code sessions do not establish its value, or the behavior of the thinner Codex reading path.

## Agreement rules, 2026-10-05

The [agreement score](results-stage1-agreement.json) reuses the same stored replies under the
shared last-person failure boundary and claim caution rules. At the 71 no-drift current-arm cuts,
the page shows two High, 29 Medium, 39 "Not enough recorded yet" and one refused reading,
compared with 12 High, 27 Medium and 31 not-enough before the change. Primary corrections fall
from 38 to 29; secondary corrections rise from one to ten. These are deterministic page effects,
not evidence that a changed model prompt detects drift better.

A complete-input replay of Keep plus those readings agrees on all 492 composer/page offered
booleans: 130 primary corrections, 66 secondary and 296 with neither. No correction carries a
later-direction line. All five specified right-flag cut-arms still offer a correction, and none
of the current-arm live High cuts lacks a cited correction entry. Realistic live High falls to
two of 99 cuts under the last-person boundary. The replay admits the write half of folder
evidence; its redacted working directory cannot establish whether a named folder exists.

The agent marks still decide which cuts count as no drift. The prepared owner review can change
that key. No new model call was made for either score.

## Reading coverage, 2026-10-05

The [coverage reconstruction](coverage-stage2.json) measures the actual bounded transcript tail
at each of the 99 frozen cuts behind 426 stored readings. All 426 files exceed the tail's byte
bound; at 387 readings the tail begins inside the intent window (123 adopted, 79 current, 86 part
and 99 realistic). At the other 39 it begins before the window. No measurement is unknown. This
reconstructs what a new press would disclose, rather than adding measurements to old readings.

The required control's four cut-arms have seven intent rows, all tagged by the shipped page as
possibly in the part not read. Claims remain independent. Long and short fixtures distinguish a
truncated tail from a complete file after a silence; a changing file is unknown. Coverage changes
no model prompt or verdict and spends no model calls. The owner marks and new-prompt checks
remain pending.

The owner approved one further qualification continuation after the seventh result: 29 carried
attempts plus two renewed attempts, with no refund of the eight shared or 36 native charges.
The [clause-isolation contract](../../SECURITY.md#clause-isolation-qualification-continuation-2026-10-07),
[fixed manifest](closure-campaign-clause-isolation.json) and
[independent handoff](closure-clause-isolation-handoff.json) keep replay's 190 and live's 18
attempts held. Thirty fresh readings and one availability retry fit the new 31-attempt
allowance. The new cumulative ceilings are 247 shared and 67 native charges; older keys retain
their ceilings. Fresh scope adjudication and checked transfer bind expectations before output.
This preparation does not qualify the producer or resume the stopped seventh run.

## Masked values, 2026-10-28

The runtime hands each reading the values a shell call masked on its command line, and the reading
scrubs a stored explanation with them. `drift_replay.py` now passes `press.masked_values` the same
way, so an explanation a replay stores is scrubbed as a reader's would be. The values reach only
that scrub: they are not in the prompt, so no frozen prompt byte, prompt digest, marks digest or
stored result moves. The model's raw reply (`raw_verdict` in the local results) is kept as the model
wrote it and is not scrubbed, as before; those results stay under `~/.compass`.
