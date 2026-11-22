import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ActivityHead } from './ActivityHead';
import { activityRow } from './activity.test.helper';
import { TooltipProvider } from '../ui/tooltip';

describe('a reader scans the activity head', () => {
  it('reads all result states as short words with the full reported accessible name', () => {
    const rows = [
      activityRow(1),
      activityRow(2, { result: 'passed', resultSource: 'summary' }),
      activityRow(3, {
        result: 'failed',
        resultSource: 'marker',
        earlierFailed: true,
        beforeLastChange: true,
      }),
    ];
    render(
      <TooltipProvider>
        {rows.map((row) => (
          <ActivityHead key={row.entry.id} row={row} />
        ))}
      </TooltipProvider>,
    );
    for (const [name, word] of [
      ['Ran, result not recorded', 'No result'],
      ['Passed, per its summary line', 'Passed'],
      ['Failed, per a failure line in its output', 'Failed'],
      ['Before the last change', ''],
      ['An earlier run failed', ''],
    ] as const) {
      const mark = screen.getByRole('img', { name });
      expect(mark.textContent).toBe(word);
      expect(mark.tabIndex).toBe(-1);
      expect(mark.className).not.toMatch(/hidden|opacity-0|hover:opacity/);
    }
    const unknown = screen.getByRole('img', { name: 'Ran, result not recorded' });
    expect(unknown.querySelector('svg')?.getAttribute('data-icon')).toBe('unrecorded');
    expect(unknown.querySelector('path')?.getAttribute('d')).toBe(
      'M128,20A108,108,0,1,0,236,128,108.12,108.12,0,0,0,128,20Zm0,192a84,84,0,1,1,84-84A84.09,84.09,0,0,1,128,212Z',
    );
  });
  it('still reads time not published in the head when no source time exists', () => {
    const { container } = render(
      <TooltipProvider>
        <ActivityHead row={{ ...activityRow(1), at: 'time not published' }} />
      </TooltipProvider>,
    );
    expect(
      container.querySelector('.next-cockpit-work-head .next-cockpit-work-at')?.textContent,
    ).toBe('time not published');
  });
});
