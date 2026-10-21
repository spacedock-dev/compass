import { describe, expect, it } from 'vitest';
import { steerTrigger } from './correction';
import { cantTellReason, claimHeading, claimReason } from './result';
import { criterion } from './shape';
import {
  CHECK_DOES_NOT_SHOW_IT,
  CLAIMS,
  CONSISTENT,
  DEPARTURE,
  RESULT_NOTHING_SHOWS_REASON,
  UNSUPPORTED,
  UNVERIFIABLE,
} from './sentences';

/* What the page makes of a line the producer settled from a recorded write, of the reason an unsettled line
   gives, of the claim a claims row quotes, and of the Steer back line a claim alone no longer draws. */

const WRITE = {
  id: 'w1',
  type: 'tool_report',
  source: 'Claude Write call',
  subject: 'write',
  work: true,
  at: 520,
  summary: 'frontend/e2e/a.ts',
};
const LINE = 'No file under frontend/e2e is edited';
const stored = (extra: Record<string, unknown> = {}) => ({
  result: DEPARTURE,
  cites: ['w1'],
  detail: '1 file recorded as written under frontend/e2e, which this line rules out.',
  clause: LINE,
  ...extra,
});
const read = (raw: unknown, entries: readonly unknown[] = [WRITE], window = 100) =>
  criterion(
    'line_1',
    'Expected outcome',
    LINE,
    raw as never,
    entries as never,
    '',
    false,
    window,
    'last-turn',
  );

describe('a line the producer settled from a recorded write', () => {
  it('departs on the written path it cites', () => {
    const row = read(stored({ why: 'recorded-write' }));
    expect(row.result).toBe(DEPARTURE);
    expect(row.citedIds).toEqual(['w1']);
    expect(row.detail).toContain('frontend/e2e');
  });

  it('is withdrawn when a model cited the same write with no token: a write carries no result', () => {
    const row = read(stored());
    expect(row.result).toBe(UNVERIFIABLE);
    expect(row.why).toBe(CHECK_DOES_NOT_SHOW_IT);
  });

  it('lets the write carry a departure and no other verdict', () => {
    const row = read(stored({ why: 'recorded-write', result: CONSISTENT }));
    expect(row.result).toBe(UNVERIFIABLE);
  });

  it('does not stand on a write from before the words were saved', () => {
    const row = read(stored({ why: 'recorded-write' }), [{ ...WRITE, at: 40 }]);
    expect(row.result).toBe(UNVERIFIABLE);
  });

  it('says why it was withdrawn where the page does not hold the write', () => {
    const row = read(stored({ why: 'recorded-write' }), []);
    expect(row.result).toBe(UNVERIFIABLE);
    expect(row.why).not.toBe('');
  });
});

describe('the reason a line reads Can’t tell', () => {
  const numbers = new Map([
    ['c2', '8'],
    ['c3', '9'],
  ]);
  const row = (extra: Record<string, unknown>) =>
    ({ why: '', limit: '', citedIds: [], ...extra }) as never;

  it('is the rule that withdrew it, or the limit of the harness, before anything else', () => {
    expect(cantTellReason(row({ why: 'a rule', limit: 'a limit' }), numbers)).toBe('a rule');
    expect(cantTellReason(row({ limit: 'a limit' }), numbers)).toBe('a limit');
  });

  it('otherwise names the entries it read, by the list’s numbers', () => {
    expect(cantTellReason(row({ citedIds: ['c2', 'c3'] }), numbers)).toBe(
      'What it read, #8, #9, neither shows nor contradicts this.',
    );
    expect(cantTellReason(row({ citedIds: ['gone'] }), numbers)).toBe(
      'What it read neither shows nor contradicts this.',
    );
  });

  it('says nothing recorded speaks to a line that cites nothing', () => {
    expect(cantTellReason(row({}), numbers)).toBe(RESULT_NOTHING_SHOWS_REASON);
  });
});

describe('the claims row quotes the claim', () => {
  const numbers = new Map([['m1', '13']]);
  const claims = (extra: Record<string, unknown>) =>
    ({
      key: CLAIMS,
      result: UNSUPPORTED,
      claimEntry: { id: 'm1', summary: 'All green locally: 473 tests pass.' },
      recordEntry: null,
      ...extra,
    }) as never;

  it('quotes the message’s title without its closing stop', () => {
    expect(claimHeading(claims({}), numbers)).toEqual({
      claim: 'All green locally: 473 tests pass',
      tail: 'is not shown by the record',
    });
  });

  const said = (summary: string) => claims({ claimEntry: { id: 'm1', summary } });
  const check = (summary: string, result: string, at = 600) => ({
    id: `c-${summary}`,
    type: 'tool_report',
    subject: 'check',
    summary,
    result,
    at,
  });
  const reason = (summary: string, entries: readonly unknown[] = [], window = 100) =>
    claimReason(said(summary), numbers, entries as never, window);

  it('says where the agent made a claim that names no kind of check, and what was read', () => {
    expect(claimReason(said('The PR is open.'), numbers)).toBe(
      "Nothing in the record read backs this claim, which the agent made at #13. The record read is the board's recent tail.",
    );
  });

  it('says no check of the kind a claim names was recorded', () => {
    expect(reason('All green locally: 473 tests pass.')).toBe(
      'No test check was recorded in what was read, so nothing backs this claim.',
    );
    expect(reason('Lint and the type checks are clean.')).toBe(
      'No lint check and no type check was recorded in what was read, so nothing backs this claim.',
    );
  });

  it('says a check of the kind ran with no recorded result', () => {
    const entries = [check('ruff check .', 'not-recorded'), check('mypy', '')];
    expect(reason('The lint and type checks pass', entries)).toBe(
      'The lint and type checks ran with no recorded result, so nothing backs this claim.',
    );
  });

  it('says a passing check was recorded and the analysis did not tie it to the claim', () => {
    expect(reason('The tests pass', [check('pytest -q', 'passed')])).toBe(
      'A test check passed on record, and the analysis did not tie it to this claim.',
    );
  });

  it('gives each claim its own reason, and reads only checks after the window opened', () => {
    const entries = [check('pytest -q', 'passed', 50), check('ruff check .', '')];
    expect(reason('The tests pass and the build is green', entries, 100)).toBe(
      'No test check and no build check was recorded in what was read, so nothing backs this claim.',
    );
    expect(reason('The tests pass', entries, 100)).not.toBe(
      reason('The build is green', entries, 100),
    );
  });

  it('has nothing to quote where the row cites no message it holds', () => {
    expect(claimHeading(claims({ claimEntry: null }), numbers)).toBeNull();
  });
});

describe('the line under Steer back', () => {
  const base = {
    shape: null,
    session: {},
    entries: [{ id: 'm1', at: 900 }] as never,
    numbers: new Map([['m1', '13']]),
    scan: null,
    generated: 1000,
  };

  it('is not drawn for a claim alone', () => {
    expect(
      steerTrigger({ ...base, offer: { departed: false, claimed: true, failed: false } }),
    ).toBe('');
  });
});
