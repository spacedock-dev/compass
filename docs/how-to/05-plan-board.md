# Set up the plan board

The Plan page shows your goals, the lanes of work serving each one, and the questions waiting on
you. Compass reads them from GitHub, or from plan files you already keep in Git. Support for more
trackers is coming in a later release.

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
4. Run --diagnose and fix the settings until nothing I expect is refused.
5. Ask me to open Plan on the dashboard and tell you whether it looks right.
6. Explain the optional session summary, including what it sends. Turn it on only if I say yes.

When you're done, tell me what you set up and anything Compass refused.
```

## Set up a GitHub plan

1. **Check your login.** Install the GitHub CLI and run `gh auth status --hostname github.com`.
   Sign in to GitHub.com with `gh auth login --hostname github.com` if needed.
2. **Choose your goals.** Copy an example below into `compass-plan.json` in your Compass home
   (`~/.compass` unless you set `COMPASS_HOME`). Replace the example names and numbers.
3. **Check the settings.** Run `spacedock-compass --diagnose` and check **Plan settings**.
   Diagnosis checks the declaration and whether Compass can find the CLI. For a plugin install,
   [find the launcher](../../HOW_TO_USE.md#find-the-copy-your-commands-will-run).
4. **Open Plan.** On the Compass computer, choose **Plan** from the page links or from **Menu**
   on a narrow screen. Check **Sources** for the read state and wait for the next refresh if
   Compass is still reading GitHub.

A milestone uses the number in its URL. Its issues become lanes and its due date appears on
the goal when set.

```json
{
  "version": 1,
  "trackers": [{"provider": "github", "kind": "milestone", "repo": "owner/repo", "number": 7}]
}
```

A parent issue uses its issue number. Its direct sub-issues become lanes.

```json
{
  "version": 1,
  "trackers": [{"provider": "github", "kind": "parent-issue", "repo": "owner/repo", "number": 42}]
}
```

A GitHub project uses its project number. Run
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

- You can put several sources in `trackers` or add it to existing file settings. An issue can
  serve several goals.
- For a project, your stored login needs access to that project and the scope described in
  `gh project --help`.
- Compass uses your stored GitHub CLI login. See
  [what the tracker read sends](../../SECURITY.md#plan-reads-from-github).
- A read with no matching issues says **No lanes found**. When a source is unavailable,
  progress reads **not measured**. Waiting on you still shows the asks and waiting sessions
  Compass has from local records.
- Start Compass with `--no-plan-trackers` to stop these reads for the run. For a plan with just
  GitHub and an event log, use the flag so the local log stays available. Remove `trackers`
  and any top-level `lane_folders` only if the remaining
  settings are valid as a standalone file plan. If the settings contain only GitHub
  sources, remove the settings file to turn off Plan.

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
- For a file plan without GitHub, keep every top-level section from the file example.
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

For GitHub lanes, put `lane_folders` at the top level. Ask your agent to read the lane's
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
| A file entry or label breaks a rule above | Fix the entry in `files`. |
| A tracker table lacks your declared lane, title or status column, or misspells one, such as `Statuz` | Fix the header so the table has all three. |
| Two tracker tables with no blank line between them | Add a blank line. |
| A repository whose Git config includes another file | Remove the include. |
| A repository that borrows another's objects (a shared or reference clone) | Run `git repack -a -d`, then delete `.git/objects/info/alternates`. |

If you use private roots or marker files, keep the parent folders of each listed file present in
the checkout, so Compass can check them.

## Optional: give each new session its lane summary

The summary uses file-based plan data. With the summary on, a Claude Code or Codex session started in a lane's folder begins with that
lane's goal, state and progress in its context.

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
