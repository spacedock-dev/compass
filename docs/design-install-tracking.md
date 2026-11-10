# Design: install tracking

How the team counts release lookups made by Spacedock, Review and Compass when they install, update
or check for a new version, without asking anyone for consent and without storing an identifier or
an IP address. It records the contract the three products and the spacedock.md website share, and
the alternatives that were tried and rejected.

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
| Marking our team's own use as internal | this repository and the installers | DRC-5160 |
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

What is counted is a release lookup, or for Spacedock's installer a counting request sent beside
one, labelled with why it was made. Neither is a completed install. Spacedock's installer counts
before it knows whether anything needs to change, so an update that installs nothing is still
counted, and a download that fails afterwards is still counted.

| Source | Kind | Counted when it reaches |
| -- | -- | -- |
| Spacedock's `install.sh`, for Spacedock and each product it installs | `install` | `/latest-release/<product>` |
| `spacedock update`, which runs `install.sh` again | `update` | `/latest-release/<product>` |
| Compass's daily update check, however Compass was installed | `check` | `/latest-release/compass` |
| Review's own standalone `install.sh` | none sent | `/latest-release/subspace` |

The route names are `spacedock`, `subspace` (Review) and `compass`. A `HEAD` request is not counted.

### Spacedock's installer counts with a separate request

Spacedock's `install.sh` keeps finding releases the way it does on its own, and sends one extra
request per product to the route only to be counted (decided 2026-11-10). It does not look releases
up through the route.

The reason is GitHub's API limit. Unauthenticated, the release API allows 60 requests an hour per
address, shared by everyone behind it. Spacedock's installer is moving its stable lookup off that API
to the `github.com/<repo>/releases/latest` redirect, with `git ls-remote --tags` as the fallback. The
route's answer for `spacedock` and `subspace` is a redirect to the API, so looking releases up
through it would bring the limit back.

The counting request is a `GET` to `https://spacedock.md/latest-release/<product>` with the fields
below. The installer does not follow the redirect, so it makes no call to GitHub. It runs in the
background with a timeout of a few seconds, discards the answer, and never changes whether the
install succeeds or how long it takes. One counting request per product per run means one count.

Review's standalone installer and Compass's update check do look releases up through the route,
once per product per run. `curl -L` follows the route's redirect to GitHub, not back to the route,
so that is still one count.

The `subspace` route maps to `spacedock-dev/subspace-beta` today, while both installers download
Review's files from `spacedock-dev/subspace`. That is a stale name, not a second release source:
`subspace-beta` was renamed to `subspace`, and GitHub redirects the old name to the same repository
and releases (Review owner, 2026-11-10). The route's mapping and the website's verification script
change to `spacedock-dev/subspace` together, before counting is turned on, keeping the stable default
and the `?prerelease=1` behaviour.

Review's standalone installer already calls its route, as a plain `curl` request with no fields, so
its lookups are counted by route and day only, with every field `unknown`. Changing that installer
is the Review owner's call.

Homebrew and plugin-marketplace installs download from GitHub directly, so the install itself never
reaches spacedock.md. GitHub's release download and clone counts stand in for those installs, and
they are an upper bound, because CI clones on every run. A Compass installed that way still makes
its daily update check through the route once the check ships, so it is counted as a running
install like any other.

## The request

Every counting client sends its fields in the query string and a plain user agent:

```text
GET https://spacedock.md/latest-release/compass?v=2.8.0&kind=check&os=darwin&arch=arm64&channel=stable&internal=0
User-Agent: compass/2.8.0
```

| Field | Values the route accepts | Meaning |
| -- | -- | -- |
| `v` | a version matching the grammar below, at most 32 characters | the currently installed version of the product the route names; left out when there is none, as on a fresh install |
| `kind` | `install`, `update`, `check` | why the lookup was made |
| `os` | `darwin`, `linux`, `windows`, `freebsd` | the operating system the client runs on; WSL is `linux`. Accepting a value does not mean every product ships for it |
| `arch` | `arm64`, `amd64` | the processor architecture, spelled as the three products name their release files |
| `channel` | `stable`, `edge` | the release stream the lookup selects: the newest stable release, or the newest release including prereleases |
| `internal` | `0`, `1` | `1` only when the client is explicitly marked as our team's |
| `ci` | `1` | present only when the request comes from CI |

There is no identifier of any kind, and no field a person typed.

### Normalising the values

Clients normalise before they send, and the route applies the same mapping again after decoding the
query, so a client that gets it wrong still lands in the right bucket or in `unknown`:

- `os` and `arch` are compared after ASCII case-folding.
- `darwin` is `darwin`, `linux` is `linux`, `freebsd` is `freebsd`, and `windows`, `win32`,
  `mingw*_nt-*` and `msys_nt-*` are `windows`.
- `arm64` and `aarch64` are `arm64`. `amd64`, `x86_64` and `x64` are `amd64`.
- `channel`, `kind`, `internal` and `ci` must match exactly, in lowercase.
- `v` loses one leading lowercase `v`, then must match
  `^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$`. Prerelease and build parts are
  kept, so `0.28.0-pre5` and `0.28.0+dev` stay distinct. Clients URL-encode it.
- Anything missing, longer than its limit or not on the list is counted as `unknown`.

Python reports Windows as `win32` and Intel processors there as `AMD64`, `uname` reports `Darwin` and
`aarch64`, Git Bash reports `MINGW64_NT-…`, and Go names targets `amd64`. The mapping is written out
so that a shell script, a Go program, a Python runtime and the edge function all agree. Both shell
installers reject Git Bash today, and normalising `windows` does not mean they support it.

The route reads these fields for counting and for nothing else. Only values that pass the rules
above reach PostHog or Plausible. A valid version is still whatever the caller chose to send, so a
hostile caller can add a count under a made-up version, but never free text. The fields never change
which release the route selects or the tag it answers with.

### Kind

Compass always sends `check`. Spacedock's `install.sh` sends `install`, and sends `update` when
`spacedock update` runs it and says so, for example through an environment variable it sets for
the script. How `spacedock update` passes that is the Spacedock owner's choice, made in DRC-5291.

### Channel and prerelease

`channel` is the release stream the lookup selects, not how the build was made. Spacedock's installer
accepts `SPACEDOCK_CHANNEL` of `stable` or `edge`, and `spacedock update` passes on the channel of
the binary running it. Each lookup reports the selection it makes for its own product. Compass has
one stream and sends `stable`.

The route's existing `?prerelease=1` selector, which picks the newest release including
prereleases, keeps working exactly as it does. Counting adds fields beside it and never replaces it.

Whether a version is a prerelease is read from the version itself (`-pre5`, `-beta.1`, `-rc.1`), not
sent as a field. The route adds it to the PostHog event as `prerelease`. A development build has no
field of its own: Spacedock reports an unstamped build as `X.Y.Z+dev`, which shows in `version`.

### CI

A client trims ASCII whitespace from its `CI` variable and case-folds it. CI is on only when the
result is `1`, `true`, `yes` or `on`; any other value, `CI=false` included, is off. When it is on,
the client sends `ci=1`, and the route drops the request before counting it. GitHub Actions, GitLab,
CircleCI and Buildkite all set `CI=true`.

The client has to say so, because the route cannot tell by itself. Recognising CI from the caller's
address would mean keeping or sending that address, and PostHog never receives it. A CI system that
does not set `CI` is counted, and so is any client that sends no fields, such as Review's standalone
installer, whatever its environment. Both are listed below as limits.

### Internal

A request is internal only when the client is explicitly marked as our team's: `SPACEDOCK_INTERNAL=1`
is set, or Compass's saved internal flag is on (DRC-5160). A development build is not internal on its
own, because outside contributors run development builds too, and our team runs stable releases.

Reports split every count three ways: internal, external, and unknown for requests that carry no
marker either way.

## What the route does with a lookup

1. It answers exactly as it would without counting: a redirect to GitHub for `spacedock` and
   `subspace`, and release data as JSON for `compass`.
2. It skips counting for a `HEAD` request, an unknown product, or `ci=1`. This filter runs once,
   before either call below.
3. For every other `GET`, it registers both analytics calls with Netlify's `context.waitUntil()`,
   wrapped in `Promise.allSettled` so one failing does not stop the other, and returns the answer
   without waiting for them. Each call has its own timeout. Delivery is best effort: a successful
   answer to the caller does not prove the lookup was counted.

### The Compass route's answer

Spacedock's installer reads `tag_name` from the route's answer and uses it, unchanged, in GitHub
download addresses, so the Compass route's answer has the same shape as GitHub's release API:

- `GET /latest-release/compass` answers `200` with `Content-Type: application/json` and one release
  object, the newest stable release. `GET /latest-release/compass?prerelease=1` answers with an array
  of one release object, the newest release whatever its prerelease flag, as GitHub does.
- Each release object carries at least `tag_name` (the real tag, such as `v2.8.0`), `name`,
  `html_url`, `published_at` and `prerelease`, copied from GitHub.
- If GitHub cannot be reached, it answers `502` with a JSON error body. Compass treats that as a
  failed check.
- The function looks GitHub up with a token held in a Netlify environment variable, or reuses its
  answer long enough, so every Compass check does not spend GitHub's 60-an-hour unauthenticated
  allowance for the website's own addresses.
- The function may reuse GitHub's answer for a few minutes, but Netlify's CDN never caches the
  route's own answer, because a lookup the CDN answers is a lookup the function never counts.

Normalising the counting fields never changes the tag, the download addresses or the release chosen.

### PostHog: the official number

One event per counted lookup, sent to the PostHog project shared by Spacedock, Review and Compass:

| Part of the event | Value |
| -- | -- |
| event name | `release_lookup` |
| properties | `product` (from the route), `kind`, `version`, `prerelease`, `os`, `arch`, `channel`, `internal` |
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

One `pageview` per counted lookup, sent to Plausible's
[Events API](https://plausible.io/docs/events-api) for a Plausible site of its own
(`installs.spacedock.md`), so lookups never mix into the website's visitor numbers. The site name
only labels the data in Plausible. Nothing resolves it, and it has no DNS record.

The page path carries the fields, because Plausible reports custom properties only on its Business
plan and cannot read an operating system out of a command-line user agent:

```text
/<product>/<channel>/<kind>/<version>/<os>-<arch>
/compass/stable/check/2.8.0/darwin-arm64
/internal/spacedock/edge/update/0.28.0-pre5/linux-amd64
```

Internal lookups are prefixed with `/internal` so they can be filtered out. A missing field is the
segment `unknown`.

The edge function sets `X-Forwarded-For` to the caller's IP address and `User-Agent` to the caller's
user agent. Without the real address, Plausible's bot filter treats the website's server as a bot
and drops the event. The Events API still answers `202` when it drops one, so the only sign is an
`x-plausible-dropped: 1` response header. A request with `X-Debug-Request: true` shows the address
Plausible sees and records nothing.

According to Plausible's [data policy](https://plausible.io/data-policy), it stores neither the
address nor the user agent. It keeps a daily visitor hash of a salt, the site, the address and the
user agent, and deletes the salt every 24 hours. Here the user agent names the product and its
version, so one machine running two products, or updating during the day, makes two hashes, and
machines behind one address with the same version make one. Plausible's daily visitors are those
hashes, not machines or installs. Plausible does derive country, region and city from the address.
The Spacedock lead accepted the address going to Plausible on 2026-11-10.

### Why the two numbers differ

Plausible's bot filter drops some lookups that PostHog counts, so Plausible's count runs lower.
PostHog is the number the team reports. Plausible is the quick view, sitting beside the website's
own traffic in a dashboard the team already uses.

## Compass's update check

Compass's dashboard server checks for the latest Compass release at most once per UTC day: in the
background after it starts, and again on the first tick after each UTC midnight while it keeps
running. No hook makes the call. It drives the "new version available" notice in the dashboard, and
each check is counted as `kind=check`, which is how running Compass installs are counted.

- It reads `spacedock.md/latest-release/compass`, and the GitHub releases API until that route is
  live.
- It follows no redirect and refuses a target that is not `https`, as every outbound request in
  [`SECURITY.md`](../SECURITY.md#scope) does.
- It sends the fields above and nothing else.
- It saves the UTC day of the attempt before it sends the request, and makes no second attempt that
  day, even if the first fails. Saving is atomic, so two servers sharing one Compass home cannot
  both check. The route counts a lookup before it knows whether the answer arrives, so saving only
  after success would let one lost answer become two counted checks. When the last successful
  answer arrived is kept separately, for the notice.

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

This counts release lookups on the server, from a request each product makes anyway, and stores no
identifier and no IP address. Counting them that way needs no consent question, and the update check
needs no privacy notice beyond SECURITY.md and the release notes.

Anything that tells one installation from another over time, such as an install ID, a daily usage
event from inside Compass, or feature counts, does need consent, and is deferred with it.

## What the counts cannot say

- Lookups are not completed installs. A lookup happens before the download, and an update that
  changes nothing still makes one.
- Lookups are not people or machines. One person with three machines is three, and Plausible's daily
  visitors are hashes, not machines.
- A machine that never updates, and has update checks off, is invisible.
- Spacedock's counting request is separate from its lookup, so a counting request that times out or
  is blocked loses that install or update from the count while the install goes ahead.
- Short-lived machines inflate installs. CI runs are left out, but a CI system that does not set
  `CI`, and any client that sends no fields, are counted.
- Homebrew and plugin-marketplace installs appear only in GitHub's numbers, which include CI clones.
  The Compass installs among them do show up later through their daily checks.
- Review's standalone installs are counted by route and day only, with every field `unknown`.
- Internal use is counted as internal only when it is marked. Unmarked team use is external or
  unknown.

## Decisions replaced

### The 2026-11-09 privacy gate

An earlier version of this design kept Compass's update check on by default only while the endpoint
forwarded no IP address to a third party. The route now forwards the caller's address to Plausible,
which was accepted, so the gate is dropped (2026-11-10). What it protected is now a disclosure
instead: SECURITY.md and the release notes say the address reaches Plausible.

### Consent and an install ID

Earlier versions of this work asked for consent at first use, shared one install ID across the three
products, and sent a daily usage event from inside Compass. All of that is deferred. Without an
identifier, a reinstall looks like a new install, which is one of the limits above.

### A `dev` channel, and development builds as internal

The first draft of this record, on 2026-11-10, had `channel` take `stable` or `dev`, with `dev`
meaning a build running from a checkout, and counted every `dev` build as internal. A review the same
day found three problems. Spacedock's real streams are `stable` and `edge`, so every `edge` lookup
would have been `unknown`. A development build is not a release stream: Spacedock marks any
unstamped build, someone else's `go install` included, as `+dev`. And outside contributors run
development builds while our team runs stable releases, so the build says nothing about whose use it
is. `channel` now records the selected stream, prerelease status comes from the version, and only an
explicit marker makes a request internal.

### Recording the check day only after success

The same draft saved the day of Compass's check only after a successful answer. Because the route
counts before the answer arrives, a lost answer would have been retried and counted twice. The day is
now saved before the request.

## Alternatives rejected

### Counting in Plausible's existing site, from the browser script

Plausible on spacedock.md is fed by the script on the website's pages. A redirect from an edge
function runs no script, so the site had recorded no `/latest-release` lookup at all, ever. Checked
on 2026-11-10.

### Plausible alone

Every breakdown has to fit in a page path, its bot filter drops some lookups, and a daily Slack post
would need a job of our own. It stays as the quick view.

### A Netlify Blobs counter

It keeps the data on Netlify with no third party, and it was the earlier recommendation for these
routes. But the team would build the counting, a page to read the counts, the dashboard and the Slack
job. Blobs has no atomic increment, so two lookups at once can lose a count unless each is stored
separately and added up later. And every breakdown has to be chosen in advance, so a question asked
later only has data from the day it is added.

### Netlify's request logs

Observability keeps every request, with its address and location, for 7 days, in the dashboard only.
Exporting them needs a plan the team does not have, and keeping addresses is what this design avoids.

### The fields in the user agent

For example `compass/2.8.0 (darwin; arm64; check)`. It looks tidier, but it is harder to parse and
to validate, and a user agent that changes with every field would split Plausible's visitor hashes
further.

### A separate event name per product

For example `compass_check`. Totals across the suite would mean adding events together in every
chart.

### `x86_64` as the spelling for Intel and AMD processors

It is what `uname -m` prints on Linux and macOS. But all three products already name their release
files `amd64`, and Spacedock's and Review's installers compute `amd64` before they download, so
`amd64` needs the least mapping.

### Spacedock's installer looking releases up through the route

The installer would have read one address and been counted by the same request. But the route
redirects to GitHub's release API, so this would undo the installer's move off the API's per-address
limit. Making the route answer with release data itself, from a token held in Netlify, would remove
the limit too, but it turns the route from a redirect into a proxy for all three products. A separate
counting request leaves the installer's lookup alone, at the cost of a second request that can fail
without the install noticing.

### Telling CI apart on the server

It needs the caller's address or a guess from the user agent. The first is what this design keeps
out of PostHog, and the second misses most CI systems.

### A shared environment variable that turns off checks and installer counting

Each product would read it differently, and a person setting it would expect it to cover things it
does not. Compass's flag and setting are its own.
