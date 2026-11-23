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
import { settledRect } from './settled-layout';

const generated = new Date(2026, 10, 23, 12).getTime() / 1000;
const claude = { project: 'acme/api', harness: 'claude' };
const board = {
  generated,
  window_hours: 24,
  ask: true,
  dismiss: true,
  harnesses: [
    {
      key: 'codex',
      label: 'Codex',
      reports_needs_input: true,
      reports_needs_input_when: 'where approvals are enabled',
      reports_rate: true,
    },
    { key: 'droid', label: 'Droid' },
  ],
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
  waitingForBoard = false,
  writeFails = false,
  persisted = true,
  collection = 'loaded',
  removeOnWrite = false,
  beforeWrite,
}: {
  readonly missingClock?: boolean;
  readonly waitingForBoard?: boolean;
  readonly writeFails?: boolean;
  readonly persisted?: boolean;
  readonly collection?:
    | 'loaded'
    | 'empty'
    | 'missing'
    | 'failed'
    | 'partial'
    | 'wait-and-dirty'
    | 'ended-collision';
  readonly removeOnWrite?: boolean;
  readonly beforeWrite?: () => Promise<void>;
  readonly canDismiss?: boolean;
  readonly onRefresh?: (refresh: () => Promise<void>) => void;
}) {
  const [shell] = useState(() => {
    const backend = fakeBackend();
    let revision = 0;
    const failed = { key: 'claude', discovered: true, error: 'Read failed' };
    let payload: object = { ...board, dismiss: canDismiss };
    if (collection === 'empty') payload = { generated, window_hours: 24, sessions: [] };
    if (collection === 'missing') payload = { generated, usage: board.usage };
    if (collection === 'failed')
      payload = { generated, sessions: [], harnesses: [failed], usage: board.usage };
    if (collection === 'partial')
      payload = {
        generated,
        sessions: [board.sessions.find(({ sid }) => sid === 'untimed')],
        harnesses: [failed, { key: 'codex', discovered: true }],
      };
    if (collection === 'wait-and-dirty')
      payload = {
        ...board,
        sessions: board.sessions.filter(({ sid }) => sid === 'review'),
        asks: [
          { id: 'ask', harness: 'claude', session_id: 'review', question: 'Review the report?' },
        ],
      };
    if (collection === 'ended-collision')
      payload = {
        ...withoutClock,
        generated,
        sessions: withoutClock.sessions.map((row, index) =>
          index === 0 ? { ...row, ended_at: generated - 120, dirty: null } : row,
        ),
      };
    const shell = createShell({
      env: createFakeEnvironment(),
      router: createRouter(fakeRouterEnvironment('#n=attention').env),
      provider: () => backend,
      doc: null,
      search: '',
      reducedMotion: () => true,
      fetch: (url) => {
        const writing = url.startsWith('/api/dismiss');
        if (writing && removeOnWrite)
          payload = { ...board, sessions: board.sessions.filter(({ sid }) => sid !== 'review') };
        if (writing && beforeWrite)
          return beforeWrite().then(() => new Response(JSON.stringify({ ok: true, persisted })));
        return url.startsWith('/api/data') && waitingForBoard
          ? new Promise<Response>(() => undefined)
          : Promise.resolve(
              new Response(
                url.startsWith('/api/data')
                  ? JSON.stringify(missingClock ? withoutClock : payload)
                  : JSON.stringify({ ok: true, persisted }),
                {
                  status: writeFails && url.startsWith('/api/dismiss') ? 503 : 200,
                  headers: { 'X-Compass-Revision': `9.${++revision}` },
                },
              ),
            );
      },
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

export const FirstBoardPending: Story = {
  args: { waitingForBoard: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText('The first payload has not arrived yet.')).toBeVisible();
    await expect(canvas.getByRole('link', { name: 'Needs you' })).toBeVisible();
    await expect(
      canvas.queryByRole('heading', { name: /Waiting on you|Worth a look|Ready to wrap up/ }),
    ).toBeNull();
  },
};

const collectionWords = [
  'No sessions in this 24-hour payload',
  'The board published no session collection.',
  'Session counts are unavailable because the sources could not be read.',
];

function collectionState(collection: 'empty' | 'missing' | 'failed', words: string): Story {
  return {
    args: { collection },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      await expect(await canvas.findByText(words, { exact: true })).toBeVisible();
      for (const other of collectionWords.filter((text) => text !== words))
        await expect(canvas.queryByText(other, { exact: true })).toBeNull();
      await expect(
        canvas.queryByRole('heading', { name: /Waiting on you|Worth a look|Ready to wrap up/ }),
      ).toBeNull();
      await expect(canvas.getByRole('link', { name: 'Needs you' })).toBeVisible();
      if (collection === 'empty') return;
      await expect(canvas.queryByRole('heading', { name: 'Other warnings' })).toBeNull();
      await userEvent.click(canvas.getByRole('button', { name: "What Compass can't see" }));
      await waitFor(() =>
        expect(canvas.getByRole('heading', { name: 'Other warnings' })).toBeVisible(),
      );
      const warnings = lane(canvasElement, 'board-risk');
      await expect(warnings.getAllByText(/95%/)[0]).toBeVisible();
    },
  };
}

export const EmptyCollection = collectionState('empty', 'No sessions in this 24-hour payload');
export const MissingCollection = collectionState(
  'missing',
  'The board published no session collection.',
);
export const UnreadableCollection = collectionState(
  'failed',
  'Session counts are unavailable because the sources could not be read.',
);

export const PartialCollection: Story = {
  args: { collection: 'partial' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole('heading', { name: 'Waiting on you (1)' })).toBeVisible();
    await expect(canvas.getByText('Awaiting confirmation', { exact: true })).toBeVisible();
    for (const words of collectionWords)
      await expect(canvas.queryByText(words, { exact: true })).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: "What Compass can't see" }));
    await waitFor(() => expect(canvas.getByText('Harness sources: 1 failed.')).toBeVisible());
  },
};

export const WaitingWithDirtyEnd: Story = {
  args: { collection: 'wait-and-dirty' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { name: 'Waiting on you (1)' });
    const waiting = lane(canvasElement, 'needs');
    await expect(waiting.getByText('Review the report?')).toBeVisible();
    await expect(
      waiting.getByText('Session ended with uncommitted work: 2 changed entries'),
    ).toBeVisible();
    await expect(canvas.getByRole('link', { name: 'Needs you 1' })).toBeVisible();
    await expect(canvas.queryByRole('heading', { name: /Worth a look/ })).toBeNull();
  },
};

export const EndedWithSharedLabel: Story = {
  args: { collection: 'ended-collision' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const title = await canvas.findByRole('heading', { name: 'Checkout 1' });
    const row = within(title.closest('article') as HTMLElement);
    await expect(row.getByText(/Ended 2 minutes ago/)).toBeVisible();
    await expect(row.getByText('Worth a look: Shared project label')).toBeVisible();
    await expect(row.queryByText(/Last active|Ended with uncommitted work/)).toBeNull();
  },
};

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
    const firstSection = headings[0]?.closest('section');
    await expect(getComputedStyle(firstSection as Element).backgroundColor).toBe(
      'rgb(255, 255, 255)',
    );
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
    await expect(canvas.getByText('1 hour 6 minutes')).not.toBeVisible();
    await expect(canvas.queryByRole('heading', { name: 'Not on this board yet' })).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: "What Compass can't see" }));
    await waitFor(() =>
      expect(canvas.getByRole('heading', { name: 'Other warnings' })).toBeVisible(),
    );
    await expect(lane(canvasElement, 'board-risk').getByText('1 hour 6 minutes')).toBeVisible();
    await waitFor(() => expect(canvas.getByText('Coverage by agent')).toBeVisible());
    await expect(
      canvas.getByText('needs-input reporting, where approvals are enabled · token-rate reporting'),
    ).toBeVisible();
    await expect(canvas.getByText('Waits not reported · Token rate not reported')).toBeVisible();
    await expect(canvas.queryByText(/Harness does not report blocks/)).toBeNull();
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
    await canvas.findByRole('heading', { name: /Worth a look/ });
    await userEvent.click(canvas.getByRole('button', { name: "What Compass can't see" }));
    await waitFor(() =>
      expect(canvas.getByText(`Reset ${absoluteTime(absoluteReset)}`)).toBeVisible(),
    );
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

export const DismissFails: Story = {
  args: { writeFails: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const title = await canvas.findByRole('heading', { name: 'Review pull request #482' });
    const row = within(title.closest('article') as HTMLElement);
    await userEvent.click(row.getByRole('button', { name: 'Dismiss' }));
    await expect(
      (await canvas.findAllByText('Compass could not save that change.')).find((node) =>
        node.closest('[data-next-dismiss-receipt]'),
      ),
    ).toBeVisible();
    await expect(title).toBeVisible();
    await expect(canvas.queryByRole('button', { name: 'Undo' })).toBeNull();
  },
};

export const MarkReadWasNotSaved: Story = {
  args: { persisted: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const title = await canvas.findByRole('heading', { name: 'Move billing to the new API' });
    const row = within(title.closest('article') as HTMLElement);
    await userEvent.click(row.getByRole('button', { name: 'Mark as read' }));
    const receipt = within(
      canvasElement.querySelector('[data-next-dismiss-receipt]') as HTMLElement,
    );
    await expect(receipt.getByText('Compass could not save that change.')).toBeVisible();
    await expect(title).toBeVisible();
    await expect(receipt.queryByText(/Marked as read/)).toBeNull();
    await expect(receipt.queryByRole('button', { name: 'Undo' })).toBeNull();
  },
};

export const KeyboardDismissMovesToUndo: Story = {
  args: { removeOnWrite: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const title = await canvas.findByRole('heading', { name: 'Review pull request #482' });
    const row = within(title.closest('article') as HTMLElement);
    row.getByRole('button', { name: 'Dismiss' }).focus();
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(title).not.toBeInTheDocument());
    await expect(canvas.getByRole('button', { name: 'Undo' })).toHaveFocus();
  },
};

export const DismissalSaving: Story = {
  play: async ({ canvasElement, mount }) => {
    let release: () => void = () => undefined;
    const hold = new Promise<void>((resolve) => {
      release = resolve;
    });
    await mount(<Example beforeWrite={() => hold} />);
    const canvas = within(canvasElement);
    const flagged = await canvas.findByRole('heading', { name: 'Review pull request #482' });
    const read = canvas.getAllByRole('button', { name: 'Mark as read' })[0] as HTMLElement;
    const dismiss = within(flagged.closest('article') as HTMLElement).getByRole('button', {
      name: 'Dismiss',
    });
    try {
      await userEvent.click(dismiss);
      await expect(dismiss).toHaveAttribute('aria-busy', 'true');
      await expect(within(dismiss).getByText('Saving…')).toBeVisible();
      await expect(read).toBeDisabled();
    } finally {
      release();
    }
    await waitFor(() => expect(read).toBeEnabled());
    await expect(canvas.getByRole('button', { name: 'Undo' })).toBeVisible();
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
        const view = within(
          canvasElement.querySelector('[data-next-view-body="attention"]') as HTMLElement,
        );
        const controls = [...view.getAllByRole('button'), ...view.getAllByRole('link')];
        for (const box of await Promise.all(controls.map(settledRect))) {
          await expect(box.width).toBeGreaterThanOrEqual(44);
          await expect(box.height).toBeGreaterThanOrEqual(44);
          await expect(box.left).toBeGreaterThanOrEqual(0);
          await expect(box.right).toBeLessThanOrEqual(window.innerWidth);
        }
      }),
  };
}

export const Fits390 = fit(390);
export const Fits375 = fit(375);
export const Fits320 = fit(320);
