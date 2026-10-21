import { describe, expect, it } from 'vitest';
import { clock } from '../observed';
import { check, driftBoard, fact, mountDrift, textOf } from './testing';

/* A departure the next reading no longer finds is said once, on that reading: nothing else on the card says
   the earlier one ended, and a level that quietly changed from Medium to nothing read as a different session.
   The page remembers the earlier reading in this tab only, so a reading it never saw depart cannot clear. */
const CLEARED = '[data-next-drift-cleared]';
const FACTS = [
  fact('m1', 400, { type: 'agent_message', by: 'agent', summary: 'Done: the queue ships.' }),
  check('c1', 500, 'failed', { result_source: 'failed flag', summary: 'pytest -q' }),
];
const reading = (readAt: number, results: readonly string[]) => ({
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
  criteria: Object.fromEntries(
    results.map((result, index) => [
      index === 0 ? 'goal' : `line_${String(index)}`,
      {
        result,
        cites: result === 'departure' ? ['c1'] : [],
        detail: result === 'departure' ? 'It stopped running the tests.' : '',
        clause: 'Ship the queue',
      },
    ]),
  ),
});
const board = (readAt: number, results: readonly string[], count: number, generated: number) => ({
  ...driftBoard({
    session: {
      annotation_assessment: reading(readAt, results),
      annotation_window_start: 100,
      annotation_reading_count: count,
    },
  }),
  generated,
});
const DEPARTS = ['departure', 'not verifiable from available evidence'];
const NOTHING = [
  'not verifiable from available evidence',
  'not verifiable from available evidence',
];

describe('a departure the next reading clears', () => {
  it('is named once, on the reading that no longer finds it, and not on the one after', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1000, DEPARTS, 1, 1100));
    await page.settle();
    expect(textOf('.next-cockpit-result-headline')).toContain('Departs from your intent');
    expect(document.querySelector(CLEARED)).toBeNull();
    await page.poll(board(1200, NOTHING, 2, 1210));
    await page.settle();
    expect(textOf(CLEARED)).toBe(`The departure from the ${clock(1000)} reading no longer holds.`);
    // Said once: it is not on the reading after, and the departure's own card is gone with it.
    await page.poll(board(1300, NOTHING, 3, 1310));
    await page.settle();
    expect(document.querySelector(CLEARED)).toBeNull();
  });

  it('says how many cleared, and stays while the reading that cleared them stands', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1000, ['departure', 'departure'], 1, 1100));
    await page.settle();
    await page.poll(board(1200, NOTHING, 2, 1210));
    await page.settle();
    expect(textOf(CLEARED)).toBe(
      `The 2 departures from the ${clock(1000)} reading no longer hold.`,
    );
    await page.poll(board(1200, NOTHING, 2, 1220));
    await page.settle();
    expect(textOf(CLEARED)).toContain('no longer hold');
  });

  it('is not said where the earlier reading departs no more than the next, or never departed', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1000, NOTHING, 1, 1100));
    await page.poll(board(1200, NOTHING, 2, 1210));
    await page.settle();
    expect(document.querySelector(CLEARED)).toBeNull();
  });

  it('is not said when a departure remains', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1000, DEPARTS, 1, 1100));
    await page.poll(board(1200, DEPARTS, 2, 1210));
    await page.settle();
    expect(document.querySelector(CLEARED)).toBeNull();
  });

  it('is not said on a first sight of a reading with none, which the tab never saw depart', async () => {
    const page = mountDrift({ facts: FACTS, session: {} });
    await page.settle();
    await page.poll(board(1200, NOTHING, 2, 1210));
    await page.settle();
    expect(document.querySelector(CLEARED)).toBeNull();
  });
});
