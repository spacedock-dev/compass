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
