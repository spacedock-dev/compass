/* Fixtures for the Intent panel's tests: a board with one Claude session the reader can annotate, and a
   scripted store behind `/api/annotate` and `/api/direction` that behaves the way the server's does, so a
   test can save words and then read them back from the next board. Not imported by production code. */
import { fireEvent } from '@testing-library/react';
import { json, mountIntent, type Handler, type IntentShellOptions } from './testing';

export const SESSION_HASH = '#n=session:alpha%2Fapp:claude:s1';

export interface Store {
  goal: string;
  lines: string[];
  revision: number;
  goal_source: string;
  goal_source_at: number | null;
  settled_through: number | null;
  discarded: boolean;
}

export function board(overrides: Record<string, unknown> = {}, store: Partial<Store> = {}) {
  const held: Store = {
    goal: '',
    lines: [],
    revision: 0,
    goal_source: '',
    goal_source_at: null,
    settled_through: null,
    discarded: false,
    ...store,
  };
  const lines: Record<string, unknown> = {};
  held.lines.forEach((line, index) => {
    lines[`annotation_line_${String(index + 1)}`] = line;
  });
  return {
    generated: 1000,
    annotate: true,
    annotate_cap: 240,
    annotate_goal_cap: 1000,
    intent_revision: 'r1',
    sessions: [
      {
        harness: 'claude',
        sid: 's1',
        project: 'alpha/app',
        project_key: '/repo/alpha',
        title: 'Alpha work',
        state: 'idle',
        first_prompt: 'Ship the queue worker',
        first_prompt_at: 100,
        annotation_goal: held.goal,
        annotation_goal_why: held.goal ? '' : 'No goal typed for this session.',
        annotation_lines_why: held.lines.length ? '' : 'No expected outcome typed.',
        annotation_revision: held.revision,
        annotation_revision_count: held.revision ? 1 : 0,
        annotation_at: held.revision ? 990 : null,
        annotation_goal_source: held.goal_source,
        annotation_goal_source_at: held.goal_source_at,
        annotation_settled_through: held.settled_through,
        ...lines,
        ...overrides,
      },
    ],
  };
}

export const stored = (revision: number, extra: Record<string, unknown> = {}) =>
  json({
    ok: true,
    outcome: 'stored',
    persisted: true,
    revision,
    saved_revision: revision,
    revision_count: 1,
    ...extra,
  });

export const OPEN_DIRECTION: Handler = () =>
  json({ ok: true, text: 'Do it the careful way', clipped: false });

export function mountSession(
  options: IntentShellOptions & {
    readonly store?: Partial<Store>;
    readonly session?: Record<string, unknown>;
  } = {},
) {
  const { store, session, ...rest } = options;
  return mountIntent({
    hash: SESSION_HASH,
    data: board(session ?? {}, store ?? {}),
    ...rest,
  });
}

/* The goal box, the outcome boxes and the footer, as a reader meets them. */
export const goalBox = (): HTMLTextAreaElement =>
  document.querySelector('textarea[data-next-cockpit-held-kind="goal"]') as HTMLTextAreaElement;
export const lineBoxes = (): HTMLTextAreaElement[] => [
  ...document.querySelectorAll<HTMLTextAreaElement>('textarea[data-next-cockpit-held-line-index]'),
];
export const control = (action: string, arg?: string): HTMLButtonElement | null =>
  document.querySelector<HTMLButtonElement>(
    `[data-next-cockpit-action="${action}"]${arg === undefined ? '' : `[data-arg="${arg}"]`}`,
  );
export const inert = (button: Element | null): boolean =>
  button?.getAttribute('aria-disabled') === 'true';

/* A keystroke the way the browser delivers one: the native value changes, then `input` fires. */
export function type(box: HTMLTextAreaElement, value: string): void {
  box.value = value;
  fireEvent.input(box);
}

export const text = (selector: string): string =>
  (document.querySelector(selector)?.textContent ?? '').replace(/\s+/g, ' ').trim();

/* A lease the server holds as the page reads it, and a route that answers every lease call with it as
   accepted: for a test that needs the Live monitor on and is not about the lease. */
export const monitorLease = (over: Record<string, unknown> = {}) => ({
  on: true,
  started_at: 1000,
  banner_due_at: 2200,
  deadline: 2800,
  confirm_by: null,
  visible: true,
  last_end: null,
  level: null,
  label: 'Live monitor · Haiku',
  model: 'claude-haiku-5-5',
  destination: 'api.anthropic.com',
  disclosure: 'Sends to api.anthropic.com through your Claude Code, to Haiku.',
  interval_sec: 60,
  now: 1100,
  ...over,
});
export const LEASE_ROUTE: Handler = () => json({ ok: true, reason: '', state: monitorLease() });
