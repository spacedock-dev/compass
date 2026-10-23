import { describe, expect, it } from 'vitest';
import { check, mountDrift, textOf } from './testing';

/* The harness's "goal met" verdict on the Drift card: always the harness's claim, with Compass's own check
   beside it where a reading made one. It never reads as a level and never as a passing check. */
const VERDICT_AT = 1_700_000_300;
const GOAL = { text: 'findings.md exists and the tests pass', at: 1_700_000_100 };
const reason = 'findings.md was written and the tests pass';
const withVerdict = (extra: Record<string, unknown> = {}) => ({
  session_goal: { ...GOAL, verdict: { met: true, at: VERDICT_AT, reason }, ...extra },
});

const ASSESSMENT = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'last-turn',
  scope_text: 'Read up to its last turn.',
  stamp: 'model · m',
  cutoff: 'Evidence read to its end.',
  coverage: {
    tail_truncated: false,
    tail_start: null,
    unlisted: 0,
    unread_checks: 0,
    goal_source: 'typed',
  },
  criteria: {
    goal: {
      result: 'departure',
      cites: ['c1'],
      detail: 'It stopped running the tests.',
      clause: 'Ship the queue',
    },
    line_1: {
      result: 'consistent with the evidence read',
      cites: ['c2'],
      detail: '',
      clause: 'Tests pass',
    },
  },
};
const FACTS = [
  check('c1', 500, 'failed', { result_source: 'failed flag', summary: 'pytest -q' }),
  check('c2', 600, 'passed'),
];
const checked = (
  check: string,
  why: string,
  at = VERDICT_AT,
  extra: Record<string, unknown> = {},
) => ({
  annotation_assessment: { ...ASSESSMENT, goal_verdict: { at, check, why, cites: [], ...extra } },
  annotation_window_start: 100,
  annotation_reading_count: 1,
});
const note = () => document.querySelector('[data-next-goal-verdict]');
const state = () => note()?.getAttribute('data-next-goal-verdict-state');

describe('the harness verdict on the Drift card', () => {
  it('is the harness claim alone, with no level implied, before any analysis', async () => {
    const page = mountDrift({ session: withVerdict() });
    await page.settle();
    await page.settle();
    expect(state()).toBe('claim-only');
    const text = textOf('[data-next-goal-verdict]');
    expect(text).toMatch(/Claude Code marked this goal met at (\d{4}-\d{2}-\d{2} )?\d{1,2}:\d{2}/);
    expect(text).toContain('The harness’s claim:');
    expect(text).toContain('Compass has not analyzed this session');
    expect(text).not.toMatch(/\b(Low|Medium|High)\b/);
    expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
  });

  it('keeps the card inset the level above it and the rows below it share', async () => {
    const page = mountDrift({ session: withVerdict() });
    await page.settle();
    await page.settle();
    expect(note()?.classList.contains('next-session-drift-limit')).toBe(true);
    expect(note()?.classList.contains('next-cockpit-reading-why')).toBe(false);
  });

  it('quotes the evaluator reason as text, never as markup', async () => {
    const page = mountDrift({
      session: withVerdict({
        verdict: { met: true, at: VERDICT_AT, reason: '<b>done</b> findings.md' },
      }),
    });
    await page.settle();
    await page.settle();
    expect(textOf('[data-next-goal-verdict]')).toContain('“<b>done</b> findings.md”');
    expect(note()?.querySelector('b')).toBeNull();
  });

  it('names Claude Code even where the payload labels the harness just Claude', async () => {
    const page = mountDrift({
      payload: { harnesses: [{ key: 'claude', label: 'Claude' }] },
      session: withVerdict(),
    });
    await page.settle();
    await page.settle();
    const text = textOf('[data-next-goal-verdict]');
    expect(text).toContain('Claude Code marked this goal met');
    expect(text).not.toMatch(/Claude marked/);
  });

  it('stands beside an agreeing analysis, still the harness claim', async () => {
    const page = mountDrift({
      session: { ...withVerdict(), ...checked('agrees', 'written-before') },
      facts: FACTS,
    });
    await page.settle();
    await page.settle();
    expect(state()).toBe('agrees');
    const text = textOf('[data-next-goal-verdict]');
    expect(text).toContain('The harness’s claim:');
    expect(text).toContain('Compass agrees');
    expect(text).toContain('does not change the level');
  });

  it('says disputed where the record undoes it, and the level stays the analysis', async () => {
    const page = mountDrift({
      session: { ...withVerdict(), ...checked('disputed', 'written-after') },
      facts: FACTS,
    });
    await page.settle();
    await page.settle();
    expect(state()).toBe('disputed');
    const text = textOf('[data-next-goal-verdict]');
    expect(text).toContain('Compass disputes it');
    expect(text).toContain('written again after the verdict');
    expect(text).toContain('Compass’s own reading stands');
    expect(textOf('[data-next-drift-verdict]')).toContain('1 departure');
  });

  it.each([
    ['deleted-after', 'deleted'],
    ['moved-after', 'moved away'],
  ])('names the file and the time where it was %s the verdict', async (why, verb) => {
    const page = mountDrift({
      session: {
        ...withVerdict(),
        ...checked('disputed', why, VERDICT_AT, {
          path: 'docs/e2e/notes.md',
          changed_at: VERDICT_AT + 90,
        }),
      },
      facts: FACTS,
    });
    await page.settle();
    await page.settle();
    expect(state()).toBe('disputed');
    const text = textOf('[data-next-goal-verdict]');
    expect(text).toMatch(
      new RegExp(
        `Compass disputes it: docs/e2e/notes\\.md was ${verb} at (\\d{4}-\\d{2}-\\d{2} )?\\d{1,2}:\\d{2}, after the verdict\\. Compass’s own reading stands`,
      ),
    );
    expect(text).not.toContain('could not confirm');
  });

  it.each([
    ['a removal token with no moment', 'deleted-after', { path: 'a.md' }],
    [
      'a file beside a token that is not a removal',
      'written-after',
      { path: 'a.md', changed_at: 1_700_000_400 },
    ],
  ])('refuses %s, and takes no check from it', async (_name, why, extra) => {
    const page = mountDrift({
      session: { ...withVerdict(), ...checked('disputed', why, VERDICT_AT, extra) },
      facts: FACTS,
    });
    await page.settle();
    await page.settle();
    expect(state()).toBe('unchecked');
  });

  it('says unconfirmed, not disputed, where the record holds neither side', async () => {
    const page = mountDrift({
      session: { ...withVerdict(), ...checked('unconfirmed', 'not-found') },
      facts: FACTS,
    });
    await page.settle();
    await page.settle();
    expect(state()).toBe('unconfirmed');
    expect(textOf('[data-next-goal-verdict]')).toContain('Compass could not confirm it');
    expect(textOf('[data-next-goal-verdict]')).not.toContain('disputes');
  });

  it('leaves a verdict newer than the reading unchecked, and says to analyze again', async () => {
    const page = mountDrift({
      session: { ...withVerdict(), ...checked('agrees', 'written-before', VERDICT_AT - 50) },
      facts: FACTS,
    });
    await page.settle();
    await page.settle();
    expect(state()).toBe('unchecked');
    expect(textOf('[data-next-goal-verdict]')).toContain('Analyze again to check it');
  });

  it.each([
    ['no verdict', undefined],
    ['a verdict that is not met', { met: false, at: VERDICT_AT, reason }],
    ['a verdict with no time', { met: true, reason }],
    ['a verdict that is not a mapping', 'met'],
  ])('draws nothing for %s', async (_name, verdict) => {
    const page = mountDrift({
      session: { session_goal: { ...GOAL, ...(verdict === undefined ? {} : { verdict }) } },
    });
    await page.settle();
    await page.settle();
    expect(note()).toBeNull();
  });

  it('refuses a reading whose check holds a token this build does not know, and takes no check from it', async () => {
    const page = mountDrift({
      session: { ...withVerdict(), ...checked('confirmed', 'trust-me') },
      facts: FACTS,
    });
    await page.settle();
    await page.settle();
    expect(document.body.textContent).toContain('goal_verdict');
    expect(state()).toBe('unchecked');
    expect(textOf('[data-next-goal-verdict]')).not.toContain('Compass agrees');
  });
});

/* The harness giving up on the goal (`met: false`, `failed: true`) is a claim of its own, published outside the
   goal because the goal is ended: never met, never a level, never a check. */
const GAVE_UP_AT = 1_700_000_300;
const gaveUp = (extra: Record<string, unknown> = {}) => ({
  session_goal: null,
  session_goal_gave_up: { at: GAVE_UP_AT, reason: 'the path does not exist', ...extra },
});
const gaveUpNote = () => document.querySelector('[data-next-goal-gave-up]');

describe('the harness giving up on the goal, on the Drift card', () => {
  it('is the harness claim with its time and reason, never met, and implies no level', async () => {
    const page = mountDrift({ session: gaveUp() });
    await page.settle();
    await page.settle();
    const text = textOf('[data-next-goal-gave-up]');
    expect(text).toMatch(
      /^The harness’s claim: Claude Code gave up on this goal at (\d{4}-\d{2}-\d{2} )?\d{1,2}:\d{2}\./,
    );
    expect(text).toContain('Its reason: “the path does not exist”');
    expect(text).not.toMatch(/\bmet\b/);
    expect(text).not.toContain('Analyze again');
    expect(text).not.toMatch(/\b(Low|Medium|High)\b/);
    expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
    expect(note()).toBeNull();
  });

  it('names Claude Code even where the payload labels the harness just Claude', async () => {
    const page = mountDrift({
      payload: { harnesses: [{ key: 'claude', label: 'Claude' }] },
      session: gaveUp(),
    });
    await page.settle();
    await page.settle();
    const text = textOf('[data-next-goal-gave-up]');
    expect(text).toContain('Claude Code gave up on this goal');
    expect(text).not.toMatch(/Claude gave up/);
  });

  it('reads the same beside an analysis and says Compass has not checked it', async () => {
    const page = mountDrift({
      session: { ...gaveUp(), ...checked('agrees', 'written-before') },
      facts: FACTS,
    });
    await page.settle();
    await page.settle();
    const text = textOf('[data-next-goal-gave-up]');
    expect(text).toContain('Claude Code gave up on this goal');
    expect(text).toContain('Compass has not checked it');
    expect(text).not.toContain('Compass agrees');
    expect(textOf('[data-next-drift-verdict]')).toContain('1 departure');
  });

  it('shares the card inset the met note uses', async () => {
    const page = mountDrift({ session: gaveUp() });
    await page.settle();
    await page.settle();
    expect(gaveUpNote()?.classList.contains('next-session-drift-limit')).toBe(true);
  });

  it('quotes the reason as text, never as markup, and omits an empty one', async () => {
    const page = mountDrift({ session: gaveUp({ reason: '<b>no</b>' }) });
    await page.settle();
    await page.settle();
    expect(textOf('[data-next-goal-gave-up]')).toContain('“<b>no</b>”');
    expect(gaveUpNote()?.querySelector('b')).toBeNull();
    page.unmount();
    const bare = mountDrift({ session: gaveUp({ reason: '' }) });
    await bare.settle();
    await bare.settle();
    expect(textOf('[data-next-goal-gave-up]')).not.toContain('Its reason');
  });

  it.each([
    ['no give-up', undefined],
    ['one with no time', { reason: 'x' }],
    ['one that is not a mapping', 'gave up'],
  ])('draws nothing for %s', async (_name, value) => {
    const page = mountDrift({
      session: {
        session_goal: null,
        ...(value === undefined ? {} : { session_goal_gave_up: value }),
      },
    });
    await page.settle();
    await page.settle();
    expect(gaveUpNote()).toBeNull();
  });

  it('is not drawn once a later goal is held, which carries the earlier give-up itself', async () => {
    const page = mountDrift({
      session: {
        session_goal: { ...GOAL, earlier: { how: 'gave-up', at: GAVE_UP_AT } },
        session_goal_gave_up: null,
      },
    });
    await page.settle();
    await page.settle();
    expect(gaveUpNote()).toBeNull();
  });
});
