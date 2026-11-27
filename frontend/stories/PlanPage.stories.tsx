import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { PlanPage } from '../src/plan/PlanPage';
import type { PlanModel } from '../src/plan/model';
import { atPageWidth } from './PageFit';
import { settledLayout, settledRect } from './settled-layout';

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
  state: 'waiting',
} as const;
const hoursSession = {
  key: { view: 'session', project: 'Library pickup', harness: 'claude', session: 'hours-review' },
  name: 'Review the weekend hours',
  state: 'waiting',
} as const;
const rotaSession = {
  key: { view: 'session', project: 'Library pickup', harness: 'codex', session: 'rota-review' },
  name: 'Check the weekend rota',
  state: 'working',
} as const;
const sundaySession = {
  key: { view: 'session', project: 'Library pickup', harness: 'codex', session: 'sunday-cover' },
  name: 'Confirm Sunday cover',
  state: 'quiet',
} as const;
const schoolSession = {
  key: {
    view: 'session',
    project: 'Library pickup',
    harness: 'claude',
    session: 'school-holidays',
  },
  name: 'Check the school holidays',
  state: 'ended',
} as const;
const longLane = {
  id: 'extended-collection',
  title:
    'Confirm the staffing and access arrangements for readers collecting reserved books after the main desk closes',
  state: 'in-progress',
  sessions: [
    {
      ...sundaySession,
      name: 'Confirm Sunday cover with the volunteers who can open the side entrance',
    },
    {
      ...schoolSession,
      name: 'Check the school holidays against the proposed collection timetable',
    },
  ],
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
    await expectRowPlacement(canvasElement, 'right');
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
    const groups = [
      ['Blocked', ['Agree on weekend hours']],
      ['In progress', ['Update the pickup reminders']],
      ['Planned', ['Run a pickup trial']],
      ['Done', ['Set up the pickup shelf', 'Put up signs at the entrance']],
    ] as const;
    await expect(card.getAllByRole('heading', { level: 4 }).map((el) => el.textContent)).toEqual(
      groups.map(([word]) => word),
    );
    for (const [name, titles] of groups) {
      const label = card.getByRole('heading', { name, level: 4 });
      await expect(label.parentElement).toHaveStyle({
        borderLeftWidth: '0px',
        borderRightWidth: '0px',
        borderBottomWidth: '0px',
        backgroundColor: 'rgba(0, 0, 0, 0)',
      });
      const laneList = within(card.getByRole('list', { name }));
      const rows = laneList.getAllByRole('listitem');
      await expect(rows).toHaveLength(titles.length);
      for (const title of titles) {
        await expect(laneList.getByText(title, { exact: true })).toBeVisible();
      }
      for (const row of rows.slice(1)) {
        await expect(row).toHaveStyle({
          borderTopWidth: '1px',
          borderLeftWidth: '0px',
          borderRightWidth: '0px',
          borderBottomWidth: '0px',
        });
      }
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

const sundayHref = '#n=session:Library%20pickup:codex:sunday-cover';
const schoolHref = '#n=session:Library%20pickup:claude:school-holidays';
const stateIcons = {
  Working: 'working',
  'Waiting on you': 'waiting',
  Quiet: 'quiet',
  Ended: 'ended',
} as const;

async function expectSessionLink(
  scope: ReturnType<typeof within>,
  name: string,
  state: keyof typeof stateIcons,
  href: string,
) {
  const link = scope.getByRole('link', { name: `Open session ${name}, ${state}` });
  const content = within(link);
  const label = content.getByText(name, { exact: true });
  await expect(label).toBeVisible();
  await expect(label).toHaveStyle({ fontSize: '13px' });
  await expect(link).toHaveAttribute('href', href);
  const icon = content.getByRole('img', { name: state });
  await expect(icon.querySelector(`svg[data-icon="${stateIcons[state]}"]`)).toBeVisible();
  for (const other of Object.keys(stateIcons).filter((word) => word !== state)) {
    await expect(content.queryByRole('img', { name: other })).toBeNull();
  }
  await expect(link.querySelector('svg[data-icon="go-to-page"]')).toBeNull();
  await expect((await settledRect(link)).height).toBeGreaterThanOrEqual(44);
  return { link, label };
}

async function expectRowPlacement(canvas: HTMLElement, side: 'right' | 'below') {
  const goals = section(canvas, 'Goals');
  const asks = within(section(canvas, 'Waiting on you').getByRole('list', { name: 'Open asks' }));
  for (const [scope, leftText] of [
    [within(goals.getByRole('list', { name: 'Blocked' })), 'Agree on weekend hours'],
    [asks, ask.text],
  ] as const) {
    const title = await settledRect(scope.getByText(leftText, { exact: true }));
    const label = await settledRect(scope.getByText(hoursSession.name, { exact: true }));
    if (side === 'below') {
      await expect(label.top).toBeGreaterThan(title.bottom);
      const icon = scope.getByRole('img', { name: 'Waiting on you' });
      await expect((await settledRect(icon)).left).toBe(title.left);
    } else {
      await expect(label.left).toBeGreaterThan(title.right);
      await expect(Math.abs(label.top - title.top)).toBeLessThan(6);
    }
  }
}

export const LaneWithOneSession: Story = {
  args: { model: { ...empty, goals: [{ ...goal, lanes: [goal.lanes[0]] }] } },
  play: async ({ canvasElement }) => {
    const goals = section(canvasElement, 'Goals');
    const done = within(goals.getByRole('list', { name: 'Done' }));
    const lane = within(done.getByRole('listitem'));
    await expect(goals.getByText('1 of 1 lane is done', { exact: true })).toBeVisible();
    await expect(lane.getByText('Set up the pickup shelf', { exact: true })).toBeVisible();
    await expect(lane.getAllByRole('link')).toHaveLength(1);
    const { link } = await expectSessionLink(lane, shelfSession.name, 'Waiting on you', shelfHref);
    link.focus();
    try {
      await expect(link).toHaveStyle({ textDecorationLine: 'underline', outlineWidth: '2px' });
    } finally {
      link.blur();
    }
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
    const hours = await expectSessionLink(lane, hoursSession.name, 'Waiting on you', hoursHref);
    const rota = await expectSessionLink(lane, rotaSession.name, 'Working', rotaHref);
    const first = await settledRect(hours.link);
    const second = await settledRect(rota.link);
    await expect(second.top).toBeGreaterThanOrEqual(first.bottom);
    if (window.innerWidth >= 640) await expect(second.right).toBe(first.right);
  },
};

export const LaneWithFourSessions: Story = {
  args: {
    model: {
      ...empty,
      goals: [
        {
          ...goal,
          lanes: [
            {
              ...goal.lanes[3],
              sessions: [hoursSession, rotaSession, sundaySession, schoolSession],
            },
          ],
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const lane = within(
      within(section(canvasElement, 'Goals').getByRole('list', { name: 'Blocked' })).getByRole(
        'listitem',
      ),
    );
    await expect(lane.getAllByRole('link')).toHaveLength(3);
    await expectSessionLink(lane, hoursSession.name, 'Waiting on you', hoursHref);
    await expectSessionLink(lane, rotaSession.name, 'Working', rotaHref);
    await expectSessionLink(lane, sundaySession.name, 'Quiet', sundayHref);
    const more = lane.getByText('and 1 more', { exact: true });
    await expect(more).toBeVisible();
    await expect(more.closest('a, button')).toBeNull();
    await expect(lane.queryByText(schoolSession.name, { exact: true })).toBeNull();
    await expect(lane.queryByRole('img', { name: 'Ended' })).toBeNull();
  },
};

export const LongLaneAndSessionNames: Story = {
  args: { model: { ...empty, goals: [{ ...goal, lanes: [longLane] }] } },
  parameters: {
    viewport: {
      options: { planBreakpoint: { name: '640 px', styles: { width: '640px', height: '800px' } } },
    },
  },
  globals: { viewport: { value: 'planBreakpoint', isRotated: false } },
  play: async ({ canvasElement }) =>
    atPageWidth(640, async () => {
      const group = within(
        section(canvasElement, 'Goals').getByRole('list', { name: 'In progress' }),
      );
      const row = group.getByRole('listitem');
      const lane = within(row);
      await expect(lane.getByText(longLane.title, { exact: true })).toBeVisible();
      const sunday = await expectSessionLink(lane, longLane.sessions[0].name, 'Quiet', sundayHref);
      const school = await expectSessionLink(lane, longLane.sessions[1].name, 'Ended', schoolHref);
      await expect(
        await settledLayout(() => row.scrollWidth - row.clientWidth),
      ).toBeLessThanOrEqual(0);
      for (const { label } of [sunday, school]) {
        await expect(label).toHaveStyle({ textOverflow: 'ellipsis', whiteSpace: 'nowrap' });
        await expect(
          await settledLayout(() => label.scrollWidth - label.clientWidth),
        ).toBeGreaterThan(0);
      }
    }),
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
    await expect(asks.getByText(ask.text, { exact: true })).toBeVisible();
    await expect(asks.getByText('Lane: Agree on weekend hours', { exact: true })).toBeVisible();
    await expectAskMetadata(asks);
    await expect(asks.getAllByRole('link')).toHaveLength(1);
    await expectSessionLink(asks, hoursSession.name, 'Waiting on you', hoursHref);
  },
};

export const AskWithoutLane: Story = {
  args: { model: { ...empty, asks: [ask], goals: [goal], sources: sourceList } },
  play: async ({ canvasElement }) => {
    const asks = within(
      section(canvasElement, 'Waiting on you').getByRole('list', { name: 'Open asks' }),
    );
    await expectAskMetadata(asks);
    await expect(asks.queryByText(/^Lane:/)).toBeNull();
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
    await expect(replies.queryByRole('img')).toBeNull();
    for (const [name, descriptor, request, href] of [
      ['Review the shelf layout', 'Codex · Library pickup', waitingSession.request, shelfHref],
      [
        'Review the weekend hours',
        'Claude Code · Library pickup',
        waitingHoursSession.request,
        hoursHref,
      ],
    ] as const) {
      const link = replies.getByRole('link', { name });
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute('href', href);
      const title = within(link).getByText(name, { exact: true });
      await expect(within(link).getByText(descriptor, { exact: true })).toBeVisible();
      await expect(within(link).getByText(request, { exact: true })).toBeVisible();
      link.focus();
      try {
        await expect(title).toHaveStyle({ textDecorationLine: 'underline' });
      } finally {
        link.blur();
      }
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

async function expectAskMetadata(scope: ReturnType<typeof within>) {
  const time = scope.getByRole('time');
  const date = new Date(loggedAt).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
  await expect(time).toHaveAttribute('datetime', loggedAt);
  await expect(time).toHaveTextContent(date);
  await expect(time.parentElement?.textContent).toBe(
    `Asked ${date} · from the log · Library plan log`,
  );
}

export const LogDate: Story = {
  args: { model: { ...empty, asks: [ask], sources: [sourceByKind.log] } },
  play: async ({ canvasElement }) => {
    const queue = section(canvasElement, 'Waiting on you');
    await expectAskMetadata(queue);
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
      await expect(done.top).toBeGreaterThan(inProgress.bottom);
      await expect(inProgress.left).toBe(done.left);
      await expectRowPlacement(canvasElement, 'below');
      await expect(canvas.getByText('Status not recognised', { exact: true })).toBeVisible();
      await expect(canvas.getByText('Marked private.', { exact: true })).toBeVisible();
      await expect(canvas.queryByText(absentQueue, { exact: true })).toBeNull();
    }),
};
