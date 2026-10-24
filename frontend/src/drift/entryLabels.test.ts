import { describe, expect, it } from 'vitest';
import { workEntries } from '../intent/work';
import { correctionText } from './correction';
import { driftRange } from './level';
import { activityRow } from './activity.test.helper';
import { foldRuns } from './workList';

/* A check or file's number is the message it follows and its place after it, so the words that name an entry
   must carry the dot: "entry #41.2", and a range reads from the lowest label to the highest. */
const session = { harness: 'claude', sid: 's1' };
const fact = (id: string, at: number, ordinal: number, sub?: number) => ({
  fact_id: id,
  type: sub === undefined ? 'user_message' : 'tool_report',
  at,
  summary: id,
  source_session: session,
  ordinal,
  ...(sub === undefined ? {} : { ordinal_sub: sub }),
});

describe('the words that name an entry by its number', () => {
  it('draws no Compass entry number in a correction (owner, 2026-10-20)', () => {
    expect(
      correctionText(['A check failed at 13:58', { entry: 'c' }, '. You said so', { entry: 'm' }]),
    ).toBe('A check failed at 13:58. You said so');
    expect(correctionText(['At 13:58', { entry: 'gone' }, '.'])).toBe('At 13:58.');
  });

  it('reads a range from the lowest label to the highest', () => {
    const entries = workEntries(session, {
      facts: [fact('a', 10, 41), fact('b', 11, 41, 1), fact('c', 12, 41, 2), fact('d', 13, 42)],
    });
    const numbers = new Map(
      entries.map((entry) => [
        entry.id,
        String(entry.ordinal) + (entry.ordinalSub === null ? '' : `.${String(entry.ordinalSub)}`),
      ]),
    );
    expect(driftRange(entries, numbers, null, null)).toBe('#41 to #42');
    expect(driftRange(entries, numbers, 11, 12)).toBe('#41.1 to #41.2');
    expect(driftRange(entries, numbers, 12, 12)).toBe('#41.2');
  });

  it('reads a folded run from its lowest label to its highest, whatever order it is drawn in', () => {
    // A check is labelled where it first ran and drawn where it last did, so the drawn ends can be
    // out of order.
    const rows = ['43.2', '44', '41.1'].map((n, i) => ({ ...activityRow(i + 1), n }));
    const [run] = foldRuns(rows);
    expect(run && 'range' in run ? run.range : null).toBe('#41.1 to #44');
  });
});
