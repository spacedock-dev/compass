import { describe, expect, it } from 'vitest';
import { contextKey } from '../api/identity';
import { annotationOf } from '../intent/annotation';
import { workSource } from '../intent/work';
import type { ContextEntry } from '../store/board';
import { analysisLevel } from './level';
import { readingShape } from './shape';

/* An analysis level of None or low may rest on a recorded harness fact: a created pull request or a used skill
   that a Consistent line cites, with no passing check
   ([DEC-26](../../../docs/design-reading-a-session.md#amended-2026-10-24-owner-an-analyze-readings-none-or-low-may-rest-on-recorded-harness-facts)).
   The server owns the floor, so the page draws the level it published; the agent's words alone never lift it
   there (`test_levels.py`). */

const NOW = 5000;
const SESSION = {
  harness: 'claude',
  sid: 'read',
  project: 'p',
  project_key: '/p',
  state: 'idle',
  annotation_goal: 'Use the skill and create a PR',
  annotation_revision: 2,
};
const SOURCE = { harness: 'claude', sid: 'read' };
const fact = (id: string, type: string, subject: string, summary: string, at: number) => ({
  fact_id: id,
  type,
  subject,
  by: 'agent',
  summary,
  at,
  source_session: SOURCE,
  evidence: { source: 'transcript', confidence: 'exact' },
});
const FACTS = [
  fact('skill1', 'tool_report', 'skill', 'linear-deep-dive', NOW - 300),
  fact('pr1', 'tool_report', 'pr', 'example-org/example-repo#7', NOW - 280),
  fact('said1', 'agent_message', '', 'Done: PR opened.', NOW - 270),
];
const CONSISTENT = 'consistent with the evidence read';
const reading = (cites: readonly string[]) => ({
  read_at: NOW - 240,
  revision_read: 2,
  window_start: NOW - 400,
  scope: 'last-turn',
  criteria: { goal: { result: CONSISTENT, cites, detail: '', clause: 'x' } },
});
const row = {
  harness: 'claude',
  sid: 'read',
  revision_read: 2,
  read_at: NOW - 240,
  computed_at: NOW - 240,
  level: 'none_or_low',
  reasons: ['floor-met'],
  cites: [],
};

function derive(cites: readonly string[]) {
  const session = { ...SESSION, annotation_assessment: reading(cites) };
  const annotation = annotationOf(session as never);
  const contexts = new Map<string, ContextEntry>([
    [
      contextKey('/p', session as never),
      {
        data: {
          semantic: { facts: FACTS },
          sources: { work: { tool_reports: [], analysis_levels: [row] } },
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
}

describe('the analysis level over recorded harness facts', () => {
  it.each([['pr1'], ['skill1', 'pr1']])('draws None or low on a line citing %s', (...cites) => {
    expect(derive(cites)?.level).toBe('none_or_low');
  });
});
