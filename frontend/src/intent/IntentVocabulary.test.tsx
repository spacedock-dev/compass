import { describe, expect, it } from 'vitest';
import { HELD_CUES, READ_FROM_NOW_WHY } from './sentences';
import { REVISION_DEFINITION } from '../drift/sentences';
import { mountSession } from './panel.testing';
import { json } from './testing';

/* The Intent card speaks of the reader's words and the times they said them, never of a revision or an
   entry number: both are the store's bookkeeping and show the reader nothing they wrote or saw
   (docs/design-reading-a-session.md, "Revision numbers stay inside the store and the wire"). Sentences the
   server composes, such as the discard account, are the server's to word and are held there. */
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

describe('the words on the Intent card', () => {
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
