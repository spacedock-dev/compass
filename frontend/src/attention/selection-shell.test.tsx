import { act, fireEvent, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import emptyBoard from '../../test/fixtures/client-contract/data-empty.json';
import unavailableBoard from '../../test/fixtures/client-contract/data-unavailable.json';
import { worthALookBoard } from '../../test/worthALookBoard';
import { mountShell } from '../shell/testing';
import { filterStoreFor } from '../sessions/filterStore';
import { attentionSelectionFor } from './select';

const { generated } = worthALookBoard();
const ended = {
  sid: 'last-turn',
  harness: 'claude',
  project: 'one',
  state: 'idle',
  ended_at: generated - 100,
};
const dirty = { ...ended, dirty: true, changed: 2 };

it('renders the selector’s exact set of flags and count in the real Sessions shell', async () => {
  const board = worthALookBoard();
  const repeated = board.sessions.find(({ sid }) => sid === 'dirty-end');
  if (!repeated) throw new Error('Missing dirty-end fixture');
  const data = { ...board, sessions: [...board.sessions, { ...repeated }] };
  const page = mountShell({ data });
  await page.settle();
  const selection = attentionSelectionFor(data);
  if (!selection) throw new Error('Board selection is absent');
  const flags = [...page.container.querySelectorAll('[data-next-row-worth-a-look]')];
  expect(
    flags.map((flag) => flag.closest('article')?.getAttribute('data-next-session')).sort(),
  ).toEqual([...selection.worthALook.keys()].map(({ sid }) => sid).sort());
  expect(flags).toHaveLength(9);
  expect(
    within(page.container).getByRole('button', { name: `Worth a look ${String(flags.length)}` }),
  ).toBeDefined();
});

it('shows a zero only after an empty session collection arrives', async () => {
  const page = mountShell({ data: { sessions: [] } });
  const canvas = within(page.container);
  expect(canvas.queryByRole('region', { name: 'At a glance' })).toBeNull();
  expect(canvas.queryByRole('button', { name: /Worth a look/ })).toBeNull();
  await page.settle();
  const glance = within(canvas.getByRole('region', { name: 'At a glance' }));
  expect(glance.getByRole('link', { name: /Waiting on you 0/ })).toBeVisible();
  expect(glance.getByRole('button', { name: /Working now 0/ })).toBeVisible();
  expect(glance.getByRole('link', { name: /Worth a look 0/ })).toBeVisible();
  expect(
    canvas.getByText('You have 0 waiting on you, 0 working, 0 quiet and 0 ended on this board.'),
  ).toBeVisible();
  expect(canvas.getByRole('button', { name: 'Worth a look 0' })).toBeDefined();
  expect(page.container.querySelector('[data-next-row-worth-a-look]')).toBeNull();
});

it('shows an unavailable count when every discovered source fails', async () => {
  const page = mountShell({
    data: { sessions: [], harnesses: [{ key: 'claude', discovered: true, error: 'Read failed' }] },
  });
  await page.settle();
  const canvas = within(page.container);
  const count = canvas.getByRole<HTMLButtonElement>('button', { name: 'Worth a look unavailable' });
  expect(count.disabled).toBe(true);
  expect(canvas.queryByRole('button', { name: 'Worth a look 0' })).toBeNull();
});

it.each([
  ['two dirty copies', [dirty, { ...dirty }]],
  ['an unmeasured copy first', [ended, dirty]],
  ['a measured copy first', [dirty, ended]],
  [
    'an active copy that would hide the end',
    [{ ...ended, ended_at: null, state: 'working' }, dirty],
  ],
])(
  'moves the duplicate dirty warning out of Now once per identity with %s',
  async (_, sessions) => {
    const page = mountShell({ data: { generated, sessions } });
    await page.settle();
    const flags = page.container.querySelectorAll('[data-next-row-worth-a-look]');
    expect(flags).toHaveLength(1);
    expect(flags[0]?.textContent).toContain('Ended with uncommitted work (2 changed entries)');
    expect(
      within(flags[0]?.closest('article') as HTMLElement).getByLabelText('Ended'),
    ).toBeDefined();
    expect(page.container.textContent).not.toContain('Session ended with uncommitted work');
  },
);

it('keeps an exact request and one dirty-end fact when the same session counts as a wait', async () => {
  const data = {
    generated,
    sessions: [dirty],
    ask: true,
    asks: [
      { id: 'end-request', session_id: dirty.sid, harness: dirty.harness, question: 'Approve?' },
    ],
  };
  const page = mountShell({ data });
  await page.settle();
  const row = page.container.querySelector<HTMLElement>('article[data-next-session="last-turn"]');
  if (!row) throw new Error('Expected the ended session row');
  expect(attentionSelectionFor(data)?.counts).toMatchObject({
    waitingOnYou: 1,
    worthALook: 0,
    badge: 1,
  });
  expect(within(row).getByText('Approve?')).toBeVisible();
  expect(within(row).getByLabelText('Ended')).toBeVisible();
  expect(
    row.querySelector('[data-next-row-worth-a-look], .next-operation-outcome--bad'),
  ).toBeNull();
  // The end and git facts are said once: the dirty end, then the one git fact it lacks.
  expect(within(row).getByText('Ended with uncommitted work · 2 changed entries')).toBeVisible();
});

it('counts the same rows in the cards, list segments and header', async () => {
  const board = worthALookBoard();
  const working = board.sessions.find(({ sid }) => sid === 'loop');
  const gate = board.sessions.find(({ sid }) => sid === 'gate');
  if (!working || !gate) throw new Error('Missing session fixtures');
  const page = mountShell({
    data: {
      ...board,
      sessions: [
        ...board.sessions,
        { ...working },
        { ...gate, sid: 'reported-block', title: 'reported-block' },
      ],
    },
  });
  await page.settle();
  const canvas = within(page.container);
  const glance = within(canvas.getByRole('region', { name: 'At a glance' }));
  expect(
    canvas.getByText('You have 3 waiting on you, 2 working, 9 quiet and 5 ended on this board.'),
  ).toBeVisible();
  expect(glance.getByRole('link', { name: /Waiting on you 3/ })).toBeVisible();
  expect(glance.getByRole('button', { name: /Working now 2/ })).toBeVisible();
  expect(glance.getByRole('link', { name: /Worth a look 9/ })).toBeVisible();
  expect(canvas.getByRole('link', { name: 'Needs you 12' })).toBeVisible();
  expect(canvas.getByRole('status', { name: 'Working sessions' }).textContent).toBe(
    '2 sessions working',
  );

  const filters = filterStoreFor(page.shell.controls);
  const visible = () =>
    [...page.container.querySelectorAll('article[data-next-session]')].map((row) =>
      row.getAttribute('data-next-session'),
    );
  for (const [segment, expected] of [
    ['waiting', ['gate', 'reported-block', 'request']],
    ['working', ['long-turn', 'loop']],
    [
      'worth',
      [
        'dirty-end',
        'dirty-unknown-count',
        'dirty-one-entry',
        'loop',
        'long-turn',
        'quiet-launch',
        'disagreement',
        'shared-one',
        'shared-two',
      ],
    ],
    ['ended', ['clean-end', 'dirty-end', 'dirty-one-entry', 'dirty-unknown-count', 'unknown-end']],
    [
      'quiet',
      [
        'dirty-stop',
        'quiet-launch',
        'disagreement',
        'shared-one',
        'shared-two',
        'drift-none',
        'drift-low',
        'drift-medium',
        'drift-high',
      ],
    ],
  ] as const) {
    await act(() => filters.set({ ...filters.get(), segment }));
    expect(visible().sort(), segment).toEqual([...expected].sort());
  }
  await act(() => filters.set({ ...filters.get(), segment: 'waiting' }));
  const row = canvas.getByRole('link', { name: 'Open session gate' }).closest('article');
  if (!row) throw new Error('Missing the native wait row');
  expect(within(row).getByRole('img', { name: 'Waiting on you' })).toBeVisible();
});

it('shows an ended session in both matching segments while its request remains answerable', async () => {
  const board = worthALookBoard();
  const page = mountShell({
    data: {
      ...board,
      sessions: board.sessions.filter(({ sid }) => sid === 'clean-end'),
      asks: [{ ...board.asks[0], session_id: 'clean-end', options: ['Yes', 'No'] }],
    },
  });
  await page.settle();
  const canvas = within(page.container);
  const glance = within(canvas.getByRole('region', { name: 'At a glance' }));
  expect(glance.getByRole('link', { name: /Waiting on you 1/ })).toBeVisible();
  expect(canvas.getByRole('link', { name: 'Needs you 1' })).toBeVisible();
  const tabs = within(canvas.getByRole('group', { name: 'Session status' }));
  for (const name of ['Waiting on you 1', 'Ended 1']) {
    fireEvent.click(tabs.getByRole('button', { name }));
    await page.settle();
    const row = canvas.getByRole('link', { name: 'Open session clean-end' }).closest('article');
    if (!row) throw new Error('Missing ended session');
    expect(within(row).getByRole('img', { name: 'Ended' })).toBeVisible();
  }
  await act(() => canvas.getByRole('link', { name: 'Open session clean-end' }).click());
  expect(canvas.getByText('Approve?', { selector: '.next-session-ask-question' })).toBeVisible();
  expect(canvas.getByRole('button', { name: 'Yes' }).hasAttribute('disabled')).toBe(false);
  expect(canvas.getByRole('button', { name: 'No' }).hasAttribute('disabled')).toBe(false);
});

it('distinguishes an empty, a partially unreadable and an unclassified board at the opening', async () => {
  const empty = mountShell({ data: emptyBoard.response.body });
  await empty.settle();
  expect(within(empty.container).getByText(/0 ended on this board/)).toBeVisible();
  empty.unmount();

  const partial = mountShell({ data: unavailableBoard.response.body });
  await partial.settle();
  const partialCanvas = within(partial.container);
  expect(
    partialCanvas.getByText(/among the sessions Compass could read, with some sources unavailable/),
  ).toBeVisible();
  expect(
    within(partialCanvas.getByRole('region', { name: 'At a glance' })).getByRole('link', {
      name: /Waiting on you 0/,
    }),
  ).toBeVisible();
  partial.unmount();

  const unclassified = mountShell({
    data: {
      sessions: [
        { harness: 'claude', sid: 'scan', state: 'idle', acquisition: 'scan-only' },
        { harness: 'claude', sid: 'unknown' },
        {
          harness: 'claude',
          sid: 'child',
          state: 'working',
          waiting_on_child: true,
          declared_children: [{ harness: 'claude', sid: 'helper' }],
        },
      ],
    },
  });
  await unclassified.settle();
  expect(
    within(unclassified.container).getByText(/and 3 with limited state evidence on this board/),
  ).toBeVisible();
});
