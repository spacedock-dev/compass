---
name: compass-release
description: Use when cutting a Compass release, choosing the major, minor or patch bump from what changed since the last tag, pushing the tag, confirming the Release workflow landed, and optionally announcing it in Slack.
---

# compass-release

One release: decide the number from the evidence, cut it, confirm it landed, and say so in a way
that claims nothing the range does not contain.

Invoke `compass-release` with no argument to analyse and propose a version. Pass a version
(`0.17.0`) to propose that one instead, and the analysis still runs so a disagreement is visible
rather than silent. Pass `--dry-run` to analyse, print the proposal and stop without tagging.

Versions here are owned by the tag-driven Release workflow. This skill does not edit a version
field, ever. It decides a number, pushes a tag and then watches.

## Public notes and development traceability

Follow [the shared publication rule](../../../AGENTS.md#public-documentation-and-release-notes).
The complete release body and announcement contain no Linear names, issue keys or tracker URLs.
The rule includes generated changelogs, copied PR titles, code fences, reference links and HTML.
Use plain claims about shipped behavior and public GitHub PR references. Keep issue-to-commit,
promise-ID and move evidence in private release preparation or allowed development records,
[whose taxonomy is defined separately](../../../docs/development-tracking.md#how-work-links-to-a-promise).
Do not publish that internal trace table as the release note.

Use `scripts/validate_plugins.py --public-text FILE` on the final assembled text before publication;
this mode checks only the supplied raw body. Unreadable/invalid input or any forbidden reference
stops publication. Repository validation alone does not check GitHub's generated or published body.
Re-read the actual body after publication and check it too. Do not claim the preflight covers text
that changed or was generated afterwards.

## Prerequisites

- A Git checkout on `main`, current with `origin`, with a clean tree and push access for tags.
- GitHub read access to confirm check status and the published Release.
- For the announcement only: a Slack capability that can resolve a channel and post to it, and the
  `humanizer:humanizer` skill. Both are optional. Missing either costs the announcement and
  nothing else.

If a prerequisite for the release itself is missing, stop before the tag push and say which.

## 1. Pre-flight

Answer all of these before looking at any diff. Any "no" stops the run.

```bash
git checkout main && git fetch --prune origin && git pull --ff-only origin main
git status --porcelain                  # must be empty
LAST=$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' '[0-9]*.[0-9]*.[0-9]*' --sort=-creatordate | head -1)
echo "last release: $LAST"
python3 scripts/bump_version.py --current
```

**`$LAST` does not survive between shell invocations.** Every block below re-derives it, and every
one of them checks it is non-empty first. An empty `$LAST` turns `"$LAST"..HEAD` into `..HEAD`,
which git resolves to `HEAD..HEAD`: zero commits, empty diffs, exit 0. It reads exactly like a
release with nothing in it. The glob matches only the two release-tag shapes the Release workflow
accepts, so a stray tag cannot become the baseline either.

- **No release hold is recorded.** A tracked `RELEASE_HOLD` file at the repository root of `main`
  means releases are paused; see [The release hold](#the-release-hold). Check it before choosing a
  number, because a pushed tag would only start a run that fails at `resolve`:

  ```bash
  git fetch -q origin main   # a stale origin/main would print "no hold" for a hold that exists
  [ -n "$(git ls-tree --name-only origin/main -- RELEASE_HOLD)" ] && echo "HOLD: read RELEASE_HOLD, stop" || echo "no hold"
  ```

- **The tree is clean and `main` is current.** A tag is a pointer to a commit on the remote; a
  local edit is not in it.
- **`bump_version.py --current` equals `$LAST` without its `v`.** If it does not, a previous
  release is half finished. Find out why before adding a second one on top. The workflow is
  idempotent and resumable, so the fix is usually to use Re-run all jobs on the existing tag's
  run (see step 6), not to cut a new number. Pushing a tag that already exists does nothing.
- **The Live monitor's Haiku is still the newest released one.** The monitor pins an explicit
  Haiku id (`CLAUDE_MONITOR_DEFAULT_MODEL` in `compass_runtime/config.py`), and a floating alias is
  refused, so a newer Haiku reaches readers only when someone moves the default. Ask whether
  Anthropic has released a newer Haiku since the last tag (the models overview in the Claude
  documentation lists the current IDs). If so, name the bump in the release notes and make it in
  its own commit before the tag: change the default, its `--claude-monitor-model` help and the
  `MANUAL.md` row, and run `compass/skills/compass/tests/test_live_monitor_model.py`, whose
  default-id test names the id. A "no" here does not stop the run; an unanswered question does.
- **`main`'s head is green.** The Release workflow runs the contract validator, its own tests, the
  bump-version tests and the whole dashboard suite, and rebuilds and tests the frontend, all on the
  exact commit it resolved, but not the quality gate — no ruff, no mypy, no coverage threshold, no
  platform matrix — because the gate already ran on every commit that reached `main`. That only
  holds if it actually did:

  ```bash
  gh run list --branch main --commit "$(git rev-parse origin/main)" \
    --json workflowName,status,conclusion
  ```

  Three workflows run on every push to `main` — Quality Gate, Validate and Plugin Compatibility —
  and all three must come back `completed` and `success` for that exact commit. Do not use
  `--limit 1`: it returns whichever of the three finished last, so it will show you a green Plugin
  Compatibility while the gate is red. Filtering on the commit is also what rules out a green run
  belonging to a superseded head.
- **The number is still free.** You do not have one yet, so this check runs in step 4 once the
  proposal names `$VERSION`: `git tag -l "v$VERSION"` and `gh release view "v$VERSION"` must both
  come back empty.

One check that does not block but should be reported: if `COMPATIBILITY.md`'s
`docs-synced-through` marker is behind `main`, say so in the proposal. A release is the natural
moment to stamp it, and [AGENTS.md, "Parallel Work"](../../../AGENTS.md#parallel-work) says to
do that once from `main` after
merges. Do not stamp it silently inside a release run.

## 2. Gather the evidence

Commit census first, because it is cheap and it frames everything else:

```bash
LAST=$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' '[0-9]*.[0-9]*.[0-9]*' --sort=-creatordate | head -1); [ -n "$LAST" ] || echo "STOP: no release tag found"
git log --oneline "$LAST"..HEAD | grep -v 'chore(release)'
git log --format='%s' "$LAST"..HEAD | grep -v '^chore(release)' \
  | sed -E -e 's/^([a-z]+)(\([^)]*\))?!?:.*/\1/' -e t -e 's/.*/(unprefixed)/' \
  | sort | uniq -c | sort -rn
git diff --stat "$LAST"..HEAD | tail -1
```

The `-e t -e 's/.*/(unprefixed)/'` pair matters: merge commits here often carry no conventional
prefix at all. Without it the census prints eight full subject lines for `v0.7.0` instead of one
`(unprefixed)` count, and a census that is mostly subject lines is not a census.

Then the scan that actually decides the bump. Each command answers "can a person running Compass
see or do something they could not before?", and each is a real surface rather than a proxy for
one:

```bash
LAST=$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' '[0-9]*.[0-9]*.[0-9]*' --sort=-creatordate | head -1); [ -n "$LAST" ] || echo "STOP: no release tag found"
# A new or changed user-facing surface
git diff --stat "$LAST"..HEAD -- compass/skills/compass/compass_runtime/web
# New or changed CLI flags
git diff "$LAST"..HEAD -- '*/cli.py' | grep -E '^[+-].*add_argument\('
# New or changed HTTP routes, GET ladder and POST table alike
git diff "$LAST"..HEAD -- '*/http_api.py' | grep -E '^[+-].*"/(api|")'
# A harness added or dropped from the registry
git diff "$LAST"..HEAD -- '*/aggregate.py' | grep -E '^[+-].*HarnessSpec\('
# New or removed payload fields every consumer sees
git diff "$LAST"..HEAD -- '*/sessions.py' '*/aggregate.py' | grep -E '^[+-] +"[a-z_]+":'
# New or changed hook events, and the stdio MCP tool
git diff --stat "$LAST"..HEAD -- compass/hooks compass/hooks.json '*/notify_hook.py' '*/mcp_server.py'
# The runtime floor (`fail_under` rides along; it is a CI knob, not a surface)
git diff "$LAST"..HEAD -- pyproject.toml | grep -E '^[+-].*(target-version|python_version|fail_under)'
# The shipped product surface, and the store paths a person configures
git diff --stat "$LAST"..HEAD -- compass/skills/compass/SKILL.md HOW_TO_USE.md COMPATIBILITY.md
```

Read what comes back. A census line is evidence; a diff hunk is the fact.

Two of those patterns are wider than they look, deliberately. The route grep matches any quoted
absolute path in `http_api.py` because POST routes are not an `if` ladder: they are entries in a
dict, `"/api/answer": self._answer,`. A pattern pinned to `path == "/` finds every GET route and
none of the POST ones, so the release that added `/api/ask`, `/api/answer`, `/api/dismiss` and
`/api/ask/withdraw` would have scanned clean. And the hook-and-MCP stat is there because `v0.13.0`
added `mcp_server.py`, 826 lines of new user-facing surface, that nothing else in this list touches.

## 3. Classify the bump

**The rule is the surface, not the commit type.** A `feat:` prefix is how the author felt about
their change, and it has been wrong in both directions here (see the last section).

**Patch** when every change corrects behaviour that already shipped, or is invisible to someone
running the dashboard. Tests, CI, benchmarks, packaging, internal refactors, comment and doc
corrections, and fixes to a surface that already existed all sit here, however many there are. A
release of twenty-one fixes is still a patch if none of them adds a surface.

**Minor** when a person running Compass can see or do something they could not before: a new
panel or row field, a new harness, a new flag, a new route, a new hook event, a widened contract,
a newly published payload key.

**Major cannot be derived from the changes.** Compass is `0.x`, and under semver the major stays
`0` until the interface is declared stable. Cutting `1.0.0` is a decision to commit to that
interface, not a consequence of any diff, so never infer one. If the operator asks for a major,
confirm it is deliberate and say what `1.0.0` would commit to, because those become the things that
need a major to change afterwards: the `/api` payload contract, the CLI flags, the store
relocation environment variables, the Python floor, the hook payload shape, the stdio MCP tool, the
plugin and skill names an install references, and the set of supported harnesses.

**Run the breaking-change scan regardless of the number.** Every grep in step 2 prints removals
alongside additions, and the `-` lines are the breaking half: a dropped CLI flag, a deleted route, a
harness out of the registry, a payload key that stopped being published, a raised Python floor. The
`--stat` commands cannot tell you that on their own, so when `compass/hooks`, `COMPATIBILITY.md` or
the web assets move, open the diff rather than reading the file count. Below `1.0.0` a break does not
force a major, but it is the single most important thing an announcement can carry, and a Python
floor raised in silence is how an install stops working with no note anywhere. Anything the scan
finds goes into the proposal and into the notes.

## 4. Propose, and stop

A release is irreversible. Tags here are immutable, a ruleset blocks deleting or moving them,
`stable` advances to the released commit, and the shared marketplace serves whatever `stable`
points at. A wrong number cannot be withdrawn, only superseded by the next one, forever.

So print the proposal and wait for an explicit yes. Never tag on an inferred approval.

The proposal carries:

1. The range: `$LAST..HEAD`, and the commit count with `chore(release)` excluded.
2. The census.
3. The classification, with the specific evidence that decided it, named. "Minor, because
   `frontend/src/sessions` gained an instruction line and `sessions.py` publishes a new `instruction`
   key" is a reason. "Minor, 4 feats" is a count.
4. Anything the breaking-change scan found, or an explicit "nothing".
5. The proposed version, and the `docs-synced-through` note if the marker is behind. Prove it is
   free before you print it, because this is the first point in the run at which the number exists:

   ```bash
   VERSION=<the proposed number>
   git tag -l "v$VERSION"                       # must print nothing
   gh release view "v$VERSION"                  # must fail with "release not found"
   ```
6. What pushing the tag will do, in one line each: validate the tag and fix the commit to release,
   verify the frontend and the tree on exactly that commit without credentials, write one
   `chore(release)` bump commit, prove its `git archive` with Python only, then move the tag onto
   it, advance `stable`, publish the Release, then stamp the version onto the marketplace listing and
   write it into the Homebrew formula.
7. The question: cut it, and separately, do you want release notes posted to Slack afterwards?

Prepare the complete public note before asking, including any generated changelog to be retained.
Preview GitHub's generated notes for the proposed tag, previous tag and exact release head. Check
that complete generated body with the standalone public-text validator too: the tag workflow may
publish it before the hand-written note is applied. If the generated preview contains tracker
references, correct the offending PR titles to plain behavior before tagging, then regenerate and
validate the whole preview. Internal provenance remains in the PR bodies. If clean generation is
still blocked, report it and stop before tagging; the workflow has no arbitrary curated-file input.
For an already approved release, a curated complete body can be validated and applied through the
authorized GitHub release operation, then the same release resumed with its actual body checked.
Reconcile its version, tag and stable state before claiming it complete; do not infer those outcomes
from the existence of a curated note. A preview checks specific bytes, not future generation.

Ask the Slack question here so the run has one interruption rather than two. The notes themselves
still get their own approval in step 7, because nobody can approve text they have not read.

## 5. Cut it

```bash
VERSION=<the number the operator just approved>        # e.g. VERSION=0.17.0
git checkout main && git pull --ff-only origin main    # again; the wait may have been long
gh run list --branch main --commit "$(git rev-parse origin/main)" \
  --json workflowName,status,conclusion                # green again, on the NEW tip
git -c tag.gpgsign=false tag "v$VERSION"
git cat-file -t "v$VERSION"                            # must print `commit`, not `tag`
git push origin "v$VERSION"
```

`-c tag.gpgsign=false` is not decoration. On a machine with `tag.gpgsign true` a bare
`git tag <name>` tries to create a signed tag, finds no message and dies with `no tag message?`
before anything reaches the remote. The override forces the lightweight form, which is what this
repository's release tags actually are: `git cat-file -t v0.16.0` prints `commit`, not `tag`, and
the workflow's own `git tag -f` re-creates the tag lightweight anyway when it moves it onto the bump
commit. Where signing is off the override does nothing, so it is safe to leave in. The `cat-file`
line is there because the failure is silent in the other direction: an annotated tag pushes fine and
you would only find out later that it does not match its siblings.

This one was found the hard way, on the first real run. Every other command in this skill was run
before it was written down; the tag command was the one that could not be rehearsed against the
real remote, and it was the one that was wrong. It can be rehearsed locally: create a throwaway
name, check the type, delete it, and never push it.

That second green check is not paranoia. The workflow releases the `main` tip, not the commit you
tagged, so anything that merged while the proposal sat waiting is in this release and the pre-flight
result no longer covers it. If the tip moved, re-run step 2 over the wider range before tagging: the
number you got approved may no longer be the right one. Regenerate and validate the proposed public
body and generated preview for that new head as well; an earlier clean body covers no later titles.

The `v` prefix is canonical. A bare `0.17.0` also works, but pick one form per release and do not
mix them in a single run.

## 6. Watch it land

Do not report a release until it exists.

```bash
gh run list --workflow Release --limit 1 --json status,conclusion,headBranch,databaseId
gh run watch <id> --exit-status
```

Then confirm all five outcomes, because the workflow does five separate things and a partial run
leaves some of them undone:

```bash
VERSION=<the number you just tagged>
git fetch --tags --force origin && git checkout main && git pull --ff-only origin main
git log --oneline -1                       # the chore(release) bump commit, if one was needed
python3 scripts/bump_version.py --current  # equals the new version
git rev-parse "v$VERSION^{commit}" && git rev-parse origin/stable   # tag moved, stable advanced
gh release view "v$VERSION" --json name,tagName,url
gh release view "v$VERSION" --json assets --jq '[.assets[].name] | sort'   # the standalone binaries
```

The last line must list five files: `compass_$VERSION_<os>_<arch>.tar.gz` for `darwin_arm64`,
`darwin_amd64`, `linux_arm64` and `linux_amd64`, and `checksums.txt`. They land a minute or so after
the release itself, from the `attach-cli` job, so look again before calling it missing. The
Spacedock installer reads exactly these names from `releases/latest`.

The marketplace listing is stamped by the `marketplace` job, after `release`. Confirm it shows the
version, because `stable` alone already serves the release and a failed stamp would otherwise pass
unnoticed:

```bash
gh api repos/spacedock-dev/marketplace/contents/.claude-plugin/marketplace.json --jq .content \
  | base64 -d | jq -r '.plugins[] | select(.name == "compass") | .version'   # equals $VERSION
```

The Homebrew formula is written by the `homebrew` job, after `attach-cli`. Confirm the tap shows the
version too, because the release and `stable` are fine without it and only `brew` users would lag:

```bash
gh api repos/spacedock-dev/homebrew-tap/contents/Formula/compass.rb --jq .content \
  | base64 -d | grep -m1 '  version '   # equals $VERSION
```

The bump commit is the one outcome that is conditional: the workflow skips it when the manifests
already carry the tagged version, which is the initial-release path and the resume path. Step 1's
parity check is what makes it unconditional on every normal release.


If the run failed part way, do not cut a new number and do not push the tag again: the tag
already exists on the remote, so a second push is `Everything up-to-date` and starts nothing, and
the ruleset forbids deleting it. Open the failed run and use **Re-run all jobs**. That is the only
re-run that works, because it is the only one that runs `resolve` again. **Re-run failed jobs**
keeps the first run's resolved target, so a target that main has since moved past fails the
assertion again, every time. Every step is idempotent and the workflow detects its own resume.
Read which job failed first:

- **`resolve` failed with "releases are on hold".** `RELEASE_HOLD` is on `main`. Nothing was
  tagged, verified, pushed or published, and nothing needs undoing. Do not work around it: read
  [The release hold](#the-release-hold).
- **`verify-frontend` or `verify-tree` failed.** Nothing was pushed, tagged or published; the tree
  that was verified is not releasable. Fix it on `main` through a PR, then Re-run all jobs on the
  same run: `resolve` takes the new main tip and both verifiers cover it. The run uses the workflow
  file of the tagged commit, so a fix to `release.yml` itself cannot be picked up by a re-run and
  needs the next version number.
- **`release` failed at "Put HEAD on the verified commit" or "Refuse to publish anything but the
  verified tree" with "main is no longer" or "main is at".** A commit landed while the verifiers
  ran, or this is a retry after the bump commit was pushed. Re-run all jobs: `resolve` takes the new
  tip, or finds this tag's release commit and resumes it. This is the safe outcome, not a defect to
  work around.
- **`release` failed at the archive proof.** The release commit exists only on the runner, so
  nothing was pushed, tagged or moved. Read the failing check in the log (versions, changes,
  bundle, inventory, page, launch); `changes` and `bundle` mean the bump commit shipped something
  other than what was verified, which should never happen and needs an owner before any re-run.
- **`build-cli` failed.** Nothing was pushed, tagged or published, because `release` waits for all
  four builds. It ran PyInstaller on a host of each target, so read which target and whether it was
  the build or the packed archive's smoke run. The `CLI package` workflow runs the same build on any
  pull request touching the runtime, so a break here that it did not catch is usually a runner
  image change. A fix goes through a PR, then Re-run all jobs; a fix to `release.yml` itself needs
  the next version number.
- **`attach-cli` failed.** The release exists and is correct; it only lacks its archives, so the
  Spacedock installer skips Compass until they are there. Re-run all jobs: the workflow resumes, finds
  the release already published, and attaches again (`--clobber` makes that safe).
- **`marketplace` failed.** The release is published and `stable` serves it, so installs already get
  the new version; only the listing's displayed version is behind. Re-run that job alone: it never
  moves the version backwards, so it is safe. If the log says the entry must point at `stable`, or
  that it found no `compass` entry, the marketplace listing has drifted from this repository, and the
  entry needs a pull request there before any re-run can pass. A rejected push three times means the
  marketplace's `main` is busy or the deploy key was removed; check the key on that repository.
- **`homebrew` failed.** The release and `stable` are fine; only `brew` users lag. If the log says
  `HOMEBREW_TAP_DEPLOY_KEY is empty`, add the secret, then re-run that job alone: the formula never
  moves backwards, so it is safe. A rejected push three times means the tap's `main` is busy or the
  deploy key was removed; check the key on that repository. After **Re-run all jobs** the archives
  are rebuilt, so `brew install` fails on a sha256 mismatch until `homebrew` succeeds again.
- **A later step failed (push, tag, `stable`, publish).** Re-run all jobs: the workflow finds this
  tag's release commit on `main`, verifies that commit, and publishes it, never a newer `main`. It
  moves `stable` forward only, so resuming an older release after a newer one leaves `stable` where
  the newer release put it and says so in the log.

### The release hold

`RELEASE_HOLD` at the repository root of `main` pauses every release. It is a real guard: the
Release workflow's `resolve` job runs `scripts/release_transition.py resolve`, which refuses with
`releases are on hold` while the file is present on `main`, for a fresh release and for a resume
alike. It reads `main`'s tree rather than the checkout, so a stray local file holds nothing and
deleting the file locally lifts nothing. `resolve` holds no credentials and runs before every
verifier, so a refused run has tagged, pushed and published nothing. `assert-checkout` asks again
in the publishing job, so a hold merged while the verifiers ran still stops a resume before the
bump, tag move or `stable`. If main cannot be read at all, both refuse: an unreadable repository
is not a missing hold.

When a hold exists, the file records why and what lifts it. The hold that covered the React cutover
lifted for 1.0.0: the legacy frontend and its rollback were removed (the script parts frozen for the
recorded Intent and drift replay live under `scripts/frozen-page/`, outside the plugin), and the
Python-only install and backend-connected development checks passed on one build of `main`. Only the
repository owner lifts a hold, by deleting the file in a reviewed pull request. This skill never
deletes it, and never edits it to make a release pass.

After the file is gone from `main`, use **Re-run all jobs** on a run that stopped at the hold (a
tag that is already pushed cannot be pushed again), or push the next version tag.

### Rehearsing the sequence

The decisions are in `scripts/release_transition.py` and can be run against a throwaway clone
whose remote is a local bare repository, without touching the real remote or a real tag:

```bash
python3 scripts/release_transition.py --repo <throwaway clone> rehearse --tag v0.2.0 --dry-run
```

`rehearse` resolves, verifies, bumps, proves the archive and, without `--dry-run`, pushes, moves the
tag and advances `stable`, all against that clone's remote. It refuses any remote whose fetch or
push URL is not a local path, so it cannot reach GitHub. `scripts/verify_release_archive.py --repo .
--commit <release commit> --verified <verified commit> --version X.Y.Z` runs only the archive
proof (versions, changes, bundle, inventory, page, launch) on a local commit. Neither command can
rehearse GitHub Actions itself, the deploy key or the rulesets.

## 6.5 Write the release note for a person

The workflow prepares GitHub's generated list of merged pull requests, checks its complete body
with the public-text validator and publishes that same file with `--notes-file`. A forbidden
reference fails before the version bump or release publication; the workflow does not sanitize
it automatically. The generated list is a changelog, not a release note, and a reader who did not
follow the work learns nothing from it.
It was CL's complaint about the 0.19 and 0.20 packaging, and 0.20's note was rewritten by hand
afterwards.

After step 6 confirms the release exists, read its actual generated body into an owned, uniquely
named draft file. Sanitize the generated section as well as writing the note above it: replace
internal issue labels in titles with plain behavior, remove tracker links and keep public GitHub
PR references. Do not blindly keep the original generated section underneath.

Validate the entire final file with `scripts/validate_plugins.py --public-text FILE` before passing
that same file to `gh release edit --notes-file`. Read back the resulting body and validate those
actual published bytes. If it differs or a generated section still violates the rule, report the
failure and correct only the authorized release body; do not announce an unchecked note. A later
edit does not make an earlier unscreened publication compliant.

What the note says, in this order:

1. The promise, in the words `docs/promise-map.md` uses. Do not write a new one for each release.
2. What this release changes about keeping that promise, as two to four plain claims grouped by
   the reader's task. Each gives one sentence of what a user can now do and one of what backs it,
   with public GitHub PR references where useful. Verify the issue/promise/move trace privately;
   internal labels belong to preparation, not the published claims.
3. How to upgrade, and what does not change.
4. What the release does not add, and a link to the promise map. This is the paragraph that makes
   the rest believable.

Two rules that come from the same review. Never promise something the release did not ship, and
never lead with before-and-after screenshots: they explain a design progression to people who
followed it, and they belong in `docs/design-*.md`.

## 7. Announce it, if asked

Only after step 6 confirms the Release exists. Announcing a release that has not published is
worse than not announcing.

**Write the notes for a person, not a changelog.** GitHub already generated the full changelog,
and the Slack message that repeats it is noise. Slack gets what changed for
someone using Compass, and a link.

Aim for a short paragraph or a few bullets: the version, the one or two things worth knowing,
anything the breaking-change scan found, and the Release URL. If nothing in the range is worth a
person's attention, say that plainly and keep it to a line. A patch release of internal corrections
does not need three bullets invented for it.

**Verify before humanising.** Every claim has to trace to a commit in `$LAST..HEAD`. This is the
step that stops a plausible summary describing work that shipped two releases ago. Check each
sentence against the log, and delete anything you cannot point at.
Keep that evidence trace in private preparation or development records; the announcement uses
plain claims and public PR/release links. Check the whole final announcement with the standalone
public-text validator after humanising and before showing it for approval.

**Then invoke `humanizer:humanizer` on the draft.** The notes are human-facing prose and they carry
the same voice standard the prose docs do. If that skill is not installed, apply the standard by
hand: it is written out in full in the [`sync-docs` skill's "Voice and tone"
section](../sync-docs/SKILL.md#voice-and-tone), which exists
precisely because this repository does not vendor the tool. No em dashes, no mechanical boldface,
sentence case, no AI-vocabulary words, no participle tails, no upbeat closer.

Resolve the channel at run time rather than trusting a remembered id:

- Search Slack for the `#agentchat` channel and take its id from the result.
- Show the operator the final text and the channel it will go to.
- Send only on an explicit yes. If they would rather see it in Slack first, post it as a draft
  instead of a message and let them send it.
- Report the message link back.

## Hard rules

Never edit a version field in a branch. The Release workflow owns all three, and `version-guard`
fails any PR that changes one.

Never tag without an explicit yes in this run. Approval for a previous release is not approval for
this one.

Never announce before `gh release view` succeeds.

Never put a claim in the notes that is not in the commit range. Nothing else in this process has a
check that would catch it.

Never publish tracker references in any release-note or announcement section, generated or written.

Never cut a major to mean "this one is big". At `0.x` that number is not available, and above
`1.0.0` it means a break, which is a fact about the diff rather than a feeling about the release.

Never back-tag or reuse a number. The workflow refuses it, and the refusal is the feature.

## Why the classification is written this way

Measured over the whole tag history on 2026-08-28: 27 release tags, so 26 version decisions after
the initial `0.1.0`. Fifteen minor, eleven patch, no major ever.

Reading the bump off the commit types would have agreed with 23 of those 26 and been wrong three
times, which is why this skill reads surfaces instead:

- `v0.4.3` was a **patch containing a `feat`**. The feat listed Cargento in the shared marketplace
  and retired our own, which is packaging. Nothing on the dashboard changed.
- `v0.8.1` was a **patch containing a `feat`**. That one was `feat(bench)`, a tool for measuring a
  session mix you do not have. A developer benchmark is not a product surface.
- `v0.8.0` was a **minor containing only a `fix`**, and it is the one that does not dissolve. The
  fix was to the release workflow itself.

The first two stop being exceptions the moment the question is "can a user see it?" rather than
"what prefix did the author use?". That is the whole argument for the rule in step 3.

One more thing the history says: `BREAKING CHANGE` and the `!` suffix have been used zero times in
this repository. No breaking change is going to announce itself in commit metadata, so the scan in
step 2 is not belt and braces. It is the only detector there is.
