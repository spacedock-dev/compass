import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { chooseSelect, openSelect } from '../../test/select';
import { json } from './testing';
import { board, control, goalBox, mountSession, stored, text, type } from './panel.testing';

/* A goal the session set with /goal is the working goal until the reader edits it, and one that arrives
   after the reader saved their own is offered, never written over their words. */

const GOAL = 'The findings file exists and every check in it passes';
const LATER = 'The findings file is split by area and every check passes';
const DETECTED = { text: GOAL, at: 500 };

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};
const press = async (button: Element | null) => {
  await act(async () => {
    fireEvent.click(button as Element);
  });
};
const select = (): HTMLButtonElement =>
  document.querySelector('[data-next-cockpit-prompt-select]') as HTMLButtonElement;
const mark = () => document.querySelector('[data-next-goal-detected]');
const offer = () => document.querySelector('[data-next-goal-update]');
const source = () => text('[data-next-cockpit-goal-source]');

const savedOwn = {
  store: { goal: 'My own goal', revision: 1 },
  session: { annotation_goal_saved_at: 400 },
};

describe('a /goal over a session with no saved goal', () => {
  it('fills the Goal field and marks it detected, with the provenance line in its existing form', async () => {
    const page = mountSession({ session: { session_goal: DETECTED } });
    await settle(page);
    expect(goalBox().value).toBe(GOAL);
    expect(mark()?.textContent).toBe('Goal detected');
    expect(source()).toMatch(/^From your \/goal at \d\d:\d\d · not saved$/);
    expect(page.posts()).toBe(0);
  });

  it('calls the untouched detected goal a draft, and an edit of it unsaved changes', async () => {
    const page = mountSession({ session: { session_goal: DETECTED } });
    await settle(page);
    expect(text('[data-next-intent-status]')).toBe('Draft');
    type(goalBox(), `${GOAL}, and the report is linked`);
    expect(text('[data-next-intent-status]')).toBe('Unsaved changes');
  });

  it('is drafted ahead of the first prompt, and where the session opened with a harness command', async () => {
    const page = mountSession({
      session: { session_goal: DETECTED, first_prompt: '/goal', first_prompt_control: true },
    });
    await settle(page);
    expect(goalBox().value).toBe(GOAL);
    expect(mark()).not.toBeNull();
  });

  it('drops the detected mark when the reader edits the field, and says the words are theirs', async () => {
    const page = mountSession({ session: { session_goal: DETECTED } });
    await settle(page);
    type(goalBox(), `${GOAL}, and the report is linked`);
    expect(mark()).toBeNull();
    expect(source()).toBe('Your edit of your /goal · not saved');
    type(goalBox(), 'Something else entirely');
    expect(source()).toBe('You typed this · not saved');
  });

  it('is replaced by a prompt the reader chooses, and the line says so', async () => {
    const page = mountSession({
      session: { session_goal: DETECTED },
      routes: {
        '/api/project-context': () =>
          json({ prompt_choices: [{ fact_id: 'p1', text: 'Fix the login redirect', at: 100 }] }),
      },
    });
    await settle(page);
    await openSelect(select());
    await page.settle();
    await chooseSelect(select(), 'p1');
    await page.settle();
    expect(goalBox().value).toBe('Fix the login redirect');
    expect(mark()).toBeNull();
    expect(source()).toMatch(/^Drafted from the prompt you chose · not saved/);
  });

  it('lists the detected goal first in the prompt list, ahead of the session’s prompts', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      session: { session_goal: DETECTED, annotation_goal_saved_at: 900 },
      routes: {
        '/api/project-context': () =>
          json({ prompt_choices: [{ fact_id: 'p1', text: 'Fix the login redirect', at: 100 }] }),
      },
    });
    await settle(page);
    await openSelect(select());
    await page.settle();
    const labels = screen.getAllByRole('option').map((option) => option.textContent ?? '');
    expect(labels[0]).toMatch(new RegExp(`^Goal detected · \\d\\d:\\d\\d ${GOAL}$`));
    expect(labels[1]).toMatch(/^First prompt/);
  });

  it('saves with Save intent, naming the goal and its time', async () => {
    const page = mountSession({
      session: { session_goal: DETECTED },
      routes: { '/api/annotate': () => stored(1) },
    });
    await settle(page);
    await press(control('held-save'));
    await settle(page);
    expect(page.allPosts()[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      adopt: 'session-goal',
      expected_prompt: GOAL,
      expected_prompt_at: 500,
      expected_revision: 0,
    });
  });

  it('offers a goal over the 240-character limit as its excerpt, with a note that it was cut', async () => {
    const excerpt = GOAL.slice(0, 30);
    const page = mountSession({
      session: { session_goal: { text: `${GOAL} ${GOAL}`, at: 500, offered: excerpt, cut: true } },
    });
    await settle(page);
    expect(goalBox().value).toBe(excerpt);
    expect(source()).toMatch(
      / · Shortened to fit 240 characters; Analyze reads this shortened goal$/,
    );
  });

  it('keeps the cut note once the cut goal is saved, while the session still states that /goal', async () => {
    const excerpt = GOAL.slice(0, 30);
    const cutGoal = { text: `${GOAL} ${GOAL}`, at: 500, offered: excerpt, cut: true };
    const page = mountSession({
      store: { goal: excerpt, revision: 1, goal_source: 'session-goal', goal_source_at: 500 },
      session: { session_goal: cutGoal },
    });
    await settle(page);
    expect(source()).toMatch(
      / · saved · Shortened to fit 240 characters; Analyze reads this shortened goal$/,
    );
  });

  it('says nothing of a cut once the saved words are not the session’s cut goal', async () => {
    const page = mountSession({
      store: { goal: GOAL, revision: 1, goal_source: 'session-goal', goal_source_at: 500 },
      session: { session_goal: DETECTED },
    });
    await settle(page);
    expect(source()).toMatch(/· saved$/);
  });

  it('reads a Codex /goal the same way', async () => {
    const page = mountSession({
      hash: '#n=session:alpha%2Fapp:codex:s1',
      session: { harness: 'codex', session_goal: DETECTED },
    });
    await settle(page);
    expect(goalBox().value).toBe(GOAL);
    expect(mark()?.textContent).toBe('Goal detected');
    expect(source()).toMatch(/^From your \/goal at \d\d:\d\d · not saved$/);
  });

  it('reads an Antigravity /goal the same way', async () => {
    const page = mountSession({
      hash: '#n=session:alpha%2Fapp:antigravity:s1',
      session: { harness: 'antigravity', session_goal: DETECTED },
    });
    await settle(page);
    expect(goalBox().value).toBe(GOAL);
    expect(mark()?.textContent).toBe('Goal detected');
  });

  it('reads no goal into a session whose harness publishes none', async () => {
    const page = mountSession({ session: { harness: 'pi', session_goal: DETECTED } });
    await settle(page);
    expect(mark()).toBeNull();
  });
});

describe('a /goal after the reader saved their own', () => {
  it('shows an update offer naming the new goal and its time, and leaves the saved words alone', async () => {
    const page = mountSession({
      ...savedOwn,
      session: { ...savedOwn.session, session_goal: { text: LATER, at: 600 } },
    });
    await settle(page);
    expect(goalBox().value).toBe('My own goal');
    expect(mark()).toBeNull();
    expect(offer()?.textContent).toMatch(/^Your \/goal changed at \d\d:\d\d: /);
    expect(offer()?.textContent).toContain(LATER);
    expect(control('goal-update-use')?.textContent).toBe('Use this goal');
    expect(control('goal-update-keep')?.textContent).toBe('Keep my goal');
    expect(page.posts()).toBe(0);
  });

  it('is not offered for a /goal older than the saved words, or the same words', async () => {
    const older = mountSession({
      ...savedOwn,
      session: { ...savedOwn.session, session_goal: { text: LATER, at: 300 } },
    });
    await settle(older);
    expect(offer()).toBeNull();
    older.unmount();
    const same = mountSession({
      store: { goal: LATER, revision: 1 },
      session: { annotation_goal_saved_at: 400, session_goal: { text: LATER, at: 600 } },
    });
    await settle(same);
    expect(offer()).toBeNull();
  });

  it('puts the new goal in the box when taken, and records its source and time on Save intent', async () => {
    const page = mountSession({
      ...savedOwn,
      session: { ...savedOwn.session, session_goal: { text: LATER, at: 600 } },
      routes: { '/api/annotate': () => stored(2) },
    });
    await settle(page);
    await press(control('goal-update-use'));
    expect(goalBox().value).toBe(LATER);
    expect(offer()).toBeNull();
    expect(mark()?.textContent).toBe('Goal detected');
    expect(page.posts()).toBe(0);
    await press(control('held-save'));
    await settle(page);
    expect(page.allPosts()[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      adopt: 'session-goal',
      expected_prompt: LATER,
      expected_prompt_at: 600,
      expected_revision: 1,
    });
  });

  it('keeps the saved goal when asked, across a refresh, and offers a still later /goal again', async () => {
    const withGoal = (goal: { text: string; at: number }) =>
      board(
        { annotation_goal_saved_at: 400, session_goal: goal },
        { goal: 'My own goal', revision: 1 },
      );
    const page = mountSession({
      ...savedOwn,
      session: { ...savedOwn.session, session_goal: { text: LATER, at: 600 } },
    });
    await settle(page);
    await press(control('goal-update-keep'));
    expect(offer()).toBeNull();
    expect(goalBox().value).toBe('My own goal');
    await page.poll(withGoal({ text: LATER, at: 600 }));
    expect(offer()).toBeNull();
    await page.poll(withGoal({ text: 'A third goal', at: 700 }));
    expect(offer()?.textContent).toContain('A third goal');
  });

  it('shows the cut note in the offer for a goal over the limit', async () => {
    const page = mountSession({
      ...savedOwn,
      session: {
        ...savedOwn.session,
        session_goal: { text: `${LATER} ${LATER}`, at: 600, offered: LATER, cut: true },
      },
    });
    await settle(page);
    expect(offer()?.textContent).toMatch(/cut to fit the goal limit/i);
  });
});
