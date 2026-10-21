import { act } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { contextKey } from '../api/identity';
import { annotationOf } from '../intent/annotation';
import { workSource } from '../intent/work';
import type { ContextEntry } from '../store/board';
import { mountSessions } from '../sessions/testing';
import { analysisLevel } from './level';
import { readingShape } from './shape';

/* A level above None or low stands only on a departure the reading shows. The analysis level, the header
   pill and the card are one derivation, so a reading that found nothing against the intent cannot draw
   Medium beside "Can't tell" or beside "Nothing found"
   ([DEC-26](../../../docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)).
   The live estimate is a different claim from a different source and does not stand in for a reading that
   has been made. */

const NOW = 5000;
const SESSION = {
  harness: 'claude',
  sid: 'read',
  project: 'p',
  project_key: '/p',
  state: 'idle',
  annotation_goal: 'Ship the queue',
  annotation_line_1: 'Tests pass',
  annotation_revision: 2,
};
const CANT_TELL = 'not verifiable from available evidence';
const DEPARTS = 'departure';

function assessment(results: readonly string[]) {
  return {
    read_at: NOW - 240,
    revision_read: 2,
    scope: 'last-turn',
    criteria: Object.fromEntries(
      results.map((result, index) => [
        index === 0 ? 'goal' : `line_${String(index)}`,
        { result, cites: result === DEPARTS ? ['f1'] : [], detail: '', clause: 'x' },
      ]),
    ),
  };
}

/* What the departure cites: an entry the record holds, or the page's own rules refuse the departure. */
const SAID = {
  fact_id: 'f1',
  type: 'agent_message',
  by: 'agent',
  summary: 'Done: the queue ships.',
  at: NOW - 300,
  source_session: { harness: 'claude', sid: 'read' },
  evidence: { source: 'transcript', confidence: 'exact' },
};

const row = (level: string) => ({
  harness: 'claude',
  sid: 'read',
  revision_read: 2,
  read_at: NOW - 240,
  computed_at: NOW - 240,
  level,
  reasons: ['failed-check'],
  cites: [],
});

describe('the analysis level', () => {
  const derive = (results: readonly string[], level: string) => {
    const session = { ...SESSION, annotation_assessment: assessment(results) };
    const annotation = annotationOf(session as never);
    const contexts = new Map<string, ContextEntry>([
      [
        contextKey('/p', session as never),
        {
          data: {
            semantic: { facts: [SAID] },
            sources: { work: { tool_reports: [], analysis_levels: [row(level)] } },
          } as never,
          revision: 1,
          error: null,
        },
      ],
    ]);
    const work = workSource(contexts, '/p', session as never);
    const shape = readingShape(
      annotation?.['assessment'],
      annotation,
      work.all || work.entries || [],
      '',
      false,
      () => 'typed',
    );
    return analysisLevel({
      contexts,
      projectKey: '/p',
      session: session as never,
      annotation,
      shape,
      work,
      payload: { annotate: true, generated: NOW } as never,
      generated: NOW,
    });
  };

  it.each(['medium', 'high', 'extreme'])(
    'withholds %s from a reading with no departure, whatever it cannot tell',
    (level) => {
      const result = derive([CANT_TELL, CANT_TELL], level);
      expect(result?.level).toBe('not_enough');
    },
  );

  it.each(['medium', 'high', 'extreme'])('keeps %s over a reading that departs', (level) => {
    const result = derive([DEPARTS, CANT_TELL], level);
    expect(result?.level).toBe(level);
  });
});

describe('the header pill and the card', () => {
  const live = {
    harness: 'claude',
    sid: 'read',
    revision: 2,
    computed_at: NOW - 60,
    level: 'medium',
    reasons: ['pass-then-write'],
    cites: [],
  };
  const context = (level: string) => ({
    semantic: { facts: [SAID] },
    sources: { work: { tool_reports: [], analysis_levels: [row(level)], live_levels: [live] } },
  });
  const open = async (
    results: readonly string[],
    level: string,
    session: Record<string, unknown> = {},
  ) => {
    const page = mountSessions({
      hash: '#n=session:p:claude:read',
      data: {
        generated: NOW,
        annotate: true,
        sessions: [{ ...SESSION, annotation_assessment: assessment(results), ...session }],
      },
      context: context(level),
    });
    await act(async () => {
      await page.settle();
    });
    return page;
  };

  it('draw no level for a reading that cannot tell, though a level row says Medium', async () => {
    await open([CANT_TELL, CANT_TELL], 'medium');
    expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
    expect(document.querySelector('[data-next-drift-level]')).toBeNull();
    expect(document.querySelector('.next-session-drift-meter')).toBeNull();
  });

  it('draw the level of a reading that departs', async () => {
    await open([DEPARTS, CANT_TELL], 'medium');
    expect(document.querySelector('[data-next-drift-pill] strong')?.textContent).toBe('Medium');
  });

  it('say "so far" while the session runs, and drop it once the session is idle', async () => {
    await open([DEPARTS, CANT_TELL], 'medium', { state: 'working' });
    expect(document.querySelector('[data-next-drift-pill]')?.textContent).toBe(
      'Drift: Medium so far',
    );
  });

  it('say "so far" for a reading of a running turn, though the session has since gone idle', async () => {
    await open([DEPARTS, CANT_TELL], 'medium', {
      annotation_assessment: { ...assessment([DEPARTS, CANT_TELL]), scope: 'mid-flight' },
    });
    expect(document.querySelector('[data-next-drift-pill]')?.textContent).toBe(
      'Drift: Medium so far',
    );
  });

  it('say no "so far" over a reading of a finished turn on an idle session', async () => {
    await open([DEPARTS, CANT_TELL], 'medium');
    expect(document.querySelector('[data-next-drift-pill]')?.textContent).toBe('Drift: Medium');
  });
});
