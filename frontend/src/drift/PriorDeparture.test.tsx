import { describe, expect, it } from 'vitest';
import { clock } from '../observed';
import { check, driftBoard, fact, mountDrift, textOf } from './testing';

/* After a steer, the agent explained the departing edit and the next reading answered the line with that
   message alone. The store kept the earlier departure beside the reading (`annotation_prior_departures`), so
   the card lists it under the later reading and never tells the reader it no longer holds: the steer is not
   shown to have worked on the agent's word. A line a check answers lists nothing, and keeps the tab's own
   "no longer holds". */

const LINE = 'Leave the stylesheets alone';
const DETAIL = 'A stylesheet was written, which this line rules out.';
const FACTS = [
  fact('w1', 520, {
    type: 'tool_report',
    by: 'agent',
    subject: 'write',
    summary: 'src/styles/queue.css',
  }),
  fact('m1', 1050, {
    type: 'agent_message',
    by: 'agent',
    summary: 'The stylesheet edit was needed for the queue page, so I kept it.',
  }),
  check('c2', 1060, 'passed', { summary: 'pytest -q' }),
];
const UNSETTLED = { result: 'not verifiable from available evidence', cites: [], detail: '' };
const DEPARTED = {
  result: 'departure',
  cites: ['w1'],
  detail: DETAIL,
  clause: LINE,
  why: 'recorded-write',
};
const reading = (readAt: number, line2: Record<string, unknown>) => ({
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: readAt,
  evidence_through: readAt,
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
    goal: { ...UNSETTLED, clause: 'Ship the queue' },
    line_1: { ...UNSETTLED, clause: 'Tests pass' },
    line_2: { clause: LINE, detail: '', ...line2 },
  },
});
const PRIOR = [{ key: 'line_2', read_at: 1000, revision_read: 3, criterion: DEPARTED }];
const board = (
  readAt: number,
  line2: Record<string, unknown>,
  count: number,
  generated: number,
  prior: readonly unknown[] = [],
) => ({
  ...driftBoard({
    session: {
      annotation_assessment: reading(readAt, line2),
      annotation_window_start: 100,
      annotation_reading_count: count,
      annotation_prior_departures: prior,
    },
    store: { lines: ['Tests pass', LINE] },
  }),
  generated,
});
const ON_MESSAGE = { result: 'consistent with the evidence read', cites: ['m1'] };
const ON_CHECK = { result: 'consistent with the evidence read', cites: ['c2'] };
const PRIOR_GROUP = '[data-next-prior-departures]';
const CLEARED = '[data-next-drift-cleared]';
const LISTED = '[data-next-drift-prior-listed]';

describe('an earlier departure the agent’s word answered', () => {
  it('stays listed under the later reading, and is never said to no longer hold', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1000, DEPARTED, 1, 1100));
    await page.settle();
    expect(document.querySelector(PRIOR_GROUP)).toBeNull();
    await page.poll(board(1200, ON_MESSAGE, 2, 1210, PRIOR));
    await page.settle();
    const group = document.querySelector<HTMLElement>(PRIOR_GROUP);
    expect(group).not.toBeNull();
    const card = group?.querySelector<HTMLElement>('[data-next-prior-departure="line_2"]');
    expect(card?.querySelector('[data-next-departure-label]')?.textContent).toBe(
      'Earlier departure · Expected outcome 2',
    );
    expect(card?.textContent).toContain(DETAIL);
    expect(card?.querySelector('[data-next-cite="w1"]')).not.toBeNull();
    expect(textOf('[data-next-prior-departure-source]')).toMatch(
      new RegExp(
        `^From the ${clock(1000)} reading\\. The ${clock(1200)} reading rests this line on what the agent said at #\\d+, which is not a check\\.$`,
      ),
    );
    // Not among the standing departures, and the steer is not said to have worked.
    expect(document.querySelector('[data-next-departures]')).toBeNull();
    expect(document.querySelector(CLEARED)).toBeNull();
    expect(textOf(LISTED)).toBe(
      `The departure from the ${clock(1000)} reading is still listed below: the reading after it rests on what the agent said.`,
    );
  });

  it('is listed from the store on a reading this tab never saw depart', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1200, ON_MESSAGE, 2, 1210, PRIOR));
    await page.settle();
    expect(document.querySelector(PRIOR_GROUP)).not.toBeNull();
    expect(textOf(LISTED)).toContain('is still listed below');
  });

  it('is not listed where a check answers the line, which keeps saying the departure no longer holds', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1000, DEPARTED, 1, 1100));
    await page.settle();
    await page.poll(board(1200, ON_CHECK, 2, 1210, PRIOR));
    await page.settle();
    expect(document.querySelector(PRIOR_GROUP)).toBeNull();
    expect(document.querySelector(LISTED)).toBeNull();
    expect(textOf(CLEARED)).toBe(`The departure from the ${clock(1000)} reading no longer holds.`);
  });
});
