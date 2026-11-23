import { expect, it } from 'vitest';
import { worthALookBoard } from '../../test/worthALookBoard';
import { attentionSelectionFor } from './select';

const { generated } = worthALookBoard();
const quiet = { harness: 'claude', sid: 'one', project: 'display', state: 'idle' };
const ended = { ...quiet, ended_at: generated - 100 };
const dirty = { ...ended, dirty: true, changed: 2 };
const loop = { errors: 5 };
const ask = { id: 'question', session_id: quiet.sid, harness: 'claude', question: 'Proceed?' };
const locationOne = {
  ...quiet,
  project_key: 'git:one',
  project_identity_source: 'git common directory',
};
const locationTwo = { ...locationOne, sid: 'two', project_key: 'git:two' };

it('distinguishes an entirely failed read from a successful measured zero', () => {
  const claude = { key: 'claude', discovered: true };
  const failed = { ...claude, error: 'Read failed' };
  const sessions = worthALookBoard().sessions.filter(({ sid }) => sid === 'dirty-end');
  expect(attentionSelectionFor({ sessions: [], harnesses: [claude] })?.counts?.worthALook).toBe(0);
  const unread = attentionSelectionFor({
    sessions: [],
    harnesses: [failed],
    usage: [{ harness: 'claude', state: 'ok', fiveH: { pct: 89 } }],
  });
  expect(unread?.counts).toBeNull();
  expect(unread?.worthALookNotices.map(({ key }) => key)).toEqual(['quota:claude:fiveH']);
  expect(
    attentionSelectionFor({
      sessions,
      harnesses: [{ key: 'codex', discovered: true, error: 'Read failed' }, claude],
    })?.counts?.worthALook,
  ).toBe(1);
});

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
  expect(selection?.worthALookNotices.map(({ primaryKind }) => primaryKind)).toEqual(['quota']);
});

it('keeps a waiting session in the badge once when it also publishes a risk', () => {
  const board = worthALookBoard();
  const gate = board.sessions.find(({ sid }) => sid === 'gate');
  const sessions = board.sessions.map((row) =>
    row === gate ? { ...row, loop: { errors: 4 } } : row,
  );
  const selection = attentionSelectionFor({ ...board, sessions });
  if (!selection) throw new Error('Board selection is absent');
  expect(selection?.counts?.badge).toBe(11);
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
  expect(selection?.counts?.worthALook).toBe(9);
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

it('represents the measured dirty copy in either order', () => {
  for (const sessions of [
    [ended, dirty],
    [dirty, ended],
    [dirty, { ...dirty }],
  ]) {
    const selection = attentionSelectionFor({ generated, sessions });
    expect([...(selection?.worthALook.values() ?? [])]).toEqual([
      'Ended with uncommitted work (2 changed entries)',
    ]);
  }
});

it.each([
  ['an ended row with a stale input state', { ...ended, state: 'needs_input', loop }, true],
  ['a disabled residual request', { ...quiet, state: 'working', loop }, false],
  ['an ended row with clean git', { ...ended, dirty: false, loop }, true],
])('retains the measured loop for %s', (_, session, askEnabled) => {
  const asks = askEnabled ? [] : [ask];
  const selection = attentionSelectionFor({
    generated,
    sessions: [session],
    ask: askEnabled,
    asks,
  });
  expect(selection?.counts).toMatchObject({
    waitingOnYou: 0,
    worthALook: 1,
    readyToWrapUp: 0,
    badge: 1,
  });
  expect([...(selection?.worthALook.values() ?? [])]).toEqual(['Repeated tool failures']);
});

it('ends a long-turn warning when the session ends', () => {
  expect(
    attentionSelectionFor({
      generated,
      sessions: [{ ...ended, state: 'working', turn: { long: true } }],
    })?.counts?.worthALook,
  ).toBe(0);
});

it('recognizes the transcript stop when choosing a reason', () => {
  const selection = attentionSelectionFor({
    generated,
    sessions: [{ ...quiet, dirty: true, turn_end_at: generated - 100 }],
  });
  expect([...(selection?.worthALook.values() ?? [])]).toEqual([
    "Git state was reported without a stop hook. A turn stop appears in Claude Code's transcript",
  ]);
});

it('counts a waiting member of a measured shared-label collision once', () => {
  const selection = attentionSelectionFor({
    sessions: [{ ...locationOne, state: 'needs_input' }, locationTwo],
  });
  expect(selection?.counts).toMatchObject({ waitingOnYou: 1, worthALook: 1, badge: 2 });
  expect([...(selection?.worthALook.keys() ?? [])].map(({ sid }) => sid)).toEqual(['two']);
});

it('keeps one measured location and an unknown location off the session count', () => {
  const selection = attentionSelectionFor({ sessions: [locationOne, { ...quiet, sid: 'two' }] });
  expect(selection?.counts?.worthALook).toBe(0);
  expect(selection?.offCountRisks.map(({ primaryKind }) => primaryKind)).toEqual(['collision']);
});

it('publishes an unowned request only while the request lane is enabled', () => {
  for (const askEnabled of [true, false]) {
    const selection = attentionSelectionFor({ sessions: [], ask: askEnabled, asks: [ask] });
    expect(selection?.offCountRisks.map(({ primaryKind }) => primaryKind)).toEqual(
      askEnabled ? ['ask'] : [],
    );
  }
});

it('bounds the git-only reason to published evidence', () => {
  const selection = attentionSelectionFor({ sessions: [{ ...quiet, dirty: true, changed: 2 }] });
  expect([...(selection?.worthALook.values() ?? [])]).toEqual([
    'Git state was reported without a recorded stop',
  ]);
});

it('retains an independent quiet-launch risk when the git state is clean at end', () => {
  const board = worthALookBoard();
  const launch = board.sessions.find(({ sid }) => sid === 'quiet-launch');
  expect(launch).toBeDefined();
  const selection = attentionSelectionFor({
    generated,
    sessions: [{ ...launch, ended_at: generated - 1, dirty: false }],
  });
  expect(selection?.counts).toMatchObject({ worthALook: 1, readyToWrapUp: 0 });
});

it('retains scoped quota for Worth a look outside the count of session flags', () => {
  const selection = attentionSelectionFor({
    generated,
    sessions: [quiet],
    usage: [{ harness: 'claude', state: 'ok', fiveH: { pct: 89 } }],
  });
  expect(selection?.counts).toMatchObject({ worthALook: 0, badge: 0 });
  expect(selection?.offCountRisks).toEqual([]);
  expect(selection?.worthALookNotices).toMatchObject([
    {
      key: 'quota:claude:fiveH',
      sessions: [],
      signals: [{ detail: { harness: 'claude', scope: 'fiveH', pct: 89 } }],
    },
  ]);
});

it('keeps both measured checkout members together in a board-scoped notice', () => {
  const first = { ...locationOne, state: 'working', checkout_key: 'checkout:one' };
  const second = { ...first, sid: 'two' };
  const selection = attentionSelectionFor({ sessions: [first, second] });
  expect(selection?.counts).toMatchObject({ worthALook: 0, badge: 0 });
  expect(selection?.worthALookNotices).toEqual([]);
  expect(selection?.offCountRisks).toMatchObject([
    { primaryKind: 'checkout', sessions: [first, second] },
  ]);
});

it('flags both measured members of a shared-label collision even if one ended with clean git', () => {
  const selection = attentionSelectionFor({
    sessions: [{ ...locationOne, ended_at: generated - 1, dirty: false }, locationTwo],
  });
  expect(selection?.counts).toMatchObject({ worthALook: 2, readyToWrapUp: 0 });
  expect([...(selection?.worthALook.values() ?? [])]).toEqual([
    'Shared project label',
    'Shared project label',
  ]);
});
