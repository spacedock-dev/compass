import { describe, expect, it } from 'vitest';
import {
  describeWarmUp,
  loadModuleGraph,
  referencedPaths,
  waitForIndex,
  warmDevServer,
} from './warm.mjs';

const page = (body: string, type = 'text/javascript', status = 200) =>
  new Response(body, { status, headers: { 'content-type': type } });

const never = () => new Promise<Response>(() => undefined);

function server(files: Record<string, () => Response | Promise<Response>>, delayMs = 0) {
  const requested: string[] = [];
  let inFlight = 0;
  let peak = 0;
  const fetchImpl = async (url: string) => {
    const path = new URL(url).pathname;
    requested.push(path);
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    try {
      if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
      return files[path] ? await files[path]() : page('', 'text/plain', 404);
    } finally {
      inFlight -= 1;
    }
  };
  return { fetchImpl, requested, peak: () => peak };
}

describe('development Storybook warm-up', () => {
  it('finds same-origin paths in documents and modules, and ignores the rest', () => {
    const html =
      '<script type="module" src="/a.js"></script><link href="/b.css"><img src="//cdn/x">';
    expect(referencedPaths(html)).toEqual(['/a.js', '/b.css']);
    const js =
      'import x from "/c.js"; export * from "/d.js"; import("/e.js"); import "react"; import "./f.js";';
    expect(referencedPaths(js)).toEqual(['/c.js', '/d.js', '/e.js']);
  });

  it('fetches the whole module graph once, following imports through every level', async () => {
    const { fetchImpl, requested } = server({
      '/iframe.html': () => page('<script src="/a.js"></script>', 'text/html'),
      '/a.js': () => page('import "/b.js"; import "/c.js";'),
      '/b.js': () => page('import "/c.js"; import "/d.js";'),
      '/c.js': () => page('export const c = 1;'),
      '/d.js': () => page('export const d = 1;'),
    });
    const summary = await loadModuleGraph('http://x', ['/iframe.html'], { fetchImpl });
    expect(summary).toEqual({ fetched: 5, skipped: 0, stoppedBy: 'complete' });
    expect(requested.sort()).toEqual(['/a.js', '/b.js', '/c.js', '/d.js', '/iframe.html']);
  });

  it('keeps several requests in flight once a module has revealed its imports', async () => {
    const children = ['/a.js', '/b.js', '/c.js', '/d.js', '/e.js', '/f.js'];
    const files: Record<string, () => Response> = {
      '/entry.js': () => page(children.map((path) => `import "${path}";`).join('')),
    };
    for (const path of children) files[path] = () => page('');
    const { fetchImpl, peak } = server(files, 15);
    const summary = await loadModuleGraph('http://x', ['/entry.js'], { fetchImpl, concurrency: 4 });
    expect(summary.fetched).toBe(7);
    expect(peak()).toBeGreaterThan(1);
  });

  it('counts a failed or missing request as skipped and carries on', async () => {
    const { fetchImpl } = server({
      '/iframe.html': () =>
        page('<script src="/gone.js"></script><script src="/ok.js"></script>', 'text/html'),
      '/ok.js': () => page(''),
    });
    expect(await loadModuleGraph('http://x', ['/iframe.html'], { fetchImpl })).toEqual({
      fetched: 2,
      skipped: 1,
      stoppedBy: 'complete',
    });
    const throwing = async () => {
      throw new Error('ECONNRESET');
    };
    expect(await loadModuleGraph('http://x', ['/iframe.html'], { fetchImpl: throwing })).toEqual({
      fetched: 0,
      skipped: 1,
      stoppedBy: 'complete',
    });
  });

  it('leaves discovered paths that match skip alone, but still fetches a named entry', async () => {
    const { fetchImpl, requested } = server({
      '/iframe.html': () => page('import "/s/a.stories.tsx"; import "/lib.js";', 'text/javascript'),
      '/lib.js': () => page(''),
      '/s/a.stories.tsx': () => page('import "/s/dep.js";'),
      '/s/b.stories.tsx': () => page(''),
    });
    const summary = await loadModuleGraph('http://x', ['/iframe.html', '/s/b.stories.tsx'], {
      fetchImpl,
      skip: /\.stories\.[jt]sx?$/,
    });
    expect(summary.fetched).toBe(3);
    expect(requested.sort()).toEqual(['/iframe.html', '/lib.js', '/s/b.stories.tsx']);
  });

  it('stops at the limit and says so', async () => {
    const { fetchImpl } = server({
      '/e.js': () => page('import "/a.js"; import "/b.js"; import "/c.js";'),
      '/a.js': () => page(''),
      '/b.js': () => page(''),
      '/c.js': () => page(''),
    });
    const summary = await loadModuleGraph('http://x', ['/e.js'], {
      fetchImpl,
      limit: 2,
      concurrency: 1,
    });
    expect(summary).toEqual({ fetched: 2, skipped: 0, stoppedBy: 'limit' });
  });

  it('returns at the deadline when a request never resolves, without throwing', async () => {
    const started = Date.now();
    const summary = await loadModuleGraph('http://x', ['/iframe.html'], {
      fetchImpl: never,
      deadlineMs: 60,
      requestTimeoutMs: 1000,
    });
    expect(Date.now() - started).toBeLessThan(500);
    expect(summary).toEqual({ fetched: 0, skipped: 1, stoppedBy: 'deadline' });
  });

  it('gives up on one stalled request after its own timeout and goes on with the rest', async () => {
    const { fetchImpl } = server({
      '/iframe.html': () =>
        page('<script src="/stuck.js"></script><script src="/ok.js"></script>', 'text/html'),
      '/stuck.js': never,
      '/ok.js': () => page(''),
    });
    const summary = await loadModuleGraph('http://x', ['/iframe.html'], {
      fetchImpl,
      requestTimeoutMs: 30,
    });
    expect(summary).toEqual({ fetched: 2, skipped: 1, stoppedBy: 'complete' });
  });

  it('waits for the index until it answers', async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      if (calls === 1) throw new Error('ECONNREFUSED');
      return page('{}', 'application/json', calls < 4 ? 503 : 200);
    };
    await waitForIndex('http://x', { fetchImpl, pauseMs: 1 });
    expect(calls).toBe(4);
  });

  it('rejects when the index never answers, including a request that never resolves', async () => {
    await expect(
      waitForIndex('http://x', {
        fetchImpl: async () => page('', 'text/plain', 503),
        timeoutMs: 20,
        pauseMs: 5,
      }),
    ).rejects.toThrow(/never answered/);
    await expect(
      waitForIndex('http://x', { fetchImpl: never, timeoutMs: 40, requestTimeoutMs: 15 }),
    ).rejects.toThrow(/never answered/);
  });

  it('returns the crawl summary from warmDevServer and describes it on one line', async () => {
    const { fetchImpl } = server({
      '/index.json': () => page('{}', 'application/json'),
      '/iframe.html': () => page('<script src="/a.js"></script>', 'text/html'),
      '/a.js': () => page(''),
    });
    const summary = await warmDevServer('http://x', { fetchImpl });
    expect(summary).toEqual({ fetched: 2, skipped: 0, stoppedBy: 'complete' });
    expect(describeWarmUp(summary)).toBe(
      'Development Storybook warm-up: 2 fetched, 0 skipped, stopped by complete',
    );
  });
});
