# Session identity: project labels and display ids

How Compass answers "which session am I looking at, and where is it running?" Both halves
were reported together in DRC-3962 and DRC-3963, because together they made distinct
sessions render as one. D-5 adds a third question to the same file, "and whose quota is it
spending?", which only one harness cannot answer with its own name.

The code is `compass_runtime/sessions.py` (identity, shape, freshness, display ids) and
`compass_runtime/aggregate.py` (dedup, ordering, the per-harness failure boundary). Collectors
produce rows; neither of those two files knows which harness a row came from, which is what keeps
identity one rule rather than ten. See
[`design-runtime-architecture.md`](design-runtime-architecture.md).

## The reported symptom

A user running three agents out of one worktree saw two of them. In their words:

> i have 2 codex and 1 claude started from subspace, but i am only seeing 1 codex and 1
> claude. also the project path is not normalized across harnesses.
> `git-spacedock-research-spacedock-subspace` vs `spacedock-subspace`

Two independent defects, and the second one hid the first.

## D-1: one project rule for every harness, `<parent>/<basename>`

Nine collectors each derived the project label their own way. Eight took the basename of a
working directory. Claude took its encoded `projects/` directory name with the home prefix
stripped, so one worktree read `subspace` on a Codex row and
`git-spacedock-research-spacedock-subspace` on a Claude row.

`project_from_cwd` is now the single rule. It returns the last two path segments, using the
host's own path module, and returns `(home)` for the home directory itself. Collectors apply
their own fallback when it returns empty.

Two segments rather than one because sibling worktrees are routinely all named the same
thing. `recce/compass` and `agy-subagents/compass` are different work; `compass` twice is
a dashboard that lies. This matters more after the normalization, not less: making labels
agree across harnesses also makes them agree across directories that merely share a
basename.

A path under the home directory is labelled relative to it. Without that, `~/foo` reads
`<username>/foo`, which puts the account name in a UI column and disagrees with the
`project_label` fallback that strips exactly that prefix. The two derivations have to land
on the same string or the unification is only skin deep.

Both are capped at two segments, and the fallback's cap lives in
`sessions.bounded_project_label` rather than downstream. `project_label` returns every
remaining segment of a home-relative path joined by `-`, and one real store held
`repos-recce-recce-cloud-infra--claude-worktrees-drc-3976-finish`. Capping it here is
reading the string the way it was just written: this is the only place a label is built by
joining path segments, so it is the only place a `-` is known to be a separator rather than
part of a directory's name. The cost is stated rather than hidden. A directory genuinely
named `work-my-repo` reads as `my-repo` on the 0.75% of rows that carry no `cwd`, which is
a grouping cost, against a home-relative path in a fourteen-day store, which
[SECURITY.md](../SECURITY.md)'s never-list calls a security bug.

The comparison against home goes through `normcase`, which folds Windows case and separator
spelling and preserves length. `C:\Users\jared` and `C:/Users/jared` and `c:\users\JARED`
are one directory, and a store may record any of them.

### Rejected

- **Capping the label in the history store instead.** It shipped that way and had to come
  back out. By the time a label reaches `history.observation` it is one string, and
  `my-cool-project` is the same shape as `alpha-beta-gamma-delta-epsilon-zeta`: the store
  split on `-` whenever no `/` was present, so real directories were truncated.
  `spacedock-ensign-drc-4044` was stored as `drc-4044` while the board went on showing the
  whole name, which grouped a project's history under a label the board never used and left
  the seeded panels with nothing to render for it. No segment count separates the two cases
  either, because `docs-sync-next-ui-design-parity` is a real directory with six of them.
  The store still bounds on `/`, which is unambiguous.
- **Splitting on both separators by hand.** Tempting, because a Windows path read on POSIX
  keeps its backslashes. `docs/design-cross-platform.md` already rejected the generic version
  of this helper and the same reasoning applies here: `\` is a legal POSIX filename
  character, so the split turns one directory named `my\proj` into two. Compass only reads
  stores written on the machine it runs on, so `ntpath` on Windows and `posixpath` elsewhere
  are the correct semantics, and `windows` is injectable so one runner covers both.
- **Comparing against home with string equality.** Passes on POSIX and silently mislabels on
  Windows, where the same directory has several legal spellings.
- **Accepting a relative or unresolved cwd.** `..` and `relative/path` produced labels like
  `compass/..`. Returning empty and letting the collector fall back to the harness name is
  the honest answer.

## D-2: read Claude's working directory from the transcript, not the directory name

Claude is the only harness whose store hands a collector no path. It encodes one into the
`projects/` directory name by replacing every separator with `-`, which is lossy:
`~/git/spacedock-research/spacedock/subspace` and a single directory literally named
`git-spacedock-research-spacedock-subspace` encode identically, so the basename cannot be
recovered by splitting.

The transcript records carry the real `cwd`, so `claude_session_cwd` reads it from the head
and the encoded name survives only as the fallback for a transcript too young to have
written one. That fallback stays whole rather than guessing at a split.

### Rejected

- **Splitting the encoded name on `-`.** Ambiguous by construction, per above. It would
  silently mangle any project whose directory name contains a hyphen, which is most of them.
- **Reverse-engineering the encoding from the home prefix.** Only recovers the prefix, which
  is the part already being stripped. The interesting segments stay ambiguous.
- **Leaving Claude on the encoded label and changing the other eight to match.** Would make
  every harness display a full path, which is what the report was complaining about.

## Antigravity multi-folder workspaces

Antigravity supports adding directories to an active workspace with `/add-dir`. Its CLI log
then writes the plural `workspaceDirs=[...]`, while `cache/last_conversations.json` still maps
the conversation to its primary workspace. Treating the whole log value as one cwd makes
`project_from_cwd` label the card from the last added directory.

The cache keeps only the most recent conversation id for a workspace. That id anchors the
primary path to the raw `workspaceDirs` context, and every conversation observed in that same
context inherits it. Metadata events are then replayed in log order, so logs still supply a
workspace for contexts missing from the cache and newer log-only values replace older ones.
Anchor discovery reads the bounded identity-bearing heads of older logs too: the cached
conversation can be quiet while a sibling in the same context remains active. Only logs inside
the requested activity window contribute sessions and prompts, so recovering an old anchor does
not put stale work back on the dashboard.

### Rejected

- **Using the whole `workspaceDirs` value as a cwd.** It combines several paths and labels the
  session from the final one.
- **Protecting only the cached conversation id.** Older sibling conversations share the same
  workspace context but no longer appear in the one-entry-per-workspace cache. They would keep
  the combined log value and split one project into two labels.
- **Filtering logs before discovering anchors.** The one cached conversation can fall outside the
  activity window before another terminal in the same workspace does. Filtering first loses the
  only unambiguous primary path even though the older log head is still safe to consult for
  identity.
- **Splitting the value on spaces.** Paths can contain spaces, and the log field carries no
  escaping that would make such a split reversible.
- **Always keeping the first log value.** Rotated logs are read oldest to newest. A session
  absent from the cache should retain the newest workspace the CLI reported.

## D-3: display ids widen per harness until unique

Session rows showed the first 8 characters of the session id. That is safe for Claude, whose
ids are random uuid4, and wrong for Codex, whose ids are UUIDv7: the leading 48 bits are a
millisecond timestamp, so agents launched together share leading hex by construction.

A fan-out in one directory therefore produced rows with the same harness badge, the same
project and the same displayed id. Four sessions reproduced locally as `019fa752` four times
over. That is the whole of the reported "sessions collapse together": nothing was ever
dropped, the rows were just indistinguishable. Fixing the project label alone would have
made it worse, since the project column started matching too.

`assign_display_ids` widens the shown prefix until it is unique, with a floor of 8, the way
git shortens a commit sha. `sid` stays whole; only the display string grows.

The group is `(harness, project)`, because that is exactly what the row prints beside the id,
so those are the rows a reader has to tell apart. Grouping by harness alone looks equivalent
and is not: four UUIDv7 agents started in the same millisecond need 16 to 18 characters to
separate, and every other Codex row would inherit that width for nothing. That is the same
objection this document raises against a fixed longer width, arriving by a different route.

### Rejected

- **A fixed longer width.** Trades one arbitrary number for another and still collides at
  enough concurrency, while making every row noisier for the common case that never needed it.
- **Showing the id tail instead of the head.** Works for UUIDv7 specifically and breaks the
  ordering intuition of every other harness. It also silently reintroduces the bug the day a
  harness adopts a random suffix scheme.
- **Deduplicating the rows.** They are not duplicates. `dedupe_sessions` was investigated
  first and correctly keys on the full `sid`; collapsing distinct sessions is the bug, not
  the fix.
- **Disambiguating with the session title.** Fan-out agents in one workflow are frequently
  dispatched with identical prompts, so the titles collide exactly when the ids do.

## D-4: the calm ledger orders rows on nothing that ticks

Calm mode gives each session one row in a table that repaints every five seconds. The first
version sorted each rank group by age, which is what the design source did. On the fixture that
looked right, because a fixture's ages are frozen. Against a live board it shuffled: two
generating sessions swapped places between refreshes, and the row a reader had their cursor on
moved out from under them.

Age itself is not the problem. Age is `generated - last_activity`, one clock shared by the whole
payload minus a per-session timestamp, so two idle rows hold their relative order forever. The
problem is a *working* row, whose last activity is always inside `WORKING_THRESHOLD_SEC` by
definition. Ordering those by age sorts them on which one wrote most recently, which is noise at
the resolution the column even prints.

So each row carries a `sortAge` that is its real age everywhere it means something and zero for a
working row, and the session id, which never changes, breaks every remaining tie. A row now moves
when its state changes and not otherwise. This is the same call `collect()` already makes
server-side when it sorts on `sid` rather than `last_activity`, arrived at independently on the
client, which is a reasonable sign it is the right one.

### Rejected

- **Bucketing age to whole minutes, then falling back to the id.** The first attempt at a fix, and
  it was worse than no fix. Ages advance together but cross their minute boundaries at different
  moments, so a row that ticked over fell behind its bucket-mates by id and then jumped back ahead
  a minute later. Measured on a 28-row board: one row crossing a boundary reordered 26 of them.
  Coarsening a key does not make a sort stable, it just makes the instability periodic.
- **Freezing the order and only re-sorting when the set of sessions changes.** Hides real state
  changes, which is the one thing the reader is watching for. A session going from working to
  needs-input has to move to the top immediately.
- **Sorting on the payload's own array order.** `collect()` does sort deterministically, but on
  `(state_rank, sid)`, which is not the order calm mode wants, and it reorders whenever any
  session's state changes. Depending on it would couple the two silently.

The row's `where` column follows D-3 to its conclusion. `project · session id` rarely fits in one
column of a dense table, and truncating the tail eats the id, which is the part D-3 widened
precisely so the row could be told apart. Only the project gives way; the id is never cut.

## D-5: a row names the authority it spends, because one harness does not own its own

Nine of the ten harnesses answer "whose quota is this burning?" with their own name. Pi does not.
It is a harness over other people's subscriptions: a Pi turn runs on `anthropic` or `openai-codex`
or a direct API key, the choice can change mid-session, and the row said only "Pi". So a Pi turn
moved the Codex gauge with nothing on screen connecting the two, which made the Codex tile look
like Codex was working.

So `base_session` gained `provider` and `model`, and the page renders them as `via Codex ·
gpt-5.6-sol`. Four things about that are decisions rather than details.

**Both fields sit on every row, at `None`.** Declaring them per harness would make the payload's
shape depend on which collector filled a row, and every consumer would then test for presence
rather than for a value. `provider` is Pi's alone, because Pi is the only harness where the answer
is not already the harness name. `model` is not: which collectors read one, and what a row says
when none of them can, is owned by [Q-11 in
design-usage-quota.md](design-usage-quota.md#q-11-every-row-names-the-model-it-runs-on-and-a-row-that-cannot-read-one-says-so).

**The payload carries the vendor's own id, unmapped.** `openai-codex`, not `codex`. Naming is
presentation, and the page already owns the harness table, so `PROVIDER_HARNESS` lives beside it in
`spark.js`. A provider Compass has no row for keeps its own name, and an unrecognised id passes
through unchanged: Pi supports twenty-odd providers and most are direct API keys with no Compass
presence, so mapping one to a harness would claim a session that does not exist.

**It is derived from the branch path on every read, never cached.** This is the one that looks like
a style choice and is not. `_extend` truncates the cached path when the session re-branches:

```python
scan["path"] = [*path_entries[: index + 1], entry]
```

A provider cached as a scalar on the scan state, the way the session name is, survives that
truncation and keeps reporting the abandoned branch's provider. Reading the path each time cannot go
stale, and it costs nothing extra because the entries are already in it.

**Recency alone decides between the two kinds of entry that carry it.** An assistant message records
what a turn actually spent; a `model_change` records a switch not yet spent, and is therefore the
newer of the two immediately after a switch, which is when someone is most likely to be looking.
Taking the newest of either needs no precedence rule. Both values come from the same entry, so a
provider is never paired with a different entry's model.

### Rejected

- **Mirroring `_latest_name`.** It looks like the precedent and is the trap. It runs a separate
  global reverse scan and is deliberately not branch-restricted, because a Pi session name is global
  state. A provider is not: copying that shape reports one the user switched away from on a branch
  the agent abandoned.
- **Reading Pi's `defaultProvider` from `~/.pi/agent/settings.json`** when a session names no
  provider. That file is current global state, so attributing it to an older session would report
  today's default as that session's history. A session with no provider makes no claim.
- **Reading `~/.pi/agent/auth.json`** to tell a subscription from an API key. It is a credential
  store, and widening Compass's credential reads for a display nicety is the wrong trade. The
  provider id carries enough: `openai-codex` and `github-copilot` are inherently subscription
  routes.
- **Publishing Pi's cost.** Pi records a dollar `cost` per turn, and on a subscription-routed call
  it is API list price for something that was billed to a subscription and charged nothing extra.
  On the machine this was built against, every provider was a subscription login, so the figure
  would have been false in the only configuration available to test it. Attribution says whose
  quota; it does not price it.
- **The borrowed harness's icon.** `HARNESS` has one for Claude and Codex, which makes the wrong
  thing easy, and a Claude glyph on a Pi row reads as a Claude session. That is the confusion this
  decision exists to remove.
- **A column in the calm ledger, and the regular idle row.** The ledger is a fixed grid whose
  columns are compared down their own length, and its `where` cell already gives up the project name
  to truncation per D-3, so there is nothing to spend. The idle row's cell truncates at a max-width
  too, which would have swallowed the label silently. Both show it where consumption is live
  instead: the working card, the needs-input row, and the calm detail panel. An idle session is
  spending nobody's quota.

## D-6: a session shows two lines, and each is labelled for the question it answers

A title answers "which session is this". "What is it working on now" is a different question,
and answering both with one string means answering one of them wrongly. Two harnesses did that
in opposite directions.

Codex answered neither. Its title came from a bounded tail read of the `event_msg`/`user_message`
record, and current builds write the prompt somewhere else: of the 276 local rollouts holding a
genuine prompt, 171 (62.0%) have the newest one outside `tail_bytes`, because `reasoning` records
carry encrypted blobs that flood the tail. Claude answered the first question and looked healthy
doing it. Its `ai-title` is generated once and never refreshed: of the 425 transcripts carrying two
or more of those records, 424 carry a single distinct value, and across the 22 that compacted
mid-session none changed. On sessions with four or more real prompts the title shares no content
word with the newest one in 112 of 152 decidable cases (73.7%).

So line 1 keeps its job, and a second labelled line carries the current instruction:

```
line 1  the session's identity, unchanged in meaning
line 2  the newest genuine prompt where it states work   -> "asked, 4m: ..."
        a bare continuation ("proceed") instead          -> the agent's own turn-start
                                                            statement of intent, above an
                                                            explicit task_started floor,
                                                            "agent, 4m: ..."
                                                         -> else the newest older prompt that
                                                            states work, and only when no
                                                            compaction boundary intervenes,
                                                            "earlier, 2h: ..."
        none of those                                    -> nothing at all
```

Codex publishes no "asked" line, because there its line 1 already is that prompt verbatim.

Nothing, rather than a best guess, is the load-bearing clause. The page resolves a title through a
`||` chain, so a wrong value does not mislead once, it masks the project name for the life of the
row. On the local corpus 177 of 457 rollouts (38.7%) reach that branch, which is the design working
rather than a shortfall: 143 of them have `<recommended_plugins>` as their only user record and
contain no operator instruction anywhere.

The label is the other one. It is what makes a second-hand or slightly stale line survivable:
"agent" says an agent is quoting itself, "earlier" says this is not the newest thing asked. A
reading with no label is refused rather than published bare.

Measured coverage of the shipped readers, over the same corpora: Codex publishes a title on 280 of
457 rollouts (61.3%) and a second line on 58 (12.7%, of which 48 are "agent" and 10 "earlier");
Claude publishes a second line on 1,906 of 3,771 transcripts (50.5%, 1,733 "asked" and 173
"earlier").

### What it did to the default dashboard

The calm view's drawer quotes `last_prompt` under a `last prompt` heading, and it quotes it only
where the string differs from the title above it. The test is exact equality. On Codex both fields
now come out of the same backward walk over the same prompt, clipped at 80 characters for the title
and 140 for `last_prompt`, so any prompt longer than 80 characters fails that test and the drawer
quotes a wider clip of the line it sits under. Over 2,931 rows of one local store, 50 Codex rows
carry a `last_prompt`, exact equality suppresses 19, and 26 of the remaining 31 are the same prompt
re-clipped. The same shape reaches Claude on 30 of 164 rows, where a session with no `ai-title`
falls back to `prompt_title` of its opening prompt.

It stays as it is. The walk that produced the duplication is what gives that view a Codex title on
280 of 457 rollouts, read through `prompt_title` rather than lifted out of raw record markup, and a
repeated quote in an opened drawer costs less than a row named after its directory. The next UI's
`nextInstructionEchoes` already suppresses the wider case, comparing against the title minus its
ellipsis; porting that test to the calm view is a change with its own risk to the rows it would
newly silence, so it is recorded here rather than made here.

### Rejected

- **Reading one record shape.** The turn-start preamble moved at CLI 0.149.
  `event_msg`/`agent_message` with `phase: "commentary"` covers 295 of the 306 local rollouts on
  0.142.5 through 0.146.1 and **0 of the 88** on 0.149.1; `event_msg`/`item_completed` with an
  `AgentMessage` item covers 78 of those 88 and none of the older files. The user record split the
  same way. Both shapes are read, on both records, for that reason and no other.
- **A plain backward walk for the preamble.** It returns the turn's LAST commentary, which is a
  progress report ("The full gate is clean. Coverage remains 85.2%"), not its first, which is a
  statement of intent ("I'm taking over task 5 in the isolated worktree"). Those differ in 227 of
  281 current turns (80.8%). Publishing the former under an "agent" label says the session was
  asked to do the thing it just finished.
- **An unbounded walk with no turn floor.** `io.reverse_lines` carries no notion of a turn, and
  26 to 43% of turns hold no commentary of their own, so the walk crosses silently into the
  previous turn and presents its intent as this one's. The floor is an explicit `task_started`
  record, and a walk that never reaches one publishes no preamble. Reaching one is not by
  itself proof, either: a turn that has not written its own `task_started` yet lets the walk
  run past the newest prompt and reach the PREVIOUS turn's floor, which would validate that
  turn's commentary as this turn's intent. So a preamble is only ever taken from records newer
  than the newest genuine prompt, which makes it this turn's by construction.
- **A naive "newest user record" read.** Injected on 230 of 456 rollouts (50.4%). Seventeen
  measured Codex shapes and fourteen Claude ones are rejected by `records.injected_prompt`, and a
  tag filter alone is not enough: after it, 306 of 2,868 Claude files still have a newest "prompt"
  that is not an instruction, and the dominant contaminants carry no markup at all.
- **A character-length rule for "this prompt states no work".** Tempting and wrong: 51.7% of newest
  prompts have a first line under 80 characters and most are short AND informative. A "under 40
  characters, walk back" rule replaces 402 good lines to fix 81 bad ones, and an independent
  reviewer's "24 characters or fewer" swept in "create the PR" and "apply the fix". The rule is a
  word count at six words or fewer, with slash commands exempt because `/release` is two words
  rendered and a whole instruction meant. The RENDERING decides the shape, which is where a
  slash command becomes recognisable; the tag-stripped BODY decides the count. Counting the
  rendering instead was wrong on 97 of 2,066 local newest prompts, because `prompt_title`
  returns line 1 only: a short opener over a multi-line body ("a backend python test is
  failing:"), and one-line prompts whose first 140 characters are mostly a pasted URL, which
  `shorten_paths` leaves whole so it counts as a single word.
- **Positional rules on the turn group.** Grouping on `passthrough.turn_id`, first-of-group is
  injected 48.4% of the time and last-of-group 32.3%. One title in three would be junk, and per the
  `||` chain above, junk permanently.
- **Walking back to an older prompt silently, with no label.** Stale on 28.3% of decidable
  mid-flight pairs, and Codex crosses a compaction boundary in 28.2% of them. A labelled older
  line is admissible where a silent substitution is not, which is the whole difference between
  this and the substitution `observer.py` already refuses to make.
- **Deriving the line in `turns.scan_turns`.** The scanner's import graph is pinned and excludes
  `transcripts`, so `prompt_title` is unreachable from it, and its over-budget branch loses the
  prompt permanently across a restart.
- **Reusing `last_prompt` for the second line.** It is read at ten render sites, two of which are
  not the session card, and `records.safe_text` collapses newlines so two lines cannot share one
  string field anyway.

## What was ruled out along the way

Worth recording, because the issue as filed pointed at collection and the cause was
presentation:

- The Codex collector. Two rollout files, distinct ids, identical cwd, both fresh, produced
  two rows.
- `dedupe_sessions`. Keys on the full `sid`, not the display id.
- The frontend. Both the rate ring buffer and the notification map key on `harness + ":" +
  sid`, and no project-based grouping exists in the render path.

## Cursor

Cursor rows were hardcoded to the literal `cursor`, so every Cursor session in every
repository shared one label. The `meta` table was the only place a workspace path could
plausibly live, so the first pass tried six key spellings inferred from the VS Code lineage
(`workspacePath`, `workspace`, `rootPath`, `projectPath`, `folder`, `cwd`), ranked by a guess
at which was most trustworthy, and closed by saying a real store should be read before the
key list was trusted.

A real store has now been read, and the answer is that none of the six is there. The decoded
payload of three live stores holds `agentId`, `blobEncryptionKey`, `createdAt`,
`isRunEverything`, `latestRootBlobId`, `mode` and `name`, plus `lastUsedModel` on two and
`subagentInfo` on the third. So the ranked read was always a no-op and every row fell back
to the harness name. The working directory is `cwd` in a sibling file the collector never
opened, `<agent dir>/meta.json`, which also carries `title` and `updatedAtMs`.

That file now feeds the same ranked map, seeded under a pseudo-key above all six rather than
compared against their winner afterwards, so which path a row publishes stays one decision in
one place. It is ranked first because it is the only value anybody has observed; if some build
does write a stale `workspace` key, ranking that above the measured one is exactly the
confident-wrong label the ladder exists to prevent.

The isdir gate stays, and applies to the measured value too. In this family `workspace`
routinely holds a `.code-workspace` *file* and `workspaceStorage/<hash>` paths are everywhere,
either of which passes an "is it an absolute path" test and yields a confident wrong label,
which is worse than no label. So a candidate is accepted only when it resolves to a directory that
exists on this machine, which makes the guess validate itself, and the `file://` spelling is
accepted alongside a bare path since it is the canonical serialization in that family.

A miss is not a fault. One live agent directory, the subagent's, has no `meta.json` at all,
so an absent, unparseable or truncated file means *this session has no workspace* and never
*this store is broken*: taking the store-error path here would withdraw the title, the model and
the workspace of every other Cursor row, which is the same argument that keeps a store with no
`blobs` table from losing its title. What it would not do is badge the harness, which this
paragraph used to claim it would. Only an exception escaping `collect` sets `harness["error"]`, and
`record_store_error` is not one: see
[design-unread-sources.md](design-unread-sources.md#u-2-store_errors-reaches-no-reader-so-a-published-field-was-required-either-way).

### Folding a subagent onto its parent

Cursor subagents keep their own store under the same workspace hash and were published as
peer top-level rows. The parent link is measured rather than inferred: the child's `meta`
carries `subagentInfo` with `parentAgentId`, `rootParentAgentId`, `toolCallId` and `typeName`,
and both ids name a sibling agent *directory*, which is exactly the `sid` another row
publishes, since a Cursor sid **is** the agent directory name. It is an id-to-id edge, not an
inference from timing or a shared hash.

Three decisions came with it:

- **`rootParentAgentId` before `parentAgentId`.** Nothing on this machine nests deeper than
  one level (there the two ids are equal), so the rule chosen is the one that cannot orphan a
  grandchild into a peer row, which is the defect being closed. Antigravity already flattens a
  whole subtree onto the root card, and the frontend's tooltip is written for it.
- **A parent id that names no row promotes the child.** The live store already holds that
  shape, and a dropped row is an invisible failure: the reader cannot tell "folded" from
  "lost". A payload naming itself is treated the same way rather than nested under itself.
- **The parent absorbs the subtree's activity**, as Goose and OpenCode do, so a parent parked
  while a child writes cannot age out of the window; `own_activity` carries the parent's own
  store mtime beside it, which is what keeps the parent-alone reading absorbing would
  otherwise throw away.

Every folded child is published as a pill, so nothing disappears from a card, but only the
children that are moving *now* are counted into the state detail: a child parked hours ago
must not make its parent read "running 1 subagent". The label is `typeName` (`cursor-guide` on
the live store) because a child's own `name` is the generic literal `New Agent`, and its model
is read from its own store rather than inherited, so a child running elsewhere is a
measurement and not an attribution.

## Claude

### A teammate dispatched into its own pane

Cursor's rule above is the one every harness is meant to follow: every folded child is published,
and only the children moving now are counted into the state detail. Claude did the opposite of the
first half. A team member dispatched into its own tmux pane writes an ordinary top-level
transcript, and the collector classified it, folded it and joined it to the teams registry
correctly, then published it only while it was fresher than the ninety-second working threshold. One
internal list was doing both jobs, so publication inherited a gate that only the state derivation
needed.

Three things followed, all measured on a live board rather than argued.

A teammate blocked on its own subagents writes nothing while it waits, so it dropped off its lead's
row and came back, over and over. A teammate that had finished vanished, and the registry could not
rescue it: a member that has written a transcript is correctly excluded from the unstarted list, so
nothing published a member that had started and stopped. And the pill carried no elapsed at all,
because the start stamp came from the transcript's first record and this harness opens a top-level
transcript with untimestamped control records: the first stamp sits at index 3 on seven of the
eight freshest transcripts measured and at index 6 on the eighth, against index 0 on every
legacy subagent file.

The fix splits the one list in two. The fresh-gated list still derives state, the state detail, last
activity and the Spacedock strip, unchanged. A separate published list carries every classified
child inside the display window, plus the unstarted members, plus each teammate's own subagents,
each element stamped with its own liveness and with the member it belongs to. A parked teammate
therefore stays on the row and reads as stopped, which is what the Cursor rule asked for in the
first place.

Two decisions inside it are worth keeping.

The registry's `isActive` flag may demote and may never promote. Claude Code 2.1.259 retains a
finished member and marks it inactive instead of pruning it, which is a genuine liveness signal and
retired an assumption the code and the shipped skill body both carried. But transcript freshness
stays authoritative for whether something is running now, because whether a hard-killed pane clears
that flag has never been measured. A signal that can only ever confirm a stop cannot invent a start.

That leaves two answers to one question, on purpose. The roster's `active` can read false as soon as
the registry says a member finished, while `state_detail` keeps counting that member as running until
its transcript ages past `working_threshold_sec`, so the pill and the state line can disagree for up
to ninety seconds and then agree again. It is not an inconsistency to tidy up: the flag is allowed to
demote the pill because a demotion is the half of it that was measured, and the state line is
deliberately left on freshness because DRC-4118 and DRC-4263 both settled what may move it.

A teammate's own workers are flattened onto the same list with the teammate named, not nested under
it. Nesting is the shape a reader might expect and it is the one that can orphan a grandchild into a
peer row, which is the defect the Cursor work closed by choosing `rootParentAgentId`. Antigravity
already flattens a whole subtree onto the root card. The attribution is a label rather than a join
key, and labels here are not unique: two runs of the same named agent inside the display window are
two children with the same name, and their workers cannot be told apart by it.

#### Rejected

Publishing the teammate as a peer row that names its lead. A teammate transcript is a complete
session transcript, so this would have delivered state, turn, tokens and the teammate's own pills
for free, and the change is deleting a `continue`. It reverses the Cursor decision on the surface
where the parent link is strongest, since a teammate names its lead by id, which is exactly the
condition under which that work folds rather than promotes. The population settled it: of the twenty
top-level transcripts fresh inside twenty-four hours in one project directory, fourteen were
classified teammates of a single lead, so promotion turns a six-row board into a twenty-row one.

What is not kept, and was claimed here in the round that shipped the fold, is a promotion rule. There
is none. A classified child is folded onto the prefix its `teamName` names and the loop moves on, so
a child whose named lead has no transcript of its own is attached to a row that never appears, and
its own workers go with it. Driven on a fixture of exactly that shape: one fresh classified child
naming an absent lead, holding one live worker, publishes **zero sessions**. The drop predates this
work and closing it means either promoting such a child or reporting the orphan, which is a
different decision than the one this issue was filed to make.

Keeping the ninety-second publication gate and encoding "finished" in the label string. Cheaper, and
refused because the chrome counts published elements into its running total, so the header would
have had to lie in order to close a gap at the pill.

### Published roster cap and omitted count

Widening the published roster from the ninety-second window to the entire display window
meant a lead session with dozens or hundreds of finished workers produced unbounded payloads
(294 elements and 30 KB observed on a single row, DRC-4348).

`sessions.SUBAGENTS_ROSTER_CAP` bounds the published roster to 60 elements per session.
Under the cap, live workers (`active is True`) are retained first, followed by the newest
finished workers ordered by `started_at` descending. The honest difference is published in
`subagents_omitted` on every session row (defaulting to 0), and rendered in the detail panel
as `+N older finished worker(s) omitted` when positive.

## D-7: a session in a linked worktree files under its repository

The two-segment label of D-1 keeps sibling worktrees apart, and it did so by splitting one
repository into one project per checkout: sessions started in `.claude/worktrees/<name>` were
filed under `worktrees/<name>`. The project key already followed the worktree's `.git` pointer
and its `commondir` back to the main checkout (`sessions.project_identity`), so the key was
right and the label, which the board groups on, was not.

`apply_project_identity` now gives a session whose working directory sits in a linked worktree
the label of the main repository (`project_from_cwd` over the main root), and publishes the
worktree's own directory name as `worktree`. A main checkout publishes `None`, so a reader can
tell "not a worktree" from an empty name. Both pointers are plain files read with no
subprocess, and the same two reads serve the key and the label.

The worktree name sits beside the project on the Sessions row and in the session header, since
the label no longer separates two sessions on one repository. It goes through the same
credential sweep as `project_name`, because a directory name is operator text.

A session whose worktree was removed afterwards has no `.git` pointer left to follow, so the
pointers cannot place it. A working directory of the form `<root>/.claude/worktrees/<name>` whose
`<root>` still holds a `.git` directory is filed under `<root>`'s repository with `<name>` as its
worktree; that layout is Claude Code's own, and no other harness's layout is guessed at. A removed
worktree elsewhere, or one whose repository is gone too, keeps the label of its own working
directory. `apply_project_identity` reads the checkout once and the same result serves the key,
the label and the worktree name.

Sessions rows draw the name as `worktree <name>` under the project, so the line is not an
unexplained second one. Bookmarks keyed by the earlier `worktrees/<name>` label do not follow a
session to its repository's label: the key was never the label, but a bookmark that stored the
label finds nothing under it and is not migrated.

Not changed: a session in a subdirectory of a main checkout keeps the label of its own working
directory, as before. How writes inside an isolation worktree count is a separate ruling.
