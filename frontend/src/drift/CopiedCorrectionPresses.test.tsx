import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { byAction, check, json, mountDrift, press, readingPosts } from './testing';

/* The path from the Sessions list to a copied correction, held at its measured length. The first-analysis
   budget (docs/design-frontend-migration.md, "The first analysis click budget") stops at the analysis; this is
   the other end of the journey, from a stored reading to the words on the clipboard. Browser proofs left the
   gate, so the count lives here, where the pre-PR suite runs it. */
const BUDGET = 3;
const CONTROL = 'button,a,input,textarea,select,summary,[role="button"],[role="option"]';

const ASSESSMENT = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'last-turn',
  criteria: {
    goal: { result: 'departure', cites: ['c1'], detail: 'It stopped.', clause: 'Ship the queue' },
  },
};
const PARTS = ['Your last check failed', { entry: 'c1' }, '. Fix it, then say so.'];
const CORRECTION = 'Your last check failed. Fix it, then say so.';

let counted: string[] = [];
let stop: (() => void) | undefined;
afterEach(() => {
  stop?.();
  counted = [];
});

/* An activation is a click that lands on something a reader can press. Focus and typing are not counted, the
   same rule the first-analysis budget applies. */
function count(): void {
  const listener = (event: Event) => {
    const control = (event.target as Element | null)?.closest(CONTROL);
    if (control)
      counted.push(
        control.getAttribute('data-next-cockpit-action') ||
          control.getAttribute('aria-label') ||
          control.textContent?.trim() ||
          control.tagName,
      );
  };
  document.addEventListener('click', listener, true);
  stop = () => document.removeEventListener('click', listener, true);
}

describe('A copied correction from a Sessions row', () => {
  it('takes three presses and asks no model', async () => {
    const page = mountDrift({
      hash: '#n=sessions',
      session: { annotation_assessment: ASSESSMENT, annotation_window_start: 100 },
      facts: [check('c1', 500, 'failed', { result_source: 'failed flag' })],
      routes: {
        '/api/correction': () => json({ ok: true, parts: PARTS }),
        '/api/correction/copied': () => json({ ok: true }),
      },
    });
    await page.settle();
    await page.settle();
    count();

    await press(screen.getByRole('link', { name: 'Ship the queue' }));
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    await press(byAction('correction-copy'));
    await page.settle();

    expect(page.written).toEqual([CORRECTION]);
    expect(counted).toEqual(['Ship the queue', 'steer-back', 'correction-copy']);
    expect(counted.length).toBeLessThanOrEqual(BUDGET);
    expect(readingPosts(page)).toEqual([]);
    const posts = page.state.requests.filter((r) => r.method === 'POST').map((r) => r.path);
    expect(posts).toEqual(['/api/correction', '/api/correction/copied']);
  });
});
