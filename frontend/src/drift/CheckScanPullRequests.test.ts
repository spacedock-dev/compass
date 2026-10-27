import { describe, expect, it } from 'vitest';
import { checkScan } from './workList';

/* A session whose only recorded work is a created pull request or a launched skill did not run no check and
   write no file: the sentence counts them from the full scan, as it counts files. */
describe('the check scan sentence beside a pull request or a skill', () => {
  it('does not say no check ran where a pull request was created', () => {
    const text = checkScan({ pull_requests: 1 });
    expect(text).not.toContain('No check ran');
    expect(text).toContain('1 pull request created');
  });

  it('counts skills and several pull requests', () => {
    const text = checkScan({ pull_requests: 2, skills_used: 3 });
    expect(text).toContain('2 pull requests created');
    expect(text).toContain('3 skills used');
  });

  it('still says no check ran where nothing was recorded at all', () => {
    expect(checkScan({})).toBe('No check ran in the part of the transcript read.');
    expect(checkScan({ pull_requests: 0, skills_used: 0 })).toBe(
      'No check ran in the part of the transcript read.',
    );
  });
});

describe('the check scan sentence beside a listing the session wrote', () => {
  it('says the commands the reader listed did not count, even where no check ran', () => {
    expect(checkScan({ reader_checks_written: true })).toBe(
      'No check ran in the part of the transcript read. The session wrote the file where you list checks, so none of the commands you listed counted as checks.',
    );
  });

  it('says it after the rest of the sentence, and is silent without the flag', () => {
    expect(checkScan({ check_runs: 1, distinct_checks: 1, reader_checks_written: true })).toMatch(
      /The session wrote the file where you list checks/,
    );
    expect(checkScan({ check_runs: 1, distinct_checks: 1 })).not.toContain('you list checks');
  });
});
