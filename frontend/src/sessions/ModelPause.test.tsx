import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SummaryPage,
  grant,
  job,
  poll,
  script,
  storedSummary,
} from '../../stories/summary.scenario';

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    value: vi.fn(),
    configurable: true,
  });
});

describe('the summaries switch is nested under Pause model calls', () => {
  it.each([true, false])('keeps the summaries answer %s through pause and resume', async (off) => {
    render(
      <SummaryPage
        ended={false}
        grant={grant({ off, consent: !off, reason: off ? 'summaries-off' : '' })}
      />,
    );
    const drift = await screen.findByRole('region', { name: 'Drift' });
    await act(async () => {
      fireEvent.click(within(drift).getByRole('button', { name: /What is sent/ }));
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'Pause model calls' }));
    });
    const region = await screen.findByRole('region', { name: 'What the session has done' });
    const label = off ? 'Turn summaries on' : 'Turn off summaries';
    await waitFor(() =>
      expect(
        within(region).getByRole('button', { name: label }).getAttribute('aria-disabled'),
      ).toBe('true'),
    );
    expect(within(region).getByText('Model calls are paused')).toBeVisible();
    await act(async () => {
      fireEvent.click(within(region).getByRole('button', { name: label }));
    });
    expect(script.posts).toHaveLength(0);
    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'Resume model calls' }));
    });
    await waitFor(() => expect(script.paused).toBe(false));
    await act(async () => {
      await poll();
    });
    const sent = within(region).queryByRole('button', { name: /What is sent/ });
    if (sent)
      await act(async () => {
        fireEvent.click(sent);
      });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: label }).getAttribute('aria-disabled')).not.toBe(
        'true',
      ),
    );
    expect(script.grant?.['off']).toBe(off);
    expect(script.posts).toHaveLength(0);
    expect(script.masterPosts).toEqual([
      { consent: 'off', press: true, observer_model: 1 },
      { consent: 'on', press: true, observer_model: 1 },
    ]);
  });

  it('disables the summary switch when a running summary stops for the master pause', async () => {
    render(<SummaryPage summary={storedSummary({ job: job({ part: 1 }) })} />);
    const drift = await screen.findByRole('region', { name: 'Drift' });
    await act(async () => {
      fireEvent.click(within(drift).getByRole('button', { name: /What is sent/ }));
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'Pause model calls' }));
    });
    const region = await screen.findByRole('region', { name: 'What the session has done' });
    await waitFor(() =>
      expect(script.summary?.['job']).toMatchObject({
        state: 'stopping',
        reason: 'model-calls-paused',
      }),
    );
    await waitFor(() =>
      expect(
        within(region)
          .getByRole('button', { name: 'Turn off summaries' })
          .getAttribute('aria-disabled'),
      ).toBe('true'),
    );
    expect(within(region).getByText('Model calls are paused')).toBeVisible();
    expect(script.posts).toHaveLength(0);
  });
});
