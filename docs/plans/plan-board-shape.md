# Plan: the plan board shape

Status: ruled, not built. The owner ruled every decision below on 2026-11-27, so they are decisions
and not proposals. The build milestone is written from this file. Delete it once the board ships and
its contents have moved to `SECURITY.md`, `MANUAL.md` and the design records.

The questions are in three GitHub issues: [what the board reads](https://github.com/spacedock-dev/compass/issues/1103),
[how a new session gets its slice](https://github.com/spacedock-dev/compass/issues/1104) and
[what the board must never show](https://github.com/spacedock-dev/compass/issues/1105). The discovery
behind them is in [round 1](https://github.com/spacedock-dev/compass/issues/1100),
[round 2](https://github.com/spacedock-dev/compass/issues/1101) and the
[account rotation findings](https://github.com/spacedock-dev/compass/issues/1102).

## What the board is for

A customer runs several agent lanes across a few repos and keeps her plan in files she writes by
hand: a goals file, a design file, a tracker, a folder of lane briefs and a shared event log. The
plan board shows that plan next to the sessions doing the work, so she, her coordinators and her
agents can see which goal each lane serves and what is waiting on a person.

It is local. It runs on loopback on her computer and never forecasts a completion date
(owner ruling, 2026-11-27, recorded in [#1101](https://github.com/spacedock-dev/compass/issues/1101)).

## Sources and settings

Decided in [#1103](https://github.com/spacedock-dev/compass/issues/1103), owner ruling, 2026-11-27.

- One hand-written settings file lives in the Compass home and never inside a repo. It names every
  repo, file, branch, lane-brief folder and log path. Nothing is guessed.
- The settings file follows the `reader_checks` precedent. The build adds a SECURITY.md read
  section, `test_security_primitives` entries and a `--no-plan` switch.
- Plan file text is published on its own `/api/plan` route, capped and redacted, apart from session
  data.
- Compass reads one Claude Code folder and one Codex home per board process (measured in
  [#1102](https://github.com/spacedock-dev/compass/issues/1102)). The agent
  launcher supports a separate folder per account profile, so the build checks the customer's
  profile `env` from her setup. If her profiles use separate folders, a follow-up issue adds an
  explicit opt-in for extra folders, and that issue carries the privacy cost.

## Status words and dates

Owner ruling, 2026-11-27.

- The settings file declares the tracker's closed list of status words and maps each to a board
  group. An unknown word marks only its own row "Status not recognised" and does not echo the word.
  `--diagnose` lists it.
- Repo items get their date from `git blame --first-parent` at the configured branch's committed
  tip, on local refs only. There is no fetch and no `gh`. The result is cached per file and tip and
  labelled "Changed {date}". The command passes `-c blame.ignoreRevsFile=`.
- An item that exists only on the draft PR's local branch reads "Proposed, not merged", with that
  branch's commit date.
- Lane briefs and the log sit outside git, so no commit can date them. The board shows the log's own
  time, labelled "from the log".
- Blame is a new git command family, so it needs a SECURITY.md amendment.

## Progress

Owner ruling, 2026-11-27. A goal shows its "done when" sentence, the lanes serving it grouped by
state, and one derived count such as "2 of 5 lanes are done". There is no bar, no percentage and no
date. A goal with no lanes reads "No lanes serve this goal yet". The count is derived from the lanes
the page renders, never authored, and it reads differently when nothing was measured (see
Measured Invariants in `AGENTS.md`).

## Layout

Owner ruling, 2026-11-27. The board is a new top-level Plan page. It is mocked up in Storybook for
the owner's sign-off before it is built. The sections, in order:

1. Waiting on you: open asks from the log first, then sessions waiting on a reply.
2. Goals.
3. Design.
4. Tracker.
5. Diagrams.

The glossary gains three rows: Blocked; a lane word distinct from the Working session state; and
"Product decisions", distinct from the existing Decisions tab. The rows go in the layer's own block
in `frontend/src/language/glossary.ts` and [the design glossary](../design-calm-compass.md#glossary),
in the same order in both.

## What never shows

Decided in [#1105](https://github.com/spacedock-dev/compass/issues/1105), owner ruling, 2026-11-27.

- Allow list. The board opens exact repo files, read from the configured ref's current tree; one
  lane-brief folder, non-recursive, with a filename grammar; and one log file. Nothing else is
  opened. There are no globs and no walking.
- Where the lists live. The allow list, private roots and markers are in the settings file in the
  Compass home, never in a repository.
- Private roots. A private root is matched by the filesystem identity (device and inode) of every
  parent folder, not by comparing path strings. A declared marker, NFC normalised and then
  casefolded, can only add privacy. A match refuses that source.
- Git history. Repo content comes only from the current tree. History supplies commit times and ids,
  never messages, authors, diffs or older content.
- Links. The board and the agent summary show no URLs. Each link becomes its host, after the
  existing redaction runs. The existing redaction was measured to miss `?key=`, `?code=`, webhooks,
  magic links and share links. That older gap is filed separately and privately.
- The log. It is read as anchored fixed-format lines with a closed list of verbs and bounded fields.
  Any other line is counted and never shown.
- Published fields. Only a closed list of named fields is published. Each is redacted, then its URLs
  become hosts, then it is capped. SECURITY.md lists the fields.
- Failures. Each source fails closed on its own: unreadable, malformed, a symlink, a hard link,
  private, or an unknown status word in a structural position. Each failure gives a closed reason,
  with no fallback to the last good read.
- The agent summary is built only from the published board model. SECURITY.md says it reaches the
  agent's model provider.
- Local only. Plan routes answer loopback peers only, whatever `--host` or `--allow-host` says. Plan
  text never enters the history store.
- What the page admits. The page lists its sources and says plainly that it cannot detect health
  information or confidential text typed into them.

## The agent summary

Decided in [#1104](https://github.com/spacedock-dev/compass/issues/1104), owner ruling, 2026-11-27.

- Delivery. A new SessionStart hook script is registered in `hooks.json` and `codex-hooks.json`. It
  prints only `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":...}}`,
  the shape both harnesses declare. That shape was measured on 2026-11-27 in
  [Claude Code 2.1.332](../captures/claude/session-start-context-2.1.332-macos.jsonl) and
  [codex-cli 0.172.0](../captures/codex/session-start-context-0.172.0-macos.jsonl). Both accept
  it, the text reaches the session's context, and printing nothing adds nothing. Every other path
  prints nothing and exits 0.
- Measured limits. Claude Code injects up to 10,000 characters whole and replaces anything longer
  with a 2 KB preview of a saved file. Codex injects up to 10,000 bytes whole and cuts anything
  longer in the middle. The 1,500-byte bound sits well under both. Both harnesses wait for the hook
  before the first model request, so its run time is added to session start. A hook past its
  `timeout` is killed and injects nothing; Codex says nothing when that happens. Codex `exec` skips
  an untrusted hook silently, and its trust is stored per hook definition, so a changed hook command
  must be trusted again. Asked to repeat the text, the Codex model declined, but it acted on it.
  Both harnesses keep the text in the session's own transcript. Neither capture measured a hook
  registered by an installed plugin or the default timeout.
- It builds the summary from the plan files with the board's own code, so it works with the
  dashboard down.
- It is off until the person turns it on in the settings file. `--plan-slice` shows what a session
  would get.
- Each account needs the plugin installed, and each Codex account needs its hooks trusted once.
- DEC-16 is amended to allow this one path. See
  [the amendment](../design-reading-a-session.md#amended-2026-11-27-an-opt-in-plan-summary-at-session-start).
  Corrections stay copy-only.
- Lane lookup. An explicit `COMPASS_LANE` setting is read at session start, like
  `COMPASS_PARENT_SESSION`. Otherwise the working folder must sit inside exactly one lane brief's
  declared folder. Otherwise the session gets nothing. Spacedock dispatch cannot help at session
  start, and subagent ensigns are a measured follow-up.
- Content. Fixed labels: goal, "done when", progress or "not measured", lane state, and up to 3 asks
  plus a count of the rest. At most 12 lines and 1,500 bytes, with no dates. It is cut from the
  board's lane row, so it cannot show anything the board does not.
- No model and no network. Like `--footer`, the hook starts no program and opens no socket.
  `test_security_primitives` pins this.
- Provider exposure. The summary goes to the harness's model provider and can cross vendors and
  accounts. That is why it is opt-in and shows fewer fields than the board.

## SECURITY.md changes the build will make

SECURITY.md is not edited now, because nothing is built. When the build lands, it adds, in outline:

- a read section for the plan settings file and the sources it names, following `reader_checks`;
- the new git command family (`git blame --first-parent`, local refs only) and its flags;
- the closed list of published plan fields, and the rule that URLs become hosts;
- the loopback-only rule for plan routes and the statement that plan text never enters the history
  store;
- a row on what can reach into a session: the opt-in summary, what it contains, and that it goes to
  the harness's model provider;
- the `--no-plan` switch and the off-by-default summary hook;
- the limit that Compass cannot detect health information or confidential text in the plan files.

## Test plan

Each "never reaches" case asserts on both the `/api/plan` payload and the summary text. Details are
in the analysis for [#1105](https://github.com/spacedock-dev/compass/issues/1105) and
[#1104](https://github.com/spacedock-dev/compass/issues/1104).

Canaries from #1105:

1. Private-marked folder. An allowed file under a declared private root is refused at config load
   and at read, including with a case-changed path, an NFD path, a symlinked alias of the root and
   `/tmp`-style aliasing.
2. Marker in the lane-brief folder. A brief whose folder carries the marker (exact, upper-case,
   NFD) is not read. A homoglyph marker is documented as not honoured, and an expected-failure test
   pins that limit.
3. Token-carrying link. Each link form that the existing redaction misses, placed in a goal line, a
   decision title, a PR title and an ask question, publishes the host only.
4. Raw log line. A free-text line, a JSON blob, an overlong ask, an unknown verb, a CR-split line
   and a control-character line are each counted and absent from the page and the summary.
5. File outside the allow list. A sibling file, a `../` path, a symlink in the tree, a submodule, a
   hard link to a file elsewhere and a work-tree file absent from the ref are never read. A
   recording seam asserts that no open or `cat-file` call was made.

Further checks from the same analysis: history never supplies a message or an older blob; removing
a source from settings removes its content; each failure gives its closed reason and no content;
admission-matrix rows refuse plan routes to a non-loopback peer under `--host 0.0.0.0` and an
`--allow-host` name; no plan field reaches the history store; and `test_security_primitives` passes
with one new reviewed process entry and no new `KNOWN GAP`.

Summary tests from #1104:

- Every string in a summary appears in the published board model for that lane (the summary is a
  subset of the board), as a property test over every fixture.
- Each of the five canaries above is checked absent from `--plan-slice` output as well as from the
  page.
- With no settings, or with the summary off, the hook's stdout is empty.
- The summary stays within 12 lines and 1,500 bytes, with per-field caps and the count of the
  remaining asks derived from the same list, so nothing drops silently.
- The hook starts no program and opens no socket, pinned by `test_security_primitives`.

## Build-start checks

Owner ruling, 2026-11-27: sample the customer's own setup and ask her nothing. Before the build
starts, read:

- the tracker's status word list;
- the lane brief format and folder;
- the log path and line format;
- the private-folder marker;
- the diagram format;
- her agent launcher profile folders.

Then run the reader against that setup with Compass reading nothing but the settings file, and have
her confirm the source list on the page.

## Out of scope

- Any completion forecast, bar or percentage.
- Reading more than one Claude Code folder or Codex home per board process, until the follow-up
  issue is ruled.
- Reading history content, other repos or any file outside the allow list.
- Non-loopback access to plan routes.
- Subagent summaries at dispatch time.
- Fixing the older redaction gap for token-carrying links, which is filed separately.
- Writing anything into a session other than the opt-in summary.
