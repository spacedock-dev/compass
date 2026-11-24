# How Compass works

Compass shows every coding-agent session on your machine in one browser tab. For each session it
tells you what the agent is doing, whether it is waiting on you, and whether its work still matches
the goal you gave it. It works with ten harnesses (the agent tools themselves, such as Claude Code,
Codex and Gemini CLI) by reading the session records they already write.

To try it, install the plugin (see the [README](../README.md#1-how-to-set-up)), then ask your agent to
"open compass" or run `/compass:compass`. The dashboard opens at `http://127.0.0.1:4553/`. To see what
a completed progress check looks like before you run one, choose See an example above the
Sessions list or in Help. Not now hides the invitation above the list.

## Checking whether a session is on track

A session goes off course when an agent's work moves away from what you asked for. It might
change files you wanted left alone, stop short, or say it finished when its own record shows
otherwise. Check progress compares your goal with the messages, tests and commands the session
recorded and the files it wrote.

In the sample session, the agent reported the milestone 97.3% complete and later found a
blocker. The reader then said an issue was still open. Is it on track? shows Slightly off
course. Follow the quotes link to see the entries behind the finding and the record that
contradicts the agent's claim that the build work was done and merged.

![The sample session's Is it on track? card shows Slightly off course, one departure and a link to three quotes.](images/how-it-works-progress-check.png)

In the view-only example, Is it on track? shows the recorded departure. The quotes open Evidence.

```mermaid
flowchart LR
    A["Set a goal<br/>and describe what done looks like"] --> B["Press<br/>Check progress"]
    B --> C{"Did the work<br/>depart from the goal?"}
    C -- "yes" --> D["Read each departure<br/>and the entries it cites"]
    D --> E["Steer back: copy the correction<br/>and paste it into the session"]
    C -- "no, or can't tell" --> F["Read why, and check<br/>again after more work"]
    E --> G["Check progress again"]
```

A check goes like this:

1. Open the Goal card to read the saved goal and what done looks like. Press Edit goal to
   change the words, or Use your prompt to start with a message from the session. The prompt
   picker says when it finds no usable prompts or cannot read them. You can save up to six
   lines describing what done looks like.
2. Press Check progress. This sends the session's content to a model (see
   [what can leave your machine](#what-can-leave-your-machine)).
3. Is it on track? shows On track, Slightly off course, Off course or Way off course when
   the record supports a level. On track means "No departure found in what Compass read".
   If Compass found a departure but has no level, the card shows the finding. Codex checks
   always use that approach for departures. The quotes link counts the entries cited by the
   finding and opens Evidence under Show technical details, with focus on the first available
   quote.
4. When Steer back is available, it opens an editable message based on your goal or a saved
   line describing what done looks like. Use Copy message and paste it into the session
   yourself. Compass never sends it for you.
5. Once a reading is saved, the button reads Check progress again. New work, a changed goal
   or a withdrawn reading can make the card show Out of date. If a newer check fails to produce a
   reading, the card identifies any finding it shows from the earlier check. Uses AI stays
   beside the button. The line "N of 100 daily checks left" appears when 10 or fewer remain.

Read a level as an account of the evidence, not a verdict you can rely on: the reader's accuracy
check has not passed. A citation such as `[41]` lets you see the evidence for yourself. Hover over it
or focus it to read that entry's own words, or choose "See in context of the session" to jump to it in
the session's Activity log.

## A session's page

The session header shows its name, current state and Check progress. At 1100 px and wider,
the header spans both columns. Goal, Is it on track? and What's happened so far are on the left.
Right now, At a glance and Project are on the right. On narrower windows, the cards run in this
order: Goal, Is it on track?, Right now, What's happened so far, At a glance and Project.

- Goal shows your saved goal and what done looks like. How goals work explains what Compass reads.
- Is it on track? shows the progress answer and the actions you can take. It repeats the header's
  Check progress button, so Not checked yet always sits beside the way to check. The two buttons
  are one control: pressing either starts one check, and both wait while it runs.
- Right now shows the latest published activity and helpers. Each helper has a small tile:
  Working while it runs, and State not known once it stops, because no agent records when a
  helper finished. Open the session to see its next step and whether it is blocked. When it
  reports its own end, the current next step and block rows disappear. At a glance shows
  published figures and labels an incomplete entry count "At least".
- Project links to the project and counts its other sessions that were active today, as in
  "2 other sessions today · 1 working".
- What's happened so far starts with Compass's outline, made from the record without a model.
  Codex outlines only your messages. A Claude Code summary adds an opening paragraph and short
  phases. Open one phase at a time. Off course here opens the matching evidence. A flag from an
  earlier check that predates new work says so. A phase shows its earliest cited time once the
  timestamps are available, and Source opens the recorded entry. A legend explains what a tool
  failure in the story means. The card says when source material could not be collected or when a collected
  part could not be summarized. Update summary can continue an interrupted message. Older
  summaries made from excerpts offer Summarize again.

At the foot of the page, Show technical details opens the Activity log. Evidence holds the
check's findings, numbered sources, and reading limits. A citation opens Activity log
and takes you to its entry. The log keeps your filter if it includes the entry and switches
to All if needed. Choose You, Agent, Commands, Files or Cited to narrow the loaded record.
Cited includes entries linked from readings and summaries. The log says how many loaded entries
the filter hides. Entries marked "Before reading window" fall outside the progress check for
your current goal.

On a Claude Code session, open **Show technical details** and select **AI use and privacy** to find the **Live monitor** switch.
It says "Checks progress about once a minute while you watch". With it on, Compass asks
Haiku, through your Claude Code, about once a minute while you view the page where the latest turns
are heading. Its source is labeled Live monitor · Haiku in AI use and privacy. The monitor's own accuracy check has
not been run yet. Until an answer arrives, or while the monitor is paused or has reached its limit,
the card shows an estimate built from the session's checks and file paths. After 20 minutes the
browser asks whether you still want it, and drops that browser holder if nobody answers.
You can also start a terminal holder with `--monitor` or the skill's `monitor on` action. It keeps
checking new work without a tab or a browser question until stopped, its session ends or its
connection is lost. [The manual](../MANUAL.md#starting-and-inspecting-an-instance) owns the commands
and limits. A terminal start can save the page's drafted goal when no goal or outcome lines are
saved; it prints those words and their source before checking.

## What can leave your machine

```mermaid
flowchart LR
    R["Session records<br/>your agents write"] -- "read only" --> S["Compass server<br/>on 127.0.0.1"]
    S --> B["Your browser"]
    S -. "quota reading" .-> V["Your vendor<br/>(login token only)"]
    S -. "model calls" .-> M["Claude Code or Codex CLI<br/>(session content)"]
    S -. "CI checks" .-> G["GitHub or GitLab<br/>(repository and PR number)"]
    S -. "reach nudges" .-> E["An endpoint you configure<br/>(counts only)"]
```

The server reads your agents' session records (transcripts, task files and SQLite databases) without
changing them, and serves the dashboard to your browser. Everything the page loads ships with
Compass, so opening it fetches nothing from the internet. The server listens only on `127.0.0.1`.
`--host 0.0.0.0` exposes it on every network interface with no password; read
[SECURITY.md](../SECURITY.md#scope) first, and prefer an SSH tunnel.

Five kinds of traffic can leave your machine. The quota reading and daily release lookup are on
by default. Three others start from something you do: pressing a button, opening a finished Claude
Code session, turning on the Live monitor, or setting an endpoint URL.

| Traffic | When | What is sent, and to whom | How to stop it |
|---|---|---|---|
| Quota reading | On by default | Your login token to your vendor, so the page can show quota windows. No session content. The Anthropic login covers any harness signed in to the same Claude subscription; Cursor is read on macOS only. | The switch in the page, or `--no-usage` |
| Model calls | When you press a button that needs one, open a finished Claude Code session, or turn on the Live monitor | Session content, through the Claude Code or Codex CLI already on your machine, signed in as you | Pause all AI use, or `--no-observer-model` |
| CI checks | When you press Check progress on a session tied to a pull request (or a GitLab merge request your goal names by its URL, on a host `glab` already knows), in a session whose folder is known | The repository and the pull request number, or the branch name, through your own `gh` or `glab`. The checks it reads go on to the reading model. Where GitHub names the required checks, only those count. | Switch off Read pull request status in Settings, run with `--no-ci-read`, or stop model calls |
| Release lookup | On by default; after server start and at most once per UTC day per Compass home | Only a `compass/<version> (<os>; <arch>[; ci][; internal])` User-Agent beyond urllib's standard headers to spacedock.md, with no query string. The route counts the lookup itself from its headers. The site counts checks in PostHog without an IP and in Plausible with the caller's IP and user agent; CI-marked checks are not counted. Plausible stores neither and derives approximate location from the address. No identifier or session content. | Switch off Look for new versions once a day in Settings, or run with `--no-update-check` |
| Reach nudges | Only after you set an endpoint URL | Counts only, such as how many sessions are waiting on you, to the endpoint you set | Leave the URL unset, or `--no-reach` |

[SECURITY.md](../SECURITY.md#scope) is the full account of all five, and its
[model-call policy](../SECURITY.md#observer-model-calls) says exactly what each model call sends and
how much.

One more path starts from you and is not traffic Compass sends. When you invoke the `compass` skill
with `sessions` or `sessions waiting`, the agent runs that read-only operation and the list it prints
becomes part of that session's context, so it goes to that session's model provider. `drift` and
`drift again` do the same with that session's own progress reading. Like Check progress, they can
spend one reading. The correction stays out of the session. The list covers
every session on the board, in any harness or project, and
[what can reach into a session](../SECURITY.md#what-can-reach-into-a-session) names each field and what
does and does not stop it. The same command run in a terminal outside the session prints to that
terminal only. There `--drift` needs `--session claude:SESSION_ID` (or `codex:THREAD_ID`) and refuses without it, and a
reading it asks for is stored on the session's page alongside readings from Check progress.

### What calls a model

Compass has no model of its own. When it needs one, it runs the Claude Code or Codex CLI already on
your machine.

| What happens | Which CLI |
|---|---|
| You press Check progress | Claude Code for a Claude Code session (Codex if `claude` is not installed), Codex for a Codex session, and Codex first for other harnesses |
| You open a finished Claude Code session, press Summarize or Update summary, or request a summary from the terminal | Claude Code, to write the session summary; a stored terminal read spends nothing |
| You press Find goal | A model reads the prompts you typed to find the session's goal |
| You press Summarize this session under Show technical details on the project page | Codex, to summarize the focused session and up to three active child sessions |
| You turn on the Live monitor on a Claude Code session | Haiku through your Claude Code, about once a minute while you view it or a terminal holder keeps it on |

Compass shows what each kind of call sends and where the first time it runs, and again if the
destination or the kind of content changes. Session summaries run without asking first; the notice
appears beside them.

To stop model calls, press Pause all AI use in the page, run `--pause-model-calls` from a shell or
invoke the skill's `pause` action: it stops all of them, the Live monitor
included, until you press Resume AI use on the page. `--no-observer-model` does the same for a whole run.
Turn off summaries stops session summaries only. Checks that read sessions without a press stay off
unless you start Compass with `--unasked-readings`.

## Finding your way around

Sessions opens first. The header shows how many sessions are Working across the board,
even on a project page.

| Tab | Key | What it shows |
|---|---|---|
| Sessions | `s` | Every session in one list, with active work above recent history. Each row shows the session's state icon and title, a line naming its agent, project and when it started, what it is doing now, and its goal. A session waiting on you shows what it is waiting for. Clicking a goal opens that session at its Goal card. |
| Projects | `p` | Sessions grouped by project. Each project has a page with a briefing and the views Overview, Timeline, Decisions and Usage and alerts. |
| Needs you | `n` | Waiting on you comes first, followed by Worth a look and Ready to wrap up. The badge counts the first two queues. Open What Compass can't see for coverage and its limits. |
| Goal history | none | Search current and older goals by their text or by session title where available. Each goal shows its source and time. Open How long goals are kept for the limits. |
| Settings | none | AI use controls, browser notifications, progress check limits, and what Forget everything deletes and keeps. Changes save as you make them. |
| Help | none | How Compass works, See an example, the icon legend, progress check terms and common questions. |

`Escape` goes back to where you opened a session from. The example opened from Help returns to
Help, and a session opened from a pasted link goes back to Sessions. Below 1100 pixels, Menu opens
the page links inline. Escape closes the open Menu and returns focus to its button. The current
view lives in the URL, so a reload or a pasted link comes back to the same place.

At a glance on Sessions shows what is waiting on you, what is working and what is worth a look.
Waiting on you and Worth a look open Needs you. Working now selects Working and moves focus to
the list. The status tabs are All, Waiting on you, Worth a look, Working, Quiet and Ended. The tabs
and At a glance count the whole loaded board while you filter it.
Search reads titles, goals, prompts and project names. Press `/` to jump to the field.
Open Filters for Project, Agent, Started and Progress check. The level chips are disabled:
Slightly off course, Off course and Way off course. No goal yet finds sessions with a published
absence of a saved goal, including drafts you haven't saved. Filters explains when some sessions
have unpublished goal data.
More filters for power users holds the complete list of choices, including
Last active, Group, Headless and Goal source.
Headless offers Headless and Interactive or unknown. Claude Code and Codex publish headless status;
Codex uses the rollout entrypoint, with `exec` headless and `cli` interactive. Unknown entrypoints and
other harnesses stay under Interactive or unknown. Both options start unselected, so
every session is shown by default. A quiet headless Codex run with a recorded turn stop says
"run finished" and its age on the list and session page. This is a reversible reading of that turn,
and later work withdraws it. When filters hide a waiting session, the result can link to it or
to Needs you. With no search matches, Show everything clears the choices. Show older sessions
reloads without filters and reads the wider collection. How filter counts work sits inside
More filters for power users. The earlier group names the published window, and How session
history works explains what those rows can tell you. If every discovered source fails, search
results and session counts are unavailable.
The [Find sessions design record](design-sessions-search.md) owns the counting rules.

At the top of Sessions, Your AI allowance shows the selected quota window, its published reset
and the amount used. The bar marks how far the window has elapsed when the clock is available.
Open How the AI allowance works for the pace, local reset date and time, and source. Turning off
quota reading stops credential-backed fetches in this browser. Fresh Codex disk readings and
Antigravity receipts can still appear. The [quota policy](../SECURITY.md#usage-quota-reads-the-quota-fetcher)
describes what Compass reads and how to stop it.

A launcher can [declare a parent and assign a group](../HOW_TO_USE.md#nest-a-launched-run-under-its-coordinator).
Linked children follow their visible parent on Sessions and name it with a page link. A waiting
parent gets a second line, `Waiting on child "title"`. Sessions and the session page link it to the
child even when a filter hides the child. An open question takes precedence over the child wait.
A reported session end takes precedence in the state label. If the board still publishes a
question for that session, you can answer it on the session page. Every Sessions row shows a
status tile beside the title, and the tiles line up in one column. The legend names each tile,
including Quiet for an observed turn stop, Ended for a reported session end, and State not known
when the agent reports it is idle but Compass saw no finished turn. A row waiting on a child
shows the tile of its own state when Compass knows it. If scanning cannot see a turn end, the
row also explains that in words. The progress slot on the row is
blank. Open the session page to see the progress reading and any live estimate the session
supports.

A Worth a look flag explains a reported risk or an end with uncommitted work. Use the Worth
a look tab to find those rows. Its count includes only sessions with the flag.

An unmatched declaration says the parent is not on the board and is not linked. Open
a parent to see its linked children and their states, or a child to open its parent. Group labels
stay separate from goals. Inherited labels say "from parent". Inside More filters for power users,
Group by group arranges the rows by label in Right now and the earlier group. Named choices, chips and headings
quote labels; unquoted "No group" means no label.
Filters and grouping last across board refreshes and trips into a session; reloading clears them.

Projects groups its list into Active today and No recent activity. The list and each project's
summary count Working, Waiting on you, Ended and Quiet from
the state shown on each member's row. A parent waiting on its child or an idle session without an
observed turn end contributes to `in no counted state`. Needs you also requires an observed turn
end to count a session as Quiet. Needs you and Sessions spell out elapsed times from the
displayed board update, so a wait ages when the next board arrives.

A quiet Codex rollout can still be working while a shell-capable call has no matching output.
Within an open turn, an unanswered `exec`, `exec_command`, `shell_command` or `write_stdin` reads
`running <tool>` for up to 15 minutes from that call. Each parallel call retires on its own output.
A new turn, a user message, a recorded finish or an interruption clears the pending evidence.
The detail names the tool, not a shell command inferred from the JavaScript an `exec` call runs.
The bounded rollout tail must still contain the call. A process killed mid-call without a recorded
end can read Working until the cap; a process still running after the cap falls back to the usual
activity rules. This is a reading of recorded calls, not a process-liveness check.

A quiet transcript can still be working. For Claude Code, an unanswered tool call in the current
step reads `running <tool>` for up to 15 minutes from that call. Only calls in the newest assistant
message qualify; a later assistant message, a human prompt, compaction, a validated Stop or an
interruption ends that foreground wait. Parallel calls in one assistant message may remain pending
independently.
Injected task notifications, system reminders and hook feedback do not end it.
In headless sessions only, background Agent or Task subagents acknowledged by a tool result in the
current turn with no recorded completion read `waiting on 1 background task` or
`waiting on N background tasks`.
Only these background subagents
can keep Working after the parent's Stop, for up to 15 minutes from the newest qualifying outstanding
launch; a later interruption or new user prompt retires that wait. Background Bash and shell jobs
do not qualify. Interactive sessions and sessions whose entrypoint is unknown keep the usual
activity and Stop rules for background subagents. The two caps are independent. An observed
session end ends both waits, and an input request still takes precedence. After either cap, Compass
falls back to its usual activity and stop rules. This covers long foreground calls and headless
sessions waiting on a background subagent, measured with Claude Code 2.1.322 on macOS. A session
killed mid-tool without an observed end can read Working until the 900-second cap, instead of the
usual 90-second activity window. This is an accepted limit: SIGKILL sent no SessionEnd in
[the ending capture](captures/claude/session-end-2.1.261-macos.jsonl), while every other measured
ending did. The [state reference](../compass/skills/compass/reference/dashboard.md#session-states)
explains the other harnesses.

A project's Usage and alerts view collects delegated work, requests waiting on you and quota
windows. Show technical details on the project page opens the steering controls, workflow stage
conditions, evidence and the read-only terminal. The
[project page design contract](design-next-ui.md#cockpit-reconciliation) records their limits.

## Where to go next

- [What Compass promises](promise-map.md): the five questions Compass answers, and where each answer
  stops.
- [The manual](../MANUAL.md): every command-line option.
- [SECURITY.md](../SECURITY.md): everything that can leave your machine, in full.
- [The skill reference](../compass/skills/compass/SKILL.md): data sources, session states and
  troubleshooting for each harness.
- [The sample session design record](design-sample-session.md): how the view-only sample is built.
