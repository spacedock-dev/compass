import { describe, expect, it } from 'vitest';
import { sessionMeta, turnEndedSentence } from './detail';

describe('the entries clause of the line under the title', () => {
  const session = { harness: 'claude', sid: 's', state: 'idle' };
  it('says a count read from the newest pages is a floor', () => {
    expect(sessionMeta(session, null, 50, null, true)).toContain('at least 50 entries');
  });
  it('states a whole record plainly', () => {
    const line = sessionMeta(session, null, 13, 4, false);
    expect(line).toContain('13 entries, 4 since your intent’s start');
    expect(line).not.toContain('at least');
  });
});

describe('a completed headless Codex run', () => {
  const session = {
    harness: 'codex',
    sid: 'exec',
    state: 'idle',
    headless: true,
    turn_end_at: 9400,
    finished_at: 9400,
    state_detail: 'run finished',
  };
  it('says the run finished with its age rather than waiting for a message', () => {
    expect(turnEndedSentence(session, 10000)).toBe('Run finished 10m ago');
    expect(sessionMeta(session, 10000, null)).toContain('Run finished 10m ago');
    expect(sessionMeta({ ...session, finished_at: null }, 10000, null)).toContain(
      'Run finished 10m ago',
    );
    expect(sessionMeta(session, 10000, null)).not.toContain('waiting');
  });
  it('keeps the interactive and other harness waiting sentence', () => {
    for (const row of [
      { ...session, headless: false },
      { ...session, headless: null },
      { ...session, harness: 'claude' },
    ]) {
      expect(turnEndedSentence(row, 10000)).toContain('waiting for you');
    }
  });
  it('withholds a finished claim without a validated stop or after new work', () => {
    expect(
      turnEndedSentence({ ...session, turn_end_at: null, finished_at: null }, 10000),
    ).toBeNull();
    expect(turnEndedSentence({ ...session, state: 'working' }, 10000)).toBeNull();
    expect(turnEndedSentence({ ...session, ended_at: 9500 }, 10000)).toBeNull();
  });
  it('does not invent an age when the payload has no clock', () => {
    expect(turnEndedSentence(session)).toBe('Run finished');
  });
});
