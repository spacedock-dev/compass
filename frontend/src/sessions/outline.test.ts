// @vitest-environment node
import { describe, expect, it } from 'vitest';
import type { Outline, OutlineBlock, OutlineCoverage } from '../api/outline';
import {
  PROMPT_CHARS,
  STAMP_FAILED,
  blockCounts,
  coverageNotes,
  noOutline,
  outlineStamp,
  outlineView,
  trimPrompt,
} from './outline';

const CLAUDE: OutlineCoverage = {
  startOffset: 0,
  agentReplies: 'read',
  checksAndFiles: 'read',
  unread: [],
};
const CODEX: OutlineCoverage = {
  ...CLAUDE,
  agentReplies: 'not_read',
  checksAndFiles: 'not_admitted',
};

const block = (over: Partial<OutlineBlock> = {}): OutlineBlock => ({
  prompt: { factId: 'p1', title: 'Add retry with backoff.', at: 1900000000 },
  span: { first: 'p1', last: 'c2', entries: 9, fromAt: 1900000000 },
  counts: { checks: 3, checksFailed: 1, files: 4, agentMessages: 2, subagentEntries: 0 },
  failures: [{ factId: 'c1', title: 'pytest tests/test_webhook.py' }],
  folders: [
    { folder: 'src/webhook', files: 3 },
    { folder: '', files: 1 },
  ],
  ...over,
});

const outline = (over: Partial<Outline> = {}): Outline => ({
  state: 'ok',
  reason: null,
  coverage: CLAUDE,
  blocks: [block()],
  moreBlocks: 0,
  ...over,
});

describe('the outline card model', () => {
  it('draws one block per prompt with its counts, failures and span', () => {
    const view = outlineView(outline(), { loaded: true, failed: false }, 'Claude Code');
    expect(view.kind).toBe('blocks');
    if (view.kind !== 'blocks') return;
    const [only] = view.blocks;
    expect(only?.prompt).toBe('Add retry with backoff.');
    expect(only?.counts).toEqual([
      // The span says "#1 to #2" in message numbers: the count names the messages and what sits under them.
      '2 messages with 7 checks and files under them',
      '2 agent replies',
      '3 checks run, 1 failed as the tool reported',
      '4 files written in src/webhook (3), no folder (1)',
    ]);
    expect(only?.failures).toEqual([{ factId: 'c1', title: 'pytest tests/test_webhook.py' }]);
    expect([only?.first, only?.last]).toEqual(['p1', 'c2']);
  });

  it('never counts checks or files, or agent replies, where the harness does not read them', () => {
    expect(blockCounts(block(), CODEX)).toEqual(['9 entries']);
    expect(coverageNotes(CODEX, 0)).toEqual([
      'Only your messages are read for this harness: the outline has no agent replies, checks or files.',
    ]);
  });

  it('says where the read stopped short, and how many earlier parts are not shown', () => {
    const partial: OutlineCoverage = {
      ...CLAUDE,
      startOffset: 900,
      unread: [{ reason: 'before_window' }, { reason: 'time' }],
    };
    const notes = coverageNotes(partial, 3);
    expect(notes).toHaveLength(3);
    expect(notes[0]).toMatch(/starts partway/);
    expect(notes[1]).toMatch(/newest entries may be missing/);
    expect(notes[2]).toBe(
      '3 earlier parts of this session are not shown here. Full activity lists every entry.',
    );
  });

  it('does not say the outline starts partway for a read from the start that stopped at its limit', () => {
    const stopped: OutlineCoverage = { ...CLAUDE, unread: [{ reason: 'time' }] };
    expect(coverageNotes(stopped, 0)).toEqual([
      'Compass stopped reading at its limit, so the newest entries may be missing. It reads again on the next update.',
    ]);
    expect(coverageNotes({ ...CLAUDE, startOffset: 512 }, 0)[0]).toMatch(/starts partway/);
  });

  it('says why there is no outline in the reader’s words', () => {
    const pi = outline({ state: 'unsupported', reason: 'no_paged_record', blocks: [] });
    expect(noOutline(pi, 'Pi')).toMatch(/^Pi keeps no record Compass can page through/);
    const view = outlineView(pi, { loaded: true, failed: false }, 'Pi');
    expect(view).toEqual({ kind: 'none', sentence: noOutline(pi, 'Pi') });
    expect(noOutline(outline({ state: 'stale' }), 'x')).toMatch(
      /changed while Compass was reading/,
    );
    expect(
      noOutline(outline({ state: 'unavailable', reason: 'session_not_matched' }), 'x'),
    ).toMatch(/exactly one session/);
  });

  it('is loading until the focused answer lands, and failed only when nothing is held', () => {
    expect(outlineView(null, { loaded: false, failed: false }, 'x')).toEqual({ kind: 'loading' });
    expect(outlineView(null, { loaded: false, failed: true }, 'x')).toEqual({ kind: 'failed' });
    expect(outlineView(null, { loaded: true, failed: false }, 'x')).toEqual({ kind: 'absent' });
  });

  it('trims a long prompt to a glance and labels work before the first prompt', () => {
    const long = `${'word '.repeat(80)}end`;
    expect(trimPrompt(long)).toHaveLength(PROMPT_CHARS);
    expect(trimPrompt(long).endsWith('…')).toBe(true);
    const view = outlineView(
      outline({ blocks: [block({ prompt: null })] }),
      { loaded: true, failed: false },
      'x',
    );
    expect(view.kind === 'blocks' && view.blocks[0]?.prompt).toBeNull();
  });

  it('stamps when the board was read and whether the session is still running', () => {
    expect(outlineStamp(null, true)).toBe('still running');
    expect(outlineStamp(null, false)).toBe('');
    expect(outlineStamp(1900000000, true)).toMatch(/^updated \d\d:\d\d · still running$/);
    // A failed refresh is not dated as an update.
    expect(outlineStamp(1900000000, false, true)).toBe(STAMP_FAILED);
  });
});
