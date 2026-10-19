/* Fixtures for the Drift step's tests: a board with one Claude session that has saved words, a reader the
   server can name, and a scripted backend that answers each route on its own terms. No model is ever
   reached: the reading route is a double, and a test that does not script it sees it refused with a 404, so
   a request nobody meant to make fails loudly. Not imported by production code. */
import { act, fireEvent } from '@testing-library/react';
import { json } from '../intent/testing';
import { board, mountSession, SESSION_HASH, type Store } from '../intent/panel.testing';
import type { IntentShellOptions, Handler, RecordedRequest } from '../intent/testing';

export { json, SESSION_HASH, type Handler };

export const ROUTE = {
  provider: 'claude',
  harness: 'claude',
  destination: 'api',
  words_destination: 'api',
  label: 'Claude Code',
  model: 'm',
  disclosure: 'This sends the session to Claude Code.',
  disclosure_parts: ['Your saved words.', 'The agent messages.'],
  tool_output: 'Tool output goes to the api.',
};

export const POLICY = {
  consent: true,
  off: false,
  reason: '',
  providers: { claude: true },
  words: { claude: true },
  tool_output: { claude: ['api'] },
  used: 1,
  limit: 10,
};

export function driftBoard(
  options: {
    readonly payload?: Record<string, unknown>;
    readonly session?: Record<string, unknown>;
    readonly store?: Partial<Store>;
  } = {},
) {
  const base = board(
    { turn_end_at: 990, ...(options.session ?? {}) },
    { goal: 'Ship the queue', lines: ['Tests pass'], revision: 3, ...(options.store ?? {}) },
  );
  return {
    ...base,
    reading_check: 'passed',
    reading: POLICY,
    reading_routes: { claude: ROUTE },
    ...(options.payload ?? {}),
  };
}

export const fact = (id: string, at: number, extra: Record<string, unknown> = {}) => ({
  fact_id: id,
  type: 'user_message',
  by: 'person:me',
  summary: `Entry ${id}`,
  at,
  source_session: { harness: 'claude', sid: 's1' },
  evidence: { source: 'transcript', confidence: 'exact' },
  ...extra,
});

export const check = (id: string, at: number, result: string, extra = {}) =>
  fact(id, at, {
    type: 'tool_report',
    by: 'agent',
    subject: 'check',
    result,
    result_source: 'passed flag',
    summary: 'pytest',
    ...extra,
  });

export const contextRoute =
  (facts: unknown[], work: Record<string, unknown> = {}): Handler =>
  () =>
    json({ semantic: { facts }, sources: { work: { tool_reports: [], ...work } } });

export function mountDrift(
  options: IntentShellOptions & {
    readonly payload?: Record<string, unknown>;
    readonly session?: Record<string, unknown>;
    readonly store?: Partial<Store>;
    readonly facts?: unknown[];
  } = {},
) {
  const { payload, session, store, facts, routes, ...rest } = options;
  const data = driftBoard({
    ...(payload ? { payload } : {}),
    ...(session ? { session } : {}),
    ...(store ? { store } : {}),
  });
  return mountSession({
    ...rest,
    routes: {
      '/api/project-context': contextRoute(facts ?? []),
      '/api/annotations': () => json({ annotations: [], intent_revision: 'r1' }),
      ...(routes ?? {}),
    },
    data,
  } as never);
}

/* Full activity starts collapsed; a reader opens it before reading or paging the record. Idempotent, so a
   test may call it after every settle. */
export const openActivity = async (): Promise<void> => {
  const trigger = document.querySelector('[data-next-full-activity-trigger]');
  if (!trigger || trigger.getAttribute('aria-expanded') === 'true') return;
  await act(async () => {
    fireEvent.click(trigger);
  });
};

export const byAction = (action: string): HTMLButtonElement | null =>
  document.querySelector<HTMLButtonElement>(`[data-next-cockpit-action="${action}"]`);

export const press = async (button: Element | null): Promise<void> => {
  if (!button) throw new Error('no such control');
  await act(async () => {
    fireEvent.click(button);
  });
};

export const textOf = (selector: string): string =>
  (document.querySelector(selector)?.textContent ?? '').replace(/\s+/g, ' ').trim();

export const readingPosts = (page: { state: { requests: RecordedRequest[] } }) =>
  page.state.requests.filter((r) => r.method === 'POST' && r.path === '/api/reading');
