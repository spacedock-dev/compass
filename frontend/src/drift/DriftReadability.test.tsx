import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { feedbackSummary } from '../intent/sentences';
import { DisclosureParts } from './ReadingControl';
import { byAction, fact, json, mountDrift, press } from './testing';

/* What the Drift pane says after a press, and how the list of what is sent is drawn: short lines with the
   rest behind a mark, and a list with labels in place of a paragraph. */
const LATER = fact('d1', 995, { summary: 'Do it the careful way' });
const session = { annotation_goal_saved_at: 500, annotation_at: 500 };
const unreachable = {
  '/api/direction': () => json({ ok: false, reason: 'out_of_reach' }),
  '/api/annotate': () => json({ ok: true, outcome: 'stored', persisted: true, revision: 4 }),
  '/api/reading': () => json({ ok: true, settled: 'stored', job: { id: 'j9', steps: [] } }),
};
const WHOLE =
  'That direction is beyond the part of the record Compass could search. Nothing was settled and no analysis was started.';

describe('a press that cannot finish', () => {
  it('leaves a short line and an info mark under the button, not the whole sentence', async () => {
    const page = mountDrift({ facts: [LATER], session, routes: unreachable });
    await page.settle();
    await page.settle();
    await press(byAction('direction-keep'));
    await page.settle();
    const button = byAction('direction-keep') as HTMLButtonElement;
    await press(button);
    await page.settle();
    const trigger = button.parentElement?.querySelector('[data-next-action-feedback-short]');
    expect(trigger?.textContent).toBe('Direction out of reach');
    expect(trigger?.querySelector('[data-icon="info"]')).not.toBeNull();
    // Beside the button the whole sentence is only the one a screen reader is given.
    const described = document.getElementById(trigger?.getAttribute('aria-describedby') ?? '');
    expect(described?.textContent).toBe(WHOLE);
    expect(described?.className).toContain('next-visually-hidden');
  });

  it('opens the whole sentence from the mark on a press, which a touch screen can make', async () => {
    const page = mountDrift({ facts: [LATER], session, routes: unreachable });
    await page.settle();
    await page.settle();
    await press(byAction('direction-keep'));
    await page.settle();
    const button = byAction('direction-keep') as HTMLButtonElement;
    await press(button);
    await page.settle();
    const opened = () =>
      [...document.querySelectorAll('[data-slot="popover-content"]')].some(
        (node) => node.textContent === WHOLE && node.hasAttribute('data-open'),
      );
    expect(opened()).toBe(false);
    await press(button.parentElement?.querySelector('[data-next-action-feedback-short]') ?? null);
    expect(opened()).toBe(true);
  });
});

describe('what is sent, where Keep may analyze', () => {
  it('is one click away under "What is sent", not a paragraph under the buttons', async () => {
    const page = mountDrift({ facts: [LATER], session, routes: unreachable });
    await page.settle();
    await page.settle();
    expect(byAction('direction-keep')?.textContent).toBe('Keep my intent and analyze');
    expect(
      document.querySelector('p.next-cockpit-reading-why#next-cockpit-reading-disclosure'),
    ).toBe(null);
    const summary = screen.getByRole('button', { name: /^What is sent/ });
    await press(summary);
    const list = document.querySelector('ul#next-cockpit-reading-disclosure');
    expect([...(list?.querySelectorAll('li') ?? [])].map((li) => li.textContent)).toEqual([
      'Your saved words.',
      'The agent messages.',
    ]);
  });
});

describe('a Keep that settles but does not analyze', () => {
  it('does not call it plainly kept when a reason follows', () => {
    expect(
      feedbackSummary(
        'Kept your intent and settled the direction. No analysis was started. The daily reading limit is reached. Try again after 09:00.',
      ),
    ).toBe('Kept, not analyzed');
    expect(
      feedbackSummary('Kept your intent and settled all 3 directions. No analysis was started.'),
    ).toBe('Intent kept');
  });
});

describe('Keep and analyze, described', () => {
  it('points its description at the list of what is sent, which holds the server parts', async () => {
    const page = mountDrift({ facts: [LATER], session, routes: unreachable });
    await page.settle();
    await page.settle();
    const keep = byAction('direction-keep') as HTMLButtonElement;
    const described = document.getElementById(keep.getAttribute('aria-describedby') ?? '');
    expect(described?.tagName).toBe('UL');
    expect(described?.textContent).toContain('Your saved words.');
    expect(document.querySelectorAll('#next-cockpit-reading-disclosure')).toHaveLength(1);
  });
});

describe('the list of what is sent', () => {
  const parts = [
    "This session's own harness reads it.",
    'Sent: your goal and a bounded set of the includes entries.',
    'Tool output included: a check’s command.',
    'To: Anthropic, off this machine, with credential shapes redacted.',
  ];

  it('draws a label in weight and the rest after it, without changing a word or the order', () => {
    const { container } = render(<DisclosureParts parts={parts} id="x" />);
    const items = [...container.querySelectorAll('li')];
    expect(items.map((li) => li.textContent)).toEqual(parts);
    expect(items.map((li) => li.querySelector('strong')?.textContent ?? null)).toEqual([
      null,
      'Sent:',
      'Tool output included:',
      'To:',
    ]);
  });

  it('draws a whole paragraph from an older route as one item, with no label cut out of a sentence', () => {
    const whole = 'Sent: an older route sent this as one string, so Sent is not a label here.';
    const { container } = render(<DisclosureParts parts={[whole]} id="y" />);
    expect(container.querySelectorAll('li')).toHaveLength(1);
    expect(container.querySelector('strong')).toBeNull();
  });
});

describe('the short line for a press that cannot finish', () => {
  it('names the cause in a few words for each answer the page knows', () => {
    expect(feedbackSummary(WHOLE)).toBe('Direction out of reach');
    expect(
      feedbackSummary(
        'That direction could not be verified as later than your intent in the current record. Your goal has not changed.',
      ),
    ).toBe('Direction unverified');
    expect(
      feedbackSummary(
        'The session wrote to its record while Compass was reading it. Press again. No outcome line was added.',
      ),
    ).toBe('Record changed, press again');
    expect(
      feedbackSummary('Kept your intent and settled the direction. No analysis was started.'),
    ).toBe('Intent kept');
  });

  it('keeps the first sentence of an answer it does not know, cut at a word when it is long', () => {
    expect(feedbackSummary('Something small happened. And then more.')).toBe(
      'Something small happened.',
    );
    const long = feedbackSummary(
      'A very long first sentence that goes on well past the room the line has for it. Then another.',
    );
    expect(long.length).toBeLessThanOrEqual(45);
    expect(long.endsWith('…')).toBe(true);
    expect(long).not.toMatch(/\s…$/);
  });
});
