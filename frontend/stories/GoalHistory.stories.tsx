import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { settled } from './a11y.audit';
import { atPageWidth } from './PageFit';

const generated = 2_000_000_000;
const project = 'Example project';
const sessions = [
  { harness: 'claude', sid: 'typed', title: 'Repair login', project },
  { harness: 'codex', sid: 'adopted', title: 'Deploy the dashboard', project },
  { harness: 'claude', sid: 'empty', title: 'Write onboarding examples', project },
];
const annotations = [
  { harness: 'claude', sid: 'typed', goal: 'Stabilize deployment', at: generated - 60 },
  {
    harness: 'codex',
    sid: 'adopted',
    goal: 'Prepare a release',
    at: generated - 120,
    goal_source: 'first-prompt',
    assessment: { level: 'off_course' },
  },
  {
    harness: 'claude',
    sid: 'older',
    title: 'Archive deployment notes',
    goal: 'Save release notes',
    at: generated - 150,
  },
  ...['Update charts', 'Review labels', 'Save instructions'].map((goal, index) => ({
    harness: 'claude',
    sid: `older-${index}`,
    goal,
    at: generated - 180 - index,
  })),
  { harness: 'claude', sid: 'gone', discarded_at: generated - 240 },
];
type Scenario = 'normal' | 'unread' | 'error' | 'off' | 'withdrawal' | 'later-error';

function Example({
  scenario = 'normal',
  onConnect,
}: {
  readonly scenario?: Scenario;
  readonly onConnect?: (refresh: () => Promise<void>, requests: string[]) => void;
}) {
  const [{ shell, writes, refresh }] = useState(() => {
    let revision = 0;
    let refreshed = false;
    const requests: string[] = [];
    const shell = createShell({
      env: createFakeEnvironment(),
      router: createRouter(fakeRouterEnvironment('#n=intent').env),
      provider: () => fakeBackend(),
      doc: null,
      search: '',
      reducedMotion: () => true,
      fetch: (url, init) => {
        if (init?.method === 'POST') requests.push(url);
        if (url.startsWith('/api/data')) {
          revision += 1;
          return Promise.resolve(
            new Response(
              JSON.stringify({
                generated: generated + revision - 1,
                annotate: scenario !== 'off',
                intent_revision: refreshed && scenario !== 'normal' ? 'r2' : 'r1',
                sessions,
              }),
              { headers: { 'X-Compass-Revision': `10.${revision}` } },
            ),
          );
        }
        if (url.startsWith('/api/annotations')) {
          if (scenario === 'error' || (refreshed && scenario === 'later-error'))
            return Promise.resolve(new Response('{}', { status: 500 }));
          if (scenario === 'unread') return new Promise<Response>(() => undefined);
          const withdrawn = refreshed && scenario === 'withdrawal';
          const kept = withdrawn
            ? [
                { harness: 'claude', sid: 'typed', discarded_at: generated - 60 },
                ...annotations.slice(1),
              ]
            : annotations;
          return Promise.resolve(
            new Response(
              JSON.stringify({ annotations: kept, intent_revision: withdrawn ? 'r2' : 'r1' }),
            ),
          );
        }
        return Promise.resolve(new Response('{}'));
      },
    });
    return {
      shell,
      writes: requests,
      refresh: async () => {
        refreshed = true;
        await shell.runtime.refresh();
      },
    };
  });
  useEffect(() => {
    onConnect?.(refresh, writes);
  }, [onConnect, refresh, writes]);
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
  title: 'Board/Goal history',
  component: Example,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

const otherStates =
  /No goal yet\.|Saved goal unavailable\.|You discarded this goal|Taken from your first prompt|You wrote this/;

function goalRow(canvas: ReturnType<typeof within>, title: string) {
  const row = canvas.getByRole('heading', { name: title }).closest('li');
  if (!row) throw new Error('Missing goal history row');
  return within(row);
}

export const TypedGoal: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('Stabilize deployment');
    const panel = canvas.getByRole('heading', { name: 'On the board now' }).closest('section');
    await expect(getComputedStyle(panel as Element).backgroundColor).toBe('rgb(255, 255, 255)');
    const row = goalRow(canvas, 'Repair login');
    await expect(row.getByText(/^You wrote this/)).toBeVisible();
    await expect(row.getByText('Saved 1 minute ago')).toBeVisible();
    await expect(row.queryAllByText(otherStates)).toHaveLength(1);
  },
};

export const AdoptedCodexGoal: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('Prepare a release');
    const row = goalRow(canvas, 'Deploy the dashboard');
    await expect(row.getByText(/^Taken from your first prompt/)).toBeVisible();
    await expect(row.getByText('Saved 2 minutes ago')).toBeVisible();
    await expect(row.queryAllByText(otherStates)).toHaveLength(1);
    const view = canvasElement.querySelector('[data-next-view-body="intent"]');
    await expect(view?.textContent).not.toMatch(
      /\b(?:On track|Slightly off course|Off course|Way off course|Show technical details)\b/i,
    );
  },
};

export const DiscardedGoal: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Show 2 more' }));
    const row = goalRow(canvas, 'Older session');
    await expect(row.getByText('You discarded this goal')).toBeVisible();
    await expect(row.getByText('Discarded 4 minutes ago')).toBeVisible();
    await expect(row.queryAllByText(otherStates)).toHaveLength(1);
    await expect(row.queryByRole('link')).toBeNull();
  },
};

export const AddAGoal: Story = {
  play: async ({ canvasElement, mount }) => {
    let requests: string[] = [];
    await mount(
      <Example
        onConnect={(_, writes) => {
          requests = writes;
        }}
      />,
    );
    const canvas = within(canvasElement);
    await canvas.findByText('No goal yet.');
    const row = goalRow(canvas, 'Write onboarding examples');
    await expect(row.getByText('No goal yet.')).toBeVisible();
    await expect(row.queryAllByText(otherStates)).toHaveLength(1);
    await userEvent.click(row.getByRole('link', { name: 'Add a goal' }));
    await expect(
      await canvas.findByRole('heading', { level: 1, name: 'Write onboarding examples' }),
    ).toBeVisible();
    await expect(requests).toEqual([]);
  },
};

export const SearchBothGroups: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('Stabilize deployment');
    const search = canvas.getByRole('searchbox', { name: 'Search goals' });
    await userEvent.type(search, 'deployment');
    await expect(canvas.getByText('Stabilize deployment')).toBeVisible();
    await expect(canvas.getByText('Archive deployment notes')).toBeVisible();
    await expect(canvas.queryByText('Write onboarding examples')).toBeNull();
    await userEvent.clear(search);
    await userEvent.type(search, 'No matching words');
    await expect(canvas.getByText('No goals or session titles match your search.')).toBeVisible();
    await expect(canvas.queryByRole('heading', { name: 'Older sessions' })).toBeNull();
    await expect(canvas.queryByRole('heading', { name: 'On the board now' })).toBeNull();
  },
};

export const UnreadableStore: Story = {
  args: { scenario: 'error' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText('Compass could not read your saved goals.')).toBeVisible();
    const row = goalRow(canvas, 'Repair login');
    await expect(row.getByText('Saved goal unavailable.')).toBeVisible();
    await expect(row.queryAllByText(otherStates)).toHaveLength(1);
    await expect(canvas.queryByText('Loading saved goals.')).toBeNull();
    await expect(canvas.queryByText('Stabilize deployment')).toBeNull();
  },
};

export const LoadingStore: Story = {
  args: { scenario: 'unread' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { name: 'Repair login' });
    await expect(canvas.getByText('Loading saved goals.')).toBeVisible();
    const row = goalRow(canvas, 'Repair login');
    await expect(row.getByText('Saved goal unavailable.')).toBeVisible();
    await expect(row.queryAllByText(otherStates)).toHaveLength(1);
    await expect(canvas.queryByText('Compass could not read your saved goals.')).toBeNull();
  },
};

export const SavingOff: Story = {
  args: { scenario: 'off' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText('Saving goals is off for this run.')).toBeVisible();
    const row = goalRow(canvas, 'Repair login');
    await expect(row.getByText('Saved goal unavailable.')).toBeVisible();
    await expect(row.queryAllByText(otherStates)).toHaveLength(1);
    await expect(canvas.queryByText('Compass could not read your saved goals.')).toBeNull();
    await expect(canvas.queryByRole('link', { name: 'Add a goal' })).toBeNull();
  },
};

function replacesAReading(scenario: 'withdrawal' | 'later-error', words: string): Story {
  return {
    play: async ({ canvasElement, mount }) => {
      let refresh: (() => Promise<void>) | undefined;
      await mount(
        <Example
          scenario={scenario}
          onConnect={(run) => {
            refresh = run;
          }}
        />,
      );
      const canvas = within(canvasElement);
      await canvas.findByText('Stabilize deployment');
      if (!refresh) throw new Error('Missing refresh function');
      await refresh();
      const row = goalRow(canvas, 'Repair login');
      await expect(await row.findByText(words)).toBeVisible();
      await expect(row.queryAllByText(otherStates)).toHaveLength(1);
      await expect(row.queryByText('Stabilize deployment')).toBeNull();
      await expect(row.queryByRole('link', { name: 'Add a goal' })).toBeNull();
    },
  };
}

export const WithdrawnAfterRefresh = replacesAReading('withdrawal', 'You discarded this goal');
export const ReadFailsAfterRefresh = replacesAReading('later-error', 'Saved goal unavailable.');

export const ExpansionSurvivesRefresh: Story = {
  play: async ({ canvasElement, mount }) => {
    let refresh: (() => Promise<void>) | undefined;
    await mount(
      <Example
        onConnect={(run) => {
          refresh = run;
        }}
      />,
    );
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Show 2 more' }));
    await expect(canvas.getByText('Save instructions')).toBeVisible();
    if (!refresh) throw new Error('Missing refresh function');
    await refresh();
    await expect(canvas.getByRole('button', { name: 'Show fewer' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    await expect(canvas.getByText('Save instructions')).toBeVisible();
  },
};

export const Retention: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole('button', { name: 'How long goals are kept' });
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    await waitFor(() =>
      expect(
        canvas.getByText(/keeps goals for up to 256 sessions, with up to 16 revisions per session/),
      ).toBeVisible(),
    );
    await expect(
      canvas.getByText(/keeps a copy of goals and expected outcomes for 14 days/),
    ).toBeVisible();
    await expect(
      canvas.getByText(/Forget everything keeps typed goals and readings/),
    ).toBeVisible();
  },
};

function fit(width: number): Story {
  return {
    play: ({ canvasElement }) =>
      atPageWidth(width, async () => {
        const canvas = within(canvasElement);
        await canvas.findByText('Stabilize deployment');
        await userEvent.click(canvas.getByRole('button', { name: 'Show 2 more' }));
        await userEvent.click(canvas.getByRole('button', { name: 'How long goals are kept' }));
        await settled();
        const view = within(
          canvasElement.querySelector('[data-next-view-body="intent"]') as HTMLElement,
        );
        const controls = ['searchbox', 'link', 'button'].flatMap((role) => view.getAllByRole(role));
        for (const control of controls) {
          const box = control.getBoundingClientRect();
          if (box.height < 44)
            throw new Error(`Target is ${box.height}px tall: ${control.outerHTML}`);
          await expect(box.height).toBeGreaterThanOrEqual(44);
          await expect(box.width).toBeGreaterThanOrEqual(44);
        }
      }),
  };
}
export const Fits390 = fit(390);
export const Fits375 = fit(375);
export const Fits320 = fit(320);
