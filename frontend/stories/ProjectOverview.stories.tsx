import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import { scenarios } from '../src/project/generate.test.helper';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { atPageWidth } from './PageFit';

const PROJECT = 'acme/dashboard';
const STAMP = new Date(2026, 10, 23, 14).getTime() / 1000;
const session = (title: string, state: string, extra = {}) => ({
  project: PROJECT,
  sid: title,
  title,
  state,
  harness: 'claude',
  started_at: STAMP - 300,
  last_activity: STAMP - 30,
  ...extra,
});
const working = session('Review the build', 'working', {
  instruction: { label: 'asked', text: 'Prepare the dashboard for review', at: STAMP - 240 },
  subagents: [{ name: 'Read the test output', active: true }],
});
const waiting = session('Request approval', 'needs_input');
const dirty = session('Write settings stories', 'idle', {
  ended_at: STAMP - 120,
  dirty: true,
  changed: 2,
});
const clean = session('Fix chart labels', 'idle', { ended_at: STAMP - 240, dirty: false });
const quiet = session('Review complete', 'idle', { finished_at: STAMP - 100 });
const unknown = session('Inspect the record', 'idle', { harness: 'codex' });
const noOutcome = session('Read the source', 'idle', { ended_at: STAMP - 30 });
const clipboard: string[] = [];
const timelineExample = scenarios().find(({ name }) => name === 'a long course');

function Example({
  sessions,
  workflow = false,
  measure = false,
  board = {},
  mixedTime = false,
  timeline = false,
}: {
  readonly sessions: readonly ReturnType<typeof session>[];
  readonly workflow?: boolean;
  readonly measure?: boolean;
  readonly board?: object;
  readonly mixedTime?: boolean;
  readonly timeline?: boolean;
}) {
  const [storage] = useState(() => fakeBackend());
  const [reload, setReload] = useState(0);
  return (
    <ProjectMount
      key={reload}
      sessions={sessions}
      workflow={workflow}
      measure={measure}
      board={board}
      mixedTime={mixedTime}
      timeline={timeline}
      storage={storage}
      reload={() => setReload(reload + 1)}
    />
  );
}

function ProjectMount({
  sessions,
  workflow,
  measure,
  board,
  mixedTime,
  timeline,
  storage,
  reload,
}: {
  readonly sessions: readonly ReturnType<typeof session>[];
  readonly workflow: boolean;
  readonly measure: boolean;
  readonly board: object;
  readonly mixedTime: boolean;
  readonly timeline: boolean;
  readonly storage: ReturnType<typeof fakeBackend>;
  readonly reload: () => void;
}) {
  const [shell] = useState(() => {
    clipboard.length = 0;
    let samples = 0;
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(
        fakeRouterEnvironment(timeline ? '#n=project:course%2Fapp' : '#n=project:acme%2Fdashboard')
          .env,
      ),
      provider: () => storage,
      doc: null,
      search: '',
      reducedMotion: () => true,
      host: { reload },
      clipboard: () => ({
        writeText: async (text) => {
          clipboard.push(text);
        },
      }),
      fetch: (url) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              url.startsWith('/api/data')
                ? {
                    generated:
                      STAMP +
                      (measure
                        ? samples++ * 1200
                        : mixedTime
                          ? ([0, 1140, 1200][samples++] ?? 1200)
                          : 0),
                    sessions: mixedTime && samples === 1 ? [quiet] : sessions,
                    harnesses: [
                      { key: 'claude', label: 'Claude Code' },
                      { key: 'codex', label: 'Codex' },
                    ],
                    tripwires: { enabled: workflow },
                    ...board,
                    ...(timeline ? timelineExample?.board : {}),
                  }
                : timeline && url.startsWith('/api/project-context')
                  ? timelineExample?.context
                  : {},
            ),
          ),
        ),
    });
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return (
    <>
      <App shell={shell} />
      {measure || mixedTime ? (
        <button type="button" onClick={() => void shell.runtime.refresh()}>
          Record another observation
        </button>
      ) : null}
      <button type="button" className="sr-only" onClick={reload}>
        Reload example
      </button>
    </>
  );
}

const meta = {
  title: 'Project',
  component: Example,
  args: { sessions: [working, waiting, dirty, clean, quiet], workflow: false },
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Overview: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole('heading', { name: PROJECT })).toBeVisible();
    await expect(
      within(canvas.getByRole('region', { name: 'Working on' })).getByText(
        'Prepare the dashboard for review',
      ),
    ).toBeVisible();
    const needs = within(canvas.getByRole('region', { name: 'Needs you' }));
    await expect(
      needs.getByText('1 waiting on you · 1 worth a look', { exact: true }),
    ).toBeVisible();
    const legend = within(canvas.getByRole('region', { name: 'Sessions' }));
    await expect(legend.getByRole('list', { name: 'What the icons mean' })).toBeVisible();
    const end = within(canvas.getByRole('region', { name: 'How today’s sessions ended' }));
    await expect(end.getByRole('heading', { name: 'Worth a look' })).toBeVisible();
    await expect(
      end.getByText('Ended with uncommitted work (2 changed entries)', { exact: true }),
    ).toBeVisible();
    await expect(end.getByRole('heading', { name: 'Ready to wrap up' })).toBeVisible();
    await expect(end.getByText('Ended with a clean working tree', { exact: true })).toBeVisible();
    await expect(
      canvas.getByText('Waiting for enough recorded working time.', { exact: true }),
    ).toBeVisible();
  },
};

export const CopyAndNotes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Copy a status update' }));
    await expect(await canvas.findByRole('button', { name: 'Copied' })).toBeVisible();
    await expect(clipboard).toHaveLength(1);
    await expect(clipboard[0]).toContain('Project: dashboard');
    await expect(canvasElement.querySelector('details')).toBeNull();
    const notes = canvas.getByRole('textbox', { name: 'Your notes' });
    await userEvent.type(notes, 'Review the new checklist tomorrow');
    await expect(canvas.queryByRole('button', { name: /Save note/ })).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: 'Show technical details' }));
    await expect(canvas.queryByRole('button', { name: 'Edit OUTCOME' })).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: 'Reload example' }));
    await expect(await canvas.findByRole('textbox', { name: 'Your notes' })).toHaveValue(
      'Review the new checklist tomorrow',
    );
  },
};

export const MeasuredTime: Story = {
  args: { sessions: [working], measure: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const time = within(
      await canvas.findByRole('region', { name: 'Time agents worked on their own' }),
    );
    const waiting = 'Waiting for enough recorded working time.';
    await expect(time.getByText(waiting, { exact: true })).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Record another observation' }));
    await expect(await time.findByText('100%', { exact: true })).toBeVisible();
    await expect(
      time.getByText('0 interventions inferred over 20 minutes of observation.', { exact: true }),
    ).toBeVisible();
    await expect(
      time.getByRole('meter', {
        name: 'Share of working or waiting time spent working without an open request',
      }),
    ).toBeVisible();
    await expect(time.queryByText(waiting, { exact: true })).toBeNull();
  },
};

export const TechnicalDetails: Story = {
  args: { workflow: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole('button', { name: 'Show technical details' });
    await expect(canvasElement.innerText).not.toMatch(/\b(?:FO|first officer|Captain|REFRESH)\b/i);
    await expect(canvas.getByText('Stage alerts', { exact: true })).not.toBeVisible();
    await expect(canvas.queryByText('Read-only terminal', { exact: true })).toBeNull();
    await expect(canvas.getByText('Your note (this tab only)', { exact: true })).not.toBeVisible();
    await userEvent.click(trigger);
    await waitFor(() =>
      expect(canvas.getByText(/FO is the first officer.*Captain is you/)).toBeVisible(),
    );
    await expect(canvas.getByRole('heading', { name: 'Stage alerts' })).toBeVisible();
    await expect(canvas.getByText('Your note (this tab only)', { exact: true })).toBeVisible();
    await expect(canvas.getByText('Read-only terminal', { exact: true })).toBeVisible();
    await expect(
      canvas.getByRole('combobox', { name: 'Session for the read-only terminal' }),
    ).toBeVisible();
    await expect(canvas.getByRole('button', { name: 'Hide technical details' })).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Hide technical details' }));
  },
};

function stateStory(row: ReturnType<typeof session>, state: string): Story {
  return {
    args: { sessions: [row] },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      const sessions = within(await canvas.findByRole('region', { name: 'Sessions' }));
      const link = within(sessions.getByRole('link', { name: new RegExp(row.title) }));
      for (const word of ['Waiting on you', 'Working', 'Ended', 'Quiet']) {
        await expect(Boolean(link.queryByRole('img', { name: word }))).toBe(word === state);
      }
      if (state === 'State not published') {
        await expect(link.getByText(state, { exact: true })).toBeVisible();
        const running = within(canvas.getByRole('region', { name: 'Running now' }));
        await expect(running.getByText('Working state unavailable', { exact: true })).toBeVisible();
        await expect(running.queryByText('Nothing working right now', { exact: true })).toBeNull();
      } else await expect(link.queryByText('State not published', { exact: true })).toBeNull();
    },
  };
}

export const Working = stateStory(working, 'Working');
export const Waiting = stateStory(waiting, 'Waiting on you');
export const Quiet = stateStory(quiet, 'Quiet');
export const Ended = stateStory(dirty, 'Ended');
export const CodexStateNotPublished = stateStory(unknown, 'State not published');
export const EndOutcomeUnavailable: Story = {
  args: { sessions: [noOutcome] },
  play: async ({ canvasElement }) => {
    const end = within(
      await within(canvasElement).findByRole('region', { name: 'How today’s sessions ended' }),
    );
    await expect(end.getByText('No outcome was published', { exact: true })).toBeVisible();
    await expect(end.queryByRole('heading', { name: 'Ready to wrap up' })).toBeNull();
    await expect(end.queryByRole('heading', { name: 'Worth a look' })).toBeNull();
  },
};

function fit(width: number): Story {
  return {
    play: async ({ canvasElement }) => {
      await within(canvasElement).findByRole('heading', { name: PROJECT });
      await atPageWidth(width, async () => {
        await expect(
          within(canvasElement).getByRole('textbox', { name: 'Your notes' }),
        ).toBeVisible();
      });
    },
  };
}
export const Fits390 = fit(390);
export const Fits375 = fit(375);
export const Fits320 = fit(320);

function endStory(
  row: ReturnType<typeof session>,
  answer: string,
  board: object = {},
  absence?: string,
): Story {
  return {
    args: { sessions: [row], board },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      const end = within(await canvas.findByRole('region', { name: 'How today’s sessions ended' }));
      await expect(end.getByText(answer, { exact: true })).toBeVisible();
      if (absence) await expect(end.getByText(absence, { exact: true })).toBeVisible();
      for (const other of [
        'No outcome was published',
        'No session ends were reported today.',
        'Ended with uncommitted work (2 changed entries)',
        'Ended with a clean working tree',
      ].filter((text) => text !== answer))
        await expect(end.queryByText(other, { exact: true })).toBeNull();
    },
  };
}

const askFor = (row: ReturnType<typeof session>) => ({
  ask: true,
  asks: [{ id: 'approval', harness: 'claude', session_id: row.sid, question: 'Approve?' }],
});

export const DirtyEndWithOpenRequest = endStory(
  dirty,
  'Ended with uncommitted work (2 changed entries)',
  askFor(dirty),
);
export const CleanEndWithOpenRequest = endStory(
  clean,
  'Ended with a clean working tree',
  askFor(clean),
);
export const EndWithNoBoardTimestamp = endStory(
  dirty,
  'Ended with uncommitted work (2 changed entries)',
  { generated: null },
  'The board has no timestamp to determine which sessions ended today.',
);
export const EndsUnobservable = endStory(working, 'Session ends are unobservable on this board.', {
  ends_observable: false,
});
export const NoEndsToday = endStory(working, 'No session ends were reported today.');

const completed = session('Release completed', 'idle', {
  ended_at: STAMP - 10,
  instruction: { label: 'asked', text: 'Archive the release', at: STAMP - 60 },
});
export const WorkingInstruction: Story = {
  args: { sessions: [working, completed] },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole('region', { name: 'Working on' }));
    await expect(card.getByText('Prepare the dashboard for review', { exact: true })).toBeVisible();
    await expect(
      card.getByText('From the latest instruction, 4 minutes ago.', { exact: true }),
    ).toBeVisible();
    await expect(card.queryByText('Archive the release', { exact: true })).toBeNull();
  },
};

export const LastRecordedInstruction: Story = {
  args: { sessions: [completed] },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole('region', { name: 'Working on' }));
    await expect(card.getByText('Archive the release', { exact: true })).toBeVisible();
    await expect(
      card.getByText('From an earlier instruction, 1 minute ago.', { exact: true }),
    ).toBeVisible();
    await expect(card.queryByText(/From the latest instruction/)).toBeNull();
  },
};

export const DuplicateAndUnlinkedSessions: Story = {
  args: {
    sessions: [
      waiting,
      { ...waiting, title: 'Duplicate report', state: 'working' },
      session('No session key', 'working', { sid: null }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText('2 sessions · 1 waiting on you · 1 working', { exact: true }),
    ).toBeVisible();
    const card = within(canvas.getByRole('region', { name: 'Sessions' }));
    await expect(card.getAllByRole('link')).toHaveLength(1);
    await expect(card.getByRole('link', { name: /Request approval/ })).toBeVisible();
    await expect(card.getByText('No session key', { exact: true })).toBeVisible();
    await expect(card.getByText('Session link unavailable', { exact: true })).toBeVisible();
    await expect(card.queryByText('Duplicate report', { exact: true })).toBeNull();
  },
};

export const MatchingTitles: Story = {
  args: {
    sessions: [
      session('Review output', 'working', { sid: 'key-A' }),
      session('Review output', 'working', { sid: 'key-B' }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(await canvas.findByRole('region', { name: 'Sessions' }));
    await expect(card.getByRole('link', { name: /Review output.*Session 1/ })).toHaveAttribute(
      'href',
      expect.stringContaining('key-A'),
    );
    await expect(card.getByRole('link', { name: /Review output.*Session 2/ })).toHaveAttribute(
      'href',
      expect.stringContaining('key-B'),
    );
    await userEvent.click(canvas.getByRole('button', { name: 'Show technical details' }));
    const picker = within(
      canvas.getByRole('combobox', { name: 'Session for the read-only terminal' }),
    );
    await expect(
      picker.getByRole('option', { name: 'Review output · Claude Code · Session 1' }),
    ).toHaveValue('session:["claude","key-A"]');
    await expect(
      picker.getByRole('option', { name: 'Review output · Claude Code · Session 2' }),
    ).toHaveValue('session:["claude","key-B"]');
  },
};

export const IdleThenWorking: Story = {
  args: { sessions: [{ ...working, sid: quiet.sid }], mixedTime: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(
      await canvas.findByRole('region', { name: 'Time agents worked on their own' }),
    );
    const observe = canvas.getByRole('button', { name: 'Record another observation' });
    await userEvent.click(observe);
    await expect(
      card.getByText('Waiting for enough recorded working time.', { exact: true }),
    ).toBeVisible();
    await userEvent.click(observe);
    await expect(await card.findByText('100%', { exact: true })).toBeVisible();
    await expect(
      card.getByText('Share of working or waiting time spent working without an open request.', {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      card.getByText('1 intervention inferred over 20 minutes of observation.', { exact: true }),
    ).toBeVisible();
    await expect(card.queryByText(/you stepped in/)).toBeNull();
  },
};

export const TimelineEvidence: Story = {
  args: { timeline: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('tab', { name: /Timeline/ }));
    const timeline = within(await canvas.findByRole('region', { name: 'Timeline' }));
    await waitFor(() => expect(timeline.getAllByText('EXACT STATE CHANGE').at(-1)).toBeVisible());
    await expect(
      timeline.queryAllByRole('button', { name: 'Evidence · source and confidence' }),
    ).toHaveLength(0);
    await expect(timeline.queryByText('s5', { exact: true })).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: 'Show technical details' }));
    await expect(timeline.getByText('s5', { exact: true })).toBeVisible();
    await expect(timeline.getAllByText('workflow state', { exact: true }).at(-1)).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Hide technical details' }));
    await expect(timeline.queryByText('s5', { exact: true })).toBeNull();
    await expect(timeline.getAllByText('EXACT STATE CHANGE').at(-1)).toBeVisible();
    await userEvent.click(canvas.getByRole('tab', { name: 'Overview' }));
    await expect(canvas.getByRole('region', { name: 'Overview' })).toBeVisible();
  },
};

export const DecisionsFilter: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('tab', { name: /Decisions/ }));
    const filters = within(canvas.getByRole('group', { name: 'Work activity filter' }));
    await expect(filters.getByRole('button', { name: 'Current work' })).toBeVisible();
    await expect(filters.queryByRole('button', { name: 'Active' })).toBeNull();
    await expect(canvas.getByRole('heading', { name: 'Recorded decisions' })).toBeVisible();
  },
};

export const UsageWithoutAReading: Story = {
  args: {
    sessions: [
      session('Request approval', 'needs_input', {
        blocked_since: STAMP - 60,
        resume_id: 'b2c3d4e5-1111-4222-8333-555500000002',
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('tab', { name: 'Usage and alerts' }));
    await expect(canvas.getByRole('heading', { name: 'Your AI allowance' })).toBeVisible();
    await expect(canvas.getByText('No plan usage has been reported yet.')).toBeVisible();
    await expect(canvas.getByRole('heading', { name: 'Waiting on you' })).toBeVisible();
    await expect(canvas.queryByRole('heading', { name: 'CAPACITY' })).toBeNull();
    const copy = canvas.getByRole('button', { name: 'Copy re-entry command' });
    await expect(copy).not.toHaveAttribute('title');
    await userEvent.click(copy);
    await waitFor(() =>
      expect(clipboard).toContain('claude --resume b2c3d4e5-1111-4222-8333-555500000002'),
    );
  },
};
