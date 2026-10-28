import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  NOTICE,
  SummaryPage,
  defaultAnswer,
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

/* Every query that waits runs before its `act`, never inside one: Testing Library turns IS_REACT_ACT_ENVIRONMENT off
   while a `findBy` polls, and a Base UI animation-frame update landing in that window inside an open act scope made
   React warn that the environment does not support act (measured on CI, 2026-10-28). */

/* The copy inside "What is sent", which these tests open: the Drift card head holds another
   (usability review, 2026-10-20). */
const popoverPause = async (): Promise<HTMLElement> =>
  (await screen.findAllByRole('button', { name: 'Pause model calls' })).find(
    (button) => !button.matches('[data-next-focus^="reading-off-head:"]'),
  ) as HTMLElement;

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
    const pause = await popoverPause();
    await act(async () => {
      fireEvent.click(pause);
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
    const resume = await screen.findByRole('button', { name: 'Resume model calls' });
    await act(async () => {
      fireEvent.click(resume);
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
    const pause = await popoverPause();
    await act(async () => {
      fireEvent.click(pause);
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

  it('drops a held summary notice when model calls are paused', async () => {
    render(
      <SummaryPage
        ended={false}
        summary={storedSummary({
          out_of_date: {
            kind: 'appended',
            reason: null,
            affected_blocks: [],
            new_entries: 2,
            appendable: true,
            action: 'update',
          },
        })}
        answer={(path, body) =>
          path !== '/api/summary' || 'consent' in body
            ? defaultAnswer(path, body)
            : {
                status: 202,
                body: { ok: true, job: job({ state: 'complete', notice: NOTICE }), notice: NOTICE },
              }
        }
      />,
    );
    const region = await screen.findByRole('region', { name: 'What the session has done' });
    const update = await within(region).findByRole('button', { name: 'Update summary' });
    await act(async () => {
      fireEvent.click(update);
    });
    await waitFor(() => expect(region.querySelector('[data-next-summary-notice]')).not.toBeNull());
    /* The summary stands, so the notice is folded to one line and is not a second "Model request notice"
       region beside the drift card's. */
    expect(region.querySelector('[data-next-summary-notice-folded]')).not.toBeNull();
    expect(within(region).queryByRole('region', { name: /request notice/ })).toBeNull();
    const drift = await screen.findByRole('region', { name: 'Drift' });
    await act(async () => {
      fireEvent.click(within(drift).getByRole('button', { name: /What is sent/ }));
    });
    const pause = await popoverPause();
    await act(async () => {
      fireEvent.click(pause);
    });
    await waitFor(() => expect(within(region).getByText('Model calls are paused')).toBeVisible());
    /* The server cleared every notice with the pause; the tab does not keep drawing one. */
    expect(region.querySelector('[data-next-summary-notice]')).toBeNull();
  });
});
