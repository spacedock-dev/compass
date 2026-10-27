import { describe, expect, it } from 'vitest';
import { datedClock } from '../observed/values';
import { mountDrift, textOf } from './testing';

const ROW = {
  constraint: 'TYPED GOAL',
  at: 960,
  clause: 'Ship the queue',
  reading: 'It stopped running the tests.',
  revision: 2,
  cutoff: 970,
  evidence: 'pytest failed',
};

describe('the departures section', () => {
  it('draws nothing for a session with no raise and no sentence about why', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    expect(document.querySelector('.next-cockpit-departures')).toBeNull();
    expect(page.state.requests.filter((r) => r.method !== 'GET')).toEqual([]);
  });

  it("keeps the lane's own sentence in view when it is on and nothing was raised", async () => {
    const page = mountDrift({
      payload: { unasked: true },
      session: { departures: [], departure_why: 'Not checked yet.', departure_checked: false },
    });
    await page.settle();
    await page.settle();
    const section = document.querySelector('.next-cockpit-departures') as HTMLElement;
    expect(section.querySelector(':scope > .next-cockpit-departure-part')).not.toBeNull();
    expect(textOf('.next-cockpit-departures > .next-cockpit-departure-part')).toContain(
      'Not checked yet.',
    );
    // Unmeasured is not zero: nothing was raised, and the lane never reached the session.
    expect(section.textContent).not.toContain('Raised while you were away: 0');
  });

  it('collapses the rows under their count, each against the intent it read, with the figures', async () => {
    const page = mountDrift({
      payload: {
        unasked: true,
        delivery_counts: { raises: 3, attempted: 3 },
      },
      session: {
        departures: [ROW, { ...ROW, revision: 0, constraint: 'EXPECTED OUTCOME · LINE 1' }],
        annotation_at: 1000,
        departure_checked: true,
        delivery_departure: {
          delivery_raises: 1,
          delivery_outcome: 'handed-over',
          delivery_why: 'A notification service accepted it.',
        },
      },
    });
    await page.settle();
    await page.settle();
    const section = document.querySelector('.next-cockpit-departures') as HTMLElement;
    expect(section.querySelector('[data-slot=accordion-trigger]')?.textContent).toBe(
      'Raised while you were away: 2',
    );
    const text = section.textContent ?? '';
    expect(text).toContain('2 departures were raised');
    expect(text).toContain('read against the intent as it stood then');
    expect(text).toContain('the intent it read is not on record');
    expect(text).toContain(
      `This raise was made at ${datedClock(960)} against an earlier version of your intent. You changed it at ${datedClock(1000)}, so it does not describe what you are asking for now.`,
    );
    expect(text).not.toMatch(/revision \d/i);
    expect(section.querySelector('[data-next-delivery="handed-over"]')?.textContent).toContain(
      'One notification was raised about this session',
    );
    // A figure the payload does not carry says so rather than reading zero: the reading nobody asked for
    // and the hand-over count the board never published.
    expect(textOf('.next-cockpit-departure-counts')).toContain('A notification service accepted');
    expect(
      [...document.querySelectorAll('.next-cockpit-count-value[data-next-absent]')].map(
        (node) => node.textContent,
      ),
    ).toEqual(['not published', 'not published']);
    expect(textOf('.next-cockpit-departure-counts')).toContain('From the reading you asked for');
  });

  it('says a raise is on record when the lane is off, and that nothing new is being checked', async () => {
    const page = mountDrift({
      payload: { unasked: false, unasked_off_reason: 'run-disabled' },
      session: { departures: [ROW] },
    });
    await page.settle();
    await page.settle();
    const text = textOf('.next-cockpit-departures');
    expect(text).toContain('The model off switch refuses unasked checks.');
    expect(text).toContain('What was already raised is still on record.');
  });
});
