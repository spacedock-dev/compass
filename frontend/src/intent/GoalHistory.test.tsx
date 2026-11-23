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
  goal: 'Prepare a release',
  goal_source: 'first-prompt',
  at: generated - 120,
};

it.each(['off', 'error', 'damaged'])(
  'explains a no-match search with the %s store notice',
  async (state) => {
    const unreadable =
      'Compass could not read compass-annotations.json, so nothing will be saved over it.';
    const page = mountIntent({
      data: {
        ...board,
        annotate: state !== 'off',
        annotate_unreadable: state === 'damaged' ? unreadable : null,
      },
      routes: {
        '/api/annotations': () =>
          json({ annotations: [], intent_revision: 'r1' }, state === 'error' ? 500 : 200),
      },
    });
    await page.settle();
    expect(screen.queryByRole('link', { name: 'Add a goal' })).toBeNull();
    if (state === 'damaged') expect(screen.getByText(unreadable)).toBeVisible();
    expect(screen.getByText('Repair login')).toBeVisible();
    fireEvent.input(screen.getByRole('searchbox', { name: 'Search goals' }), {
      target: { value: 'no-such-goal' },
    });
    expect(screen.queryByText('Repair login')).toBeNull();
    expect(screen.getByText('No goals or session titles match your search.')).toBeVisible();
  },
);

it('keeps each directly published goal searchable and shows the binding caveat', async () => {
  const binding = 'Another session sharing this identity prefix would share these words.';
  const tracked = {
    ...session,
    session_goal: { text: 'Check logs', at: generated - 60 },
    cached_deterministic_goal: { goal: 'Restore checks', observed_at: generated - 90 },
    spacedock: {
      workflows: [
        { workflow: 'Docs', goal: 'Draft the manual' },
        { workflow: 'Tests', goal: 'Verify the API' },
      ],
    },
  };
  const page = mountIntent({
    data: { ...board, sessions: [tracked, untitled] },
    routes: {
      '/api/annotations': () =>
        json({
          annotations: [{ ...recent, binding_why: binding }],
          intent_revision: 'r1',
        }),
    },
  });
  await page.settle();
  expect(screen.getByText(binding)).toBeVisible();
  const search = screen.getByRole('searchbox', { name: 'Search goals' });
  for (const words of [
    'Stabilize deployment',
    'Check logs',
    'Restore checks',
    'Draft the manual',
    'Verify the API',
  ]) {
    fireEvent.input(search, { target: { value: words } });
    expect(screen.getByText(words)).toBeVisible();
    expect(screen.queryByText('Add examples')).toBeNull();
  }
});

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
  expect(screen.queryByText('Add examples')).toBeNull();
  fireEvent.input(search, { target: { value: 'repair login' } });
  expect(screen.getByText('Stabilize deployment')).toBeVisible();
  fireEvent.input(search, { target: { value: 'prepare a release' } });
  expect(screen.getByText('Prepare a release')).toBeVisible();
  expect(screen.getByText('Session title unavailable.')).toBeVisible();
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
