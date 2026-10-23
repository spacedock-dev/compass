import { describe, expect, it } from 'vitest';
import { goalBox, mountSession, text } from './panel.testing';

/* What became of an earlier /goal, said under the Goal field: only what the record shows, never the earlier
   goal's words, and never beside the update offer, which already says the /goal changed. */

const GOAL = 'The findings file exists and every check in it passes';
const LATER = 'The findings file is split by area and every check passes';

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};
const ended = () => document.querySelector('[data-next-goal-ended]');
const held = (earlier: unknown) => ({ session_goal: { text: GOAL, at: 500, earlier } });

describe('what became of an earlier /goal', () => {
  it.each([
    ['replaced', /^Replaced an earlier \/goal at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/],
    ['met', /^An earlier \/goal was met at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/],
    ['gave-up', /^Claude Code gave up on an earlier \/goal at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/],
  ])('says %s under the Goal field, with its time', async (how, wording) => {
    const page = mountSession({ session: held({ how, at: 450 }) });
    await settle(page);
    expect(text('[data-next-goal-ended]')).toMatch(wording);
    expect(goalBox().value).toBe(GOAL);
  });

  it('draws nothing for a goal with no earlier one, or one this build cannot read', async () => {
    const none = mountSession({ session: { session_goal: { text: GOAL, at: 500 } } });
    await settle(none);
    expect(ended()).toBeNull();
    none.unmount();
    for (const earlier of [
      { how: 'cleared', at: 450 },
      { how: 'met' },
      { how: 'met', at: 'x' },
      { how: 'met', at: 0 },
      'met',
    ]) {
      const page = mountSession({ session: held(earlier) });
      await settle(page);
      expect(ended()).toBeNull();
      page.unmount();
    }
  });

  it('says a clear that left no goal and no draft, beside the Goal field', async () => {
    const page = mountSession({
      session: {
        session_goal: null,
        session_goal_cleared: { at: 450 },
        first_prompt: '',
        first_prompt_at: null,
      },
    });
    await settle(page);
    expect(text('[data-next-goal-ended]')).toMatch(
      /^Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/,
    );
    expect(goalBox().value).toBe('');
  });

  it('names the draft the Goal field holds, so the note is not read as its caption', async () => {
    const page = mountSession({
      session: { session_goal: null, session_goal_cleared: { at: 450 } },
    });
    await settle(page);
    expect(text('[data-next-goal-ended]')).toMatch(
      /^Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d; the draft below is your first prompt$/,
    );
    expect(goalBox().value).toBe('Ship the queue worker');
  });

  it('says the clear once where the session opened with /goal, in the sentence that already exists', async () => {
    const page = mountSession({
      session: {
        session_goal: null,
        session_goal_cleared: { at: 450 },
        first_prompt: '/goal a file exists',
        first_prompt_control: true,
      },
    });
    await settle(page);
    expect(ended()).toBeNull();
    const all = document.body.textContent ?? '';
    expect(all.match(/was cleared at/g)).toHaveLength(1);
    expect(all).toContain('This session opened with /goal, so there is no first prompt');
  });

  it('draws no clear over a session that holds a goal again', async () => {
    const page = mountSession({
      session: { session_goal: { text: GOAL, at: 500 }, session_goal_cleared: { at: 450 } },
    });
    await settle(page);
    expect(ended()).toBeNull();
  });

  it('stays quiet while the update offer is on screen, for every note', async () => {
    for (const earlier of [
      { how: 'replaced', at: 600 },
      { how: 'met', at: 550 },
      { how: 'gave-up', at: 550 },
    ]) {
      const page = mountSession({
        store: { goal: 'My own goal', revision: 1 },
        session: {
          annotation_goal_saved_at: 400,
          session_goal: { text: LATER, at: 600, earlier },
        },
      });
      await settle(page);
      expect(document.querySelector('[data-next-goal-update]')).not.toBeNull();
      expect(ended()).toBeNull();
      page.unmount();
    }
  });

  it('never names the earlier goal', async () => {
    const page = mountSession({ session: held({ how: 'replaced', at: 450 }) });
    await settle(page);
    expect(text('[data-next-goal-ended]')).not.toContain('findings');
  });
});
