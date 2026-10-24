import { describe, expect, it } from 'vitest';
import { capLine, capReset, readingCap } from './route';
import { mountDrift, textOf } from './testing';

/* The analysis budget is said only once it is spent, and then at the top of the session page. */
const local = (h: number, m: number, dayOffset = 0) =>
  new Date(2026, 9, 16 + dayOffset, h, m).getTime() / 1000;

describe('the analysis budget', () => {
  it('is silent under the cap and names the limit and the reset once it is spent', () => {
    expect(readingCap({ reading: { used: 99, limit: 100 } })).toBeNull();
    expect(
      readingCap({ reading: { reason: 'model-calls-paused', used: 3, limit: 100 } }),
    ).toBeNull();
    expect(readingCap({})).toBeNull();
    const spent = readingCap({
      reading: { reason: 'daily-cap', used: 100, limit: 100, retry_at: local(9, 38) },
    });
    expect(spent).toEqual({ limit: 100, retryAt: local(9, 38) });
    // A count at the limit is spent even where the reason names something that outranks it.
    expect(readingCap({ reading: { reason: 'run-disabled', used: 100, limit: 100 } })).toEqual({
      limit: 100,
      retryAt: null,
    });
  });

  it('says the reset as a local time, and says tomorrow when it is', () => {
    const now = local(8, 0) * 1000;
    const today = capReset(local(9, 38), now);
    expect(today).toMatch(/09:38|9:38/);
    expect(today).not.toContain('tomorrow');
    expect(capReset(local(7, 15, 1), now)).toMatch(/tomorrow$/);
    expect(capLine({ limit: 100, retryAt: local(9, 38) }, now)).toBe(
      `You’ve reached the limit of 100 drift analyses for the past 24 hours. You can analyze again at ${today}.`,
    );
    expect(capLine({ limit: 100, retryAt: null }, now)).toBe(
      'You’ve reached the limit of 100 drift analyses for the past 24 hours.',
    );
  });

  it('draws nothing on the session page while budget is left', async () => {
    const under = mountDrift({ payload: { reading: { used: 1, limit: 100 } } });
    await under.settle();
    expect(document.querySelector('[data-next-reading-cap]')).toBeNull();
  });

  it('draws the banner first on the session page when the budget is spent', async () => {
    const page = mountDrift({
      payload: {
        reading: { reason: 'daily-cap', used: 100, limit: 100, retry_at: local(9, 38) },
      },
    });
    await page.settle();
    const banner = document.querySelector('[data-next-reading-cap]') as HTMLElement;
    expect(banner).not.toBeNull();
    expect(banner.getAttribute('role')).toBe('status');
    expect(textOf('[data-next-reading-cap]')).toMatch(
      /^You’ve reached the limit of 100 drift analyses for the past 24 hours\. You can analyze again at /,
    );
    // First in the article, above the header and both columns.
    expect(banner.parentElement?.firstElementChild).toBe(banner);
    expect(banner.parentElement?.hasAttribute('data-next-session-detail')).toBe(true);
  });
});
