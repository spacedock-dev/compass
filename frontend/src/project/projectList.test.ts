import { expect, it } from 'vitest';
import { projectList } from './projectList';

const TODAY = new Date(2026, 10, 23, 13).getTime() / 1000;

it.each([
  ['needs_input', undefined, 'Active today', 'Waiting on you', 'Do the work'],
  ['working', undefined, 'Active today', 'Working', 'Do the work'],
  ['idle', TODAY - 60, 'Active today', 'Ended', 'Do the work'],
  ['idle', TODAY - 86400, 'No recent activity', 'Ended', 'Do the work'],
  ['idle', undefined, 'No recent activity', 'State not published', 'Do the work'],
] as const)('groups %s with an observed end at %s', (state, end, group, label, headline) => {
  const [row] = projectList({
    generated: TODAY,
    sessions: [
      {
        project: 'work',
        harness: 'claude',
        sid: 'one',
        state,
        ...(end ? { ended_at: end } : {}),
        instruction: { label: 'asked', text: 'Do the work', at: TODAY - 120 },
      },
    ],
  });
  expect(row).toMatchObject({ group, state: label, headline });
});

it('sorts waiting before newer working projects and keeps the newest instruction', () => {
  const [first, second] = projectList({
    generated: TODAY,
    sessions: [
      { project: 'a', harness: 'codex', sid: 'work', state: 'working', last_activity: TODAY - 1 },
      {
        project: 'z',
        harness: 'claude',
        sid: 'wait',
        state: 'needs_input',
        last_activity: TODAY - 100,
      },
      {
        project: 'a',
        harness: 'claude',
        sid: 'older',
        state: 'working',
        instruction: { label: 'asked', text: 'First', at: TODAY - 90 },
      },
      {
        project: 'a',
        harness: 'claude',
        sid: 'newer',
        state: 'working',
        instruction: { label: 'asked', text: 'Latest', at: TODAY - 50 },
      },
    ],
  });
  expect(first?.key).toBe('z');
  expect(second).toMatchObject({ key: 'a', headline: 'Latest' });
});

it('keeps the working instruction when a more recent instruction belongs to an ended session', () => {
  const [row] = projectList({
    generated: TODAY,
    sessions: [
      {
        project: 'p',
        harness: 'claude',
        sid: 'work',
        state: 'working',
        instruction: { label: 'asked', text: 'Prepare the release', at: TODAY - 90 },
      },
      {
        project: 'p',
        harness: 'claude',
        sid: 'end',
        state: 'idle',
        ended_at: TODAY - 10,
        instruction: { label: 'asked', text: 'Archive the release', at: TODAY - 60 },
      },
    ],
  });
  expect(row).toMatchObject({ state: 'Working', headline: 'Prepare the release' });
});

it('counts an ended session with a pending request once on Projects', () => {
  const [row] = projectList({
    generated: TODAY,
    ask: true,
    asks: [{ id: 'ask', harness: 'claude', session_id: 'one', question: 'Approve?' }],
    sessions: [
      { project: 'p', harness: 'claude', sid: 'one', state: 'idle', ended_at: TODAY - 60 },
    ],
  });
  expect(row).toMatchObject({ sessions: 1, counts: [{ word: 'Waiting on you', count: 1 }] });
});

it('preserves each visibility limit in a project with a working session', () => {
  const [row] = projectList({
    generated: TODAY,
    sessions: [
      { project: 'p', harness: 'claude', sid: 'working', state: 'working' },
      { project: 'p', harness: 'codex', sid: 'unknown', state: 'idle' },
      { project: 'p', harness: 'claude', sid: 'scan', state: 'idle', acquisition: 'scan-only' },
    ],
  });
  expect(row).toMatchObject({
    state: 'Working',
    limits: expect.arrayContaining([
      'State not published',
      'Read by scanning: no turn end can be observed here',
    ]),
  });
});
