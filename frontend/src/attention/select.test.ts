import { expect, it } from 'vitest';
import { worthALookBoard } from '../../test/worthALookBoard';
import { attentionSelectionFor } from './select';

it('distinguishes an unread board, an absent collection and a measured zero', () => {
  const body = { sessions: [] };
  expect(attentionSelectionFor(null)).toBeNull();
  expect(attentionSelectionFor({})).toBeNull();
  const empty = attentionSelectionFor(body);
  expect(empty?.counts).toEqual({
    waitingOnYou: 0,
    worthALook: 0,
    readyToWrapUp: 0,
    working: 0,
    badge: 0,
  });
  expect(attentionSelectionFor(body)).toBe(empty);
  expect(attentionSelectionFor({ ...body })).not.toBe(empty);
});

it('counts a reported block with an exact request once and flags only the ruled session evidence', () => {
  const board = worthALookBoard();
  const selection = attentionSelectionFor(board);
  if (!selection) throw new Error('Board selection is absent');
  expect(selection?.waitingOnYou.map(({ sid }) => sid)).toEqual(['gate', 'request']);
  expect(selection?.readyToWrapUp.map(({ sid }) => sid)).toEqual(['clean-end']);
  expect([...selection.worthALook.keys()].map(({ sid }) => sid).sort()).toEqual([
    'dirty-end',
    'dirty-one-entry',
    'dirty-unknown-count',
    'disagreement',
    'long-turn',
    'loop',
    'quiet-launch',
    'shared-one',
    'shared-two',
  ]);
  expect(selection?.counts).toEqual({
    waitingOnYou: 2,
    worthALook: 9,
    readyToWrapUp: 1,
    working: 2,
    badge: 11,
  });
  expect(selection?.offCountRisks.map(({ primaryKind }) => primaryKind)).toEqual(['quota']);
});

it('keeps a waiting session in the badge once when it also publishes a risk', () => {
  const board = worthALookBoard();
  const gate = board.sessions.find(({ sid }) => sid === 'gate');
  const sessions = board.sessions.map((row) =>
    row === gate ? { ...row, loop: { errors: 4 } } : row,
  );
  const selection = attentionSelectionFor({ ...board, sessions });
  if (!selection) throw new Error('Board selection is absent');
  expect(selection?.counts.badge).toBe(11);
  expect([...selection.worthALook.keys()].map(({ sid }) => sid)).not.toContain('gate');
  const withoutExactRequest = attentionSelectionFor({
    ...board,
    sessions,
    asks: board.asks.filter(({ session_id }) => session_id !== 'gate'),
  });
  expect(withoutExactRequest?.waitingOnYou.map(({ sid }) => sid)).toEqual(['gate', 'request']);
});

it('keeps measurement gaps off the session count', () => {
  const board = worthALookBoard();
  const sessions = [
    ...board.sessions,
    {
      harness: 'claude',
      sid: 'shared-unknown',
      project: 'shared',
      state: 'idle',
    },
    {
      harness: 'claude',
      sid: 'ended-unmeasured',
      project: 'old',
      ended_at: board.generated - 1,
      changed: 0,
    },
  ];
  const selection = attentionSelectionFor({ ...board, sessions });
  expect(selection?.counts.worthALook).toBe(9);
});

it('describes the recorded git entries and handles an unpublished count', () => {
  const selection = attentionSelectionFor(worthALookBoard());
  if (!selection) throw new Error('Board selection is absent');
  const reasons = new Map([...selection.worthALook].map(([{ sid }, reason]) => [sid, reason]));
  expect(reasons.get('dirty-end')).toBe('Ended with uncommitted work (2 changed entries)');
  expect(reasons.get('dirty-one-entry')).toBe('Ended with uncommitted work (1 changed entry)');
  expect(reasons.get('dirty-unknown-count')).toBe('Ended with uncommitted work');
  expect(reasons.get('disagreement')).toBe(
    'A stop was recorded while the session still reported activity',
  );
  expect([...reasons.values()].join(' ')).not.toMatch(/\b(?:files?|unsaved|lost)\b/i);
});
