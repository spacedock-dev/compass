# Design: credential redaction in published text

Owner for why the dashboard replaces credential-shaped text before it renders, how the shape list was
measured, and which alternatives were tried and rejected. The module map lives in
[`design-runtime-architecture.md`](design-runtime-architecture.md); the security posture and the
residual exposure live in [`SECURITY.md`](../SECURITY.md).

## The problem

A harness transcript records what the operator typed, verbatim. Compass reads those transcripts and
publishes prompt text. As fields rather than as prose, since a prose alias is a name no test can
check, the carriers that reach the page raw are these ten: `title`, `last_prompt`, `state_detail`,
`project_key`, `project_name`, `worktree`, `tasks[].subject`, `tasks[].activeForm`, `subagents[].name` and
`subagents[].parent`. More reaches
the page through `records.safe_text`, including the observer's derived goal and a Codex `title`,
which comes from a prompt because Codex writes no generated title at all. The swept set below adds
the instruction line's own `text` to those seven. If a key was ever pasted into a prompt, the store
holds it and the dashboard shows it.

This is not hypothetical on the machine the feature was built on. A sweep of the local Claude store
found seven distinct live Anthropic credentials sitting in ordinary prompt history, in three formats
(`sk-ant-api03-`, `sk-ant-oat01-`, `sk-ant-ort01-`). The operator chose not to rotate them, so the
runtime keeps reading them on every scan.

Loopback does not help. The dashboard is what someone opens to show a colleague what their agents are
doing, so the exposure is the screen and the screenshot, not the network.

## How the shape list was measured

The rule that shaped the whole exercise: measure by counting, never by reading. The investigation
that found the problem wrote prompt corpora to disk and copied the credentials into fifteen files as
a side effect, turning one exposure into many. So every figure below came from a script that emits
counts, filenames, match lengths and character classes, and has no code path that prints a matched
string.

The corpus is every transcript file the collectors' own globs reach, read end to end: on the first
sweep 12,685 files (12,228 Claude `projects/**/*.jsonl` plus 457 Codex `rollout-*.jsonl`) and
1,982,123 records. That is wider than what a collection publishes, deliberately. A collect reads a
bounded tail of the files inside its activity window, so it sees a fraction of this; counting the
whole store answers "is this shape on this machine at all" rather than "did the dashboard show it
last Tuesday", and a shape list built on the narrower reading would go stale the moment a window
moved.

Two figures come out of it for each shape, and they answer different questions. The first says
whether a shape exists on this machine at all. The second, the last column, says what the dashboard
actually publishes today: a genuine prompt is a user record that `records._turn_signal` reads as a
prompt and `records.injected_prompt` does not reject, which is the gate the instruction line already
uses. There were 21,076 of those on the first sweep and 13 carried a credential shape.

The Codex half of that denominator was not broken out at the time, and it matters, because
`_turn_signal` never returns a prompt for Codex at all: the Codex arm reads `response_item` records
with `role: "user"` instead, and the two numbers are nothing like each other. Re-measured on
2026-08-27 over a store that has grown since: **21,116 genuine Claude prompts and 1,004 genuine
Codex prompts**. Codex writes fewer because a rollout is one exec run rather than a conversation
that goes on for days. Twenty prompts carry a shape, 18 on Claude and 2 on Codex.

The last two columns are lengths rather than counts, and they were added when the greedy bodies were
capped (see C-8). "Longest possible" is what one match can now consume, which is the ceiling on how
much instruction a false positive can take with it. "Longest seen" is the longest single match in a
genuine prompt on the 2026-08-27 sweep, and a blank means the shape matched no prompt at all.

| Shape | Anywhere in the corpus | Files | In genuine prompts | Longest possible | Longest seen |
|---|---|---|---|---|---|
| `urlcred` (`://user:password@`) | 1,572 | 251 | 4 | to whitespace | 16 |
| `pem` (private-key header) | 1,058 | 46 | 0 | header + 200 base64 runs | |
| `jwt` (three base64url segments) | 852 | 126 | 0 | 6,149 | |
| `phc_` (PostHog) | 507 | 343 | 2 | 68 | 47 |
| `AKIA` / `ASIA` (AWS) | 246 | 50 | 1 | 20 | 20 |
| `sk-` (OpenAI) | 99 | 14 | 2 | 183 | 42 |
| `sk-ant-` (Anthropic) | 89 | 35 | 1 | 117 | 108 |
| `sk_live_` / `rk_live_` (Stripe) | 74 | 19 | 0 | 128 | |
| `gh[pousr]_` (GitHub, legacy) | 57 | 17 | 5 | 259 | 40 |
| `lin_api_` (Linear) | 25 | 16 | 0 | 72 | |
| `xox` / `xapp-` (Slack) | 22 | 3 | 2 | 101 | 98 |
| `glpat-` (GitLab) | 16 | 3 | 0 | 70 | |
| `npm_` | 12 | 4 | 0 | 40 | |
| `AIza` (Google) | 0 | 0 | 0 | 39 | |
| `github_pat_` (GitHub, current) | 0 | 0 | 0 | 107 | |
| `aws_secret_access_key` (cued) | 0 | 0 | 0 | 72 | |

Every PEM match is header-only: all 1,058 are the `-----BEGIN … PRIVATE KEY-----` line with no base64
body behind it, which is what a guidance list naming the shape looks like. The `AIza` prefix appears
45 times across 22 files with no 35-character body after it, for the same reason.

Two rows joined on 2026-08-27. `lin_api_` is Linear's personal API key: 25 full-length runs across 16
files already inside the collector's own glob, none of them in a published head, plus 67 further
lines carrying the bare prefix with nothing of the right length behind it. Nothing has reached a card
yet, which is the state `github_pat_` is in, and the same argument put both of them on the list.

`aws_secret_access_key` is the other half of the AWS pair, and it is the reason `AKIA…REDACTED` was
misleading: the access key id was covered and the secret beside it was not, so a card said something
had been removed while the half that matters stayed on screen. A bare 40-character base64 run cannot
be told apart from a hash, a chunk of a diff or a path segment, so the shape is cued instead of
shaped, and one of `aws_secret_access_key`, `AWS_SECRET_ACCESS_KEY` or `secretAccessKey` has to sit
in front of the value. It matches nothing in the local store: 431 lines across 202 files mention one
of the three cues and not one has a 40-character value behind it. The cue and the separator survive
the marker, because with a cued shape the cue is what names the kind, and `…REDACTED` on its own
would tell an operator nothing about which credential to go and rotate.

Four shapes joined on 2026-10-27, none of them measured against the local store because each is a form
a command's output prints rather than a prefix: gcloud's `ya29.` access token (a 20 to 1,024 character
body that admits `.`, because the newer `ya29.c.` form carries dots), the value of an AWS `"SecretString"`
(a run of plain characters or backslash pairs, so the escaped JSON a secret holds is removed whole
instead of stopping at its first inner quote), the password of a netrc entry, cued by `login` or
`machine` in front and not by `password` alone (which opens ordinary prose), and the signature of a
pre-signed URL, cued by a `?` or `&` in front because `sig=` and `signature=` are also ordinary code.
`passphrase` joined the cued name list. Each keeps the words around the value and replaces the value
group alone.

## C-1: Redact in place, keep the surrounding words

Dropping the line loses the instruction, and the instruction is why the line is on the card. A prompt
that pasted a key almost always says something around it, so `rotate ghp_…REDACTED then push the
branch` is a useful row and a blank one is not.

## C-2: The marker is visible on purpose

A silent scrub protects the screenshot and tells the operator nothing. Someone who sees
`sk-ant-…REDACTED` on their own card learns that their prompt history holds a live key, and that is
the only route by which it gets rotated. The marker keeps the prefix that names the kind, so it says
which credential to go looking for.

The prefix is a fixed number of leading characters per shape, not a guess at where the secret starts.
`sk-ant-` keeps 7 and stops short of the `api03` / `oat01` / `ort01` discriminator, which would have
been more useful to the operator and is one more character of a live value on a screen.

A cued shape is the exception, and it has to be. What names the kind there is the key name in front
of the value rather than any prefix of the value itself, so `aws_secret_access_key = …REDACTED`
keeps everything up to the separator and marks only the 40 characters behind it.

## C-3: One list, three application points

The filter is one measured list in `records.redact_secrets` and it is applied in three places.

Inside `records.safe_text`, because that is the bound nearly every published untrusted string already
passes through: the title, the instruction line, the observer goal, model names, tool names, the
notification body, and the ask question and its options, which the HTTP ingress bounds through it
because `asks` is a leaf that cannot reach `records` itself. Nothing had to opt in.

At the slice, through `records.redact_clip`, for the strings a collector builds out of the transcript
by hand. Which strings those are depends on the harness and the claim that they "never reach
`safe_text`" was too broad: Codex's `title` and `last_prompt` come out of
`transcripts.codex_instruction` and go through `safe_text` like everything else, while the other nine
collectors slice them straight out of the record. What every hand-built one has in common is the
ordering, and the ordering is what went wrong. A slice that runs before the filter hands the sweep
below a shape whose tail has already fallen off, and a shape whose tail has fallen off no longer
matches: that is how a URL credential cut short of its `@` published its password. `redact_clip` is
one function that redacts and then bounds, so the order is written once instead of at seventeen
call sites that each have to remember it.

Over the assembled rows in `aggregate._redact_published_text`, which is the backstop under both of
the above. Ten call sites would be ten chances for the eleventh harness to be forgotten, so the sweep
runs once over every row from every harness, and a collector added later is covered without being
asked. What it cannot do is repair an ordering mistake, because by the time it runs a clipped shape
is already unmatchable, which is why the slice sites had to be fixed as well as swept.

Moving the bound out of the collectors altogether was the alternative, so a collector would publish
unbounded text and `aggregate` would redact and clip it in one place. That is the shape with no list
to join at all, and it was not taken here: it changes what every collector returns and what every row
contract says, on a branch already touching ten collectors. It is the right next step, not the right
same step.

The swept set is `title`, `last_prompt`, `state_detail`, `project_key`, `project_name`, `worktree`,
the instruction line's `text`,
`tasks[].subject`, `tasks[].activeForm`, `subagents[].name` and `subagents[].parent`. Task subjects
are there because an agent's todo written from a prompt that held a key can quote it. Three of them
joined after the first version shipped without them, and the first two were measured publishing a
credential run with no marker:
`state_detail` carried a 108-character run while `tasks[].activeForm` on the same row correctly
showed `sk-ant-…REDACTED`, because the collector copies the task into the line before the sweep runs;
and a subagent name carried a 95-character one, which on opencode is the child session's own title,
the same string the sweep redacts when that session is a parent row.

`subagents[].parent` is the third, and it is the one that shows the sweep is a backstop rather than a
fix. It arrived as the same untrusted `agentName` one key over from `name`, went out raw beside a
redacted twin, and was joined to the table a commit later. Then the ordering caught up with it as
well: both keys were bounded at 70 characters by a plain slice before the sweep ran, so a credential
whose run straddled the cut stopped matching and published unmarked. Both now go through
`redact_clip` in the collector, which is the same lesson as `title` and `last_prompt` arriving at a
third pair of keys, and the reason the bound and the filter are one function rather than two lines.

That miss is the argument for the sweep restated. The fields are a table rather than a block apiece,
and the bar for joining it is "could a collector ever put transcript text here", not "does one
today". `state_detail` in particular is read at ten render sites across six web files, one of them
the browser notification body, which is the only published string that leaves the page.

A guard at each render site was rejected for the reason the second paragraph gives. The set of render
sites is a list, and a list is a thing the next feature forgets to join.

### The fourth path is a file, not a screen

Three of the four things that carry prompt-derived text out of the runtime are pixels. The fourth is
the observer sidecar under `~/.compass/observer/`, one JSON file per session holding the goal, the
stage and the open block, and the goal is the operator's own words. It goes through `safe_text` on
the way in, so it carries the same marker the card does, and it is worth naming rather than leaving
implied: a screenshot is momentary and a file is not. It is written owner-only through a temp file
and a rename, the same way `lifecycle.write_state` and `dismissals.save` are, and `SECURITY.md` has
what that mode does and does not buy.

## C-4: Redaction runs before the bound, not after

A key cut at a 140-character cap is still a hundred usable characters of key, and a shape whose tail
fell off no longer matches, so bounding first publishes exactly the values the filter exists to
catch. `safe_text` therefore scrubs control characters, redacts, and truncates, in that order.

The bound may overrun the cap by up to twenty characters, and only ever to finish a marker the cut
landed inside. Measured on `last_prompt`: a key starting 124 to 131 characters in published a marker
with its tail cut off, and one starting at 132 or beyond published the kept prefix and no marker at
all, which is a row ending in `sk-ant-` that reads as a truncated key rather than a redacted one. No
key body was published at any lead, so this is about what an operator can believe rather than about
a leak. `records.instruction_line` already takes the same liberty with its cap plus one, for the
ellipsis, and this is the same trick.

A control character struck through the middle of a key defeats the match on the whole key in either
order, and defeating the match is not where it ends. `safe_text` substitutes a space for that
character before the filter runs, so the head in front of it still matches on its own and redacts,
while the tail behind it is a run with no prefix left to match on and publishes beside the marker. A
probe with the separator 40 characters into the body left 75 characters of key on the row next to
`sk-ant-…REDACTED`. Both this document and `SECURITY.md` used to say the match was defeated and stop
there, which reads as "nothing goes out". It is a limit of shape matching rather than of the
ordering, and `SECURITY.md` carries it with the rest of the residual.

## C-5: The token anchor is checked in the replacer, not written as a lookbehind

Ten of the fourteen shapes have to start a token, or `dask-` followed by a long hyphenated identifier
reads as an OpenAI key. The obvious spelling is a `(?<![A-Za-z0-9_-])` lookbehind on each
alternative, and it was measured and rejected: a leading lookbehind leaves no literal for `re` to
build its first-character skip from, and the substitution cost on a 140-character line goes from
21.5 us to 36.5 us. The check moved into the replacement function, which sees the match offset and
the source string, and every alternative now opens with a literal.

The anchor is not cosmetic. A hyphen counts as inside a token, and that one decision rejects 78 of
the 177 `sk-` candidates in the local store: 177 is what a rule that treats a preceding hyphen as a
boundary finds, and 99 is what the shipped rule finds.

### The anchor used to fail open, and the shape-conditional repair

The first version of the anchor returned the match unchanged when the preceding character was inside
a token. That is a bypass, not a rough edge. One character in front of a key, `x` or a digit or `_`
or `-`, and `sk-ant-api03-` followed by a hundred characters published verbatim: same length, no
marker. So did `AKIA` plus its sixteen, and `github_pat_` plus its forty. Anyone who has ever pasted
a key onto the end of a word had published it.

It was worse than one span. `re.sub` resumes at the end of the match it just declined, so a
near-miss run swallowed the correctly anchored key sitting behind it and both went out: 142
characters in, 142 out, where the same key one space later redacted to 45.

Dropping the anchor was rejected: it is what rejects those 78 candidates, and they are hyphenated
identifiers rather than keys. The anchor is kept and made conditional on the one property that
separates the two, which is length. A `sk-ant-` run of 90 characters, `AKIA`/`ASIA` plus exactly its
16 with nothing token-shaped behind it, or `github_pat_` plus its 40 has no innocent reading whatever
sits in front of it, so above those lengths the anchor no longer applies. Below them it applies
exactly as before. `openai` is deliberately not on that list: its 32-character body is the same
length class the false positives live in, so a threshold there would trade away the rejection the
anchor exists for.

The scan is hand-rolled rather than `re.sub` for the second half of the bug. A rejected span is
re-entered at `match.start() + 1`, so it can no longer shield a valid match that starts inside it.

Re-measured over the same corpus, the change adds no matches at all: the same 12 prompts are altered
before and after, with identical per-shape span counts.

## C-6: The gate, and what it costs

`safe_text` is a hot path. A literal substring scan runs before the alternation, and the alternation
runs only if one of the shape prefixes is present, or if the text holds `://` with a colon somewhere
after it. Measured per call:

| Input | Before | After | Alternation with no gate |
|---|---|---|---|
| 4-character tool name | 366 ns | 412 ns | 461 ns |
| 22-character model id | 529 ns | 967 ns | 3,214 ns |
| 140-character prompt line | 1.70 us | 3.49 us | 23.2 us |
| 140-character line carrying an address with a port | 1.70 us | 22.0 us | 23.2 us |
| 2,000-character observer blob | 18.9 us | 46.6 us | 321 us |

The fourth row is what the clipped-`@` fix in C-7 costs. A line holding `http://127.0.0.1:4553` now
runs the alternation, because the `@` that used to admit a URL credential to the gate is exactly the
character a clip at the title cap removes. Nothing else moved, and a whole collection is unchanged
within noise on `scripts/bench_collect.py --simulate balanced-five --repeat 7`, because the synthetic
store's prompts carry no URLs.

End to end that is a whole collection moving from 32.3 ms to 33.9 ms, a 4.8% cost, on
`scripts/bench_collect.py --simulate balanced-five --repeat 7`.

Two details of the gate are measured rather than chosen. The five GitHub prefixes are spelled out
instead of gating on `gh`, which appears inside "highlight" and "tonight" and put ordinary English on
the slow path. And `://` is not a gate literal on its own: it is paired with `@`, because the
dashboard's own address (`http://127.0.0.1:4553/api/data`) is in prompts constantly and a bare `://`
gate would send most of them through the alternation for nothing.

An optimization in front of a security filter is a way to ship a measured shape switched off, so
`RedactSecretsTest` asserts every alternative is still reachable through the gate.

The alternation was checked for backtracking blowup on adversarial input, since it runs over
untrusted text. The worst of eight probes (4,000 characters of near-miss AWS prefixes) takes 0.62 ms,
and the `://user:password` shape with an `@` sitting before the scheme rather than after it takes
0.51 ms on 3,000 characters. Nothing here is quadratic in a way a prompt could exploit.

### What the 2026-08-27 shapes added to that

Three literals joined the gate with the cued AWS shape (`secret_access_key`, `SECRET_ACCESS_KEY` and
`secretAccessKey`, spelled twice rather than lowered because the gate is `str.__contains__` and
lowering a string costs more than a second scan), and one with Linear's `lin_api_`. Re-measured on
the same five inputs, per call: 0.49 us, 1.09 us, 3.71 us, 25.6 us, 51.5 us. Every figure is a little
above the column beside it and the shape of the table is unchanged.

The nested repetition in the rewritten PEM body was the thing worth probing, since a group repeated
inside another group is where a regular expression usually goes exponential. It does not here,
because everything after the header is optional and the engine therefore never has to backtrack the
repetition to make the match succeed. Seven probes, worst case 0.88 ms on 4,000 near-miss AWS
prefixes; a bare header followed by 4,000 characters of base64 takes 0.084 ms and the same header
followed by 800 short words takes 0.77 ms.

End to end, a whole collection moves from 32.2 ms to 33.6 ms on
`scripts/bench_collect.py --simulate balanced-five --repeat 7`, three interleaved runs of each to
keep a sibling's load out of the comparison. That 4.3% is mostly the redact-then-slice of C-3: the
filter now sees the whole prompt where the slice used to hand it 140 characters.

One version of that change cost twice as much rather than 4%, and it is worth writing down because
the mistake is easy to repeat. The analyzers in `transcripts.py` overwrite `title` on every user
record they pass, so redacting where the title is assigned put `redact_secrets` at the top of the
profile with 3,504 calls and 20% of the collection. The redaction moved to just before the analyzer
returns, where one transcript needs one call.

## C-7: The URL credential has two ends, and neither half may be required

`://user:password@host` was first written as `://[^\s/:@]+:[^\s/@]+(?=@)`, and both bounds were
wrong in a way that published a complete password.

The username half required a character. `redis://:password@host` is the form Redis documents, and on
every one of seven schemes tried, all 24 characters of a synthetic password published with no marker.
The half is now `*`.

The `@` was required to be present. A title is cut at 80 characters and `last_prompt` at 140, and the
cut can land between the password and the `@` the shape was anchored on: clips measured at three
points published 6, 11 and 12 password characters unmarked, and two records in the local corpus sit
at the title cap. The match now ends `(?=@|$)`.

The `$` arm needs a guard, or every address ending in a port reads as a credential, and the
dashboard's own `http://127.0.0.1:4553` is in prompts here constantly. The guard is
`(?![0-9]+$)`: a port is digits and a password that survived a clip is generally not. That trades a
clipped all-numeric password, which is the cheaper of the two errors, since blanking the dashboard
URL would have cost more instruction lines than any other false positive in this repository.

The gate moved with it. `@` alone could not admit the clipped case, so `://` is now paired with a
colon somewhere after it instead, which is what both halves of the shape need and what an ordinary
`https://host/path` does not have. C-6 has what that costs.

## C-8: Every body is capped, and the PEM body is runs rather than a class

An open-ended `{n,}` body is greedy, and the bodies that admit `-` and `_` are greedy across word
boundaries. A key glued by a hyphen to the words behind it takes the words with it: 85 characters
matched on a probe and 71 of them were instruction. Every shape now carries an upper bound as well as
a lower one, set at the vendor's own longest issued key with headroom, and the "Longest possible"
column above is what one match can consume.

The bound cuts both ways and both directions were checked. A cap below a real key would leave the
tail past it published, which is worse than the over-reach it fixes, so the caps sit well above the
longest form each vendor issues: 110 for an Anthropic body where the key is 101, 180 for OpenAI where
a project key is 161, 64 for a Linear key that is only ever 40. `RedactSecretsTest` builds one
synthetic key per shape at that longest documented length and asserts nothing survives the marker.
Above the cap the match ends and the rest of the run publishes, which is the deliberate trade: a run
longer than any key that format issues is not that key, and treating it as one is how the instruction
disappeared in the first place.

Capping and then requiring a non-token character behind the match was tried and rejected. It fails
open in the worst possible way: a run one character longer than the cap matches nothing at all, at
any length, so the whole thing publishes unmarked. Greedy-to-the-cap is the version that degrades
toward redacting too little of an over-long run rather than nothing of it.

The PEM body is the one shape where the cap is structural rather than numeric. It used to be
`[A-Za-z0-9+/=\r\n]*`, a class that deliberately excluded the space so a bare header would not
swallow the sentence behind it. The exclusion worked and the pattern did not, because `safe_text`
turns every line break into a space before the filter runs: on the path that actually publishes, the
body class could not match one character, and the key went out beside a redacted header. Allowing the
space into the class fixes the key and loses the sentence.

What replaced it is base64 runs separated by whitespace, each run at least sixteen characters:
`(?:[ \r\n]{0,4}[A-Za-z0-9+/=]{16,76}){0,200}`. A PEM line is 64 characters and an English word is
not, so the same pattern reads a body whether its line breaks survived or became spaces, and stops at
the first ordinary word after a header carrying no key. A closing short line under sixteen characters
is only eaten when the `-----END` marker is behind it, which is what keeps the rule from taking one
word off the end of a sentence.

## False positives, and the two thresholds they set

Of the 21,076 genuine operator prompts, 13 are altered (0.062%). Classified by the structure of the
match, never by reading it:

- Seven carry a value with a credential's format and a credential's length, at an assignment or
  inside quotes: one Anthropic key of 108 characters, three prompts holding five GitHub tokens of 40,
  two PostHog keys of 47, and one prompt holding two Slack tokens. Redacting those is the filter
  working.
- Two carry one repeated 42-character all-lowercase hyphenated identifier that opens a token with
  `sk-`. Those are false positives.
- Four carry a short `://user:password@` run of 6 to 16 characters, all lowercase, three distinct
  values. Whether any of them is a real password cannot be decided without reading it, which was not
  done. One of those four also carries the documented AWS placeholder `AKIAIOSFODNN7EXAMPLE`, which
  is definitely not a secret.

So the honest reading is seven correct, three wrong, three unjudged. Two thresholds came out of it.

The widening in C-5 and C-7 was re-measured against that same corpus before it shipped, because a
filter that catches more is only an improvement if it does not also blank more instruction lines. It
does not: 12 prompts altered before and 12 after, out of 21,077, with no prompt changing sides and no
shape gaining a span. The small drift from the figures above is the store having grown since, and the
re-run excludes the transcripts the review itself wrote, which are full of synthetic probes and would
otherwise be counted as findings.

The OpenAI body requires 32 characters rather than the 20 the format needs. At 20 the filter alters
25 further genuine prompts, and every one is a hyphenated identifier. 32 does not clear the two
above; requiring an uppercase character in the body would, and that was rejected too, because
OpenRouter spells its key `sk-or-v1-` followed by 64 lowercase hex and the rule that fixes two
prompts loses a vendor.

The PEM body could not hold a space, and that was correct about the false positive and wrong about
the key. With `\s` in the class, a prompt that merely names the header swallows the rest of the
sentence, which is what all 1,058 local occurrences are. But `safe_text` substitutes a space for
every line break before the filter runs, so a class of `[A-Za-z0-9+/=\r\n]` could not match one
character of a real body on the path that publishes it: the header redacted and the whole key went
out behind it. C-8 has what replaced it.

Four candidates that look like credentials and must survive are pinned as tests: a 40-character hex
git SHA, a UUID, a base64 blob in a pasted diff, and a long absolute file path. So are the dashboard's
own URL, a scp-style git remote, a URL with a user and no password, and a `postgres:16` image tag.
The address cases are pinned twice over since C-7, once as they appear and once alongside an `@`
elsewhere in the line, which forces them onto the alternation rather than letting the gate answer
for them.

### Re-measured on 2026-08-27

The caps in C-8 and the two new shapes were held to the same test the C-5 and C-7 widening was: a
filter that catches more is only an improvement if it does not also blank more instruction lines. It
does not. Over 21,116 genuine Claude prompts and 1,004 genuine Codex prompts, 20 are altered before
this change and the same 20 after (18 Claude, 2 Codex, 0.090%), with identical per-shape span counts
on both sides. No prompt changed sides, no shape gained a span, and no shape lost one. The caps sit
above the longest match anything in the corpus makes, which the last column of the table above shows
directly.

## What this does not buy

A shape list covers the formats it was measured against. A credential in a format nobody has seen
goes through unmarked, and a filter that misses gives false confidence, which is worse than no filter
for anyone who trusts it. Three of the sixteen shapes are on the list with a count of zero for
exactly that reason: `github_pat_` is the token format GitHub issues today, and shipping only the
legacy `ghp_` spelling would have been the false confidence in miniature.

Three specific gaps, each measured rather than supposed. A separator through the middle of a key
leaves the tail beside the marker, 75 characters of it on the probe in C-4. A run longer than any key
its format issues is cut at the cap, so the characters past the cap publish; the caps carry enough
headroom that a real key is not one of those, and a vendor lengthening its format would make it one.
And the cued AWS shape only fires when one of three spellings of the key name sits in front of the
value, so a secret access key on a line of its own goes through unmarked, which is the price of not
redacting every 40-character base64 run in every diff.

The rule outside the software is unchanged. Do not paste a credential into a prompt, and rotate one
that was.


## Amended 2026-10-06: native command boundaries survive an early scrub

Observer extraction used to scrub the whole native command wrapper before parsing it.
A credential cue could consume a closing field tag, losing ordinary arguments or
creating a false source cut. The transcript owner now finds the native field boundaries
first with a linear scan, masks each captured field before extraction, and preserves the
original closing tags. Overlapping malformed fields use the whole-record scrub instead.
Missing tags remain missing, so a genuinely cut direction keeps its ellipsis.

Restoring a person's words from a source window also recognizes the raw command
first. It separates the original closing delimiters before masking, then renders
the direction. Rendering before masking was tried and rejected: it folded a
line break inside a recognized AWS credential and let that credential survive.
The retained order preserves the raw-line mask and adds no missing delimiter.

Observer model packets render those commands before their final scrub and byte bound.
First-prompt and copied-correction projections use the existing safe prompt renderer
without a redundant earlier scrub. Recognized credential rules, controls and publication
bounds are unchanged. Effective coverage changes where a closing tag previously
made an ordinary word match the cued rule accidentally. This affects the final
value before the closing argument tag: a short word with no digit or symbol after
a colon (`password: correcthorse`) or a strict token/secret assignment
(`CLIENT_SECRET=staging`, `API_TOKEN=next`), and a bare `bearer` value shorter
than 16 characters, or a value shorter than three characters after another
cued assignment (`password=ab`, `API_KEY=xy`). Each can now survive within a
native command and may still be a real secret. These are documented cued-rule exceptions, not proof that the
values are harmless. The filter cannot identify every secret.

Corrected titles may receive new fact identities under the existing redaction
identity rule; no history migration or spend reset is performed.
