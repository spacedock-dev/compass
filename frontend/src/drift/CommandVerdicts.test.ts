import { describe, expect, it } from 'vitest';
import type { WorkEntry } from '../intent/work';
import { driftReasons } from './level';
import { departureTitle, departureWhat, titledEntry } from './result';
import { CONSISTENT, DEPARTURE } from './sentences';
import { checkSupports } from './shape';

/* A tier 3 command and a tier 2 CI read carry a verdict the way a check does, and the page words them as what
   they are
   ([DEC-29](../../../docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)). */
const entry = (subject: string, result: string, extra: Partial<WorkEntry> = {}): WorkEntry =>
  ({
    id: `${subject}-1`,
    type: 'tool_report',
    subject,
    result,
    at: 150,
    resultAt: null,
    summary: 'make release',
    source: 'Claude Bash call and paired result',
    ...extra,
  }) as unknown as WorkEntry;

describe('a command or CI read in the shape contract', () => {
  it.each(['command', 'ci_command'])('carries a consistent or a departure (%s)', (subject) => {
    expect(checkSupports(entry(subject, 'passed'), CONSISTENT, 100)).toBe(true);
    expect(checkSupports(entry(subject, 'failed'), DEPARTURE, 100)).toBe(true);
  });

  it.each(['command', 'ci_command'])('carries nothing once it cannot fail (%s)', (subject) => {
    const forced = entry(subject, 'passed', { cannotFail: true });
    expect(checkSupports(forced, CONSISTENT, 100)).toBe(false);
    expect(checkSupports(forced, DEPARTURE, 100)).toBe(false);
  });
});

describe('a departure that rests on a command', () => {
  const failed = entry('command', 'failed');
  it('prefers a failed command to the first entry', () => {
    const said = entry('x', '', { type: 'agent_message', subject: '' });
    expect(titledEntry([said, failed])).toBe(failed);
  });
  it('names a command, never a check or the record', () => {
    expect(departureTitle([failed])).toMatch(/^A command exited non-zero at /);
    expect(departureWhat([failed])).toMatch(/a command exited non-zero: make release\.$/);
    const ci = entry('ci_command', 'failed', { summary: 'gh pr checks 7' });
    expect(departureTitle([ci])).toMatch(/^A CI check failed at /);
  });
});

describe('a failed command or CI read that holds the live floor', () => {
  const reasons = (fact: WorkEntry) =>
    driftReasons('not_enough', ['failed-check'], [fact.id], [fact], new Map(), new Set(), 1000)
      .blockers;
  it('is worded as itself and says its entry is listed', () => {
    expect(reasons(entry('command', 'failed'))).toEqual([
      expect.stringMatching(/^Command make release exited non-zero .* ago/),
    ]);
    expect(reasons(entry('ci_command', 'failed', { summary: 'gh pr checks 7' }))).toEqual([
      expect.stringMatching(/^CI check gh pr checks 7 failed .* ago/),
    ]);
    expect(reasons(entry('command', 'failed')).join()).not.toMatch(/not listed/);
  });
});
