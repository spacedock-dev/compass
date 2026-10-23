import { act, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BOARD, mountShell } from '../shell/testing';
import { SAMPLE_FRAGMENT } from './ids';

/* The sample is view only and holds no lease: the Live monitor shows as on, so its estimate is drawn as it
   is for a reader who turned it on, and no lease call is ever made, however long the page stays or whatever
   is pressed. */
const asked: string[] = [];
vi.mock('./sampleFetch', async (original) => {
  const real = await original<typeof import('./sampleFetch')>();
  return {
    ...real,
    createSampleFetch: (...args: Parameters<typeof real.createSampleFetch>) => {
      const inner = real.createSampleFetch(...args);
      return (url: string, init?: RequestInit) => {
        asked.push(url);
        return inner(url, init);
      };
    },
  };
});

describe('the sample session and the Live monitor', () => {
  it('shows the switch on, lets a press show and hide the level, and never calls the lease route', async () => {
    const page = mountShell({ hash: SAMPLE_FRAGMENT, data: BOARD });
    await page.settle();
    await waitFor(() => expect(document.querySelector('[data-next-entry-id]')).not.toBeNull());
    const toggle = document.querySelector(
      '[data-next-cockpit-action="live-monitor"]',
    ) as HTMLButtonElement;
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    // Its press is live, as it always was: it shows or hides the level, and nothing is sent.
    await act(async () => {
      fireEvent.click(toggle);
    });
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    await act(async () => {
      fireEvent.click(toggle);
    });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    await page.settle();
    expect(asked.length).toBeGreaterThan(0);
    expect(asked.filter((url) => url.startsWith('/api/live-monitor'))).toEqual([]);
  });
});
