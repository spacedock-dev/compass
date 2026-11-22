import { within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { worthALookBoard } from '../../test/worthALookBoard';
import { mountShell } from '../shell/testing';
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
  expect(canvas.queryByRole('button', { name: /Worth a look/ })).toBeNull();
  await page.settle();
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
  expect(within(row).getByText('Session ended with uncommitted work')).toBeVisible();
  expect(within(row).getByText('2 changed entries')).toBeVisible();
});
