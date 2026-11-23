import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LEDE, SummaryPage, block, bullet, storedSummary } from '../../stories/summary.scenario';

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: true })),
  );
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    value: vi.fn(),
    configurable: true,
  });
});

describe('the lede of a stored summary', () => {
  it.each([
    ['opening paragraph', /cited for the opening summary/, 'p1'],
    ['phase bullet', /cited for “.*pytest/i, 'c1'],
  ] as const)('keeps the entry reached from a summary %s in Cited', async (_surface, label, id) => {
    render(<SummaryPage summary={storedSummary()} />);
    const region = await screen.findByRole('region', { name: 'What the session has done' });
    if (id === 'c1') {
      const phase = await waitFor(() => {
        const trigger = region.querySelector(
          '[data-next-summary-phase] [data-slot="accordion-trigger"]',
        );
        if (!trigger) throw new Error('Missing phase trigger');
        return trigger;
      });
      fireEvent.click(phase);
    }
    const chip = await waitFor(() => {
      const target = within(region)
        .getAllByRole('link', { name: label })
        .find((link) => link.getAttribute('data-next-outline-entry') === id);
      if (!target) throw new Error('Missing citation');
      return target;
    });
    fireEvent.click(chip);
    fireEvent.click(await screen.findByRole('link', { name: 'See in context of the session' }));
    const log = await screen.findByRole('tabpanel', { name: 'Activity log' });
    const row = () => log.querySelector(`[data-next-entry-id="${id}"]`);
    await waitFor(() => expect(document.activeElement).toBe(row()));
    fireEvent.click(within(log).getByRole('button', { name: 'Cited' }));
    expect(row()).toBeVisible();
  });

  it.each([
    ['All', 'All'],
    ['Commands', 'Commands'],
    ['You', 'All'],
  ])('reveals the middle check from %s and selects %s', async (before, after) => {
    render(
      <SummaryPage
        foldedChecks
        summary={storedSummary({ lede: { text: LEDE, cites: ['fold-2'] } })}
      />,
    );
    const region = await screen.findByRole('region', { name: 'What the session has done' });
    const chip = await within(region).findByRole('link', { name: /cited for the opening summary/ });
    fireEvent.click(await screen.findByRole('button', { name: 'Show technical details' }));
    const log = await screen.findByRole('tabpanel', { name: 'Activity log' });
    fireEvent.click(within(log).getByRole('button', { name: before }));
    const row = () => log.querySelector('[data-next-entry-id="fold-2"]');
    if (before === 'All') expect(row()?.closest('[hidden]')).not.toBeNull();
    if (before === 'Commands') expect(row()).toBeVisible();
    fireEvent.click(chip);
    fireEvent.click(await screen.findByRole('link', { name: 'See in context of the session' }));
    await waitFor(() => {
      expect(row()).toBeVisible();
      expect(document.activeElement).toBe(row());
    });
    expect(within(log).getByRole('button', { name: after, pressed: true })).toBeVisible();
  });

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
      '1 cited entry is an earlier check or file that Activity log does not list, so it cannot be opened from here.',
    );
  });
});
