import { describe, expect, it } from 'vitest';
import { GLOSSARY } from '../language/glossary';
import { observe, type Row } from '../observed';
import { buildSessionsScreen, noGoalYet, sessionsContext } from './rows';

/* Which absence word a Sessions row may draw, and when it must draw none. Every fixture is invented. */

const NOW = 5000;
const ROUTES = { claude: { reason: '' }, codex: { reason: '' }, pi: { reason: '' } };
const reading = {
  revision_read: 1,
  read_at: NOW - 60,
  scope: 'last-turn',
  criteria: { goal: { result: 'consistent with the evidence read', cites: [], detail: '' } },
};

function rowFor(fields: Row, metadata: Row = {}) {
  const payload: Row = {
    generated: NOW,
    annotate: true,
    reading_routes: ROUTES,
    sessions: [{ harness: 'claude', sid: 'acme', project: 'acme', state: 'idle', ...fields }],
    ...metadata,
  };
  const screen = buildSessionsScreen(payload, observe(payload));
  const row = [...screen.active, ...screen.history][0];
  if (!row) throw new Error('Missing row');
  return { row, context: sessionsContext(payload) };
}

const absent = { annotation_goal: '', annotation_goal_why: 'No goal typed for this session.' };
const draft = { first_prompt: 'Write the acme summary', first_prompt_at: NOW - 60 };
const saved = { annotation_goal: 'Ship the acme release', annotation_revision: 1 };

describe('the row absence word', () => {
  it.each([
    ['a saved goal that was never checked', saved, 'notCheckedYet'],
    [
      'saved lines and no goal, never checked',
      { ...absent, annotation_line_1: 'A summary exists' },
      'notCheckedYet',
    ],
    ['a Pi row with a saved goal', { harness: 'pi', ...saved }, 'notCheckedYet'],
    // A check adopts the draft first, so a draft is a goal that has yet to be checked.
    ['a draft goal that was never saved', { ...absent, ...draft }, 'notCheckedYet'],
    [
      'a discarded goal with a draft',
      { annotation_goal: '', annotation_discarded_at: NOW - 5, ...draft },
      'notCheckedYet',
    ],
  ])('names %s', (_name, fields, word) => {
    expect(rowFor(fields).row.absence).toBe(word);
  });

  it.each([
    ['no goal and no draft (the Goal cell says it, once)', absent],
    [
      'a prompt with no time, which the page drafts nothing from',
      { ...absent, first_prompt: 'Write the acme summary' },
    ],
    [
      'a session that opened with a harness control',
      { ...absent, ...draft, first_prompt_control: true },
    ],
    ['a draft whose harness has been checked', { ...absent, ...draft, departure_checked: true }],
    ['a Codex row with a goal', { harness: 'codex', ...saved }],
    [
      'a Codex row with a draft',
      { harness: 'codex', ...absent, ...draft, prompt_states_work: true },
    ],
    [
      'a stored departure',
      {
        ...saved,
        annotation_assessment: {
          ...reading,
          criteria: { goal: { result: 'departure', cites: ['f1'], detail: '' } },
        },
      },
    ],
    ['a stored reading that does not depart', { ...saved, annotation_assessment: reading }],
    ['a refused reading', { ...saved, annotation_reading_refused: true }],
    ['a withheld reading', { ...saved, annotation_reading_withheld: 'idle-unknown' }],
    ['a press that left no reading', { ...saved, annotation_reading_count: 1 }],
    ['an unasked check that found nothing', { ...saved, departure_checked: true }],
    ['a raised departure', { ...saved, departures: [{ at: NOW - 1, revision: 1 }] }],
    [
      'an unreadable entry',
      { ...absent, ...draft, annotation_goal_why: '', annotation_goal_unreadable: true },
    ],
    ['a draft over an unreadable entry', { ...saved, annotation_goal_unreadable: true }],
  ])('draws nothing for %s', (_name, fields) => {
    expect(rowFor(fields).row.absence).toBeNull();
  });

  it('draws nothing where the harness has no reading route', () => {
    expect(rowFor(saved, { reading_routes: { codex: {} } }).row.absence).toBeNull();
    expect(
      rowFor({ ...absent, ...draft }, { reading_routes: { codex: {} } }).row.absence,
    ).toBeNull();
    expect(rowFor(saved, { reading_routes: undefined }).row.absence).toBeNull();
  });

  it('draws nothing while annotations are off or the store cannot be read', () => {
    expect(rowFor(saved, { annotate: false }).row.absence).toBeNull();
    expect(rowFor({ ...absent, ...draft }, { annotate: false }).row.absence).toBeNull();
    for (const fields of [saved, { ...absent, ...draft }])
      expect(
        rowFor(fields, { annotate_unreadable: 'The store cannot be read' }).row.absence,
      ).toBeNull();
  });
});

describe('a row with saved outcome lines and no goal', () => {
  it('shows the expected outcome in the Goal cell and never No goal yet', () => {
    const { row } = rowFor({ ...absent, annotation_line_2: 'Done when it ships' });
    expect(row.goal).toMatchObject({
      label: GLOSSARY.doneLooksLike.plain,
      kind: 'link',
      text: 'Done when it ships',
      known: true,
    });
    expect(row.absence).toBe('notCheckedYet');
  });

  it('prefers a draft the page would offer, as before', () => {
    const { row } = rowFor({ ...absent, ...draft, annotation_line_1: 'Done when it ships' });
    expect(row.goal.label).toBe('Goal · your first prompt');
  });
});

describe('the Goal cell when the saved goal cannot be read', () => {
  it.each([
    ['the store', {}, { annotate_unreadable: 'The store cannot be read' }],
    ['this session entry', { annotation_goal_unreadable: true }, {}],
  ])(
    'says it is unavailable for %s, and never No goal yet or a prompt',
    (_name, fields, metadata) => {
      for (const row of [{ ...absent, ...draft }, { ...absent, harness: 'claude' }, saved]) {
        const { goal } = rowFor({ ...row, ...fields }, metadata).row;
        expect(goal).toMatchObject({ kind: 'off', text: 'Saved goal unavailable', known: false });
      }
    },
  );

  it('keeps Annotations off for a board with annotations off', () => {
    expect(rowFor(saved, { annotate: false }).row.goal.text).toBe('Annotations off');
  });
});

describe('noGoalYet, the one predicate the Goal cell word and both filter chips share', () => {
  it.each([
    ['never typed', absent, true],
    ['discarded', { annotation_goal: '', annotation_discarded_at: NOW - 5 }, true],
    [
      'lines only, with no prompt to show',
      { ...absent, annotation_line_2: 'Done when it ships' },
      false,
    ],
    ['a draft only (the cell shows the prompt)', { ...absent, ...draft }, false],
    ['saved', saved, false],
    ['unpublished', {}, false],
    [
      'unreadable entry',
      { ...absent, annotation_goal_why: '', annotation_goal_unreadable: true },
      false,
    ],
  ])('%s', (_name, fields, expected) => {
    const { row, context } = rowFor(fields);
    const source = { harness: 'claude', sid: 'acme', ...fields };
    expect(noGoalYet(source, context, row.goal)).toBe(expected);
  });

  it('is false for every row once the store cannot be read or annotations are off', () => {
    const base = sessionsContext({ annotate: true });
    const none = { label: 'Goal', kind: 'none', text: 'No goal yet', known: false } as const;
    expect(noGoalYet(absent, { ...base, unreadable: 'The store cannot be read' }, none)).toBe(
      false,
    );
    expect(noGoalYet(absent, { ...base, annotate: false }, none)).toBe(false);
  });

  it('draws no row absence for a row whose only word is the Goal cell No goal yet', () => {
    expect(rowFor(absent).row.absence).toBeNull();
  });
});
