import { describe, expect, it } from 'vitest';
import type { PayloadData } from '../api/types';
import { findSession, historyResetReason, sessionTitle } from './derive';

const body = (value: unknown): PayloadData => value as PayloadData;

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
    expect(sessionTitle(null)).toBe('Title not published');
    expect(sessionTitle(findSession(sessions, '', 'claude', 'bare'))).toBe('Title not published');
    expect(sessionTitle(findSession(sessions, 'alpha', 'claude', 'untitled'))).toBe(
      'Title not published',
    );
    expect(sessionTitle(findSession(sessions, 'alpha', 'claude', 'shared'))).toBe('Claude title');
  });

  it('does not call a command opener an unpublished title', () => {
    const opened = { harness: 'claude', sid: 'c', first_prompt_control: true } as never;
    expect(sessionTitle(opened)).toBe('No name: the session opened with a command');
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
