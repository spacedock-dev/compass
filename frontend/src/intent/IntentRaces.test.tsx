import { openSelect, chooseSelect } from '../../test/select';
import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { json } from './testing';
import {
  board,
  control,
  goalBox,
  lineBoxes,
  mountSession,
  stored,
  text,
  type,
} from './panel.testing';
import { intentCtxFor } from './useIntent';

/* The races a request in flight opens, and the shapes a reply can take, each held to what the reader keeps. */

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};
const press = async (button: Element | null, detail = 1) => {
  await act(async () => {
    fireEvent.click(button as Element, { detail });
  });
};
const fact = (id: string, at: number, summary: string) => ({
  fact_id: id,
  type: 'user_message',
  by: 'person:me',
  summary,
  at,
  source_session: { harness: 'claude', sid: 's1' },
});
const SAVED_AT = { annotation_goal_saved_at: 500, annotation_at: 500 };

describe('words typed while a save is open', () => {
  it('stay in the box when the save lands, because only what was sent is dropped', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      routes: { '/api/annotate': () => 'hold' },
    });
    await settle(page);
    type(goalBox(), 'Sent words');
    await press(control('held-save'));
    type(goalBox(), 'Sent words and more typed meanwhile');
    page.state.data = board({}, { goal: 'Sent words', revision: 2 });
    await page.release('/api/annotate', stored(2));
    await settle(page);
    expect(goalBox().value).toBe('Sent words and more typed meanwhile');
    expect(control('held-save')?.getAttribute('aria-disabled')).not.toBe('true');
  });

  it('is not undone by Escape or Undo while the request is still being answered', async () => {
    const page = mountSession({
      store: { goal: 'Saved', lines: ['One'], revision: 1 },
      routes: { '/api/annotate': () => 'hold' },
    });
    await settle(page);
    type(goalBox(), 'Changed goal');
    type(lineBoxes()[0] as HTMLTextAreaElement, 'Changed line');
    await press(control('held-save'));
    fireEvent.keyDown(lineBoxes()[0] as HTMLTextAreaElement, { key: 'Escape' });
    await press(control('held-undo'));
    expect(lineBoxes()[0]?.value).toBe('Changed line');
    await page.release('/api/annotate', stored(2));
  });
});

describe('a prompt chosen and then cleared', () => {
  it('is gone: typing its exact words afterwards is a typed save, not an adoption', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 1 },
      routes: {
        '/api/project-context': () =>
          json({
            prompt_choices: [{ fact_id: 'p1', text: 'Fix the redirect', at: 100, cut: false }],
          }),
        '/api/annotate': () => stored(2),
      },
    });
    await settle(page);
    const select = document.querySelector('[data-next-cockpit-prompt-select]') as HTMLButtonElement;
    await openSelect(select);
    await page.settle();
    await chooseSelect(select, 'p1');
    await press(control('held-clear', 'goal'));
    expect(goalBox().value).toBe('');
    type(goalBox(), 'Fix the redirect');
    await press(control('held-save'));
    await settle(page);
    expect(page.allPosts()[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      goal: 'Fix the redirect',
      expected_revision: 1,
    });
  });

  it('is dropped by the panel once the server stops offering it and the record has been read', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 1 },
      routes: {
        '/api/project-context': () =>
          json({
            prompt_choices: [{ fact_id: 'p1', text: 'Fix the redirect', at: 100, cut: false }],
          }),
      },
    });
    await settle(page);
    const select = document.querySelector('[data-next-cockpit-prompt-select]') as HTMLButtonElement;
    await openSelect(select);
    await page.settle();
    await chooseSelect(select, 'p1');
    const ctx = intentCtxFor(page.shell);
    expect(ctx.held.chosen.size).toBe(1);
    page.state.routes['/api/project-context'] = () => json({ prompt_choices: [] });
    await openSelect(select);
    await page.settle();
    await page.settle();
    expect(ctx.held.chosen.size).toBe(0);
  });
});

describe('a reply that is not the one the page expected', () => {
  it('does not write the lines against a baseline an unchanged adoption did not own', async () => {
    const page = mountSession({
      session: {},
      routes: {
        '/api/annotate': () =>
          json({ ok: true, outcome: 'unchanged', persisted: true, revision: 4, saved_revision: 4 }),
      },
    });
    await settle(page);
    type(lineBoxes()[0] as HTMLTextAreaElement, 'A line');
    await press(control('held-save'));
    await settle(page);
    // The adoption repeated words stored at revision 4 while the press was drawn against 0: the receipt
    // proves nothing about the lines' baseline, so they are not written.
    expect(page.allPosts()).toHaveLength(1);
    expect(lineBoxes()[0]?.value).toBe('A line');
  });

  it('names a discard that withdrew nothing, and keeps the stored sentence when the server did not say', async () => {
    const sentences = {
      stored: 'Discarded.',
      unwithdrawn: 'Discarded, but the raise still quotes it.',
      armed: 'Armed.',
    };
    const run = async (reply: object) => {
      const page = mountSession({
        store: { goal: 'Saved', revision: 1 },
        routes: { '/api/annotate': () => json(reply) },
      });
      page.state.data = { ...(page.state.data as object), annotate_discard: sentences };
      await page.poll(page.state.data);
      await press(control('held-discard'));
      await act(async () => {
        page.clock.advance(1_300);
      });
      await press(control('held-discard'));
      await settle(page);
      const said = text('.next-cockpit-held-discard .next-cockpit-held-cue');
      page.unmount();
      return said;
    };
    expect(await run({ ok: true, outcome: 'stored', persisted: true, withdrew: false })).toBe(
      sentences.unwithdrawn,
    );
    expect(await run({ ok: true, outcome: 'stored', persisted: true })).toBe(sentences.stored);
  });
});

describe('Keep names the revision it drew, however the record moves', () => {
  it('sends the revision the whole text was drawn against, not the one now on the board', async () => {
    const long = 'A direction much longer than the first words the question quotes of it.';
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      session: SAVED_AT,
      routes: {
        '/api/project-context': () =>
          json({ semantic: { facts: [fact('f1', 600, 'A direction much longer')] } }),
        '/api/direction': () => json({ ok: true, text: long, clipped: false }),
        '/api/annotate': () => stored(1, { outcome: 'unchanged' }),
      },
    });
    await settle(page);
    await press(control('direction-keep'));
    await settle(page);
    // Another tab saves a newer revision before the reader presses again.
    await page.poll(board({ ...SAVED_AT }, { goal: 'Saved', revision: 2 }));
    await press(control('direction-keep'));
    await settle(page);
    const settleBody = page.allPosts().find((post) => post.path === '/api/annotate')?.body;
    expect(settleBody).toMatchObject({ expected_revision: 1 });
  });

  it('lets a reader see a clipped direction and refuses to settle it on another press', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      session: SAVED_AT,
      routes: {
        '/api/project-context': () => json({ semantic: { facts: [fact('f1', 600, 'Short.')] } }),
        '/api/direction': () => json({ results: [{ ok: true, text: 'Short.', clipped: true }] }),
        '/api/annotate': () => stored(1, { outcome: 'unchanged' }),
      },
    });
    await settle(page);
    // The clipped start is quoted, with its limit, before any press.
    expect(page.allPosts().map((post) => post.path)).toEqual(['/api/direction']);
    expect(text('.next-cockpit-direction-whole')).toContain(
      'Only the start of this direction is shown; it is longer than Compass opens.',
    );
    await press(control('direction-keep'));
    await settle(page);
    await press(control('direction-keep'));
    await settle(page);
    expect(page.allPosts().filter((post) => post.path === '/api/annotate')).toHaveLength(0);
    expect(text('.next-cockpit-direction-question')).toContain(
      'Nothing was settled and no analysis was started: Compass could not open the whole text of every direction Keep would settle, so it cannot show you what you would keep. Press again to retry.',
    );
  });

  it('opens a multi-line direction as the one line the store would hold', async () => {
    const page = mountSession({
      store: { goal: 'Saved', revision: 1 },
      session: SAVED_AT,
      routes: {
        '/api/project-context': () => json({ semantic: { facts: [fact('f1', 600, 'Two lines')] } }),
        '/api/direction': () => json({ ok: true, text: 'first line\nsecond line', clipped: false }),
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    expect(
      (document.querySelector('[data-next-cockpit-direction-key]') as HTMLTextAreaElement).value,
    ).toBe('first line second line');
  });
});
