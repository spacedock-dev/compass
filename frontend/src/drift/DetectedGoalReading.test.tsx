import { describe, expect, it } from 'vitest';
import { goalBox, type } from '../intent/panel.testing';
import { byAction, json, mountDrift, press, readingPosts } from './testing';

/* Analyze drift over a session whose only goal is the one it set with /goal: the press adopts that goal
   by name, with its words and its time, so the model reads against what the reader sees. */
const GOAL = 'The findings file exists and every check in it passes';
const routes = { '/api/reading': () => json({ ok: true, job: { id: 'j1', steps: [] } }) };
const goalless = { store: { goal: '', lines: [], revision: 0 } };

describe('Analyze drift on a detected goal', () => {
  it('sends that goal, by source, words and time, when the reader has not edited it', async () => {
    const page = mountDrift({
      ...goalless,
      session: { session_goal: { text: GOAL, at: 500 } },
      routes,
    });
    await page.settle();
    await page.settle();
    expect(goalBox().value).toBe(GOAL);
    await press(byAction('reading-ask'));
    await page.settle();
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).toMatchObject({
      adopt: 'session-goal',
      expected_prompt: GOAL,
      expected_prompt_at: 500,
      expected_revision: 0,
    });
  });

  it('sends the excerpt, never the whole words, for a goal over the Goal limit', async () => {
    const excerpt = GOAL.slice(0, 30).trim();
    const page = mountDrift({
      ...goalless,
      session: { session_goal: { text: `${GOAL} ${GOAL}`, at: 500, offered: excerpt, cut: true } },
      routes,
    });
    await page.settle();
    await page.settle();
    await press(byAction('reading-ask'));
    await page.settle();
    expect(readingPosts(page)[0]?.body).toMatchObject({
      adopt: 'session-goal',
      expected_prompt: excerpt,
    });
  });

  it('is refused over an edit, so the model never reads words that are not on screen', async () => {
    const page = mountDrift({
      ...goalless,
      session: { session_goal: { text: GOAL, at: 500 } },
      routes,
    });
    await page.settle();
    await page.settle();
    type(goalBox(), `${GOAL}, and the report is linked`);
    await press(byAction('reading-ask'));
    await page.settle();
    expect(readingPosts(page)).toEqual([]);
  });
});
