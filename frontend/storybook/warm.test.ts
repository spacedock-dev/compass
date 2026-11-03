import { describe, expect, it } from 'vitest';
import { loadModuleGraph, referencedPaths, waitForIndex } from './warm.mjs';

const page = (body: string, type = 'text/javascript', status = 200) =>
  new Response(body, { status, headers: { 'content-type': type } });

function server(files: Record<string, () => Response>) {
  const requested: string[] = [];
  const fetchImpl = async (url: string) => {
    const path = new URL(url).pathname;
    requested.push(path);
    return files[path] ? files[path]() : page('', 'text/plain', 404);
  };
  return { fetchImpl, requested };
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
    const fetched = await loadModuleGraph('http://x', ['/iframe.html'], { fetchImpl });
    expect([...fetched].sort()).toEqual(['/a.js', '/b.js', '/c.js', '/d.js', '/iframe.html']);
    expect(requested).toHaveLength(5);
  });

  it('leaves a missing dependency to the browser and fails on a missing entry', async () => {
    const { fetchImpl } = server({
      '/iframe.html': () => page('<script src="/gone.js"></script>', 'text/html'),
    });
    expect(await loadModuleGraph('http://x', ['/iframe.html'], { fetchImpl })).toEqual([
      '/iframe.html',
    ]);
    await expect(loadModuleGraph('http://x', ['/nothing'], { fetchImpl })).rejects.toThrow(
      /answered 404/,
    );
  });

  it('stops at the limit', async () => {
    const { fetchImpl } = server({
      '/e.js': () => page('import "/a.js"; import "/b.js"; import "/c.js";'),
      '/a.js': () => page(''),
      '/b.js': () => page(''),
      '/c.js': () => page(''),
    });
    const fetched = await loadModuleGraph('http://x', ['/e.js'], {
      fetchImpl,
      limit: 2,
      concurrency: 1,
    });
    expect(fetched).toHaveLength(2);
  });

  it('waits for the index until it answers, and gives up at the deadline', async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      if (calls === 1) throw new Error('ECONNREFUSED');
      return page('{}', 'application/json', calls < 4 ? 503 : 200);
    };
    await waitForIndex('http://x', { fetchImpl, pauseMs: 1 });
    expect(calls).toBe(4);
    await expect(
      waitForIndex('http://x', {
        fetchImpl: async () => page('', 'text/plain', 503),
        timeoutMs: 20,
        pauseMs: 5,
      }),
    ).rejects.toThrow(/never answered/);
  });
});
