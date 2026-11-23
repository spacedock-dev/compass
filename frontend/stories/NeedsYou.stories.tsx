import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, within } from 'storybook/test';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

const generated = new Date(2026, 10, 23, 12).getTime() / 1000;
const claude = { project: 'acme/api', harness: 'claude' };
const board = {
  generated,
  window_hours: 24,
  ask: true,
  asks: [{ id: 'question', harness: 'claude', question: 'Proceed?', age_sec: 360 }],
  usage: [
    {
      harness: 'claude',
      state: 'ok',
      fiveH: { pct: 95, resetAt: generated + 3960, windowSec: 18000 },
      models: [{ pct: 95, label: 'fast', resetAt: generated + 3960 }],
    },
  ],
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
    {
      ...claude,
      sid: 'delegated',
      title: 'Inspect query plans',
      state: 'idle',
      delegated_launches: 2,
      delegated_unpaired: 1,
      delegated_quiet_since: generated - 3600,
      delegated_latest_launch_at: generated - 360,
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

const absoluteTimes = [new Date(2026, 10, 23, 9), new Date(2026, 10, 23, 10)];
const absoluteReset = new Date(2026, 10, 23, 13);
const withoutClock = {
  sessions: absoluteTimes.map((time, index) => ({
    ...claude,
    sid: `checkout-${index + 1}`,
    title: `Checkout ${index + 1}`,
    project_key: `path:checkout-${index + 1}`,
    started_at: time.getTime() / 1000,
  })),
  usage: [
    {
      harness: 'claude',
      state: 'ok',
      models: [{ pct: 95, label: 'fast', resetAt: absoluteReset.getTime() / 1000 }],
    },
  ],
};

function absoluteTime(time: Date) {
  const date = time.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
  const clock = time.toLocaleTimeString(undefined, { timeStyle: 'short' });
  return `on ${date} at ${clock}`;
}

function Example({ missingClock = false }: { readonly missingClock?: boolean }) {
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
        Promise.resolve(
          new Response(
            url.startsWith('/api/data')
              ? JSON.stringify(missingClock ? withoutClock : board)
              : '{}',
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
    await expect(canvas.getByText('1 hour 6 minutes')).toBeVisible();
    const reset = new Date((generated + 3960) * 1000).toLocaleTimeString(undefined, {
      timeStyle: 'short',
    });
    await expect(canvas.getByText(`Reset at ${reset}`)).toBeVisible();
    const launch = canvasElement.querySelector(
      '[data-next-attention-kind="quiet-launch"] .next-attention-risk-observation > p',
    );
    await expect(launch).toHaveTextContent('2 recorded launches');
    await expect(launch).toHaveTextContent('Latest launch 6 minutes ago');
    await expect(canvas.getByText('source · claude · waiting 6 minutes')).toBeVisible();
    const report = canvas.getByText(/Bash · 4 minutes ago/);
    await expect(report).toBeVisible();
    await expect(getComputedStyle(report).fontFamily).toMatch(/\bInter\b/i);
    const view = canvasElement.querySelector<HTMLElement>('[data-next-view-body="attention"]');
    await expect(view?.innerText).not.toMatch(/\b(?:\d{10}|\d{4}-\d{2}-\d{2}T|KiB|\d+[smhd]\b)/);
  },
};

export const AbsoluteTimesWithoutBoardClock: Story = {
  args: { missingClock: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText(`Reset ${absoluteTime(absoluteReset)}`);
    for (const [index, time] of absoluteTimes.entries()) {
      const member = canvas.getByRole('link', { name: new RegExp(`Checkout ${index + 1} ·`) });
      await expect(member).toHaveTextContent(`Start time ${absoluteTime(time)}`);
    }
  },
};
