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

describe('an open question after a turn', () => {
  it('keeps the current activity available for the owned question after either kind of finish', () => {
    const session = { harness: 'codex', state: 'idle', finished_at: 9400, turn_end_at: 9400 };
    expect(turnEndedSentence(session, 10000, true)).toBeNull();
    expect(turnEndedSentence({ ...session, headless: true }, 10000, true)).toBeNull();
  });
});

describe('metadata while a question is open', () => {
  it('keeps other state detail while a question is open', () => {
    expect(
      sessionMeta({ state: 'working', state_detail: 'generating' }, 10000, null, null, false, true),
    ).toBe('generating');
  });
  it('keeps completion sentences out while preserving the session age and entry count', () => {
    const session = {
      harness: 'codex',
      state: 'idle',
      started_at: 6400,
      finished_at: 9400,
      turn_end_at: 9400,
      state_detail: 'run finished',
    };
    for (const headless of [false, true]) {
      const meta = sessionMeta({ ...session, headless }, 10000, 3, null, false, true);
      expect(meta).not.toMatch(/turn ended|run finished/i);
      expect(meta).toContain('session started 1h 0m ago');
      expect(meta).toContain('3 entries');
      expect(sessionMeta({ ...session, headless }, 10000, 3)).toMatch(/Turn ended|Run finished/);
    }
  });
});
