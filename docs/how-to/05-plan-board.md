# Set up the plan board

The Plan page shows your goals, the lanes of work serving each one, and the questions waiting on
you. Use plan files, GitHub, or a second tracker through its own CLI. A GitHub milestone can
show its due date. The second tracker can supply target, update and completion dates.

You write one settings file, `compass-plan.json`. Most people have their coding agent write it.

## Let your agent set it up

Paste this into a Claude Code or Codex session:

```text
Please set up the Compass plan board for me.

1. Read https://raw.githubusercontent.com/spacedock-dev/compass/main/docs/how-to/05-plan-board.md
   and follow the steps for GitHub or plan files.
2. Ask me which GitHub milestone, parent issue or project to read. If I use files, ask where
   they live and read them to learn their formats. Ask about anything you cannot tell from the
   sources I gave you.
3. Show me the compass-plan.json you plan to write before saving it. It is the only file you may
   create or change. Don't edit, move or commit my plan files or anything in my repositories.
4. Run --diagnose to check the declarations and whether Compass can find the CLI.
   Open Plan and check Sources to see whether the tracker read succeeded.
5. Ask me to open Plan on the dashboard and tell you whether it looks right.
6. Explain the optional session summary, including what it sends. Turn it on only if I say yes.

When you're done, tell me what you set up and anything Compass refused.
```

## Set up a GitHub plan

1. Install the GitHub CLI and run `gh auth status --hostname github.com`.
   Sign in to GitHub.com with `gh auth login --hostname github.com` if needed.
2. Copy an example below into `compass-plan.json` in your Compass home
   (`~/.compass` unless you set `COMPASS_HOME`). Replace the example names and numbers.
3. Run `spacedock-compass --diagnose` and check Plan settings. Diagnosis checks the declaration
   and whether Compass can find the CLI. For a plugin install,
   [find the launcher](../../HOW_TO_USE.md#find-the-copy-your-commands-will-run).
4. On the Compass computer, choose Plan from the page links or from Menu on a narrow screen.
   Check Sources for the read state and wait for the next refresh if Compass is still reading GitHub.

A milestone uses the number in its URL. Its issues become lanes and its due date appears on
the goal when set.

```json
{
  "version": 1,
  "trackers": [{
    "provider": "github", "kind": "milestone", "repo": "owner/repo", "number": 7,
    "ask_labels": ["needs-me"]
  }]
}
```

A parent issue uses its issue number. Its direct sub-issues become lanes.

```json
{
  "version": 1,
  "trackers": [{"provider": "github", "kind": "parent-issue", "repo": "owner/repo", "number": 42}]
}
```

A Projects v2 source uses its project number. Only issues become lanes. Run
`gh project field-list <n> --owner <owner> --format json` and copy the `id` for the **Status**
field into `status_field`. Match the option names your project uses in `words`.

```json
{
  "version": 1,
  "trackers": [{
    "provider": "github",
    "kind": "project",
    "owner": "owner",
    "number": 3,
    "status_field": "PVTSSF_example",
    "words": {"Todo": "not_started", "In Progress": "running", "Done": "done"}
  }]
}
```

- You can put up to 32 sources in `trackers` or add it to existing file settings. An issue can
  serve several goals.
- Add `"ask_labels": ["needs-me"]` to a GitHub source to show its open issues in **Waiting on you**
  when they have a listed label and are assigned to your signed-in GitHub account. Label matching
  is case-sensitive. Use the exact spelling shown in GitHub. Omit `ask_labels` to leave asks off
  for that source. Each matching issue appears once even if several sources include it.
- For a project, your stored login needs access to that project and the scope described in
  `gh project --help`.
- Compass uses your stored GitHub CLI login. See
  [what the tracker read sends](../../SECURITY.md#plan-reads-from-github).
- A complete read with no issues says No lanes found. If a tracker read is incomplete,
  progress is unmeasured. If the sources with `ask_labels` cannot establish a complete set
  of matches, Waiting on you says "Tracker asks are not measured." The log asks and waiting
  sessions remain available.

## Read a workspace project

A second tracker can supply a project or a milestone within a project through its own CLI.
It needs a stored login for the declared workspace. Its issues become lanes, with status and
dates from the source. Use GitHub sources for `ask_labels`.
[How workspace tracker reads work](../../SECURITY.md#plan-reads-from-a-workspace-tracker).

## Pause tracker reads

- Start Compass with `--no-plan-trackers` to stop tracker CLI reads for the run. For a plan
  with just a tracker and an event log, use the flag so the local log stays available. Remove
  the last tracker declaration and any top-level `lane_folders` only if the remaining settings
  are valid as a standalone file plan.
- Use `--no-plan` to turn off the whole Plan page for the run. For a tracker-only plan you can
  remove the settings file to turn off Plan.

## Set it up yourself

Use these steps if you keep your plan in files.

1. **Copy the example.** Save the [example settings](../../compass/skills/compass/tests/fixtures/plan/stand-in.json)
   as `compass-plan.json` in your Compass home: `~/.compass`, or the folder in `COMPASS_HOME`.
   The installed plugin has the same file at `skills/compass/tests/fixtures/plan/stand-in.json`.
   See [Where the file lives](#where-the-file-lives).
2. **Point it at your files.** Under `repos`, give each repository's path, its local branch in `ref`,
   and the committed files Compass should read. See [Files to read](#files-to-read).
3. **Describe your formats.** Replace every `/example/...` path, and set your lane-brief folder in
   `briefs.folder` and your log in `log.path`. Then edit the templates until they match the lines in
   your goals, tracker, lane briefs and log. See
   [Lane state](#lane-state-from-the-tracker) and [Linking sessions](#linking-sessions-to-lanes).
4. **Mark anything private.** List folders Compass must skip. See [Private folders](#private-folders).
5. **Check it.** Run the dashboard launcher with `--diagnose` and read the **Plan settings** section.
   Fix what it refuses. See [When --diagnose refuses something](#when---diagnose-refuses-something).
6. **Open Plan.** On the Compass computer, choose **Plan** in the page links, or open **Menu** on a
   narrow screen. If Compass refuses the settings, Plan says why.

To find the launcher for step 5, see
[Find the copy your commands will run](../../HOW_TO_USE.md#find-the-copy-your-commands-will-run).
With the standalone program it is `spacedock-compass --diagnose`.

## Settings reference

### Where the file lives

- Put `compass-plan.json` in your Compass home, outside every Git repository.
- Save it as a regular file you own.
- For a file-only plan, keep every top-level section from the file example.
- It must be plain JSON. Comments and unknown keys are refused.

### Files to read

Compass reads only the files you list, as committed on the local branch you name. It never reads
uncommitted edits and never fetches.

| You write | Plan shows it as |
|---|---|
| `"plan/parts.md"` | its kind and position, such as `inventory 2` |
| `{"path": "plan/parts.md"}` | the same |
| `{"path": "plan/parts.md", "label": "Spare parts"}` | `Spare parts` |

A label:

- has at most 40 characters and no slash;
- can't repeat a file's name or path, or a name Plan would give, such as `inventory 2`;
- must differ from every other label in the same repository.

### Lane state from the tracker

Your tracker is a Markdown table. Each lane takes its state from the one row that names it.

- Add a column that holds each lane's brief slug, and name its header in `tracker.lane_column`.
- Put exactly one slug in each lane cell.
- Map each status word you use to one of `not_started`, `running`, `waiting`, `blocked`, `done`
  or `dropped`. Plan shows them as Planned, In progress, Waiting, Blocked, Done and Dropped.

A lane reads as **not measured** when:

- no row names it;
- two rows name it;
- a cell such as `hull, paint` or `hull.` mentions it. That cell counts against every lane it
  mentions.

Plan says how many of each goal's lanes are done. Dropped lanes, and lanes without a known status,
are listed apart and left out of that count.

Once you declare `tracker.lane_column`, every tracker table must have that column. A table with
none of your declared headers is ignored.

### Linking sessions to lanes

For lanes from a tracker CLI, put `lane_folders` at the top level. Ask your agent to read the lane's
stable `id` from the local Plan response (`GET /api/plan`) and use it as the key. The ID stays
the same when the issue title changes.

Under `briefs.lane_folders`, map each lane's brief slug to the folder its sessions run in:

```json
"lane_folders": {"hull": "/Users/me/work/hull"}
```

Sessions started in that folder then appear under the lane.

### Private folders

- `private.roots` lists folders Compass never reads.
- A private root inside a Git checkout also covers the same path in that repository's linked
  worktrees (`git worktree add`). It does not cover a separate clone.
- `private.markers` makes a folder private by its name, such as `restricted`. Each marker's `mode`
  says what must match: the whole name (`component`), one word of it (`token`) or any part
  (`substring`).
- To keep a folder private in every clone, put a marker file in it and list the file's name in
  `private.marker_files`.
- Compass cannot detect health information or confidential text, so list only files you are happy
  to see on the page.

### When --diagnose refuses something

The **Plan settings** section of `--diagnose` names each refused source, its kind and the reason.
For file plans, it includes missing or unreadable draft sources and refused lane folders.

| Refusal | Fix |
|---|---|
| Invalid tracker `ask_labels` | Use 1 to 32 distinct, nonblank labels of up to 128 characters each, or omit the setting. |
| A file entry or label breaks a rule above | Fix the entry in `files`. |
| A tracker table lacks your declared lane, title or status column, or misspells one, such as `Statuz` | Fix the header so the table has all three. |
| Two tracker tables with no blank line between them | Add a blank line. |
| A repository whose Git config includes another file | Remove the include. |
| A repository that borrows another's objects (a shared or reference clone) | Run `git repack -a -d`, then delete `.git/objects/info/alternates`. |

If you use private roots or marker files, keep the parent folders of each listed file present in
the checkout, so Compass can check them.

## Optional: give each new session its lane summary

With the summary on, a Claude Code or Codex session started in a file-based lane's folder begins
with that lane's goal, state and progress in its context.

That text goes to the session's model provider and is saved in the harness's session files. Read
[what the hook sends](../../SECURITY.md#what-can-reach-into-a-session) before turning it on.

1. Install the Compass plugin in each Claude Code or Codex account that should get the summary.
   `python3` on the harness's PATH must be 3.12 or newer.
2. In Codex, trust the Compass hooks when asked. Codex skips an untrusted hook silently in
   `codex exec`, and asks again after the hook changes.
3. Add `"summary": {"enabled": true}` at the top level of `compass-plan.json`.
4. Start each session inside its lane folder, or set `COMPASS_LANE` to the lane's slug in the
   session's environment.
5. Preview what a session would get with
   [`--plan-slice`](../../HOW_TO_USE_TERMINAL.md#preview-the-plan-summary), run from the same folder.

How it behaves:

- The setting is read when each session starts, even with the dashboard down.
- Lane state and progress come from the dashboard. It saves them each time it reads the plan with
  the summary on.
- Both read **not measured** if no dashboard has read the plan in the last 24 hours, or since you
  last changed `compass-plan.json`.
- To turn it off, remove `summary` or set `"enabled": false`.

## Turn the plan board off

Start the dashboard with `--no-plan`, or remove `compass-plan.json`. Either way the Plan page is
hidden.

[What the local plan route publishes](../../SECURITY.md#published-plan-fields) lists every field
the page can show.
