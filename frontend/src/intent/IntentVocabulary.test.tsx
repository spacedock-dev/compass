import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HELD_CUES, READ_FROM_NOW_WHY } from './sentences';
import { REVISION_DEFINITION } from '../drift/sentences';
import healthy from '../../test/fixtures/client-contract/data-healthy.json';
import { board, control, mountSession } from './panel.testing';
import { json } from './testing';

/* The Intent card speaks of the reader's words and the times they said them, never of a revision or an
   entry number: both are the store's bookkeeping and show the reader nothing they wrote or saw
   (docs/design-reading-a-session.md, "Revision numbers stay inside the store and the wire"). That holds for
   the discard sentences the server composes too: they are worded without it, and the cases below arm, land
   and open the menu over the sentences the live server recorded. */
const BOOKKEEPING = /revision|\bentry number|#\s?\d/i;

/* Every reader-facing string in the card: text, accessible names, titles and placeholders. */
function readerFacing(root: ParentNode): string[] {
  const strings: string[] = [];
  for (const node of root.querySelectorAll('*')) {
    for (const name of ['aria-label', 'title', 'placeholder']) {
      const value = node.getAttribute(name);
      if (value) strings.push(value);
    }
    for (const child of node.childNodes)
      if (child.nodeType === 3 && child.textContent?.trim()) strings.push(child.textContent.trim());
  }
  return strings;
}

/* The discard sentences as the real server published them (`annotate_discard`), recorded in the client contract. */
const RECORDED = healthy.response.body.annotate_discard as Record<string, string>;
const withRecorded = (data: object) => ({ ...data, annotate_discard: RECORDED });

describe('the words on the Intent card', () => {
  it('never name a revision in a recorded discard sentence', () => {
    expect(Object.keys(RECORDED).length).toBeGreaterThan(5);
    for (const sentence of Object.values(RECORDED)) expect(sentence).not.toMatch(BOOKKEEPING);
  });

  it('never name one while a discard is armed, once it has landed, or in the open menu', async () => {
    const DISCARDED = { annotation_discarded_at: 1000, annotation_revision_count: 0 };
    const page = mountSession({
      store: { goal: 'Saved goal', revision: 2 },
      routes: {
        '/api/annotate': () => {
          page.state.data = withRecorded(board(DISCARDED));
          return json({ ok: true, outcome: 'stored', persisted: true, withdrew: true });
        },
      },
    });
    await page.settle();
    await page.settle();
    page.state.data = withRecorded(page.state.data as object);
    await page.poll(page.state.data);
    const card = () => document.querySelector('.next-cockpit-held') as Element;
    fireEvent.click(screen.getByRole('button', { name: 'More about these words' }));
    const menu = [...document.querySelectorAll('[data-slot="popover-content"]')].flatMap(
      readerFacing,
    );
    expect(menu.join(' ')).toContain('Discard everything');
    for (const string of menu) expect(string).not.toMatch(BOOKKEEPING);
    await act(async () => {
      fireEvent.click(control('held-discard') as Element, { detail: 1 });
    });
    const armed = readerFacing(card());
    expect(armed.join(' ')).toContain(RECORDED['armed']);
    for (const string of armed) expect(string).not.toMatch(BOOKKEEPING);
    await act(async () => {
      page.clock.advance(1_300);
    });
    await act(async () => {
      fireEvent.click(control('held-discard') as Element, { detail: 1 });
    });
    await page.settle();
    await page.settle();
    const landed = readerFacing(card());
    expect(landed.join(' ')).toContain(RECORDED['stored']);
    for (const string of landed) expect(string).not.toMatch(BOOKKEEPING);
  });

  it('never name a revision or an entry number in a sentence the page owns', () => {
    for (const sentence of [...Object.values(HELD_CUES), READ_FROM_NOW_WHY, REVISION_DEFINITION])
      expect(sentence).not.toMatch(BOOKKEEPING);
  });

  it('never name one in the card as drawn: saved, with the later directions listed and the menu open', async () => {
    const choices = [{ fact_id: 'p1', text: 'Fix the login redirect', at: 100, cut: false }];
    const page = mountSession({
      store: { goal: 'Ship the queue worker', revision: 3 },
      session: { annotation_window_start: 1_000, annotation_at: 990 },
      routes: { '/api/project-context': () => json({ prompt_choices: choices }) },
    });
    await page.settle();
    await page.settle();
    const card = document.querySelector('.next-cockpit-held');
    expect(card).not.toBeNull();
    const strings = readerFacing(card as Element);
    expect(strings.length).toBeGreaterThan(5);
    for (const string of strings) expect(string).not.toMatch(BOOKKEEPING);
  });
});
