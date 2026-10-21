import { describe, expect, it } from 'vitest';
import type { PayloadData } from '../api/types';
import { createBoardStore } from '../store/board';
import {
  findSession,
  historyResetReason,
  selectHeaderCounts,
  sessionTitle,
  TITLE_NOT_PUBLISHED,
} from './derive';

const body = (value: unknown): PayloadData => value as PayloadData;

function counts(data: unknown) {
  const store = createBoardStore({ now: () => 1 });
  if (data !== undefined) store.acceptData(body(data), '');
  return selectHeaderCounts(store.getSnapshot());
}

describe('the header counts are read from the rows the page renders', () => {
  it('says nothing is known before the first board, and when the payload carried no sessions at all', () => {
    expect(counts(undefined)).toEqual({ state: 'unread' });
    expect(counts({ generated: 1 })).toEqual({ state: 'absent' });
  });

  it('reads an empty collection as measured zeros, which is a different fact from an absent one', () => {
    expect(counts({ sessions: [] })).toEqual({
      state: 'measured',
      gates: 0,
      running: 0,
      subagents: 0,
    });
  });

  it('counts a session as running only when it is working and its liveness is exactly true', () => {
    const rows = [
      { harness: 'claude', sid: 'live', state: 'working', active: true },
      { harness: 'claude', sid: 'unmeasured', state: 'working' },
      { harness: 'claude', sid: 'not-active', state: 'working', active: false },
      { harness: 'claude', sid: 'idle', state: 'idle', active: true },
      { harness: 'claude', sid: 'blocked', state: 'needs_input', active: true },
    ];
    expect(counts({ sessions: rows })).toMatchObject({ running: 1, gates: 1 });
  });

  it('does not count an ended session as running or blocked, whatever its last state said', () => {
    const rows = [
      { harness: 'claude', sid: 'a', state: 'working', active: true, ended_at: 1700 },
      { harness: 'claude', sid: 'b', state: 'needs_input', ended_at: 1700 },
      { harness: 'claude', sid: 'c', state: 'working', active: true, ended_at: 0 },
    ];
    expect(counts({ sessions: rows })).toMatchObject({ running: 1, gates: 0 });
  });

  it('counts every observed subagent, including those of ended sessions, and none from a non-list', () => {
    const rows = [
      { harness: 'claude', sid: 'a', state: 'working', active: true, subagents: [{}, {}] },
      { harness: 'claude', sid: 'b', state: 'idle', ended_at: 5, subagents: [{}] },
      { harness: 'claude', sid: 'c', state: 'idle', subagents: 'three' },
      { harness: 'claude', sid: 'd', state: 'idle' },
    ];
    expect(counts({ sessions: rows })).toMatchObject({ subagents: 3 });
  });

  describe('exact requests join the block count beside the state that reports one', () => {
    const rows = [
      { harness: 'claude', sid: 'one', state: 'idle' },
      { harness: 'codex', sid: 'one', state: 'needs_input' },
      { harness: 'claude', sid: 'two', state: 'idle' },
    ];

    it('counts a session holding an exact request even though its state says idle', () => {
      const asks = [{ id: 'a', harness: 'claude', session_id: 'one', question: 'Approve?' }];
      expect(counts({ ask: true, asks, sessions: rows })).toMatchObject({ gates: 2 });
    });

    it('counts a session once however many reasons it has to be counted', () => {
      const asks = [
        { id: 'a', harness: 'codex', session_id: 'one', question: 'Approve?' },
        { id: 'b', harness: 'codex', session_id: 'one', question: 'Choose?' },
      ];
      expect(counts({ ask: true, asks, sessions: rows })).toMatchObject({ gates: 1 });
    });

    it('ignores requests while the board says it publishes none', () => {
      const asks = [{ id: 'a', harness: 'claude', session_id: 'one', question: 'Approve?' }];
      expect(counts({ ask: false, asks, sessions: rows })).toMatchObject({ gates: 1 });
      expect(counts({ asks, sessions: rows })).toMatchObject({ gates: 1 });
    });

    it('ignores a blank question and a request whose owner is not exactly one session', () => {
      const blank = [{ id: 'a', harness: 'claude', session_id: 'one', question: '   ' }];
      expect(counts({ ask: true, asks: blank, sessions: rows })).toMatchObject({ gates: 1 });
      // No harness and a sid two harnesses carry: the owner is ambiguous, so nothing is attributed.
      const ambiguous = [{ id: 'a', session_id: 'one', question: 'Approve?' }];
      expect(counts({ ask: true, asks: ambiguous, sessions: rows })).toMatchObject({ gates: 1 });
      const unknown = [{ id: 'a', harness: 'claude', session_id: 'nobody', question: 'Approve?' }];
      expect(counts({ ask: true, asks: unknown, sessions: rows })).toMatchObject({ gates: 1 });
      const noSid = [{ id: 'a', harness: 'claude', question: 'Approve?' }];
      expect(counts({ ask: true, asks: noSid, sessions: rows })).toMatchObject({ gates: 1 });
    });

    it('attributes a harness-less request to the one session carrying that sid', () => {
      const asks = [{ id: 'a', session_id: 'two', question: 'Approve?' }];
      expect(counts({ ask: true, asks, sessions: rows })).toMatchObject({ gates: 2 });
    });
  });

  it('returns the same object while the accepted body is unchanged', () => {
    const store = createBoardStore({ now: () => 1 });
    store.acceptData(body({ sessions: [{ harness: 'claude', sid: 'a' }] }), '');
    const first = selectHeaderCounts(store.getSnapshot());
    store.setManualRefreshing(true);
    expect(selectHeaderCounts(store.getSnapshot())).toBe(first);
  });
});

describe('finding the one session a route names', () => {
  const sessions = body({
    sessions: [
      { harness: 'claude', sid: 'shared', project: 'alpha', title: 'Claude title' },
      { harness: 'codex', sid: 'shared', project: 'alpha', title: 'Codex title' },
      { harness: 'claude', sid: 'bare', project: '', title: '  ' },
      { harness: 'claude', sid: 'untitled', project: 'alpha' },
    ],
  });

  it('keeps the same sid under two harnesses apart', () => {
    expect(findSession(sessions, 'alpha', 'claude', 'shared')?.title).toBe('Claude title');
    expect(findSession(sessions, 'alpha', 'codex', 'shared')?.title).toBe('Codex title');
  });

  it('refuses the released id-only form when it would be ambiguous, rather than choosing an owner', () => {
    expect(findSession(sessions, 'alpha', undefined, 'shared')).toBeNull();
    expect(findSession(sessions, 'alpha', undefined, 'untitled')?.sid).toBe('untitled');
  });

  it('matches an empty project exactly and never a different one', () => {
    expect(findSession(sessions, '', 'claude', 'bare')?.sid).toBe('bare');
    expect(findSession(sessions, 'alpha', 'claude', 'bare')).toBeNull();
  });

  it('finds nothing in a board that has not loaded', () => {
    expect(findSession(null, 'alpha', 'claude', 'shared')).toBeNull();
  });

  it('states an absent title in words instead of leaving it blank', () => {
    expect(TITLE_NOT_PUBLISHED).toBe('Title not published');
    expect(sessionTitle(findSession(sessions, '', 'claude', 'bare'))).toBe(TITLE_NOT_PUBLISHED);
    expect(sessionTitle(findSession(sessions, 'alpha', 'claude', 'untitled'))).toBe(
      TITLE_NOT_PUBLISHED,
    );
    expect(sessionTitle(findSession(sessions, 'alpha', 'claude', 'shared'))).toBe('Claude title');
  });

  it('stands in for an identifier-only title with the first prompt, as the session heading does', () => {
    const keyed = {
      harness: 'claude',
      sid: 'k1',
      project: 'alpha',
      title: 'DRC-4929',
      first_prompt: 'Fix the flaky http test',
    } as never;
    expect(sessionTitle(keyed)).toBe('Fix the flaky http test');
    expect(sessionTitle({ ...(keyed as object), title: 'gpt-4' } as never)).toBe('gpt-4');
  });
});

describe('a history reset is one of two literals this build knows', () => {
  it('names the reason, and treats anything else as no reset', () => {
    expect(historyResetReason(body({ history_reset: 'unreadable' }))).toBe('unreadable');
    expect(historyResetReason(body({ history_reset: 'version' }))).toBe('version');
    expect(historyResetReason(body({ history_reset: '<img src=x onerror=alert(1)>' }))).toBeNull();
    expect(historyResetReason(body({ history_reset: 'toString' }))).toBeNull();
    expect(historyResetReason(body({ history_reset: 3 }))).toBeNull();
    expect(historyResetReason(body({}))).toBeNull();
    expect(historyResetReason(null)).toBeNull();
  });
});
