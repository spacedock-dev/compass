import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, within } from 'storybook/test';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

const generated = Date.UTC(2026, 10, 23, 12) / 1000;
const claude = { project: 'acme/api', harness: 'claude' };
const board = {
  generated,
  window_hours: 24,
  irreversible_enabled: true,
  command_reports: [
    {
      harness: 'claude',
      sid: 'review',
      label: 'Cleanup command',
      tool_name: 'Bash',
      timestamp: generated - 240,
    },
  ],
  sessions: [
    {
      ...claude,
      sid: 'sign-in',
      title: 'Fix the flaky sign-in test',
      state: 'needs_input',
      blocked_since: generated - 360,
      state_detail: 'Waiting for command approval',
      wait_unconfirmed: true,
    },
    {
      ...claude,
      sid: 'review',
      title: 'Review pull request #482',
      ended_at: generated - 1500,
      dirty: true,
      changed: 2,
    },
    {
      ...claude,
      sid: 'dependencies',
      title: 'Nightly dependency check',
      state: 'idle',
      active: true,
      finished_at: generated - 10800 + 0.25,
    },
    {
      ...claude,
      sid: 'billing',
      title: 'Move billing to the new API',
      ended_at: generated - 7200,
      finished_at: generated - 7200,
      dirty: false,
    },
    {
      ...claude,
      sid: 'charts',
      title: 'Fix chart tooltips',
      ended_at: generated - 240,
      finished_at: generated - 240,
      dirty: false,
    },
    { ...claude, sid: 'untimed', state: 'needs_input', state_detail: 'Awaiting confirmation' },
    {
      ...claude,
      sid: 'long',
      state: 'working',
      state_detail: 'Working',
      turn: { elapsed_h: '1h 10m', eta_h: '5m', long: true },
    },
  ],
};

function Example() {
  const [shell] = useState(() => {
    const backend = fakeBackend();
    return createShell({
      env: createFakeEnvironment(),
      router: createRouter(fakeRouterEnvironment('#n=attention').env),
      provider: () => backend,
      doc: null,
      search: '',
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(new Response(url.startsWith('/api/data') ? JSON.stringify(board) : '{}')),
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
  title: 'Board/Needs you',
  component: Example,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ReadableTimes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { name: /Needs you now/ });
    const wait = canvasElement.querySelector(
      '[data-next-attention-subject=\'session:["claude","sign-in"]\']',
    );
    await expect(wait).toHaveTextContent('Waiting for command approval');
    await expect(wait).toHaveTextContent('waiting 6 minutes');
    await expect(wait).toHaveTextContent('in 5 minutes');
    const untimed = canvasElement.querySelector(
      '[data-next-attention-subject=\'session:["claude","untimed"]\']',
    );
    await expect(untimed).toHaveTextContent('Awaiting confirmation');
    await expect(untimed).not.toHaveTextContent(/waiting \d/);
    await expect(canvas.getByText(/ended 25 minutes ago/)).toBeVisible();
    await expect(canvas.getByText(/ended 2 hours ago/)).toBeVisible();
    await expect(canvas.getByText(/ended 4 minutes ago/)).toBeVisible();
    await expect(canvas.getByText(/Sources disagree .*stop observed at/)).toBeVisible();
    await expect(canvas.getByText(/1 hour 10 minutes into turn/)).toBeVisible();
    await expect(canvas.getByText(/Bash · 4 minutes ago/)).toBeVisible();
    const view = canvasElement.querySelector<HTMLElement>('[data-next-view-body="attention"]');
    await expect(view?.innerText).not.toMatch(/\b(?:\d{10}|\d{4}-\d{2}-\d{2}T|KiB|\d+[smhd]\b)/);
  },
};
