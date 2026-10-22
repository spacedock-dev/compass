import { describe, expect, it } from 'vitest';
import { revisionLine } from '../intent/annotation';
import { baselineAt } from '../intent/work';
import { PROMPT_SOURCES, SESSION_GOAL } from './intent';

/* A goal the session states itself with `/goal` is adopted words keyed on the moment the command ran,
   like a prompt the reader picked: the places that branch on the closed list must treat it as that. */

describe('the session-goal source', () => {
  it('is one of the closed goal sources', () => {
    expect(PROMPT_SOURCES).toContain(SESSION_GOAL);
    expect(new Set(PROMPT_SOURCES).size).toBe(PROMPT_SOURCES.length);
  });

  it('baselines a saved goal at the moment the command ran, not at the save', () => {
    const annotation = {
      goal: 'the parser handles every token',
      goal_source: SESSION_GOAL,
      goal_source_at: 100,
      goal_saved_at: 400,
      at: 400,
    };
    expect(baselineAt(annotation, null, null)).toBe(100);
  });

  it('says a saved session goal was saved, as a saved prompt is, and not typed', () => {
    const annotation = { revision: 1, revision_count: 1, at: 1000, goal_source: SESSION_GOAL };
    expect(revisionLine(annotation, 1010)).toMatch(/^saved /);
    expect(revisionLine({ ...annotation, goal_source: 'typed' }, 1010)).toMatch(/^typed /);
  });
});
