import { describe, expect, it, vi } from 'vitest';
import { clock } from '../observed';
import { datedClock } from '../observed/values';
import { check, driftBoard, fact, jumpTo, mountDrift, textOf } from './testing';

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
  fact('m0', 530, {
    type: 'agent_message',
    by: 'agent',
    summary: 'I also restyled the queue table in src/styles/queue.css.',
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
/* The shape the producer writes on this line: a folder rule would re-depart a reading resting on a recorded
   write, so the departure that can be cleared on the agent's word cites what the agent said it did. */
const SAID_DEPARTED = {
  result: 'departure',
  cites: ['m0'],
  detail: 'A stylesheet was edited.',
  clause: LINE,
  why: '',
};
const reading = (
  readAt: number,
  line2: Record<string, unknown>,
  criteria: Record<string, unknown> = {},
) => ({
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
    ...criteria,
  },
});
const PRIOR = [{ key: 'line_2', read_at: 1000, revision_read: 3, criterion: DEPARTED }];
const SAID_PRIOR = [{ key: 'line_2', read_at: 1000, revision_read: 3, criterion: SAID_DEPARTED }];
const board = (
  readAt: number,
  line2: Record<string, unknown>,
  count: number,
  generated: number,
  prior: readonly unknown[] = [],
  criteria: Record<string, unknown> = {},
  session: Record<string, unknown> = {},
) => ({
  ...driftBoard({
    session: {
      annotation_assessment: reading(readAt, line2, criteria),
      annotation_window_start: 100,
      annotation_reading_count: count,
      annotation_prior_departures: prior,
      ...session,
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

  it('is listed where it cites what the agent said, the departure the producer writes on this line', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1200, ON_MESSAGE, 2, 1210, SAID_PRIOR));
    await page.settle();
    const card = document.querySelector<HTMLElement>('[data-next-prior-departure="line_2"]');
    expect(card?.querySelector('[data-next-departure-label]')?.textContent).toBe(
      'Earlier departure · Expected outcome 2',
    );
    expect(card?.querySelector('[data-next-cite="m0"]')).not.toBeNull();
    expect(card?.textContent).toContain('A stylesheet was edited.');
  });

  it('is named "Earlier departure" to a screen reader as well as on the page', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1200, ON_MESSAGE, 2, 1210, SAID_PRIOR));
    await page.settle();
    const card = document.querySelector<HTMLElement>('[data-next-prior-departure="line_2"]');
    const name = (card?.getAttribute('aria-labelledby') ?? '')
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ');
    expect(name).toMatch(/^Earlier departure · Expected outcome 2 \S/);
  });

  it('marks its own cited entry when its citation is pressed, not the later reading’s', async () => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as never;
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1200, ON_MESSAGE, 2, 1210, SAID_PRIOR));
    await page.settle();
    await jumpTo(document.querySelector('[data-next-prior-departure] [data-next-cite="m0"]'));
    await page.settle();
    await page.settle();
    const ids = (selector: string) =>
      [...document.querySelectorAll<HTMLElement>(selector)].map((node) =>
        node.closest('[data-next-entry-id]')?.getAttribute('data-next-entry-id'),
      );
    expect(ids('[data-next-entry-id][data-next-cited]')).toEqual(['m0']);
    expect(ids('[data-next-finding-entry]')).toEqual(['m0']);
    expect(ids('[data-next-jump-back]')).toEqual(['m0']);
  });

  it('carries its date when the reading that found it was on another day', async () => {
    const later = 1000 + 2 * 86_400;
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    page.clock.advance(2 * 86_400 * 1000);
    await page.poll(board(later, ON_MESSAGE, 2, later + 10, SAID_PRIOR));
    await page.settle();
    const now = page.clock.now() / 1000;
    const earlier = datedClock(1000, now);
    expect(earlier).not.toBe(clock(1000));
    expect(textOf('[data-next-prior-departure-source]')).toMatch(
      new RegExp(`^From the ${earlier} reading\\. The ${clock(later)} reading rests this line`),
    );
    expect(textOf(LISTED)).toBe(
      `The departure from the ${earlier} reading is still listed below: the reading after it rests on what the agent said.`,
    );
  });

  it('is told apart from one that no longer holds when the same reading found both', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    const tests = {
      result: 'departure',
      cites: ['m0'],
      detail: 'No test ran.',
      clause: 'Tests pass',
    };
    await page.poll(board(1000, SAID_DEPARTED, 1, 1100, [], { line_1: tests }));
    await page.settle();
    const passed = { ...ON_CHECK, clause: 'Tests pass', detail: '' };
    const kept = [
      { key: 'line_1', read_at: 1000, revision_read: 3, criterion: { ...tests, why: '' } },
      ...SAID_PRIOR,
    ];
    await page.poll(board(1200, ON_MESSAGE, 2, 1210, kept, { line_1: passed }));
    await page.settle();
    expect(textOf(CLEARED)).toBe(`One departure from the ${clock(1000)} reading no longer holds.`);
    expect(textOf(LISTED)).toBe(
      `Another departure from the ${clock(1000)} reading is still listed below: the reading after it rests on what the agent said.`,
    );
  });

  it('is not set aside when the reader marks the later reading Not accurate', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(
      board(1200, ON_MESSAGE, 2, 1210, SAID_PRIOR, {}, { annotation_not_accurate: true }),
    );
    await page.settle();
    const card = document.querySelector<HTMLElement>('[data-next-prior-departure="line_2"]');
    expect(card).not.toBeNull();
    expect(card?.closest('[data-next-disowned]')).toBeNull();
    // The later reading's own rows are still the ones set aside.
    expect(
      document.querySelector('[data-next-result-quiet]')?.closest('[data-next-disowned]'),
    ).not.toBeNull();
  });

  it('says the later reading rests the goal, on the goal’s card', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    const goalDeparted = { ...SAID_DEPARTED, clause: 'Ship the queue' };
    const goalOnMessage = { ...ON_MESSAGE, clause: 'Ship the queue', detail: '' };
    await page.poll(
      board(
        1200,
        { ...UNSETTLED },
        2,
        1210,
        [{ key: 'goal', read_at: 1000, revision_read: 3, criterion: goalDeparted }],
        { goal: goalOnMessage },
      ),
    );
    await page.settle();
    expect(document.querySelector('[data-next-prior-departure="goal"]')).not.toBeNull();
    expect(textOf('[data-next-prior-departure-source]')).toMatch(
      new RegExp(
        `^From the ${clock(1000)} reading\\. The ${clock(1200)} reading rests the goal on what the agent said at #\\d+, which is not a check\\.$`,
      ),
    );
  });
});
