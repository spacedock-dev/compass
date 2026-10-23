import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* A session that replaced its /goal is named by the goal it holds now. The collector publishes that
   goal as `title`; the first prompt stays the first condition, and no surface may name the session
   by it. The tab, the crumb, the heading and the Sessions row read the one published title. */
const NOW = 1900000000;
const OLD_GOAL = 'the placeholder parser handles every token type';
const NEW_GOAL = 'the placeholder lexer is split into modules under 300 lines';
const PLAIN = 'Tidy the placeholder module';

const SESSIONS = [
  {
    harness: 'claude',
    sid: 'replaced',
    project: 'demo',
    project_key: '/demo',
    title: NEW_GOAL,
    first_prompt: `/goal ${OLD_GOAL}`,
    first_prompt_at: NOW - 3600,
    session_goal: { text: NEW_GOAL, at: NOW - 600 },
    state: 'idle',
    started_at: NOW - 3600,
    last_activity_at: NOW - 600,
  },
  {
    harness: 'claude',
    sid: 'plain',
    project: 'demo',
    project_key: '/demo',
    title: PLAIN,
    first_prompt: PLAIN,
    first_prompt_at: NOW - 7200,
    state: 'idle',
    started_at: NOW - 7200,
    last_activity_at: NOW - 7000,
  },
];

function Example({ hash }: { readonly hash: string }) {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment(hash);
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) => {
        const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
        if (url.startsWith('/api/data'))
          return Promise.resolve(json({ generated: NOW, sessions: SESSIONS }));
        return Promise.resolve(json({}));
      },
    });
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return <App shell={shell} />;
}

const meta = {
  title: 'Sessions/Named by its goal',
  component: Example,
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

export const SessionsListNamesTheHeldGoal: Story = {
  args: { hash: '#n=sessions' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText(NEW_GOAL);
    await expect(canvasElement.textContent).not.toContain(OLD_GOAL);
    // A session with no /goal keeps its name.
    await expect(canvas.getByText(PLAIN)).toBeVisible();
  },
};

export const SessionPageNamesTheHeldGoal: Story = {
  args: { hash: '#n=session:demo:claude:replaced' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: NEW_GOAL });
    await waitFor(() => expect(document.title).toBe(`${NEW_GOAL} — demo — Compass`));
    await expect(canvas.getByText(NEW_GOAL, { selector: '[aria-current="page"]' })).toBeVisible();
    await expect(document.title).not.toContain(OLD_GOAL);
  },
};

export const SessionWithoutGoalKeepsItsName: Story = {
  args: { hash: '#n=session:demo:claude:plain' },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('heading', { level: 1, name: PLAIN });
    await waitFor(() => expect(document.title).toBe(`${PLAIN} — demo — Compass`));
  },
};
