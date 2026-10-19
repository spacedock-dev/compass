import { describe, expect, it } from 'vitest';
import { CHECK_FAILED_TRIGGER, steerTrigger } from './correction';

/* What put Steer back on offer names the entry the card beside it names. A departure citing #3 and #4 drew
   "Departs; evidence #3" on its row and "Departure evidence at #4" here, and a failed check under "Not checked
   yet" read as the drift check having failed. */
const entries = [
  { id: 'e3', at: 900 },
  { id: 'e4', at: 950 },
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
      session: {},
      entries: entries as never,
      numbers,
      scan: null,
      generated: 1000,
    });
    expect(text).toMatch(/^Departure evidence at #3 · /);
  });

  it('says whose check failed', () => {
    expect(CHECK_FAILED_TRIGGER).toBe('A check the agent ran failed');
    expect(CHECK_FAILED_TRIGGER).not.toMatch(/^Check failed/);
  });
});
