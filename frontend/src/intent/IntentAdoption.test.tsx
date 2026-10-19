import { openSelect, chooseSelect } from '../../test/select';
import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { json } from './testing';
import {
  board,
  control,
  goalBox,
  inert,
  lineBoxes,
  mountSession,
  stored,
  text,
  type,
} from './panel.testing';

/* Prompt adoption: a prompt chosen from "Use your prompt" stands in the goal box as a pending adoption and
   saves nothing. Save intent adopts it, naming the fact, the words and the time, and nothing the reader
   typed, chose or changed while the request was open is dropped. */

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
const CHOICES = [
  { fact_id: 'p1', text: 'Fix the login redirect', at: 100, cut: false },
  { fact_id: 'p2', text: 'Then ship the queue worker behind a flag', at: 200, cut: true },
];
const menu = () => json({ prompt_choices: CHOICES });

async function open(page: Awaited<ReturnType<typeof mountSession>>) {
  await openSelect(select());
  await page.settle();
}

async function choose(page: Awaited<ReturnType<typeof mountSession>>, factId: string) {
  await open(page);
  await chooseSelect(select(), factId);
  await page.settle();
}

describe('the "Use your prompt" menu', () => {
  it('reads the prompts once per opening, by the reader’s gesture, and never from a poll', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      routes: { '/api/project-context': menu },
    });
    await settle(page);
    const before = page.state.requests.filter((r) => r.url.includes('prompts=1')).length;
    expect(before).toBe(0);
    await open(page);
    expect(page.state.requests.filter((r) => r.url.includes('prompts=1'))).toHaveLength(1);
    expect(page.state.requests.find((r) => r.url.includes('prompts=1'))?.url).toBe(
      '/api/project-context?project=%2Frepo%2Falpha&session=claude%3As1&prompts=1',
    );
    await page.poll({ ...(page.state.data as object), generated: 1200 });
    expect(page.state.requests.filter((r) => r.url.includes('prompts=1'))).toHaveLength(1);
    expect(page.posts()).toBe(0);
  });

  it('names each prompt by its place and time, marks an excerpt, and cuts the line at a word', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      routes: { '/api/project-context': menu },
    });
    await settle(page);
    await open(page);
    const labels = screen.getAllByRole('option').map((option) => option.textContent ?? '');
    expect(labels[0]).toMatch(/^First prompt · \d\d:\d\d Fix the login redirect$/);
    expect(labels[1]).toMatch(
      /^Latest prompt · \d\d:\d\d · excerpt Then ship the queue worker behind a flag$/,
    );
  });

  it('fills the box and says so, saves nothing, and puts the face back once the reader types over it', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 1 },
      routes: { '/api/project-context': menu },
    });
    await settle(page);
    await choose(page, 'p1');
    expect(goalBox().value).toBe('Fix the login redirect');
    expect(select().textContent).toContain('Fix the login redirect');
    expect(text('#next-cockpit-cue-status')).toBe('Goal filled from your prompt. Not saved.');
    expect(page.posts()).toBe(0);
    expect(inert(control('held-save'))).toBe(false);
    expect(inert(control('held-undo'))).toBe(false);
    type(goalBox(), 'Fix the login redirect, carefully');
    expect(select().textContent).toBe('Use your prompt');
    // Typed words replace the pending adoption, so the same prompt can be picked again.
    await choose(page, 'p1');
    expect(goalBox().value).toBe('Fix the login redirect');
  });

  it('is undone by Undo changes and by Escape, which put the saved goal back', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 1 },
      routes: { '/api/project-context': menu },
    });
    await settle(page);
    await choose(page, 'p1');
    await press(control('held-undo'));
    expect(goalBox().value).toBe('Saved goal');
    await choose(page, 'p2');
    fireEvent.keyDown(goalBox(), { key: 'Escape' });
    await page.settle();
    expect(goalBox().value).toBe('Saved goal');
    expect(page.posts()).toBe(0);
  });

  it('stops offering a prompt the server no longer lists, once the record has been read', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 1 },
      routes: { '/api/project-context': menu },
    });
    await settle(page);
    await choose(page, 'p1');
    expect(goalBox().value).toBe('Fix the login redirect');
    // The next opening finds a record that no longer holds it.
    page.state.routes['/api/project-context'] = () => json({ prompt_choices: [CHOICES[1]] });

    await open(page);
    expect(goalBox().value).toBe('Saved goal');
  });
});

describe('Save intent over an adopted prompt', () => {
  it('adopts the chosen prompt naming its fact, words and time, and the revision the box was drawn against', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 3 },
      routes: {
        '/api/project-context': menu,
        '/api/annotate': () => {
          page.state.data = board(
            {},
            {
              goal: 'Fix the login redirect',
              revision: 4,
              goal_source: 'chosen-prompt',
              goal_source_at: 100,
            },
          );
          return stored(4);
        },
      },
    });
    await settle(page);
    await choose(page, 'p1');
    await press(control('held-save'));
    await settle(page);
    expect(page.allPosts()).toHaveLength(1);
    expect(page.allPosts()[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      adopt: 'chosen-prompt',
      expected_prompt: 'Fix the login redirect',
      expected_prompt_at: 100,
      prompt_fact: 'p1',
      expected_revision: 3,
    });
    expect(goalBox().value).toBe('Fix the login redirect');
    expect(text('.next-cockpit-held-field[data-next-cockpit-held-field="goal"] small')).toMatch(
      /^From your prompt · \d\d:\d\d · saved$/,
    );
  });

  it('adopts an untouched first prompt with Save intent, and nothing else does', async () => {
    const page = mountSession({
      routes: {
        '/api/annotate': () => {
          page.state.data = board(
            {},
            {
              goal: 'Ship the queue worker',
              revision: 1,
              goal_source: 'first-prompt',
              goal_source_at: 100,
            },
          );
          return stored(1);
        },
      },
    });
    await settle(page);
    await press(control('held-save'));
    await settle(page);
    expect(page.allPosts()).toHaveLength(1);
    expect(page.allPosts()[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      adopt: 'first-prompt',
      expected_prompt: 'Ship the queue worker',
      expected_prompt_at: 100,
      expected_revision: 0,
    });
  });

  it('adopts the prompt first and writes the lines against the revision the adoption minted', async () => {
    let calls = 0;
    const page = mountSession({
      routes: {
        '/api/annotate': () => {
          calls += 1;
          return calls === 1
            ? json({ ok: true, outcome: 'stored', persisted: true, revision: 5, saved_revision: 5 })
            : stored(6);
        },
      },
    });
    await settle(page);
    type(lineBoxes()[0] as HTMLTextAreaElement, 'The queue drains');
    await press(control('held-line-add'));
    await press(control('held-line-add'));
    await press(control('held-save'));
    await settle(page);
    const [first, second] = page.allPosts();
    expect(page.allPosts()).toHaveLength(2);
    expect(first?.body).toMatchObject({ adopt: 'first-prompt', expected_revision: 0 });
    // The second request carries the lines, no goal, and the revision the adoption's receipt named.
    expect(second?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      goal: null,
      lines: ['The queue drains'],
      // A line the reader added here has no stored position.
      origins: [null],
      expected_revision: 5,
    });
  });

  it('refuses to write the lines when the adoption’s receipt does not name the revision it minted', async () => {
    const page = mountSession({
      routes: {
        '/api/annotate': () =>
          json({ ok: true, outcome: 'stored', persisted: true, revision: 7, saved_revision: 5 }),
      },
    });
    await settle(page);
    type(lineBoxes()[0] as HTMLTextAreaElement, 'The queue drains');
    await press(control('held-save'));
    await settle(page);
    expect(page.allPosts()).toHaveLength(1);
    expect(text('.next-cockpit-held-footer .next-cockpit-held-cue')).toMatch(/^Not saved\./);
    expect(lineBoxes()[0]?.value).toBe('The queue drains');
  });

  it('keeps words typed while the adoption was open, as an unsaved edit over the adopted goal', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 1 },
      routes: { '/api/project-context': menu, '/api/annotate': () => 'hold' },
    });
    await settle(page);
    await choose(page, 'p1');
    await press(control('held-save'));
    type(goalBox(), 'Words typed while it saved');
    page.state.data = board(
      {},
      {
        goal: 'Fix the login redirect',
        revision: 2,
        goal_source: 'chosen-prompt',
        goal_source_at: 100,
      },
    );
    await page.release('/api/annotate', stored(2));
    await settle(page);
    expect(goalBox().value).toBe('Words typed while it saved');
    expect(inert(control('held-save'))).toBe(false);
  });

  it('keeps a prompt picked while the request was open, as the reader’s newer choice', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 1 },
      routes: { '/api/project-context': menu, '/api/annotate': () => 'hold' },
    });
    await settle(page);
    await choose(page, 'p1');
    await press(control('held-save'));
    await choose(page, 'p2');
    page.state.data = board(
      {},
      {
        goal: 'Fix the login redirect',
        revision: 2,
        goal_source: 'chosen-prompt',
        goal_source_at: 100,
      },
    );
    await page.release('/api/annotate', stored(2));
    await settle(page);
    expect(goalBox().value).toBe('Then ship the queue worker behind a flag');
  });

  it('says the store could not take the save when it is untrusted, and not that the prompt changed', async () => {
    const page = mountSession({
      routes: { '/api/annotate': () => json({ ok: true, outcome: 'untrusted', persisted: false }) },
    });
    await settle(page);
    await press(control('held-save'));
    await settle(page);
    expect(page.allPosts()).toHaveLength(1);
    expect(goalBox().value).toBe('Ship the queue worker');
  });
});
