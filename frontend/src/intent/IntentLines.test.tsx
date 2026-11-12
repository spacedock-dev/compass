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
  it('offers one empty box where nothing is saved, and adding focuses it instead of stacking a blank', async () => {
    const page = mountSession({ store: { goal: 'Saved', revision: 1 } });
    await settle(page);
    expect(lineBoxes()).toHaveLength(1);
    expect(lineBoxes()[0]?.value).toBe('');
    expect(control('held-line-add')).not.toBeNull();
    await press(control('held-line-add'));
    expect(lineBoxes()).toHaveLength(1);
    expect(document.activeElement).toBe(lineBoxes()[0]);
    type(lineBoxes()[0] as HTMLTextAreaElement, 'A check');
    await press(control('held-line-add'));
    expect(lineBoxes()).toHaveLength(2);
    expect(document.activeElement).toBe(lineBoxes()[1]);
    await press(control('held-line-add'));
    expect(lineBoxes()).toHaveLength(2);
    expect(lineBoxes().map((box) => box.value)).toEqual(['A check', '']);
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

describe('an over-limit paste stays visible', () => {
  it('keeps 900 characters, blocks save, and unblocks at 800 without a reload', async () => {
    const page = mountSession({ store: { goal: 'Saved', lines: ['Original'], revision: 2 } });
    await settle(page);
    type(lineBoxes()[0] as HTMLTextAreaElement, 'l'.repeat(900));
    expect(lineBoxes()[0]?.value).toHaveLength(900);
    expect(lineBoxes()[0]?.hasAttribute('maxlength')).toBe(false);
    expect(text('[data-next-cockpit-held-line-count="0"]')).toBe('900 / 800');
    expect(
      document.querySelector('[data-next-cockpit-held-line-count="0"]')?.getAttribute('data-over'),
    ).toBe('true');
    expect(text('.next-cockpit-held')).toContain('Line 1 is 900 characters; the limit is 800.');
    expect(inert(control('held-save'))).toBe(true);
    await press(control('held-save'));
    expect(page.posts()).toBe(0);
    type(lineBoxes()[0] as HTMLTextAreaElement, 'l'.repeat(800));
    expect(inert(control('held-save'))).toBe(false);
    expect(text('.next-cockpit-held')).not.toContain('Line 1 is 900');
    fireEvent.keyDown(lineBoxes()[0] as HTMLTextAreaElement, { key: 'Escape' });
    await settle(page);
    expect(lineBoxes()[0]?.value).toBe('Original');
  });

  it('says the over-limit sentence once as a box goes over, not on every keystroke past it', async () => {
    const page = mountSession({ store: { goal: 'Saved', lines: ['Original'], revision: 2 } });
    await settle(page);
    const region = document.querySelector('#next-cockpit-cue-status') as HTMLElement;
    const line = () => lineBoxes()[0] as HTMLTextAreaElement;
    type(line(), 'l'.repeat(800));
    expect(region.textContent).toBe('');
    type(line(), 'l'.repeat(900));
    expect(region.textContent).toBe('Line 1 is 900 characters; the limit is 800.');
    region.textContent = '';
    type(line(), 'l'.repeat(1286));
    expect(region.textContent).toBe('');
    type(line(), 'l'.repeat(10));
    type(line(), 'l'.repeat(900));
    expect(region.textContent).toBe('Line 1 is 900 characters; the limit is 800.');
    region.textContent = '';
    type(goalBox(), 'g'.repeat(1100));
    expect(region.textContent).toBe('The goal is 1,100 characters; the limit is 1,000.');
    region.textContent = '';
    type(goalBox(), 'g'.repeat(1101));
    expect(region.textContent).toBe('');
  });

  it('counts 800 emoji as 800 characters, as the store does', async () => {
    const page = mountSession({ store: { goal: 'Saved', lines: ['Original'], revision: 2 } });
    await settle(page);
    type(lineBoxes()[0] as HTMLTextAreaElement, '😀'.repeat(800));
    expect(lineBoxes()[0]?.value).toBe('😀'.repeat(800));
    expect(text('[data-next-cockpit-held-line-count="0"]')).toBe('800 / 800');
    expect(inert(control('held-save'))).toBe(false);
  });

  it.each([
    [
      { code: 'line_too_long', line: 1, length: 900, cap: 800 },
      'Not saved: line 1 is 900 characters; the limit is 800.',
    ],
    [{ code: 'too_many_lines', count: 7, max: 6 }, 'Not saved: at most 6 lines.'],
    [{ code: 'unmatchable_session' }, 'Not saved: that session id is not one the board shows.'],
  ])('shows the reason a server refused a save', async (reason, sentence) => {
    const page = mountSession({
      store: { goal: 'Saved', lines: ['Original'], revision: 2 },
      routes: {
        '/api/annotate': () => json({ ok: true, outcome: 'refused', persisted: false, reason }),
      },
    });
    await settle(page);
    type(lineBoxes()[0] as HTMLTextAreaElement, 'Changed');
    await press(control('held-save'));
    await settle(page);
    expect(text('.next-cockpit-held-footer .next-cockpit-held-cue')).toBe(sentence);
    expect(lineBoxes()[0]?.value).toBe('Changed');
  });
});

describe('a refused adoption also names its reason', () => {
  it('keeps the drafted goal and shows the refused identity', async () => {
    const page = mountSession({
      routes: {
        '/api/annotate': () =>
          json({
            ok: true,
            outcome: 'refused',
            persisted: false,
            reason: { code: 'unmatchable_session' },
          }),
      },
    });
    await settle(page);
    await press(control('held-save'));
    await settle(page);
    expect(text('.next-cockpit-held-footer .next-cockpit-held-cue')).toBe(
      'Not saved: that session id is not one the board shows.',
    );
    expect(goalBox().value).toBe('Ship the queue worker');
  });
});
