/* A shell for the Intent step's tests: the real owners over a fake clock and a scripted backend that
   answers each route on its own terms, so a test can hold an answer open, refuse it, or return
   something that is not JSON, and counts every request by method and path. Not imported by production
   code. */
import { act, render } from '@testing-library/react';
import { StrictMode } from 'react';
import type { FetchLike } from '../api/client';
import { fakeBackend } from '../../test/storage_backends';
import { createRouter } from '../router/router';
import { fakeRouterEnvironment } from '../router/testing';
import { App } from '../App';
import { createShell } from '../shell/createShell';
import { flush } from '../shell/testing';
import { createFakeClock, createFakeEnvironment } from '../transport/testing';

export interface RecordedRequest {
  readonly method: string;
  readonly url: string;
  readonly path: string;
  readonly body: Record<string, unknown> | null;
}

/* What a route answers with. A function sees the parsed request and returns the response, a promise of
   one, or `'hold'` to leave the request open until the test releases it. */
export type Handler = (request: RecordedRequest) => Response | Promise<Response> | 'hold';

export const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status });

export interface IntentShellOptions {
  readonly hash?: string;
  readonly data?: unknown;
  readonly strict?: boolean;
  readonly focusCapability?: string;
  readonly routes?: Record<string, Handler>;
}

export function mountIntent(options: IntentShellOptions = {}) {
  const history = fakeRouterEnvironment(options.hash ?? '#n=intent');
  const router = createRouter(history.env);
  const clock = createFakeClock();
  const env = createFakeEnvironment({ clock, streamSupported: true });
  const state = {
    data: options.data as unknown,
    revision: 1,
    requests: [] as RecordedRequest[],
    routes: { ...(options.routes ?? {}) } as Record<string, Handler>,
    held: [] as { readonly path: string; readonly release: (response: Response) => void }[],
    holdData: false,
    heldData: null as null | (() => void),
  };
  const fetch: FetchLike = (url, init) => {
    const path = url.split('?')[0] ?? url;
    const parsed = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    const request: RecordedRequest = { method: init?.method ?? 'GET', url, path, body: parsed };
    state.requests.push(request);
    const handler = state.routes[path];
    if (handler) {
      const answer = handler(request);
      if (answer === 'hold') {
        return new Promise<Response>((resolve) => {
          state.held.push({ path, release: resolve });
        });
      }
      return Promise.resolve(answer).then(async (response) => {
        // Older fixtures script identical source words for every id; explicit batch
        // fixtures already carry results. Requests are still counted once, as sent.
        const ids = path === '/api/direction' ? parsed?.['fact_ids'] : null;
        if (!Array.isArray(ids) || !response.ok) return response;
        const body = (await response.clone().json()) as Record<string, unknown>;
        if (Array.isArray(body['results'])) return response;
        return json({ results: ids.map(() => body) });
      });
    }
    if (path !== '/api/data') return Promise.resolve(new Response('not scripted', { status: 404 }));
    if (state.data === undefined || state.data === null)
      return Promise.reject(new Error('offline'));
    const respond = () => {
      state.revision += 1;
      return new Response(JSON.stringify(state.data), {
        status: 200,
        headers: { 'X-Compass-Revision': `7.${String(state.revision)}` },
      });
    };
    if (state.holdData && !state.heldData) {
      return new Promise<Response>((resolve) => {
        state.heldData = () => resolve(respond());
      });
    }
    return Promise.resolve(respond());
  };
  const written: string[] = [];
  const shell = createShell({
    env,
    router,
    fetch,
    provider: () => fakeBackend(),
    events: { addEventListener: () => undefined, removeEventListener: () => undefined },
    search: '',
    doc: options.focusCapability
      ? {
          querySelector: () =>
            ({ getAttribute: () => options.focusCapability ?? null }) as unknown as Element,
        }
      : null,
    host: { reload: () => undefined, streamSupported: true },
    reducedMotion: () => false,
    clipboard: () => ({
      writeText: (text: string) => {
        written.push(text);
        return Promise.resolve();
      },
    }),
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
  const count = (method: string, prefix: string) =>
    state.requests.filter((request) => request.method === method && request.path.startsWith(prefix))
      .length;
  return {
    ...view,
    shell,
    router,
    clock,
    env,
    state,
    written,
    history,
    gets: (prefix = '/api/data') => count('GET', prefix),
    posts: (prefix = '/api/') => count('POST', prefix),
    allPosts: () => state.requests.filter((request) => request.method === 'POST'),
    settle: () => act(async () => void (await flush())),
    /** Answers the oldest held request on `path`, as the server would. */
    async release(path: string, response: Response) {
      await act(async () => {
        const at = state.held.findIndex((entry) => entry.path === path);
        const [entry] = at >= 0 ? state.held.splice(at, 1) : [];
        entry?.release(response);
        await flush();
      });
    },
    /** The next board, as a poll would bring it. */
    async poll(next: unknown) {
      state.data = next;
      await act(async () => {
        const read = shell.runtime.refresh();
        await flush();
        clock.advance(500);
        await read;
        await flush();
      });
    },
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
    /** Moves the fake clock, as a wait would, and lets what it released settle. */
    async advance(ms: number) {
      await act(async () => {
        clock.advance(ms);
        await flush();
      });
    },
  };
}
