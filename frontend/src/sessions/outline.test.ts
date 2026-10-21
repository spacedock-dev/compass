// @vitest-environment node
import { describe, expect, it } from 'vitest';
import type { Outline, OutlineBlock, OutlineCoverage } from '../api/outline';
import {
  PROMPT_CHARS,
  STAMP_FAILED,
  blockLine,
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
  opening: true,
  partial: false,
  span: { first: 'p1', last: 'c2', entries: 9, fromAt: 1900000000 },
  counts: {
    checks: 3,
    checksFailed: 1,
    checksFixed: 0,
    files: 4,
    agentMessages: 2,
    subagentEntries: 0,
  },
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
  it('draws one block per prompt as short sentences, with no entry numbers and no repeated count', () => {
    const view = outlineView(outline(), { loaded: true, failed: false }, 'Claude Code');
    expect(view.kind).toBe('blocks');
    if (view.kind !== 'blocks') return;
    const [only] = view.blocks;
    expect(only?.prompt).toBe('Add retry with backoff.');
    // A failing check has its own line, so the sentence does not count it a second time.
    expect(only?.line).toBe(
      'The agent replied 2 times, ran 3 checks and wrote 4 files in src/webhook and the project root.',
    );
    expect(only?.failures).toEqual([{ factId: 'c1', title: 'pytest tests/test_webhook.py' }]);
    expect(only?.moreFailures).toBe(0);
    expect(only?.line).not.toMatch(/#|\(\d+\)|messages with|Starts at|Entries/);
    expect(only).not.toHaveProperty('first');
  });

  it('says a failing run that a later pass followed was fixed, and lists no failure for it', () => {
    const fixed = block({
      counts: { ...block().counts, checksFailed: 0, checksFixed: 1 },
      failures: [],
    });
    const line = blockLine(fixed, CLAUDE);
    expect(line).toContain('A check that failed passed on a later run.');
    expect(line).not.toMatch(/failing|still failing/);
    const view = outlineView(outline({ blocks: [fixed] }), { loaded: true, failed: false }, 'x');
    expect(view.kind === 'blocks' && view.blocks[0]?.failures).toEqual([]);
    expect(view.kind === 'blocks' && view.blocks[0]?.moreFailures).toBe(0);
    expect(blockLine(block({ counts: { ...fixed.counts, checksFixed: 2 } }), CLAUDE)).toContain(
      '2 checks that failed passed on a later run.',
    );
  });

  it('names failures not listed, so a bounded list never hides how many are red', () => {
    const view = outlineView(
      outline({
        blocks: [
          block({ counts: { ...block().counts, checksFailed: 5 }, failures: block().failures }),
        ],
      }),
      { loaded: true, failed: false },
      'x',
    );
    expect(view.kind === 'blocks' && view.blocks[0]?.moreFailures).toBe(4);
  });

  it('says what a part wrote even when only some folders are listed', () => {
    const more = block({
      counts: { ...block().counts, files: 7 },
      folders: [{ folder: 'src', files: 3 }],
    });
    expect(blockLine(more, CLAUDE)).toContain('wrote 7 files, mostly in src');
    const single = block({
      counts: { ...block().counts, checks: 0, agentMessages: 0, files: 1 },
      folders: [{ folder: 'tests/adapter/dbt_adapter', files: 1 }],
    });
    expect(blockLine(single, CLAUDE)).toBe('The agent wrote 1 file in tests/adapter/dbt_adapter.');
  });

  it('says so when nothing is recorded under a message, and counts a floor as one', () => {
    const bare = block({
      counts: {
        checks: 0,
        checksFailed: 0,
        checksFixed: 0,
        files: 0,
        agentMessages: 0,
        subagentEntries: 0,
      },
      failures: [],
      folders: [],
    });
    expect(blockLine(bare, CLAUDE)).toBe('No agent work is recorded under this message.');
    expect(blockLine({ ...block(), partial: true }, CLAUDE)).toMatch(
      /Counted only as far as Compass read\.$/,
    );
  });

  it('never counts checks or files, or agent replies, where the harness does not read them', () => {
    expect(blockLine(block(), CODEX)).toBe('');
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

  it('says the outline opens at the first message when the newest window began after it', () => {
    const partial: OutlineCoverage = {
      ...CLAUDE,
      startOffset: 900,
      unread: [{ reason: 'before_window' }],
    };
    expect(coverageNotes(partial, 0, true)).toEqual([
      'Compass read your first message and the newest part of this session. What happened between them is not outlined here.',
    ]);
    const view = outlineView(
      outline({ coverage: partial, blocks: [block(), block({ opening: false, prompt: null })] }),
      { loaded: true, failed: false },
      'x',
    );
    expect(view.kind === 'blocks' && view.notes[0]).toMatch(/read your first message/);
    // The part after the gap has no prompt to name and says where it carries on from.
    expect(view.kind === 'blocks' && view.blocks.map((row) => row.noPrompt)).toEqual([
      'Work before your first message',
      'Work carrying on from earlier in this session',
    ]);
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

  it('trims a long prompt at a word, never inside one', () => {
    const long = `${'word '.repeat(80)}end`;
    const trimmed = trimPrompt(long);
    expect(trimmed.length).toBeLessThanOrEqual(PROMPT_CHARS);
    expect(trimmed.endsWith('word…')).toBe(true);
    const title = `${'Implement the launch grant card. '.repeat(5)}The launch-grant card still says allowed when this dashboard started after Turning`;
    for (const cut of [title, `${title.slice(0, PROMPT_CHARS - 1)} tail words`]) {
      const out = trimPrompt(cut);
      expect(out.endsWith('…')).toBe(true);
      expect(cut.startsWith(out.slice(0, -1))).toBe(true);
      // The character after what was kept is a break, so no word was cut.
      expect(cut.charAt(out.length - 1)).toMatch(/^\s?$/);
      expect(/\S\s*$/.test(out.slice(0, -1))).toBe(true);
    }
    // One word with no break to keep is cut where it stands.
    expect(trimPrompt('x'.repeat(400))).toHaveLength(PROMPT_CHARS);
    expect(trimPrompt('A short prompt.')).toBe('A short prompt.');
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
