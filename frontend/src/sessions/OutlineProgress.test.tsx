import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PARTIAL_SUMMARY_PLAN, progressiveOutline } from '../../stories/outline.scenario';
import {
  SummaryPage,
  block,
  gap,
  SECOND_PHASE,
  storedSummary,
  poll,
  script,
} from '../../stories/summary.scenario';

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    value: vi.fn(),
    configurable: true,
  });
});

describe('a reader watching automatic outline progress', () => {
  it('keeps a saved summary omission independent of a partial outline', async () => {
    render(
      <SummaryPage
        outline={progressiveOutline(0)}
        summary={storedSummary({
          state: 'partial',
          reason: 'gaps',
          starts_at: 'p2',
          blocks: [gap('p1', 'c2', 4, 'before_window'), block('p2', 'a2', 2, [SECOND_PHASE])],
        })}
      />,
    );
    const region = await screen.findByRole('region', { name: 'What the session has done' });
    const box = within(region);
    await box.findByText(/^This summary starts at #3/);
    const disclosure = box.getByRole('button', { name: "Compass's outline of this session" });
    fireEvent.click(disclosure);
    await box.findByText(
      'This outline is partial. Compass will try to read more on later updates.',
    );
    expect(region.textContent).not.toMatch(/outline covers/i);
    expect(region.querySelector('[data-next-summary-gap="before_window"]')?.textContent).toContain(
      'This part was not summarized',
    );
    expect(
      region.querySelector('[data-next-summary] [data-next-outline-entry="p2"]'),
    ).not.toBeNull();
    expect(script.posts).toEqual([]);
  });

  it.each([false, null])(
    'keeps the summary size partial when coverage is %s without unread ranges',
    async (complete) => {
      const outline = progressiveOutline(2);
      render(
        <SummaryPage
          ended={false}
          outline={{
            ...outline,
            more_blocks: 0,
            coverage: { ...outline.coverage, complete, unread: [] },
          }}
          summary={PARTIAL_SUMMARY_PLAN}
        />,
      );
      const region = await screen.findByRole('region', { name: 'What the session has done' });
      await within(region).findByText('Check the retry tests before continuing.');
      const size = region.querySelector('[data-next-summary-size]')?.textContent;
      expect(size).toMatch(/^More than /);
      expect(size).toContain('Compass plans the parts when the summary starts');
      expect(size).not.toContain('in 2 parts');
      expect(region.querySelectorAll('[data-next-outline-block]')).toHaveLength(3);
      expect(script.posts).toEqual([]);
    },
  );

  it('keeps the opening and focused disclosure while the middle appears and coverage becomes complete', async () => {
    render(
      <SummaryPage ended={false} outline={progressiveOutline(0)} summary={PARTIAL_SUMMARY_PLAN} />,
    );
    const region = await screen.findByRole('region', { name: 'What the session has done' });
    const box = within(region);
    await box.findByText(
      'This outline is partial. Compass will try to read more on later updates.',
    );
    const opening = box.getByText('Add retry with backoff to the webhook handler.');
    expect(box.getByText('Keep the diff small and leave the tests alone.')).toBeVisible();
    expect(region.querySelectorAll('[data-next-outline-block]')).toHaveLength(2);
    const full = screen.getByRole('button', { name: 'Full activity' });
    await act(async () => {
      fireEvent.click(full);
      full.focus();
    });
    script.outline = progressiveOutline(1);
    await act(async () => {
      await poll();
    });
    await box.findByText('Check the retry tests before continuing.');
    expect(box.getByText('The agent ran 1 check.')).toBeVisible();
    expect(
      box.getByText('This outline is partial. Compass will try to read more on later updates.'),
    ).toBeVisible();
    expect(box.getByText('Add retry with backoff to the webhook handler.')).toBe(opening);
    expect(full.getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(full);
    script.outline = progressiveOutline(2);
    await act(async () => {
      await poll();
    });
    await waitFor(() => expect(box.queryByText(/This outline is partial/)).toBeNull());
    expect(box.getByText('The agent ran 2 checks.')).toBeVisible();
    expect(region.querySelectorAll('[data-next-outline-block]')).toHaveLength(3);
    expect(box.getByText('2 earlier parts of this session are not shown here.')).toBeVisible();
    expect(region.querySelector('[data-next-summary-size]')?.textContent).toContain(
      'Compass plans the parts when the summary starts',
    );
    expect(region.textContent).not.toMatch(
      /Full activity lists every entry|first message and the newest/,
    );
    expect(full.getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(full);
    expect(script.posts).toEqual([]);
  });
});
