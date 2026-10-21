import { act, fireEvent } from '@testing-library/react';
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

/* The expected outcome: a checklist of up to six lines held as one draft, so adding, removing and typing
   survive a redraw, and a seventh is refused where the reader meets it. */

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};
const press = async (button: Element | null) => {
  await act(async () => {
    fireEvent.click(button as Element);
  });
};

describe('the outcome checklist', () => {
  it('offers one empty box where nothing is saved, and adding to it adds the second', async () => {
    const page = mountSession({ store: { goal: 'Saved', revision: 1 } });
    await settle(page);
    expect(lineBoxes()).toHaveLength(1);
    expect(lineBoxes()[0]?.value).toBe('');
    expect(control('held-line-add')).not.toBeNull();
    type(lineBoxes()[0] as HTMLTextAreaElement, 'A check');
    await press(control('held-line-add'));
    expect(lineBoxes()).toHaveLength(2);
    expect(document.activeElement).toBe(lineBoxes()[1]);
  });

  it('refuses a seventh line in place, says so aloud, and keeps the control on the page and inert', async () => {
    const page = mountSession({
      store: { goal: 'Saved', lines: ['1', '2', '3', '4', '5', '6'], revision: 2 },
    });
    await settle(page);
    expect(lineBoxes()).toHaveLength(6);
    const add = control('held-line-add');
    expect(inert(add)).toBe(true);
    expect(add?.getAttribute('aria-describedby')).toBe('next-cockpit-held-full');
    expect(document.querySelector('#next-cockpit-held-full')?.hasAttribute('hidden')).toBe(false);
    await press(add);
    expect(lineBoxes()).toHaveLength(6);
    expect(text('#next-cockpit-cue-status')).toBe(
      'An expected outcome holds six lines. Replace or merge a line to add another.',
    );
    expect(page.posts()).toBe(0);
  });

  it('removes a line and hands focus to the last one, sending nothing', async () => {
    const page = mountSession({
      store: { goal: 'Saved', lines: ['One', 'Two', 'Three'], revision: 2 },
    });
    await settle(page);
    await press(control('held-line-remove', '0'));
    expect(lineBoxes().map((box) => box.value)).toEqual(['Two', 'Three']);
    expect(document.activeElement).toBe(lineBoxes()[1]);
    expect(page.posts()).toBe(0);
    expect(inert(control('held-save'))).toBe(false);
  });

  it('saves the changed lines with each one’s stored position, and not the goal it did not touch', async () => {
    const page = mountSession({
      store: { goal: 'Saved goal', lines: ['One', 'Two'], revision: 2 },
      routes: { '/api/annotate': () => stored(3) },
    });
    await settle(page);
    await press(control('held-line-remove', '0'));
    type(lineBoxes()[0] as HTMLTextAreaElement, 'Two, reworded');
    await press(control('held-line-add'));
    type(lineBoxes()[1] as HTMLTextAreaElement, 'A new line');
    await press(control('held-save'));
    await settle(page);
    const [post] = page.allPosts();
    expect(page.allPosts()).toHaveLength(1);
    expect(post?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      goal: null,
      lines: ['Two, reworded', 'A new line'],
      origins: [1, null],
      expected_revision: 2,
    });
  });

  it('drops a box the reader emptied only at the save, where the store drops it', async () => {
    const page = mountSession({
      store: { goal: 'Saved', lines: ['One', 'Two'], revision: 2 },
      routes: { '/api/annotate': () => stored(3) },
    });
    await settle(page);
    type(lineBoxes()[0] as HTMLTextAreaElement, '');
    expect(lineBoxes()).toHaveLength(2);
    await press(control('held-save'));
    await settle(page);
    expect((page.allPosts()[0]?.body as { lines: string[] }).lines).toEqual(['Two']);
  });

  it('shows where a saved line came from only while the box still holds it', async () => {
    const page = mountSession({
      store: { goal: 'Saved', lines: ['From the agent', 'Typed'], revision: 2 },
      session: { annotation_line_1_source: 'entry', annotation_line_1_source_id: 'f9' },
    });
    await settle(page);
    const source = document.querySelector('[data-next-cockpit-held-line-source="0"]');
    expect(source?.textContent).toBe('added from an entry');
    expect(source?.hasAttribute('data-next-cockpit-held-line-source-stale')).toBe(false);
    type(lineBoxes()[0] as HTMLTextAreaElement, 'Reworded');
    expect(
      document
        .querySelector('[data-next-cockpit-held-line-source="0"]')
        ?.hasAttribute('data-next-cockpit-held-line-source-stale'),
    ).toBe(true);
    expect(document.querySelector('[data-next-cockpit-held-line-source="1"]')).toBeNull();
  });

  it('states a store that could not be read instead of saying nothing was typed', async () => {
    const page = mountSession({ session: {} });
    page.state.data = {
      ...board(),
      annotate_unreadable: 'The annotation store could not be read.',
    };
    await page.poll(page.state.data);
    expect(text('.next-cockpit-held')).toContain('The annotation store could not be read.');
    // Nothing is drafted over a store Save intent could not write.
    expect(document.querySelector('[data-next-cockpit-draft-marks]')).toBeNull();
    expect(json({})).toBeTruthy();
    expect(goalBox().value).toBe('');
  });
});
