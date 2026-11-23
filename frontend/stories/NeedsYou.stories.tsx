import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { SHOWN, SESSION_ROW_WORDS, GLOSSARY } from '../src/language/glossary';
import {
  TOP_LEVEL_VIEWS,
  fragmentForRoute,
  type RouteInput,
  type TopLevelView,
} from '../src/router/grammar';
import { headerBoard } from '../test/headerBoard';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeEnvironment } from '../src/transport/testing';
import { atPageWidth } from './PageFit';
import { fakeBackend } from '../test/storage_backends';

const generated = new Date(2026, 10, 23, 12).getTime() / 1000;
const claude = { project: 'acme/api', harness: 'claude' };
const board = {
  generated,
  window_hours: 24,
  ask: true,
  dismiss: true,
  asks: [
    { id: 'question', harness: 'claude', question: 'Proceed?', age_sec: 360 },
    {
      id: 'make-change',
      harness: 'claude',
      session_id: 'sign-in',
      question: 'Repeat the test?',
      age_sec: 360,
    },
  ],
  usage: [
    {
      harness: 'claude',
      state: 'ok',
      fiveH: { pct: 95, resetAt: generated + 3960, windowSec: 18000 },
      models: [{ pct: 95, label: 'fast', resetAt: generated + 3960 }],
    },
  ],
  irreversible_enabled: true,
  command_reports: [
    {
      harness: 'claude',
      sid: 'review',
      label: 'Cleanup command',
      tool_name: 'Bash',
      timestamp: generated - 240,
    },
  ],
  sessions: [
    {
      ...claude,
      sid: 'sign-in',
      title: 'Fix the flaky sign-in test',
      state: 'needs_input',
      blocked_since: generated - 360,
      state_detail: 'Waiting for command approval',
      wait_unconfirmed: true,
    },
    {
      ...claude,
      sid: 'review',
      title: 'Review pull request #482',
      ended_at: generated - 1500,
      dirty: true,
      changed: 2,
    },
    {
      ...claude,
      sid: 'dependencies',
      title: 'Nightly dependency check',
      state: 'idle',
      active: true,
      finished_at: generated - 10800 + 0.25,
    },
    {
      ...claude,
      sid: 'billing',
      title: 'Move billing to the new API',
      ended_at: generated - 7200,
      finished_at: generated - 7200,
      dirty: false,
    },
    {
      ...claude,
      sid: 'charts',
      title: 'Fix chart tooltips',
      ended_at: generated - 240,
      finished_at: generated - 240,
      dirty: false,
    },
    {
      ...claude,
      sid: 'delegated',
      title: 'Inspect query plans',
      state: 'idle',
      delegated_launches: 2,
      delegated_unpaired: 1,
      delegated_quiet_since: generated - 3600,
      delegated_latest_launch_at: generated - 360,
    },
    {
      ...claude,
      sid: 'untimed',
      harness: 'codex',
      title: 'Check the deployment',
      state: 'needs_input',
      state_detail: 'Awaiting confirmation',
    },
    ...['Review the guide', 'Check the screenshots', 'Update the release notes'].map(
      (title, index) => ({
        ...claude,
        sid: `clean-${index}`,
        title,
        ended_at: generated - 120,
        dirty: false,
      }),
    ),
    {
      ...claude,
      sid: 'long',
      state: 'working',
      state_detail: 'Working',
      turn: { elapsed_h: '1h 10m', eta_h: '5m', long: true },
    },
  ],
};

const absoluteTimes = [new Date(2026, 10, 23, 9), new Date(2026, 10, 23, 10)];
const absoluteReset = new Date(2026, 10, 23, 13);
const withoutClock = {
  sessions: absoluteTimes.map((time, index) => ({
    ...claude,
    sid: `checkout-${index + 1}`,
    title: `Checkout ${index + 1}`,
    project_key: `path:checkout-${index + 1}`,
    project_identity_source: 'working directory path',
    started_at: time.getTime() / 1000,
  })),
  usage: [
    {
      harness: 'claude',
      state: 'ok',
      models: [{ pct: 95, label: 'fast', resetAt: absoluteReset.getTime() / 1000 }],
    },
  ],
};

function absoluteTime(time: Date) {
  const date = time.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
  const clock = time.toLocaleTimeString(undefined, { timeStyle: 'short' });
  return `on ${date} at ${clock}`;
}

function Example({
  missingClock = false,
  canDismiss = true,
  onRefresh,
}: {
  readonly missingClock?: boolean;
  readonly canDismiss?: boolean;
  readonly onRefresh?: (refresh: () => Promise<void>) => void;
}) {
  const [shell] = useState(() => {
    const backend = fakeBackend();
    let revision = 0;
    const shell = createShell({
      env: createFakeEnvironment(),
      router: createRouter(fakeRouterEnvironment('#n=attention').env),
      provider: () => backend,
      doc: null,
      search: '',
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          new Response(
            url.startsWith('/api/data')
              ? JSON.stringify(missingClock ? withoutClock : { ...board, dismiss: canDismiss })
              : '{"ok":true,"persisted":true}',
            { headers: { 'X-Compass-Revision': `9.${++revision}` } },
          ),
        ),
    });
    return shell;
  });
  useEffect(
    () =>
      onRefresh?.(async () => {
        await shell.runtime.refresh();
      }),
    [onRefresh, shell],
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

const meta = {
  title: 'Board/Needs you',
  component: Example,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

function lane(canvasElement: HTMLElement, name: string) {
  const section = canvasElement.querySelector<HTMLElement>(
    `[data-next-attention-section="${name}"]`,
  );
  if (!section) throw new Error(`Missing ${name} section`);
  return within(section);
}

export const QueuesAndBadge: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { name: 'Waiting on you (2)' });
    const headings = canvas.getAllByRole('heading', { level: 2 });
    await expect(headings.slice(0, 3).map((node) => node.textContent)).toEqual([
      'Waiting on you (2)',
      'Worth a look (4)',
      'Ready to wrap up (5)',
    ]);
    const waiting = lane(canvasElement, 'needs');
    const flagged = lane(canvasElement, 'risk');
    const ready = lane(canvasElement, 'close');
    await expect(waiting.getAllByRole('img', { name: 'Waiting on you' })).toHaveLength(2);
    await expect(flagged.getAllByRole('img', { name: 'Worth a look' })).toHaveLength(4);
    await expect(ready.getAllByRole('img', { name: 'Ended' })).toHaveLength(3);
    await expect(ready.getByRole('button', { name: 'Show 2 more' })).toBeVisible();
    await expect(canvas.getByRole('link', { name: 'Needs you 6' })).toBeVisible();
    for (const row of canvasElement.querySelectorAll('.next-attention-session')) {
      await expect(row.textContent).not.toMatch(/\bfinished\b/i);
    }
  },
};

export const ReadableTimes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('Waiting for command approval');
    await expect(lane(canvasElement, 'needs').getByText(/waiting 6 minutes/)).toBeVisible();
    await expect(canvas.getByText('Awaiting confirmation')).toBeVisible();
    await expect(canvas.getByText(/Ended 25 minutes ago/)).toBeVisible();
    await expect(canvas.getByText(/1 hour 10 minutes into turn/)).toBeVisible();
    await expect(canvas.getByText('1 hour 6 minutes')).toBeVisible();
    await expect(canvas.queryByRole('heading', { name: 'Not on this board yet' })).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: "What Compass can't see" }));
    await waitFor(() => expect(canvas.getByText('Coverage by agent')).toBeVisible());
    await waitFor(() =>
      expect(canvas.getByRole('heading', { name: 'Not on this board yet' })).toBeVisible(),
    );
    await expect(
      canvas.getByText('A shape match does not prove the action succeeded.'),
    ).toBeVisible();
    await expect(canvas.getByText(/Bash · 4 minutes ago/)).toBeVisible();
  },
};

export const AbsoluteTimesWithoutBoardClock: Story = {
  args: { missingClock: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText(`Reset ${absoluteTime(absoluteReset)}`);
    const cards = lane(canvasElement, 'risk');
    const controls = cards.getAllByRole('button', { name: 'Show technical details' });
    for (const [index, time] of absoluteTimes.entries()) {
      const control = controls[index];
      if (!control) throw new Error('Missing location evidence');
      await userEvent.click(control);
      await waitFor(() =>
        expect(
          cards.getByText(new RegExp(`Checkout ${index + 1}.*Start time ${absoluteTime(time)}`)),
        ).toBeVisible(),
      );
    }
  },
};

const navOrder = [
  'sessions',
  'projects',
  'attention',
  'intent',
  'settings',
  'help',
] as const satisfies readonly TopLevelView[];
const headerRoutes: readonly (readonly [RouteInput, TopLevelView])[] = [
  ...navOrder.map((view) => [{ view }, view] as const),
  [{ view: 'project', project: 'acme/dashboard' }, 'projects'],
  [
    { view: 'session', project: 'acme/dashboard', harness: 'claude', session: 'active' },
    'projects',
  ],
  [
    {
      view: 'session',
      project: 'acme/dashboard',
      harness: 'claude',
      session: 'active',
      from: 'sessions',
    },
    'sessions',
  ],
];

function HeaderExample() {
  const [example] = useState(() => {
    const base = headerBoard();
    const fixture = {
      ...base,
      sessions: [
        ...base.sessions,
        {
          harness: 'claude',
          project: 'acme/dashboard',
          sid: 'reported-block',
          title: 'Review the settings',
          state: 'needs_input',
          state_detail: 'Permission prompt: Read settings',
        },
      ],
    };
    let data = fixture;
    let publish: () => void = () => undefined;
    const firstBoard = new Promise<void>((resolve) => {
      publish = resolve;
    });
    const router = createRouter(fakeRouterEnvironment('#n=sessions').env);
    const shell = createShell({
      env: createFakeEnvironment(),
      router,
      provider: () => fakeBackend(),
      doc: null,
      search: '',
      reducedMotion: () => true,
      fetch: async (url) => {
        if (!url.startsWith('/api/data')) return new Response('{}');
        await firstBoard;
        return new Response(JSON.stringify(data));
      },
    });
    return {
      shell,
      publish,
      stopWork: () => {
        data = {
          ...fixture,
          generated: fixture.generated + 1,
          sessions: fixture.sessions.filter(
            (session) => !('state' in session) || session.state !== 'working',
          ),
        };
        return shell.runtime.refresh();
      },
    };
  });
  useEffect(
    () => () => {
      example.shell.runtime.dispose();
      example.shell.display.dispose();
    },
    [example],
  );
  return (
    <>
      <App shell={example.shell} />
      <button type="button" onClick={example.publish}>
        Publish the first board
      </button>
      <button type="button" onClick={() => void example.stopWork()}>
        Publish a board with no working sessions
      </button>
      {headerRoutes.map(([route]) => {
        const fragment = fragmentForRoute(route);
        return (
          <button type="button" key={fragment} onClick={() => example.shell.router.navigate(route)}>
            Visit {fragment}
          </button>
        );
      })}
    </>
  );
}

export const HeaderTracksTheCurrentPageAndBoard: Story = {
  render: () => <HeaderExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const primary = within(canvas.getByRole('navigation', { name: SHOWN.primary }));
    const pill = canvas.getByRole('status', { name: SHOWN.workingSessions });
    await expect(pill).toHaveTextContent(SHOWN.waitingForBoard);
    await expect(primary.getByRole('link', { name: SHOWN.attention })).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Publish the first board' }));
    const count = SHOWN.workingCountMany.replace('{count}', '2');
    await waitFor(() => expect(pill).toHaveTextContent(count));
    await expect(new Set(navOrder)).toEqual(new Set(TOP_LEVEL_VIEWS));
    for (const [route, current] of headerRoutes) {
      await userEvent.click(
        canvas.getByRole('button', { name: `Visit ${fragmentForRoute(route)}` }),
      );
      const links = primary.getAllByRole('link');
      await expect(links.map((link) => link.textContent?.trim().replace(/\s+\d+$/, ''))).toEqual(
        navOrder.map((view) => SHOWN[view]),
      );
      await waitFor(() =>
        expect(primary.getAllByRole('link', { current: 'page' })).toEqual([
          links[navOrder.indexOf(current)],
        ]),
      );
      await expect(pill).toHaveTextContent(count);
      if (current === 'attention') {
        const rows = (section: string) =>
          canvasElement.querySelectorAll(
            `[data-next-attention-section="${section}"] > ol > li:not([hidden])`,
          ).length;
        const waiting = rows('needs');
        const worth = rows('risk');
        await expect(waiting).toBe(3);
        await expect(worth).toBe(1);
        await expect(
          canvas.getByRole('heading', { name: `${SESSION_ROW_WORDS.waitingOnYou} (${waiting})` }),
        ).toBeVisible();
        await expect(
          canvas.getByRole('heading', { name: `${SESSION_ROW_WORDS.worthALook} (${worth})` }),
        ).toBeVisible();
        await expect(
          primary.getByRole('link', { name: `${SHOWN.attention} ${waiting + worth}` }),
        ).toBeVisible();
        await expect(canvas.getByText('Approve the command?')).toBeVisible();
        await expect(
          canvas.getByText('Permission prompt: Read settings', { exact: false }),
        ).toBeVisible();
      }
      if (route.view === 'session') {
        const details = canvas.getAllByRole('button', {
          name: GLOSSARY.showTechnicalDetails.plain,
        });
        await expect(details).toHaveLength(1);
        await expect(details[0]).toHaveAttribute('aria-expanded', 'false');
      }
    }
    await userEvent.click(canvas.getByRole('button', { name: 'Visit #n=sessions' }));
    await userEvent.click(
      canvas.getByRole('button', { name: 'Publish a board with no working sessions' }),
    );
    await waitFor(() => expect(pill).toHaveTextContent(SHOWN.nothingWorking));
  },
};

export const DismissAndUndo: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { name: /Worth a look/ });
    const article = canvas
      .getByRole('heading', { name: 'Review pull request #482' })
      .closest('article');
    if (!article) throw new Error('Missing the flagged session');
    const row = within(article);
    await expect(
      row.getByText('Worth a look: Ended with uncommitted work (2 changed entries)'),
    ).toBeVisible();
    await userEvent.click(row.getByRole('button', { name: 'Show technical details' }));
    await expect(row.getByRole('button', { name: 'Hide technical details' })).toBeVisible();
    await expect(canvas.getByRole('button', { name: "What Compass can't see" })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    await userEvent.click(row.getByRole('button', { name: 'Dismiss' }));
    await expect(
      (await canvas.findAllByText('Dismissed.')).find((node) =>
        node.closest('[data-next-dismiss-receipt]'),
      ),
    ).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Undo' }));
    await expect(
      (await canvas.findAllByText('Restored.')).find((node) =>
        node.closest('[data-next-dismiss-receipt]'),
      ),
    ).toBeVisible();
  },
};

export const DismissalsOff: Story = {
  args: { canDismiss: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { name: /Worth a look/ });
    await expect(canvas.queryByRole('button', { name: 'Dismiss' })).toBeNull();
    await expect(canvas.queryByRole('button', { name: 'Mark as read' })).toBeNull();
  },
};

export const WrapUpStaysOpen: Story = {
  play: async ({ canvasElement, mount }) => {
    let refresh: (() => Promise<void>) | undefined;
    await mount(
      <Example
        onRefresh={(run) => {
          refresh = run;
        }}
      />,
    );
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { name: /Ready to wrap up/ });
    const section = lane(canvasElement, 'close');
    await expect(section.getAllByRole('listitem')).toHaveLength(3);
    await userEvent.click(section.getByRole('button', { name: 'Show 2 more' }));
    await expect(section.getAllByRole('listitem')).toHaveLength(5);
    if (!refresh) throw new Error('Missing the board refresh');
    await refresh();
    await expect(section.getByRole('button', { name: 'Show fewer (hide 2)' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    await expect(section.getAllByRole('listitem')).toHaveLength(5);
  },
};

function fit(width: number): Story {
  return {
    play: ({ canvasElement }) =>
      atPageWidth(width, async () => {
        const canvas = within(canvasElement);
        await canvas.findByRole('heading', { name: 'Waiting on you (2)' });
        await userEvent.click(canvas.getByRole('button', { name: "What Compass can't see" }));
        await waitFor(() =>
          expect(canvas.getByRole('heading', { name: 'Not on this board yet' })).toBeVisible(),
        );
      }),
  };
}

export const Fits390 = fit(390);
export const Fits375 = fit(375);
export const Fits320 = fit(320);
