import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within, waitFor, userEvent } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { locationBoard, locationRow, locationRows } from '../test/location_boards';

function Board({
  hash = '#n=attention',
  locations = 1,
  checkout = 'idle',
  unknown = false,
  fallbacks = false,
  subdirectory = false,
  duplicate = false,
  mixedDuplicate = false,
}: {
  readonly hash?: string;
  readonly locations?: number;
  readonly subdirectory?: boolean;
  readonly duplicate?: boolean;
  readonly mixedDuplicate?: boolean;
  readonly unknown?: boolean;
  readonly fallbacks?: boolean;
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
    if (subdirectory) locationRow(data, 1)['project'] = 'audits/src';
    if (duplicate) {
      const row = locationRow(data, 0);
      row['project_identity_source'] = 'collector project label';
      row['state'] = 'working';
      data['sessions'] = [row, { ...row }, ...(mixedDuplicate ? [locationRow(data, 1)] : [])];
    }
    if (locations > 1) locationRow(data, 8)['project_key'] = 'path:other';
    if (unknown)
      locationRow(data, 7)['project_identity_source'] = 'inferred Claude worktree layout';
    if (fallbacks) Object.assign(locationRow(data, 8), { title: '   ', started_at: 0 });
    const clock = createFakeClock();
    return createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(fakeRouterEnvironment(hash).env),
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

async function expectNoWorthALook(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  await canvas.findByRole('button', { name: "What Compass can't see" });
  await expect(canvas.queryByRole('heading', { name: /Worth a look/ })).toBeNull();
}

async function worthALookRows(canvasElement: HTMLElement, count: number) {
  const heading = await within(canvasElement).findByRole('heading', {
    name: `Worth a look (${String(count)})`,
  });
  const section = heading.closest('section');
  const list = section?.querySelector(':scope > ol');
  if (!section || !list) throw new Error('Expected the Worth a look list');
  const rows = within(list as HTMLElement);
  await expect(rows.queryAllByRole('listitem')).toHaveLength(count);
  return rows;
}

export const ProjectShellLabels: Story = {
  args: { hash: '#n=project:audits' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const nav = within(canvas.getByRole('navigation', { name: 'Primary' }));
    await expect(nav.getAllByRole('link').map((link) => link.textContent)).toEqual([
      'Sessions',
      'Projects',
      'Needs you',
      'Goal history',
      'Settings',
      'Help',
    ]);
    await expect(nav.getByRole('link', { name: 'Projects', current: 'page' })).toBeVisible();
    const crumb = within(canvas.getByRole('navigation', { name: 'Breadcrumb' }));
    await expect(crumb.getByRole('link', { name: 'Projects' })).toHaveAttribute(
      'href',
      '#n=projects',
    );
    await expect(crumb.getByText('audits')).toHaveAttribute('aria-current', 'page');
    const tabs = await canvas.findByRole('tablist', { name: 'Project views' });
    const triggers = within(tabs).getAllByRole('tab');
    const labels = triggers.map((tab) =>
      Array.from(tab.childNodes)
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent)
        .join(''),
    );
    await expect(labels).toEqual(['Overview', 'Timeline', 'Decisions', 'Usage and alerts']);
    await expect(within(tabs).getByRole('tab', { name: 'Overview', selected: true })).toBeVisible();
    const course = within(tabs).getByRole('tab', {
      name: 'TimelineNo observed state changes observed',
    });
    await expect(within(course).getByText('0')).toBeVisible();
  },
};

export const OneMeasuredLocation: Story = {
  play: async ({ canvasElement }) => {
    await expectNoWorthALook(canvasElement);
    await expect(canvasElement.querySelector('[data-next-board-risk="collision"]')).toBeNull();
    await expect(canvasElement.textContent).not.toContain('shared location is not established');
  },
};

export const TwoMeasuredLocations: Story = {
  args: { locations: 2 },
  play: async ({ canvasElement }) => {
    const rows = await worthALookRows(canvasElement, 9);
    await expect(canvasElement.querySelector('[data-next-board-risk="collision"]')).toBeNull();
    for (let i = 0; i < 9; i++) {
      const id = String(i);
      const row = rows
        .getByRole('heading', { name: `Audit ${id}` })
        .closest('article') as HTMLElement;
      const link = within(row).getByRole('link', { name: 'Open session' });
      await expect(link).toHaveAttribute('href', `#n=session:audits:claude:audit-${id}`);
      await expect(link.closest('li')).toHaveTextContent(
        '9 sessions share this display label across 2 measured locations',
      );
    }
  },
};

export const SharedCheckout: Story = {
  args: { checkout: 'shared' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: "What Compass can't see" }));
    await expect(
      await canvas.findByRole('link', { name: 'Concurrent sessions in one checkout' }),
    ).toHaveAttribute('href', '#n=project:audits');
    const card = canvasElement.querySelector('[data-next-board-risk="checkout"]') as HTMLElement;
    await expect(within(card).getAllByRole('link', { name: /Audit \d/ })).toHaveLength(2);
    await expect(card).toHaveTextContent('2 sessions working or waiting in the same checkout');
    await expect(card.innerText).not.toContain('claude:audit-0');
    await userEvent.click(within(card).getByRole('button', { name: 'Show technical details' }));
    await waitFor(() => expect(within(card).getByText('claude:audit-0')).toBeVisible());
    await expect(card.textContent).not.toContain('checkout:shared-evidence');
  },
};

export const SameNameDistinctCheckouts: Story = {
  args: { checkout: 'distinct' },
  play: async ({ canvasElement }) => {
    await expectNoWorthALook(canvasElement);
    await expect(canvasElement.querySelector('[data-next-board-risk="checkout"]')).toBeNull();
  },
};

export const MissingCheckoutEvidence: Story = {
  args: { checkout: 'missing' },
  play: async ({ canvasElement }) => {
    await expectNoWorthALook(canvasElement);
    await expect(canvasElement.querySelector('[data-next-board-risk="checkout"]')).toBeNull();
  },
};

export const MixedMeasuredAndInferred: Story = {
  args: { locations: 2, unknown: true },
  play: async ({ canvasElement }) => {
    const rows = await worthALookRows(canvasElement, 8);
    await expect(canvasElement.querySelector('[data-next-board-risk="collision"]')).toBeNull();
    for (const i of [0, 1, 2, 3, 4, 5, 6, 8]) {
      const row = rows
        .getByRole('heading', { name: `Audit ${i}` })
        .closest('article') as HTMLElement;
      const link = within(row).getByRole('link', { name: 'Open session' });
      await expect(link).toHaveAttribute('href', `#n=session:audits:claude:audit-${String(i)}`);
      await expect(link.closest('li')).toHaveTextContent(
        '8 sessions share this display label across 2 measured locations. Location not measured for 1 session with this display label',
      );
    }
    await expect(rows.queryByRole('heading', { name: 'Audit 7' })).toBeNull();
  },
};

export const UnpublishedMemberDetails: Story = {
  args: { locations: 2, fallbacks: true },
  play: async ({ canvasElement }) => {
    const rows = await worthALookRows(canvasElement, 9);
    const last = rows
      .getAllByRole('listitem')
      .find((item) => item.textContent?.includes('claude:audit-8'));
    if (!last) throw new Error('Missing unpublished member');
    const row = within(last);
    await expect(row.getByRole('link', { name: 'Open session' })).toHaveAttribute(
      'href',
      '#n=session:audits:claude:audit-8',
    );
    await userEvent.click(row.getByRole('button', { name: 'Show technical details' }));
    await waitFor(() => expect(row.getByText(/Start time not published/)).toBeVisible());
    await expect(canvasElement.textContent).not.toContain('1970-01-01');
  },
};

export const RootAndSubdirectoryShareCheckout: Story = {
  args: { checkout: 'shared', subdirectory: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: "What Compass can't see" }));
    const heading = await canvas.findByRole('link', {
      name: 'Concurrent sessions in one checkout',
    });
    await expect(heading).toHaveAttribute('href', '#n=sessions');
    const card = canvasElement.querySelector('[data-next-board-risk="checkout"]') as HTMLElement;
    await expect(card).toHaveTextContent('2 sessions working or waiting in the same checkout');
    await expect(within(card).getAllByRole('link', { name: /Audit \d/ })).toHaveLength(2);
    await expect(within(card).getByRole('link', { name: /Audit 1/ })).toHaveAttribute(
      'href',
      '#n=session:audits%2Fsrc:claude:audit-1',
    );
  },
};

export const RepeatedIdentityHasNoOrphanCard: Story = {
  args: { duplicate: true },
  play: async ({ canvasElement }) => {
    await expectNoWorthALook(canvasElement);
    await expect(canvasElement.querySelector('[data-next-board-risk="collision"]')).toBeNull();
    await expect(canvasElement).not.toHaveTextContent('Location not measured for 2 sessions');
  },
};

export const RepeatedSessionDoesNotInventSharing: Story = {
  args: { duplicate: true },
  play: async ({ canvasElement, mount }) => {
    for (const view of ['sessions', 'projects']) {
      await mount(<Board key={view} hash={`#n=${view}`} duplicate />);
      await waitFor(() => expect(canvasElement).toHaveTextContent('audits'));
      await expect(canvasElement).not.toHaveTextContent('Location not measured');
    }
  },
};

export const RepeatedUnknownCountsOnceBesideMeasuredSession: Story = {
  args: { duplicate: true, mixedDuplicate: true },
  play: async ({ canvasElement, mount }) => {
    for (const view of ['sessions', 'projects']) {
      await mount(<Board key={view} hash={`#n=${view}`} duplicate mixedDuplicate />);
      await waitFor(() =>
        expect(canvasElement).toHaveTextContent(
          'Location not measured for 1 session with this display label',
        ),
      );
      await expect(canvasElement).not.toHaveTextContent('Location not measured for 2 sessions');
    }
  },
};
