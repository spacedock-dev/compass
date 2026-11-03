/*
 * Readiness for the development Storybook proof in `offline.mjs`.
 *
 * "Storybook ready!" means the port is bound, not that the server is idle. Vite transforms each
 * module of the preview on its first request, so the first browser to load it keeps the server's
 * event loop busy. The page's UniversalStore followers (storybook/test, storybook/status,
 * storybook/test-provider, storybook/checklist) start a 1000 ms timer when they are prepared
 * (a constant in storybook's `UniversalStore.prepareThis`), and the request they send is buffered
 * until the websocket opens. The budget therefore covers the upgrade, which the same Node process
 * serves, plus the leader's reply, and a busy event loop can miss it. Delaying every server frame
 * to the page by 1500 ms reproduces exactly the "Timed out waiting for leader state" page error.
 * Requesting the preview and its imports over plain HTTP first leaves the loop idle when the
 * socket connects. The manager is prebuilt static assets, so only the preview is crawled.
 * See docs/design-storybook-offline-proof.md, which also says what this cannot move.
 *
 * The warm-up is an accelerator, not a gate: a stalled request or a missed deadline ends the crawl
 * and the proof carries on. The error stays an error: nothing here filters it from the assertions.
 */

const SPECIFIER = /(?:\bfrom\s*|\bimport\s*\(?\s*)["'](\/[^"']+)["']/g;
const ATTRIBUTE = /\b(?:src|href)=["'](\/[^"'/][^"']*)["']/g;

/** Same-origin absolute paths a served document or module refers to, in order of appearance. */
export function referencedPaths(body) {
  const found = [];
  for (const pattern of [ATTRIBUTE, SPECIFIER]) {
    for (const match of body.matchAll(pattern)) found.push(match[1]);
  }
  return found;
}

/* Races `operation(signal)` against a timer, so a fetch that ignores its signal or a body that never
   finishes cannot hold the caller past `ms`. Resolves to `{ timedOut: true }` rather than throwing. */
async function within(ms, operation) {
  const controller = new AbortController();
  let timer;
  const expired = new Promise((resolve) => {
    timer = setTimeout(() => {
      controller.abort();
      resolve({ timedOut: true });
    }, ms);
  });
  try {
    return await Promise.race([operation(controller.signal).then((value) => ({ value })), expired]);
  } finally {
    clearTimeout(timer);
  }
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Request `entries` and everything they pull in, so the server has transformed it before a browser asks.
 * A path discovered inside a fetched body is left alone when `skip` matches it. Never throws: it returns `{ fetched, skipped, stoppedBy }`, where `skipped` counts requests that failed,
 * answered non-ok or timed out (the browser reports those itself) and `stoppedBy` is `complete`, `limit`
 * or `deadline`.
 */
export async function loadModuleGraph(
  origin,
  entries,
  {
    fetchImpl = fetch,
    limit = 2000,
    concurrency = 8,
    deadlineMs = 10_000,
    skip = null,
    requestTimeoutMs = 5000,
  } = {},
) {
  const started = Date.now();
  const seen = new Set(entries);
  const queue = [...entries];
  let fetched = 0;
  let skipped = 0;
  let active = 0;
  let stoppedBy = 'complete';
  const stopped = () => {
    if (Date.now() - started >= deadlineMs) stoppedBy = 'deadline';
    else if (fetched >= limit) stoppedBy = 'limit';
    return stoppedBy !== 'complete';
  };
  async function visit(path) {
    const remaining = Math.max(1, deadlineMs - (Date.now() - started));
    const outcome = await within(Math.min(requestTimeoutMs, remaining), async (signal) => {
      const response = await fetchImpl(origin + path, { signal });
      if (!response.ok) return null;
      const kind = response.headers.get('content-type') ?? '';
      if (!/html|javascript|css/.test(kind)) {
        await response.arrayBuffer();
        return [];
      }
      return referencedPaths(await response.text());
    }).catch(() => ({ value: null }));
    if (outcome.timedOut || outcome.value === null) {
      skipped += 1;
      return;
    }
    fetched += 1;
    for (const next of outcome.value) {
      if (seen.has(next) || skip?.test(next)) continue;
      seen.add(next);
      queue.push(next);
    }
  }
  /* A worker that finds the queue empty waits while a sibling is still fetching, because that response
     may add paths. Exiting there would leave the rest of the crawl to whichever worker was last. */
  async function worker() {
    while (!stopped()) {
      const path = queue.shift();
      if (path === undefined) {
        if (active === 0) return;
        await pause(2);
        continue;
      }
      active += 1;
      try {
        await visit(path);
      } finally {
        active -= 1;
      }
    }
  }
  await Promise.all(Array.from({ length: concurrency }, worker));
  return { fetched, skipped, stoppedBy };
}

/** Wait until the story index answers, which is when the server has finished indexing the stories. */
export async function waitForIndex(
  origin,
  { fetchImpl = fetch, timeoutMs = 30_000, pauseMs = 100, requestTimeoutMs = 5000 } = {},
) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const outcome = await within(
      requestTimeoutMs,
      async (signal) => (await fetchImpl(`${origin}/index.json`, { signal })).ok,
    ).catch(() => ({ value: false }));
    if (outcome.value === true) return;
    if (Date.now() > deadline) throw new Error(`${origin}/index.json never answered`);
    await pause(pauseMs);
  }
}

/**
 * The index, then the preview document with every module it imports; `entries` are fetched even when `skip`
 * matches them. Returns the crawl's summary.
 */
export async function warmDevServer(origin, { entries = ['/iframe.html'], ...options } = {}) {
  await waitForIndex(origin, options);
  return loadModuleGraph(origin, entries, options);
}

export function describeWarmUp({ fetched, skipped, stoppedBy }) {
  return `Development Storybook warm-up: ${fetched} fetched, ${skipped} skipped, stopped by ${stoppedBy}`;
}
