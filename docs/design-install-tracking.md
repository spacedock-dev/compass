# Design: install tracking

How the team counts installs, updates and update checks of Spacedock, Review and Compass, and how
many Compass installs are running, without asking anyone for consent and without storing an
identifier or an IP address. It records the contract the three products and the spacedock.md
website share, and the alternatives that were tried and rejected.

Status: decided on 2026-11-10, not built. Nothing in this repository sends any of it yet. When
Compass's update check ships, [`SECURITY.md`](../SECURITY.md) becomes the authority on what that
check sends, and this file stays the record of why.

The work is spread over three repositories. Tracker issues name each piece:

| Piece | Where it is built | Issue |
| -- | -- | -- |
| Counting every release lookup on spacedock.md | the landing site's `latest-release` edge function | DRC-5290 |
| A `/latest-release/compass` route that answers with release data | the same edge function | DRC-5155 |
| Spacedock's installer and `spacedock update` looking releases up through spacedock.md | the spacedock repository | DRC-5291 |
| Compass's daily update check and its off switches | this repository | DRC-5157 |
| Marking our team's own installs as internal | this repository and the installers | DRC-5160 |
| The shared PostHog project | PostHog | DRC-5156 |

---

## The question this answers

The question at the team's review on 2026-11-10 was whether people install these products at all.
Counting installs needs no consent, so in-app usage telemetry, consent and install IDs were deferred
to separate, later work. What is left is to count requests the products already have a reason to
make: looking up the latest release.

Every one of those lookups can pass through `spacedock.md/latest-release/<product>`. Before this
design that route only answered with a redirect to GitHub and counted nothing.

## What is counted, and where

| Source | Kind | Counted when it reaches |
| -- | -- | -- |
| Spacedock's `install.sh`, for Spacedock and each product it installs | `install` | `/latest-release/<product>` |
| `spacedock update`, which runs `install.sh` again | `update` | `/latest-release/<product>` |
| Compass's daily update check | `check` | `/latest-release/compass` |
| Review's own standalone `install.sh` | none sent | `/latest-release/subspace` |

The route names are `spacedock`, `subspace` (Review) and `compass`. The `subspace` route points at
`spacedock-dev/subspace`, the repository both installers download Review from.

Review's standalone installer already calls its route, as a plain `curl` request with no fields, so
its lookups are counted by route and day only, with every field `unknown`. Changing that installer
is the Review owner's call.

Homebrew installs and plugin-marketplace installs never reach spacedock.md, because both download
from GitHub directly. GitHub's own release download and clone counts stand in for them, and they
are an upper bound: CI clones on every run.

## The request

Every counting client sends its fields in the query string and a plain user agent:

```text
GET https://spacedock.md/latest-release/compass?v=2.8.0&kind=check&os=darwin&arch=arm64&channel=stable&internal=0
User-Agent: compass/2.8.0
```

| Field | Values the route accepts | Meaning |
| -- | -- | -- |
| `v` | a version such as `2.8.0` or `2.9.0-rc.1`, at most 32 characters | the version of the product making the request, or, for an install, the installer's |
| `kind` | `install`, `update`, `check` | what the request is |
| `os` | `darwin`, `linux`, `windows` | the operating system |
| `arch` | `arm64`, `x86_64` | the processor architecture; clients send `aarch64` as `arm64` and `amd64` as `x86_64` |
| `channel` | `stable`, `dev` | `dev` for a build running from a checkout |
| `internal` | `0`, `1` | `1` for our team's own use |
| `ci` | `1` | present only when the request comes from CI |

There is no identifier of any kind, and no field a person typed.

The route reads these fields for counting and for nothing else. It accepts only the values above and
drops anything longer than the limit, and it counts anything missing or not on the list as `unknown`.
A wrong or hostile value can at worst add one `unknown` to a count. It can never put free text into a
dashboard, and it never changes the answer the route gives.

### Kind

Compass always sends `check`. Spacedock's `install.sh` sends `install`, and sends `update` when
`spacedock update` runs it and says so, for example through an environment variable it sets for
the script. How `spacedock update` passes that is the Spacedock owner's choice, made in DRC-5291.

### CI

A client sends `ci=1` when its environment has a truthy `CI` variable, which GitHub Actions,
GitLab, CircleCI and Buildkite all set. The route drops such a request before counting it.

The client has to say so, because the route cannot tell by itself. Recognising CI from the caller's
address would mean keeping or sending that address, and PostHog never receives it. A CI system that
does not set `CI` is counted. That is a known limit, listed below.

### Internal

A request is internal when `SPACEDOCK_INTERNAL=1` is set, when Compass's saved internal flag is on
(DRC-5160), or when the build is `channel=dev`. Internal requests are counted, and marked, so every
count can be split into ours and external.

## What the route does with a lookup

1. It answers exactly as it would without counting: a redirect to GitHub for `spacedock` and
   `subspace`, and release data as JSON for `compass`.
2. It skips counting for a `HEAD` request, an unknown product, or `ci=1`. This filter runs once,
   before either call below.
3. For every other `GET`, after the answer is built, it makes two calls without waiting for either,
   so a slow or unreachable service never delays or breaks the answer.

### PostHog: the official number

One event per counted lookup, sent to the PostHog project shared by Spacedock, Review and Compass:

| Part of the event | Value |
| -- | -- |
| event name | `release_lookup` |
| properties | `product` (from the route), `kind`, `version`, `os`, `arch`, `channel`, `internal` |
| `$process_person_profile` | `false`, so no person is created or attached |
| `distinct_id` | a fresh random value for each event, so no two lookups can be linked |

No IP address is sent. PostHog would otherwise record the address the call comes from, which is the
website's server, not the caller, and the project also has "Discard client IP data" on and its GeoIP
transformation off. The project key lives in a Netlify environment variable, never in a repository.

One event name with a `product` property is the naming convention that tells the three products
apart: every chart is the same event broken down by `product` or `kind`.

The team's daily and weekly counts, the install dashboard and the daily Slack post all come from
PostHog.

### Plausible: the quick view

One `pageview` per counted lookup, sent to Plausible's Events API for a Plausible site of its own
(`installs.spacedock.md`), so lookups never mix into the website's visitor numbers. The site name
only labels the data in Plausible. Nothing resolves it, and it has no DNS record.

The page path carries the fields, because Plausible reports custom properties only on its Business
plan and cannot read an operating system out of a command-line user agent:

```text
/<product>/<kind>/<version>/<os>-<arch>
/compass/check/2.8.0/darwin-arm64
/internal/compass/check/2.9.0-dev/darwin-arm64
```

Kind comes second so a single path filter selects it. Internal lookups are prefixed with `/internal`
so they can be filtered out.

The edge function sets `X-Forwarded-For` to the caller's IP address and `User-Agent` to the caller's
user agent. Without the real address, Plausible's bot filter treats the website's server as a bot
and drops the event. The Events API still answers `202` when it drops one, so the only sign is an
`x-plausible-dropped: 1` response header. A request with `X-Debug-Request: true` shows the address
Plausible sees and records nothing.

According to Plausible's data policy, it stores neither the address nor the user agent. It keeps a
daily visitor hash of a salt, the site, the address and the user agent, and deletes the salt every
24 hours. That hash is what gives Plausible an approximate count of unique machines per day, which
the PostHog event, with no person, cannot give. Plausible does derive country, region and city from
the address. The Spacedock lead accepted the address going to Plausible on 2026-11-10.

### Why the two numbers differ

Plausible's bot filter drops some lookups that PostHog counts, so Plausible's count runs lower.
PostHog is the number the team reports. Plausible is the quick view, sitting beside the website's
own traffic in a dashboard the team already uses.

## Compass's update check

Compass's dashboard server checks for the latest Compass release once a day: in the background after
it starts, and again on the first tick after each UTC midnight while it keeps running. No hook makes
the call. It drives the "new version available" notice in the dashboard, and each check is counted
as `kind=check`, which is how running Compass installs are counted.

- It reads `spacedock.md/latest-release/compass`, which answers with release data as JSON, and the
  GitHub releases API until that route is live.
- It follows no redirect and refuses a target that is not `https`, as every outbound request in
  [`SECURITY.md`](../SECURITY.md#scope) does.
- It sends the fields above and nothing else.
- It records the day it last checked, and only after a successful answer, so an unreachable server
  costs nothing and is tried again.

Two switches turn it off, and either one is enough:

- the `--no-update-check` command-line flag;
- a saved setting, a checkbox on the settings page.

The saved setting exists because the server usually starts from a harness hook rather than from a
command a person types, so a flag on its own may never reach it. No environment variable turns the
check off, and there is no shared variable across the three products for it or for installer
counting.

The check stays off in every build until the release that turns it on, so a merge to `main` sends
nothing before [`SECURITY.md`](../SECURITY.md) says what is sent.

### What SECURITY.md will say

When the check ships, SECURITY.md's list of outbound requests gains it: the recipient (spacedock.md,
or GitHub until the route is live), the fields, both switches, the no-redirect rule, and that
spacedock.md passes the caller's IP address on to Plausible, which stores none of it but derives an
approximate location from it. The release notes say the same in plain words. SECURITY.md is not
changed now, because nothing sends yet.

## No consent, and why

This counts installs, updates and update checks on the server, from a lookup each product makes
anyway, and stores no identifier and no IP address. Counting installs that way needs no consent
question, and the update check needs no privacy notice beyond SECURITY.md and the release notes.

Anything that tells one installation from another over time, such as an install ID, a daily usage
event from inside Compass, or feature counts, does need consent, and is deferred with it.

## What the counts cannot say

- Requests are not people. One person with three machines is three installs.
- A machine that never updates, and has update checks off, is invisible.
- Short-lived machines inflate installs. CI runs are left out, but a CI system that does not set
  `CI` is counted.
- Homebrew and plugin-marketplace installs appear only in GitHub's numbers, which include CI clones.
- Review's standalone installs are counted by route and day only.

## Decisions replaced

### The 2026-11-09 privacy gate

An earlier version of this design kept Compass's update check on by
default only while the endpoint forwarded no IP address to a third party. The route now forwards the
caller's address to Plausible, which was accepted, so the gate is dropped (2026-11-10). What it
protected is now a disclosure instead: SECURITY.md and the release notes say the address reaches
Plausible.

### Consent and an install ID

Earlier versions of this work asked for consent at first use, shared
one install ID across the three products, and sent a daily usage event from inside Compass. All of
that is deferred. Without an identifier, a reinstall looks like a new install, which is one of the
limits above.

## Alternatives rejected

### Counting in Plausible's existing site, from the browser script

Plausible on spacedock.md is fed
by the script on the website's pages. A redirect from an edge function runs no script, so the site
had recorded no `/latest-release` lookup at all, ever. Checked on 2026-11-10.

### Plausible alone

Every breakdown has to fit in a page path, its bot filter drops some lookups,
and a daily Slack post would need a job of our own. It stays as the quick view.

### A Netlify Blobs counter

It keeps the data on Netlify with no third party, and it was the
earlier recommendation for these routes. But the team would build the counting, a page to read the
counts, the dashboard and the Slack job. Blobs has no atomic increment, so two lookups at once can
lose a count unless each is stored separately and added up later. And every breakdown has to be
chosen in advance, so a question asked later only has data from the day it is added.

### Netlify's request logs

Observability keeps every request, with its address and location, for 7
days, in the dashboard only. Exporting them needs a plan the team does not have, and keeping
addresses is what this design avoids.

### The fields in the user agent

For example `compass/2.8.0 (darwin; arm64; check)`. It looks tidier, but
it is harder to parse and to validate, and a user agent that changes with every field would make
Plausible's unique-machine count meaningless.

### A separate event name per product

For example `compass_check`. Totals across the suite would mean
adding events together in every chart.

### Telling CI apart on the server

It needs the caller's address or a guess from the user agent.
The first is what this design keeps out of PostHog, and the second misses most CI systems.

### A shared environment variable that turns off checks and installer counting

Each product would
read it differently, and a person setting it would expect it to cover things it does not. Compass's
flag and setting are its own.
