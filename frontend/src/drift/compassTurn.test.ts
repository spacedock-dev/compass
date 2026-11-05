import { describe, expect, it } from 'vitest';
import { activityRow } from './activity.test.helper';
import { arrivedLine, resultStale } from './result';
import type { Shape } from './shape';
import type { WorkEntry } from '../intent/work';

/* The server marks the agent's facts inside a turn the reader's typed Compass command opened (`compass_turn`).
   A reading never read them, so a reading is not stale for them and "arrived since" does not count them. */
const SHAPE = { revisionRead: null } as unknown as Shape;
const RAW = { read_at: 1000, evidence_through: 1000 };
const ANNOTATION = { revision: 1, at: 900, assessment: { read_at: 1000 } };

const after = (extra: Partial<WorkEntry>): WorkEntry =>
  activityRow(1, { at: 1100, ...extra }).entry;
const message = (extra: Partial<WorkEntry> = {}): WorkEntry =>
  after({ type: 'agent_message', subject: '', summary: 'Compass printed this', ...extra });

describe('a Compass turn after a reading', () => {
  it('is new work when the agent did it', () => {
    expect(resultStale(SHAPE, RAW, ANNOTATION, [message()])?.head).toBe(
      'New work since this analysis.',
    );
    expect(arrivedLine(ANNOTATION, [message()])).toBe('1 message arrived since this analysis.');
  });

  it('is not new work when the server marked it as Compass’s turn', () => {
    const marked = [message({ compassTurn: true }), after({ compassTurn: true })];
    expect(resultStale(SHAPE, RAW, ANNOTATION, marked)).toBeNull();
    expect(arrivedLine(ANNOTATION, marked)).toBe('');
  });

  it('still counts the work the agent did beside it', () => {
    const entries = [message({ compassTurn: true }), after({ id: 'c2', at: 1200 })];
    expect(resultStale(SHAPE, RAW, ANNOTATION, entries)?.kind).toBe('work');
    expect(arrivedLine(ANNOTATION, entries)).toBe('1 check arrived since this analysis.');
  });
});
