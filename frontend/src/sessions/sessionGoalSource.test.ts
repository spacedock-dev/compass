import { describe, expect, it } from 'vitest';
import { revisionLine } from '../intent/annotation';
import { baselineAt } from '../intent/work';
import { readingShape } from '../drift/shape';
import { annotationOf } from '../intent/annotation';
import { intentLogView } from '../intent/logModel';
import { projectGoal } from '../project/goal';
import { goalCell, sessionsContext } from './rows';
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

  /* Every place that names where a goal came from says "/goal" for a session goal, never "your prompt":
     the session page already said "From /goal" while the list said "FROM YOUR PROMPT" (owner feedback,
     2026-10-23). */
  describe('names its source as /goal everywhere', () => {
    const cell = (source: string) =>
      goalCell(
        {
          harness: 'claude',
          sid: 's',
          annotation_goal: 'the parser handles every token',
          annotation_goal_source: source,
        } as never,
        sessionsContext({ annotate: true } as never),
      ).label;

    it('in the Sessions list row', () => {
      expect(cell(SESSION_GOAL)).toBe('GOAL · FROM /GOAL');
      expect(cell('first-prompt')).toBe('GOAL · FROM YOUR PROMPT');
      expect(cell('typed')).toBe('GOAL · YOUR WORDS');
    });

    it('in the project goal tag', () => {
      const tag = (source: string) =>
        projectGoal(
          { sessions: [], goalKnown: false, goalText: '', goalSrcText: '' } as never,
          { goal: 'words', goal_source: source } as never,
          null,
          null,
        ).typed[0]?.tag;
      expect(tag(SESSION_GOAL)).toBe('Your saved words · from /goal');
      expect(tag('latest-prompt')).toBe('Your saved words · from your prompt');
    });

    it('in the intent log and the reading heading', () => {
      const log = intentLogView({
        payload: { annotate: true },
        board: [],
        rows: [{ harness: 'claude', sid: 's', at: 10, goal: 'words', goal_source: SESSION_GOAL }],
        load: 'read',
      } as never);
      expect(JSON.stringify(log)).toContain('Goal from /goal');
      expect(JSON.stringify(log)).not.toContain('Goal from your prompt');
      const raw = {
        revision_read: 2,
        scope: 'last-turn',
        read_at: 400,
        goal_source: SESSION_GOAL,
        goal_source_at: 100,
        criteria: {
          goal: { result: 'consistent with the evidence read', cites: [], detail: '', clause: 'x' },
        },
      };
      const annotation = annotationOf({
        harness: 'claude',
        sid: 's',
        annotation_goal: 'x',
        annotation_revision: 2,
        annotation_assessment: raw,
      } as never);
      const shape = readingShape(raw, annotation, [] as never, '', false, () => 'typed');
      expect(shape.readClauses.map(([label]) => label)).toContain('GOAL FROM /GOAL');
      expect(shape.criteria[0]?.label).toBe('GOAL FROM /GOAL');
    });
  });
});
