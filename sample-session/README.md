# The sample session

The Session page can open one example session, view only, so a new reader can see what Compass and
Intent and drift show before running an agent of their own. Open it from the line above the Sessions
list ("See a sample session"), or at `#n=session:acme%2Fdashboard:claude:sample`. The page's numbered
(i) marks give a short tour. [The design record](../docs/design-sample-session.md) owns the decisions.

This directory holds the session it was made from. The page itself ships a fixture built from it, in
`frontend/src/sample/session.fixture.json`.

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
