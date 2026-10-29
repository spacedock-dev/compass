# Design: finding sessions on Sessions

This record owns the Find sessions toolbar on Sessions: one search field, six filters, three presets,
and the lines that say what the filters hide. The module map belongs to
[design-runtime-architecture.md](design-runtime-architecture.md), and what survives a board refresh
belongs to [the reader-state record](design-reader-state.md). The code is three files under
`frontend/src/sessions/`: `filters.ts` holds the rules as pure functions of the drawn rows,
`filterStore.ts` holds the reader's choices, and `SessionsFilters.tsx` draws the toolbar.

Readers asked to find a session by its words, by when it was started and by project. Before the
toolbar the board had one order, its rank: waiting sessions and exact requests first, then recorded
drift, then activity. The toolbar narrows that board without changing the order.

## The toolbar

The toolbar sits in normal page flow inside `<search aria-label="Find sessions">`, after the fleet
facts (ACTIVE NOW and WORKING) and before Active now. It holds:

- a search field, an uncontrolled `DraftInput` with a leading search icon, a `/` hint and a Clear
  search button;
- six filter buttons, Date, Project, Harness, State, Drift and Goal, each opening a popover of
  checkboxes or radios with a count beside each option;
- three presets in a group named "Quick filters": Waiting on you, Started today and Drift recorded;
- a chip for each filter that is on, each removed by one press, and Clear all;
- a result line, and the guard lines described below.

Every change applies at once. There is no Apply button.

Filtering is one pure function applied after `buildSessionsScreen`. It removes rows from both groups
and never re-sorts them: `groupSessions` keeps its rank and lane order, and a row that moves between
groups on a poll moves inside the filter. While a filter is on, each group gains a line directly after
its header, "N of M shown", with its own Clear filters button for a reader who has scrolled away from
the bar. M is the group's unfiltered size, so the M for Active now always equals the ACTIVE NOW figure;
both are `groups.active.length`.

ACTIVE NOW and WORKING stay board-wide while filtering, and so do the header's running count, the
reported-blocks button, the favicon and the document title. The result line says so: "Showing 4 of
12 sessions. ACTIVE NOW and WORKING above count the whole board." The owner chose this on
2026-10-29. Making the figures follow the filter would change what they have meant since 2026-10-20,
and the recorded answers they are held to.

The toolbar stays out of every region `sessions.differential.test.tsx` compares: the operations
header, the fleet facts, each group's header, the group's empty sentence and each row with its
buttons. The shown-line and the filtered-empty sentences render only while a filter is on, each in an
element of its own, so the default render of every compared region is unchanged and
[the recorded answers](design-frontend-migration.md#held-to-recorded-answers) need no departure. Row
hints ("Matched in ...", "Started ...") render inside the identity cell, and only while a search or a
date filter is on.

Nothing on Sessions is sticky, and the toolbar is not either, because focus restoration and route
scrolling assume that. Below 620px the field spans the width, the `/` hint is hidden, the buttons
wrap, and every button and option row is at least 44px tall; each option row is a full-width label,
so the whole row is the touch target. Each popover opens below its own button and scrolls in the room
there. A short window used to flip the tall Date list beside its button, over the search field. There
is no single modal Filters sheet: base-nova Sheet and Drawer make the page inert, which hides the live
regions, and a popover inside a popover would collide with the Escape rule that closes all popovers
at once.

The toolbar is not drawn when there is no payload, no session collection, or a collection with no
rows. The sentences those states already had speak instead.

## Search

Search reads what the row shows: the title as published (including the LAST PROMPT fallback), the
goal cell's text when the goal is known, the current task where the row draws it, the project label,
the worktree and the harness label. An active row draws the current task under its title unless it
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
for 2.4"`. When exactly one row matches, the result line adds "Press Enter to open it." and Enter
opens that session. Enter does nothing during an input-method composition or when zero or several
rows match. The rows can lag the field by a render, so the line offers Enter only once they agree, and
Enter itself reads the words in the field, not the rows still drawn.

## How filters combine and count

Values inside one filter are ORed. Filters are ANDed with each other and with the search.

Each option's count is faceted: it is the number of rows with that value that every other filter
keeps. The filter's own choices are left out, so a count does not move when a sibling value is
pressed. Once a sibling is chosen, choosing this value too shows both, which is more than the number
beside it; How these counts work says the number is how many sessions with that value the other
filters keep. Counts are derived from the rows the screen draws and are never authored. A duplicate identity counts once per drawn row (`SessionRow.key`), the way the screen draws
it.

Option order is fixed: collator order for Project, the payload's order for Harness, and fixed lists
for the rest. A chosen value is not moved to the top and counts never reorder a list, because either
would move the option under the pointer on the press itself.

A preset sets exactly one value in another filter and reads pressed exactly when that value is set.
Waiting on you is State "Waiting on you". Started today is Date with Started and Today, and releasing
it returns Date to Any time. Drift recorded is Drift "Drift recorded", and is not drawn while
annotations are off or the annotation store is unreadable, the states in which the Drift popover lists
no options. Presets carry no count. A second preset adds its own filter, and both must
match.

A choice the board cannot apply keeps its chip but counts as no filter. That covers a date choice on
a board that published no clock, and Drift or Goal while annotations are off or the annotation store
is unreadable. The chip stays so the reader can still see and clear what they chose, and the
popover's sentence explaining it shows under the chips. Counted as a filter, it would make the result
line read "Showing 12 of 12" for a filter that hides nothing; the prototype review found that.

| Filter | Values | Read from |
|---|---|---|
| Date | Filter by Started (the default) or Last active. Then Any time, Last hour, Today, Yesterday, Last 7 days, or the not-published option. A checkbox, "Also show sessions with no start time" | Started: `started_at`, otherwise `first_prompt_at`, the order the session's age uses. Last active: `last_activity` |
| Project | Exact published labels in `Intl.Collator('en')` order, the blank label after them and the empty label last. A "Find a project" field narrows a list of more than 8 | `project`, the label Sessions and Projects group on. `project_key` only for the shared-location note |
| Harness | Harnesses the payload marks `discovered`, in payload order, with payload labels | `harness`, and `payload.harnesses` |
| State | Waiting on you, Working, Idle, Ended, State not published | `rowState()` |
| Drift | Drift recorded; Checked against your current words, none recorded; Not checked against your current words | Recorded drift, `departure_checked`, and a stored reading whose `revision_read` equals `annotation_revision` |
| Goal | Goal saved; Drafted from a prompt, not saved; No goal yet | `goalCell()`: typed words are saved, a known goal without them is drafted |

Started is the Date default because it is what readers asked for, and because it is the only choice
that discriminates on a 24-hour board, where every session was active inside the window by
construction.

Drift never offers "No drift" or "On track". A session nobody checked looks the same as one that was
checked and found nothing, and the Drift popover says so. "Checked against your current words" is
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
two or more distinct non-empty `project_key` values, which is when the board falls back to grouping by
label. The row's own note, "N sessions share this display label; shared location is not established",
counts sessions and never establishes a location, so no copy here states a number of locations.

## Absent values

A value a session does not publish has its own named option. It is never counted as zero, as idle or
as older.

- Date: a row with no stamp in the chosen field matches no dated choice. It is counted in its own
  option, "Start not published (n)" or "Activity time not published (n)", and in a line under the
  result line, such as "4 sessions have no published start time and are not shown.", with Include
  them, which sets the popover's checkbox. The popover names the harnesses responsible, derived from
  those rows. While a dated choice is on, each kept row says which time dated it, adding "from the
  first message" where the first message stood in for the start.
- Project: the empty label is "No project published" and a whitespace-only label is "Blank project
  label (n characters)", each its own option, never merged and never dropped. The length tells two
  blank labels apart, which would otherwise read the same in the list and in the chip. A chosen label that leaves the board
  stays listed as "Not on the board now" and keeps its chip, and its rows return when it comes back.
- State: an unknown state is "State not published", never Idle. A footnote names the harnesses on the
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
- Drift and Goal: with annotations off, or the annotation store unreadable, each popover holds one
  sentence saying so instead of options.
- Dates: with no published clock the Date popover says dates cannot be filtered and disables its
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
window's start, `datedClock(generated - window_hours * 3600, generated)`, and the link "Show all stored
sessions", which reloads with `?all=1` and says the filters are not kept.

In Started mode loading more would not help, because start times are read only for sessions active
in that window: a session that started in range and went quiet before the window began is missing
under either scope. The note says so and offers "Filter by last active instead", which switches the
mode and keeps the When choice.

With the default window, Yesterday and Last 7 days always show the note, Last hour never does, and
Today does only when the window is shorter than the time since midnight. Without `window_hours` the
note says only that the board holds recently active sessions. On `?all=1` the Date popover says older
sessions were not fully read, so their start time, title or model may not be published, and links back
to the default board. `?all=1` stays a reload-only scope read once at boot, which is why showing all
stored sessions resets the filters, and its link says so.

## The hidden-waiting guard

A filter may hide a session that is waiting on the reader. The alternative was to pin waiting rows
through every filter, which would make every filter impure and every count wrong by the pinned rows.
The owner accepted the guard instead on 2026-10-29.

Whenever a hidden row's `rowState()` is "Waiting on you", a static amber `Alert` (it does not
announce) under the result line says so: "1 session waiting on you is hidden by these filters." With
one hidden, it offers Open it, a link to that session named "Open it: " and the session's title, and
Clear filters. With two or more, it offers
Clear filters and See them on Attention. The line is recomputed on every displayed board, so a session
that starts waiting behind the filters is surfaced at the next paint. The header's reported-blocks
button and the favicon are board-wide, so neither goes quiet behind a filter.

When nothing matches, the result says why where it can: search reads titles, goals and prompts, not
the conversation itself; sessions outside the window are not loaded; and sessions the reader marked
handled are not on the board at all. With Waiting on you chosen and nothing matching, the State
footnote shows beside it, because an empty result there is not an all-clear for a harness that cannot
report a wait.

## Persistence

The reader's filters live in memory for the life of the tab, one store per shell: `filterStore.ts`
keeps them in a `WeakMap` keyed by `controls`, read through `useSyncExternalStore`. They survive every
poll, every view change and every trip into a session and back, whether by Escape, the breadcrumb,
the `s` key or Back. A reload ends them. The sample session's second shell keeps a store of its own.

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

`/` focuses the search field and selects its text, and prevents the default so Firefox's Quick Find
stays shut. The listener is on `window` while the toolbar is mounted, which scopes it to Sessions. It
skips by the rule the route keys use, `keyIsTaken` in `shell/keyboard.ts`: a modifier held, an
event already prevented, focus in a field or editable element, or focus in a combobox, listbox,
option, checkbox or radio. It also skips while a popover or a Select is open. The field carries
`aria-keyshortcuts="/"`.

`a`, `p` and `s` typed on a focused checkbox or radio do nothing. Only those two roles joined the skip
list, in `keyboard.ts` and in `Page.tsx`; nothing wider than that was needed, because an input inside
a popover, such as Find a project, was already skipped.

A popover's button keeps focus when it opens, as every popover on the page does, and Tab moves into
the options. Space toggles a checkbox, and the arrow keys move within a radio group. Each button's
name carries its state, for example "Project, 2 selected".

Escape in a popover closes it and returns focus to its button. `installPopoverEscape` is a document
capture handler with no exception for inputs, so it runs before the field's own Escape, and the
field's handler returns early when the event is already prevented. Otherwise Escape in a field with
text clears it and keeps focus, and in an empty field it does nothing, so focus is never dropped to
the body.

Removing a chip moves focus to the next chip, then to Clear all, then to the search field. A chip's
name is "Remove" and the words on it; a shortened chip ("Project: compass +1 more") is described by
its whole list. Clear all and every Clear filters button empty the words (including the live field's
value) and every filter, then focus the search field.

Three buttons go as they are pressed, so each hands focus on first. Include them hands it to the Date
button. Clear project filter hands it to Find a project when the list has one, or to the first
project option. Filter by last active instead hands it to the Last active radio inside the Date
popover, or to the Date button from the note under the result line.

## Focus across polls

Every control the toolbar draws has a focus key the render emits again. The field is
`sessions-search`, each filter button is `sessions-filter-<popover>`, and each option is
`<facet>:<value>`; the Date popover's are `date-field:*`, `when:*` and `include-unstamped`. A row's
title and goal links are keyed by the row, `sessions-row:<key>` and `sessions-row-goal:<key>`, and
fall back to `sessions-search`.

So a focused row that moves between groups on a poll keeps focus, a focused row that leaves the
filtered set hands focus to the search field, and a focused option that goes hands it to its
popover's button. The search field's words are held by the filter store and its caret by field
memory. Field memory restores a caret, scroll and size, never words, so Find a project keeps its words
only while the popover's content stays mounted. When the list falls to eight projects or fewer the
field leaves the page, and when it comes back it starts empty and narrows nothing.

## Announcements

Only the reader's own change speaks, through the existing cue region outside `#app`: at once after a
press, or 600ms after the last keystroke. The sentences are "Showing 4 of 12 sessions.", "No session
matches these filters." and "Filters cleared. Showing all 12 sessions." "Filters cleared" is said only
when the change took the reader's last choice away. A change that leaves only choices the board
cannot apply says "Showing all 12 sessions. The filters you chose cannot be applied to this board.",
and a setting changed while nothing is chosen, such as the Date popover's Filter by, says "Showing all
12 sessions." The key is forgotten before each sentence, so the same sentence after a second press is
spoken again. The typed words are never
read back. A poll never speaks, and no status region is added inside the Sessions view, because a
region every revision redraws would talk over the reader.

## The paint hold

While a filter popover is open, a background board paint waits exactly as it does for an open Select:
for at most twelve consecutive polls, then the board paints without holding again. Closing the
popover, or its open button leaving the page, catches up once. Without the hold, option counts and
the Project list moved under the pointer while the reader was choosing.

A filter popover's trigger carries `data-hold-paint`, which `choiceOpenIn` and `installChoiceRelease`
in `controls/displayGate.ts` match beside the Select trigger, under the same cap. Other popovers, such
as How these counts work, carry no mark and hold nothing. The owner accepted the hold on 2026-10-29.
[An open option list](design-reader-state.md#an-open-option-list) owns the rule and its cap.

## Alternatives rejected

Three designs were scored by three judges, each giving four scores out of 10. Cost scores higher when
the design is cheaper. All three judges chose the toolbar.

| Design | Usability | Honesty | Fit | Cost | Total of 120 | Judges choosing it |
|---|---|---|---|---|---|---|
| Filter toolbar | 8, 8, 8 | 9, 8, 8 | 9, 8, 8 | 7, 7, 6 | 94 | 3 of 3 |
| Facet rail | 6, 6, 6 | 9, 9, 9 | 5, 6, 5 | 5, 6, 5 | 77 | 0 |
| Smart search | 7, 6, 7 | 8, 8, 8 | 5, 5, 6 | 4, 3, 4 | 71 | 0 |

The facet rail was a column of filters beside the rows. It scored highest on honesty, but it would
have taken about 27% off every `1fr` column of the six-column row grid at every desktop width, because
`sessions.css` chooses that grid by viewport media query and `#app` is capped at 1320px. Its honest
parts were grafted onto the toolbar: the absent-value options, the shared-location rule from distinct
`project_key` values, the Open it link on the hidden-waiting guard, the coverage footnote for an empty
Waiting result, listing only discovered harnesses, the "N of M shown" line after each group header,
How these counts work, and the Goal filter in the first version.

Smart search was one field that took typed qualifiers and suggested filters as you typed. It needed a
controlled Combobox input, which departs from the form-controls ruling that a typed field stays
uncontrolled for native undo and composition. It also needed an override of Base UI's Escape,
interception of actions Base UI models as values, and five vendored files. Its presets, the row hint
saying which time dated a row, the note about sessions marked handled, the drift explanation in the
Drift popover and the Codex wait qualifier were grafted on. Typed qualifiers remain the later path, on
the same matcher.

Components considered and not added: Kbd, because the page already styles `kbd`; Input Group, because
a positioned wrapper holds the icon and the clear button; Toggle Group, because the activity filter's
pressed-button idiom covers presets; Switch; Calendar, which needs `react-day-picker` and `date-fns`;
Command, which needs `cmdk`; Combobox and DropdownMenu, which sit outside the display gate, the Escape
order and the keyboard skip rules; Sheet and Drawer, which are modal; and Empty.

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
