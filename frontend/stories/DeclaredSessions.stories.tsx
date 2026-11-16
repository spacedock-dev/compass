import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import fixture from '../test/fixtures/declared-sessions.json';

function Example({
  hash = '#n=sessions',
  childQuestion = false,
}: {
  readonly hash?: string;
  readonly childQuestion?: boolean;
}) {
  const [shell] = useState(() =>
    createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(fakeRouterEnvironment(hash).env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              url.startsWith('/api/data')
                ? {
                    ...fixture.payload,
                    ask: childQuestion,
                    asks: childQuestion
                      ? [{ id: 'q', harness: 'codex', session_id: 'child', question: 'Continue?' }]
                      : [],
                    sessions: [
                      ...fixture.payload.sessions,
                      {
                        harness: 'codex',
                        sid: 'bare',
                        project: 'demo',
                        title: 'No label assigned',
                        state: 'idle',
                      },
                      {
                        ...fixture.payload.sessions[0],
                        sid: 'second',
                        title: 'Check docs',
                        ended_at: 1899999999,
                        state: 'idle',
                      },
                    ],
                  }
                : {},
            ),
            { status: 200 },
          ),
        ),
    }),
  );
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return <App shell={shell} />;
}
const meta = { title: 'Sessions/Declared children and groups', component: Example } satisfies Meta<
  typeof Example
>;
export default meta;
type Story = StoryObj<typeof meta>;
const row = (root: HTMLElement, sid: string) =>
  root.querySelector(`[data-next-session="${sid}"]`) as HTMLElement;

export const LinkedChildrenAndWait: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('link', { name: 'Waiting on Check build' });
    await expect(row(canvasElement, 'child')).toHaveAttribute('data-declared-depth', '1');
    const active = [
      ...canvasElement.querySelectorAll('[data-next-operation-group="active"] article'),
    ];
    await expect(active.map((node) => node.getAttribute('data-next-session'))).toEqual([
      'parent',
      'child',
    ]);
    await expect(
      within(row(canvasElement, 'child')).getByRole('link', {
        name: 'Child of Coordinate release',
      }),
    ).toBeVisible();
    await expect(row(canvasElement, 'child')).toHaveTextContent(fixture.expected.child[0] ?? '');
    await userEvent.click(canvas.getByRole('button', { name: 'Headless' }));
    const popup = document.querySelector('[data-filter-popover="headless"]') as HTMLElement;
    await userEvent.click(within(popup).getByRole('checkbox', { name: /Interactive or unknown/ }));
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(row(canvasElement, 'child')).toBeNull());
    await expect(canvas.getByRole('link', { name: 'Waiting on Check build' })).toBeVisible();
  },
};
export const UnmatchedParentAndOwnGroup: Story = {
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText('Independent check');
    await expect(row(canvasElement, 'unlinked')).toHaveTextContent(
      'Declared parent is not on the board; not linked.',
    );
    await expect(row(canvasElement, 'unlinked')).not.toHaveAttribute('data-declared-depth');
    await expect(row(canvasElement, 'unlinked')).toHaveTextContent(
      fixture.expected.unlinked[0] ?? '',
    );
    await expect(row(canvasElement, 'unlinked').querySelectorAll('script')).toHaveLength(0);
    await expect(
      within(row(canvasElement, 'unlinked')).queryByRole('link', { name: /Child of/ }),
    ).toBeNull();
  },
};
export const GroupFilterAndGrouping: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('Independent check');
    await userEvent.click(canvas.getByRole('button', { name: 'Group by group' }));
    await expect(canvas.getByRole('heading', { name: 'No group' })).toBeVisible();
    await expect(
      canvas.getAllByRole('heading', { name: fixture.payload.sessions[0]?.group ?? '' }),
    ).toHaveLength(2);
    await userEvent.click(canvas.getByRole('button', { name: 'Group' }));
    const popup = document.querySelector('[data-filter-popover="group"]') as HTMLElement;
    await userEvent.click(within(popup).getByRole('checkbox', { name: /release/ }));
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(row(canvasElement, 'unlinked')).toBeNull());
    await expect(row(canvasElement, 'child')).toHaveTextContent('(from parent)');
    await expect(row(canvasElement, 'bare')).toBeNull();
    await expect(canvas.getByRole('button', { name: /Group: release/ })).toBeVisible();
  },
};
export const ParentPageNamesChildrenAndTheirState: Story = {
  args: { hash: '#n=session:demo:claude:parent' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const children = await canvas.findByRole('region', { name: 'Linked children' });
    await expect(children).toHaveTextContent('Check build · Working');
    await expect(children).toHaveTextContent('Check docs · Ended');
    await expect(canvasElement.querySelector('[data-next-session-status]')).toHaveTextContent(
      'Waiting on Check build',
    );
  },
};
export const ChildPageNamesParent: Story = {
  args: { hash: '#n=session:demo:codex:child' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole('link', { name: 'Child of Coordinate release' }),
    ).toBeVisible();
    await expect(canvas.getByText(fixture.expected.child[0] ?? '')).toBeVisible();
  },
};
export const UnmatchedChildPage: Story = {
  args: { hash: '#n=session:demo:codex:unlinked' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText('Declared parent is not on the board; not linked.'),
    ).toBeVisible();
    await expect(canvas.queryByRole('link', { name: /Child of/ })).toBeNull();
  },
};

export const FamilyLinksNavigateToTheirNamedSession: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const waiting = await canvas.findByRole('link', { name: 'Waiting on Check build' });
    const browser =
      '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
    if (browser)
      await browser.getByRole('link', { name: 'Waiting on Check build', exact: true }).click();
    else await userEvent.click(waiting);
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-session-detail]')).toHaveAttribute(
        'data-next-session-detail',
        'child',
      ),
    );
    await userEvent.click(canvas.getByRole('link', { name: 'Child of Coordinate release' }));
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-session-detail]')).toHaveAttribute(
        'data-next-session-detail',
        'parent',
      ),
    );
  },
};

export const ParentPageKeepsAChildsExactQuestion: Story = {
  args: { hash: '#n=session:demo:claude:parent', childQuestion: true },
  play: async ({ canvasElement }) => {
    const children = await within(canvasElement).findByRole('region', { name: 'Linked children' });
    await expect(children).toHaveTextContent('Check build · Waiting on you');
  },
};
