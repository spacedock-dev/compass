/*
 * Readiness for the development Storybook proof in `offline.mjs`.
 *
 * "Storybook ready!" means the port is bound, not that the server is idle. Vite transforms each
 * module on its first request, so the first browser to load the preview keeps the server's event
 * loop busy for as long as that takes. The page's UniversalStore followers (storybook/test,
 * storybook/status, storybook/test-provider, storybook/checklist) each ask the server-side leader
 * for its state over the websocket and give up 1000 ms after they are prepared (a constant in
 * storybook's `UniversalStore.prepareThis`), raising "Timed out waiting for leader state" as a page
 * error. Delaying every server reply to the page by 1500 ms reproduces exactly that error, so the
 * proof's failure is the leader answering late rather than a leader that is missing. Loading the
 * module graph over plain HTTP first moves the transform cost ahead of the browser, so the leader
 * answers an idle server. See docs/design-storybook-offline-proof.md.
 *
 * The error stays an error: nothing here filters it from the proof's assertions.
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

/**
 * Request `entries` and everything they pull in, so the server has transformed it before a browser asks.
 * Returns the paths fetched. A failed request for an entry throws; a failed request for a dependency is
 * left for the browser to report, because the proof asserts on what the browser sees.
 */
export async function loadModuleGraph(
  origin,
  entries,
  { fetchImpl = fetch, limit = 2000, concurrency = 8 } = {},
) {
  const seen = new Set();
  const queue = [...entries];
  for (const entry of entries) seen.add(entry);
  const fetched = [];
  const required = new Set(entries);
  async function worker() {
    while (queue.length > 0 && fetched.length < limit) {
      const path = queue.shift();
      let response;
      try {
        response = await fetchImpl(origin + path);
      } catch (error) {
        if (required.has(path)) throw error;
        continue;
      }
      if (!response.ok) {
        if (required.has(path)) throw new Error(`${path} answered ${response.status}`);
        continue;
      }
      fetched.push(path);
      const kind = response.headers.get('content-type') ?? '';
      if (!/html|javascript|css/.test(kind)) {
        await response.arrayBuffer();
        continue;
      }
      for (const next of referencedPaths(await response.text())) {
        if (seen.has(next)) continue;
        seen.add(next);
        queue.push(next);
      }
    }
  }
  /* A worker that finds the queue momentarily empty exits while a sibling's response may still add to it,
     so rounds repeat until a round fetches nothing. */
  for (;;) {
    const before = fetched.length;
    await Promise.all(Array.from({ length: concurrency }, worker));
    if (queue.length === 0 || fetched.length === before || fetched.length >= limit) break;
  }
  return fetched;
}

/** Wait until the story index answers, which is when the server has finished indexing the stories. */
export async function waitForIndex(
  origin,
  { fetchImpl = fetch, timeoutMs = 30_000, pauseMs = 100 } = {},
) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      const response = await fetchImpl(`${origin}/index.json`);
      if (response.ok) return;
    } catch {
      /* the server is still starting; retry until the deadline */
    }
    if (Date.now() > deadline) throw new Error(`${origin}/index.json never answered`);
    await new Promise((resolve) => setTimeout(resolve, pauseMs));
  }
}

/** Index, then the manager and the preview documents with every module they import. */
export async function warmDevServer(origin, options = {}) {
  await waitForIndex(origin, options);
  return loadModuleGraph(origin, ['/', '/iframe.html'], options);
}
