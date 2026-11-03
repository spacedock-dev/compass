# Design: the development Storybook offline proof

`frontend/storybook/offline.mjs` loads the static Storybook build and then the development server in
Chromium, and asserts that neither makes an external request or logs a console or page error. This
record explains one failure that proof had and what it does about it. The module map lives in
[the architecture record](design-runtime-architecture.md); this file owns only the proof.

## The failure

On the `Storybook (ubuntu-latest)` job the development half failed intermittently (4 of 164 attempts on
one day, once more later) with every story assertion passing. The page errors read
`Timed out waiting for leader state for UniversalStore follower with id: 'storybook/test'`, and the same
for `storybook/status`, `storybook/test-provider` and `storybook/checklist`. It passed on re-run.

## Why

The leader of each of those stores lives in the Storybook server process. The page holds followers. A
follower's timer starts when it is prepared, and it rejects its own sync 1000 ms later (a constant in
Storybook 10.6.0's `UniversalStore.prepareThis`, not configurable). The rejection surfaces as an
unhandled page error. The existing-state request the follower sends is buffered by the channel's
websocket transport until the socket opens, so the one-second budget covers the websocket upgrade plus
the leader's reply, and the same Node process serves both.

So the leader is not missing: the request or the reply arrives late. Delaying every websocket frame from
the server to the page by 1500 ms reproduces the same errors on a healthy server, and no delay does not.
What can make a real server late is its own work. "Storybook ready!" means the port is bound, and Vite
transforms each module of the preview on first request. The first browser to open the page makes the
server do all of that while four followers wait on a one-second clock, which a loaded CI runner can miss.

## What the proof does

Before it launches the browser it waits for the story index, then requests the preview document
(`/iframe.html`) over plain HTTP and follows every same-origin import it reaches
(`frontend/storybook/warm.mjs`). The transform cost is paid with no follower waiting, so the event loop is
idle when the socket connects. It does not follow story files other than the one the proof opens: following
every story reached 506 modules (about 4 s on an idle desk, past its deadline under 40 busy processes, where it
doubled the median run) against 49 for the preview and the one story. The manager is prebuilt static assets that Storybook ships, so it costs
nothing to serve and is not crawled.

The warm-up is an accelerator, not a gate. Each request has its own timeout and the crawl has an overall
deadline; a stalled request or a missed deadline ends the crawl and the proof carries on. Only an index
that never answers fails the proof, because the server is broken then. The proof prints one line, for
example `Development Storybook warm-up: N fetched, M skipped, stopped by complete`, so an under-crawl
(skipped requests such as a Vite `Outdated Optimize Dep` answer, the limit, or the deadline) shows in the
CI log. The assertions are unchanged: the timeout message is not on an ignore list, and any other error
still fails the proof.

## What was not done

- Ignoring the message. It is a real error a reader of the dev server would see.
- A throwaway warm-up page whose log is discarded. It would hide the same error in the first page and
  keeps a browser's worth of work in the proof for no gain over plain requests.
- Retrying the navigation on that error. That tolerates the failure rather than preventing it.

## What the warm-up cannot move

- Upgrade or accept lateness that transform work did not cause.
- Chromium startup contention on a loaded runner.
- Story modules loaded by dynamic or relative imports. The crawler follows absolute same-origin paths in
  the document and in served modules, so those are not proven covered, and the fetched count in the log
  line is the check.
- The one-second constant itself. A runner slow enough to answer one websocket frame in over a second on
  an idle server would still fail, and should.

## Evidence and its limit

The failure did not reproduce locally without the injected delay: 50 runs under 20 and 40 busy processes
(the second set with the build caches removed each run) passed before the change. The fix rests on the
handshake analysis above and on the delay experiment, not on a measured drop in the CI failure rate.
