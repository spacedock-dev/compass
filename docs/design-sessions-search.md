# Design: finding sessions on Sessions

This record owns the Sessions toolbar and its status tabs, search, Filters panel and result lines. The module map belongs to
[design-runtime-architecture.md](design-runtime-architecture.md), and what survives a board refresh
belongs to [the reader-state record](design-reader-state.md). The code is three files under
`frontend/src/sessions/`: `filters.ts` holds the rules as pure functions of the drawn rows,
`filterStore.ts` holds the reader's choices, and `SessionsFilters.tsx` draws the toolbar.

Readers asked to find a session by its words, by when it was started and by project. Before the
toolbar the board had one order, its rank: waiting sessions and exact requests first, then recorded
drift, then activity. The toolbar narrows that board. Linked process children follow their visible parent within each
active/history section; Group by group adds label buckets within those sections.

## The toolbar

Below At a glance, All sessions offers six pressed buttons in a group named Session status.
They read All, Waiting on you, Worth a look, Working, Quiet and Ended, in that order.
Their counts follow the same row membership the buttons show. A session with an exact request
and a workflow gate counts once under Waiting on you. Worth a look reads the row's evidence flag.
Progress readings contribute to neither count.

The 2026-10-29 board-wide counting rule applies to every tab and At a glance card.
Search and panel choices narrow the rows, while those figures keep counting the whole loaded
board. Working now selects Working and moves focus to the list. Waiting on you and Worth a
look cards open Needs you.

One search field carries the search icon and a Clear search button. Filters uses the funnel
icon and opens a panel between the search and the list. Project, Agent and Started chips cover
common choices. More filters for power users opens in place and offers the full Project list,
date field and range, Group, Group by group, Headless, State, Progress records and Goal source.
Changes apply as soon as they are made. Selected filters stay visible as removable chips.

The list groups visible rows under Right now and a heading derived from `window_hours`, such as
Earlier in the last 24 hours. A rolling window can include parts of two calendar days. The
wider collection uses Earlier sessions.
Each group counts the rows it shows when the collection is readable. A search with zero matches
says "Nothing here matches." and offers Show everything. The Show older sessions link below the
list reloads with the wider scope and explains that filters are cleared.

All tab, filter and option targets are at least 44px high. At phone widths the status buttons
scroll inside their row, the search field is 48px high, and Filters opens inline. The toolbar
moves with the page. The slash hint is hidden below 620px.
Press Working now again to clear the Working selection. An ended session with an open request
appears in both Ended and Waiting on you. The summary identifies incomplete sources and includes
a limited state count for sessions waiting on a child or without a published state.

## Search

Search reads what the row shows: the title as published (including the Last prompt fallback), the
goal cell's text when the goal is known, the current task where the row draws it, the project label,
the worktree, group and the harness label. An active row draws the current task under its title unless it
repeats the title; a history row does not draw it. Search also reads what a reader would have to open
the session to see: the first prompt (skipped when it was a control message or a copied prompt), the
latest prompt, the session's /goal, the expected outcome lines, task subjects, a current task the row
does not draw, and the session id. Placeholder sentences such as "Add a
goal" or "Title not published" are never searched, because a match on one would be a match on a fact
nobody published.

Case and accents fold away (NFKD with the combining marks removed). A "quoted phrase" is one term.
Terms are ANDed, and each term may match any field. The field reads at most 200 characters. A run of
six or more id characters also matches a session id prefix, so a pasted id finds its session; a
shorter run would match too many. Each row's folded text is built once per payload, and the rows
follow the choices through `useDeferredValue`. The keystroke's own render still holds the earlier
result, and the groups and rows are memoized on it, so that render redraws the toolbar and no row.
On a 1,500-row board in jsdom it took 171 to 181 ms and drew every row before the memoization, and 7
to 15 ms and no row after (measured 2026-10-29).

When a term matched only a field the row does not show, the identity cell names that field with about
80 characters around the match, for example `Matched in your first prompt: "write the release notes
for 2.4"`. An ID match says "Matched in the session ID". When exactly one row matches, the result
line adds "Press Enter to open it." and Enter
opens that session. Enter does nothing during an input-method composition or when zero or several
rows match. The rows can lag the field by a render, so the line offers Enter only once they agree, and
Enter itself reads the words in the field, not the rows still drawn.

## How filters combine and count

Choices within a facet are ORed. The selected tab, search, date and facet choices are ANDed.
Each counted option displays the number of its rows kept by the other choices. Its own facet is
left out. Fixed options, collator order for labels and payload order for agents keep options under
the reader's pointer as counts change. Counts use the same keys as drawn rows.
When every discovered source fails, counts are unavailable for the tabs, list groups and
filter choices. Search reports that the sources could not be read. A readable empty board has
measured zeros. On an empty board the tabs cannot start a new status filter.

Progress check selects Slightly off course, Off course and Way off course from the levels on the
rows. No goal yet uses the same published goal evidence as the Goal cell. All four Progress check
chips stay enabled on a readable annotation board, including an empty board. The
[owner's filter ruling](design-calm-compass.md#drc-5476-owner-follow-up-rulings-2026-11-22-fourth-round)
keeps the chips free of counts. Goal source keeps drafted goals separate. On a mixed board the
panel explains when rows have unpublished goal status. The advanced Progress records options
also carry no counts.

A choice whose clock or annotation data becomes unavailable stays visible and clearable.
An explanation beside the choice says why it filters nothing.
Clearing a date range also clears its option to include sessions with no published timestamp.

| Filter | Values | Read from |
|---|---|---|
| Date | Filter by Started (the default) or Last active. Then Any time, Last hour, Today, Yesterday, Last 7 days, or the not-published option. A checkbox, "Also show sessions with no start time" | Started: `started_at`, otherwise `first_prompt_at`, the order the session's age uses. Last active: `last_activity` |
| Project | Exact published labels in `Intl.Collator('en')` order, the blank label after them and the empty label last. A "Find a project" field narrows a list of more than 8 | `project`, the label Sessions and Projects group on. `project_key` only for the shared-location note |
| Group | Exact published labels in collator order, with No group last; chosen labels that left the board remain clearable | `group`; inherited labels already resolved by the producer |
| Agent | Harnesses the payload marks `discovered`, in payload order, with payload labels | `harness`, and `payload.harnesses` |
| Headless | Headless; Interactive or unknown | `headless === true` for Headless; every other value, including missing and null, for Interactive or unknown |
| State | Waiting on you, Working, Quiet, Ended, Waiting on child, State not published | `rowState()` |
| Progress records | Departure recorded; Checked against your current words, none recorded; Not checked against your current words | Recorded departures, `departure_checked`, and a stored reading whose `revision_read` equals `annotation_revision` |
| Goal source | Goal saved; Drafted from a prompt, not saved; No goal yet | Published annotation evidence. A prompt offered by `goalCell()` on a row without a saved goal is drafted. |

Headless starts with neither value selected, so all sessions show. Interactive or unknown includes
measured interactive runs and sessions whose entrypoint is unknown. The panel says
the value is read from Claude Code transcripts and Codex rollout metadata. The choice shares the
other facets' counts, chips and [tab-lifetime persistence](#persistence).

The Codex collector reads first-line `session_meta.payload.source`: `exec` publishes true, `cli`
false, and missing, malformed, object and other source values publish null. The immutable metadata
cache keeps this classification for stale rows too, without reading their turn history. Originator
is corroborating evidence only. The [entrypoint capture](captures/codex/entrypoint-0.169.0-0.167.0-macos.jsonl)
records current exec and older interactive observations separately. A source object used for subagent
lineage is not classified as interactive.

The Claude collector publishes `headless` only from non-sidechain records whose `sessionId`
matches the transcript's filename stem. Copied records from a resumed session cannot set it.
`entrypoint: sdk-cli` means true and `entrypoint: cli` means false, measured in
[the headless command capture](captures/claude/headless-command-shapes-2.1.319-macos.jsonl) and
[the interactive command capture](captures/claude/scheduled-command-shapes-2.1.319-macos.jsonl).
The existing bounded incremental goal read also reads entrypoints, retaining the latest native
declaration across appends. It selects entrypoints backwards within each batch, decoding only lines
that contain an entrypoint and the native id until it finds a non-sidechain native declaration.
The captures do not establish that a resume keeps the same entrypoint, so appends may change it.
A changed inode, a smaller file, or a changed modification time without file growth restarts the
bounded read for both entrypoint and goal state. The cache stores the observed size separately from
the complete-line cursor so a rewrite beside a partial last record also restarts it. A failed stat
or open discards that shared cache entry: headless and goal endings become unknown, goal history is
unproven, and the next successful read is cold. A cold read with no measured native entrypoint,
or an unread Claude row, publishes null. Harnesses other than Claude Code and Codex also publish null.
No parent-child relationship is inferred. This is a current board field; no lifecycle envelope writes
it and no session-history field is added.

Started is the Date default because it is what readers asked for, and because it is the only choice
that discriminates on a 24-hour board, where every session was active inside the window by
construction.

Drift never offers "No drift" or "On track". A session nobody checked looks the same as one that was
checked and found nothing, and the Progress records options preserve that distinction. "Checked against your current words" is
defined strictly: it needs `departure_checked === true` or a stored reading made against the current
revision of the reader's words, and recorded drift outranks it. A reading made against earlier words
counts as not checked. The owner kept this option in the first version on 2026-10-29.

One gap remains on the server's side. `departure_checked` counts any unasked check that has not been
withdrawn, and a check is withdrawn only when the reader clears their words. After the reader edits
their words to a new revision, a check of the earlier words keeps the session under "Checked against
your current words" until the next check. The page cannot correct it, because a check that raised
nothing publishes no revision. The fix belongs to `departures.checked`, which also chooses the
sentence the session page shows when nothing departed, so it is left to a change of its own.

The Project option carries "Label shared by more than one location" only when that label's rows carry
two or more distinct non-empty `project_key` values whose `project_identity_source` is
"git common directory" or "working directory path". A collector label fallback is unknown, not a
second location. Options and rows disclose unmeasured members explicitly. Rows and project headers
state the measured location count when it exceeds one; they omit the note when every member has
one measured location.

## Absent values

A value a session does not publish has its own named option. It is never counted as zero, as idle or
as older. Headless groups unknown values with the measured non-headless values under Interactive
or unknown, so choosing that subset keeps both.

- Date: a row with no stamp in the chosen field matches no dated choice. It is counted in its own
  option, "Start not published (n)" or "Activity time not published (n)", and in a line under the
  result line, such as "4 sessions have no published start time and are not shown.", with Include
  them, which sets the Date options' checkbox. The panel names the harnesses responsible, derived from
  those rows. While a dated choice is on, each kept row uses the shared board time formatter,
  adding "from the first message" where the first message supplied the start time.
- Project: the empty label is "No project published" and a whitespace-only label is "Blank project
  label (n characters)", each its own option, never merged and never dropped. The length tells two
  blank labels apart, which would otherwise read the same in the list and in the chip. A chosen label that leaves the board
  stays listed as "Not on the board now" and keeps its chip, and its rows return when it comes back.
- State: Quiet requires a turn stop and Ended requires a reported session end. An unknown state
  is "State not published". A scan without a turn stop has its own limit on the row. A footnote names the harnesses on the
  board that do not report a wait (`reports_needs_input` is not true), with how many of their sessions
  could be waiting unseen. A session of a harness that does report one, but whose wait state could not
  be read, is counted on its own line: "The wait state of 2 OpenCode and Pi sessions could not be read,
  so they could be waiting without showing here." The server marks such a row with the `block state`
  source gap, and every Pi and OpenCode row carries it until its adapter sends an event. A last line
  names the harnesses whose wait reporting holds only in some setups (`reports_needs_input_when`). An
  ended session waits on nobody, so it is left out of every count.
- Harness: an undiscovered harness is not listed, because listing all ten at zero would claim the
  board read stores it never found. A harness whose store could not be read is listed disabled as
  "Store could not be read", with no count.
- Drift and Goal: with annotations off, or the annotation store unreadable, the panel shows a
  sentence saying so instead of options.
- Dates: with no published clock the panel says dates cannot be filtered and disables its
  choices. The browser's clock is never substituted.

Day edges are local midnights around the board's `generated` time, each built from the calendar date
(`new Date(year, month, day - n)`), so a day that a daylight-saving change makes 23 or 25 hours long
still starts at midnight. Walking back from today's start did not: in a zone whose clocks jump at
midnight, such as America/Santiago, that day begins at 01:00 and every earlier edge inherited the
hour. That day's own edge is its first instant, 01:00. Last 7 days is today and the six days before
it. Days follow this computer's clock and time zone. The suite runs in UTC, so the tests of these
edges switch the zone for themselves, to America/New_York and America/Santiago.

## The board window

The default board holds sessions active in the last `window_hours`, 24 unless the server was started
with another window. A dated choice can reach past that, and the two Date modes fail differently
there.

In Last active mode the sessions outside the window were simply not loaded. The note gives the
window's start, `datedClock(generated - window_hours * 3600, generated)`. Show older sessions
below the list reloads with `?all=1` and says the filters are not kept.

In Started mode loading more would not help, because start times are read only for sessions active
in that window: a session that started in range and went quiet before the window began is missing
under either scope. The note says so and offers "Filter by last active instead", which switches the
mode and keeps the When choice.

With the default window, Yesterday and Last 7 days always show the note, Last hour never does, and
Today does only when the window is shorter than the time since midnight. Without `window_hours` the
note says only that the board holds recently active sessions. On `?all=1` the list footer says older
sessions were not fully read, so their start time, title or model may not be published, and links back
to the default board. `?all=1` stays a reload-only scope read once at boot, which is why showing all
stored sessions resets the filters, and its link says so.

## The hidden-waiting guard

A filter may hide a session that is waiting on the reader. The alternative was to pin waiting rows
through every filter, which would make every filter impure and every count wrong by the pinned rows.
The owner accepted the guard instead on 2026-10-29.

When a filter hides a waiting session, a static alert below the result says how many are hidden.
It offers Open it when one is hidden or See them on Needs you when several are hidden.
Clear filters is available in both cases. A poll can surface a session that starts waiting behind
the filters. An empty search result uses the single reset sentence, with board-wide waiting
counts still visible above it. Wait reporting limits are available under State in the panel.

## Persistence

The reader's filters live in memory for the life of the tab, one store per shell: `filterStore.ts`
keeps them in a `WeakMap` keyed by `controls`, read through `useSyncExternalStore`. They survive every
poll, every view change and every trip into a session and back, whether by Escape, the breadcrumb,
the `s` key or Back. The Filters panel and its nested disclosure use the keyed disclosure store.
A reload clears their open state and all choices. The sample session's second shell keeps a store of its own.

They are not written to the URL fragment:

- `router/grammar.ts` prints top-level views with no suffix, and its tests pin that.
- The router canonicalizes with `replaceState` on every hashchange, so `#n=sessions&q=x` would be
  rewritten to `#n=sessions` at once.
- `navigate()` pushes a history entry, so every toggle would flood Back.
- Escape, the breadcrumb and `s` all rebuild `{view:'sessions'}` and would drop the suffix.
- The grammar is held to recorded answers that cannot be regenerated.
- Typed prompt words would land in browser history and in copied links.

They are not written to browser storage either. That would be a twelfth storage family, touching
`storage/keys.ts`, its key-count test, the reader-state record's opening sentence and a storage row in
the migration inventory. The deciding reason is the reader: a filter silently restored on reload hides
sessions, and on this page those can be sessions waiting on them.

## Keyboard and Escape

`/` focuses the search field and selects its text. The shortcut yields to inputs, modifiers,
open choices and the Filters panel. Space toggles a checkbox and arrows move within a radio
group. Escape from the panel or its trigger closes it and returns focus to Filters. Escape in
search closes an open Filters panel first. When the panel is closed, Escape clears the search.

Removing a chip moves focus to the next chip, Clear all or the search field. Clear all, Show
everything and Clear filters reset the tab and filters, keep the grouping choice and focus search.
Include them and Filter by last active instead return focus to Filters. Clear project filter
returns focus to Find a project or the first project option.

## Focus across polls

The search field is keyed by `sessions-search` and Filters by `sessions-filters`. Advanced options
use `<facet>:<value>`, or `date-field:*`, `when:*` and `include-unstamped` for Date.
A disappearing option falls back to Filters. A row link that moves groups keeps focus through
`sessions-row:<key>`. A link that leaves the filtered set falls back to search.

Field memory retains the search caret and the filter store retains its words. The Find a project
field keeps its draft while mounted. It starts empty after leaving Sessions or after the board's
project list has shrunk to eight options or fewer.

## Announcements

Only the reader's own change speaks, through the existing cue region outside `#app`: at once after a
press, or 600ms after the last keystroke. The sentences are "Showing 4 of 12 sessions.", "Nothing here matches." and "Filters cleared. Showing all 12 sessions." "Filters cleared" is said only
when the change took the reader's last choice away. A change that leaves only choices the board
cannot apply says "Showing all 12 sessions. The filters you chose cannot be applied to this board.",
and a setting changed while nothing is chosen, such as Date's Filter by, says "Showing all
12 sessions." The key is forgotten before each sentence, so the same sentence after a second press is
spoken again. The typed words are never
read back. A poll never speaks, and no status region is added inside the Sessions view, because a
region every revision redraws would talk over the reader.

## The paint hold

Filters carries `data-hold-paint` on its trigger. While expanded, the existing display gate
holds background board paints so options and counts stay in place while the reader chooses.
Closing Filters or navigating away displays the latest deferred board once.
[An open option list](design-reader-state.md#an-open-option-list) owns the cap and manual
refresh rule. The owner accepted the hold on 2026-10-29.

## Alternatives rejected

The original toolbar had eight filter popovers and three presets. The separate openings took
several steps to combine choices, and the tall Date list fought for space with the search field.
The redesign keeps the common tabs and search in view, and the remaining facets use the same
in-flow panel. A modal sheet would make the board inert while choosing.

A facet rail would take width from session rows. Smart search with typed qualifiers required a
controlled combobox and extra Escape handling. The current layout keeps the native undo and
composition behavior of the search field, and lets readers see applied facets as chips.

## Later filters

None of these is in the first version.

| Filter | What it would offer | What it needs or must keep |
|---|---|---|
| Worktree | Linked worktree names, nested under Project | No null option, because a null worktree covers both a main checkout and an unknown working directory |
| Model | Verbatim model ids, plus "Model not published (n)"; Pi options read "via" and the provider | A footnote saying Gemini, Goose and Droid never publish one |
| How it landed, and git | Turn stopped, Session ended, Neither observed; then Uncommitted work, Clean, Not measured | Clean only for `dirty === false`; a null `dirty` is Not measured, never Clean |
| At risk | Failed-tool loop (Claude Code only, labelled), Long turn, Uncommitted at end | Attention's risk derivation, labelled per harness |
| Spacedock role, subagents, open tasks | First officer or Ensign; has running subagents; has open tasks | Hidden when no row carries the field |
| Sort | Needs attention first (today's order), Last active, Started, Waiting longest, Project A to Z, within each group | A Display popover kept apart from the filters; unstamped rows sort last, under a divider |
| Custom date range | From and To, inclusive local days, as two native date fields first | A Calendar needs `react-day-picker` and `date-fns`, with exact pins and a release-age review |
| Typed qualifiers | `harness:codex project:compass is:waiting started:today` in the same field | The same matcher and the same absent-value rules |
| Shareable view | The closed filters in the fragment, never typed words | A recorded departure from the grammar's recorded answers, its route rows, and a replace-only write path |

Token rate and duration are not planned. [The capacity promise](promise-map.md#p4-will-i-hit-the-wall-before-the-work-finishes)
rules out a ranking of who is burning fastest, and only five of the ten harnesses publish what a
duration needs.

Some later work needs the server, and none is needed now:

- Publishing the creation times some stores already hold (Cursor, Goose and OpenCode) as `started_at`,
  so Started covers more than five of the ten harnesses.
- A bounded `?since=` window on `/api/data`, so Last 7 days does not mean reading every stored session
  on every poll.
- Search over the 14-day history store, and over stored summaries.
- A per-row git branch field.
- A way to include sessions marked handled.

## Declared families and group buckets

The producer's [declared-session contract](design-declared-sessions.md) alone establishes parent
links and group inheritance. The page never uses a title, project, headless flag or matching group to
infer a family. A linked child names its parent with a page link. An unmatched declaration says
"Declared parent is not on the board; not linked." A parent held working names the selected child
as `Waiting on child "title"`, linking to it; a child without a title is named by its session id.
An open question keeps its input-wait state on the row and session page; a child hold cannot
replace input wait or an observed end.

Nesting uses only the kept rows in the current section and group bucket. It never brings a hidden
headless row back, promotes a history row into active work, or changes a counter. When the parent
is filtered out or belongs to another section or bucket, the child still names and links to it.
The parent's waiting line resolves against the whole payload, so a hidden child is still named.
The session page lists all its linked children and their states, including ended children.

A group appears as text, with "(from parent)" on an inherited label. No label draws no chip;
Group's absent-value option and grouping bucket say "No group". Named options, selected chips
and bucket headings use one formatter that quotes names and escapes embedded quotes and
backslashes, so the literal name `No group` reads `"No group"` and cannot collide with absence.
Group by group arranges named buckets in collator order, with No group last, separately in Active
now and Recent history.
Clearing filters preserves that display choice. The filter store holds both the Group selections
and grouping choice across polls and navigation; reloading the tab resets both. Group labels are
searchable words, separate from goal text.
