# Development tracking

This file owns the roadmap labels and move taxonomy. It is a development record, separate from
[what Compass promises a reader](promise-map.md). The promise map, the Visibility 2x2 board's
Promise row and the Linear project overview carry the same five promises. The in-repository check
allows the board's initial capital where the map continues a lowercase sentence; the tracker copy
is checked by hand. Build order and issue state live in the
[Cargento: Actions Front and Center project](https://linear.app/recce/project/cargento-actions-front-and-center-eed1852b11e6/overview).

Internal labels belong here, in development records and in PR traceability. User-facing docs and
release notes describe behavior without tracker names, issue keys or tracker links, under
[the repository publication rule](../AGENTS.md#public-documentation-and-release-notes).

## How work links to a promise

Every unit of roadmap work names the promise it serves and how it touches it. The link is two
labels on the Linear issue and a two-sentence **User value** section at the top of its body: who
notices this and when in their day, then the promise ID and the move. The
[burndown workflow](roadmap-burndown/README.md) requires the section at triage and reads the labels
at selection.

| ID | Question | Linear label | Board column |
|---|---|---|---|
| P1 | Which of my agents are running? | `journey:open-sessions` | `open` |
| P2 | What is it doing, and when should I come back? | `journey:mid-flight` | `mid` |
| P3 | Is anything waiting on me? | `journey:stopped-at-gate` | `gate` |
| P4 | Will I hit the wall before the work finishes? | `journey:usage` | `usage` |
| P5 | Did anything die quietly? | `journey:end-of-sessions` | `end` |

The five labels and the five columns predate the IDs. Nothing was renamed to make this table.

Work that no stage of the reader's day touches, such as contributor tooling, CI or repository
hygiene, carries `journey:none` instead, with no promise ID and no board column. It always takes
the `none` move below. The reverse does not hold: a `none` move that protects a stage, such as a
test that pins what a reading may send, keeps that stage's label. Ruled by the owner on
2026-11-01, when the label set had no answer for a flaky CI check.

The move says how the work touches its promise.

| Move | Meaning | May change the promise map |
|---|---|---|
| `keep` | Without this, the board says something untrue about the promise. Most defects land here, because the limits are part of the promise. | No |
| `sharpen` | The promise is kept and this makes it more precise, or covers one more harness. | No |
| `extend` | A new clause on an existing promise. | Yes, that promise |
| `new` | Territory no promise covers. Today that is only the Move up a level milestone. | Yes, a new promise |
| `none` | No user-visible effect. The issue says why, and the Linear project overview counts these so the share stays visible. | No |

A decision issue names the promise its ruling unblocks or forecloses, and takes the move of the
work it gates.

Only `extend` and `new` may change what the promise map says. A `keep` or `sharpen` merge changes no
wording here, and a burndown that closes one says so in its report.
