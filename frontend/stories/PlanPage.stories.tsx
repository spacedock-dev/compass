import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { PlanPage } from '../src/plan/PlanPage';
import type { PlanModel } from '../src/plan/model';
import { atPageWidth } from './PageFit';
import { settledRect } from './settled-layout';

const changedAt = '2026-11-24T12:00:00Z';
const proposedAt = '2026-11-25T12:00:00Z';
const loggedAt = '2026-11-26T13:15:00Z';
const sourceByKind = {
  goals: { id: 'goals', name: 'Library goals', status: 'ok' },
  design: { id: 'design', name: 'Library design notes', status: 'ok' },
  tracker: { id: 'tracker', name: 'Pickup work tracker', status: 'ok' },
  diagrams: { id: 'diagrams', name: 'Library diagrams', status: 'ok' },
  lanes: { id: 'lanes', name: 'Pickup lane briefs', status: 'ok' },
  log: { id: 'log', name: 'Library plan log', status: 'ok' },
} as const;
const sourceList = Object.values(sourceByKind);
const shelfSession = {
  key: { view: 'session', project: 'Library pickup', harness: 'codex', session: 'shelf:review' },
  name: 'Review the shelf layout',
} as const;
const hoursSession = {
  key: { view: 'session', project: 'Library pickup', harness: 'claude', session: 'hours-review' },
  name: 'Review the weekend hours',
} as const;
const rotaSession = {
  key: { view: 'session', project: 'Library pickup', harness: 'codex', session: 'rota-review' },
  name: 'Check the weekend rota',
} as const;
const goal = {
  id: 'pickup',
  title: 'Make library pickup easier',
  doneWhen: 'Readers can collect a reserved book without joining the main queue.',
  lanes: [
    { id: 'shelf', title: 'Set up the pickup shelf', state: 'done', sessions: [shelfSession] },
    { id: 'signs', title: 'Put up signs at the entrance', state: 'done', sessions: [] },
    { id: 'reminders', title: 'Update the pickup reminders', state: 'in-progress', sessions: [] },
    {
      id: 'weekends',
      title: 'Agree on weekend hours',
      state: 'blocked',
      sessions: [hoursSession, rotaSession],
    },
    { id: 'trial', title: 'Run a pickup trial', state: 'planned', sessions: [] },
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
  source: sourceByKind.log.name,
} as const;
const askWithLane = { ...ask, lane: 'Agree on weekend hours' } as const;
const waitingSession = {
  key: shelfSession.key,
  title: shelfSession.name,
  harnessLabel: 'Codex',
  request: 'Please confirm which shelves to keep clear.',
} as const;
const waitingHoursSession = {
  key: hoursSession.key,
  title: hoursSession.name,
  harnessLabel: 'Claude Code',
  request: 'Please confirm the closing time.',
} as const;
const changedDesign = {
  id: 'entrance',
  title: 'Use the entrance alcove for pickups',
  summary: 'Readers can see the shelf as soon as they arrive.',
  date: { kind: 'changed', at: changedAt },
  source: sourceByKind.design.name,
} as const;
const proposedDesign = {
  id: 'sign',
  title: 'Add a sign beside the return slot',
  summary: 'The sign would direct readers to the pickup shelf.',
  date: { kind: 'proposed', at: proposedAt },
  source: sourceByKind.design.name,
} as const;
const knownTrackerRow = {
  id: 'labels',
  title: 'Print labels for the pickup shelf',
  status: 'done',
  source: sourceByKind.tracker.name,
} as const;
// The unexpected source word stays outside the published model.
const unknownTrackerRow = {
  id: 'rota',
  title: 'Confirm the Saturday rota',
  status: 'unrecognised',
  rawStatus: 'Parked in orbit',
  source: sourceByKind.tracker.name,
} as const;
const pickupDiagram = {
  id: 'pickup-route',
  title: 'From the library entrance to the pickup shelf',
  summary: 'The route from the entrance, past the desk, to the shelf.',
  linkHost: 'diagrams.example.org',
  source: sourceByKind.diagrams.name,
} as const;
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
  asks: [askWithLane],
  waitingSessions: [waitingSession],
  goals: [goal, goalWithoutLanes],
  design: [changedDesign, proposedDesign],
  tracker: [knownTrackerRow, unknownTrackerRow],
  diagrams: [pickupDiagram],
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
    await expect(canvasElement.textContent).not.toMatch(/https?:\/\/|#n=session:/);
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

const shelfHref = '#n=session:Library%20pickup:codex:shelf%3Areview';
const hoursHref = '#n=session:Library%20pickup:claude:hours-review';
const rotaHref = '#n=session:Library%20pickup:codex:rota-review';

async function expectSessionLink(scope: ReturnType<typeof within>, name: string, href: string) {
  const link = scope.getByRole('link', { name });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute('href', href);
  await expect(link).toHaveAttribute('title', name);
  await expect(link.querySelector('svg[data-icon="go-to-page"]')).toBeVisible();
}

export const LaneWithOneSession: Story = {
  args: { model: { ...empty, goals: [{ ...goal, lanes: [goal.lanes[0]] }] } },
  play: async ({ canvasElement }) => {
    const done = within(section(canvasElement, 'Goals').getByRole('list', { name: 'Done' }));
    const lane = within(done.getByRole('listitem'));
    await expect(lane.getByText('Set up the pickup shelf', { exact: true })).toBeVisible();
    await expect(lane.getAllByRole('link')).toHaveLength(1);
    await expectSessionLink(lane, 'Open session Review the shelf layout', shelfHref);
  },
};

export const LaneWithTwoSessions: Story = {
  args: { model: { ...empty, goals: [{ ...goal, lanes: [goal.lanes[3]] }] } },
  play: async ({ canvasElement }) => {
    const lane = within(
      within(section(canvasElement, 'Goals').getByRole('list', { name: 'Blocked' })).getByRole(
        'listitem',
      ),
    );
    await expect(lane.getByText('Agree on weekend hours', { exact: true })).toBeVisible();
    await expect(lane.getAllByRole('link')).toHaveLength(2);
    await expectSessionLink(lane, 'Open session Review the weekend hours', hoursHref);
    await expectSessionLink(lane, 'Open session Check the weekend rota', rotaHref);
  },
};

export const LaneWithoutSessions: Story = {
  args: { model: { ...empty, goals: [{ ...goal, lanes: [goal.lanes[1], goal.lanes[3]] }] } },
  play: async ({ canvasElement }) => {
    const done = within(section(canvasElement, 'Goals').getByRole('list', { name: 'Done' }));
    const signs = done.getByRole('listitem');
    await expect(signs).toHaveTextContent(/^Put up signs at the entrance$/);
    await expect(within(signs).queryByRole('link')).toBeNull();
    await expect(signs.querySelector('svg')).toBeNull();
  },
};

export const AskWithLaneSessions: Story = {
  args: {
    model: {
      ...empty,
      asks: [askWithLane],
      goals: [
        {
          ...goal,
          lanes: [goal.lanes[0], { ...goal.lanes[3], sessions: [hoursSession] }],
        },
      ],
      sources: sourceList,
    },
  },
  play: async ({ canvasElement }) => {
    const asks = within(
      section(canvasElement, 'Waiting on you').getByRole('list', { name: 'Open asks' }),
    );
    await expect(
      asks.getByText('Library plan log · lane Agree on weekend hours', { exact: true }),
    ).toBeVisible();
    await expect(asks.getByText(fromLog, { exact: true })).toBeVisible();
    await expect(asks.getAllByRole('link')).toHaveLength(1);
    await expectSessionLink(asks, 'Open session Review the weekend hours', hoursHref);
  },
};

export const AskWithoutLane: Story = {
  args: { model: { ...empty, asks: [ask], goals: [goal], sources: sourceList } },
  play: async ({ canvasElement }) => {
    const asks = within(
      section(canvasElement, 'Waiting on you').getByRole('list', { name: 'Open asks' }),
    );
    await expect(asks.getByText('Library plan log', { exact: true })).toBeVisible();
    await expect(asks.queryByText(/· lane/)).toBeNull();
    await expect(asks.queryByRole('link')).toBeNull();
  },
};

export const WaitingRowsLinkToSessions: Story = {
  args: { model: { ...empty, waitingSessions: [waitingSession, waitingHoursSession] } },
  play: async ({ canvasElement }) => {
    const replies = within(
      section(canvasElement, 'Waiting on you').getByRole('list', {
        name: 'Sessions waiting for a reply',
      }),
    );
    await expect(replies.getAllByRole('link')).toHaveLength(2);
    for (const [name, descriptor, href] of [
      ['Review the shelf layout', 'Codex · Library pickup', shelfHref],
      ['Review the weekend hours', 'Claude Code · Library pickup', hoursHref],
    ] as const) {
      const link = replies.getByRole('link', { name });
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute('href', href);
      await expect(within(link).getByText(descriptor, { exact: true })).toBeVisible();
    }
  },
};

export const SectionSources: Story = {
  args: { model: complete },
  play: async ({ canvasElement }) => {
    for (const [name, label] of [
      ['Design', 'From Library design notes'],
      ['Tracker', 'From Pickup work tracker'],
      ['Diagrams', 'From Library diagrams'],
    ] as const) {
      const view = section(canvasElement, name);
      await expect(view.getByText(label, { exact: true })).toBeVisible();
      await expect(view.queryByRole('link')).toBeNull();
    }
  },
};

export const AsksThenWaitingSessions: Story = {
  args: {
    model: {
      ...empty,
      asks: [ask],
      waitingSessions: [waitingSession],
      sources: [sourceByKind.log],
    },
  },
  play: async ({ canvasElement }) => {
    const queue = section(canvasElement, 'Waiting on you');
    await expect(queue.getAllByRole('heading', { level: 3 }).map((el) => el.textContent)).toEqual([
      'Open asks',
      'Sessions waiting for a reply',
    ]);
    const askRow = within(queue.getByRole('list', { name: 'Open asks' }));
    const replyRow = within(queue.getByRole('list', { name: 'Sessions waiting for a reply' }));
    await expect(askRow.getByText(ask.text, { exact: true })).toBeVisible();
    await expect(replyRow.getByRole('link', { name: waitingSession.title })).toBeVisible();
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
  args: { model: { ...empty, sources: [sourceByKind.goals, refusedSource] } },
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
  args: { model: { ...empty, asks: [ask], sources: [sourceByKind.log] } },
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
