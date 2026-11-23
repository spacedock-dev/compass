import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, within } from 'storybook/test';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { headerBoard } from '../test/headerBoard';
import { fakeBackend } from '../test/storage_backends';

function HeaderExample({ fragment }: { readonly fragment: string }) {
  const [shell] = useState(() => {
    const backend = fakeBackend();
    const clock = createFakeClock();
    return createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(fakeRouterEnvironment(fragment).env),
      provider: () => backend,
      doc: null,
      search: '',
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          url.startsWith('/api/data')
            ? new Response(JSON.stringify(headerBoard()))
            : new Response('{}'),
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
  title: 'Shell/Header',
  component: HeaderExample,
  args: { fragment: '#n=sessions' },
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof HeaderExample>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Sessions: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('2 sessions working');
    const pill = canvas.getByRole('status', { name: 'Working sessions' });
    await expect(pill).toHaveTextContent('2 sessions working');
    const nav = within(canvas.getByRole('navigation', { name: 'Primary' }));
    const linkNames = ['Sessions', 'Projects', 'Needs you 3', 'Goal history', 'Settings'];
    await expect(nav.getAllByRole('link')).toEqual(
      linkNames.map((name) => nav.getByRole('link', { name })),
    );
    const current = nav.getByRole('link', { name: 'Sessions', current: 'page' });
    await expect(current).toHaveStyle({ backgroundColor: 'rgb(230, 242, 236)' });
    await expect(canvas.getByRole('link', { name: 'Compass' })).toHaveAttribute(
      'href',
      '#n=sessions',
    );
    await expect(canvas.queryByRole('button', { name: /reported blocks?/ })).toBeNull();
  },
};

export const Project: Story = {
  args: { fragment: '#n=project:acme%2Fdashboard' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('2 sessions working');
    await expect(canvas.getByRole('status', { name: 'Working sessions' })).toHaveTextContent(
      '2 sessions working',
    );
    const nav = within(canvas.getByRole('navigation', { name: 'Primary' }));
    await expect(nav.getByRole('link', { name: 'Projects', current: 'page' })).toHaveStyle({
      backgroundColor: 'rgb(230, 242, 236)',
    });
    await userEvent.click(canvas.getByText('More', { selector: 'summary' }));
    await expect(canvas.getByRole('button', { name: 'Copy briefing' })).toBeVisible();
    await expect(canvas.queryByText(/All projects.*subagents observed/)).toBeNull();
    await userEvent.click(canvas.getByText('More', { selector: 'summary' }));
  },
};
