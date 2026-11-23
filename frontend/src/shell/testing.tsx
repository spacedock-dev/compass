/* Test double for the whole shell: the real owners (runtime, store, router, announcer, gate, controls)
   over a fake clock, a fake event stream, an in-memory history and a scripted backend. Not imported by
   production code. The fake clock is the page's clock, so a poll or a cue timer moves only when a test
   advances it. */
import { act, render } from '@testing-library/react';
import { StrictMode } from 'react';
import { vi } from 'vitest';
import type { FetchLike } from '../api/client';
import { fakeBackend } from '../../test/storage_backends';
import { fakeRouterEnvironment } from '../router/testing';
import { createRouter } from '../router/router';
import { createFakeClock, createFakeEnvironment } from '../transport/testing';
import { App } from '../App';
import { createShell } from './createShell';

export interface TestShellOptions {
  /** The fragment the address bar holds before the page starts. */
  readonly hash?: string;
  /** The body /api/data answers with, or null for a board that has not answered. */
  readonly data?: unknown;
  /** Bodies for additional GET endpoints reached by the mounted view. */
  readonly getResponses?: Readonly<Record<string, unknown>>;
  readonly search?: string;
  readonly strict?: boolean;
  readonly streamSupported?: boolean;
  /** The run's terminal-raise capability, which the served document carries in a meta tag. */
  readonly focusCapability?: string;
  readonly postResponse?: () => Response;
}

export const flush = async (turns = 12): Promise<void> => {
  for (let turn = 0; turn < turns; turn += 1) await Promise.resolve();
};

export function mountShell(options: TestShellOptions = {}) {
  const history = fakeRouterEnvironment(options.hash ?? '#n=sessions');
  const router = createRouter(history.env);
  const clock = createFakeClock();
  const env = createFakeEnvironment({ clock, streamSupported: options.streamSupported ?? true });
  const backend = {
    data: options.data as unknown,
    revision: 1,
    failing: false,
    requests: [] as { method: string; url: string }[],
  };
  const fetch: FetchLike = (url, init) => {
    backend.requests.push({ method: init?.method ?? 'GET', url });
    if (init?.method === 'POST' && options.postResponse)
      return Promise.resolve(options.postResponse());
    if ((!init?.method || init.method === 'GET') && Object.hasOwn(options.getResponses ?? {}, url))
      return Promise.resolve(Response.json(options.getResponses?.[url]));
    if (url.startsWith('/api/session-record')) {
      const session = new URLSearchParams(url.split('?')[1]).get('session') ?? ':';
      const split = session.indexOf(':');
      return Promise.resolve(
        new Response(
          JSON.stringify({
            session: { harness: session.slice(0, split), sid: session.slice(split + 1) },
            entries: [],
            next: null,
            reached_start: true,
            bound: null,
            scanned_bytes: 0,
            kinds: ['user_message', 'agent_message'],
            state: 'ok',
          }),
          { status: 200 },
        ),
      );
    }
    if (backend.failing || backend.data === undefined || backend.data === null)
      return Promise.reject(new Error('offline'));
    backend.revision += 1;
    return Promise.resolve(
      new Response(JSON.stringify(backend.data), {
        status: 200,
        headers: { 'X-Compass-Revision': `7.${String(backend.revision)}` },
      }),
    );
  };
  const reload = vi.fn();
  const shell = createShell({
    env,
    router,
    fetch,
    provider: () => fakeBackend(),
    events: { addEventListener: () => undefined, removeEventListener: () => undefined },
    search: options.search ?? '',
    doc: options.focusCapability
      ? {
          querySelector: () =>
            ({ getAttribute: () => options.focusCapability ?? null }) as unknown as Element,
        }
      : null,
    host: { reload, streamSupported: options.streamSupported ?? true },
    reducedMotion: () => false,
  });
  const tree =
    options.strict === false ? (
      <App shell={shell} />
    ) : (
      <StrictMode>
        <App shell={shell} />
      </StrictMode>
    );
  const view = render(tree);
  return {
    ...view,
    shell,
    history,
    clock,
    env,
    backend,
    reload,
    router,
    gets: (prefix = '/api/data') =>
      backend.requests.filter((r) => r.method === 'GET' && r.url.startsWith(prefix)).length,
    posts: () => backend.requests.filter((r) => r.method !== 'GET').length,
    /** Lets the boot read settle and paints it. */
    settle: () => act(async () => void (await flush())),
    /** A hash change the browser reports after Back, Forward or an edited address. */
    async go(fragment: string) {
      await act(async () => {
        history.type(fragment);
        history.flush();
        await flush();
      });
    },
    async back() {
      await act(async () => {
        history.back();
        history.flush();
        await flush();
      });
    },
  };
}

/* A board the header can count from: two running (one with two subagents), one blocked, two harnesses
   that carry one sid between them, and a session with no project and no title. */
export const BOARD = {
  generated: 1000,
  sessions: [
    {
      harness: 'claude',
      sid: 'shared-sid',
      project: 'alpha/app',
      title: 'Alpha shared claude',
      state: 'working',
      active: true,
      subagents: [{}, {}],
    },
    {
      harness: 'codex',
      sid: 'shared-sid',
      project: 'alpha/app',
      title: 'Alpha shared codex',
      state: 'idle',
    },
    {
      harness: 'claude',
      sid: 'colon:sid',
      project: 'beta/api',
      state: 'needs_input',
      subagents: [{}],
    },
    {
      harness: 'codex',
      sid: 'bare-project-sid',
      project: '',
      title: 'No project label',
      state: 'idle',
    },
    {
      harness: 'codex',
      sid: 'beta-working',
      project: 'beta/api',
      title: 'Beta working',
      state: 'working',
      active: true,
    },
  ],
};
