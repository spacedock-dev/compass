import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* A goal holds 1,000 characters since 2026-10-27, so a prompt chosen as the goal is kept whole. The
   Sessions list shows its first three lines and the session page the rest, so one long goal does not
   make its row ten lines tall. */
const NOW = 1900000000;
const LONG_GOAL =
  `Update this pull request so it matches the new release. ${'Keep every screenshot current and every link working. '.repeat(18)}`.slice(
    0,
    999,
  ) + '.';
const SHORT_GOAL = 'Tidy the placeholder module';

const SESSIONS = [
  {
    harness: 'claude',
    sid: 'long',
    project: 'demo',
    project_key: '/demo',
    title: 'Docs checkout',
    annotation_goal: LONG_GOAL,
    annotation_revision: 1,
    state: 'idle',
    started_at: NOW - 3600,
    last_activity_at: NOW - 600,
  },
  {
    harness: 'claude',
    sid: 'short',
    project: 'demo',
    project_key: '/demo',
    title: 'Placeholder tidy',
    annotation_goal: SHORT_GOAL,
    annotation_revision: 1,
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
          return Promise.resolve(
            json({
              generated: NOW,
              annotate: true,
              annotate_cap: 240,
              annotate_goal_cap: 1000,
              sessions: SESSIONS,
            }),
          );
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
  title: 'Sessions/A long goal',
  component: Example,
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

export const SessionsListShowsThreeLinesOfALongGoal: Story = {
  args: { hash: '#n=sessions' },
  play: async ({ canvasElement }) => {
    const goalLink = (text: string) =>
      [...canvasElement.querySelectorAll<HTMLElement>('.next-operation-goal-link')].find(
        (link) => link.textContent === text,
      );
    await waitFor(() => expect(goalLink(LONG_GOAL)).toBeDefined());
    const long = goalLink(LONG_GOAL) as HTMLElement;
    const short = goalLink(SHORT_GOAL) as HTMLElement;
    // The whole goal is in the link, for the session page and a screen reader; only three lines show.
    await expect(long.textContent).toHaveLength(1000);
    await expect(getComputedStyle(long).webkitLineClamp).toBe('3');
    const line = Number.parseFloat(getComputedStyle(short).lineHeight);
    await expect(long.getBoundingClientRect().height).toBeLessThanOrEqual(line * 3 + 1);
    await expect(long.scrollHeight).toBeGreaterThan(long.clientHeight);
  },
};
