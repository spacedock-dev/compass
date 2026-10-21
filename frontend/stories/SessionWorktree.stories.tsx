import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* Sessions started in two linked worktrees of one repository file under that repository's project, and
   each row still names its own worktree, so the two stay distinguishable. */

const meta = { title: 'Sessions/Worktree rows' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const G = 1900000000;
const row = (sid: string, worktree: string | null) => ({
  harness: 'claude',
  sid,
  project: 'one/compass',
  project_key: 'git:synthetic',
  worktree,
  title: `Synthetic session ${sid}`,
  state: 'working',
  started_at: G - 600,
  last_activity: G - 5,
});

function Page({ hash }: { readonly hash: string }) {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment(hash);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url) =>
        url.startsWith('/api/data')
          ? json({
              generated: G,
              sessions: [row('wa', 'haiku-a'), row('wb', 'haiku-b'), row('wm', null)],
            })
          : json({}),
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

export const RowsNameTheirWorktree: Story = {
  render: () => <Page hash="#n=sessions" />,
  play: async ({ canvasElement }) => {
    const where = (sid: string) =>
      canvasElement.querySelector(
        `article[data-next-session="${sid}"] [data-next-operation-fact="where"]`,
      );
    await waitFor(() => expect(where('wa')).not.toBeNull());
    await expect(where('wa')?.textContent).toContain('one/compass');
    await expect(where('wb')?.textContent).toContain('one/compass');
    await expect(where('wa')?.textContent).toContain('haiku-a');
    await expect(where('wb')?.textContent).toContain('haiku-b');
    await expect(where('wm')?.textContent).not.toContain('haiku');
  },
};

export const HeaderNamesTheWorktree: Story = {
  render: () => <Page hash="#n=session:one/compass:claude:wa" />,
  play: async ({ canvasElement }) => {
    const root = within(canvasElement);
    await waitFor(() => expect(root.getByRole('heading', { level: 1 })).toBeInTheDocument());
    await expect(canvasElement.querySelector('.next-session-identity')?.textContent).toContain(
      'worktree haiku-a',
    );
  },
};
