import { describe, expect, it } from 'vitest';
import { failedChecks } from './correction';
import { driftAnswer, failedChecksAfterPerson } from './result';

/* A red test the agent wrote first and a later run of the same check fixed is the work going as planned, so
   it raises neither "A check failed" nor "A check the agent ran failed". The outline's rule, held here for the
   Drift card: a failed run followed by a pass of the same check is fixed. */

const person = {
  id: 'u1',
  type: 'user_message',
  by: 'person:me',
  summary: 'Ship it',
  at: 100,
  subject: '',
  result: '',
};
const check = (
  id: string,
  result: string,
  at: number,
  summary = 'pytest -q tests/test_retry.py',
) => ({
  id,
  type: 'tool_report',
  subject: 'check',
  summary,
  result,
  at,
  resultAt: undefined,
});
const held = (...rows: readonly object[]) => rows as never;

describe('a failed check a later run fixed', () => {
  it('is not a failed check after the person', () => {
    const entries = held(person, check('c1', 'failed', 200), check('c2', 'passed', 300));
    expect(failedChecksAfterPerson(entries, null, 0)).toEqual([]);
  });

  it('stays failed where the later pass is of another check', () => {
    const entries = held(
      person,
      check('c1', 'failed', 200),
      check('c2', 'passed', 300, 'ruff check .'),
    );
    expect(failedChecksAfterPerson(entries, null, 0).map((entry) => entry.id)).toEqual(['c1']);
  });

  it('stays failed where the pass came before it', () => {
    const entries = held(person, check('c2', 'passed', 150), check('c1', 'failed', 200));
    expect(failedChecksAfterPerson(entries, null, 0).map((entry) => entry.id)).toEqual(['c1']);
  });

  it('stays failed where the later run recorded no result', () => {
    const entries = held(person, check('c1', 'failed', 200), check('c2', 'not-recorded', 300));
    expect(failedChecksAfterPerson(entries, null, 0).map((entry) => entry.id)).toEqual(['c1']);
  });

  it('is not offered to Steer back from, and the answer is not a failed check', () => {
    const entries = held(person, check('c1', 'failed', 200), check('c2', 'passed', 300));
    expect(failedChecks({}, entries, null)).toEqual([]);
    const shown = {
      result: 'consistent with the evidence read',
      restsOn: 'tool',
      citedIds: ['c2'],
    };
    const shape = {
      criteria: [
        { ...shown, key: 'goal' },
        { ...shown, key: 'line_1' },
      ],
      departures: [],
      windowStart: 100,
    } as never;
    expect(driftAnswer(shape, entries, null).kind).toBe('nothing-found');
  });
});
