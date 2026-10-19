import { act, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BOARD, mountShell } from '../shell/testing';
import { SAMPLE_FRAGMENT } from './ids';
import { TOUR } from './tour';

/* The sample session as a new reader meets it: opened by its link, in the page's own Session view, over
   its own shell. The board the page itself is polling has nothing to do with it. */
const mountSample = async () => {
  const page = mountShell({ hash: SAMPLE_FRAGMENT, data: BOARD });
  await page.settle();
  await waitFor(() => expect(document.querySelector('[data-next-entry-id]')).not.toBeNull());
  return page;
};
const marks = () => [...document.querySelectorAll<HTMLElement>('[data-sample-mark]')];
const held = () => document.querySelector('[data-sample-held]')?.textContent ?? '';

describe('the sample session', () => {
  it('says it is a view-only sample and links back to Sessions', async () => {
    await mountSample();
    const banner = document.querySelector('[data-sample-banner]') as HTMLElement;
    expect(banner.textContent).toContain('Sample session (view only)');
    expect(banner.textContent).toContain('Nothing here is saved, sent or run.');
    expect(within(banner).getByRole('link', { name: 'Back to Sessions' })).toHaveProperty(
      'href',
      expect.stringContaining('#n=sessions'),
    );
  });

  it('draws the real Session page over the stored session: its entries, its intent and its reading', async () => {
    await mountSample();
    expect(document.querySelectorAll('[data-next-entry-id]').length).toBeGreaterThanOrEqual(18);
    expect(document.body.textContent).toContain('Resolve the merge conflicts on PR 56');
    expect(document.querySelector('[data-next-drift-level]')?.textContent).toContain('High');
    expect(document.querySelector('[data-next-finding]')).not.toBeNull();
  });

  it('numbers an entry by the message it follows, and keeps the number', async () => {
    await mountSample();
    const numbers = [...document.querySelectorAll('[data-next-entry]')].map((row) =>
      row.getAttribute('data-next-entry'),
    );
    expect(numbers).toContain('1');
    expect(numbers).toContain('18');
    expect(numbers.some((n) => /^\d+\.\d+$/.test(n ?? ''))).toBe(true);
  });

  it('draws every numbered mark once, in the order of the tour', async () => {
    await mountSample();
    expect(marks().map((mark) => mark.getAttribute('data-sample-mark'))).toHaveLength(TOUR.length);
    expect(new Set(marks().map((mark) => mark.getAttribute('data-sample-mark'))).size).toBe(
      TOUR.length,
    );
    for (const mark of marks()) {
      const id = mark.getAttribute('data-sample-mark');
      const n = TOUR.findIndex((note) => note.id === id) + 1;
      expect(mark.getAttribute('aria-label')).toMatch(
        new RegExp(`^Tour ${String(n)} of ${String(TOUR.length)}: `),
      );
    }
  });

  it('opens the words of a note from its mark, and the same words are in the text legend', async () => {
    await mountSample();
    const note = TOUR.find((each) => each.id === 'level');
    const mark = document.querySelector('[data-sample-mark="level"]') as HTMLElement;
    await act(async () => {
      fireEvent.click(mark);
    });
    const popup = [...document.querySelectorAll('[data-slot="popover-content"][data-open]')].find(
      (node) => node.textContent?.includes(note?.body ?? '?'),
    );
    expect(popup).toBeDefined();
    const legend = document.querySelector('[data-sample-banner] details') as HTMLElement;
    for (const each of TOUR) expect(legend.textContent).toContain(each.body);
  });

  it('holds every press that would edit, save or run, and says why', async () => {
    await mountSample();
    const remove = [...document.querySelectorAll('button')].find(
      (button) => button.textContent?.trim() === 'Remove',
    ) as HTMLElement;
    const lines = () => document.querySelectorAll('[data-next-cockpit-held-line]').length;
    const before = lines();
    await act(async () => {
      fireEvent.click(remove);
    });
    expect(lines()).toBe(before);
    expect(held()).toBe('View only: this sample cannot be edited, saved or run.');
    const box = document.querySelector('textarea') as HTMLTextAreaElement;
    const text = box.value;
    const typed = new InputEvent('beforeinput', {
      data: 'x',
      inputType: 'insertText',
      bubbles: true,
      cancelable: true,
    });
    box.dispatchEvent(typed);
    expect(typed.defaultPrevented).toBe(true);
    expect(box.value).toBe(text);
  });

  it('holds a press on Clear in the Intent card, and lets the grouped checks open', async () => {
    await mountSample();
    expect(document.querySelector('[data-next-session-more]')).toBeNull();
    const clear = document.querySelector(
      '[data-next-cockpit-action="held-clear"]',
    ) as HTMLElement | null;
    expect(clear).not.toBeNull();
    const goal = document.querySelector('textarea') as HTMLTextAreaElement;
    const before = goal.value;
    expect(before.length).toBeGreaterThan(0);
    await act(async () => {
      fireEvent.click(clear as HTMLElement);
    });
    expect(goal.value).toBe(before);
    expect(held()).toBe('View only: this sample cannot be edited, saved or run.');
    const checks = document.querySelector('[data-check-run] button') as HTMLElement;
    expect(checks.getAttribute('aria-expanded')).toBe('false');
    await act(async () => {
      fireEvent.click(checks);
    });
    expect(checks.getAttribute('aria-expanded')).toBe('true');
  });

  it('lights up the entries a finding cites when Show cited entries is pressed', async () => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    await mountSample();
    expect(document.querySelectorAll('[data-next-cited]')).toHaveLength(0);
    const jump = document.querySelector('[data-next-finding="goal"]') as HTMLElement;
    await act(async () => {
      fireEvent.click(jump);
    });
    expect(held()).toBe('');
    const cited = [...document.querySelectorAll('[data-next-cited]')];
    expect(cited.length).toBeGreaterThanOrEqual(2);
    for (const row of cited) expect(row.className).toContain('var(--accent)');
  });

  it('composes the stored correction when Steer back is pressed, without sending anything', async () => {
    const page = await mountSample();
    await act(async () => {
      fireEvent.click(
        document.querySelector('[data-next-cockpit-action="steer-back"]') as HTMLElement,
      );
    });
    await waitFor(() => expect(document.body.textContent).toContain('Back to my goal:'));
    expect(held()).toBe('');
    expect(page.posts()).toBe(0);
  });
});

describe('finding the sample', () => {
  it('invites a new reader from the top of the Sessions page, with a link to the sample', async () => {
    const page = mountShell({ hash: '#n=sessions', data: BOARD });
    await page.settle();
    const invite = document.querySelector('[data-sample-invite]') as HTMLElement;
    const link = within(invite).getByRole('link', { name: 'See a sample session (view only)' });
    expect(link.getAttribute('href')).toBe(SAMPLE_FRAGMENT);
  });
});
