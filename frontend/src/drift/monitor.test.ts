import { describe, expect, it } from 'vitest';
import {
  END_NOTES,
  endNote,
  idleLease,
  monitorLevel,
  parseLease,
  refusalNote,
  type LeaseState,
} from './monitor';

/* What the page makes of the lease the server publishes: the state it reads, the level it draws, and the
   note each reason a lease ends is shown with. The server owns every clock in it. */

const state = (over: Record<string, unknown> = {}) => ({
  on: true,
  started_at: 1000,
  banner_due_at: 2200,
  deadline: 2800,
  confirm_by: null,
  visible: true,
  last_end: null,
  level: null,
  label: 'Live monitor · Haiku',
  model: 'claude-haiku-5-5',
  destination: 'api.anthropic.com',
  disclosure: 'Sends to api.anthropic.com through your Claude Code, to Haiku.',
  interval_sec: 60,
  now: 1100,
  ...over,
});

describe('reading the lease', () => {
  it('reads the server’s state, its clock and the words it says are sent', () => {
    const lease = parseLease(state({ confirm_by: 2800 })) as LeaseState;
    expect(lease).toMatchObject({
      on: true,
      startedAt: 1000,
      bannerDueAt: 2200,
      deadline: 2800,
      confirmBy: 2800,
      destination: 'api.anthropic.com',
      now: 1100,
      lastEnd: null,
    });
    expect(lease.disclosure).toContain('Haiku');
  });

  it('reads an end as its reason and time, and drops any reason it does not know', () => {
    expect(
      parseLease(state({ on: false, last_end: { reason: 'left', at: 1500 } }))?.lastEnd,
    ).toEqual({
      reason: 'left',
      at: 1500,
    });
    expect(parseLease(state({ last_end: { reason: 'because', at: 1 } }))?.lastEnd).toBeNull();
  });

  it('reads nothing from what is not a lease', () => {
    for (const value of [null, undefined, 'on', 3, [], {}, { on: 'yes' }]) {
      expect(parseLease(value)).toBeNull();
    }
  });

  it('has an idle lease that is off and says nothing is sent', () => {
    expect(idleLease()).toMatchObject({ on: false, level: null, disclosure: null, lastEnd: null });
  });
});

describe('the level the monitor draws', () => {
  const row = (over: Record<string, unknown> = {}) => ({
    level: 'medium',
    model_level: 'medium',
    floor_applied: false,
    reason: 'The latest turns wrote outside the saved folders.',
    cites: [{ number: 1, fact_id: 'f1' }],
    fallback: 'not_enough',
    source: 'Live monitor · Haiku',
    checked_at: 1090,
    ...over,
  });

  it('is labelled the monitor’s, names its level, and carries the model’s own sentence', () => {
    const lease = parseLease(state({ level: row() })) as LeaseState;
    const level = monitorLevel(lease);
    expect(level).toMatchObject({
      level: 'medium',
      label: 'Medium',
      monitor: true,
      analysis: false,
      note: 'The latest turns wrote outside the saved folders.',
    });
    expect(level?.source.startsWith('Live monitor · Haiku')).toBe(true);
  });

  it('is absent, never None or low, until a check has completed', () => {
    expect(monitorLevel(parseLease(state()) as LeaseState)).toBeNull();
  });

  it('is absent while the lease is off, and for a level it does not know', () => {
    expect(monitorLevel(parseLease(state({ on: false, level: row() })) as LeaseState)).toBeNull();
    expect(
      monitorLevel(parseLease(state({ level: row({ level: 'severe' }) })) as LeaseState),
    ).toBeNull();
  });

  it('keeps Not enough recorded yet as a level of its own', () => {
    const level = monitorLevel(
      parseLease(state({ level: row({ level: 'not_enough' }) })) as LeaseState,
    );
    expect(level?.label).toBe('Not enough recorded yet');
  });
});

describe('the note each end is shown with', () => {
  it('has one for every reason a lease ends, and none for the reader’s own off', () => {
    expect(Object.keys(END_NOTES).sort()).toEqual(
      ['cap', 'declined', 'ended', 'left', 'paused', 'unanswered'].sort(),
    );
    expect(endNote('stopped', {})).toBe('');
  });

  it('says the session ended, with nothing live to monitor', () => {
    expect(endNote('ended', {})).toMatch(/session ended/i);
  });

  it('says no answer after the minutes the server allowed, and that no more calls were made', () => {
    expect(endNote('unanswered', { answerMinutes: 10 })).toBe(
      'Live monitor turned off: no answer after 10 minutes, so no more model calls were made.',
    );
  });

  it('words the monitor’s own limit apart from Analyze’s', () => {
    const note = endNote('cap', {});
    expect(note).toMatch(/Live monitor/);
    expect(note).not.toMatch(/drift analyses/);
    expect(note).toMatch(/not your Analyze/);
  });

  it('says why a start was refused', () => {
    expect(refusalNote('paused')).toMatch(/paused/);
    expect(refusalNote('ended')).toMatch(/ended/);
    expect(refusalNote('no-observer-model')).toMatch(/off for this run/);
    expect(refusalNote('something-new')).toMatch(/did not start/);
  });
});
