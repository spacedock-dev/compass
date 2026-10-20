import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import { useEffect, useState } from 'react';
import { ShowMore } from '../src/drift/ShowMore';
import { EMPTY_RECORD } from '../src/store/board';
import { createShell } from '../src/shell/createShell';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

const meta = {
  title: 'Drift/Record pages',
  component: ShowMore,
  args: { onMore: () => undefined },
} satisfies Meta<typeof ShowMore>;
export default meta;
type Story = StoryObj<typeof meta>;
/* Full activity starts collapsed; a reader opens it before reading or paging the record. */
const openActivity = async (element: HTMLElement) => {
  const trigger = await within(element).findByRole('button', { name: 'Full activity' });
  if (trigger.getAttribute('aria-expanded') !== 'true') await userEvent.click(trigger);
};
const ready = { ...EMPTY_RECORD, status: 'loaded' as const, pages: 1, next: 'older' };
const pagingButton = async (element: HTMLElement) => {
  const button = within(element).getByRole('button', { name: 'Show 50 older entries' });
  await expect(button.tagName).toBe('BUTTON');
  await expect(button).toHaveTextContent('Show more');
  await expect(button.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
  await expect(button.getBoundingClientRect().width).toBeGreaterThanOrEqual(44);
};
export const Idle: Story = {
  args: { record: ready },
  play: async ({ canvasElement }) => pagingButton(canvasElement),
};
export const Loading: Story = {
  args: { record: { ...ready, status: 'loading' } },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole('button', { name: 'Reading older entries' });
    await expect(button).toHaveAttribute('aria-busy', 'true');
    await expect(button).toHaveAttribute('aria-disabled', 'true');
    await expect(button).toHaveTextContent('Reading older entries');
    await expect(button.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
  },
};
export const ReadError: Story = {
  args: { record: { ...ready, status: 'error', error: { kind: 'network-error' } } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('status')).toHaveTextContent(
      'Could not read older entries',
    );
    await pagingButton(canvasElement);
  },
};
export const BoundStop: Story = {
  args: { record: { ...ready, bound: 'bytes', scannedBytes: 16777216 } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText(
        'The read stopped after reading 16 MB without reaching 50 more entries; Show more continues from there.',
      ),
    ).toBeVisible();
    await pagingButton(canvasElement);
  },
};
export const ReachedStart: Story = {
  args: { record: { ...ready, reachedStart: true, next: null } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText('That is the start of the record.')).toBeVisible();
    await expect(canvas.queryByRole('button')).toBeNull();
  },
};
export const Unsupported: Story = {
  args: { record: { ...EMPTY_RECORD, status: 'unsupported' } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText('Older entries are not read for this harness.')).toBeVisible();
    await expect(canvas.queryByRole('button')).toBeNull();
  },
};
export const Restarted: Story = {
  args: { record: { ...ready, restarted: true } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('status')).toHaveTextContent(
      'The record changed. Started again from the newest entries.',
    );
    await pagingButton(canvasElement);
  },
};
export const WindowCovered: Story = {
  args: { record: ready, pastWindow: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Everything since your intent's window opened is listed."),
    ).toBeVisible();
    const boundary = canvas.getByText("Everything since your intent's window opened is listed.");
    await expect(boundary).toHaveAttribute('tabindex', '-1');
    boundary.focus({ preventScroll: true });
    await expect(document.activeElement).toBe(boundary);
    await expect(canvas.queryByRole('button')).toBeNull();
  },
};

/* A stored reading whose Goal cites an entry that sits on the older page (`e5`), so the first page holds
   nothing it can resolve it against. */
const ASSESSMENT = {
  revision_read: 1,
  revision_read_at: 1900000000 - 190,
  window_start: 1900000000 - 200,
  read_at: 1900000000 - 10,
  evidence_through: 1900000000 - 10,
  goal_source: 'typed',
  scope: 'last-turn',
  scope_text: 'Read up to its last turn.',
  stamp: 'model · m',
  cutoff: 'Evidence read to its end.',
  coverage: {
    tail_truncated: false,
    tail_start: null,
    unlisted: 0,
    unread_checks: 0,
    goal_source: 'typed',
  },
  criteria: {
    goal: {
      result: 'consistent with the evidence read',
      cites: ['e5'],
      detail: '',
      clause: 'Synthetic goal',
    },
  },
};

/* The server's fixed numbers: the newest page holds messages 51 to 100 and the older one 1 to 50, and the
   context holds a failed check that follows message 100 as 100.1. */
const orderedMessage = (n: number) => ({
  fact_id: `e${String(n)}`,
  at: 1900000000 - 100 + n,
  type: 'user_message',
  by: 'person:reader',
  source_session: { harness: 'claude', sid: 's1' },
  summary: `Synthetic entry ${String(n)}`,
  evidence: { source: 'transcript', confidence: 'exact' },
  ordinal: n,
});
const orderedCheck = {
  fact_id: 'check:npm test',
  at: 1900000000 + 1,
  type: 'tool_report',
  by: 'agent',
  source_session: { harness: 'claude', sid: 's1' },
  summary: 'npm test',
  result: 'failed',
  evidence: { source: 'transcript', confidence: 'exact' },
  ordinal: 100,
  ordinal_sub: 1,
};

function SessionRecordExample({
  intent = false,
  reading = false,
  ordinals = false,
}: {
  readonly intent?: boolean;
  readonly reading?: boolean;
  readonly ordinals?: boolean;
}) {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment('#n=session:demo:claude:s1');
    const clock = createFakeClock();
    const data = {
      generated: 1900000000,
      annotate: intent,
      sessions: [
        {
          harness: 'claude',
          sid: 's1',
          project: 'demo',
          project_key: '/demo',
          title: 'Synthetic record',
          state: 'idle',
          started_at: 1900000000 - 23 * 3600,
          ...(intent
            ? {
                annotation_goal: 'Synthetic goal',
                annotation_revision: 1,
                annotation_at: 1900000000 - 200,
                annotation_goal_saved_at: 1900000000 - 200,
                annotation_window_start: 1900000000 - 200,
              }
            : {}),
          ...(reading ? { annotation_reading_count: 1, annotation_assessment: ASSESSMENT } : {}),
        },
      ],
    };
    return createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) => {
        const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
        if (url.startsWith('/api/data')) return Promise.resolve(json(data));
        if (url === '/api/direction')
          return Promise.resolve(
            json({ ok: true, text: 'Synthetic older direction', clipped: false }),
          );
        if (ordinals && url.startsWith('/api/project-context'))
          return Promise.resolve(
            json({
              semantic: { facts: [orderedMessage(100), orderedMessage(99), orderedCheck] },
              sources: { work: { tool_reports: [] } },
            }),
          );
        if (ordinals && url.startsWith('/api/session-record')) {
          const older = url.includes('before=');
          return Promise.resolve(
            json({
              state: 'ok',
              session: { harness: 'claude', sid: 's1' },
              entries: Array.from({ length: 50 }, (_, i) => orderedMessage((older ? 50 : 100) - i)),
              next: older ? null : 'older',
              reached_start: older,
              bound: null,
              scanned_bytes: 65536,
              kinds: ['user_message', 'agent_message'],
            }),
          );
        }
        if (url.startsWith('/api/session-record')) {
          const older = url.includes('before=');
          return Promise.resolve(
            json({
              state: 'ok',
              session: { harness: 'claude', sid: 's1' },
              entries: Array.from({ length: 50 }, (_, i) => ({
                fact_id: `e${String((older ? 50 : 100) - i)}`,
                at: 1900000000 - (older ? 50 : 0) - i,
                type: 'user_message',
                by: 'person:reader',
                source_session: { harness: 'claude', sid: 's1' },
                summary: `Synthetic entry ${String((older ? 50 : 100) - i)}`,
                evidence: { source: 'transcript', confidence: 'exact' },
              })),
              next: 'older',
              reached_start: false,
              bound: null,
              scanned_bytes: 65536,
              kinds: ['user_message', 'agent_message'],
            }),
          );
        }
        return Promise.resolve(json({}));
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
export const ReaderAppendsOlderEntries: Story = {
  render: () => <SessionRecordExample />,
  play: async ({ canvasElement }) => {
    await openActivity(canvasElement);
    const canvas = within(canvasElement);
    const button = await canvas.findByRole('button', { name: 'Show 50 older entries' });
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(50),
    );
    button.focus({ preventScroll: true });
    window.scrollTo({
      top: button.getBoundingClientRect().top + window.scrollY - 200,
      behavior: 'instant',
    });
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
    const offset = window.scrollY;
    await userEvent.click(button);
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(100),
    );
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
    await expect(document.activeElement).toBe(button);
    await expect(window.scrollY).toBe(offset);
    await expect(canvas.getByText('Numbers count from the oldest entry loaded.')).toBeVisible();
    await expect(canvasElement.querySelector('[data-next-entry-id]')).toHaveAttribute(
      'data-next-entry',
      '100',
    );
    window.scrollTo({ top: 0, behavior: 'instant' });
  },
};

/* A number is the entry's place in the session, so loading older entries adds rows below and renumbers
   nothing: the same entry reads the same number before and after, and a check keeps the number of the
   message it follows. */
export const NumbersStayWhenOlderEntriesLoad: Story = {
  render: () => <SessionRecordExample intent ordinals />,
  play: async ({ canvasElement }) => {
    await openActivity(canvasElement);
    const canvas = within(canvasElement);
    const number = (id: string) =>
      canvasElement.querySelector(`[data-next-entry-id="${id}"]`)?.getAttribute('data-next-entry');
    const button = await canvas.findByRole('button', { name: 'Show 50 older entries' });
    await waitFor(() => expect(number('e100')).toBe('100'));
    await expect(number('e60')).toBe('60');
    await expect(number('check:npm test')).toBe('100.1');
    await expect(canvas.queryByText('Numbers count from the oldest entry loaded.')).toBeNull();
    await userEvent.click(button);
    await waitFor(() => expect(number('e50')).toBe('50'));
    await expect(number('e1')).toBe('1');
    await expect(number('e100')).toBe('100');
    await expect(number('e60')).toBe('60');
    await expect(number('check:npm test')).toBe('100.1');
    await expect(canvas.queryByText('Numbers count from the oldest entry loaded.')).toBeNull();
  },
};

export const OlderDirectionDraftSurvivesNavigation: Story = {
  render: () => <SessionRecordExample intent />,
  play: async ({ canvasElement }) => {
    await openActivity(canvasElement);
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Show 50 older entries' }));
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(100),
    );
    const row = canvasElement.querySelector('[data-next-entry-id="e50"]') as HTMLElement;
    await userEvent.click(within(row).getByRole('button', { name: 'Add to my intent' }));
    await expect(await canvas.findByDisplayValue('Synthetic older direction')).toBeVisible();
    // Primary links belong to browser hashchange; this isolated router owns its keyboard path.
    await userEvent.click(canvas.getByRole('heading', { name: 'Drift' }));
    await userEvent.keyboard('s');
    await userEvent.click(await canvas.findByRole('link', { name: /Synthetic record/ }));
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(50),
    );
    await expect(await canvas.findByDisplayValue('Synthetic older direction')).toBeVisible();
    await expect(canvasElement.querySelector('[data-next-entry-id="e50"]')).toBeNull();
  },
};

export const ReadingNamesEntriesItHasNotLoaded: Story = {
  render: () => <SessionRecordExample intent reading />,
  play: async ({ canvasElement }) => {
    await openActivity(canvasElement);
    const canvas = within(canvasElement);
    const note = await waitFor(() => {
      const found = canvasElement.querySelector('[data-next-unloaded]');
      if (!found) throw new Error('the reading has not said what it is missing yet');
      return found;
    });
    await expect(note).toHaveTextContent(
      'This reading cites an entry that is not listed. Show more, under the list, may load it.',
    );
    // The page loads nothing by itself: the entry arrives only when the reader asks.
    await expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(50);
    await userEvent.click(await canvas.findByRole('button', { name: 'Show 50 older entries' }));
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(100),
    );
    await waitFor(() => expect(canvasElement.querySelector('[data-next-unloaded]')).toBeNull());
  },
};

/* The entries a reading cites are found at a glance: pressing a cited entry's number tints each cited row,
   so it stands apart from the list around it. Read from the computed style, since a tint is only visible. */
export const CitedEntriesAreTinted: Story = {
  render: () => <SessionRecordExample intent reading />,
  play: async ({ canvasElement }) => {
    await openActivity(canvasElement);
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Show 50 older entries' }));
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(100),
    );
    const row = () => canvasElement.querySelector('[data-next-entry-id="e5"]') as HTMLElement;
    const background = (node: HTMLElement) => getComputedStyle(node).backgroundColor;
    await expect(row()).not.toHaveAttribute('data-next-cited');
    const plain = background(row());
    await userEvent.click(await canvas.findByRole('link', { name: /^Show #\d+/ }));
    await waitFor(() => expect(row()).toHaveAttribute('data-next-cited'));
    await expect(background(row())).not.toBe(plain);
    await expect(getComputedStyle(row()).borderLeftWidth).toBe('3px');
    // An entry nobody cited keeps the plain row.
    const other = canvasElement.querySelector('[data-next-entry-id="e60"]') as HTMLElement;
    await expect(other).not.toHaveAttribute('data-next-cited');
  },
};

/* A page left open while its session writes. The board's context reaches back over the newest 400 KB of the
   transcript only, so an entry that arrives after the page opened and then leaves that tail used to drop off
   the list, and every number above it moved. The page now reads the newest page again when the session's
   activity changes, so what it showed stays. */
interface GrowingWorld {
  messages: number;
  tail: number;
  activity: number;
  contextReads: number;
  shell: ReturnType<typeof createShell> | null;
  clock: ReturnType<typeof createFakeClock> | null;
}
const growing: GrowingWorld = {
  messages: 0,
  tail: 0,
  activity: 0,
  contextReads: 0,
  shell: null,
  clock: null,
};
const resetGrowing = () => {
  growing.messages = 10;
  growing.tail = 3;
  growing.activity = 0;
  growing.contextReads = 0;
};
const growingMessage = (n: number) => ({
  fact_id: `m${String(n)}`,
  at: 1900000000 - 1000 + n,
  type: 'agent_message',
  by: 'agent',
  source_session: { harness: 'claude', sid: 's1' },
  summary: `Synthetic message ${String(n)}`,
  evidence: { source: 'transcript', confidence: 'exact' },
});

function GrowingRecordExample() {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment('#n=session:demo:claude:s1');
    const clock = createFakeClock();
    const made = createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) => {
        const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
        const all = Array.from({ length: growing.messages }, (_, n) => growingMessage(n));
        if (url.startsWith('/api/data'))
          return Promise.resolve(
            json({
              generated: 1900000000 + growing.activity,
              annotate: true,
              sessions: [
                {
                  harness: 'claude',
                  sid: 's1',
                  project: 'demo',
                  project_key: '/demo',
                  title: 'Synthetic growing record',
                  state: 'working',
                  started_at: 1900000000 - 3600,
                  last_activity: 1900000000 + growing.activity,
                  annotation_goal: 'Synthetic goal',
                  annotation_revision: 1,
                  annotation_at: 1900000000 - 1100,
                  annotation_goal_saved_at: 1900000000 - 1100,
                  annotation_window_start: 1900000000 - 1100,
                },
              ],
            }),
          );
        if (url.startsWith('/api/session-record'))
          return Promise.resolve(
            json({
              state: 'ok',
              session: { harness: 'claude', sid: 's1' },
              entries: [...all].reverse(),
              next: null,
              reached_start: true,
              bound: null,
              scanned_bytes: 65536,
              kinds: ['user_message', 'agent_message'],
            }),
          );
        if (url.startsWith('/api/project-context')) {
          growing.contextReads += 1;
          return Promise.resolve(
            json({
              semantic: { facts: all.slice(-growing.tail) },
              sources: { work: { tool_reports: [] } },
            }),
          );
        }
        return Promise.resolve(json({}));
      },
    });
    growing.shell = made;
    growing.clock = clock;
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
export const OpenPageKeepsWhatItShowed: Story = {
  render: () => {
    resetGrowing();
    return <GrowingRecordExample />;
  },
  play: async ({ canvasElement }) => {
    const rows = () => canvasElement.querySelectorAll('[data-next-entry-id]');
    const numbers = () =>
      Object.fromEntries(
        [...rows()].map((row) => [
          row.getAttribute('data-next-entry-id'),
          row.getAttribute('data-next-entry'),
        ]),
      );
    const poll = async () => {
      const read = growing.shell?.runtime.refresh();
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      growing.clock?.advance(500);
      await read;
    };
    await waitFor(() => expect(rows()).toHaveLength(10));
    // Five messages arrive, all still inside the board's tail, so the list rises.
    growing.messages = 15;
    growing.tail = 5;
    growing.activity += 1;
    await poll();
    await waitFor(() => expect(rows()).toHaveLength(15));
    const shown = numbers();
    // Large tool output then pushes all but the newest message out of the tail. The page keeps them.
    growing.tail = 1;
    growing.activity += 1;
    const reads = growing.contextReads;
    await poll();
    await waitFor(() => expect(growing.contextReads).toBeGreaterThan(reads));
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
    await expect(rows()).toHaveLength(15);
    await expect(numbers()).toEqual(shown);
    await expect(shown['m12']).toBe('13');
  },
};
