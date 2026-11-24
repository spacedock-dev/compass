# Calm Compass: the board's visual and language system

## Status and scope

The owner settled these redesign decisions on 2026-11-22. This is the design contract for
the four shipping slices, with the reasons and measurements a later change needs. The
[promise map](promise-map.md) describes the shipped behavior. The
[runtime architecture](design-runtime-architecture.md) owns the module map.

## Who the first layer is for

The board reads plainly to someone who does not know Compass's internals, including
non-technical readers. The redesign canvas's Before panel, "The board today reads like
a terminal", records feedback from non-technical users that the board felt "way too
technical". The Sessions toolbar made readers choose among nine filter menus before they
could find a session.
Monospace capitals made headings look like code. The goal box competed with caveats and a
character counter. A reading started with severity, entry numbers and time ranges. Project
stage jargon and raw timestamps on Attention displaced the status a reader came to see.
Settings led with bytes and gave little feedback about what a Save press changed.

Start with the questions people bring to the board. What is working? What needs me? Is the
session on track? Put the state, its plain reason and any action where that question is
answered. Give the evidence and exact values a named place to open.

## Two layers

The first layer has the answer, the next action and the limits the reader needs to interpret
either. It maps to tier 1 of [NUI-19](design-next-ui.md#nui-19-a-caveat-has-three-tiers).
The second layer is the evidence a reader can open on the board, which maps to tier 2. Tier 3
remains in design records. The [dated overlay amendment](design-next-ui.md#amended-2026-11-22-owner-overlay-choices)
specifies how that evidence opens.

Use the same Show technical details control on Session, Project, Projects (for stage
conditions) and Needs you (its per-item Technical details). Its panel gives the relevant
logs, identifiers, AI use and privacy, exact limits or raw evidence. Sessions home, Goal history
and Settings use their own inline explanations for what they show. What Compass can't see stays
visible on the first layer.

## Times and sizes

Write out elapsed units in first-layer text, as in "waiting 6 minutes" and "ended 25 minutes
ago". Use the displayed payload's generated time as the reference. The reader's locale and time
zone determine clock times and short dates. When a timestamp is missing or unusable, leave its
age out. An absolute start or scheduled reset can still use its published date and time.
Needs you uses the formatter for observed times, and Sessions and its terminal listing share
the elapsed spelling.

First-layer sizes use KB or MB on Compass's 1,024-byte scale. What is sent gives its limits in
KB. Exact byte limits belong in technical details and [`SECURITY.md`](../SECURITY.md). The
[`format.ts`](../frontend/src/shell/format.ts) size formatter supplies the board spelling. The
summary disclosure uses the window limit published with its plan or last attempt. Server-authored
disclosure copy follows in DRC-5524.

## Tokens and type

The board is light only. Keep palette roles so another palette could use the same roles later.
These are the colors from the updated style board, measured as foreground or edge against its
actual adjacent color. The [story audit](../frontend/stories/a11y.audit.ts) linearizes each sRGB
channel and divides the lighter luminance plus 0.05 by the darker luminance plus 0.05. The
ratios below use two decimal places. The minimum for normal text is 4.5:1. Required control
and state boundaries clear 3:1 under
[NUI-18](design-next-ui.md#nui-18-one-control-primitive-and-an-inert-control-stays-on-the-page).
The lighter surfaces, dividers and fills can group content decoratively.

| Pair | Foreground or edge | Background | Contrast | Use |
|---|---|---|---|---|
| Card against ground | `#FFFFFF` | `#F4F6F8` | 1.08:1 | Below 3:1. Decorative surface separation under NUI-18. |
| Ink on card | `#1F2933` | `#FFFFFF` | 14.76:1 | Body and control labels. |
| Ink on ground | `#1F2933` | `#F4F6F8` | 13.62:1 | Page text. |
| Quiet ink on card | `#52606D` | `#FFFFFF` | 6.46:1 | Supporting and absence text. |
| Quiet ink on ground | `#52606D` | `#F4F6F8` | 5.96:1 | Supporting and absence text. |
| Compass green on card | `#2F7D5B` | `#FFFFFF` | 4.99:1 | Quiet action text and outlined accent. |
| Compass green on ground | `#2F7D5B` | `#F4F6F8` | 4.61:1 | Quiet action text and focus accent. |
| Primary action text on green | `#FFFFFF` | `#2F7D5B` | 4.99:1 | Filled action. |
| Control border on card | `#7B8794` | `#FFFFFF` | 3.66:1 | Required outline for outlined controls. |
| Control border on ground | `#7B8794` | `#F4F6F8` | 3.38:1 | Required outline on the page ground. |
| Refused control label on muted fill | `#5C6976` | `#EEF1F4` | 4.96:1 | Calm disabled label. |
| Control border on muted fill | `#7B8794` | `#EEF1F4` | 3.23:1 | A refused control keeps its outline. |
| Card border on card | `#E3E7EB` | `#FFFFFF` | 1.24:1 | Below 3:1. Decorative edge under NUI-18. |
| Card border on ground | `#E3E7EB` | `#F4F6F8` | 1.15:1 | Below 3:1. Decorative edge under NUI-18. |
| Row divider on card | `#EEF1F4` | `#FFFFFF` | 1.13:1 | Below 3:1. Decorative edge under NUI-18. |
| Waiting card accent border | `#F6D9A8` | `#FFFFFF` | 1.36:1 | Below 3:1. NUI-18 requires an independent cue for the clickable card. |
| Working glyph on blue tile | `#1D4ED8` | `#E8F0FE` | 5.85:1 | Pulse shape carries state. |
| Waiting glyph on amber tile | `#92400E` | `#FEF3E2` | 6.46:1 | Clock shape carries state. |
| Worth a look flag on card | `#C2410C` | `#FFFFFF` | 5.18:1 | Off-course orange warning glyph and text. |
| Quiet glyph on grey tile | `#3E4C59` | `#EEF1F4` | 7.77:1 | Moon shape carries state. |
| Ended glyph on green tile | `#21573F` | `#E6F2EC` | 7.31:1 | Checkmark shape carries state. |
| State not known glyph on neutral tile | `#52606D` | `#F4F6F8` | 5.96:1 | Dashed circle shape carries state. |
| Working tile fill on card | `#E8F0FE` | `#FFFFFF` | 1.15:1 | Below 3:1. Decorative under NUI-18. The glyph identifies the state. |
| Waiting tile fill on card | `#FEF3E2` | `#FFFFFF` | 1.10:1 | Below 3:1. Decorative under NUI-18. The glyph identifies the state. |
| Quiet tile fill on card | `#EEF1F4` | `#FFFFFF` | 1.13:1 | Below 3:1. Decorative under NUI-18. The glyph identifies the state. |
| Ended tile fill on card | `#E6F2EC` | `#FFFFFF` | 1.15:1 | Below 3:1. Decorative under NUI-18. The glyph identifies the state. |
| State not known tile fill on card | `#F4F6F8` | `#FFFFFF` | 1.08:1 | Below 3:1. Decorative under NUI-18. The glyph identifies the state. |
| On track text on card | `#21573F` | `#FFFFFF` | 8.40:1 | Text inside the green outline. |
| Slightly off course text on card | `#9A3412` | `#FFFFFF` | 7.31:1 | Text inside the orange outline. |
| Off-course orange on card | `#C2410C` | `#FFFFFF` | 5.18:1 | Outlined boundary and filled pill against its surround. |
| Off course text on orange | `#FFFFFF` | `#C2410C` | 5.18:1 | Filled pill. |
| Way off course text on deep orange | `#FFFFFF` | `#7C2D12` | 9.37:1 | Filled pill. |

Blue identifies Working. Orange marks a progress departure or the Worth a look flag. Amber
identifies Waiting on you. Each cue has a word, a shape or both alongside color.

In the read-only terminal, xterm adjusts ANSI foregrounds to at least 4.5:1 on the light
ground. The selection uses the strong boundary color behind white text and remains visible
when the terminal loses focus. Select options show a two-pixel inset focus ring before the
reader commits a choice. The Capacity strip and Console rail use a dark elapsed tick with a
light outline so the marker stays visible on both the filled bar and the empty track.

One bundled variable Inter face supplies the five steps. The style board uses 800 for the
34 px page title, 700 for 24 px section and 18 px card titles, and 400 at 15 px for body
text. Button labels use 600 at 15 px, and the Session page's At a glance numbers use the 24 px
step at 800. Use 13 px for supporting text, tags and badges. It is the floor. Technical details
can use `ui-monospace` for logs, identifiers and commands. Use sentence case on the first
layer. Interactive targets are at least 44 px.

Every button and text field shares one control radius, `--r-control`, 12 px, as the style
board's `.btn` draws it. A button is at least 44 px tall with 18 px either side and 8 px
between a glyph and its words. Cards keep the 16 px radius and status tiles their own. The
Sessions search field and its Filters button share the control radius, so they stay matched.
A checkbox keeps a 4 px corner, because 12 px would round its 16 px box into a radio's circle.

Sentences on the page stop at `--measure`, 540 px, about 72 characters at the body step.
Inside an opened accordion or collapsible panel they span the panel instead: the panel resets
`--measure` to its own width, so the explanation behind How goals work or What is sent fills the
card it opens in. The owner asked for this on 2026-11-24, after testing main, because a capped
panel left the right half of a wide card empty. Popovers draw outside the panel and keep the
cap.

## Status language

A session state describes what the session is doing. A progress word describes evidence read
against the goal. Worth a look is a flag that can coexist with a state.

| Word | Meaning | How it appears |
|---|---|---|
| Working | The session is working. | Pulse tile. |
| Waiting on you | Needs input, has an exact request or reports a workflow gate. | Clock tile. Count a gate-reporting session once. |
| Quiet | The agent finished its turn and is waiting for your next message. | Moon tile on observed quiet state. A scan-only absence does not establish a turn end. |
| Ended | The session reported that it ended. | Checkmark tile. Ended alone carries no claim about success. |
| State not known | The agent reports it is idle, but Compass saw no finished turn, so it cannot say whether it is quiet or stopped. Also shown when no state is published. | Dashed circle on a neutral grey tile. |
| Worth a look | A published at-risk signal or a dirty end. | Orange warning flag with a reason. |

On Sessions, Project and Needs you rows, the tile carries the state with an accessible name, and
every session row draws one of the five tiles. The Session page header keeps the written state. A
second text line keeps **State not published**, **Waiting on child**, or **Read by scanning: no
turn end can be observed here** where the source calls for it. The [dashboard reference](../compass/skills/compass/reference/dashboard.md#session-states)
explains the scanning limit. Helpers are subagents. Declared child sessions retain their own
rows and relationships.

The owner asked on 2026-11-24, after testing main, for Sessions rows to follow the canvas. Under
the title, one quiet line names the harness, the project and how long ago the session started,
as in "Claude · acme/dashboard · started 1 hour 30 minutes ago". An ended row adds "ended 25
minutes ago", and a row with no published start says "start time not published". The Now line
sits under that line and the goal to the right. The Project, Next and Blocked columns and their
header strip are gone. Blocked was exactly a session waiting on you, so the Waiting on you tile
carries it. The row keeps the question it holds, in three lines under the Now line. No state,
icon or legend entry was added.

Later on 2026-11-24 the owner tested that row and asked the list to follow the canvas more
closely, because the rows sat straight on the grey ground and were harder to read. Both groups now
sit in one white card with the 16 px radius and the `--rule` edge. Each group opens with a small
header band: its name in 13 px bold quiet-tile ink and its count on the right. The earlier group
sits under a divider on the `--raise` ground, with How session history works in its band. Rows
are split by `--sunk` hairlines and carry no left-edge stripe, which the style board rules out.
The title is 18 px bold, the descriptor sits 2 px under it and the Now line 8 px under that. The
row is the title's 44 px target, so the title's own box keeps its line height. The goal is a small
bold label over plain ink that underlines on hover and focus, like a row title, because the
affordance rule keeps a resting underline for links inside sentences. The owner also ruled that
a row with no goal shows no "Add a goal" action, though the canvas draws one: the list cannot add
a goal, so the reader opens the row and adds it on the session page. The goal cell says "No goal
yet" in plain 13 px quiet grey text, with no pill, icon or link, and Help's explanation of that
word now says to open the session and add a goal there. The goal source stays in the label, as
[NUI-16](design-next-ui.md#amended-2026-11-24-owner-the-sessions-list-sits-in-one-card) and the
goal-source amendment require. A row says its end and git facts once: an unmeasured git state
and a git line the outcome already states are dropped, and a bare end is left to the tile, the
end age and "Session reported its own end". A dirty end, a known git state and a changed-entry
count stay. The status segments are one segmented control on the `--sunk` track: the chosen
segment is white with a `--line` border, and the others are plain words that clear 4.5:1. A phone
shows them as outlined pills with the chosen one filled. The search box reads "Search by title,
goal or project". The canvas's short ages and row progress pills are not taken: the elapsed
spelling above stands, and the row progress pill waits for a stored departure (the grey absence line
that can stand in its place is the 2026-11-24 note below).

Also on 2026-11-24 the owner found Sessions rows with no tile, their titles shifted left out of
line: 14 Antigravity and 3 Codex sessions reported idle with no recorded turn stop, which reads
as State not published. The owner ruled five tiles. The fifth, **State not known**, is a neutral
grey tile with a Phosphor Bold dashed circle: quiet ink `#52606D` on the page ground `#F4F6F8`,
lighter than Quiet's pair so not knowing never reads as Quiet. A question mark was passed over
because Help already uses it. Its accessible name and tooltip are "State not known". A row whose
state is State not published shows it and keeps its text line. A row waiting on a child shows the
tile of its own state: Working when the session is working, Quiet when it is idle with a recorded
turn stop, and State not known otherwise. Its Waiting on child line stays, and the row's state
word is unchanged, so the terminal parity fixture still reads Waiting on child. The tile sits in a
fixed 44 px column on every row, so titles, descriptors and Now lines line up whatever the tile.
The project page's session rows take the same tiles, and a project whose sessions publish no state
shows State not known on Projects. The Sessions legend and Help list the new tile with its
explanation. The same day the owner asked the list's empty lines to match the calm list: "No exact
session has active evidence right now.", the earlier group's empty line and the filtered-to-nothing
line are plain quiet ink at the 15 px body size, padded as a row inside the list card, with no
hatch, dashed border or tinted box, as the canvas style board draws absences. Later that day the
owner extended this to the whole board; see the
[calm absence note](#absences-are-plain-quiet-ink-across-the-board-2026-11-24).

Later that day the owner rejected the hatched box on Sessions a second time, so no absence inside a
Sessions row or the list draws it. An unknown title, "Title not published", keeps the title's 18 px
size at 600 weight in quiet ink `#52606D`, with no hatch, dashed border, background or inset, and
stays the row's link and 44 px target, so it lines up with every other title. The goal cell's
"Annotations off" is plain 13 px quiet text, as "No goal yet" is. The descriptor's "start time not
published" and the Now line's absence were already plain. The owner also asked for the toolbar to
match the canvas. The search field takes the Filters button's `--r-control` radius token, so the two
always match at the canvas's 12 px once buttons move to that corner. "All sessions" moves to the 24 px, 700 section-title step the canvas and the style
board give it, replacing an 18 px pin that no ruling set. A phone still hides that heading, as
Mobile.dc.html does.

| Progress word | Recorded level |
|---|---|
| On track | None or low. "No departure found in what Compass read". |
| Slightly off course | Medium |
| Off course | High |
| Way off course | Extreme |

The Session header and Is it on track? card can show full levels. The meter and Help explain
all four. The owner allows one progress pill on a Sessions or Project row when a stored reading
found a departure. The Sessions list draws no pill yet; the absence line under a goal is the
[2026-11-24 note](#absence-words-on-a-sessions-row-2026-11-24).
Goal history carries no level. The
[progress amendment](design-reading-a-session.md#amended-2026-11-22-owner-progress-words-by-surface)
specifies the eligible surfaces, including the terminal footer, and the Codex limit.

Use the appropriate absence word in plain grey text. Each has a short explanation available
through contextual help. The absence line and the progress pill occupy the same role on a row.

| Word | Evidence it preserves | Explanation |
|---|---|---|
| No goal yet | No goal typed or adopted. | Open the session and add a goal there to give Compass something to read against. |
| Not checked yet | A goal exists and a progress check has yet to run. | Check progress to ask Compass to read the record against the goal. |
| Too early to tell | Too little recorded evidence, including the live `not_enough` state. | The session has recorded too little for a reading. |
| Can't tell | No departure found and no check shows the goal was done. | What Compass read found no departure and gives too little evidence to say the goal was met. |
| Goal too vague to check | The goal gives too little direction to read against. | Say what should be true when the work is done. |
| Out of date | A stale or withdrawn reading. | The earlier reading no longer describes the evidence Compass can use. |

The [reading sentences](../frontend/src/drift/sentences.ts) distinguish `not_enough`, an
unclear goal, a withdrawn result and a goal-only reading without proof. Keep those reasons
distinct when rendering the new words.

## Glossary

Use one first-layer label for each meaning. Older names in this table identify the
concepts being replaced. The [ruling index](#owner-rulings) records which labels the owner
explicitly settled and where the decisions apply.

The [glossary module](../frontend/src/language/glossary.ts) holds these rows and the labels
the board currently shows. The header, breadcrumb, document title and project tabs share
the displayed labels. In header phrases, `{count}` stands for a number read from the board.
Session titles and IDs also come from the board or the route. Each view adopts the plain
wording when its redesign ships. Route tokens still belong to the router.

| Plain word | Replaces | Technical layer shows | Must stay distinct from | Allowed exceptions |
|---|---|---|---|---|
| Compass | Keeps current label | Application name | A project or session title | The prefix or suffix in a document title |
| Primary | Keeps current label | Accessible name for the main navigation | Project tabs | Accessible navigation label |
| Breadcrumb | Keeps current label | Accessible name for the parent links | Primary navigation | Accessible navigation label |
| Sessions | Keeps current label | Session list and filters | A single Session page | The sessions slug stays |
| Projects | Keeps current label | Projects list and grouping evidence | A single Project page | The projects slug stays |
| Settings | Keeps current label | Saved choices and their owners | A session's own controls | The settings slug stays |
| Session | Keeps current label | Session identity | A reported session title | Crumb when the session cannot be found. The document title may use its ID |
| Project views | Project cockpit views | Accessible group name for the project tab strip | Primary navigation | Accessible tab list label |
| Overview | Now | The project's current evidence | Session activity on the board | Default project tab |
| Timeline | Course | Observed direction changes | A progress level | The course tab slug stays |
| Decisions | Keeps current label | Recorded project decisions | Current state | The decisions tab slug stays |
| Usage and alerts | Console | Project capacity and alerts | Read-only terminal | The console tab slug stays. The terminal moves to technical details |
| Session data not published. | Keeps current label | The session collection is missing | A measured zero | Used after a board arrives without session data |
| Waiting for the first board. | Keeps current label | Initial board read | A measured zero | Used before the first board arrives |
| ● Needs you · | Keeps current label | Published request or block on the open session | The Needs you navigation destination | Browser tab title prefix |
| Title not published | Keeps current label | Missing or identifier-only session title | A session ID or a command-only opening | Session heading, breadcrumb and browser tab title |
| No name: the session opened with a command | Keeps current label | The opening prompt was a harness command | A missing published title | Session heading, breadcrumb and browser tab title |
| Working sessions | Names the pill for assistive technology | Displayed Working state | The event-backed running count | Header status |
| {count} session working | Singular Working count | One session displays Working | Observed subagents | Header pill |
| {count} sessions working | Plural Working count | More than one session displays Working | Observed subagents | Header pill |
| Goal | Intent, Intent and drift | Saved intent, source, revision and lines read | An agent's task or a provisional prompt | The `intent` slug and technical names keep their spelling |
| What "done" looks like | Expected outcome (optional) | An outcome line and its evidence | The goal itself or proof of completion | Technical fields retain their names |
| Goal history | Intent log | Saved goal revisions and source | A session's current progress | The `#n=intent` fragment survives |
| Check progress | Analyze drift | Drift, read scope and result | Live monitor, tests and builds | Existing CLI flags and skill actions |
| Check progress again | Analyze again, Check again | Prior reading and its recency | The first check or an Out of date state | Same label for a current or stale prior reading |
| Progress check | Drift check | The reading and evidence | Tests and builds run by the agent | Terminal flag `--drift` |
| Progress records | Drift filter | Recorded checks and departures | Progress levels | Sessions filters |
| Departure recorded | Drift recorded | A recorded departure from the goal | A progress level or a generic risk | The saved filter value remains `recorded` |
| This reading looks wrong | Mark as inaccurate | The marked reading and what the mark changed | Editing the goal | Undo is still offered |
| Update my goal instead | Update intent instead | The goal revision | Marking the reading wrong | Opens Goal in edit mode |
| Dismiss | No standalone attention-row control | Server dismissal record | Mark as read | Survives Forget |
| Mark as read | No standalone control | Server dismissal record | Dismiss | Survives Forget |
| Steer back | Keeps current label | Editable correction and its evidence | Editing the goal | Compass never sends the correction |
| Use your prompt | Keeps current label | Saved prompts in this session | Editing the goal directly | Stays visible in read mode |
| Edit goal | Direct editing in the goal field | Goal draft and revision | Adopting a saved prompt | Beside Use your prompt |
| Your data | No dedicated Settings section | Data kept and settings reset by Forget | AI use settings | The Forget explanation opens here in Settings |
| Where it went off course | Departure · Goal | Departure, supporting evidence and citations | A warning signal or a proposed correction | Data token `departure` stays |
| Helpers | Subagents | Recorded subagent activity | Declared child sessions | Technical language may say subagents |
| Agent | Harness | Harness identity | A particular session | Technical language may say harness |
| Needs you | Attention | Published request, gate and evidence | Waiting on you, the state and section | `attention` slug and `n` shortcut |
| Working | WORKING | The source-backed working state | Right now membership | Working now is the card label |
| Waiting on you | Needs input, Needs you now | The exact request or gate | Needs you, the navigation destination | Gate detail appears on the session page and in Needs you |
| Quiet | Idle | The observed turn-end state | Ended or a scan-only absence | Projects uses No recent activity |
| Ended | Finished, Finished cleanly | End evidence and any observed outcome | A turn end or proof of success | Ready to wrap up requires a clean end |
| Worth a look | At risk | The underlying warning or end evidence | A session state or progress level | Shows as a flag on a state |
| Ready to wrap up | Close the loop | The observed end and outcome | Worth a look | Needs you badge excludes this section |
| On track | None or low | `none_or_low` | Proof of completion or Can't tell | Session card and header, with meter and Help explaining it |
| Slightly off course | Medium | `medium` | Off course or a live estimate on a row | Row pill requires a stored departure |
| Off course | High | `high` | A generic risk signal | Row pill requires a stored departure |
| Way off course | Extreme | `extreme` | A dirty end | Row pill requires a stored departure |
| No goal yet | Generic Not checked | Goal availability | Not checked yet | Also a Progress check filter chip |
| Not checked yet | Generic Not checked | No check recorded | No goal yet or Out of date | Plain text |
| No goal and no prompt | No goal yet (Goal source chip) | No saved goal and nothing to draft one from | No goal yet | Goal source filter chip only |
| Saved goal unavailable | No goal yet over an unreadable store | The annotation store or this session entry cannot be read | No goal yet | Plain text. Goal history says it too |
| Too early to tell | Not enough recorded yet | `not_enough` and the evidence floor | Can't tell | Plain text |
| Can't tell | Goal-only reading with no level | Missing proof that the goal was met | On track | Plain text |
| Goal too vague to check | Goal too vague to analyze against | Reading refusal and reason | Too early to tell | Plain text |
| Out of date | Stale or withdrawn reading | Why the prior reading is stale or withdrawn | Never checked | Rerun still reads Check progress again |
| Pause all AI use | Pause model calls | Shared server pause state | The Summaries switch or Live monitor | `--pause-model-calls` and skill action `pause` |
| Resume AI use | Resume model calls | Shared server pause state | Starting a check, summary or monitor | Existing terminal flags |
| Live monitor | Live monitor (kept) | Live monitor · Haiku, scope and cadence | A reader-requested check | Session's technical layer. Settings points there |
| Your AI allowance | Capacity | Provider plan quota and measurement | Daily progress-check cap or prompt size limit | Allowance refers only to this plan quota |
| How much a progress check reads | Estimated prompt allowances | Prompt size limits and exact bytes | Your AI allowance | Behind Customize. Slider labels name what they cap in KB |
| Uses AI | Cost implied by Analyze | The destination, what is sent and its limits | Number of remaining checks | Always beside Check progress |
| N of 100 daily checks left | Budget count | Rolling cap and when capacity returns | Plan quota | Show at 10 or fewer checks left |
| How goals work | How Intent and drift works | Goal sources, adoption and revisions | A separate Help-only explainer | Open in place from Goal. Help links there |
| How filter counts work | How these counts work | Filter option counts and board-wide counts | The count of rows shown | Opens beneath the filters |
| How session history works | What recent means | The published window and what recently observed means | Whether a harness process is still open | Opens above the earlier rows |
| How progress checks work | Drift explainer | What the reading can and cannot establish | A verdict or account of completed work | Keep the local explanation next to the reading |
| How project grouping works | Project grouping explanation | Project evidence and folder identity | Session state or agent type | Explains Unnamed folder |
| How the AI allowance works | Quota explainer | Provider reading, pace and measurement limits | How much a progress check reads | Help and the plan quota card use the same subject |
| Help | New destination | Links to the canonical explanations | A second Goal explainer | Last in the primary navigation |
| Project | Keeps current label | Project identity | The Projects destination | Project names come from the board |
| Working now | Active now | Count of sessions in the Working state | Sessions in the Right now group | Uses the same Working count as the header |
| Nothing working right now | Running count at zero | Measured Working count of zero | No published board | Header only after the board is read |
| What Compass can't see | Also at risk, off the session count | Board-level coverage limits | A session count | Stays visible on the first layer |
| Is it on track? | Drift | Reading evidence and scope | Whether work is complete | Session progress card |
| Right now | Active now | Published current work and coming-next signals | Count of sessions in the Working state | On Sessions the earlier group names its time window |
| What's happened so far | Session activity and summary areas | Session history and sources | A goal verdict | Session page section |
| At a glance | Session facts spread across the page | Published session facts | What the session intends to do | Section title on the Session page |
| All | Unfiltered Sessions list | Published Sessions population | Working sessions alone | First Sessions tab |
| Active today | Active | Evidence of recent project activity | A session's Working state | Projects group |
| No recent activity | Recently observed | Published project activity history | The Quiet session state | Projects group |
| State not known | Blank tile slot | An idle report with no recorded turn end, or no published state | The Quiet session state | Neutral grey tile with a dashed circle |
| State not published | Keeps current label | The missing state field | The Quiet session state | Text line beside the State not known tile |
| Waiting on child | Keeps current label | The reported child and relationship | Waiting on you | Text line; the tile shows the session's own state |
| Read by scanning: no turn end can be observed here | Keeps current label | Collector scope | The Quiet session state | Text only |
| Show technical details | Separate technical controls | Activity log, AI use, limits and raw evidence | What Compass can't see | Opens in place on the surfaces with technical evidence |
| Hide technical details | Keeps the same subject as Show technical details | Closes the inline disclosure | Other collapsible sections | Only while the layer is open |
| Activity log | Full activity | Session record | Session summary | Names the technical tab and citation destination |
| AI use | Separate model and quota controls | Model and quota settings | The AI allowance | Names the Settings section |
| AI use and privacy | Separate model controls and disclosures | Model settings and what is sent | The AI allowance | Names the Session technical tab |
| Read pull request status | Turn off the pull request read | Account-wide GitHub and GitLab check reads | An individual recorded pull request read | The flag and route stay |
| Show my AI allowance | No dedicated Settings section | Browser-stored usage consent | An account setting | Labelled as kept in this browser |
| Customize | Always-visible prompt limits | Prompt size controls | Your AI allowance | Opens How much a progress check reads |

Check means a Compass progress check on the first layer. Use "tests and builds" for the
agent's own runs. Allowance belongs to the plan quota. The
[language reach ruling](#drc-5503-owner-ruling-2026-11-22) governs how the board's words
reach other reader surfaces and which contracts keep their names.

## Icons

Use the shared entry point in [ui/icons.tsx](../frontend/src/ui/icons.tsx) and Phosphor Bold
for the state and warning shapes. The Sessions legend names Working, Waiting on you, Quiet,
Ended and the Worth a look flag. Quiet uses Moon. Give icon tiles their state names for
assistive technology. A tooltip may echo a name that already appears in a visible legend.
Absence words have no icon. [NUI-12](design-next-ui.md#nui-12-motion-means-observed-activity-not-mere-attention)
still governs motion.

[DRC-5527](design-shadcn-adoption.md#icons-and-tooltips) records the icon names, weight
and import boundary. The [Calm Compass story](../frontend/stories/CalmCompass.stories.tsx)
keeps the swatches, contrast figures, type, radii, terminology and available components together.
Its reserved Switch example will be filled by the shared control.

## Overlay rule

| Placement | Use |
|---|---|
| Inline | Default for disclosures, including phone Menu and Filters. Keep open state in the disclosure store. |
| Popover | An anchored choice list or a short companion in a flex row. It opens vertically, closes siblings and has no nested popovers. |
| In-card panel | Technical details, customization or a scoped explanation such as Forget in Your data. |
| Dialog | Reserved for an irreversible action wider than its card. The redesign ships with zero dialogs. A future dialog owns focus and Escape until it closes. |
| Page | A destination with its own context, such as Help or a session opened from a list. |

Use the shared disclosures in place of native details menus. The
[overlay ruling](#drc-5497-owner-ruling-2026-11-22) and
[Switch amendment](design-shadcn-adoption.md#amended-2026-11-22-owner-switches-for-boolean-settings)
record the control decisions.

## Affordances

Use a filled green primary action, a bordered secondary action and a quiet text action,
for example Check progress, Edit goal and Not now. A control that cannot be pressed rests calm:
a muted fill, its outline kept and muted ink, never a hatch or a dashed edge. The style board
uses 16 px card radius,
a 1 px decorative border and 24 px padding, with a flat edge in place of stripes or deep
shadows. The shared Button also provides outlined and filled danger actions. Keyboard focus adds
a 2 px Compass green outline with a 2 px offset. Sessions row titles underline on hover and
keyboard focus. Links in sentences keep their underline. Session citations and the link in their
preview use the shared ring and 44 px targets. The shared Card rests flat. Both summary cards use
Inter and share a border and hairline shadow on hover. The link says "Open in Needs you" with an
arrow. The filter says "Show in the list below", names the list it controls and exposes whether
the filter is pressed. The green-tinted New to Compass invitation links to the view-only sample
and tells readers they can see a session's goal and the results of progress checks there.

Settings uses switches for boolean preferences and stepped sliders for limits. A slider
saves on release and a refusal restores that slider's previous value. The
[Settings ruling](#drc-5494-owner-ruling-2026-11-22) specifies ownership and persistence.
Your data opens the Forget explanation inline, with a Copy button for the stop-then-forget
commands. The terminal command does the reset. The explanation says deletion cannot be undone
and traces the lists to the [reset implementation](../compass/skills/compass/compass_runtime/cli.py)
and the `--forget` row in [History and annotations](../MANUAL.md#history-and-annotations).
The command clears observation history, recorded session ends, parent declarations, session summaries, copied
correction digests and annotation discard records. It keeps typed goals and group labels,
readings, dismissals, read choices and spend guards. It sets AI use to paused and summaries
to off. Goal history explains that typed goals and readings survive.

### Buttons and the calm disabled look, 2026-11-24

The owner compared the live Session page with the canvas on 2026-11-24 and asked for buttons
with "more border radius" and a "stronger" font weight. Buttons now take the canvas `.btn`: the
12 px `--r-control` radius (it was 4 px, with emphasized buttons on the 10 px card radius), a
600-weight label and 18 px side padding. The change is in the shared Button and its token, so
every page takes it, text fields and popovers included. The owner has also rejected the hatched,
dashed box for a control that cannot be pressed, on several surfaces that day. A refused button
now draws the muted `--sunk` fill, the solid `--line` outline at 3.23:1 against that fill and
`--ink3` text at 4.96:1. It stays in the tab order with `aria-disabled` where it did before and
keeps the sentence that says why. A busy button is unchanged: it keeps its own fill and spinner.
[NUI-18](design-next-ui.md#amended-2026-11-24-owner-a-refused-control-rests-calm) records the
amendment to "disabled is dashed".

### Absences are plain quiet ink across the board, 2026-11-24

The owner asked for the hatched absence box to go everywhere, not just on Sessions. The shared
`.next-absence` rule, in both stylesheets that carry it, now draws only quiet ink `#52606D`
(`--ink-absence`): no hatch, no dashed border, no background. That covers the board-status lines
("The first payload has not arrived yet.", "No data has been received in this tab.", "The board
published no session collection.", "This session is not in the current payload.", "Not present in
the current payload."), the three on Needs you, Settings while it reads or fails to read its
limits, the project console's "This project is not in the current payload." and the project
`Absence` part that Needs you, the observer controls and the terminal surface use. A view-level
absence keeps the body size and its top margin but drops the 10 by 12 px inset, which only made
sense inside a box, so its words start where the heading above them does; inside an empty project
or session card it keeps its bottom margin only. The text measures 6.46:1 on a card and 5.96:1 on
the page ground, as plain text, so the story audit no longer special-cases a hatched background,
and the `--hatch` token and its pins are gone. Refused status segments and filter options take the
calm refused look of the shared Button above. No hatch is left on the first layer. Three dashed
edges remain, none of them an absence: the switch track when a switch cannot be changed, the Add a
line control in the Goal editor, and the rule beside a defined term in the session summary. The
owner has not asked about them.

### Absence words on a Sessions row, 2026-11-24

A Sessions row draws one plain grey line at the foot of its Goal cell, or none. It is 13 px quiet
ink with no pill, border, background or icon, and it offers no action. Only words the row's own
published data proves ship:

- **No goal yet** reads on a draft row, where the Goal cell shows an unsaved prompt. Where the cell
  already says No goal yet, the line is not repeated.
- **Not checked yet** reads on a non-Codex row that has saved words (a goal or outcome lines) and
  nothing recording a check: no stored reading, refusal, withheld reading, press, unasked check or
  raised departure, and a reading route for its harness. A row whose unasked check found nothing
  says nothing, because it was checked.
- **Saved goal unavailable** replaces the Goal cell when the annotation store, or this session's own
  entry, cannot be read. The row never says No goal yet or offers a prompt as the goal over words
  that exist. A newer build's entry is detected from the read the board already makes
  (`annotation_goal_unreadable`, a bool that names no text and enters no history).

Left off the row, and why: Too early to tell and Can't tell need the analysis level, which reads
transcript evidence on every poll, so a row cannot prove them. Goal too vague to check and Out of
date need a freshness record the stored-departure pill issue builds, because the session page says
Out of date before it. A refused or withheld reading is a failed check, not "nothing departs", so
it shows nothing. A Codex row and a live-estimate row show nothing. A Live monitor lease held by
another tab or the terminal can hold a live estimate the list cannot see; that gap is recorded,
not closed, and adds no field.

The Progress check "No goal yet" chip and the row read one predicate (`noGoalYet` in `rows.ts`).
The Goal source chip is narrower, because its drafted rows are a sibling option, so it is named
**No goal and no prompt** and the two no longer read alike. `--sessions` prints the same line.

### The Session page follows the canvas, 2026-11-24

Five more changes came from the same comparison.

- **Check progress is filled wherever it can be pressed.** The header's button had dropped to
  the outlined weight while a later direction was unsettled, and Check progress again was
  always outlined. Both are now the green primary with white text whenever a press can run,
  as the canvas draws them. A refused press takes the calm refused look above.
- **Is it on track? has its own Check progress.** A goal with no check said Not checked yet and
  offered no way to check. The card now draws the header's button: Check progress before any
  reading, Check progress again after one, with the same Uses AI note. It is the same component
  with the same board, refusals, daily cap, pause and pending key, so it shows exactly when the
  header's does, and pressing either leaves both busy, then both inert while the check runs. The
  card's copy is primary only before a reading and when the card has no other primary: a later
  direction's question, Steer back and a raise for a waiting session keep theirs. The canvas
  draws no button in the card; the owner asked for it. It sits 16 px below the explanation above it
  and 16 px above the next line, the room the canvas gives the card's button rows, because 4 px
  read as cramped (owner, 2026-11-24).
- **What's happened so far keeps a fixed time column.** Each phase's time sits in a 5 rem column
  (4.25 rem on a phone) that stays empty when the phase has no time, so every title starts at the
  same place, as the canvas draws the list. An automatic column had moved each title by its
  time's width and put an untimed title at the card's left edge (owner, 2026-11-24).
- **Your AI allowance leads Sessions.** The card moved from the foot of the page to the top, under
  the example invite and above the greeting, so a reader sees how much AI use is left before the
  sessions (owner, 2026-11-24).
- **Helpers in Right now have tiles.** Each helper has the 28 px tile from the canvas, the shared
  StatusTile at its small size, named for screen readers and not a tab stop. A helper publishes
  only whether it is running. Running gets Working. The canvas draws Ended for a finished
  helper, but no harness records a helper's finish, so a helper that stopped gets State not
  known and keeps the words Not running or Activity not published beside it, under the honesty
  rules. Working says itself, so its row keeps only the elapsed time.
- **At a glance numbers lead.** The values use the 24 px step at 800. The canvas draws 24 px at
  800; the type-step ruling keeps the five steps, so no 26 px step was added.
- **Project counts the project's other sessions today.** Under the project link a quiet 13 px line
  reads "2 other sessions today · 1 working", counted from the board's rows for the same project,
  leaving this session out. Today is the Projects group's Active today rule: Working, Waiting on
  you, or a reported end on the board's calendar day. One session is singular. The working clause
  is left out at zero, and the whole line when no other session was active today. The gap under
  the Project heading is 8 px, as the canvas draws it.

## Contextual help

Help is the last navigation item. A reader can also see an explanation where a number,
reading or source limit needs one. Name that link "How <subject> works" and define the
subject in the glossary. The Goal card opens its one explainer in place and Help links to
it. Keep the reason that qualifies a first-layer answer in view. The optional explanation
can show the underlying evidence and exact units. What is sent keeps its destination and
scope, using KB for first-layer sizes and exact bytes in technical details and
[SECURITY.md](../SECURITY.md).

## Accessibility floor

The [Calm Compass Storybook guide](../frontend/stories/CalmCompass.stories.tsx) uses live
palette and type tokens and the shared Button and Card. Its labelled sections give the
remaining examples a place to land as their components ship.

Use the measured text and boundary pairs above. Preserve visible focus, keyboard operation
and reading order, including at phone widths. Labels, shapes and the visible legend carry
the meaning independently of color. Keep the 44 px target size when a glyph, a tag or a short
link looks smaller. Prove the accessible name and actual action in Storybook. The
[story audit](../frontend/stories/a11y.audit.ts) measures contrast and catches overflow and
clipping in rendered stories. Follow [NUI-18](design-next-ui.md#nui-18-one-control-primitive-and-an-inert-control-stays-on-the-page)
for the shared action hierarchy and inert controls.

## Honesty rules

Follow [DEC-27](design-reading-a-session.md#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result)
and its dated amendments. A plain word carries the same evidence floor as the technical
word. An estimate on a Session page identifies its source. A row's progress pill requires
a stored departure. An unavailable reading leaves its reason in view. What Compass can't
see names the coverage limit. Use the published state, the observed end and the source's
own timestamps, retaining each absence separately. A board refresh cannot turn absence
into a reassuring state.

Keep the population of each count visible in its wording. The header pill and Working now
card count Working sessions. The Needs you badge counts Waiting on you plus Worth a look
from the rows that render. Worth a look uses published risks and dirty ends. A reading
against the goal supplies no attention count. The shared selector reads the evidence across copies
of the same session and gives a waiting session one place in the badge. A waiting session with a
dirty end keeps one plain outcome on the row. A clean git probe at end leaves independent risks in
Worth a look. The dirty-end reason names changed git entries when the board has a count. The selector flags measured
members of a shared-label collision. Worth a look also receives quota notices with their harness and
window, outside the session count. Checkout warnings retain their measured members at board scope
alongside location gaps. If all discovered session sources fail and supply no rows, the session
counts are unavailable. The [Sessions counters amendment](design-next-ui.md#amended-2026-11-22-owner-sessions-counters)
bounds the change to NUI-16. The terminal follows the same terms when its slice lands.

## Rejected alternatives

1. The terminal-like first layer put monospace capitals, a dark ground and tool vocabulary
   ahead of the answer. Its density made source details and reader actions compete. Put the
   evidence one step below and keep the evidence limits in sight.
2. A text state pill beside a progress pill gave one row two competing status labels. Use a
   named state tile and reserve the pill for a stored progress departure.
3. A single Not checked label hid several different reasons for withholding a reading.
   Use the six absence words with their reasons.
4. The reset dialog and its Done state implied the board would execute Forget. The owner
   chose the inline explanation with the existing terminal command.

## Open questions

**Projects grouping proposal, 2026-11-23.** A project belongs to Active today when a session is
Waiting on you or Working, or has a reported end on the displayed board's local calendar day.
The other projects appear under No recent activity. An absent end time supplies no evidence for
Active today. The grouping rule is awaiting owner review in Storybook.

The Needs you rename is closed. The Projects rule that distinguishes Active today from
No recent activity still needs sign-off on the grouping logic in Storybook. The pending
builder proposal starts with observed waiting or working activity and adds a window for
projects that ended today. The two group labels and the three project-list shapes are
settled independently. The direction question's presentation also goes to Storybook for
sign-off. Its controls and placement are settled.

Sign-off works the same way for every redesign layer. The owner set this policy on
2026-11-22, when the build started. The coordinator checks each layer's stories and play
assertions against the canvas After images and the rulings above, with a browser walk and
two review lenses plus an arbiter, and lands the layer once it passes. Nothing reaches a user
until the owner tags a release, and the owner reviews main in Storybook before each tag.

## How it is enforced

The plugin validator checks repository links and heading anchors. The documentation module
checks the runtime's decision citations and pins the active public wording. The
[glossary test](../frontend/src/language/glossary.test.ts) compares all five columns with the
module in row order. The style guide shows the plain words beside the words they replace.
Later slices use this record's terms in their component and view stories. A play assertion demonstrates
what the reader sees and does, including cases where the data is absent. Use synthetic data
or the anonymized Sample session for those proofs and follow the
[frontend migration record](design-frontend-migration.md) when an asking test's wording
departs from a recorded answer.

### First-layer checks

The [style policy](../frontend/build/style-policy.mjs) counts monospace, uppercase and tracking
per source file. It recognizes equivalent font-family declarations in CSS and Tailwind utilities.
The [budget](../frontend/first-layer-budget.json) records the actual counts and gives a reason
for each file where technical work can add monospace. Other counts can fall against the PR base.
The first comparison reads the base sources when the budget is absent. The string scan includes
class recipes and conditionals, so it also counts a literal such as `uppercase` when that
word appears as a separate token in a prose string. Inline SVG belongs in the shared UI directory.

The [Storybook audit](../frontend/stories/calm.audit.ts) checks computed monospace, uppercase
transforms and tracking above 0.04 em on visible first-layer text and placeholders. The
wording check reads adjacent inline text together, looking for all-capital labels, raw epochs,
hex identifiers and bracketed citations. Acronyms such as AI and KB may stay capitalized.
Published words such as a session title, held question or task subject keep their wording.
Typography still applies to them and to the earlier labels quoted in the style guide. A
technical area is outside the text audit. Visible, enabled
control borders must reach 3:1 against the painted surround, including any control fill painted
under a translucent edge.

The initial budget lists measured failures from stories that end on legacy views or components.
During bootstrap, only stories already in the base can qualify. After that, the base budget
sets the allowed list. As each view is converted, remove its passing stories from the list.
Sessions has no technical disclosure. An ID search can find its session without printing
the matched ID on the row.

## Owner rulings

The canvas rows summarize the resolved comments. The dated entries quote the decision
comments supplied for this layer. Read a base decision with its linked follow-ups. Later
rulings govern where they change an earlier decision.

| Source | Decision | Record |
|---|---|---|
| Canvas comment 1 | Waiting on you is the session state and section. | [State words](#drc-5482-owner-ruling-2026-11-22) |
| Canvas comment 2 | A status icon tile and one text pill. The conditional progress pill is the one text pill. | [Row follow-up](#drc-5482-owner-follow-up-rulings-2026-11-22) |
| Canvas comment 3 | Review Projects in three shapes: one project, many small projects, and many projects with one busy one. | [Projects groups](#drc-5482-owner-follow-up-rulings-2026-11-22), [single-project route](#drc-5500-owner-ruling-2026-11-22) |
| Canvas comment 4 | Put the working pill on every page. | [Working counts](#drc-5485-owner-ruling-2026-11-22) |
| Canvas comment 5 | Surface Worth a look as a flag, with its own card and filter. | [Published risks](#drc-5485-owner-ruling-2026-11-22) |
| Canvas comment 6 | Clickable cards say where they go. | [Affordances](#affordances) |
| Canvas comment 7 | Put stepped sliders in the card. | [Save on release](#drc-5494-owner-ruling-2026-11-22) |
| Canvas comment 8 | Put Help last in the navigation. | [Help route](#drc-5500-owner-ruling-2026-11-22) |
| Canvas comment 9 | Forget asks first. The chosen board flow is the inline reset explanation. | [Forget ruling](#drc-5488-owner-ruling-2026-11-22) |
| [DRC-5473](https://linear.app/recce/issue/DRC-5473) | Light theme, Inter and accessibility floors. | [Owner ruling, 2026-11-22](#drc-5473-owner-ruling-2026-11-22) |
| [DRC-5476](https://linear.app/recce/issue/DRC-5476) | Terminal footer and filter chips. | [Owner follow-up rulings, 2026-11-22 (fourth round)](#drc-5476-owner-follow-up-rulings-2026-11-22-fourth-round) |
| [DRC-5476](https://linear.app/recce/issue/DRC-5476) | Progress words, absence and evidence. | [Owner ruling, 2026-11-22](#drc-5476-owner-ruling-2026-11-22) |
| [DRC-5479](https://linear.app/recce/issue/DRC-5479) | One label for reruns. | [Owner follow-up ruling, 2026-11-22 (third round)](#drc-5479-owner-follow-up-ruling-2026-11-22-third-round) |
| [DRC-5479](https://linear.app/recce/issue/DRC-5479) | The Settings limits section. | [Owner follow-up ruling, 2026-11-22](#drc-5479-owner-follow-up-ruling-2026-11-22) |
| [DRC-5479](https://linear.app/recce/issue/DRC-5479) | Goal, progress, AI and monitor names. | [Owner ruling, 2026-11-22](#drc-5479-owner-ruling-2026-11-22) |
| [DRC-5482](https://linear.app/recce/issue/DRC-5482) | Quiet icon, absence text, legend and tab order. | [Owner follow-up rulings, 2026-11-22 (third round)](#drc-5482-owner-follow-up-rulings-2026-11-22-third-round) |
| [DRC-5482](https://linear.app/recce/issue/DRC-5482) | Progress pill and Projects group labels. | [Owner follow-up rulings, 2026-11-22](#drc-5482-owner-follow-up-rulings-2026-11-22) |
| [DRC-5482](https://linear.app/recce/issue/DRC-5482) | Session states and icon placement. | [Owner ruling, 2026-11-22](#drc-5482-owner-ruling-2026-11-22) |
| [DRC-5485](https://linear.app/recce/issue/DRC-5485) | Gate sessions count once as Waiting on you. | [Owner follow-up ruling, 2026-11-22](#drc-5485-owner-follow-up-ruling-2026-11-22) |
| [DRC-5485](https://linear.app/recce/issue/DRC-5485) | Needs you sections and Working counts. | [Owner ruling, 2026-11-22](#drc-5485-owner-ruling-2026-11-22) |
| [DRC-5488](https://linear.app/recce/issue/DRC-5488) | Forget explanation and retention. | [Owner ruling, 2026-11-22](#drc-5488-owner-ruling-2026-11-22) |
| [DRC-5491](https://linear.app/recce/issue/DRC-5491) | The header spans both columns. | [Owner follow-up ruling, 2026-11-22 (fourth round)](#drc-5491-owner-follow-up-ruling-2026-11-22-fourth-round) |
| [DRC-5491](https://linear.app/recce/issue/DRC-5491) | The 1100 px breakpoint and narrow order. | [Owner follow-up ruling, 2026-11-22](#drc-5491-owner-follow-up-ruling-2026-11-22) |
| [DRC-5491](https://linear.app/recce/issue/DRC-5491) | Session layout, correction and direction. | [Owner ruling, 2026-11-22](#drc-5491-owner-ruling-2026-11-22) |
| [DRC-5494](https://linear.app/recce/issue/DRC-5494) | Summaries stays nested and reads as paused. | [Owner follow-up ruling, 2026-11-22 (fourth round)](#drc-5494-owner-follow-up-ruling-2026-11-22-fourth-round) |
| [DRC-5494](https://linear.app/recce/issue/DRC-5494) | One pause switch in two places. | [Owner follow-up ruling, 2026-11-22](#drc-5494-owner-follow-up-ruling-2026-11-22) |
| [DRC-5494](https://linear.app/recce/issue/DRC-5494) | Settings slider values and switch ownership. | [Owner ruling, 2026-11-22](#drc-5494-owner-ruling-2026-11-22) |
| [DRC-5497](https://linear.app/recce/issue/DRC-5497) | Disclosure choices and technical details. | [Owner ruling, 2026-11-22](#drc-5497-owner-ruling-2026-11-22) |
| [DRC-5500](https://linear.app/recce/issue/DRC-5500) | Needs you keeps its name. | [Owner follow-up ruling, 2026-11-22](#drc-5500-owner-follow-up-ruling-2026-11-22) |
| [DRC-5500](https://linear.app/recce/issue/DRC-5500) | Routes, shortcuts and moves. | [Owner ruling, 2026-11-22](#drc-5500-owner-ruling-2026-11-22) |
| [DRC-5503](https://linear.app/recce/issue/DRC-5503) | Terminal, notification and disclosure exceptions. | [Owner follow-up rulings, 2026-11-22](#drc-5503-owner-follow-up-rulings-2026-11-22) |
| [DRC-5503](https://linear.app/recce/issue/DRC-5503) | Where the glossary applies. | [Owner ruling, 2026-11-22](#drc-5503-owner-ruling-2026-11-22) |
| [DRC-5506](https://linear.app/recce/issue/DRC-5506) | Remove the 26 real-data captures from main. | [Owner ruling, 2026-11-22](#drc-5506-owner-ruling-2026-11-22) |
| [DRC-5531](https://linear.app/recce/issue/DRC-5531) | Ship four whole slices and keep fix releases moving. | [Owner ruling, 2026-11-22](#drc-5531-owner-ruling-2026-11-22) |

### DRC-5473 Owner ruling, 2026-11-22

> * Theme: light only. Token roles stay, so a dark palette can be pointed at them later. NUI-2 is amended: `css.test.ts` flips to require light, and `shell.css`, CONTRIBUTING and `dashboard.md` change with it.
> * Typefaces: Inter only, as one variable face. IBM Plex Mono is dropped, which frees about 169 KB of page. Monospace appears only in technical details, through `ui-monospace`. DRC-5518 measures the bytes Inter needs and raises PAGE_MAX_BYTES once, with that measurement, if the freed space is not enough.
> * Control borders are darkened to reach 3:1, about #7B8794 (3.66:1 on white). NUI-18 stays as it is.
> * Floors stay: the five type steps (13, 15, 18, 24 and 34 px), the 13 px floor and 44 px targets. Badges and tags use 13 px.

### DRC-5476 Owner follow-up rulings, 2026-11-22 (fourth round)

> * **The terminal's status-line footer** follows the row rule. It names a level only from a stored reading that found a departure (Slightly off course or worse). Otherwise it shows a ruled absence word, or nothing. It may still say the Live monitor is on.
> * **The Sessions Filters panel's Progress check chips** are Slightly off course, Off course, Way off course and No goal yet. No chip shows a count (DEC-20).

### DRC-5476 Owner ruling, 2026-11-22

> * DEC-17 rule 4, DEC-20 item 3 and DEC-26 items 3 and 6 stay as they are.
>   * A Sessions or Project row shows a progress pill only for a stored reading that found a departure (Slightly off course or worse).
>   * A live estimate never names a level on a row.
>   * Any other row shows its absence word or nothing.
> * Level words appear on the session's Is it on track card and in its header, using the full words:
>
> | Level | Word |
> |--|--|
> | None or low | On track |
> | Medium | Slightly off course |
> | High | Off course |
> | Extreme | Way off course |
>
> * On track is explained as "No departure found in what Compass read". Help and the meter list all four words, Way off course included.
> * Each absence gets its own word and a one-line How this works explanation:
>
> | State | Word |
> |--|--|
> | No goal typed | No goal yet |
> | Never checked | Not checked yet |
> | Not enough recorded yet | Too early to tell |
> | Nothing departs, but no check shows it done | Can't tell |
> | Goal too vague to read | Goal too vague to check |
> | Stale or withdrawn reading | Out of date |
>
> * Goal history shows no level.
> * Codex sessions never show a level or a correction (`SKILL.md:70`).

### DRC-5479 Owner follow-up ruling, 2026-11-22 (third round)

> The rerun button has one label, Check progress again, whether the last reading is current or out of date. Staleness shows on the card through the ruled Out of date word. This replaces the builder default recorded in DRC-5514.

### DRC-5479 Owner follow-up ruling, 2026-11-22

> The Settings section that today reads "Estimated prompt allowances" becomes "How much a progress check reads", behind its Customize button, as the canvas draws it. Each slider label says what its limit caps, in KB. The word allowance stays reserved for the plan quota card.

### DRC-5479 Owner ruling, 2026-11-22

The owner-approved scope repair assigns the public promise sentence and its test pin to DRC-5516. The naming amendment here is a development record.

> Every sub-question is ruled at once, so this issue is not split.
>
> 1. Control: Check progress, and Check progress again once a check has run. This amends DEC-20 (the 2026-09-24 heading) and DEC-27's signed table. Drift stays in the technical layer only.
> 2. Panel and card: Goal. The nav label is Goal history. Intent and drift and Intent log leave the first layer; the #n=intent slug stays.
> 3. Explainer: one, opened in place from the Goal card, and Help links to it. DEC-27 row 6d stays.
> 4. Off switch: Pause all AI use and Resume AI use, on the board and in the docs. This is a dated amendment under the 2026-10-19 heading in `docs/design-session-summary.md`; the anchored heading stays word for word. The promise-map sentence and its pinning test are updated in the same change. The `--pause-model-calls` flag and the `pause` action keep their names.
> 5. Live monitor: one name, Live monitor, with "Checks progress about once a minute while you watch" under it. It stays per session (DRC-5494), and Settings only says where it lives. Live monitor · Haiku stays in the technical layer; TheLiveMonitorIsSaidToCallAModelTest keeps passing.
> 6. Mark as inaccurate becomes This reading looks wrong, as a dated amendment after the 2026-10-16 heading. Update my goal instead stays beside Steer back and opens the Goal card in edit mode.
> 7. Cost note: "Uses AI" always sits beside Check progress. "N of 100 daily checks left" is added only when 10 or fewer remain.
> 8. First-layer meanings:
>    * check means only a Compass progress check. The agent's runs read "tests and builds", and CI checks are not called checks on the first layer.
>    * allowance means only the plan quota card, Your AI allowance.
>    * The prompt size limit keeps its name in technical details.
>    * The daily cap reads "N of 100 daily checks".

### DRC-5482 Owner follow-up rulings, 2026-11-22 (third round)

> * **Quiet icon:** Phosphor Moon, Bold. The canvas's pause bars are not used.
> * **Absence words** (No goal yet, Not checked yet, Too early to tell, Can't tell, Goal too vague to check, Out of date) get no icons; they are plain grey text. The Sessions icon legend has five entries: Working, Waiting on you, Quiet, Ended, and the Worth a look flag.

Amended 2026-11-24 (owner): the legend has six entries; State not known joins before the Worth a
look flag. See [Status language](#status-language).
> * **Sessions tab order:** All, Waiting on you, Worth a look, Working, Quiet, Ended.

### DRC-5482 Owner follow-up rulings, 2026-11-22

> * Comment 2's "one text pill" on a Sessions row is the progress pill.
>   * The row's state is carried by its icon tile, which has an accessible name and is explained by the on-page legend.
>   * The row shows at most one pill: the progress pill, and only for a stored reading that found a departure (DRC-5476).
>   * Absence words appear as plain grey text, not pills.
> * On Projects, the canvas group "Quiet lately" becomes "No recent activity", so no project group shares a word with the Quiet session state. The groups read "Active today" and "No recent activity".

### DRC-5482 Owner ruling, 2026-11-22

> | Published state | First-layer word | Icon tile | Kept absence line |
> |--|--|--|--|
> | Working | Working | yes | none |
> | Waiting on you | Waiting on you | yes | none |
> | Idle | Quiet: "The agent finished its turn and is waiting for your next message." | yes | none |
> | Ended | Ended: "The session reported that it ended." Never Finished; "Finished cleanly" is removed. | yes | none |
> | State not published | today's wording, as a second text line | never | yes |
> | Waiting on child | today's wording, as a second text line | never | yes |
> | Read by scanning, no observable turn end | today's sentence, as a second text line | never | yes |
>
> * Icon tiles replace text pills on every session row: Sessions, Project and Needs you. The Session page header keeps a text word.
> * Sessions gets a visible on-page icon legend. A tooltip never carries the only copy.
> * Helpers never absorb declared child sessions.
> * Icon weight: Phosphor Bold.

Amended 2026-11-24 (owner): no session row is left without a tile. State not published rows,
and scan-only rows, show the State not known tile; Waiting on child rows show their own state's
tile, or State not known. The text lines stay. See [Status language](#status-language).

### DRC-5485 Owner follow-up ruling, 2026-11-22

> A session that reports a workflow gate is itself Waiting on you:
> * its row takes the Waiting on you state;
> * it is listed in the Sessions Waiting on you tab;
> * it counts once in the card, the tab and the Needs you badge.
>
> The gate's detail shows on the session page and in Needs you.

### DRC-5485 Owner ruling, 2026-11-22

The [DRC-5500 follow-up](#drc-5500-owner-follow-up-ruling-2026-11-22) closes the open navigation name at the end of this comment.

> **Counts.** One selector computes three counts from the rows Needs you renders: the Needs you badge, the Sessions at-a-glance cards and the Needs you sections.
>
> **Badge.** The badge counts Waiting on you plus Worth a look.
>
> **Sections:**
>
> | Signal or end | Section |
> |--|--|
> | Needs input, an exact request, a reported workflow gate (DRC-5500) | Waiting on you |
> | Failed-tool loops, long turns, quiet launches, source disagreements, shared-label collisions, quota | Worth a look |
> | Dirty ends | Worth a look |
> | Clean ends | Ready to wrap up |
> | Also at risk, off the session count | What Compass can't see |
> | Coming next | moves to the session's Right now |
> | Any drift reading | none: no drift reading counts toward any section (DEC-20 stays) |
>
> **Dismiss and Mark as read.** Both use the server dismissals store and survive `--forget`. The Forget explanation says they are kept.
>
> **Header pill.** The header pill and the Working now card count sessions in the Working state.
> * At zero: "Nothing working right now".
> * Before data: "Waiting for the first board."
>
> **Open.** The offered rename of the Needs you nav item stays open. (Closed later by the DRC-5500 follow-up ruling: it keeps the name Needs you.)

### DRC-5488 Owner ruling, 2026-11-22

> option (a).
>
> * Settings, Your data explains the reset. Nothing irreversible runs from the page, and there is no SECURITY.md change. The explanation states:
>   * what Forget deletes and what it keeps, each item traced to `cli.py:901-990` or the --forget row of MANUAL.md;
>   * that the deletion cannot be undone;
>   * the stop-then-forget commands, with a Copy button.
> * It opens inline inside the Your data card, not in a modal (DRC-5497 ruling). The canvas dialog and its Done state are not built. The canvas's lists are wrong and are rewritten from the runtime: goals typed, readings, dismissals and read choices are kept, and the settings on that page are changed (model calls paused, summaries off).
> * The Goal history retention line is corrected: Forget everything keeps the goals a reader typed and their readings.
> * A page route that runs Forget is not part of this project. If it is ever wanted, it is security and data-loss work under full adversarial review.

### DRC-5491 Owner follow-up ruling, 2026-11-22 (fourth round)

> On the two-column Session page, the header (title, state and Check progress) spans both columns, and the two columns start below it.

### DRC-5491 Owner follow-up ruling, 2026-11-22

> The Session page switches to two columns at a window width of 1100px. Below 1100px it stacks in the ruled narrow order: Header, Goal, Is it on track?, Right now, What's happened so far, At a glance, Project.

### DRC-5491 Owner ruling, 2026-11-22

> **Layout: two columns on wide screens.** This reverses the 2026-10-19 one-column ruling (`docs/design-reading-a-session.md:8468-8478`). Right now, At a glance and Project sit in a right-hand column, as the canvas draws them. Below the breakpoint, one column reads top to bottom:
>
> 1. Header
> 2. Goal
> 3. Is it on track?
> 4. Right now
> 5. What's happened so far
> 6. At a glance
> 7. Project
>
> **Steer back** stays editable. It starts from the canvas's plain two-sentence message and keeps "Compass never sends this for you". The three reader-state rows stay.
>
> **Use your prompt** stays visible in read mode, beside Edit goal. DEC-27 row 6a stays.
>
> **The direction question** stays on the Is it on track card, with Add as a line, Make it the goal and Leave it. DEC-27 row 4 and its 2026-10-21 amendment stay. Its look is proposed in Storybook for owner sign-off.

### DRC-5494 Owner follow-up ruling, 2026-11-22 (fourth round)

> The Summaries switch stays nested under Pause all AI use in Settings, as the 2026-10-19 ruling set it. While AI use is paused, Summaries reads as paused.

### DRC-5494 Owner follow-up ruling, 2026-11-22

> Pause all AI use appears in two places: Settings, and the session's AI use and privacy technical tab. Both show one server switch, with the same label and state. The tab says the switch applies to every session.

### DRC-5494 Owner ruling, 2026-11-22

> **Sliders:**
> * Stop rule: stops are derived from the server's minimum, maximum and default, and the default and any saved value are always stops. No bound, default or threshold is hard-coded in the page.
> * Off-stop display: a saved value between stops is itself a stop, so nothing snaps on first touch.
> * Write timing: a value is written when the pointer or key is released. Each slider has one request in flight at a time, and a refusal reverts that slider.
> * Reset and Reset all post null.
> * The Codex warning threshold comes from the server's capacity for each route, not from a constant.
>
> **Switches:**
>
> | Switch | Owner | Lifetime |
> |--|--|--|
> | Summaries | server | durable |
> | Pause all AI use | server | durable |
> | Update check | server | durable |
> | Desktop notifications (moved from the header, DRC-5500) | browser permission | this browser |
> | Usage consent | browser storage | labelled as kept in this browser |
> | Live monitor | stays per session and in memory, in the session's technical layer; not a Settings switch | per session |
>
> DEC-26 item 4 stays. Settings says where the Live monitor lives, using that name.

### DRC-5497 Owner ruling, 2026-11-22

> * The rule is adopted as written:
>   1. Inline disclosure by default, held in the disclosure store.
>   2. A popover only for an anchored choice list or a short companion in a flex row. It is always vertical, closes its siblings and is never nested.
>   3. A tooltip only to name an icon that also has a visible legend.
>   4. A modal only for an irreversible action wider than its card.
>   5. No native details menus. The Project More menu is replaced.
> * NUI-19 is amended, and `docs/design-shadcn-adoption.md` records the reversal of the Switch decision.
> * The phone Menu and Filters open inline, with no Sheet or Drawer.
> * No modal ships in this project: Forget everything opens inline (DRC-5488, option (a)). When the first modal is ever built, page shortcuts and Escape stop at it. keyIsTaken must treat a focused dialog button as taken, and Escape is layered.
> * One reusable Show technical details control appears on Session, Project, Projects (for stage conditions) and Needs you (its per-item Technical details). It does not appear on Sessions home, Goal history or Settings.
> * What Compass can't see is an honest limit and stays on the first layer, outside that control.

### DRC-5500 Owner follow-up ruling, 2026-11-22

> The Needs you nav item keeps the name Needs you, which closes the open rename. The `attention` slug and the `n` shortcut stay as ruled.

### DRC-5500 Owner ruling, 2026-11-22

> **Slugs and routes**
> * Labels only. The `attention` and `intent` route slugs and the documented fragments stay.
> * A new `help` view joins TOP_LEVEL_VIEWS. A session opened from Help has a Help origin, so the crumb and Escape return to Help.
> * An old project focus link (a project route with a session appended) opens that session's page.
>
> **Shortcuts**
> * `n` opens Needs you, and `a` is retired. `p` and `s` are unchanged. Help gets no shortcut.
> * `n` is free today: `keyboard.ts` binds only a, p and s.
> * `dashboard.md:202-213` changes in the same change.
>
> **Projects tab**
> * It always shows. With one project, the page shows the single-project note.
>
> **Where the dropped header controls go**
>
> | Control | New home |
> |--|--|
> | Enable notifications | a Settings row |
> | Update notice | a restyled banner |
> | Reported-blocks (gate) button | joins Needs you: listed under Waiting on you and counted in the badge |
> | Project's read-only terminal | the project's technical details |
> | Steering bar | the project's technical details |
> | Workflow stage conditions | the project's technical details |

### DRC-5503 Owner follow-up rulings, 2026-11-22

> * `--sessions` names its groups by the board's rule: "Right now", then the label the board derives from the published window. A 24-hour window reads "Earlier in the last 24 hours".
> * The `--drift` output heading reads "Progress check ·". The `--drift` flag keeps its name.
> * The unasked-check notification keeps its title, "… may be going off track".
> * The session-summary "What is sent" disclosure keeps its sentence pointing to Turn off summaries, because that control stays on the session page. It is not a retired name.

### DRC-5503 Owner ruling, 2026-11-22

> | Surface | Follows the glossary? | Reason |
> |--|--|--|
> | Board | yes, first | the source of the words |
> | Terminal output: --sessions, --drift, --goal, --summary, --project, --monitor, pause output, status-line footer | yes, in the order board, then parity fixture, then terminal | one name per state |
> | Desktop notifications | yes | the reader sees them beside the board |
> | Skill text (`SKILL.md` and its references) | yes, within the 24,000-byte cap | the agent relays it to the reader |
> | CLI help | yes, last | lower traffic |
> | MCP text and the ask_operator tool | no, keep its words | it addresses the agent, not the reader |
> | Public docs: README, How it works, promise map, HOW_TO_USE, HOW_TO_USE_TERMINAL, MANUAL, SECURITY | yes; controls are named as the board shows them, and flags are still documented as flags | the docs must not pull Compass back to the old words |
> | Discovery text: plugin descriptions (kept identical across the manifests) and `agents/openai.yaml` short_description | yes, plain words | the first words a new user reads |
>
> * Never changes: CLI flags, skill action names, route slugs, data tokens (departure, none_or_low and the rest) and model prompt text.
> * Explanation links follow one pattern, `How <subject> works`. Each subject is written once in the glossary.
> * The What is sent disclosures the server builds show sizes in KB on the first layer, under DRC-5474's rule. Exact byte figures stay in the technical layer and in SECURITY.md.

### DRC-5531 Owner ruling, 2026-11-22

> ship in slices. No RELEASE_HOLD.
>
> The redesign lands as four stacks. Each stack lands whole:
>
> 1. The palette, type, components, icons, header and Sessions page, so the landing page is complete.
> 2. The Session page.
> 3. The other pages, Help and Forget everything.
> 4. The words outside the board: terminal, skill, CLI help and docs.
>
> Fix releases keep shipping throughout. Between slices, pages not yet rebuilt may show the new palette over their old layouts; that is accepted. DRC-5515 does not land on its own: it lands as part of slice 1.
>
> The project overview's How this ships section is updated to these slices. DRC-5523 records the ruling in the Calm Compass record.

## Screenshot evidence policy

Keep real-session captures in the gitignored `docs/reference_shots/`. Attach them only to issues
in this project's Linear workspace. Never commit them or put them in a pull request, an artifact,
a public doc or an externally shared review. Use synthetic Storybook fixtures or the anonymized
Sample session for committed evidence and all other sharing.
Describe reader feedback and real-session findings in words without exposing session
text, repo names or identifiers. A new After image shared in an issue uses the approved
upload flow and the same synthetic or sample data. The temporary upload location stays
private and the temporary file is removed after use.

The removal ruling below assigns the cleanup to its own change. The separately tracked
removal is [DRC-5532](https://linear.app/recce/issue/DRC-5532).

### DRC-5506 Owner ruling, 2026-11-22

> option (b).
>
> One docs pull request deletes the 26 tracked files under `docs/future-ui-exploration/presentations` from main. It lands with or after DRC-5525, which removes the links to them. Any image the walkthrough still needs is replaced with a sample-session capture.
>
> Reason: (c) cannot reach the tagged releases, forks or clones, and it would strand every branch in flight. (b) stops the tip of main serving real session text, at the cost of one pull request.
>
> That copies remain in history, tags, forks and clones is accepted. A removal issue is added to this project, and DRC-5523 records this ruling in the evidence policy of the Calm Compass record.
