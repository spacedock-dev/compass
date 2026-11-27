import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import type { PlanPayload } from '../src/api/plan';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import {
  crowdedSourceRows,
  crowdedSources,
  hostileDiagramBody,
  planBoard,
  planWaiting,
  readyPlan,
  refusedPlanSettings,
  unconfiguredPlan,
} from '../test/plan-fixtures';
import { fakeBackend } from '../test/storage_backends';
import { overflowReport } from './a11y.audit';
import { atPageWidth } from './PageFit';
import { settledRect } from './settled-layout';

/* How many plan reads this story's board has asked for, so a play can wait for the read it asserts about. */
const planReads = { count: 0 };

type PlanAnswer = PlanPayload | null | 'pending' | 'server-error';

function planResponse(plan: PlanAnswer): Promise<Response> {
  if (plan === 'pending') return new Promise<Response>(() => undefined);
  if (plan === 'server-error') return Promise.resolve(new Response('Boom', { status: 500 }));
  return Promise.resolve(plan ? Response.json(plan) : new Response(null, { status: 404 }));
}

function PlanBoard({ plan }: { readonly plan: PlanAnswer }) {
  const [shell] = useState(() => {
    planReads.count = 0;
    const history = fakeRouterEnvironment('#n=plan');
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url) => {
        if (url === '/api/plan') {
          planReads.count += 1;
          return planResponse(plan);
        }
        if (url.startsWith('/api/data')) return Response.json(planBoard);
        return new Response(null, { status: 404 });
      },
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
  title: 'Pages/Plan route',
  component: PlanBoard,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof PlanBoard>;
export default meta;
type Story = StoryObj<typeof meta>;

const progressUnavailable = 'Lane progress is not measured.';

async function expectPublishedPlan(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  await expect(await canvas.findByRole('heading', { name: 'Plan', level: 1 })).toBeVisible();
  const plan = within(canvas.getByRole('region', { name: 'Plan' }));
  await expect(
    plan.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent),
  ).toEqual(['Waiting on you', 'Goals', 'Design', 'Tracker', 'Diagrams']);
  await expect(
    plan.getByText('Should the pickup shelf stay open on Sundays?', { exact: true }),
  ).toBeVisible();
  const untimed = plan
    .getByText('Who can check the entrance signs?', { exact: true })
    .closest('li');
  if (!untimed) throw new Error('The untimed ask needs a row.');
  await expect(within(untimed).getByText('Library plan log', { exact: true })).toBeVisible();
  await expect(within(untimed).queryByRole('time')).toBeNull();
  await expect(untimed).not.toHaveTextContent(/from the log|Asked|Lane:/);
  await expect(plan.getByText(progressUnavailable, { exact: true })).toBeVisible();
  await expect(plan.queryByText(/\d+ of \d+ lanes/)).toBeNull();
  const draft = within(plan.getByRole('article', { name: 'Make after-hours returns easier' }));
  await expect(draft.getByText('Proposed, not merged', { exact: true })).toBeVisible();
  await expect(draft.getByText('No lanes serve this goal yet', { exact: true })).toBeVisible();
  await expect(draft.queryByRole('time')).toBeNull();
  for (const title of ['Agree on weekend hours', 'Put up signs at the entrance']) {
    const lane = plan.getByText(title, { exact: true }).closest('li');
    if (!lane) throw new Error('The lane needs a row.');
    await expect(lane.textContent).toBe(title);
    await expect(within(lane).queryByRole('link')).toBeNull();
  }
  const shelfLinks = plan.getAllByRole('link', {
    name: 'Open session Review the shelf layout, Waiting on you',
  });
  await expect(shelfLinks).toHaveLength(2);
  await expect(plan.queryByRole('link', { name: /missing|weekend rota/i })).toBeNull();
  const waiting = plan.getByRole('list', { name: 'Sessions waiting for a reply' });
  await expect(
    within(waiting)
      .getAllByRole('listitem')
      .map((row) => row.textContent),
  ).toEqual(planWaiting.map((parts) => parts.join('')));
  for (const [title] of planWaiting) {
    await expect(within(waiting).getByRole('link', { name: title }).getAttribute('href')).toMatch(
      /^#n=session:Library%20pickup:[a-z]+:[^&]+&from=plan$/,
    );
  }
  const decisions = within(plan.getByRole('list', { name: 'Product decisions' }));
  await expect(
    decisions.getByText('Use the entrance alcove for pickups', { exact: true }),
  ).toBeVisible();
  const labels = plan.getByText('Print labels for the pickup shelf', { exact: true }).closest('li');
  if (!labels) throw new Error('The tracker row needs a row.');
  await expect(within(labels).getByText('Done', { exact: true })).toBeVisible();
  const diagrams = within(canvas.getByRole('region', { name: 'Diagrams' }));
  await expect(
    diagrams.getByText('From the library entrance to the pickup shelf', { exact: true }),
  ).toBeVisible();
  await expect(plan.getByText('Status not recognised', { exact: true })).toBeVisible();
  await expect(plan.queryByText('No tracker items are listed.')).toBeNull();
  const sources = within(canvas.getByRole('region', { name: 'Sources' }));
  const refused = sources.getByText('Annex design notes', { exact: true }).closest('li');
  if (!refused) throw new Error('The refused source needs a row.');
  await expect(within(refused).getByText('Refused', { exact: true })).toBeVisible();
  await expect(within(refused).getByText('Marked private.', { exact: true })).toBeVisible();
  await expect(within(refused).queryByText('Read', { exact: true })).toBeNull();
}

export const PublishedPlan: Story = {
  args: { plan: readyPlan },
  play: async ({ canvasElement }) => {
    await expectPublishedPlan(canvasElement);
    const nav = await primary(within(canvasElement));
    await expect(nav.getByRole('link', { name: 'Plan', current: 'page' })).toHaveAttribute(
      'href',
      '#n=plan',
    );
  },
};

export const PublishedPlanOnPhone: Story = {
  args: { plan: readyPlan },
  parameters: {
    viewport: {
      options: { planPhone: { name: '400 px', styles: { width: '400px', height: '800px' } } },
    },
  },
  globals: { viewport: { value: 'planPhone', isRotated: false } },
  play: async ({ canvasElement }) =>
    atPageWidth(400, async () => {
      await expectPublishedPlan(canvasElement);
      const goal = within(canvasElement).getByRole('article', {
        name: 'Make library pickup easier',
      });
      const { left, right } = await settledRect(goal);
      await expect(left).toBe(16);
      await expect(right).toBe(384);
    }),
};

// The layout floor: the shell keeps 8 px either side, and Plan keeps its 16 px gutter inside the page.
export const PublishedPlanAt320: Story = {
  args: { plan: readyPlan },
  parameters: {
    viewport: {
      options: { planFloor: { name: '320 px', styles: { width: '320px', height: '800px' } } },
    },
  },
  globals: { viewport: { value: 'planFloor', isRotated: false } },
  play: async ({ canvasElement }) =>
    atPageWidth(320, async () => {
      const canvas = within(canvasElement);
      await expect(await canvas.findByRole('heading', { name: 'Plan', level: 1 })).toBeVisible();
      const goal = canvas.getByRole('article', { name: 'Make library pickup easier' });
      const { left, right } = await settledRect(goal);
      await expect(left).toBe(16);
      await expect(right).toBe(304);
      const report = overflowReport();
      await expect(report.page).toBeLessThanOrEqual(report.client);
      await expect(report.wide).toEqual([]);
    }),
};

/* Three inventory files in one repository, a draft branch that does not exist yet and eight lane
   briefs: each file is told apart without a path, the draft is one row, and the briefs that were
   read are one counted row with the refused brief listed on its own. */
export const CrowdedSources: Story = {
  args: { plan: { ...readyPlan, sources: crowdedSources } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole('heading', { name: 'Plan', level: 1 })).toBeVisible();
    const sources = within(canvas.getByRole('region', { name: 'Sources' }));
    const rows = sources.getAllByRole('listitem');
    await expect(rows.map((row) => row.textContent)).toEqual([...crowdedSourceRows]);
    for (const row of rows) await expect(row).toBeVisible();
    const briefs = sources.getByText('Lane briefs', { exact: true }).closest('li');
    if (!briefs) throw new Error('The lane briefs need a row.');
    await expect(within(briefs).getByText('7 read', { exact: true })).toBeVisible();
    await expect(sources.getAllByText('The branch is missing.', { exact: true })).toHaveLength(1);
  },
};

async function primary(canvas: ReturnType<typeof within>) {
  const menu = canvas.queryByRole('button', { name: 'Menu' });
  if (menu && menu.getClientRects().length > 0) await userEvent.click(menu);
  return within(canvas.getByRole('navigation', { name: 'Primary' }));
}

async function expectNoPlan(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  // A Plan bookmark draws nothing until the plan read answers, so Sessions here is that answer.
  await expect(await canvas.findByRole('heading', { name: 'All sessions' })).toBeVisible();
  await expect(planReads.count).toBeGreaterThan(0);
  const nav = await primary(canvas);
  await expect(nav.getByRole('link', { name: 'Sessions', current: 'page' })).toBeVisible();
  await expect(nav.queryByRole('link', { name: 'Plan' })).toBeNull();
  await expect(canvas.queryByRole('heading', { name: 'Plan', level: 1 })).toBeNull();
  await expect(canvas.queryByText(/The Plan settings/)).toBeNull();
}

export const NotConfigured: Story = {
  args: { plan: unconfiguredPlan },
  play: async ({ canvasElement }) => expectNoPlan(canvasElement),
};

export const Disabled: Story = {
  args: { plan: null },
  play: async ({ canvasElement }) => expectNoPlan(canvasElement),
};

export const PlanReadPending: Story = {
  args: { plan: 'pending' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(planReads.count).toBe(1));
    await expect(await canvas.findByRole('navigation', { name: 'Primary' })).toBeInTheDocument();
    await expect(canvas.queryByRole('heading', { name: 'All sessions' })).toBeNull();
    await expect(canvas.queryByRole('heading', { name: 'Plan', level: 1 })).toBeNull();
  },
};

export const PlanReadFailed: Story = {
  args: { plan: 'server-error' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(
        'Compass could not read the plan. It tries again on the next refresh.',
        { exact: true },
      ),
    ).toBeVisible();
    await expect(canvas.getByRole('heading', { name: 'Plan', level: 1 })).toBeVisible();
    await expect(canvas.queryByRole('heading', { name: 'All sessions' })).toBeNull();
    const nav = await primary(canvas);
    await expect(nav.getByRole('link', { name: 'Plan', current: 'page' })).toBeVisible();
  },
};

export const RefusedSettings: Story = {
  args: { plan: refusedPlanSettings },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole('heading', { name: 'Plan', level: 1 })).toBeVisible();
    await expect(
      (await primary(canvas)).getByRole('link', { name: 'Plan', current: 'page' }),
    ).toBeVisible();
    await expect(
      canvas.getByText('The Plan settings did not have the expected format.', { exact: true }),
    ).toBeVisible();
    await expect(canvas.queryByRole('heading', { name: 'Goals' })).toBeNull();
    await expect(
      canvas.queryByText('The Plan settings could not be read.', { exact: true }),
    ).toBeNull();
  },
};

// Shown text that looks like markup must stay text, as the diagram body must stay unread.
const markupCaption =
  '<img src="https://diagram-canary.example.test/caption" onerror="window.planDiagramRan=true">Route map';

export const InertDiagram: Story = {
  args: {
    plan: {
      ...readyPlan,
      diagrams: [{ ...readyPlan.diagrams[0], caption: markupCaption, body: hostileDiagramBody }],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const diagrams = await canvas.findByRole('region', { name: 'Diagrams' });
    const section = within(diagrams);
    await expect(
      section.getByText('From the library entrance to the pickup shelf', { exact: true }),
    ).toBeVisible();
    await expect(section.getByText('diagrams.example.org', { exact: true })).toBeVisible();
    await expect(section.getByText(markupCaption, { exact: true })).toBeVisible();
    await expect(section.queryByText('Run diagram', { exact: true })).toBeNull();
    await waitFor(async () => {
      await expect(diagrams.querySelector('img, script, a, iframe, object')).toBeNull();
      await expect(Reflect.get(window, 'planDiagramRan')).toBeUndefined();
      await expect(performance.getEntriesByType('resource').map(({ name }) => name)).not.toContain(
        'https://diagram-canary.example.test/plan-image',
      );
      await expect(performance.getEntriesByType('resource').map(({ name }) => name)).not.toContain(
        'https://diagram-canary.example.test/caption',
      );
    });
    // The Storybook offline guard also fails this story on any external request attempt.
  },
};
