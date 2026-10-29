import { describe, expect, it } from 'vitest';
import { parseFocusedSummary, parseGrant, parseJob, stampModel } from '../api/summary';
import {
  GAP_LINES,
  readSize,
  askedText,
  hiddenKey,
  hiddenSentence,
  isTestFailure,
  ledeWords,
  bulletWords,
  SUMMARY_REASONS,
  WITHHELD_LINES,
  autoStartDue,
  outOfDateLine,
  placeDeparture,
  positionOf,
  recordPositions,
  reasonSentence,
  saidText,
  SUMMARY_NOT_CLAUDE,
  SUMMARY_OFF,
  unlinkedSentence,
  withheldSentence,
  withheldTitle,
  WITHHELD_TITLES,
  summaryStamp,
} from './summary';

/* The tokens the summary contract publishes (docs/design-session-summary.md, "Job and grant contract" and
   "Bounds, spend and gaps"), each of which the card must say in the reader's words rather than as a token. */
const GRANT_REASONS = [
  'daily-cap',
  'summaries-off',
  'model-calls-paused',
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
  it('withholds every tick the server withholds', () => {
    // The server's set, session_summary._CHECK_GLYPH; a copy here that drifts lets a stored tick through.
    const ticks = [
      '\u221a',
      '\u2611',
      '\u2705',
      '\u2713',
      '\u2714',
      '\u{10102}',
      '\u{1f5f8}',
      '\u{1f5f9}',
      '\u{1fbb1}',
    ];
    for (const tick of ticks) {
      const focused = parseFocusedSummary({
        sources: {
          summary: {
            exists: true,
            lede: { text: `Retry handler ${tick}`, cites: ['a'] },
            blocks: [],
          },
        },
      });
      expect(focused?.summary?.lede).toEqual({ withheld: 'completion_claim' });
    }
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
  it('names the agent as the speaker of a said bullet, with no Said label', () => {
    // A line that already names its speaker is drawn as written: "Said:" was a kind marker leaking into the text.
    expect(saidText('The agent said it left the tests alone.')).toBe(
      'The agent said it left the tests alone.',
    );
    expect(saidText('The agent also said it would move the chart.')).toBe(
      'The agent also said it would move the chart.',
    );
    // A stored line with no named speaker gets one, so it never reads as the summary's own claim.
    expect(saidText('The parser is ready.')).toBe('The agent said: The parser is ready.');
    expect(saidText('Said the parser is ready.')).toBe('The agent said: the parser is ready.');
    expect(saidText('Said: the parser is ready.')).toBe('The agent said: the parser is ready.');
    expect(saidText('The agent said that the tooltip formats dates.')).toBe(
      'The agent said that the tooltip formats dates.',
    );
    for (const line of [
      saidText('The agent said it left the tests alone.'),
      saidText('The parser is ready.'),
      bulletWords('said', 'Ran pytest.'),
    ])
      expect(line).not.toMatch(/^Said:/);
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
  it('never draws a doubled subject: a line that names its subject takes no kind prefix', () => {
    // Seen live on a freshly written summary: the model names its subject, and the page added "The agent said:" or
    // "You said:" in front, and called the person "the person".
    const drawn = [
      bulletWords(
        'said',
        'The agent read the gate and its tests, then installed the pinned dependencies.',
      ),
      bulletWords('said', 'The agent opened draft PR #638 and said the gate was waiting.'),
      bulletWords('asked', 'The person redirected the agent to the goal: gate and tests only.'),
      bulletWords('asked', 'The person chose 54 named exceptions for the duplicates.'),
      bulletWords('did', 'The person chose 54 named exceptions for the duplicates.'),
      bulletWords('said', 'The person redirected the agent to the goal: gate and tests only.'),
    ];
    for (const line of drawn) {
      expect(line).not.toContain('said: The agent');
      expect(line).not.toContain('said: The person');
      expect(line).not.toContain('You said: The person');
    }
    expect(drawn[0]).toBe(
      'The agent read the gate and its tests, then installed the pinned dependencies.',
    );
    expect(drawn[1]).toBe('The agent opened draft PR #638 and said the gate was waiting.');
    expect(drawn[2]).toBe('You redirected the agent to the goal: gate and tests only.');
    expect(drawn[3]).toBe('You chose 54 named exceptions for the duplicates.');
    expect(drawn[4]).toBe('You chose 54 named exceptions for the duplicates.');
    expect(drawn[5]).toBe(
      'The agent said you redirected the agent to the goal: gate and tests only.',
    );
  });
  it('says "you" only for the subject, and agrees the verb with it', () => {
    expect(askedText('The person wants the diff small.')).toBe('You want the diff small.');
    expect(askedText('The person has not run it.')).toBe('You have not run it.');
    // Inside quotes or later in the line the person keeps the name they were given.
    expect(askedText('The person typed "the person is waiting" and left.')).toBe(
      'You typed "the person is waiting" and left.',
    );
    expect(askedText('Wrapped it: the person is waiting.')).toBe(
      'You said: Wrapped it: the person is waiting.',
    );
    // A possessive is not a subject, and a line already in "you" is left as written.
    expect(askedText("The person's request was narrow.")).toBe(
      "You said: The person's request was narrow.",
    );
    expect(askedText('You chose the narrow gate.')).toBe('You chose the narrow gate.');
    // A tool or file that merely starts with the word is not the agent.
    expect(saidText('Claude.md is ready.')).toBe('The agent said: Claude.md is ready.');
  });
  it('never credits the agent’s words to the person, or the person’s to the agent', () => {
    // The sample's own line: an `asked` bullet whose text reports the agent read "You said: The agent said ...".
    expect(askedText('The agent said it also raised the billing rate.')).toBe(
      'The agent said it also raised the billing rate.',
    );
    expect(bulletWords('asked', 'The agent also said it would first answer the question.')).toBe(
      'The agent also said it would first answer the question.',
    );
    // A `said` bullet cites the agent alone: one naming the person stays the agent's report of them.
    expect(bulletWords('said', 'The user asked for a walk on a new port.')).toBe(
      'The agent said you asked for a walk on a new port.',
    );
    // Work cited with words: a named speaker is said as that speaker's.
    expect(bulletWords('did', 'The agent said it ran the suite twice.')).toBe(
      'The agent said it ran the suite twice.',
    );
    expect(bulletWords('did', 'The person asked to keep the diff small.')).toBe(
      'You asked to keep the diff small.',
    );
    // Any speech verb, and any name for the agent, keeps the agent's words off the person.
    for (const [line, want] of [
      ['The agent asked whether to keep the cache.', 'The agent asked whether to keep the cache.'],
      ['The agent reported that tests failed.', 'The agent reported that tests failed.'],
      ['The agent replied that it would wait.', 'The agent replied that it would wait.'],
      ['The assistant said it would wait.', 'The assistant said it would wait.'],
      ['Claude also said it would wait.', 'Claude also said it would wait.'],
      ["The agent's reply said the cache stays.", "The agent's reply said the cache stays."],
    ] as const) {
      expect(bulletWords('asked', line)).toBe(want);
      expect(bulletWords('asked', line)).not.toMatch(/^You/);
    }
    // A line naming the person takes one speaker label, never two.
    expect(bulletWords('said', 'You confirmed the parser is fixed.')).toBe(
      'The agent said you confirmed the parser is fixed.',
    );
    expect(bulletWords('said', 'You reported failed tests.')).toBe(
      'The agent said you reported failed tests.',
    );
    expect(bulletWords('did', 'You confirmed the parser is fixed.')).toBe(
      'You confirmed the parser is fixed.',
    );
    expect(bulletWords('asked', 'You confirmed the parser is fixed.')).toBe(
      'You confirmed the parser is fixed.',
    );
    expect(bulletWords('asked', 'The person also asked for a smaller diff.')).toBe(
      'You also asked for a smaller diff.',
    );
    expect(bulletWords('said', 'The person also asked for a smaller diff.')).toBe(
      'The agent said you also asked for a smaller diff.',
    );
    expect(bulletWords('did', 'The agent reported that tests failed.')).toBe(
      'The agent reported that tests failed.',
    );
    // A bare "Said" on an asked line is still the person's.
    expect(askedText('Said to keep going.')).toBe('You said to keep going.');
    expect(askedText('Said: keep going.')).toBe('You said: keep going.');
  });
  it('points at the outline only where one is drawn, and says summaries are off everywhere', () => {
    expect(SUMMARY_NOT_CLAUDE('Gemini CLI', false)).not.toContain('outline');
    expect(SUMMARY_NOT_CLAUDE('Codex')).toContain('The outline above');
    // One switch for the machine: the sentence once said "this session".
    expect(SUMMARY_OFF).toContain('every session');
    expect(SUMMARY_OFF).not.toContain('this session');
  });
  it('says why a phase title was withheld, as a withheld line does', () => {
    expect(withheldTitle('completion_claim')).toMatch(/^Phase title left out: it used a word/);
    expect(withheldTitle('completion_claim')).toContain('“fix”');
    expect(withheldTitle('unknown')).toMatch(/^Phase title left out: /);
  });
  it('words a failed check in text, not only in colour', () => {
    expect(bulletWords('failed', 'Ran pytest.')).toBe('Failed as the tool reported: Ran pytest.');
    // The producer's report form already says "as the tool reported"; the mark does not say it again.
    expect(bulletWords('failed', 'pnpm test reported failed, as the tool reported.')).toBe(
      'Failed: pnpm test reported failed, as the tool reported.',
    );
    expect(bulletWords('did', 'Ran pytest.')).toBe('Ran pytest.');
    expect(bulletWords('said', 'Ran pytest.')).toBe('The agent said: Ran pytest.');
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
    // While the job writes it, the header does not date a summary that is still being made.
    expect(summaryStamp(base, false, 'm', true)).toBe('m · summarizing…');
    expect(summaryStamp(base, true, '', true)).toBe('summarizing…');
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
  // Each entry at the time its number implies, so these cases read as they did when placement used numbers.
  const timed = [...numbers.keys()].map((id, n) => ({ id, at: 100 + n }));
  const positions = recordPositions(timed, numbers);
  it('orders a sub-number between its neighbours', () => {
    expect(positionOf('2.1')).toEqual([2, 1]);
    expect(positionOf('x')).toBeNull();
  });
  it('places a departure in a phase, after, between or nowhere', () => {
    if (!base) throw new Error('no summary');
    expect(placeDeparture(base, ['c1'], positions)).toEqual({ where: 'phase', phases: ['0:0'] });
    expect(placeDeparture(base, ['c3'], positions).where).toBe('after');
    expect(placeDeparture(base, ['c2'], positions).where).toBe('between');
    expect(placeDeparture(base, ['zz'], positions).where).toBe('unplaced');
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
    expect(placeDeparture(unmatched, ['c2'], positions).where).toBe('unplaced');
    expect(placeDeparture(unmatched, ['c3'], positions).where).toBe('unplaced');
    expect(placeDeparture(unmatched, ['a2'], positions)).toEqual({
      where: 'phase',
      phases: ['1:0'],
    });
  });
  it('places a rerun check or a rewritten file at its newest run, not the number of its first', () => {
    // Measured on a Haiku session: turn 1 wrote src/calc.py, turn 2 wrote docs/README.md against a line that
    // ruled docs/ out, and turn 3 wrote src/calc.py again. The rewrite kept #1.1, its first write's number,
    // with the newest write's id and time, so the turn-3 phase's span reached back over #3.1 and was marked too.
    const rerun = parseFocusedSummary({
      sources: {
        summary: {
          exists: true,
          made_at: 1900000000,
          model_stamp: 'claude:m:x',
          blocks: [
            {
              first: 'm1',
              last: 'm6',
              entries: 9,
              phases: [
                { title: 'Subtract', bullets: [{ text: 'a', kind: 'did', cites: ['m1', 'm2'] }] },
                {
                  title: 'README',
                  bullets: [{ text: 'b', kind: 'did', cites: ['m3', 'readme', 'm4'] }],
                },
                {
                  title: 'Multiply',
                  bullets: [{ text: 'c', kind: 'did', cites: ['m5', 'calc', 'm6'] }],
                },
              ],
            },
          ],
        },
      },
    })?.summary;
    if (!rerun) throw new Error('no summary');
    const labels = new Map([
      ['m1', '1'],
      ['calc', '1.1'],
      ['m2', '2'],
      ['m3', '3'],
      ['readme', '3.1'],
      ['m4', '4'],
      ['m5', '5'],
      ['m6', '6'],
    ]);
    const at = { m1: 10, m2: 20, m3: 30, readme: 31, m4: 40, m5: 50, calc: 51, m6: 60 };
    const placed = recordPositions(
      Object.entries(at).map(([id, time]) => ({ id, at: time })),
      labels,
    );
    expect(placeDeparture(rerun, ['readme'], placed)).toEqual({ where: 'phase', phases: ['0:1'] });
    expect(placeDeparture(rerun, ['calc'], placed)).toEqual({ where: 'phase', phases: ['0:2'] });
  });
  it('puts a message before a rerun that shares its time, as the server numbers them', () => {
    const placed = recordPositions(
      [
        { id: 'rerun', at: 50 },
        { id: 'm5', at: 50 },
      ],
      new Map([
        ['rerun', '1.1'],
        ['m5', '5'],
      ]),
    );
    expect([...placed]).toEqual([
      ['m5', [1, 0]],
      ['rerun', [2, 0]],
    ]);
  });
  it('places only an entry the page numbers and has a time for', () => {
    const placed = recordPositions(
      [
        { id: 'a', at: 5 },
        { id: 'b', at: null },
        { id: 'c', at: 7 },
      ],
      new Map([
        ['a', '1'],
        ['b', '2'],
      ]),
    );
    expect([...placed]).toEqual([['a', [1, 0]]]);
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

describe('the focused summary plan before a start', () => {
  const plan = (extra: Record<string, unknown> = {}) =>
    parseFocusedSummary({
      sources: {
        summary: {
          exists: false,
          state: 'absent',
          plan: {
            reason: null,
            complete: true,
            parts: 4,
            windows: 3,
            calls: 8,
            minutes: 10,
            largest_read: { windows: 32, window_bytes: 16384 },
            ...extra,
          },
        },
      },
    })?.plan ?? null;

  it('says the parts and the upper bound on the minutes, singular and plural', () => {
    expect(readSize(6, false, plan())).toBe(
      'About 6 entries to read in 4 parts, up to 10 minutes.',
    );
    expect(readSize(1, false, plan({ parts: 1, windows: 0, minutes: 1 }))).toBe(
      'About 1 entry to read in 1 part, up to 1 minute.',
    );
  });

  it('quotes no parts off a partial read, whose count the job may pass', () => {
    // The count of parts off a partial read is a floor the job's own count can pass, so it is not quoted: the
    // estimate said "at least 2 parts" and the progress said "part 1 of 3".
    expect(readSize(6, true, plan({ complete: false }))).toBe(
      'More than 6 entries to read. Compass plans the parts when the summary starts, and shows them here.',
    );
  });

  it('keeps the entry count alone without a plan, with no parts, or with one the preflight would refuse', () => {
    const fallback =
      'About 6 entries to read. Compass plans the parts when the summary starts, and shows them here.';
    expect(readSize(6, false, null)).toBe(fallback);
    expect(readSize(6, false, plan({ parts: 0 }))).toBe(fallback);
    expect(readSize(6, false, plan({ reason: 'planned_calls' }))).toBe(fallback);
    expect(plan({ complete: 'yes' })).toBeNull();
    expect(plan({ minutes: -1 })).toBeNull();
    expect(readSize(null, false, plan())).toBe('');
  });

  it('is not read beside a saved summary', () => {
    const focused = parseFocusedSummary({
      sources: { summary: { exists: true, state: 'ok', plan: { complete: true } } },
    });
    expect(focused?.plan ?? null).toBeNull();
  });
});

describe('a run of hidden lines', () => {
  it('says the reason once when every line shares it', () => {
    expect(hiddenSentence(['no_citation', 'no_citation'], 'Entries #2 to #3')).toBe(
      '2 lines hidden: they cited no entry. Entries #2 to #3.',
    );
  });
  it('says a line the record does not back as left out, in the reader’s words', () => {
    expect(hiddenSentence(['completion_claim'], 'Entries #40.1 to #44, and 1 more')).toBe(
      'One line was left out because the record does not back it. Entries #40.1 to #44, and 1 more.',
    );
    expect(hiddenSentence(['completion_claim', 'completion_claim'], '')).toBe(
      '2 lines were left out because the record does not back them.',
    );
    expect(hiddenSentence(['completion_claim', 'no_citation'], '')).toBe(
      '2 lines hidden: 1 was left out because the record does not back it; 1 cited no entry.',
    );
    for (const line of [
      hiddenSentence(['completion_claim'], ''),
      hiddenSentence(['completion_claim', 'no_citation'], ''),
    ])
      expect(line).not.toContain('summary’s own voice');
  });
  it('names each reason with its count when the lines were hidden for different ones', () => {
    const line = hiddenSentence(['no_citation', 'too_long_cut', 'no_citation'], '');
    expect(line).toBe('3 lines hidden: 2 cited no entry; 1 was too long to show whole.');
    expect(line).not.toContain('each broke a rule');
    expect(hiddenSentence(['odd', 'other', 'shape_fault'], '')).toBe(
      '3 lines hidden: 2 were held back; 1 could not be shown in a form Compass accepts.',
    );
  });
  it('uses no jargon in any reason a line or a title was withheld for', () => {
    const jargon =
      /own voice|must take|must keep|summary line|phase must|changed what it (said|says)|shape a/i;
    const said = [
      ...Object.values(WITHHELD_LINES),
      ...Object.values(WITHHELD_TITLES),
      withheldSentence('unheard-of'),
      withheldTitle('unheard-of'),
      withheldSentence('completion_claim', 'opening summary'),
      ...[
        ['completion_claim'],
        ['no_citation'],
        ['shape_fault'],
        ['too_long_cut'],
        ['odd'],
        ['no_citation', 'too_long_cut', 'shape_fault', 'completion_claim', 'odd'],
      ].flatMap((reasons) => [
        hiddenSentence(reasons, ''),
        hiddenSentence([...reasons, ...reasons], ''),
      ]),
    ];
    for (const line of said) expect(line).not.toMatch(jargon);
  });
  it('says a withheld opening summary as the opening summary, not as a line', () => {
    expect(withheldSentence('completion_claim', 'opening summary')).toMatch(/opening summary/);
    expect(withheldSentence('completion_claim', 'opening summary')).not.toMatch(/this line/);
    expect(withheldSentence('completion_claim')).toMatch(/this line/);
  });
});

describe('the opening paragraph names you, not the person', () => {
  it('folds "the person" at the start of a sentence, with its verb, as a person bullet already is', () => {
    expect(
      ledeWords('The person asked for a retry. The agent added it. The user wants a test.'),
    ).toBe('You asked for a retry. The agent added it. You want a test.');
    expect(ledeWords('The person has a failing test and the agent waited for the person.')).toBe(
      'You have a failing test and the agent waited for the person.',
    );
  });
  it('folds only before a verb, never a noun, a clause or a comma', () => {
    for (const text of [
      'The user interface was redesigned.',
      'The person who asked left.',
      'The person, a reviewer, asked.',
      'The user guide changed.',
      'Done e.g. the person asked for X.',
    ]) {
      expect(ledeWords(text)).toBe(text);
    }
    expect(ledeWords('The person asked for X. The user guide changed.')).toBe(
      'You asked for X. The user guide changed.',
    );
  });
  it('leaves a possessive, a mention inside a sentence and a line with no person alone', () => {
    const text = "The person's goal was a retry. The agent waited for the person to reply.";
    expect(ledeWords(text)).toBe(text);
    expect(ledeWords('The agent added a retry.')).toBe('The agent added a retry.');
  });
});

describe('the failure badge', () => {
  it('still counts a real failure whose words contain "blocked" or "not allowed"', () => {
    expect(isTestFailure('vitest reported failed: the test was blocked on a missing mock.')).toBe(
      true,
    );
    expect(isTestFailure('pytest reported failed: expected not allowed value')).toBe(true);
    expect(isTestFailure('pytest reported failed: operation not permitted in the sandbox')).toBe(
      false,
    );
  });
  it('counts a failed test run, and no other failed check', () => {
    expect(isTestFailure('pnpm test:stories reported failed, as the tool reported.')).toBe(true);
    expect(isTestFailure('The agent ran pytest tests/test_webhook.py; it reported failed.')).toBe(
      true,
    );
    expect(isTestFailure('ruff check src reported failed, as the tool reported.')).toBe(false);
    expect(isTestFailure('pnpm build reported failed, as the tool reported.')).toBe(false);
  });
  it('does not count a failed build, lint or type check whose words name a test', () => {
    expect(isTestFailure('pnpm build:storybook reported failed, as the tool reported.')).toBe(
      false,
    );
    expect(isTestFailure('ruff check tests reported failed, as the tool reported.')).toBe(false);
    expect(
      isTestFailure('mypy compass/skills/compass/tests reported failed, as the tool reported.'),
    ).toBe(false);
  });
  it('counts a test run whatever it is called, and puts down a sandbox refusal however it is phrased', () => {
    for (const run of [
      'tox -e py312',
      'nox -s tests',
      'cargo nextest run',
      'the test suite',
      'py.test -x',
    ])
      expect(isTestFailure(`${run} reported failed, as the tool reported.`)).toBe(true);
    for (const reason of [
      'Operation not permitted',
      'EACCES opening the socket',
      'a read-only file system',
      'the launch was blocked',
      'failed to launch the browser',
      'ECONNREFUSED 127.0.0.1',
    ])
      expect(isTestFailure(`vitest run reported failed: ${reason}.`)).toBe(false);
  });
  it('does not count a run the agent put down to its sandbox', () => {
    expect(
      isTestFailure(
        'vitest run reported failed, as the tool reported, and the agent attributed the browser launch error to the sandbox.',
      ),
    ).toBe(false);
    expect(
      isTestFailure('pnpm test:stories reported failed in the agent’s environment, not-recorded.'),
    ).toBe(false);
  });
});

describe('the citations a chip cannot open', () => {
  it('is said once, as a count of the entries Full activity does not list', () => {
    expect(unlinkedSentence(1)).toBe(
      '1 cited entry is an earlier check or file that Full activity does not list, so it cannot be opened from here.',
    );
    expect(unlinkedSentence(3)).toBe(
      '3 cited entries are earlier checks or files that Full activity does not list, so they cannot be opened from here.',
    );
  });
});

describe('a hidden run’s open state', () => {
  const hidden = (cites: string[]) =>
    ({ kind: 'said', text: { withheld: 'no_citation' }, cites, citesCut: 0 }) as never;
  it('is keyed by the entries its lines cite, so a shifted run keeps its own state', () => {
    expect(hiddenKey([hidden(['b', 'a']), hidden(['a'])], 3)).toBe('cites:a+b');
    expect(hiddenKey([hidden(['b', 'a'])], 7)).toBe(hiddenKey([hidden(['a', 'b'])], 2));
  });
  it('keeps its place only when it cites nothing', () => {
    expect(hiddenKey([hidden([])], 4)).toBe('at:4');
  });
});
