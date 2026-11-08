import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor, within, userEvent } from 'storybook/test';
import { useEffect, useState } from 'react';
import type { Shell } from '../src/shell/context';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import shared from '../test/fixtures/client-contract/data-shared-explanations.json';
import liveData from '../test/fixtures/client-contract/data-live-row.json';
import liveContext from '../test/fixtures/client-contract/context-live-row.json';
import { liveMonitorFor } from '../src/intent/liveMonitor';
import project from '../test/fixtures/client-contract/data-terminal-project.json';
import context from '../test/fixtures/client-contract/context-terminal-project.json';
type MutableRow = Record<string, unknown>;

let mounted: Shell | null = null;

function Board({
  view,
  liveOnly = false,
}: {
  readonly view: 'rows' | 'project' | 'delivery';
  readonly liveOnly?: boolean;
}) {
  const [shell] = useState(() => {
    const data = (
      liveOnly
        ? liveData.response.body
        : view === 'project'
          ? project.response.body
          : shared.response.body
    ) as MutableRow;
    const ctx = liveOnly ? liveContext.response.body : context.response.body;
    const hash =
      view === 'project'
        ? '#n=project:terminal-project'
        : view === 'delivery'
          ? '#n=session:shared-words:claude:33333333'
          : liveOnly
            ? '#n=session:shared-words:claude:44444444'
            : '#n=sessions';
    const history = fakeRouterEnvironment(hash);
    const made = createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url) =>
        new Response(
          JSON.stringify(
            url.startsWith('/api/data') ? data : url.startsWith('/api/project-context') ? ctx : {},
          ),
          { status: 200 },
        ),
    });
    if (liveOnly) liveMonitorFor(made).update('claude:44444444', { fallback: true });
    mounted = made;
    return made;
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
const meta = { title: 'Sessions/Long histories', component: Board } satisfies Meta<typeof Board>;
export default meta;
type Story = StoryObj<typeof meta>;

export const StoredReadingNamesItsLevel: Story = {
  args: { view: 'rows' },
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(
        canvasElement.querySelector(
          '[data-next-session="44444444"] [data-next-session-drift-mark]',
        ),
      ).toHaveTextContent('Drift: Medium or higher'),
    );
    await expect(canvasElement.textContent).not.toContain('why:');
    for (const sid of ['11111111', '22222222', '33333333'])
      await expect(
        canvasElement.querySelector(`[data-next-session="${sid}"] [data-next-row-drift-level]`),
      ).toBeNull();
  },
};
export const LiveEstimateNamesNoRowLevel: Story = {
  args: { view: 'rows', liveOnly: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { name: 'Live estimate without a stored reading' });
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-drift-pill] strong')).toHaveTextContent(
        'High',
      ),
    );
    const live = canvasElement.querySelector('[data-next-drift-level]');
    await expect(live).toBeVisible();
    await expect(live).toHaveTextContent('Live estimate');
    await expect(live).toHaveTextContent('No model assessment for this intent yet.');
    if (!mounted) throw new Error('Board not mounted');
    mounted.router.navigate({ view: 'sessions' });
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-session="44444444"]')).not.toBeNull(),
    );
    await expect(
      canvasElement.querySelector('[data-next-session="44444444"] [data-next-session-drift-mark]'),
    ).toHaveTextContent(/^Drift · /);
    await expect(canvasElement.querySelector('[data-next-row-drift-level]')).toBeNull();
  },
};
export const ProjectShowsTheServersTaskCut: Story = {
  args: { view: 'project' },
  play: async ({ canvasElement }) => {
    const summary = await within(canvasElement).findByLabelText('Recovery summary');
    await waitFor(() =>
      expect(summary).toHaveTextContent(
        'Build the parser with bounded input and preserve every reader-facing explanation and preserve every reader-facin…',
      ),
    );
    await expect(canvasElement.textContent).not.toContain('why:');
  },
};
export const SharedDeliveryWordsKeepTheirOutcomes: Story = {
  args: { view: 'delivery' },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      await within(canvasElement).findByRole('button', { name: 'Full activity' }),
    );
    await waitFor(() =>
      expect(canvasElement.querySelector('.next-session-delivery-why')).toBeVisible(),
    );
    await waitFor(() =>
      expect(canvasElement.textContent).toContain(
        'Earlier raises about this session did not all end the same way as this one.',
      ),
    );
    await expect(canvasElement.textContent).toContain(
      "Handed to this machine's notification service, which accepted it.",
    );
    await expect(canvasElement.textContent).toContain(
      'Matched on an eight-character identity prefix',
    );
    await expect(canvasElement.textContent).not.toContain('why:');
  },
};
