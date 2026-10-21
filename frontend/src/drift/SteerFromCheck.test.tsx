import { describe, expect, it } from 'vitest';
import { datedClock } from '../observed/values';
import { byAction, check, fact, json, mountDrift, textOf } from './testing';
import { STEER_OFF_MARKED, STEER_OFF_OLDER } from './sentences';
import { readerTimeZone, readerUtcOffset } from './correction';

/* Owner, 2026-10-20: Steer back stays beside the departures it steers from, labelled with the check's time,
   including while a later direction stands; and where the rules withhold it, the departures say why. */

const ASSESSMENT = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'last-turn',
  criteria: {
    goal: { result: 'departure', cites: ['c1'], detail: 'It stopped.', clause: 'Ship the queue' },
  },
};
const FACTS = [check('c1', 500, 'failed', { result_source: 'failed flag' })];
const session = { annotation_assessment: ASSESSMENT, annotation_window_start: 100 };
/* A departure cited at the agent's own message, so no failed check offers Steer back on its own. */
const SAID = [fact('m1', 600, { type: 'agent_message', by: 'agent' })];
const saidSession = {
  annotation_assessment: {
    ...ASSESSMENT,
    criteria: {
      goal: { result: 'departure', cites: ['m1'], detail: 'It stopped.', clause: 'Ship the queue' },
    },
  },
  annotation_window_start: 100,
};

function mount(extra: Record<string, unknown> = {}) {
  return mountDrift({
    session,
    facts: FACTS,
    routes: { '/api/correction': () => json({ ok: true, parts: ['Back to my goal.'] }) },
    ...extra,
  });
}

describe('Steer back from a check', () => {
  it('names the reading the correction is built from, in the reader’s own clock', async () => {
    const page = mount();
    await page.settle();
    await page.settle();
    expect(byAction('steer-back')).not.toBeNull();
    (byAction('steer-back') as HTMLElement).click();
    await page.settle();
    // The page's own clock says the reading was today, so the hours stand alone (`datedClock` below for a date).
    expect(textOf('[data-next-steer-from]')).toBe(
      `Built from your saved intent and the reading at ${datedClock(1000, 1000)}`,
    );
    expect(document.querySelector('[data-next-steer-off]')).toBeNull();
  });

  it('stays beside the departures while a later direction stands, secondary to the question', async () => {
    const page = mount({ facts: [...FACTS, fact('d2', 1005)] });
    await page.settle();
    await page.settle();
    const steer = document.querySelector(
      '[data-next-result-steer] [data-next-cockpit-action="steer-back"]',
    );
    expect(steer).not.toBeNull();
    expect(steer?.getAttribute('data-variant')).not.toBe('primary');
    expect(document.querySelector('[data-next-steer-section] h3')?.textContent).toBe('Steer back');
    expect(
      document.querySelector('[data-next-result-steer] [data-next-cockpit-action="update-intent"]'),
    ).toBeNull();
  });

  it('says why beside the departures when the analysis was marked inaccurate', async () => {
    const page = mount({ session: { ...saidSession, annotation_not_accurate: true }, facts: SAID });
    await page.settle();
    await page.settle();
    expect(document.querySelector('[data-next-departures]')).not.toBeNull();
    expect(byAction('steer-back')).toBeNull();
    expect(textOf('[data-next-steer-off]')).toBe(STEER_OFF_MARKED);
  });

  it('says why beside the departures when the analysis read an earlier version of the intent', async () => {
    const page = mount({ session: saidSession, store: { revision: 4 }, facts: SAID });
    await page.settle();
    await page.settle();
    expect(byAction('steer-back')).toBeNull();
    expect(textOf('[data-next-steer-off]')).toBe(STEER_OFF_OLDER);
  });

  it('sends the reader’s zone with the composition request', async () => {
    const page = mount();
    await page.settle();
    await page.settle();
    (byAction('steer-back') as HTMLElement).click();
    await page.settle();
    const sent = page.state.requests.find((r) => r.path === '/api/correction');
    expect(sent?.body).toMatchObject({
      utc_offset_minutes: readerUtcOffset(),
      time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
  });
});

describe('the reader’s zone', () => {
  it('is minutes east of UTC and never negative zero', () => {
    expect(readerUtcOffset({ getTimezoneOffset: () => -480 } as Date)).toBe(480);
    expect(readerUtcOffset({ getTimezoneOffset: () => 300 } as Date)).toBe(-300);
    expect(Object.is(readerUtcOffset({ getTimezoneOffset: () => 0 } as Date), 0)).toBe(true);
  });

  it('names the zone where the browser does, and nothing where it cannot', () => {
    expect(readerTimeZone(() => 'Europe/Berlin')).toBe('Europe/Berlin');
    expect(readerTimeZone(() => '')).toBeUndefined();
    expect(readerTimeZone(() => undefined)).toBeUndefined();
    expect(
      readerTimeZone(() => {
        throw new Error('no Intl');
      }),
    ).toBeUndefined();
  });
});

describe('a dated clock', () => {
  it('is the hours alone today and leads with the date on any other day', () => {
    const now = new Date(2026, 9, 20, 15, 0).getTime() / 1000;
    expect(datedClock(new Date(2026, 9, 20, 9, 5).getTime() / 1000, now)).toBe('09:05');
    expect(datedClock(new Date(2026, 9, 19, 23, 59).getTime() / 1000, now)).toBe(
      '2026-10-19 23:59',
    );
    expect(datedClock(new Date(2025, 0, 2, 7, 1).getTime() / 1000, now)).toBe('2025-01-02 07:01');
  });
});
