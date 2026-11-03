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
follower sends an existing-state request over the websocket when it is prepared and rejects its own
sync 1000 ms later (a constant in Storybook 10.6's `UniversalStore.prepareThis`, not configurable), and
that rejection surfaces as an unhandled page error.

So the leader is not missing, it answers late. Delaying every websocket frame from the server to the page
by 1500 ms reproduces the same two errors on a healthy server, and no delay does not. What makes a real
server late is its own work: "Storybook ready!" means the port is bound, and Vite transforms each module of
the preview on first request. The first browser to open the page makes the server do all of that while
four followers wait on a one-second clock, which a loaded CI runner can miss.

## What the proof does

It requests the story index, the manager document and the preview document over plain HTTP, and follows
every same-origin import they reach, before it launches the browser (`frontend/storybook/warm.mjs`). The
transform cost is paid with no follower waiting, so the leader answers an idle server. The assertions are
unchanged: the timeout message is not on an ignore list, and any other error still fails the proof.

## What was not done

- **Ignoring the message.** It is a real error a reader of the dev server would see.
- **A throwaway warm-up page whose log is discarded.** It would hide the same error in the first page and
  keeps a browser's worth of work in the proof for no gain over plain requests.
- **Retrying the navigation on that error.** That tolerates the failure rather than preventing it.

## Limits

Not reproduced locally without the injected delay: 50 runs under 20 and 40 busy processes (the second set
with the build caches removed each run) passed before the change, so the fix rests on the handshake above
and on the delay experiment. The warm-up shortens the window but cannot make the one-second constant
larger; a runner slow enough to answer one websocket frame in over a second on an idle server would still
fail, and should.
