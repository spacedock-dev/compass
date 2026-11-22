import { within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { worthALookBoard } from '../../test/worthALookBoard';
import { mountShell } from '../shell/testing';
import { attentionSelectionFor } from './select';

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
