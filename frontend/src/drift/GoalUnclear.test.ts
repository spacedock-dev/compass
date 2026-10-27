import { describe, expect, it } from 'vitest';
import { annotationOf } from '../intent/annotation';
import { steerOffer } from './correction';
import { driftReasons } from './level';
import { driftAnswer, verdictLine, verdictNamesLevel } from './result';
import {
  BLOCKER_LINES,
  GOAL_UNCLEAR,
  GOAL_UNCLEAR_VERDICT,
  RESULTS,
  UNVERIFIABLE,
} from './sentences';
import { readingShape } from './shape';

/* A goal the model found no end state in is refused in place of a level, and a goal with no outcome line
   is read for its own end state. The producer's words for both are `reading.RESULT_GOAL_UNCLEAR` and
   `levels.REASON_GOAL_UNCLEAR`, and `api/vocabulary.test.ts` holds the spellings to the producer's.
   [DEC-26](../../../docs/design-reading-a-session.md#amended-2026-10-22-a-goal-alone-is-read-or-refused) */

const PERSON = {
  id: 'u1',
  type: 'user_message',
  by: 'person:me',
  summary: 'testing',
  at: 100,
  subject: '',
  result: '',
};
const CHECK = {
  id: 'c1',
  type: 'tool_report',
  subject: 'check',
  checkId: 'check:pytest -q',
  summary: 'pytest -q',
  result: 'passed',
  at: 300,
  resultAt: undefined,
  work: true,
};
const held = (...rows: readonly object[]) => rows as never;

const UNCLEAR = 'goal too vague to analyze against';
const AGREED =
  'This goal is too vague to analyze against. Rewrite it with what should be true when the work is done, then try again.';

const shapeOf = (criteria: Record<string, object>, entries: readonly object[] = []) => {
  const raw = { revision_read: 2, scope: 'last-turn', read_at: 400, criteria };
  const annotation = annotationOf({
    harness: 'claude',
    sid: 's',
    annotation_goal: 'testing',
    annotation_revision: 2,
    annotation_assessment: raw,
  } as never);
  return readingShape(raw, annotation, held(...entries), '', false, () => 'typed');
};

describe('the refusal', () => {
  it('says the agreed sentence, in the page and in the producer-held vocabulary', () => {
    expect(GOAL_UNCLEAR).toBe(AGREED);
    expect(RESULTS).toContain(UNCLEAR);
  });

  it('stands on the goal row with no citation, and takes no demotion', () => {
    const shape = shapeOf({ goal: { result: UNCLEAR, cites: [], detail: '', clause: 'testing' } });
    const goal = shape.criteria.find((row) => row.key === 'goal');
    expect(goal?.result).toBe(UNCLEAR);
    expect(goal?.why).toBe('');
    expect(shape.departures).toEqual([]);
  });

  it('stands whatever the saved intent says about a later direction', () => {
    const raw = {
      revision_read: 2,
      scope: 'last-turn',
      read_at: 400,
      criteria: { goal: { result: UNCLEAR, cites: [], detail: '', clause: 'x' } },
    };
    const annotation = annotationOf({
      harness: 'claude',
      sid: 's',
      annotation_revision: 2,
    } as never);
    const shape = readingShape(raw, annotation, held(), '', true, () => 'typed');
    expect(shape.criteria.find((row) => row.key === 'goal')?.result).toBe(UNCLEAR);
  });

  it('means nothing on an outcome line, which is a result outside its set', () => {
    const shape = shapeOf({
      goal: { result: UNVERIFIABLE, cites: [], detail: '', clause: 'g' },
      line_1: { result: UNCLEAR, cites: [], detail: '', clause: 'l' },
    });
    const line = shape.criteria.find((row) => row.key === 'line_1');
    expect(line?.result).toBe(UNVERIFIABLE);
  });

  it('is the answer, in place of a level, a departure or a check', () => {
    const entries = held(PERSON, { ...CHECK, result: 'failed' });
    const shape = shapeOf({ goal: { result: UNCLEAR, cites: [], detail: '', clause: 'testing' } });
    const answer = driftAnswer(shape, entries, null);
    expect(answer.kind).toBe('goal-unclear');
    expect(verdictNamesLevel(answer)).toBe(false);
    expect(verdictLine({ answer, level: 'Medium', byId: new Map(), midFlight: false })).toBe(
      GOAL_UNCLEAR_VERDICT,
    );
  });

  it('offers no Steer back for that run, even over a failed check', () => {
    const shape = shapeOf({ goal: { result: UNCLEAR, cites: [], detail: '', clause: 'testing' } });
    const session = { harness: 'claude', sid: 's', state: 'idle' };
    const annotation = annotationOf({
      ...session,
      annotation_goal: 'testing',
      annotation_revision: 2,
    } as never);
    const failed = {
      ...CHECK,
      result: 'failed',
      id: 'c9',
      at: 500,
    };
    const offer = steerOffer({
      session,
      annotation,
      source: {
        state: 'read',
        all: [PERSON, failed],
        entries: [PERSON, failed],
        scan: null,
      } as never,
      shape,
      annotate: true,
      drafted: false,
    });
    expect(offer).toBeNull();
  });
});

describe('a goal with no outcome line', () => {
  const shown = { result: 'consistent with the evidence read', restsOn: 'tool', citedIds: ['c1'] };

  it('can find nothing against what it read, where it used to say it could not tell', () => {
    const entries = held(PERSON, CHECK);
    const shape = {
      criteria: [{ ...shown, key: 'goal' }],
      departures: [],
      windowStart: 100,
    } as never;
    expect(driftAnswer(shape, entries, null).kind).toBe('nothing-found');
  });

  it('still cannot tell where the goal row could not settle', () => {
    const shape = {
      criteria: [{ result: UNVERIFIABLE, restsOn: '', citedIds: [], key: 'goal' }],
      departures: [],
      windowStart: 100,
    } as never;
    expect(driftAnswer(shape, held(PERSON, CHECK), null).kind).toBe('cant-tell');
  });

  it('departs when the goal departs', () => {
    const departing = { key: 'goal', result: 'departure', restsOn: '', citedIds: ['c1'] };
    const shape = { criteria: [departing], departures: [departing], windowStart: 100 } as never;
    expect(driftAnswer(shape, held(PERSON, CHECK), null).kind).toBe('departs');
  });
});

describe('the reasons a level is withheld for', () => {
  const reasons = (tokens: readonly string[]) =>
    driftReasons('not_enough', tokens, [], [], new Map(), new Set(), 1000).blockers;

  it('gives goal-unclear the agreed sentence', () => {
    expect(BLOCKER_LINES['goal-unclear']).toBe(AGREED);
    expect(reasons(['goal-unclear'])).toEqual([AGREED]);
  });

  it('keeps the sentence a reading stored before the change carries', () => {
    expect(reasons(['no-outcome-line'])).toEqual(['No expected outcome line was saved.']);
  });
});
