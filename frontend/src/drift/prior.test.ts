import { describe, expect, it } from 'vitest';
import { annotationOf } from '../intent/annotation';
import { clock } from '../observed';
import { priorDepartures } from './prior';
import { priorDepartureLine, priorListedLine } from './sentences';
import { readingShape } from './shape';

/* An earlier departure the store kept beside the reading that replaced it (`annotation_prior_departures`) is
   listed only where the later reading answers that line with the agent's own message and nothing else: a
   check, a written file or another departure answers it on the record, and words the reader has since changed
   were not what it departed from. */

const LINE = 'Leave the stylesheets alone';
const WRITE = {
  id: 'w1',
  type: 'tool_report',
  source: 'Claude Write call',
  subject: 'write',
  work: true,
  at: 520,
  summary: 'src/styles/queue.css',
};
const SAID = {
  id: 'm1',
  type: 'agent_message',
  by: 'agent',
  source: 'transcript',
  subject: '',
  result: '',
  at: 700,
  summary: 'The stylesheet edit was needed for the queue page, so I kept it.',
};
const PASSED = {
  id: 'c2',
  type: 'tool_report',
  source: 'Claude Bash call',
  subject: 'check',
  checkId: 'check:pytest -q',
  summary: 'pytest -q',
  result: 'passed',
  work: true,
  at: 720,
};
const ENTRIES = [WRITE, SAID, PASSED];
const UNSETTLED = { result: 'not verifiable from available evidence', cites: [], detail: '' };
const DETAIL = 'A stylesheet was written, which this line rules out.';

const stored = (extra: Record<string, unknown> = {}, criterion: Record<string, unknown> = {}) => ({
  key: 'line_2',
  read_at: 1000,
  revision_read: 3,
  criterion: {
    result: 'departure',
    cites: ['w1'],
    detail: DETAIL,
    clause: LINE,
    why: 'recorded-write',
    ...criterion,
  },
  ...extra,
});

const shapeOf = (line2: Record<string, unknown>, words: string = LINE) => {
  const raw = {
    revision_read: 3,
    window_start: 100,
    scope: 'last-turn',
    read_at: 1200,
    criteria: {
      goal: { ...UNSETTLED, clause: 'Ship the queue' },
      line_1: { ...UNSETTLED, clause: 'Tests pass' },
      line_2: { clause: words, detail: '', ...line2 },
    },
  };
  const annotation = annotationOf({
    harness: 'claude',
    sid: 's1',
    annotation_goal: 'Ship the queue',
    annotation_line_1: 'Tests pass',
    annotation_line_2: words,
    annotation_revision: 3,
    annotation_assessment: raw,
  } as never);
  return readingShape(raw, annotation, ENTRIES as never, '', false, () => 'typed');
};

const ON_MESSAGE = shapeOf({ result: 'consistent with the evidence read', cites: ['m1'] });

describe('an earlier departure beside the reading after it', () => {
  it('is listed where the later line rests on what the agent said, with its cited write and reason', () => {
    const listed = priorDepartures([stored()], ON_MESSAGE, ENTRIES as never);
    expect(listed).toHaveLength(1);
    const [prior] = listed;
    expect(prior?.key).toBe('line_2');
    expect(prior?.readAt).toBe(1000);
    expect(prior?.row.result).toBe('departure');
    expect(prior?.row.citedIds).toEqual(['w1']);
    expect(prior?.row.detail).toBe(DETAIL);
    expect(prior?.row.clause).toBe(LINE);
    expect(prior?.later.restsOn).toBe('message');
    expect(prior?.later.restsOnEntry?.id).toBe('m1');
  });

  it('is not listed where a check answers the line', () => {
    const checked = shapeOf({ result: 'consistent with the evidence read', cites: ['c2'] });
    expect(checked.criteria.find((row) => row.key === 'line_2')?.restsOn).toBe('tool');
    expect(priorDepartures([stored()], checked, ENTRIES as never)).toEqual([]);
  });

  it('is not listed where the later reading departs there again or cannot tell', () => {
    const again = shapeOf({
      result: 'departure',
      cites: ['w1'],
      detail: DETAIL,
      why: 'recorded-write',
    });
    expect(priorDepartures([stored()], again, ENTRIES as never)).toEqual([]);
    const cantTell = shapeOf(UNSETTLED);
    expect(priorDepartures([stored()], cantTell, ENTRIES as never)).toEqual([]);
  });

  it('is not listed once the reader has changed the words it departed from', () => {
    const reworded = shapeOf(
      { result: 'consistent with the evidence read', cites: ['m1'] },
      'Leave the CSS alone',
    );
    expect(priorDepartures([stored()], reworded, ENTRIES as never)).toEqual([]);
  });

  it('is not listed where the page holds none of the entries it cited', () => {
    expect(priorDepartures([stored({}, { cites: ['w9'] })], ON_MESSAGE, ENTRIES as never)).toEqual(
      [],
    );
  });

  it('refuses what is not a stored departure on the goal or an outcome line', () => {
    const refused = [
      stored({ key: 'claims' }),
      stored({ key: 'line_9' }),
      stored({}, { result: 'consistent with the evidence read' }),
      stored({ read_at: 'soon' }),
      stored({ criterion: 'departure' }),
      'line_2',
      null,
    ];
    expect(priorDepartures(refused, ON_MESSAGE, ENTRIES as never)).toEqual([]);
    expect(priorDepartures(undefined, ON_MESSAGE, ENTRIES as never)).toEqual([]);
    expect(priorDepartures({ line_2: stored() }, ON_MESSAGE, ENTRIES as never)).toEqual([]);
  });

  it('lists nothing over a reading the shape refused', () => {
    const refused = { ...ON_MESSAGE, malformed: 'surprise', criteria: [], departures: [] };
    expect(priorDepartures([stored()], refused, ENTRIES as never)).toEqual([]);
    expect(priorDepartures([stored()], null, ENTRIES as never)).toEqual([]);
  });

  it('keeps one per line, the newest', () => {
    const older = stored({ read_at: 900 }, { detail: 'Older.' });
    const listed = priorDepartures([older, stored()], ON_MESSAGE, ENTRIES as never);
    expect(listed.map((prior) => prior.readAt)).toEqual([1000]);
  });
});

describe('what the page says about it', () => {
  it('names the reading it came from and what the later one rests on', () => {
    expect(priorDepartureLine(clock(1000), clock(1200), '#17')).toBe(
      `From the ${clock(1000)} reading. The ${clock(1200)} reading rests this line on what the agent said at #17, which is not a check.`,
    );
  });

  it('says the departure is still listed, in place of saying it no longer holds', () => {
    expect(priorListedLine(1, clock(1000))).toBe(
      `The departure from the ${clock(1000)} reading is still listed below: the reading after it rests on what the agent said.`,
    );
    expect(priorListedLine(2, clock(1000))).toBe(
      `The 2 departures from the ${clock(1000)} reading are still listed below: the reading after it rests on what the agent said.`,
    );
    expect(priorListedLine(2, '')).toBe(
      'The 2 departures from earlier readings are still listed below: the reading after them rests on what the agent said.',
    );
  });
});
