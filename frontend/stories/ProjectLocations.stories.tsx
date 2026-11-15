import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within, waitFor } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { locationBoard, locationRow, locationRows } from '../test/location_boards';

function Board({
  locations = 1,
  checkout = 'idle',
}: {
  readonly locations?: number;
  readonly checkout?: 'idle' | 'shared' | 'distinct' | 'missing';
}) {
  const [shell] = useState(() => {
    const data = locationBoard(checkout === 'idle' ? 9 : 2);
    if (checkout !== 'idle')
      for (const [i, row] of locationRows(data).entries())
        Object.assign(row, {
          state: 'working',
          project_key: 'git:audits',
          project_identity_source: 'git common directory',
          worktree: 'audit',
          checkout_key:
            checkout === 'missing'
              ? null
              : checkout === 'distinct'
                ? `checkout:${String(i)}`
                : 'checkout:shared-evidence',
        });
    if (locations > 1) locationRow(data, 8)['project_key'] = 'path:other';
    const clock = createFakeClock();
    return createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(fakeRouterEnvironment('#n=attention').env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: () => Promise.resolve(new Response(JSON.stringify(data), { status: 200 })),
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

const meta = { title: 'Attention/Project locations', component: Board } satisfies Meta<
  typeof Board
>;
export default meta;
type Story = StoryObj<typeof meta>;

export const OneMeasuredLocation: Story = {
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText(/of 9 sessions carry a subject/);
    await expect(canvasElement.querySelector('[data-next-board-risk="collision"]')).toBeNull();
    await expect(canvasElement.textContent).not.toContain('shared location is not established');
  },
};

export const TwoMeasuredLocations: Story = {
  args: { locations: 2 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole('link', { name: 'Label shared across locations' }),
    ).toHaveAttribute('href', '#n=project:audits');
    const card = canvasElement.querySelector('[data-next-board-risk="collision"]') as HTMLElement;
    await expect(card).toHaveTextContent('2 measured locations');
    await expect(card).toHaveTextContent('title, worktree, id and start time');
    await waitFor(() =>
      expect(within(card).getAllByRole('link', { name: /Audit \d/ })).toHaveLength(9),
    );
    for (let i = 0; i < 9; i++)
      await expect(
        within(card).getByRole('link', { name: new RegExp(`Audit ${String(i)} `) }),
      ).toHaveAttribute('href', `#n=session:audits:claude:audit-${String(i)}`);
  },
};

export const SharedCheckout: Story = {
  args: { checkout: 'shared' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole('link', { name: 'Concurrent sessions in one checkout' }),
    ).toHaveAttribute('href', '#n=project:audits');
    const card = canvasElement.querySelector('[data-next-board-risk="checkout"]') as HTMLElement;
    await expect(within(card).getAllByRole('link', { name: /Audit \d/ })).toHaveLength(2);
    await expect(card).toHaveTextContent('2 sessions working or waiting in the same checkout');
    await expect(card.textContent).not.toContain('checkout:shared-evidence');
  },
};

export const SameNameDistinctCheckouts: Story = {
  args: { checkout: 'distinct' },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText(/of 2 sessions carry a subject/);
    await expect(canvasElement.querySelector('[data-next-board-risk="checkout"]')).toBeNull();
  },
};

export const MissingCheckoutEvidence: Story = {
  args: { checkout: 'missing' },
  play: SameNameDistinctCheckouts.play,
};
