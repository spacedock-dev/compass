/* A shell for the session screens' tests: the real owners over a fake clock and a scripted backend that,
   unlike `shell/testing`, answers each route on its own terms, so a test can hold an answer open, refuse
   it, or return something that is not JSON. Not imported by production code. */
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

export type AnswerScript =
  | { readonly kind: 'confirm' }
  | { readonly kind: 'refuse' }
  | { readonly kind: 'status'; readonly status: number }
  | { readonly kind: 'not-json' }
  | { readonly kind: 'offline' }
  | { readonly kind: 'hold' };

export interface SessionsShellOptions {
  readonly hash?: string;
  readonly data?: unknown;
  readonly strict?: boolean;
  readonly focusCapability?: string;
  readonly answer?: AnswerScript;
  /** The project context a session page reads; without it the read falls through to the board. */
  readonly context?: unknown;
}

export interface Request {
  readonly method: string;
  readonly url: string;
  readonly body: unknown;
}

export function mountSessions(options: SessionsShellOptions = {}) {
  const history = fakeRouterEnvironment(options.hash ?? '#n=sessions');
  const router = createRouter(history.env);
  const clock = createFakeClock();
  const env = createFakeEnvironment({ clock, streamSupported: true });
  const state = {
    data: options.data as unknown,
    revision: 1,
    answer: options.answer ?? ({ kind: 'confirm' } as AnswerScript),
    requests: [] as Request[],
    held: null as null | ((response: Response) => void),
    /** While set, the next board read waits for `releaseData`, as a slow refresh would. */
    holdData: false,
    heldData: null as null | (() => void),
  };
  const fetch: FetchLike = (url, init) => {
    const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : null;
    state.requests.push({ method: init?.method ?? 'GET', url, body });
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
    if (options.context !== undefined && url.startsWith('/api/project-context'))
      return Promise.resolve(new Response(JSON.stringify(options.context), { status: 200 }));
    if (url === '/api/answer') {
      const script = state.answer;
      switch (script.kind) {
        case 'confirm':
          return Promise.resolve(
            new Response(JSON.stringify({ ok: true, answered: true }), { status: 200 }),
          );
        case 'refuse':
          return Promise.resolve(
            new Response(JSON.stringify({ ok: true, answered: false }), { status: 200 }),
          );
        case 'status':
          return Promise.resolve(new Response('no', { status: script.status }));
        case 'not-json':
          return Promise.resolve(new Response('<html>', { status: 200 }));
        case 'offline':
          return Promise.reject(new Error('offline'));
        case 'hold':
          return new Promise<Response>((resolve) => {
            state.held = resolve;
          });
      }
    }
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
    state.revision += 1;
    return Promise.resolve(
      new Response(JSON.stringify(state.data), {
        status: 200,
        headers: { 'X-Compass-Revision': `7.${String(state.revision)}` },
      }),
    );
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
  return {
    ...view,
    shell,
    router,
    clock,
    state,
    written,
    history,
    gets: () =>
      state.requests.filter(
        (request) => request.method === 'GET' && request.url.startsWith('/api/data'),
      ).length,
    posts: () => state.requests.filter((request) => request.method !== 'GET'),
    settle: () => act(async () => void (await flush())),
    /** Lets the held board read answer, as a slow refresh would. */
    async releaseData() {
      await act(async () => {
        state.holdData = false;
        state.heldData?.();
        state.heldData = null;
        await flush();
      });
    },
    /** Answers the held answer request, as the server would. */
    async release(response: Response) {
      await act(async () => {
        state.held?.(response);
        state.held = null;
        await flush();
      });
    },
    /** The next board, as a poll would bring it. */
    async poll(next: unknown) {
      state.data = next;
      await act(async () => {
        const read = shell.runtime.refresh();
        await flush();
        // A reader's own toggle holds a background paint for the length of its motion, on the fake clock.
        clock.advance(500);
        await read;
        await flush();
      });
    },
  };
}
