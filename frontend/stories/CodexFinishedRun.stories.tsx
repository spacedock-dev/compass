import { analysisRow, DEPARTURE_READING, DriftScenario, fact } from './drift.scenario';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* A turn stop finishes an exec run without claiming its resumable session ended. */

const meta = { title: 'Sessions/Codex finished run' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const G = 1900000000;
const row = (sid: string, headless: boolean) => ({
  harness: 'codex',
  sid,
  project: 'synthetic',
  title: `Synthetic ${sid}`,
  headless,
  state: 'idle',
  state_detail: headless ? 'run finished' : 'awaiting your message',
  started_at: G - 3600,
  last_activity: G - 60,
  turn_end_at: G - 600,
  finished_at: headless ? null : G - 600,
  ended_at: null,
});

function Page({ hash, asking = false }: { readonly hash: string; readonly asking?: boolean }) {
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
              ask: asking,
              asks: asking
                ? [{ id: 'q', harness: 'codex', session_id: 'exec', question: 'Review the run?' }]
                : [],
              sessions: [row('exec', true), row('tui', false)],
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

export const FinishedAndInteractive: Story = {
  render: () => <Page hash="#n=sessions" />,
  play: async ({ canvasElement, mount }) => {
    await mount();
    const root = within(canvasElement);
    const article = (sid: string) =>
      canvasElement.querySelector(`article[data-next-session="${sid}"]`) as HTMLElement;
    await waitFor(() => expect(article('exec')).not.toBeNull());
    await expect(within(article('exec')).getByText('run finished 10 minutes ago')).toBeVisible();
    await expect(article('exec').textContent).not.toContain('waiting for you');
    await expect(within(article('tui')).getByText('last active 1 minute ago')).toBeVisible();
    await userEvent.click(within(article('exec')).getByRole('link', { name: /Open session/ }));
    await waitFor(() =>
      expect(root.getByRole('heading', { level: 1 })).toHaveTextContent('Synthetic exec'),
    );
    await expect(
      within(canvasElement.querySelector('.next-session-detail-meta') as HTMLElement).getByText(
        /Run finished 10m ago/,
      ),
    ).toBeVisible();
    await expect(
      canvasElement.querySelector('[data-next-session-command="activity"]')?.textContent,
    ).not.toContain('waiting for you');
    await mount(<Page key="interactive" hash="#n=session:synthetic:codex:tui" />);
    await waitFor(() =>
      expect(root.getByRole('heading', { level: 1 })).toHaveTextContent('Synthetic tui'),
    );
    await expect(
      within(canvasElement.querySelector('.next-session-detail-meta') as HTMLElement).getByText(
        /Turn ended .* · waiting for you/,
      ),
    ).toBeVisible();
    await expect(
      canvasElement.querySelector('.next-session-detail-meta')?.textContent,
    ).not.toContain('Run finished');
  },
};
export const InteractiveStillWaits: Story = {
  render: () => <Page hash="#n=session:synthetic:codex:tui" />,
  play: async ({ canvasElement }) => {
    const root = within(canvasElement);
    await waitFor(() =>
      expect(root.getByRole('heading', { level: 1 })).toHaveTextContent('Synthetic tui'),
    );
    await expect(
      within(canvasElement.querySelector('.next-session-detail-meta') as HTMLElement).getByText(
        /Turn ended .* · waiting for you/,
      ),
    ).toBeVisible();
    await expect(
      canvasElement.querySelector('[data-next-session-command="activity"]')?.textContent,
    ).not.toContain('Run finished');
  },
};

export const OpenQuestionSuppressesFinishedMetadata: Story = {
  render: () => <Page hash="#n=session:synthetic:codex:exec" asking />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('heading', { level: 1, name: 'Synthetic exec' });
    const activity = canvasElement.querySelector('[data-next-session-command="activity"]');
    await expect(activity).toHaveTextContent('Review the run?');
    const metadata = canvasElement.querySelector('.next-session-detail-meta') as HTMLElement;
    await expect(metadata).not.toHaveTextContent(/turn ended|run finished/i);
  },
};

export const StoredProgressWithoutALevel: Story = {
  render: () => (
    <DriftScenario
      scenario={{
        harness: 'codex',
        session: {
          turn_end_at: 990,
          annotation_reading_count: 1,
          annotation_assessment: {
            ...DEPARTURE_READING,
            criteria: {
              goal: {
                result: 'departure',
                cites: ['codex-message'],
                detail: 'The recorded work departed.',
                clause: 'Ship the queue',
              },
            },
          },
        },
        work: { analysis_levels: [analysisRow('codex', 'medium')] },
        facts: [fact('codex-message', 500, { type: 'agent_message', by: 'agent' }, 'codex')],
      }}
    />
  ),
  play: async ({ canvasElement }) => {
    const progress = await within(canvasElement).findByRole('region', { name: 'Is it on track?' });
    await expect(
      await within(progress).findByRole('button', { name: 'Check progress again' }),
    ).toBeVisible();
    await expect(
      progress.querySelector(
        '[data-next-drift-pill], [data-next-drift-level], [data-next-drift-source]',
      ),
    ).toBeNull();
    await expect(within(progress).getByText(/^Compass found 1 departure/)).toBeVisible();
    await expect(progress.querySelector('[data-next-progress-absence]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-session-progress]')).toBeNull();
    await expect(within(progress).queryByRole('button', { name: 'Steer back' })).toBeNull();
  },
};
