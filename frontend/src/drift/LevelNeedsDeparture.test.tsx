import { act, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { contextKey } from '../api/identity';
import { annotationOf } from '../intent/annotation';
import { workSource } from '../intent/work';
import type { ContextEntry } from '../store/board';
import { mountSessions } from '../sessions/testing';
import { analysisLevel } from './level';
import { readingShape } from './shape';
import { textOf } from './testing';

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
  const derive = (results: readonly string[], level: string, own: Record<string, unknown> = {}) => {
    const session = { ...SESSION, annotation_assessment: assessment(results), ...own };
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

  it('names the goal, not a line, when a goal-only reading has no check showing it', () => {
    const goalOnly = derive([CANT_TELL], 'none_or_low', { annotation_line_1: '' });
    expect(goalOnly?.reasons.blockers).toContain('Your goal is not shown by any check.');
    expect(goalOnly?.reasons.blockers).not.toContain(
      'A line of your intent is not shown by any check.',
    );
    const withLine = derive([CANT_TELL, CANT_TELL], 'none_or_low');
    expect(withLine?.reasons.blockers).toContain(
      'A line of your intent is not shown by any check.',
    );
  });

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
  const context = (level: string, harness: string) => ({
    semantic: { facts: [{ ...SAID, source_session: { ...SAID.source_session, harness } }] },
    sources: {
      work: {
        tool_reports: [],
        analysis_levels: [{ ...row(level), harness }],
        live_levels: [live],
      },
    },
  });
  const open = async (
    results: readonly string[],
    level: string,
    session: Record<string, unknown> = {},
  ) => {
    const harness = session['harness'] ?? SESSION.harness;
    const page = mountSessions({
      hash: `#n=session:p:${String(harness)}:read`,
      data: {
        generated: NOW,
        annotate: true,
        sessions: [{ ...SESSION, annotation_assessment: assessment(results), ...session }],
      },
      context: context(level, String(harness)),
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
    expect(document.querySelector('[data-next-drift-pill] strong')?.textContent).toBe(
      'Slightly off course',
    );
    expect(document.querySelector('[data-next-drift-level]')?.textContent).toContain(
      'From the progress check at',
    );
  });

  it('keeps the Codex departure reading visible without a level, pill or source', async () => {
    await open([DEPARTS, CANT_TELL], 'medium', { harness: 'codex' });
    expect(document.querySelector('[data-next-progress-summary]')?.textContent).toContain(
      'departure',
    );
    expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
    expect(document.querySelector('[data-next-drift-level]')).toBeNull();
    expect(document.body.textContent).not.toContain('From the progress check at');
    expect(textOf('.next-session-detail-header')).not.toContain('Slightly off course');
  });

  it.each(['claude', 'pi', 'codex'])(
    'shows a cited %s departure without claiming the evidence was insufficient',
    async (harness) => {
      await open([DEPARTS, CANT_TELL], '', { harness });
      const card = within(screen.getByRole('region', { name: 'Is it on track?' }));
      expect(card.getByText(/Compass found 1 departure/)).toBeVisible();
      expect(card.queryByText("Can't tell", { exact: true })).toBeNull();
      expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
    },
  );

  it('explains a failed newer progress check without presenting the earlier level as current', async () => {
    await open([DEPARTS, CANT_TELL], 'medium', {
      annotation_reading_withheld: 'The progress check failed. No new reading was saved.',
      annotation_reading_withheld_at: NOW - 120,
    });
    const card = within(screen.getByRole('region', { name: 'Is it on track?' }));
    expect(card.getByText("Can't tell", { exact: true })).toBeVisible();
    expect(card.getByText(/The latest progress check did not produce a reading/)).toBeVisible();
    expect(card.getByText(/The progress check failed/)).toBeVisible();
    expect(card.getByText('What the earlier check found')).toBeVisible();
    expect(card.queryByText(/Checked .* against your goal/)).toBeNull();
    expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
    expect(textOf('.next-session-detail-header')).not.toContain('Slightly off course');
  });

  it('shows a withdrawn check as out of date, with its own explanation', async () => {
    await open([DEPARTS, CANT_TELL], 'medium', {
      annotation_assessment: { ...assessment([DEPARTS, CANT_TELL]), scope: 'withdrawn' },
    });
    const card = within(screen.getByRole('region', { name: 'Is it on track?' }));
    expect(card.getByText('Out of date')).toBeVisible();
    expect(card.getByText(/This check was withdrawn/)).toBeVisible();
    expect(card.queryByText(/Checked .* against your goal/)).toBeNull();
    expect(textOf('.next-session-detail-header')).not.toContain('Slightly off course');
    expect(card.queryByText('Where it went off course')).toBeNull();
    expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
  });

  it('says so far in the header while the session works', async () => {
    await open([DEPARTS, CANT_TELL], 'medium', { state: 'working' });
    const header = textOf('.next-session-detail-header');
    expect(header).toContain('Slightly off course so far');
  });

  it('keeps so far in the header and summary for a mid-flight reading after the session goes quiet', async () => {
    await open([DEPARTS, CANT_TELL], 'medium', {
      annotation_assessment: { ...assessment([DEPARTS, CANT_TELL]), scope: 'mid-flight' },
    });
    const header = textOf('.next-session-detail-header');
    expect(header).toContain('Slightly off course so far');
    expect(textOf('[data-next-progress-summary]')).toMatch(/^So far, Compass found/);
  });

  it('shows the level without so far in the header and summary after a finished turn', async () => {
    await open([DEPARTS, CANT_TELL], 'medium');
    const header = textOf('.next-session-detail-header');
    expect(header).toContain('Slightly off course');
    expect(header).not.toContain('so far');
    expect(textOf('[data-next-progress-summary]')).not.toMatch(/^So far, Compass found/);
  });
});
