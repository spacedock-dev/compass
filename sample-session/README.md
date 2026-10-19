# The sample session

The Session page can open one example session, view only, so a new reader can see what Compass and
Intent and drift show before running an agent of their own. Open it from the line above the Sessions
list ("See a sample session"), or at `#n=session:acme%2Fdashboard:claude:sample`. The page's numbered
(i) marks give a short tour. [The design record](../docs/design-sample-session.md) owns the decisions.

This directory holds the session it was made from. The page itself ships a fixture built from it, in
`frontend/src/sample/session.fixture.json`. It also holds the longer session the next sample will be
made from, `milestone-session.jsonl`, which the page does not draw yet;
[The next sample](#the-next-sample) says what it is and what is left before the page switches to it.

## What is real, and what is not

It is an illustration, not a byte-for-byte record. These are the parts that are not the original:

- **Anonymized.** Every name, path, project word, id and date is replaced, by
  `scripts/sanitize_session.py`. The project reads as `dashboard`, the organization as `example-org`,
  the person as `Alex Doe`, and the home directory as `/Users/dev`. Thinking blocks are dropped. Run and
  job numbers and commit hashes are regenerated, and every timestamp moves by one fixed offset, so the
  order and the gaps survive and the real dates and hours do not.
- **Cut.** The record is one turn of a longer session: from the person's request to resolve a pull
  request's merge conflicts, to the moment after the agent has reproduced a Windows-only test failure and
  before it writes the fix. The first record's parent, which the cut removed, is `null`.
- **Two failed runs are recorded as failures.** The agent piped its test commands through `tail`, which
  hides the exit status, so Compass reads them as "ran, result not recorded". `shaping.json` removes the
  pipe from the two failing runs and records them the way Claude Code records any failed command. It is the
  only edit to what the session did, and `scripts/shape_sample_session.py` refuses to run if an edit
  matches nothing.
- **The intent is authored.** The session did not use Compass, so the goal and the two expected outcome
  lines were written for it, as a person might have saved them just after the first message:
  - Goal: "Resolve the merge conflicts on PR 56 by rebasing it onto main. Only history should change:
    leave PR 56's code alone, and touch .github/ only if the conflict needs it."
  - Expected outcome: "PR 56's diff is byte-identical after the rebase." and "All of PR 56's quality
    gates pass."
- **The reading and the correction are real.** One reading was run on the anonymized session through
  Claude Code, and the Steer back correction was composed by Compass from it. Both are stored in the
  fixture as they came back, apart from two rewrites that put them on the sample's own timeline (the
  reading's time, and one sentence that counted entries "about 3718h ago"). The board's reading
  permission was captured under the old consent step and is edited to readings on, with nothing
  refused and no notice recorded. `scripts/build_sample_fixture.py` makes that edit.

## Why a transcript is in the repository

The repository does not commit session transcripts, even sanitized: [tests/README.md](../tests/README.md#what-is-committed-and-what-is-not)
records why. This one is an exception the owner made on 2026-10-14, because the sample is only worth
having if a stranger can read the real record behind it. The mapping that holds the originals is never
committed, and `.gitignore` refuses a mapping file kept in this directory.

## Checks it passed

- `scripts/sanitize_session.py --verify`: every line parses, the line count matches, every parent and
  every tool result resolves, and none of the original values (plain, case-insensitive, URL-encoded or
  JSON-escaped) appear. It also sweeps for emails, other home directories, secret shapes, long hex and
  base64 runs, and runs a secret scanner when one is installed.
- Two rounds of independent review by readers who were given only the anonymized file and no original,
  each with a different lens (identity and environment, project and business content, secrets and
  structure). The second round found no leak. What it flagged that was kept on purpose: the names of
  public tools (Claude, Codex and the others), the pull request numbers the story depends on, and
  branch names from the same project, which read as ordinary work.
- `scripts/tests/test_sample_session_files.py` runs the same sweeps on the files in the repository.

## Regenerating it

The mapping file (`mapping.json`) holds the originals and lives outside the repository. Its shape is a
`salt`, a `day_shift`, a `time_shift_seconds`, an `ai_title`, a list of `literals` (`from`, `to`,
`category`, and `word` for whole-word matches), and lists of `hashes` and `numbers` to regenerate.

1. Cut the original to the turn, then `python3 scripts/sanitize_session.py --mapping mapping.json
   --input cut.jsonl --output out.jsonl`, and again with `--verify`.
2. `python3 scripts/shape_sample_session.py --edits sample-session/shaping.json --input out.jsonl
   --output sample-session/example-session.jsonl`.
3. Start an isolated Compass: an empty home, an empty `CLAUDE_CONFIG_DIR` holding only
   `projects/<encoded project folder>/<session id>.jsonl`, a temporary `COMPASS_HOME`, and `TZ=UTC`. Seed
   the intent above into that home's annotation store, with its window opening at the first message.
4. Run one reading through that server, then compose the correction.
5. `python3 scripts/build_sample_fixture.py --base-url <that server> --project acme/dashboard --sid
   <the first eight characters of the session id> --out frontend/src/sample/session.fixture.json`, then
   `pnpm build`.

The live level reads High on its own, from the two failed runs after the last message, and the
analysis reads High from the departures the reading found.

## The next sample

The sample above is one turn, so it reads like a single task. Compass is for longer work: a run toward a
milestone, where the goal is set once and the session has to hold to it for hours. The next sample is
that kind of session, and `milestone-session.jsonl` is its record. The page still draws the first sample
until the next one has its summary and reading; the switch is the last step below.

### Why this session, and why this stretch

It is one of this repository's own sessions: an agent coordinating other agents to burn down a
milestone of Compass's own roadmap, with the person's end goal stated in so many words ("burn down
fully" the milestone, with every issue in it closed). It was chosen over the other long sessions
measured for the summary work because it holds a real departure and a real steer, the steer in the
person's own words, and because the drift can be said in a sentence without knowing the project: the
goal was to close every issue in the milestone, and the agent, short of that, proposed moving an
unfinished issue out of the milestone so the milestone could close. The person's reply put it back:
the issue "is not done so of course it stays", and the agent was to finish it.

The whole session ran for about fourteen hours. The stretch kept is about ninety minutes of it, and it
holds the story from start to end:

- **The start.** The person asks the agent to coordinate several agents and burn the milestone down.
- **The work.** The agent runs builders and reviewers in parallel, merges their pull requests and
  brings the milestone to two open issues. Its context is compacted partway, so the record carries the
  summary Claude Code wrote at that point.
- **The goal, restated.** The person asks the agent to walk Intent and drift on this very session, and
  states the goal and the expected outcome.
- **A correction.** The person pastes a Steer back correction Compass composed for the session.
- **The departure and the steer.** The agent files one new defect outside the milestone and suggests
  moving another out of it, and the person steers it back. The stretch ends on the agent's first step
  after the steer.

### How it was made

- **Cut.** `scripts/cut_sample_session.py` keeps the records from the person's burndown request to the
  agent's reply after the steer, and only the kinds the page reads or the story needs: the person's and
  the agent's messages with their tool calls and results, the compaction marker, turn timings, pull
  request links and the title. Everything else Claude Code writes beside them is dropped: the loaded
  instructions and tool lists, account and remote-session records, hook summaries, editor snapshots and
  mode switches. Compass reads none of it, and most of it describes the machine rather than the work.
  1,015 records remain.
- **Anonymized**, as above, with the sanitizer's newer rules on: screenshots inside tool results are
  replaced by a placeholder, the short eight-character form of a session id becomes the short form
  of its replacement, and times written as text (a monitor's log, a file listing, "failed at 13:58" in a pasted
  correction, a Unix time in an API answer) move with the timestamps. A machine's local times are
  turned into UTC on the way, because a local time beside its UTC timestamp gives the time zone away.
  The tracker reads as `tracker.example.com`, its issue keys as `DASH-<n>` with regenerated numbers,
  and the product, under its current and its earlier name alike, as `Dashboard`, so the session about
  Compass reads as a session about a dashboard. A companion tool, other projects and sessions on the
  machine, a status-line script and a desktop utility read under neutral names, and pull request
  numbers are regenerated wherever they appear, the pull-request link records included.
  No shaping was needed: the failing check the story turns on was already run on its own and recorded
  as a failure.
- **Nothing is authored yet.** The intent is the person's own words, from the record. The summary and
  the reading will be generated once with the real producer, and stored as they come back with only the
  timeline rewrites above.

### How big it may be

The fixture ships inside the built page, so the size was bounded before anything was built. The page
as built on 2026-10-19 is 1,884,747 bytes, and it may grow by at most 400 KiB, to 2,294,347 bytes. The
page carries its script base64-encoded, so each fixture byte costs about four thirds of a page byte. The
fixture may be at most 250,000 bytes of compact JSON, which is at most about 233 KB more page than the
first sample's 75,130 bytes, and leaves the rest of the 400 KiB for code. Measured against an isolated
server, this session's record is 81 entries in two pages, and the capture without a summary or a
reading is 112,166 bytes. `frontend/build/page-size.test.mjs` holds both bounds, and runs in
`pnpm test`.

### Permission to commit it

The repository does not commit session transcripts. The owner approved this one on 2026-10-19, as an
exception like the first sample's, for the session chosen here, once it had passed
`scripts/sanitize_session.py --verify` and two independent leak reviews. The mapping and the original
stay outside the repository.

### Checks it passed

- `scripts/sanitize_session.py --verify`: passed on the committed file.
- Two independent leak reviews of the anonymized file alone, with different lenses: one reader on
  identity and environment (Codex, `gpt-6.1-sol`, high effort, read-only), the other on project and
  business content (AGY, `gemini-4-argon-high`, plan mode), both on secrets and structure. Each finding sent the file back through the sanitizer and both reviews ran again on the
  result. The first rounds found local times that still showed the machine's time zone beside the UTC
  timestamps, a machine's uptime clock, pull request numbers held as integers in the link records and
  in a form the rule missed, a companion tool's name, two other sessions' titles, other projects on the
  machine, and a status-line script and desktop utility by name. On 2026-10-19 the last round of each,
  run on the committed file, returned no leak found.
- Kept on purpose, after review: the names of public tools (Claude, Codex, AGY, Chrome and the
  others); the identifiers in the code the session quotes (`next-cockpit-*` and the other class and
  attribute names, and a string-length constant), which belong to this public repository and would
  only point back to the product the sample is shown in; dates, which moved by one fixed offset and
  fall in April and May 2026; and the hash of the project's own repository key.
- `scripts/tests/test_sample_session_files.py` runs the repository's sweeps on it, including the newer
  ones for tracker references, encoded home directories and machine temp paths.

### Switching the page to it

1. Start an isolated Compass as in step 3 above, holding only this session, and save the intent in the
   person's own words from the record, where they state the goal (burn the milestone down fully) and
   the expected outcome (every issue in it closed), its window opening at the person's first message.
2. Open the session so its summary is generated, and run one reading, then compose the correction.
3. `python3 scripts/build_sample_fixture.py --base-url <that server> --project acme/dashboard --sid
   <the first eight characters of the session id> --out frontend/src/sample/session.fixture.json`. The
   capture now reads every record page back to the start and stores the older ones under `older`.
4. Rewrite the tour for the new page, update the sample design record, move this section's facts into
   the sections above, then `pnpm build`. `pnpm test` fails if the page or the fixture is over its
   bound.
