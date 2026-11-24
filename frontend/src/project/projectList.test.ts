import { expect, it } from 'vitest';
import { companionsLine, projectCompanions, projectList } from './projectList';

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

/* The Session page's Project card: this project's other sessions today, counted from the rows. */
const companionBoard = (others: readonly Record<string, unknown>[]) => ({
  generated: TODAY,
  sessions: [
    { project: 'acme/dashboard', harness: 'claude', sid: 'self', state: 'working' },
    { project: 'acme/other', harness: 'claude', sid: 'elsewhere', state: 'working' },
    ...others.map((fields, index) => ({
      project: 'acme/dashboard',
      harness: 'codex',
      sid: `other-${String(index)}`,
      ...fields,
    })),
  ],
});
const self = { project: 'acme/dashboard', harness: 'claude', sid: 'self' };

it.each([
  ['none', [], { today: 0, working: 0 }, ''],
  [
    'one working',
    [{ state: 'working' }],
    { today: 1, working: 1 },
    '1 other session today · 1 working',
  ],
  [
    'two, one working and one ended today',
    [{ state: 'working' }, { state: 'idle', ended_at: TODAY - 60 }],
    { today: 2, working: 1 },
    '2 other sessions today · 1 working',
  ],
  [
    'one waiting on you and none working',
    [{ state: 'needs_input' }],
    { today: 1, working: 0 },
    '1 other session today',
  ],
  [
    'only sessions outside today',
    [{ state: 'idle', ended_at: TODAY - 86400 }, { state: 'idle' }],
    { today: 0, working: 0 },
    '',
  ],
] as const)('counts %s beside this session', (_, others, counts, line) => {
  const found = projectCompanions(companionBoard(others), self);
  expect(found).toEqual(counts);
  expect(companionsLine(found)).toBe(line);
});

it('never counts the session the page is about, or another project', () => {
  const found = projectCompanions(companionBoard([]), self);
  expect(found.today).toBe(0);
  expect(companionsLine(null)).toBe('');
});
