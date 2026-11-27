import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { PlanPage } from '../src/plan/PlanPage';
import type { PlanModel } from '../src/plan/model';
import { atPageWidth } from './PageFit';
import { settledRect } from './settled-layout';

const changedAt = '2026-11-24T12:00:00Z';
const proposedAt = '2026-11-25T12:00:00Z';
const loggedAt = '2026-11-26T13:15:00Z';
const goal = {
  id: 'pickup',
  title: 'Make library pickup easier',
  doneWhen: 'Readers can collect a reserved book without joining the main queue.',
  lanes: [
    { id: 'shelf', title: 'Set up the pickup shelf', state: 'done' },
    { id: 'signs', title: 'Put up signs at the entrance', state: 'done' },
    { id: 'reminders', title: 'Update the pickup reminders', state: 'in-progress' },
    { id: 'weekends', title: 'Agree on weekend hours', state: 'blocked' },
    { id: 'trial', title: 'Run a pickup trial', state: 'planned' },
  ],
} as const;
const goalWithoutLanes = {
  id: 'returns',
  title: 'Make after-hours returns easier',
  doneWhen: 'Readers can return books whenever the library is closed.',
  lanes: [],
} as const;
const ask = {
  id: 'hours',
  verb: 'ask',
  text: 'Should the pickup shelf stay open on Sundays?',
  at: loggedAt,
} as const;
const waitingSession = {
  id: 'shelf-review',
  title: 'Review the shelf layout',
  request: 'Please confirm which shelves to keep clear.',
} as const;
const changedDesign = {
  id: 'entrance',
  title: 'Use the entrance alcove for pickups',
  summary: 'Readers can see the shelf as soon as they arrive.',
  date: { kind: 'changed', at: changedAt },
} as const;
const proposedDesign = {
  id: 'sign',
  title: 'Add a sign beside the return slot',
  summary: 'The sign would direct readers to the pickup shelf.',
  date: { kind: 'proposed', at: proposedAt },
} as const;
const knownTrackerRow = {
  id: 'labels',
  title: 'Print labels for the pickup shelf',
  status: 'done',
} as const;
// The unexpected source word stays outside the published model.
const unknownTrackerRow = {
  id: 'rota',
  title: 'Confirm the Saturday rota',
  status: 'unrecognised',
  rawStatus: 'Parked in orbit',
} as const;
const sourceList = [
  { id: 'goals', name: 'Library goals', status: 'ok' },
  { id: 'design', name: 'Library design notes', status: 'ok' },
  { id: 'tracker', name: 'Pickup work tracker', status: 'ok' },
  { id: 'diagrams', name: 'Library diagrams', status: 'ok' },
  { id: 'lanes', name: 'Pickup lane briefs', status: 'ok' },
  { id: 'log', name: 'Library plan log', status: 'ok' },
] as const;
const refusedSource = {
  id: 'annex',
  name: 'Annex design notes',
  status: 'refused',
  reason: 'private',
} as const;

const empty: PlanModel = {
  asks: [],
  waitingSessions: [],
  goals: [],
  design: [],
  tracker: [],
  diagrams: [],
  sources: [],
  limits: ['health-information', 'confidential-text'],
};
const complete: PlanModel = {
  ...empty,
  asks: [ask],
  waitingSessions: [waitingSession],
  goals: [goal, goalWithoutLanes],
  design: [changedDesign, proposedDesign],
  tracker: [knownTrackerRow, unknownTrackerRow],
  diagrams: [
    {
      id: 'pickup-route',
      title: 'From the library entrance to the pickup shelf',
      summary: 'The route from the entrance, past the desk, to the shelf.',
      linkHost: 'diagrams.example.org',
    },
  ],
  sources: [...sourceList, refusedSource],
};

const meta = {
  title: 'Pages/Plan',
  component: PlanPage,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof PlanPage>;
export default meta;
type Story = StoryObj<typeof meta>;

const absentQueue = 'No open asks or sessions waiting for a reply are listed.';
const absentLanes = 'No lanes serve this goal yet';
const unknownStatus = 'Status not recognised';
const proposed = 'Proposed, not merged';
const fromLog = 'from the log';
const changed = /^Changed /;

function section(element: HTMLElement, name: string) {
  return within(within(element).getByRole('region', { name }));
}

function shortDate(at: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(at));
}

export const FullPage: Story = {
  args: { model: complete },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const main = within(canvas.getByRole('main', { name: 'Plan' }));
    await expect(main.getByRole('heading', { level: 1, name: 'Plan' })).toBeVisible();
    await expect(main.getAllByRole('heading', { level: 2 }).map((el) => el.textContent)).toEqual([
      'Waiting on you',
      'Goals',
      'Design',
      'Tracker',
      'Diagrams',
    ]);
    await expect(main.getByRole('heading', { name: 'Product decisions' })).toBeVisible();
    await expect(main.queryByRole('heading', { name: 'Decisions' })).toBeNull();
    await expect(main.getByText('diagrams.example.org', { exact: true })).toBeVisible();
    await expect(canvasElement.textContent).not.toMatch(/https?:\/\//);
    await expect(canvas.queryByRole('dialog')).toBeNull();
    await expect(main.queryByText(absentQueue, { exact: true })).toBeNull();
  },
};

export const GoalWithLanes: Story = {
  args: { model: { ...empty, goals: [goal] } },
  play: async ({ canvasElement }) => {
    const goals = section(canvasElement, 'Goals');
    const card = within(goals.getByRole('article', { name: goal.title }));
    await expect(card.getByText('Done when', { exact: true })).toBeVisible();
    await expect(card.getByText(goal.doneWhen, { exact: true })).toBeVisible();
    await expect(card.getByText('2 of 5 lanes are done', { exact: true })).toBeVisible();
    for (const [name, titles] of [
      ['Done', ['Set up the pickup shelf', 'Put up signs at the entrance']],
      ['In progress', ['Update the pickup reminders']],
      ['Blocked', ['Agree on weekend hours']],
      ['Planned', ['Run a pickup trial']],
    ] as const) {
      const lanes = within(card.getByRole('list', { name }));
      await expect(lanes.getAllByRole('listitem').map((el) => el.textContent)).toEqual(titles);
    }
    await expect(card.queryByText(absentLanes, { exact: true })).toBeNull();
    await expect(card.queryByText('Working', { exact: true })).toBeNull();
    await expect(card.queryByRole('progressbar')).toBeNull();
    await expect(card.queryByRole('meter')).toBeNull();
    await expect(card.queryByRole('time')).toBeNull();
    await expect(card.queryByText(/\d+\s*%|Changed |Proposed, not merged|from the log/)).toBeNull();
  },
};

export const GoalWithoutLanes: Story = {
  args: { model: { ...empty, goals: [goalWithoutLanes] } },
  play: async ({ canvasElement }) => {
    const card = within(
      section(canvasElement, 'Goals').getByRole('article', { name: goalWithoutLanes.title }),
    );
    await expect(card.getByText(goalWithoutLanes.doneWhen, { exact: true })).toBeVisible();
    await expect(card.getByText(absentLanes, { exact: true })).toBeVisible();
    await expect(card.queryByText(/\d+ of \d+ lanes?/)).toBeNull();
    await expect(card.queryByRole('list')).toBeNull();
    await expect(card.queryByRole('progressbar')).toBeNull();
    await expect(card.queryByRole('time')).toBeNull();
  },
};

export const AsksThenWaitingSessions: Story = {
  args: { model: { ...empty, asks: [ask], waitingSessions: [waitingSession] } },
  play: async ({ canvasElement }) => {
    const queue = section(canvasElement, 'Waiting on you');
    await expect(queue.getAllByRole('heading', { level: 3 }).map((el) => el.textContent)).toEqual([
      'Open asks',
      'Sessions waiting for a reply',
    ]);
    const askRow = within(queue.getByRole('list', { name: 'Open asks' }));
    const replyRow = within(queue.getByRole('list', { name: 'Sessions waiting for a reply' }));
    await expect(askRow.getByText(ask.text, { exact: true })).toBeVisible();
    await expect(replyRow.getByText(waitingSession.title, { exact: true })).toBeVisible();
    await expect(replyRow.getByText(waitingSession.request, { exact: true })).toBeVisible();
    await expect(queue.queryByText(absentQueue, { exact: true })).toBeNull();
  },
};

export const EmptyWaitingOnYou: Story = {
  args: { model: empty },
  play: async ({ canvasElement }) => {
    const queue = section(canvasElement, 'Waiting on you');
    await expect(queue.getByText(absentQueue, { exact: true })).toBeVisible();
    await expect(queue.queryByRole('heading', { name: 'Open asks' })).toBeNull();
    await expect(queue.queryByRole('heading', { name: 'Sessions waiting for a reply' })).toBeNull();
    await expect(queue.queryByText(ask.text, { exact: true })).toBeNull();
    await expect(queue.queryByText(waitingSession.title, { exact: true })).toBeNull();
  },
};

export const UnrecognisedTrackerStatus: Story = {
  args: { model: { ...empty, tracker: [knownTrackerRow, unknownTrackerRow] } },
  play: async ({ canvasElement }) => {
    const tracker = section(canvasElement, 'Tracker');
    const [known, unknown] = tracker.getAllByRole('listitem');
    await expect(tracker.getAllByRole('listitem')).toHaveLength(2);
    await expect(known).toHaveTextContent('Print labels for the pickup shelf');
    await expect(known).toHaveTextContent('Done');
    await expect(known).not.toHaveTextContent(unknownStatus);
    await expect(unknown).toHaveTextContent('Confirm the Saturday rota');
    await expect(tracker.getByText(unknownStatus, { exact: true })).toBeVisible();
    await expect(unknown).not.toHaveTextContent('Done');
    await expect(canvasElement).not.toHaveTextContent(unknownTrackerRow.rawStatus);
  },
};

export const RefusedSource: Story = {
  args: { model: { ...empty, sources: [sourceList[0], refusedSource] } },
  play: async ({ canvasElement }) => {
    const sources = section(canvasElement, 'Sources');
    const [read, refused] = sources.getAllByRole('listitem');
    await expect(read).toHaveTextContent('Library goals');
    await expect(read).toHaveTextContent('Read');
    await expect(read).not.toHaveTextContent('Refused');
    await expect(refused).toHaveTextContent('Annex design notes');
    await expect(sources.getByText('Refused', { exact: true })).toBeVisible();
    await expect(sources.getByText('Marked private.', { exact: true })).toBeVisible();
    await expect(refused).not.toHaveTextContent('Read');
  },
};

export const ChangedDate: Story = {
  args: { model: { ...empty, design: [changedDesign] } },
  play: async ({ canvasElement }) => {
    const design = section(canvasElement, 'Design');
    const date = design.getByText(`Changed ${shortDate(changedAt)}`, { exact: true });
    await expect(date).toBeVisible();
    await expect(date).toHaveAttribute('datetime', changedAt);
    await expect(design.queryByText(proposed, { exact: true })).toBeNull();
    await expect(design.queryByText(fromLog, { exact: true })).toBeNull();
  },
};

export const ProposedDate: Story = {
  args: { model: { ...empty, design: [proposedDesign] } },
  play: async ({ canvasElement }) => {
    const design = section(canvasElement, 'Design');
    await expect(design.getByText(proposed, { exact: true })).toBeVisible();
    const date = design.getByText(shortDate(proposedAt), { exact: true });
    await expect(date).toBeVisible();
    await expect(date).toHaveAttribute('datetime', proposedAt);
    await expect(design.queryByText(changed)).toBeNull();
    await expect(design.queryByText(fromLog, { exact: true })).toBeNull();
  },
};

export const LogDate: Story = {
  args: { model: { ...empty, asks: [ask] } },
  play: async ({ canvasElement }) => {
    const queue = section(canvasElement, 'Waiting on you');
    const logged = queue.getByText(fromLog, { exact: true });
    await expect(logged).toBeVisible();
    const time = queue.getByRole('time');
    await expect(time).toHaveAttribute('datetime', loggedAt);
    await expect(time).toHaveTextContent(shortDate(loggedAt));
    await expect(time).toHaveTextContent(
      new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(new Date(loggedAt)),
    );
    await expect(queue.queryByText(changed)).toBeNull();
    await expect(queue.queryByText(proposed, { exact: true })).toBeNull();
  },
};

export const SourcesAndLimits: Story = {
  args: { model: { ...empty, sources: sourceList } },
  play: async ({ canvasElement }) => {
    const sources = section(canvasElement, 'Sources');
    await expect(sources.getAllByRole('listitem')).toHaveLength(6);
    for (const { name } of sourceList) {
      await expect(sources.getByText(name, { exact: true })).toBeVisible();
    }
    await expect(sources.queryByText('Refused', { exact: true })).toBeNull();
    const limits = section(canvasElement, "What Compass can't see");
    await expect(
      limits.getByText(
        'Compass cannot detect health information or confidential text typed into these sources.',
        {
          exact: true,
        },
      ),
    ).toBeVisible();
  },
};

export const Narrow: Story = {
  args: { model: complete },
  parameters: {
    viewport: {
      options: { planPhone: { name: '400 px', styles: { width: '400px', height: '800px' } } },
    },
  },
  globals: { viewport: { value: 'planPhone', isRotated: false } },
  play: async ({ canvasElement }) =>
    atPageWidth(400, async () => {
      const canvas = within(canvasElement);
      await expect(canvas.getByRole('heading', { level: 1, name: 'Plan' })).toBeVisible();
      const goals = section(canvasElement, 'Goals');
      const card = within(goals.getByRole('article', { name: goal.title }));
      await expect(card.getByText('2 of 5 lanes are done', { exact: true })).toBeVisible();
      const done = await settledRect(card.getByRole('list', { name: 'Done' }));
      const inProgress = await settledRect(card.getByRole('list', { name: 'In progress' }));
      await expect(inProgress.top).toBeGreaterThan(done.bottom);
      await expect(inProgress.left).toBe(done.left);
      await expect(canvas.getByText('Status not recognised', { exact: true })).toBeVisible();
      await expect(canvas.getByText('Marked private.', { exact: true })).toBeVisible();
      await expect(canvas.queryByText(absentQueue, { exact: true })).toBeNull();
    }),
};
