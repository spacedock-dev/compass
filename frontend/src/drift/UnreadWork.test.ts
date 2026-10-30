import { describe, expect, it } from 'vitest';
import { activityRow } from './activity.test.helper';
import {
  checkScan,
  INCOMPLETE_PASS_MARK,
  incompletePass,
  MARK_LEGEND,
  unreadWork,
} from './workList';

describe('how much work a scan says was not read', () => {
  it('reads the unread subagents and calls from the scan', () => {
    expect(unreadWork({ subagent_transcripts_unread: 2, unread_calls: 4 })).toEqual({
      subagents: 2,
      calls: 4,
    });
  });

  it('reads nothing where every count is zero or absent', () => {
    expect(unreadWork({})).toEqual({ subagents: 0, calls: 0 });
    expect(unreadWork({ subagent_transcripts_unread: 0, unread_calls: 0 })).toEqual({
      subagents: 0,
      calls: 0,
    });
    expect(unreadWork(null)).toEqual({ subagents: 0, calls: 0 });
  });
});

describe('the check scan sentence beside unread work', () => {
  it('states the counts instead of implying nothing ran', () => {
    expect(checkScan({ subagent_transcripts_unread: 2, unread_calls: 4 })).toBe(
      'No check ran in the part of the transcript read; 2 subagents and 4 calls were not read.',
    );
  });

  it('reads one of each in the singular, and one kind alone', () => {
    expect(checkScan({ subagent_transcripts_unread: 1, unread_calls: 1 })).toBe(
      'No check ran in the part of the transcript read; 1 subagent and 1 call were not read.',
    );
    expect(checkScan({ subagent_transcripts_unread: 3 })).toBe(
      'No check ran in the part of the transcript read; 3 subagents were not read.',
    );
    expect(checkScan({ unread_calls: 1 })).toBe(
      'No check ran in the part of the transcript read; 1 call was not read.',
    );
  });

  it('adds the counts after the runs where a check did run', () => {
    const text = checkScan({
      check_runs: 1,
      distinct_checks: 1,
      passed: 1,
      subagent_transcripts_unread: 2,
    });
    expect(text).toContain('1 passed.');
    expect(text).toContain('2 subagents were not read.');
  });

  it('keeps today sentence where everything was read', () => {
    expect(checkScan({ subagent_transcripts_unread: 0, unread_calls: 0 })).toBe(
      'No check ran in the part of the transcript read.',
    );
  });
});

describe('the mark on a passing check when work was not read', () => {
  const passed = activityRow(1, { result: 'passed', resultSource: 'flag' });
  const marksOf = (row: ReturnType<typeof activityRow>) =>
    'check' in row.head && row.head.check ? row.head.check.marks : [];

  it('says it may not cover subagent work', () => {
    const marks = marksOf(incompletePass(passed, { subagent_transcripts_unread: 2 }));
    expect(marks.map((mark) => mark.short)).toEqual(['Passed', 'May not cover subagent work']);
  });

  it('says it for unread calls, and for both', () => {
    expect(marksOf(incompletePass(passed, { unread_calls: 4 }))[1]?.short).toBe(
      'May not cover every call',
    );
    expect(
      marksOf(incompletePass(passed, { unread_calls: 4, subagent_transcripts_unread: 1 }))[1]
        ?.short,
    ).toBe('May not cover subagent work or every call');
  });

  it('adds nothing where everything was read, or no scan was published', () => {
    expect(incompletePass(passed, { subagent_transcripts_unread: 0 })).toBe(passed);
    expect(incompletePass(passed, null)).toBe(passed);
  });

  it('marks a pass only, never a failed or unrecorded check', () => {
    const failed = activityRow(2, { result: 'failed', resultSource: 'flag' });
    const none = activityRow(3, {});
    expect(incompletePass(failed, { unread_calls: 4 })).toBe(failed);
    expect(incompletePass(none, { unread_calls: 4 })).toBe(none);
  });
});

describe('the legend for the unread-work mark', () => {
  it('explains the icon in the mark legend', () => {
    expect(MARK_LEGEND).toContain(INCOMPLETE_PASS_MARK);
    expect(INCOMPLETE_PASS_MARK.words).toContain('may not cover');
  });

  it('names the words in the mark accessible name', () => {
    const passed = activityRow(1, { result: 'passed', resultSource: 'flag' });
    const row = incompletePass(passed, { unread_calls: 4 });
    const marks = 'check' in row.head && row.head.check ? row.head.check.marks : [];
    expect(marks[1]?.words).toContain('may not cover every call');
  });
});
