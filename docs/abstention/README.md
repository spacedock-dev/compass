# The abstention check, committed half

What DEC-17's abstention check expected and what the producer did, and never the session text
either was drawn from. The ruling that fixes this split is restated in
[SECURITY.md](../../SECURITY.md#the-abstention-check); the reasoning behind the check is
[DEC-17](../design-reading-a-session.md#the-condition-on-enabling-not-on-building).

The captain accepted the twelve marked recorded cases as sufficient to enable reader-requested
readings on 2026-09-14. [acceptance.json](acceptance.json) records that decision and the bound
answer key. The runtime publishes `accepted`; no scoring verdict is implied. The
[amended ruling](../design-reading-a-session.md#amended-2026-09-14-the-captain-accepts-the-case-review)
owns enablement. The scoring format and verdicts below remain available for evaluating the producer.

That acceptance covers the Codex producer only. The Claude Code producer built by DRC-4650 has its
own gate, `annotations.CLAUDE_ABSTENTION_CHECK`, and it is recorded `not-run`. No Claude Code
qualification has passed. The committed [first Claude Code run](claude-results.json) failed with
four false reassurances. The [reviewed continuation](claude-continuation.json) bound five cases
re-frozen from that recorded packet to the same spend ledger; its
[result](claude-results-continuation.json) also failed, with five false reassurances. The
[second continuation](claude-continuation-2.json) scored a fourth packet, with a supported departure
resting on the reader's own correction, after the producer's evidence instruction (#450) and the
reader's whole words (#467) changed; its [result](claude-results-continuation-2.json) failed too,
with one false reassurance and fifteen correct judgements, and spent the last of the 23 calls. A
[third continuation](claude-continuation-3.json), after the rule that withdraws a line about what the
agent tells you (#471), scored the same five cases; its [result](claude-results-continuation-3.json)
failed with one false reassurance on a different constraint (a goal the second run had right), and
spent the last of the 28 calls the owner authorized. The
owner then kept the gate shut and authorized one more five-case run past that ceiling, as a third
continuation: 28 scorer calls, beside 31 Claude CLI invocations overall. The
[amendment](../design-reading-a-session.md#amended-2026-10-01-a-readers-correction-and-a-transcript-stop)
records the ruling. No third grant is committed yet. The accepted
packet was reviewed against Codex readings. The scorer can
report either producer (`--producer claude` or `--producer codex`), but this qualification scores
Claude Code only. Format 5 below is the packet DRC-4666 qualifies Claude Code against. A fresh
qualification is separate work. Writing a Claude Code
result opens nothing: the gate moves only in its own reviewed commit. Until then, Codex keeps
reading Claude Code sessions and the page says so before the press. The
[amendment](../design-reading-a-session.md#amended-2026-09-23-claude-code-is-built-and-gated) owns
that ruling.

On 2026-10-02 the owner accepted the Claude Code producer anyway, knowing every scored run above
failed, and `annotations.CLAUDE_ABSTENTION_CHECK` is now `accepted`, never `passed`; the paragraph
above describes the gate as it stood before that day. [claude-acceptance.json](claude-acceptance.json)
records the decision and lists each scored run with its own verdict (`failed` for all four), its
digests, counts and spend, which a test reads back from the result files. Nothing in this directory
was rewritten, rescored or deleted to make room for it. Claude Code now reads a Claude Code session
when `claude` is on PATH, and Codex reads it when not; the
[amendment](../design-reading-a-session.md#amended-2026-10-02-claude-code-is-accepted)
owns that ruling.

## What lives here

`results.json` for the Codex producer and `claude-results.json` for Claude Code, once a scoring
run has been committed, written by `scripts/score_abstention.py --score --producer <name>`. A new
Claude Code packet, if authorized after the failed run, writes `claude-results-continuation.json`
and leaves the failed file in place. The handoff is `claude-continuation.json` and must be reviewed
before scoring. Each later continuation follows the same pattern: grant k is
`claude-continuation-<k>.json`, and its packet writes `claude-results-continuation-<k>.json`, leaving
every earlier failure in place. So the second is `claude-continuation-2.json`, writing
`claude-results-continuation-2.json`, and the third `claude-continuation-3.json`, writing
`claude-results-continuation-3.json`. Each result holds:

- `producer`, `model` and `argv_digest`: which producer ran, the model id it passed, and the
  sha256 of the argv its exec builds, read without starting a process. A later change to a flag,
  the model or the effort moves the digest, so a result cannot be carried over to a producer that
  no longer runs that way.
  The owner's 2026-10-05 [Sonnet baseline policy](../../SECURITY.md#amended-2026-10-05-claude-reading-model-baseline)
  defaults new Claude runs to `claude-sonnet-5-5`; `--claude-reading-model <id>` selects another
  admitted model. `model` records that selection, while the served snapshot remains unknown.
  Changing the selection requires its own qualification; no earlier result is promoted by name.
- `destination`, `binary` and `cli_version`: where `reading_route.destination` says the call goes,
  the installed CLI it ran (its path with the home directory written `~`) and that CLI's
  `--version` line. A Claude Code result is written only when the destination is `Anthropic` and
  the CLI is the native installer's, a file under `~/.local/share/claude/versions` named for the
  version it reports. A stub on `PATH` or an `ANTHROPIC_BASE_URL` pointed elsewhere refuses the
  run before anything is written.
- `signature`: what vouches for that CLI's origin. On macOS it is
  `Developer ID Q6L2SF6YDW com.anthropic.claude-code`, written only after `codesign` confirmed the
  pinned requirement, and an unsigned or foreign binary refuses the run before it is executed. On
  Linux and Windows no signature is checked, and it reads `unchecked sha256:<hex>`, the hash of the
  file that ran. [SECURITY.md](../../SECURITY.md#the-abstention-check) states that limit.
- `spend`, the calls charged to the spend ledger when the run finished and the cap it ran under.
- `marks_digest`, the sha256 of `~/.compass/abstention-marks.json` as it was when scored. A later
  `--report` hashes the marks again and refuses PASS if they moved, because a mark written after
  seeing an output is agreement, not a mark.
- `inputs_digest`, on a historical replay: a hash of the cases and rubric as scored. A later
  report refuses PASS if either changed. The inputs themselves stay local.
- `marks`, the captain's answer key: one sixteen-character hash of `(harness, sid)` per case, and
  `judge` or `abstain` for each constraint: `goal` and `output` in the older formats, `goal` and
  `line_1` to `line_k` in format 5, plus `claims` when asked. Copied from the scored records as closed tokens, never from the
  marks file, which is hand-editable.
- `cases`, per case id: the harness, the marks, the outcome the producer landed in for each
  constraint, whether the case reached the model at all, and `asks_output`: whether the Expected
  Output question was put to the model. Only a case whose record shows work (a Pi work result,
  since the check never grants tool output) is asked it. On every other case the collector fixed
  that mark to `abstain` and the producer answers `not verifiable` without asking, so the output column there is the ruling's answer and the
  report says so instead of counting it as the model abstaining. `counts.output_not_asked` is how
  many cases that covers. In format 5 a Claude Code case's frozen checks are work evidence, so its
  lines are asked when the record holds a check or a written file.
- `basis`, per case and constraint, what a judged result rests on: `tool` only when it cites a check
  with a recorded result, `account` when it cites what the agent said or did (a written file shows
  the agent acted, not that anything checked it), `person`, `derived`, or empty
  where nothing was judged. A Goal `consistent` resting on the agent's account is never counted as
  tool-reported; `counts.goal_consistent_on_account` is how many there were.
- `counts`, `dec17`, `coverage` and `verdict`, which are what the report prints.
- `rubric`, per DEC-15 expectation case: the kind, the origin, whether it was admitted and, when it
  was not, a token saying why; whether a case with that id was scored at all; and the two scored
  columns, judgement and extraction.

Nothing here names a session, a project, a title, a prompt or a model sentence. A test asserts that
none of the local half's fields -- the session id, the project, the title, the opening ask, the
cutoff sentence, the model's detail -- appears in it, by name or by value.

## What does not live here

The cases (`~/.compass/abstention-cases.json`) name sessions and carry one user turn each. The
local results (`~/.compass/abstention-results.json`) carry the producer's withheld reason and its
cutoff sentence. The rubric expectation file (`~/.compass/abstention-rubric.json`) may carry
synthesised case bodies. All three stay on the machine that made them.

## Premarked false-consistent cases

`scripts/premarked_cases.py` holds nine synthetic cases in five classes: a command that cannot
fail (`echo`, `true`, `exit 0`), a command forced to exit zero (`make deploy || true`), CI for a
commit that is not the session's, CI after the session edited a workflow file, and a CI poll of
another pull request or repository. Each is one goal or first line whose words the cited evidence
would falsely support. The table carries no expected outcome. A different agent wrote
`premarked-false-consistent-marks.json` from the case descriptions and the written rulings alone,
before any run, using one of two tokens: `withdrawn` (the line ends not verifiable) or
`caution-kept` (it stays consistent and the prompt carries the caution, as the ruling for an
edited workflow requires). `premarked-false-consistent-marks-digest.json` binds the marks file and
the case table by sha256, and it was committed before the run test existed.

The cases are synthetic (`acme/widgets`, `fix/widget-guard`, repeated-digit commits), so they and
their fixtures are committed, unlike the recorded cases above. Nothing here calls a model.
`compass/skills/compass/tests/test_premarked_false_consistent.py` runs each case through the real
reader with a fake model that answers consistent and cites every ledger row, and checks the
outcome against the committed mark, the digest file against both inputs, and that the marks were
committed before the test. `python3 scripts/premarked_cases.py` prints the table, and `--run`
refuses unless the committed digest equals the working copy. The same cases against the real
producer are owner-gated spend and are not part of this check.

## Masked values, 2026-10-28

The drift replay passes the values a shell call masked to the producer, as the runtime does (see
[the drift replay record](../drift-replay/README.md#masked-values-2026-10-28)). The abstention
tools (`mark_abstention.py`, `score_abstention.py`) and `levels_cases.py` do not.
`mark_abstention.py` and `score_abstention.py` read frozen cases that carry each check's tail,
later-command pairs and incomplete-read pairs but no masked values. `levels_cases.py` sends no
tails and freezes only the later-command and incomplete-read pairs. None of them freezes masked
values. Freezing them would write credential-shaped values into case files and change the
case packet that the marks digest and the inputs digest bind, so a sealed input would move. The
effect is limited to an explanation: a masked value that a stored explanation quotes is not
scrubbed in these studies' local results, while the runtime would scrub it. The prompt, which
never carries those values, is unchanged, so the figures these tools report do not depend on it.

## Historical replay, case format 4

Older case formats fetch the current row and facts from the live board at scoring time. That
cannot reproduce a historical case: the session may have disappeared, its lifecycle may have
changed, and its old facts may no longer be served. Format 4 reads a frozen packet offline.
`mark_abstention.py --build` still produces the older live format; a replay packet must be
prepared from recorded evidence before marking.

The local `abstention-cases.json` has `v: 4`, the `goal` and `output` yardstick strings, and a
`cases` list. Each case carries:

| Field | Meaning |
|---|---|
| `id`, `harness`, `sid` | The canonical session hash and its recorded identity. Replay admits Claude, Codex and Pi; duplicate IDs and hashes that do not match the identity are refused. |
| `origin` | `recorded`. Generated cases belong in the separate rubric file. |
| `captured_at` | A finite, positive Unix timestamp: the time being replayed. |
| `row_snapshot` | The row observed then, including its explicit `working`, `needs_input` or `idle` state and any observed `ended_at` or `finished_at`. Its identity must match the case. |
| `producer_facts` | The semantic facts available then, in the runtime fact format. Every fact must name that same session and carry a positive timestamp no later than `captured_at`. An empty list is valid and stays empty. |

The marking screen shows the frozen producer ledger, recorded lifecycle and both yardstick
strings before asking for a mark. Optional `title` and `asked_for` fields add review context;
legacy collector counts and output-question flags are not needed. Excerpts and later reviewer
context may live in the packet for review, but only `producer_facts` enters the producer.

Keep each packet in its own directory under `~/.compass`, with the standard case and marks
filenames, and set `COMPASS_HOME` to that directory for both scripts. Run the scorer's
`--report` first: it checks every snapshot and lists the recorded lifecycle without spending.
Then run the marking script interactively. It writes a `cases_digest` alongside the marks and
refuses to reuse an existing key if the packet changed. Finally, the scorer's `--score` uses those
bound marks. `--out` selects the summary path; local results stay beside the cases. The rubric
file can live there too, or be selected with `--rubric`.

Malformed snapshots stop the whole run before any model call or result write. There is no live
fallback, including when snapshots have the wrong format version. Replay passes `captured_at`
as the producer's clock, so a settling end does not become settled just because the check runs
later. An idle row without an observed session end remains withheld. Do not invent an end or
change a quiet row to working to make it qualify. The normal evidence and eligibility rules,
coverage floor still apply to scoring. Enablement follows the amended ruling linked above.

## Case format 5: a per-case intent and frozen checks

Format 5 (`v: 5`) is what DRC-4666 scores the Claude Code producer against. It has no shared
yardstick. Each case carries every format 4 field, plus:

| Field | Meaning |
|---|---|
| `intent` | `goal` and `lines`, one to six `{text, source}` outcome lines, as a reader would save them. Each line is its own constraint, `line_1` onwards, marked and scored on its own. An optional `at` stamps when the intent counts as typed, and `window_start` opens the evidence window as a stored revision's would; without them the intent counts as typed at 1.0, before every session end. |
| `tool_output` | Claude Code only: `tails`, each check's redacted output tail by call id; `changed_after`, the `[call id, check line]` pairs a later command may have changed; and `read_incomplete`, the pairs whose pass was called before the bounded work record's read horizon. Each is frozen as a press read it at `captured_at`. An older packet with no `read_incomplete` field reads as an empty list. |
| `transcript_bytes` | Claude Code only: the transcript's length in bytes as it stood at `captured_at`: everything before the first line stamped after it, the cut the check scan makes. The score-time check reads the board's tail of the file as it stood then. A case whose `transcript_cut` is `capture` must still name exactly that length (`transcript-bytes-differ`); an older packet recorded the file's length when frozen. |

Build a packet with `mark_abstention.py --freeze <spec>`. It spends nothing. The spec is a local
file listing, per case, the `harness`, `sid`, `project`, `captured_at`, the `row` lifecycle
(`state`, `finished_at`, `ended_at`), the `intent`, and for Claude Code optionally the
`transcript` path. The freeze reads the session's facts from the board and keeps only those dated at
or before `captured_at`. A Claude Code case's user messages come instead from the transcript as it
stood at `captured_at`, through the board's own derivation over the tail a press then read: read
from today's file, a session that ran on past the board's 400 KB tail after the capture left none
of the reader's words in the case. Each user message's fact carries `reader_words`, the whole message
on one line, redacted and cut at 1,000 characters, beside the one-sentence `summary`; the producer
sends the words where the prompt has room and the summary otherwise, and the score-time check
compares both
([the amendment](../design-reading-a-session.md#amended-2026-10-01-a-reading-sees-the-readers-whole-message)).
An older packet's facts lack `reader_words`, and the parser stamp below refuses it before that
matters.
It never keeps a board check: those are computed over the whole transcript,
so a later run would reach back into the moment. It rebuilds the checks and the press reads from
the transcript as it stood at `captured_at`. It refuses a capture taken before a recorded turn
stop or end had settled.

A frozen case is `recorded` only when the machine's own records vouch for it. Otherwise it is
`synthetic`: it is marked and scored, never counts toward the coverage floor, and the rubric's word
for it does not change that. `unconfirmed` lists why, as closed tokens:

- `transcript-outside-projects`: the Claude Code transcript is not under `~/.claude/projects`.
- `transcript-other-session`: its records do not all name this session id.
- `lifecycle-unconfirmed`: neither the dashboard's stores nor, for a rolled-past turn stop, the
  transcript vouch for the lifecycle the spec gives. A
  `working` row needs a history observation in `working` at `captured_at` itself. A turn stop needs
  an `idle` observation whose `last_activity` is the `finished_at`. An end needs the ends store's
  stamp. The freeze reads `compass-history.json` and `compass-ends.json` from `--store-home`,
  `~/.compass` by default, never from the packet's own directory. The history store is capped
  and rolls, so a Claude Code turn stop older than its oldest observation is vouched instead by the
  transcript's own top-level `stop_hook_summary` for that session at the `finished_at`, one whose
  hooks did not keep the turn going. The board stamps a hook's arrival about a tenth of a second
  after that record, so the spec's `finished_at` must be copied from the record itself. A stop the
  store still reaches never falls back. The case records which vouched for it in
  `lifecycle_from`: `history`, `transcript`, or null when neither did, and the scorer derives the
  same answer itself and counts it in the summary as `recorded_on_transcript_stop` ([DEC-17, amended 2026-10-01](../design-reading-a-session.md#amended-2026-10-01-a-readers-correction-and-a-transcript-stop)).

A Codex case is a recorded history `working` observation frozen at its last activity, because
Codex has no session-end hook and is never read at a turn stop.

The scorer repeats these checks at score time for every case the packet calls `recorded`, because
the packet is hand-editable: the transcript found for that sid under `~/.claude/projects`, its
session id, and the lifecycle in this machine's history and ends stores, or for a rolled-past
turn stop its transcript, refusing a stop or end that had not settled before `captured_at`
(`captured-before-settled`). For a Claude Code case it
also rebuilds the contents from that transcript as it stood at the case's `captured_at`, the same
derivation the freeze used, and compares them with the packet as the ledger rows the producer
reads (DRC-4711):

- `checks-differ`: the check facts are not exactly the transcript's. An invented, altered or
  dropped check all land here.
- `tool-output-differs`: `tool_output`, the tails, changed-after pairs and incomplete-read pairs,
  is not exactly what a press at `captured_at` read. An absent `read_incomplete` field in an older
  packet is compared as an empty list.
- `facts-unconfirmed`: the packet's user messages are not the newest ones the transcript holds up
  to `captured_at`, in order, with none missing between them and none repeated, or are fewer than
  the board's bounded tail reads of the file's first `transcript_bytes` bytes. An older message may
  be absent, because the board read a bounded tail when the packet was frozen, of a file no larger
  than that. The tail ends there rather than at today's end, so a session that ran on past the tail
  after the freeze cannot empty it. A case frozen at its capture names exactly the capture's
  length, and no case may name less (`transcript-bytes-differ`). A Claude Code case carries only
  its user messages and its checks. The board also publishes facts of other types for a Claude
  Code session, such as an observer snapshot, and a packet holding one lands here.
- `activity-after-stop`: the transcript holds a record stamped after the recorded stop or end and
  at or before `captured_at`. Moving the capture later would otherwise carry a later turn into a
  case vouched for at the stop. The freeze refuses the same capture with the same word.
- `transcript-truncated`: the transcript is now shorter than the case's `transcript_bytes`, or the
  case records no size. The file the case was frozen from is gone, so nothing is compared.
- `transcript-bytes-differ`: a case frozen at the capture's own length (`transcript_cut` is
  `capture`) names another. A shorter length would shrink the tail and excuse a dropped message.
- `frozen-on-another-parser`: the case's `parser` stamp, a sha256 over the syntax trees of
  `io.py`, `project_context.py` and `reading.py` written at freeze, does not match the scorer's. Every case would differ, so this is
  named on its own rather than read as tampering. Freeze again on the tree you score on, with the
  freeze board started from that same checkout, since the board derives the user messages.
  `--score` does not get this far: it compares every stamp with this checkout's before the ledger
  is opened, and refuses the whole run when any differs, since each such case would only be
  withheld while the rest were charged. It names the fix: check out the commit the packet was
  frozen on, or re-freeze from this checkout and mark the new packet. `--report` says the same at
  the preflight. A recorded Claude Code case with no `parser` stamp at all, reviewed exports
  included, is refused the same way, before the ledger; recorded Codex and synthetic cases may
  omit it.

Turns appended after `captured_at` are not a mismatch. A Codex case has no transcript this check
reads, and under the per-producer floor it is a control that never covers. A case that fails any of
them becomes `synthetic`, is withheld as `not-recorded` without a model call, and never meets the
floor, whatever the packet or the rubric says. A case the packet itself calls `synthetic` is
different: it is sent, charged and scored, so it can fail the run, and it never meets the floor. `--report` runs the same check and counts only the
cases it confirms.

The scorer passes each Claude Code case's frozen checks to the producer as a press with a
tool-output grant would, and reads a Claude Code turn stop as the route does. It refuses to start
when the destination for those checks cannot be named. The marker shows the intent, each line with
its source and the frozen ledger, every check with its result words and its output tail, and asks
the goal and then each line. Where the record holds no check or work result, the lines are fixed
at `abstain` without asking.

Scoring refuses before its first call unless every case in the packet is marked, each on exactly
its own constraints, with `judge` or `abstain` and nothing else. The authorization says every case
is marked before any reading runs. A Claude Code result is written only from a format 5 packet.
`--producer codex` may report but not score, because no Codex spend is authorized for this
qualification.

### Prospective production source inputs

The explicit `--production-reading` option on `--freeze` prepares a new typed-Claude packet
with parent-agent excerpts and exact production person and newest-final source bindings.
It leaves existing packets alone. The [source-cut exception](../../SECURITY.md#prospective-qualification-source-cuts-2026-10-05)
permits a temporary raw historical input copy; recovered whole reply fields remain in memory.
Packets and marker output retain metadata and bounded excerpts, rather than restored complete
replies. Source, selection or prompt changes refuse. Adopted goals and sourced outcome lines
are outside this initial protocol, and machine vouch supplies no model accuracy result.

The 2026-10-05 source preflight vouched five recorded cases and preserved five synthetic
adversaries, with 31 native questions. Independent review of that five-case recorded packet found
no established matching-intent-incorrect-execution or misleading-completion case. All five recorded newest-final
lookups were unproven. That draft remains blocked before spending: it needs genuine source
proof for those kinds, fresh independent marks and rubric review. Mechanical recovery tests
do not establish complete-final empirical coverage or turn an earlier failure into a pass.

A model-free audit after the [source identity repair](https://github.com/spacedock-dev/compass/pull/504)
on 2026-10-06 recovered all five newest selected final replies from the exact bounded historical
cuts using their canonical filenames. All 53 selected identity and time joins matched. Four
prompts stayed unchanged because their excerpts were already whole; one restored a
2,479-character reply within the existing shares and cap. These checks establish source recovery
and allocation, not five changed prompts or model interventions. The earlier unproven report
and failed results remain historical records. They supply no semantic-kind admission or
accuracy result; genuine coverage, fresh marks and rubric review are still required before
qualification.

Other supplied corpus recordings may establish those genuine kinds. They still need reviewed
source admission and fresh independent marks; absence from the earlier packet does not mean
absence from the corpus.

### Fresh fourth qualification packet, 2026-10-06

The [fourth grant](claude-continuation-4.json) binds a new ten-case packet: five recorded cases
covering the five kinds, and five independently verified synthetic passing-check adversaries.
Fresh agent marks and rubric expectations cover all 34 questions before any producer output.
The cases, expectations and marker disagreements remain private. The earlier failed results
and their 28 charges remain unchanged.

The [shared campaign](../drift-replay/closure-campaign.json) runs qualification first with replay
and live slots held and unbound. It permits three ten-case passes and one registered retry,
31 additional attempts within the existing shared allowance. The native scorer ceiling is 59,
including the earlier 28. Each batch needs measured independent acceptance before the next;
a semantic or coverage failure stops the campaign. Preparation and activation establish no
producer PASS. The [shared guard](../drift-replay/README.md#the-shared-closure-guard) owns the
batch and stop contract.

### Fresh fifth qualification packet, 2026-10-07

The [fifth grant](claude-continuation-5.json) binds ten rebuilt production inputs after the
non-final scope clarification: five recorded cases covering the five kinds and five separately
verified synthetic adversaries. Fresh agent marks cover all 34 asked questions before output.
Independent contract review resolves canceled predicates without replacing the saved intent,
keeps earlier unshown claims separate from later shown checks, and permits attributed agent
accounts to support intent consistency. The source cases, expectations and disagreements stay
private; none of these preparation checks supplies an accuracy result.

The [fresh manifest](../drift-replay/closure-campaign-successor.json) and
[reviewed handoff](../drift-replay/closure-successor-handoff.json) preserve the stopped original
two shared charges and thirty native charges. The new epoch registers batches of one, nine,
ten and ten exposures on the bound Sonnet 5.5/high producer. Each batch needs measured independent
acceptance before the next. Thirty registered exposures and one availability retry fit the
fresh 31-attempt allowance and the native ceiling of 61. Replay and live remain held. Every
earlier failure and charge stays unchanged; this authority does not qualify the producer.

### Fifth qualification outcome, 2026-10-07

The [fifth result](claude-results-continuation-5.json) is blocked after its opening attempt and
one explicit availability retry both returned `model-failed`. Both attempts remain charged.
Neither produced a parsed answer: all three questions at that opening were withheld in both
attempts. This supplies no accuracy judgement, and the recorded failure does not identify quota,
authentication or model availability as its cause. The runner used for those attempts discarded stderr.

The two consecutive unusable attempts stop the successor campaign before any later case.
The fresh allowance has spent two of 31 attempts, with 29 held and the sole retry exhausted.
The native ledger preserves 32 charges, including its earlier thirty. The original stopped shared
epoch keeps its two charges, and the successor keeps its separate two. No opening batch has been
accepted; replay and live remain held. Resuming requires a diagnosed transport and separately
authorized, reviewed continuation authority. No failed attempt or frozen answer key is rewritten.

### Login-repaired qualification continuation, 2026-10-07

The owner reported that Claude Code had been logged out and that sign-in was repaired. They
approved another bounded qualification using the 29 unused attempts plus two additional
attempts. The [login recovery contract](../../SECURITY.md#login-repaired-qualification-continuation-2026-10-07)
preserves all earlier failures and charges. Its 31 available attempts cover thirty registered
readings and one retry; the opening diagnostic is the first registered reading, not an extra
call. The native ceiling is 63. Replay and live stay held.

The [sixth grant](claude-continuation-6.json),
[manifest](../drift-replay/closure-campaign-login-resume.json) and
[independent handoff](../drift-replay/closure-login-resume-handoff.json) bind the continuation.
The [mark transfer](claude-marks-transfer-6.json) records ten byte-identical prompts, 34 unchanged
blind expectations and 81 unchanged citation joins. Seven source receipts rebind only the
intake-code digest. Both earlier stopped epochs and all source material remain unchanged.

Qualification now retains private execution diagnostics tied to each charged attempt. They
identify a nonzero exit, timeout or other closed failure category without retaining raw error
text. A bounded CLI-text match supplies a hint, not a proven cause. These receipts do not
supply an accuracy verdict. Reusing blind marks requires independently verified identical
reading material, an explicit transfer binding and fresh source/scorer admission; earlier
packets and keys remain unchanged.

### Sixth qualification outcome, 2026-10-07

The [sixth result](claude-results-continuation-6.json) contains two parsed readings. Both Claude
Code calls exited successfully after login repair; no attempt was unusable and no retry was
used. The opening batch was independently accepted. The next case failed the frozen abstention
check, so the campaign stopped before another call.

Across seven scored questions, four were correct, none falsely reassured, one missed a departure
and two over-abstained against the rubric. On the failed case, Goal did not identify an earlier
stalled promise. The first outcome line was judged `not-reached` although its condition was
unverifiable; the second line abstained although the frozen expectation was `consistent`. The
rubric counts both line errors as over-abstention. These are different from the previous run's
execution failures: the answers arrived, but qualification failed.

Only two recorded case kinds reached the model. All five recorded kinds were admitted before
the run, but the other eight first-pass cases and every second and third reading remain
unattempted. This partial result establishes no full-packet accuracy or repeatability claim.

The new allowance spent two of 31 attempts, with 29 unused and held. The native ledger retains
34 of 63 charges; the shared ledger retains the original two charges, the first successor's
two and this continuation's two, six in total. Replay and live remain held. No earlier failure,
charge or blind mark was changed. The owner's operational acceptance remains separate from this
failed qualification. Further work must investigate how non-final readings handle unknown
conditions and earlier stalls within the 9,216-byte instruction limit; this result supplies no
measured improvement from a future fix.

### Seventh qualification preparation, 2026-10-07

The owner authorized measuring the corrected per-clause instruction after the sixth result
failed. The [finite continuation contract](../../SECURITY.md#per-clause-qualification-continuation-2026-10-07)
keeps all 34 native charges and six shared charges, carries 29 held attempts and adds two.
Thirty registered readings and one availability retry fit its 31-attempt allowance. Earlier
stops remain intact, and a semantic failure cannot use the retry.
The [seventh grant](claude-continuation-7.json),
[reviewed mark transfer](claude-marks-transfer-7.json),
[manifest](../drift-replay/closure-campaign-clause-continuation.json) and
[independent handoff](../drift-replay/closure-clause-continuation-handoff.json) bind the new
packet and zero-charge activation. Preparation itself supplies no qualification result.
The [zero-charge scope correction](../drift-replay/closure-clause-zero-reseal.json) preserves
the initial preparation and binds its corrected replacement before any reading. The reseal
changed no charge or allowance.

The correction preserves all existing departure grounds before considering unknown scope or
conditions and unfinished work. It leaves final-session instructions unchanged. Every input
must be rebuilt from the final source and frozen before output.
Unchanged evidence, criteria and reading scope may carry their independently reviewed blind
expectations forward through an explicit transfer; changed material needs fresh adjudication.
Replay and live remain held, with no refund or borrowed allowance.

### Seventh qualification outcome, 2026-10-07

The [seventh result](claude-results-continuation-7.json) failed after two parsed Sonnet 5.5/high
readings. Both calls exited successfully. The opening was independently accepted under the
registered stop criteria, with its rubric errors retained. The nine-case batch then stopped
after its first reading: an outcome marked should-abstain was judged `departure` although its
approval-qualified scope was not established. No further call or retry followed.

The frozen rubric scores three of seven questions correct, two false alarms and two
over-abstentions, with no false reassurance or missed departure. Both Goal departures were
identified. A Goal departure did not establish the approval-qualified outcome, and a separate
repaired outcome still received no judgment. The first case's attribution line also has a scope
ambiguity between the latest report and a persisted artifact. Its frozen count is preserved;
the separate approval-qualified line independently fails the abstention check. A future packet
must clarify that attribution scope and adjudicate the changed criterion before output.

Only two of the five admitted recorded kinds reached the model. Eight first-pass cases and
every second and third reading were unattempted. This is no full-packet accuracy or
repeatability result. The native ledger holds 36 of 65 charges, and the shared ledger holds
eight. Two of 31 fresh attempts were spent; 29 remain held, and the unused availability retry
cannot cross the semantic stop. Earlier results, source packets, marks and charges remain
unchanged. The replay ledger remains 631 of 870, with replay and live allowances held.

Further work must separate each whole clause's evidence and judgment, and read supported
repairs separately from an earlier Goal departure. Any change needs a new source-bound packet,
pre-output adjudication and finite continuation; the failed run cannot be resumed or regraded.

### Eighth qualification preparation, 2026-10-07

The owner approved 29 carried attempts plus two renewed attempts for thirty fresh readings
and one availability retry. The [finite contract](../../SECURITY.md#clause-isolation-qualification-continuation-2026-10-07)
preserves all 36 native charges and eight shared charges. The
[eighth grant](claude-continuation-8.json), [mark transfer](claude-marks-transfer-8.json),
[manifest](../drift-replay/closure-campaign-clause-isolation.json) and
[independent handoff](../drift-replay/closure-clause-isolation-handoff.json) bind the new packet.
The batches remain one, nine, ten and ten, each reviewed before the next. Replay and live stay held.

Each whole clause now requires its own supporting evidence. The ambiguous attribution question
expressly concerns the latest response and has two fresh blind marks. The other 33 expectations
transfer after source, scope and selection checks. Earlier results and keys are unchanged;
preparation and construction checks establish no accuracy pass. The original transition and
zero-charge reseal remain immutable. Only a new fourth epoch may be initialized, after full
local checks; merged code and current-head CI precede every reading.

### Eighth qualification outcome, 2026-10-07

The [eighth result](claude-results-continuation-8.json) failed after two parsed Sonnet 5.5/high
readings. The opening identified the Goal departure and judged the freshly scoped latest
response consistent; claims over-abstention remains reported. Independent review accepted
that opening under the existing safety rule. The next nine-call batch stopped after its first
reading: an approval-qualified outcome was judged departure without evidence establishing
that approval scope. Both CLI calls succeeded. This is an assessment error, not a sign-in or
availability failure.

Across seven questions, four were correct, one was a false alarm and two over-abstained.
There was no false reassurance or missed departure. Both Goal departures were identified;
the conditional outcome still failed the abstention guard. No subsequent call or retry ran.
Eight first-pass cases and all twenty repeated readings remain unattempted. Only two of the
five admitted recorded kinds reached the model; this is no full-packet or repeatability pass.

Two of 31 fresh attempts are spent and 29 remain held. The unused availability retry cannot
cross the semantic stop. The native ledger preserves 38 charges and the shared ledger ten;
every earlier packet, key, result, stop and the accepted opening remains intact. Replay stays
at 631 of 870, with replay and live allowances held. The producer remains unqualified, and the
Claude-only browser verification cannot be armed. A further correction needs new source-bound
expectations and finite measurement authority; this failed run cannot resume or be regraded.

### Ninth qualification measurement preparation, 2026-10-07

The owner authorized carrying 29 unused attempts and adding two, giving 31 available
for thirty fresh readings and at most one availability retry. The owner also removed
the requirement to stop at the first failing semantic batch. This generation records
wrong answers and continues its registered measurement. Independent batch reviews say
`measured`, with their actual failure counts. They cannot qualify a failed result.
Technical protection, source, coverage and account failures still block launches.

The corrected framing checks unknown prerequisites before carrying a departure judgment
forward. All 34 criterion scopes and expectations remain unchanged from the eighth packet.
Independent source reconstruction verifies ten cases, 81 citation joins and seven freshly
derived export receipts. Each actual input adds four framing bytes; its source records,
selected evidence and question inventory stay unchanged. These are construction and
admission checks, not evidence of improved model accuracy.

The [ninth grant](claude-continuation-9.json), [expectation transfer](claude-marks-transfer-9.json),
[fixed manifest](../drift-replay/closure-campaign-conditional-priority.json) and
[independent handoff](../drift-replay/closure-conditional-priority-handoff.json) bind the new
source and the complete paid history. Native and shared ceilings are 69 and 249, with
38 native and ten shared charges retained. Replay's 190 and live's 18 attempts remain held.
Only a new ordinary fifth epoch may be initialized after the complete local checks.
Merged software and passing current-head CI precede model calls. A Claude-only browser
reading requires an actual full passing qualification and separate bound route admission.

### Ninth qualification outcome, 2026-10-07

The [ninth result](claude-results-continuation-9.json) completed all thirty registered
Sonnet 5.5/high readings: ten cases read three times, with all five recorded kinds
represented in each repeat. Twenty-three readings were usable and seven failed the
semantic check. No attempt was unusable and no availability retry ran. The run continued
after wrong answers as authorized; its final verdict is `failed`, with `stopped: false`.
Completing measurement does not qualify the producer.

Across 102 scored questions, 73 were correct, four were false reassurances, one was a
false alarm, one missed a departure and 23 over-abstained. No question was unscored.
The repeat counts remain separate in the result:

| Repeat | Correct | False reassurance | False alarm | Missed departure | Over-abstention |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 25 | 1 | 0 | 0 | 8 |
| 2 | 24 | 2 | 1 | 0 | 7 |
| 3 | 24 | 1 | 0 | 1 | 8 |

The conditional approval outcome was judged without established approval scope in all
three repeats, and a compound check requirement received false reassurance in all three.
One unrelated-outcome control also failed in the second repeat. A `not_reached` answer
on a should-abstain mark remains a judged failure even when the rubric calls it
over-abstention. These observations establish errors on this frozen packet, not their
cause or a general accuracy gain. No expectation was changed after output.

Thirty of the 31 available attempts are spent. The native ledger preserves 68 charges
under its 69-call ceiling, and the shared account preserves 40 across the original and
five successor epochs. The unused availability retry remains held; it cannot rerun a
semantic failure or fund another lane. Replay remains at 631 of 870, and the 190 replay
and 18 live attempts remain held. Every earlier packet, key, result, stop and accepted
opening stays intact, as does the owner's separate 2026-10-02 operational acceptance.
There is no passing qualification or qualification acceptance, and the guarded
Claude-only browser reading cannot be armed.

### Tenth qualification preparation, 2026-10-30

The packet is prepared and sealed (see the next section), and its run failed (see the [outcome](#tenth-qualification-outcome-2026-10-30)). The owner funded one tenth continuation of
31 calls on 2026-10-30: thirty registered Sonnet 5.5/high readings and one availability
retry. If it fails, one corrected retry run of at most 31 more calls follows, and then the
study stops. Every earlier failure and charge stays as it is.

What the software now admits, and nothing more:

- **Grant 10** (`claude-continuation-10.json`) carries a `tenth_continuation_allowance`: 68
  previous calls, one carried (the ninth's unused retry), thirty renewed, 31 additional,
  three repeats and one retry, with its model and campaign bindings. It binds result 9,
  which must read `failed`, `stopped: false`, 30 attempts and none unusable.
- **Epoch six** (`TenthCampaign` in `scripts/analyze_campaign.py`) reads its manifest from
  `docs/drift-replay/closure-campaign-tenth.json` and its handoff from
  `docs/drift-replay/closure-tenth-handoff.json`. The handoff binds epoch five's thirty
  measured calls, its four batch reviews, result 9, the four earlier epochs and the native
  68-call prefix. The ceilings are 99 native and 279 shared, and the scorer admits
  `--max-calls 99` and refuses 100. The ninth's measurement rule holds: all thirty are
  measured, and a semantic failure waits for its batch review.
- **Grant 11, the retry** (`claude-continuation-11.json`), carries a
  `retry_continuation_allowance`, and only after result 10 reads `failed` with an attempt
  count equal to what the tenth charged. With P native charges at result 10 (69 to 99): P
  previous calls, 99 - P carried, P - 68 renewed, 31 additional. **Epoch seven**
  (`RetryCampaign`, `closure-campaign-retry.json`, `closure-retry-handoff.json`) has
  ceilings of P + 31 native, at most 130, and 279 + (P - 68) shared, at most 310. If the
  tenth measures thirty and leaves its retry unused, P is 98: 129 native and 309 shared.
- **Each earlier generation is an ancestor.** The ninth and tenth classes select their own
  grant by number, so each still validates every receipt once a later grant is active. An
  older key keeps reporting its own cap and cannot charge. A grant that carries no allowance
  after one that did admits no charge, even through a ledger built under the grant before it.
- **Receipts name their model.** A tenth or retry handoff carries `receipts` for `marking`,
  `kind_review` and `handoff_review`, and every batch review carries `review`, each
  `{"model", "effort"}`: `gemini-3.8-flash-medium` with `medium`, or `gemini-3.8-flash-high`
  with `high` (AGENTS.md, "Models for qualification review and marking"). Anything else is
  refused.
- **A committed packet can vouch its own stop.** `mark_abstention.py --freeze --prior-packet
  <cases file>` re-freezes a case whose stop both history stores have rolled past, at the
  same recorded stop. The prior packet must be the one a sealed grant names by its case
  digest, with a committed result whose chain begins the spend ledger. The prior case must be
  recorded with nothing unconfirmed, at the same session, lifecycle and capture, and the
  transcript must hold the same bytes up to the capture by the prior packet's prefix digest.
  Anything else leaves the case synthetic. The case records `lifecycle_from: prior-packet`
  and a `prior_vouch` reference, the scorer rechecks both, and a result counts them as
  `recorded_on_prior_packet`. This is an orchestrator decision of 2026-10-30, which the owner
  may overrule. Measured read-only on 2026-10-30: the ninth packet's `a3c76f89` and
  `a3458822` have no observation in either store and their nearest Stop records are 100.15 s
  and 91.43 s from the stop (contract review), and both transcripts still match their prefix
  digests.

Planned order:

1. The producer guards land before the freeze, so the run measures the corrected reader.
2. A fresh packet home re-freezes every carried case on merged main, because the parser
   stamp has moved, with `--prior-packet` pointing at the ninth packet's cases file. The
   steer-then-explain two-turn case takes a slot only if an independent kind review, which
   sees no results, assigns it that slot's kind. Result 10 will then say which retired case
   was not re-measured.
3. Blind marks, kind review and the handoff review run before any output, on AGY Gemini
   (`gemini-3.8-flash-medium` or `-high`) under the
   [dated security amendment](../../SECURITY.md#tenth-qualification-continuation-2026-10-30).
   Unchanged expectations may transfer. Changed ones and the new case's questions are marked
   fresh.
4. Grant 10 is committed in `marking`, then `sealed` with its allowance. The allowance's
   campaign binding covers the manifest, which carries the marks digest, so it is added at
   sealing, and the handoff is computed after that. The manifest, the handoff and epoch six's zero-charge activation
   follow. Batches stay one, nine, ten and ten, each reviewed before the next.
5. The run happens from a pinned checkout with `--max-calls 99`. Its result is recorded in its
   own section here.

### Tenth qualification packet, 2026-10-30

Steps 1 to 4 are done, with no Claude or Codex model call. The [tenth grant](claude-continuation-10.json)
is sealed, the [fixed manifest](../drift-replay/closure-campaign-tenth.json) is sealed with its
activation anchor, the [handoff](../drift-replay/closure-tenth-handoff.json) passed its independent
review, and epoch six holds zero charges. The native ledger is unchanged at 68.

The packet was re-frozen on the producer-guards tree. Five recorded cases cover the five kinds and
five authored synthetic adversaries are rebuilt from their reviewed source. The ninth's
`a3458822654ec47a` is vouched by the ninth packet at its recorded stop, as the prior-packet rule allows.
The steer-then-explain two-turn case `19f966db1f403710` is frozen at its second turn stop with both
turns, and its lifecycle is vouched by that stop's own transcript record. An independent AGY kind review
(`gemini-3.8-flash-high`, effort `high`) was shown the case's record and the five kind definitions and no
model output or result. It assigned `legitimate-change`, with `supported-departure` second. The case
therefore takes the legitimate-change slot. **The ninth's legitimate-change case `a3c76f898154b2fa` was
retired by that review and is not re-measured.** Its compound line about how a check ran, which failed in
all three ninth repeats, is not asked in the tenth. Result 10 must say so. `8b8c1a02f6376201` keeps the
supported-departure slot.

All 32 questions were marked fresh and blind under the current rulings, including the 2026-10-30 ruling on
a line about how a check ran. Two AGY markers (`gemini-3.8-flash-high`, `high`) agreed on 24, and an AGY
arbiter on the same model settled the other 8. No expectation transfers. The
[marks record](claude-marks-transfer-10.json) compares the sealed marks with the ninth's after sealing.
Six expectations moved: two judge-to-abstain on `a3458822654ec47a`, one on a claims question, two
consistent-to-departure on `f25545d5bf50515f` and one abstain-to-judge on an adversary's Goal.

A model-free dry pass ran the frozen packet through the real scorer path with fake models. An
all-`unverifiable` reply leaves all ten cases usable, so no DEC-17 failure is built into the code, and an
all-`consistent` reply fails all ten. A reply equal to the rubric scores 32 of 32 correct, so every
expectation can be reached through the resolver. These are construction checks, not a measurement. With
every charge and write fenced, the scorer admits `--max-calls 99`, passes every pre-call refusal, stops at
the first slot, and refuses 100.

The model binding pins Claude Code 2.1.314, Sonnet 5.5 at high effort. The run must use that installed
version, from a checkout whose runtime, scorer and parser files match the manifest's evidence.

### Tenth qualification outcome, 2026-10-30

The [tenth result](claude-results-continuation-10.json) completed all thirty registered
Sonnet 5.5/high readings on Claude Code 2.1.314, ten cases read three times, with all five
recorded kinds represented in each repeat. Twenty-five readings were usable and five failed
the semantic check. No attempt was unusable and no availability retry ran. The run continued
after wrong answers as authorized; its final verdict is `failed`, with `stopped: false`.
Completing measurement does not qualify the producer.

**The ninth's legitimate-change case `a3c76f898154b2fa` was retired by the independent kind
review and was not re-measured.** Its compound line about how a check ran, which failed in all
three ninth repeats, was not asked. The steer-then-explain case `19f966db1f403710` was measured
in the legitimate-change slot in its place.

Across 96 scored questions, 68 were correct, two were false reassurances, two were false
alarms, eight missed a departure and 16 over-abstained. No question was unscored. The repeat
counts remain separate in the result:

| Repeat | Correct | False reassurance | False alarm | Missed departure | Over-abstention | Semantic failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 24 | 0 | 0 | 3 | 5 | 0 |
| 2 | 22 | 1 | 1 | 2 | 6 | 3 |
| 3 | 22 | 1 | 1 | 3 | 5 | 2 |

The first repeat alone had no semantic failure; the second and third did, so the aggregate
fails. The five failed readings:

- `8b8c1a02f6376201` (supported departure), second and third repeats: an outcome line marked
  should-abstain was judged a departure.
- `19f966db1f403710` (legitimate change), second repeat: the outcome line marked as a departure
  was judged consistent, a false reassurance.
- `6182bf4aef61276f` (matching intent, incorrect execution), second repeat: the claims question
  marked should-abstain was judged unsupported.
- `d92bebe67b5b6f4c` (a partial-check adversary), third repeat: its Goal, marked should-abstain,
  was judged consistent, a false reassurance.

Recurring over-abstention, which does not fail a reading on its own, is concentrated in three
cases. `f25545d5bf50515f` abstained on its Goal, its outcome line and claims in all three
repeats, missing both departures every time. `19f966db1f403710` abstained on its Goal and claims
in all three and missed its outcome line's departure in two. `957ba71d1fa91f7e`'s Goal and
`8b8c1a02f6376201`'s second line abstained in all three where consistent was expected. These
observations establish errors on this frozen packet, not their cause. No expectation was
changed after output.

Each batch (one, nine, ten and ten) was reviewed before the next by an independent AGY reviewer,
`gemini-3.8-flash-high` at effort `high`, shown the batch's charge receipts, statuses and counts,
the reader's parsed answers and rubric grades, and the frozen case material they cite. All four
returned GO with no finding, and each receipt names that model and effort. A review records
measurement, never a pass.

The result's `recorded_on_transcript_stop` and `recorded_on_prior_packet` counts read 0 in every
repeat, although `8b8c1a02f6376201` and `19f966db1f403710` are vouched by their transcript stops
and `a3458822654ec47a` by the ninth packet. The repeated-qualification summary does not pass the
vouched-stop sets that the single-pass summary does. That is a reporting gap in the result, not a
change to any case's vouch, which the scorer checked before each charge. The scorer now passes them
to each repeat ([DEC-17, amended 2026-10-30](../design-reading-a-session.md#amended-2026-10-30-owner-a-verdict-on-words-alone-gives-way-to-the-record)),
and result 10 stays as committed.

Thirty of the tenth's 31 attempts are spent. The native ledger holds 98 charges under its 99-call
ceiling and the shared account 70 across the original and six successor epochs. The unused
availability retry carries to the one funded retry run: with P = 98, grant 11 would carry one and
renew thirty, for ceilings of 129 native and 309 shared. That run needs its own grant, handoff
and epoch seven, and then the study stops. Replay remains at 631 of 870, and the 190 replay and
18 live attempts remain held. Every earlier packet, key, result and charge stays intact, as does
the owner's separate 2026-10-02 operational acceptance.

### Fourth qualification outcome, 2026-10-06

The [native fourth result](claude-results-continuation-4.json) failed after two attempts on the
bound Sonnet 5.5 producer. The one-call opening batch passed independent review. The next batch
stopped on its first case: a question marked should-abstain returned `judged:not-reached`.
That is a judged should-abstain failure under the existing check, even though the rubric calls
it over-abstention. It is not a false `consistent` reassurance.

Seven questions were scored across two recorded cases. The rubric reports three correct results,
one missed departure and three over-abstentions, with no false reassurance or unscored question.
Eight cases in the first pass and both later passes were never attempted. The source packet had
already admitted all five recorded kinds; incomplete scored coverage does not mean the supplied
corpus lacked those kinds.

The native ledger now holds 30 charges, including the unchanged earlier 28. The shared campaign
holds two new charges and persistently refuses another launch. Its 29 remaining qualification
attempts and the other lane allowances stay held. No retry, mark revision, batch acceptance or
new campaign was used to turn this failure into a pass. A fresh qualification needs a separately
reviewed continuation that preserves every charge and failure; the remaining 29 cannot fund
another complete three-pass, ten-case run.

### Explicit reviewed exports, 2026-10-06

An owner-reviewed Claude Code export can be frozen outside the canonical projects directory
with `--freeze SPEC --production-reading --reviewed-exports MANIFEST
--reviewed-exports-sha256 SHA256`. Scoring and reporting need that same explicit pair. A case's
receipt cannot supply its own source path or approval. The [reviewed export contract](../../SECURITY.md#reviewed-native-export-intake-2026-10-06)
owns the trust boundary and accepted local-owner exposure.

The private manifest is a JSON object with exactly `v`, `review` and `exports`. `v` is `1`;
`review` has exactly `approved: true`, a nonempty `by` of at most 128 characters and a positive
epoch `at`. These record a review rather than authenticate one. `exports` holds one to 32
objects, each with exactly `path`, `sid` and `sha256`: a canonical absolute regular-file path,
its full lowercase UUID, and its complete-file SHA256. The basename is that UUID plus `.jsonl`.
Duplicate paths or eight-character identity collisions refuse. The separately supplied manifest
SHA256 binds its exact bytes; neither flag may be supplied alone.
Claude case specs use the existing eight-character lowercase hexadecimal `sid`. A full-UUID
alias or malformed id refuses before any board, history or canonical fallback, even in a mixed
spec. The manifest binds the full UUID; the importer does not silently normalize a case alias.

The fresh spec uses the existing typed intent and capture fields, with an idle row whose
`finished_at` exactly equals a native Stop timestamp. The configured settle interval must have
elapsed. The native Stop must join the preceding top-level assistant `end_turn` to an earlier
human request in physically prior UUID ancestry, with no intervening continuation through the
captured prefix. Metadata timestamp skew is allowed; each parent must precede its child in the
file, rather than on the wall clock. Both the final and human ancestor must yield native text
events. Native eligibility does not force the ancestor into the selected prompt or guarantee
whole final-word allocation. The native newline-only parser refuses literal carriage returns
inside a record or between JSON objects on one line. CRLF terminators and escaped JSON carriage
returns remain valid. This initial route
accepts a missing hook label as `Stop`, refuses other labels, and supports only a false
`preventedContinuation` value. True is an unsupported variant, not a claim that continuation
occurred. Existing canonical Stop handling is unchanged.

The freezer rebuilds admitted export facts using the native helpers and does not ask the live
board for them. It stores `reviewed_export` metadata outside `production_reading`, including the
manifest, source, prefix, case and code digests and exact native joins. Freezing, native source
callbacks, scorer reporting and scoring reverify the same resolver; the final precharge check also rechecks the
current marking and scoring scripts. Complete-file changes, including later appends, refuse.
Interactive blind marking reads the frozen packet and has no resolver flags or source reselection.
All existing source, check, tail, word-share and prompt caps still apply. No new stdout fact or
complete reply field is introduced. An old case without this receipt keeps its original
provenance and does not become recorded merely because its short id matches the manifest.

An eligible import still needs independent genuine-kind review, blind marks, rubric admission
and the registered campaign's guards before scoring. Source eligibility does not establish
that the facts needed to judge the case survived native publication, citation, selection and
the final prompt. Historical failures and packets remain unchanged.

### The spend ledger

Every model call is charged, before it runs, to one ledger at a fixed path,
`~/.cargento/drc-4666-spend.json`. That is the study's own home, where every ledger and packet of
this check was written, and it stays there after the rename
([study home ruling](../../SECURITY.md#tenth-qualification-continuation-2026-10-30)). It is shared by every producer and every packet directory, and
it never follows `COMPASS_HOME`, so a fresh packet directory does not start the count again. Its
`~`, like every other path this check trusts (the installed CLI, `~/.claude/projects`, the
dashboard's stores), is the account's home from the password database, never `HOME`, and
`--score` refuses to run while `HOME` names another directory. It
holds case ids, times, statuses and two digests per call: the marks file's and the cases and
rubric's. It stops the run at 28 calls across every run: the ceiling of 23 the owner approved in
DRC-4758, and the five more the owner authorized on 2026-10-01 for one more qualification run,
beside 31 Claude CLI invocations overall, the browser walk after a pass among them. `--max-calls`
can lower that and never raise it. A
case the cap stopped is withheld as `spend-cap`.

- The cap check and the charge happen under an exclusive lock, so concurrent runs cannot pass it.
- A missing ledger is an empty one. A ledger that cannot be read, or holds anything but this
  script's own shape, refuses every call and is left as it is.
- Once a call is charged, that packet's key is frozen. `mark_abstention.py` refuses to write marks
  or `--reset`, and `--score` refuses a packet whose marks or cases hash differently from the calls
  already charged. A mark written after an output was seen is agreement, not a mark.
- The committed result records `ledger_chain`: the first charge id, the number of calls and a hash
  chain over each charge's id and the two digests it was charged under. A later `--score` refuses
  while the ledger does not begin with that chain, reading the result at
  `docs/abstention/claude-results.json` as well as any `--out`, and refuses a committed result
  with no chain at all. Deleting, replacing or rewriting the ledger therefore does not unfreeze the
  key, and once a result is committed that packet's marks stay frozen.
- `--report` flags a result as stale when the ledger holds a call charged under unapproved digests,
  or no longer begins with the result's chain.
- `--resume` re-reads the local results and re-calls only the cases whose call failed
  (`withheld:model-failed`). It carries the other records over only when they hash to what the
  ledger recorded as the last run, so a hand-edited outcome is refused.

After a failed qualification, a fresh packet needs a reviewed continuation grant at the fixed
repository path `docs/abstention/claude-continuation.json`. Prepare it during that review.
Its first, `marking` phase binds the old failed result's chain and digests and the new cases file's
digest. `mark_abstention.py --continue-mark` then permits marking only that case set in a fresh
`COMPASS_HOME`, while the account-home ledger contains exactly the old committed charges. It
cannot reset, build or freeze, and ordinary marking remains closed. After every mark and rubric
expectation has been reviewed and the marker has exited, the `sealed` phase also binds the new
marks and combined cases-and-rubric digests. The scorer checks those values under the ledger lock
before each charge. The grant and failed result must be bounded regular repository files, not
symlinks, so the new result cannot replace what the old fixed path reads. The old charges remain
the prefix. New charges may use only the sealed key, and both count toward the same 28-call cap.
Grant k, for k of 2 or more, at `docs/abstention/claude-continuation-<k>.json` binds continuation k-1's failed result
the same way: the second binds `claude-results-continuation.json`, the third
`claude-results-continuation-2.json`. It is honoured only while every earlier grant is sealed and
each grant's `next` key is the following grant's `previous`. A grant file whose predecessor is
missing is refused, and so is one numbered past eleven, the fixed bound on the chain, or any
`claude-continuation*.json` the pattern never writes (`-0`, `-1`, `-02`). Each earlier
packet's charges must then carry that packet's own key, in ledger order, and a call is charged only
under the last grant's sealed key.
A grant does not authorize sending real session evidence to a provider or
raising that cap. Those require separate owner authorization.

The authorized closure follow-up has a separate, conditional allowance of 31 new qualification
attempts, included in the [shared 239-attempt allowance](../../SECURITY.md#shared-closure-allowance-2026-10-05).
Only a reviewed fourth continuation grant with a sealed fresh packet, actual model binding and
shared campaign binding can admit the resulting 59-call ceiling. Older packet keys retain the
28-call ceiling. The new packet requires ten distinct cases: five independently vouched
recorded kinds and five separately verified passing-check adversaries. Three complete native
repetitions must pass; one registered availability retry remains visible and charged.
Machine vouch establishes provenance, not semantic coverage. Missing source evidence blocks
qualification even when allowance remains. No grant or passing result is supplied by this
conditional implementation, and the earlier failed results remain unchanged.

The owner authorized a fresh 31-attempt continuation after the fourth grant's run failed at
30 cumulative native charges. The
[successor security contract](../../SECURITY.md#charge-preserving-qualification-successor-2026-10-06)
admits a separately bound fifth grant with a 61-call ceiling for its new key, preserving earlier
28/59 ceilings, every failure and every charge. A fresh shared epoch needs its own source,
prompt, asked-question, marks, model and acceptance bindings; the stopped run supplies no
opening-batch acceptance. Its unused 29 attempts are not additional allowance. The three-pass
ten-case qualification and charged retry rules remain unchanged. Installing the software
supplies no packet, activation or passing result. The
[fifth packet](#fresh-fifth-qualification-packet-2026-10-07) records its separately bound authority.

The failed `docs/abstention/claude-results.json` remains fixed. A continuation writes its summary
only to `docs/abstention/claude-results-continuation.json` and its local results to
`abstention-claude-continuation-results.json` in the fresh packet home. Under grant k the packet
writes `docs/abstention/claude-results-continuation-<k>.json` and
`abstention-claude-continuation-<k>-results.json` instead (the third grant's are
`claude-results-continuation-3.json` and `abstention-claude-continuation-3-results.json`), and
every earlier result stays fixed.
Scoring checks every fixed summary chain the grants run through, and reports accept each earlier
packet's charges followed by only the granted new-key suffix. Deleting or rewriting any packet's
ledger charges makes the affected result stale. A later packet cannot reset the spend or
reinterpret a failed verdict, and a fresh `--score` never replaces a written result that charged
calls; only `--resume` rewrites one, re-calling the calls that failed.

`--probe-argv` is the one way to watch what the CLI sends without spending. It starts its own stub
on `127.0.0.1` and runs the verified CLI twice with a fixed sentence: once signed in with a
placeholder API key, and once with a placeholder OAuth token and a placeholder account (a random
`@example.invalid` email and UUID) it writes into a config directory of its own. Every endpoint,
provider, credential, config-directory and proxy variable [SECURITY.md](../../SECURITY.md#the-abstention-check)
lists is removed, and the base URL points at the stub. It refuses to run when
`reading_route.destination` would name anything else, and refuses the answer unless it carries a
nonce only the stub knew, so a forwarding proxy or an operator's `ANTHROPIC_BASE_URL` cannot turn
it into a real call (DRC-4710). On Windows that route names nothing, so the probe always
refuses there before the CLI runs. Per pass it prints yes or no for: the argv carries
`--system-prompt`, the request carries the fixed sentence, and the request names the home
directory, the user name or the state directory. The OAuth pass adds whether the placeholder email
is in the disclosed block the CLI adds and whether the email or UUID appear anywhere else. It exits
0 only when the first two are yes and every leak is no, and it writes no result and charges
nothing. It says only what reached its stub; run it under an OS sandbox to know nothing else left.

Every mode that reads a packet, `mark_abstention.py`, its `--report` and `score_abstention.py`,
prints the packet's path and case count on its first line, in `~` form, and says so on the next
when `COMPASS_HOME` is unset and the default home was read. A report from the wrong home looks
like a finished key: check that line before posting one.

The marker also refuses a packet this version of the scripts cannot read, before it shows a case:
a case format other than 3, 4 or 5, or cases missing a field that `--build` (format 3) or
`--freeze` (format 5) writes. Format 5 Claude Code cases also need `tool_output`,
`transcript_bytes` and `parser`. The usual cause is a checkout older or newer than the one that froze
the packet, and the message says to `git pull`. If the checkout is already current, the packet is
older than the scripts and needs building or freezing again in a fresh `COMPASS_HOME`.

The owner's commands, in order. `COMPASS_HOME` holds the packet; the ledger does not move with it:

```bash
export COMPASS_HOME=~/.compass/abstention-claude-<date>
python3 scripts/score_abstention.py --probe-argv      # its own stub, spends nothing; expect exit 0
python3 scripts/mark_abstention.py --freeze "$COMPASS_HOME/freeze-spec.json"   # spends nothing
python3 scripts/score_abstention.py --report          # preflight, spends nothing
python3 scripts/mark_abstention.py                    # y/n/s/q per constraint, every case
python3 scripts/mark_abstention.py --report
# write the kind tags and one expectation per asked constraint into abstention-rubric.json now:
# changing the rubric after the first call changes the inputs digest and the ledger refuses it
python3 scripts/score_abstention.py --score --producer claude
python3 scripts/score_abstention.py --score --producer claude --resume   # only if a call failed
```

A packet after a failed result runs the same commands with three differences. The grant comes
first: commit its `marking` phase, naming the new cases file's digest, at the next free fixed path
(`claude-continuation.json`, then `claude-continuation-2.json`, then `claude-continuation-3.json`).
Marking uses
`mark_abstention.py --continue-mark`, because ordinary marking is closed once the ledger holds a
call. And before `--score`, commit the grant's `sealed` phase, naming the two digests the
scorer charges under: the marks file's, and the cases and rubric's together. No command prints
them; they are `marks_digest` and `_inputs_digest` in `scripts/score_abstention.py`, computed over
the packet as it will be scored.

## How to argue with a result

A case id is `sha256("<harness>|<sid>")[:16]`. Whoever holds the cases file can resolve it; nobody
else can, which is the point. The outcome per constraint is one of `withheld:<reason>`, `unparsed`,
`abstained`, `abstained:goal-unclear`, `judged:consistent`, `judged:departure`,
`judged:unsupported` or `judged:not-reached`. `withheld` means the producer refused before
the model ran, so the case says nothing about the model, and it is counted for neither side.
`abstained:goal-unclear` is the Goal row's "goal too vague to analyze against" (the
[2026-10-22 amendment](../design-reading-a-session.md#amended-2026-10-22-a-goal-alone-is-read-or-refused)).
It is an abstention, never a judgement. It reads the words, not the work, and the page draws no
departure, level or claim from it, so on an abstain mark it is correct and on a judge mark it is
held, as `abstained` is. The rubric grades it as the abstention the page renders. Before
2026-10-30 the scorer let it fall through to `judged:departure`; no committed result holds one.

The verdict is `failed` when a case marked should-abstain judged or the rubric records a false
reassurance (a mark of `abstain` on that line is not enough on its own), `blocked` when a rubric
entry left a required judgement unscored, `short` when no case failed but
fewer than one recorded case per DEC-15 kind reached the model on the harness of the producer
scored (on both Claude and Codex for a run that names no producer), `stale` when
the marks no longer hash to `marks_digest` or replay inputs no longer match `inputs_digest`, and
`passed` only when none of those hold.

Coverage is judged per producer, by the
[DEC-17 amendment of 2026-09-27](../design-reading-a-session.md#amended-2026-09-27-the-floor-is-judged-per-producer).
Each harness in `coverage` carries `kinds`, `role`, `missing` and `not_produced`. The producer's own
harness is `scored` and its absent kinds are `missing`, which reads `short`. The other harness is a
cross-harness `control`: its cases are scored and can fail the run, and its absent kinds are
`not_produced`, which never reads `short`. A run that names no producer marks both `required`. The
report
never prints one figure for the whole: false reassurance, false alarm, missed departure and
over-abstention are four counts, and citations hit, missed or extra are a fifth column beside them.

## The rubric expectation file, version 1

Kept beside the cases, never here. Its shape, so a case set can be written against it:

```json
{
  "v": 1,
  "cases": {
    "<case id>": {
      "kind": "supported-departure",
      "harness": "claude",
      "origin": "recorded",
      "expect": {
        "goal": {"result": "departure", "cites": ["<fact id>"]}
      }
    },
    "<synthesised id>": {
      "kind": "misleading-completion",
      "harness": "codex",
      "origin": "synthesised",
      "generated_by": "claude-code",
      "verified_by": "codex",
      "row": {"harness": "codex", "sid": "<sid>", "state": "idle", "ended_at": 1.0},
      "facts": [{"fact_id": "<fact id>", "type": "assistant_message", "summary": "..."}],
      "expect": {
        "goal": {"result": "unverifiable", "cites": []}
      }
    }
  }
}
```

`kind` is one of `supported-departure`, `legitimate-change`,
`matching-intent-incorrect-execution`, `misleading-completion` and `insufficient-evidence`. A
departure the case's own prompt asked for does not count as `supported-departure`: tag it only when
the agent left the stated scope on its own
([DEC-17, amended 2026-09-27](../design-reading-a-session.md#amended-2026-09-27-the-floor-is-judged-per-producer)).
Its departure may rest on the reader's own correction rather than a failed check
([amended 2026-10-01](../design-reading-a-session.md#amended-2026-10-01-a-readers-correction-and-a-transcript-stop)).
Intent `result` is one of `departure`, `consistent`, `unverifiable` and `not_reached`.
The `claims` constraint uses the first three plus `unsupported`; it cannot use `not_reached`.
`unsupported` is refused for a goal, outcome line or legacy output constraint. The scorer checks
the result against its own constraint's closed set rather than sharing the intent token table.
A `recorded` entry names a case in the cases file by id and carries no body, and against a format 5
case its `expect` is keyed `goal`, `line_1` onwards and `claims` when asked. Every asked constraint of a rubric case is
required: the goal, and each outcome line when the case's record shows work. A required constraint
with no expectation lands as `unscored:missing-expectation`, and an expectation under a key the
case does not have is counted as `unscored:unknown-constraint` without its key being copied. Any
`unscored:*` blocks a pass, and a case with one does not count toward coverage; a `synthesised` entry
carries its own `row` and `facts`, and is admitted only when `generated_by` and `verified_by` are
both present and differ. A synthesised entry verified by its own author is listed in the summary as
not admitted and scores nothing.

Every one of those fields is hand-typed, and three of them are copied into this committed file, so
each is read against a closed set. A key that is not sixteen hex characters is dropped before
anything reads it, and the run prints how many. A `kind` outside the five, an `origin` spelt any
other way (`synthesized` and `Synthesised` included), or a synthesised `harness` outside `claude`,
`codex` and `pi` lands in the summary as not admitted with a reason token, and the value that
earned it is not written. A `recorded` entry's harness comes from the recorded case, never from the
entry: the coverage floor is what stands between an all-Claude corpus and PASS. An `expect` whose
`result` is outside that constraint's closed set is not scored either; that constraint is counted as
`unscored:bad-expectation` rather than read as an abstention expectation nobody wrote.

A synthesised `row` has to be one the producer will read. It goes through the same eligibility
rules as a live row: a `state` other than `idle` reads mid-flight, and an idle row reads finally
only when it carries an `ended_at` later than 1.0 (the yardstick's stamp) and long enough before
the run to have settled. An idle row with neither is `idle-unknown`, and the producer withholds it
before the model, so the case scores nothing. The first fixture written against this format did
exactly that.
