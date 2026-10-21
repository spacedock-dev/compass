import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { chooseSelect, openSelect } from '../../test/select';
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

/* The goal and outcome editor, read the way a reader meets it: the words in the boxes, the sentences
   under them, and what a press sends. Every assertion quotes the rendered text, not the data behind it. */

const footerCue = () => text('.next-cockpit-held-footer .next-cockpit-held-cue');

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};

describe('a goal-less session arrives with its first prompt drafted and nothing sent', () => {
  it('shows the first prompt as an unsaved draft and sends no request on mount, under StrictMode', async () => {
    const page = mountSession();
    await settle(page);
    expect(goalBox().value).toBe('Ship the queue worker');
    expect(text('[data-next-cockpit-draft-marks]')).toBe('From your prompt · first · not saved.');
    // The draft is adopted by Save intent, which is live over it; nothing else is.
    expect(inert(control('held-save'))).toBe(false);
    expect(control('held-undo')?.getAttribute('aria-disabled')).toBe('true');
    expect(page.posts()).toBe(0);
    expect(page.state.requests.filter((r) => r.method !== 'GET').length).toBe(0);
  });

  it('reads nothing it was not asked to: the observed record only, and only as a passive read', async () => {
    const page = mountSession();
    await settle(page);
    const paths = new Set(page.state.requests.map((r) => `${r.method} ${r.path}`));
    expect([...paths].sort()).toEqual([
      'GET /api/data',
      'GET /api/project-context',
      'GET /api/session-record',
    ]);
  });
});

describe('typing in the goal box', () => {
  it('counts against the server bound and takes the draft marks away on the first edit', async () => {
    const page = mountSession();
    await settle(page);
    type(goalBox(), 'Ship the queue worker, then verify');
    expect(text('[data-next-cockpit-held-count="goal"]')).toBe('34 / 240');
    expect(document.querySelector('[data-next-cockpit-draft-marks]')).toBeNull();
    expect(inert(control('held-undo'))).toBe(false);
    expect(page.posts()).toBe(0);
  });

  it('collapses a pasted line break to the one space the store would keep, and cuts at the bound', async () => {
    const page = mountSession();
    await settle(page);
    type(goalBox(), 'one\ntwo');
    expect(goalBox().value).toBe('one two');
    type(goalBox(), 'x'.repeat(300));
    expect(goalBox().value).toHaveLength(240);
    expect(text('[data-next-cockpit-held-count="goal"]')).toBe('240 / 240');
  });

  it('keeps the words, the caret and the selection across a board refresh that changes nothing they stand on', async () => {
    const page = mountSession();
    await settle(page);
    const box = goalBox();
    type(box, 'my own words');
    box.setSelectionRange(3, 6);
    await page.poll({ ...(page.state.data as object), generated: 1100 });
    expect(goalBox()).toBe(box);
    expect(box.value).toBe('my own words');
    expect([box.selectionStart, box.selectionEnd]).toEqual([3, 6]);
  });

  it('keeps an unsaved draft when the reader leaves the session and comes back', async () => {
    const page = mountSession();
    await settle(page);
    type(goalBox(), 'half a sentence');
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(goalBox().value).toBe('half a sentence');
    expect(page.posts()).toBe(0);
  });

  it('puts another tab’s save into an untouched box, and leaves a box the reader is typing in alone', async () => {
    const page = mountSession({ store: { goal: 'Saved elsewhere', revision: 1 } });
    await settle(page);
    expect(goalBox().value).toBe('Saved elsewhere');
    await page.poll({
      ...(page.state.data as object),
      sessions: [
        {
          ...(page.state.data as { sessions: object[] }).sessions[0],
          annotation_goal: 'Saved elsewhere, edited',
          annotation_revision: 2,
        },
      ],
    });
    expect(goalBox().value).toBe('Saved elsewhere, edited');
    type(goalBox(), 'typing now');
    await page.poll({
      ...(page.state.data as object),
      sessions: [
        {
          ...(page.state.data as { sessions: object[] }).sessions[0],
          annotation_goal: 'A third save',
          annotation_revision: 3,
        },
      ],
    });
    expect(goalBox().value).toBe('typing now');
  });
});

describe('Save intent', () => {
  it('sends the typed goal once, with the revision both boxes were drawn against, and says it saved', async () => {
    const page = mountSession({
      routes: {
        '/api/annotate': (request) => {
          page.state.data = await_board(request.body?.['goal'] as string);
          return stored(1);
        },
      },
    });
    function await_board(goal: string) {
      return board({}, { goal, revision: 1, goal_source: '' });
    }
    await settle(page);
    type(goalBox(), 'Land the worker behind a flag');
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    const posts = page.allPosts();
    expect(posts).toHaveLength(1);
    expect(posts[0]?.path).toBe('/api/annotate');
    expect(posts[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      goal: 'Land the worker behind a flag',
      expected_revision: 0,
    });
    expect(footerCue()).toBe('Saved as a new revision.');
    // And once, in the polite region, after the paint that shows it.
    expect(text('#next-cockpit-cue-status')).toBe('Saved as a new revision.');
    expect(goalBox().value).toBe('Land the worker behind a flag');
    expect(inert(control('held-save'))).toBe(true);
  });

  it.each([
    ['an ended session says what the words cannot do beside the confirmation', 999, true],
    ['a live session says only that it saved', null, false],
  ])('on %s', async (_name, endedAt, caveat) => {
    const page = mountSession({
      ...(endedAt === null ? {} : { session: { ended_at: endedAt } }),
      routes: {
        '/api/annotate': (request) => {
          page.state.data = board(endedAt === null ? {} : { ended_at: endedAt }, {
            goal: request.body?.['goal'] as string,
            revision: 1,
            goal_source: '',
          });
          return stored(1);
        },
      },
    });
    await settle(page);
    type(goalBox(), 'Land the worker behind a flag');
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    expect(footerCue()).toBe(
      caveat
        ? 'Saved as a new revision. This session has ended. Words you save now cannot be read against it; your saved intent and the goal drafted from your prompt still can.'
        : 'Saved as a new revision.',
    );
  });

  it('does not repeat the ended-session caveat beside a refused save', async () => {
    const page = mountSession({
      session: { ended_at: 999 },
      store: { goal: 'Saved', revision: 1 },
      routes: { '/api/annotate': () => json({ ok: true, outcome: 'refused', persisted: false }) },
    });
    await settle(page);
    type(goalBox(), 'Edited words');
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    expect(footerCue()).toBe(
      'Not saved. The server refused the write, and your words are still in the box.',
    );
  });

  it('sends nothing from an inert control and nothing twice', async () => {
    const page = mountSession({ store: { goal: 'Saved', revision: 1 } });
    await settle(page);
    expect(inert(control('held-save'))).toBe(true);
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    expect(page.posts()).toBe(0);
    type(goalBox(), 'Edited');
    page.state.routes['/api/annotate'] = () => 'hold';
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
      fireEvent.click(control('held-save') as Element);
    });
    expect(page.posts()).toBe(1);
    await page.release('/api/annotate', stored(2));
  });

  it('keeps the words and says the server refused, when the store refuses the write', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      routes: { '/api/annotate': () => json({ ok: true, outcome: 'refused', persisted: false }) },
    });
    await settle(page);
    type(goalBox(), 'Edited words');
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    expect(footerCue()).toBe(
      'Not saved. The server refused the write, and your words are still in the box.',
    );
    expect(goalBox().value).toBe('Edited words');
  });

  it('takes a refusal’s cue away at the next keystroke, which is a fresh attempt on different words', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      routes: { '/api/annotate': () => json({ ok: true, outcome: 'refused', persisted: false }) },
    });
    await settle(page);
    type(goalBox(), 'Edited words');
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    expect(footerCue()).toMatch(/^Not saved\./);
    type(goalBox(), 'Edited words again');
    expect(footerCue()).toBe('');
  });

  it('keeps the words and says it cannot tell, when no answer can be read', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      routes: { '/api/annotate': () => new Response('<html>', { status: 200 }) },
    });
    await settle(page);
    type(goalBox(), 'Edited words');
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    expect(footerCue()).toBe(
      'Compass did not answer, so this page cannot tell whether your intent was saved. Your words are still in the box.',
    );
    expect(goalBox().value).toBe('Edited words');
    expect(page.posts()).toBe(1);
  });

  it('says a store that could not be written is not stored, and keeps what was typed', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      routes: {
        '/api/annotate': () => json({ ok: true, outcome: 'unwritable', persisted: false }),
      },
    });
    await settle(page);
    type(goalBox(), 'Edited words');
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    expect(footerCue()).toMatch(/^Not stored\./);
    expect(goalBox().value).toBe('Edited words');
  });

  it('drops the draft when the words already match the stored revision, because they are on disk', async () => {
    const page = mountSession({
      store: { goal: 'Same words', revision: 1 },
      routes: {
        '/api/annotate': () =>
          json({ ok: true, outcome: 'unchanged', persisted: true, revision: 1, saved_revision: 1 }),
      },
    });
    await settle(page);
    type(goalBox(), 'Same words ');
    type(goalBox(), 'Same words');
    // Back to the stored words is not an edit: Save is inert and nothing needs sending.
    expect(inert(control('held-save'))).toBe(true);
  });
});

describe('Undo changes', () => {
  it('puts both boxes back and sends nothing', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', lines: ['A saved line'], revision: 2 },
    });
    await settle(page);
    type(goalBox(), 'edited goal');
    type(lineBoxes()[0] as HTMLTextAreaElement, 'edited line');
    await act(async () => {
      fireEvent.click(control('held-undo') as Element);
    });
    await settle(page);
    expect(goalBox().value).toBe('Saved goal');
    expect(lineBoxes().map((box) => box.value)).toEqual(['A saved line']);
    expect(page.posts()).toBe(0);
    expect(control('held-undo')?.getAttribute('aria-disabled')).toBe('true');
  });

  it('is Escape in the goal box, and Escape in a line puts the whole list back', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', lines: ['One', 'Two'], revision: 2 },
    });
    await settle(page);
    type(goalBox(), 'edited goal');
    fireEvent.keyDown(goalBox(), { key: 'Escape' });
    await settle(page);
    expect(goalBox().value).toBe('Saved goal');
    await act(async () => {
      fireEvent.click(control('held-line-add') as Element);
    });
    expect(lineBoxes()).toHaveLength(3);
    fireEvent.keyDown(lineBoxes()[0] as HTMLTextAreaElement, { key: 'Escape' });
    await settle(page);
    expect(lineBoxes().map((box) => box.value)).toEqual(['One', 'Two']);
  });
});

describe('header status and goal source line', () => {
  it('derives the lede, numbered outcome lines, source line, and header status across typed, prompt, saving, refused, unconfirmed, and concurrent-revision states', async () => {
    const page = mountSession({
      session: { first_prompt: '', first_prompt_at: null },
      routes: { '/api/annotate': () => 'hold' },
    });
    await settle(page);
    expect(text('[data-next-intent-lede]')).toBe(
      'Say what this session should achieve. Type it, or start from a prompt you gave the session. Compass reads the session against these words and never writes into the session.',
    );
    expect(text('[data-next-cockpit-held-line-number="0"]')).toBe('1');
    expect(text('[data-next-intent-status]')).toBe('');
    expect(text('[data-next-cockpit-goal-source]')).toBe('');

    type(goalBox(), 'Typed goal');
    expect(text('[data-next-cockpit-goal-source]')).toBe('Typed · not saved');
    expect(text('[data-next-intent-status]')).toBe('Unsaved changes');

    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    expect(text('[data-next-intent-status]')).toBe('Saving…');

    page.state.data = board({}, { goal: 'Typed goal', revision: 1, goal_source: '' });
    await page.release('/api/annotate', stored(1));
    await settle(page);
    expect(text('[data-next-intent-status]')).toBe('Saved');
    expect(text('[data-next-cockpit-goal-source]')).toMatch(/^Typed · saved \d\d:\d\d$/);

    // Concurrent revision while holding a local edit keeps Unsaved changes.
    type(goalBox(), 'Typed goal — local edit');
    expect(text('[data-next-intent-status]')).toBe('Unsaved changes');
    await page.poll(board({}, { goal: 'Concurrent save', revision: 2, goal_source: '' }));
    expect(text('[data-next-intent-status]')).toBe('Unsaved changes');
    expect(goalBox().value).toBe('Typed goal — local edit');

    // Refused save shows Not saved in the header.
    page.state.routes['/api/annotate'] = () =>
      json({ ok: true, outcome: 'refused', persisted: false });
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    expect(text('[data-next-intent-status]')).toBe('Not saved');

    // Unconfirmed save shows Not confirmed in the header.
    type(goalBox(), 'Typed goal — retry');
    expect(text('[data-next-intent-status]')).toBe('Unsaved changes');
    page.state.routes['/api/annotate'] = () => new Response('<html>', { status: 200 });
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    expect(text('[data-next-intent-status]')).toBe('Not confirmed');
  });

  it('distinguishes adopted-then-edited from cleared-then-typed over a prompt', async () => {
    const page = mountSession({
      store: {
        goal: 'Ship the queue worker',
        revision: 1,
        goal_source: 'first-prompt',
        goal_source_at: 100,
      },
    });
    await settle(page);
    expect(text('[data-next-cockpit-goal-source]')).toBe('From your prompt · first · saved');
    type(goalBox(), 'Ship the queue worker, carefully');
    expect(text('[data-next-cockpit-goal-source]')).toBe('From your prompt, edited · not saved');
    await act(async () => {
      fireEvent.click(control('held-clear') as Element);
    });
    expect(text('[data-next-cockpit-goal-source]')).toBe('');
    type(goalBox(), 'Freshly typed goal');
    expect(text('[data-next-cockpit-goal-source]')).toBe('Typed · not saved');
  });
});

describe('the header status and source line after a prompt adoption', () => {
  const press = async (button: Element | null) => {
    await act(async () => {
      fireEvent.click(button as Element);
    });
  };
  const adopted = (page: Awaited<ReturnType<typeof mountSession>>) => () => {
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
  };

  it('says Saved once a refused adoption is pressed again and lands', async () => {
    const page = mountSession({
      routes: { '/api/annotate': () => json({ ok: true, outcome: 'untrusted', persisted: false }) },
    });
    await settle(page);
    await press(control('held-save'));
    await settle(page);
    expect(text('[data-next-intent-status]')).toBe('Not saved');
    page.state.routes['/api/annotate'] = adopted(page);
    await press(control('held-save'));
    await settle(page);
    expect(text('[data-next-intent-status]')).toBe('Saved');
    expect(text('[data-next-cockpit-goal-source]')).toBe('From your prompt · first · saved');
  });

  it('says Saved once an unconfirmed adoption is pressed again and lands', async () => {
    const page = mountSession({
      routes: { '/api/annotate': () => new Response('<html>', { status: 200 }) },
    });
    await settle(page);
    await press(control('held-save'));
    await settle(page);
    expect(text('[data-next-intent-status]')).toBe('Not confirmed');
    page.state.routes['/api/annotate'] = adopted(page);
    await press(control('held-save'));
    await settle(page);
    expect(text('[data-next-intent-status]')).toBe('Saved');
  });

  it('keeps an adopted goal’s stamp when a lines-only revision moves the annotation’s time', async () => {
    const store = {
      goal: 'Ship the queue worker',
      revision: 1,
      goal_source: 'first-prompt',
      goal_source_at: 100,
    };
    const page = mountSession({ store });
    await settle(page);
    const before = text('[data-next-cockpit-goal-source]');
    expect(before).toBe('From your prompt · first · saved');
    await page.poll(
      board({ annotation_at: 5000 }, { ...store, revision: 2, lines: ['Tests pass'] }),
    );
    await settle(page);
    expect(text('[data-next-cockpit-goal-source]')).toBe(before);
  });

  it('ends the saved stamp with a sentence before an excerpt’s note', async () => {
    const page = mountSession({
      store: {
        goal: 'Ship the queue worker behind…',
        revision: 1,
        goal_source: 'first-prompt',
        goal_source_at: 100,
      },
    });
    await settle(page);
    expect(text('[data-next-cockpit-goal-source]')).toBe(
      'From your prompt · first · saved. Excerpt. Analyze looks up the source when pressed.',
    );
  });

  it('calls words typed over the whole drafted prompt in one change Typed, and a kept prompt edited', async () => {
    const page = mountSession();
    await settle(page);
    type(goalBox(), 'Rewrite the billing export');
    expect(text('[data-next-cockpit-goal-source]')).toBe('Typed · not saved');
    type(goalBox(), 'Ship the queue worker, carefully');
    expect(text('[data-next-cockpit-goal-source]')).toBe('From your prompt, edited · not saved');
  });
});

describe('the header status over a change Save intent would not write', () => {
  it('says nothing unsaved when a drafted prompt is emptied over a goal-less session', async () => {
    const page = mountSession();
    await settle(page);
    type(goalBox(), '');
    expect(inert(control('held-save'))).toBe(true);
    expect(text('[data-next-intent-status]')).toBe('');
  });

  it('drops a chosen prompt when the stored goal is typed back over it', async () => {
    const choices = [{ fact_id: 'p1', text: 'Fix the login redirect', at: 100, cut: false }];
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 1 },
      routes: { '/api/project-context': () => json({ prompt_choices: choices }) },
    });
    await settle(page);
    const select = document.querySelector('[data-next-cockpit-prompt-select]') as HTMLButtonElement;
    await openSelect(select);
    await page.settle();
    await chooseSelect(select, 'p1');
    await page.settle();
    expect(goalBox().value).toBe('Fix the login redirect');
    type(goalBox(), 'Saved goal');
    await settle(page);
    expect(text('[data-next-intent-status]')).toBe('Saved');
    expect(inert(control('held-save'))).toBe(true);
    expect(control('held-undo')?.getAttribute('aria-disabled')).toBe('true');
  });
});
