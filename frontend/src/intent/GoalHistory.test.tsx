import { fireEvent, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { intentLogView } from './logModel';
import { json, mountIntent } from './testing';

const generated = 2_000_000_000;
const session = { harness: 'claude', sid: 'one', project: 'app', title: 'Repair login' };
const untitled = { ...session, sid: 'two', title: 'Add examples' };
const board = { annotate: true, intent_revision: 'r1', generated, sessions: [session, untitled] };
const recent = { ...session, goal: 'Stabilize deployment', at: generated - 60 };
const older = {
  harness: 'codex',
  sid: 'older',
  title: 'Deploy the docs',
  goal: 'Prepare a release',
  goal_source: 'first-prompt',
  at: generated - 120,
};

it('searches both goal and title, shows an empty result, and opens the session to add a goal', async () => {
  const page = mountIntent({
    data: board,
    routes: {
      '/api/annotations': () => json({ annotations: [recent, older], intent_revision: 'r1' }),
    },
  });
  await page.settle();
  const search = screen.getByRole('searchbox', { name: 'Search goals' });
  fireEvent.input(search, { target: { value: 'deploy' } });
  expect(screen.getByText('Stabilize deployment')).toBeVisible();
  expect(screen.getByText('Prepare a release')).toBeVisible();
  expect(screen.queryByText('Add examples')).toBeNull();
  fireEvent.input(search, { target: { value: 'other' } });
  expect(screen.getByText('No goals or session titles match your search.')).toBeVisible();
  fireEvent.input(search, { target: { value: '' } });
  fireEvent.click(screen.getByRole('link', { name: 'Add a goal' }));
  expect(page.router.getRoute()).toMatchObject({ view: 'session', session: 'two', from: 'intent' });
  expect(page.posts()).toBe(0);
});

it.each([
  ['typed', recent, 'You wrote this', 'Saved 1 minute ago'],
  ['adopted', older, 'Taken from your first prompt', 'Saved 2 minutes ago'],
  [
    'discarded',
    { ...older, discarded: true, discarded_at: generated - 180 },
    'You discarded this goal',
    'Discarded 3 minutes ago',
  ],
])('names the source and time for a %s entry', (_, record, source, time) => {
  const view = intentLogView({ payload: board, board: [session], rows: [record], load: 'read' });
  const row = view.groups
    .flatMap((group) => group.rows)
    .find((item) => item.key.endsWith(record.sid));
  expect(row).toMatchObject({ source, time });
  if ('discarded' in record) expect(row?.goal).toBe('');
});
