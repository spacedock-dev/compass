import { describe, expect, it } from 'vitest';
import { parseFocusedSummary, parseGrant, parseJob, stampModel } from '../api/summary';
import {
  GAP_LINES,
  askedText,
  bulletWords,
  SUMMARY_REASONS,
  WITHHELD_LINES,
  autoStartDue,
  outOfDateLine,
  placeDeparture,
  positionOf,
  reasonSentence,
  saidText,
  summaryStamp,
} from './summary';

/* The tokens the summary contract publishes (docs/design-session-summary.md, "Job and grant contract" and
   "Bounds, spend and gaps"), each of which the card must say in the reader's words rather than as a token. */
const GRANT_REASONS = [
  'daily-cap',
  'summaries-off',
  'readings-off',
  'run-disabled',
  'store-unavailable',
];
const START_REFUSALS = [
  'session-running',
  'summary-exists',
  'session-unavailable',
  'in-flight',
  'no-summary',
  'summary-changed',
  'source-unavailable',
  'job-unrecorded',
  'no-thread',
  'harness_not_supported',
  'invalid_bounds',
  'planned_calls',
  'planned_bytes',
  'planned_seconds',
  'output_bound_full',
  'truncated',
  'replaced',
  'changed_earlier',
  'late_evidence',
  'span_mismatch',
  'unknown_change',
];
const JOB_REASONS = [
  'cancelled',
  'deleted',
  'summaries-off',
  'grant-changed',
  'destination-changed',
  'daily-cap',
  'run-disabled',
  'store-unavailable',
  'stopping',
  'model-unavailable',
  'interrupted',
  'job-failed',
  'store-refused',
  'store-unwritable',
  'gaps',
  'bytes',
  'source_incomplete',
  'no_entries',
  'ceiling',
  'refused',
  'stopped',
  'output_bound_too_small',
];
const GAP_REASONS = [
  'before_window',
  'no_valid_reply',
  'no_output',
  'refused',
  'stopped',
  'ceiling',
  'bytes',
];
const WITHHELD_REASONS = ['completion_claim', 'no_citation', 'shape_fault', 'too_long_cut'];

const COMPLETION = /\b(done|fixed|works|working|verified|complete[ds]?|succeeded|green)\b/i;

describe('every published token has its sentence', () => {
  it.each([...GRANT_REASONS, ...START_REFUSALS, ...JOB_REASONS])('%s', (token) => {
    expect(SUMMARY_REASONS[token]).toBeDefined();
    const sentence = reasonSentence(token, { grant: null, harness: 'Codex', largest: null });
    if (/[-_]/.test(token)) expect(sentence).not.toContain(token);
    expect(sentence).not.toMatch(COMPLETION);
  });
  it.each(GAP_REASONS)('gap %s', (token) => {
    expect(GAP_LINES[token]).toBeDefined();
  });
  it.each(WITHHELD_REASONS)('withheld %s', (token) => {
    expect(WITHHELD_LINES[token]).toBeDefined();
  });
});

describe('the parsers', () => {
  it('reads a grant and refuses a block without consent', () => {
    expect(parseGrant({ consent: true, reason: '', limit: 200 })?.limit).toBe(200);
    expect(parseGrant({ reason: '' })).toBeNull();
    expect(parseGrant(null)).toBeNull();
  });
  it('reads a job and refuses an unknown state', () => {
    expect(parseJob({ id: 'j', state: 'running', part: 2, parts: 5 })?.part).toBe(2);
    expect(parseJob({ id: 'j', state: 'exploded' })).toBeNull();
  });
  it('keeps a withheld string in its place, with no text', () => {
    const focused = parseFocusedSummary({
      sources: {
        summary: {
          exists: true,
          lede: { withheld: true, reason: 'completion_claim', cites: ['a'] },
          blocks: [
            {
              first: 'a',
              last: 'b',
              entries: 2,
              phases: [
                {
                  title: { withheld: true, reason: 'completion_claim' },
                  bullets: [{ text: 'x', kind: 'nonsense', cites: ['a', 3] }],
                },
              ],
            },
            { first: 'c', last: 'd', entries: 1, gap: true, reason: 'no_output', phases: [{}] },
          ],
          made_at: 10,
          model_stamp: 'claude:claude-sonnet-5-5:abc',
        },
      },
    });
    expect(focused?.summary?.lede).toEqual({ withheld: 'completion_claim' });
    const [summarized, gap] = focused?.summary?.blocks ?? [];
    expect(summarized?.phases[0]?.title).toEqual({ withheld: 'completion_claim' });
    // An unknown kind is never drawn as plain work: its text is withheld. A non-string citation is dropped.
    expect(summarized?.phases[0]?.bullets[0]).toMatchObject({
      text: { withheld: 'shape_fault' },
      cites: ['a'],
    });
    expect(gap).toMatchObject({ gap: 'no_output', phases: [] });
  });
  it('withholds a string holding a tick, even one the server admitted', () => {
    const focused = parseFocusedSummary({
      sources: {
        summary: {
          exists: true,
          lede: { text: 'Retry handler \u2705', cites: ['a'] },
          blocks: [
            {
              first: 'a',
              last: 'a',
              entries: 1,
              phases: [
                {
                  title: 'Retry \u2714\ufe0f',
                  bullets: [{ text: 'Added the retry handler \u2713', kind: 'did', cites: ['a'] }],
                },
              ],
            },
          ],
        },
      },
    });
    const phase = focused?.summary?.blocks[0]?.phases[0];
    expect(focused?.summary?.lede).toEqual({ withheld: 'completion_claim' });
    expect(phase?.title).toEqual({ withheld: 'completion_claim' });
    expect(phase?.bullets[0]?.text).toEqual({ withheld: 'completion_claim' });
  });
  it('reads an absent and an unavailable answer, and none', () => {
    expect(
      parseFocusedSummary({ sources: { summary: { state: 'absent', exists: false } } })?.state,
    ).toBe('absent');
    expect(
      parseFocusedSummary({ sources: { summary: { state: 'unavailable', exists: false } } })?.state,
    ).toBe('unavailable');
    expect(parseFocusedSummary({ sources: {} })).toBeNull();
  });
  it('names the model from the stamp', () => {
    expect(stampModel('claude:claude-sonnet-5-5:abc')).toBe('claude-sonnet-5-5');
    expect(stampModel('claude::abc')).toBe('');
    expect(stampModel('odd')).toBe('');
  });
});

describe('what the card says', () => {
  it('opens a said bullet with Said, once', () => {
    expect(saidText('Said the parser is ready.')).toBe('Said the parser is ready.');
    expect(saidText('The parser is ready.')).toBe('Said: The parser is ready.');
    expect(saidText('The agent said it left the tests alone.')).toBe(
      'Said it left the tests alone.',
    );
  });
  it('names the person on an asked bullet, whatever verb it opens with', () => {
    expect(askedText('Asked for retry with backoff.')).toBe('You asked for retry with backoff.');
    expect(askedText('The person asked to keep the diff small.')).toBe(
      'You asked to keep the diff small.',
    );
    expect(askedText('The user confirmed the parser is fixed.')).toBe(
      'You confirmed the parser is fixed.',
    );
    expect(askedText('Confirmed the parser is fixed.')).toBe(
      'You said: Confirmed the parser is fixed.',
    );
    expect(askedText('You asked for tests.')).toBe('You asked for tests.');
  });
  it('words a failed check in text, not only in colour', () => {
    expect(bulletWords('failed', 'Ran pytest.')).toBe('Failed as the tool reported: Ran pytest.');
    expect(bulletWords('did', 'Ran pytest.')).toBe('Ran pytest.');
    expect(bulletWords('said', 'Ran pytest.')).toBe('Said: Ran pytest.');
  });
  const base = parseFocusedSummary({
    sources: {
      summary: {
        exists: true,
        made_at: 1900000000,
        model_stamp: 'claude:m:x',
        blocks: [
          {
            first: 'p1',
            last: 'c2',
            entries: 4,
            phases: [
              { title: 'Adding retry', bullets: [{ text: 'x', kind: 'did', cites: ['p1', 'c1'] }] },
            ],
          },
          {
            first: 'p2',
            last: 'a2',
            entries: 2,
            phases: [{ title: 'Second', bullets: [{ text: 'y', kind: 'said', cites: ['a2'] }] }],
          },
        ],
      },
    },
  })?.summary;
  it('stamps a finished and a running summary', () => {
    if (!base) throw new Error('no summary');
    expect(summaryStamp(base, false, 'm')).toMatch(/^m · summarized at \d\d:\d\d$/);
    expect(summaryStamp(base, true, '')).toMatch(/^updated \d\d:\d\d · still running$/);
  });
  it('says what is out of date and offers the one control for it', () => {
    if (!base) throw new Error('no summary');
    const context = { grant: null, harness: 'Claude Code', largest: null };
    expect(
      outOfDateLine(
        {
          ...base,
          outOfDate: {
            kind: 'appended',
            reason: null,
            affectedBlocks: [],
            newEntries: 12,
            action: 'update',
          },
        },
        context,
      ),
    ).toEqual({
      sentence: expect.stringMatching(/^12 new entries since \d\d:\d\d\.$/),
      action: 'update',
    });
    expect(
      outOfDateLine(
        {
          ...base,
          outOfDate: {
            kind: 'truncated',
            reason: 'truncated',
            affectedBlocks: [1],
            newEntries: 0,
            action: 'summarize_again',
          },
        },
        context,
      ),
    ).toEqual({
      sentence:
        'The session’s record got shorter after this summary was made. It affects the part “Second”.',
      action: 'rerun',
    });
    expect(
      outOfDateLine(
        {
          ...base,
          outOfDate: {
            kind: 'unchanged',
            reason: null,
            affectedBlocks: [],
            newEntries: 0,
            action: null,
          },
        },
        context,
      ),
    ).toBeNull();
  });

  const numbers = new Map([
    ['p1', '1'],
    ['a1', '2'],
    ['c1', '2.1'],
    ['c2', '2.2'],
    ['p2', '3'],
    ['a2', '4'],
    ['c3', '4.1'],
  ]);
  it('orders a sub-number between its neighbours', () => {
    expect(positionOf('2.1')).toEqual([2, 1]);
    expect(positionOf('x')).toBeNull();
  });
  it('places a departure in a phase, after, between or nowhere', () => {
    if (!base) throw new Error('no summary');
    expect(placeDeparture(base, ['c1'], numbers)).toEqual({ where: 'phase', phases: ['0:0'] });
    expect(placeDeparture(base, ['c3'], numbers).where).toBe('after');
    expect(placeDeparture(base, ['c2'], numbers).where).toBe('between');
    expect(placeDeparture(base, ['zz'], numbers).where).toBe('unplaced');
  });
  it('says only what it can stand behind when the page cannot number a summary citation', () => {
    if (!base) throw new Error('no summary');
    // The source's id for a check is not the record's, so the first phase's span is known only in part.
    const unmatched = {
      ...base,
      blocks: base.blocks.map((block, b) =>
        b === 0
          ? {
              ...block,
              last: 'source-check',
              phases: block.phases.map((phase) => ({
                ...phase,
                bullets: phase.bullets.map((row) => ({ ...row, cites: ['p1', 'source-check'] })),
              })),
            }
          : block,
      ),
    };
    expect(placeDeparture(unmatched, ['c2'], numbers).where).toBe('unplaced');
    expect(placeDeparture(unmatched, ['c3'], numbers).where).toBe('unplaced');
    expect(placeDeparture(unmatched, ['a2'], numbers)).toEqual({ where: 'phase', phases: ['1:0'] });
  });
});

describe('the open of a finished session', () => {
  const grant = parseGrant({ consent: true, reason: '' });
  const absent = parseFocusedSummary({
    sources: { summary: { state: 'absent', exists: false, job: null } },
  });
  const due = (over: Partial<Parameters<typeof autoStartDue>[0]> = {}) =>
    autoStartDue({
      grant,
      focused: absent,
      harness: 'claude',
      ended: true,
      sample: false,
      ...over,
    });
  it('is due only for a finished Claude Code session with no summary, no job and summaries on', () => {
    expect(due()).toBe(true);
    expect(due({ ended: false })).toBe(false);
    expect(due({ harness: 'codex' })).toBe(false);
    expect(due({ sample: true })).toBe(false);
    expect(due({ grant: parseGrant({ consent: false, off: true, reason: 'summaries-off' }) })).toBe(
      false,
    );
    expect(due({ grant: parseGrant({ consent: true, reason: 'daily-cap' }) })).toBe(false);
    expect(due({ grant: null })).toBe(false);
    expect(
      due({
        focused: parseFocusedSummary({
          sources: {
            summary: { state: 'absent', exists: false, job: { id: 'j', state: 'refused' } },
          },
        }),
      }),
    ).toBe(false);
    expect(
      due({
        focused: parseFocusedSummary({
          sources: { summary: { state: 'unavailable', exists: false } },
        }),
      }),
    ).toBe(false);
    expect(due({ focused: null })).toBe(false);
  });
});
