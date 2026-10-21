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
const REASON = 'It stopped running the tests.';
const reading = (
  readAt: number,
  results: readonly string[],
  reason: string = REASON,
  cites: readonly string[] = ['c1'],
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
  criteria: Object.fromEntries(
    results.map((result, index) => [
      index === 0 ? 'goal' : `line_${String(index)}`,
      {
        result,
        cites: result === 'departure' ? cites : [],
        detail: result === 'departure' ? reason : '',
        clause: 'Ship the queue',
      },
    ]),
  ),
});
const board = (
  readAt: number,
  results: readonly string[],
  count: number,
  generated: number,
  reason?: string,
  cites?: readonly string[],
) => ({
  ...driftBoard({
    session: {
      annotation_assessment: reading(readAt, results, reason, cites),
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
    expect(textOf('[data-next-drift-verdict]')).toContain('1 departure');
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

/* A correction the reader pasted between the two readings is the steer the earlier departure was built into.
   The card names it, so the reader sees that the steer worked rather than a level that quietly changed. The
   server recognises the pasted correction as Compass's own words and marks it `copied`; a message the reader
   typed is no steer. */
const pasted = (at: number, id = 'paste') =>
  fact(id, at, {
    type: 'user_message',
    by: 'person:me',
    copied: true,
    summary: 'Back to my goal',
  });
const typed = (at: number) =>
  fact('typed', at, { type: 'user_message', by: 'person:me', summary: 'Also do the other thing' });

describe('a departure the steer named, cleared by the reading after it', () => {
  it('says the correction named it, when one was pasted between the two readings', async () => {
    const page = mountDrift({ facts: [...FACTS, pasted(1100)], session: {} });
    await page.settle();
    await page.poll(board(1000, DEPARTS, 1, 1090));
    await page.settle();
    await page.poll(board(1200, NOTHING, 2, 1210));
    await page.settle();
    expect(textOf(CLEARED)).toBe(
      `The departure your correction named, from the ${clock(1000)} reading, no longer holds.`,
    );
  });

  it('counts the departures the correction named', async () => {
    const page = mountDrift({ facts: [...FACTS, pasted(1100)], session: {} });
    await page.settle();
    await page.poll(board(1000, ['departure', 'departure'], 1, 1090));
    await page.settle();
    await page.poll(board(1200, NOTHING, 2, 1210));
    await page.settle();
    expect(textOf(CLEARED)).toBe(
      `The 2 departures your correction named, from the ${clock(1000)} reading, no longer hold.`,
    );
  });

  it('keeps the plain sentence when nothing was pasted between them, or only the reader typed', async () => {
    const page = mountDrift({
      facts: [...FACTS, pasted(900), typed(1100), pasted(1300)],
      session: {},
    });
    await page.settle();
    await page.poll(board(1000, DEPARTS, 1, 1090));
    await page.settle();
    await page.poll(board(1200, NOTHING, 2, 1210));
    await page.settle();
    expect(textOf(CLEARED)).toBe(`The departure from the ${clock(1000)} reading no longer holds.`);
  });
});

/* A steer can leave the reader's concern met and the reading still departing, on something else: the walk's
   second reading kept `1 departure` with a different reason, and nothing told the reader the first had been
   addressed. The earlier departure is the one a later departure on the same line and the same reason, or on
   an entry it cited before, still is; a model words one finding differently from reading to reading, so a
   reading with no correction between is never told it replaced anything. */
const ANOTHER = check('c2', 520, 'failed', { result_source: 'failed flag', summary: 'ruff check' });
const AGAIN = 'The coverage gate was held to 54 new exceptions.';
const second = (at: number) => pasted(at, 'paste-2');

describe('a departure the steer named, replaced by a different one', () => {
  it('is said gone while another departure stands, when a correction was pasted between', async () => {
    const page = mountDrift({ facts: [...FACTS, ANOTHER, pasted(1100)], session: {} });
    await page.settle();
    await page.poll(board(1000, DEPARTS, 1, 1090));
    await page.settle();
    await page.poll(board(1200, DEPARTS, 2, 1210, AGAIN, ['c2']));
    await page.settle();
    expect(textOf('[data-next-drift-verdict]')).toContain('1 departure');
    expect(textOf(CLEARED)).toBe(
      `The departure your correction named, from the ${clock(1000)} reading, no longer holds.`,
    );
  });

  it('is not said when the departure stands again, worded as before or resting on what it did', async () => {
    const page = mountDrift({ facts: [...FACTS, ANOTHER, pasted(1100)], session: {} });
    await page.settle();
    await page.poll(board(1000, DEPARTS, 1, 1090));
    await page.settle();
    await page.poll(board(1200, DEPARTS, 2, 1210));
    await page.settle();
    expect(document.querySelector(CLEARED)).toBeNull();
    await page.poll(board(1300, DEPARTS, 3, 1310, AGAIN, ['c1']));
    await page.settle();
    expect(document.querySelector(CLEARED)).toBeNull();
  });

  it('is not said of a reading no correction came between, whatever it found instead', async () => {
    const page = mountDrift({ facts: [...FACTS, ANOTHER, pasted(900), pasted(1300)], session: {} });
    await page.settle();
    await page.poll(board(1000, DEPARTS, 1, 1090));
    await page.settle();
    await page.poll(board(1200, DEPARTS, 2, 1210, AGAIN, ['c2']));
    await page.settle();
    expect(document.querySelector(CLEARED)).toBeNull();
  });

  it('counts only the departures that went, and says corrections when more than one was pasted', async () => {
    const page = mountDrift({
      facts: [...FACTS, ANOTHER, pasted(1100), second(1150)],
      session: {},
    });
    await page.settle();
    await page.poll(board(1000, ['departure', 'departure'], 1, 1090));
    await page.settle();
    // The goal's departure stands again; the line's is gone.
    const standing = board(1200, ['departure', 'not verifiable from available evidence'], 2, 1210);
    await page.poll(standing);
    await page.settle();
    expect(textOf(CLEARED)).toBe(
      `The departure your corrections named, from the ${clock(1000)} reading, no longer holds.`,
    );
  });
});
