import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeEnvironment } from '../src/transport/testing';
import { headerBoard } from '../test/headerBoard';
import { fakeBackend } from '../test/storage_backends';
import { atPageWidth } from './PageFit';
import { settledRect } from './settled-layout';

function Example({ onConnect }: { readonly onConnect?: (refresh: () => Promise<void>) => void }) {
  const [{ shell, refresh }] = useState(() => {
    let board = { ...headerBoard(), annotate: true };
    let revision = 0;
    const shell = createShell({
      env: createFakeEnvironment(),
      router: createRouter(fakeRouterEnvironment('#n=sessions').env),
      provider: () => fakeBackend(),
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          new Response(JSON.stringify(url.startsWith('/api/data') ? board : {}), {
            headers: { 'X-Compass-Revision': `11.${++revision}` },
          }),
        ),
    });
    shell.runtime.storage.sampleInvite.dismiss();
    return {
      shell,
      refresh: async () => {
        board = {
          ...board,
          sessions: [
            ...board.sessions,
            {
              harness: 'claude',
              sid: 'gate-2',
              project: 'Another project',
              title: 'Confirm the change',
              state: 'needs_input',
            },
          ],
        };
        await shell.runtime.refresh();
      },
    };
  });
  useEffect(() => onConnect?.(refresh), [onConnect, refresh]);
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
  title: 'Board/Phone layout',
  component: Example,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

function fit(width: number): Story {
  return {
    play: ({ canvasElement }) =>
      atPageWidth(width, async () => {
        const canvas = within(canvasElement);
        await canvas.findByRole('searchbox', { name: 'Search sessions' });
        const menu = canvas.getByRole('button', { name: 'Menu' });
        const status = canvas.getByRole('group', { name: 'Session status' });
        const menuBox = await settledRect(menu);
        await expect(menuBox.height).toBeGreaterThanOrEqual(44);
        if (width === 390) {
          const workingBox = await settledRect(
            canvas.getByRole('status', { name: 'Working sessions' }),
          );
          await expect(workingBox.y + workingBox.height / 2).toBeCloseTo(
            menuBox.y + menuBox.height / 2,
            0,
          );
        }
        for (const pill of within(status).getAllByRole('button')) {
          await expect((await settledRect(pill)).height).toBeGreaterThanOrEqual(44);
        }
        await expect(status.scrollWidth).toBeGreaterThan(status.clientWidth);
        await expect(
          (await settledRect(canvas.getByRole('searchbox'))).height,
        ).toBeGreaterThanOrEqual(48);
        await expect(canvasElement.querySelector('a a')).toBeNull();
        await expect(canvas.getByRole('button', { name: 'Needs you 3' })).toBeVisible();
      }),
  };
}

export const SessionsAt390 = fit(390);
export const SessionsAt375 = fit(375);
export const SessionsAt320 = fit(320);

export const MenuFiltersAndAnnouncements: Story = {
  play: async ({ canvasElement, mount }) => {
    let refresh: (() => Promise<void>) | undefined;
    await mount(
      <Example
        onConnect={(run) => {
          refresh = run;
        }}
      />,
    );
    await atPageWidth(390, async () => {
      const canvas = within(canvasElement);
      const search = await canvas.findByRole('searchbox', { name: 'Search sessions' });
      const menu = canvas.getByRole('button', { name: 'Menu' });
      const filters = canvas.getByRole('button', { name: 'Filters' });
      const status = canvasElement.querySelector('#next-attention-status');
      const before = await settledRect(search);
      await expect(menu.querySelector('svg[data-icon="menu"]')).toBeVisible();
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await userEvent.click(menu);
      await expect(menu).toHaveAttribute('aria-expanded', 'true');
      const nav = canvas.getByRole('navigation', { name: 'Primary' });
      await expect(menu).toHaveAttribute('aria-controls', nav.id);
      await expect((await settledRect(search)).top).toBeGreaterThan(before.top);
      await expect(canvasElement.querySelector('[inert],[aria-modal="true"]')).toBeNull();
      if (!refresh || !status) throw new Error('Missing refresh or status region');
      await expect(status).toHaveAttribute('aria-live', 'polite');
      await refresh();
      await waitFor(() => expect(status).toHaveTextContent(/updated/i));
      await expect(menu).toHaveAttribute('aria-expanded', 'true');

      await userEvent.tab();
      await userEvent.keyboard('{Escape}');
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await expect(menu).toHaveFocus();

      const beforeFilters = await settledRect(canvas.getByRole('heading', { name: 'Right now' }));
      await userEvent.click(filters);
      await expect(filters).toHaveAttribute('aria-expanded', 'true');
      await expect(
        (await settledRect(canvas.getByRole('heading', { name: 'Right now' }))).top,
      ).toBeGreaterThan(beforeFilters.top);
      await expect(canvasElement.querySelector('[inert],[aria-modal="true"]')).toBeNull();
      await userEvent.click(filters);

      await userEvent.click(menu);
      await userEvent.click(
        within(canvas.getByRole('navigation', { name: 'Primary' })).getByRole('link', {
          name: 'Projects',
        }),
      );
      await canvas.findByRole('heading', { level: 1, name: 'Projects' });
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await expect(menu).toHaveFocus();
    });
  },
};

export const WaitingCardOpensNeedsYou: Story = {
  play: ({ canvasElement }) =>
    atPageWidth(390, async () => {
      const canvas = within(canvasElement);
      const glance = await canvas.findByRole('region', { name: 'At a glance' });
      await userEvent.click(within(glance).getByRole('link', { name: /Waiting on you/ }));
      await expect(
        await canvas.findByRole('heading', { level: 1, name: 'Needs you' }),
      ).toBeVisible();
    }),
};
