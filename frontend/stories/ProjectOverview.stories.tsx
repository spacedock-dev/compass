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

const PROJECT = 'acme/dashboard';
const STAMP = new Date(2026, 10, 23, 14).getTime() / 1000;
const session = (title: string, state: string, extra = {}) => ({
  project: PROJECT,
  sid: title,
  title,
  state,
  harness: 'claude',
  started_at: STAMP - 300,
  last_activity: STAMP - 30,
  ...extra,
});
const working = session('Review the build', 'working', {
  instruction: { label: 'asked', text: 'Prepare the dashboard for review', at: STAMP - 240 },
  subagents: [{ name: 'Read the test output', active: true }],
});
const waiting = session('Request approval', 'needs_input');
const dirty = session('Write settings stories', 'idle', {
  ended_at: STAMP - 120,
  dirty: true,
  changed: 2,
});
const clean = session('Fix chart labels', 'idle', { ended_at: STAMP - 240, dirty: false });
const quiet = session('Review complete', 'idle', { finished_at: STAMP - 100 });
const unknown = session('Inspect the record', 'idle', { harness: 'codex' });
const noOutcome = session('Read the source', 'idle', { ended_at: STAMP - 30 });
const clipboard: string[] = [];

function Example({
  sessions,
  workflow = false,
  measure = false,
}: {
  readonly sessions: readonly ReturnType<typeof session>[];
  readonly workflow?: boolean;
  readonly measure?: boolean;
}) {
  const [storage] = useState(() => fakeBackend());
  const [reload, setReload] = useState(0);
  return (
    <ProjectMount
      key={reload}
      sessions={sessions}
      workflow={workflow}
      measure={measure}
      storage={storage}
      reload={() => setReload(reload + 1)}
    />
  );
}

function ProjectMount({
  sessions,
  workflow,
  measure,
  storage,
  reload,
}: {
  readonly sessions: readonly ReturnType<typeof session>[];
  readonly workflow: boolean;
  readonly measure: boolean;
  readonly storage: ReturnType<typeof fakeBackend>;
  readonly reload: () => void;
}) {
  const [shell] = useState(() => {
    clipboard.length = 0;
    let samples = 0;
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(fakeRouterEnvironment('#n=project:acme%2Fdashboard').env),
      provider: () => storage,
      doc: null,
      search: '',
      reducedMotion: () => true,
      host: { reload },
      clipboard: () => ({
        writeText: async (text) => {
          clipboard.push(text);
        },
      }),
      fetch: (url) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              url.startsWith('/api/data')
                ? {
                    generated: STAMP + (measure ? samples++ * 1200 : 0),
                    sessions,
                    harnesses: [
                      { key: 'claude', label: 'Claude Code' },
                      { key: 'codex', label: 'Codex' },
                    ],
                    tripwires: { enabled: workflow },
                  }
                : {},
            ),
          ),
        ),
    });
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return (
    <>
      <App shell={shell} />
      {measure ? (
        <button type="button" onClick={() => void shell.runtime.refresh()}>
          Record another observation
        </button>
      ) : null}
      <button type="button" className="sr-only" onClick={reload}>
        Reload example
      </button>
    </>
  );
}

const meta = {
  title: 'Project',
  component: Example,
  args: { sessions: [working, waiting, dirty, clean, quiet], workflow: false },
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Overview: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole('heading', { name: PROJECT })).toBeVisible();
    await expect(
      within(canvas.getByRole('region', { name: 'Working on' })).getByText(
        'Prepare the dashboard for review',
      ),
    ).toBeVisible();
    const needs = within(canvas.getByRole('region', { name: 'Needs you' }));
    await expect(
      needs.getByText('1 waiting on you · 1 worth a look', { exact: true }),
    ).toBeVisible();
    const end = within(canvas.getByRole('region', { name: 'How today’s sessions ended' }));
    await expect(end.getByRole('heading', { name: 'Worth a look' })).toBeVisible();
    await expect(
      end.getByText('Ended with uncommitted work (2 changed entries)', { exact: true }),
    ).toBeVisible();
    await expect(end.getByRole('heading', { name: 'Ready to wrap up' })).toBeVisible();
    await expect(end.getByText('Ended with a clean working tree', { exact: true })).toBeVisible();
    await expect(
      canvas.getByText('Waiting for enough recorded working time.', { exact: true }),
    ).toBeVisible();
  },
};

export const CopyAndNotes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Copy a status update' }));
    await expect(await canvas.findByRole('button', { name: 'Copied' })).toBeVisible();
    await expect(clipboard).toHaveLength(1);
    await expect(clipboard[0]).toContain('Project: dashboard');
    await expect(canvasElement.querySelector('details')).toBeNull();
    const notes = canvas.getByRole('textbox', { name: 'Your notes' });
    await userEvent.type(notes, 'Review the new checklist tomorrow');
    await expect(canvas.queryByRole('button', { name: /Save note/ })).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: 'Reload example' }));
    await expect(await canvas.findByRole('textbox', { name: 'Your notes' })).toHaveValue(
      'Review the new checklist tomorrow',
    );
  },
};

export const MeasuredTime: Story = {
  args: { sessions: [working], measure: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const time = within(
      await canvas.findByRole('region', { name: 'Time agents worked on their own' }),
    );
    const waiting = 'Waiting for enough recorded working time.';
    await expect(time.getByText(waiting, { exact: true })).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Record another observation' }));
    await expect(await time.findByText('100%', { exact: true })).toBeVisible();
    await expect(
      time.getByText('Over 20 minutes, you stepped in 0 times.', { exact: true }),
    ).toBeVisible();
    await expect(time.queryByText(waiting, { exact: true })).toBeNull();
  },
};

export const TechnicalDetails: Story = {
  args: { workflow: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole('button', { name: 'Show technical details' });
    await expect(canvas.getByText(/FO is the first officer/)).not.toBeVisible();
    await expect(canvas.getByText('Stage alerts', { exact: true })).not.toBeVisible();
    await expect(canvas.queryByText('Read-only terminal', { exact: true })).toBeNull();
    await expect(canvas.getByText('Your note (this tab only)', { exact: true })).not.toBeVisible();
    await userEvent.click(trigger);
    await waitFor(() =>
      expect(canvas.getByText(/FO is the first officer.*Captain is you/)).toBeVisible(),
    );
    await expect(canvas.getByRole('heading', { name: 'Stage alerts' })).toBeVisible();
    await expect(canvas.getByText('Your note (this tab only)', { exact: true })).toBeVisible();
    await expect(canvas.getByText('Read-only terminal', { exact: true })).toBeVisible();
    await expect(
      canvas.getByRole('combobox', { name: 'Session for the read-only terminal' }),
    ).toBeVisible();
    await expect(canvas.getByRole('button', { name: 'Hide technical details' })).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Hide technical details' }));
  },
};

function stateStory(row: ReturnType<typeof session>, state: string): Story {
  return {
    args: { sessions: [row] },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      const sessions = within(await canvas.findByRole('region', { name: 'Sessions' }));
      const link = within(sessions.getByRole('link', { name: new RegExp(row.title) }));
      for (const word of ['Waiting on you', 'Working', 'Ended', 'Quiet']) {
        await expect(Boolean(link.queryByRole('img', { name: word }))).toBe(word === state);
      }
      if (state === 'State not published')
        await expect(link.getByText(state, { exact: true })).toBeVisible();
      else await expect(link.queryByText('State not published', { exact: true })).toBeNull();
    },
  };
}

export const Working = stateStory(working, 'Working');
export const Waiting = stateStory(waiting, 'Waiting on you');
export const Quiet = stateStory(quiet, 'Quiet');
export const Ended = stateStory(dirty, 'Ended');
export const CodexStateNotPublished = stateStory(unknown, 'State not published');
export const EndOutcomeUnavailable: Story = {
  args: { sessions: [noOutcome] },
  play: async ({ canvasElement }) => {
    const end = within(
      await within(canvasElement).findByRole('region', { name: 'How today’s sessions ended' }),
    );
    await expect(end.getByText('No outcome was published', { exact: true })).toBeVisible();
    await expect(end.queryByRole('heading', { name: 'Ready to wrap up' })).toBeNull();
    await expect(end.queryByRole('heading', { name: 'Worth a look' })).toBeNull();
  },
};

function fit(width: number): Story {
  return {
    play: async ({ canvasElement }) => {
      await within(canvasElement).findByRole('heading', { name: PROJECT });
      await atPageWidth(width, async () => {
        await expect(
          within(canvasElement).getByRole('textbox', { name: 'Your notes' }),
        ).toBeVisible();
      });
    },
  };
}
export const Fits390 = fit(390);
export const Fits375 = fit(375);
export const Fits320 = fit(320);
