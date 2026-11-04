---
name: sync-project
description: Use when reconciling Compass's Linear project, milestone and issue surfaces after a merge, before picking work, or whenever a tracker description has grown past what a reader needs to act.
---

# sync-project

Keep the tracker worth reading. A Linear surface is opened to decide what to do next, so it holds
the promise to the user, the decisions in force, and the work still to do. Everything else has a
better home, and this skill says which.

`sync-docs` owns repository Markdown. This skill owns the project overview, the milestone
descriptions and the shape of an issue. Run it in the same pass: `sync-docs` first, because a
promise sentence is canonical in `docs/promise-map.md` and the tracker copies it, then this.

## The three questions

Apply these to every block, every time. Most blocks fail at least one.

1. **Would a reader act differently for having read this?** If not, cut it.
2. **Is it about the past?** Build history belongs in the pull request that shipped it. A tracker
   surface describes what is true now and what is left.
3. **Does Linear already display it?** Issue counts, progress, status and dates are on the page
   already. Restating them creates a second number that goes stale.

## User value and the journey come first

Every surface opens with who benefits and when in their day. Not the mechanism, not the history,
not the plan.

- The **project overview** opens with the product promise, then the five stages of the user's day
  and the promise kept at each. That table is the spine of the whole project and nothing goes above
  it.
- A **milestone** opens with `## The user value` and one bold sentence naming what the user gets.
  One sentence, in their words, about their day.
- An **issue** opens with `## User value`, two sentences: who notices this and when, then the
  promise ID and the move.

Write it so the person who owns the outcome can read it. If a sentence only makes sense to someone
who has read the code, it is a mechanism note and it belongs further down or in the repository.

## Ownership: one surface per subject

Nothing goes stale here so much as it accretes, because every burndown leaves a paragraph behind
and no single paragraph looks like too much.

| Surface | Owns | Never |
|---|---|---|
| Project overview | The promise and the journey table. Build order. Decisions in force. Where to start. | Per-item status, counts Linear shows, what shipped, what it taught. |
| Milestone description | The user value for that group, what is left as one line per issue, what it waits on, a decision owed before building, and a contract note a named remaining item must read. | Anything about one item that its own issue could carry. Any dated build narrative. |
| Issue body | That item's user value, scope, acceptance criteria, score, and dated staleness notes. | Another item's status. A post-mortem of its own build. |
| Issue comment | Validation findings, build post-mortems, corrections to the body, cross-issue consequences. | Anything the body should have said instead. |
| Labels | Release row, journey stage, move, origin. They *are* the record. | Prose restating a label. |

**A closing burndown makes the overview shorter.** If it grew, something is in the wrong place.

## Where the cut material goes

Cutting is not deleting. Each kind of prose has one home:

- **How it was built, and what went wrong on the way.** The pull request that shipped it. Git keeps
  it and the issue links to it.
- **A lesson that changes how the next person builds.** A comment on the issue that taught it. If
  re-deriving it would cost a day, `docs/design-*.md` instead, and the code cites that.
- **A repeated engineering rule.** `AGENTS.md`, which agents load every session. A lesson repeated
  in a tracker description is a rule nobody wrote down.
- **A correction to a claim.** A comment on the issue that carried the wrong claim. Never edit the
  mistake away silently, because whoever read it needs to see the correction.
- **A number.** Nowhere. Linear derives it live.

## Templates

Match these shapes. Add a section only when it changes what someone does next.

### Project overview

```markdown
## What we promise

**[The product promise, one sentence, in the user's words.]**

[One line framing the table.]

| Stage of the day | What Compass tells you today | Who owns what comes next |
| -- | -- | -- |
| 1. ... | ... | [milestone] |

[Where else this wording is canonical, and the rule that they change together.]

## What is next

[Build order. What is complete. Where to start, and the skill that picks it.]

## Open decisions

[Only the open ones, linked. What a gate means. Any earlier ruling that changes what to build.]

## How to read an issue

[The label vocabulary and where it is defined. One line each.]

## Authority

[What settles a disagreement. What belongs here and what does not.]
```

### Milestone

```markdown
## The user value

**[What the user gets, one sentence.]**

[Optional single line: what this group adds beyond what is already kept.]

## What is left

[ID](url): one line of user value, in the user's words.

## Waits on

Nothing. [Or the gate, linked.]

## Decide before building        <- only when a real question is open
[The question, why it is owed now, and what it costs to get wrong.]

## Read before building          <- only when a merge changed a contract a remaining item needs
- [ID]: the one line that changes what that item's builder does.
```

`Read before building` is written by the `burndown` skill's
[Linear reconciliation, item 3](../burndown/references/linear.md#reconcile), and read at its
[issue-understanding step](../burndown/references/planning.md#3-understand-each-issue-in-the-group).
Preserve it through a rewrite, keyed by ID, and drop a bullet whose ID has reached `Done`. It is the
one exception to the no-build-history rule, and it earns it by changing what the next builder does
rather than by recording what the last one did.

A complete milestone is three lines: the heading, the promise, and `Complete. Nothing is left, and
nothing is waiting.` Resist adding a retrospective to a finished milestone. It is the single most
common way this page grows.

### Issue

Leave the acceptance criteria and the measured evidence alone: an issue body has to be buildable,
and a criterion with its `Verified by:` clause is what makes it so. Reshape only the top, so it
opens with `## User value` naming who notices and when, and move a post-mortem into a comment.

## Voice

Invoke the `humanizer` skill on any description you rewrite. It is a third party skill and a clean
checkout will not have it, so the rules that matter here are written out rather than delegated:

- No em dashes or en dashes, and no curly quotes. A period, a comma, a colon or parentheses.
- One bold sentence per surface, the promise. Bold on every other line reads as machine output and
  hides the sentence that matters.
- Sentence case in headings.
- Plain verbs. `is`, `are`, `has`. Not "serves as", "stands as", "boasts", "represents".
- Cut the stock words: crucial, key, pivotal, seamless, robust, leverage, delve, showcase,
  underscore, testament, landscape, vibrant, enduring, interplay.
- No participle tails bolted on for depth, such as "..., ensuring reliability".
- No groups of three for rhythm. Say the two things that are true.
- End on the last concrete fact. No summary paragraph and no send-off.

Keep the specifics. A measured number, a named failure mode and a rejected alternative are the parts
worth reading. Losing those is the opposite error and just as bad.

## Procedure

1. **Read the whole surface before editing.** Note where each block would live under the ownership
   table. Most blocks that fail the three questions are already recorded in a pull request.
2. **Refresh the facts from a fresh query**, not by adjusting a number already on the page. Then ask
   whether the number belongs at all. Usually Linear shows it.
3. **Rewrite from the template** rather than trimming in place. Trimming keeps the old skeleton and
   the old skeleton is the problem.
4. **Relocate before you cut.** If a lesson has no home yet, give it one and link it. Say in your
   report what moved and where.
5. **Check the labels.** Every open issue carries a `journey:*` and a `move:*` label. Report the
   ones that do not. Do not set them here: the label is a triage output, and setting it without the
   brief is the drift this check exists to catch.
6. **Check the relations.** A closed issue still holding a `blocks` edge on an open issue reads as a
   live gate. Remove that edge and add `relatedTo` in its place. Leave an edge between two closed
   issues alone, because it is the record of what waited on what.
7. **Apply the voice pass** to everything you touched, then read it back once as the person who owns
   the outcome rather than as the person who built it.

## Verification

Paste each description you wrote to a scratch file, then run this. It names the characters by code
point rather than printing them, so the checker does not itself trip the repository's tone grep:

```bash
python3 - /tmp/sync-project-draft.md <<'CHECK'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
banned = {"em dash": "\u2014", "en dash": "\u2013",
          "curly double": "\u201c\u201d", "curly single": "\u2018\u2019"}
for label, chars in banned.items():
    hits = sum(text.count(ch) for ch in chars)
    print(f"{label:14} {hits}")
bold = re.findall(r"\*\*[^*]+\*\*", text)
print(f"{'bold spans':14} {len(bold)}   (expect 1, the promise)")
CHECK
```

Every count must be zero, and the bold count must be one.

Then read the surface against the three questions one more time. If a block survives all three,
keep it. If you are unsure, it fails.

## Why this skill exists

Measured 2026-09-08, before the first pass. The project overview held about 25,000 characters, of
which the current state was three lines: build order, the open decision, and where to start. The
rest was twenty-five paragraphs of session narrative, including a refresh block whose own opening
sentence explained that its numbers had not changed. The eight milestone descriptions held 54,000
characters between them, and the two that read best were the two shortest, at 93 and 127 characters,
because both said only what the user gets and that nothing was left.

The cleanup took the overview to about 3,600 characters and the milestones to 6,300, a reduction of
roughly 88 percent, and lost no fact anyone needed to pick up work. Two of the eight milestones were
already correct and were left untouched.

The failure was not one bad edit. It was an agent appending a true paragraph after every merge, each
one defensible on its own, with nothing that ever removed one.
