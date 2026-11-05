import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { SummaryPage, collectedPartialSummary, script } from '../../stories/summary.scenario';

beforeEach(() => vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true));

it.each([true, false, null])(
  'separates source collection (%s), summary windows and freshness',
  async (complete) => {
    const summary = collectedPartialSummary();
    render(<SummaryPage summary={{ ...summary, coverage: { ...summary.coverage, complete } }} />);
    const region = await screen.findByRole('region', { name: 'What the session has done' });
    const box = within(region);
    await box.findByText(
      'Compass could not read the whole record now, so it cannot tell whether this summary is current.',
    );
    expect(region.querySelector('[data-next-summary-reason="ceiling"]')?.textContent).toContain(
      'parts after it were not summarized',
    );
    expect(region.querySelector('[data-next-summary-reason="ceiling"]')?.textContent).toContain(
      '2 finished parts of 3',
    );
    expect(
      Boolean(
        box.queryByText(
          'Source collection finished for this summary. Some parts were not summarized.',
        ),
      ),
    ).toBe(complete === true);
    expect(region.querySelector('[data-next-summary-gap="ceiling"]')?.textContent).toContain(
      'This part was not summarized',
    );
    expect(region.textContent).toContain(
      'Some fragments were not summarized; citations still open the original entries.',
    );
    expect(region.textContent).toContain('full message coverage was not recorded');
    expect(
      region.querySelector('[data-next-summary] [data-next-outline-entry="a1"]'),
    ).not.toBeNull();
    expect(script.posts).toEqual([]);
  },
);
