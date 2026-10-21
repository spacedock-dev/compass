import { act } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { liveMonitorFor } from '../intent/liveMonitor';
import { check, contextRoute, fact, mountDrift, textOf } from './testing';

/* Two things the verdict sentence says beyond its answer, each only where it is true of what the page holds.
   A reading that stands with no level owns the level slot, so a live estimate the reader switched on is hidden
   behind it and the page says so. A reading of a session minutes old that could tell nothing says it is early
   rather than leaving three empty verdicts to read as a finding. */
const HIDDEN = '[data-next-drift-live-hidden]';
const EARLY = '[data-next-drift-early]';
const CANT_TELL = 'not verifiable from available evidence';

const reading = (
  results: readonly string[],
  over: Record<string, unknown> = {},
  coverage: Record<string, unknown> | null = { tail_truncated: false, tail_start: null },
) => ({
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
  coverage: coverage && { unlisted: 0, unread_checks: 0, goal_source: 'typed', ...coverage },
  criteria: Object.fromEntries(
    results.map((result, index) => [
      index === 0 ? 'goal' : `line_${String(index)}`,
      {
        result,
        cites: result === 'departure' ? ['c1'] : [],
        detail: result === 'departure' ? 'It stopped running the tests.' : '',
        clause: 'Ship the queue',
      },
    ]),
  ),
  ...over,
});
const session = (assessment: Record<string, unknown>) => ({
  annotation_assessment: assessment,
  annotation_window_start: 100,
  annotation_reading_count: 1,
});
const FACTS = [
  fact('u1', 400, { summary: 'Ship the queue' }),
  check('c1', 500, 'passed', { summary: 'pytest -q' }),
];
const FAILED = [
  fact('u1', 400, { summary: 'Ship the queue' }),
  check('c1', 500, 'failed', { result_source: 'failed flag', summary: 'pytest -q' }),
];
const ANALYSIS = (level: string) => ({
  harness: 'claude',
  sid: 's1',
  revision_read: 3,
  read_at: 1000,
  computed_at: 1000,
  level,
  reasons: [],
  cites: [],
});
const LIVE = (level: string) => ({
  harness: 'claude',
  sid: 's1',
  revision: 3,
  computed_at: 990,
  level,
  reasons: ['pass-then-write'],
  cites: [],
});

async function open(
  assessment: Record<string, unknown>,
  work: Record<string, unknown>,
  live: boolean,
  facts: unknown[] = FACTS,
) {
  const page = mountDrift({
    session: session(assessment),
    facts,
    routes: { '/api/project-context': contextRoute(facts, work) },
  });
  await page.settle();
  if (live) {
    await act(async () => {
      liveMonitorFor(page.shell).set({ harness: 'claude', sid: 's1' }, true);
    });
  }
  await page.settle();
  return page;
}

describe('a reading that stands with no level', () => {
  const NOTHING = reading([CANT_TELL, CANT_TELL]);
  const work = { analysis_levels: [ANALYSIS('medium')], live_levels: [LIVE('medium')] };

  it('says the live estimate is hidden, when the reader has it on and it has a level to draw', async () => {
    await open(NOTHING, work, true);
    expect(document.querySelector('[data-next-drift-level]')).toBeNull();
    expect(textOf(HIDDEN)).toBe(
      'The live estimate is not drawn while this reading stands: it reads checks and file paths, never your intent.',
    );
    expect(textOf('[data-next-drift-verdict]')).not.toMatch(/Medium/);
  });

  it('says nothing of it with the live monitor off', async () => {
    await open(NOTHING, work, false);
    expect(document.querySelector(HIDDEN)).toBeNull();
  });

  it('says nothing of it where the live estimate has no level to hide', async () => {
    await open(NOTHING, { ...work, live_levels: [] }, true);
    expect(document.querySelector(HIDDEN)).toBeNull();
  });

  it('says nothing of it over a reading that draws its own level', async () => {
    await open(
      reading(['departure', CANT_TELL]),
      { ...work, analysis_levels: [ANALYSIS('medium')] },
      true,
      FAILED,
    );
    expect(document.querySelector('[data-next-drift-level]')).not.toBeNull();
    expect(document.querySelector(HIDDEN)).toBeNull();
  });
});

describe('an empty verdict early in a session', () => {
  const NOTHING = (over: Record<string, unknown> = {}, coverage?: Record<string, unknown> | null) =>
    reading(
      [CANT_TELL, CANT_TELL],
      { scope: 'mid-flight', evidence_through: 900, ...over },
      coverage,
    );

  it('says it is early, and for how long the session had run', async () => {
    await open(NOTHING(), {}, false);
    expect(textOf('[data-next-drift-verdict]')).toContain("Can't tell from what was read.");
    expect(textOf(EARLY)).toBe(
      'Early: this reading covers only the first 8m of the session. Read again once it has run its checks.',
    );
  });

  it('says nothing once the reading covers more than the first minutes', async () => {
    await open(NOTHING({ evidence_through: 400 + 601, read_at: 1001 }), {}, false);
    expect(document.querySelector(EARLY)).toBeNull();
  });

  it('says nothing where the start of the record was not read whole', async () => {
    await open(NOTHING({}, { tail_truncated: true, tail_start: 450 }), {}, false);
    expect(document.querySelector(EARLY)).toBeNull();
    await open(NOTHING({}, null), {}, false);
    expect(document.querySelector(EARLY)).toBeNull();
  });

  it('says nothing of a finished session, which has no checks still to run', async () => {
    await open(NOTHING({ scope: 'final' }), {}, false);
    expect(document.querySelector(EARLY)).toBeNull();
  });

  it('says nothing over an answer that is not an empty one', async () => {
    await open(reading(['departure', CANT_TELL], { scope: 'mid-flight' }), {}, false);
    expect(document.querySelector(EARLY)).toBeNull();
  });
});
