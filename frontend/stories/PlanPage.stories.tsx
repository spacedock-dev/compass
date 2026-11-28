import type { Meta, StoryObj } from '@storybook/react-vite';
import { type ReactNode, useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { ShellContext } from '../src/shell/context';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { planLimits } from '../test/plan-fixtures';
import { PlanPage } from '../src/plan/PlanPage';
import type { PlanModel } from '../src/plan/model';
import { hasFocusRing, restingRing, rgbOf } from './a11y.audit';
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
  state: 'running',
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
    { id: 'reminders', title: 'Update the pickup reminders', state: 'running', sessions: [] },
    {
      id: 'weekends',
      title: 'Agree on weekend hours',
      state: 'blocked',
      sessions: [hoursSession, rotaSession],
    },
    { id: 'trial', title: 'Run a pickup trial', state: 'not_started', sessions: [] },
  ],
} as const;
// Waiting is counted with the live groups; dropped and unmeasured lanes are shown apart and not counted.
const goalWithLanesApart = {
  id: 'reading-room',
  title: 'Open the quiet reading room',
  doneWhen: 'Readers can book a desk in the quiet reading room.',
  lanes: [
    { id: 'desks', title: 'Order the reading desks', state: 'waiting', sessions: [] },
    { id: 'lamps', title: 'Fit the desk lamps', state: 'done', sessions: [] },
    { id: 'phone', title: 'Take desk bookings by phone', state: 'dropped', sessions: [] },
    { id: 'quiet', title: 'Put up quiet signs', state: null, sessions: [] },
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
  text: 'Should the pickup shelf stay open on Sundays?',
  at: loggedAt,
  timeLabel: 'from the log',
  source: sourceByKind.log.name,
  sessions: [],
} as const;
const weekendLane = goal.lanes[3];
const askWithLane = {
  ...ask,
  lane: { id: weekendLane.id, title: weekendLane.title },
  sessions: weekendLane.sessions,
} as const;
const waitingSession = {
  key: shelfSession.key,
  title: shelfSession.name,
  harnessLabel: 'Codex',
  request: 'Please confirm which shelves to keep clear.',
  requestAuthored: true,
} as const;
const waitingHoursSession = {
  key: hoursSession.key,
  title: hoursSession.name,
  harnessLabel: 'Claude Code',
  request: 'Please confirm the closing time.',
  requestAuthored: true,
} as const;
const changedDesign = {
  id: 'entrance',
  title: 'Use the entrance alcove for pickups',
  summary: 'Readers can see the shelf as soon as they arrive.',
  decided: true,
  date: { kind: 'changed', at: changedAt },
  source: sourceByKind.design.name,
} as const;
const proposedDesign = {
  id: 'sign',
  title: 'Add a sign beside the return slot',
  summary: 'The sign would direct readers to the pickup shelf.',
  decided: true,
  date: { kind: 'proposed', at: proposedAt },
  source: sourceByKind.design.name,
} as const;
const undecidedDesign = {
  id: 'lockers',
  title: 'Add pickup lockers by the side door',
  summary: 'Lockers would let readers collect after hours.',
  decided: false,
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
  status: 'Status not recognised',
  rawStatus: 'Parked in orbit',
  source: sourceByKind.tracker.name,
} as const;
const pickupDiagram = {
  id: 'pickup-route',
  title: 'From the library entrance to the pickup shelf',
  summary: 'The route from the entrance, past the desk, to the shelf.',
  linkHosts: ['diagrams.example.org'],
  source: sourceByKind.diagrams.name,
} as const;
const refusedSource = {
  id: 'annex',
  name: 'Annex design notes',
  status: 'refused',
  reason: 'private',
} as const;

const empty: PlanModel = {
  trackerIncomplete: false,
  trackerOnly: false,
  asks: [],
  waitingSessions: [],
  goals: [],
  design: [],
  tracker: [],
  diagrams: [],
  sources: [],
  limits: planLimits,
};
const complete: PlanModel = {
  ...empty,
  asks: [askWithLane],
  waitingSessions: [waitingSession],
  goals: [goal, goalWithLanesApart, goalWithoutLanes],
  design: [changedDesign, proposedDesign, undecidedDesign],
  tracker: [knownTrackerRow, unknownTrackerRow],
  diagrams: [pickupDiagram],
  sources: [...sourceList, refusedSource],
};

/* The page's session links go through the shell's router, so each story draws it inside a shell that
   sits on Plan and never starts its runtime. */
function PlanShell({ children }: { readonly children: ReactNode }) {
  const [shell] = useState(() =>
    createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(fakeRouterEnvironment('#n=plan').env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async () => new Response(null, { status: 404 }),
    }),
  );
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return <ShellContext.Provider value={shell}>{children}</ShellContext.Provider>;
}

const meta = {
  title: 'Pages/Plan',
  component: PlanPage,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <PlanShell>
        <Story />
      </PlanShell>
    ),
  ],
} satisfies Meta<typeof PlanPage>;
export default meta;
type Story = StoryObj<typeof meta>;

const absentQueue = 'No open asks or sessions waiting for a reply are listed.';
const absentLanes = 'No lanes serve this goal yet';
const unknownStatus = 'Status not recognised';
const proposed = 'Proposed, not merged';
const fromLog = 'from the log';
const changed = /^Changed /;
const progressCount = /\d+ of \d+ lanes?/;
const notMeasured = 'Lane progress is not measured.';
const notCounted = {
  both: 'Dropped lanes and lanes without a known status are not counted.',
  dropped: 'Dropped lanes are not counted.',
  unknown: 'Lanes without a known status are not counted.',
} as const;
const anyNotCounted = /not counted\.$|^Lane progress is not measured\.$/;
const goalMetadata = /\d+\s*%|Changed |Proposed, not merged|from the log/;

async function expectProgress(card: ReturnType<typeof within>, text: string) {
  const counts = card.getAllByText(progressCount);
  await expect(counts).toHaveLength(1);
  await expect(counts[0]).toHaveTextContent(new RegExp(`^${text}$`));
  await expect(counts[0]).toBeVisible();
}

async function expectLinksBelowHeading(heading: HTMLElement, list: HTMLElement) {
  const { bottom } = await settledRect(heading);
  for (const link of within(list).queryAllByRole('link')) {
    await expect((await settledRect(link)).top).toBeGreaterThanOrEqual(bottom);
  }
}

/* The element whose whole text is this, though authored words sit in their own span inside it. */
function fullText(text: string) {
  return (_: string, element: Element | null) =>
    element?.textContent === text &&
    ![...element.children].some((child) => child.textContent === text);
}

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
    const main = within(canvas.getByRole('region', { name: 'Plan' }));
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
    await expect(canvasElement.textContent).not.toMatch(/(?:https?:)?\/\/[\w-]|#n=session:/);
    await expect(canvas.queryByRole('dialog')).toBeNull();
    await expect(main.queryByText(absentQueue, { exact: true })).toBeNull();
    const queue = section(canvasElement, 'Waiting on you');
    await expectLinksBelowHeading(
      queue.getByRole('heading', { name: 'Open asks' }),
      queue.getByRole('list', { name: 'Open asks' }),
    );
    await expectRowPlacement(canvasElement, 'right');
    const apart = within(
      section(canvasElement, 'Goals').getByRole('article', { name: goalWithLanesApart.title }),
    );
    await expectProgress(apart, '1 of 2 lanes are done');
    await expect(apart.getByText(notCounted.both, { exact: true })).toBeVisible();
  },
};

export const GoalWithLanes: Story = {
  args: { model: { ...empty, goals: [goal] } },
  play: async ({ canvasElement }) => {
    const goals = section(canvasElement, 'Goals');
    const card = within(goals.getByRole('article', { name: goal.title }));
    await expect(card.getByText('Done when', { exact: true })).toBeVisible();
    await expect(card.getByText(goal.doneWhen, { exact: true })).toBeVisible();
    await expectProgress(card, '2 of 5 lanes are done');
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
      const list = card.getByRole('list', { name });
      await expectLinksBelowHeading(label, list);
      const laneList = within(list);
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
    await expect(card.queryByText(goalMetadata)).toBeNull();
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
    await expect(card.queryByText(progressCount)).toBeNull();
    await expect(card.queryByRole('list')).toBeNull();
    await expect(card.queryByRole('progressbar')).toBeNull();
    await expect(card.queryByRole('meter')).toBeNull();
    await expect(card.queryByRole('time')).toBeNull();
    await expect(card.queryByText(goalMetadata)).toBeNull();
  },
};

export const GoalWithNoDoneLanes: Story = {
  args: { model: { ...empty, goals: [{ ...goal, lanes: [goal.lanes[2], weekendLane] }] } },
  play: async ({ canvasElement }) => {
    const card = within(section(canvasElement, 'Goals').getByRole('article', { name: goal.title }));
    await expectProgress(card, '0 of 2 lanes are done');
  },
};

const shelfHref = '#n=session:Library%20pickup:codex:shelf%3Areview&from=plan';
const hoursHref = '#n=session:Library%20pickup:claude:hours-review&from=plan';
const rotaHref = '#n=session:Library%20pickup:codex:rota-review&from=plan';

const sundayHref = '#n=session:Library%20pickup:codex:sunday-cover&from=plan';
const schoolHref = '#n=session:Library%20pickup:claude:school-holidays&from=plan';
const sessionIcons = {
  Working: ['working', '--status-working-ink'],
  'Waiting on you': ['waiting', '--status-waiting-ink'],
  Quiet: ['quiet', '--status-quiet-ink'],
  Ended: ['ended', '--status-ended-ink'],
  'State not known': ['state-not-known', '--ink2'],
} as const;

async function expectSessionLink(
  scope: ReturnType<typeof within>,
  name: string,
  state: keyof typeof sessionIcons,
  href: string,
) {
  const link = scope.getByRole('link', { name: `Open session ${name}, ${state}` });
  const content = within(link);
  const label = content.getByText(name, { exact: true });
  await expect(label).toBeVisible();
  await expect(label).toHaveStyle({ fontSize: '13px' });
  await expect(link).toHaveAttribute('href', href);
  const icon = content.getByRole('img', { name: state });
  const [shape, token] = sessionIcons[state];
  const svg = icon.querySelector(`svg[data-icon="${shape}"]`);
  await expect(svg).toBeVisible();
  const color = getComputedStyle(icon).getPropertyValue(token);
  await expect(svg).toHaveStyle({ color });
  for (const other of Object.keys(sessionIcons).filter((word) => word !== state)) {
    await expect(content.queryByRole('img', { name: other })).toBeNull();
  }
  await expect(link.querySelector('svg[data-icon="go-to-page"]')).toBeNull();
  await expect((await settledRect(link)).height).toBeGreaterThanOrEqual(44);
  return { link, label };
}

async function expectKeyboardLink(link: HTMLElement, name: string, href: string) {
  const resting = restingRing(link);
  await userEvent.tab();
  await expect(link).toHaveFocus();
  await expect(link).toHaveAccessibleName(name);
  await expect((await settledRect(link)).height).toBeGreaterThanOrEqual(44);
  await expect(hasFocusRing(link, resting)).toBe(true);
  const outline = getComputedStyle(link);
  await expect(outline.outlineStyle).toBe('solid');
  await expect(outline.outlineWidth).toBe('2px');
  await expect(rgbOf(outline.outlineColor)).toEqual(rgbOf(outline.getPropertyValue('--accent')));
  /* Letting Enter navigate moves the Vitest tester page itself, which closes the browser connection
     and fails the whole shard. Keyboard activation fires a click on the focused link, so the play
     records that click's target and stops it there. */
  const activated: string[] = [];
  const stop = (event: MouseEvent) => {
    const anchor = (event.target as Element | null)?.closest('a');
    if (anchor) activated.push(anchor.getAttribute('href') ?? '');
    event.preventDefault();
  };
  link.addEventListener('click', stop);
  try {
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(activated).toEqual([href]));
  } finally {
    link.removeEventListener('click', stop);
  }
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

const everyLaneState = [
  ['Blocked', { id: 'b', title: 'Agree on weekend hours', state: 'blocked' }],
  ['Waiting', { id: 'w', title: 'Order the reading desks', state: 'waiting' }],
  ['In progress', { id: 'i', title: 'Update the pickup reminders', state: 'running' }],
  ['Planned', { id: 'p', title: 'Run a pickup trial', state: 'not_started' }],
  ['Done', { id: 'd', title: 'Set up the pickup shelf', state: 'done' }],
  ['Dropped', { id: 'x', title: 'Take desk bookings by phone', state: 'dropped' }],
  [
    'Status not recognised',
    { id: 'u', title: 'Confirm the Saturday rota', state: 'Status not recognised' },
  ],
  ['Not measured', { id: 'n', title: 'Put up quiet signs', state: null }],
] as const;

function laneGroup(card: ReturnType<typeof within>, name: string) {
  return within(card.getByRole('list', { name }));
}

export const GoalWithEveryLaneState: Story = {
  args: {
    model: {
      ...empty,
      goals: [
        {
          ...goal,
          // Reversed so the page, not the fixture, puts the groups in order.
          lanes: [...everyLaneState].reverse().map(([, lane]) => ({ ...lane, sessions: [] })),
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const card = within(section(canvasElement, 'Goals').getByRole('article', { name: goal.title }));
    await expect(card.getAllByRole('heading', { level: 4 }).map((el) => el.textContent)).toEqual(
      everyLaneState.map(([word]) => word),
    );
    for (const [word, lane] of everyLaneState) {
      const rows = laneGroup(card, word).getAllByRole('listitem');
      await expect(rows).toHaveLength(1);
      await expect(rows[0]).toHaveTextContent(new RegExp(`^${lane.title}$`));
      await expect(card.getByRole('heading', { name: word, level: 4 })).toHaveClass(
        'text-muted-foreground',
      );
    }
    // Blocked, Waiting, In progress, Planned and Done are counted; the three groups after them are not.
    await expectProgress(card, '1 of 5 lanes are done');
    const note = card.getByText(notCounted.both, { exact: true });
    await expect(note).toBeVisible();
    await expect(note).toHaveClass('text-muted-foreground');
    const count = await settledRect(card.getByText(progressCount));
    await expect((await settledRect(note)).top).toBeGreaterThanOrEqual(count.bottom);
    const lastCounted = await settledRect(card.getByRole('list', { name: 'Done' }));
    for (const word of ['Dropped', 'Status not recognised', 'Not measured']) {
      await expect((await settledRect(card.getByRole('list', { name: word }))).top).toBeGreaterThan(
        lastCounted.bottom,
      );
    }
    await expect(card.queryByText('Status not published')).toBeNull();
    await expect(card.queryByText(notMeasured, { exact: true })).toBeNull();
  },
};

export const GoalWithUnmeasuredLanes: Story = {
  args: {
    model: {
      ...empty,
      goals: [
        {
          ...goal,
          lanes: [
            goal.lanes[0],
            goal.lanes[2],
            { ...goal.lanes[4], state: null },
            { ...goal.lanes[1], state: 'Status not recognised' },
          ],
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const card = within(section(canvasElement, 'Goals').getByRole('article', { name: goal.title }));
    // The unrecognised lane is a done-looking title; it is never counted as done.
    await expectProgress(card, '1 of 2 lanes are done');
    await expect(card.getByText(notCounted.unknown, { exact: true })).toBeVisible();
    await expect(laneGroup(card, 'Done').getAllByRole('listitem')).toHaveLength(1);
    await expect(laneGroup(card, 'Not measured').getByRole('listitem')).toHaveTextContent(
      /^Run a pickup trial$/,
    );
    await expect(laneGroup(card, 'Status not recognised').getByRole('listitem')).toHaveTextContent(
      /^Put up signs at the entrance$/,
    );
    await expect(card.queryByRole('list', { name: 'Planned' })).toBeNull();
    await expect(card.queryByText(notCounted.both, { exact: true })).toBeNull();
  },
};

export const GoalWithDroppedLane: Story = {
  args: {
    model: {
      ...empty,
      goals: [{ ...goal, lanes: [goal.lanes[0], { ...goal.lanes[4], state: 'dropped' }] }],
    },
  },
  play: async ({ canvasElement }) => {
    const card = within(section(canvasElement, 'Goals').getByRole('article', { name: goal.title }));
    await expectProgress(card, '1 of 1 lane is done');
    await expect(card.getByText(notCounted.dropped, { exact: true })).toBeVisible();
    await expect(laneGroup(card, 'Dropped').getByRole('listitem')).toHaveTextContent(
      /^Run a pickup trial$/,
    );
  },
};

export const GoalWithEveryLaneUnmeasured: Story = {
  args: {
    model: {
      ...empty,
      goals: [
        {
          ...goal,
          lanes: [
            { ...goal.lanes[0], state: null },
            { ...goal.lanes[1], state: null },
            { ...goal.lanes[3], state: 'Status not recognised' },
          ],
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const article = section(canvasElement, 'Goals').getByRole('article', { name: goal.title });
    const card = within(article);
    await expect(card.queryByText(progressCount)).toBeNull();
    await expect(article).not.toHaveTextContent(/\b0 of /);
    const line = card.getByText(notMeasured, { exact: true });
    await expect(line).toBeVisible();
    await expect(line).toHaveClass('text-muted-foreground');
    await expect(card.getAllByText(anyNotCounted)).toEqual([line]);
    await expect(card.getAllByRole('heading', { level: 4 }).map((el) => el.textContent)).toEqual([
      'Status not recognised',
      'Not measured',
    ]);
    await expect(laneGroup(card, 'Not measured').getAllByRole('listitem')).toHaveLength(2);
    // The session links stay on an unmeasured lane.
    await expectSessionLink(
      laneGroup(card, 'Not measured'),
      shelfSession.name,
      'Waiting on you',
      shelfHref,
    );
  },
};

export const GoalWithEveryLaneDropped: Story = {
  args: {
    model: {
      ...empty,
      goals: [{ ...goal, lanes: [{ ...goal.lanes[0], state: 'dropped' }] }],
    },
  },
  play: async ({ canvasElement }) => {
    const card = within(section(canvasElement, 'Goals').getByRole('article', { name: goal.title }));
    await expect(card.queryByText(progressCount)).toBeNull();
    await expect(card.getAllByText(anyNotCounted).map((el) => el.textContent)).toEqual([
      notCounted.dropped,
    ]);
  },
};

export const GoalWithLanesApart: Story = {
  args: { model: { ...empty, goals: [goalWithLanesApart] } },
  play: async ({ canvasElement }) => {
    const card = within(
      section(canvasElement, 'Goals').getByRole('article', { name: goalWithLanesApart.title }),
    );
    await expectProgress(card, '1 of 2 lanes are done');
    await expect(card.getByText(notCounted.both, { exact: true })).toBeVisible();
    await expect(card.getAllByRole('heading', { level: 4 }).map((el) => el.textContent)).toEqual([
      'Waiting',
      'Done',
      'Dropped',
      'Not measured',
    ]);
  },
};

// Words a person wrote into their plan files are theirs: the first-layer audit reads them as authored.
const authoredWords = 'Fix SHELF LABELS from 3f9c2ab [2]';
export const AuthoredPlanText: Story = {
  args: {
    model: {
      ...empty,
      asks: [{ ...askWithLane, text: authoredWords, lane: { id: 'a', title: authoredWords } }],
      goals: [
        {
          ...goal,
          title: authoredWords,
          doneWhen: authoredWords,
          lanes: [
            {
              ...goal.lanes[0],
              title: authoredWords,
              // A session name reaches the link's accessible name, which the audit cannot mark as authored.
              sessions: [shelfSession],
            },
          ],
        },
      ],
      design: [{ ...changedDesign, title: authoredWords, summary: authoredWords }],
      tracker: [{ ...knownTrackerRow, title: authoredWords }],
      diagrams: [{ ...pickupDiagram, title: authoredWords, summary: authoredWords }],
      sources: [{ ...sourceByKind.goals, name: authoredWords }],
    },
  },
  play: async ({ canvasElement }) => {
    const body = canvasElement.querySelector('[data-next-view-body="plan"]');
    await expect(body).not.toBeNull();
    for (const node of within(canvasElement).getAllByText(authoredWords, { exact: false })) {
      await expect(node.closest('[data-authored]'), node.outerHTML).not.toBeNull();
    }
  },
};

export const LaneWithOneSession: Story = {
  args: { model: { ...empty, goals: [{ ...goal, lanes: [goal.lanes[0]] }] } },
  play: async ({ canvasElement }) => {
    const goals = section(canvasElement, 'Goals');
    const done = within(goals.getByRole('list', { name: 'Done' }));
    const lane = within(done.getByRole('listitem'));
    await expectProgress(within(goals.getByRole('article')), '1 of 1 lane is done');
    await expect(lane.getByText('Set up the pickup shelf', { exact: true })).toBeVisible();
    await expect(lane.getAllByRole('link')).toHaveLength(1);
    const { link } = await expectSessionLink(lane, shelfSession.name, 'Waiting on you', shelfHref);
    try {
      await expectKeyboardLink(
        link,
        'Open session Review the shelf layout, Waiting on you',
        shelfHref,
      );
      await expect(link).toHaveStyle({ textDecorationLine: 'underline' });
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
    await expectProgress(
      within(section(canvasElement, 'Goals').getByRole('article')),
      '0 of 1 lane is done',
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
    await expectProgress(
      within(section(canvasElement, 'Goals').getByRole('article')),
      '0 of 1 lane is done',
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

export const LaneWithUnknownSessionState: Story = {
  args: {
    model: {
      ...empty,
      goals: [
        { ...goal, lanes: [{ ...weekendLane, sessions: [{ ...rotaSession, state: 'unknown' }] }] },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const lane = within(section(canvasElement, 'Goals').getByRole('list', { name: 'Blocked' }));
    await expectSessionLink(lane, rotaSession.name, 'State not known', rotaHref);
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
      asks: [{ ...askWithLane, sessions: [hoursSession] }],
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
    await expect(asks.getByText(fullText('Lane: Agree on weekend hours'))).toBeVisible();
    await expectAskMetadata(asks);
    await expect(asks.getAllByRole('link')).toHaveLength(1);
    await expectSessionLink(asks, hoursSession.name, 'Waiting on you', hoursHref);
  },
};

function openAsks(canvas: HTMLElement) {
  return within(section(canvas, 'Waiting on you').getByRole('list', { name: 'Open asks' }));
}

function rowWithText(list: ReturnType<typeof within>, text: string) {
  const row = list.getByText(text, { exact: true }).closest('li');
  if (!row) throw new Error(`No list row for ${text}`);
  return within(row);
}

const askAboutShelf = {
  ...ask,
  id: 'shelf',
  text: 'Which shelves should stay clear?',
  lane: { id: goal.lanes[0].id, title: goal.lanes[0].title },
  sessions: [shelfSession],
} as const;

const threeWeekendSessions = [...weekendLane.sessions, sundaySession];

export const TwoAsks: Story = {
  args: {
    model: {
      ...empty,
      asks: [{ ...askWithLane, sessions: threeWeekendSessions }, askAboutShelf],
      goals: [
        { ...goal, lanes: [goal.lanes[0], { ...weekendLane, sessions: threeWeekendSessions }] },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const asks = openAsks(canvasElement);
    const first = rowWithText(asks, askWithLane.text);
    const second = rowWithText(asks, askAboutShelf.text).getByRole('link');
    const { bottom } = await settledRect(
      first.getByRole('link', { name: 'Open session Confirm Sunday cover, Quiet' }),
    );
    await expect((await settledRect(second)).top).toBeGreaterThanOrEqual(bottom);
  },
};

export const AsksWithDuplicateLaneTitles: Story = {
  args: {
    model: {
      ...empty,
      asks: [
        askWithLane,
        { ...askAboutShelf, lane: { ...askAboutShelf.lane, title: weekendLane.title } },
      ],
      goals: [
        { ...goalWithoutLanes, lanes: [{ ...goal.lanes[0], title: weekendLane.title }] },
        { ...goal, lanes: [weekendLane] },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const asks = openAsks(canvasElement);
    const hours = rowWithText(asks, askWithLane.text);
    const shelf = rowWithText(asks, askAboutShelf.text);
    await expectSessionLink(hours, hoursSession.name, 'Waiting on you', hoursHref);
    await expectSessionLink(hours, rotaSession.name, 'Working', rotaHref);
    await expect(hours.getAllByRole('link')).toHaveLength(2);
    await expectSessionLink(shelf, shelfSession.name, 'Waiting on you', shelfHref);
    await expect(shelf.getAllByRole('link')).toHaveLength(1);
  },
};

export const AskWithGoalsSourceRefused: Story = {
  args: {
    model: {
      ...empty,
      asks: [askWithLane],
      sources: [
        { ...sourceByKind.goals, status: 'refused', reason: 'unreadable' },
        sourceByKind.log,
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const asks = openAsks(canvasElement);
    await expect(asks.getByText(fullText('Lane: Agree on weekend hours'))).toBeVisible();
    await expectAskMetadata(asks);
    await expectSessionLink(asks, hoursSession.name, 'Waiting on you', hoursHref);
    await expectSessionLink(asks, rotaSession.name, 'Working', rotaHref);
    await expect(section(canvasElement, 'Goals').getByText('No goals are listed.')).toBeVisible();
    const sources = section(canvasElement, 'Sources');
    await expect(rowWithText(sources, sourceByKind.goals.name).getByText('Refused')).toBeVisible();
    await expect(rowWithText(sources, sourceByKind.log.name).getByText('Read')).toBeVisible();
  },
};

export const AskWithoutText: Story = {
  args: { model: { ...empty, asks: [{ ...ask, text: null }] } },
  play: async ({ canvasElement }) => {
    const asks = openAsks(canvasElement);
    const words = asks.getByText('An open ask with no text', { exact: true });
    await expect(words).toBeVisible();
    await expect(words.closest('[data-authored]')).toBeNull();
    await expectAskMetadata(asks);
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
      const row = rowWithText(replies, name);
      const link = row.getByRole('link', { name });
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute('href', href);
      await expect(row.getByText(fullText(descriptor))).toBeVisible();
      await expect(row.getByText(request, { exact: true })).toBeVisible();
      await expect(link).toHaveAccessibleDescription(`${descriptor} ${request}`);
      await expectKeyboardLink(link, name, href);
      await expect(within(link).getByText(name, { exact: true })).toHaveStyle({
        textDecorationLine: 'underline',
      });
    }
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  },
};

export const WaitingSessionWithoutProject: Story = {
  args: {
    model: {
      ...empty,
      waitingSessions: [{ ...waitingSession, key: { ...waitingSession.key, project: ' ' } }],
    },
  },
  play: async ({ canvasElement }) => {
    const replies = section(canvasElement, 'Waiting on you').getByRole('list', {
      name: 'Sessions waiting for a reply',
    });
    await expect(
      within(replies).getByText(waitingSession.harnessLabel, { exact: true }),
    ).toBeVisible();
    await expect(replies).not.toHaveTextContent('·');
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
      await expect(view.getByText(fullText(label))).toBeVisible();
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
    const replyList = queue.getByRole('list', { name: 'Sessions waiting for a reply' });
    const replyRow = within(replyList);
    const askList = queue.getByRole('list', { name: 'Open asks' });
    await expect((await settledRect(replyList)).top).toBeGreaterThan(
      (await settledRect(askList)).bottom,
    );
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
    await expect(section(canvasElement, 'Goals').getByText('No goals are listed.')).toBeVisible();
    await expect(
      section(canvasElement, 'Tracker').getByText('No tracker items are listed.'),
    ).toBeVisible();
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
    await expect(tracker.getAllByRole('listitem')).toHaveLength(2);
    const known = rowWithText(tracker, knownTrackerRow.title);
    await expect(known.getByText('Done', { exact: true })).toBeVisible();
    await expect(known.queryByText(unknownStatus, { exact: false })).toBeNull();
    const unknown = rowWithText(tracker, unknownTrackerRow.title);
    await expect(unknown.getByText(unknownStatus, { exact: true })).toBeVisible();
    await expect(unknown.queryByText(/Blocked|In progress|Planned|Done/)).toBeNull();
    await expect(canvasElement).not.toHaveTextContent(unknownTrackerRow.rawStatus);
  },
};

const trackerStates = [
  [
    { ...knownTrackerRow, id: 'hours', title: 'Agree on pickup hours', status: 'blocked' },
    'Blocked',
  ],
  [
    { ...knownTrackerRow, id: 'shelf', title: 'Measure the shelf', status: 'running' },
    'In progress',
  ],
  [
    { ...knownTrackerRow, id: 'trial', title: 'Schedule the pickup trial', status: 'not_started' },
    'Planned',
  ],
  [
    { ...knownTrackerRow, id: 'carts', title: 'Order the book carts', status: 'waiting' },
    'Waiting',
  ],
  [
    { ...knownTrackerRow, id: 'kiosk', title: 'Build a pickup kiosk', status: 'dropped' },
    'Dropped',
  ],
] as const;
const trackerWithMetadata = {
  ...knownTrackerRow,
  date: changedDesign.date,
};

export const TrackerStatesAndMetadata: Story = {
  args: {
    model: { ...empty, tracker: [trackerWithMetadata, ...trackerStates.map(([item]) => item)] },
  },
  play: async ({ canvasElement }) => {
    const tracker = section(canvasElement, 'Tracker');
    const changedRow = rowWithText(tracker, knownTrackerRow.title);
    const date = changedRow.getByText(`Changed ${shortDate(changedAt)}`, { exact: true });
    await expect(date).toBeVisible();
    await expect(date).toHaveAttribute('datetime', changedAt);
    for (const [item, word] of trackerStates) {
      const row = rowWithText(tracker, item.title);
      await expect(row.getByText(word, { exact: true })).toBeVisible();
      await expect(row.queryByText(unknownStatus, { exact: true })).toBeNull();
    }
  },
};

export const RefusedSource: Story = {
  args: { model: { ...empty, sources: [sourceByKind.goals, refusedSource] } },
  play: async ({ canvasElement }) => {
    const sources = section(canvasElement, 'Sources');
    const read = rowWithText(sources, sourceByKind.goals.name);
    await expect(read.getByText('Read', { exact: true })).toBeVisible();
    await expect(read.queryByText('Refused', { exact: false })).toBeNull();
    const refused = rowWithText(sources, refusedSource.name);
    await expect(refused.getByText('Refused', { exact: true })).toBeVisible();
    await expect(refused.getByText('Marked private.', { exact: true })).toBeVisible();
    await expect(refused.queryByText('Read', { exact: true })).toBeNull();
  },
};

const refusedSources = [
  ['unreadable', 'Library goals', 'The source could not be read.'],
  ['malformed', 'Library design notes', 'The source did not have the expected format.'],
  ['symbolic link', 'Pickup work tracker', 'The file is a symbolic link.'],
  ['hard link', 'Library diagrams', 'The same file has another name.'],
  ['private', 'Annex design notes', 'Marked private.'],
  [
    'Status not recognised',
    'Pickup lane briefs',
    'Compass did not recognise a status the source needs.',
  ],
  ['branch missing', 'Library plan log', 'The branch is missing.'],
  ['git timed out', 'Annex tracker', 'Git did not answer in time.'],
] as const;

export const SourceRefusalReasons: Story = {
  args: {
    model: {
      ...empty,
      sources: refusedSources.map(([reason, name]) => ({
        id: reason,
        name,
        status: 'refused',
        reason,
      })),
    },
  },
  play: async ({ canvasElement }) => {
    const sources = section(canvasElement, 'Sources');
    for (const [, name, reason] of refusedSources) {
      const row = rowWithText(sources, name);
      await expect(row.getByText('Refused', { exact: true })).toBeVisible();
      await expect(row.getByText(reason, { exact: true })).toBeVisible();
    }
  },
};

export const UnusableDates: Story = {
  args: {
    model: {
      ...empty,
      asks: [{ ...ask, at: 'missing date' }],
      design: [
        { ...changedDesign, date: { ...changedDesign.date, at: '' } },
        { ...proposedDesign, date: { ...proposedDesign.date, at: 'unknown date' } },
      ],
      tracker: [{ ...trackerWithMetadata, date: { ...trackerWithMetadata.date, at: '' } }],
    },
  },
  play: async ({ canvasElement }) => {
    const askRow = rowWithText(openAsks(canvasElement), ask.text);
    await expect(askRow.getByText('Library plan log', { exact: true })).toBeVisible();
    const design = section(canvasElement, 'Design');
    const proposedRow = rowWithText(design, proposedDesign.title);
    await expect(proposedRow.getByText(proposed, { exact: true })).toBeVisible();
    await expect(within(canvasElement).queryByRole('time')).toBeNull();
    await expect(canvasElement).not.toHaveTextContent(/Invalid Date|Asked |Changed /);
  },
};

export const UndecidedDesignNotes: Story = {
  args: { model: { ...empty, design: [changedDesign, undecidedDesign] } },
  play: async ({ canvasElement }) => {
    const design = section(canvasElement, 'Design');
    await expect(design.getAllByRole('heading', { level: 3 }).map((el) => el.textContent)).toEqual([
      'Product decisions',
      'Not decided yet',
    ]);
    const decided = within(design.getByRole('list', { name: 'Product decisions' }));
    await expect(decided.getAllByRole('listitem')).toHaveLength(1);
    await expect(decided.getByText(changedDesign.title, { exact: true })).toBeVisible();
    await expect(decided.queryByText(undecidedDesign.title, { exact: true })).toBeNull();
    const open = within(design.getByRole('list', { name: 'Not decided yet' }));
    await expect(open.getByText(undecidedDesign.title, { exact: true })).toBeVisible();
    await expect(open.getByText(undecidedDesign.summary, { exact: true })).toBeVisible();
    const rule = design.getByRole('heading', { name: 'Not decided yet' }).parentElement;
    await expect(rule).toHaveStyle({ borderTopWidth: '1px' });
  },
};

export const OnlyUndecidedDesignNotes: Story = {
  args: { model: { ...empty, design: [undecidedDesign] } },
  play: async ({ canvasElement }) => {
    const design = section(canvasElement, 'Design');
    await expect(design.getAllByRole('heading', { level: 3 }).map((el) => el.textContent)).toEqual([
      'Not decided yet',
    ]);
    await expect(design.queryByRole('heading', { name: 'Product decisions' })).toBeNull();
  },
};

export const ChangedDate: Story = {
  args: { model: { ...empty, design: [changedDesign] } },
  play: async ({ canvasElement }) => {
    const design = section(canvasElement, 'Design');
    const date = design.getByText(`Changed ${shortDate(changedAt)}`, { exact: true });
    await expect(date).toBeVisible();
    await expect(date).toHaveAttribute('datetime', changedAt);
    await expect(design.queryByText(proposed, { exact: false })).toBeNull();
    await expect(design.queryByText(new RegExp(fromLog, 'i'))).toBeNull();
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
    await expect(design.queryByText(new RegExp(fromLog, 'i'))).toBeNull();
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
    await expect(queue.queryByText(proposed, { exact: false })).toBeNull();
  },
};

export const SourcesAndLimits: Story = {
  args: { model: { ...empty, sources: sourceList } },
  play: async ({ canvasElement }) => {
    const sources = section(canvasElement, 'Sources');
    await expect(sources.getAllByRole('listitem')).toHaveLength(6);
    for (const { name } of sourceList) {
      await expect(sources.getByText(name, { exact: true })).toBeVisible();
      await expect(rowWithText(sources, name).getByText('Read', { exact: true })).toBeVisible();
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

export const Narrow = {
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
      await expectProgress(card, '2 of 5 lanes are done');
      const done = await settledRect(card.getByRole('list', { name: 'Done' }));
      const inProgress = await settledRect(card.getByRole('list', { name: 'In progress' }));
      await expect(done.top).toBeGreaterThan(inProgress.bottom);
      await expect(inProgress.left).toBe(done.left);
      await expectRowPlacement(canvasElement, 'below');
      await expect(canvas.getByText('Status not recognised', { exact: true })).toBeVisible();
      await expect(canvas.getByText('Marked private.', { exact: true })).toBeVisible();
      await expect(canvas.queryByText(absentQueue, { exact: true })).toBeNull();
    }),
} satisfies Story;

export const ShortSessionOnPhone: Story = {
  args: {
    model: {
      ...empty,
      goals: [{ ...goal, lanes: [{ ...weekendLane, sessions: [{ ...hoursSession, name: 'A' }] }] }],
    },
  },
  parameters: Narrow.parameters,
  globals: Narrow.globals,
  play: async ({ canvasElement }) =>
    atPageWidth(400, async () => {
      const group = within(section(canvasElement, 'Goals').getByRole('list', { name: 'Blocked' }));
      const title = await settledRect(group.getByText(weekendLane.title, { exact: true }));
      const icon = await settledRect(group.getByRole('img', { name: 'Waiting on you' }));
      await expect(icon.left).toBe(title.left);
    }),
};
