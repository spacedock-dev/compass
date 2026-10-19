# The sample session

The Session page can open one example session, view only, so a new reader can see what Compass and
Intent and drift show before running an agent of their own. Open it from the line above the Sessions
list ("See a sample session"), or at `#n=session:acme%2Fdashboard:claude:sample`. The page's numbered
(i) marks give a short tour. [The design record](../docs/design-sample-session.md) owns the decisions.

This directory holds the session it was made from, `milestone-session.jsonl`. The page itself ships a
fixture built from it, in `frontend/src/sample/session.fixture.json`.

## Why this session, and why this stretch

Compass is for long work: a run toward a milestone, where the goal is set once and the session has to
hold to it for hours. The sample is that kind of session. It is one of this repository's own sessions:
an agent coordinating other agents to burn down a milestone of Compass's own roadmap, with the
person's end goal stated in so many words ("burn down fully" the milestone, with every issue in it
closed). It was chosen over the other long sessions measured for the summary work because it holds a
real departure and a real steer, the steer in the person's own words, and because the drift can be
said in a sentence without knowing the project: the goal was to close every issue in the milestone,
and the agent, short of that, suggested moving an unfinished issue out of the milestone so the
milestone could close. The person's reply put it back: the issue "is not done so of course it stays",
and the agent was to finish it.

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

## What is real, and what is not

It is an illustration, not a byte-for-byte record. These are the parts that are not the original:

- **Cut.** `scripts/cut_sample_session.py` keeps the records from the person's burndown request to the
  agent's reply after the steer, and only the kinds the page reads or the story needs: the person's and
  the agent's messages with their tool calls and results, the compaction marker, turn timings, pull
  request links and the title. Everything else Claude Code writes beside them is dropped: the loaded
  instructions and tool lists, account and remote-session records, hook summaries, editor snapshots and
  mode switches. Compass reads none of it, and most of it describes the machine rather than the work.
  1,015 records remain. The first record's parent, which the cut removed, is `null`.
- **Anonymized**, by `scripts/sanitize_session.py`. Every name, path, project word, id and date is
  replaced. The project reads as `dashboard`, the organization as `example-org`, the person's address
  as `user@example.com`, and the home directory as `/Users/dev`. Thinking blocks are dropped and
  screenshots inside tool results are replaced by a placeholder. Run and job numbers, commit hashes and
  pull request numbers are regenerated wherever they appear, the pull-request link records included,
  and the short eight-character form of a session id becomes the short form of its replacement. Every
  timestamp moves by one fixed offset, so the order and the gaps survive and no timestamp shows the
  real date or hour, and times written as text (a monitor's log, a file listing, "failed at 13:58" in a
  pasted correction, a Unix time in an API answer) move with them. A machine's local times are turned
  into UTC on the way, because a local time beside its UTC timestamp gives the time zone away. The
  tracker reads as `tracker.example.com`, its issue keys as `DASH-<n>` with regenerated numbers, and
  the slugs its links and branch names carry, which spell issue titles, are dropped. The product's
  name, under its current and its earlier name alike, reads as `Dashboard`. A companion tool, other
  projects and sessions on the machine, a status-line script and a desktop utility read under neutral
  names. So is everything that would find this repository's public history: every quoted hash that
  names a commit in it, the branch names (as `work/branch-<letter>`), the pull-request titles and
  commit subjects the session quotes, cut short or whole, and each line it quotes from a pull request's
  description or a commit's body, which reads as "(a line of the pull request's description)". The
  project key Compass prints, a hash of the repository's path, is the hash of the replaced path.
- **Not shaped.** The failing check the story turns on was already run on its own and recorded as a
  failure, so no edit to what the session did was needed. The first sample needed one, and its shaping
  script went with it.
- **What is not replaced.** The product's feature names (Intent and drift, Steer back and the others),
  its documents and file names, the identifiers in the code the session quotes, and the versions of
  the tools it ran. A reader who knows the product will recognise it, and one with the public
  repository can place the session within a few weeks, from the files it reads and the versions it
  records. Matching the work it quotes against that history could narrow it further, and a few
  sentences the agent wrote in its own messages and later reused, reworded, in a pull request's
  description are close enough to search for; the replacements above make that a search rather than a
  lookup.
- **The intent is the person's own words**, from the record, where they state it at 10:54 UTC in the
  record: the goal "Burn down fully the "Intent and drift: see where a Claude Code session
  drifted and steer it back" milestone", and the expected outcome "All the issues in the "Intent and
  drift: see where a Claude Code session drifted and steer it back" milestone are closed". It is saved
  thirty seconds after that message, as the person saved it in the session itself, with its window
  opening at the person's first message, and the later directions (the requests after the save, the
  pasted correction and the steer) are settled through the last record, as Keep would settle them.
  The save writes the store directly, because a save over HTTP opens its window at the latest message
  before it.
- **The summary and the reading are real**, each generated once on 2026-10-19 through an isolated
  Compass and the owner's signed-in Claude Code, and stored in the fixture as they came back, apart
  from the timeline rewrites below.
  - The summary was made by the summary job when the finished session was opened (`origin: "open"`),
    in three parts: two windows of 77 and 13 entries and the opening summary, three model calls,
    `claude-sonnet-5-5`. It was run twice, the second a Summarize again, because the first withheld
    its last phase whole; the second is kept, and it withholds it too. Both runs were read against the
    raw replies and withhold the same kind of line for the same reasons: the session is about merging
    pull requests and closing issues, and a line saying so in the summary's own voice ("The agent
    merged PRs"), after a comma that ends a speaker's licence, or under "It said" rather than a named
    speaker, is withheld as the ruled backstop requires. None was a producer bug. The page shows each
    withheld line in its place.
  - The reading was one Analyze through the same server, `claude-sonnet-5-5`, with tool output
    included as the default allows. It found a departure on the goal and on the outcome line, and the
    Steer back correction was composed by Compass from it. Seven model calls were made in all: six for
    the two summaries and one for the reading.
- **The timeline rewrites.** `scripts/build_sample_fixture.py` puts the stored summary 30 seconds
  after the session's last record and the reading 45 seconds after it, moves the reading's age
  sentence ("The oldest is from about 3846h ago") to the reading's place on that timeline ("about 1h
  ago"), and cuts the board's intent digest and the summary's prompt digest in its model stamp to 32
  characters. The board's permissions are shown as a store with no stored off reads them: readings
  and summaries on, nothing refused and no notice recorded, with one reading and the stored summary's
  three calls counted.

## Why a transcript is in the repository

The repository does not commit session transcripts, even sanitized: [tests/README.md](../tests/README.md#what-is-committed-and-what-is-not)
records why. This one is an exception the owner made on 2026-10-19, for this session, once it had
passed `scripts/sanitize_session.py --verify` and two independent leak reviews, because the sample is
only worth having if a stranger can read the real record behind it. On the same day the owner
approved pushing it with the content the reviews flagged and the build kept on purpose (below), after
being told how the last round's findings had been checked. It replaced the first sample, a one-turn
session committed under an exception made on 2026-10-14, which was removed when this one replaced it.
The mapping that holds the originals and the original itself are never committed, and `.gitignore`
refuses a mapping file kept in this directory.

## Checks it passed

- `scripts/sanitize_session.py --verify`: every line parses, the line count matches, every parent and
  every tool result resolves, and none of the original values (plain, case-insensitive, URL-encoded or
  JSON-escaped) appear. It also sweeps for emails, other home directories, secret shapes, long hex and
  base64 runs, and runs a secret scanner when one is installed.
- Two independent leak reviews of the anonymized file alone, with different lenses: one reader on
  identity and environment (Codex, `gpt-6.1-sol`, high effort, read-only), the other on project and
  business content (AGY, `gemini-4-argon-high`, plan mode), both on secrets and structure. Each finding
  sent the file back through the sanitizer and both reviews ran again on the result. The first rounds
  found local times that still showed the machine's time zone beside the UTC timestamps, a machine's
  uptime clock, pull request numbers held as integers in the link records and in a form the rule
  missed, a companion tool's name, two other sessions' titles, other projects on the machine, and a
  status-line script and desktop utility by name. A round run on the committed file returned no leak
  found. A later review against the repository itself found what a reader of the file alone could not:
  eight short commit hashes and the branch names, pull-request titles, commit subjects and
  pull-request descriptions the session quotes, all of which lead to dated public history; the
  tracker slugs, which spell issue titles; and a project key computed from the real path. They are
  replaced as described above, `--verify` and the file tests now check the hashes, branch names and
  project key against the repository, and both reviews ran again on the result, asked this time to
  look for those classes too.
- **The final round, in its final form.** Both reviews returned "leak found". Each finding was checked
  against the repository by the lane that built the sample, not independently: the titles, subjects,
  hashes, branch prefix and review slug they named are the regenerated replacements, none of which
  appears in the repository's commits or pull requests; the project key is the hash of the replaced
  path; and the rest is what is kept on purpose below, or worktree and scratch-folder names that exist
  only on the machine. The owner was told this before approving the push.
- Kept on purpose, after review: the names of public tools (Claude, Codex, AGY, Chrome and the
  others); the identifiers in the code the session quotes (`next-cockpit-*` and the other class and
  attribute names, and a string-length constant), which belong to this public repository and would
  only point back to the product the sample is shown in; and dates, which moved by one fixed offset and
  fall in April and May 2026.
- `scripts/tests/test_sample_session_files.py` runs the repository's sweeps on the session, the
  fixture and this README, including the ones for tracker references, encoded home directories and
  machine temp paths, and checks against this repository that no quoted hash names a commit, no branch
  name is one of its refs, and the project key is the hash of the sample's own path. It also checks
  that the fixture carries the stored summary with at least four phases, a departure whose evidence
  sits in one of them, and every record page to the start.

## How big it may be

The fixture ships inside the built page, so both are bounded before anything is built;
[the design record](../docs/design-sample-session.md#how-big-it-may-be) owns the bounds and why. This
session's record is 81 entries in two pages, and the fixture with its summary and reading is 128,257
bytes of compact JSON.

## Regenerating it

The mapping file (`mapping.json`) holds the originals and lives outside the repository. Its shape is a
`salt`, a `day_shift`, a `time_shift_seconds`, an `ai_title`, a list of `literals` (`from`, `to`,
`category`, and `word` for whole-word matches), lists of `hashes` and `numbers` to regenerate, and
optionally `commit_repo`, the repository the session worked in: every hex token in the session that
names a commit there is regenerated, and `--verify` fails if any token in the output names one.

1. Cut the original with `scripts/cut_sample_session.py`, then `python3 scripts/sanitize_session.py
   --mapping mapping.json --input cut.jsonl --output sample-session/milestone-session.jsonl`, and
   again with `--verify`.
2. Start an isolated Compass: an empty home, an empty `CLAUDE_CONFIG_DIR` holding only
   `projects/-Users-dev-repos-acme-dashboard/<session id>.jsonl`, a temporary `COMPASS_HOME`, `TZ=UTC`
   and `--window-hours 100000`, so a session from months ago is on the board. The reading and summary
   calls use the signed-in `claude` on `PATH`; if its sign-in needs the real home, a wrapper that
   restores only `HOME` and drops the scratch `CLAUDE_CONFIG_DIR` for that one program is enough.
3. Before the server starts, save the intent above into that home's annotation store with
   `annotations.annotate`, its window at the first message and its save time thirty seconds after
   the person states it, and record the session's end in `compass-ends.json` five seconds after its
   last record, so the board reads it as finished and the save as made before the end.
4. Open the session's summary with `POST /api/summary` `{"action": "start", "origin": "open"}`, run one
   reading with `POST /api/reading`, settle the later directions through the last record with `POST
   /api/annotate` `{"settle_through": ...}`, and check that `POST /api/correction` composes.
5. `python3 scripts/build_sample_fixture.py --base-url <that server> --project acme/dashboard --sid
   <the first eight characters of the session id> --out frontend/src/sample/session.fixture.json`,
   then `pnpm build`. The capture reads every record page back to the start and stores the older ones
   under `older`. `pnpm test` fails if the page or the fixture is over its bound.

The drift level reads Medium, from the two departures the reading found. The live estimate, from
checks and file paths alone, has too little recorded after the person's last message to read a level
of its own.
