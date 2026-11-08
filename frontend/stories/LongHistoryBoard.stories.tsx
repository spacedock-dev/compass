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
import current from '../test/fixtures/client-contract/data-focused-drift-medium.json';
import currentContext from '../test/fixtures/client-contract/context-focused-drift-medium.json';
import stale from '../test/fixtures/client-contract/data-focused-drift-stale.json';
import staleContext from '../test/fixtures/client-contract/context-focused-drift-stale.json';
import withdrawn from '../test/fixtures/client-contract/data-focused-drift-withdrawn.json';
import withdrawnContext from '../test/fixtures/client-contract/context-focused-drift-withdrawn.json';
import wholeTask from '../test/fixtures/client-contract/data-task-preview-whole.json';
import wholeTaskContext from '../test/fixtures/client-contract/context-task-preview-whole.json';
import xmlTask from '../test/fixtures/client-contract/data-task-preview-xml.json';
import xmlTaskContext from '../test/fixtures/client-contract/context-task-preview-xml.json';
const readings = {
  current: [current, currentContext],
  stale: [stale, staleContext],
  withdrawn: [withdrawn, withdrawnContext],
} as const;
const tasks = { whole: [wholeTask, wholeTaskContext], xml: [xmlTask, xmlTaskContext] } as const;
type MutableRow = Record<string, unknown>;

let mounted: Shell | null = null;

function Board({
  view,
  liveOnly = false,
  reading,
  task,
  missingExplanation = false,
}: {
  readonly view: 'rows' | 'project' | 'delivery';
  readonly liveOnly?: boolean;
  readonly reading?: keyof typeof readings;
  readonly task?: keyof typeof tasks;
  readonly missingExplanation?: boolean;
}) {
  const [shell] = useState(() => {
    const pair = reading ? readings[reading] : task ? tasks[task] : null;
    const data = structuredClone(
      pair
        ? pair[0].response.body
        : liveOnly
          ? liveData.response.body
          : view === 'project'
            ? project.response.body
            : shared.response.body,
    ) as MutableRow;
    if (missingExplanation) {
      const rows = data['sessions'] as MutableRow[];
      const token = rows.find((row) => row['sid'] === '33333333')?.['delivery_binding_why'];
      delete (data['explanations'] as MutableRow)[String(token)];
    }
    const ctx = pair
      ? pair[1].response.body
      : liveOnly
        ? liveContext.response.body
        : context.response.body;
    const hash = reading
      ? '#n=session:alpha-app:claude:a1b2c3d4'
      : task
        ? '#n=project:task-preview'
        : view === 'project'
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
  args: { view: 'rows', reading: 'current' },
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-drift-pill] strong')).toHaveTextContent(
        'Medium',
      ),
    );
    if (!mounted) throw new Error('Board not mounted');
    mounted.router.navigate({ view: 'sessions' });
    await waitFor(() =>
      expect(
        canvasElement.querySelector(
          '[data-next-session="a1b2c3d4"] [data-next-session-drift-mark]',
        ),
      ).toHaveTextContent('Drift: Medium'),
    );
    await expect(canvasElement.textContent).not.toContain('why:');
  },
};

async function absentReading(canvasElement: HTMLElement) {
  await within(canvasElement).findByRole('heading', { name: 'Retry work' });
  await waitFor(() => expect(canvasElement.querySelector('[data-next-drift-pill]')).toBeNull());
  if (!mounted) throw new Error('Board not mounted');
  mounted.router.navigate({ view: 'sessions' });
  await waitFor(() =>
    expect(canvasElement.querySelector('[data-next-session="a1b2c3d4"]')).not.toBeNull(),
  );
  const row = canvasElement.querySelector('[data-next-session="a1b2c3d4"]');
  await expect(row?.querySelector('[data-next-row-drift-level]')).toBeNull();
  await expect(row?.textContent).not.toMatch(/Medium|High/);
}
export const StaleReadingNamesNoRowLevel: Story = {
  args: { view: 'rows', reading: 'stale' },
  play: async ({ canvasElement }) => absentReading(canvasElement),
};
export const WithdrawnReadingNamesNoRowLevel: Story = {
  args: { view: 'rows', reading: 'withdrawn' },
  play: async ({ canvasElement }) => absentReading(canvasElement),
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

export const WholeTaskNeedsNoEllipsis: Story = {
  args: { view: 'project', task: 'whole' },
  play: async ({ canvasElement }) => {
    const summary = await within(canvasElement).findByLabelText('Recovery summary');
    await waitFor(() => expect(summary).toHaveTextContent('Build the parser'));
    await expect(summary.textContent).not.toContain('…');
  },
};
export const SkippedXmlStillDisclosesTheCut: Story = {
  args: { view: 'project', task: 'xml' },
  play: async ({ canvasElement }) => {
    const summary = await within(canvasElement).findByLabelText('Recovery summary');
    await waitFor(() => expect(summary).toHaveTextContent('Build the parser…'));
  },
};
export const MissingOptionalExplanationShowsNoToken: Story = {
  args: { view: 'delivery', missingExplanation: true },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      await within(canvasElement).findByRole('button', { name: 'Full activity' }),
    );
    await waitFor(() => expect(canvasElement.textContent).toContain('Handed to this machine'));
    // Delivery outcome and count carry the fact. Identity binding is optional supporting detail.
    await expect(canvasElement.querySelector('.next-session-delivery-why')).toHaveTextContent(
      "Handed to this machine's notification service, which accepted it.",
    );
    await expect(canvasElement.textContent).not.toContain(
      'Matched on an eight-character identity prefix',
    );
    await expect(canvasElement.textContent).not.toContain('why:');
    await expect(canvasElement.textContent).toContain('notifications were raised');
  },
};
