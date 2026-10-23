import { describe, expect, it } from 'vitest';
import { noDraftWhy } from './derive';

const PAYLOAD = { annotate: true, intent_revision: 'r1' };
const OPENED = {
  harness: 'claude',
  sid: 's',
  first_prompt: '/goal a file exists',
  first_prompt_control: true,
};

describe('why the goal box arrives empty over a /goal session', () => {
  it('says the session holds a /goal, so it never reads as goal-less', () => {
    const session = { ...OPENED, session_goal: { text: 'The findings file exists', at: 9 } };
    const why = noDraftWhy(session, null, PAYLOAD);
    expect(why).toContain('This session opened with /goal, so there is no first prompt');
    expect(why).toContain('It holds this /goal: The findings file exists');
  });

  it('keeps the plain sentence when no /goal is published', () => {
    expect(noDraftWhy(OPENED, null, PAYLOAD)).toBe(
      'This session opened with /goal, so there is no first prompt to draft a goal from.',
    );
  });

  it('takes the clear into the same sentence, so it is said once', () => {
    const session = { ...OPENED, session_goal: null, session_goal_cleared: { at: 1_700_000_300 } };
    expect(noDraftWhy(session, null, PAYLOAD)).toMatch(
      /^This session opened with \/goal, so there is no first prompt to draft a goal from\. Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d\.$/,
    );
  });

  it('ignores a clear with no moment', () => {
    const session = { ...OPENED, session_goal_cleared: { at: 'x' } };
    expect(noDraftWhy(session, null, PAYLOAD)).not.toContain('cleared');
  });
});
