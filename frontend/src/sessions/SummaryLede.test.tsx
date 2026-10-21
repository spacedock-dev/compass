import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LEDE, SummaryPage, block, bullet, storedSummary } from '../../stories/summary.scenario';

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    value: vi.fn(),
    configurable: true,
  });
});

describe('the lede of a stored summary', () => {
  it('links a message on an unloaded page that a bullet cites, and counts only what cannot open', async () => {
    render(
      <SummaryPage
        summary={storedSummary({
          lede: { text: LEDE, cites: ['older-message', 'source-check-9'] },
          blocks: [
            block('older-message', 'source-check-9', 2, [
              {
                title: 'Asking for retries',
                bullets: [
                  bullet('Asked for retry with backoff.', 'asked', ['older-message']),
                  bullet(
                    'pytest tests/test_webhook.py reported failed, as the tool reported.',
                    'failed',
                    ['source-check-9'],
                  ),
                ],
              },
            ]),
          ],
        })}
      />,
    );
    const region = await screen.findByRole('region', { name: 'What the session has done' });
    const lede = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-summary-lede]');
      if (!node) throw new Error('no lede');
      return node;
    });
    /* The message id reads older record pages, as the asked bullet's own chip does. */
    expect(
      within(lede).getAllByRole('link', { name: /cited for the opening summary/ }),
    ).toHaveLength(1);
    /* Counted once, at the foot of the summary, and not after the opening. */
    expect(lede.querySelector('[data-next-summary-unlinked]')).toBeNull();
    const notes = region.querySelectorAll('[data-next-summary-unlinked]');
    expect(notes).toHaveLength(1);
    expect(notes[0]?.textContent).toBe(
      '1 cited entry is an earlier check or file that Full activity does not list, so it cannot be opened from here.',
    );
  });
});
