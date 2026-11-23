import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { atPageWidth } from './PageFit';

const NOW = new Date(2026, 10, 23, 14).getTime() / 1000;
const session = (project: string, state: string, details = {}) => ({
  project,
  sid: project,
  state,
  harness: 'claude',
  last_activity: NOW - 120,
  ...details,
});
const waiting = session('acme/api', 'needs_input', {
  instruction: { label: 'asked', text: 'Check sign-in', at: NOW - 300 },
});
const working = session('acme/dashboard', 'working', {
  instruction: { label: 'asked', text: 'Review the security checklist', at: NOW - 350 },
});
const ended = session('acme/billing', 'idle', { ended_at: NOW - 600, dirty: true, changed: 3 });
const quiet = session('acme/website', 'idle', { finished_at: NOW - 200 });
const unknown = session('acme/unseen', 'idle', { harness: 'codex' });
const earlier = Array.from({ length: 6 }, (_, index) =>
  session(`acme/older-${String(index + 1)}`, 'idle', { ended_at: NOW - 86400 - index }),
);

type Board = { readonly sessions: readonly ReturnType<typeof session>[]; readonly stage?: boolean };
let refresh: (() => Promise<unknown>) | undefined;
function Example({ sessions, stage = false }: Board) {
  const [shell] = useState(() => {
    let request = 0;
    const backend = fakeBackend();
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(fakeRouterEnvironment('#n=projects').env),
      provider: () => backend,
      doc: null,
      search: '',
      reducedMotion: () => true,
      fetch: (url) => {
        request += 1;
        return Promise.resolve(
          new Response(
            JSON.stringify(
              url.startsWith('/api/data')
                ? { generated: NOW + request, sessions, tripwires: { enabled: stage } }
                : {},
            ),
            { headers: { 'X-Compass-Revision': `7.${String(request)}` } },
          ),
        );
      },
    });
  });
  useEffect(() => {
    refresh = () => shell.runtime.refresh();
    return () => {
      refresh = undefined;
      shell.runtime.dispose();
      shell.display.dispose();
    };
  }, [shell]);
  return <App shell={shell} />;
}

const meta = {
  title: 'Projects',
  component: Example,
  args: { sessions: [waiting, working, ended, quiet, unknown, ...earlier], stage: true },
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ManyProjects: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const active = await canvas.findByRole('list', { name: 'Active today · 3' });
    const rows = within(active).getAllByRole('link');
    await expect(rows[0]).toHaveTextContent('acme/api');
    await expect(within(active).getByRole('img', { name: '1 waiting on you' })).toBeVisible();
    await expect(within(active).getByRole('img', { name: '1 worth a look' })).toBeVisible();
    const legend = within(canvas.getByRole('list', { name: 'What the icons mean' }));
    await expect(legend.getAllByRole('listitem')).toHaveLength(5);
    await expect(legend.getByText('Worth a look')).toBeVisible();
    await expect(canvas.getByText('Stage alerts', { exact: true })).not.toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Show technical details' }));
    await waitFor(() =>
      expect(canvas.getByRole('heading', { name: 'Stage alerts' })).toBeVisible(),
    );
    await userEvent.click(canvas.getByRole('button', { name: 'Hide technical details' }));
  },
};
export const OneProject: Story = {
  args: { sessions: [working], stage: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(
        'All your sessions are in one project. You can see them together on Sessions.',
      ),
    ).toBeVisible();
    await expect(canvas.getByRole('link', { name: 'Projects', current: 'page' })).toBeVisible();
    await expect(canvas.getByRole('link', { name: 'Go to Sessions' })).toHaveAttribute(
      'href',
      '#n=sessions',
    );
    await expect(canvas.queryByRole('searchbox')).toBeNull();
  },
};
export const SixProjects: Story = {
  args: { sessions: earlier, stage: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole('heading', { name: 'No recent activity · 6' }),
    ).toBeVisible();
    await expect(canvas.queryByRole('searchbox')).toBeNull();
  },
};
export const SevenProjects: Story = {
  args: { sessions: [working, ...earlier], stage: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const search = await canvas.findByRole('searchbox', { name: 'Search projects' });
    await userEvent.type(search, 'older-6');
    await expect(canvas.getByRole('link', { name: /acme\/older-6/ })).toBeVisible();
    await expect(canvas.queryByText('No project matches.')).toBeNull();
    await userEvent.type(search, 'xyz');
    await expect(canvas.getByText('No project matches.')).toBeVisible();
  },
};
export const ExpansionSurvivesRefresh: Story = {
  args: { sessions: [working, ...earlier], stage: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const recent = within(await canvas.findByRole('list', { name: 'No recent activity · 6' }));
    await expect(recent.getAllByRole('link')).toHaveLength(3);
    await userEvent.click(canvas.getByRole('button', { name: 'Show 3 more' }));
    await expect(recent.getAllByRole('link')).toHaveLength(6);
    await refresh?.();
    await expect(recent.getAllByRole('link')).toHaveLength(6);
    await userEvent.click(canvas.getByRole('button', { name: 'Show fewer' }));
    await expect(recent.getAllByRole('link')).toHaveLength(3);
  },
};

function stateStory(row: ReturnType<typeof session>, state: string): Story {
  return {
    args: { sessions: [row], stage: false },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      const link = await canvas.findByRole('link', { name: new RegExp(row.project) });
      const tile = within(link);
      for (const word of ['Waiting on you', 'Working', 'Ended', 'Quiet']) {
        const icon = tile.queryByRole('img', { name: word, exact: true });
        await expect(Boolean(icon)).toBe(word === state);
      }
      if (state === 'State not published')
        await expect(tile.getByText(state, { exact: true })).toBeVisible();
      else await expect(tile.queryByText('State not published', { exact: true })).toBeNull();
    },
  };
}
export const Waiting = stateStory(waiting, 'Waiting on you');
export const Working = stateStory(working, 'Working');
export const Ended = stateStory(ended, 'Ended');
export const Quiet = stateStory(quiet, 'Quiet');
export const StateNotPublished = stateStory(unknown, 'State not published');

function fit(width: number): Story {
  return {
    play: async ({ canvasElement }) => {
      await within(canvasElement).findByRole('heading', { name: 'Active today · 3' });
      await atPageWidth(width, async () => {
        const rows = [...canvasElement.querySelectorAll('.project-list-row')];
        const heights = rows.map((row) => row.getBoundingClientRect().height);
        await expect(rows.length).toBeGreaterThan(3);
        await expect(new Set(heights).size).toBe(1);
      });
    },
  };
}
export const Fits390 = fit(390);
export const Fits375 = fit(375);
export const Fits320 = fit(320);
