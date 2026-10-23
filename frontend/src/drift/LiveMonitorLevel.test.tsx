import { act } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { liveMonitorFor } from '../intent/liveMonitor';
import { monitorLease } from '../intent/panel.testing';
import { check, contextRoute, fact, LEASE_ROUTE, mountDrift } from './testing';

/* The level a Haiku check earned replaces the checks-and-paths estimate in the card and the header pill,
   labelled as the monitor's; an Analyze reading outranks it; and the estimate shows whenever the monitor
   has no level, because no check has completed, or the lease is off. */

/* The server's clock orders its states: the context's is later than the answer to the page's own start. */
const LATER = 5000;
const FACTS = [
  fact('u1', 400, { summary: 'Ship the queue' }),
  check('c1', 500, 'passed', { summary: 'pytest -q' }),
];
const FAILED = [
  fact('u1', 400, { summary: 'Ship the queue' }),
  check('c1', 500, 'failed', { result_source: 'failed flag', summary: 'pytest -q' }),
];
const ESTIMATE = (level: string) => ({
  harness: 'claude',
  sid: 's1',
  revision: 3,
  computed_at: 990,
  level,
  reasons: ['pass-then-write'],
  cites: [],
});
const MONITOR = (level: string, over: Record<string, unknown> = {}) => ({
  level,
  model_level: level,
  floor_applied: false,
  reason: 'The latest turns wrote outside the saved folders.',
  cites: [{ number: 1, fact_id: 'c1' }],
  fallback: 'medium',
  source: 'Live monitor · Haiku',
  checked_at: 1090,
  ...over,
});
const READING = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
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
    goal: {
      result: 'departure',
      cites: ['c1'],
      detail: 'It stopped running the tests.',
      clause: 'Ship the queue',
    },
  },
};
const ANALYSIS = (level: string) => ({
  harness: 'claude',
  sid: 's1',
  revision_read: 3,
  read_at: 1000,
  computed_at: 1000,
  level,
  reasons: [],
  cites: [],
});

async function open(options: {
  readonly work: Record<string, unknown>;
  readonly reading?: boolean;
  readonly facts?: typeof FACTS;
  readonly on?: boolean;
}) {
  const page = mountDrift({
    session: options.reading
      ? {
          annotation_assessment: READING,
          annotation_window_start: 100,
          annotation_reading_count: 1,
        }
      : {},
    facts: options.facts ?? FACTS,
    routes: {
      '/api/project-context': contextRoute(options.facts ?? FACTS, options.work),
      '/api/live-monitor': LEASE_ROUTE,
    },
  });
  await page.settle();
  if (options.on ?? true) {
    await act(async () => {
      liveMonitorFor(page.shell).update('claude:s1', { wanted: true });
    });
  }
  await page.settle();
  return page;
}

const pill = () => document.querySelector('[data-next-drift-pill] strong')?.textContent ?? null;
const source = () =>
  document.querySelector('[data-next-drift-level] .next-session-drift-source')?.textContent ?? '';
const detail = () =>
  document.querySelector('[data-next-drift-level] .next-session-drift-detail')?.textContent ?? '';

describe('the level the monitor draws', () => {
  it('shows the monitor’s level in the pill and the card, labelled Live monitor · Haiku', async () => {
    await open({
      work: {
        live_levels: [ESTIMATE('none_or_low')],
        live_monitor: monitorLease({ level: MONITOR('high'), now: LATER }),
      },
    });
    expect(pill()).toBe('High');
    expect(source()).toMatch(/^Live monitor · Haiku/);
    expect(detail()).toMatch(/Haiku check of the latest turns/);
    expect(detail()).not.toMatch(/Reads checks and file paths/);
    expect(document.querySelector('[data-next-live-reason-line]')?.textContent).toBe(
      'The latest turns wrote outside the saved folders.',
    );
  });

  it('shows the estimate, labelled as the estimate, while no check has completed', async () => {
    await open({
      work: {
        live_levels: [ESTIMATE('medium')],
        live_monitor: monitorLease({ level: null, now: LATER }),
      },
    });
    expect(pill()).toBe('Medium');
    expect(source()).toMatch(/^Live estimate/);
    expect(detail()).toMatch(/Reads checks and file paths/);
    expect(document.querySelector('[data-next-live-reason-line]')).toBeNull();
  });

  it('turns the switch off, and draws nothing live, when the server says the lease is off', async () => {
    await open({
      work: {
        live_levels: [ESTIMATE('medium')],
        live_monitor: monitorLease({ on: false, level: MONITOR('extreme'), now: LATER }),
      },
    });
    expect(pill()).toBeNull();
    expect(document.querySelector('[data-next-drift-level]')).toBeNull();
  });

  it('shows nothing live while the switch is off, whatever the server holds', async () => {
    await open({
      on: false,
      work: {
        live_levels: [ESTIMATE('medium')],
        live_monitor: monitorLease({ level: MONITOR('high'), now: LATER }),
      },
    });
    expect(pill()).toBeNull();
    expect(document.querySelector('[data-next-drift-level]')).toBeNull();
  });

  it('is outranked by an analysis reading, which keeps the pill and the card', async () => {
    await open({
      reading: true,
      facts: FAILED,
      work: {
        live_levels: [ESTIMATE('none_or_low')],
        analysis_levels: [ANALYSIS('medium')],
        live_monitor: monitorLease({ level: MONITOR('extreme'), now: LATER }),
      },
    });
    expect(pill()).toBe('Medium');
    expect(source()).not.toMatch(/Live monitor/);
  });

  it('keeps Not enough recorded yet off the pill, as for the estimate', async () => {
    await open({
      work: {
        live_levels: [ESTIMATE('none_or_low')],
        live_monitor: monitorLease({ level: MONITOR('not_enough'), now: LATER }),
      },
    });
    expect(pill()).toBeNull();
  });
});
