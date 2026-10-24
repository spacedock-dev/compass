import { describe, expect, it } from 'vitest';
import { steerTrigger } from './correction';

/* What put Steer back on offer names the entry the card beside it names. A departure citing #3 and #4 drew
   "Departs; evidence #3" on its row and "Departure evidence at #4" here, and a failed check under "Not checked
   yet" read as the drift check having failed. */
const entries = [
  { id: 'u1', at: 100, type: 'user_message' },
  { id: 'e3', at: 900 },
  { id: 'e4', at: 950 },
  {
    id: 'e5',
    at: 960,
    type: 'tool_report',
    subject: 'check',
    summary: 'pytest -q',
    result: 'failed',
  },
];
const numbers = new Map([
  ['e3', '3'],
  ['e4', '4'],
]);

describe('the Steer back trigger', () => {
  it('names a departure by its first cited entry, as its result row does', () => {
    const text = steerTrigger({
      offer: { departed: true, claimed: false, failed: false },
      shape: { departures: [{ citedIds: ['e3', 'e4'] }], criteria: [] } as never,
      entries: entries as never,
      numbers,
      generated: 1000,
    });
    expect(text).toMatch(/^Departure evidence at #3 · /);
  });

  it('draws no line for a failed check or a claim without a departure', () => {
    for (const offer of [
      { departed: false, claimed: false, failed: true },
      { departed: false, claimed: true, failed: false },
    ]) {
      expect(
        steerTrigger({
          offer,
          shape: null,
          entries: entries as never,
          numbers,
          generated: 1000,
        }),
      ).toBe('');
    }
  });
});
